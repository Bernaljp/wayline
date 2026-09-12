"""The scout: reading a reference, the resolution chain, and what an unresolved reference becomes.

Every request in this module is answered from `fixtures/fetch/`, recorded against the live
services on 2026-09-12 (see `fixtures/fetch/README.md`). A request nobody recorded raises, so a
test that reached the network would fail rather than pass slowly.
"""

import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from wayline.fetch import recording_fetcher
from wayline.scout import (
    Reference, Scout, ScoutError, TITLE_SIMILARITY, UNRESOLVED, VERIFIED,
    normalize_title, parse_reference, parse_references, resolve, title_similarity,
)

RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"

# The five references the recordings cover, and what each one is there to show.
DOI = "10.1038/s41586-020-2649-2"
TITLE = "Attention Is All You Need"
ARXIV = "arXiv:1706.03762"
PREPRINT_DOI = "10.1101/2020.03.22.002386"
NOWHERE = "A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology"


def scout():
    return Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)


class ParseReferenceTest(unittest.TestCase):
    def test_a_bare_doi(self):
        self.assertEqual(parse_reference(DOI), Reference("doi", DOI))

    def test_a_doi_inside_a_url_or_a_citation(self):
        for text in ("https://doi.org/" + DOI, "https://dx.doi.org/" + DOI, "Harris et al., doi:%s." % DOI):
            with self.subTest(text=text):
                self.assertEqual(parse_reference(text).kind, "doi")
                self.assertEqual(parse_reference(text).value, DOI)

    def test_an_arxiv_id_in_its_several_spellings(self):
        for text in ("arXiv:1706.03762", "arxiv.org/abs/1706.03762", "https://arxiv.org/abs/1706.03762v7", "arXiv 1706.03762"):
            with self.subTest(text=text):
                reference = parse_reference(text)
                self.assertEqual(reference.kind, "arxiv")
                self.assertTrue(reference.value.startswith("1706.03762"))

    def test_an_arxiv_doi_is_read_as_an_arxiv_id(self):
        self.assertEqual(parse_reference("10.48550/arXiv.2106.15928"), Reference("arxiv", "2106.15928"))

    def test_an_old_style_arxiv_id(self):
        self.assertEqual(parse_reference("arXiv:math.GT/0309136").kind, "arxiv")

    def test_a_title_stays_a_title(self):
        self.assertEqual(parse_reference(TITLE), Reference("title", TITLE))

    def test_a_number_in_a_title_is_not_mistaken_for_an_arxiv_id(self):
        reference = parse_reference("Learning rates and the 2019.12345 problem in optimisation")
        self.assertEqual(reference.kind, "title")

    def test_a_url_with_no_identifier_is_a_url(self):
        self.assertEqual(parse_reference("https://example.org/a/paper.html").kind, "url")

    def test_a_bullet_and_a_markdown_link_are_stripped(self):
        self.assertEqual(parse_reference("- [Array programming with NumPy](https://doi.org/%s)" % DOI).value, DOI)
        self.assertEqual(parse_reference("1. %s" % TITLE).value, TITLE)

    def test_a_markdown_link_with_no_identifier_keeps_its_label(self):
        self.assertEqual(parse_reference("- [%s](https://example.org/x)" % TITLE), Reference("title", TITLE))

    def test_an_empty_reference_is_refused(self):
        with self.assertRaises(ScoutError):
            parse_reference("   ")

    def test_a_list_skips_what_it_cannot_read(self):
        references = parse_references(["", DOI, "   ", TITLE])
        self.assertEqual([reference.kind for reference in references], ["doi", "title"])


class TitleSimilarityTest(unittest.TestCase):
    def test_case_punctuation_and_accents_do_not_matter(self):
        self.assertEqual(normalize_title("Attention Is All You Need!"), "attention is all you need")
        self.assertAlmostEqual(title_similarity("Attention Is All You Need", "attention is all you need"), 1.0)

    def test_a_different_paper_falls_below_the_threshold(self):
        """Crossref's top hit for this title is "Is Attention All You Need?", which is another paper."""
        self.assertLess(title_similarity(TITLE, "Is Attention All You Need?"), TITLE_SIMILARITY)

    def test_an_empty_side_scores_zero(self):
        self.assertEqual(title_similarity(TITLE, ""), 0.0)


