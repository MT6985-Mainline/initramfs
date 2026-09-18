#!/usr/bin/env bash
ADB=/mnt/d/platform-tools/adb.exe
SER=UGEEOVYX4TZ9EE45
OUT=/home/mytiantian/corot-work/gctl-apsrc-test-bootlog.txt

echo "=== wait for android adb ==="
for i in $(seq 1 30); do
  if "$ADB" -s "$SER" get-state >/dev/null 2>&1; then echo "adb ready after $((i*10))s"; break; fi
  sleep 10
done
"$ADB" -s "$SER" devices

echo "=== wait for boot_completed ==="
for i in $(seq 1 30); do
  bc=$("$ADB" -s "$SER" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  echo "boot_completed=$bc"
  [ "$bc" = "1" ] && break
  sleep 10
done

echo "=== extract cust boot-log ==="
"$ADB" -s "$SER" shell su -c "mkdir -p /data/local/tmp/cust_ro; mount -t ext4 -o ro,noload /dev/block/sdc80 /data/local/tmp/cust_ro; cat /data/local/tmp/cust_ro/boot-log.txt; umount /data/local/tmp/cust_ro" > "$OUT" 2>/dev/null
wc -c "$OUT"
echo "=== first lines of new log ==="
head -3 "$OUT"
