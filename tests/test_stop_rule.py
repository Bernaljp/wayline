"""The stopping rule, the budgets, and the empty frontier in the conductor (Implementation Decision 17; ticket 87).

Each test drives the conductor on the one-ticket fixture with the fake worker and reads back what the owner and the
tick read: the journal's `run_ended`, the decision tickets an empty frontier opened and their answers, the objectives'
records, and the tick's relaunch decision. `tests/test_stopping.py` covers the rule and the budgets as plain functions.
"""

import io
import json
import time

from tests import machine
from tests.projects import open_objective
from tests.test_conductor import ConductorCase, done, drive, patch
from tests.test_decider import envelope
from wayline import decider, project, stopping, tick, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import now_ts
from wayline.objectives import change_objective, read_objectives
from wayline.project import answer, read_harness

HOUR = 3600


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, event, text, project=None, ticket=None):
        self.sent.append((event, text, ticket))


class StopRuleCase(ConductorCase):
    def setUp(self):
        super().setUp()
        self.recorder = Recorder()
        self.planned = []

    def set_harness(self, **changes):
        harness = read_harness(self.project)
        harness.update(changes)
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def serve(self, *objectives):
        """Ticket 1 serves `objectives`."""
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, objectives=list(objectives)), body)

    def planner(self, cut, fall_back):
        """The planner's cut, recorded: `plan.json` says when it was written, as a real cut's does."""
        self.planned.append(cut)
        self.ledger.write_json("plan.json", {"sha": "cut-%d" % len(self.planned), "cut_at": now_ts(), "cut": cut.kind})
        return {"tickets": [], "superseded": []}

    def conduct(self, *scripted, waves=None, clock=None, decider_answers=()):
        with worker.use_fake() as fake:
            for envelope_, applied in scripted:
                fake.script(envelope_, patch=applied)
            for answer_ in decider_answers:
                fake.script(envelope(answer_), role=decider.DECIDER)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.notify = self.recorder
            self.conductor.planner = self.planner
            if clock is not None:
                self.conductor.clock = clock
            results = []
            while True:  # past a wave that left nothing in flight too: the decider takes an empty frontier at the next wave
                results.extend(drive(self.conductor, 1))
                if results[-1].ended or (waves is not None and len(results) >= waves) or len(results) >= 12:
                    break
                self.conductor.settle()
            self.calls = list(fake.calls)
        return results

    def ended(self):
        return [event["payload"]["reason"] for event in self.events("run_ended")]

    def said(self):
        return self.conductor.out.getvalue()

    def frontier_tickets(self):
        return [fields for fields in tickets.read_tickets(self.project) if stopping.frontier_objective(fields.get("origin"))]

    def record(self, ticket):
        from wayline.decisions import decision_record
        fields = {entry["id"]: entry for entry in tickets.read_tickets(self.project)}[ticket]
        return decision_record(tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1])

    def objective(self, identifier):
        return {record["id"]: record for record in read_objectives(self.project)}[identifier]

    def relaunch(self, now=None):
        return tick.relaunch_decision(self.project, self.ledger, self.conductor.policy, None, now or time.time())


