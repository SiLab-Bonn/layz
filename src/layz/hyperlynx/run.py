"""Run HyperLynx analyses on a board: the Python API behind `layz hyp info|dc|si|sparam`.

Each call makes a run folder, copies the board into it (the .hyp with its project files and the
models next to it: HyperLynx saves settings, VRMs and sinks back into those), writes job.json and
runs the matching runner with HyperLynx's own Python; results land in the run folder.

    from layz.hyperlynx import run
    run.dc("board.hyp", "runs/dc")
    run.dc("board.hyp", "runs/dc_return", return_from="runs/dc/ports.csv")
    run.si("board.hyp", "runs/eye", net="/D4_N", mode="eye", bitrate=160e6, jitter={"Gaussian": 1e-10})
    run.sparam("board.hyp", "runs/sp", pins=["V1.101", "V1.102", "VTX2.101", "VTX2.102"])
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from layz.hyperlynx import setup

RUNNERS = Path(__file__).parent / "runner"
# files of a board HyperLynx reads next to the .hyp: its project and the models it may use
PROJECT = (".bud", ".bbd", ".pjh", ".dcs", ".ffs")
MODELS = (".ibs", ".ebd", ".sp", ".spi", ".cir", ".inc", ".lib", ".pml", ".mod", ".ami")
STOCK_IBIS = "modvsez.ibs"  # HyperLynx's generic CMOS driver/receiver (Libs/), for aggressors


def copy_board(board: Path, dest: Path, extra: list[Path] | tuple = ()) -> Path:
    """The .hyp, its project files and the model files beside it, into ``dest``."""
    board = Path(board)
    if board.suffix.lower() != ".hyp":
        raise SystemExit(f"{board}: give a .hyp (layz gds2hyp writes one from a GDS or .kicad_pcb)")
    if not board.exists():
        raise SystemExit(f"{board} not found")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(board, dest / board.name)
    for f in board.parent.iterdir():
        if f.is_file() and ((f.stem == board.stem and f.suffix.lower() in PROJECT) or f.suffix.lower() in MODELS):
            shutil.copy2(f, dest / f.name)
    for f in extra:
        shutil.copy2(f, dest / Path(f).name)
    return dest / board.name


def _run(kind: str, board, out, options: dict, display: bool = False, quiet: bool = False) -> Path:
    install, overlay, env = setup.prepare(quiet=quiet)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    extra = []
    if options.get("aggressors"):
        extra.append(install / "hyperlynx" / "Libs" / STOCK_IBIS)
    copy = copy_board(Path(board), out / "board", extra)
    job = {"board": str(copy), "out": str(out), **options}
    job.setdefault("license_collection", "HyperLynx SI/PI")
    (out / "job.json").write_text(json.dumps({**job, "kind": kind, "source": str(Path(board).resolve())}, indent=1))
    cmd = [str(setup.python(overlay)), "-u", str(RUNNERS / f"{kind}.py"), str(out / "job.json")]
    if display:  # BoardSim's SI engine reports to EZwave, which needs an X display
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            raise SystemExit("SI runs need an X display: install xvfb (xvfb-run), or run from a desktop session")
        cmd = [xvfb, "-a", *cmd]
    log = (out / "run.log").open("w")
    proc = subprocess.Popen(cmd, cwd=copy.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    for line in proc.stdout:
        log.write(line)
        noise = line.startswith(("[INFO] ******", "[INFO] Opening", "[INFO] Opened", "[INFO] Closing")) or \
            "Model Builder: Ground node" in line or "Stackup Verifier" in line or line.startswith("[INFO] A .CSV") \
            or line.startswith("Path: ")
        if not quiet and not noise:
            sys.stdout.write(line)
    rc = proc.wait()
    log.close()
    if rc:
        raise SystemExit(f"HyperLynx {kind} run failed (exit {rc}); log: {out / 'run.log'}")
    return out


def info(board, out, **options) -> Path:
    return _run("info", board, out, options)


def dc(board, out, nets: list[str] | None = None, include_ref: bool = True, return_from=None) -> Path:
    opts = {"nets": nets or [], "include_ref": include_ref}
    if return_from:
        opts["return_from"] = str(Path(return_from).resolve())
    return _run("dc", board, out, opts)


def si(board, out, net: str, **options) -> Path:
    return _run("si", board, out, {"net": net, **options}, display=True)


def sparam(board, out, pins: list[str], **options) -> Path:
    return _run("sparam", board, out, {"pins": pins, **options})
