"""Code at the paper order (Implementation Decision 17; ticket 119).

The seams: `paper_code.step`, which the conductor's rest point takes once a wave, over a temporary project whose records
go in through the ledger calls their own tickets built (job records, the journal's `job_launched`, artifacts manifested,
findings filed); the tool runner's recordings (`git` runs for real, the push goes to a local bare repository in the
GitHub URL's place); the fake job backend standing in for the re-runs; and the journal it wrote, replayed. What is
asserted is what the owner and the next component see: the journal, the tag in both repositories, the files under
`code/`, the ticket cut, `PAPER.md`, and the account.
"""

import io
import json
import subprocess
import sys

from tests import machine
from tests.projects import ProjectTestCase
from tests.test_code_repository import Runner
from tests.test_drawings import DrawingRunCase
from tests.test_paper import Writer
from wayline import account, drawings, paper, paper_code, provenance, resources, sections, tickets, worker
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.project import init_project, read_harness

TRAIN = "def window_ratio(samples):\n    return sum(samples) / len(samples)\n"
TRAIN_LATER = TRAIN + "\n\ndef smooth(samples):\n    return samples\n"


def git(cwd, *args):
    done = subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args), done.stderr))
    return done.stdout.strip()


def file_finding(ledger, identifier, text, locator, ticket):
    return sections.file_finding(ledger, {"id": identifier, "ticket": ticket, "text": text, "provenance": [locator], "negative": False,
                                          "heading": None, "replaces": None, "objectives": []})


class CodeAtOrderCase(ProjectTestCase):
    """Two results made by jobs at one commit of `code/`, then `code/` changed: both are stale at the order."""

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "lantern").resolve()
        self.project.mkdir()
        init_project(self.project)
        self.ledger = Ledger(self.project)
        code = self.project / "code"
        code.mkdir()
        (code / "train.py").write_text(TRAIN)
        (code / "requirements.lock").write_text("numpy==2.1.0\nscipy==1.14.1\n")
        git(self.project, "add", "code")
        git(self.project, "commit", "-q", "-m", "code: train")
        self.at = git(self.project, "rev-parse", "main")
        self.result(3, "t3-1", "results/t3-a1/metrics.json", '{"r": 0.91}\n', "Synchrony rises to r = 0.91.", "r")
        self.result(5, "t5-1", "results/t5-a1/loss.json", '{"loss": 0.25}\n', "The loss falls to 0.25.", "loss")
        fields = {"id": 5, "title": "Fit the loss", "kind": "analysis", "difficulty": 3, "status": "done", "blocked_by": [],
                  "touches": ["results/t5-a1/"], "role": "analyst", "acceptance": {"machine": ["test -f results/t5-a1/loss.json"],
                                                                                 "quality": []},
                  "proposed_by": "planner", "objectives": []}
        tickets.write_ticket(self.ledger, fields, "\nFit it.\n")
        (code / "train.py").write_text(TRAIN_LATER)
        git(self.project, "commit", "-q", "-m", "code: smooth", "--", "code/train.py")
        self.run = Runner()

    def result(self, ticket, job, output, content, text, key):
        spec = resources.JobSpec(
            id=job, ticket=ticket, cwd=str(self.project), log=str(self.project / "results" / "logs" / ("%s.log" % job)),
            command=("/usr/bin/python3", str(self.project / "code" / "train.py"), "--out", str(self.project / output)),
            expected_outputs=(str(self.project / output),))
        record = resources.job_record(spec, backend="fake", status="exited", attempts=[{
            "n": 1, "started_at": "2026-10-19T10:00:00Z", "ended_at": "2026-10-19T10:02:05Z", "result": "exited",
            "exit_code": 0, "oom": None, "overrides": {}}])
        self.ledger.write_json("jobs/%s.json" % job, record, schema="job")
        self.ledger.append_event("job_launched", {"unit": None, "gpu_uuids": [], "cores": [], "ram_gb": 0.0, "attempt": 1,
                                                  "tools": [], "commit": self.at}, ticket=ticket, job=job)
        self.ledger.append_event("job_finished", {"exit_code": 0, "seconds": 125, "outputs_ok": True}, ticket=ticket, job=job)
        path = self.project / output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        provenance.register_artifact(self.ledger, output, job, "t%d-a1" % ticket, ticket)
        file_finding(self.ledger, "t%d-a1-f1" % ticket, text, "%s#%s" % (output, key), ticket)

    def remote(self):
        bare = self.temp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        harness = read_harness(self.project)
        harness["code_repository"] = {"shape": "reproducibility", "visibility": "private", "license": "MIT",
                                      "remote": {"repository": "jpbernal/lantern", "url": str(bare), "how": "new"}}
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n")
        git(self.project, "commit", "-q", "-am", "the code repository's remote")
        return bare

    def order(self):
        paper.order(self.project, start=None)
        return paper.open_order(self.project)

    def take(self, payload, moved_to='{"loss": 0.4}\n', waves=4):
        """Take code's steps with the re-runs scripted: ticket 3's numbers hold, ticket 5's move."""
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running", "exited"], outputs={"results/t3-a1/metrics.json": '{"r": 0.91}\n'}, job_id="paper1-t3-1")
            jobs.script(["running", "exited"], outputs={"results/t5-a1/loss.json": moved_to}, job_id="paper1-t5-1")
            taken = [paper_code.step(self.project, payload, run=self.run) for _ in range(waves)]
            self.launched = list(jobs.launched)
        return taken

    def code_events(self):
        return [event["payload"] for event in self.ledger.read_events()[0] if event["event"] == "paper_code"]


