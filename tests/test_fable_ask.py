"""Ask the owner when Fable is spent (ticket 57; Implementation Decision 15).

The conductor is driven with the fake launcher over the hold project of tickets 54 and 55: a ticket
on Fable (difficulty 4) held by a journaled hold on Fable's weekly window, the fallback consent set as
the owner sets it, the notifier recorded, and a clock the test moves across the ask's timeout and the
window's reset. What is asserted is what the owner and the next process see: the ask's ticket file and
record, the journal, the notifications, the launches after each answer, `wayline status`, and the
dashboard's action and decisions view over HTTP.
"""

import io
import time
import unittest
from unittest import mock

from tests.projects import on_fable
from tests.test_actions import STATIC, ActionCase
from tests.test_fallback import FallbackCase
from tests.test_pacing import HOUR
from wayline import decisions, grill, pacing, replay, tick, tickets
from wayline import project as wayline_project
from wayline.conductor import Conductor
from wayline.jsonschema import check, load_schema
from wayline.project import (
    ProjectError, answer, fable_falls_back, falls_back_now, read_harness, render_status, set_autonomy, set_model_fallback, status_view,
)


class AskCase(FallbackCase):
    """The hold project with the notifier recorded and the ask read back from its ticket file and the journal."""

    def conductor(self, workers=1):
        driven = super().conductor(workers)
        self.notified = []
        driven.notify = self.record
        return driven

    def record(self, event, text, path=None, ticket=None):
        self.notified.append((event, ticket, text))

    def restarted(self, driven):
        """A conductor started again over the same project, fake, clock, and notifier."""
        again = Conductor(self.project, out=io.StringIO())
        again.policy, again.clock, again.notify = driven.policy, driven.clock, self.record
        self.addCleanup(again.settle, 30)
        return again

    def statuses(self):
        """Every ticket's status, the ask's included, which the hold's tests leave out."""
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def asks(self):
        return [ticket for ticket in tickets.read_tickets(self.project) if pacing.ask_window(ticket.get("origin")) is not None]

    def body(self, identifier):
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[identifier]
        return tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]

    def decisions(self):
        return [item["payload"] for item in self.events("decision")]

    def controls(self):
        return [item["payload"] for item in self.events("control")]

    def resets(self, hours):
        return pacing.iso(self.now[0] + hours * HOUR)

    def opened(self, consent="ask", hours=10, autonomy=None):
        """Ticket 1 on Fable held under `consent` (None: no key) for `hours`, and the wave that opened the ask; the conductor and its id."""
        self.add(1, difficulty=4)
        if autonomy is not None:
            set_autonomy(self.project, autonomy)
        self.hold_journaled(hours)
        if consent is not None:
            self.consent(consent)
        driven = self.conductor()
        self.assertEqual(driven.wave().launched, [])
        (ask,) = self.asks()
        return driven, ask["id"]


