"""The journal replayed into the conductor's working view (Implementation Decisions 2 and 5).

Testing Decisions seam 4: the conductor is tested by replaying a journal, and what is asserted is
the reconstructed view. These tests feed `replay` journal records built by the ledger's own
`make_event`, so a record the ledger would refuse cannot sneak in, and the recorded journal of
`fixtures/ledger/`.
"""

import unittest

from tests.paths import LEDGER_FIXTURE
from wayline import replay
from wayline.ledger import Ledger, make_event


def event(name, payload=None, ticket=None, session_id=None, job=None, at=0):
    """One journal record, validated as the ledger validates it, `at` seconds into the run."""
    minutes, seconds = divmod(at, 60)
    return make_event(name, payload, ticket=ticket, session_id=session_id, job=job,
                      ts="2026-09-12T10:%02d:%02d.000Z" % (minutes, seconds))


def launched(ticket, attempt=1, pid=4000, at=0):
    return event("ticket_launched", {
        "ticket": ticket, "attempt": attempt, "role": "coder", "model": "sonnet", "effort": "low",
        "skills": [], "worktree": "/p/.worktrees/%d" % ticket, "pid": pid, "context_chars": 10,
        "prompt_sha256": "0" * 64,
    }, ticket=ticket, at=at)


class StatusTest(unittest.TestCase):
    """What each ticket's events leave it at, and how many attempts it has had."""

    def test_statuses_and_attempts_follow_the_ticket_events(self):
        view = replay.replay([
            launched(1, pid=4001),
            event("ticket_done", {"ticket": 1}, ticket=1),
            launched(2, pid=4002),
            event("ticket_failed", {"ticket": 2, "attempt": 1, "reason": "no", "next": "resume"}, ticket=2),
            launched(2, attempt=2, pid=4003),
            launched(3, pid=4004),
            event("ticket_blocked", {"ticket": 3, "path": "src/x.py"}, ticket=3),
            launched(4, pid=4005),
            event("ticket_needs_human", {"ticket": 4, "question": "which?"}, ticket=4),
            event("ticket_done", {"ticket": 5}, ticket=5),
            event("ticket_accepted", {"ticket": 5}, ticket=5),
        ])
        self.assertEqual({identifier: ticket.status for identifier, ticket in view.tickets.items()},
                         {1: "done", 2: "running", 3: "blocked", 4: "needs_human", 5: "accepted"})
        self.assertEqual({identifier: ticket.attempt for identifier, ticket in view.tickets.items()},
                         {1: 1, 2: 2, 3: 1, 4: 1, 5: 0})

    def test_the_recorded_ledger_journal_replays_to_the_statuses_it_left(self):
        events, _ = Ledger(LEDGER_FIXTURE).read_events()
        view = replay.replay(events)
        self.assertEqual({identifier: ticket.status for identifier, ticket in view.tickets.items()},
                         {1: "accepted", 2: "done", 3: "running", 6: "failed", 8: "needs_human"})
        self.assertEqual(view.tickets[6].attempt, 2)


def session(ticket, session_id, attempt=1, at=0):
    return event("ticket_session", {"ticket": ticket, "attempt": attempt, "session_id": session_id,
                                    "model": "claude-sonnet-5"}, ticket=ticket, session_id=session_id, at=at)


def result(ticket, status="done", valid=True, attempt=1, session_id=None, at=0):
    return event("ticket_result", {"ticket": ticket, "attempt": attempt, "session_id": session_id,
                                   "status": status, "turns": 3, "duration_ms": 100, "usage": {},
                                   "permission_denials": [], "valid": valid},
                 ticket=ticket, session_id=session_id, at=at)


def resumed(ticket, reason, session_id=None, attempt=1, at=0):
    return event("ticket_resumed", {"ticket": ticket, "attempt": attempt, "session_id": session_id,
                                    "reason": reason}, ticket=ticket, session_id=session_id, at=at)


