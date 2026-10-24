#!/usr/bin/env python3
"""Compile and exercise the actual clock quirk against controlled clock/device inputs."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ClockQuirkTests(unittest.TestCase):
    def test_target_guards_low_rates_and_provider_failure(self):
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef unsigned int uint;
enum { SD_HS=2, MMC_DDR_52=4 };
struct udevice { uint64_t addr; bool compatible; };
struct mmc { uint selected_mode; uint bus_width; };
struct dwmci_host { void *priv; struct mmc *mmc; };
struct clk { int unused; };
static const char *board_name = "rk3566-anbernic-rg353v";
static uint calls, last_rate;
static long provider_result = 100000000;
static uint64_t dev_read_addr(struct udevice *dev) { return dev->addr; }
static bool device_is_compatible(struct udevice *dev, const char *name) {
 assert(!strcmp(name,"rockchip,rk3568-dw-mshc")); return dev->compatible;
}
static const char *env_get(const char *name) {
 assert(!strcmp(name,"board")); return board_name;
}
static long clk_set_rate(struct clk *clk, uint rate) {
 (void)clk; calls++; last_rate=rate; return provider_result;
}
#include "rg353v-sd-hs-clock.h"
int main(void) {
 struct udevice dev={.addr=0xfe2b0000UL,.compatible=true};
 struct mmc mmc={.selected_mode=SD_HS,.bus_width=4};
 struct dwmci_host host={.priv=&dev,.mmc=&mmc}; struct clk clk={0};
 assert(slot_rg353v_sd_hs_clock(&host,&clk,50000000));
 assert(calls==1 && last_rate==100000000); calls=0;
 uint rates[]={100000,200000,375000,400000,25000000,24000000,52000000};
 for (uint i=0;i<sizeof(rates)/sizeof(rates[0]);i++)
  assert(!slot_rg353v_sd_hs_clock(&host,&clk,rates[i]));
 assert(calls==0);
 board_name="rk3566-anbernic-rg353p"; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000));
 board_name=0; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000)); board_name="rk3566-anbernic-rg353v";
 dev.addr=0xfe2c0000UL; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000)); dev.addr=0xfe2b0000UL;
 dev.compatible=false; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000)); dev.compatible=true;
 mmc.bus_width=8; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000)); mmc.bus_width=4;
 mmc.selected_mode=MMC_DDR_52; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000));
 mmc.selected_mode=0; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000));
 assert(calls==0); mmc.selected_mode=SD_HS;
 provider_result=-22; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000));
 provider_result=50000000; assert(!slot_rg353v_sd_hs_clock(&host,&clk,50000000));
 assert(calls==2);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'test.c').write_text(source)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT/'ports/rg353v/bootloader'),
                            str(tmp/'test.c'), '-o', str(tmp/'test')], check=True)
            subprocess.run([str(tmp/'test')], check=True)


if __name__ == '__main__':
    unittest.main()
