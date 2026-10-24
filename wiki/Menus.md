# Menu reference

The settings menu scrolls. Uninstalled modules and unavailable cores remove their entries; this is the full conceptual hierarchy, not a promise that every installation shows every item.

```text
Settings
├── Appearance
│   ├── Wallpaper / wallpaper dimming
│   ├── Theme
│   └── Recents
├── Screen
│   ├── Brightness / blue-light filter
│   ├── Game Boy Advance ─ shader, correction, blending
│   ├── Game Boy Color ─ shader, correction, blending
│   ├── Game Boy ─ shader, palette, blending
│   ├── Integer scaling
│   ├── Overlays ─ On/Off, Slot/Perfect style
│   └── Frame counter
├── Audio
│   ├── Speaker volume / headphone volume / mute
│   ├── Enhanced Audio
│   └── Fast-forward sound
├── Gameplay
│   ├── Fast-forward / rewind / run-ahead
│   ├── Turbo / rumble
│   └── Eject save behavior
├── Controls ─ game buttons, shortcuts, shelf controls
├── Connections
│   ├── Wi-Fi ─ On/Off, status, other networks
│   ├── USB ─ USB Storage, USB Networking
│   ├── File Sharing ─ On/Off, status, address
│   └── SSH ─ On/Off, status, authentication
├── System
│   ├── Date & Time
│   ├── Shutdown after sleep
│   ├── Schedutil Governor ─ Off: ondemand 20 ms / On: schedutil
│   ├── Features
│   │   ├── Save states browser
│   │   ├── Manual save states
│   │   ├── Favorites
│   │   ├── Core selection
│   │   ├── Fast-forward
│   │   ├── Rewind
│   │   └── Allow In-Game Change
│   │       ├── Shaders
│   │       ├── Palettes
│   │       └── Color Correction
│   ├── Screenshots ─ shaders, filters, overlay
│   ├── Content
│   ├── OTA Updates
│   ├── Developer Mode
│   ├── Storage
│   │   ├── TF1 / TF2 ─ eject or mount
│   │   ├── Save location ─ System / Game
│   │   └── Check/Repair Storage
│   ├── Diagnostics
│   └── About
├── Gallery
└── Help
```

The Allow In-Game Change heading groups three same-level toggles; it is not another submenu. Likewise, Shutdown after sleep stays directly inside System. Diagnostics sits above About; Help stays at the top level. Core selection is hidden/disabled when only one compatible installed core is available.

Highlight a setting with **Y Info** in its bottom legend and press **Y** for a short explanation. Press **B** to close it and return to the same row and value. A, directions and shortcuts do not change anything while the explanation is open. The same help is available in the paused-game settings and on **Storage → Save location**. Simple settings and button-remapping rows keep their existing controls, including Y Reset where shown.

Help covers CPU policy, Enhanced Audio, run-ahead and rewind, save behavior, screen effects, network connections and services, screenshots and feature restrictions. It is generated only when opened, without loading help textures during shelf startup.

| Setting with contextual help | Y Info |
| --- | --- |
| ![Governor setting with Y Info](images/features/info-governor-hint.png) | ![Governor explanation](images/features/info-governor.png) |

Settings use the selected wallpaper. Waking from a settings screen intentionally returns to the shelf rather than reopening Settings.

| Top-level settings | System, scrolled |
| --- | --- |
| ![Settings](images/features/settings.png) | ![System settings](images/features/system-bottom.png) |

Every screen is linked in the [visual reference](Screens-and-Media.md). The pages below expand the practical steps:

- [First-run settings](First-Run-and-Settings.md): time, appearance, sound and restrictions.
- [Connections](Connections.md): Wi-Fi, USB networking, SSH, SMB and USB Storage.
- [Screenshots and Gallery](Screenshots-and-Gallery.md): capture, sort, browse and delete.
- [Games and storage](Adding-Games.md): content paths, external cards and safe eject.
