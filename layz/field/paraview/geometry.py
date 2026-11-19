"""Render the solved 3-D model of a run in ParaView, without any field: the conductors as copper
solids and the dielectric layers as translucent slabs, as FasterCap saw them (panels.vtk, written
by fieldview.py). Saves a PNG and a ParaView state.

    layz view geometry RUN [--z-stretch 5] [--mesh] [-o out.png]
    paraview --state RUN/geometry.pvsm

--mesh draws the solver's triangle edges on the conductors.
(On Ubuntu, ParaView needs HWLOC_COMPONENTS=-gl in the environment; `layz view` sets it.)
"""

import argparse
import os
import re

from paraview.simple import Clip, CreateView, LoadPalette, OpenDataFile, Render, SaveScreenshot, SaveState, Show, Threshold, Transform

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--z-stretch", type=float, default=None, help="exaggerate z (default: auto)")
ap.add_argument("--mesh", action="store_true", help="show the solver mesh on the conductors")
ap.add_argument("-o", "--out")
args = ap.parse_args()

path = os.path.join(os.path.abspath(args.run), "panels.vtk")
header = open(path).readlines()[1]
owners = [(int(i), n) for i, n in re.findall(r"(\d+)=(\S+)", header)]
cond_ids = [i for i, n in owners if not n.startswith("diel")]
diel_ids = [i for i, n in owners if n.startswith("diel")]

panels = OpenDataFile(path)
panels.UpdatePipeline()
b = panels.GetDataInformation().GetBounds()
zs = args.z_stretch or max(1.0, min(20.0, 0.15 * max(b[1] - b[0], b[3] - b[2]) / (b[5] - b[4])))

LoadPalette("WhiteBackground")
view = CreateView("RenderView")
view.ViewSize = [1600, 900]
view.OrientationAxesVisibility = 1


def stretched(src):
    t = Transform(Input=src)
    t.Transform = "Transform"
    t.Transform.Scale = [1, 1, zs]
    return t


# dielectric interfaces: translucent green, a little stronger for higher εr
for i, name in owners:
    if i not in diel_ids:
        continue
    k = max(float(x) for x in name.split(":")[1:])
    one = Threshold(Input=panels, Scalars=["CELLS", "owner"], LowerThreshold=i - 0.5, UpperThreshold=i + 0.5)
    d = Show(stretched(one), view)
    d.ColorArrayName = ["POINTS", ""]
    d.DiffuseColor = [0.25, 0.55 + 0.04 * min(k, 6), 0.35]
    d.Opacity = 0.12 + 0.03 * min(k, 6)

# conductors: copper
cond = Clip(Input=panels, ClipType="Scalar", Scalars=["CELLS", "owner"], Value=max(cond_ids) + 0.5, Invert=1)
cd = Show(stretched(cond), view)
cd.ColorArrayName = ["POINTS", ""]
cd.DiffuseColor = [0.80, 0.50, 0.25]
cd.Specular = 0.4
if args.mesh:
    cd.SetRepresentationType("Surface With Edges")
    cd.EdgeColor = [0.25, 0.15, 0.08]

Render(view)
cx, cy, cz = 0.5 * (b[0] + b[1]), 0.5 * (b[2] + b[3]), 0.5 * (b[4] + b[5]) * zs
w = max(b[1] - b[0], b[3] - b[2])
view.CameraFocalPoint = [cx, cy, cz]
view.CameraPosition = [cx - 0.9 * w, cy - 1.3 * w, cz + 0.9 * w]
view.CameraViewUp = [0, 0, 1]
view.ResetCamera(False)
Render(view)
out = args.out or os.path.join(args.run, "geometry.png")
SaveScreenshot(out, view, ImageResolution=[1600, 900])
SaveState(os.path.join(args.run, "geometry.pvsm"))
print(f"wrote {out} and {os.path.join(args.run, 'geometry.pvsm')} (z stretched x{zs:g})")
