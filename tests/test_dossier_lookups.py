"""What a lookup may change in a dossier, the daily retry, and one dossier per work (ticket 71, decision 17).

A project is laid out by `init`, its `INTAKE.md` names references, and `absorb --level 0` runs
over a scripted network (`tests.scout_net`). What is asserted is what the project holds after:
the dossiers, the nodes, the journal, and absorb's report.
"""

import json
from pathlib import Path

from tests.projects import ProjectTestCase
from tests.test_tick import HOUR, TickCase, ts, usage_text
from tests.scout_net import (
    DAY, DOI, DOWN, EMAIL, EMPTY_EUROPEPMC, NOT_FOUND, NOW, TITLE, crossref_work, doi_answers, net_fetcher, title_search,
)
from wayline import tick
from wayline.dossier import (
    GAVE_UP, LEVEL_1, WAITING, DossierError, absorb_level_0, all_slugs, hand_over, read_dossier, retry_flagged, write_l0,
)
from wayline.kb import read_nodes
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.scout import UNRESOLVED, VERIFIED


class LookupTestCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)
        self.intake("- %s\n" % DOI)

    def intake(self, references):
        (self.project / "research" / "INTAKE.md").write_text("# Intake\n\n## References\n\n" + references, encoding="utf-8")

    def absorb(self, answers, now=NOW):
        fetcher, net = net_fetcher(answers)
        report = absorb_level_0(self.project, fetcher=fetcher, email=EMAIL, clock=lambda: now)
        return report, net

    def only_slug(self):
        slugs = sorted(path.parent.name for path in (self.project / "research" / "refs").glob("*/dossier.json"))
        self.assertEqual(len(slugs), 1, slugs)
        return slugs[0]

    def absorbed(self):
        return [event for event in self.ledger.read_events()[0] if event["event"] == "absorbed"]

    def raise_to_level_1(self, slug):
        """What `absorb --level 1` leaves: the level, the L1 fields, and the node's level."""
        dossier = read_dossier(self.ledger, slug)
        dossier.update(level=LEVEL_1, relation_to_intent="It proposes the method.", deserves_l2_if="The exact formulation matters.")
        self.ledger.write_json("refs/%s/dossier.json" % slug, dossier, schema="dossier")
        node = self.ledger.read_json("kb/nodes/%s.json" % slug)
        node["level"] = LEVEL_1
        self.ledger.write_json("kb/nodes/%s.json" % slug, node)
        return dossier


