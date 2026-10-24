# Screens and videos

All images are native 640×480 renders of the installer or frontend. Games and cartridge artwork come from the owner’s collection; capacities, network addresses and service readings are illustrative. No ROMs or saves are bundled. See [media provenance](Media-Production.md).

## Animations

![Setup walkthrough](media/setup-walkthrough.gif)

Setup interface demonstration with condensed installation progress.

![Boot to shelf](media/boot-to-shelf.gif)

Replay of an earlier boot's captured percentage changes and presentation timing. Current measurements are about **4.2–4.3 s from eMMC** and **5.2 s from the tested TF1 microSD**, measured from Linux entry to shelf; SD timing varies with card speed and quality. [Current timings and recovery](Boot-and-Recovery.md#latest-controlled-restarts).

![Feature tour](media/feature-tour.gif)

Real games/art rendered by the frontend, plus connection and Gallery examples. GBA uses Perfect + Shimmerless.

## Installation steps

Follow the [installation walkthrough](Installation.md) for the sequence and safety checks. These cover both destinations and the alternate warnings.

<details><summary>Destination sd</summary>

![Destination sd](images/setup/01-destination-sd.png)

</details>

<details><summary>Destination emmc</summary>

![Destination emmc](images/setup/02-destination-emmc.png)

</details>

<details><summary>Preset minimal</summary>

![Preset minimal](images/setup/03-preset-minimal.png)

</details>

<details><summary>Preset recommended</summary>

![Preset recommended](images/setup/04-preset-recommended.png)

</details>

<details><summary>Preset custom</summary>

![Preset custom](images/setup/05-preset-custom.png)

</details>

<details><summary>Preset full</summary>

![Preset full](images/setup/05-preset-full.png)

</details>

<details><summary>Features emulators</summary>

![Features emulators](images/setup/06-features-emulators.png)

</details>

<details><summary>Features continue</summary>

![Features continue](images/setup/07-features-continue.png)

</details>

<details><summary>Review top</summary>

![Review top](images/setup/08-review-top.png)

</details>

<details><summary>Review bottom</summary>

![Review bottom](images/setup/09-review-bottom.png)

</details>

<details><summary>Confirm sd</summary>

![Confirm sd](images/setup/10-confirm-sd.png)

</details>

<details><summary>Confirm sd selected</summary>

![Confirm sd selected](images/setup/11-confirm-sd-selected.png)

</details>

<details><summary>Complete sd</summary>

![Complete sd](images/setup/12-complete-sd.png)

</details>

<details><summary>Confirm emmc</summary>

![Confirm emmc](images/setup/13-confirm-emmc.png)

</details>

<details><summary>Complete emmc</summary>

![Complete emmc](images/setup/14-complete-emmc.png)

</details>

<details><summary>No transfer warning</summary>

![No transfer warning](images/setup/15-no-transfer-warning.png)

</details>

<details><summary>No emulator warning</summary>

![No emulator warning](images/setup/16-no-emulator-warning.png)

</details>

<details><summary>Setup error</summary>

![Setup error](images/setup/17-setup-error.png)

</details>

## Feature explanations

In Custom setup, highlight a feature and press Y to open its explanation; B closes it. These descriptions and labels come from the same module catalog as the installer.

<details><summary>mGBA (GB / GBC / GBA)</summary>

Play Game Boy, Game Boy Color and Game Boy Advance games. Recommended default emulator. Select at least one emulator.

![mGBA (GB / GBC / GBA) explanation](images/setup/info-emulator-mgba.png)

</details>

<details><summary>gpSP (GBA)</summary>

An alternative emulator for Game Boy Advance games only. Without mGBA, Game Boy and Game Boy Color systems are hidden.

![gpSP (GBA) explanation](images/setup/info-emulator-gpsp.png)

</details>

<details><summary>Wi-Fi</summary>

Connect to wireless networks for transfers and online features. Normally starts off each boot; enable it when needed.

![Wi-Fi explanation](images/setup/info-wifi.png)

</details>

<details><summary>SSH</summary>

