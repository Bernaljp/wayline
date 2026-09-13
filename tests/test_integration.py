"""The integration protocol and the integrator role (Implementation Decisions 5 and 1; ticket 08).

Two tickets whose touch sets overlap never run at once, so the conflict they can still meet is the
one a branch left by an earlier attempt carries: the branch points at a `main` that the other
ticket has since moved. `setUp` makes that branch before the run, and the fake worker commits a
conflicting edit on it. The fake integrator is a function that does in the worktree what the role's
protocol asks of a session: start the rebase, resolve the markers, continue.
"""

import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import ONE_TICKET, FIVE_TICKETS, done, drive, patch
from wayline import conductor, pacing, project, registry, tickets, worker
from wayline import ledger as ledger_module
from wayline.conductor import Conductor
from wayline.ledger import Ledger
from wayline.worker import Envelope, Patch

SECOND_TICKET = """---
id: 2
title: Add the world line
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [hello.txt]
role: coder
skills: []
outputs: [hello.txt]
acceptance:
  machine: ["test -f hello.txt", "grep -qx world hello.txt"]
  quality: []
context_pack: []
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`grep -qx world hello.txt` passes on main."
---

## Demo

`hello.txt` on `main` carries the line `world`.
"""

RESOLVED = "hello\nworld\n"
IDENTITY = ("-c", "user.name=fake integrator", "-c", "user.email=integrator@wayline.invalid")


def git_in(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), *IDENTITY, *args], capture_output=True, text=True,
                          env=None if env is None else dict(os.environ, **env))


def integrator_result(ticket_id=2, summary="resolved hello.txt: both lines kept", status="done"):
    return Envelope(structured_output={"ticket_id": ticket_id, "status": status, "summary": summary})


