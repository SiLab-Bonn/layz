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
     "install KLayout (https://www.klayout.de/build.html)"),
    ("kicad-cli", ("program", "kicad-cli"), True, "schematic netlists, KiCad boards",
     "install KiCad"),
    ("FasterCap", ("solver", "fastercap"), True, "layz field / pex (3-D capacitance)",
     "scripts/build_solvers.sh (links it into ~/.local/bin)"),
    ("gdscheck", ("program", "gdscheck"), True, "layz drc",
     "cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck"),
    ("klayout (Python)", ("module", "klayout.db"), True, "everything", "uv sync"),
    ("klayout-pex", ("module", "klayout_pex"), True, "layz pex / field", "uv sync"),
    ("shapely", ("module", "shapely"), True, "layz nets", "uv sync"),
    ("pcbnew (KiCad)", ("module", "pcbnew"), True, "layz hyp, KiCad boards",
     "install KiCad; layz must run on the Python KiCad was built for (README); or set "
     "LAYZ_KICAD_PYTHONPATH to the folder with pcbnew.py"),
    ("HyperLynx", ("hyperlynx", ""), False, "opening layz hyp's .hyp files for SI/PI",
     "Siemens HyperLynx (licensed); set LAYZ_HYPERLYNX to its executable if it isn't on PATH"),
    ("FastCap2", ("solver", "fastcap2"), False, "--solver fastcap2", "scripts/build_solvers.sh"),
    ("pvpython (ParaView)", ("program", "pvpython"), False, "layz view of field results",
     "sudo apt install paraview"),
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
    """HyperLynx: $LAYZ_HYPERLYNX, a launcher on PATH, or a usual install folder."""
    env = os.environ.get("LAYZ_HYPERLYNX")
    if env:
        return os.path.exists(env), env if os.path.exists(env) else f"LAYZ_HYPERLYNX={env} doesn't exist"
    for prog in ("hyperlynx", "HyperLynx", "hl", "bsw", "boardsim"):
        if shutil.which(prog):
            return True, shutil.which(prog)
    import glob
    for pattern in ("/opt/*/[Hh]yper[Ll]ynx*", "/opt/[Hh]yper[Ll]ynx*", "/eda/*/[Hh]yper[Ll]ynx*",
                    os.path.expanduser("~/[Hh]yper[Ll]ynx*"),
                    "/mnt/c/MentorGraphics/*/SDD_HOME/hyperlynx*", "C:/MentorGraphics/*/SDD_HOME/hyperlynx*",
                    "C:/Siemens/*/SDD_HOME/hyperlynx*"):
        hits = glob.glob(pattern)
        if hits:
            return True, hits[0]
    return False, "not found"


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
