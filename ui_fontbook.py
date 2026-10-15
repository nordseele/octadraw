# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""Pixel fonts for the editor and the code generator.

A font is {code: {'ink': [(x, y)…], 'wid': ink width, 'adv': advance}}, y = 0 on the
baseline and negative above it. Two sources, in this order:
- free: BDF files bundled in fonts/ (licences in fonts/README.md);
- user: BDF files in the user font folder (OCTADRAW_FONTS, default <work folder>/fonts/),
  added by hand or by importing a BDF / TTF / OTF.
A key that is not loaded falls back to DEFAULT, so a project stays readable.
"""
import io
import os
import re
from pathlib import Path

BUNDLED = Path(__file__).with_name('fonts')
USER = Path(os.environ.get('OCTADRAW_FONTS') or Path(os.environ.get('OCTADRAW_HOME') or Path(__file__).resolve().with_name('work')) / 'fonts')
MAX_GLYPHS, MAX_SIZE = 4096, 64


class Fonts(dict):
    def __missing__(self, key):
        return dict.__getitem__(self, DEFAULT)


FONTS = Fonts(); SOURCE = {}; INFO = {}; DEFAULT = 'fixed-5x7'; _METRICS = {}


def parse_bdf(text):
    """BDF text -> (font, info). Raises ValueError on anything malformed."""
    font, info, glyph, rows = {}, {}, None, None
    for line in text.splitlines():
        word, _, rest = line.strip().partition(' ')
        if rows is not None and word != 'ENDCHAR':
            rows.append(word); continue
        if word in ('FAMILY_NAME', 'COPYRIGHT', 'FONT') and word not in info:
            info[word] = rest.strip().strip('"')
        elif word == 'STARTCHAR':
            glyph = dict(code=None, adv=None, bbx=None)
        elif glyph is None:
            continue
        elif word == 'ENCODING':
            glyph['code'] = int(rest.split()[0])
        elif word == 'DWIDTH':
            glyph['adv'] = int(rest.split()[0])
        elif word == 'BBX':
            glyph['bbx'] = [int(v) for v in rest.split()[:4]]
        elif word == 'BITMAP':
            rows = []
        elif word == 'ENDCHAR':
            code, bbx = glyph['code'], glyph['bbx']
            if code is not None and 32 <= code <= 0xffff and bbx and rows is not None:
                w, h, xoff, yoff = bbx
                if not (0 <= w <= MAX_SIZE and 0 <= h <= MAX_SIZE and abs(xoff) <= MAX_SIZE and abs(yoff) <= MAX_SIZE):
                    raise ValueError(f'Glyph U+{code:04X} is larger than {MAX_SIZE} px')
                ink = []
                for r, hexrow in enumerate(rows[:h]):
                    bits = int(hexrow or '0', 16); total = len(hexrow) * 4
                    ink += [(xoff + c, -(yoff + h - 1 - r)) for c in range(w) if total > c and bits >> (total - 1 - c) & 1]
                adv = glyph['adv'] if glyph['adv'] is not None else w + xoff
                font[code] = dict(ink=ink, wid=max((x + 1 for x, _ in ink), default=max(0, adv - 1)), adv=adv)
            glyph, rows = None, None
    if not any(g['ink'] for g in font.values()):
        raise ValueError('No glyph found in this BDF file')
    if len(font) > MAX_GLYPHS:
        raise ValueError(f'More than {MAX_GLYPHS} glyphs')
    return font, info


def write_bdf(font, name, copyright=''):
    ink = [p for g in font.values() for p in g['ink']] or [(0, 0)]
    ascent, descent = max(1, -min(y for _, y in ink) + 1), max(0, max(y for _, y in ink))
    width = max(max((x for x, _ in g['ink']), default=0) + 1 for g in font.values())
    lines = ['STARTFONT 2.1', f'FONT {name}', f'SIZE {ascent + descent} 75 75',
             f'FONTBOUNDINGBOX {width} {ascent + descent} 0 {-descent}',
             'STARTPROPERTIES 3', f'FONT_ASCENT {ascent}', f'FONT_DESCENT {descent}',
             'COPYRIGHT "' + copyright.replace('"', "'") + '"', 'ENDPROPERTIES', f'CHARS {len(font)}']
    for code in sorted(font):
        g = font[code]
        lines += [f'STARTCHAR U+{code:04X}', f'ENCODING {code}', 'SWIDTH 500 0', f"DWIDTH {g['adv']} 0"]
        if not g['ink']:
            lines += ['BBX 0 0 0 0', 'BITMAP', 'ENDCHAR']; continue
        xs, ys = zip(*g['ink']); left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        w, h = right - left + 1, bottom - top + 1; digits = (w + 7) // 8 * 2; rows = [0] * h
        for x, y in g['ink']:
            rows[y - top] |= 1 << (digits * 4 - 1 - (x - left))
        lines += [f'BBX {w} {h} {left} {-bottom}', 'BITMAP', *(f'{r:0{digits}X}' for r in rows), 'ENDCHAR']
    return '\n'.join(lines + ['ENDFONT', ''])


def rasterize(data, size, variation=None):
    """TTF / OTF bytes -> 1-bit font at `size` px (FreeType monochrome rendering)."""
    from PIL import ImageFont
    if not 4 <= size <= MAX_SIZE:
        raise ValueError(f'Size must be 4..{MAX_SIZE} px')
    face = ImageFont.truetype(io.BytesIO(data), size)
    try: face.set_variation_by_name(variation or 'Regular')   # variable fonts: Regular unless asked
    except Exception: pass
    ascent, _ = face.getmetrics(); font = {}
    codes = list(range(32, 127)) + list(range(160, 256)) + list(range(0x2190, 0x2200)) + list(range(0x2500, 0x2600))
    for code in codes:
        ch = chr(code)
        if code > 255 and face.getmask(ch).getbbox() is None:
            continue
        mask, (ox, oy) = face.getmask2(ch, mode='1')
        w, h = mask.size
        ink = [(ox + x, oy + y - ascent) for y in range(h) for x in range(w) if mask.getpixel((x, y))]
        adv = max(1, round(face.getlength(ch)))
        font[code] = dict(ink=ink, wid=max((x + 1 for x, _ in ink), default=max(0, adv - 1)), adv=adv)
    return font


def font_key(name):
    return (re.sub(r'[^a-z0-9_-]+', '-', Path(name).stem.lower()).strip('-') or 'font')[:40]


def reload():
    global DEFAULT
    FONTS.clear(); SOURCE.clear(); INFO.clear(); _METRICS.clear()
    for source, folder in (('free', BUNDLED), ('user', USER)):
        for path in sorted(folder.glob('*.bdf')) if folder.is_dir() else []:
            key = font_key(path.name)
            if key in FONTS:
                continue
            try:
                FONTS[key], INFO[key] = parse_bdf(path.read_text(encoding='latin-1')); SOURCE[key] = source
            except (ValueError, IndexError) as error:
                print(f'Font {path.name} skipped: {error}')
    DEFAULT = 'fixed-5x7' if 'fixed-5x7' in FONTS else next(iter(FONTS))


def import_font(name, data, size=None, variation=None):
    """Store a BDF (bytes) or a TTF/OTF rasterized at `size` px in the user folder."""
    if len(data) > 4 * 1048576:
        raise ValueError('Font file too large')
    if name.lower().endswith('.bdf'):
        font, info = parse_bdf(data.decode('latin-1')); key = font_key(name); text = data.decode('latin-1')
    elif name.lower().endswith(('.ttf', '.otf')):
        size = int(size or 0); font = rasterize(data, size, variation)
        key = font_key(f'{Path(name).stem}-{size}'); text = write_bdf(font, key, f'Rasterized at {size} px from {Path(name).name}')
    else:
        raise ValueError('Expected a .bdf, .ttf or .otf file')
    if key in SOURCE and SOURCE[key] != 'user':
        key = 'user-' + key
    USER.mkdir(parents=True, exist_ok=True)
    (USER / f'{key}.bdf').write_text(text, encoding='latin-1')
    reload()
    return key


def metrics(key, capitals=False):
    key = key if key in FONTS else DEFAULT
    if (key, capitals) not in _METRICS:
        font = FONTS[key]
        # Line metrics from ASCII only: accents and box drawing may overflow the line.
        points = [p for c, g in font.items() if c < 127 and (not capitals or chr(c) in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for p in g['ink']]
        if not points:
            points = [p for g in font.values() for p in g['ink']]
        top = min((p[1] for p in points), default=-4); bottom = max((p[1] for p in points), default=0)
        _METRICS[key, capitals] = dict(top=top, bottom=bottom, height=bottom - top + 1)
    return _METRICS[key, capitals]


def catalog():
    def kind(key):
        return 'free' if SOURCE[key] == 'free' else 'imported'
    return [dict(id=key, source=SOURCE[key], height=metrics(key)['height'], default=key == DEFAULT,
                 label=f"{key} · {kind(key)} · {metrics(key)['height']} px") for key in FONTS]


# Original five-pixel icons, independent of any font.
BASIC_SYMBOLS={
    'Play':['10000','11100','11111','11100','10000'],
    'Stop':['11111']*5,
    'Pause':['11011']*5,
    'Record':['01110','11111','11111','11111','01110'],
    'Left':['00100','01100','11111','01100','00100'],
    'Right':['00100','00110','11111','00110','00100'],
    'Up':['00100','01110','11111','00100','00100'],
    'Down':['00100','00100','11111','01110','00100']}


def glyph_catalog():
    """Tight ink bounds for standalone glyph layers; no guessed character mapping."""
    result={}
    for key,font in FONTS.items():
        entries=[]
        for code,g in font.items():
            if not g['ink']:continue
            xs,ys=zip(*g['ink']);left,top=min(xs),min(ys)
            entries.append(dict(code=code,name=f'{key} · U+{code:04X}',character=chr(code),
                width=max(xs)-left+1,height=max(ys)-top+1,
                points=[[x-left,y-top] for x,y in g['ink']]))
        result[key]=entries
    result['builtin']=[dict(name=name,width=5,height=5,points=[[x,y] for y,row in enumerate(rows) for x,pixel in enumerate(row) if pixel=='1']) for name,rows in BASIC_SYMBOLS.items()]
    return result


reload()
