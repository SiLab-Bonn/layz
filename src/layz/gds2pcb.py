#!/usr/bin/env python3
"""Prototype GDS -> KiCad .kicad_pcb converter, v3.

v3 process mapping (4 copper layers):

    GDS 68/0 -> B.Cu      (also the back-side footprint pad layer)
    GDS 3/0  -> In2.Cu
    GDS 6/0  -> In1.Cu
    GDS 8/0  -> F.Cu      (also the front-side footprint pad layer)
    GDS 7/0  -> blind via F.Cu <-> In1.Cu
    GDS 2/0  -> blind via B.Cu <-> In2.Cu   (baseline pair, new copper names)
    GDS 4/0  -> blind via In2.Cu <-> F.Cu   (baseline pair, new copper names)
    GDS 70/0 -> Edge.Cuts board outline (closed loops of segments)

v3 additions compared to gds2pcb_v2.py:
- Degenerate (zero-area) GDS shapes are ignored. Some cells carry zero-length
  line segments / point markers (e.g. the point at the cell origin on layer
  4/0 in the Bond_Pad_via cell); KLayout flattens them into zero-area
  "polygons", which v2 turned into size-0 / drill-0 phantom vias (186 of
  them at x=-5.57 mm in this design). Shapes with a zero-width or zero-height
  bounding box are now skipped and counted in "skipped shapes".

v2 additions compared to gds2pcb.py:
- GDS cells become KiCad footprints. A cell containing 8/0 geometry becomes a
  front-side footprint (pads on F.Cu); a cell containing 68/0 geometry becomes
  a back-side footprint (pads on B.Cu). The footprint is defined once per
  (cell, rotation, mirror state) and each top-level instance places a copy
  of the matching variant.
- Instance rotation and mirroring are handled through the KiCad placement
  (at + angle) plus per-variant pad geometry, not by re-baking pad
  coordinates. KiCad 10 rotates the pad POSITIONS with the footprint angle
  but keeps the pad (size w h) axis-aligned to the board (verified against
  KiCad 10.0.6 gerber/SVG export), so each rotation variant carries the
  rotated pad width/height (a 90-degree pad swaps w and h).
- Y-flip is ON by default: GDS is y-up, the KiCad board file is y-down (top
  view), so a GDS design and the resulting .kicad_pcb render the same
  top-view orientation. Use --no-flip-y to restore the v1 raw mapping.

Coordinate conventions (empirically verified against KiCad 10 drill/SVG exports):
- KiCad board file: x right, y DOWN.  GDS/KLayout: x right, y UP.
- KiCad footprint placement:  board_pad = at + R_cw(angle) * pad_local,
  identical for front- and back-side footprints (a B.Cu footprint only changes
  which side the copper is drawn on, not the pad board positions).
  => GDS point (x, y)  ->  file point (x*s, (y_ref - y)*s), angle = 90 * rot.
- KLayout mirror (Trans.is_mirror()) reflects y in GDS space. A mirrored
  instance is expressed by a mirrored footprint variant (pad local y sign
  flipped) placed at the same (at, angle).

Notes:
- Pads are rectangles from each GDS shape's bounding box (center + w/h),
  sufficient for the rectangular pad shapes in this design.
- Pads carry only their copper layer (no paste/mask entries); mask openings
  come from the separate GDS layers, as in v1.
- A single net is assigned to everything (prototype-level, as in v1).
"""

from __future__ import annotations

import argparse
import math
import re
import uuid
from collections import defaultdict
from pathlib import Path

import klayout.db as db
from pycbnew.primitives.kicad import KiCadObject
from pycbnew.primitives.net import KNet
from pycbnew.primitives.project import KProject
from pycbnew.primitives.segment import KSegment
from pycbnew.primitives.sexpressions import fnum, sexp_layers, sexp_xy
from pycbnew.primitives.via import KVia
from pycbnew.primitives.zone import KZone
from pycbnew.utils.geometry import Point

# GDS layer keys for the footprint pad layers.
FRONT_PAD_LAYER = (8, 0)   # -> F.Cu pads
BACK_PAD_LAYER = (68, 0)   # -> B.Cu pads

# GDS layer carrying the board outline (closed polygons/paths -> Edge.Cuts).
BOARD_OUTLINE_LAYER = (70, 0)
OUTLINE_WIDTH_MM = 0.1

