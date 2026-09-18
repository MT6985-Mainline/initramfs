from pathlib import Path

p = Path('/home/mytiantian/corot-work/corot-initramfs-log/init-log.c')
s = p.read_text()

# 1) pwrite64 syscall helper after pread64_
old = '''/* pread64: x0=fd x1=buf x2=count x3=offset(64-bit) */
static long pread64_(long fd, void *buf, long n, long off)
{
\treturn ksys(67, fd, (long)buf, n, off, 0);
}
'''
new = '''/* pread64: x0=fd x1=buf x2=count x3=offset(64-bit) */
static long pread64_(long fd, void *buf, long n, long off)
{
\treturn ksys(67, fd, (long)buf, n, off, 0);
}
/* pwrite64: x0=fd x1=buf x2=count x3=offset(64-bit) */
static long pwrite64_(long fd, const void *buf, long n, long off)
{
\treturn ksys(68, fd, (long)buf, n, off, 0);
}
'''
if old not in s:
    raise SystemExit('pread64 anchor missing')
s = s.replace(old, new, 1)

# 2) wdt + telemetry helpers after note()
old = '''/* file-only note (no console echo, avoids read-back duplication) */
static void note(const char *s)
{
\tif (g_log >= 0)
\t\twrite_(g_log, s, slen(s));
}
'''
new = '''/* file-only note (no console echo, avoids read-back duplication) */
static void note(const char *s)
{
\tif (g_log >= 0)
\t\twrite_(g_log, s, slen(s));
}

/* --- watchdog + display telemetry ---------------------------------- */
static long g_mem = -1;

#define WDT_RESTART_PA 0x10007008UL
#define WDT_KEY 0x1971U

static void wdt_kick(void)
{
\tunsigned int v = WDT_KEY;
\tif (g_mem >= 0)
\t\tpwrite64_(g_mem, &v, 4, (long)WDT_RESTART_PA);
}

/* sleep one second, kicking the watchdog so bring-up kernels survive */
static void pause1s(const struct timespec *ts)
{
\twdt_kick();
\tnanosleep_(ts);
}

static unsigned int rd32(unsigned long pa)
{
\tunsigned int v = 0;
\tpread64_(g_mem, &v, 4, (long)pa);
\treturn v;
}

static void tele(int n)
{
\tchar line[240];
\tint m = 0, i;
\tstatic const unsigned long dsi = 0x1400d000UL;
\tstatic const unsigned long mutex = 0x14021000UL;
\tstatic const unsigned long ovl = 0x14402000UL;
\tstatic const unsigned long gce = 0x1e980000UL;
\tstatic const unsigned long dsi_off[6] = { 0x00, 0x08, 0x0c, 0x10, 0x14, 0x18 };
\tstatic const unsigned long gth_off[3] = { 0x00, 0x20, 0x24 };

\tif (g_mem < 0)
\t\treturn;
\tm = 0;
\tline[m++] = 't'; line[m++] = 'e'; line[m++] = 'l'; line[m++] = 'e';
\tline[m++] = ' ';
\tif (n >= 100) line[m++] = '0' + n / 100 % 10;
\tif (n >= 10) line[m++] = '0' + n / 10 % 10;
\tline[m++] = '0' + n % 10;
\tline[m++] = ' ';
\tfor (i = 0; i < 6; i++) {
\t\tline[m++] = '0'; line[m++] = 'x';
\t\thex8(line + m, rd32(dsi + dsi_off[i])); m += 8;
\t\tline[m++] = ' ';
\t}
\tline[m++] = 'm'; line[m++] = 'u'; line[m++] = 'x'; line[m++] = '=';
\tline[m++] = '0'; line[m++] = 'x';
\thex8(line + m, rd32(mutex + 0x20)); m += 8;
\tline[m++] = ' ';
\tline[m++] = 'o'; line[m++] = 'v'; line[m++] = 'l'; line[m++] = '=';
\tline[m++] = '0'; line[m++] = 'x';
\thex8(line + m, rd32(ovl + 0x24)); m += 8;
\tfor (i = 0; i < 2; i++) {
\t\tint j;
\t\tunsigned long th = gce + 0x100 + (i == 0 ? 0 : 3 * 0x80);
\t\tline[m++] = ' ';
\t\tline[m++] = 'g'; line[m++] = '0' + i; line[m++] = '=';
\t\tfor (j = 0; j < 3; j++) {
\t\t\tline[m++] = '0'; line[m++] = 'x';
\t\t\thex8(line + m, rd32(th + gth_off[j])); m += 8;
\t\t\tif (j < 2) line[m++] = ',';
\t\t}
\t}
\tline[m++] = '\\n';
\tline[m] = 0;
\tif (g_log >= 0) {
\t\twrite_(g_log, line, m);
\t\tfsync_(g_log);
\t}
}
'''
if old not in s:
    raise SystemExit('note anchor missing')
