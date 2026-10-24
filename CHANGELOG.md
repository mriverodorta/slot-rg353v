# RG353V changes

## v0.1.0 — 24 October 2026

- Prepare application state and visible-cartridge pixels alongside RG353V graphics startup; retain exact artwork checks, complete first-shelf rendering and synchronous fallback. Controlled SD tests improved frontend initialization by 126 ms; total boot time remained effectively unchanged in the three-run comparison.

- Overlap internal ROM/artwork discovery with graphics, resolve primary cartridge settings after legacy migration, and refresh changed directory snapshots before presenting the first shelf.

- Defer RG353V content-folder completion until after the first displayed scene; keep configuration migration before settings load, and skip unused label/shell reads when a library or console has no valid ROMs.

- Show scanning feedback in the shelf name area during SD insertion, then fade back to the current game/console name.
- Rediscover TF1/TF2 libraries automatically after safe eject and physical reinsertion, using Linux block events plus sysfs media-generation fallback; defer mount changes during gameplay and USB Storage.

- Qualify the complete public source-build wrapper from a clean clone; prevent Python cache files entering source archives, fix installer helper invocation and audit the validated lean audio dependency set.
- Freeze U-Boot compiler/FIT metadata so source builds can reproduce the qualified loader identity; retain GPL and embedded-font notices in the frontend bundle.
- Device-specific ROCKNIX base with the qualified slim kernel, lean startup and eMMC-first/F-held TF1 recovery loader.
- Small first-boot image; SD/eMMC installation uses 512 MiB boot, 512 MiB Linux storage and remaining exFAT content space.
- Minimal, Recommended, Full and Custom setup, contextual feature explanations, review screen and installation activity indicator.
- Optional modules with matching menu visibility; ordinary offline startup and explicit Developer Mode.
- mGBA GB/GBC/GBA and optional gpSP GBA, safe save/resume handling, manual states, Favorites, per-console picture settings and remappable controls.
- Speaker/headphone routing, optional Enhanced Audio, screenshots and independent Gallery, USB storage/networking and external-card content.
- System/Game save location: progress stays on the boot system or travels with each game library; device settings remain on the boot system.
- Native TF1/TF2 boot discovery and guarded writable card mounts for portable progress.
- Fresh removable-library scans overlap graphics initialization while preserving a complete first shelf.
- Diagnostics reports the installed File Sharing service instead of the retired Samba service name.
- Signed OTA catch-up sessions with ordered updates, durable reboot continuation, a two-minute internet wait, safe cancellation and verified final-version detection.
- Optional Schedutil Governor installer module and System toggle; ondemand 20 ms remains the default.
- SSH remembers its selected state during a Wi-Fi/USB transport cycle without changing ordinary offline startup.
- Contextual Y Info explanations in Settings, paused-game settings and Save location; B closes without changing the selected value.
- Scrollable settings, System → Features restrictions, Diagnostics separated from development profilers, update/rollback and guarded SD tools.
- Separate Linux Cargo target caches, serial Rust test execution and current-hierarchy graphics smoke checks for the source-build workflow.
- Read-only source/payload privacy inventory and local GitHub Wiki export with revision-specific image/source URLs.
- Public build resources, private development provisioning and release outputs separated; README, wiki and individual upstream credits added.

The published image is the exact qualified `rc-20261023-build4` artifact. Clean Full SD installation, three retained cold starts, game/save/USB/sleep-wake checks, clean source build and privacy/source-material inspections passed. Matching source archives accompany the image. The production signed OTA catalog was fetched and verified by the public SD installation and reported up to date. Perfect retains creator ownership and an explicit no-license-specified notice. Windows hosts and other panel variants remain unqualified.

The original Slot project's changes are documented by [its upstream releases](https://github.com/BrandonKowalski/slot/releases).
