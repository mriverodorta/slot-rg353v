# Gameplay, sound and battery

![Gameplay preferences](images/features/game.png)

Open **Settings → Gameplay** to adjust the installed game features. System → Features can disable their user actions; optional modules must first be installed.

| Feature | What it does | Trade-off |
| --- | --- | --- |
| Fast-forward | Advances emulation faster while held, within available CPU capacity | Presentation may skip frames; the visible counter can fall while emulation runs faster |
| Rewind | Records recent emulation history and moves backward while held | Uses CPU and memory while recording |
| Run-Ahead | Speculatively emulates frames to reduce input delay in supported mGBA GBA games | Extra CPU cost; check demanding games and disable it if speed or sound suffers |
| Turbo Buttons | Repeats a mapped game button | Only the configured game buttons repeat |
| Rumble | Enables supported vibration events | Game/core support determines when it occurs |
| Auto Save on Eject | Controls the configured eject/resume behavior | Keep in-game battery saves as well as emulator states |

## Pause and resume

![In-game pause menu](images/features/pause.png)

Tap **F** to pause and open the in-game menu. Resume returns to play; Settings exposes the relevant picture, gameplay and control adjustments; Exit Game returns to the shelf. **Hold F** is the direct eject shortcut. Double-F opens States when enabled. [Progress formats](Saves-and-States.md).

## Sound

![Speaker, headphone and audio options](images/features/audio.png)

The speaker and 3.5 mm headphones keep separate volume levels. Start at a comfortable low volume after changing outputs. The active route should survive sleep/wake and jack insertion/removal.

**Enhanced Audio** is an optional installed module and an Audio switch. It is Off by default. Turning it On selects the enhanced 48 kHz resampling path on the next game launch. Standard mode remains available; compare sound and sustained game speed rather than assuming enhanced mode saves power.

## Frame counter and original timing

Install Frame Counter, then use **Select + X** to toggle its small integer display. It sits in the lower-right corner. It shows presented game frames, not every emulated fast-forward frame. GB/GBC/GBA timing is approximately 59.7 frames per second, so a displayed 59/60 is normal rounding. A shader, demanding scene or run-ahead can change delivered frame pacing.

## Power use

The build is tuned for this handheld; ordinary starts leave optional network services off. Enable Wi-Fi, USB networking, file sharing and SSH when needed. Display brightness, audio output/volume, game load and effects all influence battery use. Developer Mode intentionally keeps access available and is not the offline battery baseline.

The CPU uses the qualified ondemand policy with a 20 ms sampling interval. That is a governor decision interval, not a 20 ms input delay or a cap on game frame rate. Powersave mode is not the default gameplay policy. Do not infer whole-battery runtime from a short percentage sample or compare runs with different brightness, volume or scenes.

A Metroid: Zero Mission title/demo comparison used 13 minutes per governor, excluding two minutes of warm-up. Schedutil measured 2.118 W versus 2.160 W for ondemand 20 ms, with nearly identical average frame delivery (59.92 versus 59.86 FPS). This single sequential pair does not establish a meaningful battery-life gain; the default remains ondemand 20 ms.

If you install the optional **Schedutil Governor** module, System → Schedutil Governor lets you compare the alternative policy. It starts Off, even with a Full installation. On selects schedutil; Off restores ondemand with its 20 ms sampling interval. The choice applies without restarting and is remembered on reboot and wake. Startup still uses its normal brief boost through the first visible frame. CPU frequency limits and GPU settings stay unchanged.

![Optional CPU governor setting](images/features/cpu-governor.png)

## Sleep and shutdown

Tap Power to sleep and tap it again to wake. **System → Shutdown After Sleep** controls the configured long-sleep shutdown behavior. Use Slot's power menu for normal power-off and wait for it to finish before removing cards. Forced long-press shutdown is reserved for an unresponsive device.

Diagnostics can show live system status; Development Profilers is a separate optional development toolkit. Installing it does not automatically run continuous profiling. [Troubleshooting](Troubleshooting.md).