s = s.replace(old, new, 1)

# 3) open /dev/mem right after devtmpfs mount
old = '''\tout("corot-log: initramfs log-catcher started\\n");
\tdump_cmdline();
'''
new = '''\tout("corot-log: initramfs log-catcher started\\n");
\tg_mem = openat_("/dev/mem", 2 /* O_RDWR */, 0);
\tif (g_mem < 0)
\t\tout("corot-log: /dev/mem unavailable; no watchdog kick\\n");
\telse
\t\tout("corot-log: watchdog kick armed (0x10007008)\\n");
\tdump_cmdline();
'''
if old not in s:
    raise SystemExit('start anchor missing')
s = s.replace(old, new, 1)

# 4) all wait loops kick the watchdog
s = s.replace('''\t\tif (fd >= 0) {
\t\t\tclose_(fd);
\t\t\tbreak;
\t\t}
\t\tnanosleep_(&one);
\t}''', '''\t\tif (fd >= 0) {
\t\t\tclose_(fd);
\t\t\tbreak;
\t\t}
\t\tpause1s(&one);
\t}''', 1)
s = s.replace('''\t\tlist_dir("/dev/block", 's');
\t\tfor (;;)
\t\t\tnanosleep_(&five);
\t}
\tout("corot-log: " BOOT_PART " present\\n");''', '''\t\tlist_dir("/dev/block", 's');
\t\tfor (;;)
\t\t\tpause1s(&five);
\t}
\tout("corot-log: " BOOT_PART " present\\n");''', 1)
s = s.replace('''\t\tlist_dir("/dev/block", 's');
\t\tfor (;;)
\t\t\tnanosleep_(&five);
\t}
\tout("corot-log: cust mounted rw\\n");''', '''\t\tlist_dir("/dev/block", 's');
\t\tfor (;;)
\t\t\tpause1s(&five);
\t}
\tout("corot-log: cust mounted rw\\n");''', 1)
s = s.replace('''\tif (g_log < 0) {
\t\tout("corot-log: cannot create " LOG_PATH "\\n");
\t\tfor (;;)
\t\t\tnanosleep_(&five);
\t}''', '''\tif (g_log < 0) {
\t\tout("corot-log: cannot create " LOG_PATH "\\n");
\t\tfor (;;)
\t\t\tpause1s(&five);
\t}''', 1)

# 5) main loop: telemetry every 2s
old = '''\t\tif (++hb % 6 == 0) { /* ~5s cadence via 6 short sleeps */'''
new = '''\t\tif (hb % 2 == 0)
\t\t\ttele(hb / 2);
\t\tif (++hb % 6 == 0) { /* ~5s cadence via 6 short sleeps */'''
if old not in s:
    raise SystemExit('hb anchor missing')
s = s.replace(old, new, 1)

p.write_text(s)
print('init-log.c patched: wdt kick + display telemetry')
