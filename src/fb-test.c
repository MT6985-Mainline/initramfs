/* SPDX-License-Identifier: GPL-2.0 */
/* Exercise full-screen damage on the real corot DRM fbdev during capture. */
#include <linux/fb.h>

#define FB_TEST_BYTES (32UL * 1024 * 1024)
static unsigned char frame[FB_TEST_BYTES];
static struct fb_fix_screeninfo fix;
static struct fb_var_screeninfo var;
static long fb_fd = -1;
static long next_tick;
static unsigned int frame_number;
static int reported_absent;
struct fb_test_time { long sec, nsec; };

static long fb_sys(long nr, long a, long b, long c, long d)
{
	register long x0 asm("x0") = a;
	register long x1 asm("x1") = b;
	register long x2 asm("x2") = c;
	register long x3 asm("x3") = d;
	register long x8 asm("x8") = nr;
	asm volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
	return x0;
}

static int has_text(const char *s, const char *wanted)
{
	unsigned int i, j;
	for (i = 0; s[i]; i++) {
		for (j = 0; wanted[j] && s[i + j] == wanted[j]; j++)
			;
		if (!wanted[j])
			return 1;
	}
	return 0;
}

static int is_native_framebuffer(const char id[16])
{
	static const char expected[] = "mediatekdrmfb";
	unsigned int i;

	for (i = 0; i < sizeof(expected) - 1; i++)
		if (id[i] != expected[i])
			return 0;
	return id[i] == 0;
}

static char *append_number(char *p, unsigned long n)
{
	char digits[24];
	unsigned int count = 0;
	do {
		digits[count++] = '0' + n % 10;
		n /= 10;
	} while (n);
	while (count)
		*p++ = digits[--count];
	return p;
}

static void report_frame(void (*log)(const char *), unsigned long bytes)
{
	char line[160], *p = line;
	const char *s = "fb-test: mediatekdrmfb frame=";
	while (*s)
		*p++ = *s++;
	p = append_number(p, frame_number);
	*p++ = ' ';
	p = append_number(p, var.xres);
	*p++ = 'x';
	p = append_number(p, var.yres);
	*p++ = ' ';
	p = append_number(p, var.bits_per_pixel);
	s = "bpp pitch=";
	while (*s)
		*p++ = *s++;
	p = append_number(p, fix.line_length);
	s = " written=";
	while (*s)
		*p++ = *s++;
	p = append_number(p, bytes);
	*p++ = '\n';
	*p = 0;
	log(line);
}

static unsigned int channel(unsigned int color, struct fb_bitfield field)
{
	if (!field.length)
		return 0;
	return (color * ((1U << field.length) - 1) / 255) << field.offset;
}

static int display_pin_line(const char *line)
{
	static const char * const selected[] = {
		"pin 19 (", "pin 39 (", "pin 40 (", "pin 68 (",
		"pin 85 (", "pin 86 (", "pin 219 (",
	};
	unsigned int i;

	for (i = 0; i < sizeof(selected) / sizeof(selected[0]); i++)
		if (has_text(line, selected[i]))
			return 1;
	return 0;
}

static void report_pin_line(void (*log)(const char *), const char *line)
{
	const char prefix[] = "corot-pin: ";
	char report[224];
	unsigned int i = 0, j;

	if (!display_pin_line(line))
		return;
	for (j = 0; prefix[j]; j++)
		report[i++] = prefix[j];
	for (j = 0; line[j] && i < sizeof(report) - 2; j++)
		report[i++] = line[j];
	report[i++] = '\n';
	report[i] = 0;
	log(report);
}

static void report_display_pins(void (*log)(const char *), unsigned long seconds)
{
	char buffer[4096], line[192], heading[80], *p = heading;
	const char *text = "corot-pin: snapshot monotonic=";
	unsigned int reads, i, used = 0;
	int truncated = 0;
	long fd, n;

	while (*text)
		*p++ = *text++;
	p = append_number(p, seconds);
	*p++ = 's'; *p++ = '\n'; *p = 0;
	log(heading);
	/* The compiled native provider identifies itself as pinctrl_paris. */
	fd = fb_sys(56, -100,
		(long)"/sys/kernel/debug/pinctrl/10005000.pinctrl-pinctrl_paris/pins",
		0, 0);
	if (fd < 0) {
		log("corot-pin: native pinctrl debugfs unavailable\n");
		return;
	}
	/* Limit diagnostic reads to 64 KiB before resuming pattern rendering. */
	for (reads = 0; reads < 16; reads++) {
		n = fb_sys(63, fd, (long)buffer, sizeof(buffer), 0);
		if (n <= 0)
			break;
		for (i = 0; i < (unsigned long)n; i++) {
			if (buffer[i] == '\n') {
				line[used] = 0;
				if (!truncated)
					report_pin_line(log, line);
				used = 0;
				truncated = 0;
			} else if (used < sizeof(line) - 1) {
				line[used++] = buffer[i];
			} else {
				truncated = 1;
			}
		}
	}
	if (used && !truncated) {
		line[used] = 0;
		report_pin_line(log, line);
	}
	fb_sys(57, fd, 0, 0, 0);
}

