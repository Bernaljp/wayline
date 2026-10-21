"""Spec amendments (Implementation Decision 17; ticket 92).

An added or reframed objective gets new claims, experiments, metrics, and anti-claims under new ids, and nothing
already in the spec changes. The seams are the append-only check, a Type-A function over two versions of the spec;
`wayline specify --amend <O>` driven through the fake launcher (the scoped specify session, the verifier, the planner's
cut); and the conductor replayed from its journal under each autonomy. What is asserted is what a later reader sees:
`research/spec.json` and `SPEC.md`, the amendment's record, the journal's `verdict`, `decision`, `ticket_created`, and
`ticket_cancelled` events, the new tickets and what pauses them, and the confirmation ticket.
"""

import copy
import json
import shutil
import unittest

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase, open_objective
from tests.test_specify import DRAFT, INPUT, RECORDED, planned, verdict
from wayline import gates, objectives, pacing, project, specify, tickets, worker
from wayline.ledger import Ledger


def amended(base=None, objective="O2"):
    """`base` with one claim for `objective`, its experiment, a metric, and an anti-claim appended under new ids."""
    value = copy.deepcopy(base or DRAFT)
    value["claims"].append({"id": "C4", "text": "The products' gain holds at label noise 0.2.", "experiments": ["E4"],
                            "objectives": [objective]})
    value["experiments"].append({"id": "E4", "claims": ["C4"], "design": "E1 at label noise 0.2, seeds 0-9.", "baselines": ["B1"],
                                 "data": ["D1"], "metrics": ["auroc_noisy"], "success": "mean paired gain at least +0.01"})
    value["metrics"].append({"name": "auroc_noisy", "definition": "AUROC on split_b with 20 percent of labels flipped",
                             "script": "python3 toy/eval.py --noise 0.2 {artifact}"})
    value["anti_claims"].append({"id": "A3", "text": "No claim is made past noise 0.2.", "confirmed_by": "E4"})
    return value


class AppendOnlyCheckTest(unittest.TestCase):
    """The Type-A check over two versions of the spec: an amendment appends under new ids and changes nothing."""

    def test_an_amendment_that_only_appends_for_its_objective_passes(self):
        self.assertEqual(specify.check_amendment(DRAFT, amended(), "O2"), [])

    def test_a_changed_or_removed_item_is_refused_and_named(self):
        changed = amended()
        changed["claims"][1]["text"] = "Reworded."
        self.assertIn("the amendment changes claim C2, which the spec already holds; an amendment rewrites nothing",
                      specify.check_amendment(DRAFT, changed, "O2"))
        removed = amended()
        del removed["experiments"][2]
        self.assertIn("the amendment removes or moves experiment E3, which the spec already holds; an amendment rewrites nothing",
                      specify.check_amendment(DRAFT, removed, "O2"))
        moved = amended()
        moved["metrics"][0], moved["metrics"][1] = moved["metrics"][1], moved["metrics"][0]
        self.assertIn("the amendment removes or moves metric auroc, which the spec already holds; an amendment rewrites nothing",
                      specify.check_amendment(DRAFT, moved, "O2"))
        summary = amended()
        summary["summary"] = "Another summary."
        self.assertIn("the amendment changes the spec's summary, which the spec already holds; an amendment rewrites nothing",
                      specify.check_amendment(DRAFT, summary, "O2"))
        scoped = amended()
        scoped["out_of_scope"][0] = "nothing"
        self.assertIn("the amendment changes out of scope item 1, which the spec already holds; an amendment rewrites nothing",
                      specify.check_amendment(DRAFT, scoped, "O2"))

    def test_the_new_claims_are_scoped_to_the_objective(self):
        self.assertIn("the amendment adds no claim for O2", specify.check_amendment(DRAFT, copy.deepcopy(DRAFT), "O2"))
        elsewhere = amended(objective="O1")
        self.assertIn("claim C4, added by the amendment, does not name O2 among its objectives",
                      specify.check_amendment(DRAFT, elsewhere, "O2"))

    def test_an_amendment_for_a_goal_defines_its_metric(self):
        from tests.test_specify import objective
        records = [objective("O1"), objective("O2", metric="brier")]
        self.assertIn("the goal O2's metric brier is not among the spec's metrics",
                      specify.check_amendment(DRAFT, amended(), "O2", records))
        self.assertEqual(specify.check_amendment(DRAFT, amended(), "O2", [objective("O1"), objective("O2", metric="auroc_noisy")]), [])

    def test_the_amended_spec_still_passes_the_structural_checks(self):
        broken = amended()
        broken["experiments"][-1]["metrics"] = ["brier"]
        self.assertIn("experiment E4 names the metric brier, which the spec does not define",
                      specify.check_amendment(DRAFT, broken, "O2"))


