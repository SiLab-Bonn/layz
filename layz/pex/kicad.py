#!/usr/bin/env python3
"""3-D electrostatic field solve (capacitance matrix) of a KiCad board, straight from .kicad_pcb.

Everything comes from the board file itself:
    copper     tracks, pads, filled zones (KiCad's own polygons, via pcbnew)
    vias       barrels as solid cylinders of the drill diameter; plated pads likewise
    nets       KiCad net names name the conductors
    stack      the (stackup ...) block: z and thickness of every copper and dielectric
               layer, εr of each dielectric (Board Setup > Physical Stackup in KiCad)

and goes, in memory, to KLayout regions -> KLayout-PEX's FasterCapModelBuilder -> FasterCap's
.lst/.geo input -> FasterCap or FastCap2 -> capacitance matrix (and, with --charges, the panel
charges fieldview.py turns into E-field plots). No intermediate files.

Inner copper is embedded in the prepreg next to it, outer copper in the solder mask.
Boards without a stackup get KiCad's default FR4 stack, with a warning.

    layz pex board.kicad_pcb [--charges] [--stl]
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

from klayout import db

from layz import kicad
from layz import stack as stackfile
from layz.pex.solve import MODEL_DBU_UM, Conductor, Dielectric, Stack, Via, stack_from_process

pcbnew = None  # KiCad's module, imported where a board is read (layz's KiCad environment, see layz.kicad)


def _pcbnew():
    global pcbnew
    if pcbnew is None:
        kicad.require_pcbnew()
        import pcbnew as _p

        pcbnew = _p
    return pcbnew


MAX_ERROR_NM = 1000  # arc/circle polygonization error
BARREL_SIDES = 16  # via barrels as 16-gons


# --------------------------------------------------------------------------- geometry


def insert_polyset(shapes: db.Shapes, ps) -> db.Point | None:
    """Insert a KiCad SHAPE_POLY_SET (nm) as KLayout polygons (1 nm dbu); return a point on it.

    KiCad stores zone fills "fractured": a polygon with holes becomes one outline with hairline
    slits cut into the holes. The slits' near-coincident edges break the 3-D model's
    triangulation, so the set is unfractured (real holes) and simplified first."""
    ps = pcbnew.SHAPE_POLY_SET(ps)
    ps.Unfracture()
    ps.Simplify()
    first = None
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        hull = [db.Point(o.CPoint(j).x, o.CPoint(j).y) for j in range(o.PointCount())]
        if len(hull) < 3:
            continue
        poly = db.Polygon(hull)
        for h in range(ps.HoleCount(i)):
            hc = ps.Hole(i, h)
            poly.insert_hole([db.Point(hc.CPoint(j).x, hc.CPoint(j).y) for j in range(hc.PointCount())])
        shapes.insert(poly)
        first = first or hull[0]
    return first


def load_board(pcb_path: Path, refill: bool) -> tuple[db.Layout, db.Cell, Stack, list[str]]:
    _pcbnew()
    board = pcbnew.LoadBoard(str(pcb_path))
    warnings: list[str] = []

    def has_fill(z) -> bool:
        return any(z.HasFilledPolysForLayer(l) and z.GetFilledPolysList(l).OutlineCount() > 0 for l in z.GetLayerSet().CuStack())

    unfilled = [z for z in board.Zones() if not z.GetIsRuleArea() and not has_fill(z)]
    if unfilled and refill:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        warnings.append(f"filled {len(unfilled)} unfilled zone(s) with KiCad's zone filler (the .kicad_pcb is not modified)")

    cu_ids = list(board.GetEnabledLayers().CuStack())  # top -> bottom
    cu_names = [board.GetLayerName(l) for l in cu_ids]
    order = {n: i for i, n in enumerate(cu_names)}

    layout = db.Layout()
    layout.dbu = MODEL_DBU_UM  # 1 nm = KiCad's internal unit: coordinates map 1:1
    top = layout.create_cell(re.sub(r"\W", "_", pcb_path.stem))
    cu_shapes = {n: top.shapes(layout.layer(db.LayerInfo(n))) for n in cu_names}
    net_texts = {n: top.shapes(layout.layer(db.LayerInfo(f"{n}.net"))) for n in cu_names}
    via_spans: set[tuple[str, str]] = set()

    def add(item, layer_id):
        ps = pcbnew.SHAPE_POLY_SET()
        item.TransformShapeToPolygon(ps, layer_id, 0, MAX_ERROR_NM, pcbnew.ERROR_INSIDE)
        name = board.GetLayerName(layer_id)
        at = insert_polyset(cu_shapes[name], ps)
        label(name, item.GetNetname(), at)

    def label(layer_name, net, at):
        if net and at is not None:
            net_texts[layer_name].insert(db.Text(net, db.Trans(at)))

    def barrel(top_name, bot_name, pos, drill_nm, net):
        via_spans.add((top_name, bot_name))
        li = layout.layer(db.LayerInfo(f"V:{top_name}:{bot_name}"))
        r = drill_nm / 2
        pts = [db.Point(round(pos.x + r * math.cos(2 * math.pi * i / BARREL_SIDES)), round(pos.y + r * math.sin(2 * math.pi * i / BARREL_SIDES))) for i in range(BARREL_SIDES)]
        top.shapes(li).insert(db.Polygon(pts))

    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            a, b = sorted((board.GetLayerName(t.TopLayer()), board.GetLayerName(t.BottomLayer())), key=order.get)
            for lid in cu_ids:
                if order[a] <= order[board.GetLayerName(lid)] <= order[b] and t.FlashLayer(lid):
                    add(t, lid)
            barrel(a, b, t.GetPosition(), t.GetDrillValue(), t.GetNetname())
        else:
            add(t, t.GetLayer())

    for fp in board.GetFootprints():
        for pad in fp.Pads():
            for lid in cu_ids:
                if pad.IsOnLayer(lid) and pad.FlashLayer(lid):
                    add(pad, lid)
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and pad.GetDrillSizeX() > 0:
                barrel(cu_names[0], cu_names[-1], pad.GetPosition(), min(pad.GetDrillSizeX(), pad.GetDrillSizeY()), pad.GetNetname())

    for z in board.Zones():
        if z.GetIsRuleArea():
            continue
        for lid in cu_ids:
            if not z.IsOnLayer(lid):
                continue
            name = board.GetLayerName(lid)
            ps = z.GetFilledPolysList(lid) if z.HasFilledPolysForLayer(lid) else None
            if ps is None or ps.OutlineCount() == 0:
                where = f"zone {z.GetZoneName() or z.GetNetname() or '?'} on {name}"
                if refill:
                    warnings.append(f"{where} fills to nothing in KiCad (clearance/min width); skipped")
                    continue
                ps = z.Outline()
                warnings.append(f"{where} is unfilled; using its outline")
            label(name, z.GetNetname(), insert_polyset(cu_shapes[name], ps))

    process = stackfile.from_kicad_pcb(pcb_path)
    if process is None:
        board_mm = board.GetDesignSettings().GetBoardThickness() / 1e6
        warnings.append(f"{pcb_path.name} has no stackup: using KiCad's default {board_mm:g} mm FR4 stack; set the real one in Board Setup > Physical Stackup, or write the board with `layz gds2pcb --stack`")
        process = stackfile.kicad_default(cu_names, board_mm)
    process.halo_um = 1000.0
    return layout, top, stack_from_process(process, gds=False, via_spans=via_spans), warnings


def print_stack(stack: Stack) -> None:
    print("stack (µm, z = bottom face):")
    rows = [(c.z, f"  copper     {c.name:<14} z={c.z:9.3f}  t={c.thickness:8.3f}") for c in stack.conductors]
    rows += [(d.z, f"  dielectric {d.name:<14} z={d.z:9.3f}  t={d.thickness:8.3f}  εr={d.k:g}") for d in stack.dielectrics]
    for _, line in sorted(rows, key=lambda r: -r[0]):
        print(line)


def export_board(pcb_path: Path, refill: bool, folder: Path) -> None:
    """The board read into KLayout regions and its stack, written for the main environment:
    board.oas (layers by name), stack.json, warnings.json (runs where pcbnew imports)."""
    import dataclasses
    import json

    layout, top, stack, warnings = load_board(pcb_path, refill)
    folder.mkdir(parents=True, exist_ok=True)
    layout.write(str(folder / "board.oas"))
    (folder / "stack.json").write_text(json.dumps(dataclasses.asdict(stack)))
    (folder / "warnings.json").write_text(json.dumps(warnings))


def import_board(folder: Path) -> tuple[db.Layout, db.Cell, Stack, list[str]]:
    """export_board's files, back as load_board's result (layers by name only, as it made them)."""
    import json

    read = db.Layout()
    read.read(str(folder / "board.oas"))
    layout = db.Layout()
    layout.dbu = read.dbu
    src = read.top_cell()
    top = layout.create_cell(src.name)
    for i in read.layer_indexes():
        info = read.get_info(i)
        top.shapes(layout.layer(db.LayerInfo(info.name))).insert(src.shapes(i))
    d = json.loads((folder / "stack.json").read_text())
    stack = Stack(k_void=d["k_void"], halo_um=d["halo_um"], conductors=[Conductor(**c) for c in d["conductors"]], vias=[Via(**v) for v in d["vias"]], dielectrics=[Dielectric(**x) for x in d["dielectrics"]])
    return layout, top, stack, json.loads((folder / "warnings.json").read_text())


if __name__ == "__main__":  # the step layz's KiCad environment runs: BOARD FOLDER [refill]
    export_board(Path(sys.argv[1]), sys.argv[3:] == ["refill"], Path(sys.argv[2]))
