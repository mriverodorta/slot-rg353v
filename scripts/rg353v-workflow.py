#!/usr/bin/env python3
"""Compose official Slot/ROCKNIX sources with the versioned RG353V layer."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / 'ports/rg353v/layer'
DEFAULT_LOCK = ROOT / 'ports/rg353v/upstreams.lock.json'
URLS = {'slot': 'https://github.com/BrandonKowalski/slot.git',
        'rocknix': 'https://github.com/ROCKNIX/distribution.git'}


def run(*args, cwd=None, capture=False, env=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True,
                          stdout=subprocess.PIPE if capture else None,
                          text=capture, env=env).stdout


def git(path, *args, capture=True):
    return run('git', '-C', path, *args, capture=capture)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    tmp.replace(path)


def layer_hash():
    digest = hashlib.sha256()
    for path in sorted(LAYER.rglob('*')):
        if path.is_symlink():
            raise RuntimeError(f'Layer symlinks are unsupported: {path}')
        if path.is_file():
            digest.update(str(path.relative_to(LAYER)).encode() + b'\0')
            digest.update(path.read_bytes())
    return digest.hexdigest()


def export_layer():
    raise RuntimeError('Root prototype export is retired. Edit a prepared pinned checkout and update the versioned layer as described in CONTRIBUTING.md; never snapshot the project root over the layer.')


def latest_ref(name, channel):
    repo = URLS[name].removeprefix('https://github.com/').removesuffix('.git')
    endpoint = '/releases/latest' if channel == 'stable' else ''
    request = urllib.request.Request('https://api.github.com/repos/' + repo + endpoint,
                                     headers={'User-Agent': 'slot-rg353v-build'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    return 'refs/tags/' + data['tag_name'] if channel == 'stable' else 'refs/heads/' + data['default_branch']


def resolve(url, ref):
    rows = run('git', 'ls-remote', url, ref, ref + '^{}', capture=True).splitlines()
    values = dict(row.split()[::-1] for row in rows)
    commit = values.get(ref + '^{}') or values.get(ref)
    if not commit:
        raise RuntimeError(f'Cannot resolve {url} {ref}')
    return commit


def source(work, name, spec):
    if spec['url'] != URLS[name] or len(spec['commit']) != 40 or any(c not in '0123456789abcdef' for c in spec['commit']):
        raise RuntimeError(f'Invalid upstream identity for {name}')
    cache = work / 'cache' / (name + '.git')
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'clone', '--bare', spec['url'], cache)
    try:
        git(cache, 'cat-file', '-e', spec['commit'] + '^{commit}')
    except subprocess.CalledProcessError:
        git(cache, 'fetch', 'origin', spec['commit'], capture=False)
    return cache


def checkout(cache, dest, commit):
    dest.parent.mkdir(parents=True, exist_ok=True)
    run('git', 'clone', '--shared', '--no-checkout', cache, dest)
    git(dest, 'checkout', '--detach', commit, capture=False)
    with (dest / '.git/info/exclude').open('a') as f:
        f.write('\n/.rg353v-*\n/target\n/target-rg353v\n/dist-rg353v\n/vendor\n/local-logs\n/prep\n/release/\n__pycache__/\n*.py[cod]\n')


def ignore_release_output(dest):
    # Older prepared trees predate copying firmware artifacts into release/.
    exclude = dest / '.git/info/exclude'
    text = exclude.read_text()
    generated = ('/release/', '__pycache__/', '*.py[cod]')
    missing = [pattern for pattern in generated if pattern not in text.splitlines()]
    if missing:
        with exclude.open('a') as stream:
            stream.write('\n' + '\n'.join(missing) + '\n')


def fingerprint(path):
    digest = hashlib.sha256(git(path, 'diff', '--binary', 'HEAD').encode())
    for name in sorted(git(path, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')):
        if name:
            p = path / name
            digest.update(name.encode() + b'\0' + p.read_bytes())
    return digest.hexdigest()


def validate_rocknix(path):
    required = ['packages/virtual/image/package.mk', 'packages/virtual/alsa/package.mk']
    for name in required:
        if not (path / name).is_file():
            raise RuntimeError(f'ROCKNIX package contract changed: {name}')
    if not list(path.glob('**/packages/**/SDL2/package.mk')):
        raise RuntimeError('ROCKNIX no longer exposes the SDL2 package')
    project = 'ROCKNIX' if (path / 'projects/ROCKNIX/devices/RK3566').is_dir() else 'Rockchip'
    if not (path / f'projects/{project}/devices/RK3566').is_dir():
        raise RuntimeError('ROCKNIX no longer exposes RK3566')
    make = (path / 'Makefile').read_text()
    if 'docker-%:' not in make:
        raise RuntimeError('ROCKNIX Docker make target changed')
    result = subprocess.run(['git', '-C', str(path), 'grep', '-qi', 'rg353v', '--', f'projects/{project}/devices/RK3566'])
    if result.returncode != 0:
        raise RuntimeError('ROCKNIX RG353V device definition missing')
    image = path / f'projects/{project}/packages/virtual/image/package.mk'
    if not image.exists():
        image = path / 'packages/virtual/image/package.mk'
    if 'BASE_ONLY' not in image.read_text():
        raise RuntimeError('ROCKNIX base-only image contract changed')
    return project, image


def prepare(lock, work):
    if lock['schema'] != 1 or lock['layer_sha256'] != layer_hash():
        raise RuntimeError('Layer differs from lock; run update (or lock-layer for unchanged upstreams)')
    profile = lock.get('build', {}).get('profile')
    if profile is not None and profile not in ('normal', 'development'):
        raise RuntimeError('Unknown RG353V build profile')
    kernel_profile = lock.get('build', {}).get('kernel_profile')
    if kernel_profile not in (None, 'rg353v-slim-v1'):
        raise RuntimeError('Unknown RG353V kernel profile')
    userspace_profile = lock.get('build', {}).get('userspace_profile')
    if userspace_profile not in (None, 'rg353v-lean-v1'):
        raise RuntimeError('Unknown RG353V userspace profile')
    prepared = {}
    for name, spec in lock['sources'].items():
        cache = source(work, name, spec)
        dest = work / 'work' / (name + '-' + spec['commit'][:12] + '-' + lock['layer_sha256'][:12] + ('-' + profile if profile else '') + ('-' + kernel_profile if kernel_profile else '') + ('-' + userspace_profile if userspace_profile else ''))
        marker = dest / '.rg353v-prepared.json'
        if dest.exists():
            ignore_release_output(dest)
            if not marker.exists() or json.loads(marker.read_text())['fingerprint'] != fingerprint(dest):
                raise RuntimeError(f'Generated checkout was edited or preparation failed: {dest}; preserve it, then move it aside')
        else:
            checkout(cache, dest, spec['commit'])
            if name == 'slot':
                # Three-way application accepts clean upstream merges, never unresolved conflicts.
                git(dest, 'apply', '--3way', LAYER / 'patches/slot.patch', capture=False)
                if git(dest, 'ls-files', '-u').strip():
                    raise RuntimeError('Unresolved Slot patch conflict')
                git(dest, 'reset', capture=False)
                for p in (LAYER / 'files').rglob('*'):
                    if p.is_file():
                        out = dest / p.relative_to(LAYER / 'files')
                        if out.exists():
                            raise RuntimeError(f'Overlay would overwrite an upstream file: {out}')
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(p, out)
            else:
                rocknix_patch = LAYER / 'patches/rocknix.patch'
                if rocknix_patch.exists():
                    git(dest, 'apply', rocknix_patch, capture=False)
                validate_rocknix(dest)
            if name == 'slot':
                # Build products are shared across layer revisions of one upstream;
                # Cargo and core source stamps invalidate changed inputs themselves.
                artifacts = work / 'artifacts' / spec['commit']
                for folder in ('target', 'target-rg353v', 'vendor'):
                    target = artifacts / folder
                    target.mkdir(parents=True, exist_ok=True)
                    (dest / folder).symlink_to(target, target_is_directory=True)
            write_json(marker, {'fingerprint': fingerprint(dest)})
        prepared[name] = dest
    return prepared


def stage_profiles(rocknix, project, lock, policy_path):
    profile = lock.get('build', {}).get('profile')
    if profile is None:
        return  # Existing locks retain their original build behavior.
    policy = json.loads(policy_path.read_text())
    if policy.get('schema') != 1 or profile not in ('normal', 'development'):
        raise RuntimeError('Unsupported build-profile policy')
    chosen, shared = policy[profile], policy['shared']
    lists = [shared[k] + chosen.get(k, []) for k in ('image_remove', 'network_remove', 'mask_units')]
    userspace = rocknix / '.rg353v-userspace.json'
    if userspace.exists():
        extra = json.loads(userspace.read_text())
        if extra['profile'] != (lock.get('build', {}).get('userspace_profile') or 'baseline'):
            raise RuntimeError('Userspace profile mismatch')
        for index, key in enumerate(('image_remove', 'network_remove')):
            lists[index] += extra[key]
    if any(not re.fullmatch(r'[A-Za-z0-9_.:+-]+', value) for values in lists for value in values):
        raise RuntimeError('Unsafe build-profile token')
    marker = '# RG353V build-profile policy'
    masks = shared['mask_units'] + chosen['mask_units']
    for name, removed in zip(('image', 'network'), lists[:2]):
        upstream = f'projects/{project}/packages/virtual/{name}/package.mk'
        if not (rocknix / upstream).is_file():
            raise RuntimeError(f'Missing official profile base: {upstream}')
        destination = rocknix / upstream
        original = destination.read_text().split('\n' + marker, 1)[0]
        if name == 'image' and re.search(r'^\s*(?:function\s+)?post_install\s*\(', original, re.M):
            raise RuntimeError('Official Image gained a post_install hook; review profile integration')
        obsolete = rocknix / f'projects/{project}/devices/RK3566/packages/{name}/package.mk'
        if obsolete.exists() and obsolete.read_text().startswith('# Generated RG353V profile overlay;'):
            obsolete.unlink()
            obsolete.parent.rmdir()
        text = original + '\n' + marker + '\n'
        text += f'[[ "${{SLOT_RG353V_PROFILE:-}}" = "{profile}" ]] || {{ echo "RG353V profile mismatch" >&2; return 1; }}\n'
        text += 'slot_profile_deps=""\nfor dependency in ${PKG_DEPENDS_TARGET}; do\n  case "$dependency" in\n'
        text += '    ' + '|'.join(removed) + ') ;;\n' if removed else '    __no_package__) ;;\n'
        text += '    *) slot_profile_deps+=" $dependency" ;;\n  esac\ndone\nPKG_DEPENDS_TARGET="${slot_profile_deps}"\nunset slot_profile_deps dependency\n'
        if name == 'image':
            text += 'PKG_DEPENDS_TARGET+=" procps-ng"\npost_install() {\n'
            for unit in masks:
                text += f'  ln -sf /dev/null "${{INSTALL}}/usr/lib/systemd/system/{unit}"\n'
                text += f'  for link in "${{INSTALL}}"/usr/lib/systemd/system/*.wants/{unit}; do\n    [ ! -L "$link" ] || rm -f "$link"\n  done\n'
            for hook in shared['remove_daemon_hooks']:
                if not re.fullmatch(r'[A-Za-z0-9_-]+', hook):
                    raise RuntimeError('Unsafe autostart hook')
                text += f'  rm -f "${{INSTALL}}/usr/lib/autostart/daemons/{hook}"\n'
            if lock.get('build', {}).get('userspace_profile'):
                text += ('  python3 "${PROJECT_DIR}/${PROJECT}/devices/RK3566/packages/'
                         'slot-startup-profile/tools/configure-firmware.py" --root "${INSTALL}"\n')
                text += ('  python3 "${PROJECT_DIR}/${PROJECT}/devices/RK3566/packages/'
                         'slot-startup-profile/tools/configure-image-prune.py" --root "${INSTALL}"\n')
                text += ('  python3 "${PROJECT_DIR}/${PROJECT}/devices/RK3566/packages/'
                         'slot-startup-profile/tools/configure-appliance.py" --root "${INSTALL}" '
                         '--boot-artifacts "${BUILD}/slot-boot-artifacts/' + lock['layer_sha256'] + '"\n')
            text += '}\n'
        destination.write_text(text)
    if lock.get('build', {}).get('userspace_profile'):
        # The runtime copies can be removed only after preserving the inputs
        # used by ROCKNIX's later release/mkimage stage. Never take them from a
        # previous layer's cache or put them back into the runtime SYSTEM.
        release = rocknix / f'projects/{project}/bootloader/release'
        original = release.read_text()
        needle = 'cp -a ${INSTALL}/usr/share/bootloader/* ${RELEASE_DIR}/3rdparty/bootloader'
        replacement = ('test -f "${BUILD}/slot-boot-artifacts/' + lock['layer_sha256'] +
                       '/.slot-build-inputs.json" || exit 1\n  '
                       'cp -a "${BUILD}/slot-boot-artifacts/' + lock['layer_sha256'] +
                       '/"* ${RELEASE_DIR}/3rdparty/bootloader')
        if needle in original:
            release.write_text(original.replace(needle, replacement))
        elif replacement not in original:
            raise RuntimeError('Review changed ROCKNIX bootloader release contract')
    write_json(rocknix / '.rg353v-profile.json', {
        'schema': 1, 'profile': profile, 'debug_packages': chosen['debug_packages'],
        'policy_sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        'image_remove': lists[0], 'network_remove': lists[1], 'mask_units': masks,
        'retain': [p for p in policy['retain'] if not lock.get('build', {}).get('userspace_profile')
                   or p not in ('pipewire', 'wireplumber')], 'layer_sha256': lock['layer_sha256'],
    })


def stage_rocknix(slot, rocknix, lock):
    bundle = slot / 'dist-rg353v/System'
    if not (bundle / 'slot').is_file():
        raise RuntimeError('Package Slot before staging ROCKNIX')
    project, upstream_image = validate_rocknix(rocknix)
    packages = rocknix / f'projects/{project}/devices/RK3566/packages'
    for source in sorted((slot / 'ports/rg353v/rocknix').iterdir()):
        if not source.is_dir() or not (source / 'package.mk').is_file():
            continue
        destination = packages / source.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    destination = packages / 'slot-rg353v'
    # Component OTAs need the same source/layer identity as full OS bundles.
    write_json(bundle / 'build-manifest.json', lock)
    shutil.copytree(bundle, destination / 'bundle/System')
    profile = json.loads((destination / 'config/os-profile.json').read_text())
    profile.update(sources=lock['sources'], layer_sha256=lock['layer_sha256'],
                   build_profile=lock.get('build', {}).get('profile', 'legacy'),
                   kernel_profile=lock.get('build', {}).get('kernel_profile') or 'baseline',
                   userspace_profile=lock.get('build', {}).get('userspace_profile') or 'baseline',
                   factory_binaries={name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
                                     for name in ('slot', 'mgba_libretro.so', 'gpsp_libretro.so')})
    write_json(destination / 'config/os-profile.json', profile)
    image = rocknix / f'projects/{project}/packages/virtual/image/package.mk'
    if not image.exists():
        image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upstream_image, image)
    marker = '# slot-rg353v managed layer'
    text = image.read_text()
    if marker not in text:
        image.write_text(text + '\n' + marker + '\nif [ "${BASE_ONLY}" = "true" ] && [ "${DEVICE}" = "RK3566" ] && [ "${ARCH}" = "aarch64" ]; then\n  PKG_DEPENDS_TARGET+=" slot-rg353v slot-startup-profile"\nfi\n')
    splash = packages / 'slot-bootsplash'
    if project == 'ROCKNIX' and splash.exists():
        run('python3', splash / 'tools/patch-boot.py', rocknix, splash / 'config/boot-plan.json')
    kernel_profile = lock.get('build', {}).get('kernel_profile')
    if project == 'ROCKNIX':
        run('python3', slot / 'ports/rg353v/rocknix/slot-startup-profile/tools/configure-bootloader.py', '--tree', rocknix)
        kernel_tool = slot / 'ports/rg353v/rocknix/slot-startup-profile/tools/configure-kernel.py'
        kernel_args = ['--profile', kernel_profile] if kernel_profile else []
        run('python3', kernel_tool, '--tree', rocknix, *kernel_args)
        userspace_tool = slot / 'ports/rg353v/rocknix/slot-startup-profile/tools/configure-userspace.py'
        userspace_profile = lock.get('build', {}).get('userspace_profile')
        userspace_args = ['--profile', userspace_profile] if userspace_profile else []
        run('python3', userspace_tool, '--tree', rocknix, *userspace_args)
    elif kernel_profile:
        raise RuntimeError('Kernel trial requires the pinned ROCKNIX project')
    elif lock.get('build', {}).get('userspace_profile'):
        raise RuntimeError('Userspace trial requires the pinned ROCKNIX project')
    stage_profiles(rocknix, project, lock, slot / 'ports/rg353v/build-profiles.json')
    write_json(rocknix / '.rg353v-prepared.json', {'fingerprint': fingerprint(rocknix)})


def image_command(image, output, private_backup=None):
    """Public images are clean/minimal; private restoration remains explicit."""
    if private_backup is not None:
        return [ROOT / 'scripts/compose-rocknix-card.sh', image, output, private_backup.resolve()]
    return [ROOT / 'scripts/build-rg353v-clean-image.sh', image, output]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['export-layer', 'update', 'lock-layer', 'prepare', 'check', 'build', 'firmware', 'image', 'package-update'])
    parser.add_argument('--profile', choices=['normal', 'development'], help='Record a profile with update/lock-layer; other commands require the locked profile')
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    parser.add_argument('--work-dir', type=Path, default=ROOT / '.build-rg353v')
    parser.add_argument('--slot-channel', choices=['stable', 'development'], default='development')
    parser.add_argument('--rocknix-channel', choices=['stable', 'development'], default='stable')
    parser.add_argument('--slot-ref', help='Explicit official Git ref instead of the channel')
    parser.add_argument('--rocknix-ref', help='Explicit official Git ref instead of the channel')
    parser.add_argument('--update', action='store_true', help='Resolve latest upstreams before this command')
    parser.add_argument('--private-backup', type=Path, help='For image: provision Wi-Fi/SSH and content from a verified local backup')
    parser.add_argument('--base-manifest', type=Path, help='For package-update: installed revision.json exported from the handheld')
    parser.add_argument('--component', choices=['slot', 'cores'], default='slot')
    parser.add_argument('--package-id', help='For package-update: unique version label (defaults to component and layer hash)')
    parser.add_argument('--output', type=Path, help='For package-update: output .tar.gz')
    parser.add_argument('--states-compatible', action='store_true', help='Attest core save-state compatibility after regression testing')
    parser.add_argument('--full-package', action='store_true', help='Build a legacy full component package for updater bootstrap')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if args.command == 'export-layer':
        export_layer()
        return
    if args.command == 'update' or args.update:
        sources = {}
        for name in URLS:
            ref = getattr(args, name + '_ref') or latest_ref(name, getattr(args, name + '_channel'))
            sources[name] = {'url': URLS[name], 'ref': ref, 'commit': resolve(URLS[name], ref)}
        lock = {'schema': 1, 'sources': sources, 'layer_sha256': layer_hash(),
                'resolved_at': datetime.now(timezone.utc).isoformat(),
                'build': {'device': 'RG353V', 'rocknix_target': 'RK3566', 'arch': 'aarch64',
                          'base_only': True, 'startup': 'slot',
                          'content_label': 'SLOT', 'content_filesystem': 'exfat', 'profile': args.profile or 'normal'}}
        paths = prepare(lock, work)  # Validate before replacing the good lock.
        write_json(args.lock, lock)
    else:
        lock = json.loads(args.lock.read_text())
        if args.profile and args.command != 'lock-layer' and args.profile != lock.get('build', {}).get('profile'):
            raise RuntimeError('Profile differs from lock; run lock-layer --profile first')
        if args.command == 'lock-layer':
            lock['layer_sha256'] = layer_hash()
            lock['build'].update(startup='slot', content_label='SLOT', content_filesystem='exfat')
            if args.profile:
                lock['build']['profile'] = args.profile
        paths = prepare(lock, work)
        if args.command == 'lock-layer':
            write_json(args.lock, lock)
    print(json.dumps({k: str(v) for k, v in paths.items()}, indent=2), flush=True)
    if args.command == 'package-update':
        if args.base_manifest is None:
            raise RuntimeError('package-update requires --base-manifest from the installed device')
        built = paths['slot'] / 'dist-rg353v/build-manifest.json'
        if not built.exists() or json.loads(built.read_text()) != lock:
            raise RuntimeError('Run the build command for this exact lock before packaging an update')
        version = args.package_id or args.component + '-' + lock['layer_sha256'][:12]
        output = args.output or work / 'updates' / (version + '.tar.gz')
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [ROOT / 'ports/rg353v/rocknix/slot-rg353v/scripts/slot-update',
                   'package', '--system', paths['slot'] / 'dist-rg353v/System',
                   '--base', args.base_manifest.resolve(), '--kind', args.component,
                   '--id', version, '--output', output.resolve()]
        if not args.full_package:
            command.append('--delta')
        if args.states_compatible:
            command.append('--states-compatible')
        run('python3', *command)
    if args.command in ('check', 'build', 'firmware', 'image'):
        build_env = dict(os.environ, SLOT_BUILD_WORKSPACE=str(work))
        run('scripts/check-rg353v-local.sh', cwd=paths['slot'], env=build_env)
        if args.command in ('build', 'firmware', 'image'):
            run('scripts/package-rg353v.sh', cwd=paths['slot'], env=build_env)
            stage_rocknix(paths['slot'], paths['rocknix'], lock)
            write_json(paths['slot'] / 'dist-rg353v/build-manifest.json', lock)
        if args.command in ('firmware', 'image'):
            run(ROOT / 'scripts/build-rocknix-mini.sh', paths['rocknix'])
            if lock['build'].get('profile'):
                run('python3', ROOT / 'scripts/compare-rg353v-builds.py',
                    '--report', paths['rocknix'] / 'release/build-report.json',
                    '--policy', paths['slot'] / 'ports/rg353v/build-profiles.json')
        if args.command == 'image':
            release = paths['rocknix'] / 'release'
            report = release / 'build-report.json'
            if report.exists():
                artifacts = json.loads(report.read_text())['artifacts']
                images = [release / name for name in artifacts if name.endswith('-Generic.img.gz') and 'RK3566' in name]
            else:
                images = list(release.glob('*RK3566*-Generic.img.gz'))
            if len(images) != 1:
                raise RuntimeError(f'Expected one RK3566 firmware image, found {len(images)}; select the matching variant before composing')
            output = work / 'images' / (lock['layer_sha256'][:12] + ('-' + lock['build']['profile'] if lock['build'].get('profile') else ''))
            run(*image_command(images[0], output, args.private_backup))
            write_json(output / 'build-manifest.json', lock)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as error:
        print('RG353V build stopped:', error, file=sys.stderr)
        sys.exit(1)
