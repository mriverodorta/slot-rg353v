# Building an RG353V image

## Source of truth

This is a device-layer repository. `ports/rg353v/upstreams.lock.json` pins official Slot and ROCKNIX commits plus the device-layer hash. `ports/rg353v/layer/patches/slot.patch` and `layer/files/` contain the current frontend/core adaptations. The prepared tree is compiled; the old bring-up prototype is archived in ignored resources. ROCKNIX packages and hardware policies under `ports/rg353v/` supply the OS changes.

Public builds have no dependency on this owner's device, game library, Wi-Fi profiles, SSH identity, or experiment directory. Host caches and outputs go under ignored `resources/`, `localdev/` and `release/`.

## Requirements and limits

The current complete image pipeline targets an **ARM64 Linux Docker engine** (native ARM64 Linux or Docker Desktop on Apple Silicon). The older ROCKNIX stage has an x86 builder, but the custom loader/static-installer pipeline is not yet qualified end-to-end on x86/Windows. On those hosts, use an ARM64 builder or the eventual published image; do not assume the full script has been validated there.

Install Git, Python 3.11+, Bash, a C compiler, Docker and OpenSSL 3 or newer on PATH. Rust and Linux-only checks use the pinned development container. CMake is needed by host core tests. On Linux, image composition uses a privileged Docker container for loop-device filesystem operations. Docker Desktop provides a Linux VM on macOS.

Allow substantial free disk space for toolchains/download caches and adequate Docker memory. The first build can take hours. A prior 8 GB build exhausted memory in LLVM; the development Mac used a 24 GB Docker memory allocation. These are observations, not minimum resource guarantees. `RG353V_BUILD_JOBS` and `RG353V_BUILD_LOAD` control OS build concurrency.

## Public build

```sh
python3 scripts/build-image.py release --version local-1 --plan
bash scripts/build-release.sh --version local-1
```

The version identifies a fresh output directory. Existing images are never overwritten. The workflow:

1. Verifies the checked-in layer digest and prepares exact upstream commits in `resources/build/`.
2. Runs the Slot checks, compiles the ARM64 frontend and pinned patched cores, and stages the ROCKNIX packages.
3. Builds the RK3566 factory firmware using preserved Linux Docker build volumes.
4. Builds the custom F-recovery/SD-clock loader and static SquashFS installer tools from those build outputs.
5. Derives optional package ownership from the actual ROCKNIX `install_pkg` trees, resolves ELF dependencies and constructs the modular kit.
6. Composes the small first-boot SD image with public provisioning disabled, then compresses it.
7. Writes the `.img.gz`, layout report, `SHA256SUMS` and build record under `release/local-1/`.

`--plan` validates configuration only. It does not establish that compilation or hardware installation passes. The complete wrapper passed a clean-clone source build on 23 October 2026 with ARM64 Docker and Python 3.12. Each changed candidate still needs its own build and installation checks. A successful output is labelled a **candidate**, not automatically published or physically qualified.

The custom loader must match `ports/rg353v/image/installer-loader.json`. The pinned U-Boot recipes freeze compiler and FIT build timestamps separately, reproducing the qualified Generic and custom F-recovery loader hashes without changing their hardware configuration. The FIT timestamp update preserves external payload layout and hashes; an unexpected rebuilt loader still stops the build. A different compiler/build result may require a reviewed reproducibility update and new hardware qualification; do not bypass that identity check.

New installations reserve 512 MiB each for boot and Linux storage. When changing the payload, qualify the **installation workspace and OTA staging**, not just the final compressed file. `scripts/test-rg353v-partition-space.py` composes Minimal, Recommended and full selections using disposable 512 MiB ext4/FAT filesystems, reconstructs actual full/delta OS packages, and checks three compressed payload sets on FAT. It requires a public module kit, the matching public starter via `--installer-image`, qualified base/target/delta capsules, and explicit `SLOT_PARTITION_SPACE_TEST=1` inside a privileged disposable Linux container. It accepts no physical-device argument. The complete starter boot tree supplies the recovery-backup budget, including loader and setup files. Compressed setup output goes directly to boot; `--baseline-system-output` measures the former ext4-output workflow for comparison only. Retain its JSON report with the candidate's validation records.

