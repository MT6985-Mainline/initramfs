#!/usr/bin/env bash
# Rebuild the log-catcher initramfs in place (keeps wired firmware).
set -euo pipefail
export PATH=/usr/bin:/bin
OUT=/home/mytiantian/corot-work/corot-initramfs-log
ROOT=$OUT/root
aarch64-linux-gnu-gcc -nostdlib -static -fno-stack-protector -fno-builtin -ffreestanding -Os -Wl,-e,_start -o "$ROOT/init" "$OUT/init-log.c"
(cd "$ROOT" && find . -print | cpio -o -H newc) > "$OUT/initramfs.cpio"
lz4 -l -9 -f "$OUT/initramfs.cpio" "$OUT/initramfs.cpio.lz4" >/dev/null
file "$ROOT/init" "$OUT/initramfs.cpio.lz4"
stat -c '%s %n' "$OUT/initramfs.cpio.lz4"
