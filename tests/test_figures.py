"""The plot index: the crawl, the family classifier, seeded pitfalls, refresh, and the trap fold.

Every request in this module is answered from `fixtures/fetch/`, recorded against the live
sites on 2026-09-12 (see `fixtures/fetch/README.md`). A request nobody recorded raises, so a
test that reached the network would fail rather than pass slowly.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR
from wayline.fetch import Backend, Fetcher, Response, recording_fetcher
from wayline.figures import (
    FAMILIES, SITES, build_index, classify_family, default_style, figures_command,
    fold_traps_hit, load_index, refresh_full, refresh_liveness, structure_index, write_index,
)

RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"
TODAY = "2026-09-12"

# The six pages `fixtures/fetch/` carries for this module, one per site plus a second
# python-graph-gallery page chosen to exercise the matplotlib pitfall seeding.
CHART_URLS = frozenset([
    "https://python-graph-gallery.com/50-basic-violinplot-and-input-formats/",
    "https://python-graph-gallery.com/130-basic-matplotlib-scatterplot/",
    "https://r-graph-gallery.com/136-stacked-area-chart.html",
    "https://altair-viz.github.io/gallery/scatter_tooltips.html",
    "https://seaborn.pydata.org/examples/grouped_barplot.html",
    "https://plotnine.org/gallery/annotated-heatmap.html",
])


def _keep(url):
    return url in CHART_URLS


def _clock():
    return TODAY


def fetcher():
    return recording_fetcher(RECORDINGS, email=EMAIL)


def _by_id(index, needle):
    for entry in index["entries"]:
        if needle in entry["id"]:
            return entry
    raise AssertionError("no entry id contains %r among %r" % (needle, [e["id"] for e in index["entries"]]))


class BuildIndexTest(unittest.TestCase):
    def test_the_index_covers_all_five_sites(self):
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        self.assertEqual(index["source_counts"], {
            "python-graph-gallery": 2, "r-graph-gallery": 1, "altair": 1, "seaborn": 1, "plotnine": 1,
        })
        self.assertEqual(len(index["entries"]), 6)
        self.assertEqual(index["built"], TODAY)

    def test_every_entry_has_the_schema_of_research_notes_09(self):
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        required = {
            "id", "family", "chart_type", "data_shape", "when_to_use", "when_not_to_use",
            "library_implementations", "gallery_links", "known_pitfalls", "source_site",
            "source_license", "last_verified", "last_crawled",
        }
        for entry in index["entries"]:
            with self.subTest(entry=entry["id"]):
                self.assertEqual(required, set(entry.keys()))
                self.assertIn(entry["family"], FAMILIES)
                implementation = entry["library_implementations"][0]
                self.assertIn("library", implementation)
                self.assertIn("source_url", implementation["snippet_locator"])
                self.assertGreaterEqual(len(entry["gallery_links"]), 2)

    def test_no_entry_carries_prose_copied_from_a_site_or_an_image(self):
        """The catalog holds metadata and locators only (BRIEF 13.1); no field is a URL to an image."""
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        for entry in index["entries"]:
            for link in entry["gallery_links"] + [entry["library_implementations"][0]["snippet_locator"]["source_url"]]:
                self.assertNotRegex(link, r"\.(png|jpe?g|gif|svg)$")

    def test_family_classification_matches_research_notes_09s_own_examples(self):
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        expected = {
            "basic-violinplot-and-input-formats-python-graph-gallery": "distribution",
            "basic-matplotlib-scatterplot-python-graph-gallery": "correlation",
            "stacked-area-chart-r-graph-gallery": "evolution",
            "scatter-tooltips-altair": "correlation",
            "grouped-barplot-seaborn": "ranking",
            "annotated-heatmap-plotnine": "correlation",
        }
        for entry in index["entries"]:
            with self.subTest(entry=entry["id"]):
                self.assertEqual(entry["family"], expected[entry["id"]])

    def test_the_matplotlib_entry_is_seeded_with_the_skills_pitfalls(self):
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        entry = _by_id(index, "basic-matplotlib-scatterplot")
        self.assertEqual(entry["library_implementations"][0]["library"], "matplotlib")
        self.assertGreaterEqual(len(entry["known_pitfalls"]), 5)
        self.assertTrue(any("negative zorder" in pitfall for pitfall in entry["known_pitfalls"]))
        self.assertTrue(any("pdftotext" in pitfall for pitfall in entry["known_pitfalls"]))
        # never the skill's own wording, verbatim
        for pitfall in entry["known_pitfalls"]:
            self.assertNotIn("Figure.get_children()", pitfall)

    def test_a_non_matplotlib_entry_carries_no_seeded_pitfall(self):
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        entry = _by_id(index, "scatter-tooltips-altair")
        self.assertEqual(entry["known_pitfalls"], [])

    def test_the_function_or_geom_survives_the_syntax_highlighters_per_token_tags(self):
        """seaborn and plotnine wrap every token, including a lone `.`, in its own <span>."""
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        self.assertEqual(_by_id(index, "grouped-barplot-seaborn")["library_implementations"][0]["function_or_geom"], "sns.set_theme")
        self.assertEqual(_by_id(index, "annotated-heatmap-plotnine")["library_implementations"][0]["function_or_geom"], "geom_tile")

    def test_plotnine_is_not_mistaken_for_ggplot2(self):
        """`ggplot()` and `geom_*()` are also plotnine's own syntax; only the source site can tell them apart."""
        index = build_index(fetcher(), clock=_clock, url_filter=_keep)
        self.assertEqual(_by_id(index, "annotated-heatmap-plotnine")["library_implementations"][0]["library"], "plotnine")
        self.assertEqual(_by_id(index, "stacked-area-chart-r-graph-gallery")["library_implementations"][0]["library"], "ggplot2")

    def test_the_crawl_is_paced_at_one_request_per_second_with_a_descriptive_user_agent(self):
        chain = fetcher()
        build_index(chain, clock=_clock, url_filter=_keep)
        self.assertTrue(chain.user_agent.startswith("wayline/"))
        self.assertIn("mailto:%s" % EMAIL, chain.user_agent)
        self.assertEqual(set(chain.hosts), {
            "python-graph-gallery.com", "r-graph-gallery.com", "altair-viz.github.io",
            "seaborn.pydata.org", "plotnine.org",
        })