class ChainTest(unittest.TestCase):
    def test_a_doi_resolves_through_crossref(self):
        record = scout().resolve(parse_reference(DOI))
        self.assertEqual(record["existence"], VERIFIED)
        self.assertEqual(record["resolved_by"], "crossref")
        self.assertEqual(record["identifiers"]["doi"], DOI)
        self.assertEqual(record["metadata"]["title"], "Array programming with NumPy")
        self.assertEqual(record["metadata"]["year"], 2020)
        self.assertIn("Charles R. Harris", record["metadata"]["authors"])
        self.assertIn("Array programming", record["abstract"])

    def test_a_doi_that_crossref_answered_is_not_also_asked_of_openalex(self):
        """OpenAlex keyless is a daily budget, so it is asked only for what nobody else had."""
        chain = scout()
        chain.resolve(parse_reference(DOI))
        self.assertNotIn("api.openalex.org", chain.fetcher.hosts)

    def test_the_pdf_location_comes_from_unpaywall(self):
        record = scout().resolve(parse_reference(DOI))
        self.assertTrue(record["open_access"]["pdf_url"].endswith(".pdf"))
        self.assertTrue(record["open_access"]["is_oa"])
        self.assertEqual([attempt["source"] for attempt in record["attempts"]], ["crossref", "unpaywall"])

    def test_a_title_crossref_answers_wrongly_falls_through_to_openalex(self):
        record = scout().resolve(parse_reference(TITLE))
        self.assertEqual(record["existence"], VERIFIED)
        self.assertEqual(record["resolved_by"], "openalex")
        self.assertEqual(normalize_title(record["metadata"]["title"]), normalize_title(TITLE))
        crossref = [attempt for attempt in record["attempts"] if attempt["source"] == "crossref"][0]
        self.assertEqual(crossref["outcome"], "miss")
        self.assertIn("below", crossref["note"])

    def test_a_resolved_reference_is_not_asked_of_a_source_that_would_add_nothing(self):
        """Each step after the first runs only for a field still empty; the arXiv record has them all."""
        chain = scout()
        chain.resolve(parse_reference(ARXIV))
        self.assertEqual(len(chain.fetcher.requests), 1)

    def test_an_arxiv_id_resolves_through_the_arxiv_api_alone(self):
        chain = scout()
        record = chain.resolve(parse_reference(ARXIV))
        self.assertEqual(record["resolved_by"], "arxiv")
        self.assertEqual(record["identifiers"]["arxiv_id"], "1706.03762")
        self.assertEqual(record["metadata"]["year"], 2017)
        self.assertEqual(record["metadata"]["version"], "7")
        self.assertIn("Transformer", record["abstract"])
        self.assertEqual(chain.fetcher.hosts, ["export.arxiv.org"])

    def test_a_biorxiv_doi_resolves_through_the_preprint_api(self):
        record = scout().resolve(parse_reference(PREPRINT_DOI))
        self.assertEqual(record["resolved_by"], "biorxiv")
        self.assertEqual(record["identifiers"]["doi"], PREPRINT_DOI)
        self.assertEqual(record["metadata"]["container"], "biorxiv")
        self.assertEqual(record["metadata"]["type"], "preprint")
        self.assertIn("SARS-CoV-2", record["metadata"]["title"])
        self.assertIn("coronavirus", record["abstract"])

    def test_the_newest_version_of_a_preprint_is_the_one_recorded(self):
        """The API returns one entry per version, oldest first; an L0 record means the current one."""
        record = scout().resolve(parse_reference(PREPRINT_DOI))
        self.assertEqual(record["metadata"]["version"], "3")

    def test_a_preprint_record_carries_the_journal_doi_it_was_published_under(self):
        record = scout().resolve(parse_reference(PREPRINT_DOI))
        self.assertEqual(record["identifiers"]["published_doi"], "10.1038/s41586-020-2286-9")

    def test_a_preprint_doi_goes_to_the_preprint_api_before_crossref(self):
        chain = scout()
        chain.resolve(parse_reference(PREPRINT_DOI))
        self.assertEqual(chain.fetcher.hosts[0], "api.biorxiv.org")

    def test_a_reference_that_resolves_nowhere_is_unresolved_and_never_fabricated(self):
        record = scout().resolve(parse_reference(NOWHERE))
        self.assertEqual(record["existence"], UNRESOLVED)
        self.assertIsNone(record["resolved_by"])
        self.assertEqual(record["metadata"], {})
        self.assertIsNone(record["abstract"])
        self.assertNotIn("fabricated", str(record))

    def test_an_unresolved_reference_records_every_door_it_knocked_on(self):
        record = scout().resolve(parse_reference(NOWHERE))
        self.assertEqual([attempt["source"] for attempt in record["attempts"]], ["crossref", "openalex", "europepmc"])
        self.assertTrue(all(attempt["outcome"] == "miss" for attempt in record["attempts"]))
        self.assertTrue(all(attempt["status"] == 200 for attempt in record["attempts"]))

    def test_the_whole_chain_asks_semantic_scholar_nothing(self):
        """Keyless Semantic Scholar returns 429 on the first call (note 06), so it is not in the chain."""
        chain = scout()
        for text in (DOI, TITLE, ARXIV, PREPRINT_DOI, NOWHERE):
            chain.resolve(parse_reference(text))
        self.assertTrue(all("semanticscholar" not in host for host in chain.fetcher.hosts))

    def test_every_request_carries_the_owners_address_in_the_user_agent(self):
        chain = scout()
        chain.resolve(parse_reference(DOI))
        self.assertTrue(chain.fetcher.requests)
        for request in chain.fetcher.requests:
            self.assertEqual(request.headers["User-Agent"], "wayline/%s (mailto:%s)" % (chain.fetcher.tag, EMAIL))

    def test_a_url_reference_is_kept_as_a_locator_and_nothing_is_claimed_about_it(self):
        """No keyless service takes a URL, so a title made out of the URL would be an invented one."""
        chain = scout()
        record = chain.resolve(parse_reference("https://example.org/a/paper.html"))
        self.assertEqual(record["existence"], UNRESOLVED)
        self.assertEqual(record["identifiers"]["url"], "https://example.org/a/paper.html")
        self.assertEqual(record["metadata"], {})
        self.assertEqual(chain.fetcher.requests, [])
        self.assertEqual(record["attempts"][0]["outcome"], "skipped")

    def test_resolve_takes_a_string_as_readily_as_a_reference(self):
        record = resolve(DOI, recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)
        self.assertEqual(record["resolved_by"], "crossref")


