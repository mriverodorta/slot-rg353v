# Source materials for Slot RG353V v0.1.0

To install Slot, download only the **[flashable image](https://github.com/mriverodorta/slot-rg353v/releases/tag/v0.1.0)**. These archives are for inspecting or rebuilding the software.

The device layer, patches and build scripts are available in the [immutable v0.1.0 source tag](https://github.com/mriverodorta/slot-rg353v/tree/v0.1.0). A normal Git clone/build fetches its pinned public inputs; you do not need these archives for that workflow. These separate materials preserve the matching prepared/upstream sources alongside the binary release.

The former overlapping 19.4 MiB and 1.09 GiB bundles have been replaced by the component downloads below. No image, kernel, emulator or game data changed.

| Component | Download | MiB |
| --- | --- | ---: |
| U-Boot source (shared by both configurations) | [Slot-RG353V-v0.1.0-bootloader-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-bootloader-sources.tar.xz) | 27.4 |
| ROCKNIX build recipes, configurations and notices | [Slot-RG353V-v0.1.0-build-and-notices-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-build-and-notices-sources.tar.xz) | 27.7 |
| Supporting build libraries | [Slot-RG353V-v0.1.0-build-libraries-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-build-libraries-sources.tar.xz) | 32.4 |
| Slot, cores and locked Rust dependencies | [Slot-RG353V-v0.1.0-frontend-and-cores-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-frontend-and-cores-sources.tar.xz) | 66.1 |
| GCC runtime library sources | [gcc-15.2.0.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/gcc-15.2.0.tar.xz) | 96.4 |
| Graphics and audio | [Slot-RG353V-v0.1.0-graphics-audio-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-graphics-audio-sources.tar.xz) | 9.4 |
| Static installer tools and dependencies | [Slot-RG353V-v0.1.0-installer-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-installer-sources.tar.xz) | 19.0 |
| Linux kernel | [linux-7.0.2.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/linux-7.0.2.tar.xz) | 149.9 |
| Networking and security | [Slot-RG353V-v0.1.0-network-security-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-network-security-sources.tar.xz) | 118.6 |
| System components | [Slot-RG353V-v0.1.0-system-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-system-sources.tar.xz) | 94.4 |
| System utilities | [Slot-RG353V-v0.1.0-utilities-sources.tar.xz](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/Slot-RG353V-v0.1.0-utilities-sources.tar.xz) | 37.5 |

**Total: 678.8 MiB**, supplied as independent downloads. Linux and GCC retain their original compressed bytes/checksums; the other groups are recompressed without changing their inner source archive bytes. Identical SDL/U-Boot inputs are included once, with aliases recorded.

[Source manifest](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/SOURCE-MANIFEST.json) · [Source checksums](https://github.com/mriverodorta/slot-rg353v/releases/download/v0.1.0-sources/SHA256SUMS)

## Extract and build

Extract the component `.tar.xz` with your archive application or `tar -xf FILE.tar.xz`. Group archives contain uncompressed `.tar` files: extract those inner files to access each source tree. The standalone Linux and GCC archives extract directly into their source trees. For example:

```sh
mkdir source-work
tar -xf Slot-RG353V-v0.1.0-frontend-and-cores-sources.tar.xz -C source-work
mkdir source-work/slot
tar -xf source-work/slot-source.tar -C source-work/slot
```

Use the tagged project build scripts and the configurations/patches in the build-and-notices archive. Its resolved kernel/U-Boot configurations and `source-selection.json` explain the exact release mapping. Cargo dependency sources and modified mGBA/gpSP sources are in frontend-and-cores. NSPR is included in NSS. Static installer SquashFS/glibc/LZ4 sources are separate from the device runtime libraries.

Removed standalone programs and unrelated graphics stacks are not copied into this set. Small library inputs are retained conservatively where static linkage or build headers may matter; absence of a standalone file alone is not treated as proof that its source can be omitted. Original URLs/hashes remain recorded, including build-only downloads used by the full ROCKNIX workflow. A completely offline OS/toolchain build is not claimed.

## Licenses and provenance

All components retain their own licenses and notices. Original ROCKNIX software/scripts are GPLv2; other packages keep their individual terms. The build-and-notices archive contains the original notices, including Arm, Realtek and Rockchip firmware terms and the Mali wrapper source. Proprietary binary-only inputs retain their original URL/hash bindings; no unavailable proprietary source is presented as open source. Perfect artwork retains creator/adaptation copyright and its explicit no-license-specified notices. See [current credits](https://github.com/mriverodorta/slot-rg353v/blob/main/CREDITS.md).

The matching image SHA-256 is `a35e7e1fd9da4ca93f4aa93f8c833b598778b0b28e04ad8a66eafae7e27a3b6d`. `SOURCE-MANIFEST.json` binds every download and its preserved inner members, source inputs/aliases and the previous export hashes. All retained selected inputs and all inner archive hashes were verified before replacement; personal provisioning tokens were checked separately.

Sources are linked from the image release for equivalent access. They are separate from the OTA channel and do not need to be installed on the handheld.
