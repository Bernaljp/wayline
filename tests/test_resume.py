"""Resume from the journal, the heartbeat, control events, and worker re-adoption (ticket 09).

Implementation Decisions 5 and Testing Decisions seam 4: the conductor is tested by replaying a
journal and by driving its waves, and what is asserted is what the owner and the next process can
observe: the journal, the ticket files, `research/conductor.json`, and `main`.
"""

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import EXAMPLES_DIR, FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from tests.test_conductor import FIVE_TICKETS, ConductorCase, done, drive, patch, run_verb
from tests.test_verdicts import passing
from wayline import cli, project, replay, tickets, worker
from wayline.conductor import Conductor, ConductorError
from wayline.ledger import Ledger, conductor_holder, read_heartbeat
from wayline.project import control
from wayline.worker import Envelope

HOLDER = {"pid": 4242, "started_at": "2026-09-12T10:00:00.000Z", "last_wave_at": None, "harness_tag": "v0.0.0"}


class HeartbeatTest(ConductorCase):
    """The heartbeat is written every poll, and its flock keeps a second conductor off the project."""

    def hold(self):
        """Another conductor, as far as this project can tell: the lock held and a heartbeat written."""
        holder = Ledger(self.project).heartbeat().acquire()
        self.addCleanup(holder.release)
        holder.write(**HOLDER)
        return holder

    def test_the_run_writes_the_heartbeat_at_every_poll_and_lets_go_of_it_at_the_end(self):
        seen = []
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            self.conductor = Conductor(self.project, out=io.StringIO())

            def poll(seconds):
                seen.append((read_heartbeat(self.project), conductor_holder(self.project)))
                self.conductor.settle()

            waves = self.conductor.run(wait=poll)
        self.assertTrue(waves[-1].ended)
        self.assertTrue(seen, "the run never waited between waves")
        beat, holder = seen[0]
        self.assertEqual(set(beat), {"pid", "started_at", "last_wave_at", "harness_tag"})
        self.assertEqual((beat["pid"], beat["harness_tag"]), (os.getpid(), "v0.0.0"))
        self.assertEqual(holder, beat, "while the run polls, the heartbeat names the conductor holding the lock")
        self.assertLessEqual(beat["started_at"], beat["last_wave_at"])
        self.assertGreaterEqual(read_heartbeat(self.project)["last_wave_at"], beat["last_wave_at"])
        self.assertIsNone(conductor_holder(self.project), "the lock outlived the run")

    def test_a_second_conductor_is_refused_before_it_journals_anything(self):
        self.hold()
        with self.assertRaises(ConductorError) as caught:
            Conductor(self.project, out=io.StringIO()).run()
        self.assertIn("4242", str(caught.exception))
        self.assertEqual(self.events(), [])

    def test_the_run_verb_names_the_conductor_already_running_and_exits_1(self):
        self.hold()
        code, _, err = run_verb(["--project", str(self.project)])
        self.assertEqual(code, 1)
        self.assertIn("4242", err)
        self.assertIn("wayline stop", err)


KILLED_PID = 777001
SESSION = "s-killed"


