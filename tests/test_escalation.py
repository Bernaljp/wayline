"""The stall and the escalation chain (ticket 38; by rung, ticket 61; Implementation Decisions 5, 14, 15, and 16).

The conductor is driven wave by wave against the one-ticket and five-ticket fixtures with the fake
worker, and the planner it calls at the `split` step and at a stall is a fake that records each cut.
What is asserted is what the owner and a restarted conductor can see: the journal's `ticket_failed`
steps, `ticket_resumed`, `ticket_launched` with the difficulty and the rung it launched at,
`difficulty_raised`, `ticket_needs_human` with its reason, `stall`, `run_ended`, the ticket files,
and the notifications.
"""

import copy
import io
import json
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests import machine
from tests.test_conductor import FIVE_TICKETS, ConductorCase, done, patch
from tests.test_replay import event, launched
from wayline import conductor, plan, project, replay, resources, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger

LAUNCHED = {"role": "coder", "model": "sonnet", "effort": "low", "skills": [], "pid": 4000, "context_chars": 10,
            "prompt_sha256": "0" * 64}


def failed(ticket_id=1, summary="the library does not exist"):
    """A result that says the worker failed."""
    envelope = done(ticket_id)
    envelope.structured_output.update({"status": "failed", "summary": summary})
    return envelope


class Planner:
    """The fake planner: records each cut as `(kind, of, fall_back)`, and does what `act(cut)` does, or refuses."""

    def __init__(self, act=None):
        self.cuts, self.act = [], act

    def __call__(self, cut, fall_back):
        self.cuts.append((cut.kind, cut.of, fall_back))
        if self.act is None:
            raise plan.PlanError("the fake planner cuts nothing")
        return self.act(cut)


def park(project_path):
    """A planner act that parks the ticket it splits, as `plan.write_plan` does, and writes nothing else."""
    def act(cut):
        ledger = Ledger(project_path)
        if cut.kind == "split":
            path = next(tickets.tickets_dir(project_path).glob("%02d-*.md" % cut.of))
            fields, body = tickets.read_ticket(path)
            tickets.write_ticket(ledger, dict(fields, status="parked"), body)
            ledger.append_event("ticket_cancelled", {"ticket": cut.of, "by": "planner"}, ticket=cut.of)
        return {"tickets": [], "superseded": [cut.of] if cut.of else [], "gate": None}
    return act


