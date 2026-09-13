"""The tick (ticket 14; Implementation Decisions 7, 14, and 15).

`tick.tick` is called directly on a laid-out project whose journal each test writes, with a fake
heartbeat, the fake launcher scripted with `/usage` and `claude auth status`, a notifier whose
channels are faked, a relaunch that records the call, and a clock the test sets. What is asserted is
what the owner and the next process see: the journal, the ticket files, the notifications and the
relaunch the tick asked for, and how the tick ended. The verb is run for its lock, and the real
`claude auth status` backend against a stand-in executable.
"""

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.projects import ProjectTestCase
from wayline import cli, notify, pacing, project, resources, tick, tickets, worker
from wayline.ledger import Ledger

NOW = 1_789_000_000
HOUR = 3600
DAY = 24 * HOUR


def ts(seconds):
    """A journal timestamp at an epoch second, spelled as the ledger writes one."""
    return pacing.iso(seconds).replace("Z", ".000Z")


def usage_text(session, week, fable=None):
    """`/usage` as the CLI prints it, with the percentages given; the Fable line only when `fable` is."""
    lines = ["Current session: %d%% used · resets 3:45pm (UTC)" % session,
             "Current week (all models): %d%% used · resets Mon 12:00am (UTC)" % week]
    if fable is not None:
        lines.append("Current week (Fable): %d%% used · resets Mon 12:00am (UTC)" % fable)
    return "\n".join(lines) + "\n"


LOGGED_IN = {"logged_in": True, "exit_code": 0, "status": {"loggedIn": True, "subscriptionType": "max"}}
LOGGED_OUT = {"logged_in": False, "exit_code": 1, "status": {"loggedIn": False}}


