"""Run HyperLynx analyses on a board: the Python API behind a flow's targets.

Each call makes a run folder, copies the board into it (the .hyp with its project files and the
models next to it: HyperLynx saves settings, VRMs and sinks back into those), writes job.json and
runs the matching runner with HyperLynx's own Python; results land in the run folder.

Every HyperLynx setting a run uses is an argument here, without a default: a setting left out
would silently be whatever the board's project file last saved. Names are layz's, in lower
case, for HyperLynx's enumerations (corner="typical" is hlSimCornerTypical).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from layz import log
from layz.hyperlynx import setup

RUNNERS = Path(__file__).parent / "runner"
# files of a board HyperLynx reads next to the .hyp: its project and the models it may use
PROJECT = (".bud", ".bbd", ".pjh", ".dcs", ".ffs")
MODELS = (".ibs", ".ebd", ".sp", ".spi", ".cir", ".inc", ".lib", ".pml", ".mod", ".ami")


def copy_board(board: Path, dest: Path, extra: list[Path] | tuple = ()) -> Path:
    """The .hyp, its project files and the model files beside it, into ``dest``."""
    board = Path(board)
    if board.suffix.lower() != ".hyp":
        raise SystemExit(f"{board}: give a .hyp (layz.gds2hyp.convert.hyp writes one from a GDS or .kicad_pcb)")
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


def _run(kind: str, board, out, options: dict, display: bool = False) -> Path:
    install, overlay, env = setup.prepare()
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    # model libraries the job names that aren't beside the board: from HyperLynx's own Libs/
    extra = []
    for g in options.get("aggressors", []) + list(options.get("models", {}).values()):
        if not (Path(board).parent / g["lib"]).exists() and (install / "hyperlynx" / "Libs" / g["lib"]).exists():
            extra.append(install / "hyperlynx" / "Libs" / g["lib"])
    copy = copy_board(Path(board), out / "board", extra)
    job = {"kind": kind, "board": str(copy), "out": str(out), "source": str(Path(board).resolve()), **options}
    (out / "job.json").write_text(json.dumps(job, indent=1))
    cmd = [str(setup.python(overlay)), "-u", str(RUNNERS / f"{kind}.py"), str(out / "job.json")]
    if display:  # BoardSim's SI engine reports to EZwave, which needs an X display
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            raise SystemExit("SI runs need an X display: install xvfb (xvfb-run), or run from a desktop session")
        cmd = [xvfb, "-a", *cmd]
    rc = log.run("hyperlynx", cmd, cwd=copy.parent, env=env, log=out / "run.log")
    if rc:
        raise SystemExit(f"HyperLynx {kind} run failed (exit {rc}); log: {out / 'run.log'}")
    return out


def info(board, out, *, license: str) -> Path:
    """Stackup, nets with their lengths, VRMs and modelled pins -> info.json.

    license   HyperLynx license collection, as in the GUI's licensing dialog ("HyperLynx SI/PI")
    """
    options = {k: v for k, v in locals().items() if k not in ("board", "out")}
    return _run("info", board, out, options)


def dc(board, out, *, license: str, nets: list[str], include_ref: bool, vrms: dict, sinks: dict, vrm_references: dict, sink_currents: dict, max_voltage_drop: float, max_current_density: float, max_via_current: float, return_from, return_vrm_type: str, return_sink_resistance: float) -> Path:
    """DC drop (PowerSI DC) of supply nets: pin voltages and currents, via currents, HyperLynx's
    report and PowerScope file, the loss map of each supply net.

    nets                    supply nets to solve
    include_ref             also solve their reference (return) nets
    vrms                    {net: {"voltage": V, "pins": [power pins], "ref": [reference pins]}}:
                            a VRM made where the board's project has none on that net; {} for none
    sinks                   {net: {"pins": [pins], "resistance": ohm}}: DC sinks put on those pins
                            where they have none (sink_currents then sets their current); {}
    vrm_references          {net: pin}: a reference pin for VRMs that have none (HyperLynx needs
                            one, also when the reference nets aren't solved); {} for none
    sink_currents           {net: A}: the net's total load, spread evenly over its sink pins (those
                            with a DC sink in the board's project); {} keeps the project's sinks
    max_voltage_drop        HyperLynx's constraint for its report: % of the VRM voltage
    max_current_density     A/m^2, for the report
    max_via_current         A per via, for the report
    return_from             None, or a supply run's ports.csv: solve the return nets as the supply
                            (HyperLynx maps supply nets only), with the measured currents as sinks
    return_vrm_type         "simple" or "advanced": the VRM made at the old reference pins
    return_sink_resistance  ohm across each moved sink (a sink is a current source; 0 is a short)
    """
    options = {k: v for k, v in locals().items() if k not in ("board", "out")}
    if return_from is not None:
        options["return_from"] = str(Path(return_from).resolve())
    return _run("dc", board, out, options)


def si(board, out, *, license: str, net: str, operation: str, simulator: str, corner: str, probe: str, stimulus_scope: str, bit_sequence: str, prbs_order: int, repetitions: int, frequency: float, duty_cycle: float, initial_state: str, stop_s, step_s, jitter: dict, lossy: bool, roughness: bool, trapezoid: bool, nonfunctional_pads: bool, crosstalk: bool, trace_coupling: dict, area_fill_coupling: dict, sparameter_coupling: dict, driver_states: dict, aggressors: list[dict], models: dict) -> Path:
    """Signal integrity (BoardSim): waveforms or an eye of a net, at full resolution.

    net                  the net to simulate (HyperLynx brings its differential partner along)
    operation            "standard" (waveforms) or "eye" (eye diagram)
    simulator            "auto", "hypersim", "adms" or "hspice"
    corner               IC model corner: "worst", "typical" or "best"
    probe                where the waveforms are taken: "pin", "die" or "model"
    stimulus_scope       "global" (the stimulus below for every driver) or "per_net_pin"
    bit_sequence         "edge", "oscillator", "prbs", "8b10b", "64b66b", "128b130b", "128b132b"
    prbs_order           PRBS 2^n - 1 (prbs only)
    repetitions          how often the sequence repeats
    frequency            Hz: the bit rate of a sequence; the clock frequency of "oscillator"
    duty_cycle           % (oscillator)
    initial_state        "low" or "high"
    stop_s, step_s       s, or None for HyperLynx's automatic choice
    jitter               s and Hz: {"Gaussian", "GaussianFreq", "Sine", "SineFreq",
                         "SineInitPhase", "Uniform", "UniformMean", "Distortion"}, all of them
    lossy, roughness, trapezoid, nonfunctional_pads   line models
    crosstalk            couple to neighbouring nets (HyperLynx needs lossy for it)
    trace_coupling       {"enabled", "method": "electrical" | "geometric", "threshold" (V,
                         electrical), "max_distance" (m, geometric), "min_segment" (m),
                         "horizontal_neighbours", "vertical_neighbours", "nonparallel", "self"}
    area_fill_coupling   {"enabled", "grid" (m), "search_distance" (m)}
    sparameter_coupling  {"connector", "connector_threshold", "package", "package_threshold",
                         "em", "em_threshold" (dB), "fmin", "fmax" (Hz)}
    driver_states        {pin: "low" | "high" | "switching"}, e.g. to hold a victim quiet
    aggressors           [{"driver": pin, "receivers": [pins], "lib", "device", "model"}]: these
                         pins get that IBIS model and the driver switches (a lib not beside the
                         board comes from HyperLynx's Libs/, e.g. modvsez.ibs, MODvsEZIBIS, "3")
    models               {pin: {"lib", "device", "model", "io": "output" | "input"}}: the net's own
                         pins' models where the board's project has none (an output switches)
    """
    options = {k: v for k, v in locals().items() if k not in ("board", "out")}
    return _run("si", board, out, options, display=True)


def sparam(board, out, *, license: str, pins: list[str], fmin: float, fmax: float, sweep: str, steps: int, steps_per_decade: int, tolerance: str, reference_impedance: float, lossy: bool, roughness: bool, trapezoid: bool, nonfunctional_pads: bool) -> Path:
    """S-parameters between pins, as Touchstone.

    pins                 the ports, in order
    fmin, fmax           Hz
    sweep                "linear", "log" or "adaptive"
    steps                points of a linear sweep
    steps_per_decade     points per decade of a log sweep
    tolerance            adaptive sweep: "low", "medium" or "high"
    reference_impedance  ohm
    lossy, roughness, trapezoid, nonfunctional_pads   line models
    """
    options = {k: v for k, v in locals().items() if k not in ("board", "out")}
    return _run("sparam", board, out, options)
