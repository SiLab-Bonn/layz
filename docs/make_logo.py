"""Draw the layz logo: "layz" as four keycaps, the y and z keys highlighted (the two swap places
between English and German keyboards).

    .layz-env/bin/python docs/make_logo.py        # -> docs/logo.svg

Letters are DejaVu Sans Mono (it ships with matplotlib) converted to outlines, so the SVG looks the
same wherever it is shown. Colours: the Nord palette of the plot style.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.font_manager import FontProperties
from matplotlib.path import Path as MPath
from matplotlib.textpath import TextPath

KEY, GAP, LIP, R = 100.0, 14.0, 8.0, 14.0  # key size, gap between keys, side/bottom lip, corner radius
PLAIN = {"cap": "#ECEFF4", "lip": "#D8DEE9", "edge": "#4C566A", "text": "#2E3440"}
SWAP = {"cap": "#5E81AC", "lip": "#4C6A93", "edge": "#2E3440", "text": "#ECEFF4"}
MONO = FontProperties(family="DejaVu Sans Mono", weight="bold")


def glyph(ch: str, size: float, x: float, y: float, anchor: str = "center") -> str:
    """The outline of ``ch`` as SVG path data, ``size`` units high, placed at (x, y) (SVG
    coordinates, y down): centred on it, or with its top-left corner at it."""
    tp = TextPath((0, 0), ch, size=size, prop=MONO)
    ext = tp.get_extents()
    if anchor == "center":
        dx, dy = x - (ext.x0 + ext.x1) / 2, y + (ext.y0 + ext.y1) / 2
    else:  # top-left
        dx, dy = x - ext.x0, y + ext.y1
    out = []
    for verts, code in tp.iter_segments():
        pts = [(dx + verts[i], dy - verts[i + 1]) for i in range(0, len(verts), 2)]
        cmd = {MPath.MOVETO: "M", MPath.LINETO: "L", MPath.CURVE3: "Q", MPath.CURVE4: "C", MPath.CLOSEPOLY: "Z"}[code]
        out.append(cmd if cmd == "Z" else cmd + " ".join(f"{px:.2f},{py:.2f}" for px, py in pts))
    return " ".join(out)


def key(x: float, letter: str, swap: str | None) -> str:
    c = SWAP if swap else PLAIN
    top_w = KEY - 2 * LIP
    parts = [
        # the key's body and its lip (darker sides), then the top face, raised towards the back
        f'<rect x="{x:.1f}" y="0" width="{KEY}" height="{KEY}" rx="{R}" fill="{c["lip"]}" stroke="{c["edge"]}" stroke-width="3"/>',
        f'<rect x="{x + LIP:.1f}" y="{LIP * 0.5:.1f}" width="{top_w}" height="{top_w}" rx="{R * 0.7}" fill="{c["cap"]}"/>',
        f'<path d="{glyph(letter, 54, x + KEY / 2, LIP * 0.5 + top_w * 0.56)}" fill="{c["text"]}"/>',
    ]
    return "\n  ".join(parts)


def main() -> None:
    keys = [("l", None), ("a", None), ("y", "swap"), ("z", "swap")]
    pad = 6.0
    width = 4 * KEY + 3 * GAP + 2 * pad
    height = KEY + 2 * pad
    body = "\n  ".join(key(i * (KEY + GAP), ch, swap) for i, (ch, swap) in enumerate(keys))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad} {-pad} {width} {height}" width="{width * 0.6:.0f}" height="{height * 0.6:.0f}" role="img" aria-label="layz">\n  <title>layz</title>\n  {body}\n</svg>\n'
    out = Path(__file__).with_name("logo.svg")
    out.write_text(svg)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