class TwoTicketsCase(ProjectTestCase):
    """The one-ticket fixture plus a second ticket on the same file, whose branch an earlier attempt left."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "two-tickets"
        shutil.copytree(ONE_TICKET, self.project)
        (tickets.tickets_dir(self.project) / "02-add-the-world-line.md").write_text(SECOND_TICKET, encoding="utf-8")
        project.init_project(self.project)
        self.ledger = Ledger(self.project)
        self.git("branch", conductor.BRANCH % 2, "main")
        self.seen = []  # what each fake integrator found when it started

    # --- reading the project back ---

    def git(self, *args, cwd=None):
        done_process = git_in(cwd or self.project, *args)
        self.assertEqual(done_process.returncode, 0, done_process.stderr)
        return done_process.stdout.strip()

    def events(self, name=None, ticket=None):
        events, _ = self.ledger.read_events()
        return [event for event in events
                if (name is None or event["event"] == name) and (ticket is None or event["ticket"] == ticket)]

    def payload(self, name, ticket=2):
        found = self.events(name, ticket)
        self.assertTrue(found, "ticket %s has no %s event: %s" % (ticket, name, [event["event"] for event in self.events()]))
        return found[-1]["payload"]

    def status(self, identifier):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}[identifier]

    def main_text(self, name="hello.txt"):
        return self.git("show", "main:" + name) + "\n"

    def worktree(self, identifier=2):
        return self.project / conductor.WORKTREES / str(identifier)

    def integrator_calls(self):
        return [call for call in self.calls if call.request.role == "integrator"]

    def rebasing(self, cwd):
        """Whether a rebase is in progress in a worktree, as git itself records one."""
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir", cwd=cwd))
        return (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists()

    # --- the fake integrators ---

    def look(self, request):
        cwd = Path(request.cwd)
        self.seen.append({"rebasing": self.rebasing(cwd), "branch": self.git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd),
                          "status": self.git("status", "--porcelain", cwd=cwd)})

    def resolving(self, request, message):
        """What the role's protocol asks for: rebase, resolve the markers, add, continue."""
        self.look(request)
        cwd = Path(request.cwd)
        started = git_in(cwd, "rebase", "main", env=request.env)
        self.assertNotEqual(started.returncode, 0, "the integrator's own rebase should stop on the conflict")
        (cwd / "hello.txt").write_text(RESOLVED, encoding="utf-8")
        self.git("add", "--", "hello.txt", cwd=cwd)
        continued = git_in(cwd, "rebase", "--continue", env=request.env)
        self.assertEqual(continued.returncode, 0, continued.stderr)
        return integrator_result()

    def giving_up(self, request, message):
        """An integrator that looks and returns without resolving anything."""
        self.look(request)
        return integrator_result(summary="the two edits cannot both stand", status="failed")

    def stopping_midway(self, request, message):
        """An integrator that starts the rebase and stops on the conflict, leaving it in progress."""
        self.look(request)
        git_in(Path(request.cwd), "rebase", "main", env=request.env)
        return integrator_result(summary="ran out of ideas", status="failed")

    # --- driving the run ---

    def script_workers(self, fake):
        fake.script(done(1), patch=patch(), ticket="1", role="coder")
        fake.script(done(2, summary="added the world line", outputs_written=["hello.txt"]),
                    patch=Patch({"hello.txt": "world\n"}, "ticket 2: add the world line"), ticket="2", role="coder")

    def detaching(self, request, message):
        """An integrator that resolves the conflict on a detached HEAD, leaving the ticket branch where it was."""
        self.look(request)
        cwd = Path(request.cwd)
        self.git("checkout", "-q", "--detach", cwd=cwd)
        git_in(cwd, "rebase", "main", env=request.env)
        (cwd / "hello.txt").write_text(RESOLVED, encoding="utf-8")
        self.git("add", "--", "hello.txt", cwd=cwd)
        self.assertEqual(git_in(cwd, "rebase", "--continue", env=request.env).returncode, 0)
        return integrator_result()

    def smuggling(self, request, message):
        """An integrator that resolves the conflict and slips a path the branch never changed into the rebase."""
        self.look(request)
        cwd = Path(request.cwd)
        git_in(cwd, "rebase", "main", env=request.env)
        (cwd / "hello.txt").write_text(RESOLVED, encoding="utf-8")
        (cwd / "stray.txt").write_text("not the ticket's\n", encoding="utf-8")
        self.git("add", "--", "hello.txt", "stray.txt", cwd=cwd)
        self.assertEqual(git_in(cwd, "rebase", "--continue", env=request.env).returncode, 0)
        return integrator_result()

    def conduct(self, integrator=None, cls=Conductor):
        """Run both tickets to the end with the fake worker, and `integrator` answering the integrator's launch."""
        with worker.use_fake() as fake:
            self.script_workers(fake)
            if integrator is not None:
                fake.script(respond=integrator, ticket="2", role="integrator")
            self.conductor = cls(self.project, out=io.StringIO())
            results = drive(self.conductor)
            self.calls = list(fake.calls)
        return results


class RefusedIntegratorTest(TwoTicketsCase):
    """Ticket 54 (decision 15): an integrator a usage window refused is not spent, and is launched again, never resumed."""

    def refused_midway(self, request, message):
        """An integrator that starts the rebase, stops on the conflict, and is then refused by the usage limit."""
        self.look(request)
        git_in(Path(request.cwd), "rebase", "main", env=request.env)
        return Envelope(api_error_status=429, is_error=True, exit_code=1, answered=True,
                        errors=["You've hit your session limit · resets 3:45pm (UTC)"])

    def test_a_refused_integrator_is_set_aside_and_launched_again_once_the_window_resets(self):
        now = [time.time()]
        with worker.use_fake() as fake:
            self.script_workers(fake)
            fake.script(respond=self.refused_midway, ticket="2", role="integrator")
            fake.script(respond=self.resolving, ticket="2", role="integrator")
            driven = Conductor(self.project, out=io.StringIO())
            driven.clock = lambda: now[0]
            for _ in range(8):
                driven.wave()
                driven.settle()
                if self.events("paused"):
                    break
            paused = self.payload("paused", ticket=None)
            self.assertEqual(self.status(2), "running", "the integration waits for the window rather than failing")
            now[0] = pacing.epoch(paused["resets_at"])
            drive(driven)
            self.calls = list(fake.calls)
        self.assertEqual(paused["window"], "five_hour")
        self.assertEqual([call.kind for call in self.integrator_calls()], ["launch", "launch"])
        attempt = self.project / "research" / "sessions" / "2" / "1"
        self.assertTrue((attempt / "integrator-refused-1" / "stream.jsonl").is_file(), "the refused session is kept for the record")
        self.assertEqual((self.status(2), self.payload("integrated")["resolved_by"]), ("done", "integrator"))
        self.assertEqual(self.events("ticket_failed"), [])
        self.assertEqual([(seen["rebasing"], seen["branch"]) for seen in self.seen], [(False, "ticket/2")] * 2,
                         "the rebase the refused integrator began was aborted before it was launched again")