class EscalationCase(ConductorCase):
    """The one-ticket fixture, conducted with a fake planner, a recorded notifier, and a policy a test may change."""

    def setUp(self):
        super().setUp()
        self.policy = copy.deepcopy(project.policy_for(self.project))
        self.policy["stall"]["waves"] = 99  # the ladder's waves make no progress; the stall has tests of its own
        self.planner = Planner()
        self.notified = []
        self.reported = []

    def tearDown(self):
        worker.simulate_failure(None)
        super().tearDown()

    def conductor(self):
        made = Conductor(self.project, policy=self.policy, out=io.StringIO())
        made.readings = machine.recorded
        made.planner = self.planner
        made.plan_pre_check = False
        made.notify = lambda event_name, text, project=None, ticket=None: self.notified.append((event_name, ticket, text))
        made.reporter = lambda: self.reported.append(True)
        return made

    def conduct(self, *scripted, waves=20, before=None):
        """Waves until the run ends, settling the sessions between them, with each entry `(envelope, patch[, ticket])` scripted."""
        with worker.use_fake() as fake:
            for entry in scripted:
                envelope, applied = entry[:2]
                fake.script(envelope, patch=applied, ticket=entry[2] if len(entry) > 2 else None)
            self.made = self.conductor()
            if before is not None:
                before(self.made)
            results = []
            while len(results) < waves:
                results.append(self.made.wave())
                if results[-1].ended:
                    break
                self.made.settle()
            self.made.settle()
            self.calls = list(fake.calls)
        self.assertReplayIsStable()
        return results

    def assertReplayIsStable(self):
        """Decision 5: replaying the journal these waves wrote twice yields the same view, and a tail is a restart.

        Every escalation test ends here, so no step of the chain can leave the journal in a shape a
        restarted conductor would read differently from the one that wrote it.
        """
        events, _ = self.ledger.read_events()
        whole = replay.replay(events)
        self.assertEqual(replay.replay(events), whole, "replaying twice yields a different view")
        for cut in sorted({0, len(events) // 2, len(events)}):
            with self.subTest(cut=cut):
                self.assertEqual(replay.replay(events[cut:], replay.replay(events[:cut])), whole,
                                 "a view kept by tailing the journal is not the view a restart rebuilds")

    def steps(self):
        """The escalation step every `ticket_failed` named in `next`, in order."""
        return [item["payload"]["next"] for item in self.events("ticket_failed")]

    def launches(self):
        return [(item["payload"]["attempt"], item["payload"]["difficulty"], item["payload"]["model"], item["payload"]["effort"])
                for item in self.events("ticket_launched")]

    def rungs(self):
        """The rung every `ticket_launched` ran on, in order: what a tier up moves (decision 16)."""
        return [item["payload"]["rung"] for item in self.events("ticket_launched")]

    def set_fields(self, identifier=1, **changes):
        path = next(tickets.tickets_dir(self.project).glob("%02d-*.md" % identifier))
        fields, body = tickets.read_ticket(path)
        fields.update(changes)
        tickets.write_ticket(self.ledger, fields, body)
        self.git("add", "--", "research")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ledger: edit ticket %d" % identifier)

    def set_harness(self, **changes):
        harness = project.read_harness(self.project)
        harness.update(changes)
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")


class LadderTest(EscalationCase):
    """Criterion 2: resume once, one tier up one rung, a split, then a person; each step journaled in `next`.

    Inside a model family the tier up comes first, since one rung up is the cheaper remedy (decision 16);
    the split comes first only where the next rung would be on Fable, which `FableRungTest` covers.
    """

    def test_a_simulated_failure_climbs_the_whole_chain(self):
        worker.simulate_failure(1)
        results = self.conduct((done(), patch()), (done(), None), (done(), None), (done(), None),
                               (done(), None), (done(), None))
        self.assertEqual(self.steps(), ["resume", "tier_up", "resume", "split", "needs_human"])
        self.assertEqual([item["payload"]["reason"] for item in self.events("ticket_resumed")],
                         ["acceptance_failed", "acceptance_failed"], "each attempt's acceptance is resumed once first")
        self.assertEqual(self.launches(), [(1, 1, "sonnet", "low"), (2, 1, "sonnet", "high")],
                         "the tier up moved the rung, and left the difficulty level where it was")
        self.assertEqual(self.rungs(), [2, 3], "one rung up the ladder, rung 2 to rung 3")
        self.assertEqual([call.kind for call in self.calls], ["launch", "resume", "launch", "resume"])
        self.assertEqual(self.planner.cuts, [("split", 1, False)])
        self.assertIn("the planner could not split it", self.events("ticket_failed")[4]["payload"]["reason"],
                      "a split that fails goes on to the person, the last step left")
        self.assertEqual(self.payload("ticket_needs_human")["ticket"], 1)
        self.assertEqual([(name, ticket) for name, ticket, _ in self.notified], [("ticket_needs_human", 1)])
        self.assertEqual(self.ticket()["status"], "needs_human")
        self.assertTrue(results[-1].ended)
        self.assertEqual(results[-1].reason, "frontier_empty")
        commands = [result["cmd"] for item in self.events("acceptance") for result in item["payload"]["results"]]
        self.assertIn("wayline run --simulate-failure 1", commands)
        self.assertIn("Escalated one rung up: the next attempt launches on rung 3 (r3 sonnet high)", self.body())

    def test_the_simulated_failure_forces_a_one_rung_tier_up(self):
        """Criterion 6: `wayline run --simulate-failure <id>` forces a tier up that shows in the journal."""
        worker.simulate_failure(1)
        self.conduct((done(), patch()), (done(), None), (done(), None), (done(), None),
                     (done(), None), (done(), None))
        launched = [item["payload"] for item in self.events("ticket_launched")]
        self.assertEqual([(entry["attempt"], entry["rung"]) for entry in launched], [(1, 2), (2, 3)])
        self.assertIn("tier_up", self.steps())

    def test_a_failure_the_worker_reports_is_resumed_once_with_its_output(self):
        results = self.conduct((failed(), None), (done(), patch()))
        self.assertEqual(self.steps(), ["resume"])
        self.assertEqual(self.payload("ticket_resumed")["reason"], "acceptance_failed")
        self.assertEqual([call.kind for call in self.calls], ["launch", "resume"])
        self.assertIn("the library does not exist", self.calls[1].message)
        self.assertIn("research/tickets/01-write-the-hello-file.md", self.calls[1].message)
        self.assertEqual(self.ticket()["status"], "done")
        self.assertEqual([attempt for attempt, *_ in self.launches()], [1], "a resume is no new attempt")
        self.assertEqual((results[-1].ended, results[-1].reason), (True, "frontier_empty"))
        self.assertIn((1, "resume"), [item for result in results for item in result.escalated])

    def test_a_spent_resume_goes_one_rung_up_in_a_new_session(self):
        self.conduct((failed(), None), (failed(summary="still missing"), None), (done(), patch()))
        self.assertEqual(self.steps(), ["resume", "tier_up"])
        self.assertEqual(self.planner.cuts, [], "the tier up comes first inside a model family")
        self.assertEqual(self.launches(), [(1, 1, "sonnet", "low"), (2, 1, "sonnet", "high")])
        self.assertEqual(self.rungs(), [2, 3])
        self.assertEqual([call.kind for call in self.calls], ["launch", "resume", "launch"])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_resumed_session_that_reports_failed_again_goes_up_a_rung_even_when_its_acceptance_passes(self):
        self.conduct((failed(), patch()), (failed(summary="still missing"), None), (done(), None))
        self.assertEqual(self.steps(), ["resume", "tier_up"])
        self.assertEqual(self.events("ticket_failed")[1]["payload"]["reason"], "still missing")
        self.assertEqual(self.ticket()["status"], "done", "the tier-up attempt closed it")
        self.assertEqual(self.rungs(), [2, 3])

    def test_the_whole_ladder_ends_under_the_default_stall(self):
        self.policy["stall"]["waves"] = 2
        worker.simulate_failure(1)
        results = self.conduct((done(), patch()), (done(), None), (done(), None), (done(), None))
        self.assertTrue(results[-1].ended)
        self.assertEqual(self.ticket()["status"], "needs_human")
        self.assertIn(("replan", None, False), self.planner.cuts, "a ticket that keeps failing stalls the run")
        self.assertEqual(self.steps()[-1], "needs_human")

    def test_under_cheap_only_a_split_waits(self):
        self.set_fields(pinned_difficulty=1)

        def cheap(made):
            made.action = "cheap_only"
            made._pace = lambda: None
        results = self.conduct((failed(), None), (failed(), None), waves=5, before=cheap)
        self.assertEqual(self.steps(), ["resume", "split"])
        self.assertEqual(self.planner.cuts, [])
        self.assertFalse(results[-1].ended)

    def test_a_pinned_ticket_skips_the_tier_up(self):
        self.set_fields(pinned_difficulty=1)
        self.planner = Planner(park(self.project))
        results = self.conduct((failed(), None), (failed(), None))
        self.assertEqual(self.steps(), ["resume", "split"])
        self.assertEqual(self.planner.cuts, [("split", 1, False)])
        self.assertEqual(self.ticket()["status"], "parked")
        self.assertEqual((results[-1].ended, results[-1].reason), (True, "frontier_empty"))
        self.assertEqual(len(self.launches()), 1)

    def test_a_split_that_lands_parks_the_ticket_and_nothing_climbs_after_it(self):
        self.planner = Planner(park(self.project))
        results = self.conduct((failed(), None), (failed(), None), (failed(), None), (failed(), None))
        self.assertEqual(self.steps(), ["resume", "tier_up", "resume", "split"])
        self.assertEqual(self.ticket()["status"], "parked")
        self.assertEqual(self.rungs(), [2, 3], "the tier up launched once; the split parked the ticket after it")
        self.assertTrue(results[-1].ended)

    def test_a_ticket_a_split_cut_is_not_split_again(self):
        path = next(tickets.tickets_dir(self.project).glob("01-*.md"))
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, fields, body + "\n" + plan.SPLIT_NOTE % 7 + "\n")
        self.git("add", "--", "research")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ledger: a piece of ticket 7")
        self.conduct((failed(), None), (failed(), None), (done(), patch()))
        self.assertEqual(self.steps(), ["resume", "tier_up"])
        self.assertEqual(self.planner.cuts, [])
        self.assertEqual(plan.split_from(self.body()), 7)

    def test_the_top_rung_skips_the_tier_up_and_ends_needs_human_with_its_reason(self):
        """Criterion 3: rung 7 has nowhere to climb, so the split is taken and then a person, with `reason: top_rung`."""
        self.set_fields(difficulty=5)
        self.conduct((failed(), None), (failed(), None))
        self.assertEqual(self.steps(), ["resume", "split", "needs_human"])
        self.assertEqual(self.rungs(), [7], "difficulty 5 is the ladder's top rung, and nothing launched above it")
        self.assertEqual(self.payload("ticket_needs_human")["reason"], "top_rung")
        self.assertIn("rung 7, the rung ladder's top rung", self.payload("ticket_needs_human")["question"])
        self.assertIn("at the ladder's top rung", self.made.out.getvalue())

    def test_a_ticket_below_the_top_rung_is_handed_over_without_a_reason(self):
        """A pinned ticket the chain runs out on has somewhere to climb; only the top rung says why."""
        self.set_fields(pinned_difficulty=1)
        self.conduct((failed(), None), (failed(), None))
        self.assertEqual(self.steps(), ["resume", "split", "needs_human"])
        self.assertNotIn("reason", self.payload("ticket_needs_human"))

    def test_a_split_that_waits_for_fable_does_not_end_the_run(self):
        self.set_fields(pinned_difficulty=1)
        self.set_harness(model_fallback="wait")

        def hold(made):
            made.ledger.append_event("paused", {"resets_at": "2099-01-01T00:00:00Z", "window": "seven_day",
                                                "utilization": 1.0, "model": "fable"})
        results = self.conduct((failed(), None), (failed(), None), waves=5, before=hold)
        self.assertEqual(self.steps(), ["resume", "split"])
        self.assertEqual(self.planner.cuts, [], "the planner is on Fable, and the consent waits")
        self.assertFalse(results[-1].ended)
        self.assertEqual(self.ticket()["status"], "failed")

    def test_a_split_falls_back_to_opus_under_consent_auto(self):
        self.set_fields(pinned_difficulty=1)
        self.set_harness(model_fallback="auto")
        self.planner = Planner(park(self.project))

        def hold(made):
            made.ledger.append_event("paused", {"resets_at": "2099-01-01T00:00:00Z", "window": "seven_day",
                                                "utilization": 1.0, "model": "fable"})
        self.conduct((failed(), None), (failed(), None), before=hold)
        self.assertEqual(self.planner.cuts, [("split", 1, True)])

    def test_a_failed_job_resumes_the_session_that_wrote_it(self):
        resources.add_jobs(self.project, {"command": ["/bin/true"]}, ticket=1, backend="fake")
        running = done()
        running.structured_output.update({"status": "running", "jobs": ["t1-1"]})
        with resources.use_fake_jobs() as jobs:
            jobs.script([resources.JobState("failed", result="exit-code", exit_code=3, reason="exited 3")], job_id="t1-1")
            self.conduct((running, patch()), (done(), None))
        self.assertEqual(self.steps(), ["resume"])
        self.assertIn("job t1-1 failed", self.calls[1].message)
        self.assertEqual(self.calls[1].kind, "resume")
        self.assertEqual(self.ticket()["status"], "done")


class RestartTest(EscalationCase):
    """The step is read from the journal: a restarted conductor takes the chain up where it stood."""

    def record_failure(self, step, session_id="s-1", rung=2, difficulty=1):
        self.ledger.append_event("ticket_launched", dict(LAUNCHED, ticket=1, attempt=1, worktree=str(self.worktree()),
                                                         difficulty=difficulty, rung=rung), ticket=1)
        self.ledger.append_event("ticket_session", {"ticket": 1, "attempt": 1, "session_id": session_id, "model": "sonnet"},
                                 ticket=1, session_id=session_id)
        self.ledger.append_event("ticket_failed", {"ticket": 1, "attempt": 1, "reason": "it broke", "next": step}, ticket=1)
        self.set_fields(status="failed")

    def test_a_recorded_tier_up_launches_the_next_attempt_one_rung_up(self):
        self.record_failure("tier_up")
        self.conduct((done(), patch()))
        self.assertEqual(self.launches(), [(1, 1, "sonnet", "low"), (2, 1, "sonnet", "high")])
        self.assertEqual(self.rungs(), [2, 3], "one rung above the rung the failed attempt recorded")
        self.assertEqual(self.ticket()["status"], "done")
        self.assertNotIn("the journal wins", self.made.out.getvalue(), "a ticket opened for its tier up is not a contradiction")

    def test_a_recorded_tier_up_in_a_journal_older_than_the_ladder_counts_the_tier_ups(self):
        """A launch with no `rung` names no floor, so the count of tier ups moves the level's own rung instead."""
        self.record_failure("tier_up", rung=None)
        self.conduct((done(), patch()))
        self.assertEqual(self.rungs(), [None, 3])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_recorded_resume_resumes_the_recorded_session(self):
        self.record_failure("resume")
        self.conduct((done(), patch()))
        self.assertEqual([(call.kind, call.session_id) for call in self.calls], [("resume", "s-1")])
        self.assertIn("it broke", self.calls[0].message)
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_recorded_resume_with_no_session_goes_on_to_the_next_step(self):
        self.ledger.append_event("ticket_launched", dict(LAUNCHED, ticket=1, attempt=1, worktree=str(self.worktree()),
                                                         difficulty=1, rung=2), ticket=1)
        self.ledger.append_event("ticket_failed", {"ticket": 1, "attempt": 1, "reason": "it broke", "next": "resume"}, ticket=1)
        self.set_fields(status="failed")
        self.conduct((done(), patch()))
        self.assertEqual(self.steps(), ["resume", "tier_up"])
        self.assertIn("cannot be resumed", self.events("ticket_failed")[1]["payload"]["reason"])
        self.assertEqual(self.rungs(), [2, 3])
        self.assertEqual(self.ticket()["status"], "done")


class FableRungTest(EscalationCase):
    """Criteria 2 and 4: the split comes first onto Fable, the tier up climbs inside Fable, and the hold is obeyed.

    The one-ticket fixture is set to the difficulty whose rung the test needs: difficulty 3 is rung 5
    (`opus high`), difficulty 4 rung 6 (`fable low`), difficulty 5 rung 7 (`fable high`).
    """

    def cut_by_a_split(self):
        """Mark ticket 1 as one a split already cut, so the split is spent and the tier up is the only step left."""
        path = next(tickets.tickets_dir(self.project).glob("01-*.md"))
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, fields, body + "\n" + plan.SPLIT_NOTE % 7 + "\n")
        self.git("add", "--", "research")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ledger: a piece of ticket 7")

    def hold_fable(self, made):
        made.ledger.append_event("paused", {"resets_at": "2099-01-01T00:00:00Z", "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"})

    def test_the_split_comes_before_a_tier_up_onto_fable(self):
        self.set_fields(difficulty=3)
        self.planner = Planner(park(self.project))
        self.conduct((failed(), None), (failed(), None))
        self.assertEqual(self.steps(), ["resume", "split"], "rung 5 to rung 6 climbs onto Fable, so the split goes first")
        self.assertEqual(self.planner.cuts, [("split", 1, False)])
        self.assertEqual(self.rungs(), [5], "nothing launched on Fable: the split parked it first")
        self.assertEqual(self.ticket()["status"], "parked")

    def test_a_split_that_fails_then_climbs_onto_fable(self):
        self.set_fields(difficulty=3)
        self.conduct((failed(), None), (failed(), None), (done(), patch()))
        self.assertEqual(self.steps(), ["resume", "split", "tier_up"])
        self.assertEqual(self.rungs(), [5, 6], "rung 5 to rung 6, one rung, once the split had its try")
        self.assertEqual(self.launches(), [(1, 3, "opus", "high"), (2, 3, "fable", "low")],
                         "the level stayed at 3 and the rung moved")
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_tier_up_inside_fable_comes_before_the_split(self):
        self.set_fields(difficulty=4)
        self.planner = Planner(park(self.project))
        self.conduct((failed(), None), (failed(), None), (done(), patch()))
        self.assertEqual(self.steps(), ["resume", "tier_up"], "rung 6 to rung 7 stays inside Fable")
        self.assertEqual(self.planner.cuts, [])
        self.assertEqual(self.rungs(), [6, 7])
        self.assertEqual(self.launches(), [(1, 4, "fable", "low"), (2, 4, "fable", "high")])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_tier_up_onto_a_held_fable_rung_falls_back_under_auto(self):
        self.set_fields(difficulty=3)
        self.cut_by_a_split()
        self.set_harness(model_fallback="auto")
        self.conduct((failed(), None), (failed(), None), (done(), patch()), before=self.hold_fable)
        self.assertEqual(self.steps(), ["resume", "tier_up"], "the split is spent, so the tier up is what is left")
        self.assertEqual(self.launches(), [(1, 3, "opus", "high"), (2, 3, "opus", "low")],
                         "rung 6 fell back to Opus at rung 6's own effort")
        self.assertEqual(self.rungs(), [5, 6], "the launch still names the Fable rung it fell back from")
        self.assertEqual(self.events("ticket_launched")[-1]["payload"]["fallback_from"], "fable")
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_tier_up_onto_a_held_fable_rung_waits_under_wait(self):
        self.set_fields(difficulty=3)
        self.cut_by_a_split()
        self.set_harness(model_fallback="wait")
        results = self.conduct((failed(), None), (failed(), None), waves=5, before=self.hold_fable)
        self.assertEqual(self.steps(), ["resume", "tier_up"])
        self.assertEqual(self.rungs(), [5], "nothing launched on the held Fable rung")
        self.assertFalse(results[-1].ended, "the tier up is owed, and waits for the reset")
        self.assertEqual(self.ticket()["status"], "open", "opened for the tier up its launch still owes")

    def test_a_tier_up_onto_a_held_fable_rung_asks_under_ask(self):
        self.set_fields(difficulty=3)
        self.cut_by_a_split()
        self.set_harness(model_fallback="ask", autonomy="autonomous")
        results = self.conduct((failed(), None), (failed(), None), waves=5, before=self.hold_fable)
        self.assertEqual(self.steps(), ["resume", "tier_up"])
        self.assertEqual(self.rungs(), [5], "nothing launched until the ask is answered")
        self.assertEqual(len(self.events("decision_opened")), 1, "the hold dropped a launch, so the ask opened once")
        self.assertFalse(results[-1].ended)