# Physical/process defaults (overridable via --layer-map / --via-map).
DEFAULT_POLYGON_LAYER_MAP: dict[tuple[int, int], str] = {
    (68, 0): "B.Cu",
    (3, 0): "In2.Cu",
    (6, 0): "In1.Cu",
}

DEFAULT_VIA_LAYER_MAP: dict[tuple[int, int], tuple[str, str]] = {
    (7, 0): ("F.Cu", "In1.Cu"),   # blind vias under the F.Cu pads
    (2, 0): ("B.Cu", "In2.Cu"),
    (4, 0): ("In2.Cu", "In1.Cu"),
}


class KFilledZone(KZone):
    """KiCad zone with cached filled geometry identical to the outline (from v1).

    pycbnew's stock KZone does not emit the cached `(filled_polygon ...)` data
    that KiCad/HYP export relies on, so we write the fill explicitly.
    """

    def __init__(self, *, net: KNet, layer: str, points: list[Point], priority: int = 0):
        super().__init__(
            net=net,
            layer=layer,
            points=points,
            hatch_type="none",
            hatch_size=0.5,
            clearance=0,
            min_thickness=0,
            thermal_gap=0.5,
            thermal_bridge_width=0.5,
            priority=priority,
            connect_pads=KZone.ConnectPads.Solid,
        )

    def sexp_tree(self) -> list[list | str]:
        pts = [sexp_xy(pt) for pt in self.points]
        return [
            "zone",
            ["net", f"{self.net.number}"],
            ["net_name", f'"{self.net.name}"'],
            ["layer", f'"{self.layer}"'],
            ["uuid", f'"{self.uuid}"'],
            ["hatch", self.hatch_type, fnum(self.hatch_size)],
            ["priority", f"{self.priority}"],
            ["connect_pads", ["clearance", fnum(self.clearance)]],
            ["min_thickness", fnum(self.min_thickness)],
            [
                "fill",
                "yes",
                ["thermal_gap", fnum(self.thermal_gap)],
                ["thermal_bridge_width", fnum(self.thermal_bridge_width)],
                ["island_removal_mode", "0"],
            ],
            ["polygon", ["pts"] + pts],
            ["filled_polygon", ["layer", f'"{self.layer}"'], ["pts"] + pts],
        ]


class KFootprintBlock(KiCadObject):
    """One `(footprint ...)` element for a single GDS-cell instance.

    Emits raw S-expressions so pad placement is fully under our control:
    local pad coordinates already include the GDS->KiCad y flip (and the
    mirror flip for the mirrored variant); the instance transform is carried
    by `(at x y angle)` only, which KiCad interprets as
    board_pad = at + R_cw(angle) * pad_local for both F.Cu and B.Cu.

    Note: KiCad rotates pad positions with the footprint angle but keeps the
    pad (size w h) axis-aligned to the board, so the pad sizes passed in are
    already the board-axis sizes for this variant's rotation (see
    rotated_pad_size).
    """

    def __init__(
        self,
        name: str,
        at: Point,
        angle: float,
        layer: str,
        ref: str,
        value: str,
        pads: list[tuple[str, Point, tuple[float, float]]],
        net: KNet,
    ):
        super().__init__()
        self.name = name
        self.at = at
        self.angle = angle
        self.layer = layer
        self.ref = ref
        self.value = value
        self.pads = pads  # (pad id, local Point, (w, h))
        self.net = net

    def sexp_tree(self) -> list[list | str]:
        back = self.layer == "B.Cu"
        silk = "B.SilkS" if back else "F.SilkS"
        effects = ["effects", ["font", ["size", "1", "1"], ["thickness", "0.15"]]]
        if back:
            effects.append(["justify", "mirror"])

        ret: list[list | str] = [
            "footprint",
            f'"{self.name}"',
            ["layer", f'"{self.layer}"'],
            ["at", fnum(self.at.x), fnum(self.at.y), fnum(self.angle)],
            ["uuid", f'"{self.uuid}"'],
            ["descr", f'"GDS cell {self.name}"'],
            ["tedit", f'"{uuid.uuid4().hex[:16]}"'],
            ["property", "Reference", f'"{self.ref}"',
             ["at", "0", "0"], ["layer", f'"{silk}"'], effects],
            ["property", "Value", f'"{self.value}"',
             ["at", "0", "-1"], ["layer", '"F.Fab"' if not back else '"B.Fab"'], effects],
        ]
        for pad_id, local, (w, h) in self.pads:
            ret.append([
                "pad",
                f'"{pad_id}"',
                "smd",
                "rect",
                ["net", f"{self.net.number}", f'"{self.net.name}"'],
                ["at", fnum(local.x), fnum(local.y)],
                ["size", fnum(w), fnum(h)],
                sexp_layers([self.layer]),
            ])
        return ret


