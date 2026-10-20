"""Reproducing from the code repository (Implementation Decision 17, ticket 106).

A temporary project, written through the ledger seam: job records under `research/jobs/`, the journal's
`job_launched`, `job_finished`, and `ticket_launched`, artifacts manifested and findings added by
`wayline.provenance`. `git` runs for real, since the locks are read from the commit each run ran at.
"""

import json
import subprocess

from tests.projects import ProjectTestCase
from wayline import provenance, reproduce, resources, sections
from wayline.ledger import Ledger
from wayline.project import init_project


def file_finding(ledger, identifier, text, locator, ticket, replaces=None):
    """One finding through the ledger call the conductor makes when it closes a ticket."""
    return sections.file_finding(ledger, {"id": identifier, "ticket": ticket, "text": text, "provenance": [locator], "negative": False,
                                          "heading": None, "replaces": replaces, "objectives": []})

OWNER_PART = "Cite this repository as Varga (2026).\n\nThe colony data are on Zenodo, record 123.\n"


def git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


class ReproduceCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "lantern"
        self.project.mkdir()
        init_project(self.project)
        self.ledger = Ledger(self.project)
        code = self.project / "code"
        code.mkdir()
        (code / "train.py").write_text("print('train')\n")
        (code / "requirements.lock").write_text("numpy==2.1.0\n")
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "code: train")
        self.at = git(self.project, "rev-parse", "main")
        # What is installed now differs from what the job ran with.
        (code / "requirements.lock").write_text("numpy==2.3.4\n")
        git(self.project, "commit", "-q", "-am", "code: newer numpy")
        self.job_run()
        self.ticket_run()

    def job_run(self):
        spec = resources.JobSpec(
            id="t3-1", ticket=3, cwd=str(self.project), log=str(self.project / "results" / "t3-a1" / "log.txt"),
            command=("/usr/bin/python3", str(self.project / "code" / "train.py"), "--out",
                     str(self.project / "results" / "t3-a1" / "metrics.json"), "--data", "code/train.py"),
            gpu_uuids=("GPU-aaaa",), cores=(0, 1), ram_gb=8.0,
            expected_outputs=(str(self.project / "results" / "t3-a1" / "metrics.json"),),
            tools=({"name": "octave", "version": "9.2.0", "lock": "ab" * 32},),
        )
        record = resources.job_record(spec, backend="fake", gpu_indices=(1,), status="exited", attempts=[{
            "n": 1, "started_at": "2026-10-19T10:00:00Z", "ended_at": "2026-10-19T10:02:05Z", "result": "exited",
            "exit_code": 0, "oom": None, "overrides": {}}])
        self.ledger.write_json("jobs/t3-1.json", record, schema="job")
        self.ledger.append_event("job_launched", {"unit": None, "gpu_uuids": ["GPU-aaaa"], "cores": [0, 1], "ram_gb": 8.0,
                                                  "attempt": 1, "tools": list(spec.tools), "commit": self.at}, ticket=3, job="t3-1")
        self.ledger.append_event("job_finished", {"exit_code": 0, "seconds": 125, "outputs_ok": True}, ticket=3, job="t3-1")
        out = self.project / "results" / "t3-a1" / "metrics.json"
        out.parent.mkdir(parents=True)
        out.write_text('{"r": 0.91}\n')
        provenance.register_artifact(self.ledger, "results/t3-a1/metrics.json", "t3-1", "t3-a1", 3)
        self.first = file_finding(self.ledger, "t3-a1-f1", "Synchrony rises to r = 0.91.", "results/t3-a1/metrics.json#r", 3)

    def ticket_run(self):
        self.later = git(self.project, "rev-parse", "main")
        self.ledger.append_event("ticket_launched", {"ticket": 4, "attempt": 1, "commit": self.later}, ticket=4)
        self.ledger.append_event("ticket_result", {"ticket": 4, "attempt": 1, "status": "done", "duration_ms": 30000}, ticket=4)
        session = self.project / "research" / "sessions" / "4" / "1"
        session.mkdir(parents=True)
        (session / "result.json").write_text(json.dumps({"ticket_id": 4, "status": "done", "summary": "s",
                                                         "commands_run": ["python3 code/train.py --quick"]}))
        out = self.project / "results" / "t4-a1" / "quick.csv"
        out.parent.mkdir(parents=True)
        out.write_text("r\n0.88\n")
        provenance.register_artifact(self.ledger, "results/t4-a1/quick.csv", None, "t4-a1", 4)

    def rendered(self):
        return json.loads((self.project / "code" / "reproduce.json").read_text())


