"""Hold only Fable launches while Fable's weekly window is spent (ticket 54; Implementation Decision 15).

The conductor is driven with the fake launcher over the one-ticket project grown by tickets on
Fable (difficulty 4), Opus (difficulty 3), and Sonnet (difficulty 1 and 2), with a clock the test
moves across a reset, and by replaying journals that already hold the hold. What is asserted is
what the owner and the next process see: the journal, the ticket statuses, the calls the launcher
received with each call's kind and model, and `wayline status`.
"""

import io
import json
import os
import time
from datetime import datetime, timezone

from tests.projects import LADDER, ProjectTestCase, on_fable
from tests.test_conductor import done, drive, patch, run_verb
from tests.test_pacing import HOUR, REFUSED_TEXT, PacingCase, output
from tests.test_verdicts import passing
from tests.test_worker import SCHEMA, make_request
from wayline import dashboard, gates, pacing, replay, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.project import render_status, set_model_fallback, status_view
from wayline.worker import Envelope

# The `error` of the failed `task_updated` a Fable subagent's refusal leaves in its parent's stream.
FABLE_TASK = ("Agent terminated early due to an API error: " + REFUSED_TEXT
              + " (error type rate_limit, HTTP 429, model sent to the API: claude-fable-5-1)")


def journal_ts(seconds):
    """A journal timestamp at an epoch second, spelled as the ledger writes one."""
    return pacing.iso(seconds).replace("Z", ".000Z")


def usage_text(now, fable, hours=72):
    """`/usage` as the CLI prints it, both weeks resetting `hours` after `now`: the text, and that reset."""
    reset = datetime.fromtimestamp(now + hours * HOUR, timezone.utc).replace(minute=0, second=0, microsecond=0)
    prose = "%s %d, %d%s (UTC)" % (reset.strftime("%b"), reset.day, reset.hour % 12 or 12, "am" if reset.hour < 12 else "pm")
    return ("Current session: 24%% used · resets 3:45pm (UTC)\n"
            "Current week (all models): 71%% used · resets %s\n"
            "Current week (Fable): %d%% used · resets %s\n" % (prose, fable, prose)), int(reset.timestamp())


def rejected_on_fable(resets):
    """The rejected `rate_limit_event` a Fable request's own stream carries once Fable's weekly window is spent."""
    return worker.RateLimitEvent("rejected", resets, "seven_day_overage_included", None,
                                 worker.Window(0.64, resets), worker.Window(1.0, resets))


def allowed_on_fable(utilization, resets):
    """An allowed `rate_limit_event` of a Fable request, carrying Fable's weekly window at `utilization`."""
    return worker.RateLimitEvent("allowed", None, "seven_day_overage_included", None,
                                 worker.Window(0.64, resets), worker.Window(utilization, resets))


def refused(**fields):
    """A Fable session refused before its first turn, as the recorded one came back: 429, the text, exit 1."""
    values = dict(api_error_status=429, is_error=True, subtype="success", exit_code=1, num_turns=1, result_text=REFUSED_TEXT)
    values.update(fields)
    return Envelope(**values)


