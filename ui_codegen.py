# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""UI document -> editable layout metadata + real ColdFire drawing commands.

No screenshot-to-code conversion: consumes the same semantic draw operations
as the preview. Static text glyphs stay distinct from rectangle/bitmap data.
An export is shareable when every font it uses may be redistributed (see
FB.SOURCE and the font's licence). Glyphs wider than eight
pixels are cut into 8-pixel columns (ui_draw.S limit).

Runtime text: a text layer named `$name` is a slot. The editor and the PNGs show its sample text; the code
leaves it out and exports `ui_slot_<screen>_<name>` and the font table it needs, so the host draws the live
string with ui_draw_text, pixel for pixel as the editor would.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import ui_components as C


def is_slot(c):
    return c['type']=='text' and str(c.get('name','')).startswith('$') and len(c['name'])>1


def symbol(name):
    return re.sub(r'[^A-Za-z0-9_]','_',name)


def slot_record(doc,c):
    """The slot's geometry as ui_draw_text reads it (see the Slot layout in ui_draw.S)."""
    name=c['name']
    off=[k for k,on in (('Hug',c.get('hug') or c.get('hug_w') or c.get('hug_h')),('underline',c.get('underline')),
            ('stroke',c.get('stroke','none')!='none'),('fill pattern',c.get('pattern','none')!='none'),('invert',c.get('inverted')),
            ('shadows',c.get('shadows') or c.get('effect_stroke','none')!='none')) if on]
    if off:raise ValueError(f'Runtime text {name}: turn off {", ".join(off)} (the box must not depend on the text)')
    key=c.get('font','default'); key=key if key in C.FB.FONTS else C.FB.DEFAULT
    x,y,w,h=(c[k] for k in ('x','y','width','height')); pt,pr,pb,pl=C.sides(c,'text_padding')
    font=C.spaced(key,c)
    record=dict(box=[x,y,x+w-1,y+h-1],left=x+pl,right=max(x+pl,x+w-pr),top=y+pt,
        align={'center':1,'end':2}.get(c.get('text_align','start'),0),ink=int(c.get('color','black')=='black'),
        bg=int(c.get('background','white')=='black') if c.get('fill','transparent')=='filled' else 255,
        hp=doc['styles'][c['style']]['highlight_padding'],sel_top=y+pt,sel_h=C.FB.metrics(key)['height'],
        space_adv=font[32]['adv'] if 32 in font else 0,case={'upper':1,'lower':2}.get(c.get('text_case'),0))
    if not (0<=x and x+w<=128 and 0<=y and y+h<=64 and y+pt<=63):raise ValueError(f'Runtime text {name}: keep its box and text inside the screen')
    return key,record


def generate(doc):
    C.validate(doc)
    output=['| SPDX-License-Identifier: MIT (see LICENSE-MIT.txt, written next to this file by the export)',
            '| GENERATED UI — edit the JSON project, regenerate; never hand-edit.',
            '| Entry ui_page_N: a3 = allocated 128x64 surface; preserves d2-d7/a2-a6.',
            '| Navigation and runtime values belong to the host: ui_draw_text fills the ui_slot_* records.',
            '        .text']
    glyphs={}; metadata=[]; tables={}; data=[]
    def glyph(width,rows):
        key=(width,tuple(rows))
        if key not in glyphs:glyphs[key]=f'.Lui_asset_{len(glyphs)}'
        return glyphs[key]
    for page_index,page in enumerate(doc['pages']):
        commands=[]; used=set(); slots=[]
        static=deepcopy(doc)
        for c in static['pages'][page_index]['components']:
            if is_slot(c):c['device']=False   # drawn by the host, never by the static code
        _,measurements=C.render(static,page_index,commands)
        for c in C.resolve_components(doc,page):
            if not is_slot(c) or c.get('device',True) is False:continue
            key,record=slot_record(doc,c); label=f'ui_slot_{page_index+1}_{symbol(c["name"][1:])}'
            if any(v['symbol']==label for v in slots):raise ValueError(f'Two runtime texts named {c["name"]} on one screen')
            tables.setdefault(key,f'ui_font_{symbol(key)}')
            data.extend([f'        .globl {label}',f'{label}:',f'        .long {tables[key]}',
                '        .byte '+','.join(str(v) for v in (*record['box'],record['left'],record['right'],record['top'],record['align'])),
                '        .byte '+','.join(str(record[k]) for k in ('ink','bg','hp','sel_top')),
                '        .byte '+','.join(str(record[k]) for k in ('sel_h','space_adv','case'))+',0'])
            slots.append(dict(name=c['name'],id=c['id'],symbol=label,font=key,**record))
        records=[]
        def tiles(x,y,width,ink,height,top,clip):
            # Cut one glyph into columns of at most 8 px, clipped to the screen and the clip box.
            # Rows run from the line top, widened to any ink above or below the line.
            r0=max(min([0]+[dy-top for _,dy in ink]),-y); r1=min(max([height-1]+[dy-top for _,dy in ink]),63-y)
            out=[]
            for tile in range(min([0]+[dx for dx,_ in ink]),width,8):
                gx=x+tile
                if gx>=128 or gx+8<=0 or r1<r0:continue
                tw=min(8,width-tile,128-gx); rows=[0]*(r1-r0+1)
                for dx,dy in ink:
                    xx,yy=x+dx,y+dy-top
                    if tile<=dx<tile+tw and 0<=xx<128 and r0<=dy-top<=r1 and clip['x']<=xx<clip['x']+clip['width'] and clip['y']<=yy<clip['y']+clip['height']:
                        rows[dy-top-r0]|=0x80>>(dx-tile)
                if not any(rows):continue
                if gx<0:  # left edge: shift the column so it starts on screen
                    rows=[(r<<-gx)&0xff for r in rows]; tw+=gx; gx=0
                out.append((gx,y+r0,tw,rows))
            return out
        for command in commands:
            x,y,op=command['x'],command['y'],command['op']
            if command['type']=='rect':
                records.append(f"        .byte 0,{x},{y},{op},{command['x1']},{command['y1']},0,0")
            else:
                assets=[]
                if command['type']=='glyph':
                    width,rows=command['glyph']
                    if width<=8:assets=[(x,y,width,rows)]
                    else:
                        ink=[(dx,dy) for dy,row in enumerate(rows) for dx in range(width) if row>>(width-1-dx)&1]
                        assets=tiles(x,y,width,ink,len(rows),0,dict(x=0,y=0,width=128,height=64))
                else:
                    key=command.get('font','default'); key=key if key in C.FB.FONTS else C.FB.DEFAULT; used.add(key)
                    clip=command.get('clip') or dict(x=0,y=0,width=128,height=64)
                    for char in command['text']:
                        font=C.FB.FONTS[key][ord(char)]
                        width=max(font['wid'],max((p[0]+1 for p in font['ink']),default=0))
                        assets+=tiles(x,y,width,font['ink'],command.get('height',5),command.get('top',-4),clip)
                        x+=font['adv']
                for gx,gy,width,rows in assets:
                    if width>8:raise ValueError('Glyph width exceeds eight pixels')
                    records.extend([f'        .byte 1,{gx},{gy},{op}',f'        .long {glyph(width,rows)}'])
        entry=f'ui_page_{page_index+1}'
        output.extend([f'        .globl {entry}',f'{entry}:',
            '        lea %sp@(-44),%sp','        moveml %d2-%d7/%a2-%a6,%sp@',
            f'        lea .Lui_table_{page_index}(%pc),%a2','        jsr .Lui_commands:l',
            '        moveml %sp@,%d2-%d7/%a2-%a6','        lea %sp@(44),%sp','        rts',
            '        .balign 4',f'.Lui_table_{page_index}:',*records,'        .byte 255,0,0,0,0,0,0,0'])
        metadata.append(dict(fonts=sorted(used|{v['font'] for v in slots}),id=page['id'],name=page.get('name',''),note=page.get('note',''),entry=entry,slots=slots,components=measurements,commands=commands))
    for key,label in tables.items():
        data.extend(['        .balign 4',f'        .globl {label}',f'{label}:',*font_table(key,glyph)])
    output.extend(['        .balign 4',*data])
    for (width,rows),label in glyphs.items():
        output.extend([label+':','        .byte '+','.join(map(str,[width,len(rows),*rows]))])
    output.extend(['        .balign 4',(Path(__file__).with_name('ui_draw.S')).read_text()])
    return '\n'.join(output)+'\n',metadata


def font_table(key,glyph):
    """95 entries (codes 32..126): glyph pointer, advance, ink width, row below the line top, x offset."""
    font=C.FB.FONTS[key]; top=C.FB.metrics(key)['top']; spare=font.get(63) or font.get(32) or dict(ink=[],wid=0,adv=0)
    out=[]
    for code in range(32,127):
        g=font.get(code,spare); ink=g['ink']; label='0'; row=0; x0=0
        if ink:
            x0=min(x for x,_ in ink); width=max(x for x,_ in ink)-x0+1
            row=min(y-top for _,y in ink); rows=[0]*(max(y-top for _,y in ink)-row+1)
            if width>8:raise ValueError(f'Font {key}: U+{code:04X} is {width} px wide; runtime text needs glyphs of 8 px at most')
            if not (0<=row<=255 and -128<=x0<=127):raise ValueError(f'Font {key}: U+{code:04X} out of the runtime table range')
            for x,y in ink:rows[y-top-row]|=0x80>>(x-x0)
            label=glyph(width,rows)
        if not (0<=g['adv']<=255 and 0<=g['wid']<=255):raise ValueError(f'Font {key}: U+{code:04X} advance out of range')
        out+=[f'        .long {label}',f"        .byte {g['adv']},{g['wid']},{row},{x0&0xff}"]
    return out


def fonts_note(metadata):
    used=sorted({key for page in metadata for key in page['fonts']})
    lines='Fonts: '+(', '.join(f"{key} ({C.FB.SOURCE.get(key,'?')})" for key in used) or 'none')+'.\n'
    return lines+'Imported fonts: check their licence before sharing this export.\n' if any(C.FB.SOURCE.get(k)=='user' for k in used) else lines


def export(doc,folder):
    source,metadata=generate(doc)
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'ui_generated.S').write_text(source)
    (folder/'LICENSE-MIT.txt').write_text((Path(__file__).with_name('LICENSE-MIT')).read_text())
    (folder/'ui_commands.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    (folder/'CODE_README.txt').write_text(
        'Generated ColdFire code, not a firmware package.\n'
        'Assemble ui_generated.S with -mcpu=5407 and link with your module.\n'
        'Pass an allocated 128x64 surface in a3 and call ui_page_N.\n'
        'Each entry preserves d2-d7/a2-a6; d0/d1/a0/a1 are scratch.\n'
        'Coordinates/anchors, fills, text, pixels and lines come from the JSON.\n'
        'The host owns the surface lifetime, redraw scheduling and input.\n'
        'Layers marked editor-only (and an editor-only background) are absent from code and PNG.\n'
        'NOTES.md lists the designer notes per screen and layer.\n'
        'Runtime text: layers named $name are left out of ui_page_N; draw them with ui_draw_text\n'
        '(a3 surface, a0 string, a1 ui_slot_N_name, d0 flags: 1 selected, 2 fill the box first).\n'
        'Slots are listed in ui_commands.json (slots); draw them after ui_page_N.\n'
        'Reserved zones are drawn in the PNG previews only: the code leaves them untouched;\n'
        'their bounds are listed in ui_commands.json (components with reserved=true).\n'
        +fonts_note(metadata))
    return str(folder/'ui_generated.S')
