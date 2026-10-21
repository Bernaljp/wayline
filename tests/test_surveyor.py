"""The surveyor and `lit` tickets (Implementation Decision 17; ticket 99).

The seams: the role as its files define it (`worker.read_role`) and the prompt the conductor assembles for it; the
fake launcher scripting a surveyor result through the conductor (seam 4), read back from the journal, the ticket, and
the Introduction; the planner's cut at specify through the fake launcher, read back from the tickets it wrote; and
position's search of its `missing_prior_work` through the fetch seam's recordings, read back from `POSITION.md`.
"""

import json
import unittest

from tests.paths import HARNESS_ROOT
from wayline import proposals, survey, worker
from wayline import POLICY_PATH


class RoleTest(unittest.TestCase):
    def setUp(self):
        self.role = worker.read_role(survey.ROLE, HARNESS_ROOT)

    def test_the_surveyor_takes_lit_tickets_and_returns_a_result(self):
        self.assertEqual(self.role.kinds, ["lit"])
        self.assertEqual(self.role.output_schema, "result")
        self.assertFalse(self.role.may_judge)

    def test_it_runs_on_sonnet_at_medium(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(policy["roles"]["surveyor"], {"model": "sonnet", "effort": "medium"})
        self.assertEqual(survey.role_tier(policy), ("sonnet", "medium"))
        self.assertEqual(survey.role_tier({}), ("sonnet", "medium"))

    def test_its_tools_are_reading_the_scout_and_the_consultant(self):
        self.assertEqual(self.role.allowed_tools, ["Read", "Glob", "Grep", "Bash(wayline scout *)", "Bash(wayline consult *)",
                                                   "Bash(wayline accept*)"])
        self.assertTrue(worker.has_scout(self.role))
        for removed in ("Edit", "Write", "WebFetch", "WebSearch", "Bash(wayline job add*)"):
            self.assertIn(removed, self.role.disallowed_tools)

    def test_its_prompt_asks_for_introduction_passages_tagged_at_the_abstract_references_and_proposals(self):
        words = " ".join((self.role.system_prompt + "\n" + self.role.protocol).split())
        for asked in ("wayline scout search", "--citing", "wayline scout <identifier>", "`introduction`", "#abstract", "`references`",
                      "`proposals`", "never cite a work you have not scouted"):
            self.assertIn(asked, words)

    def test_kind_role_routes_lit_to_the_surveyor(self):
        self.assertEqual(proposals.KIND_ROLE["lit"], "surveyor")
        self.assertEqual(proposals.role_for("lit"), "surveyor")
        self.assertNotIn("dossier", proposals.KIND_ROLE, "a dossier ticket runs as a promotion, with no worker (ticket 98)")

    def test_the_contract_restates_both_caps(self):
        ticket = {"id": 4, "title": "Survey label noise", "kind": "lit", "difficulty": 2, "touches": [], "objectives": ["O1"],
                  "acceptance": {"machine": [], "quality": []}, "context_pack": [], "skills": []}
        text = worker.assemble_prompt(ticket, self.role, scout_max=20, search_max=20).text
        self.assertIn("at most 20 times in this ticket: it files the work's dossier", text)
        self.assertIn("Search the literature with `wayline scout search \"<query>\"`", text)
        self.assertIn("at most 20 searches in this ticket", text)
        coder = worker.assemble_prompt(dict(ticket, kind="code", touches=["src/"]), worker.read_role("coder", HARNESS_ROOT),
                                       scout_max=20, search_max=20).text
        self.assertNotIn("wayline scout search", coder, "a search is the surveyor's, for a `lit` ticket")


from tests.test_conductor import ConductorCase, drive  # noqa: E402  (the conductor's seam, after the role's own cases)

SLUG = "lovelace-2019-interaction-terms-noise"
PASSAGE = "Interaction terms lose most of their gain once labels are noisy {ref:%s#abstract}." % SLUG


def surveyed(ticket_id=1, **extra):
    """The result a surveyor returns: one Introduction passage tagged at a scouted work's abstract, the work, a proposal."""
    from wayline.worker import Envelope
    result = {"ticket_id": ticket_id, "status": "done", "summary": "searched label noise and interaction terms; one work bears on O1",
              "outputs_written": [], "references": [{"identifier": "10.5555/a", "note": "the closest prior result"}],
              "passages": [{"section": "introduction", "heading": "Label noise and interaction terms", "text": PASSAGE, "replaces": None}],
              "proposals": [{"title": "Survey symmetric and asymmetric label noise", "kind": "lit",
                             "why": "the works found treat symmetric flips alone", "radius": "moderate"}]}
    result.update(extra)
    return Envelope(structured_output=result, num_turns=6, duration_ms=2000)


class LitTicketCase(ConductorCase):
    """The one-ticket fixture with its ticket turned into a `lit` ticket for O1, and the work it cites already scouted."""

    difficulty = 3  # rung 5, Opus at medium: a lit ticket runs on the surveyor's tier whatever its difficulty

    def setUp(self):
        super().setUp()
        import io
        from tests.projects import open_objective
        from wayline import tickets
        from wayline.dossier import l0_dossier, write_l0
        from wayline.project import set_autonomy
        open_objective(self.project, "Do interaction terms survive label noise?")
        record = {"schema_version": 1, "query": {"kind": "doi", "value": "10.5555/a", "raw": "10.5555/a"}, "existence": "verified",
                  "resolved_by": "crossref", "identifiers": {"doi": "10.5555/a"},
                  "metadata": {"title": "Interaction terms under noise", "authors": ["Ada Lovelace"], "year": 2019},
                  "abstract": "Interaction terms lose most of their gain under label noise.", "open_access": {}, "attempts": []}
        write_l0(self.ledger, l0_dossier(record, SLUG))
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        fields.update(title="Survey label noise", kind="lit", role="surveyor", difficulty=self.difficulty, touches=[], outputs=[],
                      objectives=["O1"], sections=["introduction"], acceptance={"machine": [], "quality": []})
        path.unlink()
        tickets.write_ticket(self.ledger, fields, body)
        set_autonomy(self.project, "interactive")
        self.out = io.StringIO()

    def run_lit(self, *scripted, before=None, waves=None):
        from tests import machine
        from wayline.conductor import Conductor
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope, role=survey.ROLE)
            conductor = Conductor(self.project, out=self.out)
            conductor.readings = machine.recorded
            conductor.plan_pre_check = False
            if before is not None:
                before(conductor)
            results = drive(conductor, waves)
            self.calls = list(fake.calls)
        return results

    def launched(self):
        return [event["payload"] for event in self.events("ticket_launched")]


