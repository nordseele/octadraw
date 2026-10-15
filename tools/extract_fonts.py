#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""Turn the eight pixel fonts of your own Octatrack OS file into BDF fonts for OctaDraw.

    python3 tools/extract_fonts.py OCTATRACK_OS1.40C.syx [folder]

The input is the OS update you downloaded (.syx), or an OS image you already unpacked from it
(raw, loaded as is). The fonts are found by the shape of their records, not at fixed addresses,
and written as os-font-1.bdf … os-font-8.bdf (in the order the OS lists them) to `folder`,
by default OctaDraw's user font folder (OCTADRAW_FONTS, else <OCTADRAW_HOME or ./work>/fonts).

This script contains no byte of any firmware. The BDF files it writes are made from your copy of
the OS: keep them for your own use and never redistribute them.
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui_fontbook as FB  # noqa: E402

NOTICE = ('Made by extract_fonts.py from your own copy of the Octatrack OS. '
          'Not a free font: for your own use only, do not redistribute.')
SYSEX_ID, DATA, END = b'\x00\x20\x3c\x05\x00', 0x7e, 0x7f
CODES = range(32, 127)   # shortcut: printable ASCII only (what OctaDraw slots draw); widen if icons are wanted


def nibbles(b):
    assert all(v < 16 for v in b), 'SysEx header is not nibbles'
    return int(''.join(f'{v:x}' for v in b), 16)


def unseven(data, msb_first):
    """SysEx 7-bit packing: each group is one byte of high bits, then up to seven data bytes."""
    out = bytearray()
    for g in range(0, len(data), 8):
        top, rest = data[g], data[g + 1:g + 8]
        out += bytes(v | (top >> (6 - i if msb_first else i) & 1) << 7 for i, v in enumerate(rest))
    return bytes(out)


def packet_sum(offset, data):
    hi, mid, lo = offset >> 16 & 0xff, offset >> 8 & 0xff, offset & 0xff
    return ((hi & 7) + (mid & 15) + (lo & 15) + ((mid >> 4) + (lo >> 4) << 4) + sum(data)) & 0xff


def from_syx(raw):
    """SysEx dump -> the container it carries (checksummed, contiguous packets)."""
    out, size, start = bytearray(), None, None
    for msg in re.findall(rb'\xf0([\x00-\x7f]*)\xf7', raw):
        if not msg.startswith(SYSEX_ID) or len(msg) < 6:
            continue
        cmd, body = msg[5], msg[6:]
        if cmd == DATA and body:
            check, offset = nibbles(body[:2]), nibbles(body[2:8])
            start = offset if start is None else start
            assert offset == start + len(out), f'packet at {offset:#x} is out of order'
            data = unseven(body[8:], True)
            if packet_sum(offset, data) != check:
                data = unseven(body[8:], False)
                assert packet_sum(offset, data) == check, f'bad checksum in packet at {offset:#x}'
            out += data
        elif cmd == END:
            size = nibbles(body[:6])
    assert out and size == len(out), 'no complete OS update found in this SysEx file'
    return bytes(out)


def unpack(box):
    """Container: 26-byte header (magic, ..., packed length, byte sum), then the packed OS."""
    assert box[:4] == b'ELEK', 'unknown container'
    n, total = int.from_bytes(box[18:22], 'big'), int.from_bytes(box[22:26], 'big')
    packed = box[26:26 + n]
    assert len(packed) == n and sum(packed) & 0xffffffff == total, 'container checksum differs'
    return depack(packed)


def depack(src):
    """The LZ77 variant (aPLib family) the OS update uses: tag bits MSB first, 1 = literal."""
    out, pos, tag, left, last = bytearray(), 0, 0, 0, 1

    def byte():
        nonlocal pos
        pos += 1
        return src[pos - 1]

    def bit():
        nonlocal tag, left
        if not left:
            tag, left = byte(), 8
        left -= 1
        return tag >> left & 1

    def gamma():
        v = 1
        while True:
            v = v * 2 + bit()
            if bit():
                return v

    while True:
        if bit():
            out.append(byte())
            continue
        g = gamma()
        if g != 2:
            raw = (g * 256 + byte() - 0x300) & 0xffffffff
            if raw == 0xffffffff:
                return bytes(out)
            last = raw + 1
        length = bit() << 1 | bit() or gamma() + 2
        length += (last > 0xd00) + 1
        assert 0 < last <= len(out), 'corrupt packed OS'
        for _ in range(length):
            out.append(out[-last])


