#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile both corot capture sources and build a deterministic legacy-LZ4 ramdisk."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path)
parser.add_argument("--cc", default="aarch64-linux-gnu-gcc")
args = parser.parse_args()
repo = Path(__file__).resolve().parent.parent
out = (args.out or repo / "out/log-ramdisk").resolve()
if any(out == path or path in out.parents for path in (Path("/tmp"), Path("/var/tmp"))):
    raise SystemExit("Keep corot build artifacts outside temporary directories")
out.mkdir(parents=True, exist_ok=True)
scratch = out / "build-scratch"
scratch.mkdir(exist_ok=True)
environment = dict(os.environ, TMPDIR=str(scratch))
sources = [repo / "src/init-log.c", repo / "src/fb-test.c"]
subprocess.run([args.cc, "-nostdlib", "-static", "-fno-stack-protector",
                "-fno-builtin", "-ffreestanding", "-Os", "-Wl,-e,_start",
                "-o", str(out / "init"), *map(str, sources)],
               check=True, env=environment)
archive = bytearray()

def newc(name, mode, data=b"", ino=1):
    fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0,
              len(name.encode()) + 1, 0]
    archive.extend(b"070701" + b"".join(f"{value:08x}".encode() for value in fields))
    archive.extend(name.encode() + b"\0")
    archive.extend(b"\0" * ((-len(archive)) % 4))
    archive.extend(data)
    archive.extend(b"\0" * ((-len(archive)) % 4))

for ino, name in enumerate((".", "dev", "proc", "sys", "newroot"), 1):
    newc(name, 0o40755, ino=ino)
newc("init", 0o100755, (out / "init").read_bytes(), ino=6)
newc("TRAILER!!!", 0, ino=7)
(out / "initramfs.cpio").write_bytes(archive)
compressed = out / "initramfs.cpio.lz4"
subprocess.run(["lz4", "-l", "-9", "-f", str(out / "initramfs.cpio"),
                str(compressed)], check=True, env=environment)
if compressed.read_bytes()[:4] != bytes.fromhex("02214c18"):
    raise SystemExit("Expected legacy LZ4 format")
check = subprocess.run(["lz4", "-d", "-c", str(compressed)], check=True,
                       capture_output=True, env=environment)
if check.stdout != bytes(archive):
    raise SystemExit("Ramdisk payload verification failed")
manifest = {"sources": {}, "files": {}}
for path in sources:
    manifest["sources"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
for name in ("init", "initramfs.cpio", "initramfs.cpio.lz4"):
    path = out / name
    manifest["files"][name] = {"bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Built and verified: " + str(compressed))
