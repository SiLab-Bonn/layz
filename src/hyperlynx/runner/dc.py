"""DC drop (HyperLynx PowerSI DC): pin currents and voltages, every via's current, HyperLynx's
CSV report, its PowerScope file (.tps, for the GUI) and its thermal export (loss per cell).

Every setting comes from the job (layz.hyperlynx.run.dc documents them). With return_from, the
return nets are solved as the supply instead (the thermal export covers supply nets only; DC is
linear, so with the VRM moved to the return pins and the measured return currents as sinks, this
is the return path's map: its pin voltages are the VRM voltage minus the ground rise).

Outputs: ports.csv, vias.csv, report.csv, powerscope.tps, Thermal__<net>.txt, vrms.json
"""

import csv
import os

from common import enum, h, load_job, open_board, say, vrms, write_csv, write_json

job = load_job()
out = os.path.abspath(job["out"])
app = open_board(job)
d, dc = app.Design, app.DCSimulator
write_json(os.path.join(out, "vrms.json"), vrms(d))


def supply_nets():
    nets = job["nets"]
    if not nets:
        raise SystemExit("name the supply nets to solve")
    missing = [n for n in nets if d.FindNet(n) is None]
    if missing:
        raise SystemExit(f"no such net(s): {', '.join(missing)}")
    return nets


def swap_to_return(ports):
    """Replace each selected supply's VRM by one sourcing its return net at the old reference
    pins, move the sinks to the return pins (their measured currents). Returns the return nets."""
    chosen = set(supply_nets())
    swaps = []
    for v in list(d.VRMs):
        for ph in v.VRMPhases:
            if ph.PowerNet in chosen and ph.RefPins.Count:
                swaps.append((v, v.Voltage, ph.PowerNet, ph.RefNet, [str(p) for p in ph.PowerPins], [str(p) for p in ph.RefPins]))
    if not swaps:
        raise SystemExit("no VRM with a reference net among the chosen supplies")
    returns, vrm_pins = [], set()
    for v, volts, pnet, rnet, ppins, rpins in swaps:
        d.RemoveVRM(v)
        nv = d.CreateVRM(volts, enum("vrm_type", job["return_vrm_type"]), "ret_" + rnet.strip("/"))
        if nv.VRMPhases.Count == 0:
            nv.SetPhaseCount(1)
        ph = next(iter(nv.VRMPhases))
        for p in rpins:
            if p not in [str(x) for x in ph.PowerPins]:
                ph.AddPowerPin(p)
        ph.SetRefNet(pnet)
        for p in ppins:
            ph.AddRefPin(p)
        d.AddNewVRM(nv)
        returns.append(rnet)
        vrm_pins.update(ppins + rpins)
    supplies = {s[2] for s in swaps}
    for p in ports:  # sinks off the supplies ...
        if p["net"] in supplies and p["pin"] not in vrm_pins:
            pin = d.FindPin(p["pin"])
            if pin is not None and pin.DCSink is not None:
                pin.RemoveDCSink()
    total = 0.0
    for p in ports:  # ... onto the return pins (a sink: a current source with a resistance across)
        i = abs(float(p["current_A"]))
        if p["net"] in returns and p["pin"] not in vrm_pins and i > 0:
            d.FindPin(p["pin"]).AssignDCSink(i, float(job["return_sink_resistance"]))
            total += i
    say(f"return run: {', '.join(returns)} sourced at the old reference pins, {total:.4f} A of sinks")
    return returns


if job["return_from"] is not None:
    with open(job["return_from"]) as f:
        nets = swap_to_return(list(csv.DictReader(f)))
    include_ref = False  # the old supplies are now the reference: the run covers both
else:
    nets = supply_nets()
    include_ref = bool(job["include_ref"])

dc.OutputFolder = out
dc.WritePowerMap = True  # the loss map layz plots
dc.IncludeRefNets = include_ref
dc.Constraint.MaxVoltageDrop = float(job["max_voltage_drop"])
dc.Constraint.MaxCurrentDensity = float(job["max_current_density"])
dc.Constraint.MaxViaCurrent = float(job["max_via_current"])
for n in nets:
    dc.AddNet(d.FindNet(n))
say(f"DC drop: {', '.join(nets)}" + (" (+ reference nets)" if include_ref else ""))
if not dc.Run():
    raise SystemExit(f"DC drop failed: {app.LastError}")
r = dc.Result


def xy(p):
    return (p.X, p.Y) if p is not None else ("", "")


rows = []
for q in r.Ports:
    pin = d.FindPin(q.Pin)
    rows.append([q.Pin, pin.Net.Name if pin else "", *(xy(pin) if pin else ("", "")), q.Type, q.Current, q.Voltage])
write_csv(os.path.join(out, "ports.csv"), ["pin", "net", "x", "y", "type", "current_A", "voltage_V"], rows)
write_csv(os.path.join(out, "vias.csv"), ["net", "type", "layer1", "layer2", "x1", "y1", "x2", "y2", "current_A", "drop_V"], ([c.Net, c.Type, c.Layer1, c.Layer2, *xy(c.Location1), *xy(c.Location2), c.Current, c.VoltageDrop] for c in r.Connectors))
dc.GenerateReport(h.hlReportFormatCSV, os.path.join(out, "report.csv"))
dc.SaveGraph(os.path.join(out, "powerscope.tps"))
m = r.MaxCurrentDensity
write_json(os.path.join(out, "summary.json"), {"nets": nets, "include_ref": include_ref, "return_run": job["return_from"] is not None, "constraint": {"max_voltage_drop": dc.Constraint.MaxVoltageDrop, "max_current_density": dc.Constraint.MaxCurrentDensity, "max_via_current": dc.Constraint.MaxViaCurrent}, "max_current_density": {"value": m.Density, "layer": m.Layer, "at": list(xy(m.Location))}})
say(f"{r.Ports.Count} pins, {r.Connectors.Count} vias; max current density {m.Density:.3g} on {m.Layer}")
