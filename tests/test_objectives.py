"""Objectives, the record and `wayline objective add` (Implementation Decision 17; ticket 76).

Each test lays out a project with `init`, records objectives through the verb or the package function the
dashboard calls, and reads back what a later phase sees: `research/objectives.json`, `research/OBJECTIVES.md`,
the journal, and `wayline status`.
"""

import io
import json
import shlex
import sys
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import cli
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger
from wayline.objectives import ObjectiveError, add_measure, add_objective, change_objective, read_objectives
from wayline.project import ProjectError, init_project, read_harness, set_autonomy, status_view

EVAL_SCRIPT = """import sys
print("scoring", sys.argv[1])
print("auroc: %s" % open(sys.argv[1]).read().strip())
"""


def run(*args):
    """`wayline ...` in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class ObjectivesTestCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        self.owner = self.temp / "owner"
        self.owner.mkdir()

    def write(self, name, text, root=None):
        path = (root or self.owner) / name
        path.write_text(text, encoding="utf-8")
        return path

    def measure(self, **changes):
        """A measure whose eval_command prints the sample artifact's number, and that sample."""
        self.write("eval.py", EVAL_SCRIPT, root=self.project)
        sample = self.write("predictions.txt", "0.83\n")
        measure = {"metric": "auroc", "direction": "up", "target": 0.9, "held_out_split": "split_b",
                   "eval_command": "%s eval.py {artifact}" % shlex.quote(sys.executable)}
        measure.update(changes)
        return self.write("measure.json", json.dumps(measure)), sample

    def record(self):
        return json.loads((self.project / "research" / "objectives.json").read_text(encoding="utf-8"))

    def rendered(self):
        return (self.project / "research" / "OBJECTIVES.md").read_text(encoding="utf-8")

    def objective_events(self):
        events, _ = Ledger(self.project).read_events()
        return [event["payload"] for event in events if event["event"] == "objective"]