class DifficultyTest(EscalationCase):
    """Criterion 3: two failures of a kind at a tier raise it for the rest of the run, except pins and fallbacks."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "five"
        shutil.copytree(FIVE_TICKETS, self.project)
        project.init_project(self.project)
        self.ledger = Ledger(self.project)
        self.policy["max_parallel_workers"] = 1

    def record_failure(self, identifier, fallback=False):
        """A failed attempt of a code ticket at difficulty 1, handed to a person so the chain leaves it alone."""
        payload = dict(LAUNCHED, ticket=identifier, attempt=1, worktree="/p", difficulty=1, rung=2)
        if fallback:
            payload["fallback_from"] = "fable"
        self.ledger.append_event("ticket_launched", payload, ticket=identifier)
        self.ledger.append_event("ticket_failed", {"ticket": identifier, "attempt": 1, "reason": "no", "next": "needs_human"},
                                 ticket=identifier)
        self.ledger.append_event("ticket_needs_human", {"ticket": identifier, "question": "no"}, ticket=identifier)
        self.set_fields(identifier, status="needs_human")

    def assertNoRaiseBefore(self, identifier):
        """No `difficulty_raised` was journaled before the ticket's first launch (its own failure may raise the kind after)."""
        names = [(item["event"], item["payload"].get("ticket")) for item in self.events()]
        first = names.index(("ticket_launched", identifier))
        self.assertNotIn("difficulty_raised", [name for name, _ in names[:first]])

    def launched_at(self, identifier):
        return [(item["payload"]["difficulty"], item["payload"]["model"], item["payload"]["effort"])
                for item in self.events("ticket_launched") if item["payload"]["ticket"] == identifier]

    def launched_rungs(self, identifier):
        return [item["payload"]["rung"] for item in self.events("ticket_launched") if item["payload"]["ticket"] == identifier]

    def test_the_second_failure_at_a_tier_raises_the_kind(self):
        self.record_failure(1)
        for identifier in (3, 4, 5):
            self.set_fields(identifier, status="parked")  # ticket 2 alone runs; the others are read back from the graph
        snapshots = []

        def watch(made):
            end = made._end
            made._end = lambda result: (snapshots.append({entry["id"]: entry["difficulty"] for entry in made._graph()["tickets"]}),
                                        end(result))
        self.conduct((failed(2), None, 2), (failed(2), None, 2), (done(2), patch({"reports/beta.md": "beta\n"}), 2),
                     waves=6, before=watch)
        self.assertEqual(self.payload("difficulty_raised"), {"kind": "code", "from": 1, "to": 2})
        names = [(item["event"], item["payload"].get("next")) for item in self.events()]
        self.assertLess(names.index(("ticket_failed", "tier_up")), names.index(("difficulty_raised", None)),
                        "a failure its resume may still mend does not count")
        self.assertEqual(self.launched_at(2)[:1], [(1, "sonnet", "low")])
        graph = snapshots[-1]  # read before the run ended, which ends the raise with it
        self.assertEqual((graph[5], graph[3]), (2, 2), "the kind is raised for the rest of the run")
        self.assertEqual(self.launched_at(2)[1:], [(2, "sonnet", "high")],
                         "the raise moved the level to 2, whose rung is 3; the tier up would have reached the same rung")
        self.assertEqual(self.launched_rungs(2), [2, 3], "a raise and a tier up do not add")

    def test_a_failure_its_resume_mends_does_not_count(self):
        self.record_failure(1)
        self.conduct((failed(2), None, 2), (done(2), patch({"reports/beta.md": "beta\n"}), 2), waves=3)
        self.assertEqual(self.events("difficulty_raised"), [])

    def test_a_pinned_ticket_is_not_raised(self):
        self.record_failure(1)
        self.set_fields(5, pinned_difficulty=1)
        self.conduct((failed(2), None, 2), (failed(5), None, 5), waves=3)
        self.assertEqual(len(self.events("difficulty_raised")), 1)
        self.assertEqual(self.launched_at(5)[:1], [(1, "sonnet", "low")])

    def test_a_pinned_ticket_failure_does_not_count(self):
        self.record_failure(1)
        self.set_fields(2, pinned_difficulty=1)
        self.conduct((failed(2), None, 2), (failed(5), None, 5), waves=3)
        self.assertEqual(self.launched_at(5)[:1], [(1, "sonnet", "low")])
        self.assertNoRaiseBefore(5)

    def test_a_failure_that_fell_back_does_not_count(self):
        self.record_failure(1, fallback=True)
        self.conduct((failed(2), None, 2), (failed(5), None, 5), waves=3)
        self.assertEqual(self.launched_at(5)[:1], [(1, "sonnet", "low")])
        self.assertNoRaiseBefore(5)


