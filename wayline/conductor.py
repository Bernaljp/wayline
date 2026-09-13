"""The conductor (Implementation Decisions 5, Testing Decisions seam 4): the wave, end to end.

`wayline run` is one process over one project. A wave is one pass of its loop: regenerate
`graph.json`, compute the frontier, cut it down to what can be launched now, add a worktree for
each ticket it picks, assemble the prompts, launch the workers through the launcher seam,
validate what comes back, run the machine acceptance in the worktree, rebase onto `main`, run the
acceptance again, fast-forward `main`, run it once more there, write the findings and the status
through the ledger, journal every step, and remove the worktree. The run ends when the frontier
is empty.

What M0 and M1 build here, and what they leave to the tickets that extend them:

- Up to `policy.max_parallel_workers` workers (ticket 07), each session in a thread of its own.
  A wave does not wait for them (ticket 09): it carries the outcomes of the sessions that returned
  since the last wave, one at a time in id order, because the integration protocol is one rebase
  and one fast-forward at a time, then launches what the frontier allows and returns. `run` waits
  between waves, waking when a session returns or another process appends to the journal.
- Resume is start (ticket 09). `run` takes the heartbeat `research/conductor.json`, whose `flock`
  keeps a second conductor off the project, and rewrites it every wave. The first wave replays
  the journal from byte zero into a `replay.View`, reconciles the ticket files and `.worktrees/`
  with it, re-adopts a worker still running by its pid and stream, resumes a dead one by session
  id or relaunches it, carries a result no conductor carried, and queues again the verdicts a done
  ticket earned. Every later wave folds what the journal gained and applies the `control` events,
  answers, and feedback that other processes appended.
- One resume per gate, for an invalid result or a failed acceptance (BRIEF 9.1). The rest of the
  escalation ladder (a tier up, a split ticket, `needs_human`) is named in the `next` of the
  `ticket_failed` event and built by ticket 38, which also acts on the stall counter that the
  `wave` event lets a restart rebuild.
- The integration protocol (ticket 08), one ticket at a time under the ledger lock. A rebase
  conflict is aborted and the `integrator` role is launched once in the worktree, on the
  conflicting paths, to finish the rebase itself; the conductor's second rebase is the check, and
  a second conflict fails the ticket with `next: split`. The integrator is model work, so it waits
  while the run holds launches, and the attempt waits in flight with it.
- No pacing and no window pause: ticket 10 computes the action the pick order already reads and
  decides what an action refuses to launch; the owner's pause (`wayline pause`) holds launches
  here. No job poller, so an experiment ticket whose jobs outlive its worker stays `running` and
  holds the run open until ticket 19's poller closes it or `wayline stop` ends the run.
- A result's `proposals`, `decision_requests` and `goal_progress` are written into the ticket's
  `## Result` section so the owner sees them, and nothing else: admission is ticket 37, decision
  tickets are ticket 35, and keep-if-better is ticket 39.
- The Type-B gate of decision 11 (ticket 32): a done ticket's verdicts are queued and drained
  later in the same wave, and the ticket is `accepted` when every one of them passed.

The conductor never trusts the worker's own acceptance file. It runs the ticket's commands itself,
three times, and the ticket is `done` only once they passed on `main`. Nor does it trust the
worker's own account of its quality: `accepted` comes from a verifier on another model.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from wayline import HARNESS_ROOT, gates, replay, schedule, tickets, worker
from wayline.ledger import (
    ACCEPTANCE, CONTROL, DECISION, FEEDBACK, FINDING, INTEGRATED, RUN_ENDED, RUN_STARTED, TICKET_ACCEPTED,
    TICKET_BLOCKED, TICKET_CANCELLED, TICKET_DONE, TICKET_FAILED, TICKET_LAUNCHED, TICKET_NEEDS_HUMAN,
    TICKET_RERUN, TICKET_RESULT, TICKET_RESUMED, TICKET_SESSION, WAVE, ConductorBusy, Ledger, now_ts,
)
from wayline.project import ProjectError, find_project, policy_for, read_harness

__all__ = [
    "ConductorError", "Conductor", "WaveResult", "Tier", "tier_for", "porcelain_entries",
    "dirty_outside_research", "refuse_to_start", "run_command", "WORKTREES", "RESEARCH", "BRANCH",
]

MAIN = "main"
RESEARCH = "research"
FINDINGS = "findings.jsonl"
WORKTREES = ".worktrees"
BRANCH = "ticket/%s"
LEDGER_COMMIT = "ledger: wave %d"
# The heartbeat is rewritten every wave; committing it would make every wave a ledger commit.
HEARTBEAT_PATH = RESEARCH + "/conductor.json"

# How often a run waiting between waves looks at its sessions and at the journal, in seconds.
POLL_S = 2
# How long a cancel or a rerun waits for the worker it terminated before killing it outright.
STOP_WAIT_S = 15

# The gate a session answers (BRIEF 9.1): the launch, or the one resume each gate is given. The
# resume stages are the `ticket_resumed` reasons that spend them.
LAUNCH_STAGE = "launch"
INVALID_RESULT = "invalid_result"
ACCEPTANCE_FAILED = "acceptance_failed"
# What a worker that died before its session started waits for: a relaunch in the same attempt.
RELAUNCH = "relaunch"
# The gate a worker that ran past its budget is resumed at, once (decision 3).
TIMEOUT = "timeout"
# The role that finishes a conflicted rebase (decision 5), and what an attempt whose integration
# waits for the run to allow model work waits for.
INTEGRATOR = "integrator"
INTEGRATE = "integrate"

# The identity a conductor commits the ledger under when the project's repository has none.
IDENTITY = ("-c", "user.name=wayline", "-c", "user.email=wayline@localhost")

RESUME_INVALID = (
    "The result you returned could not be used: %s.\n\n"
    "Return the structured result now, through the structured output, matching the schema this "
    "session was launched with. Do not start new work."
)
RESUME_ACCEPTANCE = (
    "The machine acceptance failed in your worktree. The conductor ran the ticket's commands "
    "itself after you stopped:\n\n%s\n\n"
    "Fix what failed, run `wayline accept` again, commit on the ticket branch, and return the "
    "structured result."
)
RESUME_DIED = (
    "Your session was interrupted before it returned its result: the process running it died. "
    "Continue the ticket from where you left off, commit on the ticket branch, run `wayline accept`, "
    "and return the structured result."
)
RESUME_DIED_MESSAGE = "\n\nThe message your interrupted session was answering:\n\n%s"
RESUME_TIMEOUT = (
    "You ran out of time: this session passed its budget of %s minute(s). Return the structured result "
    "now, through the structured output, matching the schema this session was launched with. Do not "
    "start new work."
)
REJECTED = (
    "the %s verdict failed: a fresh %s session that did not write this read it and found\n\n%s"
)


# What the conductor says when a `control` event another process appended arrives, by command.
ARRIVALS = {
    "pause": lambda args, by: "paused by %s" % by,
    "resume": lambda args, by: "resumed by %s" % by,
    "stop": lambda args, by: "asked by %s to stop %s" % (by, "once the running workers return" if args.get("drain") else "at this wave"),
    "autonomy": lambda args, by: "autonomy is now %s" % args.get("autonomy"),
    "pacing": lambda args, by: "pacing thresholds: %s" % ", ".join("%s %s" % (key, args[key]) for key in ("stop_at", "cheap_at") if key in args),
}


class ConductorError(ValueError):
    """A run the conductor refuses to start, or a step of a wave that cannot be carried out."""


# --- git ------------------------------------------------------------------------------------


def _git_command(cwd, *args, identity=(), ok=(0,)):
    """One git command, captured; `ok=None` hands the caller the exit code instead of raising."""
    done = subprocess.run(["git", "-C", str(cwd), *identity, *args], capture_output=True, text=True)
    if ok is not None and done.returncode not in ok:
        raise ConductorError("git %s failed in %s (exit %d): %s"
                             % (args[0], cwd, done.returncode, (done.stderr or done.stdout).strip()))
    return done


def porcelain_entries(text):
    """The `(status, path)` pairs `git status --porcelain -z` reports, a rename's two fields included.

    With `-z` every entry is `XY <path>` up to a NUL, and a rename or a copy is followed by one
    more NUL-terminated field for the other path. Reading the fields in order is the only way to
    tell that second field from the next entry.
    """
    fields = [item for item in text.split("\0") if item != ""]
    entries, index = [], 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        status = entry[:2]
        entries.append((status, entry[3:]))
        if ("R" in status or "C" in status) and index < len(fields):
            entries.append((status, fields[index]))
            index += 1
    return entries


def dirty_outside_research(project):
    """The changed paths on the project's checkout that do not lie under `research/`, sorted."""
    text = _git_command(project, "status", "--porcelain", "-z").stdout
    return sorted({path for _, path in porcelain_entries(text)
                   if path != RESEARCH and not path.startswith(RESEARCH + "/")})


def refuse_to_start(project):
    """Every reason this run must not start, with what to do about it; () when there is none.

    The branch is checked as well as the tree, because the fast-forward of the integration
    protocol is `git merge --ff-only` into whatever the project has checked out: on another
    branch it would quietly move that one instead of `main`.

    The other refusal of decision 5, a harness checkout whose tag is not the project's pin, is
    ticket 46's: it ships with the tagging and the `upgrade` command that fixes a mismatch.
    """
    branch = _git_command(project, "rev-parse", "--abbrev-ref", "HEAD", ok=None)
    if branch.returncode != 0:
        return ["%s is not a git repository, and the conductor branches worktrees from main: "
                "run wayline init %s" % (project, project)]
    problems = []
    if branch.stdout.strip() != MAIN:
        problems.append("the project is on the branch %r, not %s, and the conductor fast-forwards %s: "
                        "run git -C %s switch %s" % (branch.stdout.strip(), MAIN, MAIN, project, MAIN))
    dirty = dirty_outside_research(project)
    if dirty:
        problems.append("%s has %d change(s) outside research/ (%s); commit or stash them, then run again"
                        % (project, len(dirty), ", ".join(dirty[:5]) + (", ..." if len(dirty) > 5 else "")))
    return problems


# --- the difficulty tier --------------------------------------------------------------------


@dataclass
class Tier:
    """What a ticket's difficulty resolves to in the policy: the model, the effort, the budget."""

    model: str
    effort: str
    max_turns: Optional[int] = None
    max_minutes: Optional[int] = None
    context_chars: Optional[int] = None