class HoldCase(PacingCase):
    """The pacing project, with blockers, waves that settle, and the journal read as the hold.

    Its `harness.json` puts the Fable rungs back (`SEVEN_RUNGS`), so difficulty 4 and 5 launch on Fable as they
    did before ticket 70, and the hold has Fable tickets to hold.
    """

    def setUp(self):
        super().setUp()
        on_fable(self.project, LADDER)
        # Committed, as an owner commits it, so `wayline run` finds nothing outside `research/` to refuse.
        self.git("add", "harness.json")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "harness: the Fable rungs back")

    def add(self, identifier, difficulty=1, blocked_by=()):
        super().add(identifier, difficulty)
        if blocked_by:
            fields = {item["id"]: item for item in tickets.read_tickets(self.project)}[identifier]
            _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))
            tickets.write_ticket(self.ledger, dict(fields, blocked_by=list(blocked_by)), body)

    def take(self, driven, count):
        """`count` waves, each settling the sessions it started before the next; every wave's result."""
        results = []
        for _ in range(count):
            results.append(driven.wave())
            driven.settle()
        return results

    def statuses(self):
        """Every ticket's status but the ask's: a project that never recorded a consent is asked once the hold drops a launch.

        The ask is ticket 57's, and `tests.test_fable_ask` asserts it; what these tests assert is the hold.
        """
        asks = {ticket["id"] for ticket in tickets.read_tickets(self.project) if pacing.ask_window(ticket.get("origin")) is not None}
        return {identifier: status for identifier, status in super().statuses().items() if identifier not in asks}

    def holds(self):
        return [item["payload"] for item in self.events("paused") if item["payload"].get("model") == "fable"]

    def pauses(self):
        return [item["payload"] for item in self.events("paused") if "model" not in item["payload"]]

    def kinds(self, identifier):
        return [call.kind for call in self.fake.calls if call.request.env.get("WAYLINE_TICKET") == str(identifier)]

    def verifier_calls(self):
        return [call for call in self.fake.calls if call.request.role == "verifier"]

    def index(self, name, **payload):
        """Where the first `name` event whose payload carries `payload` stands in the journal."""
        for number, item in enumerate(self.events()):
            if item["event"] == name and all(item["payload"].get(key) == value for key, value in payload.items()):
                return number
        self.fail("no %s event carrying %s in %s" % (name, payload, self.sequence()))

    def hold_journaled(self, hours):
        """A hold on Fable's weekly window journaled an hour ago, resetting `hours` from now."""
        self.ledger.append_event("paused", {"resets_at": pacing.iso(self.now[0] + hours * HOUR), "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"}, ts=journal_ts(self.now[0] - HOUR))


