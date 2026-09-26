"""The model that ran (ticket 63; Implementation Decisions 16, 3, 5, and 2).

A retired or unknown model name is not allowed to run quietly on another model. Every launch turns
the CLI's legacy remap off, and the launcher reads the model that ran from the result's `modelUsage`
and compares it with the one the launch named. Three halves are tested here:

- the pure half, `worker.same_model`, `model_ran`, `ran_as_asked`, and `not_served`, over the envelope
  shapes the research note on `research/model-versions` recorded live;
- the conductor half, driven with the fake launcher scripted with a result whose `modelUsage` names
  another model and with the not-served refusal, asserting the journal, the ticket statuses, the
  decision ticket the held rung opens, and which tickets the next waves launch;
- what a restarted conductor and the owner see: the view a journal replays to, and the label
  `wayline status` and the dashboard's ticket page give a launch whose model was not its rung's.
"""

import os
import unittest
from unittest import mock

from tests.projects import ProjectTestCase
from tests.test_conductor import drive, failing, patch
from tests.test_pacing import PacingCase, output
from tests.test_replay import event
from tests.test_verdicts import GateCase, passing
from wayline import dashboard, decisions, project, replay, tickets, worker
from wayline.ledger import Ledger
from wayline.worker import Envelope

# The refusal a name the subscription does not serve comes back as, verbatim from the research note.
NOT_SERVED_TEXT = ("There's an issue with the selected model (%s). It may not exist or you may not have access "
                   "to it. Run --model to pick a different model.")
# The preflight call every session makes before its own model runs; on a not-served refusal it is the whole of `modelUsage`.
PREFLIGHT = {"claude-haiku-4-5-20251001": {"inputTokens": 980, "outputTokens": 13, "costUSD": 0.00094,
                                           "canonicalModel": "claude-haiku-4-5"}}


def usage_of(*models):
    """A `modelUsage` block: the Haiku preflight, then one entry per model that answered."""
    usage = dict(PREFLIGHT)
    for model in models:
        usage[model] = {"inputTokens": 4, "outputTokens": 196, "canonicalModel": model}
    return usage


def not_served(name="claude-sonnet-4-0"):
    """The envelope a model name the subscription does not serve returns: exit 1, `subtype: success`, 404, the text."""
    return Envelope(is_error=True, subtype="success", exit_code=1, num_turns=1, api_error_status=404,
                    result_text=NOT_SERVED_TEXT % name, model_usage=dict(PREFLIGHT))


def ran_on(model, ticket_id=1):
    """A done result whose `modelUsage` says `model` answered, beside the preflight."""
    return Envelope(structured_output={"ticket_id": ticket_id, "status": "done", "summary": "wrote the file",
                                       "outputs_written": [output(ticket_id)]},
                    num_turns=3, duration_ms=1200, model_usage=usage_of(model))


