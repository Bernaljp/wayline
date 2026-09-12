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

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import conductor, project, tickets, worker
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


def patch(files=None, message="ticket 1: write hello.txt", commit=True):
    return Patch(files=dict(files or HELLO), message=message, commit=commit)


def merged(results):
    """Every wave's result as one: the lists run together, and the end is the last wave's."""
    whole = WaveResult(results[-1].number)
    for result in results:
        for name in ("launched", "done", "failed", "running", "accepted", "rejected"):
            getattr(whole, name).extend(getattr(result, name))
    whole.ended, whole.reason = results[-1].ended, results[-1].reason
    return whole


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
        """Script the fake with `(envelope, patch)` pairs and take waves until nothing is left in flight.

        A wave does not wait for its workers, so the sessions it started are settled before the
        next wave carries them. The waves stop when the run ends, when no session is in flight, or
        after `waves` of them; what the fake was called with is kept.
        """
        with worker.use_fake() as fake:
            for envelope, applied in scripted:
                fake.script(envelope, patch=applied)
            self.conductor = Conductor(self.project, out=io.StringIO())
            results = []
            while True:
                results.append(self.conductor.wave())
                if results[-1].ended or not self.conductor.flight or (waves is not None and len(results) >= waves):
                    break
                self.conductor.settle()
            self.calls = list(fake.calls)  # the fake is reset when the block ends
        return results


