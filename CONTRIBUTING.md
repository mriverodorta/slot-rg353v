# Contributing

Read [the architecture and build guide](wiki/Building.md) before changing the frontend. The earlier prototype is archived in ignored resources; the release source is prepared from the pinned upstream plus `ports/rg353v/layer/`. Do not accidentally export the prototype over the current layer.

1. Prepare the pinned sources with `python3 scripts/rg353v-workflow.py prepare --work-dir resources/build`.
2. Work in the printed prepared Slot checkout. Preserve local work before regenerating it; preparation refuses edited checkouts.
3. Export the intentional tracked diff and new files into `ports/rg353v/layer/patches/slot.patch` and `layer/files/`. Refresh the layer hash in the lock files without changing upstream commits. The new layer must prepare cleanly from the pinned upstream.
4. Run the relevant tests. Keep hardware tests silent, isolate save/state output, and back up real content before and after tests. Never change the installed eMMC system without its owner's authorization.
5. Describe the user-visible change, validation performed, hardware tested and any remaining limitations in the pull request.

Changes to an installer choice must agree across the module catalog, installation dependency checks, runtime menu visibility, service gating and documentation. Hardware/kernel changes need boot and suspend/resume qualification; a successful compile is insufficient.

Never commit ROMs, BIOS files, personal saves, network profiles, passwords, SSH identities, machine-specific logs, build caches or generated disk images. `resources/`, `localdev/` and `release/` are ignored. Do not force-add them. Report bugs in this project's issue tracker once its repository is published; do not send fork-specific failures to upstream without reproducing them there.

Include upstream attribution and license notices for code and artwork. See [CREDITS.md](CREDITS.md); Perfect's creators retain copyright and no explicit license was found; retain the owner's required attribution/no-license-specified notice.
