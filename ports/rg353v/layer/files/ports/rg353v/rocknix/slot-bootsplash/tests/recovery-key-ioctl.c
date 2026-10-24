// SPDX-License-Identifier: GPL-2.0-or-later
// Model evdev query responses; filesystem discovery and model parsing stay real.
#define _GNU_SOURCE
#include <errno.h>
#include <linux/input.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
static int scenario(const char *name) {
    const char *value = getenv("SLOT_TEST_KEY");
    return value && !strcmp(value, name);
}
int slot_test_fstat(int fd, struct stat *s) {
    (void)fd;
    memset(s, 0, sizeof(*s));
    s->st_mode = scenario("not-char") ? S_IFREG : S_IFCHR;
    return 0;
}
int slot_test_ioctl(int fd, unsigned long request, ...) {
    (void)fd;
    va_list ap;
    va_start(ap, request);
    unsigned char *out = va_arg(ap, void *);
    va_end(ap);
    if (_IOC_NR(request) == _IOC_NR(EVIOCGNAME(64))) {
        if (scenario("name-error")) { errno = EIO; return -1; }
        strcpy((char *)out, scenario("wrong-name") ? "other-input" : "gpio-keys-vol");
    } else if (_IOC_NR(request) == _IOC_NR(EVIOCGBIT(EV_KEY, 96))) {
        if (scenario("caps-error")) { errno = EIO; return -1; }
        if (!scenario("missing-key")) out[KEY_VOLUMEDOWN / 8] |= 1u << (KEY_VOLUMEDOWN % 8);
        out[KEY_VOLUMEUP / 8] |= 1u << (KEY_VOLUMEUP % 8);
    } else if (_IOC_NR(request) == _IOC_NR(EVIOCGKEY(96))) {
        if (scenario("read-error")) { errno = EIO; return -1; }
        if (scenario("held") || scenario("both")) out[KEY_VOLUMEDOWN / 8] |= 1u << (KEY_VOLUMEDOWN % 8);
        if (scenario("up") || scenario("both")) out[KEY_VOLUMEUP / 8] |= 1u << (KEY_VOLUMEUP % 8);
    } else { errno = EINVAL; return -1; }
    return (int)_IOC_SIZE(request);
}