class NeverTakesBackTest(LookupTestCase):
    def test_a_failure_leaves_a_found_dossier_as_it_was(self):
        self.absorb(doi_answers(crossref_work()))
        slug = self.only_slug()
        before = (self.project / "research" / "refs" / slug / "dossier.json").read_bytes()
        self.absorb(doi_answers(DOWN, rest=DOWN), now=NOW + DAY)
        self.assertEqual((self.project / "research" / "refs" / slug / "dossier.json").read_bytes(), before)
        self.assertEqual(len(self.absorbed()), 1)

    def test_no_match_leaves_a_found_dossier_as_it_was(self):
        self.absorb(doi_answers(crossref_work()))
        slug = self.only_slug()
        before = read_dossier(self.ledger, slug)
        self.absorb(doi_answers(NOT_FOUND), now=NOW + DAY)
        self.assertEqual(read_dossier(self.ledger, slug), before)

    def test_the_same_work_found_again_replaces_only_the_lookups_own_fields(self):
        self.absorb(doi_answers(crossref_work(abstract="The first abstract.")))
        slug = self.only_slug()
        first = self.raise_to_level_1(slug)
        report, _ = self.absorb(doi_answers(crossref_work(abstract="A corrected abstract.")), now=NOW + DAY)
        dossier = read_dossier(self.ledger, slug)
        self.assertEqual(dossier["abstract"], "A corrected abstract.")
        for kept in ("level", "relation_to_intent", "deserves_l2_if", "created", "slug"):
            self.assertEqual(dossier[kept], first[kept], kept)
        self.assertEqual(dossier["updated"], "2026-09-22T14:13:20.000Z")
        self.assertEqual(read_nodes(self.ledger)[slug]["level"], LEVEL_1)
        self.assertEqual(len(self.absorbed()), 1, "the existence did not change, so nothing more is journaled")
        self.assertEqual(report["problems"], [])

    def test_a_work_found_after_failing_journals_its_changed_existence(self):
        self.absorb(doi_answers(DOWN, rest=DOWN))
        slug = self.only_slug()
        self.assertEqual(read_dossier(self.ledger, slug)["existence"], UNRESOLVED)
        self.absorb(doi_answers(crossref_work()), now=NOW + DAY)
        self.assertEqual(read_dossier(self.ledger, slug)["existence"], VERIFIED)
        self.assertEqual([event["payload"] for event in self.absorbed()], [{"slug": slug, "level": 0}] * 2)
        self.assertEqual(read_nodes(self.ledger)[slug]["existence"], VERIFIED)

    def test_an_l1_dossier_now_resolving_to_another_work_is_left_and_reported(self):
        """A title query: the service's best match today is a different work (another DOI) under the same title."""
        self.intake("- %s\n" % TITLE)
        self.absorb({"api.crossref.org": title_search("10.5555/the.first", family="Lovelace"),
                     "api.unpaywall.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": EMPTY_EUROPEPMC})
        slug = self.only_slug()
        before = self.raise_to_level_1(slug)
        report, _ = self.absorb({"api.crossref.org": title_search("10.5555/an.erratum", family="Babbage"),
                                 "api.unpaywall.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": EMPTY_EUROPEPMC},
                                now=NOW + DAY)
        self.assertEqual(read_dossier(self.ledger, slug), before)
        self.assertEqual([item["slug"] for item in report["disagreements"]], [slug])
        self.assertIn("10.5555/an.erratum", json.dumps(report["disagreements"]))


class RetryTest(LookupTestCase):
    """The `retry` flag: at most once a day by whatever runs next, and given up after seven days."""

    def flagged(self):
        self.absorb(doi_answers(DOWN, rest=DOWN))
        return read_dossier(self.ledger, self.only_slug())

    def test_a_flagged_reference_is_not_asked_again_within_the_day(self):
        self.flagged()
        report, net = self.absorb(doi_answers(crossref_work()), now=NOW + 6 * HOUR)
        self.assertEqual(net.asked, [])
        self.assertEqual(report["written"][0]["change"], WAITING)

    def test_a_day_later_the_next_absorb_asks_again_and_finds_it(self):
        flag = self.flagged()["retry"]
        self.assertEqual((flag["service"], flag["since"]), ("crossref", "2026-09-21T14:13:20.000Z"))
        _, net = self.absorb(doi_answers(crossref_work()), now=NOW + DAY)
        self.assertTrue(net.asked)
        dossier = read_dossier(self.ledger, self.only_slug())
        self.assertEqual(dossier["existence"], VERIFIED)
        self.assertNotIn("retry", dossier)

    def test_a_failure_again_moves_the_date_and_keeps_counting_from_the_first(self):
        self.flagged()
        self.absorb(doi_answers(DOWN, rest=DOWN), now=NOW + DAY)
        flag = read_dossier(self.ledger, self.only_slug())["retry"]
        self.assertEqual((flag["date"], flag["since"]), ("2026-09-22T14:13:20.000Z", "2026-09-21T14:13:20.000Z"))

    def test_the_flag_gives_up_after_seven_days_and_nothing_asks_after(self):
        self.flagged()
        for day in range(1, 7):
            self.absorb(doi_answers(DOWN, rest=DOWN), now=NOW + day * DAY)
        report, net = self.absorb(doi_answers(crossref_work()), now=NOW + 7 * DAY)
        self.assertEqual(net.asked, [])
        dossier = read_dossier(self.ledger, self.only_slug())
        self.assertEqual(dossier["retry"]["gave_up"], "2026-09-28T14:13:20.000Z")
        self.assertEqual(dossier["existence"], UNRESOLVED)
        self.assertEqual(report["written"][0]["change"], GAVE_UP)
        _, net = self.absorb(doi_answers(crossref_work()), now=NOW + 9 * DAY)
        self.assertEqual(net.asked, [])

    def test_the_seven_days_are_the_policys(self):
        from wayline.project import policy_for

        self.assertEqual(policy_for(self.project)["scout"]["give_up_days"], 7)

    def test_no_such_work_takes_the_flag_off(self):
        self.flagged()
        self.absorb(doi_answers(NOT_FOUND), now=NOW + DAY)
        self.assertNotIn("retry", read_dossier(self.ledger, self.only_slug()))

    def test_a_flagged_reference_intake_no_longer_names_is_retried_too(self):
        self.flagged()
        self.intake("None.\n")
        fetcher, _ = net_fetcher(doi_answers(crossref_work()))
        report = retry_flagged(self.project, fetcher=fetcher, email=EMAIL, clock=lambda: NOW + DAY)
        self.assertEqual([item["change"] for item in report["written"]], ["existence changed"])
        self.assertEqual(read_dossier(self.ledger, self.only_slug())["existence"], VERIFIED)


