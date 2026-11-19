"""Open a fieldview.py cross-section in ParaView: |E| (or Ez, phi) heatmap, field lines and the
copper outline. Saves a PNG and a ParaView state, so the same view opens interactively:

    layz view section RUN/section_y5000_edge.vtk [--color Emag|Ez|phi]
    paraview --state RUN/section_y5000_edge.pvsm

The field lines follow the in-plane field (E_plane), traced both ways from the seeds that
fieldview.py writes next to the section (section_*_seeds.vtk): points just outside every
conductor's outline, denser where the field is stronger, so this works for any geometry. In the
GUI, add ParaView's own Stream Tracer (line or point-cloud seeds) for more lines, recolour the
section, add a Contour on phi for equipotentials, etc.
(On Ubuntu, ParaView needs HWLOC_COMPONENTS=-gl in the environment; `layz view` sets it.)
"""

import argparse
import os
import re

import numpy as np
from paraview import servermanager as sm
from paraview.simple import (Clip, ColorBy, CreateView, GetColorTransferFunction, GetScalarBar,
                             LoadPalette, OpenDataFile, Render, SaveScreenshot, SaveState, Show,
                             Slice, StreamTracerWithCustomSource)
from vtkmodules.numpy_interface import dataset_adapter as dsa

ap = argparse.ArgumentParser()
ap.add_argument("section", help="section_*.vtk written by fieldview.py --plane")
ap.add_argument("--color", default="Emag", choices=["Emag", "Ez", "phi"])
ap.add_argument("-o", "--out", help="PNG (default: next to the section)")
args = ap.parse_args()

run = os.path.dirname(os.path.abspath(args.section))
stem = os.path.splitext(args.section)[0]
sec = OpenDataFile(os.path.abspath(args.section))
sec.UpdatePipeline()
b = sec.GetDataInformation().GetBounds()
ycut = (b[3] - b[2]) < 1e-6           # y = const section (u = x), else x = const (u = y)
u0, u1 = (b[0], b[1]) if ycut else (b[2], b[3])
z0, z1 = b[4], b[5]
plane = b[2] if ycut else b[0]

LoadPalette("WhiteBackground")
view = CreateView("RenderView")
view.ViewSize = [1600, 900]
view.OrientationAxesVisibility = 0

# heatmap; |E| scaled to the 99.5th percentile (the field at copper corners is singular)
sd = Show(sec, view)
ColorBy(sd, ("POINTS", args.color))
lut = GetColorTransferFunction(args.color)
lut.ApplyPreset("Cool to Warm" if args.color == "Ez" else "Turbo", True)
vals = dsa.WrapDataObject(sm.Fetch(sec)).PointData[args.color]
vals = np.asarray(vals)[np.isfinite(vals)]
if args.color == "Emag":
    lut.RescaleTransferFunction(0.0, float(np.percentile(vals, 99.5)))
elif args.color == "Ez":
    m = float(np.percentile(np.abs(vals), 99.5))
    lut.RescaleTransferFunction(-m, m)
else:  # phi: the few points touching copper corners would stretch the range past the voltages
    lut.RescaleTransferFunction(float(np.percentile(vals, 0.5)), float(np.percentile(vals, 99.5)))
lut.AutomaticRescaleRangeMode = "Never"
lut.NanColor = [1.0, 1.0, 1.0]  # inside the copper: no field, drawn white
sd.SetScalarBarVisibility(view, True)
bar = GetScalarBar(lut, view)
bar.Title = {"Emag": "|E| (V/m)", "Ez": "Ez (V/m)", "phi": "potential (V)"}[args.color]
bar.ComponentTitle = ""
bar.WindowLocation = "Any Location"
bar.Orientation = "Vertical"
bar.Position = [0.93, 0.12]
bar.ScalarBarLength = 0.7

# copper outline: the conductors' panels (panels.vtk) cut by the section plane
panels_path = os.path.join(run, "panels.vtk")
if os.path.exists(panels_path):
    header = open(panels_path).readlines()[1]
    cond_ids = [int(i) for i, n in re.findall(r"(\d+)=(\S+)", header) if not n.startswith("diel")]
    panels = OpenDataFile(panels_path)
    cond = Clip(Input=panels, ClipType="Scalar", Scalars=["CELLS", "owner"],
                Value=max(cond_ids) + 0.5, Invert=1)
    cut = Slice(Input=cond)
    cut.SliceType.Origin = [0, plane + 1e-3, 0] if ycut else [plane + 1e-3, 0, 0]
    cut.SliceType.Normal = [0, 1, 0] if ycut else [1, 0, 0]
    # only the part inside the section's window (the copper may extend far beyond it)
    inwin = Clip(Input=cut, ClipType="Box", Invert=1)
    inwin.ClipType.Position = [b[0] - 1, b[2] - 1, b[4]]
    inwin.ClipType.Length = [b[1] - b[0] + 2, b[3] - b[2] + 2, b[5] - b[4]]
    od = Show(inwin, view)
    od.ColorArrayName = ["POINTS", ""]
    od.DiffuseColor = [0.0, 0.0, 0.0]
    od.AmbientColor = [0.0, 0.0, 0.0]
    od.LineWidth = 2.5

# field lines from the seeds fieldview.py wrote next to the section
seeds_path = f"{stem}_seeds.vtk"
if os.path.exists(seeds_path):
    seeds = OpenDataFile(os.path.abspath(seeds_path))
    st = StreamTracerWithCustomSource(Input=sec, SeedSource=seeds)
    st.Vectors = ["POINTS", "E_plane"]
    st.IntegrationDirection = "BOTH"
    st.MaximumStreamlineLength = 4.0 * max(u1 - u0, z1 - z0)
    ld = Show(st, view)
    ld.ColorArrayName = ["POINTS", ""]
    ld.DiffuseColor = [1.0, 1.0, 1.0]
    ld.AmbientColor = [1.0, 1.0, 1.0]
    ld.LineWidth = 1.2
    ld.Opacity = 0.8
else:
    print(f"no {seeds_path}: no field lines (rerun fieldview.py --plane)")

# camera: straight at the section, parallel projection, true aspect (after a first render,
# which would otherwise reset it to fit everything, including the copper beyond the section)
Render(view)
cu, cz = 0.5 * (u0 + u1), 0.5 * (z0 + z1)
view.CameraParallelProjection = 1
view.CameraFocalPoint = [cu, plane, cz] if ycut else [plane, cu, cz]
view.CameraPosition = [cu, plane - 1e5, cz] if ycut else [plane + 1e5, cu, cz]
view.CameraViewUp = [0, 0, 1]
# frame the section itself (the copper outline may extend far beyond it)
aspect = view.ViewSize[0] / view.ViewSize[1]
view.CameraParallelScale = 0.53 * max(z1 - z0, (u1 - u0) / (0.88 * aspect))
view.CameraFocalPoint = [cu + 0.05 * (u1 - u0), plane, cz] if ycut else [plane, cu + 0.05 * (u1 - u0), cz]
view.CameraPosition = ([cu + 0.05 * (u1 - u0), plane - 1e5, cz] if ycut
                       else [plane + 1e5, cu + 0.05 * (u1 - u0), cz])
Render(view)

png = args.out or f"{stem}_{args.color}.png"
SaveScreenshot(png, view, ImageResolution=[1600, 900])
SaveState(f"{stem}.pvsm")
print(f"wrote {png} and {stem}.pvsm  (open with: paraview --state {stem}.pvsm)")
