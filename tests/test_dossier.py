"""L0 dossiers and `wayline absorb --level 0`, over the recorded responses and a fixture intake.

The whole chain runs offline here: the ten references of `fixtures/projects/ten-references/`
resolve out of `fixtures/fetch/`, and what is asserted is what a reader of the project sees
afterwards, the dossiers, the nodes, the query pack, and the journal.
"""

import contextlib
import io
import json
import shutil
import unittest

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import cli
from wayline.dossier import (
    absorb_level_0, intake_references, l0_dossier, read_intake, slug_for, write_l0,
)
from wayline.fetch import Request, recording_fetcher
from wayline.jsonschema import ValidationError, load_schema, validate
from wayline.kb import QUERY_PACK, read_nodes
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.scout import Scout, UNRESOLVED, VERIFIED, parse_reference

RECORDINGS = FIXTURES_DIR / "fetch"
SAMPLE = FIXTURES_DIR / "projects" / "ten-references"
EMAIL = "owner@example.org"


class IntakeTest(unittest.TestCase):
    def test_the_sample_intake_names_ten_references(self):
        references = intake_references((SAMPLE / "research" / "INTAKE.md").read_text(encoding="utf-8"))
        self.assertEqual(len(references), 10)
        self.assertEqual([reference.kind for reference in references].count("doi"), 4)
        self.assertEqual([reference.kind for reference in references].count("arxiv"), 3)
        self.assertEqual([reference.kind for reference in references].count("title"), 3)

    def test_the_prose_around_the_list_is_not_a_reference(self):
        """An intake introduces its list in a sentence; looking that sentence up would be a request wasted."""
        text = "## References\n\nThe list is written the way an owner writes one:\n\n- 10.1038/s41586-020-2649-2\n"
        self.assertEqual([reference.value for reference in intake_references(text)], ["10.1038/s41586-020-2649-2"])

    def test_a_bare_list_with_no_bullets_is_still_a_list(self):
        text = "## References\n\n10.1038/s41586-020-2649-2\narXiv:1706.03762\n"
        self.assertEqual([reference.kind for reference in intake_references(text)], ["doi", "arxiv"])

    def test_only_the_references_section_is_read(self):
        text = "## The intent\n\n- 10.9999/not-a-reference\n\n## References\n\n- arXiv:1706.03762\n\n## Constraints\n\n- 10.8888/nor-this\n"
        self.assertEqual([reference.value for reference in intake_references(text)], ["1706.03762"])

    def test_an_owner_who_has_no_references_is_not_looked_up(self):
        self.assertEqual(intake_references("## References\n\nNone. A fixture that needed a dossier would not be a fixture.\n"), [])
        self.assertEqual(intake_references("## References\n\n- None\n"), [])
        self.assertEqual(intake_references("## References\n\n- n/a\n"), [])

    def test_a_title_that_merely_begins_with_none_is_still_looked_up(self):
        """"None" closing a sentence is the owner's answer; "Nothing" running on is a paper's title."""
        text = "## References\n\n- Nothing is learned twice: replay and the sample complexity of control\n"
        self.assertEqual([reference.kind for reference in intake_references(text)], ["title"])

    def test_a_reference_line_with_an_identifier_is_read_whatever_word_it_opens_with(self):
        text = "## References\n\n- None of the above, arXiv:1706.03762\n"
        self.assertEqual([reference.value for reference in intake_references(text)], ["1706.03762"])

    def test_a_reference_named_twice_is_resolved_once(self):
        text = "## References\n\n- 10.1038/s41586-020-2649-2\n- https://doi.org/10.1038/s41586-020-2649-2\n"
        self.assertEqual(len(intake_references(text)), 1)

    def test_a_project_with_no_intake_names_no_references(self):
        self.assertEqual(read_intake("/nonexistent/project"), [])


