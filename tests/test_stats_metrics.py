"""Tests for the statistics report's calculations.

Only ``stats.metrics`` is exercised here. It is deliberately free of numpy,
matplotlib and psycopg2 so that CI, which installs only ``requirements.txt``,
can still cover the maths behind every figure.
"""

import unittest
from datetime import date, datetime, timezone

from stats import metrics


def make_server(guild_id=1, member_count=100, reaction_threshold=5, joined_at=None,
                hof_channel_configured=True, total_posts=0, posts_last_30d=0,
                first_post_at=None, last_post_at=None, distinct_authors=0,
                calculation_method="most_reactions_on_emoji", **flags):
    return metrics.ServerRow(
        guild_id=guild_id,
        member_count=member_count,
        reaction_threshold=reaction_threshold,
        joined_at=joined_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
        hof_channel_configured=hof_channel_configured,
        total_posts=total_posts,
        posts_last_30d=posts_last_30d,
        first_post_at=first_post_at,
        last_post_at=last_post_at,
        distinct_authors=distinct_authors,
        calculation_method=calculation_method,
        flags=flags,
    )


class TimestampNormalisationTests(unittest.TestCase):
    def test_naive_timestamps_are_read_as_utc(self):
        naive = datetime(2025, 6, 1, 12, 0)
        self.assertEqual(metrics.as_utc(naive).tzinfo, timezone.utc)
        self.assertEqual(metrics.as_utc(naive).hour, 12)

    def test_aware_timestamps_are_converted_not_relabelled(self):
        aware = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(metrics.as_utc(aware), aware)

    def test_dates_become_midnight_utc(self):
        self.assertEqual(
            metrics.as_utc(date(2025, 6, 1)),
            datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

    def test_migration_placeholders_are_rejected(self):
        self.assertFalse(metrics.is_real_timestamp(datetime(1970, 1, 1, tzinfo=timezone.utc)))
        self.assertFalse(metrics.is_real_timestamp(None))
        self.assertTrue(metrics.is_real_timestamp(datetime(2025, 1, 1, tzinfo=timezone.utc)))


class MonthArithmeticTests(unittest.TestCase):
    def test_add_months_crosses_the_year_boundary(self):
        self.assertEqual(metrics.add_months(date(2025, 11, 1), 3), date(2026, 2, 1))
        self.assertEqual(metrics.add_months(date(2025, 1, 1), -1), date(2024, 12, 1))
        self.assertEqual(metrics.add_months(date(2025, 12, 1), 1), date(2026, 1, 1))

    def test_months_between_is_signed(self):
        self.assertEqual(metrics.months_between(date(2025, 1, 1), date(2025, 4, 1)), 3)
        self.assertEqual(metrics.months_between(date(2025, 4, 1), date(2025, 1, 1)), -3)

    def test_month_range_has_no_gaps(self):
        months = metrics.month_range(date(2025, 11, 1), date(2026, 2, 1))
        self.assertEqual(
            months,
            [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)],
        )


