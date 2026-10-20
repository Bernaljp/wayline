"""`fixtures/projects/toy/` (Implementation Decisions 14; M5 criterion 1), offline.

`toy.generate` and `toy.eval` are stdlib, so this suite imports and runs them directly with the
interpreter that runs `python -m unittest`; `toy.train` needs torch and is not imported here at
all (its live GPU run, the retry ladder recovering a real CUDA OOM, is recorded in
`docs/verification/m5.md`, the way the job runner's own live run is recorded in `m2.md`).

The reference resolution and the job runner seam are both exercised here, offline: `absorb --level
0` against the recorded responses under `fixtures/fetch/`, and the ticket's job against the fake
backend, one attempt an OOM the ladder's override recovers from.
"""

import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import resources as r
from wayline.dossier import absorb_level_0
from wayline.fetch import recording_fetcher
from wayline.jsonschema import load_schema, validate
from wayline.objectives import run_on_sample
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.tickets import write_ticket
from wayline.scout import VERIFIED

SAMPLE = FIXTURES_DIR / "projects" / "toy"
RECORDINGS = FIXTURES_DIR / "fetch"
EMAIL = "owner@example.org"

sys.path.insert(0, str(SAMPLE / "src"))
from toy.generate import FEATURES, generate, read_split, write_split  # noqa: E402
from toy.metrics import auroc  # noqa: E402


class GeneratorTest(unittest.TestCase):
    def test_the_same_seed_draws_the_same_rows(self):
        first, _ = generate(1, signal=4.0, rows=200)
        second, _ = generate(1, signal=4.0, rows=200)
        self.assertEqual(first, second)

    def test_a_different_seed_draws_different_rows(self):
        first, _ = generate(1, signal=4.0, rows=200)
        second, _ = generate(2, signal=4.0, rows=200)
        self.assertNotEqual(first, second)

    def test_the_held_out_split_is_a_fifth_and_extends_rather_than_reshuffles(self):
        small_train, small_held_out = generate(1, rows=1000)
        big_train, big_held_out = generate(1, rows=2000)
        self.assertEqual((len(small_train), len(small_held_out)), (800, 200))
        self.assertEqual((len(big_train), len(big_held_out)), (1600, 400))
        self.assertEqual(big_train[:800], small_train)  # more rows never changes the first ones

    def test_every_row_carries_the_features_and_the_interaction_term(self):
        rows, _ = generate(1, rows=10)
        for row in rows:
            with self.subTest(row=row):
                self.assertEqual(set(row), set(FEATURES) | {"interaction", "y"})
                self.assertAlmostEqual(row["interaction"], row["x3"] * row["x4"])
                self.assertIn(row["y"], (0, 1))

    def test_the_interaction_term_is_worth_modelling_at_the_shipped_signal(self):
        """What the intent asks: does seeing `x3 * x4` separate the classes better than not seeing it."""
        _, held_out = generate(1, signal=4.0, rows=20000)
        labels = [row["y"] for row in held_out]
        linear_only = [0.6 * row["x1"] - 0.4 * row["x2"] for row in held_out]
        with_interaction = [score + 1.1 * row["interaction"] for score, row in zip(linear_only, held_out)]
        self.assertGreater(auroc(labels, with_interaction), auroc(labels, linear_only))

    def test_write_and_read_split_round_trip(self):
        import tempfile

        rows, _ = generate(1, rows=5)
        with tempfile.TemporaryDirectory() as workspace:
            path = Path(workspace) / "train.jsonl"
            write_split(path, rows)
            self.assertEqual(read_split(path), rows)


class MetricsTest(unittest.TestCase):
    def test_perfect_separation_is_one(self):
        self.assertEqual(auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)

    def test_reversed_scores_are_zero(self):
        self.assertEqual(auroc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]), 0.0)

    def test_a_tie_across_the_classes_is_a_half_for_that_pair(self):
        self.assertEqual(auroc([0, 1], [0.5, 0.5]), 0.5)

    def test_one_class_only_has_no_auroc(self):
        self.assertIsNone(auroc([1, 1, 1], [0.1, 0.5, 0.9]))

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(ValueError):
            auroc([0, 1], [0.1])


