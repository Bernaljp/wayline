"""Phase P0: intake, the goal, and `intake --goal` (Implementation Decisions 10; BRIEF 6.4).

Each test lays out a project with `init`, hands `wayline intake` one of the shapes an owner arrives
with, and reads back what a later phase sees: `research/INTAKE.md` (through the dossier module's own
reference reader, which is what `absorb` uses), `harness.json`, `GOAL.json`, and the journal.
"""

import importlib.util
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import cli
from wayline.dossier import read_intake
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger
from wayline.project import init_project, read_harness

SECTIONS = ["Intent", "References", "Data", "Code", "Constraints", "Autonomy", "Radius", "Budgets",
            "Decisions that stay human-only", "Goal"]

EVAL_SCRIPT = """import os, sys
artifact = sys.argv[1]
assert artifact == os.environ["WAYLINE_ARTIFACT"], "the artifact reaches the command both ways"
print("scoring", artifact, "with 3 folds")
print("auroc: %s" % open(artifact).read().strip())
"""

# A PDF as a publisher ships one: the DOI sits in the uncompressed XMP packet, the text does not.
PDF = b"""%PDF-1.7
1 0 obj << /Type /Metadata /Subtype /XML /Length 120 >> stream
<x:xmpmeta xmlns:x="adobe:ns:meta/"><prism:doi>10.1038/s41592-019-0686-2</prism:doi></x:xmpmeta>
endstream endobj
%%EOF
"""


def run(*args, stdin=None):
    """`wayline intake ...` in-process; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin or "")):
        code = cli.main(["intake", *args])
    return code, out.getvalue(), err.getvalue()


def sections(text):
    """The `## ` headings of a markdown file, in order, with the body under each."""
    found, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            current = [line[3:].strip(), []]
            found.append(current)
        elif current is not None:
            current[1].append(line)
    return [(name, "\n".join(body).strip()) for name, body in found]


class IntakeTestCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        self.owner = self.temp / "owner"  # what the owner hands over lives outside the project
        self.owner.mkdir()

    def intake_md(self):
        return (self.project / "research" / "INTAKE.md").read_text(encoding="utf-8")

    def section(self, name):
        return dict(sections(self.intake_md()))[name]

    def goal_path(self):
        return self.project / "research" / "GOAL.json"

    def decisions(self):
        events, _ = Ledger(self.project).read_events()
        return [event for event in events if event["event"] == "decision"]

    def write(self, name, text, root=None):
        path = (root or self.owner) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def measurable_goal(self, target=0.9, **changes):
        """A goal whose eval_command prints the sample artifact's number, and that sample."""
        self.write("eval.py", EVAL_SCRIPT, root=self.project)
        sample = self.write("predictions.txt", "0.83\n")
        goal = {"metric": "auroc", "direction": "up", "target": target, "held_out_split": "split_b",
                "eval_command": "%s eval.py {artifact}" % shlex.quote(sys.executable)}
        goal.update(changes)
        return self.write("goal-%s.json" % target, json.dumps(goal)), sample


