/*
 * corot log-catcher initramfs: mirror /dev/kmsg into cust (ext4).
 *
 * Stage-1 bring-up channel: instead of pivoting into a rootfs, this init
 * mounts cust rw and appends the kernel log (plus its own phase markers
 * and heartbeats) to /newroot/boot-log.txt with fsync. Whatever happens
 * afterwards - hang, panic, watchdog - the tail stays on flash and can be
 * read back from Android: adb root; mount /dev/block/by-name/cust; cat
 * /mnt/cust/boot-log.txt
 *
 * ARM64 raw syscalls: mount=40 openat=56 close=57 read=63 write=64
 * fsync=82 mkdirat=34 getdents64=61 nanosleep=101
 */
#define AT_FDCWD -100
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 0x40
#define O_TRUNC 0x200
#define O_APPEND 0x400
#define O_NONBLOCK 0x800
#define MS_NOSUID 2
#define MS_NOEXEC 8
#define MS_RELATIME 0x200000

#define BOOT_PART "/dev/sdc80"
#define LOG_PATH "/newroot/boot-log.txt"

struct timespec { long tv_sec; long tv_nsec; };

struct dirent64 {
	unsigned long long d_ino;
	long long d_off;
	unsigned short d_reclen;
	unsigned char d_type;
	char d_name[];
};

static long ksys(long n, long a, long b, long c, long d, long e)
{
	register long x0 asm("x0") = a;
	register long x1 asm("x1") = b;
	register long x2 asm("x2") = c;
	register long x3 asm("x3") = d;
	register long x4 asm("x4") = e;
	register long x8 asm("x8") = n;
	asm volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x8) : "memory");
	return x0;
}

static long mount_(const char *src, const char *tgt, const char *type,
		   unsigned long flags, const void *data)
{
	return ksys(40, (long)src, (long)tgt, (long)type, flags, (long)data);
}
static long openat_(const char *path, long flags, long mode)
{
	return ksys(56, AT_FDCWD, (long)path, flags, mode, 0);
}
static long close_(long fd) { return ksys(57, fd, 0, 0, 0, 0); }
static long read_(long fd, void *buf, long n) { return ksys(63, fd, (long)buf, n, 0, 0); }
static long write_(long fd, const void *buf, long n) { return ksys(64, fd, (long)buf, n, 0, 0); }
static long fsync_(long fd) { return ksys(82, fd, 0, 0, 0, 0); }
static long mkdirat_(const char *path, long mode)
{
	return ksys(34, AT_FDCWD, (long)path, mode, 0, 0);
}
static long getdents64_(long fd, void *buf, long n)
{
	return ksys(61, fd, (long)buf, n, 0, 0);
}
static long nanosleep_(const struct timespec *ts)
{
	return ksys(101, (long)ts, 0, 0, 0, 0);
}
/* pread64: x0=fd x1=buf x2=count x3=offset(64-bit) */
static long pread64_(long fd, void *buf, long n, long off)
{
	return ksys(67, fd, (long)buf, n, off, 0);
}
/* pwrite64: x0=fd x1=buf x2=count x3=offset(64-bit) */
static long pwrite64_(long fd, const void *buf, long n, long off)
{
	return ksys(68, fd, (long)buf, n, off, 0);
}

static void hex8(char *dst, unsigned long v)
{
	static const char hx[] = "0123456789abcdef";
	int i;
	for (i = 7; i >= 0; i--) {
		dst[i] = hx[v & 0xf];
		v >>= 4;
	}
}

static char fbuf[1 << 20];
static void out(const char *s);
static long g_log;

/*
 * Find the real LK scanout address: the videolfb tag base (0xfd91f000) is
 * the reserved-region start, not necessarily the live scanout (same trap as
 * xaga). Read the whole reserved framebuffer range through /dev/mem and log
 * a nonzero-density map so the live layer can be located by comparing which
 * MB block holds the LK logo vs our fbcon text at region start.
 */
