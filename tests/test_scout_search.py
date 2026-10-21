"""`wayline scout search`: the literature searched for a `lit` ticket (decision 17; ticket 99).

The seam is the fetch seam's recordings (`tests.scout_net.recorded`: a scripted network recorded once into a
directory, which then replays) and the ledger over a temporary project. What is asserted is what the search
returns and prints, which services it asked, and what the journal holds after: the per-ticket count and the
day's OpenAlex requests.
"""

import contextlib
import io
import json
import os
import time
import unittest
from unittest import mock

from tests.projects import ProjectTestCase
from tests.scout_net import DOWN, EMAIL, Net, recorded
from wayline import cli, survey
from wayline.dossier import l0_dossier, write_l0
from wayline.fetch import Fetcher
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.scout import timestamp

QUERY = "label noise interaction terms"


def arxiv_feed(*entries):
    """An arXiv Atom feed of `(arxiv id, title, year)` entries."""
    items = "".join(
        '<entry><id>http://arxiv.org/abs/%s</id><title>%s</title><published>%d-01-01T00:00:00Z</published>'
        '<summary>About %s.</summary><author><name>Grace Hopper</name></author></entry>' % (identifier, title, year, title)
        for identifier, title, year in entries)
    return (200, '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">%s</feed>' % items)


def crossref_items(*items):
    """A Crossref `query.bibliographic` answer of `(doi, title, year)` items."""
    return (200, json.dumps({"status": "ok", "message": {"items": [
        {"DOI": doi, "title": [title], "author": [{"given": "Ada", "family": "Lovelace"}], "issued": {"date-parts": [[year]]},
         "container-title": ["Journal of Tests"], "type": "journal-article"} for doi, title, year in items]}}))


def europepmc_results(*items):
    """A Europe PMC search answer of `(doi or None, title, year, pmid)` results."""
    return (200, json.dumps({"resultList": {"result": [
        {"doi": doi, "title": title, "pubYear": str(year), "pmid": pmid, "authorString": "Curie M, Noether E.",
         "journalTitle": "Biomed Tests"} for doi, title, year, pmid in items]}}))


def openalex_results(*items):
    """An OpenAlex `works` answer of `(W id, doi or None, title, year)` results."""
    return (200, json.dumps({"results": [
        {"id": "https://openalex.org/%s" % identifier, "doi": "https://doi.org/%s" % doi if doi else None, "display_name": title,
         "publication_year": year, "authorships": [{"author": {"display_name": "Emmy Noether"}}],
         "primary_location": {"source": {"display_name": "Annals of Tests"}}} for identifier, doi, title, year in items]}))


EMPTY = {"export.arxiv.org": arxiv_feed(), "api.crossref.org": crossref_items(), "www.ebi.ac.uk": europepmc_results(),
         "api.openalex.org": openalex_results()}


def answers(**given):
    """The four services, each answering nothing unless `given` scripts it (by host, its dots as underscores)."""
    scripted = dict(EMPTY)
    scripted.update({host.replace("_", "."): answer for host, answer in given.items()})
    return scripted


class SearchCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)
        for identifier in (3, 7, 8):  # the `lit` tickets the searches are counted under; a search is theirs alone
            self.write_ticket(identifier, "lit")

    def write_ticket(self, identifier, kind):
        from wayline.tickets import write_ticket
        write_ticket(self.ledger, {"id": identifier, "title": "Ticket %d" % identifier, "kind": kind, "difficulty": 2, "status": "running",
                                   "blocked_by": [], "touches": [], "role": "surveyor" if kind == "lit" else "coder", "skills": [],
                                   "acceptance": {"machine": [], "quality": []}, "context_pack": [], "origin": None,
                                   "proposed_by": "planner", "demo": "passages"}, "## Demo\n\npassages\n")

    def search(self, scripted, query=QUERY, ticket=7, citing=None, clock=time.time):
        _, fetcher = recorded(scripted)
        self.fetcher = fetcher
        return survey.search(self.project, query, ticket=ticket, citing=citing, fetcher=fetcher, email=EMAIL, clock=clock)

    def hosts(self):
        return [request.host for request in self.fetcher.requests]

    def searched(self):
        return [event for event in self.ledger.read_events()[0] if event["event"] == "scout_searched"]


