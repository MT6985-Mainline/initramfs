#!/usr/bin/env python3
"""Back up and verify only corot boot_a and init_boot_a; no device writes."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
args = parser.parse_args()
adb = ["adb", "-s", args.serial]
def shell(cmd):
    return subprocess.check_output(adb + ["shell", cmd], timeout=120).decode().strip()
if shell("getprop ro.product.device") != "corot" or shell("getprop ro.boot.slot_suffix") != "_a":
    raise SystemExit("Refusing backup: device must be corot running slot a")
if not shell("id").startswith("uid=0"):
    raise SystemExit("Root ADB required")
out = Path("backups") / ("slot-a-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
out.mkdir(parents=True, exist_ok=False)
manifest = {"serial": args.serial, "slot": "a", "fingerprint": shell("getprop ro.build.fingerprint"), "partitions": {}}
for part in ("boot_a", "init_boot_a"):
    remote = "/dev/block/by-name/" + part
    size = int(shell("blockdev --getsize64 " + remote))
    remote_hash = shell("sha256sum " + remote).split()[0]
    image = out / (part + ".img")
    with image.open("xb") as f:
        subprocess.run(adb + ["exec-out", "cat", remote], stdout=f, check=True, timeout=180)
    digest = hashlib.file_digest(image.open("rb"), "sha256").hexdigest()
    if image.stat().st_size != size or digest != remote_hash:
        raise SystemExit("Backup verification failed: " + part)
    manifest["partitions"][part] = {"bytes": size, "sha256": digest, "source": remote}
    print(f"Verified {part}: {size} bytes sha256={digest}", flush=True)
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(out.resolve())
