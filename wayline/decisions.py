"""Decision tickets end to end (Implementation Decisions 5 and 8; BRIEF 6.6). Built by ticket 35.

A decision ticket is a question to the owner, or under autonomy `autonomous` to the decider, that
pauses its subgraph until it is answered. This module opens one, reads one back, and builds the
dashboard's decisions view.

**What a decision ticket carries.** Its frontmatter has `blocking` and `human_only` and nothing
else of the question, because the fields are exactly BRIEF 8.2's. The question, the options, the
recommended answer, and the evidence live in the body, under `## Decision`: bullets for a person,
then the machine copy as one `decision` record on the same `<!-- wayline:decision {...} -->` line
the grill writes into `DECISIONS.md`, with `ticket` set and `answer` null. `decision_record` reads
it back. A decision ticket written another way (the absorb's promotion ticket, the tick's login
ticket, one a person wrote) carries no record, and the view reads the text under `## Decision`.

**Opening one.** `open_decision` writes the ticket, adds it to the `blocked_by` of every ticket it
pauses, journals `ticket_created` and `decision_opened`, and notifies the owner, in that order;
the frontier rule of ticket 07 then holds it and everything that waits on it while it is open. An
`origin` names the ask: a second call with the same origin finishes what a crash left undone and
opens nothing new, so a result carried again after a restart asks nothing twice. `open_requested`
is what the conductor calls with a worker's `decision_requests`.

**Answering one** is `project.answer` (`wayline answer`, the dashboard's answer form, and a session
running that verb) and `project.journal_written_answers` (an answer written into the ticket file,
which the conductor and the tick journal). Each journals one `decision` with `decided_by: human`;
the conductor closes the ticket at its next wave, and the tick relaunches a conductor that is not
running (decision 7).

**The view.** `decisions_view` is `GET /api/projects/<id>/decisions`: the open decision tickets with
their question, options, evidence, and what they pause; the decision log with the decider's
decisions first; and the settings the page's controls start from.
"""

import hashlib
from pathlib import Path

from wayline import HARNESS_ROOT, grill, replay
from wayline.ledger import DECISION, DECISION_OPENED, TICKET_CREATED, TICKET_RERUN, Ledger
from wayline.notify import notify as send_notification
from wayline.project import AUTONOMY, ProjectError, answering_autonomy, pacing_thresholds, read_active, read_harness
from wayline.schedule import awaits_owner
from wayline.tickets import (
    DECISION as DECISION_KIND, SATISFIED, TicketError, answer_section, build_graph, empty_graph, filename, next_id,
    open_decisions, paused_by, read_graph, read_ticket, read_tickets, refresh_graph, relative_path, section,
    tickets_dir, write_ticket,
)

__all__ = [
    "DECISION_HEADING", "BLOCKINGS", "PAUSABLE", "decision_record", "decision_question", "decision_body",
    "open_decision", "open_requested", "requested_origin", "decisions_view", "decision_log", "decider_ready",
]

DECISION_HEADING = "## Decision"
# What `blocking` may say on a ticket a worker or the planner asks for (the frontmatter also allows null).
BLOCKINGS = ("subgraph", "all")
# The statuses a ticket is paused from: work not started, or stopped and waiting for another attempt. A
# running ticket is left to finish, because its attempt writes the ticket file back from what it read.
PAUSABLE = ("open", "failed", "blocked", "needs_human")
# The role a decision ticket names; the decider arrives with ticket 31.
DECIDER_ROLE = "decider"
TITLE_MAX = 72


def decider_ready(harness_root=None, project=None):
    """Whether a session can take a decision ticket: the `decider` role reads, which it does once ticket 31 installs it.

    Until then `schedule.awaits_owner` is told there is no decider, so under autonomy `autonomous` a decision ticket
    waits for the owner rather than being launched on a role that cannot be read and failed before it starts.
    """
    from wayline import worker  # the launcher, which the dashboard's views do not otherwise import
    try:
        worker.read_role(DECIDER_ROLE, harness_root or HARNESS_ROOT, project)
    except (ValueError, OSError):
        return False
    return True


# --- reading one back ---------------------------------------------------------------------------------


