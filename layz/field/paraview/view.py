"""Render a fieldview.py result with ParaView: conductors, a vertical cut plane colored by E_z,
and field arrows. Saves a PNG; also a starting point for the ParaView GUI (View > Python Shell,
or File > Load State after saving one).

    layz view field RUN_DIR [--y Y_UM] [--z-stretch S] [-o out.png]

HWLOC_COMPONENTS=-gl works around Ubuntu's ParaView hanging at startup (hwloc probing X displays).
"""

import argparse
import os
import re

from paraview.simple import Calculator, Clip, ColorBy, CreateView, GetColorTransferFunction, GetScalarBar, Glyph, LoadPalette, OpenDataFile, Render, SaveScreenshot, Show, Slice, Transform

ap = argparse.ArgumentParser()
ap.add_argument("run")
ap.add_argument("--y", type=float, help="y of the xz cut plane, µm (default: middle)")
ap.add_argument("--z-stretch", type=float, default=None, help="exaggerate z (default: auto)")
ap.add_argument("--field", default="Ez", choices=["Ez", "Emag"])
ap.add_argument("-o", "--out")
args = ap.parse_args()

field = OpenDataFile(os.path.join(args.run, "field.vtk"))
panels = OpenDataFile(os.path.join(args.run, "panels.vtk"))
field.UpdatePipeline()
b = field.GetDataInformation().GetBounds()
zs = args.z_stretch or max(1.0, min(20.0, 0.25 * max(b[1] - b[0], b[3] - b[2]) / (b[5] - b[4])))

# owner ids of the conductors, from the panels.vtk header ("0=BOT 1=TOP 2=diel0 ...")
header = open(os.path.join(args.run, "panels.vtk")).readlines()[1]
cond_ids = [int(i) for i, n in re.findall(r"(\d+)=(\S+)", header) if not n.startswith("diel")]

LoadPalette("WhiteBackground")
view = CreateView("RenderView")
view.ViewSize = [1600, 900]
view.Background = [1, 1, 1]
view.OrientationAxesVisibility = 1
try:
    view.UseColorPaletteForBackground = 0
except AttributeError:
    pass

Y = args.y if args.y is not None else 0.5 * (b[2] + b[3])


def stretched(src):
    """Exaggerate z for display (flat boards); glyphs are made afterwards, so arrows aren't stretched."""
    t = Transform(Input=src)
    t.Transform = "Transform"
    t.Transform.Scale = [1, 1, zs]
    return t


# conductors: panels whose owner is a conductor; only the half behind the cut plane
cond = Clip(Input=panels, ClipType="Scalar", Scalars=["CELLS", "owner"], Value=max(cond_ids) + 0.5, Invert=1)
back = Clip(Input=cond, ClipType="Plane")
back.ClipType.Origin = [0, Y, 0]
back.ClipType.Normal = [0, -1, 0]
cd = Show(stretched(back), view)
cd.ColorArrayName = ["POINTS", ""]
cd.DiffuseColor = [0.80, 0.50, 0.20]
cd.Opacity = 0.6

# copper cross-section in the cut plane, drawn as thick outlines
xs = Slice(Input=cond)
xs.SliceType.Origin = [0, Y, 0]
xs.SliceType.Normal = [0, 1, 0]
xd = Show(stretched(xs), view)
xd.ColorArrayName = ["POINTS", ""]
xd.DiffuseColor = [0.55, 0.30, 0.05]
xd.LineWidth = 4.0

# xz cut plane through the field, colored by Ez (or |E|), with E arrows
cut = Slice(Input=field)
cut.SliceType.Origin = [0.5 * (b[0] + b[1]), Y, 0.5 * (b[4] + b[5])]
cut.SliceType.Normal = [0, 1, 0]
cut_s = stretched(cut)
sd = Show(cut_s, view)
ColorBy(sd, ("POINTS", args.field))
lut = GetColorTransferFunction(args.field)
lut.ApplyPreset("Cool to Warm" if args.field == "Ez" else "Turbo", True)
if args.field == "Ez":  # symmetric, so 0 V/m is white
    lo, hi = cut.PointData["Ez"].GetRange()
    m = max(abs(lo), abs(hi))
    lut.RescaleTransferFunction(-m, m)
sd.SetScalarBarVisibility(view, True)
bar = GetScalarBar(lut, view)
bar.Title = f"{args.field} (V/m)"
bar.ComponentTitle = ""

# arrows in the stretched space: tilt E like the geometry, keep arrow shapes undistorted
evec = Calculator(Input=cut_s, ResultArrayName="E_plot", Function=f"E_X*iHat+E_Y*jHat+E_Z*{zs}*kHat")
emax = max(abs(v) for v in cut.PointData["Emag"].GetRange())
gl = Glyph(Input=evec, GlyphType="Arrow", OrientationArray=["POINTS", "E_plot"], ScaleArray=["POINTS", "Emag"])
gl.ScaleFactor = 0.035 * (b[1] - b[0]) / emax  # the strongest field gets an arrow of 3.5 % width
gl.GlyphMode = "Every Nth Point"
gl.Stride = 5
gd = Show(gl, view)
gd.ColorArrayName = ["POINTS", ""]
gd.DiffuseColor = [0.1, 0.1, 0.1]

# look at the cut plane from the front (-y), z up, slightly from above and the side
cx, cz = 0.5 * (b[0] + b[1]), 0.5 * (b[4] + b[5]) * zs
w = b[1] - b[0]
view.CameraFocalPoint = [cx, Y, cz]
view.CameraPosition = [cx - 0.2 * w, Y - 1.0 * w, cz + 0.18 * w]
view.CameraViewUp = [0, 0, 1]
view.CameraParallelProjection = 0
Render(view)
out = args.out or os.path.join(args.run, f"field_{args.field}.png")
SaveScreenshot(out, view, ImageResolution=[1600, 900])
print(f"wrote {out} (z stretched x{zs:g}, cut at y={Y:g} µm)")