# KiCad layer numbering that accepts this 4-copper stack with vias (same as v1).
KICAD_LAYER_BLOCK = """    (layers
        (0 "F.Cu" signal)
        (4 "In1.Cu" signal)
        (6 "In2.Cu" signal)
        (2 "B.Cu" signal)
        (9 "F.Adhes" user "F.Adhesive")
        (11 "B.Adhes" user "B.Adhesive")
        (13 "F.Paste" user)
        (15 "B.Paste" user)
        (5 "F.SilkS" user "F.Silkscreen")
        (7 "B.SilkS" user "B.Silkscreen")
        (1 "F.Mask" user)
        (3 "B.Mask" user)
        (17 "Dwgs.User" user "User.Drawings")
        (19 "Cmts.User" user "User.Comments")
        (21 "Eco1.User" user "Eco1.User")
        (23 "Eco2.User" user "Eco2.User")
        (25 "Edge.Cuts" user)
        (27 "Margin" user)
        (31 "F.CrtYd" user "F.Courtyard")
        (29 "B.CrtYd" user "B.Courtyard")
        (35 "F.Fab" user)
        (33 "B.Fab" user)
        (39 "User.1" user)
        (41 "User.2" user)
        (43 "User.3" user)
        (45 "User.4" user)
    )
"""


def parse_layer_map(items: list[str]) -> dict[tuple[int, int], str]:
    """Parse entries like `3/0=F.Cu`."""
    result: dict[tuple[int, int], str] = {}
    for item in items:
        lhs, rhs = item.split("=", 1)
        result[_parse_gds_layer_key(lhs)] = rhs
    return result


def parse_via_map(items: list[str]) -> dict[tuple[int, int], tuple[str, str]]:
    """Parse entries like `7/0=F.Cu,In1.Cu`."""
    result: dict[tuple[int, int], tuple[str, str]] = {}
    for item in items:
        lhs, rhs = item.split("=", 1)
        layers = tuple(part.strip() for part in rhs.split(","))
        if len(layers) != 2:
            raise ValueError(f"via map must have exactly two KiCad layers: {item}")
        result[_parse_gds_layer_key(lhs)] = (layers[0], layers[1])
    return result


def _parse_gds_layer_key(text: str) -> tuple[int, int]:
    if "/" in text:
        layer_s, datatype_s = text.split("/", 1)
        return (int(layer_s), int(datatype_s))
    return (int(text), 0)


def sanitize_fp_name(text: str) -> str:
    """Make a string safe for use as a KiCad footprint name."""
    return re.sub(r"[^A-Za-z0-9._:-]", "_", text)


def parse_trans_translation(trans: db.Trans) -> tuple[float, float]:
    """Extract the (x, y) translation part of a KLayout Trans.

    This binding does not expose trans.x/trans.y, but trans.to_s() gives the
    canonical string, e.g. 'r0 120,60' / 'r90m0 1485,570'; the last token is
    the 'x,y' translation in DB units.
    """
    parts = trans.to_s().split()
    x, y = parts[-1].split(",")
    return float(x), float(y)


def to_file_point(x_db: float, y_db: float, scale: float, flip_y: bool, y_ref_db: float) -> Point:
    """Map a GDS top-level DB point to KiCad file coordinates (mm).

    GDS is y-up, KiCad board file is y-down: with flip_y (default) the top of
    the GDS bbox maps to file y=0 and GDS +y maps to file -y.
    """
    y_db = y_ref_db - y_db if flip_y else y_db
    return Point(x_db * scale, y_db * scale)


