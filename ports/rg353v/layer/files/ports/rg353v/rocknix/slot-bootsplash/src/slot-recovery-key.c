// SPDX-License-Identifier: GPL-2.0-or-later
// Read the fixed RG353V volume-key bitmap without consuming input events.
// 0=held, 1=released, 2=unknown: the init script retains its original fallback.
#define _GNU_SOURCE
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
#include <linux/input.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef SLOT_RECOVERY_ROOT
#define SLOT_RECOVERY_ROOT ""
#endif
#define BITS_BYTES ((KEY_MAX + 8) / 8)
static bool bit(const unsigned char *bits, unsigned key) {
    return (bits[key / 8] & (1u << (key % 8))) != 0;
}
static bool model_matches(void) {
    FILE *f = fopen(SLOT_RECOVERY_ROOT "/sys/firmware/devicetree/base/compatible", "rb");
    if (!f) return false;
    char data[512];
    size_t n = fread(data, 1, sizeof(data), f);
    bool valid = !ferror(f) && n > 0 && n < sizeof(data) && data[n - 1] == '\0';
    fclose(f);
    if (!valid) return false;
    for (size_t i = 0; i < n; i += strlen(data + i) + 1)
        if (!strcmp(data + i, "anbernic,rg353v")) return true;
    return false;
}
int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1 || !model_matches()) return 2;
    glob_t paths = {0};
    int status = glob(SLOT_RECOVERY_ROOT "/sys/devices/platform/gpio-keys-vol/input/input*/event*", 0, NULL, &paths);
    if (status || paths.gl_pathc != 1) {
        globfree(&paths);
        return 2;
    }
    const char *event = strrchr(paths.gl_pathv[0], '/');
    if (!event || strncmp(++event, "event", 5) || !event[5] ||
        strspn(event + 5, "0123456789") != strlen(event + 5)) {
        globfree(&paths);
        return 2;
    }
    char path[PATH_MAX];
    int count = snprintf(path, sizeof(path), SLOT_RECOVERY_ROOT "/dev/input/%s", event);
    globfree(&paths);
    if (count < 0 || (size_t)count >= sizeof(path)) return 2;
    int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return 2;
    struct stat st;
    char name[64] = {0};
    unsigned char keys[BITS_BYTES] = {0}, held[BITS_BYTES] = {0};
    int result = 2;
    if (!fstat(fd, &st) && S_ISCHR(st.st_mode) &&
        ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) >= 0 &&
        !strcmp(name, "gpio-keys-vol") &&
        ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(keys)), keys) >= 0 &&
        bit(keys, KEY_VOLUMEDOWN) && bit(keys, KEY_VOLUMEUP) &&
        ioctl(fd, EVIOCGKEY(sizeof(held)), held) >= 0)
        result = bit(held, KEY_VOLUMEDOWN) ? 0 : 1;
    close(fd);
    return result;
}
