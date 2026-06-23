# gds2kicad

Convert selected GDS geometry into a KiCad `.kicad_pcb` board file.

The converter uses KLayout to read and polygonize GDS shapes, then writes KiCad PCB objects using `kicad-pycbnew`. GDS polygons are emitted as KiCad zones with cached `filled_polygon` data, so downstream exports can use the generated filled geometry without asking KiCad to recalculate zone fills.

## Preview

Example output generated from `example.gds`:

![Generated KiCad PCB preview](preview.svg)

## Install

Python 3.12 was used during development. The runtime dependencies are normal Python packages installed from PyPI via `pip`:

- `klayout`
- `kicad-pycbnew`

Create a virtual environment and install the project dependencies from `pyproject.toml`:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

No separate KiCad GUI application package is required to run the converter itself. KiCad is only needed if you want to open the generated `.kicad_pcb` file graphically or validate/export it with `kicad-cli`.

## Usage

Convert the included example GDS file:

```sh
python gds2pcb.py example.gds example.kicad_pcb
```

If no arguments are provided, the script uses those same defaults:

```sh
python gds2pcb.py
```

Convert another GDS file:

```sh
python gds2pcb.py input.gds output.kicad_pcb
```

## Default layer mapping

The current defaults are tailored for the prototype process stack:

| GDS layer/datatype | KiCad output |
| --- | --- |
| `3/0` | filled zone on `In1.Cu` |
| `6/0` | filled zone on `F.Cu` |
| `7/0` | filled zone on `F.Mask` |
| `2/0` | blind via from `B.Cu` to `In1.Cu` |
| `4/0` | blind via from `In1.Cu` to `F.Cu` |

The default generated net name is empty.

## Override mappings

Map GDS polygon layers to KiCad layers:

```sh
python gds2pcb.py input.gds output.kicad_pcb \
  --layer-map 3/0=In1.Cu \
  --layer-map 6/0=F.Cu
```

Map GDS via layers to KiCad via layer pairs:

```sh
python gds2pcb.py input.gds output.kicad_pcb \
  --via-map 2/0=B.Cu,In1.Cu \
  --via-map 4/0=In1.Cu,F.Cu
```

Set a KiCad net name:

```sh
python gds2pcb.py input.gds output.kicad_pcb --net-name /GND
```

## Notes

- GDS boxes, polygons, and paths are all converted through KLayout's `shape.dpolygon` representation.
- KiCad native via objects are circular. For each GDS via polygon, the converter uses the bounding-box center and `min(width, height)` as the via diameter.
- The via drill defaults to `diameter - 10 µm`; adjust with `--drill-shrink-um`.
- Generated zones include both `polygon` and matching `filled_polygon` sections. Avoid manually refilling zones in KiCad if you need to preserve the exact GDS-derived fill geometry.
- `--flip-y` exists for coordinate-system experiments, but the default is no mirroring.

## Generate a preview SVG

The converter itself only writes the KiCad PCB file. The `preview.svg` image in this README was generated from the converted board using KiCad CLI:

```sh
python gds2pcb.py example.gds example.kicad_pcb

kicad-cli pcb export svg example.kicad_pcb \
  --output preview.svg \
  --layers F.Cu,In1.Cu,B.Cu,F.Mask \
  --page-size-mode 2 \
  --exclude-drawing-sheet
```

KiCad / `kicad-cli` is only needed for opening, validating, or exporting the generated `.kicad_pcb` file; it is not needed to run `gds2pcb.py`.
