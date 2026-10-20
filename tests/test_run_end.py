"""The run-end gates (Implementation Decision 17; ticket 103).

Two seams. `wayline.run_end` over a copy of the ended run (`fixtures/projects/ended-run/`): the sampled verdicts and the
kill argument on the general report, every session through the fake launcher, read back from the journal, the sample
cache, and the scope-downs filed. And the conductor over the one-ticket fixture with findings filed, the fake launcher
scripting the classifier, the plotter, the verifier, and both threads of the kill argument, read back from the journal
each end kind writes and from the tick's relaunch decision over it, a replayed wave included.
"""

import io
import json
import sys
import time
from unittest import mock

from tests import machine
from tests.test_conductor import ConductorCase, done, drive
from tests.test_drawings import DrawingRunCase
from tests.test_report import Classifier, RunCase, verdict
from tests.test_results import file
from wayline import project as projects
from wayline import drawings, gates, provenance, run_end, tick, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.objectives import add_objective, change_objective

R1 = "Do the products raise the AUROC?"
CLAIM_ASKED = "Do the cited artifacts, at their locators, support this sentence"
HOUR = 3600
ORIGINAL = "`t1-a1-f1` The products"  # the first finding as the report lists it; its replacement names it too


def passing(request, message):
    return verdict()


def failing_on(marker):
    """The verifier: a claim verdict on the sentence carrying `marker` fails; every other verdict passes."""
    def respond(request, message):
        return verdict(passed=not (CLAIM_ASKED in request.prompt and marker in request.prompt),
                       text="The artifact holds 0.71 on one seed only.", locator="results/summary.json#auroc")
    return respond


class SampleCase(RunCase):
    """The ended run, its report rendered and every sentence classified."""

    def setUp(self):
        super().setUp()
        self.render()

    def sample(self, respond=passing, scripted=40):
        with worker.use_fake() as fake:
            for _ in range(scripted):
                fake.script(respond=respond, role="verifier")
            outcome = run_end.sampled_verdicts(self.project)
            self.calls = list(fake.calls)
        return outcome


