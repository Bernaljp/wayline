"""The read-only dashboard, over HTTP against the fixture ledger (Testing Decisions, seam 3).

Every test starts a real `DashboardServer` on a free loopback port and talks to it with
`http.client`, because the response is the thing this module owns: the status, the headers, the
ETag, the 304, and the bytes. Nothing here sleeps: the tail is driven by appending to the journal
through the ledger, and the server-sent-events tests read a socket with a deadline, which is
waiting on the system under test rather than on the clock.
"""

import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import threading
import unittest
import xml.etree.ElementTree as ET
import zipfile
from http.cookies import SimpleCookie
from pathlib import Path

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import TAG
from wayline.dashboard import (
    DashboardError, DashboardHandler, IDLE_TIMEOUT_S, LOOPBACK, READINGS_TTL_S, SSE_RETRY_MS,
    TOKEN_COOKIE, TOKEN_HEADER, TAIL_LINES_MAX,
    byte_range, dashboard_path, dashboard_url, download_target, etag, graph_svg, journal_tail,
    ledger_snapshot, log_path, log_tail, make_server, outputs_view, overview_view,
    phase_from_events, project_ids, projects_view, read_settings, record_settings,
    requires_token, serve_lines, static_file, ticket_view, tickets_view, tunnel_line,
)
from wayline.ledger import Ledger
from wayline.project import home, register, set_active
from wayline.provenance import sha256_of
from wayline.tickets import GRAPH, frontier, read_tickets, refresh_graph

STATIC = HARNESS_ROOT / "dashboard"

# The pins of `dashboard/vendor/VENDOR.md`; an upgrade edits that table and this tuple together.
VENDORED = (
    ("marked.umd.js", 44870, "fa0cfbf0181339312eaa3709b577ad698fc21a9baa42d580a3fd1f267b19b4a8"),
    ("purify.min.js", 29369, "f263b05369e050fa175d4ecb9c9358eb4253602d510297adfb31df48b2f1c4d5"),
)


class Response:
    """One HTTP response, unpacked into what the tests assert on."""

    def __init__(self, raw):
        self.status = raw.status
        self.headers = {name.lower(): value for name, value in raw.getheaders()}
        self.body = raw.read()

    @property
    def text(self):
        return self.body.decode("utf-8")

    @property
    def json(self):
        return json.loads(self.text)

    @property
    def etag(self):
        return self.headers.get("etag")


class DashboardTestCase(ProjectTestCase):
    """A dashboard serving one registered copy of `fixtures/ledger/` on a free loopback port."""

    require_token = False
    bind = LOOPBACK
    token = None
    sse_tick_s = 0.02
    # A long readings window, so a 304 in a test means "nothing changed" rather than "the machine's
    # loadavg happened to hold still"; `ReadingsFreshnessTest` is the one that sets it to zero.
    readings_ttl_s = 3600

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        register(self.project, TAG)
        set_active(self.project)
        self.ledger = Ledger(self.project)
        self.server = self.make()
        # Cleanups run last in first out, so these read backwards: shutdown, then join, then close.
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.thread.start()
        self.host, self.port = self.server.server_address[:2]
        self.project_id = self.project.name

    def make(self):
        """The server under test; a subclass overrides this to change how it is built."""
        return make_server(
            self.bind, 0, token=self.token, require_token=self.require_token, static_root=STATIC,
            sse_tick_s=self.sse_tick_s, memo_ttl=0.0, readings_ttl_s=self.readings_ttl_s,
        )

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request("GET", path, headers=headers or {})
            return Response(connection.getresponse())
        finally:
            connection.close()

    def api(self, suffix, headers=None):
        return self.get("/api/projects/%s%s" % (self.project_id, suffix), headers=headers)

    def append(self, event="unpaused", payload=None, **fields):
        return self.ledger.append_event(event, payload or {}, **fields)

    def journal_size(self):
        return (self.project / "research" / "journal.jsonl").stat().st_size


# --- the projects endpoint --------------------------------------------------------------------------


