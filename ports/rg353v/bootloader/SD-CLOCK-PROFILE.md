# RG353V U-Boot SD clock investigation

The live kernel-read snapshots point to a clock-accounting error in the RK3568/RK3566 U-Boot path. The full U-Boot loader requests SD High Speed at 50 MHz, but supplies a 50 MHz controller input. The Rockchip controller's fixed divide-by-two stage gives a derived card clock of 25 MHz. The captured CLKDIV register is zero (divider bypass), the bus is four bits wide, and transfers use 32-bit IDMAC DMA. FIFO/PIO is disabled. The before/after snapshots agree.

| Quantity | Value |
| --- | ---: |
| MMC mode label / requested card clock | SD High Speed (50 MHz) / 50,000,000 Hz |
| Clock provider readback | 50,000,000 Hz |
| Rockchip fixed clock-generator divider | 2 |
| DWMMC CLKDIV / CTYPE | 0 / 1 (four bits) |
| Derived card clock | 25,000,000 Hz |
| Theoretical four-bit SDR payload ceiling | 12.5 MB/s |
| Kernel file size | 29,755,400 bytes |
| Kernel file read, complete final diagnostic boot | 2.481172 s |
| Observed effective file-load rate | 11.992 MB/s (about 96% of the ceiling) |

The card clock is derived from captured register/provider state and the SoC driver model, not measured with an oscilloscope. The `signal_voltage` enum is zero because this U-Boot build disables MMC_IO_VOLTAGE; it does not measure the physical pin voltage. MMC_UHS_SUPPORT is consequently unavailable even though the board device tree advertises SDR104. Linux later negotiates SDR104 separately.

## Source evidence

Pinned U-Boot v2026.01:

- `drivers/mmc/rockchip_dw_mmc.c:rockchip_dwmmc_get_mmc_clk()` calls `clk_set_rate()` with the requested frequency and returns that frequency. Its special doubling applies only to eight-bit eMMC DDR52, not this four-bit SD path.
- `drivers/clk/rockchip/clk_rk3568.c:rk3568_sdmmc_set_clk()` selects the literal 50 MHz input for a 50 MHz request, and `rk3568_sdmmc_get_clk()` reports that input without the controller's fixed /2 normalization. Older RK3399 clock code explicitly accounts for that divider.
- `drivers/mmc/dw_mmc.c:dwmci_setup_bus()` uses divider bypass when the returned source rate equals the requested rate. The captured CLKDIV=0 agrees.

The exact cached Linux 7.0.2 driver, `drivers/mmc/host/dw_mmc-rockchip.c`, defines `RK3288_CLKGEN_DIV=2`. Its documented relationship is `bus_hz = cclkin / RK3288_CLKGEN_DIV`, then `card_clock = div ? bus_hz / (2*div) : bus_hz`. It requests twice the desired card rate and divides the readback by two. RK3566 uses the RK3568 clock provider and this DWMMC-compatible controller. Linux's clock definition exposes CLK_SDMMC0 as the source, without normalizing away that divider.

## Same-card Linux control

A read-only O_DIRECT test read 29,360,128 aligned bytes from `/flash/KERNEL` in 0.473267 s: 62.037 MB/s. This excludes the final unaligned file tail. No global cache flush, writes or hashes were used. Linux debugfs reported a 150 MHz actual clock, four-bit bus, SDR104 and 1.8 V signalling. This is a different software/mode control, not a U-Boot benchmark or a predicted result for an untested clock correction.

## Diagnostic deployment and validation

Only the designated spare SD card received the diagnostic loader. Its configuration, DDR/BL31 inputs, device trees, zero countdown and clock-selection logic match the preceding BOOTSTAGE build. New code reads selected mode, software state, clock-provider registers and DWMMC registers around `/KERNEL` loading. It does not set clocks or select transfer modes. The final loader is 9,991,168 bytes, 512 bytes larger than the original timing loader, within the existing pre-partition raw region. Prior loaders remain backed up on the handheld and development host.

The first SD metadata build exposed a BOOTSTAGE export-capacity defect: `image_setup_libfdt()` shrinks away relocation padding before the later export, so adding long metadata exhausted the remaining page padding. Slot still reached its shelf, but report export was incomplete and its reader correctly rejected the missing timing field. The diagnostic recipe now retains 16 KiB at the shrink step, inside the larger relocated FDT allocation, before LMB re-reservation. The final boot exports all 39 records, both SD snapshots, and has 15,924 unused FDT tail bytes. Its report service succeeds and no units fail. Linux reaches its first splash at 1.843819 s and shelf at 14.715325 s. These are diagnostic warm values, not new cold speed results.