class ReadoptionCase(ConductorCase):
    """The one-ticket project as a SIGKILL leaves it while ticket 1's worker is running."""

    def killed(self, session=True, stream=True):
        """The ticket running, its worktree added, its launch journaled, and maybe its session."""
        fields, body = tickets.read_ticket(tickets.tickets_dir(self.project) / "01-write-the-hello-file.md")
        tickets.write_ticket(self.ledger, dict(fields, status="running"), body)
        self.git("worktree", "add", "-b", "ticket/1", str(self.worktree()), "main")
        self.ledger.append_event("ticket_launched", {
            "ticket": 1, "attempt": 1, "role": "coder", "model": "sonnet", "effort": "low", "skills": [],
            "worktree": str(self.worktree()), "pid": KILLED_PID, "context_chars": 1, "prompt_sha256": "0" * 64,
        }, ticket=1)
        if session:
            self.ledger.append_event("ticket_session", {"ticket": 1, "attempt": 1, "session_id": SESSION,
                                                        "model": "claude-sonnet-5"}, ticket=1, session_id=SESSION)
        self.run_dir().mkdir(parents=True, exist_ok=True)
        (self.run_dir() / "pid").write_text("%d\n" % KILLED_PID, encoding="utf-8")
        lines = [{"type": "system", "subtype": "init", "session_id": SESSION, "model": "claude-sonnet-5"}] if stream else []
        (self.run_dir() / "stream.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    def run_dir(self):
        return self.project / "research" / "sessions" / "1" / "1"

    def worker_finishes(self, **extra):
        """What the worker does after its conductor died: commit on the ticket branch, write its result."""
        (self.worktree() / "hello.txt").write_text("hello\n", encoding="utf-8")
        self.git("add", "--", "hello.txt", cwd=self.worktree())
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ticket 1: write hello.txt", cwd=self.worktree())
        result = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "duration_ms": 1200,
                  "usage": {}, "permission_denials": [], "session_id": SESSION,
                  "structured_output": done(**extra).structured_output}
        with open(self.run_dir() / "stream.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(result) + "\n")

    def resume(self, *scripted):
        """A new conductor over the killed project, run to its end with the fake scripted."""
        with worker.use_fake() as fake:
            for envelope, applied in scripted:
                fake.script(envelope, patch=applied)
            conductor = Conductor(self.project, out=io.StringIO())
            # Bounded, so a restart that fails to pick something up fails the test instead of polling forever.
            self.waves = conductor.run(resume=True, wait=lambda seconds: conductor.settle(), max_waves=12)
            self.calls = list(fake.calls)

    def resumed(self):
        return [(event["payload"]["reason"], event["payload"]["session_id"]) for event in self.events("ticket_resumed")]


class ReadoptionTest(ReadoptionCase):
    """Criterion 2: a launch with no result is re-adopted, resumed by session id, or relaunched."""

    def test_a_live_worker_is_readopted_by_its_stream_and_carried_when_it_returns(self):
        self.killed()
        with worker.use_fake() as fake:
            fake.alive[KILLED_PID] = True
            conductor = Conductor(self.project, out=io.StringIO())
            conductor.wave()
            self.assertEqual(self.resumed(), [("readopted", SESSION)])
            self.assertEqual(self.ticket()["status"], "running")
            self.worker_finishes()
            fake.alive[KILLED_PID] = False
            carried = conductor.wave()
            calls = list(fake.calls)
        self.assertEqual(calls, [], "a re-adopted worker is neither resumed nor launched again")
        self.assertEqual(carried.done, [1])
        self.assertEqual(self.ticket()["status"], "done")
        self.assertEqual((self.project / "hello.txt").read_text(encoding="utf-8"), "hello\n")

    def test_a_worker_that_finished_while_no_conductor_watched_is_carried_from_its_stream(self):
        self.killed()
        self.worker_finishes()
        self.resume()
        self.assertEqual(self.resumed(), [("readopted", SESSION)])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_dead_worker_whose_session_started_is_resumed_by_its_session_id(self):
        self.killed()
        self.resume((done(), patch()))
        self.assertEqual(self.resumed(), [("worker_died", SESSION)])
        self.assertEqual([(call.kind, call.session_id) for call in self.calls], [("resume", SESSION)])
        self.assertIn("interrupted", self.calls[0].message)
        self.assertEqual(self.ticket()["status"], "done")
        self.assertEqual(self.payload("run_ended"), {"reason": "frontier_empty"})

    def test_a_session_the_stream_saw_and_the_journal_missed_is_journaled_and_resumed(self):
        self.killed(session=False)
        self.resume((done(), patch()))
        self.assertEqual([event["payload"]["session_id"] for event in self.events("ticket_session")], [SESSION])
        self.assertEqual(self.resumed(), [("worker_died", SESSION)])
        self.assertEqual([call.kind for call in self.calls], ["resume"])

    def test_a_dead_worker_that_never_said_who_it_was_is_relaunched_in_the_same_attempt(self):
        self.killed(session=False, stream=False)
        self.resume((done(), patch()))
        self.assertEqual(self.resumed(), [("worker_died", None)])
        self.assertEqual([call.kind for call in self.calls], ["launch"])
        self.assertEqual([event["payload"]["attempt"] for event in self.events("ticket_launched")], [1, 1])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_readopted_worker_past_its_budget_is_sent_sigterm_and_resumed_once_out_of_time(self):
        """Decision 3's timeout, for the worker nobody's launcher is timing: the one a restart re-adopted."""
        self.killed()
        (self.run_dir() / "env.json").write_text(json.dumps({"started_at": "2020-01-01T00:00:00.000Z"}), encoding="utf-8")
        with worker.use_fake() as fake:
            fake.alive[KILLED_PID] = True
            fake.script(done(), patch=patch())
            drive(Conductor(self.project, out=io.StringIO()))
            calls, alive = list(fake.calls), fake.alive[KILLED_PID]
        self.assertFalse(alive, "the worker was not sent SIGTERM")
        self.assertEqual(self.resumed(), [("readopted", SESSION), ("timeout", SESSION)])
        self.assertEqual([(call.kind, call.session_id) for call in calls], [("resume", SESSION)])
        self.assertIn("ran out of time", calls[0].message)
        self.assertEqual(self.ticket()["status"], "done")


class PausedRestartTest(ReadoptionCase):
    """Decision 5, wave step 8: while the owner has paused the run, a restart starts no session either."""

    def restart_while_paused(self):
        """A first wave over the killed project while paused; then the owner resumes and the run goes on."""
        control(self.project, "pause")
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            driven = Conductor(self.project, out=io.StringIO())
            held = driven.wave()
            self.held = (list(fake.calls), self.events("ticket_resumed"), held.ended)
            control(self.project, "resume")
            drive(driven)
            self.calls = list(fake.calls)

    def test_a_relaunch_waits_until_the_owner_resumes_the_run(self):
        self.killed(session=False, stream=False)
        self.restart_while_paused()
        self.assertEqual(self.held, ([], [], False))
        self.assertEqual([call.kind for call in self.calls], ["launch"])
        self.assertEqual(self.resumed(), [("worker_died", None)])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_resume_by_session_id_waits_until_the_owner_resumes_the_run(self):
        self.killed()
        self.restart_while_paused()
        self.assertEqual(self.held, ([], [], False))
        self.assertEqual([(call.kind, call.session_id) for call in self.calls], [("resume", SESSION)])
        self.assertEqual(self.resumed(), [("worker_died", SESSION)])
        self.assertEqual(self.ticket()["status"], "done")


class TakeOverCase(ReadoptionCase):
    def write(self, **changes):
        """A change to ticket 1's file, as a hand or a conductor that died halfway would leave it."""
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, **changes), body)


