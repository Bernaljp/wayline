"""Pacing and the pause on usage limits (ticket 10; Implementation Decisions 5, wave step 8, and 3).

The pure half (`wayline.pacing`) is tested on its own: the action a reading comes to, the
thresholds, the `/usage` text, the three signals of a hit limit, and when a pause ends. The
conductor half is tested through the fake launcher, whose envelopes carry `rate_limit_event`s at
any utilization or with `status: rejected`, and a clock the test moves across a reset, so that no
test sleeps. What is asserted is what the owner sees: the journal, the ticket statuses, the calls
the launcher received, and `wayline status`.
"""

import io
import json
import os
import time
import unittest
from datetime import datetime, timezone
from unittest import mock
from pathlib import Path
from zoneinfo import ZoneInfo

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, patch, run_verb
from tests.test_resume import ReadoptionCase, control
from tests.test_worker import SCHEMA, STREAMS, StandInMixin, make_request
from wayline import pacing, schedule, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.pacing import Limit, Windows
from wayline.project import render_status, status_view
from wayline.worker import Envelope, RateLimitEvent

# What `claude -p "/usage"` printed in research-notes/02, launch 4.
USAGE_TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 24% used · resets Sep 11, 10:10pm (Asia/Riyadh)
Current week (all models): 23% used · resets Sep 16, 5am (Asia/Riyadh)
Current week (Fable): 43% used · resets Sep 16, 5am (Asia/Riyadh)

