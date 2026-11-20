"""layz: layout tools for SiLab's FR4 PCBs, RDL chips and flex PCBs.

    layz run FLOW      a design's flow: FLOW is its flow.py, or the folder with it
    layz web           the runs in a browser: http://HOST:8003/
    layz doctor        which external tools this machine has, then the tests

A flow.py names its layout (GDS or KiCad board), stack, schematic and limits, and runs its
targets in order: DRC and LVS, the HyperLynx board, capacitance and fields, DC drop, SI and
S-parameters, each through layz's Python API (layz.drc.run, layz.lvs.run, layz.gds2hyp,
layz.pex.run, layz.field.run, layz.hyperlynx.run; see layz/flow.py). Examples:
designs/ivtx_rdl/flow.py, designs/ivtx_flex/flow.py.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["run"] and len(argv) == 2:
        from layz import flow

        return flow.main(argv[1:])
    if argv == ["web"]:
        from layz.web import server

        return server.main()
    if argv == ["doctor"]:
        from layz import doctor

        return doctor.main([]) or 0
    if argv in (["-V"], ["--version"]):
        from layz import __version__

        print(f"layz {__version__}")
        return 0
    print(__doc__.strip())
    return 0 if argv in ([], ["-h"], ["--help"]) else 2


if __name__ == "__main__":
    sys.exit(main())