class SessionTest(unittest.TestCase):
    """Which attempts a restarted conductor still owes something, with the session and pid to find it by."""

    def setUp(self):
        self.view = replay.replay([
            # 1: carried to the end.
            launched(1, pid=4001), session(1, "s-1"), result(1, session_id="s-1"),
            event("ticket_done", {"ticket": 1}, ticket=1),
            # 2: its session started and nothing came back yet.
            launched(2, pid=4002), session(2, "s-2"),
            # 3: launched, and killed before its session said who it was.
            launched(3, pid=4003),
            # 4: its result came back and its outcome was never carried.
            launched(4, pid=4004), session(4, "s-4"), result(4, session_id="s-4"),
            # 5: its worker left jobs running.
            launched(5, pid=4005), session(5, "s-5"), result(5, status="running", session_id="s-5"),
            # 6: an invalid result, and the resume that answers it still running.
            launched(6, pid=4006), session(6, "s-6"), result(6, valid=False, session_id="s-6"),
            resumed(6, "invalid_result", "s-6"),
            # 7: a live worker a restarted conductor picked up again.
            launched(7, pid=4007), session(7, "s-7"), resumed(7, "readopted", "s-7"),
            # 8: dead before its session started, and relaunched in the same attempt.
            launched(8, pid=4008), resumed(8, "worker_died"), launched(8, pid=4108),
            # 9: dead after its session started, and resumed by session id.
            launched(9, pid=4009), session(9, "s-9"), resumed(9, "worker_died", "s-9"),
        ])

    def attempt(self, ticket):
        return self.view.tickets[ticket].attempts[self.view.tickets[ticket].attempt]

    def test_each_attempt_keeps_the_session_id_and_the_pid_it_was_launched_with(self):
        self.assertEqual({ticket: (self.attempt(ticket).session_id, self.attempt(ticket).pid) for ticket in range(1, 10)}, {
            1: ("s-1", 4001), 2: ("s-2", 4002), 3: (None, 4003), 4: ("s-4", 4004), 5: ("s-5", 4005),
            6: ("s-6", 4006), 7: ("s-7", 4007), 8: (None, 4108), 9: ("s-9", 4009),
        })

    def test_the_state_says_what_a_restarted_conductor_owes_each_attempt(self):
        self.assertEqual({ticket: self.attempt(ticket).state for ticket in range(1, 10)}, {
            1: "ended", 2: "session", 3: "session", 4: "result", 5: "jobs",
            6: "session", 7: "session", 8: "session", 9: "session",
        })
        self.assertEqual([ticket for ticket, _ in self.view.in_flight()], [2, 3, 4, 6, 7, 8, 9])

    def test_a_resume_that_starts_a_process_is_a_session_and_a_re_adoption_starts_none(self):
        self.assertEqual([(item.kind, item.reason) for item in self.attempt(6).sessions],
                         [("launch", None), ("resume", "invalid_result")])
        self.assertEqual([(item.kind, item.reason) for item in self.attempt(7).sessions], [("launch", None)])
        self.assertEqual([(item.kind, item.reason) for item in self.attempt(9).sessions],
                         [("launch", None), ("resume", "worker_died")])
        self.assertEqual([(item.kind, item.pid) for item in self.attempt(8).sessions], [("launch", 4108)])

    def test_the_stage_is_the_gate_the_running_session_answers_and_each_gate_resumes_once(self):
        self.assertEqual((self.attempt(6).stage, self.attempt(6).spent), ("invalid_result", {"invalid_result"}))
        self.assertEqual((self.attempt(9).stage, self.attempt(9).spent), ("launch", set()))
        self.assertEqual((self.attempt(7).stage, self.attempt(7).spent), ("launch", set()))


def run_started(resume=False, autonomy="checkpoints", pid=31415, at=0):
    return event("run_started", {"resume": resume, "harness_tag": "v0.0.0", "autonomy": autonomy,
                                 "radius": "moderate", "pid": pid}, at=at)


def control(command, args=None, by="cli", ticket=None, at=0):
    return event("control", {"command": command, "args": args or {}, "by": by}, ticket=ticket, at=at)


def wave(number, outcomes, progressed, at=0):
    return event("wave", {"number": number, "outcomes": outcomes, "progressed": progressed}, at=at)


