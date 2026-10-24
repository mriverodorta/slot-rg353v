#!/usr/bin/env python3
"""Stage reversible, opt-in RG353V package overrides from pinned official recipes."""
import argparse
import hashlib
import json
from pathlib import Path
import re

PROFILE = 'rg353v-lean-v1'
MARKER = '# Generated RG353V userspace override;'
IMAGE_MARKER = '# Generated RG353V random-access image policy;'


def filter_deps(names):
    if not names or any(not re.fullmatch(r'[A-Za-z0-9_+.-]+', n) for n in names):
        raise ValueError('Invalid package dependency filter')
    return ('\nslot_deps=""\nfor dependency in ${PKG_DEPENDS_TARGET}; do\n'
            '  case "$dependency" in\n    ' + '|'.join(names) + ') ;;\n'
            '    *) slot_deps+=" $dependency" ;;\n  esac\ndone\n'
            'PKG_DEPENDS_TARGET="${slot_deps}"\nunset slot_deps dependency\n')


def stage_mali(sources, policy, profile):
    """Select the same pinned GLES binary family without OpenCL/Vulkan payload."""
    variant = policy.get('mali_variant', 'bifrost-g52-g29p1-full')
    if variant not in ('bifrost-g52-g29p1-full', 'bifrost-g52-g29p1-gles'):
        raise ValueError('Unknown Mali binary variant')
    recipe = sources / 'libmali/package.mk'
    original = recipe.read_text().split('\n' + MARKER, 1)[0]
    if hashlib.sha256(original.encode()).hexdigest() != policy['source_sha256']['libmali']:
        raise ValueError('Review changed upstream recipe: libmali')
    hooks = re.findall(r'^post_makeinstall_target\(\) \{\n.*?^\}', original, re.M | re.S)
    move = 'mv "${INSTALL}"/usr/lib/mali/libMaliVulkan.* "${INSTALL}"/usr/lib/'
    if len(hooks) != 1 or hooks[0].count(move) != 1:
        raise ValueError('Review changed Mali installation contract')
    if profile and variant == 'bifrost-g52-g29p1-gles':
        # The unpack hook evaluates PLATFORM when called. Meson's final option
        # overrides the earlier default while preserving the exact upstream text.
        hook = hooks[0].replace(move, 'if compgen -G "${INSTALL}/usr/lib/mali/libMaliVulkan.*" > /dev/null; then ' + move + '; fi')
        recipe.write_text(original + '\n' + MARKER + '\nPLATFORM="-gles"\n'
                          'PKG_MESON_OPTS_TARGET+=" -Dplatform=gles"\n' +
                          filter_deps(['vulkan-tools', 'vulkan-wsi-layer']) + '\n' + hook + '\n')
    else:
        recipe.write_text(original)


