"""Shared look and feel for every figure the report exports.

One place decides palette, chrome and layout so the exported folder reads as a
single report instead of fourteen unrelated matplotlib defaults.

Colour rules this module encodes, and why:

* Categorical hues are assigned in a fixed order and never cycled. Slots beyond
  the third are not colourblind separable against each other, so any chart that
  needs more than three colours folds its tail into "Other" instead.
* Magnitude uses one hue, light to dark. Never a rainbow.
* Polarity (servers gained vs servers lost) uses the warm/cool diverging pair.
* Status colours are reserved for good/bad and never stand in for "series 4".
* No chart uses two y-axes. Two measures of different scale become two stacked
  panels sharing one x-axis.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")  # The report is written to files; never open a GUI window.

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

# Chart chrome and ink.
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# Categorical slots, in assignment order. Only the first three are separable as
# an unordered set, which is why charts here never use more than three.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
SERIES_BLUE, SERIES_ORANGE, SERIES_AQUA = SERIES

# Polarity: warm against cool, with a neutral middle.
POSITIVE = "#2a78d6"
NEGATIVE = "#e34948"

# Status, reserved for good/bad readings only.
STATUS_GOOD = "#0ca30c"
STATUS_CRITICAL = "#d03b3b"

# Single hue ramp for magnitude. Light steps mean "near zero".
SEQUENTIAL_STEPS = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
# Ordinal marks must stay readable against the surface, so the ramp used for
# discrete ordered bars starts darker than the sequential one.
ORDINAL_STEPS = ("#86b6ef", "#5598e7", "#3987e5", "#256abf", "#184f95")

SEQUENTIAL_CMAP = LinearSegmentedColormap.from_list("hof_sequential", SEQUENTIAL_STEPS)

FONT_STACK = ["Segoe UI", "DejaVu Sans", "sans-serif"]
MONO_STACK = ["DejaVu Sans Mono", "Consolas", "monospace"]

DPI = 150


@dataclass
class Output:
    """One exported panel, plus the question it exists to answer.

    ``report.py`` turns these into the index that ships with the export, so a
    reader knows what they are looking at without opening every PNG.
    """

    filename: str
    title: str
    question: str
    csv_filename: str = ""


def apply_style():
    """Install the report's rcParams. Safe to call more than once."""
    # DejaVu Sans, the bundled fallback, has no semibold. Weight 600 is what the
    # headings want where a UI sans is installed; where it is not, matplotlib
    # substitutes bold and says so once per figure. The substitution is correct,
    # so the running commentary is just noise on a report that writes 16 files.
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

    plt.rcParams.update(
        {
            "figure.facecolor": PAGE,
            "figure.dpi": DPI,
            "savefig.facecolor": PAGE,
            "savefig.dpi": DPI,
            "savefig.bbox": "tight",
            "axes.facecolor": SURFACE,
            "axes.edgecolor": AXIS,
            "axes.linewidth": 0.8,
            "axes.labelcolor": INK_SECONDARY,
            "axes.labelsize": 9.5,
            "axes.titlesize": 11,
            "axes.titlecolor": INK,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "grid.linestyle": "-",  # Dashes read as "projection"; a grid is not one.
            "xtick.color": INK_MUTED,
            "ytick.color": INK_MUTED,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "font.family": "sans-serif",
            "font.sans-serif": FONT_STACK,
            "font.size": 9.5,
            "text.color": INK,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "legend.labelcolor": INK_SECONDARY,
            "lines.linewidth": 2.0,
            "lines.markersize": 5,
            "patch.linewidth": 0,
        }
    )


def new_figure(title, subtitle="", figsize=(11, 6), panels=1, height_ratios=None, sharex=False):
    """A titled figure with recessive chrome and room reserved for the header.

    Returns ``(fig, axes)`` where ``axes`` is a single axis for ``panels == 1``
    and a list otherwise.
    """
    fig, axes = plt.subplots(
        panels,
        1,
        figsize=figsize,
        sharex=sharex,
        gridspec_kw={"height_ratios": height_ratios} if height_ratios else None,
    )
    axes_list = list(axes) if panels > 1 else [axes]
    for ax in axes_list:
        _strip_spines(ax)

    top = 1 - (0.5 / figsize[1])
    fig.text(0.01, top, title, ha="left", va="top", fontsize=14, color=INK, fontweight="600")
    if subtitle:
        fig.text(
            0.01,
            top - (0.32 / figsize[1]),
            subtitle,
            ha="left",
            va="top",
            fontsize=9.5,
            color=INK_SECONDARY,
        )
    return fig, (axes_list if panels > 1 else axes_list[0])


def _strip_spines(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)


def footer(fig, note):
    """A muted source/caveat line under the plot."""
    if note:
        fig.text(0.01, 0.005, note, ha="left", va="bottom", fontsize=8, color=INK_MUTED)


def finish(fig, out_dir, filename, note="", header_inches=0.95):
    """Reserve space for the header, save the figure and close it."""
    height = fig.get_size_inches()[1]
    fig.tight_layout(rect=(0, 0.03 if note else 0.0, 1, 1 - header_inches / height))
    path = os.path.join(out_dir, filename)
    footer(fig, note)
    fig.savefig(path)
    plt.close(fig)
    return path


def write_csv(out_dir, filename, header, rows):
    """Write the table twin of a chart.

    Every figure ships one: a PNG cannot be hovered, so the numbers behind it
    have to be readable somewhere that is not the picture.
    """
    path = os.path.join(out_dir, filename)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def sequential_color(fraction):
    """A step from the single-hue magnitude ramp, ``fraction`` in ``[0, 1]``."""
    return SEQUENTIAL_CMAP(max(0.0, min(1.0, fraction)))


def ordinal_color(index, total):
    """A step from the ordinal ramp for discrete ordered marks (funnel stages)."""
    if total <= 1:
        return ORDINAL_STEPS[0]
    position = index / (total - 1) * (len(ORDINAL_STEPS) - 1)
    return ORDINAL_STEPS[int(round(position))]


def compact(value, decimals=0):
    """Axis and label friendly number: 12_400 becomes ``12.4k``."""
    number = float(value or 0)
    for limit, suffix in ((1_000_000_000, "b"), (1_000_000, "m"), (1_000, "k")):
        if abs(number) >= limit:
            scaled = number / limit
            return f"{scaled:.1f}{suffix}".replace(".0", "")
    if decimals:
        return f"{number:,.{decimals}f}"
    return f"{number:,.0f}"


def label_bars(ax, bars, values, formatter=None, color=INK_SECONDARY, offset=3, fontsize=8.5):
    """Direct-label a small set of bars.

    Used selectively: on charts with few bars, where the number is the point.
    Dense charts leave the values to the axis and the CSV twin.
    """
    formatter = formatter or (lambda v: compact(v))
    for bar, value in zip(bars, values):
        ax.annotate(
            formatter(value),
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, offset if bar.get_height() >= 0 else -offset - 6),
            textcoords="offset points",
            ha="center",
            va="bottom" if bar.get_height() >= 0 else "top",
            fontsize=fontsize,
            color=color,
        )


def month_ticks(ax, months, max_labels=18):
    """Thin month labels so a three year x-axis stays readable."""
    if not months:
        return
    step = max(1, len(months) // max_labels)
    positions = list(range(0, len(months), step))
    ax.set_xticks(positions)
    ax.set_xticklabels([months[i].strftime("%Y-%m") for i in positions], rotation=45, ha="right")