class TickCase(ProjectTestCase):
    """A laid-out project with no conductor, the fake launcher, and every outside effect of the tick recorded."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        project.init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=None)
        self.ledger = Ledger(self.project)
        self.fake = self.enterContext(worker.use_fake())
        self.now = NOW
        self.heartbeat = None
        self.living = set()
        self.credentials = self.temp / "credentials.json"
        self.environ = {}
        self.sent = []
        self.relaunched = []
        self.refusal = None
        self.polled = []
        self.rendered = []

    # --- the fakes ---

    def machine(self, **overrides):
        values = dict(clock=lambda: self.now, heartbeat=lambda path: self.heartbeat, alive=lambda pid: pid in self.living,
                      credentials=self.credentials, environ=self.environ, notify=self.notify, relaunch=self.relaunch,
                      render=self.render, poll_jobs=self.poll)
        values.update(overrides)
        return tick.Machine(**values)

    def notify(self, event, text, path, ticket):
        """The real notifier, whose `notify-send` exits 1 as it does over SSH, and no Telegram interpreter."""
        self.sent.append((event, ticket, text))
        return notify.notify(event, text, project=path, ticket=ticket,
                             run=lambda argv, timeout: subprocess.CompletedProcess(argv, 1, "", "no notification daemon"))

    def relaunch(self, path):
        if self.refusal is not None:
            raise self.refusal
        self.relaunched.append(Path(path))
        return "Running as unit: wayline-conductor.service"

    def render(self, path):
        self.rendered.append(Path(path))
        return str(Path(path) / "research" / "REPORT.md")

    def poll(self, path):
        self.polled.append(Path(path))
        return []

    def run_tick(self, **overrides):
        self.out = io.StringIO()
        return tick.tick(project=self.project, machine=self.machine(**overrides), out=self.out)

    # --- the project ---

    def journal(self, event, payload=None, ticket=None, at=None):
        return self.ledger.append_event(event, payload or {}, ticket=ticket, ts=ts(self.now if at is None else at))

    def events(self, name=None):
        found, _ = self.ledger.read_events()
        return [event for event in found if name is None or event["event"] == name]

    def add_ticket(self, identifier, status="open", difficulty=1, kind="code", human_only=False, quality=()):
        fields = {"id": identifier, "title": "Ticket %d" % identifier, "kind": kind, "difficulty": difficulty,
                  "status": status, "blocked_by": [], "touches": ["file%d.txt" % identifier], "role": "coder",
                  "acceptance": {"machine": ["true"]}, "proposed_by": "planner"}
        if kind == "decision":
            fields.update(blocking=None, human_only=human_only, role="decider", touches=[])
        if quality:
            fields["acceptance"]["quality"] = list(quality)
        tickets.write_ticket(self.ledger, fields, "\n## Demo\n\nTicket %d.\n" % identifier)

    def set_status(self, identifier, status):
        ticket = {item["id"]: item for item in tickets.read_tickets(self.project)}[identifier]
        path = tickets.tickets_dir(self.project) / tickets.filename(ticket)
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, status=status), body)

    def ran(self, ended=None, autonomy="checkpoints"):
        """A run that started, and ended for `ended` when one is given (a conductor killed mid-run writes no end)."""
        self.journal("run_started", {"resume": False, "harness_tag": "v0.0.0", "autonomy": autonomy, "radius": "moderate", "pid": 4242})
        if ended is not None:
            self.journal("run_ended", {"reason": ended})

    def done_on(self, identifier, model):
        """Ticket `identifier` launched on `model` and done, which earns the verdicts its difficulty and criteria ask."""
        self.journal("ticket_launched", {"ticket": identifier, "attempt": 1, "role": "coder", "model": model, "effort": "high"}, ticket=identifier)
        self.journal("ticket_done", {"ticket": identifier}, ticket=identifier)

    def login_ends(self, access_in, refresh_in):
        self.credentials.write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "a", "refreshToken": "r", "expiresAt": int((self.now + access_in) * 1000),
            "refreshTokenExpiresAt": int((self.now + refresh_in) * 1000), "subscriptionType": "max",
        }}), encoding="utf-8")

    def login_tickets(self):
        return [item for item in tickets.read_tickets(self.project) if str(item.get("origin") or "").startswith(tick.LOGIN_ORIGIN)]


# --- no project --------------------------------------------------------------------------------------------------


class NoProjectTest(TickCase):
    def test_without_an_active_project_the_tick_ends_before_it_reads_anything(self):
        project.active_path().unlink()  # `init` made the project active
        self.fake.usage_text = usage_text(95, 95)
        self.out = io.StringIO()
        result = tick.tick(machine=self.machine(), out=self.out)
        self.assertEqual((result.ended, result.project, result.pacing), (tick.NO_PROJECT, None, None))
        self.assertIn("no active project", self.out.getvalue())
        self.assertEqual((self.relaunched, self.polled, self.sent), ([], [], []))
        self.assertEqual(self.events("pacing"), [])

    def test_the_active_pointer_names_the_project_the_tick_serves(self):
        project.set_active(self.project)
        result = tick.tick(machine=self.machine(), out=io.StringIO())
        self.assertEqual(result.project, str(self.project.resolve()))


# --- the login ---------------------------------------------------------------------------------------------------


class LoginTest(TickCase):
    def setUp(self):
        super().setUp()
        self.fake.auth = LOGGED_IN

    def test_a_login_ending_within_three_days_opens_one_human_only_decision_ticket_and_notifies_the_owner(self):
        self.login_ends(access_in=6 * HOUR, refresh_in=2 * DAY)
        result = self.run_tick()
        [opened] = self.login_tickets()
        self.assertEqual((opened["kind"], opened["status"], opened["human_only"], opened["blocking"], opened["proposed_by"]),
                         ("decision", "open", True, None, "tick"))
        self.assertEqual(result.login["ticket"], opened["id"])
        self.assertEqual(result.login["expires_at"], self.now + 2 * DAY)
        self.assertEqual(self.events("decision_opened")[-1]["payload"], {"ticket": opened["id"], "blocking": None, "human_only": True})
        self.assertEqual(self.events("ticket_created")[-1]["payload"]["proposed_by"], "tick")
        self.assertEqual([(event, ticket) for event, ticket, _ in self.sent], [("decision_opened", opened["id"])])
        self.assertIn("wayline answer %d" % opened["id"], self.sent[0][2])
        claims = [event for event in self.events("notified") if event["ticket"] == opened["id"]]
        self.assertEqual([event["payload"]["channel"] for event in claims], [None, "notify-send"])

        self.now += HOUR
        self.run_tick()
        self.assertEqual(len(self.login_tickets()), 1)
        self.assertEqual(len(self.sent), 1)

    def test_the_access_token_ending_in_hours_is_not_the_login_ending(self):
        self.login_ends(access_in=6 * HOUR, refresh_in=26 * DAY)
        result = self.run_tick()
        self.assertEqual((result.login["expires_at"], result.login["lapsed"], result.login["ticket"]), (self.now + 26 * DAY, False, None))
        self.assertEqual((self.login_tickets(), self.sent), ([], []))

    def test_an_answered_warning_is_not_asked_again_for_the_same_login(self):
        self.login_ends(access_in=6 * HOUR, refresh_in=2 * DAY)
        self.run_tick()
        [opened] = self.login_tickets()
        project.answer(self.project, opened["id"], "later")
        self.set_status(opened["id"], "done")  # what the conductor does with an answered decision ticket
        self.now += DAY
        result = self.run_tick()
        self.assertEqual((len(self.login_tickets()), result.login["ticket"]), (1, None))

    def test_a_new_login_that_nears_its_end_is_warned_of_again(self):
        self.login_ends(access_in=6 * HOUR, refresh_in=2 * DAY)
        self.run_tick()
        [opened] = self.login_tickets()
        self.set_status(opened["id"], "done")
        self.now += 28 * DAY
        self.login_ends(access_in=6 * HOUR, refresh_in=DAY)  # the owner signed in again, and that login is ending too
        result = self.run_tick()
        self.assertEqual(len(self.login_tickets()), 2)
        self.assertNotEqual(result.login["ticket"], opened["id"])

    def test_units_on_a_setup_token_do_not_read_the_stored_login(self):
        self.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "sk-ant-oat01-test"
        self.login_ends(access_in=HOUR, refresh_in=HOUR)
        result = self.run_tick()
        self.assertEqual((result.login["token"], result.login["expires_at"], result.login["lapsed"]), (True, None, False))
        self.assertEqual(self.login_tickets(), [])

    def test_a_login_that_ended_lapses_and_the_tick_only_polls_the_jobs(self):
        self.login_ends(access_in=-HOUR, refresh_in=-HOUR)
        self.fake.usage_text = usage_text(10, 10)
        self.ran()
        self.add_ticket(1)
        result = self.run_tick()
        self.assertEqual(result.ended, tick.LAPSED)
        [opened] = self.login_tickets()
        self.assertIn("lapsed", opened["title"])
        self.assertEqual(self.polled, [self.project.resolve()])
        self.assertEqual((self.relaunched, self.rendered, self.events("pacing")), ([], [], []))

    def test_claude_auth_status_reporting_no_login_is_a_lapse(self):
        self.fake.auth = LOGGED_OUT
        result = self.run_tick()
        self.assertEqual((result.ended, result.login["logged_in"]), (tick.LAPSED, False))
        [opened] = self.login_tickets()
        self.assertIn("no login", opened["origin"])

    def test_a_lapse_answered_is_asked_again_only_after_the_warning_days(self):
        self.fake.auth = LOGGED_OUT
        self.run_tick()
        [opened] = self.login_tickets()
        self.set_status(opened["id"], "done")
        self.now += DAY
        self.run_tick()
        self.assertEqual(len(self.login_tickets()), 1)
        self.now += 3 * DAY
        self.run_tick()
        self.assertEqual(len(self.login_tickets()), 2)


class AuthStatusBackendTest(unittest.TestCase):
    """`ClaudeCli.auth_status` runs `claude auth status --json` and reads its exit code and JSON."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-auth-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.stand_in = self.temp / "claude"
        self.stand_in.write_text('#!/bin/sh\nprintf "%s" "$*" > "$FAKE_AUTH_ARGV"\nprintf "%s" "$FAKE_AUTH_JSON"\nexit "$FAKE_AUTH_EXIT"\n',
                                 encoding="utf-8")
        self.stand_in.chmod(0o755)

    def status(self, printed, exit_code):
        with mock.patch.dict(os.environ, {"WAYLINE_CLAUDE": str(self.stand_in), "FAKE_AUTH_ARGV": str(self.temp / "argv"),
                                          "FAKE_AUTH_JSON": printed, "FAKE_AUTH_EXIT": str(exit_code)}):
            return worker.ClaudeCli().auth_status()

    def test_a_login_reads_as_logged_in(self):
        self.assertEqual(self.status('{"loggedIn": true, "subscriptionType": "max"}', 0),
                         {"logged_in": True, "exit_code": 0, "status": {"loggedIn": True, "subscriptionType": "max"}})
        self.assertEqual((self.temp / "argv").read_text(encoding="utf-8"), "auth status --json")

    def test_exit_1_reads_as_no_login(self):
        self.assertEqual(self.status('{"loggedIn": false}', 1), {"logged_in": False, "exit_code": 1, "status": {"loggedIn": False}})

    def test_output_that_is_not_json_is_read_by_the_exit_code(self):
        self.assertEqual(self.status("Not logged in", 1), {"logged_in": False, "exit_code": 1, "status": None})


