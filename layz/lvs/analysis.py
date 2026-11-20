"""A `layz.lvs.run` folder: a table, printed and written as CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from layz.table import table


def findings(run: Path, *, out: Path | None) -> list[dict]:
    """Opens, shorts, unknown and floating labels (each must be none), and how much the labels
    cover: checked schematic nets and pins."""
    s = json.loads((run / "summary.json").read_text())
    rows = [{"check": k, "count": s[k], "pass": s[k] == 0} for k in ("open", "short", "unknown", "floating")]
    rows.append({"check": "schematic nets checked", "count": f"{s['checked nets']} of {s['schematic nets']}", "pass": s["checked nets"] > 0})
    rows.append({"check": "pins checked", "count": s["pins checked"], "pass": True})
    return table(f"LVS: {s['layout nets']} layout nets, {s['labels']} labels", rows, out)


def parity(run: Path, *, out: Path | None) -> list[dict]:
    """A board's schematic parity (layz.lvs.run.board): each kind of mismatch, and unconnected
    items; each must be none."""
    with open(run / "parity.csv") as f:
        found = list(csv.DictReader(f))
    kinds: dict[str, int] = {}
    for r in found:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    rows = [{"check": k, "count": n, "pass": False} for k, n in sorted(kinds.items())] or [{"check": "schematic parity", "count": 0, "pass": True}]
    return table(f"LVS (KiCad schematic parity): {len(found)} findings", rows, out)
