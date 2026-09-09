"""The report's figures.

Every chart here is chosen for a fleet of hundreds of servers. The charts it
replaces plotted one bar per guild against a guild-ID axis, which stopped being
readable somewhere around thirty servers and stopped being informative long
before that. The replacements answer questions that scale: how lopsided is the
fleet, where do the posts come from, who sticks around, and what do servers do
after they install.

Two conventions hold throughout:

* No figure uses two y-axes. Two measures of different scale become two stacked
  panels sharing one x-axis, so no accidental correlation is invented.
* Every figure writes a CSV twin. A PNG has no tooltip, so the numbers behind a
  dense chart have to be legible somewhere else.
"""

from __future__ import annotations

import os

import numpy as np

from stats import metrics, theme
from stats.theme import Output

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def render_size_distribution(out_dir, dataset):
    """Server count and member mass, both against a log size axis.

    Split into two panels rather than one dual-axis chart because the point is
    the contradiction between them: most servers are small, most members are not.
    """
    member_counts = [s.member_count or 0 for s in dataset.servers]
    edges, counts = metrics.log_histogram(member_counts, bins_per_decade=3)
    member_mass = metrics.bin_by_edges([(value, value) for value in member_counts], edges)
    total_members = sum(member_counts) or 1
    member_share = [value / total_members * 100 for value in member_mass]

    median = metrics.percentile(member_counts, 50)
    p90 = metrics.percentile(member_counts, 90)

    fig, (ax_top, ax_bottom) = theme.new_figure(
        "How big are the servers, and where do the members sit?",
        f"{len(dataset.servers):,} servers, {total_members:,} members. "
        f"Median server {median:,.0f} members, p90 {p90:,.0f}.",
        figsize=(11, 7.4), panels=2, sharex=True,
    )

    # Bars are drawn against log10 positions rather than on a log axis: on a log
    # axis a constant fractional width collapses the gap between the leftmost
    # bars and exaggerates it on the right.
    log_edges = np.log10(np.array(edges))
    lefts = log_edges[:-1]
    widths = np.diff(log_edges) * 0.86

    ax_top.bar(lefts, counts, width=widths, align="edge", color=theme.SERIES_BLUE)
    ax_top.set_ylabel("Servers")
    ax_top.set_title("Servers per size band", loc="left", fontsize=10.5, color=theme.INK_SECONDARY, pad=8)
    # Headroom so the median marker's label does not sit on top of a bar.
    ax_top.set_ylim(top=max(counts) * 1.16)

    ax_bottom.bar(lefts, member_share, width=widths, align="edge", color=theme.SERIES_ORANGE)
    ax_bottom.set_ylabel("% of all members")
    ax_bottom.set_xlabel("Members in server (log scale)")
    ax_bottom.set_title("Share of the member base held by each size band", loc="left",
                        fontsize=10.5, color=theme.INK_SECONDARY, pad=8)

    decades = range(int(np.floor(log_edges[0])), int(np.ceil(log_edges[-1])) + 1)
    for ax in (ax_top, ax_bottom):
        ax.grid(axis="x", visible=False)
        ax.set_xticks(list(decades))
        ax.set_xticklabels([theme.compact(10 ** decade) for decade in decades])
        ax.axvline(np.log10(median), color=theme.INK_MUTED, linewidth=1.0)
    ax_top.annotate("median server", xy=(np.log10(median), 1), xycoords=("data", "axes fraction"),
                    xytext=(5, -4), textcoords="offset points", fontsize=8.5,
                    color=theme.INK_MUTED, va="top")

    theme.finish(fig, out_dir, "10_server_size_distribution.png",
                 note="Log-spaced bins; three bins per decade. Bars are counts, not densities.")
    theme.write_csv(
        out_dir, "10_server_size_distribution.csv",
        ["bin_low_members", "bin_high_members", "servers", "members_in_bin", "share_of_members_pct"],
        [
            [f"{edges[i]:.0f}", f"{edges[i + 1]:.0f}", counts[i], f"{member_mass[i]:.0f}", f"{member_share[i]:.2f}"]
            for i in range(len(counts))
        ],
    )
    return Output("10_server_size_distribution.png", "Server size distribution",
                  "Is the fleet made of many small servers or a few large ones?",
                  "10_server_size_distribution.csv")


