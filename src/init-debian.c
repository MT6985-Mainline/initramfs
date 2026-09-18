/* corot initramfs: mount Debian ext4 on cust and pivot_root into it. */
#define AT_FDCWD -100
#define O_RDONLY 0
#define MS_RDONLY 1
#define MS_NOSUID 2
#define MS_NOEXEC 8
#define MS_RELATIME 0x200000
#define MS_MOVE 0x2000
#define MNT_DETACH 2

struct timespec { long tv_sec; long tv_nsec; };

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
{ return ksys(40, (long)src, (long)tgt, (long)type, flags, (long)data); }
static long umount2_(const char *path, long flags)
{ return ksys(39, (long)path, flags, 0, 0, 0); }
static long open_(const char *path, long flags)
{ return ksys(56, AT_FDCWD, (long)path, flags, 0, 0); }
static long close_(long fd)
{ return ksys(57, fd, 0, 0, 0, 0); }
static long write_(long fd, const char *s, long n)
{ return ksys(64, fd, (long)s, n, 0, 0); }
static long mkdir_(const char *path, long mode)
{ return ksys(34, AT_FDCWD, (long)path, mode, 0, 0); }
static long chdir_(const char *path)
{ return ksys(49, (long)path, 0, 0, 0, 0); }
static long pivot_root_(const char *newroot, const char *putold)
{ return ksys(41, (long)newroot, (long)putold, 0, 0, 0); }
static long execve_(const char *path, char *const argv[], char *const envp[])
{ return ksys(221, (long)path, (long)argv, (long)envp, 0, 0); }
static long nanosleep_(const struct timespec *ts)
{ return ksys(101, (long)ts, 0, 0, 0, 0); }
static int slen(const char *s) { int n=0; while (s[n]) n++; return n; }
static void msg(const char *s)
{
	long fd = open_("/dev/kmsg", 1);
	if (fd >= 0) { write_(fd, s, slen(s)); close_(fd); }
}

void _start(void)
{
	struct timespec ts = { 1, 0 };
	char *argv[] = { (char *)"/sbin/init", 0 };
	char *envp[] = { (char *)"PATH=/sbin:/bin:/usr/sbin:/usr/bin", 0 };
	int i;
	long fd;

	mkdir_("/dev", 0755); mkdir_("/proc", 0755); mkdir_("/sys", 0755);
	mkdir_("/newroot", 0755); mkdir_("/newroot/oldroot", 0755);
	mount_("devtmpfs", "/dev", "devtmpfs", MS_NOSUID | MS_NOEXEC, "mode=0755");
	mount_("proc", "/proc", "proc", MS_NOSUID | MS_NOEXEC | MS_RELATIME, 0);
	mount_("sysfs", "/sys", "sysfs", MS_NOSUID | MS_NOEXEC | MS_RELATIME, 0);
	msg("corot-init: waiting for UFS cust /dev/sdc80\n");
	for (i = 0; i < 30; i++) {
		fd = open_("/dev/sdc80", O_RDONLY);
		if (fd >= 0) { close_(fd); break; }
		nanosleep_(&ts);
	}
	if (i == 30) {
		msg("corot-init: /dev/sdc80 missing\n");
		for (;;) nanosleep_(&ts);
	}
	msg("corot-init: mounting Debian cust ext4\n");
	if (mount_("/dev/sdc80", "/newroot", "ext4", MS_RDONLY, 0) < 0) {
		msg("corot-init: cust mount failed\n");
		for (;;) nanosleep_(&ts);
	}
	mount_("/dev", "/newroot/dev", 0, MS_MOVE, 0);
	mount_("/proc", "/newroot/proc", 0, MS_MOVE, 0);
	mount_("/sys", "/newroot/sys", 0, MS_MOVE, 0);
	if (pivot_root_("/newroot", "/newroot/oldroot") < 0) {
		msg("corot-init: pivot_root failed\n");
		for (;;) nanosleep_(&ts);
	}
	chdir_("/");
	umount2_("/oldroot", MNT_DETACH);
	mkdir_("/dev/pts", 0755);
	mount_("devpts", "/dev/pts", "devpts", 0, "gid=5,mode=620");
	msg("corot-init: starting Debian TTY init\n");
	execve_("/sbin/init", argv, envp);
	msg("corot-init: exec Debian init failed\n");
	for (;;) nanosleep_(&ts);
}
