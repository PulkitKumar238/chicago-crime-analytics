"""Shared chart styling so every use-case figure looks like one deck."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import seaborn as sns  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

NAVY = "#12263F"
ACCENT = "#2A6F97"
WARM = "#C1452B"
GRID = "#DCE3EA"

SEQUENTIAL = "crest"
DIVERGING = "vlag"
CATEGORY = ["#2A6F97", "#468FAF", "#61A5C2", "#89C2D9", "#A9D6E5",
            "#C1452B", "#E07A5F", "#F2CC8F", "#81B29A", "#3D5A80"]


def setup_style() -> None:
    sns.set_theme(style="whitegrid")
    plt.rcParams.update({
        "figure.dpi": config.FIG_DPI,
        "savefig.dpi": config.FIG_DPI,
        "savefig.bbox": "tight",
        "font.family": "DejaVu Sans",
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlecolor": NAVY,
        "axes.labelsize": 10,
        "axes.labelcolor": "#33475B",
        "axes.edgecolor": GRID,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.7,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.color": "#5A6B7C",
        "ytick.color": "#5A6B7C",
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })


def save(fig, name: str, outdir: Path | None = None) -> Path:
    """Save a figure into usecases/figures and return its path."""
    outdir = Path(outdir or config.FIGURES_DIR)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def annotate_bars(ax, fmt="{:,.0f}", horizontal=False, pad=3, fontsize=8):
    """Put value labels on a bar chart."""
    for container in ax.containers:
        ax.bar_label(container, fmt=lambda v: fmt.format(v), padding=pad,
                     fontsize=fontsize, color="#33475B")
    if horizontal:
        ax.margins(x=0.12)
    else:
        ax.margins(y=0.12)
