"""Plots of `layz hyp` run folders, in layz.plotstyle (FRIDA's style). Each folder's job.json
says what it holds; nothing here knows a design's net names.

    dc       pin voltages (supply nets | their reference nets), via currents, loss map
             (with a return run among the folders: supply | return side by side)
    si       waveforms at each differential pin pair, the eye (eye mode), crosstalk (with
             aggressors: their waveforms over the victim's noise); several SI folders overlay
    sparam   |S| of each port pair; a 4-port P/N pair also as mixed-mode SDD21, SDD11, SCD21
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm, Normalize

from layz.plotstyle import CURVE_COLORS, DENSITY_COLOR_MAP, GRID_MAJOR_COLOR, PLOT_STYLE, SPINE_COLOR, save_figure, style_grid, style_info_box

MM, IN = 1e3, 25.4


def _rows(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def wave(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """A HyperLynx/EZwave waveform CSV: (time s, value)."""
    t, v = [], []
    for line in Path(path).read_text().splitlines():
        p = line.split(",")
        if len(p) == 2:
            try:
                t.append(float(p[0]))
                v.append(float(p[1]))
            except ValueError:
                pass
    return np.array(t), np.array(v)


def load_thermal(path: Path):
    """HyperLynx's thermal export: per-layer grids of watts per cell (inches) -> (grids, cell mm²,
    extent mm)."""
    lines = Path(path).read_text().splitlines()
    hdr = {k.strip(): v.strip() for k, v in (l.split("=", 1) for l in lines[:12] if "=" in l)}
    nx, ny = int(hdr["N_x"]), int(hdr["N_y"])
    x0, y0, dx, dy = (float(hdr[k]) for k in ("X_offset", "Y_offset", "Dx", "Dy"))
    names = [l.split(",")[1].strip().strip('"') for l in lines if l.startswith("Layer:")]
    grids, cur = {}, None
    for l in lines:
        if l.startswith("Layer = "):
            cur = names[int(l.split("=")[1])]
            grids[cur] = np.full((ny, nx), np.nan)
        elif l.startswith("Row ") and cur is not None:
            k, vals = l[4:].split(":", 1)
            a = np.array([float(t) if t else np.nan for t in vals.split(",")[1 : nx + 1]])
            grids[cur][int(k), : len(a)] = a
    return grids, dx * dy * IN * IN, [x0 * IN, (x0 + nx * dx) * IN, y0 * IN, (y0 + ny * dy) * IN]


def current_density(run: Path) -> dict[str, tuple[np.ndarray, float, list[float]]]:
    """Per layer of a DC run: (current density in A/m² per grid cell, the layer's resistivity in
    ohm·m, extent in mm), from HyperLynx's loss export.

    That export holds, per cell, the loss density at the cell's sample point times the cell's
    copper volume: P = J²·ρ·t·A (its total runs some 20 % above I·ΔV at 180 µm cells, as cells at
    copper edges count whole). So J = √(P / (ρ·t·A)), which reproduces the maximum current density
    HyperLynx reports itself; ρ·J is the voltage drop per length along the copper (V/m = mV/mm).
    t comes from the export's layer table, ρ from the board's STACKUP."""
    import re

    hyp = next((run / "board").glob("*.hyp"))
    rho = {m.group(2): float(m.group(1)) for m in re.finditer(r'\(SIGNAL [^)]*?C=([-\d.eE+]+) L="([^"]+)"', hyp.read_text())}
    out: dict[str, tuple[np.ndarray, float, list[float]]] = {}
    for f in sorted(run.glob("Thermal__*.txt")):
        lines = f.read_text().splitlines()
        thick = {l.split(",")[1].strip().strip('"'): float(l.split(",")[3]) * IN / MM for l in lines if l.startswith("Layer:")}
        grids, cell, ext = load_thermal(f)
        for lay, P in grids.items():
            J = np.sqrt(np.where(P > 0, P, np.nan) / (rho[lay] * thick[lay] * cell / MM**2))
            out[lay] = (np.fmax(out[lay][0], J) if lay in out else J, rho[lay], ext)
    return out


# ------------------------------------------------------------------------------------------ DC


def _sides(run: Path):
    """(supply nets, reference nets, {net: VRM voltage}) of a DC run."""
    vrms = json.loads((run / "vrms.json").read_text())
    nets = set(json.loads((run / "summary.json").read_text())["nets"])
    sup = {v["power_net"]: v["voltage"] for v in vrms if v["power_net"] in nets}
    ref = {v["ref_net"]: 0.0 for v in vrms if v["power_net"] in nets and v["ref_net"]}
    return sup, ref


def _loss(ports, volts: dict) -> float:
    return abs(sum(float(p["current_A"]) * (volts[p["net"]] - float(p["voltage_V"])) for p in ports if p["net"] in volts))


@mpl.rc_context(PLOT_STYLE)
def plot_dc(run: Path, out: Path, ret: Path | None = None) -> list[Path]:
    ports, vias = _rows(run / "ports.csv"), [c for c in _rows(run / "vias.csv") if c["x1"]]
    sup, ref = _sides(run)
    paths: list[Path] = []

    fig, axes = plt.subplots(2, 1, figsize=(12.8, 4.6), sharex=True)
    for ax, side, name in ((axes[0], sup, "Supply"), (axes[1], ref, "Return")):
        ax.scatter([float(c["x1"]) * MM for c in vias if c["net"] in side], [float(c["y1"]) * MM for c in vias if c["net"] in side], s=1, color=GRID_MAJOR_COLOR, zorder=1)
        pins = [p for p in ports if p["net"] in side and p["x"]]
        if not pins:
            ax.set_visible(False)
            continue
        v = np.array([float(p["voltage_V"]) for p in pins])
        cmap = DENSITY_COLOR_MAP.reversed() if name == "Supply" else DENSITY_COLOR_MAP  # worst bright
        sc = ax.scatter([float(p["x"]) * MM for p in pins], [float(p["y"]) * MM for p in pins], c=v * 1e3, cmap=cmap, s=22, edgecolors=SPINE_COLOR, linewidths=0.3, zorder=2)
        fig.colorbar(sc, ax=ax, label="Pin voltage (mV)")
        ax.set_aspect("equal")
        ax.set_ylabel("y (mm)")
        ax.set_title(f"{name} pins ({', '.join(sorted(side))}): {v.min() * 1e3:.1f} to {v.max() * 1e3:.1f} mV, loss {_loss(ports, side) * 1e3:.0f} mW (grey: vias)", fontsize=10)
    axes[-1].set_xlabel("x (mm)")
    paths += save_figure(fig, out / "dc_pin_voltage")

    cur = np.array([abs(float(c["current_A"])) for c in vias])
    if len(cur) and cur.max() > 0:
        norm = LogNorm(vmin=max(1e-6, cur[cur > 0].min()), vmax=cur.max())
        fig, axes = plt.subplots(2, 1, figsize=(12.8, 4.6), sharex=True)
        for ax, side, name in ((axes[0], sup, "supply"), (axes[1], ref, "return")):
            sel = sorted((k for k, c in enumerate(vias) if c["net"] in side), key=lambda k: cur[k])
            if not sel:
                ax.set_visible(False)
                continue
            sc = ax.scatter([float(vias[k]["x1"]) * MM for k in sel], [float(vias[k]["y1"]) * MM for k in sel], c=cur[sel], cmap=DENSITY_COLOR_MAP, norm=norm, s=5, linewidths=0)
            ax.set_aspect("equal")
            ax.set_ylabel("y (mm)")
            ax.set_title(f"Via current, {name}: {len(sel)} vias, max {cur[sel].max() * 1e3:.0f} mA", fontsize=10)
        axes[-1].set_xlabel("x (mm)")
        fig.colorbar(sc, ax=axes, label="Via current (A)")
        paths += save_figure(fig, out / "dc_via_current")

    maps = []
    for f in sorted(run.glob("Thermal__*.txt")):
        maps.append(("Supply", load_thermal(f), _loss(ports, sup)))
    if ret is not None:
        rports = _rows(ret / "ports.csv")
        for f in sorted(ret.glob("Thermal__*.txt")):
            maps.append(("Return", load_thermal(f), _loss(ports, ref)))
        del rports
    if maps:
        paths += _plot_loss(maps, out)
        paths += _plot_current([("Supply", current_density(run))] + ([("Return", current_density(ret))] if ret is not None else []), out)
    return paths


@mpl.rc_context(PLOT_STYLE)
def _plot_current(maps, out: Path) -> list[Path]:
    """Current density per layer (supply, return side by side), with the drop per mm it means."""
    layers = []
    for _, dens in maps:
        layers += [n for n, (J, _, _) in dens.items() if np.isfinite(J).any() and np.nanmax(J) > 1e-3 * max(np.nanmax(a) for a, _, _ in dens.values() if np.isfinite(a).any()) and n not in layers]
    vmax = max(np.nanmax(J) for _, dens in maps for n, (J, _, _) in dens.items() if n in layers) / MM**2
    norm = Normalize(vmin=0, vmax=vmax)  # linear: where the current crowds
    fig, axes = plt.subplots(len(layers), len(maps), figsize=(7.2 * len(maps), 1.25 * len(layers) + 1.0), sharex=True, sharey=True, squeeze=False)
    for j, (side, dens) in enumerate(maps):
        for i, lay in enumerate(layers):
            ax = axes[i, j]
            if lay not in dens or not np.isfinite(dens[lay][0]).any():
                ax.set_title(f"{side}, {lay}: no copper", fontsize=10)
                continue
            J, rho, ext = dens[lay]
            im = ax.imshow(J / MM**2, origin="lower", extent=ext, cmap=DENSITY_COLOR_MAP, norm=norm, aspect="equal", interpolation="nearest", rasterized=True)
            k = np.unravel_index(np.nanargmax(J), J.shape)
            x = ext[0] + (k[1] + 0.5) * (ext[1] - ext[0]) / J.shape[1]
            y = ext[2] + (k[0] + 0.5) * (ext[3] - ext[2]) / J.shape[0]
            ax.plot([x], [y], marker="o", markersize=6, markerfacecolor="none", markeredgecolor=SPINE_COLOR)
            ax.set_title(f"{side}, {lay}: max {np.nanmax(J) / MM**2:.0f} A/mm², {rho * np.nanmax(J):.2f} mV/mm, at ({x:.1f}, {y:.1f}) mm", fontsize=10)
            ax.set_xlabel("x (mm)" if i == len(layers) - 1 else "")
            ax.set_ylabel("y (mm)" if j == 0 else "")
    fig.colorbar(im, ax=axes, label="Current density (A/mm²); × ρ: drop per length")
    return list(save_figure(fig, out / "dc_current_density"))


@mpl.rc_context(PLOT_STYLE)
def _plot_loss(maps, out: Path) -> list[Path]:
    layers = []
    for _, (g, _, _), _ in maps:
        tot = sum(np.nansum(a) for a in g.values())
        layers += [n for n, a in g.items() if np.nansum(a) > 1e-3 * tot and n not in layers]
    vmax = max(np.nanmax(a / c) for _, (g, c, _), _ in maps for n, a in g.items() if n in layers)
    norm = LogNorm(vmin=vmax * 1e-4, vmax=vmax)
    fig, axes = plt.subplots(len(layers), len(maps), figsize=(7.2 * len(maps), 1.25 * len(layers) + 1.0), sharex=True, sharey=True, squeeze=False)
    for j, (side, (g, cell, ext), exact) in enumerate(maps):
        tot = sum(np.nansum(a) for a in g.values())
        empty = [n for n, a in g.items() if n not in layers]
        for i, lay in enumerate(layers):
            ax, a = axes[i, j], g.get(lay)
            if a is not None:
                im = ax.imshow(np.where(a > 0, a / cell, np.nan), origin="lower", extent=ext, cmap=DENSITY_COLOR_MAP, norm=norm, aspect="equal", interpolation="nearest", rasterized=True)
            note = f" (map total {tot * 1e3:.0f} mW, exact I·ΔV {exact * 1e3:.0f} mW)" if i == 0 else f" (no copper on {', '.join(empty)})" if i == len(layers) - 1 and empty else ""
            ax.set_title(f"{side}, {lay}: {np.nansum(a) * 1e3 if a is not None else 0:.0f} mW{note}", fontsize=10)
            ax.set_xlabel("x (mm)" if i == len(layers) - 1 else "")
            ax.set_ylabel("y (mm)" if j == 0 else "")
    fig.colorbar(im, ax=axes, label="Joule loss density (W/mm²)")
    return list(save_figure(fig, out / "dc_loss_map"))


# ------------------------------------------------------------------------------------------ SI


def _diff_waves(run: Path) -> list[dict]:
    si = json.loads((run / "si.json").read_text())
    waves = si.get("waves", [])
    diff = [w for w in waves if "," in w["name"]]
    return diff or waves


def unit_interval(t, v) -> tuple[float, float]:
    """(UI, a nominal crossing time) from the shortest run between crossings of a PRBS waveform."""
    zc = t[1:][np.diff(np.sign(v - 0.5 * (v.min() + v.max()))) != 0]
    gaps = np.diff(zc)
    return float(np.median(gaps[gaps < 1.25 * np.percentile(gaps, 5)])), float(zc[0])


def _edge_times(t, v, lo: float, hi: float, rising: bool, max_s: float) -> np.ndarray:
    """Times from ``lo`` to ``hi`` (rising) or ``hi`` to ``lo`` (falling) of each edge, by linear
    interpolation; edges that don't make it within ``max_s`` are left out."""
    a, b = (lo, hi) if rising else (hi, lo)
    sgn = 1 if rising else -1

    def cross(level):  # times v passes ``level`` in the edge's direction
        i = np.nonzero((sgn * (v[:-1] - level) < 0) & (sgn * (v[1:] - level) >= 0))[0]
        return t[i] + (level - v[i]) / (v[i + 1] - v[i]) * (t[i + 1] - t[i])

    ta, tb = cross(a), cross(b)
    if not len(ta) or not len(tb):
        return np.array([])
    # each edge: the first end-level crossing after a start-level crossing, from the last start
    # before it (a reflection that dips and comes back is no new edge)
    k = np.searchsorted(tb, ta)
    ok = k < len(tb)
    nxt = np.append(ta[1:], np.inf)
    ok &= nxt > np.where(ok, tb[np.minimum(k, len(tb) - 1)], np.inf)
    d = tb[k[ok]] - ta[ok]
    return d[(d > 0) & (d < max_s)]