NOISE = "Does the gain survive label noise?"


class AmendCase(ProjectTestCase):
    """The recorded grill's project, the toy spec (its claims name O1) confirmed, then O2 added: the fake launcher in place."""

    autonomy = "interactive"

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "toy").resolve()
        project.init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        research = self.project / "research"
        for name in ("DECISIONS.md", "CONTEXT.md", "journal.jsonl"):
            shutil.copy(RECORDED / "research" / name, research / name)
        shutil.copy(INPUT / "research" / "POSITION.md", research / "POSITION.md")
        shutil.copytree(INPUT / "research" / "refs", research / "refs", dirs_exist_ok=True)
        shutil.copytree(INPUT / "context" / "toy", self.project / "toy")
        self.ledger = Ledger(self.project)
        self.ledger.write_markdown("kb/query_pack.md", "# Query pack\n\n- paper-a extends paper-b\n")
        open_objective(self.project)
        self.ledger.write_json("spec.json", DRAFT, schema="spec")
        self.ledger.write_markdown("SPEC.md", specify.render_spec(DRAFT))
        self.ledger.append_event("verdict", {"subject_kind": "spec", "subject": "research/SPEC.md at %s" % specify.spec_sha(self.project),
                                             "verdict_type": "spec_coverage", "pass": True, "session_id": "verifier-1",
                                             "model": "claude-opus-5", "findings": []})
        project.set_autonomy(self.project, "interactive")
        specify.confirm(self.project, "confirm")
        self.base_sha = specify.spec_sha(self.project)
        objectives.add_objective(self.project, NOISE)
        project.set_autonomy(self.project, self.autonomy)
        self.notified = []
        self.fake = self.enterContext(worker.use_fake())

    def notify(self, event, text, path, ticket):
        self.notified.append((event, ticket, text))

    def script(self, *planner, verdicts=(verdict(),)):
        for envelope in planner:
            self.fake.script(envelope, role=specify.PLANNER)
        for envelope in verdicts:
            self.fake.script(envelope, role=gates.VERIFIER)

    def amend(self, objective="O2"):
        return specify.amend(self.project, objective, notify=self.notify, pre_check=False)

    def calls(self, role):
        return [call for call in self.fake.calls if call.request.role == role]

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def spec(self):
        return json.loads((self.project / "research" / "spec.json").read_text(encoding="utf-8"))

    def state(self, objective="O2"):
        return specify.amendment_state(self.project, objective)

    def ticket(self, identifier):
        return {found["id"]: found for found in tickets.read_tickets(self.project)}[identifier]


