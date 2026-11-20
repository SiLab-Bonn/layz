# Stack files

A GDS carries only 2-D shapes; heights, thicknesses and permittivities come from a **stack
file**, one per process. It lists the layers top to bottom; z positions are derived from the
order. `layz gds2pcb`, `gds2hyp`, `pex` and `lvs` all read the same file.

```toml
name = "Uni Bonn RDL"
outline = "70/0"              # GDS layer of the board/die outline

[[layer]]
name = "TopPad"               # free: the process's own layer names
type = "copper"               # copper | dielectric | mask
thickness_um = 0.5
gds = "8/0"                   # drawing layer
pads = true                   # layz gds2pcb: GDS sub-cells with these shapes become footprint pads
zones = false                 # layz gds2pcb: top-level shapes become copper zones (default true)
labels = ["8/1"]              # layz lvs: label layers (default: datatype 1 of the drawing layer)

[[layer]]
name = "P3"
type = "dielectric"
thickness_um = 5.0
er = 3.3
material = "Polyimide"

[[layer]]
name = "M3"
type = "copper"
thickness_um = 6.0
gds = "6/0"
# ... more layers ...

[[via]]
gds = "7/0"                   # P3 opening
top = "TopPad"
bottom = "M3"
```

Units are µm. Copper layers go to KiCad by their order, top to bottom: F.Cu, In1.Cu, ..., B.Cu;
a `.hyp` made from a GDS names them as the stack does (M3, M2, ...). Stacks of real PCBs
(tech/multicb) use KiCad's names, which map onto themselves.

`layz gds2pcb --stack` writes the stack into the board as its KiCad physical stackup,
so the `.kicad_pcb`, the `.hyp` and the FasterCap model all carry it; a board made in KiCad uses
its own stackup (Board Setup > Physical Stackup). The full format is documented in
[layz/stack.py](../layz/stack.py).

The processes in this repo are in [tech/](../tech): `uni-bonn-rdl` and the Multi-CB buildups in
`multicb/`, each with a readme on its source.