class ProjectsEndpointTest(DashboardTestCase):
    def test_it_lists_the_registered_project_with_the_active_one_marked(self):
        view = self.get("/api/projects").json
        self.assertEqual(view["harness_tag"], TAG)
        self.assertEqual(view["active"], self.project_id)
        self.assertEqual([project["id"] for project in view["projects"]], [self.project_id])
        entry = view["projects"][0]
        self.assertEqual(entry["path"], str(self.project))
        self.assertTrue(entry["active"])
        self.assertTrue(entry["readable"])

    def test_it_carries_the_poll_intervals_the_page_uses(self):
        settings = self.get("/api/projects").json["settings"]
        self.assertEqual(settings, {"poll_journal_s": 2, "poll_views_s": 5})

    def test_a_project_whose_directory_is_gone_stays_in_the_list_as_unreadable(self):
        register(self.temp / "removed", TAG)
        projects = {project["id"]: project for project in self.get("/api/projects").json["projects"]}
        self.assertFalse(projects["removed"]["readable"])
        self.assertTrue(projects[self.project_id]["readable"])

    def test_a_project_directory_that_disappears_moves_the_etag(self):
        second = self.temp / "second"
        shutil.copytree(self.project, second)
        register(second, TAG)
        first = self.get("/api/projects")
        self.assertTrue(all(project["readable"] for project in first.json["projects"]))
        shutil.rmtree(second)
        changed = self.get("/api/projects", {"If-None-Match": first.etag})
        self.assertEqual(changed.status, 200, "a tab whose path is gone has to reach the page")
        self.assertFalse({project["id"]: project["readable"] for project in changed.json["projects"]}["second"])

    def test_editing_the_poll_intervals_moves_the_etag(self):
        first = self.get("/api/projects")
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["dashboard"]["poll_journal_s"] = 4
        (self.project / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        changed = self.get("/api/projects", {"If-None-Match": first.etag})
        self.assertEqual(changed.status, 200)
        self.assertEqual(changed.json["settings"]["poll_journal_s"], 4)

    def test_an_unchanged_pointer_answers_304(self):
        first = self.get("/api/projects")
        self.assertEqual(first.status, 200)
        self.assertTrue(first.etag)
        again = self.get("/api/projects", {"If-None-Match": first.etag})
        self.assertEqual(again.status, 304)
        self.assertEqual(again.body, b"")
        self.assertEqual(again.etag, first.etag)

    def test_registering_another_project_changes_the_etag(self):
        first = self.get("/api/projects")
        register(self.temp / "another", TAG)
        again = self.get("/api/projects", {"If-None-Match": first.etag})
        self.assertEqual(again.status, 200)
        self.assertNotEqual(again.etag, first.etag)

    def test_two_projects_of_one_name_get_distinct_ids(self):
        first, second = self.temp / "a" / "toy", self.temp / "b" / "toy"
        ids = project_ids([{"path": str(first)}, {"path": str(second)}])
        self.assertEqual(len(set(ids.values())), 2)
        for value in ids.values():
            self.assertTrue(value.startswith("toy-"), value)

    def test_a_name_that_is_not_a_url_segment_is_replaced(self):
        ids = project_ids([{"path": "/tmp/a project/with space"}])
        self.assertRegex(next(iter(ids.values())), r"^with-space-[0-9a-f]{8}$")

    def test_an_entry_without_a_path_is_skipped_rather_than_raising(self):
        view = projects_view(active=None, entries=[{"name": "broken"}, "nonsense", {"path": "/tmp/x"}])
        self.assertEqual([project["id"] for project in view["projects"]], ["x"])


# --- the overview endpoint ----------------------------------------------------------------------------


class OverviewEndpointTest(DashboardTestCase):
    def test_it_carries_the_fields_decision_8_names(self):
        view = self.api("/overview").json
        for key in ("phase", "autonomy", "radius", "goal", "window", "resources", "running", "jobs", "frontier", "decisions", "counts", "events", "offset"):
            self.assertIn(key, view)
        self.assertEqual(view["id"], self.project_id)
        self.assertEqual(view["autonomy"], "checkpoints")
        self.assertEqual(view["radius"], "moderate")
        # The project's own pin, not the checkout's tag: the two differ from the moment a tag
        # moves until `wayline upgrade` is run, and the overview shows what the project pins.
        pinned = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))["harness_tag"]
        self.assertEqual(view["harness_tag"], pinned)
        self.assertEqual(view["offset"], self.journal_size())

    def test_the_last_events_are_the_tail_of_the_journal(self):
        view = self.api("/overview").json
        events, _ = self.ledger.read_events()
        self.assertEqual(view["events"], events[-10:])

    def test_it_names_the_running_tickets_the_jobs_and_the_open_decisions(self):
        view = self.api("/overview").json
        self.assertEqual([entry["id"] for entry in view["running"]], [3])
        self.assertEqual([job["id"] for job in view["jobs"]], ["j-0001"], "j-0002 has exited; only live jobs are shown")
        self.assertEqual([entry["id"] for entry in view["decisions"]], [10])
        self.assertTrue(view["frontier"])

    def test_the_phase_comes_from_the_journal(self):
        self.assertIsNone(self.api("/overview").json["phase"])
        self.append("phase", {"from": "P4", "to": "P5"})
        self.assertEqual(self.api("/overview").json["phase"], "P5")

    def test_phase_from_events_ignores_a_value_outside_the_phases(self):
        self.assertIsNone(phase_from_events([{"event": "phase", "payload": {"to": "P9"}}]))
        self.assertEqual(phase_from_events([{"event": "phase", "payload": {"to": "P1"}}, {"event": "unpaused", "payload": {}}]), "P1")

    def test_a_poll_never_writes_the_generated_graph(self):
        self.api("/overview")
        self.api("/overview")
        self.assertFalse((self.project / "research" / GRAPH).exists(), "the dashboard is a reader; graph.json is the conductor's")

    def test_an_unchanged_ledger_answers_304_and_a_changed_one_does_not(self):
        first = self.api("/overview")
        self.assertEqual(first.status, 200)
        self.assertEqual(self.api("/overview", {"If-None-Match": first.etag}).status, 304)
        self.append("unpaused")
        changed = self.api("/overview", {"If-None-Match": first.etag})
        self.assertEqual(changed.status, 200)
        self.assertNotEqual(changed.etag, first.etag)

    def test_the_shipped_readings_window_matches_the_views_poll_interval(self):
        policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(READINGS_TTL_S, policy["dashboard"]["poll_views_s"], "a reading is at most one poll old")

    def test_the_tag_covers_the_whole_view_and_not_only_the_ledger(self):
        """A value no ledger file's mtime reports must still move the tag.

        The overview carries the machine's live readings and whether this project is the active
        one, none of which the `os.scandir` snapshot sees. The active pointer is the one such value
        a test can move on purpose, and moving it must not leave the page on a 304 forever.
        """
        first = self.api("/overview")
        self.assertTrue(first.json["active"])
        snapshot = ledger_snapshot(self.project)
        set_active(self.temp / "elsewhere")
        self.assertEqual(ledger_snapshot(self.project), snapshot, "the ledger did not move")
        changed = self.api("/overview", {"If-None-Match": first.etag})
        self.assertEqual(changed.status, 200, "the view changed, so the tag had to")
        self.assertFalse(changed.json["active"])

    def test_the_live_readings_are_in_the_view(self):
        resources = self.api("/overview").json["resources"]
        if resources is None:
            self.skipTest("this machine cannot produce a resource reading")
        for key in ("cpu", "ram", "gpus", "reservation"):
            self.assertIn(key, resources)

    def test_a_broken_ticket_file_becomes_a_problem_and_not_a_failure(self):
        (self.project / "research" / "tickets" / "01-scaffold-the-analysis-package.md").write_text("not frontmatter\n", encoding="utf-8")
        view = self.api("/overview").json
        self.assertEqual(self.api("/overview").status, 200)
        self.assertTrue(view["problems"])

    def test_an_unknown_project_id_is_a_bad_request_that_says_where_the_ids_are(self):
        response = self.get("/api/projects/nosuch/overview")
        self.assertEqual(response.status, 400)
        self.assertIn("/api/projects", response.text)

    def test_a_registered_project_whose_directory_is_gone_is_a_bad_request(self):
        register(self.temp / "removed", TAG)
        self.assertEqual(self.get("/api/projects/removed/overview").status, 400)

    def test_overview_view_computes_its_own_id_when_it_is_called_directly(self):
        self.assertEqual(overview_view(self.project)["id"], self.project_id)


# --- the journal tail ----------------------------------------------------------------------------------


class ReadingsFreshnessTest(DashboardTestCase):
    """With no readings window, the overview refuses to answer 304 from a stale reading."""

    readings_ttl_s = 0

    def test_every_poll_is_answered_with_a_fresh_view(self):
        first = self.api("/overview")
        for _ in range(3):
            again = self.api("/overview", {"If-None-Match": first.etag})
            self.assertEqual(again.status, 200, "a live reading must never be served from a 304")
            self.assertNotEqual(again.etag, first.etag)