/* --- bounded SMI/IOMMU port-state probe ---------------------------- */
#define COROT_SMI_LARB_PORTS 9
static long smi_mem_fd = -1;
static volatile unsigned int *smi_larb[4];
static volatile unsigned int *smi_common;
static volatile unsigned int *smi_subcomm;
static volatile unsigned int *smi_iommu;
static int smi_probe_initialized;

static char *append_text(char *p, const char *s)
{
	while (*s)
		*p++ = *s++;
	return p;
}

static char *append_hex32(char *p, unsigned int value)
{
	static const char digits[] = "0123456789abcdef";
	int shift;

	for (shift = 28; shift >= 0; shift -= 4)
		*p++ = digits[(value >> shift) & 0xf];
	return p;
}

static long map_smi_page(unsigned long pa)
{
	register long x0 asm("x0") = 0;
	register long x1 asm("x1") = 4096;
	register long x2 asm("x2") = 1; /* PROT_READ */
	register long x3 asm("x3") = 1; /* MAP_SHARED */
	register long x4 asm("x4") = smi_mem_fd;
	register long x5 asm("x5") = pa;
	register long x8 asm("x8") = 222;

	asm volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3),
		     "r"(x4), "r"(x5), "r"(x8) : "memory");
	return x0;
}

static int is_active_state(const char *s)
{
	return s[0] == 'a' && s[1] == 'c' && s[2] == 't' && s[3] == 'i' &&
	       s[4] == 'v' && s[5] == 'e' && (s[6] == '\n' || s[6] == 0);
}

static int iommu_runtime_active(void)
{
	char buffer[32];
	long fd, n;

	fd = fb_sys(56, -100,
		(long)"/sys/devices/platform/1e802000.iommu/power/runtime_status",
		0, 0);
	if (fd < 0)
		return -1;
	n = fb_sys(63, fd, (long)buffer, sizeof(buffer) - 1, 0);
	fb_sys(57, fd, 0, 0, 0);
	if (n <= 0)
		return -1;
	buffer[n] = 0;
	return is_active_state(buffer);
}

static void log_map_failure(void (*log)(const char *), unsigned long pa, long ret)
{
	char line[128], *p = line;

	p = append_text(p, "corot-smi: mmap failed pa=0x");
	p = append_hex32(p, (unsigned int)pa);
	p = append_text(p, " ret=0x");
	p = append_hex32(p, (unsigned int)ret);
	*p++ = '\n';
	*p = 0;
	log(line);
}

static void report_smi_larb(void (*log)(const char *), unsigned long seconds,
			    const char *name, volatile unsigned int *base)
{
	static const unsigned int key_ports[] = {1, 2, 4, 5, 6};
	char line[320], *p;
	unsigned int i, port, raw, ostd;

	if (!base)
		return;
	p = line;
	p = append_text(p, "corot-smi: snap=");
	p = append_number(p, seconds);
	p = append_text(p, "s ");
	p = append_text(p, name);
	p = append_text(p, " thr=0x");
	p = append_hex32(p, base[0x024 / 4]);
	p = append_text(p, " sw=0x");
	p = append_hex32(p, base[0x040 / 4]);
	p = append_text(p, " ports=");
	for (i = 0; i < COROT_SMI_LARB_PORTS; i++) {
		p = append_hex32(p, base[(0x380 + i * 4) / 4]);
		*p++ = ' ';
	}
	*p = 0;
	log(line);

	p = line;
	p = append_text(p, "corot-smi: snap=");
	p = append_number(p, seconds);
	p = append_text(p, "s ");
	p = append_text(p, name);
	p = append_text(p, " key=");
	for (i = 0; i < sizeof(key_ports) / sizeof(key_ports[0]); i++) {
		port = key_ports[i];
		raw = base[(0x380 + port * 4) / 4];
		ostd = base[(0x200 + port * 4) / 4];
		p = append_text(p, "p");
		p = append_number(p, port);
		p = append_text(p, ":mmu");
		*p++ = '0' + (raw & 1);
		p = append_text(p, ",bank");
		*p++ = '0' + ((raw >> 8) & 3);
		p = append_text(p, ",ostd=0x");
		p = append_hex32(p, ostd);
		*p++ = ' ';
	}
	*p = 0;
	log(line);
}