class StallTest(EscalationCase):
    """Criterion 1: settling waves without progress count up; at `policy.stall.waves` a replan, or a stop under strict."""

    def setUp(self):
        super().setUp()
        self.policy["stall"]["waves"] = 2
        self.planner = Planner(park(self.project))

    def test_two_settling_waves_without_progress_file_a_replan(self):
        replan_only = park(self.project)

        def act(cut):
            if cut.kind == "split":
                raise plan.PlanError("this planner only re-cuts")
            return replan_only(cut)
        self.planner = Planner(act)
        results = self.conduct((failed(), None), (failed(), None), (done(), patch()))
        stalls = self.events("stall")
        self.assertEqual([item["payload"] for item in stalls], [{"waves": 2, "action": "replan"}])
        self.assertIn(("replan", None, False), self.planner.cuts)
        sequence = self.sequence()
        self.assertEqual([name for name in sequence if name in ("wave", "stall")][:3], ["wave", "wave", "stall"])
        self.assertTrue(any(result.stalled for result in results))
        self.assertEqual(self.ticket()["status"], "done", "the run goes on after the replan")

    def test_progress_resets_the_counter(self):
        self.conduct((failed(), None), (done(), patch()))
        self.assertEqual([item["payload"]["progressed"] for item in self.events("wave")], [False, True])
        self.assertEqual(self.events("stall"), [])

    def test_a_wave_that_carried_no_outcome_does_not_count(self):
        view = replay.replay([event("wave", {"number": 1, "outcomes": 1, "progressed": False}),
                              event("wave", {"number": 2, "outcomes": 0, "progressed": False})])
        self.assertEqual(view.stall, 1)
        self.conduct((failed(), None), (done(), patch()))
        self.assertEqual(len(self.events("wave")), 2, "the launch wave settles nothing and journals no wave")

    def test_a_replan_that_fails_is_said_and_not_launched_again(self):
        self.planner = Planner()
        results = self.conduct((failed(), None), (failed(), None), (done(), patch()))
        self.assertEqual([cut for cut in self.planner.cuts if cut[0] == "replan"], [("replan", None, False)])
        self.assertIn("could not re-cut the graph", self.made.out.getvalue())
        self.assertEqual((results[-1].ended, results[-1].reason), (True, "frontier_empty"))

    def test_a_replan_held_on_fable_keeps_the_run_open(self):
        self.ledger.append_event("stall", {"waves": 2, "action": "replan"})
        self.set_harness(model_fallback="wait")
        self.set_fields(status="done")
        self.ledger.append_event("paused", {"resets_at": "2099-01-01T00:00:00Z", "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"})
        results = self.conduct(waves=3)
        self.assertEqual(self.planner.cuts, [])
        self.assertFalse(results[-1].ended, "the replan is owed, and waits for the window")

    def test_a_restart_replans_a_stall_its_run_did_not_cut(self):
        self.ledger.append_event("stall", {"waves": 2, "action": "replan"})
        self.conduct(waves=2)
        self.assertEqual(self.planner.cuts, [("replan", None, False)])

    def test_a_stall_of_an_ended_run_is_not_replanned_by_the_next(self):
        self.ledger.append_event("stall", {"waves": 2, "action": "replan"})
        self.ledger.append_event("run_ended", {"reason": "frontier_empty"})
        self.conduct((done(), patch()), waves=3)
        self.assertEqual(self.planner.cuts, [])

    def test_under_strict_the_run_stops_and_the_report_is_rendered(self):
        self.set_harness(radius="strict")
        results = self.conduct((failed(), None), (failed(), None), (done(), None))
        self.assertEqual(self.payload("stall"), {"waves": 2, "action": "stop"})
        self.assertEqual(self.payload("run_ended"), {"reason": "stall_strict"})
        self.assertEqual((results[-1].ended, results[-1].reason), (True, "stall_strict"))
        self.assertEqual(self.reported, [True])
        self.assertEqual(self.planner.cuts, [])
        self.assertIn("run_ended", [name for name, _, _ in self.notified])
        self.assertEqual(self.sequence().count("run_ended"), 1)
        self.assertEqual(self.made.flight, {}, "the wave that stopped the run launched nothing")
        self.assertEqual(self.sequence()[-1], "run_ended")
        self.assertNotEqual(self.ticket()["status"], "running")


