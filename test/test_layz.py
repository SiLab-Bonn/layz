"""layz's tests, run by `layz doctor` (tests needing FasterCap or KiCad are skipped without them)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from layz import cli, stack

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "test"
RDL = "uni-bonn-rdl"  # a process by name: tech/uni-bonn-rdl/stack.toml

try:
    import pcbnew  # noqa: F401

    HAVE_PCBNEW = True
except ImportError:
    HAVE_PCBNEW = False
HAVE_FASTERCAP = shutil.which("FasterCap") is not None
needs_kicad = pytest.mark.skipif(not HAVE_PCBNEW, reason="KiCad's pcbnew module not found")
needs_fastercap = pytest.mark.skipif(not HAVE_FASTERCAP, reason="FasterCap not on PATH")


def test_cli_lists_commands(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for cmd in ("gds2pcb", "gds2hyp", "hyp", "nets", "lvs", "pex", "field", "view", "doctor"):
        assert f"layz {cmd}" in out


def test_stack_heights_from_order():
    p = stack.load(RDL)
    assert [l.name for l in p.copper] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    # asiclab's z: chip pad top at 0 (here 1), M2 7..13, M3 25..31, P3 to 36 (here 37)
    assert p.thickness_um == pytest.approx(37.5)
    assert p.by_name("B.Cu").z_um == 0
    assert p.by_name("In2.Cu").z_um == pytest.approx(8)
    assert p.by_name("In1.Cu").z_um == pytest.approx(26)


def test_stack_rejects_bad_files(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('[[layer]]\nname="a"\ntype="copper"\nthickness_um=1\n[[layer]]\nname="m"\ntype="mask"\nthickness_um=1\n[[layer]]\nname="b"\ntype="copper"\nthickness_um=1\n')
    with pytest.raises(ValueError, match="first or last"):
        stack.load(bad)


def test_kicad_stackup_round_trip(tmp_path):
    p = stack.load(RDL)
    pcb = tmp_path / "s.kicad_pcb"
    pcb.write_text("(kicad_pcb\n    (setup\n" + p.kicad_stackup() + "    )\n)\n")
    back = stack.from_kicad_pcb(pcb)
    assert [(l.type, l.thickness_um, l.k) for l in back.layers] == [(l.type, pytest.approx(l.thickness_um), l.k) for l in p.layers]


@pytest.mark.parametrize("path", sorted((ROOT / "tech").glob("**/*.toml")), ids=lambda p: str(p.relative_to(ROOT / "tech")))
def test_every_stack_file(path, tmp_path):
    """Each stack loads, is valid for KiCad, and survives the KiCad stackup round trip."""
    p = stack.load(path)
    p.check_kicad()
    pcb = tmp_path / "s.kicad_pcb"
    pcb.write_text("(kicad_pcb\n    (setup\n" + p.kicad_stackup() + "    )\n)\n")
    back = stack.from_kicad_pcb(pcb)
    assert [(l.type, round(l.thickness_um, 3), l.k) for l in back.layers] == [(l.type, round(l.thickness_um, 3), l.k) for l in p.layers]


@pytest.mark.parametrize("name,total_um", [("multicb/4L-01", 1640), ("multicb/4L-02", 1020), ("multicb/flex_2F-l", 161), ("multicb/flex_2F-a", 187)])
def test_multicb_totals(name, total_um):
    """Totals as published by Multi-CB (rigid: plus 2 x 10 µm assumed solder mask)."""
    assert stack.load(name).thickness_um == pytest.approx(total_um)


@needs_kicad
def test_gds_to_hyp(tmp_path):
    """test/route.gds (two pads, a route, a via, a plane) through layz gds2pcb and gds2hyp: the
    .hyp's STACKUP is test/route.toml's layers, in inches, with their εr."""
    hyp = tmp_path / "route.hyp"
    assert cli.main(["gds2hyp", str(TESTS / "route.gds"), "--stack", str(TESTS / "route.toml"), "-o", str(hyp)]) == 0
    text = hyp.read_text()
    assert text.startswith("{VERSION=2.14}\n{UNITS=ENGLISH LENGTH}\n")
    rows = re.findall(r"\((SIGNAL|DIELECTRIC) T=([\d.e-]+) .*?C=([\d.e-]+)", text.split("{STACKUP", 1)[1].split("}", 1)[0])
    layers = [l for l in stack.load(TESTS / "route.toml").layers if l.type in ("copper", "dielectric")]
    assert [r[0] for r in rows] == ["SIGNAL" if l.type == "copper" else "DIELECTRIC" for l in layers]
    assert [float(r[1]) * 25400 for r in rows] == pytest.approx([l.thickness_um for l in layers], rel=1e-4)
    assert [float(r[2]) for r in rows if r[0] == "DIELECTRIC"] == [l.er for l in layers if l.type == "dielectric"]
    assert text.count("(VIA ") == 1 and text.count('(? REF="FP') == 2


@needs_fastercap
def test_vacuum_plates_capacitance(tmp_path):
    """Two 1 mm² plates, 10 µm vacuum gap: 918.8 fF mutual (ideal 885 fF + fringe)."""
    out = tmp_path / "run"
    cli.main(["pex", str(TESTS / "plates.gds"), "--stack", str(TESTS / "plates.toml"), "--out", str(out)])
    rows = (out / "maxwell_matrix_fF.csv").read_text().splitlines()
    mutual = -float(rows[1].split(",")[2])
    assert mutual == pytest.approx(918.8, rel=0.01)


@needs_kicad
def test_kicad_board_model(tmp_path):
    """The 10 mm PCB plate board becomes the validated 3-D model (3788 triangles, 1888 copper);
    solved at 1 % it gives 21.54 pF (9 min on 18 threads, so not repeated here)."""
    out = tmp_path / "run"
    cli.main(["pex", str(TESTS / "pcb_plates.kicad_pcb"), "--dry-run", "--out", str(out)])
    geo = list(out.glob("m*.geo"))
    count = lambda files: sum(f.read_text().count("\nT ") for f in files)
    assert count(geo) == 3788
    assert count([f for f in geo if "net=" in f.name]) == 1888


# ------------------------------------------------------------------ pours -> traces (layz.gds2hyp.traces)


def _l_route(w=0.04, pad=0.3):
    """An L-shaped 40 µm strip (2 mm then 1 mm) with a square pad at its start (mm)."""
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union

    strip = LineString([(0, 0), (2, 0), (2, 1)]).buffer(w / 2, cap_style="flat", join_style="mitre")
    return unary_union([strip, box(-pad / 2, -pad / 2, pad / 2, pad / 2)])


def test_traces_l_route_with_pad():
    from shapely.geometry import Point

    from layz.gds2hyp.traces import split_route

    segs, keep = split_route(_l_route(), [Point(0, 0)])
    length = sum(((s.x2 - s.x1) ** 2 + (s.y2 - s.y1) ** 2) ** 0.5 for s in segs)
    assert all(abs(s.width - 0.04) < 0.002 for s in segs)
    assert abs(length - 3.0) < 0.1  # runs into the pad's pin, to the strip's end
    assert keep == []  # the pad holds the pin: its padstack models it
    ends = {(round(s.x1, 3), round(s.y1, 3)) for s in segs} | {(round(s.x2, 3), round(s.y2, 3)) for s in segs}
    assert (0.0, 0.0) in ends  # reaches the pin


def test_traces_leave_planes_alone():
    from shapely.geometry import box

    from layz.gds2hyp.traces import split_route

    assert split_route(box(0, 0, 5, 3)) is None  # a plane is not a route


def test_hyp_traces_pass_converts_signal_keeps_supply():
    from layz.gds2hyp.convert import add_traces

    def poly(pid, pts):
        lines = [f'  {{POLYGON T=POUR L="In1.Cu" ID={pid} X={pts[0][0]:.6f} Y={pts[0][1]:.6f}\n']
        lines += [f"    (LINE X={x:.6f} Y={y:.6f})\n" for x, y in pts + [pts[0]]]
        return "".join(lines) + "  }\n"

    inch = 1 / 25.4
    strip = [(0, 0), (4 * inch, 0), (4 * inch, 0.04 * inch), (0, 0.04 * inch)]  # 4 mm x 40 µm
    plane = [(0, 1 * inch), (4 * inch, 1 * inch), (4 * inch, 2 * inch), (0, 2 * inch)]
    hyp = f'{{VERSION=2.14}}\n{{UNITS=ENGLISH LENGTH}}\n\n{{NET="SIG"\n  (PIN X=0.000000 Y=0.000787 R="U1.1" P=0)\n  (PIN X={4 * inch:.6f} Y=0.000787 R="U2.1" P=0)\n' + poly(1, strip) + '}\n\n{NET="VDD"\n  (PIN X=0.01 Y=0.05 R="U1.2" P=0)\n  (PIN X=0.1 Y=0.05 R="U2.2" P=0)\n' + poly(2, plane) + "}\n\n"
    out, report = add_traces(hyp)
    sig = out.split('{NET="SIG"')[1].split("}\n\n")[0]
    vdd = out.split('{NET="VDD"')[1]
    assert [r[0] for r in report] == ["SIG"]
    assert "(SEG" in sig and "{POLYGON" not in sig
    assert "{POLYGON" in vdd and "(SEG" not in vdd
    assert abs(report[0][2] - 4.0) < 0.05 and abs(report[0][3] - 0.04) < 0.002  # mm
    assert add_traces(hyp, "none")[0] == hyp


# ------------------------------------------------------------------ layz lvs


def test_lvs_finds_open_short_unknown(tmp_path):
    import klayout.db as kdb

    from layz.lvs import compare as lvs

    (tmp_path / "stack.toml").write_text('name = "t"\n[[layer]]\nname = "F.Cu"\ntype = "copper"\nthickness_um = 1\ngds = "6/0"\n[[layer]]\nname = "D"\ntype = "dielectric"\nthickness_um = 5\n[[layer]]\nname = "B.Cu"\ntype = "copper"\nthickness_um = 1\ngds = "3/0"\n[[via]]\ngds = "4/0"\ntop = "F.Cu"\nbottom = "B.Cu"\n')
    (tmp_path / "sch.net").write_text('(export (nets (net (code "1") (name "/A") (node (ref "U1") (pin "1")) (node (ref "U2") (pin "1"))) (net (code "2") (name "/B") (node (ref "U1") (pin "2")) (node (ref "U2") (pin "2"))) (net (code "3") (name "/C") (node (ref "U1") (pin "3"))) (net (code "4") (name "/D") (node (ref "U2") (pin "3")))))')
    ly = kdb.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("TOP")
    m3, m2, v, l3 = (ly.layer(*ld) for ld in ((6, 0), (3, 0), (4, 0), (6, 1)))  # 6/1: M3's pin layer
    um = lambda *a: kdb.Box(*[int(x * 1000) for x in a])
    top.shapes(m3).insert(um(0, 0, 100, 10))
    top.shapes(v).insert(um(95, 0, 100, 10))
    top.shapes(m2).insert(um(95, 0, 200, 10))  # A: across the via
    top.shapes(l3).insert(kdb.Text("U1.1", kdb.Trans(5000, 5000)))
    top.shapes(m2).insert(kdb.Text("U2.1", kdb.Trans(195000, 5000)))  # text on a drawing layer
    top.shapes(m3).insert(um(0, 30, 90, 40))
    top.shapes(m3).insert(um(110, 30, 200, 40))  # B: open
    top.shapes(l3).insert(kdb.Text("U1.2", kdb.Trans(5000, 35000)))
    top.shapes(l3).insert(kdb.Text("U2.2", kdb.Trans(195000, 35000)))
    top.shapes(m3).insert(um(0, 60, 200, 70))  # C and D: short
    top.shapes(l3).insert(kdb.Text("C", kdb.Trans(5000, 65000)))
    top.shapes(l3).insert(kdb.Text("/D", kdb.Trans(195000, 65000)))
    top.shapes(l3).insert(kdb.Text("NOPE", kdb.Trans(100000, 5000)))
    ly.write(str(tmp_path / "t.gds"))
    rc = lvs.main(["--lay", str(tmp_path / "t.gds"), "--stack", str(tmp_path / "stack.toml"), "--sch", str(tmp_path / "sch.net"), "--report", str(tmp_path / "r.lyrdb")])
    nets, labels, _ = lvs.extract(tmp_path / "t.gds", stack.load(tmp_path / "stack.toml"), [])
    findings, stats = lvs.compare(lvs.read_netlist((tmp_path / "sch.net").read_text()), labels)
    kinds = sorted(f.kind for f in findings)
    assert rc == 1 and kinds == ["open", "short", "unknown"]
    assert "/B" in next(f.what for f in findings if f.kind == "open")
    assert stats["checked nets"] == 4
    assert (tmp_path / "r.lyrdb").read_text().count("<item>") == 5


# ------------------------------------------------------------------ HyperLynx (no HyperLynx needed)


def test_hyperlynx_overlay(tmp_path, monkeypatch):
    from layz.hyperlynx import setup

    sdd = tmp_path / "install" / "SDD_HOME"
    (sdd / "Scripting" / "bin").mkdir(parents=True)
    (sdd / "Scripting" / "bin" / "pythonHL").write_text("#!/bin/sh\n")
    (sdd / "hyperlynx").mkdir()
    for f in ("Bsw.pak", "Bsw.alg", "bswConsole", "hyperlynx.so"):
        (sdd / "hyperlynx" / f).write_text(f)
    (sdd / "hyperlynx" / "Bsw.pak").chmod(0o444)
    monkeypatch.setenv("LAYZ_HYPERLYNX_HOME", str(sdd))
    monkeypatch.setenv("LAYZ_HYPERLYNX_OVERLAY", str(tmp_path / "ov"))
    monkeypatch.setenv("MGLS_LICENSE_FILE", "1@server")
    install, overlay, env = setup.prepare(quiet=True)
    assert (overlay / "Scripting").is_symlink()
    hl = overlay / "hyperlynx"
    assert hl.is_dir() and not hl.is_symlink()
    assert (hl / "bswConsole").is_symlink() and not (hl / "Bsw.pak").is_symlink()
    (hl / "Bsw.pak").write_text("written by BoardSim")  # writable copy, install untouched
    assert (sdd / "hyperlynx" / "Bsw.pak").read_text() == "Bsw.pak"
    assert env["HYP_HOME"].startswith(str(hl)) and env["MGLS_LICENSE_FILE"] == "1@server"
    assert setup.prepare(quiet=True)[1] == overlay  # second call reuses it


def _hyperlynx_runs(tmp_path):
    """Small synthetic run folders of each kind, as the runners write them."""
    import json

    import numpy as np

    dc = tmp_path / "dc"
    dc.mkdir()
    (dc / "job.json").write_text(json.dumps({"kind": "dc"}))
    (dc / "vrms.json").write_text(json.dumps([{"voltage": 3.0, "power_net": "/V", "power_pins": ["U1.1"], "ref_net": "/G", "ref_pins": ["U1.2"]}]))
    (dc / "summary.json").write_text(json.dumps({"nets": ["/V"], "max_current_density": {"value": 1.0, "layer": "F.Cu", "at": [0, 0]}}))
    (dc / "board").mkdir()
    (dc / "board" / "b.hyp").write_text('{STACKUP\n  (SIGNAL T=0.001 P=0 C=1.724e-08 L="F.Cu" M=COPPER)\n}\n')
    (dc / "ports.csv").write_text("pin,net,x,y,type,current_A,voltage_V\nU1.1,/V,0,0,0,-1.0,3.0\nU2.1,/V,0.01,0,1,1.0,2.9\nU1.2,/G,0,0.001,0,1.0,0.0\nU2.2,/G,0.01,0.001,1,-1.0,0.05\n")
    (dc / "vias.csv").write_text("net,type,layer1,layer2,x1,y1,x2,y2,current_A,drop_V\n/V,0,A,B,0.005,0,0.005,0,1.0,1e-6\n/G,0,A,B,0.005,0.001,0.005,0.001,1.0,1e-6\n")
    grid = "\n".join(f"Row {r}:," + ",".join("1e-4" if 1 <= r <= 2 else "" for _ in range(10)) for r in range(4))
    (dc / "Thermal__V.txt").write_text('Net = "/V", 3\nLayerCount = 1\nLayer: 0, "F.Cu", 0, 0.001\nX_offset = 0\nY_offset = 0\nDx = 0.04\nDy = 0.01\nN_x = 10\nN_y = 4\nLayer = 0\n' + grid + "\n")
    si = tmp_path / "eye"
    si.mkdir()
    t = np.arange(0, 400e-9, 50e-12)
    bits = np.random.default_rng(1).integers(0, 2, 64)
    v = np.where(bits[(t // 6.25e-9).astype(int) % 64], 0.4, -0.4)
    (si / "rx.csv").write_text("Time,V\n" + "\n".join(f"{a:.6e},{b:.4f}" for a, b in zip(t, v)))
    (si / "job.json").write_text(json.dumps({"kind": "si"}))
    (si / "si.json").write_text(json.dumps({"mode": "eye", "lossy": True, "jitter": {}, "waves": [{"name": "V(U2-1,U2-2)", "file": "rx.csv"}]}))
    sp = tmp_path / "sp"
    sp.mkdir()
    (sp / "job.json").write_text(json.dumps({"kind": "sparam"}))
    (sp / "sparam.json").write_text(json.dumps({"pins": ["A", "B"], "lossy": True, "file": "sparams.s2p"}))
    (sp / "sparams.s2p").write_text("# HZ S RI R 50\n1e6 0.1 0 0.9 0 0.9 0 0.1 0\n1e9 0.3 0 0.7 0 0.7 0 0.3 0\n")
    return dc, si, sp


def test_hyperlynx_touchstone_and_plots(tmp_path):
    import numpy as np

    from layz.hyperlynx import plots

    dc, si, sp = _hyperlynx_runs(tmp_path)
    f, S = plots.read_touchstone(sp / "sparams.s2p")
    assert f.tolist() == [1e6, 1e9] and np.isclose(S[0, 1, 0], 0.9) and np.isclose(S[1, 0, 0], 0.3)
    paths = plots.plot_dc(dc, tmp_path / "plots") + plots.plot_si([si], tmp_path / "plots", skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), settle=0.1) + plots.plot_sparam(sp, tmp_path / "plots")
    names = {p.stem for p in paths}
    assert {"dc_pin_voltage", "dc_via_current", "dc_loss_map", "si_waveforms", "si_eye", "sparams_sp"} <= names
    assert all(p.exists() for p in paths)


def test_hyperlynx_analysis(tmp_path):
    from layz.hyperlynx import analysis

    dc, si, sp = _hyperlynx_runs(tmp_path)
    (row,) = analysis.dc_drop(dc, max_drop=0.04, out=tmp_path / "dc.csv")
    assert abs(row["drop_mV"] - 100) < 1e-6 and abs(row["return_rise_mV"] - 50) < 1e-6
    assert row["pass"] is False and (tmp_path / "dc.csv").exists()  # 150 mV of 3 V: 5 %
    assert analysis.dc_drop(dc, max_drop=0.06, out=None)[0]["pass"] is True
    (eye,) = analysis.eyes([si], min_height=0.2, min_width_ui=0.7, at=None, skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8), out=tmp_path / "eyes.csv")
    assert eye["height_mV"] > 700 and eye["width_ui"] > 0.9 and eye["pass"]
    assert 0 < eye["rise_ps"] <= 50 and 0 < eye["fall_ps"] <= 50  # one 50 ps sample per edge
    assert analysis.crosstalk(si, max_noise=0.1, at=None, settle=0.1, out=None)[0]["pass"] is False  # an eye is no quiet line
    assert analysis.sparams(sp, at_hz=1e9, min_sdd21_db=-3, max_sdd11_db=-10, out=None) == []  # a 2-port: no mixed mode


def test_current_density(tmp_path):
    """J = sqrt(P / (rho t A)) from the loss export: 1e-4 W in a 1.016 x 0.254 mm cell of 25.4 um copper."""
    import numpy as np

    from layz.hyperlynx import analysis, plots

    dc, _, _ = _hyperlynx_runs(tmp_path)
    J, rho, _ = plots.current_density(dc)["F.Cu"]
    expect = (1e-4 / (1.724e-8 * 25.4e-6 * 1.016e-3 * 0.254e-3)) ** 0.5
    assert rho == 1.724e-8 and abs(np.nanmax(J) / expect - 1) < 1e-9 and np.isnan(J[0, 0])
    (row,) = analysis.current_density(dc, max_density=1e7, out=None)  # J is 3e7
    assert row["layer"] == "F.Cu" and row["pass"] is False and row["over_limit_pct"] == 100
    assert abs(row["max_drop_mV_per_mm"] - rho * expect) < 1e-9


def test_eye_densify_and_hexagon():
    import numpy as np

    from layz.hyperlynx import plots

    t, v = plots.densify([0, 1, 2], [0, 1, 1], 0.25)
    assert t.tolist() == [0, 0.25, 0.5, 0.75, 1, 2] and v.tolist() == [0, 0.25, 0.5, 0.75, 1, 1]
    ui, rng = 1e-9, np.random.default_rng(2)
    bits = rng.integers(0, 2, 200)
    t = np.arange(0, 200 * ui, 10e-12)
    k = np.minimum((t // ui).astype(int), 199)
    edge = np.clip((t % ui) / 100e-12, 0, 1)  # 100 ps linear edges
    prev = np.roll(bits, 1)[k]
    v = (prev + (bits[k] - prev) * edge) - 0.5
    e = plots.eye(t, v, ui, skip_ui=4, centre_window=0.05, edge_levels=(0.2, 0.8))
    assert abs(e["height"] - 1) < 0.02 and e["width"] > 0.85 * ui
    assert 50e-12 < e["rise"] < 70e-12 and 50e-12 < e["fall"] < 70e-12  # 20-80 % of 100 ps
    hx = np.array(e["hexagon"])
    assert len(hx) == 6 and hx[:, 1].max() <= 0.5 + 1e-9 and hx[:, 1].min() >= -0.5 - 1e-9


def test_hyperlynx_targets(tmp_path, capsys):
    from layz.hyperlynx import cli, targets

    flow = tmp_path / "flow.py"
    flow.write_text('from layz.hyperlynx import target\nDONE = []\n\n@target\ndef first():\n    """One."""\n    DONE.append("first")\n\n@target\ndef second():\n    """Two, after first."""\n    if "first" not in DONE:\n        first()\n    (DONE.append("second"), open(__file__ + ".out", "w").write(" ".join(DONE)))\n')
    assert cli.main(["-f", str(flow)]) == 0
    listing = capsys.readouterr().out
    assert "first" in listing and "Two, after first." in listing
    assert cli.main(["-f", str(flow), "second"]) == 0
    assert (tmp_path / "flow.py.out").read_text() == "first second"
    with pytest.raises(SystemExit):
        cli.main(["-f", str(flow), "nope"])
    with pytest.raises(TypeError):
        targets.target(lambda x: None)