class CarryAfterRestartTest(TakeOverCase):
    """A session that returned, whose result is journaled and whose outcome was never carried."""

    def test_a_result_journaled_and_never_carried_is_carried_without_journaling_anything_twice(self):
        finding = {"text": "hello is one line", "provenance": "hello.txt#L1"}
        self.killed()
        self.worker_finishes(findings=[finding])
        self.ledger.append_event("ticket_result", {
            "ticket": 1, "attempt": 1, "session_id": SESSION, "status": "done", "turns": 3,
            "duration_ms": 1200, "usage": {}, "permission_denials": [], "valid": True,
        }, ticket=1, session_id=SESSION)
        record = {"id": "t1-a1-f1", "ticket": 1, "text": finding["text"], "provenance": finding["provenance"], "negative": False}
        self.ledger.append_record("findings.jsonl", record)
        self.ledger.append_event("finding", record, ticket=1)
        self.resume()
        self.assertEqual((self.resumed(), self.calls), ([], []))
        self.assertEqual(len(self.events("ticket_result")), 1)
        self.assertEqual(len(self.events("finding")), 1)
        filed = [line for line in (self.project / "research" / "findings.jsonl").read_text(encoding="utf-8").split("\n") if line]
        self.assertEqual(len(filed), 1)
        self.assertEqual(self.ticket()["status"], "done")
        self.assertEqual((self.project / "hello.txt").read_text(encoding="utf-8"), "hello\n")


class ReconcileTest(TakeOverCase):
    """Criterion 1: the ticket files follow the journal, except where a hand edit wins."""

    def test_a_ticket_left_running_with_no_launch_in_the_journal_goes_back_to_the_frontier(self):
        self.write(status="running")
        self.resume((done(), patch()))
        self.assertEqual([event["payload"]["attempt"] for event in self.events("ticket_launched")], [1])
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_failure_the_journal_holds_wins_over_a_ticket_file_not_rewritten_yet(self):
        self.killed()
        self.ledger.append_event("ticket_failed", {"ticket": 1, "attempt": 1, "reason": "no", "next": "resume"}, ticket=1)
        self.resume()
        self.assertEqual(self.ticket()["status"], "failed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.payload("run_ended"), {"reason": "frontier_empty"})

    def test_a_hand_pinned_difficulty_survives_the_reconcile_and_sets_the_relaunch_tier(self):
        self.killed(session=False, stream=False)
        self.write(pinned_difficulty=3)
        self.resume((done(), patch()))
        self.assertEqual((self.calls[0].request.model, self.calls[0].request.effort), ("opus", "high"))
        self.assertEqual(self.ticket()["pinned_difficulty"], 3)
        self.assertEqual(self.ticket()["status"], "done")

    def test_the_worktree_of_a_ticket_the_journal_closed_is_removed(self):
        self.killed()
        self.ledger.append_event("ticket_done", {"ticket": 1}, ticket=1)
        self.resume()
        self.assertFalse(self.worktree().exists())
        self.assertNotIn("ticket/1", self.branches())
        self.assertEqual(self.ticket()["status"], "done")


class VerdictAfterRestartTest(TakeOverCase):
    """A done ticket whose verdict was queued in a conductor that died is verdicted by the next one."""

    def test_a_done_ticket_whose_verdict_was_never_taken_is_verdicted_and_accepted(self):
        self.killed()
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, _ = tickets.read_ticket(path)
        self.write(status="done", acceptance=dict(fields["acceptance"], quality=["hello.txt holds the one line hello"]))
        self.ledger.append_event("integrated", {"ticket": 1, "commit": self.git("rev-parse", "main"), "resolved_by": "none"}, ticket=1)
        self.ledger.append_event("ticket_done", {"ticket": 1}, ticket=1)
        self.resume((passing(), None))
        self.assertEqual([call.request.role for call in self.calls], ["verifier"])
        self.assertEqual(len(self.events("verdict")), 1)
        self.assertEqual(self.ticket()["status"], "accepted")


class ControlCase(ConductorCase):
    """A conductor driven wave by wave, with control events appended between its waves as another process would."""

    def conductor_over(self, *scripted, **policy):
        """A conductor driven wave by wave over the fake, scripted with `(envelope, patch, delay)` triples.

        A long `delay` holds a worker until the test releases it, so nothing here sleeps.
        """
        fake = self.enterContext(worker.use_fake())
        for envelope, applied, delay in scripted:
            fake.script(envelope, patch=applied, delay=delay)
        driven = Conductor(self.project, out=io.StringIO())
        driven.policy = dict(driven.policy, **policy)
        self.addCleanup(driven.settle, 30)
        self.addCleanup(fake.release)
        return fake, driven

    def until_quiet(self, driven):
        """The last result of `drive`: waves until the run ends or nothing is in flight."""
        return drive(driven)[-1]

    def another_ticket(self, identifier):
        """Ticket `identifier`, independent of ticket 1: its own file to write and its own acceptance."""
        fields, body = tickets.read_ticket(tickets.tickets_dir(self.project) / "01-write-the-hello-file.md")
        name = "f%d.txt" % identifier
        tickets.write_ticket(self.ledger, dict(fields, id=identifier, title="Write file %d" % identifier, touches=[name],
                                               outputs=[name], acceptance=dict(fields["acceptance"], machine=["test -f " + name])), body)

    def second_ticket(self):
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, id=2, title="Write the second file",
                                               touches=["second.txt"], outputs=["second.txt"]), body)