static void report_smi_common(void (*log)(const char *), unsigned long seconds,
			      const char *name, volatile unsigned int *base)
{
	char line[192], *p;

	if (!base)
		return;
	p = line;
	p = append_text(p, "corot-smi: snap=");
	p = append_number(p, seconds);
	p = append_text(p, "s ");
	p = append_text(p, name);
	p = append_text(p, " l1len=0x");
	p = append_hex32(p, base[0x100 / 4]);
	p = append_text(p, " preultra=0x");
	p = append_hex32(p, base[0x244 / 4]);
	p = append_text(p, " dummy=0x");
	p = append_hex32(p, base[0x444 / 4]);
	*p = 0;
	log(line);
}

static void report_smi_iommu(void (*log)(const char *), unsigned long seconds)
{
	char line[256], *p;
	int active;

	if (!smi_iommu)
		return;
	active = iommu_runtime_active();
	p = line;
	p = append_text(p, "corot-smi: snap=");
	p = append_number(p, seconds);
	p = append_text(p, "s iommu@1e802000 runtime=");
	p = append_text(p, active == 1 ? "active" :
			(active == 0 ? "suspended" : "unknown"));
	if (active != 1) {
		*p = 0;
		log(line);
		return;
	}
	p = append_text(p, " pt=0x");
	p = append_hex32(p, smi_iommu[0x000 / 4]);
	p = append_text(p, " ctrl=0x");
	p = append_hex32(p, smi_iommu[0x110 / 4]);
	p = append_text(p, " ivrp=0x");
	p = append_hex32(p, smi_iommu[0x114 / 4]);
	p = append_text(p, " int0=0x");
	p = append_hex32(p, smi_iommu[0x120 / 4]);
	p = append_text(p, " main=0x");
	p = append_hex32(p, smi_iommu[0x124 / 4]);
	p = append_text(p, " f0=0x");
	p = append_hex32(p, smi_iommu[0x130 / 4]);
	p = append_text(p, " f1=0x");
	p = append_hex32(p, smi_iommu[0x134 / 4]);
	*p = 0;
	log(line);
}

static void report_smi_state(void (*log)(const char *), unsigned long seconds)
{
	static const unsigned long larb_pa[4] = {
		0x1440c000UL, 0x1440d000UL, 0x1460c000UL, 0x1460d000UL,
	};
	static const char *const larb_name[4] = {
		"larb0@1440c000", "larb1@1440d000",
		"larb20@1460c000", "larb21@1460d000",
	};
	long mapping;
	unsigned int i;

	if (!smi_probe_initialized) {
		smi_probe_initialized = 1;
		smi_mem_fd = fb_sys(56, -100, (long)"/dev/mem", 2, 0);
		if (smi_mem_fd < 0) {
			log("corot-smi: /dev/mem unavailable\n");
			return;
		}
		for (i = 0; i < 4; i++) {
			mapping = map_smi_page(larb_pa[i]);
			if (mapping < 0)
				log_map_failure(log, larb_pa[i], mapping);
			else
				smi_larb[i] = (volatile unsigned int *)mapping;
		}
		mapping = map_smi_page(0x1e801000UL);
		if (mapping < 0)
			log_map_failure(log, 0x1e801000UL, mapping);
		else
			smi_common = (volatile unsigned int *)mapping;
		mapping = map_smi_page(0x1440e000UL);
		if (mapping < 0)
			log_map_failure(log, 0x1440e000UL, mapping);
		else
			smi_subcomm = (volatile unsigned int *)mapping;
		mapping = map_smi_page(0x1e802000UL);
		if (mapping < 0)
			log_map_failure(log, 0x1e802000UL, mapping);
		else
			smi_iommu = (volatile unsigned int *)mapping;
	}
	for (i = 0; i < 4; i++)
		report_smi_larb(log, seconds, larb_name[i], smi_larb[i]);
	report_smi_common(log, seconds, "common@1e801000", smi_common);
	report_smi_common(log, seconds, "subcomm@1440e000", smi_subcomm);
	report_smi_iommu(log, seconds);
}

void corot_smi_snapshot(void (*log)(const char *))
{
	struct fb_test_time now;

	if (fb_sys(113, 1, (long)&now, 0, 0))
		return;
	report_smi_state(log, now.sec);
}

