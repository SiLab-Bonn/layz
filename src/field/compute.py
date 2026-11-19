#!/usr/bin/env python3
"""Electric field and potential from a FasterCap charge solution (fieldsolve.py --charges).

FasterCap solves for the surface charge on every panel: on conductors and, for dielectric
interfaces, the polarization charge. Both are *total* charges, so the potential and field
anywhere are plain Coulomb sums over all panels in vacuum:

    phi(r) = 1/(4 pi eps0) sum_i sigma_i A_i / |r - r_i|
    E(r)   = 1/(4 pi eps0) sum_i sigma_i A_i (r - r_i) / |r - r_i|^3

(far panels as point charges, near ones integrated adaptively). One
FasterCap column holds the charges with one conductor at 1 V and the others at 0 V; any
set of conductor voltages is a superposition of these columns.

Writes into the run directory:
    field.vtk     E (V/m), |E|, Ez, phi on a 3-D grid: ParaView -> Slice / Glyph / Stream Tracer
    panels.vtk    the refined panels with their charge density, conductor/dielectric id
    field.html    interactive preview: conductors + |E| on cut planes (open in a browser)

Run in the repo's venv (see install.md):
    layz field run_board --voltage TOP=1 --voltage BOT=0
"""

from __future__ import annotations

import argparse
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

EPS0 = 8.8541878128e-12
KE = 1.0 / (4.0 * math.pi * EPS0)
UM = 1e-6  # model lengths are µm; FasterCap treats them as m, so its fields are V/µm


# --------------------------------------------------------------------------- reading


