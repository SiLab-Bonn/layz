# Installing layz

layz is a standard Python package (`pyproject.toml`, Python 3.12 to 3.15), installed with
Python's own `venv` and `pip`. It also uses tools that are not on PyPI:

| Tool | Needed for | Install |
| --- | --- | --- |
| KiCad 10 (`kicad-cli`, its `pcbnew` Python module) | `gds2hyp` from a board or GDS, `pex` on boards, `lvs` | `install/kicad.sh` |
| FasterCap (default) / FastCap2 | `pex`, `field` | `install/fastercap.sh` |
| gdscheck | `drc` | `install/gdscheck.sh` |
| ParaView (optional) | looking at field results in 3-D (layz/field/paraview, with pvpython) | `install/paraview.sh` |
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
- KiCad 10: layz's own, apart from any KiCad you have: KiCad's AppImage unpacked into
  `~/.local/share/layz` on Linux (KiCad.app on macOS), with a small environment on KiCad's own
  Python where layz runs the steps that need `pcbnew`. Nothing of it goes on your PATH.
- KLayout 0.30.13 from klayout.org (Ubuntu `.deb`, RHEL/AlmaLinux `.rpm`, macOS `.dmg`); the
  distribution's on Debian, Fedora and Arch, for which klayout.org builds none.
- ParaView: the distribution's on Debian and Ubuntu, Homebrew on macOS; on AlmaLinux, ParaView's
  own Linux build in `~/.local/share/layz` (EPEL has only 5.11).
- FastCap2 needs GoogleTest; on AlmaLinux that is only in EPEL, so there only FasterCap (layz's
  default solver) is built.
- HyperLynx: found under `/eda/Siemens`, or set `LAYZ_HYPERLYNX_HOME` to its `SDD_HOME` folder; its
  license server is SiLab's unless `MGLS_LICENSE_FILE` says otherwise.
- Your shell's startup file (`~/.bashrc`, `~/.zshrc`) gets one marked `layz` block at its end, putting
  `~/.local/bin` on PATH; `install.sh` rewrites it on every run.
