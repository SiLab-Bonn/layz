"""`layz run`: a design's flow, its @target functions run in order.

    layz run --design designs/ivtx_rdl            every target, in the file's order
    layz run --design ivtx_rdl drc lvs            some, by name (a name: designs/NAME)
    layz run --design ivtx_rdl --list             the targets, with their docstrings
    layz run --flow path/to/flow.py               a flow file elsewhere (default: ./flow.py)

A design's flow.py defines each step as a function without arguments or return value,
decorated with ``@target``; the function names its own inputs and outputs and does its work by
calling layz's Python API, one module per tool, each the same way: ``run`` runs the tool into
a folder with every option given, ``analysis`` checks the results against limits (a table,
printed and written as CSV), ``plots`` plots them in layz.plotstyle:

    layz.drc.run, layz.lvs.run                    design rules, connectivity vs the schematic
    layz.gds2hyp                                  the board for HyperLynx
    layz.pex.run / analysis / plots               capacitance matrix (FasterCap)
    layz.field.run / plots                        E-field and potential of a pex run
    layz.hyperlynx.run / analysis / plots         DC drop, SI, crosstalk, S-parameters

    from layz.flow import target
    from layz.hyperlynx import run

    @target
    def dc():
        \"\"\"DC drop of the 3 V rails.\"\"\"
        run.dc(BOARD, RESULTS / "dc", nets=["/3V_1", "/3V_2"], ...)

The targets run in order, and the run stops at the first that fails (--keep-going: run the rest
anyway, and fail at the end).
"""

from __future__ import annotations

import importlib.util
import sys
import time
from collections.abc import Callable
from pathlib import Path

TARGETS: dict[str, Callable[[], None]] = {}


def target(function: Callable[[], None]) -> Callable[[], None]:
    """Register ``function`` as a target, by its name."""
    if function.__code__.co_argcount or function.__code__.co_kwonlyargcount:
        raise TypeError(f"target {function.__name__} takes arguments: a target takes none")
    TARGETS[function.__name__] = function
    return function


def load(flow: Path) -> dict[str, Callable[[], None]]:
    """Import a flow file (its targets register themselves) and return its targets in order."""
    TARGETS.clear()
    spec = importlib.util.spec_from_file_location(f"layz_flow_{flow.parent.name}", flow)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not TARGETS:
        raise SystemExit(f"{flow}: no @target functions")
    return dict(TARGETS)


def describe(targets: dict[str, Callable[[], None]]) -> str:
    import textwrap

    width = max(len(n) for n in targets)
    lines = []
    for name, fn in targets.items():
        first = " ".join((fn.__doc__ or "").strip().split("\n\n")[0].split())  # its first paragraph
        text = textwrap.wrap(first, 96 - width) or [""]
        lines.append(f"  {name:<{width}}  {text[0]}")
        lines += [f"  {'':<{width}}  {t}" for t in text[1:]]
    return "\n".join(lines)


def run_targets(targets: dict[str, Callable[[], None]], names: list[str], keep_going: bool = False) -> list[str]:
    """Run ``names`` (all when empty) in order; the names of those that failed."""
    names = names or list(targets)
    unknown = [n for n in names if n not in targets]
    if unknown:
        raise SystemExit(f"unknown target(s) {', '.join(unknown)}; targets:\n{describe(targets)}")
    failed = []
    for name in names:
        start = time.monotonic()
        print(f"== {name}", flush=True)
        try:
            targets[name]()
        except (Exception, SystemExit) as e:  # a target stops with SystemExit or any error
            failed.append(name)
            print(f"== {name} FAILED after {time.monotonic() - start:.0f} s: {e}", flush=True)
            if not keep_going:
                break
            continue
        print(f"== {name} done in {time.monotonic() - start:.0f} s", flush=True)
    return failed


REPO = Path(__file__).resolve().parents[1]  # the repo layz runs from (editable install)


def find_flow(design: str | None, flow: Path | None) -> Path:
    """--flow FILE, --design DIR (a folder with flow.py, or a name in designs/), else ./flow.py."""
    if flow:
        return flow
    if design:
        for p in (Path(design) / "flow.py", Path.cwd() / "designs" / design / "flow.py", REPO / "designs" / design / "flow.py"):
            if p.exists():
                return p
        raise SystemExit(f"no flow.py in {design} (nor designs/{design} here or in {REPO})")
    if Path("flow.py").exists():
        return Path("flow.py")
    known = sorted(p.parent.name for p in REPO.glob("designs/*/flow.py"))
    raise SystemExit("no ./flow.py: give --design DIR" + (f" ({', '.join(known)})" if known else "") + " or --flow FILE")


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="layz run", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("targets", nargs="*", help="target names (default: all, in order)")
    ap.add_argument("-d", "--design", help="the design's folder (with flow.py), or its name in designs/")
    ap.add_argument("-f", "--flow", type=Path, help="a flow file")
    ap.add_argument("-l", "--list", action="store_true", help="list the targets")
    ap.add_argument("-k", "--keep-going", action="store_true", help="run the other targets after one fails")
    a = ap.parse_args(argv)
    flow = find_flow(a.design, a.flow)
    found = load(flow)
    if a.list:
        print(f"targets of {flow}:\n{describe(found)}")
        return 0
    failed = run_targets(found, a.targets, a.keep_going)
    if failed:
        print(f"failed: {', '.join(failed)}")
    return 1 if failed else 0
