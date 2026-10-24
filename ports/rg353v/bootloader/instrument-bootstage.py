#!/usr/bin/env python3
"""Instrument isolated, pinned U-Boot; optionally apply the guarded SD clock trial."""
from pathlib import Path
import sys


def instrument(root, sd_probe=False, sd_clock_fix=False, emmc_select=False):
    if sd_clock_fix and not sd_probe:
        raise ValueError('The SD clock experiment requires its live diagnostic probe')
    changed = {}

    def edit(name, pairs):
        path = root / name
        text = changed[name] if name in changed else path.read_text()
        for old, new in pairs:
            if text.count(old) != 1:
                raise ValueError(f'{name}: expected one matching instrumentation site')
            text = text.replace(old, new)
        changed[name] = text

    def mark(name, tabs=1):
        return '\t' * tabs + f'bootstage_mark_name(BOOTSTAGE_ID_ALLOC, "{name}");\n'

    edit('board/anbernic/rgxx3_rk3566/rgxx3-rk3566.c', [
        ('#include <adc.h>', '#include <adc.h>\n#include <bootstage.h>'),
        ('\tret = set_gd_value();', mark('slot-board-start') + '\tret = set_gd_value();'),
        ('\t\tret = rgxx3_detect_display();', mark('slot-panel-start', 2) + '\t\tret = rgxx3_detect_display();\n' + mark('slot-panel-end', 2)),
        ('\t\tret = rgxx3_detect_regulator();', mark('slot-regulator-start', 2) + '\t\tret = rgxx3_detect_regulator();\n' + mark('slot-regulator-end', 2)),
        ('\tstartup_buzz();', mark('slot-orange-led') + mark('slot-rumble-start') + '\tstartup_buzz();\n' + mark('slot-rumble-end') + mark('slot-board-end')),
    ])
    edit('arch/arm/mach-rockchip/spl.c', [
        ('#include <cpu_func.h>', '#include <cpu_func.h>\n#include <bootstage.h>'),
        ('\tarch_cpu_init();', mark('slot-spl-early-ready') + '\tarch_cpu_init();\n' + mark('slot-spl-cpu-ready')),
        ('\tret = dram_init();', mark('slot-spl-dram-start') + '\tret = dram_init();\n' + mark('slot-spl-dram-end')),
    ])
    edit('common/spl/spl.c', [
        ('\t\t\tret = spl_load_image(spl_image, loader);', mark('slot-spl-image-start', 3) + '\t\t\tret = spl_load_image(spl_image, loader);\n' + mark('slot-spl-image-end', 3)),
    ])
    edit('common/main.c', [
        ('\ts = bootdelay_process();', mark('slot-bootdelay-start') + '\ts = bootdelay_process();\n' + mark('slot-bootdelay-end')),
        ('\tautoboot_command(s);', mark('slot-autoboot-start') + '\tautoboot_command(s);'),
    ])
    edit('cmd/bootflow.c', [
        ('#include <bootstd.h>', '#include <bootstd.h>\n#include <bootstage.h>'),
        ('\tstd->cur_bootflow = NULL;\n\n\tflags =', mark('slot-bootflow-scan-start') + '\tstd->cur_bootflow = NULL;\n\n\tflags ='),
        ('\t\tif (!menu && boot && !bflow.err)\n\t\t\tbootflow_run_boot(&iter, &bflow);', '\t\tif (!menu && boot && !bflow.err) {\n' + mark('slot-bootflow-selected', 3) + '\t\t\tbootflow_run_boot(&iter, &bflow);\n\t\t}'),
    ])
    edit('boot/pxe_utils.c', [
        ('#include <bootflow.h>', '#include <bootflow.h>\n#include <bootstage.h>'),
        ('\tret = ctx->getfile(ctx, relfile, addr_buf, type, &size);', '\tbootstage_mark_name(BOOTSTAGE_ID_ALLOC, strdup(relfile));\n' + mark('slot-file-read-start') + '\tret = ctx->getfile(ctx, relfile, addr_buf, type, &size);\n' + mark('slot-file-read-end')),
    ])
    edit('boot/image-fdt.c', [
        ('ret = fdt_shrink_to_minimum(blob, 0);',
         'ret = fdt_shrink_to_minimum(blob, IS_ENABLED(CONFIG_BOOTSTAGE_FDT) ? 16384 : 0);'),
    ])
    if sd_probe:
        edit('include/dwmmc.h', [
            ('#define __DWMMC_HW_H', '#define __DWMMC_HW_H\n\nstruct mmc;\nvoid slot_sd_probe(struct mmc *mmc, const char *phase);'),
        ])
        edit('drivers/mmc/rockchip_dw_mmc.c', [
            ('#include <clk.h>', '#include <clk.h>\n#include <bootstage.h>\n#include <env.h>\n#include <malloc.h>'),
            ('static uint rockchip_dwmmc_get_mmc_clk', '''void slot_sd_probe(struct mmc *mmc, const char *phase)
{
	struct rockchip_dwmmc_priv *priv;
	struct dwmci_host *host;
	char text[512];
	ulong rate;
	const char *board = env_get("board");
	const char *machine = ofnode_read_string(ofnode_root(), "compatible");

	if (!mmc || !mmc->dev ||
	    strcmp(mmc->dev->driver->name, "rockchip_rk3288_dw_mshc"))
		return;
	priv = dev_get_priv(mmc->dev);
	host = &priv->host;
	rate = clk_get_rate(&priv->clk);
	snprintf(text, sizeof(text),
		 "slot-sd-probe;phase=%s;controller=%s;board=%s;machine=%s;mode=%s;bus_width=%u;"
		 "requested_hz=%u;provider_hz=%lu;fixed_divider=2;divider=%u;ctype=%u;"
		 "signal_voltage_enum=%u;fifo_mode=%u;dma64=%u;ddr=%u;"
		 "config_max_hz=%u;max_blocks=%u;card_caps=%u;host_caps=%u",
		 phase, mmc->dev->name, board ? board : "unknown",
		 machine ? machine : "unknown", mmc_mode_name(mmc->selected_mode),
		 mmc->bus_width, mmc->clock, rate,
		 dwmci_readl(host, DWMCI_CLKDIV) & 0xff,
		 dwmci_readl(host, DWMCI_CTYPE), mmc->signal_voltage,
		 host->fifo_mode, host->dma_64bit_address, mmc->ddr_mode, mmc->cfg->f_max,
		 mmc->cfg->b_max, mmc->card_caps, mmc->host_caps);
	bootstage_mark_name(BOOTSTAGE_ID_ALLOC, strdup(text));
}

static uint rockchip_dwmmc_get_mmc_clk'''),
        ])
        edit('boot/bootmeth_extlinux.c', [
            ('#include <extlinux.h>', '#include <extlinux.h>\n#include <dwmmc.h>\n#include <dm/device-internal.h>'),
            ('\tret = bootmeth_read_file(info->dev, info->bflow, file_path, addr,\n\t\t\t\t type, sizep);', '''	if (!strcmp(file_path, "/KERNEL") && info->bflow->blk &&
	    device_get_uclass_id(dev_get_parent(info->bflow->blk)) == UCLASS_MMC)
		slot_sd_probe(mmc_get_mmc_dev(dev_get_parent(info->bflow->blk)), "before");
	ret = bootmeth_read_file(info->dev, info->bflow, file_path, addr,
				 type, sizep);
	if (!strcmp(file_path, "/KERNEL") && info->bflow->blk &&
	    device_get_uclass_id(dev_get_parent(info->bflow->blk)) == UCLASS_MMC)
		slot_sd_probe(mmc_get_mmc_dev(dev_get_parent(info->bflow->blk)), "after");'''),
        ])
    if sd_clock_fix:
        changed['drivers/mmc/slot-rg353v-sd-hs-clock.h'] = Path(__file__).with_name('rg353v-sd-hs-clock.h').read_text()
        edit('drivers/mmc/rockchip_dw_mmc.c', [
            ('#include <linux/err.h>', '#include <linux/err.h>\n#ifndef CONFIG_XPL_BUILD\n#include "slot-rg353v-sd-hs-clock.h"\n#endif'),
            ('\tret = clk_set_rate(&priv->clk, freq);', '''#ifndef CONFIG_XPL_BUILD
	if (slot_rg353v_sd_hs_clock(host, &priv->clk, freq))
		return freq;
#endif
	ret = clk_set_rate(&priv->clk, freq);'''),
        ])
    if emmc_select:
        changed['board/anbernic/rgxx3_rk3566/slot-rg353v-boot-select.h'] = Path(__file__).with_name('rg353v-boot-select.h').read_text()
        edit('board/anbernic/rgxx3_rk3566/rgxx3-rk3566.c', [
            ('DECLARE_GLOBAL_DATA_PTR;', 'DECLARE_GLOBAL_DATA_PTR;\n#ifndef CONFIG_XPL_BUILD\n#include "slot-rg353v-boot-select.h"\n#endif'),
            ('\tenv_set("fdtfile", rg3xx_model_details[gd->board_type].fdtfile);',
             '\tenv_set("fdtfile", rg3xx_model_details[gd->board_type].fdtfile);\n#ifndef CONFIG_XPL_BUILD\n\tslot_rg353v_boot_select();\n#endif'),
        ])
        edit('arch/arm/dts/rk3566-anbernic-rg353p-u-boot.dtsi', [
            ('u-boot,spl-boot-order = &sdmmc0, &sdhci;',
             'u-boot,spl-boot-order = "same-as-spl", &sdmmc0, &sdhci;'),
        ])
    for name, text in changed.items():
        (root / name).write_text(text)
    return list(changed)


if __name__ == '__main__':
    for name in instrument(Path(sys.argv[1]), sd_probe='--sd-probe' in sys.argv[2:],
                           sd_clock_fix='--sd-clock-fix' in sys.argv[2:],
                           emmc_select='--emmc-select' in sys.argv[2:]):
        print(name)