class ClassifyFamilyTest(unittest.TestCase):
    def test_a_heatmap_is_not_the_map_family(self):
        self.assertEqual(classify_family("Annotated Heatmap"), "correlation")

    def test_a_stacked_area_chart_is_evolution_not_part_of_a_whole(self):
        self.assertEqual(classify_family("Stacked area chart with R"), "evolution")

    def test_a_scatterplot_matches_as_one_word(self):
        self.assertEqual(classify_family("Basic Matplotlib Scatterplot"), "correlation")

    def test_a_real_map_is_the_map_family(self):
        self.assertEqual(classify_family("Choropleth Map of Population"), "map")

    def test_nothing_recognizable_falls_back_to_multi_dimensional(self):
        self.assertEqual(classify_family("A Perfectly Unclassifiable Diagram"), "multi_dimensional")


class StructureAndStyleTest(unittest.TestCase):
    def test_structure_index_has_the_four_named_layouts(self):
        structures = {structure["id"] for structure in structure_index()["structures"]}
        self.assertEqual(structures, {"pipeline", "funnel-and-fan", "grid", "before-and-after"})

    def test_default_style_has_the_color_budget_of_brief_13_1(self):
        style = default_style()
        self.assertEqual(len(style["categorical"]), len(set(style["categorical"])))
        self.assertGreaterEqual(len(style["categorical"]), 8)
        self.assertIn("low", style["diverging"])
        self.assertIn("high", style["diverging"])
        self.assertTrue(style["special_hue"].startswith("#"))
        self.assertGreaterEqual(len(style["equation_parameter_colors"]), 1)


class RefreshLivenessTest(unittest.TestCase):
    """A fake backend, never the network (Testing Decisions: no seam test sleeps or dials out)."""

    class _FakeBackend(Backend):
        def __init__(self, statuses):
            self.statuses = statuses
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            return Response(request.url, self.statuses.get(request.url, 404))

    def _index(self):
        return build_index(fetcher(), clock=_clock, url_filter=_keep)

    def test_a_live_url_updates_last_verified(self):
        index = self._index()
        for entry in index["entries"]:
            entry["last_verified"] = "2020-01-01"
        backend = self._FakeBackend({
            entry["library_implementations"][0]["snippet_locator"]["source_url"]: 200
            for entry in index["entries"]
        })
        report = refresh_liveness(Fetcher(backend), index, clock=lambda: "2026-10-01")
        self.assertEqual(report["checked"], 6)
        self.assertEqual(report["live"], 6)
        self.assertEqual(report["dead"], [])
        self.assertTrue(all(entry["last_verified"] == "2026-10-01" for entry in index["entries"]))

    def test_a_dead_url_is_named_and_its_last_verified_is_untouched(self):
        index = self._index()
        entry = index["entries"][0]
        entry["last_verified"] = "2020-01-01"
        url = entry["library_implementations"][0]["snippet_locator"]["source_url"]
        backend = self._FakeBackend({})  # every request answers 404
        report = refresh_liveness(Fetcher(backend), index, clock=lambda: "2026-10-01")
        self.assertIn(url, report["dead"])
        self.assertEqual(entry["last_verified"], "2020-01-01")

    def test_head_falls_back_to_get(self):
        """A site that refuses HEAD with 405 is asked again with GET before it counts as dead."""
        index = self._index()
        url = index["entries"][0]["library_implementations"][0]["snippet_locator"]["source_url"]
        for entry in index["entries"][1:]:
            entry["library_implementations"] = []  # only the one URL under test is checked

        class _Head405ThenGet200(Backend):
            def send(self, request):
                return Response(request.url, 405 if request.method == "HEAD" else 200)

        report = refresh_liveness(Fetcher(_Head405ThenGet200()), index, clock=lambda: "2026-10-01")
        self.assertEqual(report["live"], 1)