Control the handheld from a computer using a terminal. Needs Wi-Fi or USB Networking. Remembers your SSH switch within the current boot when a connection returns.

![SSH explanation](images/setup/info-ssh.png)

</details>

<details><summary>File Sharing (SMB)</summary>

Copy games and saves using your computer's file manager over the network. Needs Wi-Fi or USB Networking.

![File Sharing (SMB) explanation](images/setup/info-sharing.png)

</details>

<details><summary>USB Storage</summary>

Show the games partition as a USB drive on your computer. Safely eject it before returning to Slot.

![USB Storage explanation](images/setup/info-usb-storage.png)

</details>

<details><summary>USB Networking</summary>

Connect by USB to Windows 11, macOS or Linux. Add SSH or File Sharing for access. Internet via USB also needs sharing enabled on the computer.

![USB Networking explanation](images/setup/info-usb-network.png)

</details>

<details><summary>Games from TF1 / TF2</summary>

Play from TF1 or TF2; inserted cards appear automatically on the shelf. Choose System or Game storage for saves and states. Use the Slot folder layout.

![Games from TF1 / TF2 explanation](images/setup/info-external-sd.png)

</details>

<details><summary>Enhanced Audio</summary>

Optional 48 kHz resampling. Adds an Audio setting, initially Off. Uses a little more CPU. Changes apply the next time you open a game.

![Enhanced Audio explanation](images/setup/info-enhanced-audio.png)

</details>

<details><summary>Shaders and Color Filters</summary>

Choose per-console shaders, color correction and frame blending. Some effects use more CPU or GPU power.

![Shaders and Color Filters explanation](images/setup/info-filters.png)

</details>

<details><summary>Console Overlays</summary>

Add console borders around the game, including Slot and Perfect styles. Available styles depend on the system.

![Console Overlays explanation](images/setup/info-overlays.png)

</details>

<details><summary>Frame Counter</summary>

Show a small frame-rate number while playing. Toggle it with Select + X.

![Frame Counter explanation](images/setup/info-frame-counter.png)

</details>

<details><summary>Screenshots</summary>

Capture games with Select + Start. Configure shaders, screen filters and overlays in System. Copy PNG images from Screenshots using a card reader or USB Storage; Gallery is optional.

![Screenshots explanation](images/setup/info-screenshots.png)

</details>

<details><summary>Gallery</summary>

Browse screenshots on the handheld. Sort by game, date or platform, view full screen and delete images with confirmation. Screenshots capture is a separate optional feature.

![Gallery explanation](images/setup/info-gallery.png)

</details>

<details><summary>Rewind</summary>

Move backward through recent gameplay by holding L2. Uses extra memory and processing while recording.

![Rewind explanation](images/setup/info-rewind.png)

</details>

<details><summary>Run-Ahead</summary>

Reduce input delay in GBA games using mGBA. Uses more CPU and can reduce speed in demanding games. Unavailable with gpSP only.

![Run-Ahead explanation](images/setup/info-runahead.png)

</details>

<details><summary>Automatic Network Time</summary>

Set the clock from the internet using Wi-Fi or Internet via USB. USB needs internet sharing on the computer. Manual clock setting stays available.

![Automatic Network Time explanation](images/setup/info-network-time.png)

</details>

<details><summary>OTA Updates</summary>

Download small signed updates in order, continuing after restarts. Preserves installed features and a rollback version. Needs internet access.

![OTA Updates explanation](images/setup/info-updates.png)

</details>

<details><summary>Diagnostics</summary>

View available RAM, temperature, storage, versions and service status. Readings refresh while Diagnostics is open.

![Diagnostics explanation](images/setup/info-diagnostics.png)

</details>

<details><summary>SD Storage Check / Repair</summary>

Manually check or repair SD games storage. Repair needs confirmation and changes filesystem metadata. Back up first. Internal eMMC and system partitions stay protected.

![SD Storage Check / Repair explanation](images/setup/info-storage-tools.png)

</details>

<details><summary>Schedutil Governor</summary>