class TheReRunsTest(CodeAtOrderCase):
    def test_a_result_whose_numbers_held_stands_and_one_whose_numbers_moved_gets_a_ticket(self):
        payload = self.order()
        taken = self.take(payload)
        self.assertEqual(taken[:2], [False, True], "the re-runs are polled once a wave; the steps end once both ended")
        reruns = {event["result"]: event for event in self.code_events() if event["step"] == "rerun"}
        self.assertEqual(reruns["ticket 3"]["outcome"], "held")
        self.assertIsNone(reruns["ticket 3"]["ticket"])
        self.assertEqual(reruns["ticket 5"]["outcome"], "moved")
        cut = reruns["ticket 5"]["ticket"]
        fields = {entry["id"]: entry for entry in tickets.read_tickets(self.project)}
        self.assertEqual(sorted(fields), [5, cut], "one ticket cut, for the result whose numbers moved")
        self.assertEqual((fields[cut]["kind"], fields[cut]["role"], fields[cut]["status"]), ("analysis", "analyst", "open"))
        self.assertIn("paper-1", fields[cut]["title"])
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields[cut]))
        self.assertIn("The loss falls to 0.25.", body)
        self.assertIn("t5-a1-f1", body)
        self.assertEqual(self.code_events()[-1]["step"], "done")

    def test_the_re_runs_run_at_the_tag_in_their_own_worktree_and_leave_the_runs_outputs_alone(self):
        self.take(self.order())
        spec = next(spec for spec, _ in self.launched if spec.id == "paper1-t3-1")
        worktree = self.project / ".worktrees" / "paper-1"
        self.assertEqual(spec.cwd, str(worktree))
        self.assertEqual(spec.command[1], str(worktree / "code" / "train.py"), "the tracked code at the tag")
        self.assertEqual(spec.command[3], str(worktree / "results" / "t3-a1" / "metrics.json"))
        self.assertEqual((self.project / "results" / "t5-a1" / "loss.json").read_text(), '{"loss": 0.25}\n',
                         "the run its findings cite is left as it was")
        self.assertFalse(worktree.exists(), "the worktree goes once the steps are done")

    def test_a_result_whose_code_did_not_change_is_not_re_run(self):
        git(self.project, "checkout", "-q", "-B", "main", self.at)  # back to the code the runs ran at
        self.take(self.order())
        self.assertEqual([event["step"] for event in self.code_events()], ["tagged", "done"])
        self.assertEqual(self.launched, [])

    def test_a_re_run_that_fails_is_listed_and_cuts_no_ticket(self):
        payload = self.order()
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running", "exited"], outputs={"results/t3-a1/metrics.json": '{"r": 0.91}\n'}, job_id="paper1-t3-1")
            jobs.script(["failed"], job_id="paper1-t5-1")
            for _ in range(3):
                paper_code.step(self.project, payload, run=self.run)
        reruns = {event["result"]: event for event in self.code_events() if event["step"] == "rerun"}
        self.assertEqual(reruns["ticket 5"]["outcome"], "failed")
        self.assertIn("paper1-t5-1", reruns["ticket 5"]["reason"])
        self.assertEqual([entry["id"] for entry in tickets.read_tickets(self.project)], [5])

    def test_a_restarted_conductor_goes_on_from_the_journal(self):
        payload = self.order()
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running", "running", "exited"], outputs={"results/t3-a1/metrics.json": '{"r": 0.91}\n'}, job_id="paper1-t3-1")
            jobs.script(["running", "running", "exited"], outputs={"results/t5-a1/loss.json": '{"loss": 0.25}\n'}, job_id="paper1-t5-1")
            self.assertFalse(paper_code.step(self.project, payload, run=self.run))
            # A new process has nothing but the journal and the record: the re-runs are polled, never launched again.
            self.assertFalse(paper_code.step(self.project, payload, run=Runner()))
            self.assertTrue(paper_code.step(self.project, payload, run=Runner()))
            self.assertEqual(sorted(spec.id for spec, _ in jobs.launched), ["paper1-t3-1", "paper1-t5-1"])
        self.assertEqual([event["outcome"] for event in self.code_events() if event["step"] == "rerun"], ["held", "held"])