def render_concentration(out_dir, dataset):
    """Lorenz curves for posts and members.

    The single most useful chart once there are hundreds of servers: it says in
    one line how much of the product's output comes from how few servers.
    """
    posts = [s.total_posts for s in dataset.servers]
    members = [s.member_count or 0 for s in dataset.servers]

    post_pop, post_cum = metrics.lorenz_curve(posts)
    member_pop, member_cum = metrics.lorenz_curve(members)

    top1 = metrics.top_share(posts, 0.01)
    top5 = metrics.top_share(posts, 0.05)
    top10 = metrics.top_share(posts, 0.10)

    fig, ax = theme.new_figure(
        "How concentrated is Hall of Fame activity?",
        f"Top 1% of servers produce {top1:.0f}% of all posts, top 5% produce {top5:.0f}%, "
        f"top 10% produce {top10:.0f}%. Gini {metrics.gini(posts):.2f}.",
        figsize=(9.5, 6.4),
    )

    ax.plot([0, 100], [0, 100], color=theme.INK_MUTED, linewidth=1.2, label="Perfectly even")
    ax.plot(post_pop, post_cum, color=theme.SERIES_BLUE, label="Hall of Fame posts")
    ax.plot(member_pop, member_cum, color=theme.SERIES_ORANGE, label="Members")

    ax.set_xlabel("Cumulative share of servers, smallest first (%)")
    ax.set_ylabel("Cumulative share of total (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.legend(loc="upper left")

    # One direct label rather than a number on every point: the 90th percentile
    # of servers is where the curve's message lives.
    marker = min(range(len(post_pop)), key=lambda i: abs(post_pop[i] - 90))
    ax.plot(post_pop[marker], post_cum[marker], "o", color=theme.SERIES_BLUE,
            markersize=7, markeredgecolor=theme.SURFACE, markeredgewidth=2)
    ax.annotate(
        f"the smallest 90% of servers\naccount for {post_cum[marker]:.0f}% of posts",
        xy=(post_pop[marker], post_cum[marker]), xytext=(-16, 26), textcoords="offset points",
        ha="right", va="bottom", fontsize=9, color=theme.INK_SECONDARY,
    )

    theme.finish(fig, out_dir, "11_activity_concentration.png",
                 note="A curve hugging the bottom-right means a few servers carry almost everything.")
    theme.write_csv(
        out_dir, "11_activity_concentration.csv",
        ["top_fraction", "share_of_posts_pct", "share_of_members_pct"],
        [
            [f"top {int(fraction * 100)}%", f"{metrics.top_share(posts, fraction):.2f}",
             f"{metrics.top_share(members, fraction):.2f}"]
            for fraction in (0.01, 0.05, 0.10, 0.25, 0.50)
        ],
    )
    return Output("11_activity_concentration.png", "Activity concentration",
                  "How few servers produce most of the posts?", "11_activity_concentration.csv")


def render_growth_and_churn(out_dir, dataset):
    """Monthly installs against uninstalls, and the installed base they produce."""
    rows = metrics.lifecycle_by_month(dataset.lifespans, dataset.now)
    if not rows:
        return None

    months = [row["month"] for row in rows]
    joined = [row["joined"] for row in rows]
    left = [-row["left"] for row in rows]
    installed = [row["installed"] for row in rows]
    recent_churn = metrics.mean([row["churn_rate"] for row in rows[-6:]])

    fig, (ax_top, ax_bottom) = theme.new_figure(
        "Installs, uninstalls and the installed base",
        f"{installed[-1]:,} servers installed at the end of {months[-1]:%B %Y}. "
        f"Average monthly churn over the last six months: {recent_churn:.1f}%.",
        figsize=(12, 7.6), panels=2, sharex=True, height_ratios=[1.15, 1],
    )

    x = np.arange(len(months))
    ax_top.bar(x, joined, width=0.72, color=theme.POSITIVE, label="Servers joined")
    ax_top.bar(x, left, width=0.72, color=theme.NEGATIVE, label="Servers left")
    ax_top.axhline(0, color=theme.AXIS, linewidth=1.0)
    ax_top.set_ylabel("Servers per month")
    ax_top.legend(loc="upper left", ncols=2)
    ax_top.grid(axis="x", visible=False)

    ax_bottom.plot(x, installed, color=theme.SERIES_BLUE)
    ax_bottom.fill_between(x, installed, color=theme.SERIES_BLUE, alpha=0.10)
    ax_bottom.set_ylabel("Servers installed")
    ax_bottom.set_xlabel("Month")
    ax_bottom.grid(axis="x", visible=False)
    ax_bottom.annotate(
        f"{installed[-1]:,}", xy=(x[-1], installed[-1]), xytext=(-4, 8),
        textcoords="offset points", ha="right", fontsize=10,
        color=theme.SERIES_BLUE, fontweight="600",
    )

    theme.month_ticks(ax_bottom, months)
    theme.finish(fig, out_dir, "12_growth_and_churn.png",
                 note="Uninstalls are drawn below the axis so gross growth and gross loss stay separable. "
                      "The final month is still in progress, so its bars are partial.")
    theme.write_csv(
        out_dir, "12_growth_and_churn.csv",
        ["month", "joined", "left", "net", "installed_end_of_month", "churn_rate_pct"],
        [[f"{row['month']:%Y-%m}", row["joined"], row["left"], row["net"], row["installed"],
          f"{row['churn_rate']:.2f}"] for row in rows],
    )
    return Output("12_growth_and_churn.png", "Growth and churn",
                  "Is the fleet still growing, and how much of it leaks away?",
                  "12_growth_and_churn.csv")


def render_cohort_retention(out_dir, dataset, cohort_limit=18):
    """Retention heatmap: each row a join cohort, each column a month of age."""
    cohort_data = metrics.cohort_retention(dataset.lifespans, dataset.now, max_months=12)
    cohorts = cohort_data["cohorts"][-cohort_limit:]
    if not cohorts:
        return None
    sizes = cohort_data["sizes"][-cohort_limit:]
    matrix = cohort_data["matrix"][-cohort_limit:]

    grid = np.array([[np.nan if value is None else value for value in row] for row in matrix], dtype=float)

    fig, ax = theme.new_figure(
        "Do servers that install stay installed?",
        "Share of each month's new servers still installed N months later. Blank cells have not happened yet.",
        figsize=(11.5, 0.9 + 0.38 * len(cohorts) + 1.6),
    )
    ax.grid(False)

    image = ax.imshow(grid, cmap=theme.SEQUENTIAL_CMAP, vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(grid.shape[1]))
    ax.set_xticklabels([f"M{index}" for index in range(grid.shape[1])])
    ax.set_yticks(range(len(cohorts)))
    ax.set_yticklabels([f"{cohort:%Y-%m}  (n={size})" for cohort, size in zip(cohorts, sizes)],
                       fontfamily=theme.MONO_STACK)
    ax.set_xlabel("Months since install")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for row_index in range(grid.shape[0]):
        for column_index in range(grid.shape[1]):
            value = grid[row_index, column_index]
            if np.isnan(value):
                continue
            ax.text(column_index, row_index, f"{value:.0f}", ha="center", va="center", fontsize=7.5,
                    color=theme.SURFACE if value > 62 else theme.INK)

    bar = fig.colorbar(image, ax=ax, pad=0.015, fraction=0.03, shrink=0.62)
    bar.set_label("% still installed", color=theme.INK_SECONDARY, fontsize=9)
    bar.outline.set_visible(False)
    bar.ax.tick_params(labelsize=8, color=theme.AXIS, labelcolor=theme.INK_MUTED, length=0)

    theme.finish(fig, out_dir, "13_cohort_retention.png",
                 note="M0 is the install month itself, so it is 100% by construction.")
    theme.write_csv(
        out_dir, "13_cohort_retention.csv",
        ["cohort", "cohort_size"] + [f"m{index}" for index in range(grid.shape[1])],
        [
            [f"{cohort:%Y-%m}", size] + ["" if value is None else f"{value:.1f}" for value in row]
            for cohort, size, row in zip(cohorts, sizes, matrix)
        ],
    )
    return Output("13_cohort_retention.png", "Cohort retention",
                  "Are newer cohorts sticking around better than older ones?",
                  "13_cohort_retention.csv")


def render_activation_funnel(out_dir, dataset):
    """Install to habit, one bar per stage."""
    rows = metrics.activation_funnel(dataset.servers)
    labels = [row["stage"] for row in rows]
    values = [row["servers"] for row in rows]

    biggest_drop = max(rows[1:], key=lambda row: 100.0 - row["step_conversion"])
    fig, ax = theme.new_figure(
        "From install to habit",
        f"{rows[-1]['share_of_installs']:.0f}% of installed servers have both posted recently and "
        f"built up ten posts. The steepest drop is \"{biggest_drop['stage']}\", which keeps only "
        f"{biggest_drop['step_conversion']:.0f}% of the stage above it.",
        figsize=(10.5, 5.6),
    )

    positions = np.arange(len(rows))
    colors = [theme.ordinal_color(index, len(rows)) for index in range(len(rows))]
    ax.barh(positions, values, height=0.62, color=colors)
    ax.set_yticks(positions)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Servers")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(values) * 1.22 if values else 1)

    for position, row in zip(positions, rows):
        drop = "" if position == 0 else f"   ({row['step_conversion']:.0f}% of the step above)"
        ax.annotate(
            f"{row['servers']:,}  ·  {row['share_of_installs']:.0f}% of installs{drop}",
            xy=(row["servers"], position), xytext=(8, 0), textcoords="offset points",
            va="center", fontsize=9, color=theme.INK_SECONDARY,
        )

    theme.finish(fig, out_dir, "14_activation_funnel.png",
                 note="Each stage narrows the previous stage's set, so the stages are genuinely nested. "
                      "The ramp is ordered, not categorical: darker means further down the funnel.")
    theme.write_csv(
        out_dir, "14_activation_funnel.csv",
        ["stage", "servers", "share_of_installs_pct", "step_conversion_pct"],
        [[row["stage"], row["servers"], f"{row['share_of_installs']:.2f}",
          f"{row['step_conversion']:.2f}"] for row in rows],
    )
    return Output("14_activation_funnel.png", "Activation funnel",
                  "Where do servers fall out between installing and posting regularly?",
                  "14_activation_funnel.csv")


def render_size_vs_activity(out_dir, dataset):
    """Density, not dots.

    A scatter of 500 servers over four orders of magnitude is a smear. Binning
    into hexagons shows where the mass is, and a median line per size decile
    shows the relationship the smear was hiding.
    """
    points = [
        (server.member_count, server.posts_per_day(dataset.now))
        for server in dataset.servers
        if server.is_activated and server.member_count and server.posts_per_day(dataset.now)
    ]
    if len(points) < 10:
        return None

    members = np.array([point[0] for point in points], dtype=float)
    rate = np.array([point[1] for point in points], dtype=float)

    fig, ax = theme.new_figure(
        "Does a bigger server mean a busier Hall of Fame?",
        f"{len(points):,} activated servers. Both axes are log scaled; colour is how many servers "
        "fall in each cell.",
        figsize=(10.5, 6.6),
    )

    hexes = ax.hexbin(members, rate, xscale="log", yscale="log", gridsize=26,
                      cmap=theme.SEQUENTIAL_CMAP, mincnt=1, linewidths=0.2, edgecolors=theme.SURFACE)

    # Median posting rate per size decile: the trend the density map implies.
    order = np.argsort(members)
    deciles = np.array_split(order, 10)
    decile_x = [float(np.median(members[chunk])) for chunk in deciles if len(chunk)]
    decile_y = [float(np.median(rate[chunk])) for chunk in deciles if len(chunk)]
    ax.plot(decile_x, decile_y, color=theme.SERIES_ORANGE, marker="o", markersize=6,
            markeredgecolor=theme.SURFACE, markeredgewidth=1.5, label="Median per size decile")

    ax.set_xlabel("Members in server")
    ax.set_ylabel("Hall of Fame posts per day")
    ax.legend(loc="upper left")

    bar = fig.colorbar(hexes, ax=ax, pad=0.015, fraction=0.035, shrink=0.72)
    bar.set_label("Servers per cell", color=theme.INK_SECONDARY, fontsize=9)
    bar.outline.set_visible(False)
    bar.ax.tick_params(labelsize=8, color=theme.AXIS, labelcolor=theme.INK_MUTED, length=0)

    theme.finish(fig, out_dir, "15_size_vs_activity.png",
                 note="Posts per day is lifetime posts over days installed, so old and new servers compare fairly.")
    theme.write_csv(
        out_dir, "15_size_vs_activity.csv",
        ["size_decile", "median_members", "median_posts_per_day"],
        [[index + 1, f"{x:.0f}", f"{y:.3f}"] for index, (x, y) in enumerate(zip(decile_x, decile_y))],
    )
    return Output("15_size_vs_activity.png", "Server size vs activity",
                  "Does server size predict how much gets celebrated?", "15_size_vs_activity.csv")


def render_monthly_posts(out_dir, dataset):
    """Fleet output above, per-server output below.

    Total posts keep rising simply because servers keep being added, so the
    second panel reports the median active server instead. If the top panel
    climbs while the bottom one is flat, growth is coming from new installs
    rather than from deeper engagement.
    """
    rows = metrics.monthly_post_summary(dataset.monthly_guild_posts)
    if not rows:
        return None

    months = [row["month"] for row in rows]
    x = np.arange(len(months))
    totals = [row["posts"] for row in rows]
    median = [row["median_per_server"] for row in rows]
    p25 = [row["p25_per_server"] for row in rows]
    p75 = [row["p75_per_server"] for row in rows]

    fig, (ax_top, ax_bottom) = theme.new_figure(
        "Hall of Fame output per month",
        f"{totals[-1]:,} posts across {rows[-1]['active_servers']:,} active servers in "
        f"{months[-1]:%B %Y}.",
        figsize=(12, 7.6), panels=2, sharex=True,
    )

    ax_top.bar(x, totals, width=0.72, color=theme.SERIES_BLUE)
    ax_top.set_ylabel("Posts across the fleet")
    ax_top.grid(axis="x", visible=False)
    ax_top.annotate(theme.compact(totals[-1]), xy=(x[-1], totals[-1]), xytext=(0, 5),
                    textcoords="offset points", ha="center", fontsize=9, color=theme.INK_SECONDARY)

    ax_bottom.fill_between(x, p25, p75, color=theme.SERIES_BLUE, alpha=0.16,
                           label="Middle half of active servers")
    ax_bottom.plot(x, median, color=theme.SERIES_BLUE, label="Median active server")
    ax_bottom.set_ylabel("Posts per active server")
    ax_bottom.set_xlabel("Month")
    ax_bottom.grid(axis="x", visible=False)
    ax_bottom.legend(loc="upper left", ncols=2)

    theme.month_ticks(ax_bottom, months)
    theme.finish(fig, out_dir, "16_monthly_output.png",
                 note="An active server is one that published at least one post that month. "
                      "The final month is still in progress, so it is not comparable to the ones before it.")
    theme.write_csv(
        out_dir, "16_monthly_output.csv",
        ["month", "posts", "active_servers", "p25_per_server", "median_per_server", "p75_per_server"],
        [[f"{row['month']:%Y-%m}", row["posts"], row["active_servers"], f"{row['p25_per_server']:.2f}",
          f"{row['median_per_server']:.2f}", f"{row['p75_per_server']:.2f}"] for row in rows],
    )
    return Output("16_monthly_output.png", "Monthly output",
                  "Is the fleet posting more because of new servers or busier ones?",
                  "16_monthly_output.csv")


def render_posting_rhythm(out_dir, dataset):
    """When posts land, weekday against hour."""
    if not dataset.posting_rhythm:
        return None

    grid = np.zeros((7, 24), dtype=float)
    for cell in dataset.posting_rhythm:
        if 0 <= cell.weekday < 7 and 0 <= cell.hour < 24:
            grid[cell.weekday, cell.hour] += cell.posts
    total = grid.sum()
    if total <= 0:
        return None
    share_grid = grid / total * 100

    peak_day, peak_hour = np.unravel_index(int(np.argmax(share_grid)), share_grid.shape)

    fig, ax = theme.new_figure(
        "When does the Hall of Fame fill up?",
        f"Share of all posts by weekday and hour, UTC. Busiest slot: {WEEKDAY_LABELS[peak_day]} "
        f"{peak_hour:02d}:00 with {share_grid[peak_day, peak_hour]:.1f}% of posts.",
        figsize=(12.5, 4.6),
    )
    ax.grid(False)

    image = ax.imshow(share_grid, cmap=theme.SEQUENTIAL_CMAP, aspect="auto", vmin=0)
    ax.set_yticks(range(7))
    ax.set_yticklabels(WEEKDAY_LABELS)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{hour:02d}" for hour in range(0, 24, 2)])
    ax.set_xlabel("Hour of day (UTC)")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    bar = fig.colorbar(image, ax=ax, pad=0.012, fraction=0.02, shrink=0.85)
    bar.set_label("% of all posts", color=theme.INK_SECONDARY, fontsize=9)
    bar.outline.set_visible(False)
    bar.ax.tick_params(labelsize=8, color=theme.AXIS, labelcolor=theme.INK_MUTED, length=0)

    theme.finish(fig, out_dir, "17_posting_rhythm.png",
                 note="Useful for scheduling maintenance and for reading the leaderboard job's load profile.")
    theme.write_csv(
        out_dir, "17_posting_rhythm.csv",
        ["weekday", "hour", "posts", "share_of_posts_pct"],
        [
            [WEEKDAY_LABELS[day], hour, int(grid[day, hour]), f"{share_grid[day, hour]:.3f}"]
            for day in range(7) for hour in range(24)
        ],
    )
    return Output("17_posting_rhythm.png", "Posting rhythm",
                  "What time of week does the bot actually do its work?", "17_posting_rhythm.csv")


def render_threshold_bands(out_dir, dataset):
    """What thresholds servers pick, and how those servers then do."""
    rows = metrics.threshold_bands(dataset.servers)
    labels = [
        f"{row['band']}\n{row['median_members']:,.0f} members" for row in rows
    ]
    servers = [row["servers"] for row in rows]
    activation = [row["activation_rate"] for row in rows]

    default_band = max(rows, key=lambda row: row["servers"])

    fig, (ax_top, ax_bottom) = theme.new_figure(
        "Reaction thresholds: what servers choose, and what happens next",
        f"{default_band['share_of_servers']:.0f}% of servers sit in the {default_band['band']} band. "
        "The second panel asks whether a higher bar suppresses the first post.",
        figsize=(10.5, 7.4), panels=2, sharex=True,
    )

    x = np.arange(len(rows))
    bars_top = ax_top.bar(x, servers, width=0.62, color=theme.SERIES_BLUE)
    ax_top.set_ylabel("Servers")
    ax_top.grid(axis="x", visible=False)
    theme.label_bars(ax_top, bars_top, servers)

    bars_bottom = ax_bottom.bar(x, activation, width=0.62, color=theme.SERIES_ORANGE)
    ax_bottom.set_ylabel("% that ever posted")
    ax_bottom.set_xlabel("Reaction threshold band, with the band's median server size")
    ax_bottom.set_ylim(0, 105)
    ax_bottom.grid(axis="x", visible=False)
    theme.label_bars(ax_bottom, bars_bottom, activation, formatter=lambda v: f"{v:.0f}%")

    ax_bottom.set_xticks(x)
    ax_bottom.set_xticklabels(labels)

    theme.finish(fig, out_dir, "18_threshold_bands.png",
                 note="Bands are correlational: large servers both raise the threshold and behave differently anyway.")
    theme.write_csv(
        out_dir, "18_threshold_bands.csv",
        ["band", "servers", "share_of_servers_pct", "activation_rate_pct", "median_members",
         "median_posts_per_1k"],
        [[row["band"], row["servers"], f"{row['share_of_servers']:.2f}",
          f"{row['activation_rate']:.2f}", f"{row['median_members']:.0f}",
          f"{row['median_posts_per_1k']:.2f}"] for row in rows],
    )
    return Output("18_threshold_bands.png", "Reaction threshold bands",
                  "Is the default reaction threshold serving servers well?", "18_threshold_bands.csv")


def render_reaction_headroom(out_dir, dataset):
    """How far past its threshold a post actually lands."""
    if not dataset.reaction_headroom:
        return None

    labels, counts = metrics.reaction_headroom_histogram(dataset.reaction_headroom)
    total = sum(counts)
    if not total:
        return None
    shares = [count / total * 100 for count in counts]
    median_multiple = metrics.median_reaction_multiple(dataset.reaction_headroom)

    fig, ax = theme.new_figure(
        "How far above the threshold does a post land?",
        f"{total:,} posts. The median post reaches {median_multiple:.2f}x its server's reaction "
        "threshold.",
        figsize=(9.5, 5.4),
    )

    x = np.arange(len(labels))
    bars = ax.bar(x, shares, width=0.62, color=theme.SERIES_BLUE)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Reactions as a multiple of the server's threshold")
    ax.set_ylabel("% of posts")
    ax.grid(axis="x", visible=False)
    # A bucket holding a fraction of a percent should not be labelled "0%".
    theme.label_bars(ax, bars, shares,
                     formatter=lambda v: f"{v:.0f}%" if v >= 1 else f"{v:.1f}%")

    theme.finish(fig, out_dir, "19_reaction_headroom.png",
                 note="A mass piled in the first bucket means the threshold is what decides; a long tail means it is a formality.")
    theme.write_csv(
        out_dir, "19_reaction_headroom.csv",
        ["multiple_of_threshold", "posts", "share_of_posts_pct"],
        [[label, count, f"{share:.2f}"] for label, count, share in zip(labels, counts, shares)],
    )
    return Output("19_reaction_headroom.png", "Reaction headroom",
                  "Do posts scrape past the threshold or blow through it?", "19_reaction_headroom.csv")


def render_survival(out_dir, dataset):
    """How long an install lasts.

    One series, so no legend: the title names it. Deliberately not split by
    whether the server ever posted - leaving deletes the guild's config row, so
    every departure would land in the never-posted arm by construction and the
    chart would draw survivorship bias as a finding.
    """
    points = metrics.survival_curve(dataset.lifespans, dataset.now, max_months=24)
    usable = [point for point in points if point["survival"] is not None and point["eligible"] >= 5]
    if len(usable) < 4:
        return None

    half_life = metrics.survival_half_life(usable)
    half_life_text = (
        f"Half of all installs are gone by month {half_life}."
        if half_life is not None
        else f"More than half of installs survive the full {usable[-1]['month']} months tracked."
    )

    fig, ax = theme.new_figure(
        "How long does an install last?",
        f"Share of servers still installed N months after joining. {half_life_text}",
        figsize=(10.5, 6.0),
    )

    months = [point["month"] for point in usable]
    survival = [point["survival"] for point in usable]
    ax.plot(months, survival, color=theme.SERIES_BLUE)
    ax.fill_between(months, survival, color=theme.SERIES_BLUE, alpha=0.10)
    ax.set_xlabel("Months since install")
    ax.set_ylabel("% still installed")
    ax.set_ylim(0, 102)
    ax.set_xlim(0, months[-1])

    if half_life is not None:
        ax.axhline(50, color=theme.INK_MUTED, linewidth=1.0)
        ax.annotate("half of installs", xy=(0, 50), xytext=(6, 5), textcoords="offset points",
                    fontsize=8.5, color=theme.INK_MUTED)

    last = usable[-1]
    ax.annotate(
        f"{last['survival']:.0f}% at month {last['month']}\n(n={last['eligible']} old enough to count)",
        xy=(last["month"], last["survival"]), xytext=(-10, 14), textcoords="offset points",
        ha="right", fontsize=9, color=theme.INK_SECONDARY,
    )

    theme.finish(fig, out_dir, "20_install_survival.png",
                 note="Each point counts only servers old enough to have reached that age, so recent installs "
                      "do not drag the tail down. Ages with fewer than five eligible servers are omitted.")
    theme.write_csv(
        out_dir, "20_install_survival.csv",
        ["months_since_install", "servers_old_enough", "still_installed", "survival_pct"],
        [
            [point["month"], point["eligible"], point["alive"],
             "" if point["survival"] is None else f"{point['survival']:.2f}"]
            for point in points
        ],
    )
    return Output("20_install_survival.png", "Install survival",
                  "How long does a server keep the bot after installing it?",
                  "20_install_survival.csv")


def render_all(out_dir, dataset):
    """Every chart in the report, in reading order."""
    renderers = (
        render_size_distribution,
        render_concentration,
        render_growth_and_churn,
        render_cohort_retention,
        render_activation_funnel,
        render_size_vs_activity,
        render_monthly_posts,
        render_posting_rhythm,
        render_threshold_bands,
        render_reaction_headroom,
        render_survival,
    )
    outputs = []
    for renderer in renderers:
        output = renderer(out_dir, dataset)
        if output is None:
            print(f"  skipped {renderer.__name__}: not enough data")
            continue
        outputs.append(output)
        print(f"  wrote {os.path.basename(output.filename)}")
    return outputs
