"""Turn strip-shaped copper (signal routes drawn as polygons) into traces: centreline + width.

GDS layouts, and KiCad boards made from them (layz.gds2pcb), carry every route as a filled polygon.
HyperLynx BoardSim only builds transmission lines, coupling and loss from traces (SEG/ARC), so a
net drawn as pours has no length for it: no delay, no loss, no crosstalk. This module recovers the
traces of strip-shaped copper:

    strip test   a strip of width w and length L has area A = wL and perimeter P ~ 2L, so
                 w ~ 2A/P; eroding it by a little over w/2 removes it, a wide area survives
    centreline   the medial axis: the Voronoi edges of the densified outline that lie well
                 inside the polygon, merged into lines, spurs pruned, then simplified
    ends         extended to the strip's ends and snapped to the net's vias/pins nearby

Everything works in one length unit (whatever the caller's coordinates are in).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, unary_union

# blobs (pads, via landings) are what survives an opening by OPEN x the strip width: more than a
# right-angle corner of the strip (its largest inscribed circle has radius 0.586 w)
OPEN = 0.7
MIN_ASPECT = 4.0  # a strip is at least this many widths long (a plane is not a route)


@dataclass(frozen=True)
class Seg:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float


def rect_width(area: float, perimeter: float) -> float:
    """The short side of the rectangle with this area and perimeter (A = wL, P = 2(w + L)); for a
    long strip ~2A/P, but right for short ones too. 2A/P where no rectangle fits."""
    h = perimeter / 2
    disc = h * h - 4 * area
    return (h - disc**0.5) / 2 if disc > 0 else 2 * area / perimeter


def strip_width(poly: Polygon, erode: float = 0.6, keep: float = 0.1) -> float | None:
    """The strip's width if ``poly`` is a strip (eroding by ``erode`` x width leaves less than
    ``keep`` of its area), else None."""
    a, p = poly.area, poly.length
    if a <= 0 or p <= 0:
        return None
    w = rect_width(a, p)
    if a / w < MIN_ASPECT * w:
        return None
    return w if poly.buffer(-erode * w).area < keep * a else None


def _medial_axis(poly: Polygon, w: float) -> list[LineString]:
    step = w / 4
    outline = shapely.segmentize(poly.boundary, step)
    pts = shapely.get_coordinates(outline)
    if len(pts) < 4:
        return []
    # break the symmetry of evenly sampled straight edges (co-circular points give degenerate,
    # zig-zagging Voronoi edges): a fixed jitter far below any feature size
    pts = pts + np.random.default_rng(0).uniform(-1e-3 * w, 1e-3 * w, pts.shape)
    edges = shapely.voronoi_polygons(shapely.MultiPoint(pts), only_edges=True)
    core = poly.buffer(-0.3 * w)  # the axis lies w/2 from both sides: keep edges deep inside
    if core.is_empty:
        return []
    inside = [e for e in shapely.get_parts(edges) if core.contains(e)]
    merged = linemerge(unary_union(inside)) if inside else None
    if merged is None or merged.is_empty:
        return []
    lines = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
    return lines


def _prune(lines: list[LineString], w: float) -> list[LineString]:
    """Drop spurs: lines with a free end shorter than ~2 widths (corner artefacts)."""
    for _ in range(5):
        ends = [tuple(np.round(c, 9)) for l in lines for c in (l.coords[0], l.coords[-1])]
        count = {e: ends.count(e) for e in ends}
        keep = []
        changed = False
        for l in lines:
            a, b = tuple(np.round(l.coords[0], 9)), tuple(np.round(l.coords[-1], 9))
            free = count[a] == 1 or count[b] == 1
            if free and l.length < 2 * w and len(lines) > 1:
                changed = True
                continue
            keep.append(l)
        merged = linemerge(keep)
        lines = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
        if not changed:
            break
    return lines


def _extend(line: LineString, poly: Polygon, anchors: list[Point], w: float, reach: float = 1.5, blobs: list[tuple[Polygon, Point]] = ()) -> LineString:
    """Extend both free ends: on to an anchor (via/pin, or a blob's middle) within ``reach``
    widths, as one more vertex (a short dog-leg into the via, the route's own shape kept), else
    along their last direction to the copper's edge. A tip at a blob (pad, via landing) always
    runs on to that blob's target (its via/pin, or its middle), however far."""
    coords = list(line.coords)
    first, last = [], []
    for end in (0, -1):
        tip = np.array(coords[end])
        prev = np.array(coords[1] if end == 0 else coords[-2])
        d = tip - prev
        n = np.linalg.norm(d)
        if n == 0:
            continue
        d /= n
        at_blob = [(b, t) for b, t in blobs if b.distance(Point(tip)) < 0.6 * w]
        if at_blob:
            t = min(at_blob, key=lambda bt: bt[0].distance(Point(tip)))[1]
            if t.distance(Point(tip)) > 1e-3 * w:
                (first if end == 0 else last).append((t.x, t.y))
            continue
        near = [a for a in anchors if a.distance(Point(tip)) < reach * w]
        if near:
            a = min(near, key=lambda q: q.distance(Point(tip)))
            if a.distance(Point(tip)) > 1e-3 * w:
                (first if end == 0 else last).append((a.x, a.y))
            continue
        # run on to the copper's edge (the axis stops ~w/2 short of a square end)
        ray = LineString([tip, tip + d * 2 * w]).intersection(poly)
        if ray.geom_type == "MultiLineString":
            ray = ray.geoms[0]
        if isinstance(ray, LineString) and not ray.is_empty:
            coords[end] = tuple(ray.coords[-1])
    return LineString(first + coords + last)


def _width(poly: Polygon) -> float:
    """The strip width of a route that may carry pad-like blobs: 2A/P, recomputed without the
    blobs that an opening at that width finds (twice is enough)."""
    w = rect_width(poly.area, poly.length)
    for _ in range(2):
        blobs = poly.buffer(-OPEN * w).buffer(OPEN * w)
        core = poly.difference(blobs)
        if core.is_empty or core.length == 0:
            break
        w = rect_width(core.area, core.length - core.intersection(blobs.boundary).length)
    return w


REJECTED: list[str] = []  # why the last split_route calls gave None (for warnings and debugging)


def _reject(why: str) -> None:
    REJECTED.append(why)


def split_route(poly: Polygon, anchors: list[Point] | None = None, simplify: float = 0.15) -> tuple[list[Seg], list[Polygon]] | None:
    """A route polygon as traces: (segments along the strip parts, the pad-like blobs left over).

    Blobs are what survives an opening (erode then dilate) at ~the strip width: pads and via
    landings. The strip parts between them become centreline segments as wide as the strip,
    their ends run into the blobs (to a via/pin inside one, or its middle). A blob holding a
    via/pin is dropped (its padstack models it); other blobs stay as copper. None: not a route
    (too little of it is strip, or the centreline would not cover it)."""
    anchors = anchors or []
    w = _width(poly)
    if not w > 0:
        return _reject("no width")
    blobs = poly.buffer(-OPEN * w).buffer(OPEN * w).intersection(poly)
    core = poly.difference(blobs.buffer(1e-3 * w))
    if core.is_empty or core.area < 0.5 * poly.area:
        return _reject(f"mostly pad-like ({0 if core.is_empty else core.area / poly.area:.0%} strip)")
    blob_parts = [b for b in getattr(blobs, "geoms", [blobs]) if isinstance(b, Polygon) and b.area > 0]
    targets = list(anchors)
    blob_targets = []  # each blob's target: the via/pin nearest its middle, else its middle
    for b in blob_parts:
        inside = [a for a in anchors if b.buffer(0.5 * w).contains(a)]
        mid = b.representative_point()
        blob_targets.append((b, min(inside, key=mid.distance) if inside else mid))
    segs: list[Seg] = []
    strips, odd = [], 0.0
    for piece in getattr(core, "geoms", [core]):
        if not isinstance(piece, Polygon):
            continue
        pw = strip_width(piece)
        if pw is None or piece.area < 0.5 * w * w:
            odd += piece.area  # slivers the opening leaves at blob edges
            continue
        strips.append((piece, pw))
    if odd > 0.15 * core.area:
        return _reject(f"non-strip pieces {odd / core.area:.0%} of the route")
    for piece, pw in strips:
        lines = _prune(_medial_axis(piece, pw), pw)
        for line in lines:
            line = _extend(line.simplify(simplify * pw, preserve_topology=False), piece.union(blobs).buffer(0), targets, max(pw, 0.5 * w), reach=4.0, blobs=blob_targets)
            c = list(line.coords)
            segs += [Seg(*c[i], *c[i + 1], pw) for i in range(len(c) - 1) if c[i] != c[i + 1]]
    if not segs:
        return _reject("no centreline")
    # a dropped landing with several vias/pins: tie the others to the one the trace runs into
    for b, t in blob_targets:
        for a in anchors:
            if a is not t and b.buffer(0.5 * w).contains(a) and a.distance(t) > 1e-3 * w:
                segs.append(Seg(t.x, t.y, a.x, a.y, w))
    covered = unary_union([LineString([(s.x1, s.y1), (s.x2, s.y2)]).buffer(s.width / 2, cap_style="square") for s in segs])
    strip_area = sum(p.area for p, _ in strips)
    cover = covered.intersection(core).area / strip_area
    if cover < 0.8:
        return _reject(f"centreline covers {cover:.0%} of the strip")
    keep = [b for b in blob_parts if not any(b.buffer(0.5 * w).contains(a) for a in anchors)]
    return segs, keep