def u32(img, at):
    return int.from_bytes(img[at:at + 4], 'big')


def find_table(img):
    """Eight consecutive 20-byte font records: default advance, (lift << 16) | rows, then pointers to
    a width per code (256 bytes, maybe padded), an offset per code (256 signed words), the glyph columns."""
    def record(at):
        adv, rows, widths, offsets, columns = (u32(img, at + 4 * i) for i in range(5))
        return (columns - offsets == 512 and offsets - widths in (256, 257) and offsets % 2 == 0
                and 0 < adv < 32 and 0 < rows & 0xffff <= 16 and rows >> 16 < 16)
    hits = [at for at in range(0, len(img) - 20, 2) if record(at)]
    starts = [at for at in hits if at - 20 not in hits]
    runs = [at for at in starts if all(at + 20 * i in hits for i in range(8)) and at + 160 not in hits]
    if len(runs) != 1:
        sys.exit(f'Font table not found ({len(runs)} candidates): is this an Octatrack OS file?')
    return runs[0]


def load_address(img, table):
    """The OS refers to its font records by absolute address: the load address is the one that
    turns the most stored longs into a record's address."""
    pointers = [u32(img, table + 20 * i + o) for i in range(8) for o in (8, 12, 16)]
    low, high = max(pointers) - len(img) + 1, min(pointers)     # every pointer must land in the image
    longs = Counter(u32(img, at) for at in range(0, len(img) - 3, 2))
    bases = {value - table - 20 * i for i in range(8) for value in longs if low <= value - table - 20 * i <= high}
    assert bases, 'no reference to the font records'
    return max(bases, key=lambda b: sum(longs[b + table + 20 * i] for i in range(8)))


def fonts(img):
    table = find_table(img)
    base = load_address(img, table)
    for i in range(8):
        adv, rows, widths, offsets, columns = (u32(img, table + 20 * i + 4 * j) for j in range(5))
        widths, offsets, columns = widths - base, offsets - base, columns - base
        lift, step = rows >> 16, 2 if rows & 0xffff > 8 else 1   # one byte per column up to 8 rows, else a word
        font = {}
        for c in CODES:
            offset = int.from_bytes(img[offsets + 2 * c:offsets + 2 * c + 2], 'big', signed=True)
            if offset < 0:                         # absent: drawn as nothing, measured as nothing
                font[c] = dict(ink=[], wid=0, adv=0)
                continue
            w = int.from_bytes(img[widths + c:widths + c + 1], 'big', signed=True)
            at, ink = columns + offset, []
            for x in range(w):                     # a column's top bit is its bottom row, `lift` rows under the baseline
                bits = int.from_bytes(img[at + x * step:at + (x + 1) * step], 'big')
                ink += [(x, lift - k) for k in range(8 * step) if bits >> (8 * step - 1 - k) & 1]
            font[c] = dict(ink=sorted(ink, key=lambda p: (p[1], p[0])), wid=w or adv, adv=w + 1)
        yield font


def read_os(path):
    raw = Path(path).read_bytes()
    if raw[:1] == b'\xf0':
        return unpack(from_syx(raw))
    if raw[:4] == b'ELUP':
        sys.exit('This .bin is the card update format: give the .syx from the same download instead.')
    return raw


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    folder = Path(sys.argv[2]) if len(sys.argv) == 3 else FB.USER
    folder.mkdir(parents=True, exist_ok=True)
    for n, font in enumerate(fonts(read_os(sys.argv[1])), 1):
        path = folder / f'os-font-{n}.bdf'
        path.write_text(FB.write_bdf(font, f'os-font-{n}', NOTICE), encoding='latin-1')
        print(f'{path}: {sum(1 for g in font.values() if g["adv"])} glyphs')
    print('These fonts come from your OS file: do not redistribute them.')


if __name__ == '__main__':
    main()
