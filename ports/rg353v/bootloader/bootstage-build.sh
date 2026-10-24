#!/usr/bin/env bash
set -euo pipefail
baseline=/baseline/rocknix/build.ROCKNIX-RK3566.aarch64
build=/work/rocknix/build.ROCKNIX-RK3566.aarch64
original="$baseline/build/u-boot-Generic-v2026.01"
expected=ebbe69e8ebbbf4809eb8046c1a989ffc408dc825d332d2d01e6e7fcf51780854
[[ $(sha256sum "$original/uboot.bin" | cut -d ' ' -f 1) == "$expected" ]] || { echo 'Baseline loader differs from the device-qualified build.' >&2; exit 1; }
[[ ! -e /work/.bootstage-building ]] || { echo 'A bootstage build is already running.' >&2; exit 1; }
mkdir /work/.bootstage-building
trap 'rmdir /work/.bootstage-building' EXIT
mkdir -p "$build/build"
ln -sfn "$baseline/toolchain" "$build/toolchain"
PKG_BUILD="$build/build/u-boot-Generic-v2026.01"
mkdir -p "$PKG_BUILD"
rsync -a --delete "$original/" "$PKG_BUILD/"
cp "$original/.config" /output/baseline.config
cd "$PKG_BUILD"
./scripts/config --set-val BOOTDELAY 0 --enable BOOTSTAGE --enable SPL_BOOTSTAGE \
  --enable BOOTSTAGE_FDT --enable BOOTSTAGE_STASH --disable BOOTSTAGE_REPORT \
  --set-val BOOTSTAGE_RECORD_COUNT 256 --set-val SPL_BOOTSTAGE_RECORD_COUNT 64 \
  --set-val BOOTSTAGE_STASH_ADDR 0x01800000 --set-val BOOTSTAGE_STASH_SIZE 0x4000 \
  --set-val SYS_FDT_PAD 0x10000
probe_args=()
if [[ ${SLOT_BOOTSTAGE_SD_PROBE:-0} == 1 ]]; then probe_args+=(--sd-probe); fi
if [[ ${SLOT_BOOTSTAGE_SD_CLOCK_FIX:-0} == 1 ]]; then probe_args+=(--sd-clock-fix); fi
if [[ ${SLOT_BOOTSTAGE_EMMC_SELECT:-0} == 1 ]]; then probe_args+=(--emmc-select); fi
python3 /recipe/instrument-bootstage.py "$PKG_BUILD" "${probe_args[@]}" > /output/instrumented-files.txt
TOOLCHAIN="$build/toolchain"
export ARCH=arm64 CROSS_COMPILE="$TOOLCHAIN/bin/aarch64-rocknix-linux-gnu-"
export PATH="$TOOLCHAIN/bin:$PATH"
export _python_sysroot="$TOOLCHAIN" _python_prefix=/ _python_exec_prefix=/
# Reproduce the timestamp metadata of the qualified F-recovery loader.
export SOURCE_DATE_EPOCH=1792207994
export PYTHONDONTWRITEBYTECODE=1
host_flags="-Wl,-rpath,$TOOLCHAIN/lib -L$TOOLCHAIN/lib"
make HOSTCC=gcc HOSTCFLAGS="-I$TOOLCHAIN/include" HOSTLDFLAGS="$host_flags" olddefconfig
python3 - <<'PY'
from pathlib import Path
import json

def config(path):
 return {line.split('=',1)[0]:line.split('=',1)[1] for line in Path(path).read_text().splitlines() if line.startswith('CONFIG_')}
