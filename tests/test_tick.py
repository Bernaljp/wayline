"""The tick (ticket 14; Implementation Decisions 7, 14, and 15).

`tick.tick` is called directly on a laid-out project whose journal each test writes, with a fake
conductor heartbeat, the fake launcher scripted with `/usage` and `auth status`, a notifier whose
channels are faked, a relaunch that records the call, and a clock the test sets. What is asserted is
what the owner and the next process see: the journal, the ticket files, the notifications and the
relaunch the tick asked for, and how the tick ended. The verb is run for its lock, and the real
`auth status` backend against a stand-in executable.
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

from tests.projects import ProjectTestCase, on_fable, open_objective
from wayline import cli, decisions, notify, pacing, project, resources, tick, tickets, worker
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
UNSAID = {"logged_in": None, "exit_code": 2, "status": None}


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
        self.holding = False  # whether a conductor holds the heartbeat's lock
        self.credentials = self.temp / "credentials.json"
        self.environ = {}
        self.sent = []
        self.relaunched = []
        self.refusal = None
        self.polled = []
        self.rendered = []

    # --- the fakes ---

    def machine(self, **overrides):
        values = dict(clock=lambda: self.now, conductor=lambda path: self.heartbeat if self.holding else None,
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

    def add_ticket(self, identifier, status="open", difficulty=1, kind="code", human_only=False, quality=(), answer=None):
        fields = {"id": identifier, "title": "Ticket %d" % identifier, "kind": kind, "difficulty": difficulty,
                  "status": status, "blocked_by": [], "touches": ["file%d.txt" % identifier], "role": "coder",
                  "acceptance": {"machine": ["true"]}, "proposed_by": "planner"}
        if kind == "decision":
            fields.update(blocking=None, human_only=human_only, role="decider", touches=[])
        if quality:
            fields["acceptance"]["quality"] = list(quality)
        body = "\n## Demo\n\nTicket %d.\n" % identifier
        tickets.write_ticket(self.ledger, fields, tickets.with_answer(body, answer) if answer is not None else body)

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

    def answered(self, identifier, text="the held-out split"):
        self.journal("decision", {"ticket": identifier, "answer": text, "decided_by": "human", "rationale": None, "confidence": None},
                     ticket=identifier)

    def done_on(self, identifier, model):
        """Ticket `identifier` launched on `model` and done, which earns the verdicts its difficulty and criteria ask."""
        self.journal("ticket_launched", {"ticket": identifier, "attempt": 1, "role": "coder", "model": model, "effort": "high"}, ticket=identifier)
        self.journal("ticket_done", {"ticket": identifier}, ticket=identifier)

    def login_ends(self, access_in, refresh_in=None):
        oauth = {"accessToken": "a", "refreshToken": "r", "expiresAt": int((self.now + access_in) * 1000), "subscriptionType": "max"}
        if refresh_in is not None:
            oauth["refreshTokenExpiresAt"] = int((self.now + refresh_in) * 1000)
        self.credentials.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")

    def login_tickets(self):
        return [item for item in tickets.read_tickets(self.project) if str(item.get("origin") or "").startswith(tick.LOGIN_ORIGIN)]

    def launch_job(self, jobs, job_id, outputs=(), states=("running",), written=None):
        jobs.script([resources.JobState(state, result="success", exit_code=0) if state == "exited" else state for state in states],
                    outputs=written or {}, job_id=job_id)
        resources.JobRunner(self.project, backend=jobs).launch(resources.JobSpec(
            id=job_id, ticket=1, command=("python3", "train.py"), cwd=str(self.project),
            log=str(self.project / "results" / "logs" / ("%s.log" % job_id)), expected_outputs=tuple(outputs)))


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

    def test_an_access_token_alone_past_its_end_is_its_routine_refresh_while_auth_status_reports_the_login(self):
        self.login_ends(access_in=-HOUR)
        result = self.run_tick()
        self.assertEqual((result.login["expires_at"], result.login["lapsed"], result.login["ticket"]), (None, False, None))
        self.assertEqual(self.login_tickets(), [])

    def test_a_login_past_its_expiry_that_auth_status_still_reports_is_warned_of_and_not_lapsed(self):
        self.login_ends(access_in=6 * HOUR, refresh_in=-HOUR)
        result = self.run_tick()
        self.assertFalse(result.login["lapsed"])
        self.assertNotEqual(result.ended, tick.LAPSED)
        [opened] = self.login_tickets()
        self.assertEqual(opened["title"], "Renew the login before it ends")

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

    def test_a_stored_login_that_ended_lapses_when_auth_status_cannot_say_and_the_tick_only_polls_the_jobs(self):
        self.fake.auth = None
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

    def test_auth_status_failing_without_saying_there_is_no_login_is_not_a_lapse(self):
        self.fake.auth = UNSAID
        self.login_ends(access_in=6 * HOUR, refresh_in=26 * DAY)
        result = self.run_tick()
        self.assertEqual((result.login["logged_in"], result.login["lapsed"], self.login_tickets()), (None, False, []))

    def test_auth_status_reporting_no_login_is_a_lapse(self):
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
    """`ClaudeCli.auth_status` runs `auth status --json` and reads its exit code and JSON."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="wayline-auth-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.stand_in = self.temp / "stand-in"
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

    def test_logged_in_false_reads_as_no_login(self):
        self.assertEqual(self.status('{"loggedIn": false}', 1), {"logged_in": False, "exit_code": 1, "status": {"loggedIn": False}})

    def test_a_nonzero_exit_that_does_not_say_there_is_no_login_says_nothing(self):
        self.assertEqual(self.status("TypeError: cannot read the configuration", 1), {"logged_in": None, "exit_code": 1, "status": None})


