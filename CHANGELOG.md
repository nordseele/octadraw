# Release notes

## 0.13 — 2026-10-21

### Lists
- **Checkbox on every row**: height (`auto` or 5..12 px), shape (square or round), inner padding (0..3),
  gap to the text (0..8) and a checked state per row (`marks`). The row grows to `max(text, checkbox)` and
  both stay centred.
- **Grid reflow**: `Direction: Grid` with `Columns` / `Rows` fixed or automatic, a fill order, columns that
  hug their content or share the width equally, a maximum column width, and row / column separators.
- The Hug size accounts for the checkbox and for the grid.
- Grid dimensions go up to 64 columns / rows, so `Rows: 1` works with any number of items; a render error
  clears the canvas instead of leaving a stale frame that drifts away from the selection.
- Equal columns never shrink below the widest item, so a narrow or pasted list shows its text at once
  instead of an empty box.
- A pasted layer keeps the place and size it was copied at: the paste root drops Hug and its
  size/position constraints, so the selection box no longer jumps and the text shows without a resize.
- New lists keep a fixed width and hug their height, so adding items grows the list instead of
  overflowing; a Hug layer that no longer fits the 64 px screen is clipped at the screen edge instead of
  failing the preview. Dragging a Hug handle makes that axis fixed.

### Screen background
- The option is now **Reference image**; the "(editor only)" qualifier is gone.
- With no PNG in `references/`, the option says so and its tooltip gives the work folder path.
- **bg on device** is unchecked and disabled for a reference image, with an explanation: a reference is a
  tracing guide, never drawn on the device.

### Documentation and examples
- `docs/FORMAT.md`: the new list keys and the grid.
- `README.md`: checkboxes, grids and reference images.
- `examples/checklist/`: square checks, automatic hug columns and a capped column width.

## 0.12 — 2026-10-15
- First layout: 128 × 64 one-bit editor, ColdFire export, slot text, fonts, examples and the pixel bench.
