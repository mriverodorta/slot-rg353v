# Picture, scaling and overlays

The tested internal display is 640×480. GB/GBC games are 160×144; GBA games are 240×160. These shapes do not exactly match the panel.

![Screen configuration](images/features/screen.png)

| Console / mode | Game rectangle | Unused space |
| --- | --- | --- |
| GB/GBC at integer 3× | 480×432 | 80 px each side, 24 px top/bottom when centered |
| GBA at integer 2× | 480×320 | 80 px each side, 80 px top/bottom when centered |
| GB/GBC full height, aspect preserved | approximately 533×480 | approximately 53–54 px each side |
| GBA full width, aspect preserved | approximately 640×427 | approximately 53 px remaining vertically |

Slot borders use the full-height GB/GBC and full-width GBA layouts. GBA is aligned to the top with its border/logo below. These are fractional scales, not integer 3×/2×. Overlays can constrain the viewport to their designed opening; stretch/shrink shortcuts are blocked while overlays are active to preserve alignment.

## Shaders versus overlays

| GBA | GB | GBC |
| --- | --- | --- |
| ![GBA picture settings](images/features/screen-gba.png) | ![GB picture settings](images/features/screen-gb.png) | ![GBC picture settings](images/features/screen-gbc.png) |

- **Off:** no selected decorative shader; baseline display sampling/scaling still occurs.
- **Shimmerless:** controls fractional-scaling shimmer while keeping a clean picture.
- **Sharp LCD:** Shimmerless-based scaling plus an LCD grid effect.
- **LCD3x:** an LCD subpixel look. The name does not force a 3× integer game viewport.
- Other retained Slot effects include Dot, zfast LCD and Simpletex.

Each console has its own screen preferences. GB also has palettes; color correction and frame blending solve different problems from scaling. Frame blending combines consecutive images and can reproduce effects used by older displays, but changes motion appearance and processing cost.

Open Screen → Game Boy, Game Boy Color or Game Boy Advance. Left/Right cycles the selected option. Shader choices begin **Off → Shimmerless → Sharp LCD**, followed by the retained effects. Default shortcut assignments are Select + A/B for next/previous shader and Select + Y for correction; GB palettes use Select + R2/L2. System → Features can disable those shortcuts without changing the selected effect.

### Border style and positioning

![Overlay switches](images/features/overlays.png)

Open **Screen → Overlays**. **Overlay** enables/disables the border; **Overlay Style** selects Slot or Perfect. The GBA Slot opening fills the width, aligns to the top and leaves a logo strip below. GB/GBC fill the height with their console borders on the sides. No game pixels are intentionally cropped by those Slot layouts.

An overlay is an image drawn with the game. Slot-style borders primarily decorate unused space. Perfect artwork can also add a pixel-grid/display appearance over the game itself. Combining that with a strong LCD shader stacks effects. For comparing Perfect to its source setup, start with the shader Off, then adjust deliberately. The screenshot options let you choose which layers to include.

Perfect's original and adaptation credits, copyright ownership and no-license-specified status are documented in [CREDITS](../CREDITS.md). The pack is retained as a project packaging decision; this does not establish creator permission or place its artwork under the project's GPL license. The shaders have separate provenance and terms.

To compare the Retro Game Corps/Perfect presentation, choose Perfect and start with the shader **Off**. For your own Slot-style combination, switch to Slot and compare Sharp LCD, LCD3x or a clean Shimmerless picture. A Perfect grid is itself part of the picture effect; it is not only a decorative logo strip. Settings pages remain readable and save/load notifications render above the effect.

Use [Retro Game Corps' guide](https://retrogamecorps.com/2024/09/01/guide-shaders-and-overlays-on-retro-handhelds/) as a reference. Our native Slot renderer implements the effects directly; this is not a RetroArch preset UI.

## GBA examples: Perfect and Shimmerless

The illustrations below use **Perfect overlay + Shimmerless**. They show games running through the qualified mGBA core in the documentation capture environment; they are picture examples, not device performance measurements.

![Zelda with Perfect and Shimmerless](images/features/game-zelda.png)

![Metroid Fusion with Perfect and Shimmerless](images/features/game-metroid-fusion.png)

![Golden Sun battle with Perfect and Shimmerless](images/features/game-golden-sun-battle.png)