class ResolvedConflictTest(TwoTicketsCase):
    """A rebase conflict resolved once by a fresh integrator session, then integrated."""

    def setUp(self):
        super().setUp()
        self.results = self.conduct(self.resolving)

    def test_both_tickets_are_done_and_main_carries_both_edits(self):
        self.assertEqual((self.status(1), self.status(2)), ("done", "done"))
        self.assertEqual(self.main_text(), RESOLVED)
        self.assertTrue(self.results[-1].ended)

    def test_the_journal_shows_resolved_by_integrator(self):
        self.assertEqual(self.payload("integrated", 1)["resolved_by"], "none")
        integrated = self.payload("integrated", 2)
        self.assertEqual(integrated["resolved_by"], "integrator")
        self.assertEqual(integrated["commit"], self.git("log", "-1", "--format=%H", "--grep", "ticket 2: add the world line", "main"))

    def test_the_integrator_was_launched_once_in_the_worktree_with_the_conflicting_paths_as_its_touch_set(self):
        calls = self.integrator_calls()
        self.assertEqual(len(calls), 1)
        request = calls[0].request
        self.assertEqual(Path(request.cwd), self.worktree())
        self.assertEqual(request.env["TICKET_TOUCHES"], "hello.txt")
        self.assertEqual(request.env["WAYLINE_TICKET"], "2")
        self.assertTrue(request.env["WAYLINE_RUN"].endswith("research/sessions/2/1/integrator"), request.env["WAYLINE_RUN"])
        self.assertEqual(request.env["GIT_EDITOR"], "true")

    def test_the_rebase_was_aborted_before_the_integrator_started(self):
        self.assertEqual(self.seen, [{"rebasing": False, "branch": "ticket/2", "status": ""}])

    def test_the_conflict_markers_are_the_integrator_context(self):
        prompt = self.integrator_calls()[0].request.prompt
        self.assertIn("<<<<<<<", prompt)
        self.assertIn(">>>>>>>", prompt)
        self.assertIn("## hello.txt", prompt)
        self.assertIn("git rebase main", prompt)
        self.assertIn("grep -qx world hello.txt", prompt)

    def test_the_integrator_runs_with_its_own_role_and_the_policy_tier(self):
        request = self.integrator_calls()[0].request
        role = worker.read_role("integrator")
        self.assertEqual((request.model, request.effort), ("opus", "high"))
        self.assertEqual((request.allowed_tools, request.disallowed_tools), (role.allowed_tools, role.disallowed_tools))
        settings = json.loads(Path(request.settings_path).read_text(encoding="utf-8"))
        self.assertIn("touch_set_guard.sh", json.dumps(settings))

    def test_the_acceptance_reran_on_the_rebased_branch_and_on_main(self):
        wheres = [(event["payload"]["where"], event["payload"]["pass"]) for event in self.events("acceptance", 2)]
        self.assertEqual(wheres, [("worktree", True), ("rebased", True), ("main", True)])

    def test_the_branch_and_the_worktree_are_deleted(self):
        self.assertFalse(self.worktree().exists())
        self.assertNotIn("ticket/2", self.git("branch"))

    def test_the_integrator_session_is_noted_in_the_ticket_file(self):
        body = (tickets.tickets_dir(self.project) / "02-add-the-world-line.md").read_text(encoding="utf-8")
        self.assertIn("**Integrator** (attempt 1), session `%s`" % self.seen_session(), body)
        self.assertIn("resolved hello.txt: both lines kept", body)

    def seen_session(self):
        stream = self.integrator_calls()[0].run_dir / "stream.jsonl"
        return json.loads(stream.read_text(encoding="utf-8").split("\n")[0])["session_id"]

    def test_the_integrator_session_does_not_enter_the_replayed_attempt(self):
        """Nothing journaled for the integrator is a `ticket_*` event, so a restart replays the coder's attempt alone."""
        launched = self.events("ticket_launched", 2)
        self.assertEqual([event["payload"]["role"] for event in launched], ["coder"])
        sessions = {event["payload"]["session_id"] for event in self.events("ticket_session", 2)}
        self.assertNotIn(self.integrator_calls()[0].run_dir.name, sessions)
        self.assertEqual(len(sessions), 1)