class LitTicketTest(LitTicketCase):
    def test_a_lit_ticket_runs_on_the_surveyor_at_sonnet_medium_whatever_its_difficulty(self):
        self.run_lit(surveyed())
        [launch] = self.launched()
        self.assertEqual((launch["role"], launch["model"], launch["effort"], launch["rung"]), ("surveyor", "sonnet", "medium", None))
        self.assertEqual(launch["difficulty"], 3)
        request = self.calls[0].request
        self.assertEqual((request.role, request.model, request.effort), ("surveyor", "sonnet", "medium"))
        self.assertEqual(request.allowed_tools, worker.read_role(survey.ROLE, HARNESS_ROOT).allowed_tools)
        self.assertIn("at most 20 searches in this ticket", request.prompt)
        self.assertIn("(surveyor, sonnet medium, attempt 1)", self.out.getvalue())

    def test_its_turns_and_minutes_are_its_rungs(self):
        self.run_lit(surveyed())
        request = self.calls[0].request
        agent = request.agent_json if isinstance(request.agent_json, dict) else __import__("json").loads(request.agent_json)
        self.assertEqual((agent["surveyor"]["maxTurns"], request.max_minutes), (100, 90), "rung 5 takes the medium budget")

    def test_its_introduction_passage_lands_and_the_work_is_kept_with_its_note(self):
        from wayline.dossier import read_dossier
        self.run_lit(surveyed())
        self.assertEqual(self.ticket()["status"], "done")
        introduction = (self.project / "research" / "sections" / "introduction.md").read_text(encoding="utf-8")
        self.assertIn("## Label noise and interaction terms", introduction)
        self.assertIn(PASSAGE, introduction)
        [passage] = [event["payload"] for event in self.events("passage")]
        self.assertEqual((passage["section"], passage["objectives"]), ("introduction", ["O1"]))
        from wayline import specify
        self.assertTrue(specify.introduction_covers(self.project, "O1"), "O1 is covered now, so no lit ticket is cut for it again")
        self.assertEqual(read_dossier(self.ledger, SLUG)["notes"][0]["text"], "the closest prior result")

    def test_its_lit_proposal_is_admitted_onto_the_surveyor(self):
        self.run_lit(surveyed())
        self.assertEqual((self.ticket(2)["kind"], self.ticket(2)["role"], self.ticket(2)["title"]),
                         ("lit", "surveyor", "Survey symmetric and asymmetric label noise"))

    def test_a_cheap_window_leaves_it_on_the_surveyors_tier(self):
        self.run_lit(surveyed(), before=lambda conductor: conductor.simulate_step_down(3600))
        [launch] = self.launched()
        self.assertEqual((launch["model"], launch["effort"]), ("sonnet", "medium"))

    def test_a_policy_moves_the_surveyor(self):
        import json
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness.setdefault("policy", {}).setdefault("roles", {})["surveyor"] = {"model": "haiku", "effort": "medium"}
        (self.project / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        self.run_lit(surveyed())
        [launch] = self.launched()
        self.assertEqual((launch["model"], launch["effort"]), ("haiku", "medium"))


class LitEscalationTest(LitTicketCase):
    def test_a_failing_lit_ticket_takes_its_resume_and_no_tier_up(self):
        failed = surveyed(status="failed", summary="every search failed")
        self.run_lit(failed, failed, waves=3)
        steps = [event["payload"]["next"] for event in self.events("ticket_failed")]
        self.assertEqual(steps[0], "resume")
        self.assertNotIn("tier_up", steps, "the surveyor's tier is no rung to climb from")
        for launch in self.launched():
            self.assertEqual((launch["model"], launch["effort"]), ("sonnet", "medium"))
        self.assertIn("resume", [call.kind for call in self.calls])
        for call in self.calls:
            self.assertEqual((call.request.role, call.request.model, call.request.effort), ("surveyor", "sonnet", "medium"),
                             "the resume rebuilds the tier its launch journaled")
        self.assertNotIn("the rung ladder's top rung", " ".join(event["payload"]["question"] for event in self.events("ticket_needs_human")))


    def test_a_surveyor_model_nobody_serves_goes_to_a_person_with_no_rung_held(self):
        from tests.test_model_ran import not_served
        with worker.use_fake() as fake:
            fake.script(respond=lambda request, message: not_served("sonnet"), role=survey.ROLE)
            from tests import machine
            from wayline.conductor import Conductor
            conductor = Conductor(self.project, out=self.out)
            conductor.readings = machine.recorded
            drive(conductor, 2)
        failed = self.events("ticket_failed")[0]["payload"]
        self.assertEqual(failed["next"], "needs_human")
        self.assertIn("model_not_served", failed["reason"])
        self.assertNotIn("rung", failed["reason"])
        self.assertEqual([event for event in self.events("decision_opened") if "not served" in str(event)], [])

from tests.test_plan import CUT, PlanCase, planned  # noqa: E402  (the planner's seam)


def lit_ticket(*served, key="T20", context_pack=("research/OBJECTIVES.md",)):
    return {"key": key, "title": "Survey label noise and interaction terms", "kind": "lit", "difficulty": 2, "blocked_by": [],
            "touches": [], "acceptance": {"machine": [], "quality": []}, "objectives": list(served),
            "context_pack": list(context_pack), "origin": "research/OBJECTIVES.md",
            "demo": "The Introduction gains passages on the objectives, each tagged at a scouted work's abstract."}


def with_lit(*items):
    value = json.loads(json.dumps(CUT))
    value["tickets"] = value["tickets"] + list(items)
    return value


class AtSpecifyTest(PlanCase):
    """The graph's first cut: a `lit` ticket for each open objective no Introduction passage with a `ref` tag covers."""

    introduction_covered = False

    def test_the_planner_is_asked_for_lit_tickets_serving_the_uncovered_objectives(self):
        self.script(planned(with_lit(lit_ticket("O1", "O2"))))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        [call] = self.calls("planner")
        asked = call.request.prompt.split("# What you are asked for", 1)[1].split("\n# ", 1)[0]
        self.assertIn("`lit` tickets serving O1, O2", asked)
        self.assertIn("one ticket may serve several objectives that share a literature", asked)

    def test_one_lit_ticket_serving_objectives_that_share_a_literature_is_written_on_the_surveyor(self):
        self.script(planned(with_lit(lit_ticket("O1", "O2"))))
        written = self.plan()["written"]
        [lit] = [identifier for identifier in written["tickets"] if self.ticket(identifier)["kind"] == "lit"]
        self.assertEqual((self.ticket(lit)["role"], self.ticket(lit)["objectives"]), ("surveyor", ["O1", "O2"]))

    def test_a_cut_that_leaves_an_objective_uncovered_is_returned_with_the_failure(self):
        self.script(planned(with_lit(lit_ticket("O1"))), planned(with_lit(lit_ticket("O1"), lit_ticket("O2", key="T21"))))
        report = self.plan()
        self.assertIsNone(report["stopped"], report)
        message = self.second_message()
        self.assertIn("no Introduction passage with a `ref` tag covers O2, and no `lit` ticket of this cut serves it", message)
        self.assertNotIn("covers O1,", message)
        lits = sorted(self.ticket(identifier)["objectives"][0] for identifier in report["written"]["tickets"]
                      if self.ticket(identifier)["kind"] == "lit")
        self.assertEqual(lits, ["O1", "O2"])

    def test_an_objective_the_introduction_already_cites_for_needs_none(self):
        from wayline import sections
        sections.add_passage(self.project, "introduction", "Interaction terms",
                             "Interaction terms help on tabular data {ref:paper-a#abstract}.", by="owner", objectives=["O1"])
        self.script(planned(with_lit(lit_ticket("O2"))))
        self.assertIsNone(self.plan()["stopped"])
        asked = self.calls("planner")[0].request.prompt.split("# What you are asked for", 1)[1].split("\n# ", 1)[0]
        self.assertIn("`lit` tickets serving O2", asked)
        self.assertNotIn("O1, O2", asked)

    def test_a_passage_without_a_ref_tag_covers_nothing(self):
        from wayline import sections
        sections.add_passage(self.project, "introduction", "Interaction terms", "Interaction terms are a classic idea.", by="owner",
                             objectives=["O1", "O2"])
        self.assertEqual(survey.uncovered(self.project), ["O1", "O2"])

    def test_a_covered_project_is_asked_for_none(self):
        from wayline import sections
        sections.add_passage(self.project, "introduction", "Interaction terms",
                             "Interaction terms help on tabular data {ref:paper-a#abstract}.", by="owner", objectives=["O1", "O2"])
        self.assertEqual(survey.uncovered(self.project), [])
        self.script(planned(CUT))
        self.assertIsNone(self.plan()["stopped"])
        self.assertNotIn("`lit` tickets serving", self.calls("planner")[0].request.prompt)

    def test_the_first_lit_tickets_are_handed_what_positions_search_found(self):
        self.ledger.write_json("position.json", {"memo": {"missing_prior_work": ["A gradient-boosted tree baseline"]},
                                                 "missing_scouted": [{"gap": "A gradient-boosted tree baseline", "works": [], "note": None}]})
        self.script(planned(with_lit(lit_ticket("O1", "O2"))))
        written = self.plan()["written"]
        for identifier in written["tickets"]:
            found = self.ticket(identifier)
            if found["kind"] == "lit":
                self.assertEqual(found["context_pack"], ["research/OBJECTIVES.md", survey.MISSING_LOCATOR])
            else:
                self.assertNotIn(survey.MISSING_LOCATOR, found["context_pack"])

    def test_nothing_is_handed_when_position_named_no_missing_work(self):
        self.script(planned(with_lit(lit_ticket("O1", "O2"))))
        written = self.plan()["written"]
        [lit] = [identifier for identifier in written["tickets"] if self.ticket(identifier)["kind"] == "lit"]
        self.assertEqual(self.ticket(lit)["context_pack"], ["research/OBJECTIVES.md"])

    def test_the_journal_replays_the_lit_ticket_cut_on_the_surveyor(self):
        from wayline.replay import replay
        self.script(planned(with_lit(lit_ticket("O1", "O2"))))
        written = self.plan()["written"]
        [lit] = [identifier for identifier in written["tickets"] if self.ticket(identifier)["kind"] == "lit"]
        events = self.events()
        [created] = [event["payload"] for event in events if event["event"] == "ticket_created" and event["payload"]["ticket"] == lit]
        self.assertEqual((created["kind"], created["proposed_by"]), ("lit", "planner"))
        [assigned] = [event["payload"] for event in events if event["event"] == "assigned" and event["payload"]["ticket"] == lit]
        self.assertEqual(assigned["role"], "surveyor")
        self.assertEqual(replay(events).tickets[lit].status, "open")


from tests.test_amendments import AmendCase, amended, cut_for, experiment_ticket  # noqa: E402  (the amendment's seam)
from tests.test_amendments import lit_ticket as amendment_lit  # noqa: E402


class AfterAmendmentTest(AmendCase):
    """An added objective's amendment is followed by a `lit` ticket on the surveyor when no Introduction passage covers it."""

    def test_the_journal_replays_the_amendments_lit_ticket_on_the_surveyor(self):
        from wayline import specify
        from wayline.replay import replay
        self.script(planned(amended()))
        self.amend()
        specify.confirm_amendment(self.project, "O2", "confirm")
        self.script(cut_for(experiment_ticket(), amendment_lit()), verdicts=())
        self.assertIsNone(self.amend()["stopped"])
        events = self.events()
        lits = [event["payload"]["ticket"] for event in events if event["event"] == "ticket_created" and event["payload"]["kind"] == "lit"]
        self.assertEqual(len(lits), 1)
        [record] = [item for item in specify.read_amendments(self.project) if item["objective"] == "O2"]
        self.assertEqual(record["lit"], lits)
        [assigned] = [event["payload"] for event in events if event["event"] == "assigned" and event["payload"]["ticket"] == lits[0]]
        self.assertEqual(assigned["role"], "surveyor")
        self.assertEqual((self.ticket(lits[0])["objectives"], self.ticket(lits[0])["touches"]), (["O2"], []))
        self.assertEqual(replay(events).tickets[lits[0]].status, "open")

    def test_a_lit_ticket_that_would_write_a_file_is_returned(self):
        from wayline import specify
        self.script(planned(amended()))
        self.amend()
        specify.confirm_amendment(self.project, "O2", "confirm")
        writing = dict(amendment_lit(), touches=["notes/lit-o2/"])
        self.script(cut_for(experiment_ticket(), writing), cut_for(), verdicts=())
        self.assertIsNone(self.amend()["stopped"])
        message = [call for call in self.calls("planner") if call.kind == "resume"][-1].message
        self.assertIn("is a lit ticket, whose touch set is empty: the surveyor writes no file", message)


from tests.test_position import RECORDINGS, PositionCase, memo, written  # noqa: E402  (position's seam)

GAP = "A gradient-boosted tree baseline, the usual strong model for tabular data, which none of the dossiers covers."


class _Recorded:
    """The position suite's recordings first, then a scripted network for what they do not hold (the setup search)."""

    def __init__(self, net):
        from wayline.fetch import DirectoryBackend
        self.recordings, self.net = DirectoryBackend(RECORDINGS), net

    def send(self, request):
        from wayline.fetch import FetchError
        try:
            return self.recordings.send(request)
        except FetchError:
            return self.net.send(request)


class MissingPriorWorkTest(PositionCase):
    """Position's `missing_prior_work` is searched at setup, uncounted by any ticket, and `POSITION.md` lists what was found."""

    def setUp(self):
        super().setUp()
        from tests.scout_net import EMAIL, Net
        from tests.test_scout_search import answers, crossref_items
        from wayline.fetch import Fetcher
        from wayline.scout import Scout
        self.net = Net(answers(api_crossref_org=crossref_items(("10.5555/xgb", "XGBoost: a scalable tree boosting system", 2016))))
        self.scout = Scout(Fetcher(_Recorded(self.net), email=EMAIL), EMAIL)

    def test_each_gap_is_searched_once_at_setup_and_journaled_with_no_ticket(self):
        self.take(written(memo()))
        searched = [event for event in self.ledger.read_events()[0] if event["event"] == "scout_searched"]
        self.assertEqual([(event["ticket"], event["payload"]["query"]) for event in searched], [(None, GAP)])
        self.assertEqual(len([url for url in self.net.asked if "api.crossref.org" in url]), 1)

    def test_what_the_search_found_is_kept_and_listed_under_the_gap(self):
        self.take(written(memo()))
        [scouted] = self.record()["missing_scouted"]
        self.assertEqual(scouted["gap"], GAP)
        self.assertEqual([work["identifier"] for work in scouted["works"]], ["doi:10.5555/xgb"])
        text = self.text()
        lacking = text[text.index("### What the references lack"):text.index("## Feasibility")]
        self.assertIn("- " + GAP, lacking)
        self.assertIn("  - found by the search: *XGBoost: a scalable tree boosting system* (Ada Lovelace, 2016); scout it as "
                      "`doi:10.5555/xgb`", lacking)
        self.assertIn("the first `lit` tickets take them up", lacking)
        self.assertTrue(survey.missing_scouted(self.project))

    def test_no_dossier_is_filed_for_what_the_search_found(self):
        self.take(written(memo()))
        self.assertFalse(any("xgb" in path.name for path in (self.project / "research" / "refs").iterdir()))

    def test_a_memo_with_no_missing_work_searches_nothing(self):
        value = memo()
        value["missing_prior_work"] = []
        self.take(written(value))
        self.assertEqual([event for event in self.ledger.read_events()[0] if event["event"] == "scout_searched"], [])
        self.assertFalse(survey.missing_scouted(self.project))


if __name__ == "__main__":
    unittest.main()
