"""What HyperLynx sees in a board: stackup, nets (length, trace segments, vias, pins and their
models), VRMs and DC sinks.   -> info.json in the output folder."""

from common import h, load_job, open_board, say, vrms, write_json  # noqa: F401

job = load_job()
app = open_board(job)
d = app.Design

stackup = []
for lay in d.Stackup.Layers:
    m = lay.Material
    stackup.append({"name": lay.Name, "type": lay.Type, "thickness_m": lay.Thickness, "er": m.RelativePermittivity, "loss_tangent": m.LossTangent, "resistivity": m.BulkResistivity})

nets = []
for n in d.Nets:
    pins = []
    for p in n.Pins:
        model = p.Model
        pins.append({"pin": p.FullName, "x": p.X, "y": p.Y, "model": None if model is None else {"lib": model.LibFile, "device": model.Device, "io_dir": model.IoDir}, "dc_sink": None if p.DCSink is None else {"current": p.DCSink.Current, "resistance": p.DCSink.Resistance}})
    nets.append({"name": n.Name, "supply": n.IsSupply, "length_m": n.Length, "segments": n.Segments.Count, "vias": n.Vias.Count, "pins": pins})

info = {"board": job["board"], "stackup": stackup, "vrms": vrms(d), "nets": nets}
write_json(job["out"] + "/info.json", info)

say("stackup: " + ", ".join(f"{s['name']} {s['thickness_m'] * 1e6:.2f} um" for s in stackup))
say(f"{len(nets)} nets; VRMs: " + ", ".join(f"{v['power_net']} {v['voltage']} V (ref {v['ref_net'] or '-'})" for v in info["vrms"]))
routed = sorted((n for n in nets if n["segments"]), key=lambda n: -n["length_m"])
say(f"{len(routed)} nets with traces" + (": " + ", ".join(f"{n['name']} {n['length_m'] * 1e3:.1f} mm" for n in routed[:12]) if routed else " (all copper is pours: layz.gds2hyp writes signal routes as traces)"))
modelled = [p["pin"] for n in nets for p in n["pins"] if p["model"]]
say(f"{len(modelled)} pins with IBIS/SPICE models")
