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
  09. No pacing and no pause: ticket 10. No job poller, so a `running` result (an experiment
  ticket) is a ticket only a person can close until ticket 17 lands.

The conductor never trusts the worker's own acceptance file. It runs the ticket's commands itself,
three times, and the ticket is `done` only once they passed on `main`.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
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


# --- the difficulty tier ---------------------------------------------------------------------------


@dataclass
class Tier:
    """What a ticket's difficulty resolves to in the policy: the model, the effort, and the budget."""

    model: str
    effort: str
    budget: Optional[str] = None
    max_turns: Optional[int] = None
    max_minutes: Optional[int] = None
    context_chars: Optional[int] = None


def tier_for(policy, difficulty, ticket_budget=None):
    """The tier of `difficulty` (policy `difficulty`, `budget`, `context_pack`), the ticket's own budget winning.

    `context_pack.max_chars` is keyed by model and names only the three a worker runs on, so
    anything else (a `haiku` judge) takes the smallest cap rather than none at all.
    """
    tiers = policy.get("difficulty") or {}
    tier = tiers.get(str(difficulty), tiers.get(difficulty))
    if not isinstance(tier, dict) or "model" not in tier or "effort" not in tier:
        raise ConductorError("policy.difficulty has no tier %r; it has %s" % (difficulty, ", ".join(sorted(map(str, tiers))) or "none"))
    budget = dict((policy.get("budget") or {}).get(tier.get("budget")) or {})
    budget.update({key: value for key, value in (ticket_budget or {}).items() if value is not None})
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    return Tier(
        model=tier["model"], effort=tier["effort"], budget=tier.get("budget"),
        max_turns=budget.get("max_turns"), max_minutes=budget.get("max_minutes"),
        context_chars=caps.get(tier["model"], min(caps.values()) if caps else None),
    )


# --- what a wave did ---------------------------------------------------------------------------------


@dataclass
class WaveResult:
    """One pass of the loop, as the `run` verb and the tests read it.

    `failed` holds the tickets that were launched and did not reach `done`, whatever the reason:
    a failure, a block, or a question for a person. The journal says which.
    """

    number: int
    launched: list = field(default_factory=list)
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    ended: bool = False
    reason: Optional[str] = None
    ledger_commit: Optional[str] = None


@dataclass
class _Run:
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


# --- the conductor ------------------------------------------------------------------------------------


