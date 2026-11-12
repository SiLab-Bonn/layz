"""Process stack files: one TOML file per process (FR4 PCB, RDL, flex), read by every layz tool.

A stack lists the physical layers top to bottom, each with its thickness; heights (z) are
derived from the order, never typed. Copper layers name the GDS layer they're drawn on, via
layers the two copper layers they join. From this one description layz writes the KiCad board
stackup (`layz gds2pcb --stack`), so the .kicad_pcb, the HyperLynx .hyp (`layz hyp`) and the
FasterCap model (`layz pex`) all carry the same stack; a GDS can also go to `layz pex --stack`
directly.

    name = "SiLab RDL, 4 copper"     # free text
    outline = "70/0"                 # GDS layer of the board/die outline (optional)
    halo_um = 200                    # pex: dielectric slabs extend this far past the copper

    [[layer]]                        # top to bottom
    name = "F.Mask"
    type = "mask"                    # mask | copper | dielectric
    thickness_um = 1.0
    er = 3.3                         # relative permittivity (mask, dielectric)
    material = "Polyimide"           # optional, written to KiCad and HyperLynx
    loss_tangent = 0.02              # optional (Df), written to KiCad

    [[layer]]
    name = "F.Cu"                    # KiCad layer name: F.Cu, In1.Cu, In2.Cu, ..., B.Cu
    type = "copper"
    thickness_um = 0.5
    gds = "8/0"                      # GDS layer/datatype drawn on this copper layer
    pads = true                      # gds2pcb: shapes in sub-cells become footprint pads
    zones = false                    # gds2pcb: top-level shapes become copper zones (default true)

    [[via]]
    gds = "7/0"
    top = "F.Cu"
    bottom = "In1.Cu"

Units are µm throughout. Masks may only be the first and last layers. The copper layers must
be KiCad's names, in order (F.Cu, In1.Cu, ..., B.Cu), wherever the stack goes to KiCad or
HyperLynx; a stack used only by `layz pex` on a GDS may name them freely.

This module also reads the stackup out of a .kicad_pcb (the reverse direction), which is how
`layz pex` and `layz hyp` get the stack of a KiCad board.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

K_DEFAULT = {"mask": 3.3, "dielectric": 4.5}  # KiCad's own defaults when no εr is given
TYPES = ("copper", "dielectric", "mask")


@dataclass
class Layer:
    name: str
    type: str                     # copper | dielectric | mask
    thickness_um: float
    er: float | None = None
    material: str | None = None
    loss_tangent: float | None = None
    gds: str | None = None        # copper only: "L/D"
    pads: bool = False            # copper only: sub-cell shapes become footprint pads
    zones: bool = True            # copper only: top-level shapes become zones
    z_um: float = 0.0             # bottom face, filled in by Process (z = 0 at the bottom)

    @property
    def k(self) -> float:
        return self.er or K_DEFAULT["mask" if self.type == "mask" else "dielectric"]


@dataclass
class ViaLayer:
    gds: str
    top: str
    bottom: str


@dataclass
class Process:
    name: str
    layers: list[Layer]
    vias: list[ViaLayer] = field(default_factory=list)
    outline: str | None = None
    halo_um: float = 200.0

    def __post_init__(self):
        z = 0.0
        for layer in reversed(self.layers):
            layer.z_um = z
            z += layer.thickness_um

    @property
    def copper(self) -> list[Layer]:
        return [l for l in self.layers if l.type == "copper"]

    def by_name(self, name: str) -> Layer:
        for l in self.layers:
            if l.name == name:
                return l
        raise KeyError(name)

    @property
    def thickness_um(self) -> float:
        return sum(l.thickness_um for l in self.layers)

    # ----------------------------------------------------------------- KiCad

    def check_kicad(self) -> None:
        names = [l.name for l in self.copper]
        n = len(names)
        want = ["F.Cu", *[f"In{i}.Cu" for i in range(1, n - 1)], "B.Cu"] if n >= 2 else ["F.Cu"]
        if names != want:
            raise ValueError(f"for KiCad the copper layers must be {want} in order, not {names}")

    def kicad_stackup(self) -> str:
        """The (stackup ...) block of a .kicad_pcb (KiCad lengths in mm)."""
        self.check_kicad()
        out = ["\t\t(stackup"]
        n_diel = 0
        for i, l in enumerate(self.layers):
            mm = f"{l.thickness_um / 1000:.6g}"
            mat = f' (material "{l.material}")' if l.material else ""
            if l.type == "mask":
                side = "F" if i == 0 else "B"
                kind = "Top Solder Mask" if side == "F" else "Bottom Solder Mask"
                out.append(f'\t\t\t(layer "{side}.Mask" (type "{kind}") (thickness {mm}){mat}'
                           f" (epsilon_r {l.k:g}))")
            elif l.type == "copper":
                out.append(f'\t\t\t(layer "{l.name}" (type "copper") (thickness {mm}))')
            else:
                n_diel += 1
                out.append(f'\t\t\t(layer "dielectric {n_diel}" (type "core") (thickness {mm})'
                           f"{mat} (epsilon_r {l.k:g}) (loss_tangent {l.loss_tangent or 0:g}))")
        out += ['\t\t\t(copper_finish "None")', "\t\t\t(dielectric_constraints no)", "\t\t)"]
        return "\n".join(out) + "\n"

    def gds_layer_maps(self):
        """gds2pcb's maps: zones {gds: copper}, vias {gds: (a, b)}, pads {gds: copper}."""
        key = lambda s: tuple(int(x) for x in s.split("/"))
        zones = {key(l.gds): l.name for l in self.copper if l.gds and l.zones}
        pads = {key(l.gds): l.name for l in self.copper if l.gds and l.pads}
        vias = {key(v.gds): (v.top, v.bottom) for v in self.vias}
        return zones, vias, pads


