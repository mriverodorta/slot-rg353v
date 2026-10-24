# Slot for Anbernic RG353V

A focused Game Boy, Game Boy Color and Game Boy Advance firmware for the **Anbernic RG353V**, combining [Slot](https://github.com/BrandonKowalski/slot) with a device-specific [ROCKNIX](https://github.com/ROCKNIX/distribution) base.

Browse cartridges, play, suspend and resume. Choose optional features during installation; their menus follow what you install. This is an independent RG353V adaptation, not an official release from the upstream authors. Other handhelds and RG353V panel variants have not been qualified by this project.

![Slot RG353V cartridge shelf](wiki/images/features/shelf.png)

The [illustrated user guide](wiki/Home.md) covers every setup page, optional module, connection method and game control. Browse [all screens and videos](wiki/Screens-and-Media.md), including the native-resolution setup walkthrough and boot timing replay.

## Install

1. Download this project's compressed `.img.gz` from [GitHub Releases](https://github.com/mriverodorta/slot-rg353v/releases/latest). Use the **public release**, not an image marked `PRIVATE`.
2. Flash it to a spare microSD with [balenaEtcher](https://etcher.balena.io/). Select the compressed image directly. Flashing erases the selected card.
3. Insert the card in **TF1**. If our eMMC loader is already installed, hold **F** while powering on to boot TF1.
4. Choose **Set up this SD card** or **Install to internal eMMC**, then choose Minimal, Recommended, Full or Custom. Full automatically includes every feature available in the image. Review the destination and features before confirming. Internal installation replaces the eMMC system, including Android.
5. Setup creates a **512 MiB boot** partition, **512 MiB system storage**, and an **exFAT SLOT content partition using the remaining space**. It uses the destination's actual capacity. This layout returns **5 GiB** to games compared with the earlier layout; existing installations keep their partition sizes until reinstalled.
6. Restart as directed. When booting a setup SD beside an installed eMMC system, hold **F** while pressing **A** to restart into that SD.
7. Check the clock; Miami/Eastern time is the initial choice. Add your own uncompressed `.gb`, `.gbc` and `.gba` games to `Games/GB`, `Games/GBC` and `Games/GBA` on SLOT.

See [installation and recovery](wiki/Installation.md) before replacing an existing installation. Images contain no commercial games, BIOS files or personal saves. Back up your content before flashing or reinstalling.

The image release contains only the flashable image and its checksum. Optional [source materials](SOURCES.md) are organized in a separate release; they are not needed for installation.

## Features

| Area | What this build provides |
| --- | --- |
| Games | mGBA for GB/GBC/GBA; optional gpSP for GBA; D-pad and left-stick movement |
| Shelf | Cartridge names, remembered browsing position, optional Favorites and live Wi-Fi status |
| Saves | Battery saves, eject resume, manual states and a browser; save on the system or alongside the game library |
| Picture | Per-console screen settings, shaders, color correction, GB palettes and frame blending |
| Borders | Slot and Perfect border styles; see [third-party artwork ownership and license notices](CREDITS.md) |
| Capture | Independent Screenshots and Gallery modules; PNG capture, sorting, browsing and confirmed deletion |
| Audio | Speaker/headphone routing and separate volumes; optional Enhanced Audio, off by default |
| Storage | eMMC or SD installation, optional games from TF1/TF2, USB mass storage and SD checks |
| Connections | Optional Wi-Fi, SSH, SMB and USB networking; ordinary boots start offline |
| Control | Remappable inputs and shortcuts; System → Features can disable advanced controls |
| Maintenance | Optional Diagnostics, development profilers, compatible updates and rollback |

Installed modules determine which entries appear. Installing a network feature does not automatically switch it on. Developer Mode deliberately keeps selected development access available across restarts.

## Build your own image

The authoritative firmware is the pinned upstream source plus `ports/rg353v/layer/`. Use the image workflow below; the earlier bring-up prototype is archived locally under ignored `resources/bringup-prototype/`.

On an ARM64 Docker host, install Git, Python **3.11+**, Bash, a C compiler and OpenSSL 3 or newer on PATH. The pinned container supplies Rust. Start Docker, then run:

```sh
python3 scripts/build-image.py release --version my-build --plan
bash scripts/build-release.sh --version my-build
```

The first build downloads and compiles the toolchain and OS and needs substantial disk space and memory. Outputs go to ignored `release/my-build/`. Exact upstream commits are locked; the command does not update them to development branches. See [the build guide](wiki/Building.md) for prerequisites, stages, known limitations and faster composition from qualified inputs.

Personal images use a separate command and ignored credential directory:

```sh
bash scripts/build-localdev.sh --version my-development-build
```

This embeds configured Wi-Fi profiles and the SSH **public** key for your own handheld. It never embeds your computer's SSH private key. Never publish the resulting `PRIVATE` image. See [development](wiki/Development.md).

## Documentation

Start at the [wiki index](wiki/Home.md): [setup modules](wiki/Setup-and-Modules.md), [controls](wiki/Controls.md), [menus](wiki/Menus.md), [saves](wiki/Saves-and-States.md), [screen effects](wiki/Screen-and-Overlays.md), [connections](wiki/Connections.md), [screenshots](wiki/Screenshots-and-Gallery.md), [troubleshooting](wiki/Troubleshooting.md) and [contributing](CONTRIBUTING.md).

Current startup is **about 4.2–4.3 seconds when the system boots from internal eMMC**, versus **about 5.2 seconds from the tested TF1 microSD**; SD timing depends on card speed and quality. The latest three controlled restarts averaged **4.295 s on eMMC** and **5.190 s on SD**, with the same software, all 23 modules and the 81-game library/active saves on TF2. These measure Linux entry to the first shelf frame and exclude the physical Power/rumble and bootloader interval. See [startup measurements and conditions](wiki/Boot-and-Recovery.md#latest-controlled-restarts).

## Credits and licenses

Perfect GB/DMG, GBC and GBA overlays and the DMG palette are the work of **[1playerinsertcoin](https://www.reddit.com/user/1playerinsertcoin/)**, with adaptations by **[mugwomp93](https://github.com/mugwomp93/muOS_Customization)**, collected in the **[Retro Game Corps Overlay Pack](https://github.com/retrogamecorps/RGC-Overlay-Pack)**. Copyright remains with their respective creators. **No explicit redistribution license was found for these files.** They are separately credited third-party artwork; this project's GPL license does not grant rights to that artwork. See [the exact provenance and file notices](licenses/perfect-overlays/PROVENANCE.md).

Built on the work of the Slot, ROCKNIX, mGBA, gpSP, libretro, shader and overlay authors. Read [CREDITS.md](CREDITS.md) for individual links, adaptations and asset licensing, and [LICENSE](LICENSE) for Slot's GPL terms. Components keep their own licenses. The first public candidate passed clean Full SD installation, game/save/USB/sleep-wake checks and three retained cold starts. See [qualification details and tested host limits](wiki/Releasing.md).