class OpenAskTest(AskCase):
    """Criterion 1: one ask per spent window, when the hold first drops a launch, with its options, recommendation, and notification."""

    def setUp(self):
        super().setUp()
        on_fable(self.project, "verifier.opus")  # work written on Opus is read on Fable, which the hold holds

    def test_the_first_dropped_launch_opens_one_human_only_ask_keyed_by_the_reset_that_pauses_nothing_and_notifies(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        self.hold_journaled(10)
        self.consent("ask")
        driven = self.conductor()
        self.script(2)
        self.assertEqual(driven.wave().launched, [2], "the hold drops only the launch on Fable")
        (ask,) = self.asks()
        identifier = ask["id"]
        self.assertEqual((ask["kind"], ask["status"], ask["human_only"], ask["blocking"], ask["proposed_by"], ask["origin"], ask["blocked_by"]),
                         ("decision", "open", True, None, "conductor", pacing.ask_origin(self.resets(10)), []))
        record = decisions.decision_record(self.body(identifier))
        self.assertEqual((record["options"], record["recommended"], record["human_only"], record["blocking"]),
                         (["fall back", "wait", "always fall back", "always wait"], "wait", True, None))
        self.assertIn("held on Fable: ticket 1", record["evidence"])
        self.assertEqual([item["payload"] for item in self.events("decision_opened")],
                         [{"ticket": identifier, "blocking": None, "human_only": True}])
        ((event, ticket, text),) = self.notified
        self.assertEqual((event, ticket), ("decision_opened", identifier))
        for said in (self.resets(10), "it holds ticket 1", "recommended: wait", 'wayline answer %d "<option>"' % identifier):
            self.assertIn(said, text)
        self.assertNotIn(2, [entry for entry in tickets.read_tickets(self.project) if identifier in entry["blocked_by"]])

        driven.settle()
        driven.wave()
        self.restarted(driven).wave()
        self.assertEqual(([ask["id"] for ask in self.asks()], len(self.events("decision_opened")), len(self.notified)), ([identifier], 1, 1),
                         "neither the next wave nor a restart opens a second ask about the window")
        status = render_status(status_view(self.project))
        self.assertIn("#%-3d %s  (human_only)" % (identifier, ask["title"]), status)
        self.assertNotIn("falls back at", status, "an explicit ask never times out")

    def test_the_recommendation_is_fall_back_when_the_reset_is_at_least_wait_under_hours_away(self):
        self.opened(hours=13)
        (ask,) = self.asks()
        self.assertEqual(decisions.decision_record(self.body(ask["id"]))["recommended"], "fall back")

    def test_a_policy_that_waits_longer_recommends_wait_further_from_the_reset(self):
        self.add(1, difficulty=4)
        self.hold_journaled(30)
        driven = self.conductor()
        driven.policy = dict(driven.policy, model_fallback={"wait_under_hours": 48, "ask_timeout_hours": 2})
        driven.wave()
        (ask,) = self.asks()
        self.assertEqual(decisions.decision_record(self.body(ask["id"]))["recommended"], "wait")

    def test_a_spent_week_with_nothing_waiting_on_fable_asks_nothing(self):
        self.add(1, difficulty=1)
        self.hold_journaled(10)
        driven = self.conductor()
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        driven.settle()
        driven.wave()
        self.assertEqual((self.asks(), self.events("decision_opened"), self.notified), ([], [], []))

    def nobody_asked_under(self, consent):
        self.add(1, difficulty=4)
        self.hold_journaled(10)
        self.consent(consent)
        driven = self.conductor()
        self.script(1)
        driven.wave()
        driven.settle()
        driven.wave()
        self.assertEqual((self.asks(), self.events("decision_opened")), ([], []))

    def test_under_wait_nobody_is_asked(self):
        self.nobody_asked_under("wait")

    def test_under_auto_nobody_is_asked(self):
        self.nobody_asked_under("auto")

    def test_verdicts_the_hold_keeps_on_fable_open_the_ask_too(self):
        self.add(1, difficulty=3)
        self.consent("ask")
        driven = self.conductor()
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        driven.settle()
        self.hold_journaled(10)
        carried = driven.wave()
        self.assertEqual((carried.done, carried.accepted), ([1], []), "the verdict on Opus's work runs on Fable, and waits")
        (ask,) = self.asks()
        self.assertIn("held on Fable: the verdicts on ticket 1", decisions.decision_record(self.body(ask["id"]))["evidence"])


class AnswerAskTest(AskCase):
    """Criterion 2: each answer, trimmed and case-insensitive, takes effect at the next wave."""

    def test_fall_back_falls_back_for_this_window_and_leaves_the_consent_as_it_was(self):
        driven, identifier = self.opened()
        self.script(1)
        answer(self.project, identifier, "  Fall Back ")
        self.assertTrue(fable_falls_back(self.project, self.now[0]), "a launch outside the conductor falls back too")
        waved = driven.wave()
        self.assertEqual(waved.launched, [1])
        self.assertEqual((self.launches(1)[0]["model"], self.launches(1)[0]["fallback_from"]), ("opus", "r6 fable low"))
        self.assertEqual(self.statuses()[identifier], "done")
        self.assertEqual(read_harness(self.project)["model_fallback"], "ask")
        self.assertEqual([item["args"]["model_fallback"] for item in self.controls()], ["ask"], "no consent is journaled for this window alone")
        self.assertIn("Fable work falls back to Opus while Fable's weekly window is spent until %s" % self.resets(10), driven.out.getvalue())

    def test_wait_waits_for_the_reset(self):
        driven, identifier = self.opened()
        self.script(1)
        answer(self.project, identifier, "WAIT")
        self.assertEqual(driven.wave().launched, [])
        self.assertEqual(self.statuses()[identifier], "done")
        self.assertFalse(fable_falls_back(self.project, self.now[0]))
        self.assertEqual(self.asks()[0]["id"], identifier)
        self.assertEqual(len(self.events("decision_opened")), 1, "an answered ask is not asked again while its window lasts")

    def test_always_fall_back_also_journals_control_model_fallback_auto(self):
        driven, identifier = self.opened()
        self.script(1)
        answer(self.project, identifier, "always fall back")
        self.assertEqual(self.controls()[-1], {"command": "model_fallback", "args": {"model_fallback": "auto"}, "by": "cli"})
        self.assertEqual(read_harness(self.project)["model_fallback"], "auto")
        self.assertEqual(driven.wave().launched, [1])
        self.assertEqual(self.launches(1)[0]["fallback_from"], "r6 fable low")
        self.assertEqual([item["answer"] for item in self.decisions()], ["always fall back"], "an answered ask is not superseded by its own consent")

    def test_always_wait_written_into_the_ticket_file_also_journals_control_model_fallback_wait(self):
        driven, identifier = self.opened()
        self.script(1)
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[identifier]
        tickets.write_ticket(self.ledger, fields, tickets.with_answer(self.body(identifier), "Always Wait"))
        self.assertEqual(driven.wave().launched, [])
        self.assertEqual(self.decisions(), [{"ticket": identifier, "answer": "Always Wait", "decided_by": "human", "rationale": None, "confidence": None}])
        self.assertEqual(self.controls()[-1], {"command": "model_fallback", "args": {"model_fallback": "wait"}, "by": "file"})
        self.assertEqual(read_harness(self.project)["model_fallback"], "wait")

    def test_an_answer_matching_no_option_counts_as_wait_and_a_notification_says_so(self):
        driven, identifier = self.opened()
        self.script(1)
        answer(self.project, identifier, "fall back, but only for the planner")
        self.assertEqual(driven.wave().launched, [])
        self.assertEqual(self.statuses()[identifier], "done")
        ((event, ticket, text),) = [item for item in self.notified if item[0] == "decision"]
        self.assertEqual(ticket, identifier)
        for said in ("counts as wait", "fall back, but only for the planner", "wayline rerun %d" % identifier):
            self.assertIn(said, text)
        self.assertEqual(read_harness(self.project)["model_fallback"], "ask")


class CloseAskTest(AskCase):
    """Criterion 3: the reset or a change of consent closes an unanswered ask as superseded, and a late answer is refused."""

    def test_the_first_wave_past_the_reset_closes_it_as_superseded_and_fable_work_goes_on_on_fable(self):
        driven, identifier = self.opened(hours=10)
        self.now[0] += 11 * HOUR
        self.script(1)
        waved = driven.wave()
        (closed,) = self.decisions()
        self.assertEqual((closed["ticket"], closed["answer"], closed["decided_by"], closed["confidence"]),
                         (identifier, "superseded", "conductor", None))
        self.assertIn("reset at %s" % self.resets(-1), closed["rationale"])
        self.assertEqual(self.statuses()[identifier], "done")
        self.assertEqual(tickets.answer_section(self.body(identifier)), "superseded")
        self.assertEqual(waved.launched, [1], "the hold ended at the reset")
        self.assertEqual((self.launches(1)[0]["model"], self.launches(1)[0].get("fallback_from")), ("fable", None))

        with self.assertRaisesRegex(ProjectError, "closed by the conductor"):
            answer(self.project, identifier, "fall back")
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[identifier]
        rewritten = self.body(identifier).replace("## Answer\n\nsuperseded\n", "## Answer\n\nfall back\n")
        self.assertEqual(tickets.answer_section(rewritten), "fall back")
        tickets.write_ticket(self.ledger, fields, rewritten)
        driven.settle()
        driven.wave()
        self.assertEqual([item["answer"] for item in self.decisions()], ["superseded"], "an answer written after the close is not taken")

    def test_a_decision_the_conductor_closed_is_one_the_schema_and_the_grill_accept(self):
        driven, identifier = self.opened(hours=1)
        self.now[0] += 2 * HOUR
        driven.wave()
        record = dict(decisions.decision_record(self.body(identifier)), answer="superseded", decided_by="conductor",
                      rationale=self.decisions()[0]["rationale"], timestamp=self.events("decision")[0]["ts"])
        check(record, load_schema("decision"))
        self.assertEqual(grill.parse_records(grill.machine_line(record), source="the test")[0]["decided_by"], "conductor")
        self.assertIn("conductor", grill.DECIDERS)
        (logged,) = decisions.decisions_view(self.project)["log"]
        self.assertEqual((logged["ticket"], logged["decided_by"], logged["answer"]), (identifier, "conductor", "superseded"))

    def test_a_consent_set_to_auto_while_it_is_open_closes_it_and_fable_work_falls_back(self):
        driven, identifier = self.opened()
        self.script(1)
        set_model_fallback(self.project, "auto", by="dashboard")
        self.assertEqual(driven.wave().launched, [1])
        (closed,) = self.decisions()
        self.assertEqual((closed["answer"], closed["decided_by"]), ("superseded", "conductor"))
        self.assertIn("set to auto", closed["rationale"])
        self.assertEqual(self.launches(1)[0]["fallback_from"], "r6 fable low")

    def test_a_consent_set_to_wait_while_it_is_open_closes_it_and_fable_work_waits_with_nobody_asked_again(self):
        driven, identifier = self.opened()
        self.script(1)
        set_model_fallback(self.project, "wait")
        self.assertEqual(driven.wave().launched, [])
        self.assertEqual([(item["answer"], item["decided_by"]) for item in self.decisions()], [("superseded", "conductor")])
        driven.wave()
        self.assertEqual((len(self.asks()), len(self.events("decision_opened"))), (1, 1))

    def test_a_consent_set_to_ask_again_closes_nothing(self):
        driven, identifier = self.opened(consent=None)
        set_model_fallback(self.project, "ask")
        driven.wave()
        self.assertEqual(self.decisions(), [])
        self.assertEqual(self.statuses()[identifier], "open")


class AskTimeoutTest(AskCase):
    """Criterion 4: only a project without the key, under `autonomous`, falls back after the timeout."""

    def test_without_the_key_under_autonomous_it_falls_back_for_this_window_after_ask_timeout_hours(self):
        driven, identifier = self.opened(consent=None, autonomy="autonomous")
        opened = pacing.epoch(self.events("ticket_created")[-1]["ts"])
        at = pacing.iso(opened + 2 * HOUR)
        self.assertIn("#%-3d %s  (human_only)  falls back at %s unless answered" % (identifier, self.asks()[0]["title"], at),
                      render_status(status_view(self.project)))
        (entry,) = decisions.decisions_view(self.project)["open"]
        self.assertEqual((entry["id"], entry["falls_back_at"], entry["awaits"]), (identifier, at, "owner"))

        self.script(1)
        self.now[0] += HOUR
        self.assertEqual(driven.wave().launched, [])
        self.assertEqual(self.decisions(), [], "an hour in, the ask still waits")
        self.now[0] = opened + 2 * HOUR + 1
        waved = driven.wave()
        (timed_out,) = self.decisions()
        self.assertEqual((timed_out["ticket"], timed_out["answer"], timed_out["decided_by"]), (identifier, "fall back", "conductor"))
        self.assertIn("ask_timeout_hours (2)", timed_out["rationale"])
        self.assertEqual(waved.launched, [1], "the timeout's answer is read before the wave launches")
        self.assertEqual(self.launches(1)[0]["fallback_from"], "r6 fable low")
        self.assertNotIn("model_fallback", read_harness(self.project), "the timeout answers for the window, never for the project")
        with self.assertRaisesRegex(ProjectError, "closed by the conductor"):
            answer(self.project, identifier, "wait")

    def waits_past_the_timeout(self, consent, autonomy):
        driven, identifier = self.opened(consent=consent, hours=48, autonomy=autonomy)
        self.now[0] += 47 * HOUR
        driven.wave()
        self.assertEqual(self.decisions(), [])
        self.assertEqual(self.statuses()[identifier], "open")
        self.assertNotIn("falls back at", render_status(status_view(self.project)))

    def test_an_explicit_ask_never_times_out_under_autonomous(self):
        self.waits_past_the_timeout("ask", "autonomous")

    def test_without_the_key_under_checkpoints_the_ask_waits(self):
        self.waits_past_the_timeout(None, "checkpoints")

    def test_without_the_key_under_interactive_the_ask_waits(self):
        self.waits_past_the_timeout(None, "interactive")

    def test_a_policy_timeout_is_read_from_policy_model_fallback(self):
        driven, identifier = self.opened(consent=None, autonomy="autonomous")
        driven.policy = dict(driven.policy, model_fallback={"wait_under_hours": 12, "ask_timeout_hours": 0.5})
        self.now[0] += HOUR
        driven.wave()
        self.assertEqual([item["answer"] for item in self.decisions()], ["fall back"])
        self.assertIn("ask_timeout_hours (0.5)", self.decisions()[0]["rationale"])


class ReviewedAskTest(AskCase):
    """Found by the review: a hold whose reset moved, a consent set back to ask, a late answer, a failed always answer, and the tick."""

    def setUp(self):
        super().setUp()
        on_fable(self.project, "verifier.opus")  # work written on Opus is read on Fable, which the hold holds

    def test_an_answer_holds_when_a_later_refusal_moves_the_hold_s_reset_and_nobody_is_asked_twice(self):
        driven, identifier = self.opened(hours=10)
        answer(self.project, identifier, "fall back")
        later = self.resets(30)
        self.ledger.append_event("paused", {"resets_at": later, "window": "seven_day", "utilization": 1.0, "model": "fable"})
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        self.assertEqual(self.launches(1)[0]["fallback_from"], "r6 fable low")
        driven.settle()
        driven.wave()
        self.assertEqual((len(self.asks()), len(self.events("decision_opened"))), (1, 1))
        self.assertEqual(replay.replay(self.events()).ask_for(later), identifier)
        self.assertTrue(fable_falls_back(self.project, self.now[0] + 11 * HOUR), "past the first reset, the answer still holds until the moved one")

    def test_a_consent_set_to_wait_and_back_to_ask_before_the_next_wave_closes_nothing(self):
        driven, identifier = self.opened()
        set_model_fallback(self.project, "wait")
        set_model_fallback(self.project, "ask")
        driven.wave()
        self.assertEqual(self.decisions(), [])
        self.assertEqual(self.statuses()[identifier], "open")

    def test_a_late_answer_is_told_how_to_set_the_consent_and_not_to_rerun(self):
        driven, identifier = self.opened()
        set_model_fallback(self.project, "auto")
        driven.wave()
        with self.assertRaises(ProjectError) as refused:
            answer(self.project, identifier, "fall back")
        self.assertIn("wayline switch --fallback", str(refused.exception))
        self.assertNotIn("rerun", str(refused.exception))

    def test_an_always_answer_whose_consent_cannot_be_set_journals_no_answer(self):
        driven, identifier = self.opened()
        with mock.patch.object(wayline_project, "set_model_fallback", side_effect=ProjectError("harness.json cannot be read")):
            with self.assertRaisesRegex(ProjectError, "cannot be read"):
                answer(self.project, identifier, "always fall back")
        self.assertEqual((self.decisions(), tickets.answer_section(self.body(identifier))), ([], None))

    def test_the_tick_relaunches_a_conductor_for_verdicts_on_fable_once_the_ask_timed_out(self):
        set_autonomy(self.project, "autonomous")
        self.add(1, difficulty=3)
        driven = self.conductor()
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        driven.settle()
        self.hold_journaled(10)
        driven.wave()
        self.assertEqual(len(self.asks()), 1)
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": "autonomous", "radius": "moderate",
                                                 "pid": 999999})
        opened = pacing.epoch(self.events("ticket_created")[-1]["ts"])
        reason, why = tick.relaunch_decision(self.project, self.ledger, driven.policy, None, opened + HOUR)
        self.assertIsNone(reason)
        self.assertIn("wait for a verdict on Fable", why)
        reason, why = tick.relaunch_decision(self.project, self.ledger, driven.policy, None, opened + 2 * HOUR + 1)
        self.assertIsNone(why)
        self.assertIn("owed a verdict", reason)