def _hexagon(x, up, lo, mid, gap, top, bot) -> list[tuple[float, float]]:
    """The eye opening as the largest hexagon no trace enters. ``up``/``lo`` are the lowest high
    and highest low sample per phase ``x`` (UI from the centre). For a top level T, the flat top
    edge spans the phases around the centre whose traces stay above T (the bottom likewise); the
    corners at the mid level start at the crossings (-gap/2, +gap/2) and move in until the sides
    clear the traces. Of a few top and bottom levels, the largest hexagon wins."""
    h = gap / 2
    c = int(np.argmin(np.abs(x)))

    def flat(env, level, sign):  # phases around the centre whose traces stay beyond ``level``
        ok = sign * (env - level) >= 0
        if not ok[c]:
            return None
        l = r = c
        while l > 0 and ok[l - 1] and x[l - 1] > -h:
            l -= 1
        while r < len(x) - 1 and ok[r + 1] and x[r + 1] < h:
            r += 1
        return x[l], x[r]

    def corner(xe, need, room, side):
        """The mid-level corner of the side from the flat edge's end ``xe``: the side passes x at
        need (x - xv) / (xe - xv) from mid, which must stay within ``room``."""
        sel = (x < xe) & (x > -h) if side < 0 else (x > xe) & (x < h)
        q = np.clip(room[sel] / need, 0, None)
        xs = x[sel]
        bad = q < 1
        if side < 0:
            lim = (xs[bad] - q[bad] * xe) / (1 - q[bad])
            return max([-h, *lim])
        lim = (xs[bad] - q[bad] * xe) / (1 - q[bad])
        return min([h, *lim])

    best, area = [], 0.0
    for f in (1.0, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5):
        T = mid + f * (top - mid)
        ft = flat(up, T, 1)
        if ft is None:
            continue
        for g in (1.0, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5):
            B = mid + g * (bot - mid)
            fb = flat(lo, B, -1)
            if fb is None:
                continue
            ru, rl = up - mid, mid - lo
            xl = max(corner(ft[0], T - mid, ru, -1), corner(fb[0], mid - B, rl, -1))
            xr = min(corner(ft[1], T - mid, ru, 1), corner(fb[1], mid - B, rl, 1))
            pts = [(xl, mid), (ft[0], T), (ft[1], T), (xr, mid), (fb[1], B), (fb[0], B)]
            px, py = np.array(pts).T
            a = 0.5 * abs(np.dot(px, np.roll(py, 1)) - np.dot(py, np.roll(px, 1)))
            if a > area:
                best, area = [tuple(map(float, p)) for p in pts], a
    return best


