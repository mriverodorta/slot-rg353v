/* SPDX-License-Identifier: GPL-2.0+ */
static void slot_rg353v_boot_select(void)
{
	const char *board = env_get("board");
	const char *command, *target;
	char text[96];
	u32 raw = 1023;
	int ret = 0, i;
	bool pressed = true;

	if (!board || strcmp(board, "rk3566-anbernic-rg353v"))
		return;
	for (i = 0; i < 3; i++) {
		ret = adc_channel_single_shot("saradc@fe720000", 0, &raw);
		if (ret || raw > 32) {
			pressed = false;
			break;
		}
	}
	target = pressed ? "sd" : "emmc";
	command = pressed ? "bootflow scan -lb mmc1; bootflow scan -lb mmc0" :
			    "bootflow scan -lb mmc0; bootflow scan -lb mmc1";
	if (env_set("bootcmd", command))
		return;
	snprintf(text, sizeof(text), "slot-boot-choice;target=%s;f_raw=%u;adc_error=%d",
		 target, raw, ret);
	bootstage_mark_name(BOOTSTAGE_ID_ALLOC, strdup(text));
}