class ControlTest(ControlCase):
    """Criterion 4: the conductor applies the control events other processes appended, at its next wave."""

    def test_a_paused_run_launches_nothing_until_the_owner_resumes_it(self):
        fake, driven = self.conductor_over((done(), patch(), 0))
        control(self.project, "pause")
        held = driven.wave()
        control(self.project, "resume")
        launched = driven.wave()
        driven.settle()
        last = driven.wave()
        self.assertEqual((held.launched, launched.launched), ([], [1]))
        self.assertFalse(held.ended, "a paused run with work left is not over")
        self.assertTrue(last.ended)
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_stop_ends_the_run_now_and_leaves_its_worker_running_for_the_next_run_to_readopt(self):
        fake, driven = self.conductor_over((done(), patch(), 600))
        driven.wave()
        control(self.project, "stop")
        stopped = driven.wave()
        self.assertEqual((stopped.ended, stopped.reason), (True, "stopped"))
        self.assertEqual(self.payload("run_ended"), {"reason": "stopped"})
        self.assertEqual(self.events("ticket_result"), [], "a stop does not wait for the worker")
        self.assertTrue(worker.pid_alive(self.payload("ticket_launched")["pid"]), "nor does it end the worker")
        after = Conductor(self.project, out=io.StringIO())

        def wait(seconds):
            fake.release()  # the worker the stopped run left behind finishes on its own
            driven.settle()

        after.run(resume=True, wait=wait, max_waves=12)
        self.assertEqual([event["payload"]["reason"] for event in self.events("ticket_resumed")], ["readopted"])
        self.assertEqual([call.kind for call in fake.calls], ["launch"], "nothing was resumed or launched again")
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_drain_waits_for_the_running_worker_and_launches_nothing_new(self):
        self.second_ticket()
        fake, driven = self.conductor_over((done(), patch(), 600), max_parallel_workers=1)
        self.assertEqual(driven.wave().launched, [1])
        control(self.project, "stop", {"drain": True})
        draining = driven.wave()
        fake.release()
        driven.settle()
        ended = driven.wave()
        self.assertFalse(draining.ended or draining.launched)
        self.assertEqual((ended.done, ended.launched, ended.reason), ([1], [], "stopped"))
        self.assertEqual({item["id"]: item["status"] for item in tickets.read_tickets(self.project)}, {1: "done", 2: "open"})

    def test_cancel_ends_the_running_worker_and_parks_its_ticket(self):
        fake, driven = self.conductor_over((done(), patch(), 30))
        driven.wave()
        control(self.project, "cancel", {"ticket": 1})
        parked = driven.wave()
        self.assertEqual(self.payload("ticket_cancelled"), {"ticket": 1, "by": "cli"})
        self.assertEqual(self.ticket()["status"], "parked")
        self.assertEqual(self.events("ticket_result"), [])
        self.assertTrue(parked.ended, "nothing is left to run once the only ticket is parked")

    def test_rerun_reopens_a_failed_ticket_and_launches_a_new_attempt(self):
        fake, driven = self.conductor_over((Envelope(), None, 0), (Envelope(), None, 0), (done(), patch(), 0))
        self.until_quiet(driven)
        self.assertEqual(self.ticket()["status"], "failed")
        control(self.project, "rerun", {"ticket": 1})
        self.until_quiet(driven)
        self.assertEqual(self.payload("ticket_rerun"), {"ticket": 1, "by": "cli"})
        self.assertEqual([event["payload"]["attempt"] for event in self.events("ticket_launched")], [1, 2])
        self.assertEqual(self.ticket()["status"], "done")

    def test_feedback_autonomy_and_pacing_reach_the_next_wave(self):
        fake, driven = self.conductor_over((done(), patch(), 0))
        self.ledger.append_event("feedback", {"id": "f-1", "source": "cli"})
        control(self.project, "autonomy", {"autonomy": "autonomous"})
        control(self.project, "pacing", {"stop_at": 0.95})
        driven.wave()
        said = driven.out.getvalue()
        self.assertIn("feedback f-1", said)
        self.assertIn("autonomy is now autonomous", said)
        self.assertIn("stop_at 0.95", said)
        self.assertEqual((driven.view.autonomy, driven.view.thresholds), ("autonomous", {"stop_at": 0.95}))