def tier_for(policy, difficulty, ticket_budget=None):
    """The tier of `difficulty` (policy `difficulty`, `budget`, `context_pack`), the ticket's budget winning.

    `context_pack.max_chars` is keyed by model and names only the three a worker runs on, so
    anything else (a `haiku` judge) takes the smallest cap rather than none at all.
    """
    tiers = policy.get("difficulty") or {}
    tier = tiers.get(str(difficulty), tiers.get(difficulty))
    if not isinstance(tier, dict) or "model" not in tier or "effort" not in tier:
        raise ConductorError("policy.difficulty has no tier %r; it has %s"
                             % (difficulty, ", ".join(sorted(map(str, tiers))) or "none"))
    budget = dict((policy.get("budget") or {}).get(tier.get("budget")) or {})
    budget.update({key: value for key, value in (ticket_budget or {}).items() if value is not None})
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    return Tier(
        model=tier["model"], effort=tier["effort"],
        max_turns=budget.get("max_turns"), max_minutes=budget.get("max_minutes"),
        context_chars=caps.get(tier["model"], min(caps.values()) if caps else None),
    )


# --- what a wave did ------------------------------------------------------------------------


@dataclass
class WaveResult:
    """One pass of the loop, as the `run` verb and the tests read it.

    `launched` holds the tickets whose worker process started, in pick order: the same tickets the
    journal's `ticket_launched` events name, so a pick the launcher refused is counted as failed
    and nothing else. `failed` holds the tickets that were launched, did not reach `done`, and are not still
    running, whatever the reason: a failure, a block, or a question for a person. The journal
    says which.
    """

    number: int
    launched: list = field(default_factory=list)
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    running: list = field(default_factory=list)
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    ended: bool = False
    reason: Optional[str] = None
    ledger_commit: Optional[str] = None
    # The worker outcomes this wave carried and the findings they filed: a wave that carried one is
    # a settling wave, and whether it filed anything is what the stall counter reads.
    outcomes: int = 0
    findings: int = 0

    @property
    def touched(self):
        """Whether this wave moved anything at all; a wave that did not cannot be repeated usefully.

        A wave that only drained the verdict queue moved something: the tickets it accepted
        released whatever waited on them, so the next wave has work the last one did not.
        """
        return bool(self.launched or self.done or self.failed or self.running
                    or self.accepted or self.rejected or self.outcomes)


@dataclass
class _Queued:
    """One done ticket's Type-B gate: every verdict it earned, and the attempt that earned it.

    The queue lives on the conductor for the length of the run. A process that dies with a
    verdict still queued loses it and leaves the ticket `done` and unaccepted, which is what
    `wayline status` and `schedule.held_back` then say; replaying the journal to find them again
    is part of the resume ticket 09 builds.
    """

    ticket: int
    attempt: int
    asks: list


@dataclass
class _Want:
    """The session an attempt waits to start while the run holds model work.

    `stage` is the gate a resume answers (`invalid_result`, `acceptance_failed`), `worker_died` for
    the resume of a session that died, or `relaunch` for a worker that died before its session
    started; `message` is what a resume says.
    """

    stage: str
    message: Optional[str] = None


class _Stop(NamedTuple):
    """A stop this run is to apply: whether it drains, and the reason its `run_ended` carries."""

    drain: bool
    reason: str


class _Conflict(NamedTuple):
    """A rebase that stopped: the paths git names as unmerged, each one's text with its markers, and git's words."""

    paths: list
    markers: list
    output: str


@dataclass
class _Attempt:
    """One attempt at one ticket, carried through the steps of the outcome."""

    ticket: dict
    body: str
    number: int
    worktree: Path
    role: Optional[worker.Role] = None
    tier: Optional[Tier] = None
    prompt: Optional[worker.Prompt] = None
    request: Optional[worker.LaunchRequest] = None
    envelope: Optional[worker.Envelope] = None
    session_id: Optional[str] = None
    resumed: bool = False
    # The commit `main` was fast-forwarded to, which is what a verdict on the diff reads.
    commit: Optional[str] = None
    # The graph's effective difficulty, which is the ticket's unless the human pinned one.
    difficulty: Optional[int] = None
    # Whether a worker process actually started, which is when `ticket_launched` is journaled.
    started: bool = False
    # What the launch raised, when it did: a thread cannot fail its own wave, so the failure is
    # carried back to the main thread and the ticket is failed there, in pick order, like any other.
    failure: Optional[BaseException] = None
    # The gate the session in flight answers, and whether the result it returned is journaled yet.
    stage: str = LAUNCH_STAGE
    result_journaled: bool = False
    # The session in flight: its thread, the moment its process exists, and where to find it.
    thread: Optional[threading.Thread] = None
    begun: threading.Event = field(default_factory=threading.Event)
    pid: Optional[int] = None
    run_dir: Optional[Path] = None
    stream_path: Optional[Path] = None
    tail: Optional[worker.StreamTail] = None
    session_journaled: bool = False
    # The session the attempt waits to start while the run holds model work: a resume, or a relaunch.
    want: Optional[_Want] = None
    # A session this conductor did not start (a restart re-adopted it): polled by stream and pid.
    adopted: bool = False
    # When a re-adopted session started, which its budget is counted from, and when the conductor
    # sent it SIGTERM for running past that budget.
    started_at: Optional[str] = None
    terminated_at: Optional[float] = None
    # The findings `_close` filed for this attempt.
    findings: int = 0
    # Whether the attempt passed every gate before the integration and waits to integrate, because
    # its rebase conflicted while the run held the integrator's launch.
    integrating: bool = False

    @property
    def id(self):
        return self.ticket["id"]

    @property
    def running(self):
        """Whether a session this conductor started for the attempt is still running in its thread."""
        return self.thread is not None and self.thread.is_alive()

    @property
    def result(self):
        """The validated structured output, or an empty mapping before there is one."""
        return (self.envelope.structured_output or {}) if self.envelope is not None else {}


# --- the conductor --------------------------------------------------------------------------


