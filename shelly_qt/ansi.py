"""ANSI/VT escape handling for console lines in the operation log.

Shelly passes through build output (makepkg, git, compilers) that carries SGR
colour codes. Like the GTK app's transaction view, we render SGR colours and
styles and drop everything else: cursor movement, erase and OSC sequences
(including OSC-8 hyperlinks). Carriage return and backspace get the overwrite
behaviour a terminal would show for a single line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

# CSI ... final byte, OSC ... BEL/ST, and lone two-byte escapes.
_ESC = re.compile(r"\x1b(?:\[([0-?]*)[ -/]*([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[@-Z\\-_])")

PALETTE16 = [
    (0x00, 0x00, 0x00), (0xcd, 0x00, 0x00), (0x00, 0xcd, 0x00), (0xcd, 0xcd, 0x00),
    (0x00, 0x00, 0xee), (0xcd, 0x00, 0xcd), (0x00, 0xcd, 0xcd), (0xe5, 0xe5, 0xe5),
    (0x7f, 0x7f, 0x7f), (0xff, 0x00, 0x00), (0x00, 0xff, 0x00), (0xff, 0xff, 0x00),
    (0x5c, 0x5c, 0xff), (0xff, 0x00, 0xff), (0x00, 0xff, 0xff), (0xff, 0xff, 0xff),
]

Rgb = tuple[int, int, int]


@dataclass(frozen=True)
class Attrs:
    fg: Rgb | None = None
    bg: Rgb | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    inverse: bool = False
    hidden: bool = False


def color256(n: int) -> Rgb:
    if n < 16:
        return PALETTE16[n]
    if n < 232:
        n -= 16
        steps = (0, 95, 135, 175, 215, 255)
        return steps[n // 36], steps[(n // 6) % 6], steps[n % 6]
    v = 8 + (n - 232) * 10
    return v, v, v


def _extended(params: list[int], i: int) -> tuple[Rgb | None, int]:
    """Parse ``5;n`` or ``2;r;g;b`` after a 38/48; return (colour, params consumed)."""
    if i < len(params) and params[i] == 5 and i + 1 < len(params):
        return color256(params[i + 1] % 256), 2
    if i < len(params) and params[i] == 2 and i + 3 < len(params):
        r, g, b = (max(0, min(255, x)) for x in params[i + 1:i + 4])
        return (r, g, b), 4
    return None, 0


def apply_sgr(a: Attrs, codes: str) -> Attrs:
    params = [int(p) if p.isdigit() else 0 for p in codes.replace(":", ";").split(";")] if codes else [0]
    i = 0
    while i < len(params):
        p = params[i]
        i += 1
        if p == 0:
            a = Attrs()
        elif p == 1:
            a = replace(a, bold=True)
        elif p == 2:
            a = replace(a, dim=True)
        elif p == 3:
            a = replace(a, italic=True)
        elif p == 4:
            a = replace(a, underline=True)
        elif p == 7:
            a = replace(a, inverse=True)
        elif p == 8:
            a = replace(a, hidden=True)
        elif p == 22:
            a = replace(a, bold=False, dim=False)
        elif p == 23:
            a = replace(a, italic=False)
        elif p == 24:
            a = replace(a, underline=False)
        elif p == 27:
            a = replace(a, inverse=False)
        elif p == 28:
            a = replace(a, hidden=False)
        elif 30 <= p <= 37:
            a = replace(a, fg=PALETTE16[p - 30])
        elif 90 <= p <= 97:
            a = replace(a, fg=PALETTE16[p - 90 + 8])
        elif 40 <= p <= 47:
            a = replace(a, bg=PALETTE16[p - 40])
        elif 100 <= p <= 107:
            a = replace(a, bg=PALETTE16[p - 100 + 8])
        elif p == 39:
            a = replace(a, fg=None)
        elif p == 49:
            a = replace(a, bg=None)
        elif p in (38, 48):
            c, used = _extended(params, i)
            i += used
            if c is not None:
                a = replace(a, fg=c) if p == 38 else replace(a, bg=c)
    return a


def parse(line: str, start: Attrs | None = None) -> tuple[list[tuple[str, Attrs]], Attrs]:
    """Split one line into styled runs. Returns (runs, attributes in effect at the end)."""
    cells: list[tuple[str, Attrs]] = []  # one entry per visible character
    col = 0
    a = start or Attrs()
    pos = 0

    def put(text: str) -> None:
        nonlocal col
        for ch in text:
            if ch == "\r":
                col = 0
            elif ch == "\b":
                col = max(0, col - 1)
            elif ch < " " and ch != "\t":
                continue
            else:
                if col < len(cells):
                    cells[col] = (ch, a)
                else:
                    cells.append((ch, a))
                col += 1

    for m in _ESC.finditer(line):
        put(line[pos:m.start()])
        pos = m.end()
        if m.group(2) == "m":
            a = apply_sgr(a, m.group(1) or "")
    put(line[pos:])

    runs: list[tuple[str, Attrs]] = []
    for ch, attrs in cells:
        if runs and runs[-1][1] == attrs:
            runs[-1] = (runs[-1][0] + ch, attrs)
        else:
            runs.append((ch, attrs))
    return runs, a


def strip(text: str) -> str:
    """Plain text with escapes removed, line by line (for banners and parsing)."""
    if "\x1b" not in text and "\r" not in text and "\b" not in text:
        return text
    return "\n".join("".join(t for t, _ in parse(ln)[0]) for ln in text.split("\n"))
