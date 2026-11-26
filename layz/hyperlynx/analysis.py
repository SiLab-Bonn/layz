"""Checks of HyperLynx run folders (layz.hyperlynx.run) against a design's limits: DC drop per rail, eye opening,
crosstalk noise, insertion and return loss. Each returns rows (dicts), prints them as a table and
writes them as CSV; the limits are the design's (its flow.py), nothing here knows net names.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from layz.hyperlynx import plots
from layz.table import table


def dc_drop(run: Path, *, out: Path | None) -> list[dict]:
    """Per supply net: VRM voltage, the current its sinks draw, lowest pin voltage, drop, and the
    rise of its return."""
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
        pins = set(v["power_pins"])
        current = sum(abs(float(p["current_A"])) for p in ports if p["net"] == v["power_net"] and p["pin"] not in pins)
        rows.append({"net": v["power_net"], "vrm_V": v["voltage"], "current_A": current, "min_pin_V": min(sup), "drop_mV": drop * 1e3, "return": v["ref_net"], "return_rise_mV": rise * 1e3})
    return table(f"DC drop ({run.name})", rows, out)


def net_density(run: Path, nets: set[str]) -> dict[str, np.ndarray]:
    """The current density (A/m²) of each cell of a DC run's loss map, per net: every cell goes to
    the net whose copper (the board's .hyp) is nearest on that layer."""
    from layz.hyperlynx import copper

    cu = copper.read(next((run / "board").glob("*.hyp")), nets)
    names = sorted(cu)
    out: dict[str, list] = {n: [] for n in names}
    for lay, (J, _, ext) in plots.current_density(run).items():
        k = np.isfinite(J)
        if not k.any():
            continue
        ny, nx = J.shape
        iy, ix = np.nonzero(k)
        x = (ext[0] + (ix + 0.5) * (ext[1] - ext[0]) / nx) / plots.IN  # mm -> inches, as the .hyp
        y = (ext[2] + (iy + 0.5) * (ext[3] - ext[2]) / ny) / plots.IN
        owner = copper.assign(cu, lay, x, y)
        for j, n in enumerate(names):
            out[n].append(J[k][owner == j])
    return {n: np.concatenate(v) if v else np.array([]) for n, v in out.items()}


def connectivity(hyp: Path, *, tolerance_m: float, nets: list[str] | None, out: Path | None) -> list[dict]:
    """Pins their net's copper doesn't reach (farther than ``tolerance_m`` from it on every layer),
    per net with copper (``nets``: only these), and the copper that belongs to no net (KiCad's
    EmptyNet...). Needs no HyperLynx: it reads the board's .hyp."""
    import shapely

    from layz.hyperlynx import copper

    cu = copper.read(hyp)
    rows = []
    for net, ps in sorted(copper.pins(hyp).items()):
        if (nets is not None and net not in nets) or net not in cu:
            continue
        g = shapely.union_all([x for x in cu[net].values() if not x.is_empty])
        far = [(r, g.distance(shapely.Point(x, y)) * 25.4e-3) for r, x, y in ps]
        far = [(r, d) for r, d in far if d > tolerance_m]
        if far:
            rows.append({"net": net, "pins": len(ps), "unconnected": len(far), "which": " ".join(f"{r}({d * 1e3:.1f}mm)" for r, d in far)})
    unassigned = [n for n in cu if n.startswith("EmptyNet")]
    area = sum(g.area for n in unassigned for g in cu[n].values()) * 645.16
    return table(f"Connectivity ({Path(hyp).name}): pins farther than {tolerance_m * 1e6:.0f} um from their net's copper; {len(unassigned)} pieces of copper ({area:.1f} mm²) on no net", rows, out)


def dc_table(supply: Path, ret: Path | None, *, out: Path | None) -> list[dict]:
    """Per net of a DC run, as in a design review: resistance from the VRM to the net's sink pins
    (min, max; HyperLynx's resistance matrix), voltage drop over those pins (min, max: the VRM
    voltage less the pin's on a supply net, the rise on a return net), and current density (the
    median of the net's copper, and its maximum). Supply nets and nets without a return come from
    ``supply``, return nets' current density from ``ret`` (the return run)."""
    ports = plots._rows(supply / "ports.csv")
    vrms = json.loads((supply / "vrms.json").read_text())
    solved = set(json.loads((supply / "summary.json").read_text())["nets"])
    volts = {v["power_net"]: v["voltage"] for v in vrms}
    refs = {v["ref_net"] for v in vrms if v["power_net"] in solved and v["ref_net"]}
    vrm_pins = {p for v in vrms for p in v["power_pins"] + v["ref_pins"]}
    res = plots._rows(supply / "resistance.csv") if (supply / "resistance.csv").exists() else []
    pin_net = {p["pin"]: p["net"] for p in ports} | {p: v["power_net"] for v in vrms for p in v["power_pins"]} | {p: v["ref_net"] for v in vrms for p in v["ref_pins"]}
    res = [dict(x, net=pin_net.get(x["sink"], x["net"])) for x in res if pin_net.get(x["source"]) == pin_net.get(x["sink"])]  # same-net pairs
    dens = net_density(supply, solved)
    if ret is not None:
        dens.update({n: j for n, j in net_density(ret, refs).items() if n in refs})
    rows = []
    for net in [n for n in sorted(solved)] + sorted(refs):
        pins = [p for p in ports if p["net"] == net and p["pin"] not in vrm_pins and abs(float(p["current_A"])) > 0]
        v = np.array([float(p["voltage_V"]) for p in pins])
        drop = (volts[net] - v) if net in volts else v  # a return: its rise
        r = np.array([float(x["resistance_ohm"]) for x in res if x["net"] == net])
        j = dens.get(net, np.array([]))
        rows.append({"net": net, "kind": "return" if net in refs else "supply", "sinks": len(pins), "current_A": float(sum(abs(float(p["current_A"])) for p in pins)), "R_min_mohm": float(r.min()) * 1e3 if r.size else np.nan, "R_max_mohm": float(r.max()) * 1e3 if r.size else np.nan, "drop_min_V": float(drop.min()) if drop.size else np.nan, "drop_max_V": float(drop.max()) if drop.size else np.nan, "J_median_A_mm2": float(np.median(j)) / 1e6 if j.size else np.nan, "J_max_A_mm2": float(j.max()) / 1e6 if j.size else np.nan})
    return table(f"DC per net ({supply.name}{' + ' + ret.name if ret is not None else ''})", rows, out)


def current_density(runs: list[Path], *, max_density: float, out: Path | None) -> list[dict]:
    """Per DC run (side: the supply run, the return run) and layer: the highest current density
    (A/mm²) in the copper, where, the drop per length it causes (mV/mm), and the share of the
    copper above ``max_density`` (A/m²); pass where nothing is above it. HyperLynx's own maxima
    are in the title, as a cross-check."""
    rows, own = [], []
    for run in runs:
        hl = json.loads((run / "summary.json").read_text())["max_current_density"]
        own.append(f"{run.name} {hl['value'] / 1e6:.0f} A/mm² on {hl['layer']}")
        rows += _density_rows(run, max_density)
    return table(f"Current density (HyperLynx's own maxima: {'; '.join(own)})", rows, out)


def _density_rows(run: Path, max_density: float) -> list[dict]:
    rows = []
    for lay, (J, rho, ext) in plots.current_density(run).items():
        if not np.isfinite(J).any():
            continue
        k = np.unravel_index(np.nanargmax(J), J.shape)
        rows.append({"side": run.name, "layer": lay, "max_A_per_mm2": float(np.nanmax(J)) / 1e6, "x_mm": ext[0] + (k[1] + 0.5) * (ext[1] - ext[0]) / J.shape[1], "y_mm": ext[2] + (k[0] + 0.5) * (ext[3] - ext[2]) / J.shape[0], "max_drop_mV_per_mm": rho * float(np.nanmax(J)), "over_limit_pct": 100 * float(np.nanmean(J[np.isfinite(J)] > max_density)), "limit_A_per_mm2": max_density / 1e6, "pass": bool(np.nanmax(J) <= max_density)})
    return rows


def pins(runs: list[Path], *, out: Path | None) -> list[dict]:
    """Every pin of DC runs (side: the supply run, the return run): its net, current and voltage."""
    rows = [{"side": run.name, "pin": p["pin"], "net": p["net"], "current_A": float(p["current_A"]), "voltage_V": float(p["voltage_V"])} for run in runs for p in plots._rows(run / "ports.csv")]
    return table(f"Pins ({', '.join(r.name for r in runs)})", rows, out, quiet=True)


def resistance(run: Path, *, out: Path | None) -> list[dict]:
    """HyperLynx's resistance from each VRM pin to each sink pin of its net (mohm)."""
    rows = [{"net": x["net"], "source": x["source"], "sink": x["sink"], "R_mohm": float(x["resistance_ohm"]) * 1e3} for x in plots._rows(run / "resistance.csv")] if (run / "resistance.csv").exists() else []
    return table(f"Resistance VRM -> sink ({run.name})", rows, out, quiet=True)


def _at(run: Path, at: str | None) -> list[dict]:
    """The run's (differential) waveforms, only those whose name contains ``at`` if given."""
    return [w for w in plots._diff_waves(run) if at is None or at in w["name"]]


def eyes(runs: list[Path], *, min_height: float, min_width_ui: float, at: str | None, skip_ui: float, centre_window: float, edge_levels: tuple[float, float], out: Path | None) -> list[dict]:
    """Eye height, width, rise and fall times of each eye run's waveforms (those naming ``at``,
    e.g. the receiver; None: all), against the limits (V, share of a UI). skip_ui,
    centre_window, edge_levels: how the eye is measured (plots.eye)."""
    rows = []
    for run in runs:
        si = json.loads((run / "si.json").read_text())
        if si.get("mode") != "eye":
            continue
        for w in _at(run, at):
            t, v = plots.wave(run / w["file"])
            ui = plots.run_ui(run, t, v)
            e = plots.eye(t, v, ui, skip_ui=skip_ui, centre_window=centre_window, edge_levels=edge_levels)
            hgt, wid = e["height"], e["width"]
            rows.append({"run": run.name, "wave": w["name"], "height_mV": hgt * 1e3, "width_ns": wid * 1e9, "width_ui": wid / ui, "rise_ps": e["rise"] * 1e12, "fall_ps": e["fall"] * 1e12, "pass": bool(hgt >= min_height and wid / ui >= min_width_ui)})
    return table(f"Eyes (limits: height >= {min_height * 1e3:.0f} mV, width >= {min_width_ui:.2f} UI)", rows, out)


def crosstalk(run: Path, *, max_noise: float, at: str | None, settle: float, out: Path | None) -> list[dict]:
    """Peak-to-peak and rms noise at each differential pair (those naming ``at``; None: all) of
    a crosstalk run, after its first ``settle`` share of time, against the limit (V p-p)."""
    rows = []
    for w in _at(run, at):
        t, v = plots.wave(run / w["file"])
        k = t > t[0] + settle * (t[-1] - t[0])  # after the start-up
        rows.append({"wave": w["name"], "noise_pp_mV": float(np.ptp(v[k])) * 1e3, "noise_rms_mV": float(v[k].std()) * 1e3, "limit_pp_mV": max_noise * 1e3, "pass": bool(np.ptp(v[k]) <= max_noise)})
    return table(f"Crosstalk ({run.name}, limit {max_noise * 1e3:.0f} mV p-p)", rows, out)


def sparams(run: Path, *, at_hz: float, min_sdd21_db: float, max_sdd11_db: float, out: Path | None) -> list[dict]:
    """Mixed-mode insertion and return loss of a 4-port pair at ``at_hz`` (e.g. its Nyquist)."""
    info = json.loads((run / "sparam.json").read_text())
    f, S = plots.read_touchstone(run / info["file"])
    if S.shape[1] != 4:
        return []
    M = np.array([[1, -1, 0, 0], [0, 0, 1, -1], [1, 1, 0, 0], [0, 0, 1, 1]]) / np.sqrt(2)
    Smm = M @ S @ M.T
    k = int(np.argmin(abs(f - at_hz)))
    db = lambda x: float(20 * np.log10(abs(x) + 1e-30))
    sdd21, sdd11 = db(Smm[k, 1, 0]), db(Smm[k, 0, 0])
    rows = [{"pins": " ".join(info["pins"]), "f_MHz": f[k] / 1e6, "SDD21_dB": sdd21, "SDD11_dB": sdd11, "SCD21_dB": db(Smm[k, 3, 0]), "pass": bool(sdd21 >= min_sdd21_db and sdd11 <= max_sdd11_db)}]
    return table(f"S-parameters at {at_hz / 1e6:.0f} MHz (limits: SDD21 >= {min_sdd21_db} dB, SDD11 <= {max_sdd11_db} dB)", rows, out)


def tdr(run: Path, *, rise_ps: float, er_eff: float, out: Path | None) -> list[dict]:
    """Per port and pair of an S-parameter run (plots.tdr): the reference impedance, the lowest
    and highest impedance seen and where (distance), and the impedance at the far end."""
    r = plots.tdr(run, rise_ps=rise_ps, er_eff=er_eff)
    rows = []
    for label, t in r["traces"].items():
        inside = t["t"] <= 2 * r["delay_s"]  # the line itself, up to its round trip
        z, d = t["Z"][inside], t["d"][inside]
        lo, hi = int(np.argmin(z)), int(np.argmax(z))
        rows.append({"trace": label, "Z0_ohm": t["z0"], "Z_min_ohm": float(z[lo]), "at_min_mm": float(d[lo] * 1e3), "Z_max_ohm": float(z[hi]), "at_max_mm": float(d[hi] * 1e3), "Z_end_ohm": float(t["Z"][-1])})
    return table(f"TDR ({run.name}; {r['rise_ps']:.0f} ps step, one-way delay {r['delay_s'] * 1e9:.2f} ns)", rows, out)