class JoinTest(LookupTestCase):
    """One work, one dossier: a second name joins the first, and two dossiers of one work collapse to one."""

    ANSWERS = {"api.crossref.org/works/": crossref_work(), "api.crossref.org/works?": title_search(DOI, title="A work the services know"),
               "api.unpaywall.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": EMPTY_EUROPEPMC}

    def test_a_doi_and_a_title_naming_one_work_give_one_dossier_recording_both_names(self):
        self.intake("- %s\n- A work the services know\n" % DOI)
        report, _ = self.absorb(self.ANSWERS)
        slug = self.only_slug()
        names = [(name["kind"], name["value"]) for name in read_dossier(self.ledger, slug)["names"]]
        self.assertEqual(names, [("doi", DOI), ("title", "A work the services know")])
        self.assertEqual([item["slug"] for item in report["written"]], [slug, slug])

    def test_the_second_name_stays_joined_on_the_next_pass(self):
        self.intake("- %s\n- A work the services know\n" % DOI)
        self.absorb(self.ANSWERS)
        self.absorb(self.ANSWERS, now=NOW + DAY)
        self.assertEqual(len(read_dossier(self.ledger, self.only_slug())["names"]), 2)

    def test_two_dossiers_of_one_work_collapse_to_the_higher_level_with_the_notes_moved(self):
        self.absorb(self.ANSWERS)
        kept = self.only_slug()
        self.raise_to_level_1(kept)
        twin = dict(read_dossier(self.ledger, kept), slug="lovelace-2021-twin", level=0, created="2026-01-01T00:00:00.000Z",
                    names=[{"kind": "title", "value": "A work the services know"}],
                    notes=[{"text": "the owner's first paper on this", "by": "intake", "ts": "2026-01-01T00:00:00.000Z"}])
        for name in ("relation_to_intent", "deserves_l2_if"):
            twin.pop(name)
        write_l0(self.ledger, twin)
        report, _ = self.absorb(self.ANSWERS, now=NOW + DAY)
        self.assertEqual(all_slugs(self.ledger), [kept])
        pointer = read_dossier(self.ledger, "lovelace-2021-twin")
        self.assertEqual(pointer["joined_into"], kept)
        self.assertEqual(pointer.get("notes", []), [])
        survivor = read_dossier(self.ledger, kept)
        self.assertEqual(survivor["level"], LEVEL_1)
        self.assertEqual([note["text"] for note in survivor["notes"]], ["the owner's first paper on this"])
        self.assertIn({"kind": "title", "value": "A work the services know"}, survivor["names"])
        self.assertNotIn("lovelace-2021-twin", read_nodes(self.ledger))
        self.assertEqual(report["joined"], [{"slug": "lovelace-2021-twin", "into": kept}])

    def test_on_a_tie_the_older_dossier_stays(self):
        self.absorb(self.ANSWERS)
        first = self.only_slug()
        twin = dict(read_dossier(self.ledger, first), slug="lovelace-2021-older", created="2025-01-01T00:00:00.000Z")
        write_l0(self.ledger, twin)
        self.absorb(self.ANSWERS, now=NOW + DAY)
        self.assertEqual(all_slugs(self.ledger), ["lovelace-2021-older"])
        self.assertEqual(read_dossier(self.ledger, first)["joined_into"], "lovelace-2021-older")