def verb(project_path, *arguments):
    """One `wayline` verb in process, with `--project` and its output captured."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(arguments) + ["--project", str(project_path)])
    return code, out.getvalue(), err.getvalue()


class AnswerTest(ControlCase):
    """Criterion 4's `answer`, and criterion 1's hand-written answer that wins on reconcile."""

    def decision_ticket(self, body="\n## Question\n\nWhich greeting goes in hello.txt?\n"):
        """Ticket 2, an open decision ticket that holds ticket 1 back until it is answered."""
        fields = json.loads((EXAMPLES_DIR / "ticket" / "valid-decision.json").read_text(encoding="utf-8"))
        fields.update(id=2, title="Which greeting goes in hello.txt", status="open", blocked_by=[],
                      blocking="subgraph", human_only=True)
        tickets.write_ticket(self.ledger, fields, body)
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        one, one_body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(one, blocked_by=[2]), one_body)

    def body_of(self, identifier):
        ticket = {item["id"]: item for item in tickets.read_tickets(self.project)}[identifier]
        return (tickets.tickets_dir(self.project) / tickets.filename(ticket)).read_text(encoding="utf-8")

    def statuses(self):
        return {item["id"]: item["status"] for item in tickets.read_tickets(self.project)}

    def test_an_answer_from_the_command_line_closes_the_decision_and_releases_what_it_held(self):
        self.decision_ticket()
        code, _, err = verb(self.project, "answer", "2", "the plain greeting")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.payload("decision"), {"ticket": 2, "answer": "the plain greeting", "decided_by": "human",
                                                    "rationale": None, "confidence": None})
        self.assertIn("## Answer\n\nthe plain greeting", self.body_of(2))
        fake, driven = self.conductor_over((done(), patch(), 0))
        self.until_quiet(driven)
        self.assertEqual(self.statuses(), {1: "done", 2: "done"})
        self.assertEqual([event["payload"]["ticket"] for event in self.events("ticket_launched")], [1])

    def test_a_hand_written_answer_wins_over_the_answer_the_journal_holds(self):
        self.decision_ticket(body="\n## Question\n\nWhich greeting?\n\n## Answer\n\nthe loud greeting\n")
        self.ledger.append_event("decision", {"ticket": 2, "answer": "the plain greeting", "decided_by": "human",
                                              "rationale": None, "confidence": None}, ticket=2)
        fake, driven = self.conductor_over((done(), patch(), 0))
        self.until_quiet(driven)
        self.assertEqual([event["payload"]["answer"] for event in self.events("decision")],
                         ["the plain greeting", "the loud greeting"])
        self.assertEqual(self.payload("decision")["decided_by"], "human")
        self.assertEqual(self.statuses(), {1: "done", 2: "done"})

    def test_answer_refuses_a_ticket_that_is_not_an_open_decision(self):
        code, _, err = verb(self.project, "answer", "1", "anything")
        self.assertEqual(code, 1)
        self.assertIn("decision", err)
        self.assertEqual(self.events("decision"), [])

    def test_a_rerun_decision_ticket_is_asked_again_and_takes_a_new_answer(self):
        self.decision_ticket()
        verb(self.project, "answer", "2", "the plain greeting")
        fake, driven = self.conductor_over((done(), patch(), 0))
        self.until_quiet(driven)
        control(self.project, "pause")  # the reopened decision ticket is not launched; the answer still applies
        control(self.project, "rerun", {"ticket": 2})
        driven.wave()
        self.assertEqual(self.statuses()[2], "open", "the old answer must not close the ticket again")
        self.assertEqual(len(self.events("decision")), 1)
        self.assertIn("## Superseded answer\n\nthe plain greeting", self.body_of(2))
        code, _, err = verb(self.project, "answer", "2", "the loud greeting")
        self.assertEqual(code, 0, err)
        driven.wave()
        self.assertEqual(self.statuses()[2], "done")
        self.assertEqual([event["payload"]["answer"] for event in self.events("decision")],
                         ["the plain greeting", "the loud greeting"])


class SwitchDrainTest(ControlCase):
    """Criterion 5, in decision 1's order: `switch` asks for the drain, waits for it, then moves the pointer."""

    def test_switch_drains_the_run_waits_for_it_and_only_then_moves_the_pointer(self):
        other = self.temp / "other"
        project.init_project(other)
        project.set_active(self.project)
        job = self.project / "research" / "jobs" / "j-0001.json"
        job.write_text('{"id": "j-0001", "status": "running"}\n', encoding="utf-8")
        fake = self.enterContext(worker.use_fake())
        fake.script(done(), patch=patch(), delay=600)
        driven = Conductor(self.project, out=io.StringIO())
        launched, asked, waves = threading.Event(), threading.Event(), []

        def wait(seconds):
            launched.set()     # the first wave launched ticket 1, whose worker is held
            asked.wait(60)     # until `switch` has asked for the drain
            fake.release()
            driven.settle()

        running = threading.Thread(target=lambda: waves.extend(driven.run(wait=wait, max_waves=12)), daemon=True)
        running.start()
        self.addCleanup(running.join, 60)
        self.addCleanup(fake.release)
        self.addCleanup(asked.set)
        self.assertTrue(launched.wait(60))
        seen = []

        def drain(previous):
            seen.append(project.read_active())
            asked.set()
            running.join(60)

        moved = project.switch_project(other, wait=drain)
        self.assertEqual(seen, [self.project.resolve()], "the pointer moved before the drain was done")
        self.assertEqual(project.read_active(), other.resolve())
        self.assertEqual(waves[-1].reason, "switched")
        self.assertEqual(moved["drained"]["pid"], os.getpid())
        self.assertEqual([event["payload"] for event in self.events("control")],
                         [{"command": "stop", "args": {"drain": True, "switch_to": str(other.resolve())}, "by": "cli"}])
        names = [event["event"] for event in self.events()]
        self.assertLess(names.index("run_ended"), names.index("switched"))
        self.assertEqual(self.payload("run_ended"), {"reason": "switched"})
        self.assertEqual(self.ticket()["status"], "done", "the worker running at the switch was waited for")
        self.assertEqual(job.read_text(encoding="utf-8"), '{"id": "j-0001", "status": "running"}\n')