# --- /usage and the heartbeat ---------------------------------------------------------------------------------------


class UsageTest(TickCase):
    def setUp(self):
        super().setUp()
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 30), "harness_tag": "v0.0.0"}
        self.holding = True

    def pacings(self):
        return [event["payload"] for event in self.events("pacing")]

    def test_usage_is_journaled_as_pacing_with_its_fable_line_and_only_when_it_changed(self):
        self.fake.usage_text = usage_text(24, 23, fable=43)
        result = self.run_tick()
        self.assertEqual(result.pacing, {"five_hour": 0.24, "seven_day": 0.23, "fable": 0.43,
                                         "action": "normal", "fable_action": "normal"})
        self.assertEqual(self.pacings(), [result.pacing])
        self.run_tick()
        self.assertEqual(len(self.pacings()), 1)
        self.fake.usage_text = usage_text(95, 23, fable=43)
        self.run_tick()
        self.assertEqual(self.pacings()[-1], {"five_hour": 0.95, "seven_day": 0.23, "fable": 0.43,
                                              "action": "stop", "fable_action": "normal"})

    def test_usage_that_cannot_be_read_journals_nothing(self):
        self.fake.usage_text = worker.LaunchError("the executable is not on PATH")
        result = self.run_tick()
        self.assertEqual((result.pacing, self.pacings(), result.problems), (None, [], []))


