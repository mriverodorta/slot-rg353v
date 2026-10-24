#!/usr/bin/env python3
"""Build a modular RG353V image. Public and personal outputs never share a directory."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kw):
    subprocess.run([str(x) for x in args], check=True, cwd=ROOT, **kw)


def load_workflow():
    spec = importlib.util.spec_from_file_location('workflow', ROOT/'scripts/rg353v-workflow.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(args):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.version):
        raise ValueError('Use a short version containing letters, numbers, dots, hyphens or underscores')
    private = args.profile == 'localdev'
    output = ROOT/('localdev/images' if private else 'release')/args.version
    if output.exists():
        raise ValueError('Output already exists; choose a new version (existing images are never overwritten)')
    supplied = [args.firmware, args.loader, args.module_kit]
    if any(supplied) and not all(supplied):
        raise ValueError('Fast composition requires --firmware, --loader and --module-kit together')
    for p in filter(None, supplied):
        if not p.exists():
            raise ValueError('Missing build input: '+str(p))
        if not private and (ROOT/'localdev').resolve() in p.resolve().parents:
            raise ValueError('Public builds refuse localdev inputs')
    provisioning = ROOT/'localdev/provisioning'
    if private:
        # This contains the client's PUBLIC key and saved network profiles. The
        # separate server host key identifies only this owner's development image.
        for name in ('slot-setup-debug.json', 'ssh_host_ed25519_key'):
            if not (provisioning/name).is_file():
                raise ValueError('Configure localdev/provisioning first; see wiki/Development.md')
    source_archive = getattr(args, 'source_archive', None)
    if source_archive is not None:
        if not source_archive.is_file() or source_archive.is_symlink():
            raise ValueError('Missing regular matching source archive')
        if not private and (ROOT/'localdev').resolve() in source_archive.resolve().parents:
            raise ValueError('Public builds refuse localdev source assets')
    return {'profile': args.profile, 'version': args.version, 'output': str(output),
            'private': private, 'source_build': not any(supplied),
            'lock': str(args.lock.resolve()), 'work': str((ROOT/'resources/build').resolve()),
            'firmware': str(args.firmware.resolve()) if args.firmware else None,
            'loader': str(args.loader.resolve()) if args.loader else None,
            'module_kit': str(args.module_kit.resolve()) if args.module_kit else None,
            'source_archive': str(source_archive.resolve()) if source_archive else None}


def source_inputs(args, info):
    """Build from pinned public sources, without accessing personal library data."""
    work = Path(info['work'])
    work.mkdir(parents=True, exist_ok=True)
    workflow = load_workflow()
    run(sys.executable, ROOT/'scripts/rg353v-workflow.py', 'firmware', '--lock', args.lock,
        '--work-dir', work)
    lock = json.loads(args.lock.read_text())
    paths = workflow.prepare(lock, work)
    source = paths['slot']/'dist-rg353v/Sources/slot-source.tar.gz'
    if not source.is_file():
        raise ValueError('The source build did not produce its matching source asset')
    info['source_archive'] = str(source)
    report = json.loads((paths['rocknix']/'release/build-report.json').read_text())
    images = [paths['rocknix']/'release'/name for name in report['artifacts']
              if 'RK3566' in name and name.endswith('-Generic.img.gz')]
    if len(images) != 1:
        raise ValueError('Expected one pinned RK3566 Generic factory image')
    out = work/'installer'/args.version
    out.mkdir(parents=True)
    # The bootloader build uses the freshly built, pinned ROCKNIX toolchain.
    # No board backup or device export is an input to a source build.
    env = dict(os.environ, SLOT_BOOTSTAGE_SD_PROBE='1', SLOT_BOOTSTAGE_SD_CLOCK_FIX='1', SLOT_BOOTSTAGE_EMMC_SELECT='1')
    run('bash', ROOT/'scripts/build-rg353v-bootstage.sh', out/'loader', env=env)
    run('bash', ROOT/'scripts/build-rg353v-installer-tools.sh', out/'tools')
    arch = subprocess.check_output(['docker', 'info', '--format', '{{.Architecture}}'], text=True).strip()
    if arch not in ('aarch64', 'arm64'):
        raise ValueError('The current installer-tool/loader pipeline requires an ARM64 Docker engine')
    # Reuse only public compilation outputs. All root extraction/splitting stays
    # on Linux, so case-distinct kernel module filenames survive macOS hosts.
    run('docker', 'run', '--rm', '--privileged', '-v', 'slot-rocknix-rg353v-arm-builder:/cache:ro',
        '-v', 'slot-rg353v-installer-kit:/work', '-e', 'KIT_VERSION='+args.version,
        '-v', str(ROOT/'scripts')+':/src/scripts:ro', '-v', str(ROOT/'ports')+':/src/ports:ro',
        '-v', str(out)+':/task', '-v', str(images[0])+':/factory.img.gz:ro',
        'slot-rg353v-module-tools:latest', 'python3', '/src/scripts/prepare-rg353v-module-kit.py')
    return images[0], out/'loader/rg353v-bootstage.bin', out/'kit'


def finish_record(args, info, compressed):
    output = compressed.parent
    digest = hashlib.sha256()
    with compressed.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    digest = digest.hexdigest()
    sums = digest+'  '+compressed.name+'\n'
    source_record = None
    if info.get('source_archive'):
        source = output/('Slot-RG353V-'+args.version+'-source.tar.gz')
        if source.exists():
            raise ValueError('Source asset output exists')
        shutil.copy2(info['source_archive'], source)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        sums += source_hash+'  '+source.name+'\n'
        source_record = {'file': source.name, 'sha256': source_hash, 'bytes': source.stat().st_size}
    (output/'SHA256SUMS').write_text(sums)
    lock = json.loads(args.lock.read_text())
    record = {key: info[key] for key in ('profile', 'version', 'private', 'source_build')}
    record.update(image=compressed.name, sha256=digest, compressed_bytes=compressed.stat().st_size,
                  source_asset=source_record,
                  sources=lock['sources'], layer_sha256=lock['layer_sha256'],
                  repository_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  working_tree_changes=subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip() != '',
                  qualification='candidate; physical clean-install validation still required',
                  publication='not uploaded; review CREDITS.md and wiki/Releasing.md before publication')
    # Do not put the owner's absolute source/provisioning paths in the record
    # that can accompany a public image.
    (output/'build.json').write_text(json.dumps(record, indent=2)+'\n')
    if info['private']:
        for p in output.iterdir():
            if p.is_file():
                p.chmod(0o600)


def promote_localdev(output):
    """Keep one current personal image; preserve old delivered paths as links."""
    home = ROOT/'localdev'
    current = home/'current'
    if current.exists() and not current.is_symlink():
        raise ValueError('localdev/current must be a managed link, not a directory')
    if current.is_symlink():
        previous = current.resolve(strict=True)
        if previous != output.resolve():
            if previous.parent != (home/'images').resolve():
                raise ValueError('Refusing to archive an unexpected current-image location')
            record = json.loads((previous/'build.json').read_text())
            if record.get('private') is not True:
                raise ValueError('Current image lacks a private build receipt')
            archive = ROOT/'resources/private-image-history'/previous.name
            archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if archive.exists():
                raise ValueError('Private image history destination already exists')
            previous.rename(archive)
            previous.symlink_to(os.path.relpath(archive, previous.parent), target_is_directory=True)
    temporary = home/'.current-new'
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('Another development-image promotion may be in progress')
    temporary.symlink_to(os.path.relpath(output, home), target_is_directory=True)
    temporary.replace(current)


def main():
    if sys.version_info < (3, 11):
        raise ValueError('Image builds require Python 3.11 or newer; put that python3 first on PATH')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=('release', 'localdev'))
    parser.add_argument('--version', required=True)
    parser.add_argument('--lock', type=Path, default=ROOT/'ports/rg353v/upstreams.lock.json')
    parser.add_argument('--firmware', type=Path, help='Qualified two-partition factory .img.gz (optional fast composition)')
    parser.add_argument('--loader', type=Path, help='Pinned F-recovery loader')
    parser.add_argument('--module-kit', type=Path, help='Public module kit directory')
    parser.add_argument('--source-archive', type=Path, help='Matching source asset for fast composition; copied beside the image')
    parser.add_argument('--plan', action='store_true', help='Validate paths and print the build plan without building')
    args = parser.parse_args()
    info = plan(args)
    if args.plan:
        print(json.dumps(info, indent=2))
        return
    arch = subprocess.check_output(['docker', 'info', '--format', '{{.Architecture}}'], text=True).strip()
    if arch not in ('aarch64', 'arm64'):
        raise ValueError('Image assembly currently requires an ARM64 Docker engine; see wiki/Building.md')
    if subprocess.run(['docker', 'image', 'inspect', 'slot-rg353v-module-tools:latest'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run('docker', 'build', '-t', 'slot-rg353v-module-tools:latest',
            '-f', ROOT/'ports/rg353v/image/Dockerfile', ROOT/'ports/rg353v/image')
    firmware, loader, kit = ((args.firmware.resolve(), args.loader.resolve(), args.module_kit.resolve())
                             if args.firmware else source_inputs(args, info))
    output = Path(info['output'])
    output.mkdir(parents=True, mode=0o700 if info['private'] else 0o755)
    filename = 'Slot-RG353V-'+args.version+('-PRIVATE' if info['private'] else '')+'.img'
    mounts = ['-v', str(ROOT/'scripts')+':/src/scripts:ro',
              '-v', str(ROOT/'ports')+':/src/ports:ro', '-v', str(firmware)+':/factory.img.gz:ro',
              '-v', str(loader)+':/loader.bin:ro', '-v', str(kit)+':/kit:ro',
              '-v', str(output)+':/output']
    extra = ['--public']
    if info['private']:
        # Never mount any private directory in the public container.
        mounts += ['-v', str(ROOT/'localdev/provisioning')+':/private:ro']
        extra = ['--debug-profile', '/private/slot-setup-debug.json', '--host-key',
                 '/private/ssh_host_ed25519_key', '--setup-debug']
    run('docker', 'run', '--rm', '--privileged', *mounts,
        '-e', 'IMAGE_NAME='+filename, '-e', 'OUTPUT_UID='+str(os.getuid()),
        '-e', 'OUTPUT_GID='+str(os.getgid()), 'slot-rg353v-module-tools:latest',
        'bash', '-ec', '''
          trap 'rm -f /output/.factory.img' EXIT
          pigz -dc /factory.img.gz > /output/.factory.img
          python3 /src/scripts/compose-rg353v-clean.py --input /output/.factory.img \
            --output "/output/$IMAGE_NAME" --loader /loader.bin --module-kit /kit "$@"
          pigz -p 4 -k "/output/$IMAGE_NAME"
          pigz -t "/output/$IMAGE_NAME.gz"
          chown -R "$OUTPUT_UID:$OUTPUT_GID" /output
        ''', 'compose', *extra)
    compressed = output/(filename+'.gz')
    finish_record(args, info, compressed)
    # gzip was verified above; only the compressed delivery image is retained.
    (output/filename).unlink()
    if info['private']:
        promote_localdev(output)
    print(str(compressed))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Image build stopped:', error, file=sys.stderr)
        sys.exit(1)
