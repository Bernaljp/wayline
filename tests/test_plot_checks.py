"""The five readability checks on a plot's SVG (ticket 77; Implementation Decision 17).

Every sample under `fixtures/plots/samples/` was drawn by the library it is named after
(`fixtures/plots/make_python.py`, `make_altair.py`, `make_ggplot2.R`), so the checks are held to
the SVG each library really writes: matplotlib with its text as glyph outlines (its default),
seaborn through matplotlib with its text as `<text>`, Altair through vl-convert, and ggplot2
through svglite and through R's own cairo `svg()` device. Per library, `<lib>-clean.svg` and
`<lib>-heatmap-36.svg` pass all five checks, and each other sample is made to break one.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR
from wayline import POLICY_PATH, plot_checks

SAMPLES = FIXTURES_DIR / "plots" / "samples"
LIBRARIES = ("matplotlib", "seaborn", "altair", "ggplot2")

# The sample made to break each check.
BROKEN = {
    "rotated_text": "rotated-ticks",
    "axis_label_length": "long-label",
    "stacked_titles": "suptitle",
    "heatmap_cell_labels": "heatmap-37",
    "flat_summary_mark": "flat-box",
}


def run(name, **kwargs):
    report = plot_checks.run_readability_checks(SAMPLES / (name + ".svg"), **kwargs)
    return {outcome["id"]: outcome for outcome in report}


class ReadabilityChecksTest(unittest.TestCase):
    def test_the_report_lists_the_five_checks_in_order_as_type_a_outcomes(self):
        report = plot_checks.run_readability_checks(SAMPLES / "matplotlib-clean.svg")
        self.assertEqual([outcome["id"] for outcome in report], list(plot_checks.READABILITY_CHECK_IDS))
        self.assertEqual(list(plot_checks.READABILITY_CHECK_IDS), list(BROKEN))
        for outcome in report:
            self.assertEqual(set(outcome), {"id", "type", "pass", "tool", "detail"})
            self.assertEqual(outcome["type"], "A")

    def test_the_clean_samples_of_every_library_pass_all_five(self):
        for library in LIBRARIES:
            for sample in ("clean", "heatmap-36"):
                report = run("%s-%s" % (library, sample))
                for check_id, outcome in report.items():
                    with self.subTest(library=library, sample=sample, check=check_id):
                        self.assertIs(outcome["pass"], True, outcome["detail"])

    def test_each_broken_sample_fails_its_own_check_and_only_it(self):
        for library in LIBRARIES:
            for check_id, sample in BROKEN.items():
                report = run("%s-%s" % (library, sample))
                with self.subTest(library=library, check=check_id):
                    self.assertIs(report[check_id]["pass"], False, report[check_id]["detail"])
                for other, outcome in report.items():
                    if other != check_id:
                        with self.subTest(library=library, sample=sample, other=other):
                            self.assertIs(outcome["pass"], True, outcome["detail"])

    def test_plots_that_only_look_like_a_broken_sample_pass_all_five(self):
        """Bars of tiny values, a stacked bar's thin top, 400 narrow bins, panel letters under a figure title,
        a mathtext label short as drawn, a ggplot2 caption and bottom legend under a short x title, a
        `theme_classic` panel of points and labels, and an annotated `imshow` of 36 cells."""
        for name in ("matplotlib-bars", "matplotlib-imshow-36", "ggplot2-caption-and-bars", "ggplot2-points-classic"):
            for check_id, outcome in run(name).items():
                with self.subTest(sample=name, check=check_id):
                    self.assertIs(outcome["pass"], True, outcome["detail"])

    def test_an_annotated_raster_heatmap_and_one_drawn_with_gaps_are_still_counted(self):
        for name in ("matplotlib-imshow-49", "ggplot2-tile-gaps-37"):
            report = run(name)
            with self.subTest(sample=name):
                self.assertIs(report["heatmap_cell_labels"]["pass"], False, report["heatmap_cell_labels"]["detail"])
                self.assertEqual([check for check, outcome in report.items() if outcome["pass"] is not True], ["heatmap_cell_labels"])

    def test_the_failures_name_what_broke_the_check(self):
        self.assertIn("'raw'", run("ggplot2-rotated-ticks")["rotated_text"]["detail"])
        self.assertIn("43 characters", run("altair-long-label")["axis_label_length"]["detail"])
        self.assertIn("'AUROC by arm'", run("seaborn-suptitle")["stacked_titles"]["detail"])
        self.assertIn("37 cells", run("matplotlib-heatmap-37")["heatmap_cell_labels"]["detail"])
        self.assertIn("flat", run("ggplot2-flat-box")["flat_summary_mark"]["detail"])


class NotRunTest(unittest.TestCase):
    """A check that cannot run on a plot is listed as not run with the reason, never passed or failed."""

    def test_the_text_checks_do_not_run_on_glyph_outlines_and_the_geometric_ones_still_do(self):
        report = run("ggplot2-cairo-outlines")
        for check_id in ("rotated_text", "axis_label_length", "stacked_titles"):
            with self.subTest(check=check_id):
                self.assertIsNone(report[check_id]["pass"])
                self.assertIs(report[check_id]["not_run"], True)
                self.assertIn("glyph outlines", report[check_id]["detail"])
        self.assertIs(report["heatmap_cell_labels"]["pass"], True)
        self.assertIs(report["flat_summary_mark"]["pass"], True)

    def test_an_svg_whose_writer_names_no_roles_runs_only_the_geometric_checks(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">'
               '<rect x="10" y="40" width="30" height="0" fill="#888"/>'
               '<text x="50" y="70" transform="rotate(-45 50 70)">sideways</text></svg>')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plot.svg"
            path.write_text(svg, encoding="utf-8")
            report = {outcome["id"]: outcome for outcome in plot_checks.run_readability_checks(path)}
        self.assertIsNone(report["rotated_text"]["pass"])
        self.assertIn("writer", report["rotated_text"]["detail"])
        self.assertIs(report["flat_summary_mark"]["pass"], False)

    def test_an_unreadable_svg_fails_every_check_with_the_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plot.svg"
            path.write_text("<svg", encoding="utf-8")
            report = plot_checks.run_readability_checks(path)
        self.assertEqual([outcome["pass"] for outcome in report], [False] * 5)
        self.assertIn("could not be read", report[0]["detail"])


class ThresholdsTest(unittest.TestCase):
    """40 characters and 36 cells are policy values, read from `policy.plot_checks`."""

    def test_the_shipped_policy_holds_the_two_thresholds(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(policy["plot_checks"], {"axis_label_max_chars": 40, "heatmap_label_max_cells": 36})

    def test_the_limits_are_inclusive_one_over_fails(self):
        """The long-label samples carry 43 characters and the broken heatmaps 37 cells: one over a limit fails, the limit passes."""
        at = {"plot_checks": {"axis_label_max_chars": 43, "heatmap_label_max_cells": 37}}
        under = {"plot_checks": {"axis_label_max_chars": 42, "heatmap_label_max_cells": 36}}
        for library in LIBRARIES:
            with self.subTest(library=library):
                self.assertIs(run("%s-long-label" % library, policy=at)["axis_label_length"]["pass"], True)
                self.assertIs(run("%s-long-label" % library, policy=under)["axis_label_length"]["pass"], False)
                self.assertIs(run("%s-heatmap-37" % library, policy=at)["heatmap_cell_labels"]["pass"], True)
                self.assertIs(run("%s-heatmap-37" % library, policy=under)["heatmap_cell_labels"]["pass"], False)

    def test_a_project_policy_moves_the_thresholds(self):
        loose = {"plot_checks": {"axis_label_max_chars": 50, "heatmap_label_max_cells": 40}}
        self.assertIs(run("matplotlib-long-label", policy=loose)["axis_label_length"]["pass"], True)
        self.assertIs(run("seaborn-heatmap-37", policy=loose)["heatmap_cell_labels"]["pass"], True)
        tight = {"plot_checks": {"axis_label_max_chars": 4, "heatmap_label_max_cells": 9}}
        self.assertIs(run("ggplot2-clean", policy=tight)["axis_label_length"]["pass"], False)
        self.assertIs(run("altair-heatmap-36", policy=tight)["heatmap_cell_labels"]["pass"], False)


if __name__ == "__main__":
    unittest.main()