class Conductor:
    """One `wayline run` over one project: the wave, and what a run carries between waves."""

    def __init__(self, project, harness_root=HARNESS_ROOT, policy=None, out=None):
        self.project = Path(project).resolve()
        self.harness_root = Path(harness_root).resolve()
        self.ledger = Ledger(self.project)
        self.policy = policy_for(self.project, self.harness_root) if policy is None else policy
        self.number = 0
        self.out = sys.stdout if out is None else out
        self._who_args = None
        # The Type-B queue of decision 11: what each done ticket earned, drained later in the wave
        # because a verdict is model work like any other and is paced like any other.
        self.verdicts = []
        # The pacing action of wave step 8 and the resource answer of step 7, both seams the pick
        # order already reads: ticket 10 computes the action from the windows, and the job poller
        # replaces `resources_free` with the free-slot rule of `wayline.resources`.
        self.action = schedule.NORMAL
        self.resources_free = schedule.everything_free
        # What a run carries between waves: the working view folded from the journal, the byte
        # offset read so far, the attempts whose sessions are in flight, and the heartbeat.
        self.view = replay.View()
        self.offset = 0
        self.flight = {}
        self._wake = threading.Event()
        self.heartbeat = None
        self.started_at = self.last_wave_at = self.harness_tag = None
        # Resume is start: the first wave takes over what the replayed journal says is owed.
        self.taken_over = False
        # The cancels and reruns that changed nothing, said once each rather than every wave.
        self.declined = set()

    def say(self, message):
        print(message, file=self.out, flush=True)

    # --- the loop ---

    def wave(self):
        """One pass of the loop (decision 5), called directly by tests.

        A wave does not wait for its workers. It carries the outcomes of the sessions that
        finished since the last wave, launches what the frontier allows, and returns; the sessions
        it started run on in their threads and are carried by a later wave.
        """
        self.number += 1
        self.last_wave_at = now_ts()
        result = WaveResult(self.number)
        self._beat()
        arrived = self._tail()
        first = not self.taken_over
        if first:
            self._take_over(result)
        self._apply_controls(arrived, first)
        self._poll(result)
        if not self._holds_launches():
            picks = self._picks(self._graph())
            if picks:
                self._start(picks, result)
            self._drain_verdicts(result)
        self._journal_wave(result)
        self._end(result)
        result.ledger_commit = self._commit_ledger()
        self._tail()
        self._beat()
        return result

    def run(self, max_waves=None, resume=False, wait=None):
        """Take the heartbeat, journal `run_started`, and take waves until the run ends.

        Returns every wave's result. Between two waves the run waits up to `policy.poll_seconds`,
        waking early when a session it started has returned or another process appended to the
        journal; the wait lives here and not in the wave, so that no test sleeps (Testing
        Decisions, seam 4). `wait(seconds)` replaces it, which is how a test settles its workers
        between waves instead.

        `run_started` is journaled here rather than in the verb, because the dashboard calls this
        function in process. The heartbeat lock is taken first, so a second conductor on the same
        project is refused before it has journaled anything.
        """
        harness = read_harness(self.project)
        try:
            self.heartbeat = self.ledger.heartbeat().acquire()
        except ConductorBusy as busy:
            raise ConductorError("%s; wayline stop --project %s stops it" % (busy, self.project)) from None
        try:
            self.harness_tag, self.started_at = harness.get("harness_tag"), now_ts()
            self._beat()
            self.ledger.append_event(RUN_STARTED, {
                "resume": bool(resume), "harness_tag": harness.get("harness_tag"),
                "autonomy": harness.get("autonomy"), "radius": harness.get("radius"), "pid": os.getpid(),
            })
            waves = []
            wait = self._idle if wait is None else wait
            while True:
                waves.append(self.wave())
                if waves[-1].ended or (max_waves is not None and len(waves) >= max_waves):
                    return waves
                wait(self._poll_seconds())
        finally:
            self.heartbeat.release()
            self.heartbeat = None

    def settle(self, timeout=None):
        """Wait until every session this conductor started has returned; the next wave carries them."""
        for attempt in list(self.flight.values()):
            if attempt.thread is not None:
                attempt.thread.join(timeout)

    def _idle(self, seconds):
        """Wait up to `seconds` for something the next wave can act on, looking every `POLL_S`."""
        deadline = time.monotonic() + seconds
        while not self._ready():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._wake.wait(min(remaining, POLL_S))
            self._wake.clear()

    def _ready(self):
        """Whether a session returned, or the journal grew past what this conductor has read."""
        # An attempt that waits for the run to allow model work again is woken by the journal
        # (`wayline resume`), not by its own finished thread, or the run would take waves back to back.
        if any(attempt.want is None and attempt.thread is not None and not attempt.running
               for attempt in self.flight.values()):
            return True
        if any(attempt.adopted and attempt.tail.read().result is not None for attempt in self.flight.values()):
            return True
        try:
            return self.ledger.journal_path.stat().st_size > self.offset
        except OSError:
            return False

    def _poll_seconds(self):
        seconds = self.policy.get("poll_seconds", 60)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
            raise ConductorError("policy.poll_seconds is %r; it is a number of seconds, 0 or more" % (seconds,))
        return seconds

    def _beat(self):
        """Rewrite the heartbeat `research/conductor.json` (decision 5), when this conductor holds it."""
        if self.heartbeat is not None:
            self.heartbeat.write(pid=os.getpid(), started_at=self.started_at,
                                 last_wave_at=self.last_wave_at, harness_tag=self.harness_tag)

    def _tail(self):
        """Fold what the journal gained since the last read into the working view (wave step 1)."""
        events, self.offset = self.ledger.read_events(self.offset)
        replay.replay(events, self.view)
        return events

    def _journal_wave(self, result):
        """The `wave` event of a settling wave, which is what lets a restart rebuild the stall counter."""
        if result.outcomes:
            self.ledger.append_event(WAVE, {"number": self.number, "outcomes": result.outcomes,
                                            "progressed": bool(result.done or result.findings)})

    def _end(self, result):
        """`run_ended`: once a stop has been applied, or once the frontier is empty and nothing runs.

        A stop without `drain` ends the run at this wave and leaves the workers still running to
        finish on their own, for the next run to re-adopt. A drain waits for them, and leaves a
        session that has not started yet to the next run, whose take-over finds it in the journal.
        """
        stopping = self._stop_requested()
        if stopping is not None:
            if stopping.drain:
                for identifier, attempt in list(self.flight.items()):
                    if attempt.want is not None and not attempt.running:
                        self.flight.pop(identifier)
                if self.flight:
                    return
            else:
                left = sorted(identifier for identifier, attempt in self.flight.items() if attempt.running or attempt.adopted)
                if left:
                    self.say("  ticket(s) %s still have a worker running; it finishes on its own and the next run re-adopts it"
                             % ", ".join(str(identifier) for identifier in left))
            self.ledger.append_event(RUN_ENDED, {"reason": stopping.reason})
            result.ended, result.reason = True, stopping.reason
            return
        if self.flight:
            return
        graph = self._graph()
        running = [entry for entry in graph["tickets"] if entry["status"] == "running"]
        if not tickets.frontier(graph) and not running:
            for line in schedule.held_back(graph):
                self.say(line)
            self.ledger.append_event(RUN_ENDED, {"reason": "frontier_empty"})
            result.ended, result.reason = True, "frontier_empty"

    def _graph(self):
        events, _ = self.ledger.read_events()
        graph, _ = tickets.refresh_graph(self.project, ledger=self.ledger, events=events)
        return graph

    # --- what this wave launches (decision 5, wave steps 7 to 9) ---

    def _picks(self, graph):
        """The tickets to launch now: the launchable subset of the frontier, in pick order.

        `max_parallel_workers` counts workers, so a wave fills only the slots that the workers still
        running from earlier waves leave free. A ticket left `running` by jobs that outlived their
        worker holds its touch set against the frontier but occupies no worker slot, because that
        ticket has no worker.
        """
        running = [entry for entry in graph["tickets"] if entry["status"] == "running"]
        busy = sum(1 for attempt in self.flight.values() if attempt.running or attempt.adopted)
        return schedule.pick(
            graph, running=running, slots=max(0, self._slots() - busy), action=self.action,
            root=self.project, free=self.resources_free, goal_tickets=self._goal_tickets(),
        )

    def _slots(self):
        """`policy.max_parallel_workers`: how many workers this conductor runs at once."""
        slots = self.policy.get("max_parallel_workers", 1)
        if isinstance(slots, bool) or not isinstance(slots, int) or slots < 1:
            raise ConductorError("policy.max_parallel_workers is %r; it is a whole number of workers, at least 1"
                                 % (slots,))
        return slots

    def _goal_tickets(self):
        """The ids of the tickets that report a goal metric, which the pick order prefers.

        `graph.json` carries the scheduling fields of decision 2 and `goal_metric` is not one of
        them, so the ticket files answer this; the conductor reads them for every launch anyway.
        """
        return {ticket["id"] for ticket in tickets.read_tickets(self.project) if ticket.get("goal_metric")}

    # --- the tickets of one wave ---

    def _start(self, picks, result):
        """Prepare every pick, start its session, and return once each worker process has started.

        The preparation is serial, because `git worktree add` writes the repository the other
        launches read and each launch says its line in pick order. The sessions then run in threads
        of their own; the wave waits only until each process exists or its launch failed, so
        `launched` names exactly the tickets whose `ticket_launched` was journaled.
        """
        attempts = []
        for entry in picks:
            ticket, body = self._ticket(entry["id"])
            attempt = _Attempt(ticket, body, int(entry.get("attempt") or 0) + 1, self._worktree(entry["id"]))
            try:
                self._begin(attempt, entry)
            except (ValueError, OSError) as failure:  # a role, a prompt, a settings file, or a git step
                self._fail(attempt, str(failure), "needs_human")
                result.failed.append(attempt.id)
                continue
            attempts.append(attempt)
            self._run_session(attempt, "launch")
        for attempt in attempts:
            attempt.begun.wait()
            if attempt.started:
                result.launched.append(attempt.id)
                self.flight[attempt.id] = attempt
            else:
                self._carry(attempt, result)  # the launcher refused it before a process started

    def _run_session(self, attempt, kind, message=None):
        """Start one session of an attempt, its launch or a resume, in a thread of its own."""
        attempt.envelope = attempt.failure = None
        attempt.result_journaled = attempt.adopted = False
        attempt.begun = threading.Event()
        attempt.thread = threading.Thread(target=self._session, args=(attempt, kind, message),
                                          name="wayline-ticket-%d" % attempt.id, daemon=True)
        attempt.thread.start()

    def _session(self, attempt, kind, message):
        """A session's thread: the launcher seam, blocking on its child until the child exits.

        Every `Exception` is carried to the main thread rather than raised here, where it would be
        printed and lost; `_carry` fails the ticket on the two a ticket can be failed on and raises
        the rest there. The thread is a daemon because a worker is a process of its own: a
        conductor that exits leaves it running, for the next conductor to re-adopt.
        """
        try:
            began = lambda started: self._began(attempt, started, kind)
            if kind == "launch":
                attempt.envelope = worker.launch(attempt.request, on_start=began)
            else:
                attempt.envelope = worker.resume(attempt.request, attempt.session_id, message, on_start=began)
        except Exception as failure:  # carried to the main thread, and raised again there
            attempt.failure = failure
        finally:
            attempt.begun.set()
            self._wake.set()

    def _began(self, attempt, started, kind):
        """The session's process exists: where to find it, and, for a launch, `ticket_launched` with its pid."""
        attempt.pid, attempt.run_dir, attempt.stream_path = started.pid, Path(started.run_dir), Path(started.stream_path)
        attempt.tail = worker.StreamTail(started.stream_path)
        if kind == "launch":
            self._journal_launch(attempt, started)
        attempt.started = True
        attempt.begun.set()

    def _take_over(self, result):
        """Resume is start (decision 5): pick up every attempt the journal, replayed from byte zero, still owes.

        A session with no `ticket_result` is re-adopted when its stream already holds the result or
        its pid is still that session's worker, resumed by session id when it died after its session
        started, and relaunched in the same attempt when it died before. Each is journaled as
        `ticket_resumed` with its reason. A result no conductor carried is carried. This runs once,
        at the conductor's first wave.
        """
        self.taken_over = True
        self._reconcile_statuses()
        graph = {entry["id"]: entry for entry in self._graph()["tickets"]}
        for identifier, replayed in self.view.in_flight():
            if identifier not in graph:
                continue
            ticket, body = self._ticket(identifier)
            attempt = _Attempt(ticket, body, replayed.number, self._worktree(identifier))
            try:
                self._adopt(attempt, replayed, graph[identifier])
            except (ValueError, OSError) as failure:  # a role, a prompt, a settings file, or a git step
                self.flight.pop(attempt.id, None)
                self._fail(attempt, str(failure), "needs_human")
                result.failed.append(attempt.id)
        self._reconcile_worktrees(graph)
        self._requeue_verdicts(graph)

    def _reconcile_statuses(self):
        """Rewrite each ticket file whose status the journal contradicts (decision 5, resume).

        The journal wins, because a conductor killed between an event and the file it rewrites
        leaves the file one step behind. A ticket the journal never named whose file says `running`
        was being launched when the conductor died, and goes back to `open`. Nothing else in the
        file changes, so a hand-pinned difficulty and an `## Answer` section stay as they were left.
        """
        for ticket in tickets.read_tickets(self.project):
            known = self.view.tickets.get(ticket["id"])
            status = known.status if known is not None else None
            if status is None and ticket["status"] == "running":
                status = "open"
            if status is None or status == ticket["status"]:
                continue
            self._set_status(ticket["id"], status)
            self.say("  ticket %d: %s in its file and %s in the journal; the journal wins"
                     % (ticket["id"], ticket["status"], status))

    def _reconcile_worktrees(self, graph):
        """Remove the worktree and the branch of every ticket the journal closed (decision 5, resume)."""
        directory = self.project / WORKTREES
        if not directory.is_dir():
            return
        for path in sorted(directory.iterdir()):
            identifier = int(path.name) if path.name.isdigit() else None
            entry = graph.get(identifier)
            if entry is None or entry["status"] not in tickets.SATISFIED or identifier in self.flight:
                continue
            self._remove_worktree(identifier)
            self.say("  removed the worktree of ticket %d, which the journal closed" % identifier)

    def _requeue_verdicts(self, graph):
        """Queue again the verdicts a done ticket earned and no conductor took (decision 11).

        The queue lived in the process that died. A verdict the journal already holds as passed is
        not taken twice, and a ticket all of whose verdicts passed is accepted here.
        """
        for identifier, entry in sorted(graph.items()):
            known = self.view.tickets.get(identifier)
            launched = known.latest if known is not None else None
            if entry["status"] != "done" or launched is None or not launched.model:
                continue
            if any(queued.ticket == identifier for queued in self.verdicts):
                continue
            ticket, _ = self._ticket(identifier)
            earned = gates.ticket_asks(ticket, entry.get("difficulty", ticket["difficulty"]), launched.model,
                                       tickets.relative_path(ticket), commit=self.view.integrated.get(identifier),
                                       outputs=ticket.get("outputs") or [])
            passed = {item["verdict_type"] for item in self.view.verdicts.get(identifier, []) if item.get("pass")}
            asks = [ask for ask in earned if ask.verdict_type not in passed]
            if asks:
                self.verdicts.append(_Queued(identifier, launched.number, asks))
                self.say("  ticket %d is done and its %s verdict was never taken; queued again"
                         % (identifier, ", ".join(ask.verdict_type for ask in asks)))
            elif earned:
                self._set_status(identifier, "accepted")
                self.ledger.append_event(TICKET_ACCEPTED, {"ticket": identifier}, ticket=identifier)
                self.say("  ticket %d passed every verdict before the restart; accepted" % identifier)

    def _adopt(self, attempt, replayed, entry):
        """Take over one attempt a restart found still owed: carry its result, re-adopt it, resume it, or relaunch it."""
        attempt.role = worker.read_role(attempt.ticket["role"], self.harness_root, self.project)
        attempt.difficulty = entry.get("difficulty", attempt.ticket["difficulty"])
        attempt.tier = tier_for(self.policy, attempt.difficulty, attempt.ticket.get("budget"))
        attempt.stage, attempt.resumed = replayed.stage, bool(replayed.spent)
        attempt.session_id, attempt.session_journaled = replayed.session_id, replayed.session_id is not None
        self._prepare(attempt)
        session = replayed.sessions[-1]
        attempt.run_dir = self._session_path(attempt, session)
        attempt.stream_path = attempt.run_dir / "stream.jsonl" if attempt.run_dir else None
        attempt.pid = session.pid if session.kind == "launch" else _read_pid(attempt.run_dir)
        attempt.started_at = _session_started(attempt.run_dir) or session.ts
        attempt.tail = worker.StreamTail(attempt.stream_path or self._attempt_dir(attempt) / "missing")
        attempt.tail.read()
        self._journal_session(attempt)  # a session the stream saw and the journal missed
        attempt.started = True
        self.flight[attempt.id] = attempt
        if replayed.owed == replay.RESULT:
            if attempt.stream_path is None or not attempt.stream_path.is_file():
                raise ConductorError("ticket %d's result is journaled and its stream is gone; a person has to look"
                                     % attempt.id)
            attempt.envelope = worker.read_envelope(attempt.stream_path, attempt.request.schema_path)
            attempt.result_journaled = True
            self.say("  ticket %d: carrying the result its worker returned before the restart" % attempt.id)
        elif attempt.tail.result is not None or self._alive(attempt):
            self._journal_resumed(attempt, replay.READOPTED)
            attempt.adopted = True
            self.say("  ticket %d: re-adopted its worker (pid %s)" % (attempt.id, attempt.pid))
        else:
            self._died(attempt, session)

    def _died(self, attempt, session):
        """A session that died without its result: resumed by session id, or relaunched when it had none.

        Either one waits, like any session that needs a model, while the run is paused or stopping.
        """
        if attempt.session_id:
            message = RESUME_DIED
            previous = attempt.run_dir / "prompt.md" if session.kind == "resume" and attempt.run_dir else None
            if previous is not None and previous.is_file():
                message += RESUME_DIED_MESSAGE % previous.read_text(encoding="utf-8").strip()
            attempt.want = _Want(replay.WORKER_DIED, message)
            doing = "its worker died; resuming session %s" % attempt.session_id
        else:
            attempt.want = _Want(RELAUNCH)
            doing = "its worker died before its session started; relaunching it"
        self.flight[attempt.id] = attempt
        started = self._start_wanted(attempt)
        self.say("  ticket %d: %s%s" % (attempt.id, doing, "" if started else " once the run may launch again"))

    def _adopted_returned(self, attempt):
        """Whether a re-adopted session has returned; a dead one without a result is resumed or relaunched.

        The launcher stops the sessions it started at their budget, and a re-adopted worker is nobody's
        child, so the conductor holds it to the same budget (decision 3): past `max_minutes` it is sent
        SIGTERM, then SIGKILL if it outlasts `STOP_WAIT_S`, and once it is gone its session is resumed
        once with "you ran out of time".
        """
        attempt.tail.read()
        if attempt.tail.result is not None:
            attempt.envelope = worker.read_envelope(attempt.stream_path, attempt.request.schema_path)
            return True
        if self._alive(attempt):
            if attempt.terminated_at is None and self._over_budget(attempt):
                worker.terminate(attempt.pid, self._attempt_dir(attempt))
                attempt.terminated_at = time.monotonic()
                self.say("  ticket %d: its re-adopted worker ran past its budget of %s minute(s); sent it SIGTERM"
                         % (attempt.id, attempt.tier.max_minutes))
            elif attempt.terminated_at is not None and time.monotonic() - attempt.terminated_at > STOP_WAIT_S:
                worker.terminate(attempt.pid, self._attempt_dir(attempt), hard=True)
            return False
        attempt.adopted = False
        if attempt.terminated_at is not None and attempt.session_id:
            attempt.want = _Want(TIMEOUT, RESUME_TIMEOUT % attempt.tier.max_minutes)
            self.flight[attempt.id] = attempt
            started = self._start_wanted(attempt)
            self.say("  ticket %d: resuming session %s out of time%s"
                     % (attempt.id, attempt.session_id, "" if started else " once the run may launch again"))
        else:
            self._died(attempt, replay.Session("launch" if attempt.run_dir == self._attempt_dir(attempt) else "resume"))
        return False

    def _over_budget(self, attempt):
        """Whether a re-adopted session has run longer than its tier's `max_minutes`."""
        started = _parse_ts(attempt.started_at)
        limit = attempt.tier.max_minutes if attempt.tier is not None else None
        if started is None or not limit:
            return False
        return (datetime.now(timezone.utc) - started).total_seconds() > limit * 60

    def _alive(self, attempt):
        return attempt.pid is not None and worker.pid_alive(attempt.pid, self._attempt_dir(attempt))

    def _attempt_dir(self, attempt):
        return worker.session_dir(self.project, attempt.id, attempt.number)

    def _prepare(self, attempt):
        """The worktree, the prompt, and the request an attempt taken over needs for its next session."""
        self._add_worktree(attempt)
        attempt.prompt = self._prompt(attempt)
        attempt.request = self._request(attempt, attempt.prompt)

    def _session_path(self, attempt, session):
        """The directory a session wrote to: the attempt's own for a launch, its `resume-<k>` for a resume.

        A resume's directory is the one whose process started after the journal named the resume,
        which `env.json` records; None when no process ever started for it.
        """
        base = self._attempt_dir(attempt)
        if session.kind == "launch":
            return base
        numbered = []
        for candidate in base.glob("resume-*"):
            suffix = candidate.name.split("-", 1)[1]
            if suffix.isdigit():
                numbered.append((int(suffix), candidate))
        for _, candidate in sorted(numbered, reverse=True):
            started = _session_started(candidate)
            if started is None:
                continue
            if session.ts and started >= session.ts:
                return candidate
            break
        return None

    def _poll(self, result):
        """Wave step 3: journal the sessions that began, carry the ones that returned, start what waits.

        One attempt's unexpected exception does not abandon the others: every attempt is looked at,
        and then the first such exception is raised again.
        """
        escaped = None
        for identifier in sorted(self.flight):
            attempt = self.flight[identifier]
            try:
                self._journal_session(attempt)
                if attempt.running:
                    continue
                if attempt.want is not None:
                    if attempt.want.stage != INTEGRATE:
                        self._start_wanted(attempt)
                        continue
                    if self._holds_launches():
                        continue
                    attempt.want = None  # the integration it waited for may launch its integrator now

                if attempt.adopted and not self._adopted_returned(attempt):
                    continue
                self._carry(attempt, result)
            except Exception as failure:  # not one of the two a ticket can be failed on
                self.flight.pop(identifier, None)
                escaped = failure if escaped is None else escaped
        if escaped is not None:
            raise escaped

    def _carry(self, attempt, result):
        """What a returned session came to, counted into the wave; nothing expected raises out."""
        if attempt.thread is not None:
            attempt.thread.join()
        outcome = "failed"
        try:
            if attempt.failure is not None:
                raise attempt.failure
            if attempt.envelope is None:
                raise ConductorError("the worker thread ended without a result and without an error")
            attempt.session_id = attempt.session_id or attempt.envelope.session_id
            self._journal_session(attempt)
            outcome = self._advance(attempt)
        except (ValueError, OSError) as failure:  # a launch, a ticket file, or a git step
            self._fail(attempt, str(failure), "needs_human")
        finally:
            # An integration left waiting for the run to allow model work is counted by the wave that concludes it.
            if attempt.started and not attempt.integrating:
                result.outcomes += 1
        if outcome == "session":
            self.flight[attempt.id] = attempt
            return
        self.flight.pop(attempt.id, None)
        result.findings += attempt.findings
        {"done": result.done, "running": result.running}.get(outcome, result.failed).append(attempt.id)

    def _journal_session(self, attempt):
        """`ticket_session`, once the stream's `system/init` says which session this is (decision 3)."""
        if attempt.session_journaled:
            return
        session_id = model = None
        if attempt.tail is not None:
            attempt.tail.read()
            session_id, model = attempt.tail.session_id, attempt.tail.model
        if session_id is None and attempt.envelope is not None:
            session_id, model = attempt.envelope.session_id, attempt.envelope.model
        if session_id is None:
            return
        attempt.session_id, attempt.session_journaled = session_id, True
        self.ledger.append_event(TICKET_SESSION, {
            "ticket": attempt.id, "attempt": attempt.number, "session_id": session_id, "model": model,
        }, ticket=attempt.id, session_id=session_id)
        self.say("  ticket %d session %s (%s)" % (attempt.id, session_id, model or "an unnamed model"))

    def _begin(self, attempt, entry):
        """Everything one launch needs: the role, the tier, the worktree, the prompt, the request.

        This is the serial half of a launch. Two workers may run at once but their worktrees are
        added one after another, because `git worktree add` writes the repository the other
        launches are reading, and both say their line in pick order rather than interleaved.
        """
        attempt.role = worker.read_role(attempt.ticket["role"], self.harness_root, self.project)
        attempt.difficulty = entry.get("difficulty", attempt.ticket["difficulty"])
        attempt.tier = tier_for(self.policy, attempt.difficulty, attempt.ticket.get("budget"))
        self._add_worktree(attempt)
        self._write_ticket(attempt, "running")
        attempt.prompt = self._prompt(attempt)
        attempt.request = self._request(attempt, attempt.prompt)
        self.say("wave %d: ticket %d %s (%s, %s %s, attempt %d)" % (
            self.number, attempt.id, attempt.ticket["title"], attempt.role.name,
            attempt.tier.model, attempt.tier.effort, attempt.number))

    def _prompt(self, attempt):
        """The prompt of decision 3; a locator resolves in the worktree first, then in the project."""
        return worker.assemble_prompt(
            attempt.ticket, attempt.role,
            roots=(attempt.worktree, self.project),
            max_chars=attempt.tier.context_chars,
            budget={"max_turns": attempt.tier.max_turns, "max_minutes": attempt.tier.max_minutes},
            consult_max=(self.policy.get("consultant") or {}).get("max_questions_per_ticket", worker.CONSULT_MAX),
        )

    def _request(self, attempt, prompt):
        """The `LaunchRequest` of decision 3: the role's tools, the rendered guards, both add-dirs."""
        run_dir = worker.session_dir(self.project, attempt.id, attempt.number)
        settings = gates.write_worker_settings(run_dir / "settings.json", self.harness_root)
        return worker.LaunchRequest(
            role=attempt.role.name,
            model=attempt.tier.model,
            effort=attempt.tier.effort,
            prompt=prompt.text,
            agent_json=attempt.role.agent_json(attempt.tier.model, attempt.tier.effort, attempt.tier.max_turns),
            allowed_tools=list(attempt.role.allowed_tools),
            disallowed_tools=list(attempt.role.disallowed_tools),
            settings_path=settings,
            add_dirs=[str(self.harness_root), str(self.project)],
            cwd=attempt.worktree,
            env=worker.session_env(self.project, attempt.id, attempt.number, attempt.ticket["touches"],
                                   harness_root=self.harness_root),
            schema_path=self.harness_root / "schemas" / ((attempt.role.output_schema or "result") + ".json"),
            max_minutes=attempt.tier.max_minutes,
        )

    def _journal_launch(self, attempt, started):
        attempt.started = True
        self.ledger.append_event(TICKET_LAUNCHED, {
            "ticket": attempt.id, "attempt": attempt.number, "role": attempt.role.name,
            "model": attempt.tier.model, "effort": attempt.tier.effort,
            "skills": list(attempt.ticket.get("skills") or []),
            "worktree": str(attempt.worktree), "pid": started.pid,
            "context_chars": attempt.prompt.context_chars, "prompt_sha256": attempt.prompt.sha256,
        }, ticket=attempt.id)

    # --- the worker outcome (BRIEF 9.1) ---

    def _advance(self, attempt):
        """Carry a returned session through the outcome (BRIEF 9.1): `done`, `running`, `failed`, or `session`.

        `attempt.stage` is the gate the session answers. A launch's result is validated and acted
        on, and an invalid one is resumed once with the error; the machine acceptance runs in the
        worktree, and a failure is resumed once with the output. A session answering one of those
        resumes continues from its gate, which is also where a restarted conductor picks an attempt
        up. `session` means a new session started, or waits to, and the attempt stays in flight.
        """
        if not attempt.result_journaled:
            self._journal_result(attempt)
            attempt.result_journaled = True
        if attempt.integrating:
            attempt.integrating = False
            return self._finish(attempt)
        problem = self._invalid(attempt)
        if attempt.stage == ACCEPTANCE_FAILED:
            if problem is not None:
                self._fail(attempt, "the resumed session returned no usable result: %s" % problem, "tier_up")
                return "failed"
            if not self._accept(attempt, "worktree", attempt.worktree)["pass"]:
                self._fail(attempt, "the machine acceptance still failed in the worktree after one resume", "tier_up")
                return "failed"
        else:
            if problem is not None:
                if attempt.stage in (INVALID_RESULT, TIMEOUT):
                    self._fail(attempt, "the result was still unusable after one resume: %s" % problem, "tier_up")
                    return "failed"
                return self._want_resume(attempt, INVALID_RESULT, RESUME_INVALID % problem)
            carried = self._act_on(attempt)
            if carried != "done":
                return carried
            record = self._accept(attempt, "worktree", attempt.worktree)
            if not record["pass"]:
                return self._want_resume(attempt, ACCEPTANCE_FAILED, RESUME_ACCEPTANCE % _failures(record["results"]))
        return self._finish(attempt)

    def _finish(self, attempt):
        """The branch's commits integrated and the ticket closed: `done`, `failed`, or `session` while the integrator waits."""
        self._stop_integrator(attempt)
        if not self._committed(attempt):
            return "failed"
        outcome = self._integrate(attempt)
        if outcome == "done":
            self._close(attempt)
        return outcome

    def _invalid(self, attempt):
        """Why the envelope is not a result the conductor can act on, or None when it is one."""
        if attempt.envelope is None:
            return "the worker was never launched"
        if not attempt.envelope.valid:
            return "; ".join(attempt.envelope.errors) or "the session returned no structured result"
        returned = attempt.result.get("ticket_id")
        if returned != attempt.id:
            return "the result carries ticket_id %r, and this is ticket %d" % (returned, attempt.id)
        return None

    def _journal_result(self, attempt):
        envelope = attempt.envelope
        self.ledger.append_event(TICKET_RESULT, {
            "ticket": attempt.id, "attempt": attempt.number, "session_id": attempt.session_id,
            "status": attempt.result.get("status"), "turns": envelope.num_turns,
            "duration_ms": envelope.duration_ms, "usage": envelope.usage,
            "permission_denials": envelope.permission_denials, "valid": self._invalid(attempt) is None,
        }, ticket=attempt.id, session_id=attempt.session_id)

    def _want_resume(self, attempt, stage, message):
        """Spend a gate's one resume (BRIEF 9.1): now, or as soon as the run may start model work."""
        if not attempt.session_id:
            self._fail(attempt, "there is no session id to resume: %s"
                       % "; ".join(attempt.envelope.errors or ["the session never started"]), "tier_up")
            return "failed"
        attempt.want = _Want(stage, message)
        self._start_wanted(attempt)
        return "session"

    def _start_wanted(self, attempt):
        """Start the session an attempt waits for, unless the run holds model work; returns whether it did."""
        if attempt.want is None or attempt.want.stage == INTEGRATE or self._holds_launches():
            return False  # an integration is carried again by `_poll`, not started as a session
        want, attempt.want = attempt.want, None
        if want.stage == RELAUNCH:
            self._journal_resumed(attempt, replay.WORKER_DIED)
            attempt.started = attempt.session_journaled = False
            attempt.tail = None
            self._run_session(attempt, "launch")
        else:
            self._journal_resumed(attempt, want.stage)
            if want.stage in replay.GATES:
                attempt.stage, attempt.resumed = want.stage, True
            self._run_session(attempt, "resume", want.message)
        attempt.begun.wait()
        return True

    def _journal_resumed(self, attempt, reason):
        """`ticket_resumed` for the attempt's session, with the reason decision 2's table gives it."""
        self.ledger.append_event(TICKET_RESUMED, {
            "ticket": attempt.id, "attempt": attempt.number, "session_id": attempt.session_id, "reason": reason,
        }, ticket=attempt.id, session_id=attempt.session_id)

    def _act_on(self, attempt):
        """What the result's own status asks for: `done`, `running`, or `failed` for the wave's count.

        The status is read before the acceptance is run, because only the worker can report that it
        is blocked or that it needs a person, and a ticket in either state must not spend its one
        resume on gates that were never going to pass.
        """
        outside = attempt.result.get("touched_outside_declared") or []
        blocked_on = attempt.result.get("blocked_on")
        if outside or blocked_on:
            path = ", ".join(outside) if outside else blocked_on
            self._write_ticket(attempt, "blocked", attempt.result)
            self.ledger.append_event(TICKET_BLOCKED, {"ticket": attempt.id, "path": path}, ticket=attempt.id)
            self.say("  ticket %d is blocked on %s; the planner re-cuts it" % (attempt.id, path))
            return "failed"
        status = attempt.result.get("status")
        if status == "done":
            return "done"
        summary = (attempt.result.get("summary") or "").strip()
        if status == "running":
            # Decision 5: a running result records its job ids and leaves the ticket running for
            # the poller. Until ticket 17 builds one, this run simply has nothing left to advance.
            self._write_ticket(attempt, "running", attempt.result)
            self.say("  ticket %d left job(s) running (%s); the poller arrives with ticket 17"
                     % (attempt.id, ", ".join(attempt.result.get("jobs") or []) or "none named"))
            return "running"
        if status == "failed":
            self._fail(attempt, summary or "the worker reported a failure and left no summary",
                       self._next_step(attempt))
        elif status == "needs_human":
            self._needs_human(attempt, summary or "the worker asked for a person and left no question")
        else:
            self._fail(attempt, "the result carries the status %r, which the conductor does not act on"
                       % (status,), "needs_human")
        return "failed"

    def _holds_launches(self):
        """Whether this wave may start no session that needs a model: the owner paused, or the run is stopping."""
        return self.view.paused_by_owner or self._stop_requested() is not None

    def _stop_requested(self):
        """The stop this run is to apply, as a `_Stop`, or None.

        A stop given to this run, or a `switched` that took the project away, which drains: the
        workers running are waited for and nothing new starts (decision 1, one active project).
        """
        stop, switched = self.view.stop, self.view.switched
        away = bool(switched) and switched.get("from") == str(self.project) and switched.get("to") != str(self.project)
        if stop is None and not away:
            return None
        drain = True if stop is None else stop["drain"]
        return _Stop(drain, "switched" if away or (stop or {}).get("switch_to") else "stopped")

    # --- what other processes asked for (decision 5, wave step 1) ---

    def _apply_controls(self, arrived, first):
        """Take in the control events and feedback the journal gained, and act on the ones that act here.

        At the first wave the journal was read from byte zero, so only what arrived after the last
        run ended is said aloud; what an earlier conductor already said is not said again. A stop
        acts in `_end`, at the close of the wave; a cancel, a rerun, and an answer act here.
        """
        if first:
            ends = [index for index, event in enumerate(arrived) if event.get("event") == RUN_ENDED]
            arrived = arrived[ends[-1] + 1:] if ends else arrived
        for event in arrived:
            self._say_arrival(event)
        for identifier in sorted(self.view.cancels):
            self._end_ticket(identifier, "cancel", self.view.cancels[identifier])
        for identifier in sorted(self.view.reruns):
            self._end_ticket(identifier, "rerun", self.view.reruns[identifier])
        self._tail()  # what the cancels and the reruns just journaled, before the answers are read
        self._apply_answers()

    def _apply_answers(self):
        """Wave step 4: an answered decision ticket is done, and an answer written in its file is the owner's.

        A `decision` event answers a ticket, from `wayline answer`, the dashboard, or a session. An
        answer a person wrote into the ticket's `## Answer` section is journaled here as theirs,
        and it wins over the answer the journal held, because the file is where a person answers
        (decision 2). Nothing new is journaled for the ticket's closing: the `decision` is the record.
        """
        for ticket in tickets.read_tickets(self.project):
            if ticket["kind"] != tickets.DECISION:
                continue
            _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(ticket))
            written = tickets.answer_section(body)
            known = self.view.answers.get(ticket["id"])
            if written is not None and (known is None or str(known.get("answer") or "").strip() != written):
                known = self.ledger.append_event(DECISION, {
                    "ticket": ticket["id"], "answer": written, "decided_by": "human", "rationale": None, "confidence": None,
                }, ticket=ticket["id"])["payload"]
                self.say("  ticket %d: the answer written in its file is journaled as the owner's" % ticket["id"])
            if known is not None and ticket["status"] not in tickets.SATISFIED + ("parked",):
                self._set_status(ticket["id"], "done")
                self.say("  ticket %d answered by the %s: %s" % (ticket["id"], known.get("decided_by"), known.get("answer")))

    def _say_arrival(self, event):
        payload = event.get("payload") or {}
        if event.get("event") == FEEDBACK:
            self.say("  feedback %s (%s) waits for the evolve loop" % (payload.get("id"), payload.get("source")))
            return
        say = ARRIVALS.get(payload.get("command")) if event.get("event") == CONTROL else None
        if say is not None:
            self.say("  " + say(payload.get("args") if isinstance(payload.get("args"), dict) else {}, payload.get("by")))

    def _terminate(self, attempt):
        """End one session, this process's child or a re-adopted worker, and wait for its thread."""
        if attempt.pid is not None and (attempt.adopted or attempt.running):
            worker.terminate(attempt.pid, self._attempt_dir(attempt))
        if attempt.thread is not None:
            attempt.thread.join(STOP_WAIT_S)
            if attempt.running and attempt.pid is not None:
                worker.terminate(attempt.pid, self._attempt_dir(attempt), hard=True)
                attempt.thread.join(STOP_WAIT_S)

    def _end_ticket(self, identifier, command, by):
        """A `cancel` parks the ticket and a `rerun` opens it again, ending its running worker first.

        A rerun of an answered decision ticket asks its question again, so the answer's heading is
        renamed and the file no longer closes the ticket at the next wave.
        """
        attempt = self.flight.get(identifier)
        try:
            ticket, _ = self._ticket(identifier)
        except ConductorError:
            ticket = None
        status = ticket["status"] if ticket else None
        if ticket is None or (command == "cancel" and status in ("done", "accepted", "parked")) \
                or (command == "rerun" and status == "open" and attempt is None):
            if (command, identifier) not in self.declined:
                self.declined.add((command, identifier))
                self.say("  a %s of ticket %s changes nothing: %s" % (command, identifier, "no such ticket" if ticket is None else "it is %s" % status))
            return
        if attempt is not None:
            self._terminate(attempt)
            self.flight.pop(identifier, None)
        if command == "cancel":
            self.ledger.append_event(TICKET_CANCELLED, {"ticket": identifier, "by": by}, ticket=identifier)
            self._set_status(identifier, "parked")
            self.say("  ticket %d cancelled by %s; it is parked" % (identifier, by))
        else:
            self.ledger.append_event(TICKET_RERUN, {"ticket": identifier, "by": by}, ticket=identifier)
            ticket, body = self._ticket(identifier)
            tickets.write_ticket(self.ledger, dict(ticket, status="open"), tickets.retire_answer(body))
            self.say("  ticket %d rerun by %s; it is open for a new attempt" % (identifier, by))

    def _accept(self, attempt, where, cwd):
        """Run the ticket's machine acceptance in `cwd` and journal it under the label `where`."""
        commands = (attempt.ticket.get("acceptance") or {}).get("machine") or []
        record = gates.acceptance_file_record(gates.run_machine_acceptance(commands, cwd, self._timeout()), where)
        self.ledger.append_event(ACCEPTANCE, {
            "ticket": attempt.id, "attempt": attempt.number, "where": where,
            "pass": record["pass"], "results": record["results"],
        }, ticket=attempt.id, session_id=attempt.session_id)
        self.say("  acceptance (%s): %s" % (where, "pass" if record["pass"] else "fail"))
        return record

    def _timeout(self):
        timeout = self.policy.get("acceptance_timeout_s", 600)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ConductorError("policy.acceptance_timeout_s is %r; it is a positive number of seconds"
                                 % (timeout,))
        return timeout

    def _committed(self, attempt):
        """The branch is what gets integrated, so work the worker left uncommitted is not a result.

        Without this the rebase below would refuse a worktree with tracked changes and the ticket
        would be reported as a conflict it never had, and an uncommitted new file would survive
        every acceptance in the worktree and fail only on `main`, after the fast-forward.

        Tracked changes always count. An untracked file counts when it lies in the ticket's touch
        set, which is where this ticket's work belongs; untracked noise elsewhere (a `__pycache__`
        the acceptance commands just made) is not the worker's doing and is not held against it.
        """
        dirty = [path for status, path in porcelain_entries(self._git(attempt.worktree, "status", "--porcelain", "-z").stdout)
                 if status != "??" or _in_touch_set(path, attempt.ticket["touches"])]
        if not dirty:
            return True
        self._fail(attempt, "the worker left %d path(s) uncommitted in its worktree (%s); the conductor "
                   "integrates the branch, not the working tree" % (len(dirty), ", ".join(sorted(dirty)[:5])),
                   self._next_step(attempt))
        return False

    # --- the integration protocol ---

    def _integrate(self, attempt):
        """The integration protocol of decision 5 for one ticket: `done`, `failed`, or `session`.

        Integrations are carried one at a time on the conductor's thread, and every git step that
        moves a branch or `main` holds the ledger lock, the lock any other process that writes the
        ledger takes. In the worktree, `git rebase main`; on a conflict the rebase is aborted and the
        integrator is launched once, which finishes the rebase itself (a commit on top of the old
        branch cannot help: the next rebase replays the commit that conflicted). The conductor then
        rebases again, and a second conflict fails the ticket with `next: split`. The integrator's
        session and every acceptance run outside the lock, because either may take minutes and
        `wayline answer`, `wayline consult`, and the dashboard write the ledger meanwhile.

        What the integrator hands back is checked, not trusted: the worktree must still be on the
        ticket branch, and the branch must still carry a change of its own and no path it did not
        change before. An integrator a restarted conductor finds already launched for this attempt
        is not launched again.

        A conflict met while the run holds launches leaves the integration waiting in flight
        (`session`); the wave after the hold ends carries it again from the rebase.

        After a clean rebase the acceptance reruns on the branch (`where: rebased`), `main` is
        fast-forwarded, the acceptance reruns there (`where: main`), and `integrated` records the
        commit and who resolved the conflict.
        """
        spent = self._integrator_spent(attempt)
        resolved_by = INTEGRATOR if spent else "none"
        problem = self._off_branch(attempt)
        if problem is not None:
            self._fail(attempt, problem, "split" if spent else self._next_step(attempt))
            return "failed"
        before = self._branch_paths(attempt)
        with self.ledger.lock():
            conflict = self._rebase(attempt)
        if conflict is not None and spent:
            self._fail(attempt, "rebasing %s onto main conflicts in %s, and the integrator was already launched for "
                       "this attempt before the conductor restarted" % (BRANCH % attempt.id, ", ".join(conflict.paths)
                                                                        or "a path git did not name"), "split")
            return "failed"
        if conflict is not None:
            if not conflict.paths:
                self._fail(attempt, "rebasing %s onto main failed and git named no conflicting path, so there is "
                           "nothing an integrator could resolve: %s" % (BRANCH % attempt.id, conflict.output), "split")
                return "failed"
            if self._holds_launches():
                attempt.integrating, attempt.want = True, _Want(INTEGRATE)
                self.say("  ticket %d: rebasing onto main conflicts in %s; the integrator waits until the run may launch again"
                         % (attempt.id, ", ".join(conflict.paths)))
                return "session"
            # Every path both sides changed may conflict, not only the one the rebase stopped on first.
            touches = sorted(set(conflict.paths) | (before & self._main_paths(attempt)))
            told = self._launch_integrator(attempt, conflict, touches)
            resolved_by = INTEGRATOR
            with self.ledger.lock():
                again = self._rebase(attempt)
            if again is not None:
                self._fail(attempt, "rebasing %s onto main conflicted in %s; the integrator %s; the rebase after it "
                           "still fails%s" % (BRANCH % attempt.id, ", ".join(conflict.paths), told,
                                              " in " + ", ".join(again.paths) if again.paths else ": " + again.output),
                           "split")
                return "failed"
            problem = self._off_branch(attempt) or _changed_by_integrator(before, self._branch_paths(attempt))
            if problem is not None:
                self._fail(attempt, "the integrator %s; %s" % (told, problem), "split")
                return "failed"
        if not self._accept(attempt, "rebased", attempt.worktree)["pass"]:
            self._fail(attempt, "the machine acceptance failed after the rebase onto main", self._next_step(attempt))
            return "failed"
        with self.ledger.lock():
            merge = self._git(self.project, "merge", "--ff-only", BRANCH % attempt.id, ok=None)
            commit = attempt.commit = self._head(self.project) if merge.returncode == 0 else None
        if merge.returncode != 0:
            self._fail(attempt, "main could not be fast-forwarded to %s: %s"
                       % (BRANCH % attempt.id, (merge.stderr or merge.stdout).strip()), "split")
            return "failed"
        if not self._accept(attempt, "main", self.project)["pass"]:
            self._fail(attempt, "the machine acceptance failed on main after the fast-forward to %s; main "
                       "carries the commit and a person has to look" % commit[:12], "needs_human")
            return "failed"
        if self.view.integrated.get(attempt.id) != commit:  # journaled already by a conductor that died after it
            self.ledger.append_event(INTEGRATED, {"ticket": attempt.id, "commit": commit, "resolved_by": resolved_by},
                                     ticket=attempt.id)
        self.say("  integrated %s into main as %s%s" % (BRANCH % attempt.id, commit[:12],
                                                        " (resolved by the integrator)" if resolved_by == INTEGRATOR else ""))
        return "done"

    def _rebase(self, attempt):
        """`git rebase main` in the worktree: None when it is clean, else the `_Conflict`, with no rebase left in progress.

        The conflicting files are read before the abort, because the markers exist only while the
        rebase is stopped. A rebase an integrator left in progress fails here as well, and is aborted.
        """
        rebased = self._git(attempt.worktree, "rebase", MAIN, ok=None)
        if rebased.returncode == 0:
            return None
        paths = [line for line in self._git(attempt.worktree, "diff", "--name-only", "--diff-filter=U",
                                            ok=None).stdout.split("\n") if line.strip()]
        markers = [(path, _conflicted_text(attempt.worktree / path)) for path in paths]
        self._git(attempt.worktree, "rebase", "--abort", ok=None)
        return _Conflict(paths, markers, (rebased.stderr or rebased.stdout).strip())

    def _off_branch(self, attempt):
        """Why the worktree has no ticket branch checked out to integrate, or None when it has."""
        head = self._git(attempt.worktree, "symbolic-ref", "--quiet", "--short", "HEAD", ok=None)
        if head.returncode == 0 and head.stdout.strip() == BRANCH % attempt.id:
            return None
        return "the worktree of ticket %d is on %s, not %s, so the branch it would integrate is not the one it worked on" % (
            attempt.id, head.stdout.strip() or "a detached HEAD", BRANCH % attempt.id)

    def _branch_paths(self, attempt):
        """The paths the ticket branch changes since it left `main`."""
        return _names(self._git(self.project, "diff", "--name-only", "-z", "%s...%s" % (MAIN, BRANCH % attempt.id)).stdout)

    def _main_paths(self, attempt):
        """The paths `main` changed since the ticket branch left it."""
        return _names(self._git(self.project, "diff", "--name-only", "-z", "%s...%s" % (BRANCH % attempt.id, MAIN)).stdout)

    def _integrator_dir(self, attempt):
        return self._attempt_dir(attempt) / INTEGRATOR

    def _integrator_spent(self, attempt):
        """Whether this attempt's one integrator was already launched: its session left a stream."""
        return (self._integrator_dir(attempt) / "stream.jsonl").is_file()

    def _stop_integrator(self, attempt):
        """An integrator a dead conductor launched: ended if it still runs, and the rebase it was in aborted.

        Nothing but the session directory records it, because its session is not journaled; a
        restarted conductor that carries the attempt would otherwise rebase the worktree under it.
        """
        if not self._integrator_spent(attempt) or not (attempt.worktree / ".git").exists():
            return
        run_dir = self._integrator_dir(attempt)
        pid = _read_pid(run_dir)
        if pid is not None and worker.pid_alive(pid, run_dir):
            worker.terminate(pid, run_dir)
            deadline = time.monotonic() + STOP_WAIT_S
            while worker.pid_alive(pid, run_dir) and time.monotonic() < deadline:
                time.sleep(0.2)
            if worker.pid_alive(pid, run_dir):
                worker.terminate(pid, run_dir, hard=True)
            self.say("  ticket %d: stopped the integrator (pid %d) a conductor launched before the restart" % (attempt.id, pid))
        self._git(attempt.worktree, "rebase", "--abort", ok=None)  # nothing to abort is not an error here

    def _launch_integrator(self, attempt, conflict, touches):
        """Launch the integrator once, in the worktree, with `touches` as its touch set; what it came to, in words.

        The session runs to its end on this thread, since nothing behind this ticket can integrate
        before it. Nothing about it is journaled as a `ticket_*` event: the attempt a restart
        replays is the worker's, and an integrator's session id there would be resumed as the
        worker's. The ticket file records the session instead, `integrated` records that the
        integrator resolved the conflict, and its session directory is what a restart finds.
        """
        told, session = None, None
        try:
            role = worker.read_role(INTEGRATOR, self.harness_root, self.project)
            tier = self._integrator_tier(attempt)
            run_dir = self._integrator_dir(attempt)
            prompt = worker.integrator_prompt(attempt.ticket, role, conflict.markers, touches=touches,
                                              max_chars=tier.context_chars,
                                              budget={"max_turns": tier.max_turns, "max_minutes": tier.max_minutes})
            env = worker.session_env(self.project, attempt.id, attempt.number, touches, harness_root=self.harness_root)
            env.update(WAYLINE_RUN=str(run_dir), TICKET_ACCEPTANCE_FILE=str(run_dir / "acceptance.json"),
                       GIT_EDITOR="true")  # `git rebase --continue` opens no editor in a session with no terminal
            request = worker.LaunchRequest(
                role=role.name, model=tier.model, effort=tier.effort, prompt=prompt.text,
                agent_json=role.agent_json(tier.model, tier.effort, tier.max_turns),
                allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
                settings_path=gates.write_worker_settings(run_dir / "settings.json", self.harness_root),
                add_dirs=[str(self.harness_root), str(self.project)], cwd=attempt.worktree, env=env,
                schema_path=self.harness_root / "schemas" / ((role.output_schema or "result") + ".json"),
                max_minutes=tier.max_minutes,
            )
            self.say("  ticket %d: rebasing onto main conflicts in %s; launching the integrator (%s %s)"
                     % (attempt.id, ", ".join(conflict.paths), tier.model, tier.effort))
            envelope = worker.launch(request)
        except Exception as failure:  # a role, a prompt, a settings file, or the launch: the ticket is split, not the run
            told = "could not be launched (%s)" % failure
        else:
            session = "session `%s` on %s" % (envelope.session_id or "unknown", envelope.model or tier.model)
            result = envelope.structured_output if envelope.valid else None
            if result is None:
                told = "returned no usable result (%s)" % ("; ".join(envelope.errors) or "no structured output")
            else:
                told = "returned %s: %s" % (result.get("status"), (result.get("summary") or "").strip() or "no summary")
        self.say("  ticket %d: the integrator %s" % (attempt.id, told))
        attempt.body = tickets.with_result_note(attempt.body, [
            "**Integrator** (attempt %d), %s, on %s: it %s." % (
                attempt.number, session or "no session", ", ".join("`%s`" % path for path in touches), told),
        ])
        tickets.write_ticket(self.ledger, attempt.ticket, attempt.body)
        return told

    def _integrator_tier(self, attempt):
        """`policy.roles.integrator`'s model and effort, with the ticket's own budget and the model's context cap."""
        entry = (self.policy.get("roles") or {}).get(INTEGRATOR) or {}
        model, effort = entry.get("model") or attempt.tier.model, entry.get("effort") or attempt.tier.effort
        caps = (self.policy.get("context_pack") or {}).get("max_chars") or {}
        return Tier(model=model, effort=effort, max_turns=attempt.tier.max_turns, max_minutes=attempt.tier.max_minutes,
                    context_chars=caps.get(model, attempt.tier.context_chars))

    # --- closing the ticket ---

    def _close(self, attempt):
        """The findings, the status, `ticket_done`, and the worktree the ticket no longer needs."""
        for index, finding in enumerate(attempt.result.get("findings") or [], start=1):
            record = {
                "id": "t%d-a%d-f%d" % (attempt.id, attempt.number, index),
                "ticket": attempt.id,
                "text": finding["text"],
                "provenance": finding["provenance"],
                "negative": bool(finding.get("negative", False)),
            }
            if record["id"] in self.view.findings:
                continue  # filed before a restart
            self.ledger.append_record(FINDINGS, record)
            self.ledger.append_event(FINDING, record, ticket=attempt.id)
            attempt.findings += 1
        self._write_ticket(attempt, "done", attempt.result)
        self.ledger.append_event(TICKET_DONE, {"ticket": attempt.id}, ticket=attempt.id)
        self._queue_verdicts(attempt)
        self._remove_worktree(attempt.id)
        self.say("  ticket %d done" % attempt.id)

    # --- the Type-B gate (decision 11) ---

    def _queue_verdicts(self, attempt):
        """Queue the verdicts this done ticket earned; nothing is launched from here.

        The queue is drained later in the wave, once every worker's outcome has been carried,
        because a verdict is model work like any other: it is paced with the rest, and it must not
        hold the integration of the tickets behind it.
        """
        outputs = attempt.result.get("outputs_written") or attempt.ticket.get("outputs") or []
        asks = gates.ticket_asks(
            attempt.ticket, attempt.difficulty, attempt.tier.model,
            tickets.relative_path(attempt.ticket), commit=attempt.commit, outputs=outputs,
        )
        if not asks:
            return
        self.verdicts.append(_Queued(attempt.id, attempt.number, asks))
        self.say("  ticket %d earned %d verdict(s): %s"
                 % (attempt.id, len(asks), ", ".join(ask.verdict_type for ask in asks)))

    def _drain_verdicts(self, result):
        """Take every queued verdict, ticket by ticket, and accept or fail each ticket.

        Pacing holds the whole queue rather than part of it: a ticket whose first verdict passed
        and whose second was never taken is neither accepted nor failed, and leaving one in that
        state across a window boundary is worse than leaving both for the next wave.
        """
        if not self.verdicts:
            return
        if schedule.holds_model_work(self.action):
            self.say("  %d ticket(s) wait for a verdict; pacing says %s"
                     % (len(self.verdicts), self.action))
            return
        queued, self.verdicts = self.verdicts, []
        for entry in queued:
            self._gate(entry, result)

    def _gate(self, entry, result):
        """One done ticket's verdicts, in order; every one of them has to pass before it is accepted."""
        for ask in entry.asks:
            try:
                verdict = gates.verdict_for(ask, project=self.project, harness_root=self.harness_root,
                                            policy=self.policy, ledger=self.ledger)
            except (ValueError, OSError) as failure:
                # A verdict nobody could take is not a verdict against the ticket. It keeps the
                # `done` its machine gates earned and is not accepted, which is what `wayline
                # status` shows and what holds any dependent of a difficulty-5 ticket.
                self.say("  ticket %d: the %s verdict could not be taken (%s); the ticket stays "
                         "done and unaccepted" % (entry.ticket, ask.verdict_type, failure))
                return
            self.say("  ticket %d: the %s verdict %s on %s (session %s)"
                     % (entry.ticket, ask.verdict_type, "passed" if verdict.passed else "failed",
                        verdict.model or "an unnamed model", verdict.session_id or "unknown"))
            if not verdict.passed:
                self._reject(entry, verdict)
                result.rejected.append(entry.ticket)
                return
        self._accept_ticket(entry, verdict)
        result.accepted.append(entry.ticket)

    def _accept_ticket(self, entry, verdict):
        """`done` to `accepted`: the one transition a passing quality verdict makes (decision 2)."""
        self._set_status(entry.ticket, "accepted", self._verdict_note(verdict))
        self.ledger.append_event(TICKET_ACCEPTED, {"ticket": entry.ticket}, ticket=entry.ticket)
        self.say("  ticket %d accepted" % entry.ticket)

    def _reject(self, entry, verdict):
        """A failed verdict: the ticket is failed with the findings as its failure output."""
        reason = REJECTED % (verdict.verdict_type, verdict.model or "verifier",
                             gates.findings_text(verdict.findings))
        self._set_status(entry.ticket, "failed", self._verdict_note(verdict))
        self.ledger.append_event(TICKET_FAILED, {
            "ticket": entry.ticket, "attempt": entry.attempt, "reason": reason, "next": "resume",
        }, ticket=entry.ticket, session_id=verdict.session_id)
        self.say("  ticket %d failed its %s verdict (next: resume)"
                 % (entry.ticket, verdict.verdict_type))

    def _verdict_note(self, verdict):
        """What a verdict has to say in the ticket file: who read it, on what, and what they found.

        The journal carries the same thing, but the ticket file is where a person looks and where
        the next attempt's prompt comes from, so a verdict that reached only the journal would
        have reached neither.
        """
        lines = ["**Verdict (%s): %s** by %s, session `%s`."
                 % (verdict.verdict_type, "passed" if verdict.passed else "failed",
                    verdict.model or "an unnamed model", verdict.session_id or "unknown")]
        if verdict.findings:
            lines.extend(["", gates.findings_text(verdict.findings)])
        return lines

    def _set_status(self, identifier, status, note=()):
        """Write one ticket's status, and any note, through the ledger, outside any attempt at it.

        The Type-B gate runs after the attempt was carried and its worktree removed, so there is
        no `_Attempt` left to write from and no new result to append.
        """
        ticket, body = self._ticket(identifier)
        if note:
            body = tickets.with_result_note(body, note)
        tickets.write_ticket(self.ledger, dict(ticket, status=status), body)

    def _next_step(self, attempt):
        """The rung of the escalation ladder this failure lands on: the one resume, if it is unspent."""
        return "tier_up" if attempt.resumed else "resume"

    def _fail(self, attempt, reason, next_step):
        """Journal the failure and leave the worktree and the branch for the attempt that follows."""
        self.ledger.append_event(TICKET_FAILED, {
            "ticket": attempt.id, "attempt": attempt.number, "reason": reason, "next": next_step,
        }, ticket=attempt.id, session_id=attempt.session_id)
        self._write_ticket(attempt, "failed", attempt.result)
        self.say("  ticket %d failed: %s (next: %s)" % (attempt.id, reason, next_step))

    def _needs_human(self, attempt, question):
        self.ledger.append_event(TICKET_NEEDS_HUMAN, {"ticket": attempt.id, "question": question},
                                 ticket=attempt.id)
        self._write_ticket(attempt, "needs_human", attempt.result)
        self.say("  ticket %d needs a person: %s" % (attempt.id, question))

    # --- the ticket file ---

    def _ticket(self, identifier):
        for ticket in tickets.read_tickets(self.project):
            if ticket["id"] == identifier:
                return ticket, tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(ticket))[1]
        raise ConductorError("no ticket in %s has id %s" % (tickets.tickets_dir(self.project), identifier))

    def _write_ticket(self, attempt, status, result=None):
        """The status and, once an attempt has a result, the `## Result` section (decision 2)."""
        attempt.ticket = dict(attempt.ticket, status=status)
        if result:
            attempt.body = tickets.with_result(attempt.body, attempt.number, result)
            for line in tickets.result_notes(result):
                self.say("  ticket %d %s" % (attempt.id, line))
        tickets.write_ticket(self.ledger, attempt.ticket, attempt.body)

    # --- worktrees and commits ---

    def _worktree(self, identifier):
        return self.project / WORKTREES / str(identifier)

    def _add_worktree(self, attempt):
        """`.worktrees/<id>` on `ticket/<id>` from `main`, reusing what an earlier attempt left."""
        branch = BRANCH % attempt.id
        if (attempt.worktree / ".git").exists():
            if self._git(attempt.worktree, "rev-parse", "--abbrev-ref", "HEAD", ok=None).stdout.strip() == branch:
                return attempt.worktree
            self._remove_worktree(attempt.id, branch=False)
        elif attempt.worktree.exists():
            raise ConductorError("%s exists and is not a worktree; remove it and run again" % attempt.worktree)
        self._git(self.project, "worktree", "prune")
        known = self._git(self.project, "rev-parse", "--verify", "--quiet",
                          "refs/heads/" + branch, ok=None).returncode == 0
        self._git(self.project, "worktree", "add", *([] if known else ["-b", branch]),
                  str(attempt.worktree), branch if known else MAIN)
        return attempt.worktree

    def _remove_worktree(self, identifier, branch=True):
        path = self._worktree(identifier)
        if path.exists():
            self._git(self.project, "worktree", "remove", "--force", str(path), ok=None)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        self._git(self.project, "worktree", "prune")
        if branch:
            self._git(self.project, "branch", "-D", BRANCH % identifier, ok=None)

    def _commit_ledger(self):
        """Commit what the wave wrote under `research/`, so `main` stays clean for the next fast-forward.

        The session directories of the attempts still in flight are left for a later wave. Their
        worker, or the thread waiting on it, is still writing there (`result.json`, the worker's
        `acceptance.json`), and a file renamed into place while `git add` reads the directory fails
        the whole add. The wave that carries an attempt commits its directory.
        """
        busy = [":(exclude)" + self._attempt_dir(attempt).relative_to(self.project).as_posix()
                for attempt in self.flight.values()]
        with self.ledger.lock():  # a commit to `main`, like the fast-forward of an integration
            self._git(self.project, "add", "--", RESEARCH, *busy)
            if self._git(self.project, "diff", "--cached", "--name-only", "--", HEARTBEAT_PATH).stdout.strip():
                # A project laid out before the heartbeat was ignored: keep the file out of the commit.
                self._git(self.project, "reset", "-q", "--", HEARTBEAT_PATH)
            if self._git(self.project, "diff", "--cached", "--quiet", "--", RESEARCH, ok=None).returncode == 0:
                return None
            self._git(self.project, "commit", "-q", "-m", LEDGER_COMMIT % self.number, "--", RESEARCH, *busy)
            return self._head(self.project)

    def _head(self, path):
        return self._git(path, "rev-parse", "HEAD").stdout.strip()

    def _git(self, cwd, *args, ok=(0,)):
        """One git command under the project's committer identity; `ok=None` hands back the exit code."""
        return _git_command(cwd, *args, identity=self._who(), ok=ok)

    def _who(self):
        """A committer identity, only when the project's repository has none of its own."""
        if self._who_args is None:
            done = _git_command(self.project, "config", "user.email", ok=None)
            self._who_args = () if done.stdout.strip() else IDENTITY
        return self._who_args