class SampleCacheTest(SampleCase):
    def test_a_rerun_with_no_new_claims_samples_nothing(self):
        first = self.sample()
        self.assertEqual(first["sampled"], 5, "five claims never sampled: all of them, since at least ten are read")
        self.assertEqual(len(self.calls), 5)
        second = self.sample()
        self.assertEqual((second["new"], second["sampled"]), (0, 0))
        self.assertEqual(self.calls, [], "nothing launched")

    def test_only_claims_never_sampled_are_taken(self):
        self.sample()
        self.book.append_record("findings.jsonl", {
            "id": "f-0006", "ticket": 1, "text": "The disagreement is 3.1 percent on the second split too.",
            "provenance": ["results/features/summary.json#label_disagreement"], "negative": False,
            "heading": "Do the two label sources agree?", "ts": "2026-09-12T05:00:00.000Z"})
        self.render()
        outcome = self.sample()
        self.assertEqual((outcome["new"], outcome["sampled"]), (1, 1))
        [call] = self.calls
        self.assertIn("`f-0006`", call.request.prompt)

    def test_ten_percent_of_the_new_claims_at_least_ten_plus_every_difficulty_5_claim(self):
        self.sample()
        for number in range(30):
            self.add("f-1%03d" % number, 1, "Seed %d leaves the disagreement at 3.1 percent." % number)
        for number in range(2):
            self.add("f-2%03d" % number, 3, "The interaction gain holds on fold %d." % number)
        self.render()
        outcome = self.sample()
        self.assertEqual((outcome["new"], outcome["sampled"]), (32, 12), "ten of the thirty, and both difficulty-5 claims")
        prompts = " ".join(call.request.prompt for call in self.calls)
        for number in range(2):
            self.assertIn("`f-2%03d`" % number, prompts)

    def test_a_failing_claim_files_a_scope_down_that_names_the_finding_it_narrows(self):
        outcome = self.sample(lambda request, message: verdict(passed="`f-0002`" not in request.prompt))
        [identifier] = outcome["tickets"]
        fields = {entry["id"]: entry for entry in tickets.read_tickets(self.project)}[identifier]
        self.assertTrue(run_end.is_scope_down(fields))
        self.assertEqual(fields["sections"], ["results"], "a scope-down returns findings")
        self.assertEqual(run_end.targets(fields), ["f-0002"])
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        self.assertIn("`replaces`", body)
        finding = {"text": "The baseline reaches 0.812.", "provenance": "results/baseline/summary.json#auroc_mean",
                   "heading": "Do interaction terms raise the held-out AUROC?"}
        self.assertEqual(run_end.check_scope_down(fields, {"findings": [dict(finding, replaces="f-0002")]}), [])
        self.assertTrue(run_end.check_scope_down(fields, {"findings": [dict(finding, replaces=None)]}))
        self.assertTrue(run_end.check_scope_down(fields, {"findings": [dict(finding, replaces="f-0001")]}))
        self.assertTrue(run_end.check_scope_down(fields, {"findings": []}))

    def argue(self, memo=passing, adjudication=passing):
        with worker.use_fake() as fake:
            fake.script(respond=memo, role="verifier")
            fake.script(respond=adjudication, role="verifier")
            taken = run_end.kill_argument(self.project)
            self.calls = list(fake.calls)
        return taken

    def kills(self):
        return [event["payload"] for event in self.events("verdict") if event["payload"]["verdict_type"] == "kill_argument"]

    def test_the_kill_argument_runs_on_the_general_report_and_not_again_while_it_is_unchanged(self):
        taken = self.argue()
        self.assertTrue(taken.passed)
        self.assertEqual(len(self.calls), 2, "the memo and its adjudication, two sessions")
        [kill] = self.kills()
        self.assertEqual(kill["subject_kind"], "report")
        self.assertTrue(kill["subject"].startswith("research/REPORT.md#kill-"))
        self.assertIn("research/REPORT.md", self.calls[0].request.prompt)
        self.render()  # the records change at every render; the report does not
        self.assertIsNone(self.argue())
        self.assertEqual(self.calls, [])
        self.add("f-0006", 1, "The disagreement is 3.1 percent on the second split too.")
        self.render()
        self.assertTrue(self.argue().passed, "a changed report is argued again")
        self.assertEqual(len(self.kills()), 2)

    def test_a_failed_kill_argument_files_one_scope_down_naming_the_findings_it_may_narrow(self):
        standing = lambda request, message: verdict(False, text="The gain is one split's.")
        taken = self.argue(memo=standing, adjudication=standing)
        self.assertFalse(taken.passed)
        [fields] = run_end.scope_downs(self.project)
        self.assertEqual((fields["origin"], fields["sections"], fields["touches"]), (run_end.KILL_ORIGIN, ["results"], []))
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        self.assertIn("The gain is one split's.", body)
        self.assertIn("`f-0003`", body)
        self.assertIn("`replaces`", body)
        self.add("f-0006", 1, "The disagreement is 3.1 percent on the second split too.")
        self.render()
        self.argue(memo=standing, adjudication=standing)
        self.assertEqual(len(run_end.scope_downs(self.project)), 1, "one open at a time")

    def add(self, identifier, ticket, text):
        artifact = "results/interactions/summary.json#auroc_mean" if ticket == 3 else "results/features/summary.json#label_disagreement"
        self.book.append_record("findings.jsonl", {
            "id": identifier, "ticket": ticket, "text": text, "provenance": [artifact], "negative": False,
            "heading": "Do the two label sources agree?", "ts": "2026-09-12T05:00:00.000Z"})


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, event, text, project=None, ticket=None):
        self.sent.append((event, text, ticket))


def narrowed(ticket, replaces="t1-a1-f1"):
    """The writer's result on a scope-down: the finding narrowed, naming the one it narrows."""
    return done(ticket, summary="narrowed the claim to one seed", outputs_written=[], findings=[{
        "text": "On one seed the products raise the AUROC to 0.71.", "provenance": "results/summary.json#auroc",
        "heading": R1, "replaces": replaces}])


