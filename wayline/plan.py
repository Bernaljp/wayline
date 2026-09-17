"""Plan, phase P4 (Implementation Decisions 10, 2, and 5; BRIEF 8.2 to 8.4). Built by ticket 34.

The spec becomes an executable graph. `wayline plan` launches the `planner` role in its plan protocol
through the worker launcher (seam 1), on `policy.roles.planner`, with `plan.json` as its schema and,
in its prompt, `research/SPEC.md` whole, `GOAL.json`, the query pack, the registry (rebuilt at every
launch), and what the journal says already failed. The session writes nothing: it returns a `plan`
record, tickets keyed `T1`, `T2`, ... with `blocked_by` among the keys or `#<id>` for a ticket the
project holds, and the decision tickets to open, each with what it pauses. Code numbers the tickets
from the next free id, has the librarian assign a role and skills to each (journaled `assigned`),
runs the plan-time checks, writes `research/tickets/NN-slug.md` in the flat YAML subset (journaled
`ticket_created`), regenerates `graph.json`, opens the decision tickets (`decisions.open_decision`),
and keeps the record with the ids it became as `research/plan.json`.

**The checks** (`check_tickets`, and `check_graph` on a written graph) are the Type-A gate of
decision 10: the graph is a DAG; every work ticket has `demo`, `acceptance.machine`, `touches` under
the project (and never `research/`, which the ledger alone writes), `difficulty` 1 to 5,
`context_pack`, `role`, and `skills`; no machine criterion passes at the base commit, which is `main`
of the project's repository checked out into a detached worktree (the project directory itself when
it lies in no repository); and every `code` ticket the planner declared to add public API is
followed by a `docs` ticket, the declaration kept under `## Public API` in the ticket body so a
written graph can be checked again. Every check runs on every plan, so the one return a failing plan
gets carries every failure; a second failure ends the call and writes nothing.

**The cuts.** A first `plan` cuts the whole graph. `wayline plan --replan` (`replan`) re-cuts every
work ticket that is `open` or `blocked`: the planner is given the graph as it stands and the
journal's failures, stalls, blocks, findings, and answers, the superseded tickets are parked and
journaled `ticket_cancelled` by the planner, a planner's decision ticket that paused only superseded
tickets is parked with them, and the new tickets may wait on the kept ones as `#<id>`. `wayline plan
--split <id>` (`split`) replaces one ticket with at least two no harder than it: the pieces inherit
its blockers, whatever waited on it waits on all of them, and the ticket is parked the same way. Both
are what the conductor calls at a stall and at the `split` rung of the escalation ladder (ticket 38).
A `revise` is a plan cut again with what the owner asked to change.

**The confirmation**, by autonomy, as `wayline specify` asks it. Under `checkpoints` a decision ticket
"Confirm the graph" is opened with `blocking: all` and origin `plan: confirm research/graph.json at
<sha>`, in the same locked section that writes the tickets, so no wave can find them without their
gate; under `autonomous` the decider answers it at once; under `interactive` the session asks the
owner and records the word with `wayline plan confirm` or `wayline plan revise "<what to change>"`,
journaled as a `decision` with no ticket whose answer leads with `graph <sha>:`. An answer that
confirms journals `phase P4 -> P5`. Any other answer is what to change: `graph_sent_back`, called from
every path an answer takes (`project.answer`, an answer written into the file, the decider), parks the
graph's open tickets at once, because the conductor closes an answered ticket at its next wave
whatever the answer says; the graph then stands sent back until the next `wayline plan` cuts it again
with the change, and no later answer confirms it. A split asks nothing: it inherits the graph's
confirmation, so `plan.json` is not rewritten by it.

`plan_state` reads all of this back from `plan.json`, the tickets, and the journal, so the verb is
safe to run again at any point: it cuts, asks, waits, or advances, whichever the ledger says is owed.
Two cuts of one graph at once are refused at the write: a first plan when one was written since the
session launched, a re-cut when the tickets it supersedes are not the ones the planner was shown.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from wayline import HARNESS_ROOT, decider, decisions, gates, registry, specify, worker
from wayline.cli import parse_args
from wayline.frontmatter import dump_document
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import (
    DECISION, DIFFICULTY_RAISED, FINDING, PROGRESS, STALL, TICKET_BLOCKED, TICKET_CANCELLED, TICKET_CREATED, TICKET_DONE, TICKET_FAILED,
    TICKET_NEEDS_HUMAN, Ledger, LedgerError, now_ts,
)
from wayline.project import ProjectError, find_project, journal_written_answers, policy_for, read_harness
from wayline.project import answer as answer_ticket
from wayline.tickets import (
    DECISION as DECISION_KIND, SATISFIED, TicketError, answer_section, build_graph, filename, next_id, read_ticket, read_tickets,
    refresh_graph, section, tickets_dir, write_ticket,
)

__all__ = [
    "PLANNER", "PLAN_SCHEMA", "PLAN_JSON", "KINDS", "RECUT", "PlanError", "Cut", "Prepared", "is_existing", "existing_id",
    "ticket_body", "adds_public_api", "retry_steps", "touch_problem", "base_checkout", "criteria_at_base", "check_tickets",
    "check_graph", "superseded_by", "prepare", "check_plan", "read_all", "registry_text", "rubric_text", "journal_text", "graph_text",
    "plan_prompt", "cut_graph", "write_plan", "park_open", "read_plan", "graph_sha", "plan_state", "graph_sent_back", "confirm",
    "advance", "plan", "replan", "split", "render_report", "plan_command", "SPLIT_NOTE", "split_from",
]

PLANNER = specify.PLANNER
PLAN_SCHEMA = "plan"
PLAN_JSON = "plan.json"                 # research/plan.json: the record as returned, and the ids it became
SESSIONS = "sessions/plan"              # research/sessions/plan/<n>
PLAN_PHASE, EXECUTE_PHASE = "P4", "P5"
SUBJECT = "research/graph.json"
ORIGIN_PREFIX = "plan: confirm %s at " % SUBJECT
ORIGIN = ORIGIN_PREFIX + "%s"
TITLE = "Confirm the graph"
CONFIRM, REVISE = specify.CONFIRM, specify.REVISE
ANSWER_PREFIX = "graph %s: "            # the interactive answer's `decision`, keyed by the graph it answers
INTERACTIVE, CHECKPOINTS, AUTONOMOUS = specify.INTERACTIVE, specify.CHECKPOINTS, specify.AUTONOMOUS
# The four cuts of the graph the planner is launched for.
KINDS = ("plan", "replan", "split", "revise")
# The statuses a re-cut takes back: work not started, or stopped on a path the planner has to re-cut around.
RECUT = ("open", "blocked")
# The statuses a ticket can be split from: not started, or stopped short of a person.
SPLITTABLE = ("open", "failed", "blocked", "needs_human")
CLOSED = SATISFIED + ("parked",)
EXISTING = "#"                          # a reference to a ticket the project holds: #<id>
BY_PLANNER = "planner"                  # `ticket_cancelled` by the planner: a superseded ticket
MAIN = "main"                           # the base commit's branch, the one worktrees branch from (decision 3)
CHECK_LABEL = "wayline plan"
JOURNAL_LINES = 200                     # the journal digest keeps this many of its last lines
UNASSIGNED = "unassigned"               # the role a ticket no role covers is prepared with, so the check names the kind
DEMO_HEADING = "## Demo"
NOTES_HEADING = "## Notes"
PUBLIC_API_HEADING = "## Public API"
PUBLIC_API_LINE = "This ticket adds public API, so a `docs` ticket follows it."
SUPERSEDED_HEADING = "## Superseded"

RESUME_INVALID = (
    "The plan you returned could not be read: %s. Return the whole plan again through the structured output, as the plan "
    "schema asks."
)
RESUME_CHECKS = (
    "The harness's plan-time checks failed on the plan you returned:\n\n%s\n\nChange what they name, keep the rest, and "
    "return the whole plan again through the structured output."
)
# The signals of BRIEF 8.4's rubric, by difficulty; the model, the effort, and the budget come from the policy.
SIGNALS = {
    1: "mechanical, one file, fully machine-checkable",
    2: "a routine change, a known pattern, few files",
    3: "a new code path or an experiment, numerical care; an independent verdict on the diff follows",
    4: "design judgment, several modules, ambiguous acceptance; an independent verdict on the result follows",
    5: "research-critical, the claim depends on it; the verdict is mandatory and the ticket is accepted only after it",
}


class PlanError(ValueError):
    """A graph nobody could cut: no confirmed spec, a ticket that cannot be split, a plan that failed its checks twice."""

    def __init__(self, message, failures=()):
        super().__init__(message)
        self.failures = list(failures)


@dataclass
class Cut:
    """One cut of the graph: which of the planner's four asks this launch is, and what it carries."""

    kind: str                                   # plan | replan | split | revise
    of: Optional[int] = None                    # the ticket a split replaces
    change: Optional[str] = None                # what the owner or the decider asked to change, for a revise
    sent_back: list = field(default_factory=list)  # the ids a sent-back answer parked, which a revise takes back too

    def __post_init__(self):
        if self.kind not in KINDS:
            raise PlanError("a cut is one of %s, got %r" % (", ".join(KINDS), self.kind))
        if (self.kind == "split") != (self.of is not None):
            raise PlanError("a split names the ticket it replaces, and no other cut does")

    @property
    def asked(self):
        """What the planner is asked for, in one line of its prompt."""
        return {
            "plan": "the first cut of this project's graph",
            "replan": "a re-cut after a stall: every ticket marked re-cut below is cut again, from what the journal says failed",
            "split": "a split of ticket #%s, which failed its escalation: at least two smaller tickets that replace it" % self.of,
            "revise": "a re-cut: the owner sent the graph back with what to change",
        }[self.kind]

    def why_superseded(self, replacements):
        """The line a parked ticket's body carries: which cut superseded it and what replaced it."""
        named = ", ".join(str(identifier) for identifier in replacements) or "none"
        return {
            "split": "Split by the planner into tickets %s." % named,
            "replan": "Re-cut by the planner after a stall; its replacements are tickets %s." % named,
            "revise": "Re-cut by the planner with the owner's change; its replacements are tickets %s." % named,
            "plan": "Superseded by the planner's first cut of the graph; its replacements are tickets %s." % named,
        }[self.kind]