What's contributing to your limits usage?
"""

RIYADH = ZoneInfo("Asia/Riyadh")
HOUR = 3600


def at(zone, *fields):
    return int(datetime(*fields, tzinfo=zone).timestamp())


def event(status="allowed", resets_at=None, kind="five_hour", five_hour=None, seven_day=None, five_reset=None, week_reset=None):
    """One `rate_limit_event` as a scripted envelope carries it; a window left None is absent from `unifiedWindows`."""
    return RateLimitEvent.from_dict({
        "status": status, "resets_at": resets_at, "rate_limit_type": kind,
        "five_hour": None if five_hour is None else {"utilization": five_hour, "resets_at": five_reset},
        "seven_day": None if seven_day is None else {"utilization": seven_day, "resets_at": week_reset},
    })


# --- the pure half -------------------------------------------------------------------------------


class ActionTest(unittest.TestCase):
    """Criterion 1: `stop` at or above `stop_at` on either window, `cheap_only` at or above `cheap_at`, else `normal`."""

    def test_either_window_at_0_79_0_81_and_0_91_comes_to_normal_cheap_only_and_stop(self):
        for window in ("five_hour", "seven_day"):
            for value, action in ((0.79, "normal"), (0.81, "cheap_only"), (0.91, "stop")):
                with self.subTest(window=window, value=value):
                    readings = {"five_hour": 0.1, "seven_day": 0.1, window: value}
                    self.assertEqual(pacing.action_for(readings["five_hour"], readings["seven_day"]), action)

    def test_the_thresholds_are_inclusive(self):
        self.assertEqual(pacing.action_for(0.90, None), "stop")
        self.assertEqual(pacing.action_for(None, 0.80), "cheap_only")

    def test_no_reading_at_all_is_normal(self):
        self.assertEqual(pacing.action_for(None, None), "normal")

    def test_later_layers_of_thresholds_win_and_a_mistyped_one_is_passed_over(self):
        self.assertEqual(pacing.thresholds(), (0.90, 0.80))
        self.assertEqual(pacing.thresholds({"stop_at": 0.95, "cheap_at": 0.85}, {"cheap_at": 0.7}), (0.95, 0.7))
        self.assertEqual(pacing.thresholds({"stop_at": 0.95}, {"stop_at": "high", "cheap_at": 3}), (0.95, 0.80))


class WindowsTest(unittest.TestCase):
    def test_a_reading_whose_window_has_reset_since_is_no_reading(self):
        windows = Windows()
        windows.record("five_hour", 1.0, resets_at=1000, observed_at=500)
        self.assertEqual(windows.utilization("five_hour", 999), 1.0)
        self.assertIsNone(windows.utilization("five_hour", 1000))

    def test_a_reading_that_names_no_reset_has_reset_once_it_is_older_than_its_window(self):
        windows = Windows()
        windows.record("five_hour", 0.95, observed_at=0)
        windows.record("seven_day", 0.95, observed_at=0)
        self.assertEqual(windows.utilization("five_hour", 5 * HOUR - 1), 0.95)
        self.assertIsNone(windows.utilization("five_hour", 5 * HOUR))
        self.assertEqual(windows.utilization("seven_day", 5 * HOUR), 0.95)
        self.assertIsNone(windows.utilization("seven_day", 7 * 24 * HOUR))

    def test_an_older_reading_does_not_replace_a_newer_one(self):
        windows = Windows()
        self.assertTrue(windows.record("seven_day", 0.5, observed_at=200))
        self.assertFalse(windows.record("seven_day", 0.2, observed_at=100))
        self.assertEqual(windows.utilization("seven_day", 0), 0.5)

    def test_a_rate_limit_event_without_unified_windows_carries_no_reading(self):
        windows = Windows()
        windows.observe(event(status="allowed_warning", resets_at=1789153800), 0)
        self.assertFalse(windows.known())
        windows.observe(event(five_hour=0.14, seven_day=0.21, five_reset=1789153800, week_reset=1789524000), 0)
        self.assertEqual((windows.utilization("five_hour", 0), windows.utilization("seven_day", 0)), (0.14, 0.21))

    def test_the_next_reset_is_the_named_window_s_then_either_window_s(self):
        windows = Windows()
        windows.record("five_hour", 0.5, resets_at=2000)
        windows.record("seven_day", 0.5, resets_at=9000)
        self.assertEqual(windows.next_reset(1000, "seven_day"), 9000)
        self.assertEqual(windows.next_reset(1000), 2000)
        self.assertEqual(windows.next_reset(5000, "five_hour"), 9000)
        self.assertIsNone(windows.next_reset(10000))


class UsageTest(unittest.TestCase):
    """Criterion 1: `/usage` parsed with the two regexes of decision 5."""

    def test_the_recorded_usage_text_reads_as_both_windows_and_their_resets(self):
        now = at(RIYADH, 2026, 9, 11, 18, 0)
        usage = pacing.parse_usage(USAGE_TEXT, now)
        self.assertEqual((usage.five_hour, usage.seven_day), (0.24, 0.23))
        self.assertEqual(usage.resets["five_hour"], at(RIYADH, 2026, 9, 11, 22, 10))
        self.assertEqual(usage.resets["seven_day"], at(RIYADH, 2026, 9, 16, 5, 0))

    def test_the_fable_week_is_read_as_fable_s_and_not_as_the_all_models_week(self):
        now = at(timezone.utc, 2026, 9, 11, 12, 0)
        usage = pacing.parse_usage("Current week (Fable): 43% used · resets Sep 16, 5am (UTC)", now)
        self.assertEqual((usage.five_hour, usage.seven_day, usage.fable), (None, None, 0.43))
        self.assertEqual(usage.resets, {"fable": at(timezone.utc, 2026, 9, 16, 5, 0)})

    def test_text_without_either_line_is_no_reading(self):
        self.assertIsNone(pacing.parse_usage("Unknown command: /usage", 0))
        self.assertIsNone(pacing.parse_usage(None, 0))


class ResetProseTest(unittest.TestCase):
    def test_a_bare_time_is_the_next_one(self):
        before = at(timezone.utc, 2026, 9, 11, 15, 0)
        after = at(timezone.utc, 2026, 9, 11, 16, 0)
        self.assertEqual(pacing.parse_reset("3:45pm", "UTC", before), at(timezone.utc, 2026, 9, 11, 15, 45))
        self.assertEqual(pacing.parse_reset("3:45pm", "UTC", after), at(timezone.utc, 2026, 9, 12, 15, 45))

    def test_a_weekday_is_the_next_such_day(self):
        friday = at(timezone.utc, 2026, 9, 11, 12, 0)
        self.assertEqual(pacing.parse_reset("Mon 12:00am", "UTC", friday), at(timezone.utc, 2026, 9, 14, 0, 0))

    def test_a_date_early_in_next_year_is_next_year_s(self):
        december = at(timezone.utc, 2026, 12, 30, 12, 0)
        self.assertEqual(pacing.parse_reset("Jan 2, 5am", "UTC", december), at(timezone.utc, 2027, 1, 2, 5, 0))

    def test_prose_that_is_not_a_time_is_none(self):
        for prose in ("soon", "25:00pm", "Foo 3, 5am", "Feb 30, 5am", ""):
            with self.subTest(prose=prose):
                self.assertIsNone(pacing.parse_reset(prose, "UTC", 0))


class HitLimitTest(unittest.TestCase):
    """Criterion 3: a hit limit is any of three signals, and the reset comes from the event or the message."""

    def test_a_rejected_event_is_a_hit_limit_with_its_reset_window_and_utilization(self):
        envelope = Envelope(rate_limit_events=[event(five_hour=0.5), event(status="rejected", resets_at=1789153800,
                                                                          five_hour=1.0, seven_day=0.61)])
        self.assertEqual(pacing.hit_limit(envelope), Limit("rate_limit_event", 1789153800, "five_hour", 1.0))

    def test_allowed_and_warning_events_are_not_a_hit_limit(self):
        envelope = Envelope(exit_code=0, rate_limit_events=[event(five_hour=0.95), event(status="allowed_warning")])
        self.assertIsNone(pacing.hit_limit(envelope))

    def test_a_429_result_is_a_hit_limit_whose_reset_is_read_from_its_message(self):
        now = at(timezone.utc, 2026, 9, 11, 12, 0)
        envelope = Envelope(api_error_status=429, errors=["You've hit your session limit · resets 3:45pm (UTC)"], exit_code=1)
        limit = pacing.hit_limit(envelope, now=now)
        self.assertEqual(limit, Limit("api_error_status", at(timezone.utc, 2026, 9, 11, 15, 45), "five_hour", None))

    def test_a_non_zero_exit_that_says_so_on_stderr_is_a_hit_limit(self):
        now = at(timezone.utc, 2026, 9, 11, 12, 0)
        limit = pacing.hit_limit(Envelope(exit_code=1), stderr="You've hit your weekly limit · resets Mon 12:00am (UTC)\n", now=now)
        self.assertEqual(limit, Limit("message", at(timezone.utc, 2026, 9, 14, 0, 0), "seven_day", None))

    def test_the_result_text_says_so_as_well(self):
        self.assertEqual(pacing.hit_limit(Envelope(exit_code=1, result_text="You've hit your limit")).signal, "message")

    def test_the_words_on_a_clean_exit_are_not_a_hit_limit(self):
        self.assertIsNone(pacing.hit_limit(Envelope(exit_code=0, result_text="the test asserts we hit your rate limit")))

    def test_the_pause_ends_at_the_signal_s_reset_else_the_next_known_window_reset_else_in_five_hours(self):
        windows = Windows()
        self.assertEqual(pacing.resets_at(Limit("message", 7000), windows, 1000), 7000)
        self.assertEqual(pacing.resets_at(Limit("message"), windows, 1000), 1000 + 5 * HOUR)
        windows.record("seven_day", 0.99, resets_at=9000)
        self.assertEqual(pacing.resets_at(Limit("api_error_status", window="seven_day"), windows, 1000), 9000)


# What `claude -p "/usage"` printed while Fable's weekly window was spent (the Fable research note, question 3).
USAGE_FABLE_SPENT = """Current session: 24% used · resets Sep 13, 1:20pm (Asia/Riyadh)
Current week (all models): 71% used · resets Sep 16, 5am (Asia/Riyadh)
Current week (Fable): 100% used · resets Sep 16, 5am (Asia/Riyadh)
"""

REFUSED_TEXT = ("You've reached your Fable limit. Switch to another model, or manage usage credits at "
                "claude.ai/settings/usage?from=cc_cli_limit_message, to continue.")


def fable_event(status="rejected", utilization=1.0, resets_at=1789524000):
    """A `rate_limit_event` of Fable's weekly window, as only a Fable request's own event carries it."""
    return RateLimitEvent.from_dict({
        "status": status, "resets_at": resets_at if status == "rejected" else None, "rate_limit_type": "seven_day_overage_included",
        "five_hour": {"utilization": 0.16, "resets_at": 1789255200}, "seven_day": {"utilization": 0.64, "resets_at": 1789524000},
        "seven_day_overage_included": {"utilization": utilization, "resets_at": resets_at},
    })


class FableWindowTest(unittest.TestCase):
    """Ticket 54, criteria 1 and 2 (decision 15): Fable's weekly window read, and a Fable refusal in each of its forms."""

    def test_the_fable_line_of_usage_reads_beside_the_two_windows_with_its_reset(self):
        now = at(RIYADH, 2026, 9, 13, 12, 0)
        usage = pacing.parse_usage(USAGE_FABLE_SPENT, now)
        self.assertEqual((usage.five_hour, usage.seven_day, usage.fable), (0.24, 0.71, 1.0))
        self.assertEqual(usage.resets["fable"], at(RIYADH, 2026, 9, 16, 5, 0))
        self.assertEqual(usage.resets["fable"], usage.resets["seven_day"], "the two weeks reset together on this account")

    def test_only_the_fable_block_of_a_rate_limit_event_is_read_as_fable_s_window(self):
        windows = Windows()
        windows.observe(event(five_hour=0.2, seven_day=0.64, five_reset=2000, week_reset=9000), 0)
        self.assertIsNone(windows.utilization("fable", 0), "other models' events never carry Fable's window")
        windows.observe(fable_event(status="allowed", utilization=0.93, resets_at=9000), 0)
        self.assertEqual((windows.utilization("fable", 0), windows.utilization("seven_day", 0)), (0.93, 0.64))
        self.assertIsNone(windows.utilization("fable", 9000))

    def test_the_recorded_refusal_is_a_fable_refusal_by_its_rejected_event(self):
        envelope = worker.read_envelope(STREAMS / "note-fable-refused.jsonl", None, exit_code=1)
        self.assertEqual((envelope.api_error_status, envelope.is_error, envelope.subtype, envelope.num_turns), (429, True, "success", 1))
        self.assertEqual(pacing.hit_limit(envelope, model="fable"), Limit("rate_limit_event", 1789524000, "seven_day", 1.0, "fable"))
        self.assertFalse(envelope.answered, "refused before its first turn: the one assistant message is the synthetic refusal")

    def test_its_429_alone_is_a_fable_refusal_on_a_fable_launch(self):
        envelope = worker.read_envelope(STREAMS / "note-fable-refused.jsonl", None, exit_code=1)
        envelope.rate_limit_events, envelope.result_text = [], None
        self.assertEqual(pacing.hit_limit(envelope, model="fable"), Limit("api_error_status", None, "seven_day", None, "fable"))
        self.assertEqual(pacing.hit_limit(envelope, model="opus"), Limit("api_error_status", None, "unknown", None, None),
                         "a 429 that names no window on another model's launch is the whole run's")

    def test_the_text_signal_matches_reached_your_as_well_as_hit_your(self):
        refused = pacing.hit_limit(Envelope(exit_code=1, result_text=REFUSED_TEXT))
        self.assertEqual(refused, Limit("message", None, "seven_day", None, "fable"), "the text names Fable, whatever the launch was on")
        self.assertEqual(pacing.hit_limit(Envelope(exit_code=1, result_text="You've reached your weekly limit")),
                         Limit("message", None, "seven_day", None, None))
        self.assertIsNone(pacing.hit_limit(Envelope(exit_code=0, result_text=REFUSED_TEXT)), "a clean exit is not a refusal")

    def test_a_session_limit_on_a_fable_launch_is_still_the_whole_run_s(self):
        now = at(timezone.utc, 2026, 9, 11, 12, 0)
        envelope = Envelope(api_error_status=429, exit_code=1, errors=["You've hit your session limit · resets 3:45pm (UTC)"])
        self.assertEqual(pacing.hit_limit(envelope, now=now, model="fable"),
                         Limit("api_error_status", at(timezone.utc, 2026, 9, 11, 15, 45), "five_hour", None, None))
        rejected = Envelope(exit_code=1, rate_limit_events=[event(status="rejected", resets_at=1789153800, five_hour=1.0)])
        self.assertIsNone(pacing.hit_limit(rejected, model="fable").model)

    def test_a_subagent_s_failed_task_is_a_fable_refusal_while_its_parent_s_result_stays_a_success(self):
        envelope = worker.read_envelope(STREAMS / "note-fable-subagent-refused.jsonl", None, exit_code=0)
        self.assertEqual((envelope.is_error, envelope.subtype, envelope.api_error_status), (False, "success", None))
        self.assertTrue(envelope.answered)
        self.assertEqual(len(envelope.failed_tasks), 1)
        self.assertIn("claude-fable-5-1", envelope.failed_tasks[0]["error"])
        self.assertEqual(pacing.hit_limit(envelope, model="haiku").model, "fable", "the rejected event in the parent's stream says so")
        envelope.rate_limit_events = []
        self.assertEqual(pacing.hit_limit(envelope, model="haiku"), Limit("subagent", None, "seven_day", None, "fable"))

    def test_a_failed_task_fable_did_not_refuse_is_no_limit(self):
        for error in ("Agent terminated early: the tool failed",
                      "Agent terminated early due to an API error (error type rate_limit, HTTP 429, model sent to the API: claude-opus-5)"):
            with self.subTest(error=error):
                envelope = Envelope(exit_code=0, failed_tasks=[{"task_id": "t1", "error": error}])
                self.assertIsNone(pacing.hit_limit(envelope, model="haiku"), "a subagent on another model met a limit of its own")

    def test_only_the_line_that_says_a_limit_was_hit_decides_the_window(self):
        now = at(timezone.utc, 2026, 9, 11, 12, 0)
        stderr = "debug: model sent to the API: claude-fable-5-1\nYou've hit your session limit · resets 3:45pm (UTC)\n"
        self.assertEqual(pacing.hit_limit(Envelope(exit_code=1), stderr=stderr, now=now, model="fable"),
                         Limit("message", at(timezone.utc, 2026, 9, 11, 15, 45), "five_hour", None, None))

    def test_a_worker_that_took_turns_answered_and_a_synthetic_refusal_did_not(self):
        self.assertTrue(worker.read_envelope(STREAMS / "note01-launch2-success.jsonl", None, exit_code=0).answered)
        self.assertTrue(worker.read_envelope(STREAMS / "synth-killed.jsonl", None, exit_code=143).answered)
        self.assertFalse(worker.read_envelope(STREAMS / "synth-rejected-429.jsonl", None, exit_code=1).answered)

    def test_a_fable_refusal_resets_at_its_signal_else_fable_s_reading_else_the_week_s_never_the_five_hour(self):
        refusal = Limit("message", None, "seven_day", None, "fable")
        windows = Windows()
        windows.record("five_hour", 0.3, resets_at=2000)
        self.assertEqual(pacing.resets_at(refusal, windows, 1000), 1000 + 5 * HOUR)
        windows.record("seven_day", 0.7, resets_at=8000)
        self.assertEqual(pacing.resets_at(refusal, windows, 1000), 8000)
        windows.record("fable", 1.0, resets_at=9000)
        self.assertEqual(pacing.resets_at(refusal, windows, 1000), 9000)
        self.assertEqual(pacing.resets_at(Limit("rate_limit_event", 7000, "seven_day", 1.0, "fable"), windows, 1000), 7000)

    def test_the_hold_s_paused_payload_names_the_model_and_the_week(self):
        windows = Windows()
        windows.record("fable", 1.0, resets_at=9000)
        self.assertEqual(pacing.paused_payload(Limit("api_error_status", None, "seven_day", None, "fable"), 9000, windows),
                         {"resets_at": pacing.iso(9000), "window": "seven_day", "utilization": 1.0, "model": "fable"})
        self.assertNotIn("model", pacing.paused_payload(Limit("message", None, "five_hour"), 9000, windows))


