#!/usr/bin/env python3
"""Exercise native same-disk resolution and actual exFAT probes without mounts."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'ports/rg353v/rocknix/slot-startup-profile/src/slot-content-probe.c'


class ContentProbe(unittest.TestCase):
    def test_resolution_mount_ambiguity_and_real_filesystem_labels(self):
        source = r'''
#define main production_main
#include "slot-content-probe.c"
#undef main
#include <assert.h>
static bool mounts(const char *text) {
    FILE *f=fmemopen((void *)text,strlen(text),"r");assert(f);
    char b[PATH_MAX],s[PATH_MAX];bool ok=mounted_sources(f,b,s);fclose(f);
    return ok;
}
int main(int argc,char **argv) {
    assert(argc==4);
    char c[PATH_MAX];
    assert(same_disk("/dev/mmcblk0p1","/dev/mmcblk0p2",c));
    assert(!strcmp(c,"/dev/mmcblk0p3"));
    assert(same_disk("/dev/mmcblk1p1","/dev/mmcblk1p2",c));
    assert(!strcmp(c,"/dev/mmcblk1p3"));
    assert(same_disk("/dev/mmcblk12p1","/dev/mmcblk12p2",c));
    assert(!same_disk("/dev/mmcblk0p1","/dev/mmcblk1p2",c));
    assert(!same_disk("/dev/mmcblk0p1","/dev/mmcblk0p22",c));
    assert(!same_disk("/dev/mmcblk0p11","/dev/mmcblk0p2",c));
    assert(!same_disk("/dev/mmcblkAp1","/dev/mmcblkAp2",c));
    assert(!same_disk("/dev/sda1","/dev/sda2",c));
    assert(!same_disk("/dev/mmcblk0/../p1","/dev/mmcblk0/../p2",c));
    assert(mounts("/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage ext4 rw 0 0\n"));
    assert(!mounts("/dev/mmcblk0p1 /flash vfat ro 0 0\n"));
    assert(!mounts("/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage exfat rw 0 0\n"));
    assert(!mounts("/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage ext4 rw 0 0\n/dev/mmcblk1p1 /flash vfat ro 0 0\n"));
    assert(!mounts("/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage ext4 rw 0 0\n/dev/mmcblk1p2 /storage ext4 rw 0 0\n"));
    assert(valid_filesystem(argv[1]));
    assert(!valid_filesystem(argv[2]));
    assert(!valid_filesystem(argv[3]));
    assert(!valid_filesystem("/does/not/exist"));
    return 0;
}
'''
        cc = shlex.split(os.environ.get('SLOT_TEST_CC', 'cc'))
        runner = shlex.split(os.environ.get('SLOT_TEST_RUNNER', ''))
        mkfs = shlex.split(os.environ.get('SLOT_TEST_MKFS_EXFAT', 'mkfs.exfat'))
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); test = root/'test.c'; test.write_text(source)
            binary = root/'test'
            subprocess.run([*cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I'+str(SOURCE.parent), str(test), '-lblkid', '-o', str(binary)], check=True)
            images = [root/n for n in ('slot.exfat', 'other.exfat', 'blank.img')]
            for image in images:
                with image.open('wb') as f:
                    f.truncate(32*1024**2)
            for label, image in zip(('SLOT', 'OTHER'), images):
                subprocess.run([*runner, *mkfs, '-L', label, str(image)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run([*runner, str(binary), *map(str, images)], check=True)


if __name__ == '__main__':
    unittest.main()
