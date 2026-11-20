"""A board for the viewer: a .hyp read into plain JSON (mm, Y up): its outline, stackup, copper per
net and layer, traces, vias, pins, and the counts the board panel shows (trace widths, via sizes
and spans, layers, thickness, size)."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

MM = 25.4  # .hyp lengths are inches
_KV = re.compile(r'(\w+)=("[^"]*"|[^\s)]+)')


def _rec(line: str) -> dict[str, str]:
    return {k: v.strip('"') for k, v in _KV.findall(line)}


def read(hyp: Path) -> dict:
    lines = Path(hyp).read_text(errors="replace").splitlines()
    outline, stackup, padstacks = [], [], {}
    polys, segs, vias, pins = [], [], [], []
    devices = set()
    net = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s.startswith("(PERIMETER_SEGMENT"):
            r = _rec(s)
            outline.append([float(r[k]) * MM for k in ("X1", "Y1", "X2", "Y2")])
        elif s.startswith(("(SIGNAL", "(DIELECTRIC")):
            r = _rec(s)
            stackup.append({"name": r.get("L", ""), "type": "copper" if s.startswith("(SIGNAL") else "mask" if "Mask" in r.get("L", "") else "dielectric", "thickness_mm": float(r.get("T", 0)) * MM, "er": float(r["C"]) if "C" in r and s.startswith("(DIELECTRIC") else None, "material": r.get("M", "")})
        elif s.startswith("(?") and "REF=" in s:
            devices.add(_rec(s)["REF"])
        elif s.startswith("{PADSTACK="):
            head = s[len("{PADSTACK=") :].split(",")
            pid, drill = int(head[0]), float(head[1]) * MM if len(head) > 1 and head[1].strip() else 0.0
            shapes = []
            i += 1
            while not lines[i].strip().startswith("}"):
                parts = [p.strip().strip('"') for p in lines[i].strip().strip("()").split(",")]
                shapes.append({"layer": parts[0], "shape": int(parts[1]), "w": float(parts[2]) * MM, "h": float(parts[3]) * MM})
                i += 1
            padstacks[pid] = {"drill": drill, "shapes": shapes}
        elif raw.startswith("{NET="):
            net = raw.split('"')[1] if '"' in raw else raw[5:].strip()
        elif raw.startswith("}"):
            net = None
        elif net is not None:
            if s.startswith(("{POLYGON", "{POLYVOID")):
                r = _rec(s)
                pts = []
                i += 1
                while not lines[i].strip().startswith("}"):
                    v = _rec(lines[i])
                    if "X" in v:
                        pts.append([round(float(v["X"]) * MM, 5), round(float(v["Y"]) * MM, 5)])
                    i += 1
                if s.startswith("{POLYGON"):
                    polys.append({"net": net, "layer": r.get("L", ""), "id": r.get("ID"), "pts": pts, "holes": []})
                else:
                    for p in reversed(polys):
                        if p["id"] == r.get("ID"):
                            p["holes"].append(pts)
                            break
            elif s.startswith("(SEG"):
                r = _rec(s)
                segs.append({"net": net, "layer": r["L"], "x1": float(r["X1"]) * MM, "y1": float(r["Y1"]) * MM, "x2": float(r["X2"]) * MM, "y2": float(r["Y2"]) * MM, "w": float(r["W"]) * MM})
            elif s.startswith("(VIA"):
                r = _rec(s)
                vias.append({"net": net, "x": float(r["X"]) * MM, "y": float(r["Y"]) * MM, "p": int(r["P"])})
            elif s.startswith("(PIN"):
                r = _rec(s)
                pins.append({"net": net, "ref": r["R"], "x": float(r["X"]) * MM, "y": float(r["Y"]) * MM, "p": int(r["P"])})
        i += 1

    for v in vias:
        ps = padstacks.get(v["p"], {"drill": 0.0, "shapes": []})
        sizes = [sh["w"] for sh in ps["shapes"]] or [0.0]
        v.update(d=max(sizes), drill=ps["drill"], layers=[sh["layer"] for sh in ps["shapes"]])
    for p in pins:
        ps = padstacks.get(p["p"], {"drill": 0.0, "shapes": []})
        sh = ps["shapes"][0] if ps["shapes"] else {"layer": "", "w": 0.0, "h": 0.0}
        p.update(layer=sh["layer"], w=sh["w"], h=sh["h"])

    copper = [l["name"] for l in stackup if l["type"] == "copper"]
    order = {name: k for k, name in enumerate(copper)}
    spans = Counter()
    for v in vias:
        on = sorted((l for l in v["layers"] if l in order), key=order.get)
        if on:
            spans[f"{on[0]} / {on[-1]}"] += 1
    xs = [c for s in outline for c in (s[0], s[2])] or [p[0] for q in polys for p in q["pts"]] or [0.0]
    ys = [c for s in outline for c in (s[1], s[3])] or [p[1] for q in polys for p in q["pts"]] or [0.0]
    stats = {"copper_layers": len(copper), "thickness_mm": sum(l["thickness_mm"] for l in stackup), "size_mm": [max(xs) - min(xs), max(ys) - min(ys)], "nets": len({x["net"] for x in polys + segs + vias + pins}), "pours": len(polys), "tracks": len(segs), "vias": len(vias), "pins": len(pins), "components": len(devices), "trace_widths": sorted(Counter(round(s["w"], 4) for s in segs).items(), key=lambda kv: -kv[1]), "via_profiles": sorted(Counter(f"{v['d']:.3f} / {v['drill']:.3f}" for v in vias).items(), key=lambda kv: -kv[1]), "via_spans": sorted(spans.items(), key=lambda kv: -kv[1])}
    return {"name": Path(hyp).name, "bbox": [min(xs), min(ys), max(xs), max(ys)], "outline": outline, "stackup": stackup, "copper": copper, "polys": [{k: p[k] for k in ("net", "layer", "pts", "holes")} for p in polys], "segs": segs, "vias": [{k: v[k] for k in ("net", "x", "y", "d", "drill", "layers")} for v in vias], "pins": [{k: p[k] for k in ("net", "ref", "x", "y", "w", "h", "layer")} for p in pins], "stats": stats}