def dpolygon_to_points(poly: db.DPolygon, scale: float, flip_y: bool, y_ref_db: float) -> list[Point]:
    pts = [to_file_point(p.x, p.y, scale, flip_y, y_ref_db) for p in poly.each_point_hull()]
    # KiCad polygon point lists are implicitly closed; do not repeat the first point.
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def via_from_dpolygon(
    poly: db.DPolygon,
    scale: float,
    flip_y: bool,
    y_ref_db: float,
    net: KNet,
    layers: tuple[str, str],
    drill_shrink_um: float,
) -> KVia:
    """Convert a GDS via polygon to a circular KiCad via (same approach as v1).

    KiCad `via` objects only store circular diameter/drill, so we use the
    bounding-box center and the smaller dimension as the diameter.
    """

    bbox = poly.bbox()
    size_size = min(bbox.width(), bbox.height()) * scale
    drill_size = max(min(bbox.width(), bbox.height()) - drill_shrink_um, 0.001) * scale
    # if size_size == 0:
    #     size_size = 0
    #     drill_size = None
    # if drill_size == 0:
    #     drill_size = None
    via = KVia(
        at=to_file_point((bbox.left + bbox.right) / 2, (bbox.bottom + bbox.top) / 2,
                         scale, flip_y, y_ref_db),
        net=net,
        size=size_size,
        drill=drill_size,
        layers=layers,
        via_type="buried" if "F.Cu" not in layers and "B.Cu" not in layers else "blind",
    )
    return via


def rotated_pad_size(w: float, h: float, angle_deg: float) -> tuple[float, float]:
    """Board-axis-aligned size of a w x h rectangle rotated by angle_deg.

    KiCad does not rotate a pad's (size w h) with the footprint angle, so a
    rotated instance needs its own footprint variant with the rotated pad
    dimensions: 0/180 deg keep (w, h), 90/270 deg give (h, w).
    """
    a = math.radians(angle_deg)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    return (w * c + h * s, w * s + h * c)


def build_pads(
    cell: db.Cell,
    layer_index: int,
    scale: float,
    mirrored: bool,
    angle_deg: float,
) -> list[tuple[str, Point, tuple[float, float]]]:
    """Build SMD rect pads from a cell's direct shapes on one pad layer.

    Local pad coordinates are in KiCad file space: GDS x is kept, GDS y is
    negated (y-up -> y-down). The mirrored variant additionally flips the
    local y sign, which together with the unchanged (at, angle) reproduces a
    KLayout mirrored instance (see module docstring). The pad sizes are the
    board-axis sizes for this variant's rotation (rotated_pad_size).
    """
    shapes = list(cell.each_shape(layer_index))
    if not shapes:
        return []
    pads: list[tuple[str, Point, tuple[float, float], tuple[float, float]]] = []
    for shape in shapes:
        bbox = shape.dpolygon.bbox()
        cx = (bbox.left + bbox.right) / 2
        cy = (bbox.bottom + bbox.top) / 2
        y_sign = 1.0 if mirrored else -1.0
        pads.append((
            Point(cx * scale, y_sign * cy * scale),
            rotated_pad_size(bbox.width() * scale, bbox.height() * scale, angle_deg),
            (cy, cx),  # sort key
        ))
    pads.sort(key=lambda p: p[2])
    return [(str(i + 1), pos, size) for i, (pos, size, _) in enumerate(pads)]