class AskReplayTest(unittest.TestCase):
    """The ask as the journal replays it: keyed by the reset its origin names, and closed by a consent that stops asking."""

    RESETS = "2026-09-16T02:00:00Z"

    @staticmethod
    def created(ticket, origin, ts="2026-09-14T10:00:00.000Z"):
        return {"event": "ticket_created", "ts": ts, "ticket": ticket, "payload": {"ticket": ticket, "kind": "decision", "origin": origin}}

    @staticmethod
    def control(consent):
        return {"event": "control", "payload": {"command": "model_fallback", "args": {"model_fallback": consent}, "by": "cli"}}

    @staticmethod
    def decided(ticket, text, by="human"):
        return {"event": "decision", "ticket": ticket, "payload": {"ticket": ticket, "answer": text, "decided_by": by}}

    def hold(self):
        return {"event": "paused", "payload": {"resets_at": self.RESETS, "window": "seven_day", "utilization": 1.0, "model": "fable"}}

    def test_an_ask_is_found_by_its_window_and_another_decision_ticket_is_not_an_ask(self):
        view = replay.replay([self.created(4, "ticket 1 attempt 1: decision request abc"), self.created(5, pacing.ask_origin(self.RESETS))])
        self.assertEqual(view.asks, {5: {"resets_at": self.RESETS, "opened": "2026-09-14T10:00:00.000Z"}})
        self.assertEqual((view.ask_for(self.RESETS), view.ask_for("2026-09-23T02:00:00Z")), (5, None))

    def paused(self, resets, ts):
        return {"event": "paused", "ts": ts, "payload": {"resets_at": resets, "window": "seven_day", "utilization": 1.0, "model": "fable"}}

    def test_a_later_reset_of_the_standing_hold_moves_the_ask_and_its_answer_with_it(self):
        later = "2026-09-20T02:00:00Z"
        view = replay.replay([self.paused(self.RESETS, "2026-09-14T09:00:00.000Z"), self.created(5, pacing.ask_origin(self.RESETS)),
                              self.decided(5, "fall back"), self.paused(later, "2026-09-14T11:00:00.000Z")])
        self.assertEqual((view.ask_for(later), view.ask_for(self.RESETS), view.asks[5]["resets_at"]), (5, None, later))
        self.assertTrue(falls_back_now("ask", view))

    def test_a_hold_journaled_after_the_last_reset_is_another_week_and_its_ask_stays_with_its_own(self):
        next_week = "2026-09-23T02:00:00Z"
        view = replay.replay([self.paused(self.RESETS, "2026-09-14T09:00:00.000Z"), self.created(5, pacing.ask_origin(self.RESETS)),
                              self.decided(5, "fall back"), self.paused(next_week, "2026-09-17T09:00:00.000Z")])
        self.assertEqual((view.ask_for(next_week), view.ask_for(self.RESETS)), (None, 5))
        self.assertFalse(falls_back_now("ask", view), "last week's answer says nothing of this week")

    def test_falls_back_now_under_each_consent_and_answer(self):
        view = replay.replay([self.hold(), self.created(5, pacing.ask_origin(self.RESETS))])
        self.assertEqual([falls_back_now(consent, view) for consent in ("auto", "ask", "wait")], [True, False, False])
        for text, expected in (("fall back", True), (" ALWAYS FALL BACK", True), ("wait", False), ("always wait", False),
                               ("superseded", False), ("yes please", False)):
            with self.subTest(answer=text):
                answered = replay.replay([self.decided(5, text)], replay.replay([self.hold(), self.created(5, pacing.ask_origin(self.RESETS))]))
                self.assertEqual(falls_back_now("ask", answered), expected)
                self.assertFalse(falls_back_now("wait", answered))
        other = replay.replay([self.hold(), self.created(5, pacing.ask_origin("2026-09-09T02:00:00Z")), self.decided(5, "fall back")])
        self.assertFalse(falls_back_now("ask", other), "an answer about another window says nothing of this one")
        self.assertFalse(falls_back_now("ask", replay.replay([])), "no hold, nothing to fall back from")


