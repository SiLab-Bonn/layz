#!/usr/bin/env python3
"""Render a simple SVG preview directly from a GDS file.

This is intended for README/documentation previews, not as a replacement for a
layout editor. It uses KLayout to polygonize GDS boxes, polygons, and paths, then
writes those polygons as SVG paths grouped by GDS layer/datatype.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import klayout.db as db

DEFAULT_COLORS = [
    "#c83434",
    "#3a7bd5",
    "#33a852",
    "#f4b400",
    "#9c27b0",
    "#00acc1",
    "#ef6c00",
    "#6d4c41",
]


def svg_num(value: float) -> str:
    return f"{value:.6g}"


def polygon_to_path(poly: db.DPolygon, scale: float, flip_y: bool, y_ref: float) -> str:
    points = []
    for point in poly.each_point_hull():
        x = point.x * scale
        y_um = y_ref - point.y if flip_y else point.y
        y = y_um * scale
        points.append((x, y))

    if not points:
        return ""

    commands = [f"M {svg_num(points[0][0])} {svg_num(points[0][1])}"]
    commands.extend(f"L {svg_num(x)} {svg_num(y)}" for x, y in points[1:])
    commands.append("Z")
    return " ".join(commands)


def render_gds_to_svg(
    gds_path: Path,
    svg_path: Path,
    scale_mm_per_um: float,
    width_px: int,
    flip_y: bool,
) -> None:
    layout = db.Layout()
    layout.read(str(gds_path))

    top = layout.top_cell()
    if top is None:
        raise ValueError(f"No top cell found in {gds_path}")

    bbox = top.dbbox()
    min_x = bbox.left * scale_mm_per_um
    min_y = bbox.bottom * scale_mm_per_um
    width = bbox.width() * scale_mm_per_um
    height = bbox.height() * scale_mm_per_um
    y_ref = bbox.top

    if width <= 0 or height <= 0:
        raise ValueError("Top cell has empty bounding box")

    height_px = max(1, round(width_px * height / width))
    paths_by_layer: dict[tuple[int, int], list[str]] = defaultdict(list)

    for layer_index in layout.layer_indexes():
        info = layout.get_info(layer_index)
        key = (info.layer, info.datatype)
        iterator = top.begin_shapes_rec(layer_index)
        while not iterator.at_end():
            shape = iterator.shape()
            poly = shape.dpolygon.transformed(iterator.dtrans())
            path = polygon_to_path(poly, scale_mm_per_um, flip_y, y_ref)
            if path:
                paths_by_layer[key].append(path)
            iterator.next()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" '
        f'viewBox="{svg_num(min_x)} {svg_num(min_y)} {svg_num(width)} {svg_num(height)}">',
        f"  <title>GDS preview: {gds_path.name}</title>",
    ]

    for index, key in enumerate(sorted(paths_by_layer)):
        color = DEFAULT_COLORS[index % len(DEFAULT_COLORS)]
        layer, datatype = key
        lines.append(
            f'  <g id="gds-{layer}-{datatype}" fill="{color}" fill-opacity="0.72" stroke="{color}" stroke-width="0.001">'
        )
        lines.append(f"    <title>GDS layer {layer}/{datatype}</title>")
        for path in paths_by_layer[key]:
            lines.append(f'    <path d="{path}"/>')
        lines.append("  </g>")

    lines.append("</svg>")
    svg_path.write_text("\n".join(lines) + "\n")

    print(f"wrote {svg_path}")
    print(f"top cell: {top.name}")
    print(f"layers: {len(paths_by_layer)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("gds", nargs="?", default="example.gds", type=Path)
    parser.add_argument("svg", nargs="?", default="example_gds.svg", type=Path)
    parser.add_argument("--scale-mm-per-um", type=float, default=0.001)
    parser.add_argument("--width-px", type=int, default=504)
    parser.add_argument("--flip-y", action="store_true")
    args = parser.parse_args(argv)

    render_gds_to_svg(
        args.gds,
        args.svg,
        args.scale_mm_per_um,
        args.width_px,
        args.flip_y,
    )


if __name__ == "__main__":
    main()
