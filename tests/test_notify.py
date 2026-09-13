"""The notifier (Implementation Decisions 7): journal first, `notify-send`, then `hermes send`, never raise.

The subprocesses are faked; what is asserted is what the owner and the tick can observe: the
commands run, in order, and the two `notified` events the journal carries.
"""

import json
import subprocess
from unittest import mock

from tests.projects import ProjectTestCase
from wayline import notify
from wayline.ledger import Ledger
from wayline.project import HARNESS_JSON, init_project

HERMES = "/opt/hermes/venv/bin/python"


class Channels:
    """A stand-in for `subprocess.run`: answers each call with the next scripted exit code or exception."""

    def __init__(self, *answers, look=None):
        self.answers = list(answers)
        self.calls = []
        self.look = look

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        if self.look is not None:
            self.look()
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return subprocess.CompletedProcess(argv, answer, "", "no daemon" if answer else "")


class NotifyTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)

    def with_hermes(self, value=HERMES):
        path = self.project / HARNESS_JSON
        harness = json.loads(path.read_text(encoding="utf-8"))
        harness["notify"]["hermes_python"] = value
        path.write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def notified(self):
        events, _ = self.ledger.read_events()
        return [event for event in events if event["event"] == "notified"]

    def test_notify_send_delivers_and_both_events_are_journaled(self):
        channels = Channels(0)
        outcome = notify.notify("paused", "the window closed; it resets at 14:00", project=self.project, run=channels)
        self.assertEqual(channels.calls, [["notify-send", "-a", "wayline", "-u", "normal", "wayline: paused (study)",
                                           "the window closed; it resets at 14:00"]])
        self.assertEqual(outcome, {"event": "paused", "channel": "notify-send", "ok": True, "exit_code": 0, "journaled": True})
        self.assertEqual([event["payload"] for event in self.notified()], [
            {"event": "paused", "channel": None, "ok": None, "exit_code": None},
            {"event": "paused", "channel": "notify-send", "ok": True, "exit_code": 0},
        ])

    def test_the_claim_is_in_the_journal_before_any_channel_runs(self):
        seen = []
        channels = Channels(0, look=lambda: seen.append(len(self.notified())))
        notify.notify("run_ended", "frontier_empty", project=self.project, run=channels)
        self.assertEqual(seen, [1])

    def test_a_failed_notify_send_falls_through_to_hermes(self):
        self.with_hermes()
        channels = Channels(1, 0)
        outcome = notify.notify("decision_opened", "ticket 7 asks which split is held out", project=self.project, run=channels)
        self.assertEqual(channels.calls[1], [HERMES, "-m", "hermes_cli.main", "send", "--to", "telegram",
                                             "--subject", "[wayline]", "ticket 7 asks which split is held out"])
        self.assertEqual((outcome["channel"], outcome["ok"], outcome["exit_code"]), ("hermes", True, 0))
        self.assertEqual(self.notified()[-1]["payload"], {"event": "decision_opened", "channel": "hermes", "ok": True, "exit_code": 0})

    def test_a_delivered_notify_send_does_not_also_send_to_the_phone(self):
        self.with_hermes()
        channels = Channels(0)
        notify.notify("paused", "text", project=self.project, run=channels)
        self.assertEqual(len(channels.calls), 1)

    def test_a_failed_hermes_is_journaled_with_its_exit_code(self):
        self.with_hermes()
        outcome = notify.notify("paused", "text", project=self.project, run=Channels(1, 1))
        self.assertEqual(self.notified()[-1]["payload"], {"event": "paused", "channel": "hermes", "ok": False, "exit_code": 1})
        self.assertFalse(outcome["ok"])

    def test_without_hermes_the_notifier_stops_at_notify_send(self):
        channels = Channels(1)
        notify.notify("paused", "text", project=self.project, run=channels)
        self.assertEqual(len(channels.calls), 1)
        self.assertEqual(self.notified()[-1]["payload"], {"event": "paused", "channel": "notify-send", "ok": False, "exit_code": 1})

    def test_a_timed_out_or_crashing_channel_falls_through_with_no_exit_code(self):
        self.with_hermes()
        with self.assertLogs("wayline.notify", level="WARNING"):
            outcome = notify.notify("paused", "text", project=self.project,
                                    run=Channels(subprocess.TimeoutExpired("notify-send", 15), RuntimeError("hermes exploded")))
        self.assertEqual((outcome["channel"], outcome["ok"], outcome["exit_code"]), ("hermes", False, None))
        self.assertEqual(self.notified()[-1]["payload"], {"event": "paused", "channel": "hermes", "ok": False, "exit_code": None})

    def test_no_channel_that_can_run_is_channel_none(self):
        self.with_hermes("/nowhere/python")
        outcome = notify.notify("paused", "text", project=self.project, run=Channels(FileNotFoundError(), FileNotFoundError()))
        self.assertEqual(self.notified()[-1]["payload"], {"event": "paused", "channel": "none", "ok": False, "exit_code": None})
        self.assertFalse(outcome["ok"])

    def test_the_ticket_rides_on_both_events(self):
        notify.notify("ticket_needs_human", "ticket 3 needs you", project=self.project, ticket=3, run=Channels(0))
        self.assertEqual([event["ticket"] for event in self.notified()], [3, 3])

    def test_it_never_raises(self):
        with mock.patch("wayline.notify._hermes_python", side_effect=RuntimeError("harness.json exploded")):
            with self.assertLogs("wayline.notify", level="ERROR"):
                outcome = notify.notify("paused", "text", project=self.project, run=Channels(1))
        self.assertFalse(outcome["ok"])
        self.assertEqual(len(self.notified()), 1)  # the claim made it; the outcome did not

    def test_an_unwritable_journal_still_reaches_the_owner(self):
        journal = self.project / "research" / "journal.jsonl"
        journal.unlink()
        journal.mkdir()  # an append to it fails, whoever runs the suite
        channels = Channels(0)
        with self.assertLogs("wayline.notify", level="ERROR"):
            outcome = notify.notify("paused", "text", project=self.project, run=channels)
        self.assertEqual(len(channels.calls), 1)
        self.assertTrue(outcome["ok"])
        self.assertFalse(outcome["journaled"])

    def test_the_active_project_is_the_default_and_none_still_notifies(self):
        notify.notify("paused", "text", run=Channels(0))
        self.assertEqual(len(self.notified()), 2)  # init made the study the active project
        (self.wayline_home / "active").unlink()
        channels = Channels(0)
        outcome = notify.notify("paused", "text", run=channels)
        self.assertEqual(channels.calls[0][5], "wayline: paused")
        self.assertEqual((outcome["ok"], outcome["journaled"]), (True, False))