def decision_record(body):
    """The `decision` record in a decision ticket's body, or None when the body carries none.

    Raises `ProjectError` for a record that is there and is not a valid `decision`, as the grill does
    for one in `DECISIONS.md`: a hand edit is reported, never taken on trust.
    """
    for record in grill.parse_records(body, source="the ticket body"):
        if record.get("ticket") is not None:
            return record
    return None


def decision_question(fields, body):
    """The question a decision ticket asks: its record's, else the first paragraph under `## Decision`, else its title."""
    try:
        record = decision_record(body or "")
    except ProjectError:
        record = None
    if record is not None:
        return record["question"]
    written = section(body or "", DECISION_HEADING)
    if written:
        return _one_line(written.split("\n\n")[0])
    return (fields or {}).get("title")


# --- opening one ---------------------------------------------------------------------------------------


def _not_a_heading(text):
    """A line no reader of the body takes for a heading: a leading `#` escaped, as markdown shows it.

    The question is a line of its own under `## Decision`, and a question that read `## Answer` would
    otherwise be the owner's answer to `answer_section`.
    """
    return "\\" + text if text.startswith("#") else text


def _one_line(text):
    """Text on one line, with nothing in it that could end the section or hide the record below it."""
    return " ".join(str(text).split()).replace("<!--", "<\\!--")