# --- /usage and the heartbeat ---------------------------------------------------------------------------------------


class UsageTest(TickCase):
    def setUp(self):
        super().setUp()
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 30), "harness_tag": "v0.0.0"}
        self.living.add(4242)

    def pacings(self):
        return [event["payload"] for event in self.events("pacing")]

    def test_usage_is_journaled_as_pacing_with_its_fable_line_and_only_when_it_changed(self):
        self.fake.usage_text = usage_text(24, 23, fable=43)
        result = self.run_tick()
        self.assertEqual(result.pacing, {"five_hour": 0.24, "seven_day": 0.23, "fable": 0.43, "action": "normal"})
        self.assertEqual(self.pacings(), [result.pacing])
        self.run_tick()
        self.assertEqual(len(self.pacings()), 1)
        self.fake.usage_text = usage_text(95, 23, fable=43)
        self.run_tick()
        self.assertEqual(self.pacings()[-1], {"five_hour": 0.95, "seven_day": 0.23, "fable": 0.43, "action": "stop"})

    def test_usage_that_cannot_be_read_journals_nothing(self):
        self.fake.usage_text = worker.LaunchError("claude is not on PATH")
        result = self.run_tick()
        self.assertEqual((result.pacing, self.pacings(), result.problems), (None, [], []))


