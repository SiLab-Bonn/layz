"""layz checks: `uv run pytest` (solver tests are skipped when FasterCap/KiCad are missing)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from layz import cli, stack

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
EXAMPLES = ROOT / "example_files"
RDL = ROOT / "stacks" / "uni_bonn_rdl.toml"
OBELIX_KICAD = TESTS / "obelix_kicad_stack.toml"
REF_HYP = EXAMPLES / "obelix1_ivtx_ladder_with_nets_v3.1.hyp"

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
    for cmd in ("gds2pcb", "nets", "hyp", "pex", "field", "view", "doctor"):
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
    bad.write_text('[[layer]]\nname="a"\ntype="copper"\nthickness_um=1\n'
                   '[[layer]]\nname="m"\ntype="mask"\nthickness_um=1\n'
                   '[[layer]]\nname="b"\ntype="copper"\nthickness_um=1\n')
    with pytest.raises(ValueError, match="first or last"):
        stack.load(bad)


def test_kicad_stackup_round_trip(tmp_path):
    p = stack.load(RDL)
    pcb = tmp_path / "s.kicad_pcb"
    pcb.write_text("(kicad_pcb\n    (setup\n" + p.kicad_stackup() + "    )\n)\n")
    back = stack.from_kicad_pcb(pcb)
    assert [(l.type, l.thickness_um, l.k) for l in back.layers] == \
           [(l.type, pytest.approx(l.thickness_um), l.k) for l in p.layers]


@pytest.mark.parametrize("path", sorted((ROOT / "stacks").glob("*.toml")), ids=lambda p: p.stem)
def test_every_stack_file(path, tmp_path):
    """Each stack loads, is valid for KiCad, and survives the KiCad stackup round trip."""
    p = stack.load(path)
    p.check_kicad()
    pcb = tmp_path / "s.kicad_pcb"
    pcb.write_text("(kicad_pcb\n    (setup\n" + p.kicad_stackup() + "    )\n)\n")
    back = stack.from_kicad_pcb(pcb)
    assert [(l.type, round(l.thickness_um, 3), l.k) for l in back.layers] == \
           [(l.type, round(l.thickness_um, 3), l.k) for l in p.layers]


@pytest.mark.parametrize("name,total_um", [("multicb_4L-01", 1640), ("multicb_4L-02", 1020),
                                           ("multicb_flex_2F-l", 161), ("multicb_flex_2F-a", 187)])
def test_multicb_totals(name, total_um):
    """Totals as published by Multi-CB (rigid: plus 2 x 10 µm assumed solder mask)."""
    assert stack.load(ROOT / "stacks" / f"{name}.toml").thickness_um == pytest.approx(total_um)


@needs_kicad
def test_gds_to_hyp_stackup_matches_kicad_gui(tmp_path):
    """The obelix1 RDL GDS through gds2pcb --stack and layz hyp, with the stackup that was typed
    into KiCad, gives the same STACKUP section that KiCad's GUI exporter wrote."""
    hyp = tmp_path / "ob.hyp"
    assert cli.main(["hyp", str(EXAMPLES / "obelix1_ivtx_ladder_v2.gds"), "--stack", str(OBELIX_KICAD),
                     "-o", str(hyp)]) == 0
    section = lambda f: re.search(r"\{STACKUP\n.*?\n\}", Path(f).read_text(), re.S).group(0)
    assert section(hyp) == section(REF_HYP)
    text = hyp.read_text()
    assert text.startswith("{VERSION=2.14}\n{UNITS=ENGLISH LENGTH}\n")
    assert text.count("(VIA ") > 12000


@needs_fastercap
def test_vacuum_plates_capacitance(tmp_path):
    """Two 1 mm² plates, 10 µm vacuum gap: 918.8 fF mutual (ideal 885 fF + fringe)."""
    out = tmp_path / "run"
    cli.main(["pex", str(TESTS / "plates.gds"), "--stack", str(TESTS / "plates.toml"),
              "--out", str(out)])
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
