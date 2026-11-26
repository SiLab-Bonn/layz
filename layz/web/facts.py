"""A board's facts for the viewer, as one table: thickness, size, area, layers, nets, pins, metal
density and material budget per layer, and the GDS's hierarchy where the board came from one."""

from __future__ import annotations

from pathlib import Path

NM = 1e-6  # the union's grid: 1 nm, in mm


def _copper_area(b: dict) -> dict[str, float]:
    """Each copper layer's metal area (mm²): its pours and traces merged, overlaps counted once."""
    import klayout.db as kdb

    regions = {name: kdb.Region() for name in b["copper"]}
    for p in b["polys"]:
        if p["layer"] in regions:
            poly = kdb.DPolygon([kdb.DPoint(x, y) for x, y in p["pts"]])
            for hole in p["holes"]:
                poly.insert_hole([kdb.DPoint(x, y) for x, y in hole])
            regions[p["layer"]].insert(poly.to_itype(NM))
    for s in b["segs"]:
        if s["layer"] in regions and s["w"] > 0:
            regions[s["layer"]].insert(kdb.DPath([kdb.DPoint(s["x1"], s["y1"]), kdb.DPoint(s["x2"], s["y2"])], s["w"], s["w"] / 2, s["w"] / 2, True).to_itype(NM).polygon())
    return {name: r.merged().area() * NM * NM for name, r in regions.items()}


def _hierarchy(gds: Path) -> tuple[int, int]:
    """A GDS's hierarchy levels below its top cell and its instances (each array element)."""
    import klayout.db as kdb

    ly = kdb.Layout()
    ly.read(str(gds))
    top = ly.top_cell()

    def depth(cell) -> int:
        kids = {ly.cell(i.cell_index) for i in cell.each_inst()}
        return 1 + max((depth(c) for c in kids), default=0)

    it = kdb.RecursiveInstanceIterator(ly, top)
    count = 0
    while not it.at_end():
        count += 1
        it.next()
    return depth(top) - 1, count


def board(b: dict, stack=None, gds: Path | None = None) -> list[list[str]]:
    """The facts table's rows [fact, value]. ``stack``: the run's layz.stack.Process, for each
    layer's material (else the board's own); ``gds``: the layout the board came from."""
    from layz import stack as stackfile

    def size(mm: float) -> str:
        return f"{mm:.3f} mm" if mm >= 1 else f"{mm * 1000:.1f} µm"

    w, hgt = b["stats"]["size_mm"]
    area = w * hgt
    own = {l.name: l for l in stack.layers} if stack else {}
    metal = _copper_area(b)
    rows = [["total thickness", f"{b['stats']['thickness_mm'] * 1000:.1f} µm"], ["dimensions", f"{size(w)} × {size(hgt)}"],
            ["area", f"{area:.3f} mm²" if area >= 0.01 else f"{area * 1e6:.0f} µm²"], ["layers", f"{len(b['stackup'])} ({len(b['copper'])} metal)"],
            ["nets", str(len({x['net'] for x in b['polys'] + b['segs'] + b['vias'] + b['pins'] if x['net']}))], ["pins", str(len(b["pins"]))]]
    for name in b["copper"]:
        rows.append([f"density {name}", f"{100 * metal[name] / area:.1f} %" if area else "—"])
    budget, unknown = 0.0, []
    for l in b["stackup"]:
        mine = own.get(l["name"])
        x0 = (mine.x0_mm if mine and mine.x0_mm else None) or stackfile.x0_mm((mine.material if mine else None) or l.get("material"), l["type"])
        if x0 is None:
            unknown.append(l["name"])
            continue
        frac = metal.get(l["name"], 0.0) / area if l["type"] == "copper" and area else 1.0  # a metal layer: its share of the area
        xx0 = l["thickness_mm"] / x0 * frac
        budget += xx0
        rows.append([f"material budget {l['name']}", f"{100 * xx0:.4f} % X0"])
    rows.append(["material budget, total", f"{100 * budget:.4f} % X0" + (f" (without {', '.join(unknown)}: material unknown)" if unknown else "")])
    if gds and Path(gds).suffix.lower() in (".gds", ".gds2", ".oas") and Path(gds).is_file():
        levels, instances = _hierarchy(Path(gds))
        rows += [["hierarchy levels", str(levels)], ["instances", str(instances)]]
    return rows
