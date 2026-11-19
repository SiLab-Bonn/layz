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
from matplotlib.colors import LogNorm

from layz.plotstyle import (CURVE_COLORS, DENSITY_COLOR_MAP, GRID_MAJOR_COLOR, PLOT_STYLE, SPINE_COLOR,
                            save_figure, style_grid, style_info_box)

MM, IN = 1e3, 25.4


def _rows(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _job(run: Path) -> dict:
    return json.loads((run / "job.json").read_text())


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
            a = np.array([float(t) if t else np.nan for t in vals.split(",")[1:nx + 1]])
            grids[cur][int(k), :len(a)] = a
    return grids, dx * dy * IN * IN, [x0 * IN, (x0 + nx * dx) * IN, y0 * IN, (y0 + ny * dy) * IN]


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
        ax.scatter([float(c["x1"]) * MM for c in vias if c["net"] in side],
                   [float(c["y1"]) * MM for c in vias if c["net"] in side], s=1, color=GRID_MAJOR_COLOR, zorder=1)
        pins = [p for p in ports if p["net"] in side and p["x"]]
        if not pins:
            ax.set_visible(False)
            continue
        v = np.array([float(p["voltage_V"]) for p in pins])
        cmap = DENSITY_COLOR_MAP.reversed() if name == "Supply" else DENSITY_COLOR_MAP  # worst bright
        sc = ax.scatter([float(p["x"]) * MM for p in pins], [float(p["y"]) * MM for p in pins], c=v * 1e3,
                        cmap=cmap, s=22, edgecolors=SPINE_COLOR, linewidths=0.3, zorder=2)
        fig.colorbar(sc, ax=ax, label="Pin voltage (mV)")
        ax.set_aspect("equal")
        ax.set_ylabel("y (mm)")
        ax.set_title(f"{name} pins ({', '.join(sorted(side))}): {v.min() * 1e3:.1f} to {v.max() * 1e3:.1f} mV, "
                     f"loss {_loss(ports, side) * 1e3:.0f} mW (grey: vias)", fontsize=10)
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
            sc = ax.scatter([float(vias[k]["x1"]) * MM for k in sel], [float(vias[k]["y1"]) * MM for k in sel],
                            c=cur[sel], cmap=DENSITY_COLOR_MAP, norm=norm, s=5, linewidths=0)
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
    return paths


@mpl.rc_context(PLOT_STYLE)
def _plot_loss(maps, out: Path) -> list[Path]:
    layers = []
    for _, (g, _, _), _ in maps:
        tot = sum(np.nansum(a) for a in g.values())
        layers += [n for n, a in g.items() if np.nansum(a) > 1e-3 * tot and n not in layers]
    vmax = max(np.nanmax(a / c) for _, (g, c, _), _ in maps for n, a in g.items() if n in layers)
    norm = LogNorm(vmin=vmax * 1e-4, vmax=vmax)
    fig, axes = plt.subplots(len(layers), len(maps), figsize=(7.2 * len(maps), 1.25 * len(layers) + 1.0),
                             sharex=True, sharey=True, squeeze=False)
    for j, (side, (g, cell, ext), exact) in enumerate(maps):
        tot = sum(np.nansum(a) for a in g.values())
        empty = [n for n, a in g.items() if n not in layers]
        for i, lay in enumerate(layers):
            ax, a = axes[i, j], g.get(lay)
            if a is not None:
                im = ax.imshow(np.where(a > 0, a / cell, np.nan), origin="lower", extent=ext, cmap=DENSITY_COLOR_MAP,
                               norm=norm, aspect="equal", interpolation="nearest", rasterized=True)
            note = (f" (map total {tot * 1e3:.0f} mW, exact I·ΔV {exact * 1e3:.0f} mW)" if i == 0
                    else f" (no copper on {', '.join(empty)})" if i == len(layers) - 1 and empty else "")
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


def eye_metrics(t, v, ui, tc) -> tuple[float, float]:
    """Eye height at the centre (±5 % UI) and eye width at the mid level, skipping 4 UI."""
    keep = t > tc + 4 * ui
    ph, vv = ((t[keep] - tc) % ui) / ui, v[keep]
    mid = 0.5 * (vv.max() + vv.min())
    c = np.abs(ph - 0.5) < 0.05
    hi, lo = vv[c & (vv > mid)], vv[c & (vv < mid)]
    zc = (ph[1:][np.diff(np.sign(vv - mid)) != 0] + 0.5) % 1.0
    return (hi.min() - lo.max() if len(hi) and len(lo) else np.nan), ((1 - np.ptp(zc)) * ui if len(zc) else np.nan)


def _label(run: Path) -> str:
    si = json.loads((run / "si.json").read_text())
    parts = ["real lines" if si.get("lossy") else "ideal lines"]
    if si.get("crosstalk"):
        parts.append("crosstalk")
    jit = {k: v for k, v in si.get("jitter", {}).items() if v and k != "SineFreq"}
    if jit:
        parts.append("jitter " + ", ".join(f"{k} {v * 1e12:.0f} ps" for k, v in jit.items()))
    return f"{run.name}: " + ", ".join(parts)


@mpl.rc_context(PLOT_STYLE)
def plot_si(runs: list[Path], out: Path) -> list[Path]:
    paths: list[Path] = []
    # runs with aggressors (a quiet victim, another stimulus) get their own crosstalk plot
    signal = [r for r in runs if not json.loads((r / "si.json").read_text()).get("aggressors")]
    waves = {r: _diff_waves(r) for r in signal}
    names = [w["name"] for w in waves[signal[0]]] if signal else []
    if not names:
        return paths + [p for r in runs for p in _plot_crosstalk(r, json.loads((r / "si.json").read_text()), out)]
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
        fig, axes = plt.subplots(len(eyes), len(names), figsize=(4.8 * len(names), 3.2 * len(eyes) + 0.6),
                                 squeeze=False, sharex=True)
        t0, v0 = wave(first / waves[first][0]["file"])
        ui, tc = unit_interval(t0, v0)
        for i, r in enumerate(eyes):
            for j, name in enumerate(names):
                w = next((w for w in waves[r] if w["name"] == name), None)
                ax = axes[i, j]
                if w is None:
                    ax.set_visible(False)
                    continue
                t, v = wave(r / w["file"])
                keep = t > tc + 4 * ui
                span = max(abs(v).max(), 1e-3) * 1.1
                hist, xe, ye = np.histogram2d(((t[keep] - tc + 0.5 * ui) % (2 * ui)) / ui, v[keep],
                                              bins=(400, 240), range=((0, 2), (-span, span)))
                mesh = ax.pcolormesh(xe, ye, np.ma.masked_less_equal(hist.T, 0), cmap=DENSITY_COLOR_MAP,
                                     norm=LogNorm(), shading="flat", rasterized=True)
                hgt, wid = eye_metrics(t, v, ui, tc)
                ax.set_title(f"{name}\n{_label(r)}", fontsize=8)
                style_info_box(ax, [f"height {hgt * 1e3:.0f} mV", f"width {wid * 1e9:.2f} ns"],
                               location="center")  # the eye's opening is empty
                if i == len(eyes) - 1:
                    ax.set_xlabel(f"Time (UI, {ui * 1e9:.3g} ns, {1 / ui / 1e6:.0f} Mb/s)")
                if j == 0:
                    ax.set_ylabel("V (V)")
        fig.colorbar(mesh, ax=axes, label="Samples")
        paths += save_figure(fig, out / "si_eye")

    for r in runs:
        si = json.loads((r / "si.json").read_text())
        if si.get("aggressors"):
            paths += _plot_crosstalk(r, si, out)
    return paths


@mpl.rc_context(PLOT_STYLE)
def _plot_crosstalk(run: Path, si: dict, out: Path) -> list[Path]:
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
    k = t > t[0] + 0.1 * (t[-1] - t[0])
    axes[1].plot(t * 1e9, (v - np.median(v[k])) * 1e3, color=CURVE_COLORS[1])
    axes[1].set_title(f"{victim['name']}" + (" (victim held low)" if si.get("victim_quiet") else "") +
                      f": {np.ptp(v[k]) * 1e3:.0f} mV p-p, {v[k].std() * 1e3:.0f} mV rms", fontsize=10)
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
    db = lambda x: 20 * np.log10(np.abs(x) + 1e-30)  # noqa: E731
    fig, ax = plt.subplots()
    if n == 4:  # ports 1,2 at one end, 3,4 at the other, P before N
        M = np.array([[1, -1, 0, 0], [0, 0, 1, -1], [1, 1, 0, 0], [0, 0, 1, 1]]) / np.sqrt(2)
        Smm = M @ S @ M.T
        curves = [("SDD21, insertion", Smm[:, 1, 0]), ("SDD11, return", Smm[:, 0, 0]),
                  ("SCD21, diff to common", Smm[:, 3, 0])]
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

def plot_runs(runs: list[Path], out: Path | None = None) -> list[Path]:
    runs = [Path(r) for r in runs]
    out = Path(out) if out else runs[0] / "plots"
    jobs = {r: _job(r) for r in runs}
    paths: list[Path] = []
    returns = {Path(j["return_from"]).parent.resolve(): r for r, j in jobs.items() if j.get("return_from")}
    for r, j in jobs.items():
        if j["kind"] == "dc" and not j.get("return_from"):
            paths += plot_dc(r, out, returns.get(r.resolve()))
        elif j["kind"] == "sparam":
            paths += plot_sparam(r, out)
    si = [r for r, j in jobs.items() if j["kind"] == "si"]
    if si:
        paths += plot_si(si, out)
    return paths