class DistributionTests(unittest.TestCase):
    def test_percentile_interpolates_like_numpy(self):
        values = [1, 2, 3, 4]
        self.assertAlmostEqual(metrics.percentile(values, 0), 1.0)
        self.assertAlmostEqual(metrics.percentile(values, 50), 2.5)
        self.assertAlmostEqual(metrics.percentile(values, 100), 4.0)
        self.assertAlmostEqual(metrics.percentile(values, 25), 1.75)

    def test_percentile_of_empty_input_is_zero(self):
        self.assertEqual(metrics.percentile([], 50), 0.0)

    def test_gini_is_zero_when_everything_is_equal(self):
        self.assertAlmostEqual(metrics.gini([5, 5, 5, 5]), 0.0)

    def test_gini_approaches_one_when_one_entry_holds_everything(self):
        self.assertGreater(metrics.gini([0, 0, 0, 0, 0, 0, 0, 0, 0, 100]), 0.85)

    def test_lorenz_curve_starts_at_origin_and_ends_at_100(self):
        population, cumulative = metrics.lorenz_curve([1, 2, 3, 4])
        self.assertEqual((population[0], cumulative[0]), (0.0, 0.0))
        self.assertAlmostEqual(population[-1], 100.0)
        self.assertAlmostEqual(cumulative[-1], 100.0)

    def test_lorenz_curve_of_an_even_distribution_is_the_diagonal(self):
        population, cumulative = metrics.lorenz_curve([4, 4, 4, 4])
        for x, y in zip(population, cumulative):
            self.assertAlmostEqual(x, y)

    def test_top_share_counts_the_largest_entries(self):
        # Ten servers, one holding 100 and nine holding 0.
        values = [100] + [0] * 9
        self.assertAlmostEqual(metrics.top_share(values, 0.1), 100.0)

    def test_top_share_always_takes_at_least_one_entry(self):
        self.assertAlmostEqual(metrics.top_share([10, 10], 0.01), 50.0)

    def test_log_histogram_spreads_values_across_decades(self):
        edges, counts = metrics.log_histogram([1, 10, 100, 1000], bins_per_decade=1)
        self.assertEqual(sum(counts), 4)
        self.assertTrue(all(edges[i] < edges[i + 1] for i in range(len(edges) - 1)))

    def test_log_histogram_ignores_non_positive_values(self):
        _edges, counts = metrics.log_histogram([0, -5, 10, 20], bins_per_decade=1)
        self.assertEqual(sum(counts), 2)

    def test_bin_by_edges_sums_weights_not_occurrences(self):
        totals = metrics.bin_by_edges([(5, 5), (7, 7), (50, 50)], [1, 10, 100])
        self.assertEqual(totals, [12.0, 50.0])


