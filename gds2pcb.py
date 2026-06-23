#!/usr/bin/env python3
"""Prototype GDS -> KiCad .kicad_pcb converter using KLayout + kicad-pycbnew.

Current process mapping, per this test structure:

    M1: no GDS shapes imported, represented by B.Cu so via1 has a lower endpoint
    via1 / poly1: GDS 2/0 -> KiCad via B.Cu <-> In1.Cu
    M2: GDS 3/0 -> In1.Cu
    via2 / poly2: GDS 4/0 -> KiCad via In1.Cu <-> F.Cu
    M3: GDS 6/0 -> F.Cu
    solder-mask cut: GDS 7/0 -> F.Mask filled zone

Notes:
- KiCad's native `via` object stores circular diameter/drill only. The file format
  does not appear to support square via shape for `via` objects. For each GDS via
  polygon we therefore use its bounding box center and an equivalent diameter.
- Drill is set to via diameter minus 10 um by default.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import klayout.db as db
from pycbnew.primitives.net import KNet
from pycbnew.primitives.project import KProject
from pycbnew.primitives.sexpressions import fnum, sexp_xy
from pycbnew.primitives.via import KVia
from pycbnew.primitives.zone import KZone
from pycbnew.utils.geometry import Point

# Physical/process defaults requested by the user.
DEFAULT_POLYGON_LAYER_MAP: dict[tuple[int, int], str] = {
    (3, 0): "In1.Cu",  # M2
    (6, 0): "F.Cu",  # M3
    (7, 0): "F.Mask",  # solder-mask opening / cut
}

DEFAULT_VIA_LAYER_MAP: dict[tuple[int, int], tuple[str, str]] = {
    (2, 0): ("B.Cu", "In1.Cu"),  # via1/poly1 between M1 and M2
    (4, 0): ("In1.Cu", "F.Cu"),  # via2/poly2 between M2 and M3
}


class KFilledZone(KZone):
    """KiCad zone with cached filled geometry identical to the outline.

    KiCad/HYP export uses the zone's cached `(filled_polygon ...)` data.  pycbnew's
    stock KZone can describe the zone outline, but it does not emit that cached filled
    polygon.  This class deliberately writes a filled polygon with the same points as
    the zone polygon so KiCad does not need to calculate/refill it.
    """

    def __init__(
        self, *, net: KNet, layer: str, points: list[Point], priority: int = 0
    ):
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


# KiCad accepts this layer numbering scheme; it matches power_connector_tests.kicad_pcb.
# pycbnew's generated multilayer numbering uses In1.Cu=1, which KiCad rejected when vias are present.
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
        (21 "Eco1.User" user "User.Eco1")
        (23 "Eco2.User" user "User.Eco2")
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
    """Parse entries like `3=F.Cu` or `3/0=F.Cu`."""
    result: dict[tuple[int, int], str] = {}
    for item in items:
        lhs, rhs = item.split("=", 1)
        result[_parse_gds_layer_key(lhs)] = rhs
    return result


def parse_via_map(items: list[str]) -> dict[tuple[int, int], tuple[str, str]]:
    """Parse entries like `2/0=B.Cu,In1.Cu`."""
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


def dpolygon_to_points(
    poly: db.DPolygon, scale: float, flip_y: bool, y_ref_um: float
) -> list[Point]:
    pts = []
    for p in poly.each_point_hull():
        y_um = y_ref_um - p.y if flip_y else p.y
        pts.append(Point(p.x * scale, y_um * scale))

    # KiCad polygon point lists are implicitly closed; do not repeat the first point.
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def via_from_dpolygon(
    poly: db.DPolygon,
    scale: float,
    flip_y: bool,
    y_ref_um: float,
    net: KNet,
    layers: tuple[str, str],
    drill_shrink_um: float,
) -> KVia:
    bbox = poly.bbox()
    cx_um = (bbox.left + bbox.right) / 2
    cy_um = (bbox.bottom + bbox.top) / 2
    if flip_y:
        cy_um = y_ref_um - cy_um

    width_um = bbox.width()
    height_um = bbox.height()

    # Native KiCad vias are circular. If the GDS polygon is square, this is exact.
    # If it is rectangular, use the smaller dimension so the circle fits inside.
    diameter_um = min(width_um, height_um)
    drill_um = max(diameter_um - drill_shrink_um, 0.001)

    via_type = "buried" if "F.Cu" not in layers and "B.Cu" not in layers else "blind"

    return KVia(
        at=Point(cx_um * scale, cy_um * scale),
        net=net,
        size=diameter_um * scale,
        drill=drill_um * scale,
        layers=layers,
        via_type=via_type,
    )


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

    bbox = top.dbbox()
    y_ref_um = bbox.top

    # Three copper layers: bottom M1 placeholder, middle M2, top M3.
    project = KProject(str(pcb_path), version="20240108", copper_layers=3)
    gds_net = KNet(1, net_name)
    project.add(gds_net)

    polygon_counts: dict[tuple[int, int, str], int] = defaultdict(int)
    via_counts: dict[tuple[int, int, str, str], int] = defaultdict(int)
    skipped = 0

    for layer_index in layout.layer_indexes():
        info = layout.get_info(layer_index)
        gds_key = (info.layer, info.datatype)
        kicad_poly_layer = polygon_layer_map.get(gds_key)
        kicad_via_layers = via_layer_map.get(gds_key)

        # Ignore unmapped layers deliberately; this avoids accidental layer-stack mixups.
        if kicad_poly_layer is None and kicad_via_layers is None:
            continue

        iterator = top.begin_shapes_rec(layer_index)
        while not iterator.at_end():
            shape = iterator.shape()
            try:
                # dpolygon converts boxes and paths to polygon outlines too.
                poly = shape.dpolygon.transformed(iterator.dtrans())
                if kicad_via_layers is not None:
                    project.add(
                        via_from_dpolygon(
                            poly,
                            scale_mm_per_um,
                            flip_y,
                            y_ref_um,
                            gds_net,
                            kicad_via_layers,
                            drill_shrink_um,
                        )
                    )
                    via_counts[(info.layer, info.datatype, *kicad_via_layers)] += 1
                elif kicad_poly_layer is not None:
                    points = dpolygon_to_points(poly, scale_mm_per_um, flip_y, y_ref_um)
                    if len(points) >= 3:
                        project.add(
                            KFilledZone(
                                net=gds_net,
                                layer=kicad_poly_layer,
                                points=points,
                            )
                        )
                        polygon_counts[
                            (info.layer, info.datatype, kicad_poly_layer)
                        ] += 1
                    else:
                        skipped += 1
            except Exception as exc:  # noqa: BLE001 - report and continue for exploratory conversion.
                skipped += 1
                print(
                    f"skipped layer {info.layer}/{info.datatype} shape {shape}: {exc}"
                )
            iterator.next()

    project.save()
    normalize_layer_block(Path(project.filename))
    print(f"wrote {project.filename}")
    print(f"top cell: {top.name}")
    print(f"dbu: {layout.dbu} um/database-unit")
    print("polygon layer mapping and shape counts:")
    for (gds_layer, datatype, kicad_layer), count in sorted(polygon_counts.items()):
        print(f"  GDS {gds_layer}/{datatype} -> {kicad_layer}: {count}")
    print("via layer mapping and via counts:")
    for (gds_layer, datatype, layer_a, layer_b), count in sorted(via_counts.items()):
        via_type = (
            "buried"
            if "F.Cu" not in (layer_a, layer_b) and "B.Cu" not in (layer_a, layer_b)
            else "blind"
        )
        print(
            f"  GDS {gds_layer}/{datatype} -> {via_type} via {layer_a} <-> {layer_b}: {count}"
        )
    if skipped:
        print(f"skipped shapes: {skipped}")


def normalize_layer_block(pcb_path: Path) -> None:
    text = pcb_path.read_text()
    start = text.find("    (layers\n")
    end = text.find("    (net", start)
    if start == -1 or end == -1:
        raise ValueError("Could not locate generated layers block")
    pcb_path.write_text(text[:start] + KICAD_LAYER_BLOCK + text[end:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gds", nargs="?", default="conversion_test.gds", type=Path)
    parser.add_argument(
        "pcb", nargs="?", default="conversion_test_pycbnew.kicad_pcb", type=Path
    )
    parser.add_argument(
        "--layer-map",
        action="append",
        default=[],
        help="Map a GDS polygon layer/datatype to a KiCad layer, e.g. --layer-map 3/0=In1.Cu",
    )
    parser.add_argument(
        "--via-map",
        action="append",
        default=[],
        help="Map a GDS via layer/datatype to a KiCad via layer pair, e.g. --via-map 2/0=B.Cu,In1.Cu",
    )
    parser.add_argument("--scale-mm-per-um", type=float, default=0.001)
    parser.add_argument("--drill-shrink-um", type=float, default=10.0)
    parser.add_argument(
        "--net-name",
        default="",
        help="KiCad net name assigned to generated zones and vias; default: empty string",
    )
    parser.add_argument(
        "--flip-y",
        action="store_true",
        help="Mirror about the top of the GDS top-cell bbox",
    )
    args = parser.parse_args()

    polygon_layer_map = {**DEFAULT_POLYGON_LAYER_MAP, **parse_layer_map(args.layer_map)}
    via_layer_map = {**DEFAULT_VIA_LAYER_MAP, **parse_via_map(args.via_map)}

    convert_gds_to_kicad(
        args.gds,
        args.pcb,
        polygon_layer_map,
        via_layer_map,
        args.scale_mm_per_um,
        args.drill_shrink_um,
        args.flip_y,
        args.net_name,
    )


if __name__ == "__main__":
    main()