class ReadingTest(unittest.TestCase):
    """Criterion 2: which model a result says ran, and whether it is the one the launch named."""

    def test_an_alias_matches_any_version_of_its_family_and_a_version_only_itself(self):
        self.assertTrue(worker.same_model("opus", "claude-opus-4-8"))
        self.assertTrue(worker.same_model("sonnet", "claude-sonnet-5"))
        self.assertTrue(worker.same_model("haiku", "claude-haiku-4-5-20251001"))
        self.assertFalse(worker.same_model("sonnet", "claude-opus-5"))
        self.assertTrue(worker.same_model("claude-opus-4-8", "claude-opus-4-8"))
        self.assertFalse(worker.same_model("claude-opus-4-8", "claude-opus-5"))

    def test_a_dated_id_is_the_same_version_as_its_undated_name_and_case_does_not_matter(self):
        self.assertTrue(worker.same_model("claude-sonnet-4-5", "claude-sonnet-4-5-20250929"))
        self.assertTrue(worker.same_model("claude-sonnet-4-5-20250929", "claude-sonnet-4-5"))
        self.assertTrue(worker.same_model("Claude-Opus-4-8", "claude-opus-4-8"))
        self.assertFalse(worker.same_model("claude-sonnet-4-5", "claude-sonnet-4-6"))

    def test_the_model_that_ran_is_the_entry_that_answered_not_the_haiku_preflight(self):
        self.assertEqual(worker.model_ran(Envelope(model_usage=usage_of("claude-opus-5"))), "claude-opus-5")
        self.assertIsNone(worker.model_ran(Envelope()), "a result that names no model says nothing")
        self.assertEqual(worker.model_ran(Envelope(model_usage=usage_of("claude-haiku-4-5"))), "claude-haiku-4-5",
                         "a launch on Haiku ran on Haiku: with nothing else in the block, the preflight's family is the answer")

    def test_a_launch_whose_model_is_among_the_models_that_ran_ran_as_asked(self):
        envelope = Envelope(model_usage=usage_of("claude-sonnet-5"))
        self.assertTrue(worker.ran_as_asked("sonnet", envelope))
        self.assertTrue(worker.ran_as_asked("claude-sonnet-5", envelope))
        self.assertFalse(worker.ran_as_asked("claude-sonnet-4-6", envelope))
        self.assertFalse(worker.ran_as_asked("opus", envelope))

    def test_a_subagent_on_another_model_is_no_mismatch(self):
        """A session may run subagents elsewhere; what is asked is whether the rung's model ran, not whether it ran alone."""
        envelope = Envelope(model_usage=usage_of("claude-opus-5", "claude-sonnet-5"))
        self.assertTrue(worker.ran_as_asked("opus", envelope))

    def test_a_result_that_names_no_model_usage_is_not_a_mismatch(self):
        self.assertTrue(worker.ran_as_asked("claude-opus-4-8", Envelope()))
        self.assertTrue(worker.ran_as_asked("claude-opus-4-8", Envelope(model_usage={})))

    def test_the_not_served_refusal_is_read_by_its_status_and_its_text(self):
        self.assertEqual(worker.not_served(not_served("claude-opus-9-9")), "claude-opus-9-9")
        self.assertEqual(worker.not_served(Envelope(api_error_status=404, errors=[NOT_SERVED_TEXT % "mythos"])), "mythos")
        self.assertIsNone(worker.not_served(Envelope(api_error_status=429, result_text=NOT_SERVED_TEXT % "x")),
                          "a 429 is a usage limit, which pacing reads")
        self.assertIsNone(worker.not_served(Envelope(api_error_status=404, result_text="something else went wrong")))
        self.assertIsNone(worker.not_served(None))

    def test_a_not_served_refusal_ran_no_model_at_all(self):
        """`modelUsage` holds only the preflight, which is the clean test the research note named."""
        self.assertFalse(worker.ran_as_asked("claude-sonnet-4-0", not_served()))


class RemapTest(unittest.TestCase):
    """Criterion 1: every `LaunchRequest` turns the legacy model remap off."""

    def request(self, **overrides):
        fields = dict(role="coder", model="sonnet", effort="low", prompt="do it",
                      agent_json={"coder": {"description": "a coder", "prompt": "You code."}})
        fields.update(overrides)
        return worker.LaunchRequest(**fields)

    def test_a_request_built_with_no_environment_still_carries_it(self):
        self.assertEqual(self.request().env[worker.NO_LEGACY_REMAP], "1")

    def test_a_request_built_with_an_environment_keeps_it_and_gains_the_variable(self):
        environment = worker.session_env("/tmp/project", 7, 1, ["src/"])
        request = self.request(env=environment)
        self.assertEqual(request.env[worker.NO_LEGACY_REMAP], "1")
        self.assertEqual(request.env["WAYLINE_TICKET"], "7")

    def test_a_caller_that_spelled_the_variable_itself_keeps_its_value(self):
        self.assertEqual(self.request(env={worker.NO_LEGACY_REMAP: "0"}).env[worker.NO_LEGACY_REMAP], "0")

    def test_a_role_session_the_harness_builds_elsewhere_carries_it(self):
        """The smoke verb's request, built by the launcher itself, stands for every builder outside the conductor."""
        self.assertEqual(worker.smoke_request("/tmp/run").env[worker.NO_LEGACY_REMAP], "1")

    def test_every_request_may_answer_past_the_cli_s_default_output_cap(self):
        """The M6 demo's planner, cutting tickets smaller, wrote one answer past the CLI's 64000-token default."""
        with mock.patch.dict(os.environ):
            os.environ.pop(worker.MAX_OUTPUT_TOKENS, None)
            self.assertEqual(self.request().env[worker.MAX_OUTPUT_TOKENS], str(worker.OUTPUT_TOKENS))
            os.environ[worker.MAX_OUTPUT_TOKENS] = "32000"
            self.assertEqual(self.request().env[worker.MAX_OUTPUT_TOKENS], "32000", "the owner's own setting stands")
        self.assertEqual(self.request(env={worker.MAX_OUTPUT_TOKENS: "8000"}).env[worker.MAX_OUTPUT_TOKENS], "8000")

    def test_a_fallen_back_request_carries_it_too(self):
        request, moved = worker.fall_back(self.request(model="fable"))
        self.assertTrue(moved)
        self.assertEqual(request.env[worker.NO_LEGACY_REMAP], "1")


