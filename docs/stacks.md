# Stack files

A GDS carries only 2-D shapes; heights, thicknesses and permittivities come from a **stack
file**, one per process. It lists the layers top to bottom; z positions are derived from the
order. `layz gds2pcb`, `gds2hyp`, `pex` and `lvs` all read the same file.

```toml
name = "SiLab RDL, 4 copper"
outline = "70/0"              # GDS layer of the board/die outline

[[layer]]
name = "F.Mask"
type = "mask"                 # mask | copper | dielectric
thickness_um = 1.0
er = 3.3

[[layer]]
name = "F.Cu"                 # KiCad names: F.Cu, In1.Cu, ..., B.Cu
type = "copper"
thickness_um = 0.5
gds = "8/0"                   # drawing layer
pads = true                   # layz gds2pcb: GDS sub-cells with these shapes become footprint pads
zones = false                 # layz gds2pcb: top-level shapes become copper zones (default true)
labels = ["8/1"]              # layz lvs: label layers (default: datatype 1 of the drawing layer)

[[layer]]
name = "DE_F.Cu"
type = "dielectric"
thickness_um = 4.0
er = 4.5
material = "FR4"
# ... more layers ...

[[via]]
gds = "7/0"
top = "F.Cu"
bottom = "In1.Cu"
```

Units are µm. `layz gds2pcb --stack` writes the stack into the board as its KiCad physical stackup,
so the `.kicad_pcb`, the `.hyp` and the FasterCap model all carry it; a board made in KiCad uses
its own stackup (Board Setup > Physical Stackup). The full format is documented in
[layz/stack.py](../layz/stack.py).

The processes in this repo are in [tech/](../tech): `uni-bonn-rdl` and the Multi-CB buildups in
`multicb/`, each with a readme on its source.