class RuleTest(StopRuleCase):
    def test_with_no_objective_open_the_run_ends_objectives_closed_before_it_launches_anything(self):
        open_objective(self.project)
        change_objective(self.project, "O1", "answered", "owner", answer="the owner answered it")
        results = self.conduct()
        self.assertEqual((results[-1].reason, self.ended()), ("objectives_closed", ["objectives_closed"]))
        self.assertNotIn("ticket_launched", self.sequence())
        self.assertEqual([event for event, _, _ in self.recorder.sent], ["run_ended"])
        self.assertIn("the objectives the stopping rule waits on are closed (O1)", self.recorder.sent[0][1])

    def test_a_list_rule_ends_once_the_objectives_it_names_are_closed(self):
        open_objective(self.project, "First?")
        open_objective(self.project, "Second?")
        change_objective(self.project, "O2", "dropped", "owner", answer="not worth it")
        self.set_harness(stop_when=["O2"])
        self.assertEqual(self.conduct()[-1].reason, "objectives_closed")

    def test_a_list_rule_waits_while_one_it_names_is_open(self):
        open_objective(self.project, "First?")
        open_objective(self.project, "Second?")
        change_objective(self.project, "O2", "dropped", "owner", answer="not worth it")
        self.set_harness(stop_when=["O1", "O2"], autonomy="checkpoints")
        self.conduct((done(), patch()))
        self.assertIn("ticket_done", self.sequence())
        self.assertEqual(self.ended(), ["frontier_empty"])

    def test_the_rule_is_read_every_wave(self):
        open_objective(self.project)
        results = self.conduct((done(), patch()), waves=1)
        self.assertFalse(results[-1].ended)
        change_objective(self.project, "O1", "parked", "owner", answer="later")
        self.conductor.settle()
        self.assertEqual(self.conductor.wave().reason, "objectives_closed")

    def test_under_frontier_no_ticket_opens_and_the_end_notice_lists_the_open_objectives(self):
        open_objective(self.project, "First?")
        open_objective(self.project, "Second?")
        change_objective(self.project, "O2", "answered", "owner", answer="yes")
        self.set_harness(stop_when="frontier")
        results = self.conduct((done(), patch()))
        self.assertEqual(results[-1].reason, "frontier_empty")
        self.assertEqual(self.frontier_tickets(), [])
        self.assertNotIn("decision_opened", self.sequence())
        notices = [text for event, text, _ in self.recorder.sent if event == "run_ended"]
        self.assertEqual(len(notices), 1)
        self.assertIn("the objectives still open: O1", notices[0])

    def test_a_project_that_records_no_objective_runs_to_its_frontier(self):
        self.assertEqual(self.conduct((done(), patch()))[-1].reason, "frontier_empty")
        self.assertEqual(self.frontier_tickets(), [])

    def test_a_goal_json_is_read_by_nobody(self):
        """A project holding a GOAL.json runs as if it were absent: its `stop_when` ends nothing, its metric judges nothing."""
        (self.project / "research" / "GOAL.json").write_text(json.dumps({
            "metric": "auroc", "direction": "up", "target": 0.0, "held_out_split": None, "eval_command": "echo auroc: 1",
            "dataset_or_split": None, "baseline": {"value": None, "source": None},
            "budget": {"gpu_hours": 0, "wallclock": 0, "usage_windows": 0}, "stop_when": "goal_reached"}), encoding="utf-8")
        results = self.conduct((done(), patch()))
        self.assertEqual(results[-1].reason, "frontier_empty")
        self.assertNotIn("progress", self.sequence())


class BudgetTest(StopRuleCase):
    def test_a_spent_wall_clock_budget_ends_the_run_budget_spent(self):
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})
        self.set_harness(budgets={"wallclock_hours": 1, "gpu_hours": None})
        results = self.conduct((done(), patch()), clock=lambda: time.time() + 2 * HOUR)
        self.assertEqual((results[-1].reason, self.ended()), ("budget_spent", ["budget_spent"]))
        self.assertNotIn("ticket_launched", self.sequence())
        self.assertIn("the wall-clock budget of 1 hour(s) is spent", self.recorder.sent[0][1])

    def test_a_spent_gpu_budget_ends_the_run_budget_spent(self):
        self.ledger.append_event("job_launched", {"job": "t9-1", "ticket": 9, "gpu_uuids": ["GPU-a", "GPU-b"]}, job="t9-1")
        self.set_harness(budgets={"gpu_hours": 5})
        results = self.conduct((done(), patch()), clock=lambda: time.time() + 3 * HOUR)
        self.assertEqual(results[-1].reason, "budget_spent")
        self.assertIn("the GPU budget of 5 hour(s) is spent (6.00 used)", self.said())

    def test_a_harness_json_that_cannot_be_read_ends_nothing(self):
        """The tick reads no default rule into a `harness.json` it cannot read: it ends nothing for good on it."""
        open_objective(self.project)
        change_objective(self.project, "O1", "answered", "owner", answer="yes")
        self.assertIsNotNone(tick.ended_for_good(self.project, [], time.time()))
        (self.project / "harness.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(tick.ended_for_good(self.project, [], time.time()))

    def test_a_budget_not_spent_ends_nothing(self):
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})
        self.set_harness(budgets={"wallclock_hours": 10, "gpu_hours": 10})
        self.assertEqual(self.conduct((done(), patch()))[-1].reason, "frontier_empty")