class ModelCase(PacingCase):
    """The pacing project with tickets at the rungs a test needs, and a notifier the test reads.

    `policy.difficulty` maps level 1 to rung 2 (`sonnet low`), level 2 to rung 3 (`sonnet high`), and
    level 3 to rung 5 (`opus high`), so a test holds one rung by failing a ticket at the level that names it.
    """

    def setUp(self):
        super().setUp()
        self.notified = []

    def conductor(self, workers=1):
        driven = super().conductor(workers)
        driven.notify = lambda name, text, project=None, ticket=None: self.notified.append((name, ticket, text))
        return driven

    def take(self, driven, count):
        """`count` waves, each settling the sessions it started before the next; every wave's result."""
        results = []
        for _ in range(count):
            results.append(driven.wave())
            driven.settle()
        return results

    def script_ran_on(self, identifier, model):
        """Ticket `identifier`'s worker: a done result whose `modelUsage` says `model` answered, and the file it wrote."""
        self.fake.script(ran_on(model, identifier), patch=patch({output(identifier): "hello\n"}, "ticket %d" % identifier),
                         ticket=identifier)

    def failures(self):
        return [(item["payload"]["reason"], item["payload"]["next"]) for item in self.events("ticket_failed")]

    def launches(self):
        return [(item["payload"]["ticket"], item["payload"]["attempt"], item["payload"]["rung"])
                for item in self.events("ticket_launched")]

    def statuses(self):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def decision_tickets(self):
        """Every decision ticket a not-served failure opened, by id, with its fields."""
        return {fields["id"]: fields for fields in tickets.read_tickets(self.project)
                if replay.origin_rung(fields.get("origin")) is not None}


class MismatchTest(ModelCase):
    """Criterion 2: a result whose `modelUsage` names another model fails the attempt, and says which model ran."""

    def test_a_launch_that_ran_elsewhere_fails_with_model_mismatch_and_journals_the_model_that_ran(self):
        driven = self.conductor()
        self.script_ran_on(1, "claude-opus-5")  # rung 2 is `sonnet low`, and Opus is no Sonnet
        self.script(1)  # the attempt one tier up, which goes well
        drive(driven)
        self.assertEqual(self.first("ticket_result")["model_ran"], "claude-opus-5")
        reason, step = self.failures()[0]
        self.assertTrue(reason.startswith("model_mismatch:"), reason)
        self.assertIn("claude-opus-5", reason)
        self.assertEqual(step, "tier_up", "no resume: the session is running on a model nobody asked for")
        self.assertEqual(self.events("ticket_resumed"), [])
        self.assertEqual(self.launches(), [(1, 1, 2), (1, 2, 3)], "the ticket goes on one rung up")
        self.assertEqual(self.statuses()[1], "done")

    def test_every_session_a_run_launches_turns_the_legacy_remap_off(self):
        driven = self.conductor()
        self.script_ran_on(1, "claude-sonnet-5")
        drive(driven)
        self.assertTrue(self.fake.calls)
        self.assertEqual({call.request.env[worker.NO_LEGACY_REMAP] for call in self.fake.calls}, {"1"})

    def test_a_launch_that_ran_as_asked_journals_no_model_ran(self):
        driven = self.conductor()
        self.script_ran_on(1, "claude-sonnet-5")
        drive(driven)
        self.assertNotIn("model_ran", self.first("ticket_result"))
        self.assertEqual(self.failures(), [])


