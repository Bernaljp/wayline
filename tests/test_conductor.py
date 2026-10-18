"""The conductor's M0 path (Implementation Decisions 5; Testing Decisions seam 4).

A wave is driven directly against `fixtures/projects/one-ticket/` with the fake worker, and what
is asserted is what the next component and the owner can see: the journal, `main`, the ticket
files, the ledger, the worktree that is or is not still there. The same path is run once through
the shell, because "unattended, one command" is what M0 demos.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests import machine
from tests.projects import SEVEN_RUNG_LADDER, ProjectTestCase, fable_policy, open_objective
from wayline import conductor, gates, objectives, project, resources, tickets, worker
from wayline.conductor import Conductor, ConductorError, WaveResult
from wayline.ledger import Ledger
from wayline.worker import Envelope, Patch

ONE_TICKET = FIXTURES_DIR / "projects" / "one-ticket"
FIVE_TICKETS = FIXTURES_DIR / "projects" / "five-tickets"

HELLO = {"hello.txt": "hello\n"}
WRONG = {"hello.txt": "goodbye\n"}


def done(ticket_id=1, **extra):
    """An envelope carrying the result a coder returns when the ticket went well."""
    result = {
        "ticket_id": ticket_id,
        "status": "done",
        "summary": "wrote hello.txt and ran the acceptance",
        "outputs_written": ["hello.txt"],
    }
    result.update(extra)
    return Envelope(structured_output=result, num_turns=3, duration_ms=1200)


def hold_the_ladder(case):
    """Leave every failed ticket on its first rung for the length of a test: its failure is what the test reads.

    The escalation ladder that climbs from a failure is ticket 38's, and `tests/test_escalation.py` covers it; a
    suite about an integration or a sweep asserts the failure it met, which a climbing ladder would move on from.
    """
    for name, value in (("_escalate", lambda self, result: None), ("_owed_steps", lambda self: [])):
        patcher = mock.patch.object(conductor.Conductor, name, value)
        patcher.start()
        case.addCleanup(patcher.stop)


def failing(ticket_id=1, summary="the library does not exist"):
    """An envelope carrying the result a coder returns when the ticket did not go well."""
    envelope = done(ticket_id)
    envelope.structured_output.update({"status": "failed", "summary": summary})
    return envelope


def patch(files=None, message="ticket 1: write hello.txt", commit=True):
    return Patch(files=dict(files or HELLO), message=message, commit=commit)


def combined(results):
    """Every wave's result as one: the lists run together, and the end is the last wave's."""
    whole = WaveResult(results[-1].number)
    for result in results:
        for name in ("launched", "done", "failed", "running", "accepted", "rejected"):
            getattr(whole, name).extend(getattr(result, name))
    whole.ended, whole.reason = results[-1].ended, results[-1].reason
    return whole


def drive(conductor, waves=None):
    """Waves until the run ends or nothing is in flight, settling the sessions in between; every wave's result.

    A wave does not wait for its workers, so a test that wants a ticket carried settles the sessions
    the last wave started before it takes the next one. `waves` bounds how many it takes.
    """
    results = []
    while True:
        results.append(conductor.wave())
        if results[-1].ended or not conductor.flight or (waves is not None and len(results) >= waves):
            return results
        conductor.settle()


class ConductorCase(ProjectTestCase):
    """A laid-out copy of the one-ticket fixture, with `~/.wayline` pointed at a temporary directory."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "one-ticket"
        shutil.copytree(ONE_TICKET, self.project)
        project.init_project(self.project)
        self.ledger = Ledger(self.project)

    # --- reading the project back ---

    def events(self, name=None):
        events, _ = self.ledger.read_events()
        return [event for event in events if name is None or event["event"] == name]

    def sequence(self):
        return [event["event"] for event in self.events()]

    def payload(self, name):
        found = self.events(name)
        self.assertTrue(found, "no %s event in the journal: %s" % (name, self.sequence()))
        return found[-1]["payload"]

    def first(self, name):
        """The first such event's payload: a failure's own, before the escalation ladder (ticket 38) climbs on from it."""
        found = self.events(name)
        self.assertTrue(found, "no %s event in the journal: %s" % (name, self.sequence()))
        return found[0]["payload"]

    def ticket(self, identifier=1):
        return {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[identifier]

    def body(self):
        return (tickets.tickets_dir(self.project) / "01-write-the-hello-file.md").read_text(encoding="utf-8")

    def git(self, *args, cwd=None):
        done_process = subprocess.run(["git", "-C", str(cwd or self.project), *args], capture_output=True, text=True)
        self.assertEqual(done_process.returncode, 0, done_process.stderr)
        return done_process.stdout.strip()

    def log(self):
        return self.git("log", "--format=%s", "main").split("\n")

    def worktree(self, identifier=1):
        return self.project / conductor.WORKTREES / str(identifier)

    def branches(self):
        """`git branch` marks the current branch with `*` and one checked out in a worktree with `+`."""
        return [line[2:].strip() for line in self.git("branch").split("\n") if line.strip()]

    def commit_on_main(self, name, text="from main\n"):
        (self.project / name).write_text(text, encoding="utf-8")
        self.git("add", "--", name)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main: add " + name)

    # --- driving a wave ---

    def conduct(self, *scripted, waves=None):
        """Script the fake with `(envelope, patch)` pairs, `drive` the conductor, keep what the fake was called with."""
        with worker.use_fake() as fake:
            for envelope, applied in scripted:
                fake.script(envelope, patch=applied)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False  # a split the ladder reaches rebuilds the registry without the CLI's validator
            results = drive(self.conductor, waves)
            self.calls = list(fake.calls)  # the fake is reset when the block ends
        return results


class WholePathTest(ConductorCase):
    """One ticket from the frontier to a fast-forwarded `main`, which is M0's demo."""

    def setUp(self):
        super().setUp()
        self.result = combined(self.conduct((done(findings=[{"text": "a finding", "provenance": "hello.txt#L1"}]), patch())))

    def test_the_journal_carries_the_steps_in_order(self):
        self.assertEqual(self.sequence(), [
            "ticket_launched", "ticket_session", "ticket_result",
            "acceptance", "acceptance", "acceptance",
            "integrated", "manifest", "finding", "ticket_done", "wave", "run_ended",
        ])

    def test_the_acceptance_ran_in_all_three_places_and_passed(self):
        wheres = [event["payload"]["where"] for event in self.events("acceptance")]
        self.assertEqual(wheres, ["worktree", "rebased", "main"])
        for event in self.events("acceptance"):
            self.assertTrue(event["payload"]["pass"])
            self.assertEqual([result["cmd"] for result in event["payload"]["results"]],
                             ["test -f hello.txt", "grep -qx hello hello.txt"])

    def test_main_carries_the_worker_commit_under_the_ledger_commit(self):
        # The wave that carried the outcome commits the ledger on top of the fast-forward.
        self.assertEqual(self.log()[:2], ["ledger: wave 2", "ticket 1: write hello.txt"])
        self.assertEqual((self.project / "hello.txt").read_text(encoding="utf-8"), "hello\n")
        self.assertEqual(self.payload("integrated")["commit"], self.git("rev-parse", "main~1"))
        self.assertEqual(self.payload("integrated")["resolved_by"], "none")

    def test_the_worktree_and_the_branch_are_gone(self):
        self.assertFalse(self.worktree().exists())
        self.assertNotIn("ticket/1", self.branches())
        self.assertNotIn("worktrees/1", self.git("worktree", "list"))

    def test_the_ticket_is_done_and_carries_its_result(self):
        self.assertEqual(self.ticket()["status"], "done")
        body = (tickets.tickets_dir(self.project) / "01-write-the-hello-file.md").read_text(encoding="utf-8")
        self.assertIn("## Result", body)
        self.assertIn("### Attempt 1", body)
        self.assertIn("wrote hello.txt and ran the acceptance", body)

    def test_the_finding_reaches_findings_jsonl_and_the_journal(self):
        written = [json.loads(line) for line in (self.project / "research" / "findings.jsonl").read_text(encoding="utf-8").split("\n") if line]
        self.assertEqual(written, [{"id": "t1-a1-f1", "ticket": 1, "text": "a finding", "provenance": "hello.txt#L1", "negative": False}])
        self.assertEqual(self.payload("finding"), written[0])

    def test_the_run_ends_when_the_frontier_is_empty(self):
        self.assertTrue(self.result.ended)
        self.assertEqual(self.result.reason, "frontier_empty")
        self.assertEqual(self.payload("run_ended"), {"reason": "frontier_empty"})
        self.assertEqual((self.result.launched, self.result.done, self.result.failed), ([1], [1], []))

    def test_the_ledger_commit_names_the_wave_and_touches_only_research(self):
        self.assertEqual(self.log()[0], "ledger: wave 2")
        changed = self.git("show", "--name-only", "--format=", "main").split("\n")
        self.assertTrue(changed)
        for path in changed:
            self.assertTrue(path.startswith("research/"), path)

    def test_nothing_is_left_uncommitted_outside_research(self):
        self.assertEqual(conductor.dirty_outside_research(self.project), [])

    def test_the_wave_regenerated_the_graph_it_schedules_from(self):
        stored = json.loads((self.project / "research" / "graph.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["id"] for entry in stored["tickets"]], [1])
        self.assertEqual(stored["tickets"][0]["status"], "done")
        self.assertEqual(stored["tickets"][0]["attempt"], 1)
        self.assertIn("01-write-the-hello-file.md", stored["snapshot"])


class LaunchTest(ConductorCase):
    """What the wave hands the launcher seam, and what it journals about the launch."""

    def setUp(self):
        super().setUp()
        self.conduct((done(), patch()))
        self.call = self.calls[0]

    def test_the_worker_ran_in_the_ticket_worktree(self):
        self.assertEqual(Path(self.call.request.cwd), self.worktree())
        self.assertEqual(self.payload("ticket_launched")["worktree"], str(self.worktree()))

    def test_the_launch_carries_the_environment_the_guards_read(self):
        environment = self.call.request.env
        self.assertEqual(environment["TICKET_TOUCHES"], "hello.txt")
        self.assertEqual(environment["WAYLINE_TICKET"], "1")
        self.assertEqual(Path(environment["WAYLINE_PROJECT"]), self.project)
        self.assertTrue(environment["TICKET_ACCEPTANCE_FILE"].endswith("research/sessions/1/1/acceptance.json"))

    def test_the_launch_carries_the_role_and_its_tool_lists(self):
        role = worker.read_role("coder")
        self.assertEqual(self.call.request.role, "coder")
        self.assertEqual(self.call.request.allowed_tools, role.allowed_tools)
        self.assertEqual(self.call.request.disallowed_tools, role.disallowed_tools)
        self.assertNotIn("tools", self.call.request.agent_json["coder"])

    def test_the_model_and_effort_come_from_the_difficulty_tier(self):
        self.assertEqual((self.call.request.model, self.call.request.effort), ("sonnet", "low"))
        self.assertEqual(self.call.request.agent_json["coder"]["maxTurns"], 40)
        self.assertEqual(self.call.request.max_minutes, 30)
        launched = self.payload("ticket_launched")
        self.assertEqual((launched["model"], launched["effort"], launched["role"]), ("sonnet", "low", "coder"))

    def test_the_per_launch_settings_are_the_rendered_guards(self):
        settings = json.loads(Path(self.call.request.settings_path).read_text(encoding="utf-8"))
        commands = [handler["command"] for matchers in settings["hooks"].values() for matcher in matchers for handler in matcher["hooks"]]
        self.assertEqual(sorted(Path(command).name for command in commands), ["command_guard.sh", "stop_guard.sh", "touch_set_guard.sh"])
        self.assertTrue(all(command.startswith(str(HARNESS_ROOT)) for command in commands))

    def test_both_directories_of_the_launch_line_are_added(self):
        self.assertEqual(self.call.request.add_dirs, [str(HARNESS_ROOT), str(self.project)])

    def test_the_prompt_beside_the_stream_is_the_one_the_journal_hashes(self):
        written = (self.project / "research" / "sessions" / "1" / "1" / "prompt.md").read_text(encoding="utf-8")
        self.assertEqual(self.payload("ticket_launched")["prompt_sha256"], hashlib.sha256(written.encode("utf-8")).hexdigest())
        self.assertIn("# Ticket 1: Write the hello file", written)
        self.assertIn("Prove that the conductor runs one ticket end to end", written)  # the context pack

    def test_the_session_is_journaled_from_the_stream(self):
        session = self.payload("ticket_session")
        self.assertEqual(session["session_id"], self.events("ticket_result")[0]["payload"]["session_id"])
        self.assertEqual(session["model"], "claude-sonnet-5")
        self.assertEqual(self.payload("ticket_launched")["context_chars"], len((ONE_TICKET / "research" / "INTAKE.md").read_text(encoding="utf-8")))


class RebaseTest(ConductorCase):
    """The integration protocol: the worker's commit is replayed on a `main` that moved."""

    def setUp(self):
        super().setUp()
        # The branch exists before the wave and points at an older main, so the rebase is real.
        self.git("branch", conductor.BRANCH % 1, "main")
        self.commit_on_main("from-main.txt")

    def test_the_commit_is_replayed_on_top_of_main(self):
        self.conduct((done(), patch()))
        log = self.log()
        self.assertEqual(log[:2], ["ledger: wave 2", "ticket 1: write hello.txt"])
        self.assertLess(log.index("ticket 1: write hello.txt"), log.index("main: add from-main.txt"))
        self.assertTrue((self.project / "from-main.txt").exists())
        self.assertEqual((self.project / "hello.txt").read_text(encoding="utf-8"), "hello\n")
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_conflict_fails_the_ticket_and_leaves_main_alone(self):
        self.commit_on_main("hello.txt", "a different hello\n")
        head = self.git("rev-parse", "main")
        self.conduct((done(), patch()))
        failed = self.first("ticket_failed")
        self.assertEqual(failed["next"], "split")
        self.assertIn("hello.txt", failed["reason"])
        self.assertIn("integrator", failed["reason"])  # nothing scripted it, so it could not be launched
        subjects = self.log()
        above = next((index for index, subject in enumerate(subjects) if not subject.startswith("ledger:")), len(subjects))
        self.assertEqual(self.git("rev-parse", "main~%d" % above), head, "only the ledger's own commits are above it")
        self.assertEqual((self.project / "hello.txt").read_text(encoding="utf-8"), "a different hello\n")

    def test_a_conflict_leaves_no_rebase_in_progress_and_keeps_the_worktree(self):
        self.commit_on_main("hello.txt", "a different hello\n")
        self.conduct((done(), patch()))
        self.assertTrue(self.worktree().exists(), "the branch and its worktree stay for the next attempt")
        self.assertIn("ticket/1", self.branches())
        self.assertEqual(self.git("status", "--porcelain", cwd=self.worktree()), "")
        # The split nothing scripted fails, so the ladder hands the ticket to a person (ticket 38).
        self.assertEqual(self.ticket()["status"], "needs_human")


class InvalidResultTest(ConductorCase):
    """A result the schema refuses: resumed once with the error, then the ticket fails."""

    def test_one_resume_recovers_the_ticket(self):
        self.conduct((Envelope(), None), (done(), patch()))
        self.assertEqual(self.sequence(), [
            "ticket_launched", "ticket_session", "ticket_result", "ticket_resumed", "wave", "ticket_result",
            "acceptance", "acceptance", "acceptance", "integrated", "ticket_done", "wave", "run_ended",
        ])
        self.assertEqual(self.payload("ticket_resumed")["reason"], "invalid_result")
        self.assertEqual([event["payload"]["valid"] for event in self.events("ticket_result")], [False, True])
        self.assertEqual([call.kind for call in self.calls], ["launch", "resume"])
        self.assertEqual(self.ticket()["status"], "done")

    def test_the_resume_message_carries_the_error(self):
        self.conduct((Envelope(), None), (done(), patch()))
        self.assertIn("structured_output", self.calls[1].message)
        self.assertIn("Do not start new work", self.calls[1].message)

    def test_a_second_invalid_result_fails_the_ticket(self):
        self.conduct((Envelope(), None), (Envelope(), None))
        self.assertEqual(self.first("ticket_failed")["next"], "tier_up", "rung 2 to rung 3 stays inside sonnet (ticket 61)")
        self.assertIn("after one resume", self.first("ticket_failed")["reason"])
        self.assertEqual(self.ticket()["status"], "needs_human", "the tier-up attempt and the split had nothing scripted")
        self.assertNotIn("integrated", self.sequence())
        self.assertTrue(self.worktree().exists())

    def test_a_result_for_another_ticket_is_not_this_ticket_result(self):
        self.conduct((done(ticket_id=9), patch()), (done(ticket_id=9), patch()))
        self.assertIn("ticket_id 9", self.first("ticket_failed")["reason"])

    def test_a_run_that_ends_with_a_failed_ticket_still_ends(self):
        result = combined(self.conduct((Envelope(), None), (Envelope(), None)))
        self.assertTrue(result.ended)
        self.assertEqual(set(result.failed), {1})


class FailedAcceptanceTest(ConductorCase):
    """The Type-A gates the conductor runs itself: a failure is resumed once with the output."""

    def test_one_resume_recovers_the_ticket(self):
        self.conduct((done(), patch(WRONG)), (done(), patch(HELLO, message="ticket 1: fix hello.txt")))
        self.assertEqual([event["payload"]["where"] for event in self.events("acceptance")],
                         ["worktree", "worktree", "rebased", "main"])
        self.assertEqual([event["payload"]["pass"] for event in self.events("acceptance")], [False, True, True, True])
        self.assertEqual(self.payload("ticket_resumed")["reason"], "acceptance_failed")
        self.assertEqual(self.ticket()["status"], "done")

    def test_the_resume_message_quotes_the_command_that_failed(self):
        self.conduct((done(), patch(WRONG)), (done(), patch(HELLO, message="ticket 1: fix hello.txt")))
        message = self.calls[1].message
        self.assertIn("grep -qx hello hello.txt", message)
        self.assertIn("exit 1", message)
        self.assertNotIn("test -f hello.txt\n(exit", message)  # only the failing command is quoted

    def test_a_second_failure_fails_the_ticket(self):
        self.conduct((done(), patch(WRONG)), (done(), patch(WRONG, message="ticket 1: still wrong")))
        failures = [event["payload"] for event in self.events("ticket_failed")]
        self.assertEqual([item["next"] for item in failures[:2]], ["resume", "tier_up"])
        self.assertIn("still failed in the worktree", failures[1]["reason"])
        self.assertNotIn("integrated", self.sequence())
        self.assertFalse((self.project / "hello.txt").exists())


class UncommittedWorkTest(ConductorCase):
    """The conductor integrates a branch, so work left in the working tree is not a result."""

    def test_an_uncommitted_file_in_the_touch_set_fails_the_ticket(self):
        self.conduct((done(), patch(commit=False)))
        self.assertIn("uncommitted", self.first("ticket_failed")["reason"])
        self.assertIn("hello.txt", self.first("ticket_failed")["reason"])
        self.assertEqual(self.first("ticket_failed")["next"], "resume")
        self.assertNotIn("integrated", self.sequence())
        self.assertFalse((self.project / "hello.txt").exists(), "main must not move on it")

    def test_untracked_noise_outside_the_touch_set_is_not_held_against_the_worker(self):
        self.widen_acceptance()
        self.conduct((done(), patch()))
        self.assertIn("ticket_done", self.sequence())
        self.assertEqual(self.ticket()["status"], "done")

    def test_bytecode_left_in_the_touch_set_is_not_held_against_the_worker(self):
        self.drop_in_pkg("pkg/__pycache__/mod.cpython-312.pyc")
        self.conduct((done(), patch()))
        self.assertIn("integrated", self.sequence())
        self.assertEqual(self.ticket()["status"], "done")

    def test_any_other_untracked_file_in_the_touch_set_still_fails_the_ticket(self):
        self.drop_in_pkg("pkg/new.py")
        self.conduct((done(), patch()))
        self.assertIn("pkg/new.py", self.first("ticket_failed")["reason"])
        self.assertNotIn("integrated", self.sequence())

    def drop_in_pkg(self, name):
        """Put `pkg/` in the touch set and have a tracked `pkg/` gain an untracked `name` in the worktree."""
        (self.project / "pkg").mkdir()
        (self.project / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        fields["touches"] = list(fields["touches"]) + ["pkg/"]
        fields["acceptance"]["machine"] = ["test -f hello.txt", "mkdir -p %s && : > %s" % (name.rsplit("/", 1)[0], name)]
        tickets.write_ticket(self.ledger, fields, body)
        self.git("add", "--", "research", "pkg")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ledger: touch pkg/")

    def widen_acceptance(self):
        """Give the ticket a gate that drops a build artifact, as a real test command would."""
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        fields["acceptance"]["machine"] = ["test -f hello.txt", ": > build-artifact.tmp"]
        tickets.write_ticket(self.ledger, fields, body)
        self.git("add", "--", "research")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ledger: widen the acceptance")


class ResultStatusTest(ConductorCase):
    """A result that is not `done` never reaches the integration."""

    def test_blocked_on_marks_the_ticket_blocked_with_the_path(self):
        self.conduct((done(blocked_on="src/other.py is outside the touch set"), patch()))
        self.assertEqual(self.payload("ticket_blocked")["path"], "src/other.py is outside the touch set")
        self.assertEqual(self.ticket()["status"], "blocked")
        self.assertNotIn("acceptance", self.sequence())

    def test_a_write_outside_the_declared_touch_set_blocks_the_ticket(self):
        self.conduct((done(touched_outside_declared=["docs/readme.md"]), patch()))
        self.assertEqual(self.payload("ticket_blocked")["path"], "docs/readme.md")
        self.assertEqual(self.ticket()["status"], "blocked")

    def test_a_failed_status_fails_the_ticket_with_its_summary(self):
        envelope = done()
        envelope.structured_output.update({"status": "failed", "summary": "the library does not exist"})
        self.conduct((envelope, None))
        self.assertEqual(self.first("ticket_failed")["reason"], "the library does not exist")
        self.assertEqual(self.ticket()["status"], "needs_human", "its resume had nothing scripted")

    def test_needs_human_asks_the_question_the_worker_left(self):
        envelope = done()
        envelope.structured_output.update({"status": "needs_human", "summary": "which split is held out?"})
        self.conduct((envelope, None))
        self.assertEqual(self.payload("ticket_needs_human")["question"], "which split is held out?")
        self.assertEqual(self.ticket()["status"], "needs_human")

    def test_a_running_result_is_integrated_and_leaves_the_ticket_running_for_its_jobs(self):
        """Decision 5: a running result records the job ids, its branch reaches main, and the poller takes the ticket."""
        resources.add_jobs(self.project, {"command": ["/bin/true"]}, ticket=1, backend="fake")
        envelope = done()
        envelope.structured_output.update({"status": "running", "jobs": ["t1-1"]})
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running"], job_id="t1-1")
            result = combined(self.conduct((envelope, patch())))
        self.assertEqual(self.ticket()["status"], "running")
        self.assertEqual((result.running, result.failed, result.done), ([1], [], []))
        self.assertFalse(result.ended, "a ticket is still running, so the run is not over")
        self.assertIn("integrated", self.sequence())
        self.assertEqual(self.payload("ticket_result")["jobs"], ["t1-1"])
        self.assertEqual(self.payload("job_launched")["attempt"], 1)
        self.assertFalse(self.worktree().exists())
        self.assertIn("Jobs: `t1-1`", self.body())

    def test_a_running_result_naming_no_job_file_is_resumed_once_with_the_reason(self):
        envelope = done()
        envelope.structured_output.update({"status": "running", "jobs": ["j-0001"]})
        self.conduct((envelope, patch()), (envelope, None))
        resumed = self.events("ticket_resumed")
        self.assertEqual([event["payload"]["reason"] for event in resumed], ["invalid_result"])
        self.assertIn("research/jobs/j-0001.json does not exist", self.calls[1].message)
        self.assertEqual(self.first("ticket_failed")["next"], "tier_up")
        self.assertEqual(self.ticket()["status"], "needs_human", "the tier-up attempt and the split had nothing scripted")

    def test_what_no_ticket_reads_yet_is_written_into_the_ticket_rather_than_dropped(self):
        self.conduct((done(
            proposals=[{"title": "Try the graph variant", "kind": "experiment", "why": "the residuals cluster"}],
            decision_requests=[{"question": "which split is held out?", "options": ["a", "b"], "recommended": "a"}],
            goal_progress={"metric": "auroc", "value": 0.81},
        ), patch()))
        body = self.body()
        self.assertIn("Try the graph variant", body)
        self.assertIn("which split is held out?", body)
        self.assertIn("auroc = 0.81", body)
        self.assertEqual(self.ticket()["status"], "done")

    def test_the_next_rung_is_the_resume_while_it_is_unspent(self):
        envelope = done()
        envelope.structured_output.update({"status": "failed", "summary": "no"})
        self.conduct((envelope, None))
        self.assertEqual(self.first("ticket_failed")["next"], "resume")


class RefuseToStartTest(ConductorCase):
    """`wayline run` refuses a project it would integrate into badly, and says what to do.

    The third refusal decision 5 names, a harness checkout whose tag is not the project's pin, is
    tested in `test_versions`. The suite runs with `WAYLINE_UNPINNED=1` (`tests/__init__.py`),
    because the harness it runs from is between tags.
    """

    def problems(self):
        return conductor.refuse_to_start(self.project)

    def test_a_clean_project_on_main_has_nothing_against_it(self):
        self.assertEqual(self.problems(), [])

    def test_a_change_outside_research_refuses_the_run(self):
        (self.project / "stray.txt").write_text("mine\n", encoding="utf-8")
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("stray.txt", problems[0])
        self.assertIn("commit or stash", problems[0])

    def test_a_tracked_change_outside_research_refuses_the_run(self):
        (self.project / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertIn("README.md", self.problems()[0])

    def test_a_change_inside_research_is_what_the_conductor_itself_writes(self):
        (self.project / "research" / "findings.jsonl").write_text('{"id":"x"}\n', encoding="utf-8")
        self.assertEqual(self.problems(), [])
        self.assertEqual(conductor.dirty_outside_research(self.project), [])

    def test_a_project_on_another_branch_refuses_the_run(self):
        self.git("switch", "-c", "elsewhere")
        problems = self.problems()
        self.assertIn("elsewhere", problems[0])
        self.assertIn("git -C", problems[0])

    def test_the_verb_exits_2_and_prints_what_to_do(self):
        (self.project / "stray.txt").write_text("mine\n", encoding="utf-8")
        code, out, err = run_verb(["--project", str(self.project)])
        self.assertEqual(code, 2)
        self.assertIn("stray.txt", err)
        self.assertNotIn("ticket_launched", [event["event"] for event in self.events()])


def run_verb(arguments):
    """`wayline run` in process, with its output captured."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = conductor.run_command(arguments)
    return code, out.getvalue(), err.getvalue()


class RunLoopTest(ConductorCase):
    """`Conductor.run`, the loop both the verb and the dashboard call."""

    def conduct_run(self, *scripted, **options):
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope, patch=patch() if envelope.structured_output.get("status") in ("done", "running") else None)
            conductor = Conductor(self.project, out=io.StringIO())
            conductor.readings = machine.recorded
            return conductor.run(wait=lambda seconds: conductor.settle(), **options)

    def test_the_run_journals_its_start_and_stops_when_the_frontier_empties(self):
        waves = self.conduct_run(done())
        self.assertEqual(len(waves), 2, "one wave launches the worker, the next carries its outcome")
        self.assertTrue(waves[-1].ended)
        self.assertEqual(self.sequence()[0], "run_started")
        started = self.payload("run_started")
        self.assertEqual((started["harness_tag"], started["autonomy"], started["radius"]), ("v0.0.0", "checkpoints", "moderate"))
        self.assertEqual(started["resume"], False)
        self.assertEqual(started["pid"], os.getpid())

    def test_a_run_with_nothing_it_can_advance_keeps_polling_rather_than_ending(self):
        """A running ticket holds the run open: the job poller, the tick, or a control event may yet move it."""
        resources.add_jobs(self.project, {"command": ["/bin/true"]}, ticket=1, backend="fake")
        envelope = done()
        envelope.structured_output.update({"status": "running", "jobs": ["t1-1"]})
        with resources.use_fake_jobs() as jobs:
            jobs.script(["running"], job_id="t1-1")
            waves = self.conduct_run(envelope, max_waves=4)
        self.assertEqual(len(waves), 4)
        self.assertFalse(waves[-1].touched)
        self.assertFalse(waves[-1].ended)
        self.assertNotIn("run_ended", self.sequence())
        self.assertEqual(self.ticket()["status"], "running")

    def test_max_waves_stops_the_loop_whatever_the_frontier_holds(self):
        waves = self.conduct_run(max_waves=1)
        self.assertEqual(len(waves), 1)
        self.assertEqual(self.ticket()["status"], "needs_human")  # the fake had nothing scripted: no session, nothing to climb
        self.assertIn("no scripted envelope", self.payload("ticket_failed")["reason"])
        self.assertEqual(self.payload("ticket_failed")["next"], "needs_human")


class FiveTicketsCase(ProjectTestCase):
    """A laid-out copy of the five-ticket fixture, run with the fake worker it ships with."""

    def lay_out(self, name="five-tickets"):
        """A copy of the fixture, laid out by `init`, with its ledger."""
        self.project = self.temp / name
        shutil.copytree(FIVE_TICKETS, self.project)
        project.init_project(self.project)
        self.ledger = Ledger(self.project)
        return self.project

    def conduct(self, name="five-tickets", policy=None):
        """Copy the fixture, lay it out, and run the conductor over it to the end."""
        self.lay_out(name)
        with worker.use_fake() as fake:
            fake.load(FIVE_TICKETS / "fake-worker.json")
            conductor = Conductor(self.project, policy=policy, out=io.StringIO())
            self.waves = conductor.run(wait=lambda seconds: conductor.settle())
        self.journal, _ = self.ledger.read_events()
        return self.waves

    def launched(self):
        """The tickets each wave launched, for the waves that launched any."""
        return [wave.launched for wave in self.waves if wave.launched]

    def read_journal(self):
        self.journal, _ = self.ledger.read_events()
        return self.journal

    def at_payload(self, name, identifier):
        """The payload of this ticket's last event of this name."""
        found = [event["payload"] for event in self.read_journal()
                 if event["event"] == name and event["ticket"] == identifier]
        self.assertTrue(found, "ticket %d has no %s event" % (identifier, name))
        return found[-1]

    def at(self, name, identifier):
        """Where in the journal this ticket's one event of this name is."""
        found = [index for index, event in enumerate(self.journal)
                 if event["event"] == name and event["ticket"] == identifier]
        self.assertEqual(len(found), 1, "ticket %d has %d %s event(s)" % (identifier, len(found), name))
        return found[0]

    def statuses(self):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def read(self, name):
        return (self.project / name).read_text(encoding="utf-8")


class FiveTicketsTest(FiveTicketsCase):
    """The M1 graph with two workers: the branches overlap and the touch-set conflict serializes."""

    def setUp(self):
        super().setUp()
        self.conduct()

    def test_the_two_branches_run_two_at_a_time(self):
        """`max_parallel_workers` is 2, and the graph has two branches that share no path."""
        self.assertEqual(self.launched(), [[1, 2], [3, 4], [5]])

    def test_both_workers_of_a_wave_were_launched_before_either_result_was_carried(self):
        self.assertLess(self.at("ticket_launched", 2), self.at("ticket_result", 1))
        self.assertLess(self.at("ticket_launched", 4), self.at("ticket_result", 3))

    def test_the_conflicting_ticket_launched_only_after_the_tickets_it_shares_a_path_with(self):
        """Ticket 5 may write all of `notes/`, where tickets 1 and 3 write, and nothing blocks it."""
        launched = self.at("ticket_launched", 5)
        self.assertGreater(launched, self.at("integrated", 1))
        self.assertGreater(launched, self.at("integrated", 3))

    def test_every_ticket_closes_and_the_run_ends_with_an_empty_frontier(self):
        self.assertEqual(self.statuses(), {1: "done", 2: "done", 3: "done", 4: "done", 5: "done"})
        self.assertTrue(self.waves[-1].ended)
        self.assertEqual(self.journal[-1]["event"], "run_ended")
        self.assertEqual(self.journal[-1]["payload"], {"reason": "frontier_empty"})
        self.assertEqual(self.read("notes/alpha.md"), "alpha\nalpha extended\n")
        self.assertEqual(self.read("reports/beta.md"), "beta\nbeta extended\n")
        self.assertIn("alpha.md", self.read("notes/INDEX.md"))
        self.assertEqual(list((self.project / conductor.WORKTREES).iterdir()), [])

    def test_every_launch_records_the_context_it_sent_and_the_prompt_it_sent_it_in(self):
        launches = [event["payload"] for event in self.journal if event["event"] == "ticket_launched"]
        self.assertEqual(len(launches), 5)
        for payload in launches:
            with self.subTest(ticket=payload["ticket"]):
                self.assertGreater(payload["context_chars"], 0)
                self.assertRegex(payload["prompt_sha256"], r"\A[0-9a-f]{64}\Z")
        self.assertEqual(len({payload["prompt_sha256"] for payload in launches}), 5)


class SlotsTest(FiveTicketsCase):
    """`policy.max_parallel_workers`: how many workers one wave runs at once."""

    def test_one_slot_runs_the_same_graph_one_ticket_at_a_time(self):
        policy = dict(project.policy_for(self.temp / "nowhere", HARNESS_ROOT), max_parallel_workers=1)
        self.conduct(policy=policy)
        self.assertEqual(self.launched(), [[1], [2], [3], [4], [5]])
        self.assertEqual(set(self.statuses().values()), {"done"})

    def test_a_policy_that_names_no_usable_number_of_workers_is_refused(self):
        self.lay_out()
        policy = dict(project.policy_for(self.project, HARNESS_ROOT), max_parallel_workers=0)
        with self.assertRaises(ConductorError) as caught:
            Conductor(self.project, policy=policy, out=io.StringIO()).wave()
        self.assertIn("max_parallel_workers", str(caught.exception))


class ObjectiveClassTest(FiveTicketsCase):
    """Ticket 81: after the critical path, a ticket serving an objective the stopping rule waits on goes first."""

    def one_slot(self):
        return dict(project.policy_for(self.temp / "nowhere", HARNESS_ROOT), max_parallel_workers=1)

    def serve(self, identifier, *served):
        """Ticket `identifier` names `served` in its `objectives`, as the planner cuts it."""
        path = [found for found in tickets.tickets_dir(self.project).glob("%02d-*.md" % identifier)][0]
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, objectives=list(served)), body)

    def first_launch(self):
        with worker.use_fake() as fake:
            fake.load(FIVE_TICKETS / "fake-worker.json")
            wave = Conductor(self.project, policy=self.one_slot(), out=io.StringIO()).wave()
        return wave.launched

    def test_a_ticket_serving_an_open_objective_launches_before_one_serving_none(self):
        self.lay_out()
        open_objective(self.project)
        self.serve(2, "O1")
        self.assertEqual(self.first_launch(), [2], "tickets 1 and 2 have the same critical path; 2 serves O1")

    def test_a_ticket_serving_a_closed_objective_is_class_2_as_the_journal_says(self):
        self.lay_out()
        open_objective(self.project)
        self.serve(2, "O1")
        objectives.change_objective(self.project, "O1", "parked", by="owner", answer="later")
        self.assertEqual(self.first_launch(), [1], "O1 is parked in the journal, so ticket 2 serves nothing open")

    def test_without_objectives_the_order_is_the_one_it_was(self):
        self.lay_out()
        self.assertEqual(self.first_launch(), [1])


class ParallelOutcomeTest(FiveTicketsCase):
    """What one worker's trouble does to the other worker of the same wave."""

    def test_a_launch_the_backend_refuses_is_not_counted_as_launched(self):
        """`wave.launched` names the tickets whose process started, as `ticket_launched` does."""
        self.lay_out()
        with worker.use_fake() as fake:
            fake.script(done(ticket_id=2), patch=patch({"reports/beta.md": "beta\n"}, "ticket 2"), ticket="2")
            driven = Conductor(self.project, out=io.StringIO())
            wave = driven.wave()
            driven.settle()
            carried = driven.wave()
        self.assertEqual(wave.launched, [2])
        self.assertEqual(sorted(wave.failed), [1], "a refused launch fails in the wave that tried it")
        self.assertEqual(sorted(carried.done), [2])
        self.assertIn("no scripted envelope", self.at_payload("ticket_failed", 1)["reason"])
        self.assertEqual([event["payload"]["ticket"] for event in self.read_journal()
                          if event["event"] == "ticket_launched"], [2])

    def test_an_unexpected_failure_on_one_ticket_still_carries_the_other(self):
        """Both workers have already committed; an uncarried one would be left `running` forever."""
        class Exploding(Conductor):
            def _advance(self, attempt):
                if attempt.id == 1:
                    raise RuntimeError("something no wave step accounts for")
                return super()._advance(attempt)

        self.lay_out()
        with worker.use_fake() as fake:
            fake.load(FIVE_TICKETS / "fake-worker.json")
            exploding = Exploding(self.project, out=io.StringIO())
            exploding.wave()
            exploding.settle()
            with self.assertRaises(RuntimeError):
                exploding.wave()
        self.assertEqual(self.statuses()[2], "done")
        self.assertEqual(self.read("reports/beta.md"), "beta\n")
        self.assertIn("integrated", [event["event"] for event in self.read_journal() if event["ticket"] == 2])


class WorkerSlotsCase(ConductorCase):
    """The one-ticket project with as many independent tickets as a slot test needs (ticket 59).

    Every session is scripted with a long delay, so a worker runs until the test releases it and
    nothing here sleeps (Testing Decisions, seam 4). `fake.live()` is how many workers the launcher
    holds at that moment, and `fake.peak` the most it ever held, which is what `max_parallel_workers`
    bounds at every moment and not only at the moment a wave picks.
    """

    def another_ticket(self, identifier):
        """Ticket `identifier`, independent of every other: its own file to write and its own acceptance."""
        fields, body = tickets.read_ticket(tickets.tickets_dir(self.project) / "01-write-the-hello-file.md")
        name = "f%d.txt" % identifier
        tickets.write_ticket(self.ledger, dict(fields, id=identifier, title="Write file %d" % identifier,
                                               touches=[name], outputs=[name],
                                               acceptance=dict(fields["acceptance"], machine=["test -f " + name])), body)

    def tickets_beside_the_first(self, count):
        """Tickets 2 to `count`, each with its own file, so `count` of them may run at once."""
        for identifier in range(2, count + 1):
            self.another_ticket(identifier)

    def wrote(self, identifier):
        """What ticket `identifier`'s worker returns when it went well, and the commit it leaves."""
        if identifier == 1:
            return done(), patch()
        name = "f%d.txt" % identifier
        return (done(ticket_id=identifier, outputs_written=[name]),
                patch({name: "written\n"}, "ticket %d: write %s" % (identifier, name)))

    def held(self, fake, identifier, envelope=None, applied=None):
        """One held call for a ticket: what it returns and the commit it leaves, until the test releases it."""
        if envelope is None:
            envelope, applied = self.wrote(identifier)
        fake.script(envelope, patch=applied, delay=600, ticket=identifier)

    def conductor_with(self, slots):
        """A conductor over this project whose policy allows `slots` workers at once."""
        driven = Conductor(self.project, out=io.StringIO())
        driven.policy = dict(driven.policy, max_parallel_workers=slots,
                             stall=dict(driven.policy["stall"], waves=99))  # the ladder's waves are the test's, not a stall's
        driven.readings = machine.recorded
        driven.plan_pre_check = False
        self.addCleanup(driven.settle, 30)
        return driven

    def returns(self, driven, fake, identifier=None):
        """The held session(s) return now: released, and their threads waited for, so the result is in.

        The conductor has not carried it: that is the moment `max_parallel_workers` used to count
        the slot free.
        """
        released = fake.release(ticket=identifier)
        for wanted, attempt in list(driven.flight.items()):
            if attempt.thread is not None and (identifier is None or wanted == identifier):
                attempt.thread.join(30)
        return released

    def at_the_pick(self, driven, release):
        """Run `release` between wave step 3 (the poll) and wave step 9 (the pick), at every wave."""
        picks = driven._picks

        def picking(graph):
            release()
            return picks(graph)

        driven._picks = picking
        self.addCleanup(lambda: driven.__dict__.pop("_picks", None))

    def quiet(self, driven, fake):
        """Every held session returns and every thread is joined, so no test leaves a worker running."""
        fake.release()
        driven.settle(30)

    def statuses(self):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def killed_worker(self, identifier, pid, session=None):
        """Ticket `identifier` as a SIGKILL left it: running, its worktree added, its launch journaled.

        Without a session it left nothing to resume, so the conductor relaunches it in the same attempt.
        """
        path = next(tickets.tickets_dir(self.project).glob("%02d-*.md" % identifier))
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, status="running"), body)
        self.git("worktree", "add", "-b", conductor.BRANCH % identifier, str(self.worktree(identifier)), "main")
        self.ledger.append_event("ticket_launched", {
            "ticket": identifier, "attempt": 1, "role": "coder", "model": "sonnet", "effort": "low", "skills": [],
            "worktree": str(self.worktree(identifier)), "pid": pid, "context_chars": 1, "prompt_sha256": "0" * 64,
        }, ticket=identifier)
        run_dir = self.project / "research" / "sessions" / str(identifier) / "1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "pid").write_text("%d\n" % pid, encoding="utf-8")
        if session is not None:
            self.ledger.append_event("ticket_session", {"ticket": identifier, "attempt": 1, "session_id": session,
                                                        "model": "claude-sonnet-5"}, ticket=identifier, session_id=session)
            (run_dir / "stream.jsonl").write_text(json.dumps({
                "type": "system", "subtype": "init", "session_id": session, "model": "claude-sonnet-5"}) + "\n",
                encoding="utf-8")
        return run_dir

    def left_a_failure(self, run_dir, identifier, session):
        """The result a re-adopted worker left in its stream before it died: a failure, which needs no commit."""
        with open(run_dir / "stream.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "duration_ms": 900,
                "usage": {}, "permission_denials": [], "session_id": session,
                "structured_output": failing(identifier).structured_output}) + "\n")


