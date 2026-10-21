# OctaDraw project format

A project is one JSON file (`project.json` in the work folder, or any file opened with **Open…**).
`validate()` in `ui_components.py` is the authority: it rejects anything outside the ranges below, and
the editor, the PNG export and the code generator all go through it. Keys left out take the default shown.

## Project

| Key | Value |
|---|---|
| `version` | `1` |
| `name` | project name |
| `styles` | 1 to 8 named styles: `{"default": {"highlight_padding": 1}}`. `highlight_padding` 0..3 is the margin of a selected text's highlight. Every layer names its style in `style`. |
| `pages` | 1 to 48 screens (below) |
| `font` | optional default font key for new text |
| `target` | optional preview only: `lcd` (default, lit = dark) or `oled` (lit = bright) |

Font keys are the font file names without extension (`fixed-5x7`, or an imported font). A key that is not
loaded draws with the default font, so a project stays readable on another machine.

## Screen (`pages[]`)

| Key | Value |
|---|---|
| `id` | unique string. The code entry is `ui_page_N`, with N its position in `pages` (1-based) |
| `name` | up to 40 characters |
| `background` | `black` (default), `white`, `pattern`, or `reference` |
| `bg_pattern`, `bg_base` | for `pattern`: a pattern name (`checker`, `dots`, `hlines`, `grid`…) on `black` or `white` |
| `reference`, `reference_dim` | for `reference`: a PNG name in `<work>/references/`, shown in the editor only |
| `background_device` | `false` = background drawn in the editor only |
| `note` | up to 2000 characters for whoever wires the screen (copied into `NOTES.md`) |
| `visibility_states` | named snapshots `{"name": …, "hidden": {layer id: true/false}}` |
| `components` | up to 128 layers, drawn in order (later = on top) |

## Layer (`components[]`)

Every layer has `id` (unique on its screen), `type`, `style`, `x`, `y`, `width`, `height` (integers, inside
0..127 × 0..63) and optionally:

| Key | Value |
|---|---|
| `name` | up to 32 characters. A **text** layer named `$name` is a runtime slot (see the README) |
| `parent` | id of a container: `rect`, `group`, `grid` or `layout`. `x`, `y` stay screen coordinates; a dock, an auto layout or a constraint recomputes them from the parent's content |
| `color`, `background` | `black` / `white` (`line` also takes `invert`) |
| `device` | `false` = shown in the editor only, left out of the PNGs and the code |
| `hidden`, `locked` | editor state only |
| `inverted` | invert the area once the layer and its children are drawn |
| `dock`, `dock_gap`, `dock_span`, `dock_over_padding` | stick to a side (`top`, `bottom`, `left`, `right`) of a `rect` / `group` parent or of the screen |
| `constraint_x`, `constraint_y` | `left`, `right`, `both`, `center` or `scale` when the parent is resized |
| `shadows`, `effect_stroke` | up to 4 offset copies; an outline around the drawn shape |
| `master`, `instance_of`, `state`, `state_of`, `state_off` | linked components and their named states (managed by the editor) |
| `note` | up to 2000 characters |

| Type | Main keys |
|---|---|
| `text` | `text`, `font`, `text_align` (`start` / `center` / `end`), `text_case` (`upper` / `lower`), `text_padding` 0..16 or `padding_sides` [t, r, b, l], `fill` (`transparent` / `filled`), `hug`, `underline`, `stroke`, `space_width`, `selectable` + `focus_state` (`normal` / `selected`) |
| `rect` | `fill` (`none` / `black` / `white` / `invert`), `stroke`, `stroke_width` 1..4, `stroke_style`, `radius` 0..16, `pattern`, `padding` |
| `group` | container without drawing; `padding` |
| `shape` | `shape` (`ellipse`, `triangle`, `arrow`, `polygon`, `star`, `diamond`), `direction`, `sides`, `rotation`, `fill`, `stroke` |
| `line` | `ends` [[x, y], [x, y]] relative to the box, `stroke_width`, `stroke_style` (`solid` / `dotted` / `dashed`), `cap_start` / `cap_end` |
| `drawing` | `points` [[x, y]…] relative to the box (free pixels) |
| `image` | `pixels`: `width × height` characters, `1` lit (black), `0` unlit (drawn only when `white` is `opaque`), `.` transparent; `invert`, `xor` |
| `grid` | table: `grid_rows`, `grid_cols`, `header_rows`, `header_cols`, `header`, `header_text`, `side_text`, lines and fill |
| `layout` | auto layout of its children: `layout_cols`, `layout_rows`, `layout_flow`, `gap_x`, `gap_y`, `cell_w` / `cell_h` (`hug` / `fill`) |
| `list` | `items` (comma separated), `orientation` (`vertical` / `horizontal` / `grid`), `selected`, per-state styles `n_*` / `s_*`, separators; checkbox: `check`, `check_size` (`auto` or 5..12), `check_shape` (`square` / `round`), `check_padding` (0..3), `check_gap` (0..8), `marks` (one `0` / `1` per item); grid: `list_cols` / `list_rows` (0 = automatic, 1..64), `list_flow` (`rows` / `columns`), `list_col_width` (`hug` = each column fits its content; `equal` = same width for every column, never below the widest item), `list_col_max` (0 = automatic, 1..128 px) |
| `multislider` | `values` or a generated `source`, `range_min` / `range_max`, `ms_style`, `selected` |
| `scrollbar` | `orientation`, `track`, `total`, `visible`, `position` |
| `waveform` | test signal for previews: `signal`, `display`, `amplitude`, `cycles`, `seed`, `playhead`, trims, slices |
| `iso` | isometric solid: `iso_shape`, `iso_a`, `iso_b`, `iso_h`, face fills |
| `placeholder` | reserved zone: shown in the editor and the PNGs, never compiled. The host draws there |

## Saved screens and widgets

`<work>/screens/*.json` hold `{"kind": "octadraw-screen", "version": 1, "page": …, "styles": …}`.
`<work>/widgets/*.json` hold `{"kind": "octadraw-widget", "version": 1, "name", "width", "height",
"background", "components", "styles"}`, with coordinates relative to the widget's top-left corner.

## Export (`<work>/export/`)

`ui_commands.json` lists, per screen: `id`, `name`, `note`, `entry` (`ui_page_N`), `fonts`, `slots`
(runtime texts: `symbol`, `box`, `left`, `right`, `top`, `align`, `font`…), `components` (resolved bounds,
names, notes, reserved zones) and `commands` (the draw commands compiled into `ui_generated.S`).
