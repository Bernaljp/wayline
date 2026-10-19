"""A ticket's references and the `ref` tags it writes, checked at acceptance (decision 17; ticket 98).

The seams are the ledger over a temporary project (dossiers filed through `wayline.dossier`, read back from
`research/refs/`) and the fetch seam's recordings for the scout the check runs free. What is asserted is what
the check sends back, what it accepts with a flag, and what the project holds after.
"""

import io
import json

from tests import machine
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, hold_the_ladder, patch
from tests.scout_net import DOI, DOWN, EMAIL, NOT_FOUND, NOW, crossref_work, doi_answers, net_fetcher, recorded
from wayline import conductor, provenance, references, worker
from wayline.conductor import Conductor
from wayline.dossier import look_up_one, read_dossier
from wayline.ledger import Ledger
from wayline.project import init_project

OTHER_DOI = "10.5555/wayline.other"


class TagTest(ProjectTestCase):
    def test_a_ref_tag_names_a_work_by_slug_or_by_identifier(self):
        self.assertEqual(provenance.parse_tag("ref:smith-2020#abstract"), ("ref", {"slug": "smith-2020", "locator": "abstract"}))
        self.assertEqual(provenance.parse_tag("ref:doi:10.1038/s41586-020-2649-2#abstract"),
                         ("ref", {"identifier": "doi:10.1038/s41586-020-2649-2", "locator": "abstract"}))
        self.assertEqual(provenance.parse_tag("ref:arxiv:1802.03426#metadata.title"),
                         ("ref", {"identifier": "arxiv:1802.03426", "locator": "metadata.title"}))

    def test_an_inherited_citation_is_an_identifier_tag_with_no_locator(self):
        self.assertEqual(provenance.parse_tag("ref:doi:10.1038/xyz"), ("ref", {"identifier": "doi:10.1038/xyz", "locator": None}))
        self.assertEqual(provenance.parse_tag("ref:smith-2020"), ("ref", None))  # a slug always names its locator

    def test_the_sentence_splitter_reads_an_identifier_tag_as_one(self):
        found = provenance.sentences("The flows are learned {ref:doi:10.1038/xyz#abstract}. Then more.")
        self.assertEqual(found[0].tags, ("ref:doi:10.1038/xyz#abstract",))


class CheckCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)

    def file(self, answers=None, identifier=DOI):
        fetcher, _ = net_fetcher(answers or doi_answers(crossref_work()))
        return look_up_one(self.project, identifier, fetcher=fetcher, email=EMAIL, clock=lambda: NOW)["slug"]

    def check(self, result, answers=None, ticket=5):
        _, fetcher = recorded(answers or {})
        return references.check_references(self.project, ticket, result, fetcher=fetcher, email=EMAIL, clock=lambda: NOW)

    @staticmethod
    def result(text, refs=(), section="introduction"):
        return {"ticket_id": 5, "status": "done", "summary": "wrote it",
                "passages": [{"section": section, "heading": "Prior work", "text": text, "replaces": None}],
                "references": [dict(item) for item in refs]}

    def slugs(self):
        return sorted(path.parent.name for path in (self.project / "research" / "refs").glob("*/dossier.json"))


class CitedDossierTest(CheckCase):
    def test_a_work_cited_by_its_slug_at_its_abstract_passes_and_stays_at_level_0(self):
        slug = self.file()
        check = self.check(self.result("The flows are learned {ref:%s#abstract}." % slug))
        self.assertEqual(check["problems"], [])
        self.assertEqual(read_dossier(self.ledger, slug)["level"], 0)

    def test_a_work_cited_by_its_doi_maps_through_the_identifier_index(self):
        self.file()
        check = self.check(self.result("The flows are learned {ref:doi:%s#metadata.title}." % DOI))
        self.assertEqual(check["problems"], [])

    def test_a_slug_no_dossier_holds_sends_the_worker_back(self):
        check = self.check(self.result("The flows are learned {ref:ghost-2020-paper#abstract}."))
        self.assertEqual(len(check["problems"]), 1)
        self.assertIn("ghost-2020-paper", check["problems"][0])

    def test_a_work_cited_by_identifier_that_is_neither_a_dossier_nor_listed_sends_the_worker_back(self):
        check = self.check(self.result("The flows are learned {ref:doi:%s#abstract}." % OTHER_DOI))
        self.assertEqual(len(check["problems"]), 1)
        self.assertIn("references", check["problems"][0])


