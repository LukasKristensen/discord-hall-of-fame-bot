"""Tables rendered as figures, plus the CSV twin of each one.

With hundreds of servers a lot of the interesting output is not a chart at all:
segment breakdowns, percentile summaries and league tables carry more per pixel
than any bar chart of 500 bars ever could. Tables are laid out in a monospace
face so columns line up without measuring glyphs.
"""

from __future__ import annotations

import os

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from stats import metrics, theme
from stats.theme import Output

# DejaVu Sans Mono advances 0.6 em per glyph, which makes column geometry exact
# rather than estimated.
MONO_ADVANCE = 0.6
COLUMN_GAP = 3  # characters


def fmt_int(value):
    return f"{value:,.0f}"


def fmt_pct(value, decimals=1):
    return f"{value:,.{decimals}f}%"


def fmt_float(value, decimals=1):
    return f"{value:,.{decimals}f}"


def render_table(out_dir, filename, title, subtitle, columns, rows, note="", fontsize=9.5):
    """Draw a table as a figure.

    ``columns`` is a list of ``(header, align)`` where align is ``"l"`` or
    ``"r"``; ``rows`` is a list of lists of preformatted strings.
    """
    headers = [header for header, _ in columns]
    aligns = [align for _, align in columns]
    widths = [
        max([len(header)] + [len(row[index]) for row in rows]) if rows else len(header)
        for index, header in enumerate(headers)
    ]
    total_chars = sum(widths) + COLUMN_GAP * (len(widths) - 1)

    char_inches = fontsize * MONO_ADVANCE / 72.0
    row_inches = fontsize * 2.0 / 72.0
    header_block = 1.0 if subtitle else 0.75
    footer_block = 0.32 if note else 0.12
    fig_width = total_chars * char_inches + 0.9
    fig_height = header_block + row_inches * (len(rows) + 1.6) + footer_block

    fig = plt.figure(figsize=(fig_width, fig_height))
    fig.text(0.5 / fig_width, 1 - 0.28 / fig_height, title,
             ha="left", va="top", fontsize=14, color=theme.INK, fontweight="600")
    if subtitle:
        fig.text(0.5 / fig_width, 1 - 0.58 / fig_height, subtitle,
                 ha="left", va="top", fontsize=9.5, color=theme.INK_SECONDARY)

    ax = fig.add_axes(
        [
            0.45 / fig_width,
            footer_block / fig_height,
            (fig_width - 0.9) / fig_width,
            (fig_height - header_block - footer_block) / fig_height,
        ]
    )
    ax.set_xlim(0, total_chars)
    ax.set_ylim(len(rows) + 0.6, -1.2)
    ax.axis("off")
    ax.set_facecolor(theme.SURFACE)

    starts = []
    cursor = 0
    for width in widths:
        starts.append(cursor)
        cursor += width + COLUMN_GAP

    def draw_row(values, y, color, weight="normal"):
        for index, value in enumerate(values):
            if aligns[index] == "r":
                x = starts[index] + widths[index]
                ha = "right"
            else:
                x = starts[index]
                ha = "left"
            ax.text(x, y, value, ha=ha, va="center", fontsize=fontsize,
                    family=theme.MONO_STACK, color=color, fontweight=weight)

    draw_row(headers, -0.7, theme.INK_SECONDARY, "600")
    ax.plot([0, total_chars], [-0.15, -0.15], color=theme.AXIS, linewidth=1.0)
    for index, row in enumerate(rows):
        draw_row(row, index + 0.45, theme.INK)
        ax.plot([0, total_chars], [index + 0.95, index + 0.95], color=theme.GRID, linewidth=0.7)

    if note:
        fig.text(0.5 / fig_width, 0.06 / fig_height, note,
                 ha="left", va="bottom", fontsize=8, color=theme.INK_MUTED)

    fig.savefig(os.path.join(out_dir, filename))
    plt.close(fig)


