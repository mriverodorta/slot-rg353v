# RG353V source and image workflow

See [Building](../../wiki/Building.md) for the complete image pipeline and [Development](../../wiki/Development.md) for private provisioning.

```sh
# Exact locked sources; does not advance upstream pins.
python3 scripts/rg353v-workflow.py prepare --work-dir resources/build

# Public or private complete image (a fresh version directory is required).
bash scripts/build-release.sh --version candidate-1
bash scripts/build-localdev.sh --version dev-1
```

The low-level workflow also exposes `check`, `build`, `firmware`, `image` and component-update operations. For the current modular installer use the top-level `build-image.py` wrapper. The low-level legacy image command is not the release entry point.

Do not use `--update` for reproducing a release. Upstream updates must be reviewed against the current patch and tested; the current ROCKNIX stable source and mGBA development-derived pin are stated in [Credits](../../CREDITS.md). Never run the legacy root `export-layer` over the current layer: it would snapshot the older prototype.

Actual image qualification and retention requirements are in [Releasing](../../wiki/Releasing.md). The ignored historical experiments retain their compatibility links, build caches, recovery backups and evidence. They are not dependencies of a clean source build.