class TheRenderedFilesTest(ReproduceCase):
    def test_each_cited_run_gives_its_command_commit_inputs_outputs_time_and_hardware(self):
        reproduce.render(self.project)
        record = self.rendered()
        result, = record["results"]
        run, = result["runs"]
        self.assertEqual(run["run_id"], "t3-a1")
        self.assertEqual(run["job"], "t3-1")
        self.assertEqual(run["commit"], self.at)
        self.assertEqual(run["command"], ["/usr/bin/python3", "train.py", "--out", "metrics.json", "--data", "train.py"])
        self.assertEqual(run["inputs"], ["train.py"])
        self.assertEqual([output["name"] for output in run["outputs"]], ["metrics.json"])
        self.assertEqual(run["outputs"][0]["sha256"], provenance.sha256_of(self.project / "results" / "t3-a1" / "metrics.json"))
        self.assertEqual(run["seconds"], 125)
        self.assertEqual(run["hardware"], {"gpu_uuids": ["GPU-aaaa"], "gpu_indices": [1], "cores": [0, 1], "ram_gb": 8.0})
        self.assertEqual(result["findings"], [self.first["id"]])
        text = (self.project / "code" / "REPRODUCE.md").read_text()
        for piece in ("t3-a1", self.at, "python3 train.py --out metrics.json", "125 s", "GPU-aaaa", self.first["text"]):
            self.assertIn(piece, text)

    def test_the_locks_come_from_the_commit_the_job_ran_at(self):
        reproduce.render(self.project)
        self.assertEqual((self.project / "code" / "locks" / self.at / "requirements.lock").read_text(), "numpy==2.1.0\n")
        self.assertEqual(self.rendered()["results"][0]["runs"][0]["locks"], "locks/%s/" % self.at)
        tools = json.loads((self.project / "code" / "locks" / "tools.json").read_text())
        self.assertEqual(tools["tools"], [{"name": "octave", "version": "9.2.0", "lock": "ab" * 32, "runs": ["t3-a1"]}])
        self.assertIn("octave 9.2.0", (self.project / "code" / "REPRODUCE.md").read_text())

    def test_no_file_names_a_path_the_code_repository_does_not_hold(self):
        reproduce.render(self.project)
        for name in ("REPRODUCE.md", "reproduce.json", "README.md", "locks/tools.json"):
            text = (self.project / "code" / name).read_text()
            for prefix in ("research/", "jobs/", "results/", str(self.project)):
                self.assertNotIn(prefix, text, "%s names %s" % (name, prefix))

    def test_the_readme_renders_from_the_records(self):
        reproduce.render(self.project)
        readme = (self.project / "code" / "README.md").read_text()
        self.assertIn("# lantern", readme)
        self.assertIn("REPRODUCE.md", readme)
        self.assertIn(reproduce.OWNER_BEGIN, readme)


class TheOwnersPartTest(ReproduceCase):
    def test_the_owners_part_survives_a_re_render_word_for_word(self):
        reproduce.render(self.project)
        path = self.project / "code" / "README.md"
        readme = path.read_text()
        begin = readme.index(reproduce.OWNER_BEGIN) + len(reproduce.OWNER_BEGIN)
        path.write_text(readme[:begin] + "\n" + OWNER_PART + readme[readme.index(reproduce.OWNER_END):])
        file_finding(self.ledger, "t4-a1-f1", "A quick run agrees.", "results/t4-a1/quick.csv#r", 4)
        reproduce.render(self.project)
        self.assertIn(reproduce.OWNER_BEGIN + "\n" + OWNER_PART + reproduce.OWNER_END, path.read_text())

    def test_a_readme_without_markers_is_kept_whole_as_the_owners_part(self):
        (self.project / "code" / "README.md").write_text("# phaselock\n\nThe owner's own words.\n")
        reproduce.render(self.project)
        readme = (self.project / "code" / "README.md").read_text()
        self.assertIn(reproduce.OWNER_BEGIN + "\n# phaselock\n\nThe owner's own words.\n" + reproduce.OWNER_END, readme)