class WorkerSlotsTest(WorkerSlotsCase):
    """Criteria 1 and 2 of ticket 59: every session a conductor owes holds its worker slot."""

    def test_a_session_that_returns_between_the_poll_and_the_pick_keeps_its_slot(self):
        self.tickets_beside_the_first(2)
        with worker.use_fake() as fake:
            self.held(fake, 1)
            self.held(fake, 2)
            driven = self.conductor_with(1)
            launched = driven.wave()
            self.at_the_pick(driven, lambda: self.returns(driven, fake, 1))
            between = driven.wave()
            carried = driven.wave()
            self.quiet(driven, fake)
        self.assertEqual(launched.launched, [1])
        self.assertEqual((between.launched, between.done), ([], []),
                         "the slot of a session whose result is not carried yet is not free")
        self.assertEqual((carried.done, carried.launched), ([1], [2]))

    def test_the_slot_stays_taken_until_the_resume_of_a_carried_session_returns(self):
        self.tickets_beside_the_first(2)
        with worker.use_fake() as fake:
            self.held(fake, 1, Envelope())  # nothing usable: the gate resumes it once
            self.held(fake, 1)              # what the resumed session returns
            self.held(fake, 2)
            driven = self.conductor_with(1)
            driven.wave()
            self.returns(driven, fake, 1)
            resumed = driven.wave()
            kinds, live = [call.kind for call in fake.calls], fake.live()
            self.returns(driven, fake, 1)
            carried = driven.wave()
            self.quiet(driven, fake)
        self.assertEqual(kinds, ["launch", "resume"])
        self.assertEqual((resumed.launched, live), ([], 1), "the resume holds the slot its launch held")
        self.assertEqual((carried.done, carried.launched), ([1], [2]))

    def test_a_gate_resume_waits_for_a_free_slot_and_the_wait_is_said_once(self):
        self.tickets_beside_the_first(2)
        with worker.use_fake() as fake:
            self.held(fake, 1, Envelope())  # nothing usable: the gate resumes it once
            self.held(fake, 1)
            self.held(fake, 2)
            driven = self.conductor_with(2)
            launched = driven.wave()
            self.returns(driven, fake, 1)
            driven.policy = dict(driven.policy, max_parallel_workers=1)  # one slot, and ticket 2's worker holds it
            waiting = driven.wave()
            waited = ([call.kind for call in fake.calls], fake.live())
            driven.wave()
            said = driven.out.getvalue().count("waits for a free worker slot")
            self.returns(driven, fake, 2)
            freed = driven.wave()
            kinds = [call.kind for call in fake.calls]
            self.quiet(driven, fake)
        self.assertEqual(launched.launched, [1, 2])
        self.assertEqual(waited, (["launch", "launch"], 1), "the resume waits while the other worker holds the slot")
        self.assertEqual(waiting.launched, [])
        self.assertEqual(said, 1, "the wait is said once, not at every wave")
        self.assertEqual(freed.done, [2])
        self.assertEqual(kinds, ["launch", "launch", "resume"], "the resume starts at the first wave with a free slot")

    def test_two_sessions_waiting_for_one_slot_do_not_keep_each_other_out(self):
        """More waiting sessions than slots is reachable, and every one of them must still start.

        The attempts in flight can outnumber the slots: the hold on Fable's weekly window gives a
        waiting session's slot away, a restart re-adopts what the journal owes, and the policy can
        be lowered between runs, which is what this test does. Counting one waiting attempt against
        another would leave both waiting for good, with no worker running and nothing said.
        """
        self.tickets_beside_the_first(2)
        with worker.use_fake() as fake:
            for identifier in (1, 2):
                self.held(fake, identifier, Envelope())  # neither launch returns anything usable
                self.held(fake, identifier)              # what each resumed session returns
            driven = self.conductor_with(2)
            driven.wave()
            self.returns(driven, fake)  # both sessions return, and neither is carried yet
            driven.policy = dict(driven.policy, max_parallel_workers=1)
            results = []
            while len(results) < 8:
                results.append(driven.wave())
                if results[-1].ended:
                    break
                self.returns(driven, fake)
            kinds, peak = [call.kind for call in fake.calls], fake.peak
            self.quiet(driven, fake)
        self.assertTrue(results[-1].ended, "the run hung with both sessions waiting for the one slot")
        self.assertEqual(kinds, ["launch", "launch", "resume", "resume"])
        self.assertEqual(peak, 2, "the two launches ran under the policy that allowed two")
        self.assertEqual(self.statuses(), {1: "done", 2: "done"})

    def test_a_relaunch_after_a_worker_died_waits_for_a_free_slot(self):
        """Resume is start: the take-over relaunches a worker that left no session, into a slot of its own."""
        self.tickets_beside_the_first(2)
        run_dir = self.killed_worker(1, 777001, session="s-1")
        self.killed_worker(2, 777002)  # no session: it is relaunched, not resumed
        with worker.use_fake() as fake:
            fake.alive[777001] = True   # ticket 1's worker outlived its conductor and holds the one slot
            self.held(fake, 2)
            driven = self.conductor_with(1)
            adopted = driven.wave()
            waited = [call.kind for call in fake.calls]
            self.left_a_failure(run_dir, 1, "s-1")
            fake.alive[777001] = False
            freed = driven.wave()
            kinds = [call.kind for call in fake.calls]
            launched_for = [call.request.env["WAYLINE_TICKET"] for call in fake.calls]
            self.quiet(driven, fake)
        self.assertEqual(adopted.launched, [])
        self.assertEqual(waited, [], "the relaunch waits while the re-adopted worker holds the slot")
        self.assertIn("waits for a free worker slot", driven.out.getvalue())
        self.assertEqual(freed.failed, [1])
        self.assertEqual((kinds, launched_for), (["launch"], ["2"]),
                         "the relaunch starts at the first wave with a free slot")

    def test_no_more_workers_run_at_once_than_the_policy_allows(self):
        """Criterion 3: launches, a gate's resume, and the ladder's resume, every session returning at the pick."""
        for slots in (2, 3):
            with self.subTest(slots=slots):
                self.mixed_run(slots)

    def mixed_run(self, slots, waves=25):
        """Seven tickets over one run, with every held session returning between the poll and the pick."""
        self.project = self.temp / ("slots-%d" % slots)
        shutil.copytree(ONE_TICKET, self.project)
        project.init_project(self.project)
        self.ledger = Ledger(self.project)
        self.tickets_beside_the_first(7)
        with worker.use_fake() as fake:
            self.held(fake, 1, Envelope())      # nothing usable: the gate resumes it once
            self.held(fake, 1)
            self.held(fake, 2, failing(2))      # a failure the worker reports: the ladder resumes its session
            self.held(fake, 2)
            for identifier in range(3, 8):
                self.held(fake, identifier)
            driven = self.conductor_with(slots)
            self.at_the_pick(driven, lambda: self.returns(driven, fake))
            results, live = [], []
            while len(results) < waves:
                results.append(driven.wave())
                live.append(fake.live())
                if results[-1].ended:
                    break
            kinds, peak = [call.kind for call in fake.calls], fake.peak
            self.quiet(driven, fake)
        self.assertTrue(results[-1].ended, "the run did not end in %d waves" % waves)
        self.assertLessEqual(max(live), slots, "more workers were running between waves than the policy allows")
        self.assertLessEqual(peak, slots, "the launcher held more workers at once than the policy allows")
        self.assertEqual(self.statuses(), {identifier: "done" for identifier in range(1, 8)})
        self.assertEqual(kinds.count("resume"), 2, "the gate's resume and the ladder's resume both ran")