class DraftTest(AmendCase):
    """One specify session scoped to the objective appends under new ids; the verifier judges the amendment alone."""

    def test_one_scoped_session_appends_and_the_verifier_judges_the_amendment_alone(self):
        self.script(planned(amended()))
        report = self.amend()
        self.assertIsNone(report["stopped"], report)
        [call] = self.calls(specify.PLANNER)
        prompt = call.request.prompt
        self.assertEqual((call.kind, call.request.model, call.request.effort), ("launch", "opus", "xhigh"))
        self.assertIn("a spec amendment for O2", prompt)
        self.assertIn("- O2: %s" % NOISE, prompt)
        self.assertIn("## Amend", prompt)
        self.assertNotIn("## Plan", prompt)
        self.assertIn('"id": "C3"', prompt, "the spec as it stands, whole, to append to")
        self.assertIn("C4, A3, E4", prompt, "the next free ids")
        self.assertEqual(self.spec(), amended())
        self.assertEqual((self.project / "research" / "SPEC.md").read_text(encoding="utf-8"), specify.render_spec(amended()))
        [judged] = self.events("verdict")[1:]
        sha = specify.spec_sha(self.project)
        self.assertEqual((judged["payload"]["subject"], judged["payload"]["pass"]),
                         ("research/SPEC.md amendment for O2 at %s" % sha, True))
        [check] = self.calls(gates.VERIFIER)
        self.assertIn("C4", check.request.prompt)
        self.assertIn("E4", check.request.prompt)
        self.assertIn("Judge only what the amendment for O2 added", check.request.prompt)
        self.assertEqual(specify.spec_state(self.project)["state"], "confirmed", "the spec stands confirmed: the run goes on")
        state = self.state()
        self.assertEqual((state["state"], state["base"], state["claims"]), ("unasked", self.base_sha, ["C4"]))
        self.assertEqual(self.events("ticket_created"), [], "under interactive the owner confirms before tickets are cut")

    def test_an_amendment_that_rewrites_the_spec_is_returned_once_and_then_nothing_is_written(self):
        rewritten = amended()
        rewritten["claims"][0]["text"] = "Reworded."
        self.script(planned(rewritten), planned(rewritten), verdicts=())
        report = self.amend()
        self.assertIn("failed its checks twice", report["stopped"])
        second = self.calls(specify.PLANNER)[1]
        self.assertEqual(second.kind, "resume")
        self.assertIn("the amendment changes claim C1", second.message)
        self.assertEqual(self.spec(), DRAFT, "nothing written")
        self.assertEqual(self.state()["state"], "none")
        self.script(planned(rewritten), planned(amended()))
        self.assertIsNone(self.amend()["stopped"])
        self.assertEqual(self.spec(), amended())

    def test_a_failed_verdict_is_drafted_again_with_its_findings_and_one_never_taken_is_judged_alone(self):
        from tests.test_specify import FINDING
        self.script(planned(amended()), planned(amended()), verdicts=(verdict(False, [FINDING]), verdict(False, [FINDING])))
        report = self.amend()
        self.assertEqual(report["stopped"], "the verifier failed the amendment twice; it stands unconfirmed")
        self.assertEqual(self.state()["state"], "unverified")
        self.script(planned(amended()))
        self.assertIsNone(self.amend()["stopped"])
        launch = self.calls(specify.PLANNER)[-1]
        self.assertEqual(launch.kind, "launch", "a fresh draft")
        self.assertIn("E2 compares the network", launch.request.prompt)

    def test_amendments_are_made_one_at_a_time(self):
        self.script(planned(amended()))
        self.amend()
        objectives.add_objective(self.project, "Does it hold on images?")
        report = self.amend("O3")
        self.assertIn("the amendment for O2 is unasked, and amendments are made one at a time", report["stopped"])
        self.assertEqual(len(self.calls(specify.PLANNER)), 1)

    def test_an_objective_a_claim_answers_or_one_not_open_needs_no_amendment(self):
        for objective, said in (("O1", "claim C1 answers it already"), ("O7", "no objective O7")):
            with self.subTest(objective=objective):
                report = self.amend(objective)
                self.assertIn(said, report["stopped"])
        self.assertEqual(self.fake.calls, [])


def experiment_ticket(objective="O2"):
    return {"key": "T1", "title": "Run E4: the products at label noise 0.2", "kind": "experiment", "difficulty": 3, "blocked_by": [],
            "touches": ["experiments/e4/", "results/e4/"], "resources": {"gpu": 0, "cpu": 4, "ram_gb": 8, "wallclock_minutes": 30},
            "acceptance": {"machine": ["test -f experiments/e4/run.py"], "quality": []}, "objectives": [objective],
            "context_pack": ["research/SPEC.md#e4-claims-c4"], "origin": "research/SPEC.md#e4-claims-c4",
            "demo": "`results/e4/summary.json` holds ten paired AUROC differences at label noise 0.2."}


