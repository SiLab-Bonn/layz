# layz

Layout tools for SiLab's FR4 PCBs, in-house RDL chips (maskless lithography) and the flex PCBs
that connect them, as one command line tool:

```
layz drc       design rule check of a GDS (gdscheck, with the kit's deck)
layz pcb       GDS -> KiCad .kicad_pcb (copper zones, footprints, vias, outline, stackup)
layz nets      assign zone/via nets from a seed footprint's pad nets
layz hyp       .kicad_pcb or GDS -> HyperLynx .hyp (for SI/PI)
layz svg       GDS -> SVG preview
layz pex       3-D capacitance matrix with FasterCap/FastCap2 (.kicad_pcb, or GDS + stack)
layz field     electric field and potential from a `layz pex --charges` run
layz view      open a result: DRC report in KLayout, or ParaView renders of a field run
layz doctor    which external tools this machine has
```

`layz <command> -h` shows each command's options.

## Install

layz is a standard Python package (`pyproject.toml`, Python 3.12 to 3.15), installed with
Python's own `venv` and `pip`. It also uses tools that are not on PyPI:

| Tool | Needed for | Linux | macOS |
| --- | --- | --- | --- |
| KiCad (its `pcbnew` Python module, `kicad-cli`) | `pcb`, `hyp`, `pex` on boards, schematic netlists | [kicad.org/download/linux](https://www.kicad.org/download/linux/) | [kicad.org/download/macos](https://www.kicad.org/download/macos/) |
| KLayout | viewing GDS and DRC results | [klayout.de/build.html](https://www.klayout.de/build.html) | [klayout.de/build.html](https://www.klayout.de/build.html) |
| FasterCap (default) / FastCap2 | `pex`, `field` | `scripts/build_solvers.sh` (sources: [FasterCap](https://github.com/iic-jku/FasterCap), [FastCap2](https://github.com/martinjankoehler/FastCap2)) | [FasterCap releases](https://github.com/iic-jku/FasterCap/releases) (or `scripts/build_solvers.sh`) |
| gdscheck | `drc` | [github.com/aesc-silicon/gdscheck](https://github.com/aesc-silicon/gdscheck), with Rust's `cargo` ([rust-lang.org/tools/install](https://www.rust-lang.org/tools/install)) | same |
| ParaView (optional) | `view` of field results | [paraview.org/download](https://www.paraview.org/download/) | [paraview.org/download](https://www.paraview.org/download/) |

gdscheck installs with `cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck`,
into `~/.cargo/bin`. layz finds it there even when that folder isn't on `PATH` (cargo warns
about it when Rust comes from the distribution's packages rather than rustup); to run
`gdscheck` yourself, add `export PATH="$HOME/.cargo/bin:$PATH"` to `~/.bashrc` or `~/.zshrc`.

KLayout's Python module, KLayout-PEX, Shapely and the rest come from PyPI. From the repo root:

```sh
./install.sh                # once; again after a pull that changes dependencies
layz doctor                 # checks klayout, kicad-cli, FasterCap and gdscheck, and more
```

`install.sh` (bash; works from zsh too, on Linux and macOS) makes `.venv/` with the Python that
KiCad's `pcbnew` module is built for (Linux: `python3`, 3.14 on Ubuntu 26.04; macOS: KiCad's own),
checks it's Python 3.12 to 3.15, installs layz into it with `pip install --editable .` (changes in
this repo take effect directly), links `layz` into `~/.local/bin`, and adds that folder to `PATH`
in `~/.bashrc` or `~/.zshrc` if it isn't there yet. `./install.sh --test` also installs pytest,
`./install.sh --uninstall` removes the link. Keep the clone: the DRC decks (`drc/`) and stacks
(`stacks/`) are read from it.

By hand, the same is:

```sh
python3 -m venv --system-site-packages .venv      # system packages: pcbnew comes with KiCad
.venv/bin/pip install --editable .
ln -sf "$PWD/.venv/bin/layz" ~/.local/bin/layz
```

layz finds KiCad's `pcbnew` by itself, also from a venv without the system's packages; set
`LAYZ_KICAD_PYTHONPATH` to the folder holding `pcbnew.py` if it's somewhere unusual.
`layz doctor` exits with an error when a required tool is missing, and warns about optional
ones (HyperLynx via `LAYZ_HYPERLYNX`, FastCap2, ParaView).

On Debian, Ubuntu and Kali also `sudo apt install cmake g++ make git curl libopenblas-dev`
(the script checks these first and prints the command for Fedora, Arch and macOS too), then
`scripts/build_solvers.sh`: it builds FasterCap (iic-jku fork, headless), FastCap2 and a
wxWidgets base library into `~/.local/share/layz` and links the solvers into `~/.local/bin`.
layz finds them on `PATH`, or through `LAYZ_FASTERCAP` / `LAYZ_FASTCAP2`. On macOS see the notes
at the top of the script.

Tests run in the same venv:

```sh
./install.sh --test
.venv/bin/python -m pytest
```

## Stack files

A GDS carries only 2-D shapes; heights, thicknesses and permittivities come from a **stack
file**, one per process, in `stacks/`. It lists the layers top to bottom; z positions are derived
from the order. Every tool reads the same file:

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
gds = "8/0"
pads = true                   # GDS sub-cells with these shapes become footprint pads
zones = false                 # top-level shapes become copper zones (default true)

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

`layz pcb --stack` writes the stack into the board as its KiCad physical stackup, so the
`.kicad_pcb`, the `.hyp` and the FasterCap model all carry it. A board made in KiCad uses its
own stackup (Board Setup > Physical Stackup). The full format is documented in
[src/layz/stack.py](src/layz/stack.py).

| Stack file | Process | Source |
| --- | --- | --- |
| `uni_bonn_rdl.toml` | Uni Bonn RDL, Al on polyimide (obelix1: M2 + M3 on the chip pads) | asiclab `tech/uni-bonn-rdl` thicknesses, obelix1 KiCad mapping; polyimide εr and 8/0 to confirm |
| `multicb_4L-01.toml` | Multi-CB 4-layer FR4, 1.6 mm | Multi-CB defined buildup 4L-01 (mask assumed: 10 µm, εr 3.3) |
| `multicb_4L-02.toml` | Multi-CB 4-layer FR4, 1.0 mm | Multi-CB defined buildup 4L-02 (mask assumed) |
| `multicb_flex_2F-l.toml` | Multi-CB 2-layer flex, adhesiveless, 161 µm | Multi-CB standard 2F-l |
| `multicb_flex_2F-a.toml` | Multi-CB 2-layer flex, adhesive-bonded, 187 µm | Multi-CB standard 2F-a |

The Multi-CB files are their published standard buildups; for a board ordered with a custom
buildup, copy the closest one and enter the ordered thicknesses and materials.

## GDS -> KiCad -> HyperLynx

```sh
layz hyp example_files/obelix1_ivtx_ladder_v2.gds --stack stacks/uni_bonn_rdl.toml   # one step
```

or step by step, to edit the board in between:

```sh
layz pcb --lay design.gds --stack stacks/uni_bonn_rdl.toml          # -> design.kicad_pcb
# KiCad: Update PCB from Schematic (references and the seed footprint's pad nets)
layz nets design.kicad_pcb --seed-footprint VTX2       # -> design_nets_assigned.kicad_pcb
layz hyp design_nets_assigned.kicad_pcb               # -> design_nets_assigned.hyp
```

`layz pcb`: GDS cells with pad-layer shapes become footprints (one per cell and orientation),
top-level copper becomes filled zones, via layers become blind/buried vias, the outline layer
becomes Edge.Cuts; Y is flipped so the board shows the GDS top view. `nets`: nets propagate from
the seed footprint's pads through touching copper and vias. `hyp`: a re-implementation of KiCad's
HyperLynx exporter (KiCad has it only in the GUI), same records and number format: board
outline, stackup, devices, padstacks, and per net its pins, vias, tracks and zone fills.

## Design rule check

```sh
layz drc --lay design.gds --kit uni-bonn-rdl                  # -> design.lyrdb
layz view design.lyrdb --lay design.gds                     # KLayout with the violation markers
```

Decks are gdscheck PDKs in its own YAML format, one per kit in `drc/<kit>/`.
`drc/uni-bonn-rdl/` is the in-house RDL (maskless lithography), with the layers of asiclab's
`tech/uni-bonn-rdl`: chip pads 68/0, Al M1 1/0, M2 3/0, M3 6/0, polyimide openings V1 2/0,
V2 4/0, pad openings 7/0, outline 70/0.

| Rule | Value |
| --- | --- |
| M1, M2, M3 width, spacing, notch | ≥ 10 µm |
| M1, M2, M3 area (minimum feature 10 × 10 µm) | ≥ 100 µm² |
| V1, V2, pad opening size / spacing (spacing assumed = metal spacing) | ≥ 10 µm |
| V1 by M2, V2 by M2 and M3, pad openings by M3, every side | ≥ 10 µm (pads ≥ 30 × 30 µm) |
| V1 landing on M1 or a chip pad | contained |
| metal density in any 1 × 1 mm window (step 500 µm), inside the outline 70/0 | ≤ 95 % |

Chip pads (68/0) are the chip's and aren't checked. V2 is the 4/0 opening alone (asiclab's
tech has 4/0 AND 5/0; designs draw V2 on 4/0). `--suite geometry` leaves out density. `--benchmark` times each rule on its own (slowest first):
on the obelix1 ladder the M2 and M3 width checks are 98 % of the run. `--tile` is gdscheck's
merge tile; layz uses 20 mm, about 5x faster than 2 mm on the ladder's long planes. The
obelix1 ladder GDS takes about 35 s (18 threads) and reports 261 violations: V2 enclosure
by M2 (52) and M3 (138), density in 19 + 20 windows on M2/M3, 19 notches, 1 width, and 12 at V1
and pad openings.

## Capacitance and fields

```sh
layz pex board.kicad_pcb                              # stack from the board
layz pex chip.gds --stack stacks/uni_bonn_rdl.toml       # stack from the file
layz pex board.kicad_pcb --charges --out run          # also keep charges for fields
layz field run --voltage TOP=1                        # 3-D grid -> run/field.vtk
layz field run --voltage TOP=1 --plane y=5000         # cross-section, PNG + VTK
layz view section run/section_y5000_edge.vtk          # ParaView: heatmap + field lines
layz view geometry run                                # ParaView: the 3-D model
```

A conductor is any copper that touches or is joined by vias (no LVS, no netlist), named by net
(KiCad), by GDS texts or `--name NAME=LAYER@X,Y`. The 3-D model (extrusion, dielectric interfaces,
triangulation into FasterCap's `.lst`/`.geo`) comes from KLayout-PEX's `FasterCapModelBuilder`.
Results: `maxwell_matrix_fF.csv` (Maxwell sign convention: diagonal total, off-diagonal
−mutual) and `spice_caps_fF.csv`.

**Keep `--tolerance` at 1 % or tighter** (the default). With dielectrics FasterCap's first passes
can be far off: plates with εr = 4 gave 2336 fF at 5 % and 3591 fF at 1 %, without an error.
layz warns when FasterCap stops after a single pass.

`--voltage` sets conductor voltages when computing fields; any bias is a superposition of the
solved columns, so it needs no new solve. On Ubuntu ParaView needs `HWLOC_COMPONENTS=-gl`
(`layz view` sets it).

## Checks

`.venv/bin/python -m pytest` (about 3 s):

- GDS -> `.hyp` of the obelix1 RDL design gives the same STACKUP section as the `.hyp` KiCad's GUI
  exported (`example_files/obelix1_ivtx_ladder_with_nets_v3.1.hyp`).
- `tests/plates.gds`, two 1 mm² plates 10 µm apart in vacuum: 918.8 fF (ideal 885 fF + fringe).
- `tests/pcb_plates.kicad_pcb` (two 10 × 10 mm, 35 µm plates on 0.2 mm FR4, from
  `tests/make_pcb_plates.py`) builds the validated 3-D model. Solved at 1 %: 21.54 pF against
  ~21.7 pF from Palmer's edge-corrected formula, 5.16 kV/m in the FR4 at 1 V (ideal 5.0).
- Stack files: heights, validation, KiCad stackup round trip.

## Files

- `src/layz/` the package; `stacks/` process stacks; `example_files/` reference designs
  (GDS, KiCad schematic, a KiCad-exported `.hyp`); `tests/`; `scripts/build_solvers.sh`.
