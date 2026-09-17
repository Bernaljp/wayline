"""The dashboard's actions and its decisions view, over HTTP (ticket 35; Implementation Decisions 8).

Every test starts a real `DashboardServer` on a free loopback port, with a token, over a laid-out
copy of `fixtures/projects/decision-branch/`, and talks to it with `http.client`, as
`tests.test_dashboard` does. An action calls the function its verb calls, and those functions have
tests of their own (`tests.test_decisions`); what is asserted here is that each route reaches its
function with `by: dashboard`, takes the token from the header and from nowhere else, refuses what
it must with a status that says why, and runs no shell. A test that waits for the switch thread
polls for its effect with a deadline, which is waiting on the system under test.
"""

import http.client
import io
import json
import shutil
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_dashboard import Response
from wayline import dashboard, intake, project, replay, tickets
from wayline.dashboard import (
    ACTIONS, FILENAME_HEADER, JSON_BODY_MAX, LOOPBACK, TOKEN_COOKIE, TOKEN_HEADER, dashboard_path, dashboard_url, is_terminal,
    make_server, serve_lines,
)
from wayline.ledger import Ledger

BRANCH = HARNESS_ROOT / "fixtures" / "projects" / "decision-branch"
STATIC = HARNESS_ROOT / "dashboard"
TOKEN = "a-token-with-enough-entropy-to-stand-in"
_THE_TOKEN = object()