Ten parser regressions and twelve workflow tests pass. Two reviews checked type/driver guards and read-only snapshot code, then divider interpretation against the Linux controller/clock sources, export capacity and complete on-device reports. No production promotion or electrical clock change is part of this investigation. The previously reported intermittent cyan/striped splash remains a separate unresolved qualification issue.

## Guarded clock correction on the spare

The opt-in `SLOT_BOOTSTAGE_SD_CLOCK_FIX=1` candidate corrects only the existing four-bit SD High Speed 50 MHz request on the detected RG353V first SD slot. It programs 100 MHz controller input and returns the effective 50 MHz rate to generic DWMMC, retaining CLKDIV=0. Initialization-frequency quantization is avoided by leaving all initialization/low-rate requests on the original path. SPL, device trees, DDR/BL31, UHS/voltage configuration, boot command and OS remain unchanged. If the clock provider rejects or cannot produce the requested input, execution falls through to the original clock callback.

Two earlier guards did not engage and their restart tests stopped: the control device tree is generic `anbernic,rg353p`, while the detected board environment is `rk3566-anbernic-rg353v`. The second trial used a shortened board name. Capturing both identities resolved the mismatch. Neither no-op trial is included in the speed results.

The corrected candidate (`756e77cd9f89`, 9,991,680 bytes) passed three warm restarts, each retaining 39 records, two matching SD snapshots, a visible-shelf marker and zero failed units. Each snapshot reports 100 MHz input, derived 50 MHz card clock, four-bit SD High Speed, CLKDIV=0 and IDMAC DMA.

| Kernel file load | Duration |
| --- | ---: |
| Previous read-only probe | 2.481172 s |
| Corrected warm restart 1 | 1.248898 s |
| Corrected warm restart 2 | 1.248706 s |
| Corrected warm restart 3 | 1.249014 s |
| Corrected median | 1.248898 s |

The measured warm kernel-read reduction is 1.232274 seconds / 49.665%, with effective throughput 23.825 MB/s against the derived 25 MB/s payload ceiling. The loader remains on the spare only, with the previous loader backed up on the device and development host; no full-card scan or loader readback pass was used.

The final Linux log contains an initial SD tuning error followed by successful SDR104 attachment, and a Wi-Fi SDIO timeout followed by recovery. Both patterns also occur in the retained pre-correction log. They are recorded rather than called error-free. The host harness compiles the actual quirk header and exercises guards, initialization requests and rejected/unexpected provider rates; it passes alongside ten parser and twelve workflow regressions. Two reviews cover the actual compiled diff, fallback/SPL scope and device identity, then the timing/register captures, backup/write bounds and historical log comparison. See [clock-correction validation](../sd-clock-fix-validation.json). The intermittent cyan/striped splash remains an unresolved production-qualification condition.

## Cold validation and timing origin

All three cold boots retained 39 records and both matching 100 MHz input / derived 50 MHz card-clock snapshots. Reports are ordered by their device file timestamps, with the final report matching the live boot ID; the collector's initial batch order was filename order. All three splashes were visually checked and appeared normal.

| Cold run | Rumble → splash, manual timer | Kernel read, BOOTSTAGE | Linux entry → splash |
| --- | ---: | ---: | ---: |
| 1 | 4.18 s | 1.248703 s | 1.850683 s |
| 2 | 4.28 s | 1.249019 s | 1.835170 s |
| 3 | 4.18 s | 1.248703 s | 1.833145 s |

The cold kernel-read median is 1.248703 s, down 1.232572 s from the prior complete cold trace's 2.481275 s. The final validation found no failed services and confirmed SSH connectivity. Three normal cold displays do not explain or permanently clear the historical intermittent stripe fault.

The 4.xx stopwatch readings start at the orange LED/rumble. The initial button press lights the LED red about one second earlier. Therefore the rumble-to-splash median is 4.18 s and estimated button-to-splash median is approximately 5.18 s; the extra second is an estimate, not a measured ROM/DDR/power-sequencing split. Earlier 5.58/5.55/5.43 readings were requested and labeled Power-to-splash, so directly subtracting those from the new rumble-based readings would mix timing origins. The 1.233 s kernel-read improvement is independently measured with the same operation markers.

Within the cold full-U-Boot epoch, early initialization to relocation is about 750.5 ms; orange/rumble start to the final handoff marker is about 1,707.5 ms. That latter interval includes the 200.1 ms rumble, 229.6 ms bootflow scan, 1,248.7 ms kernel read and 10.1 ms DTB read. Linux entry to splash is separately about 1,835.2 ms. These values locate work, but the handoff marker precedes export/cleanup and the clock origins differ: they are not a complete additive button-to-splash timeline.
