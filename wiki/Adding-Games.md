# Games, content and storage

## Content folders

The exFAT partition named **SLOT** holds your library. The internal Linux path is `/storage/slotcontent`; a computer mounting the partition sees its top-level folders directly.

```text
SLOT/
├── Games/
│   ├── GB/             .gb games
│   ├── GBC/            .gbc games
│   └── GBA/            .gba games
├── Saves/              in-game battery saves
├── States/             automatic resume and manual states
├── Labels/             cartridge artwork
├── Wallpapers/         optional wallpapers
├── Screenshots/        PNG captures
├── BIOS/               your legally obtained BIOS, if needed
└── Config/             content settings and public-key import folder
```

Copy uncompressed games into the matching console folder. ZIP and 7z archives are not playable. Only platforms supported by an installed emulator appear: mGBA supplies all three; gpSP alone supplies GBA. The image includes no commercial ROMs or proprietary BIOS.

## Choose a transfer route

| Route | What you need | Procedure |
| --- | --- | --- |
| Card reader | SD installation | Shut down, wait for shutdown, remove the system card and mount SLOT on the computer. Copy, safely eject, reinsert and boot. |
| USB Storage | Installed USB Storage module | Eject a game, open Connections → USB → USB Storage, connect the DC USB-C data port and start transfer. Safely eject SLOT on the computer before finishing. |
| SMB | File Sharing plus Wi-Fi or USB Networking | Enable the connection and File Sharing. Open its displayed share address and copy files. |
| SSH/SFTP | SSH plus Wi-Fi or USB Networking | Enable the connection and SSH. Use SFTP to the content path above. |
| Secondary card | Games from TF1 / TF2 module | Use a compatible Slot card layout. Insert on the shelf to discover games automatically, or insert before boot. |

The [connection walkthrough](Connections.md) has each screen and platform-specific address examples.

## Refresh after copying

![Content menu](images/features/content.png)

Return to Slot after completing the transfer. Use **System → Content** when you need its library/refresh actions. A missing game may have the wrong extension, be compressed, sit in the wrong console folder, or require an emulator you did not install. Files copied by macOS can include hidden metadata; these are not additional games.

## Secondary cards and safe ejection

![Storage controls](images/features/storage.png)

Open **System → Storage** to inspect TF1/TF2. Select a mounted secondary card, press A and confirm the eject action. Wait for success before physically removing it. The current system disk is protected. After safely ejecting and physically reinserting a secondary card, its games return automatically while on the shelf. Allow a few seconds for mounting and the debounced library scan. The shelf temporarily shows **Scanning SD card for games...** in its game/console name area, then fades back to the current name when scanning finishes. If the card is still inserted after Eject, it stays safely unmounted until you choose Mount or physically reinsert it.

Boot card discovery uses the RG353V native helper before Slot starts. Slot reads mounted SD game and artwork directories in a background thread while graphics initializes, then waits for that scan before constructing the first shelf. The scan runs fresh each boot; there is no persistent library index. After startup, the existing background worker listens for Linux SD block-device events and checks lightweight sysfs media identities as a fallback. It rescans mounts only when media changes or you request a refresh, and waits while a game or USB Storage is active. No extra boot service is added. Python storage-management tools run on demand. Slow cards can still extend startup when their scan outlasts graphics initialization.

![SD card scan feedback](images/features/sd-scanning.png)

![Confirm secondary-card ejection](images/features/storage-eject.png)

While running from eMMC, either slot can supply a supported games library. While running from SD, the active system SD is required and must not be removed. A recovery card can retain its boot/system partitions and expose games from its SLOT partition; formatting the entire recovery card as exFAT removes its recovery installation.

SD Storage Check / Repair is a separate optional module. Its operations apply to supported SD game storage, require confirmation and can change filesystem metadata. Back up before repair. It is not a general eMMC/system repair tool.

## Save location

With **Games from TF1 / TF2** installed, open **System → Storage → Save location**. Press A or Left/Right to choose; Y opens an explanation and B closes it:

| Option | Battery saves and save states |
| --- | --- |
| **System** (default) | The SLOT partition belonging to the system you booted. An eMMC boot saves internally; an SD boot saves on that system SD. |
| **Game** | The library volume containing each game's ROM. TF1 games use TF1 `Saves/` and `States/`; TF2 games use TF2. Internal games still save internally. |

Folders stay separate: `Saves/<console>/<game>.sav` for in-game saves and `States/<console>/<emulator>/<game>/` for resume and manual states. Device settings stay in the boot system's `Config/`. The state browser and save/load shortcuts follow the same location.

![Game save location](images/features/storage-game.png)

Eject the game before changing this option. Switching does **not** copy, merge or overwrite existing progress; each location keeps its own save set. Back up and transfer the desired progress before switching if you want to continue it. Game mode makes managed secondary cards writable, so always use **Storage → Eject** before removing them. A missing or read-only card produces a storage error rather than silently saving internally or into RAM.

A portable library can travel between handhelds configured to use those folders. Battery saves are generally easier to share between emulators. Save states depend on the emulator and its version; using mGBA elsewhere does not guarantee compatibility with every mGBA build.

Secondary libraries also supply their cartridge labels, BIOS, wallpapers and screenshots to the relevant browsers. New screenshots continue to use the system SLOT partition; **Save location** controls game saves and states.

## Keep progress safe

Eject a running game before copying Saves, States or Config. Avoid copying a stale backup over newer progress. Back up those folders along with artwork, wallpapers and screenshots you want to keep. USB Storage gives the computer ownership of SLOT; do not write it from another connection at the same time.

[Saves and state formats](Saves-and-States.md) · [Recovery](Installation.md#emmc-boot-and-recovery)
