# Corot MT6985 log and display-test initramfs

This initramfs records the Redmi K60 Ultra mainline kernel log and exercises the
complete MiCode DRM v2 / mi_disp / M12 display port. The current checkpoint is
**r360**: Linux console content appears on the panel, with a noisy bottom band.
Continuing full-screen updates are not yet verified. See
[the r360 hardware checkpoint](docs/r360-display-progress.md).

The authorized test target is **UGEEOVYX4TZ9EE45**, on **slot a**. The test helper
checks the device identity, slot, backup hashes and image hashes before flashing
only `boot_a` and `init_boot_a`. The original Android images are backed up locally
and verified after restoration.

## Capture and display test

`src/init-log.c` and `src/fb-test.c` form a static, freestanding ARM64 executable
using raw system calls. It mounts devtmpfs, proc, sysfs and debugfs, reads
`/dev/kmsg`, and locates the log filesystem by its ext4 UUID
`a6333b1b-a1a1-4cf7-90ca-8317634b7aec`. It mounts only an exact match and writes
`/newroot/boot-log.txt` with regular `fsync` calls.

The capture owns the identified MT6985 watchdog through its real device
interface. Its sparse RGU mapping verifies the bootloader reboot reason. A
monotonic 120-second deadline stops feeds and requests a reboot to fastboot,
including while register dumps keep the log reader busy. A kernel shutdown
fault can still prevent that transition; r360 required manual fastboot entry
and the guarded `--restore-only` procedure.

The display test accepts only a native `mediatekdrmfb` framebuffer at
1220 x 2712 with a valid pitch, length and pixel layout. It detaches the fb
console, writes red/green/blue/white quadrants, and advances a white vertical
bar every five seconds. A successful framebuffer write proves the CPU wrote
that buffer; physical display observations and hardware completion logs are
needed to establish scanout. Three bounded pin snapshots record the panel,
reset and TE pin state.

## Build the ramdisk

Dependencies: Python 3, `aarch64-linux-gnu-gcc` and `lz4`. All generated files
and compiler scratch stay in the selected output directory.

```sh
python3 tools/build-log-ramdisk.py --out out/log-ramdisk
```

The old `scripts/build_channel.sh`, `scripts/rebuild_init_log.sh` and
`scripts/build_log_initramfs.sh` entry points call this builder and accept the
same options. They compile both current sources and no longer depend on old
host paths. `src/Makefile` retains the earlier minimal `src/init.c` build.

`prebuilt/initramfs.cpio.lz4` is the exact ramdisk tested with r360.
[Its manifest](prebuilt/r360-manifest.json) records the sources, init and archive
hashes. The standalone builder verifies that decompression reproduces the
entire deterministic cpio archive.

## Kernel build and guarded test workflow

The `bringup/` directory stores the build, pack, backup, test and evidence
helpers used in this workspace. Install them into a sibling workspace
`scripts/` directory: their paths are resolved relative to that directory.
The workspace layout is `linux-native/`, `initramfs/`, `scripts/`, `out/`,
`images/`, `backups/`, `board/` and `evidence/`.

From the workspace containing this repository:

```sh
mkdir -p scripts
cp initramfs/bringup/*.py scripts/
python3 scripts/backup-slot-a.py --serial UGEEOVYX4TZ9EE45
python3 scripts/build-corot.py --source linux-native --name r360 --release r360 --target all --jobs 8
python3 scripts/pack-corot.py --build out/r360 --tag r360
```

The kernel source is
[MT6985-Mainline/linux, 7.2-mt6985-xiaomi-corot](https://github.com/MT6985-Mainline/linux/tree/7.2-mt6985-xiaomi-corot).
The build checks the complete provider selection and the genuine MT6985 MML
topology/initcall. Packing checks the matching release and marker, the exact
embedded DTB, legacy-LZ4 payloads and partition sizes. New test tags require a
matching source marker and `corot_test` DT tag.

Before a test, replace the backup path below with the directory created for the
connected target. The helper verifies `corot`, serial, current slot a and both
original partition hashes, enables `fastboot oem p2u on`, tests the images and
then restores the original slot-a images.

```sh
python3 scripts/test-slot-a.py --images images/r360 --backup backups/slot-a-20261114T075949Z
python3 scripts/collect-crash.py --serial UGEEOVYX4TZ9EE45 --tag after-r360
python3 scripts/preserve-corot-build.py --build out/r360 --tag r360
```

If the tested kernel does not return to fastboot, enter fastboot manually on
this K60 Ultra, then run:

```sh
python3 scripts/test-slot-a.py --restore-only --backup backups/slot-a-20261114T075949Z
```

The collector reads expdb, the pstore partition, ramoops files and the
UUID-identified cust log from restored Android. It uses
`/data/local/corot-cust-read` as a read-only mountpoint. Raw dumps, stock boot
images and local debug builds remain in the workspace.

Always identify the unique kernel release/build counter and test tag before
interpreting a log. Persistent expdb can retain earlier boot failures.
