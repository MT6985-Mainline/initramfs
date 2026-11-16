#!/usr/bin/env python3
"""Capture corot expdb, persistent pstore, and cust log without partition writes."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--tag", required=True)
args=parser.parse_args()
if args.serial != "UGEEOVYX4TZ9EE45":
    raise SystemExit("Capture is restricted to the authorized corot serial")
if not re.fullmatch(r"[a-zA-Z0-9-]+", args.tag):
    raise SystemExit("Invalid tag")
adb=["adb", "-s", args.serial]
def shell(command):
    return subprocess.check_output(adb+["shell", command], timeout=60).decode().strip()
if shell("getprop ro.product.device") != "corot" or shell("getprop ro.boot.slot_suffix") != "_a":
    raise SystemExit("Device must be corot on slot a")
out=Path("evidence")/(args.tag+"-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
out.mkdir(parents=True, exist_ok=False)
manifest={"serial": args.serial, "slot": "a", "files": {}}
def capture(name, command, expected=None):
    result=subprocess.run(adb+["exec-out"]+command, capture_output=True, timeout=180)
    data=result.stdout
    (out/name).write_bytes(data)
    manifest["files"][name]={"bytes":len(data), "sha256":hashlib.sha256(data).hexdigest(), "rc":result.returncode, "stderr":result.stderr.decode(errors="replace")}
    if result.returncode or (expected is not None and len(data)!=expected):
        raise RuntimeError("Capture failed: "+name)
    print(f"{name}: {len(data)} bytes", flush=True)
    return data
for part in ("expdb", "pstore"):
    remote="/dev/block/by-name/"+part
    size=int(shell("blockdev --getsize64 "+remote))
    data=capture(part+".bin", ["cat",remote], size)
    if not any(data):
        print("No nonzero data in "+part, flush=True)
    text=b"\n".join(re.findall(rb"[\x09\x20-\x7e]{8,}",data))
    (out/(part+"-strings.txt")).write_bytes(text)
paths=shell("ls /sys/fs/pstore").splitlines()
for name in paths:
    if re.fullmatch(r"[a-zA-Z0-9_.-]+",name):
        capture(name,["cat","/sys/fs/pstore/"+name])
uuid=shell("blkid /dev/block/by-name/cust")
if 'a6333b1b-a1a1-4cf7-90ca-8317634b7aec' in uuid:
    target="/data/local/corot-cust-read"
    if target in shell("cat /proc/mounts"):
        raise SystemExit("Cust capture mountpoint already in use")
    shell("mkdir -p "+target)
    shell("mount -t ext4 -o ro,noload /dev/block/by-name/cust "+target)
    try:
        if shell("test -f "+target+"/boot-log.txt && echo exists || echo absent") == "exists":
            capture("cust-boot-log.txt",["cat",target+"/boot-log.txt"])
        else:
            manifest["cust-log"] = "absent"
            print("No historical cust boot-log.txt", flush=True)
    finally:
        shell("umount "+target)
(out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print(out.resolve())