class ShellRunTest(ProjectTestCase):
    """The same path from the shell, with the fixture's own fake script: M0's "one command"."""

    def run_fixture(self, source):
        """Copy a fixture project, lay it out, and run it with `WAYLINE_LAUNCHER=fake`."""
        target = self.temp / source.name
        shutil.copytree(source, target)
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home))
        laid_out = subprocess.run([sys.executable, "-m", "wayline", "init", str(target)],
                                  cwd=HARNESS_ROOT, capture_output=True, text=True, env=environment, timeout=120)
        self.assertEqual(laid_out.returncode, 0, laid_out.stderr)

        # `init` made it the active project, so the run needs no --project: "unattended, one command".
        environment.update(WAYLINE_LAUNCHER="fake", WAYLINE_FAKE_SCRIPT=str(target / "fake-worker.json"))
        ran = subprocess.run([sys.executable, "-m", "wayline", "run"],
                             cwd=HARNESS_ROOT, capture_output=True, text=True, env=environment, timeout=300)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("frontier_empty", ran.stdout)
        self.assertEqual(list((target / conductor.WORKTREES).iterdir()), [])
        events = [json.loads(line) for line in (target / "research" / "journal.jsonl").read_text(encoding="utf-8").split("\n") if line]
        self.assertEqual(events[0]["event"], "run_started")
        self.assertEqual(events[-1]["event"], "run_ended")
        return target, ran, events

    def test_the_fixture_runs_end_to_end_with_the_fake_backend(self):
        target, ran, events = self.run_fixture(ONE_TICKET)
        self.assertIn("1 ticket(s) done", ran.stdout)
        self.assertEqual((target / "hello.txt").read_text(encoding="utf-8"), "hello\n")
        self.assertIn("ticket_done", [event["event"] for event in events])

    def test_the_five_ticket_fixture_runs_its_whole_graph_with_two_workers(self):
        """M1's demo from the shell: three waves, five tickets, the conflict serialized."""
        target, ran, events = self.run_fixture(FIVE_TICKETS)
        self.assertRegex(ran.stdout, r"\d+ wave\(s\), 5 ticket\(s\) done")
        self.assertEqual([fields["status"] for fields in tickets.read_tickets(target)], ["done"] * 5)
        closed = [event["payload"]["ticket"] for event in events if event["event"] == "ticket_done"]
        self.assertEqual(sorted(closed), [1, 2, 3, 4, 5])