class LifespanTests(unittest.TestCase):
    def test_a_join_with_no_leave_is_still_installed(self):
        events = [(1, "JOIN", datetime(2025, 1, 5, tzinfo=timezone.utc))]
        lifespans = metrics.build_lifespans(events, [make_server(guild_id=1)])
        self.assertEqual(len(lifespans), 1)
        self.assertTrue(lifespans[0].is_alive)

    def test_a_leave_event_closes_the_lifespan(self):
        events = [
            (1, "JOIN", datetime(2025, 1, 5, tzinfo=timezone.utc)),
            (1, "LEAVE", datetime(2025, 4, 5, tzinfo=timezone.utc)),
        ]
        lifespans = metrics.build_lifespans(events, [])
        self.assertEqual(lifespans[0].left_at, datetime(2025, 4, 5, tzinfo=timezone.utc))

    def test_a_guild_with_no_config_row_counts_as_churned(self):
        # Leaving deletes the config row. A JOIN with no matching config and no
        # LEAVE row is a guild that went away without the event being recorded.
        events = [(1, "JOIN", datetime(2025, 1, 5, tzinfo=timezone.utc))]
        lifespans = metrics.build_lifespans(events, servers=[])
        self.assertFalse(lifespans[0].is_alive)

    def test_installed_guilds_without_events_fall_back_to_joined_date(self):
        server = make_server(guild_id=7, joined_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
        lifespans = metrics.build_lifespans([], [server])
        self.assertEqual(len(lifespans), 1)
        self.assertEqual(lifespans[0].guild_id, 7)
        self.assertTrue(lifespans[0].is_alive)

    def test_placeholder_join_dates_are_not_turned_into_lifespans(self):
        server = make_server(guild_id=7, joined_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(metrics.build_lifespans([], [server]), [])

    def test_a_reinvite_restarts_the_clock(self):
        events = [
            (1, "JOIN", datetime(2024, 1, 1, tzinfo=timezone.utc)),
            (1, "LEAVE", datetime(2024, 6, 1, tzinfo=timezone.utc)),
            (1, "JOIN", datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ]
        lifespans = metrics.build_lifespans(events, [make_server(guild_id=1)])
        self.assertEqual(lifespans[0].joined_at, datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(lifespans[0].is_alive)


class LifecycleByMonthTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 4, 15, tzinfo=timezone.utc)
        self.lifespans = [
            metrics.GuildLifespan(1, datetime(2025, 1, 10, tzinfo=timezone.utc)),
            metrics.GuildLifespan(2, datetime(2025, 1, 20, tzinfo=timezone.utc),
                                  datetime(2025, 3, 5, tzinfo=timezone.utc)),
            metrics.GuildLifespan(3, datetime(2025, 2, 2, tzinfo=timezone.utc)),
        ]

    def test_installed_base_is_the_running_net(self):
        rows = metrics.lifecycle_by_month(self.lifespans, self.now)
        self.assertEqual([row["installed"] for row in rows], [2, 3, 2, 2])

    def test_joins_and_leaves_land_in_the_right_months(self):
        rows = {row["month"]: row for row in metrics.lifecycle_by_month(self.lifespans, self.now)}
        self.assertEqual(rows[date(2025, 1, 1)]["joined"], 2)
        self.assertEqual(rows[date(2025, 3, 1)]["left"], 1)
        self.assertEqual(rows[date(2025, 3, 1)]["net"], -1)

    def test_churn_is_measured_against_the_opening_installed_base(self):
        rows = {row["month"]: row for row in metrics.lifecycle_by_month(self.lifespans, self.now)}
        # Three servers were installed entering March and one of them left.
        self.assertAlmostEqual(rows[date(2025, 3, 1)]["churn_rate"], 100 / 3)

    def test_the_first_month_cannot_churn(self):
        rows = metrics.lifecycle_by_month(self.lifespans, self.now)
        self.assertEqual(rows[0]["churn_rate"], 0.0)


class ActivationFunnelTests(unittest.TestCase):
    def setUp(self):
        self.servers = [
            # Posting now, but has never reached ten posts.
            make_server(guild_id=1, total_posts=3, posts_last_30d=3),
            # Plenty of posts, but dormant.
            make_server(guild_id=2, total_posts=40, posts_last_30d=0),
            # The full funnel.
            make_server(guild_id=3, total_posts=40, posts_last_30d=6),
            # Installed and never configured.
            make_server(guild_id=4, hof_channel_configured=False),
        ]

    def test_stages_never_grow(self):
        counts = [row["servers"] for row in metrics.activation_funnel(self.servers)]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_no_stage_converts_above_100_percent(self):
        # Counting stages independently used to report a live server that never
        # reached ten posts as a gain over the stage above it.
        for row in metrics.activation_funnel(self.servers):
            self.assertLessEqual(row["step_conversion"], 100.0)

    def test_the_final_stage_requires_every_earlier_condition(self):
        rows = metrics.activation_funnel(self.servers)
        self.assertEqual(rows[0]["servers"], 4)
        self.assertEqual(rows[-1]["servers"], 1)

    def test_an_empty_fleet_does_not_divide_by_zero(self):
        rows = metrics.activation_funnel([])
        self.assertEqual([row["servers"] for row in rows], [0, 0, 0, 0, 0])
        self.assertEqual(rows[0]["share_of_installs"], 0.0)


class CohortRetentionTests(unittest.TestCase):
    def test_months_that_have_not_happened_are_left_blank(self):
        lifespans = [metrics.GuildLifespan(1, datetime(2025, 1, 10, tzinfo=timezone.utc))]
        result = metrics.cohort_retention(lifespans, datetime(2025, 3, 15, tzinfo=timezone.utc),
                                          max_months=6)
        row = result["matrix"][0]
        self.assertEqual(row[:3], [100.0, 100.0, 100.0])
        self.assertTrue(all(value is None for value in row[3:]))

    def test_a_departure_shows_up_from_the_month_it_happened(self):
        lifespans = [
            metrics.GuildLifespan(1, datetime(2025, 1, 10, tzinfo=timezone.utc)),
            metrics.GuildLifespan(2, datetime(2025, 1, 12, tzinfo=timezone.utc),
                                  datetime(2025, 2, 20, tzinfo=timezone.utc)),
        ]
        result = metrics.cohort_retention(lifespans, datetime(2025, 4, 15, tzinfo=timezone.utc),
                                          max_months=3)
        self.assertEqual(result["sizes"], [2])
        # Both alive at M0 and M1; the second is gone by the start of M2.
        self.assertEqual(result["matrix"][0][:3], [100.0, 100.0, 50.0])

    def test_no_lifespans_gives_an_empty_grid(self):
        result = metrics.cohort_retention([], datetime(2025, 4, 15, tzinfo=timezone.utc))
        self.assertEqual(result["cohorts"], [])


class SurvivalTests(unittest.TestCase):
    def test_only_servers_old_enough_are_counted(self):
        lifespans = [
            metrics.GuildLifespan(1, datetime(2024, 1, 10, tzinfo=timezone.utc)),
            metrics.GuildLifespan(2, datetime(2025, 3, 10, tzinfo=timezone.utc)),
        ]
        points = metrics.survival_curve(lifespans, datetime(2025, 4, 15, tzinfo=timezone.utc),
                                        max_months=12)
        self.assertEqual(points[0]["eligible"], 2)
        # Only the 2024 install is old enough to have reached month 12.
        self.assertEqual(points[12]["eligible"], 1)

    def test_survival_is_none_when_nothing_is_eligible(self):
        lifespans = [metrics.GuildLifespan(1, datetime(2025, 4, 1, tzinfo=timezone.utc))]
        points = metrics.survival_curve(lifespans, datetime(2025, 4, 15, tzinfo=timezone.utc),
                                        max_months=3)
        self.assertIsNone(points[2]["survival"])

    def test_half_life_is_the_first_age_below_fifty_percent(self):
        points = [
            {"month": 0, "survival": 100.0},
            {"month": 1, "survival": 70.0},
            {"month": 2, "survival": 40.0},
            {"month": 3, "survival": 45.0},
        ]
        self.assertEqual(metrics.survival_half_life(points), 2)

    def test_half_life_is_none_when_survival_stays_high(self):
        points = [{"month": 0, "survival": 100.0}, {"month": 1, "survival": 80.0}]
        self.assertIsNone(metrics.survival_half_life(points))


class MonthlyPostSummaryTests(unittest.TestCase):
    def test_months_with_no_posts_are_still_reported(self):
        entries = [
            metrics.MonthlyGuildPosts(date(2025, 1, 1), 1, 4),
            metrics.MonthlyGuildPosts(date(2025, 3, 1), 1, 6),
        ]
        rows = metrics.monthly_post_summary(entries)
        self.assertEqual([row["month"] for row in rows],
                         [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)])
        self.assertEqual(rows[1]["posts"], 0)
        self.assertEqual(rows[1]["active_servers"], 0)

    def test_the_median_ignores_servers_that_did_not_post(self):
        entries = [
            metrics.MonthlyGuildPosts(date(2025, 1, 1), 1, 2),
            metrics.MonthlyGuildPosts(date(2025, 1, 1), 2, 4),
            metrics.MonthlyGuildPosts(date(2025, 1, 1), 3, 300),
        ]
        row = metrics.monthly_post_summary(entries)[0]
        self.assertEqual(row["active_servers"], 3)
        self.assertAlmostEqual(row["median_per_server"], 4.0)


class SegmentationTests(unittest.TestCase):
    def test_servers_land_in_the_expected_size_band(self):
        self.assertEqual(make_server(member_count=50).size_bucket, "< 100")
        self.assertEqual(make_server(member_count=100).size_bucket, "100 - 499")
        self.assertEqual(make_server(member_count=25_000).size_bucket, "10k+")

    def test_size_segments_shares_add_up(self):
        servers = [
            make_server(guild_id=1, member_count=50, total_posts=1),
            make_server(guild_id=2, member_count=800, total_posts=9),
            make_server(guild_id=3, member_count=20_000, total_posts=90),
        ]
        rows = metrics.size_segments(servers)
        self.assertAlmostEqual(sum(row["share_of_servers"] for row in rows), 100.0)
        self.assertAlmostEqual(sum(row["share_of_posts"] for row in rows), 100.0)
        self.assertAlmostEqual(sum(row["share_of_members"] for row in rows), 100.0)

    def test_empty_size_bands_do_not_divide_by_zero(self):
        rows = metrics.size_segments([make_server(member_count=50)])
        empty = [row for row in rows if row["segment"] == "10k+"][0]
        self.assertEqual(empty["servers"], 0)
        self.assertEqual(empty["activation_rate"], 0.0)

    def test_threshold_bands_split_on_the_documented_edges(self):
        self.assertEqual(make_server(reaction_threshold=3).threshold_band, "1 - 3")
        self.assertEqual(make_server(reaction_threshold=5).threshold_band, "4 - 5")
        self.assertEqual(make_server(reaction_threshold=25).threshold_band, "20+")

    def test_config_adoption_compares_activation_on_and_off(self):
        servers = [
            make_server(guild_id=1, total_posts=5, leaderboard_setup=True),
            make_server(guild_id=2, total_posts=0, leaderboard_setup=False),
        ]
        row = [r for r in metrics.config_adoption(servers) if r["setting"] == "Leaderboard set up"][0]
        self.assertEqual(row["servers_on"], 1)
        self.assertAlmostEqual(row["activation_on"], 100.0)
        self.assertAlmostEqual(row["activation_off"], 0.0)


class ServerRowDerivationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 4, 1, tzinfo=timezone.utc)

    def test_posts_per_day_uses_days_installed(self):
        server = make_server(joined_at=datetime(2025, 3, 2, tzinfo=timezone.utc), total_posts=30)
        self.assertAlmostEqual(server.posts_per_day(self.now), 1.0, places=2)

    def test_posts_per_day_is_none_without_a_usable_join_date(self):
        server = make_server(joined_at=datetime(1970, 1, 1, tzinfo=timezone.utc), total_posts=30)
        self.assertIsNone(server.posts_per_day(self.now))

    def test_posts_per_1k_members_is_none_for_an_unknown_member_count(self):
        self.assertIsNone(make_server(member_count=0, total_posts=5).posts_per_1k_members)
        self.assertAlmostEqual(make_server(member_count=500, total_posts=5).posts_per_1k_members, 10.0)

    def test_days_to_first_post_needs_both_timestamps(self):
        server = make_server(
            joined_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            first_post_at=datetime(2025, 1, 11, tzinfo=timezone.utc),
            total_posts=1,
        )
        self.assertAlmostEqual(server.days_to_first_post, 10.0)
        self.assertIsNone(make_server(total_posts=1).days_to_first_post)


class ReactionHeadroomTests(unittest.TestCase):
    def test_posts_are_bucketed_by_multiple_of_the_threshold(self):
        buckets = [
            metrics.ReactionBucket(reaction_count=5, reaction_threshold=5, posts=10),   # 1.0x
            metrics.ReactionBucket(reaction_count=10, reaction_threshold=5, posts=4),   # 2.0x
            metrics.ReactionBucket(reaction_count=30, reaction_threshold=5, posts=1),   # 6.0x
        ]
        labels, counts = metrics.reaction_headroom_histogram(buckets)
        self.assertEqual(counts[0], 10)
        self.assertEqual(counts[labels.index("2 - 3x")], 4)
        self.assertEqual(counts[-1], 1)

    def test_a_zero_threshold_is_skipped_rather_than_crashing(self):
        buckets = [metrics.ReactionBucket(reaction_count=5, reaction_threshold=0, posts=3)]
        _labels, counts = metrics.reaction_headroom_histogram(buckets)
        self.assertEqual(sum(counts), 0)

    def test_median_multiple_is_weighted_by_post_count(self):
        buckets = [
            metrics.ReactionBucket(reaction_count=5, reaction_threshold=5, posts=99),
            metrics.ReactionBucket(reaction_count=50, reaction_threshold=5, posts=1),
        ]
        self.assertAlmostEqual(metrics.median_reaction_multiple(buckets), 1.0)

    def test_median_multiple_of_nothing_is_zero(self):
        self.assertEqual(metrics.median_reaction_multiple([]), 0.0)


class HeadlineKpiTests(unittest.TestCase):
    def test_an_empty_fleet_reports_nothing_rather_than_crashing(self):
        dataset = metrics.StatsDataset(generated_at=datetime(2025, 4, 1, tzinfo=timezone.utc))
        self.assertEqual(metrics.headline_kpis(dataset), [])

    def test_every_kpi_has_a_label_value_and_note(self):
        dataset = metrics.StatsDataset(
            generated_at=datetime(2025, 4, 1, tzinfo=timezone.utc),
            servers=[make_server(guild_id=1, total_posts=5, posts_last_30d=2)],
            lifespans=[metrics.GuildLifespan(1, datetime(2025, 1, 1, tzinfo=timezone.utc))],
            monthly_guild_posts=[metrics.MonthlyGuildPosts(date(2025, 3, 1), 1, 5)],
        )
        kpis = metrics.headline_kpis(dataset)
        self.assertTrue(kpis)
        for kpi in kpis:
            self.assertIn(kpi["format"], {"int", "pct", "float"})
            self.assertTrue(kpi["label"])
            self.assertTrue(kpi["note"])


if __name__ == "__main__":
    unittest.main()
