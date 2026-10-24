# Startup, sleep and recovery

![Boot splash to cartridge shelf](media/boot-to-shelf.gif)

**Boot timing replay** at 640×480, using an earlier captured run's percentage changes and swap timestamps. [Timing data](media/boot-timing.json). The software first-scene marker was **4.664 seconds from Linux entry**; the first splash was at 1.152 seconds. This profiling run includes capture overhead and does not represent the latest eMMC or SD measurements below. Images use the actual renderer and guide shelf; this is not camera footage.

## What a boot time means

The Power press, orange LED/rumble, Linux entry, first visible splash and first shelf frame are different timing points. Keep the start point consistent when comparing builds. A 4.6-second controlled restart measurement does not establish 4.6 seconds from a cold Power press; it can exclude bootloader/power sequencing. The replay above follows its captured timestamps, including the initial black interval. Its final 800 ms shelf hold is for viewing and is outside the boot time. It is not stretched to a target duration.

## Latest controlled restarts

**About 4.2–4.3 seconds applies to booting the system from internal eMMC. Booting the same system from a microSD in TF1 averaged about 5.2 seconds on the tested card.** SD startup varies with card speed and quality; 5.2 seconds is a measured example, not a fixed time for every card.

The 23 October 2026 comparison kept the same verified kernel, compressed OS, frontend, both emulators and settings. All 23 modules were installed, with the same removable game library on TF2, **Save location: Game**, Developer Mode On and USB networking Off. TF1 was absent for the eMMC baseline. For the SD runs, the system was on TF1 and the eMMC boot entry was temporarily disabled to allow automatic SD restarts.

| System boot medium | Run 1 | Run 2 | Run 3 | Average |
| --- | ---: | ---: | ---: | ---: |
| Internal eMMC | 4.310 s | 4.292 s | 4.284 s | **4.295 s** |
| TF1 microSD | 5.286 s | 5.160 s | 5.125 s | **5.190 s** |

The SD configuration averaged **895 ms longer (+20.8%)**. About 713 ms of that difference occurred during initramfs/systemd startup. These results compare the complete storage configurations, including TF1 presence, rather than isolating raw media transfer speed. A separate manually initiated eMMC boot recorded a Linux-to-shelf marker of 4.257 seconds; it is not included in the three-run average. [Exact timing data and conditions](media/boot-media-comparison-timing.json).

All times above run from **Linux entry to the first shelf frame**. They exclude shutdown, U-Boot, SD fallback, the physical Power/rumble interval and Wi-Fi reconnection. All six measured restarts passed boot/software/storage checks, with games and save/state hashes unchanged. Network availability can follow the shelf; card performance, library size and selected features can affect startup.

## Earlier eMMC controlled restarts

This historical set predates the optional Schedutil Governor module. The separate SD measurements below include that installed module with its setting Off.

This earlier eMMC development test used all 22 modules, a removable game library on TF1, **Save location: Game**, Developer Mode On and USB networking Off:

| Test | Run 1 | Run 2 | Run 3 | Average |
| --- | ---: | ---: | ---: | ---: |
| Before overlapping the SD scan | 4.97 s | 4.91 s | 4.89 s | 4.923 s |
| SD scan alongside graphics | 4.48 s | 4.47 s | 4.51 s | 4.487 s |

This saved approximately **437 ms** to the populated first shelf. The SD directory scan is still performed fresh on every boot. Slot starts it while graphics initializes and waits for its result before resolving the remembered cartridge and drawing the shelf. It does not show an empty shelf first or rely on a persistent library index. A slow card can still extend startup.

These are **Linux-entry-to-first-shelf controlled warm restarts**, not Power-button, rumble-to-shelf or cold-boot measurements. The instrumented presentation replay above is a separate run, not a recording of these three tests. Network availability can follow the first shelf; library size, selected modules, boot medium and card speed affect startup.

## SD startup folder and scan refinement

