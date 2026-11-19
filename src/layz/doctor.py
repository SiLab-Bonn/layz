"""`layz doctor`: check that this machine has what layz needs.

Required: the three tools on PATH (klayout, kicad-cli, FasterCap) and the Python modules layz
imports (klayout, klayout-pex, shapely, KiCad's pcbnew). Optional tools are reported but don't
fail the check. Exit status: 0 when everything required is there, 1 otherwise.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys

# (what, (kind, name), required, needed for, how to get it)
CHECKS = [
    ("klayout", ("program", "klayout"), True, "DRC/LVS, viewing GDS and DRC results",
     "https://www.klayout.de/build.html"),
    ("kicad-cli", ("program", "kicad-cli"), True, "schematic netlists, KiCad boards",
     "https://www.kicad.org/download/"),
    ("FasterCap", ("solver", "fastercap"), True, "layz field / pex (3-D capacitance)",
     "scripts/build_solvers.sh (links it into ~/.local/bin)"),
    ("gdscheck", ("solver", "gdscheck"), True, "layz drc",
     "cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck"),
    ("klayout (Python)", ("module", "klayout.db"), True, "everything", "./install.sh (install.md)"),
    ("klayout-pex", ("module", "klayout_pex"), True, "layz pex / field", "./install.sh (install.md)"),
    ("shapely", ("module", "shapely"), True, "layz nets", "./install.sh (install.md)"),
    ("pcbnew (KiCad)", ("module", "pcbnew"), True, "layz gds2pcb, gds2hyp, KiCad boards",
     "install KiCad; layz must run on the Python KiCad was built for (install.md); or set "
     "LAYZ_KICAD_PYTHONPATH to the folder with pcbnew.py"),
    ("HyperLynx", ("hyperlynx", ""), False, "layz hyp (SI/PI runs)",
     "Siemens HyperLynx (licensed); set LAYZ_HYPERLYNX_HOME to its SDD_HOME folder"),
    ("FastCap2", ("solver", "fastcap2"), False, "--solver fastcap2", "scripts/build_solvers.sh"),
    ("pvpython (ParaView)", ("program", "pvpython"), False, "layz view of field results",
     "https://www.paraview.org/download/"),
]


def _check(kind: str, name: str) -> tuple[bool, str]:
    if kind == "module":
        try:
            m = importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 - report any import failure
            return False, f"{type(e).__name__}: {e}"
        v = m.Version() if name == "pcbnew" else getattr(m, "__version__", "")
        return True, f"{v} ({os.path.dirname(getattr(m, '__file__', '') or '')})".strip()
    if kind == "solver":
        from layz import solvers
        try:
            return True, solvers.find(name)
        except SystemExit as e:
            return False, str(e)
    if kind == "hyperlynx":
        return _find_hyperlynx()
    path = shutil.which(name)
    return (path is not None), (path or "not on PATH")


def _find_hyperlynx() -> tuple[bool, str]:
    """HyperLynx as `layz hyp` finds it: $LAYZ_HYPERLYNX_HOME, or an SDD_HOME under /eda/Siemens."""
    from layz.hyperlynx import setup
    try:
        return True, str(setup.find_install())
    except SystemExit as e:
        return False, str(e)


def main(argv: list[str] | None = None) -> int:
    print(f"python {sys.version.split()[0]} ({sys.executable})")
    missing_required = 0
    for section, req in (("required", True), ("optional", False)):
        print(f"{section}:")
        for what, (kind, name), required, needed, get in CHECKS:
            if required != req:
                continue
            ok, info = _check(kind, name)
            print(f"  {'ok' if ok else ('MISSING' if required else '--'):<7} {what:<20} {info}")
            if not ok:
                print(f"          {'needed' if required else 'warning: optional, used'} for: {needed}; "
                      f"get it: {get}")
                missing_required += required
    if os.environ.get("HWLOC_COMPONENTS") is None and shutil.which("pvpython"):
        print("note: on Ubuntu, ParaView hangs at start-up unless HWLOC_COMPONENTS=-gl is set "
              "(layz view sets it for you)")
    if missing_required:
        print(f"{missing_required} required missing")
        return 1
    print("all required tools found")
    return 0
