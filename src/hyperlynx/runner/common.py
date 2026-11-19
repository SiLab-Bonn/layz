"""Shared by the runners, which HyperLynx's own Python (3.11) executes: stdlib + hyperlynx only.

A runner is started as ``pythonHL -u runner/<name>.py JOB.json``. The job names the board (a
copy layz made in the run folder), the output folder and the analysis's options.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys

import hyperlynx as h


def say(*args) -> None:
    print(*args)
    sys.stdout.flush()


def load_job() -> dict:
    with open(sys.argv[1]) as f:
        return json.load(f)


# layz's names for HyperLynx's enumerations
ENUMS = {
    "operation": {"standard": h.hlSimOpStandard, "eye": h.hlSimOpEyeDiagram},
    "simulator": {"auto": h.hlSimTypeAuto, "hypersim": h.hlSimTypeHyperSim, "adms": h.hlSimTypeADMS, "hspice": h.hlSimTypeHSPICE},
    "corner": {"worst": h.hlSimCornerWorst, "typical": h.hlSimCornerTypical, "best": h.hlSimCornerBest},
    "probe": {"pin": h.hlSimProbeAtPin, "die": h.hlSimProbeAtDie, "model": h.hlSimProbeByModel},
    "stimulus_scope": {"global": h.hlStimScopeGlobal, "per_net_pin": h.hlStimScopePerNetPin},
    "bit_sequence": {"edge": h.hlBitSequenceEdge, "oscillator": h.hlBitSequenceOscillator, "prbs": h.hlBitSequencePBRS, "8b10b": h.hlBitSequence10B8B, "64b66b": h.hlBitSequence64B66B, "128b130b": h.hlBitSequence128B130B, "128b132b": h.hlBitSequence128B132B},
    "initial_state": {"low": h.hlStimInitStateLow, "high": h.hlStimInitStateHigh},
    "method": {"electrical": h.hlCrosstalkElectrical, "geometric": h.hlCrosstalkGeometric},
    "driver_state": {"low": h.hlDrvStateLow, "high": h.hlDrvStateHigh, "switching": h.hlDrvStateSwitching},
    "vrm_type": {"simple": h.hlVRMTypeSimple, "advanced": h.hlVRMTypeAdvanced},
    "sweep": {"linear": h.hlFreqSweepLinear, "log": h.hlFreqSweepLog, "adaptive": h.hlFreqSweepAdaptive},
    "tolerance": {"low": h.hlFreqSweepToleranceLow, "medium": h.hlFreqSweepToleranceMedium, "high": h.hlFreqSweepToleranceHigh},
}


def enum(kind: str, name: str) -> int:
    """HyperLynx's value for one of layz's names (ENUMS); exits naming the choices otherwise."""
    if name not in ENUMS[kind]:
        sys.exit(f"{kind} {name!r}: one of {', '.join(ENUMS[kind])}")
    return ENUMS[kind][name]


def open_board(job: dict):
    """HLApplication with the board open; exits with HyperLynx's message if it won't open."""
    app = h.HLApplication()
    app.SetLicenseCollections(job["license"])
    if not app.LicensesWereAcquired():
        sys.exit(f"no HyperLynx license from collection {job['license']!r}: check MGLS_LICENSE_FILE and the collection's name (as in the GUI's licensing dialog)")
    if not app.OpenFile(os.path.abspath(job["board"])):
        sys.exit(f"HyperLynx cannot open {job['board']}: {app.LastError or 'see bsw.log in the run folder'}")
    return app


def write_csv(path: str, header: list[str], rows) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_json(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=1)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def vrms(design) -> list[dict]:
    """Every VRM phase: voltage, power net/pins, reference net/pins."""
    out = []
    for v in design.VRMs:
        for ph in v.VRMPhases:
            out.append({"voltage": v.Voltage, "power_net": ph.PowerNet, "power_pins": [str(p) for p in ph.PowerPins], "ref_net": ph.RefNet, "ref_pins": [str(p) for p in ph.RefPins]})
    return out


def save_waves(result, outdir: str) -> list[str]:
    """Each waveform of a simulation result as HyperLynx's CSV (full resolution with the
    EZwave target, 1024 points with the oscilloscope)."""
    names = []
    for w in result.Waveforms:
        fn = safe_name(w.Name) + ".csv"
        if w.Save(os.path.join(outdir, fn)):
            names.append({"name": w.Name, "file": fn})
    return names
