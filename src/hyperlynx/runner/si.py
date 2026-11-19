"""Signal integrity (HyperLynx BoardSim): waveforms or an eye of one net, optionally with loss,
crosstalk from driven aggressors, and stimulus jitter. Needs an X display (EZwave): layz runs it
under xvfb-run.

Job options:
    net          the net to simulate (its pair, *_P/*_N, comes along)
    mode         "eye" (PRBS, eye diagram), "std" (a pattern) or "osc" (every driver toggles at
                 bitrate/2: a clock, used for crosstalk from aggressors)
    bitrate      bit/s (eye, std) or 2 x clock frequency (osc)
    prbs_order, repetitions, stop_s (std/osc), step_s
    lossy, roughness, trapezoid   realistic line models (default: all on)
    crosstalk    couple to neighbouring nets (needs lossy); aggressors are the nets with switching
                 drivers within reach
    aggressors   [{"driver": "V4.114", "receivers": ["VTX2.114"]}, ...]: give these pins the stock
                 IBIS CMOS driver/receiver (modvsez.ibs) and switch them
    victim_quiet hold the net's own drivers low (measure only what couples in)
    jitter       {"Gaussian": 1e-10, "Sine": 3e-10, "SineFreq": 5e6, ...} in seconds
    xt_threshold V, aggressors coupling less than this are left out (default 0.001)

Outputs: one CSV per waveform (full resolution), si.json (settings as HyperLynx read them back).

Order matters: select the net first; choosing the target, operation or stimulus resets the
crosstalk switches, so those go last, and Apply() resets Crosstalk itself, so it is set again.
"""

import os

from common import h, load_job, open_board, save_waves, say, write_json

job = load_job()
out = os.path.abspath(job["out"])
app = open_board(job)
d, sim = app.Design, app.Simulator
net = job["net"]
if d.FindNet(net) is None:
    raise SystemExit(f"no net {net!r}")
d.SelectNet(net)

for g in job.get("aggressors", []):
    for pin, io in [(g["driver"], h.hlIoDirOutput)] + [(r, h.hlIoDirInput) for r in g.get("receivers", [])]:
        p = d.FindPin(pin)
        if p is None:
            raise SystemExit(f"aggressor pin {pin!r} not found")
        if not p.AssignModel("modvsez.ibs", "MODvsEZIBIS", "3"):
            raise SystemExit(f"cannot give {pin} the stock IBIS model: {app.LastError}")
        p.Model.IoDir = io
        if io == h.hlIoDirOutput:
            p.Model.DrvState = h.hlDrvStateSwitching
    say(f"aggressor {g['driver']} -> {', '.join(g.get('receivers', []))}")

pair = [net] + ([net[:-1] + ("P" if net.endswith("N") else "N")] if net[-1:] in "NP" else [])
if job.get("victim_quiet"):
    for p in [q for n in pair if d.FindNet(n) is not None for q in d.FindNet(n).Pins]:
        if p.Model is not None and p.Model.IoDir == h.hlIoDirOutput:
            p.Model.DrvState = h.hlDrvStateLow
            say(f"victim driver {p.FullName} held low")

# target, operation, stimulus
sim.Target = h.hlSimResultTargetEZWave  # full-resolution waveforms (the oscilloscope gives 1024 points)
mode = job.get("mode", "eye")
st = sim.Stimulus
if mode == "eye":
    sim.Operation = h.hlSimOpEyeDiagram
    st.BitSequenceType = h.hlBitSequencePBRS
    st.BitOrder = int(job.get("prbs_order", 7))
    st.Repetitions = int(job.get("repetitions", 4))
elif mode == "osc":
    sim.Operation = h.hlSimOpStandard
    st.BitSequenceType = h.hlBitSequenceOscillator
else:
    sim.Operation = h.hlSimOpStandard
bitrate = float(job.get("bitrate", 160e6))
# a PRBS/pattern stimulus takes the bit rate; the oscillator its clock frequency, half of it
st.Frequency = bitrate / 2 if mode == "osc" else bitrate
for k in ("Gaussian", "Sine", "Uniform", "Distortion"):
    setattr(st.Jitter, k, 0.0)
for k, v in (job.get("jitter") or {}).items():
    setattr(st.Jitter, k, float(v))
if job.get("stop_s"):
    sim.StopAuto = False
    sim.StopTime = float(job["stop_s"])
else:
    sim.StopAuto = True
if job.get("step_s"):
    sim.StepAuto = False
    sim.Step = float(job["step_s"])

# line models and crosstalk, last
xt_on = bool(job.get("crosstalk"))
ss = d.SimSettings
ss.Lossy = bool(job.get("lossy", True)) or xt_on  # crosstalk is off unless the simulation is lossy
ss.SurfaceRoughness = bool(job.get("roughness", True))
ss.TrapezoidTraces = bool(job.get("trapezoid", True))
ss.Crosstalk = xt_on
xt = d.CrosstalkSettingsEx
xt.TraceCoupling.Enabled = xt_on
xt.AreaFillCoupling.Enabled = xt_on
if xt_on:
    xt.TraceCoupling.Threshold = float(job.get("xt_threshold", 0.001))
    xt.TraceCoupling.MaxDistToAggressor = float(job.get("xt_max_distance_m", 0.5e-3))
xt.Apply()
ss.Crosstalk = xt_on

jt = st.Jitter
settings = {
    "net": net, "mode": mode, "bitrate": bitrate, "stimulus_frequency": st.Frequency, "operation": sim.Operation,
    "lossy": ss.Lossy, "roughness": ss.SurfaceRoughness, "trapezoid": ss.TrapezoidTraces,
    "crosstalk": ss.Crosstalk, "trace_coupling": xt.TraceCoupling.Enabled, "areafill_coupling": xt.AreaFillCoupling.Enabled,
    "jitter": {k: getattr(jt, k) for k in ("Gaussian", "Sine", "SineFreq", "Uniform", "Distortion")},
    "aggressors": job.get("aggressors", []), "victim_quiet": bool(job.get("victim_quiet")),
}
if xt_on and not ss.Crosstalk:
    raise SystemExit("HyperLynx switched crosstalk off (it needs a lossy simulation and a selected net)")
say("settings: " + ", ".join(f"{k}={v}" for k, v in settings.items() if k not in ("aggressors",)))
ok = sim.Run()
if not ok:
    raise SystemExit(f"simulation failed: {app.LastError or 'see bsw.log in the run folder'}")
settings["waves"] = save_waves(sim.Result, out)
write_json(os.path.join(out, "si.json"), settings)
say(f"{len(settings['waves'])} waveforms")
