# Wiki images, animation and reproduction

The guide and its assets are version-controlled in `wiki/`. Markdown links use relative paths so the guide can be browsed with the source on GitHub. The separate GitHub Wiki is a different Git repository. `scripts/export-rg353v-wiki.py` prepares its Markdown pages locally, rewriting page links to Wiki URLs and credit/source links and image embeds to an explicit source tag or commit. Images remain in the versioned source repository. No wiki or media is uploaded by this tool.

## Provenance

| Asset | How it is made |
| --- | --- |
| Setup PNGs | The actual `slot-setup-ui.py` Canvas and Model with example storage capacities and public feature defaults |
| Settings/shelf PNGs | The pinned Slot frontend plus RG353V layer, running with SDL/GLES in a disposable headless container; cartridge artwork supplied for documentation illustrations |
| Connection/diagnostic PNGs | The same UI, supplied with isolated example service responses; no live credentials or identifying device data |
| Gameplay/Gallery PNGs | Zelda, Metroid Fusion and Golden Sun run through the qualified mGBA core with a read-only source library and isolated saves/states; no ROMs, BIOS or save files are bundled |
| Setup GIF/MP4 | Native setup renders with scripted choices and condensed example progress; installation duration is not measured |
| Boot GIF/MP4 | Actual splash renderer and guide shelf, replaying captured framebuffer/GLES percentage changes and timestamps; reconstructed images, not camera footage |
| Feature-tour GIF/MP4 | A sequence of the captured shelf, real gameplay, settings, connection and Gallery screens |

The animations contain no audio, title cards or timing labels over the device UI. Their captions and this provenance explain how they were made. The 640×480 frames match the panel's pixel dimensions; they do not reproduce its optical brightness, reflections or camera exposure.

The GBA illustrations use **Perfect overlays + Shimmerless**. They therefore include Perfect artwork in the rendered screenshots; the original/adaptation ownership and [no-license-specified notice](../CREDITS.md) apply to these assets as well. Published illustrations do not include the underlying game or save files.

## Generate assets

Install Pillow in a host development environment. For MP4 output, provide an FFmpeg executable through `FFMPEG` or PATH. These are host documentation tools, not additional firmware dependencies.

```sh
python3 -m venv resources/wiki-tools
resources/wiki-tools/bin/pip install Pillow imageio-ffmpeg
```

Prepare the pinned source using the existing workflow; do not build the archived root prototype:

```sh
python3 scripts/rg353v-workflow.py prepare
```

Use the prepared **Slot** path printed by that command. Frontend captures use an ARM64 development container with Rust 1.96.1, SDL2, software GLES and Xvfb. Build it from the same checked-in Dockerfile as development; the script does not silently install system packages or modify the handheld. Production builds continue to use the ordinary build scripts.

```sh
docker build --platform linux/arm64 -t slot-rg353v-dev:rust-1.96.1 \
  -f ports/rg353v/Dockerfile ports/rg353v
```

Use `--container` if you gave that image another name. The private documentation tools/cache are not required by a clean clone; Pillow, the public Dockerfile, the pinned source and the checked-in capture scripts supply the inputs.

```sh
FFMPEG="$(resources/wiki-tools/bin/python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" \
  resources/wiki-tools/bin/python scripts/render-rg353v-wiki.py all \
    --source /absolute/path/to/prepared/slot-WORKSPACE \
    --library /absolute/path/to/private/content \
    --core /absolute/path/to/qualified/mgba_libretro.so
```

The `--library` folder is mounted read-only. The capture program requires the illustrated Zelda/Metroid/Golden Sun games and matching cartridge art, and the qualified ARM64 mGBA core; those private inputs are not part of a clean clone or image. A maintainer reproducing these particular screenshots must supply legally obtained copies. Only the selected progress snapshots are copied into the disposable root; all capture-session writes stay there.

The default compilation target and intermediate files live under ignored `resources/`. `--target` may point to an existing compatible target cache. The script temporarily places its own example in the prepared workspace and removes that exact file in `finally`; it refuses to overwrite an existing example. It never exports a prepared tree over the authoritative layer.

The boot command reads the sanitized [presentation trace](media/boot-timing.json). A temporary native renderer probe recorded percentage changes after framebuffer writes; a temporary GLES probe captured just the counter pixels before each swap and its return timestamp. Those pixels were matched against native renderer templates. Both probes were removed and the ordinary frontend restored afterward; user settings and save/state hashes were unchanged. Probing adds work, so this run is evidence of presentation behavior rather than a new performance benchmark.

The early 0% frame has its own timestamp. The second initramfs draw (31%) is bounded by its begin/end markers, about 37 ms apart; the replay uses the completion bound. The framebuffer-to-GLES ownership transition and physical panel scanout were not filmed. The trace includes the captured black GLES clear and the brief 100% handoff. It neither fills in unshown percentages nor rescales the run to a chosen duration. The GIF rounds absolute boundaries to 10 ms; its 100% interval is 30 ms. The MP4 uses 60 fps rather than 25 fps to retain the short handoff. The final 800 ms shelf hold is outside the measured boot interval. The boot validator checks the milestone plan and renderer hashes against the capture; changing those inputs requires reviewing or recapturing the trace.

Individual commands are `setup`, `frontend`, `boot`, `tour` and `manifest`. Run frontend before boot/tour because those sequences use its captures. Validate the guide and media after changing the asset list:

```sh
python3 scripts/check-rg353v-wiki.py
```

## Review before publication

The generated `media/manifest.json` records source pins, per-file hashes, sizes, dimensions and animation durations. It also records hashes of the capture scripts, documentation service fixtures, setup renderer/font and module catalog, so changes to those inputs cannot silently leave stale media. The checker verifies Markdown targets, image dimensions, GIF timing, module-help coverage and the manifest. Inspect the rendered images as well; a successful build does not establish readable text or correct navigation.

Do not copy private experiment captures directly into the guide. Check for passwords, SSIDs, keys, host fingerprints and device identifiers. The underlying games/art retain their owners' rights, and the screenshots do not grant redistribution rights to ROMs or BIOS. Use illustrative addresses. Retain clean-install, source-license and platform qualification notes; attractive screenshots do not replace those checks.

## Prepare the GitHub Wiki

After the publication gates are resolved, prepare a fresh local export using the reviewed source tag or commit:

```sh
python3 scripts/export-rg353v-wiki.py --ref v1.0.0 \
  --repository mriverodorta/slot-rg353v \
  --output release/wiki-v1.0.0
```

The tag above is an example, not an existing release. `main` can be used for a local preview. The export includes Home, the sidebar, footer and all guide pages; inline screenshots/GIFs point to the same source revision. It rejects missing local targets and video download links and never overwrites an existing export. Review that directory before copying its Markdown into the separate Wiki repository. The required third-party artwork ownership and no-license-specified notices remain applicable.
