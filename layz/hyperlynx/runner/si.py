"""Signal integrity (HyperLynx BoardSim): waveforms or an eye of one net, at full resolution.
Needs an X display (EZwave): layz runs it under xvfb-run.

Every setting comes from the job (layz.hyperlynx.run.si documents them); nothing is left to what
the board's project file last saved. The one fixed choice: results go to EZwave, the only target
whose waveforms HyperLynx saves at full resolution (the oscilloscope gives 1024 points).

Outputs: one CSV per waveform, si.json (the settings as HyperLynx reads them back).

Order matters: select the net first; choosing the target, operation or stimulus resets the
crosstalk switches, so those go last, and Apply() resets Crosstalk itself, so it is set again.
"""

import os

from common import ENUMS, enum, h, load_job, open_board, save_waves, say, write_json

job = load_job()
out = os.path.abspath(job["out"])
app = open_board(job)
d, sim = app.Design, app.Simulator

# the net
if d.FindNet(job["net"]) is None:
    raise SystemExit(f"no net {job['net']!r}")
d.SelectNet(job["net"])

# models: aggressors get the given IBIS model and switch; other pins' driver states as given
for g in job["aggressors"]:
    for pin, io in [(g["driver"], h.hlIoDirOutput)] + [(r, h.hlIoDirInput) for r in g["receivers"]]:
        p = d.FindPin(pin)
        if p is None:
            raise SystemExit(f"aggressor pin {pin!r} not found")
        if not p.AssignModel(g["lib"], g["device"], g["model"]):
            raise SystemExit(f"cannot give {pin} the model {g['lib']} {g['device']} {g['model']}: {app.LastError}")
        p.Model.IoDir = io
        if io == h.hlIoDirOutput:
            p.Model.DrvState = h.hlDrvStateSwitching
    say(f"aggressor {g['driver']} -> {', '.join(g['receivers'])}")
for ref, value in job.get("component_values", {}).items():  # passives the project has no value for
    c = d.FindComponent(ref)
    if c is None:
        raise SystemExit(f"component {ref!r} not found")
    c.Value = value
    say(f"{ref} = {value:g}")
for pin, m in job.get("models", {}).items():  # the net's own pins, where the project has no model
    p = d.FindPin(pin)
    if p is None:
        raise SystemExit(f"pin {pin!r} not found")
    ref = None
    if "like" in m:  # another pin's model, with its SPICE ports wired the same way to this pin
        ref = d.FindPin(m["like"])
        if ref is None or ref.Model is None:
            raise SystemExit(f"pin {m['like']!r} not found, or without a model")
        ref = ref.Model
        lib, device, model = ref.LibFile, ref.Device, ref.PinModel
    else:
        lib, device, model = m["lib"], m["device"], m["model"]
    if not p.AssignModel(lib, device, model):
        raise SystemExit(f"cannot give {pin} the model {lib} {device} {model}: {app.LastError}")
    if ref is not None and ref.SpicePorts is not None and p.Model.SpicePorts is not None:
        mine, theirs = p.Model.SpicePorts, ref.SpicePorts
        conn = {theirs.Item(j).Name: theirs.Item(j).CktConn for j in range(1, theirs.Count + 1)}
        for i in range(1, mine.Count + 1):
            port = mine.Item(i)
            if port.Name in conn:
                port.CktConn = conn[port.Name].replace(m["like"], pin)  # its pin for the other's
    p.Model.IoDir = h.hlIoDirOutput if m["io"] == "output" else h.hlIoDirInput
    if m["io"] == "output":
        p.Model.DrvState = h.hlDrvStateSwitching
    say(f"{pin}: {device} ({m['io']})" + (f", as {m['like']}" if "like" in m else ""))
for pin, state in job["driver_states"].items():
    p = d.FindPin(pin)
    if p is None or p.Model is None:
        raise SystemExit(f"pin {pin!r} not found, or without a model")
    p.Model.DrvState = enum("driver_state", state)
    say(f"{pin} driver {state}")

# simulator, target, operation
sim.Type = enum("simulator", job["simulator"])
sim.Corner = enum("corner", job["corner"])
sim.ProbePosition = enum("probe", job["probe"])
sim.Target = h.hlSimResultTargetEZWave
sim.Operation = enum("operation", job["operation"])
sim.StimScope = enum("stimulus_scope", job["stimulus_scope"])

# stimulus
st = sim.Stimulus
st.BitSequenceType = enum("bit_sequence", job["bit_sequence"])
st.BitOrder = int(job["prbs_order"])
st.Repetitions = int(job["repetitions"])
st.Frequency = float(job["frequency"])
st.DutyCycle = float(job["duty_cycle"])
st.InitialState = enum("initial_state", job["initial_state"])
jitter_keys = ("Gaussian", "GaussianFreq", "Sine", "SineFreq", "SineInitPhase", "Uniform", "UniformMean", "Distortion")
if set(job["jitter"]) != set(jitter_keys):
    raise SystemExit(f"jitter needs exactly {', '.join(jitter_keys)}")
for k in jitter_keys:
    setattr(st.Jitter, k, float(job["jitter"][k]))

# time
sim.StopAuto = job["stop_s"] is None
if job["stop_s"] is not None:
    sim.StopTime = float(job["stop_s"])
sim.StepAuto = job["step_s"] is None
if job["step_s"] is not None:
    sim.Step = float(job["step_s"])