def lit_ticket(objective="O2"):
    return {"key": "T2", "title": "Survey label noise and interaction terms", "kind": "lit", "difficulty": 2, "blocked_by": [],
            "touches": [], "acceptance": {"machine": [], "quality": []},
            "objectives": [objective], "context_pack": ["research/OBJECTIVES.md"], "origin": "research/OBJECTIVES.md",
            "demo": "The Introduction gains passages on label noise, each tagged at a dossier's abstract."}


def cut_for(*tickets_):
    return planned({"tickets": list(tickets_) or [experiment_ticket(), lit_ticket()], "decisions": [], "notes": []})


def decided(answer):
    from wayline.worker import Envelope
    return Envelope(structured_output={"question": "as asked", "options": ["confirm"], "answer": answer, "confidence": 0.8,
                                       "decided_by": "decider", "rationale": "The claims answer the objective.", "reversible": True,
                                       "timestamp": None})


class InteractiveTest(AmendCase):
    """Under `interactive` the conversation confirms, and the planner cuts the new claims' tickets after the owner's word."""

    def test_the_owners_word_comes_first_then_the_planner_cuts_the_new_claims_and_a_lit_ticket(self):
        self.script(planned(amended()))
        self.amend()
        state = specify.confirm_amendment(self.project, "O2", "confirm")
        self.assertEqual(state["state"], "uncut")
        [answered] = [event["payload"] for event in self.events("decision") if "amendment O2" in str(event["payload"]["answer"])]
        self.assertEqual(answered["answer"], "amendment O2 at %s: confirm" % state["sha"])
        self.script(cut_for(), verdicts=())
        report = self.amend()
        self.assertIsNone(report["stopped"], report)
        [call] = [call for call in self.calls(specify.PLANNER) if call.request.schema_path.name == "plan.json"]
        self.assertIn("a cut for the spec amendment of objective O2: tickets for its new claims C4 alone", call.request.prompt)
        self.assertIn("a `lit` ticket serving O2", call.request.prompt)
        created = [event["payload"]["ticket"] for event in self.events("ticket_created")]
        self.assertEqual(len(created), 2)
        self.assertEqual([self.ticket(identifier)["objectives"] for identifier in created], [["O2"], ["O2"]])
        self.assertEqual((self.ticket(created[1])["kind"], self.ticket(created[1])["role"]), ("lit", "surveyor"))
        self.assertEqual([fields for fields in tickets.read_tickets(self.project) if fields["kind"] == "decision"], [])
        self.assertFalse((self.project / "research" / "plan.json").exists(), "the graph's own record is not the amendment's")
        state = self.state()
        self.assertEqual((state["state"], state["tickets"]), ("confirmed", created))
        self.assertIsNone(self.amend()["stopped"])
        self.assertEqual(len(self.events("ticket_created")), 2, "run again, nothing is cut twice")

    def test_a_cut_that_strays_from_the_objective_or_skips_the_lit_ticket_is_returned_with_the_failures(self):
        self.script(planned(amended()))
        self.amend()
        specify.confirm_amendment(self.project, "O2", "confirm")
        self.script(cut_for(experiment_ticket("O1")), cut_for(), verdicts=())
        self.assertIsNone(self.amend()["stopped"])
        message = [call for call in self.calls(specify.PLANNER) if call.kind == "resume"][-1].message
        self.assertIn("does not name O2 among its objectives", message)
        self.assertIn("so the cut includes a `lit` ticket serving it", message)

    def test_an_introduction_passage_with_a_ref_tag_on_the_objective_needs_no_lit_ticket(self):
        from wayline import sections
        sections.add_passage(self.project, "introduction", "Label noise",
                             "Label noise erodes interaction gains {ref:paper-a#abstract}.", by="owner", objectives=["O2"])
        self.assertTrue(specify.introduction_covers(self.project, "O2"))
        self.assertFalse(specify.introduction_covers(self.project, "O1"))
        self.script(planned(amended()))
        self.amend()
        specify.confirm_amendment(self.project, "O2", "confirm")
        self.script(cut_for(experiment_ticket()), verdicts=())
        self.assertIsNone(self.amend()["stopped"])
        [call] = [call for call in self.calls(specify.PLANNER) if call.request.schema_path.name == "plan.json"]
        self.assertNotIn("`lit` ticket", call.request.prompt.split("# What you are asked for", 1)[1].split("\n# ", 1)[0])


