"""S-parameters between pins (HyperLynx's S-parameter extractor), as a Touchstone file.

Job options: pins (the ports, in order: "V1.101", ...), fmin, fmax (Hz), lossy (default true).
Output: sparams.s<N>p (HyperLynx writes its port map as comments at the top).
"""

import os

from common import load_job, open_board, say, write_json

job = load_job()
out = os.path.abspath(job["out"])
app = open_board(job)
d, ex = app.Design, app.SParamExtractor
pins = job["pins"]
missing = [p for p in pins if d.FindPin(p) is None]
if missing:
    raise SystemExit(f"no such pin(s): {', '.join(missing)}")
lossy = bool(job.get("lossy", True))
ss = d.SimSettings
ss.Lossy = ss.SurfaceRoughness = ss.TrapezoidTraces = lossy
for p in pins:
    ex.Ports.Add(p)
ex.MinFreq, ex.MaxFreq = float(job.get("fmin", 1e6)), float(job.get("fmax", 5e9))
path = os.path.join(out, f"sparams.s{len(pins)}p")
say(f"extracting {len(pins)} ports {ex.MinFreq:.3g}..{ex.MaxFreq:.3g} Hz, lossy={lossy}")
if not ex.Extract(path):
    raise SystemExit(f"extraction failed: {app.LastError}")
write_json(os.path.join(out, "sparam.json"), {"pins": pins, "fmin": ex.MinFreq, "fmax": ex.MaxFreq,
                                               "lossy": lossy, "file": os.path.basename(path)})
say(f"wrote {path}")
