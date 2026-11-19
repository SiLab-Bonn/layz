#!/usr/bin/env python3
"""Propagate authoritative footprint-pad nets through geometric copper connectivity.

Only pads on the selected seed footprint (VTX2 by default) define nets. Existing
zone/via labels are corrected when they disagree with a uniquely connected seed
net; other footprint pads are checked afterward for net mismatches.

Requires Python 3 and Shapely >= 2.0. The input board is never changed unless
--in-place is explicitly selected. By default a sibling *_nets_assigned board
is written.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from shapely import make_valid
    from shapely.affinity import rotate, translate
    from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
except ImportError as exc:  # pragma: no cover - depends on the user's environment
    raise SystemExit(
        "This script requires Shapely >= 2.0. Install it with: python3 -m pip install shapely"
    ) from exc


TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()";]+|;[^\n]*')


class Atom(str):
    """S-expression atom retaining its source span."""

    def __new__(cls, value: str, start: int, end: int):
        obj = str.__new__(cls, value)
        obj.start = start
        obj.end = end
        return obj


class Form(list):
    """S-expression list retaining its source span."""

    def __init__(self, values: list[Any], start: int, end: int):
        super().__init__(values)
        self.start = start
        self.end = end


@dataclass
class Token:
    value: str
    start: int
    end: int
    quoted: bool = False


def parse_sexpr(source: str) -> Form:
    tokens: list[Token] = []
    for match in TOKEN_RE.finditer(source):
        raw = match.group(0)
        if raw.isspace() or raw.startswith(";"):
            continue
        if raw.startswith('"'):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid quoted string at byte {match.start()}: {exc}") from exc
            tokens.append(Token(value, match.start(), match.end(), True))
        else:
            tokens.append(Token(raw, match.start(), match.end()))

    pos = 0

    def parse_one() -> Any:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Unexpected end of S-expression")
        token = tokens[pos]
        if token.value != "(":
            if token.value == ")":
                raise ValueError(f"Unexpected ')' at byte {token.start}")
            pos += 1
            return Atom(token.value, token.start, token.end)

        start = token.start
        pos += 1
        values: list[Any] = []
        while pos < len(tokens) and tokens[pos].value != ")":
            values.append(parse_one())
        if pos >= len(tokens):
            raise ValueError(f"Unclosed '(' at byte {start}")
        end = tokens[pos].end
        pos += 1
        return Form(values, start, end)

    root = parse_one()
    if pos != len(tokens):
        raise ValueError(f"Unexpected S-expression content at byte {tokens[pos].start}")
    if not isinstance(root, Form):
        raise ValueError("Expected a top-level S-expression")
    return root


def head(form: Any) -> str:
    return str(form[0]) if isinstance(form, Form) and form else ""


def children(form: Form, tag: str) -> list[Form]:
    return [item for item in form if isinstance(item, Form) and head(item) == tag]


def child(form: Form, tag: str) -> Form | None:
    return next((item for item in form if isinstance(item, Form) and head(item) == tag), None)


def number(value: Any, description: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {description}: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"Invalid {description}: {value!r}")
    return result


def get_net(form: Form) -> str:
    """Read modern KiCad net names; tolerate legacy net-code + net_name forms."""
    net_name = child(form, "net_name")
    if net_name is not None and len(net_name) > 1:
        return str(net_name[1])
    net = child(form, "net")
    if net is None or len(net) < 2:
        return ""
    value = str(net[1])
    # In pre-v10 files, (net 12) is a code and (net_name "GND") is separate.
    return "" if value.isdigit() else value


def copper_layers(root: Form) -> list[str]:
    layers_form = child(root, "layers")
    if layers_form is None:
        return ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    result = []
    for layer in (item for item in layers_form if isinstance(item, Form)):
        # The board layer table uses forms whose first item is a numeric ID.
        if len(layer) >= 3 and str(layer[2]) in {"signal", "power"}:
            name = str(layer[1])
            if name.endswith(".Cu"):
                result.append(name)
    if not result:
        result = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    return result


def expand_copper_layers(layer_names: list[str], all_copper: list[str]) -> list[str]:
    expanded: set[str] = set()
    for name in layer_names:
        if name == "*.Cu":
            expanded.update(all_copper)
        elif name == "F&B.Cu":
            expanded.update(layer for layer in all_copper if layer in {"F.Cu", "B.Cu"})
        elif name.endswith(".Cu") and name in all_copper:
            expanded.add(name)
    return sorted(expanded)


def xy_points(pts_form: Form | None) -> list[tuple[float, float]]:
    if pts_form is None:
        return []
    points = []
    for point in children(pts_form, "xy"):
        if len(point) >= 3:
            points.append((number(point[1], "x coordinate"), number(point[2], "y coordinate")))
    return points


def polygonal(geometry: Any) -> Any:
    """Repair a polygon and discard non-area remnants from make_valid()."""
    repaired = make_valid(geometry)
    if repaired.geom_type == "Polygon" or repaired.geom_type == "MultiPolygon":
        return repaired
    polygons = []
    if isinstance(repaired, GeometryCollection):
        polygons = [part for part in repaired.geoms if part.geom_type == "Polygon" and not part.is_empty]
    return unary_union(polygons) if polygons else GeometryCollection()


def zone_geometry(zone: Form) -> Any:
    filled = children(zone, "filled_polygon")
    polygons = []
    for filled_polygon in filled:
        points = xy_points(child(filled_polygon, "pts"))
        if len(points) >= 3:
            polygons.append(polygonal(Polygon(points)))
    polygons = [part for part in polygons if not part.is_empty]
    return unary_union(polygons) if polygons else GeometryCollection()


def footprint_reference(footprint: Form, index: int) -> str:
    for prop in children(footprint, "property"):
        if len(prop) >= 3 and str(prop[1]) == "Reference":
            return str(prop[2])
    for prop in children(footprint, "fp_text"):
        if len(prop) >= 3 and str(prop[1]) == "reference":
            return str(prop[2])
    return f"<footprint-{index}>"


def pad_geometry(pad: Form, footprint_at: Form, description: str) -> Any:
    if len(pad) < 4:
        raise ValueError(f"Malformed pad in {description}")
    shape = str(pad[3])
    at = child(pad, "at")
    size = child(pad, "size")
    if at is None or size is None or len(at) < 3 or len(size) < 3:
        raise ValueError(f"Pad {description} has no usable (at ...) or (size ...) field")
    if len(footprint_at) < 3:
        raise ValueError(f"Malformed footprint position for pad {description}")

    fx, fy = number(footprint_at[1], "footprint x"), number(footprint_at[2], "footprint y")
    footprint_angle = number(footprint_at[3], "footprint angle") if len(footprint_at) > 3 else 0.0
    px, py = number(at[1], "pad x"), number(at[2], "pad y")
    pad_angle = number(at[3], "pad angle") if len(at) > 3 else 0.0
    w, h = number(size[1], "pad width"), number(size[2], "pad height")
    if w <= 0 or h <= 0:
        raise ValueError(f"Pad {description} has non-positive size")

    # KiCad's board-coordinate Y axis points down. A positive S-expression
    # rotation therefore maps local (x,y) to (cos*x + sin*y, -sin*x + cos*y).
    angle = math.radians(footprint_angle)
    cx = fx + math.cos(angle) * px + math.sin(angle) * py
    cy = fy - math.sin(angle) * px + math.cos(angle) * py

    if shape == "rect":
        geometry = box(-w / 2, -h / 2, w / 2, h / 2)
    elif shape == "circle":
        geometry = Point(0, 0).buffer(min(w, h) / 2, quad_segs=16)
    elif shape == "oval":
        radius = min(w, h) / 2
        if w >= h:
            geometry = LineString([(-w / 2 + radius, 0), (w / 2 - radius, 0)]).buffer(radius, quad_segs=16)
        else:
            geometry = LineString([(0, -h / 2 + radius), (0, h / 2 - radius)]).buffer(radius, quad_segs=16)
    elif shape == "roundrect":
        ratio_form = child(pad, "roundrect_rratio")
        ratio = number(ratio_form[1], "round-rectangle ratio") if ratio_form and len(ratio_form) > 1 else 0.25
        radius = max(0.0, min(w, h) * ratio)
        geometry = box(-w / 2 + radius, -h / 2 + radius, w / 2 - radius, h / 2 - radius)
        if radius > 0:
            geometry = geometry.buffer(radius, quad_segs=16)
    else:
        raise ValueError(
            f"Unsupported pad shape {shape!r} on {description}; add explicit geometry handling before assigning nets"
        )

    geometry = rotate(geometry, -(footprint_angle + pad_angle), origin=(0, 0), use_radians=False)
    return translate(geometry, xoff=cx, yoff=cy)


def arc_geometry(arc: Form, width: float) -> Any:
    start_form, mid_form, end_form = child(arc, "start"), child(arc, "mid"), child(arc, "end")
    if not start_form or not mid_form or not end_form:
        raise ValueError("An arc needs (start ...), (mid ...), and (end ...) fields")
    start = (number(start_form[1], "arc x"), number(start_form[2], "arc y"))
    mid = (number(mid_form[1], "arc x"), number(mid_form[2], "arc y"))
    end = (number(end_form[1], "arc x"), number(end_form[2], "arc y"))
    x1, y1 = start
    x2, y2 = mid
    x3, y3 = end
    determinant = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(determinant) < 1e-12:
        return LineString([start, mid, end]).buffer(width / 2, quad_segs=8)

    c1 = x1 * x1 + y1 * y1
    c2 = x2 * x2 + y2 * y2
    c3 = x3 * x3 + y3 * y3
    cx = (c1 * (y2 - y3) + c2 * (y3 - y1) + c3 * (y1 - y2)) / determinant
    cy = (c1 * (x3 - x2) + c2 * (x1 - x3) + c3 * (x2 - x1)) / determinant
    radius = math.hypot(x1 - cx, y1 - cy)
    angles = [math.atan2(y - cy, x - cx) for x, y in (start, mid, end)]
    ccw_sweep = (angles[2] - angles[0]) % (2 * math.pi)
    ccw_mid = (angles[1] - angles[0]) % (2 * math.pi)
    sweep = ccw_sweep if ccw_mid <= ccw_sweep else ccw_sweep - 2 * math.pi
    steps = max(8, math.ceil(abs(sweep) * radius / max(width / 4, 0.005)))
    points = [
        (cx + radius * math.cos(angles[0] + sweep * i / steps),
         cy + radius * math.sin(angles[0] + sweep * i / steps))
        for i in range(steps + 1)
    ]
    return LineString(points).buffer(width / 2, quad_segs=8)


@dataclass
class Conductor:
    index: int
    kind: str
    name: str
    net: str
    layers: list[str]
    geometry: Any
    form: Form
    net_form: Form | None = None
    assigned_net: str = ""
    seed_source: bool = False


class UnionFind:
    def __init__(self, count: int):
        self.parent = list(range(count))
        self.rank = [0] * count

    def find(self, item: int) -> int:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: int, right: int) -> None:
        left, right = self.find(left), self.find(right)
        if left == right:
            return
        if self.rank[left] < self.rank[right]:
            left, right = right, left
        self.parent[right] = left
        if self.rank[left] == self.rank[right]:
            self.rank[left] += 1


def source_modifications(source: str, nodes: list[Conductor], assigned: dict[int, str]) -> list[tuple[int, int, str]]:
    modifications: list[tuple[int, int, str]] = []
    for node_id, net_name in assigned.items():
        node = nodes[node_id]
        if node.kind == "zone":
            if node.net_form is not None and len(node.net_form) > 1 and str(node.net_form[1]) != net_name:
                atom = node.net_form[1]
                modifications.append((atom.start, atom.end, json.dumps(net_name, ensure_ascii=False)))
            elif node.net_form is None:
                tag = node.form[0]
                line_start = source.rfind("\n", 0, node.form.start) + 1
                indentation = source[line_start:node.form.start] + "\t"
                modifications.append((tag.end, tag.end, f"\n{indentation}(net {json.dumps(net_name, ensure_ascii=False)})"))
        elif node.kind == "via":
            if node.net_form is not None and len(node.net_form) > 1 and str(node.net_form[1]) != net_name:
                atom = node.net_form[1]
                modifications.append((atom.start, atom.end, json.dumps(net_name, ensure_ascii=False)))
            elif node.net_form is None:
                # KiCad requires a net field on a via; insert after its type (e.g. blind/buried).
                tag = node.form[1] if len(node.form) > 1 else node.form[0]
                line_start = source.rfind("\n", 0, node.form.start) + 1
                indentation = source[line_start:node.form.start] + "\t"
                modifications.append((tag.end, tag.end, f"\n{indentation}(net {json.dumps(net_name, ensure_ascii=False)})"))
    return modifications


def build_graph(root: Form, all_copper: list[str], tolerance: float, seed_footprint: str) -> tuple[list[Conductor], UnionFind, dict[str, list[tuple[int, Any]]], list[int]]:
    nodes: list[Conductor] = []
    layer_geometries: dict[str, list[tuple[int, Any]]] = defaultdict(list)
    pad_nodes: list[int] = []

    def add(kind: str, name: str, net: str, layers: list[str], geometry: Any, form: Form, seed_source: bool = False) -> int:
        if geometry is None or geometry.is_empty:
            return -1
        index = len(nodes)
        nodes.append(Conductor(index, kind, name, net, layers, geometry, form, child(form, "net"), seed_source=seed_source))
        for layer in layers:
            if layer in all_copper:
                # Buffer each item's geometry by half the requested gap, so two
                # items can bridge at most tolerance millimetres in total.
                indexed_geometry = geometry.buffer(tolerance / 2, quad_segs=8) if tolerance > 0 else geometry
                layer_geometries[layer].append((index, indexed_geometry))
        return index

    for top in root[1:]:
        if not isinstance(top, Form):
            continue
        if head(top) == "footprint":
            fp_at = child(top, "at")
            if fp_at is None:
                continue
            ref = footprint_reference(top, len(pad_nodes))
            for pad in children(top, "pad"):
                name = str(pad[1]) if len(pad) > 1 else "?"
                description = f"{ref} pad {name}"
                layer_form = child(pad, "layers")
                layers = expand_copper_layers([str(x) for x in layer_form[1:]] if layer_form else [], all_copper)
                if not layers:
                    continue
                geometry = pad_geometry(pad, fp_at, description)
                pad_net = get_net(pad)
                node_id = add("pad", description, pad_net, layers, geometry, pad,
                              seed_source=(ref == seed_footprint and bool(pad_net)))
                if node_id >= 0:
                    pad_nodes.append(node_id)

        elif head(top) == "zone":
            fill_form = child(top, "fill")
            if fill_form is None or len(fill_form) < 2 or str(fill_form[1]) != "yes":
                continue
            layer_form = child(top, "layer")
            layer = str(layer_form[1]) if layer_form and len(layer_form) > 1 else ""
            if layer not in all_copper:
                continue
            geometry = zone_geometry(top)
            if geometry.is_empty:
                continue
            uuid_form = child(top, "uuid")
            name = str(uuid_form[1]) if uuid_form and len(uuid_form) > 1 else f"zone-{len(nodes)}"
            add("zone", name, get_net(top), [layer], geometry, top)

        elif head(top) == "via":
            at, size, layers_form = child(top, "at"), child(top, "size"), child(top, "layers")
            if at is None or size is None or layers_form is None:
                continue
            x, y = number(at[1], "via x"), number(at[2], "via y")
            diameter = number(size[1], "via diameter")
            layers = expand_copper_layers([str(x) for x in layers_form[1:]], all_copper)
            if not layers:
                continue
            uuid_form = child(top, "uuid")
            name = str(uuid_form[1]) if uuid_form and len(uuid_form) > 1 else f"via-{len(nodes)}"
            add("via", name, get_net(top), layers, Point(x, y).buffer(diameter / 2, quad_segs=16), top)

        elif head(top) == "segment":
            start, end, width_form, layer_form = (child(top, field) for field in ("start", "end", "width", "layer"))
            if not start or not end or not width_form or not layer_form:
                continue
            width = number(width_form[1], "track width")
            line = LineString([(number(start[1], "track x"), number(start[2], "track y")),
                               (number(end[1], "track x"), number(end[2], "track y"))])
            layer = str(layer_form[1])
            if layer in all_copper:
                add("track", f"segment-{len(nodes)}", get_net(top), [layer], line.buffer(width / 2, quad_segs=8), top)

        elif head(top) == "arc":
            width_form, layer_form = child(top, "width"), child(top, "layer")
            if not width_form or not layer_form:
                continue
            width = number(width_form[1], "arc width")
            layer = str(layer_form[1])
            if layer in all_copper:
                add("track", f"arc-{len(nodes)}", get_net(top), [layer], arc_geometry(top, width), top)

    union_find = UnionFind(len(nodes))
    pair_checks = 0
    for layer, entries in layer_geometries.items():
        if len(entries) < 2:
            continue
        geometries = [geometry for _, geometry in entries]
        tree = STRtree(geometries)
        node_ids = [node_id for node_id, _ in entries]
        for local_index, geometry in enumerate(geometries):
            matches = tree.query(geometry, predicate="intersects")
            for other_index in matches:
                other_index = int(other_index)
                if other_index <= local_index:
                    continue
                left, right = node_ids[local_index], node_ids[other_index]
                if left != right:
                    union_find.union(left, right)
                    pair_checks += 1
    return nodes, union_find, layer_geometries, pad_nodes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assign KiCad zone/via nets from a selected footprint's authoritative pad nets."
    )
    parser.add_argument("board", type=Path, help="Input .kicad_pcb board")
    parser.add_argument("-o", "--output", type=Path, help="Output board (default: *_nets_assigned.kicad_pcb)")
    parser.add_argument(
        "--seed-footprint", default="VTX2",
        help="Reference designator whose pad nets are authoritative (default: VTX2)",
    )
    parser.add_argument("--in-place", action="store_true", help="Modify the input board after making a .bak backup")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and report only; do not write a board")
    parser.add_argument(
        "--tolerance-mm", type=float, default=0.001,
        help="Maximum extra gap bridged between copper shapes (default: 0.001 mm; use 0 for exact touch/overlap)",
    )
    args = parser.parse_args(argv)

    if args.tolerance_mm < 0:
        parser.error("--tolerance-mm must be >= 0")
    if args.in_place and args.output:
        parser.error("Use either --in-place or --output, not both")

    board_path = args.board.expanduser().resolve()
    if not board_path.is_file():
        parser.error(f"Board file not found: {board_path}")
    source = board_path.read_text(encoding="utf-8")

    try:
        root = parse_sexpr(source)
        all_copper = copper_layers(root)
        seed_footprints = [
            top for top in root[1:]
            if isinstance(top, Form) and head(top) == "footprint"
            and footprint_reference(top, 0) == args.seed_footprint
        ]
        if not seed_footprints:
            print(f"ERROR: no footprint with Reference {args.seed_footprint!r} exists in {board_path}", file=sys.stderr)
            return 2

        seed_pads = [pad for footprint in seed_footprints for pad in children(footprint, "pad")]
        netted_seed_pads = [pad for pad in seed_pads if get_net(pad)]
        if not netted_seed_pads:
            print(
                f"ERROR: found footprint {args.seed_footprint!r} with {len(seed_pads)} pad(s), "
                "but none has a (net ...) assignment in this board file. "
                "Save/assign the VTX2 pad nets in the PCB first, or select a different seed footprint.",
                file=sys.stderr,
            )
            return 2

        nodes, union_find, _layer_geometries, pad_nodes = build_graph(
            root, all_copper, args.tolerance_mm, args.seed_footprint
        )
    except (ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    component_seed_nets: dict[int, set[str]] = defaultdict(set)
    component_seed_pads: dict[int, list[str]] = defaultdict(list)
    component_members: dict[int, list[int]] = defaultdict(list)
    for node in nodes:
        component = union_find.find(node.index)
        component_members[component].append(node.index)
        if node.seed_source and node.net:
            component_seed_nets[component].add(node.net)
            component_seed_pads[component].append(node.name)

    seed_pad_count = sum(1 for node in nodes if node.seed_source)
    if seed_pad_count == 0:
        print(f"ERROR: no net-assigned pads found on seed footprint {args.seed_footprint!r}", file=sys.stderr)
        return 2

    assigned: dict[int, str] = {}
    no_seed_source = defaultdict(int)
    withheld_by_clash = defaultdict(int)
    conflict_components = []
    for component, members in component_members.items():
        nets = component_seed_nets[component]
        if len(nets) > 1:
            conflict_components.append((component, members, sorted(nets)))
            for node_id in members:
                node = nodes[node_id]
                if node.kind in {"zone", "via"}:
                    withheld_by_clash[node.kind] += 1
            continue
        if not nets:
            for node_id in members:
                node = nodes[node_id]
                if node.kind in {"zone", "via"}:
                    no_seed_source[node.kind] += 1
            continue
        inferred_net = next(iter(nets))
        for node_id in members:
            node = nodes[node_id]
            if node.kind in {"zone", "via"} and node.net != inferred_net:
                node.assigned_net = inferred_net
                assigned[node_id] = inferred_net

    counts = defaultdict(int)
    for node in nodes:
        counts[node.kind] += 1
    assigned_counts = defaultdict(int)
    overwritten_counts = defaultdict(int)
    for node_id in assigned:
        node = nodes[node_id]
        assigned_counts[node.kind] += 1
        if node.net:
            overwritten_counts[node.kind] += 1

    pad_mismatches = []
    for component, members in component_members.items():
        seed_nets = component_seed_nets[component]
        if not seed_nets:
            continue
        expected_net = (
            next(iter(seed_nets)) if len(seed_nets) == 1
            else "one of " + ", ".join(sorted(seed_nets))
        )
        for node_id in members:
            node = nodes[node_id]
            if node.kind == "pad" and not node.seed_source and node.net not in seed_nets:
                pad_mismatches.append((node.name, node.net or "<no net>", expected_net))
    pad_mismatches = sorted(set(pad_mismatches))

    print(f"Board: {board_path}")
    print(f"Copper layers: {', '.join(all_copper)}")
    print(f"Authoritative pad-net source: footprint {args.seed_footprint}")
    print("Conductors: " + ", ".join(f"{kind}={counts[kind]}" for kind in ("pad", "track", "via", "zone")))
    print(f"Geometric tolerance: {args.tolerance_mm:g} mm")
    print(
        "Updated zone/via nets from the seed footprint: "
        f"zones={assigned_counts['zone']} ({overwritten_counts['zone']} replaced existing labels), "
        f"vias={assigned_counts['via']} ({overwritten_counts['via']} replaced existing labels)"
    )

    if conflict_components:
        print(
            f"\nERROR: {len(conflict_components)} connected copper component(s) touch pads "
            f"on {args.seed_footprint} with different nets; left those components unchanged:"
        )
        for component, members, nets in conflict_components:
            seed_pads = sorted(set(component_seed_pads[component]))
            net_list = nets[:8]
            if len(nets) > len(net_list):
                net_list.append(f"... +{len(nets) - len(net_list)} more")
            pad_list = seed_pads[:10]
            if len(seed_pads) > len(pad_list):
                pad_list.append(f"... +{len(seed_pads) - len(pad_list)} more")
            print(f"  NET CLASH: seed nets={net_list}; {args.seed_footprint} pads={pad_list}")

    if pad_mismatches:
        print(
            f"\nERROR: {len(pad_mismatches)} other-footprint pad(s) have a net different "
            f"from the connected {args.seed_footprint} pad net:"
        )
        for name, actual_net, expected_net in pad_mismatches[:50]:
            print(f"  PAD NET VIOLATION: {name} is {actual_net}; connected seed net is {expected_net}")
        if len(pad_mismatches) > 50:
            print(f"  ... and {len(pad_mismatches) - 50} more pad mismatch(es)")

    if no_seed_source or withheld_by_clash:
        print("\nWARNING: zone/via objects left unchanged:")
        for kind in ("zone", "via"):
            if no_seed_source[kind] or withheld_by_clash[kind]:
                print(
                    f"  {kind}: {no_seed_source[kind]} not connected to {args.seed_footprint}; "
                    f"{withheld_by_clash[kind]} touch different-net seed pads"
                )

    if not args.dry_run and assigned:
        modifications = source_modifications(source, nodes, assigned)
        updated = source
        for start, end, replacement in sorted(modifications, key=lambda item: item[0], reverse=True):
            updated = updated[:start] + replacement + updated[end:]

        if args.in_place:
            target = board_path
            backup = board_path.with_suffix(board_path.suffix + ".bak")
            suffix = 1
            while backup.exists():
                backup = board_path.with_suffix(board_path.suffix + f".bak.{suffix}")
                suffix += 1
            shutil.copy2(board_path, backup)
            print(f"Backup: {backup}")
        else:
            target = args.output.expanduser().resolve() if args.output else board_path.with_name(
                board_path.stem + "_nets_assigned" + board_path.suffix
            )
            if target == board_path:
                parser.error("Output would overwrite the input; use --in-place to allow this")

        temp_target = target.with_name(target.name + ".tmp")
        temp_target.write_text(updated, encoding="utf-8")
        temp_target.replace(target)
        print(f"Wrote: {target}")
    elif args.dry_run:
        print("Dry run: no board file written.")
    else:
        print("No missing zone/via nets could be inferred; no output file written.")

    return 1 if conflict_components or pad_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
