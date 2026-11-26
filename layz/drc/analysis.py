"""A `layz.drc.run` folder against limits: a table, printed and written as CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from layz.table import table


def violations(run: Path, *, max_violations: int, out: Path | None) -> list[dict]:
    """Violations per rule: passes with at most ``max_violations`` each."""
    with open(run / "rules.csv") as f:
        rows = [{"rule": r["rule"], "violations": int(r["violations"]), "pass": int(r["violations"]) <= max_violations} for r in csv.DictReader(f)]
    rows.sort(key=lambda r: -r["violations"])  # the violated first, then the rest in the deck's order
    total = sum(r["violations"] for r in rows)
    return table(f"DRC: {total} violations in {sum(1 for r in rows if r['violations'])} of {len(rows)} rules (limit {max_violations} per rule)", rows, out)