class JournalTailTest(DashboardTestCase):
    def test_since_zero_returns_the_whole_journal_and_the_next_offset(self):
        tail = self.api("/journal?since=0").json
        events, offset = self.ledger.read_events()
        self.assertEqual(tail["events"], events)
        self.assertEqual(tail["next"], offset)
        self.assertEqual(tail["size"], self.journal_size())
        self.assertFalse(tail["truncated"])

    def test_a_second_poll_receives_only_what_was_appended(self):
        first = self.api("/journal?since=0").json
        written = self.append("finding", {"id": "f-0002", "ticket": 3, "text": "one more", "provenance": [], "negative": False})
        tail = self.api("/journal?since=%d" % first["next"]).json
        self.assertEqual(tail["events"], [written])
        self.assertEqual(tail["next"], self.journal_size())
        self.assertEqual(tail["since"], first["next"])

    def test_a_poll_at_the_end_of_the_journal_returns_no_events(self):
        offset = self.api("/journal?since=0").json["next"]
        tail = self.api("/journal?since=%d" % offset).json
        self.assertEqual(tail["events"], [])
        self.assertEqual(tail["next"], offset)

    def test_an_unchanged_journal_answers_304(self):
        first = self.api("/journal?since=0")
        self.assertEqual(self.api("/journal?since=0", {"If-None-Match": first.etag}).status, 304)
        self.append("unpaused")
        self.assertEqual(self.api("/journal?since=0", {"If-None-Match": first.etag}).status, 200)

    def test_the_tag_of_one_offset_is_not_the_tag_of_another(self):
        first = self.api("/journal?since=0")
        other = self.api("/journal?since=%d" % first.json["next"], {"If-None-Match": first.etag})
        self.assertEqual(other.status, 200, "a tag belongs to the offset it was issued for")

    def test_an_offset_past_the_end_is_reported_and_read_from_zero(self):
        tail = self.api("/journal?since=%d" % (self.journal_size() + 10_000)).json
        self.assertTrue(tail["truncated"])
        self.assertEqual(tail["since"], 0)
        self.assertEqual(len(tail["events"]), len(self.ledger.read_events()[0]))

    def test_an_offset_that_is_not_a_byte_count_is_a_bad_request(self):
        for value in ("-1", "abc", "1.5"):
            with self.subTest(since=value):
                response = self.api("/journal?since=%s" % value)
                self.assertEqual(response.status, 400)
                self.assertIn("since", response.text)

    def test_no_offset_and_an_empty_offset_both_read_from_zero(self):
        whole = self.api("/journal?since=0").json
        for path in ("/journal", "/journal?since="):
            with self.subTest(path=path):
                self.assertEqual(self.api(path).json["events"], whole["events"])

    def test_a_half_written_line_is_not_served_until_it_is_whole(self):
        path = self.project / "research" / "journal.jsonl"
        whole = self.api("/journal?since=0").json
        with open(path, "ab") as handle:
            handle.write(b'{"ts":"2026-09-12T00:00:00.000Z","event":"unpaused"')
        tail = self.api("/journal?since=%d" % whole["next"]).json
        self.assertEqual(tail["events"], [])
        self.assertEqual(tail["next"], whole["next"])

    def test_tail_by_line_count_answers_with_the_last_lines_and_their_offset(self):
        whole = self.api("/journal?since=0").json
        for lines in (1, 3, 10, len(whole["events"]), len(whole["events"]) + 50):
            with self.subTest(lines=lines):
                tail = self.api("/journal?tail=%d" % lines).json
                expected = whole["events"][-lines:]
                self.assertEqual(tail["events"], expected)
                self.assertEqual(tail["next"], whole["next"], "a tail read ends where the journal does")

    def test_a_tail_read_crosses_the_block_boundary(self):
        """The backwards read steps in blocks; a journal longer than one block must still be right."""
        while self.journal_size() <= (1 << 16):
            self.append("unpaused", {}, ticket=None)
        whole, _ = self.ledger.read_events()
        tail = self.api("/journal?tail=5").json
        self.assertEqual(tail["events"], whole[-5:])

    def test_a_tail_larger_than_the_cap_reads_the_journal_from_the_start(self):
        asked = self.api("/journal?tail=%d" % (TAIL_LINES_MAX * 10)).json
        whole = self.api("/journal?since=0").json
        self.assertEqual(asked["events"], whole["events"])
        self.assertEqual(asked["since"], 0)

    def test_a_tail_that_is_not_a_line_count_is_a_bad_request(self):
        for value in ("0", "-2", "many"):
            with self.subTest(tail=value):
                response = self.api("/journal?tail=%s" % value)
                self.assertEqual(response.status, 400)
                self.assertIn("tail", response.text)

    def test_journal_tail_of_a_project_with_no_journal_is_empty(self):
        empty = self.temp / "empty"
        (empty / "research").mkdir(parents=True)
        tail = journal_tail(empty)
        self.assertEqual(tail, {"since": 0, "next": 0, "size": 0, "truncated": False, "events": []})


# --- the graph endpoint --------------------------------------------------------------------------------


class GraphEndpointTest(DashboardTestCase):
    def test_it_returns_well_formed_svg_with_one_rect_per_ticket_and_one_line_per_edge(self):
        response = self.api("/graph.svg")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("content-type"), "image/svg+xml")
        tickets = read_tickets(self.project)
        edges = sum(len(fields["blocked_by"]) for fields in tickets)
        root = ET.fromstring(response.text)
        ns = "{http://www.w3.org/2000/svg}"
        self.assertEqual(len(root.findall(".//%srect" % ns)), len(tickets))
        self.assertEqual(len(root.findall(".//%sline" % ns)), edges)

    def test_the_frontier_is_highlighted(self):
        svg = graph_svg(self.project)
        graph, _ = refresh_graph(self.project, write=False)
        frontier_ids = {entry["id"] for entry in frontier(graph)}
        self.assertTrue(frontier_ids)
        # Every frontier node's rect carries the frontier fill and no other node does.
        rects = re.findall(r'<rect[^>]*fill="([^"]+)"[^>]*/><text[^>]*>(\d+)</text>', svg)
        by_id = {int(node_id): fill for fill, node_id in rects}
        for entry in graph["tickets"]:
            expected = "#8ecae6" if entry["id"] in frontier_ids else None
            if expected:
                self.assertEqual(by_id[entry["id"]], expected)
            else:
                self.assertNotEqual(by_id[entry["id"]], "#8ecae6")

    def test_an_unchanged_ledger_answers_304(self):
        first = self.api("/graph.svg")
        self.assertEqual(self.api("/graph.svg", {"If-None-Match": first.etag}).status, 304)
        self.append("unpaused")
        self.assertEqual(self.api("/graph.svg", {"If-None-Match": first.etag}).status, 200)

    def test_graph_svg_of_a_project_with_no_tickets_is_an_empty_canvas(self):
        empty = self.temp / "no-tickets"
        (empty / "research" / "tickets").mkdir(parents=True)
        self.assertIn("<svg", graph_svg(empty))


# --- the tickets endpoints ------------------------------------------------------------------------------


class TicketsEndpointTest(DashboardTestCase):
    def test_it_lists_every_ticket_by_id(self):
        view = self.api("/tickets").json
        self.assertEqual([fields["id"] for fields in view], list(range(1, 12)))
        self.assertEqual(view[0]["title"], "Scaffold the analysis package")

    def test_an_unchanged_ledger_answers_304(self):
        first = self.api("/tickets")
        self.assertEqual(self.api("/tickets", {"If-None-Match": first.etag}).status, 304)


