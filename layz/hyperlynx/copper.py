"""The copper of a board's nets, from its .hyp: pours (POLYGON, less their POLYVOIDs) and traces
(SEG, as wide as their W), per net and layer, in inches, as shapely geometry. Used to tell which
net a cell of HyperLynx's loss map belongs to (a DC run solves several nets at once).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

_NUM = re.compile(r"\b(X|Y|X1|Y1|X2|Y2|W)=([-\d.eE+]+)")
_LAYER = re.compile(r'L="([^"]*)"')
_ID = re.compile(r"\bID=(\d+)")


def read(hyp: Path, nets: set[str] | None = None) -> dict[str, dict[str, shapely.Geometry]]:
    """{net: {layer: copper}} of the named nets (all nets if None)."""
    lines = Path(hyp).read_text(errors="replace").splitlines()
    pours: dict[tuple[str, str, str], list] = {}  # (net, layer, id) -> [outline, voids...]
    segs: dict[tuple[str, str], list] = {}
    net, i = None, 0
    while i < len(lines):
        s = lines[i].strip()
        if lines[i].startswith("{NET="):
            net = lines[i].split('"')[1]
        elif lines[i].startswith("}"):
            net = None
        elif net is not None and (nets is None or net in nets):
            if s.startswith(("{POLYGON", "{POLYVOID")):
                layer = _LAYER.search(s)
                pid = _ID.search(s)
                pts, i = [], i + 1
                while not lines[i].strip().startswith("}"):
                    v = dict(_NUM.findall(lines[i]))
                    if "X" in v:
                        pts.append((float(v["X"]), float(v["Y"])))
                    elif "X2" in v:  # an arc: its end point (the outline stays closed)
                        pts.append((float(v["X2"]), float(v["Y2"])))
                    i += 1
                if len(pts) >= 3:
                    key = (net, layer.group(1) if layer else "", pid.group(1) if pid else str(i))
                    poly = Polygon(pts).buffer(0)
                    if s.startswith("{POLYGON"):
                        pours.setdefault(key, []).insert(0, poly)
                    else:  # a void of the pour with its ID; its layer is the pour's
                        for k in pours:
                            if k[0] == net and k[2] == key[2]:
                                pours[k].append(poly)
            elif s.startswith("(SEG"):
                v = dict(_NUM.findall(s))
                layer = _LAYER.search(s)
                line = LineString([(float(v["X1"]), float(v["Y1"])), (float(v["X2"]), float(v["Y2"]))])
                segs.setdefault((net, layer.group(1) if layer else ""), []).append(line.buffer(float(v["W"]) / 2))
        i += 1
    out: dict[str, dict[str, list]] = {}
    for (n, lay, _), parts in pours.items():
        out.setdefault(n, {}).setdefault(lay, []).append(parts[0].difference(unary_union(parts[1:])) if len(parts) > 1 else parts[0])
    for (n, lay), parts in segs.items():
        out.setdefault(n, {}).setdefault(lay, []).extend(parts)
    return {n: {lay: unary_union(g) for lay, g in by.items()} for n, by in out.items()}


def assign(copper: dict[str, dict[str, shapely.Geometry]], layer: str, x_in: np.ndarray, y_in: np.ndarray) -> np.ndarray:
    """The net (index into sorted(copper)) nearest to each point (inches) on ``layer``; -1 where
    no net has copper on that layer."""
    names = sorted(copper)
    dist = np.full((len(names), len(x_in)), np.inf)
    pts = shapely.points(x_in, y_in)
    for k, n in enumerate(names):
        g = copper[n].get(layer)
        if g is not None and not g.is_empty:
            dist[k] = shapely.distance(g, pts)
    best = np.argmin(dist, axis=0)
    best[~np.isfinite(dist.min(axis=0))] = -1
    return best


def pins(hyp: Path) -> dict[str, list[tuple[str, float, float]]]:
    """{net: [(pin, x, y)]} of a .hyp, in inches."""
    out: dict[str, list] = {}
    net = None
    for line in Path(hyp).read_text(errors="replace").splitlines():
        if line.startswith("{NET="):
            net = line.split('"')[1]
        elif line.startswith("}"):
            net = None
        elif net is not None and line.strip().startswith("(PIN"):
            v = dict(re.findall(r'\b(X|Y|R)=("[^"]*"|[-\w.]+)', line))
            out.setdefault(net, []).append((v["R"].strip('"'), float(v["X"]), float(v["Y"])))
    return out
