"""The conductor (Implementation Decisions 5, Testing Decisions seam 4): the wave, end to end.

`wayline run` is one process over one project. A wave is one pass of its loop: regenerate
`graph.json`, compute the frontier, add a worktree for the ticket it picks, assemble the prompt,
launch the worker through the launcher seam, validate what comes back, run the machine acceptance
in the worktree, rebase onto `main`, run the acceptance again, fast-forward `main`, run it once
more there, write the findings and the status through the ledger, journal every step, and remove
the worktree. The run ends when the frontier is empty.

What M0 builds, and what it leaves to the tickets that extend it:

- One worker per wave, launched and waited for, so the whole path runs in the suite in seconds
  and no test sleeps. Ticket 07 makes the launch asynchronous, adds the launchable filter (touch
  sets and resources) and the pick order, and runs two workers at once.
- One resume per attempt, for an invalid result or a failed acceptance (BRIEF 9.1). The rest of
  the escalation ladder (a tier up, a split ticket, `needs_human`) is named in the `next` of the
  `ticket_failed` event and built by ticket 38.
- The conflict-free integration. A rebase conflict fails the ticket with `next: split`; the
  integrator role that resolves one arrives with ticket 08.
- No heartbeat, no lock on `research/conductor.json`, no `control` events and no replay: ticket
  09. No pacing and no pause: ticket 10. No job poller, so an experiment ticket whose jobs
  outlive its worker stays `running` and this run ends with nothing left that it can advance.
- A result's `proposals`, `decision_requests` and `goal_progress` are written into the ticket's
  `## Result` section so the owner sees them, and nothing else: admission is ticket 37, decision
  tickets are ticket 35, and keep-if-better is ticket 39.

The conductor never trusts the worker's own acceptance file. It runs the ticket's commands itself,
three times, and the ticket is `done` only once they passed on `main`.
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from wayline import HARNESS_ROOT, gates, tickets, worker
from wayline.ledger import (
    ACCEPTANCE, FINDING, INTEGRATED, RUN_ENDED, RUN_STARTED, TICKET_BLOCKED, TICKET_DONE,
    TICKET_FAILED, TICKET_LAUNCHED, TICKET_NEEDS_HUMAN, TICKET_RESULT, TICKET_RESUMED,
    TICKET_SESSION, Ledger,
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

    `failed` holds the tickets that were launched, did not reach `done`, and are not still
    running, whatever the reason: a failure, a block, or a question for a person. The journal
    says which.
    """

    number: int
    launched: list = field(default_factory=list)
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    running: list = field(default_factory=list)
    ended: bool = False
    reason: Optional[str] = None
    ledger_commit: Optional[str] = None

    @property
    def touched(self):
        """Whether this wave moved anything at all; a wave that did not cannot be repeated usefully."""
        return bool(self.launched or self.done or self.failed or self.running)