# --- the launcher ------------------------------------------------------------------------------


class SimulatedLimitFakeTest(ProjectTestCase):
    """Criterion 4: `--simulate-limit <seconds>` makes the next launch carry one rejected event, and only that one."""

    def setUp(self):
        super().setUp()
        self.addCleanup(worker.simulate_limit, None)

    def launch(self, fake, name):
        run_dir = self.temp / name
        run_dir.mkdir()
        fake.script(Envelope(structured_output={"ok": True}))
        return worker.launch(make_request(run_dir, schema_path=str(SCHEMA)))

    def test_the_next_launch_carries_one_rejected_event_that_many_seconds_ahead(self):
        with worker.use_fake() as fake:
            worker.simulate_limit(30)
            before = time.time()
            first = self.launch(fake, "first")
            second = self.launch(fake, "second")
        rejected = [item for item in first.rate_limit_events if item.status == "rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertGreaterEqual(rejected[0].resets_at, int(before) + 30)
        self.assertLessEqual(rejected[0].resets_at, int(time.time()) + 31)
        self.assertEqual(second.rate_limit_events, [], "one launch, not every launch")

    def test_a_fable_limit_waits_for_the_next_fable_launch_and_rejects_fable_s_weekly_window(self):
        with worker.use_fake() as fake:
            worker.simulate_limit(30, model="fable")
            before = time.time()
            opus = self.launch(fake, "opus")
            fake.script(Envelope(structured_output={"ok": True}))
            (self.temp / "fable").mkdir()
            fable = worker.launch(make_request(self.temp / "fable", schema_path=str(SCHEMA), model="fable"))
        self.assertEqual(opus.rate_limit_events, [], "a launch on another model does not take it")
        (rejected,) = fable.rate_limit_events
        self.assertEqual((rejected.status, rejected.rate_limit_type), ("rejected", "seven_day_overage_included"))
        self.assertGreaterEqual(rejected.resets_at, int(before) + 30)
        self.assertEqual(rejected.seven_day_overage_included.utilization, 1.0)
        self.assertEqual(pacing.hit_limit(fable, model="fable").model, "fable")
        self.assertIsNone(worker.simulated_limit())

    def test_a_launch_that_defines_an_agent_on_fable_is_a_fable_launch(self):
        agents = {"coder": {"description": "a coder", "prompt": "You code.", "model": "haiku", "effort": "low"},
                  "probe": {"description": "probe", "prompt": "Reply ok", "model": "fable", "effort": "low"}}
        self.assertTrue(worker.launches_on(make_request(self.temp, model="haiku", agent_json=agents), "fable"))
        self.assertTrue(worker.launches_on(make_request(self.temp, model="haiku", agent_json=json.dumps(agents)), "fable"))
        self.assertFalse(worker.launches_on(make_request(self.temp, model="opus"), "fable"))


class LauncherCliTest(StandInMixin, unittest.TestCase):
    """The real backend: the injected event lands in the stream, and `/usage` is one plain `claude -p`."""

    def tearDown(self):
        worker.simulate_limit(None)

    def test_the_injected_event_is_in_the_stream_the_session_wrote(self):
        worker.simulate_limit(60)
        envelope = worker.launch(self.request())
        lines = [json.loads(line) for line in (self.run / "stream.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((lines[0]["type"], lines[0]["rate_limit_info"]["status"]), ("rate_limit_event", "rejected"))
        self.assertEqual([item.status for item in envelope.rate_limit_events], ["rejected", "allowed", "allowed"])
        self.assertEqual(envelope.subtype, "success", "the session itself ran as it would have")

    def test_usage_runs_the_local_command_and_returns_its_text(self):
        reply = self.root / "usage.jsonl"
        reply.write_text(json.dumps({"type": "result", "subtype": "success", "num_turns": 0, "result": USAGE_TEXT}) + "\n", encoding="utf-8")
        os.environ["FAKE_CLAUDE_STREAM"] = str(reply)
        self.assertEqual(worker.usage(), USAGE_TEXT)
        self.assertEqual(self.recorded()["argv"], ["-p", "/usage", "--output-format", "json", "--no-session-persistence"])

    def test_usage_that_prints_no_json_is_a_launch_error(self):
        os.environ["FAKE_CLAUDE_STREAM"] = str(STREAMS / "README.md")
        with self.assertRaises(worker.LaunchError):
            worker.usage()


class StreamTailTest(unittest.TestCase):
    def test_the_tail_collects_every_rate_limit_event_as_the_stream_grows(self):
        tail = worker.StreamTail(STREAMS / "synth-rejected-429.jsonl").read()
        self.assertEqual([item.status for item in tail.rate_limit_events], ["rejected"])
        self.assertEqual(tail.rate_limit_events[0].five_hour.utilization, 1.0)


# --- the conductor -----------------------------------------------------------------------------


def output(identifier):
    return "hello.txt" if identifier == 1 else "f%d.txt" % identifier


class PacingCase(ConductorCase):
    """The one-ticket project grown by more independent tickets, a fake keyed by ticket, and a clock the test moves."""

    def setUp(self):
        super().setUp()
        self.now = [float(int(time.time()))]
        self.addCleanup(worker.simulate_limit, None)

    def add(self, identifier, difficulty=1):
        """Ticket `identifier`: its own file to write and its own acceptance; ticket 1 is the fixture's."""
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        if identifier == 1:
            tickets.write_ticket(self.ledger, dict(fields, difficulty=difficulty), body)
            return
        name = output(identifier)
        tickets.write_ticket(self.ledger, dict(fields, id=identifier, title="Write file %d" % identifier, difficulty=difficulty,
                                               touches=[name], outputs=[name],
                                               acceptance=dict(fields["acceptance"], machine=["test -f " + name])), body)

    def conductor(self, workers=1):
        self.fake = self.enterContext(worker.use_fake())
        driven = Conductor(self.project, out=io.StringIO())
        driven.policy = dict(driven.policy, max_parallel_workers=workers)
        driven.clock = lambda: self.now[0]
        self.addCleanup(driven.settle, 30)
        self.addCleanup(self.fake.release)
        return driven

    def script(self, identifier, *events, envelope=None, delay=0):
        """Ticket `identifier`'s worker: a done result and its file, or `envelope`, carrying `events`."""
        if envelope is None:
            envelope = done(ticket_id=identifier, outputs_written=[output(identifier)])
            applied = patch({output(identifier): "hello\n"}, "ticket %d" % identifier)
        else:
            applied = None
        envelope.rate_limit_events = list(events)
        self.fake.script(envelope, patch=applied, delay=delay, ticket=identifier)

    def reading(self, window, value):
        """A reading of `value` on one window and 0.1 on the other, both resetting well after this test."""
        values = {"five_hour": 0.1, "seven_day": 0.1, window: value}
        return event(five_hour=values["five_hour"], seven_day=values["seven_day"],
                     five_reset=int(self.now[0]) + 4 * HOUR, week_reset=int(self.now[0]) + 96 * HOUR)

    def pacings(self):
        return [(item["payload"]["five_hour"], item["payload"]["seven_day"], item["payload"]["action"]) for item in self.events("pacing")]

    def launched(self):
        return [item["payload"]["ticket"] for item in self.events("ticket_launched")]

    def statuses(self):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def between(self, first, second):
        names = self.sequence()
        return names[names.index(first) + 1:names.index(second)]


class PacingActionTest(PacingCase):
    """Criteria 1 and 6: readings at 0.79, 0.81 and 0.91 on each window come to the actions, journaled only on change."""

    def pace_through(self, window):
        """Four tickets in turn carry 0.79, 0.81, 0.81 again, and 0.91 on `window`; a fifth waits."""
        for identifier in (2, 3, 4, 5):
            self.add(identifier)
        driven = self.conductor()
        self.script(1, self.reading(window, 0.79))
        self.script(2, self.reading(window, 0.81))
        self.script(3, self.reading(window, 0.81))
        self.script(4, self.reading(window, 0.91))
        last = drive(driven)[-1]
        expected = [(value, 0.1, action) if window == "five_hour" else (0.1, value, action)
                    for value, action in ((0.79, "normal"), (0.81, "cheap_only"), (0.91, "stop"))]
        self.assertEqual(self.pacings(), expected, "the second 0.81 changed nothing, so it is not journaled")
        self.assertEqual(driven.action, "stop")
        self.assertEqual(self.launched(), [1, 2, 3, 4])
        self.assertEqual(self.statuses(), {1: "done", 2: "done", 3: "done", 4: "done", 5: "open"})
        self.assertFalse(last.ended, "a stopped run with work left waits; it does not end")
        self.assertEqual(len(self.fake.calls), 4)

    def test_the_five_hour_window_paces_the_run_through_normal_cheap_only_and_stop(self):
        self.pace_through("five_hour")

    def test_the_seven_day_window_paces_the_run_through_normal_cheap_only_and_stop(self):
        self.pace_through("seven_day")

    def test_cheap_only_defers_no_ticket_and_still_holds_the_verdicts(self):
        """Ticket 62: the deferral of hard tickets is gone; each launch runs one rung down instead (decision 16)."""
        self.add(1, difficulty=3)
        self.add(2, difficulty=3)
        self.add(3, difficulty=2)
        driven = self.conductor()
        self.script(1, self.reading("five_hour", 0.85))
        self.script(2)
        self.script(3)
        drive(driven)
        self.assertEqual(sorted(self.launched()), [1, 2, 3])
        self.assertEqual(self.statuses(), {1: "done", 2: "done", 3: "done"})
        self.assertEqual({call.request.role for call in self.fake.calls}, {"coder"}, "no verifier ran under cheap_only")
        self.assertEqual(len(driven.verdicts), 2, "the difficulty 3 tickets' verdicts wait: a verdict is not on the ladder")
        self.assertIn("pacing says cheap_only", driven.out.getvalue())
        rungs = {item["payload"]["ticket"]: item["payload"]["rung"] for item in self.events("ticket_launched")}
        self.assertEqual((rungs[2], rungs[3]), (4, 2), "difficulty 3 stepped from rung 5 to 4, difficulty 2 from rung 3 to 2")

    def test_the_thresholds_are_read_from_harness_json_and_a_control_event_moves_them(self):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["pacing"] = {"stop_at": 0.6, "cheap_at": 0.4}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.add(2)
        driven = self.conductor()
        self.script(1, self.reading("five_hour", 0.5))
        driven.wave()
        driven.settle()
        driven.wave()
        self.assertEqual(self.pacings(), [(0.5, 0.1, "cheap_only")])
        control(self.project, "pacing", {"cheap_at": 0.55})
        driven.wave()
        self.assertEqual(self.pacings(), [(0.5, 0.1, "cheap_only"), (0.5, 0.1, "normal")])

    def test_a_stop_a_restart_replays_holds_launches_only_while_its_window_can_still_be_full(self):
        """A `pacing` event names no reset, so nothing a stopped run cannot start would ever replace it otherwise."""
        written = pacing.iso(self.now[0] - HOUR).replace("Z", ".000Z")
        self.ledger.append_event("pacing", {"five_hour": 0.95, "seven_day": 0.1, "action": "stop"}, ts=written)
        driven = self.conductor()
        self.script(1)
        self.assertEqual((driven.wave().launched, driven.action), ([], "stop"))
        self.now[0] += 4 * HOUR
        self.assertEqual(driven.wave().launched, [1])
        self.assertEqual(self.pacings()[-1], (None, 0.1, "normal"))

    def test_a_resume_waiting_on_a_reading_its_own_stream_just_gave_is_held_by_it(self):
        driven = self.conductor()
        self.script(1, self.reading("five_hour", 0.95), envelope=Envelope())
        self.script(1)
        driven.wave()
        driven.settle()
        driven.wave()
        self.assertEqual(self.pacings(), [(0.95, 0.1, "stop")])
        self.assertEqual(self.events("ticket_resumed"), [], "the invalid result's one resume waits for the window")
        self.assertEqual(len(self.fake.calls), 1)

    def test_the_usage_reading_at_run_start_is_journaled_as_the_first_pacing(self):
        driven = self.conductor()
        self.now[0] = at(RIYADH, 2026, 9, 11, 18, 0)  # the afternoon the text was recorded, before both resets
        self.fake.usage_text = USAGE_TEXT
        self.script(1)
        driven.run(wait=lambda seconds: driven.settle(), max_waves=4)
        self.assertEqual(self.sequence()[:2], ["run_started", "pacing"])
        self.assertEqual(self.pacings()[0], (0.24, 0.23, "normal"))

    def test_a_usage_command_that_fails_is_said_and_the_run_goes_on(self):
        driven = self.conductor()
        self.fake.usage_text = worker.LaunchError("claude is not on PATH")
        self.script(1)
        waves = driven.run(wait=lambda seconds: driven.settle(), max_waves=4)
        self.assertTrue(waves[-1].ended)
        self.assertIn("claude is not on PATH", driven.out.getvalue())
        self.assertEqual(self.events("pacing"), [])


class PauseTest(PacingCase):
    """Criteria 2, 3 and 6: a hit limit pauses the run, the workers running finish and their checks run, and the reset unpauses it."""

    def test_a_rejected_event_pauses_the_run_while_only_the_running_worker_s_checks_run(self):
        self.add(2)
        driven = self.conductor()
        resets = int(self.now[0]) + 1800
        self.script(1, event(status="rejected", resets_at=resets, five_hour=1.0, seven_day=0.61,
                             five_reset=resets, week_reset=resets + 96 * HOUR), delay=600)
        self.script(2)
        self.assertEqual(driven.wave().launched, [1])
        seen = driven.wave()  # the worker is still running; its stream already said the limit was hit
        self.assertEqual(self.payload("paused"), {"resets_at": pacing.iso(resets), "window": "five_hour", "utilization": 1.0})
        self.assertEqual(seen.launched, [])
        self.fake.release()
        driven.settle()
        carried = driven.wave()
        held = driven.wave()
        self.assertEqual((carried.done, carried.launched, held.launched), ([1], [], []))
        self.assertEqual(len(self.fake.calls), 1, "nothing that needs a model started while paused")
        self.now[0] = resets
        continued = driven.wave()
        self.assertEqual(continued.launched, [2])
        self.assertEqual(self.payload("unpaused"), {})
        while_paused = set(self.between("paused", "unpaused"))
        self.assertIn("acceptance", while_paused)
        self.assertIn("integrated", while_paused)
        self.assertFalse(while_paused & {"ticket_launched", "ticket_resumed", "verdict"}, while_paused)
        self.assertLess(self.sequence().index("unpaused"), self.sequence().index("ticket_launched", 1))
        driven.settle()
        drive(driven)
        self.assertEqual(self.statuses(), {1: "done", 2: "done"})

    def test_a_429_is_journaled_as_a_pause_and_its_session_resumed_after_the_reset_without_failing(self):
        driven = self.conductor()
        limited = Envelope(api_error_status=429, is_error=True, subtype="error_during_execution", exit_code=1, answered=True,
                           errors=["You've hit your session limit · resets 3:45pm"])  # stopped mid-work, so resumed
        self.script(1, envelope=limited)
        self.script(1)
        driven.wave()
        driven.settle()
        carried = driven.wave()
        paused = self.payload("paused")
        resets = pacing.epoch(paused["resets_at"])
        local = datetime.fromtimestamp(resets).astimezone()
        self.assertEqual((local.hour, local.minute, paused["window"]), (15, 45, "five_hour"))
        self.assertLess(0, resets - self.now[0] + 60)
        self.assertLessEqual(resets - self.now[0], 24 * HOUR)
        self.assertEqual(self.payload("ticket_result")["valid"], False)
        self.assertEqual((self.events("ticket_failed"), self.events("ticket_resumed"), self.events("wave")), ([], [], []),
                         "a limit spends no gate and is not a settling outcome")
        self.assertEqual((carried.failed, self.statuses()[1]), ([], "running"))
        self.now[0] = resets + 1
        driven.wave()
        resumed = self.payload("ticket_resumed")
        self.assertEqual(resumed["reason"], "worker_died")
        self.assertEqual([call.kind for call in self.fake.calls], ["launch", "resume"])
        self.assertIn("usage limit", self.fake.calls[1].message)
        self.assertEqual(self.sequence().index("unpaused") + 1, self.sequence().index("ticket_resumed"))
        driven.settle()
        drive(driven)
        self.assertEqual(self.statuses(), {1: "done"})

    def test_a_non_zero_exit_that_says_the_weekly_limit_was_hit_pauses_on_the_week(self):
        driven = self.conductor()
        limited = Envelope(is_error=True, exit_code=1, result_text="You've hit your weekly limit")
        self.script(1, envelope=limited)
        driven.wave()
        driven.settle()
        driven.wave()
        paused = self.payload("paused")
        self.assertEqual(paused["window"], "seven_day")
        self.assertEqual(pacing.epoch(paused["resets_at"]), self.now[0] + 5 * HOUR, "no reset said and none known: five hours")

    def test_a_pause_is_not_journaled_twice_for_the_same_limit(self):
        driven = self.conductor()
        resets = int(self.now[0]) + 600
        self.script(1, event(status="rejected", resets_at=resets))
        drive(driven)
        self.assertEqual(len(self.events("paused")), 1)

    def test_the_run_waits_no_longer_than_the_reset(self):
        driven = self.conductor()
        control(self.project, "pause")  # the owner's pause, so the wave launches nothing either way
        self.ledger.append_event("paused", {"resets_at": pacing.iso(self.now[0] + 20), "window": "five_hour", "utilization": 1.0})
        waited = []
        driven.run(wait=waited.append, max_waves=2)
        self.assertEqual(waited, [20])


class PacedRestartTest(ReadoptionCase):
    """A restart paces before it takes over: a dead worker is not resumed past the stop the `/usage` reading says."""

    def test_a_restart_whose_usage_reading_says_stop_resumes_no_session_on_its_first_wave(self):
        self.killed()
        with worker.use_fake() as fake:
            fake.usage_text = ("Current session: 95% used · resets 3:45pm (UTC)\n"
                               "Current week (all models): 10% used · resets Mon 12:00am (UTC)\n")
            fake.script(done(), patch=patch())
            driven = Conductor(self.project, out=io.StringIO())
            driven.run(resume=True, wait=lambda seconds: driven.settle(), max_waves=1)
            calls = list(fake.calls)
        self.assertEqual(calls, [])
        self.assertEqual(self.events("ticket_resumed"), [])
        self.assertEqual((self.payload("pacing")["five_hour"], self.payload("pacing")["action"]), (0.95, "stop"))
        self.assertIn("once the run may launch again", driven.out.getvalue())


class SimulateLimitVerbTest(PacingCase):
    """Criterion 4 through the verb: the simulated limit pauses the run, which journals the reset that many seconds ahead."""

    def test_run_simulate_limit_pauses_on_the_first_launch(self):
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            before = time.time()
            code, out, err = run_verb(["--simulate-limit", "3600", "--max-waves", "2", "--project", str(self.project)])
        self.assertEqual(code, 0, out + err)
        paused = self.payload("paused")
        self.assertGreaterEqual(pacing.epoch(paused["resets_at"]), int(before) + 3600)
        self.assertLessEqual(pacing.epoch(paused["resets_at"]), time.time() + 3601)
        self.assertEqual(self.ticket()["status"], "done", "the worker running when the limit hit finished")
        self.assertIsNone(worker.simulated_limit(), "the verb disarms what no launch took")

    def test_a_negative_number_of_seconds_is_refused(self):
        code, _, err = run_verb(["--simulate-limit", "-5", "--project", str(self.project)])
        self.assertEqual(code, 2)
        self.assertIn("--simulate-limit", err)

    def test_the_simulated_limit_reaches_the_detached_unit(self):
        """The M5 demo pauses a detached run: `--detach` hands the flag to the unit, spelled as it was given."""
        from wayline import conductor
        for spelling in ("3600", "fable:600", "cheap:900"):
            with self.subTest(spelling=spelling), \
                    mock.patch.object(conductor.tick, "launch_detached", return_value="") as launch, \
                    mock.patch.object(conductor, "conductor_holder", return_value=None), \
                    mock.patch.object(conductor, "announce_dashboard"), \
                    mock.patch.object(conductor, "refuse_to_start", return_value=[]):
                code, out, err = run_verb(["--detach", "--simulate-limit", spelling, "--project", str(self.project)])
                self.assertEqual(code, 0, out + err)
                self.assertEqual(launch.call_args[0][1], ["--simulate-limit", spelling])


# --- wayline status ----------------------------------------------------------------------------


class StatusWindowTest(ProjectTestCase):
    """Criterion 5: `wayline status` prints both utilizations, the action, and the pause with its reset time."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.ledger = Ledger(self.project)

    def window_line(self):
        return [line for line in render_status(status_view(self.project)).splitlines() if line.startswith("window")][0]

    def test_the_line_carries_the_action_and_both_utilizations(self):
        self.ledger.append_event("pacing", {"five_hour": 0.85, "seven_day": 0.41, "action": "cheap_only"})
        line = self.window_line()
        for part in ("cheap_only", "five_hour 0.85", "seven_day 0.41"):
            self.assertIn(part, line)
        self.assertNotIn("paused", line)

    def test_a_paused_run_shows_the_pause_with_its_window_and_reset_time_beside_the_action(self):
        self.ledger.append_event("pacing", {"five_hour": 1.0, "seven_day": None, "action": "stop"})
        self.ledger.append_event("paused", {"resets_at": "2026-09-13T18:00:00Z", "window": "five_hour", "utilization": 1.0})
        line = self.window_line()
        for part in ("stop", "paused on five_hour until 2026-09-13T18:00:00Z", "five_hour 1", "seven_day unknown"):
            self.assertIn(part, line)

    def test_the_thresholds_a_control_event_set_are_the_ones_status_reports(self):
        self.ledger.append_event("control", {"command": "pacing", "args": {"stop_at": 0.95}, "by": "cli"})
        window = status_view(self.project)["window"]
        self.assertEqual((window["stop_at"], window["cheap_at"]), (0.95, 0.80))


if __name__ == "__main__":
    unittest.main()
