#!/usr/bin/env bash
set -euo pipefail
baseline=/baseline/rocknix/build.ROCKNIX-RK3566.aarch64
build=/work/rocknix/build.ROCKNIX-RK3566.aarch64
original="$baseline/build/u-boot-Generic-v2026.01"
expected=ebbe69e8ebbbf4809eb8046c1a989ffc408dc825d332d2d01e6e7fcf51780854
[[ $(sha256sum "$original/uboot.bin" | cut -d ' ' -f 1) == "$expected" ]] || { echo 'Baseline loader differs from the device-qualified build.' >&2; exit 1; }
[[ ! -e /work/.fastboot-building ]] || { echo 'A fastboot build is already running.' >&2; exit 1; }
mkdir /work/.fastboot-building
trap 'rmdir /work/.fastboot-building' EXIT
mkdir -p "$build/build"
ln -sfn "$baseline/toolchain" "$build/toolchain"
PKG_BUILD="$build/build/u-boot-Generic-v2026.01"
mkdir -p "$PKG_BUILD"
rsync -a --delete "$original/" "$PKG_BUILD/"
cp "$original/.config" /output/baseline.config
cd "$PKG_BUILD"
python3 - <<'PY'
from pathlib import Path
p=Path('.config');text=p.read_text()
assert text.count('CONFIG_BOOTDELAY=2\n')==1
assert 'CONFIG_ENV_IS_NOWHERE=y\n' in text
assert 'CONFIG_BOOTCOMMAND="bootflow scan -lb"\n' in text
p.write_text(text.replace('CONFIG_BOOTDELAY=2\n','CONFIG_BOOTDELAY=0\n'))
PY
TOOLCHAIN="$build/toolchain"
export ARCH=arm64 CROSS_COMPILE="$TOOLCHAIN/bin/aarch64-rocknix-linux-gnu-"
export PATH="$TOOLCHAIN/bin:$PATH"
export _python_sysroot="$TOOLCHAIN" _python_prefix=/ _python_exec_prefix=/
export PYTHONDONTWRITEBYTECODE=1
host_flags="-Wl,-rpath,$TOOLCHAIN/lib -L$TOOLCHAIN/lib"
make HOSTCC=gcc HOSTCFLAGS="-I$TOOLCHAIN/include" HOSTLDFLAGS="$host_flags" olddefconfig
python3 - <<'PY'
from pathlib import Path
expected=Path('/output/baseline.config').read_text().replace('CONFIG_BOOTDELAY=2\n','CONFIG_BOOTDELAY=0\n')
assert Path('.config').read_text()==expected,'Unexpected configuration changes'
PY
PKG_RKBIN="$baseline/build/rkbin-74213af1e952c4683d2e35952507133b61394862"
PKG_BL31="$PKG_RKBIN/bin/rk35/rk3568_bl31_v1.45.elf"
PKG_DDR_BIN="$PKG_RKBIN/bin/rk35/rk3568_ddr_1056MHz_v1.23.bin"
PKG_MINILOADER=spl/u-boot-spl.bin
make -j2 HOSTCC=gcc HOSTCFLAGS="-I$TOOLCHAIN/include" HOSTLDFLAGS="$host_flags" u-boot.dtb u-boot.img tools
make -j2 BL31="$PKG_BL31" ROCKCHIP_TPL="$PKG_DDR_BIN" HOSTCC=gcc HOSTCFLAGS="-I$TOOLCHAIN/include" HOSTLDFLAGS="$host_flags" HOSTSTRIP=true CONFIG_MKIMAGE_DTC_PATH=scripts/dtc/dtc
rm -f uboot.bin idbloader.img
DEVICE=RK3566
source /baseline/rocknix/projects/ROCKNIX/bootloader/rkhelper
cp uboot.bin /output/rg353v-bootdelay0.bin
cp .config /output/candidate.config
./tools/dumpimage -l u-boot.itb > /output/candidate-fit.txt
./tools/dumpimage -l "$original/u-boot.itb" > /output/baseline-fit.txt
export PKG_RKBIN PKG_DDR_BIN PKG_BL31 PKG_BUILD
python3 - <<'PY'
from pathlib import Path
import hashlib,json,os
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
baseline=Path('/baseline/rocknix/build.ROCKNIX-RK3566.aarch64/build/u-boot-Generic-v2026.01')
candidate=Path('/output/rg353v-bootdelay0.bin')
assert candidate.stat().st_size==baseline.joinpath('uboot.bin').stat().st_size
for name in ['dts/upstream/src/arm64/rockchip/rk3566-anbernic-rg353p.dts','dts/upstream/src/arm64/rockchip/rk3566-anbernic-rg353v.dts','board/anbernic/rgxx3_rk3566/rgxx3-rk3566.c']:
 assert sha(Path(name))==sha(baseline/name)
manifest={'schema':1,'status':'experimental; not device-tested or installed','target':'rg353v-panel-v2','rocknix_commit':'c445081a59518f37d9776e5412dd7b14910696f7','u_boot_version':'v2026.01','change':'CONFIG_BOOTDELAY=2 to CONFIG_BOOTDELAY=0; all other configuration and source unchanged','baseline_sha256':sha(baseline/'uboot.bin'),'candidate_sha256':sha(candidate),'bytes':candidate.stat().st_size,'sd_offset_bytes':32768,'ddr_firmware_sha256':sha(Path(os.environ['PKG_DDR_BIN'])),'bl31_firmware_sha256':sha(Path(os.environ['PKG_BL31'])),'baseline_config_sha256':sha(Path('/output/baseline.config')),'candidate_config_sha256':sha(Path('/output/candidate.config'))}
Path('/output/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
PY
chown -R "$OUTPUT_UID:$OUTPUT_GID" /output
