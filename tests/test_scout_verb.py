"""`wayline scout <identifier>`: a worker checks a work mid-ticket (decision 17; ticket 98).

The seams are the fetch seam's recordings (`tests.scout_net.recorded`: a scripted network recorded
once into a directory, which then replays) and the ledger over a temporary project. What is asserted is
what the call returns, what it prints, and what the project holds after: the dossiers and the journal.
"""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.scout_net import DOI, DOWN, EMAIL, NOT_FOUND, NOW, crossref_work, doi_answers, net_fetcher, recorded
from wayline import cli, references, worker
from wayline.dossier import read_dossier
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.scout import UNRESOLVED, VERIFIED


class ScoutCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)

    def scout(self, answers, identifier=DOI, ticket=7, now=NOW):
        _, fetcher = recorded(answers)
        return references.scout(self.project, identifier, ticket=ticket, fetcher=fetcher, email=EMAIL, clock=lambda: now)

    def slugs(self):
        return sorted(path.parent.name for path in (self.project / "research" / "refs").glob("*/dossier.json"))

    def scouted(self):
        return [event for event in self.ledger.read_events()[0] if event["event"] == "scouted"]


class FoundTest(ScoutCase):
    def setUp(self):
        super().setUp()
        self.report = self.scout(doi_answers(crossref_work()))

    def test_it_files_the_l0_dossier_at_once(self):
        self.assertEqual(self.report["outcome"], "found")
        self.assertEqual(self.slugs(), [self.report["slug"]])
        dossier = read_dossier(self.ledger, self.report["slug"])
        self.assertEqual((dossier["existence"], dossier["level"]), (VERIFIED, 0))
        self.assertTrue((self.project / "research" / "kb" / "nodes" / ("%s.json" % self.report["slug"])).is_file())

    def test_it_returns_the_details_and_the_abstract(self):
        self.assertEqual(self.report["dossier"]["metadata"]["title"], "A work the services know")
        self.assertEqual(self.report["dossier"]["abstract"], "What the work found.")

    def test_it_is_counted_under_the_ticket(self):
        self.assertEqual([(event["ticket"], event["payload"]["identifier"], event["payload"]["outcome"], event["payload"]["slug"])
                          for event in self.scouted()], [(7, DOI, "found", self.report["slug"])])
        self.assertEqual((self.report["asked"], self.report["limit"]), (1, 20))

    def test_a_second_call_about_the_same_work_files_no_second_dossier(self):
        again = self.scout(doi_answers(crossref_work()))
        self.assertEqual(again["slug"], self.report["slug"])
        self.assertEqual(self.slugs(), [self.report["slug"]])


class FailureTest(ScoutCase):
    def setUp(self):
        super().setUp()
        self.report = self.scout(doi_answers(DOWN, rest=DOWN))

    def test_a_503_files_an_unresolved_dossier_with_the_retry_flag(self):
        self.assertEqual(self.report["outcome"], "failed")
        dossier = read_dossier(self.ledger, self.report["slug"])
        self.assertEqual(dossier["existence"], UNRESOLVED)
        self.assertEqual((dossier["retry"]["service"], dossier["retry"]["failure"]), ("crossref", "status 503"))

    def test_it_is_counted_as_failed(self):
        self.assertEqual([event["payload"]["outcome"] for event in self.scouted()], ["failed"])


class NoSuchWorkTest(ScoutCase):
    def setUp(self):
        super().setUp()
        self.report = self.scout(doi_answers(NOT_FOUND))

    def test_it_files_nothing(self):
        self.assertEqual((self.report["outcome"], self.report["slug"]), ("no such work", None))
        self.assertEqual(self.slugs(), [])

    def test_it_is_still_counted(self):
        self.assertEqual([(event["payload"]["outcome"], event["payload"]["slug"]) for event in self.scouted()], [("no such work", None)])

    def test_an_exact_title_no_service_knows_files_nothing_either(self):
        empty = json.dumps({"status": "ok", "message": {"items": []}})
        report = self.scout({"api.crossref.org": (200, empty), "api.openalex.org": (200, json.dumps({"results": []})),
                             "www.ebi.ac.uk": (200, json.dumps({"resultList": {"result": []}}))}, identifier="A paper nobody ever wrote about cells")
        self.assertEqual(report["outcome"], "no such work")
        self.assertEqual(self.slugs(), [])


