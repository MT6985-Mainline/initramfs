#!/usr/bin/env python3
"""Preserve the exact tagged corot build and source state in the workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--build", type=Path, required=True)
parser.add_argument("--tag", required=True)
args = parser.parse_args()
if not re.fullmatch(r"[a-zA-Z0-9-]+", args.tag):
    raise SystemExit("Invalid tag")
root = Path(__file__).resolve().parent.parent
build = (root / args.build).resolve()
native = root / "linux-native"
expected = json.loads((root / "images" / args.tag / "manifest.json").read_text())
if expected["serial"] != "UGEEOVYX4TZ9EE45" or expected["slot"] != "a":
    raise SystemExit("Image provenance must match the authorized target and slot")
if (native / ".config.corot-build-held").exists():
    raise SystemExit("A build holds source .config; do not archive an in-flight build")
kernel = build / "arch/arm64/boot/Image"
dtb = build / "arch/arm64/boot/dts/mediatek/mt6985-xiaomi-corot.dtb"
for path, key in ((kernel, "kernel_sha256"), (dtb, "dtb_sha256")):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected[key]:
        raise SystemExit("Build differs from the tagged image: " + str(path))
saved = root / "out" / (args.tag + "-tested")
saved.mkdir(exist_ok=False)
manifest = {"tag": args.tag, "serial": expected["serial"], "slot": "a", "files": {}}
files = [build / ".config", kernel, dtb, build / "vmlinux", build / "System.map",
         build / "include/config/kernel.release"]
files.extend(build.glob("*.log"))
for source in files:
    relative = source.relative_to(build)
    target = saved / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest["files"][str(relative)] = {"bytes": target.stat().st_size, "sha256": digest}
image_dir = root / "images" / args.tag
for name in ("test.log", "init-log.c", "fb-test.c", "manifest.json"):
    source = image_dir / name
    if source.exists():
        shutil.copy2(source, saved / ("image-" + name))
manifest["source_commit"] = subprocess.check_output(
    ["git", "-C", str(native), "rev-parse", "HEAD"], text=True).strip()
patch = subprocess.check_output(
    ["git", "-C", str(native), "diff", "--no-ext-diff", "--binary", "HEAD"])
(saved / "source-diff.patch").write_bytes(patch)
manifest["source_diff_sha256"] = hashlib.sha256(patch).hexdigest()
names = subprocess.check_output(
    ["git", "-C", str(native), "ls-files", "--others", "--exclude-standard", "-z"]).split(b"\0")
manifest["new_sources"] = {}
with tarfile.open(saved / "source-new-files.tar.gz", "w:gz") as archive:
    for name in names:
        if not name:
            continue
        relative = Path(name.decode())
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("Invalid source path")
        source = native / relative
        archive.add(source, arcname=str(relative), recursive=False)
        if source.is_file() and not source.is_symlink():
            manifest["new_sources"][str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
(saved / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Preserved exact build and source provenance: " + str(saved))
