"""S-parameters between pins (HyperLynx's S-parameter extractor), as a Touchstone file.

Every setting comes from the job (layz.hyperlynx.run.sparam documents them).
Output: sparams.s<N>p (HyperLynx writes its port map as comments at the top), sparam.json.
"""

import os

from common import enum, load_job, open_board, say, write_json

job = load_job()
out = os.path.abspath(job["out"])
app = open_board(job)
d, ex = app.Design, app.SParamExtractor
pins = job["pins"]
missing = [p for p in pins if d.FindPin(p) is None]
if missing:
    raise SystemExit(f"no such pin(s): {', '.join(missing)}")

ss = d.SimSettings
ss.Lossy = bool(job["lossy"])
ss.SurfaceRoughness = bool(job["roughness"])
ss.TrapezoidTraces = bool(job["trapezoid"])
ss.NonfunctionPads = bool(job["nonfunctional_pads"])
for p in pins:
    ex.Ports.Add(p)
ex.MinFreq = float(job["fmin"])
ex.MaxFreq = float(job["fmax"])
ex.FreqSweepType = enum("sweep", job["sweep"])
ex.StepCount = int(job["steps"])
ex.StepPerDecade = int(job["steps_per_decade"])
ex.Tolerance = enum("tolerance", job["tolerance"])
ex.RefImpedance = float(job["reference_impedance"])

path = os.path.join(out, f"sparams.s{len(pins)}p")
say(f"extracting {len(pins)} ports {ex.MinFreq:.3g}..{ex.MaxFreq:.3g} Hz, {job['sweep']} sweep, {ex.RefImpedance:g} ohm, lossy={ss.Lossy}")
if not ex.Extract(path):
    raise SystemExit(f"extraction failed: {app.LastError}")
write_json(os.path.join(out, "sparam.json"), {"pins": pins, "fmin": ex.MinFreq, "fmax": ex.MaxFreq, "sweep": job["sweep"], "steps": ex.StepCount, "steps_per_decade": ex.StepPerDecade, "tolerance": job["tolerance"], "reference_impedance": ex.RefImpedance, "lossy": ss.Lossy, "roughness": ss.SurfaceRoughness, "trapezoid": ss.TrapezoidTraces, "nonfunctional_pads": ss.NonfunctionPads, "file": os.path.basename(path)})
say(f"wrote {path}")