def _title(question):
    """A title cut from the question on a word boundary: the file name is built from it."""
    if len(question) <= TITLE_MAX:
        return question
    cut = question[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (cut or question[:TITLE_MAX]) + "..."


def _ids(identifiers):
    return ", ".join(str(identifier) for identifier in identifiers)


def _named(identifiers):
    """`ticket 3` or `tickets 3, 4`."""
    return ("ticket %s" if len(identifiers) == 1 else "tickets %s") % _ids(identifiers)


def decision_body(record, paused=(), origin=None):
    """A decision ticket's body: the question for a person, its machine copy, and how to answer it."""
    identifier = record["ticket"]
    lines = [DECISION_HEADING, "", _not_a_heading(record["question"]), ""]
    if record.get("options"):
        lines += ["- options:"] + ["  - " + option for option in record["options"]]
    if record.get("recommended"):
        lines.append("- recommended: " + record["recommended"])
    if record.get("evidence"):
        lines += ["- evidence:"] + ["  - " + item for item in record["evidence"]]
    if record.get("blocking") == "all":
        lines.append("- blocking: `all`, so no other ticket launches until it is answered")
    elif paused:
        lines.append("- blocking: `subgraph`, so %s and whatever waits on %s wait for the answer"
                     % (_named(paused), "it" if len(paused) == 1 else "them"))
    else:
        lines.append("- blocking: `subgraph`, and no ticket waited on it when it was opened")
    lines.append("- human-only: yes, only the owner answers it" if record.get("human_only")
                 else "- human-only: no, so under autonomy `autonomous` the decider may answer it")
    if origin:
        lines.append("- asked by: " + _one_line(origin))
    lines += ["", grill.machine_line(record), "", "## How to answer", "",
              "`wayline answer %d \"<answer>\"`, from the command line or from a session; the answer form in the "
              "dashboard's decisions view; or the answer written under an `## Answer` heading at the end of this file. "
              "Each is journaled as the owner's decision, and the conductor closes this ticket at its next wave." % identifier]
    return "\n".join(lines) + "\n"


def _decision_opened(events, identifier):
    """Which of `ticket_created` and `decision_opened` the journal already holds for this ticket."""
    held = set()
    for event in events:
        name = event.get("event")
        if name in (TICKET_CREATED, DECISION_OPENED) and (event.get("payload") or {}).get("ticket") == identifier:
            held.add(name)
    return held


def open_decision(project, question, options=(), recommended=None, evidence=(), blocking="subgraph", human_only=False,
                  reversible=True, pauses=(), blocked_by=(), proposed_by="planner", origin=None, title=None,
                  context_pack=(), notify=None):
    """Open one decision ticket; returns `{"ticket", "opened", "paused"}`.

    `pauses` names the tickets that wait for the answer: each one not yet running or closed gets the
    new ticket in its `blocked_by`, and the frontier holds whatever waits on those in turn.
    `blocked_by` is what the question itself waits on, usually nothing. `origin` names the ask; a
    decision ticket that already carries it is completed rather than opened again: its missing
    pause edges are added, its missing events journaled, and the owner notified only when
    `decision_opened` is journaled by this call. `notify(event, text, project, ticket)` is the
    notifier, `wayline.notify.notify` by default.

    Raises `TicketError` for a question with no text, a `blocking` that is not `subgraph` or `all`,
    a ticket named that does not exist, or edges that would form a cycle; nothing is written then.
    """
    project = Path(project).resolve()
    question = _one_line(question or "")
    if not question:
        raise TicketError("a decision ticket needs a question")
    if blocking not in BLOCKINGS:
        raise TicketError("a decision ticket's blocking is subgraph or all, got %r" % (blocking,))
    options = [_one_line(option) for option in options or () if str(option).strip()]
    evidence = [_one_line(item) for item in evidence or () if str(item).strip()]
    recommended = _one_line(recommended) if recommended and str(recommended).strip() else None
    ledger = Ledger(project)
    with ledger.lock():
        existing = {ticket["id"]: ticket for ticket in read_tickets(project)}
        unknown = sorted((set(pauses) | set(blocked_by)) - set(existing))
        if unknown:
            raise TicketError("%s has no ticket %s for a decision ticket to name" % (project, _ids(unknown)))
        found = [ticket for ticket in existing.values()
                 if origin is not None and ticket["kind"] == DECISION_KIND and ticket.get("origin") == origin]
        identifier = found[0]["id"] if found else next_id(project)
        paused = sorted(ticket_id for ticket_id in set(pauses)
                        if ticket_id != identifier and existing[ticket_id]["status"] in PAUSABLE)
        rewritten = {ticket_id: dict(existing[ticket_id], blocked_by=sorted(set(existing[ticket_id]["blocked_by"]) | {identifier}))
                     for ticket_id in paused if identifier not in existing[ticket_id]["blocked_by"]}
        if found:
            fields = found[0]
            asked = decision_question(fields, read_ticket(tickets_dir(project) / filename(fields))[1])
        else:
            asked = question
            fields = {
                "id": identifier, "title": _one_line(title) if title else _title(question), "kind": DECISION_KIND,
                "difficulty": 1, "status": "open", "blocked_by": sorted(set(blocked_by)), "blocking": blocking,
                "human_only": bool(human_only), "touches": [], "role": DECIDER_ROLE, "skills": [], "acceptance": {},
                "context_pack": list(context_pack), "origin": origin, "proposed_by": proposed_by,
                "demo": "The owner%s answers: %s" % ("" if human_only else " or the decider", question),
            }
        after = dict(existing)
        after.update(rewritten)
        after[identifier] = fields
        build_graph(list(after.values()))  # a cycle raises before anything is written
        if not found:
            record = {"ticket": identifier, "question": question, "options": options, "recommended": recommended,
                      "evidence": evidence, "blocking": blocking, "human_only": bool(human_only), "reversible": bool(reversible),
                      "answer": None, "rationale": None, "confidence": None, "decided_by": None, "timestamp": None}
            body = decision_body(record, paused, origin)
            decision_record(body)  # the record reads back, or nothing is written
            write_ticket(ledger, fields, body)
        for ticket_id, ticket in sorted(rewritten.items()):
            _, text = read_ticket(tickets_dir(project) / filename(existing[ticket_id]))
            write_ticket(ledger, ticket, text)
        events, _ = ledger.read_events()
        held = _decision_opened(events, identifier)
        if TICKET_CREATED not in held:
            ledger.append_event(TICKET_CREATED, {"ticket": identifier, "kind": DECISION_KIND, "proposed_by": fields["proposed_by"],
                                                 "origin": fields.get("origin"), "blocked_by": fields["blocked_by"]}, ticket=identifier)
        announce = DECISION_OPENED not in held
        if announce:
            ledger.append_event(DECISION_OPENED, {"ticket": identifier, "blocking": fields.get("blocking"),
                                                  "human_only": bool(fields.get("human_only"))}, ticket=identifier)
    if announce:
        text = _notification(project, fields, asked, paused)
        (notify or send_notification)(DECISION_OPENED, text, project, identifier)
    return {"ticket": identifier, "opened": not found, "paused": paused}


def _notification(project, fields, question, paused):
    if fields.get("blocking") == "all":
        pauses = "It pauses every other ticket."
    elif paused:
        pauses = "It pauses %s." % _named(paused)
    else:
        pauses = "No ticket waits on it yet."
    return "%s: decision ticket %d%s asks: %s %s Answer with wayline answer %d \"<answer>\" or in the dashboard's decisions view." % (
        project.name, fields["id"], " (human only)" if fields.get("human_only") else "", question, pauses, fields["id"])


def requested_origin(requester, attempt, question):
    """The origin of the decision ticket a worker's result asked for: the ticket, the attempt, and the question it asked.

    The question is named by the first twelve hex of its hash, so the same result carried twice, and a resumed
    session of the same attempt asking the same question, open it once; another question is another ticket.
    """
    digest = hashlib.sha256(_one_line(question or "").encode("utf-8")).hexdigest()[:12]
    return "ticket %d attempt %d: decision request %s" % (requester, attempt, digest)


def open_requested(project, requester, attempt, requests, notify=None):
    """The decision tickets a worker's `decision_requests` ask for; the `open_decision` report of each, in order.

    Each pauses the tickets that wait on the requesting ticket, because a question the worker could
    not settle is about the work those tickets build on; what waits on them waits in turn. The
    requester's own ticket file is the ticket's context pack. The origin is the requester, the
    attempt, and the question (`requested_origin`), so the same result carried twice opens nothing
    twice and a later attempt that asks again is a new question.
    """
    tickets = {ticket["id"]: ticket for ticket in read_tickets(project)}
    if requester not in tickets:
        raise TicketError("%s has no ticket %s to have asked a decision" % (project, requester))
    dependents = sorted(ticket["id"] for ticket in tickets.values() if requester in ticket["blocked_by"])
    reports = []
    for request in requests or ():
        reports.append(open_decision(
            project, request.get("question"), options=request.get("options") or (), recommended=request.get("recommended"),
            evidence=request.get("evidence") or (), blocking=request.get("blocking") or "subgraph",
            human_only=bool(request.get("human_only")), pauses=dependents, proposed_by="worker:%d" % requester,
            origin=requested_origin(requester, attempt, request.get("question")), context_pack=[relative_path(tickets[requester])], notify=notify,
        ))
    return reports


# --- the view ------------------------------------------------------------------------------------------


def decisions_view(project):
    """The dashboard's decisions view: the open decision tickets, the decision log, and the controls' settings.

    Read-only: the graph is computed with `write=False` and nothing takes the ledger's lock, as every
    view the dashboard polls. What cannot be read lands in `problems`, and the rest is still built.
    """
    project = Path(project).resolve()
    harness = read_harness(project)
    ledger = Ledger(project)
    problems = []
    try:
        events, _ = ledger.read_events()
    except OSError as failure:
        events = []
        problems.append("journal: %s" % failure)
    view = replay.replay(events)
    fields, bodies = {}, {}
    try:
        for ticket in read_tickets(project):
            fields[ticket["id"]] = ticket
            if ticket["kind"] == DECISION_KIND:
                bodies[ticket["id"]] = read_ticket(tickets_dir(project) / filename(ticket))[1]
    except (ValueError, OSError) as failure:
        problems.append("tickets: %s" % failure)
    try:
        graph, _ = refresh_graph(project, ledger=ledger, events=events, write=False)
    except (ValueError, OSError) as failure:
        problems.append("graph.json: %s" % failure)
        graph = read_graph(project) or empty_graph()
    try:
        records = grill.read_records(project)
    except (ProjectError, OSError) as failure:
        records = []
        problems.append("DECISIONS.md: %s" % failure)
    autonomy = harness.get("autonomy")
    # Who answers is decided under the autonomy a running conductor holds, and whether a decider can be launched at all.
    answering, decider = answering_autonomy(project, harness, view), decider_ready(project=project)
    stop_at, cheap_at = pacing_thresholds(project, harness, view)
    active = read_active()
    return {
        "project": str(project),
        "open": [_open_entry(entry, fields.get(entry["id"]) or {}, bodies.get(entry["id"]) or "", graph, view, answering, decider, problems)
                 for entry in open_decisions(graph)],
        "log": decision_log(events, records, fields, bodies),
        "controls": {
            "autonomy": autonomy,
            "autonomy_levels": list(AUTONOMY),
            "stop_at": stop_at,
            "cheap_at": cheap_at,
            "paused_by_owner": view.paused_by_owner,
            "active": active is not None and active.resolve() == project,
        },
        "problems": problems,
    }


def _open_entry(entry, ticket, body, graph, view, autonomy, decider, problems):
    identifier = entry["id"]
    try:
        record = decision_record(body) or {}
    except ProjectError as failure:
        record = {}
        problems.append("ticket %d: %s" % (identifier, failure))
    if entry.get("blocking") == "all":
        pauses = sorted(item["id"] for item in graph["tickets"]
                        if item["id"] != identifier and item["kind"] != DECISION_KIND and item["status"] in PAUSABLE)
    else:
        pauses = sorted(item["id"] for item in graph["tickets"]
                        if item["id"] in paused_by(graph, [identifier]) and item["status"] not in SATISFIED + ("parked",))
    answered = view.answers.get(identifier)
    return {
        "id": identifier,
        "title": ticket.get("title"),
        "status": entry["status"],
        "blocking": entry.get("blocking"),
        "human_only": bool(entry.get("human_only")),
        "proposed_by": ticket.get("proposed_by"),
        "origin": ticket.get("origin"),
        "question": decision_question(ticket, body),
        "options": list(record.get("options") or []),
        "recommended": record.get("recommended"),
        "evidence": list(record.get("evidence") or []),
        "reversible": record.get("reversible", True),
        "pauses": pauses,
        "awaits": "owner" if awaits_owner(entry, autonomy, decider) else "decider",
        # Journaled and not yet closed by a conductor, or written into the file and not yet journaled.
        "answered": {"answer": answered.get("answer"), "decided_by": answered.get("decided_by")} if answered else None,
        "written": answer_section(body),
    }


def _ticket_of(payload, event):
    ticket = payload.get("ticket", event.get("ticket"))
    return ticket if isinstance(ticket, int) and not isinstance(ticket, bool) else None


def decision_log(events, records=(), tickets=None, bodies=None):
    """Every `decision` the journal holds, the decider's first, each with the question it answered.

    A decision naming a ticket takes its question from that ticket. One naming none is the grill's,
    matched to its record in `DECISIONS.md` by the answer the grill journals for it, or another
    decision of the owner's, such as the intake's goal, which carries its own words in `answer`. A
    ticket's answer is `superseded` once a later answer or a rerun of the ticket replaces it; a grill
    answer, once a later record in `DECISIONS.md` supersedes its question. Within the decider's and the
    owner's, the order is the journal's.
    """
    tickets, bodies = tickets or {}, bodies or {}
    records = list(records or ())
    by_answer = {grill.record_payload(record)["answer"]: record for record in records
                 if record.get("id") and record.get("answer") is not None}
    replaced = grill.superseded_by(records)
    entries, latest = [], {}
    for event in events:
        name, payload = event.get("event"), event.get("payload") or {}
        ticket = _ticket_of(payload, event)
        if name == TICKET_RERUN and ticket in latest:
            latest.pop(ticket)["superseded"] = True
            continue
        if name != DECISION:
            continue
        entry = {"ts": event.get("ts"), "ticket": ticket, "id": None, "question": None, "answer": payload.get("answer"),
                 "decided_by": payload.get("decided_by"), "rationale": payload.get("rationale"),
                 "confidence": payload.get("confidence"), "superseded": False}
        if ticket is not None:
            if ticket in latest:
                latest[ticket]["superseded"] = True
            latest[ticket] = entry
            entry["question"] = decision_question(tickets.get(ticket), bodies.get(ticket))
        else:
            record = by_answer.get(entry["answer"])
            if record is not None:
                entry.update(id=record["id"], question=record["question"], answer=record["answer"],
                             superseded=record["id"] in replaced)
        entries.append(entry)
    return ([entry for entry in entries if entry["decided_by"] == "decider"]
            + [entry for entry in entries if entry["decided_by"] != "decider"])
