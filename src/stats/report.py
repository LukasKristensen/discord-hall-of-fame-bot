"""Runs the whole export and writes the index that explains it.

An export folder is meant to be handed to someone else, so it ships a README
naming the question each figure answers. Without that, fourteen PNGs in a
timestamped folder are a puzzle rather than a report.
"""

from __future__ import annotations

import os
from datetime import datetime

from stats import charts, metrics, tables, theme

INDEX_FILENAME = "README.md"


def create_output_dir(root, reference_dt=None):
    """A timestamped folder under ``root``, created if missing."""
    stamp = (reference_dt or datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(root, stamp)
    os.makedirs(path, exist_ok=True)
    return path


def render(dataset, out_dir):
    """Export every table and chart, then the index. Returns the outputs."""
    theme.apply_style()

    print("Tables:")
    outputs = tables.render_all(out_dir, dataset)
    for output in outputs:
        print(f"  wrote {output.filename}")

    print("Charts:")
    outputs.extend(charts.render_all(out_dir, dataset))

    write_index(dataset, out_dir, outputs)
    return outputs


def write_index(dataset, out_dir, outputs):
    """Write the README that ships alongside the images."""
    kpis = metrics.headline_kpis(dataset)
    lines = [
        "# Hall of Fame server statistics",
        "",
        f"Generated **{dataset.now:%Y-%m-%d %H:%M} UTC** from the **{dataset.source}** dataset.",
        "",
        "## Headline numbers",
        "",
        "| Metric | Value | Note |",
        "| --- | ---: | --- |",
    ]
    for kpi in kpis:
        lines.append(f"| {kpi['label']} | {tables.format_kpi(kpi)} | {kpi['note']} |")

    lines += [
        "",
        "## Figures",
        "",
        "Each figure ships a CSV twin holding the numbers behind it, because a PNG "
        "cannot be inspected.",
        "",
        "| Figure | Answers | Data |",
        "| --- | --- | --- |",
    ]
    for output in outputs:
        csv_cell = f"[csv]({output.csv_filename})" if output.csv_filename else "-"
        lines.append(f"| [{output.title}]({output.filename}) | {output.question} | {csv_cell} |")

    lines += [
        "",
        "## Reading notes",
        "",
        "- **Activated** means the server has published at least one Hall of Fame post; "
        "**live** means it published one within the trailing "
        f"{metrics.LIVE_WINDOW_DAYS} days.",
        "- Per-server figures report medians rather than means. The fleet is heavy tailed, "
        "so a mean describes the largest handful of servers and nobody else.",
        "- No figure uses two y-axes. Where two measures of different scale belong together "
        "they are stacked as two panels over one shared x-axis.",
        "- Uninstalling deletes the guild's config row and its posts, so anything that "
        "needs to know what a departed server was like is not answerable from this data. "
        "That is why install survival is reported for the fleet as a whole rather than "
        "split by whether the server ever posted.",
        "- The most recent month is still in progress wherever it appears, so it is not "
        "comparable with the months before it.",
        "",
    ]

    path = os.path.join(out_dir, INDEX_FILENAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print(f"  wrote {INDEX_FILENAME}")
    return path
