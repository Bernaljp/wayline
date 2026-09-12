"""L1 skims, reading budgets, and promotion triggers (Implementation Decisions 9).

The L1 call runs over the fake launcher; nothing here reaches the network. A project starts
from `write_l0`, the way `wayline absorb --level 0` would leave it, and each test builds on
that up through the skim, the promotion budget, and the minimal report.
"""

import unittest

from tests.paths import FIXTURES_DIR
from wayline.dossier import (
    CITED_BY_SPEC, CONSULTANT_QUESTION, CONTEXT_PACK, LEVEL_0, LEVEL_1, LEVEL_2,
    PLANNER_OR_DECIDER, PRIMARY_AT_INTAKE, TRIGGERS, DossierError,
    absorb_level_1, demote, l0_dossier, l1_input, l1_prompt, promote, read_dossier,
    render_levels_report, render_levels_text, write_l0,
)
from wayline.fetch import recording_fetcher
from wayline.jsonschema import load_schema, validate
from wayline.kb import read_nodes
from wayline.ledger import Ledger
from wayline.scout import Scout, parse_reference
from wayline.tickets import read_tickets
from wayline import worker
from wayline.worker import Envelope

RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"


class L1TestCase(unittest.TestCase):
    """A bare project (no `wayline init`) with one or more L0 dossiers, the way absorb --level 0 leaves it."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        self.temp = Path(tempfile.mkdtemp(prefix="wayline-l1-test-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.project = self.temp / "project"
        (self.project / "research").mkdir(parents=True)
        self.ledger = Ledger(self.project)
        self.scout = Scout(recording_fetcher(RECORDINGS, email=EMAIL), EMAIL)

    def seed(self, text, slug):
        dossier = l0_dossier(self.scout.resolve(parse_reference(text)), slug)
        write_l0(self.ledger, dossier)
        return dossier

    def record(self, relation="It proposes the method the intent is built on.",
               deserves="The project needs the exact formulation, not just the idea."):
        return Envelope(structured_output={
            "schema_version": 1, "relation_to_intent": relation, "deserves_l2_if": deserves,
        })


class L1InputTest(L1TestCase):
    def test_title_and_abstract_are_the_input_when_nothing_else_exists(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        text, cut = l1_input(self.ledger, "vaswani-2017-attention", max_chars=40000)
        self.assertIn("Attention Is All You Need", text)
        self.assertIn("dominant sequence transduction", text)
        self.assertFalse(cut)

    def test_a_capped_input_says_it_was_cut(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        text, cut = l1_input(self.ledger, "vaswani-2017-attention", max_chars=20)
        self.assertEqual(len(text), 20)
        self.assertTrue(cut)

    def test_no_dossier_is_a_dossier_error(self):
        with self.assertRaises(DossierError):
            l1_input(self.ledger, "nonexistent", max_chars=100)

    def test_the_prompt_carries_the_intent_and_the_cut_notice(self):
        prompt = l1_prompt("find out whether X improves Y", "the paper's material", cut=True)
        self.assertIn("find out whether X improves Y", prompt)
        self.assertIn("the paper's material", prompt)
        self.assertIn("cut", prompt)


class AbsorbLevel1Test(L1TestCase):
    def test_a_skim_writes_the_l1_record_into_the_dossier(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            report = absorb_level_1(self.project, ["vaswani-2017-attention"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["skimmed"][0]["status"], "skimmed")
        dossier = read_dossier(self.ledger, "vaswani-2017-attention")
        self.assertEqual(dossier["level"], LEVEL_1)
        self.assertIn("method the intent", dossier["relation_to_intent"])
        self.assertIn("exact formulation", dossier["deserves_l2_if"])
        check_errors = validate(dossier, load_schema("dossier"))
        self.assertEqual(check_errors, [])

    def test_the_knowledge_base_node_moves_to_level_1_too(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["vaswani-2017-attention"])
        node = read_nodes(self.ledger)["vaswani-2017-attention"]
        self.assertEqual(node["level"], LEVEL_1)

    def test_the_journal_records_one_absorbed_event_at_level_1(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["vaswani-2017-attention"])
        events, _ = self.ledger.read_events()
        absorbed = [event for event in events if event["event"] == "absorbed" and event["payload"]["level"] == LEVEL_1]
        self.assertEqual(len(absorbed), 1)
        self.assertEqual(absorbed[0]["payload"]["slug"], "vaswani-2017-attention")

    def test_a_dossier_already_at_level_1_is_not_skimmed_again(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["vaswani-2017-attention"])
            report = absorb_level_1(self.project, ["vaswani-2017-attention"])  # nothing scripted the second time
            self.assertEqual(len(fake.calls), 1)
        self.assertEqual(report["skimmed"][0]["status"], "already level 1")

    def test_omitting_slugs_skims_every_dossier_below_level_1(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        self.seed("10.1038/s41586-020-2649-2", "second")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            fake.script(self.record(), role="reader")
            report = absorb_level_1(self.project)
        self.assertEqual({item["slug"] for item in report["skimmed"]}, {"vaswani-2017-attention", "second"})

    def test_an_invalid_result_is_a_problem_not_a_crash(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"schema_version": 1, "relation_to_intent": "x"}), role="reader")  # missing deserves_l2_if
            report = absorb_level_1(self.project, ["vaswani-2017-attention"])
        self.assertEqual(report["skimmed"], [])
        self.assertEqual(len(report["problems"]), 1)
        self.assertEqual(read_dossier(self.ledger, "vaswani-2017-attention")["level"], LEVEL_0)


class PromotionTest(L1TestCase):
    def promote_to_l1(self, slug):
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, [slug])

    def test_every_trigger_of_decision_9_is_accepted(self):
        self.assertEqual(len(TRIGGERS), 5)
        for trigger in (PRIMARY_AT_INTAKE, CITED_BY_SPEC, CONTEXT_PACK, CONSULTANT_QUESTION, PLANNER_OR_DECIDER):
            self.assertIn(trigger, TRIGGERS)

    def test_an_unknown_trigger_is_refused(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with self.assertRaises(DossierError):
            promote(self.ledger, "vaswani-2017-attention", "because I felt like it")

    def test_a_promotion_inside_budget_bumps_the_level_and_journals_the_trigger(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        self.promote_to_l1("vaswani-2017-attention")
        outcome = promote(self.ledger, "vaswani-2017-attention", PRIMARY_AT_INTAKE, phase="P1")
        self.assertEqual(outcome, {"promoted": True, "phase": "P1", "used": 1, "limit": 3})
        self.assertEqual(read_dossier(self.ledger, "vaswani-2017-attention")["level"], LEVEL_2)
        events, _ = self.ledger.read_events()
        promoted = [event for event in events if event["event"] == "promoted"]
        self.assertEqual(promoted[0]["payload"], {"slug": "vaswani-2017-attention", "from_level": LEVEL_1, "to_level": LEVEL_2, "trigger": PRIMARY_AT_INTAKE})

    def test_the_knowledge_base_node_follows_a_promotion(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        self.promote_to_l1("vaswani-2017-attention")
        promote(self.ledger, "vaswani-2017-attention", PRIMARY_AT_INTAKE, phase="P1")
        self.assertEqual(read_nodes(self.ledger)["vaswani-2017-attention"]["level"], LEVEL_2)

    def test_promoting_an_already_l2_paper_is_a_no_op(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        self.promote_to_l1("vaswani-2017-attention")
        promote(self.ledger, "vaswani-2017-attention", PRIMARY_AT_INTAKE, phase="P1")
        outcome = promote(self.ledger, "vaswani-2017-attention", CITED_BY_SPEC, phase="P1")
        self.assertEqual(outcome, {"promoted": False, "reason": "already level 2"})

    def test_the_fourth_p1_promotion_opens_a_decision_ticket_instead(self):
        """`policy.json` caps P1 at 3 level-2 reads; the 4th trigger in P1 asks a human instead."""
        slugs = []
        for index, (text, slug) in enumerate([
            ("arXiv:1706.03762", "one"), ("10.1038/s41586-020-2649-2", "two"),
            ("10.1101/2020.03.22.002386", "three"), ("arXiv:1912.01703", "four"),
        ]):
            self.seed(text, slug)
            self.promote_to_l1(slug)
            slugs.append(slug)
        outcomes = [promote(self.ledger, slug, PLANNER_OR_DECIDER, phase="P1") for slug in slugs]
        self.assertTrue(all(outcome["promoted"] for outcome in outcomes[:3]))
        self.assertFalse(outcomes[3]["promoted"])
        self.assertIn("decision_ticket", outcomes[3])
        self.assertEqual(read_dossier(self.ledger, "four")["level"], LEVEL_1)  # not bumped

        ticket_id = outcomes[3]["decision_ticket"]
        fields = next((t for t in read_tickets(self.project) if t["id"] == ticket_id), None)
        self.assertIsNotNone(fields)
        self.assertEqual(fields["kind"], "decision")
        self.assertEqual(fields["status"], "open")
        self.assertIn("four", fields["title"])
        self.assertIn("planner or the decider promotes", fields["origin"])

        events, _ = self.ledger.read_events()
        created = [event for event in events if event["event"] == "ticket_created" and event["ticket"] == ticket_id]
        opened = [event for event in events if event["event"] == "decision_opened" and event["ticket"] == ticket_id]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(opened), 1)
        self.assertEqual(created[0]["payload"]["kind"], "decision")

    def test_a_consultant_trigger_with_a_ticket_is_proposed_by_that_worker(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        self.promote_to_l1("vaswani-2017-attention")
        for slug in ("a", "b", "c"):
            self.seed("10.1038/s41586-020-2649-2" if slug == "a" else "10.1101/2020.03.22.002386" if slug == "b" else "arXiv:1912.01703", slug)
            self.promote_to_l1(slug)
            promote(self.ledger, slug, PLANNER_OR_DECIDER, phase="P1")  # spend the P1 budget of 3
        outcome = promote(self.ledger, "vaswani-2017-attention", CONSULTANT_QUESTION, phase="P1", ticket=7)
        self.assertFalse(outcome["promoted"])
        fields = next(t for t in read_tickets(self.project) if t["id"] == outcome["decision_ticket"])
        self.assertEqual(fields["proposed_by"], "worker:7")

    def test_a_phase_with_no_budget_entry_promotes_without_limit(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        self.promote_to_l1("vaswani-2017-attention")
        outcome = promote(self.ledger, "vaswani-2017-attention", PRIMARY_AT_INTAKE, phase="P9")
        self.assertTrue(outcome["promoted"])
        self.assertIsNone(outcome["limit"])

    def test_budgets_are_tracked_separately_per_phase(self):
        for text, slug in [("arXiv:1706.03762", "one"), ("10.1038/s41586-020-2649-2", "two")]:
            self.seed(text, slug)
            self.promote_to_l1(slug)
        self.ledger.append_event("phase", {"from": "P0", "to": "P1"})
        promote(self.ledger, "one", PRIMARY_AT_INTAKE)  # phase inferred as P1, used 1/3
        self.ledger.append_event("phase", {"from": "P1", "to": "P2"})
        self.ledger.append_event("phase", {"from": "P2", "to": "P3"})
        outcome = promote(self.ledger, "two", PRIMARY_AT_INTAKE)  # phase inferred as P3, budget is fresh
        self.assertTrue(outcome["promoted"])
        self.assertEqual(outcome["phase"], "P3")
        self.assertEqual(outcome["used"], 1)
        self.assertEqual(outcome["limit"], 2)

    def test_the_third_p3_promotion_opens_a_decision_ticket_too(self):
        """`policy.json` caps P3 (and P5) at 2 level-2 reads apiece; the boundary holds in both phases."""
        slugs = ["one", "two", "three"]
        for text, slug in zip(["arXiv:1706.03762", "10.1038/s41586-020-2649-2", "10.1101/2020.03.22.002386"], slugs):
            self.seed(text, slug)
            self.promote_to_l1(slug)
        self.ledger.append_event("phase", {"from": "P2", "to": "P3"})
        outcomes = [promote(self.ledger, slug, CITED_BY_SPEC, phase="P3") for slug in slugs]
        self.assertTrue(outcomes[0]["promoted"])
        self.assertTrue(outcomes[1]["promoted"])
        self.assertFalse(outcomes[2]["promoted"])
        self.assertIn("decision_ticket", outcomes[2])


class DemoteTest(L1TestCase):
    def test_demoting_from_l2_to_l1_drops_the_l1_fields_it_still_has(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["vaswani-2017-attention"])
        promote(self.ledger, "vaswani-2017-attention", PRIMARY_AT_INTAKE, phase="P1")
        outcome = demote(self.ledger, "vaswani-2017-attention", LEVEL_1, "the coverage audit could not confirm depth")
        self.assertEqual(outcome, {"from_level": LEVEL_2, "to_level": LEVEL_1})
        dossier = read_dossier(self.ledger, "vaswani-2017-attention")
        self.assertEqual(dossier["level"], LEVEL_1)

    def test_a_demotion_is_journaled_with_its_trigger(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["vaswani-2017-attention"])
        demote(self.ledger, "vaswani-2017-attention", LEVEL_0, "a duplicate of another reference")
        events, _ = self.ledger.read_events()
        demoted = [event for event in events if event["event"] == "demoted"]
        self.assertEqual(demoted[0]["payload"], {
            "slug": "vaswani-2017-attention", "from_level": LEVEL_1, "to_level": LEVEL_0,
            "trigger": "a duplicate of another reference",
        })

    def test_demoting_to_the_same_or_a_higher_level_is_refused(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with self.assertRaises(DossierError):
            demote(self.ledger, "vaswani-2017-attention", LEVEL_0, "no reason")  # already at level 0

    def test_a_blank_trigger_is_refused(self):
        self.seed("arXiv:1706.03762", "vaswani-2017-attention")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["vaswani-2017-attention"])
        with self.assertRaises(DossierError):
            demote(self.ledger, "vaswani-2017-attention", LEVEL_0, "   ")


class ReportTest(L1TestCase):
    def test_papers_are_grouped_by_level(self):
        self.seed("arXiv:1706.03762", "one")
        self.seed("10.1038/s41586-020-2649-2", "two")
        with worker.use_fake() as fake:
            fake.script(self.record(), role="reader")
            absorb_level_1(self.project, ["one"])
        report = render_levels_report(self.project)
        self.assertEqual(report["by_level"][LEVEL_0], ["two"])
        self.assertEqual(report["by_level"][LEVEL_1], ["one"])
        self.assertEqual(report["by_level"][LEVEL_2], [])

    def test_a_promotion_beyond_budget_is_listed_as_not_read_in_full_with_its_reason(self):
        slugs = []
        for index, (text, slug) in enumerate([
            ("arXiv:1706.03762", "one"), ("10.1038/s41586-020-2649-2", "two"),
            ("10.1101/2020.03.22.002386", "three"), ("arXiv:1912.01703", "four"),
        ]):
            self.seed(text, slug)
            with worker.use_fake() as fake:
                fake.script(self.record(), role="reader")
                absorb_level_1(self.project, [slug])
            slugs.append(slug)
        for slug in slugs:
            promote(self.ledger, slug, PLANNER_OR_DECIDER, phase="P1")
        report = render_levels_report(self.project)
        self.assertEqual(len(report["not_read_in_full"]), 1)
        pending = report["not_read_in_full"][0]
        self.assertEqual(pending["slug"], "four")
        self.assertIn("planner or the decider promotes", pending["reason"])
        text = render_levels_text(report)
        self.assertIn("not read in full:", text)
        self.assertIn("four", text)

    def test_the_text_report_says_none_pending_when_there_is_nothing_open(self):
        self.seed("arXiv:1706.03762", "one")
        text = render_levels_text(render_levels_report(self.project))
        self.assertIn("not read in full: none", text)


if __name__ == "__main__":
    unittest.main()