class ReplayTest(unittest.TestCase):
    """What the view keeps for the ladder and the adjustment, from recorded events."""

    def launch(self, ticket, attempt=1, difficulty=1, fallback=False, rung=2):
        record = launched(ticket, attempt)
        record["payload"]["difficulty"] = difficulty
        if rung is not None:
            record["payload"]["rung"] = rung
        if fallback:
            record["payload"]["fallback_from"] = "fable"
        return record

    def failure(self, ticket, step, attempt=1):
        return event("ticket_failed", {"ticket": ticket, "attempt": attempt, "reason": "no", "next": step}, ticket=ticket)

    def test_the_step_is_the_last_failure_s_while_the_ticket_is_failed(self):
        view = replay.replay([self.launch(1), self.failure(1, "resume")])
        self.assertEqual((view.tickets[1].step, view.tickets[1].failure), ("resume", "no"))
        view.apply(event("ticket_resumed", {"ticket": 1, "attempt": 1, "session_id": "s", "reason": "acceptance_failed"}, ticket=1))
        self.assertIsNone(view.tickets[1].step, "the resume took it up")
        self.assertIsNone(view.tickets[1].latest.ended, "the failed attempt is taken up again")
        self.assertEqual([identifier for identifier, _ in view.in_flight()], [1])
        view.apply(self.failure(1, "tier_up"))
        self.assertEqual(view.tickets[1].taken("tier_up"), 1)
        view.apply(event("ticket_rerun", {"ticket": 1, "by": "cli"}, ticket=1))
        self.assertEqual(view.tickets[1].taken("tier_up"), 0)

    def test_a_tier_up_records_one_rung_above_the_rung_the_attempt_ran_on(self):
        """The floor counts rungs, not difficulty levels (decision 16); a rerun clears it."""
        view = replay.replay([self.launch(1, rung=5), self.failure(1, "tier_up")])
        self.assertEqual(view.tickets[1].rung_floor, 6)
        view.apply(event("ticket_rerun", {"ticket": 1, "by": "cli"}, ticket=1))
        self.assertIsNone(view.tickets[1].rung_floor)

    def test_a_journal_older_than_the_rung_ladder_records_no_floor(self):
        view = replay.replay([self.launch(1, rung=None), self.failure(1, "tier_up")])
        self.assertIsNone(view.tickets[1].rung_floor)
        self.assertEqual(view.tickets[1].taken("tier_up"), 1)

    def test_a_failed_verdict_after_done_ends_the_attempt_as_failed(self):
        view = replay.replay([self.launch(1), event("ticket_done", {"ticket": 1}, ticket=1), self.failure(1, "resume")])
        self.assertEqual(view.tickets[1].latest.ended, "ticket_failed")

    def test_failures_count_by_launch_difficulty_and_skip_fallbacks(self):
        view = replay.replay([self.launch(1, difficulty=2), self.failure(1, "resume"), self.failure(1, "tier_up"),
                              self.launch(2, fallback=True), self.failure(2, "resume")])
        self.assertEqual(view.failures, {(1, 1): 2})

    def test_raises_last_for_the_run(self):
        view = replay.replay([self.launch(1), self.failure(1, "resume"),
                              event("difficulty_raised", {"kind": "code", "from": 1, "to": 2})])
        self.assertEqual(view.raised, {"code": {1: 2}})
        view.apply(event("run_ended", {"reason": "stopped"}))
        self.assertEqual((view.raised, view.failures), ({}, {}))

    def test_a_stall_that_asks_for_a_replan_is_remembered(self):
        view = replay.replay([event("stall", {"waves": 2, "action": "replan"}, at=5), event("stall", {"waves": 2, "action": "stop"}, at=9)])
        self.assertEqual(view.replan_at, "2026-09-12T10:00:05.000Z")


