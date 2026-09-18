#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/bin:/bin
OUT=/home/mytiantian/corot-work/corot-initramfs-debian
ROOT=$OUT/root
rm -rf "$OUT"
mkdir -p "$ROOT/dev" "$ROOT/proc" "$ROOT/sys" "$ROOT/newroot"
cp /mnt/e/corot/corot-initramfs/init-debian.c "$OUT/init-debian.c"
aarch64-linux-gnu-gcc -nostdlib -static -fno-stack-protector -fno-builtin -ffreestanding -Os -Wl,-e,_start -o "$ROOT/init" "$OUT/init-debian.c"
cd "$ROOT"
find . -print | cpio -o -H newc > "$OUT/initramfs.cpio"
lz4 -l -9 -f "$OUT/initramfs.cpio" "$OUT/initramfs.cpio.lz4" >/dev/null
cp -f "$OUT/initramfs.cpio.lz4" /home/mytiantian/corot-work/corot-initramfs/initramfs.cpio.lz4
file "$ROOT/init" "$OUT/initramfs.cpio.lz4"
ls -lh "$OUT/initramfs.cpio.lz4"