class StandingStateTest(unittest.TestCase):
    """What holds for the project rather than for one ticket: the windows, the owner's say, the stall."""

    def test_the_window_pause_lasts_until_unpaused_and_outlives_a_restart(self):
        paused = event("paused", {"resets_at": "2026-09-12T13:00:00Z", "window": "five_hour", "utilization": 0.93})
        view = replay.replay([run_started(), paused, run_started(resume=True, pid=2)])
        self.assertEqual(view.pause, {"resets_at": "2026-09-12T13:00:00Z", "window": "five_hour", "utilization": 0.93})
        self.assertIsNone(view.apply(event("unpaused")).pause)

    def test_pacing_is_the_latest_reading(self):
        view = replay.replay([
            event("pacing", {"five_hour": 0.5, "seven_day": 0.2, "action": "normal"}),
            event("pacing", {"five_hour": 0.85, "seven_day": 0.3, "action": "cheap_only"}),
        ])
        self.assertEqual(view.pacing, {"five_hour": 0.85, "seven_day": 0.3, "action": "cheap_only"})
        self.assertEqual(replay.replay([]).pacing, {"five_hour": None, "seven_day": None, "action": "normal"})

    def test_the_owner_pause_holds_until_the_owner_resumes_even_across_a_restart(self):
        view = replay.replay([run_started(), control("pause"), run_started(resume=True, pid=2)])
        self.assertTrue(view.paused_by_owner)
        self.assertFalse(view.apply(control("resume")).paused_by_owner)

    def test_autonomy_and_the_pacing_thresholds_follow_the_control_events(self):
        view = replay.replay([
            run_started(autonomy="checkpoints"),
            control("autonomy", {"autonomy": "autonomous"}),
            control("pacing", {"stop_at": 0.95}),
            control("pacing", {"cheap_at": 0.7}),
        ])
        self.assertEqual(view.autonomy, "autonomous")
        self.assertEqual(view.thresholds, {"stop_at": 0.95, "cheap_at": 0.7})

    def test_the_stall_counter_counts_settling_waves_that_made_no_progress(self):
        """Decision 5: a settling wave processed an outcome; one without progress counts, progress resets."""
        view = replay.replay([run_started(), wave(1, 1, False), wave(2, 2, False), wave(3, 0, False)])
        self.assertEqual(view.stall, 2)
        self.assertEqual(view.apply(wave(4, 1, True)).stall, 0)
        self.assertEqual(view.apply(wave(5, 1, False)).stall, 1)
        self.assertEqual(view.apply(event("stall", {"waves": 1, "action": "replan"})).stall, 0)
        view.apply(wave(6, 1, False))
        self.assertEqual(view.apply(run_started(resume=True, pid=2)).stall, 1, "a resumed run keeps its count")
        self.assertEqual(view.apply(run_started(resume=False, pid=3)).stall, 0, "a new run starts from zero")


