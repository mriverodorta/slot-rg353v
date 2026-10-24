# RG353V spare-card bootloader profiling

This is a diagnostic build of the pinned U-Boot v2026.01, not a production bootloader update. Build with `bash scripts/build-rg353v-bootstage.sh`. The host wrapper uses a separate Docker volume and mounts the qualified firmware cache read-only. It does not access an SD-card device. The normal fastboot recipe remains unchanged.

The profiling build retains the installed spare's `CONFIG_BOOTDELAY=0`, `bootflow scan -lb`, board/panel code, device trees, DDR blob and BL31. It enables BOOTSTAGE, SPL_BOOTSTAGE, BOOTSTAGE_FDT and BOOTSTAGE_STASH, increases timing record/FDT capacity, and inserts named timing calls at exact sites in the pinned source. It does not print a timing report during boot. `instrumented-files.txt` and `config-delta.json` accompany the artifact. The initial timing loader grows by 4,096 bytes to 9,990,656 bytes; later variants record their own sizes in their manifests. All remain wholly before partition one.

SPL passes its records to full U-Boot using a 16 KiB buffer at `0x01800000`, above the loader/FIT/script buffers and below the configured kernel load address `0x02000000`. The regular kernel, DTB, overlay and ramdisk load addresses do not overlap this buffer. Full U-Boot exports records in the OS device tree before its final cleanup/handoff. Linux exposes them under `/sys/firmware/devicetree/base/bootstage`.

Run `python3 read-bootstage.py` on the handheld to read the current boot. The experimental report path/service saves reports after `/run/slot-boot/frontend.displayed` appears to `/storage/slotcontent/Diagnostics/Bootloader/`, retaining ten. This is an after-startup measurement export, not a boot dependency. Files are also available through the Slot share under `Diagnostics/Bootloader`. No credentials are included in these reports.

The spare installation retains both a previous-loader backup and the profiling loader under `/storage/.cache/slot-bootloader-bootstage/`, plus a private Mac backup. Its bounded helper checks the exact spare SD identity, capacity, GPT and partition layout, completed provisioning and empty cartridge state before any write. Its `rollback` action restores the previous zero-delay loader. The original working card and eMMC are excluded. No full-card scan or loader read-back pass was performed.

## Clock interpretation

The initial three warm reports contain 37 records each and all preserve SPL records. Each shows a backwards timestamp between SPL `end phase` (about 308 ms) and full U-Boot `board_init_f` (about 7 ms). The cause is not established. The parser therefore separates them into two epochs and rejects operation spans crossing a discontinuity. It does not add them into a Power-button-to-kernel total.

The upstream `reset=0` record is synthetic. Boot ROM, proprietary DDR training, button/power sequencing and the transition between epochs remain unmeasured internally. The instrumented SPL `dram_init` call is later RAM setup, not proprietary DDR training. Accumulator records overlap other operations and must not be added as independent timeline stages. Linux CLOCK_MONOTONIC also has its own origin. U-Boot's final `start_kernel` mark precedes report export and cleanup, so it is not an exact Linux-entry timestamp.

## Initial warm restart results

Three controlled restarts reached the shelf, restored SSH and had zero failed systemd units. These are profiling restarts, not cold Power-to-splash measurements.

| Operation | Median measured duration |
| --- | ---: |
| Kernel file read | 2,480.975 ms |
| Bootflow scan start to selected bootflow | 311.432 ms |
| Rumble call | 200.060 ms |
| SPL image-loading call | 179.600 ms |
| Panel identification | 34.512 ms |
| Device-tree file read | 16.598 ms |
| Linux entry to first splash write | 1,838.884 ms |

The two file reads include the U-Boot file-loading path, not just raw media transfer. The scan includes discovery/configuration work. These rows are operation spans, not a complete additive timeline across firmware stages. The 29,755,400-byte kernel read corresponds to approximately 12.0 MB/s. These initial runs precede the separate SD clock investigation and correction below.

## Cold physical checks and recorder correction

The user timed three cold boots at 5.58, 5.55 and 5.43 seconds Power-to-splash (median 5.55 seconds), with normal graphics in all three. Their matched Linux first-splash writes are 1.832121, 1.827792 and 1.835896 seconds. The original 45-second report-export timer did not fire during the first two boots; those Linux reports survive, but their U-Boot timing exports do not. Only the third cold boot has a complete retained BOOTSTAGE report, and its kernel file read is 2.481275 seconds. Do not present the warm measurements as three retained cold U-Boot traces.

The timer has been replaced with a path-triggered export after Slot's first presented frame. The oneshot service uses `RemainAfterExit=yes` so the persistent marker cannot trigger repeated exports. This keeps export work after the first shelf frame and captures shorter test boots. The profiling build's physical median is 0.24 seconds above the earlier zero-delay sample; these small sequential manual samples do not establish profiling overhead or a new speed improvement. The previous intermittent cyan/striped splash is not explained by these normal checks and still prevents production qualification.

The corrected path exporter passed a controlled warm restart (`3763c4dc`): first scene at 14.169430 s and exporter start at 14.203408 s, about 34 ms later. The report saved successfully, the service remained active/exited to prevent retriggering, and no systemd units failed. This extra restart is excluded from the three user-timed cold samples.


The optional SD-state variant builds with `SLOT_BOOTSTAGE_SD_PROBE=1 bash scripts/build-rg353v-bootstage.sh .build-rg353v/bootloader/sd-probe`. It captures read-only MMC/provider/DWMMC state around the kernel read. The recipe now retains 16 KiB of FDT tail space through the final shrink/re-reservation step so the later BOOTSTAGE export is complete. See [SD clock investigation](SD-CLOCK-PROFILE.md).

The separate clock-correction candidate requires both `SLOT_BOOTSTAGE_SD_PROBE=1` and `SLOT_BOOTSTAGE_SD_CLOCK_FIX=1`. Its isolated quirk applies only to detected board `rk3566-anbernic-rg353v`, controller `0xfe2b0000` with `rockchip,rk3568-dw-mshc`, four-bit SD High Speed and a 50 MHz request. It requests 100 MHz upstream of the fixed /2 and returns 50 MHz to generic DWMMC. SPL and initialization rates keep the original callback. A rejected/unexpected provider rate falls through to the original clock-setting path. The control device tree identifies as RG353P; the board's hardware detection exports the full RG353V identifier, which is also captured in the SD metadata. This candidate changes clock programming and must not be described as timing-only. Build it into a separate output directory; it is experimental on the spare only. See [clock-correction validation](../sd-clock-fix-validation.json).