class AskHelpersTest(unittest.TestCase):
    def test_an_answer_is_matched_trimmed_and_case_insensitively(self):
        self.assertEqual([pacing.ask_choice(text) for text in ("fall back", " Wait\n", "ALWAYS FALL BACK", "always  wait", "", None)],
                         ["fall back", "wait", "always fall back", None, None, None])

    def test_the_recommendation_turns_at_wait_under_hours(self):
        now = 1_000_000
        self.assertEqual(pacing.ask_recommended(now + 12 * HOUR - 1, now), "wait")
        self.assertEqual(pacing.ask_recommended(now + 12 * HOUR, now), "fall back")
        self.assertEqual(pacing.ask_recommended(now + 30 * HOUR, now, wait_under_hours=48), "wait")

    def test_the_policy_hours_fall_back_to_the_defaults_for_a_value_that_is_not_hours(self):
        self.assertEqual(pacing.ask_hours({}), (12, 2))
        self.assertEqual(pacing.ask_hours({"model_fallback": {"wait_under_hours": 6, "ask_timeout_hours": "soon"}}), (6, 2))

    def test_the_origin_names_the_window_and_nothing_else_is_an_ask(self):
        self.assertEqual(pacing.ask_window(pacing.ask_origin("2026-09-16T02:00:00Z")), "2026-09-16T02:00:00Z")
        self.assertIsNone(pacing.ask_window("ticket 3 attempt 1: decision request 0a1b2c3d4e5f"))
        self.assertIsNone(pacing.ask_window(None))

    def test_a_blocking_null_decision_ticket_names_no_ticket_to_pause(self):
        with self.assertRaisesRegex(ValueError, "pauses no ticket"):
            decisions.open_decision("/nonexistent", "A question?", blocking=None, pauses=[1])