class VagueIntentWithReferencesAndAGoalTest(IntakeTestCase):
    """A paragraph, a reference list, a PDF, and a goal with a sample artifact."""

    def setUp(self):
        super().setUp()
        references = self.write("refs.md", "# what I have been reading\n\n- arXiv:1706.03762\n"
                                           "- https://doi.org/10.1371/journal.pcbi.1008074\n"
                                           "- Highly accurate protein structure prediction with AlphaFold\n")
        pdf = self.owner / "scipy.pdf"
        pdf.write_bytes(PDF)
        goal, sample = self.measurable_goal()
        self.code, self.out, self.err = run(
            "--project", str(self.project), "I think interaction terms help on the synthetic set, maybe?",
            str(references), str(pdf), "--goal", str(goal), "--sample", str(sample))

    def test_the_intake_succeeds(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertIn("INTAKE.md", self.out)

    def test_every_section_is_present_in_order_and_none_is_empty(self):
        found = sections(self.intake_md())
        self.assertEqual([name for name, _ in found], SECTIONS)
        for name, body in found:
            self.assertTrue(body, "section %s is empty" % name)

    def test_the_intent_is_the_owners_words(self):
        self.assertIn("I think interaction terms help on the synthetic set, maybe?", self.section("Intent"))

    def test_absorb_reads_every_reference_including_the_one_inside_the_pdf(self):
        found = {(reference.kind, reference.value) for reference in read_intake(self.project)}
        self.assertEqual(found, {
            ("arxiv", "1706.03762"),
            ("doi", "10.1371/journal.pcbi.1008074"),
            ("title", "Highly accurate protein structure prediction with AlphaFold"),
            ("doi", "10.1038/s41592-019-0686-2"),
        })

    def test_the_goal_is_written_whole_with_nothing_unstated_guessed(self):
        goal = json.loads(self.goal_path().read_text(encoding="utf-8"))
        check(goal, load_schema("goal"))
        self.assertEqual((goal["metric"], goal["direction"], goal["target"]), ("auroc", "up", 0.9))
        self.assertEqual(goal["held_out_split"], "split_b")
        self.assertIsNone(goal["dataset_or_split"])
        self.assertEqual(goal["baseline"], {"value": None, "source": None})
        self.assertEqual(goal["budget"], {"gpu_hours": None, "wallclock": None, "usage_windows": None})
        self.assertEqual(goal["stop_when"], "goal_reached")

    def test_the_goal_section_reports_what_the_command_measured(self):
        self.assertIn("0.83", self.section("Goal"))

    def test_the_goal_is_journaled_as_a_decision_by_the_human(self):
        decisions = self.decisions()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["payload"]["decided_by"], "human")
        self.assertIn("auroc", decisions[0]["payload"]["answer"])

    def test_harness_json_keeps_the_defaults_and_records_the_human_only_classes(self):
        harness = read_harness(self.project)
        self.assertEqual(harness["autonomy"], "checkpoints")
        self.assertEqual(harness["radius"], "moderate")
        self.assertEqual(harness["human_only"], ["goal", "data"])
        self.assertIn("`goal`", self.section("Decisions that stay human-only"))
        self.assertIn("`data`", self.section("Decisions that stay human-only"))