A later development comparison used the same TF1 system card, TF2 game library, remembered shelf/cartridge, all 23 modules, Save location Game, Developer Mode On and USB networking Off. The kernel, OS image, cores and governor setting were unchanged. Only the frontend and its source-change record were updated.

| Controlled warm restarts | Run 1 | Run 2 | Run 3 | Average |
| --- | ---: | ---: | ---: | ---: |
| Before folder/scan refinement | 6.148 s | 5.927 s | 5.832 s | 5.969 s |
| Deferred folders and lazy label/settings reads | 5.635 s | 5.408 s | 5.556 s | 5.533 s |

The observed average reduction was **436 ms (7.3%)**. Frontend startup itself fell from **1.678 to 1.328 seconds**, a repeatable reduction of about **351 ms**; the remaining difference lies in normal variation before frontend entry. Folder preparation fell from 347 to 138 ms, and the scan interval from 423 to 279 ms.

Normal RG353V startup prepares configuration and migrates legacy settings before reading them. Completing the standard content-folder layout runs in a worker after the first displayed scene. Battery saves and state writers create their own required directories, so immediately opening or resuming a game does not depend on that worker finishing. Setup and explicit root initialization still create the complete folder layout.

Every console's game directory is scanned afresh. Label directories and cartridge-shell settings are read only after finding a valid ROM that needs them. Empty consoles avoid those extra reads; adding a game still makes it appear on the next scan without rebuilding a persistent index. These changes do not optimize or replace users' artwork.

These are **Linux-entry-to-first-scene software restarts on an SD system**, not a new eMMC benchmark or a physical Power/rumble measurement. Detailed capture ran only after the shelf and was kept in RAM until retrieval. The six boots verified the native normal-boot guards, complete library discovery and absence of failed units. A fresh-image installation and physical cold-start confirmation of this refinement remain separate qualification steps.

## Internal-library scan overlap

The next frontend refinement also starts internal ROM/artwork discovery during graphics initialization. Separate workers scan the system library and removable libraries. The primary worker does not read cartridge settings: the main thread resolves those only after legacy migration. A boot-local directory snapshot is checked before reuse; changed directories, roots or mount lists and failed workers fall back to a fresh scan. No library index persists between boots, and the first shelf still waits for the complete merged library.

A fresh before/after set kept the same TF1/TF2 layout, game library, selected cartridge, modules and settings as above:

| Controlled warm restarts | Run 1 | Run 2 | Run 3 | Average |
| --- | ---: | ---: | ---: | ---: |
| Before internal scan overlap | 5.990 s | 5.487 s | 5.493 s | 5.657 s |
| Internal scan alongside graphics | 5.216 s | 5.234 s | 5.424 s | 5.292 s |

The observed average reduction was **365 ms (6.5%)**. Frontend startup fell from **1.334 to 1.038 seconds**, about **296 ms**. The main-thread scan interval fell from **279 ms to 0.4 ms**; the primary worker finished before root/settings preparation in all three updated runs. Graphics preparation increased by about 41 ms under concurrent I/O, already included in the net result. Some of the total saving is variation before frontend entry. [Timing data](media/boot-scan-overlap-timing.json).

These are software restarts from Linux entry to first scene, with heavy profiling only after the shelf. They do not establish a physical cold Power-to-shelf time or a new eMMC result. Both cores, the kernel and OS image were unchanged; the previous frontend remained available for rollback. Fresh-install and physical cold-start qualification of this exact refinement remain separate.

## Initial cartridge rendering alongside graphics

A further frontend refinement prepares the application on a startup worker while SDL/DRM initializes, then queues pixels for the visible cartridges. The existing library merge, settings migration, remembered shelf and cache content checks are retained. Device/audio attachment and all GPU texture uploads stay on their original threads; the first shelf still waits for every visible cartridge. Adjacent shelves remain deferred until after the first display swap. A failed preparation worker falls back to the ordinary synchronous startup.

The next controlled set used the same TF1 system, TF2 game library, selected GBC cartridge, modules and settings:

