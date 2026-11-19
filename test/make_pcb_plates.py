#!/usr/bin/env python3
"""KiCad parallel-plate test board: two 10x10 mm copper plates (35 µm, 1 oz) on F.Cu and
B.Cu of a 0.2 mm FR4 core (εr 4.5), with 10 µm solder mask (εr 3.3) on both sides.

Ideal (no fringing): C = eps0 * 4.5 * (10 mm)^2 / 0.2 mm = 19.92 pF.

Run in the repo's venv (needs KiCad's pcbnew):  python test/make_pcb_plates.py [out.kicad_pcb]
"""

import sys
from pathlib import Path

import pcbnew

PLATE_MM = 10.0
CORE_MM = 0.2
CU_MM = 0.035
MASK_MM = 0.01

STACKUP = f"""		(stackup
			(layer "F.SilkS" (type "Top Silk Screen"))
			(layer "F.Mask" (type "Top Solder Mask") (thickness {MASK_MM}) (epsilon_r 3.3))
			(layer "F.Cu" (type "copper") (thickness {CU_MM}))
			(layer "dielectric 1" (type "core") (thickness {CORE_MM}) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
			(layer "B.Cu" (type "copper") (thickness {CU_MM}))
			(layer "B.Mask" (type "Bottom Solder Mask") (thickness {MASK_MM}) (epsilon_r 3.3))
			(layer "B.SilkS" (type "Bottom Silk Screen"))
			(copper_finish "None")
			(dielectric_constraints no)
		)
"""


def mm(v: float) -> int:
    return pcbnew.FromMM(v)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("pcb_plates.kicad_pcb"))
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(mm(CORE_MM + 2 * CU_MM + 2 * MASK_MM))

    # board outline, 2 mm around the plates
    m = 2.0
    pts = [(-m, -m), (PLATE_MM + m, -m), (PLATE_MM + m, PLATE_MM + m), (-m, PLATE_MM + m)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
        seg.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        board.Add(seg)

    for net_name, layer in (("TOP", pcbnew.F_Cu), ("BOT", pcbnew.B_Cu)):
        net = pcbnew.NETINFO_ITEM(board, net_name)
        board.Add(net)
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(net)
        z.SetZoneName(f"plate_{net_name}")
        z.SetLocalClearance(0)
        z.SetMinThickness(mm(0.1))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((0, 0), (PLATE_MM, 0), (PLATE_MM, PLATE_MM), (0, PLATE_MM)):
            ol.Append(mm(x), mm(y))
        board.Add(z)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(str(out))

    # pcbnew's SWIG API can't set the stackup: write it into the (setup ...) section
    text = out.read_text()
    i = text.index("(setup") + len("(setup")
    out.write_text(text[:i] + "\n" + STACKUP + text[i:])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