class LocatorTest(CheckCase):
    def test_a_locator_beyond_what_level_0_holds_is_sent_back(self):
        slug = self.file()
        check = self.check(self.result("The method uses warmup {ref:%s#sec-3.2}." % slug))
        self.assertEqual(len(check["problems"]), 1)
        self.assertIn("#sec-3.2", check["problems"][0])
        self.assertIn("promotion", check["problems"][0])

    def test_a_metadata_field_the_dossier_lacks_is_sent_back(self):
        slug = self.file()
        self.assertEqual(len(self.check(self.result("It is cited {ref:%s#metadata.volume}." % slug))["problems"]), 1)

    def test_an_abstract_the_dossier_does_not_hold_is_sent_back(self):
        slug = self.file(doi_answers(crossref_work(abstract="")))
        self.assertEqual(len(self.check(self.result("It is cited {ref:%s#abstract}." % slug))["problems"]), 1)

    def test_at_level_2_an_entrys_locator_is_what_it_holds(self):
        slug = self.file()
        dossier = read_dossier(self.ledger, slug)
        self.ledger.write_json("refs/%s/dossier.json" % slug, dict(dossier, level=2), schema="dossier")
        self.ledger.write_bytes("refs/%s/entries.jsonl" % slug, (json.dumps({"item_id": "eq-1", "locator": "flat.tex:13"}) + "\n").encode())
        self.assertEqual(self.check(self.result("It is cited {ref:%s#flat.tex:13}." % slug))["problems"], [])
        self.assertEqual(len(self.check(self.result("It is cited {ref:%s#flat.tex:99}." % slug))["problems"]), 1)

    def test_a_citation_a_ticket_writes_names_its_locator(self):
        self.file()
        self.assertEqual(len(self.check(self.result("It is cited {ref:doi:%s}." % DOI))["problems"]), 1)


class ListedReferenceTest(CheckCase):
    def test_a_listed_work_no_dossier_holds_is_looked_up_free_filed_and_given_its_note(self):
        check = self.check(self.result("The flows are learned {ref:doi:%s#abstract}." % DOI,
                                       refs=[{"identifier": DOI, "note": "The method we build on."}]), doi_answers(crossref_work()))
        self.assertEqual(check["problems"], [])
        [slug] = self.slugs()
        notes = read_dossier(self.ledger, slug)["notes"]
        self.assertEqual([(note["text"], note["by"]) for note in notes], [("The method we build on.", "ticket 5")])
        self.assertEqual([event for event in self.ledger.read_events()[0] if event["event"] == "scouted"], [], "the check runs free")

    def test_no_such_work_sends_the_worker_back_as_most_likely_invented(self):
        check = self.check(self.result("Nothing cited here.", refs=[{"identifier": OTHER_DOI, "note": ""}]), doi_answers(NOT_FOUND))
        self.assertEqual(len(check["problems"]), 1)
        self.assertIn("most likely invented", check["problems"][0])
        self.assertEqual(self.slugs(), [])

    def test_an_invented_work_listed_and_cited_is_sent_back_once(self):
        check = self.check(self.result("It holds {ref:doi:%s#abstract}." % OTHER_DOI, refs=[{"identifier": OTHER_DOI, "note": ""}]),
                           doi_answers(NOT_FOUND))
        self.assertEqual(len(check["problems"]), 1)

    def test_a_service_failure_accepts_with_the_flag(self):
        check = self.check(self.result("The flows are learned {ref:doi:%s#abstract}." % DOI, refs=[{"identifier": DOI, "note": "n"}]),
                           doi_answers(DOWN, rest=DOWN))
        self.assertEqual(check["problems"], [])
        [slug] = self.slugs()
        self.assertEqual(check["flagged"], [slug])
        self.assertIn("retry", read_dossier(self.ledger, slug))

    def test_a_listed_work_a_dossier_already_holds_is_not_asked_again_and_keeps_the_note(self):
        slug = self.file()
        fetcher, net = net_fetcher({})
        check = references.check_references(self.project, 5, self.result("Cited {ref:%s#abstract}." % slug, refs=[{"identifier": DOI, "note": "Kept."}]),
                                            fetcher=fetcher, email=EMAIL, clock=lambda: NOW)
        self.assertEqual(check["problems"], [])
        self.assertEqual(net.asked, [])
        self.assertEqual(read_dossier(self.ledger, slug)["notes"][0]["by"], "ticket 5")

    def test_a_url_is_refused(self):
        check = self.check(self.result("Nothing cited here.", refs=[{"identifier": "https://example.org/paper", "note": ""}]))
        self.assertEqual(len(check["problems"]), 1)
        self.assertIn("URL", check["problems"][0])

    def test_a_finding_cites_like_a_passage(self):
        result = {"ticket_id": 5, "status": "done", "summary": "s", "findings": [{"text": "It holds {ref:ghost-paper#abstract}.", "provenance": "x.json#a"}]}
        self.assertEqual(len(self.check(result)["problems"]), 1)