class SlugTest(unittest.TestCase):
    def test_the_slug_is_family_year_and_title_words(self):
        record = {"metadata": {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani", "Noam Shazeer"], "year": 2017}}
        self.assertEqual(slug_for(record), "vaswani-2017-attention-all-you-need")

    def test_a_second_reference_wanting_a_taken_slug_gets_its_own(self):
        record = {"metadata": {"title": "A paper", "authors": ["Ann Lee"], "year": 2020}}
        first = slug_for(record)
        self.assertEqual(slug_for(record, taken={first}), first + "-2")

    def test_an_unresolved_reference_still_gets_a_slug_from_what_the_owner_wrote(self):
        record = {"metadata": {}, "identifiers": {}, "query": {"kind": "title", "value": "A taxonomy of marmalade"}}
        self.assertEqual(slug_for(record), "a-taxonomy-of-marmalade")

    def test_a_slug_is_always_a_node_id_too(self):
        """One string names the dossier's directory and its node, so one function has to accept both."""
        from wayline.kb import node_id

        for record in (
            {"metadata": {"title": "word " * 40, "authors": ["Somebody Withaverylongfamilyname"], "year": 2020}},
            {"metadata": {}, "identifiers": {}, "query": {"kind": "title", "value": "A taxonomy of marmalade " * 6}},
            {"metadata": {"title": "Ünïcödé: a stüdy", "authors": ["Ann Lee"], "year": 1999}},
        ):
            with self.subTest(title=(record["metadata"].get("title") or "")[:30]):
                slug = slug_for(record)
                self.assertEqual(node_id(slug), slug)
                self.assertLessEqual(len(slug), 80)

    def test_a_taken_slug_and_its_neighbour_both_stay_node_ids(self):
        from wayline.kb import node_id

        record = {"metadata": {"title": "word " * 40, "authors": ["Ann Lee"], "year": 2020}}
        first = slug_for(record)
        second = slug_for(record, taken={first})
        self.assertNotEqual(first, second)
        self.assertEqual(node_id(second), second)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.scout = Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)

    def dossier(self, text, slug="a-slug"):
        return l0_dossier(self.scout.resolve(parse_reference(text)), slug)

    def test_a_resolved_reference_becomes_a_level_0_dossier_that_validates(self):
        dossier = self.dossier("10.1038/s41586-020-2649-2")
        self.assertEqual(validate(dossier, load_schema("dossier")), [])
        self.assertEqual(dossier["level"], 0)
        self.assertEqual(dossier["existence"], VERIFIED)
        self.assertEqual(dossier["resolved_by"], "crossref")
        self.assertTrue(dossier["abstract"])

    def test_an_unresolved_reference_becomes_a_dossier_too(self):
        dossier = self.dossier("A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology")
        self.assertEqual(validate(dossier, load_schema("dossier")), [])
        self.assertEqual(dossier["existence"], UNRESOLVED)
        self.assertIsNone(dossier["resolved_by"])
        self.assertTrue(dossier["attempts"], "an unresolved record still shows where the scout looked")

    def test_the_schema_refuses_an_existence_value_it_does_not_know(self):
        dossier = self.dossier("10.1038/s41586-020-2649-2")
        dossier["existence"] = "fabricated"
        self.assertTrue(validate(dossier, load_schema("dossier")))

    def test_a_slug_that_is_not_a_directory_name_is_refused(self):
        with self.assertRaises(ValidationError):
            self.dossier("10.1038/s41586-020-2649-2", slug="Not A Slug")


class WriteTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        (self.project / "research").mkdir(parents=True)
        self.ledger = Ledger(self.project)
        self.scout = Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)

    def write(self, text, slug):
        dossier = l0_dossier(self.scout.resolve(parse_reference(text)), slug)
        write_l0(self.ledger, dossier)
        return dossier

    def test_the_dossier_and_its_node_land_where_the_spec_puts_them(self):
        self.write("arXiv:1706.03762", "vaswani-2017-attention")
        dossier = json.loads((self.project / "research" / "refs" / "vaswani-2017-attention" / "dossier.json").read_text(encoding="utf-8"))
        node = json.loads((self.project / "research" / "kb" / "nodes" / "vaswani-2017-attention.json").read_text(encoding="utf-8"))
        self.assertEqual(dossier["identifiers"]["arxiv_id"], "1706.03762")
        self.assertEqual(node["kind"], "paper")
        self.assertEqual(node["existence"], "verified")
        self.assertEqual(node["year"], 2017)

    def test_the_node_carries_no_abstract(self):
        dossier = self.write("arXiv:1706.03762", "vaswani-2017-attention")
        node = read_nodes(self.ledger)["vaswani-2017-attention"]
        self.assertNotIn(dossier["abstract"][:40], json.dumps(node))

    def test_an_unresolved_reference_is_still_a_node_in_the_graph(self):
        """That a reference was named and resolved nowhere is a fact about the project."""
        self.write("A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology", "nowhere")
        self.assertEqual(read_nodes(self.ledger)["nowhere"]["existence"], "unresolved")

    def test_writing_a_dossier_journals_absorbed(self):
        self.write("arXiv:1706.03762", "vaswani-2017-attention")
        events, _ = self.ledger.read_events()
        absorbed = [event for event in events if event["event"] == "absorbed"]
        self.assertEqual(len(absorbed), 1)
        self.assertEqual(absorbed[0]["payload"], {"slug": "vaswani-2017-attention", "level": 0})


