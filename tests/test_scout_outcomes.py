"""The scout's outcomes, its cache, and the arXiv abs-page fallback (ticket 71, Implementation Decision 17).

Every lookup here goes through the fetch seam: the network is `tests.scout_net.Net`, scripted by
URL, and the recordings are synthetic ones `tests.scout_net.recorded` makes. Nothing reaches the network.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.scout_net import DOI, EMAIL, EMPTY_EUROPEPMC, NOT_FOUND, NOW, Net, crossref_work, recorded
from wayline.fetch import AnswerCache, DirectoryBackend, FetchError, Fetcher, recording_fetcher
from wayline.scout import FAILED, FOUND, NO_MATCH, NO_SUCH_WORK, Scout, outcome, parse_reference

CROSSREF_WORK = crossref_work()[1]
EMPTY_EUROPEPMC = EMPTY_EUROPEPMC[1]


def scout_over(answers, clock=lambda: NOW):
    net = Net(answers)
    return Scout(Fetcher(net, email=EMAIL), EMAIL, clock=clock), net


def sources(record, wanted):
    return [attempt["source"] for attempt in record["attempts"] if attempt["outcome"] == wanted]


class OutcomesTest(unittest.TestCase):
    def test_a_service_that_knows_the_work_is_found(self):
        scout, _ = scout_over({"api.crossref.org": (200, CROSSREF_WORK), "api.unpaywall.org": NOT_FOUND,
                               "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)})
        record = scout.resolve(parse_reference(DOI))
        self.assertEqual(record["attempts"][0]["outcome"], FOUND)
        self.assertEqual(outcome(record), FOUND)
        self.assertNotIn("retry", record)

    def test_every_service_answering_nothing_is_no_such_work(self):
        scout, _ = scout_over({"api.crossref.org": NOT_FOUND, "api.openalex.org": NOT_FOUND,
                               "api.unpaywall.org": NOT_FOUND, "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)})
        record = scout.resolve(parse_reference(DOI))
        self.assertEqual(sources(record, NO_MATCH), ["crossref", "openalex", "unpaywall", "europepmc"])
        self.assertEqual(outcome(record), NO_SUCH_WORK)
        self.assertNotIn("retry", record)

    def test_an_error_status_a_timeout_and_an_unreadable_answer_are_failures(self):
        scout, _ = scout_over({"api.crossref.org": (503, "Service Unavailable"),
                               "api.openalex.org": FetchError("timed out"),
                               "api.unpaywall.org": (200, "<html>a proxy's page</html>"),
                               "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)})
        record = scout.resolve(parse_reference(DOI))
        self.assertEqual(sources(record, FAILED), ["crossref", "openalex", "unpaywall"])
        self.assertEqual(sources(record, NO_MATCH), ["europepmc"])
        self.assertEqual(outcome(record), FAILED)

    def test_a_failure_on_a_work_not_found_sets_the_retry_flag(self):
        scout, _ = scout_over({"api.crossref.org": (503, "Service Unavailable"), "api.openalex.org": NOT_FOUND,
                               "api.unpaywall.org": NOT_FOUND, "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)})
        record = scout.resolve(parse_reference(DOI))
        self.assertEqual(record["retry"]["service"], "crossref")
        self.assertIn("503", record["retry"]["failure"])
        self.assertEqual(record["retry"]["date"], "2026-09-21T14:13:20.000Z")

    def test_a_failure_while_filling_in_a_found_work_sets_no_flag(self):
        scout, _ = scout_over({"api.crossref.org": (200, CROSSREF_WORK), "api.unpaywall.org": (500, "oops"),
                               "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)})
        record = scout.resolve(parse_reference(DOI))
        self.assertEqual(outcome(record), FOUND)
        self.assertNotIn("retry", record)


ARXIV_ID = "2304.02443"
ABS_PAGE = """<!DOCTYPE html><html><head><title>[2304.02443] Physics-informed flows</title>
<meta name="citation_title" content="Physics-informed flows on manifolds" />
<meta name="citation_author" content="Noether, Emmy" />
<meta name="citation_author" content="Hilbert, David" />
<meta name="citation_date" content="2023/04/05" />
<meta name="citation_online_date" content="2023/04/06" />
<meta name="citation_pdf_url" content="https://arxiv.org/pdf/2304.02443" />
<meta name="citation_arxiv_id" content="2304.02443" />
<meta name="citation_abstract" content="We learn flows that respect the physics." />
</head><body></body></html>"""
EMPTY_FEED = ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
              '<title>arXiv Query</title></feed>')


class AbsPageTest(unittest.TestCase):
    def setUp(self):
        self.root, recorder = recorded({"export.arxiv.org": (503, "Service Unavailable"), "arxiv.org/abs/": (200, ABS_PAGE)})
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        Scout(recorder, EMAIL, clock=lambda: NOW).resolve(parse_reference("arXiv:" + ARXIV_ID))
        self.fetcher = recording_fetcher(self.root, email=EMAIL)
        self.record = Scout(self.fetcher, EMAIL, clock=lambda: NOW).resolve(parse_reference("arXiv:" + ARXIV_ID))

    def test_the_recorded_503_sits_beside_the_abs_page(self):
        statuses = sorted(json.loads(path.read_text(encoding="utf-8"))["response"]["status"] for path in self.root.rglob("*.json"))
        self.assertEqual(statuses, [200, 503])

    def test_a_failed_api_is_followed_by_the_abs_page_as_an_attempt_of_its_own(self):
        attempts = [(attempt["source"], attempt["outcome"], attempt["status"]) for attempt in self.record["attempts"]]
        self.assertEqual(attempts, [("arxiv", FAILED, 503), ("arxiv", FOUND, 200)])
        self.assertIn("arxiv.org/abs/" + ARXIV_ID, self.record["attempts"][1]["url"])
        self.assertEqual(self.fetcher.hosts, ["export.arxiv.org", "arxiv.org"])

    def test_the_work_is_found_from_the_meta_tags_with_the_arxiv_doi(self):
        self.assertEqual(outcome(self.record), FOUND)
        self.assertEqual(self.record["resolved_by"], "arxiv")
        self.assertEqual(self.record["identifiers"]["doi"], "10.48550/arXiv." + ARXIV_ID)
        self.assertEqual(self.record["identifiers"]["arxiv_id"], ARXIV_ID)
        self.assertEqual(self.record["metadata"]["title"], "Physics-informed flows on manifolds")
        self.assertEqual(self.record["metadata"]["authors"], ["Emmy Noether", "David Hilbert"])
        self.assertEqual(self.record["metadata"]["year"], 2023)
        self.assertEqual(self.record["abstract"], "We learn flows that respect the physics.")
        self.assertEqual(self.record["open_access"]["pdf_url"], "https://arxiv.org/pdf/2304.02443")

    def test_a_work_found_by_its_abs_page_keeps_the_flag_so_the_api_fills_in_the_rest(self):
        self.assertEqual(self.record["retry"]["service"], "arxiv")
        self.assertIn("503", self.record["retry"]["failure"])

    def test_an_api_that_answers_no_match_sends_nobody_to_the_abs_page(self):
        scout, net = scout_over({"export.arxiv.org": (200, EMPTY_FEED)})
        record = scout.resolve(parse_reference("arXiv:" + ARXIV_ID))
        self.assertEqual(outcome(record), NO_SUCH_WORK)
        self.assertEqual(len(net.asked), 1)

    def test_an_abs_page_that_fails_too_leaves_the_work_unresolved_and_flagged(self):
        scout, _ = scout_over({"export.arxiv.org": FetchError("timed out"), "arxiv.org/abs/": (502, "Bad Gateway")})
        record = scout.resolve(parse_reference("arXiv:" + ARXIV_ID))
        self.assertEqual(outcome(record), FAILED)
        self.assertEqual([attempt["outcome"] for attempt in record["attempts"]], [FAILED, FAILED])
        self.assertEqual(record["retry"]["service"], "arxiv")


class CacheTest(unittest.TestCase):
    """`research/.cache/scout/`: an answer replayed only for a work already found, and nothing written but successes."""

    ANSWERS = {"api.crossref.org": (200, CROSSREF_WORK), "api.unpaywall.org": NOT_FOUND,
               "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wayline-cache-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def scout(self, answers):
        net = Net(answers)
        return Scout(Fetcher(AnswerCache(self.root, net), email=EMAIL), EMAIL, clock=lambda: NOW), net

    def cached_statuses(self):
        return sorted(json.loads(path.read_text(encoding="utf-8"))["response"]["status"] for path in self.root.rglob("*.json"))

    def test_only_successful_answers_are_written(self):
        scout, _ = self.scout({"api.crossref.org": (503, "Service Unavailable"), "api.openalex.org": FetchError("timed out"),
                               "api.unpaywall.org": NOT_FOUND, "www.ebi.ac.uk": (200, EMPTY_EUROPEPMC)})
        scout.resolve(parse_reference(DOI))
        self.assertEqual(self.cached_statuses(), [200], "the 503, the timeout, and the 404 are never written")

    def test_a_work_already_found_is_answered_from_the_cache(self):
        scout, net = self.scout(self.ANSWERS)
        first = scout.resolve(parse_reference(DOI))
        asked = len(net.asked)
        again = scout.resolve(parse_reference(DOI), found=True)
        self.assertEqual(again["metadata"], first["metadata"])
        self.assertEqual(len(net.asked), asked + 1, "only the unpaywall 404, never written, is asked again")

    def test_a_work_not_yet_found_goes_to_the_network_whatever_the_cache_holds(self):
        scout, net = self.scout(self.ANSWERS)
        scout.resolve(parse_reference(DOI))
        asked = len(net.asked)
        scout.resolve(parse_reference(DOI))
        self.assertEqual(len(net.asked), 2 * asked)

    def test_a_failure_an_older_cache_kept_is_never_replayed(self):
        """A v1.0 cache kept failures; copied into a new project, they are asked again."""
        Fetcher(DirectoryBackend(self.root, inner=Net({"api.crossref.org": (503, "down")}), record=True)).fetch(
            "https://api.crossref.org/works/10.5555%2Fwayline.found?mailto=x")
        scout, _ = self.scout(self.ANSWERS)
        record = scout.resolve(parse_reference(DOI), found=True)
        self.assertEqual(record["attempts"][0]["outcome"], FOUND)

    def test_the_projects_scout_fetcher_is_this_cache(self):
        from wayline.dossier import scout_fetcher

        project = Path(tempfile.mkdtemp(prefix="wayline-project-"))
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        fetcher = scout_fetcher(project, email=EMAIL)
        self.assertIsInstance(fetcher.backend, AnswerCache)
        self.assertEqual(fetcher.backend.root, project / "research" / ".cache" / "scout")

    def test_the_plot_gallery_crawl_keeps_only_successful_answers(self):
        crawl = Fetcher(DirectoryBackend(self.root, inner=Net({"seaborn.pydata.org/a": (200, "<html>a</html>"),
                                                                 "seaborn.pydata.org/b": (500, "down")}),
                                         record=True, keep_failures=False))
        crawl.fetch("https://seaborn.pydata.org/a")
        crawl.fetch("https://seaborn.pydata.org/b")
        self.assertEqual(self.cached_statuses(), [200])

    def test_the_figures_cache_is_one_that_keeps_no_failure(self):
        from wayline.figures import index_fetcher

        project = Path(tempfile.mkdtemp(prefix="wayline-project-"))
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        self.assertFalse(index_fetcher(project).backend.keep_failures)

    def test_the_suites_recordings_still_replay_failures(self):
        root, recorder = recorded({"api.crossref.org": (503, "Service Unavailable")})
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        recorder.fetch("https://api.crossref.org/works/x")
        self.assertEqual(recording_fetcher(root).fetch("https://api.crossref.org/works/x").status, 503)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
