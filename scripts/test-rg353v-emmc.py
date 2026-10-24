#!/usr/bin/env python3
"""Exercise boot selection and storage isolation without opening hardware."""
from pathlib import Path
import importlib.util
import subprocess
import struct
import tempfile
import unittest
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]


class EmmcTests(unittest.TestCase):
    def test_graphical_boot_keeps_uart_and_storage_but_removes_lcd_console(self):
        spec = importlib.util.spec_from_file_location('console_installer', ROOT/'ports/rg353v/image/slot-emmc-install.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        args = ['boot=UUID=ABCD-1234', 'disk=UUID=system', 'quiet',
                'console=ttyS2,1500000', 'console=tty0', 'console=tty1,115200',
                'systemd.debug_shell=ttyS2']
        expected = [args[0], args[1], 'quiet', 'console=ttyS2,1500000', 'systemd.debug_shell=ttyS2']
        self.assertEqual(module.graphical_boot_arguments(args), expected)
        self.assertEqual(module.graphical_boot_arguments(expected), expected)
        self.assertEqual(module.graphical_boot_arguments(['quiet', 'console=tty0']),
                         ['quiet', 'console=ttyS2,1500000'])

    def test_gpt_headers_crc_backup_and_partition_identity(self):
        spec = importlib.util.spec_from_file_location('gpt_installer', ROOT/'ports/rg353v/image/slot-emmc-install.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        total = 31268536320; disk = str(uuid.uuid4())
        guids = {str(n): str(uuid.uuid4()) for n in (1, 2, 3)}
        regions = dict(module.gpt_regions(total, disk, guids)); last = total//512-1
        self.assertEqual(regions[0][510:], b'\x55\xaa')
        self.assertEqual(regions[0][450], 0xee)
        for current, backup, table in ((1, last, 2), (last, 1, last-32)):
            raw = bytearray(regions[current*512]); crc = struct.unpack_from('<I', raw, 16)[0]
            struct.pack_into('<I', raw, 16, 0)
            self.assertEqual(crc, zlib.crc32(raw[:92]))
            self.assertEqual(struct.unpack_from('<QQ', raw, 24), (current, backup))
            self.assertEqual(str(uuid.UUID(bytes_le=bytes(raw[56:72]))), disk)
            self.assertEqual(struct.unpack_from('<Q', raw, 72)[0], table)
            self.assertEqual(struct.unpack_from('<I', raw, 88)[0], zlib.crc32(regions[table*512]))
        entries = regions[1024]
        self.assertEqual(entries, regions[(last-32)*512])
        for n, (start, size) in module.geometry(total).items():
            row = entries[(n-1)*128:n*128]
            self.assertEqual(str(uuid.UUID(bytes_le=row[16:32])), guids[str(n)])
            self.assertEqual(struct.unpack_from('<QQQ', row, 32),
                             (start//512, (start+size)//512-1, 4 if n == 1 else 0))

    def test_internal_geometry_reserves_loader_and_backup_gpt(self):
        spec = importlib.util.spec_from_file_location('emmc_installer', ROOT/'ports/rg353v/image/slot-emmc-install.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        parts = module.geometry(31268536320)
        self.assertEqual(parts[1], (16*1024**2, 512*1024**2))
        self.assertEqual(parts[2], (528*1024**2, 512*1024**2))
        self.assertEqual(parts[3][0], sum(parts[2]))
        self.assertLessEqual(sum(parts[3]), 31268536320-33*512)
        self.assertEqual(parts[3][1], 28779*1024**2)
        legacy = module.geometry(31268536320, boot_mib=1024, storage_mib=5120)
        self.assertEqual(parts[3][1], legacy[3][1] + 5*1024**3)
        larger = module.geometry(31268536320, boot_mib=2048, storage_mib=5120)
        self.assertEqual(legacy[3][1], larger[3][1] + 1024**3)
        for boot in (0, 256, 4096, True, '2048'):
            with self.assertRaises(ValueError):
                module.geometry(31268536320, boot_mib=boot)
        for bad in (7*1024**3, 31268536321):
            with self.assertRaises(ValueError):
                module.geometry(bad)

    def test_old_plans_keep_old_geometry_and_new_plans_are_explicit(self):
        spec = importlib.util.spec_from_file_location('plan_installer', ROOT/'ports/rg353v/image/slot-emmc-install.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        plan = {'schema': 1, 'target': {'bytes': 31268536320}}
        self.assertEqual(module.plan_geometry(plan)[1][1], 1024**3)
        plan['schema'] = 2
        with self.assertRaises(ValueError):
            module.plan_geometry(plan)
        plan['layout'] = {'boot_mib': 2048, 'storage_mib': 5120}
        self.assertEqual(module.plan_geometry(plan), module.geometry(31268536320, boot_mib=2048, storage_mib=5120))
        plan['layout']['boot_mib'] = 1024
        self.assertEqual(module.plan_geometry(plan), module.geometry(31268536320, boot_mib=1024, storage_mib=5120))
        plan['schema'] = 1
        with self.assertRaises(ValueError):
            module.plan_geometry(plan)
        plan['schema'] = 2
        plan['layout'] = dict(module.DEFAULT_LAYOUT)
        self.assertEqual(module.plan_geometry(plan), module.geometry(31268536320))
        for layout in ({'boot_mib':512,'storage_mib':5120}, {'boot_mib':1024,'storage_mib':512}):
            plan['layout']=layout
            with self.assertRaises(ValueError):module.plan_geometry(plan)
        plan['schema'] = 2
        plan['layout']['storage_mib'] = 4096
        with self.assertRaises(ValueError):
            module.plan_geometry(plan)

    def test_content_follows_boot_disk_and_rejects_mixed_sources(self):
        helper = ROOT/'ports/rg353v/rocknix/slot-rg353v/scripts/slot-content-device'
        for number in (0, 1, 12):
            disk = '/dev/mmcblk' + str(number)
            p = subprocess.run(['sh', str(helper), disk+'p1', disk+'p2'], capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout), (0, disk+'p3\n'))
        for boot, storage in [('/dev/mmcblk0p1', '/dev/mmcblk1p2'),
                              ('/dev/mmcblk1p1', '/dev/mmcblk0p2'),
                              ('/dev/mmcblk0p2', '/dev/mmcblk0p2'),
                              ('/dev/loop0p1', '/dev/loop0p2'),
                              ('/dev/mmcblkBADp1', '/dev/mmcblkBADp2')]:
            p = subprocess.run(['sh', str(helper), boot, storage], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertEqual(p.stdout, '')

    def test_actual_boot_header_adc_failure_threshold_and_override(self):
        source = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
#define BOOTSTAGE_ID_ALLOC 0
static const char *board="rk3566-anbernic-rg353v";
static u32 samples[3];
static int count, fail_at, set_result, marks;
static char command[128], marker[128];
static const char *env_get(const char *key) { assert(!strcmp(key,"board")); return board; }
static int env_set(const char *key, const char *value) {
 assert(!strcmp(key,"bootcmd")); if (!set_result) strcpy(command,value); return set_result;
}
static int adc_channel_single_shot(const char *name, int channel, u32 *raw) {
 assert(!strcmp(name,"saradc@fe720000") && channel==0 && count<3);
 int i=count++; if (i==fail_at) return -5; *raw=samples[i]; return 0;
}
static void bootstage_mark_name(int id, char *name) {
 assert(id==0); strcpy(marker,name); free(name); marks++;
}
#include "rg353v-boot-select.h"
static void reset(u32 a,u32 b,u32 c) {
 samples[0]=a;samples[1]=b;samples[2]=c;count=marks=set_result=0;fail_at=-1;
 command[0]=marker[0]=0;
}
int main(void) {
 reset(1023,1023,1023);slot_rg353v_boot_select();
 assert(!strcmp(command,"bootflow scan -lb mmc0; bootflow scan -lb mmc1") && count==1);
 assert(strstr(marker,"target=emmc") && marks==1);
 reset(0,1,0);slot_rg353v_boot_select();
 assert(!strcmp(command,"bootflow scan -lb mmc1; bootflow scan -lb mmc0") && count==3);
 assert(strstr(marker,"target=sd"));
 reset(32,32,32);slot_rg353v_boot_select();assert(strstr(marker,"target=sd"));
 reset(0,33,0);slot_rg353v_boot_select();assert(strstr(marker,"target=emmc") && count==2);
 reset(0,0,0);fail_at=1;slot_rg353v_boot_select();
 assert(strstr(marker,"target=emmc") && strstr(marker,"adc_error=-5"));
 reset(0,0,0);set_result=-12;slot_rg353v_boot_select();assert(!marks && !command[0]);
 reset(0,0,0);board="rk3566-anbernic-rg353p";slot_rg353v_boot_select();assert(!count && !marks);
 board=0;slot_rg353v_boot_select();assert(!count && !marks);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'test.c').write_text(source)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I',
                            str(ROOT/'ports/rg353v/bootloader'), str(root/'test.c'),
                            '-o', str(root/'test')], check=True)
            subprocess.run([str(root/'test')], check=True)


if __name__ == '__main__':
    unittest.main()
