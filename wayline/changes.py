"""Feedback, change records, and harness tickets (Implementation Decisions 12 and 16). Built by ticket 45.

The owner says what should have gone better and the harness changes itself under test. `wayline.evolve`
(ticket 46) moves harness versions; this module is the loop in front of it.

**Intake.** Feedback arrives three ways, and each is a file under `research/feedback/` and one `feedback`
event with its source: `wayline feedback "<text>"` and `wayline evolve "<text>"` (`cli`), the dashboard's
feedback form (`dashboard`), and a file the owner dropped into the directory (`file`, journaled by
`take_dropped` the next time anything looks). An item's id is its file's stem. `research/evolve.json` holds
what the evolver has read and what it made of each item, so `pending_feedback` is what no session has read.

**The retrospective.** After every `run_ended`, `file_retrospective` reads the journal since the last one:
failures, escalations, stalls, rework, turns per closed ticket, skills below the registry's median first-time
pass rate, quarantined fixtures, and the local skills worth promoting. When any of it is worth a session the
text is filed as one more feedback item, source `retrospective`, so the evolver reads it as it reads the
owner's. A run that launched only harness tickets earns none, or the loop would feed itself.

**The evolver.** `evolve` launches the `evolver` role through the worker launcher (seam 1) on
`policy.roles.evolver` (`fable`, `xhigh`), Opus in Fable's place when the hold says so, with `change_list.json`
as its schema and, in its prompt, the pending items, the journal numbered by line, the records already open,
the registry, and the policy. The session writes nothing. `check_list` is its Type-A gate: every record
answers an item it was shown, cites journal lines the journal holds, names a target its mechanism and scope
allow, and names a fixture that does not exist yet; every item is answered or dismissed. A failing list goes
back once with every failure; a second failure marks the items read, so no wave launches the session again
over them, and raises.

**Change records and harness tickets.** `file_changes` gives each record its id and status, keeps it as
`research/changes/<id>.json` under the `change` schema, journals `change_record`, and files one `harness`
ticket for it: the librarian assigns the role and skills, the touch set is the record's target and its
fixture's directory, and the origin `change <id>` is how the conductor finds the record again. A local change
targets the project's `.claude/skills/wayline-<name>/`, `.claude/agents/<role>.md`, or `harness.json`, and
runs like any ticket, on the project's `main`. A global change targets a path in the harness repository and
works on the branch `evolve/<id>`, checked out as a worktree of the harness repository under
`~/.wayline/worktrees/`. Under autonomy `autonomous` a global change is never applied: it is kept as
`proposed`, no ticket is filed, and `REPORT.md` lists it (`proposal_lines`) with the command that applies it,
`wayline evolve --apply <id>`, which is the owner's.

**The ladder.** A record whose mechanism is `policy` and whose keys include `tiers` or `difficulty` changes
the rung ladder: it is always `risk: high`, and a decision ticket of class `ladder` holds its harness ticket.
The class is human-only unless the ladder consent is `auto` (`project.human_only_classes_now`), so under
`autonomous` the decider takes it only then. `ladder_answered`, called from every path an answer takes,
parks the harness ticket at once when the answer does not approve.

**The proof.** A fixture born from feedback encodes the desired behaviour, so `prove` runs it twice before the
conductor integrates a harness ticket: on the changed subject, where it must pass, and on the subject as it
was, where it must fail. A local role override that did not exist runs there as the harness's role it replaces,
and a local skill that did not exist runs as no skill (`_old_stand_in`), so the old behaviour is shown failing;
any other subject that did not exist fails without a run. Both runs happen on a copy, so a change that is
not proven leaves nothing behind; a proven one gets the passing run as its baseline, which is what makes a
model-authored skill assignable to the registry.

**A global change's branch.** `check_global` adds the changelog paragraph, commits, and runs the harness tests
and the full fixture suite on the branch; the record then waits as `awaiting_owner`. `settle_global`, run by
every `wayline evolve`, tags the harness `main` once it holds the branch (`evolve.release`, ticket 46) and
marks the record `applied`.
"""

import argparse
import os
import json
import re
import shutil
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from wayline import HARNESS_ROOT, decisions, evolve as versions, fixtures, gates, pacing, registry, specify, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import (
    CHANGE_RECORD, DIFFICULTY_RAISED, FEEDBACK, K_FIXTURE, K_ID, K_MECHANISM, K_SCOPE_KIND, K_SOURCE, RUN_ENDED, STALL,
    TICKET_CANCELLED, TICKET_CREATED, TICKET_DONE, TICKET_FAILED, TICKET_LAUNCHED, TICKET_NEEDS_HUMAN, TICKET_RERUN, TICKET_RESULT,
    TICKET_RESUMED, VERDICT, Ledger, LedgerError, now_ts,
)
from wayline.project import ProjectError, find_project, policy_for, read_harness
from wayline.tickets import (
    DECISION as DECISION_KIND, TicketError, filename, next_id, read_ticket, read_tickets, refresh_graph, tickets_dir, write_ticket,
)

__all__ = [
    "ChangeError", "Proof", "EVOLVER", "LIST_SCHEMA", "CHANGE_SCHEMA", "FEEDBACK_DIR", "CHANGES_DIR", "EVOLVE_JSON", "SOURCES",
    "RETROSPECTIVE", "FIGURE", "file_from_figure", "HARNESS_KIND", "LADDER_KEYS", "STATUSES", "file_feedback", "take_dropped", "pending_feedback", "read_state",
    "mark_read", "claim", "release", "evolver_tier", "evolves_on_fable", "is_ladder_change", "target_problem", "check_list", "touches_for",
    "read_changes", "read_change", "change_of", "global_change", "file_changes", "apply_proposal", "ladder_answered", "approves",
    "evolve_prompt", "evolve", "retrospective", "render_retrospective", "notable", "file_retrospective", "after_run",
    "proposal_lines", "prove", "global_worktree", "add_global_worktree", "remove_global_worktree", "check_global", "settle_global",
    "set_status", "changes_view", "render_report", "feedback_command", "evolve_command",
]

EVOLVER = "evolver"
LIST_SCHEMA = "change_list"             # what the session returns
CHANGE_SCHEMA = "change"                # what research/changes/<id>.json holds
FEEDBACK_DIR = "feedback"               # research/feedback/<id>.md, and whatever the owner drops there
CHANGES_DIR = "changes"                 # research/changes/<id>.json
EVOLVE_JSON = "evolve.json"             # research/evolve.json: what the evolver has read, and what it made of each item
SESSIONS = "sessions/evolve"            # research/sessions/evolve/<n>
EVOLVER_BUDGET = "large"                # policy.budget: the evolver is a large-budget role (policy.roles, fable xhigh)
CLI, DASHBOARD, FILE, RETROSPECTIVE = "cli", "dashboard", "file", "retrospective"
FIGURE = "figure"                       # the figure role's traps for the plot index (ticket 50), filed by code like the retrospective
SOURCES = (CLI, DASHBOARD)              # the sources a person files under; `file` is what `take_dropped` finds
HARNESS_KIND = "harness"
BY_EVOLVE = "evolve"                    # `proposed_by` on a harness ticket, and `by` on the one a refusal parks
LADDER_KEYS = ("tiers", "difficulty")   # the policy keys that are the rung ladder (decision 16)
LADDER_CLASS = "ladder"
LOCAL, GLOBAL = "local", "global"
OPEN, PROPOSED, AWAITING_OWNER, APPLIED, DECLINED = "open", "proposed", "awaiting_owner", "applied", "declined"
STATUSES = (OPEN, PROPOSED, AWAITING_OWNER, APPLIED, DECLINED)
AUTONOMOUS = "autonomous"
BRANCH = "evolve/%s"
ORIGIN = "change %s"                  # a harness ticket's origin; a global one adds its branch (`tickets.works_in_the_harness`)
GLOBAL_ORIGIN = "change %s: evolve/%s"
LADDER_ORIGIN = "change %s: ladder"
APPROVE, DECLINE = "approve", "decline"
APPROVING = ("approve", "approved", "yes", "apply", "confirm", "confirmed", "ok", "okay")
SLUG_WORDS = 5
TITLE_WORDS = 8
FEEDBACK_MAX_CHARS = 20000              # what one item hands the evolver; a longer file is cut, and the cut is said
JOURNAL_LINES = 400                     # the journal digest keeps this many of its last lines
PAYLOAD_CHARS = 240
DEMO_CHARS = 240                        # a harness ticket's one-line demo: the first sentence of what is desired
EXCERPT_CHARS = 200                     # what the dashboard's view shows of an item
# What the digest leaves out: events that say nothing about how a session behaved.
QUIET = ("pacing", "wave", "notified", "manifest", "consulted", "report_rendered", "job_waiting")
# The reasons a run ends that the owner chose; the retrospective is filed, and no session is launched on top of a stop.
OWNER_ENDED = ("stopped", "switched")
TURNS_LISTED = 5

