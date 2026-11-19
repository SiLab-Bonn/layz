"""Plot style copied from FRIDA (``flow/analysis/plots.py``): the Nord colours, Computer Modern
text, ticks inside on all four sides, the light major/minor grid and legend-styled info boxes.
Use it as FRIDA does for figures drawn directly with matplotlib:

    @mpl.rc_context(PLOT_STYLE)
    def plot_something(...):
        fig, ax = plt.subplots()
        ...
        style_grid(ax)
        return save_figure(fig, out / "name")      # a suffixless stem: writes .pdf (and .png)

Used by layz.hyperlynx.plots; any new layz plot should use it too.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from cycler import cycler
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.offsetbox import AnchoredOffsetbox, TextArea, VPacker
from matplotlib.ticker import AutoMinorLocator, NullLocator

PLOT_PNGS = True  # layz: also PNG, for quick previews
PLOT_SVGS = False
PLOT_PDFS = True
PNG_DPI = 500
INFO_BOX_FONT_SIZE = 7.0

# Nord presentation colors. The ordering gives all plots a stable semantic
# sequence instead of inheriting Matplotlib's version-dependent default cycle.
PLOT_FACE_COLOR = "white"
TEXT_COLOR = "black"
SPINE_COLOR = "#4C566A"
LEGEND_FACE_COLOR = "#ECEFF4"
GRID_MAJOR_COLOR = "#D8DEE9"
GRID_MINOR_COLOR = "#E5E9F0"
NORD_BLUE = "#5E81AC"
NORD_RED = "#BF616A"
NORD_GREEN = "#A3BE8C"
NORD_ORANGE = "#D08770"
NORD_PURPLE = "#B48EAD"
NORD_CYAN = "#88C0D0"
NORD_YELLOW = "#EBCB8B"
NORD_TEAL = "#8FBCBB"
NORD_LIGHT_BLUE = "#81A1C1"
NORD_DARK = "#4C566A"
# The scope's amplitude-spectral-density plots share this range in nV/√Hz (the
# ADC's input-referred code spectra are its spec, flow.adc.plots, on their own data).
SPECTRAL_DENSITY_LIMITS_NV = (1.0, 1.0e5)
# The per-decade RMS panels below them share this range in µV.
DECADE_RMS_LIMITS_UV = (0.1, 1.0e4)

CURVE_COLORS = (NORD_BLUE, NORD_ORANGE, NORD_GREEN, NORD_PURPLE, NORD_YELLOW, NORD_RED, NORD_CYAN, NORD_TEAL, NORD_LIGHT_BLUE, NORD_DARK)
SPECTRUM_COLOR_MAP = LinearSegmentedColormap.from_list("nord_blue_orange_yellow", (NORD_BLUE, NORD_ORANGE, NORD_YELLOW))
DENSITY_COLOR_MAP = LinearSegmentedColormap.from_list("nord_blue_red", (NORD_BLUE, NORD_RED))  # every gradient: low blue, high red
PLOT_STYLE = mpl.RcParams(
    {
        "text.usetex": False,
        "mathtext.fontset": "cm",
        "font.family": "serif",
        "font.serif": ["Computer Modern Roman", "DejaVu Serif"],
        "font.size": 10.0,
        "figure.figsize": (9.6, 5.4),
        "figure.constrained_layout.use": True,
        "axes.titlesize": 12.0,
        "axes.titlecolor": TEXT_COLOR,
        "axes.titleweight": "normal",
        "axes.labelsize": 10.0,
        "axes.labelcolor": TEXT_COLOR,
        "axes.edgecolor": SPINE_COLOR,
        "axes.linewidth": 0.8,
        "axes.facecolor": PLOT_FACE_COLOR,
        "axes.grid": False,
        "axes.prop_cycle": cycler(color=CURVE_COLORS),
        "xtick.color": TEXT_COLOR,
        "xtick.direction": "in",
        "xtick.labelsize": 10.0,
        "xtick.major.size": 2.5,
        "xtick.minor.size": 1.5,
        "xtick.top": True,
        "ytick.color": TEXT_COLOR,
        "ytick.direction": "in",
        "ytick.labelsize": 10.0,
        "ytick.major.size": 2.5,
        "ytick.minor.size": 1.5,
        "ytick.right": True,
        "text.color": TEXT_COLOR,
        "figure.facecolor": PLOT_FACE_COLOR,
        "figure.titlesize": 12.0,
        "figure.titleweight": "normal",
        "savefig.facecolor": PLOT_FACE_COLOR,
        "savefig.dpi": PNG_DPI,
        "savefig.bbox": None,
        "legend.loc": "best",
        "legend.frameon": True,
        "legend.fancybox": True,
        "legend.facecolor": LEGEND_FACE_COLOR,
        "legend.edgecolor": SPINE_COLOR,
        "legend.framealpha": 0.9,
        "legend.labelcolor": TEXT_COLOR,
        "legend.linewidth": 0.8,
        "legend.borderpad": 0.4,
        "legend.borderaxespad": 0.5,
        "legend.fontsize": 10.0,
        "legend.title_fontsize": 10.0,
        "lines.linewidth": 1.0,
        "lines.markersize": 4.0,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


def style_grid(ax: plt.Axes) -> None:
    """Apply the shared light grid."""

    # rcParams cannot give major and minor grid lines different appearances.
    # Retain explicitly selected minor-tick intervals, such as the 0.25 MSPS
    # measurement spacing. ``minorticks_on`` would replace them with an
    # AutoMinorLocator and produce misleading 0.20 MSPS tick marks.
    if isinstance(ax.xaxis.get_minor_locator(), NullLocator):
        ax.xaxis.set_minor_locator(AutoMinorLocator())
    if isinstance(ax.yaxis.get_minor_locator(), NullLocator):
        ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.set_axisbelow(True)
    ax.grid(True, which="major", color=GRID_MAJOR_COLOR, alpha=0.95, linewidth=0.8)
    ax.grid(True, which="minor", color=GRID_MINOR_COLOR, alpha=1.0, linewidth=0.5)


def style_info_box(ax: plt.Axes, lines: Sequence[str], *, location: str = "upper right", line_colors: Sequence[str] | None = None) -> None:
    """Add measurement setup using the same spacing and frame as a legend."""

    # Legend rcParams do not apply automatically to anchored offset boxes.
    if not lines:
        return
    if line_colors is not None and len(line_colors) != len(lines):
        raise ValueError("information-box line colors must match its lines")
    if line_colors is None:
        child = TextArea("\n".join(lines), textprops={"size": INFO_BOX_FONT_SIZE})
    else:
        child = VPacker(children=[TextArea(line, textprops={"color": color, "size": INFO_BOX_FONT_SIZE}) for line, color in zip(lines, line_colors, strict=True)], align="left", pad=0.0, sep=1.0)
    box = AnchoredOffsetbox(loc=location, child=child, frameon=True, pad=mpl.rcParams["legend.borderpad"], borderpad=mpl.rcParams["legend.borderaxespad"])
    box.patch.set_boxstyle(f"round,pad={mpl.rcParams['legend.borderpad']}")
    box.patch.set_facecolor(mpl.rcParams["legend.facecolor"])
    box.patch.set_edgecolor(mpl.rcParams["legend.edgecolor"])
    box.patch.set_alpha(mpl.rcParams["legend.framealpha"])
    box.patch.set_linewidth(mpl.rcParams["legend.linewidth"])
    ax.add_artist(box)


def style_time_units(time_s: np.ndarray) -> tuple[float, str]:
    # rcParams cannot choose a readable unit from the plotted data extent.
    maximum = float(np.nanmax(np.abs(time_s)))
    if maximum < 1e-9:
        return 1e12, "ps"
    if maximum < 1e-6:
        return 1e9, "ns"
    if maximum < 1e-3:
        return 1e6, "µs"
    if maximum < 1.0:
        return 1e3, "ms"
    return 1.0, "s"


def style_ratio_limits(*ratios: np.ndarray) -> tuple[float, float]:
    """An axis around 1 wide enough for every finite ratio, so the worst points stay in view."""
    finite = np.concatenate([np.asarray(ratio, dtype=np.float64) for ratio in ratios])
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 0.9, 1.1
    return min(0.9, float(np.min(finite)) - 0.05), max(1.1, float(np.max(finite)) + 0.05)


def save_figure(fig: plt.Figure, output_path: Path, *, pdf_metadata: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    output_path = Path(output_path)
    if output_path.suffix:
        raise ValueError("plot output_path must be a suffixless artifact stem")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    formats = tuple(output_format for output_format, enabled in (("png", PLOT_PNGS), ("svg", PLOT_SVGS), ("pdf", PLOT_PDFS)) if enabled)
    if not formats:
        raise RuntimeError("at least one plot output format must be enabled")
    # Preserve figures that explicitly disable automatic layout. Matplotlib can
    # otherwise install the rcParam-selected constrained-layout engine after the
    # first backend renders, causing later formats to move manually positioned
    # axes underneath legends and colorbars.
    with mpl.rc_context({"figure.constrained_layout.use": False}):
        for output_format in formats:
            path = output_path.with_suffix(f".{output_format}")
            if output_format == "pdf" and pdf_metadata is not None:
                fig.savefig(path, metadata=dict(pdf_metadata))
            else:
                fig.savefig(path)
            paths.append(path)
    plt.close(fig)
    return tuple(paths)