class SecondConflictTest(TwoTicketsCase):
    """An integration the integrator did not resolve fails the ticket with a request to split it."""

    def assert_split(self, launched=1):
        failed = self.payload("ticket_failed")
        self.assertEqual(failed["next"], "split")
        self.assertIn("hello.txt", failed["reason"])
        self.assertIn("integrator", failed["reason"])
        self.assertEqual(self.status(2), "failed")
        self.assertEqual(self.events("integrated", 2), [])
        self.assertEqual(self.main_text(), "hello\n")
        self.assertEqual(len(self.integrator_calls()), launched, "the integrator is launched once, never twice")
        self.assertTrue(self.worktree().exists(), "the branch and its worktree stay for whoever re-cuts the ticket")
        self.assertFalse(self.rebasing(self.worktree()))

    def test_an_integrator_that_resolves_nothing_yields_split(self):
        self.conduct(self.giving_up)
        self.assert_split()
        self.assertEqual(self.git("status", "--porcelain", cwd=self.worktree()), "")

    def test_an_integrator_that_leaves_the_rebase_in_progress_yields_split(self):
        self.conduct(self.stopping_midway)
        self.assert_split()

    def test_an_integrator_that_cannot_be_launched_yields_split(self):
        self.conduct(None)
        self.assert_split(launched=0)  # the fake refused the launch before it took a call
        self.assertIn("could not be launched", self.payload("ticket_failed")["reason"])

    def test_no_acceptance_runs_on_a_branch_that_never_rebased(self):
        self.conduct(self.giving_up)
        self.assertEqual([event["payload"]["where"] for event in self.events("acceptance", 2)], ["worktree"])


class HandedBackTest(TwoTicketsCase):
    """What the integrator hands back is checked: the ticket branch, and no path the branch did not change."""

    def test_a_resolution_on_a_detached_head_is_not_integrated(self):
        self.conduct(self.detaching)
        failed = self.payload("ticket_failed")
        self.assertEqual(failed["next"], "split")
        self.assertIn("detached HEAD", failed["reason"])
        self.assertEqual(self.events("integrated", 2), [])
        self.assertEqual(self.main_text(), "hello\n")

    def test_a_path_the_branch_never_changed_is_not_integrated(self):
        self.conduct(self.smuggling)
        failed = self.payload("ticket_failed")
        self.assertEqual(failed["next"], "split")
        self.assertIn("stray.txt", failed["reason"])
        self.assertEqual(self.events("integrated", 2), [])
        self.assertNotIn("stray.txt", self.git("ls-tree", "--name-only", "main"))


class WiderConflictTest(TwoTicketsCase):
    """The touch set is every path both sides changed, not only the path the rebase stopped on first."""

    def setUp(self):
        super().setUp()
        self.git("checkout", "-q", conductor.BRANCH % 2)
        (self.project / "b.txt").write_text("branch b\n", encoding="utf-8")
        self.git("add", "--", "b.txt")
        self.git("commit", "-q", "-m", "ticket 2: an earlier attempt's b.txt")
        self.git("checkout", "-q", "main")
        (self.project / "b.txt").write_text("main b\n", encoding="utf-8")
        self.git("add", "--", "b.txt")
        self.git("commit", "-q", "-m", "main: b.txt")

    def test_the_integrator_may_write_the_later_conflict_too(self):
        self.conduct(self.giving_up)
        request = self.integrator_calls()[0].request
        self.assertEqual(request.env["TICKET_TOUCHES"], "b.txt:hello.txt")
        self.assertIn("## b.txt", request.prompt)
        self.assertIn("`b.txt`, `hello.txt`", request.prompt)