class HeartbeatTest(TickCase):
    def setUp(self):
        super().setUp()
        self.ran()
        self.add_ticket(1)
        self.fake.usage_text = usage_text(10, 10)

    def test_a_live_conductor_that_waved_recently_ends_the_tick_once_usage_is_read(self):
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 60), "harness_tag": "v0.0.0"}
        self.living.add(4242)
        result = self.run_tick()
        self.assertEqual(result.ended, tick.CONDUCTOR_ALIVE)
        self.assertEqual(len(self.events("pacing")), 1)
        self.assertEqual((self.polled, self.rendered, self.sent, self.relaunched), ([], [], [], []))

    def test_a_live_conductor_that_stopped_waving_is_not_relaunched_but_the_rest_runs(self):
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 600), "harness_tag": "v0.0.0"}
        self.living.add(4242)
        result = self.run_tick()
        self.assertEqual(result.ended, tick.NOT_RELAUNCHED)
        self.assertIn("still holds the project", result.why)
        self.assertEqual((self.polled, self.rendered, self.relaunched), ([self.project.resolve()], [self.project.resolve()], []))

    def test_a_dead_conductor_with_work_and_an_open_window_is_relaunched(self):
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 60), "harness_tag": "v0.0.0"}
        result = self.run_tick()
        self.assertEqual((result.ended, result.relaunched), (tick.RELAUNCHED, True))
        self.assertEqual(self.relaunched, [self.project.resolve()])
        self.assertIn("1 ticket(s) on the frontier", result.why)
        self.assertEqual(self.polled, [self.project.resolve()])

    def test_no_heartbeat_at_all_is_no_conductor(self):
        self.assertTrue(self.run_tick().relaunched)


# --- the relaunch ------------------------------------------------------------------------------------------------------


class WindowTest(TickCase):
    """Work remains; whether the window lets the conductor launch decides the relaunch."""

    def setUp(self):
        super().setUp()
        self.ran()
        self.add_ticket(1)

    def paused(self, resets_at):
        self.journal("paused", {"resets_at": pacing.iso(resets_at), "window": "five_hour", "utilization": 1.0})

    def test_a_pause_whose_reset_has_passed_relaunches(self):
        self.paused(NOW - 60)
        self.assertTrue(self.run_tick().relaunched)

    def test_a_pause_still_standing_with_no_reading_does_not(self):
        self.paused(NOW + HOUR)
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("paused until %s" % pacing.iso(NOW + HOUR), result.why)
        self.now = NOW + HOUR + 60
        self.assertTrue(self.run_tick().relaunched)

    def test_a_reading_under_stop_at_relaunches_before_the_pause_resets(self):
        self.paused(NOW + HOUR)
        self.fake.usage_text = usage_text(10, 20)
        self.assertTrue(self.run_tick().relaunched)

    def test_a_reading_at_stop_at_keeps_the_window_closed(self):
        self.fake.usage_text = usage_text(91, 20)
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("/usage reads 0.91", result.why)

    def test_the_project_s_own_stop_at_is_the_threshold(self):
        path = self.project / project.HARNESS_JSON
        harness = json.loads(path.read_text(encoding="utf-8"))
        harness["pacing"] = {"stop_at": 0.95}
        path.write_text(json.dumps(harness), encoding="utf-8")
        self.fake.usage_text = usage_text(91, 20)
        self.assertTrue(self.run_tick().relaunched)


