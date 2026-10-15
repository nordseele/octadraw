# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 nordseele
"""128 x 64 one-bit canvas helpers: text measurement and fitting, rectangles, 5-px glyphs."""
W, H = 128, 64

# Scrollbar arrows, 5 x 3, one byte per row (bit 7 = leftmost pixel).
G_UP = (5, [0x20, 0x70, 0xF8])
G_DN = (5, [0xF8, 0x70, 0x20])


def text_width(font, s):
    """Ink width: the advances of every glyph but the last, then the last one's own width."""
    if not s:
        return 0
    return sum(font[ord(c)]["adv"] for c in s[:-1]) + font[ord(s[-1])]["wid"]


def fit(font, s, width):
    while s and text_width(font, s) > width:
        s = s[:-1]
    return s


def blank(v=0):
    return [[v] * W for _ in range(H)]


def rect(img, x0, r0, x1, r1, op):
    """op 0 clear, 1 set, 2 invert; the caller keeps the bounds inside the screen."""
    for r in range(r0, r1 + 1):
        for x in range(x0, x1 + 1):
            img[r][x] = 1 if op == 1 else (0 if op == 0 else 1 - img[r][x])


def glyph(img, g, x, r, op=1):
    w, rows = g
    for dy, bits in enumerate(rows):
        for dx in range(w):
            if bits & (0x80 >> dx) and 0 <= r + dy < H and 0 <= x + dx < W:
                img[r + dy][x + dx] = op


if __name__ == "__main__":
    font = {ord("A"): dict(ink=[], wid=3, adv=4), ord("B"): dict(ink=[], wid=5, adv=6)}
    assert text_width(font, "AB") == 9 and fit(font, "ABAB", 9) == "AB" and fit(font, "A", 0) == ""
    img = blank(); glyph(img, G_UP, 126, 62)
    assert img[62][126] == 0 and img[63][126] == 0 and img[63][127] == 1   # clipped at the screen edge
    print("ui_pixels OK")
