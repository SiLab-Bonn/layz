"""The tables of every analysis (layz.*.analysis): printed, and written as CSV."""

from __future__ import annotations

import csv
from pathlib import Path


def table(title: str, rows: list[dict], out: Path | None) -> list[dict]:
    if not rows:
        return rows
    keys = list(rows[0])
    fmt = lambda v: f"{v:.4g}" if isinstance(v, float) else str(v)
    width = {k: max(len(k), *(len(fmt(r[k])) for r in rows)) for k in keys}
    print(title)
    print("  " + "  ".join(k.ljust(width[k]) for k in keys))
    for r in rows:
        print("  " + "  ".join(fmt(r[k]).ljust(width[k]) for k in keys))
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, keys)
            w.writeheader()
            w.writerows(rows)
    return rows