Add a System switch for an alternative CPU power policy. Initially Off: ondemand 20 ms stays the default. Battery savings vary by game. CPU speed limits stay unchanged.

![Schedutil Governor explanation](images/setup/info-schedutil-governor.png)

</details>

<details><summary>Development Profilers</summary>

Add boot-timing and process-usage tools for development. Recording is enabled separately when investigating an issue.

![Development Profilers explanation](images/setup/info-profilers.png)

</details>

<details><summary>Developer Mode</summary>

Add a Developer Mode switch that keeps network access and SSH available across restarts. Requires SSH and Wi-Fi or USB Networking.

![Developer Mode explanation](images/setup/info-developer.png)

</details>

## Installed settings and features

The reference uses all modules. Your installation hides omitted capabilities; [the menu map](Menus.md) explains where they belong. Expand a screen to view it at native resolution.

<details><summary>About</summary>

![About](images/features/about.png)

</details>

<details><summary>Appearance</summary>

![Appearance](images/features/appearance.png)

</details>

<details><summary>Audio</summary>

![Audio](images/features/audio.png)

</details>

<details><summary>First-run date and time</summary>

![First-run date and time](images/features/clock-setup.png)

</details>

<details><summary>Connections</summary>

![Connections](images/features/connections.png)

</details>

<details><summary>Content</summary>

![Content](images/features/content.png)

</details>

<details><summary>Controls game</summary>

![Controls game](images/features/controls-game.png)

</details>

<details><summary>Controls recording</summary>

![Controls recording](images/features/controls-recording.png)

</details>

<details><summary>Controls shelf</summary>

![Controls shelf](images/features/controls-shelf.png)

</details>

<details><summary>Controls shortcuts</summary>

![Controls shortcuts](images/features/controls-shortcuts.png)

</details>

<details><summary>Controls</summary>

![Controls](images/features/controls.png)

</details>

<details><summary>Cpu governor on</summary>

![Cpu governor on](images/features/cpu-governor-on.png)

</details>

<details><summary>Cpu governor</summary>

![Cpu governor](images/features/cpu-governor.png)

</details>

<details><summary>Date time</summary>

![Date time](images/features/date-time.png)

</details>

<details><summary>Diagnostics services</summary>

![Diagnostics services](images/features/diagnostics-services.png)

</details>

<details><summary>Diagnostics versions</summary>

![Diagnostics versions](images/features/diagnostics-versions.png)

</details>

<details><summary>Diagnostics</summary>

![Diagnostics](images/features/diagnostics.png)

</details>

<details><summary>Favorites shelf</summary>

![Favorites shelf](images/features/favorites.png)

</details>

<details><summary>Feature restrictions, in-game changes</summary>

![Feature restrictions, in-game changes](images/features/features-in-game.png)

</details>

<details><summary>Features</summary>

![Features](images/features/features.png)

</details>

<details><summary>File sharing</summary>

![File sharing](images/features/file-sharing.png)

</details>

<details><summary>Screenshot deletion confirmation</summary>

![Screenshot deletion confirmation](images/features/gallery-delete.png)

</details>

<details><summary>Gallery sorted by date</summary>

![Gallery sorted by date](images/features/gallery-grid-date.png)

</details>

<details><summary>Gallery sorted by game</summary>

![Gallery sorted by game](images/features/gallery-grid-game.png)

</details>

<details><summary>Gallery sorted by platform</summary>

![Gallery sorted by platform](images/features/gallery-grid-platform.png)

</details>

<details><summary>Full-screen image after legends fade</summary>

![Full-screen image after legends fade](images/features/gallery-image-hidden.png)

</details>

<details><summary>Full-screen image with legends</summary>

![Full-screen image with legends](images/features/gallery-image.png)

</details>

<details><summary>Golden Sun: The Lost Age battle</summary>

![Golden Sun: The Lost Age battle](images/features/game-golden-sun-battle.png)

</details>

<details><summary>Metroid Fusion</summary>

![Metroid Fusion](images/features/game-metroid-fusion.png)

</details>

<details><summary>Zelda with Perfect overlay and Shimmerless</summary>

