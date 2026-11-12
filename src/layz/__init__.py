"""layz: layout tools for SiLab FR4 PCBs, RDL chips and flex PCBs."""

__version__ = "0.2.0"

import glob as _glob
import importlib.util as _util
import os as _os
import sys as _sys

# KiCad's `pcbnew` Python module ships with KiCad, not on PyPI, so a `uv tool install` (an
# isolated venv) can't see it. Find it and append its folder to sys.path: appended, so layz's
# own dependencies always come first. Override with LAYZ_KICAD_PYTHONPATH. The module is built for
# one Python version (Ubuntu 26.04: 3.14), so install layz with that Python (see README).
_KICAD_PATHS = [
    "/usr/lib/python3/dist-packages",                                   # Debian, Ubuntu
    f"/usr/lib/python3.{_sys.version_info.minor}/site-packages",       # Arch
    f"/usr/lib64/python3.{_sys.version_info.minor}/site-packages",     # Fedora
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current"
    f"/lib/python3.{_sys.version_info.minor}/site-packages",           # macOS
]


def _find_kicad_python() -> str | None:
    paths = [p for p in _os.environ.get("LAYZ_KICAD_PYTHONPATH", "").split(_os.pathsep) if p]
    for d in paths + _KICAD_PATHS:
        if _glob.glob(_os.path.join(d, "pcbnew.py")):
            return d
    return None


if _util.find_spec("pcbnew") is None:
    _d = _find_kicad_python()
    if _d and _d not in _sys.path:
        _sys.path.append(_d)
