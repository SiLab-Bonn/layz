"""`layz doctor`: check that this machine has what layz needs, then run layz's tests.

    layz doctor            the tools, then the test suite (about 40 s)
    layz doctor --quick    the tools only

Required: klayout, kicad-cli, FasterCap, gdscheck and the Python modules layz imports (klayout,
klayout-pex, shapely, KiCad's pcbnew). Optional tools are reported but don't fail the check; the
tests that need them are skipped. Exit status: 0 when everything required is there and the tests
pass, 1 otherwise.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys

# (what, (kind, name), required, needed for, how to get it)
CHECKS = [
    ("klayout", ("program", "klayout"), True, "DRC/LVS, viewing GDS and DRC results", "https://www.klayout.de/build.html"),
    ("kicad-cli", ("program", "kicad-cli"), True, "schematic netlists, KiCad boards", "https://www.kicad.org/download/"),
    ("FasterCap", ("solver", "fastercap"), True, "layz field / pex (3-D capacitance)", "install/build_solvers.sh (links it into ~/.local/bin)"),
    ("gdscheck", ("solver", "gdscheck"), True, "layz drc", "install/install_gdscheck.sh"),
    ("klayout (Python)", ("module", "klayout.db"), True, "everything", "./install.sh (install.md)"),
    ("klayout-pex", ("module", "klayout_pex"), True, "layz pex / field", "./install.sh (install.md)"),
    ("shapely", ("module", "shapely"), True, "layz nets", "./install.sh (install.md)"),
    ("pcbnew (KiCad)", ("module", "pcbnew"), True, "layz gds2pcb, gds2hyp, KiCad boards", "install KiCad; layz must run on the Python KiCad was built for (install.md); or set LAYZ_KICAD_PYTHONPATH to the folder with pcbnew.py"),
    ("HyperLynx", ("hyperlynx", ""), False, "layz hyp (SI/PI runs)", "Siemens HyperLynx (licensed); set LAYZ_HYPERLYNX_HOME to its SDD_HOME folder"),
    ("FastCap2", ("solver", "fastcap2"), False, "--solver fastcap2", "install/build_solvers.sh"),
    ("pvpython (ParaView)", ("program", "pvpython"), False, "layz view of field results", "https://www.paraview.org/download/"),
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


def run_tests() -> int:
    """The repo's test suite (test/ in the clone layz runs from), in this Python."""
    import subprocess
    from pathlib import Path

    tests = Path(__file__).resolve().parents[1] / "test"
    if not tests.is_dir():
        print(f"tests: no {tests} (layz isn't running from its clone); skipped")
        return 0
    print(f"tests ({tests}):", flush=True)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "-W", "ignore::DeprecationWarning", str(tests)], cwd=tests.parent, env={**os.environ, "MPLBACKEND": "Agg"}).returncode  # plots to files only


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="layz doctor", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="check the tools only, without the tests")
    a = ap.parse_args(argv or [])
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
                print(f"          {'needed' if required else 'warning: optional, used'} for: {needed}; get it: {get}")
                missing_required += required
    if os.environ.get("HWLOC_COMPONENTS") is None and shutil.which("pvpython"):
        print("note: on Ubuntu, ParaView hangs at start-up unless HWLOC_COMPONENTS=-gl is set (layz view sets it for you)")
    if missing_required:
        print(f"{missing_required} required missing")
    else:
        print("all required tools found")
    failed = 0 if a.quick else run_tests()
    return 1 if missing_required or failed else 0
