"""Ticket files and `graph.json` (Implementation Decisions 2).

A ticket is `research/tickets/NN-slug.md`: the frontmatter of BRIEF 8.2 in the flat YAML subset
the `frontmatter` module reads and writes, then a markdown body. `NN` is the ticket's id, so the
file name and the frontmatter cannot disagree.

`graph.json` is regenerated from `tickets/` by code and is the only thing the conductor schedules
from; it holds the scheduling fields of Implementation Decisions 2 and nothing else. An
`os.scandir` snapshot of `tickets/` is stored beside them, so a regeneration that would change
nothing is skipped and `graph.json` stays byte-identical between waves.

The graph's `difficulty` is the effective one: a `pinned_difficulty` set by the human wins over
the ticket's own difficulty, because the conductor picks the model from the graph and escalation
never changes a pin.
"""

import os
import re
from pathlib import Path

from wayline.frontmatter import FrontmatterError, dump_document, load_document
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger

__all__ = [
    "TicketError", "TICKETS", "GRAPH", "SCHEDULING_FIELDS", "STATUSES", "SATISFIED", "DECISION",
    "HARDEST", "RESULT_HEADING",
    "slug", "filename", "parse_ticket", "read_ticket", "read_tickets", "write_ticket",
    "snapshot", "attempts_from_events", "build_graph", "read_graph", "refresh_graph",
    "frontier", "open_decisions", "is_open_decision", "by_status", "empty_graph", "tickets_dir", "with_result", "result_notes",
]

TICKETS = "tickets"
GRAPH = "graph.json"

# The scheduling fields of Implementation Decisions 2, in the spec's order.
SCHEDULING_FIELDS = (
    "id", "kind", "status", "difficulty", "blocked_by", "blocking", "human_only",
    "touches", "resources", "role", "skills", "attempt",
)

STATUSES = ("open", "running", "done", "accepted", "failed", "blocked", "needs_human", "parked")
# A blocker stops holding its dependents when it is done or accepted (the glossary's frontier).
SATISFIED = ("done", "accepted")
# The kind whose open tickets pause their subgraph, and the difficulty whose blockers need a verdict.
DECISION = "decision"
HARDEST = 5

# The heading the ledger appends an attempt's result under (Implementation Decisions 2).
RESULT_HEADING = "## Result"

_FILENAME_RE = re.compile(r"(\d+)-([a-z0-9][a-z0-9-]*)\.md\Z")
_SLUG_MAX = 48


class TicketError(ValueError):
    """A ticket file the harness cannot use: bad frontmatter, a name that disagrees with the id, a cycle."""


# --- names -----------------------------------------------------------------------------------


def slug(title):
    """The file-name half of `NN-slug.md`: lowercase words joined by single dashes."""
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(text) > _SLUG_MAX:
        text = text[:_SLUG_MAX].rstrip("-")
    if not text:
        raise TicketError("title %r has no characters a slug can be built from" % (title,))
    return text


def filename(ticket):
    """`NN-slug.md` for a ticket's frontmatter."""
    return "%02d-%s.md" % (ticket["id"], slug(ticket["title"]))


# --- reading ---------------------------------------------------------------------------------


def parse_ticket(text, source=None):
    """Parse one ticket file into `(frontmatter, body)`, validating the frontmatter."""
    where = str(source) if source else "ticket"
    try:
        fields, body = load_document(text)
    except FrontmatterError as failure:
        raise TicketError("%s: %s" % (where, failure)) from None
    try:
        check(fields, load_schema("ticket"), name=where)
    except ValidationError as failure:
        raise TicketError(str(failure)) from None
    return fields, body


def read_ticket(path):
    """Read one `tickets/NN-slug.md`; the leading number must be the ticket's id."""
    path = Path(path)
    fields, body = parse_ticket(path.read_text(encoding="utf-8"), source=path)
    match = _FILENAME_RE.match(path.name)
    if not match:
        raise TicketError("%s: a ticket file is named NN-slug.md (digits, a dash, a lowercase slug)" % path)
    if int(match.group(1)) != fields["id"]:
        raise TicketError("%s: the file name says ticket %d, the frontmatter says %d" % (path, int(match.group(1)), fields["id"]))
    return fields, body


