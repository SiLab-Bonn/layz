"""`layz lvs`: compare a GDS layout's connectivity with a KiCad schematic's netlist.

For interconnect (RDL, PCB) there are no devices to recognise: the comparison is net by net.
KLayout extracts the layout's nets from the copper and via layers of a layz stack
(LayoutToNetlist), and text labels in the layout say what each net is meant to be:

    net label   text = a schematic net name ("D4_N", or "/D4_N"): names the net it sits on
    pin label   text = REF.PIN of a schematic pin ("V4.102"): that pin is at this spot

A label names the net whose copper its origin lies on. Labels are read from

    * each copper layer's label layer: its datatype 1 (6/0 -> 6/1), or what the stack lists as
      labels = [...] for that layer,
    * the copper drawing layers themselves (a text on 6/0 names the 6/0 net under it),
    * --labels L/D:COPPER, a label layer tied to one copper layer (e.g. 80/7:6/0).

Checks (each listed with where it is, also as a KLayout marker database with --report):

    open        one schematic net on several layout nets (its pins, or its name, are split)
    short       one layout net carrying several schematic nets (pins or names)
    unknown     a label naming no schematic net or pin
    unlabelled  schematic nets no label checks (info: add labels to cover them)

    layz lvs --lay design.gds --stack uni-bonn-rdl --sch design.kicad_sch
             [--labels 80/7:6/0] [--report lvs.lyrdb]
Exit status 0 when there are no opens, shorts or unknown labels, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import klayout.db as kdb
import klayout.rdb as krdb

from layz import stack as stackfile


# ------------------------------------------------------------------------------- schematic side

@dataclass
class Schematic:
    nets: dict[str, set[tuple[str, str]]]          # net name -> {(ref, pin)}
    pin_net: dict[tuple[str, str], str] = field(default_factory=dict)

    def __post_init__(self):
        self.pin_net = {p: n for n, pins in self.nets.items() for p in pins}


def norm(name: str) -> str:
    """Net names compare without KiCad's sheet path ("/D4_N" == "D4_N") and case."""
    return name.rsplit("/", 1)[-1].strip().upper()


def read_netlist(text: str) -> Schematic:
    """A KiCad netlist (kicad-cli sch export netlist, kicadsexpr): nets and their nodes."""
    nets: dict[str, set] = {}
    for block in re.split(r"\(net\s+\(code", text)[1:]:
        m = re.search(r'\(name\s+"((?:\\.|[^"\\])*)"\)', block)
        if not m:
            continue
        nodes = re.findall(r'\(node\s+\(ref\s+"([^"]*)"\)\s+\(pin\s+"([^"]*)"\)', block)
        nets[m.group(1)] = set(nodes)
    return Schematic(nets)


def schematic_netlist(path: Path) -> Schematic:
    if path.suffix == ".kicad_sch":
        cli = shutil.which("kicad-cli")
        if not cli:
            raise SystemExit("kicad-cli not found: export the netlist in KiCad and pass the .net file")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "netlist.net"
            subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(path)],
                           check=True, capture_output=True)
            return read_netlist(out.read_text(encoding="utf-8"))
    return read_netlist(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- layout side

@dataclass
class Label:
    text: str
    x: float          # µm
    y: float
    layer: str        # the label's L/D
    copper: str       # the copper layer (L/D) it names
    net: int | None   # layout net it sits on (cluster id), None: on no copper


def _ld(s: str) -> tuple[int, int]:
    a, b = s.split("/")
    return int(a), int(b)


def extract(gds: Path, process, extra_labels: list[str]) -> tuple[dict[int, str], list[Label]]:
    """Layout nets (cluster id -> KLayout's name for it) and every label, probed onto its net."""
    ly = kdb.Layout()
    ly.read(str(gds))
    top = ly.top_cell()
    top.flatten(-1, True)  # labels and copper in one coordinate system; boards are small
    l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))

    copper = {}  # "L/D" -> region
    for layer in process.copper:
        if not layer.gds:
            continue
        li = ly.find_layer(*_ld(layer.gds))
        if li is None:
            continue
        copper[layer.gds] = l2n.make_polygon_layer(li, layer.name)
        l2n.connect(copper[layer.gds])
    names = {layer.gds: layer.name for layer in process.copper if layer.gds}
    for via in process.vias:
        li = ly.find_layer(*_ld(via.gds))
        if li is None:
            continue
        v = l2n.make_polygon_layer(li, f"via {via.gds}")
        l2n.connect(v)
        for side in (via.top, via.bottom):
            g = process.by_name(side).gds
            if g in copper:
                l2n.connect(v, copper[g])

    # label layers: each copper drawing layer, the stack's label purposes, --labels
    label_map: list[tuple[str, str]] = [(g, g) for g in copper]
    for layer in process.copper:
        for lab in getattr(layer, "labels", []) or []:
            label_map.append((lab, layer.gds))
    for spec in extra_labels:
        lab, _, cu = spec.partition(":")
        if not cu:
            raise SystemExit(f"--labels {spec}: give the copper layer it names, as L/D:COPPER (e.g. 80/7:6/0)")
        if cu not in copper:
            raise SystemExit(f"--labels {spec}: {cu} is not a copper layer of the stack ({', '.join(copper)})")
        label_map.append((lab, cu))

    l2n.extract_netlist()
    circuit = l2n.netlist().circuit_by_name(top.name) or next(l2n.netlist().each_circuit_top_down())
    nets = {n.cluster_id: n.expanded_name() for n in circuit.each_net()}

    labels = []
    dbu = ly.dbu
    for lab, cu in label_map:
        li = ly.find_layer(*_ld(lab))
        if li is None:
            continue
        for sh in top.shapes(li).each():
            if not sh.is_text():
                continue
            p = sh.text_pos
            net = l2n.probe_net(copper[cu], kdb.Point(p.x, p.y))
            labels.append(Label(sh.text_string.strip(), p.x * dbu, p.y * dbu, lab, cu,
                                net.cluster_id if net is not None else None))
    return nets, labels, names