class AtAcceptanceTest(ConductorCase):
    """The check runs in the worktree's acceptance: a cited work no dossier holds sends the worker back with the problem."""

    def test_an_invented_citation_sends_the_worker_back_and_a_clean_result_passes(self):
        hold_the_ladder(self)
        cited = {"section": "methods", "heading": "The files", "text": "The file follows a known format {ref:ghost-2020-paper#abstract}.",
                 "replaces": None}
        clean = dict(cited, text="The file holds one line, `hello`.")
        with worker.use_fake() as fake:
            fake.script(done(1, passages=[cited]), patch=patch(), ticket=1)
            fake.script(done(1, passages=[clean]), ticket=1)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            self.conductor.scout_fetcher, _ = net_fetcher({})
            drive(self.conductor)
            calls = list(fake.calls)
        accepted = [event["payload"] for event in self.events("acceptance") if event["ticket"] == 1 and event["payload"]["where"] == "worktree"]
        first, last = accepted[0], accepted[-1]
        self.assertFalse(first["pass"])
        self.assertEqual(first["results"][-1]["cmd"], conductor.REFERENCES_CHECK)
        self.assertIn("ghost-2020-paper", first["results"][-1]["tail"])
        self.assertIn("ghost-2020-paper", [call for call in calls if call.kind == "resume"][0].message)
        self.assertTrue(last["pass"])

    def test_a_result_that_cites_nothing_adds_no_acceptance_line(self):
        with worker.use_fake() as fake:
            fake.script(done(1), patch=patch(), ticket=1)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            drive(self.conductor)
        commands = [result["cmd"] for event in self.events("acceptance") for result in event["payload"]["results"]]
        self.assertNotIn(conductor.REFERENCES_CHECK, commands)


class LintByIdentifierTest(CheckCase):
    def test_the_linter_resolves_an_identifier_tag_through_the_identifier_index(self):
        self.file()
        lint = provenance.lint(self.project, "The flows are learned {ref:doi:%s#abstract}.\n" % DOI.upper(), {})
        self.assertEqual([problem["problem"] for problem in lint.problems if problem["tag"]], [])

    def test_an_identifier_no_dossier_holds_does_not_resolve(self):
        lint = provenance.lint(self.project, "The flows are learned {ref:doi:%s#abstract}.\n" % OTHER_DOI, {})
        self.assertEqual([problem["problem"] for problem in lint.problems if problem["tag"]], ["unresolved_ref"])
