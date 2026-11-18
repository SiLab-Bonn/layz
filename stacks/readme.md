# Stack files

A GDS carries only 2-D shapes; heights, thicknesses and permittivities come from a **stack
file**, one per process. It lists the layers top to bottom; z positions are derived from the
order. `layz pcb`, `hyp`, `pex` and `lvs` all read the same file.

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
pads = true                   # layz pcb: GDS sub-cells with these shapes become footprint pads
zones = false                 # layz pcb: top-level shapes become copper zones (default true)
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

Units are µm. `layz pcb --stack` writes the stack into the board as its KiCad physical stackup,
so the `.kicad_pcb`, the `.hyp` and the FasterCap model all carry it; a board made in KiCad uses
its own stackup (Board Setup > Physical Stackup). The full format is documented in
[src/layz/stack.py](../src/layz/stack.py).

| Stack file | Process | Source |
| --- | --- | --- |
| `uni_bonn_rdl.toml` | Uni Bonn RDL, Al on polyimide (obelix1: M2 + M3 on the chip pads) | asiclab `tech/uni-bonn-rdl` thicknesses, obelix1 KiCad mapping; polyimide εr and 8/0 to confirm |
| `multicb_4L-01.toml` | Multi-CB 4-layer FR4, 1.6 mm | Multi-CB defined buildup 4L-01 (mask assumed: 10 µm, εr 3.3) |
| `multicb_4L-02.toml` | Multi-CB 4-layer FR4, 1.0 mm | Multi-CB defined buildup 4L-02 (mask assumed) |
| `multicb_flex_2F-l.toml` | Multi-CB 2-layer flex, adhesiveless, 161 µm | Multi-CB standard 2F-l |
| `multicb_flex_2F-a.toml` | Multi-CB 2-layer flex, adhesive-bonded, 187 µm | Multi-CB standard 2F-a |

The Multi-CB files are their published standard buildups; for a board ordered with a custom
buildup, copy the closest one and enter the ordered thicknesses and materials.