class CapTest(ScoutCase):
    def test_the_twenty_first_call_is_refused_before_any_request(self):
        _, fetcher = recorded(doi_answers(crossref_work()))
        for _ in range(20):
            references.scout(self.project, DOI, ticket=7, fetcher=fetcher, email=EMAIL, clock=lambda: NOW)
        fetcher, net = net_fetcher(doi_answers(crossref_work()))
        with self.assertRaises(references.ScoutRefused) as refused:
            references.scout(self.project, DOI, ticket=7, fetcher=fetcher, email=EMAIL, clock=lambda: NOW)
        self.assertIn("calls_per_ticket", str(refused.exception))
        self.assertEqual(net.asked, [])
        self.assertEqual(len(self.scouted()), 20)

    def test_another_ticket_and_a_call_outside_any_ticket_have_their_own_count(self):
        for _ in range(20):
            self.scout(doi_answers(crossref_work()))
        self.assertEqual(self.scout(doi_answers(crossref_work()), ticket=8)["asked"], 1)
        self.assertIsNone(self.scout(doi_answers(crossref_work()), ticket=None)["asked"])
        self.assertEqual(len(self.scouted()), 21)


class RefusedTest(ScoutCase):
    def test_a_url_is_never_looked_up(self):
        fetcher, net = net_fetcher({})
        with self.assertRaises(references.ReferenceError_):
            references.scout(self.project, "https://openreview.net/forum?id=abc", ticket=7, fetcher=fetcher, email=EMAIL)
        self.assertEqual(net.asked, [])
        self.assertEqual(self.scouted(), [])


class RolesTest(unittest.TestCase):
    def test_the_workers_that_cite_have_the_verb_on_their_allowed_tools(self):
        for name in ("coder", "analyst", "experimenter", "writer"):
            with self.subTest(role=name):
                self.assertIn("Bash(wayline scout *)", worker.read_role(name, HARNESS_ROOT).allowed_tools)

    def test_the_prompt_of_a_role_with_the_verb_says_how_to_cite(self):
        ticket = {"id": 4, "title": "Write the related work", "kind": "writing", "difficulty": 2, "status": "open", "blocked_by": [],
                  "touches": [], "role": "writer", "acceptance": {}, "proposed_by": "planner", "sections": ["introduction"]}
        prompt = worker.assemble_prompt(ticket, worker.read_role("writer", HARNESS_ROOT)).text
        self.assertIn("wayline scout <identifier>", prompt)
        self.assertIn("references", prompt)
        self.assertNotIn("wayline scout", worker.assemble_prompt(dict(ticket, role="integrator"), worker.read_role("integrator", HARNESS_ROOT)).text)


class VerbTest(ScoutCase):
    def run_verb(self, answers, *args, ticket="7"):
        _, fetcher = recorded(answers)
        env = {"WAYLINE_PROJECT": str(self.project), "WAYLINE_TICKET": ticket}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch("wayline.dossier.scout_fetcher", lambda *a, **k: fetcher), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["scout", *args])
        return code, out.getvalue(), err.getvalue()

    def test_the_verb_is_built(self):
        self.assertIsNotNone(cli.lookup("scout").handler)

    def test_it_prints_the_slug_the_details_and_the_abstract(self):
        code, out, err = self.run_verb(doi_answers(crossref_work()), DOI)
        self.assertEqual(code, 0, err)
        slug = self.slugs()[0]
        self.assertIn("slug        %s" % slug, out)
        self.assertIn("{ref:%s#abstract}" % slug, out)
        self.assertIn("A work the services know", out)
        self.assertIn("abstract    What the work found.", out)
        self.assertIn("calls       1 of 20 made by ticket 7", out)

    def test_no_such_work_exits_1_and_says_why(self):
        code, out, _ = self.run_verb(doi_answers(NOT_FOUND), DOI)
        self.assertEqual(code, 1)
        self.assertIn("most likely invented", out)

    def test_a_service_failure_exits_0_and_says_acceptance_takes_it_with_the_flag(self):
        code, out, _ = self.run_verb(doi_answers(DOWN, rest=DOWN), DOI)
        self.assertEqual(code, 0)
        self.assertIn("retry flag", out)

    def test_a_non_numeric_ticket_is_refused(self):
        code, _, err = self.run_verb({}, DOI, ticket="seven")
        self.assertEqual(code, 2)
        self.assertIn("WAYLINE_TICKET", err)

    def test_the_twenty_first_call_exits_1(self):
        for _ in range(20):
            self.assertEqual(self.run_verb(doi_answers(crossref_work()), DOI)[0], 0)
        code, _, err = self.run_verb(doi_answers(crossref_work()), DOI)
        self.assertEqual(code, 1)
        self.assertIn("calls_per_ticket", err)