class LockedStepsTest(TwoTicketsCase):
    """One integration at a time under the ledger lock: the rebases and the fast-forward hold it, the acceptance does not."""

    def test_the_git_steps_hold_the_lock_and_the_acceptance_runs_outside_it(self):
        seen = []

        class Watching(Conductor):
            def holding(inner):
                return ledger_module._process_lock(inner.ledger.lock_path).depth > 0

            def _git(inner, cwd, *args, ok=(0,)):
                if args[:1] == ("merge",) or args[:2] == ("rebase", "main"):
                    seen.append((" ".join(args[:2]), inner.holding()))
                return super()._git(cwd, *args, ok=ok)

            def _accept(inner, attempt, where, cwd):
                seen.append(("accept " + where, inner.holding()))
                return super()._accept(attempt, where, cwd)

        self.conduct(self.resolving, cls=Watching)
        self.assertEqual(self.payload("integrated")["resolved_by"], "integrator")
        self.assertEqual(sum(1 for step, _ in seen if step == "rebase main"), 3, "one for ticket 1, two for ticket 2")
        for step, holding in seen:
            with self.subTest(step=step):
                self.assertEqual(holding, not step.startswith("accept"))


class Died(BaseException):
    """A conductor killed at a chosen step: nothing in the wave catches it."""


class RestartTest(TwoTicketsCase):
    """A conductor that dies around the integrator: the next one never launches a second integrator for the attempt."""

    def die_after_the_integrator(self, integrator):
        with worker.use_fake() as fake:
            self.script_workers(fake)
            fake.script(respond=integrator, ticket="2", role="integrator")

            class Dying(Conductor):
                def _launch_integrator(inner, attempt, conflict, touches):
                    super()._launch_integrator(attempt, conflict, touches)
                    raise Died()

            with self.assertRaises(Died):
                drive(Dying(self.project, out=io.StringIO()))
            self.results = drive(Conductor(self.project, out=io.StringIO()))
            self.calls = list(fake.calls)

    def test_a_resolution_the_dead_conductor_never_integrated_is_integrated_as_the_integrator_s(self):
        self.die_after_the_integrator(self.resolving)
        self.assertEqual(self.status(2), "done")
        self.assertEqual(self.payload("integrated")["resolved_by"], "integrator")
        self.assertEqual(self.main_text(), RESOLVED)
        self.assertEqual(len(self.integrator_calls()), 1)

    def test_a_rebase_the_dead_conductor_s_integrator_left_in_progress_is_split_without_a_second_integrator(self):
        self.die_after_the_integrator(self.stopping_midway)
        failed = self.payload("ticket_failed")
        self.assertEqual(failed["next"], "split")
        self.assertIn("before the conductor restarted", failed["reason"])
        self.assertEqual(len(self.integrator_calls()), 1)
        self.assertFalse(self.rebasing(self.worktree()))
        self.assertEqual(self.main_text(), "hello\n")


class PausedIntegrationTest(TwoTicketsCase):
    """The integrator is model work: the owner's pause holds it, and the integration waits in flight."""

    def test_the_integrator_waits_for_the_resume(self):
        with worker.use_fake() as fake:
            self.script_workers(fake)
            fake.script(respond=self.resolving, ticket="2", role="integrator")
            driven = Conductor(self.project, out=io.StringIO())
            driven.wave()          # launches 1
            driven.settle()
            driven.wave()          # carries 1, launches 2
            driven.settle()
            project.control(self.project, "pause")
            held = driven.wave()   # carries 2 up to the conflict, and holds the integrator
            self.assertEqual([call.request.role for call in fake.calls].count("integrator"), 0)
            self.assertIn(2, driven.flight)
            self.assertEqual((held.done, held.failed), ([], []))
            self.assertEqual(self.status(2), "running")
            again = driven.wave()  # still paused: nothing changes
            self.assertEqual((again.done, again.failed), ([], []))
            project.control(self.project, "resume")
            resumed = driven.wave()
            self.calls = list(fake.calls)
        self.assertEqual(resumed.done, [2])
        self.assertEqual((held.outcomes, again.outcomes, resumed.outcomes), (0, 0, 1),
                         "one worker result is one outcome, counted by the wave that concludes it")
        waves = [event["payload"] for event in self.events("wave")]
        self.assertEqual([wave["progressed"] for wave in waves], [True, True])
        self.assertEqual(len(self.integrator_calls()), 1)
        self.assertEqual(self.payload("integrated")["resolved_by"], "integrator")
        self.assertEqual(self.main_text(), RESOLVED)
        self.assertEqual([event["payload"]["where"] for event in self.events("acceptance", 2)],
                         ["worktree", "rebased", "main"], "the worktree acceptance is not run twice")


