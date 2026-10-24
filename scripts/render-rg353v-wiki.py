#!/usr/bin/env python3
"""Render the native 640x480 guide assets without touching a handheld.

Requires Pillow. Frontend captures additionally need the prepared pinned Slot
workspace, Docker and the development image; animations optionally use ffmpeg.
All installer operations here stop at Model.key(); no install backend is loaded.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / 'wiki'
WORK = ROOT / 'resources/wiki-capture-20261022'


def load_ui():
    spec = importlib.util.spec_from_file_location('setup_ui', ROOT / 'ports/rg353v/image/slot-setup-ui.py')
    ui = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ui)
    return ui


def setup():
    ui = load_ui()
    catalog = json.loads((ROOT / 'ports/rg353v/modules/catalog-v1.json').read_text())
    canvas = ui.Canvas(ROOT / 'ports/rg353v/image/slot-setup-font.json.gz')
    spec = importlib.util.spec_from_file_location('emmc_layout', ROOT / 'ports/rg353v/image/slot-emmc-install.py')
    layout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(layout)
    def destination(capacity):
        return {'bytes': capacity, 'content_bytes': layout.geometry(capacity)[3][1],
                'layout': dict(layout.DEFAULT_LAYOUT)}
    source = destination(60492349440)
    target = destination(31268536320)
    dest = WIKI / 'images/setup'
    dest.mkdir(parents=True, exist_ok=True)
    model = ui.Model(source, target, modules=catalog, sd_test=True)
    animation = []
    def shot(name, duration=1100, animate=True):
        model.draw(canvas)
        image = Image.frombytes('RGBA', (640, 480), bytes(canvas.pixels)).convert('RGB')
        image.save(dest / (name + '.png'), optimize=True)
        if animate:
            animation.append((image.copy(), duration))
    shot('01-destination-sd')
    model.key('down'); shot('02-destination-emmc', animate=False)
    model.key('up'); model.key('a'); shot('03-preset-minimal')
    model.key('right'); shot('04-preset-recommended')
    model.key('left'); model.key('down'); shot('05-preset-full')
    model.key('a'); shot('review-full',1400)
    model.key('b'); model.key('right'); shot('05-preset-custom')
    model.key('a'); shot('06-features-emulators')
    # Walk every installed feature and capture each group and every Y modal.
    groups = set()
    for i, module in enumerate(catalog['modules']):
        model.selected = i
        model.scroll_features()
        if module.get('group') not in groups:
            groups.add(module.get('group'))
            shot('features-' + module['id'], animate=False)
        if module['id'] not in model.features:
            model.key('a')
        if module['id'] in ('wifi', 'usb-network', 'screenshots', 'gallery'):
            shot('select-' + module['id'], duration=700)
        model.key('y'); shot('info-' + module['id'], animate=False); model.key('b')
    model.selected = len(catalog['modules']); model.scroll_features()
    shot('07-features-continue'); model.key('a')
    assert model.page == 'review'
    shot('08-review-top', 1600)
    model.draw(canvas)
    while model.text_first < model.document_limit:
        before = model.text_first
        for _ in range(5): model.key('down')
        shot('review-' + str(model.text_first).zfill(2), 650)
        assert model.text_first > before
    shot('09-review-bottom', 1200)
    model.key('a'); shot('10-confirm-sd', 1500)
    model.key('down'); shot('11-confirm-sd-selected', 1000)
    # Model returns 'sd'; deliberately never dispatch to the installation code.
    assert model.key('a') == 'sd'
    for i, (message, percent) in enumerate([
        ('Preparing the SD card', 5), ('Preparing system storage', 20),
        ('Creating game storage', 45), ('Finishing the SD installation', 75),
        ('Checking feature packages', 78), ('Building your selected system', 88),
        ('Checking the selected system', 96), ('Ready to restart', 100),
    ]):
        model.status = message; model.percent = percent
        for tick in range(3):
            model.elapsed = 5 + i * 5 + tick
            model.activity_frame = tick
            shot(f'progress-{percent:03}-{tick}', 300)
    model.page = 'done'; model.text_first = 0; shot('12-complete-sd', 1800)
    model.draw(canvas)
    while model.text_first < model.document_limit:
        for _ in range(5): model.key('down')
        shot('complete-' + str(model.text_first).zfill(2), 650)
    # Alternate paths, warning states and the eMMC confirmation are references.
    model.action = 'emmc'; model.page = 'confirm'; model.selected = 0
    shot('13-confirm-emmc', animate=False)
    model.page = 'done'; model.text_first = 0; shot('14-complete-emmc', animate=False)
    model.features = {'emulator-mgba'}; model.page = 'modules'; model.access()
    assert model.page == 'access'; shot('15-no-transfer-warning', animate=False)
    model.page = 'modules'; model.action = 'sd'; model.features = set()
    model.selected = len(catalog['modules']); model.key('a')
    assert model.page == 'modules'; shot('16-no-emulator-warning', animate=False)
    for name in ('minimal','recommended','full'):
        model.page='presets'; model.selected=ui.preset_index(name)
        model.key('a'); shot('review-' + name, animate=False)
    model.page='error'; model.status='Example: setup was interrupted. Restart setup from the SD card.'
    shot('17-setup-error', animate=False)
    save_animation('setup-walkthrough', animation)
    return len(list(dest.glob('*.png')))


def save_animation(name, frames, fps=25):
    dest = WIKI / 'media'; dest.mkdir(parents=True, exist_ok=True)
    # Shared palette avoids unnecessary colour shifts at each frame boundary.
    atlas = Image.new('RGB', (640, 480 * len(frames)))
    for i, (im, _) in enumerate(frames): atlas.paste(im, (0, 480*i))
    palette = atlas.resize((320, max(1, 240*len(frames)))).quantize(colors=256)
    indexed = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im, _ in frames]
    indexed[0].save(dest/(name+'.gif'), save_all=True, append_images=indexed[1:],
                    duration=[n for _, n in frames], loop=0, disposal=1, optimize=True)
    ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg')
    if ffmpeg:
        with tempfile.TemporaryDirectory(prefix='video-', dir=WORK) as temporary:
            temporary = Path(temporary); lines=[]
            for i, (im, duration) in enumerate(frames):
                im.save(temporary/f'{i:04}.png')
                lines += [f"file '{i:04}.png'"]
                if fps != 25:
                    # PNG's default 25 Hz input clock loses short handoff frames.
                    lines += ['option framerate 1000']
                lines += [f'duration {duration/1000:.3f}']
            lines.append(f"file '{len(frames)-1:04}.png'")
            if fps != 25:
                lines.append('option framerate 1000')
            (temporary/'list.txt').write_text('\n'.join(lines)+'\n')
            total = sum(n for _,n in frames)/1000
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','concat',
                '-safe','0','-i',str(temporary/'list.txt'),'-vf',f'fps={fps}','-t',str(total),
                '-an','-c:v','libx264','-preset','slow','-crf','18','-pix_fmt','yuv420p',
                '-movflags','+faststart',str(dest/(name+'.mp4'))],check=True)


def frontend(source, target, container, library, core, only_ota=False):
    source=source.resolve(); target=target.resolve(); target.mkdir(parents=True,exist_ok=True)
    if not (source/'crates/slot/src/frontend.rs').is_file():
        raise SystemExit('Use the prepared, pinned Slot workspace, not the archived root prototype.')
    library=library.resolve(); core=core.resolve()
    if not (library/'Games').is_dir() or not (library/'Labels').is_dir():
        raise SystemExit('--library needs Games and Labels; it will be mounted read-only.')
    if not core.is_file() or core.name!='mgba_libretro.so':raise SystemExit('--core needs the qualified ARM64 mGBA library')
    original=ROOT/'scripts/wiki/frontend.rs'
    example=source/'crates/slot/examples/wiki_guide.rs'
    if example.exists():
        raise SystemExit('Refusing to overwrite an existing wiki_guide.rs; remove only your owned previous capture copy.')
    example_bytes=original.read_bytes()
    example.write_bytes(example_bytes)
    fixture=ROOT/'scripts/wiki/mock-services.py'
    output=WIKI/'images/features'; output.mkdir(parents=True,exist_ok=True)
    commands='''set -eu
mkdir -p /doc-system
for name in slot-sharing-ui slot-ssh-ui slot-diagnostics-ui slot-ota-ui; do cp /docs-fixtures/mock-services.py /doc-system/$name; done
ln -s /doc-core/mgba_libretro.so /doc-system/mgba_libretro.so
for name in nmcli slot-usb-network slot-usb-storage slot-sd-library; do cp /docs-fixtures/mock-services.py /usr/bin/$name; chmod 755 /usr/bin/$name; done
export SLOT_CORE_DIR=/doc-system WIKI_LIBRARY=/library LIBGL_ALWAYS_SOFTWARE=1 SDL_AUDIODRIVER=dummy
cargo build --locked -p slot --no-default-features --features rg353v --example wiki_guide
xvfb-run -a -s '-screen 0 640x480x24' /target/debug/examples/wiki_guide /captures
'''
    try:
        subprocess.run(['docker','run','--rm','--init','--platform','linux/arm64',
            '-v',str(source)+':/src', '-v',str(target)+':/target',
            '-v',str(library)+':/library:ro', '-v',str(core)+':/doc-core/mgba_libretro.so:ro',
            '-v','slot-rg353v-cargo:/usr/local/cargo/registry',
            '-v','slot-rg353v-cargo-git:/usr/local/cargo/git',
            '-v',str(fixture.parent)+':/docs-fixtures:ro', '-v',str(output)+':/captures',
            *(['-e','WIKI_ONLY_OTA=1'] if only_ota else []),
            '-w','/src','-e','RUSTUP_TOOLCHAIN=1.96.1','-e','CARGO_TARGET_DIR=/target',
            '--entrypoint','sh',container,'-c',commands],check=True)
    finally:
        if example.exists() and example.read_bytes()==example_bytes: example.unlink()
    # The Rust PNG writer favours speed. Re-encode losslessly for repository size.
    for path in output.glob('*.png'):
        with Image.open(path) as image:
            original=image.tobytes(); mode=image.mode
            image.save(path,optimize=True,compress_level=9)
        with Image.open(path) as image:
            assert image.mode==mode and image.tobytes()==original


def boot():
    # Replay one captured run; never invent intermediate values or force a total.
    from wiki.boot_timing import load_timing, quantized_events
    timing=load_timing(ROOT)
    frames=[]
    with tempfile.TemporaryDirectory(prefix='splash-',dir=WORK) as temporary:
        executable=Path(temporary)/'splash'
        subprocess.run(['cc','-O2','-o',str(executable),str(ROOT/'ports/rg353v/rocknix/slot-bootsplash/src/slot-splash.c'),'-lm','-pthread'],check=True)
        images={'black':Image.new('RGB',(640,480)),
                'shelf':Image.open(WIKI/'images/features/shelf.png').convert('RGB')}
        for event,duration in quantized_events(timing):
            key=event.get('percent',event['view'])
            if key not in images:
                ppm=Path(temporary)/'frame.ppm'
                subprocess.run([str(executable),'--ppm',str(key),str(ppm)],check=True)
                images[key]=Image.open(ppm).convert('RGB').copy()
            frames.append((images[key],duration))
        save_animation('boot-to-shelf',frames,fps=60)


def tour():
    names=['shelf','favorites','settings','screen-gba','game-zelda',
           'game-metroid-fusion','game-golden-sun-battle','pause','states',
           'wifi','file-sharing','usb-network','usb-storage-connected',
           'gallery-grid-date','gallery-grid-platform','gallery-image',
           'gallery-image-hidden','gallery-delete','features-in-game']
    frames=[(Image.open(WIKI/'images/features'/(name+'.png')).convert('RGB'),
             1800 if name.startswith('game-') else 1200) for name in names]
    save_animation('feature-tour',frames)


def manifest():
    files={}
    for directory in (WIKI/'images',WIKI/'media'):
        for path in sorted(directory.rglob('*')):
            if path.suffix not in ('.png','.gif','.mp4'):continue
            row={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
            if path.suffix!='.mp4':
                with Image.open(path) as im:
                    assert im.size==(640,480),(path,im.size)
                    row['width'],row['height']=im.size
                    if path.suffix=='.gif':
                        duration=0
                        for i in range(im.n_frames):im.seek(i);duration+=im.info.get('duration',0)
                        row.update(frames=im.n_frames,duration_ms=duration)
            files[str(path.relative_to(WIKI))]=row
    lock=json.loads((ROOT/'ports/rg353v/upstreams.lock.json').read_text())
    (WIKI/'media/manifest.json').write_text(json.dumps({'schema':1,'resolution':[640,480],
        'provenance':'Native installer/frontend renders with read-only owner game/art sources, isolated progress and example service responses; not live device recordings. No ROMs, saves or library files are included.',
        'boot_animation':{'kind':'Captured presentation-timing replay; reconstructed pixels, not camera footage or a performance benchmark.',
            'timing_file':'media/boot-timing.json',
            'timing_sha256':hashlib.sha256((WIKI/'media/boot-timing.json').read_bytes()).hexdigest(),
            'mp4_fps':60},
        'setup_animation':'Demonstration; installation progress is condensed and not a speed measurement.',
        'gba_picture':'Perfect overlay with Shimmerless; third-party copyright and no-license-specified notices are recorded in CREDITS.md.',
        'render_inputs':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'scripts/render-rg353v-wiki.py','scripts/wiki/boot_timing.py',
            'scripts/wiki/frontend.rs','scripts/wiki/mock-services.py',
            'ports/rg353v/image/slot-setup-ui.py','ports/rg353v/image/slot-setup-font.json.gz',
            'ports/rg353v/modules/catalog-v1.json')},
        'source':lock,'files':files},indent=2)+'\n')
    print(f'Validated {len(files)} media assets at native resolution.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['setup','frontend','boot','tour','manifest','all'])
    p.add_argument('--only-ota',action='store_true',help='For frontend: refresh only OTA states and their shelf backdrop')
    p.add_argument('--source',type=Path,help='Prepared pinned Slot workspace for native frontend captures')
    p.add_argument('--target',type=Path,default=WORK/'target')
    p.add_argument('--container',default='slot-rg353v-dev:rust-1.96.1',help='ARM64 image built from ports/rg353v/Dockerfile')
    p.add_argument('--library',type=Path,help='Private game/art source; mounted read-only, never bundled')
    p.add_argument('--core',type=Path,help='Qualified ARM64 mgba_libretro.so; mounted read-only')
    args=p.parse_args(); WORK.mkdir(parents=True,exist_ok=True)
    if args.command in ('frontend','all') and not args.source:p.error('--source is required')
    if args.command in ('frontend','all') and (not args.library or not args.core):p.error('--library and --core are required; no placeholder-game captures')
    if args.command in ('setup','all'): print('Setup images:',setup())
    if args.command in ('frontend','all'):frontend(args.source,args.target,args.container,args.library,args.core,args.only_ota)
    if args.command in ('boot','all'):boot()
    if args.command in ('tour','all'):tour()
    manifest()


if __name__=='__main__':main()