| Software restarts | Run 1 | Run 2 | Run 3 | Average |
| --- | ---: | ---: | ---: | ---: |
| Before early pixel queue | 5.177 s | 5.269 s | 5.168 s | 5.205 s |
| With early pixel queue | 5.102 s | 5.309 s | 5.177 s | 5.196 s |

Frontend initialization consistently fell from **1.027 to 0.900 seconds**, about **126 ms**. Remaining cartridge-pixel/upload waiting after frontend construction fell from **327 to 290 ms**; root/settings preparation also overlaps graphics now. These intervals overlap and must not be added as independent savings.

The total boot averages differ by only **9 ms**, so this set establishes **no meaningful overall boot-time reduction**. Earlier startup averaged 118 ms longer in the updated set: initramfs varied by about 76 ms and systemd-to-service by 46 ms, while launcher time stayed effectively unchanged. These three-run samples do not establish that the frontend change caused variation before its process started. [Timing data](media/boot-art-overlap-timing.json).

All six normal restarts passed the native guards and reached the populated shelf with Wi-Fi SSH; USB networking stayed Off. The previous frontend is retained for rollback, both cores and the OS/kernel remain unchanged, and save/state hashes were checked before and after. This component was tested on TF1; a fresh image and physical cold-start qualification remain separate from these Linux-entry measurements.

## Additional storage experiments

Two further candidates were tested with the same TF1 system card and TF2 game library. Each candidate had three controlled software restarts; both were compared with the same three-run baseline. The exFAT-probe trial used an OS delta retaining the active frontend/kernel; the parallel-scan trial used the restored baseline OS with only its frontend changed. Activation and restoration restarts are excluded below.

| Candidate | Run 1 | Run 2 | Run 3 | Average |
| --- | ---: | ---: | ---: | ---: |
| Qualified baseline | 5.330 s | 5.051 s | 5.035 s | 5.139 s |
| exFAT-only filesystem probe | 5.187 s | 5.180 s | 5.307 s | 5.225 s |
| Parallel console directory scans | 5.061 s | 5.495 s | 5.335 s | 5.297 s |

**Neither change was retained.** The filtered probe was faster in a warm read-only check but did not improve controlled-restart discovery/boot measurements. Parallel console scanning increased its average scan interval from 479 to 517 ms and frontend initialization from 902 to 938 ms. The previous OS, frontend and verified rollback frontend were restored. Additional native tests now cover rejection of ext4 and missing paths. [Timing data](media/boot-storage-timing.json).