# --- the resume message and the touch set ---------------------------------------------------


def _session_started(run_dir):
    """When the session in `run_dir` started, as the launcher recorded it in `env.json`, or None."""
    try:
        return json.loads((Path(run_dir) / "env.json").read_text(encoding="utf-8")).get("started_at")
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def _parse_ts(value):
    """A journal timestamp (`ledger.now_ts`) as an aware datetime, or None when it is not one."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _conflicted_text(path):
    """A conflicting file as a stopped rebase left it, for the integrator's prompt; what git left instead when it is not text."""
    try:
        data = path.read_bytes()
    except OSError:
        return "(no file at this path in the stopped rebase: one side deleted it)\n"
    if b"\0" in data[:8000]:
        return "(a binary file of %d bytes; git cannot place conflict markers in it)\n" % len(data)
    return data.decode("utf-8", errors="replace")


def _names(text):
    """The paths `git diff --name-only -z` printed, as a set."""
    return {name for name in text.split("\0") if name}


def _changed_by_integrator(before, after):
    """Why a branch the integrator rebased is not the branch it was given, or None when it still is one."""
    if not after:
        return "the rebased branch carries no change of its own any more"
    extra = sorted(after - before)
    if extra:
        return "the rebased branch now changes %s, which the branch did not change before" % ", ".join(extra)
    return None


