"""Capacitance extraction for a flow's targets (layz.flow): every option given, the results in
one folder.

    from layz.pex import analysis, plots, run

    caps = run.capacitance(GDS, RESULTS / "pex", stack="uni-bonn-rdl", ...)
    analysis.coupling(caps, max_coupling_fF=50.0, out=caps / "coupling.csv")
    plots.matrix(caps, caps)

Writes into ``out``: maxwell_matrix_fF.csv (Maxwell matrix: diagonal total, off-diagonal minus
the mutual), spice_caps_fF.csv (a, b, C: the mutual capacitances, and each conductor's to
infinity), the solver's model (.lst/.geo) and log, job.json (the options), and with charges=True
the panel charges `layz.field.run` needs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def capacitance(layout: Path, out: Path, *, stack: str | Path | None, cell: str | None, names: dict[str, tuple[str, float, float]], nets: list[str] | None, split_nets: bool, solver: str, tolerance: float, mesh: float, d_coeff: float, galerkin: bool, amax: float | None, delaunay_b: float, charges: bool, stl: bool, refill: bool) -> Path:
    """The capacitance matrix of the conductors of ``layout`` (a GDS with ``stack``, or a
    .kicad_pcb with stack=None: the board carries its own).

    cell        top cell (None: the layout's)
    names       body name -> (conductor layer name, x, y µm): names the body touching that point
    nets        only these bodies (None: all)
    split_nets  disconnected bodies of one name stay separate conductors
    solver      "fastercap" or "fastcap2"
    tolerance   relative (keep <= 0.01 with dielectrics); mesh, d_coeff, galerkin: FasterCap's
                -m, -d, -g
    amax        largest start triangle, µm² (None: FasterCap refines itself; FastCap2 bbox/2000)
    delaunay_b  KLayout-PEX's triangulation parameter
    charges     also the panel charges, for layz.field.run
    stl         also an STL per body and dielectric
    refill      .kicad_pcb: fill the zones first (False: the fills as saved)
    """
    from layz.pex import solve

    out.mkdir(parents=True, exist_ok=True)
    options = {"layout": str(layout), "stack": str(stack) if stack else None, "cell": cell, "names": names, "nets": nets, "split_nets": split_nets, "solver": solver, "tolerance": tolerance, "mesh": mesh, "d_coeff": d_coeff, "galerkin": galerkin, "amax": amax, "delaunay_b": delaunay_b, "charges": charges, "stl": stl, "refill": refill}
    (out / "job.json").write_text(json.dumps(options, indent=1))
    args = argparse.Namespace(split_nets=split_nets, nets=",".join(nets) if nets else None, solver=solver, amax=amax, delaunay_b=delaunay_b, tolerance=tolerance, mesh=mesh, d_coeff=d_coeff, galerkin=galerkin, charges=charges, stl=stl, list=False, dry_run=False, verbose=False)
    solve.setup_logging(False)
    ports = [(name, conductor, x, y) for name, (conductor, x, y) in names.items()]
    if Path(layout).suffix.lower() == ".kicad_pcb":
        if stack is not None:
            raise ValueError("a .kicad_pcb carries its own stackup: stack=None")
        layout_db, top, process_stack = _board(Path(layout), refill)
    else:
        from layz import stack as stackfile

        if stack is None:
            raise ValueError("a GDS needs its stack")
        layout_db, top = solve.load_gds(Path(layout), cell)
        process_stack = solve.stack_from_process(stackfile.load(stack), gds=True)
    solve.run_flow(args, layout_db, top, process_stack, out, ports)
    return out


def _board(pcb: Path, refill: bool):
    """A board's copper and stackup, read with KiCad's pcbnew (in layz's KiCad environment)."""
    import sys
    import tempfile

    from layz import kicad
    from layz.pex.kicad import import_board, load_board, print_stack

    if kicad.use_env() or not kicad.pcbnew_here():
        with tempfile.TemporaryDirectory() as tmp:
            if kicad.run("layz.pex.kicad", [str(pcb), tmp] + (["refill"] if refill else [])):
                raise SystemExit("reading the board in layz's KiCad environment failed")
            layout, top, stack, warnings = import_board(Path(tmp))
    else:
        layout, top, stack, warnings = load_board(pcb, refill=refill)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print_stack(stack)
    return layout, top, stack
