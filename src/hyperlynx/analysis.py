"""Checks of `layz hyp` run folders against a design's limits: DC drop per rail, eye opening,
crosstalk noise, insertion and return loss. Each returns rows (dicts), prints them as a table and
writes them as CSV; the limits are the design's (its flow.py), nothing here knows net names.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from layz.hyperlynx import plots


def _table(title: str, rows: list[dict], out: Path | None) -> list[dict]:
    if not rows:
        return rows
    keys = list(rows[0])
    fmt = lambda v: f"{v:.4g}" if isinstance(v, float) else str(v)  # noqa: E731
    width = {k: max(len(k), *(len(fmt(r[k])) for r in rows)) for k in keys}
    print(title)
    print("  " + "  ".join(k.ljust(width[k]) for k in keys))
    for r in rows:
        print("  " + "  ".join(fmt(r[k]).ljust(width[k]) for k in keys))
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows(rows)
    return rows


def dc_drop(run: Path, max_drop: float, out: Path | None = None) -> list[dict]:
    """Per supply net: VRM voltage, lowest pin voltage, drop (V and share of the VRM voltage),
    and the rise of its return; pass where drop + return rise stay under ``max_drop`` (share)."""
    ports = plots._rows(run / "ports.csv")
    vrms = json.loads((run / "vrms.json").read_text())
    nets = set(json.loads((run / "summary.json").read_text())["nets"])
    rows = []
    for v in vrms:
        if v["power_net"] not in nets:
            continue
        sup = [float(p["voltage_V"]) for p in ports if p["net"] == v["power_net"]]
        ret = [float(p["voltage_V"]) for p in ports if p["net"] == v["ref_net"]]
        drop, rise = v["voltage"] - min(sup), (max(ret) if ret else 0.0)
        share = (drop + rise) / v["voltage"]
        rows.append({"net": v["power_net"], "vrm_V": v["voltage"], "min_pin_V": min(sup), "drop_mV": drop * 1e3,
                     "return": v["ref_net"], "return_rise_mV": rise * 1e3, "total_pct": share * 100,
                     "limit_pct": max_drop * 100, "pass": share <= max_drop})
    return _table(f"DC drop ({run.name})", rows, out)


def _at(run: Path, at: str | None) -> list[dict]:
    """The run's (differential) waveforms, only those whose name contains ``at`` if given."""
    return [w for w in plots._diff_waves(run) if at is None or at in w["name"]]


def eyes(runs: list[Path], min_height: float, min_width_ui: float, out: Path | None = None,
         at: str | None = None) -> list[dict]:
    """Eye height, width and 20-80 % rise and fall times of each eye run's waveforms (those naming ``at``, e.g. the receiver),
    against the limits (V, share of a UI)."""
    rows = []
    for run in runs:
        si = json.loads((run / "si.json").read_text())
        if si.get("mode") != "eye":
            continue
        for w in _at(run, at):
            t, v = plots.wave(run / w["file"])
            ui = plots.run_ui(run, t, v)
            e = plots.eye(t, v, ui)
            hgt, wid = e["height"], e["width"]
            rows.append({"run": run.name, "wave": w["name"], "height_mV": hgt * 1e3, "width_ns": wid * 1e9,
                         "width_ui": wid / ui, "rise_ps": e["rise"] * 1e12, "fall_ps": e["fall"] * 1e12,
                         "pass": bool(hgt >= min_height and wid / ui >= min_width_ui)})
    return _table(f"Eyes (limits: height >= {min_height * 1e3:.0f} mV, width >= {min_width_ui:.2f} UI)", rows, out)


def crosstalk(run: Path, max_noise: float, out: Path | None = None, at: str | None = None) -> list[dict]:
    """Peak-to-peak and rms noise at each differential pair (those naming ``at``) of a crosstalk
    run, against the limit (V p-p)."""
    rows = []
    for w in _at(run, at):
        t, v = plots.wave(run / w["file"])
        k = t > t[0] + 0.1 * (t[-1] - t[0])  # after the start-up
        rows.append({"wave": w["name"], "noise_pp_mV": float(np.ptp(v[k])) * 1e3,
                     "noise_rms_mV": float(v[k].std()) * 1e3, "limit_pp_mV": max_noise * 1e3,
                     "pass": bool(np.ptp(v[k]) <= max_noise)})
    return _table(f"Crosstalk ({run.name}, limit {max_noise * 1e3:.0f} mV p-p)", rows, out)


def sparams(run: Path, at_hz: float, min_sdd21_db: float, max_sdd11_db: float, out: Path | None = None) -> list[dict]:
    """Mixed-mode insertion and return loss of a 4-port pair at ``at_hz`` (e.g. its Nyquist)."""
    info = json.loads((run / "sparam.json").read_text())
    f, S = plots.read_touchstone(run / info["file"])
    if S.shape[1] != 4:
        return []
    M = np.array([[1, -1, 0, 0], [0, 0, 1, -1], [1, 1, 0, 0], [0, 0, 1, 1]]) / np.sqrt(2)
    Smm = M @ S @ M.T
    k = int(np.argmin(abs(f - at_hz)))
    db = lambda x: float(20 * np.log10(abs(x) + 1e-30))  # noqa: E731
    sdd21, sdd11 = db(Smm[k, 1, 0]), db(Smm[k, 0, 0])
    rows = [{"pins": " ".join(info["pins"]), "f_MHz": f[k] / 1e6, "SDD21_dB": sdd21, "SDD11_dB": sdd11,
             "SCD21_dB": db(Smm[k, 3, 0]), "pass": bool(sdd21 >= min_sdd21_db and sdd11 <= max_sdd11_db)}]
    return _table(f"S-parameters at {at_hz / 1e6:.0f} MHz (limits: SDD21 >= {min_sdd21_db} dB, "
                  f"SDD11 <= {max_sdd11_db} dB)", rows, out)
