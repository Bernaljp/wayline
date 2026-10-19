"""`wayline status` over the fixture ledger, and the fixture itself.

`fixtures/ledger/` is a project whose ledger holds tickets in every status, two jobs, a goal, and
a journal longer than the ten events `status` prints. Every test copies it first, because reading
a status regenerates `graph.json`.
"""

import json
import os
import subprocess
import sys
import unittest

from tests.paths import HARNESS_ROOT, LEDGER_FIXTURE
from tests.projects import ProjectTestCase
from wayline.jsonschema import check, load_schema
from wayline.ledger import EVENTS, Ledger, make_event
from wayline.project import init_project, read_jobs, render_status, status_view, switch_project
from wayline.tickets import GRAPH, STATUSES, read_tickets


class FixtureLedgerTest(unittest.TestCase):
    """The committed fixture is data the other tests trust; these tests keep it honest."""

    def test_every_ticket_file_validates(self):
        tickets = read_tickets(LEDGER_FIXTURE)
        self.assertGreaterEqual(len(tickets), len(STATUSES))
        for fields in tickets:
            check(fields, load_schema("ticket"), name="ticket %d" % fields["id"])

    def test_the_fixture_holds_a_ticket_in_every_status(self):
        present = {fields["status"] for fields in read_tickets(LEDGER_FIXTURE)}
        self.assertEqual(present, set(STATUSES))

    def test_the_fixture_holds_an_open_decision_ticket(self):
        decisions = [fields for fields in read_tickets(LEDGER_FIXTURE) if fields["kind"] == "decision"]
        self.assertTrue(decisions)
        self.assertEqual(decisions[0]["status"], "open")
        self.assertTrue(decisions[0]["human_only"])

    def test_the_journal_is_in_timestamp_order(self):
        events, _ = Ledger(LEDGER_FIXTURE).read_events()
        stamps = [event["ts"] for event in events]
        self.assertEqual(stamps, sorted(stamps), "the ledger writes file order and ts order together")

    def test_every_journal_line_is_a_valid_event_of_the_vocabulary(self):
        events, offset = Ledger(LEDGER_FIXTURE).read_events()
        self.assertGreater(len(events), 10, "the fixture journal must be longer than the ten status prints")
        self.assertEqual(offset, (LEDGER_FIXTURE / "research" / "journal.jsonl").stat().st_size)
        for event in events:
            check(event, load_schema("journal_event"), name=event["event"])
            self.assertIn(event["event"], EVENTS)
            make_event(event["event"], event["payload"], ticket=event["ticket"], session_id=event["session_id"], job=event["job"], ts=event["ts"])

    def test_every_job_file_validates(self):
        jobs, problems = read_jobs(LEDGER_FIXTURE)
        self.assertEqual(problems, [])
        self.assertEqual([job["id"] for job in jobs], ["j-0001", "j-0002"])

    def test_the_manifest_and_the_harness_validate(self):
        check(json.loads((LEDGER_FIXTURE / "research" / "manifest.json").read_text(encoding="utf-8")), load_schema("manifest"))
        check(json.loads((LEDGER_FIXTURE / "harness.json").read_text(encoding="utf-8")), load_schema("harness"))

    def test_the_fixture_carries_no_generated_graph(self):
        self.assertFalse((LEDGER_FIXTURE / "research" / GRAPH).exists(), "graph.json is generated; it is not committed")


class StatusViewTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.view = status_view(self.project)

    def test_the_frontier_is_the_open_tickets_whose_blockers_are_satisfied(self):
        self.assertEqual([entry["id"] for entry in self.view["frontier"]], [5, 10])
        self.assertEqual(self.view["frontier"][0]["title"], "Plot the learning curves")

    def test_the_running_tickets_carry_their_attempt(self):
        self.assertEqual([entry["id"] for entry in self.view["running"]], [3])
        self.assertEqual(self.view["running"][0]["attempt"], 1)
        self.assertEqual(self.view["running"][0]["title"], "Train the baseline model")

    def test_only_the_live_jobs_are_running(self):
        self.assertEqual([job["id"] for job in self.view["jobs"]], ["j-0001"])
        self.assertEqual(self.view["jobs"][0]["ticket"], 3)

    def test_the_open_decision_tickets_are_listed(self):
        self.assertEqual([entry["id"] for entry in self.view["decisions"]], [10])
        self.assertTrue(self.view["decisions"][0]["human_only"])
        self.assertEqual(self.view["decisions"][0]["blocking"], "subgraph")

    def test_the_window_is_the_last_pacing_reading(self):
        window = self.view["window"]
        self.assertEqual(window["action"], "normal")
        self.assertEqual(window["five_hour"], 0.41)
        self.assertEqual(window["seven_day"], 0.52)
        self.assertFalse(window["paused"], "the fixture pauses and unpauses again")
        self.assertEqual(window["stop_at"], 0.90)

    def test_a_pause_without_an_unpause_shows_as_paused(self):
        Ledger(self.project).append_event("paused", {"resets_at": "2026-09-11T18:00:00Z", "window": "seven_day", "utilization": 0.93})
        window = status_view(self.project)["window"]
        self.assertTrue(window["paused"])
        self.assertEqual(window["window"], "seven_day")
        self.assertEqual(window["resets_at"], "2026-09-11T18:00:00Z")

    def test_a_goal_carries_its_target_and_its_best_kept_reading(self):
        """Ticket 87: the goal is an objective with a measure, its best kept value recomputed from its own `progress`."""
        goal = self.view["objectives"][0]
        self.assertEqual((goal["id"], goal["metric"], goal["direction"], goal["target"]), ("O1", "auroc", "up", 0.9))
        self.assertEqual(goal["best"], 0.812)
        self.assertFalse(goal["reached"])
        self.assertNotIn("goal", self.view, "GOAL.json is read by nobody")

    def test_a_reading_past_the_target_reaches_the_goal(self):
        Ledger(self.project).append_event("progress", {"metric": "auroc", "value": 0.94, "ticket": 3, "run_id": "t3-a2", "kept": True,
                                                       "goal": "O1"})
        self.assertTrue(status_view(self.project)["objectives"][0]["reached"])

    def test_a_reading_of_no_goal_is_not_this_goal_s(self):
        Ledger(self.project).append_event("progress", {"metric": "auroc", "value": 0.94, "ticket": 3, "run_id": "t3-a2", "kept": True})
        self.assertEqual(status_view(self.project)["objectives"][0]["best"], 0.812)

    def test_a_project_without_objectives_has_none(self):
        (self.project / "research" / "objectives.json").unlink()
        self.assertEqual(status_view(self.project)["objectives"], [])

    def test_the_stopping_rule_and_the_budgets(self):
        stopping = self.view["stopping"]
        self.assertEqual((stopping["rule"], stopping["spent"]), ("objectives", []))
        self.assertEqual(stopping["budgets"]["gpu_hours"]["limit"], None)

    def test_the_last_ten_events_are_the_tail_of_the_journal(self):
        events, _ = Ledger(self.project).read_events()
        self.assertEqual(self.view["events"], events[-10:])
        self.assertEqual(len(self.view["events"]), 10)
        self.assertEqual(self.view["offset"], (self.project / "research" / "journal.jsonl").stat().st_size)

    def test_the_counts_cover_every_status(self):
        self.assertEqual(self.view["counts"]["open"], 4)
        for status in STATUSES:
            self.assertGreaterEqual(self.view["counts"][status], 1, status)

    def test_the_head_names_the_project_and_the_pin(self):
        self.assertEqual(self.view["harness_tag"], "v0.0.0")
        self.assertEqual(self.view["autonomy"], "checkpoints")
        self.assertEqual(self.view["radius"], "moderate")
        self.assertFalse(self.view["active"], "the fixture copy is not the active project")

    def test_the_active_project_is_marked(self):
        harness = self.fake_harness()
        init_project(self.temp / "other", harness_root=harness)
        (self.project / ".claude").mkdir(exist_ok=True)
        switch_project(self.project)
        self.assertTrue(status_view(self.project)["active"])

    def test_nothing_is_wrong_with_the_fixture(self):
        self.assertEqual(self.view["problems"], [])