# line models and crosstalk, last
ss = d.SimSettings
if job["crosstalk"] and not job["lossy"]:
    raise SystemExit("crosstalk needs lossy=True (HyperLynx switches crosstalk off in lossless runs)")
ss.Lossy = bool(job["lossy"])
ss.SurfaceRoughness = bool(job["roughness"])
ss.TrapezoidTraces = bool(job["trapezoid"])
ss.NonfunctionPads = bool(job["nonfunctional_pads"])
ss.Crosstalk = bool(job["crosstalk"])
xt = d.CrosstalkSettingsEx
tc, af, sp = job["trace_coupling"], job["area_fill_coupling"], job["sparameter_coupling"]
xt.TraceCoupling.Enabled = bool(tc["enabled"])
xt.TraceCoupling.Method = enum("method", tc["method"])
xt.TraceCoupling.Threshold = float(tc["threshold"])
xt.TraceCoupling.MaxDistToAggressor = float(tc["max_distance"])
xt.TraceCoupling.MinCoupleSegLen = float(tc["min_segment"])
xt.TraceCoupling.HorzNeighborLim = int(tc["horizontal_neighbours"])
xt.TraceCoupling.VertNeighborLim = int(tc["vertical_neighbours"])
xt.TraceCoupling.NonParallel = bool(tc["nonparallel"])
xt.TraceCoupling.Self = bool(tc["self"])
xt.AreaFillCoupling.Enabled = bool(af["enabled"])
xt.AreaFillCoupling.Grid = float(af["grid"])
xt.AreaFillCoupling.SearchDist = float(af["search_distance"])
xt.SParameterCoupling.ConnectorEnabled = bool(sp["connector"])
xt.SParameterCoupling.ConnectorThreshold = float(sp["connector_threshold"])
xt.SParameterCoupling.PackageEnabled = bool(sp["package"])
xt.SParameterCoupling.PackageThreshold = float(sp["package_threshold"])
xt.SParameterCoupling.EMEnabled = bool(sp["em"])
xt.SParameterCoupling.EMThreshold = float(sp["em_threshold"])
xt.SParameterCoupling.MinFreq = float(sp["fmin"])
xt.SParameterCoupling.MaxFreq = float(sp["fmax"])
xt.Apply()
ss.Crosstalk = bool(job["crosstalk"])
if bool(job["crosstalk"]) != bool(ss.Crosstalk):
    raise SystemExit("HyperLynx switched crosstalk off (it needs a lossy simulation and a selected net)")

# the settings as HyperLynx reads them back
names = {kind: {v: k for k, v in table.items()} for kind, table in ENUMS.items()}
jt = st.Jitter
settings = {
    "net": job["net"],
    "operation": names["operation"].get(sim.Operation),
    "mode": "eye" if sim.Operation == h.hlSimOpEyeDiagram else "standard",
    "simulator": names["simulator"].get(sim.Type),
    "corner": names["corner"].get(sim.Corner),
    "probe": names["probe"].get(sim.ProbePosition),
    "stimulus_scope": names["stimulus_scope"].get(sim.StimScope),
    "bit_sequence": names["bit_sequence"].get(st.BitSequenceType),
    "prbs_order": st.BitOrder,
    "repetitions": st.Repetitions,
    "frequency": st.Frequency,
    "bitrate": 2 * st.Frequency if st.BitSequenceType == h.hlBitSequenceOscillator else st.Frequency,
    "duty_cycle": st.DutyCycle,
    "initial_state": names["initial_state"].get(st.InitialState),
    "stop_s": None if sim.StopAuto else sim.StopTime,
    "step_s": None if sim.StepAuto else sim.Step,
    "jitter": {k: getattr(jt, k) for k in jitter_keys},
    "lossy": ss.Lossy,
    "roughness": ss.SurfaceRoughness,
    "trapezoid": ss.TrapezoidTraces,
    "nonfunctional_pads": ss.NonfunctionPads,
    "crosstalk": ss.Crosstalk,
    "trace_coupling": {"enabled": xt.TraceCoupling.Enabled, "method": names["method"].get(xt.TraceCoupling.Method), "threshold": xt.TraceCoupling.Threshold, "max_distance": xt.TraceCoupling.MaxDistToAggressor, "min_segment": xt.TraceCoupling.MinCoupleSegLen, "horizontal_neighbours": xt.TraceCoupling.HorzNeighborLim, "vertical_neighbours": xt.TraceCoupling.VertNeighborLim, "nonparallel": xt.TraceCoupling.NonParallel, "self": xt.TraceCoupling.Self},
    "area_fill_coupling": {"enabled": xt.AreaFillCoupling.Enabled, "grid": xt.AreaFillCoupling.Grid, "search_distance": xt.AreaFillCoupling.SearchDist},
    "driver_states": job["driver_states"],
    "aggressors": job["aggressors"],
    "models": job.get("models", {}),
    "component_values": job.get("component_values", {}),
}
say("settings: " + ", ".join(f"{k}={v}" for k, v in settings.items() if k not in ("aggressors", "trace_coupling", "area_fill_coupling")))
if not sim.Run():
    raise SystemExit(f"simulation failed: {app.LastError or 'see bsw.log in the run folder'}")
settings["waves"] = save_waves(sim.Result, out)
write_json(os.path.join(out, "si.json"), settings)
say(f"{len(settings['waves'])} waveforms")
