# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""OctaDraw documents: 128 x 64 one-bit screens made of layers, rendered pixel for pixel.

The same draw commands feed the editor preview, the PNG exports and the ColdFire code generator.
Projects, screens, widgets, fonts and references live in the work folder (OCTADRAW_HOME).
"""
import base64
from copy import deepcopy
import io
import json
import math
import os
import random
import re
from contextvars import ContextVar
from pathlib import Path

import ui_pixels as P
import ui_fontbook as FB
from PIL import Image

STORE = Path(os.environ.get('OCTADRAW_HOME') or Path(__file__).resolve().with_name('work'))
ALIGNMENTS = ('free', 'start', 'center', 'end', 'stretch')
# per-axis constraint relative to the parent content (after its Dock); overrides the legacy align_* of that axis.
CONSTRAINTS = ('left', 'right', 'both', 'center', 'scale')
NO_RESIZE = ('image', 'iso', 'drawing', 'line')
# Layers sit anywhere on 0..127 x 0..63.
STROKE_SIDES = ('rect','text','grid','layout','list','multislider')   # types whose rectangular frame can drop sides
FREE = ('text', 'drawing', 'line', 'rect', 'scrollbar', 'placeholder', 'waveform', 'image', 'group', 'iso', 'shape', 'grid', 'layout', 'list', 'multislider')
ISO_FACES = ('none', 'black', 'white', 'checker', 'dots', 'sparse', 'hlines', 'vlines', 'diagonal', 'grid')
FIXED_SIZE = ('drawing', 'line', 'image')
CONTAINERS = ('rect', 'group', 'grid', 'layout')
SHAPE_KINDS = ('ellipse', 'triangle', 'arrow', 'polygon', 'star', 'diamond')
DIRECTIONS = ('up', 'down', 'left', 'right')
DOCKS = ('top', 'bottom', 'left', 'right')
DOCK_PARENTS = ('rect', 'group')
NO_DOCK = ('image', 'iso', 'drawing', 'line')
# Line layer: two ends inside its box, stroke 1-4 px, solid / dotted / dashed, caps, colour black / white / invert.
LINE_STYLES = ('solid', 'dotted', 'dashed')
LINE_CAPS = ('none', 'arrow', 'dot')
TARGETS = ('lcd', 'oled')   # preview only: lit pixel dark (LCD) or bright (OLED)
BACKGROUNDS = ('white', 'black', 'reference', 'pattern')
REFERENCES = STORE / 'references'
WAVE_SIGNALS = ('loop', 'decay', 'sine', 'noise')
PATTERNS = ('none', 'checker', 'dots', 'sparse', 'hlines', 'vlines', 'diagonal', 'grid', 'noise')
BG_PATTERNS = ('checker', 'dots', 'dense', 'sparse', 'hlines', 'wide', 'vlines', 'diagonal', 'diagonal2', 'crosshatch', 'grid', 'grid8', 'bricks')
# display case of a text (the source string is kept as typed).
TEXT_CASES = ('upper', 'lower')
# auto layout container. Cells: Hug (largest child of the column / row) or Fill (equal share of the content).
CELL_SIZES = ('hug', 'fill')
CELL_ALIGNS = ('start', 'center', 'end', 'stretch')


def cased(c, text):
    """Text as displayed: `text_case` upper / lower, else as typed."""
    mode=c.get('text_case')
    return text.upper() if mode=='upper' else text.lower() if mode=='lower' else text


def split_labels(text):
    """Table labels: `A | B | C` (older projects) or, without a bar, `A, B, C`."""
    return text.split('|') if '|' in text else text.split(',')


def list_items(c):
    return [v.strip() for v in c.get('items','').split(',') if v.strip()][:64]


def spaced(font_key,c):
    """Font of a text layer, with its own space advance if Space width is set."""
    font=FB.FONTS[font_key]; space=c.get('space_width')
    return font if space is None or 32 not in font else {**font,32:{**font[32],'adv':space}}


def text_ink(font_key, text, font=None):
    """Ink extent of an actual string: (width from first column, top dy, bottom dy)."""
    font=font or FB.FONTS[font_key]; cursor=0; right=0; ys=[]
    for char in text:
        g=font.get(ord(char))
        if not g:continue
        for dx,dy in g['ink']:right=max(right,cursor+dx+1);ys.append(dy)
        cursor+=g['adv']
    m=FB.metrics(font_key)
    return right,(min(ys) if ys else m['top']),(max(ys) if ys else 0)
COMMANDS = ContextVar('ui_draw_commands', default=None)


def draw_rect(img,x0,y0,x1,y1,op):
    if x1<x0 or y1<y0:return
    if not (0<=x0<=x1<128 and 0<=y0<=y1<64):
        raise ValueError('Drawing outside screen')
    log=COMMANDS.get()
    if log is not None:log.append(dict(type='rect',x=x0,y=y0,x1=x1,y1=y1,op=op))
    P.rect(img,x0,y0,x1,y1,op)


def frame_out(c):
    """Width of a frame drawn OUTSIDE the layer (`stroke_position` outer), else 0."""
    if c.get('stroke_position')!='outer' or c['type'] not in ('rect','grid','layout','text','list','multislider') or c['type']=='rect' and c.get('radius',0): return 0
    on=c.get('stroke','black' if c['type'] in ('rect','grid') else 'none')!='none' and (c['type']!='grid' or c.get('outer',True))
    return c.get('stroke_width',1) if on else 0


def margin(c):
    return 2 if c['type']=='rect' and c.get('shadow') else 0


def sides(c,key):
    """Padding as (top, right, bottom, left): `padding_sides` when set, else the uniform value of `key`."""
    v=c.get('padding_sides')
    return tuple(v) if v else (c.get(key,0),)*4


def frame_bounds(c, style):
    """Inside of the outline, before padding: (frame, (top, right, bottom, left) padding)."""
    x,y,w,h = (c[k] for k in ('x','y','width','height'))
    if c['type'] in FREE:
        framed = c['type']=='rect' or c['type']=='grid' and c.get('outer',True)
        k = c.get('stroke_width',1) if framed and c.get('stroke','black')!='none' else 0
        if c['type']=='layout' and c.get('stroke','none')!='none': k=c.get('stroke_width',1)
        if frame_out(c): k=0   # outer frame: the whole box is content
        pad = sides(c,'padding') if c['type'] in ('rect','group','grid','layout') else (0,0,0,0)
        return dict(x=x+k, y=y+k, width=max(0,w-2*k), height=max(0,h-2*k)), pad
    raise ValueError('Unknown layer type')


def shrink(frame, pad):
    t,r,b,l = pad
    return dict(x=frame['x']+l, y=frame['y']+t, width=max(0,frame['width']-l-r), height=max(0,frame['height']-t-b))


def content_bounds(c, style):
    return shrink(*frame_bounds(c, style))


def dock_layout(parent, kids, doc):
    """Dock: children glued to a side of their container, each one taking its band out of the room left
    for the next. Order: "Full length" layers first, then top/bottom (full width), then left/right
    (between them); layer order only among the same rank. Returns ({id: (x, y, w, h)}, remaining area).
    `parent` = resolved container (None = the screen); `kids` = its children with their own sizes."""
    if parent is None: frame,pad = dict(x=0,y=0,width=128,height=64),(0,0,0,0)
    else: frame,pad = frame_bounds(parent,doc['styles'][parent['style']])
    x0,y0,x1,y1 = frame['x'],frame['y'],frame['x']+frame['width'],frame['y']+frame['height']
    t,r,b,l = pad; rects={}
    rank=lambda c:0 if c.get('dock_span') else 1 if c['dock'] in ('top','bottom') else 2
    for c in sorted((c for c in kids if c.get('dock')),key=rank):
        side=c['dock']
        gap=c.get('dock_gap',0)
        if c.get('dock_over_padding',False): zx0,zy0,zx1,zy1 = x0,y0,x1,y1
        else: zx0,zy0,zx1,zy1 = x0+l,y0+t,x1-r,y1-b
        zw,zh = zx1-zx0,zy1-zy0
        if zw<=0 or zh<=0 or (c['height']>zh if side in ('top','bottom') else c['width']>zw):
            raise ValueError('Docked layer exceeds parent content')
        if side=='top': rects[c['id']]=(zx0,zy0,zw,c['height']); y0=zy0+c['height']+gap; t=0
        elif side=='bottom': rects[c['id']]=(zx0,zy1-c['height'],zw,c['height']); y1=zy1-c['height']-gap; b=0
        elif side=='left': rects[c['id']]=(zx0,zy0,c['width'],zh); x0=zx0+c['width']+gap; l=0
        else: rects[c['id']]=(zx1-c['width'],zy0,c['width'],zh); x1=zx1-c['width']-gap; r=0
    return rects,shrink(dict(x=x0,y=y0,width=max(0,x1-x0),height=max(0,y1-y0)),(t,r,b,l))


def layout_cells(c, kids, area):
    """Auto layout: a grid of `layout_cols` columns x `layout_rows` rows (absent = as many rows as the
    children need). `layout_flow` rows (default) fills row after row and adds rows when full; columns fills
    column after column and adds columns. A child with `cell` (slot index) sits in that slot; the others take
    the free slots in layer order. Column widths / row heights: Hug = largest child of that column / row
    (an empty one: largest child overall, else 8 px), Fill = equal share of `area` (gaps excluded).
    Inside its cell a child is aligned start / center / end / stretch, or placed at `cell_x` / `cell_y`
    from the cell's top-left (free placement, kept inside the cell).
    Returns ({id: (x, y, w, h)}, (content width, content height), cells (x, y, w, h) in slot order,
    {id: slot})."""
    n=len(kids); cols=c.get('layout_cols',3); flow=c.get('layout_flow','rows')
    explicit={}
    for k,kid in enumerate(kids):
        slot=kid.get('cell')
        if isinstance(slot,int) and 0<=slot<256 and slot not in explicit.values(): explicit[k]=slot
    need=max([n]+[v+1 for v in explicit.values()])
    rows=c.get('layout_rows') or max(1,-(-need//cols))
    if flow=='columns':
        cols=max(cols,-(-need//rows)); slot=lambda k:(k//rows,k%rows)
    else:
        rows=max(rows,-(-need//cols)); slot=lambda k:(k%cols,k//cols)
    used=set(explicit.values()); free=(i for i in range(cols*rows) if i not in used)
    assigned=[explicit[k] if k in explicit else next(free) for k in range(n)]
    gx,gy=c.get('gap_x',2),c.get('gap_y',2)
    def sizes(count,mode,room,gap,axis,size):
        if mode=='fill':
            free_px=room-gap*(count-1)
            if free_px<count: raise ValueError('Layout too small for its cells')
            return [free_px//count+(1 if i<free_px%count else 0) for i in range(count)]
        empty=max([kid[size] for kid in kids] or [8])
        return [max([kid[size] for k,kid in enumerate(kids) if slot(assigned[k])[axis]==i] or [empty]) for i in range(count)]
    # Fill needs the container size: a Hug container always hugs its cells on that axis.
    cw=sizes(cols,'hug' if c.get('hug_w') or area is None else c.get('cell_w','hug'),area and area['width'],gx,0,'width')
    rh=sizes(rows,'hug' if c.get('hug_h') or area is None else c.get('cell_h','hug'),area and area['height'],gy,1,'height')
    total=(sum(cw)+gx*(len(cw)-1),sum(rh)+gy*(len(rh)-1))
    if area is None: return {},total,[],{}
    def cell(k):
        col,row=slot(k)
        return [area['x']+sum(cw[:col])+gx*col,area['y']+sum(rh[:row])+gy*row,cw[col],rh[row]]
    cells=[cell(k) for k in range(cols*rows)]
    rects={}
    for k,kid in enumerate(kids):
        cell=cells[assigned[k]]
        box=[0,0,kid['width'],kid['height']]
        for i,key,free_key in ((0,'cell_align_x','cell_x'),(1,'cell_align_y','cell_y')):
            mode=c.get(key,'start'); size=cell[2+i]
            if kid['type'] not in NO_RESIZE and ((mode=='stretch' and free_key not in kid) or box[2+i]>size): box[2+i]=max(1,size)
            space=size-box[2+i]
            if free_key in kid: box[i]=cell[i]+max(0,min(kid[free_key],space))
            else: box[i]=cell[i]+(space//2 if mode=='center' else space if mode=='end' else 0)
        rects[kid['id']]=tuple(box)
    return rects,total,cells,{kid['id']:assigned[k] for k,kid in enumerate(kids)}


def layout_outer(c, total):
    """Hug container: outer size from its content size (padding and frame included)."""
    frame,(t,r,b,l)=frame_bounds(dict(c,width=1000,height=1000),None)
    k=frame['x']-c['x']
    return total[0]+l+r+2*k,total[1]+t+b+2*k


def screen_content(doc, page):
    """Room left on the screen once its docked layers are placed (editor: area of the layers without parent)."""
    return resolve_components(doc,page,True)[1]


def resolve_components(doc, page, with_screen=False):
    """Resolve anchors once, for both rendering and editor hit testing."""
    source={c['id']:c for c in page['components']}; resolved={}; bases={}; layouts={}
    def base(key):
        # Own size only (Hug text, iso solid): independent of the parent, so docks can read it first.
        if key in bases: return bases[key]
        c=deepcopy(source[key])
        if c['type']=='iso':
            a,b,h=c.get('iso_a',8),c.get('iso_b',8),c.get('iso_h',8)
            c['width']=2*a+2*b+1; c['height']=a+b+h+1
        if c['type']=='text' and (c.get('hug') or c.get('hug_w') or c.get('hug_h')):
            # Hug content: the box follows the text plus its padding (stroke included in the padding).
            key_font=c.get('font','default'); pt,pr,pb,pl=sides(c,'text_padding')
            width,top,bottom=text_ink(key_font,clean_text(cased(c,c.get('text','')),key_font,False),spaced(key_font,c))
            if c.get('underline'):bottom=max(bottom,2)
            if c.get('hug') or c.get('hug_w'):c['width']=max(1,width+pl+pr)
            if c.get('hug') or c.get('hug_h'):c['height']=bottom-top+1+pt+pb; c['_ink_top']=top
        if c['type']=='list' and (c.get('hug') or c.get('hug_w') or c.get('hug_h')):
            w,h=list_size(c)
            if c.get('hug') or c.get('hug_w'):c['width']=w
            if c.get('hug') or c.get('hug_h'):c['height']=h
        if c['type']=='layout' and (c.get('hug_w') or c.get('hug_h')):
            kids=[base(k['id']) for k in page['components'] if k.get('parent')==key]
            w,h=layout_outer(c,layout_cells(c,kids,None)[1])
            if c.get('hug_w'):c['width']=max(1,w)
            if c.get('hug_h'):c['height']=max(1,h)
        bases[key]=c
        return c
    def layout(pkey):
        # Docked rectangles and remaining content area of one parent ('' = the screen).
        if pkey not in layouts:
            kids=[base(k['id']) for k in page['components'] if (k.get('parent') or '')==pkey]
            parent=resolve(pkey) if pkey else None
            if parent and parent['type']=='layout':
                area=content_bounds(parent,doc['styles'][parent['style']])
                rects,_,cells,slots=layout_cells(parent,kids,area)
                parent['_cells']=cells; parent['_slots']=slots   # editor: drop targets / structure overlay
                layouts[pkey]=(rects,area)
            elif any(k.get('dock') for k in kids): layouts[pkey]=dock_layout(parent,kids,doc)
            elif parent: layouts[pkey]=({},content_bounds(parent,doc['styles'][parent['style']]))
            else: layouts[pkey]=({},dict(x=0,y=0,width=128,height=64))
        return layouts[pkey]
    def resolve(key):
        if key in resolved: return resolved[key]
        c=deepcopy(base(key)); parent=c.get('parent')
        rects,area=layout(parent or '')
        placed=c.get('dock') or key in rects
        if placed:
            # Docked or in an auto layout: the container dictates the place; alignment, offsets and stretch do not apply.
            c['x'],c['y'],c['width'],c['height']=rects[key]
        for axis,size,align in [] if placed else [('x','width','align_x'),('y','height','align_y')]:
            cons=c.get('constraint_'+axis)
            if cons:
                # constraint: distances / shift / per-mille span against the parent content (`area`).
                a0,s0=area[axis],area[size]; off=c.get('offset_'+axis,0); end=c.get('end_'+axis,0)
                if cons=='both':
                    c[axis]=a0+off; c[size]=max(1,s0-off-end)
                elif cons=='scale':
                    st,sz=c.get('scale_'+axis,(0,1000)); lo=(st*s0+500)//1000; hi=((st+sz)*s0+500)//1000
                    c[axis]=a0+lo; c[size]=max(1,hi-lo)
                elif cons=='left':
                    c[axis]=a0+off
                else:
                    space=s0-c[size]
                    if space<0: raise ValueError('Layer exceeds parent content')
                    c[axis]=a0+(space//2+c.get('center_'+axis,0) if cons=='center' else space-end)
                continue
            mode=c.get(align,'free')
            if mode=='stretch' and c['type'] not in FIXED_SIZE:
                # Constraint: keep both margins to the parent content (or the screen).
                c[axis]=area[axis]+c.get('offset_'+axis,0)
                c[size]=max(1,area[size]-c.get('offset_'+axis,0)-c.get('end_'+axis,0))
                continue
            if mode=='stretch':mode='free'
            if mode=='free' and parent and ('offset_'+axis) in c:
                c[axis]=area[axis]+c['offset_'+axis]
            if mode!='free':
                space=area[size]-c[size]
                if space<0: raise ValueError('Layer exceeds parent content')
                c[axis]=area[axis]+(space//2 if mode=='center' else space if mode=='end' else 0)
                if not parent and c['type'] not in FREE:
                    c[axis]=max(1,min((125 if axis=='x' else 61)-c[size],c[axis]))
        o=frame_out(c)
        if not (0<=c['x']-o and 0<=c['y']-o and c['x']+c['width']+margin(c)+o<=128 and c['y']+c['height']+margin(c)+o<=64):
            if c.get('hug') or c.get('hug_w') or c.get('hug_h'):
                # Hug content that no longer fits the screen (a list grows with its items): clip it to the screen
                # instead of failing the whole preview.
                c['width']=min(c['width'],max(1,128-c['x']-margin(c)-o))
                c['height']=min(c['height'],max(1,64-c['y']-margin(c)-o))
            if not (0<=c['x']-o and 0<=c['y']-o and c['x']+c['width']+margin(c)+o<=128 and c['y']+c['height']+margin(c)+o<=64):
                raise ValueError('Alignment outside screen')
        c['_parent_bounds']=area
        resolved[key]=c
        return c
    for c in page['components']: resolve(c['id'])
    for c in page['components']:
        if c['type']=='layout': layout(c['id'])   # cells of every layout, empty ones included
    layout('')
    # Containers that dock children expose the room left (editor measurements, alignment of the others).
    for key,(_,area) in layouts.items():
        if key:resolved[key]['_content']=area
    # Draw order = layer tree: each container, then its children (in list order), then the next sibling.
    children={}
    for c in page['components']:children.setdefault(c.get('parent') or '',[]).append(c['id'])
    order=[]
    def walk(key):
        for cid in children.get(key,[]):order.append(resolved[cid]);walk(cid)
    walk('')
    return (order,layouts[''][1]) if with_screen else order


def default_document():
    return dict(version=1, name='Untitled', styles=dict(default=dict(highlight_padding=1)),
                pages=[dict(id='screen1', name='Screen 1', background='black', components=[])])


def font_name(key):
    # A font not loaded here renders with FB.DEFAULT: projects stay portable.
    return isinstance(key,str) and 0<len(key)<=64


def clean_text(value,font_key='default',uppercase=True):
    text=str(value).upper() if uppercase else str(value)
    font=FB.FONTS[font_key];missing='?' if ord('?') in font else ' '
    return ''.join(c if ord(c) in font else missing for c in text)[:63]


def validate(doc):
    if not isinstance(doc, dict):
        raise ValueError('Invalid UI project')
    if doc.get('version') != 1 or not isinstance(doc.get('pages'), list) or not 1 <= len(doc['pages']) <= 48:
        raise ValueError('Invalid UI project')
    if not isinstance(doc.get('styles'), dict) or not 1 <= len(doc['styles']) <= 8:
        raise ValueError('Invalid styles')
    for style in doc['styles'].values():
        if not isinstance(style, dict):
            raise ValueError('Invalid style')
        for key, lo, hi in (('highlight_padding', 0, 3),):
            if not isinstance(style.get(key), int) or not lo <= style[key] <= hi:
                raise ValueError('Style out of range: '+key)
    if doc.get('target','lcd') not in TARGETS:
        raise ValueError('Unknown target')
    if 'font' in doc and not font_name(doc['font']):
        raise ValueError('Invalid project font')
    page_ids = set()
    for page in doc['pages']:
        if not isinstance(page, dict) or not isinstance(page.get('id'), str) or page['id'] in page_ids:
            raise ValueError('Invalid or duplicate screen ID')
        page_ids.add(page['id'])
        if not isinstance(page.get('family',''),str) or len(page.get('family',''))>40 or not isinstance(page.get('note',''),str) or len(page.get('note',''))>2000 or not isinstance(page.get('background_device',True),bool):
            raise ValueError('Invalid screen note or background option')
        if page.get('background')=='reference' and (not isinstance(page.get('reference',''),str) or not REFERENCE_NAME(page.get('reference','')) or not isinstance(page.get('reference_dim',True),bool)):
            raise ValueError('Invalid reference image')
        if not isinstance(page.get('name',''), str) or len(page.get('name','')) > 40 or page.get('background','black') not in BACKGROUNDS or page.get('bg_pattern','checker') not in BG_PATTERNS or page.get('bg_base','black') not in ('black','white'):
            raise ValueError('Invalid screen name or background')
        if not isinstance(page.get('components'), list) or len(page['components']) > 128:
            raise ValueError('At most 128 layers per screen')
        states = page.get('visibility_states', [])
        if not isinstance(states, list):
            raise ValueError('Invalid visibility states')
        names = set()
        for state in states:
            if not isinstance(state, dict):
                raise ValueError('Invalid visibility state')
            name, hidden = state.get('name'), state.get('hidden')
            if not isinstance(name, str) or not name.strip() or len(name) > 40 or name in names:
                raise ValueError('Invalid or duplicate visibility state name')
            names.add(name)
            # Deleted layers may remain in a snapshot; recall ignores their IDs.
            if not isinstance(hidden, dict) or any(not isinstance(key, str) or not isinstance(value, bool) for key, value in hidden.items()):
                raise ValueError('Visibility state flags must be booleans')
        component_ids = set()
        for c in page['components']:
            if not isinstance(c, dict) or not isinstance(c.get('id'), str) or c['id'] in component_ids:
                raise ValueError('Invalid or duplicate layer ID')
            component_ids.add(c['id'])
            if c.get('type') not in FREE or c.get('style') not in doc['styles']:
                raise ValueError('Unknown layer/style')
            x, y, w, h = (c.get(k) for k in ('x', 'y', 'width', 'height'))
            if not all(isinstance(v, int) for v in (x,y,w,h)) or not (
                    0 <= x and 0 <= y and 1 <= w and 1 <= h and x+w+margin(c) <= 128 and y+h+margin(c) <= 64):
                raise ValueError('Layer outside screen (including shadow)')
            if c.get('color','black') not in (('black','white','invert') if c['type']=='line' else ('black','white')) or c.get('background','white') not in ('black','white'):
                raise ValueError('Colour must be black or white')
            if any(c.get(k,'free') not in ALIGNMENTS for k in ('align_x','align_y')):
                raise ValueError('Unknown alignment')
            if any(not isinstance(c.get(k,False),bool) for k in ('locked','hidden','inverted','pinned')) or not isinstance(c.get('device',True),bool):
                raise ValueError('Lock / visibility flags must be booleans')
            if not isinstance(c.get('note',''),str) or len(c.get('note',''))>2000:
                raise ValueError('Note: at most 2000 characters')
            if c['type']=='image' and (not isinstance(c.get('pixels'),str) or len(c['pixels'])!=w*h or set(c['pixels'])-set('01.')
                    or c.get('white','transparent') not in ('transparent','opaque') or not isinstance(c.get('invert',False),bool)
                    or not isinstance(c.get('xor',False),bool)):
                raise ValueError('Invalid image layer')
            if any(k in c and (not isinstance(c[k],int) or not -128<=c[k]<=128) for k in ('offset_x','offset_y','end_x','end_y')):
                raise ValueError('Invalid parent offset')
            for axis in 'xy':
                k=c.get('constraint_'+axis)
                if k is not None and (k not in CONSTRAINTS or k in ('both','scale') and c['type'] in NO_RESIZE):
                    raise ValueError('Unknown constraint, or one that needs a resizable layer')
                v=c.get('center_'+axis,0)
                if not isinstance(v,int) or isinstance(v,bool) or not -128<=v<=128:
                    raise ValueError('Invalid centre offset')
                v=c.get('scale_'+axis,[0,1000])
                if not (isinstance(v,(list,tuple)) and len(v)==2 and all(isinstance(n,int) and not isinstance(n,bool) for n in v)
                        and 0<=v[0]<=1000 and 1<=v[1]<=1000 and v[0]+v[1]<=1000):
                    raise ValueError('Scale must be [start, size] per mille, start+size at most 1000')
            if c.get('text_align','start') not in ('start','center','end'):
                raise ValueError('Unknown text alignment')
            if not font_name(c.get('font','default')):
                raise ValueError('Invalid font name')
            if c.get('focus_state','normal') not in ('normal','selected') or c['type'] not in ('rect','shape','grid','layout') and c.get('fill','transparent') not in ('transparent','filled'):
                raise ValueError('Unknown text variant')
            if c['type']=='rect' and (c.get('fill','none') not in ('none','black','white','invert') or
                    c.get('stroke','black') not in ('none','black','white') or not isinstance(c.get('shadow',False),bool)):
                raise ValueError('Invalid rectangle')
            def number(key,lo,hi,default):
                v=c.get(key,default)
                if not isinstance(v,int) or isinstance(v,bool) or not lo<=v<=hi:
                    raise ValueError(f'{key} must be between {lo} and {hi}')
            if c['type'] in ('rect','text','shape','grid'):
                number('stroke_width',1,4,1)
                if c.get('stroke_style','solid') not in ('solid','dotted'):raise ValueError('Unknown stroke style')
            if c['type']=='rect':number('radius',0,16,0)
            if c['type']=='shape':
                number('sides',3,12,5);number('rotation',0,359,0);number('head',0,64,0);number('shaft',0,64,0);number('inner',10,90,50)
                if c.get('shape','ellipse') not in SHAPE_KINDS or c.get('direction','right') not in DIRECTIONS or c.get('fill','none') not in ('none','black','white','invert') or c.get('stroke','black') not in ('none','black','white'):
                    raise ValueError('Invalid shape')
            if c['type']=='grid':
                number('grid_rows',1,32,3);number('grid_cols',1,32,4);number('header_rows',0,4,0);number('header_cols',0,4,0);number('header_height',0,40,0)
                if not isinstance(c.get('header_lines',False),bool):raise ValueError('Invalid table header lines')
                if any(not isinstance(c.get(k,''),str) or len(c.get(k,''))>400 for k in ('header_text','side_text')) or c.get('header_align','center') not in ('start','center','end') or not font_name(c.get('header_font','default')):
                    raise ValueError('Invalid table labels')
                if any(c.get(k,'solid') not in ('solid','dotted','none') for k in ('lines_h','lines_v')) or c.get('stroke','black') not in ('none','black','white') or c.get('fill','none') not in ('none','black','white') or c.get('header','invert') not in ('invert','black','white','none') or not isinstance(c.get('outer',True),bool):
                    raise ValueError('Invalid grid')
            if c['type']=='iso':
                for key,lo,hi,default in (('iso_a',1,30,8),('iso_b',1,30,8),('iso_h',0,40,8)):number(key,lo,hi,default)
                if c.get('iso_shape','box') not in ('box','wedge','pyramid','cylinder') or c.get('slope','right') not in ('left','right'):raise ValueError('Invalid iso shape')
                if any(c.get(face+'_fill','none') not in ISO_FACES for face in ('top','left','right')) or c.get('stroke','white') not in ('none','black','white'):
                    raise ValueError('Invalid iso box')
            if c['type']=='scrollbar':
                for key,lo,hi,default in (('total',1,999,20),('visible',1,999,5),('position',0,999,0)):number(key,lo,hi,default)
                if c.get('orientation','vertical') not in ('vertical','horizontal') or c.get('track','arrows') not in ('arrows','arrows_thumb','outline','line','dotted','none') or not isinstance(c.get('arrows_auto',False),bool):
                    raise ValueError('Invalid scrollbar')
            if c['type']=='waveform':
                for key,lo,hi,default in (('amplitude',1,100,90),('cycles',1,32,8),('seed',0,9999,1),('playhead',-1,100,-1)):number(key,lo,hi,default)
                number('centre_width',1,3,1)
                for key,lo,hi,default in (('trim_start',-1,100,-1),('trim_end',-1,100,-1),('slices',0,64,0),('slice_len',0,64,0)):number(key,lo,hi,default)
                if c.get('trim_style','solid') not in ('solid','dotted') or c.get('trim_outside','keep') not in ('keep','dim','invert') or c.get('marker_op','ink') not in ('ink','invert') or not isinstance(c.get('trim_flags',True),bool):
                    raise ValueError('Invalid trim markers')
                if c.get('signal','loop') not in WAVE_SIGNALS or c.get('display','mirror') not in ('mirror','top','line') or not isinstance(c.get('centre',True),bool) or c.get('centre_style','solid') not in ('solid','dotted','none'):
                    raise ValueError('Invalid waveform')
            if c['type'] in ('rect','group','grid','layout','list','multislider') and (not isinstance(c.get('padding',0),int) or not 0<=c.get('padding',0)<=20):
                raise ValueError('Container padding must be between 0 and 20')
            shadows=c.get('shadows',[])
            if not isinstance(shadows,list) or len(shadows)>4 or any(not isinstance(v,dict) or any(not isinstance(v.get(k,0),int) or not -8<=v.get(k,0)<=8 for k in ('dx','dy'))
                    or v.get('color','black') not in ('black','white') or v.get('style','solid') not in ('solid','dotted') or v.get('shape','box') not in ('box','ink')
                    or v.get('stroke','none') not in ('none','black','white') or not isinstance(v.get('stroke_width',1),int) or isinstance(v.get('stroke_width',1),bool) or not 1<=v.get('stroke_width',1)<=4 for v in shadows):
                raise ValueError('Shadows: at most 4, offsets −8..8')
            if c.get('effect_stroke','none') not in ('none','black','white'):
                raise ValueError('Invalid combined outline colour')
            number('effect_stroke_width',1,4,1)
            if c['type'] in ('rect','text','shape') and (c.get('pattern','none') not in PATTERNS or c.get('pattern_color','black') not in ('black','white')):
                raise ValueError('Unknown fill pattern')
            if c['type'] in ('rect','text','shape') and c.get('pattern','none')=='noise':
                number('density',1,99,30);number('seed',0,9999,1)
            if 'space_width' in c and (c['type']!='text' or not isinstance(c['space_width'],int) or isinstance(c['space_width'],bool) or not 0<=c['space_width']<=8):
                raise ValueError('Space width: 0..8 px, on a text')
            if c['type']=='text' and (c.get('stroke','none') not in ('none','black','white') or any(not isinstance(c.get(k,False),bool) for k in ('hug','hug_w','hug_h','underline'))):
                raise ValueError('Invalid text frame')
            if not isinstance(c.get('name',''),str) or len(c.get('name',''))>32:
                raise ValueError('Layer name: at most 32 characters')
            # linked components (kept in sync by the editor; rendered and compiled like any layer).
            if not isinstance(c.get('master',False),bool) or any(not isinstance(c.get(k,''),str) or len(c.get(k,''))>64 for k in ('instance_of','master_key')) or not isinstance(c.get('synced',{}),dict):
                raise ValueError('Invalid component link')
            # component states: `state_off` states are neither drawn nor compiled; Export draws each one.
            if not isinstance(c.get('state_off',False),bool) or any(not isinstance(c.get(k,''),str) or len(c.get(k,''))>64 for k in ('state_of','state','state_key')):
                raise ValueError('Invalid component state')
            if any(k in c and (not isinstance(c[k],int) or isinstance(c[k],bool) or not 0<=c[k]<hi) for k,hi in (('cell',256),('cell_x',128),('cell_y',128))):
                raise ValueError('Invalid cell placement')
            if c.get('stroke_position','inner') not in ('inner','outer'):
                raise ValueError('Frame position: inner or outer')
            if c.get('text_case') is not None and (c.get('text_case') not in TEXT_CASES or c['type'] not in ('text','grid','list')):
                raise ValueError('Text case: upper or lower, on a text, table or list')
            if c['type']=='layout':
                number('layout_cols',1,16,3);number('layout_rows',1,16,1);number('gap_x',0,32,2);number('gap_y',0,32,2)
                if c.get('cell_fill','none') not in ('none','black','white') or c.get('cell_lines','none') not in ('none','solid','dotted') or c.get('cell_line_color','black') not in ('black','white'):
                    raise ValueError('Invalid layout cell style')
                if c.get('layout_flow','rows') not in ('rows','columns'):
                    raise ValueError('Layout fill order: rows or columns')
                if c.get('cell_w','hug') not in CELL_SIZES or c.get('cell_h','hug') not in CELL_SIZES or any(c.get(k,'start') not in CELL_ALIGNS for k in ('cell_align_x','cell_align_y')):
                    raise ValueError('Invalid layout cells')
                if c.get('stroke','none') not in ('none','black','white') or c.get('fill','none') not in ('none','black','white') or any(not isinstance(c.get(k,False),bool) for k in ('hug_w','hug_h')):
                    raise ValueError('Invalid layout frame')
                number('stroke_width',1,4,1)
            if c['type']=='list':
                number('item_gap',0,8,1);number('item_padding',0,8,1);number('selected',-1,63,-1)
                ips=c.get('item_padding_sides')
                if ips is not None and (not isinstance(ips,list) or len(ips)!=4 or any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=8 for v in ips)):
                    raise ValueError('Item padding per side: four values 0..8 (top, right, bottom, left)')
                number('highlight_padding',0,6,0);number('sep_inset',0,20,0);number('stroke_width',1,4,1)
                if any(not isinstance(c.get(k,False),bool) for k in ('hug_w','hug_h')) or c.get('box_fill','none') not in ('none','black','white') or c.get('stroke','none') not in ('none','black','white') or c.get('stroke_style','solid') not in ('solid','dotted'):
                    raise ValueError('Invalid list box')
                if c.get('item_width','text') not in ('text','full') or c.get('sep','none') not in ('none','solid','dotted','char') or c.get('sep_color','black') not in ('black','white') or not isinstance(c.get('sep_char','|'),str) or len(c.get('sep_char','|'))>3 or not isinstance(c.get('prepend_reserve',False),bool) or ('s_font' in c and not font_name(c['s_font'])):
                    raise ValueError('Invalid list layout')
                for pre in ('n_','s_'):
                    v=lambda k,d:c.get(pre+k,d)
                    if v('bg','none') not in LIST_BG or v('stroke','none') not in LIST_STROKE or v('stroke_style','solid') not in ('solid','dotted') or v('color','black') not in ('black','white') or not isinstance(v('underline',False),bool) or v('stroke_width',1) not in (1,2,3):
                        raise ValueError('Invalid list item style')
                    for k in ('prepend','append'):
                        a_=v(k,'')
                        if not isinstance(a_,str) or len(a_)>16 or a_.startswith('icon:') and not affix_glyph(a_):
                            raise ValueError('Prepend / append: up to 8 characters, or icon:<symbol>')
                if not isinstance(c.get('items',''),str) or len(c.get('items',''))>400 or c.get('orientation','vertical') not in ('vertical','horizontal','grid') or not isinstance(c.get('hug',False),bool) or c.get('text_align','start') not in ('start','center','end'):
                    raise ValueError('Invalid list')
                for k in ('list_cols','list_rows'):
                    v=c.get(k,0)
                    if not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=64:
                        raise ValueError('List columns / rows: 0 (auto) to 64')
                v=c.get('list_col_max',0)
                if not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=128:
                    raise ValueError('List max column width: 0 (auto) to 128')
                if c.get('list_col_width','hug') not in ('hug','equal'):
                    raise ValueError('List column width: hug or equal')
                if c.get('list_flow','columns') not in ('rows','columns'):
                    raise ValueError('List fill order: rows or columns')
                if c.get('check'):
                    if c.get('check_shape','square') not in LIST_SHAPES:
                        raise ValueError('Checkbox shape: square or round')
                    cs=c.get('check_size','auto')
                    if cs!='auto' and (not isinstance(cs,int) or isinstance(cs,bool) or not 5<=cs<=12):
                        raise ValueError('Checkbox size: auto or 5..12')
                    cp=c.get('check_padding',0)
                    if not isinstance(cp,int) or isinstance(cp,bool) or not 0<=cp<=3:
                        raise ValueError('Checkbox inner padding: 0..3')
                    cg=c.get('check_gap',3)
                    if not isinstance(cg,int) or isinstance(cg,bool) or not 0<=cg<=8:
                        raise ValueError('Gap between checkbox and text: 0..8')
                marks=c.get('marks','')
                if not isinstance(marks,str) or len(marks)>64 or set(marks)-set('01'):
                    raise ValueError('Checkbox states: up to 64 characters, 0 or 1')
                if c.get('orientation')=='grid':
                    cols,rows=c.get('list_cols',0) or 0,c.get('list_rows',0) or 0
                    if cols and rows and cols*rows<len(list_items(c)):
                        raise ValueError('List grid: not enough cells for its items')
            ss=c.get('stroke_sides')
            if ss is not None and (not isinstance(ss,list) or len(ss)!=4 or any(not isinstance(v,bool) for v in ss) or c['type'] not in STROKE_SIDES):
                raise ValueError('Stroke sides: four booleans (top, right, bottom, left) on a rect, text, table, layout, list or multislider')
            ps=c.get('padding_sides')
            if ps is not None and (not isinstance(ps,list) or len(ps)!=4 or any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=20 for v in ps) or c['type'] not in ('rect','group','grid','layout','text','list','multislider')):
                raise ValueError('Padding per side: four values 0..20 (top, right, bottom, left)')
            if not isinstance(c.get('text_padding',0),int) or not 0<=c.get('text_padding',0)<=16:
                raise ValueError('Text padding must be between 0 and 16')
            if not isinstance(c.get('selectable',False),bool):
                raise ValueError('Selectable must be a boolean')
            if c['type']=='line':
                ends=c.get('ends')
                if (not isinstance(ends,list) or len(ends)!=2 or any(not isinstance(p,list) or len(p)!=2 or not all(isinstance(v,int) for v in p) or not (0<=p[0]<w and 0<=p[1]<h) for p in ends)):
                    raise ValueError('Line ends must lie inside the line box')
                if (c.get('stroke_style','solid') not in LINE_STYLES or any(c.get(k,'none') not in LINE_CAPS for k in ('cap_start','cap_end'))
                        or not isinstance(c.get('stroke_width',1),int) or not 1<=c.get('stroke_width',1)<=4
                        or any(not isinstance(c.get(k,d),int) or not 1<=c.get(k,d)<=16 for k,d in (('dash',3),('gap',2)))):
                    raise ValueError('Invalid line style')
            if c['type']=='multislider':
                for key,lo,hi,default in (('count',1,64,8),('seed',0,9999,1),('range_min',-999,999,0),('range_max',-999,999,100),('level',0,100,100),('thickness',1,4,1),
                                          ('bar_width',0,32,0),('spacing',0,8,1),('segment',0,16,0),('segment_gap',1,4,1),('selected',-1,63,-1),('stroke_width',1,4,1)):number(key,lo,hi,default)
                if c.get('range_min',0)>=c.get('range_max',100):raise ValueError('range_min must be below range_max')
                for key in ('values','peaks'):ms_parse(c.get(key,''),key)
                if (c.get('source','list') not in MS_SOURCES or c.get('orientation','vertical') not in ('vertical','horizontal') or c.get('ms_style','bar') not in MS_STYLES
                        or c.get('zero_line','none') not in ('none','solid','dotted') or c.get('cane_frame','none') not in ('none','bar','slot')
                        or c.get('peak_style','none') not in ('none','line','dot') or c.get('selected_style','invert') not in ('invert','frame','marker')
                        or c.get('box_fill','none') not in ('none','black','white') or c.get('stroke','none') not in ('none','black','white')
                        or c.get('stroke_style','solid') not in ('solid','dotted') or not isinstance(c.get('signed',False),bool)):
                    raise ValueError('Invalid multislider')
                canes=c.get('canes',['solid'])
                if not isinstance(canes,list) or not 1<=len(canes)<=4 or any(not isinstance(k,str) or k!='solid' and k not in PATTERN_TESTS for k in canes):
                    raise ValueError('Canes: 1 to 4 fills, each solid or a pattern name')
                if not isinstance(c.get('ghost','none'),str) or c.get('ghost','none') not in ('none','solid')+tuple(PATTERN_TESTS):raise ValueError('Ghost: none, solid or a pattern name')
            if c['type']=='drawing':
                points=c.get('points',[])
                if not isinstance(points,list) or len(points)>8192 or c.get('pattern','solid') not in ('solid','dotted'):
                    raise ValueError('Invalid drawing')
                if any(not isinstance(p,list) or len(p)!=2 or not all(isinstance(v,int) for v in p)
                       or not (0<=p[0]<w and 0<=p[1]<h) for p in points):
                    raise ValueError('Pixel outside drawing')
        lookup={c['id']:c for c in page['components']}
        for c in page['components']:
            if 'dock_gap' in c and (not isinstance(c['dock_gap'],int) or isinstance(c['dock_gap'],bool) or not 0<=c['dock_gap']<=8):
                raise ValueError('Dock gap must be between 0 and 8')
            if not isinstance(c.get('dock_over_padding',False),bool) or not isinstance(c.get('dock_span',False),bool):
                raise ValueError('Dock over padding / full length must be booleans')
            if 'dock' in c:
                if c['dock'] not in DOCKS:
                    raise ValueError('Unknown dock side')
                if c['type'] not in FREE or c['type'] in NO_DOCK:
                    raise ValueError('This layer type cannot be docked')
                if c.get('parent') and lookup.get(c['parent'],{}).get('type') not in DOCK_PARENTS:
                    raise ValueError('Dock needs a rectangle, a group or the screen as parent')
            seen={c['id']}; parent=c.get('parent')
            while parent:
                if parent in seen or parent not in lookup or lookup[parent]['type'] not in CONTAINERS:
                    raise ValueError('Invalid or cyclic parent container')
                seen.add(parent); parent=lookup[parent].get('parent')
    return doc


def REFERENCE_NAME(name):
    return 0 < len(name) <= 64 and name.replace('_','').replace('-','').isalnum()


def reference_catalog():
    """128x64 PNGs in the references folder: shown behind the layers in the editor, never exported."""
    return [dict(id=p.stem,label=p.stem.replace('_',' ')) for p in sorted(REFERENCES.glob('*.png')) if REFERENCE_NAME(p.stem)] if REFERENCES.is_dir() else []


def reference_bits(name):
    """128x64 reference as '1' (lit, drawn black) / '0'; None when the file is missing."""
    if not REFERENCE_NAME(name):raise ValueError('Invalid reference image')
    path=REFERENCES/(name+'.png')
    if not path.exists():return None
    image=Image.open(path).convert('L')
    if image.size!=(128,64):raise ValueError('Reference image is not 128x64')
    return ''.join('1' if v<128 else '0' for v in image.getdata())


def load():
    path = STORE / 'project.json'
    return validate(json.loads(path.read_text())) if path.exists() else default_document()


def save(doc):
    validate(doc)
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / 'project.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n')
    return str(STORE / 'project.json')


def image_from_pixels(pixels):
    return Image.frombytes('L', (128,64), bytes(0 if bit else 255 for row in pixels for bit in row))


def draw_text(img,x,top,string,width,ink=1,op=None,font_key='default',uppercase=True,clip=None,font=None):
    base=FB.FONTS[font_key];font=font or base;metric=FB.metrics(font_key)
    value=P.fit(font,clean_text(string,font_key,uppercase),max(0,width))
    if 0 <= top < 64 and 0 <= x < 128:
        log=COMMANDS.get()
        if log is not None:
            # A custom space advance: one command per word, so the code generator keeps the font's own advances.
            runs=[(x,value)];cursor=x
            if font is not base:
                runs=[]
                for word in value.split(' '):
                    if word:runs.append((cursor,word))
                    cursor+=sum(font[ord(ch)]['adv'] for ch in word)+font[32]['adv']
            for rx,rv in runs:log.append(dict(type='text',x=rx,y=top,text=rv,font=font_key,top=metric['top'],height=metric['height'],clip=clip,op=ink if op is None else op))
        cursor=x
        for char in value:
            for dx,dy in font[ord(char)]['ink']:
                xx,yy=cursor+dx,top+dy-metric['top']
                if 0<=xx<128 and 0<=yy<64 and (not clip or clip['x']<=xx<clip['x']+clip['width'] and clip['y']<=yy<clip['y']+clip['height']):
                    img[yy][xx]=1-img[yy][xx] if op==2 else ink
            cursor+=font[ord(char)]['adv']
    return value,P.text_width(font,value)


def draw_glyph(img,glyph,x,y,ink):
    log=COMMANDS.get()
    if log is not None:log.append(dict(type='glyph',x=x,y=y,glyph=glyph,op=ink))
    mask=P.blank(); P.glyph(mask,glyph,x,y)
    for yy in range(max(0,y),min(64,y+5)):
        for xx in range(max(0,x),min(128,x+5)):
            if mask[yy][xx]:img[yy][xx]=ink


def page_background(page):
    return page.get('background','black')


PATTERN_TESTS=dict(checker=lambda u,v:(u+v)%2==0,dots=lambda u,v:u%2==0 and v%2==0,sparse=lambda u,v:u%4==0 and v%4==0,
                   hlines=lambda u,v:v%2==0,vlines=lambda u,v:u%2==0,diagonal=lambda u,v:(u+v)%4==0,grid=lambda u,v:u%4==0 or v%4==0,
                   dense=lambda u,v:not(u%2==0 and v%2==0),wide=lambda u,v:(v//2)%2==0,diagonal2=lambda u,v:(u-v)%4==0,
                   crosshatch=lambda u,v:(u+v)%4==0 or (u-v)%4==0,grid8=lambda u,v:u%8==0 or v%8==0,bricks=lambda u,v:v%4==0 or (u+(v//4)%2*4)%8==0)


def outline(img,x,y,x1,y1,op,width=1,dotted=False,sides=None):
    """Rectangle outline, width px inward; dotted = every other pixel along the frame.
    sides = [top, right, bottom, left] booleans; a side left out lets its neighbours run to the corner."""
    t,r,bo,l=sides or (True,)*4
    for i in range(width):
        a,b,c_,d=x+i,y+i,x1-i,y1-i
        if c_<a or d<b:break
        if not dotted:
            if t:draw_rect(img,a,b,c_,b,op)
            if bo and (d>b or not t):draw_rect(img,a,d,c_,d,op)
            lo,hi=b+(1 if t else 0),d-(1 if bo else 0)
            if hi>=lo:
                if l:draw_rect(img,a,lo,a,hi,op)
                if r and (c_>a or not l):draw_rect(img,c_,lo,c_,hi,op)
            continue
        cells=({(xx,b) for xx in range(a,c_+1)} if t else set())|({(xx,d) for xx in range(a,c_+1)} if bo else set())|({(a,yy) for yy in range(b,d+1)} if l else set())|({(c_,yy) for yy in range(b,d+1)} if r else set())
        for xx,yy in sorted(cells):
            if (xx+yy)%2==0:draw_rect(img,xx,yy,xx,yy,op)


def iso_line(a,b):
    """Pixels of a 2:1, 1:1 or vertical edge (Bresenham, inclusive)."""
    (x0,y0),(x1,y1)=a,b; dx,dy=abs(x1-x0),-abs(y1-y0); sx=1 if x0<x1 else -1; sy=1 if y0<y1 else -1; err=dx+dy; out=[]
    while True:
        out.append((x0,y0))
        if (x0,y0)==(x1,y1):return out
        e2=2*err
        if e2>=dy:err+=dy;x0+=sx
        if e2<=dx:err+=dx;y0+=sy


def line_cap_size(c,cap):
    """Arrow head length (its half-width is one less) or dot radius for this stroke width."""
    w=c.get('stroke_width',1)
    return 2+w if cap=='arrow' else w//2+1 if cap=='dot' else 0


def line_cells(c):
    """Pixels of a line layer (absolute): Bresenham centre line, thickness across the major axis, dash pattern, caps."""
    (ax,ay),(bx,by)=[(c['x']+p[0],c['y']+p[1]) for p in c['ends']]
    w=c.get('stroke_width',1); style=c.get('stroke_style','solid'); dash,gap=c.get('dash',3),c.get('gap',2)
    flat=abs(bx-ax)>=abs(by-ay); lo=-((w-1)//2); cells=set()
    # An arrow head replaces the shaft under it (a thick shaft would blunt the tip).
    tips=[(tx,ty,line_cap_size(c,'arrow')) for cap,(tx,ty) in ((c.get('cap_start','none'),(ax,ay)),(c.get('cap_end','none'),(bx,by))) if cap=='arrow' and (ax,ay)!=(bx,by)]
    for i,(x,y) in enumerate(iso_line((ax,ay),(bx,by))):
        if any(max(abs(x-tx),abs(y-ty))<r for tx,ty,r in tips):continue
        if style=='dotted' and (i//w)%2:continue
        if style=='dashed' and i%(dash+gap)>=dash:continue
        for k in range(lo,lo+w):cells.add((x,y+k) if flat else (x+k,y))
    for cap,(tx,ty),(fx,fy) in ((c.get('cap_start','none'),(ax,ay),(bx,by)),(c.get('cap_end','none'),(bx,by),(ax,ay))):
        n=line_cap_size(c,cap)
        if cap=='dot':
            cells|={(tx+dx,ty+dy) for dy in range(-n,n+1) for dx in range(-n,n+1) if dx*dx+dy*dy<=n*n}
        elif cap=='arrow' and (tx,ty)!=(fx,fy):
            # Pixel steps (Chebyshev unit): axis and 45° heads come out as clean pixel-art triangles.
            k=max(abs(tx-fx),abs(ty-fy)); ux,uy=(tx-fx)/k,(ty-fy)/k; hw=n-1
            cx,cy=tx-ux*n,ty-uy*n; r=lambda v:math.floor(v+.5)
            pts=[(tx,ty),(r(cx-uy*hw),r(cy+ux*hw)),(r(cx+uy*hw),r(cy-ux*hw))]
            if abs(tx-fx)==abs(ty-fy):  # exact 45°: legs along the axes, the classic pixel arrow
                sx,sy=(1 if tx>fx else -1),(1 if ty>fy else -1); pts=[(tx,ty),(tx-sx*(n+1),ty),(tx,ty-sy*(n+1))]
            for p0,p1 in zip(pts,pts[1:]+pts[:1]):cells|=set(iso_line(p0,p1))
            def inside(px,py):
                v=[(x2-x1)*(py-y1)-(y2-y1)*(px-x1) for (x1,y1),(x2,y2) in zip(pts,pts[1:]+pts[:1])]
                return all(e>=0 for e in v) or all(e<=0 for e in v)
            xs,ys=[q[0] for q in pts],[q[1] for q in pts]
            cells|={(px,py) for py in range(min(ys),max(ys)+1) for px in range(min(xs),max(xs)+1) if inside(px,py)}
    return cells


def draw_line(img,c,_ink):
    op={'black':1,'white':0,'invert':2}[c.get('color','black')]; area=c.get('_parent_bounds') or dict(x=0,y=0,width=128,height=64)
    fill_cells(img,{(x,y) for x,y in line_cells(c) if 0<=x<128 and 0<=y<64 and area['x']<=x<area['x']+area['width'] and area['y']<=y<area['y']+area['height']},op)


def draw_iso(img,c,_ink):
    """Isometric solid (2:1): box, wedge (ramp), pyramid, cylinder. A = right side, B = left side, H = height.
    Faces filled (empty / black / white / pattern), then edges."""
    a,b,h=c.get('iso_a',8),c.get('iso_b',8),c.get('iso_h',8); x0,y0=c['x'],c['y']; kind=c.get('iso_shape','box')
    L,T,R,B=(x0,y0+b),(x0+2*b,y0),(x0+2*b+2*a,y0+a),(x0+2*a,y0+a+b)
    down=lambda p:(p[0],p[1]+h)
    stroke=c.get('stroke','white'); ink=0 if stroke=='white' else 1
    def inside(poly,px,py):
        hit=False
        for i in range(len(poly)):
            (xa,ya),(xb,yb)=poly[i],poly[i-1]
            if (ya>py)!=(yb>py) and px<(xb-xa)*(py-ya)/(yb-ya)+xa:hit=not hit
        return hit
    box=[(xx,yy) for yy in range(c['y'],c['y']+c['height']) for xx in range(c['x'],c['x']+c['width'])]
    area=lambda poly:{(xx,yy) for xx,yy in box if inside(poly,xx,yy)}
    edge_cells=set(); edges=[]
    if kind=='cylinder':
        rx=(2*a+2*b+1)/2; ry=(a+b+1)/2; cx=x0+rx; cy=y0+ry
        disc=lambda yc:{(xx,yy) for xx,yy in box if ((xx+.5-cx)/rx)**2+((yy+.5-yc)/ry)**2<=1}
        top,bottom=disc(cy),disc(cy+h)
        body=({(xx,yy) for xx,yy in box if abs(xx+.5-cx)<=rx and cy<=yy+.5<=cy+h}|bottom)-top
        faces=dict(left={p for p in body if p[0]+.5<cx},right={p for p in body if p[0]+.5>=cx},top=top)
        rim=lambda cells:{(xx,yy) for xx,yy in cells if any((xx+dx,yy+dy) not in cells for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))}
        edge_cells=rim(top|body)|rim(top)
    else:
        if kind=='wedge' and c.get('slope','right')=='left':
            faces=dict(top=[T,R,down(B),down(L)],right=[R,down(R),down(B)])
            edges=[(T,R),(R,down(B)),(down(B),down(L)),(down(L),T),(R,down(R)),(down(R),down(B))]
        elif kind=='wedge':
            faces=dict(top=[L,T,down(R),down(B)],left=[L,down(B),down(L)])
            edges=[(L,T),(T,down(R)),(down(R),down(B)),(down(B),L),(L,down(L)),(down(L),down(B))]
        elif kind=='pyramid':
            apex=(x0+a+b,y0+(a+b)//2)
            faces=dict(left=[apex,down(L),down(B)],right=[apex,down(B),down(R)])
            edges=[(apex,down(L)),(apex,down(B)),(apex,down(R)),(down(L),down(B)),(down(B),down(R))]
        else:
            faces=dict(top=[L,T,R,B],left=[L,B,down(B),down(L)],right=[B,R,down(R),down(B)])
            edges=[(L,T),(T,R),(R,B),(B,L)]
            if h:edges+=[(L,down(L)),(B,down(B)),(R,down(R)),(down(L),down(B)),(down(B),down(R))]
        faces={k:area(v) for k,v in faces.items() if h or k=='top' or kind=='pyramid'}
    for name in ('left','right','top'):
        fill=c.get(name+'_fill','none')
        if fill=='none' or name not in faces:continue
        cells=[]
        for xx,yy in sorted(faces[name],key=lambda p:(p[1],p[0])):
            op=1 if fill=='black' else 0 if fill=='white' else (ink if PATTERN_TESTS[fill](xx-x0,yy-y0) else 1-ink)
            cells.append((xx,yy,op))
        for xx,yy,op in cells:draw_rect(img,xx,yy,xx,yy,op)
    if stroke=='none':return
    for e in edges:edge_cells.update(iso_line(*e))
    for px in sorted(edge_cells,key=lambda p:(p[1],p[0])):draw_rect(img,px[0],px[1],px[0],px[1],ink)


def draw_pattern(img,c,x0,y0,x1,y1):
    """Fill pattern in the area, relative to its corner (moves with the layer)."""
    kind=c.get('pattern','none')
    if kind=='none' or x1<x0 or y1<y0:return
    op=int(c.get('pattern_color','black')=='black'); rng=random.Random(c.get('seed',1)); density=c.get('density',30)/100
    tests=PATTERN_TESTS
    for y in range(y0,y1+1):
        row=[(rng.random()<density) if kind=='noise' else tests[kind](x-x0,y-y0) for x in range(x0,x1+1)]+[False]
        start=None
        for i,on in enumerate(row):
            if on and start is None:start=i
            if not on and start is not None:draw_rect(img,x0+start,y,x0+i-1,y,op);start=None


def draw_shadows(img,c,render_alone):
    """Drop shadows, optional inner strokes, then an outer outline of the layer + shadows."""
    token=COMMANDS.set(None)
    try:
        low,high=[[0]*128 for _ in range(64)],[[1]*128 for _ in range(64)]
        render_alone(low);render_alone(high)
    finally:COMMANDS.reset(token)
    own={(x,y) for y in range(64) for x in range(128) if (low[y][x],high[y][x])!=(0,1)}
    combined=set(own)
    o=frame_out(c)   # an outer frame belongs to the box
    box={(x,y) for y in range(c['y']-o,c['y']+c['height']+o) for x in range(c['x']-o,c['x']+c['width']+o)}
    for shadow in c.get('shadows',[]):
        dx,dy=shadow.get('dx',2),shadow.get('dy',2); op=int(shadow.get('color','black')=='black'); dotted=shadow.get('style')=='dotted'
        base=box if shadow.get('shape','box')=='box' else own
        shifted={(x+dx,y+dy) for x,y in base}
        combined|=shifted-base
        cells=shifted-base
        cells={(x,y) for x,y in cells if 0<=x<128 and 0<=y<64 and (not dotted or (x+y)%2==0)}
        fill_cells(img,cells,op)
        stroke=shadow.get('stroke','none')
        if stroke!='none':
            ring=stroke_cells(shifted,shadow.get('stroke_width',1))-base
            fill_cells(img,{(x,y) for x,y in ring if 0<=x<128 and 0<=y<64},int(stroke=='black'))
    stroke=c.get('effect_stroke','none')
    if stroke!='none':
        ring=stroke_cells(combined,c.get('effect_stroke_width',1),outside=True)
        fill_cells(img,{(x,y) for x,y in ring if 0<=x<128 and 0<=y<64},int(stroke=='black'))


def draw_shape(img,c,_ink):
    """Plain rectangle: optional fill (black/white/invert), 1 px stroke, 2 px drop shadow."""
    x,y,w,h=(c[k] for k in ('x','y','width','height')); x1,y1=x+w-1,y+h-1
    ops=dict(black=1,white=0,invert=2); fill=c.get('fill','none'); stroke=c.get('stroke','black')
    if c.get('shadow'):
        shade=int(stroke!='white')
        draw_rect(img,x1+1,y+2,x1+2,y1+2,shade); draw_rect(img,x+2,y1+1,x1,y1+2,shade)
    if c.get('radius',0):paint_cells(img,c,rounded_cells(c));return
    o=frame_out(c); inset=c.get('stroke_width',1) if stroke!='none' and not o else 0
    it,ir,ib,il=(inset*bool(v) for v in c.get('stroke_sides') or (1,)*4)
    if fill!='none' and x1-ir>=x+il and y1-ib>=y+it:draw_rect(img,x+il,y+it,x1-ir,y1-ib,ops[fill])
    draw_pattern(img,c,x+il,y+it,x1-ir,y1-ib)
    if stroke!='none':outline(img,x-o,y-o,x1+o,y1+o,ops[stroke],c.get('stroke_width',1),c.get('stroke_style','solid')=='dotted',c.get('stroke_sides'))


def draw_scrollbar(img,c,ink):
    x,y,w,h=(c[k] for k in ('x','y','width','height'))
    vertical=c.get('orientation','vertical')=='vertical'; length,breadth=(h,w) if vertical else (w,h)
    def bar(a0,a1,b0,b1,op):
        if vertical:draw_rect(img,x+b0,y+a0,x+b1,y+a1,op)
        else:draw_rect(img,x+a0,y+b0,x+a1,y+b1,op)
    track=c.get('track','arrows'); mid=(breadth-1)//2
    if track in ('arrows','arrows_thumb') and not vertical:track='line'
    if track in ('arrows','arrows_thumb'):
        # Arrows at both ends. "auto": only while rows remain above / below.
        total,visible=c.get('total',20),c.get('visible',5); first=min(c.get('position',0),max(0,total-visible))
        gx=x+(w-5)//2; auto=c.get('arrows_auto',False)
        if not auto or first>0:draw_glyph(img,P.G_UP,gx,y,ink)
        if not auto or first+visible<total:draw_glyph(img,P.G_DN,gx,y+h-3,ink)
        if track=='arrows' or h<12:return
        # Thumb between the chevrons, on a dotted centre track.
        top,span=y+5,h-10; mid=x+(w-1)//2
        for yy in range(top,top+span,2):draw_rect(img,mid,yy,mid,yy,ink)
        size=span if visible>=total else min(span,max(2,round(span*visible/total)))
        start=0 if visible>=total else round((span-size)*first/(total-visible))
        draw_rect(img,max(x,mid-1),top+start,min(x+w-1,mid+1),top+start+size-1,ink)
        return
    inset=1 if track=='outline' and length>2 and breadth>2 else 0
    if track=='outline':
        bar(0,length-1,0,breadth-1,ink)
        if inset:bar(1,length-2,1,breadth-2,1-ink)
    elif track=='line':bar(0,length-1,mid,mid,ink)
    elif track=='dotted':
        for a in range(0,length,2):bar(a,a,mid,mid,ink)
    span=length-2*inset; total,visible=c.get('total',20),c.get('visible',5)
    if visible>=total:size,start=span,0
    else:
        size=min(span,max(2 if span>=4 else 1,round(span*visible/total)))
        start=round((span-size)*min(c.get('position',0),total-visible)/(total-visible))
    bar(inset+start,inset+start+size-1,inset,breadth-1-inset,ink)


def wave_levels(c,width):
    """Deterministic test signal, one (peak 0..1, signed -1..1) pair per column."""
    rng=random.Random(c.get('seed',1)); hits=c.get('cycles',8); kind=c.get('signal','loop'); accents=(1,.35,.7,.35)
    levels=[]; smooth=.5
    for i in range(width):
        phase=i*hits/width; k=int(phase); local=phase-k; noise=rng.random()
        if kind=='sine':
            value=math.sin(2*math.pi*phase); peak=abs(value)
        elif kind=='noise':
            smooth=.6*smooth+.4*noise; peak=.2+.8*smooth; value=peak*(2*noise-1)
        else:
            envelope=(accents[k%4] if kind=='loop' else 1)*math.exp(-local*(5 if kind=='loop' else 3))
            peak=envelope*(.6+.4*noise); value=peak*math.sin(i*1.7)
        levels.append((peak,value))
    return levels


def draw_waveform(img,c,ink):
    x,y,w,h=(c[k] for k in ('x','y','width','height')); y1=y+h-1
    amount=c.get('amplitude',90)/100; display=c.get('display','mirror'); upper=y+(h-1)//2; lower=y+h//2
    style=c.get('centre_style','solid') if c.get('centre',True) else 'none'
    if style!='none':
        k=c.get('centre_width',1); first=y1-k+1 if display=='top' else max(y,upper-(k-1)//2)
        for row in range(first,min(y1,first+k-1)+1):
            if style=='solid':draw_rect(img,x,row,x+w-1,row,ink)
            else:
                for col in range(x,x+w,2):draw_rect(img,col,row,col,row,ink)
    previous=None
    for i,(peak,value) in enumerate(wave_levels(c,w)):
        if display=='mirror':
            p=round(peak*amount*(h-1)/2); draw_rect(img,x+i,max(y,upper-p),x+i,min(y1,lower+p),ink)
        elif display=='top':
            draw_rect(img,x+i,max(y,y1-round(peak*amount*(h-1))),x+i,y1,ink)
        else:
            row=y+round((1-value*amount)*(h-1)/2); a,b=(row,row) if previous is None else sorted((previous,row))
            draw_rect(img,x+i,a,x+i,b,ink); previous=row
    start,end=c.get('trim_start',-1),c.get('trim_end',-1); col=lambda pct:x+round(pct*(w-1)/100)
    a=col(start) if start>=0 else x; b=col(end) if end>=0 else x+w-1
    if b<a:a,b=b,a
    outside=c.get('trim_outside','keep')
    if outside!='keep':
        for lo,hi in ((x,a-1),(b+1,x+w-1)):
            if hi<lo:continue
            if outside=='invert':draw_rect(img,lo,y,hi,y1,2)
            else:fill_cells(img,{(xx,yy) for yy in range(y,y1+1) for xx in range(lo,hi+1) if (xx+yy)%2==0},1-ink)
    mop=2 if c.get('marker_op','ink')=='invert' else ink; dotted=c.get('trim_style','solid')=='dotted'
    def marker(column,top,bottom):
        if dotted:fill_cells(img,{(column,yy) for yy in range(top,bottom+1) if (yy-top)%2==0},mop)
        else:draw_rect(img,column,top,column,bottom,mop)
    for pct,side in ((start,1),(end,-1)):
        if pct<0:continue
        column=col(pct); marker(column,y,y1)
    n=c.get('slices',0)
    if n>1:
        length=c.get('slice_len',0) or h
        for i in range(1,n):marker(a+round(i*(b-a)/n),y,min(y1,y+length-1))
    if c.get('playhead',-1)>=0:
        column=x+round(c['playhead']*(w-1)/100); draw_rect(img,column,y,column,y1,2)


def draw_placeholder(img,c,ink):
    """Reserved zone: shown in previews and PNG mock-ups, never compiled (bounds go to ui_commands.json)."""
    token=COMMANDS.set(None)
    try:
        x,y,w,h=(c[k] for k in ('x','y','width','height')); x1,y1=x+w-1,y+h-1
        def dot(px,py):
            if (px+py)%2==0:img[py][px]=ink
        for xx in range(x,x1+1):dot(xx,y);dot(xx,y1)
        for yy in range(y,y1+1):dot(x,yy);dot(x1,yy)
        steps=max(w,h)
        for i in range(0,steps,2):
            t=i/max(1,steps-1); px=x+round(t*(w-1)); img[y+round(t*(h-1))][px]=img[y1-round(t*(h-1))][px]=ink
        name=clean_text(c.get('name',''))
        font=FB.FONTS['default']; tw=P.text_width(font,name); fh=FB.metrics('default',True)['height']
        if name and tw+4<=w and fh+4<=h:
            tx=x+(w-tw)//2; ty=y+(h-fh)//2
            draw_rect(img,tx-2,ty-2,tx+tw+1,ty+fh+1,1-ink); draw_text(img,tx,ty,name,tw,ink)
    finally:COMMANDS.reset(token)


def draw_image(img,c,_ink):
    """Imported PNG: '1' black, '0' white, '.' transparent; runs of one colour become rectangles."""
    x,y,w=c['x'],c['y'],c['width']; bits=c['pixels']; swap=c.get('invert',False)
    def op(v):
        if c.get('xor'):return None if v=='.' else 2
        if v=='.' or v=='0' and c.get('white','transparent')=='transparent':return None
        return int((v=='1')!=swap)
    for yy in range(c['height']):
        row=bits[yy*w:(yy+1)*w]; start=0
        for xx in range(1,w+1):
            if xx==w or op(row[xx])!=op(row[start]):
                if op(row[start]) is not None:draw_rect(img,x+start,y+yy,x+xx-1,y+yy,op(row[start]))
                start=xx


def import_image(data):
    """PNG -> image layer pixels. Alpha < 50 % = transparent, else luminance threshold at 50 %."""
    raw=base64.b64decode(data,validate=True)
    if len(raw)>200000:raise ValueError('PNG too large')
    image=Image.open(io.BytesIO(raw)).convert('RGBA')
    box=image.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
    if not box:raise ValueError('PNG is fully transparent')
    image=image.crop(box)
    if image.width>128 or image.height>64:raise ValueError(f'Image {image.width}×{image.height}: at most 128×64 after trimming transparent margins')
    pixels=[];approx=0
    for r,g,b,a in image.getdata():
        if a<128:pixels.append('.');approx+=a>0;continue
        lum=(r*299+g*587+b*114)//1000;pixels.append('1' if lum<128 else '0')
        approx+=a<255 or not (r==g==b and r in (0,255))
    return dict(width=image.width,height=image.height,pixels=''.join(pixels),approximated=approx)


def fill_cells(img,cells,op):
    """Pixels as row runs: one rectangle command per horizontal run."""
    rows={}
    for x,y in cells:rows.setdefault(y,[]).append(x)
    for y in sorted(rows):
        xs=sorted(rows[y]);start=xs[0]
        for i,x in enumerate(xs):
            if i==len(xs)-1 or xs[i+1]!=x+1:
                draw_rect(img,start,y,x,y,op)
                if i<len(xs)-1:start=xs[i+1]


def polygon_cells(points,x0,y0,w,h):
    """Pixels whose centre lies inside the polygon (even-odd), points in layer-local units 0..w / 0..h."""
    out=set()
    for v in range(h):
        py=v+.5+1.3e-4
        for u in range(w):
            px=u+.5+1e-4;hit=False
            for i in range(len(points)):
                (xa,ya),(xb,yb)=points[i],points[i-1]
                if (ya>py)!=(yb>py) and px<(xb-xa)*(py-ya)/(yb-ya)+xa:hit=not hit
            if hit:out.add((x0+u,y0+v))
    return out


def directed(points,w,h,direction):
    """Points drawn pointing right (along = length, across = breadth) turned to the chosen direction."""
    if direction=='left':return [(w-a,b) for a,b in points]
    if direction=='down':return [(b,a) for a,b in points]
    if direction=='up':return [(b,h-a) for a,b in points]
    return points


def shape_cells(c):
    """Outline of a 2D shape as the set of pixels it covers."""
    x0,y0,w,h=(c[k] for k in ('x','y','width','height')); kind=c.get('shape','ellipse')
    if kind=='ellipse':
        rx,ry=w/2,h/2
        return {(x0+u,y0+v) for v in range(h) for u in range(w) if ((u+.5-rx)/rx)**2+((v+.5-ry)/ry)**2<=1+1e-9}
    direction=c.get('direction','right'); along,across=(h,w) if direction in ('up','down') else (w,h)
    if kind=='triangle':pts=directed([(0,0),(along,across/2),(0,across)],w,h,direction)
    elif kind=='arrow':
        head=min(along,c.get('head',0) or max(2,(across+1)//2)); shaft=min(across,c.get('shaft',0) or max(1,round(across/3)))
        a,b=(across-shaft)/2,(across+shaft)/2; neck=along-head
        pts=[(0,a),(neck,a),(neck,0),(along,across/2),(neck,across),(neck,b),(0,b)] if neck>0 else [(0,0),(along,across/2),(0,across)]
        pts=directed(pts,w,h,direction)
    elif kind=='diamond':pts=[(w/2,0),(w,h/2),(w/2,h),(0,h/2)]
    else:
        n=c.get('sides',5); turn=math.radians(c.get('rotation',0)-90); star=kind=='star'; inner=c.get('inner',50)/100; pts=[]
        for i in range(2*n if star else n):
            r=inner if star and i%2 else 1; t=turn+2*math.pi*i/(2*n if star else n)
            pts.append((w/2+r*w/2*math.cos(t),h/2+r*h/2*math.sin(t)))
    return polygon_cells(pts,x0,y0,w,h)


def rounded_cells(c):
    x0,y0,w,h=(c[k] for k in ('x','y','width','height')); r=min(c.get('radius',0),w//2,h//2); out=set()
    for v in range(h):
        for u in range(w):
            cu=r if u<r else w-r if u>=w-r else None; cv=r if v<r else h-r if v>=h-r else None
            if cu is not None and cv is not None and math.hypot(u+.5-cu,v+.5-cv)>r-.5+1e-9:continue
            out.add((x0+u,y0+v))
    return out


def stroke_cells(cells,width,outside=False):
    """Inner pixel rings, or an outer halo with square corners. Clip only after finding the contour."""
    area=set(cells); ring=set()
    for _ in range(width):
        if outside:
            layer={(x+dx,y+dy) for x,y in area for dx in (-1,0,1) for dy in (-1,0,1)}-area
            area|=layer
        else:
            layer={(x,y) for x,y in area if any((x+dx,y+dy) not in area for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))}
            area-=layer
        ring|=layer
    return ring


def paint_cells(img,c,cells):
    """Fill, fill pattern then stroke (k px inward, solid or dotted) of a pixel area."""
    stroke=c.get('stroke','black'); k=c.get('stroke_width',1) if stroke!='none' else 0
    ring=stroke_cells(cells,k); inner=cells-ring
    ops=dict(black=1,white=0,invert=2); fill=c.get('fill','none')
    if fill!='none' and inner:fill_cells(img,inner,ops[fill])
    kind=c.get('pattern','none')
    if kind!='none' and inner:
        rng=random.Random(c.get('seed',1)); density=c.get('density',30)/100; x0,y0=c['x'],c['y']
        on={(x,y) for x,y in sorted(inner,key=lambda p:(p[1],p[0])) if ((rng.random()<density) if kind=='noise' else PATTERN_TESTS[kind](x-x0,y-y0))}
        if on:fill_cells(img,on,int(c.get('pattern_color','black')=='black'))
    if k:
        if c.get('stroke_style','solid')=='dotted':ring={(x,y) for x,y in ring if (x+y)%2==0}
        if ring:fill_cells(img,ring,ops[stroke])


def draw_2d(img,c,_ink):
    """Ellipse / circle, triangle, arrow, diamond, regular polygon, star."""
    paint_cells(img,c,shape_cells(c))


def grid_lines(start,size,count):
    """Inner separators of `count` equal cells over `size` pixels (frame columns excluded)."""
    return [start+round(i*(size-1)/count) for i in range(1,count)]


def grid_row_lines(c,y,h,k):
    """Row separators; with a header height, header rows get that height and the rest share the remainder."""
    rows=c.get('grid_rows',3); hr=min(c.get('header_rows',0),rows); hh=c.get('header_height',0); y1=y+h-1
    if not hh or not hr or hr>=rows:return grid_lines(y,h,rows)
    lines=[y+k+i*(hh+1)+hh for i in range(hr)]
    lines+=grid_lines(lines[-1],y1-lines[-1]+1,rows-hr)
    return [v for v in lines if y<v<y1]


def draw_grid(img,c,_ink):
    """Grid / table: optional cell fill, header rows/columns, inner lines, outer frame, header labels."""
    x,y,w,h=(c[k] for k in ('x','y','width','height')); x1,y1=x+w-1,y+h-1
    stroke=c.get('stroke','black'); op=int(stroke!='white'); outer=c.get('outer',True) and stroke!='none'
    k=c.get('stroke_width',1) if outer else 0
    rows,cols=c.get('grid_rows',3),c.get('grid_cols',4); ys,xs=grid_row_lines(c,y,h,k),grid_lines(x,w,cols)
    fill=c.get('fill','none')
    if fill!='none' and x1-k>=x+k and y1-k>=y+k:draw_rect(img,x+k,y+k,x1-k,y1-k,int(fill=='black'))
    hr,hc=min(c.get('header_rows',0),rows),min(c.get('header_cols',0),cols)
    # By default no separator inside a header: a line segment is skipped when both its sides are header cells.
    clean=c.get('header','invert')!='none' and not c.get('header_lines',False)
    head_y=ys[hr-1] if hr and hr<=len(ys) else y1-k+1; head_x=xs[hc-1] if hc and hc<=len(xs) else x1-k+1
    def segments(lo,hi,cut,both_header_before,both_header_after):
        out=[]
        for a,b,inside in ((lo,cut-1,both_header_before),(cut,hi,both_header_after)):
            a,b=max(a,lo),min(b,hi)
            if b>=a and not (clean and inside):out.append((a,b))
        return out
    if stroke!='none':
        for key,lines,vertical in (('lines_h',ys,False),('lines_v',xs,True)):
            style=c.get(key,'solid')
            if style=='none':continue
            for index,pos in enumerate(lines):
                if vertical:parts=segments(y+k,y1-k,head_y,hr>0,index+1<hc)
                else:parts=segments(x+k,x1-k,head_x,hc>0,index+1<hr)
                for a,b in parts:
                    if vertical:
                        if style=='solid':draw_rect(img,pos,a,pos,b,op)
                        else:fill_cells(img,{(pos,yy) for yy in range(a,b+1) if (pos+yy)%2==0},op)
                    else:
                        if style=='solid':draw_rect(img,a,pos,b,pos,op)
                        else:fill_cells(img,{(xx,pos) for xx in range(a,b+1) if (xx+pos)%2==0},op)
    header=c.get('header','invert'); hops=dict(invert=2,black=1,white=0)
    if header!='none':
        if hr:
            bottom=(ys[hr-1]-1) if hr<=len(ys) else y1-k
            if bottom>=y+k:draw_rect(img,x+k,y+k,x1-k,bottom,hops[header])
        if hc:
            right=(xs[hc-1]-1) if hc<cols else x1-k; top=(ys[hr-1]+(0 if clean else 1)) if hr and hr<=len(ys) else y+k
            if hr>=rows:top=y1-k+1
            if right>=x+k and top<=y1-k:draw_rect(img,x+k,top,right,y1-k,hops[header])
    # Labels: header_text along the first row, side_text down the first column (rows under the header).
    font_key=c.get('header_font','default'); font=FB.FONTS[font_key]; fh=FB.metrics(font_key,True)['height']; align=c.get('header_align','center')
    col_x=[x+k]+[v+1 for v in xs]; col_r=[v-1 for v in xs]+[x1-k]; row_y=[y+k]+[v+1 for v in ys]; row_b=[v-1 for v in ys]+[y1-k]
    def label(text,col,row,in_header):
        cx,cr,cy,cb=col_x[col],col_r[col],row_y[row],row_b[row]; cw=cr-cx+1-2
        if cw<1 or cb<cy or not text:return
        ink=(2 if header=='invert' else 0 if header=='black' else 1) if in_header and header!='none' else op
        value=P.fit(font,clean_text(cased(c,text),font_key,False),cw); tw=P.text_width(font,value)
        tx=cx+1+((cw-tw)//2 if align=='center' else cw-tw if align=='end' else 0); ty=cy+max(0,(cb-cy+1-fh)//2)
        draw_text(img,tx,ty,value,cw,ink=ink if ink!=2 else 1,op=2 if ink==2 else None,font_key=font_key,uppercase=False,clip=dict(x=cx,y=cy,width=cr-cx+1,height=cb-cy+1))
    for col,text in enumerate(split_labels(c.get('header_text',''))[:cols]):label(text.strip(),col,0,hr>0 or hc>col)
    for i,text in enumerate(split_labels(c.get('side_text',''))):
        row=(1 if hr else 0)+i
        if row<rows:label(text.strip(),0,row,hc>0 or hr>row)
    o=frame_out(c)
    if outer:outline(img,x-o,y-o,x1+o,y1+o,op,k,c.get('stroke_style','solid')=='dotted',c.get('stroke_sides'))


def draw_layout(img,c,_ink):
    """Auto layout frame: optional fill and outline (none by default: an invisible container)."""
    x,y,w,h=(c[k] for k in ('x','y','width','height')); stroke=c.get('stroke','none'); k=c.get('stroke_width',1) if stroke!='none' else 0
    if c.get('fill','none')!='none' and w>2*k and h>2*k:draw_rect(img,x+k,y+k,x+w-1-k,y+h-1-k,int(c['fill']=='black'))
    cells=c.get('_cells') or []
    if c.get('cell_fill','none')!='none':
        for cx,cy,cw,ch in cells:
            if cw>0 and ch>0:draw_rect(img,cx,cy,cx+cw-1,cy+ch-1,int(c['cell_fill']=='black'))
    if c.get('cell_lines','none')!='none' and cells:
        # Separators in the gaps between columns / rows, across the whole grid.
        op=int(c.get('cell_line_color','black')=='black'); dotted=c['cell_lines']=='dotted'
        x0,y0=min(v[0] for v in cells),min(v[1] for v in cells)
        x1,y1=max(v[0]+v[2]-1 for v in cells),max(v[1]+v[3]-1 for v in cells)
        cols=sorted({(v[0],v[0]+v[2]-1) for v in cells}); rows=sorted({(v[1],v[1]+v[3]-1) for v in cells})
        gx,gy=c.get('gap_x',2),c.get('gap_y',2)
        for (_,right),_next in zip(cols,cols[1:]):
            sx=right+1+(gx-1)//2
            if dotted:fill_cells(img,{(sx,yy) for yy in range(y0,y1+1) if (yy-y0)%2==0},op)
            else:draw_rect(img,sx,y0,sx,y1,op)
        for (_,bottom),_next in zip(rows,rows[1:]):
            sy=bottom+1+(gy-1)//2
            if dotted:fill_cells(img,{(xx,sy) for xx in range(x0,x1+1) if (xx-x0)%2==0},op)
            else:draw_rect(img,x0,sy,x1,sy,op)
    o=frame_out(c)
    if k:outline(img,x-o,y-o,x+w-1+o,y+h-1+o,int(stroke=='black'),k,c.get('stroke_style','solid')=='dotted',c.get('stroke_sides'))


LIST_BG=('none','black','white','invert'); LIST_STROKE=('none','black','white')
LIST_STYLE_KEYS=('bg','stroke','stroke_width','stroke_style','color','underline','prepend','append')
LIST_SHAPES=('square','round')


def list_style(c,selected):
    """Item style: `n_*` for every item; `s_*` for the selected one, each key falling back to the normal style
    (background: invert, like before). Text colour of the selected one follows its background unless set."""
    n=dict(bg=c.get('n_bg','none'),stroke=c.get('n_stroke','none'),stroke_width=c.get('n_stroke_width',1),
           stroke_style=c.get('n_stroke_style','solid'),color=c.get('n_color',c.get('color','black')),
           underline=c.get('n_underline',False),prepend=c.get('n_prepend',''),append=c.get('n_append',''),font=c.get('font','default'))
    if not selected:return n
    st=dict(n,bg=c.get('s_bg','invert'),font=c.get('s_font') or n['font'])
    for k in ('stroke','stroke_width','stroke_style','underline','prepend','append'):
        if 's_'+k in c:st[k]=c['s_'+k]
    st['color']=c.get('s_color','white' if st['bg']=='black' else 'black' if st['bg']=='white' else n['color'])
    return st


def affix_glyph(value):
    """'icon:Name' -> an original 5x5 symbol (width, rows) for draw_glyph, else None (plain text)."""
    if isinstance(value,str) and value.startswith('icon:') and value[5:] in FB.BASIC_SYMBOLS:
        return (5,[int(r,2)<<3 for r in FB.BASIC_SYMBOLS[value[5:]]])
    return None


def affix_width(value,font_key):
    if not value:return 0
    if affix_glyph(value):return 5+2
    return P.text_width(FB.FONTS[font_key],clean_text(value,font_key,False))+2


def check_size(c,fh):
    """Checkbox side in pixels: `check_size` 5..12, or auto = the row text height minus two."""
    v=c.get('check_size','auto')
    return max(5,min(12,fh-2)) if v=='auto' else v


def disc_cells(x,y,s):
    """Filled disc of side s, as pixels (a 5x5 circle loses its corners)."""
    mid=(s-1)/2; r=s/2-0.15
    return {(x+i,y+j) for j in range(s) for i in range(s) if (i-mid)**2+(j-mid)**2<=r*r}


def check_cells(x,y,s,shape,pad,checked):
    """Pixels of a checkbox: a one-pixel ring, plus a filled core inset by `pad` when checked.
    The padding is clamped so the core never disappears into the ring."""
    if s<1:return set()
    pad=min(pad,max(0,(s-3)//2))
    if shape=='round':
        cells=disc_cells(x,y,s)
        if s>2:cells-=disc_cells(x+1,y+1,s-2)
        if checked and s-2-2*pad>=1:cells|=disc_cells(x+1+pad,y+1+pad,s-2-2*pad)
        return cells
    cells=set()
    for i in range(s):
        cells|={(x+i,y),(x+i,y+s-1),(x,y+i),(x+s-1,y+i)}
    if checked and s-2-2*pad>=1:
        for j in range(1+pad,s-1-pad):
            for i in range(1+pad,s-1-pad):cells.add((x+i,y+j))
    return cells


def list_geometry(c,x,y,w,h,hug=False):
    """Every item of a list placed in (x, y, w, h): its box, text, checkbox, affixes and style, plus the
    separators. Shared by the Hug size and the drawing so both always agree. `orientation` grid reflows the
    items into `list_cols` x `list_rows` cells (0 or absent = automatic)."""
    items=list_items(c); sel=c.get('selected',-1); orientation=c.get('orientation','vertical')
    if not items:return [],[],(1,1),''
    grid=orientation=='grid'; horizontal=orientation=='horizontal'
    pt,pr,pb,pl=c.get('item_padding_sides') or (c.get('item_padding',1),)*4; gap=c.get('item_gap',1); sp=c.get('highlight_padding',0); full=c.get('item_width','text')=='full' and not hug   # Hug: Full row spans the content, not the room
    styles=[list_style(c,False),list_style(c,True)]
    fh=max(FB.metrics(st['font'],True)['height'] for st in styles)
    check=bool(c.get('check')); cs=check_size(c,fh) if check else 0; mw=cs+(c.get('check_gap',3) if check else 0)
    ch=max(fh,cs); rh=pt+ch+pb
    sep=c.get('sep','none'); sep_char=clean_text(c.get('sep_char','|'),c.get('font','default'),False) if sep=='char' else ''
    sep_w=P.text_width(FB.FONTS[c.get('font','default')],sep_char) if sep_char else 0
    reserve=max(affix_width(st['prepend'],st['font']) for st in styles) if c.get('prepend_reserve') else None
    meta=[]
    for i,item in enumerate(items):
        st=styles[int(i==sel)]
        meta.append(dict(style=st,font=FB.FONTS[st['font']],text=clean_text(cased(c,item),st['font'],False),
            pw=reserve if reserve is not None else affix_width(st['prepend'],st['font']),
            aw=affix_width(st['append'],st['font'])))
    def place(i,cx,cw,ry,row_h,top,check_top,span=True):
        m=meta[i]; inner=cw-pl-pr
        value=P.fit(m['font'],m['text'],max(0,inner-mw-m['pw']-m['aw'])); tw=P.text_width(m['font'],value)
        block=mw+m['pw']+tw+m['aw']; mode='start' if hug or horizontal else c.get('text_align','start')
        left=cx+pl+((inner-block)//2 if mode=='center' else inner-block if mode=='end' else 0)
        box=[cx if full and span else left-pl,ry,(cx+cw-1) if full and span else left+block-1+pr,ry+row_h-1]
        core=list(box)
        if i==sel and sp:box=[box[0]-sp,box[1]-sp,box[2]+sp,box[3]+sp]
        return dict(index=i,box=box,core=core,left=left,top=top,check_top=check_top,value=value,tw=tw,
            pw=m['pw'],aw=m['aw'],mw=mw,cs=cs,style=m['style'],selected=i==sel)
    out=[]; seps=[]
    if grid:
        n=len(items); cols=c.get('list_cols',0) or 0; nrows=c.get('list_rows',0) or 0; flow=c.get('list_flow','columns'); cap=c.get('list_col_max',0) or 0; col_mode=c.get('list_col_width','hug')
        if cols and nrows:
            if cols*nrows<n:raise ValueError('List grid: not enough cells for its items')
        elif cols:nrows=-(-n//cols)
        elif nrows:cols=-(-n//nrows)
        else:
            widest=max([mw+m['pw']+P.text_width(m['font'],m['text'])+m['aw']+pl+pr for m in meta] or [1])
            target=min(widest,cap) if cap else widest
            cols=1 if hug else max(1,min(64,n or 1,(w+gap)//(max(1,target)+gap)))
            nrows=max(1,-(-(n or 1)//max(1,cols)))
        cols=max(1,min(64,cols)); nrows=max(1,min(64,nrows))
        if cols*nrows<n:raise ValueError('List grid: not enough cells for its items')
        slot=(lambda k:(k//nrows,k%nrows)) if flow=='columns' else (lambda k:(k%cols,k//cols))
        natural=[0]*cols
        for k,m in enumerate(meta):
            j,_=slot(k); natural[j]=max(natural[j],mw+m['pw']+P.text_width(m['font'],m['text'])+m['aw']+pl+pr)
        if hug or col_mode=='hug':
            fill=max(natural) if natural and max(natural)>0 else 1
            cw=[v if v else fill for v in natural]
        else:
            free=max(0,w-gap*(cols-1)); cw=[max(1,free//cols+(1 if j<free%cols else 0)) for j in range(cols)]
            widest=max(natural) if natural else 1
            if widest>1:cw=[max(v,widest) for v in cw]   # Equal never shrinks a column below its widest item
        if cap:cw=[max(1,min(v,cap)) for v in cw]
        col_x=[];cursor=x
        for j in range(cols):col_x.append(cursor);cursor+=cw[j]+gap
        for k in range(n):
            j,r=slot(k); ry=y+r*(rh+gap)
            out.append(place(k,col_x[j],cw[j],ry,rh,ry+pt+(ch-fh)//2,ry+pt+(ch-cs)//2))
        right=col_x[-1]+cw[-1]; bottom=y+nrows*rh+(nrows-1)*gap
        if sep in ('solid','dotted'):
            for r in range(1,nrows):seps.append(('h',y+r*(rh+gap)-gap//2))
            for j in range(1,cols):seps.append(('v',col_x[j]-gap//2))
        return out,seps,(max(1,right-x),max(1,bottom-y)),''
    if horizontal:
        cx=x
        for k in range(len(meta)):
            if out and cx>x+w-1:break
            top=y+max(0,(h-fh)//2) if full else y+pt+(ch-fh)//2
            ctop=y+max(0,(h-cs)//2) if full else y+pt+(ch-cs)//2
            it=place(k,cx,x+w-cx,y,h if full else rh,top,ctop,span=False)
            out.append(it); cx=it['core'][2]+1+gap+((sep_w+gap) if sep_char else 0)
        for a,b in zip(out,out[1:]):
            seps.append(('v',a['core'][2]+1+(gap-1)//2) if not sep_char else ('char',a['core'][2]+1+gap))
    else:
        cy=y
        for k in range(len(meta)):
            if out and cy>y+h-1:break
            it=place(k,x,w,cy,rh,cy+pt+(ch-fh)//2,cy+pt+(ch-cs)//2)
            out.append(it); cy=it['core'][3]+1+gap
        for a,b in zip(out,out[1:]):seps.append(('h',a['core'][3]+1+(gap-1)//2))
    right=max([it['core'][2] for it in out] or [x-1]); bottom=max([it['core'][3] for it in out] or [y-1])
    return out,seps,(max(1,right-x+1),max(1,bottom-y+1)),sep_char


def list_box(c):
    """List frame inset (inner frame width) and padding (top, right, bottom, left) around the items."""
    k=c.get('stroke_width',1) if c.get('stroke','none')!='none' and not frame_out(c) else 0
    return k,sides(c,'padding')


def list_size(c):
    """Hug size of a list: every item with its padding, affixes and checkbox, gaps (and separators) between
    items, plus the list's own inner frame and padding. A fixed width (Height: Hug content only) is used as
    is, so a grid finds the same columns it will draw."""
    hug=bool(c.get('hug') or c.get('hug_w')); k,(pt,pr,pb,pl)=list_box(c)
    w=10000 if hug else max(0,c['width']-2*k-pl-pr)
    _,_,(cw,ch),_=list_geometry(c,0,0,w,10000,hug=hug)
    return max(1,cw+pl+pr+2*k),max(1,ch+pt+pb+2*k)


def draw_list(img,c,ink):
    """List: comma-separated items, one per row, side by side or in a grid; per-state background, stroke, text
    colour, underline, checkbox, prepend / append; the selected one may grow (highlight padding); separators."""
    ops=dict(black=1,white=0); X,Y,W,H=(c[k] for k in ('x','y','width','height'))
    if c.get('box_fill','none')!='none':draw_rect(img,X,Y,X+W-1,Y+H-1,ops[c['box_fill']])
    k,(pt,pr,pb,pl)=list_box(c); x,y=X+k+pl,Y+k+pt; w,h=max(0,W-2*k-pl-pr),max(0,H-2*k-pt-pb)
    clip=dict(x=x,y=y,width=w,height=h); cl=lambda b:(max(x,b[0]),max(y,b[1]),min(x+w-1,b[2]),min(y+h-1,b[3]))
    items,seps,size,sep_char=list_geometry(c,x,y,w,h); is_grid=c.get('orientation')=='grid'
    check=c.get('check',False); shape=c.get('check_shape','square'); pad=c.get('check_padding',0); marks=c.get('marks','') if check else ''
    for it in items:
        st=it['style'];b=cl(it['box']);ok=b[0]<=b[2] and b[1]<=b[3]
        if ok and st['bg'] in ops:draw_rect(img,*b,ops[st['bg']])
        if ok and st['stroke']!='none':outline(img,*b,ops[st['stroke']],st['stroke_width'],st['stroke_style']=='dotted')
        op=ops[st['color']]; tx=it['left']+it['mw']
        if check and it['cs']:
            on=it['index']<len(marks) and marks[it['index']]=='1'
            fill_cells(img,{(xx,yy) for xx,yy in check_cells(it['left'],it['check_top'],it['cs'],shape,pad,on) if x<=xx<x+w and y<=yy<y+h},op)
        for value,at in ((st['prepend'],tx),(st['append'],tx+it['pw']+it['tw']+(2 if it['tw'] else 0))):
            if not value:continue
            g=affix_glyph(value)
            if g:
                gy=it['top']+(FB.metrics(st['font'],True)['height']-5)//2
                if x<=at and at+5<=x+w and y<=gy and gy+5<=y+h:draw_glyph(img,g,at,gy,op)
            else:draw_text(img,at,it['top'],value,x+w-at,op,font_key=st['font'],uppercase=False,clip=clip)
        if it['value']:
            draw_text(img,tx+it['pw'],it['top'],it['value'],it['tw']+1,op,font_key=st['font'],uppercase=False,clip=clip)
            if st['underline']:
                uy=it['top']+FB.metrics(st['font'],True)['height']
                ux0,ux1=max(x,tx+it['pw']),min(x+w-1,tx+it['pw']+it['tw']-1)
                if y<=uy<y+h and ux0<=ux1:draw_rect(img,ux0,uy,ux1,uy,op)
        if ok and st['bg']=='invert':draw_rect(img,*b,2)
    sop=ops[c.get('sep_color',c.get('color','black'))]; inset=c.get('sep_inset',0); dotted=c.get('sep')=='dotted'
    hx1=min(x+size[0]-1,x+w-1) if is_grid else x+w-1
    vy1=min(y+size[1]-1,y+h-1) if is_grid else y+h-1
    for kind,pos in seps if c.get('sep','none')!='none' else []:
        if kind=='char':
            top=items[0]['top'];draw_text(img,pos,top,sep_char,x+w-pos,sop,font_key=c.get('font','default'),uppercase=False,clip=clip)
        elif kind=='h' and y<=pos<y+h:
            a,b_=x+inset,hx1-inset
            if dotted:fill_cells(img,{(xx,pos) for xx in range(a,b_+1) if (xx-a)%2==0},sop)
            elif a<=b_:draw_rect(img,a,pos,b_,pos,sop)
        elif kind=='v' and x<=pos<x+w:
            a,b_=y+inset,vy1-inset
            if dotted:fill_cells(img,{(pos,yy) for yy in range(a,b_+1) if (yy-a)%2==0},sop)
            elif a<=b_:draw_rect(img,pos,a,pos,b_,sop)
    if c.get('stroke','none')!='none':
        o=frame_out(c);outline(img,X-o,Y-o,X+W-1+o,Y+H-1+o,ops[c['stroke']],c.get('stroke_width',1),c.get('stroke_style','solid')=='dotted',c.get('stroke_sides'))


MS_SOURCES = ('list', 'ramp', 'sine', 'random', 'noise')
MS_STYLES = ('bar', 'hollow', 'thin', 'point', 'line')


def ms_parse(text,key='values'):
    """Integers of a comma-separated string (at most 64, 400 characters)."""
    if not isinstance(text,str) or len(text)>400:raise ValueError(f'{key}: text of at most 400 characters')
    out=[]
    for part in text.split(','):
        part=part.strip()
        if not part:continue
        if not re.fullmatch(r'-?\d{1,6}',part):raise ValueError(f'{key}: integers separated by commas')
        out.append(int(part))
    if len(out)>64:raise ValueError(f'{key}: at most 64 values')
    return out


def ms_values(c):
    """Slider values (clamped to the range): typed list or generated ramp / sine / random / noise."""
    lo,hi=c.get('range_min',0),c.get('range_max',100); src=c.get('source','list'); n=c.get('count',8)
    if src=='list':vals=ms_parse(c.get('values',''))
    elif src=='ramp':vals=[lo+(hi-lo)*i/max(n-1,1) for i in range(n)]
    elif src=='sine':vals=[lo+(hi-lo)*(.5+.5*math.sin(2*math.pi*i/n)) for i in range(n)]
    else:
        rng=random.Random(c.get('seed',1)); raw=[rng.random() for _ in range(n)]
        if src=='noise':raw=[(raw[max(i-1,0)]+2*raw[i]+raw[min(i+1,n-1)])/4 for i in range(n)]
        vals=[lo+(hi-lo)*r for r in raw]
    return [min(hi,max(lo,math.floor(v+.5))) for v in vals]


def draw_multislider(img,c,ink):
    """Simplified Max multislider: sliders side by side (vertical) or stacked (horizontal) in the box content, drawn with
    draw_rect / fill_cells only. `along` = value axis counted from the baseline end, `across` = slider axis."""
    X,Y,W,H=(c[k] for k in ('x','y','width','height')); ops=dict(black=1,white=0)
    if c.get('box_fill','none')!='none':draw_rect(img,X,Y,X+W-1,Y+H-1,ops[c['box_fill']])
    k,(pt,pr,pb,pl)=list_box(c); cx,cy=X+k+pl,Y+k+pt; cw,ch=max(0,W-2*k-pl-pr),max(0,H-2*k-pt-pb)
    def finish():
        if c.get('stroke','none')!='none':
            o=frame_out(c);outline(img,X-o,Y-o,X+W-1+o,Y+H-1+o,ops[c['stroke']],c.get('stroke_width',1),c.get('stroke_style','solid')=='dotted',c.get('stroke_sides'))
    vertical=c.get('orientation','vertical')=='vertical'; vals=ms_values(c); n=len(vals)
    if not cw or not ch or not n:return finish()
    lo,hi=c.get('range_min',0),c.get('range_max',100); style=c.get('ms_style','bar'); th=c.get('thickness',1); level=c.get('level',100)
    L,A=(ch,cw) if vertical else (cw,ch); sp=c.get('spacing',1); seg,gap=c.get('segment',0),c.get('segment_gap',1)
    signed=c.get('signed',False); selected,sel_style=c.get('selected',-1),c.get('selected_style','invert')
    marker=sel_style=='marker' and L>=4 and 0<=selected<n   # marker row / column reserved beside the bars
    Lb=L-2 if marker else L
    bw=c.get('bar_width',0) or max(1,(A-sp*(n-1))//n)
    off=0 if c.get('bar_width') else max(0,(A-(n*bw+sp*(n-1)))//2)
    canes=c.get('canes',['solid']); cane=lambda i:None if canes[i%len(canes)]=='solid' else PATTERN_TESTS[canes[i%len(canes)]]
    ghost=c.get('ghost','none'); ghost_test=PATTERN_TESTS.get(ghost)
    pos=lambda v:(2*(v-lo)*Lb+(hi-lo))//(2*(hi-lo))
    zero_in=lo<=0<=hi; B=pos(0) if signed and zero_in else 0
    def R(a0,a1,l0,l1):
        l0,l1=max(l0,0),min(l1,Lb-1)
        return (cx+a0,cy+Lb-1-l1,cx+a1,cy+Lb-1-l0) if vertical else (cx+l0,cy+a0,cx+l1,cy+a1)
    def ring(r):
        x0,y0,x1,y1=r
        return [(x0,y0,x1,y0),(x0,y1,x1,y1),(x0,y0,x0,y1),(x1,y0,x1,y1)]
    def put(rects,test,op):
        cells=set()
        for x0,y0,x1,y1 in rects:
            x0,y0,x1,y1=max(x0,cx),max(y0,cy),min(x1,cx+cw-1),min(y1,cy+ch-1)
            if x1<x0 or y1<y0:continue
            if test is None:draw_rect(img,x0,y0,x1,y1,op)
            else:cells|={(x,y) for y in range(y0,y1+1) for x in range(x0,x1+1) if test(x,y)}
        fill_cells(img,cells,op)
    def shown(e):   # along pixel that shows a value e pixels from the baseline
        return min(max(B+e-1 if e>0 else B+e,0),Lb-1)
    def units(e):   # LED segments of one slider as (start, end, lit); a segment is lit only if fully covered
        up=[(B+j*(seg+gap),B+j*(seg+gap)+seg-1) for j in range(Lb)]
        down=[(B-1-j*(seg+gap)-seg+1,B-1-j*(seg+gap)) for j in range(Lb)] if signed and B else []
        lit=lambda s,t:e>0 and s>=B and t<=B+e-1 or e<0 and t<B and s>=B+e
        return [(s,t,lit(s,t)) for s,t in up+down if s>=0 and t<=Lb-1]
    slots=[]
    for i,v in enumerate(vals):
        a0=off+i*(bw+sp)
        if a0>A-1:break
        e=pos(v)-B; e=(1 if e>0 else -1)*((abs(e)*level+50)//100)
        slots.append((i,a0,a0+bw-1,e,shown(e)))
    if ghost!='none':   # empty (unlit) part of every slot
        for i,a0,a1,e,m in slots:
            spans=[(s,t) for s,t,on in units(e) if not on] if seg else [(0,Lb-1)] if e==0 else [(0,B-1),(B+e,Lb-1)] if e>0 else [(0,B+e-1),(B,Lb-1)]
            put([R(a0,a1,s,t) for s,t in spans if t>=s],ghost_test,ink)
    pts=[]
    for i,a0,a1,e,m in slots:
        t=cane(i)
        if style in ('bar','hollow'):
            spans=[(s,u) for s,u,on in units(e) if on] if seg else [(B,B+e-1)] if e>0 else [(B+e,B-1)] if e<0 else []
            rects=[R(a0,a1,s,u) for s,u in spans]
            if style=='bar':
                if ghost!='none' and t:put(rects,None,1-ink)   # clear the ghost under a patterned bar
                put(rects,t,ink)
            else:put([q for r in rects for q in ring(r)],t,ink)
        elif style=='thin':put([R(a0,a1,m-th+1,m) if e>=0 else R(a0,a1,m,m+th-1)],t,ink)
        elif style=='point':
            p0=a0+max(0,(bw-th)//2); p1=min(a1,p0+th-1); put([R(p0,p1,m-th+1,m) if e>=0 else R(p0,p1,m,m+th-1)],t,ink)
        else:pts.append((i,a0+(bw-1)//2,m))
        if c.get('cane_frame','none')=='bar' and e:put(ring(R(a0,a1,*((B,B+e-1) if e>0 else (B+e,B-1)))),None,ink)
        elif c.get('cane_frame','none')=='slot':put(ring(R(a0,a1,0,Lb-1)),None,ink)
    for (i,ac,m),nxt in zip(pts,pts[1:]+[None]):   # line style: Bresenham between slider centres, square pen
        seq=iso_line((ac,m),(nxt[1],nxt[2])) if nxt else [(ac,m)]
        cells=[(cx+u,cy+Lb-1-w_) if vertical else (cx+w_,cy+u) for u,w_ in seq]
        put([(px-(th-1)//2,py-(th-1)//2,px-(th-1)//2+th-1,py-(th-1)//2+th-1) for px,py in cells],cane(i),ink)
    if c.get('zero_line','none')!='none' and zero_in:
        z=min(B,Lb-1); r=R(0,A-1,z,z)
        put([r] if c['zero_line']=='solid' else [(x,y,x,y) for y in range(r[1],r[3]+1) for x in range(r[0],r[2]+1) if (x+y)%2==0],None,ink)
    peaks=ms_parse(c.get('peaks',''))
    if c.get('peak_style','none')!='none':
        for i,a0,a1,e,m in slots:
            if i>=len(peaks):break
            pm=shown(pos(min(hi,max(lo,peaks[i])))-B); mid=a0+(bw-1)//2
            put([R(a0,a1,pm,pm)] if c['peak_style']=='line' else [R(mid,mid,pm,pm)],None,ink)
    for i,a0,a1,e,m in slots:
        if i!=selected:continue
        slot=R(a0,a1,0,Lb-1)
        if sel_style=='invert':put([slot],None,2)
        elif sel_style=='frame':put(ring(slot),None,ink)
        elif marker:put([(cx+a0,cy+L-1,cx+a1,cy+L-1) if vertical else (cx+L-1,cy+a0,cx+L-1,cy+a1)],None,ink)
    finish()


SHAPES=dict(multislider=draw_multislider,line=draw_line,layout=draw_layout,list=draw_list,shape=draw_2d,grid=draw_grid,iso=draw_iso,group=lambda img,c,ink:None,image=draw_image,rect=draw_shape,scrollbar=draw_scrollbar,waveform=draw_waveform,placeholder=draw_placeholder)


def _render(doc,page_index=0,editor=False):
    validate(doc)
    if not 0 <= page_index < len(doc['pages']):
        raise ValueError('Unknown screen')
    page=doc['pages'][page_index]; lookup={c['id']:c for c in page['components']}
    def skipped(c):
        # Editor: eye toggle. Device (PNG export, code): "show on device" toggle. Both inherit from parents.
        while c:
            if c.get('state_off') or (c.get('hidden') if editor else c.get('device',True) is False):return True
            c=lookup.get(c.get('parent'))
        return False
    img=P.blank(); background=page_background(page)
    if background=='reference':
        # Reference only: shown in the editor, never exported nor compiled (no draw command).
        bits=reference_bits(page.get('reference','')) if editor and page.get('reference') else None
        if bits:
            for i,v in enumerate(bits):img[i//128][i%128]=int(v)
    elif not editor and page.get('background_device',True) is False:pass
    elif background=='pattern':
        base=page.get('bg_base','black'); draw_rect(img,0,0,127,63,int(base=='black'))
        draw_pattern(img,dict(pattern=page.get('bg_pattern','checker'),pattern_color='white' if base=='black' else 'black'),0,0,127,63)
    else:draw_rect(img,0,0,127,63,int(background=='black'))
    measurements=[]
    def draw(img,components,measurements):
        for c in components:
            x,y,w,h=(c[k] for k in ('x','y','width','height'))
            style=doc['styles'][c['style']]
            hp=style['highlight_padding']
            ink=int(c.get('color','black')=='black')
            font_key=c.get('font','default');font=FB.FONTS[font_key];font_height=FB.metrics(font_key,True)['height']
            bounds={k:c[k] for k in ('x','y','width','height')}
            info=dict(id=c['id'],type=c['type'],bounds=bounds,content=c.get('_content') or content_bounds(c,style),font=font_key,font_height=font_height,focusable=c.get('selectable',False))
            if c.get('note'):info['note']=c['note']
            if c.get('name'):info['name']=c['name']
            if c.get('master'):info['component']='master'
            if c.get('instance_of'):info['instance_of']=c['instance_of']
            if c.get('master_key'):info['master_key']=c['master_key']
            if c.get('master') and (c.get('state') or c.get('state_of')):info['state']=c.get('state') or 'default';info['state_of']=c.get('state_of') or c['id']
            if c['type']=='layout':info['slots']=c.get('_slots') or {}
            if c['type']=='layout':info['cells']=c.get('_cells') or [[v[k] for k in ('x','y','width','height')] for v in [c.get('_content') or content_bounds(c,style)]]
            if c.get('device',True) is False:info['device']=False
            if skipped(c):
                measurements.append(dict(info,visible=0,skipped=True)); continue
            if c['type']=='drawing':
                for i,(xx,yy) in enumerate(c.get('points',[])):
                    px,py=x+xx,y+yy; area=c['_parent_bounds']
                    if c.get('pattern','solid')=='dotted' and i%2:continue
                    if 0<=px<128 and 0<=py<64 and area['x']<=px<area['x']+area['width'] and area['y']<=py<area['y']+area['height']:
                        draw_rect(img,px,py,px,py,ink)
                measurements.append(dict(info,visible=0)); continue
            if (c.get('shadows') or c.get('effect_stroke','none')!='none') and c['type'] in ('rect','text','image','iso','shape','grid','layout','list','line','multislider'):
                draw_shadows(img,c,lambda target,c=c:draw(target,[dict(c,shadows=[],effect_stroke='none')],[]))
            if c['type'] in SHAPES:
                SHAPES[c['type']](img,c,ink)
                extra=dict(reserved=True,name=c.get('name','')) if c['type']=='placeholder' else {}
                measurements.append(dict(info,visible=0,**extra)); continue
            if c['type']=='text':
                font=spaced(font_key,c);pt,pr,pb,pl=sides(c,'text_padding');room=max(0,w-pl-pr)
                text=P.fit(font,clean_text(cased(c,c.get('text','TEXT')),font_key,False),room);tw=P.text_width(font,text)
                mode=c.get('text_align','start');tx=x+pl+(room-tw)//2 if mode=='center' else x+w-pr-tw if mode=='end' else x+pl
                if c.get('fill','transparent')=='filled':
                    draw_rect(img,x,y,x+w-1,y+h-1,int(c.get('background','white')=='black'));draw_pattern(img,c,x,y,x+w-1,y+h-1)
                o=frame_out(c)
                if c.get('stroke','none')!='none':outline(img,x-o,y-o,x+w-1+o,y+h-1+o,int(c['stroke']=='black'),c.get('stroke_width',1),c.get('stroke_style','solid')=='dotted',c.get('stroke_sides'))
                mtop=FB.metrics(font_key)['top'];ty=y+pt-(c.get('_ink_top',mtop)-mtop)
                if c.get('underline') and tw:
                    row=ty-mtop+2;inkw,_,_=text_ink(font_key,text,font)
                    if y<=row<y+h:draw_rect(img,max(x,tx),row,min(x+w-1,tx+inkw-1),row,ink)
                draw_text(img,tx,ty,text,room,ink,font_key=font_key,uppercase=False,clip=bounds,font=font)
                if c.get('selectable',False) and c.get('focus_state','normal')=='selected' and tw:
                    draw_rect(img,max(x,tx-hp),max(y,y+pt-hp),min(x+w-1,tx+tw-1+hp),min(y+h-1,y+pt+FB.metrics(font_key)['height']-1+hp),2)
                measurements.append(dict(info,visible=1))
                continue
            raise ValueError('Unknown layer type')
    def subtree(cid):
        ids={cid};grew=True
        while grew:
            grew=False
            for v in page['components']:
                if v.get('parent') in ids and v['id'] not in ids:ids.add(v['id']);grew=True
        return ids
    def paint(img,components,measurements,invert=True):
        # "Invert colours": XOR the layer's area once the layer and all its children are drawn.
        pending=[]
        def close(until=None):
            while pending and (until is None or until['id'] not in pending[-1][1]):
                b,_=pending.pop();draw_rect(img,b['x'],b['y'],b['x']+b['width']-1,b['y']+b['height']-1,2)
        for c in components:
            if invert:close(c)
            draw(img,[c],measurements)
            if invert and c.get('inverted') and not skipped(c):
                pending.append(({k:c[k] for k in ('x','y','width','height')},subtree(c['id'])))
        if invert:close()
    resolved=resolve_components(doc,page)
    paint(img,resolved,measurements)
    if editor:
        # Net effect of each layer on any pixel: 1/0 = set/clear, x = invert, . = untouched.
        # The editor composites these masks itself, so a drag moves layers without a server trip.
        for c,m in zip(resolved,measurements):
            if m.get('skipped'):continue
            low,high=[[0]*128 for _ in range(64)],[[1]*128 for _ in range(64)]
            paint(low,[c],[],False);paint(high,[c],[],False)
            cells={(x,y):('.' if (low[y][x],high[y][x])==(0,1) else 'x' if (low[y][x],high[y][x])==(1,0) else str(low[y][x]))
                   for y in range(64) for x in range(128) if (low[y][x],high[y][x])!=(0,1)}
            if not cells:continue
            xs=[x for x,_ in cells];ys=[y for _,y in cells];x0,y0=min(xs),min(ys);w,h=max(xs)-x0+1,max(ys)-y0+1
            m['mask']=dict(x=x0,y=y0,width=w,height=h,bits=''.join(cells.get((x0+i%w,y0+i//w),'.') for i in range(w*h)))
    return image_from_pixels(img),measurements


def render(doc,page_index=0,commands=None,editor=False):
    token=COMMANDS.set(commands)
    try:return _render(doc,page_index,editor)
    finally:COMMANDS.reset(token)


def state_families(page):
    """Component states on one screen: family id -> its masters in layer order (only families with 2+ states)."""
    out={}
    for c in page['components']:
        if c.get('master') and (c.get('state') or c.get('state_of')):out.setdefault(c.get('state_of') or c['id'],[]).append(c)
    return {k:v for k,v in out.items() if len(v)>1}


def state_png(i,family,c):
    return f"page_{i+1:02d}__{screen_slug(family[0].get('name') or family[0]['id'])}__{screen_slug(c.get('state') or 'default')}.png"


def export(doc):
    validate(doc)
    folder=STORE/'export'; folder.mkdir(parents=True,exist_ok=True)
    (folder/'project.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    for i,page in enumerate(doc['pages']):
        image,_=render(doc,i)
        image.save(folder/f'page_{i+1:02d}.png')
        image.resize((768,384),Image.Resampling.NEAREST).save(folder/f'page_{i+1:02d}_x6.png')
        # One screen per component state, the other states of that component hidden: what the agent must reproduce.
        for family in state_families(page).values():
            for c in family:
                d=deepcopy(doc)
                for v in d['pages'][i]['components']:
                    if any(v['id']==m['id'] for m in family):v['state_off']=v['id']!=c['id']
                image,_=render(d,i); name=state_png(i,family,c)
                image.save(folder/name); image.resize((768,384),Image.Resampling.NEAREST).save(folder/name.replace('.png','_x6.png'))
    from ui_codegen import export as export_code
    export_code(doc,folder)
    (folder/'NOTES.md').write_text(notes(doc))
    return str(folder)


def notes(doc):
    """Designer notes for the agent wiring the screens: one section per screen, layers with bounds."""
    out=[f"# {doc.get('name','UI')} — designer notes",'','Generated by OctaDraw export. Coordinates: x, y, width × height on the 128×64 screen.','']
    for i,page in enumerate(doc['pages']):
        _,measured=render(doc,i)
        out+=[f"## Screen {i+1}: {page.get('name') or page['id']} (`ui_page_{i+1}`)",'']
        if page.get('note'):out+=[page['note'],'']
        if page.get('background_device',True) is False:out+=['Background: editor only (not drawn on the device).','']
        byid={c['id']:c for c in page['components']}
        for m in measured:
            c=byid[m['id']];b=m['bounds'];flags=[]
            if c.get('device',True) is False:flags.append('editor only')
            if c['type']=='placeholder':flags.append('reserved zone, drawn by the host')
            if c['type']=='text' and str(c.get('name','')).startswith('$'):flags.append('runtime text, drawn by the host with ui_draw_text')
            if c.get('parent'):flags.append('in '+c['parent'])
            if c['type']=='layout':flags.append(f"auto layout, {c.get('layout_cols',3)} columns"+(f" x {c['layout_rows']} rows" if c.get('layout_rows') else '')+(', filled column by column' if c.get('layout_flow')=='columns' else ''))
            if c.get('master'):flags.append('component master')
            if c.get('instance_of'):flags.append(f"instance of `{c['instance_of']}`")
            if c.get('master') and (c.get('state') or c.get('state_of')):flags.append(f"state “{c.get('state') or 'default'}”"+(', not shown on this screen' if c.get('state_off') else ''))
            content=c.get('text') or c.get('items') or ''
            label=' '.join(v for v in (f"**{c['name']}**" if c.get('name') else '',f"“{content}”" if content and content!=c.get('name') else '') if v)
            out.append(f"- {c['type']} `{c['id']}` {label} — {b['x']}, {b['y']} · {b['width']} × {b['height']}".replace('  ',' ')+(f" ({', '.join(flags)})" if flags else ''))
            if c.get('note'):out+=['  '+line for line in c['note'].splitlines()]
        families=state_families(page)
        if families:
            bounds={m['id']:m['bounds'] for m in measured}
            out+=['','### States','','Each state is a separate drawing of the same component; the device shows one at a time. Screen with that state: the PNG named.','']
            for family in families.values():
                out.append(f"- **{family[0].get('name') or family[0]['type']}** (`{family[0].get('state_of') or family[0]['id']}`)")
                for c in family:
                    b=bounds[c['id']]
                    out.append(f"  - “{c.get('state') or 'default'}” `{c['id']}` — {b['x']}, {b['y']} · {b['width']} × {b['height']} — `{state_png(i,family,c)}`"+('' if c.get('state_off') else ' (shown in the screen PNG)'))
                    if c.get('note'):out+=['    '+line for line in c['note'].splitlines()]
        out.append('')
    return '\n'.join(out)


SCREENS=STORE/'screens'


def screen_slug(name):
    slug=''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in name.strip())[:40].strip('_')
    return slug or 'screen'


def save_screen(doc,page_index):
    """One screen as a self-contained file (with its styles), without saving the project."""
    validate(doc); page=doc['pages'][page_index]
    used={c['style'] for c in page['components']}|{'default'}
    data=dict(kind='octadraw-screen',version=1,page=page,styles={k:v for k,v in doc['styles'].items() if k in used})
    SCREENS.mkdir(parents=True,exist_ok=True); path=SCREENS/(screen_slug(page.get('name') or page['id'])+'.json')
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n'); return str(path)


def list_screens():
    return sorted(p.stem for p in SCREENS.glob('*.json')) if SCREENS.exists() else []


def load_screen(name):
    path=SCREENS/(screen_slug(name)+'.json')
    data=json.loads(path.read_text())
    if data.get('kind')!='octadraw-screen':raise ValueError('Not an OctaDraw screen file')
    probe=dict(version=1,name='probe',styles=data['styles'],pages=[data['page']]);validate(probe)
    return data


WIDGETS=STORE/'widgets'


def widget_probe(data):
    """A widget as a one-screen document: components at their relative position from 0,0."""
    background=data.get('background','white')
    if background not in BACKGROUNDS:raise ValueError('Invalid widget background')
    probe=dict(version=1,name='widget',styles=data['styles'],
               pages=[dict(id='widget',name=str(data.get('name',''))[:40],background=background,components=data['components'])])
    return validate(probe)


def save_widget(data):
    """Reusable set of layers (children, relative positions, styles), shared by every project."""
    name=str(data.get('name','')).strip()[:40]
    if not name:raise ValueError('Widget name required')
    if not isinstance(data.get('components'),list) or not 1<=len(data['components'])<=128:raise ValueError('Select at least one layer')
    probe=widget_probe(data); _,measured=render(probe)
    width=max(m['bounds']['x']+m['bounds']['width'] for m in measured); height=max(m['bounds']['y']+m['bounds']['height'] for m in measured)
    out=dict(kind='octadraw-widget',version=1,name=name,background=probe['pages'][0]['background'],width=width,height=height,
             components=data['components'],styles=probe['styles'])
    WIDGETS.mkdir(parents=True,exist_ok=True); path=WIDGETS/(screen_slug(name)+'.json')
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n'); return str(path)


def load_widget(name):
    data=json.loads((WIDGETS/(screen_slug(name)+'.json')).read_text())
    if data.get('kind')!='octadraw-widget':raise ValueError('Not an OctaDraw widget file')
    widget_probe(data); return data


def list_widgets():
    """Name, size and a PNG thumbnail (its own background) of each saved widget."""
    out=[]
    for path in sorted(WIDGETS.glob('*.json')) if WIDGETS.exists() else []:
        try:
            data=load_widget(path.stem); image,_=render(widget_probe(data))
            buffer=io.BytesIO(); image.crop((0,0,data['width'],data['height'])).save(buffer,format='PNG')
            out.append(dict(file=path.stem,name=data['name'],width=data['width'],height=data['height'],png=base64.b64encode(buffer.getvalue()).decode()))
        except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError):continue
    return out


def delete_widget(name):
    path=WIDGETS/(screen_slug(name)+'.json')
    if path.exists():path.unlink()
    return True
