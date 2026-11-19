"""Locate the external field solvers.

Order: an explicit environment variable (LAYZ_FASTERCAP / LAYZ_FASTCAP2 / LAYZ_GDSCHECK),
then the program on PATH (`FasterCap`, `fastcap`, `gdscheck`), then its usual install folder
even when that isn't on PATH (~/.local/bin for the solvers, which install/build_solvers.sh links
there; ~/.cargo/bin for gdscheck, where `cargo install` puts it).
"""

from __future__ import annotations

import os
import shutil

# tool -> (environment variable, program name, extra folders searched after PATH, how to get it)
_SOLVERS = {
    "fastercap": ("LAYZ_FASTERCAP", "FasterCap", ["~/.local/bin"], "build it with install/build_solvers.sh (which links it into ~/.local/bin)"),
    "fastcap2": ("LAYZ_FASTCAP2", "fastcap", ["~/.local/bin"], "build it with install/build_solvers.sh (which links it into ~/.local/bin)"),
    # cargo installs into ~/.cargo/bin, which isn't on PATH when Rust comes from the distribution
    "gdscheck": ("LAYZ_GDSCHECK", "gdscheck", ["~/.cargo/bin"], "cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck"),
}


def find(solver: str) -> str:
    env, program, extra, how = _SOLVERS[solver]
    path = os.environ.get(env) or shutil.which(program)
    if not path:
        dirs = os.pathsep.join(os.path.expanduser(d) for d in extra)
        path = shutil.which(program, path=dirs)
    if not path:
        raise SystemExit(f"{program} not found: {how}; or set {env} to its path")
    return path
