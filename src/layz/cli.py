"""layz: layout tools for SiLab's FR4 PCBs, RDL chips and flex PCBs.

    layz drc       design rule check of a GDS (gdscheck, the kit's deck)
    layz gds2pcb   GDS -> KiCad .kicad_pcb (copper zones, footprints, vias, outline)
    layz nets      assign zone/via nets from a seed footprint's pad nets
    layz hyp       KiCad .kicad_pcb -> HyperLynx .hyp
    layz svg       GDS -> SVG preview
    layz pex       capacitance matrix with FasterCap/FastCap2 (.kicad_pcb, or GDS + stack)
    layz field     electric field and potential from a `layz pex --charges` run
    layz view      open a result: a .lyrdb in KLayout, or ParaView renders of a field run
    layz doctor    which external tools (KiCad, FasterCap, ParaView, ...) this machine has

`layz <command> -h` shows each command's options.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

# command -> (module, one-line help); modules load lazily, so `layz svg` doesn't import pcbnew
COMMANDS = {
    "drc": ("layz.drc", "design rule check of a GDS"),
    "gds2pcb": ("layz.gds2pcb", "GDS -> KiCad .kicad_pcb"),
    "nets": ("layz.nets", "assign zone/via nets from a seed footprint's pad nets"),
    "hyp": ("layz.hyp", "KiCad .kicad_pcb -> HyperLynx .hyp"),
    "svg": ("layz.svg", "GDS -> SVG preview"),
    "pex": ("layz.pex.cli", "capacitance matrix with FasterCap/FastCap2"),
    "field": ("layz.field", "electric field and potential from a `layz pex --charges` run"),
    "view": (None, "ParaView renders of a run: section | geometry | field"),
    "doctor": ("layz.doctor", "which external tools this machine has"),
}

VIEWS = {"section": "section.py", "geometry": "geometry.py", "field": "view.py"}


def view_drc(argv: list[str]) -> int:
    """A DRC report in KLayout, over its layout: klayout LAYOUT -m REPORT."""
    import argparse
    ap = argparse.ArgumentParser(prog="layz view")
    ap.add_argument("report")
    ap.add_argument("--lay", required=True, help="the layout the report is for")
    a = ap.parse_args(argv)
    klayout = shutil.which("klayout")
    if not klayout:
        print("klayout not found on PATH", file=sys.stderr)
        return 2
    return subprocess.call([klayout, a.lay, "-m", a.report])


def view(argv: list[str]) -> int:
    """Run one of the ParaView scripts with pvpython (ParaView's own Python)."""
    if argv and argv[0].endswith(".lyrdb"):
        return view_drc(argv)
    if not argv or argv[0] not in VIEWS:
        print("usage: layz view REPORT.lyrdb --lay LAYOUT.gds\n"
              "       layz view {section,geometry,field} ARGS...  (each takes -h)", file=sys.stderr)
        return 2
    pvpython = shutil.which("pvpython")
    if not pvpython:
        print("pvpython not found: install ParaView, https://www.paraview.org/download/", file=sys.stderr)
        return 2
    script = Path(__file__).parent / "paraview" / VIEWS[argv[0]]
    env = dict(os.environ)
    env.setdefault("HWLOC_COMPONENTS", "-gl")  # Ubuntu's ParaView hangs at start-up without it
    return subprocess.call([pvpython, str(script), *argv[1:]], env=env)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] in ("-V", "--version"):
        from layz import __version__
        print(f"layz {__version__}")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"layz: unknown command {cmd!r}; one of: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    if cmd == "view":
        return view(rest)
    sys.argv[0] = f"layz {cmd}"  # argparse prog name in each command's usage line
    result = importlib.import_module(COMMANDS[cmd][0]).main(rest)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