def eye(t, v, ui, *, skip_ui: float, centre_window: float, edge_levels: tuple[float, float], bins: int = 200) -> dict:
    """The eye of a waveform, skipping its first ``skip_ui`` UI, measured on its joined-up trace:
    width   the widest gap between the mid-level crossings folded into one UI;
    centre  that gap's middle, as a phase (0..1 UI from the first sample);
    height  the opening within ±``centre_window`` UI of the centre;
    hexagon the opening as (phase from the centre in UI, V) points, clear of every trace;
    rise, fall  median edge times between ``edge_levels`` (shares of the swing, (0.2, 0.8) for
            20-80 %), between the levels at the centre.
    ``bins`` is the phase resolution of the measurement (200 per UI).
    Independent of where the waveform starts, so jittered and ideal runs are measured alike."""
    t, v = np.asarray(t, float), np.asarray(v, float)
    t0 = t[0]
    keep = t > t0 + skip_ui * ui
    t, v = t[keep], v[keep]
    nan = {"height": np.nan, "width": np.nan, "centre": np.nan, "hexagon": [], "rise": np.nan, "fall": np.nan}
    if len(t) < 4:
        return nan
    mid = 0.5 * (v.max() + v.min())
    ph = ((t - t0) % ui) / ui
    zc = np.sort(ph[1:][np.diff(np.sign(v - mid)) != 0])
    if not len(zc):
        return nan
    gaps = np.diff(np.append(zc, zc[0] + 1))
    k = int(np.argmax(gaps))
    centre, gap = (zc[k] + 0.5 * gaps[k]) % 1, gaps[k]

    td, vd = densify(t, v, dv=np.ptp(v) / 400, dt=ui / bins)
    x = ((td - t0) / ui - centre + 0.5) % 1 - 0.5  # phase from the centre, -0.5..0.5
    idx = np.clip(((x + 0.5) * bins).astype(int), 0, bins - 1)
    up, lo = np.full(bins, np.inf), np.full(bins, -np.inf)
    hi_m, lo_m = vd > mid, vd < mid
    np.minimum.at(up, idx[hi_m], vd[hi_m])
    np.maximum.at(lo, idx[lo_m], vd[lo_m])
    up, lo = np.where(np.isinf(up), mid, up), np.where(np.isinf(lo), mid, lo)
    c = bins // 2
    w = max(1, int(centre_window * bins))
    top, bot = up[c - w : c + w + 1].min(), lo[c - w : c + w + 1].max()
    hexagon = _hexagon((np.arange(bins) + 0.5) / bins - 0.5, up, lo, mid, gap, top, bot)

    cw = np.abs(((t - t0) / ui - centre + 0.5) % 1 - 0.5) < centre_window
    one, zero = np.median(v[cw & (v > mid)]), np.median(v[cw & (v < mid)])
    lo_level, hi_level = zero + edge_levels[0] * (one - zero), zero + edge_levels[1] * (one - zero)
    rise, fall = (_edge_times(t, v, lo_level, hi_level, s, ui) for s in (True, False))
    return {"height": float(top - bot), "width": float(gap * ui), "centre": float(centre), "hexagon": hexagon, "rise": float(np.median(rise)) if len(rise) else np.nan, "fall": float(np.median(fall)) if len(fall) else np.nan}


