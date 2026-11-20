"""`layz run FLOW`: a design's flow, its @target functions run in order.

    layz run designs/ivtx_rdl                     the flow.py in that folder, every step
    layz run designs/ivtx_rdl/flow.py             the same
    layz run designs/ivtx_rdl drc lvs             only these steps (and setup, first: the inputs);
                                                  the others keep their last run's results

At the end, the run's page is written as a file, results/NAME/report.html: open it in a browser
as it is (`layz web` shows the same page served).

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

The targets run in file order; the run stops at the first that fails. A target that can't run
with the inputs it has raises ``Skip(why)``: noted as skipped, and the run goes on.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from layz import log

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


INPUTS = ("LAYOUT", "STACK", "SCHEMATIC")  # what a flow's setup names as its inputs, for the viewer


class Skip(Exception):
    """Raised by a target that can't run with these inputs (``raise Skip("no KiCad board")``):
    the run notes it as skipped, and goes on."""  # what a flow's setup names, for the viewer


def run_targets(targets: dict[str, Callable[[], None]], record: Path | None = None, only: set[str] | None = None) -> str | None:
    """Run every target in order (with ``only``, those of them); the name of the one that failed,
    if one did. With ``record``, write the run there as it goes (run.json: the targets with status
    and time, the inputs setup named), which `layz web` shows; targets not run keep what the last
    run recorded of them."""
    last = {}
    if only is not None and record is not None and record.exists():
        last = {t["name"]: t for t in json.loads(record.read_text()).get("targets", [])}
    run = {"flow": "", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "inputs": {}, "targets": [last.get(n) if only is not None and n not in only and n in last else {"name": n, "doc": " ".join((f.__doc__ or "").split()), "status": "pending", "seconds": None, "error": None} for n, f in targets.items()]}
    if record is not None:
        run["flow"] = str(next(iter(targets.values())).__globals__.get("__file__", ""))
    if record is not None:  # recorded from the start: every step pending, then each as it ends
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(run, indent=1))
    failed = None
    for i, (name, function) in enumerate(targets.items()):
        if only is not None and name not in only:
            continue
        entry = run["targets"][i]
        start = time.monotonic()
        first = log.FILE["lines"]
        log.info("flow", f"[{i + 1}/{len(targets)}] {name}: {entry['doc'].split('. ')[0]}")
        log.COUNTS.update(INFO=0, WARN=0, ERROR=0, fail=0)
        log.STEP = []
        try:
            with log.capture("layz"):
                function()
            # it ran: ok, or with warnings (its tools warned), or with errors (checks failed,
            # its tools reported errors); a crash is "failed"
            entry["errors"], entry["warnings"] = log.COUNTS["fail"] + log.COUNTS["ERROR"], log.COUNTS["WARN"]
            entry["status"] = "errors" if entry["errors"] else "warnings" if entry["warnings"] else "ok"
        except Skip as e:
            entry["status"], entry["error"] = "skipped", str(e)
        except (Exception, SystemExit) as e:  # a target stops with SystemExit or any error
            entry["status"], entry["error"] = "failed", str(e) or type(e).__name__
            failed = name
        entry["seconds"] = round(time.monotonic() - start, 2)
        if failed:
            for line in entry["error"].splitlines():
                log.error("flow", line)
            log.error("flow", f"[{i + 1}/{len(targets)}] {name}: failed after {entry['seconds']:.0f} s")
        elif entry["status"] == "skipped":
            log.warn("flow", f"[{i + 1}/{len(targets)}] {name}: skipped: {entry['error']}")
        else:
            say = log.warn if entry["status"] != "ok" else log.info
            say("flow", f"[{i + 1}/{len(targets)}] {name}: {entry['status']} in {entry['seconds']:.0f} s" + (f" ({entry['errors']} errors, {entry['warnings']} warnings)" if entry["status"] != "ok" else ""))
        entry["log"] = [first, log.FILE["lines"]]  # its lines in run.log
        if record is not None:  # and its own log, among the step's files
            folder = record.parent / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "log.txt").write_text("\n".join(log.STEP) + "\n")
        log.STEP = None
        if record is not None:
            g = function.__globals__
            run["inputs"] = {k.lower(): str(g[k]) for k in INPUTS if g.get(k) is not None}
            if g.get("BOARD") is not None:  # the board the flow makes for HyperLynx: an output
                run["board"] = str(g["BOARD"])
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps(run, indent=1))
        if failed:
            break
    return failed


def main(argv: list[str]) -> int:
    """`layz run FLOW [TARGET ...]`: FLOW is a flow.py, or the folder with it; TARGETs, the steps to
    run (setup, the first, always), else all. The run is recorded in results/<the flow's
    folder>/run.json, and written as a page, report.html, next to it."""
    flow = Path(argv[0])
    if flow.is_dir():
        flow = flow / "flow.py"
    if not flow.is_file():
        raise SystemExit(f"no flow file {flow}")
    found = load(flow)
    log.info("flow", f"{flow}: {len(found)} targets: {', '.join(found)}")
    only = None
    if argv[1:]:
        unknown = [n for n in argv[1:] if n not in found]
        if unknown:
            raise SystemExit(f"{flow}: no target {', '.join(unknown)} (its targets: {', '.join(found)})")
        only = {next(iter(found)), *argv[1:]}  # the first (setup: the inputs) always
        log.info("flow", f"running {', '.join(n for n in found if n in only)}; the others keep their last results")
    record = Path("results") / flow.resolve().parent.name / "run.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    with open(record.parent / "run.log", "w") as f:
        log.FILE.update(file=f, lines=0)
        try:
            failed = run_targets(found, record, only)
        finally:
            log.FILE.update(file=None, lines=0)
    run = json.loads(record.read_text()) if record.exists() else {"targets": []}
    ran = [t for t in run["targets"] if only is None or t["name"] in only]
    tally = {st: [t["name"] for t in ran if t["status"] == st] for st in ("errors", "warnings")}
    summary = f"stopped at {failed}" if failed else "every step ran" + "".join(f"; {', '.join(n)} with {st}" for st, n in tally.items() if n)
    (log.error if failed else log.warn if any(tally.values()) else log.info)("flow", f"{flow.resolve().parent.name}: {summary}; results in {record.parent}")
    try:  # the run as a page to open from the file manager, without `layz web`
        from layz.web import report

        log.info("flow", f"report: {report.write(record.parent.name).resolve()}")
    except Exception as e:  # noqa: BLE001 (the run is done; only its page is missing)
        log.warn("flow", f"no report page: {e}")
    return 1 if failed else 0