class NotServedTest(ModelCase):
    """Criteria 3 and 4: a name the subscription does not serve holds its rung and asks the owner, and the run goes on."""

    def hold_rung_two(self, driven):
        """Ticket 1, at rung 2, is refused by a name the subscription does not serve; the decision ticket's id."""
        self.script(1, envelope=not_served("claude-sonnet-4-0"))
        self.script(1)  # the attempt one tier up, at rung 3, which goes well
        self.take(driven, 2)
        opened = self.decision_tickets()
        self.assertEqual(len(opened), 1, "one decision ticket per held rung")
        return next(iter(opened))

    def test_the_refusal_fails_the_attempt_without_a_resume_and_without_pausing_the_run(self):
        driven = self.conductor()
        self.hold_rung_two(driven)
        reason, step = self.failures()[0]
        self.assertTrue(reason.startswith("model_not_served:"), reason)
        self.assertIn("claude-sonnet-4-0", reason)
        self.assertEqual(step, "tier_up")
        self.assertEqual(self.events("ticket_resumed"), [], "a 404 is not resumed: the resume would be refused the same way")
        self.assertEqual(self.events("paused"), [], "the refusal cost no window, so it is no model refusal and pauses nothing")
        self.assertNotIn("model_ran", self.first("ticket_result"), "nothing ran, so nothing is named as having run")

    def test_the_held_rung_opens_one_human_only_decision_ticket_naming_the_rung_its_model_and_the_refused_name(self):
        driven = self.conductor()
        identifier = self.hold_rung_two(driven)
        fields = self.decision_tickets()[identifier]
        self.assertTrue(fields["human_only"], "a policy naming a dead model needs the owner's edit")
        self.assertIsNone(fields["blocking"], "the hold on the rung is what holds the work, not this ticket's subgraph")
        self.assertEqual(fields["origin"], replay.not_served_origin(2, 1, 1))
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        self.assertIn("rung 2", decisions.decision_question(fields, body).lower())
        self.assertIn("sonnet", decisions.decision_question(fields, body))
        self.assertIn("claude-sonnet-4-0", body)
        self.assertIn("policy.tiers", body)
        self.assertEqual([name for name, *_ in self.notified], ["decision_opened"])
        self.assertIn("not served", self.notified[0][2])
        self.assertEqual(decisions.for_the_decider(self.project), [],
                         "human-only under every autonomy: the decider never answers it, whatever the project's is")

    def test_a_ticket_at_the_held_rung_waits_while_one_at_another_rung_launches(self):
        self.add(2, difficulty=3)  # rung 5, `opus high`
        self.add(3, difficulty=1)  # rung 2, held
        driven = self.conductor(workers=2)
        self.script(2)
        identifier = self.hold_rung_two(driven)
        self.take(driven, 2)
        launched = {ticket for ticket, *_ in self.launches()}
        self.assertIn(2, launched, "another rung keeps launching")
        self.assertNotIn(3, launched, "its rung is held until the owner answers")
        self.assertEqual(self.statuses()[3], "open")
        self.assertEqual(self.decision_tickets()[identifier]["status"], "open")

    def test_the_same_ticket_launches_at_that_rung_when_nothing_holds_it(self):
        """The control for the test above: what keeps ticket 3 waiting is the hold, not the project."""
        self.add(3, difficulty=1)
        driven = self.conductor(workers=2)
        self.script(1)
        self.script(3)
        self.take(driven, 2)
        self.assertEqual({ticket for ticket, *_ in self.launches()}, {1, 3})
        self.assertEqual(self.decision_tickets(), {})

    def test_a_tier_up_onto_a_held_rung_waits_with_it(self):
        self.add(1, difficulty=2)  # rung 3, `sonnet high`, the rung this test holds
        self.add(2, difficulty=1)  # rung 2; one tier up lands its next attempt on rung 3
        driven = self.conductor(workers=2)
        ladder = dict(driven.policy["escalation"], resume=0, then=["tier_up", "needs_human"])
        driven.policy = dict(driven.policy, escalation=ladder)  # the split is the planner's, and has tests of its own
        self.script(1, envelope=not_served("claude-sonnet-4-6"))
        self.script(1)  # ticket 1 goes on at rung 4, one rung up from the held rung (ticket 61)
        self.fake.script(failing(2), ticket=2)
        self.take(driven, 3)
        self.assertEqual([step for _, step in self.failures()], ["tier_up", "tier_up"])
        self.assertEqual(self.launches(), [(1, 1, 3), (2, 1, 2), (1, 2, 4)],
                         "ticket 2's tier up waits on the held rung while ticket 1 goes on at another")
        self.assertEqual(self.statuses()[2], "open")

    def test_the_answer_lifts_the_hold_and_the_waiting_ticket_launches(self):
        self.add(3, difficulty=1)
        driven = self.conductor()
        identifier = self.hold_rung_two(driven)
        self.take(driven, 1)
        self.assertNotIn(3, {ticket for ticket, *_ in self.launches()})
        project.answer(self.project, identifier, "rung 2 now names sonnet", by="human")
        self.script(3)
        self.take(driven, 2)
        self.assertIn(3, {ticket for ticket, *_ in self.launches()}, "the answer lifted the hold")
        self.assertEqual(self.statuses()[3], "done")

    def test_a_second_refusal_at_a_held_rung_opens_no_second_decision_ticket(self):
        self.add(2, difficulty=1)  # rung 2 as well
        driven = self.conductor(workers=2)
        identifier = self.hold_rung_two(driven)
        self.assertEqual(list(self.decision_tickets()), [identifier])
        # The hold keeps ticket 2 from launching at all, so the refusal is met again only by replaying it here.
        view = replay.replay(self.events())
        self.assertEqual(view.held_rungs(), {2: identifier})


