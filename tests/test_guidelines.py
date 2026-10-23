"""The venue guidelines (Implementation Decisions 13): the build off recorded pages, and the seven checks.

The build runs against `fixtures/fetch/`, which holds the responses one live run recorded, so the
whole of it, fifteen venues and their supporting pages, runs offline and a page nobody recorded
raises rather than reaching the network. The checks run on the two sample drafts under
`fixtures/manuscripts/`, each against two venues, because the interesting assertion is that one
draft draws different findings from different guidelines.
"""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from wayline import guidelines as venue
from wayline.fetch import FetchError, Response, recording_fetcher
from wayline.jsonschema import load_schema, validate
from wayline.provenance import parse_tag, sentences

MANUSCRIPTS = FIXTURES_DIR / "manuscripts"
MARKDOWN_DRAFT = MANUSCRIPTS / "markdown-draft"
LATEX_DRAFT = MANUSCRIPTS / "latex-draft"

# The day the fixtures were recorded; the build stamps it on every venue whose page answered.
RECORDED_ON = "2026-09-12"


def offline():
    """A fetcher that answers only from the recorded responses."""
    return recording_fetcher(FIXTURES_DIR / "fetch")


class BuiltVenuesTest(unittest.TestCase):
    """One build of every venue, off the recorded pages, shared by the assertions below."""

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="wayline-guidelines-"))
        cls.fetcher = offline()
        cls.report = venue.build(root=cls.directory, fetcher=cls.fetcher, today=RECORDED_ON)
        cls.by_venue = {entry["venue"]: entry for entry in cls.report["venues"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_every_recorded_venue_is_built(self):
        self.assertEqual(self.report["built"], len(venue.VENUES))
        self.assertEqual(
            sorted(self.by_venue),
            sorted(seed["venue"] for seed in venue.VENUES),
        )

    def test_every_venue_writes_its_three_things(self):
        for seed in venue.VENUES:
            with self.subTest(venue=seed["venue"]):
                directory = self.directory / venue.GUIDELINES_DIR / seed["venue"]
                self.assertTrue((directory / venue.GUIDELINES_JSON).is_file())
                self.assertTrue((directory / venue.SOURCE_MD).is_file())
                forms = [form for form in seed["guidelines"]["reporting_checklists"] if form.get("cache_as")]
                for form in forms:
                    self.assertTrue((directory / venue.CHECKLIST_DIR / form["cache_as"]).is_file(),
                                    "%s did not cache %s" % (seed["venue"], form["cache_as"]))

    def test_every_built_file_validates_against_the_schema(self):
        schema = load_schema("guidelines")
        for seed in venue.VENUES:
            with self.subTest(venue=seed["venue"]):
                built = venue.read_guidelines(self.directory, seed["venue"])
                self.assertEqual(validate(built, schema), [])
                self.assertEqual(built["venue"], seed["venue"])

    def test_a_venue_that_answers_is_dated_by_the_build_and_one_that_does_not_keeps_the_note(self):
        self.assertEqual(self.by_venue["plos-compbiol"]["date_checked"], RECORDED_ON)
        self.assertTrue(self.by_venue["plos-compbiol"]["reached"])
        self.assertEqual(self.by_venue["cell"]["date_checked"], venue.NOTE_DATE)
        self.assertFalse(self.by_venue["cell"]["reached"])

    def test_the_four_venues_behind_a_bot_check_verify_nothing(self):
        """Cell, Cell Systems, PNAS and Bioinformatics answer a stateless client with 403."""
        for slug in ("cell", "cell-systems", "pnas", "bioinformatics"):
            with self.subTest(venue=slug):
                built = venue.read_guidelines(self.directory, slug)
                self.assertEqual(built["verification"]["fully_verified_fields"], [])
                self.assertEqual(
                    sorted(built["verification"]["unverified_fields"]),
                    sorted(venue.VERIFIED_FIELDS),
                )
                statuses = {attempt["status"] for attempt in self.by_venue[slug]["attempts"]}
                self.assertEqual(statuses, {403})

    def test_cell_and_genome_biology_are_retried_with_their_alternate_paths(self):
        tried = [attempt["url"] for attempt in self.by_venue["cell"]["attempts"]]
        self.assertGreater(len(tried), 1, "Cell was not retried")
        self.assertEqual(tried[0], venue.venue_seed("cell")["sources"][0]["url"])

        genome = self.by_venue["genome-biology"]
        self.assertTrue(genome["reached"], "the Genome Biology retry no longer answers")
        built = venue.read_guidelines(self.directory, "genome-biology")
        self.assertIn("length_limits", built["verification"]["fully_verified_fields"])
        self.assertIn("required_structure", built["verification"]["fully_verified_fields"])

    def test_a_field_is_verified_only_when_its_wording_is_still_on_the_page(self):
        plos = venue.read_guidelines(self.directory, "plos-compbiol")
        self.assertIn("figure_spec", plos["verification"]["fully_verified_fields"])
        self.assertIn("template", plos["verification"]["unverified_fields"])
        self.assertNotIn("template", plos["verification"]["fully_verified_fields"])

    def test_a_partly_confirmed_field_is_named_by_its_sub_path(self):
        nature = venue.read_guidelines(self.directory, "nature")
        self.assertIn("figure_spec.color_mode", nature["verification"]["unverified_fields"])
        self.assertNotIn("figure_spec", nature["verification"]["fully_verified_fields"])

    def test_every_verification_entry_names_a_field_of_the_file(self):
        for seed in venue.VENUES:
            built = venue.read_guidelines(self.directory, seed["venue"])
            verification = built["verification"]
            with self.subTest(venue=seed["venue"]):
                self.assertEqual(
                    set(verification["fully_verified_fields"]) & {name.split(".")[0] for name in verification["unverified_fields"]},
                    set(),
                    "a field cannot be both verified and not",
                )
                for name in verification["fully_verified_fields"] + verification["unverified_fields"]:
                    self.assertIn(name.split(".")[0], built, "%r is not a field of guidelines.json" % name)

    def test_source_md_says_what_was_fetched_and_why_a_field_is_unverified(self):
        text = (self.directory / venue.GUIDELINES_DIR / "cell" / venue.SOURCE_MD).read_text(encoding="utf-8")
        self.assertIn("https://www.cell.com/cell/information-for-authors", text)
        self.assertIn("403", text)
        self.assertIn("snippet", text)
        self.assertIn("never stored", text)

    def test_no_manuscript_template_is_ever_fetched_or_stored(self):
        templates = {
            seed["guidelines"]["template"]["url"]
            for seed in venue.VENUES if seed["guidelines"]["template"]["url"]
        }
        asked = {request.url for request in self.fetcher.requests}
        self.assertEqual(templates & asked, set(), "the build fetched a manuscript template")
        stored = [path for path in self.directory.rglob("*") if path.suffix.lower() in (".zip", ".docx", ".cls", ".sty")]
        self.assertEqual(stored, [])

    def test_only_checklist_forms_are_cached_and_only_under_checklist(self):
        cached = [path for path in self.directory.rglob("*") if path.suffix.lower() == ".pdf"]
        self.assertTrue(cached, "no checklist form was cached")
        for path in cached:
            with self.subTest(path=path.name):
                self.assertEqual(path.parent.name, venue.CHECKLIST_DIR)
                self.assertTrue(path.read_bytes().startswith(b"%PDF"))
        for built in (venue.read_guidelines(self.directory, "elife"),):
            mdar = [form for form in built["reporting_checklists"] if form["name"] == "MDAR"][0]
            self.assertEqual(mdar["cached_as"], "checklist/elife-mdar-checklist.pdf")

    def test_the_build_is_deterministic(self):
        second = Path(tempfile.mkdtemp(prefix="wayline-guidelines-again-"))
        try:
            venue.build(root=second, fetcher=offline(), today=RECORDED_ON)
            for seed in venue.VENUES:
                with self.subTest(venue=seed["venue"]):
                    left = (self.directory / venue.GUIDELINES_DIR / seed["venue"] / venue.GUIDELINES_JSON).read_text(encoding="utf-8")
                    right = (second / venue.GUIDELINES_DIR / seed["venue"] / venue.GUIDELINES_JSON).read_text(encoding="utf-8")
                    self.assertEqual(left, right)
        finally:
            shutil.rmtree(second, ignore_errors=True)


class BuildRulesTest(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="wayline-guidelines-rules-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def test_a_venue_nobody_recorded_is_refused(self):
        with self.assertRaises(venue.GuidelinesError):
            venue.venue_seed("journal-of-nothing")

    def test_one_venue_can_be_built_alone(self):
        report = venue.build(root=self.directory, fetcher=offline(), venues=["arxiv"], today=RECORDED_ON)
        self.assertEqual([entry["venue"] for entry in report["venues"]], ["arxiv"])
        self.assertTrue((self.directory / venue.GUIDELINES_DIR / "arxiv" / venue.GUIDELINES_JSON).is_file())

    def test_a_page_that_lost_its_wording_unverifies_its_field(self):
        seed = venue.venue_seed("arxiv")

        class Stale:
            requests = []

            def fetch(self, url, headers=None, method="GET"):
                return Response(url, 200, {}, b"<html>arXiv has changed every word of this page.</html>")

        report = venue.build_venue(seed, Stale(), root=self.directory, today=RECORDED_ON)
        self.assertIn("figure_spec", report["unverified_fields"])
        self.assertIn("no longer carries", report["reasons"]["figure_spec"])

    def test_a_request_that_fails_outright_is_recorded_as_an_error(self):
        seed = venue.venue_seed("arxiv")

        class Broken:
            def fetch(self, url, headers=None, method="GET"):
                raise FetchError("the network is down")

        report = venue.build_venue(seed, Broken(), root=self.directory, today=RECORDED_ON)
        self.assertFalse(report["reached"])
        self.assertEqual({attempt["outcome"] for attempt in report["attempts"]}, {"error"})
        self.assertEqual(report["date_checked"], venue.NOTE_DATE)

    def test_checklist_caching_can_be_turned_off(self):
        asked = []

        class Counting:
            def fetch(inner, url, headers=None, method="GET"):
                asked.append(url)
                return Response(url, 200, {}, b"<html>nothing</html>")

        venue.build_venue(venue.venue_seed("elife"), Counting(), root=self.directory,
                          today=RECORDED_ON, cache_checklists=False)
        self.assertNotIn(
            "https://elife-cdn.s3.amazonaws.com/xpub/guides/eLife_MDAR_checklist.pdf", asked)
        self.assertFalse((self.directory / venue.GUIDELINES_DIR / "elife" / venue.CHECKLIST_DIR).exists())

    def test_the_build_asks_for_gzip(self):
        seen = []

        class Watching:
            def fetch(inner, url, headers=None, method="GET"):
                seen.append(dict(headers or {}))
                return Response(url, 200, {}, b"<html>nothing</html>")

        venue.build_venue(venue.venue_seed("iclr"), Watching(), root=self.directory, today=RECORDED_ON)
        self.assertTrue(seen)
        self.assertEqual(seen[0].get("Accept-Encoding"), "gzip")

    def test_a_gzipped_page_is_read_as_text(self):
        import gzip as gzip_module
        body = gzip_module.compress(b"<p>Nine&nbsp;pages&mdash;or fewer.</p>")
        text = venue.page_text(Response("https://example.org", 200, {"content-encoding": "gzip"}, body))
        self.assertEqual(text, "Nine pages—or fewer.")

    def test_script_and_style_never_reach_the_text(self):
        body = b"<style>p{color:red}</style><script>var nine = 9;</script><p>Nine pages.</p>"
        self.assertEqual(venue.page_text(Response("https://example.org", 200, {}, body)), "Nine pages.")


class ShippedGuidelinesTest(unittest.TestCase):
    """What the harness ships under `guidelines/`, built by the live run `docs/verification/m7.md` records."""

    def test_every_recorded_venue_is_on_disk_and_validates(self):
        schema = load_schema("guidelines")
        for seed in venue.VENUES:
            with self.subTest(venue=seed["venue"]):
                built = venue.read_guidelines(HARNESS_ROOT, seed["venue"])
                self.assertEqual(validate(built, schema), [])

    def test_the_shipped_files_hold_no_manuscript_template(self):
        shipped = HARNESS_ROOT / venue.GUIDELINES_DIR
        for path in shipped.rglob("*"):
            if path.is_file():
                with self.subTest(path=str(path.relative_to(shipped))):
                    self.assertNotIn(path.suffix.lower(), (".zip", ".docx", ".cls", ".sty", ".tex"))
                    self.assertIn(path.name, (venue.GUIDELINES_JSON, venue.SOURCE_MD) + tuple(
                        form["cache_as"] for seed in venue.VENUES
                        for form in seed["guidelines"]["reporting_checklists"] if form.get("cache_as")) + tuple(
                        csl for csl, _ in venue.CITATION_STYLES.values() if csl))

    def test_each_venue_names_its_citation_style_and_the_style_is_vendored_beside_it(self):
        """Ticket 118: a compilation cites through the CSL style `reference_style.csl` names, an independent style of the
        Citation Style Language styles, since pandoc reads no dependent one."""
        for seed in venue.VENUES:
            with self.subTest(venue=seed["venue"]):
                style = venue.read_guidelines(HARNESS_ROOT, seed["venue"])["reference_style"]
                self.assertEqual((style["csl"], style["bibtex"]), venue.CITATION_STYLES[seed["venue"]])
                if style["csl"]:
                    text = (HARNESS_ROOT / venue.GUIDELINES_DIR / seed["venue"] / style["csl"]).read_text(encoding="utf-8")
                    self.assertIn('xmlns="http://purl.org/net/xbiblio/csl"', text)
                    self.assertNotIn('rel="independent-parent"', text)
        self.assertEqual(venue.CITATION_STYLES["nature-methods"], ("nature.csl", False))
        self.assertEqual(venue.CITATION_STYLES["neurips"], (None, True))


class ManuscriptTest(unittest.TestCase):
    def test_a_markdown_draft_is_read_section_by_section(self):
        draft = venue.Manuscript(MARKDOWN_DRAFT)
        self.assertEqual(draft.kind, "markdown")
        self.assertIn("Materials and Methods", draft.section_names())
        self.assertEqual(draft.title(), "A sample Markdown draft for the guidelines checks")
        self.assertEqual(draft.abstract_words(), 43)
        self.assertEqual(draft.references(), (2, "numbered"))
        self.assertEqual(draft.study_types(), ["animal", "custom-code", "life-sciences"])

    def test_a_latex_draft_is_read_the_same_way(self):
        draft = venue.Manuscript(LATEX_DRAFT)
        self.assertEqual(draft.kind, "latex")
        self.assertIn("Introduction", draft.section_names())
        self.assertEqual(draft.title(), "A sample LaTeX draft for the guidelines checks")
        self.assertIn("iclr2027_conference", draft.document_classes())
        self.assertEqual(draft.references(), (2, "author-date"))
        self.assertEqual(draft.pdf_pages(), 3)

    def test_the_checklist_directory_is_not_part_of_the_draft(self):
        draft = venue.Manuscript(MARKDOWN_DRAFT)
        self.assertEqual([path.name for path in draft.files], ["paper.md"])
        self.assertIn("arrive-checklist.md", draft.file_names())

    def test_the_venue_s_exclusions_come_off_the_word_count(self):
        draft = venue.Manuscript(MARKDOWN_DRAFT)
        whole = draft.body_words()
        without_methods = draft.body_words(["Materials and Methods"])
        self.assertLess(without_methods, whole)

    def test_a_figure_carries_the_file_it_points_at_and_its_legend(self):
        figures = venue.Manuscript(MARKDOWN_DRAFT).figures()
        self.assertEqual([Path(figure["file"]).name for figure in figures], ["fig1.tif", "fig2.png"])
        self.assertTrue(figures[0]["legend"].startswith("Figure 1."))

    def test_a_directory_with_no_draft_in_it_is_refused(self):
        empty = Path(tempfile.mkdtemp(prefix="wayline-empty-"))
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with self.assertRaises(venue.GuidelinesError):
            venue.Manuscript(empty)
        with self.assertRaises(venue.GuidelinesError):
            venue.Manuscript(empty / "nothing-here")


class ImageFactsTest(unittest.TestCase):
    def test_a_tiff_header_gives_its_resolution_and_colour_mode(self):
        facts = venue.image_facts(MARKDOWN_DRAFT / "figures" / "fig1.tif")
        self.assertEqual((facts["format"], facts["dpi"], facts["color_mode"]), ("TIFF", 300, "RGB"))
        self.assertFalse(facts["vector"])

    def test_a_png_header_gives_its_resolution_and_colour_mode(self):
        facts = venue.image_facts(MARKDOWN_DRAFT / "figures" / "fig2.png")
        self.assertEqual((facts["format"], facts["dpi"], facts["color_mode"]), ("PNG", 72, "RGB"))

    def test_a_vector_file_claims_no_resolution(self):
        facts = venue.image_facts(LATEX_DRAFT / "draft.pdf")
        self.assertTrue(facts["vector"])
        self.assertIsNone(facts["dpi"])

    def test_a_file_that_is_not_there_says_so_rather_than_raising(self):
        facts = venue.image_facts(MARKDOWN_DRAFT / "figures" / "missing.png")
        self.assertIsNone(facts["dpi"])
        self.assertIsNone(facts["size_mb"])


class ChecksTest(unittest.TestCase):
    """The seven checks, on the sample drafts, against two venues each."""

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="wayline-guidelines-checks-"))
        venue.build(root=cls.directory, fetcher=offline(), today=RECORDED_ON, cache_checklists=False)
        cls.guidelines = {
            slug: venue.read_guidelines(cls.directory, slug)
            for slug in ("plos-compbiol", "nature", "iclr", "icml", "nature-communications",
                         "neurips", "genome-biology")
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def findings(self, draft, slug, project=None):
        return venue.run_checks(venue.Manuscript(draft), self.guidelines[slug], project=project)

    def by_check(self, findings, name):
        return [finding for finding in findings if finding.check == name]

    def test_all_seven_checks_run_and_only_the_seven(self):
        findings = self.findings(MARKDOWN_DRAFT, "plos-compbiol")
        self.assertEqual({finding.check for finding in findings}, set(venue.CHECKS))
        self.assertEqual([finding.check for finding in findings],
                         sorted([finding.check for finding in findings], key=venue.CHECKS.index))

    def test_one_draft_two_venues_two_verdicts(self):
        """The same Markdown draft: PLOS refuses its figure, Nature refuses its missing checklist."""
        plos = self.findings(MARKDOWN_DRAFT, "plos-compbiol")
        nature = self.findings(MARKDOWN_DRAFT, "nature")

        self.assertEqual([finding.level for finding in self.by_check(plos, "figures")].count("fail"), 2)
        self.assertTrue(any("fig2.png" in finding.message and "PNG" in finding.message
                            for finding in self.by_check(plos, "figures")))
        self.assertTrue(any("72 dpi" in finding.message for finding in self.by_check(plos, "figures")))
        self.assertEqual(venue.worst(self.by_check(nature, "figures")), "ok")

        self.assertEqual(venue.worst(self.by_check(plos, "reporting_checklists")), "ok")
        self.assertEqual(venue.worst(self.by_check(nature, "reporting_checklists")), "fail")

        self.assertEqual(venue.worst(self.by_check(plos, "structure")), "fail")
        self.assertEqual(venue.worst(self.by_check(nature, "structure")), "warn")

    def test_the_latex_draft_against_the_venue_it_was_written_for_and_one_it_was_not(self):
        iclr = self.findings(LATEX_DRAFT, "iclr")
        icml = self.findings(LATEX_DRAFT, "icml")
        self.assertEqual(venue.worst(self.by_check(iclr, "template")), "ok")
        self.assertEqual(venue.worst(self.by_check(icml, "template")), "fail")
        self.assertTrue(any("icml2026" in finding.message for finding in self.by_check(icml, "template")))
        self.assertTrue(any("3 pages" in finding.message for finding in self.by_check(iclr, "length")))

    def test_a_page_limit_without_a_compiled_pdf_is_skipped_rather_than_guessed(self):
        findings = self.by_check(self.findings(MARKDOWN_DRAFT, "nature"), "length")
        pages = [finding for finding in findings if "page" in finding.message]
        self.assertEqual([finding.level for finding in pages], ["skipped"])

    def structure_of(self, body, slug):
        draft = Path(tempfile.mkdtemp(prefix="wayline-order-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(body, encoding="utf-8")
        return self.by_check(venue.run_checks(draft, self.guidelines[slug]), "structure")

    def test_sections_out_of_order_fail_at_a_venue_that_is_not_structure_flexible(self):
        """Ticket 115: `check_structure` checks the order of the required sections where the venue fixes it."""
        ordered = "".join("## %s\n\nText.\n\n" % name for name in ("Abstract", "Results", "Methods"))
        swapped = "".join("## %s\n\nText.\n\n" % name for name in ("Abstract", "Methods", "Results"))
        self.assertFalse(self.guidelines["nature-communications"]["structure_flexible"])
        self.assertNotIn("order", " ".join(finding.message for finding in self.structure_of("# T\n\n" + ordered, "nature-communications")))
        failed = [finding for finding in self.structure_of("# T\n\n" + swapped, "nature-communications") if "order" in finding.message]
        self.assertEqual([finding.level for finding in failed], ["fail"])
        self.assertIn("Results, Methods", failed[0].message)

    def test_a_subsection_and_a_draft_of_several_files_say_nothing_of_the_order(self):
        sub = "# T\n\n## Abstract\n\nText.\n\n### Methods of others\n\nText.\n\n## Results\n\nText.\n\n## Methods\n\nText.\n"
        self.assertFalse([finding for finding in self.structure_of(sub, "nature-communications") if "order" in finding.message])
        draft = Path(tempfile.mkdtemp(prefix="wayline-parts-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "a-methods.md").write_text("## Methods\n\nText.\n", encoding="utf-8")
        (draft / "b-results.md").write_text("## Results\n\nText.\n", encoding="utf-8")
        found = self.by_check(venue.run_checks(draft, self.guidelines["nature-communications"]), "structure")
        self.assertFalse([finding for finding in found if "order" in finding.message], "files in name order are no sections' order")

    def test_a_structure_flexible_venue_takes_its_sections_in_any_order(self):
        self.assertTrue(self.guidelines["nature"]["structure_flexible"])
        swapped = "# T\n\n## Methods\n\nText.\n\n## Summary paragraph\n\nText.\n"
        self.assertFalse([finding for finding in self.structure_of(swapped, "nature") if "order" in finding.message])

    def test_a_word_count_over_the_limit_fails(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-long-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(
            "# Long\n\n## Introduction\n\n" + ("word " * 6000) + "\n", encoding="utf-8")
        findings = self.by_check(venue.run_checks(draft, self.guidelines["nature"]), "length")
        self.assertEqual(findings[0].level, "fail")
        self.assertIn("over the 4300", findings[0].message)

    def test_a_legend_over_the_cap_fails(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-legend-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "figures").mkdir()
        shutil.copy(MARKDOWN_DRAFT / "figures" / "fig1.tif", draft / "figures" / "fig1.tif")
        (draft / "paper.md").write_text(
            "# Long legend\n\n## Results\n\n![a panel](figures/fig1.tif)\n\nFigure 1. "
            + ("word " * 400) + "\n", encoding="utf-8")
        findings = self.by_check(venue.run_checks(draft, self.guidelines["nature-communications"]), "figures")
        self.assertTrue(any(finding.level == "fail" and "legend" in finding.message for finding in findings))

    def test_a_checklist_is_matched_by_its_acronym_its_whole_name_or_what_it_is_called_in_practice(self):
        self.assertEqual(venue._checklist_keys("ARRIVE"), ["arrive"])
        self.assertEqual(venue._checklist_keys("STROBE-MR"), ["strobemr"])
        self.assertIn("paperchecklist", venue._checklist_keys("NeurIPS Paper Checklist"))
        self.assertIn("minimumstandardsofreporting",
                      venue._checklist_keys("BioMed Central Minimum Standards of Reporting Checklist"))

    def test_every_checklist_a_venue_requires_can_be_matched_by_a_name_someone_would_use(self):
        """A required form no file name could ever match is a check the author cannot pass."""
        for seed in venue.VENUES:
            for form in seed["guidelines"]["reporting_checklists"]:
                if not form["required"]:
                    continue
                with self.subTest(venue=seed["venue"], form=form["name"]):
                    shortest = min(venue._checklist_keys(form["name"]), key=len)
                    self.assertLessEqual(len(shortest), 30, "%r can only be matched by its full title" % form["name"])

    def test_a_checklist_the_draft_carries_as_a_section_counts(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-embedded-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(
            "# Draft\n\n## Results\n\nNothing.\n\n## NeurIPS Paper Checklist\n\nAnswered in full.\n",
            encoding="utf-8")
        findings = self.by_check(venue.run_checks(draft, self.guidelines["neurips"]), "reporting_checklists")
        self.assertEqual(venue.worst(findings), "ok")
        self.assertTrue(any("in the draft" in finding.message for finding in findings))

    def test_a_file_that_merely_shares_a_word_is_not_the_checklist(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-checklist-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(
            "# Draft\n\n## Methods\n\nSequencing libraries were prepared from mouse tissue.\n", encoding="utf-8")
        (draft / "reporting-notes.md").write_text("not a Reporting Summary\n", encoding="utf-8")
        findings = self.by_check(venue.run_checks(draft, self.guidelines["nature"]), "reporting_checklists")
        self.assertEqual(venue.worst(findings), "fail")

    def test_a_venue_that_spells_a_format_tif_accepts_a_file_named_tiff(self):
        """Nature Communications writes TIF and JPG where a file is named .tiff and .jpeg."""
        findings = self.by_check(self.findings(MARKDOWN_DRAFT, "nature-communications"), "figures")
        self.assertFalse(any("fig1.tif is TIFF" in finding.message for finding in findings), findings)
        self.assertEqual(venue._format_name(".tif"), venue._format_name("TIFF"))
        self.assertEqual(venue._format_name(".jpg"), venue._format_name("JPEG"))

    def test_a_latex_table_is_one_display_item_and_not_a_figure(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-table-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "figures").mkdir()
        shutil.copy(LATEX_DRAFT / "figures" / "fig1.png", draft / "figures" / "fig1.png")
        (draft / "draft.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
            "\\begin{figure}\\includegraphics{figures/fig1.png}\\caption{A panel.}\\end{figure}\n"
            "\\begin{table}\\caption{A table.}\\end{table}\n\\end{document}\n", encoding="utf-8")
        manuscript = venue.Manuscript(draft)
        self.assertEqual(len(manuscript.figures()), 1)
        self.assertEqual(manuscript.tables(), 1)
        findings = self.by_check(venue.run_checks(manuscript, self.guidelines["nature-communications"]), "figures")
        self.assertTrue(any("2 display item(s)" in finding.message for finding in findings), findings)
        self.assertFalse(any("not on disk" in finding.message for finding in findings), findings)

    def test_provenance_tags_are_markup_and_not_words(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-tagwords-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(
            "# Tagged\n\n## Results\n\nThe signal held {res:t52-a1/results/metrics.json#auroc}. "
            "It held again {ref:smith-2020#p3}.\n", encoding="utf-8")
        self.assertEqual(venue.Manuscript(draft).body_words(), 6)  # the two sentences, not the tags

    def test_a_draft_given_by_a_relative_path_reads_the_same_files(self):
        here = Path.cwd()
        relative = venue.Manuscript(LATEX_DRAFT.relative_to(here)) if LATEX_DRAFT.is_relative_to(here) else None
        if relative is None:
            self.skipTest("the fixtures are not under the working directory")
        absolute = venue.Manuscript(LATEX_DRAFT)
        self.assertEqual(relative.pdf_pages(), absolute.pdf_pages())
        self.assertEqual(relative.figures()[0]["file"], absolute.figures()[0]["file"])

    def test_a_single_file_draft_carries_no_package(self):
        """`check paper.md` must not drag every .bib and PDF under its directory into the count."""
        draft = venue.Manuscript(MARKDOWN_DRAFT / "paper.md")
        self.assertEqual(draft.file_names(), ["paper.md"])
        self.assertIsNone(draft.pdf_pages())

    def test_an_outline_count_is_not_a_page_count(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-outline-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "draft.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\\section{One}\\end{document}\n", encoding="utf-8")
        (draft / "draft.pdf").write_text(
            "%PDF-1.5\n"
            "1 0 obj\n<< /Type /Catalog /Pages 2 0 R /Outlines 9 0 R >>\nendobj\n"
            "2 0 obj\n<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>\nendobj\n"
            "3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
            "4 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
            "9 0 obj\n<< /Type /Outlines /Count 17 >>\nendobj\n"
            "trailer\n<< /Root 1 0 R >>\n%%EOF\n", encoding="ascii")
        self.assertEqual(venue.Manuscript(draft).pdf_pages(), 2)

    def test_a_malformed_provenance_tag_fails_the_cross_check(self):
        draft = Path(tempfile.mkdtemp(prefix="wayline-tags-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(
            "# Tags\n\n## Results\n\nA claim with a good tag {res:t52-a1/metrics.json#auroc}. "
            "A claim with a broken one {res:nothing-like-a-run-id}.\n", encoding="utf-8")
        findings = self.by_check(venue.run_checks(draft, self.guidelines["nature"]), "provenance")
        self.assertEqual(venue.worst(findings), "fail")
        self.assertTrue(any("malformed" in finding.message for finding in findings))

    def test_the_cross_check_resolves_tags_against_a_project_when_it_is_given(self):
        project = Path(tempfile.mkdtemp(prefix="wayline-project-"))
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        (project / "research").mkdir()
        (project / "research" / "manifest.json").write_text(json.dumps({"entries": [
            {"path": "results/metrics.json", "size": 1, "sha256": "0" * 64,
             "job": None, "run_id": "t52-a1", "ticket": "52", "ts": "2026-09-12T00:00:00.000Z"},
        ]}), encoding="utf-8")
        draft = Path(tempfile.mkdtemp(prefix="wayline-tags-project-"))
        self.addCleanup(shutil.rmtree, draft, ignore_errors=True)
        (draft / "paper.md").write_text(
            "# Tags\n\n## Results\n\nA claim that resolves {res:t52-a1/results/metrics.json#auroc}. "
            "A claim that does not {res:t52-a1/results/nowhere.json#auroc}.\n", encoding="utf-8")
        findings = self.by_check(venue.run_checks(draft, self.guidelines["nature"], project=project), "provenance")
        self.assertEqual(venue.worst(findings), "fail")
        self.assertTrue(any("nowhere.json" in finding.message for finding in findings))
        self.assertFalse(any("metrics.json#auroc}" in finding.message and "resolve to nothing" in finding.message
                             for finding in findings))

    def test_the_checks_read_guidelines_json_and_nothing_else(self):
        """No network, no research note: the file on disk is the whole input."""
        findings = venue.run_checks(MARKDOWN_DRAFT, self.guidelines["plos-compbiol"])
        self.assertTrue(findings)
        with self.assertRaises(venue.GuidelinesError):
            venue.read_guidelines(self.directory, "journal-of-nothing")


class SentencePassTest(unittest.TestCase):
    """The pass `provenance` owns and both halves of the provenance work share."""

    def test_a_sentence_keeps_the_tags_it_ends_with(self):
        found = sentences("The signal held {res:t1-a1/metrics.json#auroc}. Nothing else did.")
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].tags, ("res:t1-a1/metrics.json#auroc",))
        self.assertEqual(found[1].tags, ())

    def test_an_abbreviation_does_not_end_a_sentence(self):
        found = sentences("Fig. 1 shows the curve. The curve is flat.")
        self.assertEqual([sentence.text for sentence in found],
                         ["Fig. 1 shows the curve.", "The curve is flat."])

    def test_nothing_at_all_is_no_sentences_rather_than_a_crash(self):
        """A section body that comes back empty is normal; the linter must not die on it."""
        self.assertEqual(sentences(None), [])
        self.assertEqual(sentences(""), [])

    def test_a_tag_is_parsed_or_refused(self):
        self.assertEqual(parse_tag("ref:smith-2020#p3"), ("ref", {"slug": "smith-2020", "locator": "p3"}))
        self.assertEqual(parse_tag("res:t1-a1/x.json#y")[1]["run_id"], "t1-a1")
        self.assertEqual(parse_tag("res:no-run-id")[1], None)
        self.assertEqual(parse_tag("nonsense"), (None, None))


class CommandTest(unittest.TestCase):
    """The verb, run in process the way the dashboard calls it, with its printing captured."""

    def run_verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = venue.build_command(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_build_writes_where_it_is_told_and_prints_a_line_per_venue(self):
        directory = Path(tempfile.mkdtemp(prefix="wayline-guidelines-cli-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        code, out, _ = self.run_verb(
            "build", "--root", str(directory), "--fixtures", str(FIXTURES_DIR / "fetch"),
            "--venue", "arxiv", "--no-checklists",
        )
        self.assertEqual(code, 0)
        self.assertIn("arxiv", out)
        self.assertTrue((directory / venue.GUIDELINES_DIR / "arxiv" / venue.GUIDELINES_JSON).is_file())

    def test_build_can_print_its_report_as_json(self):
        directory = Path(tempfile.mkdtemp(prefix="wayline-guidelines-cli-json-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        code, out, _ = self.run_verb(
            "build", "--root", str(directory), "--fixtures", str(FIXTURES_DIR / "fetch"),
            "--venue", "arxiv", "--no-checklists", "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["venues"][0]["venue"], "arxiv")

    def test_check_exits_1_when_something_fails_and_0_when_nothing_does(self):
        directory = Path(tempfile.mkdtemp(prefix="wayline-guidelines-cli-check-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        venue.build(root=directory, fetcher=offline(), today=RECORDED_ON, cache_checklists=False)
        failing, failed_out, _ = self.run_verb("check", str(MARKDOWN_DRAFT), "--venue", "plos-compbiol", "--root", str(directory))
        passing, _, _ = self.run_verb("check", str(LATEX_DRAFT), "--venue", "iclr", "--root", str(directory))
        self.assertEqual((failing, passing), (1, 0))
        self.assertIn("FAIL", failed_out)

    def test_an_unknown_venue_is_an_error_not_a_traceback(self):
        code, out, err = self.run_verb("check", str(MARKDOWN_DRAFT), "--venue", "journal-of-nothing")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("journal-of-nothing", err)


if __name__ == "__main__":
    unittest.main()
