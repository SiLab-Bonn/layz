"""A GDS's nets: KLayout's connectivity of the copper and via layers of a layz stack
(LayoutToNetlist), and the text labels on them. `layz lvs` compares them with a schematic;
`layz gds2pcb` names the board's nets from them.

A label names the net whose copper its origin lies on. Labels are read from each copper
layer's label layers (its datatype 1, 6/0 -> 6/1, or what the stack lists as labels = [...])
and from the copper drawing layers themselves. Its text is a net name ("D4_N", or "/D4_N"), or
REF.PIN of a schematic pin ("V4.102").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import klayout.db as kdb

PIN = re.compile(r"[A-Za-z]+\d+\.\w+")  # REF.PIN: a pin label, not a net name


@dataclass
class Label:
    text: str
    x: float  # µm
    y: float
    layer: str  # the label's L/D
    copper: str  # the copper layer (L/D) it names
    net: int | None  # layout net it sits on (cluster id), None: on no copper

    @property
    def is_pin(self) -> bool:
        return bool(PIN.fullmatch(self.text))


def _ld(s: str) -> tuple[int, int]:
    a, b = s.split("/")
    return int(a), int(b)


class Connectivity:
    """The nets of ``gds`` (its top cell, flattened) on the copper and vias of ``process``."""

    def __init__(self, gds: Path, process):
        ly = kdb.Layout()
        ly.read(str(gds))
        top = ly.top_cell()
        top.flatten(-1, True)  # labels and copper in one coordinate system; boards are small
        self.dbu = ly.dbu
        self.l2n = l2n = kdb.LayoutToNetlist(kdb.RecursiveShapeIterator(ly, top, []))

        self.regions = {}  # "L/D" -> region, copper and via layers
        for layer in process.copper:
            li = ly.find_layer(*_ld(layer.gds)) if layer.gds else None
            if li is not None:
                self.regions[layer.gds] = l2n.make_polygon_layer(li, layer.name)
                l2n.connect(self.regions[layer.gds])
        self.copper = {g for g in self.regions}
        self.names = {layer.gds: layer.name for layer in process.copper if layer.gds}
        for via in process.vias:
            li = ly.find_layer(*_ld(via.gds))
            if li is None:
                continue
            v = self.regions[via.gds] = l2n.make_polygon_layer(li, f"via {via.gds}")
            l2n.connect(v)
            for side in (via.top, via.bottom):
                g = process.by_name(side).gds
                if g in self.copper:
                    l2n.connect(v, self.regions[g])

        # label layers: each copper drawing layer and the stack's label layers
        label_map = [(g, g) for g in self.copper]
        for layer in process.copper:
            for lab in layer.labels:
                label_map.append((lab, layer.gds))

        l2n.extract_netlist()
        circuit = l2n.netlist().circuit_by_name(top.name) or next(l2n.netlist().each_circuit_top_down())
        self.nets = {n.cluster_id: n.expanded_name() for n in circuit.each_net()}

        self.labels = []
        for lab, cu in label_map:
            if cu not in self.copper:
                continue
            li = ly.find_layer(*_ld(lab))
            if li is None:
                continue
            for sh in top.shapes(li).each():
                if not sh.is_text():
                    continue
                p = sh.text_pos
                net = l2n.probe_net(self.regions[cu], kdb.Point(p.x, p.y))
                self.labels.append(Label(sh.text_string.strip(), p.x * self.dbu, p.y * self.dbu, lab, cu, net.cluster_id if net is not None else None))

    def net_at(self, gds: str, x_um: float, y_um: float) -> int | None:
        """The net (cluster id) of the shape on layer ``gds`` (copper or via) at a point."""
        net = self.l2n.probe_net(self.regions[gds], kdb.DPoint(x_um, y_um))
        return net.cluster_id if net is not None else None

    def net_names(self) -> tuple[dict[int, str], list[str]]:
        """Each labelled net's name, from its net labels, and what is wrong: a net with two
        names (a short), a net label on no copper."""
        named: dict[int, dict[str, Label]] = {}
        problems = []
        for lab in self.labels:
            if lab.is_pin:
                continue
            if lab.net is None:
                problems.append(f"net label {lab.text!r} at ({lab.x:.1f}, {lab.y:.1f}) µm on {lab.layer} lies on no {self.names[lab.copper]} copper")
                continue
            named.setdefault(lab.net, {}).setdefault(lab.text.rsplit("/", 1)[-1], lab)
        names = {}
        for net, by_name in named.items():
            if len(by_name) > 1:
                where = ", ".join(f"{t!r} at ({lab.x:.1f}, {lab.y:.1f})" for t, lab in sorted(by_name.items()))
                problems.append(f"one net carries several names (a short): {where}")
            names[net] = min(by_name)
        return names, problems