class ServicesTest(SearchCase):
    """A search asks arXiv, Crossref, and Europe PMC, then OpenAlex, and returns every work they found, each once."""

    def setUp(self):
        super().setUp()
        self.report = self.search(answers(
            export_arxiv_org=arxiv_feed(("2101.00001v2", "Noisy labels and products", 2021)),
            api_crossref_org=crossref_items(("10.5555/a", "Interaction terms under noise", 2019), ("10.5555/b", "Robust AUROC", 2020)),
            www_ebi_ac_uk=europepmc_results(("10.5555/A", "Interaction terms under noise", 2019, "111"), (None, "Label flips in trials", 2018, "222")),
            api_openalex_org=openalex_results(("W9", None, "Noisy labels and products", 2021), ("W8", "10.5555/c", "Pairwise features", 2022)),
        ))

    def test_it_asks_each_service_once_and_openalex_last(self):
        self.assertEqual(self.hosts(), ["export.arxiv.org", "api.crossref.org", "www.ebi.ac.uk", "api.openalex.org"])
        self.assertEqual({name: entry["outcome"] for name, entry in self.report["services"].items()},
                         {"arxiv": "found", "crossref": "found", "europepmc": "found", "openalex": "found"})

    def test_every_work_found_is_listed_once_with_an_identifier_the_scout_takes(self):
        self.assertEqual([(work["identifier"], work["title"], work["year"]) for work in self.report["works"]], [
            ("arxiv:2101.00001", "Noisy labels and products", 2021),
            ("doi:10.5555/a", "Interaction terms under noise", 2019),
            ("doi:10.5555/b", "Robust AUROC", 2020),
            ("Label flips in trials", "Label flips in trials", 2018),
            ("doi:10.5555/c", "Pairwise features", 2022),
        ])
        self.assertEqual(self.report["works"][1]["sources"], ["crossref", "europepmc"])
        self.assertEqual(self.report["works"][0]["sources"], ["arxiv", "openalex"])

    def test_it_is_journaled_and_counted_under_the_ticket(self):
        [event] = self.searched()
        self.assertEqual((event["ticket"], event["payload"]), (7, {"query": QUERY, "citing": None, "works": 5, "openalex": 1}))
        self.assertEqual((self.report["asked"], self.report["limit"]), (1, 20))

    def test_it_files_no_dossier(self):
        self.assertEqual(list((self.project / "research" / "refs").glob("*/dossier.json")), [])


class LitOnlyTest(SearchCase):
    """A search is the surveyor's: whatever role's tools reach the verb, a ticket that is not `lit` is refused before any request."""

    def test_a_code_ticket_is_refused(self):
        self.write_ticket(9, "code")
        with self.assertRaises(survey.SearchRefused) as raised:
            self.search(answers(), ticket=9)
        self.assertIn("ticket 9 is a code ticket", str(raised.exception))
        self.assertEqual(self.hosts(), [])
        self.assertEqual(self.searched(), [])

    def test_a_ticket_the_project_does_not_hold_is_refused(self):
        with self.assertRaises(survey.SearchRefused) as raised:
            self.search(answers(), ticket=40)
        self.assertIn("no ticket the project holds", str(raised.exception))

    def test_a_title_to_scout_is_quoted_for_the_shell(self):
        report = self.search(answers(www_ebi_ac_uk=europepmc_results((None, 'The "hallmarks" of $(cancer)', 2018, "1"))))
        text = survey.render(report)
        self.assertIn("""scout it: wayline scout 'The "hallmarks" of $(cancer)'""", text)


class AlwaysLiveTest(SearchCase):
    def test_a_search_is_asked_of_the_network_every_time_and_never_cached(self):
        net = Net(answers())
        fetcher = Fetcher(net, email=EMAIL)
        for _ in range(2):
            survey.search(self.project, QUERY, ticket=7, fetcher=fetcher, email=EMAIL)
        self.assertEqual(len(net.asked), 8)
        self.assertFalse(any(request.replay for request in fetcher.requests))
        self.assertFalse((self.project / "research" / ".cache" / "scout").exists())

    def test_the_default_fetcher_has_no_cache(self):
        from wayline.fetch import AnswerCache, DirectoryBackend
        fetcher = survey.search_fetcher(EMAIL)
        self.assertNotIsInstance(fetcher.backend, (AnswerCache, DirectoryBackend))


