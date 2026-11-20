"""layz: layout tools for SiLab's FR4 PCBs, RDL chips and flex PCBs.

    layz run       a design's flow, from DRC and LVS to SI and power: its targets, in order

In the order they run, one by one:

    layz doctor    which external tools (KiCad, FasterCap, ParaView, ...) this machine has, then the tests
    layz drc       design rule check of a GDS (gdscheck, the kit's deck)
    layz lvs       GDS connectivity vs a KiCad schematic (net and pin labels)
    layz pex       capacitance matrix with FasterCap/FastCap2 (GDS + stack, or .kicad_pcb)
    layz field     electric field and potential from a `layz pex --charges` run
    layz gds2hyp   GDS / KiCad .kicad_pcb / .hyp -> HyperLynx .hyp (signal pours as traces)
    layz view      open a result: a .lyrdb in KLayout, or ParaView renders of a field run

Utilities:

    layz gds2pcb   GDS -> KiCad .kicad_pcb (zones, footprints, vias, outline; nets from the GDS's labels)
    layz svg       GDS -> SVG preview

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
COMMANDS = {"run": ("layz.flow", "a design's flow: its targets, in order"), "doctor": ("layz.doctor", "which external tools this machine has, then the tests"), "drc": ("layz.drc.check", "design rule check of a GDS"), "lvs": ("layz.lvs.compare", "GDS connectivity vs a KiCad schematic"), "pex": ("layz.pex.cli", "capacitance matrix with FasterCap/FastCap2"), "field": ("layz.field.compute", "electric field and potential from a `layz pex --charges` run"), "gds2hyp": ("layz.gds2hyp.convert", "GDS / KiCad .kicad_pcb / .hyp -> HyperLynx .hyp"), "view": (None, "ParaView renders of a run: section | geometry | field"), "gds2pcb": ("layz.gds2pcb.convert", "GDS -> KiCad .kicad_pcb"), "svg": ("layz.svg.render", "GDS -> SVG preview")}

VIEWS = {"section": "section.py", "geometry": "geometry.py", "field": "view.py"}


def view_drc(argv: list[str]) -> int:
    """A DRC report in KLayout, over its layout: klayout LAYOUT -m REPORT."""
    import argparse

    ap = argparse.ArgumentParser(prog="layz view")
    ap.add_argument("report")
    ap.add_argument("--lay", required=True, help="the layout the report is for")
    a = ap.parse_args(argv)
    klayout = find_klayout()
    if not klayout:
        print("KLayout not found (on PATH, or in /Applications on macOS)", file=sys.stderr)
        return 2
    return subprocess.call([klayout, a.lay, "-m", a.report])


def find_klayout() -> str | None:
    """KLayout's program: on PATH, else inside a macOS app in /Applications (klayout.app,
    KLayout.app, ...: a .dmg puts no command on PATH)."""
    exe = shutil.which("klayout")
    if exe:
        return exe
    apps = Path("/Applications")
    for app in sorted(apps.iterdir()) if apps.is_dir() else []:
        exe = app / "Contents" / "MacOS" / "klayout"
        if app.name.lower().startswith("klayout") and app.suffix.lower() == ".app" and exe.exists():
            return str(exe)
    return None


def view(argv: list[str]) -> int:
    """Run one of the ParaView scripts with pvpython (ParaView's own Python)."""
    if argv and argv[0].endswith(".lyrdb"):
        return view_drc(argv)
    if not argv or argv[0] not in VIEWS:
        print("usage: layz view REPORT.lyrdb --lay LAYOUT.gds\n       layz view {section,geometry,field} ARGS...  (each takes -h)", file=sys.stderr)
        return 2
    pvpython = shutil.which("pvpython")
    if not pvpython:
        print("pvpython not found: install ParaView, https://www.paraview.org/download/", file=sys.stderr)
        return 2
    script = Path(__file__).parent / "field" / "paraview" / VIEWS[argv[0]]
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