def tickets_dir(project):
    """`<project>/research/tickets`."""
    return Path(project) / "research" / TICKETS


def read_tickets(project):
    """Every ticket of a project, by id; raises TicketError on a duplicate id or an unknown blocker."""
    directory = tickets_dir(project)
    tickets = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.md")):
            fields, _ = read_ticket(path)
            if fields["id"] in tickets:
                raise TicketError("ticket %d is defined twice under %s" % (fields["id"], directory))
            tickets[fields["id"]] = fields
    for ticket in tickets.values():
        for blocker in ticket["blocked_by"]:
            if blocker == ticket["id"]:
                raise TicketError("ticket %d blocks itself" % ticket["id"])
            if blocker not in tickets:
                raise TicketError("ticket %d is blocked by %d, which does not exist" % (ticket["id"], blocker))
    return [tickets[key] for key in sorted(tickets)]


def result_notes(result):
    """The lines of a result that no code reads yet, one short sentence each, or an empty list.

    A worker may return proposals, decision requests, and goal progress before the tickets that
    act on them exist (37, 35, and 39). They are written into the ticket body and said aloud
    rather than dropped, because a proposal nobody ever sees is worse than one that waits.
    """
    notes = []
    progress = result.get("goal_progress")
    if progress:
        notes.append("reported %s = %s" % (progress.get("metric"), progress.get("value")))
    proposals = result.get("proposals") or []
    if proposals:
        notes.append("proposed %s (ticket 37 admits proposals)"
                     % ", ".join("%s (%s)" % (item.get("title"), item.get("kind")) for item in proposals))
    requests = result.get("decision_requests") or []
    if requests:
        notes.append("asked %s (ticket 35 opens decision tickets)"
                     % "; ".join(item.get("question", "") for item in requests))
    return notes


def with_result(body, attempt, result):
    """The ticket body with this attempt's `## Result` section appended (Implementation Decisions 2)."""
    lines = ["### Attempt %d" % attempt, "",
             (result.get("summary") or "").strip() or "(the result carried no summary)"]
    for key, label in (("outputs_written", "Wrote"), ("commands_run", "Ran"), ("jobs", "Jobs")):
        items = result.get(key) or []
        if items:
            lines.extend(["", "%s: %s" % (label, ", ".join("`%s`" % item for item in items))])
    for note in result_notes(result):
        lines.extend(["", note[0].upper() + note[1:] + "."])
    text = body.rstrip("\n")
    if "\n" + RESULT_HEADING + "\n" not in text + "\n":
        lines = [RESULT_HEADING, ""] + lines
    return text + "\n\n" + "\n".join(lines) + "\n"


def write_ticket(ledger, fields, body=""):
    """Write `tickets/NN-slug.md` through the ledger; returns the path written."""
    if not isinstance(ledger, Ledger):
        ledger = Ledger(ledger)
    check(fields, load_schema("ticket"), name="ticket %s" % fields.get("id"))
    if body and not body.startswith("\n"):
        body = "\n" + body
    return ledger.write_markdown(TICKETS + "/" + filename(fields), dump_document(fields, body))


# --- the graph -------------------------------------------------------------------------------


def snapshot(project):
    """An `os.scandir` snapshot of `tickets/`: file name to `[size, mtime_ns]`, in name order."""
    directory = tickets_dir(project)
    seen = {}
    try:
        entries = list(os.scandir(directory))
    except (FileNotFoundError, NotADirectoryError):
        return seen
    for entry in entries:
        if not entry.name.endswith(".md") or not entry.is_file():
            continue
        info = entry.stat()
        seen[entry.name] = [info.st_size, info.st_mtime_ns]
    return {name: seen[name] for name in sorted(seen)}