class CommandTest(unittest.TestCase):
    """What other processes asked for, held until the event that carries it out."""

    def test_a_stop_holds_for_the_run_it_was_given_to_and_a_new_run_supersedes_it(self):
        view = replay.replay([run_started(), control("stop", {"drain": True, "switch_to": "/other"})])
        self.assertEqual(view.stop, {"drain": True, "switch_to": "/other", "by": "cli"})
        self.assertEqual(view.apply(control("stop", by="dashboard")).stop,
                         {"drain": False, "switch_to": "/other", "by": "dashboard"})
        self.assertFalse(view.apply(control("stop", {"drain": True})).stop["drain"], "a drain never softens a stop")
        self.assertIsNone(view.apply(event("run_ended", {"reason": "stopped"})).stop)
        self.assertIsNone(replay.replay([run_started(), control("stop"), run_started(resume=True, pid=2)]).stop)

    def test_cancel_and_rerun_wait_for_the_event_that_carries_them_out_even_across_a_restart(self):
        view = replay.replay([control("cancel", {"ticket": 3}, ticket=3), control("rerun", {"ticket": 4}, by="dashboard", ticket=4)])
        self.assertEqual((view.cancels, view.reruns), ({3: "cli"}, {4: "dashboard"}))
        view.apply(event("ticket_cancelled", {"ticket": 3, "by": "cli"}, ticket=3))
        view.apply(run_started(resume=True))
        self.assertEqual((view.cancels, view.reruns), ({}, {4: "dashboard"}))
        self.assertEqual(view.apply(event("ticket_rerun", {"ticket": 4, "by": "dashboard"}, ticket=4)).reruns, {})

    def test_an_answer_stands_until_its_ticket_is_rerun(self):
        view = replay.replay([event("decision", {"ticket": 10, "answer": "the second split", "decided_by": "human",
                                                 "rationale": None, "confidence": None}, ticket=10)])
        self.assertEqual(view.answers, {10: {"answer": "the second split", "decided_by": "human",
                                             "rationale": None, "confidence": None}})
        self.assertEqual(view.apply(event("ticket_rerun", {"ticket": 10, "by": "cli"}, ticket=10)).answers, {})

    def test_feedback_is_kept_in_order_and_a_switch_away_holds_for_its_run(self):
        view = replay.replay([
            run_started(),
            event("feedback", {"id": "f-1", "source": "cli"}),
            event("feedback", {"id": "f-2", "source": "dashboard"}),
            event("switched", {"from": "/a", "to": "/b"}),
        ])
        self.assertEqual(view.feedback, [{"id": "f-1", "source": "cli"}, {"id": "f-2", "source": "dashboard"}])
        self.assertEqual(view.switched, {"from": "/a", "to": "/b"})
        self.assertIsNone(view.apply(run_started(resume=True, pid=2)).switched)

    def test_the_recorded_ledger_journal_rebuilds_jobs_sessions_pids_and_the_run(self):
        events, _ = Ledger(LEDGER_FIXTURE).read_events()
        view = replay.replay(events)
        self.assertEqual(view.jobs, {
            "j-0001": {"ticket": 3, "status": "running", "attempt": 1, "exit_code": None},
            "j-0002": {"ticket": 3, "status": "exited", "attempt": None, "exit_code": 0},
        })
        self.assertEqual({identifier: ticket.latest.pid for identifier, ticket in view.tickets.items() if ticket.latest},
                         {1: 31416, 2: 31490, 3: 31600, 6: 31560})
        self.assertEqual(view.tickets[1].latest.session_id, "1f3c9a20-0000-4000-8000-000000000001")
        self.assertEqual((view.findings, view.integrated), ({"f-0001"}, {1: "4c2f9a1"}))
        self.assertEqual(view.verdicts, {1: [{"verdict_type": "ticket_quality", "pass": True}]})
        self.assertEqual(view.run, {"pid": 31415, "resume": False, "ts": "2026-09-11T11:00:00.000Z", "ended": None})
        self.assertIsNone(view.pause)
        self.assertEqual(view.pacing, {"five_hour": 0.41, "seven_day": 0.52, "action": "normal"})


class IdempotenceTest(unittest.TestCase):
    """Decision 5: replaying twice yields the same view, and the view a running conductor keeps by
    tailing the journal is the view a restart rebuilds from byte zero."""

    def journal(self):
        events, _ = Ledger(LEDGER_FIXTURE).read_events()
        return events + [
            run_started(resume=True, pid=2, at=10),
            launched(20, pid=5020, at=11), session(20, "s-20", at=12),
            result(20, valid=False, session_id="s-20", at=13), resumed(20, "invalid_result", "s-20", at=14),
            launched(21, pid=5021, at=15), resumed(21, "readopted", at=16),
            control("pause", at=17), control("cancel", {"ticket": 6}, ticket=6, at=18),
            wave(1, 1, False, at=19), control("stop", {"drain": True, "switch_to": "/b"}, at=20),
            event("switched", {"from": "/a", "to": "/b"}, at=21),
            event("decision", {"ticket": 10, "answer": "split b", "decided_by": "human",
                               "rationale": None, "confidence": None}, ticket=10, at=22),
            event("feedback", {"id": "f-9", "source": "file"}, at=23),
        ]

    def test_replaying_the_same_journal_twice_yields_the_same_view(self):
        events = self.journal()
        untouched = [dict(item, payload=dict(item["payload"])) for item in events]
        first, second = replay.replay(events), replay.replay(events)
        self.assertEqual(first, second)
        self.assertEqual(events, untouched, "replay changed the records it read")
        self.assertEqual(first.stop, {"drain": True, "switch_to": "/b", "by": "cli"})

    def test_a_view_kept_by_tailing_the_journal_is_the_view_a_restart_rebuilds(self):
        events = self.journal()
        whole = replay.replay(events)
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                self.assertEqual(replay.replay(events[cut:], replay.replay(events[:cut])), whole)


if __name__ == "__main__":
    unittest.main()
