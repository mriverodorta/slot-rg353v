# Slot RG353V guide

This guide describes this project's RG353V firmware, not the original Slot build for other handhelds. Menu entries depend on the installed modules.

![The RG353V cartridge shelf](images/features/shelf.png)

Start with the [illustrated installation walkthrough](Installation.md), then [configure the handheld](First-Run-and-Settings.md) and [add your games](Adding-Games.md).

Current startup measurements are **about 4.2–4.3 s from internal eMMC**, or **about 5.2 s from the tested TF1 microSD**. SD results depend on card speed and quality. These timings measure Linux entry to the shelf; see the [runs and timing definitions](Boot-and-Recovery.md#latest-controlled-restarts).

![Setup walkthrough](media/setup-walkthrough.gif)

The walkthrough uses the actual installer renderer. Feature choices and installation progress are demonstrated; installation duration varies.

| Start here | Reference |
| --- | --- |
| [Install, expand and recover](Installation.md) | SD versus eMMC, partition sizes, F boot and backups |
| [Setup presets and modules](Setup-and-Modules.md) | What each optional feature adds or removes |
| [First run and settings](First-Run-and-Settings.md) | Clock, wallpaper, sound, controls and offline startup |
| [Add games and manage storage](Adding-Games.md) | Folder layout, external cards, safe removal and backups |
| [Controls](Controls.md) | Shelf, games, shortcuts and remapping |
| [Menu reference](Menus.md) | Where every group belongs |
| [Saves and states](Saves-and-States.md) | Battery saves, resume, manual saves and recovery |
| [Screen and overlays](Screen-and-Overlays.md) | Scaling, shaders, palettes and Perfect borders |
| [Gameplay and battery](Gameplay-and-Battery.md) | Fast-forward, rewind, run-ahead, audio and power |
| [Startup and recovery](Boot-and-Recovery.md) | Boot animation, timing definitions, sleep and F recovery |
| [Connections](Connections.md) | Wi-Fi, USB networking, SSH, SMB and USB storage |
| [OTA updates](OTA-Updates.md) | Small signed component updates, OS patches and rollback |
| [Screenshots and Gallery](Screenshots-and-Gallery.md) | Capture options, sorting and deletion |
| [Maintenance and troubleshooting](Troubleshooting.md) | Audio, sleep, storage checks and diagnostics |
| [Build from source](Building.md) | Pins, device layer, caches and image composition |
| [Private development](Development.md) | Personal Wi-Fi/public SSH key provisioning |
| [Release procedure](Releasing.md) | Clean image, corresponding source and qualification |

[Credits and licenses](../CREDITS.md) · [Contributing](../CONTRIBUTING.md) · [Project README](../README.md)

These files are the version-controlled user guide and can always be read alongside the code. The separate GitHub Wiki uses the same pages, with links rewritten for wiki navigation.

Screens are native **640×480** renders of the pinned frontend/device layer, with illustrative game images and cartridge artwork. Connection details and storage capacities are examples. No personal Wi-Fi credentials, SSH keys, ROMs, BIOS or save files are included. See [media provenance and reproduction](Media-Production.md).
