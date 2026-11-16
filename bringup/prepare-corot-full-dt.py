#!/usr/bin/env python3
"""Prepare the full real corot display topology with proven mainline UFS capture."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import libfdt
from corot_mmqos import normalize_mmqos_paths

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stock',type=Path,required=True)
parser.add_argument('--core',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--tag',required=True)
args=parser.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9-]+',args.tag):
 raise SystemExit('Invalid tag')
stock=args.stock.read_bytes()
fdt=libfdt.Fdt(stock)
fdt.resize(len(stock)+65536)
core=libfdt.Fdt(args.core.read_bytes())
manifest={'tag':args.tag,'stock_sha256':hashlib.sha256(stock).hexdigest(),'core_sha256':hashlib.sha256(args.core.read_bytes()).hexdigest(),'serial':'UGEEOVYX4TZ9EE45','slot':'a','changes':[]}
def props(tree,path):
 node=tree.path_offset(path)
 result={}
 offset=tree.first_property_offset(node,quiet=(libfdt.NOTFOUND,))
 while offset>=0:
  p=tree.get_property_by_offset(offset)
  result[p.name]=bytes(p)
  offset=tree.next_property_offset(offset,quiet=(libfdt.NOTFOUND,))
 return result
def setprop(path,name,data):
 fdt.setprop(fdt.path_offset(path),name,data)
def remove(path,name):
 fdt.delprop(fdt.path_offset(path),name,quiet=(libfdt.NOTFOUND,))
def string(value):return value.encode()+b'\0'
def cells(*values):return struct.pack('>'+('I'*len(values)),*values)
compatible=bytes(fdt.getprop(0,'compatible'))
if b'xiaomi,corot\0' not in compatible:
 setprop('/','compatible',b'xiaomi,corot\0'+compatible)
setprop('/','model',string('Redmi K60 Ultra (corot, MT6985)'))
chosen=props(fdt,'/chosen')
bootargs=chosen.get('bootargs',b'').rstrip(b'\0').decode()
bootargs=' '.join(option for option in bootargs.split() if not option.startswith(('corot_test=', 'ramoops.')))
for option in ('clk_ignore_unused','pd_ignore_unused','printk.devkmsg=on','corot_test='+args.tag):
 if option not in bootargs:
  bootargs+=' '+option
setprop('/chosen','bootargs',string(bootargs))
# Preserve initrd addresses supplied by the current boot, already scanned by
# setup_machine_fdt(), rather than replacing them with a previous Android boot.
for name in ('linux,initrd-start','linux,initrd-end','kaslr-seed','rng-seed'):
 remove('/chosen',name)
manifest['changes'].append('Preserved full stock display, clock, GCE, SMI and IOMMU topology; removed captured initrd pointers')
# The secondary host is the optional IRIS processing path. Primary panel
# output and the dual display processing pipes remain represented in full.
for path in ('/dsi1@1420d000','/dsi@1420d000'):
 if fdt.path_offset(path,quiet=(libfdt.NOTFOUND,))>=0:
  setprop(path,'status',string('disabled'))
  manifest['changes'].append('Disabled secondary IRIS DSI host: '+path)
for path in ('/dispsys-config@14000000',):
 if fdt.path_offset(path,quiet=(libfdt.NOTFOUND,))>=0:
  for name in ('enable-secondary-path','enable-discrete-path'):
   remove(path,name)
# Normalize the ESD GPIO property to the descriptor-based panel interface;
# IRQ trigger flags are configured separately in the complete panel driver.
for path in ('/dsi0@1400d000/panel1@0','/dsi0@1400d000/panel2@0'):
 if fdt.path_offset(path,quiet=(libfdt.NOTFOUND,))<0:
  continue
 properties=props(fdt,path)
 old=properties.get('mi,esd-err-irq-gpio')
 if old:
  values=list(struct.unpack('>'+('I'*(len(old)//4)),old))
  values[-1]=0
  setprop(path,'esd-gpios',cells(*values))
# Keep the already tested minimal UFS binding so the log catcher can write
# its UUID-identified cust log while the new display topology is evaluated.
ufs='/soc/ufshci@112b0000'
old=props(fdt,ufs)
for name in old:
 if name not in ('phandle','linux,phandle'):
  remove(ufs,name)
for name,data in props(core,'/ufshci@112b0000').items():
 if name in ('phandle','linux,phandle','interrupt-parent'):
  continue
 if name=='interrupts':
  values=struct.unpack('>'+('I'*(len(data)//4)),data)
  assert len(values)==3
  data=cells(*values,0)
 setprop(ufs,name,data)
manifest['changes'].append('Kept proven mainline UFS register/IRQ binding and disabled MCQ for log capture')
# A concrete ramoops device supplies crash capture in addition to expdb.
reserved='/reserved-memory'
parent=fdt.path_offset(reserved)
node=fdt.first_subnode(parent,quiet=(libfdt.NOTFOUND,))
ram_path=None
while node>=0:
 try:
  reg=bytes(fdt.getprop(node,'reg'))
  if len(reg)>=16 and struct.unpack('>Q',reg[:8])[0]==0x48090000:
   ram_path=fdt.get_path(node)
   break
 except libfdt.FdtException:
  pass
 node=fdt.next_subnode(node,quiet=(libfdt.NOTFOUND,))
if not ram_path:
 fdt.add_subnode(fdt.path_offset(reserved),'ramoops@48090000')
 ram_path=reserved+'/ramoops@48090000'
 setprop(ram_path,'reg',cells(0,0x48090000,0,0xe0000))
setprop(ram_path,'compatible',string('ramoops'))
for name,value in (('record-size',0x10000),('console-size',0x40000),('pmsg-size',0x10000)):
 setprop(ram_path,name,cells(value))
setprop(ram_path,'no-map',b'')
manifest['changes'].append('Configured actual ramoops region at 0x48090000; removed duplicate command-line ramoops device')
mmqos_paths=normalize_mmqos_paths(fdt,Path(__file__).resolve().parent.parent/'linux-native')
manifest['changes'].append('Corrected '+str(mmqos_paths['corrected_paths'])+' MMQOS endpoints to their table- and physical-SMI-proven common')
manifest['mmqos_paths']={'validated':mmqos_paths['validated_paths'],'corrected':mmqos_paths['corrected_paths']}
fdt.pack()
args.output.mkdir(parents=True,exist_ok=True)
binary=bytes(fdt.as_bytearray())
(args.output/'mt6985-xiaomi-corot.dtb').write_bytes(binary)
result=subprocess.run(['dtc','-q','-I','dtb','-O','dts'],input=binary,check=True,capture_output=True)
(args.output/'mt6985-xiaomi-corot.dts').write_bytes(result.stdout)
manifest['output_sha256']=hashlib.sha256(binary).hexdigest()
(args.output/'mmqos-paths.json').write_text(json.dumps(mmqos_paths,indent=2)+'\n')
(args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Prepared full real corot topology:',args.output)
