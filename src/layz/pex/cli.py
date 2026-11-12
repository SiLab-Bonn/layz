"""`layz pex`: capacitance extraction. A .kicad_pcb carries its own stackup; a GDS needs --stack."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    target = next((a for a in argv if not a.startswith("-")), "")
    if target.lower().endswith(".kicad_pcb"):
        from layz.pex.kicad import main as kicad_main
        return kicad_main(argv)
    from layz.pex.solve import main as gds_main
    return gds_main(argv)