class TheJournalReplayTest(CodeAtOrderCase):
    """A recorded journal of an order with one changed result whose numbers held and one whose numbers moved."""

    JOURNAL = [
        {"event": "paper_order", "payload": {"order": 1, "action": "ordered", "by": "owner", "run": None, "batch": None}},
        {"event": "paper_code", "payload": {"order": 1, "step": "tagged", "tag": "paper-1", "commit": "c0ffee", "split": "5p1it",
                                            "pushed": True, "reason": None}},
        {"event": "paper_code", "payload": {"order": 1, "step": "rerun_launched", "result": "ticket 3", "jobs": ["paper1-t3-1"]}},
        {"event": "paper_code", "payload": {"order": 1, "step": "rerun_launched", "result": "ticket 5", "jobs": ["paper1-t5-1"]}},
        {"event": "paper_code", "payload": {"order": 1, "step": "rerun", "result": "ticket 3", "jobs": ["paper1-t3-1"],
                                            "outcome": "held", "ticket": None, "reason": None}},
        {"event": "paper_code", "payload": {"order": 1, "step": "rerun", "result": "ticket 5", "jobs": ["paper1-t5-1"],
                                            "outcome": "moved", "ticket": 7, "reason": None}},
        {"event": "paper_code", "payload": {"order": 1, "step": "done", "tag": "paper-1", "commit": "c0ffee"}},
    ]

    def test_the_replay_holds_each_step_of_the_order(self):
        seen = paper_code.state(self.JOURNAL, 1)
        self.assertEqual((seen["tagged"]["tag"], seen["tagged"]["pushed"]), ("paper-1", True))
        self.assertEqual(sorted(seen["launched"]), ["ticket 3", "ticket 5"])
        self.assertEqual({name: (event["outcome"], event["ticket"]) for name, event in seen["reruns"].items()},
                         {"ticket 3": ("held", None), "ticket 5": ("moved", 7)})
        self.assertIsNotNone(seen["done"])
        self.assertEqual(paper_code.state(self.JOURNAL, 2), {"tagged": None, "launched": {}, "reruns": {}, "done": None})

    def test_every_event_of_the_recorded_journal_is_one_the_ledger_takes(self):
        for event in self.JOURNAL:
            self.ledger.append_event(event["event"], event["payload"])
        self.assertTrue(paper_code.step(self.project, {"order": 1}, run=self.run), "a journal that holds `done` takes no step")
        self.assertFalse(self.run.calls)


