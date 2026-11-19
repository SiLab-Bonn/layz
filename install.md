# Installing layz

layz is a standard Python package (`pyproject.toml`, Python 3.12 to 3.15), installed with
Python's own `venv` and `pip`. It also uses tools that are not on PyPI:

| Tool | Needed for | Linux | macOS |
| --- | --- | --- | --- |
| KiCad (its `pcbnew` Python module, `kicad-cli`) | `gds2pcb`, `gds2hyp`, `pex` on boards, `lvs` (schematic netlists) | [kicad.org/download/linux](https://www.kicad.org/download/linux/) | [kicad.org/download/macos](https://www.kicad.org/download/macos/) |
| KLayout | viewing GDS, DRC and LVS results | [klayout.de/build.html](https://www.klayout.de/build.html) | [klayout.de/build.html](https://www.klayout.de/build.html) |
| FasterCap (default) / FastCap2 | `pex`, `field` | `scripts/build_solvers.sh` (sources: [FasterCap](https://github.com/iic-jku/FasterCap), [FastCap2](https://github.com/martinjankoehler/FastCap2)) | [FasterCap releases](https://github.com/iic-jku/FasterCap/releases) (or `scripts/build_solvers.sh`) |
| gdscheck | `drc` | [github.com/aesc-silicon/gdscheck](https://github.com/aesc-silicon/gdscheck), with Rust's `cargo` ([rust-lang.org/tools/install](https://www.rust-lang.org/tools/install)) | same |
| ParaView (optional) | `view` of field results | [paraview.org/download](https://www.paraview.org/download/) | [paraview.org/download](https://www.paraview.org/download/) |
| HyperLynx (optional, licensed) | opening the `.hyp` files for SI/PI | Siemens | — |

## layz itself

KLayout's Python module, KLayout-PEX, Shapely and the rest come from PyPI. From the repo root:

```sh
./install.sh                # once; again after a pull that changes dependencies
layz doctor                 # checks klayout, kicad-cli, FasterCap, gdscheck and more
```

`install.sh` (bash; works from zsh too, on Linux and macOS) makes `.venv/` with the Python that
KiCad's `pcbnew` module is built for (Linux: `python3`, 3.14 on Ubuntu 26.04; macOS: KiCad's
own), checks it's Python 3.12 to 3.15 (where `python3` is older, as 3.9 on AlmaLinux 9, it
takes the newest `python3.14`, `python3.13` or `python3.12` on `PATH` or in `~/.local/bin`), installs layz into it with `pip install --editable .`
(changes in this repo take effect directly), links `layz` into `~/.local/bin`, and adds that
folder to `PATH` in `~/.bashrc` or `~/.zshrc` if it isn't there yet. `./install.sh --test` also
installs pytest, `./install.sh --uninstall` removes the link. Keep the clone: the DRC decks
(`drc/`) and stacks (`stacks/`) are read from it.

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

## Field solvers

On Debian, Ubuntu and Kali first `sudo apt install cmake g++ make git curl libopenblas-dev`
(the script checks these and prints the command for Fedora, Arch and macOS too), then:

```sh
scripts/build_solvers.sh
```

It builds FasterCap (iic-jku fork, headless), FastCap2 and a wxWidgets base library into
`~/.local/share/layz` and links the solvers into `~/.local/bin`. layz finds them on `PATH`, or
through `LAYZ_FASTERCAP` / `LAYZ_FASTCAP2`. On macOS see the notes at the top of the script.

## gdscheck

```sh
cargo install --git https://github.com/aesc-silicon/gdscheck gdscheck
```

It installs into `~/.cargo/bin`. layz finds it there even when that folder isn't on `PATH` (cargo
warns about it when Rust comes from the distribution's packages rather than rustup); to run
`gdscheck` yourself, add `export PATH="$HOME/.cargo/bin:$PATH"` to `~/.bashrc` or `~/.zshrc`.

## Tests

```sh
./install.sh --test
.venv/bin/python -m pytest          # about 30 s; solver tests skip without FasterCap/KiCad
```

What they check:

- GDS -> `.hyp` of the obelix1 RDL design gives the same STACKUP section as the `.hyp` KiCad's
  GUI exported (`example_files/obelix1_ivtx_ladder_with_nets_v3.1.hyp`).
- Pours -> traces: an L-shaped route with a pad, a plane left alone, a signal converted and a
  supply kept, and the 17 signal nets of the obelix1 export.
- LVS: a test layout with a clean net, an open, a short and an unknown label.
- `tests/plates.gds`, two 1 mm² plates 10 µm apart in vacuum: 918.8 fF (ideal 885 fF + fringe).
- `tests/pcb_plates.kicad_pcb` (two 10 × 10 mm, 35 µm plates on 0.2 mm FR4, from
  `tests/make_pcb_plates.py`) builds the validated 3-D model. Solved at 1 %: 21.54 pF against
  ~21.7 pF from Palmer's edge-corrected formula, 5.16 kV/m in the FR4 at 1 V (ideal 5.0).
- Stack files: heights, validation, KiCad stackup round trip.
