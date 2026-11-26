"""The voltage drop at every place of a DC run's copper, from HyperLynx's own results.

HyperLynx exports no voltage map, but its loss map (plots.current_density) gives the current
density J in every cell, so the field there: |grad V| = rho·J. The drop from the VRM to a place is
the integral of grad V along the current's path, which runs from the VRM to every place (DC, sinks
only); along any other path the integral of |grad V| is larger. So the drop at a cell is the
shortest path from the VRM's pins to it, with rho·J·length as each step's length, over the cells
of its own net, and each via's own drop (HyperLynx's) between layers. The sink pins' drops, against
the voltages HyperLynx reports at them, check it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from layz.hyperlynx import plots


def drop_map(run: Path) -> dict:
    """{"nets": [...], "extent": [x0, x1, y0, y1] mm, "layers": {layer: {"drop": V per cell (nan:
    no copper carrying current), "J": A/m², "net": index into nets (-1 none)}}, "check": the sink
    pins' drops against HyperLynx's}. A supply run's drop is from its VRM's voltage down; a return
    run's (the VRM at the old reference pins), the rise from the VRM's reference up."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    from layz.hyperlynx import copper
    from layz.web import board as boardfile

    hyp = next((run / "board").glob("*.hyp"))
    solved = set(json.loads((run / "summary.json").read_text())["nets"])
    vrms_all = json.loads((run / "vrms.json").read_text())
    vrms = [v for v in vrms_all if v["power_net"] in solved]
    names = sorted(solved)
    cu = copper.read(hyp, set(names))
    names = sorted(cu)  # those with copper, the order copper.assign counts in
    dens = plots.current_density(run)
    layers = list(dens)
    ext = dens[layers[0]][2]
    ny, nx = dens[layers[0]][0].shape
    dx, dy = (ext[1] - ext[0]) / nx * 1e-3, (ext[3] - ext[2]) / ny * 1e-3  # m

    # each cell carrying current: a node, on its net (the nearest net's copper on that layer)
    owner, grad, ids = {}, {}, {}
    count = 0
    for lay in layers:
        J, rho, _ = dens[lay]
        own = np.full(J.shape, -1, dtype=int)
        k = np.isfinite(J) & (J > 0)
        if k.any():
            iy, ix = np.nonzero(k)
            x = (ext[0] + (ix + 0.5) * (ext[1] - ext[0]) / nx) / plots.IN
            y = (ext[2] + (iy + 0.5) * (ext[3] - ext[2]) / ny) / plots.IN
            own[k] = copper.assign(cu, lay, x, y)
        owner[lay], grad[lay] = own, np.where(own >= 0, rho * np.nan_to_num(J), np.nan)  # V/m
        idx = np.full(J.shape, -1, dtype=int)
        n = int((own >= 0).sum())
        idx[own >= 0] = np.arange(count, count + n)
        ids[lay], count = idx, count + n

    rows, cols, w = [], [], []

    def link(a, b, weight):
        rows.append(a); cols.append(b); w.append(weight)

    for lay in layers:  # neighbours on one layer and net: half each cell's field times the step
        own, g, idx = owner[lay], grad[lay], ids[lay]
        for (sy, sx), step in (((0, 1), dx), ((1, 0), dy)):
            a = (slice(0, ny - sy), slice(0, nx - sx))
            b = (slice(sy, ny), slice(sx, nx))
            same = (own[a] >= 0) & (own[a] == own[b])
            link(idx[a][same], idx[b][same], 0.5 * (g[a][same] + g[b][same]) * step + 1e-12)

    def node(lay: str, x_mm: float, y_mm: float, net: int, reach: int = 3) -> int:
        """The node of ``net`` on ``lay`` nearest (x, y), within ``reach`` cells; -1 if none."""
        if lay not in ids:
            return -1
        ix, iy = int((x_mm - ext[0]) / (ext[1] - ext[0]) * nx), int((y_mm - ext[2]) / (ext[3] - ext[2]) * ny)
        best, far = -1, 1e9
        for jy in range(max(0, iy - reach), min(ny, iy + reach + 1)):
            for jx in range(max(0, ix - reach), min(nx, ix + reach + 1)):
                if owner[lay][jy, jx] == net and (d := (jx - ix) ** 2 + (jy - iy) ** 2) < far:
                    best, far = ids[lay][jy, jx], d
        return best

    net_of = {n: i for i, n in enumerate(names)}
    for v in plots._rows(run / "vias.csv"):  # vias: their own drop, between the layers they join
        if v["net"] in net_of and v["x1"]:
            a = node(v["layer1"], float(v["x1"]) * 1e3, float(v["y1"]) * 1e3, net_of[v["net"]])
            b = node(v["layer2"], float(v["x2"] or v["x1"]) * 1e3, float(v["y2"] or v["y1"]) * 1e3, net_of[v["net"]])
            if a >= 0 and b >= 0:
                link(np.array([a]), np.array([b]), np.array([abs(float(v["drop_V"])) + 1e-12]))

    b = boardfile.read(hyp)
    pin_layer = {p["ref"]: p["layer"] for p in b["pins"]}
    ports = {p["pin"]: p for p in plots._rows(run / "ports.csv")}

    def pin_node(pin: str, net: str) -> int:
        p = ports.get(pin)
        if p is None or not p["x"] or net not in net_of:
            return -1
        x, y = float(p["x"]) * 1e3, float(p["y"]) * 1e3
        # its pad's layer first; a pad on a layer without its net's copper (a top pad): the copper under it
        order = ([pin_layer[pin]] if pin in pin_layer else []) + [lay for lay in layers if lay != pin_layer.get(pin)]
        return next((n for lay in order if (n := node(lay, x, y, net_of[net])) >= 0), -1)

    # the VRM's pins: its power pins on a supply run; on a return run (layz's runner/dc.py moves the
    # VRM to the old reference pins) its reference pins
    src_pins = [(p, v["power_net"]) for v in vrms for p in v["power_pins"]] + [(p, v["ref_net"]) for v in vrms_all if v["ref_net"] in solved for p in v["ref_pins"]]
    sources = [n for p, net in src_pins if (n := pin_node(p, net)) >= 0]
    v_src = {net: float(ports[p]["voltage_V"]) for p, net in src_pins if p in ports}
    graph = coo_matrix((np.concatenate(w), (np.concatenate(rows), np.concatenate(cols))), shape=(count, count)).tocsr() if rows else None
    dist = dijkstra(graph, directed=False, indices=sources, min_only=True) if graph is not None and sources else np.full(count, np.nan)
    dist[~np.isfinite(dist)] = np.nan  # copper the VRM doesn't reach (HyperLynx's: none, a split net)

    # the check: each sink pin's drop here, against its voltage's distance from the VRM pin's
    # (HyperLynx's both)
    vrm_pins = {p for p, _ in src_pins}
    errs = []
    for pin, p in ports.items():
        if p["net"] in v_src and pin not in vrm_pins and abs(float(p["current_A"])) > 0:
            n = pin_node(pin, p["net"])
            if n >= 0 and np.isfinite(dist[n]):
                errs.append((abs(v_src[p["net"]] - float(p["voltage_V"])), float(dist[n]), pin))
    e = np.array([x[:2] for x in errs]) if errs else np.zeros((0, 2))
    check = {"pins": len(e), "max_error_mV": float(np.abs(e[:, 1] - e[:, 0]).max() * 1e3) if len(e) else None, "max_drop_mV": float(e[:, 0].max() * 1e3) if len(e) else None}

    out = {}
    for lay in layers:
        D = np.full((ny, nx), np.nan)
        k = ids[lay] >= 0
        D[k] = dist[ids[lay][k]]
        out[lay] = {"drop": D, "J": np.where(owner[lay] >= 0, dens[lay][0], np.nan), "net": owner[lay]}
    return {"nets": names, "extent": ext, "layers": out, "check": check, "pins": errs}