The clean-image, setup and module-install tests also have opt-in Linux loop-device integration modes. Use those to exercise interrupted partitioning/publication and retry before physical qualification. Legacy schema-1 installation receipts must retain their original recorded geometry; only new explicit schema-2 clean-install plans select the 512 MiB boot / 512 MiB Linux-storage layout.

## Compose from already qualified inputs

To reuse a known factory image, loader and module kit without rebuilding the OS:

```sh
python3 scripts/build-image.py release --version candidate-1 \
  --firmware /absolute/path/factory.img.gz \
  --loader /absolute/path/rg353v-bootstage.bin \
  --module-kit /absolute/path/public-module-kit
```

All three inputs are required together. A factory image here is the two-partition ROCKNIX build product, **not** an installed personal card dump. The current module kit must include the intended frontend, helpers, cores and matching kernel modules. This path does not update a stale input automatically.

The 23 October 2026 clean-clone qualification completed the public source-build wrapper on an ARM64 Docker engine with Python 3.12. Its `rc-20261023-build1` image is 133,687,073 compressed bytes (127.5 MiB), accompanied by its matching Slot source archive and checksums. The image and its four actual-payload preset compositions passed host inspection; this does not substitute for physical installation testing.

## Release source materials

Binary releases provide a separate corresponding-source bundle, alongside the flash image and checksums. It contains the device-layer project, the matching prepared Slot source, patched mGBA source and gpSP source/patches, Cargo dependency sources, modified ROCKNIX recipes and resolved kernel/U-Boot configurations, and the cached open-source OS package inputs. A manifest records input URLs and SHA-256 hashes. NSPR is supplied inside the NSS archive; inline and virtual packages are covered by the ROCKNIX recipes. Generic and Specific U-Boot sources are included explicitly.

The source bundle also retains third-party notices, the Mali wrapper source, and the original Arm, Realtek and Rockchip binary-firmware terms. Proprietary driver/firmware source that upstream does not provide cannot be supplied as open source; the exact public binary input hashes and URLs are recorded instead. Their terms remain separate from Slot's GPL. Downloading the source materials is unnecessary when simply flashing the image.

## Locks, caching and reproducibility

Normal builds do not use `--update`. A release tag and a development branch are different eligibility policies. ROCKNIX remains pinned to released `20261001`. The current mGBA pin is development-derived and device-tested; see Credits for precise provenance.

Generated Python bytecode caches are excluded from prepared-tree tracking and source packaging; checks suppress cache writes. Real source changes still invalidate preparation.

The layer hash detects content changes but does not identify the top-level documentation or new release tooling, so record the final repository commit in release metadata too. UUIDs and some filesystem/archive timestamps are generated during composition; these images are not claimed to be byte-for-byte reproducible. “Build from source” means documented inputs and processes, with recorded outputs.

Cargo intermediates stay on Linux Docker volumes, isolated per prepared checkout. Only the finished frontend executable is copied to the host for packaging. Host and RG353V feature graphs use separate absolute Linux target paths, avoiding the shared host symlink namespace. Old host target directories are preserved. Rust tests run serially inside each test process for reliable process/environment and temporary-command tests; compilation remains parallel.

Never delete ROCKNIX source/download/build caches or Docker volumes during ordinary cleanup. The local migration leaves ignored compatibility links for older recipes; a fresh clone needs no such links.

## RG353V payload policy

Normal lean builds run the reviewed appliance trim after all OS packages are installed, before optional-module splitting. `configure-appliance.py` and `config/appliance-prune.json` check exact payload hashes and the retained ELF dependency graph. Changed upstream files require review rather than silently matching a broad deletion pattern. The policy preserves source/license notices and the working graphics libraries. Loader files needed by ROCKNIX’s factory-image writer are preserved in a layer-specific build-cache directory before their runtime copies are removed; the later release stage reads that cache, not the trimmed OS tree. OS capsules likewise take device trees and overlays from the matching firmware archive's `3rdparty/bootloader` directory when SYSTEM no longer contains those build inputs.

The board hardware database contains only the RG353V built-in input rules. One compiled database replaces the former factory/no-overrides pair and broad vendor tables. Persistent user calibration overrides are still compiled and cached when changed. This does not remove the kernel drivers or udev's built-in device detection.