def _read_pid(run_dir):
    """The pid a backend wrote beside a session's stream, or None."""
    try:
        return int((Path(run_dir) / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError, TypeError):
        return None


def _failures(results):
    """The failing commands of an acceptance record, as the resume message quotes them."""
    failed = ["$ %s\n(exit %d)\n%s" % (result["cmd"], result["exit_code"], (result["tail"] or "").strip())
              for result in results or () if result["exit_code"] != 0]
    return "\n\n".join(failed) or "(no command reported a non-zero exit code)"


def _in_touch_set(path, touches):
    """Whether an untracked path lies in the ticket's touch set, as the touch-set guard reads one."""
    path = path.rstrip("/")
    for entry in touches or ():
        entry = str(entry).rstrip("/")
        if path == entry or path.startswith(entry + "/") or entry.startswith(path + "/"):
            return True
    return False


# --- the verb ---------------------------------------------------------------------------------

# The flags of decision 1's verb table that later tickets build, named so `run` can say which.
LATER = (
    ("detach", "--detach", "ticket 13 (the transient wayline-conductor unit)"),
    ("simulate_limit", "--simulate-limit", "ticket 10 (pacing and the pause)"),
    ("simulate_failure", "--simulate-failure", "ticket 38 (the stall and the escalation ladder)"),
)


def run_command(args):
    """`wayline run`: the conductor over the active project, or the one `--project` names."""
    parser = argparse.ArgumentParser(prog="wayline run",
                                     description="run the conductor over a project until its frontier is empty")
    parser.add_argument("--project", help="the project to run; the active one by default")
    parser.add_argument("--resume", action="store_true", help="say in run_started that this run resumes one (every run replays the journal)")
    parser.add_argument("--detach", action="store_true", help="run as the transient unit wayline-conductor (ticket 13)")
    parser.add_argument("--simulate-limit", metavar="S", help="pretend a usage limit was hit (ticket 10)")
    parser.add_argument("--simulate-failure", metavar="ID", help="pretend a ticket failed (ticket 38)")
    parser.add_argument("--max-waves", type=int, metavar="N", help="stop after N waves, whatever the frontier still holds")
    try:
        options = parser.parse_args(args)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 2
    for name, flag, owner in LATER:
        if getattr(options, name):
            print("wayline run: %s is not yet implemented; it arrives with %s" % (flag, owner), file=sys.stderr)
            return 2

    try:
        project = find_project(options.project)
        problems = refuse_to_start(project)
        harness = read_harness(project)
    except (ProjectError, ConductorError, ValueError, OSError) as failure:
        print("wayline run: %s" % failure, file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print("wayline run: %s" % problem, file=sys.stderr)
        return 2

    conductor = Conductor(project)
    print("run      %s (%s, radius %s)" % (project, harness.get("autonomy"), harness.get("radius")))
    try:
        waves = conductor.run(max_waves=options.max_waves, resume=options.resume)
    except (ConductorError, ValueError, OSError) as failure:
        print("wayline run: %s" % failure, file=sys.stderr)
        return 1
    done = [identifier for wave in waves for identifier in wave.done]
    failed = [identifier for wave in waves for identifier in wave.failed]
    running = [identifier for wave in waves for identifier in wave.running]
    accepted = [identifier for wave in waves for identifier in wave.accepted]
    rejected = [identifier for wave in waves for identifier in wave.rejected]
    print("%d wave(s), %d ticket(s) done, %d accepted, %d unfinished%s"
          % (len(waves), len(done), len(accepted), len(failed) + len(rejected),
             "; " + waves[-1].reason if waves and waves[-1].reason else ""))
    if rejected:
        # A rejected ticket reached `done` and was failed afterwards by its verdict, so it is in
        # neither the frontier nor the running set and nothing else here would mention it.
        print("ticket(s) %s were done and failed their quality verdict; the journal carries the findings"
              % ", ".join(str(identifier) for identifier in rejected))
    if running:
        print("ticket(s) %s left jobs running; nothing here can advance them until the job poller lands"
              % ", ".join(str(identifier) for identifier in running))
    return 1 if failed or rejected else 0