static void fb_scan(void)
{
	static const unsigned long base = 0xfd91f000UL;
	static const unsigned long size = 0x026e0000UL;
	unsigned long off;
	long fd = openat_("/dev/mem", O_RDONLY, 0);

	if (fd < 0) {
		out("fbscan: no /dev/mem\n");
		return;
	}
	out("fbscan: mapping map of 0xfd91f000+0x26e0000 follows\n");
	for (off = 0; off < size; off += sizeof(fbuf)) {
		long n = pread64_(fd, fbuf, sizeof(fbuf), (long)(base + off));
		unsigned long i, nz = 0, d0 = 0, d1 = 0;
		char line[72];

		if (n <= 0) {
			out("fbscan: read failed, stopping\n");
			break;
		}
		for (i = 0; i < (unsigned long)n; i++)
			if (fbuf[i])
				nz++;
		if (n >= 8) {
			d0 = *(volatile unsigned long *)(fbuf);
			d1 = *(volatile unsigned long *)(fbuf + 8);
		}
		if (nz || (off & 0xffffff) == 0) {
			line[0] = 'f'; line[1] = 'b'; line[2] = 's'; line[3] = 'c';
			line[4] = 'a'; line[5] = 'n'; line[6] = ' '; line[7] = '0';
			line[8] = 'x'; hex8(line + 9, base + off);
			line[17] = ' '; line[18] = 'n'; line[19] = 'z'; line[20] = '=';
			line[21] = '0'; line[22] = 'x'; hex8(line + 23, nz);
			line[31] = ' '; line[32] = 'd'; line[33] = '0'; line[34] = '=';
			line[35] = '0'; line[36] = 'x'; hex8(line + 37, d0);
			line[45] = ' '; line[46] = 'd'; line[47] = '1'; line[48] = '=';
			line[49] = '0'; line[50] = 'x'; hex8(line + 51, d1);
			line[59] = '\n'; line[60] = 0;
			out(line);
			fsync_(g_log);
		}
	}
	close_(fd);
	out("fbscan: done\n");
}

static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }

static long g_log = -1;
static long g_kmsg_w = -1;
static long g_serial = -1;

static void out(const char *s)
{
	if (g_log >= 0)
		write_(g_log, s, slen(s));
	if (g_kmsg_w >= 0)
		write_(g_kmsg_w, s, slen(s));
	if (g_serial >= 0)
		write_(g_serial, s, slen(s));
}

/* file-only note (no console echo, avoids read-back duplication) */
static void note(const char *s)
{
	if (g_log >= 0)
		write_(g_log, s, slen(s));
}

/* --- watchdog + display telemetry ---------------------------------- */
static long g_mem = -1;

#define WDT_RESTART_PA 0x1c007008UL
#define WDT_KEY 0x1971U

/* reboot(LINUX_REBOOT_CMD_RESTART2, "bootloader") */
static void reboot_bootloader(void)
{
	static const char arg[] = "bootloader";
	ksys(142, (long)0xfee1deadUL, (long)0x28121969UL, (long)0xa932fb52UL,
	     (long)arg, 0);
}

static void wdt_kick(void)
{
	unsigned int v = WDT_KEY;
	if (g_mem >= 0)
		pwrite64_(g_mem, &v, 4, (long)WDT_RESTART_PA);
}

/* sleep one second, kicking the watchdog so bring-up kernels survive */
static void pause1s(const struct timespec *ts)
{
	wdt_kick();
	nanosleep_(ts);
}

static unsigned int rd32(unsigned long pa)
{
	unsigned int v = 0;
	pread64_(g_mem, &v, 4, (long)pa);
	return v;
}

