#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""ColdFire proof: the generated code draws, pixel for pixel, what the editor draws. No firmware involved.

    python3 tests/bench_m68k.py                 # needs m68k-elf-as/ld/objcopy/nm (binutils) and `pip install unicorn`

1. Static: every screen of every examples/*/project.json is assembled (-mcpu=5407), run in Unicorn on a
   128 x 64 surface in RAM, and compared with the Python render of the same screen (runtime slots and reserved
   zones left out: the host draws those).
2. Runtime: examples/demo/demo.S fills the demo's slots with live strings (selection, case, alignment, a string
   longer than its box) and the result is compared with the editor's render of the same values.
3. Slot edge cases (tests/slots): ui_draw_text called directly on boxes smaller than the font, centred, lower
   case, transparent over a pattern, custom space advance, a 6x13 font with a wider highlight.
Each call must preserve d2-d7/a2-a6 and the stack.
"""
from copy import deepcopy
import json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import ui_codegen as G                      # noqa: E402
import ui_components as C                   # noqa: E402

ORG, RAM, RET, STACK = 0x10000, 0x200000, 0x300000, 0x3f0000
SURFACE, BITS, MASK, STRINGS, STATE = RAM, RAM + 0x1000, RAM + 0x2000, RAM + 0x3000, RAM + 0x4000
STRIDE = 2                                  # longs per column: 64 rows / 32
MARKS = {r: 0x11111111 * i for i, r in enumerate(('D2', 'D3', 'D4', 'D5', 'D6', 'D7', 'A2', 'A4', 'A5', 'A6'), 2)}


def build(sources):
    """Assemble and link the sources at ORG -> (image bytes, {global symbol: address})."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d); objects = []
        for i, text in enumerate(sources):
            (d / f'{i}.s').write_text(text)
            subprocess.run(['m68k-elf-as', '-mcpu=5407', '-o', str(d / f'{i}.o'), str(d / f'{i}.s')], check=True)
            objects.append(str(d / f'{i}.o'))
        subprocess.run(['m68k-elf-ld', f'-Ttext=0x{ORG:x}', '-e', '0', '-o', str(d / 'a.elf'), *objects], check=True)
        subprocess.run(['m68k-elf-objcopy', '-O', 'binary', str(d / 'a.elf'), str(d / 'a.bin')], check=True)
        names = subprocess.run(['m68k-elf-nm', str(d / 'a.elf')], capture_output=True, text=True, check=True).stdout
        symbols = {n: int(a, 16) for a, kind, n in (line.split() for line in names.splitlines() if len(line.split()) == 3) if kind in 'TtDd'}
        return (d / 'a.bin').read_bytes(), symbols


class Machine:
    def __init__(self, image):
        from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
        import unicorn.m68k_const as K
        self.K, self.uc = K, Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.uc.mem_map(0, 0x400000)
        self.uc.mem_write(ORG, image)
        self.uc.reg_write(K.UC_M68K_REG_SR, 0x2700)      # supervisor before the first stack write
        self.uc.mem_write(SURFACE, b''.join(v.to_bytes(4, 'big') for v in (128, 64, STRIDE, BITS, MASK)))

    def call(self, entry, a0=0, a1=0, d0=0, clear=True):
        K, uc = self.K, self.uc
        if clear:
            uc.mem_write(BITS, bytes(128 * STRIDE * 4)); uc.mem_write(MASK, bytes(128 * STRIDE * 4))
        for r, v in MARKS.items():
            uc.reg_write(getattr(K, f'UC_M68K_REG_{r}'), v)
        uc.reg_write(K.UC_M68K_REG_A3, SURFACE); uc.reg_write(K.UC_M68K_REG_A0, a0)
        uc.reg_write(K.UC_M68K_REG_A1, a1); uc.reg_write(K.UC_M68K_REG_D0, d0)
        uc.mem_write(STACK - 4, RET.to_bytes(4, 'big')); uc.reg_write(K.UC_M68K_REG_A7, STACK - 4)
        uc.emu_start(entry, RET, count=50_000_000)
        bad = [r for r, v in MARKS.items() if uc.reg_read(getattr(K, f'UC_M68K_REG_{r}')) != v]
        assert not bad and uc.reg_read(K.UC_M68K_REG_A3) == SURFACE, f'registers not preserved: {bad}'
        assert uc.reg_read(K.UC_M68K_REG_A7) == STACK, 'stack not balanced'
        return self.lit_pixels()

    def lit_pixels(self):
        bits = self.uc.mem_read(BITS, 128 * STRIDE * 4)
        def lit(x, row):
            up = 63 - row; i = (x * STRIDE + (up >> 5)) * 4
            return int.from_bytes(bits[i:i + 4], 'big') >> (31 - (up & 31)) & 1
        return bytes(lit(x, row) for row in range(64) for x in range(128))

    def strings(self, values):
        out, at = [], STRINGS
        for v in values:
            self.uc.mem_write(at, v.encode('ascii') + b'\0'); out.append(at); at += len(v) + 1
        return out


def expected(doc, page):
    """Lit pixels of the editor's device render: 1 = lit (drawn black)."""
    image, _ = C.render(doc, page)
    return bytes(1 if v == 0 else 0 for v in image.tobytes())


def compare(got, want, what):
    diff = [(i % 128, i // 128) for i in range(len(want)) if got[i] != want[i]]
    assert not diff, f'{what}: {len(diff)} pixel(s) differ, first {diff[:6]}'


def static_proof():
    checked = 0
    for path in sorted((HERE / 'examples').glob('*/project.json')):
        doc = json.loads(path.read_text()); source, _ = G.generate(doc)
        image, symbols = build([source]); machine = Machine(image)
        static = deepcopy(doc)
        for page in static['pages']:
            for c in page['components']:
                if G.is_slot(c) or c['type'] == 'placeholder': c['device'] = False   # host-drawn areas
        for i in range(len(doc['pages'])):
            compare(machine.call(symbols[f'ui_page_{i + 1}']), expected(static, i), f'{path.parent.name} screen {i + 1}')
            checked += 1
    return checked