class GoalTest(unittest.TestCase):
    """O1 in `research/objectives.json` is the fixture's goal, and its `eval_command` is real: `toy.eval` over an artifact."""

    def setUp(self):
        self.record = json.loads((SAMPLE / "research" / "objectives.json").read_text(encoding="utf-8"))
        self.goal = self.record["objectives"][0]["measure"]

    def test_the_objectives_validate_and_no_goal_json_is_shipped(self):
        self.assertEqual(validate(self.record, load_schema("objectives")), [])
        self.assertEqual([(objective["id"], objective["status"]) for objective in self.record["objectives"]], [("O1", "open")])
        self.assertFalse((SAMPLE / "research" / "GOAL.json").exists())

    def test_the_stopping_rule_is_in_harness_json(self):
        harness = json.loads((SAMPLE / "harness.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(harness, load_schema("harness")), [])
        self.assertEqual(harness["stop_when"], "objectives")

    def test_the_goal_reaches_up_to_a_reachable_target(self):
        self.assertEqual(self.goal["metric"], "auroc")
        self.assertEqual(self.goal["direction"], "up")
        self.assertLess(self.goal["target"], 0.9)  # below every seed's trained auroc, recorded live in m5.md

    def test_eval_command_prints_the_metric_the_measure_check_reads(self):
        """The check `wayline objective add` runs on a measure's sample artifact (ticket 76), where intake's went."""
        import tempfile

        with tempfile.TemporaryDirectory() as workspace:
            artifact = Path(workspace) / "summary.json"
            artifact.write_text(json.dumps({"seed": 1, "auroc": 0.851}), encoding="utf-8")
            kind, reason, value = run_on_sample(self.goal["eval_command"], self.goal["metric"], SAMPLE, artifact)
        self.assertEqual(kind, "accepted", reason)
        self.assertAlmostEqual(value, 0.851)


class ToyRunTest(ProjectTestCase):
    """The toy on the new shape (ticket 87): a goal ticket kept on O1's real measure, O1 written reached, the rule ending the run."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        shutil.copytree(SAMPLE, self.project, ignore=shutil.ignore_patterns("make.py", "__pycache__"))
        init_project(self.project)
        self.ledger = Ledger(self.project)
        write_ticket(self.ledger, {
            "id": 1, "title": "Train with the interaction term", "kind": "code", "difficulty": 1, "status": "open",
            "blocked_by": [], "touches": ["metrics/"], "role": "coder", "skills": [], "objectives": ["O1"], "goal": "O1",
            "outputs": ["metrics/seed-*.json"], "acceptance": {"machine": ["test -f metrics/seed-1.json"], "quality": []},
            "context_pack": ["research/INTAKE.md"], "origin": "research/objectives.json#O1", "proposed_by": "planner",
            "demo": "Three seeds' summaries under metrics/."}, "## Demo\n\nThree seeds' summaries.\n")

    def test_the_goal_is_reached_by_code_and_the_stopping_rule_ends_the_run(self):
        from tests import machine
        from tests.test_conductor import done, drive
        from wayline import worker
        from wayline.conductor import Conductor
        files = {"metrics/seed-%d.json" % seed: json.dumps({"seed": seed, "auroc": value}) + "\n"
                 for seed, value in ((1, 0.85), (2, 0.86), (3, 0.87))}
        with worker.use_fake() as fake:
            fake.script(done(outputs_written=sorted(files)), patch=worker.Patch(files=files, message="ticket 1: three seeds"))
            conductor = Conductor(self.project, out=io.StringIO())
            conductor.readings = machine.recorded
            conductor.notify = lambda *args, **kwargs: None
            results = []
            while not (results and results[-1].ended) and len(results) < 6:
                results.extend(drive(conductor, 1))
                conductor.settle()
        events, _ = self.ledger.read_events()
        progress = [event["payload"] for event in events if event["event"] == "progress"]
        self.assertEqual([(payload["goal"], payload["kept"]) for payload in progress], [("O1", True)])
        self.assertAlmostEqual(progress[0]["value"], 0.86)
        record = json.loads((self.project / "research" / "objectives.json").read_text(encoding="utf-8"))["objectives"][0]
        self.assertEqual(record["status"], "answered")
        self.assertEqual([event["payload"]["reason"] for event in events if event["event"] == "run_ended"], ["goal_reached"])


class IntakeReferencesTest(unittest.TestCase):
    def test_the_intake_names_three_references_of_three_kinds(self):
        from wayline.dossier import intake_references

        text = (SAMPLE / "research" / "INTAKE.md").read_text(encoding="utf-8")
        references = intake_references(text)
        self.assertEqual([reference.kind for reference in references], ["doi", "doi", "arxiv"])


class AbsorbTest(ProjectTestCase):
    """`wayline init` on a copy of the fixture, then `absorb --level 0` against the recordings."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "toy"
        shutil.copytree(SAMPLE, self.project, ignore=shutil.ignore_patterns("make.py", "src"))
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None)

    def absorb(self):
        return absorb_level_0(self.project, fetcher=recording_fetcher(RECORDINGS, email=EMAIL), email=EMAIL)

    def test_the_three_references_resolve_from_the_recordings(self):
        report = self.absorb()
        self.assertEqual(report["references"], 3)
        self.assertEqual(report["verified"], 3)
        self.assertEqual(report["unresolved"], 0)
        self.assertEqual(report["problems"], [])

    def test_two_resolve_through_crossref_and_one_through_arxiv(self):
        report = self.absorb()
        sources = sorted(written["resolved_by"] for written in report["written"])
        self.assertEqual(sources, ["arxiv", "crossref", "crossref"])

    def test_every_dossier_written_validates(self):
        self.absorb()
        for path in sorted((self.project / "research" / "refs").glob("*/dossier.json")):
            with self.subTest(dossier=path.parent.name):
                self.assertEqual(validate(json.loads(path.read_text(encoding="utf-8")), load_schema("dossier")), [])


def _train_spec(temp, ticket=3, **overrides):
    fields = {
        "id": "t%d-1" % ticket, "ticket": ticket,
        "command": ("python3", "-m", "toy.train", "--seed", "1", "--batch-size", "90000",
                    "--out", "results/toy/seed-1/summary.json"),
        "cwd": str(temp), "log": str(Path(temp) / "results" / "logs" / ("t%d-1.log" % ticket)),
        "expected_outputs": ("results/toy/seed-1/summary.json",),
        "retry": {"host_oom": [], "gpu_oom": [{"--batch-size": "256"}]},
    }
    fields.update(overrides)
    return r.JobSpec(**fields)


CUDA_TRACEBACK = (
    "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 30.18 GiB. "
    "GPU 0 has a total capacity of 23.69 GiB of which 23.35 GiB is free.\n"
)


class RetryLadderTest(ProjectTestCase):
    """The oversized configuration's job, faked: one `oom_gpu` attempt, then the ladder's recovery.

    This is the fake half of the ticket's acceptance ("runs with fake jobs in the suite"); the GPU
    half ("and on the GPU live") is `docs/verification/m5.md`, where the same two commands ran for
    real against the RTX 3090 the ladder was written for: the oversized `--batch-size` OOM'd with
    exactly this traceback, and `--batch-size 256` (the ladder's own override) then finished in
    under ten seconds with a real held-out AUROC.
    """

    def test_the_oversized_attempt_oom_s_and_writes_no_outputs(self):
        with r.use_fake_jobs() as fake:
            fake.script([r.JobState("oom_gpu", result="exit-code", exit_code=1)], log=CUDA_TRACEBACK)
            spec = _train_spec(self.temp)
            handle = r.JobRunner(backend=fake).launch(spec)
            state = fake.poll(handle)
        self.assertEqual((state.name, state.oom), ("oom_gpu", "gpu"))
        self.assertIn("CUDA out of memory", r.log_tail(spec.log))
        self.assertFalse((self.temp / "results" / "toy" / "seed-1" / "summary.json").exists())

    def test_the_ladder_s_step_names_the_override_the_next_attempt_needs(self):
        spec = _train_spec(self.temp)
        step = spec.retry["gpu_oom"][0]
        self.assertEqual(step, {"--batch-size": "256"})
        retried_command = tuple(
            step["--batch-size"] if part == "90000" else part for part in spec.command
        )
        self.assertNotIn("90000", retried_command)
        self.assertIn("256", retried_command)

    def test_the_retried_attempt_exits_and_writes_the_metrics_the_ladder_recovered(self):
        with r.use_fake_jobs() as fake:
            fake.script(["exited"], outputs={"results/toy/seed-1/summary.json": json.dumps({"seed": 1, "auroc": 0.851})})
            spec = _train_spec(self.temp, command=("python3", "-m", "toy.train", "--seed", "1", "--batch-size", "256",
                                                    "--out", "results/toy/seed-1/summary.json"))
            handle = r.JobRunner(backend=fake).launch(spec)
            state = fake.poll(handle)
        self.assertEqual(state.name, "exited")
        summary = json.loads((self.temp / "results" / "toy" / "seed-1" / "summary.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(summary["auroc"], 0.82)  # O1's target

    def test_wayline_job_add_accepts_the_ticket_s_spec_including_the_ladder(self):
        project = self.temp / "toy"
        (project / "research").mkdir(parents=True)
        spec = {
            "id": "t3-1", "ticket": 3,
            "command": ["python3", "-m", "toy.train", "--seed", "1", "--batch-size", "90000",
                        "--out", "results/toy/seed-1/summary.json"],
            "cwd": str(project), "log": str(project / "results" / "logs" / "t3-1.log"),
            "expected_outputs": ["results/toy/seed-1/summary.json"],
            "retry": {"host_oom": [], "gpu_oom": [{"--batch-size": "256"}]},
        }
        records = r.add_jobs(project, spec, ticket=3, backend="fake")
        self.assertEqual(len(records), 1)
        self.assertEqual(validate(records[0], load_schema("job")), [])
        self.assertEqual(records[0]["retry"]["gpu_oom"], [{"--batch-size": "256"}])


class MaterialsTest(unittest.TestCase):
    """The papers and the code repository the intent's three references and Code section name."""

    def test_the_two_pdfs_and_the_tarball_exist(self):
        for name in ("paper-a.pdf", "paper-b.pdf", "paper-c-source.tar.gz"):
            with self.subTest(name=name):
                self.assertTrue((SAMPLE / "materials" / name).exists())

    def test_the_tarball_names_the_tiny_repo_s_pinned_commit(self):
        import tarfile

        with tarfile.open(SAMPLE / "materials" / "paper-c-source.tar.gz") as archive:
            text = archive.extractfile("sections/availability.tex").read().decode("utf-8")
        self.assertIn("5de2bb44acea3892f9e0fc5c7b5b401179889958", text)

    def test_the_named_commit_is_the_tiny_pkg_repo_s_tagged_one(self):
        tiny_pkg = FIXTURES_DIR / "code" / "tiny-pkg.git"
        tag = subprocess.run(["git", "--git-dir", str(tiny_pkg), "rev-list", "-n", "1", "v0.1.0"],
                              capture_output=True, text=True, check=True, cwd=str(HARNESS_ROOT))
        self.assertEqual(tag.stdout.strip(), "5de2bb44acea3892f9e0fc5c7b5b401179889958")


if __name__ == "__main__":
    unittest.main()