static void tele(int n)
{
	char line[240];
	int m = 0, i;
	static const unsigned long dsi = 0x1400d000UL;
	static const unsigned long mutex = 0x14001000UL;
	static const unsigned long ovl = 0x14402000UL;
	static const unsigned long gce = 0x1e980000UL;
	static const unsigned long dsi_off[6] = { 0x00, 0x08, 0x0c, 0x10, 0x14, 0x18 };
	static const unsigned long gth_off[3] = { 0x00, 0x20, 0x24 };

	if (g_mem < 0)
		return;
	m = 0;
	line[m++] = 't'; line[m++] = 'e'; line[m++] = 'l'; line[m++] = 'e';
	line[m++] = ' ';
	if (n >= 100) line[m++] = '0' + n / 100 % 10;
	if (n >= 10) line[m++] = '0' + n / 10 % 10;
	line[m++] = '0' + n % 10;
	line[m++] = ' ';
	for (i = 0; i < 6; i++) {
		line[m++] = '0'; line[m++] = 'x';
		hex8(line + m, rd32(dsi + dsi_off[i])); m += 8;
		line[m++] = ' ';
	}
	line[m++] = 'm'; line[m++] = 'u'; line[m++] = 'x'; line[m++] = '=';
	line[m++] = '0'; line[m++] = 'x';
	hex8(line + m, rd32(mutex + 0x20)); m += 8;
	line[m++] = ' ';
	line[m++] = 'o'; line[m++] = 'v'; line[m++] = 'l'; line[m++] = '=';
	line[m++] = '0'; line[m++] = 'x';
	hex8(line + m, rd32(ovl + 0x24)); m += 8;
	for (i = 0; i < 2; i++) {
		int j;
		unsigned long th = gce + 0x100 + (i == 0 ? 0 : 3 * 0x80);
		line[m++] = ' ';
		line[m++] = 'g'; line[m++] = '0' + i; line[m++] = '=';
		for (j = 0; j < 3; j++) {
			line[m++] = '0'; line[m++] = 'x';
			hex8(line + m, rd32(th + gth_off[j])); m += 8;
			if (j < 2) line[m++] = ',';
		}
	}
	line[m++] = '\n';
	line[m] = 0;
	if (g_log >= 0) {
		write_(g_log, line, m);
		fsync_(g_log);
	}
}


/*
 * USB bring-up evidence.  The host sees nothing at all from the corot gadget,
 * so record what the device side believes: whether a UDC exists at all, and
 * whether it ever saw the host (the state advances from "not attached" to
 * "default"/"addressed"/"configured" once the host drives a bus reset).
 */
static void cat_sys(const char *path)
{
	char buf[192];
	long fd = openat_(path, O_RDONLY, 0);
	long n;

	out("corot-usb: ");
	out(path);
	out(" = ");
	if (fd < 0) {
		note("(open failed)\n");
		return;
	}
	n = read_(fd, buf, sizeof(buf) - 1);
	close_(fd);
	if (n <= 0) {
		note("(empty)\n");
		return;
	}
	buf[n] = 0;
	while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r'))
		buf[--n] = 0;
	note(buf);
	note("\n");
}

/* path = "/sys/class/udc/" + name + suffix */
static void build_udc_path(char *path, const char *name, const char *suffix)
{
	static const char prefix[] = "/sys/class/udc/";
	int m = 0, k;

	for (k = 0; prefix[k] && m < 150; k++)
		path[m++] = prefix[k];
	for (k = 0; name[k] && m < 150; k++)
		path[m++] = name[k];
	for (k = 0; suffix[k] && m < 180; k++)
		path[m++] = suffix[k];
	path[m] = 0;
}