def until(predicate, timeout=10.0):
    """Whether `predicate()` came true within `timeout` seconds, looking every 20 ms."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class ActionCase(ProjectTestCase):
    """A dashboard with a token, serving a laid-out copy of the decision-branch project on a free loopback port."""

    token = TOKEN
    require_token = False

    def setUp(self):
        super().setUp()
        self.project = self.lay_out("decision-branch")
        self.ledger = Ledger(self.project)
        self.server = make_server(LOOPBACK, 0, token=self.token, require_token=self.require_token, static_root=STATIC,
                                  memo_ttl=0.0, readings_ttl_s=3600)
        # Cleanups run last in first out, so these read backwards: shutdown, then join, then close.
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)
        thread.start()
        self.host, self.port = self.server.server_address[:2]

    def lay_out(self, name):
        target = (self.temp / name).resolve()
        shutil.copytree(BRANCH, target)
        project.init_project(target, git=False, hermes_python=None, owner_email=None)
        return target

    def request(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            return Response(connection.getresponse())
        finally:
            connection.close()

    def act(self, name, body=None, token=_THE_TOKEN, headers=None, raw=None, project_id=None, query=""):
        sent = dict(headers or {})
        token = self.token if token is _THE_TOKEN else token
        if token is not None:
            sent[TOKEN_HEADER] = token
        data = raw if raw is not None else json.dumps({} if body is None else body).encode("utf-8")
        return self.request("POST", "/api/projects/%s/actions/%s%s" % (project_id or self.project.name, name, query), data, sent)

    def events(self, name=None, of=None):
        found, _ = Ledger(of or self.project).read_events()
        return [event for event in found if name is None or event["event"] == name]

    def body(self, identifier):
        fields = {ticket["id"]: ticket for ticket in tickets.read_tickets(self.project)}[identifier]
        return tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]


# --- the token ----------------------------------------------------------------------------------------------


class ActionTokenTest(ActionCase):
    """An action takes the token from its header and from nowhere else, on every bind."""

    def test_every_action_is_refused_without_the_token_header_and_leaves_the_ledger_as_it_was(self):
        journal, harness = self.ledger.journal_path.read_bytes(), (self.project / "harness.json").read_bytes()
        for name in ACTIONS:
            with self.subTest(action=name):
                response = self.act(name, token=None)
                self.assertEqual(response.status, 403)
                self.assertEqual((response.json["ok"], response.json["action"]), (False, name))
                self.assertIn(TOKEN_HEADER, response.json["error"])
        self.assertEqual((self.ledger.journal_path.read_bytes(), (self.project / "harness.json").read_bytes()), (journal, harness))

    def test_neither_the_token_in_the_url_nor_the_token_cookie_stands_in_for_the_header(self):
        self.assertEqual(self.act("pause", token=None, query="?token=%s" % TOKEN).status, 403)
        self.assertEqual(self.act("pause", token=None, headers={"Cookie": "%s=%s" % (TOKEN_COOKIE, TOKEN)}).status, 403)
        self.assertEqual(self.events("control"), [])

    def test_a_wrong_token_is_refused_and_the_right_one_acts(self):
        self.assertEqual(self.act("pause", token="wrong").status, 403)
        response = self.act("pause")
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(response.json["control"], {"command": "pause", "args": {}, "by": "dashboard"})

    def test_an_action_asked_with_get_is_405_and_an_unknown_action_or_path_404(self):
        asked = self.request("GET", "/api/projects/%s/actions/pause" % self.project.name)
        self.assertEqual((asked.status, asked.headers.get("allow")), (405, "POST"))
        self.assertEqual(self.act("launch").status, 404)
        self.assertEqual(self.request("POST", "/api/projects/%s/elsewhere" % self.project.name, b"{}", {TOKEN_HEADER: TOKEN}).status, 404)
        self.assertEqual(self.events("control"), [])

    def test_an_unknown_project_is_a_bad_request(self):
        response = self.act("pause", project_id="nowhere")
        self.assertEqual(response.status, 400)
        self.assertIn("no registered project", response.json["error"])


class TokenlessServerTest(ActionCase):
    token = None

    def test_a_server_started_without_a_token_acts_for_no_one(self):
        for offered in ("anything", ""):
            with self.subTest(offered=offered):
                self.assertEqual(self.act("pause", token=offered).status, 403)
        self.assertEqual(self.events("control"), [])


class WideBindTest(ActionCase):
    require_token = True

    def test_the_header_is_also_the_token_every_request_needs_on_a_wide_bind(self):
        self.assertEqual(self.act("pause").status, 200)
        self.assertEqual(self.act("pause", token=None).status, 403)


class ActionBodyTest(ActionCase):
    def test_a_body_that_is_not_a_json_object_is_refused(self):
        for raw in (b"not json", b"[1, 2]", b'"pause"', b"\xff\xfe"):
            with self.subTest(raw=raw):
                response = self.act("pause", raw=raw)
                self.assertEqual(response.status, 400)
                self.assertIn("JSON object", response.json["error"])

    def test_a_field_the_action_does_not_take_is_refused(self):
        response = self.act("pause", {"why": "lunch"})
        self.assertEqual(response.status, 400)
        self.assertIn("does not take why", response.json["error"])

    def test_a_body_over_the_cap_is_413(self):
        response = self.act("pause", raw=b" " * (JSON_BODY_MAX + 1))
        self.assertEqual(response.status, 413)

    def test_a_chunked_body_is_411(self):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.putrequest("POST", "/api/projects/%s/actions/pause" % self.project.name)
            connection.putheader(TOKEN_HEADER, TOKEN)
            connection.putheader("Transfer-Encoding", "chunked")
            connection.endheaders()
            connection.send(b"2\r\n{}\r\n0\r\n\r\n")
            response = Response(connection.getresponse())
        finally:
            connection.close()
        self.assertEqual(response.status, 411)
        self.assertEqual(self.events("control"), [])


# --- each action ---------------------------------------------------------------------------------------------


class AnswerActionTest(ActionCase):
    def test_the_answer_form_answers_through_the_verb_s_function(self):
        response = self.act("answer", {"ticket": 2, "answer": "one line", "rationale": "a glance"})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual((response.json["ok"], response.json["action"], response.json["conductor"]), (True, "answer", None))
        self.assertEqual(response.json["decision"],
                         {"ticket": 2, "answer": "one line", "decided_by": "human", "rationale": "a glance", "confidence": None})
        self.assertEqual(tickets.answer_section(self.body(2)), "one line")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_a_second_answer_a_code_ticket_and_a_missing_or_mistyped_field_are_refused(self):
        self.act("answer", {"ticket": 2, "answer": "one line"})
        refusals = (({"ticket": 2, "answer": "a table"}, "answered already"), ({"ticket": 1, "answer": "x"}, "only a decision ticket"),
                    ({"ticket": 2}, "needs answer"), ({"ticket": "2", "answer": "x"}, "whole number"),
                    ({"ticket": 2, "answer": 7}, "answer is a string"), ({"ticket": 2, "answer": "x", "confidence": 3}, "confidence"))
        for body, message in refusals:
            with self.subTest(body=body):
                response = self.act("answer", body)
                self.assertEqual(response.status, 400)
                self.assertIn(message, response.json["error"])
        self.assertEqual(len(self.events("decision")), 1)


class AutonomyActionTest(ActionCase):
    def test_raising_writes_harness_json_and_journals_the_control(self):
        response = self.act("autonomy", {"autonomy": "autonomous"})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual((response.json["from"], response.json["to"], response.json["changed"]), ("checkpoints", "autonomous", True))
        self.assertEqual(project.read_harness(self.project)["autonomy"], "autonomous")
        self.assertEqual(self.events("control")[-1]["payload"], {"command": "autonomy", "args": {"autonomy": "autonomous"}, "by": "dashboard"})

    def test_lowering_while_a_conductor_holds_the_project_is_refused(self):
        self.act("autonomy", {"autonomy": "autonomous"})
        heartbeat = self.ledger.heartbeat().acquire()
        try:
            response = self.act("autonomy", {"autonomy": "checkpoints"})
        finally:
            heartbeat.release()
        self.assertEqual(response.status, 400)
        self.assertIn("lowered only while no conductor is running", response.json["error"])
        self.assertEqual(project.read_harness(self.project)["autonomy"], "autonomous")

    def test_a_level_that_is_not_one_is_refused(self):
        self.assertEqual(self.act("autonomy", {"autonomy": "wild"}).status, 400)
        self.assertEqual(self.act("autonomy", {"autonomy": 3}).status, 400)


class PauseResumeActionTest(ActionCase):
    def test_pause_and_resume_journal_their_controls_and_the_decisions_view_follows(self):
        for name, paused in (("pause", True), ("resume", False)):
            with self.subTest(action=name):
                response = self.act(name)
                self.assertEqual(response.json["control"], {"command": name, "args": {}, "by": "dashboard"})
                events, _ = self.ledger.read_events()
                self.assertEqual(replay.replay(events).paused_by_owner, paused)
                view = self.request("GET", "/api/projects/%s/decisions" % self.project.name).json
                self.assertEqual(view["controls"]["paused_by_owner"], paused)


class CancelRerunActionTest(ActionCase):
    def test_cancel_and_rerun_journal_their_control_for_the_ticket(self):
        for name in ("cancel", "rerun"):
            with self.subTest(action=name):
                response = self.act(name, {"ticket": 3})
                self.assertEqual(response.status, 200, response.text)
                self.assertEqual(response.json["control"], {"command": name, "args": {"ticket": 3}, "by": "dashboard"})
                self.assertEqual(self.events("control")[-1]["ticket"], 3)

    def test_a_ticket_the_project_does_not_have_is_refused(self):
        response = self.act("cancel", {"ticket": 99})
        self.assertEqual(response.status, 400)
        self.assertIn("has no ticket 99", response.json["error"])
        self.assertEqual(self.act("rerun", {}).status, 400)
        self.assertEqual(self.events("control"), [])


class PacingActionTest(ActionCase):
    def test_the_thresholds_are_written_and_journaled(self):
        response = self.act("pacing", {"stop_at": 0.95, "cheap_at": 0.85})
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual(response.json["to"], {"stop_at": 0.95, "cheap_at": 0.85})
        self.assertEqual(project.read_harness(self.project)["pacing"], {"stop_at": 0.95, "cheap_at": 0.85})
        self.assertEqual(self.events("control")[-1]["payload"],
                         {"command": "pacing", "args": {"stop_at": 0.95, "cheap_at": 0.85}, "by": "dashboard"})

    def test_a_cheap_threshold_above_the_stop_and_no_threshold_at_all_are_refused(self):
        for body, message in (({"cheap_at": 0.95}, "above stop_at"), ({}, "give stop_at"), ({"stop_at": "high"}, "fraction")):
            with self.subTest(body=body):
                response = self.act("pacing", body)
                self.assertEqual(response.status, 400)
                self.assertIn(message, response.json["error"])
        self.assertEqual(self.events("control"), [])


class SwitchActionTest(ActionCase):
    def setUp(self):
        super().setUp()
        self.other = self.lay_out("other")
        project.set_active(self.project)

    def test_a_switch_with_no_conductor_to_drain_moves_the_pointer_before_the_reply(self):
        response = self.act("switch", project_id="other")
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual((response.json["moved"], response.json["draining"]), (True, None))
        self.assertEqual(project.read_active().resolve(), self.other)
        for where in (self.project, self.other):
            self.assertEqual(self.events("switched", of=where)[-1]["payload"], {"from": str(self.project), "to": str(self.other)})

    def test_a_switch_to_the_active_project_changes_nothing(self):
        response = self.act("switch")
        self.assertEqual((response.status, response.json["moved"]), (200, False))

    def test_a_conductor_to_drain_is_asked_to_stop_and_the_switch_finishes_once_it_has_ended(self):
        heartbeat = self.ledger.heartbeat().acquire()
        released = False
        try:
            with mock.patch.object(project, "DRAIN_POLL_S", 0.05):
                response = self.act("switch", project_id="other")
                self.assertEqual(response.status, 202, response.text)
                self.assertIsNotNone(response.json["draining"])
                self.assertEqual(response.json["to"], str(self.other))
                again = self.act("switch", project_id="other")
                self.assertEqual(again.status, 409)
                self.assertIn("already waiting", again.json["error"])
                self.assertTrue(until(lambda: self.events("control")))
                self.assertEqual(self.events("control")[-1]["payload"],
                                 {"command": "stop", "args": {"drain": True, "switch_to": str(self.other)}, "by": "dashboard"})
                self.assertEqual(project.read_active().resolve(), self.project, "the pointer waits for the drain")
                heartbeat.release()
                released = True
                self.assertTrue(until(lambda: project.read_active().resolve() == self.other))
        finally:
            if not released:
                heartbeat.release()
        self.assertTrue(until(lambda: self.server.switching.acquire(blocking=False)))
        self.server.switching.release()

    def test_a_conductor_that_starts_after_the_check_turns_the_switch_into_a_202_rather_than_holding_the_request(self):
        """Found by the review: a switch that met a conductor after it had looked for one held the request for the whole drain."""
        release = threading.Event()

        def draining_switch(target, by="cli", wait=None):
            release.wait(60)
            return project.switch_project(target, by=by)

        with mock.patch.object(dashboard, "switch_project", draining_switch), mock.patch.object(dashboard, "SWITCH_REPLY_S", 0.2):
            response = self.act("switch", project_id="other")
            self.assertEqual(response.status, 202, response.text)
            self.assertIsNone(response.json["draining"])
            self.assertEqual(self.act("switch", project_id="other").status, 409)
            self.assertEqual(project.read_active().resolve(), self.project)
            release.set()
            self.assertTrue(until(lambda: project.read_active().resolve() == self.other))
        self.assertTrue(until(lambda: self.server.switching.acquire(blocking=False)))
        self.server.switching.release()


class IntakeActionTest(ActionCase):
    def drop(self, name, data, headers=None):
        sent = {FILENAME_HEADER: quote(name), "Content-Type": "application/octet-stream"} if headers is None else headers
        return self.act("intake", raw=data, headers=sent)

    def test_a_dropped_reference_list_is_kept_and_added_to_the_intake(self):
        data = b"- 10.1234/wayline.drop.one\n- arXiv:2401.00002\n"
        response = self.drop("refs.md", data)
        self.assertEqual(response.status, 200, response.text)
        self.assertEqual({key: response.json[key] for key in ("path", "size", "already", "taken")},
                         {"path": "research/intake/refs.md", "size": len(data), "already": False, "taken": ["References"]})
        self.assertEqual((self.project / "research" / "intake" / "refs.md").read_bytes(), data)
        references = tickets.section((self.project / "research" / "INTAKE.md").read_text(encoding="utf-8"), "## References")
        self.assertIn("- 10.1234/wayline.drop.one", references)
        self.assertIn("- arXiv:2401.00002", references)

    def test_a_name_that_is_not_a_plain_file_name_an_empty_file_and_a_missing_name_are_refused(self):
        for name in ("../escape.md", ".hidden", "a/b.md"):
            with self.subTest(name=name):
                response = self.drop(name, b"text")
                self.assertEqual(response.status, 400)
                self.assertIn("plain file name", response.json["error"])
        self.assertIn("empty", self.drop("empty.md", b"").json["error"])
        self.assertIn(FILENAME_HEADER, self.drop("unnamed.md", b"text", headers={}).json["error"])
        self.assertFalse((self.project / "research" / "intake").exists())

    def test_a_file_over_the_drop_s_cap_is_413(self):
        with mock.patch.object(intake, "DROP_MAX_BYTES", 8):
            self.assertEqual(self.drop("big.md", b"123456789").status, 413)
        self.assertFalse((self.project / "research" / "intake").exists())


class DecisionsEndpointTest(ActionCase):
    def decisions(self, headers=None):
        return self.request("GET", "/api/projects/%s/decisions" % self.project.name, headers=headers)

    def test_it_serves_the_open_decisions_the_log_and_the_controls_without_a_token_on_loopback(self):
        response = self.decisions()
        self.assertEqual(response.status, 200)
        view = response.json
        self.assertEqual([(entry["id"], entry["options"], entry["pauses"]) for entry in view["open"]], [(2, ["one line", "a table"], [3, 5])])
        self.assertEqual(len(view["open"][0]["evidence"]), 2)
        self.assertEqual((view["log"], view["controls"]["autonomy"], view["controls"]["active"]), ([], "checkpoints", True))

    def test_an_unchanged_ledger_answers_304_and_an_answer_moves_the_tag(self):
        first = self.decisions()
        self.assertEqual(self.decisions({"If-None-Match": first.etag}).status, 304)
        self.act("answer", {"ticket": 2, "answer": "one line"})
        after = self.decisions({"If-None-Match": first.etag})
        self.assertEqual(after.status, 200)
        self.assertEqual(after.json["open"][0]["answered"], {"answer": "one line", "decided_by": "human"})
        self.assertEqual([(entry["ticket"], entry["decided_by"]) for entry in after.json["log"]], [(2, "human")])


class NoShellTest(ActionCase):
    """Criterion 3: every action calls a function in this process, and no action starts a shell."""

    def test_no_action_runs_a_shell(self):
        self.lay_out("other")
        project.set_active(self.project)
        started = []
        real = subprocess.Popen

        class Watched(real):
            def __init__(self, args, *rest, **options):
                started.append((args, bool(options.get("shell"))))
                super().__init__(args, *rest, **options)

        steps = [("answer", {"ticket": 2, "answer": "one line"}), ("autonomy", {"autonomy": "autonomous"}), ("pause", {}), ("resume", {}),
                 ("cancel", {"ticket": 3}), ("rerun", {"ticket": 3}), ("pacing", {"stop_at": 0.95}), ("model_fallback", {"model_fallback": "wait"}),
                 ("ladder_changes", {"ladder_changes": "auto"})]
        with mock.patch.object(subprocess, "Popen", Watched):
            for name, body in steps:
                with self.subTest(action=name):
                    self.assertEqual(self.act(name, body).status, 200)
            dropped = self.act("intake", raw=b"Try the interaction term first.\n", headers={FILENAME_HEADER: "plan.md"})
            self.assertEqual(dropped.status, 200, dropped.text)
            self.assertEqual(self.act("switch", project_id="other").status, 200)
        shells = [args for args, shell in started
                  if shell or (isinstance(args, (list, tuple)) and Path(str(args[0])).name in ("sh", "bash", "dash", "zsh"))]
        self.assertEqual(shells, [])


class PrintedTokenTest(ProjectTestCase):
    """Found by the review: the URL that carries the token went to the user journal through `wayline-dashboard.service`."""

    SETTINGS = {"port": 8765, "bind": LOOPBACK, "token": "secret", "poll_journal_s": 2, "poll_views_s": 5}

    def test_output_that_is_not_a_terminal_prints_the_url_without_the_token_and_says_where_it_is(self):
        text = "\n".join(serve_lines(self.SETTINGS, {"projects": []}, workstation="box", with_token=False))
        self.assertNotIn("secret", text)
        self.assertIn("http://127.0.0.1:8765/", text)
        self.assertIn(str(dashboard_path()), text)
        self.assertEqual(dashboard_url(self.SETTINGS, with_token=False), "http://127.0.0.1:8765/")

    def test_a_terminal_is_told_apart_from_a_string_and_a_file(self):
        self.assertFalse(is_terminal(io.StringIO()))
        with open(self.temp / "out.txt", "w", encoding="utf-8") as handle:
            self.assertFalse(is_terminal(handle))


class PageTest(unittest.TestCase):
    """Criterion 4: the page carries the decisions view and every control, and sends each action with the token in its header."""

    def test_the_page_carries_the_decisions_view_and_every_control(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        for element in ("decisions-open", "decisions-log", "autonomy-form", "autonomy-select", "pacing-form", "stop-at", "cheap-at",
                        "switch-button", "pause-button", "resume-button", "intake-drop", "intake-file", "action-note"):
            with self.subTest(element=element):
                self.assertIn('id="%s"' % element, page)
        self.assertEqual(page.count('step="any"'), 2, "a threshold off the 0.01 grid must not block the pacing form")

    def test_the_script_takes_every_action_and_sends_the_token_in_the_header(self):
        script = (STATIC / "app.js").read_text(encoding="utf-8")
        for name in ACTIONS:
            with self.subTest(action=name):
                self.assertIn("'%s'" % name, script)
        self.assertIn("'X-Wayline-Token': TOKEN", script)
        self.assertIn("projectPath('/decisions')", script)
        self.assertIn("'X-Wayline-Filename': encodeURIComponent(file.name)", script)
