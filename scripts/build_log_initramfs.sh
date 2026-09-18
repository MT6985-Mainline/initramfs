#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/bin:/bin
OUT=/home/mytiantian/corot-work/corot-initramfs-log
ROOT=$OUT/root
rm -rf "$OUT"
mkdir -p "$ROOT/dev" "$ROOT/proc" "$ROOT/sys" "$ROOT/newroot"
cp /mnt/e/corot/corot-initramfs/init-log.c "$OUT/init-log.c"
aarch64-linux-gnu-gcc -nostdlib -static -fno-stack-protector -fno-builtin -ffreestanding -Os -Wl,-e,_start -o "$ROOT/init" "$OUT/init-log.c"
cd "$ROOT"
find . -print | cpio -o -H newc > "$OUT/initramfs.cpio"
lz4 -l -9 -f "$OUT/initramfs.cpio" "$OUT/initramfs.cpio.lz4" >/dev/null
cp -f "$OUT/initramfs.cpio.lz4" /home/mytiantian/corot-work/corot-initramfs/initramfs.cpio.lz4
file "$ROOT/init" "$OUT/initramfs.cpio.lz4"
# repack boot/init_boot with current kernel + log-catcher ramdisk
python3 /home/mytiantian/corot-work/pack_corot_images.py
truncate -s 8388608 /home/mytiantian/corot-work/images/corot-init_boot.img
cp -f /home/mytiantian/corot-work/images/corot-boot.img /mnt/e/corot/corot-boot.img
cp -f /home/mytiantian/corot-work/images/corot-init_boot.img /mnt/e/corot/corot-init_boot-full.img
ls -lh /mnt/e/corot/corot-boot.img /mnt/e/corot/corot-init_boot-full.img