class LedgerCommitTest(ControlCase):
    """A wave commits the ledger without the session directory of a worker that is still writing into it."""

    def test_a_running_worker_s_session_directory_waits_for_the_wave_that_carries_it(self):
        fake, driven = self.conductor_over((done(), patch(), 600))
        launching = driven.wave()
        session = "research/sessions/1/1/"
        first = self.git("show", "--name-only", "--format=", launching.ledger_commit).split("\n")
        self.assertIn("research/journal.jsonl", first)
        self.assertEqual([path for path in first if path.startswith(session)], [],
                         "the ledger commit took files a running worker's session was still writing")
        fake.release()
        driven.settle()
        carrying = driven.wave()
        later = self.git("show", "--name-only", "--format=", carrying.ledger_commit).split("\n")
        self.assertIn(session + "prompt.md", later)
        self.assertIn(session + "result.json", later)


class SlotsWhileRunningTest(ControlCase):
    """`max_parallel_workers` counts the workers still running from earlier waves, not only this wave's."""

    def test_a_wave_launches_only_into_the_slots_the_running_workers_leave_free(self):
        for identifier in (2, 3, 4):
            self.another_ticket(identifier)
        fake = self.enterContext(worker.use_fake())
        fake.script(done(), patch=patch(), delay=600, ticket=1)
        for identifier in (2, 3, 4):
            name = "f%d.txt" % identifier
            fake.script(done(ticket_id=identifier, outputs_written=[name]),
                        patch=patch({name: "x\n"}, "ticket %d" % identifier), delay=600, ticket=identifier)
        driven = Conductor(self.project, out=io.StringIO())
        driven.policy = dict(driven.policy, max_parallel_workers=2)
        self.addCleanup(driven.settle, 30)
        self.addCleanup(fake.release)
        first = driven.wave()
        fake.release(ticket=1)
        driven.flight[1].thread.join(10)  # ticket 1's worker has returned, and ticket 2's is still running
        second = driven.wave()
        self.assertEqual((first.launched, second.done, second.launched), ([1, 2], [1], [3]))