class TicketEndpointTest(DashboardTestCase):
    def test_it_carries_the_frontmatter_the_body_and_the_context_pack(self):
        view = self.api("/tickets/2").json
        self.assertEqual(view["fields"]["id"], 2)
        self.assertEqual(view["fields"]["title"], "Build the feature table")
        self.assertIn("One summary file with a row count and the feature names.", view["body"])
        self.assertEqual(view["context_pack"], [])

    def test_the_latest_result_is_the_most_recent_attempts_result_json(self):
        view = self.api("/tickets/2").json
        self.assertEqual(view["result"]["status"], "done")
        self.assertEqual(view["result"]["summary"], "Wrote the feature table and its summary.")

    def test_a_ticket_with_no_attempts_has_no_result(self):
        self.assertIsNone(self.api("/tickets/1").json["result"])

    def test_the_findings_are_filtered_by_ticket(self):
        view = self.api("/tickets/2").json
        self.assertEqual([entry["id"] for entry in view["findings"]], ["f-0001"])
        self.assertEqual(self.api("/tickets/1").json["findings"], [])

    def test_the_session_and_job_logs_are_named(self):
        view = self.api("/tickets/2").json
        self.assertEqual([entry["id"] for entry in view["sessions"]], ["2/1", "2/1/resume-1"])
        self.assertEqual(view["jobs"], [])

    def test_a_running_tickets_jobs_are_named(self):
        view = self.api("/tickets/3").json
        self.assertEqual([entry["id"] for entry in view["sessions"]], ["3/1"])
        self.assertEqual(sorted(job["id"] for job in view["jobs"]), ["j-0001", "j-0002"])

    def test_a_ticket_with_no_sessions_or_jobs_has_empty_lists(self):
        view = self.api("/tickets/1").json
        self.assertEqual(view["sessions"], [])
        self.assertEqual(view["jobs"], [])

    def test_an_unknown_ticket_id_is_a_bad_request(self):
        response = self.api("/tickets/999")
        self.assertEqual(response.status, 400)
        self.assertIn("no such ticket", response.text)

    def test_an_unchanged_ledger_answers_304(self):
        first = self.api("/tickets/2")
        self.assertEqual(self.api("/tickets/2", {"If-None-Match": first.etag}).status, 304)

    def test_a_new_resume_moves_the_tag_though_it_never_touches_the_ticket_file(self):
        """A resume writes into `resume-<k>/` without changing the ticket's status or file.

        `ledger_snapshot` alone would miss it, and a client that cached the tag before the resume
        was written would keep being told 304 forever: the session list `ticket_view` carries would
        be stale exactly where a page open on a running ticket needs it freshest.
        """
        first = self.api("/tickets/2")
        resume_dir = self.project / "research" / "sessions" / "2" / "1" / "resume-2"
        resume_dir.mkdir()
        (resume_dir / "stream.jsonl").write_text('{"type": "system"}\n', encoding="utf-8")
        changed = self.api("/tickets/2", {"If-None-Match": first.etag})
        self.assertEqual(changed.status, 200)
        self.assertNotEqual(changed.etag, first.etag)
        self.assertIn("2/1/resume-2", [entry["id"] for entry in changed.json["sessions"]])


# --- the logs endpoint ----------------------------------------------------------------------------------


class LogTailEndpointTest(DashboardTestCase):
    def test_a_session_log_tails_by_byte_offset(self):
        whole = (self.project / "research" / "sessions" / "2" / "1" / "stream.jsonl").read_bytes()
        first = self.api("/logs/session/2/1?since=0").json
        self.assertTrue(first["exists"])
        self.assertEqual(first["text"].encode("utf-8"), whole)
        self.assertEqual(first["next"], len(whole))
        again = self.api("/logs/session/2/1?since=%d" % first["next"]).json
        self.assertEqual(again["text"], "")

    def test_a_resume_log_is_addressed_by_its_own_id(self):
        view = self.api("/logs/session/2/1/resume-1?since=0").json
        self.assertTrue(view["exists"])
        self.assertIn("Resuming", view["text"])

    def test_a_job_log_tails_the_jobs_own_log_file(self):
        view = self.api("/logs/job/j-0001?since=0").json
        self.assertTrue(view["exists"])
        self.assertIn("epoch 1", view["text"])

    def test_an_unknown_job_id_answers_exists_false_rather_than_failing(self):
        view = self.api("/logs/job/j-9999?since=0").json
        self.assertFalse(view["exists"])

    def test_the_tick_log_is_read_from_the_per_machine_home_not_the_project(self):
        (home() / "tick.log").write_text("tick 1\n", encoding="utf-8")
        view = self.api("/logs/tick/tick?since=0").json
        self.assertTrue(view["exists"])
        self.assertEqual(view["text"], "tick 1\n")

    def test_a_log_that_does_not_exist_yet_answers_exists_false(self):
        view = self.api("/logs/session/2/9?since=0").json
        self.assertEqual(view, {"since": 0, "next": 0, "size": 0, "truncated": False, "text": "", "exists": False})

    def test_a_bad_session_id_is_a_bad_request(self):
        response = self.api("/logs/session/not-a-ticket?since=0")
        self.assertEqual(response.status, 400)

    def test_a_session_id_cannot_escape_the_sessions_directory(self):
        with self.assertRaises(DashboardError):
            log_path(self.project, "session", "../../../etc/passwd")
        response = self.api("/logs/session/../../../etc/passwd?since=0")
        self.assertEqual(response.status, 400)

    def test_a_job_log_field_cannot_escape_the_project_directory(self):
        jobs = self.project / "research" / "jobs"
        escaping = json.loads((jobs / "j-0001.json").read_text(encoding="utf-8"))
        escaping["id"], escaping["log"] = "j-escape", "../outside.log"
        (jobs / "j-escape.json").write_text(json.dumps(escaping), encoding="utf-8")
        self.assertIsNone(log_path(self.project, "job", "j-escape"))

    def test_an_unknown_log_kind_is_a_bad_request(self):
        response = self.api("/logs/nonsense/2/1?since=0")
        self.assertEqual(response.status, 400)

    def test_an_unchanged_log_answers_304(self):
        first = self.api("/logs/session/2/1?since=0")
        self.assertEqual(self.api("/logs/session/2/1?since=0", {"If-None-Match": first.etag}).status, 304)


# --- the outputs index (ticket 42) --------------------------------------------------------------


