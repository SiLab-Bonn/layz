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

## Installing

Once per machine, an admin installs the system packages for every user (on macOS, yourself,
without sudo):

```sh
sudo install/system.sh
```

Then each user, without sudo, from the repo root:

```sh
./install.sh                # once; again after a pull
```

`install.sh` first checks every system package any part of layz needs; if some are missing it
lists them all and stops before installing anything. Then it installs, into your home and this
repo: layz itself (`install/layz.sh`), FasterCap (`install/fastercap.sh`), gdscheck
(`install/gdscheck.sh`), ParaView where it isn't a system package (`install/paraview.sh`), checks
KiCad 10 (`install/kicad.sh`), and ends with `layz doctor` and layz's tests. Each step also runs
on its own, without arguments. The commands work in the same terminal afterwards.

Keep the clone: layz runs from it, from its own environment `.layz-env/` (nobody activates it).
`./install.sh --uninstall` removes the `layz` command.

What comes from where (Debian, Ubuntu, AlmaLinux, macOS):

- Python 3.12 to 3.15: where `python3` is older (3.9 on AlmaLinux 9), the newest one the system
  has; `LAYZ_PYTHON=/path/to/python3 ./install.sh` picks one yourself.
- KiCad 10: KiCad's PPA on Ubuntu, the distribution's where it ships 10 (Debian testing, Fedora),
  Homebrew on macOS (layz then runs on KiCad's Python). AlmaLinux and Debian 13 have no KiCad 10
  package: `install.sh` says so, and layz's KiCad steps need another machine.
- ParaView: the distribution's on Debian and Ubuntu, Homebrew on macOS; on AlmaLinux, ParaView's
  own Linux build in `~/.local/share/layz` (EPEL has only 5.11).
- FastCap2 needs GoogleTest; on AlmaLinux that is only in EPEL, so there only FasterCap (layz's
  default solver) is built.
- KiCad's `pcbnew` elsewhere: set `LAYZ_KICAD_PYTHONPATH` to the folder holding `pcbnew.py`.
- HyperLynx: found under `/eda/Siemens`, or set `LAYZ_HYPERLYNX_HOME` to its `SDD_HOME` folder.
