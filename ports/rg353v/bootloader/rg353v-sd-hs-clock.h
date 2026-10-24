/* SPDX-License-Identifier: GPL-2.0+ */
static bool slot_rg353v_sd_hs_clock(struct dwmci_host *host, struct clk *clk,
				  uint freq)
{
	struct udevice *dev = host->priv;
	const char *board = env_get("board");

	if (freq != 50000000 || host->mmc->selected_mode != SD_HS ||
	    host->mmc->bus_width != 4 ||
	    dev_read_addr(dev) != 0xfe2b0000UL ||
	    !device_is_compatible(dev, "rockchip,rk3568-dw-mshc") ||
	    !board || strcmp(board, "rk3566-anbernic-rg353v"))
		return false;

	/* This controller divides its input by two before CLKDIV. */
	return clk_set_rate(clk, 100000000) == 100000000;
}
