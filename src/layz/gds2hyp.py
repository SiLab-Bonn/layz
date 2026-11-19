"""Write a HyperLynx .hyp file from a KiCad board, the way KiCad's own exporter does.

KiCad only offers its HyperLynx exporter in the PCB editor (File > Export > Hyperlynx), not in
kicad-cli or its Python module. This is a re-implementation of that exporter
(pcbnew/exporters/export_hyperlynx.cpp, KiCad 10), checked against a file the GUI wrote:
the same records, in the same order and number format.

    {VERSION=2.14} / {UNITS=ENGLISH LENGTH}    lengths in inches, Y negated
    {BOARD ...}       PERIMETER_SEGMENT per board-outline segment
    {STACKUP ...}     SIGNAL per copper layer, DIELECTRIC per dielectric/mask (from the
                      board's stackup: `layz gds2pcb --stack` writes it)
    {DEVICES ...}     one per footprint
    {PADSTACK=n ...}  pad and via padstacks, deduplicated, numbered in order of first use
    {NET="..." ...}   per net: PIN, VIA, SEG, ARC, and zone fills as POLYGON / POLYVOID;
                      every copper object without a net gets its own EmptyNet<n>

    layz gds2hyp design.gds --stack stacks/uni_bonn_rdl.toml [-o design.hyp]   (via layz gds2pcb)
    layz gds2hyp board.kicad_pcb [-o board.hyp]
    layz gds2hyp exported.hyp -o with_traces.hyp                             (pours -> traces only)

Running HyperLynx on the result: `layz hyp` (layz.hyperlynx).

Signal routes drawn as polygons (every GDS route, and KiCad zones made from them) become pours,
which HyperLynx BoardSim cannot model as transmission lines (no length, loss or crosstalk). By
default (--traces auto) strip-shaped pours of signal nets are written as traces instead: their
centreline as SEG records, as wide as the strip (layz.traces). Supplies and planes stay pours.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from layz import stack as stackfile

pcbnew = None  # KiCad's module, imported when a board is written (a .hyp rewrite needs no KiCad)


def _kicad():
    global pcbnew
    if pcbnew is None:
        import pcbnew as _pcbnew
        pcbnew = _pcbnew
    return pcbnew

RESISTIVITY = 1.724e-8  # copper bulk resistivity, Ω·m (KiCad's constant)


def iu2hyp(iu: float) -> float:
    """KiCad internal units (nm) -> inches."""
    return iu / 1e9 / 0.0254


def _shape_ids() -> dict:
    ids = {pcbnew.PAD_SHAPE_CIRCLE: 0, pcbnew.PAD_SHAPE_OVAL: 0,
           pcbnew.PAD_SHAPE_RECTANGLE: 1, pcbnew.PAD_SHAPE_ROUNDRECT: 2}
    return ids


@dataclass(frozen=True)
class PadStack:
    drill: int                                    # nm, 0 = no hole
    shapes: tuple                                 # ((layer_id, shape_id, sx, sy), ...)
    angle: float


class HypWriter:
    def __init__(self, board, out, warn=print):
        self.b = board
        self.o = out
        self.warn = warn
        self.cu = list(pcbnew.LSET.AllCuMask().CuStack())
        self.board_cu = [l for l in board.GetEnabledLayers().CuStack()]
        self.stacks: list[PadStack] = []
        self.stack_id: dict[PadStack, int] = {}
        self.stack_of: dict[str, int] = {}        # pad/via UUID -> padstack id
        self.poly_id = 1
        self.shape_ids = _shape_ids()
        self.warned_shapes: set = set()

    def p(self, indent: int, text: str) -> None:
        self.o.write("  " * indent + text)

    # ---------------------------------------------------------------- padstacks

    def _add(self, ps: PadStack) -> int:
        if ps not in self.stack_id:
            self.stack_id[ps] = len(self.stacks)
            self.stacks.append(ps)
        return self.stack_id[ps]

    def _shape_id(self, shape) -> int:
        if shape in self.shape_ids:
            return self.shape_ids[shape]
        if shape not in self.warned_shapes:
            self.warned_shapes.add(shape)
            self.warn(f"pad shape {shape} has no HyperLynx equivalent: written as oval (as KiCad does)")
        return 0

    def pad_padstack(self, pad) -> PadStack:
        angle = 180.0 - pad.GetOrientation().AsDegrees()
        if angle < 0:
            angle += 360.0
        shapes = []
        for l in pad.GetLayerSet().CuStack():
            eff = pad.Padstack().EffectiveLayerFor(l)
            sz = pad.GetSize(eff)
            shapes.append((l, self._shape_id(pad.GetShape(eff)), sz.x, sz.y))
        return PadStack(drill=pad.GetDrillSizeX(), shapes=tuple(shapes), angle=angle)

    def via_stack(self, via) -> PadStack:
        shapes = []
        for l in via.GetLayerSet().CuStack():
            w = via.GetWidth(via.Padstack().EffectiveLayerFor(l))
            shapes.append((l, 0, w, w))
        return PadStack(drill=via.GetDrillValue(), shapes=tuple(shapes), angle=0.0)

    def collect_stacks(self) -> None:
        for fp in self.b.GetFootprints():
            for pad in fp.Pads():
                self.stack_of[pad.m_Uuid.AsString()] = self._add(self.pad_padstack(pad))
        for t in self.b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                self.stack_of[t.m_Uuid.AsString()] = self._add(self.via_stack(t))

    # ---------------------------------------------------------------- sections

    def header(self) -> None:
        self.p(0, "{VERSION=2.14}\n")
        self.p(0, "{UNITS=ENGLISH LENGTH}\n\n")

    def board_outline(self) -> None:
        self.p(0, f'{{BOARD "{self.b.GetFileName()}"\n')
        ps = pcbnew.SHAPE_POLY_SET()
        if not self.b.GetBoardPolygonOutlines(ps, False):
            self.warn("board outline is malformed (run DRC in KiCad): written as far as it goes")
        for i in range(ps.OutlineCount()):
            for chain in [ps.Outline(i)] + [ps.Hole(i, h) for h in range(ps.HoleCount(i))]:
                for j in range(chain.SegmentCount()):
                    s = chain.CSegment(j)
                    self.p(1, "(PERIMETER_SEGMENT X1=%.9f Y1=%.9f X2=%.9f Y2=%.9f)\n" % (
                        iu2hyp(s.A.x), iu2hyp(-s.A.y), iu2hyp(s.B.x), iu2hyp(-s.B.y)))
        self.p(0, "}\n\n")

    def stackup(self, process) -> None:
        self.p(0, "{STACKUP\n")
        copper = None
        n_diel = {}
        for l in process.layers:
            t = iu2hyp(l.thickness_um * 1000)
            if l.type == "copper":
                copper = l.name
                self.p(1, '(SIGNAL T=%g P=%g C=%g L="%.20s" M=COPPER)\n' % (t, 0.0, RESISTIVITY, copper))
            elif l.type == "mask":
                self.p(1, '(DIELECTRIC T=%g C=%g L="%.20s" M="%.20s")\n' % (
                    t, l.k, l.name, l.material or "Solder Mask"))
            else:
                self.p(1, '(DIELECTRIC T=%g C=%g L="DE_%.17s" M="%.20s")\n' % (
                    t, l.k, copper or "", l.material or "FR4"))
        self.p(0, "}\n\n")

    def devices(self) -> None:
        self.p(0, "{DEVICES\n")
        for fp in self.b.GetFootprints():
            ref = fp.GetReference() or "EMPTY"
            self.p(1, f'(? REF="{ref}" L="{self.b.GetLayerName(fp.GetLayer())}")\n')
        self.p(0, "}\n\n")

    def padstacks(self) -> None:
        all_cu = set(self.board_cu)
        for n, ps in enumerate(self.stacks):
            self.p(0, "{PADSTACK=%d, %.9f\n" % (n, iu2hyp(ps.drill)))
            layers = [s[0] for s in ps.shapes]
            same = len({s[1:] for s in ps.shapes}) == 1
            if set(layers) >= all_cu and same and ps.shapes:
                self.p(1, '("MDEF", %s)\n' % self._shape_str(ps.shapes[0], ps.angle))
            else:
                for s in ps.shapes:
                    self.p(1, '("%s", %s)\n' % (self.b.GetLayerName(s[0]), self._shape_str(s, ps.angle)))
            self.p(0, "}\n\n")

    @staticmethod
    def _shape_str(s, angle: float) -> str:
        return "%d, %.9f, %.9f, %.1f, M" % (s[1], iu2hyp(s[2]), iu2hyp(s[3]), angle)

    # ---------------------------------------------------------------- nets

    def _on_copper(self, item) -> bool:
        return any(True for _ in item.GetLayerSet().CuStack())

    def net_objects(self, code: int) -> list:
        """Pads, then tracks/vias, then zones of a net (code -1: everything without a net)."""
        match = (lambda c: c <= 0) if code < 0 else (lambda c: c == code)
        objs = [pad for fp in self.b.GetFootprints() for pad in fp.Pads()
                if match(pad.GetNetCode()) and self._on_copper(pad)]
        objs += [t for t in self.b.GetTracks() if match(t.GetNetCode()) and self._on_copper(t)]
        objs += [z for z in self.b.Zones() if not z.GetIsRuleArea() and match(z.GetNetCode())
                 and self._on_copper(z)]
        return objs

    def write_objects(self, objs) -> None:
        for o in objs:
            cls = o.GetClass()
            if cls == "PAD":
                fp = o.GetParentFootprint()
                ref = (fp.GetReference() if fp else "") or "EMPTY"
                num = o.GetNumber() or "1"
                pos = o.GetPosition()
                self.p(1, '(PIN X=%.10f Y=%.10f R="%s.%s" P=%d)\n' % (
                    iu2hyp(pos.x), iu2hyp(-pos.y), ref, num, self.stack_of[o.m_Uuid.AsString()]))
            elif cls == "PCB_VIA":
                pos = o.GetPosition()
                self.p(1, "(VIA X=%.10f Y=%.10f P=%d)\n" % (
                    iu2hyp(pos.x), iu2hyp(-pos.y), self.stack_of[o.m_Uuid.AsString()]))
            elif cls == "PCB_TRACK":
                a, b = o.GetStart(), o.GetEnd()
                self.p(1, '(SEG X1=%.10f Y1=%.10f X2=%.10f Y2=%.10f W=%.10f L="%s")\n' % (
                    iu2hyp(a.x), iu2hyp(-a.y), iu2hyp(b.x), iu2hyp(-b.y), iu2hyp(o.GetWidth()),
                    self.b.GetLayerName(o.GetLayer())))
            elif cls == "PCB_ARC":
                a, b, c = o.GetStart(), o.GetEnd(), o.GetCenter()
                if not o.IsCCW():
                    a, b = b, a
                self.p(1, '(ARC X1=%.10f Y1=%.10f X2=%.10f Y2=%.10f XC=%.10f YC=%.10f R=%.10f W=%.10f L="%s")\n' % (
                    iu2hyp(a.x), iu2hyp(-a.y), iu2hyp(b.x), iu2hyp(-b.y), iu2hyp(c.x), iu2hyp(-c.y),
                    iu2hyp(o.GetRadius()), iu2hyp(o.GetWidth()), self.b.GetLayerName(o.GetLayer())))
            elif cls == "ZONE":
                for layer in o.GetLayerSet().Seq():
                    if not o.HasFilledPolysForLayer(layer):
                        continue
                    fill = pcbnew.SHAPE_POLY_SET(o.GetFilledPolysList(layer))
                    fill.Simplify()
                    name = self.b.GetLayerName(layer)
                    for i in range(fill.OutlineCount()):
                        self._poly('{POLYGON T=POUR L="%s" ID=%d' % (name, self.poly_id), fill.Outline(i))
                        for h in range(fill.HoleCount(i)):
                            self._poly("{POLYVOID ID=%d" % self.poly_id, fill.Hole(i, h))
                        self.poly_id += 1

    def _poly(self, head: str, chain) -> None:
        pts = [chain.CPoint(k) for k in range(chain.PointCount())]
        if not pts:
            return
        self.p(1, "%s X=%.10f Y=%.10f\n" % (head, iu2hyp(pts[0].x), iu2hyp(-pts[0].y)))
        for pt in pts + [pts[0]]:
            self.p(2, "(LINE X=%.10f Y=%.10f)\n" % (iu2hyp(pt.x), iu2hyp(-pt.y)))
        self.p(1, "}\n")

    def nets(self) -> None:
        self.poly_id = 1
        by_code = self.b.GetNetInfo().NetsByNetcode()
        for code in sorted(by_code.keys()):
            net = by_code[code]
            if code <= 0 or not net.GetNetname():
                continue
            objs = self.net_objects(code)
            if not objs:
                continue
            self.p(0, f'{{NET="{net.GetNetname()}"\n')
            self.write_objects(objs)
            self.p(0, "}\n\n")
        for n, obj in enumerate(self.net_objects(-1)):
            self.p(0, f'{{NET="EmptyNet{n}"\n')
            self.write_objects([obj])
            self.p(0, "}\n\n")

    def run(self, process) -> None:
        self.collect_stacks()
        self.header()
        self.board_outline()
        self.stackup(process)
        self.devices()
        self.padstacks()
        self.nets()


# ---------------------------------------------------------------- pours -> traces

TRACE_MAX_WIDTH_MM = 0.08  # auto: nets whose strips are at most this wide (signals, not supplies)


def _parse_nets(lines: list[str]):
    """Each {NET=...} block of a .hyp: (name, first line, last line, polygons per layer, anchors,
    pin count, whether it has voids/arcs in its pours)."""
    import re

    from shapely.geometry import Point, Polygon
    nets = []
    i = 0
    num = re.compile(r"\b([XY])=([-\d.eE+]+)")
    while i < len(lines):
        if not lines[i].startswith("{NET="):
            i += 1
            continue
        name = lines[i][len('{NET="'):].split('"')[0]
        start, polys, anchors, pins, odd = i, {}, [], 0, False
        i += 1
        while i < len(lines) and not lines[i].startswith("}"):
            s = lines[i].strip()
            if s.startswith(("(PIN", "(VIA")):
                xy = dict(num.findall(s))
                anchors.append(Point(float(xy["X"]), float(xy["Y"])))
                pins += s.startswith("(PIN")
            elif s.startswith("{POLYVOID"):
                odd = True
            elif s.startswith("{POLYGON"):
                layer = re.search(r'L="([^"]*)"', s).group(1)
                pts, j = [], i + 1
                while not lines[j].strip().startswith("}"):
                    t = lines[j].strip()
                    if t.startswith("(LINE"):
                        xy = dict(num.findall(t))
                        pts.append((float(xy["X"]), float(xy["Y"])))
                    else:
                        odd = True  # CURVE: not a plain outline
                    j += 1
                if len(pts) >= 3:
                    polys.setdefault(layer, []).append((i, j, Polygon(pts).buffer(0)))
                i = j
            i += 1
        nets.append((name, start, i, polys, anchors, pins, odd))
        i += 1
    return nets


def add_traces(text: str, select: str = "auto", max_width_mm: float = TRACE_MAX_WIDTH_MM,
               warn=print) -> tuple[str, list[tuple[str, int, float, float]]]:
    """Rewrite a .hyp's strip-shaped pours as traces (SEG records), net by net; see layz.traces.

    ``select``: "auto" (nets with >= 2 pins, >= 95 % of their copper strips, no strip wider than
    ``max_width_mm``), "none", or comma-separated net names (converted whatever their width).
    A converted net keeps its PIN/VIA records; each strip becomes SEGs, pad-like copper holding a
    via/pin is dropped (the padstack models it), other leftovers stay pours. Returns the new text
    and, per converted net, (name, segments, trace length, width) in mm."""
    from shapely.ops import unary_union

    from layz import traces as tr
    if select == "none":
        return text, []
    lines = text.splitlines(keepends=True)
    if not any(l.startswith("{UNITS=ENGLISH") for l in lines[:5]):
        raise ValueError("pours -> traces needs a .hyp in ENGLISH units (inches), as KiCad and layz write")
    named = None if select == "auto" else {n.strip() for n in select.split(",") if n.strip()}
    max_w = max_width_mm / 25.4
    poly_id = max([int(m) for l in lines for m in __import__("re").findall(r"\bID=(\d+)", l)] or [0]) + 1
    out, done, report = [], 0, []
    for name, start, end, polys, anchors, pins, odd in _parse_nets(lines):
        if named is not None and name not in named:
            continue
        if named is None and pins < 2 or not polys:
            continue
        if odd:
            warn(f"{name}: pours with voids or arcs, left as pours")
            continue
        segs_by_layer, keep_by_layer, area, conv = {}, {}, 0.0, 0.0
        drop = set()
        for layer, items in polys.items():
            merged = unary_union([p for _, _, p in items])
            for part in getattr(merged, "geoms", [merged]):
                area += part.area
                tr.REJECTED.clear()
                res = tr.split_route(part, anchors)
                if res is None:
                    keep_by_layer.setdefault(layer, []).append(part)
                    continue
                conv += part.area
                segs_by_layer.setdefault(layer, []).extend(res[0])
                keep_by_layer.setdefault(layer, []).extend(res[1])
            drop.update((a, b) for a, b, _ in items)
        widths = [s.width for v in segs_by_layer.values() for s in v]
        if not widths:
            continue
        if named is None and (conv < 0.95 * area or max(widths) > max_w):
            continue
        # replace this net's POLYGON blocks by its SEGs and leftover pours
        body = []
        skip = {k for a, b in drop for k in range(a, b + 1)}
        for k in range(start + 1, end):
            if k not in skip:
                body.append(lines[k])
        for layer, segs in segs_by_layer.items():
            for s in segs:
                body.append('  (SEG X1=%.10f Y1=%.10f X2=%.10f Y2=%.10f W=%.10f L="%s")\n' % (
                    s.x1, s.y1, s.x2, s.y2, s.width, layer))
        for layer, parts in keep_by_layer.items():
            for p in parts:
                pts = list(p.exterior.coords)
                body.append('  {POLYGON T=POUR L="%s" ID=%d X=%.10f Y=%.10f\n' % (layer, poly_id, *pts[0]))
                body += ["    (LINE X=%.10f Y=%.10f)\n" % q for q in pts]
                body.append("  }\n")
                poly_id += 1
        out += lines[done:start + 1] + body
        done = end
        length = sum(((s.x2 - s.x1) ** 2 + (s.y2 - s.y1) ** 2) ** 0.5 for v in segs_by_layer.values() for s in v)
        report.append((name, len(widths), length * 25.4, max(widths) * 25.4))
    out += lines[done:]
    return "".join(out), report


def board_process(pcb_path: Path, board):
    process = stackfile.from_kicad_pcb(pcb_path)
    if process is None:
        cu = [board.GetLayerName(l) for l in board.GetEnabledLayers().CuStack()]
        board_mm = board.GetDesignSettings().GetBoardThickness() / 1e6
        print(f"warning: {pcb_path.name} has no stackup: writing KiCad's default {board_mm:g} mm FR4 "
              "stack; use `layz gds2pcb --stack` or set it in Board Setup > Physical Stackup",
              file=sys.stderr)
        process = stackfile.kicad_default(cu, board_mm)
    return process


def write_hyp(pcb_path: Path, hyp_path: Path, refill: bool = False) -> None:
    _kicad()
    board = pcbnew.LoadBoard(str(pcb_path))
    if refill:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    process = board_process(pcb_path, board)
    with open(hyp_path, "w", encoding="utf-8") as f:
        HypWriter(board, f, warn=lambda m: print(f"warning: {m}", file=sys.stderr)).run(process)


def traces_pass(hyp_path: Path, select: str, max_width_mm: float) -> None:
    """Rewrite ``hyp_path`` in place with its strip-shaped pours as traces, and say what changed."""
    text, report = add_traces(hyp_path.read_text(encoding="utf-8"), select, max_width_mm,
                              warn=lambda m: print(f"warning: {m}", file=sys.stderr))
    hyp_path.write_text(text, encoding="utf-8")
    if report:
        print(f"pours -> traces: {len(report)} net(s)")
        for name, n, length, width in report:
            print(f"  {name:20} {n:4d} segments, {length:8.2f} mm, {width * 1e3:5.1f} um wide")
    elif select != "none":
        print("pours -> traces: no net qualified (see --traces)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 epilog="Running HyperLynx on the .hyp: layz hyp {setup,info,dc,si,sparam,plot,run} -h")
    ap.add_argument("input", type=Path,
                    help=".kicad_pcb board, a GDS (converted with layz gds2pcb), or a .hyp to rewrite")
    ap.add_argument("-o", "--out", type=Path, help="output .hyp (default: next to the input)")
    ap.add_argument("--stack", type=Path, help="GDS input: layz process stack (.toml)")
    ap.add_argument("--keep-pcb", action="store_true",
                    help="GDS input: keep the intermediate .kicad_pcb next to the .hyp")
    ap.add_argument("--refill", action="store_true",
                    help="refill zones with KiCad's zone filler first (default: use the fills as saved)")
    ap.add_argument("--traces", default="auto", metavar="auto|none|NET,...",
                    help="write strip-shaped pours as traces (centreline + width), so HyperLynx models "
                         "their transmission lines, loss and crosstalk: 'auto' (default) every net that "
                         "is >= 95 %% strips no wider than --trace-max-width, 'none' (KiCad's own output), "
                         "or the nets named")
    ap.add_argument("--trace-max-width", type=float, default=TRACE_MAX_WIDTH_MM, metavar="MM",
                    help=f"auto: widest strip of a net made traces (default {TRACE_MAX_WIDTH_MM} mm)")
    args = ap.parse_args(argv)
    suffix = args.input.suffix.lower()
    out = args.out or args.input.with_suffix(".hyp")

    if suffix == ".hyp":
        if out.resolve() == args.input.resolve():
            ap.error("a .hyp input needs -o (a different file): the input is not overwritten")
        out.write_text(args.input.read_text(encoding="utf-8"), encoding="utf-8")
    elif suffix == ".kicad_pcb":
        write_hyp(args.input, out, refill=args.refill)
    else:
        if not args.stack:
            ap.error("a GDS input needs --stack (its layer mapping and stackup)")
        from layz import gds2pcb
        with tempfile.TemporaryDirectory() as tmp:
            pcb = out.with_suffix(".kicad_pcb") if args.keep_pcb else Path(tmp) / (out.stem + ".kicad_pcb")
            gds2pcb.main(["--lay", str(args.input), "-o", str(pcb), "--stack", str(args.stack)])
            write_hyp(pcb, out, refill=args.refill)
    traces_pass(out, args.traces, args.trace_max_width)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