class HandOverTest(LookupTestCase):
    """The owner's hand-over: a DOI or an exact title back to the scout, a PDF as the source, or "leave it"."""

    LOST = "The lost paper on cell flows"

    def setUp(self):
        super().setUp()
        self.intake("- %s\n" % self.LOST)
        self.absorb({"api.crossref.org": DOWN, "api.openalex.org": DOWN, "www.ebi.ac.uk": DOWN})
        self.slug = self.only_slug()
        self.assertEqual(read_dossier(self.ledger, self.slug)["existence"], UNRESOLVED)

    def hand(self, answer, answers=(), read_pdf=None):
        fetcher, net = net_fetcher(dict(answers))
        result = hand_over(self.project, self.slug, answer, fetcher=fetcher, email=EMAIL, clock=lambda: NOW + HOUR, read_pdf=read_pdf)
        return result, net

    def test_a_doi_goes_back_to_the_scout_and_the_dossier_is_found(self):
        result, net = self.hand(DOI, doi_answers(crossref_work()))
        self.assertTrue(net.asked)
        dossier = read_dossier(self.ledger, self.slug)
        self.assertEqual((dossier["existence"], dossier["resolved_by"]), (VERIFIED, "crossref"))
        self.assertNotIn("retry", dossier)
        self.assertIn({"kind": "doi", "value": DOI, "raw": DOI}, dossier["names"])
        self.assertEqual(dossier["handed_over"], [{"answer": "doi", "value": DOI, "ts": "2026-09-21T15:13:20.000Z"}])
        self.assertEqual(len(self.absorbed()), 2)
        self.assertEqual(result["change"], "existence changed")

    def test_an_exact_title_goes_back_to_the_scout(self):
        self.hand("A work the services know", {"api.crossref.org": title_search(DOI, title="A work the services know"),
                                               "api.unpaywall.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": EMPTY_EUROPEPMC})
        dossier = read_dossier(self.ledger, self.slug)
        self.assertEqual(dossier["existence"], VERIFIED)
        self.assertEqual(dossier["handed_over"][0]["answer"], "title")

    def test_a_pdf_whose_title_a_service_knows_is_found_by_the_scout_and_kept_as_the_source(self):
        pdf = self.temp / "lost.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.hand(str(pdf), {"api.crossref.org": title_search(DOI, title="A work the services know"),
                             "api.unpaywall.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": EMPTY_EUROPEPMC},
                  read_pdf=lambda path: {"title": "A work the services know"})
        dossier = read_dossier(self.ledger, self.slug)
        self.assertEqual((dossier["existence"], dossier["resolved_by"]), (VERIFIED, "crossref"))
        self.assertTrue((self.project / "research" / "refs" / self.slug / "source" / "lost.pdf").is_file())
        self.assertEqual(dossier["handed_over"][0]["answer"], "pdf")

    def test_a_pdf_no_service_knows_is_found_by_the_owner_with_its_details_read_from_it(self):
        pdf = self.temp / "lost.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        details = {"title": "Cell flows, a working draft", "authors": ["Ada Lovelace"], "year": 2019}
        _, net = self.hand(str(pdf), {"api.crossref.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "www.ebi.ac.uk": EMPTY_EUROPEPMC},
                           read_pdf=lambda path: details)
        self.assertTrue(net.asked, "the scout tries the PDF's title first")
        dossier = read_dossier(self.ledger, self.slug)
        self.assertEqual((dossier["existence"], dossier["resolved_by"]), (VERIFIED, "owner"))
        self.assertEqual(dossier["metadata"], {"title": "Cell flows, a working draft", "authors": ["Ada Lovelace"], "year": 2019})
        self.assertNotIn("retry", dossier)

    def test_leave_it_is_recorded_and_settles_the_item_with_nothing_asked(self):
        before = read_dossier(self.ledger, self.slug)
        _, net = self.hand("leave it")
        self.assertEqual(net.asked, [])
        dossier = read_dossier(self.ledger, self.slug)
        self.assertEqual(dossier["handed_over"], [{"answer": "leave", "value": None, "ts": "2026-09-21T15:13:20.000Z"}])
        self.assertEqual({key: value for key, value in dossier.items() if key not in ("handed_over", "updated")},
                         {key: value for key, value in before.items() if key != "updated"})

    def test_a_url_is_refused_since_no_service_looks_one_up(self):
        with self.assertRaises(DossierError):
            self.hand("https://openreview.net/forum?id=abc")

    def test_the_verb_runs_in_process_for_the_cli_and_the_dashboard(self):
        import contextlib
        import io

        from wayline import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["reference", self.slug, "leave it", "--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertEqual(read_dossier(self.ledger, self.slug)["handed_over"][0]["answer"], "leave")


class ReviewRegressionTest(LookupTestCase):
    def test_the_next_absorb_retries_a_flagged_reference_intake_no_longer_names(self):
        self.absorb(doi_answers(DOWN, rest=DOWN))
        self.intake("None.\n")
        _, net = self.absorb(doi_answers(crossref_work()), now=NOW + DAY)
        self.assertTrue(net.asked)
        self.assertEqual(read_dossier(self.ledger, self.only_slug())["existence"], VERIFIED)

    def test_a_pdf_handed_over_for_a_found_work_becomes_its_source_and_takes_nothing_back(self):
        self.absorb(doi_answers(crossref_work()))
        slug = self.only_slug()
        before = read_dossier(self.ledger, slug)
        pdf = self.temp / "copy.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        fetcher, _ = net_fetcher({})
        hand_over(self.project, slug, str(pdf), fetcher=fetcher, email=EMAIL, clock=lambda: NOW, read_pdf=lambda path: {})
        dossier = read_dossier(self.ledger, slug)
        for name in ("metadata", "abstract", "resolved_by", "identifiers"):
            self.assertEqual(dossier[name], before[name], name)
        self.assertTrue((self.project / "research" / "refs" / slug / "source" / "copy.pdf").is_file())

    def test_an_arxiv_id_handed_over_is_recorded_as_one(self):
        self.intake("- The lost paper\n")
        self.absorb({"api.crossref.org": DOWN, "api.openalex.org": DOWN, "www.ebi.ac.uk": DOWN})
        fetcher, _ = net_fetcher({"export.arxiv.org": (200, '<feed xmlns="http://www.w3.org/2005/Atom"></feed>')})
        result = hand_over(self.project, self.only_slug(), "arXiv:2304.02443", fetcher=fetcher, email=EMAIL, clock=lambda: NOW)
        self.assertEqual(result["dossier"]["handed_over"][0]["answer"], "arxiv")


class TickRetryTest(TickCase):
    """The tick retries the flagged references while a run is live, before it defers to a conductor that is waving."""

    def setUp(self):
        super().setUp()
        self.fake.usage_text = usage_text(10, 10)
        self.retried = []

    def references(self, path, clock):
        self.retried.append((Path(path), clock()))
        return {"written": [], "problems": []}

    def test_a_live_run_has_the_flagged_references_retried_even_while_its_conductor_waves(self):
        self.ran()
        self.heartbeat = {"pid": 4242, "started_at": ts(self.now - HOUR), "last_wave_at": ts(self.now - 60), "harness_tag": "v0.0.0"}
        self.holding = True
        result = self.run_tick(references=self.references)
        self.assertEqual(result.ended, tick.CONDUCTOR_ALIVE)
        self.assertEqual(self.retried, [(self.project.resolve(), self.now)])

    def test_no_run_live_retries_nothing(self):
        self.ran(ended="frontier_empty")
        self.run_tick(references=self.references)
        self.assertEqual(self.retried, [])
