// SPDX-License-Identifier: GPL-3.0-or-later
// Resolve this appliance's content partition without scanning other disks.
// Read-only: mounting and USB ownership remain in slot-mount-content.
#define _GNU_SOURCE
#include <blkid/blkid.h>
#include <limits.h>
#include <mntent.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static bool same_disk(const char *boot, const char *storage, char *content) {
    const char *prefix = "/dev/mmcblk";
    size_t n = strlen(prefix);
    if (strncmp(boot, prefix, n)) return false;
    const char *p = boot + n;
    if (*p < '0' || *p > '9') return false;
    while (*p >= '0' && *p <= '9') p++;
    if (strcmp(p, "p1")) return false;
    size_t disk_len = (size_t)(p - boot);
    if (disk_len + 3 > PATH_MAX || strlen(storage) != disk_len + 2 ||
        strncmp(boot, storage, disk_len) || strcmp(storage + disk_len, "p2")) return false;
    memcpy(content, boot, disk_len);
    memcpy(content + disk_len, "p3", 3);
    return true;
}

static bool mounted_sources(FILE *f, char *boot, char *storage) {
    struct mntent entry, *p;
    char buffer[16384];
    unsigned boots = 0, stores = 0;
    while ((p = getmntent_r(f, &entry, buffer, sizeof buffer))) {
        if (!strcmp(p->mnt_dir, "/flash")) {
            if (++boots != 1 || strcmp(p->mnt_type, "vfat") ||
                strlen(p->mnt_fsname) >= PATH_MAX) return false;
            strcpy(boot, p->mnt_fsname);
        } else if (!strcmp(p->mnt_dir, "/storage")) {
            if (++stores != 1 || strcmp(p->mnt_type, "ext4") ||
                strlen(p->mnt_fsname) >= PATH_MAX) return false;
            strcpy(storage, p->mnt_fsname);
        }
    }
    return !ferror(f) && boots == 1 && stores == 1;
}

static bool tag_equals(blkid_probe probe, const char *tag, const char *wanted) {
    const char *value = NULL;
    size_t size = 0;
    return !blkid_probe_lookup_value(probe, tag, &value, &size) &&
        size == strlen(wanted) + 1 && !memcmp(value, wanted, size);
}

static bool valid_filesystem(const char *path) {
    blkid_probe probe = blkid_new_probe_from_filename(path);
    if (!probe) return false;
    bool ok = !blkid_probe_enable_partitions(probe, 0) &&
        !blkid_probe_enable_superblocks(probe, 1) &&
        !blkid_probe_set_superblocks_flags(probe, BLKID_SUBLKS_TYPE | BLKID_SUBLKS_LABEL) &&
        !blkid_do_safeprobe(probe) && tag_equals(probe, "TYPE", "exfat") &&
        tag_equals(probe, "LABEL", "SLOT");
    blkid_free_probe(probe);
    return ok;
}

int main(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 1;
    FILE *f = setmntent("/proc/self/mounts", "r");
    char boot[PATH_MAX], storage[PATH_MAX], real_boot[PATH_MAX], real_storage[PATH_MAX];
    char content[PATH_MAX];
    if (!f) return 1;
    bool ok = mounted_sources(f, boot, storage);
    endmntent(f);
    if (!ok || !realpath(boot, real_boot) || !realpath(storage, real_storage) ||
        !same_disk(real_boot, real_storage, content)) return 1;
    struct stat b, s, c;
    if (stat(real_boot, &b) || stat(real_storage, &s) || stat(content, &c) ||
        !S_ISBLK(b.st_mode) || !S_ISBLK(s.st_mode) || !S_ISBLK(c.st_mode) ||
        b.st_rdev == s.st_rdev || c.st_rdev == b.st_rdev || c.st_rdev == s.st_rdev ||
        !valid_filesystem(content)) return 1;
    return puts(content) < 0 ? 1 : 0;
}