class AnObjectiveTest(ObjectivesTestCase):
    def test_an_objective_is_recorded_open_without_a_measure_and_rendered(self):
        code, out, err = run("objective", "add", "Do interaction terms help on the synthetic set?", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("O1", out)
        record = self.record()
        check(record, load_schema("objectives"), name="objectives.json")
        self.assertEqual(record["objectives"], [{
            "id": "O1", "text": "Do interaction terms help on the synthetic set?", "measure": None, "status": "open",
            "answer": None, "evidence": [], "reframed_as": None}])
        text = self.rendered()
        self.assertIn("## O1 Do interaction terms help on the synthetic set?", text)
        self.assertIn("- Status: open", text)
        self.assertIn("- Measure: none (an objective, not a goal)", text)


class AGoalTest(ObjectivesTestCase):
    def test_a_goal_is_recorded_once_its_command_printed_the_metric_on_the_sample(self):
        measure, sample = self.measure()
        code, out, err = run("objective", "add", "Do interaction terms raise the AUROC?", "--measure", str(measure),
                             "--sample", str(sample), "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("a goal", out)
        self.assertIn("printed 0.83", out)
        recorded = self.record()["objectives"][0]
        self.assertEqual(recorded["measure"], {
            "metric": "auroc", "direction": "up", "target": 0.9, "held_out_split": "split_b",
            "eval_command": "%s eval.py {artifact}" % shlex.quote(sys.executable), "baseline": {"value": None, "source": None},
            "dataset_or_split": None, "min_seeds": None})
        self.assertIn("`auroc` up to 0.9 on the held-out split `split_b`", self.rendered())

    def test_a_measure_whose_command_fails_records_an_objective_without_a_measure_and_says_why(self):
        measure, sample = self.measure(eval_command="echo 'labels file is empty' >&2; exit 3")
        code, out, err = run("objective", "add", "Do interaction terms raise the AUROC?", "--measure", str(measure),
                             "--sample", str(sample), "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("without a measure", out)
        self.assertIn("exit 3", out)
        self.assertIn("labels file is empty", out)
        recorded = self.record()["objectives"][0]
        self.assertEqual((recorded["id"], recorded["status"], recorded["measure"]), ("O1", "open", None))

    def test_a_measure_without_a_sample_is_not_taken(self):
        measure, _ = self.measure()
        objective, result = add_objective(self.project, "Do interaction terms raise the AUROC?", measure=json.loads(measure.read_text()))
        self.assertEqual(result.kind, "missing")
        self.assertIn("--sample", result.reason)
        self.assertIsNone(objective["measure"])

    def test_a_command_that_prints_no_number_for_the_metric_is_not_taken(self):
        measure, sample = self.measure(eval_command="echo 'read 1200 rows'; echo done")
        objective, result = add_objective(self.project, "Q?", measure=json.loads(measure.read_text()), sample=sample)
        self.assertEqual(result.kind, "no_number")
        self.assertIsNone(objective["measure"])

    def test_a_null_target_is_accepted(self):
        measure, sample = self.measure(target=None)
        objective, result = add_objective(self.project, "How low can the loss go?", measure=json.loads(measure.read_text()), sample=sample)
        self.assertTrue(result.accepted, result.reason)
        self.assertIsNone(objective["measure"]["target"])
        self.assertIsNone(self.record()["objectives"][0]["measure"]["target"])
        self.assertIn("no target (keep improving)", self.rendered())

    def test_two_measures_given_for_one_objective_are_refused(self):
        measure, sample = self.measure()
        stated = json.loads(measure.read_text())
        with self.assertRaisesRegex(ObjectiveError, "at most one measure"):
            add_objective(self.project, "Q?", measure=[stated, dict(stated, metric="loss")], sample=sample)
        self.assertEqual(read_objectives(self.project), [], "a refused measure records nothing")

    def test_a_measure_not_in_the_shape_is_refused_by_the_verb_and_nothing_is_recorded(self):
        measure, sample = self.measure(direction="sideways")
        code, _, err = run("objective", "add", "Q?", "--measure", str(measure), "--sample", str(sample), "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("direction", err)
        self.assertFalse((self.project / "research" / "objectives.json").exists())

    def test_a_second_measure_on_a_goal_is_refused(self):
        measure, sample = self.measure()
        stated = json.loads(measure.read_text())
        objective, _ = add_objective(self.project, "Q?", measure=stated, sample=sample)
        with self.assertRaisesRegex(ObjectiveError, "at most one"):
            add_measure(self.project, objective["id"], dict(stated, metric="loss"), sample=sample)
        self.assertEqual(self.record()["objectives"][0]["measure"]["metric"], "auroc")

    def test_an_objective_without_a_measure_becomes_a_goal_when_given_one(self):
        objective, _ = add_objective(self.project, "Q?")
        measure, sample = self.measure()
        _, result = add_measure(self.project, objective["id"], json.loads(measure.read_text()), sample=sample)
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(self.record()["objectives"][0]["measure"]["metric"], "auroc")
        self.assertEqual([event["measure"] for event in self.objective_events()], [None, "auroc"])


class ChangesTest(ObjectivesTestCase):
    def test_each_change_journals_an_objective_event_with_who_made_it(self):
        add_objective(self.project, "Do interaction terms help?")
        add_objective(self.project, "Is the effect linear?", by="decider")
        change_objective(self.project, "O1", "answered", by="code", answer="yes, by 0.04 AUROC",
                         evidence=["res:results/auroc.json#auroc"])
        self.assertEqual(self.objective_events(), [
            {"id": "O1", "text": "Do interaction terms help?", "status": "open", "measure": None, "by": "owner"},
            {"id": "O2", "text": "Is the effect linear?", "status": "open", "measure": None, "by": "decider"},
            {"id": "O1", "text": "Do interaction terms help?", "status": "answered", "measure": None, "by": "code"},
        ])

    def test_a_change_by_anyone_else_is_refused(self):
        with self.assertRaises(ObjectiveError):
            add_objective(self.project, "Q?", by="worker")
        self.assertEqual(read_objectives(self.project), [])

    def test_objectives_md_renders_in_id_order_with_status_measure_answer_and_evidence(self):
        for number in range(1, 11):
            add_objective(self.project, "Question %d?" % number)
        change_objective(self.project, "O2", "answered", by="owner", answer="no", evidence=["res:results/q2.json#effect", "ref:smith2020"])
        text = self.rendered()
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, ["## O%d Question %d?" % (number, number) for number in range(1, 11)])
        answered = text.split("## O2 ")[1].split("## O3 ")[0]
        self.assertIn("- Status: answered", answered)
        self.assertIn("- Answer: no", answered)
        self.assertIn("- Evidence: `res:results/q2.json#effect`, `ref:smith2020`", answered)
        self.assertIn("- Answer: none yet", text.split("## O3 ")[1])

    def test_ids_are_never_reused_after_a_drop(self):
        add_objective(self.project, "First?")
        add_objective(self.project, "Second?")
        change_objective(self.project, "O2", "dropped", by="owner", answer="out of scope")
        third, _ = add_objective(self.project, "Third?")
        self.assertEqual(third["id"], "O3")
        self.assertEqual([(objective["id"], objective["status"]) for objective in read_objectives(self.project)],
                         [("O1", "open"), ("O2", "dropped"), ("O3", "open")])

    def test_a_reframing_names_its_successor(self):
        add_objective(self.project, "Which features matter?")
        with self.assertRaisesRegex(ObjectiveError, "replaced it"):
            change_objective(self.project, "O1", "reframed", by="owner")
        add_objective(self.project, "Do the top three features carry the signal?")
        with self.assertRaisesRegex(ObjectiveError, "itself"):
            change_objective(self.project, "O1", "reframed", by="owner", reframed_as="O1")
        change_objective(self.project, "O1", "reframed", by="owner", reframed_as="O2")
        self.assertIn("- Reframed as: O2", self.rendered())


class AutonomyTest(ObjectivesTestCase):
    def test_the_switch_to_autonomous_is_refused_with_no_objective_open_and_then_allowed(self):
        code, _, err = run("switch", "--autonomy", "autonomous", "--project", str(self.project))
        self.assertNotEqual(code, 0)
        self.assertIn("no objective is open", err)
        self.assertIn("wayline objective add", err)
        self.assertEqual(read_harness(self.project)["autonomy"], "checkpoints")
        add_objective(self.project, "First?")
        change_objective(self.project, "O1", "parked", by="owner", answer="later")
        self.assertNotEqual(run("switch", "--autonomy", "autonomous", "--project", str(self.project))[0], 0,
                            "a parked objective is not an open one")
        add_objective(self.project, "Second?")
        code, _, err = run("switch", "--autonomy", "autonomous", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertEqual(read_harness(self.project)["autonomy"], "autonomous")

    def test_the_package_function_the_dashboard_calls_refuses_too(self):
        with self.assertRaisesRegex(ProjectError, "wayline objective add"):
            set_autonomy(self.project, "autonomous", by="dashboard")
        set_autonomy(self.project, "interactive")  # the other levels need no objective
        self.assertEqual(read_harness(self.project)["autonomy"], "interactive")


class StatusTest(ObjectivesTestCase):
    def test_status_reads_each_objective_s_status(self):
        measure, sample = self.measure()
        add_objective(self.project, "Do interaction terms raise the AUROC?", measure=json.loads(measure.read_text()), sample=sample)
        add_objective(self.project, "Is the effect linear?")
        change_objective(self.project, "O2", "parked", by="owner", answer="after O1")
        view = status_view(self.project)
        self.assertEqual([(entry["id"], entry["status"], entry["metric"]) for entry in view["objectives"]],
                         [("O1", "open", "auroc"), ("O2", "parked", None)])
        code, out, err = run("status", "--project", str(self.project))
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("objectives  1 open of 2", lines)
        self.assertIn("  O1  open    Do interaction terms raise the AUROC?  (goal: `auroc` up to 0.9)", lines)
        self.assertIn("  O2  parked  Is the effect linear?", lines)
        self.assertFalse([line for line in lines if line.startswith("goal ")], "the objectives' statuses take the goal line's place")

    def test_an_unreadable_record_is_a_problem_not_a_crash(self):
        (self.project / "research" / "objectives.json").write_text("[]\n", encoding="utf-8")
        view = status_view(self.project)
        self.assertEqual(view["objectives"], [])
        self.assertTrue([problem for problem in view["problems"] if problem.startswith("objectives.json")], view["problems"])

    def test_status_says_when_no_objective_is_recorded(self):
        self.assertEqual(status_view(self.project)["objectives"], [])
        self.assertIn("objectives  none recorded (wayline objective add)", run("status", "--project", str(self.project))[1].splitlines())


class GoalJsonStillReadTest(ObjectivesTestCase):
    """The expand step: a project with both a `GOAL.json` and objectives behaves as it did on its goal."""

    def setUp(self):
        super().setUp()
        self.project = self.ledger_fixture()
        add_objective(self.project, "Do interaction terms help?")

    def test_the_goal_json_readers_still_read_it(self):
        from wayline import goal
        self.assertEqual(goal.read_goal(Ledger(self.project))["metric"], "auroc")
        self.assertEqual(status_view(self.project)["goal"]["metric"], "auroc")
        self.assertEqual(status_view(self.project)["objectives"][0]["id"], "O1")
