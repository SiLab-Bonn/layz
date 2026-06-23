# gds2kicad

Convert selected GDS geometry into a KiCad `.kicad_pcb` board file.

The converter uses KLayout to read and polygonize GDS shapes, then writes KiCad PCB objects using `kicad-pycbnew`. GDS polygons are emitted as KiCad zones with cached `filled_polygon` data, so downstream exports can use the generated filled geometry without asking KiCad to recalculate zone fills.

## Preview

Example output from the test GDS conversion:

![Generated KiCad PCB preview](docs/preview.svg)

## Install

Python 3.12 was used during development. Create a virtual environment and install dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Dependencies:

- `klayout`
- `kicad-pycbnew`

KiCad is not required to run the converter, but it is required to open the generated `.kicad_pcb` file or to validate/export it with `kicad-cli`.

## Usage

```sh
python gds2pcb.py input.gds output.kicad_pcb
```

If no arguments are provided, the script defaults to:

```sh
python gds2pcb.py conversion_test.gds conversion_test_pycbnew.kicad_pcb
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

## Validate with KiCad CLI

If KiCad is installed, you can verify that KiCad can load/render the generated board:

```sh
kicad-cli pcb export svg output.kicad_pcb \
  --output output.svg \
  --layers F.Cu,In1.Cu,B.Cu,F.Mask \
  --page-size-mode 2 \
  --exclude-drawing-sheet
```
