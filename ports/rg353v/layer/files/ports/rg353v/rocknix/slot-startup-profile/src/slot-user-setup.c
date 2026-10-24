// SPDX-License-Identifier: GPL-2.0-or-later
// Cheap read-only gates. Upstream scripts remain the setup and repair authority.
#define _POSIX_C_SOURCE 200809L
#include <dirent.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *root = "";

static bool path(char out[PATH_MAX], const char *name) {
    int n = snprintf(out, PATH_MAX, "%s%s", root, name);
    return n > 0 && n < PATH_MAX;
}

static bool info(const char *name, struct stat *st) {
    char p[PATH_MAX];
    return path(p, name) && stat(p, st) == 0;
}

static bool exists(const char *name) {
    struct stat st;
    return info(name, &st);
}

static bool directory(const char *name) {
    struct stat st;
    return info(name, &st) && S_ISDIR(st.st_mode);
}

static char *read_file(const char *name) {
    char p[PATH_MAX];
    if (!path(p, name)) return NULL;
    FILE *f = fopen(p, "rb");
    if (!f) return NULL;
    char *data = malloc(65537);
    if (!data) { fclose(f); return NULL; }
    size_t n = fread(data, 1, 65536, f);
    bool ok = !ferror(f) && feof(f);
    fclose(f);
    if (!ok) { free(data); return NULL; }
    data[n] = 0;
    // These inputs are text. Embedded NUL or oversized data must use repair.
    if (strlen(data) != n) { free(data); return NULL; }
    return data;
}

static bool config_ready(void) {
    struct stat st;
    if (!exists("/storage/.configured") || !directory("/storage/.config/locale") ||
        !info("/storage/.cache/ld.so.cache", &st) || !S_ISREG(st.st_mode) ||
        st.st_size < 20 || !info("/etc/os-release", &st)) return false;
    char expected[64];
    snprintf(expected, sizeof(expected), "%lld", (long long)st.st_mtime);
    char *stamp = read_file("/storage/.cache/ld.so.cache.osstamp");
    if (!stamp) return false;
    size_t n = strlen(stamp);
    while (n && stamp[n - 1] == '\n') stamp[--n] = 0; // shell command substitution
    bool ok = strcmp(stamp, expected) == 0;
    free(stamp);
    return ok;
}

// Match the non-overwriting cache population without running cp or a shell.
static bool populated(const char *source, const char *dest, unsigned depth) {
    if (depth > 32) return false;
    char p[PATH_MAX];
    if (!path(p, source)) return false;
    DIR *dir = opendir(p);
    if (!dir) return false;
    bool ok = true;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char a[PATH_MAX], b[PATH_MAX], full[PATH_MAX];
        int na = snprintf(a, sizeof(a), "%s/%s", source, entry->d_name);
        int nb = snprintf(b, sizeof(b), "%s/%s", dest, entry->d_name);
        struct stat src, dst;
        if (na < 0 || na >= PATH_MAX || nb < 0 || nb >= PATH_MAX ||
            !path(full, a) || lstat(full, &src) || !path(full, b) || lstat(full, &dst)) {
            ok = false; break;
        }
        if (S_ISDIR(src.st_mode) &&
            (!S_ISDIR(dst.st_mode) || !populated(a, b, depth + 1))) {
            ok = false; break;
        }
    }
    closedir(dir);
    return ok;
}

static char *root_line(char *text, size_t *len) {
    char *found = NULL;
    for (char *s = text; *s;) {
        char *end = strchr(s, '\n');
        if (!end) return NULL; // upstream merge produces newline-terminated records
        if (!strncmp(s, "root:", 5)) {
            if (found) return NULL;
            found = s; *len = (size_t)(end - s + 1);
        }
        s = end + 1;
    }
    return found;
}

static bool shadow_ready(void) {
    struct stat st;
    if (!info("/storage/.cache/shadow", &st) || !S_ISREG(st.st_mode) ||
        (st.st_mode & 07777) != 0 || st.st_uid != 0) return false;
    char *factory = read_file("/usr/cache/shadow");
    char *saved = read_file("/storage/.cache/shadow");
    bool ok = false;
    if (factory && saved) {
        size_t fn = 0, sn = 0;
        char *f = root_line(factory, &fn), *s = root_line(saved, &sn);
        if (f && s && f - factory == s - saved &&
            !memcmp(factory, saved, (size_t)(f - factory)) && !strcmp(f + fn, s + sn))
            ok = true;
    }
    free(factory); free(saved);
    return ok;
}

static bool cache_ready(void) {
    struct stat st;
    if (info("/storage/.cache/services", &st) && S_ISREG(st.st_mode)) return false;
    return populated("/usr/cache", "/storage/.cache", 0) && shadow_ready();
}

int main(int argc, char **argv) {
    bool check = argc == 4 && !strcmp(argv[1], "--check");
    const char *mode = check ? argv[2] : argc == 2 ? argv[1] : "";
    if (check) root = argv[3];
    bool config = !strcmp(mode, "config");
    if (!config && strcmp(mode, "cache")) return 2;
    if (config ? config_ready() : cache_ready()) {
        if (!check) puts(config ? "Slot user config: unchanged" : "Slot user cache: unchanged");
        return 0;
    }
    if (check) return 1;
    const char *script = config ? "/usr/bin/userconfig-setup" : "/usr/bin/usercache-setup";
    puts(config ? "Slot user config: setup/repair" : "Slot user cache: setup/repair");
    fflush(stdout);
    execl(script, script, (char *)NULL);
    perror(script);
    return 1;
}
