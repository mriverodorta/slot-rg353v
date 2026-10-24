# Credits and third-party components

This project adapts upstream work for one RG353V configuration. Attribution does not imply endorsement or replace each component's license. Preserve these notices, the original license files, and corresponding source when distributing binaries.

## Frontend and operating system

| Project / author | What we use or adapt | Source / terms |
| --- | --- | --- |
| Slot / Brandon Kowalski and contributors | Cartridge shelf, UI, GLES renderer, libretro integration and upstream features, extended for RG353V, modular installation and our menu hierarchy | [Slot source](https://github.com/BrandonKowalski/slot), [Slot guide](https://slot-cfw.fyi), GPL-3.0-or-later; [local license](LICENSE) |
| ROCKNIX contributors | Linux appliance base, kernel/device support, toolchain, packages and systemd infrastructure, with our hardware-specific kernel, boot and service changes | [Distribution](https://github.com/ROCKNIX/distribution), [build documentation](https://rocknix.org/contribute/build/); original ROCKNIX software/scripts GPL-2.0 ([pinned license notice](https://github.com/ROCKNIX/distribution/blob/c445081a59518f37d9776e5412dd7b14910696f7/LICENSE.md)), individual packages retain their own terms; ROCKNIX branding has separate CC BY-NC-SA terms |
| Linux / U-Boot / Rockchip firmware contributors | RK3566 boot, device drivers, device trees, eMMC/SD chain and F-held recovery selection | [Linux](https://kernel.org/), [U-Boot](https://source.denx.de/u-boot/u-boot), [Rockchip rkbin](https://github.com/rockchip-linux/rkbin); consult their exact source/package license notices, including firmware terms |
| SDL / Mesa and graphics contributors | SDL2 display/context handling and the installed GPU/EGL/GLES stack | [SDL](https://github.com/libsdl-org/SDL), [Mesa](https://mesa3d.org/); the actual retained userspace/GPU packages are recorded by the ROCKNIX build |
| ksmbd / cifsd-team and Linux SMB contributors | Optional kernel SMB server and its userspace configuration/session helper; used instead of the former Samba server | [ksmbd-tools](https://github.com/cifsd-team/ksmbd-tools), [Linux SMB server](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/fs/smb/server); tools 3.5.7, GPL-2.0-or-later; preserve the package's COPYING and corresponding kernel source |
| Arm / Rockchip / JeffyCN | Mali-G52 userspace binary and ROCKNIX's EGL/GLES integration; the retained GLES-only variant passed the recorded device qualification | [Pinned binary collection](https://github.com/JeffyCN/mirrors/tree/libmali), [ROCKNIX packaging](https://github.com/ROCKNIX/distribution/tree/main/projects/ROCKNIX/packages/graphics/libmali); proprietary binary redistribution terms remain separate from the open-source wrappers |
| MyMinUI / Turro75 and contributors | Hardware reference during initial RG353V bring-up; not the runtime base | [MyMinUI](https://github.com/Turro75/MyMinUI) |
| BaseOS / pvaibhav and contributors | Source comparison and design ideas for deferred startup; this firmware still uses ROCKNIX | [BaseOS](https://github.com/pvaibhav/BaseOS) |

## Emulation

| Component | Use | License and source |
| --- | --- | --- |
| mGBA / endrift and contributors | GB, GBC and GBA via the libretro core, plus the included local save, palette, audio and state fixes | [mGBA](https://github.com/mgba-emu/mgba), [libretro core](https://github.com/libretro/mgba), [MPL-2.0](licenses/mgba-MPL-2.0.txt) |
| gpSP / Exophase, notaz and contributors | Optional alternative GBA libretro core, with the included local patches | [libretro/gpSP](https://github.com/libretro/gpsp), [GPL-2.0](licenses/gpsp-GPL-2.0.txt) |
| libretro contributors | Core API and shader source collection; Slot is the frontend, not RetroArch | [libretro](https://github.com/libretro), [shader collection](https://github.com/libretro/glsl-shaders) |

The current mGBA pin is `7a12d6d4b9acb14c0ae62c9166b6a2f3d08007f6`, based on development 0.11 code. It is device-tested but **not** an official stable mGBA release. gpSP is pinned to `5819380c2ffb0900219d700a382ee68c464ebb99`. The exact patches and source metadata accompany the core builds. ROCKNIX is pinned to released tag `20261001`, commit `c445081a59518f37d9776e5412dd7b14910696f7`; the Slot patch base is `868631d7b131540df87c8e3295638e27445cdba2`.

## Shaders, overlays and fonts

| Work / author | What we use | Reference / terms |
| --- | --- | --- |
| Sharp Shimmerless / zadpos (Woohyun-Kang) | Shimmerless and Sharp LCD adaptations for our game viewport and framebuffer dimensions | [Source](https://github.com/Woohyun-Kang/Sharp-Shimmerless-Shader), [adaptation notes](licenses/shimmerless-source/SOURCE.txt), CC0-1.0 |
| LCD3x / Gigaherz | LCD subpixel shader adapted into Slot's GLES renderer | [LCD3x source](https://github.com/libretro/glsl-shaders/blob/master/handheld/shaders/lcd3x.glsl), public domain; [local notices](licenses/shaders.txt) |
| Dot / Themaister | Dot shader, with Slot's sharper falloff and blend changes | [Source collection](https://github.com/libretro/glsl-shaders/tree/master/handheld/shaders), public domain |
| zfast LCD / Greg Hogan (SoltanGris42) | zfast LCD shader | [Source](https://github.com/libretro/glsl-shaders/blob/master/handheld/shaders/zfast_lcd_standard.glsl), GPL-2.0-or-later |
| Simpletex LCD / jdgleaver | LCD shader using zfast line weighting; paper texture and Slot's grid-bias adaptation | [Source collection](https://github.com/libretro/glsl-shaders/tree/master/handheld/shaders), GPL-2.0-or-later |
| Retro Game Corps / Russ | Guide and collection used to reproduce and compare handheld screen effects; not the original author of every shader or overlay | [Guide](https://retrogamecorps.com/2024/09/01/guide-shaders-and-overlays-on-retro-handhelds/), [RGC Overlay Pack](https://github.com/retrogamecorps/RGC-Overlay-Pack) |
| 1playerinsertcoin / mugwomp93 | Perfect GB/GBC/GBA artwork and DMG palette distributed in the RGC pack | [original creator’s GBA post](https://www.reddit.com/r/MiyooMini/comments/18ovuld/i_made_a_game_boy_advance_overlay/), [muOS adaptations](https://github.com/mugwomp93/muOS_Customization), [authorship and permission evidence](licenses/perfect-overlays/PROVENANCE.md) |
| mugwomp93 / chrizzo-hb | Earlier Perfect GBA SP no-grid bezel, scaled/recolored in the inherited assets | [Original](https://github.com/mugwomp93/Knulli_Customization), [collection](https://github.com/chrizzo-hb/knulli-bezels), [CC BY-SA 4.0 adaptation notice](licenses/bezel-CC-BY-SA-4.0.txt) |
| Nuno Nogueira / JaJaWa | GBA wordmark vector, adapted for the Slot border | [Wikimedia source](https://commons.wikimedia.org/wiki/File:Game_Boy_Advance_logo.svg), [PD-textlogo and trademark notice](licenses/gba-wordmark-PD.txt) |
| Open Sans Project Authors | Embedded Open Sans label font used by the frontend and setup | [Open Sans](https://github.com/googlefonts/opensans), [SIL OFL 1.1 notice](licenses/label-font-OFL-1.1.txt) |
| Nerd Fonts contributors and original font authors | Symbols used by the installer and UI | [Nerd Fonts](https://github.com/ryanoasis/nerd-fonts), [installer font notice](ports/rg353v/image/assets/setup-menu-icons.ttf.LICENSE.txt), [frontend font notice](ports/rg353v/image/assets/SymbolsNerdFontMono-Regular.ttf.LICENSE.txt) |

The bundled Perfect images came from RGC pack commit `a1624d98af4cb0d4af2ff0b21d26d0131a1e4631`. Its supplied notices do not provide an explicit redistribution license for those images/palette. Copyright remains with the original creators and adapters. The owner has directed that public packaging retain these files with attribution and an explicit no-license-specified notice; this is a packaging decision, not evidence of permission. The project's GPL license does not license this artwork. The separately licensed no-grid GBA SP bezel does not establish rights for the entire Perfect pack. Your private images retain their current behavior.

Nintendo's console names, logos and other trademarks identify the emulated systems. This project is not affiliated with Nintendo or the hardware manufacturers.

## Source availability

This repository's device layer, scripts and exact upstream pins form the RG353V build recipe. Firmware packages retain their own source URLs, patches and license metadata. A public binary release must also make the corresponding modified sources/build inputs available under the applicable licenses; a README credit alone is insufficient. See [release preparation](wiki/Releasing.md).

Slot source packaging writes a separate `dist-rg353v/Sources/slot-source.tar.gz` asset, rather than storing it in the installed SYSTEM. Image source builds copy that archive beside the compressed image and record its hash; fast composition accepts `--source-archive`. Each eventual public image and OTA release must link its immutable matching source tag/archive and required build inputs. Removing the on-device archive does not remove source availability obligations or the retained license/copyright notices.

The frontend bundle retains Slot’s GPL text and the embedded Open Sans/Symbols Nerd Font notices under `System/licenses/`, in addition to shader, overlay and core notices. These notices do not replace the exact OS-package corresponding-source review.

The public candidate source-material export additionally collects the patched core sources, Cargo dependency sources, modified ROCKNIX recipes/configuration and OS package source archives. Its manifest distinguishes source archives from proprietary binary-only inputs, records checksums and original URLs, and explains inline/virtual package inputs. Arm, Realtek and Rockchip notices accompany these materials; this does not change their license terms or imply that all firmware is open source. See [Building](wiki/Building.md#release-source-materials).
