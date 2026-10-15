# AGENTS.md

Instructions for coding agents. Two jobs: wiring an OctaDraw export into a ColdFire module, and changing
OctaDraw itself. Read `README.md` first; `docs/FORMAT.md` describes the project JSON.

## Wiring an export into your code

An export folder holds:
- `ui_generated.S`: the code;
- `ui_commands.json`: geometry, slots and draw commands;
- `NOTES.md`: the designer's notes;
- `page_NN.png`: the expected pixels;
- `LICENSE-MIT.txt`.

**Do not edit `ui_generated.S` by hand**: change the project and export again.

1. **Read the intent first.** Read `NOTES.md` and every `note` in `ui_commands.json`: the designer writes there
   what each screen and layer is for, which states exist and what the host must do.
2. **Build.**
   - Assemble with `m68k-elf-as -mcpu=5407` and link the object into your module.
   - Entry points are globals: `ui_page_N` (one per screen), `ui_draw_text`, `ui_draw_rect`, `ui_slot_N_<name>`
     and `ui_font_<key>`.
   - The code uses absolute addresses (`jsr …:l`, `.long` pointers): let your linker relocate it.
3. **Provide the surface.**
   - `a3` points to five longs: `width (128), height (64), stride, bits, mask`.
   - Bits are stored by column: column `x` starts at long `x * stride` (stride = 2 for 64 rows).
   - Inside a column, bit 31 of the first long is the **bottom** row, so row `r` (0 = top) is bit `31 - ((63 - r) & 31)`
     of long `x * stride + ((63 - r) >> 5)`.
   - Each drawn pixel also sets its bit in `mask`.
   - Allocating, showing and freeing the surface is your module's job.
4. **Draw a screen.**
   - Call `ui_page_N`, then `ui_draw_text` once per slot listed in `ui_commands.json → slots`, in that order.
   - Each slot call takes `a0` = NUL-terminated ASCII (32..126), `a1` = `ui_slot_N_<name>` and `d0` flags: bit 1
     fills the slot box with its background first (always set it when you redraw over an old value), bit 0
     draws the selection highlight.
   - A slot with `bg` = 255 is transparent: redraw the whole screen before drawing it again.
5. **Registers.**
   - Every entry preserves `d2–d7` and `a2–a6`; `d0`, `d1`, `a0` and `a1` are scratch.
   - None of them allocates memory, touches anything outside the surface, or depends on a firmware address.
6. **Follow your firmware's redraw rules.** OctaDraw draws pixels only. When to redraw, how to show the surface
   and which keys move the selection belong to your code. Reserved zones (`reserved: true` in
   `ui_commands.json`) are left untouched for you to draw.
7. **Check pixels before hardware.**
   - Run the code in an emulator against `page_NN.png`: black = lit pixel.
   - `tests/bench_m68k.py` shows how to do this with Unicorn: build, call with a surface in RAM, decode the bits,
     compare.
   - On an LCD a lit pixel looks dark. Compare the polarity on the device once, with a screen that has an obvious
     shape.

**ColdFire traps that bite hand-written host code:**
- no `movem` with `-(sp)` / `(sp)+` (use `lea -n(sp),sp; movem.l …,(sp)`);
- immediate shifts are 1..8;
- `moveq` is −128..127;
- no `mulu.l #imm`.

`examples/demo/demo.S` is a complete, small host: copy its shape.

## Changing OctaDraw

| File | Role |
|---|---|
| `ui_components.py` | document model, validation (`validate()` is the format's authority), the renderer |
| `ui_codegen.py` | draw commands → `ui_generated.S`, slots and runtime font tables |
| `ui_draw.S` | the ColdFire command interpreter and the runtime text entries (MIT) |
| `ui_pixels.py` | canvas helpers: text width, fit, rectangles, small glyphs |
| `ui_fontbook.py` | font loading (bundled BDF, user BDF/TTF/OTF) |
| `octadraw.py` | local HTTP server, editor only |
| `ui_editor.html` | the editor (single file, no build step) |
| `tests/bench_m68k.py` | ColdFire proof: generated code vs Python render, pixel for pixel |
| `tools/extract_fonts.py` | the OS fonts as BDF, read from the user's own OS file (never commit its output) |

**Rules:**
- **One source of truth.** The preview, the PNGs and the code come from the same draw commands. A new layer type or
  option must render through `C.render` and compile through `ui_codegen`, never through a separate path.
- **Keep the bench green and meaningful.**
  - Run `python3 ui_pixels.py` and `python3 tests/bench_m68k.py` after any change to rendering, codegen or
    `ui_draw.S`.
  - A new check must fail on the code before your fix.
  - When you change `ui_draw.S`, break it on purpose once (a mutation) and confirm the bench catches it.
- **No third-party bitmaps or binaries.** Fonts must be free and keep their licence in `fonts/README.md`. Never
  add firmware images, extracted bytes, screenshots of a device's own screens, or glyphs taken from one.
- **Licences.** GPL-3.0-or-later for the editor and tools; MIT for `ui_draw.S`, generated code and
  `examples/demo/demo.S`. Keep the SPDX headers.
- **Stay local.** The server binds to 127.0.0.1 and checks the `Origin` of every POST. Keep both.
