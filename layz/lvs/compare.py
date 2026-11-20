"""Compare a GDS layout's connectivity with a KiCad schematic's netlist.

For interconnect (RDL, PCB) there are no devices to recognise: the comparison is net by net.
KLayout extracts the layout's nets from the copper and via layers of a layz stack
(LayoutToNetlist), and text labels in the layout say what each net is meant to be:

    net label   text = a schematic net name ("D4_N", or "/D4_N"): names the net it sits on
    pin label   text = REF.PIN of a schematic pin ("V4.102"): that pin is at this spot

A label names the net whose copper its origin lies on. Labels are read from

    * each copper layer's label layer: its datatype 1 (6/0 -> 6/1), or what the stack lists as
      labels = [...] for that layer,
    * the copper drawing layers themselves (a text on 6/0 names the 6/0 net under it).

Checks (each listed with where it is, also as a KLayout marker database, lvs.lyrdb):

    open        one schematic net on several layout nets (its pins, or its name, are split)
    short       one layout net carrying several schematic nets (pins or names)
    unknown     a label naming no schematic net or pin
    unlabelled  schematic nets no label checks (info: add labels to cover them)

A flow runs it with layz.lvs.run.lvs(GDS, OUT, stack="uni-bonn-rdl", schematic=SCH), and
layz.lvs.analysis.findings fails on opens, shorts or unknown labels.
"""

from __future__ import annotations

import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import klayout.db as kdb
import klayout.rdb as krdb

from layz.connectivity import Connectivity, Label

# ------------------------------------------------------------------------------- schematic side


@dataclass
class Schematic:
    nets: dict[str, set[tuple[str, str]]]  # net name -> {(ref, pin)}
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
        from layz import kicad

        cli = kicad.cli()
        if not cli:
            raise SystemExit("kicad-cli not found: run install/kicad.sh, or export the netlist in KiCad and pass the .net file")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "netlist.net"
            from layz import log

            if log.run("kicad-cli", [cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(path)]):
                raise SystemExit(f"kicad-cli could not export the netlist of {path}")
            return read_netlist(out.read_text(encoding="utf-8"))
    return read_netlist(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- layout side


def extract(gds: Path, process) -> tuple[dict[int, str], list[Label], dict[str, str]]:
    """Layout nets (cluster id -> KLayout's name for it), every label probed onto its net, and
    the copper layers' names by L/D."""
    c = Connectivity(gds, process)
    return c.nets, c.labels, c.names


# ------------------------------------------------------------------------------- comparison


@dataclass
class Finding:
    kind: str  # open | short | unknown | floating
    what: str
    where: list[tuple[float, float, str]]  # (x, y, label text) in µm


def compare(sch: Schematic, labels: list[Label]) -> tuple[list[Finding], dict]:
    by_name = {norm(n): n for n in sch.nets}
    pins = {f"{r}.{p}".upper(): (r, p) for r, p in sch.pin_net}
    findings: list[Finding] = []
    net_of_sch = defaultdict(lambda: defaultdict(list))  # schematic net -> layout net -> labels
    sch_of_net = defaultdict(lambda: defaultdict(list))  # layout net -> schematic net -> labels
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
            findings.append(Finding("unknown", f"label {lab.text!r} names no schematic net or pin", [(lab.x, lab.y, lab.text)]))
            continue
        if lab.net is None:
            findings.append(Finding("floating", f"label {lab.text!r} ({sn}) is not on {lab.copper} copper", [(lab.x, lab.y, lab.text)]))
            continue
        net_of_sch[sn][lab.net].append(lab)
        sch_of_net[lab.net][sn].append(lab)
    for sn, parts in sorted(net_of_sch.items()):
        if len(parts) > 1:
            findings.append(Finding("open", f"{sn} is split over {len(parts)} layout nets", [(l.x, l.y, l.text) for labs in parts.values() for l in labs]))
    for ln, snets in sorted(sch_of_net.items()):
        if len(snets) > 1:
            findings.append(Finding("short", f"one layout net joins {', '.join(sorted(snets))}", [(l.x, l.y, l.text) for labs in snets.values() for l in labs]))
    covered = set(net_of_sch)
    stats = {"schematic nets": len(sch.nets), "checked nets": len(covered), "unchecked nets": sorted(set(sch.nets) - covered), "pins checked": f"{len(checked_pins)} of {len(sch.pin_net)}", "labels": len(labels)}
    return findings, stats


def write_report(path: Path, top: str, findings: list[Finding]) -> None:
    """KLayout marker database: one category per kind, a marker per label involved."""
    rdb = krdb.ReportDatabase("layz.lvs")
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