class WholePathTest(ConductorCase):
    """One ticket from the frontier to a fast-forwarded `main`, which is M0's demo."""

    def setUp(self):
        super().setUp()
        self.result = merged(self.conduct((done(findings=[{"text": "a finding", "provenance": "hello.txt#L1"}]), patch())))

    def test_the_journal_carries_the_steps_in_order(self):
        self.assertEqual(self.sequence(), [
            "ticket_launched", "ticket_session", "ticket_result",
            "acceptance", "acceptance", "acceptance",
            "integrated", "finding", "ticket_done", "wave", "run_ended",
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
        failed = self.payload("ticket_failed")
        self.assertEqual(failed["next"], "split")
        self.assertIn("hello.txt", failed["reason"])
        self.assertIn("ticket 08", failed["reason"])
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
        self.assertEqual(self.ticket()["status"], "failed")


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
        self.assertEqual(self.payload("ticket_failed")["next"], "tier_up")
        self.assertIn("after one resume", self.payload("ticket_failed")["reason"])
        self.assertEqual(self.ticket()["status"], "failed")
        self.assertNotIn("integrated", self.sequence())
        self.assertTrue(self.worktree().exists())

    def test_a_result_for_another_ticket_is_not_this_ticket_result(self):
        self.conduct((done(ticket_id=9), patch()), (done(ticket_id=9), patch()))
        self.assertIn("ticket_id 9", self.payload("ticket_failed")["reason"])

    def test_a_run_that_ends_with_a_failed_ticket_still_ends(self):
        result = merged(self.conduct((Envelope(), None), (Envelope(), None)))
        self.assertTrue(result.ended)
        self.assertEqual(result.failed, [1])


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
        self.assertEqual(self.payload("ticket_failed")["next"], "tier_up")
        self.assertIn("still failed in the worktree", self.payload("ticket_failed")["reason"])
        self.assertNotIn("integrated", self.sequence())
        self.assertFalse((self.project / "hello.txt").exists())


class UncommittedWorkTest(ConductorCase):
    """The conductor integrates a branch, so work left in the working tree is not a result."""

    def test_an_uncommitted_file_in_the_touch_set_fails_the_ticket(self):
        self.conduct((done(), patch(commit=False)))
        self.assertIn("uncommitted", self.payload("ticket_failed")["reason"])
        self.assertIn("hello.txt", self.payload("ticket_failed")["reason"])
        self.assertEqual(self.payload("ticket_failed")["next"], "resume")
        self.assertNotIn("integrated", self.sequence())
        self.assertFalse((self.project / "hello.txt").exists(), "main must not move on it")

    def test_untracked_noise_outside_the_touch_set_is_not_held_against_the_worker(self):
        self.widen_acceptance()
        self.conduct((done(), patch()))
        self.assertIn("ticket_done", self.sequence())
        self.assertEqual(self.ticket()["status"], "done")

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
        self.assertEqual(self.payload("ticket_failed")["reason"], "the library does not exist")
        self.assertEqual(self.ticket()["status"], "failed")

    def test_needs_human_asks_the_question_the_worker_left(self):
        envelope = done()
        envelope.structured_output.update({"status": "needs_human", "summary": "which split is held out?"})
        self.conduct((envelope, None))
        self.assertEqual(self.payload("ticket_needs_human")["question"], "which split is held out?")
        self.assertEqual(self.ticket()["status"], "needs_human")

    def test_a_running_result_records_its_jobs_and_leaves_the_ticket_running(self):
        """Decision 5: a running result records the job ids and leaves the ticket for the poller."""
        envelope = done()
        envelope.structured_output.update({"status": "running", "jobs": ["j-0001"]})
        result = merged(self.conduct((envelope, None)))
        self.assertEqual(self.ticket()["status"], "running")
        self.assertEqual((result.running, result.failed, result.done), ([1], [], []))
        self.assertFalse(result.ended, "a ticket is still running, so the run is not over")
        self.assertNotIn("acceptance", self.sequence())
        self.assertIn("Jobs: `j-0001`", self.body())

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
        self.assertEqual(self.payload("ticket_failed")["next"], "resume")


class RefuseToStartTest(ConductorCase):
    """`wayline run` refuses a project it would integrate into badly, and says what to do.

    The other refusal decision 5 names, a harness checkout whose tag is not the project's pin, is
    ticket 46's: it arrives with the tagging and the `upgrade` command that fixes a mismatch. The
    harness this suite runs from is on no tag, and these tests show that does not stop a run.
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

    def test_a_flag_a_later_ticket_builds_says_which(self):
        for flag, owner in (("--detach", "ticket 13"), ("--simulate-limit", "ticket 10")):
            with self.subTest(flag=flag):
                arguments = [flag] if flag != "--simulate-limit" else [flag, "5"]
                code, _, err = run_verb(arguments + ["--project", str(self.project)])
                self.assertEqual(code, 2)
                self.assertIn(owner, err)


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
                fake.script(envelope, patch=patch() if envelope.structured_output.get("status") == "done" else None)
            conductor = Conductor(self.project, out=io.StringIO())
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
        envelope = done()
        envelope.structured_output.update({"status": "running", "jobs": ["j-0001"]})
        waves = self.conduct_run(envelope, max_waves=4)
        self.assertEqual(len(waves), 4)
        self.assertFalse(waves[-1].touched)
        self.assertFalse(waves[-1].ended)
        self.assertNotIn("run_ended", self.sequence())
        self.assertEqual(self.ticket()["status"], "running")

    def test_max_waves_stops_the_loop_whatever_the_frontier_holds(self):
        waves = self.conduct_run(max_waves=1)
        self.assertEqual(len(waves), 1)
        self.assertEqual(self.ticket()["status"], "failed")  # the fake had nothing scripted
        self.assertIn("no scripted envelope", self.payload("ticket_failed")["reason"])


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


class ParallelOutcomeTest(FiveTicketsCase):
    """What one worker's trouble does to the other worker of the same wave."""

    def test_a_launch_the_backend_refuses_is_not_counted_as_launched(self):
        """`wave.launched` names the tickets whose process started, as `ticket_launched` does."""
        self.lay_out()
        with worker.use_fake() as fake:
            fake.script(done(ticket_id=2), patch=patch({"reports/beta.md": "beta\n"}, "ticket 2"), ticket="2")
            conductor_ = Conductor(self.project, out=io.StringIO())
            wave = conductor_.wave()
            conductor_.settle()
            carried = conductor_.wave()
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
    """The policy's difficulty table, which decides the model, the effort, and the budget."""

    def setUp(self):
        self.policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))

    def test_every_difficulty_resolves_to_the_table_of_decision_14(self):
        expected = [("sonnet", "low", 40), ("sonnet", "medium", 40), ("opus", "high", 100), ("fable", "xhigh", 200), ("fable", "max", 200)]
        for difficulty, (model, effort, turns) in enumerate(expected, start=1):
            with self.subTest(difficulty=difficulty):
                tier = conductor.tier_for(self.policy, difficulty)
                self.assertEqual((tier.model, tier.effort, tier.max_turns), (model, effort, turns))

    def test_the_context_cap_follows_the_model(self):
        self.assertEqual(conductor.tier_for(self.policy, 1).context_chars, 120000)
        self.assertEqual(conductor.tier_for(self.policy, 5).context_chars, 300000)

    def test_a_model_outside_the_cap_table_takes_the_smallest_cap(self):
        policy = dict(self.policy, difficulty=dict(self.policy["difficulty"], **{"1": {"model": "haiku", "effort": "low", "budget": "small"}}))
        self.assertEqual(conductor.tier_for(policy, 1).context_chars, 120000)

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