def _one_line(text):
    return " ".join(str(text or "").split())


def _prose(text):
    """Free prose for a ticket body: a line that would read as a heading is escaped, so the sections stay where they are."""
    lines = []
    for line in str(text or "").strip().split("\n"):
        lines.append("\\" + line if line.lstrip().startswith("#") else line)
    return "\n".join(lines)


# --- references and bodies -------------------------------------------------------------------------------


def is_existing(reference):
    """Whether a `blocked_by` or `pauses` entry names a ticket the project holds (`#<id>`) rather than a key of the plan."""
    return isinstance(reference, str) and reference.startswith(EXISTING)


def existing_id(reference):
    return int(reference[len(EXISTING):])


SPLIT_NOTE = "Cut from ticket %d by the planner's split."
_SPLIT_NOTE_RE = re.compile(r"^Cut from ticket (\d+) by the planner's split\.$", re.MULTILINE)


def split_from(body):
    """The id of the ticket a split cut this one from, read from the note `ticket_body` writes; None for any other ticket."""
    match = _SPLIT_NOTE_RE.search(body or "")
    return int(match.group(1)) if match else None


def ticket_body(item, of=None):
    """A cut ticket's body: `## Demo`, the planner's notes, and the public-API declaration the docs check reads back."""
    lines = [DEMO_HEADING, "", _prose(_one_line(item["demo"]))]
    notes = _prose(item.get("notes") or "")
    if of is not None:
        notes = SPLIT_NOTE % of + ("\n\n" + notes if notes else "")
    if notes:
        lines += ["", NOTES_HEADING, "", notes]
    if item.get("adds_public_api"):
        lines += ["", PUBLIC_API_HEADING, "", PUBLIC_API_LINE]
    return "\n".join(lines) + "\n"


def adds_public_api(body):
    """Whether a ticket body carries the planner's declaration that the ticket adds public API."""
    return section(body or "", PUBLIC_API_HEADING) is not None


def retry_steps(value):
    """A plan's retry ladders as a ticket file spells them: each override object as `--batch-size=16 NAME=value`."""
    if not value:
        return None
    spelled = {}
    for name in ("host_oom", "gpu_oom"):
        steps = []
        for step in value.get(name) or []:
            if isinstance(step, dict):
                step = " ".join("%s=%s" % (key, step[key]) for key in step)
            steps.append(str(step))
        spelled[name] = steps
    return spelled


# --- the plan-time checks ------------------------------------------------------------------------------