def attempts_from_events(events):
    """The attempt counter per ticket, from the `ticket_launched` events of the journal."""
    attempts = {}
    for event in events or ():
        if event.get("event") != "ticket_launched":
            continue
        payload = event.get("payload") or {}
        identifier, attempt = payload.get("ticket"), payload.get("attempt")
        if isinstance(identifier, int) and isinstance(attempt, int):
            attempts[identifier] = max(attempts.get(identifier, 0), attempt)
    return attempts


def _entry(ticket, attempt):
    pinned = ticket.get("pinned_difficulty")
    return {
        "id": ticket["id"],
        "kind": ticket["kind"],
        "status": ticket["status"],
        "difficulty": ticket["difficulty"] if pinned is None else pinned,
        "blocked_by": list(ticket["blocked_by"]),
        "blocking": ticket.get("blocking"),
        "human_only": bool(ticket.get("human_only", False)),
        "touches": list(ticket["touches"]),
        "resources": ticket.get("resources"),
        "role": ticket["role"],
        "skills": list(ticket.get("skills") or []),
        "attempt": attempt,
    }


def empty_graph():
    """The graph of a project with no tickets; what `init` lays down."""
    return {"snapshot": {}, "tickets": []}


def build_graph(tickets, attempts=None, snap=None):
    """The graph for a list of ticket frontmatters; raises TicketError on a blocking cycle."""
    attempts = attempts or {}
    entries = [_entry(ticket, attempts.get(ticket["id"], 0)) for ticket in tickets]
    _check_acyclic(entries)
    return {"snapshot": dict(snap or {}), "tickets": entries}


def _check_acyclic(entries):
    """Depth-first over `blocked_by`; a cycle would starve the frontier without a word."""
    blockers = {entry["id"]: entry["blocked_by"] for entry in entries}
    OPEN, CLOSED = 1, 2
    state = {}
    for start in blockers:
        if state.get(start) == CLOSED:
            continue
        state[start] = OPEN
        stack = [(start, iter(blockers[start]))]
        while stack:
            node, children = stack[-1]
            descended = False
            for child in children:
                if child not in blockers or state.get(child) == CLOSED:
                    continue
                if state.get(child) == OPEN:
                    raise TicketError("the blocking edges form a cycle through ticket %d" % child)
                state[child] = OPEN
                stack.append((child, iter(blockers[child])))
                descended = True
                break
            if not descended:
                state[node] = CLOSED
                stack.pop()


# What every reader of a stored graph indexes without looking first; an entry missing one of
# these is not a graph entry, however well-formed the JSON around it is.
_REQUIRED_ENTRY_FIELDS = ("id", "kind", "status", "blocked_by")


def read_graph(project):
    """The stored `graph.json`, or None when it is missing, unreadable, or not a graph.

    A file a hand or a crash left half-written must not reach the frontier computation, which
    indexes these fields: None here means "regenerate", and every caller handles it.
    """
    try:
        graph = Ledger(project).read_json(GRAPH)
    except (OSError, ValueError):
        return None
    if not isinstance(graph, dict) or not isinstance(graph.get("tickets"), list):
        return None
    if not isinstance(graph.get("snapshot", {}), dict):
        return None
    for entry in graph["tickets"]:
        if not isinstance(entry, dict) or any(field not in entry for field in _REQUIRED_ENTRY_FIELDS):
            return None
        if not isinstance(entry["id"], int) or not isinstance(entry["blocked_by"], list):
            return None
    return graph


def refresh_graph(project, ledger=None, events=None, force=False, write=True):
    """Regenerate `graph.json` from `tickets/` when the snapshot or the attempts changed.

    Returns `(graph, regenerated)`. Nothing is written when the result would be what is already
    stored, so a status that changes nothing leaves the file byte-identical.

    `write=False` computes the same graph and writes nothing, which is how the dashboard reads a
    project: a view polled every few seconds must not take the ledger's lock to rewrite a file the
    conductor owns. `regenerated` then means the stored file is stale, not that it was rewritten.
    """
    ledger = ledger or Ledger(project)
    stored = read_graph(project)
    current = snapshot(project)
    attempts = attempts_from_events(events) if events is not None else None
    if stored is not None and not force:
        stored_attempts = {entry["id"]: entry.get("attempt", 0) for entry in stored["tickets"]}
        if stored.get("snapshot") == current and (attempts is None or attempts == _without_zeros(stored_attempts)):
            return stored, False
        if attempts is None:
            attempts = stored_attempts
    graph = build_graph(read_tickets(project), attempts or {}, current)
    if stored == graph:
        return stored, False
    if write:
        ledger.write_json(GRAPH, graph)
    return graph, True


