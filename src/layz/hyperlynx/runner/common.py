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

import hyperlynx as h  # noqa: F401  (HyperLynx's module; re-exported for the runners)


def say(*args) -> None:
    print(*args)
    sys.stdout.flush()


def load_job() -> dict:
    with open(sys.argv[1]) as f:
        return json.load(f)


def open_board(job: dict):
    """HLApplication with the board open; exits with HyperLynx's message if it won't open."""
    app = h.HLApplication()
    app.SetLicenseCollections(job.get("license_collection", "HyperLynx SI/PI"))
    if not app.LicensesWereAcquired():
        sys.exit(f"no HyperLynx license from collection {job.get('license_collection')!r}: "
                 "check MGLS_LICENSE_FILE and the collection's name (as in the GUI's licensing dialog)")
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
            out.append({"voltage": v.Voltage, "power_net": ph.PowerNet, "power_pins": [str(p) for p in ph.PowerPins],
                        "ref_net": ph.RefNet, "ref_pins": [str(p) for p in ph.RefPins]})
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