![Zelda with Perfect overlay and Shimmerless](images/features/game-slot-overlay.png)

</details>

<details><summary>Zelda: Link’s Awakening</summary>

![Zelda: Link’s Awakening](images/features/game-zelda-gb.png)

</details>

<details><summary>Zelda: Link’s Awakening DX</summary>

![Zelda: Link’s Awakening DX](images/features/game-zelda-gbc.png)

</details>

<details><summary>Zelda: A Link to the Past</summary>

![Zelda: A Link to the Past](images/features/game-zelda.png)

</details>

<details><summary>Gameplay preferences</summary>

![Gameplay preferences](images/features/game.png)

</details>

<details><summary>Help</summary>

![Help](images/features/help.png)

</details>

<details><summary>Info enhanced audio hint</summary>

![Info enhanced audio hint](images/features/info-enhanced-audio-hint.png)

</details>

<details><summary>Info enhanced audio</summary>

![Info enhanced audio](images/features/info-enhanced-audio.png)

</details>

<details><summary>Info governor hint</summary>

![Info governor hint](images/features/info-governor-hint.png)

</details>

<details><summary>Info governor</summary>

![Info governor](images/features/info-governor.png)

</details>

<details><summary>Info in game shaders hint</summary>

![Info in game shaders hint](images/features/info-in-game-shaders-hint.png)

</details>

<details><summary>Info in game shaders</summary>

![Info in game shaders](images/features/info-in-game-shaders.png)

</details>

<details><summary>Info overlay style hint</summary>

![Info overlay style hint](images/features/info-overlay-style-hint.png)

</details>

<details><summary>Info overlay style</summary>

![Info overlay style](images/features/info-overlay-style.png)

</details>

<details><summary>Info paused game</summary>

![Info paused game](images/features/info-paused-game.png)

</details>

<details><summary>Info run ahead hint</summary>

![Info run ahead hint](images/features/info-run-ahead-hint.png)

</details>

<details><summary>Info run ahead</summary>

![Info run ahead](images/features/info-run-ahead.png)

</details>

<details><summary>Info save location</summary>

![Info save location](images/features/info-save-location.png)

</details>

<details><summary>Info usb network hint</summary>

![Info usb network hint](images/features/info-usb-network-hint.png)

</details>

<details><summary>Info usb network</summary>

![Info usb network](images/features/info-usb-network.png)

</details>

<details><summary>Overlays</summary>

![Overlays](images/features/overlays.png)

</details>

<details><summary>Pause</summary>

![Pause](images/features/pause.png)

</details>

<details><summary>Power menu while a game remains inserted</summary>

![Power menu while a game remains inserted](images/features/power-menu-game.png)

</details>

<details><summary>GB screen preferences</summary>

![GB screen preferences](images/features/screen-gb.png)

</details>

<details><summary>GBA screen preferences</summary>

![GBA screen preferences](images/features/screen-gba.png)

</details>

<details><summary>GBC screen preferences</summary>

![GBC screen preferences](images/features/screen-gbc.png)

</details>

<details><summary>Screen</summary>

![Screen](images/features/screen.png)

</details>

<details><summary>Screenshots</summary>

![Screenshots](images/features/screenshots.png)

</details>

<details><summary>Settings, Gallery and Help</summary>

![Settings, Gallery and Help](images/features/settings-gallery.png)

</details>

<details><summary>Settings, first page</summary>

![Settings, first page](images/features/settings.png)

</details>

<details><summary>Cartridge shelf</summary>

![Cartridge shelf](images/features/shelf.png)

</details>

<details><summary>Ssh set password</summary>

![Ssh set password](images/features/ssh-set-password.png)

</details>

<details><summary>Ssh</summary>

![Ssh](images/features/ssh.png)

</details>

<details><summary>State deletion confirmation</summary>

![State deletion confirmation](images/features/states-delete.png)

</details>

<details><summary>Manual state browser</summary>

![Manual state browser](images/features/states.png)

</details>

<details><summary>Storage eject</summary>