class PrecisePlanWithARepositoryTest(IntakeTestCase):
    """A plan, the repository it builds on, a data pointer, and every setting stated."""

    def setUp(self):
        super().setUp()
        self.repository = self.owner / "analysis"
        self.repository.mkdir()
        (self.repository / "train.py").write_text("print('train')\n", encoding="utf-8")
        git = ["git", "-C", str(self.repository), "-c", "user.name=owner", "-c", "user.email=owner@example.org"]
        subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-qm", "start"], check=True)
        self.head = subprocess.run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        plan = self.write("plan.md", "# Plan\n\n1. Fit the baseline on split_a.\n2. Add pairwise interaction terms.\n"
                                     "3. Report held-out AUROC on split_b with three seeds.\n")
        data = self.write("data/cells.csv", "x,y\n1,0\n")
        self.code, self.out, self.err = run(
            "--project", str(self.project), "--plan", str(plan), str(self.repository), "--data", str(data),
            "--data", "split_b is held out and never leaves this machine",
            "--constraint", "no new dependencies beyond scikit-learn",
            "--autonomy", "autonomous", "--radius", "strict",
            "--gpu-hours", "10", "--wallclock-hours", "48", "--usage-windows", "4",
            "--human-only", "baselines: which baselines the claims are compared against")

    def test_the_intake_succeeds_without_a_goal(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertFalse(self.goal_path().exists())
        self.assertEqual(self.decisions(), [])
        self.assertIn("No quantitative goal", self.section("Goal"))

    def test_the_plan_is_quoted_whole_as_the_intent(self):
        intent = self.section("Intent")
        self.assertIn("plan.md", intent)
        for step in ("Fit the baseline on split_a.", "Add pairwise interaction terms.", "three seeds."):
            self.assertIn(step, intent)

    def test_the_repository_is_pinned_to_its_commit(self):
        code = self.section("Code")
        self.assertIn(self.head, code)
        self.assertIn("main", code)

    def test_the_data_pointers_are_listed_as_given(self):
        data = self.section("Data")
        self.assertIn("cells.csv", data)
        self.assertIn("a file", data)
        self.assertIn("split_b is held out and never leaves this machine", data)

    def test_there_are_no_references_and_absorb_looks_nothing_up(self):
        self.assertEqual(read_intake(self.project), [])

    def test_a_later_intake_that_names_no_class_keeps_the_ones_the_owner_added(self):
        code, _, err = run("--project", str(self.project), "--intent", "the same question, restated")
        self.assertEqual(code, 0, err)
        harness = read_harness(self.project)
        self.assertEqual(harness["human_only"], ["goal", "data", "baselines"])
        self.assertEqual((harness["autonomy"], harness["radius"]), ("autonomous", "strict"))

    def test_the_settings_land_in_harness_json_and_in_intake_md(self):
        harness = read_harness(self.project)
        self.assertEqual(harness["autonomy"], "autonomous")
        self.assertEqual(harness["radius"], "strict")
        self.assertEqual(harness["budgets"], {"gpu_hours": 10, "wallclock_hours": 48, "usage_windows": 4})
        self.assertEqual(harness["human_only"], ["goal", "data", "baselines"])
        self.assertIn("`autonomous`", self.section("Autonomy"))
        self.assertIn("`strict`", self.section("Radius"))
        self.assertIn("48", self.section("Budgets"))
        self.assertIn("which baselines the claims are compared against", self.section("Decisions that stay human-only"))
        self.assertIn("no new dependencies beyond scikit-learn", self.section("Constraints"))


class BadGoalTest(IntakeTestCase):
    """A goal nothing can measure is rejected with the reason, and the intake is written without it."""

    def intake_with(self, goal, sample=True):
        path = self.write("goal.json", json.dumps(goal))
        args = ["--project", str(self.project), "--intent", "find out whether it works", "--goal", str(path)]
        if sample:
            args += ["--sample", str(self.write("sample.txt", "0.5\n"))]
        return run(*args)

    def assert_rejected(self, result, words):
        code, out, err = result
        self.assertEqual(code, 1, out + err)
        self.assertIn("rejected", err)
        for word in words:
            self.assertIn(word, err)
            self.assertIn(word, self.section("Goal"))
        self.assertFalse(self.goal_path().exists())
        self.assertEqual(self.decisions(), [])
        self.assertIn("find out whether it works", self.section("Intent"), "a rejected goal is not a failed intake")

    def test_a_goal_with_no_sample_artifact_is_rejected_as_missing_even_when_its_command_needs_none(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "echo 'auroc: 0.95'"}
        self.assert_rejected(self.intake_with(goal, sample=False), ["missing", "--sample"])

    def test_a_rejected_goal_changes_nothing_in_harness_json(self):
        before = (self.project / "harness.json").read_bytes()
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "exit 3",
                "budget": {"gpu_hours": 999, "wallclock": None, "usage_windows": None}}
        self.assert_rejected(self.intake_with(goal), ["fails"])
        harness = read_harness(self.project)
        self.assertIsNone(harness["budgets"]["gpu_hours"])
        self.assertNotEqual((self.project / "harness.json").read_bytes(), before, "the intake itself is still recorded")

    def test_a_goal_without_an_eval_command_is_rejected_as_missing(self):
        self.assert_rejected(self.intake_with({"metric": "auroc", "direction": "up", "target": 0.9}), ["missing", "eval_command"])

    def test_a_command_the_shell_cannot_find_is_rejected_as_missing(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "wayline-no-such-scorer {artifact}"}
        self.assert_rejected(self.intake_with(goal), ["missing", "wayline-no-such-scorer"])

    def test_a_command_that_needs_an_artifact_and_got_none_is_rejected_as_missing(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "cat {artifact}"}
        self.assert_rejected(self.intake_with(goal, sample=False), ["missing", "--sample"])

    def test_a_command_that_fails_is_rejected_with_its_exit_code_and_output(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "echo 'labels file is empty' >&2; exit 3"}
        self.assert_rejected(self.intake_with(goal), ["fails", "exit 3", "labels file is empty"])

    def test_a_command_that_prints_no_number_is_rejected(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "echo scoring done"}
        self.assert_rejected(self.intake_with(goal), ["no number", "auroc"])

    def test_a_number_that_is_not_the_metric_is_not_taken_for_it(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "echo 'read 1200 rows'; echo done"}
        self.assert_rejected(self.intake_with(goal), ["no number"])

    def test_a_goal_outside_the_shape_is_rejected_as_invalid(self):
        goal = {"metric": "auroc", "direction": "sideways", "target": "high", "eval_command": "echo 'auroc: 1'"}
        self.assert_rejected(self.intake_with(goal), ["invalid", "direction"])

    def test_a_baseline_number_without_a_source_is_rejected(self):
        goal = {"metric": "auroc", "direction": "up", "target": 0.9, "eval_command": "echo 'auroc: 0.7'", "baseline": {"value": 0.8}}
        self.assert_rejected(self.intake_with(goal), ["invalid", "baseline"])