class TheTagTest(CodeAtOrderCase):
    def test_the_tag_is_on_main_and_pushed_with_the_split_through_the_tool_runner(self):
        bare = self.remote()
        self.take(self.order())
        tagged = self.code_events()[0]
        self.assertEqual((tagged["step"], tagged["tag"], tagged["pushed"]), ("tagged", "paper-1", True))
        self.assertEqual(git(self.project, "rev-parse", "paper-1^{commit}"), tagged["commit"])
        self.assertEqual(len(self.run.ran("push", str(bare), "%s:refs/tags/paper-1" % tagged["split"])), 1)
        self.assertEqual(git(bare, "rev-parse", "paper-1^{commit}"), tagged["split"])
        self.assertEqual(git(bare, "rev-parse", "main"), tagged["split"], "the split itself is pushed before its tag")
        listed = git(bare, "ls-tree", "--name-only", "paper-1").splitlines()
        for name in ("train.py", "environment.yml", "Dockerfile", "REPRODUCE.md"):
            self.assertIn(name, listed)
        self.assertNotIn("research", listed)

    def test_a_project_with_no_remote_keeps_the_tag_local_and_says_so(self):
        self.take(self.order())
        tagged = self.code_events()[0]
        self.assertFalse(tagged["pushed"])
        self.assertIn("no remote", tagged["reason"])
        self.assertFalse(self.run.ran("push"))
        self.assertEqual(git(self.project, "rev-parse", "paper-1^{commit}"), tagged["commit"])

    def test_a_repository_still_private_at_the_order_is_waiting_on_the_owner(self):
        self.remote()
        self.order()
        waiting = account.account_view(self.project, full=False)["sections"]["Waiting on you"]
        line, = [line for line in waiting if "still private" in line]
        self.assertIn("`jpbernal/lantern`", line)
        self.assertIn("paper-1", line)


class TheFilesUnderCodeTest(CodeAtOrderCase):
    def drawing(self):
        """An accepted drawing whose script computes a number a finding cites."""
        record = drawings._blank_record("R1", 1, 9, drawings.ORDER, ["t3-a1-f1"], "matplotlib")
        record.update(status="accepted", script="drawings/R1-1/draw.py", numbers="drawings/R1-1/numbers.json")
        self.ledger.write_json(drawings.record_path("R1-1"), record, schema="drawing")
        folder = self.project / "drawings" / "R1-1"
        folder.mkdir(parents=True)
        (folder / "draw.py").write_text("import json\njson.dump({'ratio': 1.5}, open('numbers.json', 'w'))\n")
        (folder / "numbers.json").write_text('{"ratio": 1.5}\n')
        git(self.project, "add", "drawings")
        git(self.project, "commit", "-q", "-m", "the drawing")
        file_finding(self.ledger, "t9-a1-f1", "The ratio is 1.5.", "drawings/R1-1/numbers.json#ratio", 9)

    def test_the_script_behind_a_cited_drawing_number_is_copied_into_code_figures_and_tagged(self):
        self.drawing()
        self.take(self.order())
        copied = self.project / "code" / "figures" / "R1-1.py"
        self.assertEqual(copied.read_text(), (self.project / "drawings" / "R1-1" / "draw.py").read_text())
        self.assertIn("t9-a1-f1", (self.project / "code" / "figures" / "FIGURES.md").read_text())
        self.assertIn("R1-1.py", git(self.project, "ls-tree", "--name-only", "paper-1:code/figures").splitlines())
        record = paper_code.read_record(self.project, 1)
        self.assertEqual([(entry["drawing"], entry["file"], entry["findings"]) for entry in record["figures"]],
                         [("R1-1", "code/figures/R1-1.py", ["t9-a1-f1"])])

    def test_an_environment_file_and_a_dockerfile_are_rendered_from_the_locks(self):
        self.take(self.order())
        environment = (self.project / "code" / "environment.yml").read_text()
        for line in ("  - conda-forge", "  - pip:", "    - numpy==2.1.0", "    - scipy==1.14.1"):
            self.assertIn(line, environment.splitlines())
        self.assertTrue(any(line.startswith("  - python=") for line in environment.splitlines()))
        dockerfile = (self.project / "code" / "Dockerfile").read_text()
        self.assertIn("FROM %s" % paper_code.BASE_IMAGE, dockerfile)
        self.assertIn("-f environment.yml", dockerfile)
        self.assertEqual(git(self.project, "show", "paper-1:code/environment.yml") + "\n", environment)
        self.assertEqual(git(self.project, "status", "--porcelain", "--", "code"), "", "all of it is committed with the tag")

    def test_the_files_are_written_whatever_the_environment_setting(self):
        harness = read_harness(self.project)
        harness["environment"] = "container"
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n")
        self.take(self.order())
        self.assertTrue((self.project / "code" / "environment.yml").is_file())
        self.assertTrue((self.project / "code" / "Dockerfile").is_file())

    def test_the_owners_own_dockerfile_is_kept_with_wayline_s_beside_it(self):
        (self.project / "code" / "Dockerfile").write_text("FROM debian:bookworm\n")
        git(self.project, "add", "code/Dockerfile")
        git(self.project, "commit", "-q", "-m", "the owner's Dockerfile")
        self.take(self.order())
        self.assertEqual((self.project / "code" / "Dockerfile").read_text(), "FROM debian:bookworm\n")
        self.assertIn(paper_code.MARK, (self.project / "code" / "Dockerfile.wayline").read_text())
        self.assertEqual(paper_code.read_record(self.project, 1)["kept"], ["code/Dockerfile"])

    def test_the_code_to_methods_check_runs_over_all_of_code_and_names_what_methods_lacks(self):
        self.take(self.order())
        methods = paper_code.read_record(self.project, 1)["methods"]
        self.assertGreaterEqual(methods["files"], 1)
        self.assertTrue(any("window_ratio" in problem for problem in methods["problems"]), methods)
        self.assertFalse(any("figures/" in problem for problem in methods["problems"]))
        lines = "\n".join(paper_code.report_lines(paper_code.read_record(self.project, 1)))
        self.assertIn("window_ratio", lines)
        self.assertIn("ticket 5: its numbers moved", lines)
        self.assertIn("ticket 3: its numbers held", lines)
        told = paper_code.writer_lines(paper_code.read_record(self.project, 1))
        self.assertIn("window_ratio", told)
        self.assertIn("The loss falls to 0.25.", told)


