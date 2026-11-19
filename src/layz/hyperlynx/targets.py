"""Targets of a design's HyperLynx flow: `layz hyp TARGET ...` runs them by name.

A design's flow.py defines each step as a function without arguments or return value, decorated
with ``@target``; the function names its own inputs and outputs (paths at the top of the file)
and does its work by calling layz.hyperlynx.run / plots. A target that needs another's output
calls it where the output is missing, in plain Python:

    from layz.hyperlynx import run, target

    @target
    def dc():
        \"\"\"DC drop of the 3 V rails.\"\"\"
        run.dc(BOARD, RESULTS / "dc", nets=["/3V_1", "/3V_2"])

`layz hyp` lists the targets with their docstrings; `layz hyp all` runs them in file order.
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
    width = max(len(n) for n in targets)
    lines = []
    for name, fn in targets.items():
        doc = (fn.__doc__ or "").strip().splitlines()
        lines.append(f"  {name:<{width}}  {doc[0] if doc else ''}")
    return "\n".join(lines)


def run_targets(targets: dict[str, Callable[[], None]], names: list[str]) -> None:
    if names == ["all"]:
        names = list(targets)
    unknown = [n for n in names if n not in targets]
    if unknown:
        raise SystemExit(f"unknown target(s) {', '.join(unknown)}; targets:\n{describe(targets)}")
    for name in names:
        start = time.monotonic()
        print(f"== {name}", flush=True)
        targets[name]()
        print(f"== {name} done in {time.monotonic() - start:.0f} s", flush=True)