class HeldRungReplayTest(ProjectTestCase):
    """Criterion 4: the hold is the journal's, so a replay rebuilds it and an answer lifts it."""

    def created(self, ticket, origin, at=0):
        return event("ticket_created", {"ticket": ticket, "kind": "decision", "proposed_by": "conductor",
                                        "origin": origin, "blocked_by": []}, ticket=ticket, at=at)

    def journal(self):
        """A run in which rung 2's model was refused at ticket 1 and rung 5 kept launching."""
        return [
            event("run_started", {"resume": False, "harness_tag": "v0", "autonomy": "autonomous",
                                  "radius": "normal", "pid": 10}, at=0),
            event("ticket_launched", {"ticket": 1, "attempt": 1, "role": "coder", "model": "sonnet", "effort": "low",
                                      "skills": [], "worktree": "/p/.worktrees/1", "pid": 11, "context_chars": 10,
                                      "prompt_sha256": "0" * 64, "difficulty": 1, "rung": 2}, ticket=1, at=1),
            event("ticket_failed", {"ticket": 1, "attempt": 1, "reason": "model_not_served: the subscription does not "
                                                                         "serve claude-sonnet-4-0", "next": "tier_up"}, ticket=1, at=2),
            self.created(9, replay.not_served_origin(2, 1, 1), at=3),
            event("decision_opened", {"ticket": 9, "blocking": None, "human_only": True}, ticket=9, at=4),
            event("ticket_launched", {"ticket": 2, "attempt": 1, "role": "coder", "model": "opus", "effort": "high",
                                      "skills": [], "worktree": "/p/.worktrees/2", "pid": 12, "context_chars": 10,
                                      "prompt_sha256": "0" * 64, "difficulty": 3, "rung": 5}, ticket=2, at=5),
        ]

    def test_a_replay_rebuilds_the_hold_and_holds_only_that_rung(self):
        view = replay.replay(self.journal())
        self.assertEqual(view.held_rungs(), {2: 9})
        self.assertEqual(view.tickets[2].latest.rung, 5, "the other rung kept launching")

    def test_the_decision_tickets_answer_lifts_the_hold(self):
        answered = self.journal() + [event("decision", {"ticket": 9, "answer": "rung 2 now names sonnet",
                                                        "decided_by": "human", "rationale": None, "confidence": None},
                                           ticket=9, at=6)]
        self.assertEqual(replay.replay(answered).held_rungs(), {})

    def test_replaying_the_same_journal_twice_holds_the_same_rungs(self):
        events = self.journal()
        self.assertEqual(replay.replay(events).held_rungs(), replay.replay(events).held_rungs())
        folded = replay.replay(events)
        replay.replay(events, folded)  # the same events folded in again
        self.assertEqual(folded.held_rungs(), {2: 9})
        self.assertEqual(len(folded.rung_asks), 1)

    def test_a_rung_refused_again_after_its_ask_was_answered_is_held_again(self):
        events = self.journal() + [
            event("decision", {"ticket": 9, "answer": "edited", "decided_by": "human", "rationale": None,
                               "confidence": None}, ticket=9, at=6),
            self.created(10, replay.not_served_origin(2, 3, 1), at=7),
        ]
        self.assertEqual(replay.replay(events).held_rungs(), {2: 10})