def _check(p: Process, path: str) -> Process:
    names = [l.name for l in p.layers]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: layer names must be unique")
    for i, l in enumerate(p.layers):
        if l.type not in TYPES:
            raise ValueError(f"{path}: layer {l.name}: type must be one of {TYPES}")
        if l.thickness_um <= 0:
            raise ValueError(f"{path}: layer {l.name}: thickness_um must be > 0")
        if l.type == "mask" and 0 < i < len(p.layers) - 1:
            raise ValueError(f"{path}: mask layer {l.name} must be the first or last layer")
        if l.gds and not re.fullmatch(r"\d+/\d+", l.gds):
            raise ValueError(f"{path}: layer {l.name}: gds must look like \"8/0\"")
    copper = {l.name for l in p.copper}
    for v in p.vias:
        if v.top not in copper or v.bottom not in copper:
            raise ValueError(f"{path}: via {v.gds}: top/bottom must be copper layers")
        if names.index(v.top) > names.index(v.bottom):
            raise ValueError(f"{path}: via {v.gds}: top ({v.top}) must be above bottom ({v.bottom})")
    return p


def load(path: str | Path) -> Process:
    d = tomllib.loads(Path(path).read_text())
    if "layer" not in d:
        raise ValueError(f"{path}: no [[layer]] entries (a layz stack lists its layers top to bottom)")
    layers = [Layer(name=x["name"], type=x["type"], thickness_um=float(x["thickness_um"]),
                    er=x.get("er"), material=x.get("material"), loss_tangent=x.get("loss_tangent"),
                    gds=x.get("gds"),
                    pads=bool(x.get("pads", False)), zones=bool(x.get("zones", True)))
              for x in d["layer"]]
    vias = [ViaLayer(gds=v["gds"], top=v["top"], bottom=v["bottom"]) for v in d.get("via", [])]
    return _check(Process(name=d.get("name", Path(path).stem), layers=layers, vias=vias,
                          outline=d.get("outline"), halo_um=float(d.get("halo_um", 200.0))),
                  str(path))


# ------------------------------------------------------------------- from a .kicad_pcb


def _sexp(text: str) -> list:
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack: list[list] = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(t.strip('"'))
    return stack[0]


def from_kicad_pcb(pcb_path: str | Path) -> Process | None:
    """The board's (stackup ...) as a Process, or None if the board has no stackup."""
    text = Path(pcb_path).read_text()
    start = text.find("(stackup")
    if start < 0:
        return None
    depth = 0
    for end in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[end], 0)
        if depth == 0:
            break
    layers = []
    for node in _sexp(text[start:end + 1])[0][1:]:
        if not isinstance(node, list) or node[0] != "layer":
            continue
        d = {"name": node[1]}
        for kv in node[2:]:
            if isinstance(kv, list) and len(kv) >= 2:
                d.setdefault(kv[0], kv[1])  # first sublayer of a multi-sublayer dielectric
        t = d.get("type", "")
        kind = ("copper" if t == "copper" else "mask" if "Mask" in t
                else "dielectric" if t in ("core", "prepreg") or d["name"].startswith("dielectric")
                else None)
        mm = float(d.get("thickness", 0) or 0)
        if kind is None or mm <= 0:
            continue  # silkscreen, paste, ...
        layers.append(Layer(name=d["name"], type=kind, thickness_um=mm * 1000,
                            er=float(d["epsilon_r"]) if "epsilon_r" in d else None,
                            material=d.get("material"),
                            loss_tangent=float(d["loss_tangent"]) if "loss_tangent" in d else None))
    return Process(name=Path(pcb_path).stem, layers=layers)


def kicad_default(cu_names: list[str], board_mm: float) -> Process:
    """KiCad's default stack: 35 µm copper, FR4 4.5, 10 µm mask 3.3, total = board thickness."""
    n = len(cu_names)
    diel = (board_mm * 1000 - n * 35 - 20) / max(n - 1, 1)
    layers = [Layer("F.Mask", "mask", 10)]
    for i, name in enumerate(cu_names):
        layers.append(Layer(name, "copper", 35))
        if i < n - 1:
            layers.append(Layer(f"dielectric {i + 1}", "dielectric", diel, material="FR4"))
    layers.append(Layer("B.Mask", "mask", 10))
    return Process(name="KiCad default", layers=layers)