class BlockedResultTest(TwoTicketsCase):
    """A result that names a path outside its touch set, or what blocks it, is never integrated."""

    def conduct_blocked(self, **blocked):
        with worker.use_fake() as fake:
            fake.script(done(1, **blocked), patch=patch(), ticket="1", role="coder")
            fake.script(done(2), patch=Patch({"hello.txt": "world\n"}, "ticket 2"), ticket="2", role="coder")
            driven = Conductor(self.project, out=io.StringIO())
            drive(driven, waves=2)
            self.calls = list(fake.calls)

    def test_touched_outside_declared_blocks_the_ticket_with_the_path(self):
        self.conduct_blocked(touched_outside_declared=["docs/readme.md"])
        self.assertEqual(self.payload("ticket_blocked", 1), {"ticket": 1, "path": "docs/readme.md"})
        self.assert_not_integrated()

    def test_blocked_on_blocks_the_ticket_with_the_path(self):
        self.conduct_blocked(blocked_on="src/other.py")
        self.assertEqual(self.payload("ticket_blocked", 1)["path"], "src/other.py")
        self.assert_not_integrated()

    def assert_not_integrated(self):
        self.assertEqual(self.status(1), "blocked")
        self.assertEqual(self.events("acceptance", 1), [])
        self.assertEqual(self.events("integrated", 1), [])
        self.assertNotIn("ticket 1: write hello.txt", self.git("log", "--format=%s", "main"))
        self.assertEqual(self.integrator_calls(), [])