class WorkTest(TickCase):
    def test_no_work_is_no_relaunch(self):
        self.ran(ended="frontier_empty")
        self.add_ticket(1, status="done")
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_a_project_never_run_is_left_for_the_owner_to_start(self):
        self.add_ticket(1)
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("never been run", result.why)

    def test_a_run_the_owner_stopped_is_not_relaunched_for_work(self):
        self.ran(ended="stopped")
        self.add_ticket(1)
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("ended stopped", result.why)

    def test_a_run_killed_mid_run_with_a_ticket_running_is_relaunched(self):
        self.ran()
        self.add_ticket(1, status="running")
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("1 ticket(s) running", result.why)

    def test_a_human_only_decision_ticket_is_not_work(self):
        self.ran(ended="frontier_empty", autonomy="autonomous")
        self.add_ticket(1, kind="decision", human_only=True)
        self.assertFalse(self.run_tick().relaunched)

    def test_a_decision_ticket_the_decider_may_take_is_work_only_under_autonomous(self):
        self.ran(ended="frontier_empty")
        self.add_ticket(1, kind="decision")
        self.assertFalse(self.run_tick().relaunched)
        self.ran(ended="frontier_empty", autonomy="autonomous")
        self.assertTrue(self.run_tick().relaunched)

    def test_a_running_job_is_polled_and_its_outputs_are_checked_once_it_exited(self):
        self.ran()
        self.add_ticket(1, status="running")
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running", resources.JobState("exited", result="success", exit_code=0)],
                        outputs={"results/metrics.json": '{"auroc": 0.81}', "results/table.csv": "seed,auroc\n1,0.81\n"})
            resources.JobRunner(self.project, backend=jobs).launch(resources.JobSpec(
                id="j-0001", ticket=1, command=("python3", "train.py"), cwd=str(self.project),
                log=str(self.project / "results" / "logs" / "j-0001.log"),
                expected_outputs=("results/metrics.json", "results/table.csv")))
            first = self.run_tick(poll_jobs=tick.poll_jobs)
            second = self.run_tick(poll_jobs=tick.poll_jobs)
        self.assertEqual(first.jobs, [{"job": "j-0001", "ticket": 1, "was": "running", "now": "running"}])
        self.assertEqual(first.checks, [])
        self.assertIn("1 job(s) live", first.why)
        self.assertEqual(second.jobs, [{"job": "j-0001", "ticket": 1, "was": "running", "now": "exited"}])
        self.assertEqual(second.checks, [{"job": "j-0001", "ticket": 1, "outputs_ok": True, "problems": []}])

    def test_an_output_that_does_not_parse_fails_the_check(self):
        self.ran()
        self.add_ticket(1, status="running")
        with resources.use_fake_jobs() as jobs:
            jobs.script([resources.JobState("exited", result="success", exit_code=0)], outputs={"results/metrics.json": "auroc=0.81"})
            resources.JobRunner(self.project, backend=jobs).launch(resources.JobSpec(
                id="j-0002", ticket=1, command=("python3", "train.py"), cwd=str(self.project),
                log=str(self.project / "results" / "logs" / "j-0002.log"),
                expected_outputs=("results/metrics.json", "results/missing.csv")))
            result = self.run_tick(poll_jobs=tick.poll_jobs)
        [check] = result.checks
        self.assertFalse(check["outputs_ok"])
        self.assertEqual([problem.split(" ")[0] for problem in check["problems"]], ["results/metrics.json", "results/missing.csv"])
        self.assertIn("does not parse", check["problems"][0])
        self.assertIn("is missing", check["problems"][1])


