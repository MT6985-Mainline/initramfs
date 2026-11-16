#!/usr/bin/env python3
"""Build a bounded log ramdisk and pack corot Android v4 images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--tag', required=True)
args = parser.parse_args()
if not args.tag.replace('-', '').isalnum():
    raise SystemExit('Invalid tag')
root = Path(__file__).resolve().parent.parent
out = root / 'images' / args.tag
out.mkdir(parents=True, exist_ok=True)
temporary = out / 'pack-scratch'
temporary.mkdir(parents=True, exist_ok=True)
os.environ['TMPDIR'] = str(temporary.resolve())
source = (root / 'initramfs/src/init-log.c').read_text()
if '0xa1b2c3d4UL' not in source or 'capture_deadline.tv_sec += 120' not in source:
    raise SystemExit('Log ramdisk must have the correct reboot opcode and bounded capture')
init_source = out / 'init-log.c'
init_source.write_text(source)
fb_source = out / 'fb-test.c'
fb_source.write_text((root / 'initramfs/src/fb-test.c').read_text())
subprocess.run(['aarch64-linux-gnu-gcc', '-nostdlib', '-static', '-fno-stack-protector', '-fno-builtin', '-ffreestanding', '-Os', '-Wl,-e,_start', '-o', str(out / 'init'), str(init_source), str(fb_source)], check=True)
archive = bytearray()
def newc(name, mode, data=b'', ino=1):
    fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name.encode()) + 1, 0]
    archive.extend(b'070701' + b''.join(f'{v:08x}'.encode() for v in fields))
    archive.extend(name.encode() + b'\0')
    archive.extend(b'\0' * ((-len(archive)) % 4))
    archive.extend(data)
    archive.extend(b'\0' * ((-len(archive)) % 4))
for i, name in enumerate(('.', 'dev', 'proc', 'sys', 'newroot'), 1):
    newc(name, 0o40755, ino=i)
newc('init', 0o100755, (out / 'init').read_bytes(), ino=6)
newc('TRAILER!!!', 0, ino=7)
(out / 'initramfs.cpio').write_bytes(archive)
subprocess.run(['lz4', '-l', '-9', '-f', str(out / 'initramfs.cpio'), str(out / 'initramfs.cpio.lz4')], check=True)
image = args.build / 'arch/arm64/boot/Image'
raw = image.read_bytes()
if b'-corot-' + args.tag.encode() not in raw or b'COROT ' + args.tag.encode() + b' marker' not in raw:
    raise SystemExit('Kernel lacks matching unique release and diagnostic marker')
dtb = (args.build / 'arch/arm64/boot/dts/mediatek/mt6985-xiaomi-corot.dtb').read_bytes()
if raw.count(dtb) != 1 or b'corot_test=' + args.tag.encode() + b'\0' not in dtb:
    raise SystemExit('Kernel must embed the exact compiled DTB with the matching test tag')
subprocess.run(['lz4', '-l', '-9', '-f', str(image), str(out / 'Image.lz4')], check=True)
compressed = (out / 'Image.lz4').read_bytes()
if compressed[:4] != bytes.fromhex('02214c18'):
    raise SystemExit('Expected legacy LZ4 kernel format')
def align(n):
    return (n + 4095) // 4096 * 4096
def pack(name, kernel, ramdisk, limit):
    header = bytearray(4096)
    header[:8] = b'ANDROID!'
    for offset, value in ((8, len(kernel)), (12, len(ramdisk)), (20, 1584), (40, 4)):
        struct.pack_into('<I', header, offset, value)
    blob = bytes(header)
    for data in (kernel, ramdisk):
        if data:
            blob += data
            blob += b'\0' * (align(len(blob)) - len(blob))
    if len(blob) > limit:
        raise SystemExit(name + ' exceeds partition')
    if name == 'init_boot_a.img':
        blob += b'\0' * (limit - len(blob))
    (out / name).write_bytes(blob)
pack('boot_a.img', compressed, b'', 67108864)
pack('init_boot_a.img', b'', (out / 'initramfs.cpio.lz4').read_bytes(), 8388608)
for name, payload, wanted in (('boot_a.img', compressed, raw), ('init_boot_a.img', (out / 'initramfs.cpio.lz4').read_bytes(), bytes(archive))):
    blob = (out / name).read_bytes()
    if blob[4096:4096 + len(payload)] != payload:
        raise SystemExit('Payload placement mismatch')
    decoded = subprocess.run(['lz4', '-d', '-c'], input=blob[4096:4096 + len(payload)], check=True, capture_output=True).stdout
    if decoded != wanted:
        raise SystemExit('Payload verification failed')
manifest = {'tag': args.tag, 'serial': 'UGEEOVYX4TZ9EE45', 'slot': 'a', 'kernel_sha256': hashlib.sha256(raw).hexdigest(), 'dtb_sha256': hashlib.sha256((args.build / 'arch/arm64/boot/dts/mediatek/mt6985-xiaomi-corot.dtb').read_bytes()).hexdigest(), 'files': {}}
for name in ('boot_a.img', 'init_boot_a.img'):
    data = (out / name).read_bytes()
    manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Verified packed images: ' + str(out))