def densify(t, v, dv: float, dt: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The waveform with linear steps of at most ``dv`` (V) and ``dt`` (s) between samples.

    HyperLynx samples on a fixed step (10 ps) and moves jittered edges by whole steps, so a fast
    edge is a few samples at the same voltages every time: histogrammed raw, an eye shows dashes
    at discrete levels. Joined up, as a scope draws them, each edge is a line."""
    t, v = np.asarray(t, float), np.asarray(v, float)
    steps = np.abs(np.diff(v)) / dv
    if dt:
        steps = np.maximum(steps, np.diff(t) / dt)
    n = np.maximum(1, np.ceil(steps).astype(int))
    seg = np.repeat(np.arange(len(n)), n)
    frac = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / np.repeat(n, n)
    tt = np.append(t[seg] + frac * np.diff(t)[seg], t[-1])
    vv = np.append(v[seg] + frac * np.diff(v)[seg], v[-1])
    return tt, vv


def run_ui(run: Path, t, v) -> float:
    """The unit interval of an eye run: from its bit rate, else from its waveform."""
    bitrate = json.loads((run / "si.json").read_text()).get("bitrate")
    return 1 / bitrate if bitrate else unit_interval(t, v)[0]


def _label(run: Path) -> str:
    si = json.loads((run / "si.json").read_text())
    parts = ["real lines" if si.get("lossy") else "ideal lines"]
    if si.get("crosstalk"):
        parts.append("crosstalk")
    j = si.get("jitter", {})
    jit = []  # the jitter amounts (s); their frequencies, phase and mean are no amounts
    if j.get("Gaussian"):
        jit.append(f"random {j['Gaussian'] * 1e12:.0f} ps rms")
    if j.get("Sine"):
        jit.append(f"sine {j['Sine'] * 1e12:.0f} ps at {j.get('SineFreq', 0) / 1e6:g} MHz")
    if j.get("Uniform"):
        jit.append(f"uniform {j['Uniform'] * 1e12:.0f} ps")
    if j.get("Distortion"):
        jit.append(f"duty-cycle distortion {j['Distortion'] * 1e12:.0f} ps")
    label = f"{run.name}: " + ", ".join(parts)
    return label + ("\njitter " + ", ".join(jit) if jit else "")


@mpl.rc_context(PLOT_STYLE)
def plot_si(runs: list[Path], out: Path, *, skip_ui: float, centre_window: float, edge_levels: tuple[float, float], settle: float) -> list[Path]:
    """Waveforms and eyes of SI runs, and crosstalk runs (those with aggressors) on their own.
    skip_ui, centre_window, edge_levels: as for eye(); settle: share of a crosstalk run's time
    left out as start-up."""
    paths: list[Path] = []
    # runs with aggressors (a quiet victim, another stimulus) get their own crosstalk plot
    signal = [r for r in runs if not json.loads((r / "si.json").read_text()).get("aggressors")]
    waves = {r: _diff_waves(r) for r in signal}
    names = [w["name"] for w in waves[signal[0]]] if signal else []
    if not names:
        return paths + [p for r in runs for p in _plot_crosstalk(r, json.loads((r / "si.json").read_text()), out, settle)]
    fig, axes = plt.subplots(len(names), 1, figsize=(9.6, 2.6 * len(names) + 0.6), sharex=True, squeeze=False)
    for ax, name in zip(axes[:, 0], names):
        for (r, ws), c in zip(waves.items(), CURVE_COLORS):
            w = next((w for w in ws if w["name"] == name), None)
            if w is None:
                continue
            t, v = wave(r / w["file"])
            m = t < min(t[-1], t[0] + 150e-9 + (t[-1] - t[0]) * 0.1)
            ax.plot(t[m] * 1e9, v[m], color=c, label=_label(r))
        ax.set_title(name, fontsize=10)
        ax.set_ylabel("V (V)")
        style_grid(ax)
    axes[0, 0].legend(loc="upper right", fontsize=8)
    axes[-1, 0].set_xlabel("Time (ns)")
    paths += save_figure(fig, out / "si_waveforms")

    eyes = [r for r in signal if json.loads((r / "si.json").read_text()).get("mode") == "eye"]
    if eyes:
        first = eyes[0]
        fig, axes = plt.subplots(len(eyes), len(names), figsize=(4.8 * len(names), 3.2 * len(eyes) + 0.6), squeeze=False, sharex=True)
        t0, v0 = wave(first / waves[first][0]["file"])
        ui = run_ui(first, t0, v0)
        for i, r in enumerate(eyes):
            for j, name in enumerate(names):
                w = next((w for w in waves[r] if w["name"] == name), None)
                ax = axes[i, j]
                if w is None:
                    ax.set_visible(False)
                    continue
                t, v = wave(r / w["file"])
                e = eye(t, v, ui, skip_ui=skip_ui, centre_window=centre_window, edge_levels=edge_levels)
                span = max(abs(v).max(), 1e-3) * 1.1
                nx, ny = 400, 240
                td, vd = densify(t, v, dv=span / ny, dt=ui / (nx / 2))  # a point in every bin it crosses
                keep = td > td[0] + skip_ui * ui
                # each eye centred at 1 UI, its crossings near 0.5 and 1.5
                x = ((td[keep] - t[0]) / ui - e["centre"] + 1) % 2
                hist, xe, ye = np.histogram2d(x, vd[keep], bins=(nx, ny), range=((0, 2), (-span, span)))
                mesh = ax.pcolormesh(xe, ye, np.ma.masked_less_equal(hist.T, 0), cmap=DENSITY_COLOR_MAP, norm=LogNorm(), shading="flat", rasterized=True)
                if e["hexagon"]:
                    hx = [1 + p[0] for p in e["hexagon"]] + [1 + e["hexagon"][0][0]]
                    hy = [p[1] for p in e["hexagon"]] + [e["hexagon"][0][1]]
                    ax.fill(hx, hy, color=GRID_MAJOR_COLOR, alpha=0.6, lw=0)
                    ax.plot(hx, hy, color=SPINE_COLOR, lw=1.0)
                    # the values inside the opening, at its middle
                    cx = float(np.mean(hx[1:3] + hx[4:6]))  # the middle of the flat edges
                    cy = 0.5 * (max(hy) + min(hy))
                    ax.text(cx, cy, f"height {e['height'] * 1e3:.0f} mV\nwidth {e['width'] * 1e9:.2f} ns\n= {e['width'] / ui:.2f} UI\nrise {e['rise'] * 1e12:.0f} ps\nfall {e['fall'] * 1e12:.0f} ps\n({edge_levels[0]:.0%}-{edge_levels[1]:.0%})", ha="center", va="center", fontsize=7, color=SPINE_COLOR, linespacing=1.4)
                ax.set_xlim(0, 2)
                ax.set_title(f"{name}\n{_label(r)}", fontsize=8)
                if i == len(eyes) - 1:
                    ax.set_xlabel(f"Time (UI, {ui * 1e9:.3g} ns, {1 / ui / 1e6:.0f} Mb/s)")
                if j == 0:
                    ax.set_ylabel("V (V)")
        fig.colorbar(mesh, ax=axes, label="Samples")
        paths += save_figure(fig, out / "si_eye")

    for r in runs:
        si = json.loads((r / "si.json").read_text())
        if si.get("aggressors"):
            paths += _plot_crosstalk(r, si, out, settle)
    return paths


@mpl.rc_context(PLOT_STYLE)
def _plot_crosstalk(run: Path, si: dict, out: Path, settle: float) -> list[Path]:
    fig, axes = plt.subplots(2, 1, figsize=(9.6, 6.0), sharex=True)
    for g, c in zip(si["aggressors"], CURVE_COLORS[2:]):
        stem = g["driver"].replace(".", "-")
        w = next((w for w in si["waves"] if w["name"] in (f"V({stem})", g["driver"])), None)
        if w:
            t, v = wave(run / w["file"])
            axes[0].plot(t * 1e9, v, color=c, label=f"aggressor {g['driver']}")
    axes[0].set_ylabel("Aggressor (V)")
    axes[0].legend(loc="upper right")
    victim = _diff_waves(run)[-1]
    t, v = wave(run / victim["file"])
    k = t > t[0] + settle * (t[-1] - t[0])
    axes[1].plot(t * 1e9, (v - np.median(v[k])) * 1e3, color=CURVE_COLORS[1])
    axes[1].set_title(f"{victim['name']}" + (f" (drivers {', '.join(f'{p} {s}' for p, s in si['driver_states'].items())})" if si.get("driver_states") else "") + f": {np.ptp(v[k]) * 1e3:.0f} mV p-p, {v[k].std() * 1e3:.0f} mV rms", fontsize=10)
    axes[1].set_ylabel("Victim noise (mV)")
    axes[1].set_xlabel("Time (ns)")
    for ax in axes:
        style_grid(ax)
    return list(save_figure(fig, out / f"crosstalk_{run.name}"))


# ------------------------------------------------------------------------------------- S-parameters


def read_touchstone(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(f Hz, S[f, n, n]) of an RI/MA/DB Touchstone v1 file."""
    n = int(Path(path).suffix[2:-1])
    nums, unit, fmt = [], 1.0, "MA"
    for line in open(path):
        line = line.split("!")[0].strip()
        if line.startswith("#"):
            tok = line[1:].upper().split()
            unit = {"HZ": 1, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}.get(tok[0], 1.0)
            fmt = next((t for t in tok if t in ("RI", "MA", "DB")), "MA")
        elif line:
            nums += [float(t) for t in line.split()]
    a = np.array(nums).reshape(-1, 1 + 2 * n * n)
    x, y = a[:, 1::2], a[:, 2::2]
    s = x + 1j * y if fmt == "RI" else (x if fmt == "MA" else 10 ** (x / 20)) * np.exp(1j * np.deg2rad(y))
    s = s.reshape(-1, n, n)
    return a[:, 0] * unit, (np.swapaxes(s, 1, 2) if n == 2 else s)  # 2-port files are column-major


@mpl.rc_context(PLOT_STYLE)
def plot_sparam(run: Path, out: Path) -> list[Path]:
    info = json.loads((run / "sparam.json").read_text())
    f, S = read_touchstone(run / info["file"])
    pins, n = info["pins"], S.shape[1]
    db = lambda x: 20 * np.log10(np.abs(x) + 1e-30)
    fig, ax = plt.subplots()
    if n == 4:  # ports 1,2 at one end, 3,4 at the other, P before N
        M = np.array([[1, -1, 0, 0], [0, 0, 1, -1], [1, 1, 0, 0], [0, 0, 1, 1]]) / np.sqrt(2)
        Smm = M @ S @ M.T
        curves = [("SDD21, insertion", Smm[:, 1, 0]), ("SDD11, return", Smm[:, 0, 0]), ("SCD21, diff to common", Smm[:, 3, 0])]
    else:
        curves = [(f"S{i + 1}{j + 1} ({pins[i]} <- {pins[j]})", S[:, i, j]) for i in range(n) for j in range(i + 1)]
    for (lab, s), c in zip(curves, CURVE_COLORS):
        ax.semilogx(f, db(s), color=c, label=lab)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.set_title(f"S-parameters {', '.join(pins)}" + (" (lossy)" if info.get("lossy") else " (lossless)"))
    style_grid(ax)
    ax.legend(loc="lower left", fontsize=8)
    style_info_box(ax, [f"max singular value {np.linalg.svd(S, compute_uv=False).max():.3f}"], location="lower right")
    return list(save_figure(fig, out / f"sparams_{run.name}"))


# ------------------------------------------------------------------------------------------ all
