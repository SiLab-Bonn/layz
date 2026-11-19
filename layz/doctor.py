"""`layz doctor`: check that this machine has what layz needs, then run layz's tests.

    layz doctor            the tools, then the test suite (about 40 s)
    layz doctor --quick    the tools only

One line per tool: ok, !! (required and missing, with how to get it), -- (optional, or not
available). The tests that need a missing tool are skipped.
Exit status: 0 when everything required is there and the tests pass, 1 otherwise.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys

# (what, checks, required, needed for, how to get it); a check is (kind, name)
CHECKS = [("KLayout", [("program", "klayout")], True, "DRC/LVS, viewing GDS", "sudo install/system.sh"), ("KiCad 10", [("kicad", "")], True, "gds2hyp from a board or GDS, pex on boards, lvs", "./install.sh (layz's own KiCad: install/kicad.sh)"), ("FasterCap", [("solver", "fastercap")], True, "pex, field", "./install.sh"), ("gdscheck", [("solver", "gdscheck")], True, "drc", "./install.sh"), ("Python modules", [("module", "klayout.db"), ("module", "klayout_pex"), ("module", "shapely")], True, "everything", "./install.sh"), ("HyperLynx", [("hyperlynx", "")], False, "hyp", "licensed; set LAYZ_HYPERLYNX_HOME to its SDD_HOME"), ("FastCap2", [("solver", "fastcap2")], False, "pex --solver fastcap2", "sudo install/system.sh, then ./install.sh"), ("ParaView", [("program", "pvpython")], False, "view", "./install.sh")]


def _short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


def _check(kind: str, name: str) -> tuple[bool, str]:
    if kind == "module":
        try:
            m = importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 - report any import failure
            return False, f"{type(e).__name__}: {e}"
        v = m.Version() if name == "pcbnew" else getattr(m, "__version__", "")
        return True, f"{name.split('.')[0].replace('_', '-')} {v}".strip()
    if kind == "solver":
        from layz import solvers

        try:
            return True, _short(solvers.find(name))
        except SystemExit:
            return False, "not found"
    if kind == "kicad":  # layz's own KiCad: kicad-cli and pcbnew in its environment
        import subprocess

        from layz import kicad

        cli, py = kicad.cli(), kicad.python()
        if not cli:
            return False, "no kicad-cli"
        if py is None:
            return (True, f"{_short(cli)}, pcbnew here (not layz's own KiCad)") if kicad.pcbnew_here() else (False, "no KiCad environment")
        r = subprocess.run([str(py), "-c", "import pcbnew; print(pcbnew.Version())"], capture_output=True, text=True)
        return (r.returncode == 0), (f"{_short(cli)}, pcbnew {r.stdout.strip()} in {_short(str(py.parent.parent))}" if r.returncode == 0 else "pcbnew doesn't import in its environment")
    if kind == "hyperlynx":
        from layz.hyperlynx import setup

        try:
            return True, str(setup.find_install())
        except SystemExit:
            return False, "not found"
    path = shutil.which(name)
    return (path is not None), (_short(path) if path else "not on PATH")


def _os_name() -> str:
    try:
        return next(line.split("=", 1)[1].strip().strip('"') for line in open("/etc/os-release") if line.startswith("PRETTY_NAME="))
    except (OSError, StopIteration):
        return sys.platform


def run_tests() -> tuple[int, str]:
    """The repo's test suite (test/ in the clone layz runs from), in this Python: (status, summary)."""
    import subprocess
    from pathlib import Path

    tests = Path(__file__).resolve().parents[1] / "test"
    if not tests.is_dir():
        return 0, "no test/ (layz isn't running from its clone)"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "-W", "ignore::DeprecationWarning", "-rf", str(tests)], cwd=tests.parent, env={**os.environ, "MPLBACKEND": "Agg"}, capture_output=True, text=True)  # plots to files only
    lines = [line for line in r.stdout.splitlines() if line.strip()]
    summary = lines[-1].strip("= ") if lines else "no output"
    failed = [line for line in lines if line.startswith("FAILED")]
    return r.returncode, summary + ("".join(f"\n    {f}" for f in failed) if failed else "")


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="layz doctor", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="check the tools only, without the tests")
    a = ap.parse_args(argv or [])
    width = max(60, shutil.get_terminal_size((100, 20)).columns)

    def say(line: str) -> None:
        print(line if len(line) <= width else line[: width - 1] + "…")

    say(f"layz doctor: {_os_name()}, Python {sys.version.split()[0]} in {_short(os.path.dirname(os.path.dirname(sys.executable)))}")
    missing = 0
    for what, checks, required, needed, get in CHECKS:
        results = [_check(kind, name) for kind, name in checks]
        ok = all(r[0] for r in results)
        if ok:
            say(f"  ok  {what:<15} {', '.join(r[1] for r in results)}")
        elif required:
            missing += 1
            say(f"  !!  {what:<15} missing ({needed}): {get}")
        else:
            say(f"  --  {what:<15} optional ({needed}): {get}")
    status = 0
    if not a.quick:
        status, summary = run_tests()
        say(f"tests: {summary}")
    say(f"{missing} required missing" if missing else "ready")
    return 1 if missing or status else 0