def _without_zeros(attempts):
    """`attempts_from_events` omits a ticket never launched; a stored graph writes it as 0."""
    return {key: value for key, value in attempts.items() if value}


# --- views over the graph --------------------------------------------------------------------


def by_status(graph):
    """Ticket ids per status, in the status order of Implementation Decisions 2."""
    counts = {status: [] for status in STATUSES}
    for entry in graph["tickets"]:
        counts.setdefault(entry["status"], []).append(entry["id"])
    return counts


def frontier(graph):
    """Open tickets whose blockers are done or accepted (the glossary's frontier), by id.

    Wave step 7 of Implementation Decisions 5 states the two rules that narrow it further:

    - A difficulty-5 blocker counts only when it is `accepted`, not merely `done` (BRIEF 8.4: the
      hardest work is depended on only after a verifier has passed it, never on its own say-so).
      The difficulty read is the graph's effective one, so a `pinned_difficulty` of 5 counts too.
    - An open decision ticket pauses what it holds: with `blocking: subgraph` every ticket that
      waits on it, however far down the blocking edges; with `blocking: all` everything. Both
      leave the decision tickets themselves in the frontier, because a paused project must still
      be able to answer the question that paused it (the decider of ticket 35 is launched for one
      like any other ticket). A decision ticket is open until it is `done`, `accepted`, or
      `parked`; the answer paths that close one arrive with ticket 35.
    """
    entries = graph["tickets"]
    by_id = {entry["id"]: entry for entry in entries}
    ready = [entry for entry in entries
             if entry["status"] == "open"
             and all(_blocker_satisfied(by_id.get(blocker)) for blocker in entry["blocked_by"])]
    pending = [entry for entry in entries if is_open_decision(entry)]
    if any(entry.get("blocking") == "all" for entry in pending):
        ready = [entry for entry in ready if entry["kind"] == DECISION]
    else:
        paused = _paused_by(entries, [entry for entry in pending if entry.get("blocking") == "subgraph"])
        ready = [entry for entry in ready if entry["id"] not in paused or entry["kind"] == DECISION]
    return sorted(ready, key=lambda entry: entry["id"])


def _blocker_satisfied(blocker):
    """Whether a blocker holds its dependents no longer; an unknown id holds them (read_tickets refuses one)."""
    if blocker is None:
        return False
    if blocker.get("difficulty") == HARDEST:
        return blocker["status"] == "accepted"
    return blocker["status"] in SATISFIED


def open_decisions(graph):
    """The decision tickets still waiting for an answer, by id: the ones that pause the frontier.

    Open is every status but `done`, `accepted`, and `parked`: a decision whose decider failed or
    that is waiting on a person holds its subgraph exactly as an untouched one does, and a view
    that left it out would be a view that cannot say why a project stopped.
    """
    return sorted((entry for entry in graph["tickets"] if is_open_decision(entry)),
                  key=lambda entry: entry["id"])


def is_open_decision(entry):
    """Whether this graph entry is a decision ticket still waiting for an answer."""
    return entry["kind"] == DECISION and entry["status"] not in SATISFIED + ("parked",)


def _paused_by(entries, decisions):
    """The ids that wait on any of these decision tickets, down the blocking edges, transitively."""
    dependents = {}
    for entry in entries:
        for blocker in entry["blocked_by"]:
            dependents.setdefault(blocker, []).append(entry["id"])
    paused, stack = set(), [entry["id"] for entry in decisions]
    while stack:
        for identifier in dependents.get(stack.pop(), ()):
            if identifier not in paused:
                paused.add(identifier)
                stack.append(identifier)
    return paused