class AReplacedFindingTest(ReproduceCase):
    def test_a_finding_replaced_by_another_changes_the_runs_listed(self):
        reproduce.render(self.project)
        file_finding(self.ledger, "t4-a1-f1", "Synchrony is r = 0.88 on the quick run.", "results/t4-a1/quick.csv#r", 4,
                     replaces=self.first["id"])
        reproduce.render(self.project)
        runs = [run["run_id"] for result in self.rendered()["results"] for run in result["runs"]]
        self.assertEqual(runs, ["t4-a1"])
        run = self.rendered()["results"][0]["runs"][0]
        self.assertIsNone(run["job"])
        self.assertEqual(run["command"], ["python3 train.py --quick"])
        self.assertEqual(run["commit"], self.later)
        self.assertEqual(run["seconds"], 30)
        self.assertEqual((self.project / "code" / "locks" / self.later / "requirements.lock").read_text(), "numpy==2.3.4\n")
        self.assertFalse((self.project / "code" / "locks" / self.at).exists(), "a lock no cited run ran with is gone")
        self.assertNotIn("t3-a1", (self.project / "code" / "REPRODUCE.md").read_text())


    def test_a_finding_the_conductor_filed_with_replaces_drops_the_old_runs(self):
        """The conductor files a worker's finding itself, carrying the `replaces` its result named."""
        self.ledger.append_record("findings.jsonl", {"id": "t4-a1-f1", "ticket": 4, "text": "r = 0.88",
                                                     "provenance": "results/t4-a1/quick.csv#r", "negative": False,
                                                     "replaces": self.first["id"]})
        reproduce.render(self.project)
        self.assertEqual([run["run_id"] for result in self.rendered()["results"] for run in result["runs"]], ["t4-a1"])


class PathsTheRepositoryHoldsTest(ReproduceCase):
    def test_paths_out_of_code_and_inside_session_commands_are_named_by_file_name(self):
        session = self.project / "research" / "sessions" / "4" / "1"
        (session / "resume-1").mkdir()
        (session / "resume-1" / "result.json").write_text(json.dumps({"commands_run": [
            "cd %s && python3 -c \"open('results/t4-a1/quick.csv')\" --out ../results/t4-a1/quick.csv" % self.project]}))
        file_finding(self.ledger, "t4-a1-f1", "A quick run agrees.", "results/t4-a1/quick.csv#r", 4)
        reproduce.render(self.project)
        run = self.rendered()["results"][1]["runs"][0]
        self.assertEqual(run["command"], ["python3 train.py --quick",
                                          "cd . && python3 -c \"open('quick.csv')\" --out quick.csv"])


class OnlyAfterAChangeTest(ReproduceCase):
    def test_a_render_left_uncommitted_is_rendered_again(self):
        reproduce.render_if_changed(self.project)
        self.assertTrue(reproduce.render_if_changed(self.project), "the wave's commit did not happen")

    def test_nothing_is_written_when_neither_code_nor_the_cited_runs_changed(self):
        self.assertTrue(reproduce.render_if_changed(self.project))
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "rendered")
        self.assertEqual(reproduce.render_if_changed(self.project), [])

    def test_a_change_to_code_re_renders(self):
        reproduce.render_if_changed(self.project)
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "rendered")
        (self.project / "code" / "plot.py").write_text("print('plot')\n")
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "code: plot")
        self.assertIn("code/reproduce.json", reproduce.render_if_changed(self.project))

    def test_a_cited_job_that_ran_again_re_renders(self):
        reproduce.render_if_changed(self.project)
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "rendered")
        self.ledger.append_event("job_finished", {"exit_code": 0, "seconds": 140, "outputs_ok": True}, ticket=3, job="t3-1")
        self.assertIn("code/reproduce.json", reproduce.render_if_changed(self.project))
        self.assertEqual(self.rendered()["results"][0]["runs"][0]["seconds"], 140)

    def test_a_project_without_code_renders_nothing(self):
        other = self.temp / "bare"
        other.mkdir()
        init_project(other)
        self.assertEqual(reproduce.render_if_changed(other), [])
        self.assertFalse((other / "code").exists())