class ReviewedEdgesTest(CodeAtOrderCase):
    """What the review of ticket 119 found: the owner's own files are code, a re-run reads only what it wrote, re-runs never
    share a core, a job named from a ticket's worktree runs at the tag, and a closed window pauses the check."""

    def rewrite_job(self, job, change):
        record = self.ledger.read_json("jobs/%s.json" % job)
        change(record)
        self.ledger.write_json("jobs/%s.json" % job, record, schema="job")

    def test_the_owners_environment_file_is_kept_and_the_dockerfile_builds_wayline_s(self):
        (self.project / "code" / "environment.yml").write_text("name: mine\n")
        git(self.project, "add", "code/environment.yml")
        git(self.project, "commit", "-q", "-m", "the owner's environment")
        self.take(self.order())
        self.assertEqual((self.project / "code" / "environment.yml").read_text(), "name: mine\n")
        self.assertIn("numpy==2.1.0", (self.project / "code" / "environment.wayline.yml").read_text())
        self.assertIn("-f environment.wayline.yml", (self.project / "code" / "Dockerfile").read_text())

    def test_an_owners_file_in_code_figures_is_code_whose_change_makes_a_result_stale(self):
        git(self.project, "checkout", "-q", "-B", "main", self.at)
        (self.project / "code" / "figures").mkdir()
        (self.project / "code" / "figures" / "plot.py").write_text("WINDOW = 512\n")
        git(self.project, "add", "code/figures")
        git(self.project, "commit", "-q", "-m", "the owner's plotting code")
        self.take(self.order())
        self.assertEqual(sorted(event["result"] for event in self.code_events() if event["step"] == "rerun"), ["ticket 3", "ticket 5"])

    def test_a_job_with_no_expected_outputs_compares_nothing_and_is_not_said_to_hold(self):
        self.rewrite_job("t3-1", lambda record: record.update(expected_outputs=[]))
        self.take(self.order())
        rerun = next(event for event in self.code_events() if event["step"] == "rerun" and event["result"] == "ticket 3")
        self.assertEqual(rerun["outcome"], "failed")
        self.assertIn("no expected outputs", rerun["reason"])

    def test_re_runs_that_want_the_same_cores_run_one_after_the_other(self):
        for job in ("t3-1", "t5-1"):
            self.rewrite_job(job, lambda record: record["devices"].update(cores=[0, 1]))
        payload = self.order()
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running", "exited"], outputs={"results/t3-a1/metrics.json": '{"r": 0.91}\n'}, job_id="paper1-t3-1")
            jobs.script(["running", "exited"], outputs={"results/t5-a1/loss.json": '{"loss": 0.25}\n'}, job_id="paper1-t5-1")
            paper_code.step(self.project, payload, run=self.run)
            self.assertEqual([spec.id for spec, _ in jobs.launched], ["paper1-t3-1"], "the second waits for the cores")
            for _ in range(4):
                paper_code.step(self.project, payload, run=self.run)
            self.assertEqual([spec.id for spec, _ in jobs.launched], ["paper1-t3-1", "paper1-t5-1"])
        self.assertEqual([event["outcome"] for event in self.code_events() if event["step"] == "rerun"], ["held", "held"])

    def test_a_job_named_from_a_tickets_worktree_runs_at_the_tag(self):
        old = self.project / ".worktrees" / "12"

        def into_worktree(record):
            record["cwd"] = str(old)
            record["command"] = ["/usr/bin/python3", str(old / "code" / "train.py"), "--out", str(old / "results" / "t3-a1" / "metrics.json")]
            record["expected_outputs"] = [str(old / "results" / "t3-a1" / "metrics.json")]
        self.rewrite_job("t3-1", into_worktree)
        self.take(self.order())
        spec = next(spec for spec, _ in self.launched if spec.id == "paper1-t3-1")
        worktree = self.project / ".worktrees" / "paper-1"
        self.assertEqual((spec.cwd, spec.command[1]), (str(worktree), str(worktree / "code" / "train.py")))
        self.assertEqual(spec.expected_outputs, (str(worktree / "results" / "t3-a1" / "metrics.json"),))

    def test_a_reading_the_usage_window_refused_pauses_the_order_and_the_check_runs_after_it(self):
        from unittest import mock
        from wayline import gates, methods
        payload = self.order()
        refused = methods.Outcome(refused=gates.UsageLimited("the five-hour window is spent"))
        with mock.patch.object(methods, "check", return_value=refused):
            with self.assertRaises(gates.UsageLimited):
                self.take(payload)
        self.assertNotIn("done", [event["step"] for event in self.code_events()])
        self.take(payload)
        self.assertEqual(self.code_events()[-1]["step"], "done")