class Conductor:
    """One `wayline run` over one project: the wave, and the state a run carries between waves."""

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

    def run(self, max_waves=None, sleep=time.sleep, resume=False):
        """Journal `run_started` and take waves until the run ends; returns every wave's result.

        The sleep lives here and not inside the wave, so that no test sleeps (Testing Decisions,
        seam 4), and so the wave stays the one function a test drives. `run_started` lives here
        rather than in the verb, because the dashboard calls this function in process.
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
            if result.ended:
                break
            if not (result.launched or result.done or result.failed):
                sleep(self.policy.get("poll_seconds", 60))
        return waves

    def _graph(self):
        events, _ = self.ledger.read_events()
        graph, _ = tickets.refresh_graph(self.project, ledger=self.ledger, events=events)
        return graph

    # --- one ticket, one attempt ---

    def _work(self, entry, result):
        """One ticket from launch to `done`, or to whatever stopped it; nothing here raises out."""
        ticket, body = self._ticket(entry["id"])
        run = _Run(ticket, body, int(entry.get("attempt") or 0) + 1, self._worktree(entry["id"]))
        try:
            self._begin(run, entry)
            result.launched.append(run.id)
            if self._final_result(run) and self._act_on(run) and self._acceptance(run) and self._integrate(run):
                self._close(run)
                result.done.append(run.id)
                return
        except (ValueError, OSError) as failure:  # a launch, a role, a ticket file, or a git step
            self._fail(run, str(failure), "needs_human")
        result.failed.append(run.id)

    def _begin(self, run, entry):
        """The worktree, the prompt, and the launch; returns once the worker has finished."""
        run.role = worker.read_role(run.ticket["role"], self.harness_root, self.project)
        run.tier = tier_for(self.policy, entry.get("difficulty", run.ticket["difficulty"]), run.ticket.get("budget"))
        self._add_worktree(run)
        self._write_ticket(run, "running")
        prompt = self._prompt(run)
        run.request = self._request(run, prompt)
        self.say("wave %d: ticket %d %s (%s, %s %s, attempt %d)" % (
            self.number, run.id, run.ticket["title"], run.role.name, run.tier.model, run.tier.effort, run.number))
        run.envelope = worker.launch(run.request, on_start=lambda started: self._journal_launch(run, prompt, started))
        run.session_id = run.envelope.session_id
        self.ledger.append_event(TICKET_SESSION, {
            "ticket": run.id, "attempt": run.number,
            "session_id": run.session_id, "model": run.envelope.model,
        }, ticket=run.id, session_id=run.session_id)

    def _prompt(self, run):
        """The prompt of decision 3; a locator resolves in the worktree first, then in the project."""
        return worker.assemble_prompt(
            run.ticket, run.role,
            roots=(run.worktree, self.project),
            max_chars=run.tier.context_chars,
            budget={"max_turns": run.tier.max_turns, "max_minutes": run.tier.max_minutes},
            consult_max=(self.policy.get("consultant") or {}).get("max_questions_per_ticket", worker.CONSULT_MAX),
        )

    def _request(self, run, prompt):
        run_dir = worker.session_dir(self.project, run.id, run.number)
        settings = gates.write_worker_settings(run_dir / "settings.json", self.harness_root)
        return worker.LaunchRequest(
            role=run.role.name,
            model=run.tier.model,
            effort=run.tier.effort,
            prompt=prompt.text,
            agent_json=run.role.agent_json(run.tier.model, run.tier.effort, run.tier.max_turns),
            allowed_tools=list(run.role.allowed_tools),
            disallowed_tools=list(run.role.disallowed_tools),
            settings_path=settings,
            add_dirs=[str(self.harness_root), str(self.project)],
            cwd=run.worktree,
            env=worker.session_env(self.project, run.id, run.number, run.ticket["touches"]),
            schema_path=self.harness_root / "schemas" / ((run.role.output_schema or "result") + ".json"),
            max_minutes=run.tier.max_minutes,
        )

    def _journal_launch(self, run, prompt, started):
        self.ledger.append_event(TICKET_LAUNCHED, {
            "ticket": run.id, "attempt": run.number, "role": run.role.name, "model": run.tier.model,
            "effort": run.tier.effort, "skills": list(run.ticket.get("skills") or []),
            "worktree": str(run.worktree), "pid": started.pid,
            "context_chars": prompt.context_chars, "prompt_sha256": prompt.sha256,
        }, ticket=run.id)

    # --- the worker outcome (BRIEF 9.1) ---

    def _final_result(self, run):
        """Validate the result; an invalid one is resumed once with the error, then the ticket fails."""
        self._journal_result(run)
        problem = self._invalid(run)
        if problem is None:
            return True
        if not self._resume(run, "invalid_result", RESUME_INVALID % problem):
            return False
        self._journal_result(run)
        problem = self._invalid(run)
        if problem is None:
            return True
        self._fail(run, "the result was still unusable after one resume: %s" % problem, "tier_up")
        return False

    def _invalid(self, run):
        """Why the envelope is not a result the conductor can act on, or None when it is one."""
        if run.envelope is None:
            return "the worker was never launched"
        if not run.envelope.valid:
            return "; ".join(run.envelope.errors) or "the session returned no structured result"
        returned = run.result.get("ticket_id")
        if returned != run.id:
            return "the result carries ticket_id %r, and this is ticket %d" % (returned, run.id)
        return None

    def _journal_result(self, run):
        envelope = run.envelope
        self.ledger.append_event(TICKET_RESULT, {
            "ticket": run.id, "attempt": run.number, "session_id": run.session_id,
            "status": run.result.get("status"), "turns": envelope.num_turns,
            "duration_ms": envelope.duration_ms, "usage": envelope.usage,
            "permission_denials": envelope.permission_denials, "valid": self._invalid(run) is None,
        }, ticket=run.id, session_id=run.session_id)

    def _resume(self, run, reason, message):
        """The one resume an attempt gets (BRIEF 9.1); False when there is no session to resume."""
        if not run.session_id:
            self._fail(run, "there is no session id to resume: %s" % "; ".join(run.envelope.errors or ["the session never started"]), "tier_up")
            return False
        self.ledger.append_event(TICKET_RESUMED, {
            "ticket": run.id, "attempt": run.number, "session_id": run.session_id, "reason": reason,
        }, ticket=run.id, session_id=run.session_id)
        run.envelope = worker.resume(run.request, run.session_id, message)
        run.resumed = True
        return True

    def _act_on(self, run):
        """What the result's own status asks for; only `done` goes on to the acceptance and the integration."""
        outside = run.result.get("touched_outside_declared") or []
        blocked_on = run.result.get("blocked_on")
        if outside or blocked_on:
            path = ", ".join(outside) if outside else blocked_on
            self._write_ticket(run, "blocked", run.result)
            self.ledger.append_event(TICKET_BLOCKED, {"ticket": run.id, "path": path}, ticket=run.id)
            self.say("  ticket %d is blocked on %s; the planner re-cuts it" % (run.id, path))
            return False
        status = run.result.get("status")
        if status == "done":
            return True
        summary = (run.result.get("summary") or "").strip()
        if status == "failed":
            self._fail(run, summary or "the worker reported a failure and left no summary", "tier_up")
        elif status == "needs_human":
            self._needs_human(run, summary or "the worker asked for a person and left no question")
        elif status == "running":
            self._needs_human(run, "the result leaves job(s) running (%s) and the job poller arrives with ticket 17"
                              % (", ".join(run.result.get("jobs") or []) or "none named"))
        else:
            self._fail(run, "the result carries the status %r, which the conductor does not act on" % (status,), "needs_human")
        return False

    def _acceptance(self, run):
        """The Type-A gates in the worktree; a failure is resumed once with the output."""
        record = self._accept(run, "worktree")
        if record["pass"]:
            return self._committed(run)
        if not self._resume(run, "acceptance_failed", RESUME_ACCEPTANCE % _failures(record["results"])):
            return False
        self._journal_result(run)
        problem = self._invalid(run)
        if problem is not None:
            self._fail(run, "the resumed session returned no usable result: %s" % problem, "tier_up")
            return False
        if not self._accept(run, "worktree")["pass"]:
            self._fail(run, "the machine acceptance still failed in the worktree after one resume", "tier_up")
            return False
        return self._committed(run)

    def _accept(self, run, where):
        """Run the ticket's machine acceptance where the spec says, and journal what it found."""
        commands = (run.ticket.get("acceptance") or {}).get("machine") or []
        cwd = self.project if where == "main" else run.worktree
        record = gates.acceptance_file_record(gates.run_machine_acceptance(commands, cwd, self._timeout()), where)
        self.ledger.append_event(ACCEPTANCE, {
            "ticket": run.id, "attempt": run.number, "where": where,
            "pass": record["pass"], "results": record["results"],
        }, ticket=run.id, session_id=run.session_id)
        self.say("  acceptance (%s): %s" % (where, "pass" if record["pass"] else "fail"))
        return record

    def _timeout(self):
        timeout = self.policy.get("acceptance_timeout_s", 600)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ConductorError("policy.acceptance_timeout_s is %r; it is a positive number of seconds" % (timeout,))
        return timeout

    def _committed(self, run):
        """The branch is what gets integrated, so work the worker left uncommitted is not a result.

        Tracked changes always count. An untracked file counts when it lies in the ticket's touch
        set, which is where this ticket's work belongs; untracked noise elsewhere (a `__pycache__`
        the acceptance commands just made) is not the worker's doing and is not held against it.
        """
        dirty = [path for status, path in porcelain_entries(self._git(run.worktree, "status", "--porcelain", "-z").stdout)
                 if status != "??" or _in_touch_set(path, run.ticket["touches"])]
        if not dirty:
            return True
        self._fail(run, "the worker left %d path(s) uncommitted in its worktree (%s); the conductor integrates the branch, not the working tree"
                   % (len(dirty), ", ".join(sorted(dirty)[:5])), "tier_up")
        return False

    # --- the integration protocol ---

    def _integrate(self, run):
        """Rebase, re-accept, fast-forward `main`, accept there (decision 5, the conflict-free case)."""
        if self._git(run.worktree, "rebase", MAIN, ok=None).returncode != 0:
            conflicts = [line for line in self._git(run.worktree, "diff", "--name-only", "--diff-filter=U", ok=None).stdout.split("\n") if line.strip()]
            self._git(run.worktree, "rebase", "--abort", ok=None)
            self._fail(run, "rebasing %s onto main conflicts in %s; the integrator role arrives with ticket 08"
                       % (BRANCH % run.id, ", ".join(conflicts) or "a path git did not name"), "split")
            return False
        if not self._accept(run, "rebased")["pass"]:
            self._fail(run, "the machine acceptance failed after the rebase onto main", "tier_up")
            return False
        merge = self._git(self.project, "merge", "--ff-only", BRANCH % run.id, ok=None)
        if merge.returncode != 0:
            self._fail(run, "main could not be fast-forwarded to %s: %s" % (BRANCH % run.id, (merge.stderr or merge.stdout).strip()), "split")
            return False
        commit = self._head(self.project)
        if not self._accept(run, "main")["pass"]:
            self._fail(run, "the machine acceptance failed on main after the fast-forward to %s; main carries the commit and a person has to look"
                       % commit[:12], "needs_human")
            return False
        self.ledger.append_event(INTEGRATED, {"ticket": run.id, "commit": commit, "resolved_by": "none"}, ticket=run.id)
        self.say("  integrated %s into main as %s" % (BRANCH % run.id, commit[:12]))
        return True

    # --- closing the ticket ---

    def _close(self, run):
        """The findings, the status, `ticket_done`, and the worktree the ticket no longer needs."""
        for index, finding in enumerate(run.result.get("findings") or [], start=1):
            record = {
                "id": "t%d-a%d-f%d" % (run.id, run.number, index),
                "ticket": run.id,
                "text": finding["text"],
                "provenance": finding["provenance"],
                "negative": bool(finding.get("negative", False)),
            }
            self.ledger.append_record(FINDINGS, record)
            self.ledger.append_event(FINDING, record, ticket=run.id)
        self._write_ticket(run, "done", run.result)
        self.ledger.append_event(TICKET_DONE, {"ticket": run.id}, ticket=run.id)
        self._remove_worktree(run.id)
        self.say("  ticket %d done" % run.id)

    def _fail(self, run, reason, next_step):
        """Journal the failure and leave the worktree and the branch for the attempt that follows."""
        self.ledger.append_event(TICKET_FAILED, {
            "ticket": run.id, "attempt": run.number, "reason": reason, "next": next_step,
        }, ticket=run.id, session_id=run.session_id)
        self._write_ticket(run, "failed", run.result)
        self.say("  ticket %d failed: %s (next: %s)" % (run.id, reason, next_step))

    def _needs_human(self, run, question):
        self.ledger.append_event(TICKET_NEEDS_HUMAN, {"ticket": run.id, "question": question}, ticket=run.id)
        self._write_ticket(run, "needs_human", run.result)
        self.say("  ticket %d needs a person: %s" % (run.id, question))

    # --- the ticket file ---

    def _ticket(self, identifier):
        for ticket in tickets.read_tickets(self.project):
            if ticket["id"] == identifier:
                return ticket, tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(ticket))[1]
        raise ConductorError("no ticket in %s has id %s" % (tickets.tickets_dir(self.project), identifier))

    def _write_ticket(self, run, status, result=None):
        """The status and, once an attempt has a result, the `## Result` section (decision 2)."""
        run.ticket = dict(run.ticket, status=status)
        if result:
            run.body = _with_result(run.body, run.number, result)
        tickets.write_ticket(self.ledger, run.ticket, run.body)

    # --- git ---

    def _worktree(self, identifier):
        return self.project / WORKTREES / str(identifier)

    def _add_worktree(self, run):
        """`.worktrees/<id>` on `ticket/<id>` from `main`, reusing what an earlier attempt left."""
        branch = BRANCH % run.id
        if (run.worktree / ".git").exists():
            if self._git(run.worktree, "rev-parse", "--abbrev-ref", "HEAD", ok=None).stdout.strip() == branch:
                return run.worktree
            self._remove_worktree(run.id, branch=False)
        elif run.worktree.exists():
            raise ConductorError("%s exists and is not a worktree; remove it and run again" % run.worktree)
        self._git(self.project, "worktree", "prune")
        known = self._git(self.project, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch, ok=None).returncode == 0
        self._git(self.project, "worktree", "add", *([] if known else ["-b", branch]), str(run.worktree), branch if known else MAIN)
        return run.worktree

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
        """One git command; `ok=None` hands the caller the exit code instead of raising."""
        done = subprocess.run(["git", "-C", str(cwd), *self._who(), *args], capture_output=True, text=True)
        if ok is not None and done.returncode not in ok:
            raise ConductorError("git %s failed in %s (exit %d): %s" % (args[0], cwd, done.returncode, (done.stderr or done.stdout).strip()))
        return done

    def _who(self):
        """A committer identity, only when the project's repository has none of its own."""
        if self._who_args is None:
            done = subprocess.run(["git", "-C", str(self.project), "config", "user.email"], capture_output=True, text=True)
            self._who_args = () if done.stdout.strip() else IDENTITY
        return self._who_args