def stage(tree, policy_path, profile=None):
    if profile not in (None, PROFILE):
        raise ValueError('Unknown userspace profile')
    policy = json.loads(policy_path.read_text())
    if policy['schema'] != 1 or policy['id'] != PROFILE:
        raise ValueError('Unsupported userspace policy')
    # Small random reads into the large Mali library otherwise decompress whole
    # 1 MiB blocks. Use the measured low-latency LZ4 codec and 64 KiB blocks.
    # The baseline profile restores the exact upstream options prefix.
    options = tree/'projects/ROCKNIX/options'
    original_options = options.read_text().split('\n'+IMAGE_MARKER, 1)[0]
    if (not re.search(r'^\s*SQUASHFS_COMPRESSION="zstd"\s*$', original_options, re.M)
            or re.search(r'^\s*SQUASHFS_COMPRESSION_OPTION=', original_options, re.M)):
        raise ValueError('Review changed upstream SquashFS options')
    image_policy = policy['squashfs']
    if image_policy != {'compression': 'lz4', 'high_compression': True, 'block_bytes': 65536}:
        raise ValueError('Unsupported random-access image policy')
    options.write_text(original_options + (
        '\n'+IMAGE_MARKER+'\n'
        'if [ "${BASE_ONLY:-}" = true ] && [ "${DEVICE:-}" = RK3566 ] '
        '&& [ "${ARCH:-}" = aarch64 ]; then\n'
        '  SQUASHFS_COMPRESSION="lz4"\n'
        '  SQUASHFS_COMPRESSION_OPTION="-Xhc -b 65536"\nfi\n'
        if profile else ''))
    # The target reader/kernel already support LZ4. Enable that codec in the
    # official host image writer too; baseline staging restores its recipe.
    writer = tree/'projects/ROCKNIX/packages/sysutils/squashfs-tools/package.mk'
    writer_text = writer.read_text().split('\n'+MARKER, 1)[0]
    if hashlib.sha256(writer_text.encode()).hexdigest() != policy['source_sha256']['squashfs-tools']:
        raise ValueError('Review changed upstream recipe: squashfs-tools')
    host = re.findall(r'^make_host\(\) \{\n.*?^\}', writer_text, re.M|re.S)
    if len(host) != 1 or host[0].count('LZ4_SUPPORT=0') != 1:
        raise ValueError('Review changed host SquashFS codec contract')
    writer.write_text(writer_text + ('\n'+MARKER+'\n'
        'PKG_DEPENDS_HOST+=" lz4:host"\n'
        'PKG_NEED_UNPACK+=" $(get_pkg_directory lz4)"\n'
        +host[0].replace('LZ4_SUPPORT=0', 'LZ4_SUPPORT=1')+'\n' if profile else ''))
    device = tree/'projects/ROCKNIX/devices/RK3566/packages'
    sources = tree/'projects/ROCKNIX/packages/graphics'
    stage_mali(sources, policy, profile)
    originals = {}
    for name in ('SDL2', 'SDL2_glesonly'):
        source = sources/name
        text = (source/'package.mk').read_text().split('\n'+MARKER,1)[0]
        if hashlib.sha256(text.encode()).hexdigest() != policy['source_sha256'][name]:
            raise ValueError('Review changed upstream recipe: ' + name)
        if (device/name).exists():
            raise ValueError('Conflicting device override: ' + name)
        originals[name] = text
    # ROCKNIX project and device packages share one local namespace. Modify the
    # selected project recipe during composition, retaining its original prefix
    # and patch directory; baseline staging restores that exact prefix.
    for name,text in originals.items():
        if profile and name == 'SDL2':
            hooks = re.findall(r'^pre_configure_target\(\)\{\n.*?^\}',text,re.M|re.S)
            if len(hooks) != 1:
                raise ValueError('Review changed SDL configure hook')
            text += '\n'+MARKER+'\n'+filter_deps(policy['sdl_remove'])
            text += '\n'+hooks[0].replace('pre_configure_target(){','slot_upstream_pre_configure_target(){',1)+'\n'
            flags = ' '.join('-D'+n+'='+v for n,v in policy['sdl_required'].items())
            text += ('\npre_configure_target() {\n  slot_upstream_pre_configure_target\n'
                     '  PKG_CMAKE_OPTS_TARGET+=" ' + flags + '"\n}\n')
        (sources/name/'package.mk').write_text(text)
    slot = device/'slot-rg353v/package.mk'
    text = slot.read_text()
    if MARKER in text:
        text = text.split('\n'+MARKER, 1)[0]
    slot.write_text(text+('\n'+MARKER+'\n'+filter_deps(policy['slot_remove'])+
                         '\nPKG_DEPENDS_TARGET+=" seatd"\n' if profile else ''))
    result = {'schema': 1, 'profile': profile or 'baseline',
              'policy_sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest(),
              'image_remove': policy['image_remove'] if profile else [],
              'network_remove': policy['network_remove'] if profile else [],
              'candidate_requires_hardware_validation': profile is not None}
    (tree/'.rg353v-userspace.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def prune(root, policy_path):
    factory = json.loads((root/'usr/share/slot/os-profile.json').read_text())
    if factory.get('userspace_profile','baseline') == 'baseline':
        return {'profile':'baseline','removed':[]}
    if factory['userspace_profile'] != PROFILE:
        raise ValueError('Unknown installed userspace profile')
    policy = json.loads(policy_path.read_text())
    for icd in (root/'usr/share/vulkan/icd.d').glob('*.json'):
        if 'panfrost' in icd.read_text():
            raise ValueError('Panfrost ICD still enabled; preserve its library')
    removed = []
    for name in policy['image_remove_files']:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid image trim path')
        path = root/relative
        if any(p.is_symlink() for p in [path,*path.parents] if p != root and root in p.parents):
            raise ValueError('Image trim path crosses symlink: '+name)
        if path.exists():
            removed.append({'path':name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    for item in removed:
        (root/item['path']).unlink()
    report = {'profile':PROFILE,'removed':removed}
    output = root/'usr/share/slot/hardware/userspace-trim.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    # Repeated staging preserves the original removal evidence.
    if removed or not output.exists():
        output.write_text(json.dumps(report,indent=2)+'\n')
    return report


def validate(tree, policy_path):
    policy = json.loads(policy_path.read_text())
    build = tree/'build.ROCKNIX-RK3566.aarch64'
    packages = {p.name for p in (build/'image/.stamps').iterdir() if p.is_dir()}
    missing = set(policy['retain']) - packages
    unwanted = set(policy['packages_absent']) & packages
    if missing or unwanted:
        raise ValueError(f'Userspace closure mismatch: missing={sorted(missing)}, unwanted={sorted(unwanted)}')
    for name in ('SDL2', 'SDL2_glesonly'):
        caches = list((build/'build').glob(name+'-*/.aarch64-*/CMakeCache.txt'))
        if len(caches) != 1:
            raise ValueError('Missing/ambiguous SDL CMake cache: '+name)
        # CMake stores subordinate OFF options as INTERNAL when their parent
        # backend is disabled. Validate both forms, then inspect compiled macros.
        values = dict(re.findall(r'^([A-Z0-9_]+):(?:BOOL|INTERNAL)=(.*)$', caches[0].read_text(), re.M))
        for symbol, wanted in policy['sdl_required'].items():
            if values.get(symbol) != wanted:
                raise ValueError(f'{name}: {symbol} expected {wanted}, got {values.get(symbol)}')
        headers = list(caches[0].parent.glob('include-config-*/SDL2/SDL_config.h'))
        if len(headers) != 1:
            raise ValueError('Missing/ambiguous compiled SDL header: '+name)
        header = headers[0]
        compiled = set(re.findall(r'^#define (SDL_[A-Z0-9_]+) 1$',header.read_text(),re.M))
        wanted = {'SDL_AUDIO_DRIVER_ALSA','SDL_VIDEO_DRIVER_KMSDRM','SDL_VIDEO_OPENGL_ES2','SDL_JOYSTICK_LINUX'}
        unused = {'SDL_AUDIO_DRIVER_PIPEWIRE','SDL_AUDIO_DRIVER_PULSEAUDIO','SDL_VIDEO_DRIVER_WAYLAND','SDL_VIDEO_DRIVER_X11','SDL_VIDEO_VULKAN','SDL_USE_LIBUDEV'}
        if not wanted <= compiled or unused & compiled:
            raise ValueError('SDL compiled backend mismatch: '+name)
    return {'profile': PROFILE, 'package_closure': 'passed', 'sdl_build_flags': 'passed'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--tree', type=Path)
    group.add_argument('--image-root', type=Path)
    parser.add_argument('--policy', type=Path, default=Path(__file__).parents[1]/'config/userspace-lean-v1.json')
    parser.add_argument('--profile', choices=[PROFILE])
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prune(args.image_root,args.policy) if args.image_root else
                     validate(args.tree,args.policy) if args.validate else stage(args.tree,args.policy,args.profile),indent=2))