def touch_problem(touch, project):
    """Why a touch set entry is not a path under the project, or None when it is one.

    Absolute paths, `..`, and the whole project are refused, and so is anything under `research/`,
    which the ledger alone writes (decision 2): a worker whose touch set named it would be allowed
    by the guard to write what the conductor owns.
    """
    text = str(touch or "").strip()
    if not text:
        return "is empty"
    if text.startswith("/") or text.startswith("~"):
        return "is not a path under the project"
    parts = [part for part in text.replace("\\", "/").split("/") if part not in ("", ".")]
    if ".." in parts:
        return "leaves the project"
    if not parts:
        return "names the whole project"
    root = Path(project).resolve()
    if not (root / text).resolve().is_relative_to(root):
        return "resolves outside the project"
    if parts[0] == "research":
        return "is under research/, which the ledger alone writes"
    return None


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _repository(project):
    """`(toplevel, prefix, ref, commit)` of the repository the project lies in, or None when it lies in none.

    The base is `main` (the branch the conductor's worktrees branch from, decision 3), else `HEAD`. A
    project inside a larger repository is checked at its prefix under that repository's base. A
    repository with no commit has no base, which is said rather than checked in place.
    """
    top = _git(project, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        return None
    toplevel = Path(top.stdout.strip()).resolve()
    prefix = Path(project).resolve().relative_to(toplevel)
    for ref in (MAIN, "HEAD"):
        done = _git(toplevel, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if done.returncode == 0 and done.stdout.strip():
            return toplevel, prefix, ref, done.stdout.strip()
    raise PlanError("the repository at %s has no commit to be the base the machine criteria are run at" % toplevel)


@contextmanager
def base_checkout(project):
    """`(directory, description)`: the base commit checked out to run the machine criteria in, removed afterward.

    A detached worktree of the base under a temporary directory, so an uncommitted, untracked, or
    ignored file in the working tree cannot make a criterion pass; a worktree that cannot be added is
    a refusal, never a run in the live tree. A project that lies in no repository is checked in place,
    since it has no commit to be the base.
    """
    project = Path(project).resolve()
    found = _repository(project)
    if found is None:
        yield project, "the project directory, which lies in no repository"
        return
    toplevel, prefix, ref, commit = found
    root = Path(tempfile.mkdtemp(prefix="wayline-plan-base-"))
    checkout = root / "base"
    added = _git(toplevel, "worktree", "add", "--detach", str(checkout), commit)
    if added.returncode != 0:
        shutil.rmtree(root, ignore_errors=True)
        raise PlanError("a worktree of %s at %s could not be added to run the machine criteria at the base: %s"
                        % (toplevel, commit[:12], (added.stderr or added.stdout).strip()))
    try:
        cwd = checkout / prefix
        cwd.mkdir(parents=True, exist_ok=True)  # a project directory that did not exist at the base is empty there
        yield cwd, "%s at %s%s" % (ref, commit[:12], "" if prefix == Path(".") else ", under %s" % prefix)
    finally:
        _git(toplevel, "worktree", "remove", "--force", str(checkout))
        shutil.rmtree(root, ignore_errors=True)
        _git(toplevel, "worktree", "prune")


def _work(fields):
    return fields.get("kind") != DECISION_KIND


def _label(fields, labels):
    return (labels or {}).get(fields.get("id")) or "ticket %s" % fields.get("id")


def criteria_at_base(tickets, project, timeout_s, labels=None):
    """The machine criteria of these tickets that pass at the base commit, each a failure (BRIEF 8.3).

    Every command is run from the base checkout with `shell=True` under `timeout_s`, as `wayline accept`
    runs it; one that exits 0 before the work is done measures nothing. A command that times out did
    not pass.
    """
    commands = [(_label(fields, labels), command) for fields, _ in tickets if _work(fields)
                for command in (fields.get("acceptance") or {}).get("machine") or []]
    if not commands:
        return []
    failures = []
    with base_checkout(project) as (cwd, where):
        for label, command in commands:
            result = gates.run_shell(command, cwd, timeout_s, label=CHECK_LABEL)
            if result["exit_code"] == 0:
                failures.append("%s: the machine criterion `%s` passes at the base commit (%s), so it measures nothing"
                                % (label, command, where))
    return failures


def check_tickets(new, graph, project, *, base=True, timeout_s=None, declared=frozenset(), labels=None):
    """The plan-time Type-A checks of decision 10; returns the failures, each one line, empty when they pass.

    `new` is `[(fields, body)]`, the tickets checked field by field; `graph` is the frontmatter of every
    ticket the project will hold, `new` included, for the DAG and the docs rule. `declared` holds the ids
    of the `code` tickets that add public API (the plan's declaration, or the body's for a written graph),
    and `labels` names a ticket in the failures by its key rather than its id, for the planner. `base`
    False skips the run at the base commit, which a view that only reads a graph asks for. Every check
    runs whatever the ones before it found, so one return carries every failure.
    """
    project = Path(project).resolve()
    failures = []
    ids = {fields.get("id") for fields in graph}
    for fields, _ in new:
        try:
            check(fields, load_schema("ticket"), name=_label(fields, labels))
        except ValidationError as failure:
            failures.append(str(failure))
        try:
            filename(fields)
        except (TicketError, KeyError, TypeError) as failure:
            failures.append("%s: its title gives no file name (%s)" % (_label(fields, labels), failure))
    for fields in graph:
        for blocker in fields.get("blocked_by") or []:
            if blocker not in ids:
                failures.append("%s waits on ticket %s, which the graph does not hold" % (_label(fields, labels), blocker))
    try:
        build_graph([fields for fields in graph if fields.get("id") in ids])
    except (TicketError, KeyError, TypeError) as failure:
        failures.append("the graph is not a DAG: %s" % failure)
    for fields, _ in new:
        if not _work(fields):
            continue
        label = _label(fields, labels)
        if not _one_line(fields.get("demo")):
            failures.append("%s has no demo" % label)
        if not (fields.get("acceptance") or {}).get("machine"):
            failures.append("%s has no machine criterion in acceptance.machine" % label)
        touches = fields.get("touches") or []
        if not touches:
            failures.append("%s has no touch set" % label)
        for touch in touches:
            problem = touch_problem(touch, project)
            if problem:
                failures.append("%s: the touch set entry `%s` %s" % (label, touch, problem))
        if not isinstance(fields.get("difficulty"), int) or not 1 <= fields["difficulty"] <= 5:
            failures.append("%s has no difficulty from 1 to 5" % label)
        if not fields.get("context_pack"):
            failures.append("%s has no context pack" % label)
        if not fields.get("role") or fields.get("role") == UNASSIGNED:
            failures.append("%s has no role: no assignable role covers a %s ticket, and the harness needs one before it can run"
                            % (label, fields.get("kind")))
        if not isinstance(fields.get("skills"), list):
            failures.append("%s has no skills list (the librarian assigns it, empty when no skill matches)" % label)
    # A parked docs ticket documents nothing, so it does not satisfy the rule for the code ticket it waited on.
    docs = [fields for fields in graph if fields.get("kind") == "docs" and fields.get("status") != "parked"]
    for fields in graph:
        if fields.get("kind") == "code" and fields.get("id") in declared and fields.get("status") not in CLOSED:
            if not any(fields["id"] in (item.get("blocked_by") or []) for item in docs):
                failures.append("%s adds public API and no docs ticket waits on it" % _label(fields, labels))
    # The base commit is run whatever the checks above found, so the one return a plan gets carries
    # every failure at once: a planner that fixed the structure and only then learned that a criterion
    # passes at the base would have spent its return on half the news.
    if base:
        if timeout_s is None:
            timeout_s = policy_for(project).get("acceptance_timeout_s", 600)
        failures.extend(criteria_at_base(new, project, timeout_s, labels))
    return failures


def read_all(project):
    """Every ticket of the project with its body, by id."""
    found = {}
    for fields in read_tickets(project):
        found[fields["id"]] = (fields, read_ticket(tickets_dir(project) / filename(fields))[1])
    return found


def check_graph(project, base=True, timeout_s=None):
    """The plan-time checks on the graph as written: every open work ticket checked, the whole graph for the DAG and the docs rule.

    What the fixture of the `wayline-plan` skill and the tests run on a written graph, hand-written or
    cut. A ticket already `done` is not run at the base commit, since its criteria pass now by design.
    """
    project = Path(project).resolve()
    try:
        existing = read_all(project)
    except TicketError as failure:  # a file the harness cannot use is the first failure, and the only one it can name
        return [str(failure)]
    graph = [fields for fields, _ in existing.values()]
    new = [(fields, body) for fields, body in existing.values() if _work(fields) and fields["status"] == "open"]
    declared = {fields["id"] for fields, body in existing.values() if fields["kind"] == "code" and adds_public_api(body)}
    return check_tickets(new, graph, project, base=base, timeout_s=timeout_s, declared=declared)


# --- resolving a plan against the project ---------------------------------------------------------------


def _dependents(existing):
    """id -> the ids that wait on it directly, over the tickets as they stand."""
    found = {}
    for identifier, (fields, _) in existing.items():
        for blocker in fields["blocked_by"]:
            found.setdefault(blocker, []).append(identifier)
    return found


def superseded_by(cut, existing):
    """The ids this cut takes back, sorted: what is parked when the plan is written.

    A split supersedes the ticket it replaces alone. The other cuts supersede every work ticket that is
    `open` or `blocked` (`RECUT`), a revise also the tickets its sent-back answer parked, and with them
    every decision ticket of the planner's with `blocking: subgraph` that pauses nothing but tickets in
    that set: a question asked about work that is being cut again is asked again by the new plan when it
    still stands. A first plan takes back what it finds too, so tickets a crash left behind, or a plan
    that stopped before `plan.json` was written, never run beside the graph.
    """
    if cut.kind == "split":
        return [cut.of]
    taken = {identifier for identifier, (fields, _) in existing.items() if _work(fields) and fields["status"] in RECUT}
    taken.update(identifier for identifier in cut.sent_back if identifier in existing)
    dependents = _dependents(existing)
    for identifier, (fields, _) in existing.items():
        if (fields["kind"] == DECISION_KIND and fields.get("proposed_by") == PLANNER and fields.get("blocking") == "subgraph"
                and fields["status"] not in CLOSED and dependents.get(identifier) and set(dependents[identifier]) <= taken):
            taken.add(identifier)
    return sorted(taken)


class Prepared:
    """A plan resolved against the project: the tickets it becomes, the decisions to open, and what it supersedes."""

    def __init__(self):
        self.tickets = []      # (key, fields, body, tags), in the plan's order
        self.decisions = []    # (record, pause ids, origin)
        self.superseded = []   # the ids the cut parks
        self.repointed = {}    # id -> fields rewritten, the dependents of a split ticket
        self.failures = []
        self.declared = set()  # the ids of the code tickets that add public API, new and kept
        self.labels = {}       # id -> "T3 (ticket 12)"
        self.graph = []        # every ticket's frontmatter as the project will hold it, the decisions as placeholders


def prepare(record, project, existing, index, cut, start=None):
    """Resolve a `plan` record against the project: ids, references, the librarian's assignments, the bodies.

    `existing` is `read_all(project)`; `index` the registry; `start` the id the first ticket takes
    (`next_id` when None). What cannot be resolved is a failure the planner is returned; nothing here
    writes. A split's pieces inherit the split ticket's blockers, and its dependents are re-pointed at
    all of them.
    """
    project = Path(project).resolve()
    prepared = Prepared()
    failures = prepared.failures
    start = next_id(project) if start is None else start
    tickets = record.get("tickets") or []
    ids, seen = {}, set()
    for position, item in enumerate(tickets):
        key = item["key"]
        if key in seen:
            failures.append("the key %s is used more than once" % key)
        seen.add(key)
        ids.setdefault(key, start + position)
    prepared.superseded = superseded_by(cut, existing)
    superseded = set(prepared.superseded)
    split_of = existing[cut.of][0] if cut.kind == "split" and cut.of in existing else None
    if cut.kind == "split":
        if split_of is None:
            failures.append("the project has no ticket %s to split" % cut.of)
        elif split_of["status"] not in SPLITTABLE:
            failures.append("ticket %d is %s, so it is not split" % (cut.of, split_of["status"]))
        if len(tickets) < 2:
            failures.append("a split cuts at least two tickets; the plan holds %d" % len(tickets))
        for item in tickets:
            if split_of is not None and item["difficulty"] > split_of["difficulty"]:
                failures.append("%s is difficulty %d, harder than ticket %d (difficulty %d) it is cut from"
                                % (item["key"], item["difficulty"], cut.of, split_of["difficulty"]))
    elif not tickets:
        failures.append("a plan cuts at least one ticket; the plan holds none")

    def resolve(reference, label, verb):
        """One `blocked_by` or `pauses` entry as an id, or None with the failure named."""
        if not is_existing(reference):
            if reference not in ids:
                failures.append("%s %s %s, which is no key of this plan" % (label, verb, reference))
                return None
            return ids[reference]
        identifier = existing_id(reference)
        if identifier not in existing:
            failures.append("%s %s #%d, which the project does not hold" % (label, verb, identifier))
        elif identifier == cut.of:
            failures.append("%s %s #%d, the ticket this split replaces" % (label, verb, identifier))
        elif identifier in superseded:
            failures.append("%s %s #%d, which this plan re-cuts; name its replacement's key instead" % (label, verb, identifier))
        elif existing[identifier][0]["status"] == "parked":
            failures.append("%s %s #%d, which is parked and would hold it forever" % (label, verb, identifier))
        else:
            return identifier
        return None

    for item in tickets:
        key, identifier = item["key"], ids[item["key"]]
        label = "%s (ticket %d)" % (key, identifier)
        prepared.labels[identifier] = label
        blockers = set()
        for reference in item["blocked_by"]:
            resolved = resolve(reference, label, "waits on")
            if resolved is not None:
                blockers.add(resolved)
        if split_of is not None:
            blockers.update(split_of["blocked_by"])
        assignment = registry.librarian({"id": identifier, "kind": item["kind"]}, index, tags=item.get("tags"))
        fields = {
            "id": identifier, "title": _one_line(item["title"]), "kind": item["kind"], "difficulty": item["difficulty"],
            "status": "open", "blocked_by": sorted(blockers), "touches": [str(touch).strip() for touch in item["touches"]],
            "role": assignment["role"] or UNASSIGNED, "skills": list(assignment["skills"]),
        }
        if item.get("resources") is not None:
            fields["resources"] = dict(item["resources"])
        for name in ("inputs", "outputs"):
            if item.get(name):
                fields[name] = list(item[name])
        fields["acceptance"] = {"machine": list(item["acceptance"].get("machine") or []),
                                "quality": list(item["acceptance"].get("quality") or [])}
        if item.get("goal_metric") is not None:
            fields["goal_metric"] = dict(item["goal_metric"])
        fields["context_pack"] = list(item["context_pack"])
        fields["origin"] = _one_line(item["origin"])
        fields["proposed_by"] = PLANNER
        fields["demo"] = _one_line(item["demo"])
        if item.get("retry") and item["kind"] == "experiment":
            fields["retry"] = retry_steps(item["retry"])
        if item.get("adds_public_api") and item["kind"] == "code":
            prepared.declared.add(identifier)
        prepared.tickets.append((key, fields, ticket_body(item, cut.of), item.get("tags")))
    first_decision = start + len(tickets)
    placeholders = []
    for position, item in enumerate(record.get("decisions") or []):
        identifier = first_decision + position
        label = "decision %d (ticket %d)" % (position + 1, identifier)
        pauses = []
        for reference in item["pauses"]:
            resolved = resolve(reference, label, "pauses")
            if resolved is not None:
                pauses.append(resolved)
        if item["blocking"] == "subgraph" and not pauses:
            failures.append("%s pauses no ticket; a decision with blocking subgraph names the keys it pauses" % label)
        prepared.decisions.append((item, sorted(set(pauses)), item.get("origin")))
        placeholders.append({"id": identifier, "kind": DECISION_KIND, "status": "open", "difficulty": 1, "blocked_by": [],
                             "blocking": item["blocking"], "human_only": bool(item["human_only"]), "touches": [], "role": decisions.DECIDER_ROLE,
                             "skills": [], "pauses": sorted(set(pauses))})
    if split_of is not None:
        pieces = sorted(fields["id"] for _, fields, _, _ in prepared.tickets)
        for identifier, (fields, _) in existing.items():
            if cut.of in fields["blocked_by"] and fields["status"] not in CLOSED:
                prepared.repointed[identifier] = dict(fields, blocked_by=sorted((set(fields["blocked_by"]) - {cut.of}) | set(pieces)))
    graph = {}
    for identifier, (fields, body) in existing.items():
        graph[identifier] = dict(prepared.repointed.get(identifier, fields), status="parked" if identifier in superseded else fields["status"])
        # A kept code ticket that declared public API still needs its docs ticket, which this cut may have taken back.
        if fields["kind"] == "code" and identifier not in superseded and adds_public_api(body):
            prepared.declared.add(identifier)
    for _, fields, _, _ in prepared.tickets:
        graph[fields["id"]] = dict(fields)
    for placeholder in placeholders:
        for identifier in placeholder.pop("pauses"):
            if identifier in graph and graph[identifier]["status"] in decisions.PAUSABLE:
                graph[identifier] = dict(graph[identifier], blocked_by=sorted(set(graph[identifier]["blocked_by"]) | {placeholder["id"]}))
        graph[placeholder["id"]] = placeholder
    prepared.graph = [graph[identifier] for identifier in sorted(graph)]
    return prepared


def check_plan(record, project, existing, index, cut, start=None, base=True, timeout_s=None):
    """The schema, the resolution, and the plan-time checks on a returned plan: `(failures, prepared)`, every failure at once."""
    try:
        check(record, load_schema(PLAN_SCHEMA), name="the plan")
    except ValidationError as failure:
        return [str(failure)], None
    prepared = prepare(record, project, existing, index, cut, start=start)
    failures = list(prepared.failures)
    failures += check_tickets([(fields, body) for _, fields, body, _ in prepared.tickets], prepared.graph, project,
                              base=base, timeout_s=timeout_s, declared=prepared.declared, labels=prepared.labels)
    return failures, prepared


# --- the prompt -------------------------------------------------------------------------------------------


def _work_kinds():
    return [kind for kind in registry.ticket_kinds() if kind != DECISION_KIND]


def registry_text(index):
    """The roles and skills the librarian assigns from, as the planner needs them: which kinds have a role, which skills exist."""
    entries = [entry for entry in (index or {}).get("entries") or [] if entry.get("assignable")]
    roles = [entry for entry in entries if entry["kind"] == "role" and entry["applicability_tags"]["kinds"]]
    skills = [entry for entry in entries if entry["kind"] == "skill" and entry["applicability_tags"]["kinds"]]
    lines = ["# The registry", "",
             "The librarian assigns every ticket its role and its skills from research/registry.json, by the ticket's kind and "
             "tags. A kind no role covers cannot be cut: a ticket of one comes back to you as a failure.", "", "Roles, by the kinds they cover:"]
    covered = set()
    for entry in roles:
        kinds = entry["applicability_tags"]["kinds"]
        covered.update(kinds)
        lines.append("- `%s` for %s tickets: %s" % (entry["id"], ", ".join(kinds), _one_line(entry["capability_summary"])))
    missing = [kind for kind in _work_kinds() if kind not in covered]
    if missing:
        lines.append("- no role covers %s tickets; do not cut one, and say in `notes` what would need it" % ", ".join("`%s`" % kind for kind in missing))
    lines += ["", "Skills, by kind and tags:"]
    for entry in skills:
        tags = entry["applicability_tags"]
        wants = "; ".join("%s %s" % (dimension.replace("_", " "), ", ".join(tags[dimension]))
                          for dimension in ("data_types", "libraries", "venues") if tags[dimension])
        lines.append("- `%s` for %s tickets%s: %s" % (entry["id"], ", ".join(tags["kinds"]), " (wants " + wants + ")" if wants else "",
                                                       _one_line(entry["capability_summary"])))
    if not skills:
        lines.append("- none matches a ticket by kind yet, so every ticket's `skills` will be empty; that is expected")
    return "\n".join(lines)


def rubric_text(policy):
    """The difficulty rubric of BRIEF 8.4, with the rung of the rung ladder each level names (decision 16): its model, effort, and budget."""
    from wayline import conductor  # the conductor imports this module; the rung ladder is resolved there

    lines = ["# The difficulty rubric", "",
             "Difficulty names a rung of the rung ladder (policy.difficulty into policy.tiers), which sets the model, the effort, "
             "and the budget a ticket's worker gets:", ""]
    for level in range(1, 6):
        try:
            tier = conductor.tier_for(policy or {}, level)
        except conductor.ConductorError:
            lines.append("- %d: %s. No rung is set for this level." % (level, SIGNALS[level]))
            continue
        budget = (conductor.ladder(policy)[tier.rung - 1] or {}).get("budget", "?")
        lines.append("- %d: %s. Rung %d, %s at %s, a %s budget." % (level, SIGNALS[level], tier.rung, tier.model, tier.effort, budget))
    return "\n".join(lines)


def _journal_line(event):
    name, payload = event.get("event"), event.get("payload") or {}
    ticket = payload.get("ticket", event.get("ticket"))
    stamp = str(event.get("ts") or "")[:19]
    if name == TICKET_FAILED:
        return "- %s ticket %s failed (attempt %s, next: %s): %s" % (stamp, ticket, payload.get("attempt"), payload.get("next"),
                                                                   _one_line(payload.get("reason")))
    if name == TICKET_BLOCKED:
        return "- %s ticket %s is blocked: it had to write %s, outside its touch set" % (stamp, ticket, payload.get("path"))
    if name == TICKET_NEEDS_HUMAN:
        return "- %s ticket %s needs a person: %s" % (stamp, ticket, _one_line(payload.get("question")))
    if name == TICKET_DONE:
        return "- %s ticket %s is done" % (stamp, ticket)
    if name == STALL:
        return "- %s the run stalled after %s settling wave(s) without progress (action: %s)" % (stamp, payload.get("waves"), payload.get("action"))
    if name == DIFFICULTY_RAISED:
        return "- %s the default difficulty of %s tickets rose from %s to %s" % (stamp, payload.get("kind"), payload.get("from"), payload.get("to"))
    if name == FINDING:
        return "- %s finding %s from ticket %s%s: %s" % (stamp, payload.get("id"), ticket, " (negative)" if payload.get("negative") else "",
                                                       _one_line(payload.get("text")))
    if name == PROGRESS:
        return "- %s progress: %s = %s from ticket %s (%s)" % (stamp, payload.get("metric"), payload.get("value"), ticket,
                                                             "kept" if payload.get("kept") else "not kept")
    if name == DECISION:
        who = payload.get("decided_by") or "someone"
        subject = "on ticket %s" % ticket if ticket is not None else "of the grill or the owner"
        return "- %s decision %s by the %s: %s" % (stamp, subject, "owner" if who == "human" else who, _one_line(payload.get("answer")))
    return None


def journal_text(events, focus=None):
    """What the journal says a planner has to know: failures, blocks, stalls, findings, progress, and answers, one line each.

    `focus` is a ticket id: only its lines and the run's stalls, for a split. The last `JOURNAL_LINES`
    lines are kept, with the cut announced.
    """
    lines = []
    for event in events or ():
        line = _journal_line(event)
        if line is None:
            continue
        payload = event.get("payload") or {}
        ticket = payload.get("ticket", event.get("ticket"))
        if focus is not None and ticket != focus and event.get("event") != STALL:
            continue
        lines.append(line)
    heading = ["# What the journal says", "",
               "Read it before you cut: what failed and why, what a person or the decider answered, and what progressed. "
               "A plan that repeats what failed wastes a window."]
    if not lines:
        return "\n".join(heading + ["", "- nothing has run yet: no failure, no finding, no answer"])
    if len(lines) > JOURNAL_LINES:
        dropped = len(lines) - JOURNAL_LINES
        lines = ["- [wayline: %d earlier line(s) left out; open research/journal.jsonl for them]" % dropped] + lines[-JOURNAL_LINES:]
    return "\n".join(heading + [""] + lines)


def _fence(text):
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def graph_text(existing, superseded=(), of=None):
    """The graph as it stands, for a re-cut: every ticket on one line, marked kept, re-cut, parked, or split; the split ticket whole."""
    if not existing:
        return ""
    superseded = set(superseded)
    lines = ["# The graph as it stands", ""]
    if of is not None:
        lines.append("Every ticket the project holds. Ticket #%d is the one you split; the rest stay, and a piece waits on one of them as `#<id>`." % of)
    else:
        lines.append("Every ticket the project holds. Those marked re-cut are yours to cut again (they are parked when you return); "
                     "the rest stay, and a new ticket waits on one of them as `#<id>`.")
    lines.append("A ticket marked parked is closed for good: nothing waits on it, and a plan that names it fails its checks.")
    lines.append("")
    for identifier in sorted(existing):
        fields, body = existing[identifier]
        if identifier == of:
            mark = "split"
        elif identifier in superseded:
            mark = "re-cut"
        elif fields["status"] == "parked":
            mark = "parked"
        else:
            mark = "kept"
        parts = ["- #%d [%s, %s] %s d%s \"%s\"" % (identifier, fields["status"], mark, fields["kind"], fields.get("difficulty"), _one_line(fields["title"]))]
        if fields["blocked_by"]:
            parts.append("waits on %s" % ", ".join("#%d" % blocker for blocker in fields["blocked_by"]))
        if fields.get("touches"):
            parts.append("touches %s" % ", ".join("`%s`" % touch for touch in fields["touches"]))
        machine = (fields.get("acceptance") or {}).get("machine") or []
        if machine:
            parts.append("acceptance %s" % "; ".join("`%s`" % command for command in machine))
        if fields["kind"] == "code" and adds_public_api(body):
            parts.append("adds public API, so a docs ticket has to wait on it")
        if fields.get("demo"):
            parts.append("demo: %s" % _one_line(fields["demo"]))
        if fields.get("origin"):
            parts.append("origin %s" % fields["origin"])
        lines.append("; ".join(parts))
    if of is not None and of in existing:
        fields, body = existing[of]
        whole = dump_document(fields, body if body.startswith("\n") else "\n" + body)  # the file as the worker and the owner read it
        fence = _fence(whole)
        lines += ["", "## The ticket to split, #%d, whole" % of, "", fence, whole.rstrip("\n"), fence]
    return "\n".join(lines)


def plan_prompt(role, cut, harness, project, policy, records, index, journal, graph, cut_short=False):
    """The planner's plan prompt: what is asked, the cut, the records, the registry, the rubric, the journal, the graph, the protocol, the schema."""
    lines = ["# What you are asked for", "",
             "The ticket graph of this project: phase P4, plan. The harness numbers what you return, has the librarian assign a "
             "role and skills to every ticket, runs the plan-time checks, writes `research/tickets/NN-slug.md` and "
             "`research/graph.json`, opens a decision ticket for every choice you report open, and, by the project's autonomy, "
             "asks for the graph's confirmation before the conductor runs it.", "",
             "- the cut: %s" % cut.asked,
             "- autonomy: %s; radius: %s" % (harness.get("autonomy"), harness.get("radius"))]
    if cut.change:
        lines += ["", "# What to change", "",
                  "The graph as it was cut was not accepted. Change what this names, and keep what it does not:", "", cut.change.strip()]
    parts = ["\n".join(lines), records]
    if cut_short:
        parts.append("[wayline: the records were cut at the context cap; the paths below hold the rest.]")
    parts += [registry_text(index), rubric_text(policy), journal, graph]
    parts.append("\n".join([
        "# The paths you may open",
        "",
        "The project is `%s`; open these with the Read tool when a record points into them:" % project,
        "",
        "- `research/SPEC.md` and `research/spec.json`: the spec, inlined above when it fit",
        "- `research/DECISIONS.md`: what the owner settled, which binds every ticket",
        "- `research/INTAKE.md`: the intent, the data, the constraints, the radius",
        "- `research/refs/<slug>/dossier.json`, and `dossier.md` for a reference read in full",
        "- `research/tickets/<n>-<slug>.md`: the tickets the project holds, listed above when there are any",
        "- `research/journal.jsonl`: the whole journal, digested above",
        "- the project's own code, for the touch sets and the criteria: what exists, and what a ticket has to add",
    ]))
    parts.append(specify.protocol_for(role.protocol, "plan"))
    parts.append(worker.schema_section("# The plan", PLAN_SCHEMA, closing=[
        "",
        "Keys are `T<n>`; a `blocked_by` or `pauses` entry is a key of this plan or `#<id>` for a ticket the project holds. "
        "`role`, `skills`, `status`, and the ids are the harness's, not yours.",
    ]))
    return "\n\n".join(part.strip("\n") for part in parts if part and part.strip()) + "\n"


def _records(project, max_chars):
    """The records the plan reads, inlined: the spec whole, the goal, the query pack; `(text, cut short)`."""
    ledger = Ledger(project)

    def read(relative):
        try:
            return ledger.path(relative).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    entries = [
        ("research/SPEC.md", read(specify.SPEC_MD), "[wayline: there is no SPEC.md; run wayline specify]"),
        ("research/GOAL.json", read("GOAL.json"), "[wayline: no goal is stated]"),
        ("research/kb/query_pack.md", read("kb/query_pack.md"), "[wayline: there is no query pack; no reference was absorbed]"),
    ]
    return decider.inline_records(entries, max_chars, "Read them in this order; the spec is what the tickets implement, and nothing else.")


# --- one planner session -----------------------------------------------------------------------------------


class _Session(specify.PlannerSession):
    """The plan session and its one allowance of each return: an unreadable plan, and a plan that failed the checks."""

    error = PlanError
    schema = PLAN_SCHEMA
    sessions = SESSIONS
    what = "the planner's plan session"

    def plan(self, prompt, checker):
        """A plan that passed the schema and the checks, with each gate's one return spent as needed; `(record, prepared)`."""
        envelope = self.start(prompt)
        problem = self.unusable(envelope)
        if problem is not None:
            self.say("  the plan could not be read (%s); returned to the planner once" % problem)
            envelope = self.continue_with(RESUME_INVALID % problem)
            problem = self.unusable(envelope)
        if problem is not None:
            raise PlanError("the planner returned no plan the schema accepts: %s" % problem)
        return self.checked(envelope.structured_output, checker)

    def checked(self, record, checker, returned=False):
        """`record` once it passes the checks; a failing one goes back once, a second failure raises."""
        self.keep(record, "plan")
        failures, prepared = checker(record)
        if failures and not returned:
            self.say("  the plan failed %d check(s); returned to the planner once" % len(failures))
            envelope = self.continue_with(RESUME_CHECKS % "\n".join("- " + failure for failure in failures))
            problem = self.unusable(envelope)
            if problem is not None:
                raise PlanError("the planner's second plan could not be read: %s" % problem, failures)
            return self.checked(envelope.structured_output, checker, returned=True)
        if failures:
            raise PlanError("the plan failed its checks twice; nothing was written", failures)
        return record, prepared


# --- writing the graph -------------------------------------------------------------------------------------


def _park(ledger, fields, body, why):
    """One superseded ticket: `parked`, the reason under `## Superseded`, and `ticket_cancelled` by the planner."""
    text = body.rstrip("\n") + "\n\n" + SUPERSEDED_HEADING + "\n\n" + _one_line(why) + "\n"
    write_ticket(ledger, dict(fields, status="parked"), text)
    ledger.append_event(TICKET_CANCELLED, {"ticket": fields["id"], "by": BY_PLANNER}, ticket=fields["id"])


def park_open(project, ledger, why, only=None):
    """Park every work ticket that is `open` or `blocked` (or, with `only`, those of them named); returns the ids."""
    parked = []
    for identifier, (fields, body) in sorted(read_all(project).items()):
        if not _work(fields) or fields["status"] not in RECUT or (only is not None and identifier not in only):
            continue
        _park(ledger, fields, body, why)
        parked.append(identifier)
    return parked


def _digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def graph_sha(record, tickets, decisions_opened):
    """The name of one version of the graph: the plan record with the ids it became, hashed."""
    return _digest({"tickets": list(tickets), "decisions": list(decisions_opened), "plan": record})


def _ask(project, sha, tickets, opened, notify):
    """The confirmation ticket for the graph at `sha`: `blocking: all`, answerable by the decider under autonomous."""
    span = "tickets %d to %d" % (min(tickets), max(tickets)) if tickets else "no ticket"
    return decisions.open_decision(
        project, "Confirm the graph (%s at %s: %s%s) before the conductor runs it? Answer confirm, or revise: and what to change."
                 % (SUBJECT, sha, span, ", and decision tickets %s" % ", ".join(str(item) for item in opened) if opened else ""),
        options=[CONFIRM, REVISE], recommended=CONFIRM,
        evidence=["%s at %s: its plan-time checks passed, the base commit included" % (SUBJECT, sha),
                  "the plan as returned, with the ids it became: research/plan.json",
                  "a revise parks the graph at once; the next wayline plan cuts it again with the change"],
        blocking="all", human_only=False, reversible=True, proposed_by=PLANNER, origin=ORIGIN % sha, title=TITLE,
        context_pack=[SUBJECT, "research/plan.json"], notify=notify)["ticket"]


def write_plan(project, ledger, record, index, cut, *, expected=None, autonomy=None, session=None, notify=None):
    """Write what a checked plan becomes, under the ledger's lock; returns what was written.

    The plan is resolved again here, against the project as it stands now: a first plan is refused when
    a graph was cut since the session launched, and a re-cut when what it supersedes is not `expected`,
    the ids the planner was shown as re-cut, so two cuts of one graph at once cannot both land. The
    superseded tickets are parked first, so the frontier never holds a ticket and its replacement at
    once; then the new tickets are written and journaled (`ticket_created`, and `assigned` through the
    librarian), a split's dependents re-pointed, the decision tickets opened, the record kept as
    `research/plan.json` (not for a split, which inherits the graph's confirmation), `graph.json`
    regenerated, and, under `checkpoints` or `autonomous`, the confirmation opened in this same locked
    section, so no wave can find the new tickets without their gate.
    """
    project = Path(project).resolve()
    with ledger.lock():
        existing = read_all(project)
        if cut.kind == "plan" and read_plan(project) is not None:
            raise PlanError("a graph was cut since this session started (research/plan.json at %s); nothing was written"
                            % read_plan(project)["sha"])
        prepared = prepare(record, project, existing, index, cut)
        if prepared.failures:
            raise PlanError("the plan no longer fits the project as it stands now: %s" % "; ".join(prepared.failures), prepared.failures)
        if expected is not None and list(expected) != prepared.superseded:
            raise PlanError("the graph changed since the planner was launched: it was shown tickets %s as re-cut, and now %s would "
                            "be; nothing was written, so run wayline plan again"
                            % (", ".join(str(item) for item in expected) or "none", ", ".join(str(item) for item in prepared.superseded) or "none"))
        replacements = [fields["id"] for _, fields, _, _ in prepared.tickets]
        for identifier in prepared.superseded:
            fields, body = existing[identifier]
            if fields["status"] != "parked":
                _park(ledger, fields, body, cut.why_superseded(replacements))
        written = []
        for key, fields, body, tags in prepared.tickets:
            write_ticket(ledger, fields, body)
            ledger.append_event(TICKET_CREATED, {"ticket": fields["id"], "kind": fields["kind"], "proposed_by": PLANNER,
                                                 "origin": fields.get("origin"), "blocked_by": fields["blocked_by"]}, ticket=fields["id"])
            registry.assign(fields, index, ledger=ledger, tags=tags)
            written.append(fields["id"])
        for identifier, fields in sorted(prepared.repointed.items()):
            write_ticket(ledger, fields, existing[identifier][1])
        opened = []
        for position, (item, pauses, origin) in enumerate(prepared.decisions, 1):
            report = decisions.open_decision(
                project, item["question"], options=item.get("options") or (), recommended=item.get("recommended"),
                evidence=item.get("evidence") or (), blocking=item["blocking"], human_only=bool(item.get("human_only")),
                pauses=pauses, proposed_by=PLANNER, origin="plan %s: %s" % (_digest(record), origin or "decision %d" % position),
                context_pack=["research/SPEC.md"], notify=notify)
            opened.append(report["ticket"])
        outcome = {"cut": cut.kind, "of": cut.of, "tickets": written, "decisions": opened, "superseded": list(prepared.superseded),
                   "repointed": sorted(prepared.repointed), "notes": list(record.get("notes") or []), "sha": None, "gate": None}
        if cut.kind != "split":
            outcome["sha"] = graph_sha(record, written, opened)
            ledger.write_json(PLAN_JSON, {
                "sha": outcome["sha"], "cut_at": now_ts(), "cut": cut.kind, "change": cut.change, "session_id": session,
                "tickets": written, "decisions": opened, "superseded": list(prepared.superseded), "sent_back": None, "plan": record,
            })
            if autonomy in (CHECKPOINTS, AUTONOMOUS):
                outcome["gate"] = _ask(project, outcome["sha"], written, opened, notify)
        events, _ = ledger.read_events()
        refresh_graph(project, ledger=ledger, events=events, force=True)
    return outcome


# --- where the graph stands ------------------------------------------------------------------------------


def read_plan(project):
    """`research/plan.json`, or None when no plan was cut (or the file cannot be read)."""
    try:
        record = Ledger(project).read_json(PLAN_JSON)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("sha") else None


def _confirmation_ticket(project, sha):
    for ticket in read_tickets(project):
        if ticket["kind"] == DECISION_KIND and ticket.get("origin") == ORIGIN % sha:
            return ticket
    return None


def _feedback(answer, rationale):
    change = specify.what_to_change(answer)
    if change == specify.what_to_change(REVISE):
        change = ""  # the option's placeholder, as the decider may pick it: the change is in the rationale
    rationale = str(rationale or "").strip()
    if rationale:
        change = (change + " (the reason given: %s)" % rationale).strip()
    return change or "no change was named; read the answer on the ticket"


def plan_state(project, events=None):
    """Where the graph stands, read from `plan.json`, the tickets, and the journal.

    `state` is one of `none` (no plan was cut), `unasked` (cut, no confirmation asked or given), `pending`
    (a confirmation ticket waits), `confirmed`, or `revise` (sent back with what to change, which
    `feedback` holds, until the next cut). `sha`, `ticket`, `answer`, `decided_by`, `cut`, `tickets`,
    `decisions`, `sent_back`, and `phase` go with it. A graph once sent back stays `revise` whatever is
    answered later: its tickets are parked, and only a re-cut brings a graph back.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    if events is None:
        events, _ = ledger.read_events()
    state = {"state": "none", "sha": None, "ticket": None, "answer": None, "decided_by": None, "feedback": None, "cut": None,
             "tickets": [], "decisions": [], "sent_back": None, "phase": specify.current_phase(events)}
    record = read_plan(project)
    if record is None:
        return state
    sha = record["sha"]
    state.update(sha=sha, cut=record.get("cut"), tickets=list(record.get("tickets") or []), decisions=list(record.get("decisions") or []),
                 sent_back=record.get("sent_back"))
    ticket = _confirmation_ticket(project, sha)
    state["ticket"] = ticket["id"] if ticket is not None else None
    answer = None
    prefix = ANSWER_PREFIX % sha
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") != DECISION:
            continue
        text = str(payload.get("answer") or "")
        if payload.get("ticket") is None and text.startswith(prefix):
            answer = dict(payload, answer=text[len(prefix):])
        elif ticket is not None and payload.get("ticket") == ticket["id"]:
            answer = dict(payload)
    if answer is None and ticket is not None:
        written = answer_section(read_ticket(tickets_dir(project) / filename(ticket))[1])
        if written is not None:
            answer = {"answer": written, "decided_by": "human"}
    if state["sent_back"]:
        sent = state["sent_back"].get("answer")
        rationale = answer.get("rationale") if answer is not None and answer.get("answer") == sent else None
        state.update(state="revise", answer=sent, decided_by=(answer or {}).get("decided_by") if answer is not None and answer.get("answer") == sent else None,
                     feedback=_feedback(sent, rationale))
        return state
    if answer is None:
        state["state"] = "pending" if ticket is not None else "unasked"
        return state
    state.update(answer=answer["answer"], decided_by=answer.get("decided_by"))
    if specify.confirms(answer["answer"]):
        state["state"] = "confirmed"
        return state
    state["state"], state["feedback"] = "revise", _feedback(answer["answer"], answer.get("rationale"))
    return state


def _send_back(project, ledger, why, ticket, answer):
    """Park the graph's open tickets, record the sent-back answer in `plan.json`, and refresh the graph; returns the ids parked."""
    with ledger.lock():
        parked = park_open(project, ledger, why)
        record = read_plan(project)
        if record is not None:
            record["sent_back"] = {"ticket": ticket, "answer": answer, "parked": parked}
            ledger.write_json(PLAN_JSON, record)
        if parked:
            refresh_graph(project, ledger=ledger)  # the stored graph says at once that nothing of it can launch
    return parked


def graph_sent_back(project, ledger, fields, answer):
    """The graph's open tickets, parked because the answer to its confirmation asks for a change; `[]` for any other answer.

    Every path an answer takes calls this under the ledger's lock (`project.graph_answered`): the
    conductor closes an answered decision ticket at its next wave whatever the answer says, and a
    `blocking: all` ticket that is closed holds nothing, so a graph the owner or the decider sent back
    is parked here, at once, and `plan.json` records it for the next `wayline plan` to cut again.
    """
    fields = fields or {}
    origin = str(fields.get("origin") or "")
    if fields.get("kind") != DECISION_KIND or not origin.startswith(ORIGIN_PREFIX) or specify.confirms(answer):
        return []
    why = ("Sent back: the answer to decision ticket %d, \"%s\", asks for a change; the next wayline plan cuts the graph again."
           % (fields["id"], _one_line(answer)))
    return _send_back(Path(project).resolve(), ledger, why, fields["id"], answer)


def advance(project, events=None):
    """Journal `phase P4 -> P5` once the graph is confirmed; returns whether it moved."""
    project = Path(project).resolve()
    ledger = Ledger(project)
    if events is None:
        events, _ = ledger.read_events()
    if plan_state(project, events)["state"] != "confirmed":
        return False
    now = specify.current_phase(events)
    if now is not None and specify.PHASES.index(now) >= specify.PHASES.index(EXECUTE_PHASE):
        return False
    return specify.move_phase(ledger, events, EXECUTE_PHASE)


# --- cutting -----------------------------------------------------------------------------------------------


def cut_graph(project, cut, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None, say=lambda text: None,
              pre_check=True):
    """Launch the planner for `cut`, check what it returns, and write it; returns what was written.

    A first plan needs the spec confirmed; a split needs a ticket that can be split. The registry is
    rebuilt first, since the librarian assigns from it. Raises `PlanError` when nothing can be cut or the
    plan failed its checks twice, `gates.UsageLimited` when a window refused the session, and
    `gates.FableHeld` when the planner waits for Fable's weekly window.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    harness = read_harness(project)
    events, _ = ledger.read_events()
    existing = read_all(project)
    if cut.kind == "plan":
        state = specify.spec_state(project, events)
        if state["state"] != "confirmed":
            raise PlanError("the spec is %s, and the graph is cut from a confirmed spec; run wayline specify first" % state["state"])
        problems = specify.check_spec(project)
        if problems:
            raise PlanError("research/SPEC.md fails its checks, so it cannot be cut: %s" % "; ".join(problems), problems)
    if cut.kind == "split":
        found = existing.get(cut.of)
        if found is None:
            raise PlanError("%s has no ticket %s to split" % (project, cut.of))
        if not _work(found[0]):
            raise PlanError("ticket %d is a decision ticket, which is answered rather than split" % cut.of)
        if found[0]["status"] not in SPLITTABLE:
            raise PlanError("ticket %d is %s, so it is not split" % (cut.of, found[0]["status"]))
    index = registry.build(project, harness_root=harness_root, events=events, pre_check=pre_check)
    session = _Session(project, harness_root, policy, fall_back, say)
    records, cut_short = _records(project, specify.context_cap(policy, session.model))
    superseded = superseded_by(cut, existing)
    prompt = plan_prompt(session.role, cut, harness, project, policy, records, index, journal_text(events, cut.of),
                         graph_text(existing, superseded, of=cut.of), cut_short=cut_short)
    say("cutting the graph (%s): the planner on %s at %s%s" % (cut.kind, session.model, session.effort,
                                                             " in place of fable" if session.fallback_from else ""))

    def checker(returned):
        return check_plan(returned, project, existing, index, cut, timeout_s=policy.get("acceptance_timeout_s"))

    returned, _ = session.plan(prompt, checker)
    outcome = write_plan(project, ledger, returned, index, cut, expected=superseded, autonomy=harness.get("autonomy"),
                         session=session.session_id, notify=notify)
    outcome.update(model=session.model, fallback_from=session.fallback_from, session_id=session.session_id)
    say("  wrote %d ticket(s)%s%s%s" % (len(outcome["tickets"]),
                                        " and %d decision ticket(s)" % len(outcome["decisions"]) if outcome["decisions"] else "",
                                        "; parked %s" % ", ".join(str(item) for item in outcome["superseded"]) if outcome["superseded"] else "",
                                        "; opened decision ticket %d, \"%s\", blocking all" % (outcome["gate"], TITLE) if outcome["gate"] else ""))
    return outcome


# --- the confirmation ---------------------------------------------------------------------------------------


def _decide(project, identifier, harness_root, policy, fall_back, notify, say):
    """Under autonomous: the decider on the confirmation ticket, now. Returns the outcome's line, or why it waits."""
    for fields, body, record in decisions.for_the_decider(project):
        if fields["id"] != identifier:
            continue
        try:
            outcome = decider.decide_ticket(project, fields, body, record, harness_root=harness_root, policy=policy,
                                            fall_back=fall_back, notify=notify)
        except gates.FableHeld as held:
            return "the decider waits for Fable's weekly window (until %s)" % held.resets_at
        except gates.UsageLimited as refused:
            return "the usage limit refused the decider: %s" % refused
        return outcome.line
    return "decision ticket %d is not the decider's to take now" % identifier


def confirm(project, text, rationale=None, by="cli"):
    """The owner's answer to the graph's confirmation: through its ticket when one is open, else journaled with no ticket.

    An answer that does not confirm parks the graph's open tickets, as one given through the ticket
    does. Returns the state after the answer (and the phase moved when it confirms). Refused when no
    cut graph waits for an answer, and once the graph was sent back: its tickets are parked, and only
    `wayline plan` brings a graph back.
    """
    project = Path(project).resolve()
    text = str(text or "").strip()
    if not text:
        raise PlanError("an answer to the graph's confirmation needs some text")
    state = plan_state(project)
    if state["state"] == "revise":
        raise PlanError("the graph was sent back (%s) and its tickets are parked, so there is nothing to confirm; %s"
                        % (state["feedback"], _next(state)))
    if state["state"] not in ("unasked", "pending"):
        raise PlanError("the graph is %s, so there is nothing to confirm; %s" % (state["state"], _next(state)))
    ledger = Ledger(project)
    if state["state"] == "pending":
        answer_ticket(project, state["ticket"], text, rationale=rationale, by=by)
    else:
        with ledger.lock():
            ledger.append_event(DECISION, {"ticket": None, "answer": ANSWER_PREFIX % state["sha"] + text, "decided_by": "human",
                                           "rationale": rationale, "confidence": None})
            if not specify.confirms(text):
                _send_back(project, ledger, "Sent back by the owner (wayline plan revise: \"%s\"); the next wayline plan cuts the graph "
                           "again." % _one_line(text), None, text)
    advance(project)
    return plan_state(project)


def _next(state):
    return {
        "none": "run wayline plan to cut the graph from the confirmed spec",
        "unasked": "answer with wayline plan confirm, or wayline plan revise \"<what to change>\"",
        "pending": "answer decision ticket %s with wayline answer %s confirm (or revise: ...), or in the dashboard"
                   % (state.get("ticket"), state.get("ticket")),
        "confirmed": "next: wayline run (wayline plan --replan re-cuts the open tickets, --split <id> replaces one)",
        "revise": "run wayline plan to cut the graph again with the change asked for",
    }[state["state"]]


# --- the verb ------------------------------------------------------------------------------------------------


def plan(project, *, replan=False, split=None, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None, out=None,
         pre_check=True):
    """Do whatever the graph owes next: cut, re-cut, split, ask, decide, or advance. Returns the report.

    The report is `{project, autonomy, cut, did, written, stopped, failures, state}`; `stopped` names what
    ended the call early (a failed gate, a usage window, the hold on Fable's window) and `failures` the
    checks behind it; `written` is what the cut wrote.
    """
    project = Path(project).resolve()
    say = (lambda text: print(text, file=out)) if out is not None else (lambda text: None)
    ledger = Ledger(project)
    harness = read_harness(project)
    autonomy = harness.get("autonomy")
    report = {"project": str(project), "autonomy": autonomy, "cut": None, "did": [], "written": None, "stopped": None, "failures": []}
    journal_written_answers(project, ledger)
    state = plan_state(project)
    if split is not None:
        cut = Cut("split", of=split)
    elif replan:
        cut = Cut("replan")
    elif state["state"] == "revise":
        cut = Cut("revise", change="The %s asked: %s" % ("owner" if state["decided_by"] in ("human", None) else state["decided_by"],
                                                        state["feedback"]),
                  sent_back=list((state["sent_back"] or {}).get("parked") or []))
    elif state["state"] == "none":
        cut = Cut("plan")
    else:
        cut = None
    report["cut"] = cut.kind if cut is not None else None
    if cut is not None:
        try:
            outcome = cut_graph(project, cut, harness_root=harness_root, policy=policy, fall_back=fall_back, notify=notify, say=say,
                                pre_check=pre_check)
        except PlanError as failure:
            report.update(stopped=str(failure), failures=failure.failures)
        except gates.FableHeld as held:
            report["stopped"] = "Fable's weekly window is held until %s and the consent waits: %s" % (held.resets_at, held)
        except gates.UsageLimited as refused:
            report["stopped"] = "the usage limit refused a session: %s" % refused
        except (gates.GateError, worker.LaunchError, worker.RoleError, registry.RegistryError, TicketError, ProjectError) as failure:
            report["stopped"] = str(failure)
        else:
            report["written"] = outcome
            report["did"].append("%s: wrote %d ticket(s)%s%s on %s%s" % (
                cut.kind, len(outcome["tickets"]),
                " and %d decision ticket(s)" % len(outcome["decisions"]) if outcome["decisions"] else "",
                ", parked %s" % ", ".join(str(item) for item in outcome["superseded"]) if outcome["superseded"] else "",
                outcome.get("model") or "an unnamed model", " in place of fable" if outcome.get("fallback_from") else ""))
            if outcome.get("gate"):
                report["did"].append("opened decision ticket %d, \"%s\", blocking all" % (outcome["gate"], TITLE))
        state = plan_state(project)
    if state["state"] == "unasked" and report["stopped"] is None:
        if autonomy == INTERACTIVE:
            report["did"].append("the graph waits for the owner's word in this session")
        else:  # a plan.json written without its gate, which no cut of this version leaves behind
            identifier = _ask(project, state["sha"], state["tickets"], state["decisions"], notify)
            refresh_graph(project, ledger=ledger)
            report["did"].append("opened decision ticket %d, \"%s\", blocking all" % (identifier, TITLE))
        state = plan_state(project)
    if state["state"] == "pending" and autonomy == AUTONOMOUS and report["stopped"] is None:
        report["did"].append("the decider on ticket %d: %s" % (state["ticket"], _decide(
            project, state["ticket"], harness_root, policy, fall_back, notify, say)))
        state = plan_state(project)
    if advance(project):
        report["did"].append("the graph is confirmed; the phase moved to %s" % EXECUTE_PHASE)
        state = plan_state(project)
    report["state"] = state
    return report


def replan(project, **context):
    """`wayline plan --replan`: re-cut the open tickets after a stall (what the conductor calls, ticket 38)."""
    return plan(project, replan=True, **context)


def split(project, identifier, **context):
    """`wayline plan --split <id>`: replace one failed ticket with smaller ones (the `split` rung of the ladder, ticket 38)."""
    return plan(project, split=identifier, **context)


def _ticket_lines(project, ids):
    """One line per cut ticket: the id, the kind, the difficulty, the role, the title, and what it waits on."""
    lines = []
    found = {fields["id"]: fields for fields in read_tickets(project)}
    for identifier in ids:
        fields = found.get(identifier)
        if fields is None:
            continue
        waits = " (waits on %s)" % ", ".join(str(item) for item in fields["blocked_by"]) if fields["blocked_by"] else ""
        lines.append("    %3d  %-10s d%s  %-12s %s%s" % (identifier, fields["kind"], fields.get("difficulty"), fields.get("role") or "?",
                                                        fields["title"], waits))
    return lines


def render_report(report):
    """The text `wayline plan` prints."""
    state = report["state"]
    lines = ["plan  %s  (autonomy %s)" % (report["project"], report["autonomy"])]
    lines += ["  " + line for line in report["did"]] or ["  nothing to do"]
    written = report.get("written")
    if written:
        lines += _ticket_lines(report["project"], written["tickets"] + written["decisions"])
        if written.get("repointed"):
            lines.append("  re-pointed at the pieces: %s" % ", ".join(str(item) for item in written["repointed"]))
        for note in written.get("notes") or []:
            lines.append("  the planner notes: %s" % note)
    if report["stopped"]:
        lines.append("  stopped: %s" % report["stopped"])
        lines += ["    " + line for failure in report["failures"] for line in str(failure).split("\n")]
    lines.append("  the graph: %s%s%s" % (state["state"], " at %s" % state["sha"] if state["sha"] else "",
                                          ", answered by the %s: %s" % (state["decided_by"], state["answer"]) if state["answer"] else ""))
    if state["phase"]:
        lines.append("  phase: %s" % state["phase"])
    if state["state"] == "unasked" and report["autonomy"] == INTERACTIVE:
        lines += ["", "Read the graph back to the owner (wayline status prints the frontier) and record their word with:",
                  "  wayline plan confirm [--rationale \"<why>\"]",
                  "  wayline plan revise \"<what to change>\""]
    else:
        lines.append("  " + _next(state))
    return "\n".join(lines)


def plan_command(args):
    args = list(args)
    if args and args[0] in ("confirm", "revise"):
        return _answer_command(args[0], args[1:])
    parser = argparse.ArgumentParser(
        prog="wayline plan",
        description="phase P4: cut research/SPEC.md into research/tickets/ and graph.json with the planner, assign a role and "
                    "skills to every ticket from the registry, run the plan-time checks, and ask for the graph's confirmation by "
                    "the project's autonomy; run again, it does whatever the graph owes next. `wayline plan confirm` and "
                    "`wayline plan revise` record the owner's answer.")
    parser.add_argument("--replan", action="store_true", help="re-cut every open or blocked ticket from what the journal says failed")
    parser.add_argument("--split", type=int, metavar="ID", help="replace one failed ticket with smaller ones that inherit its blockers and dependents")
    parser.add_argument("--no-pre-check", action="store_true", help="skip the free structural pre-check when the registry is rebuilt")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.replan and options.split is not None:
        print("wayline plan: --replan and --split are two different cuts; give one", file=sys.stderr)
        return 2
    try:
        project = find_project(options.project)
        report = plan(project, replan=options.replan, split=options.split, out=None if options.json else sys.stdout,
                      pre_check=not options.no_pre_check)
    except (ProjectError, LedgerError, TicketError, PlanError, OSError) as failure:
        print("wayline plan: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else render_report(report))
    return 1 if report["stopped"] else 0


def _answer_command(verb, args):
    parser = argparse.ArgumentParser(
        prog="wayline plan %s" % verb,
        description="record the owner's %s of the graph: through its confirmation ticket when one is open, else journaled"
                    % ("confirmation" if verb == "confirm" else "request for a change"))
    if verb == "revise":
        parser.add_argument("change", help="what to change, in a sentence")
    parser.add_argument("--rationale", help="the owner's reason, when they gave one")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    text = CONFIRM if verb == "confirm" else "revise: " + options.change
    try:
        project = find_project(options.project)
        state = confirm(project, text, rationale=options.rationale)
    except PlanError as failure:
        print("wayline plan %s: %s" % (verb, failure), file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, TicketError, OSError) as failure:
        print("wayline plan %s: %s" % (verb, failure), file=sys.stderr)
        return 1
    print("the graph: %s at %s; %s" % (state["state"], state["sha"], _next(state)))
    return 0
