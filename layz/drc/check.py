"""`layz drc`: design rule check of a GDS with gdscheck and the kit's rule deck.

    layz drc --lay design.gds --kit uni-bonn-rdl [-o design.lyrdb] [--suite main|geometry]
    layz drc --lay design.gds --kit uni-bonn-rdl --benchmark   # time each rule
    layz view design.lyrdb --lay design.gds          # KLayout with the violation markers

Decks are gdscheck PDKs in the repo's drc/<kit>/ (pdk.yml, decks/, suites/), in gdscheck's own
format. Exit status: 0 clean, 2 violations (gdscheck's), 1 errors.
"""

from __future__ import annotations

from pathlib import Path

DRC_DIR = Path(__file__).resolve().parents[2] / "tech"  # tech/<kit>/pdk.yml


def kits() -> list[str]:
    return sorted(p.parent.name for p in DRC_DIR.glob("*/pdk.yml"))


def top_cell(gds: Path) -> str:
    from klayout import db

    layout = db.Layout()
    layout.read(str(gds))
    tops = layout.top_cells()
    if len(tops) != 1:
        raise SystemExit(f"{gds}: {len(tops)} top cells ({', '.join(c.name for c in tops)}); pick one with --topcell")
    return tops[0].name