def read_panels(path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Triangles (N,3,3) in µm, charge density per triangle, owner name per triangle."""
    tris, q, owner = [], [], []
    for line in path.read_text().splitlines():
        t = line.split()
        if not t or t[0] not in ("T", "Q"):
            continue
        n = 3 if t[0] == "T" else 4
        v = np.array(t[2:2 + 3 * n], float).reshape(n, 3)
        sigma = float(t[-1])  # dielectric lines carry a reference point before the charge
        for tri in ([v[0], v[1], v[2]],) if n == 3 else ([v[0], v[1], v[2]], [v[0], v[2], v[3]]):
            tris.append(tri)
            q.append(sigma)
            owner.append(t[1])
    return np.array(tris, float).reshape(-1, 3, 3), np.array(q), owner


def clean(name: str) -> str:
    return re.sub(r"^g\d+_", "", name)


def load_run(run: Path) -> dict[str, tuple[np.ndarray, np.ndarray, list[str]]]:
    """Excitation name -> (triangles, sigma, owner) of all panels in that column."""
    cols = {}
    lst = sorted(p for p in run.glob("m_g*.lst"))
    if not lst:
        raise SystemExit(f"no charge files in {run}: run fieldsolve.py with --charges")
    for p in lst:
        exc = clean(p.stem[2:])
        parts = []
        for line in p.read_text().splitlines():
            t = line.split()
            if t and t[0] == "C":
                tr, sg, ow = read_panels(run / t[1])
                parts.append((tr, sg, [clean(o) for o in ow]))
            elif t and t[0] == "D":  # dielectric interface: "diel:<εr one side>:<εr other side>"
                tr, sg, ow = read_panels(run / t[1])
                parts.append((tr, sg, [f"diel:{float(t[2]):g}:{float(t[3]):g}"] * len(ow)))
        tris = np.concatenate([x[0] for x in parts])
        sig = np.concatenate([x[1] for x in parts])
        own = [o for x in parts for o in x[2]]
        cols[exc] = (tris, sig, own)
    return cols


# --------------------------------------------------------------------------- physics


def _split(t: np.ndarray, levels: int) -> np.ndarray:
    """Midpoint-subdivide triangles (M,3,3) `levels` times -> (M, 4**levels, 3, 3)."""
    t = t[:, None]
    for _ in range(levels):
        a, b, c = t[..., 0, :], t[..., 1, :], t[..., 2, :]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        t = np.concatenate([np.stack(x, -2) for x in
                            ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))], axis=1)
    return t


NEAR = 3.0      # a (sub-)triangle closer than NEAR x its size is split further
MAX_DEPTH = 12  # down to size/4096


def _near(p: np.ndarray, tris: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Adaptive integration of pairs (point p[i], triangle tris[i] with charge q[i]):
    split into 4, keep the children that are far enough as point charges, recurse on the rest."""
    n = len(p)
    ph, e = np.zeros(n), np.zeros((n, 3))
    idx, T, Q = np.arange(n), tris, q
    for depth in range(MAX_DEPTH):
        T = _split(T, 1).reshape(-1, 3, 3)
        Q, idx = np.repeat(Q / 4, 4), np.repeat(idx, 4)
        c = T.mean(axis=1)
        size = np.max(np.linalg.norm(T - np.roll(T, 1, axis=1), axis=2), axis=1)
        d = p[idx] - c
        r2 = np.maximum(np.einsum("ij,ij->i", d, d), 1e-18)
        done = (r2 >= (NEAR * size) ** 2) | (depth == MAX_DEPTH - 1)
        r = np.sqrt(r2[done])
        np.add.at(ph, idx[done], Q[done] / r)
        np.add.at(e, idx[done], (Q[done] / r ** 3)[:, None] * d[done])
        T, Q, idx = T[~done], Q[~done], idx[~done]
        if not len(idx):
            break
    return ph, e


def coulomb(tris: np.ndarray, sig: np.ndarray, pts: np.ndarray,
            threads: int) -> tuple[np.ndarray, np.ndarray]:
    """phi (V) and E (V/m) at pts (µm) from uniformly charged triangles (FasterCap units).

    Far panels act as point charges at their centroids; panels within NEAR panel sizes of
    a point are integrated adaptively (_near)."""
    cen = tris.mean(axis=1)
    area = 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
    q = sig * area
    size = np.max(np.linalg.norm(tris - np.roll(tris, 1, axis=1), axis=2), axis=1)
    phi = np.zeros(len(pts))
    E = np.zeros((len(pts), 3))
    chunk = max(1, int(1e6 // max(len(tris), 1)))  # ~60 MB of temporaries per thread

    def work(i0):
        p = pts[i0:i0 + chunk]
        d = p[:, None, :] - cen[None, :, :]
        r2 = np.maximum(np.einsum("ijk,ijk->ij", d, d), 1e-18)
        inv = 1.0 / np.sqrt(r2)
        near = r2 < (NEAR * size[None, :]) ** 2
        inv[near] = 0.0  # handled by _near
        ph = inv @ q
        e = np.einsum("ij,ijk->ik", q[None, :] * inv ** 3, d)
        pi, ji = np.nonzero(near)
        for s0 in range(0, len(pi), 4000):
            pp, jj = pi[s0:s0 + 4000], ji[s0:s0 + 4000]
            nph, ne = _near(p[pp], tris[jj], q[jj])
            np.add.at(ph, pp, nph)
            np.add.at(e, pp, ne)
        phi[i0:i0 + chunk] = KE * ph
        E[i0:i0 + chunk] = KE * e / UM

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(work, range(0, len(pts), chunk)))
    return phi, E


# --------------------------------------------------------------------------- output


def write_vtk_grid(path: Path, origin, spacing, dims, phi, E) -> None:
    _write_vtk_points(path, "fieldview E field (V/m), potential (V), lengths in um",
                      dims, origin, spacing, vectors={"E": E},
                      scalars={"Emag": np.linalg.norm(E, axis=1), "Ez": E[:, 2], "phi": phi})


def write_vtk_panels(path: Path, tris, sig, owner) -> None:
    names = sorted(set(owner))
    ids = np.array([names.index(o) for o in owner])
    n = len(tris)
    with open(path, "w") as f:
        f.write("# vtk DataFile Version 3.0\nfieldview panels; owner ids: "
                + " ".join(f"{i}={nm}" for i, nm in enumerate(names)) + "\n")
        f.write(f"ASCII\nDATASET POLYDATA\nPOINTS {3 * n} float\n")
        np.savetxt(f, tris.reshape(-1, 3), fmt="%.6g")
        f.write(f"POLYGONS {n} {4 * n}\n")
        np.savetxt(f, np.column_stack([np.full(n, 3), np.arange(3 * n).reshape(-1, 3)]), fmt="%d")
        f.write(f"CELL_DATA {n}\nSCALARS sigma_total float 1\nLOOKUP_TABLE default\n")
        np.savetxt(f, sig, fmt="%.6g")
        f.write("SCALARS owner int 1\nLOOKUP_TABLE default\n")
        np.savetxt(f, ids, fmt="%d")


def write_html(path: Path, title: str, info: str, zs: float, unit: str, scale: float,
               conductors: list, dielectrics: list, planes: list) -> None:
    """Self-contained plotly page (plotly.js inlined, works offline).

    conductors: [(label, triangles)], dielectrics: [(εr, triangles)], planes: [(label, X, Y, Z, |E|
    scaled, visible)]. Geometry in µm; z is multiplied by zs here. (Field lines: ParaView, on a
    --plane section; see paraview/section.py.)"""
    import plotly.graph_objects as go

    bg, fg, grid = "#0d1117", "#c9d1d9", "#30363d"
    fig = go.Figure()

    def mesh(tris, **kw):
        v = tris.reshape(-1, 3).copy()
        v[:, 2] *= zs
        k = np.arange(len(v)).reshape(-1, 3)
        return go.Mesh3d(x=v[:, 0], y=v[:, 1], z=v[:, 2], i=k[:, 0], j=k[:, 1], k=k[:, 2], **kw)

    # dielectrics: translucent, greener for higher εr (FR4 > solder mask)
    ks = sorted({k for k, _ in dielectrics})
    for n, (k, tris) in enumerate(sorted(dielectrics, key=lambda d: d[0])):
        frac = 0.0 if len(ks) == 1 else ks.index(k) / (len(ks) - 1)
        color = f"rgb({int(60 - 20 * frac)},{int(140 + 40 * frac)},{int(90 - 20 * frac)})"
        fig.add_trace(mesh(tris, color=color, opacity=0.10 + 0.06 * frac, flatshading=True,
                           name="dielectrics", legendgroup="diel", showlegend=(n == 0),
                           hovertemplate=f"dielectric εr={k:g}<extra></extra>",
                           lighting=dict(ambient=0.8, diffuse=0.3, specular=0.0)))
    for label, tris in conductors:
        fig.add_trace(mesh(tris, color="#d08a4a", opacity=1.0, flatshading=True, name=label,
                           hovertemplate=f"{label}<extra></extra>",
                           lighting=dict(ambient=0.45, diffuse=0.8, specular=0.6, roughness=0.35),
                           lightposition=dict(x=2000, y=-5000, z=8000)))

    vals = np.concatenate([p[4][np.isfinite(p[4])].ravel() for p in planes])
    vmax = float(np.nanpercentile(vals, 99.5))
    for j, (label, X, Y, Z, C, visible) in enumerate(planes):
        fig.add_trace(go.Surface(x=X, y=Y, z=Z * zs, surfacecolor=C, colorscale="Turbo",
                                 cmin=0, cmax=vmax, name=label, showlegend=True,
                                 visible=True if visible else "legendonly", opacity=0.92,
                                 showscale=(j == 0),
                                 colorbar=dict(title=dict(text=f"|E| ({unit})", font=dict(color=fg)),
                                               tickfont=dict(color=fg), x=1.0, len=0.75,
                                               outlinewidth=0),
                                 lighting=dict(ambient=1.0, diffuse=0.0, specular=0.0),
                                 hovertemplate=f"{label}<br>x=%{{x:.0f}} y=%{{y:.0f}} µm"
                                               f"<br>|E|=%{{surfacecolor:.3g}} {unit}<extra></extra>"))
    axis = dict(color=fg, gridcolor=grid, zerolinecolor=grid, showbackground=False,
                title_font=dict(size=12))
    zaxis = dict(axis, tickvals=None, title=f"z (µm) ×{zs:.3g}" if zs != 1 else "z (µm)")
    if zs != 1:  # label the stretched axis in real µm
        zmin = min(float(np.nanmin(p[3])) for p in planes)
        zmax = max(float(np.nanmax(p[3])) for p in planes)
        ticks = np.linspace(zmin, zmax, 5)
        zaxis.update(tickvals=ticks * zs, ticktext=[f"{t:.0f}" for t in ticks])
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=bg, font=dict(color=fg),
        title=dict(text=f"{title}<br><sup>{info}</sup>", x=0.02),
        scene=dict(xaxis=dict(axis, title="x (µm)"), yaxis=dict(axis, title="y (µm)"), zaxis=zaxis,
                   aspectmode="data", bgcolor=bg,
                   camera=dict(eye=dict(x=0.25, y=-1.55, z=0.55), up=dict(x=0, y=0, z=1))),
        legend=dict(itemclick="toggle", x=0.01, y=0.92, bgcolor="rgba(13,17,23,0.6)",
                    font=dict(color=fg)),
        margin=dict(l=0, r=0, t=70, b=0))
    fig.write_html(str(path), include_plotlyjs=True, full_html=True,
                   config=dict(displaylogo=False, toImageButtonOptions=dict(scale=2)))


# --------------------------------------------------------------------------- cross-section


def plane_segments(tris: np.ndarray, axis: int, value: float) -> np.ndarray:
    """Intersections of triangles with the plane coord[axis] == value, as segments (n,2,2)
    in (u, z), u being the other horizontal axis. Triangles lying in the plane are skipped."""
    u_ax = 1 - axis  # axis 0 (x cut) -> u = y; axis 1 (y cut) -> u = x
    d = tris[:, :, axis] - (value + 1e-6)  # off mesh vertices, which often sit on round values
    cross = (d.min(1) < 0) & (d.max(1) > 0)
    segs = []
    for t, dd in zip(tris[cross], d[cross]):
        pts = []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            if dd[i] == 0:
                pts.append(t[i])
            if dd[i] * dd[j] < 0:
                a = dd[i] / (dd[i] - dd[j])
                pts.append(t[i] + a * (t[j] - t[i]))
        if len(pts) >= 2:
            segs.append([[pts[0][u_ax], pts[0][2]], [pts[1][u_ax], pts[1][2]]])
    return np.array(segs).reshape(-1, 2, 2)


def chain(segs: np.ndarray, tol: float = 1e-3) -> list[np.ndarray]:
    """Join segments sharing end points into closed polygons (conductor cross-sections)."""
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    adj: dict = {}
    for k, (a, b) in enumerate(segs):
        adj.setdefault(key(a), []).append((k, 1))
        adj.setdefault(key(b), []).append((k, 0))
    used = np.zeros(len(segs), bool)
    polys = []
    for k0 in range(len(segs)):
        if used[k0]:
            continue
        used[k0] = True
        poly = [segs[k0][0], segs[k0][1]]
        cur = segs[k0][1]
        while True:
            nxt = [(k, e) for k, e in adj.get(key(cur), []) if not used[k]]
            if not nxt:
                break
            k, e = nxt[0]
            used[k] = True
            cur = segs[k][e]
            poly.append(cur)
        if len(poly) >= 4:
            polys.append(np.array(poly))
    return polys


def write_vtk_section(path: Path, axis: int, value: float, gu, gz, phi, Eu, Eo, Ez) -> None:
    """A cross-section as a one-cell-thick VTK grid (ParaView: color by Emag/Ez/phi, and
    Stream Tracer on E_plane for field lines). Values inside conductors: phi NaN, E 0."""
    nu, nz = len(gu), len(gz)
    du = (gu[-1] - gu[0]) / max(nu - 1, 1)
    dz = (gz[-1] - gz[0]) / max(nz - 1, 1)
    if axis == 1:  # y cut: u = x
        dims, origin, spacing = (nu, 1, nz), (gu[0], value, gz[0]), (du, 1.0, dz)
        E, Ep = (Eu, Eo, Ez), (Eu, 0 * Eo, Ez)
    else:          # x cut: u = y
        dims, origin, spacing = (1, nu, nz), (value, gu[0], gz[0]), (1.0, du, dz)
        E, Ep = (Eo, Eu, Ez), (0 * Eo, Eu, Ez)
    vec = lambda c: np.column_stack([a.ravel() for a in c])
    _write_vtk_points(path, "fieldview cross-section: E (V/m), phi (V), lengths in um",
                      dims, origin, spacing,
                      vectors={"E": vec(E), "E_plane": vec(Ep)},
                      scalars={"Emag": np.hypot(np.hypot(Eu, Ez), Eo), "Ez": Ez, "phi": phi})


def _write_vtk_points(path: Path, title: str, dims, origin, spacing,
                      vectors: dict, scalars: dict) -> None:
    """Legacy VTK STRUCTURED_POINTS, binary (big-endian float32: compact, and NaN-safe)."""
    n = int(np.prod(dims))
    with open(path, "wb") as f:
        head = (f"# vtk DataFile Version 3.0\n{title}\nBINARY\nDATASET STRUCTURED_POINTS\n"
                f"DIMENSIONS {dims[0]} {dims[1]} {dims[2]}\n"
                "ORIGIN {} {} {}\nSPACING {} {} {}\n".format(*origin, *spacing)
                + f"POINT_DATA {n}\n")
        f.write(head.encode())
        for name, arr in vectors.items():
            f.write(f"VECTORS {name} float\n".encode())
            f.write(np.asarray(arr, ">f4").reshape(n, 3).tobytes() + b"\n")
        for name, arr in scalars.items():
            f.write(f"SCALARS {name} float 1\nLOOKUP_TABLE default\n".encode())
            f.write(np.asarray(arr, ">f4").reshape(n).tobytes() + b"\n")


def section_seeds(outlines: dict, gu, gz, Em, n: int) -> np.ndarray:
    """Field-line seeds for a section, for any geometry: points just outside every conductor's
    outline in the window, chosen with a density following sqrt(|E|) there, so lines start where
    field leaves or enters copper (more where it's stronger, but some on weak faces too).
    Returns (k, 2) points in (u, z)."""
    from matplotlib.path import Path as MPath

    du, dz = gu[1] - gu[0], gz[1] - gz[0]
    h = min(du, dz)
    paths = [MPath(p) for polys in outlines.values() for p in polys]
    cand = []
    for polys in outlines.values():
        for poly in polys:
            P = poly[:-1] if np.allclose(poly[0], poly[-1]) else poly
            if len(P) < 3:
                continue
            area = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
            seg = np.roll(P, -1, axis=0) - P
            ln = np.linalg.norm(seg, axis=1)
            nrm = np.column_stack([seg[:, 1], -seg[:, 0]]) / np.maximum(ln, 1e-12)[:, None]
            nrm = -nrm if area < 0 else nrm  # outward
            for k in range(len(P)):
                m = max(1, int(ln[k] / (0.5 * h)))
                t = (np.arange(m) + 0.5) / m
                cand.append(P[k] + t[:, None] * seg[k] + 1.5 * h * nrm[k])
    if not cand:
        return np.zeros((0, 2))
    c = np.concatenate(cand)
    ok = (c[:, 0] > gu[0]) & (c[:, 0] < gu[-1]) & (c[:, 1] > gz[0]) & (c[:, 1] < gz[-1])
    c = c[ok]
    for p in paths:
        c = c[~p.contains_points(c)]
    if not len(c):
        return c
    iu = np.clip(np.round((c[:, 0] - gu[0]) / du).astype(int), 0, len(gu) - 1)
    iz = np.clip(np.round((c[:, 1] - gz[0]) / dz).astype(int), 0, len(gz) - 1)
    w = np.sqrt(np.nan_to_num(Em[iz, iu]))
    if w.sum() <= 0:
        return c[:: max(1, len(c) // n)]
    cdf = np.cumsum(w) / w.sum()
    return c[np.unique(np.searchsorted(cdf, (np.arange(n) + 0.5) / n))]


def write_vtk_seeds(path: Path, axis: int, value: float, seeds: np.ndarray) -> None:
    """Seed points (u, z) of a section as VTK polydata vertices (ParaView: StreamTracer seeds)."""
    k = len(seeds)
    xyz = np.zeros((k, 3))
    xyz[:, axis], xyz[:, 1 - axis], xyz[:, 2] = value, seeds[:, 0], seeds[:, 1]
    with open(path, "w") as f:
        f.write("# vtk DataFile Version 3.0\nfieldview field-line seeds (um)\nASCII\n"
                f"DATASET POLYDATA\nPOINTS {k} float\n")
        np.savetxt(f, xyz, fmt="%.6g")
        f.write(f"VERTICES {k} {2 * k}\n")
        np.savetxt(f, np.column_stack([np.ones(k, int), np.arange(k)]), fmt="%d")


def cross_section(run: Path, tris, sig, owner, volts, axis: int, value: float, threads: int,
                  windows: list[tuple[str, tuple[float, float, float, float]]], res: int,
                  n_seeds: int = 60) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath

    u_ax = 1 - axis
    an, un = "xy"[axis], "xy"[u_ax]
    cond_names = sorted({o for o in owner if not o.startswith("diel")})
    owner = np.array(owner)
    outlines = {n: chain(plane_segments(tris[owner == n], axis, value)) for n in cond_names}
    diel_segs = plane_segments(tris[np.char.startswith(owner, "diel")], axis, value)
    vmin = min([0.0, *volts.values()])
    vmax = max([0.0, *volts.values()])

    for tag, (u0, u1, z0, z1) in windows:
        su, sz = u1 - u0, z1 - z0
        stretch = 1.0 if su / sz <= 6 else su / sz / 3  # show flat windows at 3:1
        nu = res
        nz = max(20, int(round(res * sz * stretch / su)))
        gu, gz = np.linspace(u0, u1, nu), np.linspace(z0, z1, nz)
        U, Z = np.meshgrid(gu, gz)
        pts = np.zeros((U.size, 3))
        pts[:, axis], pts[:, u_ax], pts[:, 2] = value, U.ravel(), Z.ravel()
        print(f"[{tag}] {nu}x{nz} points on {an}={value:g} µm ...", flush=True)
        phi, E = coulomb(tris, sig, pts, threads)
        phi, Eu, Ez = phi.reshape(nz, nu), E[:, u_ax].reshape(nz, nu), E[:, 2].reshape(nz, nu)
        Eo = E[:, axis].reshape(nz, nu)  # out of the plane
        Em = np.hypot(Eu, Ez)  # in-plane magnitude
        inside = np.zeros(U.shape, bool)
        for polys in outlines.values():
            for poly in polys:
                inside |= MPath(poly).contains_points(np.column_stack([U.ravel(), Z.ravel()])).reshape(U.shape)
        phi[inside], Em[inside], Eu[inside], Ez[inside], Eo[inside] = np.nan, np.nan, 0, 0, 0
        write_vtk_section(run / f"section_{an}{value:g}_{tag}.vtk", axis, value, gu, gz,
                          phi, Eu, Eo, Ez)
        write_vtk_seeds(run / f"section_{an}{value:g}_{tag}_seeds.vtk", axis, value,
                        section_seeds(outlines, gu, gz, Em, n_seeds))
        unit, k = ("kV/mm", 1e-6) if np.nanmax(Em) > 1e6 else ("V/mm", 1e-3)
        Ek = Em * k
        ecap = np.nanpercentile(Ek, 99.5)

        fig_w = 13
        panel_h = max(2.4, min(5.5, fig_w / 2 * (sz * stretch) / su * 1.15))
        fig, axs = plt.subplots(1, 2, figsize=(fig_w, panel_h + 1.2), constrained_layout=True)
        for ax, data, cmap, lim, label in (
                (axs[0], phi, "turbo", (vmin, vmax), "potential φ (V)"),
                (axs[1], Ek, "turbo", (0, ecap), f"|E| ({unit})" + (" (clipped)" if np.nanmax(Ek) > ecap * 1.01 else ""))):
            im = ax.imshow(data, origin="lower", extent=(u0, u1, z0, z1), cmap=cmap,
                           vmin=lim[0], vmax=lim[1], aspect=stretch, interpolation="bilinear")
            fig.colorbar(im, ax=ax, label=label, shrink=0.9)
            # arrows in screen space: z component scaled like the geometry, length ~ sqrt(|E|)
            step_u = max(1, nu // 28)
            step_z = max(1, int(round(step_u * (su / nu) / (sz / nz) / stretch)))
            sl = (slice(step_z // 2, None, step_z), slice(step_u // 2, None, step_u))
            du, dz = Eu[sl], Ez[sl] * stretch
            mag = np.hypot(du, dz)
            ln = np.sqrt(np.nan_to_num(Em[sl]) / np.nanmax(Em))
            with np.errstate(invalid="ignore", divide="ignore"):
                du, dz = np.where(mag > 0, du / mag * ln, 0), np.where(mag > 0, dz / mag * ln, 0)
            ax.quiver(U[sl], Z[sl], du, dz, angles="uv", scale_units="width", scale=36,
                      width=0.0022, headwidth=4, color="k", alpha=0.75)
            for seg in diel_segs:
                ax.plot(seg[:, 0], seg[:, 1], color="0.35", lw=0.6)
            for n, polys in outlines.items():
                for poly in polys:
                    ax.fill(poly[:, 0], poly[:, 1], facecolor="white", edgecolor="black", lw=1.0)
                    if (poly[:, 0].max() - poly[:, 0].min()) > 0.15 * su:
                        cu = np.clip(poly[:, 0].mean(), u0 + 0.1 * su, u1 - 0.1 * su)
                        ax.text(cu, poly[:, 1].mean(), f"{n}  {volts.get(n, 0.0):g} V",
                                ha="center", va="center", fontsize=7, clip_on=True)
            ax.set_xlim(u0, u1)
            ax.set_ylim(z0, z1)
            ax.set_xlabel(f"{un} (µm)")
            ax.set_ylabel("z (µm)" + (f"  — exaggerated ×{stretch:.3g}" if stretch != 1 else ""))
        fig.suptitle(f"{run.name}: cross-section {an} = {value:g} µm ({tag})", fontsize=11)
        out = run / f"section_{an}{value:g}_{tag}.png"
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"wrote {out}")


def default_windows(tris, owner, axis: int, value: float):
    """Full cut through the conductors, plus a zoom (true aspect) onto the right-most edge."""
    u_ax = 1 - axis
    owner = np.array(owner)
    c = tris[~np.char.startswith(owner, "diel")].reshape(-1, 3)
    u_lo, u_hi = c[:, u_ax].min(), c[:, u_ax].max()
    z_lo, z_hi = c[:, 2].min(), c[:, 2].max()
    hz = z_hi - z_lo
    full = (u_lo - 0.08 * (u_hi - u_lo), u_hi + 0.08 * (u_hi - u_lo), z_lo - 0.6 * hz, z_hi + 0.6 * hz)
    zc = 0.5 * (z_lo + z_hi)
    w = 1.6 * hz
    edge = (u_hi - w, u_hi + w, zc - 0.65 * w, zc + 0.65 * w)
    return [("full", full), ("edge", edge)]


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run", type=Path, help="fieldsolve.py run directory (made with --charges)")
    ap.add_argument("--voltage", action="append", default=[], metavar="NAME=VOLTS",
                    help="conductor voltage; unlisted conductors are at 0 V "
                         "(default: the first conductor at 1 V)")
    ap.add_argument("--box", help="field region x0,y0,z0,x1,y1,z1 in µm "
                                  "(default: conductor bounding box + 10 %%)")
    ap.add_argument("--points", type=float, default=60000, help="approximate grid size (points)")
    ap.add_argument("--z-stretch", type=float, default=None,
                    help="HTML only: exaggerate z by this factor (default: auto for flat boards)")
    ap.add_argument("--seeds", type=int, default=60,
                    help="--plane: field-line seeds written next to each section (for ParaView)")
    ap.add_argument("--threads", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--plane", metavar="x=V|y=V",
                    help="2-D cross-section instead of the 3-D grid: plot potential and |E| with "
                         "arrows on the plane x=V or y=V (µm) as PNGs (full cut and an edge zoom)")
    ap.add_argument("--window", metavar="U0,U1,Z0,Z1",
                    help="--plane: plot only this window (µm, U = the in-plane horizontal axis)")
    ap.add_argument("--res", type=int, default=320, help="--plane: points across the window")
    ap.add_argument("--probe", action="append", default=[], metavar="X,Y,Z",
                    help="print phi and E at this point (µm); repeatable")
    args = ap.parse_args(argv)

    cols = load_run(args.run)
    names = list(cols)
    volts = {names[0]: 1.0} if not args.voltage else {}
    for v in args.voltage:
        k, x = v.split("=")
        if k not in cols:
            raise SystemExit(f"unknown conductor {k!r}; have {', '.join(names)}")
        volts[k] = float(x)
    print("voltages:", ", ".join(f"{n}={volts.get(n, 0.0):g} V" for n in names))

    # superpose the columns (identical panels in every column, as FasterCap refines once)
    tris, _, owner = cols[names[0]]
    sig = np.zeros(len(tris))
    for n, v in volts.items():
        if v:
            t, s, _ = cols[n]
            if len(t) != len(tris):
                raise SystemExit("columns have different meshes; can't superpose")
            sig += v * s
    print(f"{len(tris)} panels")

    if args.plane:
        m = re.fullmatch(r"([xy])=(-?[\d.eE+-]+)", args.plane)
        if not m:
            raise SystemExit("--plane expects x=VALUE or y=VALUE (µm)")
        axis, value = "xy".index(m[1]), float(m[2])
        if args.window:
            windows = [("window", tuple(float(v) for v in args.window.split(",")))]
        else:
            windows = default_windows(tris, owner, axis, value)
        cross_section(args.run, tris, sig, owner, volts, axis, value, args.threads, windows, args.res,
                      args.seeds)
        return

    cond = np.array([not o.startswith("diel") for o in owner])
    ctris = tris[cond]
    lo, hi = ctris.reshape(-1, 3).min(0), ctris.reshape(-1, 3).max(0)
    if args.box:
        b = [float(x) for x in args.box.split(",")]
        lo, hi = np.array(b[:3]), np.array(b[3:])
    else:
        pad = 0.1 * (hi - lo)
        pad[2] = max(pad[2], 0.5 * (hi[2] - lo[2]))
        lo, hi = lo - pad, hi + pad
    ext = hi - lo
    # spacing: roughly cubic cells, but at least 24 points across the thinnest dimension
    h = (np.prod(ext) / args.points) ** (1 / 3)
    h = min(h, ext[2] / 24)
    dims = np.maximum(np.round(ext / h).astype(int) + 1, 2)
    if np.prod(dims) > 4 * args.points:  # flat boards: keep x/y resolution bounded
        sxy = math.sqrt(args.points / dims[2] / (ext[0] * ext[1]))
        dims[:2] = np.maximum(np.round(ext[:2] * sxy).astype(int) + 1, 2)
    spacing = ext / (dims - 1)
    print(f"grid {dims[0]}x{dims[1]}x{dims[2]} = {np.prod(dims)} points, "
          f"spacing {spacing[0]:.3g},{spacing[1]:.3g},{spacing[2]:.3g} µm")


    gx, gy, gz = (lo[i] + spacing[i] * np.arange(dims[i]) for i in range(3))
    Z, Y, X = np.meshgrid(gz, gy, gx, indexing="ij")  # VTK order: x fastest
    pts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    phi, E = coulomb(tris, sig, pts, args.threads)

    write_vtk_grid(args.run / "field.vtk", lo, spacing, dims, phi, E)
    write_vtk_panels(args.run / "panels.vtk", tris, sig, owner)

    for p in args.probe:
        r = np.array([[float(x) for x in p.split(",")]])
        ph, e = coulomb(tris, sig, r, 1)
        print(f"probe ({p}) µm: phi={ph[0]:.4g} V  E=({e[0, 0]:.4g}, {e[0, 1]:.4g}, {e[0, 2]:.4g}) V/m"
              f"  |E|={np.linalg.norm(e[0]):.4g} V/m")

    # HTML page: copper, dielectric slabs, |E| on cut planes, field lines in the xz cut
    Em = np.linalg.norm(E, axis=1).reshape(dims[2], dims[1], dims[0])
    scale, unit = (1e-6, "V/µm") if np.nanpercentile(Em, 99) > 1e5 else (1e-3, "V/mm")
    Ek = Em * scale
    zs = args.z_stretch or max(1.0, min(20.0, 0.25 * max(ext[0], ext[1]) / ext[2]))
    ix, iy, iz = dims[0] // 2, dims[1] // 2, dims[2] // 2
    planes = [
        (f"xz cut, y={gy[iy]:.0f} µm", X[:, iy, :], Y[:, iy, :], Z[:, iy, :], Ek[:, iy, :], True),
        (f"yz cut, x={gx[ix]:.0f} µm", X[:, :, ix], Y[:, :, ix], Z[:, :, ix], Ek[:, :, ix], False),
        (f"xy cut, z={gz[iz]:.1f} µm", X[iz], Y[iz], Z[iz], Ek[iz], False),
    ]
    ownr = np.array(owner)
    conductors = [(f"{n} ({volts.get(n, 0.0):g} V)", tris[ownr == n])
                  for n in sorted({o for o in owner if not o.startswith("diel")})]
    dielectrics = []
    for key in sorted({o for o in owner if o.startswith("diel:")}):
        _, k1, k2 = key.split(":")
        dielectrics.append((max(float(k1), float(k2)), tris[ownr == key]))
    info = ("|E| on the xz cut; "
            + ", ".join(f"{n}={volts.get(n, 0.0):g} V" for n in names)
            + (f"; z stretched ×{zs:.3g}" if zs != 1 else ""))
    try:
        write_html(args.run / "field.html", args.run.name, info, zs, unit, scale,
                   conductors, dielectrics, planes)
        html = f", {args.run / 'field.html'}"
    except ImportError:
        html = " (install plotly for field.html)"
    print(f"wrote {args.run / 'field.vtk'}, {args.run / 'panels.vtk'}{html}")


if __name__ == "__main__":
    main()
