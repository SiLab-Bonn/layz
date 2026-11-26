"""Design rule check for a flow's targets (layz.flow): gdscheck with the kit's deck, every option
given, into one folder.

    from layz.drc import analysis, run

    checked = run.drc(GDS, RESULTS / "drc", kit="uni-bonn-rdl", suite="main", topcell=None, tile=20000.0)
    analysis.violations(checked, max_violations=0, out=checked / "violations.csv")

Writes drc.lyrdb (KLayout markers: `klayout GDS -m drc.lyrdb`), rules.csv (violations per
rule) and job.json. A PCB is checked by KiCad itself, against the rules in its own board:

    checked = run.board(PCB, RESULTS / "drc", refill_zones=True, all_track_errors=False)

which writes drc.json (KiCad's report: open the board in KiCad to see the markers) and the same
rules.csv, so analysis.violations reads both.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from layz import log


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
    rc = log.run("gdscheck", cmd)
    if not report.exists():
        raise SystemExit(f"gdscheck wrote no report (exit {rc})")
    with open(out / "rules.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule", "violations"])
        w.writerows({**dict.fromkeys(suite_rules(kit, suite), 0), **per_rule(report)}.items())  # every rule, passing ones with 0
    (out / "markers.json").write_text(json.dumps({"on": "layout", "boxes": markers(report)}))
    return out


def markers(report: Path) -> list[dict]:
    """Each violation of a KLayout marker database as a box (mm, the layout's coordinates), with
    its rule and message: for the viewer to mark on the layout."""
    import klayout.db  # noqa: F401  (binds the geometry types the values return)
    import klayout.rdb as krdb

    db = krdb.ReportDatabase("")
    db.load(str(report))
    found = []
    for item in db.each_item():
        rule = db.category_by_id(item.category_id()).path()
        box, text = None, ""
        for v in item.each_value():
            shape = v.box() if v.is_box() else v.polygon().bbox() if v.is_polygon() else v.edge().bbox() if v.is_edge() else v.edge_pair().bbox() if v.is_edge_pair() else v.path().bbox() if v.is_path() else None
            if shape is not None:
                box = shape if box is None else box + shape
            elif v.is_string():
                text = v.string()
        if box is not None:
            found.append({"rule": rule, "what": text, "box": [box.left / 1000, box.bottom / 1000, box.right / 1000, box.top / 1000]})
    return found


def suite_rules(kit: str, suite: str) -> list[str]:
    """Every rule id a kit's suite checks (its decks' rules), in the decks' order."""
    import yaml

    from layz.drc.check import DRC_DIR

    ids = []
    for inc in yaml.safe_load((DRC_DIR / kit / "suites" / f"{suite}.yml").read_text()).get("include", []):
        deck = DRC_DIR / kit / "decks" / f"{inc['deck']}.yml"
        ids += [r["id"] for r in (yaml.safe_load(deck.read_text()) or {}).get("rules", []) if "id" in r]
    return ids


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


def board(pcb: Path, out: Path, *, refill_zones: bool, all_track_errors: bool) -> Path:
    """KiCad's DRC of ``pcb`` (kicad-cli pcb drc), with the board's own rules; every severity.

    refill_zones      fill the zones first (else the fills as saved)
    all_track_errors  every error of each track (else KiCad's first)
    """
    from layz import kicad

    cli = kicad.cli()
    if not cli:
        raise SystemExit("kicad-cli not found: run install/kicad.sh")
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps({"board": str(pcb), "refill_zones": refill_zones, "all_track_errors": all_track_errors}, indent=1))
    report = out / "drc.json"
    cmd = [cli, "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "-o", str(report), *(["--refill-zones"] if refill_zones else []), *(["--all-track-errors"] if all_track_errors else []), str(pcb)]
    if log.run("kicad-cli", cmd):
        raise SystemExit("kicad-cli pcb drc failed")
    d = json.loads(report.read_text())
    counts: dict[str, int] = {}
    for v in d["violations"]:
        key = f"{v['severity']}: {v['type']}"
        counts[key] = counts.get(key, 0) + 1
    counts["unconnected items"] = len(d["unconnected_items"])
    boxes = []  # on the board's .hyp coordinates (mm, Y up: KiCad's Y negated)
    for v in d["violations"] + [dict(u, type="unconnected items") for u in d["unconnected_items"]]:
        for i in v.get("items", [])[:1]:
            x, y = i["pos"]["x"], -i["pos"]["y"]
            boxes.append({"rule": f"{v.get('severity', 'error')}: {v['type']}" if v["type"] != "unconnected items" else v["type"], "what": v.get("description", ""), "box": [x - 0.05, y - 0.05, x + 0.05, y + 0.05]})
    (out / "markers.json").write_text(json.dumps({"on": "board", "boxes": boxes}))
    with open(out / "rules.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule", "violations"])
        w.writerows(sorted(counts.items()))
    return out