class GoalLaterTest(IntakeTestCase):
    """`wayline intake --goal` adds a goal after the intake, replaces it, and journals each change."""

    def setUp(self):
        super().setUp()
        code, _, err = run("--project", str(self.project), "--intent", "see whether interaction terms help",
                           "--constraint", "CPU only")
        self.assertEqual(code, 0, err)
        self.before = self.intake_md()

    def test_a_goal_added_later_is_written_journaled_and_reflected_in_intake_md(self):
        goal, sample = self.measurable_goal()
        code, out, err = run("--project", str(self.project), "--goal", str(goal), "--sample", str(sample))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.goal_path().read_text(encoding="utf-8"))["target"], 0.9)
        decisions = self.decisions()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["payload"]["decided_by"], "human")
        self.assertIsNone(decisions[0]["ticket"])
        self.assertIn("0.83", self.section("Goal"))
        unchanged = [(name, body) for name, body in sections(self.before) if name != "Goal"]
        self.assertEqual([(name, body) for name, body in sections(self.intake_md()) if name != "Goal"], unchanged)

    def test_a_replaced_goal_names_the_one_it_replaces(self):
        first, sample = self.measurable_goal(target=0.85)
        self.assertEqual(run("--project", str(self.project), "--goal", str(first), "--sample", str(sample))[0], 0)
        second, sample = self.measurable_goal(target=0.9)
        code, _, err = run("--project", str(self.project), "--goal", str(second), "--sample", str(sample),
                           "--rationale", "the position memo says 0.85 is already published")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.goal_path().read_text(encoding="utf-8"))["target"], 0.9)
        decisions = self.decisions()
        self.assertEqual(len(decisions), 2)
        self.assertIn("the position memo says 0.85 is already published", decisions[1]["payload"]["rationale"])
        self.assertIn("0.85", decisions[1]["payload"]["rationale"])

    def test_the_same_goal_twice_changes_nothing(self):
        goal, sample = self.measurable_goal()
        self.assertEqual(run("--project", str(self.project), "--goal", str(goal), "--sample", str(sample))[0], 0)
        code, out, _ = run("--project", str(self.project), "--goal", str(goal), "--sample", str(sample))
        self.assertEqual(code, 0)
        self.assertIn("unchanged", out)
        self.assertEqual(len(self.decisions()), 1)

    def test_a_rejected_replacement_leaves_the_standing_goal_alone(self):
        goal, sample = self.measurable_goal()
        run("--project", str(self.project), "--goal", str(goal), "--sample", str(sample))
        standing, journal = self.goal_path().read_bytes(), (self.project / "research" / "journal.jsonl").read_bytes()
        bad = self.write("bad.json", json.dumps({"metric": "auroc", "direction": "up", "target": 0.95, "eval_command": "false"}))
        code, _, err = run("--project", str(self.project), "--goal", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("rejected", err)
        self.assertEqual(self.goal_path().read_bytes(), standing)
        self.assertEqual((self.project / "research" / "journal.jsonl").read_bytes(), journal)

    def test_the_goal_can_arrive_on_stdin(self):
        goal, sample = self.measurable_goal()
        code, _, err = run("--project", str(self.project), "--goal", "-", "--sample", str(sample),
                           stdin=goal.read_text(encoding="utf-8"))
        self.assertEqual(code, 0, err)
        self.assertTrue(self.goal_path().exists())


class SpecOnStdinTest(IntakeTestCase):
    """The skill's path: one JSON spec on stdin, the ledger writing what the conversation settled."""

    def test_a_spec_on_stdin_writes_the_same_intake_the_flags_do(self):
        goal, sample = self.measurable_goal()
        spec = {"intent": "does it help?", "references": ["10.1038/s41586-020-2649-2"], "data": ["data/ lives on the NAS"],
                "constraints": ["finish by October"], "autonomy": "interactive", "radius": "exploratory",
                "budgets": {"gpu_hours": 2}, "human_only": ["methods"],
                "goal": json.loads(goal.read_text(encoding="utf-8")), "sample": str(sample)}
        code, _, err = run("--project", str(self.project), "--from", "-", stdin=json.dumps(spec))
        self.assertEqual(code, 0, err)
        harness = read_harness(self.project)
        self.assertEqual((harness["autonomy"], harness["radius"]), ("interactive", "exploratory"))
        self.assertEqual(harness["human_only"], ["goal", "data", "methods"])
        self.assertEqual(harness["budgets"]["gpu_hours"], 2)
        self.assertEqual([reference.value for reference in read_intake(self.project)], ["10.1038/s41586-020-2649-2"])

    def test_a_spec_with_a_field_intake_does_not_know_is_refused(self):
        code, _, err = run("--project", str(self.project), "--from", "-", stdin=json.dumps({"intent": "x", "deadline": "soon"}))
        self.assertEqual(code, 2)
        self.assertIn("deadline", err)
        self.assertEqual(self.intake_md(), (HARNESS_ROOT / "templates" / "project" / "research" / "INTAKE.md").read_text(encoding="utf-8"))

    def test_an_intake_with_no_intent_and_no_plan_is_refused(self):
        code, _, err = run("--project", str(self.project), "--reference", "arXiv:1706.03762")
        self.assertEqual(code, 2)
        self.assertIn("intent", err)

    def test_a_path_that_does_not_exist_is_refused_rather_than_read_as_the_intent(self):
        code, _, err = run("--project", str(self.project), "the intent", str(self.owner / "missing" / "refs.md"))
        self.assertEqual(code, 2)
        self.assertIn("refs.md", err)


class RecordedIntakeFixtureTest(IntakeTestCase):
    """The skill's fixture: a recorded session's files pass the structural checks it declares."""

    FIXTURE = FIXTURES_DIR / "skill" / "wayline-intake"

    def test_the_recording_passes_every_structural_check(self):
        record = json.loads((self.FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        recorded = self.FIXTURE / "recorded"
        kinds = {check["check"] for check in record["structural"]}
        self.assertTrue({"file_exists", "file_absent", "python", "tool_used"} <= kinds, kinds)
        for check_record in record["structural"]:
            with self.subTest(check=check_record):
                self.assertEqual(structural(check_record, recorded, self.FIXTURE), [])

    def test_the_checks_catch_an_intake_that_lost_a_section_or_invented_a_goal(self):
        record = json.loads((self.FIXTURE / "fixture.json").read_text(encoding="utf-8"))
        broken = self.temp / "broken"
        shutil.copytree(self.FIXTURE / "recorded", broken)
        text = (broken / "research" / "INTAKE.md").read_text(encoding="utf-8")
        (broken / "research" / "INTAKE.md").write_text(text.replace("## Radius", "## Scope"), encoding="utf-8")
        (broken / "research" / "GOAL.json").write_text("{}", encoding="utf-8")
        failures = [problem for check_record in record["structural"] for problem in structural(check_record, broken, self.FIXTURE)]
        self.assertTrue(any("Radius" in problem for problem in failures), failures)
        self.assertTrue(any("GOAL.json" in problem for problem in failures), failures)


def structural(record, root, fixture_dir):
    """The structural checks this fixture uses, evaluated the way research-notes 07 defines them.

    The runner of ticket 44 owns the whole vocabulary; until it lands this is the part of it the
    recorded intake needs, so the recording is checked by the suite rather than by nobody.
    """
    kind = record["check"]
    if kind == "file_exists":
        return [] if (root / record["path"]).is_file() else ["%s does not exist" % record["path"]]
    if kind == "file_absent":
        return [] if not (root / record["path"]).exists() else ["%s exists and must not" % record["path"]]
    if kind == "python":
        spec = importlib.util.spec_from_file_location("fixture_checks", fixture_dir / record["file"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return list(getattr(module, record["fn"])(root))
    if kind in ("tool_used", "tool_not_used"):
        # A recording of several turns of one session holds one trace per turn; the checks read them all.
        traces = sorted(root.glob("trace-*.jsonl"))
        if not traces:
            return ["no trace-*.jsonl in the recording"]
        pattern = re.compile(record.get("input_matches", ""))
        used = False
        for trace in traces:
            for line in trace.read_text(encoding="utf-8").splitlines():
                inner = json.loads(line).get("message")
                for block in (inner.get("content") if isinstance(inner, dict) else None) or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == record["tool"]:
                        used = used or bool(pattern.search(json.dumps(block.get("input"), ensure_ascii=False)))
        if kind == "tool_used":
            return [] if used else ["no %s call matching %r in the trace" % (record["tool"], record.get("input_matches"))]
        return ["a %s call matching %r is in the trace" % (record["tool"], record.get("input_matches"))] if used else []
    return ["check %r is not one this test evaluates" % kind]
