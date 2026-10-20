"""The stopping rule and the budgets as plain functions (Implementation Decision 17; ticket 87).

The rule is read from `harness.json` and judged against the objectives' records and the goals' `progress`; the
budgets are counted from replayed journals; the switches write `harness.json` and journal `control` in a temporary
project. The conductor's half, the rule read every wave and the empty frontier, is `tests/test_stop_rule.py`.
"""

import io
import json
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase, open_objective
from wayline import cli, stopping
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger, make_event
from wayline.pacing import epoch
from wayline.project import ProjectError, init_project, read_harness


def objective(identifier, status="open", target=None, metric=None):
    measure = None if metric is None else {
        "metric": metric, "direction": "up", "target": target, "held_out_split": None, "eval_command": "cat {artifact}",
        "baseline": {"value": None, "source": None}, "dataset_or_split": None, "min_seeds": None}
    return {"id": identifier, "text": "Question %s?" % identifier, "measure": measure, "status": status,
            "answer": None if status == "open" else "closed", "evidence": [], "reframed_as": None}


def kept(goal, value):
    return {"goal": goal, "metric": "auroc", "value": value, "kept": True}


def at(text):
    return epoch(text)


def event(name, payload, ts, job=None):
    return make_event(name, payload, ts=ts, job=job)


class RuleTest(ProjectTestCase):
    def test_the_rule_is_objectives_by_default(self):
        self.assertEqual(stopping.rule_of({}), "objectives")
        self.assertEqual(stopping.rule_of({"stop_when": "frontier"}), "frontier")
        self.assertEqual(stopping.rule_of({"stop_when": ["O2", "O1"]}), ["O2", "O1"])

    def test_what_the_rule_waits_on(self):
        records = [objective("O1"), objective("O2", "parked"), objective("O3")]
        self.assertEqual([found["id"] for found in stopping.waited("objectives", records)], ["O1", "O3"])
        self.assertEqual([found["id"] for found in stopping.waited(["O3", "O2"], records)], ["O3"])
        self.assertEqual(stopping.waited("frontier", records), [])

    def test_objectives_ends_once_no_objective_is_open(self):
        self.assertIsNone(stopping.rule_end("objectives", [objective("O1"), objective("O2", "answered")], []))
        self.assertEqual(stopping.rule_end("objectives", [objective("O1", "answered"), objective("O2", "dropped")], []),
                         "objectives_closed")

    def test_a_list_ends_once_the_objectives_it_names_are_closed(self):
        records = [objective("O1", "answered"), objective("O2")]
        self.assertEqual(stopping.rule_end(["O1"], records, []), "objectives_closed")
        self.assertIsNone(stopping.rule_end(["O1", "O2"], records, []))

    def test_goal_reached_when_every_objective_it_closed_was_a_goal_that_reached_its_target(self):
        records = [objective("O1", "answered", target=0.8, metric="auroc"), objective("O2", "answered", target=0.9, metric="auroc")]
        self.assertEqual(stopping.rule_end("objectives", records, [kept("O1", 0.85), kept("O2", 0.95)]), "goal_reached")
        self.assertEqual(stopping.rule_end("objectives", records, [kept("O1", 0.85)]), "objectives_closed")
        self.assertEqual(stopping.rule_end(["O1"], records, [kept("O1", 0.85)]), "goal_reached")

    def test_frontier_never_ends_on_the_objectives(self):
        self.assertIsNone(stopping.rule_end("frontier", [objective("O1", "answered")], []))

    def test_a_project_that_records_no_objective_runs_to_its_frontier(self):
        self.assertIsNone(stopping.rule_end("objectives", [], []))
        self.assertEqual(stopping.waited("objectives", []), [])

    def test_the_goals_reached_and_still_open_are_the_ones_code_writes_reached(self):
        records = [objective("O1", target=0.8, metric="auroc"), objective("O2", target=0.9, metric="auroc"),
                   objective("O3", "answered", target=0.1, metric="auroc"), objective("O4")]
        self.assertEqual([found["id"] for found in stopping.reached_goals(records, [kept("O1", 0.8), kept("O2", 0.85),
                                                                                     kept("O3", 0.9)])], ["O1"])


