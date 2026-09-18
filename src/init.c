/*
 * Minimal no-libc init for corot mainline bring-up.
 * Mounts virtual filesystems, prints a heartbeat, lists block devices,
 * and stays alive so printk / simplefb / log_store can be captured.
 */
#ifndef BOOT_PARTITION
#define BOOT_PARTITION "/dev/sdc80"
#endif

#define AT_FDCWD -100
#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 0x40
#define O_TRUNC 0x200
#define MS_NOSUID 2
#define MS_NOEXEC 8
#define MS_RELATIME 0x200000

struct timespec {
	long tv_sec;
	long tv_nsec;
};

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

static long mount_(const char *src, const char *tgt, const char *fstype,
		   unsigned long flags, const void *data)
{
	return ksys(40, (long)src, (long)tgt, (long)fstype, flags, (long)data);
}

static long openat(long dirfd, const char *path, long flags, long mode)
{
	return ksys(56, dirfd, (long)path, flags, mode, 0);
}

static long close_(long fd)
{
	return ksys(57, fd, 0, 0, 0, 0);
}

static long write_(long fd, const void *buf, long n)
{
	return ksys(64, fd, (long)buf, n, 0, 0);
}

static long nanosleep_(const struct timespec *ts)
{
	return ksys(101, (long)ts, 0, 0, 0, 0);
}

static long mkdirat(long dirfd, const char *path, long mode)
{
	return ksys(34, dirfd, (long)path, mode, 0, 0);
}

static long getdents64(long fd, void *buf, long n)
{
	return ksys(217, fd, (long)buf, n, 0, 0);
}

static int slen(const char *s)
{
	int n = 0;
	while (s[n])
		n++;
	return n;
}

static void puts_fd(long fd, const char *s)
{
	if (fd >= 0)
		write_(fd, s, slen(s));
}

static void puts_all(const char *s)
{
	long k = openat(AT_FDCWD, "/dev/kmsg", O_WRONLY, 0);
	long t = openat(AT_FDCWD, "/dev/tty0", O_WRONLY, 0);
	puts_fd(1, s);
	puts_fd(k, s);
	puts_fd(t, s);
	if (k >= 0)
		close_(k);
	if (t >= 0)
		close_(t);
}

static void list_dev(void)
{
	char buf[4096];
	long fd = openat(AT_FDCWD, "/dev", O_RDONLY, 0);
	long n;
	if (fd < 0) {
		puts_all("corot-init: cannot open /dev\n");
		return;
	}
	puts_all("corot-init: /dev listing\n");
	while ((n = getdents64(fd, buf, sizeof(buf))) > 0) {
		long off = 0;
		while (off < n) {
			struct dirent64 *de = (struct dirent64 *)(buf + off);
			if (de->d_name[0] == 's' || de->d_name[0] == 'm' ||
			    de->d_name[0] == 'u' || de->d_name[0] == 't' ||
			    de->d_name[0] == 'f') {
				puts_all("  ");
				puts_all(de->d_name);
				puts_all("\n");
			}
			off += de->d_reclen;
		}
	}
	close_(fd);
}

void _start(void)
{
	struct timespec ts = { .tv_sec = 2, .tv_nsec = 0 };
	int i;

	mkdirat(AT_FDCWD, "/dev", 0755);
	mkdirat(AT_FDCWD, "/proc", 0755);
	mkdirat(AT_FDCWD, "/sys", 0755);
	mkdirat(AT_FDCWD, "/newroot", 0755);
	mount_("devtmpfs", "/dev", "devtmpfs", MS_NOSUID | MS_NOEXEC, "mode=0755");
	mount_("proc", "/proc", "proc", MS_NOSUID | MS_NOEXEC | MS_RELATIME, 0);
	mount_("sysfs", "/sys", "sysfs", MS_NOSUID | MS_NOEXEC | MS_RELATIME, 0);

	puts_all("corot-init: mainline initramfs started\n");
	puts_all("corot-init: BOOT_PARTITION=" BOOT_PARTITION "\n");

	for (i = 0; i < 30; i++) {
		list_dev();
		puts_all("corot-init: heartbeat\n");
		nanosleep_(&ts);
	}

	puts_all("corot-init: staying alive; no switch_root (UFS may be absent)\n");
	for (;;)
		nanosleep_(&ts);
}