static void dump_udc(void)
{
	static const char *const suffix[4] = {
		"/state", "/current_speed", "/maximum_speed", "/function" };
	char buf[4096];
	char path[192];
	long fd = openat_("/sys/class/udc", O_RDONLY, 0);
	long n;
	int seen = 0;
	int i;

	if (fd < 0) {
		note("corot-usb: /sys/class/udc missing\n");
		return;
	}
	while ((n = getdents64_(fd, buf, sizeof(buf))) > 0) {
		long off = 0;

		while (off < n) {
			struct dirent64 *de = (struct dirent64 *)(buf + off);

			if (de->d_name[0] != '.') {
				seen++;
				note("corot-usb: UDC ");
				note(de->d_name);
				note("\n");
				for (i = 0; i < 4; i++) {
					build_udc_path(path, de->d_name, suffix[i]);
					cat_sys(path);
				}
			}
			off += de->d_reclen;
		}
	}
	close_(fd);
	if (!seen)
		note("corot-usb: /sys/class/udc is EMPTY (no UDC registered)\n");
}

static void list_dir(const char *path, char prefix)
{
	char buf[4096];
	long fd = openat_(path, O_RDONLY, 0);
	long n;

	if (fd < 0) {
		note("corot-log: cannot open dir\n");
		return;
	}
	out("corot-log: listing ");
	out(path);
	out("\n");
	while ((n = getdents64_(fd, buf, sizeof(buf))) > 0) {
		long off = 0;
		while (off < n) {
			struct dirent64 *de = (struct dirent64 *)(buf + off);
			if (de->d_name[0] == prefix) {
				out("  ");
				out(de->d_name);
				out("\n");
			}
			off += de->d_reclen;
		}
	}
	close_(fd);
}


/* ---- previous-boot crash console (ramoops/pstore) ---- */
static void cat_pstore_file(const char *path)
{
	char buf[8192];
	long fd, n;

	note("corot-log: [pstore] ");
	note(path);
	fd = openat_(path, O_RDONLY, 0);
	if (fd < 0) {
		note(" -> absent\n");
		return;
	}
	note(" -> follows\n");
	while ((n = read_(fd, buf, sizeof(buf))) > 0)
		write_(g_log, buf, n);
	close_(fd);
	note("\ncorot-log: [pstore] end ");
	note(path);
	note("\n");
	fsync_(g_log);
}

static void dump_pstore(void)
{
	note("corot-log: === previous-boot pstore dump ===\n");
	cat_pstore_file("/sys/fs/pstore/console-ramoops-0");
	cat_pstore_file("/sys/fs/pstore/console-ramoops");
	cat_pstore_file("/sys/fs/pstore/dmesg-ramoops-0");
	cat_pstore_file("/sys/fs/pstore/dmesg-ramoops-1");
	note("corot-log: === end previous-boot pstore dump ===\n");
	fsync_(g_log);
}

static void dump_cmdline(void)
{
	char buf[2048];
	long fd = openat_("/proc/cmdline", O_RDONLY, 0);
	long n;

	if (fd < 0) {
		note("corot-log: no /proc/cmdline\n");
		return;
	}
	n = read_(fd, buf, sizeof(buf) - 1);
	close_(fd);
	if (n > 0) {
		buf[n] = '\n';
		out("corot-log: cmdline: ");
		write_(g_log >= 0 ? g_log : 1, buf, n + 1);
	}
}

