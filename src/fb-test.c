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
	if (pin_snapshots++ < 3)
		report_display_pins(log, now.sec);
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
