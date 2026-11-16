#!/usr/bin/env python3
"""Read-only stock display evidence capture for Xiaomi corot."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--output", type=Path, default=Path("evidence"))
args = parser.parse_args()
adb = ["adb", "-s", args.serial]
probe = subprocess.run(adb + ["shell", "getprop ro.product.device"], check=True, capture_output=True)
if probe.stdout.strip() != b"corot":
    raise SystemExit("Refusing capture: selected device is not corot")
out = args.output / ("stock-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
out.mkdir(parents=True, exist_ok=False)
commands = {
    "identity.txt": ["shell", "id; uname -a; getprop ro.build.fingerprint; getprop ro.boot.slot_suffix; getprop ro.boot.verifiedbootstate; cat /proc/cmdline"],
    "stock.dtb": ["exec-out", "cat", "/sys/firmware/fdt"],
    "stock.config.gz": ["exec-out", "cat", "/proc/config.gz"],
    "dmesg.txt": ["exec-out", "dmesg"],
    "modules.txt": ["exec-out", "cat", "/proc/modules"],
    "display-sysfs.txt": ["shell", "for p in /sys/class/mi_display/disp-DSI-0/panel_info /sys/class/mi_display/disp-DSI-0/dynamic_fps /sys/class/mi_display/disp-DSI-0/disp_param /sys/class/drm/card0-DSI-1/status /sys/class/drm/card0-DSI-1/modes /sys/class/drm/card0-DSI-2/status; do echo \"$p\"; cat \"$p\"; done"],
    "partitions.txt": ["shell", "ls -l /dev/block/by-name; cat /proc/partitions; cat /proc/mounts; blkid /dev/block/by-name/cust"],
    "pstore-console.txt": ["exec-out", "cat", "/sys/fs/pstore/console-ramoops-0"],
    "pstore-pmsg.bin": ["exec-out", "cat", "/sys/fs/pstore/pmsg-ramoops-0"],
}
manifest = {"serial": args.serial, "files": {}}
for name, command in commands.items():
    result = subprocess.run(adb + command, capture_output=True, timeout=90)
    (out / name).write_bytes(result.stdout)
    manifest["files"][name] = {"command": command, "returncode": result.returncode, "bytes": len(result.stdout), "sha256": hashlib.sha256(result.stdout).hexdigest(), "stderr": result.stderr.decode(errors="replace")}
    print(f"{name}: {len(result.stdout)} bytes, rc={result.returncode}", flush=True)
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(out.resolve())