def render_kpi_board(out_dir, dataset):
    """The first page: nine headline numbers, three across.

    A single number is not a bar chart. Anything the reader should walk away
    remembering belongs here rather than being read off an axis.
    """
    kpis = metrics.headline_kpis(dataset)
    if not kpis:
        return None

    # Laid out in inches and converted to figure fractions once, so the three
    # lines of a card cannot drift apart from each other or from their rule.
    columns = 3
    rows = (len(kpis) + columns - 1) // columns
    header_inches = 1.05
    card_inches = 1.45
    fig_width = 12.0
    fig_height = header_inches + card_inches * rows + 0.2

    def y_at(inches_from_top):
        return 1.0 - inches_from_top / fig_height

    fig = plt.figure(figsize=(fig_width, fig_height))
    fig.text(0.02, y_at(0.30), "Hall of Fame fleet at a glance",
             ha="left", va="top", fontsize=17, color=theme.INK, fontweight="600")
    fig.text(0.02, y_at(0.66),
             f"Generated {dataset.now:%Y-%m-%d %H:%M} UTC from the {dataset.source} dataset",
             ha="left", va="top", fontsize=10, color=theme.INK_SECONDARY)

    card_width = 0.96 / columns
    for index, kpi in enumerate(kpis):
        row, column = divmod(index, columns)
        left = 0.02 + column * card_width
        card_top = header_inches + row * card_inches

        fig.text(left, y_at(card_top), kpi["label"].upper(), ha="left", va="top",
                 fontsize=8.5, color=theme.INK_MUTED, fontweight="600")
        # Hero figures use proportional digits, not tabular: equal-width digits
        # make a large standalone number look loose.
        fig.text(left, y_at(card_top + 0.24), format_kpi(kpi), ha="left", va="top",
                 fontsize=26, color=theme.INK, fontweight="600")
        fig.text(left, y_at(card_top + 0.84), kpi["note"], ha="left", va="top",
                 fontsize=9, color=theme.INK_SECONDARY)

        # The rule separates one card from the next, so the bottom row has none.
        if row < rows - 1:
            rule_y = y_at(card_top + 1.16)
            fig.add_artist(
                Line2D([left, left + card_width - 0.025], [rule_y, rule_y],
                       transform=fig.transFigure, color=theme.GRID, linewidth=0.8)
            )

    fig.savefig(os.path.join(out_dir, "00_summary.png"))
    plt.close(fig)

    theme.write_csv(
        out_dir, "00_summary.csv", ["metric", "value", "note"],
        [[kpi["label"], format_kpi(kpi), kpi["note"]] for kpi in kpis],
    )
    return Output("00_summary.png", "Fleet at a glance",
                  "What are the headline numbers right now?", "00_summary.csv")


def format_kpi(kpi):
    if kpi["format"] == "pct":
        return f"{kpi['value']:,.1f}%"
    if kpi["format"] == "float":
        return f"{kpi['value']:,.1f}"
    return f"{kpi['value']:,.0f}"


def render_size_segments(out_dir, dataset):
    """Where the servers, the members and the posts actually sit."""
    rows = metrics.size_segments(dataset.servers)
    header = [
        ("Server size", "l"), ("Servers", "r"), ("% of servers", "r"), ("Members", "r"),
        ("% of members", "r"), ("Posts", "r"), ("% of posts", "r"), ("Activated", "r"),
        ("Live 30d", "r"), ("Median posts", "r"), ("Posts / 1k", "r"), ("Median thresh.", "r"),
    ]
    body = [
        [
            row["segment"], fmt_int(row["servers"]), fmt_pct(row["share_of_servers"]),
            fmt_int(row["members"]), fmt_pct(row["share_of_members"]), fmt_int(row["posts"]),
            fmt_pct(row["share_of_posts"]), fmt_pct(row["activation_rate"]),
            fmt_pct(row["live_rate"]), fmt_float(row["median_posts"]),
            fmt_float(row["median_posts_per_1k"]), fmt_float(row["median_threshold"], 0),
        ]
        for row in rows
    ]
    render_table(
        out_dir, "01_size_segments.png",
        "The fleet by server size",
        "One row per size band. The share columns show how lopsided the fleet is; the median columns "
        "show what a typical server in that band looks like.",
        header, body,
        note="Activated = has published at least one post. Live 30d = posted within the trailing 30 days.",
    )
    theme.write_csv(out_dir, "01_size_segments.csv", [name for name, _ in header], body)
    return Output("01_size_segments.png", "The fleet by server size",
                  "Do small and large servers behave differently?", "01_size_segments.csv")