class FailureTest(SearchCase):
    def test_a_service_that_fails_is_reported_and_the_others_still_answer(self):
        report = self.search(answers(api_crossref_org=DOWN, www_ebi_ac_uk=europepmc_results(("10.5555/a", "Interaction terms", 2019, "1"))))
        self.assertEqual(report["services"]["crossref"], {"outcome": "failed", "works": 0, "note": "status 503"})
        self.assertEqual(report["services"]["arxiv"]["outcome"], "no match")
        self.assertEqual([work["identifier"] for work in report["works"]], ["doi:10.5555/a"])


class CapTest(SearchCase):
    def test_a_ticket_is_refused_past_its_twenty_searches_before_any_request(self):
        for _ in range(20):
            self.ledger.append_event("scout_searched", {"query": "q", "citing": None, "works": 0, "openalex": 0}, ticket=7)
        with self.assertRaises(survey.SearchRefused) as raised:
            self.search(answers())
        self.assertIn("policy.scout.searches_per_ticket (20)", str(raised.exception))
        self.assertEqual(self.hosts(), [])
        self.assertEqual(len(self.searched()), 20)

    def test_another_ticket_and_an_uncounted_search_are_not_held_by_it(self):
        for _ in range(20):
            self.ledger.append_event("scout_searched", {"query": "q", "citing": None, "works": 0, "openalex": 0}, ticket=7)
        self.assertEqual(self.search(answers(), ticket=8)["asked"], 1)
        report = self.search(answers(), ticket=None)
        self.assertIsNone(report["asked"])
        self.assertIsNone(self.searched()[-1]["ticket"])

    def test_the_cap_is_the_policys(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness.setdefault("policy", {}).setdefault("scout", {})["searches_per_ticket"] = 2
        (self.project / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        self.search(answers())
        self.search(answers())
        with self.assertRaises(survey.SearchRefused):
            self.search(answers())


class OpenAlexDayTest(SearchCase):
    """OpenAlex costs USD 0.001 a request: code counts the day's requests from the journal and stops at 100."""

    def spend(self, count, ts=None):
        self.ledger.append_event("scout_searched", {"query": "q", "citing": None, "works": 0, "openalex": count}, ticket=3, ts=ts)

    def test_openalex_is_not_asked_once_the_days_hundred_are_spent(self):
        self.spend(60)
        self.spend(40)
        report = self.search(answers())
        self.assertNotIn("api.openalex.org", self.hosts())
        self.assertEqual(report["services"]["openalex"]["outcome"], "skipped")
        self.assertIn("100 OpenAlex requests", report["services"]["openalex"]["note"])
        self.assertEqual(report["openalex"], {"asked": 0, "today": 100, "limit": 100})
        self.assertEqual(self.searched()[-1]["payload"]["openalex"], 0)

    def test_yesterdays_requests_do_not_count(self):
        yesterday = timestamp(time.time() - 86400)
        self.spend(100, ts=yesterday)
        report = self.search(answers())
        self.assertIn("api.openalex.org", self.hosts())
        self.assertEqual(report["openalex"], {"asked": 1, "today": 1, "limit": 100})

    def test_the_last_request_of_the_day_is_still_asked(self):
        self.spend(99)
        self.assertEqual(self.search(answers())["openalex"], {"asked": 1, "today": 100, "limit": 100})


SEED = "10.5555/seed"


class CitingTest(SearchCase):
    """The works that cite a seed: Europe PMC's citations by the seed's PMID, and OpenAlex's `cites:` by its OpenAlex id."""

    def file_seed(self, **identifiers):
        record = {"schema_version": 1, "query": {"kind": "doi", "value": SEED, "raw": SEED}, "existence": "verified",
                  "resolved_by": "crossref", "identifiers": dict({"doi": SEED}, **identifiers),
                  "metadata": {"title": "The seed", "authors": ["Ada Lovelace"], "year": 2015}, "abstract": "Seeded.",
                  "open_access": {}, "attempts": []}
        write_l0(self.ledger, l0_dossier(record, "lovelace-2015-seed"))

    def test_a_filed_seed_is_followed_through_both_services(self):
        self.file_seed(pmid="12345", openalex="https://openalex.org/W77")
        report = self.search({
            "MED/12345/citations": (200, json.dumps({"citationList": {"citation": [
                {"id": "999", "source": "MED", "title": "Citing in trials", "authorString": "Curie M.", "pubYear": 2020}]}})),
            "filter=cites%3AW77": openalex_results(("W5", "10.5555/later", "A later work", 2023)),
        }, query=None, citing=SEED)
        self.assertEqual(report["citing"], SEED)
        self.assertEqual([work["identifier"] for work in report["works"]], ["Citing in trials", "doi:10.5555/later"])
        self.assertEqual(self.hosts(), ["www.ebi.ac.uk", "api.openalex.org"])
        self.assertEqual(self.searched()[-1]["payload"], {"query": None, "citing": SEED, "works": 2, "openalex": 1})

    def test_a_seed_no_dossier_holds_is_resolved_live_and_not_filed(self):
        report = self.search({
            "api.crossref.org/works/10.5555": (200, json.dumps({"status": "ok", "message": {
                "DOI": SEED, "title": ["The seed"], "issued": {"date-parts": [[2015]]}}})),
            "api.openalex.org/works/doi": (200, json.dumps({"id": "https://openalex.org/W77", "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345"},
                                                            "display_name": "The seed"})),
            "MED/12345/citations": (200, json.dumps({"citationList": {"citation": []}})),
            "filter=cites%3AW77": openalex_results(("W5", "10.5555/later", "A later work", 2023)),
            "api.unpaywall.org": (404, "{}"), "www.ebi.ac.uk/europepmc/webservices/rest/search": europepmc_results(),
        }, query=None, citing=SEED)
        self.assertEqual([work["identifier"] for work in report["works"]], ["doi:10.5555/later"])
        self.assertEqual(list((self.project / "research" / "refs").glob("*/dossier.json")), [])

    def test_a_seed_nothing_knows_finds_nothing_and_says_so(self):
        report = self.search({"": (404, "{}")}, query=None, citing="10.5555/nothing")
        self.assertEqual(report["works"], [])
        self.assertIn("no service knows the seed", report["note"])

    def test_a_url_is_refused_as_a_seed(self):
        with self.assertRaises(survey.SearchError):
            self.search(answers(), query=None, citing="https://example.org/paper")

    def test_a_search_names_a_query_or_a_seed(self):
        with self.assertRaises(survey.SearchError):
            self.search(answers(), query="  ", citing=None)


class VerbTest(SearchCase):
    def run_verb(self, *args, ticket="7"):
        out, err = io.StringIO(), io.StringIO()
        _, fetcher = recorded(answers(api_crossref_org=crossref_items(("10.5555/a", "Interaction terms under noise", 2019))))
        environment = {"WAYLINE_TICKET": ticket, "WAYLINE_PROJECT": str(self.project)}
        with mock.patch.dict(os.environ, environment), mock.patch.object(survey, "search_fetcher", lambda email=None: fetcher), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["scout", "search", *args])
        return code, out.getvalue(), err.getvalue()

    def test_scout_search_prints_each_work_with_the_identifier_to_scout(self):
        code, out, err = self.run_verb(QUERY)
        self.assertEqual(code, 0, err)
        self.assertIn("doi:10.5555/a", out)
        self.assertIn("Interaction terms under noise", out)
        self.assertIn("wayline scout", out)
        self.assertIn("searches    1 of 20 made by ticket 7", out)

    def test_the_json_form_is_the_report(self):
        code, out, _ = self.run_verb(QUERY, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["works"][0]["identifier"], "doi:10.5555/a")

    def test_the_citing_form(self):
        code, out, err = self.run_verb("--citing", "arxiv:2101.00001")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.searched()[-1]["payload"]["citing"], "arxiv:2101.00001")

    def test_past_the_cap_it_exits_1_and_says_why(self):
        for _ in range(20):
            self.ledger.append_event("scout_searched", {"query": "q", "citing": None, "works": 0, "openalex": 0}, ticket=7)
        code, _, err = self.run_verb(QUERY)
        self.assertEqual(code, 1)
        self.assertIn("searches_per_ticket", err)

    def test_scout_with_an_identifier_still_looks_one_work_up(self):
        from wayline import references
        with mock.patch.object(references, "scout", return_value={
                "identifier": "10.5555/a", "outcome": "no such work", "slug": None, "dossier": None, "ticket": 7, "asked": 1,
                "limit": 20}) as called, mock.patch.dict(os.environ, {"WAYLINE_TICKET": "7", "WAYLINE_PROJECT": str(self.project)}), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main(["scout", "10.5555/a"])
        called.assert_called_once()


if __name__ == "__main__":
    unittest.main()
