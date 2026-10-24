#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef SLOT_MACHINE_ID_FILE
#define SLOT_MACHINE_ID_FILE "/etc/machine-id"
#endif
#ifndef SLOT_MACHINE_ID_BACKING
#define SLOT_MACHINE_ID_BACKING "/storage/.cache/systemd-machine-id"
#endif
#ifndef SLOT_MACHINE_ID_TOOL
#define SLOT_MACHINE_ID_TOOL "/usr/bin/systemd-machine-id-setup"
#endif

static bool ready(const char *identity, const char *backing)
{
    int a = open(identity, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    int b = open(backing, O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOFOLLOW);
    struct stat sa, sb;
    bool valid = false;
    if (a < 0 || b < 0 || fstat(a, &sa) || fstat(b, &sb))
        goto out;
    /* A temporary bind-mounted ID must still use systemd's normal setup. */
    if (!S_ISREG(sa.st_mode) || sa.st_dev != sb.st_dev || sa.st_ino != sb.st_ino || sa.st_size != 33)
        goto out;
    char text[33];
    size_t used = 0;
    while (used < sizeof(text)) {
        ssize_t n = read(a, text + used, sizeof(text) - used);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            goto out;
        used += (size_t)n;
    }
    if (text[32] != '\n')
        goto out;
    bool nonzero = false;
    for (size_t i = 0; i < 32; ++i) {
        if (!((text[i] >= '0' && text[i] <= '9') || (text[i] >= 'a' && text[i] <= 'f')))
            goto out;
        nonzero |= text[i] != '0';
    }
    valid = nonzero;
out:
    if (a >= 0) close(a);
    if (b >= 0) close(b);
    return valid;
}

int main(int argc, char **argv)
{
    if (argc == 4 && !strcmp(argv[1], "--check"))
        return ready(argv[2], argv[3]) ? 0 : 1;
    if (argc != 1)
        return 2;
    if (ready(SLOT_MACHINE_ID_FILE, SLOT_MACHINE_ID_BACKING))
        return 0;
    execl(SLOT_MACHINE_ID_TOOL, "systemd-machine-id-setup", (char *)NULL);
    perror("slot: machine-id setup");
    return 1;
}
