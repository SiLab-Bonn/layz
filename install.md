# Installing layz

layz is a standard Python package (`pyproject.toml`, Python 3.12 to 3.15), installed with
Python's own `venv` and `pip`. It also uses tools that are not on PyPI:

| Tool | Needed for | Linux | macOS |
| --- | --- | --- | --- |
| KiCad (its `pcbnew` Python module, `kicad-cli`) | `gds2pcb`, `gds2hyp`, `pex` on boards, `lvs` (schematic netlists) | [kicad.org/download/linux](https://www.kicad.org/download/linux/) | [kicad.org/download/macos](https://www.kicad.org/download/macos/) |
| KLayout | viewing GDS, DRC and LVS results | [klayout.de/build.html](https://www.klayout.de/build.html) | [klayout.de/build.html](https://www.klayout.de/build.html) |
| FasterCap (default) / FastCap2 | `pex`, `field` | `scripts/build_solvers.sh` | `scripts/build_solvers.sh` |
| gdscheck | `drc` | `scripts/install_gdscheck.sh` | `scripts/install_gdscheck.sh` |
| ParaView (optional) | `view` of field results | [paraview.org/download](https://www.paraview.org/download/) | [paraview.org/download](https://www.paraview.org/download/) |
| HyperLynx (optional, licensed) | `hyp` (SI/PI runs) | Siemens | — |

## layz itself

From the repo root:

```sh
./install.sh                # once; again after a pull that changes dependencies
layz doctor                 # what layz found, then its tests (--quick: just the tools)
```

Keep the clone: layz runs from it. `./install.sh --uninstall` removes the `layz` command.

If something isn't found:

- no suitable Python (layz needs 3.12 to 3.15): install one, or
  `LAYZ_PYTHON=/path/to/python3 ./install.sh`
- KiCad's `pcbnew`: set `LAYZ_KICAD_PYTHONPATH` to the folder holding `pcbnew.py`
- HyperLynx: set `LAYZ_HYPERLYNX_HOME` to its `SDD_HOME` folder

## Field solvers, gdscheck

```sh
scripts/build_solvers.sh     # FasterCap and FastCap2
scripts/install_gdscheck.sh  # gdscheck, for layz drc
```

Both install what they need first with the system's package manager (apt, dnf or pacman, asking
for sudo; Homebrew on macOS), and the commands work in the same terminal afterwards.
