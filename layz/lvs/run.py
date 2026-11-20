"""LVS for a flow's targets (layz.flow): the layout's nets, named by its labels, against a KiCad
schematic, into one folder. The command line (`layz lvs`) is the same.

    from layz.lvs import analysis, run

    checked = run.lvs(GDS, RESULTS / "lvs", stack="uni-bonn-rdl", schematic=SCH)
    analysis.findings(checked, out=checked / "summary.csv")

Writes lvs.lyrdb (KLayout markers), findings.csv (kind, what, x, y µm), summary.json (the
counts) and job.json. A PCB is compared with its schematic by KiCad itself (its schematic
parity: the .kicad_sch next to the board, by the project's name):

    checked = run.board(PCB, RESULTS / "lvs", refill_zones=True)
    analysis.parity(checked, out=checked / "summary.csv")

which writes parity.json (KiCad's DRC report with schematic parity) and parity.csv.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


def lvs(layout: Path, out: Path, *, stack: str | Path, schematic: Path) -> Path:
    """Compare ``layout`` (copper, vias and labels of ``stack``) with ``schematic`` (.kicad_sch,
    read with kicad-cli, or its .net netlist)."""
    import klayout.db as kdb

    from layz import stack as stackfile
    from layz.lvs.compare import compare, extract, schematic_netlist, write_report

    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps({"layout": str(layout), "stack": str(stack), "schematic": str(schematic)}, indent=1))
    sch = schematic_netlist(Path(schematic))
    nets, labels, _ = extract(Path(layout), stackfile.load(stack))
    found, stats = compare(sch, labels)
    with open(out / "findings.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "what", "x_um", "y_um"])
        w.writerows([x.kind, x.what, f"{x.where[0][0]:.3f}", f"{x.where[0][1]:.3f}"] for x in found)
    kinds = ("open", "short", "unknown", "floating")
    summary = {"layout nets": len(nets), **stats, **{k: sum(1 for x in found if x.kind == k) for k in kinds}}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    ly = kdb.Layout()
    ly.read(str(layout))
    write_report(out / "lvs.lyrdb", ly.top_cell().name, found)
    return out


def board(pcb: Path, out: Path, *, refill_zones: bool) -> Path:
    """KiCad's schematic parity of ``pcb`` (kicad-cli pcb drc --schematic-parity): footprints,
    nets and values against the project's schematic, and the copper's unconnected items."""
    import subprocess

    from layz import kicad

    cli = kicad.cli()
    if not cli:
        raise SystemExit("kicad-cli not found: run install/kicad.sh")
    if not Path(pcb).with_suffix(".kicad_sch").exists():
        raise SystemExit(f"no {Path(pcb).with_suffix('.kicad_sch').name} next to {pcb}: KiCad compares the board with its project's schematic")
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps({"board": str(pcb), "refill_zones": refill_zones}, indent=1))
    report = out / "parity.json"
    subprocess.run([cli, "pcb", "drc", "--format", "json", "--schematic-parity", "--severity-all", "--units", "mm", "-o", str(report), *(["--refill-zones"] if refill_zones else []), str(pcb)], check=True, capture_output=True)
    d = json.loads(report.read_text())
    with open(out / "parity.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "what"])
        w.writerows([p["type"], "; ".join(i["description"] for i in p.get("items", [])) or p["description"]] for p in d["schematic_parity"])
        w.writerows(["unconnected", "; ".join(i["description"] for i in u.get("items", []))] for u in d["unconnected_items"])
    return out
