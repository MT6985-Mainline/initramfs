#!/usr/bin/env python3
# Add USB/UDC diagnostics to the real log-catcher init.
import shutil, sys, io

P = "/home/mytiantian/corot-work/corot-initramfs-log/init-log.c"
s = io.open(P, encoding="utf-8").read()

def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        print("FAIL: expected %d found %d for:\n%s" % (count, n, old[:200]))
        sys.exit(1)
    s = s.replace(old, new, count)

HELPERS = r'''
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

static void list_dir(const char *path, char prefix)'''

rep("static void list_dir(const char *path, char prefix)", HELPERS)

rep("""		if (g_serial < 0 && (hb % 5) == 0) {""",
    """		if ((hb % 10) == 0)
			dump_udc();
		if (g_serial < 0 && (hb % 5) == 0) {""")

rep("""		note("corot-log: ttyGS0 logging enabled\\n");
	else
		note("corot-log: ttyGS0 not present; cust logging only\\n");""",
    """		note("corot-log: ttyGS0 logging enabled (usb serial live)\\n");
	else
		note("corot-log: ttyGS0 not present; cust logging only\\n");
	dump_udc();""")

rep("""			if (g_serial >= 0)
				note("corot-log: ttyGS0 logging enabled\\n");""",
    """			if (g_serial >= 0)
				note("corot-log: ttyGS0 logging enabled (usb serial live)\\n");""")

shutil.copy2(P, P + ".pre-usbdiag")
io.open(P, "w", encoding="utf-8").write(s)
print("init-log.c patched")