base=config('/output/baseline.config');current=config('.config')
diff={key:{'before':base.get(key),'after':current.get(key)} for key in base.keys()|current.keys() if base.get(key)!=current.get(key)}
assert all('BOOTSTAGE' in key or key in ('CONFIG_BOOTDELAY','CONFIG_SYS_FDT_PAD') for key in diff),diff
assert current['CONFIG_BOOTDELAY']=='0' and current['CONFIG_BOOTCOMMAND']==base['CONFIG_BOOTCOMMAND']
for key in ['BOOTSTAGE','SPL_BOOTSTAGE','BOOTSTAGE_FDT','BOOTSTAGE_STASH']:assert current['CONFIG_'+key]=='y'
assert current.get('CONFIG_BOOTSTAGE_REPORT') is None
Path('/output/config-delta.json').write_text(json.dumps(diff,indent=2)+'\n')
PY
PKG_RKBIN="$baseline/build/rkbin-74213af1e952c4683d2e35952507133b61394862"
PKG_BL31="$PKG_RKBIN/bin/rk35/rk3568_bl31_v1.45.elf"
PKG_DDR_BIN="$PKG_RKBIN/bin/rk35/rk3568_ddr_1056MHz_v1.23.bin"
PKG_MINILOADER=spl/u-boot-spl.bin
make -j2 HOSTCC=gcc HOSTCFLAGS="-I$TOOLCHAIN/include" HOSTLDFLAGS="$host_flags" u-boot.dtb u-boot.img tools
make -j2 BL31="$PKG_BL31" ROCKCHIP_TPL="$PKG_DDR_BIN" HOSTCC=gcc HOSTCFLAGS="-I$TOOLCHAIN/include" HOSTLDFLAGS="$host_flags" HOSTSTRIP=true CONFIG_MKIMAGE_DTC_PATH=scripts/dtc/dtc
python3 /fit-metadata.py --fit u-boot.itb --epoch 1792207999
rm -f uboot.bin idbloader.img
DEVICE=RK3566
source /baseline/rocknix/projects/ROCKNIX/bootloader/rkhelper
cp uboot.bin /output/rg353v-bootstage.bin
cp .config /output/candidate.config
./tools/dumpimage -l u-boot.itb > /output/candidate-fit.txt
./tools/dumpimage -l "$original/u-boot.itb" > /output/baseline-fit.txt
export PKG_RKBIN PKG_DDR_BIN PKG_BL31 PKG_BUILD
python3 - <<'PY'
from pathlib import Path
import hashlib,json,os
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
baseline=Path('/baseline/rocknix/build.ROCKNIX-RK3566.aarch64/build/u-boot-Generic-v2026.01')
candidate=Path('/output/rg353v-bootstage.bin')
assert 0 < candidate.stat().st_size < 16777216 - 32768
for name in ['dts/upstream/src/arm64/rockchip/rk3566-anbernic-rg353p.dts','dts/upstream/src/arm64/rockchip/rk3566-anbernic-rg353v.dts']:
 assert sha(Path(name))==sha(baseline/name)
manifest={'schema':1,'status':'experimental; not device-tested or installed','target':'rg353v-panel-v2','rocknix_commit':'c445081a59518f37d9776e5412dd7b14910696f7','u_boot_version':'v2026.01','change':'BOOTSTAGE and SPL timing, FDT export, named markers; preserves installed BOOTDELAY=0 and boot command','baseline_sha256':sha(baseline/'uboot.bin'),'candidate_sha256':sha(candidate),'bytes':candidate.stat().st_size,'sd_offset_bytes':32768,'ddr_firmware_sha256':sha(Path(os.environ['PKG_DDR_BIN'])),'bl31_firmware_sha256':sha(Path(os.environ['PKG_BL31'])),'baseline_config_sha256':sha(Path('/output/baseline.config')),'candidate_config_sha256':sha(Path('/output/candidate.config'))}
manifest['config_delta']=json.loads(Path('/output/config-delta.json').read_text())
manifest['instrumented_files']=Path('/output/instrumented-files.txt').read_text().splitlines()
manifest['sd_probe']=os.environ.get('SLOT_BOOTSTAGE_SD_PROBE')=='1'
manifest['sd_clock_fix']=os.environ.get('SLOT_BOOTSTAGE_SD_CLOCK_FIX')=='1'
manifest['emmc_select']=os.environ.get('SLOT_BOOTSTAGE_EMMC_SELECT')=='1'
if manifest['emmc_select']:
 manifest['change']='BOOTSTAGE, SD clock quirk, SPL same-device chain; RG353V eMMC-first boot with F-held TF1 override and fallback'
manifest['stash_region']={'start':0x01800000,'bytes':0x4000,'note':'Above U-Boot/FIT/script buffers; below kernel_addr_r 0x02000000; used only for SPL-to-U-Boot records and final stash.'}
Path('/output/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
PY
chown -R "$OUTPUT_UID:$OUTPUT_GID" /output
