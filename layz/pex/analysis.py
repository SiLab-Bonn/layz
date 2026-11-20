"""A `layz.pex.run` folder against limits: tables, printed and written as CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from layz.table import table


def matrix(run: Path) -> tuple[list[str], list[list[float]]]:
    """The Maxwell capacitance matrix of a run: conductor names and rows, in fF."""
    with open(run / "maxwell_matrix_fF.csv") as f:
        rows = list(csv.reader(f))
    return rows[0][1:], [[float(v) for v in r[1:]] for r in rows[1:]]


def coupling(run: Path, *, max_coupling_fF: float, out: Path | None) -> list[dict]:
    """Each pair's mutual capacitance, and as a share of each one's total (its crosstalk ratio):
    passes when at most ``max_coupling_fF``."""
    names, C = matrix(run)
    rows = []
    for i, a in enumerate(names):
        for j in range(i + 1, len(names)):
            c = -C[i][j]
            rows.append({"a": a, "b": names[j], "mutual_fF": c, "of_a_total": c / C[i][i] if C[i][i] else 0.0, "of_b_total": c / C[j][j] if C[j][j] else 0.0, "pass": c <= max_coupling_fF})
    rows.sort(key=lambda r: -r["mutual_fF"])
    return table(f"mutual capacitance (limit {max_coupling_fF:g} fF)", rows, out)


def totals(run: Path, *, out: Path | None) -> list[dict]:
    """Each conductor's total capacitance and the part of it to infinity (to no other conductor)."""
    names, C = matrix(run)
    rows = [{"conductor": n, "total_fF": C[i][i], "to_infinity_fF": sum(C[i])} for i, n in enumerate(names)]
    return table("capacitance per conductor", rows, out)