class AbsorbTest(ProjectTestCase):
    """The verb over the sample intake, offline."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "ten-references"
        shutil.copytree(SAMPLE, self.project)
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None)
        self.ledger = Ledger(self.project)

    def absorb(self):
        return absorb_level_0(self.project, fetcher=recording_fetcher(RECORDINGS, email=EMAIL), email=EMAIL)

    def test_ten_references_get_ten_l0_records(self):
        report = self.absorb()
        self.assertEqual(report["references"], 10)
        self.assertEqual(len(report["written"]), 10)
        self.assertEqual(report["problems"], [])
        self.assertEqual(len(list((self.project / "research" / "refs").glob("*/dossier.json"))), 10)

    def test_nine_resolve_and_the_invented_one_does_not(self):
        report = self.absorb()
        self.assertEqual(report["verified"], 9)
        self.assertEqual(report["unresolved"], 1)
        unresolved = [written for written in report["written"] if written["existence"] == UNRESOLVED]
        self.assertIn("marmalade", unresolved[0]["reference"])

    def test_every_dossier_written_validates_against_the_schema(self):
        self.absorb()
        for path in sorted((self.project / "research" / "refs").glob("*/dossier.json")):
            with self.subTest(dossier=path.parent.name):
                self.assertEqual(validate(json.loads(path.read_text(encoding="utf-8")), load_schema("dossier")), [])

    def test_every_resolved_record_names_the_source_that_resolved_it(self):
        report = self.absorb()
        sources = {written["resolved_by"] for written in report["written"] if written["existence"] == VERIFIED}
        self.assertEqual(sources, {"crossref", "openalex", "arxiv", "biorxiv"})

    def test_each_reference_gets_a_node_and_the_query_pack_is_regenerated(self):
        self.absorb()
        nodes = read_nodes(self.ledger)
        self.assertEqual(len(nodes), 10)
        pack = (self.project / "research" / QUERY_PACK).read_text(encoding="utf-8")
        self.assertIn("10 node(s)", pack)
        for identifier in nodes:
            self.assertIn(identifier, pack)

    def test_the_query_pack_carries_no_abstract_from_any_dossier(self):
        self.absorb()
        pack = (self.project / "research" / QUERY_PACK).read_text(encoding="utf-8")
        for path in sorted((self.project / "research" / "refs").glob("*/dossier.json")):
            abstract = json.loads(path.read_text(encoding="utf-8"))["abstract"]
            if abstract:
                with self.subTest(dossier=path.parent.name):
                    self.assertNotIn(abstract[:60], pack)

    def test_a_second_pass_changes_nothing_and_asks_nothing_new(self):
        first = self.absorb()
        fetcher = recording_fetcher(RECORDINGS, email=EMAIL)
        second = absorb_level_0(self.project, fetcher=fetcher, email=EMAIL)
        self.assertEqual([written["slug"] for written in first["written"]], [written["slug"] for written in second["written"]])
        self.assertEqual(len(list((self.project / "research" / "refs").glob("*/dossier.json"))), 10)
        self.assertEqual(fetcher.backend.misses, [])

    def test_the_journal_records_one_absorbed_event_per_reference(self):
        self.absorb()
        events, _ = self.ledger.read_events()
        absorbed = [event for event in events if event["event"] == "absorbed"]
        self.assertEqual(len(absorbed), 10)
        self.assertTrue(all(event["payload"]["level"] == 0 for event in absorbed))

    def test_the_default_fetcher_caches_every_lookup_under_the_projects_scout_cache(self):
        """`research/.cache/scout/` is gitignored, so the cache never dirties the ledger's diff."""
        from wayline.dossier import CACHE, scout_fetcher

        request = Request("https://api.crossref.org/works/10.1/x")
        fetcher = scout_fetcher(self.project, email=EMAIL)
        self.assertEqual(fetcher.backend.root, self.project / "research" / CACHE)
        self.assertTrue(fetcher.backend.record, "a miss must be recorded, or the cache never fills")
        self.assertEqual(
            fetcher.backend.path_for(request),
            self.project / "research" / CACHE / "api.crossref.org" / (request.hash + ".json"),
        )
        self.assertIn("research/.cache/", (self.project / ".gitignore").read_text(encoding="utf-8"))

    def test_a_project_with_no_owner_address_is_told_what_the_polite_pools_lose(self):
        """A project laid out before the address existed still absorbs; it is just not in the pool."""
        harness = self.project / "harness.json"
        stored = json.loads(harness.read_text(encoding="utf-8"))
        stored["owner_email"] = None
        harness.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
        report = absorb_level_0(self.project, fetcher=recording_fetcher(RECORDINGS, email=None))
        self.assertEqual(report["references"], 10)
        self.assertTrue(any("mailto" in note for note in report["notes"]))
        self.assertTrue(any("owner_email" in note for note in report["notes"]))

    def test_a_project_with_an_address_gets_no_such_note(self):
        self.assertEqual(self.absorb()["notes"], [])

    def test_nothing_reaches_the_network(self):
        """The recording backend has no inner backend, so an unrecorded request would raise."""
        fetcher = recording_fetcher(RECORDINGS, email=EMAIL)
        absorb_level_0(self.project, fetcher=fetcher, email=EMAIL)
        self.assertIsNone(fetcher.backend.inner)
        self.assertEqual(fetcher.backend.misses, [])


class VerbTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "ten-references"
        shutil.copytree(SAMPLE, self.project)
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None)

    def run_verb(self, *args):
        """One verb, with its printing kept out of the suite's output; returns the code and the text."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_the_verb_runs_the_pass_over_the_recorded_responses(self):
        code, printed, _ = self.run_verb("absorb", "--level", "0", "--project", str(self.project), "--fixtures", str(RECORDINGS))
        self.assertEqual(code, 0)
        self.assertIn("9 verified, 1 unresolved", printed)
        self.assertEqual(len(list((self.project / "research" / "refs").glob("*/dossier.json"))), 10)

    def test_the_report_comes_back_as_json_when_it_is_asked_for(self):
        code, printed, _ = self.run_verb("absorb", "--project", str(self.project), "--fixtures", str(RECORDINGS), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed)["verified"], 9)

    def test_a_level_that_is_not_built_yet_exits_2_and_says_which_ticket_builds_it(self):
        code, _, complaint = self.run_verb("absorb", "--level", "2", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("tickets 21 to 24", complaint)

    def test_a_level_outside_the_three_is_an_argument_error(self):
        self.assertEqual(self.run_verb("absorb", "--level", "9", "--project", str(self.project))[0], 2)

    def test_the_verb_is_registered_and_built(self):
        self.assertIsNotNone(cli.lookup("absorb").handler)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