def runtime_proof():
    folder = HERE / 'examples/demo'
    doc = json.loads((folder / 'project.json').read_text()); source, _ = G.generate(doc)
    image, symbols = build([source, (folder / 'demo.S').read_text()]); machine = Machine(image)
    states = [
        ('list demo', 0, ['Kick', 'Snare', 'Hat', 'Clap'], ['100', '64', '7', '0']),
        ('Mixed Case ~', 2, ['A very long sample name', '', 'x', 'WWWWWWWWWWWWWW'], ['-12dB', '', '127', 'OFF']),
        ('', 9, ['one', 'two', 'three', 'four'], ['1', '2', '3', '4']),
        ('Selected last', 3, ['a', 'b', 'c', 'Last row'], ['', '', '', 'ON']),
    ]
    for title, selected, names, values in states:
        pointers = machine.strings([title, *names, *values])
        machine.uc.mem_write(STATE, b''.join(v.to_bytes(4, 'big') for v in (pointers[0], selected, *pointers[1:])))
        got = machine.call(symbols['demo_list_draw'], STATE)
        want = deepcopy(doc); layers = {c['id']: c for c in want['pages'][0]['components']}
        layers['title']['text'] = title
        for i in range(4):
            layers[f'name{i + 1}']['text'], layers[f'value{i + 1}']['text'] = names[i], values[i]
            if i == selected:
                layers[f'name{i + 1}'].update(selectable=True, focus_state='selected')
        compare(got, expected(want, 0), f'demo state {title!r}')
    return len(states)


def slot_proof():
    doc = json.loads((HERE / 'tests/slots/project.json').read_text()); source, meta = G.generate(doc)
    image, symbols = build([source]); machine = Machine(image)
    cases = [dict(clip='Clipped Box', tiny='Truncated here', centre='MiXeD', space='a b  c', big='Big 42', last='Last row'),
             dict(clip='', tiny='ok', centre='Centre text too long for it', space='no', big='W', last=' spaces ')]
    count = 0
    for texts in cases:
        for selected in (None, *texts):
            pointers = dict(zip(texts, machine.strings(list(texts.values()))))
            machine.call(symbols['ui_page_1'])
            for slot in meta[0]['slots']:
                key = slot['id']
                machine.call(symbols['ui_draw_text'], pointers[key], symbols[slot['symbol']], 2 | (key == selected), clear=False)
            got = machine.lit_pixels()
            want = deepcopy(doc); layers = {c['id']: c for c in want['pages'][0]['components']}
            for key, text in texts.items():
                layers[key]['text'] = text
                if key == selected: layers[key].update(selectable=True, focus_state='selected')
            compare(got, expected(want, 0), f'slots {texts} selected {selected}')
            count += 1
    return count


if __name__ == '__main__':
    print(f'PASS static: {static_proof()} screens identical to the editor')
    print(f'PASS runtime: {runtime_proof()} demo states identical to the editor')
    print(f'PASS slots: {slot_proof()} edge-case states identical to the editor')
