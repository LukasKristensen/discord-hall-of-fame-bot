"""Tests for the parts of the statistics report that need the plotting stack.

``stats.report`` and ``stats.charts`` import matplotlib, which CI does not install because the bot
never plots anything, so these are skipped there and run wherever the report itself can be run.
"""

import dataclasses
import importlib.util
import os
import tempfile
import unittest
import warnings
from datetime import datetime, timezone

HAS_PLOTTING = all(importlib.util.find_spec(name) for name in ("matplotlib", "numpy"))


@unittest.skipUnless(HAS_PLOTTING, "the report needs matplotlib and numpy")
class CreateOutputDirTests(unittest.TestCase):
    def setUp(self):
        from stats import report
        self.report = report
        self.root = tempfile.mkdtemp()
        self.moment = datetime(2026, 9, 26, 15, 0, 0, tzinfo=timezone.utc)

    def test_two_exports_in_the_same_second_get_their_own_folders(self):
        """Sharing one would have the second export silently overwrite the first."""
        first = self.report.create_output_dir(self.root, self.moment)
        second = self.report.create_output_dir(self.root, self.moment)

        self.assertNotEqual(first, second)
        self.assertTrue(os.path.isdir(first))
        self.assertTrue(os.path.isdir(second))

    def test_names_the_folder_after_the_time_it_was_made(self):
        path = self.report.create_output_dir(self.root, self.moment)
        self.assertEqual("20260926_150000", os.path.basename(path))


@unittest.skipUnless(HAS_PLOTTING, "the report needs matplotlib and numpy")
class SizeDistributionChartTests(unittest.TestCase):
    def test_servers_of_unknown_size_do_not_break_the_median_marker(self):
        """A size of 0 means it was never recorded, and log10(0) has no place on the axis."""
        from stats import charts, synthetic, theme

        theme.apply_style()
        dataset = synthetic.build_dataset()
        count = len(dataset.servers)
        servers = [dataclasses.replace(server, member_count=0) if index < count * 0.6 else server
                   for index, server in enumerate(dataset.servers)]

        with tempfile.TemporaryDirectory() as out_dir, warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            output = charts.render_size_distribution(out_dir, dataclasses.replace(dataset, servers=servers))

        self.assertIsNotNone(output)


if __name__ == "__main__":
    unittest.main()
