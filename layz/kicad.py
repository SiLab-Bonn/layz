"""layz's own KiCad: kicad-cli and the pcbnew Python module, kept apart from any KiCad the user has.

install/kicad.sh puts KiCad 10 in ~/.local/share/layz (KiCad's AppImage, unpacked, on Linux;
KiCad.app on macOS) with a small Python environment on KiCad's own Python (``kicad-env``: KiCad's
Python is 3.11 in the AppImage, too old for all of layz, so only the steps that need pcbnew run
there). This module finds them; nothing goes on the user's PATH.

    cli()          kicad-cli, layz's own (else one on PATH)
    python()       the KiCad environment's Python, or None
    run(argv)      run `layz ARGV` in the KiCad environment (a command that needs pcbnew)
    pcbnew_here()  whether this Python can import pcbnew itself (a fallback without layz's KiCad)
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "10.0.8"
TOOLS = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "layz"
REPO = Path(__file__).resolve().parents[1]  # the clone; its `layz` link is the package
APP = Path("/Applications/KiCad/KiCad.app")


def python() -> Path | None:
    """The KiCad environment's Python ($LAYZ_KICAD_PYTHON, else install/kicad.sh's), or None."""
    env = os.environ.get("LAYZ_KICAD_PYTHON")
    if env:
        return Path(env)
    p = TOOLS / "kicad-env" / "bin" / "python"
    return p if p.exists() else None


def cli() -> str | None:
    """kicad-cli: layz's own KiCad first, else one on PATH."""
    for p in (TOOLS / f"kicad-{VERSION}" / "bin" / "kicad-cli", APP / "Contents" / "MacOS" / "kicad-cli"):
        if p.exists():
            return str(p)
    return shutil.which("kicad-cli")


def pcbnew_here() -> bool:
    return importlib.util.find_spec("pcbnew") is not None


def in_kicad_env() -> bool:
    """Whether this process already is the KiCad environment."""
    py = python()
    return py is not None and Path(sys.prefix).resolve() == py.parent.parent.resolve()


def use_env() -> bool:
    """Whether a command needing pcbnew should go to the KiCad environment: layz's own KiCad
    whenever it is installed (it doesn't mix with a KiCad the user has), unless this is it."""
    return python() is not None and not in_kicad_env()


def run(argv: list[str]) -> int:
    """`layz ARGV` in the KiCad environment, with this clone's layz."""
    py = python()
    if py is None:
        raise SystemExit("layz's KiCad is not installed: run install/kicad.sh (or ./install.sh)")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
    return subprocess.run([str(py), "-m", "layz.cli", *argv], env=env).returncode


def require_pcbnew() -> None:
    """Exit with how to get KiCad if this Python can't import pcbnew."""
    if not pcbnew_here():
        raise SystemExit("this step needs KiCad's pcbnew: run install/kicad.sh (or ./install.sh), which installs layz's own KiCad 10")