class VerbTest(ControlCase):
    """Criterion 4's verbs: each appends the event the conductor applies."""

    def test_pause_resume_cancel_and_rerun_journal_their_control_events(self):
        for arguments in (["pause"], ["resume"], ["cancel", "1"], ["rerun", "1"]):
            code, _, err = verb(self.project, *arguments)
            self.assertEqual(code, 0, err)
        self.assertEqual([(event["payload"]["command"], event["payload"]["args"], event["payload"]["by"], event["ticket"])
                          for event in self.events("control")],
                         [("pause", {}, "cli", None), ("resume", {}, "cli", None),
                          ("cancel", {"ticket": 1}, "cli", 1), ("rerun", {"ticket": 1}, "cli", 1)])

    def test_stop_with_no_conductor_running_is_journaled_all_the_same_and_says_so(self):
        code, out, err = verb(self.project, "stop", "--drain")
        self.assertEqual(code, 0, err)
        self.assertIn("no conductor is running", out)
        self.assertEqual(self.payload("control"), {"command": "stop", "args": {"drain": True}, "by": "cli"})

    def test_stop_reaches_the_conductor_that_holds_the_heartbeat(self):
        holder = Ledger(self.project).heartbeat().acquire()
        self.addCleanup(holder.release)
        holder.write(**HOLDER)
        code, out, err = verb(self.project, "stop", "--drain")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.payload("control"), {"command": "stop", "args": {"drain": True}, "by": "cli"})
        self.assertIn("4242", out)

    def test_cancel_refuses_a_ticket_the_project_does_not_have(self):
        code, _, err = verb(self.project, "cancel", "9")
        self.assertEqual(code, 1)
        self.assertIn("9", err)
        self.assertEqual(self.events("control"), [])

    def test_run_resume_says_in_run_started_that_it_resumes(self):
        with worker.use_fake() as fake:
            fake.script(done(), patch=patch())
            code, _, err = run_verb(["--resume", "--project", str(self.project)])
        self.assertEqual(code, 0, err)
        self.assertIs(self.payload("run_started")["resume"], True)


KILL_RESUME = FIXTURES_DIR / "conductor" / "m1-kill-resume"


class RecordedKillTest(unittest.TestCase):
    """Criterion 6: the recorded journal of a run killed mid-wave replays to the view the kill left.

    `fixtures/conductor/record.py` made the recording: the five-ticket project, killed with SIGKILL
    while the second wave's workers (tickets 3 and 4) were running.
    """

    @classmethod
    def setUpClass(cls):
        cls.events, _ = Ledger(KILL_RESUME).read_events()
        cls.view = replay.replay(cls.events)

    def test_the_recording_is_a_run_that_started_and_never_ended(self):
        names = [event["event"] for event in self.events]
        self.assertEqual(names[0], "run_started")
        self.assertNotIn("run_ended", names)

    def test_replay_rebuilds_the_statuses_and_the_attempts_the_kill_left(self):
        self.assertEqual({identifier: ticket.status for identifier, ticket in self.view.tickets.items()},
                         {1: "done", 2: "done", 3: "running", 4: "running"})
        self.assertEqual({identifier: ticket.attempt for identifier, ticket in self.view.tickets.items()},
                         {1: 1, 2: 1, 3: 1, 4: 1})

    def test_the_two_interrupted_workers_are_owed_their_results_by_session_and_pid(self):
        self.assertEqual([(identifier, attempt.owed) for identifier, attempt in self.view.in_flight()],
                         [(3, "session"), (4, "session")])
        for identifier, attempt in self.view.in_flight():
            with self.subTest(ticket=identifier):
                run = KILL_RESUME / "research" / "sessions" / str(identifier) / "1"
                self.assertEqual(attempt.session_id, worker.StreamTail(run / "stream.jsonl").read().session_id)
                self.assertEqual(attempt.pid, int((run / "pid").read_text(encoding="utf-8")))

    def test_the_standing_state_is_rebuilt_and_the_heartbeat_names_the_killed_run(self):
        self.assertEqual((self.view.pause, self.view.paused_by_owner, self.view.stop), (None, False, None))
        self.assertEqual((self.view.pacing["action"], self.view.stall), ("normal", 0))
        self.assertEqual(read_heartbeat(KILL_RESUME)["pid"], self.view.run["pid"])

    def test_replaying_the_recording_twice_yields_the_same_view(self):
        self.assertEqual(replay.replay(self.events), self.view)

    def test_the_ticket_files_it_recorded_say_what_the_journal_says(self):
        self.assertEqual({ticket["id"]: ticket["status"] for ticket in tickets.read_tickets(KILL_RESUME)},
                         {1: "done", 2: "done", 3: "running", 4: "running", 5: "open"})