def convert_gds_to_kicad(
    gds_path: Path,
    pcb_path: Path,
    polygon_layer_map: dict[tuple[int, int], str],
    via_layer_map: dict[tuple[int, int], tuple[str, str]],
    scale_mm_per_um: float,
    drill_shrink_um: float,
    flip_y: bool,
    net_name: str,
) -> None:
    layout = db.Layout()
    layout.read(str(gds_path))

    top = layout.top_cell()
    if top is None:
        raise ValueError(f"No top cell found in {gds_path}")

    # 1 DB unit = layout.dbu um; scale DB units -> mm.
    scale = scale_mm_per_um * layout.dbu
    y_ref_db = top.dbbox().top

    project = KProject(str(pcb_path), version="20240108", copper_layers=4)
    gds_net = KNet(1, net_name)
    project.add(gds_net)

    # GDS (layer, datatype) -> DB layer index.
    layer_indexes: dict[tuple[int, int], int] = {}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        layer_indexes[(info.layer, info.datatype)] = li

    # ------------------------------------------------------------------
    # Pass 1: zones and vias for all mapped layers (v1 approach).
    # begin_shapes_rec flattens every instance into top-level coordinates.
    # ------------------------------------------------------------------
    polygon_counts: dict[tuple[int, int, str], int] = defaultdict(int)
    via_counts: dict[tuple[int, int, str, str], int] = defaultdict(int)
    outline_segments = 0
    skipped = 0

    for layer_index in layout.layer_indexes():
        info = layout.get_info(layer_index)
        gds_key = (info.layer, info.datatype)
        if gds_key in (FRONT_PAD_LAYER, BACK_PAD_LAYER):
            continue  # pad layers are converted to footprint pads in pass 2
        kicad_poly_layer = polygon_layer_map.get(gds_key)
        kicad_via_layers = via_layer_map.get(gds_key)
        if kicad_poly_layer is None and kicad_via_layers is None:
            continue

        iterator = top.begin_shapes_rec(layer_index)
        while not iterator.at_end():
            shape = iterator.shape()
            try:
                poly = shape.dpolygon.transformed(iterator.dtrans())
                if min(poly.bbox().width(), poly.bbox().height()) == 0:
                    # Degenerate point/line shape (e.g. a zero-length GDS LSEG,
                    # such as the point markers in the Bond_Pad_via cell on
                    # 4/0): no area, so neither a real via nor a polygon.
                    # (no continue here: iterator.next() must still run below)
                    skipped += 1
                elif kicad_via_layers is not None:
                    project.add(via_from_dpolygon(
                        poly, scale, flip_y, y_ref_db, gds_net,
                        kicad_via_layers, drill_shrink_um,
                    ))
                    via_counts[(info.layer, info.datatype, *kicad_via_layers)] += 1
                elif kicad_poly_layer is not None:
                    points = dpolygon_to_points(poly, scale, flip_y, y_ref_db)
                    if len(points) >= 3:
                        project.add(KFilledZone(net=gds_net, layer=kicad_poly_layer, points=points))
                        polygon_counts[(info.layer, info.datatype, kicad_poly_layer)] += 1
                    else:
                        skipped += 1
            except Exception as exc:  # noqa: BLE001 - report and continue for exploratory conversion.
                skipped += 1
                print(f"skipped layer {info.layer}/{info.datatype} shape {shape}: {exc}")
            iterator.next()

    # ------------------------------------------------------------------
    # Pass 1b: board outline. Closed 70/0 polygons become Edge.Cuts loops.
    # ------------------------------------------------------------------
    outline_li = layer_indexes.get(BOARD_OUTLINE_LAYER)
    if outline_li is not None:
        it = top.begin_shapes_rec(outline_li)
        while not it.at_end():
            poly = it.shape().dpolygon.transformed(it.dtrans())
            hull = list(poly.each_point_hull())
            if len(hull) >= 3:
                pts = [to_file_point(p.x, p.y, scale, flip_y, y_ref_db) for p in hull]
                for p1, p2 in zip(pts, pts[1:] + pts[:1]):
                    project.add(KSegment(None, "Edge.Cuts", p1, p2, OUTLINE_WIDTH_MM))
                    outline_segments += 1
            it.next()

    # ------------------------------------------------------------------
    # Pass 2: footprints. One footprint definition per (cell, rotation, mirror);
    # each distinct transform found on a pad layer places one copy of it.
    # Instances are collected with begin_shapes_rec (the same geometry source
    # as pass 1) instead of top.each_inst(), so placements and zones always
    # agree even when the two iteration paths report different instances.
    # ------------------------------------------------------------------
    fp_definitions: dict[tuple[str, float, bool], list[tuple[str, Point, tuple[float, float]]]] = {}
    fp_placements: dict[str, int] = defaultdict(int)
    ref_counter = 0

    def place_footprint(cell: db.Cell, layer: str, at: Point, angle: float, mirrored: bool) -> None:
        nonlocal ref_counter
        cell_name = cell.name
        # One definition per (cell, rotation, mirror): the pad positions are
        # rotated by the placement angle, but pad sizes must be pre-rotated
        # per variant (see rotated_pad_size / module docstring).
        key = (cell_name, angle, mirrored)
        if key not in fp_definitions:
            li = layer_indexes.get(FRONT_PAD_LAYER if layer == "F.Cu" else BACK_PAD_LAYER)
            work = cell.dup()   # flatten() is non-const; work on a copy
            work.flatten(True)  # expands sub-instances into local shapes
            fp_definitions[key] = build_pads(work, li, scale, mirrored, angle)
            variant = ""
            if angle or mirrored:
                variant = (" (variant: " + (f"rot {int(angle)}deg" if angle else "")
                           + (", mirrored" if mirrored else "") + ")")
            print(f"footprint '{cell_name}': {len(fp_definitions[key])} pads on {layer}{variant}")
        if not fp_definitions[key]:
            return
        ref_counter += 1
        fp_placements[cell_name] += 1
        fp_name = sanitize_fp_name(cell_name)
        if angle:
            fp_name += f"_R{int(angle)}"
        if mirrored:
            fp_name += "_M"
        block = KFootprintBlock(
            name=fp_name,
            at=at,
            angle=angle,
            layer=layer,
            ref=f"FP{ref_counter}",
            value=cell_name,
            pads=fp_definitions[key],
            net=gds_net,
        )
        project.footprints.append(block)

    def collect_pad_instances(gds_key: tuple[int, int]):
        """Distinct (cell, dtrans) pairs producing shapes on a pad layer."""
        li = layer_indexes.get(gds_key)
        if li is None:
            return []
        seen: dict[str, tuple[db.Cell, db.DTrans]] = {}
        it = top.begin_shapes_rec(li)
        while not it.at_end():
            dt = it.dtrans()
            if dt.to_s() not in seen:
                seen[dt.to_s()] = (it.cell(), dt)
            it.next()
        return list(seen.values())

    for gds_key, side in ((FRONT_PAD_LAYER, "F.Cu"), (BACK_PAD_LAYER, "B.Cu")):
        for cell, dt in collect_pad_instances(gds_key):
            if cell is top:  # pad shapes directly in the top cell -> fp at origin
                place_footprint(cell, side, at=Point(0, 0), angle=0, mirrored=False)
                continue
            tx, ty = parse_trans_translation(dt)
            place_footprint(
                cell,
                side,
                at=to_file_point(tx, ty, scale, flip_y, y_ref_db),
                angle=dt.rot() * 90,
                mirrored=dt.is_mirror(),
            )

    project.save()
    normalize_layer_block(Path(project.filename))

    # ------------------------------------------------------------------
    # Summary.
    # ------------------------------------------------------------------
    print(f"wrote {project.filename}")
    print(f"top cell: {top.name}")
    print(f"dbu: {layout.dbu} um/database-unit")
    print(f"y flip (GDS y-up -> KiCad y-down): {flip_y}")
    print("polygon layer mapping and shape counts:")
    for (gds_layer, datatype, kicad_layer), count in sorted(polygon_counts.items()):
        print(f"  GDS {gds_layer}/{datatype} -> {kicad_layer}: {count}")
    print("via layer mapping and via counts:")
    for (gds_layer, datatype, layer_a, layer_b), count in sorted(via_counts.items()):
        via_type = "buried" if "F.Cu" not in (layer_a, layer_b) and "B.Cu" not in (layer_a, layer_b) else "blind"
        print(f"  GDS {gds_layer}/{datatype} -> {via_type} via {layer_a} <-> {layer_b}: {count}")
    print("footprint definitions and placements:")
    for cell_name, count in sorted(fp_placements.items()):
        print(f"  {cell_name}: {count} placements")
    print(f"board outline (GDS {BOARD_OUTLINE_LAYER[0]}/{BOARD_OUTLINE_LAYER[1]} -> Edge.Cuts): "
          f"{outline_segments} segments")
    if skipped:
        print(f"skipped shapes: {skipped}")


