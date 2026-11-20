"""A design's inputs for the viewer: a GDS drawn on its stack's layers (KLayout), a KiCad board or
schematic as SVG (kicad-cli), a netlist as its nets."""

from __future__ import annotations

import re
from pathlib import Path

MM = 1e-3  # GDS µm -> mm


def gds(path: Path, stack: str | Path) -> dict:
    """The GDS's copper (merged, per layer of the stack), via cuts, labels, outline and the stack."""
    import klayout.db as kdb

    from layz import stack as stackfile

    process = stackfile.load(stack)
    ly = kdb.Layout()
    ly.read(str(path))
    top = ly.top_cell()
    dbu = ly.dbu

    def region(spec: str):
        li = ly.find_layer(*(int(x) for x in spec.split("/")))
        return kdb.Region(top.begin_shapes_rec(li)).merged() if li is not None else kdb.Region()

    def rings(poly) -> tuple[list, list]:
        hull = [[p.x * dbu * MM, p.y * dbu * MM] for p in poly.each_point_hull()]
        holes = [[[p.x * dbu * MM, p.y * dbu * MM] for p in poly.each_point_hole(k)] for k in range(poly.holes())]
        return hull, holes

    polys, cuts, labels = [], [], []
    for layer in process.copper:
        if not layer.gds:
            continue
        for poly in region(layer.gds).each():
            hull, holes = rings(poly)
            polys.append({"net": "", "layer": layer.name, "pts": hull, "holes": holes})
        for spec in [layer.gds, *layer.labels]:
            li = ly.find_layer(*(int(x) for x in spec.split("/")))
            if li is None:
                continue
            it = top.begin_shapes_rec(li)
            while not it.at_end():
                sh = it.shape()
                if sh.is_text():
                    p = it.trans() * sh.text_pos
                    labels.append({"text": sh.text_string, "x": p.x * dbu * MM, "y": p.y * dbu * MM, "layer": layer.name})
                it.next()
    for via in process.vias:
        for poly in region(via.gds).each():
            hull, _ = rings(poly)
            cuts.append({"layers": [via.top, via.bottom], "pts": hull})
    outline = []
    if process.outline:
        for poly in region(process.outline).each():
            hull, _ = rings(poly)
            outline += [[a[0], a[1], b[0], b[1]] for a, b in zip(hull, hull[1:] + hull[:1])]
    box = top.dbbox()
    stackup = [{"name": l.name, "type": l.type, "thickness_mm": l.thickness_um * MM, "er": l.er if l.type != "copper" else None, "material": l.material or ""} for l in process.layers]
    copper = [l.name for l in process.copper]
    count = lambda name: sum(1 for p in polys if p["layer"] == name)
    return {"name": Path(path).name, "kind": "gds", "bbox": [box.left * MM, box.bottom * MM, box.right * MM, box.top * MM], "outline": outline, "stackup": stackup, "copper": copper, "polys": polys, "segs": [], "vias": [], "pins": [], "cuts": cuts, "labels": labels, "stats": {"thickness_mm": sum(l["thickness_mm"] for l in stackup), "size_mm": [box.width() * MM, box.height() * MM], "copper_layers": len(copper), "shapes per layer": {n: count(n) for n in copper}, "via cuts": len(cuts), "labels": len(labels)}}


THEMES = Path(__file__).parent / "kicad"  # KiCad colour themes (colors/*.json) for the drawings
DARK = {".kicad_sch": "wDark_2", ".kicad_pcb": "nord2_dark"}  # light: KiCad's own colours


def kicad_svg(path: Path, out: Path, dark: bool) -> list[Path]:
    """A KiCad schematic (every sheet) or board as SVG in ``out`` (kicad-cli), without drawing
    sheet or background, in the page's colours: Nord themes for dark, KiCad's for light. The
    themes come from layz's own KiCad config folder, so the user's KiCad settings are left alone."""
    import os

    from layz import kicad, log

    cli = kicad.cli()
    if not cli:
        raise FileNotFoundError("kicad-cli not found (install/kicad.sh)")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.svg"):
        old.unlink()
    path = Path(path)
    theme = ["-t", DARK[path.suffix]] if dark else []
    if path.suffix == ".kicad_sch":
        cmd = [cli, "sch", "export", "svg", "--exclude-drawing-sheet", "--no-background-color", *theme, "-o", str(out), str(path)]
    else:
        cmd = [cli, "pcb", "export", "svg", "--mode-single", "--fit-page-to-board", "--exclude-drawing-sheet", *theme, "-l", "F.Cu,In1.Cu,In2.Cu,B.Cu,Edge.Cuts,F.Silkscreen", "-o", str(out / "board.svg"), str(path)]
    config = out.parent / "kicad-config"  # KICAD_CONFIG_HOME: <it>/<version>/colors/<theme>.json
    for version in ("10.0", "9.0"):
        (config / version / "colors").mkdir(parents=True, exist_ok=True)
        for f in (THEMES / "colors").glob("*.json"):
            (config / version / "colors" / f.name).write_bytes(f.read_bytes())
    if log.run("kicad-cli", cmd, env={**os.environ, "KICAD_CONFIG_HOME": str(config)}):
        raise FileNotFoundError(f"kicad-cli could not draw {path}")
    return sorted(out.glob("*.svg"))


def netlist(path: Path) -> list[dict]:
    """A KiCad netlist's nets and their pins."""
    text = Path(path).read_text(errors="replace")
    nets = []
    for block in re.split(r"\(net\s+\(code", text)[1:]:
        m = re.search(r'\(name\s+"((?:\\.|[^"\\])*)"\)', block)
        if m:
            nets.append({"net": m[1], "pins": [f"{r}.{p}" for r, p in re.findall(r'\(node\s+\(ref\s+"([^"]*)"\)\s+\(pin\s+"([^"]*)"\)', block)]})
    return nets