class CheckpointsTest(AmendCase):
    """Under `checkpoints` a "Confirm the amendment" ticket pauses only the new tickets; the rest of the run keeps going."""

    autonomy = "checkpoints"

    def setUp(self):
        super().setUp()
        from tests.test_plan import fields
        tickets.write_ticket(self.ledger, fields(1, objectives=["O1"]), "## Demo\n\nsrc/1.py exists\n")

    def confirmations(self):
        return [fields for fields in tickets.read_tickets(self.project) if fields["title"] == specify.AMEND_TITLE]

    def test_the_tickets_are_cut_and_only_they_wait_for_the_confirmation(self):
        self.script(planned(amended()), cut_for())
        report = self.amend()
        self.assertIsNone(report["stopped"], report)
        [gate] = self.confirmations()
        state = self.state()
        self.assertEqual((state["state"], state["ticket"]), ("pending", gate["id"]))
        self.assertEqual((gate["blocking"], gate["human_only"]), ("subgraph", False))
        self.assertEqual(gate["origin"], "specify: confirm the amendment for O2 at %s" % state["sha"])
        paused = sorted(fields["id"] for fields in tickets.read_tickets(self.project) if gate["id"] in fields["blocked_by"])
        self.assertEqual(paused, state["tickets"])
        self.assertEqual(self.ticket(1)["blocked_by"], [], "the rest of the run keeps going")
        self.assertEqual(specify.spec_state(self.project)["state"], "confirmed")
        self.assertEqual([fields["title"] for fields in tickets.read_tickets(self.project) if fields["title"] == specify.TITLE], [],
                         "no blocking-all confirmation of the spec")
        self.assertEqual([event for event, ticket, _ in self.notified if ticket == gate["id"]], ["decision_opened"])
        from wayline.project import answer
        answer(self.project, gate["id"], "confirm")
        self.assertEqual(self.state()["state"], "confirmed")

    def test_a_revise_parks_the_new_tickets_and_the_next_amend_drafts_again_from_the_same_base(self):
        from wayline.project import answer
        self.script(planned(amended()), cut_for())
        self.amend()
        first = self.state()
        answer(self.project, first["ticket"], "revise: test it at noise 0.1 too")
        self.assertEqual([self.ticket(identifier)["status"] for identifier in first["tickets"]], ["parked", "parked"])
        self.assertEqual(self.ticket(1)["status"], "open")
        self.assertEqual(self.state()["state"], "revise")
        again = amended()
        again["experiments"][-1]["design"] = "E1 at label noise 0.1 and 0.2, seeds 0-9."
        self.script(planned(again), cut_for())
        report = self.amend()
        self.assertIsNone(report["stopped"], report)
        launch = [call for call in self.calls(specify.PLANNER) if call.request.schema_path.name == "spec.json"][-1]
        self.assertEqual(launch.kind, "launch", "a fresh session")
        self.assertIn("test it at noise 0.1 too", launch.request.prompt)
        self.assertIn('"id": "C3"', launch.request.prompt)
        self.assertNotIn('"id": "C4"', launch.request.prompt, "drafted again from the spec it amends")
        self.assertEqual(self.spec(), again)
        second = self.state()
        self.assertEqual((second["state"], second["base"]), ("pending", self.base_sha))
        self.assertNotEqual(second["tickets"], first["tickets"])
        self.assertEqual(specify.spec_state(self.project)["state"], "confirmed")


class AutonomousTest(AmendCase):
    """Under `autonomous` the decider confirms the amendment at once."""

    autonomy = "autonomous"

    def test_the_decider_confirms_and_the_new_tickets_go_free(self):
        from wayline import decider
        self.script(planned(amended()), cut_for())
        self.fake.script(decided("confirm"), role=decider.DECIDER)
        report = self.amend()
        self.assertIsNone(report["stopped"], report)
        state = self.state()
        self.assertEqual((state["state"], state["decided_by"]), ("confirmed", "decider"))
        self.assertEqual(len(self.calls(decider.DECIDER)), 1)