def write_stackup(pcb_path: Path, process) -> None:
    """Put the process's stackup into the board's (setup ...) and set the board thickness, so
    KiCad, `layz hyp` and `layz pex` all read the same stack from the .kicad_pcb."""
    text = pcb_path.read_text()
    # board thickness first, in (general ...), before the stackup adds its own (thickness ...)
    mm = f"{process.thickness_um / 1000:.6g}"
    g = text.find("(general")
    if g >= 0:
        g_end = text.find("\n    )", g)
        head, n = re.subn(r"\(thickness [0-9.]+\)", f"(thickness {mm})", text[g:g_end], count=1)
        text = text[:g] + (head if n else head.replace("(general", f"(general\n        (thickness {mm})", 1)) + text[g_end:]
    else:  # pycbnew writes no (general ...): it goes right before the layer table
        k = text.find("    (layers")
        text = text[:k] + f"    (general\n        (thickness {mm})\n    )\n" + text[k:]
    i = text.find("(setup")
    if i >= 0:
        i += len("(setup")
        text = text[:i] + "\n" + process.kicad_stackup() + text[i:]
    else:  # pycbnew writes no (setup ...): KiCad's order puts it right after the layer table
        j = text.find("\n    (net")
        if j < 0:
            raise ValueError(f"{pcb_path}: can't find where to put the (setup ...) section")
        text = text[:j] + "\n    (setup\n" + process.kicad_stackup() + "    )" + text[j:]
    pcb_path.write_text(text)