class TickTest(StopRuleCase):
    def test_the_tick_does_not_relaunch_a_run_a_budget_ended_even_after_an_answer(self):
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})
        self.set_harness(budgets={"wallclock_hours": 1})
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": 1})
        self.conduct(clock=lambda: time.time() + 2 * HOUR)
        reason, why = self.relaunch(time.time() + 2 * HOUR)
        self.assertIsNone(reason)
        self.assertIn("only the owner raises a budget", why)
        stopping.set_budget(self.project, "wallclock_hours", 5)
        reason, why = self.relaunch(time.time() + 2 * HOUR)
        self.assertIsNone(reason)
        self.assertIn("budget_spent", why, "the run ended for good; the owner starts the next one")

    def test_the_tick_does_not_relaunch_a_run_its_rule_ended(self):
        open_objective(self.project)
        change_objective(self.project, "O1", "answered", "owner", answer="yes")
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": 1})
        self.conduct()
        reason, why = self.relaunch()
        self.assertIsNone(reason)
        self.assertIn("the stopping rule objectives", why)


class EmptyFrontierCase(StopRuleCase):
    def setUp(self):
        super().setUp()
        open_objective(self.project, "Does the hello file help?")
        open_objective(self.project, "Is it read?")
        self.serve("O1")

    def asks(self):
        return {stopping.frontier_objective(fields["origin"]): fields for fields in self.frontier_tickets()}


class OwnerAnswersTest(EmptyFrontierCase):
    def test_under_checkpoints_one_ticket_per_objective_and_the_run_ends_frontier_empty(self):
        results = self.conduct((done(), patch()))
        self.assertEqual(results[-1].reason, "frontier_empty")
        asks = self.asks()
        self.assertEqual(sorted(asks), ["O1", "O2"])
        for identifier, fields in asks.items():
            record = self.record(fields["id"])
            self.assertEqual(record["options"], ["replan for it", "answer it as it stands", "park it", "drop it"])
            self.assertFalse(fields["human_only"])
            self.assertIsNone(fields["blocking"])
        self.assertEqual(self.record(asks["O1"]["id"])["recommended"], "replan for it", "ticket 1 serving O1 was done")
        self.assertEqual(self.record(asks["O2"]["id"])["recommended"], "answer it as it stands", "nothing served O2")
        self.assertIn("decision ticket(s) %d, %d wait for the owner" % (asks["O1"]["id"], asks["O2"]["id"]), self.said())

    def test_under_interactive_the_owner_answers_too(self):
        self.set_harness(autonomy="interactive")
        self.assertEqual(self.conduct((done(), patch()))[-1].reason, "frontier_empty")
        self.assertEqual(sorted(self.asks()), ["O1", "O2"])

    def test_a_second_run_asks_nothing_twice(self):
        self.conduct((done(), patch()))
        first = sorted(fields["id"] for fields in self.frontier_tickets())
        self.assertEqual(self.conduct()[-1].reason, "frontier_empty")
        self.assertEqual(sorted(fields["id"] for fields in self.frontier_tickets()), first)
        self.assertEqual(len(self.events("decision_opened")), 2)

    def test_the_end_notice_is_sent_once_run_ended_is_journaled(self):
        """Its `notified` claim then follows the end, so the tick does not send the end a second time."""
        seen = []
        self.recorder = lambda event, text, project=None, ticket=None: seen.append((event, text, self.sequence()))
        self.conduct((done(), patch()))
        notices = [(text, journal) for event, text, journal in seen if event == "run_ended"]
        self.assertEqual(len(notices), 1)
        self.assertIn("the frontier is empty and the stopping rule", notices[0][0])
        self.assertEqual(notices[0][1][-1], "run_ended")

    def test_the_tick_relaunches_after_the_answer(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints",
                                                 "radius": "moderate", "pid": 1})
        self.conduct((done(), patch()))
        self.assertEqual(self.relaunch()[0], None)
        answer(self.project, self.asks()["O2"]["id"], "park it")
        self.assertEqual(self.relaunch()[0], "a decision ticket was answered since the conductor last ran")

    def test_park_and_drop_close_the_objectives_and_the_rule_ends_the_run(self):
        self.conduct((done(), patch()))
        asks = self.asks()
        answer(self.project, asks["O1"]["id"], "drop it")
        answer(self.project, asks["O2"]["id"], "option 3")
        results = self.conduct()
        self.assertEqual((self.objective("O1")["status"], self.objective("O2")["status"]), ("dropped", "parked"))
        self.assertEqual(self.ended()[-1], "objectives_closed")
        self.assertEqual(results[-1].reason, "objectives_closed")
        bys = [event["payload"]["by"] for event in self.events("objective") if event["payload"]["status"] in ("dropped", "parked")]
        self.assertEqual(bys, ["owner", "owner"])

    def test_a_split_written_after_the_answer_is_not_the_replan(self):
        self.conduct((done(), patch()))
        answer(self.project, self.asks()["O1"]["id"], "replan for it")
        self.ledger.write_json("plan.json", {"sha": "split", "cut_at": now_ts(), "cut": "split"})
        self.conduct()
        self.assertEqual([cut.kind for cut in self.planned], ["revise"])

    def test_a_replan_the_planner_could_not_cut_is_said_to_the_owner(self):
        self.conduct((done(), patch()))
        answer(self.project, self.asks()["O1"]["id"], "replan for it")
        self.planner = lambda cut, fall_back: ValueError("the planner returned no plan")
        self.conduct()
        self.assertTrue([text for event, text, _ in self.recorder.sent if "the planner could not replan for O1" in text])

    def test_a_replan_answer_cuts_once_and_an_answer_as_it_stands_asks_nothing_again(self):
        self.conduct((done(), patch()))
        asks = self.asks()
        answer(self.project, asks["O1"]["id"], "replan for it")
        answer(self.project, asks["O2"]["id"], "answer it as it stands")
        results = self.conduct()
        self.assertEqual([(cut.kind, "O1" in cut.change) for cut in self.planned], [("revise", True)])
        self.assertEqual(results[-1].reason, "frontier_empty")
        self.assertEqual(len(self.frontier_tickets()), 2, "nothing was created since the answers, so nothing is asked again")
        self.assertEqual(self.objective("O2")["status"], "open", "answering as it stands is the fresh verifier's to write")
        self.conduct()
        self.assertEqual(len(self.planned), 1)


