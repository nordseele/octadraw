# OctaDraw

Pixel editor for the Octatrack's 128 × 64 one-bit screen. You draw screens in the browser,
and OctaDraw exports ColdFire assembly that draws the same pixels on the unit, plus PNG previews
and a JSON description that you (or a coding agent) wire into your own firmware module.

What you see in the editor is exactly what the generated code draws: the preview, the PNGs and the
assembly all come from the same draw commands.

----
<img width="1382" height="748" alt="otdraw" src="https://github.com/user-attachments/assets/e0900278-3ce1-4ef0-a231-e287a7ee7908" />

----

### Demo video
[![Demo video](https://img.youtube.com/vi/yNRahR6SXeg/hqdefault.jpg)](https://www.youtube.com/watch?v=yNRahR6SXeg)

## Run it

You need Python 3.9 or later and Pillow.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python octadraw.py            # then open http://127.0.0.1:8077/
```

On macOS you can double-click `OctaDraw.command` instead. Use `--port` (or `PORT=…` for the
launcher) to pick another port.

Your work lives in the **work folder**: `./work/` by default, or the folder named by `OCTADRAW_HOME`.

| In the work folder | What it holds |
|---|---|
| `project.json` | the project (**Save**) |
| `export/` | the latest **Export** (see below) |
| `screens/`, `widgets/` | screens and widgets saved for reuse across projects |
| `fonts/` | your imported fonts (`OCTADRAW_FONTS` overrides this one) |
| `references/` | 128 × 64 PNGs you can show behind a screen while you draw |

## Using the editor

- **Screens**: a project holds up to 48 screens. Each one has a background (white, black, a pattern,
  or a reference image) and a note for whoever wires it.
- **Layers**: text, rectangles, shapes, lines, free pixels, tables, auto layouts, lists, multisliders,
  scrollbars, waveforms, isometric solids, PNG images, and reserved zones (areas the host draws itself,
  such as an animation). Drag to move or resize. Arrow keys move by 1 px, Shift + arrows by 10 px.
  The `?` button in Properties shows the shortcuts.
- **Lists**: comma-separated items, optionally with a checkbox on every row (height, square or round,
  inner padding, gap after the checkbox, and a checked state per row). A list can stay a column, a row, or
  reflow into a grid of columns and rows, fixed or automatic; columns hug their content or share the width
  equally, with a maximum column width. A new list keeps its width and grows in height as you add items;
  past 64 px it clips at the screen edge, so use the grid for long lists.
- **Containers**: rectangles, groups, tables and auto layouts hold children. Children can dock to a side,
  or follow constraints when their parent is resized.
- **Components**: mark a layer as a master and place instances of it. Edits to the master reach every
  instance, and a master can have named **states** (for example normal / selected).
- **Visibility states**: named snapshots of which layers are shown on a screen.
- **Editor-only**: untick "on device" to keep a layer or background out of the PNGs and the code.
- **Reference image**: put 128 × 64 PNGs in `references/` in your work folder, reload the page, then pick
  one as the screen background. It is a tracing guide behind your layers: the editor shows it, the exported
  PNGs and the generated code never do.
- **Preview**: LCD (lit pixel = dark) or OLED (lit pixel = bright). This changes the display only,
  never the project or the export.

### Fonts

The fonts in `fonts/` are free X11 misc-fixed fonts (public domain; see `fonts/README.md`).
**Import font…** adds a BDF font, or a TTF/OTF rendered at the pixel size you choose. Imported fonts are
stored in your work folder and never copied into this repository. Check an imported font's licence before
you share an export that uses it: the export notes list the fonts each export embeds.

To draw with the Octatrack's own eight fonts, extract them from **your own copy** of the OS update
(the `.syx` from the official download, or an OS image you unpacked from it):

```sh
python3 tools/extract_fonts.py OCTATRACK_OS1.40C.syx      # writes os-font-1.bdf … os-font-8.bdf
```

They go to your font folder (or the folder given as a second argument). The script holds no firmware data
and this repository ships none: the fonts are made on your machine from your file, for your own use. Do not
redistribute them, and do not share exports that embed them.

## What Export writes

| File | Content |
|---|---|
| `ui_generated.S` | one entry point `ui_page_N` per screen, the glyphs it uses, and the renderer (`ui_draw.S`) |
| `ui_commands.json` | per screen: layer bounds, names, notes, reserved zones, and the draw commands |
| `NOTES.md` | designer notes per screen and layer, and a PNG name for each component state |
| `page_NN.png`, `page_NN_x6.png` | 1:1 and 6× previews of each screen (black = lit pixel) |
| `CODE_README.txt` | a short reminder of the calling convention |

### Calling the generated code

- Assemble with `m68k-elf-as -mcpu=5407` and link it into your module.
- Call `ui_page_N` with **a3** pointing to the 128 × 64 drawing surface. `d2–d7` and `a2–a6` are
  preserved; `d0`, `d1`, `a0` and `a1` are scratch.
- The surface is five longs: `width, height, stride, bits, mask`. The bits are stored **by column**: column
  `x` starts at long `x * stride`, and inside a column, bit 31 of the first long is the bottom row.
  Every pixel drawn also sets its bit in `mask`.
- Your code owns the surface, decides when to redraw, and handles input.
- Glyphs wider than 8 px are cut into 8-px columns, because the renderer draws 8-px-wide glyphs.

### Live text: names, values, selection

Name a text layer with a leading `$` (for example `$title` or `$value1`) to make it a **slot**. The editor
and the PNGs show its sample text. `ui_page_N` leaves it out, and the export adds a `ui_slot_N_name`
record and the font table it needs. To draw a screen:

1. call `ui_page_N`;
2. for each slot, call `ui_draw_text` with **a3** = the surface, **a0** = a NUL-terminated ASCII string,
   **a1** = `ui_slot_N_name` and **d0** = flags. Bit 1 fills the slot box with its background first, and
   bit 0 draws the selection highlight. It returns the ink width in `d0`.

The result is what the editor would draw with that string: the layer's font, case, alignment and padding,
cut to fit its box. Keep a slot's box independent of its text (no Hug, underline, stroke, pattern, invert
or shadow), use a font whose glyphs are at most 8 px wide, and draw slots last. `ui_draw_rect`
(`d0` x0, `d1` row0, `d2` x1, `d3` row1, `d4` 0 clear / 1 set / 2 invert) is also exported.

`examples/demo/` shows a complete host: a list whose title, names, values and cursor come from a
state block. `demo.S` is the host code, and `project.json` the screen; open the screen with **Open…**.

## Proof

`tests/bench_m68k.py` assembles the examples with `m68k-elf-as -mcpu=5407` and runs them in the
Unicorn emulator on a surface in RAM. No firmware is involved. It checks that every screen, every demo
state and a set of slot edge cases are pixel-identical to the editor's render, and that every call
preserves its registers and the stack.

```sh
.venv/bin/pip install unicorn
.venv/bin/python tests/bench_m68k.py
```

## More

- `AGENTS.md`: how a coding agent wires an export into a ColdFire module, and the rules for changing OctaDraw.
- `CHANGELOG.md`: release notes.
- `docs/FORMAT.md`: the project JSON.

## Licence

- The editor and its tools: GPL-3.0-or-later (`LICENSE`).
- `ui_draw.S`, the code OctaDraw generates (which embeds `ui_draw.S`) and `examples/demo/demo.S`: MIT
  (`LICENSE-MIT`, also written into every export), so you can use exported
  screens in any firmware module without the GPL applying to it.
- The bundled fonts keep their own licences (`fonts/README.md`).

Octatrack is a trademark of its owner. This project is not affiliated with it and ships no part of any
firmware.