class EffectiveDifficultyTest(EscalationCase):
    """The level the next attempt launches at: pins win, raises chain, the top level caps, and a tier up does not move it."""

    def test_the_rules(self):
        made = self.conductor()
        made.view.raised = {"code": {1: 2, 2: 3}}
        fields = {"id": 1, "kind": "code", "difficulty": 1}
        self.assertEqual(made._effective_difficulty(fields), 3)
        self.assertEqual(made._effective_difficulty(dict(fields, kind="docs")), 1)
        self.assertEqual(made._effective_difficulty(dict(fields, pinned_difficulty=1)), 1)
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["tier_up"], rung_floor=6)
        self.assertEqual(made._effective_difficulty(fields), 3, "a tier up counts rungs, and leaves the level alone")


class EffectiveRungTest(EscalationCase):
    """Criterion 1: the rung the next attempt launches on: the level's rung, lifted by every tier up, capped at rung 7."""

    def test_the_rules(self):
        made = self.conductor()
        fields = {"id": 1, "kind": "code", "difficulty": 1}
        self.assertEqual(made._effective_rung(fields), 2, "difficulty 1 is rung 2")
        made.view.raised = {"code": {1: 2}}
        self.assertEqual(made._effective_rung(fields), 3, "a kind raised to level 2 is rung 3")
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["tier_up"], rung_floor=3)
        self.assertEqual(made._effective_rung(fields), 3, "a raise and a tier up do not add")
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["tier_up"], rung_floor=5)
        self.assertEqual(made._effective_rung(fields), 5, "one rung above the rung the attempt that failed ran on")
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["tier_up"], rung_floor=99)
        self.assertEqual(made._effective_rung(fields), 7, "never past the ladder's top rung")
        made.view.raised = {}
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["tier_up", "tier_up"])
        self.assertEqual(made._effective_rung(fields), 4, "a journal without a rung counts the tier ups")
        self.assertEqual(made._effective_rung(dict(fields, pinned_difficulty=5)), 7, "a pin names the rung outright")

    def test_a_failure_that_begins_at_the_split_still_goes_on_to_the_tier_up(self):
        """An integration that conflicted begins at the split, and climbs after it when the split is spent.

        `start` names where the failure begins, not where the chain is cut, so the order the tier up and
        the split are in does not decide whether the one after `start` is reachable.
        """
        made = self.conductor()
        self.assertEqual(made._step_from(1, "split"), "split")
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["split"])
        self.assertEqual(made._step_from(1, "split"), "tier_up", "the split is spent, so the tier up is next")
        made.view.tickets[1] = replay.TicketView(1, status="failed", steps=["split", "tier_up"])
        self.assertEqual(made._step_from(1, "split"), "needs_human")

    def test_the_next_rung_and_where_the_split_comes_first(self):
        made = self.conductor()
        self.assertEqual(made._next_rung(1), 3, "difficulty 1 is rung 2, and a tier up reaches rung 3")
        self.assertFalse(made._tier_up_reaches_fable(1), "rung 2 to rung 3 stays inside sonnet")
        self.assertEqual(made._step_order(1), ["tier_up", "split"])
        self.set_fields(difficulty=3)
        self.assertEqual(made._next_rung(1), 6, "difficulty 3 is rung 5, and a tier up reaches rung 6")
        self.assertTrue(made._tier_up_reaches_fable(1), "rung 5 to rung 6 climbs onto Fable")
        self.assertEqual(made._step_order(1), ["split", "tier_up"])
        self.set_fields(difficulty=4)
        self.assertEqual(made._next_rung(1), 7, "difficulty 4 is rung 6, and a tier up reaches rung 7")
        self.assertFalse(made._tier_up_reaches_fable(1), "rung 6 to rung 7 stays inside Fable")
        self.assertEqual(made._step_order(1), ["tier_up", "split"])
        self.set_fields(difficulty=5)
        self.assertIsNone(made._next_rung(1), "rung 7 has nowhere to climb")
        self.assertFalse(made._tier_up_reaches_fable(1))