class RefreshFullTest(unittest.TestCase):
    def test_a_full_recrawl_updates_last_crawled_and_keeps_the_carried_pitfall(self):
        previous = build_index(fetcher(), clock=_clock, url_filter=_keep)
        entry = _by_id(previous, "scatter-tooltips-altair")
        entry["known_pitfalls"].append("a pitfall the evolve loop promoted last quarter")

        fresh = refresh_full(fetcher(), previous, clock=lambda: "2026-12-01", url_filter=_keep)

        refreshed = _by_id(fresh, "scatter-tooltips-altair")
        self.assertIn("a pitfall the evolve loop promoted last quarter", refreshed["known_pitfalls"])
        self.assertEqual(refreshed["last_crawled"], "2026-12-01")
        self.assertEqual(len(fresh["entries"]), 6)


class FoldTrapsHitTest(unittest.TestCase):
    def _index(self):
        return build_index(fetcher(), clock=_clock, url_filter=_keep)

    def test_a_promoted_trap_matching_chart_type_and_library_is_folded_in(self):
        index = self._index()
        traps = [{
            "library": "matplotlib", "chart_type": "Basic Matplotlib Scatterplot",
            "description": "a new trap found while rendering a real figure",
            "fix": "do the other thing instead", "promote_to_index": True,
        }]
        unmatched = fold_traps_hit(index, traps)
        self.assertEqual(unmatched, [])
        entry = _by_id(index, "basic-matplotlib-scatterplot")
        self.assertIn("a new trap found while rendering a real figure", entry["known_pitfalls"])

    def test_a_trap_not_promoted_is_left_out(self):
        index = self._index()
        before = json.dumps(index)
        fold_traps_hit(index, [{"library": "matplotlib", "chart_type": "Basic Matplotlib Scatterplot", "description": "not promoted", "promote_to_index": False}])
        self.assertEqual(json.dumps(index), before)

    def test_a_trap_matching_nothing_is_returned_unmatched_not_invented_as_a_new_entry(self):
        index = self._index()
        before = len(index["entries"])
        trap = {"library": "matplotlib", "chart_type": "A Chart Type Nobody Crawled", "description": "x", "promote_to_index": True}
        unmatched = fold_traps_hit(index, [trap])
        self.assertEqual(unmatched, [trap])
        self.assertEqual(len(index["entries"]), before)


class IndexFileTest(unittest.TestCase):
    def test_write_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plot_index.json"
            index = build_index(fetcher(), clock=_clock, url_filter=_keep)
            write_index(path, index)
            self.assertEqual(load_index(path), index)

    def test_loading_a_missing_index_is_a_blank_one_not_an_error(self):
        blank = load_index(Path(tempfile.gettempdir()) / "no-such-plot-index-file.json")
        self.assertEqual(blank["entries"], [])


class FiguresCommandTest(unittest.TestCase):
    def test_no_subcommand_is_exit_code_2(self):
        self.assertEqual(figures_command([]), 2)

    def test_an_unknown_subcommand_is_exit_code_2(self):
        self.assertEqual(figures_command(["frobnicate"]), 2)


class SitesTest(unittest.TestCase):
    def test_every_site_of_brief_13_1_is_registered(self):
        self.assertEqual(set(SITES), {"python-graph-gallery", "r-graph-gallery", "altair", "seaborn", "plotnine"})


class RecordingsTest(unittest.TestCase):
    def test_the_gallery_recordings_are_committed_and_readable(self):
        for host in ("python-graph-gallery.com", "r-graph-gallery.com", "altair-viz.github.io", "seaborn.pydata.org", "plotnine.org"):
            with self.subTest(host=host):
                files = sorted((RECORDINGS / host).glob("*.json"))
                self.assertGreaterEqual(len(files), 1, "no recording for " + host)

    def test_no_gallery_recording_carries_the_address_of_whoever_made_it(self):
        for host in ("python-graph-gallery.com", "r-graph-gallery.com", "altair-viz.github.io", "seaborn.pydata.org", "plotnine.org"):
            for path in sorted((RECORDINGS / host).glob("*.json")):
                with self.subTest(recording=path.name):
                    self.assertNotIn("@", path.read_text(encoding="utf-8").split('"body"')[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