class DeciderAnswersTest(EmptyFrontierCase):
    def setUp(self):
        super().setUp()
        project.set_autonomy(self.project, "autonomous")

    def decider_calls(self):
        return [call for call in self.calls if call.request.role == decider.DECIDER]

    def test_the_decider_answers_the_empty_frontier_in_one_session(self):
        results = self.conduct((done(), patch()), decider_answers=["O1: replan for it; O2: answer it as it stands"])
        self.assertEqual(len(self.decider_calls()), 1)
        prompt = self.decider_calls()[0].request.prompt
        self.assertIn("- subject: the empty frontier", prompt)
        self.assertIn("- options: O1: replan for it | O1: answer it as it stands | O2: replan for it | O2: answer it as it stands", prompt)
        asks = self.asks()
        decided = {event["payload"]["ticket"]: event["payload"]["answer"] for event in self.events("decision")
                   if event["payload"].get("decided_by") == "decider"}
        self.assertEqual(decided, {asks["O1"]["id"]: "replan for it", asks["O2"]["id"]: "answer it as it stands"})
        self.assertEqual([cut.kind for cut in self.planned], ["revise"])
        self.assertEqual(results[-1].reason, "frontier_empty")
        self.assertEqual(len(self.frontier_tickets()), 2)

    def test_the_decider_never_parks_or_drops_an_objective_the_rule_names(self):
        self.conduct((done(), patch()), decider_answers=["O1: drop it; O2: answer it as it stands"])
        asks = self.asks()
        o1 = {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[asks["O1"]["id"]]
        self.assertTrue(o1["human_only"], "turned over to the owner")
        self.assertEqual(self.objective("O1")["status"], "open")
        decided = [event["payload"]["ticket"] for event in self.events("decision") if event["payload"].get("decided_by") == "decider"]
        self.assertEqual(decided, [asks["O2"]["id"]])
        self.assertEqual(self.ended()[-1], "frontier_empty")