# ------------------------------------------------------------------------------- comparison

@dataclass
class Finding:
    kind: str                     # open | short | unknown | floating
    what: str
    where: list[tuple[float, float, str]]  # (x, y, label text) in µm


def compare(sch: Schematic, labels: list[Label]) -> tuple[list[Finding], dict]:
    by_name = {norm(n): n for n in sch.nets}
    pins = {f"{r}.{p}".upper(): (r, p) for r, p in sch.pin_net}
    findings: list[Finding] = []
    net_of_sch = defaultdict(lambda: defaultdict(list))   # schematic net -> layout net -> labels
    sch_of_net = defaultdict(lambda: defaultdict(list))   # layout net -> schematic net -> labels
    checked_pins, named = set(), set()
    for lab in labels:
        key = lab.text.upper()
        if key in pins:
            sn = sch.pin_net[pins[key]]
            checked_pins.add(pins[key])
        elif norm(lab.text) in by_name:
            sn = by_name[norm(lab.text)]
            named.add(sn)
        else:
            findings.append(Finding("unknown", f"label {lab.text!r} names no schematic net or pin",
                                    [(lab.x, lab.y, lab.text)]))
            continue
        if lab.net is None:
            findings.append(Finding("floating", f"label {lab.text!r} ({sn}) is not on {lab.copper} copper",
                                    [(lab.x, lab.y, lab.text)]))
            continue
        net_of_sch[sn][lab.net].append(lab)
        sch_of_net[lab.net][sn].append(lab)
    for sn, parts in sorted(net_of_sch.items()):
        if len(parts) > 1:
            findings.append(Finding("open", f"{sn} is split over {len(parts)} layout nets",
                                    [(l.x, l.y, l.text) for labs in parts.values() for l in labs]))
    for ln, snets in sorted(sch_of_net.items()):
        if len(snets) > 1:
            findings.append(Finding("short", f"one layout net joins {', '.join(sorted(snets))}",
                                    [(l.x, l.y, l.text) for labs in snets.values() for l in labs]))
    covered = set(net_of_sch)
    stats = {
        "schematic nets": len(sch.nets),
        "checked nets": len(covered),
        "unchecked nets": sorted(set(sch.nets) - covered),
        "pins checked": f"{len(checked_pins)} of {len(sch.pin_net)}",
        "labels": len(labels),
    }
    return findings, stats


def write_report(path: Path, top: str, findings: list[Finding]) -> None:
    """KLayout marker database: one category per kind, a marker per label involved."""
    rdb = krdb.ReportDatabase("layz lvs")
    cell = rdb.create_cell(top)
    cats = {}
    for f in findings:
        if f.kind not in cats:
            cats[f.kind] = rdb.create_category(f.kind)
        for x, y, text in f.where:
            item = rdb.create_item(cell.rdb_id(), cats[f.kind].rdb_id())
            item.add_value(f"{f.what} ({text})")
            item.add_value(kdb.DBox(x - 2, y - 2, x + 2, y + 2))  # µm
    rdb.save(str(path))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lay", type=Path, required=True, help="layout (GDS/OASIS)")
    ap.add_argument("--stack", type=Path, required=True, help="layz stack (.toml): copper, vias, label layers")
    ap.add_argument("--sch", type=Path, required=True,
                    help="KiCad schematic (.kicad_sch, via kicad-cli) or its netlist (.net, kicadsexpr)")
    ap.add_argument("--labels", action="append", default=[], metavar="L/D:COPPER",
                    help="a label layer and the copper layer its texts name, e.g. 80/7:6/0 (repeatable)")
    ap.add_argument("--report", type=Path, help="write a KLayout marker database (.lyrdb) of the findings")
    a = ap.parse_args(argv)

    process = stackfile.load(a.stack)
    sch = schematic_netlist(a.sch)
    nets, labels, _ = extract(a.lay, process, a.labels)
    findings, stats = compare(sch, labels)

    print(f"layout: {len(nets)} nets, {stats['labels']} labels; schematic: {stats['schematic nets']} nets")
    print(f"checked: {stats['checked nets']} of {stats['schematic nets']} schematic nets, "
          f"{stats['pins checked']} pins")
    count = defaultdict(int)
    for f in findings:
        count[f.kind] += 1
    for kind in ("open", "short", "unknown", "floating"):
        items = [f for f in findings if f.kind == kind]
        if not items:
            continue
        print(f"\n{kind}: {len(items)}")
        for f in items[:25]:
            x, y, _ = f.where[0]
            print(f"  {f.what}  (at {x:.1f}, {y:.1f} µm)")
        if len(items) > 25:
            print(f"  ... {len(items) - 25} more")
    if stats["unchecked nets"]:
        u = stats["unchecked nets"]
        print(f"\nunlabelled: {len(u)} schematic nets have no label: {', '.join(u[:15])}{' ...' if len(u) > 15 else ''}")
    if a.report:
        ly = kdb.Layout()
        ly.read(str(a.lay))
        write_report(a.report, ly.top_cell().name, findings)
        print(f"\nwrote {a.report} (layz view {a.report} --lay {a.lay})")
    bad = count["open"] + count["short"] + count["unknown"]
    print("\nLVS " + ("clean" if not bad and stats["checked nets"] else
                      "incomplete: no label matched a schematic net" if not bad else "FAILED"))
    return 1 if bad or not stats["checked nets"] else 0


if __name__ == "__main__":
    sys.exit(main())
