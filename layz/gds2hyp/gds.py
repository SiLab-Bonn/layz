"""A HyperLynx .hyp straight from a GDS and its layz stack: no KiCad board in between.

    {BOARD ...}       the outline layer's shapes (else the copper's bounding box)
    {STACKUP ...}     the stack's layers, by the stack's names (M3, P3, ...)
    {DEVICES ...}     one per REF of the pin labels (REF.PIN, "V4.102")
    {PADSTACK=n ...}  one per pin pad size and per via, numbered in order of first use
    {NET="..." ...}   per net, named by its net labels: PIN at each pin label (its pad: the
                      smallest pad-layer shape under it), VIA per via shape, and the net's
                      merged copper per layer as POLYGON / POLYVOID

Coordinates are the GDS's, in inches (Y up, as in the GDS). Every net must carry a net label,
as in layz.gds2pcb; a net with two names, or a label on no copper, stops it too.
"""

from __future__ import annotations

from pathlib import Path

import klayout.db as kdb

from layz.connectivity import Connectivity, _ld

RESISTIVITY = 1.724e-8  # copper bulk resistivity, Ω·m (what KiCad's exporter writes)
INCH_UM = 25400.0


def stackup(process) -> str:
    """The {STACKUP} section of a stack, by its own layer names."""
    lines = ["{STACKUP\n"]
    for l in process.layers:
        t = l.thickness_um / INCH_UM
        if l.type == "copper":
            lines.append('  (SIGNAL T=%g P=%g C=%g L="%.20s" M=COPPER)\n' % (t, 0.0, RESISTIVITY, l.name))
        else:
            lines.append('  (DIELECTRIC T=%g C=%g L="%.20s" M="%.20s")\n' % (t, l.k, l.name, l.material or ("Solder Mask" if l.type == "mask" else "FR4")))
    return "".join(lines) + "}\n\n"