class LedgerCommitsTest(ProjectTestCase):
    """`ledger: wave <n>` lands on `main` under a branch cut before it, and the branch still fast-forwards."""

    def git(self, *args):
        done_process = git_in(self.project, *args)
        self.assertEqual(done_process.returncode, 0, done_process.stderr)
        return done_process.stdout.strip()

    def payload(self, name, ticket):
        events, _ = Ledger(self.project).read_events()
        return [event["payload"] for event in events if event["event"] == name and event["ticket"] == ticket][-1]

    def ancestor(self, older, newer):
        return git_in(self.project, "merge-base", "--is-ancestor", older, newer).returncode == 0

    def commit_named(self, subject):
        return self.git("log", "-1", "--format=%H", "--fixed-strings", "--grep", subject, "main")

    def test_one_ticket_rebases_over_the_ledger_commit_of_the_wave_that_launched_it(self):
        self.project = self.temp / "one-ticket"
        shutil.copytree(ONE_TICKET, self.project)
        project.init_project(self.project)
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            driven = Conductor(self.project, out=io.StringIO())
            launched = driven.wave()
            self.assertIsNotNone(launched.ledger_commit, "the launching wave commits the ledger to main")
            base = self.git("merge-base", "main", conductor.BRANCH % 1)
            self.assertNotEqual(base, launched.ledger_commit, "the branch was cut before that commit")
            driven.settle()
            carried = driven.wave()
        commit = self.payload("integrated", 1)["commit"]
        self.assertTrue(self.ancestor(launched.ledger_commit, commit))
        self.assertEqual(self.git("rev-parse", commit + "~1"), launched.ledger_commit)
        self.assertEqual(self.git("rev-parse", carried.ledger_commit + "~1"), commit)
        self.assertEqual(self.git("log", "-1", "--format=%s", "main"), "ledger: wave 2")

    def test_a_ticket_still_running_across_two_ledger_commits_fast_forwards_after_its_rebase(self):
        self.project = self.temp / "five-tickets"
        shutil.copytree(FIVE_TICKETS, self.project)
        project.init_project(self.project)
        script = json.loads((FIVE_TICKETS / "fake-worker.json").read_text(encoding="utf-8"))
        for entry in script:
            if str(entry.get("ticket")) == "2":
                entry["delay"] = 300  # released by the test, never waited out
        slow = self.temp / "slow-worker.json"
        slow.write_text(json.dumps(script), encoding="utf-8")
        with worker.use_fake() as fake:
            fake.load(slow)
            driven = Conductor(self.project, out=io.StringIO())
            first = driven.wave()                 # launches 1 and 2
            self.assertEqual(first.launched, [1, 2])
            base = self.git("merge-base", "main", conductor.BRANCH % 2)
            driven.flight[1].thread.join()
            second = driven.wave()                # carries 1, launches 3; 2 still runs
            self.assertEqual(second.done, [1])
            self.assertIn(2, driven.flight)
            driven.flight[3].thread.join()
            fake.release(ticket=2)
            driven.flight[2].thread.join()
            third = driven.wave()                 # carries 2 and 3
            self.assertIn(2, third.done)
        commit = self.payload("integrated", 2)["commit"]
        for wave in (first, second):
            self.assertIsNotNone(wave.ledger_commit)
            self.assertFalse(self.ancestor(wave.ledger_commit, base), "ticket 2 was branched before %s" % wave.ledger_commit)
            self.assertTrue(self.ancestor(wave.ledger_commit, commit))
        self.assertTrue(self.ancestor(commit, "main"))
        self.assertEqual(self.payload("integrated", 2)["resolved_by"], "none")


class IntegratorRoleTest(ProjectTestCase):
    """`roles/integrator/`: a read-and-edit session whose writes the touch set confines to the conflicting paths."""

    def setUp(self):
        super().setUp()
        self.role = worker.read_role("integrator")

    def test_the_role_reads_and_edits_and_writes_no_new_file(self):
        for tool in ("Read", "Edit", "Glob", "Grep"):
            self.assertIn(tool, self.role.allowed_tools)
        for tool in ("Write", "NotebookEdit", "Agent", "WebFetch", "WebSearch", "mcp__*", "Skill"):
            self.assertIn(tool, self.role.disallowed_tools)
            self.assertNotIn(tool, self.role.allowed_tools)

    def test_its_commands_are_the_rebase_and_reading_git(self):
        bash = [tool for tool in self.role.allowed_tools if tool.startswith("Bash(")]
        for exact in ("Bash(git rebase main)", "Bash(git rebase --continue)", "Bash(git rebase --abort)"):
            self.assertIn(exact, bash)
        self.assertNotIn("Bash(git rebase *)", bash, "a glob would admit `git rebase --exec <any command>`")
        self.assertIn("Bash(git add *)", bash)
        for command in bash:
            self.assertRegex(command, r"^Bash\((git (rebase|add|status|diff|log|show)|wayline accept)")
        for forbidden in ("push", "reset", "merge", "checkout", "commit", "python"):
            self.assertFalse(any(forbidden in command for command in bash), forbidden)

    def test_it_returns_the_result_schema_and_judges_nothing(self):
        self.assertEqual(self.role.output_schema, "result")
        self.assertFalse(self.role.may_judge)
        self.assertEqual(self.role.kinds, [], "the conductor launches it; the librarian never assigns it")
        self.assertIn("git rebase main", self.role.protocol)
        self.assertNotIn("tools", self.role.agent_json("opus", "high")["integrator"])

    def test_its_sidecar_is_stamped(self):
        sidecar = json.loads((HARNESS_ROOT / "roles" / "integrator" / "wayline.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["sha256"], registry.content_sha256(HARNESS_ROOT / "roles" / "integrator"))


if __name__ == "__main__":
    import unittest
    unittest.main()
