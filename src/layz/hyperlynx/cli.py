"""`layz hyp`: run a design's HyperLynx flow targets by name.

    layz hyp -d ivtx_rdl                   list the targets of designs/ivtx_rdl/flow.py
    layz hyp -d ivtx_rdl setup dc si       run these targets, in this order
    layz hyp -d ivtx_rdl all               run every target, in file order
    layz hyp -f path/to/flow.py TARGET     a flow file elsewhere (default: ./flow.py)

A flow file defines its steps as @target functions (layz.hyperlynx.targets), usually setup,
info, dc, si and sparams; each takes its inputs, runs HyperLynx (layz.hyperlynx.run), checks the
results (layz.hyperlynx.analysis) and plots them (layz.hyperlynx.plots) into its own folder.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # the repo layz runs from (editable install)


def find_flow(design: str | None, flow: Path | None) -> Path:
    if flow:
        return flow
    if design:
        for base in (Path.cwd(), REPO):
            p = base / "designs" / design / "flow.py"
            if p.exists():
                return p
        raise SystemExit(f"no designs/{design}/flow.py here or in {REPO}")
    if Path("flow.py").exists():
        return Path("flow.py")
    known = sorted(p.parent.name for p in REPO.glob("designs/*/flow.py"))
    raise SystemExit("no ./flow.py: give -d DESIGN" + (f" ({', '.join(known)})" if known else "") + " or -f FLOW")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="layz hyp", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("targets", nargs="*", help="target names, or 'all' (none: list them)")
    ap.add_argument("-d", "--design", help="designs/DESIGN/flow.py")
    ap.add_argument("-f", "--flow", type=Path, help="a flow file")
    a = ap.parse_args(argv)

    from layz.hyperlynx import targets
    flow = find_flow(a.design, a.flow)
    found = targets.load(flow)
    if not a.targets:
        print(f"targets of {flow}:\n{targets.describe(found)}")
        return 0
    targets.run_targets(found, a.targets)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
