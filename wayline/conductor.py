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
  between waves, waking when a session returns or another process appends to the journal. The limit
  holds at every moment and not only at the moment a wave picks (ticket 59): an attempt holds its
  worker slot while its session runs, while its result waits to be carried, and while it waits to
  start the session it wants, and a resume waits for a free slot as a launch does (`_busy`).
- Resume is start (ticket 09). `run` takes the heartbeat `research/conductor.json`, whose `flock`
  keeps a second conductor off the project, and rewrites it every wave. The first wave replays
  the journal from byte zero into a `replay.View`, reconciles the ticket files and `.worktrees/`
  with it, re-adopts a worker still running by its pid and stream, resumes a dead one by session
  id or relaunches it, carries a result no conductor carried, and queues again the verdicts a done
  ticket earned. Every later wave folds what the journal gained and applies the `control` events,
  answers, and feedback that other processes appended.
- One resume per gate, for an invalid result or a failed acceptance (BRIEF 9.1), and the rest of the
  escalation chain (ticket 38; by rung, ticket 61). Every failure journals `ticket_failed` with the step
  it goes to in `next`, and each wave takes every failed ticket up its step, in the order
  `policy.escalation.then` gives after the resume: `resume` resumes the failed attempt's session once
  with the failure output (a failed verdict and a failed job included), `split` has the planner replace
  it (`plan.cut_graph`, what `wayline plan --split` runs), `tier_up` opens the ticket again for a new
  attempt one rung up the rung ladder, and `needs_human` hands it to a person with a notification. The
  tier up comes before the split while the next rung is on the failed attempt's own model family, and
  the split comes first when the next rung is on Fable, so the scarce Fable week is spent only after the
  cheaper remedy (decision 16). A split that fails goes on to the tier up. A ticket a split cut is never
  split again, and a pinned ticket skips the tier up; a ticket already on the ladder's top rung has
  nowhere to climb, so its tier up is skipped as spent and it ends `needs_human` with `reason: top_rung`
  once the split has been tried. The step is read from the journal, so a restart takes the chain up where
  it stood, and a run does not end while a failed ticket still waits on a step. A kind whose attempts
  failed twice at one difficulty level has its default level raised one for the rest of the run
  (`difficulty_raised`), and the rung follows from the level, except for pinned tickets and never
  counting an attempt that fell back to Opus (decision 15); `ticket_launched` carries the difficulty and
  the rung an attempt launched at, and those failures are counted by the difficulty.
- The stall (ticket 38). A settling wave journals `wave`, and when the counter the replayed journal
  keeps reaches `policy.stall.waves` the conductor journals `stall` and has the planner re-cut the open
  tickets (`plan.cut_graph` with a replan, what `wayline plan --replan` runs), or, under radius
  `strict`, ends the run with `stall_strict` and renders `REPORT.md`. `wayline run --simulate-failure
  <id>` fails every acceptance of one ticket, so the owner can watch the whole ladder in minutes.
- The integration protocol (ticket 08), one ticket at a time under the ledger lock. A rebase
  conflict is aborted and the `integrator` role is launched once in the worktree, on the
  conflicting paths, to finish the rebase itself; the conductor's second rebase is the check, and
  a second conflict fails the ticket with `next: split`. The integrator is model work, so it waits
  while the run holds launches, and the attempt waits in flight with it.
- Pacing and the window pause (ticket 10, `wayline.pacing`). `run` reads `/usage` before its first
  wave, and every wave folds in the `rate_limit_event`s the workers' streams gained, so the action of
  wave step 8 follows the windows while the workers are still running; `pacing` is journaled when the
  reading changes. `stop`, a window pause, the owner's pause, and a stop hold every session that needs
  a model, verdicts and resumes included. `cheap_only` launches every ticket, each one rung down the
  rung ladder (ticket 62, decision 16: `stepped_down`, floor rung 2, never out of Fable from a
  project's own Fable rungs, and an attempt that is itself a tier up exempt), and holds the verdicts,
  which are not on the ladder. What needs no model still happens first in the wave: the workers
  already running finish, and their machine checks and integration run. A hit limit journals `paused`,
  a session the limit stopped mid-work is resumed after the reset instead of failed, one it refused
  before its first turn is relaunched in the same attempt (decision 15), and the first wave past the
  reset journals `unpaused`. No job poller, so an experiment ticket whose jobs outlive its worker
  stays `running` and holds the run open until ticket 19's poller closes it or `wayline stop` ends the
  run.
- The hold on Fable's weekly window (ticket 54, decision 15). A refusal on that window, or a reading
  of it at `pacing.stop_at`, journals `paused` with `model: fable` instead of the whole-run pause.
  While the hold stands, launchable drops every launch on Fable (a ticket whose tier is Fable, a
  session that defines an agent on Fable, and a done ticket's verdicts, whole, when any of them
  runs on Fable) and everything else keeps launching; a Fable session stopped mid-work waits and is
  resumed on Fable after the reset. `/usage` is read again before a wave launches Fable work, and
  `unpaused` with `model: fable` ends the hold at the reset, or earlier when a reading puts Fable
  under `stop_at`. Below `stop_at` and at `cheap_at`, that window steps a Fable launch one rung down
  instead, from a project's top Fable rung to the Fable rung below it and no further (ticket 62; the
  shipped rung ladder has no Fable rung since ticket 70): a launch on a Fable rung is paced by
  Fable's weekly window and the all-models week, every other launch by the five-hour and all-models
  windows, and `pacing` carries both actions.