These experiments targeted the earlier 4.5–4.6-second eMMC experience. TF1-system measurements also include loading Linux libraries and rendered-art caches from SD, so their difference could not all be assigned to inserted-card discovery. Historical graphics/artwork timings came from different builds and conditions. The subsequent [same-build storage comparison](#latest-controlled-restarts) now records a 4.295-second eMMC average and a 5.190-second TF1 average; it supersedes those historical timings as the current eMMC-versus-SD reference.

## Why the percentage jumps

The counter is **completed checkpoints**, not elapsed time, bytes loaded or a prediction of time remaining. The shared plan contains 29 equally counted checkpoints: 12 initramfs steps, seven service groups and ten frontend stages. It displays `floor(100 × completed / 29)`. For example, 9 completions give 31%, 12 give 41%, 15 give 51%, 18 give 62% and 24 give 82%.

The initramfs draws once at 0% and again around its splash-loading step at 31%; it does not redraw after every early checkpoint. The normal renderer then samples completion at roughly 15 Hz. After graphics takes over, Slot refreshes a saved splash image at selected frontend boundaries. Several milestones can finish between those updates, so a boot may skip 48%, 58%, 79% or the late 86–96% values. The exact sequence varies with scheduling and card/artwork work. This capture included a brief 48% and 86%; another boot can show 51% or 82% directly.

There is no retained 35-second countdown or artificial per-step wait. Some inherited initramfs checkpoints, such as conditional flash cleanup and boot-menu checks, remain in the accounting even when they do almost no work on this device. The audio checkpoint now means that the deferred audio sink is prepared, not that speaker setup has already finished. Network and update background services are not prerequisites for 100%. The counter therefore does not express how much startup work or time remains.

The frontend presents 100% once and immediately draws the first scene. In the captured run, the two swap-return timestamps were **34.7 ms apart**. The GIF represents this as 30 ms on its 10 ms timing grid; the MP4 retains the handoff at 60 fps. These are software presentation timings; optical panel latency was not measured. [Capture details and limitations](Media-Production.md).

## Normal startup

With our loader installed, eMMC starts normally without F. Hold F before pressing Power to select the TF1 recovery/setup SD, and keep F held until its splash/setup. An SD installation alongside eMMC can require F on each restart. This is our installed loader's behavior, not a universal factory-ROM shortcut.

First-run clock setup appears before ordinary use. Check the date/time and Miami/Eastern offset, confirm with A, then reach the shelf. After first run, an ejected game returns to the remembered shelf/cartridge. A game left inserted resumes directly on the next start when its resume state is readable. The [save-location policy](Adding-Games.md#save-location) also applies during startup; keep a Game-mode card inserted. Optional services start off unless Developer Mode is enabled.

## Shut down or restart from a game

Hold **Power for about one second** to open the Power menu. Choose **Power Off** and confirm with **A** for a full shutdown, or choose **Restart** for a software reboot. Slot saves resume progress without ejecting the game. On the next start, that cartridge should resume directly; holding A while opening a cartridge bypasses resume when you need the title screen instead.

![Power menu over a running game](images/features/power-menu-game.png)

Wait for shutdown to finish before removing a system or Game-mode library card. A short Power tap is sleep, not a full shutdown. Holding Power until the hardware forcibly switches off is a recovery action and can lose unwritten progress.

## Sleep

Tap Power to sleep and tap it again to wake. Shelf, controls and the chosen audio output should return. With Wi-Fi enabled, its icon updates once reconnection completes. Waking from Settings intentionally returns to the shelf. **System → Shutdown After Sleep** can power off after the selected sleep interval.

## Recover an update

An unfinished OTA session returns to its updater after reboot and waits for startup health and internet access. Once completed or cancelled, ordinary shelf/game startup returns. See [catch-up updates](OTA-Updates.md#catch-up-after-skipping-releases).

Keep a known-good recovery SD before changing system/kernel versions. OTA retains the prior confirmed component/OS set and uses trial health checks. An update package does not repartition the device or rewrite its first-stage loader. [OTA details](OTA-Updates.md).

If eMMC will not boot, use the TF1 recovery card with F. Verify the actual boot disk before attempting any repair. Back up progress and record the build, screen and LED state. An off LED is not always proof the device is fully off; collect logs through USB SSH if available before forcing a restart.

Rockchip USB loader recovery is a separate advanced procedure. It is not USB Storage or USB Networking, and generic raw-flash commands may destroy the wrong disk. Use a reviewed, device-specific recovery procedure.


## Public candidate cold-start qualification

The exact PUBLIC `rc-20261023-build4` Full installation was tested with its system on TF1 and the game library on TF2, Save location **Game**, Developer Mode On and USB networking Off. The tester shut down through Slot, waited 15 seconds after the LED went out and powered on holding F. Three distinct retained reports measured **4.880, 5.090 and 4.865 seconds**, averaging **4.945 seconds** from Linux entry to first shelf swap. These exclude physical Power/rumble and the earlier bootloader interval.

Every retained boot reached the shelf with the complete game library and no failed services; Wi-Fi/SSH recovered. The last local snapshot ran at 11 seconds, before Wi-Fi association, and a later check confirmed connectivity. Earlier missing timing reports were replaced with additional starts; no missing values were inferred. The delayed recorder ran after the shelf, saved locally rather than depending on Mac connectivity, and was removed after collection. These SD cold-start measurements complement the earlier eMMC/SD controlled-restart comparison; they are not a new eMMC timing result.