_WORD_RE = re.compile(r"[a-z0-9]+")
_ORIGIN_RE = re.compile(r"^change ([0-9]{3}-[a-z0-9-]+)(?:: evolve/[0-9]{3}-[a-z0-9-]+)?\Z")
_RECORD_ID_RE = re.compile(r"^[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_LADDER_ORIGIN_RE = re.compile(r"^change ([0-9]{3}-[a-z0-9-]+): ladder\Z")
_LOCATOR_RE = re.compile(r"^research/journal\.jsonl#L([0-9]+)\Z")
_LOCAL_SKILL_RE = re.compile(r"^\.claude/skills/wayline-[a-z0-9][a-z0-9-]*/\Z")
_LOCAL_ROLE_RE = re.compile(r"^\.claude/agents/([a-z][a-z0-9-]*)\.md\Z")

RESUME_INVALID = (
    "The list you returned could not be read: %s. Return the whole list again through the structured output, as the "
    "change_list schema asks."
)
RESUME_CHECKS = (
    "The harness's checks failed on the list you returned:\n\n%s\n\nChange what they name, keep the rest, and return the "
    "whole list again through the structured output."
)


class ChangeError(ValueError):
    """Feedback the harness cannot file, or a change record it refuses, with what to do instead."""

    def __init__(self, message, failures=()):
        super().__init__(message)
        self.failures = list(failures)


# --- intake -------------------------------------------------------------------------------------------


def _slug(text, words=SLUG_WORDS):
    return "-".join(_WORD_RE.findall(str(text).lower())[:words])


def _one_line(text):
    return " ".join(str(text or "").split())


def _first_sentence(text, limit=DEMO_CHARS):
    """The first sentence of a paragraph, for a ticket's one-line `demo`; the body carries the whole of it."""
    line = _one_line(text)
    match = re.match(r"^(.+?[.!?])(?:\s|\Z)", line)
    sentence = match.group(1) if match else line
    return sentence if len(sentence) <= limit else sentence[:limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."


def _journaled(events):
    """Every `feedback` the journal holds, as `{id: source}`, in journal order."""
    return {(event.get("payload") or {}).get(K_ID): (event.get("payload") or {}).get(K_SOURCE)
            for event in events if event.get("event") == FEEDBACK}


def _files(ledger):
    """The feedback files, by id: every regular, visible file in `research/feedback/`."""
    directory = ledger.research / FEEDBACK_DIR
    if not directory.is_dir():
        return {}
    return {path.stem: path for path in sorted(directory.iterdir()) if path.is_file() and not path.name.startswith(".")}


def _file(ledger, text, source, stem=None):
    """Write one item and journal it, under the lock the caller holds; `stem` names it, else its number and first words do."""
    events, _ = ledger.read_events()
    taken = set(_journaled(events)) | set(_files(ledger))
    identifier = stem
    number = len(_journaled(events)) + 1
    while identifier is None or identifier in taken:
        identifier = "%03d-%s" % (number, _slug(text) or "feedback")
        if any(name.startswith("%03d-" % number) for name in taken):
            identifier = None
        number += 1
    path = ledger.write_markdown("%s/%s.md" % (FEEDBACK_DIR, identifier), text)
    ledger.append_event(FEEDBACK, {K_ID: identifier, K_SOURCE: source})
    return {"id": identifier, "source": source, "path": str(path)}


def file_feedback(project, text, source=CLI):
    """File one item of feedback: `research/feedback/<id>.md` and a `feedback` event; returns `{"id", "source", "path"}`.

    The id is the next free number and the first words of the text, so the owner can tell the items apart in
    a listing. The file is written before the event, under one lock, so a reader that finds the event finds the text.
    """
    text = str(text or "").strip()
    if not text:
        raise ChangeError("there is no text to file as feedback")
    if source not in SOURCES:
        raise ChangeError("feedback is filed from %s, got %r; a file dropped in research/%s/ is taken as it is"
                          % (" or ".join(SOURCES), source, FEEDBACK_DIR))
    ledger = Ledger(project)
    with ledger.lock():
        return _file(ledger, text, source)


def take_dropped(project):
    """Journal every file the owner dropped in `research/feedback/` that the journal does not hold; the items taken."""
    ledger = Ledger(project)
    taken = []
    with ledger.lock():
        events, _ = ledger.read_events()
        known = _journaled(events)
        for identifier, path in _files(ledger).items():
            if identifier in known:
                continue
            ledger.append_event(FEEDBACK, {K_ID: identifier, K_SOURCE: FILE})
            taken.append({"id": identifier, "source": FILE, "path": str(path)})
    return taken


def read_state(ledger):
    """`research/evolve.json`: `{"read": {<feedback id>: {"records", "dismissed", "session_id", "ts"}}, "claimed": {<id>: {"pid", "ts"}}}`."""
    try:
        state = ledger.read_json(EVOLVE_JSON)
    except (OSError, ValueError, LedgerError):
        state = None
    state = state if isinstance(state, dict) else {}
    state.setdefault("read", {})
    state.setdefault("claimed", {})
    return state


def mark_read(ledger, made, session_id=None):
    """Record what an evolver session made of each item, and drop its claim: `made` maps a feedback id to `{"records", "dismissed"}`."""
    with ledger.lock():
        state = read_state(ledger)
        for identifier, outcome in made.items():
            state["read"][identifier] = {"records": list(outcome.get("records") or []), "dismissed": outcome.get("dismissed"),
                                         "session_id": session_id, "ts": now_ts()}
            state["claimed"].pop(identifier, None)
        ledger.write_json(EVOLVE_JSON, state)
    return state


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def _claimed_elsewhere(state):
    """The items another live process is evolving right now; a claim whose process is gone holds nothing."""
    return {identifier for identifier, claim in state["claimed"].items()
            if isinstance(claim, dict) and claim.get("pid") != os.getpid() and _alive(claim.get("pid"))}


def claim(ledger, identifiers):
    """Claim the items for this process for the length of an evolver session; the ids it got, in order.

    A session lasts minutes, and `wayline evolve` and a running conductor both look for pending feedback, so
    without a claim both would spend a session on the same items and file the same change twice.
    """
    with ledger.lock():
        state = read_state(ledger)
        taken = _claimed_elsewhere(state)
        got = [identifier for identifier in identifiers if identifier not in taken and identifier not in state["read"]]
        for identifier in got:
            state["claimed"][identifier] = {"pid": os.getpid(), "ts": now_ts()}
        if got:
            ledger.write_json(EVOLVE_JSON, state)
    return got


def release(ledger, identifiers):
    """Drop this process's claims on the items a session did not get to read: a refusal, a hold, a failure to launch."""
    with ledger.lock():
        state = read_state(ledger)
        mine = [identifier for identifier in identifiers if (state["claimed"].get(identifier) or {}).get("pid") == os.getpid()]
        for identifier in mine:
            state["claimed"].pop(identifier)
        if mine:
            ledger.write_json(EVOLVE_JSON, state)


def _text_of(path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as failure:
        return "(the file could not be read: %s)" % failure
    if len(text) > FEEDBACK_MAX_CHARS:
        return text[:FEEDBACK_MAX_CHARS] + "\n\n(cut at %d characters of %d)\n" % (FEEDBACK_MAX_CHARS, len(text))
    return text


def pending_feedback(project, journaled=None):
    """The feedback no evolver session has read, in journal order, each with its text; dropped files are taken first.

    `journaled` is `{id: source}` when the caller already folded the journal (the conductor, once a wave): the
    journal is then read again only when the directory holds a file it does not name. An item another live
    process has claimed for its own session is not pending here.
    """
    ledger = Ledger(project)
    files = _files(ledger)
    if journaled is None or set(files) - set(journaled):
        take_dropped(project)
        journaled = _journaled(ledger.read_events()[0])
    state = read_state(ledger)
    skipped = set(state["read"]) | _claimed_elsewhere(state)
    return [{"id": identifier, "source": source, "text": _text_of(files[identifier]) if identifier in files else "(its file is gone)"}
            for identifier, source in journaled.items() if identifier not in skipped]


# --- the tier ---------------------------------------------------------------------------------------


def evolver_tier(policy, fall_back=False):
    """The `(model, effort, fallback_from)` the evolver runs at: `policy.roles.evolver`, Opus in Fable's place when `fall_back`."""
    entry = ((policy or {}).get("roles") or {}).get(EVOLVER) or {}
    model, effort = entry.get("model"), entry.get("effort")
    if model not in worker.MODEL_ALIASES or effort not in worker.EFFORTS:
        raise ChangeError("policy.roles.evolver names no model and effort the launcher knows; got %r" % (entry,))
    if model == pacing.FABLE and fall_back:
        return pacing.OPUS, effort, pacing.FABLE
    return model, effort, None


def evolves_on_fable(policy):
    """Whether the evolver's tier is Fable, so the hold on Fable's weekly window holds it (decision 15)."""
    try:
        return evolver_tier(policy)[0] == pacing.FABLE
    except ChangeError:
        return False


def _falls_back_now(project, policy, fall_back, what):
    """Whether this launch falls back to Opus now: the caller's word, else the journal's hold, and only for an evolver on Fable."""
    if fall_back is not None:
        return bool(fall_back)
    if not evolves_on_fable(policy):
        return False
    return gates.fallback_now(project, what)


# --- the checks ---------------------------------------------------------------------------------------


def is_ladder_change(record):
    """Whether a record changes the rung ladder: its mechanism is `policy` and its keys include `tiers` or `difficulty`."""
    return record.get("mechanism") == "policy" and bool(set(record.get("keys") or ()) & set(LADDER_KEYS))


def _target(record):
    """The target as it is kept: slashes forward, and a skill's directory with its trailing slash."""
    text = str(record.get("target") or "").strip().replace("\\", "/")
    if record.get("mechanism") == "skill" and record.get("scope_kind") == LOCAL and text and not text.endswith("/"):
        text += "/"
    return text


def target_problem(record, project, harness_root=HARNESS_ROOT, policy=None):
    """Why a record's target is not one its mechanism and scope allow, or None when it is one."""
    mechanism, scope, text = record.get("mechanism"), record.get("scope_kind"), _target(record)
    if text.startswith("/") or text.startswith("~"):
        return "the target %s is not a path under the project or the harness repository" % text
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if ".." in parts:
        return "the target %s leaves the tree it names" % text
    if not parts:
        return "the target names a whole tree"
    if parts[0] == "research":
        return "the target %s is under research/, which the ledger alone writes" % text
    if mechanism == "policy":
        keys = list(record.get("keys") or [])
        if not keys:
            return "a policy change names no policy key in `keys`"
        known = policy if policy is not None else policy_for(project, harness_root)
        unknown = [key for key in keys if key not in known]
        if unknown:
            return "there is no policy key `%s`; the policy's keys are %s" % (unknown[0], ", ".join(sorted(known)))
    if scope == LOCAL:
        if mechanism in ("hook", "code"):
            return "a %s change is global: a project holds no %s of its own, so its target is a path in the harness repository" % (mechanism, mechanism)
        if mechanism == "policy":
            return None if text == "harness.json" else "a local policy change is an override in harness.json, not %s" % text
        if mechanism == "skill":
            if not _LOCAL_SKILL_RE.match(text):
                return ("a local skill lives at .claude/skills/wayline-<name>/, got %s; the wayline- prefix is what lets a ticket name it" % text)
            return None
        match = _LOCAL_ROLE_RE.match(text)
        if match is None:
            return "a local %s change is made in .claude/agents/<role>.md, got %s" % (mechanism, text)
        if not (Path(harness_root) / "roles" / match.group(1) / registry.SIDECAR).is_file():
            return "the harness has no role `%s` for .claude/agents/%s.md to override" % (match.group(1), match.group(1))
        return None
    if mechanism == "policy" and text != "policy.json":
        return "a global policy change is made in policy.json, not %s" % text
    if not (Path(harness_root) / parts[0]).exists():
        return "the harness repository holds no %s for the target %s to be under" % (parts[0], text)
    return None


def check_list(answer, pending, journal_lines, project, harness_root=HARNESS_ROOT, policy=None):
    """The Type-A checks on what the evolver returned; every failure, named for the session that gets them back."""
    failures = []
    shown = {item["id"] for item in pending}
    answered = set()
    known_fixtures = set()
    for position, record in enumerate(answer.get("records") or [], start=1):
        label = "record %d (%s)" % (position, _one_line(record.get("title")))
        if record["feedback"] not in shown:
            failures.append("%s answers the feedback %s, which is not among the items shown" % (label, record["feedback"]))
        answered.add(record["feedback"])
        for locator in record["observed"]["journal_events"]:
            line = int(_LOCATOR_RE.match(locator).group(1))
            if not 1 <= line <= journal_lines:
                failures.append("%s cites %s, and the journal holds %d line(s)" % (label, locator, journal_lines))
        problem = target_problem(record, project, harness_root, policy)
        if problem is not None:
            failures.append("%s: %s" % (label, problem))
        if not _slug(record["title"]):
            failures.append("%s has a title no id can be cut from; use letters or digits" % label)
        root = Path(project) if record["scope_kind"] == LOCAL else Path(harness_root)
        if (root / fixtures.FIXTURES / record["fixture"]).exists() or record["fixture"] in known_fixtures:
            failures.append("%s names the fixture %s, which exists already; a fixture born from feedback is a new one" % (label, record["fixture"]))
        known_fixtures.add(record["fixture"])
    for item in answer.get("dismissed") or []:
        if item["feedback"] not in shown:
            failures.append("the dismissed item %s is not among the items shown" % item["feedback"])
        answered.add(item["feedback"])
    for identifier in sorted(shown - answered):
        failures.append("%s is answered by no record and is not dismissed" % identifier)
    return failures


# --- the records --------------------------------------------------------------------------------------


def _record_path(identifier):
    return "%s/%s.json" % (CHANGES_DIR, identifier)


def read_changes(project):
    """Every change record the project holds, by id; a file the schema refuses is skipped, never trusted."""
    directory = Path(project) / "research" / CHANGES_DIR
    records = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            check(record, load_schema(CHANGE_SCHEMA), name=str(path))
        except (OSError, ValueError):
            continue
        records.append(record)
    return records


def read_change(project, identifier):
    """One change record, read from its own file, or None: the conductor asks for one at a time, often."""
    if not identifier or not _RECORD_ID_RE.match(str(identifier)):
        return None
    path = Path(project) / "research" / _record_path(identifier)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        check(record, load_schema(CHANGE_SCHEMA), name=str(path))
    except (OSError, ValueError):
        return None
    return record


def change_of(ticket):
    """The id of the change record a harness ticket was filed for, from its origin; None for any other ticket."""
    if (ticket or {}).get("kind") != HARNESS_KIND:
        return None
    match = _ORIGIN_RE.match(str(ticket.get("origin") or ""))
    return match.group(1) if match else None


def global_change(project, ticket):
    """The record of the global change `ticket` was filed for, or None: the ticket works in the harness repository then."""
    identifier = change_of(ticket)
    record = read_change(project, identifier) if identifier else None
    return record if record is not None and record["scope_kind"] == GLOBAL else None


def set_status(project, identifier, status, **fields):
    """Rewrite one record with a new status and whatever else changed (`commit`, `checks`, `proof`, `tag`); returns it."""
    ledger = Ledger(project)
    with ledger.lock():
        record = read_change(project, identifier)
        if record is None:
            raise ChangeError("%s holds no change record %s" % (project, identifier))
        record = dict(record, status=status, **fields)
        ledger.write_json(_record_path(identifier), record, schema=CHANGE_SCHEMA)
    return record


def touches_for(record):
    """A harness ticket's touch set: the record's target, and the directory of the fixture that proves it."""
    return [record["target"], "%s/%s/" % (fixtures.FIXTURES, record["fixture"])]


def global_worktree(record):
    """Where a global change's branch is checked out: `~/.wayline/worktrees/evolve-<id>`."""
    return versions.worktree_path("evolve-" + record["id"])


def _ticket_body(record, acceptance):
    where = ("the branch `%s` of the harness repository, checked out as your worktree" % record["branch"]
             if record["scope_kind"] == GLOBAL else "the project, in your worktree")
    lines = [
        "## Demo", "", record["desired"], "",
        "## Change record", "",
        "`research/%s` is the record this ticket makes real, in %s." % (_record_path(record["id"]), where), "",
        "- observed: " + _one_line(record["observed"]["text"]),
    ]
    lines += ["  - evidence: " + locator for locator in record["observed"]["journal_events"]]
    lines += [
        "- desired: " + _one_line(record["desired"]),
        "- mechanism: `%s`, %s, risk %s" % (record["mechanism"], record["scope_kind"], record["risk"]),
        "- target: `%s`%s" % (record["target"], " (policy keys: %s)" % ", ".join("`%s`" % key for key in record["keys"]) if record.get("keys") else ""),
    ]
    if record.get("notes"):
        lines.append("- notes: " + _one_line(record["notes"]))
    lines += [
        "", "## The fixture", "",
        "The change ships with the fixture `%s`, under `fixtures/%s/`. It encodes the desired behaviour: record it from the "
        "journaled session that showed the observed one (`wayline fixture record --session <id> --kind %s --slug %s --root . "
        "--no-baseline`), then prune its structural checks and write the checks or the rubric that say what must now hold. "
        "Before this ticket is integrated the conductor runs it twice: it passes on your change, and it fails on the subject as it "
        "is today. A fixture that passes on both proves nothing, and the ticket fails on it."
        % (record["fixture"], record["fixture"], record["fixture"].split("/")[0], record["fixture"].split("/")[1]),
    ]
    if record["mechanism"] == "skill" and record["scope_kind"] == LOCAL:
        lines += ["", "A local skill is `SKILL.md`, a `wayline.json` sidecar (`id`, `scope_kind: local`, `capability_summary`, "
                  "`applicability_tags`, `cost_hint`, `fixtures` naming `%s`, `sha256`), and that fixture; the librarian assigns it "
                  "only once the fixture has passed." % record["fixture"]]
    if not acceptance:
        lines += ["", "No machine criterion was given, so the fixture is the whole gate."]
    return "\n".join(lines) + "\n"


def _feedback_path(ledger, identifier):
    path = _files(ledger).get(identifier)
    return "research/%s/%s" % (FEEDBACK_DIR, path.name) if path is not None else None


def _file_ticket(project, ledger, record, index, notify):
    """One harness ticket for `record`, and the ladder's decision ticket when it changes the rung ladder; returns the record.

    The difficulty and the machine criteria are the record's own, kept on it when the evolver returned them, so a
    proposal the owner applies later is filed exactly as the one filed at once would have been.
    """
    acceptance = [command for command in record.get("acceptance") or [] if str(command).strip()]
    if record["scope_kind"] == GLOBAL:
        record = dict(record, branch=BRANCH % record["id"], worktree=str(global_worktree(record)))
    identifier = next_id(project)
    fields = {
        "id": identifier, "title": _one_line(record["title"]), "kind": HARNESS_KIND, "difficulty": int(record.get("difficulty") or 2),
        "status": "open", "blocked_by": [], "touches": touches_for(record),
    }
    assignment = registry.librarian(fields, index)
    if assignment["role"] is None:
        raise ChangeError("no assignable role covers a harness ticket, so change record %s cannot be filed: %s"
                          % (record["id"], "; ".join(assignment["notes"])))
    context = ["research/" + _record_path(record["id"])]
    feedback = _feedback_path(ledger, record.get("feedback"))
    if feedback is not None:
        context.append(feedback)
    fields.update({
        "role": assignment["role"], "skills": list(assignment["skills"]),
        "acceptance": {"machine": acceptance or ["test -f %s/%s/fixture.json" % (fixtures.FIXTURES, record["fixture"])], "quality": []},
        "context_pack": context, "proposed_by": BY_EVOLVE, "demo": _first_sentence(record["desired"]),
        "origin": GLOBAL_ORIGIN % (record["id"], record["id"]) if record["scope_kind"] == GLOBAL else ORIGIN % record["id"],
    })
    record = dict(record, status=OPEN, ticket=identifier)
    ledger.write_json(_record_path(record["id"]), record, schema=CHANGE_SCHEMA)
    write_ticket(ledger, fields, _ticket_body(record, acceptance))
    ledger.append_event(TICKET_CREATED, {"ticket": identifier, "kind": HARNESS_KIND, "proposed_by": BY_EVOLVE,
                                         "origin": fields["origin"], "blocked_by": []}, ticket=identifier)
    registry.assign(fields, index, ledger=ledger)
    if is_ladder_change(record):
        opened = decisions.open_decision(
            project, "Change record %s changes the rung ladder (policy %s): %s Apply it?"
            % (record["id"], ", ".join("`%s`" % key for key in record["keys"]), _one_line(record["desired"])),
            options=[APPROVE, DECLINE], evidence=[_one_line(record["observed"]["text"])] + list(record["observed"]["journal_events"]),
            blocking="subgraph", pauses=[identifier], proposed_by=BY_EVOLVE, origin=LADDER_ORIGIN % record["id"],
            title="Apply the change to the rung ladder of %s" % record["id"], context_pack=context, notify=notify,
            decision_class=LADDER_CLASS)
        record = dict(record, decision=opened["ticket"])
        ledger.write_json(_record_path(record["id"]), record, schema=CHANGE_SCHEMA)
    return record


def file_changes(project, answer, *, harness_root=HARNESS_ROOT, autonomy=None, notify=None, index=None, pre_check=True):
    """Keep every record of a checked list and file its harness ticket, under the ledger's lock; the records as kept.

    A global change under autonomy `autonomous` is kept as `proposed` and no ticket is filed: global changes are
    on the irreversible list (decision 4), so the report proposes it and nothing is applied.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    autonomy = read_harness(project).get("autonomy") if autonomy is None else autonomy
    index = registry.build(project, harness_root, pre_check=pre_check) if index is None else index
    kept = []
    filed = [item for item in answer.get("records") or [] if not (item["scope_kind"] == GLOBAL and autonomy == AUTONOMOUS)]
    if filed and registry.librarian({"kind": HARNESS_KIND}, index)["role"] is None:
        # Said before anything is written: a record kept without its ticket would be answered by nothing.
        raise ChangeError("no assignable role covers a harness ticket, so no change record can be filed; the registry needs one first")
    with ledger.lock():
        number = len(read_changes(project))
        for item in answer.get("records") or []:
            number += 1
            record = {
                "id": "%03d-%s" % (number, _slug(item["title"], TITLE_WORDS)), "title": _one_line(item["title"]),
                "feedback": item["feedback"], "observed": {"text": item["observed"]["text"].strip(),
                                                           "journal_events": list(item["observed"]["journal_events"])},
                "desired": item["desired"].strip(), "mechanism": item["mechanism"], "scope_kind": item["scope_kind"],
                "risk": "high" if is_ladder_change(item) else item["risk"], "target": _target(item), "keys": list(item.get("keys") or []),
                "fixture": item["fixture"], "status": PROPOSED, "ticket": None, "decision": None, "branch": None, "worktree": None,
                "commit": None, "checks": [], "proof": None, "tag": None, "notes": item.get("notes") or "", "created": now_ts(),
                "difficulty": int(item.get("difficulty") or 2),
                "acceptance": [command for command in item.get("acceptance") or [] if str(command).strip()],
            }
            ledger.write_json(_record_path(record["id"]), record, schema=CHANGE_SCHEMA)
            ledger.append_event(CHANGE_RECORD, {K_ID: record["id"], K_SCOPE_KIND: record["scope_kind"],
                                                K_MECHANISM: record["mechanism"], K_FIXTURE: record["fixture"]})
            if not (record["scope_kind"] == GLOBAL and autonomy == AUTONOMOUS):
                record = _file_ticket(project, ledger, record, index, notify)
            kept.append(record)
        if any(record["ticket"] is not None for record in kept):
            refresh_graph(project, ledger=ledger, events=ledger.read_events()[0], force=True)
    return kept


def apply_proposal(project, identifier, *, harness_root=HARNESS_ROOT, notify=None, pre_check=True):
    """`wayline evolve --apply <id>`: the owner's word on a proposed global change; its harness ticket is filed now."""
    project = Path(project).resolve()
    ledger = Ledger(project)
    with ledger.lock():
        record = read_change(project, identifier)
        if record is None:
            raise ChangeError("%s holds no change record %s" % (project, identifier))
        if record["status"] != PROPOSED:
            raise ChangeError("change record %s is %s, not proposed; there is nothing to apply" % (identifier, record["status"]))
        index = registry.build(project, harness_root, pre_check=pre_check)
        record = _file_ticket(project, ledger, record, index, notify)
        refresh_graph(project, ledger=ledger, events=ledger.read_events()[0], force=True)
    return record


# --- the ladder's answer --------------------------------------------------------------------------------


def approves(answer):
    """Whether an answer to the ladder's decision approves the change: it opens with `approve`, `yes`, `apply`, or `confirm`."""
    words = _WORD_RE.findall(str(answer or "").lower())
    return bool(words) and words[0] in APPROVING


def ladder_answered(project, fields, answer, ledger=None):
    """An answer to a change's ladder decision that does not approve parks its harness ticket at once; the ids parked.

    The conductor closes an answered decision ticket at its next wave whatever the answer says, and a closed
    blocker holds nothing, so every path an answer takes calls this under the ledger's lock
    (`project.graph_answered`). Any other ticket's answer is left alone.
    """
    match = _LADDER_ORIGIN_RE.match(str((fields or {}).get("origin") or ""))
    if match is None or (fields or {}).get("kind") != DECISION_KIND or approves(answer):
        return []
    project = Path(project).resolve()
    ledger = ledger or Ledger(project)
    with ledger.lock():
        record = read_change(project, match.group(1))
        if record is None or record["status"] != OPEN:
            return []
        parked = []
        for ticket in read_tickets(project):
            if ticket["id"] == record["ticket"] and ticket["status"] in decisions.PAUSABLE:
                _, body = read_ticket(tickets_dir(project) / filename(ticket))
                text = body.rstrip("\n") + "\n\n## Declined\n\nThe ladder decision (ticket %d) was answered: %s\n" % (fields["id"], _one_line(answer))
                write_ticket(ledger, dict(ticket, status="parked"), text)
                ledger.append_event(TICKET_CANCELLED, {"ticket": ticket["id"], "by": BY_EVOLVE}, ticket=ticket["id"])
                parked.append(ticket["id"])
        ledger.write_json(_record_path(record["id"]), dict(record, status=DECLINED), schema=CHANGE_SCHEMA)
    return parked


# --- the prompt -----------------------------------------------------------------------------------------


def _journal_digest(ledger):
    """`(text, line count)`: the journal numbered by line, quiet events left out, the last `JOURNAL_LINES` kept."""
    try:
        raw = ledger.journal_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        raw = []
    lines = []
    for number, text in enumerate(raw, start=1):
        try:
            event = json.loads(text)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("event") in QUIET:
            continue
        payload = json.dumps(event.get("payload") or {}, sort_keys=True, ensure_ascii=False)
        if len(payload) > PAYLOAD_CHARS:
            payload = payload[:PAYLOAD_CHARS] + "..."
        session = " session=%s" % event["session_id"] if event.get("session_id") else ""
        lines.append("L%d %s %s%s %s" % (number, str(event.get("ts") or "")[:19], event.get("event"), session, payload))
    if len(lines) > JOURNAL_LINES:
        lines = ["[wayline: %d earlier line(s) left out; open research/journal.jsonl for them]" % (len(lines) - JOURNAL_LINES)] + lines[-JOURNAL_LINES:]
    return "\n".join(lines) or "(the journal is empty)", len(raw)


def _registry_text(index):
    lines = []
    for entry in (index or {}).get("entries") or []:
        outcome = entry.get("outcome") or {}
        state = "assignable" if entry.get("assignable") else "not assignable: %s" % _one_line("; ".join(entry.get("problems") or [])[:200])
        lines.append("- %s `%s` (%s, %s), assigned %d, passed first time %d, failed %d: %s" % (
            entry.get("kind"), entry.get("id"), entry.get("scope_kind"), state, outcome.get("assigned", 0),
            outcome.get("passed_first_time", 0), outcome.get("failed", 0), _one_line(entry.get("capability_summary"))))
    return "\n".join(lines) or "- the registry is empty"


def evolve_prompt(role, pending, journal, records, index, policy, harness, project, harness_root):
    """The evolver's prompt: its protocol, the items, the numbered journal, the open records, the registry, the policy."""
    parts = ["# The evolver's session", "",
             "You are handed the feedback no session has read yet. Return the change records it calls for, as the protocol says.", "",
             role.protocol.strip() or "# Protocol\n\nReturn the change records through the structured output.", "",
             "# The feedback", ""]
    for item in pending:
        parts += ["## %s (%s)" % (item["id"], item["source"]), "", item["text"].strip(), ""]
    parts += ["# The journal", "", "`research/journal.jsonl`, one line per event as `L<line> <time> <event> <payload>`; cite a line as "
              "`research/journal.jsonl#L<line>`.", "", "```", journal, "```", "", "# Change records already open", ""]
    standing = [record for record in records if record["status"] in (OPEN, PROPOSED, AWAITING_OWNER)]
    parts += ["- `%s` (%s, %s, %s): %s" % (record["id"], record["status"], record["mechanism"], record["target"], _one_line(record["desired"]))
              for record in standing] or ["- none"]
    parts += ["", "# The registry", "", _registry_text(index), "", "# The policy and the project", "",
              "- autonomy: `%s`; ladder consent: `%s`" % (harness.get("autonomy"), harness.get("ladder_changes") or "ask (unset)"),
              "- the policy's keys: %s" % ", ".join("`%s`" % key for key in sorted(policy)),
              "- `tiers` (the rung ladder): %s" % json.dumps(policy.get("tiers")),
              "- `difficulty` (level to rung): %s" % json.dumps(policy.get("difficulty")),
              "- the project's overrides in `harness.json`: %s" % json.dumps(harness.get("policy") or {}),
              "- the project is %s and the harness repository is %s; both are open to you for reading" % (project, harness_root)]
    return "\n".join(parts) + "\n"


# --- the session ----------------------------------------------------------------------------------------


class _Session:
    """One evolver session: the launch, the one resume a failing gate gets, and the record kept beside its stream."""

    what = "the evolver's session"

    def __init__(self, project, harness_root, policy, fall_back, say):
        self.project, self.harness_root, self.policy, self.say = project, Path(harness_root).resolve(), policy, say
        self.ledger = Ledger(project)
        self.model, self.effort, self.fallback_from = evolver_tier(policy, _falls_back_now(project, policy, fall_back, self.what))
        self.role = worker.read_role(EVOLVER, harness_root, project)
        self.run_dir = specify.session_dir(project, SESSIONS)
        self.request = self.session_id = None
        self.kept = 0

    def _budget(self, key):
        return ((self.policy.get("budget") or {}).get(EVOLVER_BUDGET) or {}).get(key)

    def start(self, prompt):
        self.request = worker.LaunchRequest(
            role=self.role.name, model=self.model, effort=self.effort, prompt=prompt,
            agent_json=self.role.agent_json(self.model, self.effort, self._budget("max_turns")),
            allowed_tools=list(self.role.allowed_tools), disallowed_tools=list(self.role.disallowed_tools),
            settings_path=gates.write_worker_settings(self.run_dir / "settings.json", self.harness_root),
            add_dirs=[str(self.harness_root), str(self.project)], cwd=self.project,
            env=gates.verdict_env(self.project, self.run_dir),
            schema_path=self.harness_root / "schemas" / (LIST_SCHEMA + ".json"),
            max_minutes=self._budget("max_minutes"),
        )
        return self._taken(worker.launch(self.request))

    def continue_with(self, message):
        if not self.session_id:
            raise ChangeError("the evolver's session has no id to be resumed with")
        return self._taken(worker.resume(self.request, self.session_id, message))

    def _taken(self, envelope):
        gates.raise_if_refused(envelope, self.model, self.what)
        self.session_id = envelope.session_id or self.session_id
        return envelope

    def keep(self, answer):
        self.kept += 1
        self.ledger.write_json("%s/list-%d.json" % (Path(self.run_dir).relative_to(self.ledger.research), self.kept), answer)

    @staticmethod
    def unusable(envelope):
        if not envelope.valid:
            return "; ".join(envelope.errors) or "the session returned no structured %s" % LIST_SCHEMA
        try:
            check(envelope.structured_output, load_schema(LIST_SCHEMA), name="the " + LIST_SCHEMA)
        except ValidationError as failure:
            return str(failure)
        return None

    def checked(self, prompt, checker):
        """A list that passed the schema and `checker`, with each gate's one return spent as needed; raises `ChangeError`."""
        envelope = self.start(prompt)
        problem = self.unusable(envelope)
        if problem is not None:
            self.say("the evolver's list could not be read (%s); returned to it once" % problem)
            envelope = self.continue_with(RESUME_INVALID % problem)
            problem = self.unusable(envelope)
        if problem is not None:
            raise ChangeError("the evolver returned no list the schema accepts: %s" % problem)
        answer = envelope.structured_output
        self.keep(answer)
        failures = checker(answer)
        if failures:
            self.say("the evolver's list failed %d check(s); returned to it once" % len(failures))
            envelope = self.continue_with(RESUME_CHECKS % "\n".join("- " + failure for failure in failures))
            problem = self.unusable(envelope)
            if problem is not None:
                raise ChangeError("the evolver's second list could not be read: %s" % problem, failures)
            answer = envelope.structured_output
            self.keep(answer)
            failures = checker(answer)
        if failures:
            raise ChangeError("the evolver's list failed its checks twice; nothing was filed: %s" % "; ".join(failures), failures)
        return answer


def _evolve_pending(project, ledger, pending, report, harness_root, policy, fall_back, notify, say, pre_check):
    """The session over `pending`, its gates, and what it files, written into `report`; the items end read or still claimed."""
    harness = read_harness(project)
    index = registry.build(project, harness_root, pre_check=pre_check)
    journal, journal_lines = _journal_digest(ledger)
    session = _Session(project, harness_root, policy, fall_back, say)
    say("evolver on %s %s%s over %d item(s): %s" % (session.model, session.effort,
                                                    " (falling back from Fable)" if session.fallback_from else "",
                                                    len(pending), ", ".join(report["pending"])))
    prompt = evolve_prompt(session.role, pending, journal, read_changes(project), index, policy, harness, project, harness_root)
    report["launched"] = True
    shown = {item["id"] for item in pending}

    def refused(why):
        """Mark the items read with why nothing more came of them, naming whatever was written before the failure."""
        written = {}
        for record in read_changes(project):
            if record.get("feedback") in shown:
                written.setdefault(record["feedback"], []).append(record["id"])
        mark_read(ledger, {identifier: {"records": written.get(identifier, []), "dismissed": why} for identifier in shown},
                  session_id=session.session_id)

    before = {record["id"] for record in read_changes(project)}
    try:
        answer = session.checked(prompt, lambda returned: check_list(returned, pending, journal_lines, project, harness_root, policy))
    except ChangeError as failure:
        if failure.failures or session.session_id:
            refused("the evolver's list was refused: %s" % failure)
        raise
    try:
        kept = file_changes(project, answer, harness_root=harness_root, autonomy=harness.get("autonomy"), notify=notify, index=index,
                            pre_check=pre_check)
    except (ValueError, OSError) as failure:
        # The session is spent and its list was good. Left pending, the items would cost a session every wave and
        # file the same change again under a new id, so they are read, and what went wrong is what they say.
        left = sorted(record["id"] for record in read_changes(project) if record["id"] not in before)
        refused("the evolver's list passed its checks and could not be filed: %s%s" % (
            failure, "; written before the failure: %s" % ", ".join(left) if left else ""))
        raise
    made = {identifier: {"records": [], "dismissed": None} for identifier in shown}
    for record in kept:
        made[record["feedback"]]["records"].append(record["id"])
    for item in answer.get("dismissed") or []:
        made[item["feedback"]]["dismissed"] = item["reason"]
        report["dismissed"][item["feedback"]] = item["reason"]
    mark_read(ledger, made, session_id=session.session_id)
    report["records"] = [record["id"] for record in kept]
    report["proposed"] = [record["id"] for record in kept if record["status"] == PROPOSED]
    report["tickets"] = [record["ticket"] for record in kept if record["ticket"] is not None]
    report["decisions"] = [record["decision"] for record in kept if record["decision"] is not None]
    report["recommendations"] = list(answer.get("recommendations") or [])


def evolve(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, notify=None, say=lambda text: None, pre_check=True,
           tag=None):
    """One turn of the loop: take what was dropped, launch the evolver over what is pending, file what it returns, tag what landed.

    Returns `{"launched", "pending", "records", "proposed", "tickets", "decisions", "dismissed", "recommendations", "tagged",
    "waiting"}`. Nothing pending launches nothing. A usage window that refuses the session raises `gates.UsageLimited`
    and a held Fable window `gates.FableHeld`, and the items stay pending; a list that fails its gates twice, or one
    that passed them and could not be filed, raises with the items marked read, so the conductor does not spend a
    session on them every wave. The items are claimed for the length of the session (`claim`), so a second process
    looking meanwhile finds nothing pending.
    """
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    ledger = Ledger(project)
    report = {"launched": False, "pending": [], "records": [], "proposed": [], "tickets": [], "decisions": [], "dismissed": {},
              "recommendations": [], "tagged": [], "waiting": []}
    # The claim lasts the session: `wayline evolve` and a running conductor must not both spend one on the same items.
    claimed = set(claim(ledger, [item["id"] for item in pending_feedback(project)]))
    pending = [item for item in pending_feedback(project) if item["id"] in claimed]
    report["pending"] = [item["id"] for item in pending]
    if pending:
        try:
            _evolve_pending(project, ledger, pending, report, harness_root, policy, fall_back, notify, say, pre_check)
        finally:
            release(ledger, report["pending"])  # what a refusal, a hold, or a failed launch left unread is pending again
    settled = settle_global(project, harness_root, tag=tag)
    report["tagged"], report["waiting"] = settled["tagged"], settled["waiting"]
    return report


# --- the retrospective ------------------------------------------------------------------------------------


def _span(events):
    """The events since the last retrospective was filed: what the next one reads."""
    start = 0
    for position, event in enumerate(events):
        if event.get("event") == FEEDBACK and (event.get("payload") or {}).get(K_SOURCE) == RETROSPECTIVE:
            start = position + 1
    return events[start:]


def retrospective(project, harness_root=HARNESS_ROOT, events=None, index=None, pre_check=True):
    """What the journal since the last retrospective says went badly, as a dict `render_retrospective` spells out.

    Failures, escalations (a tier up, a split, a hand-off to a person, a kind's difficulty raised), stalls, rework
    (second attempts, resumes, failed verdicts, reruns), turns per closed ticket, the skills whose first-time pass
    rate is below the registry's median, the quarantined fixtures, and the local skills worth promoting.
    `worked` counts the launches of tickets that are not harness tickets: a span without one earns no retrospective.
    """
    project = Path(project).resolve()
    if events is None:
        events, _ = Ledger(project).read_events()
    span = _span(events)
    kinds = {ticket["id"]: ticket["kind"] for ticket in read_tickets(project)}
    retro = {"failures": [], "escalations": [], "stalls": [], "rework": [], "turns": {}, "poor_skills": [], "quarantined": [],
             "promote": [], "worked": 0, "ended": None}
    turns, attempts, closed = {}, {}, set()
    for event in span:
        name, payload = event.get("event"), event.get("payload") or {}
        ticket = payload.get("ticket", event.get("ticket"))
        if name == TICKET_LAUNCHED:
            attempts[ticket] = max(attempts.get(ticket, 0), int(payload.get("attempt") or 1))
            if kinds.get(ticket) != HARNESS_KIND:
                retro["worked"] += 1
        elif name == TICKET_FAILED:
            line = "ticket %s attempt %s failed (next: %s): %s" % (ticket, payload.get("attempt"), payload.get("next"), _one_line(payload.get("reason")))
            retro["failures"].append(line)
            if payload.get("next") in ("tier_up", "split", "needs_human"):
                retro["escalations"].append("ticket %s escalated to `%s` after attempt %s" % (ticket, payload.get("next"), payload.get("attempt")))
        elif name == TICKET_NEEDS_HUMAN:
            retro["escalations"].append("ticket %s was handed to a person: %s" % (ticket, _one_line(payload.get("question"))))
        elif name == DIFFICULTY_RAISED:
            retro["escalations"].append("the default difficulty of %s tickets rose from %s to %s" % (payload.get("kind"), payload.get("from"), payload.get("to")))
        elif name == STALL:
            retro["stalls"].append("the run stalled after %s settling wave(s) without progress (action: %s)" % (payload.get("waves"), payload.get("action")))
        elif name == TICKET_RESUMED:
            retro["rework"].append("ticket %s attempt %s was resumed (%s)" % (ticket, payload.get("attempt"), payload.get("reason")))
        elif name == TICKET_RERUN:
            retro["rework"].append("ticket %s was rerun by %s" % (ticket, payload.get("by")))
        elif name == VERDICT and payload.get("subject_kind") == "ticket" and payload.get("pass") is False:
            retro["rework"].append("ticket %s failed its %s verdict" % (payload.get("subject"), payload.get("verdict_type")))
        elif name == TICKET_RESULT:
            turns[ticket] = turns.get(ticket, 0) + int(payload.get("turns") or 0)
        elif name == TICKET_DONE:
            closed.add(ticket)
        elif name == RUN_ENDED:
            retro["ended"] = payload.get("reason")
    retro["rework"] += ["ticket %s took %d attempts" % (ticket, count) for ticket, count in sorted(attempts.items()) if count > 1]
    retro["turns"] = {ticket: turns[ticket] for ticket in sorted(closed) if ticket in turns}
    index = registry.build(project, harness_root, events=events, write=False, pre_check=pre_check) if index is None else index
    rates = {entry["id"]: entry["outcome"]["passed_first_time"] / entry["outcome"]["assigned"]
             for entry in index.get("entries") or [] if entry.get("kind") == "skill" and (entry.get("outcome") or {}).get("assigned")}
    if len(rates) > 1:
        median = statistics.median(rates.values())
        retro["poor_skills"] = ["`%s` passed first time on %d%% of its launches, below the registry's median of %d%%"
                                % (identifier, round(rate * 100), round(median * 100))
                                for identifier, rate in sorted(rates.items()) if rate < median]
    for root in (project, Path(harness_root)):
        for directory in fixtures.discover(root):
            try:
                quarantine = json.loads((directory / "fixture.json").read_text(encoding="utf-8")).get("quarantine") or {}
            except (OSError, ValueError):
                continue
            if quarantine.get("status") == "quarantined":
                retro["quarantined"].append("`%s` is quarantined after %d flake(s); tighten its checks or its rubric"
                                            % (fixtures.fixture_id(directory), len(quarantine.get("flakes") or [])))
    retro["promote"] = versions.render_recommendations(versions.promotion_candidates(index))
    return retro


def notable(retro):
    """Whether a retrospective is worth an evolver session: something failed, escalated, stalled, was redone, or tests badly."""
    return any(retro.get(key) for key in ("failures", "escalations", "stalls", "rework", "poor_skills", "quarantined"))


def render_retrospective(retro):
    lines = ["# Retrospective", "", "Computed by code from the journal since the last retrospective%s. It is feedback like the owner's: "
             "say what should change so that the next run does not repeat it, and dismiss it when nothing should."
             % (", over a run that ended `%s`" % retro["ended"] if retro.get("ended") else "")]
    for key, heading in (("failures", "Failures"), ("escalations", "Escalations"), ("stalls", "Stalls"), ("rework", "Rework"),
                         ("poor_skills", "Skills below the registry's median first-time pass rate"), ("quarantined", "Quarantined fixtures")):
        lines += ["", "## " + heading, ""] + (["- " + line for line in retro[key]] or ["- none"])
    lines += ["", "## Turns per closed ticket", ""]
    if retro["turns"]:
        counts = list(retro["turns"].values())
        lines.append("- %d ticket(s) closed, %.1f turns each on average" % (len(counts), sum(counts) / len(counts)))
        lines += ["- ticket %s: %d turns" % (ticket, count)
                  for ticket, count in sorted(retro["turns"].items(), key=lambda pair: -pair[1])[:TURNS_LISTED]]
    else:
        lines.append("- no ticket closed")
    if retro["promote"]:
        lines += ["", "## Promotion"] + [""] + retro["promote"]
    return "\n".join(lines) + "\n"


def file_retrospective(project, harness_root=HARNESS_ROOT, pre_check=True):
    """File the retrospective over the journal since the last one as a feedback item; None when it earns none.

    It earns none when the span launched no ticket but harness tickets, which is what keeps the loop from feeding
    itself, and when nothing in it is `notable`.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    retro = retrospective(project, harness_root, pre_check=pre_check)
    if not retro["worked"] or not notable(retro):
        return None
    with ledger.lock():
        return _file(ledger, render_retrospective(retro), RETROSPECTIVE, stem="retro-" + re.sub(r"[^0-9TZ]", "", now_ts()))


def file_from_figure(project, text, stem):
    """File what a figure result hands the evolve loop (ticket 50): the traps it would promote into the plot index.

    `stem` names the item after the figure and its version, so a result filed again after a restart finds its item
    already there and files nothing twice; returns the item, or None when it was filed before.
    """
    text = str(text or "").strip()
    if not text:
        raise ChangeError("there is no text to file as feedback")
    ledger = Ledger(project)
    with ledger.lock():
        events, _ = ledger.read_events()
        if stem in _journaled(events) or stem in _files(ledger):
            return None
        return _file(ledger, text, FIGURE, stem=stem)


def _paced_out(project, policy):
    """Why the evolver's session is not launched on top of a run that just ended, or None when pacing allows it.

    In the wave, `cheap_only` holds the evolver as it holds the decider and a verdict, and a paused run launches
    nothing. The run that ended leaves that word in the journal, and what it protected is still to be protected.
    """
    from wayline import replay  # the replayed view is the one the conductor and the tick read
    view = replay.replay(Ledger(project).read_events()[0])
    if view.pause is not None:
        return "the run ended paused on a usage window until %s" % view.pause.get("resets_at")
    action = view.pacing.get("fable_action" if evolves_on_fable(policy) else "action") or "normal"
    if action != "normal":
        return "pacing is `%s`, which holds a max-effort session" % action
    return None


def after_run(project, reason=None, *, harness_root=HARNESS_ROOT, policy=None, notify=None, say=print, pre_check=True):
    """What `wayline run` does once `run_ended` is journaled: the retrospective, then the evolver over what is pending.

    Nothing here fails the run that just ended: what goes wrong is said, and the items stay pending for the next
    `wayline evolve`. A run the owner ended (`stopped`, `switched`) files its retrospective and launches no session
    on top of the stop.
    """
    try:
        item = file_retrospective(project, harness_root, pre_check=pre_check)
        if item is not None:
            say("retrospective %s filed for the evolve loop" % item["id"])
        if reason in OWNER_ENDED:
            return None
        held = _paced_out(project, policy_for(project, harness_root) if policy is None else policy)
        if held is not None:
            say("evolve   %s; the feedback waits for wayline evolve" % held)
            return None
        report = evolve(project, harness_root=harness_root, policy=policy, notify=notify, say=lambda text: say("  " + text), pre_check=pre_check)
    except (ChangeError, gates.GateError, versions.EvolveError, ProjectError, LedgerError, TicketError, registry.RegistryError,
            worker.LaunchError, worker.RoleError, ValueError, OSError) as failure:
        say("evolve   %s" % failure)
        return None
    if report["launched"] or report["tagged"]:
        say(render_report(report))
    return report


# --- the report's proposals -------------------------------------------------------------------------------


def proposal_lines(project):
    """`REPORT.md`'s lines for the global changes the run proposed and did not apply, each with the command that applies it."""
    lines = []
    for record in read_changes(project):
        if record["scope_kind"] != GLOBAL:
            continue
        state = {PROPOSED: "proposed, not applied: `wayline evolve --apply %s` files its harness ticket" % record["id"],
                 OPEN: "its harness ticket %s works on `%s`" % (record["ticket"], record["branch"]),
                 AWAITING_OWNER: "`%s` passed the tests and the fixture suite and waits for the owner's merge" % record["branch"],
                 APPLIED: "applied%s" % (", tagged `%s`" % record["tag"] if record.get("tag") else ""),
                 DECLINED: "declined"}[record["status"]]
        lines.append("- Change record `%s`, *%s* (`%s` at `%s`, risk %s, fixture `%s`): %s. Desired: %s" % (
            record["id"], record.get("title") or record["id"], record["mechanism"], record["target"], record["risk"], record["fixture"],
            state, _one_line(record["desired"])))
    return lines


# --- the proof ----------------------------------------------------------------------------------------------


@dataclass
class Proof:
    """Whether a change's fixture proves it: `problem` says why not, and `waits` that a run stopped before it could say."""

    fixture: str
    old: Optional[str] = None
    new: Optional[str] = None
    problem: Optional[str] = None
    waits: bool = False

    @property
    def proven(self):
        return self.problem is None and not self.waits


def _copy_of(directory, holder):
    target = Path(holder) / directory.parent.name / directory.name
    shutil.copytree(directory, target, ignore=shutil.ignore_patterns("runs"))
    return target


def _subject_missing(directory, root):
    """Whether `root` lacks a subject file of the fixture in `directory`: the behaviour did not exist there, which fails it."""
    try:
        subject = fixtures.load_fixture(directory)["subject"]
    except fixtures.FixtureError:
        return False
    return any(not (Path(root) / relative).is_file() for relative in [subject["path"]] + list(subject.get("also") or []))


_LOCAL_ROLE_FILE_RE = re.compile(r"^\.claude/agents/([a-z][a-z0-9-]*)\.md\Z")
_LOCAL_SKILL_FILE_RE = re.compile(r"^\.claude/skills/wayline-[a-z0-9][a-z0-9-]*/.+\Z")


def _old_stand_in(directory, old_root, holder, harness_root):
    """`(root, said)`: a tree that carries the subject as it was before a local change, when the old tree lacks it.

    A local role override that did not exist is the harness's `roles/<role>/agent.md`, which the role launched with
    until the override (`worker.read_role`); a local skill that did not exist is no skill, so an empty file stands in
    and the pinned skill text leaves the prompt. Both run, so the old behaviour is shown failing rather than presumed
    to. `(old_root, None)` when the old tree holds every subject file, and `(None, None)` when nothing can stand in.
    """
    try:
        subject = fixtures.load_fixture(directory)["subject"]
    except fixtures.FixtureError:
        return old_root, None
    paths = [subject["path"]] + list(subject.get("also") or [])
    if all((Path(old_root) / relative).is_file() for relative in paths):
        return old_root, None
    stand_in, said = Path(holder) / "old-subject", []
    for relative in paths:
        target = stand_in / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        role = _LOCAL_ROLE_FILE_RE.match(relative)
        harness_role = Path(harness_root) / "roles" / role.group(1) / registry.ROLE_FILE if role else None
        if (Path(old_root) / relative).is_file():
            shutil.copy(Path(old_root) / relative, target)
        elif harness_role is not None and harness_role.is_file():
            shutil.copy(harness_role, target)
            said.append("on the harness's roles/%s/%s, which the override replaces" % (role.group(1), registry.ROLE_FILE))
        elif _LOCAL_SKILL_FILE_RE.match(relative):
            target.write_text("", encoding="utf-8")
            said.append("without the skill, which did not exist")
        else:
            return None, None
    return stand_in, "; ".join(dict.fromkeys(said))


def prove(fixture_id, old_root, new_root, policy=None, runner=None, harness_root=HARNESS_ROOT):
    """Run the fixture on the changed subject, where it must pass, and on the subject as it was, where it must fail.

    Both runs happen on a copy of the fixture, so a change that is not proven leaves its worktree as the worker
    left it. A proven one gets the passing run as the fixture's baseline, written into `new_root`'s
    `fixture.json` for the caller to commit. A subject the old tree does not hold cannot run there, which is a
    failure on the old subject. Any other run that could not happen shows nothing: not on the new subject, and
    not on the old one either.
    """
    runner = runner or fixtures.run_fixture
    directory = Path(new_root) / fixtures.FIXTURES / fixture_id
    proof = Proof(fixture_id)
    if not (directory / "fixture.json").is_file():
        proof.problem = "the change ships no fixture %s under %s/" % (fixture_id, fixtures.FIXTURES)
        return proof
    with tempfile.TemporaryDirectory(prefix="wayline-proof-") as holder:
        fresh = _copy_of(directory, Path(holder) / "new")
        new = runner(fresh, root=new_root, policy=policy)
        proof.new = fixtures.describe(new)
        if new.partial:
            proof.waits = True
            return proof
        if not new.passed:
            proof.problem = "the fixture %s does not pass on the change: %s" % (fixture_id, new.skipped or proof.new)
            return proof
        stand_in, said = _old_stand_in(fresh, old_root, holder, harness_root)
        old = runner(_copy_of(directory, Path(holder) / "old"), root=stand_in or old_root, policy=policy)
        proof.old = fixtures.describe(old) + (" (%s)" % said if said else "")
        if old.partial:
            proof.waits = True
            return proof
        if old.skipped is not None and not _subject_missing(fresh, old_root):
            # It ran on the change, so it is runnable; here it could not run for some other reason (a launch that
            # failed, an input that did not render), and a run that did not happen shows no failure.
            proof.problem = ("the fixture %s could not be run on the subject as it was (%s), so nothing shows that it fails there"
                             % (fixture_id, old.skipped))
            return proof
        if old.passed:
            proof.problem = ("the fixture %s passes on the subject as it was (%s), so it does not encode the desired behaviour; "
                             "tighten its checks or its rubric until the old behaviour fails them" % (fixture_id, proof.old))
            return proof
        fixtures.set_baseline(fresh, new, root=new_root)
        shutil.copy(fresh / "fixture.json", directory / "fixture.json")
    return proof


# --- a global change's branch -----------------------------------------------------------------------------


def add_global_worktree(harness_root, record):
    """`evolve/<id>` from the harness `main`, checked out at the record's worktree; reuses what an earlier attempt left."""
    harness_root, branch, path = Path(harness_root).resolve(), record["branch"], Path(record["worktree"])
    if (path / ".git").exists():
        if versions.git(path, "rev-parse", "--abbrev-ref", "HEAD", ok=None).stdout.strip() == branch:
            return path
        versions.git(harness_root, "worktree", "remove", "--force", str(path), ok=None)
    elif path.exists():
        raise ChangeError("%s exists and is not a worktree; remove it and run again" % path)
    versions.git(harness_root, "worktree", "prune", ok=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    if versions.exists(harness_root, "refs/heads/" + branch):
        versions.git(harness_root, "worktree", "add", "--quiet", str(path), branch)
    else:
        versions.git(harness_root, "worktree", "add", "--quiet", "-b", branch, str(path), versions.main_branch(harness_root))
    return path


def remove_global_worktree(harness_root, record, branch=True):
    """Drop a global change's worktree, and its branch unless the owner may still want it (`awaiting_owner`, `applied`)."""
    harness_root, path = Path(harness_root).resolve(), Path(record["worktree"])
    if path.exists():
        versions.git(harness_root, "worktree", "remove", "--force", str(path), ok=None)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    versions.git(harness_root, "worktree", "prune", ok=None)
    if branch and record["status"] not in (AWAITING_OWNER, APPLIED) and versions.exists(harness_root, "refs/heads/" + record["branch"]):
        versions.git(harness_root, "branch", "-D", record["branch"], ok=None)


def old_subject(harness_root, record, holder):
    """A detached checkout of the commit `evolve/<id>` left the harness `main` at, under `holder`: the subject as it was."""
    harness_root = Path(harness_root).resolve()
    base = versions.git(harness_root, "merge-base", record["branch"], versions.main_branch(harness_root)).stdout.strip()
    path = Path(holder) / "old"
    versions.git(harness_root, "worktree", "add", "--quiet", "--detach", str(path), base)
    return path


def drop_old_subject(harness_root, path):
    versions.git(Path(harness_root).resolve(), "worktree", "remove", "--force", str(path), ok=None)
    versions.git(Path(harness_root).resolve(), "worktree", "prune", ok=None)


def commit_all(worktree, message):
    """Commit everything the worktree holds uncommitted; returns the head."""
    versions.git(worktree, "add", "-A")
    if versions.git(worktree, "status", "--porcelain").stdout.strip():
        versions.git(worktree, *versions.identity(worktree), "commit", "-q", "-m", message)
    return versions.git(worktree, "rev-parse", "HEAD").stdout.strip()


def check_global(project, record, run=None):
    """The changelog paragraph, a commit, then the harness tests and the full fixture suite on the branch; `(commit, checks)`."""
    worktree = Path(record["worktree"])
    changelog = worktree / versions.CHANGELOG
    paragraph = "- %s: change record `%s` from the project `%s`, proven by the fixture `%s` (`wayline evolve`)." % (
        record.get("title") or record["id"], record["id"], Path(project).name, record["fixture"])
    text = changelog.read_text(encoding="utf-8") if changelog.is_file() else ""
    if paragraph not in text:
        changelog.write_text(versions.add_unreleased(text, paragraph), encoding="utf-8")
    commit = commit_all(worktree, "Change record %s: the changelog and the fixture's baseline" % record["id"])
    return commit, versions.run_checks(worktree, run)


def _landed(harness_root, branch, main):
    """How `main` holds the branch: `ancestor` (merged), `content` (squashed or rebased: every file it wrote is on `main` as the branch has it), or None."""
    tip = versions.git(harness_root, "rev-parse", branch).stdout.strip()
    if versions.git(harness_root, "merge-base", "--is-ancestor", tip, main, ok=None).returncode == 0:
        return "ancestor", tip
    base = versions.git(harness_root, "merge-base", tip, main).stdout.strip()
    written = [path for path in versions.git(harness_root, "diff", "--name-only", base, tip).stdout.splitlines()
               if path and path != versions.CHANGELOG]
    if written and versions.git(harness_root, "diff", "--quiet", tip, main, "--", *written, ok=None).returncode == 0:
        return "content", tip
    return None, tip


def settle_global(project, harness_root=HARNESS_ROOT, tag=None):
    """Tag every global change the harness `main` now holds, and say which still wait; `{"tagged": [...], "waiting": [...]}`.

    The owner merges `evolve/<id>`; the next `wayline evolve` finds it on `main`, releases a tag over it the way a
    promotion does (`evolve.release`: the changelog entry, the package version, the tag, `tagged`), and marks the
    record `applied`. A tag that already covers the merge is taken as the record's.
    """
    project, harness_root = Path(project).resolve(), Path(harness_root).resolve()
    settled = {"tagged": [], "waiting": []}
    waiting = [record for record in read_changes(project) if record["status"] == AWAITING_OWNER]
    if not waiting:
        return settled
    main = versions.main_branch(harness_root)
    for record in waiting:
        if not versions.exists(harness_root, "refs/heads/" + record["branch"]):
            settled["waiting"].append("%s: the branch %s is gone from %s" % (record["id"], record["branch"], harness_root))
            continue
        state, tip = _landed(harness_root, record["branch"], main)
        if state is None:
            settled["waiting"].append("%s: %s is not merged into the harness %s yet" % (record["id"], record["branch"], main))
            continue
        revision = tip if state == "ancestor" else main
        covering = [line.strip() for line in versions.git(harness_root, "tag", "--contains" if state == "ancestor" else "--points-at",
                                                          revision).stdout.splitlines() if versions.parse_tag(line.strip())]
        if covering:
            released = sorted(covering, key=versions.parse_tag)[0]
            remove_global_worktree(harness_root, dict(record, status=OPEN))
        else:
            released = versions.release(harness_root, main, tag, project, {"branch": record["branch"], "worktree": record["worktree"]})["tag"]
        set_status(project, record["id"], APPLIED, tag=released)
        settled["tagged"].append("%s: %s" % (record["id"], released))
    return settled


# --- the dashboard's view ---------------------------------------------------------------------------------


def changes_view(project):
    """`GET /api/projects/<id>/changes`: the feedback items with what was made of each, and the change records.

    A view writes nothing, and it is served without the token: a file the owner dropped that the journal does not
    hold yet is listed as `journaled: false`, and whoever next looks for pending feedback (`wayline evolve`, a
    wave) journals it. Each item carries an excerpt, not its text.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    events, _ = ledger.read_events()
    files, read, journaled = _files(ledger), read_state(ledger)["read"], _journaled(events)
    filed = {(event.get("payload") or {}).get(K_ID): event.get("ts") for event in events if event.get("event") == FEEDBACK}
    statuses = {ticket["id"]: ticket["status"] for ticket in read_tickets(project)}
    items = []
    for identifier, source in list(journaled.items()) + [(identifier, FILE) for identifier in files if identifier not in journaled]:
        made = read.get(identifier)
        items.append({"id": identifier, "source": source, "ts": filed.get(identifier), "journaled": identifier in journaled,
                      "read": made is not None, "records": list((made or {}).get("records") or []),
                      "dismissed": (made or {}).get("dismissed"),
                      "excerpt": _one_line(_text_of(files[identifier]))[:EXCERPT_CHARS] if identifier in files else None})
    records = [dict(record, ticket_status=statuses.get(record.get("ticket"))) for record in read_changes(project)]
    return {"feedback": list(reversed(items)), "changes": list(reversed(records)),
            "pending": sum(1 for item in items if not item["read"]), "sources": list(SOURCES)}


# --- the verbs --------------------------------------------------------------------------------------------


def render_report(report):
    lines = []
    if report["launched"]:
        lines.append("evolved  %d item(s) into %d change record(s)" % (len(report["pending"]), len(report["records"])))
    elif not report["tagged"] and not report["waiting"]:
        lines.append("nothing  no feedback is pending and no global change waits")
    lines += ["  record  %s" % identifier for identifier in report["records"]]
    if report["tickets"]:
        lines.append("  harness ticket(s) %s filed; wayline run works them" % ", ".join(str(item) for item in report["tickets"]))
    if report["decisions"]:
        lines.append("  decision ticket(s) %s ask about the rung ladder; wayline answer <id> approve|decline" % ", ".join(str(item) for item in report["decisions"]))
    lines += ["  proposed %s: a global change under autonomy autonomous is never applied; wayline evolve --apply %s is the owner's"
              % (identifier, identifier) for identifier in report["proposed"]]
    lines += ["  dismissed %s: %s" % (identifier, reason) for identifier, reason in report["dismissed"].items()]
    lines += ["  recommend %s" % text for text in report["recommendations"]]
    lines += ["tagged   %s" % text for text in report["tagged"]]
    lines += ["waiting  %s" % text for text in report["waiting"]]
    return "\n".join(lines)


def feedback_command(args):
    """`wayline feedback "<text>" [--project <path>]`: file it, and leave it for the evolve loop."""
    parser = argparse.ArgumentParser(prog="wayline feedback", description="file feedback for the evolve loop")
    parser.add_argument("text", help="what should have gone better")
    parser.add_argument("--project", help="the project the feedback is about; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        item = file_feedback(find_project(options.project), options.text, source=CLI)
    except ChangeError as failure:
        print("wayline feedback: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError) as failure:
        print("wayline feedback: %s" % failure, file=sys.stderr)
        return 1
    print("feedback %s filed in %s" % (item["id"], item["path"]))
    print("  wayline evolve turns it into change records and harness tickets; a running conductor does so at its next wave")
    return 0


def evolve_command(args):
    """`wayline evolve ["<text>"] [--apply <id>] [--retrospective] [--tag <tag>] [--project <path>]`."""
    parser = argparse.ArgumentParser(
        prog="wayline evolve",
        description="turn feedback into change records, harness tickets, and fixtures; tag the global changes the harness main now holds")
    parser.add_argument("text", nargs="?", help="feedback to file before the evolver is launched")
    parser.add_argument("--apply", metavar="ID", help="file the harness ticket of a global change that was only proposed")
    parser.add_argument("--retrospective", action="store_true", help="file the retrospective over the journal first, when it earns one")
    parser.add_argument("--tag", help="the tag to make once main holds a global change (default: the next minor tag)")
    parser.add_argument("--project", help="the project to evolve; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.tag is not None and versions.parse_tag(options.tag) is None:
        print("wayline evolve: %r is not a tag; tags are spelled vMAJOR.MINOR.PATCH" % options.tag, file=sys.stderr)
        return 2
    try:
        project = find_project(options.project)
        if options.apply:
            record = apply_proposal(project, options.apply)
            print("applied  change record %s: harness ticket %d works on %s; wayline run works it" % (record["id"], record["ticket"], record["branch"]))
            return 0
        if options.text is not None:
            item = file_feedback(project, options.text, source=CLI)
            print("feedback %s filed in %s" % (item["id"], item["path"]))
        if options.retrospective:
            item = file_retrospective(project)
            print("retrospective %s" % ("%s filed" % item["id"] if item else "not filed: nothing in the journal since the last one earns it"))
        report = evolve(project, say=lambda text: print("  " + text), tag=options.tag)
    except gates.GateError as failure:  # a usage window or the hold on Fable's weekly window: the items stay pending
        print("wayline evolve: %s" % failure, file=sys.stderr)
        return 2
    except (ChangeError, versions.EvolveError, ProjectError, LedgerError, TicketError, registry.RegistryError, worker.LaunchError,
            worker.RoleError, ValidationError, OSError, ValueError) as failure:
        print("wayline evolve: %s" % failure, file=sys.stderr)
        return 1
    print(render_report(report))
    return 0