class StatusGraphTest(ProjectTestCase):
    def test_status_regenerates_the_graph_and_then_leaves_it_alone(self):
        project = self.ledger_fixture()
        graph_path = project / "research" / GRAPH
        self.assertFalse(graph_path.exists())
        first = status_view(project)
        self.assertTrue(first["graph_regenerated"])
        self.assertTrue(graph_path.exists())
        before = graph_path.read_bytes()
        second = status_view(project)
        self.assertFalse(second["graph_regenerated"])
        self.assertEqual(graph_path.read_bytes(), before)
        self.assertEqual(first["frontier"], second["frontier"])

    def test_status_picks_up_a_ticket_a_human_edited(self):
        project = self.ledger_fixture()
        status_view(project)
        path = project / "research" / "tickets" / "05-plot-the-learning-curves.md"
        path.write_text(path.read_text(encoding="utf-8").replace("status: open", "status: done"), encoding="utf-8")
        view = status_view(project)
        self.assertTrue(view["graph_regenerated"])
        self.assertEqual([entry["id"] for entry in view["frontier"]], [10])

    def test_a_broken_ticket_file_becomes_a_problem_not_a_traceback(self):
        project = self.ledger_fixture()
        path = project / "research" / "tickets" / "05-plot-the-learning-curves.md"
        path.write_text("---\nid: 5\nnot a ticket\n---\n", encoding="utf-8")
        view = status_view(project)
        self.assertTrue(view["problems"])
        self.assertIn("tickets", view["problems"][0])
        self.assertIn("window", view)
        self.assertEqual(view["counts"]["open"], 0, "with no graph to fall back on the counts are empty")

    def test_a_broken_ticket_file_leaves_the_last_good_graph_printing(self):
        project = self.ledger_fixture()
        good = status_view(project)
        path = project / "research" / "tickets" / "05-plot-the-learning-curves.md"
        path.write_text("---\nid: 5\nnot a ticket\n---\n", encoding="utf-8")
        view = status_view(project)
        self.assertTrue(any(problem.startswith("graph.json:") for problem in view["problems"]))
        self.assertEqual([entry["id"] for entry in view["frontier"]], [entry["id"] for entry in good["frontier"]])

    def test_a_malformed_graph_file_is_regenerated_rather_than_indexed(self):
        for broken in ('{"snapshot": {}, "tickets": [{"kind": "code"}]}', '{"snapshot": {}, "tickets": [1, 2]}',
                       '{"tickets": "none"}', 'not json at all'):
            with self.subTest(graph=broken):
                project = self.ledger_fixture(name="fixture-" + str(abs(hash(broken))))
                (project / "research" / GRAPH).write_text(broken + "\n", encoding="utf-8")
                view = status_view(project)
                self.assertEqual(view["problems"], [])
                self.assertTrue(view["graph_regenerated"])
                self.assertEqual([entry["id"] for entry in view["frontier"]], [5, 10])

    def test_a_broken_job_file_becomes_a_problem(self):
        project = self.ledger_fixture()
        (project / "research" / "jobs" / "j-0003.json").write_text("{\"id\": \"j-0003\"}\n", encoding="utf-8")
        view = status_view(project)
        self.assertTrue(any(problem.startswith("jobs:") for problem in view["problems"]))
        self.assertEqual([job["id"] for job in view["jobs"]], ["j-0001"])


class RenderStatusTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        self.text = render_status(status_view(self.project))

    def test_the_text_names_every_section(self):
        for heading in ("project", "harness", "frontier (2)", "running tickets (1)", "running jobs (1)",
                        "open decision tickets (1)", "tickets needing a person (1)", "window", "objectives", "stopping", "tickets",
                        "last 10 events"):
            self.assertIn(heading, self.text)

    def test_a_ticket_waiting_for_a_person_is_listed_with_its_question(self):
        self.assertIn("#8   Reconcile the two label sources", self.text)
        self.assertIn("Which label source wins where the two disagree?", self.text)
        self.assertNotIn("at the ladder's top rung", self.text, "this one was not left on the top rung")

    def test_a_ticket_the_chain_left_on_the_top_rung_says_so(self):
        """Decision 16: `reason: top_rung` reads as "at the ladder's top rung" in status."""
        Ledger(self.project).append_event(
            "ticket_needs_human", {"ticket": 8, "question": "it failed on rung 7", "reason": "top_rung"}, ticket=8)
        text = render_status(status_view(self.project))
        self.assertIn("#8   Reconcile the two label sources  (at the ladder's top rung)", text)

    def test_the_text_names_the_frontier_tickets_by_title(self):
        self.assertIn("Plot the learning curves", self.text)
        self.assertIn("Which split is held out?", self.text)

    def test_the_text_carries_the_window_the_goal_and_the_stopping_rule(self):
        self.assertIn("five_hour 0.41", self.text)
        self.assertIn("(goal: `auroc` up to 0.9, best kept 0.812)", self.text)
        self.assertIn("stopping  objectives (the run ends when no objective is open); budgets: wall clock no limit", self.text)

    def test_the_text_carries_the_running_job(self):
        self.assertIn("j-0001", self.text)
        self.assertIn("wayline-job-j-0001.service", self.text)

    def test_no_line_of_the_text_is_blank_padded_nonsense(self):
        for line in self.text.splitlines():
            self.assertEqual(line, line.rstrip(), "a rendered line carries trailing spaces")

    def test_an_event_with_nothing_to_show_still_renders_a_clean_line(self):
        ledger = Ledger(self.project)
        ledger.append_event("unpaused")
        ledger.append_event("ticket_done", {"ticket": 3}, ticket=3)
        text = render_status(status_view(self.project))
        self.assertIn("unpaused", text)
        for line in text.splitlines():
            self.assertEqual(line, line.rstrip(), "a rendered line carries trailing spaces")

    def test_a_graph_entry_with_no_ticket_file_still_renders_a_clean_line(self):
        graph = json.loads((self.project / "research" / GRAPH).read_text(encoding="utf-8"))
        graph["tickets"].append({
            "id": 99, "kind": "code", "status": "open", "difficulty": 1, "blocked_by": [],
            "blocking": None, "human_only": False, "touches": [], "resources": None,
            "role": "coder", "skills": [], "attempt": 0,
        })
        # The snapshot is left as it is, so the graph is not regenerated over the entry.
        (self.project / "research" / GRAPH).write_text(json.dumps(graph) + "\n", encoding="utf-8")
        text = render_status(status_view(self.project))
        self.assertIn("#99", text)
        for line in text.splitlines():
            self.assertEqual(line, line.rstrip(), "a rendered line carries trailing spaces")


class StatusCommandTest(ProjectTestCase):
    def run_cli(self, *args):
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home))
        return subprocess.run([sys.executable, "-m", "wayline", *args], cwd=str(HARNESS_ROOT),
                              capture_output=True, text=True, timeout=120, env=environment)

    def test_status_reads_the_project_the_flag_names(self):
        project = self.ledger_fixture()
        done = self.run_cli("status", "--project", str(project))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("frontier (2)", done.stdout)
        self.assertIn("Train the baseline model", done.stdout)

    def test_status_reads_the_active_project_without_a_flag(self):
        project = self.temp / "study"
        init_project(project, harness_root=self.fake_harness())
        done = self.run_cli("status")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("[active]", done.stdout)
        self.assertIn("frontier (0)", done.stdout)

    def test_status_prints_the_view_as_json(self):
        project = self.ledger_fixture()
        done = self.run_cli("status", "--project", str(project), "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        view = json.loads(done.stdout)
        self.assertEqual([entry["id"] for entry in view["frontier"]], [5, 10])
        self.assertEqual(view["problems"], [])

    def test_status_without_an_active_project_exits_1_and_says_what_to_run(self):
        done = self.run_cli("status")
        self.assertEqual(done.returncode, 1)
        self.assertIn("no active project", done.stderr)

    def test_status_over_a_ledger_with_a_problem_exits_1(self):
        project = self.ledger_fixture()
        (project / "research" / "jobs" / "j-0003.json").write_text("{}\n", encoding="utf-8")
        done = self.run_cli("status", "--project", str(project))
        self.assertEqual(done.returncode, 1)
        self.assertIn("problems (1)", done.stdout)


if __name__ == "__main__":
    unittest.main()