class NoFabricationTest(unittest.TestCase):
    def test_fabricated_is_never_a_value_the_scout_can_write(self):
        """It may be talked about in the prose; it may never be a string the code can put in a record."""
        for module in ("scout.py", "dossier.py", "kb.py"):
            source = (HARNESS_ROOT / "wayline" / module).read_text(encoding="utf-8")
            with self.subTest(module=module):
                self.assertNotIn('"fabricated"', source)
                self.assertNotIn("'fabricated'", source)

    def test_the_dossier_schema_admits_only_two_existence_values(self):
        from wayline.jsonschema import load_schema

        self.assertEqual(load_schema("dossier")["properties"]["existence"]["enum"], [VERIFIED, UNRESOLVED])


class RecordingsTest(unittest.TestCase):
    def test_the_recordings_are_committed_and_readable(self):
        files = sorted(Path(RECORDINGS).rglob("*.json"))
        self.assertGreaterEqual(len(files), 10, "the recorded chain is missing responses")
        self.assertTrue((RECORDINGS / "README.md").is_file(), "the recordings need the note that says how to remake them")

    def test_no_recording_carries_the_address_of_whoever_made_it(self):
        for path in sorted(Path(RECORDINGS).rglob("*.json")):
            with self.subTest(recording=path.name):
                self.assertNotIn("@", path.read_text(encoding="utf-8").split('"body"')[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