The image omits locale-generation sources, Python package-bootstrap/demo files, unrelated loader copies, Btrfs commands, unused desktop/build data and disconnected distribution helpers. It retains UTF-8 handling and a small Unicode/Latin conversion set. Identical SDL variants share one physical file. Slot's fonts are embedded and setup uses bundled glyph data, so neither requires the removed external Liberation fonts or legacy SDL notifier.

These payload changes need clean-install and hardware qualification for their exact candidate. Smaller GPU variants and alternate file-sharing backends remain separate experiments until their graphics, storage, compatibility and lifecycle checks pass.

The current replacement work selects ksmbd-tools 3.5.7 and builds the matching Linux SMB server as an optional module. Both baseline and slim kernel configurations include this shared module capability; the baseline otherwise restores its upstream hardware configuration. The File Sharing module owns the helper, service and server modules; omitting it must omit that payload. The server starts only with a session grant, after content storage is mounted, and is stopped before USB Storage takes ownership. Guest sharing requires no imported Samba password database. The existing `samba.enabled` compatibility key is retained for older settings; it does not imply that the Samba binaries remain installed.

`configure-ksmbd.py` removes only reviewed legacy Samba files after the new backend is present and the retained ELF dependency graph passes. An unexpected file or changed hash stops the migration before deletion. Physical eMMC transfers, supported computer clients and service/suspend lifecycle checks remain qualification requirements; a successful build or loopback transfer alone is insufficient. The GLES-only Mali package passed equal-condition frame pacing and game suspend/wake checks on the owner's eMMC. Its raw userspace library is about 22.4 MiB instead of 57.1 MiB; it retains the EGL/GLES/GBM interfaces used by Slot. A fresh distributable image still requires clean-install qualification.

The kernel recipe also carries the [NCM transmit-timer retry fix](https://lore.kernel.org/r/20260817192638.437798-1-cosmin-gabriel.tanislav.xa@renesas.com) independently of the slimming profile. In our USB tests, the unfixed timer could leave the final packets queued when transmit requests were busy, stalling SMB and SSH. ECM compatibility mode avoided the stall. The fix retries the pending flush after the normal timer interval; it adds no boot-time service. Record its local patch and qualification evidence rather than claiming that the entire kernel was upgraded to a newer upstream release.

The additional r14 payload candidate removes orphaned GnuTLS dependencies only after the Samba-to-ksmbd migration. Exact-hash policy also covers standalone development/build tools, leftover Avahi/gettext/XCB data, unused firmware, selected Python packages and old XML/font/archive libraries. The obsolete EmulationStation controller-layout command and its exact profile helper are removed together; native RG353V input does not use them. CA preparation, OpenSSL, NSS/SQLite, UTF-8 handling, radio firmware, recovery tools and license notices remain. The matching Slot source archive is retained as a separate build/release asset rather than installed in SYSTEM. The owner eMMC regression passed the retained imports/ELF checks, real module compositions, HTTPS/network/SSH, actual-eMMC SMB and USB storage, eight game/overlay combinations, three deep-sleep cycles and three controlled restarts. These results do not replace fresh-installer or physical Windows qualification.

The r15 accessory-tool trim removes standalone ALSA MIDI/administration utilities, jq with its otherwise-unused Oniguruma library, the ZIP command-line tools with libzip, and the already-disabled RPC utilities. This does not remove native speaker/headphone routing, ALSA playback/mixer APIs, Python JSON/ZIP/tar APIs or optional user-facing features. Each group passed staged target imports, helper checks and retained ELF closure before entering the exact-hash policy. The owner eMMC candidate passed 140 source/module tests, eight silent game/overlay combinations, HTTPS/update validation, the full-library SMB round trip on real exFAT storage, USB mass storage, attached-USB deep sleep and three controlled restarts. SYSTEM shrank by 920 KiB compressed; the 4.697-second mean kernel-to-shelf time is effectively unchanged. This does not replace fresh-installer, physical Windows or listening checks. mDNS, ethtool and specialized systemd tools remain outside this pass. The separate legacy-script review is not included in r15.


The later 23 October builds include automatic SD reinsertion discovery and the fading shelf scan message. The corrected build-3 public candidate passed host extraction, payload/privacy checks and all four preset compositions; its matching development build also passed device component/OS update tests. Subsequent frontend startup changes overlap primary storage scanning and artwork preparation with graphics initialization. A fresh public image containing these refinements is being qualified separately; earlier device results do not establish a clean-install pass for that image.
