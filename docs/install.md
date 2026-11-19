# Installing layz

layz is a standard Python package (`pyproject.toml`, Python 3.12 to 3.15), installed with
Python's own `venv` and `pip`. It also uses tools that are not on PyPI:

| Tool | Needed for | Install |
| --- | --- | --- |
| KiCad 10 (`kicad-cli`, its `pcbnew` Python module) | `gds2pcb`, `gds2hyp` from a GDS, `pex` on boards, `lvs` | `install/kicad.sh` |
| FasterCap (default) / FastCap2 | `pex`, `field` | `install/fastercap.sh` |
| gdscheck | `drc` | `install/gdscheck.sh` |
| ParaView (optional) | `view` of field results | `install/paraview.sh` |
| KLayout | viewing GDS, DRC and LVS results | [klayout.de/build.html](https://www.klayout.de/build.html) |
| HyperLynx (optional, licensed) | `hyp` (SI/PI runs) | Siemens |

## layz itself

From the repo root:

```sh
./install.sh                # once; again after a pull that changes dependencies
layz doctor                 # what layz found, then its tests (--quick: just the tools)
```

Keep the clone: layz runs from it. `./install.sh --uninstall` removes the `layz` command.

If something isn't found:

- Python: layz needs 3.12 to 3.15; where `python3` is older (3.9 on AlmaLinux 9), `install.sh`
  uses the newest one installed, or installs the newest the package manager has (asking for sudo).
  `LAYZ_PYTHON=/path/to/python3 ./install.sh` picks one yourself
- KiCad's `pcbnew`: set `LAYZ_KICAD_PYTHONPATH` to the folder holding `pcbnew.py`
- HyperLynx: set `LAYZ_HYPERLYNX_HOME` to its `SDD_HOME` folder

## The tools

```sh
install/kicad.sh       # KiCad 10
install/fastercap.sh   # FasterCap (and FastCap2)
install/gdscheck.sh    # gdscheck
install/paraview.sh    # ParaView
```

Each takes no arguments and works on Debian, Ubuntu, AlmaLinux and macOS: it installs what it
needs with the system's package manager (apt, dnf, asking for sudo; Homebrew on macOS), and the
command works in the same terminal afterwards. Run one again to update.

- KiCad 10 comes from KiCad's PPA on Ubuntu, from the distribution where it ships 10 (Debian
  testing, Fedora), and from Homebrew on macOS (then `./install.sh` again: layz runs on KiCad's
  Python there). AlmaLinux and Debian 13 have no KiCad 10 package: the script says so and stops.
- ParaView is the distribution's on Debian and Ubuntu; on AlmaLinux, ParaView's own Linux build
  in `~/.local/share/layz`.
- FastCap2 needs GoogleTest to build; on AlmaLinux that is only in EPEL, so there the script
  builds FasterCap alone (layz's default solver).