class RecordedKillResumeTest(ProjectTestCase):
    """Testing Decisions, seam 4: the recorded journal is the input, and what the next waves append is asserted."""

    def test_the_next_run_resumes_both_interrupted_workers_and_ends_with_an_empty_frontier(self):
        target = self.temp / "m1-kill-resume"
        shutil.copytree(KILL_RESUME, target)
        project.init_project(target)
        recorded, _ = Ledger(KILL_RESUME).read_events()
        sessions = {identifier: attempt.session_id for identifier, attempt in replay.replay(recorded).in_flight()}
        with worker.use_fake() as fake:
            fake.load(FIVE_TICKETS / "fake-worker.json")
            driven = Conductor(target, out=io.StringIO())
            driven.run(resume=True, wait=lambda seconds: driven.settle(), max_waves=12)
            calls = [(call.kind, call.request.env["WAYLINE_TICKET"], call.session_id) for call in fake.calls]
        appended = Ledger(target).read_events()[0][len(recorded):]
        self.assertEqual((appended[0]["event"], appended[0]["payload"]["resume"]), ("run_started", True))
        self.assertEqual([(event["ticket"], event["payload"]["reason"], event["payload"]["session_id"])
                          for event in appended if event["event"] == "ticket_resumed"],
                         [(3, "worker_died", sessions[3]), (4, "worker_died", sessions[4])])
        self.assertEqual(calls, [("resume", "3", sessions[3]), ("resume", "4", sessions[4]), ("launch", "5", None)])
        self.assertEqual((appended[-1]["event"], appended[-1]["payload"]), ("run_ended", {"reason": "frontier_empty"}))
        self.assertEqual([ticket["status"] for ticket in tickets.read_tickets(target)], ["done"] * 5)
        self.assertEqual((target / "notes" / "alpha.md").read_text(encoding="utf-8"), "alpha\nalpha extended\n")
        self.assertEqual((target / "reports" / "beta.md").read_text(encoding="utf-8"), "beta\nbeta extended\n")


class KillResumeTest(ProjectTestCase):
    """Criterion 6: a conductor process killed with SIGKILL during a slow worker is resumed to the end."""

    def wayline(self, *arguments, **options):
        return [sys.executable, "-m", "wayline", *arguments]

    def test_a_conductor_killed_during_a_slow_worker_resumes_to_a_clean_empty_frontier(self):
        target = self.temp / "five-tickets"
        shutil.copytree(FIVE_TICKETS, target)
        harness = json.loads((target / "harness.json").read_text(encoding="utf-8"))
        harness["policy"] = {"poll_seconds": 1}
        (target / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        entries = json.loads((FIVE_TICKETS / "fake-worker.json").read_text(encoding="utf-8"))
        (self.temp / "slow.json").write_text(json.dumps([dict(entry, delay=600) if entry["ticket"] == "2" else entry
                                                         for entry in entries]), encoding="utf-8")
        environment = dict(os.environ, WAYLINE_HOME=str(self.wayline_home), WAYLINE_LAUNCHER="fake")
        subprocess.run(self.wayline("init", str(target)), cwd=HARNESS_ROOT, env=environment, check=True,
                       capture_output=True, timeout=120)

        environment["WAYLINE_FAKE_SCRIPT"] = str(self.temp / "slow.json")
        running = subprocess.Popen(self.wayline("run", "--project", str(target)), cwd=HARNESS_ROOT, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(lambda: running.poll() is None and (running.kill(), running.wait()))
        for line in running.stdout:  # the conductor's own lines, read as they come: no sleep decides when to kill
            if line.strip() == "ticket 5 done":
                break
        else:
            self.fail("the conductor ended before the fast branch was done")
        os.kill(running.pid, signal.SIGKILL)
        running.wait(60)
        running.stdout.close()

        killed = replay.replay(Ledger(target).read_events()[0])
        self.assertIsNone(killed.run["ended"])
        self.assertEqual({identifier: ticket.status for identifier, ticket in killed.tickets.items()},
                         {1: "done", 2: "running", 3: "done", 5: "done"})

        environment["WAYLINE_FAKE_SCRIPT"] = str(FIVE_TICKETS / "fake-worker.json")
        resumed = subprocess.run(self.wayline("run", "--resume", "--project", str(target)), cwd=HARNESS_ROOT,
                                 env=environment, capture_output=True, text=True, timeout=300)
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        events, _ = Ledger(target).read_events()
        self.assertEqual((events[-1]["event"], events[-1]["payload"]), ("run_ended", {"reason": "frontier_empty"}))
        self.assertEqual([(event["ticket"], event["payload"]["reason"]) for event in events if event["event"] == "ticket_resumed"],
                         [(2, "worker_died")])
        self.assertEqual([ticket["status"] for ticket in tickets.read_tickets(target)], ["done"] * 5)
        self.assertEqual(list((target / ".worktrees").iterdir()), [])
        self.assertEqual((target / "reports" / "beta.md").read_text(encoding="utf-8"), "beta\nbeta extended\n")
        self.assertIsNone(conductor_holder(target))


if __name__ == "__main__":
    unittest.main()
