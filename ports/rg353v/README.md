# RG353V device layer

The current user guide is [the wiki](../../wiki/Home.md); the image build entry point is [Building](../../wiki/Building.md). This replaces the older bring-up notes that referred to a 2025 card and untested hardware features.

The release frontend comes from the pinned official Slot checkout plus `layer/patches/slot.patch` and `layer/files/`. The older Rust prototype is archived in ignored resources. The build workflow prepares separate sources and refuses an edited/generated checkout rather than silently resetting it.

- `upstreams*.lock.json`: exact source commits, build profiles and layer digest.
- `image/`: first-boot UI, SD/eMMC setup, modular installation and installer assets.
- `modules/catalog-v1.json`: installable capabilities and file/package ownership.
- `rocknix/`: packages, runtime helpers, systemd units and startup policies.
- `bootloader/`: measured loader modifications, SD-clock fix and eMMC/F selection.
- `layer/`: frontend patch and new files, including mirrored public build inputs.

Build resources belong under ignored `resources/`. Personal provisioning belongs under ignored `localdev/`. Public candidate images belong under ignored `release/`. No real library or credential is a public build dependency. See [Credits](../../CREDITS.md) and [Contributing](../../CONTRIBUTING.md).
