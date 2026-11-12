"""Locate the external field solvers.

Order: an explicit environment variable (LAYZ_FASTERCAP / LAYZ_FASTCAP2), then the program
on PATH (`FasterCap`, `fastcap`). scripts/build_solvers.sh builds both and links them into
~/.local/bin.
"""

from __future__ import annotations

import os
import shutil

_SOLVERS = {
    "fastercap": ("LAYZ_FASTERCAP", "FasterCap"),
    "fastcap2": ("LAYZ_FASTCAP2", "fastcap"),
}


def find(solver: str) -> str:
    env, program = _SOLVERS[solver]
    path = os.environ.get(env) or shutil.which(program)
    if not path:
        raise SystemExit(
            f"{program} not found: build it with scripts/build_solvers.sh (which links it into "
            f"~/.local/bin), or set {env} to its path")
    return path
