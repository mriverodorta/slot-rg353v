# Setup presets and optional modules

The core provides the launcher, required OS/display/input/audio/storage foundations and installation health checks. Select at least one emulator. Optional package files and exclusive libraries are omitted from the installed system when their module is not selected; features implemented inside the shared frontend are gated by the installed-feature policy rather than compiled into a separate frontend for every combination.

## Presets

| Preset | Included | Flow |
| --- | --- | --- |
| Minimal | mGBA for GB/GBC/GBA; essential runtime only | Skips custom selection and opens review |
| Recommended | mGBA, USB Storage, TF1/TF2 games, shaders, overlays and rewind | Skips custom selection and opens review |
| Full | Every emulator and optional feature in the image's module catalog | Skips custom selection and opens review |
| Custom | Your selected emulators and optional modules | Opens the feature selector, then review |

Presets appear in a 2×2 grid: Minimal and Recommended above Full and Custom. Use Up/Down and Left/Right to move, A to select, B to return. Full is calculated from the module catalog at selection time, so it includes newly added features automatically. It does not force optional runtime effects or network services On. On private development images, Full is initially highlighted and the prepared developer-access options are applied when its required features are selected.

On the feature selector, **A or Left/Right** switches the selected feature On/Off. **Y** opens its explanation and **B** closes that explanation. Continue moves to review. Review is read-only; B returns to change choices. An activity indicator and elapsed time show that installation is working.

![Preset choice](images/setup/05-preset-custom.png)

![Custom module selection](images/setup/06-features-emulators.png)

See the [complete illustrated installation](Installation.md) for the SD/eMMC path. The [visual reference](Screens-and-Media.md#feature-explanations) contains the Y explanation for every module, captured from the current catalog.

Setup warns when no emulator is selected or when the selected destination lacks a practical way to add games. An eMMC system with all transports disabled needs an installed external-card route, for example. Dependencies and missing access routes must be resolved or acknowledged as directed before confirmation.

## Modules

| Module | What it adds |
| --- | --- |
| mGBA (GB / GBC / GBA) | Play Game Boy, Game Boy Color and Game Boy Advance games. Recommended default emulator. Select at least one emulator. |
| gpSP (GBA) | An alternative emulator for Game Boy Advance games only. Without mGBA, Game Boy and Game Boy Color systems are hidden. |
| Wi-Fi | Connect to wireless networks for transfers and online features. Normally starts off each boot; enable it when needed. |
| SSH | Control the handheld from a computer using a terminal. Needs Wi-Fi or USB Networking. Remembers your SSH switch within the current boot when a connection returns. |
| File Sharing (SMB) | Copy games and saves using your computer's file manager over the network. Needs Wi-Fi or USB Networking. |
| USB Storage | Show the games partition as a USB drive on your computer. Safely eject it before returning to Slot. |
| USB Networking | Connect by USB to Windows 11, macOS or Linux. Add SSH or File Sharing for access. Internet via USB also needs sharing enabled on the computer. |
| Games from TF1 / TF2 | Play from TF1 or TF2; inserted cards appear automatically on the shelf. Choose System or Game storage for saves and states. Use the Slot folder layout. |
| Enhanced Audio | Optional 48 kHz resampling. Adds an Audio setting, initially Off. Uses a little more CPU. Changes apply the next time you open a game. |
| Shaders and Color Filters | Choose per-console shaders, color correction and frame blending. Some effects use more CPU or GPU power. |
| Console Overlays | Add console borders around the game, including Slot and Perfect styles. Available styles depend on the system. |
| Frame Counter | Show a small frame-rate number while playing. Toggle it with Select + X. |
| Screenshots | Capture games with Select + Start. Configure shaders, screen filters and overlays in System. Copy PNG images from Screenshots using a card reader or USB Storage; Gallery is optional. |
| Gallery | Browse screenshots on the handheld. Sort by game, date or platform, view full screen and delete images with confirmation. Screenshots capture is a separate optional feature. |
| Rewind | Move backward through recent gameplay by holding L2. Uses extra memory and processing while recording. |
| Run-Ahead | Reduce input delay in GBA games using mGBA. Uses more CPU and can reduce speed in demanding games. Unavailable with gpSP only. |
| Automatic Network Time | Set the clock from the internet using Wi-Fi or Internet via USB. USB needs internet sharing on the computer. Manual clock setting stays available. |
| OTA Updates | Add small signed Slot/core updates and OS patches, with ordered catch-up and continuation after restarts. Downloads need an internet connection. See [OTA updates](OTA-Updates.md). |
| Diagnostics | View available RAM, temperature, storage, versions and service status. Readings refresh while Diagnostics is open. |
| SD Storage Check / Repair | Manually check or repair SD games storage. Repair needs confirmation and changes filesystem metadata. Back up first. Internal eMMC and system partitions stay protected. |
| Schedutil Governor | Add a System switch for an alternative CPU power policy. Initially Off: ondemand 20 ms stays the default. Battery savings vary by game. CPU speed limits stay unchanged. |
| Development Profilers | Add boot-timing and process-usage tools for development. Recording is enabled separately when investigating an issue. |
| Developer Mode | Add a Developer Mode switch that keeps network access and SSH available across restarts. Requires SSH and Wi-Fi or USB Networking. |

Only mGBA supplies GB/GBC support. gpSP alone leaves a GBA-only system; absent platforms are hidden. Core switching is unavailable when only one compatible core is installed.

Screenshots and Gallery are independent. Diagnostics has no export action. Enhanced Audio and Schedutil Governor are installed separately and still default Off. Developer Mode is available only when its required SSH and transport capabilities are installed. Installing Wi-Fi, SSH or SMB does not start them on every ordinary boot.

Runtime **System → Features** is different from installation: its toggles restrict advanced user actions without reinstalling files. It is not an installer module manager, and it does not add omitted packages. See [Menus](Menus.md) and [Controls](Controls.md).