def normalize_layer_block(pcb_path: Path) -> None:
    """Replace the generated layers block with the KiCad-accepted numbering."""
    text = pcb_path.read_text()
    start = text.find("    (layers\n")
    end = text.find("    (net", start)
    if start == -1 or end == -1:
        raise ValueError("Could not locate generated layers block")
    pcb_path.write_text(text[:start] + KICAD_LAYER_BLOCK + text[end:])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lay", type=Path, required=True, help="layout (.gds)")
    parser.add_argument("-o", "--out", type=Path,
                        help="KiCad board (default: the layout's name with .kicad_pcb)")
    parser.add_argument(
        "--stack", type=Path,
        help="layz process stack (.toml): sets the GDS layer mapping (copper zones, footprint pad "
             "layers, vias, outline) and is written into the board as its KiCad stackup; "
             "--layer-map/--via-map then override single entries",
    )
    parser.add_argument(
        "--layer-map", action="append", default=[],
        help="Map a GDS polygon layer/datatype to a KiCad layer, e.g. --layer-map 3/0=In2.Cu",
    )
    parser.add_argument(
        "--via-map", action="append", default=[],
        help="Map a GDS via layer/datatype to a KiCad via layer pair, e.g. --via-map 7/0=F.Cu,In1.Cu",
    )
    parser.add_argument("--scale-mm-per-um", type=float, default=1)
    parser.add_argument("--drill-shrink-um", type=float, default=10.0)
    parser.add_argument(
        "--net-name", default="",
        help="KiCad net name assigned to generated zones, vias and pads; default: empty string",
    )
    parser.add_argument(
        "--no-flip-y", action="store_true",
        help="Do not flip Y (raw GDS->KiCad coordinate mapping)",
    )
    args = parser.parse_args(argv)
    args.gds = args.lay
    args.pcb = args.out or args.lay.with_suffix(".kicad_pcb")

    global FRONT_PAD_LAYER, BACK_PAD_LAYER, BOARD_OUTLINE_LAYER
    process = None
    zones, vias = DEFAULT_POLYGON_LAYER_MAP, DEFAULT_VIA_LAYER_MAP
    if args.stack:
        from layz import stack as stackfile
        process = stackfile.load(args.stack)
        process.check_kicad()
        if len(process.copper) != 4:
            parser.error("gds2pcb writes 4-copper boards (F.Cu, In1.Cu, In2.Cu, B.Cu) for now; "
                         f"{args.stack} has {len(process.copper)} copper layers")
        zones, vias, pads = process.gds_layer_maps()
        side_pads = {name: key for key, name in pads.items()}
        FRONT_PAD_LAYER = side_pads.get("F.Cu", (-1, -1))
        BACK_PAD_LAYER = side_pads.get("B.Cu", (-1, -1))
        if process.outline:
            BOARD_OUTLINE_LAYER = tuple(int(x) for x in process.outline.split("/"))
    polygon_layer_map = {**zones, **parse_layer_map(args.layer_map)}
    via_layer_map = {**vias, **parse_via_map(args.via_map)}

    convert_gds_to_kicad(
        args.gds,
        args.pcb,
        polygon_layer_map,
        via_layer_map,
        args.scale_mm_per_um,
        args.drill_shrink_um,
        flip_y=not args.no_flip_y,
        net_name=args.net_name,
    )
    if process is not None:
        write_stackup(args.pcb, process)
        print(f"stackup: {process.name} ({len(process.layers)} layers, "
              f"{process.thickness_um:g} µm) written into the board")


if __name__ == "__main__":
    main()
