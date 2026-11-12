"""`layz drc`: design rule check of a GDS with gdscheck and the kit's rule deck.

    layz drc --lay design.gds --kit silab-rdl [-o design.lyrdb] [--suite main|geometry]
    layz view design.lyrdb --lay design.gds          # KLayout with the violation markers

Decks are gdscheck PDKs in the repo's drc/<kit>/ (pdk.yml, decks/, suites/), in gdscheck's own
format. Exit status: 0 clean, 2 violations (gdscheck's), 1 errors.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DRC_DIR = Path(__file__).resolve().parents[2] / "drc"


def kits() -> list[str]:
    return sorted(p.parent.name for p in DRC_DIR.glob("*/pdk.yml"))


def top_cell(gds: Path) -> str:
    import klayout.db as db
    layout = db.Layout()
    layout.read(str(gds))
    tops = layout.top_cells()
    if len(tops) != 1:
        raise SystemExit(f"{gds}: {len(tops)} top cells ({', '.join(c.name for c in tops)}); "
                         "pick one with --topcell")
    return tops[0].name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lay", type=Path, required=True, help="layout (.gds, .gds.gz)")
    ap.add_argument("--kit", required=True, help=f"process kit: {', '.join(kits()) or '(none found)'}")
    ap.add_argument("-o", "--out", type=Path, help="report (.lyrdb; default: next to the layout)")
    ap.add_argument("--suite", default="main", help="gdscheck suite (default: main)")
    ap.add_argument("--topcell", help="top cell (default: the layout's only top cell)")
    ap.add_argument("--tile", type=float, default=2000.0,
                    help="gdscheck merge tile, µm (default 2000: board/RDL scale; gdscheck's own "
                         "20 µm is for chips and is much slower here)")
    ap.add_argument("-v", "--verbose", action="store_true", help="every violation's message")
    args = ap.parse_args(argv)

    gdscheck = shutil.which("gdscheck")
    if not gdscheck:
        raise SystemExit("gdscheck not found on PATH: "
                         "cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck")
    if args.kit not in kits():
        raise SystemExit(f"no DRC deck for kit {args.kit!r}; have: {', '.join(kits())}")
    out = args.out or args.lay.with_suffix(".lyrdb")
    cmd = [gdscheck, "run", "--pdk-path", str(DRC_DIR), "-p", args.kit, "-s", args.suite,
           "-t", args.topcell or top_cell(args.lay), "--tile", str(args.tile),
           "-i", str(args.lay), "-r", str(out)]
    if args.verbose:
        cmd.append("-v")
    rc = subprocess.call(cmd)
    if out.exists():
        print(f"open in KLayout: layz view {out} --lay {args.lay}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
