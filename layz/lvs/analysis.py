"""A `layz.lvs.run` folder: a table, printed and written as CSV."""

from __future__ import annotations

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