class VerbTest(AmendCase):
    """`wayline specify --amend <O>` runs the amendment; `confirm --amend` and `revise --amend` record the owner's word."""

    def test_the_verb_drafts_and_the_owners_word_is_recorded(self):
        from tests.test_specify import run
        self.script(planned(amended()))
        code, out, err = run("specify", "--amend", "O2", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("specify --amend O2", out)
        self.assertIn("the amendment: unasked", out)
        self.assertIn("wayline specify confirm --amend O2", out)
        code, out, err = run("specify", "revise", "--amend", "O2", "test it at noise 0.1 too", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("revise", out)
        self.assertEqual(self.state()["feedback"], "test it at noise 0.1 too")
        code, out, err = run("specify", "confirm", "--amend", "O2", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.state()["state"], "uncut", "the last answer given wins")
        code, _, err = run("specify", "--amend", "O1", "--project", str(self.project))
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_an_objective_added_once_the_spec_is_confirmed_names_the_amendment(self):
        from tests.test_specify import run
        code, out, err = run("objective", "add", "Does it hold on images?", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("wayline specify --amend O3", out)


from tests.test_conductor import ConductorCase  # noqa: E402  (the conductor's seam, after the module's own cases)


FEASIBLE = {"verdict": "reachable", "reasoning": "the generator takes a noise level", "revised_target": None}


class ConductorReplayTest(ConductorCase):
    """The conductor replayed: an approved batch's add gets its amendment by the autonomy, once; reopens get none."""

    def setUp(self):
        super().setUp()
        from wayline.project import read_harness
        open_objective(self.project)
        first = self.ticket(1)
        path = tickets.tickets_dir(self.project) / tickets.filename(first)
        _, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(first, difficulty=1, objectives=["O1"]), body)
        spec = copy.deepcopy(DRAFT)
        spec["claims"][1]["objectives"] = ["O1"]
        self.base = spec
        self.ledger.write_json("spec.json", spec, schema="spec")
        self.ledger.write_markdown("SPEC.md", specify.render_spec(spec))
        self.ledger.append_event("verdict", {"subject_kind": "spec", "subject": "research/SPEC.md at %s" % specify.spec_sha(self.project),
                                             "verdict_type": "spec_coverage", "pass": True, "session_id": "verifier-1",
                                             "model": "claude-opus-5", "findings": []})
        project.set_autonomy(self.project, "interactive")
        specify.confirm(self.project, "confirm")
        harness = read_harness(self.project)
        harness.update(stop_when="frontier")
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.fake = self.enterContext(worker.use_fake())
        self.sent = []

    def autonomy(self, value):
        project.set_autonomy(self.project, value)

    def approve(self, *stated):
        from wayline import objective_changes
        from wayline.project import answer
        objective_changes.take_verdict(self.project, 1, 1, "result", list(stated))
        objective_changes.settle(self.project, notify=lambda *args: None)
        ticket = [fields for fields in tickets.read_tickets(self.project) if objective_changes.is_changes_ticket(fields.get("origin"))][-1]
        answer(self.project, ticket["id"], "approve all")

    def run_conductor(self, waves=4, launches=True):
        import io
        from unittest import mock
        from tests import machine
        from tests.test_conductor import drive
        from wayline.conductor import Conductor
        conductor = Conductor(self.project, out=io.StringIO())
        conductor.readings = machine.recorded
        conductor.notify = lambda *args: self.sent.append(args)
        conductor.plan_pre_check = False
        self.picked = []
        if launches:
            return drive(conductor, waves)
        with mock.patch.object(Conductor, "_start", lambda self_, picks, result: self.picked.extend(pick["id"] for pick in picks)):
            return drive(conductor, waves)

    def script_work(self):
        from tests.test_conductor import done, patch
        self.fake.script(done(), patch=patch(), role="coder")

    def planner_calls(self, schema):
        return [call for call in self.fake.calls if call.request.role == specify.PLANNER and call.request.schema_path.name == schema]

    def state(self):
        return specify.amendment_state(self.project, "O2")

    def test_under_checkpoints_the_conductor_amends_cuts_and_asks_while_the_rest_runs_and_does_nothing_twice(self):
        self.autonomy("checkpoints")
        self.approve({"kind": "add", "objective": NOISE, "reason": "the sweep raises it", "evidence": [], "feasibility": FEASIBLE})
        self.fake.script(planned(amended(self.base)), role=specify.PLANNER)
        self.fake.script(verdict(), role=gates.VERIFIER)
        self.fake.script(cut_for(), role=specify.PLANNER)
        self.script_work()
        self.run_conductor()
        self.assertEqual(objectives.named(objectives.read_objectives(self.project), "O2")["text"], NOISE)
        state = self.state()
        self.assertEqual(state["state"], "pending")
        self.assertEqual(self.ticket(1)["status"], "done", "the rest of the run kept going")
        for identifier in state["tickets"]:
            self.assertEqual((self.ticket(identifier)["status"], self.ticket(identifier)["blocked_by"]), ("open", [state["ticket"]]))
        self.assertEqual([event["payload"]["ticket"] for event in self.events("ticket_launched")], [1])
        self.assertEqual((len(self.planner_calls("spec.json")), len(self.planner_calls("plan.json"))), (1, 1))
        calls = len(self.fake.calls)
        self.run_conductor()
        self.assertEqual(len(self.fake.calls), calls, "a restarted conductor drafts, judges, and cuts nothing twice")
        self.assertEqual(len([fields for fields in tickets.read_tickets(self.project) if fields["title"] == specify.AMEND_TITLE]), 1)

    def test_under_interactive_the_conductor_drafts_and_the_owner_is_told_the_amendment_waits_on_their_word(self):
        self.autonomy("interactive")
        self.approve({"kind": "add", "objective": NOISE, "reason": "the sweep raises it", "evidence": [], "feasibility": FEASIBLE})
        self.fake.script(planned(amended(self.base)), role=specify.PLANNER)
        self.fake.script(verdict(), role=gates.VERIFIER)
        self.script_work()
        self.run_conductor()
        self.assertEqual(self.state()["state"], "unasked")
        told = [text for _, text, _, _ in self.sent if "amendment" in text]
        self.assertEqual(len(told), 1)
        self.assertIn("wayline specify confirm --amend O2", told[0])
        self.run_conductor()
        self.assertEqual(len([text for _, text, _, _ in self.sent if "amendment" in text]), 1, "told once")
        specify.confirm_amendment(self.project, "O2", "confirm")
        self.fake.script(cut_for(), role=specify.PLANNER)
        self.run_conductor(launches=False)
        state = self.state()
        self.assertEqual(state["state"], "confirmed")
        self.assertEqual(sorted(self.picked), sorted(state["tickets"]), "confirmed first, the new tickets run at once")

    def test_under_autonomous_the_decider_confirms_in_the_same_wave_and_nothing_holds_the_new_tickets(self):
        from wayline import decider
        self.autonomy("autonomous")
        self.approve({"kind": "add", "objective": NOISE, "reason": "the sweep raises it", "evidence": [], "feasibility": FEASIBLE})
        self.fake.script(planned(amended(self.base)), role=specify.PLANNER)
        self.fake.script(verdict(), role=gates.VERIFIER)
        self.fake.script(cut_for(), role=specify.PLANNER)
        self.fake.script(decided("confirm"), role=decider.DECIDER)
        self.run_conductor(waves=1, launches=False)
        state = self.state()
        self.assertEqual((state["state"], state["decided_by"]), ("confirmed", "decider"))
        self.assertEqual(self.events("run_ended"), [], "the run goes on")
        self.run_conductor(waves=1, launches=False)
        self.assertIn(self.ticket(state["ticket"])["status"], tickets.SATISFIED, "the answered confirmation holds nothing")
        for identifier in state["tickets"]:
            self.assertEqual(self.ticket(identifier)["blocked_by"], [state["ticket"]])

    def test_a_usage_window_that_refuses_the_amendment_pauses_the_run_and_one_that_raises_fails_no_wave(self):
        import io
        from tests import machine
        from tests.test_conductor import drive
        from wayline.conductor import Conductor
        self.autonomy("checkpoints")
        self.approve({"kind": "add", "objective": NOISE, "reason": "the sweep raises it", "evidence": [], "feasibility": FEASIBLE})
        self.script_work()
        conductor = Conductor(self.project, out=io.StringIO())
        conductor.readings = machine.recorded
        conductor.notify = lambda *args: self.sent.append(args)
        conductor.amender = lambda identifier, fall_back: {
            "did": [], "stopped": "the usage limit refused a session", "failures": [], "state": None, "autonomy": "checkpoints",
            "waits": gates.UsageLimited("refused until noon", pacing.Limit("message", 4102444800, "five_hour", None))}
        drive(conductor, 1)
        self.assertTrue(self.events("paused"), "the window's refusal pauses the run, as a refused cut does")

    def test_an_amendment_step_that_raises_fails_no_wave_and_the_owner_is_told(self):
        import io
        from tests import machine
        from tests.test_conductor import drive
        from wayline.conductor import Conductor
        self.autonomy("checkpoints")
        self.approve({"kind": "add", "objective": NOISE, "reason": "the sweep raises it", "evidence": [], "feasibility": FEASIBLE})
        self.script_work()

        def broken(identifier, fall_back):
            raise ValueError("a ticket file the harness cannot read")
        conductor = Conductor(self.project, out=io.StringIO())
        conductor.readings = machine.recorded
        conductor.notify = lambda *args: self.sent.append(args)
        conductor.amender = broken
        drive(conductor, 2)
        self.assertIn("could not be made: a ticket file the harness cannot read", conductor.out.getvalue())
        self.assertEqual(len([text for _, text, _, _ in self.sent if "could not be made" in text]), 1, "told once, not tried again")

    def test_reopening_a_parked_objective_brings_its_claims_back_with_no_amendment(self):
        from wayline.objectives import add_objective, change_objective
        self.autonomy("checkpoints")
        add_objective(self.project, NOISE)
        spec = json.loads((self.project / "research" / "spec.json").read_text(encoding="utf-8"))
        change_objective(self.project, "O2", "parked", "owner", answer="later")
        self.assertNotRegex((self.project / "research" / "SPEC.md").read_text(encoding="utf-8"), r"set aside",
                            "no claim names O2 yet")
        spec["claims"][2]["objectives"] = ["O2"]
        self.ledger.write_json("spec.json", spec, schema="spec")
        specify.render_set_aside(self.project)
        self.assertRegex((self.project / "research" / "SPEC.md").read_text(encoding="utf-8"), r"\*\*C3\.\*\*.*set aside")
        self.approve({"kind": "reopen", "objective": "O2", "reason": "the data arrived", "evidence": []})
        self.script_work()
        self.run_conductor()
        self.assertEqual(objectives.named(objectives.read_objectives(self.project), "O2")["status"], "open")
        self.assertNotIn("set aside", (self.project / "research" / "SPEC.md").read_text(encoding="utf-8"))
        self.assertEqual(self.planner_calls("spec.json") + self.planner_calls("plan.json"), [], "no amendment, no cut")
        self.assertEqual(specify.read_amendments(self.project), [])
        self.assertEqual(specify.owed_amendments(self.project), [])

    def test_the_owners_reopen_of_an_answered_objective_keeps_the_old_answer_and_has_the_planner_cut_fresh_tickets_once(self):
        from wayline import objective_changes
        from wayline.objectives import change_objective
        self.autonomy("checkpoints")
        change_objective(self.project, "O1", "answered", "owner", answer="the products add nothing")
        objective_changes.apply_change(self.project, {"kind": "reopen", "objective": "O1"}, "owner")
        found = objectives.named(objectives.read_objectives(self.project), "O1")
        self.assertEqual((found["status"], found["superseded"][0]["answer"]), ("open", "the products add nothing"))
        self.fake.script(cut_for(experiment_ticket("O1")), role=specify.PLANNER)
        self.run_conductor(launches=False)
        [cut] = self.planner_calls("plan.json")
        self.assertIn("The owner reopened the objective(s) O1", cut.request.prompt)
        self.assertEqual(self.planner_calls("spec.json"), [], "a reopen needs no amendment")
        self.run_conductor(launches=False)
        self.assertEqual(len(self.planner_calls("plan.json")), 1, "the fresh tickets are cut once")


if __name__ == "__main__":
    unittest.main()
