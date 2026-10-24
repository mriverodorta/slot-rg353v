# Saves, resume and manual states

## Three different kinds of progress

**Battery save:** the save created through the game's own menu. It lives under `Saves/<platform>/` and is usually the best long-term progress format. Use the game's Continue/Load option after booting normally without a resume state.

**Automatic resume:** the emulator snapshot saved when ejecting with F or shutting down normally through the Power menu. Opening the cartridge normally resumes from it. A cartridge left inserted resumes directly after startup; an ejected cartridge returns to its shelf. Launch while holding A to bypass resume and reach the game's title screen. A forced power loss can lose changes that have not been written.

**Manual state:** a snapshot created by Select + R1 or a state action. Our state browser lists timestamped entries; creating another manual state adds a new entry rather than simply treating every old entry as the current quick slot. Select + L1 uses the quick/manual load path; browse States to deliberately choose an older timestamp. Automatic retention policies can remove old entries, so use battery saves as well.

The state browser is reached through the in-game States access (double-F by default). Left/Right browses entries. Follow A's displayed load action. Y requests deletion; the confirmation requires A to delete, and B cancels. Save/load notifications show text in the fading bar, including with Perfect overlays.

![State browser](images/features/states.png)

![Confirm state deletion](images/features/states-delete.png)

## Feature controls

System → Features can disable the state browser independently of manual save/load shortcuts. Eject resume and game battery saves are separate. A disabled browser does not erase existing files.

## Moving saves from another frontend

Match the exact game filename and core format. A RetroArch `.srm` can be a battery save, whereas `.state` is an emulator-specific snapshot. Compressed/wrapped RetroArch state files may need conversion before our native mGBA state loader accepts them. Gambatte states are not mGBA states. Different core versions or ROM revisions may also be incompatible.

Some GB cartridge saves, notably MBC2 and RTC-backed games, require format handling beyond renaming the extension. Back up both sides before importing. An older `resume.state` can make a newly imported battery save appear absent; bypass resume with A and use the game's own load menu to check it.

## Backup practice

Copy `Saves`, `States` and `Config` along with any content you cannot replace. Eject a running game before transferring these folders so the save is consistent. Safely eject USB Storage on the computer before returning to play. Read/storage failures should be investigated rather than repeatedly saving over an unreadable destination.

## Portable progress

**System → Storage → Save location** chooses **System** or **Game** for battery saves, automatic resume, manual states and the state browser. See [Save location](Adding-Games.md#save-location) for paths, transfer precautions and emulator compatibility. Settings remain on the boot system.