class OutputsEndpointTest(DashboardTestCase):
    def setUp(self):
        super().setUp()
        research = self.project / "research"
        (research / "findings.md").write_text("# findings\n\nnone yet.\n", encoding="utf-8")
        (research / "REPORT.md").write_text("# Report\n\nA claim.\n", encoding="utf-8")
        (research / "paper").mkdir(parents=True, exist_ok=True)
        (research / "paper" / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        refs = research / "refs" / "attn-is-all-you-need"
        (refs / "figures").mkdir(parents=True, exist_ok=True)
        (refs / "source").mkdir(parents=True, exist_ok=True)
        (refs / "dossier.json").write_text(json.dumps({"slug": "attn-is-all-you-need"}), encoding="utf-8")
        (refs / "dossier.md").write_text("# Attention Is All You Need\n", encoding="utf-8")
        (refs / "figures" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        (refs / "source" / "flat.tex").write_text("never re-served\n", encoding="utf-8")
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs" / "index.html").write_text("<h1>docs</h1>\n", encoding="utf-8")

    def outputs(self):
        return self.api("/outputs").json

    def test_results_come_from_the_manifest_verbatim(self):
        manifest = json.loads((self.project / "research" / "manifest.json").read_text(encoding="utf-8"))
        results = self.outputs()["results"]
        self.assertEqual(len(results), len(manifest["entries"]))
        for entry, expected in zip(results, manifest["entries"]):
            self.assertEqual(entry["path"], expected["path"])
            self.assertEqual(entry["size"], expected["size"])
            self.assertEqual(entry["sha256"], expected["sha256"])
            self.assertEqual(entry["ticket"], expected["ticket"])

    def test_findings_jsonl_and_findings_md_are_indexed_with_a_real_hash(self):
        entries = {entry["path"]: entry for entry in self.outputs()["findings"]}
        self.assertIn("research/findings.jsonl", entries)
        self.assertIn("research/findings.md", entries)
        on_disk = self.project / "research" / "findings.md"
        self.assertEqual(entries["research/findings.md"]["sha256"], sha256_of(on_disk))
        self.assertEqual(entries["research/findings.md"]["size"], on_disk.stat().st_size)

    def test_the_report_is_indexed_when_it_exists(self):
        report = self.outputs()["report"]
        self.assertEqual([entry["path"] for entry in report], ["research/REPORT.md"])

    def test_the_report_is_absent_rather_than_an_error_before_it_is_rendered(self):
        (self.project / "research" / "REPORT.md").unlink()
        self.assertEqual(self.outputs()["report"], [])

    def test_the_paper_and_docs_trees_are_walked(self):
        view = self.outputs()
        self.assertEqual([entry["path"] for entry in view["paper"]], ["research/paper/main.tex"])
        self.assertEqual([entry["path"] for entry in view["docs"]], ["docs/index.html"])

    def test_dossiers_carry_the_dossier_files_and_nothing_else_beside_them(self):
        paths = {entry["path"] for entry in self.outputs()["dossiers"]}
        self.assertEqual(paths, {
            "research/refs/attn-is-all-you-need/dossier.json",
            "research/refs/attn-is-all-you-need/dossier.md",
        })

    def test_figures_are_a_references_own_figures_directory(self):
        paths = [entry["path"] for entry in self.outputs()["figures"]]
        self.assertEqual(paths, ["research/refs/attn-is-all-you-need/figures/fig1.png"])

    def test_a_references_source_tree_is_never_indexed_anywhere(self):
        view = self.outputs()
        every_path = [entry["path"] for category in view.values() for entry in category]
        self.assertFalse(any("/source/" in path for path in every_path), every_path)

    def test_missing_paper_and_docs_trees_are_empty_lists_not_errors(self):
        shutil.rmtree(self.project / "research" / "paper")
        shutil.rmtree(self.project / "docs")
        view = self.outputs()
        self.assertEqual(view["paper"], [])
        self.assertEqual(view["docs"], [])

    def test_an_unchanged_index_answers_304_and_a_new_file_moves_the_tag(self):
        first = self.api("/outputs")
        self.assertEqual(first.status, 200)
        self.assertEqual(self.api("/outputs", {"If-None-Match": first.etag}).status, 304)
        (self.project / "research" / "paper" / "abstract.tex").write_text("abstract\n", encoding="utf-8")
        changed = self.api("/outputs", {"If-None-Match": first.etag})
        self.assertEqual(changed.status, 200)
        self.assertNotEqual(changed.etag, first.etag)


# --- downloads: single files, ranges, and directories as a zip (ticket 42) ----------------------


class ByteRangeTest(unittest.TestCase):
    def test_no_header_means_the_whole_body(self):
        self.assertIsNone(byte_range(None, 100))

    def test_a_first_last_range(self):
        self.assertEqual(byte_range("bytes=100-199", 1000), (100, 199))

    def test_an_open_ended_range_runs_to_the_end(self):
        self.assertEqual(byte_range("bytes=900-", 1000), (900, 999))

    def test_a_suffix_range_is_the_last_n_bytes(self):
        self.assertEqual(byte_range("bytes=-100", 1000), (900, 999))

    def test_a_suffix_longer_than_the_file_clamps_to_the_start(self):
        self.assertEqual(byte_range("bytes=-10000", 1000), (0, 999))

    def test_a_multi_range_header_is_treated_as_the_whole_body(self):
        self.assertIsNone(byte_range("bytes=0-10,20-30", 1000))

    def test_a_range_past_the_end_is_unsatisfiable(self):
        with self.assertRaises(Exception):
            byte_range("bytes=99999999-", 1000)


class DownloadEndpointTest(DashboardTestCase):
    def setUp(self):
        super().setUp()
        refs = self.project / "research" / "refs" / "paper-x" / "source"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "flat.tex").write_text("never re-served\n", encoding="utf-8")
        (self.project / "research" / "paper").mkdir(parents=True, exist_ok=True)
        (self.project / "research" / "paper" / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.project / "research" / "paper" / "sections").mkdir(exist_ok=True)
        (self.project / "research" / "paper" / "sections" / "intro.tex").write_text("Introduction.\n", encoding="utf-8")

    def download(self, relpath, headers=None):
        return self.get("/api/projects/%s/download/%s" % (self.project_id, relpath), headers=headers)

    def test_it_downloads_a_file_that_exists_on_disk(self):
        response = self.download("results/baseline/seed-1.log")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("accept-ranges"), "bytes")
        self.assertEqual(response.body, (self.project / "results" / "baseline" / "seed-1.log").read_bytes())

    def test_a_missing_manifest_path_is_a_clean_404_not_a_crash(self):
        response = self.download("results/features/summary.json")
        self.assertEqual(response.status, 404)

    def test_a_single_range_answers_206_with_content_range(self):
        whole = (self.project / "results" / "baseline" / "seed-1.log").read_bytes()
        response = self.download("results/baseline/seed-1.log", {"Range": "bytes=0-9"})
        self.assertEqual(response.status, 206)
        self.assertEqual(response.body, whole[0:10])
        self.assertEqual(response.headers.get("content-range"), "bytes 0-9/%d" % len(whole))

    def test_a_range_past_the_end_is_416(self):
        response = self.download("results/baseline/seed-1.log", {"Range": "bytes=999999-"})
        self.assertEqual(response.status, 416)
        self.assertTrue(response.headers.get("content-range", "").startswith("bytes */"))

    def test_a_path_escaping_the_project_is_refused(self):
        response = self.download("../../../etc/passwd")
        self.assertEqual(response.status, 404)

    def test_a_references_source_file_cannot_be_downloaded_though_it_exists_on_disk(self):
        path = "research/refs/paper-x/source/flat.tex"
        self.assertTrue((self.project / path).is_file())
        self.assertIsNone(download_target(self.project, path))
        self.assertEqual(self.download(path).status, 404)

    def test_a_directory_downloads_as_a_clean_zip(self):
        response = self.download("research/paper")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("content-type"), "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(response.body))
        self.assertIsNone(archive.testzip())
        self.assertEqual(set(archive.namelist()), {"main.tex", "sections/intro.tex"})

    def test_a_directory_zip_never_carries_a_references_source_tree(self):
        response = self.download("research/refs/paper-x")
        archive = zipfile.ZipFile(io.BytesIO(response.body))
        self.assertIsNone(archive.testzip())
        self.assertNotIn("source/flat.tex", archive.namelist())

    def test_a_seventeen_megabyte_tree_zips_cleanly(self):
        """research-notes 08 Section 3's own measurement, reproduced as the ticket's acceptance."""
        bulk = self.project / "results" / "bulk"
        bulk.mkdir(parents=True, exist_ok=True)
        line = (b"the quick brown fox jumps over the lazy dog\n") * 200  # ~8.8 KB of text
        for index in range(40):
            (bulk / ("file-%02d.txt" % index)).write_bytes(line * 47)  # ~400 KB each, ~16 MB total
        (bulk / "noise.bin").write_bytes(os.urandom(3 * 1024 * 1024))  # +3 MiB incompressible
        total = sum(path.stat().st_size for path in bulk.rglob("*") if path.is_file())
        self.assertGreater(total, 17 * 1024 * 1024 - (1024 * 1024))
        response = self.download("results/bulk")
        self.assertEqual(response.status, 200)
        archive = zipfile.ZipFile(io.BytesIO(response.body))
        self.assertIsNone(archive.testzip())
        self.assertEqual(len(archive.namelist()), 41)
        if shutil.which("unzip"):
            extracted = self.temp / "extracted"
            zip_path = self.temp / "tree.zip"
            zip_path.write_bytes(response.body)
            extracted.mkdir()
            result = subprocess.run(["unzip", "-tq", str(zip_path)], cwd=extracted, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


# --- server-sent events, the alternative behind ?transport=sse ---------------------------------------


class ServerSentEventsTest(DashboardTestCase):
    """The SSE alternative of OPEN-20: raw sockets, because `http.client` waits for a whole body."""

    def stream(self, since=0, last_event_id=None, timeout=10):
        """Open the stream and return the socket with its headers already read."""
        client = socket.create_connection((self.host, self.port), timeout=timeout)
        self.addCleanup(client.close)
        request = "GET /api/projects/%s/journal?transport=sse&since=%d HTTP/1.1\r\nHost: %s\r\n" % (self.project_id, since, self.host)
        if last_event_id is not None:
            request += "Last-Event-ID: %s\r\n" % last_event_id
        client.sendall((request + "\r\n").encode("ascii"))
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = client.recv(4096)
            if not chunk:
                self.fail("the stream closed before its headers arrived")
            buffer += chunk
        head, rest = buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").splitlines()
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        return client, lines[0], headers, rest

    @staticmethod
    def read_until(client, rest, marker, limit=65536):
        """Read from the stream until `marker` is in what has arrived, and return it."""
        buffer = rest
        while marker not in buffer and len(buffer) < limit:
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer += chunk
        return buffer.decode("utf-8")

    def read_ids(self, client, rest, count, limit=65536):
        """Read until `count` `id:` lines have arrived, and return the ids as integers."""
        buffer = rest
        while buffer.count(b"id: ") < count and len(buffer) < limit:
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer += chunk
        return [int(line.split(":", 1)[1]) for line in buffer.decode("utf-8").splitlines() if line.startswith("id: ")]

    def test_the_response_is_an_unchunked_event_stream_that_ends_with_the_connection(self):
        client, status, headers, rest = self.stream()
        self.assertIn("200", status)
        self.assertEqual(headers["content-type"], "text/event-stream; charset=utf-8")
        self.assertEqual(headers["connection"], "close")
        self.assertEqual(headers["cache-control"], "no-cache")
        self.assertNotIn("transfer-encoding", headers)
        self.assertNotIn("content-length", headers)
        self.assertIn("retry: %d" % SSE_RETRY_MS, self.read_until(client, rest, b"retry:"))

    def test_every_event_carries_the_journal_offset_after_its_line_as_its_id(self):
        client, _, _, rest = self.stream()
        offsets = self.line_offsets()
        ids = self.read_ids(client, rest, len(offsets))
        self.assertEqual(ids, offsets, "the id is the offset after the line it carries, per line")

    def test_an_event_appended_after_the_stream_opened_arrives_on_it(self):
        client, _, _, rest = self.stream(since=self.journal_size())
        self.read_until(client, rest, b"retry:")
        written = self.append("unpaused")
        text = self.read_until(client, b"", b"unpaused")
        self.assertIn("data: %s" % json.dumps(written, ensure_ascii=False, separators=(",", ":")), text)
        self.assertIn("id: %d" % self.journal_size(), text)

    def test_last_event_id_resumes_where_the_dropped_stream_stopped(self):
        offsets = self.line_offsets()
        client, _, _, rest = self.stream(last_event_id=offsets[0])
        ids = self.read_ids(client, rest, 1)
        self.assertEqual(ids[0], offsets[1], "a resume starts with the line after the id it was given")

    def test_a_last_event_id_past_the_end_of_the_journal_starts_over(self):
        client, _, _, rest = self.stream(last_event_id=self.journal_size() + 10_000)
        ids = self.read_ids(client, rest, 1)
        self.assertEqual(ids[0], self.line_offsets()[0])

    def test_the_stream_thread_ends_when_the_client_goes_away(self):
        before = threading.active_count()
        client, _, _, rest = self.stream()
        self.read_until(client, rest, b"retry:")
        self.assertGreater(threading.active_count(), before)
        client.close()
        deadline = threading.Event()
        # The select() dead-client check ends the thread within a tick; wait on that, not on a sleep.
        for _ in range(500):
            if threading.active_count() <= before:
                break
            deadline.wait(0.02)
        self.assertLessEqual(threading.active_count(), before, "an abandoned stream must not hold a thread")

    def line_offsets(self):
        """The byte offset after each line of the fixture journal: the ids the stream must send."""
        offsets, position = [], 0
        for raw in (self.project / "research" / "journal.jsonl").read_bytes().splitlines(keepends=True):
            position += len(raw)
            offsets.append(position)
        return offsets


# --- the static page ---------------------------------------------------------------------------------


class StaticPageTest(DashboardTestCase):
    def test_the_root_serves_the_page(self):
        response = self.get("/")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")
        self.assertIn("<title>wayline</title>", response.text)
        self.assertEqual(int(response.headers["content-length"]), len(response.body))

    def test_the_page_loads_the_three_assets_and_the_two_vendored_files(self):
        page = self.get("/").text
        for reference in ("/style.css", "/app.js", "/vendor/marked.umd.js", "/vendor/purify.min.js"):
            self.assertIn(reference, page)
            served = self.get(reference)
            self.assertEqual(served.status, 200, reference)
            self.assertEqual(served.headers["content-type"], "text/css; charset=utf-8" if reference.endswith(".css") else "text/javascript; charset=utf-8")

    def test_an_unchanged_asset_answers_304(self):
        first = self.get("/app.js")
        self.assertEqual(self.get("/app.js", {"If-None-Match": first.etag}).status, 304)

    def test_nothing_outside_the_dashboard_directory_is_servable(self):
        for path in ("/../wayline/cli.py", "/%2e%2e/policy.json", "/vendor/../../policy.json", "/nosuch.js"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status, 404)

    def test_an_unknown_api_path_is_not_answered_with_the_page(self):
        response = self.get("/api/nosuch")
        self.assertEqual(response.status, 404)
        self.assertIn("no such endpoint", response.text)

    def test_static_file_resolves_a_directory_to_its_index(self):
        self.assertEqual(static_file("/", root=STATIC), (STATIC / "index.html").resolve())
        self.assertIsNone(static_file("/vendor", root=STATIC))


class VendoredAssetsTest(unittest.TestCase):
    """The pins of `dashboard/vendor/VENDOR.md`: a drifted file is a failing test, not a surprise."""

    def test_every_vendored_file_matches_its_recorded_size_and_digest(self):
        for name, size, digest in VENDORED:
            with self.subTest(file=name):
                data = (STATIC / "vendor" / name).read_bytes()
                self.assertEqual(len(data), size)
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_the_record_names_every_vendored_file_with_its_digest(self):
        record = (STATIC / "vendor" / "VENDOR.md").read_text(encoding="utf-8")
        for name, size, digest in VENDORED:
            self.assertIn(name, record)
            self.assertIn(digest, record)
            self.assertIn(str(size), record)

    def test_the_vendor_directory_holds_nothing_else(self):
        present = sorted(path.name for path in (STATIC / "vendor").iterdir())
        self.assertEqual(present, sorted(["VENDOR.md"] + [name for name, _, _ in VENDORED]))


# --- the token rule -------------------------------------------------------------------------------------


class LoopbackNeedsNoTokenTest(DashboardTestCase):
    def test_a_view_on_loopback_is_served_without_a_token(self):
        self.assertEqual(self.get("/api/projects").status, 200)

    def test_requires_token_is_decided_by_the_bind(self):
        self.assertFalse(requires_token(LOOPBACK))
        self.assertFalse(requires_token("localhost"))
        self.assertFalse(requires_token("::1"))
        self.assertTrue(requires_token("0.0.0.0"))
        self.assertTrue(requires_token("192.168.1.9"))


class TokenRuleTest(DashboardTestCase):
    """A server bound wider than loopback, bound to loopback in the test and asked to act wide."""

    require_token = True
    token = "a-token-with-enough-entropy-to-stand-in"

    def test_a_request_without_the_token_is_refused(self):
        response = self.get("/api/projects")
        self.assertEqual(response.status, 403)
        self.assertIn("token", response.text)

    def test_the_token_is_accepted_in_the_header_and_in_the_query(self):
        self.assertEqual(self.get("/api/projects", {TOKEN_HEADER: self.token}).status, 200)
        self.assertEqual(self.get("/api/projects?token=%s" % self.token).status, 200)

    def test_the_page_and_its_assets_load_the_way_a_browser_asks_for_them(self):
        """The URL `serve` prints has to give a working page, assets included.

        A browser attaches neither the header nor the query to a `<link>` or a `<script>`, so the
        page's own subresources arrive with nothing but the cookie the first response set. Without
        that the owner would get an unstyled page with no tabs and no explanation.
        """
        page = self.get("/?token=%s" % self.token)
        self.assertEqual(page.status, 200)
        cookie = SimpleCookie(page.headers["set-cookie"])
        self.assertEqual(cookie[TOKEN_COOKIE].value, self.token)
        self.assertEqual(cookie[TOKEN_COOKIE]["samesite"], "Strict")
        self.assertTrue(cookie[TOKEN_COOKIE]["httponly"])
        carried = {"Cookie": "%s=%s" % (TOKEN_COOKIE, self.token)}
        for path in ("/style.css", "/app.js", "/vendor/marked.umd.js", "/vendor/purify.min.js",
                     "/api/projects", "/api/projects/%s/overview" % self.project_id,
                     "/api/projects/%s/journal?since=0" % self.project_id):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status, 403, "nothing is served without the token")
                self.assertEqual(self.get(path, carried).status, 200)

    def test_a_response_to_a_header_or_cookie_request_sets_no_cookie(self):
        for headers in ({TOKEN_HEADER: self.token}, {"Cookie": "%s=%s" % (TOKEN_COOKIE, self.token)}):
            with self.subTest(headers=sorted(headers)):
                self.assertNotIn("set-cookie", self.get("/api/projects", headers).headers)

    def test_a_wrong_cookie_is_refused(self):
        self.assertEqual(self.get("/api/projects", {"Cookie": "%s=wrong" % TOKEN_COOKIE}).status, 403)
        self.assertEqual(self.get("/api/projects", {"Cookie": "unrelated=1"}).status, 403)

    def test_a_wrong_token_is_refused_everywhere_including_the_page_and_the_stream(self):
        for path in ("/", "/app.js", "/api/projects", "/api/projects/%s/overview" % self.project_id,
                     "/api/projects/%s/journal?since=0" % self.project_id,
                     "/api/projects/%s/journal?transport=sse" % self.project_id):
            with self.subTest(path=path):
                self.assertEqual(self.get(path + ("&" if "?" in path else "?") + "token=wrong").status, 403)

    def test_a_wider_bind_raises_the_request_queue(self):
        self.assertEqual(self.server.request_queue_size, 16)

    def test_a_wide_server_without_a_token_is_refused_at_construction(self):
        with self.assertRaises(DashboardError):
            make_server("0.0.0.0", 0, token=None)

    def test_the_shipped_idle_timeout_is_longer_than_a_poll_and_shorter_than_a_tab(self):
        self.assertEqual(DashboardHandler.timeout, IDLE_TIMEOUT_S)
        self.assertGreater(IDLE_TIMEOUT_S, 5)
        self.assertLessEqual(IDLE_TIMEOUT_S, 60)