class TierTest(unittest.TestCase):
    """The rung ladder (decision 16): a difficulty names a rung, which decides the model, the effort, and the budget.

    `shipped` is the harness's own `policy.json`, six rungs with none on Fable since ticket 70; `policy` is the
    seven rungs v1.0.0 shipped, with the Fable rungs a project may put back in its `harness.json`.
    """

    def setUp(self):
        self.shipped = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
        self.policy = fable_policy(self.shipped, SEVEN_RUNG_LADDER)

    def test_every_difficulty_resolves_through_its_rung_to_the_shipped_ladder(self):
        expected = [(2, "sonnet", "low", 40), (3, "sonnet", "high", 40), (5, "opus", "medium", 100), (6, "opus", "high", 200), (6, "opus", "high", 200)]
        for difficulty, (rung, model, effort, turns) in enumerate(expected, start=1):
            with self.subTest(difficulty=difficulty):
                tier = conductor.tier_for(self.shipped, difficulty)
                self.assertEqual((tier.rung, tier.model, tier.effort, tier.max_turns, tier.family), (rung, model, effort, turns, model))
                self.assertEqual(tier.label, "r%d %s %s" % (rung, model, effort))

    def test_every_difficulty_resolves_through_its_rung_to_the_ladder_of_decision_16(self):
        expected = [(2, "sonnet", "low", 40), (3, "sonnet", "high", 40), (5, "opus", "high", 100), (6, "fable", "low", 200), (7, "fable", "high", 200)]
        for difficulty, (rung, model, effort, turns) in enumerate(expected, start=1):
            with self.subTest(difficulty=difficulty):
                tier = conductor.tier_for(self.policy, difficulty)
                self.assertEqual((tier.rung, tier.model, tier.effort, tier.max_turns, tier.family), (rung, model, effort, turns, model))
                self.assertEqual(tier.label, "r%d %s %s" % (rung, model, effort))

    def test_every_rung_of_the_shipped_ladder_resolves(self):
        labels = [conductor.rung_tier(self.shipped, rung).label for rung in range(1, 7)]
        self.assertEqual(labels, ["r1 haiku medium", "r2 sonnet low", "r3 sonnet high", "r4 opus low", "r5 opus medium", "r6 opus high"])
        self.assertEqual([conductor.rung_tier(self.shipped, rung).max_turns for rung in (1, 4, 5, 6)], [40, 100, 100, 200])

    def test_every_rung_of_the_seven_rung_ladder_resolves(self):
        labels = [conductor.rung_tier(self.policy, rung).label for rung in range(1, 8)]
        self.assertEqual(labels, ["r1 haiku medium", "r2 sonnet low", "r3 sonnet high", "r4 opus low", "r5 opus high",
                                  "r6 fable low", "r7 fable high"])
        self.assertEqual([conductor.rung_tier(self.policy, rung).max_turns for rung in (1, 4, 7)], [40, 100, 200])

    def test_a_rung_on_a_full_version_name_keeps_the_name_and_takes_its_family(self):
        policy = json.loads(json.dumps(self.shipped))
        policy["tiers"][4]["model"] = "claude-opus-4-8"
        tier = conductor.tier_for(policy, 3)
        self.assertEqual((tier.rung, tier.model, tier.family, tier.effort), (5, "claude-opus-4-8", "opus", "medium"))
        self.assertEqual(tier.context_chars, 200000, "the context pack is cut at the family's cap")
        self.assertEqual(tier.label, "r5 claude-opus-4-8 medium")
        self.assertEqual(gates.verifier_tier(policy, tier.model), ("opus", "max"), "the verifier table is keyed by the family")

    def test_a_fallback_tier_keeps_the_rung(self):
        tier = conductor.fallback_tier(self.policy, conductor.tier_for(self.policy, 5))
        self.assertEqual((tier.rung, tier.model, tier.family, tier.effort, tier.context_chars), (7, "opus", "opus", "high", 200000))

    def test_the_context_cap_follows_the_model(self):
        self.assertEqual(conductor.tier_for(self.policy, 1).context_chars, 120000)
        self.assertEqual(conductor.tier_for(self.policy, 5).context_chars, 300000)
        self.assertEqual(conductor.tier_for(self.shipped, 5).context_chars, 200000, "the shipped top rung is on Opus")

    def test_a_model_outside_the_cap_table_takes_the_smallest_cap(self):
        self.assertEqual(conductor.rung_tier(self.policy, 1).context_chars, 120000, "the haiku rung")

    def test_a_rung_the_ladder_does_not_have_is_refused(self):
        with self.assertRaises(ConductorError) as caught:
            conductor.rung_tier(self.policy, 8)
        self.assertIn("1 to 7", str(caught.exception))
        with self.assertRaises(ConductorError) as caught:
            conductor.rung_tier(self.shipped, 7)
        self.assertIn("1 to 6", str(caught.exception))

    def test_the_old_difficulty_shape_names_upgrade(self):
        policy = dict(self.policy, difficulty={"1": {"model": "sonnet", "effort": "low", "budget": "small"}})
        with self.assertRaises(ConductorError) as caught:
            conductor.tier_for(policy, 1)
        self.assertIn("wayline upgrade", str(caught.exception))

    def test_the_ticket_budget_wins_over_the_tier(self):
        tier = conductor.tier_for(self.policy, 1, {"max_turns": 5, "max_minutes": 2})
        self.assertEqual((tier.max_turns, tier.max_minutes), (5, 2))

    def test_a_difficulty_the_policy_does_not_have_names_the_ones_it_does(self):
        with self.assertRaises(ConductorError) as caught:
            conductor.tier_for(self.policy, 9)
        self.assertIn("1, 2, 3, 4, 5", str(caught.exception))


class PorcelainTest(unittest.TestCase):
    """`git status --porcelain -z`, whose rename entries are two fields, not one."""

    def test_a_plain_entry_is_a_status_and_a_path(self):
        self.assertEqual(conductor.porcelain_entries("?? stray.txt\0"), [("??", "stray.txt")])

    def test_a_rename_carries_both_paths_and_does_not_swallow_the_next_entry(self):
        self.assertEqual(
            conductor.porcelain_entries("R  new.txt\0old.txt\0 M other.txt\0"),
            [("R ", "new.txt"), ("R ", "old.txt"), (" M", "other.txt")])

    def test_a_path_with_a_space_survives(self):
        self.assertEqual(conductor.porcelain_entries("?? a file.txt\0"), [("??", "a file.txt")])

    def test_nothing_changed_is_no_entries(self):
        self.assertEqual(conductor.porcelain_entries(""), [])


if __name__ == "__main__":
    unittest.main()