def render_distribution(out_dir, dataset):
    """Percentiles, because the mean of 500 heavy-tailed servers is a fiction."""
    rows = metrics.distribution_table(dataset.servers, dataset.now)
    header = [("Metric", "l"), ("n", "r"), ("p10", "r"), ("p25", "r"), ("median", "r"),
              ("p75", "r"), ("p90", "r"), ("p99", "r"), ("mean", "r")]
    body = [
        [
            row["metric"], fmt_int(row["n"]), fmt_float(row["p10"], 2), fmt_float(row["p25"], 2),
            fmt_float(row["p50"], 2), fmt_float(row["p75"], 2), fmt_float(row["p90"], 2),
            fmt_float(row["p99"], 2), fmt_float(row["mean"], 2),
        ]
        for row in rows
    ]
    render_table(
        out_dir, "02_distributions.png",
        "Distribution of every per-server metric",
        "Read the median column, not the mean. Where mean sits far above p90 the metric is "
        "dominated by a handful of servers.",
        header, body,
        note="Rows restricted to activated servers are labelled as such; days-to-first-post excludes servers that never posted.",
    )
    theme.write_csv(out_dir, "02_distributions.csv", [name for name, _ in header], body)
    return Output("02_distributions.png", "Distribution of per-server metrics",
                  "What does a typical server look like, and how long is the tail?", "02_distributions.csv")


def render_top_servers(out_dir, dataset, limit=25):
    """The league table the old per-guild bar charts were reaching for."""
    rows = metrics.top_servers(dataset.servers, dataset.now, limit)
    header = [("#", "r"), ("Guild ID", "l"), ("Members", "r"), ("Posts 30d", "r"),
              ("Posts total", "r"), ("Posts / 1k", "r"), ("Authors", "r"),
              ("Threshold", "r"), ("Months", "r")]
    body = [
        [
            str(row["rank"]), str(row["guild_id"]), fmt_int(row["members"]),
            fmt_int(row["posts_30d"]), fmt_int(row["posts_total"]),
            fmt_float(row["posts_per_1k"]), fmt_int(row["authors"]),
            fmt_int(row["threshold"]), fmt_float(row["months_installed"]),
        ]
        for row in rows
    ]
    render_table(
        out_dir, f"03_top_{limit}_servers.png",
        f"Top {limit} servers by posts in the last 30 days",
        "A ranked table beats a bar chart here: guild IDs carry no meaning on an axis, and 500 bars "
        "cannot be read at all.",
        header, body,
        note="Posts / 1k normalises lifetime posts by member count, so small active servers are not buried.",
    )
    theme.write_csv(out_dir, f"03_top_{limit}_servers.csv", [name for name, _ in header], body)
    return Output(f"03_top_{limit}_servers.png", f"Top {limit} servers",
                  "Which servers are carrying the fleet?", f"03_top_{limit}_servers.csv")


def render_config_adoption(out_dir, dataset):
    """Which settings people actually change, and whether it matters."""
    rows = metrics.config_adoption(dataset.servers)
    header = [("Setting", "l"), ("Servers on", "r"), ("% of servers", "r"), ("% of members", "r"),
              ("Activated when on", "r"), ("Activated when off", "r"), ("Difference", "r")]
    body = []
    for row in rows:
        difference = row["activation_on"] - row["activation_off"]
        body.append([
            row["setting"], fmt_int(row["servers_on"]), fmt_pct(row["share_of_servers"]),
            fmt_pct(row["share_of_members"]), fmt_pct(row["activation_on"]),
            fmt_pct(row["activation_off"]), f"{difference:+.1f}pp",
        ])

    methods = metrics.calculation_method_adoption(dataset.servers)
    for row in methods:
        body.append([
            f"Method: {row['method']}", fmt_int(row["servers"]), fmt_pct(row["share_of_servers"]),
            "-", fmt_pct(row["activation_rate"]), "-", "-",
        ])

    render_table(
        out_dir, "04_config_adoption.png",
        "Configuration adoption and its correlation with activation",
        "How many servers change each setting, weighted by servers and by members, and how activation "
        "differs between the servers that turn it on and those that do not.",
        header, body,
        note="The difference column is correlation, not causation: servers that configure more are also servers that engage more.",
    )
    theme.write_csv(out_dir, "04_config_adoption.csv", [name for name, _ in header], body)
    return Output("04_config_adoption.png", "Configuration adoption",
                  "Which settings do servers change, and does it go with activation?", "04_config_adoption.csv")


def render_all(out_dir, dataset):
    """Every table in the report, in reading order."""
    outputs = [
        render_kpi_board(out_dir, dataset),
        render_size_segments(out_dir, dataset),
        render_distribution(out_dir, dataset),
        render_top_servers(out_dir, dataset),
        render_config_adoption(out_dir, dataset),
    ]
    return [output for output in outputs if output]