class IdleConnectionTest(DashboardTestCase):
    """An idle peer must not hold a thread: the token is only checked once a request has arrived."""

    handler = None  # set in setUp to a handler with a timeout a test can wait for

    def setUp(self):
        class Impatient(DashboardHandler):
            timeout = 0.2

        type(self).handler = Impatient
        super().setUp()

    def make(self):
        return make_server(self.bind, 0, token=self.token, require_token=self.require_token,
                           static_root=STATIC, sse_tick_s=self.sse_tick_s, memo_ttl=0.0, handler=self.handler)

    def test_a_connection_that_sends_nothing_is_closed(self):
        client = socket.create_connection((self.host, self.port), timeout=10)
        self.addCleanup(client.close)
        self.assertEqual(client.recv(1), b"", "the server closed an idle connection instead of waiting on it")

    def test_a_request_that_stops_mid_headers_is_closed(self):
        client = socket.create_connection((self.host, self.port), timeout=10)
        self.addCleanup(client.close)
        client.sendall(b"GET /api/projects HTTP/1.1\r\nHost: x\r\n")  # no blank line: never finished
        self.assertEqual(client.recv(1), b"")


# --- the settings, the ETag helper, and the snapshot ---------------------------------------------------------


class SettingsTest(ProjectTestCase):
    def test_the_first_read_mints_a_token_and_stores_it_privately(self):
        settings = read_settings()
        self.assertEqual(settings["port"], 8765)
        self.assertEqual(settings["bind"], LOOPBACK)
        self.assertTrue(settings["token"])
        self.assertEqual(stat.S_IMODE(os.stat(dashboard_path()).st_mode), 0o600)
        self.assertEqual(read_settings()["token"], settings["token"], "a restart must not invalidate a bookmarked URL")

    def test_the_arguments_win_and_the_file_records_what_this_start_used(self):
        read_settings()
        settings = read_settings(port=9999, bind="0.0.0.0")
        self.assertEqual((settings["port"], settings["bind"]), (9999, "0.0.0.0"))
        stored = json.loads(dashboard_path().read_text(encoding="utf-8"))
        self.assertEqual((stored["port"], stored["bind"]), (9999, "0.0.0.0"))

    def test_the_file_never_wins_over_the_configured_port(self):
        read_settings(port=9999)
        self.assertEqual(read_settings()["port"], 8765, "a --port passed once is not the new default")

    def test_a_projects_harness_json_moves_the_port_and_the_intervals(self):
        project = self.ledger_fixture()
        harness = json.loads((project / "harness.json").read_text(encoding="utf-8"))
        harness["dashboard"].update(port=8900, poll_journal_s=1, poll_views_s=3)
        (project / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        settings = read_settings(project=project)
        self.assertEqual(settings["port"], 8900)
        self.assertEqual((settings["poll_journal_s"], settings["poll_views_s"]), (1, 3))

    def test_an_unreadable_settings_file_is_replaced_rather_than_fatal(self):
        dashboard_path().parent.mkdir(parents=True, exist_ok=True)
        dashboard_path().write_text("{ not json", encoding="utf-8")
        self.assertTrue(read_settings()["token"])

    def test_the_url_carries_the_token_on_every_bind(self):
        """The views on loopback need none, but every action does (ticket 35), and the page sends the one its own URL carries."""
        loopback = {"port": 8765, "bind": LOOPBACK, "token": "secret"}
        self.assertEqual(dashboard_url(loopback), "http://127.0.0.1:8765/?token=secret")
        self.assertEqual(dashboard_url(dict(loopback, token=None)), "http://127.0.0.1:8765/")
        wide = {"port": 8765, "bind": "0.0.0.0", "token": "secret"}
        self.assertIn("token=secret", dashboard_url(wide))
        self.assertNotIn("0.0.0.0", dashboard_url(wide), "0.0.0.0 is an address to listen on, not one to dial")

    def test_the_recorded_port_is_the_one_the_server_bound(self):
        settings = read_settings(port=0)
        settings["port"] = 41234
        record_settings(settings)
        self.assertEqual(json.loads(dashboard_path().read_text(encoding="utf-8"))["port"], 41234)


class ServeLinesTest(ProjectTestCase):
    def test_the_tunnel_line_forwards_the_port_to_loopback(self):
        line = tunnel_line(8765, workstation="box")
        self.assertIn("ssh ", line)
        self.assertIn("-L 8765:127.0.0.1:8765 box", line)
        self.assertIn("ServerAliveInterval=30", line)
        self.assertIn("-N", line)

    def test_serve_prints_the_url_the_tunnel_line_and_the_tabs(self):
        project = self.ledger_fixture()
        register(project, TAG)
        set_active(project)
        settings = {"port": 8765, "bind": LOOPBACK, "token": "secret", "poll_journal_s": 2, "poll_views_s": 5}
        text = "\n".join(serve_lines(settings, projects_view(settings=settings), workstation="box"))
        self.assertIn("http://127.0.0.1:8765/", text)
        self.assertIn("-L 8765:127.0.0.1:8765 box", text)
        self.assertIn(str(project), text)
        self.assertIn("active", text)
        self.assertIn("http://127.0.0.1:8765/?token=secret", text, "the views on loopback need no token, but the actions do")
        self.assertIn("every action needs the token the URL carries", text)

    def test_a_wider_bind_prints_the_token_and_says_it_is_needed(self):
        settings = {"port": 8765, "bind": "0.0.0.0", "token": "secret", "poll_journal_s": 2, "poll_views_s": 5}
        text = "\n".join(serve_lines(settings, projects_view(settings=settings), workstation="box"))
        self.assertIn("token=secret", text)
        self.assertIn("every request needs the token", text)

    def test_with_no_project_registered_it_says_what_to_run(self):
        settings = {"port": 8765, "bind": LOOPBACK, "token": "secret"}
        text = "\n".join(serve_lines(settings, projects_view(settings=settings)))
        self.assertIn("wayline init", text)


class SnapshotTest(ProjectTestCase):
    def test_the_snapshot_covers_the_ledger_and_moves_when_a_file_does(self):
        project = self.ledger_fixture()
        first = ledger_snapshot(project)
        self.assertIn("harness.json", first)
        self.assertIn("research/journal.jsonl", first)
        self.assertIn("research/tickets/01-scaffold-the-analysis-package.md", first)
        self.assertIn("research/jobs/j-0001.json", first)
        Ledger(project).append_event("unpaused", {})
        self.assertNotEqual(ledger_snapshot(project), first)

    def test_the_snapshot_skips_the_lock_and_the_temp_files_of_an_atomic_write(self):
        project = self.ledger_fixture()
        (project / "research" / ".lock").write_text("", encoding="utf-8")
        (project / "research" / ".graph.json.abc123.tmp").write_text("{}", encoding="utf-8")
        keys = ledger_snapshot(project)
        self.assertFalse([key for key in keys if Path(key).name.startswith(".")], keys)

    def test_a_project_that_is_not_there_snapshots_to_nothing(self):
        self.assertEqual(ledger_snapshot(self.temp / "nosuch"), {})

    def test_the_etag_is_quoted_stable_and_route_specific(self):
        snapshot = {"research/journal.jsonl": (1, 2)}
        tag = etag("overview", "toy", snapshot)
        self.assertTrue(tag.startswith('"') and tag.endswith('"'))
        self.assertEqual(tag, etag("overview", "toy", snapshot))
        self.assertNotEqual(tag, etag("journal", "toy", snapshot))
        self.assertNotEqual(tag, etag("overview", "other", snapshot))


class MemoTest(unittest.TestCase):
    def test_a_value_is_built_once_a_second_and_then_again(self):
        from wayline.dashboard import Memo

        now = [1000.0]
        memo = Memo(ttl=1.0, clock=lambda: now[0])
        built = []

        def build():
            built.append(len(built))
            return len(built)

        self.assertEqual(memo.get("k", build), 1)
        now[0] += 0.5
        self.assertEqual(memo.get("k", build), 1)
        now[0] += 0.6
        self.assertEqual(memo.get("k", build), 2)
        self.assertEqual(len(built), 2)


class VerbTest(unittest.TestCase):
    def test_the_serve_verb_is_built(self):
        from wayline import cli

        verb = cli.lookup("serve")
        self.assertIsNotNone(verb.handler)
        self.assertNotIn("serve", cli.overview().split("not yet implemented")[0][-200:])

    def test_serve_refuses_a_project_that_is_not_one(self):
        from wayline.dashboard import serve_command

        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(serve_command(["--project", "/nonexistent-project-path"]), 1)
        self.assertIn("not a wayline project", errors.getvalue())

    def test_serve_refuses_an_unknown_flag(self):
        from wayline.dashboard import serve_command

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(serve_command(["--nope"]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