class RefusalHoldTest(HoldCase):
    """Criteria 2 to 5: each form of a Fable refusal holds only Fable launches, and the reset lifts the hold."""

    def setUp(self):
        super().setUp()
        on_fable(self.project, "verifier.opus")  # work written on Opus is read on Fable, which a refusal holds

    def test_a_refused_fable_ticket_holds_only_fable_launches_is_relaunched_never_resumed_and_the_reset_lifts_the_hold(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=4)
        self.add(3, difficulty=3)
        driven = self.conductor()
        resets = int(self.now[0]) + HOUR
        self.script(1, rejected_on_fable(resets), envelope=refused())
        self.script(1)
        self.script(2)
        self.script(3)
        for _ in range(3):
            self.fake.script(passing(), role="verifier")
        first, carried, closed = self.take(driven, 3)
        self.assertEqual(first.launched, [1])
        self.assertEqual(self.holds(), [{"resets_at": pacing.iso(resets), "window": "seven_day", "utilization": 1.0, "model": "fable"}])
        self.assertEqual(self.pauses(), [], "a refusal on Fable's weekly window pauses nothing")
        self.assertEqual((carried.launched, closed.done), ([3], [3]), "the Opus ticket took the slot, the other Fable ticket did not")
        self.assertEqual(self.statuses(), {1: "running", 2: "open", 3: "done"})
        self.assertEqual(self.verifier_calls(), [], "ticket 3's diff verdict runs on Fable, so it stays queued")
        self.assertIn("wait for a verdict on Fable", driven.out.getvalue())
        self.assertEqual(self.kinds(1), ["launch"], "the relaunch waits for the reset")

        self.now[0] = resets
        drive(driven)
        unheld = self.index("unpaused", model="fable")
        before = [item for item in self.events()[:unheld] if item["event"] in ("ticket_launched", "verdict")]
        self.assertEqual([(item["event"], item["payload"].get("ticket")) for item in before],
                         [("ticket_launched", 1), ("ticket_launched", 3)])
        self.assertEqual(self.kinds(1), ["launch", "launch"], "refused before its first turn: relaunched, never resumed")
        relaunch = self.payload("ticket_resumed")
        self.assertEqual((relaunch["reason"], relaunch["session_id"]), ("worker_died", None))
        self.assertEqual([call.request.model for call in self.verifier_calls()].count("fable"), 1)
        self.assertEqual(self.statuses(), {1: "accepted", 2: "accepted", 3: "accepted"})
        kept = self.project / "research" / "sessions" / "1" / "1" / "refused-1" / "stream.jsonl"
        self.assertIn("reached your Fable limit", kept.read_text(encoding="utf-8"), "the refused stream is kept beside its relaunch")
        self.assertEqual(driven.out.getvalue().count("wait for a verdict on Fable"), 1, "said once, not at every wave of the hold")

    def hold_on(self, envelope):
        """Ticket 1 on Fable comes back as `envelope`, and ticket 2 on Sonnet takes the slot it leaves."""
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        driven = self.conductor()
        self.script(1, envelope=envelope)
        self.script(2)
        first, carried = self.take(driven, 2)
        self.assertEqual((first.launched, carried.launched), ([1], [2]))
        (hold,) = self.holds()
        self.assertEqual((hold["window"], hold["utilization"], hold["model"]), ("seven_day", 1.0, "fable"))
        self.assertEqual(pacing.epoch(hold["resets_at"]), self.now[0] + 5 * HOUR, "no reset said and none known: five hours")
        self.assertEqual(self.pauses(), [])
        self.assertEqual(self.kinds(1), ["launch"])

    def test_a_429_alone_on_a_fable_launch_holds_fable(self):
        self.hold_on(Envelope(api_error_status=429, is_error=True, exit_code=1))

    def test_the_reached_your_fable_limit_text_alone_holds_fable(self):
        self.hold_on(Envelope(is_error=True, exit_code=1, result_text=REFUSED_TEXT))

    def test_a_subagent_refused_inside_an_allowed_session_holds_fable_while_the_session_is_carried(self):
        self.add(1, difficulty=2)
        self.add(2, difficulty=4, blocked_by=[1])
        self.add(3, difficulty=1)
        driven = self.conductor()
        parent = done(ticket_id=1, outputs_written=["hello.txt"])
        parent.answered, parent.failed_tasks = True, [{"task_id": "a0f0f0f0f0f0f0f71", "error": FABLE_TASK}]
        self.fake.script(parent, patch=patch(), ticket=1)
        self.script(3)
        first, carried, closed = self.take(driven, 3)
        self.assertEqual((first.launched, carried.done, carried.launched, closed.done), ([1], [1], [3], [3]))
        (hold,) = self.holds()
        self.assertEqual((hold["window"], hold["model"]), ("seven_day", "fable"))
        self.assertIn("(subagent)", driven.out.getvalue())
        self.assertEqual(self.events("ticket_resumed"), [], "the parent's own result was a success")
        self.assertEqual(self.statuses(), {1: "done", 2: "open", 3: "done"},
                         "ticket 2 reached the frontier on Fable, and the hold keeps it back")

    def test_a_fable_session_stopped_mid_work_waits_and_is_resumed_on_fable_after_the_reset(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        driven = self.conductor()
        resets = int(self.now[0]) + 1800
        self.script(1, rejected_on_fable(resets), envelope=refused(answered=True, num_turns=12))
        self.script(1)
        self.script(2)
        self.fake.script(passing(), role="verifier")
        first, carried, closed = self.take(driven, 3)
        self.assertEqual((first.launched, carried.launched, closed.done), ([1], [2], [2]))
        self.assertEqual(self.kinds(1), ["launch"], "the resume waits for the hold")
        self.now[0] = resets
        drive(driven)
        self.assertEqual(self.kinds(1), ["launch", "resume"])
        (resume,) = [call for call in self.fake.calls if call.kind == "resume"]
        self.assertEqual(resume.request.model, "fable")
        self.assertIn("usage limit", resume.message)
        self.assertLess(self.index("unpaused", model="fable"), self.index("ticket_resumed"))
        self.assertEqual(self.statuses(), {1: "accepted", 2: "done"})

    def test_a_refusal_reporting_fable_under_stop_at_holds_until_the_reset_all_the_same(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["pacing"] = {"stop_at": 1.0, "cheap_at": 0.99}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        driven = self.conductor()
        resets = int(self.now[0]) + HOUR
        spent = worker.RateLimitEvent("rejected", resets, "seven_day_overage_included", None,
                                      worker.Window(0.64, resets), worker.Window(0.98, resets))
        self.script(1, spent, envelope=refused())
        self.script(2)
        self.take(driven, 4)
        self.assertEqual((len(self.holds()), self.events("unpaused")), (1, []), "its own 0.98 does not end the hold it began")
        self.assertEqual(self.kinds(1), ["launch"])

    def test_an_allowed_fable_reading_in_a_running_stream_does_not_end_the_hold(self):
        """A stream does not say when it wrote an event: the allowed one may be older than the refusal."""
        self.add(1, difficulty=4)
        self.add(2, difficulty=4)
        driven = self.conductor(workers=2)
        resets = int(self.now[0]) + 3 * HOUR
        self.script(1, rejected_on_fable(resets), envelope=refused())
        self.script(2, allowed_on_fable(0.89, resets), delay=600)
        self.assertEqual(sorted(driven.wave().launched), [1, 2])
        driven.flight[1].thread.join(30)
        driven.wave()
        self.assertEqual((len(self.holds()), self.events("unpaused")), (1, []))
        self.assertEqual(self.kinds(1), ["launch"], "held, so not relaunched into the spent week")


class ReplayedHoldTest(HoldCase):
    """Criteria 3 and 4 by journal replay: the hold outlives a restart, and a whole-run pause starts and ends inside it."""

    def test_a_whole_run_pause_starts_and_ends_inside_the_hold(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        self.hold_journaled(10)
        self.ledger.append_event("paused", {"resets_at": pacing.iso(self.now[0] + HOUR), "window": "five_hour", "utilization": 1.0},
                                 ts=journal_ts(self.now[0]))
        driven = self.conductor()
        self.script(1)
        self.script(2)
        self.fake.script(passing(), role="verifier")
        self.assertEqual(driven.wave().launched, [], "the whole run is paused")
        self.now[0] += HOUR
        self.assertEqual(driven.wave().launched, [2], "the pause ended inside the hold, which still keeps the Fable ticket back")
        driven.settle()
        driven.wave()
        view = replay.replay(self.events())
        self.assertIsNone(view.pause)
        self.assertEqual(view.hold["resets_at"], pacing.iso(self.now[0] + 9 * HOUR), "the hold still stands")
        self.now[0] += 9 * HOUR
        self.assertEqual(driven.wave().launched, [1])
        order = [self.index("unpaused"), self.index("ticket_launched", ticket=2),
                 self.index("unpaused", model="fable"), self.index("ticket_launched", ticket=1)]
        self.assertEqual(order, sorted(order))
        drive(driven)
        self.assertEqual(self.statuses(), {1: "accepted", 2: "done"})

    def test_a_restart_rebuilds_the_hold_and_an_older_reading_under_stop_at_does_not_end_it(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        self.ledger.append_event("pacing", {"five_hour": 0.2, "seven_day": 0.6, "fable": 0.43, "action": "normal"},
                                 ts=journal_ts(self.now[0] - 2 * HOUR))
        self.hold_journaled(10)
        driven = self.conductor()
        self.script(2)
        self.assertEqual(driven.wave().launched, [2])
        self.assertEqual(self.events("unpaused"), [])
        once, twice = replay.replay(self.events()), replay.replay(self.events())
        self.assertEqual(once, twice, "replaying twice yields the same view")
        self.assertEqual(once.hold, {"resets_at": pacing.iso(self.now[0] + 10 * HOUR), "window": "seven_day", "utilization": 1.0})

    def test_a_usage_reading_under_stop_at_at_run_start_ends_a_replayed_hold_before_the_reset(self):
        self.add(1, difficulty=4)
        self.hold_journaled(10)
        driven = self.conductor()
        self.fake.usage_text, _ = usage_text(self.now[0], fable=43)
        self.script(1)
        waves = driven.run(wait=lambda seconds: driven.settle(), max_waves=1)
        self.assertEqual(waves[0].launched, [1])
        self.assertEqual(self.events("unpaused")[0]["payload"], {"model": "fable"})
        self.assertLess(self.index("unpaused", model="fable"), self.index("ticket_launched"))

    def test_a_restart_past_the_reset_carrying_a_refusal_that_named_no_reset_does_not_hold_fable_again(self):
        self.add(1, difficulty=4)
        first = self.conductor()
        self.script(1, envelope=refused(result_text=None))
        self.assertEqual(first.wave().launched, [1])
        first.settle()  # the worker returned, and its conductor died before it carried the result
        stream = self.project / "research" / "sessions" / "1" / "1" / "stream.jsonl"
        os.utime(stream, (self.now[0] - 8 * 24 * HOUR,) * 2)
        self.fake.usage_text, _ = usage_text(self.now[0], fable=10, hours=6 * 24)
        self.script(1)
        self.fake.script(passing(), role="verifier")
        again = Conductor(self.project, out=io.StringIO())
        again.clock = lambda: self.now[0]
        self.addCleanup(again.settle, 30)
        again.run(resume=True, wait=lambda seconds: again.settle(), max_waves=4)
        self.assertEqual(self.holds(), [], "the 10% read since says the week reset after that refusal")
        self.assertEqual(self.kinds(1), ["launch", "launch"])
        self.assertEqual(self.statuses(), {1: "accepted"})


class UsageBeforeFableWaveTest(HoldCase):
    """Criteria 1 and 3: `/usage` is read before a wave launches Fable work; Fable at `stop_at` holds it, `cheap_at` never."""

    def test_fable_at_stop_at_read_before_the_wave_holds_the_launch_and_a_later_reading_under_it_ends_the_hold(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        driven = self.conductor()
        self.fake.usage_text, resets = usage_text(self.now[0], fable=100)
        self.script(1)
        self.script(2)
        self.fake.script(passing(), role="verifier")
        self.assertEqual(driven.wave().launched, [2], "the slot went to the Sonnet ticket")
        self.assertEqual(self.payload("pacing"), {"five_hour": 0.24, "seven_day": 0.71, "fable": 1.0,
                                                  "action": "normal", "fable_action": "stop"})
        self.assertEqual(self.holds(), [{"resets_at": pacing.iso(resets), "window": "seven_day", "utilization": 1.0, "model": "fable"}])
        self.assertLess(self.index("paused", model="fable"), self.index("ticket_launched"))
        driven.settle()
        driven.wave()
        self.now[0] += 60
        self.fake.usage_text, _ = usage_text(self.now[0], fable=43)
        # The tick's reading, journaled by another process.
        self.ledger.append_event("pacing", {"five_hour": 0.24, "seven_day": 0.71, "fable": 0.43, "action": "normal"},
                                 ts=journal_ts(self.now[0]))
        self.assertEqual(driven.wave().launched, [1], "a reading under stop_at ended the hold before its reset")
        self.assertEqual(self.events("unpaused")[-1]["payload"], {"model": "fable"})
        drive(driven)
        self.assertEqual(self.statuses(), {1: "accepted", 2: "done"})

    def test_cheap_at_never_applies_to_fable_s_weekly_window(self):
        self.add(1, difficulty=4)
        driven = self.conductor()
        self.fake.usage_text, _ = usage_text(self.now[0], fable=85)
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        self.assertEqual((self.events("paused"), driven.action, self.payload("pacing")["fable"]), ([], "normal", 0.85))

    def test_a_usage_reading_before_a_fable_wave_that_says_stop_launches_nothing_at_all(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=3)
        driven = self.conductor(workers=2)
        text, _ = usage_text(self.now[0], fable=43)
        self.fake.usage_text = text.replace("Current session: 24%", "Current session: 95%")
        self.assertEqual(driven.wave().launched, [], "the picks made before the reading are not launched into a full window")
        self.assertEqual((driven.action, self.events("ticket_launched"), self.holds()), ("stop", [], []))


class RefusedVerdictTest(HoldCase):
    """Criterion 5 on the gates: a refused verdict is no verdict, is never resumed, and is launched again fresh."""

    def setUp(self):
        super().setUp()
        on_fable(self.project, "verifier.opus")  # work written on Opus is read on Fable, which refuses

    def test_take_verdict_raises_usage_limited_instead_of_resuming_a_refused_session(self):
        self.conductor()
        self.fake.script(refused(), role="verifier")
        with self.assertRaises(gates.UsageLimited) as caught:
            gates.verdict("ticket", "research/tickets/01-write-the-hello-file.md", "Does hello.txt hold one line?",
                          ["hello.txt"], "Only hello.txt.", project=self.project, author_model="opus",
                          verdict_type="quality", ticket=1)
        self.assertEqual((caught.exception.limit.model, caught.exception.limit.window), ("fable", "seven_day"))
        self.assertIn("Fable's weekly window", str(caught.exception))
        self.assertEqual([(call.kind, call.request.model) for call in self.fake.calls], [("launch", "fable")])
        self.assertEqual(self.events("verdict"), [])

    def test_a_refused_verdict_stays_queued_keeps_the_run_open_and_is_launched_again_after_the_reset(self):
        self.add(1, difficulty=3)
        driven = self.conductor()
        self.script(1)
        self.fake.script(refused(), role="verifier")
        self.fake.script(passing(), role="verifier")
        waves = self.take(driven, 4)
        (hold,) = self.holds()
        self.assertFalse(any(wave.ended for wave in waves), "a verdict the hold keeps queued keeps the run open for the reset")
        self.assertEqual((self.events("verdict"), self.events("run_ended"), self.statuses()), ([], [], {1: "done"}))
        self.assertIn("launched again, never resumed", driven.out.getvalue())
        self.now[0] = pacing.epoch(hold["resets_at"])
        last = drive(driven)[-1]
        self.assertEqual([(call.kind, call.request.model) for call in self.verifier_calls()], [("launch", "fable"), ("launch", "fable")])
        self.assertLess(self.index("unpaused", model="fable"), self.index("verdict"))
        self.assertEqual((self.statuses(), last.reason), ({1: "accepted"}, "frontier_empty"))


class HeardInAVerdictTest(HoldCase):
    """A refusal a verdict's own stream carries begins the hold, although the verdict answered (decision 15).

    A Fable refusal can hide inside a session that still returns its answer (a subagent's task, or the
    event `--simulate-limit fable:` writes ahead of the session). A worker's stream is folded as it is
    read; a verdict's is folded once the gate returns it, so the answer stands and the hold begins, and
    no later verdict of the same ticket launches on Fable past it. Found on the M5 overnight run, where
    the simulated refusal fell on a verdict and held nothing.
    """

    def setUp(self):
        super().setUp()
        on_fable(self.project, "verifier.opus")  # work written on Opus is read on Fable, whose refusal the verdict carries

    def verdicts_of(self, identifier):
        return [item["payload"] for item in self.events("verdict") if item["ticket"] == identifier]

    def run_until_the_first_verdict(self, consent):
        self.add(1, difficulty=3)  # an Opus author: every verdict it earns runs on Fable
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        acceptance = dict(fields["acceptance"], quality=["hello.txt greets the reader in one plain sentence."])
        tickets.write_ticket(self.ledger, dict(fields, acceptance=acceptance), body)  # a quality verdict, then the diff's
        if consent:
            set_model_fallback(self.project, consent)
        driven = self.conductor()
        self.resets = int(self.now[0]) + HOUR
        self.script(1)
        answered = passing()
        answered.rate_limit_events = [rejected_on_fable(self.resets)]
        self.fake.script(answered, role="verifier")
        self.fake.script(passing(), role="verifier")
        self.take(driven, 3)
        return driven

    def test_the_answer_stands_and_the_hold_begins_with_the_rest_of_the_ticket_s_verdicts_queued(self):
        driven = self.run_until_the_first_verdict(None)
        (hold,) = self.holds()
        self.assertEqual((hold["resets_at"], hold["window"]), (pacing.iso(self.resets), "seven_day"))
        self.assertEqual([item["pass"] for item in self.verdicts_of(1)], [True], "the verdict that answered is journaled")
        self.assertEqual([(call.kind, call.request.model) for call in self.verifier_calls()], [("launch", "fable")],
                         "the ticket's next verdict is not launched on Fable past the hold")
        self.assertEqual(self.statuses(), {1: "done"})
        self.assertIn("wait for a verdict on Fable", driven.out.getvalue())

    def test_under_auto_the_rest_of_the_ticket_s_verdicts_fall_back_to_opus(self):
        self.run_until_the_first_verdict("auto")
        self.assertEqual(len(self.holds()), 1)
        self.assertEqual([(call.kind, call.request.model) for call in self.verifier_calls()],
                         [("launch", "fable"), ("launch", "opus")])
        taken = self.verdicts_of(1)
        self.assertEqual([item.get("fallback_from") for item in taken], [None, "r7 fable high"])
        self.assertEqual(self.statuses(), {1: "accepted"})


class AnsweredRefusalTest(HoldCase):
    """Any session the conductor starts can carry a Fable refusal and still answer: the decider, the planner, the evolver.

    The launcher keeps the rejected events of every session that returned a usable answer, and the conductor
    folds them at its next wave, so a refusal is never spent on a session that had no stream of its own read
    (found on the M5 overnight run, where the simulated refusal fell on the evolver and held nothing).
    """

    def request(self, name):
        run_dir = self.temp / name
        run_dir.mkdir()
        # A session with no ticket: the decider's, say, whose stream the conductor does not read itself.
        return make_request(run_dir, schema_path=str(SCHEMA), env={"WAYLINE_PROJECT": str(self.project), "WAYLINE_RUN": str(run_dir)})

    def test_a_refusal_riding_an_answered_session_begins_the_hold_at_the_next_wave(self):
        self.add(1, difficulty=4)
        driven = self.conductor()
        resets = int(self.now[0]) + HOUR
        answered = Envelope(structured_output={"skill_token": "UNKNOWN", "report": "decided"})
        answered.rate_limit_events = [rejected_on_fable(resets)]
        self.fake.script(answered)
        self.assertTrue(worker.launch(self.request("decider")).valid)
        self.script(1)
        self.assertEqual(driven.wave().launched, [], "the Fable ticket is held by the refusal the decider's session carried")
        (hold,) = self.holds()
        self.assertEqual(hold["resets_at"], pacing.iso(resets))
        self.assertEqual(worker.take_answered_refusals(), [], "a refusal is folded once")

    def test_the_refusal_is_heard_whenever_the_conductor_asks_whether_it_may_launch(self):
        """The M5 run again: a decider's refusal, then a stall whose replan starts in the same wave, before any fold."""
        self.add(1, difficulty=4)
        driven = self.conductor()
        driven.wave()
        driven.settle()
        answered = Envelope(structured_output={"skill_token": "UNKNOWN", "report": "decided"})
        answered.rate_limit_events = [rejected_on_fable(int(self.now[0]) + HOUR)]
        self.fake.script(answered)
        worker.launch(self.request("decider"))
        self.assertTrue(driven._fable_held(), "the planner a stall launches next asks this before it starts")
        self.assertEqual(len(self.holds()), 1)

    def test_a_ticket_worker_s_refusal_is_left_to_the_stream_the_conductor_reads(self):
        """Heard twice, a refusal that names no reset would pause twice: `_observe` reads a worker's own stream."""
        answered = Envelope(structured_output={"skill_token": "UNKNOWN", "report": "done"})
        answered.rate_limit_events = [rejected_on_fable(int(self.now[0]) + HOUR)]
        with worker.use_fake() as fake:
            fake.script(answered)
            run_dir = self.temp / "ticket-worker"
            run_dir.mkdir()
            worker.launch(make_request(run_dir, schema_path=str(SCHEMA)))  # WAYLINE_TICKET is set: a ticket's worker
        self.assertEqual(worker.take_answered_refusals(), [])

    def test_a_refusal_left_by_another_run_is_not_this_run_s(self):
        answered = Envelope(structured_output={"skill_token": "UNKNOWN", "report": "decided"})
        with worker.use_fake() as fake:
            answered.rate_limit_events = [rejected_on_fable(int(self.now[0]) + HOUR)]
            fake.script(answered)
            worker.launch(self.request("decider"))
        self.add(1, difficulty=4)
        driven = self.conductor()
        self.script(1)
        self.assertEqual(driven.wave().launched, [1])
        self.assertEqual(self.holds(), [])


class SimulatedFableLimitTest(HoldCase):
    """Criterion 6: `wayline run --simulate-limit fable:<seconds>` holds Fable alone; `<seconds>` keeps its meaning."""

    def test_run_simulate_limit_fable_holds_only_fable_launches(self):
        self.add(1, difficulty=4)
        self.add(2, difficulty=1)
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch(), ticket=1)
            fake.script(done(ticket_id=2, outputs_written=[output(2)]), patch=patch({output(2): "hello\n"}, "ticket 2"), ticket=2)
            fake.script(passing(), role="verifier")
            before = time.time()
            code, out, err = run_verb(["--simulate-limit", "fable:3600", "--max-waves", "6", "--project", str(self.project)])
        self.assertEqual(code, 0, out + err)
        (hold,) = self.holds()
        self.assertGreaterEqual(pacing.epoch(hold["resets_at"]), int(before) + 3600)
        self.assertLessEqual(pacing.epoch(hold["resets_at"]), time.time() + 3601)
        self.assertEqual(self.pauses(), [])
        self.assertEqual(self.statuses(), {1: "accepted", 2: "done"}, "the Fable session the limit hit ran as it would have")
        self.assertIsNone(worker.simulated_limit())

    def test_a_real_reading_does_not_lift_the_simulated_hold_before_its_seconds_are_out(self):
        """The M5 overnight run: a live `/usage` read Fable at 7%, under `stop_at`, and ended the simulated hold at once.

        `--simulate-limit fable:<seconds>` exists to show Fable work held and falling back for that long, the way
        `cheap:<seconds>` shows the step down; a real reading ends the hold only once its reset has passed.
        """
        self.add(1, difficulty=4)
        self.add(2, difficulty=4)
        set_model_fallback(self.project, "auto")
        self.hold_journaled(1)
        driven = self.conductor()
        driven.simulate_fable_hold()
        self.fake.usage_text, _ = usage_text(self.now[0], fable=7)
        self.script(1)
        self.script(2)
        self.assertEqual(driven.wave().launched, [1])
        driven.settle()
        self.now[0] += 60
        # The tick's reading, journaled by another process: the one that ended the hold live.
        self.ledger.append_event("pacing", {"five_hour": 0.24, "seven_day": 0.71, "fable": 0.07, "action": "normal"},
                                 ts=journal_ts(self.now[0]))
        self.assertEqual(driven.wave().launched, [2], "the next wave hears the reading under stop_at, and still holds")
        launched = [item["payload"] for item in self.events("ticket_launched")]
        self.assertEqual([(item["model"], item.get("fallback_from")) for item in launched], [("opus", "r6 fable low")] * 2)
        self.assertEqual(self.events("unpaused"), [], "the simulated hold stands until its own reset")
        self.now[0] += 2 * HOUR
        driven.settle()
        driven.wave()
        self.assertEqual(self.events("unpaused")[-1]["payload"], {"model": "fable"})

    def test_a_simulated_limit_on_another_model_or_without_seconds_is_refused(self):
        for value in ("opus:60", "fable:-5", "fable:", "soon"):
            with self.subTest(value=value):
                code, _, err = run_verb(["--simulate-limit", value, "--project", str(self.project)])
                self.assertEqual(code, 2)
                self.assertIn("fable:<seconds>", err)


class FableStatusTest(ProjectTestCase):
    """Criterion 7: `wayline status` and the dashboard overview show `fable <N>` on the window line."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.ledger = Ledger(self.project)

    def test_the_window_line_and_the_overview_carry_fable_s_utilization_and_the_hold_pauses_nothing(self):
        self.ledger.append_event("pacing", {"five_hour": 0.2, "seven_day": 0.6, "fable": 1.0, "action": "normal"})
        self.ledger.append_event("paused", {"resets_at": "2026-09-16T02:00:00Z", "window": "seven_day",
                                            "utilization": 1.0, "model": "fable"})
        line = [line for line in render_status(status_view(self.project)).splitlines() if line.startswith("window")][0]
        for part in ("normal", "five_hour 0.2", "seven_day 0.6", "fable 1"):
            self.assertIn(part, line)
        self.assertNotIn("paused", line, "the hold on Fable's weekly window pauses nothing")
        self.assertEqual(dashboard.overview_view(self.project)["window"]["fable"], 1.0)
