#!/usr/bin/env bash
set -euo pipefail
ADB=/mnt/d/platform-tools/adb.exe
SER=UGEEOVYX4TZ9EE45
OUT=/home/mytiantian/corot-work/after-ext
"$ADB" -s "$SER" shell 'mkdir -p /mnt/cust-rw; mount -t ext4 /dev/block/sdc80 /mnt/cust-rw 2>/dev/null; ls -l /mnt/cust-rw/boot-log.txt'
"$ADB" -s "$SER" shell 'cat /mnt/cust-rw/boot-log.txt' > "$OUT/boot-log.txt" 2> "$OUT/boot-log.err" || true
"$ADB" -s "$SER" shell 'umount /mnt/cust-rw' || true
stat -c '%n %s' "$OUT/boot-log.txt"