class AnswerTest(TickCase):
    def decision(self, identifier=2):
        self.add_ticket(identifier, kind="decision", human_only=True)
        self.journal("decision", {"ticket": identifier, "answer": "the held-out split", "decided_by": "human",
                                  "rationale": None, "confidence": None}, ticket=identifier)

    def test_an_answer_after_the_run_ended_relaunches_even_a_stopped_run_with_the_window_closed(self):
        self.ran(ended="stopped")
        self.decision()
        self.fake.usage_text = usage_text(95, 95)
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("a decision was answered", result.why)

    def test_an_answer_after_a_pause_relaunches(self):
        self.ran()
        self.journal("paused", {"resets_at": pacing.iso(NOW + HOUR), "window": "five_hour", "utilization": 1.0})
        self.decision()
        self.assertTrue(self.run_tick().relaunched)

    def test_an_answer_the_last_run_already_took_does_not(self):
        self.ran()
        self.decision()
        self.journal("run_ended", {"reason": "frontier_empty"})
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)


class FableVerdictTest(TickCase):
    """A verdict queue that waits only on Fable counts as work once Fable's weekly window has reset (decision 15)."""

    def setUp(self):
        super().setUp()
        self.ran()  # a conductor killed while its verdicts waited
        self.add_ticket(1, status="done", difficulty=3)
        self.done_on(1, "opus")  # a difficulty-3 diff read on an Opus author goes to a Fable verifier
        self.resets = NOW + 2 * DAY
        self.journal("paused", {"resets_at": pacing.iso(self.resets), "window": "seven_day", "utilization": 1.0, "model": "fable"})

    def test_while_the_hold_stands_a_queue_waiting_only_on_fable_is_no_work(self):
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("1 ticket(s) wait for a verdict on Fable", result.why)

    def test_once_fable_s_window_has_reset_the_queue_is_work(self):
        self.now = self.resets + 60
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("1 ticket(s) owed a verdict", result.why)

    def test_a_fable_reading_under_stop_at_is_a_reset_before_the_hold_s_reset(self):
        self.fake.usage_text = usage_text(10, 20, fable=12)
        self.assertTrue(self.run_tick().relaunched)

    def test_a_fable_reading_at_stop_at_keeps_the_queue_waiting_without_a_hold(self):
        self.now = self.resets + 60
        self.fake.usage_text = usage_text(10, 20, fable=97)
        self.assertFalse(self.run_tick().relaunched)

    def test_a_verdict_that_does_not_run_on_fable_is_work_while_the_hold_stands(self):
        self.add_ticket(2, status="done", difficulty=2, quality=["the file says hello"])
        self.done_on(2, "sonnet")  # a Sonnet author's quality verdict goes to Opus
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("2 ticket(s) owed a verdict", result.why)

    def test_a_ticket_whose_verdicts_all_passed_owes_none(self):
        for verdict_type in ("diff",):
            self.journal("verdict", {"subject_kind": "ticket", "subject": "tickets/01-ticket-1.md", "verdict_type": verdict_type,
                                     "pass": True, "session_id": "s", "model": "fable", "findings": []}, ticket=1)
        self.now = self.resets + 60
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)


# --- jobs, the report, the notifications --------------------------------------------------------------------------------