class HeartbeatTest(TickCase):
    def setUp(self):
        super().setUp()
        self.ran()
        self.add_ticket(1)
        self.fake.usage_text = usage_text(10, 10)

    def test_a_conductor_that_holds_the_project_and_waved_recently_ends_the_tick_once_usage_is_read(self):
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 60), "harness_tag": "v0.0.0"}
        self.holding = True
        result = self.run_tick()
        self.assertEqual(result.ended, tick.CONDUCTOR_ALIVE)
        self.assertEqual(len(self.events("pacing")), 1)
        self.assertEqual((self.polled, self.rendered, self.sent, self.relaunched), ([], [], [], []))

    def test_a_conductor_that_took_the_lock_and_has_not_written_its_heartbeat_yet_is_alive(self):
        self.heartbeat, self.holding = {}, True
        result = self.run_tick()
        self.assertEqual(result.ended, tick.CONDUCTOR_ALIVE)
        self.assertIn("has not written its first heartbeat", result.why)

    def test_a_conductor_that_holds_the_project_and_stopped_waving_is_not_relaunched_but_the_rest_runs(self):
        self.heartbeat = {"pid": 4242, "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 600), "harness_tag": "v0.0.0"}
        self.holding = True
        result = self.run_tick()
        self.assertEqual(result.ended, tick.NOT_RELAUNCHED)
        self.assertIn("still holds the project", result.why)
        self.assertEqual((self.polled, self.rendered, self.relaunched), ([self.project.resolve()], [self.project.resolve()], []))

    def test_a_heartbeat_no_conductor_holds_is_no_conductor_whatever_its_pid_names_now(self):
        """After a reboot the heartbeat's pid can name another process; the lock of the dead conductor is gone."""
        self.heartbeat = {"pid": os.getpid(), "started_at": ts(NOW - HOUR), "last_wave_at": ts(NOW - 60), "harness_tag": "v0.0.0"}
        result = self.run_tick()
        self.assertEqual((result.ended, result.relaunched), (tick.RELAUNCHED, True))
        self.assertEqual(self.relaunched, [self.project.resolve()])
        self.assertIn("1 ticket(s) on the frontier", result.why)
        self.assertEqual(self.polled, [self.project.resolve()])

    def test_the_real_heartbeat_lock_answers_by_default(self):
        self.assertIs(tick.Machine().conductor, tick.conductor_holder)
        result = self.run_tick(conductor=tick.conductor_holder)
        self.assertTrue(result.relaunched)


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

    def test_a_stop_no_conductor_took_is_not_dropped_by_a_relaunch(self):
        self.ran()
        self.add_ticket(1)
        project.control(self.project, "stop", {"drain": False})
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("a stop (by cli) waits for a conductor", result.why)

    def test_a_project_switched_away_from_is_not_relaunched(self):
        self.ran()
        self.add_ticket(1)
        self.journal("switched", {"from": str(self.project.resolve()), "to": str(self.temp / "other")})
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("switched away from", result.why)

    def test_a_run_killed_mid_run_with_a_ticket_running_is_relaunched(self):
        self.ran()
        self.add_ticket(1, status="running")
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("1 ticket(s) running", result.why)

    def test_a_human_only_decision_ticket_is_not_work(self):
        self.ran(ended="frontier_empty", autonomy="autonomous")
        self.add_ticket(1, kind="decision", human_only=True)
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_a_decision_ticket_a_session_may_take_is_work(self):
        """Under `autonomous` the decider takes a decision ticket that is not human-only, so it is work to relaunch for."""
        self.ran(ended="frontier_empty", autonomy="autonomous")
        open_objective(self.project)
        project.set_autonomy(self.project, "autonomous")
        self.add_ticket(1, kind="decision")
        with mock.patch.object(decisions, "decider_ready", return_value=True):
            self.assertTrue(self.run_tick().relaunched)

    def test_without_a_decider_role_a_decision_ticket_is_not_work_even_under_autonomous(self):
        self.ran(ended="frontier_empty", autonomy="autonomous")
        open_objective(self.project)
        project.set_autonomy(self.project, "autonomous")
        self.add_ticket(1, kind="decision")
        with mock.patch.object(decisions, "decider_ready", return_value=False):
            result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_under_checkpoints_every_decision_ticket_waits_for_the_owner_and_is_not_work(self):
        """The relaunched run starts from `harness.json`'s autonomy, under which the owner answers every decision ticket (ticket 35)."""
        self.ran(ended="frontier_empty")
        self.add_ticket(1, kind="decision")
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_a_pending_job_file_is_not_work_on_its_own(self):
        """Nothing launches a pending job of a ticket that no longer runs, so a relaunch would only end at its first wave."""
        self.ran(ended="frontier_empty")
        self.add_ticket(1, status="done")
        spec = resources.JobSpec(id="j-0003", ticket=1, command=("python3", "train.py"), cwd=str(self.project),
                                 log=str(self.project / "results" / "logs" / "j-0003.log"))
        resources.JobRunner(self.project, backend=resources.FAKE_JOBS).write(
            resources.job_record(spec, backend=resources.FakeJobs.name, unit=resources.unit_name("j-0003"), status="pending"))
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_a_running_job_is_polled_and_its_outputs_are_checked_once_it_exited(self):
        self.ran()
        self.add_ticket(1, status="running")
        with resources.use_fake_jobs() as jobs:
            self.launch_job(jobs, "j-0001", outputs=("results/metrics.json", "results/table.csv"), states=("running", "exited"),
                            written={"results/metrics.json": '{"auroc": 0.81}', "results/table.csv": "seed,auroc\n1,0.81\n"})
            first = self.run_tick(poll_jobs=tick.poll_jobs)
            second = self.run_tick(poll_jobs=tick.poll_jobs)
        self.assertEqual(first.jobs, [{"job": "j-0001", "ticket": 1, "was": "running", "now": "running", "error": None}])
        self.assertEqual(first.checks, [])
        self.assertIn("1 ticket(s) running with 1 job(s) live", first.why)
        self.assertEqual(second.jobs, [{"job": "j-0001", "ticket": 1, "was": "running", "now": "exited", "error": None}])
        self.assertEqual(second.checks, [{"job": "j-0001", "ticket": 1, "outputs_ok": True, "problems": []}])

    def test_a_job_that_cannot_be_polled_does_not_keep_the_next_one_unpolled(self):
        self.ran()
        self.add_ticket(1, status="running")
        with resources.use_fake_jobs() as jobs:
            self.launch_job(jobs, "j-0001")
            self.launch_job(jobs, "j-0002")
            with mock.patch.object(resources.JobRunner, "poll",
                                   side_effect=[resources.JobError("no LoadState"), resources.JobState("running")]):
                result = self.run_tick(poll_jobs=tick.poll_jobs)
        self.assertEqual([(job["job"], job["now"]) for job in result.jobs], [("j-0001", None), ("j-0002", "running")])
        self.assertIn("no LoadState", result.jobs[0]["error"])
        self.assertEqual(result.problems, ["jobs: j-0001: JobError: no LoadState"])
        self.assertTrue(result.relaunched)

    def test_an_output_that_does_not_parse_fails_the_check(self):
        self.ran()
        self.add_ticket(1, status="running")
        with resources.use_fake_jobs() as jobs:
            self.launch_job(jobs, "j-0002", outputs=("results/metrics.json", "results/missing.csv"), states=("exited",),
                            written={"results/metrics.json": "auroc=0.81"})
            result = self.run_tick(poll_jobs=tick.poll_jobs)
        [check] = result.checks
        self.assertFalse(check["outputs_ok"])
        self.assertEqual([problem.split(" ")[0] for problem in check["problems"]], ["results/metrics.json", "results/missing.csv"])
        self.assertIn("does not parse", check["problems"][0])
        self.assertIn("is missing", check["problems"][1])


class AnswerTest(TickCase):
    def test_an_answer_after_the_run_ended_relaunches_even_a_stopped_run_with_the_window_closed(self):
        self.ran(ended="stopped")
        self.add_ticket(2, kind="decision", human_only=True)
        self.answered(2)
        self.fake.usage_text = usage_text(95, 95)
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("a decision ticket was answered", result.why)

    def test_an_answer_after_a_pause_relaunches(self):
        self.ran()
        self.journal("paused", {"resets_at": pacing.iso(NOW + HOUR), "window": "five_hour", "utilization": 1.0})
        self.add_ticket(2, kind="decision", human_only=True)
        self.answered(2)
        self.assertTrue(self.run_tick().relaunched)

    def test_an_answer_after_a_stop_no_conductor_took_relaunches(self):
        self.ran()
        project.control(self.project, "stop", {"drain": False})
        self.add_ticket(2, kind="decision", human_only=True)
        self.answered(2)
        self.assertTrue(self.run_tick().relaunched)

    def test_an_answer_written_into_the_ticket_file_is_journaled_as_the_owner_s_and_relaunches(self):
        self.ran(ended="stopped")
        self.add_ticket(2, kind="decision", human_only=True, answer="the held-out split")
        result = self.run_tick()
        self.assertEqual(result.answers, [2])
        self.assertEqual(self.events("decision")[-1]["payload"], {"ticket": 2, "answer": "the held-out split", "decided_by": "human",
                                                                 "rationale": None, "confidence": None})
        self.assertTrue(result.relaunched)
        self.run_tick()
        self.assertEqual(len(self.events("decision")), 1)

    def test_an_answer_the_last_run_already_took_does_not(self):
        self.ran()
        self.add_ticket(2, kind="decision", human_only=True, status="done")
        self.answered(2)
        self.journal("run_ended", {"reason": "frontier_empty"})
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_an_answer_a_run_started_after_and_was_killed_in_does_not(self):
        self.ran()
        self.add_ticket(2, kind="decision", human_only=True, status="done")
        self.answered(2)
        self.ran()  # took the answer at its first wave, then was killed without an end
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("no work remains", result.why)

    def test_a_decision_that_names_no_ticket_answers_nothing(self):
        self.ran(ended="goal_reached")
        self.journal("decision", {"ticket": None, "answer": "auroc up to 0.9", "decided_by": "human", "rationale": None, "confidence": None})
        result = self.run_tick()
        self.assertFalse(result.relaunched)
        self.assertIn("ended goal_reached", result.why)


class FableVerdictTest(TickCase):
    """A verdict queue that waits only on Fable counts as work once Fable's weekly window has reset (decision 15)."""

    def setUp(self):
        super().setUp()
        self.ran()  # a conductor killed while its verdicts waited
        on_fable(self.project, "verifier.opus")
        self.add_ticket(1, status="done", difficulty=3)
        self.done_on(1, "opus")  # a difficulty-3 diff read on an Opus author goes to the Fable verifier the project gives it
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

    def test_under_auto_a_queue_waiting_only_on_fable_is_work_while_the_hold_stands(self):
        """Ticket 56: under the fallback consent `auto` a conductor takes those verdicts on Opus, so they wait on nothing."""
        project.set_model_fallback(self.project, "auto")
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("1 ticket(s) owed a verdict", result.why)

    def test_under_wait_and_ask_the_queue_still_waits(self):
        for consent in ("wait", "ask"):
            with self.subTest(consent=consent):
                project.set_model_fallback(self.project, consent)
                result = self.run_tick()
                self.assertFalse(result.relaunched)
                self.assertIn("1 ticket(s) wait for a verdict on Fable", result.why)

    def test_a_verdict_that_does_not_run_on_fable_is_work_while_the_hold_stands(self):
        self.add_ticket(2, status="done", difficulty=2, quality=["the file says hello"])
        self.done_on(2, "sonnet")  # a Sonnet author's quality verdict goes to Opus
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("2 ticket(s) owed a verdict", result.why)

    def test_a_ticket_whose_verdicts_all_passed_is_owed_its_acceptance_which_needs_no_fable(self):
        self.journal("verdict", {"subject_kind": "ticket", "subject": "tickets/01-ticket-1.md", "verdict_type": "diff",
                                 "pass": True, "session_id": "s", "model": "fable", "findings": []}, ticket=1)
        result = self.run_tick()
        self.assertTrue(result.relaunched)
        self.assertIn("1 ticket(s) owed their acceptance", result.why)


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

    def test_a_decision_answered_before_a_conductor_closed_it_is_not_sent(self):
        self.ran()
        self.add_ticket(2, kind="decision")
        self.journal("decision_opened", {"ticket": 2, "blocking": None, "human_only": False}, ticket=2)
        project.answer(self.project, 2, "the held-out split")
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

    def test_a_refused_relaunch_is_a_problem_and_the_owner_is_told_once(self):
        self.ran()
        self.add_ticket(1)
        self.refusal = tick.UnitsOff("WAYLINE_UNITS=none: this process does not reach the user manager")
        result = self.run_tick()
        self.assertEqual((result.ended, result.relaunched), (tick.NOT_RELAUNCHED, False))
        self.assertIn("WAYLINE_UNITS=none", result.why)
        self.assertEqual(len(result.problems), 1)
        self.assertEqual([(event, ticket) for event, ticket, _ in self.sent], [("relaunch_refused", None)])
        self.assertIn("did not relaunch the conductor although 1 ticket(s) on the frontier", self.sent[0][2])
        self.now += 15 * 60
        self.run_tick()
        self.assertEqual(len(self.sent), 1)


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
