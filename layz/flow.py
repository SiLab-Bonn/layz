"""`layz run FLOW`: a design's flow, its @target functions run in order.

    layz run designs/ivtx_rdl                     the flow.py in that folder
    layz run designs/ivtx_rdl/flow.py             the same

A design's flow.py defines each step as a function without arguments or return value,
decorated with ``@target``; the function names its own inputs (layout, stack, schematic) and
outputs, and does its work by calling layz's Python API, one module per tool, each the same way:
``run`` runs the tool into a folder with every option given, ``analysis`` checks the results
against limits (a table, printed and written as CSV), ``plots`` plots them in layz.plotstyle:

    layz.drc.run / analysis                       design rules (gdscheck; KiCad's for boards)
    layz.lvs.run / analysis                       connectivity vs the schematic
    layz.gds2hyp                                  the board for HyperLynx
    layz.pex.run / analysis / plots               capacitance matrix (FasterCap)
    layz.field.run                                E-field and potential of a pex run
    layz.hyperlynx.run / analysis / plots         DC drop, SI, crosstalk, S-parameters

    from layz.flow import target
    from layz.hyperlynx import run

    @target
    def dc():
        \"\"\"DC drop of the 3 V rails.\"\"\"
        run.dc(BOARD, RESULTS / "dc", nets=["/3V_1", "/3V_2"], ...)

The targets run in file order; the run stops at the first that fails.
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


def run_targets(targets: dict[str, Callable[[], None]]) -> str | None:
    """Run every target in order; the name of the one that failed, if one did."""
    for name, function in targets.items():
        start = time.monotonic()
        print(f"== {name}", flush=True)
        try:
            function()
        except (Exception, SystemExit) as e:  # a target stops with SystemExit or any error
            print(f"== {name} FAILED after {time.monotonic() - start:.0f} s: {e}", flush=True)
            return name
        print(f"== {name} done in {time.monotonic() - start:.0f} s", flush=True)
    return None


def main(argv: list[str]) -> int:
    """`layz run FLOW`: FLOW is a flow.py, or the folder with it."""
    flow = Path(argv[0])
    if flow.is_dir():
        flow = flow / "flow.py"
    if not flow.is_file():
        raise SystemExit(f"no flow file {flow}")
    found = load(flow)
    print(f"{flow}: {', '.join(found)}", flush=True)
    failed = run_targets(found)
    return 1 if failed else 0