class OrderRunCodeTest(DrawingRunCase):
    """The conductor at a paper order: code's steps between the batch and the writer, read back from what it wrote."""

    def setUp(self):
        super().setUp()
        code = self.project / "code"
        code.mkdir()
        (code / "train.py").write_text(TRAIN)
        self.git("add", "code")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "code: train")

    def test_the_writer_waits_for_code_s_steps_and_paper_md_lists_them(self):
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": None, "autonomy": "interactive",
                                                 "radius": "moderate", "pid": 1})
        self.ledger.append_event("run_ended", {"reason": "objectives_closed"})
        paper.order(self.project, start=None)
        writer = Writer(self.project)
        with worker.use_fake() as fake:
            fake.script(respond=self.plotter(), role="plotter")
            fake.script(respond=writer, role="writer")
            driven = Conductor(self.project, out=io.StringIO())
            driven.readings = machine.recorded
            driven.drawing_python = sys.executable
            driven.code_run = Runner()
            self.addCleanup(driven.settle, 30)
            for _ in range(20):
                if driven.wave().ended:
                    break
                driven.settle()
        names = [(event["event"], event["payload"].get("step") or event["payload"].get("action"))
                 for event in self.events() if event["event"] in ("paper_code", "paper_order")]
        self.assertLess(names.index(("paper_code", "done")), names.index(("paper_order", "composed")))
        self.git("rev-parse", "--verify", "-q", "paper-1^{commit}")
        report = (self.project / "research" / "paper" / "PAPER.md").read_text()
        self.assertIn("The code repository's tag is `paper-1`", report)
        self.assertIn("## Code at the order", report)
        self.assertIn("window_ratio", report)
        self.assertIn("## Code at the order", writer.prompts[0])
        self.assertIn("window_ratio", writer.prompts[0])
        record = json.loads((self.project / "research" / "paper" / "paper.json").read_text())
        self.assertEqual((record["code"]["tag"], record["code"]["record"]), ("paper-1", "orders/1/code.json"))
