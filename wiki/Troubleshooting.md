# Maintenance and troubleshooting

## Diagnostics and profilers

![Diagnostics menu](images/features/diagnostics.png)

System → Diagnostics shows live readings, versions and service status when its module is installed. Collection happens while the page is open. An inactive optional service may simply be switched off; a completed oneshot unit can be active without a running process. Diagnostics does not export reports or create report files.

Development Profilers is a separate optional module for boot/process/battery investigations. Installing it does not enable recording or network access. Avoid leaving high-frequency recording enabled for normal battery-life comparisons. Boot measurements must state their start point: Linux entry, rumble and the physical Power press are different intervals.

## Audio

The device speaker and wired 3.5 mm headphones have separate volume settings. Plugging in headphones should route sound away from the speaker, including after sleep/wake. Test at a comfortable volume. If the routing fails, note the active core, whether the jack was inserted before launch, and whether suspend occurred.

Enhanced Audio must be installed before its Audio switch appears. It is **Off by default**, selecting it enables the optional 48 kHz resampling path on the next game launch. It can cost extra CPU/power; do not assume it improves all game audio.

## Sleep and power

Tap Power to sleep and tap again to wake. Settings intentionally return to the shelf after waking. Use Slot's power menu for normal shutdown, and wait until shutdown has completed before removing a card. The short shutdown screen should transition to black without a boot splash reappearing.

If waking fails, record the screen and LED state. An off LED alone does not establish that the machine fully powered off. If USB SSH is available, collect logs first. A long Power hold is recovery for an unresponsive system and can lose unwritten progress; do not use it as the routine shutdown method.

## Wi-Fi unavailable

Confirm the Wi-Fi module was installed and the radio is on. “Adapter unavailable” differs from a wrong password. If USB networking and SSH were installed, enable those to inspect the failed boot without immediately restarting. Record whether failure followed a cold boot, restart or sleep/wake. Some Mac-created hotspot configurations remain a compatibility investigation; do not treat every handshake failure as a typo.

## Storage

The optional storage tools can check/repair supported **SD game filesystems** with confirmation and power checks. They do not offer arbitrary repair of internal eMMC, boot or system partitions. Back up first. Eject external content through the storage controls if offered, or shut down before removing the card. The active system disk is protected.

## Updates and recovery

OTA Updates is optional and needs a usable internet connection for downloads. Use this project's compatible update format, not an ordinary upstream ROCKNIX or Slot bundle. There is no public update endpoint promised until this project publishes one. Managed updates retain the current and previous confirmed versions plus at most one staged trial; older variants should not enter the normal boot path.

For an unbootable eMMC update, use the known-good TF1 recovery card and hold F at power-on with our loader. Keep a backup of your games and progress. Report the exact build and boot medium when requesting help.

## Quick checks

| Symptom | Check first |
| --- | --- |
| TF1 starts Android or never reaches setup | Check the [stock Android/legacy-loader prerequisite](Installation.md#before-starting-stock-android-and-the-legacy-bootloader); F-held SD selection requires our installed loader |
| A menu option is missing | Was its module selected during setup? Is the console supported by an installed core? |
| A game is missing | Correct Games folder, uncompressed extension, supported emulator and refreshed library |
| A shortcut does nothing | Installed module, System → Features restriction and remapping conflict |
| Wi-Fi connected but USB terminal fails | USB Networking and SSH must both be enabled; use the USB address |
| USB charges but no drive/adapter appears | DC port, data-capable cable, chosen USB mode and host accessory approval |
| SMB address will not open | Enable a transport and File Sharing; use the displayed IP/share, not the guide's example address |
| A restored battery save seems ignored | Bypass automatic resume by holding A at launch, then use the game's own load menu |
| OTA reports no compatible update | A signed package must match your exact installed base and module selection; no public feed is configured yet |

The diagnostics illustration uses example readings. It is not a current RAM/battery measurement of your handheld.