![Storage eject](images/features/storage-eject.png)

</details>

<details><summary>Save location: Game</summary>

![Save location: Game](images/features/storage-game.png)

</details>

<details><summary>Save location: System</summary>

![Save location: System](images/features/storage-system.png)

</details>

<details><summary>Storage: removable cards and progress policy</summary>

![Storage: removable cards and progress policy](images/features/storage-top.png)

</details>

<details><summary>Storage</summary>

![Storage](images/features/storage.png)

</details>

<details><summary>System, lower entries</summary>

![System, lower entries](images/features/system-bottom.png)

</details>

<details><summary>System</summary>

![System](images/features/system.png)

</details>

<details><summary>Updates complete</summary>

![Updates complete](images/features/updates-complete.png)

</details>

<details><summary>Updates resume</summary>

![Updates resume](images/features/updates-resume.png)

</details>

<details><summary>Updates startup check</summary>

![Updates startup check](images/features/updates-startup-check.png)

</details>

<details><summary>Updates waiting internet</summary>

![Updates waiting internet](images/features/updates-waiting-internet.png)

</details>

<details><summary>Updates</summary>

![Updates](images/features/updates.png)

</details>

<details><summary>Usb network</summary>

![Usb network](images/features/usb-network.png)

</details>

<details><summary>USB Storage, shared with computer</summary>

![USB Storage, shared with computer](images/features/usb-storage-connected.png)

</details>

<details><summary>USB Storage, waiting for computer</summary>

![USB Storage, waiting for computer](images/features/usb-storage-waiting.png)

</details>

<details><summary>Usb storage</summary>

![Usb storage](images/features/usb-storage.png)

</details>

<details><summary>Usb</summary>

![Usb](images/features/usb.png)

</details>

<details><summary>Wifi networks</summary>

![Wifi networks](images/features/wifi-networks.png)

</details>

<details><summary>Wifi password</summary>

![Wifi password](images/features/wifi-password.png)

</details>

<details><summary>Wifi status</summary>

![Wifi status](images/features/wifi-status.png)

</details>

<details><summary>Wifi</summary>

![Wifi](images/features/wifi.png)

</details>

## Setup selection and progress reference

The remaining captures show each feature group, selection example, preset review, scrolled review/completion and progress stage. The working-dot phases are animation frames, not separate user actions.

- [Complete 05](images/setup/complete-05.png)
- [Complete 10](images/setup/complete-10.png)
- [Features emulator mgba](images/setup/features-emulator-mgba.png)
- [Features enhanced audio](images/setup/features-enhanced-audio.png)
- [Features network time](images/setup/features-network-time.png)
- [Features wifi](images/setup/features-wifi.png)
- [Progress 005 1](images/setup/progress-005-1.png)
- [Progress 020 1](images/setup/progress-020-1.png)
- [Progress 045 1](images/setup/progress-045-1.png)
- [Progress 075 1](images/setup/progress-075-1.png)
- [Progress 078 1](images/setup/progress-078-1.png)
- [Progress 088 1](images/setup/progress-088-1.png)
- [Progress 096 1](images/setup/progress-096-1.png)
- [Progress 100 1](images/setup/progress-100-1.png)
- [Review 05](images/setup/review-05.png)
- [Review 10](images/setup/review-10.png)
- [Review 15](images/setup/review-15.png)
- [Review 17](images/setup/review-17.png)
- [Review full](images/setup/review-full.png)
- [Review minimal](images/setup/review-minimal.png)
- [Review recommended](images/setup/review-recommended.png)
- [Select gallery](images/setup/select-gallery.png)
- [Select screenshots](images/setup/select-screenshots.png)
- [Select usb network](images/setup/select-usb-network.png)
- [Select wifi](images/setup/select-wifi.png)

[Guide home](Home.md) · [Reproduce the media](Media-Production.md)

<details><summary>SD card scan feedback</summary>

![Scanning SD card for games](images/features/sd-scanning.png)

Native 640×480 frontend preview using existing collection artwork. Insertion feedback occupies the game/console name area and fades after discovery.

</details>
