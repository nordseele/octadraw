# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""Original pixel wordmark for the editor chrome; no firmware fonts/assets."""
from html import escape
import json
from pathlib import Path

# Original 5x7 lettering, independent of any device font.
SCALE=4
LETTERS={
 'a':['00000','00000','01110','00001','01111','10001','01111'],
 'c':['00000','00000','01111','10000','10000','10000','01111'],
 'd':['00001','00001','01111','10001','10001','10001','01111'],
 'e':['00000','00000','01110','10001','11111','10000','01111'],
 'i':['00100','00000','01100','00100','00100','00100','01110'],
 'l':['01100','00100','00100','00100','00100','00100','01110'],
 'n':['00000','00000','11110','10001','10001','10001','10001'],
 'o':['00000','00000','01110','10001','10001','10001','01110'],
 'p':['00000','00000','11110','10001','11110','10000','10000'],
 'r':['00000','00000','10111','11000','10000','10000','10000'],
 's':['00000','00000','01111','10000','01110','00001','11110'],
 't':['00100','00100','11111','00100','00100','00100','00011'],
 'u':['00000','00000','10001','10001','10001','10001','01111'],
 'v':['00000','00000','10001','10001','10001','01010','00100'],
 'w':['00000','00000','10001','10001','10101','10101','01010'],
 'y':['00000','00000','10001','10001','01111','00001','01110'],
 'b':['10000','10000','11110','10001','10001','10001','11110'],
 ' ':['00000']*7,
}


def load():
    data=json.loads(Path(__file__).with_name('ui_brand.json').read_text());name=data['name'];version=str(data.get('version',''))
    if not isinstance(name,str) or not 1<=len(name)<=32:raise ValueError('Nom invalide')
    chars=name.lower();rects=[]
    for i,char in enumerate(chars):
        if char not in LETTERS:
            return dict(name=name,svg=f'<span>{escape(name)}</span>')
        for y,row in enumerate(LETTERS[char]):
            x=0
            while x<5:
                if row[x]=='1':
                    run=len(row[x:])-len(row[x:].lstrip('1'))
                    rects.append(f'<rect x="{i*6+x}" y="{y}" width="{run}" height="1"/>');x+=run
                else:x+=1
    # Whole-pixel size (4 px per dot): identical in every browser, no font involved.
    w=len(chars)*6-1
    svg=(f'<svg class="brand-mark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} 7" width="{w*SCALE}" height="{7*SCALE}" '
         f'aria-hidden="true" shape-rendering="crispEdges" fill="currentColor">'+''.join(rects)+'</svg>')
    return dict(name=name,svg=svg,version=version)


def page(html):
    """Editor page with the logo and version inlined (no flash of text before /brand answers)."""
    b=load()
    return html.replace('<!--LOGO-->',b['svg']).replace('<!--VERSION-->',escape(b['version']))


if __name__=='__main__':
    # python3 tools/ui_brand.py -> tools/octadraw_logo.svg (standalone logo, black)
    Path(__file__).with_name('octadraw_logo.svg').write_text(load()['svg'].replace(' class="brand-mark"','').replace(' aria-hidden="true"','').replace('currentColor','#000')+'\n')