static void detach_fb_console(void (*log)(const char *))
{
	char path[] = "/sys/class/vtconsole/vtcon0/name";
	char name[96];
	long fd, n;
	unsigned int index;
	const unsigned int digit = sizeof("/sys/class/vtconsole/vtcon") - 1;
	const unsigned int attribute = digit + 2;
	for (index = 0; index < 4; index++) {
		path[digit] = '0' + index;
		path[attribute] = 'n'; path[attribute + 1] = 'a'; path[attribute + 2] = 'm'; path[attribute + 3] = 'e'; path[attribute + 4] = 0;
		fd = fb_sys(56, -100, (long)path, 0, 0);
		if (fd < 0)
			continue;
		n = fb_sys(63, fd, (long)name, sizeof(name) - 1, 0);
		fb_sys(57, fd, 0, 0, 0);
		if (n <= 0)
			continue;
		name[n] = 0;
		if (!has_text(name, "frame buffer"))
			continue;
		path[attribute] = 'b'; path[attribute + 1] = 'i'; path[attribute + 2] = 'n'; path[attribute + 3] = 'd';
		fd = fb_sys(56, -100, (long)path, 1, 0);
		if (fd >= 0) {
			if (fb_sys(64, fd, (long)"0", 1, 0) == 1)
				log("fb-test: detached fb console for bounded color-pattern test\n");
			fb_sys(57, fd, 0, 0, 0);
		}
	}
}

void corot_fb_test_step(void (*log)(const char *))
{
	struct fb_test_time now;
	unsigned long size, offset;
	unsigned int x, y, bytes_per_pixel, pixel, r, g, b, i, sweep;
	long written;
	static unsigned int pin_snapshots;
	if (fb_sys(113, 1, (long)&now, 0, 0) || now.sec < next_tick)
		return;
	next_tick = now.sec + 5;
	if (pin_snapshots++ < 3) {
		report_display_pins(log, now.sec);
		report_smi_state(log, now.sec);
	}
	if (fb_fd < 0) {
		fb_fd = fb_sys(56, -100, (long)"/dev/fb0", 2, 0);
		if (fb_fd < 0) {
			if (!reported_absent++)
				log("fb-test: waiting for native DRM framebuffer\n");
			return;
		}
		if (fb_sys(29, fb_fd, FBIOGET_FSCREENINFO, (long)&fix, 0) ||
		    fb_sys(29, fb_fd, FBIOGET_VSCREENINFO, (long)&var, 0) ||
		    !is_native_framebuffer(fix.id) ||
		    var.xres != 1220 || var.yres != 2712 ||
		    (var.bits_per_pixel != 16 && var.bits_per_pixel != 32) ||
		    var.red.msb_right || var.green.msb_right || var.blue.msb_right ||
		    var.transp.msb_right || var.red.length > 16 || var.green.length > 16 ||
		    var.blue.length > 16 || var.transp.length > 16 ||
		    var.red.offset + var.red.length > var.bits_per_pixel ||
		    var.green.offset + var.green.length > var.bits_per_pixel ||
		    var.blue.offset + var.blue.length > var.bits_per_pixel ||
		    var.transp.offset + var.transp.length > var.bits_per_pixel ||
		    var.xoffset || var.yoffset ||
		    fix.line_length < var.xres * (var.bits_per_pixel / 8) ||
		    (unsigned long)fix.line_length * var.yres > FB_TEST_BYTES ||
		    (unsigned long)fix.line_length * var.yres > fix.smem_len) {
			log("fb-test: framebuffer is not a valid full-size corot native scanout\n");
			fb_sys(57, fb_fd, 0, 0, 0);
			fb_fd = -1;
			return;
		}
		detach_fb_console(log);
		fb_sys(29, fb_fd, FBIOBLANK, FB_BLANK_UNBLANK, 0);
		log("fb-test: quadrants red/green/blue/white, white vertical bar moves every 5s\n");
	}
	size = (unsigned long)fix.line_length * var.yres;
	bytes_per_pixel = var.bits_per_pixel / 8;
	sweep = (frame_number * 61) % var.xres;
	for (y = 0; y < var.yres; y++) {
		for (x = 0; x < var.xres; x++) {
			r = g = b = 0;
			if (y < var.yres / 2) {
				if (x < var.xres / 2) r = 255;
				else g = 255;
			} else if (x < var.xres / 2) b = 255;
			else r = g = b = 255;
			if (x >= sweep && x < sweep + 16) r = g = b = 255;
			if (x == var.xres / 2 || y == var.yres / 2 ||
			    !x || !y || x == var.xres - 1 || y == var.yres - 1) r = g = b = 0;
			pixel = channel(r, var.red) | channel(g, var.green) |
				channel(b, var.blue) | channel(255, var.transp);
			offset = (unsigned long)y * fix.line_length + x * bytes_per_pixel;
			for (i = 0; i < bytes_per_pixel; i++) frame[offset + i] = pixel >> (8 * i);
		}
	}
	written = fb_sys(68, fb_fd, (long)frame, size, 0);
	if (written != (long)size) {
		log("fb-test: full-frame write failed or was short\n");
		return;
	}
	report_frame(log, written);
	frame_number++;
}