class VerdictModelTest(GateCase):
    """Criterion 2: a verdict carries `model_ran` when its own session ran on another model."""

    @staticmethod
    def judged_on(model):
        """A passing verdict whose result says `model` answered; the verifier for a Sonnet author is Opus."""
        envelope = passing()
        envelope.model_usage = usage_of(model)
        return envelope

    def test_a_verdict_whose_session_ran_elsewhere_journals_the_model_that_ran(self):
        taken = self.take(self.judged_on("claude-sonnet-5"))
        self.assertEqual(taken.model_ran, "claude-sonnet-5")
        self.assertEqual(self.events("verdict")[-1]["payload"]["model_ran"], "claude-sonnet-5")

    def test_a_verdict_that_ran_as_asked_journals_no_model_ran(self):
        taken = self.take(self.judged_on("claude-opus-5"))
        self.assertIsNone(taken.model_ran)
        self.assertNotIn("model_ran", self.events("verdict")[-1]["payload"])

    def test_every_verdict_session_turns_the_legacy_remap_off(self):
        self.take(passing())
        self.assertEqual([call.request.env[worker.NO_LEGACY_REMAP] for call in self.calls], ["1"])


class LabelTest(ProjectTestCase):
    """Criterion 5: `wayline status` and the dashboard's ticket page show both models when they differ."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.ledger = Ledger(self.project)

    def running(self):
        """The one ticket the fixture journal left running, which is the one these launches are added to."""
        view = project.status_view(self.project)
        self.assertEqual(len(view["running"]), 1)
        return view["running"][0]["id"]

    def launch(self, attempt, **payload):
        fields = {"ticket": self.running(), "attempt": attempt, "role": "coder", "model": "claude-opus-4-8",
                  "effort": "high", "skills": [], "worktree": ".worktrees/1", "pid": 4242, "context_chars": 100,
                  "prompt_sha256": "b" * 64, "difficulty": 3, "rung": 5}
        fields.update(payload)
        self.ledger.append_event("ticket_launched", fields, ticket=fields["ticket"])

    def result(self, attempt, **payload):
        fields = {"ticket": self.running(), "attempt": attempt, "session_id": "s-%d" % attempt, "status": "done",
                  "turns": 3, "duration_ms": 10, "usage": {}, "permission_denials": [], "valid": True}
        fields.update(payload)
        self.ledger.append_event("ticket_result", fields, ticket=fields["ticket"])

    def line(self):
        view = project.status_view(self.project)
        return view["running"][0], view

    def test_the_label_names_the_rung_then_the_model_that_ran(self):
        self.assertEqual(project.rung_label(5, "claude-opus-4-8", "high", "claude-opus-5"),
                         "r5 claude-opus-4-8 high, ran claude-opus-5")
        self.assertEqual(project.rung_label(5, "claude-opus-4-8", "high", None), "r5 claude-opus-4-8 high")

    def test_status_shows_both_models_on_a_launch_whose_model_was_not_its_rungs(self):
        self.launch(4)
        self.result(4, model_ran="claude-opus-5")
        entry, view = self.line()
        self.assertEqual(entry["launch"], "r5 claude-opus-4-8 high, ran claude-opus-5")
        self.assertIn("r5 claude-opus-4-8 high, ran claude-opus-5", project.render_status(view))

    def test_a_launch_that_ran_as_asked_shows_one_model(self):
        self.launch(4)
        self.result(4)
        self.assertEqual(self.line()[0]["launch"], "r5 claude-opus-4-8 high")

    def test_the_next_launch_is_labeled_by_its_own_result(self):
        self.launch(4)
        self.result(4, model_ran="claude-opus-5")
        self.launch(5)
        self.assertEqual(self.line()[0]["launch"], "r5 claude-opus-4-8 high")

    def test_the_dashboards_ticket_page_labels_each_attempt_the_same_way(self):
        self.launch(4)
        self.result(4, model_ran="claude-opus-5")
        self.assertEqual(dashboard._launch_labels(self.project, self.running())[4],
                         "r5 claude-opus-4-8 high, ran claude-opus-5")


if __name__ == "__main__":
    unittest.main()