# --- the ticket body and the resume message ------------------------------------------------------------


def _with_result(body, attempt, result):
    """Append this attempt's `## Result` section to the ticket body (decision 2)."""
    lines = ["### Attempt %d" % attempt, "", (result.get("summary") or "").strip() or "(the result carried no summary)"]
    for key, label in (("outputs_written", "Wrote"), ("commands_run", "Ran")):
        items = result.get(key) or []
        if items:
            lines.extend(["", "%s: %s" % (label, ", ".join("`%s`" % item for item in items))])
    text = body.rstrip("\n")
    if "\n## Result\n" not in text + "\n":
        lines = ["## Result", ""] + lines
    return text + "\n\n" + "\n".join(lines) + "\n"


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


# --- starting a run -----------------------------------------------------------------------------------


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
    done = subprocess.run(["git", "-C", str(project), "status", "--porcelain", "-z"], capture_output=True, text=True)
    if done.returncode != 0:
        raise ConductorError("git status failed in %s: %s" % (project, (done.stderr or done.stdout).strip()))
    return sorted({path for _, path in porcelain_entries(done.stdout)
                   if path != RESEARCH and not path.startswith(RESEARCH + "/")})


def refuse_to_start(project, harness_root=HARNESS_ROOT):
    """Every reason this run must not start, and every note worth printing (decision 5).

    Returns `(problems, notes)`; a run starts only when `problems` is empty. The pin is compared
    only when the harness checkout is exactly on a tag: a checkout that is not (a branch under
    development, which is where the harness is built) has no tag to differ from the pin, so it
    becomes a note naming the pin rather than a refusal that would make the harness unusable on
    the machine that builds it.
    """
    problems, notes = [], []
    branch = subprocess.run(["git", "-C", str(project), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    if branch.returncode != 0:
        problems.append("%s is not a git repository, and the conductor branches worktrees from main: run wayline init %s" % (project, project))
        return problems, notes
    if branch.stdout.strip() != MAIN:
        problems.append("the project is on the branch %r, not %s, and the conductor fast-forwards %s: run git -C %s switch %s"
                        % (branch.stdout.strip(), MAIN, MAIN, project, MAIN))
    dirty = dirty_outside_research(project)
    if dirty:
        problems.append("%s has %d change(s) outside research/ (%s); commit or stash them, then run again"
                        % (project, len(dirty), ", ".join(dirty[:5]) + (", ..." if len(dirty) > 5 else "")))
    pinned = read_harness(project).get("harness_tag")
    described = subprocess.run(["git", "-C", str(harness_root), "describe", "--tags", "--exact-match"], capture_output=True, text=True)
    tag = described.stdout.strip() if described.returncode == 0 else None
    if tag is None:
        notes.append("the harness checkout %s is not on a tag, so the pin %s is not checked" % (harness_root, pinned))
    elif pinned and tag != pinned:
        problems.append("the harness checkout is %s and the project pins %s: run wayline upgrade --to %s, or check out %s" % (tag, pinned, tag, pinned))
    return problems, notes


# The flags of decision 1's verb table that later tickets build, named so `run` can say which.
LATER = (
    ("resume", "--resume", "ticket 09 (resume, the heartbeat, and the control events)"),
    ("detach", "--detach", "ticket 09 (the transient wayline-conductor unit)"),
    ("simulate_limit", "--simulate-limit", "ticket 10 (pacing and the pause)"),
    ("simulate_failure", "--simulate-failure", "ticket 38 (the stall and the escalation ladder)"),
)


def run_command(args):
    """`wayline run`: the conductor over the active project, or the one `--project` names."""
    parser = argparse.ArgumentParser(prog="wayline run", description="run the conductor over a project until its frontier is empty")
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
        problems, notes = refuse_to_start(project)
        harness = read_harness(project)
    except (ProjectError, ConductorError, ValueError, OSError) as failure:
        print("wayline run: %s" % failure, file=sys.stderr)
        return 1
    for note in notes:
        print("note     %s" % note)
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
    print("%d wave(s), %d ticket(s) done, %d unfinished%s"
          % (len(waves), len(done), len(failed), "; " + waves[-1].reason if waves and waves[-1].reason else ""))
    return 1 if failed else 0