class GatesRunCase(ConductorCase):
    """The conductor at a run end over the one-ticket fixture: ticket 1 done, one finding filed, the general report
    rendered; no drawing (no plotting interpreter), so the gates are what the end waits on."""

    def setUp(self):
        super().setUp()
        fields = self.ticket(1)
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))
        tickets.write_ticket(self.ledger, dict(fields, status="done"), body)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71, "loss": 0.25}\n', encoding="utf-8")
        provenance.register_artifact(self.ledger, "results/summary.json", None, "t1-a1", 1)
        file(self.ledger, "t1-a1-f1", "The products raise the AUROC to 0.71.", R1, ticket=1)
        provenance.render_report(self.project, offline=True)
        self.recorder = Recorder()
        self.commit("the finding")

    def ticket(self, identifier):
        return {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[identifier]

    def commit(self, message):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)

    def close_the_objective(self, other=True):
        add_objective(self.project, R1)
        change_objective(self.project, "O1", "answered", "owner", answer="Yes.", evidence=["res:t1-a1/results/summary.json#auroc"])
        if other:
            other = dict(self.ticket(1), id=2, status="open", title="Write another file", touches=["other.txt"], outputs=["other.txt"])
            tickets.write_ticket(self.ledger, other, "\nAnother.\n")
        self.commit("an objective answered")

    def started(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": 1})

    def set_harness(self, **changes):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness.update(changes)
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.commit("the harness")

    def conduct(self, verifier=passing, writer=(), clock=None, waves=16):
        with worker.use_fake() as fake:
            for _ in range(6):
                fake.script(respond=Classifier(), role="classifier")
            for _ in range(24):
                fake.script(respond=verifier, role="verifier")
            for envelope in writer:
                fake.script(envelope, role="writer")
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.drawing_python = None
            self.conductor.notify = self.recorder
            if clock is not None:
                self.conductor.clock = clock
            results = []
            while len(results) < waves and not (results and results[-1].ended):
                results += drive(self.conductor, 1)
                self.conductor.settle()
            self.calls = list(fake.calls)
        return results

    def verdicts(self, kind=None):
        return [event["payload"] for event in self.events("verdict")
                if kind is None or event["payload"]["verdict_type"] == kind]

    def index(self, name, predicate=lambda payload: True):
        events = self.events()
        return [position for position, event in enumerate(events) if event["event"] == name and predicate(event["payload"])]

    def report(self):
        return (self.project / provenance.REPORT_PATH).read_text(encoding="utf-8")

    def ended(self):
        return [event["payload"]["reason"] for event in self.events("run_ended")]


class FrontierEmptyTest(GatesRunCase):
    def test_the_gates_run_sampled_verdicts_then_the_kill_argument_before_the_run_ends_and_its_notice(self):
        results = self.conduct()
        self.assertEqual(self.ended(), ["frontier_empty"])
        [claim] = self.index("verdict", lambda payload: payload["verdict_type"] == "claim_support")
        [kill] = self.index("verdict", lambda payload: payload["verdict_type"] == "kill_argument")
        [end] = self.index("run_ended")
        self.assertLess(claim, kill)
        self.assertLess(kill, end)
        self.assertTrue(results[-1].ended)
        self.assertEqual([event for event, _, _ in self.recorder.sent], ["run_ended"], "one end notice, after the gates")

    def test_a_failing_claim_continues_the_run_with_its_scope_down_until_no_gate_is_owed(self):
        self.conduct(verifier=failing_on(ORIGINAL), writer=[narrowed(2)])
        [fields] = run_end.scope_downs(self.project)
        self.assertEqual(fields["id"], 2)
        self.assertIn(fields["status"], ("done", "accepted"))
        current = [finding["id"] for finding in provenance.current_findings(self.project)]
        self.assertEqual(current, ["t2-a1-f1"], "the narrowed finding replaces the one it narrows")
        self.assertEqual(self.ended(), ["frontier_empty"])
        self.assertEqual(len(self.verdicts("kill_argument")), 2, "the report changed, so it was argued again")
        claims = self.verdicts("claim_support")
        self.assertEqual([payload["pass"] for payload in claims], [False, True], "the narrowed claim was never sampled")
        runs = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8").split("## Runs")[1]
        self.assertIn("The run-end gates:", runs)
        self.assertIn("`claim_support` on the claim", runs)
        self.assertIn("`kill_argument` on the report", runs)
        self.assertIn("scoped down by ticket 2", runs)


class RuleEndTest(GatesRunCase):
    def test_at_objectives_closed_only_the_scope_down_runs_and_the_run_ends_once_no_gate_is_owed(self):
        self.close_the_objective()
        self.conduct(verifier=failing_on(ORIGINAL), writer=[narrowed(3)])
        launched = [event["payload"]["ticket"] for event in self.events("ticket_launched")]
        self.assertEqual(launched, [3], "the scope-down alone, never ticket 2")
        self.assertEqual(self.ended(), ["objectives_closed"])
        [end] = self.index("run_ended")
        self.assertLess(max(self.index("verdict")), end)

    def test_the_tick_relaunches_a_run_that_continues_for_its_scope_down_and_not_one_that_ended(self):
        self.close_the_objective()
        self.started()
        with mock.patch.object(Conductor, "_start", lambda self, picks, result: None):
            self.conduct(verifier=failing_on(ORIGINAL), waves=1)  # the conductor dies with the scope-down filed
        self.assertEqual(self.ended(), [])
        self.assertTrue(run_end.scope_downs(self.project))
        reason, why = tick.relaunch_decision(self.project, self.ledger, self.conductor.policy, None, time.time())
        self.assertIsNotNone(reason, why)
        self.assertIn("scope-down", reason)
        self.conduct(verifier=failing_on(ORIGINAL), writer=[narrowed(3)])
        self.assertEqual(self.ended(), ["objectives_closed"])
        reason, why = tick.relaunch_decision(self.project, self.ledger, self.conductor.policy, None, time.time())
        self.assertIsNone(reason)
        self.assertIn("objectives_closed", why)

    def test_a_replayed_wave_takes_no_gate_twice(self):
        self.close_the_objective()
        self.conduct(verifier=failing_on(ORIGINAL), writer=[narrowed(3)], waves=1)  # dies with the scope-down's result
        gated = lambda: [payload for payload in self.verdicts() if payload["subject"].startswith("research/REPORT.md#")]
        taken = gated()
        self.assertEqual([payload["verdict_type"] for payload in taken], ["claim_support", "kill_argument"])
        self.conduct(verifier=failing_on(ORIGINAL), waves=1)  # a new conductor replays the journal and carries it
        self.assertEqual(gated(), taken, "no gate is taken again")
        self.assertEqual(len(run_end.scope_downs(self.project)), 1, "no scope-down is filed again")
        self.assertIn(self.ticket(3)["status"], ("done", "accepted"), "the replayed wave carried the scope-down")
        self.assertEqual(self.ended(), [])
        self.conduct(verifier=failing_on(ORIGINAL))
        self.assertEqual(self.ended(), ["objectives_closed"])
        self.assertEqual([payload["verdict_type"] for payload in gated()][2:], ["claim_support", "kill_argument"],
                         "after the scope-down only the narrowed claim and the changed report are owed a gate")


class OnceEndTest(GatesRunCase):
    def test_after_budget_spent_the_gates_run_once_their_scope_down_waits_and_the_claim_is_marked(self):
        self.set_harness(budgets={"wallclock_hours": 1})
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": 1})
        self.conduct(verifier=failing_on(ORIGINAL), clock=lambda: time.time() + 2 * HOUR)
        self.assertEqual(self.ended(), ["budget_spent"])
        [fields] = run_end.scope_downs(self.project)
        self.assertEqual(fields["status"], "open", "it waits for the next run")
        self.assertEqual(self.events("ticket_launched"), [])
        [end] = self.index("run_ended")
        self.assertLess(max(self.index("verdict")), end)
        banner = self.report().split("## 1.")[0]
        self.assertIn("ticket %d" % fields["id"], banner)
        self.assertIn("The products raise the AUROC to 0.71.", banner)

    def test_after_a_strict_stall_the_gates_run_once_and_the_run_ends_stall_strict(self):
        self.ledger.append_event("stall", {"waves": 3, "action": "stop"})
        self.conduct(verifier=failing_on(ORIGINAL))
        self.assertEqual(self.ended(), ["stall_strict"])
        [fields] = run_end.scope_downs(self.project)
        self.assertEqual(fields["status"], "open")
        self.assertEqual(self.events("ticket_launched"), [])
        self.assertTrue(self.verdicts("kill_argument"))


class RuleEndEdgeTest(GatesRunCase):
    def test_a_rule_end_resting_on_a_scope_down_with_the_frontier_empty_ends_with_the_rules_reason(self):
        self.close_the_objective(other=False)
        self.conduct(verifier=failing_on(ORIGINAL), writer=[narrowed(2)])
        self.assertEqual(self.ended(), ["objectives_closed"], "never frontier_empty while the rule's end holds")

    def test_the_kill_argument_runs_at_most_max_rounds_times_in_a_run_and_its_last_scope_down_waits(self):
        self.close_the_objective()
        standing = lambda request, message: verdict(passed=not any(question in request.prompt for question in (
            gates.MEMO_QUESTION, gates.ADJUDICATION_QUESTION)), text="The gain is one seed's.", locator="results/summary.json#auroc")
        self.conduct(verifier=standing, writer=[narrowed(3), narrowed(4, replaces="t3-a1-f1")], waves=24)
        self.assertEqual(self.ended(), ["objectives_closed"])
        self.assertEqual(len(self.verdicts("kill_argument")), run_end.MAX_ROUNDS)
        last = run_end.scope_downs(self.project)[-1]
        self.assertEqual((last["status"], last["origin"]), ("open", run_end.KILL_ORIGIN), "the last waits for the next run")
        self.assertIn("scope-down ticket %d" % last["id"], self.report().split("## 1.")[0])


class OwedTest(SampleCase):
    def test_a_scope_down_failed_and_waiting_on_its_step_is_still_owed(self):
        outcome = self.sample(lambda request, message: verdict(passed="`f-0002`" not in request.prompt))
        [identifier] = outcome["tickets"]
        fields = {entry["id"]: entry for entry in tickets.read_tickets(self.project)}[identifier]
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        tickets.write_ticket(self.book, dict(fields, status="failed"), body)
        self.book.append_event("ticket_failed", {"ticket": identifier, "attempt": 1, "reason": "x", "next": "resume"}, ticket=identifier)
        self.assertIn("1 scope-down(s) of the run-end gates", run_end.owed(self.project))

    def test_a_claims_scope_down_that_names_no_finding_wants_findings_without_replaces(self):
        fields = {"kind": "writing", "proposed_by": "verifier", "origin": "research/REPORT.md#claim-0123456789abcdef", "inputs": []}
        finding = {"text": "It holds on one seed.", "provenance": "results/x.json#k", "heading": "H", "replaces": None}
        self.assertEqual(run_end.check_scope_down(fields, {"findings": [finding]}), [])
        self.assertTrue(run_end.check_scope_down(dict(fields, origin=run_end.KILL_ORIGIN), {"findings": [finding]}))


class NoGateTest(GatesRunCase):
    def test_after_stopped_or_switched_no_gate_runs(self):
        for args, reason in (({"drain": False}, "stopped"), ({"drain": True, "switch_to": "/elsewhere"}, "switched")):
            with self.subTest(reason=reason):
                self.setUp()
                self.close_the_objective()
                projects.control(self.project, "stop", args)
                self.conduct()
                self.assertEqual(self.ended(), [reason])
                self.assertEqual(self.verdicts(), [])
                self.assertEqual([call.request.role for call in self.calls], [])


class DrawingsFirstTest(DrawingRunCase):
    def test_the_drawings_come_first_then_the_sampled_verdicts_then_the_kill_argument(self):
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role=drawings.ROLE)
            for _ in range(3):
                fake.script(respond=Classifier(), role="classifier")
            for _ in range(6):
                fake.script(respond=passing, role="verifier")
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.drawing_python = sys.executable
            results = []
            while len(results) < 12 and not (results and results[-1].ended):
                results += drive(self.conductor, 1)
                self.conductor.settle()
        order = [(event["event"], (event["payload"].get("outcome") or event["payload"].get("verdict_type")))
                 for event in self.events() if event["event"] in ("drawing", "verdict", "run_ended")]
        steps = [step for step in order if step in (("drawing", "accepted"), ("verdict", "claim_support"),
                                                    ("verdict", "kill_argument"), ("run_ended", None))]
        self.assertEqual(steps, [("drawing", "accepted"), ("verdict", "claim_support"), ("verdict", "kill_argument"),
                                 ("run_ended", None)])
        self.assertEqual(self.payload("run_ended")["reason"], "frontier_empty")