class AskActionTest(ActionCase):
    """Criterion 5 over HTTP: the `model_fallback` action behind the token, and the ask answered on the decisions view's form."""

    def test_the_model_fallback_action_writes_harness_json_and_journals_control_by_the_dashboard(self):
        response = self.act("model_fallback", {"model_fallback": "auto"})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual((response.json["from"], response.json["to"], response.json["changed"]), (None, "auto", True))
        self.assertEqual(read_harness(self.project)["model_fallback"], "auto")
        self.assertEqual(self.events("control")[-1]["payload"], {"command": "model_fallback", "args": {"model_fallback": "auto"}, "by": "dashboard"})

    def test_without_the_token_or_with_a_wrong_one_it_is_refused_and_a_consent_nobody_holds_is_a_400(self):
        for token in (None, "wrong"):
            with self.subTest(token=token):
                self.assertEqual(self.act("model_fallback", {"model_fallback": "auto"}, token=token).status, 403)
        refused = self.act("model_fallback", {"model_fallback": "sometimes"})
        self.assertEqual(refused.status, 400)
        self.assertIn("one of auto, ask, wait", refused.json["error"])
        self.assertEqual(self.act("model_fallback", {}).status, 400)
        self.assertEqual(self.events("control"), [])
        self.assertNotIn("model_fallback", read_harness(self.project))

    def test_the_decisions_view_carries_the_ask_and_its_form_answers_it(self):
        resets = pacing.iso(time.time() + 20 * HOUR)
        opened = decisions.open_fable_ask(self.project, resets, ["ticket 3"], notify=lambda *arguments: None)
        view = self.request("GET", "/api/projects/%s/decisions" % self.project.name)
        self.assertEqual(view.status, 200, view.text)
        (entry,) = [item for item in view.json["open"] if item["id"] == opened["ticket"]]
        self.assertEqual((entry["options"], entry["recommended"], entry["human_only"], entry["blocking"], entry["pauses"], entry["falls_back_at"]),
                         (["fall back", "wait", "always fall back", "always wait"], "fall back", True, None, [], None))
        self.assertEqual({key: view.json["controls"][key] for key in ("model_fallback", "model_fallback_stated", "model_fallback_levels")},
                         {"model_fallback": "ask", "model_fallback_stated": False, "model_fallback_levels": ["auto", "ask", "wait"]})

        response = self.act("answer", {"ticket": opened["ticket"], "answer": "always fall back"})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(response.json["decision"]["answer"], "always fall back")
        self.assertEqual(self.events("control")[-1]["payload"], {"command": "model_fallback", "args": {"model_fallback": "auto"}, "by": "dashboard"})
        self.assertEqual(read_harness(self.project)["model_fallback"], "auto")

    def test_the_page_carries_the_fallback_consent_control(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        for element in ("model-fallback-form", "model-fallback-select", "model-fallback-set", "model-fallback-current"):
            with self.subTest(element=element):
                self.assertIn('id="%s"' % element, page)
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("perform('model_fallback', { model_fallback: consent }", script)
        self.assertIn("decision.falls_back_at", script)


if __name__ == "__main__":
    unittest.main()
