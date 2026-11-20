"""Plots of a `layz.pex.run` folder, in layz.plotstyle."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

from layz.pex.analysis import matrix as read_matrix
from layz.plotstyle import DENSITY_COLOR_MAP, PLOT_STYLE, save_figure


@mpl.rc_context(PLOT_STYLE)
def matrix(run: Path, out: Path) -> list[Path]:
    """The capacitance matrix as a map: totals on the diagonal, mutuals off it (fF, log scale)."""
    names, C = read_matrix(run)
    M = np.abs(np.array(C))
    n = len(names)
    size = max(3.5, 0.45 * n + 1.5)
    fig, ax = plt.subplots(figsize=(size + 1.2, size))
    positive = M[M > 0]
    im = ax.imshow(np.where(M > 0, M, np.nan), cmap=DENSITY_COLOR_MAP, norm=LogNorm(vmin=positive.min(), vmax=positive.max()) if positive.size else None)
    fig.colorbar(im, ax=ax, label="capacitance (fF): total on the diagonal, mutual off it")
    ax.set_xticks(range(n), names, rotation=60, ha="right")
    ax.set_yticks(range(n), names)
    if n <= 16:
        for i in range(n):
            for j in range(n):
                ax.text(j, i, f"{M[i, j]:.3g}", ha="center", va="center", fontsize=6, color="white")
    ax.set_title(f"{run.name}: capacitance matrix")
    return list(save_figure(fig, out / "capacitance_matrix"))
