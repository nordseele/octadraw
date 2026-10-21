#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""OctaDraw: 128 x 64 one-bit screen editor with ColdFire code export.

python3 octadraw.py              # http://127.0.0.1:8077
python3 octadraw.py --port 8078
Work folder (projects, exports, widgets, fonts, references): OCTADRAW_HOME, default ./work.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
from pathlib import Path

import ui_brand as brand
import ui_components as C
import ui_fontbook as fonts

HERE = Path(__file__).resolve().parent


def code_stamp():
    # Newest Python source of the server: a later one means this process runs stale code.
    return max(path.stat().st_mtime for path in HERE.glob('*.py'))


STARTED = code_stamp()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8077)
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, body, content='application/json', status=200):
            if content == 'application/json':
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content+'; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/':
                self.reply(brand.page((HERE / 'ui_editor.html').read_text()).encode(), 'text/html')
            elif self.path == '/project':
                self.reply(C.load())
            elif self.path == '/brand':
                self.reply(brand.load())
            elif self.path == '/server-info':
                self.reply({'stale': code_stamp() > STARTED, 'work': str(C.STORE)})
            elif self.path == '/fonts':
                self.reply(fonts.catalog())
            elif self.path == '/references':
                self.reply(C.reference_catalog())
            elif self.path.startswith('/reference-bits/'):
                try:
                    self.reply({'bits': C.reference_bits(self.path[len('/reference-bits/'):])})
                except (ValueError, OSError) as error:
                    self.reply({'error': str(error)}, status=400)
            elif self.path == '/editor/widgets':
                self.reply(C.list_widgets())
            elif self.path == '/editor/screens':
                self.reply(C.list_screens())
            elif self.path == '/glyphs':
                self.reply(fonts.glyph_catalog())
            elif self.path in ('/ui_theme.css', '/ui_theme.js'):
                path = HERE / self.path[1:]
                self.reply(path.read_bytes(), 'text/css' if path.suffix == '.css' else 'application/javascript')
            else:
                self.reply({'error': 'Unknown page'}, status=404)

        def do_POST(self):
            try:
                origin = self.headers.get('Origin')
                if origin and origin != f'http://127.0.0.1:{args.port}':
                    raise ValueError('Origin not allowed')
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected JSON')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= (8 if self.path == '/editor/font-import' else 1) * 1048576:
                    raise ValueError('Request too large')
                body = json.loads(self.rfile.read(length))
                if self.path == '/editor/preview':
                    page = int(body.get('page', 0))
                    picture, measurements = C.render(body['document'], page, editor=True)
                    buffer = io.BytesIO(); picture.save(buffer, format='PNG')
                    self.reply(dict(png=base64.b64encode(buffer.getvalue()).decode(), measurements=measurements,
                                    screen=C.screen_content(body['document'], body['document']['pages'][page])))
                elif self.path == '/editor/save':
                    self.reply({'path': C.save(body['document'])})
                elif self.path == '/editor/export':
                    self.reply({'path': C.export(body['document'])})
                elif self.path == '/editor/image':
                    self.reply(C.import_image(body['png']))
                elif self.path == '/editor/screen-save':
                    self.reply({'path': C.save_screen(body['document'], int(body['page']))})
                elif self.path == '/editor/screen-load':
                    self.reply(C.load_screen(str(body['name'])))
                elif self.path == '/editor/widget-save':
                    self.reply({'path': C.save_widget(body)})
                elif self.path == '/editor/widget-load':
                    self.reply(C.load_widget(str(body['name'])))
                elif self.path == '/editor/widget-delete':
                    self.reply({'deleted': C.delete_widget(str(body['name']))})
                elif self.path == '/editor/font-import':
                    size = body.get('size')
                    self.reply({'id': fonts.import_font(str(body['name']), base64.b64decode(body['data']), int(size) if size else None)})
                else:
                    self.reply({'error': 'Unknown action'}, status=404)
            except (ValueError, KeyError, TypeError, OSError) as error:
                self.reply({'error': str(error)}, status=400)

    server = HTTPServer(('127.0.0.1', args.port), Handler)
    print(f'OctaDraw: http://127.0.0.1:{args.port}  (work folder: {C.STORE})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