def write_hyp(gds: Path, process, hyp: Path, drill_shrink_um: float = 10.0) -> None:
    conn = Connectivity(gds, process)
    names, problems = conn.net_names()
    problems += [f"pin label {lab.text!r} at ({lab.x:.1f}, {lab.y:.1f}) µm on {lab.layer} lies on no {conn.names[lab.copper]} copper" for lab in conn.labels if lab.is_pin and lab.net is None]
    unnamed = sorted(set(conn.nets) - set(names))
    for net in unnamed:
        g, box = next(((g, r.bbox()) for g in conn.regions if not (r := conn.shapes(g, net)).is_empty()), (None, None))
        if g is None:
            continue  # no shapes
        c = box.center()
        problems.append(f"net without a label: {conn.names.get(g, 'via ' + g)} {g} at ({c.x * conn.dbu:.1f}, {c.y * conn.dbu:.1f}) µm")
    if problems:
        shown = "\n  ".join(problems[:30]) + (f"\n  ... and {len(problems) - 30} more" if len(problems) > 30 else "")
        raise SystemExit(f"{gds}: the GDS's net labels don't name every net (put a text with the net's name on the copper's label layer, datatype 1: 6/0 -> 6/1):\n  {shown}")

    dbu = conn.dbu
    inch = lambda v_db: v_db * dbu / INCH_UM  # database units -> inches
    out: list[str] = ["{VERSION=2.14}\n", "{UNITS=ENGLISH LENGTH}\n\n"]

    # board outline: the outline layer's merged shapes, else the copper's bounding box
    outline = kdb.Region()
    if process.outline and (li := conn.layout.find_layer(*_ld(process.outline))) is not None:
        outline = kdb.Region(conn.top.begin_shapes_rec(li)).merged()
    if outline.is_empty():
        box = kdb.Box()
        for r in conn.regions.values():
            box += kdb.Region(r).bbox()
        outline = kdb.Region(box)
    out.append(f'{{BOARD "{Path(gds).name}"\n')
    for poly in outline.each():
        pts = list(poly.each_point_hull())
        for a, b in zip(pts, pts[1:] + pts[:1]):
            out.append("  (PERIMETER_SEGMENT X1=%.9f Y1=%.9f X2=%.9f Y2=%.9f)\n" % (inch(a.x), inch(a.y), inch(b.x), inch(b.y)))
    out.append("}\n\n")

    out.append(stackup(process))

    # padstacks: a pin's pad is the smallest shape of its copper layer under the pin label;
    # a via is round, as wide as its shape's smaller side, on the two layers it joins
    stacks: dict[tuple, int] = {}
    stack_text: list[str] = []

    def padstack(drill_in: float, shapes: tuple) -> int:
        key = (round(drill_in, 9), shapes)
        if key not in stacks:
            stacks[key] = len(stacks)
            body = "".join('  ("%s", %d, %.9f, %.9f, 0.0, M)\n' % s for s in shapes)
            stack_text.append("{PADSTACK=%d, %.9f\n%s}\n\n" % (stacks[key], drill_in, body))
        return stacks[key]

    unmerged = {}
    for layer in process.copper:
        li = conn.layout.find_layer(*_ld(layer.gds)) if layer.gds else None
        if li is not None:
            r = kdb.Region(conn.top.begin_shapes_rec(li))
            r.merged_semantics = False
            unmerged[layer.gds] = r

    by_net: dict[int, list[str]] = {net: [] for net in names}
    devices: dict[str, str] = {}
    for lab in conn.labels:
        if not lab.is_pin:
            continue
        p = kdb.Point(round(lab.x / dbu), round(lab.y / dbu))
        under = [poly for poly in unmerged[lab.copper].interacting(kdb.Region(kdb.Box(p, p).enlarged(1))).each()]
        box = min(under, key=lambda q: q.area()).bbox()
        cu = conn.names[lab.copper]
        ps = padstack(0.0, ((cu, 1, inch(box.width()), inch(box.height())),))
        devices.setdefault(lab.text.split(".")[0], cu)
        by_net[lab.net].append('  (PIN X=%.10f Y=%.10f R="%s" P=%d)\n' % (inch(p.x), inch(p.y), lab.text, ps))

    for via in process.vias:
        if via.gds not in conn.regions:
            continue
        li = conn.layout.find_layer(*_ld(via.gds))
        r = kdb.Region(conn.top.begin_shapes_rec(li))
        r.merged_semantics = False
        for poly in r.each():
            box = poly.bbox()
            if min(box.width(), box.height()) == 0:
                continue  # a point marker, no via
            c = box.center()
            net = conn.net_at(via.gds, c.x * dbu, c.y * dbu)
            size = min(box.width(), box.height()) * dbu
            ps = padstack(max(size - drill_shrink_um, 0.001) / INCH_UM, tuple((name, 0, size / INCH_UM, size / INCH_UM) for name in (via.top, via.bottom)))
            by_net[net].append("  (VIA X=%.10f Y=%.10f P=%d)\n" % (inch(c.x), inch(c.y), ps))

    poly_id = 1
    for net in by_net:
        for layer in process.copper:
            if layer.gds not in conn.copper:
                continue
            for poly in conn.shapes(layer.gds, net).each():
                for k, chain in enumerate([list(poly.each_point_hull())] + [list(poly.each_point_hole(h)) for h in range(poly.holes())]):
                    head = '{POLYGON T=POUR L="%s" ID=%d' % (layer.name, poly_id) if k == 0 else "{POLYVOID ID=%d" % poly_id
                    out_lines = ["  %s X=%.10f Y=%.10f\n" % (head, inch(chain[0].x), inch(chain[0].y))]
                    out_lines += ["    (LINE X=%.10f Y=%.10f)\n" % (inch(q.x), inch(q.y)) for q in chain + chain[:1]]
                    by_net[net] += out_lines + ["  }\n"]
                poly_id += 1

    out.append("{DEVICES\n")
    out += [f'  (? REF="{ref}" L="{cu}")\n' for ref, cu in devices.items()]
    out.append("}\n\n")
    out += stack_text
    merged: dict[str, list[str]] = {}  # one NET per name: separate pieces with the same label are one net
    for net, lines in by_net.items():
        merged.setdefault(names[net], []).extend(lines)
    for name in sorted(merged):
        out.append(f'{{NET="{name}"\n')
        out += merged[name]
        out.append("}\n\n")
    hyp.write_text("".join(out), encoding="utf-8")
    print(f"wrote {hyp}: {len(merged)} nets, {sum(1 for lab in conn.labels if lab.is_pin)} pins, {len(devices)} devices, {len(stacks)} padstacks")
