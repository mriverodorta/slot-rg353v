#!/usr/bin/env python3
"""Run on RG353V: isolated original GB/GBC/GBA fixtures against installed cores.

No games, settings or saves in the content partition are opened. This tests the
libretro API on real hardware, not Slot's frontend save pipeline or display FPS.
Each core/fixture runs in a separate bounded subprocess and private tempdir.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time


def fixture(platform):
    rom = bytearray(32768)
    if platform == 'GBA':
        struct.pack_into('<I', rom, 0, 0xea00002e)
        rom[0xa0:0xac] = b'SLOT TEST\0\0\0'
        rom[0xac:0xb0] = b'SLTE'
        rom[0xb0:0xb2] = b'00'
        rom[0xb2] = 0x96
        rom[0xbd] = (-sum(rom[0xa0:0xbd])-0x19) & 255
        # Original ARM program: SRAM marker, mode-3 colour counter at VBlank.
        code = [0xe3a0040e, 0xe3a0105a, 0xe5c01000,
                0xe3a00404, 0xe3a01c04, 0xe3811003, 0xe5801000,
                0xe3a02406, 0xe3a03000, 0xe1d040b6, 0xe35400a0,
                0x1afffffc, 0xe2833001, 0xe1c230b0, 0xe1d040b6,
                0xe35400a0, 0x0afffffc, 0xeafffff6]
        for i, word in enumerate(code):
            struct.pack_into('<I', rom, 0xc0 + i*4, word)
        rom[0x200:0x209] = b'SRAM_V113'
    else:
        rom[0x100:0x104] = bytes([0, 0xc3, 0x50, 0x01])
        rom[0x104:0x108] = bytes([0xce, 0xed, 0x66, 0x66])
        rom[0x134:0x13e] = b'SLOT PROBE'
        rom[0x143] = 0x80 if platform == 'GBC' else 0
        rom[0x147] = 0x1b if platform == 'GBC' else 0x06
        rom[0x149] = 0x02 if platform == 'GBC' else 0
        program = bytes([0x3e, 0x0a, 0xea, 0, 0, 0x3e, 0x05,
                         0xea, 0, 0xa0, 0x3e, 0x06, 0xea, 1, 0xa0, 0x18, 0xfe])
        rom[0x150:0x150+len(program)] = program
        rom[0x14d] = (-sum(rom[0x134:0x14d])-len(rom[0x134:0x14d])) & 255
    return bytes(rom)


class Game(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p),
                ('size', C.c_size_t), ('meta', C.c_char_p)]


def run(core_path, platform, workspace=None):
    with tempfile.TemporaryDirectory(prefix='slot-core-probe-', dir=workspace) as directory:
        root = Path(directory)
        rom = root / ('probe.' + platform.lower())
        rom.write_bytes(fixture(platform))
        lib = C.CDLL(str(core_path))
        keep = []
        frame = {'hash': None, 'size': None, 'bpp': 2, 'count': 0}
        options = {b'mgba_skip_bios': b'ON', b'mgba_frameskip': b'disabled'}
        directory_bytes = str(root).encode()

        def environment(cmd, data):
            if cmd == 10:  # SET_PIXEL_FORMAT
                frame['bpp'] = 4 if C.cast(data, C.POINTER(C.c_int))[0] == 1 else 2
                return True
            if cmd in (3, 15):  # GET_CAN_DUPE, GET_VARIABLE
                if cmd == 3:
                    C.cast(data, C.POINTER(C.c_bool))[0] = True
                    return True
                fields = C.cast(data, C.POINTER(C.c_char_p))
                value = options.get(fields[0])
                fields[1] = value
                return value is not None
            if cmd == 17:  # GET_VARIABLE_UPDATE
                C.cast(data, C.POINTER(C.c_bool))[0] = False
                return True
            if cmd in (9, 30, 31):  # directories remain private
                C.cast(data, C.POINTER(C.c_char_p))[0] = directory_bytes
                return True
            return cmd in (11, 16, 18, 35, 36, 37, 51)

        def video(data, width, height, pitch):
            if data:
                h = hashlib.sha256()
                for y in range(height):
                    h.update(C.string_at(data + y*pitch, width*frame['bpp']))
                frame.update(hash=h.hexdigest(), size=[width, height])
            frame['count'] += 1

        callbacks = [
            ('retro_set_environment', C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p), environment),
            ('retro_set_video_refresh', C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t), video),
            ('retro_set_audio_sample', C.CFUNCTYPE(None, C.c_int16, C.c_int16), lambda l, r: None),
            ('retro_set_audio_sample_batch', C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t), lambda p, n: n),
            ('retro_set_input_poll', C.CFUNCTYPE(None), lambda: None),
            ('retro_set_input_state', C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint), lambda *a: 0),
        ]
        for name, kind, callback in callbacks:
            value = kind(callback)
            keep.append(value)
            getattr(lib, name).argtypes = [kind]
            getattr(lib, name)(value)
        lib.retro_load_game.argtypes = [C.POINTER(Game)]
        lib.retro_load_game.restype = C.c_bool
        lib.retro_get_memory_size.argtypes = [C.c_uint]
        lib.retro_get_memory_size.restype = C.c_size_t
        lib.retro_get_memory_data.argtypes = [C.c_uint]
        lib.retro_get_memory_data.restype = C.c_void_p
        lib.retro_serialize_size.restype = C.c_size_t
        for name in ['retro_serialize', 'retro_unserialize']:
            getattr(lib, name).argtypes = [C.c_void_p, C.c_size_t]
            getattr(lib, name).restype = C.c_bool
        data = C.create_string_buffer(rom.read_bytes())
        game = Game(str(rom).encode(), C.cast(data, C.c_void_p), len(data)-1, None)
        loaded = False
        lib.retro_init()
        try:
            assert lib.retro_load_game(C.byref(game)), 'ROM load failed'
            loaded = True
            for _ in range(120): lib.retro_run()
            expected_size = [240, 160] if platform == 'GBA' else [160, 144]
            assert frame['size'] == expected_size, frame
            size = lib.retro_get_memory_size(0)
            pointer = lib.retro_get_memory_data(0)
            assert pointer and size, 'No battery RAM'
            saved = C.string_at(pointer, size)
            expected_marker = b'\x5a' if platform == 'GBA' else (b'\x65' if platform == 'GB' else b'\x05\x06')
            assert saved.startswith(expected_marker), (platform, saved[:8].hex())
            (root/'probe.sav').write_bytes(saved)
            state_size = lib.retro_serialize_size()
            assert 0 < state_size < 16*1024*1024, state_size
            state = C.create_string_buffer(state_size)
            assert lib.retro_serialize(state, state_size)
            before_advance = frame['hash']
            for _ in range(20): lib.retro_run()
            expected_frame = frame['hash']
            if platform == 'GBA':
                assert expected_frame != before_advance, 'GBA colour counter did not advance'
            assert lib.retro_unserialize(state, state_size)
            for _ in range(20): lib.retro_run()
            assert frame['hash'] == expected_frame, 'State replay differs'
            lib.retro_unload_game()
            loaded = False
            assert lib.retro_load_game(C.byref(game)), 'Fresh load failed'
            loaded = True
            # GBA save type autodetection is deferred until the program touches
            # SRAM. A successful load alone does not promise a populated region.
            for _ in range(120): lib.retro_run()
            pointer = lib.retro_get_memory_data(0)
            assert pointer and lib.retro_get_memory_size(0) == size
            C.memset(pointer, 0xa5, size)
            C.memmove(pointer, (root/'probe.sav').read_bytes(), size)
            assert C.string_at(pointer, size) == saved, 'SRAM restore differs'
            return {'platform': platform, 'core': core_path.name,
                    'core_sha256': hashlib.sha256(core_path.read_bytes()).hexdigest(),
                    'video_size': expected_size, 'state_bytes': state_size,
                    'sram_bytes': size, 'marker': expected_marker.hex(),
                    'state_replay': True, 'fresh_load_sram_restore': True, 'passed': True}
        finally:
            if loaded: lib.retro_unload_game()
            lib.retro_deinit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core_directory', type=Path)
    parser.add_argument('--child', choices=['GB', 'GBC', 'GBA'])
    parser.add_argument('--core', choices=['mgba', 'gpsp'])
    parser.add_argument('--workspace', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if not args.core: parser.error('--child requires --core')
        start = time.monotonic()
        result = run((args.core_directory/(args.core+'_libretro.so')).resolve(), args.child, args.workspace)
        result['elapsed_seconds'] = time.monotonic()-start
        print('RESULT '+json.dumps(result), flush=True)
        return
    with tempfile.TemporaryDirectory(prefix='slot-core-batch-') as workspace:
        for core, platform in [('mgba','GB'), ('mgba','GBC'), ('mgba','GBA'), ('gpsp','GBA')]:
            result = subprocess.run([sys.executable, __file__, str(args.core_directory),
                                     '--child', platform, '--core', core, '--workspace', workspace],
                                    capture_output=True, text=True, timeout=90)
            lines = [line[7:] for line in result.stdout.splitlines() if line.startswith('RESULT ')]
            if result.returncode or not lines:
                print(json.dumps({'core': core, 'platform': platform, 'passed': False,
                                  'exit': result.returncode, 'output': (result.stdout+result.stderr)[-4000:]}), flush=True)
                raise SystemExit(1)
            print(lines[-1], flush=True)


if __name__ == '__main__':
    main()