class VerbTest(EscalationCase):
    """Criterion 4's verb: `wayline run --simulate-failure <id>`."""

    def run_verb(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = conductor.run_command(arguments)
        return code, out.getvalue(), err.getvalue()

    def test_an_id_that_is_not_a_ticket_id_is_refused(self):
        for value in ("0", "x"):
            with self.subTest(value=value):
                code, _, _ = self.run_verb(["--simulate-failure", value, "--project", str(self.project)])
                self.assertEqual(code, 2)

    def test_the_flag_reaches_the_detached_unit(self):
        with mock.patch.object(conductor.tick, "launch_detached", return_value="") as launch, \
                mock.patch.object(conductor, "conductor_holder", return_value=None), \
                mock.patch.object(conductor, "announce_dashboard"), \
                mock.patch.object(conductor, "refuse_to_start", return_value=[]):
            code, _, err = self.run_verb(["--detach", "--simulate-failure", "1", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        self.assertEqual(launch.call_args[0][1], ["--simulate-failure", "1"])

    def test_the_run_arms_and_disarms_the_failure(self):
        seen = []
        with mock.patch.object(conductor, "refuse_to_start", return_value=[]), \
                mock.patch.object(conductor, "announce_dashboard"), \
                mock.patch.object(Conductor, "run", lambda self, **options: seen.append(worker.simulated_failure(1)) or []):
            code, out, err = self.run_verb(["--simulate-failure", "1", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        self.assertEqual(seen[0]["cmd"], "wayline run --simulate-failure 1")
        self.assertIsNone(worker.simulated_failure(1), "disarmed once the run returned")
        self.assertIn("every acceptance of ticket 1 fails", out)

    def test_an_armed_failure_names_one_ticket(self):
        worker.simulate_failure(3)
        self.assertIsNone(worker.simulated_failure(2))
        self.assertEqual(worker.simulated_failure(3)["exit_code"], 1)


if __name__ == "__main__":
    unittest.main()