- The fallback to Opus (ticket 55, decision 15). While the hold stands and the fallback consent is
  `auto`, a launch on Fable runs on Opus at the same effort and budget under Opus's context cap,
  every agent it defines on Fable moves with it, and `ticket_launched` carries `fallback_from`,
  naming the Fable rung it came from (`r7 fable high`, decision 16). A
  Fable session the hold would keep waiting (refused before its first turn, stopped mid-work, or owed
  a gate's resume) starts again as a fresh Opus session in the same attempt and worktree, never as a
  resume of the Fable transcript. Under `wait`, and under `ask` until the ask is built, Fable work
  waits as above; a verdict whose verifier is Fable waits under every consent until verdicts fall back.
- Decision tickets (ticket 35, `wayline.decisions`). Each of a valid result's `decision_requests`
  opens a decision ticket that pauses the tickets waiting on the one that asked, journals
  `decision_opened`, and notifies the owner. Every wave journals an answer written into a decision
  ticket's file and marks an answered decision ticket `done`, which releases what it paused. Under
  autonomy `interactive` and `checkpoints` no session is launched for a decision ticket, and one
  left on the frontier keeps no run going: the owner's answer is what the tick relaunches for.
- A result's `proposals` and `goal_progress` are written into the ticket's `## Result` section so
  the owner sees them; admission is ticket 37. The worker's own `goal_progress` is never what is kept.
- Keep-if-better, per goal (tickets 39 and 87, `wayline.goal`). A ticket whose `goal` names an open goal (an
  objective with a measure in `objectives.json`) is measured by that measure's `eval_command` on each seed
  artifact before its integration: a `done` result in its worktree, a `running` one once its jobs exited 0.
  Fewer seeds than the measure's `min_seeds` (else `policy.goal.min_seeds`) fail the ticket with a request for
  more. A change whose mean does not beat the goal's own best kept value by more than `policy.goal.margin_sd`
  standard deviations (at one seed, by any strict gain) is discarded: `progress` with `kept: false` and
  `discarded` are journaled with the goal, the ticket is `done` and earns no verdict, its findings are filed as
  negative results, and its branch and worktree stay, renamed `ticket/<id>-a<n>` and `.worktrees/<id>-a<n>`. A
  `done` result is then never fast-forwarded; a `running` one, whose branch reached `main` before its jobs, is
  reverted there. A kept change journals `progress` with `kept: true` once it is on `main`.
- The stopping rule and the budgets (ticket 87, `wayline.stopping`; wave step 6). Code writes each open goal whose
  best kept value reached its target answered; `harness.json`'s `stop_when` is read every wave and ends the run
  `objectives_closed` (or `goal_reached`), and a spent budget ends it `budget_spent`. An empty frontier with an
  objective the rule waits on opens one decision ticket per such objective: the owner answers under `interactive`
  and `checkpoints` (the run ends `frontier_empty` meanwhile), the decider under `autonomous` in one session,
  replanning or answering only; a `replan for it` answer is cut by the planner as a revise.
- The ask of decision 15 (ticket 57). Under the fallback consent `ask`, the first wave whose hold drops a
  launch on Fable opens one human-only decision ticket about the window, keyed by its reset, which
  pauses nothing (`decisions.open_fable_ask`). Its answer, read at the next wave, falls back for the
  window (`fall back`), waits (`wait`, and any answer matching no option, which the owner is told), or
  also sets the consent (`always fall back`, `always wait`). An ask nobody answered is closed as
  superseded at the first wave past its reset or on a change of consent to `auto` or `wait`, and on a
  project that never recorded a consent, under `autonomous`, answered `fall back` at its timeout.
- The model that ran (ticket 63, decision 16). Every launch turns the CLI's legacy model remap off, and
  a returned session is checked against the model it was launched with before anything else is made of it.
  A result whose `modelUsage` names no model of the rung's fails the attempt with `model_mismatch`, and the
  model that ran is on its `ticket_result`. A name the subscription does not serve fails it with
  `model_not_served`, which is never resumed or retried: the rung is held, one human-only decision ticket
  per held rung asks the owner to edit the policy, and launches at every other rung go on. The hold is that
  open ticket, so a replay rebuilds it and the owner's answer lifts it.
- The Type-B gate of decision 11 (ticket 32): a done ticket's verdicts are queued and drained
  later in the same wave, and the ticket is `accepted` when every one of them passed.

The conductor never trusts the worker's own acceptance file. It runs the ticket's commands itself,
three times, and the ticket is `done` only once they passed on `main`. Nor does it trust the
worker's own account of its quality: `accepted` comes from a verifier on another model.
"""

import argparse
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from wayline import HARNESS_ROOT, code_repository, concerns, decider, decisions, gates, methods, notify, numbers, objectives, pacing, proposals, references, replay, reproduce, resources, schedule, sections, software, stopping, tick, tickets, verification, worker
from wayline import goal as goals
from wayline.tools import run_tool
from wayline.ledger import (
    ACCEPTANCE, CONTROL, DIFFICULTY_RAISED, DISCARDED, FEEDBACK, INTEGRATED, PROGRESS, JOB_FAILED, JOB_FINISHED, JOB_RETRIED, JOB_WAITING, PACING, PAUSED, RUN_ENDED, RUN_STARTED, TICKET_ACCEPTED, UNPAUSED,
    TICKET_BLOCKED, TICKET_CANCELLED, TICKET_DONE, TICKET_FAILED, TICKET_LAUNCHED, TICKET_NEEDS_HUMAN,
    TICKET_RERUN, TICKET_RESULT, TICKET_RESUMED, TICKET_SESSION, STALL, WAVE, ConductorBusy, Ledger, conductor_holder, now_ts,
)
from wayline.jsonschema import ValidationError
from wayline.project import (
    UPGRADE_HINT, ProjectError, ask_falls_back_at, check_policy, consent_for, fallback_consent, falls_back_now, find_project,
    journal_written_answers, policy_for, read_harness, rung_label,
)

__all__ = [
    "ConductorError", "Conductor", "WaveResult", "Tier", "tier_for", "rung_tier", "rung_of", "rung_label", "ladder", "fallback_tier",
    "rung_family", "stepped_down", "FLOOR_RUNG",
    "porcelain_entries",
    "dirty_outside_research", "refuse_to_start", "run_command", "WORKTREES", "RESEARCH", "BRANCH",
]

MAIN = "main"
INTERACTIVE = "interactive"  # the autonomy under which a passage replacing an owner's is a notice (ticket 88)
RESEARCH = "research"
WORKTREES = ".worktrees"
BRANCH = "ticket/%s"
LEDGER_COMMIT = "ledger: wave %d"
# The acceptance result the declared-sections check of decision 17 adds in the worktree (ticket 86).
SECTIONS_CHECK = "wayline: the declared sections got their passages"
VERIFICATION_CHECK = "wayline: the verification names its route"  # ticket 97: a verification ticket's verdict, at its acceptance
INHERITED_FILE = "inherited.json"  # beside a ticket attempt's session: its verdicts on inherited claims, for its verdict (ticket 97)
# The acceptance result the check of a ticket's references adds in the worktree (decision 17; ticket 98).
REFERENCES_CHECK = "wayline: every cited work is a dossier or listed, at a locator its level holds"
# The acceptance result the provenance linter adds in the worktree over a result's passages and findings (decision 17; ticket 88).
LINT_CHECK = "wayline: every claim sentence ends with a provenance tag that resolves"
# What the owner is told when the code repository's remote refuses code/'s split (decision 17; the `notified` event's `event`).
CODE_PUSH_REJECTED = "code_push_rejected"
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
RESUME_LIMIT = (
    "Your session stopped at the subscription's usage limit before it returned its result, and the "
    "window has reset since. Continue the ticket from where you left off, commit on the ticket branch, "
    "run `wayline accept`, and return the structured result."
)
# What a fresh Opus session is told when it takes over the work of a Fable session the hold keeps waiting (decision 15):
# one that stopped before it returned its result, and one that returned and is owed a gate's resume.
FALLBACK_PARTIAL = (
    "An earlier session on this ticket ran on Fable and stopped before it returned its result, and Fable's weekly "
    "window is spent. It left partial work in this worktree, on the ticket branch, committed or not. This session "
    "continues the ticket on Opus: read what is already there (the status and the log of the ticket branch, and the "
    "files in the touch set) and carry on from it rather than start over."
)
FALLBACK_RETURNED = (
    "An earlier session on this ticket ran on Fable and returned its result, and the conductor's follow-up to it, "
    "below, cannot go to Fable while Fable's weekly window is spent. Its work is in this worktree, on the ticket "
    "branch. This session takes the follow-up on Opus: read what is already there (the status and the log of the "
    "ticket branch, and the files in the touch set), then do what the follow-up asks, building on that work rather "
    "than starting over."
)
FALLBACK_LAST_MESSAGE = "The conductor's last message to that session, which this session answers in its place:\n\n%s"
# Where an attempt that fell back keeps the notes its prompt carries, so a restart that relaunches it says them again.
FALLBACK_NOTES = "fallback.json"
# The last failure a tier-up attempt carries in its prompt (ticket 68), kept in its attempt's directory so a
# restart that relaunches the attempt says it again.
LAST_FAILURE = "failure.json"
LAST_FAILURE_HEADING = worker.LAST_FAILURE_HEADING
# What `_start_wanted` returns when it started a fresh Opus session in place of one the hold kept waiting on Fable.
FALLEN_BACK = "fallen_back"
# What `_act_on` returns for a valid `running` result: its branch is integrated and its jobs left to the poller (ticket 19).
RUNNING = "running_jobs"
# The commit that reverts a discarded experiment's change on `main` (ticket 39); its trailer finds it again after a restart.
REVERT_TRAILER = "Wayline-Discarded: %s"
# Where a discarded attempt's change stays (ticket 39), out of the way of the ticket's next attempt.
DISCARDED_BRANCH = "ticket/%d-a%d"
DISCARDED_WORKTREE = "%d-a%d"
REVERT_MESSAGE = "ticket %d: discarded by keep-if-better\n\n" + REVERT_TRAILER
# The steps of the escalation chain (decision 5; ticket 38), as `ticket_failed` names them in `next`.
# A step is not a rung: a rung is a rung of the rung ladder, `policy.tiers` (decision 16).
RESUME, TIER_UP, SPLIT, NEEDS_HUMAN = "resume", "tier_up", "split", "needs_human"
# Why a `ticket_needs_human` was journaled, when the chain ran out on the ladder's top rung (decision 16).
TOP_RUNG = "top_rung"
# How `status`, the dashboard, and `REPORT.md` say that a ticket ended with nowhere left to climb.
TOP_RUNG_NOTE = "at the ladder's top rung"
# The order is the owner's (2026-09-17): a split before a tier up, since a tier up (to Fable above all) is the dearer step.
# `tier_up` counts rungs of the rung ladder, so a tier up moves one rung (decision 16). `then` is the order
# after the resume while the tier up stays inside the failed attempt's model family; `_step_order` puts the
# split first when the next rung is on Fable, because the Fable week is scarcer than the planner's session.
LADDER = {"resume": 1, "then": [TIER_UP, SPLIT, NEEDS_HUMAN], "tier_up": 1, "raise_after_failures": 2}
# The floor of the step down at `pacing.cheap_at` (decision 16): pacing never runs a launch below
# this rung of the rung ladder, whatever the windows read (`stepped_down`).
FLOOR_RUNG = 2
# The stall's two actions, and the reason a strict stall ends the run with (decision 5).
REPLAN, STOP = "replan", "stop"
STALL_STRICT = "stall_strict"
STALL_WAVES = 2
RESUME_FAILED = (
    "The ticket failed after this session returned its result:\n\n%s\n\n"
    "The ticket file, %s, holds the whole failure output under its `## Result` section (the end of a job's log, "
    "a verifier's findings). Fix what failed in this worktree, which is checked out on the ticket branch, run "
    "`wayline accept`, commit on the ticket branch, and return the structured result."
)
TIER_UP_FAILED = (
    "The attempt before this one failed, and the escalation chain sent the ticket one rung up to this fresh "
    "session. The failure output its resume was given:\n\n%s\n\n"
    "The ticket file, %s, holds the whole failure output under its `## Result` section. Work already on `main` "
    "or on the ticket branch does not make the ticket done: mend what failed, then run `wayline accept`, commit "
    "on the ticket branch, and return the structured result."
)
# How much of a failed job's log the journal and the ticket's failure output carry.
LOG_TAIL_CHARS = 4000
REJECTED = (
    "the %s verdict failed: a fresh %s session that did not write this read it and found\n\n%s"
)


# What the conductor says when a `control` event another process appended arrives, by command.
ARRIVALS = {
    "pause": lambda args, by: "paused by %s" % by,
    "resume": lambda args, by: "resumed by %s" % by,
    "stop": lambda args, by: "asked by %s to stop %s" % (by, "once the running workers return" if args.get("drain") else "at this wave"),
    "autonomy": lambda args, by: "autonomy is now %s" % args.get("autonomy"),
    "model_fallback": lambda args, by: "fallback consent is now %s" % args.get("model_fallback"),
    "ladder_changes": lambda args, by: "ladder consent is now %s" % args.get("ladder_changes"),
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


def refuse_to_start(project, harness_root=None):
    """Every reason this run must not start, with what to do about it; () when there is none.

    The branch is checked as well as the tree, because the fast-forward of the integration
    protocol is `git merge --ff-only` into whatever the project has checked out: on another
    branch it would quietly move that one instead of `main`.

    The third refusal of decision 5 is a harness checkout whose tag is not the project's pin
    (`evolve.pin_problem`, which names the `wayline upgrade` command that fixes it).
    """
    from wayline import evolve  # the evolve module imports the fixture runner; keep this module's import light

    harness_root = harness_root or HARNESS_ROOT
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
    pinned = evolve.pin_problem(project, harness_root)
    if pinned:
        problems.append(pinned)
    # The rung ladder (decision 16): a policy the schema or the ladder refuses, an old-shape `difficulty` override first.
    try:
        check_policy(policy_for(project, harness_root), name="the policy of %s (policy.json under harness.json)" % project)
    except ValidationError as failure:
        problems.append(str(failure))
    return problems


# --- the difficulty tier --------------------------------------------------------------------


@dataclass
class Tier:
    """What a ticket launches at: the rung of the rung ladder its difficulty names, resolved (decision 16).

    `model` is the rung's, an alias or a full version name, and `family` its family (`opus` for
    `claude-opus-4-8`), which keys the context cap and the verifier table. `rung` is the rung's 1-based
    index in `policy.tiers`, what `ticket_launched` and `verdict` carry and `wayline status` labels a launch
    by; None for a tier no rung made (a role's).
    """

    model: str
    effort: str
    max_turns: Optional[int] = None
    max_minutes: Optional[int] = None
    context_chars: Optional[int] = None
    rung: Optional[int] = None
    family: Optional[str] = None

    def __post_init__(self):
        if self.family is None:
            self.family = pacing.family(self.model)

    @property
    def label(self):
        """`r5 opus high`, the label of decision 16; without the index for a tier no rung made."""
        return rung_label(self.rung, self.model, self.effort)


def ladder(policy):
    """`policy.tiers`, the rung ladder: the rungs as listed, cheapest first."""
    rungs = policy.get("tiers")
    if not isinstance(rungs, list) or not rungs:
        raise ConductorError("policy.tiers, the rung ladder, is missing or empty")
    return rungs


def rung_tier(policy, rung, ticket_budget=None):
    """The tier of rung `rung` (its 1-based index in `policy.tiers`), under `budget` and `context_pack`, the ticket's budget winning.

    `context_pack.max_chars` is keyed by family and names only the three a worker runs on, so
    anything else (a `haiku` rung) takes the smallest cap rather than none at all.
    """
    rungs = ladder(policy)
    index = rung if isinstance(rung, int) and not isinstance(rung, bool) else None
    if index is None or not 1 <= index <= len(rungs):
        raise ConductorError("policy.tiers has no rung %r; the rung ladder has %d rung(s), 1 to %d" % (rung, len(rungs), len(rungs)))
    entry = rungs[index - 1]
    if not isinstance(entry, dict) or "model" not in entry or "effort" not in entry:
        raise ConductorError("policy.tiers rung %d is not a model, an effort, and a budget: %r" % (index, entry))
    family = pacing.family(entry["model"])
    if family is None:
        raise ConductorError("policy.tiers rung %d names the model %r, which is no alias (%s) and no full version name of one"
                             % (index, entry["model"], ", ".join(pacing.FAMILIES)))
    budget = dict((policy.get("budget") or {}).get(entry.get("budget")) or {})
    budget.update({key: value for key, value in (ticket_budget or {}).items() if value is not None})
    return Tier(
        model=entry["model"], effort=entry["effort"],
        max_turns=budget.get("max_turns"), max_minutes=budget.get("max_minutes"),
        context_chars=_context_cap(policy, family), rung=index, family=family,
    )


def rung_family(policy, rung):
    """The family of the model rung `rung` names, or None for a rung the ladder does not have."""
    rungs = ladder(policy)
    index = rung if isinstance(rung, int) and not isinstance(rung, bool) else None
    if index is None or not 1 <= index <= len(rungs):
        return None
    entry = rungs[index - 1]
    return pacing.family(entry.get("model")) if isinstance(entry, dict) else None


def stepped_down(policy, rung):
    """The rung a launch runs on while `cheap_at` is in force: one below `rung` (decision 16).

    Two floors hold. A launch never runs below `FLOOR_RUNG`, because a nearly spent window is a
    reason to spend less on a ticket, never a reason to hand a hard ticket to the cheapest model
    there is. And a launch on Fable never steps out of Fable: the step is read by family, never by
    index, so on a project's own Fable rungs (the shipped rung ladder has none since ticket 70) it takes a
    launch from the top Fable rung to the one below it, and the lowest Fable rung stays where it is,
    because leaving Fable is what the hold and the fallback do (decision 15), under the owner's
    consent, and not what pacing does.

    A rung the ladder does not have is returned as it came: the launch fails on it in `rung_tier`,
    where the owner reads why, rather than silently running one rung off.
    """
    below = rung - 1 if isinstance(rung, int) and not isinstance(rung, bool) else None
    if below is None or rung <= FLOOR_RUNG or rung_family(policy, rung) is None:
        return rung
    if rung_family(policy, rung) == pacing.FABLE and rung_family(policy, below) != pacing.FABLE:
        return rung
    return below


def rung_of(policy, difficulty):
    """The rung index `policy.difficulty` maps `difficulty` to; the old shape (a level mapped to a model) names `wayline upgrade`."""
    levels = policy.get("difficulty") or {}
    rung = levels.get(str(difficulty), levels.get(difficulty))
    if isinstance(rung, dict):
        raise ConductorError("policy.difficulty maps level %s to a model and an effort, the shape before the rung ladder; %s"
                             % (difficulty, UPGRADE_HINT))
    if not isinstance(rung, int) or isinstance(rung, bool):
        raise ConductorError("policy.difficulty has no rung for level %r; it has %s"
                             % (difficulty, ", ".join(sorted(map(str, levels))) or "none"))
    return rung


def tier_for(policy, difficulty, ticket_budget=None):
    """The tier of `difficulty`: the rung `policy.difficulty` maps it to, resolved by `rung_tier`."""
    return rung_tier(policy, rung_of(policy, difficulty), ticket_budget)


def _context_cap(policy, family):
    """`policy.context_pack.max_chars` for `family`; a family it does not name takes the smallest cap rather than none."""
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    return caps.get(family, min(caps.values()) if caps else None)


def fallback_tier(policy, tier):
    """What a tier on Fable becomes while Fable work falls back (decision 15).

    Opus, at the same effort and the same turns and minutes, under `context_pack.max_chars.opus`: the
    difficulty, the rung, and the budget are the ticket's, and only the model and its context cap change.
    """
    return Tier(model=pacing.OPUS, effort=tier.effort, max_turns=tier.max_turns, max_minutes=tier.max_minutes,
                context_chars=_context_cap(policy, pacing.OPUS), rung=tier.rung, family=pacing.OPUS)


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
    # The decision tickets the decider answered this wave, and the parked proposals it reconsidered (ticket 31).
    decided: list = field(default_factory=list)
    reconsidered: list = field(default_factory=list)
    ended: bool = False
    reason: Optional[str] = None
    ledger_commit: Optional[str] = None
    # The worker outcomes this wave carried and the findings they filed: a wave that carried one is
    # a settling wave, and whether it filed anything is what the stall counter reads.
    outcomes: int = 0
    findings: int = 0
    # The jobs that exited 0 with outputs that parsed: progress, like a finding, for the stall counter (ticket 19).
    jobs_finished: int = 0
    # The changes keep-if-better kept: progress toward the goal, for the stall counter (ticket 39).
    kept: int = 0
    # The escalation steps this wave took, as `(ticket, step)`, and whether it journaled a stall (ticket 38).
    escalated: list = field(default_factory=list)
    stalled: bool = False

    @property
    def touched(self):
        """Whether this wave moved anything at all; a wave that did not cannot be repeated usefully.

        A wave that only drained the verdict queue moved something: the tickets it accepted
        released whatever waited on them, so the next wave has work the last one did not.
        """
        return bool(self.launched or self.done or self.failed or self.running
                    or self.accepted or self.rejected or self.decided or self.reconsidered or self.outcomes
                    or self.escalated or self.stalled)


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
    started; `message` is what a resume says. `answering` is the message the session that died was
    itself answering, when it was a resume, which a fresh session taking its place is given (decision 15).
    """

    stage: str
    message: Optional[str] = None
    answering: Optional[str] = None


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
    no_diff: bool = False  # the integration added no commit of the ticket's own
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
    # Whether the wait for a free worker slot was said for the session it wants, which is said once.
    waiting_for_slot: bool = False
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
    # How many of the session stream's `rate_limit_event`s pacing has already folded in.
    limits_read: int = 0
    # The Fable rung (`r7 fable high`) the attempt's session came from when it runs on Opus because
    # Fable work fell back (decisions 15 and 16), else None.
    fallback_from: Optional[str] = None
    # The rung the attempt would have run on had pacing not stepped it down one (decision 16), for the launch line.
    stepped_from: Optional[str] = None
    # What keep-if-better judged of this attempt (ticket 39), once it has, and whether the change was kept.
    judgment: Optional[goals.Judgment] = None
    kept: bool = False

    @property
    def id(self):
        return self.ticket["id"]

    @property
    def running(self):
        """Whether a session this conductor started for the attempt is still running in its thread."""
        return self.thread is not None and self.thread.is_alive()

    @property
    def has_a_session(self):
        """Whether a session of this attempt is running, or returned and is not carried yet (ticket 59).

        A session that returned holds its worker slot until the wave reads it, because the wave
        that carries it may resume it. An attempt that waits to start a session has none: its own
        was carried, and `thread` outlives the session that set it, so the dead thread of a carried
        session is not one. An attempt whose result was carried and that owes nothing has left `flight`.
        """
        if self.want is not None:
            return False
        return self.running or self.adopted or self.thread is not None

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
        # What names this run's waves on a passage (`<run>/<number>`): wave numbers start again at every run, and two
        # replacements of one passage are kept side by side only when they land in the same wave (decision 17).
        self._run_key = uuid.uuid4().hex[:8]
        self.out = sys.stdout if out is None else out
        self._who_args = None
        # The Type-B queue of decision 11: what each done ticket earned, drained later in the wave
        # because a verdict is model work like any other and is paced like any other.
        self.verdicts = []
        # The pacing action of wave step 8, computed from the latest reading of each window, and the
        # resource answer of step 7, which the job poller replaces with the free-slot rule of
        # `wayline.resources`. `clock` is the time pacing reads, which a test moves across a reset.
        self.action = schedule.NORMAL
        # The action a launch on a Fable rung runs under (decision 16): the same thresholds over the
        # windows a Fable rung reads, Fable's weekly window and the all-models week.
        self.fable_action = schedule.NORMAL
        self.windows = pacing.Windows()
        self.clock = time.time
        # The reading `run --simulate-limit cheap:[fable:]<seconds>` forces, as `(seconds, model)`, and the
        # moment it lapses; the demo forces a step down with it rather than waiting for a nearly spent window.
        self._simulated_step = self._simulated_until = None
        self._simulated_fable = False  # `run --simulate-limit fable:<seconds>`: its hold stands until its own reset
        # The wave `/usage` was last read for before it launched Fable work (decision 15): once a wave at most.
        self._usage_wave = None
        # What was last said of `/usage` giving no reading and of verdicts waiting on the hold, so a week-long hold says each once.
        self._usage_trouble = None
        self._said_waiting = None
        # The tickets last said to be waiting on a rung the subscription does not serve (decision 16), said on change.
        self._said_held_rungs = ()
        # The fallback consent as this wave read it, and the wave it read it for (decision 15).
        self._consent = self._consent_wave = None
        # The launches on Fable the hold dropped in this wave, which the ask of decision 15 names when the consent asks.
        self._dropped = []
        self._proposal_cap = {}
        self.resources_free = schedule.everything_free
        # What the wave's `software` step left (ticket 82): the tools gone without, the install and check jobs under
        # way, and why each ticket that needs a missing tool waits. `tools` is the record it read, `~/.wayline/tools/`.
        self.software = software.Settled()
        self.tools = None
        self._said_software = ()
        # The job runner of decision 6, made when a wave first has a job to poll or launch, and the machine readings the
        # free-slot rule places pending jobs by (`resources.read_readings`), which a test replaces with a recorded one.
        self.jobs_runner = None
        self.readings = None
        # The tool runner the push of the code repository's split goes through (decision 17, seam 6); a test records it.
        self.code_run = run_tool
        self.methods_run = run_tool    # the parsers of the rule from code to Methods (ticket 107); tests replay recordings
        self.methods_tools = None      # `tools.json` as the machine records it, unless a test hands one in
        # The embedding model the repeated-claims check at acceptance runs through (ticket 95); tests replay recordings.
        self.repeats_run = run_tool
        self.repeats_tools = None
        # The split the remote last refused, which this run does not push again (it is told to the owner once).
        self._code_rejected = None
        # The notifier the owner hears of a decision ticket through when this run opens one (decision 7), on a thread of
        # its own so a slow channel never holds a wave; a test stands in its own. `notifying` is those threads.
        self.notify = self._notify_in_background
        self.notifying = []
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
        worker.take_answered_refusals()  # a refusal a session of another run carried is not this run's
        # The cancels and reruns that changed nothing, said once each rather than every wave.
        self.declined = set()
        # The planner's cut at the `split` step and at a stall (ticket 38): `planner(cut, fall_back)` returns what was
        # written, and a test stands in its own. `plan_pre_check` is the registry's free pre-check before a cut.
        # `reporter()` renders `REPORT.md` when a strict stall ends the run. `_replanned` is the stall whose replan
        # this run has taken, so a cut that failed is not launched again at every wave.
        self.planner = self._cut
        self.plan_pre_check = True
        # The fetcher the check of a ticket's references runs the scout on (ticket 98): None for the project's cache.
        self.scout_fetcher = None
        # The sentence classifier the linter at acceptance asks about a result's untagged sentences (ticket 88):
        # `classifier(texts) -> classes`, a haiku batch through the launcher; a test stands in its own.
        self.classifier = self._classify
        # The verifier the numbers check sends each sentence it cannot match to (ticket 90): `(attempt, check) -> Judged`.
        self.numbers_verifier = self._verify_numbers
        # The level-2 read a `dossier` ticket runs as its promotion, `(project, slug) -> report` (ticket 98): None for
        # `absorb.absorb_level_2`; and the inventory it builds first when the paper has none, None for `dossier.build_inventory`.
        self.absorb_dossier = None
        self.dossier_inventory = None
        self.reporter = self._render_report
        self._integrated_now = False  # a ticket was integrated in this wave, so the general report renders at its end
        self._replanned = None
        self._objectives_trouble = None
        self._harness_trouble = None
        self._objective_replans = set()
        self._answer_stamps = {}
        # The evolve loop (ticket 45, decision 12). A policy nobody handed in is read again every wave, so a local change
        # to `harness.json` is used from the next one. `evolver(fall_back)` is the evolver's session over the pending
        # feedback, `prover` runs a change's fixture on the old and the new subject, and `global_checks` runs the harness
        # tests and the fixture suite on a global change's branch; a test stands in its own for each.
        self._policy_given = policy is not None
        self._policy_stamp = self._policy_files()
        self._policy_trouble = None
        self.evolver = self._run_evolver
        self.prover = None
        self.global_checks = None
        self._changes = {}

    @property
    def policy(self):
        return self._policy

    @policy.setter
    def policy(self, value):
        """A policy assigned from outside is the caller's, and `_reread_policy` leaves it standing."""
        self._policy, self._policy_given = value, True

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
        self._dropped = []
        self._proposal_cap = {}  # the per-radius count admitted this wave (ticket 37), shared across every result it carries
        self._beat()
        self._reread_policy()
        arrived = self._tail()
        self._fold_answered_refusals()
        self._pace()  # what `run` start and the journal read, before anything below can start a session
        first = not self.taken_over
        if first:
            self._take_over(result)
        self._apply_controls(arrived, first)
        self._unpause_at_reset()
        # Jobs need no model, so they are polled, retried, closed, and launched whatever the pacing says (wave steps 2 and 8).
        self._poll_jobs(result)
        self._poll(result)
        self._place_jobs(result)
        self._software(result)
        self._concerns()
        self._verifications()
        self._pace()
        if not self._rule_ends(result) and not self._holds_launches() and not self._stops_at_stall(result):
            self._escalate(result)
            self._replan(result)
            self._decide(result)
            self._read_cited()
            self._replan_objectives(result)
            self._evolve(result)
            self._fold_answered_refusals()  # the decider, the planner, and the evolver answer in this wave
            picks = self._picks(self._graph())
            if picks:
                self._start(picks, result)
            self._drain_verdicts(result)
            self._reconsider_parked(result)
        self._ask_owner()
        self._journal_wave(result)
        self._check_stall(result)
        self._end(result)
        reported = False
        if self._integrated_now or result.findings:
            self._propose_outline_merges()
            reported = self._render_general_report()  # it renders the account and the outline in the same pass
        self._render_account()
        if not reported:
            self._render_outline()
        if result.ended:
            self._end_notice(result)
        result.ledger_commit = self._commit_ledger(self._render_reproduce())
        self._push_code()
        self._tail()
        self._beat()
        return result

    def _render_general_report(self):
        """`research/REPORT.md`, the general report, rendered by code after every wave that integrated a ticket (ticket 90).

        Offline: it launches no session, the classifier included. One that fails is said, and the tick renders it again
        when the journal moved; nothing in the run waits on it. Returns whether it rendered, the outline with it.
        """
        self._integrated_now = False
        from wayline import provenance  # the provenance module pulls in the gates and the report
        try:
            provenance.render_report(self.project, harness_root=self.harness_root, policy=self.policy, offline=True)
        except (ValueError, OSError) as failure:
            self.say("  REPORT.md was not rendered: %s; the tick renders it again" % failure)
            return False
        return True

    def _render_account(self):
        """`research/ACCOUNT.md` rendered by code at the end of every wave, so the wave's ledger commit carries it (ticket 89).

        A render that would leave the file as it is writes and journals nothing. One that fails is said, and the next wave
        renders it again: the account is a view of the journal, and nothing in the run waits on it.
        """
        from wayline import account  # the account reads every part of the ledger
        try:
            account.render_account(self.project)
        except (ValueError, OSError) as failure:
            self.say("  ACCOUNT.md was not rendered: %s; the next wave renders it again" % failure)

    def _render_outline(self):
        """`research/OUTLINE.md` rendered by code at the end of every wave, taking the owner's edit of it in first (ticket 104).

        A render that would leave the file as it is writes nothing; one that fails is said, and the next wave renders it again.
        """
        from wayline import outline  # the outline reads every part of the ledger
        try:
            outline.render_outline(self.project)
        except (ValueError, OSError) as failure:
            self.say("  OUTLINE.md was not rendered: %s; the next wave renders it again" % failure)

    def _propose_outline_merges(self):
        """The outline's merge proposals after a wave that integrated (ticket 104): the embedding model, no tokens, over the
        headings of the results under each objective, when they changed. One that cannot run is said; nothing waits on it."""
        from wayline import outline, repeats  # the outline reads every part of the ledger
        try:
            batch = outline.propose_merges(self.project, run=self.repeats_run, tools=self.repeats_tools)
        except (repeats.RepeatsError, ValueError, OSError) as failure:
            self.say("  the outline proposed no merge: %s" % failure)
            return
        if batch is not None:
            self.say("  the outline proposes %d merge(s) of results whose headings sit close: %s" % (len(batch["items"]), batch["id"]))

    def _end_notice(self, result):
        """The one notice of this run's end, sent after `run_ended` and the gates (decision 17; ticket 89).

        It opens with the account's first paragraph, then "N decided for you, M waiting on you" and the path. Sent after
        `run_ended`, its `notified` claim follows the end, so the tick never sends it again; the tick sends it only when
        this conductor died between the two.
        """
        from wayline import account
        try:
            text = account.end_notice(self.project)
        except (ValueError, OSError) as failure:
            text = "%s: the run ended (%s); research/ACCOUNT.md could not be read: %s" % (self.project.name, result.reason, failure)
        self.notify(tick.GOAL_REACHED if result.reason == stopping.GOAL_REACHED else RUN_ENDED, text, self.project, None)

    def _push_code(self):
        """Push `code/`'s split once a wave changed it (decision 17): code, never a worker, keeps the code repository's remote.

        What was pushed last is the latest `code_pushed` the view folded, so a restart pushes nothing a run before it
        already pushed, and the split walks only what `main` gained since. A push the network or a credential failed
        is said and tried again by the next wave. A push the remote refused (its branch holds commits the split does
        not descend from) is never forced: the owner is told once, and that split is not pushed again, since pushing
        it again cannot mend it; a later change to `code/` makes a new split, which is tried.
        """
        try:
            pushed = code_repository.push_if_changed(self.project, self.view.code_pushed, run=self.code_run,
                                                     skip=self._code_rejected)
        except code_repository.CodePushRejected as rejected:
            self._code_rejected = rejected.commit
            self.say("  the code repository refused the push: %s" % rejected)
            self.notify(CODE_PUSH_REJECTED, "%s: %s. Bring that branch into code/'s history, or answer the setup "
                        "question again with another remote." % (self.project.name, rejected), self.project)
            return None
        except code_repository.CodeRepositoryError as failure:
            self.say("  the code repository was not pushed: %s; the next wave tries again" % failure)
            return None
        if pushed:
            self.say("  pushed code/ to the code repository as %s" % pushed[:12])
        return pushed

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
            with self.ledger.lock():
                # Read again under the ledger's lock now that the heartbeat is held: `wayline switch
                # --autonomy` lowers only while no conductor holds it, and a lowering written between
                # the read above and the heartbeat must not be undone by the autonomy this run announces.
                harness = read_harness(self.project)
                self.harness_tag, self.started_at = harness.get("harness_tag"), now_ts()
                self._beat()
                self.ledger.append_event(RUN_STARTED, {
                    "resume": bool(resume), "harness_tag": harness.get("harness_tag"),
                    "autonomy": harness.get("autonomy"), "radius": harness.get("radius"), "pid": os.getpid(),
                })
            self._read_usage()
            self._usage_wave = self.number + 1  # the reading `run` start just took stands for its first wave
            waves = []
            wait = self._idle if wait is None else wait
            while True:
                waves.append(self.wave())
                if waves[-1].ended or (max_waves is not None and len(waves) >= max_waves):
                    return waves
                wait(self._wait_seconds())
        finally:
            self.heartbeat.release()
            self.heartbeat = None
            for thread in list(self.notifying):  # what this run claimed to the owner is sent before it returns
                thread.join()

    def settle(self, timeout=None):
        """Wait until every session this conductor started has returned; the next wave carries them."""
        for attempt in list(self.flight.values()):
            if attempt.thread is not None:
                attempt.thread.join(timeout)
        for thread in list(self.notifying):
            thread.join(timeout)

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
        self._heard_pacing(events)
        return events

    def _journal_wave(self, result):
        """The `wave` event of a settling wave, which is what lets a restart rebuild the stall counter."""
        if result.outcomes:
            self.ledger.append_event(WAVE, {"number": self.number, "outcomes": result.outcomes,
                                            "progressed": bool(result.done or result.findings or result.jobs_finished or result.kept)})

    def _end(self, result):
        """`run_ended`: once a stop has been applied, or once the frontier is empty, nothing runs, and no verdict is queued.

        A stop without `drain` ends the run at this wave and leaves the workers still running to
        finish on their own, for the next run to re-adopt. A drain waits for them, and leaves a
        session that has not started yet to the next run, whose take-over finds it in the journal.
        """
        if result.ended:
            return  # the stopping rule or a budget ended the run earlier in this wave, which journaled `run_ended`
        requested = self._stop_requested()
        if requested is not None:
            if requested.drain:
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
            self.ledger.append_event(RUN_ENDED, {"reason": requested.reason})
            result.ended, result.reason = True, requested.reason
            return
        if self.flight or self.verdicts:
            # Queued verdicts wait on pacing or on the hold on Fable's weekly window, and are taken once it allows.
            return
        if self._owed_steps() or self._owed_replan() is not None or self._owed_objective_replans():
            return  # a failed ticket still waits on its step, a stall or an empty frontier on its replan: all wait, like any model work
        if self.software.in_flight:
            return  # an install or a licensed check runs as a job, and the tickets waiting on it launch once it is recorded
        graph = self._graph()
        running = [entry for entry in graph["tickets"] if entry["status"] == "running"]
        autonomy, decider = self._autonomy(), decisions.decider_ready(self.harness_root, self.project)
        # A decision ticket the owner answers stays on the frontier for them and no session takes it, so it keeps no run
        # going: the owner's answer is what the tick relaunches the conductor for (decision 7). A ticket that waits for a
        # tool nobody is installing keeps none going either: it waits on its software decision (ticket 82).
        if not [entry for entry in tickets.frontier(graph)
                if not schedule.awaits_owner(entry, autonomy, decider) and not self._needs_tools(entry)] and not running:
            takes, notice = self._empty_frontier(autonomy, decider)
            if takes:
                return  # the decider takes this empty frontier's tickets at the next wave
            for line in schedule.held_back(graph, autonomy, decider):
                self.say(line)
            self.ledger.append_event(RUN_ENDED, {"reason": stopping.FRONTIER_EMPTY})
            result.ended, result.reason = True, stopping.FRONTIER_EMPTY  # `notice` was said; the end notice follows the wave

    def _graph(self):
        """`graph.json`, regenerated, with what the next attempt launches at: its difficulty and its rung.

        `difficulty` is `_effective_difficulty`, the level a pin or a kind raise moved; `rung` is
        `_effective_rung`, the rung of the rung ladder that level names, lifted by every tier up the
        escalation chain took (decision 16). Both are added to the entries this returns, not to the
        `graph.json` that `refresh_graph` has already written: the file holds each ticket's own
        difficulty, and what a run moved lives in the journal.
        """
        events, _ = self.ledger.read_events()
        graph, _ = tickets.refresh_graph(self.project, ledger=self.ledger, events=events)
        found = {fields["id"]: fields for fields in tickets.read_tickets(self.project)}
        for entry in graph["tickets"]:
            if entry["id"] in found:
                entry["difficulty"] = self._effective_difficulty(found[entry["id"]])
                try:
                    entry["rung"] = self._effective_rung(found[entry["id"]])
                except ConductorError:
                    pass  # a policy with no rung for the level: the launch fails on it, and says so there
        return graph

    # --- what this wave launches (decision 5, wave steps 7 to 9) ---

    def _software(self, result):
        """Wave step 2's software part (decision 17; ticket 82): marks and answers kept in step, installs as jobs, asks opened.

        The dry runs that size an ask, the installs, and the licensed check are jobs, so they run
        whatever the pacing says, and the conductor never waits on the network: `software.settle`
        launches them through the job runner, and the job poll of the next waves concludes them like
        any job. A refused launch or a tools error is said, and fails no wave.
        """
        from wayline.tools import Tools

        self.tools = Tools()
        try:
            self.software = software.settle(self.project, self._runner, tools=self.tools, notify=self.notify, say=self.say,
                                            harness_root=self.harness_root)
        except (ValueError, OSError, RuntimeError) as failure:  # a refused job launch (`resources.JobError`) or a tools error fails no wave
            self.say("  the software step could not run: %s" % failure)
            self.software = software.Settled()
        self._tail()

    def _concerns(self):
        """Wave step 2's concerns part (decision 17; ticket 96): marks taken, objectives followed, a decision per concern to sort.

        Code alone: `concerns.settle` answers a concern whose objectives are answered, follows a reframe, sends one
        whose objective dropped back to be sorted, and past setup opens one decision ticket of class `concern` for each
        concern that waits, placing it once the owner or the decider answers. An unreadable record is said, and fails
        no wave.
        """
        try:
            concerns.settle(self.project, notify=self.notify, say=self.say)
        except (concerns.ConcernError, concerns.ConcernsUnreadable, tickets.TicketError, ValueError, OSError) as failure:
            self.say("  the concerns could not be settled: %s" % failure)
        self._tail()

    def _verifications(self):
        """Wave step 2's verification part (decision 17; ticket 97): results followed, the objective answered, a decision per gap.

        Code alone: `verification.settle` takes in the inherited results and their standing, answers "Do the inherited
        results hold?" once each has a verdict or is unverifiable, and past setup opens one decision ticket of class
        `material` per gap, takes each answer, and makes a result unverifiable when its verification ended `needs_human`
        under `autonomous`, releasing what it blocked. An unreadable record is said, and fails no wave.
        """
        try:
            verification.settle(self.project, notify=self.notify, say=self.say)
        except (verification.VerificationError, verification.VerificationUnreadable, tickets.TicketError, ValueError,
                OSError) as failure:
            self.say("  the verifications could not be settled: %s" % failure)
        self._tail()

    def _read_cited(self):
        """The read route (decision 17; ticket 97): the inherited claims that cite a reference the project holds, read by the
        consultant one reference at a time, past setup and while the objective is open. A failure is said, and fails no wave."""
        try:
            if not verification.reading(self.project):
                return
            report = verification.read(self.project)
        except (verification.VerificationError, verification.VerificationUnreadable, ValueError, OSError) as failure:
            self.say("  the cited inherited claims could not be read: %s" % failure)
            return
        if report["asked"]:
            self.say("  read %d cited inherited claim(s) against %s: %d settled" % (
                sum(1 for _ in report["asked"]), ", ".join(report["asked"]), len(report["settled"])))
        self._tail()

    def _needs_tools(self, entry):
        """The tools this ticket needs that are neither recorded nor gone without: it is not launchable while any is (ticket 82)."""
        if not entry.get("software"):
            return []
        if self.tools is None:
            from wayline.tools import Tools
            self.tools = Tools()
        return self.software.missing(entry, self.tools)

    def _picks(self, graph):
        """The tickets to launch now: the launchable subset of the frontier, in pick order.

        `max_parallel_workers` counts workers, so a wave fills only the slots that the attempts in
        flight leave free: a session still running, one that returned and is not carried yet, and
        one an attempt waits to start all hold theirs (`_takes_a_slot`, ticket 59). A ticket left
        `running` by jobs that outlived their worker holds its touch set against the frontier but
        occupies no worker slot, because that ticket has no worker.

        While the hold on Fable's weekly window stands, a ticket whose tier is Fable is dropped
        before the pick, so its slot goes to whatever else is launchable, unless the fallback consent
        is `auto`, when nothing is dropped and the Fable tickets launch on Opus (`_begin`). When the pick would launch
        Fable work and no hold stands, `/usage` is read first and the pick is made again under what
        it says: without the Fable tickets when it began the hold, and under the action it paced to.
        """
        running = [entry for entry in graph["tickets"] if entry["status"] == "running"]
        busy = self._busy()
        classes = self._objective_classes()
        autonomy = self._autonomy()
        decider = decisions.decider_ready(self.harness_root, self.project)

        def held(entry):
            if self.view.hold is not None and not self._falls_back() and self._on_fable(entry):
                return True
            return self._rung_held(entry) is not None

        def free(entry):
            return self.resources_free(entry) and not self._needs_tools(entry)

        def pick():
            return schedule.pick(
                graph, running=running, slots=max(0, self._slots() - busy), action=self.action,
                root=self.project, free=free, classes=classes,
                held=held, autonomy=autonomy, decider=decider,
            )

        picks = pick()
        if any(self._on_fable(entry) for entry in picks) and self._read_usage_before_fable():
            picks = pick()  # the reading may have begun the hold or moved the action: pick again under what it says
        waiting = []
        for entry in tickets.frontier(graph):
            if schedule.holds_model_work(self.action) or schedule.awaits_owner(entry, autonomy, decider):
                continue
            if self.view.hold is not None and not self._falls_back() and self._on_fable(entry):
                self._held_back("ticket %d" % entry["id"])
            holding = self._rung_held(entry)
            if holding is not None:
                waiting.append("  ticket %d waits: its rung's model is not served, and decision ticket %d holds that rung"
                               % (entry["id"], holding))
        if tuple(waiting) != self._said_held_rungs:  # a hold lasts until the owner answers; the wait is said on change
            for line in waiting:
                self.say(line)
            self._said_held_rungs = tuple(waiting)
        tools = tuple("  ticket %d waits: %s" % (entry["id"], "; ".join(self.software.waiting.get(entry["id"]) or
                                                                         ["it needs %s" % ", ".join(self._needs_tools(entry))]))
                      for entry in tickets.frontier(graph) if self._needs_tools(entry))
        if tools != self._said_software:  # a ticket waits for its tools until they are recorded; the wait is said on change
            for line in tools:
                self.say(line)
            self._said_software = tools
        return picks

    def _launch_rung(self, identifier, rung):
        """The rung this ticket's next attempt runs on: its level's, stepped down one at `cheap_at` (decision 16).

        The windows the rung's own family reads decide (`pacing.rung_action`, folded into `action`
        and `fable_action` by `_pace`), and the floors of `stepped_down` hold. An attempt that is
        itself a tier up of the escalation chain runs on the rung it climbed to whatever the windows
        read, or pacing would step the escalation back down and cancel it.
        """
        if not schedule.steps_down(self._rung_action(rung)) or self._climbed(identifier):
            return rung
        return stepped_down(self.policy, rung)

    def _tier_ran(self, rung, difficulty, budget=None):
        """The tier of a session already under way: the rung `ticket_launched` named, else its difficulty's.

        A session is resumed and re-adopted on the model it was launched on, and a launch stepped down
        one rung at `cheap_at` (decision 16) ran below its level's rung. A journal written before the
        rung ladder carries no rung, and a rung this policy no longer has is read as its level's.
        """
        if rung is not None:
            try:
                return rung_tier(self.policy, rung, budget)
            except ConductorError:
                pass
        return tier_for(self.policy, difficulty, budget)

    def _rung_action(self, rung):
        """The pacing action a launch on this rung runs under: `fable_action` for a Fable rung, `action` for every other."""
        return self.fable_action if rung_family(self.policy, rung) == pacing.FABLE else self.action

    def _climbed(self, identifier):
        """Whether the escalation chain has taken this ticket up a tier, which pacing never steps back down."""
        known = self.view.tickets.get(identifier)
        return known is not None and bool(known.taken(TIER_UP))

    def _rung_held(self, entry):
        """The decision ticket holding the rung this ticket would launch at, or None when nothing holds it (decision 16).

        A rung is held from the not-served failure that asked the owner about it until that ask is answered, so a
        ticket at that rung waits, a tier up onto it waits with it, and every other rung goes on launching.
        """
        held = self.view.held_rungs()
        if not held:
            return None
        rung = entry.get("rung")  # the effective rung `_graph` put on the entry, which a tier up may have lifted
        if rung is None:
            try:
                rung = rung_of(self.policy, entry.get("difficulty"))
            except ConductorError:
                return None  # the launch fails on the missing rung, and says so there
        return held.get(rung)

    def _on_fable(self, entry):
        """Whether a ticket launches on Fable: the rung its next attempt launches on is on Fable (decisions 15 and 16).

        The rung is the one `_graph` put on the entry, which a tier up may have lifted past the level's own;
        an entry from anywhere else falls back to the tier of its difficulty.
        """
        try:
            rung = entry.get("rung")
            tier = rung_tier(self.policy, rung) if rung is not None else tier_for(self.policy, entry.get("difficulty"))
            return tier.family == pacing.FABLE
        except ConductorError:
            return False  # the launch fails on the missing tier, and says so there

    def _read_usage_before_fable(self):
        """Read `/usage` before this wave starts Fable work, once a wave and only while no hold stands; whether it read.

        Reading `/usage` takes no turn, so it is read before any wave that would launch Fable work
        (decision 15): a week spent since the last reading begins the hold before a launch is refused.
        The reading paces the run as well, so a caller that asked whether it may launch has to ask again.
        """
        if self.view.hold is not None or self._usage_wave == self.number:
            return False
        self._usage_wave = self.number
        self._read_usage()
        self._pace()
        return True

    def _fable_held(self):
        """Whether the hold on Fable's weekly window stands, reading `/usage` first when this wave has not.

        A refusal a session that answered carried is folded first, whenever it came: a stall's replan starts at
        the end of the very wave whose decider carried one, before the next wave's fold (the M5 overnight run).
        """
        self._fold_answered_refusals()
        self._read_usage_before_fable()
        return self.view.hold is not None

    def _held_on_fable(self, request):
        """Whether a session waits for the hold: it runs on Fable or defines an agent on Fable, and the hold stands."""
        return request is not None and worker.launches_on(request, pacing.FABLE) and self._fable_held()

    def _falls_back(self):
        """Whether Fable work falls back to Opus now: the hold stands and the consent falls back (decision 15).

        The consent is `project.fallback_consent`'s: a `control model_fallback` this run heard, else
        `harness.json`, read once a wave, so a changed consent applies at the next wave and one wave
        never falls back for one launch and waits for the next. `auto` falls back and `wait` waits;
        `ask`, and a project without the key, falls back once the ask about the hold's window is
        answered `fall back` or `always fall back` (`project.falls_back_now`), and waits until then.
        """
        if self.view.hold is None:
            return False
        if self._consent_wave != self.number:
            consent = consent_for(self.project, self.view)[0]
            self._consent, self._consent_wave = (consent, falls_back_now(consent, self.view)), self.number
        return self._consent[1]

    def _held_back(self, what):
        """Name a launch on Fable the hold dropped in this wave, for the ask of decision 15 (`_ask_owner`)."""
        if what not in self._dropped:
            self._dropped.append(what)

    def _ask_owner(self):
        """Under the fallback consent `ask`, open the ask about the hold's window once the hold dropped a launch (decision 15).

        One decision ticket per spent window, keyed by the hold's `resets_at`: once the journal holds an ask about
        that window nothing is opened again, and `open_decision`'s origin finishes one a crash left half written. A
        spent week with no Fable work waiting drops nothing and asks nothing. `ask` covers a project without the key.
        """
        dropped, self._dropped = self._dropped, []
        if not dropped or self.view.hold is None:
            return
        resets = self.view.hold.get("resets_at")
        if resets is None or self.view.ask_for(resets) is not None or consent_for(self.project, self.view)[0] != pacing.ASK:
            return
        try:
            report = decisions.open_fable_ask(self.project, resets, dropped, self.clock(), self.policy, notify=self.notify)
        except (ValueError, OSError) as failure:
            self.say("  the ask about Fable's weekly window could not be opened: %s" % failure)
            return
        self._tail()
        self.say("  Fable's weekly window is spent until %s and the consent asks: decision ticket %d asks the owner whether %s "
                 "falls back to Opus" % (resets, report["ticket"], ", ".join(dropped)))

    def _settle_asks(self):
        """Answer each ask of decision 15 nobody answered that the conductor closes, as a `decision` with `decided_by: conductor`.

        At the first wave past the reset of the window it asks about, or at a wave whose consent no longer asks
        (a `control model_fallback` set `auto` or `wait`, read as `_falls_back` reads it, so a consent set back to
        `ask` before the wave closes nothing), it is closed with `answer: superseded`, and Fable work goes on as the
        consent says. On a project that never recorded a consent, under autonomy `autonomous`, it is answered
        `fall back` for its window once `policy.model_fallback.ask_timeout_hours` passed (`project.ask_falls_back_at`);
        an explicit `ask` never times out. `_apply_answers` then closes the ticket as it closes any answered one.
        """
        now, closed = self.clock(), False
        consent = consent_for(self.project, self.view)[0] if self.view.asks else None
        for identifier, ask in sorted(self.view.asks.items()):
            if identifier in self.view.answers:
                continue
            resets = pacing.epoch(ask["resets_at"])
            if resets is not None and resets <= now:
                answer, why = pacing.SUPERSEDED, "Fable's weekly window reset at %s before the ask was answered" % ask["resets_at"]
            elif consent != pacing.ASK:
                answer, why = pacing.SUPERSEDED, "the fallback consent was set to %s while the ask was open" % consent
            else:
                try:
                    harness = read_harness(self.project)
                except (ProjectError, ValueError, OSError):
                    harness = {}
                at = ask_falls_back_at(harness, self.view, identifier, self._autonomy(), self.policy)
                if at is None or pacing.epoch(at) > now:
                    continue
                answer, why = pacing.FALL_BACK, (
                    "no answer within policy.model_fallback.ask_timeout_hours (%g) on a project that never recorded a fallback "
                    "consent, under autonomy autonomous: Fable work falls back to Opus until %s"
                    % (pacing.ask_hours(self.policy)[1], ask["resets_at"]))
            if decisions.close_ask(self.project, identifier, answer, why) is not None:
                closed = True
                self.say("  ticket %d, the ask about Fable's weekly window, closed by the conductor: %s (%s)" % (identifier, answer, why))
        if closed:
            self._tail()
            self._consent_wave = None  # a timeout's `fall back` is read again before this wave launches anything

    def _answered_frontier(self, fields, known):
        """Act on the answer to an empty-frontier ticket at its closing (ticket 87).

        `park it` and `drop it` close the objective, the owner's word; `replan for it` is owed to the planner
        (`_replan_objectives`); `answer it as it stands` is handed to the fresh verifier's path of decision 17, and the
        objective stays open until that path writes its answer. An answer that picks none of the four applies nothing.
        """
        identifier = stopping.frontier_objective(fields.get("origin"))
        if identifier is None:
            return
        choice = stopping.frontier_choice(known.get("answer"))
        if choice in (stopping.PARK, stopping.DROP):
            status = "parked" if choice == stopping.PARK else "dropped"
            by = "decider" if known.get("decided_by") == "decider" else "owner"
            try:
                records = objectives.read_objectives(self.project)
                found = objectives.named(records, identifier)
                if found is not None and objectives.is_open(found):
                    objectives.change_objective(self.project, identifier, status, by, answer="the frontier emptied with it open, and "
                                                "the %s chose to %s it (ticket %d)" % (by, choice.split()[0], fields["id"]))
                    self._tail()
            except (objectives.ObjectivesUnreadable, objectives.ObjectiveError, ValueError, OSError) as failure:
                self.say("  ticket %d: %s could not be %s: %s" % (fields["id"], identifier, status, failure))
                return
            self.say("  ticket %d: %s is %s" % (fields["id"], identifier, status))
        elif choice == stopping.REPLAN:
            self.say("  ticket %d: the planner replans for %s" % (fields["id"], identifier))
        elif choice == stopping.ANSWER:
            self.say("  ticket %d: %s is to be answered as it stands by a fresh verifier; it stays open until that answer is written"
                     % (fields["id"], identifier))
        else:
            self.say("  ticket %d: the answer picks none of %s, so nothing is applied to %s"
                     % (fields["id"], ", ".join(stopping.FRONTIER_OPTIONS), identifier))

    def _empty_frontier(self, autonomy, decider_ready):
        """At an empty frontier, the tickets the stopping rule asks for: `(takes, notice)`.

        `takes` is True when the decider takes them at the next wave; `notice` the end notice the run's end sends, or None.

        Under `stop_when: frontier`, or with no open objective the rule waits on, nothing is asked. Otherwise one
        decision ticket per such objective is opened, once per empty frontier (`stopping.empty_frontier_asks`).
        Under `autonomous`, with a decider, the run goes on so the decider answers them in one session; under
        `interactive` and `checkpoints` they wait for the owner, the run ends `frontier_empty`, and the tick
        relaunches it after the answer. The run's end says which objectives stay open.
        """
        harness = self._harness_for_rule()
        if harness is None:
            return False, None
        rule = stopping.rule_of(harness)
        records = self._objective_records() or []
        still = [record["id"] for record in records if objectives.is_open(record)]
        waiting = stopping.waited(rule, records)
        if rule == stopping.FRONTIER or not waiting:
            if not still:
                return False, None
            return False, self._frontier_notice("the frontier is empty under the stopping rule %s; the objectives still open: %s"
                                                % (stopping.describe_rule(rule), ", ".join(still)))
        try:
            events, _ = self.ledger.read_events()
            opened, standing, settled = stopping.empty_frontier_asks(self.project, waiting, rule, events,
                                                                     tickets.read_tickets(self.project), notify=self.notify)
        except (ValueError, OSError) as failure:
            self.say("  the empty frontier's decision tickets could not be opened: %s" % failure)
            return False, None
        self._tail()
        for identifier in opened:
            self.say("  the frontier is empty with an objective the stopping rule waits on: decision ticket %d asks what to do" % identifier)
        asked = opened + standing
        # The decider takes an open one that is not human-only: one it was refused is the owner's now, and one it could not
        # answer (`needs_human`) waits for a person, so neither keeps the run going.
        takable = {fields["id"] for fields in tickets.read_tickets(self.project)
                   if fields["status"] == "open" and not fields.get("human_only")}
        if [identifier for identifier in asked if identifier in takable] and autonomy == schedule.AUTONOMOUS and decider_ready:
            return True, None
        words = ["the frontier is empty and the stopping rule %s waits on %s" % (stopping.describe_rule(rule),
                                                                                 ", ".join(record["id"] for record in waiting))]
        if asked:
            words.append("decision ticket(s) %s wait for the owner" % ", ".join(str(identifier) for identifier in asked))
        if settled:
            words.append("%s %s answered at the last empty frontier and nothing was created since" % (
                ", ".join(settled), "was" if len(settled) == 1 else "were"))
        return False, self._frontier_notice("; ".join(words))

    def _frontier_notice(self, words):
        """The end notice of a run whose frontier emptied with objectives open: said now, sent once `run_ended` is journaled."""
        self.say("  " + words)
        return words

    def _harness_for_rule(self):
        """`harness.json` for the stopping rule and the budgets, or None when it cannot be read, which is said once per run.

        A file that cannot be read ends nothing: falling back to the default rule could end a run its own rule would not.
        """
        try:
            harness = read_harness(self.project)
        except (ProjectError, ValueError, OSError) as failure:
            if str(failure) != self._harness_trouble:
                self._harness_trouble = str(failure)
                self.say("  harness.json cannot be read, so the stopping rule and the budgets end nothing until it reads: %s" % failure)
            return None
        self._harness_trouble = None
        return harness

    def _owed_objective_replans(self):
        """The empty-frontier tickets answered `replan for it` whose replan is still owed, by ticket id.

        Owed until this run cut it, or until a cut was written after the answer (`plan.json`'s `cut_at`).
        """
        from wayline import plan
        answers = {identifier: known for identifier, known in self.view.answers.items()
                   if identifier not in self._objective_replans and stopping.frontier_choice(known.get("answer")) == stopping.REPLAN}
        if not answers:
            return {}
        found = {fields["id"]: fields for fields in tickets.read_tickets(self.project)
                 if fields["id"] in answers and stopping.frontier_objective(fields.get("origin")) is not None}
        if not found:
            return {}
        record = plan.read_plan(self.project) or {}
        # Only a revise is a replan for an objective: a split the escalation wrote meanwhile replans nothing of it.
        cut_at = str(record.get("cut_at") or "") if record.get("cut") == "revise" else ""
        if any(identifier not in self._answer_stamps for identifier in found):
            events, _ = self.ledger.read_events()
            for event in events:
                payload = event.get("payload") or {}
                if event.get("event") == "decision" and payload.get("ticket") in found:
                    self._answer_stamps[payload["ticket"]] = event.get("ts") or ""
        return {identifier: fields for identifier, fields in found.items() if self._answer_stamps.get(identifier, "") > cut_at}

    def _replan_objectives(self, result):
        """The planner's re-cut for the objectives an empty frontier's tickets were answered `replan for it` about (ticket 87).

        One cut covers every objective owed, a revise that cuts new tickets serving each within the spec; it waits,
        like any model work, while pacing or the hold allows none.
        """
        owed = self._owed_objective_replans()
        if not owed or self._holds_launches() or self.action != schedule.NORMAL:
            return
        from wayline import plan
        named = sorted({stopping.frontier_objective(fields.get("origin")) for fields in owed.values()})
        records = self._objective_records() or []
        about = "; ".join("%s, \"%s\"" % (identifier, (objectives.named(records, identifier) or {}).get("text", "")) for identifier in named)
        change = ("Replan for the open objective(s) %s: the frontier emptied with them open and the stopping rule waits on them. "
                  "Cut new tickets that serve them within the spec; work already done stands." % about)
        outcome = self._launch_cut(plan.Cut("revise", change=change), "the planner's replan for %s" % ", ".join(named))
        if outcome is None:
            return
        self._objective_replans.update(owed)
        self._tail()
        if isinstance(outcome, BaseException):
            words = "the planner could not replan for %s: %s" % (", ".join(named), outcome)
            self.say("  " + words)
            # Not tried again every wave: the owner is told, and answers again (wayline rerun on the ticket) once it is mended.
            # A notice about the decision answered, never a run's end, which has its one notice (ticket 89).
            self.notify(decisions.DECISION, "%s: %s; wayline rerun %s asks again" % (
                self.project.name, words, " / ".join(str(identifier) for identifier in sorted(owed))), self.project, None)
            return
        result.escalated.append((None, REPLAN))
        self.say("  the planner replanned for %s: ticket(s) %s written" % (
            ", ".join(named), ", ".join(str(item) for item in outcome.get("tickets") or []) or "none"))

    def _answered_ask(self, identifier, known):
        """Say what the owner's answer to the ask of decision 15 does, at its closing; one that matches no option is also sent to the owner."""
        ask = self.view.asks.get(identifier)
        if ask is None or known.get("decided_by") != "human":
            return
        choice = pacing.ask_choice(known.get("answer"))
        if choice is not None:
            does = "falls back to Opus" if pacing.ask_falls_back(choice) else "waits for the reset"
            also = "; the fallback consent is now %s" % pacing.ALWAYS[choice] if choice in pacing.ALWAYS else ""
            self.say("  ticket %d: Fable work %s while Fable's weekly window is spent until %s%s" % (identifier, does, ask["resets_at"], also))
            return
        text = ("%s: the answer to decision ticket %d, \"%s\", matches none of %s, so it counts as wait: Fable work waits for the "
                "reset at %s. wayline rerun %d asks again, and wayline switch --fallback auto falls back from the next wave."
                % (self.project.name, identifier, known.get("answer"), ", ".join(pacing.ASK_OPTIONS), ask["resets_at"], identifier))
        self.say("  ticket %d: the answer matches no option and counts as wait; the owner is told" % identifier)
        self.notify(decisions.DECISION, text, self.project, identifier)

    def _busy(self, besides=None):
        """How many worker slots are taken now, counting every attempt this conductor owes a session (ticket 59).

        `max_parallel_workers` holds at every moment, not only at the moment a wave picks, so a
        session that returned between wave step 3 (the poll) and step 9 (the pick) still holds its
        slot: the wave after carries it, and may resume it. `besides` is the attempt about to take
        a slot itself, which is never counted against its own session.
        """
        return sum(1 for attempt in self.flight.values() if attempt is not besides and self._takes_a_slot(attempt))

    def _takes_a_slot(self, attempt):
        """Whether the attempt holds one of `max_parallel_workers` worker slots now (ticket 59).

        It holds one while a session of its own runs or waits to be carried, and while it waits to
        start the session it wants, because that session starts as soon as this wave or the next
        allows. Two things wait and hold nothing: an integration, whose integrator the wave that
        carries it launches rather than the attempt, and a session the hold on Fable's weekly window
        keeps waiting, whose slot goes to whatever else is launchable (decision 15, ticket 54). Both
        take a slot when they do start, which `_start_wanted` waits for.
        """
        if attempt.want is None:
            return attempt.has_a_session
        if attempt.want.stage == INTEGRATE:
            return False
        return not (self._held_on_fable(attempt.request) and not self._falls_back())

    def _free_slot(self, attempt):
        """Whether a slot is free for the session this attempt waits to start; the wait is said once.

        What is counted here is the sessions that run now, not the attempts that wait, so two
        attempts waiting for one slot never keep each other out: the first to be looked at starts,
        and its session is what the next one waits for. They can outnumber the slots (the hold on
        Fable's weekly window gives a waiting session's slot away, a restart re-adopts what the
        journal owes, `max_parallel_workers` is lowered between runs), and counting one waiting
        attempt against another would then leave every one of them waiting for good.
        """
        taken = sum(1 for other in self.flight.values() if other is not attempt and other.has_a_session)
        slots = self._slots()
        if taken < slots:
            return True
        if not attempt.waiting_for_slot:
            attempt.waiting_for_slot = True
            self.say("  ticket %d: its %s waits for a free worker slot (%d of %d taken)"
                     % (attempt.id, "relaunch" if attempt.want.stage == RELAUNCH else "resume", taken, slots))
        return False

    def _waits_for(self, attempt):
        """What the session this attempt did not start is waiting for, for the line its caller says."""
        return " once a worker slot is free" if attempt.waiting_for_slot else " once the run may launch again"

    def _slots(self):
        """`policy.max_parallel_workers`: how many workers this conductor runs at once."""
        slots = self.policy.get("max_parallel_workers", 1)
        if isinstance(slots, bool) or not isinstance(slots, int) or slots < 1:
            raise ConductorError("policy.max_parallel_workers is %r; it is a whole number of workers, at least 1"
                                 % (slots,))
        return slots

    def _objective_classes(self):
        """The objective class of every ticket, by id, which the pick order reads after the critical path (ticket 81).

        A ticket serves the objectives it names and the goal it reports; which of them are open is
        `objectives.json`'s, the one record keep-if-better and the plan read too, and which the stopping
        rule waits on is `harness.json`'s `stop_when` (ticket 87: every open one under `objectives`, the
        open ones it names under a list, none under `frontier`). A record that cannot be read is said and
        counts no objective open, so every ticket is class 2 and the wave goes on in the order it had
        before objectives. `graph.json` carries the scheduling fields of decision 2 and `objectives` is
        not one of them, so the ticket files answer this; the conductor reads them for every launch anyway.
        """
        try:
            records = objectives.read_objectives(self.project)
        except objectives.ObjectivesUnreadable as failure:
            self.say("  %s; the pick order counts no objective open" % failure)
            records = []
        try:
            rule = stopping.rule_of(read_harness(self.project))
        except (ProjectError, ValueError, OSError):
            rule = stopping.OBJECTIVES
        pursued = {record["id"] for record in records if objectives.is_open(record)}
        waited = {record["id"] for record in stopping.waited(rule, records)}
        return {ticket["id"]: schedule.objective_class(objectives.served(ticket), pursued, waited)
                for ticket in tickets.read_tickets(self.project)}

    # --- the tickets of one wave ---

    def _start(self, picks, result):
        """Prepare every pick, start its session, and return once each worker process has started.

        The preparation is serial, because `git worktree add` writes the repository the other
        launches read and each launch says its line in pick order. The sessions then run in threads
        of their own; the wave waits only until each process exists or its launch failed, so
        `launched` names exactly the tickets whose `ticket_launched` was journaled.
        """
        attempts, promotions = [], []
        for entry in picks:
            ticket, body = self._ticket(entry["id"])
            if ticket["kind"] == tickets.DOSSIER:
                promotions.append(ticket)  # no worker session: a promotion through absorb, run once the workers started (ticket 98)
                continue
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
        for ticket in promotions:
            self._beat()
            self._run_dossier(ticket, result)
            self._beat()

    def _run_dossier(self, ticket, result):
        """Run a `dossier` ticket as a promotion through absorb, with no worker session (decision 17; ticket 98).

        The level-2 read runs in the wave, as the decider's session does: it is code's and the absorb session's
        work, not a worker's, so no `ticket_launched` is journaled and nothing is owed a restarted conductor. Its
        `promoted` and `absorbed` are journaled by the promotion and the read, then `ticket_done`; a read that fails
        its coverage audit hands the ticket to a person, since no session of its own could be resumed. A promotion
        beyond the phase's budget opens its decision ticket and the dossier ticket waits on it, blocked by it.
        """
        from wayline import absorb
        identifier = ticket["id"]
        self.say("wave %d: ticket %d %s (a promotion through absorb, no worker session)" % (self.number, identifier, ticket["title"]))
        answers = {number: (answer or {}).get("answer") for number, answer in self.view.answers.items()}
        try:
            run = absorb.run_dossier_ticket(self.project, ticket, tickets_by_id={fields["id"]: fields for fields in tickets.read_tickets(self.project)},
                                            answers=answers, absorb=self.absorb_dossier, inventory=self.dossier_inventory, ledger=self.ledger)
        except (ValueError, OSError) as failure:
            run = {"outcome": absorb.FAILED, "slug": None, "reason": str(failure), "decision": None}
        if run["outcome"] == absorb.WAITS:
            fields, body = self._ticket(identifier)
            blocked = sorted(set(fields.get("blocked_by") or []) | {run["decision"]})
            tickets.write_ticket(self.ledger, dict(fields, blocked_by=blocked), body)
            self.say("  ticket %d waits on decision ticket %d: promoting %s is %s" % (identifier, run["decision"], run["slug"], run["reason"]))
            return
        if run["outcome"] == absorb.FAILED:
            question = "its promotion through absorb did not finish: %s" % run["reason"]
            self.ledger.append_event(TICKET_NEEDS_HUMAN, {"ticket": identifier, "question": question}, ticket=identifier)
            self._set_status(identifier, "needs_human", ["**Promotion:** %s." % run["reason"]])
            self.say("  ticket %d needs a person: %s" % (identifier, question))
            self._tell_owner(identifier, question)
            result.failed.append(identifier)
            return
        note = ("**Promotion:** the promotion of `%s` was answered no; nothing was read." % run["slug"] if run["outcome"] == absorb.DECLINED
                else "**Promotion:** `%s` read in full at level 2." % run["slug"])
        self.ledger.append_event(TICKET_DONE, {"ticket": identifier}, ticket=identifier)
        self._set_status(identifier, "done", [note])
        self.say("  ticket %d done: %s" % (identifier, note.split(":** ", 1)[1]))
        result.done.append(identifier)

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
        attempt.limits_read = 0
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
            if known is not None and known.step == TIER_UP and ticket["status"] == "open":
                continue  # opened again for its tier up, which the next `ticket_launched` journals
            if ticket["kind"] == tickets.DECISION and ticket["id"] in self.view.answers:
                continue  # an answered decision ticket is closed by `_apply_answers`, once, with what it says and does
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
            if identifier in self.view.discarded:
                continue  # keep-if-better keeps a discarded change's branch and worktree (ticket 39)
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
            if identifier in self.view.discarded:
                continue  # a discarded change is not on `main`, and earns no verdict (ticket 39)
            if any(queued.ticket == identifier for queued in self.verdicts):
                continue
            ticket, _ = self._ticket(identifier)
            difficulty = launched.difficulty if launched.difficulty is not None else entry.get("difficulty", ticket["difficulty"])
            earned, asks = gates.owed_asks(ticket, difficulty, launched.model,
                                           self.view.integrated.get(identifier), self.view.passed(identifier), rung=launched.rung,
                                           no_diff=identifier in self.view.integrated_empty,
                                           code_rule=methods.read_code_rule(worker.session_dir(self.project, identifier, launched.number)),
                                           inherited=self._inherited_items(identifier, launched.number))
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
        # The difficulty it launched at: a raise journaled since does not move an attempt already under way.
        attempt.difficulty = replayed.difficulty if replayed.difficulty is not None else entry.get("difficulty", attempt.ticket["difficulty"])
        # The rung it launched on, which a step down at `cheap_at` (decision 16) may have put below its level's.
        attempt.tier = self._tier_ran(replayed.rung, attempt.difficulty, attempt.ticket.get("budget"))
        if replayed.fallback_from:
            # Its session runs on Opus and is resumed there, whatever the hold and the consent say now.
            attempt.tier, attempt.fallback_from = fallback_tier(self.policy, attempt.tier), replayed.fallback_from
        attempt.stage, attempt.resumed = replayed.stage, bool(replayed.spent)
        attempt.session_id, attempt.session_journaled = replayed.session_id, replayed.session_id is not None
        self._prepare(attempt, self._fallback_notes(attempt) if replayed.fallback_from else ())
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
            attempt.envelope = worker.read_envelope(attempt.stream_path, attempt.request.schema_path, record=True)
            attempt.result_journaled = True
            self.say("  ticket %d: carrying the result its worker returned before the restart" % attempt.id)
        elif attempt.tail.result is not None or self._alive(attempt):
            self._journal_resumed(attempt, replay.READOPTED)
            attempt.adopted = True
            self.say("  ticket %d: re-adopted its worker (pid %s)" % (attempt.id, attempt.pid))
        else:
            self._died(attempt, session)

    def _died(self, attempt, session, why=RESUME_DIED, what="its worker died"):
        """A session that ended without its result: resumed by session id, or relaunched when it had none.

        `why` is what the resume says and `what` is what the conductor says happened: a worker that
        died, or a session a usage limit stopped. Either one waits, like any session that needs a
        model, while the run is paused or stopping.
        """
        if attempt.session_id:
            message = why
            previous = attempt.run_dir / "prompt.md" if session.kind == "resume" and attempt.run_dir else None
            answering = previous.read_text(encoding="utf-8").strip() if previous is not None and previous.is_file() else None
            if answering:
                message += RESUME_DIED_MESSAGE % answering
            attempt.want = _Want(replay.WORKER_DIED, message, answering)
            doing = "%s; resuming session %s" % (what, attempt.session_id)
        else:
            attempt.want = _Want(RELAUNCH)
            doing = "%s before its session started; relaunching it" % what
        self.flight[attempt.id] = attempt
        started = self._start_wanted(attempt)
        if started == FALLEN_BACK:
            return  # a fresh session on Opus took its place, which `_fall_back_session` said
        self.say("  ticket %d: %s%s" % (attempt.id, doing, "" if started else self._waits_for(attempt)))

    def _adopted_returned(self, attempt):
        """Whether a re-adopted session has returned; a dead one without a result is resumed or relaunched.

        The launcher stops the sessions it started at their budget, and a re-adopted worker is nobody's
        child, so the conductor holds it to the same budget (decision 3): past `max_minutes` it is sent
        SIGTERM, then SIGKILL if it outlasts `STOP_WAIT_S`, and once it is gone its session is resumed
        once with "you ran out of time".
        """
        attempt.tail.read()
        if attempt.tail.result is not None:
            attempt.envelope = worker.read_envelope(attempt.stream_path, attempt.request.schema_path, record=True)
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
            resumed_by = attempt.session_id
            started = self._start_wanted(attempt)
            if started != FALLEN_BACK:  # a fresh session on Opus took its place, which `_fall_back_session` said
                self.say("  ticket %d: resuming session %s out of time%s"
                         % (attempt.id, resumed_by, "" if started else self._waits_for(attempt)))
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

    def _prepare(self, attempt, notes=()):
        """The worktree, the prompt, and the request an attempt taken over needs for its next session."""
        self._add_worktree(attempt)
        attempt.prompt = self._prompt(attempt, notes)
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
        and then the first such exception is raised again. A carry frees the worker slot the attempt
        held, so the sessions still waiting for one are looked at again afterwards (ticket 59); that
        is what makes a waiting session start at the first wave with a free slot, whether the slot
        came free before this wave or in it.
        """
        escaped = None
        for identifier in sorted(self.flight):
            attempt = self.flight[identifier]
            try:
                self._journal_session(attempt)
                self._observe(attempt)
                if attempt.running:
                    continue
                if attempt.want is not None:
                    if attempt.want.stage != INTEGRATE:
                        self._start_wanted(attempt)
                        continue
                    if self._integrator_waits(attempt):
                        continue
                    attempt.want = None  # the integration it waited for may launch its integrator now

                if attempt.adopted and not self._adopted_returned(attempt):
                    continue
                self._carry(attempt, result)
            except Exception as failure:  # not one of the two a ticket can be failed on
                self.flight.pop(identifier, None)
                escaped = failure if escaped is None else escaped
        for identifier in sorted(self.flight):
            attempt = self.flight[identifier]
            try:
                if attempt.want is not None and attempt.want.stage != INTEGRATE and not attempt.running:
                    self._start_wanted(attempt)  # a carry above may have freed the slot it waits for
            except Exception as failure:
                self.flight.pop(identifier, None)
                escaped = failure if escaped is None else escaped
        if escaped is not None:
            raise escaped

    def _carry(self, attempt, result):
        """What a returned session came to, counted into the wave; nothing expected raises out.

        A session a usage limit stopped without a usable result is no outcome at all: it is the
        window's doing, so it spends no gate, is not counted as settling the wave, and waits to be
        resumed after the reset (`_wait_out`).
        """
        if attempt.thread is not None:
            attempt.thread.join()
        outcome, limited = "failed", False
        try:
            if attempt.failure is not None:
                raise attempt.failure
            if attempt.envelope is None:
                raise ConductorError("the worker thread ended without a result and without an error")
            attempt.session_id = attempt.session_id or attempt.envelope.session_id
            self._journal_session(attempt)
            self._observe(attempt)
            limit, written = self._limit_of(attempt)
            if limit is not None and limit.signal != pacing.EVENT_SIGNAL:  # a rejected event paused the run as it was read
                self._pause(limit, "ticket %d's worker" % attempt.id, written)
            limited = limit is not None and not attempt.envelope.valid
            outcome = self._wait_out(attempt) if limited else self._advance(attempt)
        except (ValueError, OSError) as failure:  # a launch, a ticket file, or a git step
            self._fail(attempt, str(failure), "needs_human")
        finally:
            # An integration left waiting for the run to allow model work is counted by the wave that concludes it.
            if attempt.started and not limited and not attempt.integrating:
                result.outcomes += 1
        if outcome == "session":
            self.flight[attempt.id] = attempt
            return
        self.flight.pop(attempt.id, None)
        result.findings += attempt.findings
        result.kept += int(attempt.kept)
        if outcome not in ("done", "running"):
            self._cancel_jobs(attempt.id)  # the jobs a failed attempt wrote never run
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
        # The level is what the difficulty adjustment counts failures by; the rung is what the attempt runs on,
        # and a tier up has moved the second without moving the first (decision 16).
        attempt.difficulty = entry.get("difficulty", attempt.ticket["difficulty"])
        rung = self._effective_rung(attempt.ticket)
        running = self._launch_rung(attempt.id, rung)
        attempt.stepped_from = rung_tier(self.policy, rung, attempt.ticket.get("budget")).label if running != rung else None
        attempt.tier = rung_tier(self.policy, running, attempt.ticket.get("budget"))
        if attempt.tier.family == pacing.FABLE and self._falls_back():
            attempt.fallback_from, attempt.tier = attempt.tier.label, fallback_tier(self.policy, attempt.tier)
        self._add_worktree(attempt)
        self._write_ticket(attempt, "running")
        self._keep_last_failure(attempt)
        attempt.prompt = self._prompt(attempt)
        attempt.request = self._request(attempt, attempt.prompt)
        own = attempt.ticket.get("pinned_difficulty") or attempt.ticket["difficulty"]
        climbed = rung != rung_of(self.policy, attempt.difficulty)
        self.say("wave %d: ticket %d %s (%s, %s, attempt %d)%s%s%s%s" % (
            self.number, attempt.id, attempt.ticket["title"], attempt.role.name,
            attempt.tier.label, attempt.number,
            ", difficulty %s raised from %s" % (attempt.difficulty, own) if attempt.difficulty != own else "",
            ", one rung up the ladder" if climbed else "",
            ", stepping down one rung from %s" % attempt.stepped_from if attempt.stepped_from else "",
            ", falling back from %s" % attempt.fallback_from if attempt.fallback_from else ""))

    def _prompt(self, attempt, notes=()):
        """The prompt of decision 3; a locator resolves in the worktree first, then in the project."""
        return worker.assemble_prompt(
            attempt.ticket, attempt.role,
            roots=(attempt.worktree, self.project),
            max_chars=attempt.tier.context_chars,
            budget={"max_turns": attempt.tier.max_turns, "max_minutes": attempt.tier.max_minutes},
            consult_max=(self.policy.get("consultant") or {}).get("max_questions_per_ticket", worker.CONSULT_MAX),
            scout_max=(self.policy.get("scout") or {}).get("calls_per_ticket", worker.SCOUT_MAX),
            notes=notes,
            failure=self._last_failure(attempt),
            sections=self._paper_pack(attempt),
        )

    def _paper_pack(self, attempt):
        """The context pack's part on the paper: the declared sections, the verification, the concerns of the ticket's
        objectives (ticket 96), and their outline entries with the owner's notes (ticket 104), together kept to the tier's
        context cap."""
        from wayline import outline  # the outline reads every part of the ledger
        cap = attempt.tier.context_chars
        parts = [sections.pack_text(self.ledger, sections.declared(attempt.ticket), cap)]
        served = objectives.served(attempt.ticket)
        for build in (lambda left: verification.pack_text(self.ledger, attempt.ticket, left),
                      lambda left: concerns.pack_text(self.ledger, served, left),
                      lambda left: outline.pack_text(self.ledger, served, left)):
            left = None if cap is None else max(0, int(cap) - sum(len(part) for part in parts))
            parts.append(build(left))
        return "\n\n".join(part for part in parts if part)

    def _keep_last_failure(self, attempt):
        """Write `failure.json` for an attempt a tier up launches: the failure output of the attempt before it (ticket 68).

        A tier up opens a fresh session, which would otherwise start from the ticket as the planner wrote it,
        find the earlier work passing its machine criteria, and return `done` with nothing mended.
        """
        known = self.view.tickets.get(attempt.id)
        if known is None or not known.steps or known.steps[-1] != TIER_UP:
            return
        text = TIER_UP_FAILED % (known.failure or "no reason was recorded", tickets.relative_path(attempt.ticket))
        self.ledger.write_json(self._attempt_dir(attempt).relative_to(self.ledger.research) / LAST_FAILURE,
                               {"failure": text})

    def _last_failure(self, attempt):
        """The failure a tier-up attempt carries in its prompt, from `failure.json`; None for any other attempt."""
        try:
            text = json.loads((self._attempt_dir(attempt) / LAST_FAILURE).read_text(encoding="utf-8")).get("failure")
        except (OSError, ValueError, AttributeError):
            return None
        return text if isinstance(text, str) else None

    def _request(self, attempt, prompt):
        """The `LaunchRequest` of decision 3: the role's tools, the rendered guards, both add-dirs.

        An attempt that fell back launches every agent it defines on Fable on Opus with it (decision 15).
        """
        run_dir = worker.session_dir(self.project, attempt.id, attempt.number)
        settings = gates.write_worker_settings(run_dir / "settings.json", self.harness_root)
        request = worker.LaunchRequest(
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
        if attempt.fallback_from:
            # The role's own agent is on the tier's model, Opus already; this moves any other agent the launch defines on Fable.
            request, _ = worker.fall_back(request)
        return request

    def _journal_launch(self, attempt, started):
        attempt.started = True
        payload = {
            "ticket": attempt.id, "attempt": attempt.number, "role": attempt.role.name,
            "model": attempt.tier.model, "effort": attempt.tier.effort,
            "skills": list(attempt.ticket.get("skills") or []),
            "worktree": str(attempt.worktree), "pid": started.pid,
            "context_chars": attempt.prompt.context_chars, "prompt_sha256": attempt.prompt.sha256,
            "difficulty": attempt.difficulty, "rung": attempt.tier.rung,
        }
        if attempt.fallback_from:
            payload["fallback_from"] = attempt.fallback_from
        # The code the attempt runs at (decision 17): its worktree's HEAD, which a later attempt's reused branch keeps.
        commit = code_repository.head_commit(attempt.worktree)
        if commit:
            payload["commit"] = commit
        self.ledger.append_event(TICKET_LAUNCHED, payload, ticket=attempt.id)

    # --- jobs (decision 6, wave step 2; ticket 19) ---

    def _runner(self):
        """The job runner, made once a wave has a job to poll or launch; its backend is `WAYLINE_JOBS`'s or the machine's."""
        if self.jobs_runner is None:
            self.jobs_runner = resources.JobRunner(self.project)
        return self.jobs_runner

    def _job_records(self):
        """Every job file under `research/jobs/`, in id order; one that does not read is said and passed over."""
        records = []
        for path in sorted((self.ledger.research / "jobs").glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as failure:
                self.say("  the job file %s does not read: %s" % (path.name, failure))
                continue
            if isinstance(record, dict) and record.get("id"):
                records.append(record)
        return records

    def _owed_jobs(self):
        """`{ticket: (attempt, [job ids])}` for every ticket whose latest attempt is owed its jobs (a running result, integrated)."""
        owed = {}
        for identifier, known in self.view.tickets.items():
            attempt = known.latest
            if attempt is None or attempt.owed != replay.JOBS or known.status != "running":
                continue
            result = attempt.sessions[-1].result or {}
            owed[identifier] = (attempt.number, [str(job) for job in result.get("jobs") or []])
        return owed

    def _jobs_problem(self, attempt):
        """Why a `running` result's jobs cannot be left to the poller, or None: each is a pending job file of this ticket."""
        named = attempt.result.get("jobs") or []
        if not named:
            return "the result says running and names no job; a running result lists the job ids `wayline job add` printed"
        for job in named:
            try:
                record = self.ledger.read_json("jobs/%s.json" % job)
            except (OSError, ValueError):
                return "the result names job %s, and research/jobs/%s.json does not exist; write it with wayline job add" % (job, job)
            if record.get("ticket") != attempt.id:
                return "the result names job %s, which belongs to ticket %s" % (job, record.get("ticket"))
            if record.get("status") != "pending":
                return "the result names job %s, which is %s and not pending; a job is launched by the conductor" % (job, record.get("status"))
        return None

    def _leave_running(self, attempt):
        """A running result whose branch is on `main`: its jobs wait for the poller, and its worktree goes.

        A job path the worker spelled inside its worktree is spelled in the project instead, since the
        worktree is removed and the same files are on `main` now.
        """
        worktree, jobs = str(attempt.worktree), [str(job) for job in attempt.result.get("jobs") or []]
        for job in jobs:
            record = self.ledger.read_json("jobs/%s.json" % job)
            moved = _moved_out_of(record, worktree, str(self.project))
            if moved != record:
                self.ledger.write_json("jobs/%s.json" % job, moved, schema="job")
                self.say("  job %s named paths in the worktree of ticket %d; they now name the project" % (job, attempt.id))
        self._write_ticket(attempt, "running", attempt.result)
        if self._goal_ticket(attempt.ticket):
            self.say("  ticket %d reports the goal's metric: its branch and worktree stay until its jobs are judged" % attempt.id)
        else:
            self._remove_worktree(attempt.id)
        self._tail()
        self.say("  ticket %d is running %d job(s): %s" % (attempt.id, len(jobs), ", ".join(jobs)))

    def _poll_jobs(self, result):
        """Wave step 2: every job launched and not concluded is polled, and each one that ended is concluded.

        A job the journal names as launched (or retried) and nothing since is not concluded, whatever
        its file says: the tick polls jobs too, and writes what it read, and the conclusion (outputs,
        the ladder, the ticket) is this conductor's alone. Then every owed ticket whose jobs all
        exited 0 with outputs that parse is done.
        """
        concluded = False
        for record in self._job_records():
            if (self.view.jobs.get(record["id"]) or {}).get("status") != "running":
                continue
            state = self._job_state(record)
            if state is None or not state.terminal:
                continue
            record = self._runner().read(record["id"]) or record
            # Read again for every job: concluding the one before may have failed its ticket.
            self._conclude_job(record, state, self._owed_jobs(), result)
            concluded = True
        if concluded:
            self._tail()
        for identifier, (number, jobs) in sorted(self._owed_jobs().items()):
            if jobs and all(self._job_done(job) for job in jobs):
                self._close_jobs(identifier, number, jobs, result)

    def _job_state(self, record):
        """What the job is now: polled while its file says running, else what the file already recorded."""
        if record.get("status") == "running":
            try:
                return self._runner().poll(resources.handle_for(record))
            except (resources.JobError, OSError, ValueError) as failure:
                self.say("  job %s could not be polled: %s" % (record["id"], failure))
                return None
        if record.get("status") not in resources.JOB_STATES:
            return None
        attempts = record.get("attempts") or [{}]
        tail = resources.log_tail(record["log"]) if record["status"] in ("oom_gpu", "failed") else None
        result = attempts[-1].get("result")
        reason = "wallclock" if result == "timeout" else (
            "exited %s" % attempts[-1].get("exit_code") if result == "exit-code" else result)
        return resources.JobState(record["status"], result=result, exit_code=attempts[-1].get("exit_code"),
                                  reason=reason, log_tail=tail or None)

    def _job_done(self, job):
        known = self.view.jobs.get(job) or {}
        return known.get("status") == "exited" and known.get("exit_code") == 0

    def _conclude_job(self, record, state, owed, result):
        """One job that ended: its outputs checked and manifested, its ladder stepped, or its failure journaled."""
        job, ticket = record["id"], record["ticket"]
        mine = ticket in owed and job in owed[ticket][1]
        result.outcomes += 1
        if state.name == "exited" and (state.exit_code or 0) == 0:
            problems = [problem for problem in (self._output_problem(record, output) for output in record.get("expected_outputs") or [])
                        if problem is not None]
            self.ledger.append_event(JOB_FINISHED, {"job": job, "exit_code": 0, "seconds": _job_seconds(record),
                                                    "outputs_ok": not problems}, ticket=ticket, job=job)
            self._cleanup_job(record)
            if problems:
                self._job_failed(record, "its outputs do not parse: %s" % "; ".join(problems), "")
                if mine:
                    self._fail_jobs(ticket, owed[ticket], "job %s exited 0 and %s" % (job, "; ".join(problems)), result)
                return
            if mine:
                self._manifest_outputs(record, owed[ticket][0])
                result.jobs_finished += 1
            self.say("  job %s (ticket %d) exited 0 in %ss; outputs %s" % (
                job, ticket, _job_seconds(record), ", ".join(record.get("expected_outputs") or []) or "none expected"))
            return
        tail = (state.log_tail or resources.log_tail(record["log"]))[-LOG_TAIL_CHARS:]
        if state.oom is not None and mine:
            step = self._retry_step(record, state.oom)
            if step is not None:
                self._retry_job(record, state.oom, step)
                return
            why = "the %s OOM ladder is exhausted after %d attempt(s)" % (state.oom, len(record.get("attempts") or []))
        elif state.oom is not None:
            why = "a %s OOM" % state.oom
        else:
            why = state.reason or state.name
        self._cleanup_job(record)
        if record.get("status") == "killed" and not mine:
            return  # cancelled by the harness, which journaled `job_cancelled` then
        self._job_failed(record, why, tail)
        if mine:
            self._fail_jobs(ticket, owed[ticket], "job %s failed: %s" % (job, why), result, tail)

    def _output_problem(self, record, output):
        """`resources.output_problem`, and one more: an output the manifest cannot name lies outside the project."""
        problem = resources.output_problem(record["cwd"], output)
        if problem is not None:
            return problem
        path = Path(output) if os.path.isabs(output) else Path(record["cwd"]) / output
        if not _inside(path, self.project):
            return "%s lies outside the project, so the manifest cannot name it" % output
        return None

    def _manifest_outputs(self, record, number):
        from wayline import provenance  # the provenance module pulls in the gates and the report
        for output in record.get("expected_outputs") or []:
            path = Path(output) if os.path.isabs(output) else Path(record["cwd"]) / output
            relative = os.path.relpath(os.path.realpath(path), os.path.realpath(self.project))
            provenance.register_artifact(self.ledger, relative, record["id"], "t%d-a%d" % (record["ticket"], number), record["ticket"])

    def _job_failed(self, record, reason, tail):
        self.ledger.append_event(JOB_FAILED, {"job": record["id"], "reason": reason, "log_tail": tail},
                                 ticket=record["ticket"], job=record["id"])
        self.say("  job %s (ticket %d) failed: %s" % (record["id"], record["ticket"], reason))

    def _cleanup_job(self, record):
        try:
            self._runner().cleanup(resources.handle_for(record))
        except (resources.JobError, OSError) as failure:
            self.say("  job %s could not be cleaned up: %s" % (record["id"], failure))

    def _retry_step(self, record, oom):
        """The next footprint step after an OOM (decision 6), reading the machine only for a host OOM's doubling."""
        double = (self.policy.get("jobs") or {}).get("host_oom_first_doubles_memory", True)
        cap = 0.0
        if oom == "host" and double and float((record.get("devices") or {}).get("ram_gb") or 0) > 0:
            others = [other for other in self._job_records() if other["status"] == "running" and other["id"] != record["id"]]
            try:
                cap = resources.ram_cap_gb(self._read_readings(), others)
            except (resources.ResourceError, OSError, ValueError) as failure:
                self.say("  the free RAM could not be read (%s); job %s steps its ladder instead" % (failure, record["id"]))
        return resources.next_retry(record, oom, cap, double_first=double)

    def _retry_job(self, record, oom, step):
        """Relaunch an OOM'd job at once on the devices it just freed, under the next step, and journal `job_retried`."""
        job, number = record["id"], len(record.get("attempts") or []) + 1
        self.ledger.append_event(JOB_RETRIED, {"job": job, "attempt": number, "oom": oom, "overrides": step},
                                 ticket=record["ticket"], job=job)
        self._cleanup_job(record)
        # The log is appended to, so the attempt that ran out of memory is moved aside: the OOM rule reads only the last
        # bytes of the log, and the next attempt's failure must not be read by the signature this one left.
        log = Path(record["log"])
        try:
            log.replace(log.with_name("%s.%d%s" % (log.stem, number - 1, log.suffix)))
        except OSError:
            pass  # no log to keep, which the next attempt's tail reads as empty
        ahead = dict(record, attempts=list(record.get("attempts") or []) + [{"overrides": step}])
        devices = dict(record["devices"])
        if resources.RAM_OVERRIDE in step:
            devices["ram_gb"] = step[resources.RAM_OVERRIDE]
        self.say("  job %s (ticket %d) ran out of %s memory; retrying it as attempt %d with %s" % (
            job, record["ticket"], "host" if oom == "host" else "GPU", number, json.dumps(step, sort_keys=True)))
        self._launch_job(dict(record, devices=devices), resources.effective_overrides(ahead), step,
                         tuple(devices.get("gpu_indices") or ()))

    def _launch_job(self, record, overrides, step, gpu_indices):
        """Launch one job file's command under `overrides`; a launch the runner refuses fails the job and its ticket."""
        spec = resources.spec_from_record(record)
        argv, environment = resources.apply_overrides(spec.command, spec.env, overrides)
        spec = replace(spec, command=tuple(argv), env=environment)
        try:
            return self._runner().launch(spec, gpu_indices=gpu_indices, overrides=step)
        except (resources.JobError, OSError, ValueError) as failure:
            self._job_failed(record, "the launch was refused: %s" % failure, "")
            self._tail()
            owed = self._owed_jobs()
            if record["ticket"] in owed:
                self._fail_jobs(record["ticket"], owed[record["ticket"]], "job %s could not be launched: %s"
                                % (record["id"], failure), None)
            return None

    def _fail_jobs(self, identifier, owed, reason, result, tail=""):
        """Fail an experiment ticket from its jobs: the other jobs are cancelled, and the log tail is the failure output."""
        number, jobs = owed
        for job in jobs:
            record = self._runner().read(job)
            if record is not None and record.get("status") in resources.LIVE_JOB_STATUSES:
                self._runner().kill(resources.handle_for(record))
        note = [reason] + (["", "The end of the job's log:", "", "```", tail.rstrip("\n"), "```"] if tail else [])
        self._climb(identifier, number, self._step_for(identifier), reason, note)
        if result is not None:
            result.failed.append(identifier)

    def _close_jobs(self, identifier, number, jobs, result):
        """An experiment ticket whose jobs all exited 0 with their outputs manifested: done, and its verdicts queued."""
        ticket, body = self._ticket(identifier)
        known = self.view.tickets[identifier].latest
        attempt = _Attempt(ticket, body, number, self._worktree(identifier))
        attempt.difficulty = known.difficulty if known.difficulty is not None else (ticket.get("pinned_difficulty") or ticket["difficulty"])
        attempt.tier = Tier(model=known.model, effort=known.effort)
        attempt.commit = self.view.integrated.get(identifier)
        judgment = self._keep_if_better(attempt, self.project, self._seed_outputs(ticket, jobs),
                                        lambda reason: self._fail_jobs(identifier, (number, jobs), reason, result))
        if judgment == "failed":
            return
        note = ["Every job exited 0 and its outputs parsed: %s." % ", ".join(jobs)]
        if judgment is not None and not judgment.kept:
            self._discard_jobs(attempt, judgment, note, known, result)
            return
        if judgment is not None:
            self._journal_judgment(attempt, judgment)
            result.kept += 1
        # A goal ticket's worktree was kept for its judgment; kept, or no longer judged since GOAL.json changed, it goes.
        if (self._worktree(identifier) / ".git").exists():
            self._remove_worktree(identifier)
        # The passages its worker returned with the jobs it left (decision 17): its change stands on `main` now.
        note += self._file_passages(attempt, self._running_output(attempt, known).get("passages"))
        self._take_verdicts_on_inherited(attempt, self._running_output(attempt, known))
        self._set_status(identifier, "done", note)
        self.ledger.append_event(TICKET_DONE, {"ticket": identifier}, ticket=identifier)
        self._tail()
        if known.model:
            self._queue_verdicts(attempt)
        result.done.append(identifier)
        self.say("  ticket %d done: its %d job(s) exited 0 and their outputs are in the manifest" % (identifier, len(jobs)))

    # --- keep-if-better (ticket 39) ---

    def _goal_of(self, ticket):
        """`(goal, skip)`: the open goal this ticket reports, from `objectives.json`, and why keep-if-better does not judge it.

        `goal` is the objective record with its measure (`goals.goal_for`), None when `skip` says why not. An
        `objectives.json` that cannot be read judges nothing, with the reason: an integration never ends on a record
        it could not read.
        """
        if not ticket.get("goal"):
            return None, "the ticket names no goal"
        try:
            records = objectives.read_objectives(self.project)
        except objectives.ObjectivesUnreadable as failure:
            return None, str(failure)
        return goals.goal_for(ticket, records)

    def _goal_ticket(self, ticket):
        """Whether keep-if-better judges this ticket: its `goal` names an open goal, an objective with a measure."""
        return self._goal_of(ticket)[1] is None

    def _keep_if_better(self, attempt, root, outputs, fail):
        """The `Judgment` of this attempt's seeds under `root`; None when it is no goal ticket; `failed` once `fail` ran.

        An attempt judged already (in flight, or before a restart, from its judgment record) is not
        measured again. A measurement that failed, and one with fewer seeds than the policy asks for,
        fail the ticket through `fail(reason)`.
        """
        goal, skip = self._goal_of(attempt.ticket)
        if skip is not None:
            if attempt.ticket.get("goal"):
                self.say("  ticket %d: keep-if-better does not run: %s" % (attempt.id, skip))
            return None
        policy = self.policy.get("goal") or {}
        saved = attempt.judgment or self._read_judgment(attempt)
        if saved is not None and goals.run_id(attempt.id, attempt.number) in self.view.progress:
            attempt.judgment = saved  # journaled already: what it was judged then stands
            return saved
        if saved is not None:
            # Measured already, and not journaled yet: the seeds are not read again, but the best kept value may have
            # moved since (another ticket kept a change while this one waited to integrate), so they are judged again.
            values, artifacts = saved.values, None
        else:
            artifacts = goals.seed_artifacts(outputs, root)
            try:
                values = goals.evaluate(goal["measure"], artifacts, self.project, self._timeout())
            except goals.GoalError as failure:
                fail("keep-if-better measured nothing: %s" % failure)
                return "failed"
        measure = goal["measure"]
        judgment = goals.judge(measure["metric"], values, goals.best_kept(self.view.progress.values(), goal), measure["direction"],
                               min_seeds=goals.min_seeds(measure, policy),
                               margin_sd=policy.get("margin_sd", goals.DEFAULT_MARGIN_SD))
        if saved is not None and judgment == saved:
            attempt.judgment = saved
            return saved
        self.say("  ticket %d: keep-if-better read %s" % (attempt.id, judgment.words()))
        if judgment.short is not None:
            fail("keep-if-better: %s" % judgment.short)
            return "failed"
        record = {"goal": goal["id"], "metric": judgment.metric, "values": list(judgment.values), "mean": judgment.mean,
                  "sd": judgment.sd, "best": judgment.best, "kept": judgment.kept}
        if artifacts is not None:
            record["artifacts"] = [str(path) for path in artifacts]
        self.ledger.write_json(self._judgment_record(attempt.id, attempt.number), record)
        attempt.judgment = judgment
        return judgment

    def _read_judgment(self, attempt):
        try:
            record = self.ledger.read_json(self._judgment_record(attempt.id, attempt.number))
            return goals.Judgment(record["metric"], tuple(record["values"]), record["mean"], record["sd"],
                                  record["best"], bool(record["kept"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def _judgment_record(identifier, number):
        return "sessions/%d/%d/%s" % (identifier, number, goals.JUDGMENT)

    @staticmethod
    def _integration_record(identifier, number):
        return "sessions/%d/%d/%s" % (identifier, number, goals.INTEGRATION)

    def _journal_judgment(self, attempt, judgment, kept=None):
        """`progress` for this evaluation, and `discarded` when the change was not kept; each once, across restarts."""
        kept = judgment.kept if kept is None else kept
        run_id = goals.run_id(attempt.id, attempt.number)
        if run_id not in self.view.progress:
            self.ledger.append_event(PROGRESS, {"metric": judgment.metric, "value": judgment.mean, "ticket": attempt.id,
                                                "run_id": run_id, "kept": kept, "goal": attempt.ticket.get("goal")}, ticket=attempt.id)
        if not judgment.kept and attempt.id not in self.view.discarded:
            self.ledger.append_event(DISCARDED, {"ticket": attempt.id, "metric": judgment.metric, "best": judgment.best,
                                                 "sd": judgment.sd, "seeds": judgment.seeds, "goal": attempt.ticket.get("goal")},
                                     ticket=attempt.id)
        self._tail()
        attempt.kept = kept
        self.say("  ticket %d: %s" % (attempt.id, "kept" if kept else (
            "not kept" if judgment.kept else "discarded; its branch stays as %s" % (DISCARDED_BRANCH % (attempt.id, attempt.number)))))

    def _discard_note(self, attempt, judgment):
        return ("Discarded by keep-if-better, and not integrated: %s, which is not better by more than %s standard "
                "deviation(s). The change stays on the branch %s, in the worktree %s; the findings are negative results, "
                "and only a new ticket citing new evidence revives the change." % (
                    judgment.words(), (self.policy.get("goal") or {}).get("margin_sd", goals.DEFAULT_MARGIN_SD),
                    DISCARDED_BRANCH % (attempt.id, attempt.number),
                    "%s/%s" % (WORKTREES, DISCARDED_WORKTREE % (attempt.id, attempt.number))))

    def _set_aside_discarded(self, identifier, number):
        """Move a discarded attempt's worktree and branch to names of its own; the worktree's path, or None when there is none.

        `ticket/<id>` and `.worktrees/<id>` are what the ticket's next attempt (a rerun) starts from, and a
        discarded change must neither be that start nor be removed when that attempt closes: its negative
        findings cite files in its worktree. A restart that finds it moved already moves nothing.
        """
        target = self.project / WORKTREES / (DISCARDED_WORKTREE % (identifier, number))
        if (target / ".git").exists():
            return target
        source = self._worktree(identifier)
        if not (source / ".git").exists():
            return None
        with self.ledger.lock():
            self._git(self.project, "worktree", "move", str(source), str(target))
            self._git(self.project, "branch", "-m", BRANCH % identifier, DISCARDED_BRANCH % (identifier, number))
        return target

    def _seed_outputs(self, ticket, jobs):
        """The ticket's outputs, then each job's `expected_outputs`, as paths relative to the project."""
        outputs = list(ticket.get("outputs") or [])
        for job in jobs:
            record = self._runner().read(job) or {}
            for output in record.get("expected_outputs") or []:
                path = Path(output) if os.path.isabs(output) else Path(record.get("cwd") or self.project) / output
                if _inside(path, self.project):
                    outputs.append(os.path.relpath(os.path.realpath(path), os.path.realpath(self.project)))
        return outputs

    def _discard_jobs(self, attempt, judgment, note, known, result):
        """An experiment ticket's discarded change: reverted on `main`, its findings negative, `done` without a verdict."""
        identifier = attempt.id
        problem = self._revert(attempt)
        if problem is not None:
            self._climb(identifier, attempt.number, NEEDS_HUMAN, problem, [problem])
            result.failed.append(identifier)
            return
        self._journal_judgment(attempt, judgment)
        worktree = self._set_aside_discarded(identifier, attempt.number)
        refused = self._file_findings(attempt, self._running_findings(attempt, known), True, worktree)
        result.findings += attempt.findings
        self._set_status(identifier, "done", note + refused + [self._discard_note(attempt, judgment)])
        self.ledger.append_event(TICKET_DONE, {"ticket": identifier}, ticket=identifier)
        self._tail()
        result.done.append(identifier)
        self.say("  ticket %d done and discarded: its change is reverted on main" % identifier)

    def _running_output(self, attempt, known):
        """The `running` result a job-bearing ticket's worker returned, read from its session; empty when it cannot be read."""
        session = known.sessions[-1] if known is not None and known.sessions else None
        run_dir = self._session_path(attempt, session) if session is not None else None
        try:
            returned = json.loads((run_dir / "result.json").read_text(encoding="utf-8")) if run_dir else {}
        except (OSError, ValueError):
            return {}
        if not isinstance(returned, dict):
            return {}
        output = returned.get("structured_output") if isinstance(returned.get("structured_output"), dict) else returned
        return output if isinstance(output, dict) else {}

    def _running_findings(self, attempt, known):
        """The findings of the `running` result an experiment ticket's worker returned, read from its session."""
        output = self._running_output(attempt, known)
        findings = output.get("findings") if isinstance(output.get("findings"), list) else []
        return [finding for finding in findings
                if isinstance(finding, dict) and isinstance(finding.get("text"), str) and isinstance(finding.get("provenance"), str)]

    def _revert(self, attempt):
        """Revert on `main` what a running goal ticket's fast-forward brought; None when done, else why it could not be.

        The range is the one `_integrate` recorded, and the revert commit carries it in a trailer, so a
        restart does not revert twice. A revert that conflicts is aborted, and `main` is left as it was
        for a person to look at.
        """
        try:
            record = self.ledger.read_json(self._integration_record(attempt.id, attempt.number))
            span = "%s..%s" % (record["base"], record["commit"])
        except (OSError, ValueError, KeyError, TypeError):
            return ("keep-if-better discarded ticket %d, whose branch reached main before its jobs, and the range its "
                    "fast-forward brought was not recorded, so it cannot be reverted" % attempt.id)
        with self.ledger.lock():
            if self._git(self.project, "log", "-1", "--format=%H", "--fixed-strings", "--grep", REVERT_TRAILER % span,
                         MAIN, ok=None).stdout.strip():
                return None  # reverted before a restart
            if not self._git(self.project, "rev-list", span, ok=None).stdout.strip():
                return None
            reverted = self._git(self.project, "revert", "--no-commit", span, ok=None)
            if reverted.returncode != 0:
                self._git(self.project, "revert", "--abort", ok=None)
                return ("keep-if-better discarded ticket %d, and reverting %s on main fails: %s" % (
                    attempt.id, span, (reverted.stderr or reverted.stdout).strip()))
            if self._git(self.project, "diff", "--cached", "--quiet", ok=None).returncode == 0:
                self._git(self.project, "revert", "--quit", ok=None)
                self.say("  ticket %d: %s is undone on main already; nothing to revert" % (attempt.id, span))
                return None
            self._git(self.project, "commit", "-q", "-m", REVERT_MESSAGE % (attempt.id, span))
        self.say("  ticket %d: reverted %s on main; the branch %s keeps the change" % (attempt.id, span, BRANCH % attempt.id))
        return None

    def _objective_records(self):
        """`objectives.json`'s objectives, or None when the record cannot be read, which is said once per run."""
        try:
            return objectives.read_objectives(self.project)
        except objectives.ObjectivesUnreadable as failure:
            if str(failure) != self._objectives_trouble:
                self._objectives_trouble = str(failure)
                self.say("  %s; the stopping rule waits on no objective until it reads" % failure)
            return None

    def _write_reached(self, records):
        """Code writes each open goal whose best kept value reached its target answered, from the measured values; the records after."""
        progress = list(self.view.progress.values())
        reached = stopping.reached_goals(records, progress)
        for record in reached:
            measure = record["measure"]
            best = goals.best_kept(progress, record, baseline=False)
            kept = [payload.get("run_id") for payload in progress if payload.get("goal") == record["id"] and payload.get("kept")
                    and payload.get("value") == best]
            answer = "reached: the best kept %s is %s against the target %s (%s), measured by code%s" % (
                measure["metric"], goals.number(best), goals.number(measure.get("target")), measure["direction"],
                " on %s" % kept[-1] if kept else "")
            try:
                objectives.change_objective(self.project, record["id"], "answered", "code", answer=answer)
            except (objectives.ObjectiveError, ValueError, OSError) as failure:
                self.say("  goal %s reached, and it could not be written: %s" % (record["id"], failure))
                continue
            self.say("  goal %s %s" % (record["id"], answer))
        if not reached:
            return records
        self._tail()
        return self._objective_records() or records

    def _rule_ends(self, result):
        """Wave step 6 (decision 17; ticket 87): end the run when the stopping rule holds or a budget is spent.

        Code first writes reached every open goal whose best kept value reached its target. Then the rule of
        `harness.json`'s `stop_when` is read, every wave: it ends the run `objectives_closed`, or `goal_reached` when
        every objective it closed was a goal that reached its target. A budget spent ends it `budget_spent`. The
        workers still running finish on their own, as after a stop, and the owner is notified.
        """
        records = self._objective_records()
        if records is not None:
            records = self._write_reached(records)
        harness = self._harness_for_rule()
        if harness is None:
            return False
        rule = stopping.rule_of(harness)
        reason = stopping.rule_end(rule, records, list(self.view.progress.values())) if records is not None else None
        if reason is not None:
            closed = [record["id"] for record in stopping.covered(rule, records)]
            words = ("every goal the stopping rule waits on is reached (%s)" if reason == stopping.GOAL_REACHED else
                     "the objectives the stopping rule waits on are closed (%s)") % ", ".join(closed)
        else:
            if not stopping.stated(harness):
                return False
            events, _ = self.ledger.read_events()
            found = stopping.spent(harness, events, self.clock())
            if not found:
                return False
            reason, words = stopping.BUDGET_SPENT, stopping.describe_spent(found)
        self.ledger.append_event(RUN_ENDED, {"reason": reason})
        result.ended, result.reason = True, reason
        words = "%s; the run ended (%s)" % (words, reason)
        self.say("  " + words)
        left = sorted(identifier for identifier, attempt in self.flight.items() if attempt.running or attempt.adopted)
        if left:
            self.say("  ticket(s) %s still have a worker running; it finishes on its own and the next run re-adopts it"
                     % ", ".join(str(identifier) for identifier in left))
        return True  # the end notice follows the wave (`_end_notice`)

    def _place_jobs(self, result):
        """Launch as many pending jobs of the owed tickets as the free-slot rule places; journal why the others wait."""
        owed = self._owed_jobs()
        wanted = {job for _, jobs in owed.values() for job in jobs}
        if not wanted:
            return
        records = self._job_records()
        pending = [record for record in records if record["id"] in wanted and record.get("status") == "pending"]
        if not pending:
            return
        running = [record for record in records if record.get("status") == "running"]
        try:
            readings = self._read_readings()
        except (resources.ResourceError, OSError, ValueError) as failure:
            self.say("  the machine could not be read (%s); %d job(s) wait" % (failure, len(pending)))
            return
        requests = {}
        for record in pending:
            ticket, _ = self._ticket(record["ticket"])
            requests[record["id"]] = resources.job_request(record, ticket.get("resources"))
        jobs_policy = self.policy.get("jobs") or {}
        placements, waiting = resources.place_jobs(
            pending, running, readings, requests,
            util_threshold=jobs_policy.get("gpu_util_free_below", resources.DEFAULT_GPU_UTIL_FREE_BELOW))
        by_id = {record["id"]: record for record in pending}
        for job, reason in sorted(waiting.items()):
            never = resources.never_fits(requests[job], readings)
            if never is not None and self._is_owed(by_id[job]):
                waiting.pop(job)
                self._runner().write(dict(self._runner().read(job) or by_id[job], status="failed"))
                self._job_failed(by_id[job], never, "")
                self._tail()
                self._fail_jobs(by_id[job]["ticket"], self._owed_jobs()[by_id[job]["ticket"]],
                                "job %s can never be placed: %s" % (job, never), result)
        for placement in placements:
            current = self._runner().read(placement.job)
            if current is None or current.get("status") != "pending" or not self._is_owed(current):
                continue  # its ticket failed a moment ago, and the job was cancelled with it
            record = dict(by_id[placement.job], devices={
                "gpu_uuids": list(placement.gpu_uuids), "gpu_indices": list(placement.gpu_indices),
                "cores": list(placement.cores), "ram_gb": placement.ram_gb})
            if self._launch_job(record, resources.effective_overrides(record), {}, placement.gpu_indices) is not None:
                self.say("  job %s (ticket %d) launched on %s, cores %s" % (
                    placement.job, record["ticket"], "GPU %s" % ",".join(map(str, placement.gpu_indices)) if placement.gpu_indices else "no GPU",
                    resources._range_text(placement.cores)))
        for job, reason in sorted(waiting.items()):
            if job not in self._owed_ids():
                continue
            if _waiting_kind((self.view.jobs.get(job) or {}).get("waiting")) == _waiting_kind(reason):
                continue  # the same wait, whatever the load or the free RAM reads this wave
            self.ledger.append_event(JOB_WAITING, {"job": job, "ticket": by_id[job]["ticket"], "reason": reason},
                                     ticket=by_id[job]["ticket"], job=job)
            self.say("  job %s (ticket %d) waits: %s" % (job, by_id[job]["ticket"], reason))
        self._tail()

    def _owed_ids(self):
        return {job for _, jobs in self._owed_jobs().values() for job in jobs}

    def _is_owed(self, record):
        """Whether a job file belongs to a ticket still owed its jobs, as the view says now."""
        owed = self._owed_jobs().get(record.get("ticket"))
        return owed is not None and record.get("id") in owed[1]

    def _read_readings(self):
        """The machine as the free-slot rule reads it: `self.readings()` when a test set one, else `resources.read_readings`."""
        if self.readings is not None:
            return self.readings()
        jobs_policy = self.policy.get("jobs") or {}
        return resources.read_readings(read_harness(self.project),
                                       gpu_util_samples=jobs_policy.get("gpu_util_samples", resources.DEFAULT_GPU_UTIL_SAMPLES))

    def _cancel_jobs(self, identifier):
        """End every job of a cancelled or rerun ticket that is still on the machine or waiting to be."""
        for record in self._job_records():
            if record.get("ticket") == identifier and record.get("status") in resources.LIVE_JOB_STATUSES:
                self._runner().kill(resources.handle_for(record))
                self.say("  job %s of ticket %d cancelled" % (record["id"], identifier))

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
            wrong_model = self._model_that_ran(attempt)
            if wrong_model is not None:
                return wrong_model  # the session did not run on the rung's model (decision 16): no gate, no resume
        if attempt.integrating:
            attempt.integrating = False
            return self._finish(attempt)
        problem = self._invalid(attempt)
        if attempt.stage == ACCEPTANCE_FAILED:
            if problem is not None:
                self._fail(attempt, "the resumed session returned no usable result: %s" % problem, self._step_from(attempt.id))
                return "failed"
            # What the resumed session asked and proposed is taken, and a status other than done is acted on, as at a launch.
            carried = self._act_on(attempt)
            if carried not in ("done", RUNNING):
                return carried
            if not self._accept(attempt, "worktree", attempt.worktree)["pass"]:
                self._fail(attempt, "the machine acceptance still failed in the worktree after one resume", self._step_from(attempt.id))
                return "failed"
        else:
            if problem is not None:
                if attempt.stage in (INVALID_RESULT, TIMEOUT):
                    self._fail(attempt, "the result was still unusable after one resume: %s" % problem, self._step_from(attempt.id))
                    return "failed"
                return self._want_resume(attempt, INVALID_RESULT, RESUME_INVALID % problem)
            carried = self._act_on(attempt)
            if carried not in ("done", RUNNING):
                return carried
            record = self._accept(attempt, "worktree", attempt.worktree)
            if not record["pass"]:
                return self._want_resume(attempt, ACCEPTANCE_FAILED, RESUME_ACCEPTANCE % _failures(record["results"]))
        return self._finish(attempt)

    def _finish(self, attempt):
        """The branch's commits integrated and the ticket closed: `done`, `failed`, or `session` while the integrator waits."""
        self._stop_integrator(attempt)
        running = attempt.result.get("status") == "running"
        if running:
            problem = self._jobs_problem(attempt)
            if problem is not None:
                self._fail(attempt, problem, self._next_step(attempt))
                return "failed"
        if not self._committed(attempt):
            return "failed"
        judgment = None
        if not running:  # a running result is judged once its jobs have written the seeds
            judgment = self._keep_if_better(attempt, attempt.worktree, attempt.ticket.get("outputs"),
                                            lambda reason: self._fail(attempt, reason, self._next_step(attempt)))
            if judgment == "failed":
                return "failed"
            if judgment is not None and not judgment.kept:
                self._journal_judgment(attempt, judgment)
                attempt.worktree = self._set_aside_discarded(attempt.id, attempt.number) or attempt.worktree
                self._close(attempt, discarded=judgment)
                return "done"
        record = self._change_record(attempt.id, attempt.ticket)
        if record is not None:
            # A harness ticket's fixture fails on the old subject and passes on the change before it is integrated (ticket 45).
            proven = self._prove(attempt, record)
            if proven is not True:
                return proven
            if record["scope_kind"] == "global":
                return self._finish_global(attempt, record)
        outcome = self._integrate(attempt)
        if record is not None and outcome == "done":
            from wayline import changes
            changes.set_status(self.project, record["id"], "applied")
        if outcome == "done" and running:
            self._leave_running(attempt)  # its passages wait for its jobs: written when they close and the change is kept
            return "running"
        if judgment is not None and outcome in ("done", "failed"):
            # A change judged better is kept only once it is on `main`; one whose integration failed was not kept.
            self._journal_judgment(attempt, judgment, kept=outcome == "done")
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
        payload = {
            "ticket": attempt.id, "attempt": attempt.number, "session_id": attempt.session_id,
            "status": attempt.result.get("status"), "turns": envelope.num_turns,
            "duration_ms": envelope.duration_ms, "usage": envelope.usage,
            "permission_denials": envelope.permission_denials, "valid": self._invalid(attempt) is None,
        }
        if attempt.result.get("status") == "running":
            payload["jobs"] = [str(job) for job in attempt.result.get("jobs") or []]
        asked = self._launched_on(attempt)
        if asked is not None and worker.not_served(envelope) is None and not worker.ran_as_asked(asked, envelope):
            # The model that ran, when it was not the rung's (decision 16); a not-served refusal ran no model at all,
            # and its `modelUsage` holds only the Haiku preflight, so that failure names no model here.
            payload["model_ran"] = worker.model_ran(envelope)
        self.ledger.append_event(TICKET_RESULT, payload, ticket=attempt.id, session_id=attempt.session_id)

    @staticmethod
    def _launched_on(attempt):
        """The model this attempt's session was launched with: its request's, else its tier's; None when neither is known."""
        if attempt.request is not None:
            return attempt.request.model
        return attempt.tier.model if attempt.tier is not None else None

    def _model_that_ran(self, attempt):
        """`failed` when the session did not run on the model it was launched with, None when it did (decision 16).

        Neither failure is one a resume could mend, so both skip the ladder's resume and take the rung above it.
        A model name the subscription does not serve comes back as a 404 that spent no window and no turn: the
        rung is held and the owner asked (`_hold_rung`), because a policy naming a dead model needs an edit no
        conductor can make, while the rest of the run goes on at other rungs. A result whose `modelUsage` names
        no model of the rung's ran somewhere nobody asked for, which with the legacy remap off means a fallback
        or a remap; its `ticket_result` carries the model that ran.
        """
        envelope, asked = attempt.envelope, self._launched_on(attempt)
        if envelope is None or asked is None:
            return None
        refused = worker.not_served(envelope)
        if refused is not None:
            held = self._hold_rung(attempt, refused)
            self._fail(attempt, "model_not_served: the subscription does not serve %s, the model this launch named%s; "
                                "the attempt is not retried and launches at that rung are held%s"
                       % (refused, "" if attempt.tier is None else " at rung %s" % attempt.tier.rung,
                          " until decision ticket %d is answered" % held if held else ""),
                       # Straight to the tier up, skipping the split: a rung naming a model nobody serves is a policy
                       # typo, and re-cutting the ticket would spend the planner on it. A tier up onto a held rung waits.
                       self._step_from(attempt.id, start=TIER_UP))
            return "failed"
        if worker.ran_as_asked(asked, envelope):
            return None
        self._fail(attempt, "model_mismatch: the launch named %s and the result says %s ran; the work is not what the "
                            "rung asked for, and the attempt is not resumed"
                   % (asked, worker.model_ran(envelope) or "another model"),
                   # As for a refusal: neither failure says anything about the work, so the split, which makes the
                   # work smaller, is skipped and the ladder goes straight to the tier up.
                   self._step_from(attempt.id, start=TIER_UP))
        return "failed"

    def _hold_rung(self, attempt, refused):
        """Hold every launch at the rung whose model the subscription refused, by asking the owner (decision 16).

        The hold is the open decision ticket: `View.held_rungs` reads it back from the journal, so a restarted
        conductor holds what a running one does and an answer lifts it. One ticket per held rung: a second
        refusal at a rung already held opens nothing, and `open_decision`'s origin finishes one a crash left
        half written. Returns the decision ticket's id, or None when there is nothing to hold or it could not
        be opened, which leaves the failure itself as the record.
        """
        rung = attempt.tier.rung if attempt.tier is not None else None
        if rung is None:
            self.say("  ticket %d named a model the subscription does not serve (%s), and no rung to hold" % (attempt.id, refused))
            return None
        self._tail()
        held = self.view.held_rungs().get(rung)
        if held is not None:
            self.say("  ticket %d met rung r%d's unserved model again; decision ticket %d already holds that rung" % (attempt.id, rung, held))
            return held
        try:
            report = decisions.open_not_served(self.project, rung, attempt.tier.model, refused,
                                               attempt.id, attempt.number, notify=self.notify)
        except (ValueError, OSError) as failure:
            self.say("  the ask about rung r%d's unserved model could not be opened: %s" % (rung, failure))
            return None
        self._tail()
        self.say("  rung r%d names %s, which this subscription does not serve: launches at that rung are held and "
                 "decision ticket %d asks the owner to edit the policy" % (rung, refused, report["ticket"]))
        return report["ticket"]

    def _want_resume(self, attempt, stage, message):
        """Spend a gate's one resume (BRIEF 9.1): now, or as soon as the run may start model work."""
        if not attempt.session_id:
            self._fail(attempt, "there is no session id to resume: %s"
                       % "; ".join(attempt.envelope.errors or ["the session never started"]), self._step_from(attempt.id))
            return "failed"
        if stage == ACCEPTANCE_FAILED:
            # The chain's first step (ticket 38): the failure is journaled with `next: resume`, then the session is resumed.
            self.ledger.append_event(TICKET_FAILED, {"ticket": attempt.id, "attempt": attempt.number,
                                                     "reason": "the machine acceptance failed in the worktree", "next": RESUME},
                                     ticket=attempt.id, session_id=attempt.session_id)
            self._tail()
        attempt.want = _Want(stage, message)
        self._start_wanted(attempt)
        return "session"

    def _start_wanted(self, attempt):
        """Start the session an attempt waits for, unless the run holds model work or the hold holds it on Fable.

        A session is a worker like any launch, so it also waits for a free worker slot when every slot
        is taken (ticket 59), as the escalation chain's resume does; the wait is said once and the session starts
        at the first wave with a free slot.

        Under the fallback consent `auto` the hold holds nothing back: a session it would keep waiting on
        Fable starts as a fresh Opus session in the same attempt instead (`_fall_back_session`). Returns
        True when it started the session, `FALLEN_BACK` when a fresh Opus session took its place, and
        False when nothing started.
        """
        if attempt.want is None or attempt.want.stage == INTEGRATE or self._holds_launches():
            return False  # an integration is carried again by `_poll`, not started as a session
        held = self._held_on_fable(attempt.request)
        if self._holds_launches() or (held and not self._falls_back()):
            # Resumed, or relaunched, on Fable once the hold ends; and the `/usage` the hold read may have said `stop`.
            if held and not self._holds_launches():
                self._held_back("ticket %d's session" % attempt.id)
            attempt.waiting_for_slot = False  # what it waits for now is the hold, and a slot's wait is said again after it
            return False
        if not self._free_slot(attempt):
            return False  # every slot is taken: it starts at the first wave one is free
        want, attempt.want, attempt.waiting_for_slot = attempt.want, None, False
        if held:
            self._fall_back_session(attempt, want)
            attempt.begun.wait()
            return FALLEN_BACK
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

    def _fall_back_session(self, attempt, want):
        """Start a session the hold keeps waiting on Fable as a fresh Opus session in the same attempt and worktree.

        Never a resume: resuming a Fable transcript on Opus is unverified (decision 15). A session refused
        before its first turn left nothing, and is launched again on Opus. One that stopped before it
        returned (at the limit, or its worker died) left partial work in the worktree, and the prompt says
        so, with the message it was answering when it was a resume. One that returned and is owed a gate's
        resume is told it returned, and given the gate's message; the gate's one resume is spent as the
        resume would have spent it. The launched session's stream, stderr, and result are kept in
        `stopped-<n>/`, since the fresh launch writes over them, and the notes in `fallback.json`, so a
        restart that relaunches the attempt says them again. `ticket_resumed` is journaled with no session
        id, as for any relaunch in the same attempt, and the launch journals `ticket_launched` with `fallback_from`.
        """
        ran, gate = want.stage != RELAUNCH, want.stage in replay.GATES
        returned = want.stage in (INVALID_RESULT, ACCEPTANCE_FAILED)
        if ran:
            self._keep_session(attempt, "stopped")
        if gate:
            attempt.stage, attempt.resumed = want.stage, True
        attempt.session_id = None
        self._journal_resumed(attempt, want.stage if gate else replay.WORKER_DIED)
        attempt.started = attempt.session_journaled = False
        attempt.tail = None
        notes = [FALLBACK_RETURNED if returned else FALLBACK_PARTIAL] if ran else []
        last = want.message if gate else want.answering
        if ran and last:
            notes.append(FALLBACK_LAST_MESSAGE % last)
        if attempt.tier.family == pacing.FABLE:
            attempt.fallback_from, attempt.tier = attempt.tier.label, fallback_tier(self.policy, attempt.tier)
        elif not attempt.fallback_from:  # a tier no rung made, or one already moved: the rung it came from is unnamed
            attempt.fallback_from = pacing.FABLE
        if notes:
            self.ledger.write_json(self._attempt_dir(attempt).relative_to(self.ledger.research) / FALLBACK_NOTES,
                                   {"fallback_from": attempt.fallback_from, "notes": notes})
        attempt.prompt = self._prompt(attempt, notes)
        attempt.request = self._request(attempt, attempt.prompt)
        taken = ("its %s resume would run on Fable; a fresh session takes it" % want.stage if returned
                 else "its session on Fable stopped before it returned; a fresh session continues its partial work" if ran
                 else "its session on Fable never started work; it is launched again")
        self.say("  ticket %d: Fable's weekly window is spent and the fallback consent is auto; %s on %s %s, in the same attempt"
                 % (attempt.id, taken, attempt.tier.model, attempt.tier.effort))
        self._run_session(attempt, "launch")

    def _fallback_notes(self, attempt):
        """The notes a fallback launch of this attempt carried in its prompt, from `fallback.json`; () when there are none."""
        try:
            notes = json.loads((self._attempt_dir(attempt) / FALLBACK_NOTES).read_text(encoding="utf-8")).get("notes")
        except (OSError, ValueError, AttributeError):
            return ()
        return [note for note in notes if isinstance(note, str)] if isinstance(notes, list) else ()

    def _journal_resumed(self, attempt, reason):
        """`ticket_resumed` for the attempt's session, with the reason decision 2's table gives it."""
        self.ledger.append_event(TICKET_RESUMED, {
            "ticket": attempt.id, "attempt": attempt.number, "session_id": attempt.session_id, "reason": reason,
        }, ticket=attempt.id, session_id=attempt.session_id)

    def _open_requested(self, attempt):
        """Wave step 5: each of a valid result's `decision_requests` opens a decision ticket, pausing what waits on this one.

        A request the ledger refuses (a question with no text) is said aloud and left in the ticket's
        `## Result` section, where every request is written; it does not fail the work that asked it.
        """
        requests = attempt.result.get("decision_requests") or []
        if not requests:
            return
        try:
            reports = decisions.open_requested(self.project, attempt.id, attempt.number, requests, notify=self.notify)
        except (ValueError, OSError) as failure:  # a ticket the schema or the ledger refuses fails nothing the worker did
            self.say("  ticket %d asked a decision that could not be opened: %s" % (attempt.id, failure))
            return
        for report in reports:
            if report["opened"]:
                self.say("  ticket %d asked a decision: decision ticket %d, pausing %s" % (
                    attempt.id, report["ticket"],
                    "ticket(s) %s" % ", ".join(str(item) for item in report["paused"]) if report["paused"] else "no ticket yet"))

    def _admit_proposals(self, attempt):
        """Wave step 5: each of a valid result's `proposals` is admitted or parked (ticket 37).

        A proposal the ledger refuses (a launch failure of the dedup judge) is said aloud and left
        for a later wave to retry; it does not fail the work that proposed it.
        """
        requested = attempt.result.get("proposals") or []
        if not requested:
            return
        try:
            outcomes = proposals.admit_proposals(
                self.project, requested, origin_ticket=attempt.id, origin_prefix="ticket %d attempt %d" % (attempt.id, attempt.number),
                proposed_by="worker:%d" % attempt.id, policy=self.policy, harness_root=self.harness_root,
                wave_cap=self._proposal_cap, notify=self.notify)
        except (ValueError, OSError) as failure:
            self.say("  ticket %d proposed ticket(s) that could not be admitted: %s" % (attempt.id, failure))
            return
        for outcome in outcomes:
            if outcome["outcome"] == "admitted":
                self.say("  ticket %d proposed a ticket: admitted as ticket %d" % (attempt.id, outcome["ticket"]))
            else:
                self.say("  ticket %d proposed a ticket: parked (%s)" % (attempt.id, outcome["reason"]))

    def _notify_in_background(self, event, text, project=None, ticket=None):
        """`wayline.notify.notify` on a thread of its own: hermes may take two minutes, and a wave does not wait for it.

        The notifier journals its claim before any channel runs and never raises. `settle` and the end of `run` wait
        for these threads, so what a run claimed to the owner is sent before the run returns.
        """
        thread = threading.Thread(target=notify.notify, args=(event, text), kwargs={"project": project, "ticket": ticket},
                                  name="wayline-notify")
        self.notifying = [item for item in self.notifying if item.is_alive()] + [thread]
        thread.start()
        return thread

    def _act_on(self, attempt):
        """What the result's own status asks for: `done`, `running`, or `failed` for the wave's count.

        The status is read before the acceptance is run, because only the worker can report that it
        is blocked or that it needs a person, and a ticket in either state must not spend its one
        resume on gates that were never going to pass. The decision tickets the result asks for are
        opened first, whatever its status, since a question is worth asking whether or not the work
        that raised it passes.
        """
        self._open_requested(attempt)
        self._admit_proposals(attempt)
        outside = attempt.result.get("touched_outside_declared") or []
        blocked_on = attempt.result.get("blocked_on")
        status = attempt.result.get("status")
        if not outside and (blocked_on or status in ("blocked", "needs_human")) and worker.simulated_failure(attempt.id) is not None:
            # The owner's simulated failure (`run --simulate-failure`) is what a worker told of it honestly reports as
            # blocked or for a person; either is this attempt failing, so the chain climbs as the flag exists to show.
            said = blocked_on or (attempt.result.get("summary") or "").strip() or status
            self._fail(attempt, "the worker reported %s under the simulated failure: %s"
                       % ("blocked" if blocked_on or status == "blocked" else status, said), self._next_step(attempt))
            return "failed"
        if outside or blocked_on:
            path = ", ".join(outside) if outside else blocked_on
            self._write_ticket(attempt, "blocked", attempt.result)
            self.ledger.append_event(TICKET_BLOCKED, {"ticket": attempt.id, "path": path}, ticket=attempt.id)
            gap = None if outside else software.gap_of(blocked_on)
            if gap is None and not outside and verification.gap_of(blocked_on) is not None and attempt.ticket.get("verifies"):
                # The verification lacks material it needs (ticket 97): a decision pausing only that verification.
                try:
                    report = verification.open_gap(self.project, attempt.id, blocked_on, notify=self.notify)
                except (verification.VerificationError, verification.VerificationUnreadable, tickets.TicketError, ValueError,
                        OSError) as failure:
                    self.say("  ticket %d is blocked on missing material, and its decision could not be opened: %s" % (attempt.id, failure))
                    return "failed"
                if report is not None:
                    self.say("  ticket %d is blocked: its verification lacks %s; decision ticket %d asks about it"
                             % (attempt.id, verification.gap_of(blocked_on)[1], report["ticket"]))
                    return "failed"
            if gap is None:
                self.say("  ticket %d is blocked on %s; the planner re-cuts it" % (attempt.id, path))
                return "failed"
            # An installed tool lacks what the code needs (ticket 82): code opens the decision, which only the owner answers.
            try:
                report = software.open_gap(self.project, attempt.id, gap[0], gap[1], notify=self.notify)
            except (ValueError, OSError, RuntimeError) as failure:
                self.say("  ticket %d is blocked on a gap in %s, and its decision could not be opened: %s" % (attempt.id, gap[0], failure))
                return "failed"
            self.say("  ticket %d is blocked: the installed %s lacks what its code needs (%s); decision ticket %d asks the owner"
                     % (attempt.id, gap[0], gap[1], report["ticket"]))
            return "failed"
        if status == "done":
            return "done"
        summary = (attempt.result.get("summary") or "").strip()
        if status == "running":
            # Decision 5: a running result names its jobs, and its branch is integrated like a done one's before
            # they launch, so the jobs run the code on `main`; the job poller then closes the ticket (ticket 19).
            problem = self._jobs_problem(attempt)
            if problem is None:
                return RUNNING
            if attempt.stage in (INVALID_RESULT, TIMEOUT, ACCEPTANCE_FAILED):
                self._fail(attempt, "the result was still unusable after one resume: %s" % problem, self._step_from(attempt.id))
                return "failed"
            return self._want_resume(attempt, INVALID_RESULT, RESUME_INVALID % problem)
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
        """Whether this wave may start no session that needs a model (wave step 8).

        The owner paused the run, a usage limit paused it until its window resets, pacing says
        `stop`, or the run is stopping.
        """
        self._fold_answered_refusals()  # a refusal a session that answered carried pauses before anything launches
        return (self.view.paused_by_owner or self.view.pause is not None
                or schedule.holds_model_work(self.action) or self._stop_requested() is not None)

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

    # --- pacing and the pause (decision 5, wave step 8) ---

    def _read_usage(self):
        """The `/usage` reading of `run` start, through the launcher seam; a failure is said, never raised."""
        try:
            text = worker.usage()
        except (worker.LaunchError, OSError) as failure:
            self._usage_says("/usage could not be read (%s); pacing waits for the workers' rate_limit_event" % failure)
            return
        now = self.clock()
        usage = pacing.parse_usage(text, now) if text is not None else None
        if usage is None:
            if text is not None:
                self._usage_says("/usage printed none of the windows; pacing waits for the workers' rate_limit_event")
            return
        self._usage_trouble = None
        for name in pacing.READINGS:
            self.windows.record(name, getattr(usage, name), usage.resets.get(name), now)

    def _usage_says(self, message):
        """Say why `/usage` gave no reading once, not at every wave that reads it again."""
        if message != self._usage_trouble:
            self.say("  " + message)
        self._usage_trouble = message

    def _heard_pacing(self, events):
        """Take the readings in `pacing` events another process journaled (the tick's `/usage`) or a restart replays.

        Each is taken as read at its event's time, so it replaces only an older reading: the
        `/usage` a run read at its start is not undone by the journal it replays at its first wave.
        An event that says what this run's readings already say is its own, and is passed over.
        """
        for event in events:
            payload, observed = event.get("payload") or {}, pacing.epoch(event.get("ts"))
            if event.get("event") in (PAUSED, UNPAUSED) and payload.get("model") == pacing.FABLE and observed is not None:
                self._heard_hold(event["event"], payload, observed)
                continue
            if event.get("event") != PACING:
                continue
            now = self.clock()
            if observed is None or all(payload.get(name) == self.windows.utilization(name, now) for name in pacing.READINGS):
                continue
            for name in pacing.READINGS:
                self.windows.record(name, payload.get(name), None, observed)

    def _heard_hold(self, name, payload, observed):
        """Take what a journaled hold says of Fable's weekly window (decision 15).

        Its `paused` is a reading of the week as spent at the moment it was journaled, so a `pacing`
        event from before it cannot end it at a restart. Its `unpaused` retires a reading that still
        has the week spent, because a `pacing` event names no reset and would begin the hold again.
        A hold the readings already put at `stop_at` or above (this run's own) is passed over, and one
        taken in is read as at least `stop_at`, so a refusal that reported less does not end its own hold.
        """
        held, stop_at = self.windows.readings.get(pacing.FABLE), self._thresholds()[0]
        if name == UNPAUSED:
            if held is not None and (held.observed_at is None or held.observed_at <= observed) and held.utilization >= stop_at:
                del self.windows.readings[pacing.FABLE]
            return
        if (self.windows.utilization(pacing.FABLE, self.clock()) or 0) >= stop_at:
            return
        utilization = payload.get("utilization")
        spent = max(stop_at, utilization if isinstance(utilization, (int, float)) and not isinstance(utilization, bool) else 1.0)
        resets = pacing.epoch(payload.get("resets_at"))
        self.windows.record(pacing.FABLE, spent, None if resets is None else int(resets), observed)

    def _observe(self, attempt):
        """Fold the `rate_limit_event`s a session's stream gained into the readings; a rejected one pauses the run.

        The action is computed again at once, before the caller carries or resumes anything, so a
        session waiting to start is held by the reading its own stream just gave.
        """
        if attempt.tail is None:
            return
        seen = attempt.tail.read().rate_limit_events
        if len(seen) < attempt.limits_read:  # a relaunch rewrote the stream
            attempt.limits_read = 0
        if len(seen) == attempt.limits_read:
            return
        now = self.clock()
        for event in seen[attempt.limits_read:]:
            # A stream does not say when it wrote an event, so while the hold stands its Fable reading is not taken:
            # an allowed event written before the refusal that began the hold would end it. `/usage` and the reset do.
            self.windows.observe(event, now, pacing.WINDOWS if self.view.hold is not None else pacing.READINGS)
            limit = pacing.rejected(event)
            if limit is not None:
                self._pause(limit, "ticket %d's worker" % attempt.id)
        attempt.limits_read = len(seen)
        self._pace()

    def _limit_of(self, attempt):
        """`(limit, written)`: the usage limit a returned session stopped at (or None), and when its stream was last written.

        A reset the message gives as a bare time (`resets 3:45pm`) is read against when the stream
        was last written, so a result a restart carries hours later does not pause until tomorrow.
        """
        reference = self.clock()
        if attempt.stream_path is not None:
            try:
                reference = min(reference, attempt.stream_path.stat().st_mtime)
            except OSError:
                pass
        limit = pacing.hit_limit(attempt.envelope, worker.stderr_tail(attempt.run_dir), reference,
                                 model=attempt.request.model if attempt.request is not None else None)
        return limit, reference

    def _wait_out(self, attempt):
        """A session a usage limit stopped: journal its result, then resume it after the reset rather than fail it.

        The resume is journaled `ticket_resumed` with `worker_died`, the reason decision 2 gives the
        resume of an interrupted session by its id (or the relaunch of one that never started), and
        like it spends no gate. A launch the limit refused before its first turn holds nothing to
        resume, so it is relaunched in the same attempt instead, never resumed (decision 15).
        """
        if not attempt.result_journaled:
            self._journal_result(attempt)
            attempt.result_journaled = True
        kind = "launch" if attempt.run_dir in (None, self._attempt_dir(attempt)) else "resume"
        if kind == "launch" and not attempt.envelope.answered:
            self._keep_session(attempt, "refused")
            attempt.session_id, attempt.want = None, _Want(RELAUNCH)
            self.flight[attempt.id] = attempt
            started = self._start_wanted(attempt)
            if started != FALLEN_BACK:  # a fresh session on Opus took its place, which `_fall_back_session` said
                self.say("  ticket %d: the usage limit refused its session before its first turn; relaunching it%s"
                         % (attempt.id, "" if started else self._waits_for(attempt)))
            return "session"
        self._died(attempt, replay.Session(kind), RESUME_LIMIT, "its session stopped at the usage limit")
        return "session"

    def _keep_session(self, attempt, label):
        """Copy the attempt's launched session's stream, stderr, and result into `<label>-<n>/`, which a relaunch writes over.

        `label` is `refused` for a session a limit refused before its first turn, and `stopped` for one whose
        work a fresh session on Opus takes over (decision 15). The journal's `ticket_session` and
        `ticket_result` name the session, so what it wrote is kept beside them.
        """
        base = self._attempt_dir(attempt)
        number = 1
        while (base / ("%s-%d" % (label, number))).exists():
            number += 1
        kept = base / ("%s-%d" % (label, number))
        try:
            kept.mkdir(parents=True)
            for name in ("stream.jsonl", "stderr.txt", "result.json"):
                if (base / name).is_file():
                    shutil.copy2(base / name, kept / name)
        except OSError as failure:
            self.say("  ticket %d: the %s session could not be kept in %s (%s); its relaunch writes over it"
                     % (attempt.id, label, kept.name, failure))

    def _pause(self, limit, source, written=None):
        """Journal `paused` for a hit limit, unless its window has reset already or the run is paused as long.

        A limit on Fable's weekly window pauses nothing: it begins the hold on Fable launches (`_hold`).
        `written` is when the session that met the limit last wrote its stream, which a restart may carry long after.
        """
        if limit.model == pacing.FABLE:
            self._hold(limit, source, written)
            return
        now = self.clock()
        resets = pacing.resets_at(limit, self.windows, now)
        if resets <= now:
            return
        held = pacing.epoch((self.view.pause or {}).get("resets_at"))
        if held is not None and held >= resets:
            return
        payload = pacing.paused_payload(limit, resets, self.windows)
        self.ledger.append_event(PAUSED, payload)
        self._tail()
        self.say("  %s hit the usage limit (%s, %s window); paused until %s: running workers finish, nothing that needs a model starts"
                 % (source, limit.signal, limit.window, payload["resets_at"]))

    def _unpause_at_reset(self):
        """`unpaused` once the window a pause or the hold waits for has reset; one whose reset cannot be read ends now."""
        pause, hold = self.view.pause, self.view.hold
        if pause is not None and not self._resets_later(pause):
            self.ledger.append_event(UNPAUSED, {})
            self._tail()
            self.say("  the %s window reset (%s); unpaused" % (pause.get("window") or "unknown", pause.get("resets_at")))
        if hold is not None and not self._resets_later(hold):
            self._unhold("Fable's weekly window reset (%s)" % hold.get("resets_at"))

    def _resets_later(self, stands):
        """Whether a pause or the hold waits for a reset that is still ahead."""
        resets = pacing.epoch(stands.get("resets_at"))
        return resets is not None and resets > self.clock()

    def _fold_answered_refusals(self):
        """Pause or hold on every refusal a session that still answered carried (`worker.take_answered_refusals`).

        A worker's stream is folded as it is read (`_observe`) and a verdict's as the gate returns it
        (`_heard_verdict`); the decider, the planner, and the evolver have no stream the conductor reads, so a Fable
        refusal riding one of their answers would begin no hold (decision 15). Folding one twice holds once.
        """
        for event in worker.take_answered_refusals():
            limit = pacing.rejected(event)
            if limit is not None:
                self._pause(limit, "a session that answered")

    def _hold(self, limit, source, written=None):
        """Journal the hold on Fable's weekly window, `paused` with `model: fable`, unless it stands as long already.

        A refusal is itself a reading of the week as spent, at `stop_at` at least, so neither its own
        figure nor an older `/usage` reading ends the hold at the next wave. A refusal met just now is
        the newest reading there is. One whose stream was `written` earlier (a result a restart carries)
        gives way to a reading taken since that puts Fable under `stop_at`: the week reset in between.
        Nothing else is held: the run goes on launching every session that is not on Fable (decision 15).
        """
        now = self.clock()
        resets = pacing.resets_at(limit, self.windows, now)
        if resets <= now:
            return
        if limit.signal != pacing.READING_SIGNAL:
            stop_at, held = self._thresholds()[0], self.windows.readings.get(pacing.FABLE)
            at = now if written is None or written >= now else written
            newer = held is not None and held.observed_at is not None and held.observed_at > at
            if at < now and newer and (self.windows.utilization(pacing.FABLE, now) or 0) < stop_at:
                return
            spent = max(stop_at, 1.0 if limit.utilization is None else limit.utilization)
            self.windows.record(pacing.FABLE, spent, resets, held.observed_at if newer else at)
        standing = pacing.epoch((self.view.hold or {}).get("resets_at"))
        if standing is not None and standing >= resets:
            return
        payload = pacing.paused_payload(limit, resets, self.windows)
        self.ledger.append_event(PAUSED, payload)
        self._tail()
        self.say("  %s: Fable's weekly window is spent (%s); Fable launches are held until %s and everything else keeps launching"
                 % (source, limit.signal, payload["resets_at"]))

    def _unhold(self, why):
        """Journal the end of the hold on Fable's weekly window: `unpaused` with `model: fable`."""
        self.ledger.append_event(UNPAUSED, {"model": pacing.FABLE})
        self._tail()
        self.say("  %s; Fable launches are no longer held" % why)

    def _pace(self):
        """Wave step 8: the action from the latest readings, journaled as `pacing` when the reading changed.

        With nothing read from either surface yet, the action stands as it is: a run is never
        slowed or stopped on a guess. `action` is the one a launch off Fable runs under, read from
        the five-hour and all-models windows, and `fable_action` the one a launch on a Fable rung
        runs under, read from Fable's weekly window and the all-models week (decision 16); the
        event carries both. Fable's weekly window never moves the run's action: at `stop_at` it
        begins or ends the hold on Fable launches (`_hold_by_reading`), and at `cheap_at` it steps
        a Fable launch one rung down, to the lowest Fable rung and no further.
        """
        self._force_reading()
        if not self.windows.known():
            return
        now = self.clock()
        stop_at, cheap_at = self._thresholds()
        reading = {name: self.windows.utilization(name, now) for name in pacing.READINGS}
        if self.windows.known(pacing.WINDOWS):
            self.action = pacing.action_for(reading["five_hour"], reading["seven_day"], stop_at, cheap_at)
        if self.windows.known(pacing.windows_for(pacing.FABLE)):
            self.fable_action = pacing.rung_action(pacing.FABLE, reading, stop_at, cheap_at)
        reading["action"], reading["fable_action"] = self.action, self.fable_action
        if reading != self.view.pacing:
            self.ledger.append_event(PACING, reading)
            self._tail()
            self.say("  pacing: %s (five_hour %s, seven_day %s, fable %s %s; stop at %s, cheap only at %s)"
                     % (self.action, reading["five_hour"], reading["seven_day"], reading["fable"],
                        self.fable_action, stop_at, cheap_at))
        self._hold_by_reading(reading["fable"], stop_at)

    def simulate_step_down(self, seconds, model=None):
        """Force a reading past `cheap_at` and under `stop_at` for `seconds`: `run --simulate-limit cheap:[fable:]<seconds>`.

        On every model's windows, or on Fable's weekly window alone with `model` `fable`, so the M5
        demo can show launches one rung down without waiting for a window to be nearly spent. The
        reading is taken again at every wave, so a real one read meanwhile does not undo it, and it
        lapses on its own once the seconds are out, because a reading whose reset has passed is no
        reading (`Windows.utilization`). `seconds` None disarms it.
        """
        self._simulated_step = None if seconds is None else (float(seconds), model)
        self._simulated_until = None

    def simulate_fable_hold(self, on=True):
        """`run --simulate-limit fable:<seconds>`: the hold the simulated refusal begins stands until its own reset.

        The simulated refusal is written into one Fable session's stream; a real `/usage` reading taken before the
        next Fable wave would read the week as it truly is and end the hold at once, so nothing on Fable would ever
        be seen falling back (the M5 overnight run). While a hold stands, Fable's week is read as spent until the
        hold's reset, as `simulate_step_down` forces its reading for its seconds; past the reset nothing is forced.
        """
        self._simulated_fable = bool(on)

    def _force_fable_hold(self):
        """Read Fable's weekly window as spent while the simulated hold stands (`simulate_fable_hold`)."""
        hold = self.view.hold if self._simulated_fable else None
        resets = pacing.epoch((hold or {}).get("resets_at"))
        now = self.clock()
        if resets is not None and resets > now:
            self.windows.record(pacing.FABLE, 1.0, resets, now)

    def _force_reading(self):
        """Take the simulated reading of `simulate_step_down`, while its seconds last."""
        self._force_fable_hold()
        if self._simulated_step is None:
            return
        seconds, model = self._simulated_step
        now = self.clock()
        stop_at, cheap_at = self._thresholds()
        forced = round((cheap_at + stop_at) / 2, 4) if cheap_at < stop_at else cheap_at
        if self._simulated_until is None:
            self._simulated_until = now + seconds
            self.say("  simulating a reading of %s on %s until %s, at or above cheap_at %s and under stop_at %s"
                     % (forced, "Fable's weekly window" if model == pacing.FABLE else "the windows every model draws on",
                        pacing.iso(self._simulated_until), cheap_at, stop_at))
        if now >= self._simulated_until:
            self._simulated_step = None
            return
        for name in (pacing.FABLE,) if model == pacing.FABLE else pacing.WINDOWS:
            self.windows.record(name, forced, int(self._simulated_until), now)

    def _hold_by_reading(self, fable, stop_at):
        """The hold a reading of Fable's weekly window calls for: begun at `stop_at` or above, ended under it.

        `cheap_at` never applies, since Fable has no cheaper tier (decision 15). A reading under
        `stop_at` can end a hold only when it is newer than what began the hold, which `Windows`
        sees to: a reading is replaced only by one read at the same moment or later.
        """
        if fable is None:
            return
        if self.view.hold is None and fable >= stop_at:
            reading = self.windows.readings.get(pacing.FABLE)
            self._hold(pacing.Limit(pacing.READING_SIGNAL, reading.resets_at if reading else None, pacing.SEVEN_DAY,
                                    fable, pacing.FABLE), "Fable's weekly window reads %s, at or above stop_at %s" % (fable, stop_at))
        elif self.view.hold is not None and fable < stop_at:
            self._unhold("Fable's weekly window reads %s, under stop_at %s" % (fable, stop_at))

    def _thresholds(self):
        """`(stop_at, cheap_at)`: `policy.pacing`, under `harness.json`'s `pacing`, under a `control pacing` event's."""
        try:
            harness = read_harness(self.project)
        except (ProjectError, ValueError, OSError):
            harness = {}
        return pacing.thresholds(self.policy.get("pacing"), harness.get("pacing"), self.view.thresholds)

    def _autonomy(self):
        """The autonomy this run holds: the journal's (`run_started`, then `control autonomy`), else `harness.json`'s."""
        if self.view.autonomy:
            return self.view.autonomy
        try:
            return read_harness(self.project).get("autonomy")
        except (ProjectError, ValueError, OSError):
            return None

    def _wait_seconds(self):
        """How long `run` waits before the next wave: `policy.poll_seconds`, or less when a pause or the hold resets sooner."""
        seconds = self._poll_seconds()
        for stands in (self.view.pause, self.view.hold):
            resets = pacing.epoch((stands or {}).get("resets_at"))
            if resets is not None:
                seconds = max(0, min(seconds, resets - self.clock()))
        return seconds

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
        The asks of decision 15 the conductor answers itself are answered first (`_settle_asks`), so an
        answer written into the file of an ask closed as superseded is not taken.
        """
        self._settle_asks()
        written = journal_written_answers(self.project, self.ledger)
        for identifier in sorted(written):
            self.say("  ticket %d: the answer written in its file is journaled as the owner's" % identifier)
        placed = False
        for ticket in tickets.read_tickets(self.project):
            if ticket["kind"] != tickets.DECISION:
                continue
            known = written.get(ticket["id"]) or self.view.answers.get(ticket["id"])
            if known is not None and ticket["status"] not in tickets.SATISFIED + ("parked",):
                self._set_status(ticket["id"], "done")
                self.say("  ticket %d answered by the %s: %s" % (ticket["id"], known.get("decided_by"), known.get("answer")))
                self._answered_ask(ticket["id"], known)
                self._answered_frontier(ticket, known)
                placed = placed or concerns.concern_of(ticket.get("origin")) is not None
        if placed:
            self._concerns()  # the answer places its concern now, even when the run ends with this wave

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
        self._cancel_jobs(identifier)
        if command == "cancel":
            self.ledger.append_event(TICKET_CANCELLED, {"ticket": identifier, "by": by}, ticket=identifier)
            self._set_status(identifier, "parked")
            self.say("  ticket %d cancelled by %s; it is parked" % (identifier, by))
        else:
            self.ledger.append_event(TICKET_RERUN, {"ticket": identifier, "by": by}, ticket=identifier)
            ticket, body = self._ticket(identifier)
            tickets.write_ticket(self.ledger, dict(ticket, status="open"), tickets.retire_answer(body))
            self.say("  ticket %d rerun by %s; it is open for a new attempt" % (identifier, by))

    def _place_staged(self, attempt):
        """What the worker could only stage under `.wayline-staged/` put under `.claude/` and committed on the ticket's branch.

        Claude Code refuses a headless session's writes under `.claude/` (`worker.STAGED`), so a local skill or role
        override arrives staged. `wayline accept` places it when the worker runs it; this places what is still staged
        and commits the placement either way, before the acceptance, the proof, and the integration read the branch.
        """
        touches = [touch for touch in attempt.ticket["touches"] if worker.staged_path(touch) is not None]
        if not touches:
            return
        worker.place_staged(attempt.worktree, touches)
        paths = [touch for touch in touches if (attempt.worktree / touch).exists()]
        if self._git(attempt.worktree, "ls-files", "--", worker.STAGED).stdout.strip():
            paths.append(worker.STAGED)
        if not paths:
            return
        self._git(attempt.worktree, "add", "-A", "-f", "--", *paths)  # a project may ignore .claude/; this touch is its work
        if self._git(attempt.worktree, "diff", "--cached", "--quiet", "--", *paths, ok=None).returncode != 0:
            self._git(attempt.worktree, "commit", "-q", "-m", "ticket %d: place the staged %s" % (attempt.id, ", ".join(touches)), "--", *paths)
            self.say("  ticket %d: placed the staged %s" % (attempt.id, ", ".join(touches)))

    def _accept(self, attempt, where, cwd):
        """Run the ticket's machine acceptance in `cwd` and journal it under the label `where`."""
        if where == "worktree" and Path(cwd) == Path(attempt.worktree):
            self._place_staged(attempt)
        commands = tickets.machine_acceptance(attempt.ticket)
        results = gates.run_machine_acceptance(commands, cwd, self._timeout())
        if where == "worktree":
            results = (list(results) + self._sections_check(attempt) + self._lint_check(attempt) + self._numbers_check(attempt)
                       + self._references_check(attempt) + self._methods_check(attempt) + self._verification_check(attempt))
            results = results + self._repeats_check(attempt, results)
        simulated = worker.simulated_failure(attempt.id)  # `wayline run --simulate-failure` (ticket 38)
        if simulated is not None:
            results = list(results) + [simulated]
        record = gates.acceptance_file_record(results, where)
        self.ledger.append_event(ACCEPTANCE, {
            "ticket": attempt.id, "attempt": attempt.number, "where": where,
            "pass": record["pass"], "results": record["results"],
        }, ticket=attempt.id, session_id=attempt.session_id)
        self.say("  acceptance (%s): %s" % (where, "pass" if record["pass"] else "fail"))
        return record

    def _sections_check(self, attempt):
        """The declared-sections check of decision 17 as one acceptance result, or none for a ticket that declares none.

        A declared section that got no passage (Results, no finding) or a `replaces` naming nothing its section holds
        fails it, and the worker is sent back with the problems, as for any machine criterion that failed in its worktree.
        """
        if not sections.declared(attempt.ticket):
            return []
        problems = sections.check_result(self.ledger, attempt.ticket, attempt.result)
        return [{"cmd": SECTIONS_CHECK, "exit_code": 1 if problems else 0, "seconds": 0.0,
                 "tail": "\n".join(problems) if problems else "every declared section got its passage"}]

    def _verification_check(self, attempt):
        """A verification ticket's verdict (decision 17; ticket 97) as one acceptance result, or none for any other ticket.

        It names its route; `reproduced` runs at the commit intake recorded; a verdict on substitute data narrows each claim
        it replaces. A failing one sends the worker back with the problems.
        """
        if not attempt.ticket.get("verifies"):
            return []
        problems = verification.check_result(self.project, attempt.ticket, attempt.result)
        return [{"cmd": VERIFICATION_CHECK, "exit_code": 1 if problems else 0, "seconds": 0.0,
                 "tail": "\n".join(problems) if problems else "the verdict names its route"}]

    def _lint_check(self, attempt):
        """The provenance linter (decision 17; ticket 88) over the result's passages and findings, as one acceptance result.

        Every tag must resolve (a `code` tag against the ticket's worktree, the attempt's own `res` tags by the files of
        its worktree) and every sentence the classifier calls a claim must end with one; a failing sentence sends the
        worker back. The classifier is asked only about the sentences that end with no tag, one haiku batch through
        `self.classifier`; when it cannot answer, those sentences are listed in the tail, never failed. None for a result
        with no passage and no finding carrying a tag of its own, since a finding's provenance tags it.
        """
        result = attempt.result or {}
        tagged = [item for item in result.get("findings") or [] if isinstance(item, dict)
                  and _provenance().ANY_TAG_RE.search(str(item.get("text") or ""))]
        if not result.get("passages") and not tagged:
            return []
        classes = self.classifier(_provenance().result_sentences(result))
        lint = _provenance().lint_result(self.project, result, classes, code_root=attempt.worktree,
                                               run_id="t%d-a%d" % (attempt.id, attempt.number))
        lines = ["%s (%s): %s%s; %s" % (problem["problem"], problem["passage"], problem["sentence"],
                                        " tag `%s`" % problem["tag"] if problem["tag"] else "", problem["detail"])
                 for problem in lint.problems]
        lines += ["listed, not failed: %s (%s): %s" % (item["problem"], item["passage"], item["sentence"]) for item in lint.listed]
        tail = "\n".join(lines) if lines else "every claim sentence ends with a provenance tag that resolves"
        return [{"cmd": LINT_CHECK, "exit_code": 0 if lint.passed else 1, "seconds": 0.0, "tail": tail}]

    def _numbers_check(self, attempt):
        """The numbers check (decision 17; ticket 90) over the result's findings as one acceptance result; none without a finding.

        Every number in a finding must match a value at its sentence's `res` locators, read in the ticket's worktree and
        then the project, a tag naming another run only while the manifest still holds that run's file at its path. Each
        sentence code cannot match goes to a fresh verifier through `self.numbers_verifier`; a failing verdict sends the
        worker back with the sentence. A verifier launches only when every other verdict would (pacing `normal` and no
        hold on launches); otherwise the sentences are listed, never failed.
        """
        findings = [item for item in (attempt.result or {}).get("findings") or [] if isinstance(item, dict)]
        if not findings:
            return []
        from wayline import provenance  # the provenance module pulls in the gates and the report
        runs = {entry.get("path"): entry.get("run_id") for entry in provenance.read_manifest(self.ledger).get("entries", [])}
        outcome = numbers.check(findings, numbers.reader(attempt.worktree, self.project), numbers.spec_parameters(self.project),
                                runs=runs, own_run="t%d-a%d" % (attempt.id, attempt.number))
        if outcome.unmatched and (self.action != schedule.NORMAL or self._holds_launches()):
            judged = numbers.Judged(outcome, [(sentence, None, "the run holds its verdicts now, so no verifier was launched")
                                              for sentence in outcome.unmatched])
        else:
            judged = self.numbers_verifier(attempt, outcome) if outcome.unmatched else numbers.Judged(outcome)
        return [numbers.acceptance_result(judged)]

    def _verify_numbers(self, attempt, outcome):
        """One fresh verifier per sentence whose numbers code could not match, on the verifier the table gives for its author."""
        return numbers.judge(self.project, outcome, ticket=attempt.id, author_model=attempt.tier.model, fall_back=self._falls_back(),
                             policy=self.policy, harness_root=self.harness_root, ledger=self.ledger, cwd=attempt.worktree)

    def _classify(self, texts):
        """The classifier's classes for `texts`, one haiku batch through the launcher for what the cache does not hold.

        A launch that fails or a usage window that refuses it leaves the sentences it did not reach unclassified, which
        the acceptance lists rather than fails: a closed window is no verdict on the worker's prose.
        """
        provenance = _provenance()
        if not texts or schedule.holds_model_work(self.action):  # a pacing stop launches no model, the classifier included
            return provenance.read_claims_cache(self.ledger)
        try:
            return provenance.classify(self.project, texts, harness_root=self.harness_root, policy=self.policy)
        except (provenance.ProvenanceError, worker.LaunchError, OSError) as failure:
            self.say("  the sentence classifier did not answer at acceptance: %s" % failure)
            return provenance.read_claims_cache(self.ledger)

    def _references_check(self, attempt):
        """The check of a ticket's references (decision 17; ticket 98) as one acceptance result, or none for a result that cites nothing.

        Every cited work must be a dossier or listed in `references`, the scout runs free on the listed works no
        dossier holds, and a locator must name what the dossier holds at its level; a problem sends the worker back
        like any machine criterion that failed in its worktree, and a service failure passes with its flag.
        """
        result = attempt.result or {}
        if not result.get("references") and not references.cited(result):
            return []
        try:
            check = references.check_references(self.project, attempt.id, result, fetcher=self.scout_fetcher, ledger=self.ledger)
        except (ValueError, OSError) as failure:
            return [{"cmd": REFERENCES_CHECK, "exit_code": 1, "seconds": 0.0, "tail": "the references could not be checked: %s" % failure}]
        problems = check["problems"]
        tail = "\n".join(problems) if problems else "every cited work is a dossier or listed"
        if check["flagged"]:
            tail += "\naccepted with the retry flag, a service having failed: %s" % ", ".join(check["flagged"])
        return [{"cmd": REFERENCES_CHECK, "exit_code": 1 if problems else 0, "seconds": 0.0, "tail": tail}]

    def _methods_check(self, attempt):
        """The rule from code to Methods (decision 17, ticket 107) as one acceptance result; none when the diff changed no code.

        A developed method with no `code` tag in a current Methods passage, a used method no Methods passage names, or a
        parameter with no reason fails it, and the worker is sent back with the list. Code fills each `parameters` entry's
        value and default into the result, which `_close` keeps beside the attempt's session for the verdict that judges
        them. A reading a usage window refused fails the check and pauses the run.
        """
        try:
            outcome = methods.check(self.ledger, attempt.worktree, attempt.result, run=self.methods_run, tools=self.methods_tools,
                                    policy=self.policy, harness_root=self.harness_root, ticket=attempt.id, attempt=attempt.number)
        except (methods.MethodsError, OSError) as failure:
            self.say("  ticket %d: the code-to-Methods check could not read the diff: %s" % (attempt.id, failure))
            return []
        if outcome is None:
            return []
        if outcome.refused is not None:
            # A closed window, not a verdict on the work: the run pauses, and the files are read on the resume after it.
            self._pause(outcome.refused.limit, "ticket %d's code reading" % attempt.id)
        if outcome.parameters:  # entries come only from a result that gave some, so it is the envelope's own mapping
            attempt.result["parameters"] = outcome.parameters
        return [outcome.acceptance_result()]

    def _repeats_check(self, attempt, results=()):
        """The repeated-claims check (decision 17; ticket 95) as one acceptance result; none when nothing could be repeated.

        A new passage or finding that repeats a current passage without naming it in `replaces` sends the worker back with
        the passage it repeats. The embedding model runs with no tokens; the confirmer is a session on Opus, so a pacing
        stop leaves the check listed rather than run, and so does a model or a confirmer that cannot answer. A confirmer a
        usage window refused fails the check and pauses the run, as the code reading does. It is not run when an earlier
        result already sends the worker back: the text it would read is about to change.
        """
        from wayline import repeats  # the repeated-claims check reads every section
        result = attempt.result or {}
        if not result.get("passages") and not result.get("findings"):
            return []
        if any(item.get("exit_code") != 0 for item in results):
            return []
        if schedule.holds_model_work(self.action):
            return [{"cmd": repeats.REPEATS_CHECK, "exit_code": 0, "seconds": 0.0,
                     "tail": "listed, not failed: repeats not checked: a pacing stop launches no model"}]
        try:
            checked = repeats.check_result(self.project, result, run=self.repeats_run, tools=self.repeats_tools, policy=self.policy,
                                           harness_root=self.harness_root)
        except (repeats.RepeatsError, ValueError, OSError) as failure:
            return [{"cmd": repeats.REPEATS_CHECK, "exit_code": 0, "seconds": 0.0,
                     "tail": "listed, not failed: repeats not checked: %s" % failure}]
        if checked is None:
            return []
        if checked.refused is not None:
            # A closed window, not a verdict on the text: the run pauses, and the check runs again on the resume after it.
            self._pause(checked.refused.limit, "ticket %d's repeated-claims check" % attempt.id)
        return [checked.acceptance_result()]

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
        Bytecode (`__pycache__/`, `*.pyc`) never counts, inside the touch set or out.
        """
        dirty = [path for status, path in porcelain_entries(self._git(attempt.worktree, "status", "--porcelain", "-z").stdout)
                 if status != "??" or (_in_touch_set(path, attempt.ticket["touches"]) and not _bytecode(path))]
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
            self._fail(attempt, problem, self._step_from(attempt.id, SPLIT) if spent else self._next_step(attempt))
            return "failed"
        before = self._branch_paths(attempt)
        self._commit_harness_json(attempt)
        with self.ledger.lock():
            conflict = self._rebase(attempt)
        if conflict is not None and spent:
            self._fail(attempt, "rebasing %s onto main conflicts in %s, and the integrator was already launched for "
                       "this attempt before the conductor restarted" % (BRANCH % attempt.id, ", ".join(conflict.paths)
                                                                        or "a path git did not name"), self._step_from(attempt.id, SPLIT))
            return "failed"
        if conflict is not None:
            if not conflict.paths:
                self._fail(attempt, "rebasing %s onto main failed and git named no conflicting path, so there is "
                           "nothing an integrator could resolve: %s" % (BRANCH % attempt.id, conflict.output), self._step_from(attempt.id, SPLIT))
                return "failed"
            if self._integrator_waits(attempt):
                attempt.integrating, attempt.want = True, _Want(INTEGRATE)
                self.say("  ticket %d: rebasing onto main conflicts in %s; the integrator waits until the run may launch again"
                         % (attempt.id, ", ".join(conflict.paths)))
                return "session"
            # Every path both sides changed may conflict, not only the one the rebase stopped on first.
            touches = sorted(set(conflict.paths) | (before & self._main_paths(attempt)))
            told = self._launch_integrator(attempt, conflict, touches)
            if told is None:  # a usage window refused it: it is not spent, and is launched again once the window allows
                attempt.integrating, attempt.want = True, _Want(INTEGRATE)
                return "session"
            resolved_by = INTEGRATOR
            with self.ledger.lock():
                again = self._rebase(attempt)
            if again is not None:
                self._fail(attempt, "rebasing %s onto main conflicted in %s; the integrator %s; the rebase after it "
                           "still fails%s" % (BRANCH % attempt.id, ", ".join(conflict.paths), told,
                                              " in " + ", ".join(again.paths) if again.paths else ": " + again.output),
                           self._step_from(attempt.id, SPLIT))
                return "failed"
            problem = self._off_branch(attempt) or _changed_by_integrator(before, self._branch_paths(attempt))
            if problem is not None:
                self._fail(attempt, "the integrator %s; %s" % (told, problem), self._step_from(attempt.id, SPLIT))
                return "failed"
        if not self._accept(attempt, "rebased", attempt.worktree)["pass"]:
            self._fail(attempt, "the machine acceptance failed after the rebase onto main", self._next_step(attempt))
            return "failed"
        with self.ledger.lock():
            base = self._head(self.project)
            merge = self._git(self.project, "merge", "--ff-only", BRANCH % attempt.id, ok=None)
            commit = attempt.commit = self._head(self.project) if merge.returncode == 0 else None
        if commit is not None and attempt.result.get("status") == "running" and self._goal_ticket(attempt.ticket):
            # Its jobs are judged after this fast-forward, and a discard reverts `base..commit` (ticket 39).
            self.ledger.write_json(self._integration_record(attempt.id, attempt.number), {"base": base, "commit": commit})
        if merge.returncode != 0:
            self._fail(attempt, "main could not be fast-forwarded to %s: %s"
                       % (BRANCH % attempt.id, (merge.stderr or merge.stdout).strip()), self._step_from(attempt.id, SPLIT))
            return "failed"
        if not self._accept(attempt, "main", self.project)["pass"]:
            self._fail(attempt, "the machine acceptance failed on main after the fast-forward to %s; main "
                       "carries the commit and a person has to look" % commit[:12], "needs_human")
            return "failed"
        if self.view.integrated.get(attempt.id) != commit:  # journaled already by a conductor that died after it
            integrated = {"ticket": attempt.id, "commit": commit, "resolved_by": resolved_by}
            if commit == base:
                integrated["empty"] = True  # the fast-forward moved nothing: the ticket added no commit of its own
                attempt.no_diff = True
            self.ledger.append_event(INTEGRATED, integrated,
                                     ticket=attempt.id)
        self._integrated_now = True  # the general report renders at the end of this wave (ticket 90)
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

    def _set_aside(self, run_dir):
        """Move a refused integrator's session directory aside, kept for the record, so its one launch is not spent."""
        number = 1
        while run_dir.with_name("%s-refused-%d" % (run_dir.name, number)).exists():
            number += 1
        aside = run_dir.with_name("%s-refused-%d" % (run_dir.name, number))
        run_dir.rename(aside)
        return aside

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
        """Launch the integrator once, in the worktree, with `touches` as its touch set; what it came to, in words, or None if refused.

        A session a usage window refused is no launch at all: the limit is journaled, its directory
        is set aside, and None tells the integration to wait and launch it again (decision 15).

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
            limit = pacing.hit_limit(envelope, worker.stderr_tail(run_dir), self.clock(), model=tier.model)
            if limit is not None and not envelope.valid:
                self._pause(limit, "ticket %d's integrator" % attempt.id)
                self._git(attempt.worktree, "rebase", "--abort", ok=None)  # what the refused session began is not left in progress
                try:
                    aside = self._set_aside(run_dir)
                except OSError as failure:  # its one launch stays spent, and the rebase after it fails the ticket as it would
                    told = ("was refused by the usage limit, and its session could not be set aside to be launched again (%s)"
                            % failure)
                else:
                    self.say("  ticket %d: the usage limit refused the integrator; its session is kept in %s, and it is "
                             "launched again, never resumed, once the window allows" % (attempt.id, aside.name))
                    return None
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

    def _integrator_waits(self, attempt):
        """Whether the integrator may not launch now: the run holds model work, or it runs on Fable while the hold stands.

        Its request defines the one agent, on its tier's model, so that model says whether it is on Fable.
        The run is asked again after the hold, because the `/usage` the hold may read can say `stop`, and
        so is the tier, because under the fallback consent `auto` a hold that reading began moves it to Opus.
        """
        if self._holds_launches():
            return True
        if self._integrator_tier(attempt).family == pacing.FABLE and self._fable_held() and not self._falls_back():
            self._held_back("ticket %d's integrator" % attempt.id)
            return True
        return self._holds_launches()

    def _integrator_tier(self, attempt):
        """`policy.roles.integrator`'s model and effort, with the ticket's own budget and the model's context cap.

        On Fable while the hold stands under the fallback consent `auto`, it falls back to Opus like any launch.
        """
        entry = (self.policy.get("roles") or {}).get(INTEGRATOR) or {}
        model, effort = entry.get("model") or attempt.tier.model, entry.get("effort") or attempt.tier.effort
        caps = (self.policy.get("context_pack") or {}).get("max_chars") or {}
        tier = Tier(model=model, effort=effort, max_turns=attempt.tier.max_turns, max_minutes=attempt.tier.max_minutes,
                    context_chars=caps.get(pacing.family(model) or model, attempt.tier.context_chars))
        return fallback_tier(self.policy, tier) if tier.family == pacing.FABLE and self._falls_back() else tier

    # --- closing the ticket ---

    def _close(self, attempt, discarded=None, waits_for_owner=None):
        """The findings, the status, `ticket_done`, and the worktree the ticket no longer needs.

        A finding's provenance must resolve in the manifest (decision 6): a cited file on `main` that the
        manifest does not name yet is registered for this attempt, and a finding citing nothing that is
        either is refused, said, and noted on the ticket, without failing the work that filed it.

        A change keep-if-better `discarded` (a `Judgment`) is closed without its integration: its findings
        are negative results, a file they cite in the worktree is cited there, it earns no verdict, and its
        worktree and branch stay (ticket 39).

        A global change (ticket 45) is closed without an integration too: `waits_for_owner` is the note that says
        where its branch stands, it earns no verdict here because the owner reads the branch, and its worktree
        and branch stay.
        """
        notes = self._file_findings(attempt, attempt.result.get("findings") or [], discarded is not None, attempt.worktree)
        if discarded is None and waits_for_owner is None:
            notes += self._file_passages(attempt)  # its work is on `main` now; a change not integrated adds no passage
        if discarded is not None:
            notes.append(self._discard_note(attempt, discarded))
        if waits_for_owner is not None:
            notes.append(waits_for_owner)
        if notes:
            attempt.body = tickets.with_result_note(attempt.body, notes)
        rule = methods.code_rule(attempt.result)
        if rule is not None and discarded is None and waits_for_owner is None:
            # What the verdict judges, kept beside the session so a restarted conductor asks the same (ticket 107).
            methods.write_code_rule(self._attempt_dir(attempt), rule)
        if discarded is None and waits_for_owner is None:
            self._take_verdicts_on_inherited(attempt)
        self._write_ticket(attempt, "done", attempt.result)
        self.ledger.append_event(TICKET_DONE, {"ticket": attempt.id}, ticket=attempt.id)
        if discarded is not None:
            self.say("  ticket %d done and not integrated: its change was discarded" % attempt.id)
            return
        if waits_for_owner is not None:
            self.say("  ticket %d done and not integrated: its branch waits for the owner" % attempt.id)
            return
        self._queue_verdicts(attempt)
        self._remove_worktree(attempt.id)
        self.say("  ticket %d done" % attempt.id)

    def _file_findings(self, attempt, findings, negative, worktree):
        """File each finding whose provenance resolves, negative when `negative`; the notes on those refused."""
        refused = []
        for index, finding in enumerate(findings, start=1):
            provenance = finding["provenance"]
            if negative:
                provenance = self._in_worktree(provenance, worktree)
            problem = self._unresolved(attempt, provenance)
            if problem is not None:
                refused.append("A finding was refused: %s (%s)" % (problem, finding["text"]))
                self.say("  ticket %d: a finding was refused: %s" % (attempt.id, problem))
                continue
            record = {
                "id": "t%d-a%d-f%d" % (attempt.id, attempt.number, index),
                "ticket": attempt.id,
                "text": finding["text"],
                "provenance": provenance,
                "negative": bool(negative or finding.get("negative", False)),
                # A finding is a Results passage (decision 17): its heading (the ticket's title when it named none),
                # the finding a scope-down narrows, and the ticket's objectives.
                "heading": finding.get("heading") or attempt.ticket["title"],
                # A discarded change displaces nothing: its findings stand beside what they would have replaced.
                "replaces": None if negative else finding.get("replaces"),
                "objectives": list(attempt.ticket.get("objectives") or []),
                # What this project's evidence says of the inherited claim it replaces (ticket 93).
                "evidence": None if negative else finding.get("evidence"),
                # Why its evidence overrides the owner's passage it replaces (ticket 88).
                "reason": None if negative else finding.get("reason"),
            }
            if record["id"] in self.view.findings:
                continue  # filed before a restart
            if not negative:
                self._manifest_own_tags(attempt, finding["text"])
            try:
                line = sections.file_finding(self.ledger, record, wave=self._wave_key(), render=False)
            except sections.SectionError as failure:
                refused.append("A finding was refused: %s (%s)" % (failure, finding["text"]))
                self.say("  ticket %d: a finding was refused: %s" % (attempt.id, failure))
                continue
            attempt.findings += 1
            self._owner_overridden(attempt, line)
        if attempt.findings:
            sections.render_section(self.ledger, sections.RESULTS)
        return refused

    def _wave_key(self):
        """The wave a passage or a finding lands in, unique across runs: `<run>/<number>`."""
        return "%s/%d" % (self._run_key, self.number)

    def _file_passages(self, attempt, passages=None):
        """Write the passages the attempt returned (or `passages`), through the ledger, and render the sections they
        touched; the notes on those refused.

        Called once the ticket's work is on `main` (for a running result, once its jobs closed and its change was
        kept), under the ledger lock, so tickets adding to one section are written one at a time in the order the wave
        carries them, which is id order. A passage filed before a restart (the same `by`, section, heading, and text)
        is not filed again.
        """
        refused, touched = [], set()
        passages = attempt.result.get("passages") if passages is None else passages
        by = sections.by_ticket(attempt.id, attempt.number)
        with self.ledger.lock():
            filed = {(item.get("section"), item.get("heading"), item.get("text")) for item in sections.read_passages(self.ledger)
                     if item.get("by") == by}
            for item in [entry for entry in passages or [] if isinstance(entry, dict)]:
                key = (item.get("section"), " ".join(str(item.get("heading") or "").split()), str(item.get("text") or "").strip())
                if key in filed:
                    continue
                try:
                    self._manifest_own_tags(attempt, item.get("text"))
                    record = sections.add_passage(self.ledger, item.get("section"), item.get("heading"), item.get("text"), by=by,
                                                  replaces=item.get("replaces"), objectives=attempt.ticket.get("objectives") or [],
                                                  ticket=attempt.id, wave=self._wave_key(), render=False, evidence=item.get("evidence"),
                                                  reason=str(item.get("reason") or "").strip() or None)
                    touched.add(item.get("section"))
                    self._owner_overridden(attempt, record)
                except sections.SectionError as failure:
                    refused.append("A passage was refused: %s (%s)" % (failure, item.get("heading")))
                    self.say("  ticket %d: a passage was refused: %s" % (attempt.id, failure))
            sections.render_sections(self.ledger, only=[name for name in sections.SECTIONS if name in touched])
        return refused

    def _owner_overridden(self, attempt, record):
        """Under autonomy `interactive`, a passage or finding that replaced an owner's passage is a notice (ticket 88).

        The `passage` or `finding` event already carries `replaces_owner` and the reason, which the account lists under
        "Changed without asking you"; at the other autonomies that listing is the whole of it.
        """
        if not (record or {}).get("replaces_owner") or self._autonomy() != INTERACTIVE:
            return
        self.notify(sections.PASSAGE, "%s: ticket %d replaced your passage %s in %s: %s" % (
            self.project.name, attempt.id, record.get("replaces"), sections.TITLES.get(record.get("section"), "Results"),
            record.get("reason") or "no reason given"), self.project, attempt.id)

    def _manifest_own_tags(self, attempt, text):
        """A passage's or finding's `res` tags of the attempt's own run name files the linter took from its worktree, which
        its branch carried to `main`: manifest each under this run, the one the tag names, as the run that wrote it."""
        provenance = _provenance()
        own = "t%d-a%d" % (attempt.id, attempt.number)
        for sentence in provenance.sentences(str(text or "")):
            for found in sentence.tags:
                kind, parts = provenance.parse_tag(found)
                if kind != "res" or not parts or parts["run_id"] != own:
                    continue
                artifact = Path(parts["artifact"])
                path = self.project / artifact
                if artifact.is_absolute() or ".." in artifact.parts or not _inside(path, self.project) or not path.is_file():
                    self.say("  ticket %d: `{%s}` names no file on main, so it stays unresolved" % (attempt.id, found))
                    continue
                provenance.register_artifact(self.ledger, artifact.as_posix(), None, own, attempt.id)

    def _in_worktree(self, provenance, worktree):
        """A discarded change's `<path>#<locator>` spelled at the worktree it stays in, when the file is there.

        Its artifacts never reach `main`, so a path that names a file of the worktree names that file,
        not whatever `main` holds under the same name.
        """
        artifact, sep, locator = str(provenance).partition("#")
        if not sep or not artifact or Path(artifact).is_absolute() or ".." in Path(artifact).parts:
            return provenance
        if worktree is None or not (Path(worktree) / artifact).is_file():
            return provenance
        relative = (Path(worktree) / artifact).relative_to(self.project).as_posix()
        return "%s#%s" % (relative, locator)

    def _unresolved(self, attempt, provenance):
        """Why a finding's `<path>#<locator>` does not resolve in the manifest, registering a cited file on `main`; None when it does."""
        from wayline import provenance as provenance_module  # the provenance module pulls in the gates and the report
        artifact, sep, locator = str(provenance).partition("#")
        if not sep or not artifact or not locator:
            return "provenance %r is not <path>#<locator>" % provenance
        if artifact in provenance_module.manifest_paths(provenance_module.read_manifest(self.ledger)):
            return None
        path = self.project / artifact
        if Path(artifact).is_absolute() or ".." in Path(artifact).parts or not _inside(path, self.project) or not path.is_file():
            return "provenance %r cites %s, which is neither in manifest.json nor a file in the project" % (provenance, artifact)
        provenance_module.register_artifact(self.ledger, artifact, None, "t%d-a%d" % (attempt.id, attempt.number), attempt.id)
        return None

    # --- the decider (decision 10; ticket 31) ---

    def _decide(self, result):
        """Wave step 5: under autonomy `autonomous`, launch the decider on every open decision ticket not human-only.

        One session per ticket, taken here like a verdict rather than picked as a worker: at the decider's
        tier (`policy.roles.decider`), with `decision.json` as its schema and no worktree, since it writes
        nothing but its answer. It is model work, so it waits under pacing and, when its tier is Fable, under
        the hold on Fable's weekly window, falling back to Opus when the consent says (decision 15). A ticket
        answered is closed in this same wave, so what it paused launches now rather than a wave later; one the
        decider was refused turns human-only and waits for the owner; one nobody could decide is handed to a
        person (`ticket_needs_human`) rather than tried again every wave.
        """
        if not self._decider_takes():
            return
        try:
            asked = decisions.for_the_decider(self.project, self.view)
        except (ValueError, OSError) as failure:
            self.say("  the decision tickets could not be read for the decider: %s" % failure)
            return
        frontier = [(fields, body, record, stopping.frontier_objective(fields.get("origin"))) for fields, body, record in asked
                    if stopping.frontier_objective(fields.get("origin")) is not None]
        asked = [(fields, body, record) for fields, body, record in asked if stopping.frontier_objective(fields.get("origin")) is None]
        if frontier and not self._decide_frontier(frontier, result):
            return
        for fields, body, record in asked:
            if self._holds_launches() or self.action != schedule.NORMAL:
                return
            outcome, stopped = self._launch_decider("the decider on ticket %d" % fields["id"], lambda falls_back: decider.decide_ticket(
                self.project, fields, body, record, harness_root=self.harness_root, policy=self.policy, fall_back=falls_back,
                notify=self.notify))
            if stopped:
                return
            if outcome is None:
                continue
            if outcome.status == "failed":
                self._decider_failed(fields["id"], outcome.why)
                continue
            self.say("  ticket %d: %s" % (fields["id"], outcome.line))
            if outcome.status == "decided":
                result.decided.append(fields["id"])
        if result.decided:
            self._tail()
            self._apply_answers()  # closed now, so what the answered tickets paused is launchable in this wave

    def _decide_frontier(self, entries, result):
        """The decider on an empty frontier's tickets, in one session (ticket 87); False when the wave decides no more.

        It replans or answers each objective the rule waits on; a park, a drop, or nothing is turned over to the owner.
        """
        if self._holds_launches() or self.action != schedule.NORMAL:
            return False
        outcome, stopped = self._launch_decider(decider.FRONTIER_SUBJECT, lambda falls_back: decider.decide_frontier(
            self.project, entries, harness_root=self.harness_root, policy=self.policy, fall_back=falls_back, notify=self.notify))
        if stopped:
            return False
        if outcome is None:
            return True
        if isinstance(outcome, tuple):
            outcome, decided = outcome
        else:
            decided = []
        if outcome.status == "failed":
            for fields, _, _, _ in entries:
                self._decider_failed(fields["id"], outcome.why)
            return True
        self.say("  %s" % outcome.line)
        result.decided.extend(decided)
        return True

    def _launch_decider(self, what, decide):
        """One launch of the decider under the wave's rules: `(outcome, stopped)`.

        `decide(falls_back)` is the launch. It waits for the hold on Fable's weekly window when the decider's tier is
        Fable and the consent waits (`outcome` None, named for the ask of decision 15), and a usage window that
        refuses it pauses the run and stops this wave's deciding (`stopped`); a launch that raised is a failed
        outcome, for the caller to hand to a person or say aloud.
        """
        on_fable = decider.decides_on_fable(self.policy) and self._fable_held()
        falls_back = on_fable and self._falls_back()
        if on_fable and not falls_back:
            self._held_back(what)
            return None, False
        try:
            return decide(falls_back), False
        except gates.FableHeld:
            self._held_back(what)
            return None, False
        except gates.UsageLimited as refused:
            self._pause(refused.limit, what)
            self.say("  %s: the usage limit refused it; it is launched again once the window allows" % what)
            return None, True
        except (ValueError, OSError) as failure:
            return decider.Outcome(None, "failed", why=str(failure)), False

    def _decider_takes(self):
        """Whether the decider is launched in this wave: autonomy `autonomous`, a decider role that reads, and pacing `normal`.

        Without the role every decision ticket waits for the owner (`schedule.awaits_owner`), and a max-effort
        session is never cheap, so `cheap_only` holds it as it holds a verdict.
        """
        return (self._autonomy() == schedule.AUTONOMOUS and self.action == schedule.NORMAL
                and decisions.decider_ready(self.harness_root, self.project))

    def _decider_failed(self, identifier, why):
        """A decision ticket nobody could decide: `ticket_needs_human`, and the ticket waits for a person.

        The status leaves the frontier, so the run can end, while the ticket still pauses what it holds and
        `wayline answer` still takes the owner's answer; a retry every wave would spend a max-effort session
        each time on the same failure.
        """
        self.ledger.append_event(TICKET_NEEDS_HUMAN, {"ticket": identifier, "question": "the decider could not answer it: %s" % why},
                                 ticket=identifier)
        self._set_status(identifier, "needs_human", ["- the decider could not answer it: %s" % why])
        self.say("  ticket %d: the decider could not answer it (%s); it waits for a person" % (identifier, why))

    def _reconsider_parked(self, result):
        """The end of the wave: under `autonomous`, the decider reconsiders every parked proposal not yet reconsidered.

        Each answer is a `decision` with no ticket, `proposal <id>: admit` or `keep parked`. `decide_proposal`
        (ticket 31) only journals that opinion; `proposals.apply_admitted` (ticket 37) reads it back afterward and
        actually admits an `admit` within the cap, or leaves it parked for a later wave's cap to allow it. One
        already reconsidered is not asked again. The same pacing and hold rules as `_decide`.
        """
        if not self._decider_takes():
            return
        parked = decisions.parked_proposals(self.project)
        if parked:
            events, _ = self.ledger.read_events()
            taken = decider.reconsidered(self.project, events)
            for proposal in parked:
                if str(proposal["id"]) in taken or self._holds_launches() or self.action != schedule.NORMAL:
                    continue
                outcome, stopped = self._launch_decider(
                    "the decider on parked proposal %s" % proposal["id"], lambda falls_back: decider.decide_proposal(
                        self.project, proposal, harness_root=self.harness_root, policy=self.policy, fall_back=falls_back,
                        notify=self.notify))
                if stopped:
                    return
                if outcome is None:
                    continue
                if outcome.status == "failed":
                    self.say("  parked proposal %s: the decider could not reconsider it: %s" % (proposal["id"], outcome.why))
                    continue
                self.say("  %s" % outcome.line)
                result.reconsidered.append(str(proposal["id"]))
        try:
            admitted = proposals.apply_admitted(self.project, policy=self.policy, harness_root=self.harness_root,
                                                wave_cap=self._proposal_cap, notify=self.notify)
        except (ValueError, OSError) as failure:
            self.say("  a proposal the decider admitted could not be taken up: %s" % failure)
            return
        for outcome in admitted:
            if outcome["outcome"] == "admitted":
                self.say("  parked proposal %s: admitted as ticket %d" % (outcome["id"], outcome["ticket"]))

    # --- the Type-B gate (decision 11) ---

    def _take_verdicts_on_inherited(self, attempt, result=None):
        """A done ticket's verdicts on inherited claims (ticket 97): a verification ticket's verdict recorded with its route,
        and every verdict on an inherited claim kept beside the session for the fresh verifier, so a restart asks the same.
        `result` is the `running` result of a ticket whose jobs closed it, else the attempt's own."""
        result = attempt.result if result is None else result
        try:
            verification.take_result(self.project, attempt.ticket, result)
            items = verification.verdict_items(self.project, attempt.ticket, result)
        except (verification.VerificationError, verification.VerificationUnreadable, ValueError, OSError) as failure:
            self.say("  ticket %d's verdicts on inherited claims could not be recorded: %s" % (attempt.id, failure))
            return
        if items:
            path = self._attempt_dir(attempt) / INHERITED_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")

    def _inherited_items(self, identifier, number):
        """The verdicts on inherited claims kept beside a ticket attempt's session (ticket 97), or None."""
        try:
            items = json.loads((worker.session_dir(self.project, identifier, number) / INHERITED_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return items if isinstance(items, list) and items else None

    def _queue_verdicts(self, attempt):
        """Queue the verdicts this done ticket earned; nothing is launched from here.

        The queue is drained later in the wave, once every worker's outcome has been carried,
        because a verdict is model work like any other: it is paced with the rest, and it must not
        hold the integration of the tickets behind it.
        """
        outputs = attempt.result.get("outputs_written") or attempt.ticket.get("outputs") or []
        asks = gates.ticket_asks(
            attempt.ticket, attempt.difficulty, attempt.tier.model,
            tickets.relative_path(attempt.ticket), commit=attempt.commit, outputs=outputs, rung=attempt.tier.rung,
            no_diff=attempt.no_diff or attempt.id in self.view.integrated_empty, code_rule=methods.code_rule(attempt.result),
            inherited=self._inherited_items(attempt.id, attempt.number),
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
        state across a window boundary is worse than leaving both for the next wave. `cheap_only`
        holds it too, because a verdict runs above the work it judges, is not on the rung ladder,
        and so is never stepped down to a cheaper rung the way a ticket launch is (decision 16).

        While the hold on Fable's weekly window stands, a done ticket any of whose verdicts runs on
        Fable keeps every one of them queued, and the other tickets' verdicts are taken, unless the
        fallback consent is `auto`: then a fresh Opus session takes each of them at the table's effort,
        and its `verdict` carries `fallback_from: fable` (decision 15).
        """
        if not self.verdicts:
            return
        if self.action != schedule.NORMAL:
            self.say("  %d ticket(s) wait for a verdict; pacing says %s"
                     % (len(self.verdicts), self.action))
            return
        queued, self.verdicts = self.verdicts, []
        for entry in queued:
            on_fable = self._verdicts_on_fable(entry) and self._fable_held()
            falls_back = on_fable and self._falls_back()
            if (on_fable and not falls_back) or self._holds_launches() or self.action != schedule.NORMAL:
                # The ticket's verdicts wait whole: on the hold, or on a refusal or a `/usage` reading met in this wave.
                self.verdicts.append(entry)
                if on_fable and not falls_back:
                    self._held_back("the verdicts on ticket %d" % entry.ticket)
                continue
            self._gate(entry, result, falls_back)
        waiting = (sorted(entry.ticket for entry in self.verdicts if self._verdicts_on_fable(entry))
                   if self.view.hold is not None and not self._falls_back() else None)
        if waiting and waiting != self._said_waiting:
            self.say("  ticket(s) %s wait for a verdict on Fable while Fable's weekly window is held"
                     % ", ".join(str(identifier) for identifier in waiting))
        self._said_waiting = waiting

    def _verdicts_on_fable(self, entry):
        """Whether any verdict a done ticket earned runs on Fable: its verifier's tier for the author names Fable."""
        return any(gates.verifies_on_fable(self.policy, ask.author_model) for ask in entry.asks)

    def _gate(self, entry, result, fall_back):
        """One done ticket's verdicts, in order; every one of them has to pass before it is accepted.

        `fall_back` is this wave's answer for a verdict on Fable (`_drain_verdicts`), handed to the gate so
        that it never reads the consent apart from the wave: true takes it on Opus at the table's effort.
        """
        for index, ask in enumerate(entry.asks):
            if index:
                # A refusal an earlier verdict of this ticket carried may have paused the run or begun the hold since.
                on_fable = gates.verifies_on_fable(self.policy, ask.author_model) and self._fable_held()
                if self._holds_launches() or self.action != schedule.NORMAL or (on_fable and not self._falls_back()):
                    self.verdicts.append(_Queued(entry.ticket, entry.attempt, entry.asks[index:]))
                    if on_fable and not self._holds_launches() and self.action == schedule.NORMAL:
                        self._held_back("the verdicts on ticket %d" % entry.ticket)
                    return
                fall_back = fall_back or on_fable
            try:
                verdict = gates.verdict_for(ask, project=self.project, harness_root=self.harness_root,
                                            policy=self.policy, ledger=self.ledger, fall_back=fall_back)
            except gates.FableHeld:
                # The hold on Fable's weekly window waits under the consent: nothing was launched, and the rest stays queued.
                self.verdicts.append(_Queued(entry.ticket, entry.attempt, entry.asks[index:]))
                self._held_back("the verdicts on ticket %d" % entry.ticket)
                self.say("  ticket %d: its %s verdict waits for Fable's weekly window" % (entry.ticket, ask.verdict_type))
                return
            except gates.UsageLimited as refused:
                # A closed window, not a verdict: what is left of the ticket's verdicts stays queued, to be launched again.
                self._pause(refused.limit, "ticket %d's %s verdict" % (entry.ticket, ask.verdict_type))
                self.verdicts.append(_Queued(entry.ticket, entry.attempt, entry.asks[index:]))
                self.say("  ticket %d: the usage limit refused its %s verdict; it stays queued and is launched again, never resumed"
                         % (entry.ticket, ask.verdict_type))
                return
            except (ValueError, OSError) as failure:
                # A verdict nobody could take is not a verdict against the ticket. It keeps the
                # `done` its machine gates earned and is not accepted, which is what `wayline
                # status` shows and what holds any dependent of a difficulty-5 ticket.
                self.say("  ticket %d: the %s verdict could not be taken (%s); the ticket stays "
                         "done and unaccepted" % (entry.ticket, ask.verdict_type, failure))
                return
            self.say("  ticket %d: the %s verdict %s on %s (session %s)%s"
                     % (entry.ticket, ask.verdict_type, "passed" if verdict.passed else "failed",
                        verdict.model or "an unnamed model", verdict.session_id or "unknown",
                        ", falling back from %s" % verdict.fallback_from if verdict.fallback_from else ""))
            self._heard_verdict(verdict, "ticket %d's %s verdict" % (entry.ticket, ask.verdict_type))
            self._admit_verdict_proposals(entry.ticket, ask, verdict)
            if not verdict.passed:
                self._reject(entry, verdict)
                result.rejected.append(entry.ticket)
                return
        self._accept_ticket(entry, verdict)
        result.accepted.append(entry.ticket)

    def _heard_verdict(self, verdict, source):
        """Fold the `rate_limit_event`s a verdict's sessions wrote into the readings, as `_observe` folds a worker's.

        The verdict answered, so it stands; a rejected event among them pauses the run, or on Fable's weekly
        window begins the hold (decision 15: a refusal can ride a session that still returned its answer).
        """
        events = list(getattr(verdict, "rate_limit_events", None) or [])
        if not events:
            return
        now = self.clock()
        for event in events:
            self.windows.observe(event, now, pacing.WINDOWS if self.view.hold is not None else pacing.READINGS)
            limit = pacing.rejected(event)
            if limit is not None:
                self._pause(limit, source)
        self._pace()

    def _admit_verdict_proposals(self, ticket, ask, verdict):
        """Admission on the critic's and the verifier's `proposals` (ticket 37), the same rules as a worker's result's.

        `proposed_by` is `verifier` for both roles the schema names it: the critic's depth spot-check
        is a Type-B verdict like the verifier's own, and the ticket schema names one author for both.
        """
        if not verdict.proposals:
            return
        try:
            outcomes = proposals.admit_proposals(
                self.project, verdict.proposals, origin_ticket=ticket,
                origin_prefix="ticket %d's %s verdict" % (ticket, ask.verdict_type), proposed_by="verifier",
                policy=self.policy, harness_root=self.harness_root, wave_cap=self._proposal_cap, notify=self.notify)
        except (ValueError, OSError) as failure:
            self.say("  ticket %d's %s verdict proposed ticket(s) that could not be admitted: %s" % (ticket, ask.verdict_type, failure))
            return
        for outcome in outcomes:
            if outcome["outcome"] == "admitted":
                self.say("  ticket %d's %s verdict proposed a ticket: admitted as ticket %d" % (ticket, ask.verdict_type, outcome["ticket"]))
            else:
                self.say("  ticket %d's %s verdict proposed a ticket: parked (%s)" % (ticket, ask.verdict_type, outcome["reason"]))

    def _accept_ticket(self, entry, verdict):
        """`done` to `accepted`: the one transition a passing quality verdict makes (decision 2)."""
        self._set_status(entry.ticket, "accepted", self._verdict_note(verdict))
        self.ledger.append_event(TICKET_ACCEPTED, {"ticket": entry.ticket}, ticket=entry.ticket)
        self.say("  ticket %d accepted" % entry.ticket)

    def _reject(self, entry, verdict):
        """A failed verdict: the ticket is failed with the findings as its failure output."""
        reason = REJECTED % (verdict.verdict_type, verdict.model or "verifier",
                             gates.findings_text(verdict.findings))
        self._climb(entry.ticket, entry.attempt, self._step_for(entry.ticket), reason, self._verdict_note(verdict),
                    session_id=verdict.session_id, said="failed its %s verdict" % verdict.verdict_type)

    def _verdict_note(self, verdict):
        """What a verdict has to say in the ticket file: who read it, on what, and what they found.

        The journal carries the same thing, but the ticket file is where a person looks and where
        the next attempt's prompt comes from, so a verdict that reached only the journal would
        have reached neither.
        """
        lines = ["**Verdict (%s): %s** by %s%s, session `%s`."
                 % (verdict.verdict_type, "passed" if verdict.passed else "failed",
                    verdict.model or "an unnamed model",
                    " in place of %s, whose weekly window was spent" % verdict.fallback_from if verdict.fallback_from else "",
                    verdict.session_id or "unknown")]
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
        """The step of the escalation chain this failure lands on: the one resume while it is unspent, else what is after it."""
        if not attempt.resumed and attempt.session_id and self._ladder()["resume"]:
            return RESUME
        return self._step_from(attempt.id)

    def _fail(self, attempt, reason, next_step):
        """Journal the failure and leave the worktree and the branch for the attempt that follows.

        A failure whose step is `needs_human` hands the ticket to a person at once (`_after_failure`).
        """
        self.ledger.append_event(TICKET_FAILED, {
            "ticket": attempt.id, "attempt": attempt.number, "reason": reason, "next": next_step,
        }, ticket=attempt.id, session_id=attempt.session_id)
        self._write_ticket(attempt, "failed", attempt.result)
        self.say("  ticket %d failed: %s (next: %s)" % (attempt.id, reason, next_step))
        self._after_failure(attempt.id, next_step, reason)
        if next_step == NEEDS_HUMAN:
            attempt.ticket = dict(attempt.ticket, status="needs_human")

    def _needs_human(self, attempt, question):
        self.ledger.append_event(TICKET_NEEDS_HUMAN, {"ticket": attempt.id, "question": question},
                                 ticket=attempt.id)
        self._write_ticket(attempt, "needs_human", attempt.result)
        self.say("  ticket %d needs a person: %s" % (attempt.id, question))
        self._tell_owner(attempt.id, question)

    # --- the escalation chain and the difficulty adjustment (decision 5; ticket 38; by rung, decision 16) ---

    def _ladder(self):
        """`policy.escalation`, over the defaults of decision 14."""
        ladder = dict(LADDER)
        ladder.update(self.policy.get("escalation") or {})
        return ladder

    def _max_tier(self):
        """The highest difficulty `policy.difficulty` names: no tier up and no raise goes past it."""
        tiers = [int(key) for key in (self.policy.get("difficulty") or {}) if str(key).isdigit()]
        return max(tiers, default=tickets.HARDEST)

    def _effective_difficulty(self, fields):
        """The difficulty level the ticket's next attempt launches at.

        A `pinned_difficulty` wins, whatever the run raised. Otherwise the ticket's own difficulty, moved up by
        every raise the run journaled for its kind (`difficulty_raised` from that level); never past the top level.
        A tier up no longer moves the level (decision 16): it counts rungs, and `_effective_rung` is where it lands.
        """
        pinned = fields.get("pinned_difficulty")
        if pinned is not None:
            return pinned
        difficulty, raised, seen = fields["difficulty"], self.view.raised.get(fields["kind"]) or {}, set()
        while difficulty in raised and difficulty not in seen:
            seen.add(difficulty)
            difficulty = raised[difficulty]
        return min(difficulty, self._max_tier())

    # --- the rung the next attempt launches on (decision 16; ticket 61) ---

    def _top_rung(self):
        """The highest rung the rung ladder has: no tier up climbs past it."""
        return len(ladder(self.policy))

    def _effective_rung(self, fields):
        """The rung of the rung ladder the ticket's next attempt launches on.

        The level's own rung (`policy.difficulty` over `_effective_difficulty`, so a pin and a kind raise both
        count), lifted to the rung floor every tier up the chain took left behind: one rung above the rung the
        attempt it sent up ran on. A raise and a tier up do not add, they take the higher of the two. A journal
        written before the rung ladder carries no `rung` on its launches, so its floor is counted by tier ups
        from the level's rung instead. Never past the ladder's top rung.
        """
        rung = rung_of(self.policy, self._effective_difficulty(fields))
        known = self.view.tickets.get(fields["id"])
        if known is not None and known.taken(TIER_UP):
            floor = known.rung_floor if known.rung_floor is not None else rung + known.taken(TIER_UP)
            rung = max(rung, floor)
        return min(rung, self._top_rung())

    def _ran_on(self, identifier):
        """The rung the ticket's latest attempt ran on, or None when no journal records one."""
        known = self.view.tickets.get(identifier)
        latest = known.latest if known is not None else None
        return latest.rung if latest is not None else None

    def _next_rung(self, identifier):
        """The rung a tier up would launch the ticket's next attempt on, or None when there is none above it.

        One rung above the rung the attempt that failed ran on, and never below the rung the ticket would
        launch on anyway: a kind raise journaled since may already have lifted it that far, and then the
        tier up lands where the raise put it rather than a rung past it. A journal older than the rung
        ladder records no rung, so the rung the next attempt would launch on stands in for it.
        """
        fields = self._fields(identifier)
        if fields is None:
            return None
        rung, ran = self._effective_rung(fields), self._ran_on(identifier)
        rung = max(rung, ran + 1) if ran is not None else rung + 1
        return rung if rung <= self._top_rung() else None

    def _at_top_rung(self, identifier):
        """Whether the chain left this ticket with nowhere to climb: it has a ticket file, and no rung above it.

        A ticket whose file is gone has no rung at all, and is handed over without a reason rather than
        reported as one the ladder ran out on.
        """
        return self._fields(identifier) is not None and self._next_rung(identifier) is None

    def _rung_family(self, rung):
        """The model family of a rung of the rung ladder, or None for a rung the ladder does not have."""
        rungs = ladder(self.policy)
        if not isinstance(rung, int) or isinstance(rung, bool) or not 1 <= rung <= len(rungs):
            return None
        entry = rungs[rung - 1]
        return pacing.family(entry.get("model")) if isinstance(entry, dict) else None

    def _tier_up_reaches_fable(self, identifier):
        """Whether a tier up would take this ticket onto Fable from a rung that is not.

        Rung 5 to rung 6 on the v1.0.0 rung ladder. Read by family, so only a project's own Fable
        rungs make it true: on the shipped rung ladder a tier up stays on Opus up to the top rung
        (ticket 70). That is the one step the split comes before (decision 16): Fable's weekly window
        is the scarce resource, so the cheaper remedy is tried first, and the ticket climbs onto Fable
        only after it. The family compared against is the one the attempt that failed ran on, not the
        one the rung below the tier up's happens to be: a kind raise can lift the target two rungs
        above the attempt, and the climb onto Fable is still a climb onto Fable.
        """
        above = self._next_rung(identifier)
        if above is None or self._rung_family(above) != pacing.FABLE:
            return False
        ran = self._ran_on(identifier)
        return self._rung_family(ran if ran is not None else above - 1) != pacing.FABLE

    def _fields(self, identifier):
        """The ticket's frontmatter, or None when no ticket file has that id."""
        return next((fields for fields in tickets.read_tickets(self.project) if fields["id"] == identifier), None)

    def _step_order(self, identifier):
        """The escalation steps after the resume, in the order this ticket takes them (decision 16).

        `policy.escalation.then` gives the order while the tier up stays inside the failed attempt's own model
        family: the tier up first, since one rung up is the cheaper remedy. When the tier up would take the
        ticket onto Fable and the failed attempt was not there, the split comes first, so the scarce Fable week
        is spent only after the planner has had its try.
        """
        order = [step for step in self._ladder()["then"] if step in (SPLIT, TIER_UP)]
        if SPLIT in order and TIER_UP in order and self._tier_up_reaches_fable(identifier):
            order = sorted(order, key=lambda step: 0 if step == SPLIT else 1)
        return order

    def _step_from(self, identifier, start=None):
        """The first step after the resume this ticket can still take, in `_step_order` order, from `start` on.

        A split is taken once, and never for a decision ticket, which is answered, nor for a ticket a split cut, so
        splits do not recurse, nor for the harness ticket of a change record, which the record owns as no cut of the
        graph takes it back (`plan.superseded_by`). A tier up is taken `policy.escalation.tier_up` times at most, and never for a pinned
        ticket or one already on the ladder's top rung, which has nowhere to climb (decision 16). A step already
        taken counts as spent, so a step that could not be taken sends the ticket on to the next. `start` is where a
        failure that names its own step begins (an integration that conflicted starts at the split); `needs_human`
        is what is left.
        """
        self._tail()  # what this wave journaled about the ticket so far counts
        ladder, known, fields = self._ladder(), self.view.tickets.get(identifier), self._fields(identifier)
        if fields is None:
            return NEEDS_HUMAN
        taken = known.taken if known is not None else (lambda name: 0)
        order = self._step_order(identifier)
        if start in order:
            # `start` is where this failure begins, not a cut: an integration that conflicted begins at the
            # split, and still goes on to the tier up when the split is spent, whichever order the two are in.
            order = [start] + [step for step in order if step != start]
        for step in order:
            if step == SPLIT and not taken(SPLIT) and fields["kind"] != tickets.DECISION and not self._cut_by_split(identifier) \
                    and self._change_record(identifier, fields) is None:
                return SPLIT
            if step == TIER_UP and taken(TIER_UP) < ladder["tier_up"] and fields.get("pinned_difficulty") is None \
                    and self._next_rung(identifier) is not None:
                return TIER_UP
        return NEEDS_HUMAN

    def _cut_by_split(self, identifier):
        """Whether a split cut this ticket, as the note its body carries says."""
        from wayline import plan  # the plan module pulls in the registry and the planner's session
        try:
            _, body = self._ticket(identifier)
        except ConductorError:
            return False
        return plan.split_from(body) is not None

    def _step_for(self, identifier):
        """The step of a failure met outside the attempt's own session (a job, a verdict): as `_next_step`, from the journal."""
        self._tail()  # the session this wave journaled for the attempt is the one to resume
        known = self.view.tickets.get(identifier)
        latest = known.latest if known is not None else None
        if latest is not None and latest.session_id and not latest.spent and self._ladder()["resume"]:
            return RESUME
        return self._step_from(identifier)

    def _climb(self, identifier, number, step, reason, note=(), session_id=None, said="failed"):
        """Journal `ticket_failed` with `step` for a ticket no attempt object is carrying, and act on it as `_fail` does."""
        self.ledger.append_event(TICKET_FAILED, {"ticket": identifier, "attempt": number, "reason": reason, "next": step},
                                 ticket=identifier, session_id=session_id)
        self._set_status(identifier, "failed", list(note))
        self.say("  ticket %d %s: %s (next: %s)" % (identifier, said, reason.split("\n")[0], step))
        self._after_failure(identifier, step, reason)

    def _after_failure(self, identifier, step, reason):
        """What every failure does once journaled: the difficulty adjustment, and a person told when the chain is spent.

        A ticket the chain leaves on the ladder's top rung, with nowhere to climb, is handed over with
        `reason: top_rung`, which `status`, the dashboard, and `REPORT.md` read as "at the ladder's top
        rung" (decision 16).
        """
        self._tail()
        self._adjust_difficulty(identifier)
        if step != NEEDS_HUMAN:
            return
        top = self._at_top_rung(identifier)
        question = "it failed%s and no step of the escalation chain is left: %s" % (
            " on rung %d, the rung ladder's top rung" % self._top_rung() if top else "", reason)
        payload = {"ticket": identifier, "question": question}
        if top:
            payload["reason"] = TOP_RUNG
        self.ledger.append_event(TICKET_NEEDS_HUMAN, payload, ticket=identifier)
        self._set_status(identifier, "needs_human")
        self._tail()
        self.say("  ticket %d needs a person: its escalation chain is spent%s"
                 % (identifier, " and it is %s" % TOP_RUNG_NOTE if top else ""))
        self._tell_owner(identifier, question)

    def _tell_owner(self, identifier, question):
        """The notification of a ticket that needs a person (decision 7), claimed by this run so the tick does not send it again."""
        self.notify(TICKET_NEEDS_HUMAN, "%s: ticket %d needs a human: %s" % (self.project.name, identifier, question.split("\n")[0]),
                    self.project, identifier)

    def _adjust_difficulty(self, identifier):
        """Raise the ticket's kind one tier for the rest of the run once its attempts failed `raise_after_failures` times at a tier.

        The failures counted are the run's failed attempts (`View.failures`: an attempt that fell back to Opus is never
        among them, decision 15) of unpinned tickets of the same kind at the tier the failed attempt launched at. A kind
        is raised from a tier once; a pinned ticket neither counts nor is raised.
        """
        found = {fields["id"]: fields for fields in tickets.read_tickets(self.project)}
        fields, known = found.get(identifier), self.view.tickets.get(identifier)
        if fields is None or fields.get("pinned_difficulty") is not None or known is None or known.latest is None:
            return
        tier = self.view.failures.get((identifier, known.latest.number))
        kind = fields["kind"]
        if tier is None or tier >= self._max_tier() or tier in (self.view.raised.get(kind) or {}):
            return
        if not self._ran_at_its_level(identifier, known.latest.number):
            return
        failed = [key for key, difficulty in self.view.failures.items()
                  if difficulty == tier and (found.get(key[0]) or {}).get("kind") == kind
                  and (found.get(key[0]) or {}).get("pinned_difficulty") is None
                  and self._ran_at_its_level(*key)]
        if len(failed) < self._ladder()["raise_after_failures"]:
            return
        self.ledger.append_event(DIFFICULTY_RAISED, {"kind": kind, "from": tier, "to": tier + 1})
        self._tail()
        self.say("  %d %s attempt(s) failed at difficulty %d (%s); %s tickets at difficulty %d launch at %d for the rest of the run"
                 % (len(failed), kind, tier, ", ".join("ticket %d attempt %d" % key for key in sorted(failed)), kind, tier, tier + 1))

    def _ran_at_its_level(self, identifier, number):
        """Whether this failed attempt counts toward its kind's raise: it ran on the rung its level names.

        An attempt the escalation chain lifted a rung did not run at what its difficulty level says, so
        counting it would raise a whole kind off one ticket's own climb (decision 16). It is left out for
        the reason a fallback attempt is (decision 15): the level names one rung, and the attempt ran on
        another. A journal older than the rung ladder records no rung, and counts as it always did.
        """
        known = self.view.tickets.get(identifier)
        attempt = known.attempts.get(number) if known is not None else None
        if attempt is None or attempt.rung is None or attempt.difficulty is None:
            return True
        try:
            return attempt.rung == rung_of(self.policy, attempt.difficulty)
        except ConductorError:
            return True  # a policy with no rung for the level: the launch fails on it, and says so there

    def _owed_steps(self):
        """The failed tickets that wait on a step a wave takes (`resume`, `tier_up`, `split`), by id."""
        found = {fields["id"]: fields for fields in tickets.read_tickets(self.project)}
        return [identifier for identifier, known in sorted(self.view.tickets.items())
                if known.step in (RESUME, TIER_UP, SPLIT) and identifier not in self.flight
                and (found.get(identifier) or {}).get("status") == "failed"]

    def _escalate(self, result):
        """Take every failed ticket up the step its last `ticket_failed` names; model work, so only while launches are allowed.

        A step that sends the ticket on to another (a split that fails goes to the tier up) is followed in the same
        wave, so the tier up it lands on launches now rather than a wave later. Each step is looked at once a wave
        per ticket, and every step is taken a bounded number of times, so the pass ends.
        """
        seen = set()
        while True:
            owed = [(identifier, self.view.tickets[identifier].step) for identifier in self._owed_steps()]
            owed = [item for item in owed if item not in seen]
            if not owed or self._holds_launches():
                return
            for item in owed:
                seen.add(item)
                self._take_step(item[0], result)

    def _take_step(self, identifier, result):
        """One failed ticket taken up its escalation step, unless pacing holds it."""
        if self._holds_launches():
            return
        step = self.view.tickets[identifier].step
        if step == SPLIT and self.action != schedule.NORMAL:
            return  # the planner's session is never cheap, so `cheap_only` holds it as it holds a verdict
        try:
            if step == RESUME:
                took = self._resume_failed(identifier)
            elif step == TIER_UP:
                took = self._tier_up(identifier)
            else:
                took = self._split(identifier)
        except (ValueError, OSError) as failure:  # a role, a prompt, a settings file, or a git step
            self.flight.pop(identifier, None)
            after = self._step_from(identifier)  # the step that could not be taken counts as taken
            self._climb(identifier, self.view.tickets[identifier].attempt, after,
                        "the %s step could not be taken: %s" % (step, failure))
            took = True
        if took:
            result.escalated.append((identifier, step))

    def _resume_failed(self, identifier):
        """The `resume` step: the failed attempt's session, resumed once with the failure output; whether it was taken.

        A failure met after the session returned (a job, a verdict, the integration) is given to that session, in the
        worktree it wrote, made again from the ticket branch or from `main` when the integration removed it. An attempt
        with no session to resume, or whose resume is spent, goes to the next step instead. The resume waits, like any
        on Fable, while the hold stands and the consent waits; under fallback a fresh Opus session takes it.
        """
        known = self.view.tickets[identifier]
        latest = known.latest
        if self._busy() >= self._slots() or schedule.holds_model_work(self.action):
            return False  # a resume is a worker like any launch: it waits for a slot, and for the pacing to allow a session
        # A resume is the attempt's own session again, on the model it was launched on: pacing steps a
        # launch down a rung (decision 16), never a session already under way.
        if latest is None or not latest.session_id or latest.spent:
            self._climb(identifier, known.attempt, self._step_from(identifier),
                        "%s; its session cannot be resumed" % (known.failure or "it failed"))
            return True
        ticket, body = self._ticket(identifier)
        attempt = _Attempt(ticket, body, latest.number, self._worktree(identifier))
        attempt.role = worker.read_role(ticket["role"], self.harness_root, self.project)
        attempt.difficulty = latest.difficulty if latest.difficulty is not None else self._effective_difficulty(ticket)
        attempt.tier = self._tier_ran(latest.rung, attempt.difficulty, ticket.get("budget"))
        if latest.fallback_from:
            attempt.tier, attempt.fallback_from = fallback_tier(self.policy, attempt.tier), latest.fallback_from
        attempt.session_id, attempt.session_journaled = latest.session_id, True
        attempt.started = True
        self._prepare(attempt, self._fallback_notes(attempt) if latest.fallback_from else ())
        if self._held_on_fable(attempt.request) and not self._falls_back():
            self._held_back("ticket %d's resume" % identifier)
            return False
        message = RESUME_FAILED % (known.failure or "no reason was recorded", tickets.relative_path(ticket))
        self._write_ticket(attempt, "running")
        attempt.want = _Want(ACCEPTANCE_FAILED, message)
        self.flight[identifier] = attempt
        started = self._start_wanted(attempt)
        if started is True:
            self.say("  ticket %d: resuming session %s once with the failure output (escalation: resume)" % (identifier, latest.session_id))
        return bool(started)

    def _tier_up(self, identifier):
        """The `tier_up` step: the ticket is opened again, and its next attempt launches one rung up in a new session.

        The rung is the one `_effective_rung` reads back from the journal's floor, so the launch itself needs
        nothing from here: it reads the same rung, and a Fable rung the hold is holding falls back, waits, or
        asks there as the fallback consent says (decision 15), like any other launch on Fable.
        """
        fields = self._fields(identifier)
        rung = self._effective_rung(fields)
        tier = rung_tier(self.policy, rung, fields.get("budget"))
        self._set_status(identifier, "open", ["Escalated one rung up: the next attempt launches on rung %d (%s), "
                                              "in a new session." % (rung, tier.label)])
        self.say("  ticket %d: escalation: its next attempt launches one rung up, on rung %d (%s)"
                 % (identifier, rung, tier.label))
        return True

    def _planner_falls_back(self, what):
        """Whether the planner may launch now, and on what: `(may, fall_back)`; it waits when it is on Fable, held, and the consent waits."""
        from wayline import specify  # the specify module pulls in the gates and the planner's session
        if specify.planner_tier(self.policy)[0] != pacing.FABLE or not self._fable_held():
            return True, False
        if self._falls_back():
            return True, True
        self._held_back(what)
        return False, False

    def _cut(self, cut, fall_back):
        """The planner's cut of the graph, what `wayline plan --split` and `--replan` run (ticket 34); returns what was written."""
        from wayline import plan  # the plan module pulls in the registry and the planner's session
        return plan.cut_graph(self.project, cut, harness_root=self.harness_root, policy=self.policy, fall_back=fall_back,
                              notify=self.notify, say=lambda text: self.say("  " + text), pre_check=self.plan_pre_check)

    def _launch_cut(self, cut, what):
        """One cut of the graph under the wave's rules: what was written, None when it waits, or the failure it met."""
        may, fall_back = self._planner_falls_back(what)
        if not may:
            return None
        try:
            return self.planner(cut, fall_back)
        except gates.FableHeld:
            self._held_back(what)
            return None
        except gates.UsageLimited as refused:
            self._pause(refused.limit, what)
            self.say("  %s: the usage limit refused it; it is launched again once the window allows" % what)
            return None
        except (ValueError, OSError) as failure:
            return failure

    def _split(self, identifier):
        """The `split` step: the planner replaces the ticket with smaller ones, which parks it; a split that fails needs a person."""
        from wayline import plan
        outcome = self._launch_cut(plan.Cut("split", of=identifier), "the planner's split of ticket %d" % identifier)
        if outcome is None:
            return False
        self._tail()
        if isinstance(outcome, BaseException):
            known = self.view.tickets[identifier]
            self._climb(identifier, known.attempt, self._step_from(identifier), "the planner could not split it: %s" % outcome)
            return True
        self.say("  ticket %d: escalation: split by the planner into ticket(s) %s; it is parked"
                 % (identifier, ", ".join(str(item) for item in outcome.get("tickets") or []) or "none"))
        return True

    # --- the stall (decision 5; ticket 38) ---

    def _stall_waves(self):
        waves = (self.policy.get("stall") or {}).get("waves", STALL_WAVES)
        if isinstance(waves, bool) or not isinstance(waves, int) or waves < 1:
            raise ConductorError("policy.stall.waves is %r; it is a whole number of waves, at least 1" % (waves,))
        return waves

    def _radius(self):
        try:
            return read_harness(self.project).get("radius")
        except (ProjectError, ValueError, OSError):
            return None

    def _check_stall(self, result):
        """Wave step 10: at `policy.stall.waves` settling waves without progress, journal `stall` and act on it.

        The counter is the replayed journal's (`View.stall`), which the `wave` event this wave journaled has moved.
        Under radius `strict` the run ends with `stall_strict` and `REPORT.md` is rendered; otherwise the planner
        re-cuts the open tickets (`_replan`), at this wave's end or as soon as the run may launch model work.
        """
        if not result.outcomes or result.ended:
            return
        self._tail()
        waves = self._stall_waves()
        if self.view.stall < waves:
            return
        strict = self._radius() == "strict"
        self.ledger.append_event(STALL, {"waves": self.view.stall, "action": STOP if strict else REPLAN})
        self._tail()
        result.stalled = True
        if not strict:
            self.say("  the run stalled: %d settling wave(s) without a closed ticket, a finding, or goal progress; the planner re-cuts "
                     "the open tickets" % waves)
            if not self._holds_launches():
                self._replan(result)
            return
        self.ledger.append_event(RUN_ENDED, {"reason": STALL_STRICT})
        result.ended, result.reason = True, STALL_STRICT
        words = ("the run stalled: %d settling wave(s) without a closed ticket, a finding, or goal progress, and the radius is "
                 "strict, so it stopped" % waves)
        self.say("  " + words)
        self.reporter()  # the end notice follows the wave (`_end_notice`)

    def _stops_at_stall(self, result):
        """Whether this wave ends the run on a strict stall: then it launches nothing, since nothing would carry what it started."""
        if not result.outcomes or result.done or result.findings or result.jobs_finished or result.kept:
            return False
        return self.view.stall + 1 >= self._stall_waves() and self._radius() == "strict"

    def _render_report(self):
        """P7 at a strict stall: `REPORT.md` rendered from the ledger, offline when the classifier cannot run; never raises."""
        from wayline import provenance  # the provenance module pulls in the gates and the report
        for offline in (False, True):
            try:
                rendered = provenance.render_report(self.project, harness_root=self.harness_root, policy=self.policy, offline=offline)
            except (ValueError, OSError) as failure:
                self.say("  REPORT.md could not be rendered%s: %s" % (" offline" if offline else "", failure))
                continue
            self.say("  rendered %s (linter %s)" % (rendered.path, "passed" if rendered.lint.passed else "failed"))
            return rendered
        return None

    def _owed_replan(self):
        """The time of the stall whose replan is still owed, or None: none was asked, this run took it, or a re-cut was written since."""
        stalled = self.view.replan_at
        if stalled is None or stalled == self._replanned:
            return None
        from wayline import plan
        record = plan.read_plan(self.project) or {}
        if record.get("cut") == "replan" and str(record.get("cut_at") or "") >= stalled:
            return None
        return stalled

    def _replan(self, result):
        """The stall's replan: the planner re-cuts every open or blocked ticket from what the journal says failed."""
        stalled = self._owed_replan()
        if stalled is None or self._holds_launches() or self.action != schedule.NORMAL:
            return
        from wayline import plan
        outcome = self._launch_cut(plan.Cut("replan"), "the planner's replan after the stall")
        if outcome is None:
            return
        self._replanned = stalled
        self._tail()
        if isinstance(outcome, BaseException):
            self.say("  the planner could not re-cut the graph after the stall: %s" % outcome)
            return
        result.escalated.append((None, REPLAN))
        self.say("  the planner re-cut the graph after the stall: ticket(s) %s written, %s parked%s" % (
            ", ".join(str(item) for item in outcome.get("tickets") or []) or "none",
            ", ".join(str(item) for item in outcome.get("superseded") or []) or "none",
            "; decision ticket %d asks to confirm it" % outcome["gate"] if outcome.get("gate") else ""))

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

    # --- the evolve loop (decision 12; ticket 45) ---

    def _policy_files(self):
        """`(st_mtime_ns, st_size)` of `harness.json` and the harness's `policy.json`: what says the policy may have changed."""
        stamp = []
        for path in (self.project / "harness.json", self.harness_root / "policy.json"):
            try:
                found = path.stat()
                stamp.append((found.st_mtime_ns, found.st_size))
            except OSError:
                stamp.append(None)
        return stamp

    def _reread_policy(self):
        """Read the policy again when `harness.json` changed, so a local change is used from this wave (decision 12).

        A policy a caller handed in or assigned stands. One the schema or the ladder refuses is said once and the policy
        the run already had stands, because a wave must not die on an override a harness ticket just wrote.
        """
        if self._policy_given:
            return
        stamp = self._policy_files()
        if stamp == self._policy_stamp:
            return
        self._policy_stamp = stamp
        try:
            policy = policy_for(self.project, self.harness_root)
            check_policy(policy, name="the policy of %s (policy.json under harness.json)" % self.project)
        except (ValidationError, ValueError, OSError) as failure:
            if str(failure) != self._policy_trouble:
                self._policy_trouble = str(failure)
                self.say("  harness.json changed, and the policy it gives is refused, so the one this run had stands: %s" % failure)
            return
        self._policy_trouble = None
        self._policy = policy
        self.say("  harness.json changed; this wave runs under the policy it gives")

    def _run_evolver(self, fall_back):
        """The evolver's session over the pending feedback, what `wayline evolve` runs; returns its report."""
        from wayline import changes  # the evolve loop pulls in the registry, the fixtures, and the session helpers
        return changes.evolve(self.project, harness_root=self.harness_root, policy=self.policy, fall_back=fall_back,
                              notify=self.notify, say=lambda text: self.say("  " + text), pre_check=self.plan_pre_check)

    def _evolve(self, result):
        """Launch the evolver when feedback is pending, so a local change is filed now and used from the next wave.

        It is a max-effort session like the decider's: `cheap_only` holds it, the hold on Fable's weekly window holds
        it or sends it to Opus as the fallback consent says, and a usage window that refuses it pauses the run. A list
        the evolver got wrong twice is marked read by `changes.evolve`, so it is said here and not launched again.
        """
        from wayline import changes
        # The journal this wave already folded names the items; a file the owner dropped since is found by one scan of
        # `research/feedback/`, and only then is the journal read again.
        journaled = {item["id"]: item["source"] for item in self.view.feedback}
        if not changes.pending_feedback(self.project, journaled=journaled):
            return
        what = "the evolver's session"
        if self.action != schedule.NORMAL:
            return
        fall_back = False
        if changes.evolves_on_fable(self.policy) and self._fable_held():
            if not self._falls_back():
                self._held_back(what)
                return
            fall_back = True
        try:
            report = self.evolver(fall_back)
        except gates.FableHeld:
            self._held_back(what)
            return
        except gates.UsageLimited as refused:
            self._pause(refused.limit, what)
            self.say("  %s: the usage limit refused it; it is launched again once the window allows" % what)
            return
        except (ValueError, OSError) as failure:
            self.say("  %s failed, and the feedback it read waits for the owner: %s" % (what, failure))
            return
        self._tail()
        for line in changes.render_report(report).splitlines():
            self.say("  " + line)

    def _change_record(self, identifier, ticket=None):
        """The change record harness ticket `identifier` was filed for, read now; None for any other ticket."""
        if self._changes.get(identifier, True) is None:
            return None
        if ticket is None:
            try:
                ticket, _ = self._ticket(identifier)
            except ConductorError:
                return None
        if ticket.get("kind") != "harness" or not str(ticket.get("origin") or "").startswith("change "):
            self._changes[identifier] = None
            return None
        from wayline import changes
        record = changes.read_change(self.project, changes.change_of(ticket))
        self._changes[identifier] = None if record is None else record["id"]
        return record

    def _global_change(self, identifier):
        """The record of the global change ticket `identifier` works on, whose worktree is one of the harness repository's."""
        record = self._change_record(identifier)
        return record if record is not None and record["scope_kind"] == "global" else None

    def _prove(self, attempt, record):
        """The fixture run on the old subject, where it fails, and on the change, where it passes: True, `failed`, or `session`.

        The old subject of a local change is the project's `main`, the directory itself; that of a global change is
        the commit its branch left the harness `main` at, checked out for the length of the proof. A proven change's
        baseline is committed on the branch, so the registry finds a model-authored skill's fixture passed.
        """
        from wayline import changes
        proven = record.get("proof") or {}
        if proven.get("head") and proven["head"] == self._head(attempt.worktree):
            return True  # proven already, and the branch has not moved: an integration carried again is not proven again
        # The old subject of a local override or a new skill stands in from this conductor's own harness.
        prover = self.prover or functools.partial(changes.prove, harness_root=self.harness_root)
        holder = old = None
        try:
            if record["scope_kind"] == "global":
                holder = tempfile.mkdtemp(prefix="wayline-old-subject-")
                old = changes.old_subject(self.harness_root, record, holder)
            proof = prover(record["fixture"], old or self.project, attempt.worktree, self.policy)
        except (ValueError, OSError) as failure:
            self._fail(attempt, "the fixture %s could not be run: %s" % (record["fixture"], failure), self._next_step(attempt))
            return "failed"
        finally:
            if old is not None:
                changes.drop_old_subject(self.harness_root, old)
            if holder is not None:
                shutil.rmtree(holder, ignore_errors=True)
        if proof.waits:
            attempt.integrating, attempt.want = True, _Want(INTEGRATE)
            self.say("  ticket %d: the run of fixture %s stopped for cost before it could say; it is carried again" % (attempt.id, record["fixture"]))
            return "session"
        if proof.problem is not None:
            self._fail(attempt, proof.problem, self._next_step(attempt))
            return "failed"
        head = changes.commit_all(attempt.worktree, "ticket %d: the baseline of fixture %s" % (attempt.id, record["fixture"]))
        changes.set_status(self.project, record["id"], record["status"], proof={"old": proof.old or "", "new": proof.new or "", "head": head})
        self.say("  ticket %d: fixture %s fails on the old subject and passes on the change" % (attempt.id, record["fixture"]))
        return True

    def _finish_global(self, attempt, record):
        """A global change is never integrated here: its branch is checked and waits for the owner (decision 12).

        The harness tests and the full fixture suite run on `evolve/<id>`. A failure fails the attempt like a failed
        acceptance; a pass closes the ticket as done, leaves the branch and its worktree for the owner to read and
        merge, and marks the record `awaiting_owner`, which `wayline evolve` tags once the harness `main` holds it.
        """
        from wayline import changes
        try:
            commit, checks = changes.check_global(self.project, record, self.global_checks)
        except (ValueError, OSError) as failure:
            self._fail(attempt, "the branch %s could not be checked: %s" % (record["branch"], failure), self._next_step(attempt))
            return "failed"
        stored = [dict(item, tail=item.get("tail") or "") for item in checks]
        failed = [item for item in checks if item["exit_code"] != 0]
        if failed:
            changes.set_status(self.project, record["id"], record["status"], commit=commit, checks=stored)
            self._fail(attempt, "on %s, %s failed (exit %d): %s" % (record["branch"], failed[0]["name"], failed[0]["exit_code"],
                                                                  " | ".join((failed[0].get("tail") or "").splitlines()[-3:])),
                       self._next_step(attempt))
            return "failed"
        changes.set_status(self.project, record["id"], "awaiting_owner", commit=commit, checks=stored)
        self._close(attempt, waits_for_owner="The harness tests and the full fixture suite pass on `%s` at %s, in %s. It waits for the "
                    "owner to merge it into the harness main; `wayline evolve` then tags the result." % (record["branch"], commit[:12], record["worktree"]))
        return "done"

    # --- worktrees and commits ---

    def _worktree(self, identifier):
        record = self._global_change(identifier)
        if record is not None:
            return Path(record["worktree"])  # a global change works on `evolve/<id>`, in a worktree of the harness repository
        return self.project / WORKTREES / str(identifier)

    def _add_worktree(self, attempt):
        """`.worktrees/<id>` on `ticket/<id>` from `main`, reusing what an earlier attempt left."""
        record = self._global_change(attempt.id)
        if record is not None:
            from wayline import changes
            return changes.add_global_worktree(self.harness_root, record)
        self._commit_harness_json(attempt)
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

    def _commit_harness_json(self, attempt):
        """Commit a `harness.json` the owner's switches left uncommitted, before a ticket that edits it leaves or rejoins `main`.

        `wayline switch` writes the file and commits nothing, and a harness ticket whose touch set names it (a local
        policy change, ticket 45) would otherwise branch from a stale copy and meet a fast-forward git refuses.
        """
        if "harness.json" not in (attempt.ticket.get("touches") or []):
            return
        with self.ledger.lock():
            if self._git(self.project, "status", "--porcelain", "--", "harness.json").stdout.strip():
                self._git(self.project, "add", "--", "harness.json")
                self._git(self.project, "commit", "-q", "-m", "wayline: harness.json as the owner's switches left it", "--", "harness.json")

    def _remove_worktree(self, identifier, branch=True):
        record = self._global_change(identifier)
        if record is not None:
            from wayline import changes
            changes.remove_global_worktree(self.harness_root, record, branch=branch)
            return
        path = self._worktree(identifier)
        if path.exists():
            self._git(self.project, "worktree", "remove", "--force", str(path), ok=None)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        self._git(self.project, "worktree", "prune")
        if branch:
            self._git(self.project, "branch", "-D", BRANCH % identifier, ok=None)

    def _render_reproduce(self):
        """Re-render `REPRODUCE.md`, `reproduce.json`, the locks, and `README.md` in `code/` (decision 17, ticket 106).

        Only after a wave that changed `code/` or ran a job a current finding cites (or changed which runs the findings
        cite); the paths written are committed with the wave, and the next push of the code repository carries them.
        A render that fails is said and tried again by the next wave.
        """
        try:
            return reproduce.render_if_changed(self.project)
        except (OSError, ValueError) as failure:
            self.say("  REPRODUCE.md was not rendered: %s; the next wave tries again" % failure)
            return []

    def _commit_ledger(self, rendered=()):
        """Commit what the wave wrote under `research/`, so `main` stays clean for the next fast-forward.

        The session directories of the attempts still in flight are left for a later wave. Their
        worker, or the thread waiting on it, is still writing there (`result.json`, the worker's
        `acceptance.json`), and a file renamed into place while `git add` reads the directory fails
        the whole add. The wave that carries an attempt commits its directory.
        """
        busy = [":(exclude)" + self._attempt_dir(attempt).relative_to(self.project).as_posix()
                for attempt in self.flight.values()]
        rendered = list(rendered)
        with self.ledger.lock():  # a commit to `main`, like the fast-forward of an integration
            self._git(self.project, "add", "--", RESEARCH, *busy, *rendered)
            if self._git(self.project, "diff", "--cached", "--name-only", "--", HEARTBEAT_PATH).stdout.strip():
                # A project laid out before the heartbeat was ignored: keep the file out of the commit.
                self._git(self.project, "reset", "-q", "--", HEARTBEAT_PATH)
            if self._git(self.project, "diff", "--cached", "--quiet", "--", RESEARCH, *rendered, ok=None).returncode == 0:
                return None
            self._git(self.project, "commit", "-q", "-m", LEDGER_COMMIT % self.number, "--", RESEARCH, *busy, *rendered)
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


def _job_seconds(record):
    """How long the job's last attempt ran, from its two timestamps; 0 when either is missing."""
    attempts = record.get("attempts") or [{}]
    started, ended = _parse_ts(attempts[-1].get("started_at")), _parse_ts(attempts[-1].get("ended_at"))
    if started is None or ended is None:
        return 0
    return max(0, int(round((ended - started).total_seconds())))


def _waiting_kind(reason):
    """What a wait is for, without the readings in its text: `needs 4 core(s)` of `needs 4 core(s) and the load is 7.5 ...`."""
    return None if reason is None else reason.split(" and ")[0]


def _provenance():
    from wayline import provenance  # the provenance module pulls in the gates and the report
    return provenance


def _inside(path, root):
    """Whether `path`, symlinks resolved, lies under `root`."""
    real, base = os.path.realpath(path), os.path.realpath(root)
    return real == base or real.startswith(base + os.sep)


def _moved_out_of(value, old, new):
    """`value` with every string that names `old` or a path under it naming the same path under `new` instead."""
    if isinstance(value, dict):
        return {key: _moved_out_of(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_moved_out_of(item, old, new) for item in value]
    if isinstance(value, str) and (value == old or value.startswith(old + os.sep)):
        return new + value[len(old):]
    return value


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


def _bytecode(path):
    """Whether an untracked path is Python bytecode: a `__pycache__/` directory or a `*.pyc` file."""
    path = path.rstrip("/")
    return "__pycache__" in path.split("/") or path.endswith(".pyc")


def _in_touch_set(path, touches):
    """Whether an untracked path lies in the ticket's touch set, as the touch-set guard reads one."""
    path = path.rstrip("/")
    for entry in touches or ():
        entry = str(entry).rstrip("/")
        if path == entry or path.startswith(entry + "/") or entry.startswith(path + "/"):
            return True
    return False


# --- the verb ---------------------------------------------------------------------------------

class _Simulated(NamedTuple):
    """What `--simulate-limit` asks for: how long, on whose windows, and whether it steps down or pauses."""

    seconds: float
    model: Optional[str]
    step_down: bool


def parse_simulated_limit(text):
    """`--simulate-limit`'s value as a `_Simulated`, or None when it is not one of its spellings.

    `S` arms a hit limit on every model's windows and `fable:S` one on Fable's weekly window, which
    pause the run and hold Fable launches (decisions 5 and 15). `cheap:S` and `cheap:fable:S` force a
    reading past `pacing.cheap_at` and under `pacing.stop_at` for that many seconds instead, on every
    model's windows or on Fable's alone, so a demo can show launches one rung down (decision 16).
    """
    rest, step_down = str(text), False
    if rest.startswith("cheap:"):
        rest, step_down = rest[len("cheap:"):], True
    model, _, seconds = rest.rpartition(":")
    if model not in ("", pacing.FABLE):
        return None
    try:
        value = float(seconds)
    except ValueError:
        return None
    return _Simulated(value, model or None, step_down) if 0 <= value < float("inf") else None


def run_command(args):
    """`wayline run`: the conductor over the active project, or the one `--project` names."""
    parser = argparse.ArgumentParser(prog="wayline run",
                                     description="run the conductor over a project until its frontier is empty")
    parser.add_argument("--project", help="the project to run; the active one by default")
    parser.add_argument("--resume", action="store_true", help="say in run_started that this run resumes one (every run replays the journal)")
    parser.add_argument("--detach", action="store_true", help="run as the transient user unit wayline-conductor, which outlives this shell")
    parser.add_argument("--simulate-limit", metavar="[cheap:][fable:]S",
                        help="the next launch carries a rejected rate_limit_event resetting S seconds ahead, which pauses the run; "
                             "with fable:S the next Fable launch is refused on Fable's weekly window, which holds only Fable launches; "
                             "with cheap:S (or cheap:fable:S) no launch is refused and a reading past cheap_at stands for S seconds, "
                             "under which every launch runs one rung down")
    parser.add_argument("--simulate-failure", metavar="ID", type=int,
                        help="every acceptance of ticket ID fails, on every attempt, so the escalation chain climbs one rung and on to the top")
    parser.add_argument("--max-waves", type=int, metavar="N", help="stop after N waves, whatever the frontier still holds")
    try:
        options = parser.parse_args(args)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 2
    if options.simulate_failure is not None and options.simulate_failure < 1:
        print("wayline run: --simulate-failure takes a ticket id, a whole number from 1", file=sys.stderr)
        return 2
    simulated = None if options.simulate_limit is None else parse_simulated_limit(options.simulate_limit)
    if options.simulate_limit is not None and simulated is None:
        print("wayline run: --simulate-limit takes <seconds>, fable:<seconds> (Fable's weekly window alone), or either "
              "prefixed by cheap: (a reading past cheap_at for that long, rather than a hit limit); the seconds are 0 or more",
              file=sys.stderr)
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

    if options.detach:
        return _detach(project, options)
    announce_dashboard(project)
    conductor = Conductor(project)
    print("run      %s (%s, radius %s)" % (project, harness.get("autonomy"), harness.get("radius")))
    if simulated is not None and simulated.step_down:
        conductor.simulate_step_down(simulated.seconds, simulated.model)
        print("simulate a reading past cheap_at for %g second(s) on %s; every launch runs one rung down"
              % (simulated.seconds, "Fable's weekly window" if simulated.model else "every model's windows"))
    elif simulated is not None:
        worker.simulate_limit(simulated.seconds, simulated.model)
        conductor.simulate_fable_hold(simulated.model == pacing.FABLE)
    if options.simulate_failure is not None:
        worker.simulate_failure(options.simulate_failure)
        print("simulate every acceptance of ticket %d fails, on every attempt" % options.simulate_failure)
    try:
        waves = conductor.run(max_waves=options.max_waves, resume=options.resume)
    except (ConductorError, ValueError, OSError) as failure:
        print("wayline run: %s" % failure, file=sys.stderr)
        return 1
    finally:
        worker.simulate_limit(None)  # a limit no launch took must not reach the next run in this process
        worker.simulate_failure(None)
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
    running = [identifier for identifier in running if identifier not in done and identifier not in failed]
    if running:
        print("ticket(s) %s still have jobs running; the next run polls them"
              % ", ".join(str(identifier) for identifier in running))
    if waves and waves[-1].ended:
        # After every `run_ended` the evolver runs a retrospective over the journal (decision 12); nothing in it fails this run.
        from wayline import changes  # the evolve loop pulls in the registry, the fixtures, and the session helpers
        changes.after_run(project, waves[-1].reason)
    return 1 if failed or rejected else 0


def _detach(project, options):
    """`run --detach`: the same run, started as the transient unit `wayline-conductor` (decision 5).

    The refusals a foreground run makes have already been made here, at the terminal, where the
    owner reads them; inside the unit they would only reach the manager's journal.
    """
    holder = conductor_holder(project)
    if holder is not None:
        print("wayline run: a conductor (pid %s) already runs on %s" % (holder.get("pid", "?"), project), file=sys.stderr)
        return 1
    run_args = ["--max-waves", str(options.max_waves)] if options.max_waves is not None else []
    if options.simulate_limit is not None:
        # Checked already, so the unit refuses nothing the terminal accepted; spelled as it was given.
        run_args += ["--simulate-limit", options.simulate_limit]
    if options.simulate_failure is not None:
        run_args += ["--simulate-failure", str(options.simulate_failure)]
    try:
        said = tick.launch_detached(project, run_args)
    except tick.UnitError as failure:
        print("wayline run: %s" % failure, file=sys.stderr)
        return 1
    print("detached %s as %s.service%s" % (project, tick.CONDUCTOR_UNIT, "  (%s)" % said if said else ""))
    print("  journalctl --user -u %s -f follows it; wayline status reads the project; wayline stop ends it" % tick.CONDUCTOR_UNIT)
    announce_dashboard(project)
    return 0


def announce_dashboard(project, out=None):
    """Print the dashboard's address and start its service when it is not active (decision 8).

    `run` never hosts the dashboard, so the address it prints is the service's, which outlives
    every conductor. Nothing here can fail the run: the dashboard is a view.
    """
    out = out or sys.stdout
    from wayline import dashboard  # the views import the project module this one does; keep the verb's import light
    state, detail = tick.ensure_dashboard()
    try:
        settings = dashboard.read_settings(project=project)
    except (ValueError, OSError) as failure:
        print("dashboard  unknown address: %s" % failure, file=out)
        return state
    notes = {
        "active": "",
        "started": "  (started %s)" % tick.DASHBOARD_SERVICE,
        "off": "  (%s; wayline serve runs it by hand)" % detail,
        "failed": "  (%s did not start: %s; wayline init installs it, wayline serve runs it by hand)" % (tick.DASHBOARD_SERVICE, detail),
    }
    # The token only at a terminal: a detached run's output goes to the user journal, which is kept.
    print("dashboard  %s%s" % (dashboard.dashboard_url(settings, with_token=dashboard.is_terminal(out)), notes[state]), file=out)
    print("  " + dashboard.tunnel_line(settings["port"]), file=out)
    return state