@dataclass
class _Attempt:
    """One attempt at one ticket, carried through the steps of the outcome."""

    ticket: dict
    body: str
    number: int
    worktree: Path
    role: Optional[worker.Role] = None
    tier: Optional[Tier] = None
    request: Optional[worker.LaunchRequest] = None
    envelope: Optional[worker.Envelope] = None
    session_id: Optional[str] = None
    resumed: bool = False

    @property
    def id(self):
        return self.ticket["id"]

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

    def say(self, message):
        print(message, file=self.out, flush=True)

    # --- the loop ---

    def wave(self):
        """One pass of the loop (decision 5), called directly by tests."""
        self.number += 1
        result = WaveResult(self.number)
        ready = tickets.frontier(self._graph())
        if ready:
            self._work(ready[0], result)
        graph = self._graph()
        running = [entry for entry in graph["tickets"] if entry["status"] == "running"]
        if not tickets.frontier(graph) and not running:
            self.ledger.append_event(RUN_ENDED, {"reason": "frontier_empty"})
            result.ended, result.reason = True, "frontier_empty"
        result.ledger_commit = self._commit_ledger()
        return result

    def run(self, max_waves=None, resume=False):
        """Journal `run_started` and take waves until the run ends; returns every wave's result.

        A wave that moved nothing ends the loop, because in M0 nothing can arrive while the
        conductor waits: there is no job poller, no tick, and no control event. The wait between
        waves, and the pause at a usage limit, arrive with tickets 09 and 10 and live here rather
        than inside the wave, so that no test sleeps (Testing Decisions, seam 4).

        `run_started` is journaled here rather than in the verb, because the dashboard calls this
        function in process.
        """
        harness = read_harness(self.project)
        self.ledger.append_event(RUN_STARTED, {
            "resume": bool(resume), "harness_tag": harness.get("harness_tag"),
            "autonomy": harness.get("autonomy"), "radius": harness.get("radius"), "pid": os.getpid(),
        })
        waves = []
        while max_waves is None or len(waves) < max_waves:
            result = self.wave()
            waves.append(result)
            if result.ended or not result.touched:
                break
        return waves

    def _graph(self):
        events, _ = self.ledger.read_events()
        graph, _ = tickets.refresh_graph(self.project, ledger=self.ledger, events=events)
        return graph

    # --- one ticket, one attempt ---

    def _work(self, entry, result):
        """One ticket from launch to `done`, or to whatever stopped it; nothing here raises out."""
        ticket, body = self._ticket(entry["id"])
        attempt = _Attempt(ticket, body, int(entry.get("attempt") or 0) + 1, self._worktree(entry["id"]))
        outcome = "failed"
        try:
            self._begin(attempt, entry)
            result.launched.append(attempt.id)
            outcome = self._outcome(attempt)
        except (ValueError, OSError) as failure:  # a launch, a role, a ticket file, or a git step
            self._fail(attempt, str(failure), "needs_human")
        {"done": result.done, "running": result.running}.get(outcome, result.failed).append(attempt.id)

    def _outcome(self, attempt):
        """What this attempt came to: `done`, `running` (its jobs outlive it), or `failed`."""
        if not self._final_result(attempt):
            return "failed"
        carried = self._act_on(attempt)
        if carried != "done":
            return carried
        if self._acceptance(attempt) and self._integrate(attempt):
            self._close(attempt)
            return "done"
        return "failed"

    def _begin(self, attempt, entry):
        """The worktree, the prompt, and the launch; returns once the worker has finished."""
        attempt.role = worker.read_role(attempt.ticket["role"], self.harness_root, self.project)
        attempt.tier = tier_for(self.policy, entry.get("difficulty", attempt.ticket["difficulty"]),
                                attempt.ticket.get("budget"))
        self._add_worktree(attempt)
        self._write_ticket(attempt, "running")
        prompt = self._prompt(attempt)
        attempt.request = self._request(attempt, prompt)
        self.say("wave %d: ticket %d %s (%s, %s %s, attempt %d)" % (
            self.number, attempt.id, attempt.ticket["title"], attempt.role.name,
            attempt.tier.model, attempt.tier.effort, attempt.number))
        attempt.envelope = worker.launch(
            attempt.request, on_start=lambda started: self._journal_launch(attempt, prompt, started))
        attempt.session_id = attempt.envelope.session_id
        self.ledger.append_event(TICKET_SESSION, {
            "ticket": attempt.id, "attempt": attempt.number,
            "session_id": attempt.session_id, "model": attempt.envelope.model,
        }, ticket=attempt.id, session_id=attempt.session_id)

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

    def _journal_launch(self, attempt, prompt, started):
        self.ledger.append_event(TICKET_LAUNCHED, {
            "ticket": attempt.id, "attempt": attempt.number, "role": attempt.role.name,
            "model": attempt.tier.model, "effort": attempt.tier.effort,
            "skills": list(attempt.ticket.get("skills") or []),
            "worktree": str(attempt.worktree), "pid": started.pid,
            "context_chars": prompt.context_chars, "prompt_sha256": prompt.sha256,
        }, ticket=attempt.id)

    # --- the worker outcome (BRIEF 9.1) ---

    def _final_result(self, attempt):
        """Validate the result; an invalid one is resumed once with the error, then the ticket fails."""
        self._journal_result(attempt)
        problem = self._invalid(attempt)
        if problem is None:
            return True
        problem = self._resumed_result(attempt, "invalid_result", RESUME_INVALID % problem)
        if problem is None:
            return True
        self._fail(attempt, "the result was still unusable after one resume: %s" % problem, "tier_up")
        return False

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

    def _resumed_result(self, attempt, reason, message):
        """Spend the attempt's one resume (BRIEF 9.1); returns why the new result is unusable, or None.

        A ticket whose session left no id to resume is failed here and reported as unusable, so
        both callers can treat "no usable result" as one answer.
        """
        if not attempt.session_id:
            self._fail(attempt, "there is no session id to resume: %s"
                       % "; ".join(attempt.envelope.errors or ["the session never started"]), "tier_up")
            return "the session left no id to resume"
        self.ledger.append_event(TICKET_RESUMED, {
            "ticket": attempt.id, "attempt": attempt.number,
            "session_id": attempt.session_id, "reason": reason,
        }, ticket=attempt.id, session_id=attempt.session_id)
        attempt.envelope = worker.resume(attempt.request, attempt.session_id, message)
        attempt.resumed = True
        self._journal_result(attempt)
        return self._invalid(attempt)

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

    def _acceptance(self, attempt):
        """The Type-A gates in the worktree; a failure is resumed once with the output."""
        record = self._accept(attempt, "worktree", attempt.worktree)
        if record["pass"]:
            return self._committed(attempt)
        problem = self._resumed_result(attempt, "acceptance_failed", RESUME_ACCEPTANCE % _failures(record["results"]))
        if problem is not None:
            self._fail(attempt, "the resumed session returned no usable result: %s" % problem, "tier_up")
            return False
        if not self._accept(attempt, "worktree", attempt.worktree)["pass"]:
            self._fail(attempt, "the machine acceptance still failed in the worktree after one resume", "tier_up")
            return False
        return self._committed(attempt)

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
        """Rebase, re-accept, fast-forward `main`, accept there (decision 5, the conflict-free case)."""
        if self._git(attempt.worktree, "rebase", MAIN, ok=None).returncode != 0:
            conflicts = [line for line in self._git(attempt.worktree, "diff", "--name-only",
                                                    "--diff-filter=U", ok=None).stdout.split("\n") if line.strip()]
            self._git(attempt.worktree, "rebase", "--abort", ok=None)
            self._fail(attempt, "rebasing %s onto main conflicts in %s; the integrator role arrives with ticket 08"
                       % (BRANCH % attempt.id, ", ".join(conflicts) or "a path git did not name"), "split")
            return False
        if not self._accept(attempt, "rebased", attempt.worktree)["pass"]:
            self._fail(attempt, "the machine acceptance failed after the rebase onto main", self._next_step(attempt))
            return False
        merge = self._git(self.project, "merge", "--ff-only", BRANCH % attempt.id, ok=None)
        if merge.returncode != 0:
            self._fail(attempt, "main could not be fast-forwarded to %s: %s"
                       % (BRANCH % attempt.id, (merge.stderr or merge.stdout).strip()), "split")
            return False
        commit = self._head(self.project)
        if not self._accept(attempt, "main", self.project)["pass"]:
            self._fail(attempt, "the machine acceptance failed on main after the fast-forward to %s; main "
                       "carries the commit and a person has to look" % commit[:12], "needs_human")
            return False
        self.ledger.append_event(INTEGRATED, {"ticket": attempt.id, "commit": commit, "resolved_by": "none"},
                                 ticket=attempt.id)
        self.say("  integrated %s into main as %s" % (BRANCH % attempt.id, commit[:12]))
        return True

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
            self.ledger.append_record(FINDINGS, record)
            self.ledger.append_event(FINDING, record, ticket=attempt.id)
        self._write_ticket(attempt, "done", attempt.result)
        self.ledger.append_event(TICKET_DONE, {"ticket": attempt.id}, ticket=attempt.id)
        self._remove_worktree(attempt.id)
        self.say("  ticket %d done" % attempt.id)

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
        """Commit what the wave wrote under `research/`, so `main` stays clean for the next fast-forward."""
        self._git(self.project, "add", "--", RESEARCH)
        if self._git(self.project, "diff", "--cached", "--quiet", "--", RESEARCH, ok=None).returncode == 0:
            return None
        self._git(self.project, "commit", "-q", "-m", LEDGER_COMMIT % self.number, "--", RESEARCH)
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
    ("resume", "--resume", "ticket 09 (resume, the heartbeat, and the control events)"),
    ("detach", "--detach", "ticket 09 (the transient wayline-conductor unit)"),
    ("simulate_limit", "--simulate-limit", "ticket 10 (pacing and the pause)"),
    ("simulate_failure", "--simulate-failure", "ticket 38 (the stall and the escalation ladder)"),
)


def run_command(args):
    """`wayline run`: the conductor over the active project, or the one `--project` names."""
    parser = argparse.ArgumentParser(prog="wayline run",
                                     description="run the conductor over a project until its frontier is empty")
    parser.add_argument("--project", help="the project to run; the active one by default")
    parser.add_argument("--resume", action="store_true", help="replay the journal and re-adopt live workers (ticket 09)")
    parser.add_argument("--detach", action="store_true", help="run as the transient unit wayline-conductor (ticket 09)")
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
        waves = conductor.run(max_waves=options.max_waves)
    except (ConductorError, ValueError, OSError) as failure:
        print("wayline run: %s" % failure, file=sys.stderr)
        return 1
    done = [identifier for wave in waves for identifier in wave.done]
    failed = [identifier for wave in waves for identifier in wave.failed]
    running = [identifier for wave in waves for identifier in wave.running]
    print("%d wave(s), %d ticket(s) done, %d unfinished%s"
          % (len(waves), len(done), len(failed), "; " + waves[-1].reason if waves and waves[-1].reason else ""))
    if running:
        print("ticket(s) %s left jobs running; nothing here can advance them until the job poller lands"
              % ", ".join(str(identifier) for identifier in running))
    return 1 if failed else 0
