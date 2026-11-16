#!/usr/bin/env python3
"""Test corot in slot a, then restore verified stock slot a images."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

SERIAL = 'UGEEOVYX4TZ9EE45'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--images', type=Path)
parser.add_argument('--backup', type=Path, required=True)
parser.add_argument('--restore-only', action='store_true')
parser.add_argument('--from-fastboot', action='store_true')
args = parser.parse_args()
backup = json.loads((args.backup / 'manifest.json').read_text())
if backup['serial'] != SERIAL or backup['slot'] != 'a':
    raise SystemExit('Backup is not for the authorized device and slot')
for part in ('boot_a', 'init_boot_a'):
    p = args.backup / (part + '.img')
    item = backup['partitions'][part]
    with p.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if p.stat().st_size != item['bytes'] or digest != item['sha256']:
        raise SystemExit('Backup checksum mismatch: ' + part)
if not args.restore_only:
    if args.images is None:
        raise SystemExit('--images is required for a test')
    images = json.loads((args.images / 'manifest.json').read_text())
    if images['serial'] != SERIAL or images['slot'] != 'a':
        raise SystemExit('Test images are not for the authorized device and slot')
    for name in ('boot_a.img', 'init_boot_a.img'):
        p = args.images / name
        item = images['files'][name]
        with p.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        if p.stat().st_size != item['bytes'] or digest != item['sha256']:
            raise SystemExit('Test image checksum mismatch: ' + name)
log = args.backup / 'restore.log' if args.restore_only else args.images / 'test.log'
logfile = log.open('a', buffering=1)
def run(program, params, timeout=60):
    if program not in ('adb', 'fastboot'):
        raise ValueError('Unexpected tool')
    if program == 'fastboot' and params and params[0] == 'flash':
        if params[1] not in ('boot_a', 'init_boot_a'):
            raise ValueError('Only a-slot boot and init_boot may be flashed')
    command = [program, '-s', SERIAL] + params
    logfile.write('$ ' + ' '.join(command) + '\n')
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    output = (result.stdout + result.stderr).decode(errors='replace')
    logfile.write(output)
    print(output.strip(), flush=True)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(command))
    # ADB daemon notices go to stderr; identity/hash checks use stdout only.
    # Fastboot getvar reports its authoritative values on stderr.
    return result.stdout.decode(errors="replace").strip() if program == "adb" else output.strip()
def in_fastboot():
    result = subprocess.run(['fastboot', '-s', SERIAL, 'devices'], capture_output=True, timeout=5)
    return any(line.split()[0] == SERIAL for line in result.stdout.decode().splitlines() if line.split())
def wait_fastboot(seconds):
    until = time.monotonic() + seconds
    last_report = 0
    while time.monotonic() < until:
        if in_fastboot():
            return True
        if time.monotonic() - last_report >= 20:
            print('Waiting for target fastboot, remaining ' + str(round(until - time.monotonic())) + 's', flush=True)
            last_report = time.monotonic()
        time.sleep(2)
    return False
def check_fastboot():
    if not in_fastboot():
        raise RuntimeError('Target fastboot is absent')
    product = run('fastboot', ['getvar', 'product'])
    slot = run('fastboot', ['getvar', 'current-slot'])
    if not re.search(r'product:\s*corot\b', product) or not re.search(r'current-slot:\s*a\b', slot):
        raise RuntimeError('Fastboot product or slot mismatch')
def restore():
    check_fastboot()
    for part in ('boot_a', 'init_boot_a'):
        run('fastboot', ['flash', part, str(args.backup / (part + '.img'))], timeout=120)
    run('fastboot', ['reboot'])
    print('Original boot_a and init_boot_a restored; waiting for Android', flush=True)
    run('adb', ['wait-for-device'], timeout=150)
    identity = run('adb', ['shell', 'getprop ro.product.device; getprop ro.boot.slot_suffix; uname -r'])
    if identity.splitlines()[:2] != ['corot', '_a']:
        raise RuntimeError('Android identity mismatch after restoration')
    hashes = run('adb', ['shell', 'sha256sum /dev/block/by-name/boot_a /dev/block/by-name/init_boot_a'], timeout=90)
    for part in ('boot_a', 'init_boot_a'):
        if backup['partitions'][part]['sha256'] not in hashes:
            raise RuntimeError('Restored partition checksum mismatch: ' + part)
    print('Verified original Android restored on target slot a', flush=True)
if args.restore_only:
    restore()
else:
    if not args.from_fastboot:
        identity = run('adb', ['shell', 'getprop ro.product.device; getprop ro.boot.slot_suffix'])
        if identity.splitlines() != ['corot', '_a']:
            raise SystemExit('Refusing test: target must be corot currently running slot a')
        current_hashes = run('adb', ['shell', 'sha256sum /dev/block/by-name/boot_a /dev/block/by-name/init_boot_a'], timeout=90)
        for part in ('boot_a', 'init_boot_a'):
            if backup['partitions'][part]['sha256'] not in current_hashes:
                raise SystemExit('Current a-slot image differs from the backup: ' + part)
        run('adb', ['reboot', 'bootloader'])
        if not wait_fastboot(45):
            raise SystemExit('Target did not enter fastboot; no partitions flashed')
    check_fastboot()
    run('fastboot', ['oem', 'p2u', 'on'])
    flashed = False
    try:
        for part in ('boot_a', 'init_boot_a'):
            flashed = True
            run('fastboot', ['flash', part, str(args.images / (part + '.img'))], timeout=120)
        run('fastboot', ['reboot'])
        # Let the initial fastboot device disappear before detecting test end.
        time.sleep(5)
        if not wait_fastboot(210):
            raise RuntimeError('Target has not returned to fastboot; manual power+volume-down may be required')
    finally:
        if flashed and in_fastboot():
            restore()
        elif flashed:
            print('Stock backup verified and ready, but target fastboot is absent. Use --restore-only once it returns.', flush=True)