void _start(void)
{
	static char kbuf[4096];
	struct timespec one = { 1, 0 };
	struct timespec five = { 5, 0 };
	long kmsg_rd;
	int i, hb = 0;

	mkdirat_("/dev", 0755);
	mkdirat_("/proc", 0755);
	mkdirat_("/sys", 0755);
	mkdirat_("/newroot", 0755);
	mount_("devtmpfs", "/dev", "devtmpfs", MS_NOSUID | MS_NOEXEC, "mode=0755");
	mount_("proc", "/proc", "proc", MS_NOSUID | MS_NOEXEC | MS_RELATIME, 0);
	mount_("sysfs", "/sys", "sysfs", MS_NOSUID | MS_NOEXEC | MS_RELATIME, 0);

	g_kmsg_w = openat_("/dev/kmsg", O_WRONLY | O_APPEND, 0);
	kmsg_rd = openat_("/dev/kmsg", O_RDONLY | O_NONBLOCK, 0);

	out("corot-log: initramfs log-catcher started\n");
	g_mem = openat_("/dev/mem", 2 /* O_RDWR */, 0);
	if (g_mem < 0)
		out("corot-log: /dev/mem unavailable; no watchdog kick\n");
	else
		out("corot-log: watchdog kick armed (0x10007008)\n");
	dump_cmdline();

	/* wait for UFS block device */
	for (i = 0; i < 45; i++) {
		long fd = openat_(BOOT_PART, O_RDONLY, 0);
		if (fd >= 0) {
			close_(fd);
			break;
		}
		pause1s(&one);
	}
	if (i == 45) {
		out("corot-log: " BOOT_PART " never appeared\n");
		list_dir("/dev/block", 's');
		for (;;)
			pause1s(&five);
	}
	out("corot-log: " BOOT_PART " present\n");

	if (mount_(BOOT_PART, "/newroot", "ext4", 0, 0) < 0) {
		out("corot-log: cust ext4 mount FAILED\n");
		list_dir("/dev/block", 's');
		for (;;)
			pause1s(&five);
	}
	out("corot-log: cust mounted rw\n");

	g_log = openat_(LOG_PATH, O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0644);
	if (g_log < 0) {
		out("corot-log: cannot create " LOG_PATH "\n");
		for (;;)
			pause1s(&five);
	}
	g_serial = openat_("/dev/ttyGS0", O_WRONLY | O_NONBLOCK, 0);
	if (g_serial >= 0)
		note("corot-log: ttyGS0 logging enabled (usb serial live)\n");
	else
		note("corot-log: ttyGS0 not present; cust logging only\n");
	dump_udc();

	note("corot-log: === boot-log.txt opened; kernel log follows ===\n");
	dump_cmdline();
	dump_pstore();
	list_dir("/dev/block", 's');
	fb_scan();

	/* drain backlog, then stream forever with heartbeats */
	for (;;) {
		long n = read_(kmsg_rd, kbuf, sizeof(kbuf));
		if (n > 0) {
			write_(g_log, kbuf, n);
			if (g_serial >= 0)
				write_(g_serial, kbuf, n);
			/* push every chunk: a WDT reset must not lose the tail */
			fsync_(g_log);
			continue;
		}
		if (hb % 2 == 0) {
			tele(hb / 2);
			/* hand the device back to fastboot after a fixed window */
			if (hb / 2 >= 90) {
				note("corot-log: telemetry window done, reboot to bootloader\n");
				reboot_bootloader();
			}
		}
		if ((hb % 10) == 0)
			dump_udc();
		if (g_serial < 0 && (hb % 5) == 0) {
			g_serial = openat_("/dev/ttyGS0", O_WRONLY | O_NONBLOCK, 0);
			if (g_serial >= 0)
				note("corot-log: ttyGS0 logging enabled (usb serial live)\n");
		}
		if (++hb % 6 == 0) { /* ~5s cadence via 6 short sleeps */
			char line[48];
			int m = 0;
			const char *p = "---- corot-hb ";
			while (*p) { line[m++] = *p++; }
			if (hb / 6 >= 100) { line[m++] = '0' + (hb / 6) / 100 % 10; }
			if (hb / 6 >= 10) { line[m++] = '0' + (hb / 6) / 10 % 10; }
			line[m++] = '0' + (hb / 6) % 10;
			line[m++] = ' ';
			line[m++] = 'a';
			line[m++] = 'l';
			line[m++] = 'i';
			line[m++] = 'v';
			line[m++] = 'e';
			line[m++] = ' ';
			line[m++] = '=';
			line[m++] = '=';
			line[m++] = '\n';
			write_(g_log, line, m);
			fsync_(g_log);
		}
		nanosleep_(&one);
	}
}
