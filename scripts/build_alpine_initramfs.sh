#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/lib/llvm-22/bin:/usr/bin:/bin
OUT=/home/mytiantian/corot-work/alpine-initramfs
ROOT=$OUT/root
SRC=/home/mytiantian/corot-work/corot-initramfs-alpine-init.c
rm -rf "$OUT"
mkdir -p "$ROOT/dev" "$ROOT/proc" "$ROOT/sys" "$ROOT/newroot"
aarch64-linux-gnu-gcc -nostdlib -static -fno-stack-protector -fno-builtin -ffreestanding -Os -Wl,-e,_start -o "$ROOT/init" "$SRC"
(cd "$ROOT" && find . -print | cpio -o -H newc) > "$OUT/initramfs.cpio"
lz4 -l -9 -f "$OUT/initramfs.cpio" "$OUT/initramfs.cpio.lz4" >/dev/null
file "$ROOT/init" "$OUT/initramfs.cpio.lz4"
stat -c '%s %n' "$OUT/initramfs.cpio.lz4"