class BudgetTest(ProjectTestCase):
    def test_wall_clock_is_counted_from_the_end_of_setup(self):
        events = [event("phase", {"from": "P2", "to": "P3"}, "2026-10-01T08:00:00.000Z"),
                  event("phase", {"from": "P4", "to": "P5"}, "2026-10-01T10:00:00.000Z"),
                  event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "autonomous", "radius": "moderate",
                                        "pid": 1}, "2026-10-01T10:30:00.000Z")]
        self.assertEqual(stopping.setup_ended_at(events), "2026-10-01T10:00:00.000Z")
        self.assertAlmostEqual(stopping.wallclock_hours(events, at("2026-10-01T13:00:00Z")), 3.0)

    def test_without_a_phase_the_first_run_ends_setup(self):
        events = [event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints", "radius": "moderate",
                                        "pid": 1}, "2026-10-01T10:00:00.000Z")]
        self.assertAlmostEqual(stopping.wallclock_hours(events, at("2026-10-01T10:30:00Z")), 0.5)
        self.assertEqual(stopping.wallclock_hours([], at("2026-10-01T10:30:00Z")), 0.0)

    def test_gpu_hours_are_each_job_s_hours_times_the_gpus_it_held(self):
        two = ["GPU-a", "GPU-b"]
        events = [
            event("job_launched", {"job": "j1", "ticket": 1, "gpu_uuids": two}, "2026-10-01T10:00:00.000Z", job="j1"),
            event("job_finished", {"job": "j1", "exit_code": 0, "seconds": 5400, "outputs_ok": True}, "2026-10-01T11:30:00.000Z", job="j1"),
            event("job_launched", {"job": "j2", "ticket": 2, "gpu_uuids": ["GPU-a"]}, "2026-10-01T10:00:00.000Z", job="j2"),
            event("job_failed", {"job": "j2", "reason": "oom", "log_tail": ""}, "2026-10-01T10:30:00.000Z", job="j2"),
            event("job_launched", {"job": "j3", "ticket": 3, "gpu_uuids": []}, "2026-10-01T10:00:00.000Z", job="j3"),
            event("job_launched", {"job": "j4", "ticket": 4, "gpu_uuids": ["GPU-b"]}, "2026-10-01T12:00:00.000Z", job="j4"),
        ]
        # j1: 1.5 h on two GPUs; j2: 0.5 h on one; j3: none held; j4: still running, 1 h so far on one.
        self.assertAlmostEqual(stopping.gpu_hours(events, at("2026-10-01T13:00:00Z")), 3.0 + 0.5 + 1.0)

    def test_a_budget_is_spent_at_its_limit_and_none_is_no_limit(self):
        events = [event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "autonomous", "radius": "moderate",
                                        "pid": 1}, "2026-10-01T10:00:00.000Z"),
                  event("job_launched", {"job": "j1", "ticket": 1, "gpu_uuids": ["GPU-a"]}, "2026-10-01T10:00:00.000Z", job="j1")]
        now = at("2026-10-01T12:00:00Z")
        self.assertEqual(stopping.spent({"budgets": {"wallclock_hours": 2, "gpu_hours": None}}, events, now)[0][:2],
                         ("wallclock_hours", 2.0))
        self.assertEqual([name for name, _, _ in stopping.spent({"budgets": {"gpu_hours": 1.5}}, events, now)], ["gpu_hours"])
        self.assertEqual(stopping.spent({"budgets": {"wallclock_hours": 3, "gpu_hours": 3}}, events, now), [])
        self.assertEqual(stopping.spent({}, events, now), [])

    def test_a_budget_of_zero_is_spent_only_by_the_first_hour_used(self):
        """`gpu_hours: 0` is a project that uses no GPU: nothing run yet spends it, a GPU job does."""
        events = [event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "autonomous", "radius": "moderate",
                                        "pid": 1}, "2026-10-01T10:00:00.000Z")]
        now = at("2026-10-01T12:00:00Z")
        self.assertEqual(stopping.spent({"budgets": {"gpu_hours": 0}}, events, now), [])
        events.append(event("job_launched", {"job": "j1", "ticket": 1, "gpu_uuids": ["GPU-a"]}, "2026-10-01T11:00:00.000Z", job="j1"))
        self.assertEqual([name for name, _, _ in stopping.spent({"budgets": {"gpu_hours": 0}}, events, now)], ["gpu_hours"])


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class SwitchTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)

    def controls(self):
        events, _ = Ledger(self.project).read_events()
        return [entry["payload"] for entry in events if entry["event"] == "control"]

    def test_the_harness_schema_takes_the_rule_and_no_usage_windows(self):
        schema = load_schema("harness")
        harness = read_harness(self.project)
        for rule in ("objectives", "frontier", ["O1", "O2"]):
            check(dict(harness, stop_when=rule), schema, name="harness.json")
        for wrong in ("goal_reached", "graph_empty", [], ["goal"]):
            with self.subTest(rule=wrong), self.assertRaises(ValueError):
                check(dict(harness, stop_when=wrong), schema, name="harness.json")
        with self.assertRaises(ValueError):
            check(dict(harness, budgets={"usage_windows": 3}), schema, name="harness.json")

    def test_stop_when_writes_harness_json_and_journals_control(self):
        open_objective(self.project)
        report = stopping.set_stop_when(self.project, ["O1"])
        self.assertEqual((report["from"], report["to"], report["changed"]), ("objectives", ["O1"], True))
        self.assertEqual(read_harness(self.project)["stop_when"], ["O1"])
        self.assertEqual(self.controls()[-1], {"command": "stop_when", "args": {"stop_when": ["O1"], "from": "objectives"},
                                               "by": "cli"})
        self.assertFalse(stopping.set_stop_when(self.project, ["O1"])["changed"])
        self.assertEqual(len(self.controls()), 1)

    def test_a_list_naming_an_objective_the_project_does_not_hold_is_refused(self):
        with self.assertRaisesRegex(ProjectError, "O7"):
            stopping.set_stop_when(self.project, ["O7"])
        with self.assertRaisesRegex(ProjectError, "objectives, frontier, or a list"):
            stopping.set_stop_when(self.project, "goal_reached")
        self.assertNotIn("stop_when", read_harness(self.project))
        self.assertEqual(self.controls(), [])

    def test_budget_writes_harness_json_and_journals_control(self):
        report = stopping.set_budget(self.project, "wallclock_hours", 12)
        self.assertEqual((report["from"], report["to"], report["changed"], report["raised"]), (None, 12, True, False))
        self.assertEqual(read_harness(self.project)["budgets"]["wallclock_hours"], 12)
        self.assertEqual(self.controls()[-1], {"command": "budget", "args": {"name": "wallclock_hours", "value": 12, "from": None},
                                               "by": "cli"})
        self.assertFalse(stopping.set_budget(self.project, "wallclock_hours", 6)["raised"])
        self.assertTrue(stopping.set_budget(self.project, "wallclock_hours", 20)["raised"])
        self.assertTrue(stopping.set_budget(self.project, "wallclock_hours", None)["raised"])
        self.assertFalse(stopping.set_budget(self.project, "gpu_hours", None)["changed"])

    def test_a_budget_that_is_no_budget_or_negative_is_refused(self):
        for name, value in (("usage_windows", 3), ("gpu_hours", -1), ("gpu_hours", True)):
            with self.subTest(name=name, value=value), self.assertRaises(ProjectError):
                stopping.set_budget(self.project, name, value)

    def test_after_setup_the_change_is_said_to_be_on_the_irreversible_list(self):
        self.assertFalse(stopping.set_budget(self.project, "gpu_hours", 4)["after_setup"])
        Ledger(self.project).append_event("run_started", {"resume": False, "harness_tag": "v1.1.0", "autonomy": "checkpoints",
                                                          "radius": "moderate", "pid": 1})
        self.assertTrue(stopping.set_budget(self.project, "gpu_hours", 8)["after_setup"])
        self.assertTrue(stopping.set_stop_when(self.project, "frontier")["after_setup"])

    def test_the_verbs(self):
        open_objective(self.project)
        code, out, err = run("switch", "--stop-when", "O1", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertEqual(read_harness(self.project)["stop_when"], ["O1"])
        code, out, err = run("switch", "--stop-when", "frontier", "--project", str(self.project))
        self.assertEqual((code, read_harness(self.project)["stop_when"]), (0, "frontier"))
        code, out, err = run("switch", "--budget", "gpu_hours=10", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertEqual(read_harness(self.project)["budgets"]["gpu_hours"], 10)
        code, out, err = run("switch", "--budget", "gpu_hours=none", "--project", str(self.project))
        self.assertEqual((code, read_harness(self.project)["budgets"]["gpu_hours"]), (0, None))
        code, _, err = run("switch", "--budget", "weeks=3", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("wallclock_hours", err)
        self.assertEqual(json.loads((self.project / "harness.json").read_text(encoding="utf-8"))["budgets"]["gpu_hours"], None)
