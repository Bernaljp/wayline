"""The journal replayed into the conductor's working view (Implementation Decisions 2 and 5).

The journal is the bus: every process appends its events, and the conductor rebuilds what it
knows by folding them in order. Resume is the same fold from byte zero, so the view is a pure
function of the events: nothing here reads a file, the clock, or the machine, and replaying the
same journal twice yields the same view.

A ticket's attempts are kept session by session, because that is what a restarted conductor has
to act on. An attempt runs in one process at a time: its launch, or a resume of it. A session
whose `ticket_result` never arrived is still owed its result (the worker may be alive, or may
have died with or without a session id to resume), and a result whose outcome no terminal event
closed is still owed its carrying.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from wayline.ledger import (
    CONTROL, DECISION, FEEDBACK, FINDING, INTEGRATED, JOB_CANCELLED, JOB_FAILED, JOB_FINISHED,
    JOB_LAUNCHED, JOB_RETRIED, JOB_WAITING, PACING, PAUSED, RUN_ENDED, RUN_STARTED, STALL, SWITCHED,
    TICKET_ACCEPTED, TICKET_BLOCKED, TICKET_CANCELLED, TICKET_CREATED, TICKET_DONE, TICKET_FAILED,
    TICKET_LAUNCHED, TICKET_NEEDS_HUMAN, TICKET_RERUN, TICKET_RESULT, TICKET_RESUMED, TICKET_SESSION,
    UNPAUSED, VERDICT, WAVE, PROGRESS, DISCARDED, DIFFICULTY_RAISED, OBJECTIVE,
)
# The model a `paused` and an `unpaused` name for the hold on Fable's weekly window, the fallback consents a `control` may set,
# and the window a ticket's origin names when it is the ask of decision 15.
from wayline.pacing import CONSENTS, FABLE, ask_window, epoch

# The ladder consent of decision 16 (`project.LADDER_CONSENTS`, named here so replay keeps importing no project).
LADDER_CONSENTS = ("auto", "ask")

# The origin of the decision ticket a rung opens when the subscription refuses its model (decision 16, ticket 63).
# It names the rung and the attempt that met the refusal: a result carried twice opens one ticket, and a rung
# refused again after its ask was answered opens another, so `held_rungs` can be rebuilt from the journal alone.
_NOT_SERVED_ORIGIN = "not served: rung %d, ticket %d attempt %d"
_NOT_SERVED_RE = re.compile(r"^not served: rung (\d+)\b")

__all__ = [
    "STATUS_AFTER", "GATES", "READOPTED", "WORKER_DIED", "SESSION", "RESULT", "JOBS", "ENDS_ATTEMPT",
    "JOB_STATUS_AFTER", "Session", "Attempt", "TicketView", "View", "replay",
    "not_served_origin", "origin_rung",
]

# The status each ticket event leaves its ticket at (the transitions of Implementation Decisions 2).
STATUS_AFTER = {
    TICKET_CREATED: "open",
    TICKET_LAUNCHED: "running",
    TICKET_RESUMED: "running",
    TICKET_DONE: "done",
    TICKET_ACCEPTED: "accepted",
    TICKET_FAILED: "failed",
    TICKET_BLOCKED: "blocked",
    TICKET_NEEDS_HUMAN: "needs_human",
    TICKET_CANCELLED: "parked",
    TICKET_RERUN: "open",
}

# The `ticket_resumed` reasons that spend a gate's one resume (BRIEF 9.1). The resumed session
# answers that gate, which is the attempt's stage until its result is carried.
GATES = ("invalid_result", "acceptance_failed", "timeout")

# The `ticket_resumed` reasons a restart journals: a worker picked up again without a new process
# (its pid is still that session's worker, or its stream already holds its result), and a worker
# that died without its result, resumed by its session id or, with none, relaunched.
READOPTED = "readopted"
WORKER_DIED = "worker_died"

# What an attempt still owes a conductor: its session's result, the carrying of that result, or
# the jobs a `running` result left behind.
SESSION, RESULT, JOBS = "session", "result", "jobs"

# The events after which an attempt is owed nothing more.
ENDS_ATTEMPT = (TICKET_DONE, TICKET_FAILED, TICKET_BLOCKED, TICKET_NEEDS_HUMAN, TICKET_CANCELLED, TICKET_RERUN)

# What each job event says of its job, as far as the journal can tell (decision 6's poller reads the rest).
JOB_STATUS_AFTER = {
    JOB_LAUNCHED: "running",
    JOB_RETRIED: "running",
    JOB_FINISHED: "exited",
    JOB_FAILED: "failed",
    JOB_CANCELLED: "cancelled",
    JOB_WAITING: "pending",
}


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class Session:
    """One process an attempt ran in: its launch, or one resume that started a process.

    `ts` is when the journal named it, which is how the conductor tells the session directory of
    a resume (`resume-<k>/`, whose `env.json` records when the process started) from an earlier one.
    """

    kind: str
    reason: Optional[str] = None
    pid: Optional[int] = None
    ts: Optional[str] = None
    result: Optional[dict] = None


@dataclass
class Attempt:
    """One attempt at a ticket: what it was launched with, its sessions, and what it is still owed."""

    number: int
    pid: Optional[int] = None
    session_id: Optional[str] = None
    role: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    worktree: Optional[str] = None
    # `fable` when the latest session was launched on Opus because Fable work fell back (decision 15), which the
    # difficulty adjustment of decision 5 never counts; None otherwise.
    fallback_from: Optional[str] = None
    # The effective difficulty the attempt was launched at, which the difficulty adjustment counts failures by (ticket 38).
    difficulty: Optional[int] = None
    # The index of the rung it ran on (decision 16); None in a journal written before the rung ladder.
    rung: Optional[int] = None
    # The model its session actually ran on, when the result said another than the rung's (decision 16); None otherwise.
    model_ran: Optional[str] = None
    sessions: list = field(default_factory=list)
    stage: str = "launch"
    spent: set = field(default_factory=set)
    # Whether `integrated` named this attempt's branch: a `running` result owes its jobs only after it.
    integrated: bool = False
    ended: Optional[str] = None

    @property
    def owed(self):
        """What a conductor still owes this attempt: `SESSION`, `RESULT`, `JOBS`, or None once it ended."""
        if self.ended:
            return None
        latest = self.sessions[-1] if self.sessions else None
        if latest is None or latest.result is None:
            return SESSION
        if latest.result.get("status") == "running" and latest.result.get("valid"):
            # A `running` result is integrated before its jobs launch (ticket 19): until then it is still carried.
            return JOBS if self.integrated else RESULT
        return RESULT


@dataclass
class TicketView:
    """One ticket as the journal tells it: its status and its attempts, by number."""

    id: int
    status: Optional[str] = None
    attempts: dict = field(default_factory=dict)
    # The `next` of every `ticket_failed` since the ticket was last rerun: the steps of the escalation chain it was sent to
    # (ticket 38). A step is `resume`, `tier_up`, `split`, or `needs_human`, never a rung of the rung ladder (decision 16).
    steps: list = field(default_factory=list)
    # The `reason` of the last `ticket_failed`: the failure output the chain's resume is given.
    failure: Optional[str] = None
    # One rung above the rung the last attempt sent to `tier_up` ran on: the rung its next attempt starts from
    # (decision 16). None while no tier up was journaled, or while the journal is older than the rung ladder and
    # its launches carry no `rung`, which the conductor counts by tier ups instead.
    rung_floor: Optional[int] = None

    @property
    def step(self):
        """The escalation step a failed ticket waits on: the `next` of its last `ticket_failed`; None unless the ticket is `failed`."""
        return self.steps[-1] if self.status == "failed" and self.steps else None

    def taken(self, step):
        """How many times the chain sent this ticket to `step` since it was last rerun."""
        return self.steps.count(step)

    @property
    def attempt(self):
        """The attempt counter: the highest attempt launched, 0 before the first."""
        return max(self.attempts, default=0)

    @property
    def latest(self):
        return self.attempts.get(self.attempt)

    def _named(self, payload):
        """The attempt an event names, or the latest when it names none."""
        number = _int(payload.get("attempt"))
        return self.latest if number is None else self.attempts.get(number)

    def launched(self, payload, ts):
        number = _int(payload.get("attempt"))
        if number is None:
            return
        attempt = self.attempts.get(number)
        relaunched = attempt is not None and not attempt.ended
        if not relaunched:
            attempt = self.attempts[number] = Attempt(number)
        pid = _int(payload.get("pid"))
        # A launch into an attempt that already ran is the relaunch of a worker that died before
        # its session started: it replaces that session rather than following it. A relaunch that
        # fell back to Opus (decision 15) may replace a session that ran, stopped, and answered a gate:
        # the gate it answered stays the attempt's stage.
        fallback_from = payload.get("fallback_from")
        attempt.pid, attempt.session_id = pid, None
        attempt.stage = attempt.stage if relaunched and fallback_from else "launch"
        attempt.role, attempt.model = payload.get("role"), payload.get("model")
        attempt.effort, attempt.worktree = payload.get("effort"), payload.get("worktree")
        attempt.fallback_from = fallback_from
        attempt.difficulty = _int(payload.get("difficulty"))
        attempt.rung = _int(payload.get("rung"))
        attempt.model_ran = None  # what this launch ran on is its own result's word
        attempt.sessions = [Session("launch", pid=pid, ts=ts)]

    def session(self, payload):
        attempt = self._named(payload)
        if attempt is not None and payload.get("session_id"):
            attempt.session_id = payload["session_id"]

    def result(self, payload):
        attempt = self._named(payload)
        if attempt is None or attempt.ended:
            return
        if payload.get("session_id"):
            attempt.session_id = payload["session_id"]
        if payload.get("model_ran"):
            attempt.model_ran = payload["model_ran"]
        if attempt.sessions and attempt.sessions[-1].result is None:
            attempt.sessions[-1].result = dict(payload)

    def resumed(self, payload, ts):
        attempt = self._named(payload)
        reason, session_id = payload.get("reason"), payload.get("session_id")
        if attempt is not None and attempt.ended == TICKET_FAILED and reason in GATES:
            # The escalation chain's resume takes a failed attempt up again, in the same session (ticket 38); what it
            # returns is integrated afresh, whatever its failed result was.
            attempt.ended, attempt.integrated = None, False
        if attempt is None or attempt.ended:
            return
        if session_id:
            attempt.session_id = session_id
        if reason == READOPTED or (reason == WORKER_DIED and not session_id):
            # A re-adoption starts no process, and a relaunch is the `ticket_launched` that follows.
            return
        attempt.sessions.append(Session("resume", reason=reason, ts=ts))
        if reason in GATES:
            attempt.stage = reason
            attempt.spent.add(reason)

    def end(self, name, payload):
        attempt = self._named(payload)
        # A failed verdict fails an attempt that ended `done` (decision 11), and the ladder takes it from the failure.
        if attempt is not None and (not attempt.ended or (name == TICKET_FAILED and attempt.ended == TICKET_DONE)):
            attempt.ended = name


def _pacing(payload=None):
    """The reading a `pacing` event carries: both actions, the Fable one of decision 16 beside the run's.

    A `pacing` event written before the rung ladder carries no `fable_action`, and reads as `normal`:
    what it says of Fable's weekly window is a reading, and the run paced Fable launches by it alone.
    """
    payload = payload or {}
    return {"five_hour": payload.get("five_hour"), "seven_day": payload.get("seven_day"),
            "fable": payload.get("fable"), "action": payload.get("action") or "normal",
            "fable_action": payload.get("fable_action") or "normal"}


@dataclass
class View:
    """The conductor's working view of one project, built by folding its journal in order.

    `pause` is the window pause (`paused` until `unpaused`) and `paused_by_owner` the owner's
    (`control pause` until `control resume`); both outlive a restart, because neither the usage
    window nor the owner's instruction ends with a conductor. `hold` is the hold on Fable's weekly
    window (`paused` with `model: fable` until `unpaused` with it, decision 15), which outlives a
    restart the same way; it holds only the launches on Fable, so a whole-run pause can start and
    end inside it. `model_fallback` is the fallback consent a `control model_fallback` set during
    the run that is running, None before one arrives and once the run ends: a new run starts from
    `harness.json`, which `wayline switch --fallback` writes before it journals the event, and a
    control journaled while no run is open changes only what `harness.json` already says.
    `ladder_changes` is the ladder consent of decision 16, folded the same way from a
    `control ladder_changes`. `stall` is the stall counter of
    decision 5, rebuilt from the `wave` event the conductor journals at the end of every settling
    wave: progress resets it, and so does a `stall`, after which the count starts again. Nothing
    else does, so a run started with `--resume` and one started without rebuild the same view.

    What other processes ask for is held until the event that carries it out. A `stop` belongs to
    the run that is running: `run_ended` consumes it, and a run started after it is not stopped by
    it. A `switched` is kept for its run the same way. A `cancel` or a `rerun` names a ticket and
    outlives a restart, until `ticket_cancelled` or `ticket_rerun` says it was done. An answer
    stands until its ticket is rerun.

    `asks` holds the ask of decision 15 by its ticket: the reset of the window it asks about and when it
    was opened. The reset is the one its origin names until a later `paused` moves the reset of the hold
    it asked about (a refusal that names the week's reset after one that named none): the ask moves with
    it, so its answer still holds and nobody is asked twice about one spent week. A `paused` journaled
    once that reset has passed begins another week's hold, and the ask stays with its own.

    `rung_asks` holds the decision ticket each not-served failure opened, by its ticket, and `held_rungs`
    reads back the rungs held now (decision 16): a rung whose model the subscription refused is held until
    the owner answers, because a policy naming a dead model needs an edit no conductor can make.
    """

    tickets: dict = field(default_factory=dict)
    pause: Optional[dict] = None
    hold: Optional[dict] = None
    pacing: dict = field(default_factory=_pacing)
    paused_by_owner: bool = False
    autonomy: Optional[str] = None
    model_fallback: Optional[str] = None
    ladder_changes: Optional[str] = None
    thresholds: dict = field(default_factory=dict)
    stall: int = 0
    run: Optional[dict] = None
    stop: Optional[dict] = None
    switched: Optional[dict] = None
    cancels: dict = field(default_factory=dict)
    reruns: dict = field(default_factory=dict)
    answers: dict = field(default_factory=dict)
    asks: dict = field(default_factory=dict)
    # The rungs whose model the subscription refused (decision 16, ticket 63): `{ticket: {rung, opened}}` for every
    # decision ticket a not-served failure opened, which `held_rungs` reads back as the rungs held now.
    rung_asks: dict = field(default_factory=dict)
    feedback: list = field(default_factory=list)
    jobs: dict = field(default_factory=dict)
    findings: set = field(default_factory=set)
    integrated: dict = field(default_factory=dict)
    # The tickets whose last integration added no commit of their own (`integrated` with `empty`): a diff of theirs is nothing
    # to read, so their independent read is of their result (the M5 run's scope-down writing tickets).
    integrated_empty: set = field(default_factory=set)
    verdicts: dict = field(default_factory=dict)
    # Keep-if-better (ticket 39): every evaluation's `progress` by its run id, so a restart judges no attempt twice, and
    # the `discarded` payload of each ticket whose latest attempt was not kept, whose branch and worktree stay.
    progress: dict = field(default_factory=dict)
    discarded: dict = field(default_factory=dict)
    # The difficulty adjustment of decision 5 (ticket 38), for the run that is running: every failed attempt that did not
    # fall back, `{(ticket, attempt): the difficulty it launched at}`, and the raises journaled, `{kind: {from: to}}`.
    # A `run_ended` clears both, since a raise lasts for the rest of the run.
    failures: dict = field(default_factory=dict)
    raised: dict = field(default_factory=dict)
    # When the last `stall` that asked for a replan was journaled: the replan it owes, until a re-cut is written after it
    # or its run ends (a later run starts its own count).
    replan_at: Optional[str] = None
    # Every objective's status by id, from its last `objective` event (decision 17): what the pick order's objective class
    # reads (ticket 81), so a restarted conductor orders the frontier as the journal says, objectives.json aside.
    objectives: dict = field(default_factory=dict)

    def open_objectives(self):
        """The ids of the objectives open now."""
        return {identifier for identifier, status in self.objectives.items() if status == "open"}

    def apply(self, event):
        """Fold one journal record into the view; returns the view."""
        name = event.get("event")
        payload = event.get("payload") or {}
        identifier = _int(payload.get("ticket", event.get("ticket")))
        if identifier is not None and (name in STATUS_AFTER or name in (TICKET_SESSION, TICKET_RESULT)):
            self._ticket_event(self.tickets.setdefault(identifier, TicketView(identifier)), name, payload, event.get("ts"))
        if name == TICKET_FAILED and identifier is not None and payload.get("next") != "resume":
            # An attempt has failed once its one resume is behind it: a failure the resume may still mend does not count.
            attempt = self.tickets[identifier]._named(payload)
            if attempt is not None and attempt.difficulty is not None and not attempt.fallback_from:
                self.failures[(identifier, attempt.number)] = attempt.difficulty
        if name in (TICKET_LAUNCHED, TICKET_RERUN) and identifier is not None:
            self.discarded.pop(identifier, None)  # a new attempt is judged afresh
        if name == TICKET_CREATED and identifier is not None and ask_window(payload.get("origin")) is not None:
            self.asks[identifier] = {"resets_at": ask_window(payload["origin"]), "opened": event.get("ts")}
        if name == TICKET_CREATED and identifier is not None and origin_rung(payload.get("origin")) is not None:
            self.rung_asks[identifier] = {"rung": origin_rung(payload["origin"]), "opened": event.get("ts")}
        if name == OBJECTIVE and payload.get("id"):
            self.objectives[payload["id"]] = payload.get("status")
        if name == RUN_STARTED:
            self.autonomy = payload.get("autonomy") or self.autonomy
            self.run = {"pid": payload.get("pid"), "resume": bool(payload.get("resume")),
                        "ts": event.get("ts"), "ended": None}
            self.stop = self.switched = self.model_fallback = self.ladder_changes = None
        elif name == RUN_ENDED:
            if self.run is not None:
                self.run["ended"] = payload.get("reason")
            self.stop = self.switched = self.model_fallback = self.ladder_changes = None
            self.failures, self.raised, self.replan_at = {}, {}, None
        elif name == PAUSED:
            stands = {key: payload.get(key) for key in ("resets_at", "window", "utilization")}
            if payload.get("model") == FABLE:
                self._move_asks(self.hold, stands, event.get("ts"))
                self.hold = stands
            else:
                self.pause = stands
        elif name == UNPAUSED:
            if payload.get("model") == FABLE:
                self.hold = None
            else:
                self.pause = None
        elif name == PACING:
            self.pacing = _pacing(payload)
        elif name == CONTROL:
            self._control(payload, identifier)
        elif name == WAVE:
            if (_int(payload.get("outcomes")) or 0) > 0:
                self.stall = 0 if payload.get("progressed") else self.stall + 1
        elif name == STALL:
            self.stall = 0
            if payload.get("action") == "replan":
                self.replan_at = event.get("ts")
        elif name == DIFFICULTY_RAISED and isinstance(payload.get("kind"), str):
            start, end = _int(payload.get("from")), _int(payload.get("to"))
            if start is not None and end is not None:
                self.raised.setdefault(payload["kind"], {})[start] = end
        elif name == SWITCHED:
            self.switched = {"from": payload.get("from"), "to": payload.get("to")}
        elif name == FEEDBACK:
            self.feedback.append({"id": payload.get("id"), "source": payload.get("source")})
        elif name == DECISION and identifier is not None:
            self.answers[identifier] = {key: payload.get(key) for key in ("answer", "decided_by", "rationale", "confidence")}
            # The answer is the record of a decision ticket's closing (the conductor journals nothing more), so the view
            # holds the ticket done: a later run's take-over would otherwise reopen it as the journal's word (ticket 36).
            known = self.tickets.get(identifier)
            if known is not None and known.status in ("open", "blocked", "needs_human"):
                known.status = "done"
        elif name == TICKET_CANCELLED and identifier is not None:
            self.cancels.pop(identifier, None)
        elif name == TICKET_RERUN and identifier is not None:
            self.reruns.pop(identifier, None)
            self.answers.pop(identifier, None)
        elif name == TICKET_DONE and identifier is not None:
            self.verdicts.pop(identifier, None)
        elif name == VERDICT and identifier is not None:
            self.verdicts.setdefault(identifier, []).append(
                {"verdict_type": payload.get("verdict_type"), "pass": payload.get("pass")})
        elif name == FINDING and payload.get("id"):
            self.findings.add(payload["id"])
        elif name == PROGRESS and payload.get("run_id"):
            self.progress[payload["run_id"]] = dict(payload)
        elif name == DISCARDED and identifier is not None:
            self.discarded[identifier] = dict(payload)
        elif name == INTEGRATED and identifier is not None:
            self.integrated[identifier] = payload.get("commit")
            if payload.get("empty"):
                self.integrated_empty.add(identifier)
            else:
                self.integrated_empty.discard(identifier)
            ticket = self.tickets.get(identifier)
            if ticket is not None and ticket.latest is not None and not ticket.latest.ended:
                ticket.latest.integrated = True
        elif name in JOB_STATUS_AFTER:
            self._job(name, payload, event)
        return self

    @staticmethod
    def _ticket_event(ticket, name, payload, ts):
        if name in STATUS_AFTER:
            ticket.status = STATUS_AFTER[name]
        if name == TICKET_LAUNCHED:
            ticket.launched(payload, ts)
        elif name == TICKET_SESSION:
            ticket.session(payload)
        elif name == TICKET_RESULT:
            ticket.result(payload)
        elif name == TICKET_RESUMED:
            ticket.resumed(payload, ts)
        elif name in ENDS_ATTEMPT:
            ticket.end(name, payload)
        if name == TICKET_FAILED:
            ticket.steps.append(payload.get("next"))
            ticket.failure = payload.get("reason")
            failed = ticket._named(payload)
            # A tier up counts rungs, not difficulty levels (decision 16): the next attempt starts one rung
            # above the rung the failed attempt ran on, whatever the ticket's level says.
            if payload.get("next") == "tier_up" and failed is not None and failed.rung is not None:
                ticket.rung_floor = max(ticket.rung_floor or 0, failed.rung + 1)
        elif name == TICKET_RERUN:
            ticket.steps, ticket.failure, ticket.rung_floor = [], None, None

    def _control(self, payload, identifier):
        command = payload.get("command")
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        target = _int(args.get("ticket"))
        target = identifier if target is None else target
        if command == "pause":
            self.paused_by_owner = True
        elif command == "resume":
            self.paused_by_owner = False
        elif command == "stop":
            previous = self.stop or {}
            self.stop = {
                # A drain waits for running workers; an immediate stop does not, and a later drain
                # does not soften a stop that was already immediate.
                "drain": bool(args.get("drain")) and previous.get("drain", True),
                "switch_to": args.get("switch_to") or previous.get("switch_to"),
                "by": payload.get("by"),
            }
        elif command == "cancel" and target is not None:
            self.cancels[target] = payload.get("by")
        elif command == "rerun" and target is not None:
            self.reruns[target] = payload.get("by")
        elif command == "autonomy" and args.get("autonomy"):
            self.autonomy = args["autonomy"]
        elif command == "model_fallback" and args.get("model_fallback") in CONSENTS and self.run is not None and not self.run["ended"]:
            self.model_fallback = args["model_fallback"]
        elif command == "ladder_changes" and args.get("ladder_changes") in LADDER_CONSENTS and self.run is not None and not self.run["ended"]:
            self.ladder_changes = args["ladder_changes"]
        elif command == "pacing":
            self.thresholds.update({key: args[key] for key in ("stop_at", "cheap_at") if key in args})

    def _job(self, name, payload, event):
        job = payload.get("job") or event.get("job")
        if not job:
            return
        record = self.jobs.setdefault(job, {"ticket": None, "status": None, "attempt": None, "exit_code": None})
        ticket = _int(payload.get("ticket", event.get("ticket")))
        if ticket is not None:
            record["ticket"] = ticket
        record["status"] = JOB_STATUS_AFTER[name]
        if _int(payload.get("attempt")) is not None:
            record["attempt"] = payload["attempt"]
        if name == JOB_FINISHED:
            record["exit_code"] = _int(payload.get("exit_code"))
        if name == JOB_WAITING:
            record["waiting"] = payload.get("reason")
        else:
            record.pop("waiting", None)

    def _move_asks(self, standing, stands, ts):
        """Move the asks about a standing hold to the reset a later `paused` gives it, while that hold's reset is still ahead."""
        if standing is None or standing.get("resets_at") == stands.get("resets_at"):
            return
        before, at = epoch(standing.get("resets_at")), epoch(ts)
        if before is None or (at is not None and at >= before):
            return
        for ask in self.asks.values():
            if ask["resets_at"] == standing.get("resets_at"):
                ask["resets_at"] = stands.get("resets_at")

    def ask_for(self, resets_at):
        """The ticket id of the ask about the window resetting at `resets_at`, the latest opened; None when none was."""
        found = [ticket for ticket, ask in self.asks.items() if ask["resets_at"] == resets_at]
        return max(found) if found else None

    def held_rungs(self):
        """The rungs held now, `{rung: the decision ticket holding it}` (decision 16, ticket 63).

        A rung is held from the not-served failure that opened its decision ticket until that ticket is
        answered; the answer is the owner's word that the policy was edited, and the journal is all this reads,
        so a restarted conductor holds the same rungs a running one does.
        """
        return {ask["rung"]: ticket for ticket, ask in sorted(self.rung_asks.items()) if ticket not in self.answers}

    def passed(self, identifier):
        """The verdict types a ticket passed since it was last done."""
        return {item["verdict_type"] for item in self.verdicts.get(identifier, []) if item.get("pass")}

    def in_flight(self):
        """`(ticket id, attempt)` for every attempt still owed its session's result or that result's carrying, by id."""
        return [(identifier, ticket.latest) for identifier, ticket in sorted(self.tickets.items())
                if ticket.latest is not None and ticket.latest.owed in (SESSION, RESULT)]


def not_served_origin(rung, ticket, attempt):
    """The origin of the decision ticket about a rung whose model the subscription does not serve (decision 16)."""
    return _NOT_SERVED_ORIGIN % (int(rung), int(ticket), int(attempt))


def origin_rung(origin):
    """The rung a not-served origin names, or None for any other origin (the inverse of `not_served_origin`)."""
    match = _NOT_SERVED_RE.match(origin) if isinstance(origin, str) else None
    return int(match.group(1)) if match else None


def replay(events, view=None):
    """Fold `events` into `view` (a fresh one by default) and return it."""
    view = View() if view is None else view
    for event in events:
        view.apply(event)
    return view
