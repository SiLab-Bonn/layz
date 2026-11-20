"""Design rule check for a flow's targets (layz.flow): gdscheck with the kit's deck, every option
given, into one folder. The command line (`layz drc`) is the same with defaults.

    from layz.drc import analysis, run

    checked = run.drc(GDS, RESULTS / "drc", kit="uni-bonn-rdl", suite="main", topcell=None, tile=20000.0)
    analysis.violations(checked, max_violations=0, out=checked / "violations.csv")

Writes drc.lyrdb (KLayout markers: `layz view drc.lyrdb --lay GDS`), rules.csv (violations per
rule) and job.json.
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path


def drc(layout: Path, out: Path, *, kit: str, suite: str, topcell: str | None, tile: float) -> Path:
    """Check ``layout`` against the rules of ``kit`` (tech/<kit>/pdk.yml).

    suite    the deck's suite (main: everything; geometry: without density)
    topcell  None: the layout's only top cell
    tile     gdscheck's merge tile, µm (20000 for boards and RDL)
    """
    from layz import solvers
    from layz.drc.check import DRC_DIR, kits, top_cell

    if kit not in kits():
        raise SystemExit(f"no DRC deck for kit {kit!r}; have: {', '.join(kits())}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps({"layout": str(layout), "kit": kit, "suite": suite, "topcell": topcell, "tile": tile}, indent=1))
    report = out / "drc.lyrdb"
    report.unlink(missing_ok=True)
    cmd = [solvers.find("gdscheck"), "run", "--pdk-path", str(DRC_DIR), "-p", kit, "-s", suite, "-t", topcell or top_cell(Path(layout)), "--tile", str(tile), "-i", str(layout), "-r", str(report)]
    rc = subprocess.call(cmd)
    if not report.exists():
        raise SystemExit(f"gdscheck wrote no report (exit {rc})")
    with open(out / "rules.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule", "violations"])
        w.writerows(per_rule(report).items())
    return out


def per_rule(report: Path) -> dict[str, int]:
    """Violations per rule (category) of a KLayout marker database."""
    import klayout.rdb as krdb

    db = krdb.ReportDatabase("")
    db.load(str(report))
    counts = {}

    def walk(cats, prefix=""):
        for c in cats:
            name = prefix + c.name()
            subs = list(c.each_sub_category())
            if subs:
                walk(subs, name + ".")
            else:
                counts[name] = c.num_items()

    walk(list(db.each_category()))
    return counts
