# mt6985-7.2-initramfs-corot

The log-catcher initramfs used for the corot (Xiaomi Redmi K60 Ultra,
MediaTek MT6985) mainline bring-up.

## Why it exists

The board has no usable serial console and a test kernel can hang hard enough
to take the whole SoC down with it, which is exactly when the log matters
most. So instead of pivoting into a rootfs, this `init` mounts the phone's
`cust` partition (ext4) read-write and streams `/dev/kmsg` into
`/newroot/boot-log.txt`, `fsync`-ing after every chunk.

`cust` is found by its **ext4 superblock UUID**, not by a device node: on the
stock Android kernel it is `/dev/sdc80`, but the mainline test kernel enumerates
UFS differently, so a hard-coded node silently sent every bring-up round's log
somewhere else - which made those rounds look like "the kernel printed nothing"
and produced conclusions from runs that had recorded no data at all.  The
catcher now probes `/dev/block/by-name/cust` first and then every `/dev/sd*`
node, matches magic `0xEF53` at superblock +56 and the UUID
`a6333b1b-a1a1-4cf7-90ca-8317634b7aec` (label `debian-cust`), and mounts only an
exact match - nothing is ever mounted, or `O_TRUNC`'d, on a guess.
Whatever happens afterwards — hang, panic, watchdog reset — the tail is
already on flash and can be read back from Android.

It is a single freestanding C file: no libc, no busybox, no dynamic linking,
raw ARM64 syscalls only (`mount` 40, `openat` 56, `read` 63, `write` 64,
`fsync` 82, `mkdirat` 34, `nanosleep` 101), statically linked, ~10 KiB.

## What it does

`_start()` in `src/init-log.c`:

1. `mkdir` + mount `devtmpfs` on `/dev`, `proc` on `/proc`, `sysfs` on `/sys`.
2. Open `/dev/kmsg` read-write. If `/dev/mem` is available, arm the watchdog
   kick (`0x1c007008`, key `0x1971`) so a WDT reset cannot cut the capture
   short.
3. Wait up to 45 s for `cust` to be identified by UUID (see above), mount it
   ext4 at `/newroot` and open `/newroot/boot-log.txt`
   (`O_CREAT|O_TRUNC|O_APPEND`).  The successful match is logged, so the log
   itself records where it went:
   `corot-log: cust found at /dev/block/by-name/cust (uuid match)`.
4. Optionally mirror the same stream to `/dev/ttyGS0` when USB gadget serial
   comes up.
5. Dump one-shot context: `/proc/cmdline`, pstore (`/sys/fs/pstore/*`),
   a listing of `/dev/block`, a framebuffer scan, and the UDC state.
6. Loop forever: read `/dev/kmsg`, append to the log, `fsync`, and every
   couple of seconds emit a telemetry line plus a heartbeat
   (`---- corot-hb N alive ==`) so a truncated log still shows how far it got.
7. After a fixed telemetry window it reboots to the bootloader, which the
   flash scripts use as the "test finished" signal.

### A note on the window length

The window is `h / 2 >= 90` telemetry ticks, but `h` only advances on loop
iterations where `/dev/kmsg` had nothing to read. A kernel that is spewing
display register dumps keeps the loop busy and the wall-clock window stretches
accordingly — observed end-to-end test windows in this project ranged from
~140 s to ~470 s. Do not treat the window length as a fixed number; detect the
transition (fastboot/adb appearing) instead.

## Files

| Path | What |
|---|---|
| `src/init-log.c` | the log-catcher, current version (552 lines) |
| `src/init.c` | the earlier minimal init (no log capture) |
| `src/init-debian.c` | variant that pivots into a Debian rootfs |
| `src/Makefile` | small standalone build for `init.c` |
| `prebuilt/initramfs.cpio.lz4` | ready-made ramdisk (6 KiB) |
| `scripts/build_log_initramfs.sh` | the build actually used: compiles `init-log.c`, makes the cpio, lz4-compresses it, then repacks boot/init_boot |
| `scripts/rebuild_init_log.sh` | rebuild only the ramdisk |
| `scripts/build_channel.sh` | compile `init-log.c`, pack the cpio + lz4 and drop it into the kernel pack directory |
| `scripts/build_alpine_initramfs.sh`, `scripts/build_debian_initramfs.sh` | alternate rootfs-based ramdisks |
| `scripts/read_cust_log.sh`, `scripts/extract_cust.sh` | pull `boot-log.txt` back from Android |
| `scripts/patch_init_log.py`, `patch_init_log_reboot.py`, `patch_initlog.py` | in-place patch helpers used while developing it |

## Building

```sh
aarch64-linux-gnu-gcc -nostdlib -static -fno-stack-protector -fno-builtin \
    -ffreestanding -Os -Wl,-e,_start -o root/init src/init-log.c
(cd root && find . -print | cpio -o -H newc > ../initramfs.cpio)
lz4 -l -9 -f initramfs.cpio initramfs.cpio.lz4
```

The ramdisk is only a few KiB; it goes into `init_boot_a` and `init_boot_b`
(padded to the partition's 8 MiB), while the kernel goes into `boot_ab`.
`vendor_boot` is never touched.

```sh
fastboot -s $SERIAL flash boot_ab     corot-boot.img
fastboot -s $SERIAL flash init_boot_a corot-init_boot.img
fastboot -s $SERIAL flash init_boot_b corot-init_boot.img
```

## Reading the log back

From Android with root:

```sh
mkdir -p /data/local/tmp/cust
mount -t ext4 -o ro,noload /dev/block/sdc80 /data/local/tmp/cust
cat /data/local/tmp/cust/boot-log.txt
umount /data/local/tmp/cust
```

`scripts/read_cust_log.sh` does exactly this over `adb`.

**Always check the kernel banner in the captured log** — it contains
`dirty #NNN` with the build counter. A log whose counter did not advance is a
stale file from a previous boot, and several wrong conclusions in this project
came from reading one.
