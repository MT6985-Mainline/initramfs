from pathlib import Path

p = Path('/home/mytiantian/corot-work/corot-initramfs-log/init-log.c')
s = p.read_text()

old = '''static void wdt_kick(void)
'''
new = '''/* reboot(LINUX_REBOOT_CMD_RESTART2, "bootloader") */
static void reboot_bootloader(void)
{
\tstatic const char arg[] = "bootloader";
\tksys(142, (long)0xfee1deadUL, (long)0x28121969UL, (long)0xa932fb52UL,
\t     (long)arg, 0);
}

static void wdt_kick(void)
'''
if old not in s:
    raise SystemExit('wdt anchor missing')
s = s.replace(old, new, 1)

old = '''\t\tif (hb % 2 == 0)
\t\t\ttele(hb / 2);
'''
new = '''\t\tif (hb % 2 == 0) {
\t\t\ttele(hb / 2);
\t\t\t/* hand the device back to fastboot after a fixed window */
\t\t\tif (hb / 2 >= 90) {
\t\t\t\tnote("corot-log: telemetry window done, reboot to bootloader\\n");
\t\t\t\treboot_bootloader();
\t\t\t}
\t\t}
'''
if old not in s:
    raise SystemExit('tele anchor missing')
s = s.replace(old, new, 1)
p.write_text(s)
print('auto reboot-to-bootloader after 180s added')