class NotificationTest(TickCase):
    def said(self):
        return [(event, ticket) for event, ticket, _ in self.sent]

    def test_every_standing_event_is_sent_once(self):
        self.ran()
        self.add_ticket(2, kind="decision")
        self.journal("decision_opened", {"ticket": 2, "blocking": None, "human_only": False}, ticket=2)
        self.add_ticket(3, status="needs_human")
        self.journal("ticket_needs_human", {"ticket": 3, "question": "which seed is held out?"}, ticket=3)
        self.journal("paused", {"resets_at": pacing.iso(NOW + HOUR), "window": "five_hour", "utilization": 1.0})
        self.journal("run_ended", {"reason": "stopped"})
        result = self.run_tick()
        self.assertEqual(self.said(), [("decision_opened", 2), ("ticket_needs_human", 3), ("paused", None), ("run_ended", None)])
        self.assertEqual([item["event"] for item in result.notified], ["decision_opened", "ticket_needs_human", "paused", "run_ended"])
        texts = [text for _, _, text in self.sent]
        self.assertTrue(all(text.startswith("study: ") for text in texts), texts)
        self.assertIn("wayline answer 2", texts[0])
        self.assertIn("which seed is held out?", texts[1])
        self.assertIn(pacing.iso(NOW + HOUR), texts[2])
        self.assertIn("stopped", texts[3])
        self.assertEqual(len(self.events("notified")), 8)  # each one's claim, then how it went

        self.now += 15 * 60
        self.run_tick()
        self.assertEqual(len(self.sent), 4)

    def test_what_no_longer_stands_is_not_sent_late(self):
        self.ran(ended="frontier_empty")
        self.add_ticket(2, kind="decision", status="done")
        self.journal("decision_opened", {"ticket": 2, "blocking": None, "human_only": False}, ticket=2)
        self.add_ticket(3)
        self.journal("ticket_needs_human", {"ticket": 3, "question": "which seed?"}, ticket=3)
        self.journal("paused", {"resets_at": pacing.iso(NOW + HOUR), "window": "five_hour", "utilization": 1.0})
        self.journal("unpaused", {})
        self.journal("paused", {"resets_at": pacing.iso(NOW - 60), "window": "five_hour", "utilization": 1.0})
        self.ran()
        self.run_tick()
        self.assertEqual(self.said(), [])

    def test_the_hold_on_fable_is_not_sent_as_a_pause(self):
        self.ran()
        self.journal("paused", {"resets_at": pacing.iso(NOW + DAY), "window": "seven_day", "utilization": 1.0, "model": "fable"})
        self.run_tick()
        self.assertEqual(self.said(), [])

    def test_a_run_that_reached_its_goal_is_sent_as_goal_reached(self):
        self.ran(ended="goal_reached")
        self.run_tick()
        self.assertEqual(self.said(), [("goal_reached", None)])

    def test_a_claim_whose_channel_failed_is_not_sent_again(self):
        self.ran(ended="frontier_empty")
        self.journal("notified", {"event": "run_ended", "channel": None, "ok": None, "exit_code": None})
        self.run_tick()
        self.assertEqual(self.said(), [])


class ReportTest(TickCase):
    def test_the_report_is_rendered_offline_when_the_journal_moved_and_not_again_when_it_did_not(self):
        self.ran()
        first = self.run_tick(render=tick.render_report)
        self.assertEqual(first.report, str(self.project.resolve() / "research" / "REPORT.md"))
        self.assertTrue(Path(first.report).is_file())
        self.assertEqual(len(self.events("report_rendered")), 1)
        self.assertEqual(self.fake.calls, [])  # no session was launched to render it
        self.now += 15 * 60
        second = self.run_tick(render=tick.render_report)
        self.assertIsNone(second.report)
        self.assertEqual(len(self.events("report_rendered")), 1)

    def test_a_report_that_cannot_render_is_a_problem_and_the_relaunch_still_happens(self):
        self.ran()
        self.add_ticket(1)

        def broken(path):
            raise RuntimeError("the disk is full")

        result = self.run_tick(render=broken)
        self.assertEqual(result.problems, ["report: the disk is full"])
        self.assertTrue(result.relaunched)
        self.assertIn("report failed", self.out.getvalue())

    def test_a_refused_relaunch_is_said_and_kept_as_a_problem(self):
        self.ran()
        self.add_ticket(1)
        self.refusal = tick.UnitsOff("WAYLINE_UNITS=none: this process does not reach the user manager")
        result = self.run_tick()
        self.assertEqual((result.ended, result.relaunched), (tick.NOT_RELAUNCHED, False))
        self.assertIn("WAYLINE_UNITS=none", result.why)
        self.assertEqual(len(result.problems), 1)


# --- the verb -----------------------------------------------------------------------------------------------------------


class VerbTest(ProjectTestCase):
    def tick_verb(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["tick", *args])
        return code, out.getvalue()

    def test_wayline_tick_without_an_active_project_exits_0(self):
        code, said = self.tick_verb()
        self.assertEqual(code, 0)
        self.assertIn("no active project", said)

    def test_a_tick_holding_the_lock_keeps_a_second_one_out(self):
        with tick.tick_lock() as held:
            self.assertTrue(held)
            code, said = self.tick_verb()
        self.assertEqual(code, 0)
        self.assertIn("another tick holds %s" % (self.wayline_home / "tick.lock"), said)
        code, said = self.tick_verb()
        self.assertIn("no active project", said)


if __name__ == "__main__":
    unittest.main()
