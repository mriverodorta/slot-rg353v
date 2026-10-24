#!/usr/bin/env python3
"""Create our original GBA color-pattern diagnostic; no commercial ROM/BIOS data."""
from pathlib import Path
import struct
import sys

# ARM program: enable mode 3/BG2, paint 38400 16-bit pixels, wait for a full
# VBlank boundary, and repeat with an advancing color counter.
code = [
    0xE3A00404, 0xE3A01C04, 0xE3811003, 0xE5801000,
    0xE3A02406, 0xE3A03000, 0xE3A04C96,
    0xE0C230B2, 0xE2833001, 0xE2544001, 0x1AFFFFFB,
    0xE1D050B6, 0xE35500A0, 0x1AFFFFFC,
    0xE1D050B6, 0xE35500A0, 0x0AFFFFFC,
    0xE3A02406, 0xE3A04C96, 0xEAFFFFF2,
]
rom = bytearray(0x8000)
struct.pack_into("<I", rom, 0, 0xEA00002E)
rom[0xA0:0xAC] = b"SLOT TEST\0\0\0"
rom[0xAC:0xB0] = b"SLTE"
rom[0xB0:0xB2] = b"00"
rom[0xB2] = 0x96
rom[0xBD] = (-sum(rom[0xA0:0xBD]) - 0x19) & 255
for index, word in enumerate(code):
    struct.pack_into("<I", rom, 0xC0 + index * 4, word)
destination = Path(sys.argv[1] if len(sys.argv) > 1 else "local-logs/Slot Diagnostic.gba")
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(rom)
print(destination)
