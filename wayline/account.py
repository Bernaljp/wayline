"""The account: what wayline did in a project (Implementation Decision 17; ticket 89).

`research/ACCOUNT.md` is rendered by code alone, from the journal and the ledger, in the same pass as the reports
(`provenance.render_report` renders it after `REPORT.md`, and the conductor at the end of every wave), so the
reports stay about the science and the audit stays complete. A render that would write the file as it already
stands writes nothing and journals nothing; one that changes it journals `report_rendered` with `report: account`.

**What it holds.** Its first line says that code writes it, that the research is in `REPORT.md`, and that anything
the owner wants to tell the project goes to the conversation. Then, in order, with an empty section left out:

- **Where the project stands**: one paragraph (running since when, or ended and why; each objective's status; the
  stopping rule; each budget spent against its limit). The same paragraph opens the end notice.
- **Decided for you**: each decider decision and conductor default not yet reviewed, one line each, numbered by
  its place among the journal's `decision` events (`D1` onward), with when, what, the answer, the confidence,
  "on Opus while Fable was spent" where it applies, and a link to where its rationale already lives. A superseded
  decision leaves the list.
- **Waiting on you**: the decision tickets for the owner, the tickets needing a person, the proposed global
  harness changes (one wording: `wayline evolve --apply <id>`), the important unresolved references whose failure is
  final (ticket 105: the owner named it, or a standing passage, a concern, or an objective cites it), the reports
  edited and not yet turned into passages, a code repository still private at the order, and the outline's open
  proposals as one line with their count (ticket 104).
- **Changed without asking you**: every passage and finding journaled with `replaces_owner` (ticket 88), each with
  the owner's passage (or the consolidation made from the owner's text) it replaced, its reason, and its evidence; a
  consolidation the owner asked for is not listed (ticket 90).
  Every merge of a repeated inherited claim made at setup that still stands follows (ticket 95, `wayline.repeats`);
  the render takes the marks on the merges and contradictions batches first, so a merge marked split has left it.
- **Runs**: the latest run in full, earlier runs one table row each. Tokens, turns, and minutes come from
  `ticket_result`; no dollar figure is journaled, so none is shown.
- **Not pursued**: the parked proposals with their reason, the parked tickets, and the objective proposals not upheld
  with the verdict's reason (ticket 91).
- **Library**: how many cited references are not yet resolved, with a pointer to References' "Not yet resolved" list
  (ticket 105), then papers by dossier level, promotions not read in full, and dossiers that now resolve to another work.

**The edit rule.** The account is read-only, as the reports are: an edit is noticed by its hash against the last
`report_rendered` of the account, committed as it stood (`edited` on the next `report_rendered`), listed in the
next render's banner, and never taken in. `take_edit` is that rule for any code-rendered file.

**Reviewing.** A decision listed under "Decided for you" stays there until the owner lets it stand or reverses
it, by `wayline review <id> stand|reverse` or by marking its item: every unreviewed decision is an item of an open
`account_review` batch (ticket 79), marks `stand` and `reverse`, default `stand`. A review is journaled as
`reviewed`; a reviewed decision stays counted in its run. A reversal is the owner's own answer through the existing
verbs: a decision ticket is asked again (`ticket_rerun`) human-only and, with an answer, answered by the owner
(`project.answer`); a grill question is revised (`grill answer --revise`); a parked proposal the decider kept parked
is admitted; the paper's venue is the owner's next `wayline paper --venue`. Under `autonomous` a conversation the owner opens
starts with "Decided for you" as one numbered item recommending "let them stand", and the owner's yes is
`wayline review all stand --shown <ids>` (`review_all`), one `reviewed` per decision shown, and one decided since is left
listed (ticket 109). A reversal with no answer ("undo it")
reopens the decision human-only and asks in one line: a grill question or a proposal on a human-only decision ticket
(origin `review D<n>: ...`) whose answer the next render takes in (`_settle_reopened`). A mark that cannot be taken
is said in the banner. Nothing a review does stops a run.

**The end notice.** `end_notice` is the one notice a run end sends: the account's first paragraph, then "N decided
for you, M waiting on you", then the path. The conductor sends it after the run's end, and the tick when the
conductor died first.
"""

import argparse
import hashlib
import re
import subprocess
import sys
import time
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path

from wayline import batches, grill, pacing, replay, tickets
from wayline.cli import parse_args
from wayline.ledger import (
    ABSORBED, DECISION, DECISION_OPENED, DEMOTED, FINDING, PACING, PAPER_STARTED, PASSAGE, PAUSED,
    PROMOTED, PROPOSAL_ADMITTED, PROPOSAL_PARKED, REPORT_RENDERED, REVIEWED, RUN_ENDED, RUN_STARTED, TICKET_ACCEPTED,
    TICKET_CANCELLED, TICKET_CREATED, TICKET_DONE, TICKET_FAILED, TICKET_LAUNCHED, TICKET_NEEDS_HUMAN, TICKET_RERUN,
    TICKET_RESULT, VERDICT, WAVE, Ledger, LedgerError, now_ts,
)
from wayline.project import NEEDS_HUMAN_NOTES, ProjectError, find_project, read_harness

__all__ = [
    "ACCOUNT", "ACCOUNT_PATH", "REPORT_KIND", "FIRST_LINE", "TITLES", "STAND", "REVERSE", "REVIEWS", "AccountError",
    "Rendered", "account_view", "render_account", "take_edit", "commit_edit", "end_notice", "counts_line", "review", "settle_marks",
    "ALL", "review_all", "review_command",
]

ACCOUNT = "ACCOUNT.md"
ACCOUNT_PATH = "research/" + ACCOUNT
REPORT_KIND = "account"  # `report` on the account's `report_rendered`
FIRST_LINE = ("Code writes this file from the journal and the ledger and never reads it back: the research is in "
              "[REPORT.md](REPORT.md), and anything you want to tell the project goes to the conversation.")
TITLES = ("Where the project stands", "Decided for you", "Waiting on you", "Changed without asking you", "Runs",
          "Not pursued", "Library")
STAND, REVERSE = "stand", "reverse"
REVIEWS = (STAND, REVERSE)
OWNER = "owner"
# Who made a decision the owner reviews: the decider, or the conductor taking a default.
REVIEWED_BY = ("decider", "conductor")
REVIEW_BATCH = "account_review"
EDIT_COMMIT = "%s as edited by hand, kept as it stood"
IDENTITY = ("-c", "user.name=wayline", "-c", "user.email=wayline@localhost")
# A budget's hours are shown to a tenth: a finer figure would change the account at every wave of a run.
HOURS_PLACES = 1

# What `run_ended`'s reason says in the account's first paragraph.
REASONS = {
    "frontier_empty": "no work was left on the frontier",
    "goal_reached": "every goal the stopping rule waits on was reached",
    "objectives_closed": "the objectives the stopping rule waits on closed",
    "budget_spent": "a budget was spent",
    "stopped": "the owner stopped it",
    "stall_strict": "it stalled under the strict radius",
    "switched": "the owner switched to another project",
}
# A ticket's outcome in a run, from the last of these events the run journaled for it.
OUTCOMES = {TICKET_LAUNCHED: "running", TICKET_DONE: "done", TICKET_ACCEPTED: "accepted", TICKET_FAILED: "failed",
            TICKET_NEEDS_HUMAN: "needs a human", TICKET_CANCELLED: "cancelled", TICKET_RERUN: "rerun"}
# What a decision with no ticket is about: its answer opens with the subject's prefix.
PROPOSAL_PREFIX = "proposal "
VENUE_PREFIX = "paper venue: "
PROPOSAL_ANSWERS = ("admit", "keep parked")
# The origin of the human-only decision ticket a reversal with no answer opens: the decision, then what it was about.
REOPENED_ORIGIN = "review %s: %s"
_REOPENED = re.compile(r"^review (D[1-9][0-9]*): (grill Q[1-9][0-9]*|proposal .+)$")  # what a parked proposal's decision answers (`decider.ADMIT`, `decider.KEEP_PARKED`)
# A grill question's `decision` (`grill.record_payload`): its id, its question, then its answer.
_GRILL_ANSWER = re.compile(r"^(Q[1-9][0-9]*) (.*) Answer: (.*)$", re.S)


class AccountError(ValueError):
    """A review the account refuses: an unknown decision, one reviewed already, or a reversal it cannot apply."""


# --- what the account is rendered from -------------------------------------------------------------------


@dataclass
class _Context:
    project: Path
    events: list
    harness: dict
    tickets: dict
    bodies: dict
    now: float
    notes: list = field(default_factory=list)


def _context(project, now=None, events=None):
    project = Path(project).resolve()
    notes = []
    if events is None:
        events, _ = Ledger(project).read_events()
    try:
        harness = read_harness(project)
    except (ProjectError, OSError, ValueError) as failure:
        harness = {}
        notes.append("harness.json could not be read: %s" % failure)
    by_id, bodies = {}, {}
    try:
        for fields in tickets.read_tickets(project):
            by_id[fields["id"]] = fields
            if fields["kind"] == tickets.DECISION:
                bodies[fields["id"]] = tickets.read_ticket(tickets.tickets_dir(project) / tickets.filename(fields))[1]
    except (tickets.TicketError, OSError, ValueError) as failure:
        notes.append("the tickets could not be read: %s" % failure)
    if now is None:
        now = _resting_now(events)
    return _Context(project, events, harness, by_id, bodies, now, notes)


def _resting_now(events):
    """The moment the hours are counted to: now while a run is live, else when the last run ended.

    An ended project's account then stays as it is until something happens, rather than changing at every tick.
    """
    live = None
    for event in events:
        if event.get("event") == RUN_STARTED:
            live = True
        elif event.get("event") == RUN_ENDED:
            live = event.get("ts")
    if live is True or live is None:
        return time.time()
    return pacing.epoch(live) or time.time()


# --- the decisions ---------------------------------------------------------------------------------------


Decision = namedtuple("Decision", "id ts ticket record question answer decided_by rationale confidence model fallback_from")


def _decisions(context):
    """Every decision the decider or the conductor made that still stands, by its `D` id, oldest first."""
    from wayline.decisions import decision_log  # the decisions module imports the project module this one does
    try:
        records = grill.read_records(context.project)
    except (ProjectError, OSError, ValueError) as failure:
        records = []
        context.notes.append("DECISIONS.md could not be read: %s" % failure)
    log = decision_log(context.events, records, context.tickets, context.bodies)
    standing = [entry for entry in log if entry["decided_by"] in REVIEWED_BY and not entry["superseded"]]
    standing.sort(key=lambda entry: int(entry["decision"][1:]))
    found = []
    for entry in standing:
        record, question = entry["id"], entry["question"]
        settled = _GRILL_ANSWER.match(str(entry["answer"] or "")) if entry["ticket"] is None else None
        if record is None and settled:  # a grill answer `DECISIONS.md` no longer holds: its answer still names it
            record, question = settled.group(1), settled.group(2)
        found.append(Decision(entry["decision"], entry["ts"], entry["ticket"], record, question, entry["answer"], entry["decided_by"],
                              entry["rationale"], entry["confidence"], entry.get("model"), entry.get("fallback_from")))
    return found


def _reviews(events):
    """`{D id: the latest reviewed payload}`."""
    found = {}
    for event in events:
        if event.get("event") == REVIEWED:
            payload = event.get("payload") or {}
            found[payload.get("decision")] = dict(payload, ts=event.get("ts"))
    return found


def _unreviewed(context):
    reviewed = _reviews(context.events)
    return [decision for decision in _decisions(context) if decision.id not in reviewed]


def _subject(decision, context):
    if decision.ticket is not None:
        title = (context.tickets.get(decision.ticket) or {}).get("title")
        return "ticket %d%s" % (decision.ticket, ", *%s*" % title if title else "")
    if decision.record:
        return "%s, *%s*" % (decision.record, _one_line(decision.question))
    answer = str(decision.answer or "")
    if answer.startswith(PROPOSAL_PREFIX):
        return "parked %s" % answer.split(":", 1)[0]
    if answer.startswith(VENUE_PREFIX):
        return "the paper's venue"
    return "a question with no ticket"


def _answer_of(decision):
    answer = str(decision.answer or "")
    if decision.record and " Answer: " in answer:
        return answer.split(" Answer: ", 1)[1]
    if decision.ticket is None and answer.startswith(PROPOSAL_PREFIX):
        return answer.split(":", 1)[1].strip()
    if answer.startswith(VENUE_PREFIX):
        return answer[len(VENUE_PREFIX):]
    return answer


def _rationale_link(decision, context):
    """Where the decision's rationale already lives, as a link relative to `research/`."""
    if decision.ticket is not None and decision.ticket in context.tickets:
        name = tickets.filename(context.tickets[decision.ticket])
        return "[tickets/%s](tickets/%s)" % (name, name)
    if decision.record:
        return "[DECISIONS.md](DECISIONS.md)"
    return "[journal.jsonl](journal.jsonl), at %s" % _when(decision.ts)


def _decided_line(decision, context):
    confidence = "confidence %s" % _number(decision.confidence) if decision.confidence is not None else "no confidence given"
    fell_back = ", on Opus while Fable was spent" if decision.fallback_from else ""
    return "- %s, %s, %s: **%s** (by the %s, %s%s). Rationale: %s" % (
        decision.id, _when(decision.ts), _subject(decision, context), _one_line(_answer_of(decision)), decision.decided_by,
        confidence, fell_back, _rationale_link(decision, context))


# --- waiting on you ---------------------------------------------------------------------------------------


def _waiting(context):
    from wayline.decisions import decider_ready, decision_question  # the decisions module imports the project module
    from wayline.schedule import awaits_owner
    autonomy = context.harness.get("autonomy")
    decider = decider_ready(project=context.project)
    lines = []
    for number in sorted(context.tickets):
        fields = context.tickets[number]
        if tickets.is_open_decision(fields) and awaits_owner(fields, autonomy, decider):
            lines.append("- Decision ticket %d%s: %s Answer with `wayline answer %d \"<answer>\"`." % (
                number, " (human only)" if fields.get("human_only") else "",
                _one_line(decision_question(fields, context.bodies.get(number))), number))
    asked, why = {}, {}
    for event in context.events:
        if event.get("event") == TICKET_NEEDS_HUMAN:
            payload = event.get("payload") or {}
            asked[payload.get("ticket")] = payload.get("question")
            why[payload.get("ticket")] = NEEDS_HUMAN_NOTES.get(payload.get("reason"))
    for number in sorted(context.tickets):
        fields = context.tickets[number]
        if fields["status"] == "needs_human":
            lines.append("- Ticket %d, *%s*, needs a person%s: %s" % (
                number, fields["title"], " (%s)" % why[number] if why.get(number) else "",
                _one_line(asked.get(number) or "no question was journaled")))
    lines.extend(_global_changes(context))
    lines.extend(_unresolved_references(context))
    lines.extend(_edited_reports(context))
    lines.extend(_private_repository(context))
    lines.extend(_outline_proposals(context))
    return lines


def _outline_proposals(context):
    """The outline's open proposals as one line with their count (ticket 104): what "Proposed, not settled" lists."""
    from wayline import outline  # the outline reads every part of the ledger
    try:
        proposals = outline.open_proposals(context.project)
    except (LedgerError, OSError, ValueError) as failure:
        context.notes.append("the outline's proposals could not be read: %s" % failure)
        return []
    if not proposals:
        return []
    return ["- The outline has %d open proposal%s (merges of results to take or decline, inherited headings no objective "
            "checks, subsections to open as objectives): research/OUTLINE.md, under \"Proposed, not settled\"." % (
                len(proposals), "" if len(proposals) == 1 else "s")]


def _global_changes(context):
    """The global changes proposed and not applied, each in the one wording that applies it."""
    from wayline import changes  # the evolve loop pulls in the registry and the fixtures
    try:
        records = changes.read_changes(context.project)
    except (OSError, ValueError) as failure:
        context.notes.append("the change records could not be read: %s" % failure)
        return []
    return ["- Global change `%s`, *%s* (`%s` at `%s`, risk %s): proposed, not applied; `wayline evolve --apply %s` applies it." % (
        record["id"], record.get("title") or record["id"], record["mechanism"], record["target"], record["risk"], record["id"])
        for record in records if record["scope_kind"] == changes.GLOBAL and record["status"] == changes.PROPOSED]


def _unresolved_references(context):
    """The important unresolved references whose failure is final, one line each (ticket 105, `references.final`).

    Important: the owner named it, or a standing passage, a concern, or an objective cites it. Final: no service knows it,
    its `retry` flag gave up, or nothing can look it up; one still retrying is not listed, and one the owner left ("leave
    it") is settled until the paper order. Under every autonomy it is listed here; under `autonomous` it is never raised.
    """
    from wayline import references  # the references module reads every section and the dossiers
    try:
        return [references.waiting_line(item) for item in references.final(context.project)]
    except (OSError, ValueError, LedgerError) as failure:
        context.notes.append("the unresolved references could not be read: %s" % failure)
        return []


def _edited_reports(context):
    """The reports edited by hand and not yet turned into passages: an `edited` render of a report other than the account
    with no passage of the owner's after it."""
    lines, owner_since = [], False
    for event in reversed(context.events):
        name, payload = event.get("event"), event.get("payload") or {}
        if name == PASSAGE and payload.get("by") == OWNER:
            owner_since = True
        elif (name == REPORT_RENDERED and payload.get("edited") and payload.get("report") not in (REPORT_KIND,) and not owner_since
              and not payload.get("version")):  # a result's report lists its own edits, which are never taken in (ticket 101)
            lines.append("- %s was edited by hand (kept as it stood in commit `%s`); what it says becomes passages when you say so in the conversation." % (
                "REPORT.md" if payload.get("report") in (None, "general") else payload.get("report"), str(payload["edited"])[:12]))
    return list(reversed(lines))


def _private_repository(context):
    from wayline import code_repository
    try:
        record = code_repository.record(context.project)
    except (ProjectError, OSError, ValueError):
        return []
    ordered = any(event.get("event") == PAPER_STARTED for event in context.events)
    if not ordered or not record.get("remote") or record.get("visibility") != "private":
        return []
    return ["- The code repository `%s` is still private, and the paper order names it; making it public is your word alone." % record["remote"]]


# --- changed without asking you ---------------------------------------------------------------------------


def _changed(context):
    """Every passage and finding the journal carries with `replaces_owner` (ticket 88): each replaced an owner's passage, or a
    consolidation made from the owner's text, without asking. A consolidation the owner asked for is never flagged.

    The id a replacement names may be one the owner's passage had already replaced (the ledger follows it to what
    stood in its place), so the passage named is the owner's one standing there when the replacement came.
    """
    from wayline import sections
    try:
        log = sections.read_passages(context.project) + sections.read_findings(context.project)
    except (OSError, ValueError, LedgerError):
        log = []
    lines = []
    for event in context.events:
        name, payload = event.get("event"), event.get("payload") or {}
        if name not in (PASSAGE, FINDING) or not payload.get("replaces_owner"):
            continue
        replaced = _owners_passage(log, payload.get("replaces"), payload.get("id"), str(event.get("ts") or ""))
        section = replaced.get("section") or (payload.get("section") if name == PASSAGE else "results")
        by = payload.get("by") if name == PASSAGE else "a finding of ticket %s" % payload.get("ticket")
        lines.append("- Your passage %s in %s, \"%s\", was replaced by %s (%s): %s%s." % (
            replaced.get("id") or payload.get("replaces"), sections.TITLES.get(section, section),
            _one_line(replaced.get("text")) or "no longer in the log", payload.get("id"), by,
            _one_line(payload.get("reason") or "no reason was given"),
            "; the evidence %s it" % payload["evidence"] if payload.get("evidence") else ""))
    from wayline import repeats  # the repeated-claims check reads the sections and the batches
    return lines + repeats.account_lines(context.project)


def _owners_passage(log, replaces, replacing, before):
    """The owner's passage (or consolidation of the owner's text) at `replaces` or standing in its place by the time
    `replacing` came (`before`, its event's time); `{}` when the log holds none."""
    children = {}
    for item in log:
        if item.get("replaces") and item.get("id") != replacing and str(item.get("ts") or "") <= before:
            children.setdefault(item["replaces"], []).append(item)
    queue, seen = [item for item in log if item.get("id") == replaces], set()
    while queue:
        item = queue.pop(0)
        if item.get("id") in seen:
            continue
        seen.add(item.get("id"))
        if item.get("by") in (OWNER, "consolidation"):
            return item
        queue.extend(children.get(item.get("id"), []))
    return {}


# --- runs -------------------------------------------------------------------------------------------------


@dataclass
class _Run:
    number: int
    start: int
    end: int = None  # the index of its `run_ended`, None while it is live
    after: int = None  # the index where the next run starts (or the journal ends): the run-end gates lie between


def _runs(events):
    """Every run, from its `run_started` to its `run_ended`.

    A `run_ended` with no `run_started` open before it (a journal that lost its start, or waves taken without `run`)
    ends a run that began with the first event after the run before it, so its end is still told.
    """
    runs = []
    for index, event in enumerate(events):
        name = event.get("event")
        if name == RUN_STARTED:
            if runs:
                runs[-1].after = index
            runs.append(_Run(len(runs) + 1, index))
        elif name == RUN_ENDED and runs and runs[-1].end is None:
            runs[-1].end = index
        elif name == RUN_ENDED:
            start = runs[-1].end + 1 if runs else 0
            if runs:
                runs[-1].after = start
            runs.append(_Run(len(runs) + 1, start, end=index))
    if runs and runs[-1].after is None:
        runs[-1].after = len(events)
    return runs


def _span(run, events):
    stop = run.end + 1 if run.end is not None else run.after
    return events[run.start:stop]


def _usage_tokens(usage):
    usage = usage if isinstance(usage, dict) else {}
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return tuple(usage.get(key) if _is_number(usage.get(key)) else 0 for key in keys)


def _per_ticket(span):
    """Per ticket: outcome, verdict type, model, turns, minutes, and tokens, from one run's events."""
    found = {}
    for event in span:
        name, payload = event.get("event"), event.get("payload") or {}
        ticket = payload.get("ticket", event.get("ticket"))
        if not isinstance(ticket, int) or isinstance(ticket, bool):
            continue
        entry = found.setdefault(ticket, {"outcome": None, "verdict": None, "model": None, "turns": 0, "ms": 0,
                                          "tokens": (0, 0, 0, 0), "sessions": 0})
        if name in OUTCOMES:
            entry["outcome"] = OUTCOMES[name]
            if name == TICKET_FAILED and payload.get("next"):
                entry["outcome"] = "failed, next %s" % payload["next"]
        if name == TICKET_LAUNCHED:
            entry["model"] = payload.get("model")
        elif name == TICKET_RESULT:
            entry["sessions"] += 1
            entry["turns"] += payload.get("turns") if _is_number(payload.get("turns")) else 0
            entry["ms"] += payload.get("duration_ms") if _is_number(payload.get("duration_ms")) else 0
            entry["tokens"] = tuple(a + b for a, b in zip(entry["tokens"], _usage_tokens(payload.get("usage"))))
            if payload.get("model_ran"):
                entry["model"] = payload["model_ran"]
        elif name == VERDICT and payload.get("subject_kind") == "ticket":
            entry["verdict"] = "%s %s" % (payload.get("verdict_type"), "passed" if payload.get("pass") else "failed")
    return {ticket: entry for ticket, entry in found.items() if entry["sessions"] or entry["outcome"] or entry["verdict"]}


def _run_bounds(run, events, now):
    """`(start, end)` of a run in epoch seconds: to its `run_ended`, else to its last event when a later run started
    (a run that died with no end), else to `now` while it is live."""
    start = pacing.epoch(events[run.start].get("ts"))
    if run.end is not None:
        end = pacing.epoch(events[run.end].get("ts"))
    elif run.after < len(events):
        end = pacing.epoch(events[max(run.start, run.after - 1)].get("ts"))
    else:
        end = now
    return start, end


def _wall_hours(run, events, now):
    start, end = _run_bounds(run, events, now)
    return 0.0 if start is None or end is None else max(0.0, end - start) / 3600.0


def _gpu_hours(run, events, now):
    """The GPU hours spent during the run, counted as the GPU budget counts them (`stopping.gpu_hours`): a job carried
    over from an earlier run counts its hours in this one, and a job that failed counts too."""
    from wayline import stopping  # the stopping module imports the goal module, which imports the gates
    start, end = _run_bounds(run, events, now)
    if start is None or end is None:
        return 0.0
    stop = run.end + 1 if run.end is not None else run.after
    return max(0.0, stopping.gpu_hours(events[:stop], end) - stopping.gpu_hours(events[:run.start], start))


def _waves(span):
    return sum(1 for event in span if event.get("event") == WAVE)


def _tokens_text(tokens):
    fresh, out, read, written = tokens
    return "%d (%d in, %d out, %d cache read, %d cache written)" % (fresh + out + read + written, fresh, out, read, written)


def _latest_run(run, context):
    events = context.events
    span = _span(run, events)
    started = events[run.start]
    if run.end is None:
        ending = "running"
    else:
        reason = (events[run.end].get("payload") or {}).get("reason")
        ending = "ended %s: %s (`%s`)" % (_when(events[run.end].get("ts")), REASONS.get(reason, "no reason was journaled"), reason)
    lines = ["### Run %d, the latest" % run.number, "",
             "Started %s, %s; %d wave(s). Wall clock %.1f hours; GPU %.2f hours." % (
                 _when(started.get("ts")), ending, _waves(span), _wall_hours(run, events, context.now), _gpu_hours(run, events, context.now))]
    peaks = _peaks(span)
    if peaks:
        lines[-1] += " Peak utilization: %s." % ", ".join("%s %s" % (window, _number(value)) for window, value in sorted(peaks.items()))
    lines.extend([""] + _pauses(span))
    per = _per_ticket(span)
    if per:
        lines.extend(["", "| Ticket | Kind | Outcome | Verdict | Model | Turns | Minutes | Tokens |", "|---|---|---|---|---|---|---|---|"])
        for ticket in sorted(per):
            entry, fields = per[ticket], context.tickets.get(ticket) or {}
            lines.append("| %d | %s | %s | %s | %s | %d | %.1f | %s |" % (
                ticket, fields.get("kind", "?"), entry["outcome"] or "not closed", entry["verdict"] or "none",
                entry["model"] or "none", entry["turns"], entry["ms"] / 60000.0, _tokens_text(entry["tokens"])))
        total = [sum(entry["tokens"][index] for entry in per.values()) for index in range(4)]
        lines.append("")
        lines.append("Total: %d turns, %.1f minutes, %s tokens; no dollar figure is journaled." % (
            sum(entry["turns"] for entry in per.values()), sum(entry["ms"] for entry in per.values()) / 60000.0,
            _tokens_text(total)))
    drawings = [ticket for ticket in sorted(per) if (context.tickets.get(ticket) or {}).get("kind") == "drawing"]
    if drawings:
        lines.extend(["", "Drawings:", ""])
        lines.extend("- Ticket %d%s: %s tokens, %d turns, %.1f minutes" % (
            ticket, _drawing_outcome(ticket, span, context.events), _tokens_text(per[ticket]["tokens"]), per[ticket]["turns"],
            per[ticket]["ms"] / 60000.0) for ticket in drawings)
    lines.extend(_gates(run, context))
    lines.extend(_fell_back(context.events[run.start:run.after], context))  # the run-end gates are the run's too
    return lines


def _drawing_outcome(ticket, span, events):
    """What a drawing ticket came to in this run, from its `drawing` events (ticket 100): accepted with what it drew and
    what it left out, or failed, its result keeping its last accepted drawing; empty while it is still open."""
    closed = [event.get("payload") or {} for event in span if event.get("event") == "drawing"
              and (event.get("payload") or {}).get("ticket") == ticket and (event.get("payload") or {}).get("outcome") in ("accepted", "failed")]
    if not closed:
        return ""
    last = closed[-1]
    name = "%s-%s" % (last.get("result"), last.get("version"))
    if last["outcome"] == "accepted":
        words = ", %s accepted: %s" % (name, ", ".join(last.get("plots") or []) or "no plot")
        left = ["%s (%s)" % (entry.get("what"), entry.get("reason")) for entry in last.get("left_out") or [] if isinstance(entry, dict)]
        if left:
            words += "; left out %s" % "; ".join(left)
        if last.get("retired"):
            words += "; retired %s" % ", ".join(last["retired"])
        return words
    earlier = [(event.get("payload") or {}).get("version") for event in events if event.get("event") == "drawing"
               and (event.get("payload") or {}).get("result") == last.get("result")
               and (event.get("payload") or {}).get("outcome") == "accepted"
               and int((event.get("payload") or {}).get("version") or 0) < int(last.get("version") or 0)]
    kept = ("%s keeps its last accepted drawing, %s-%s" % (last.get("result"), last.get("result"), earlier[-1]) if earlier
            else "%s keeps no accepted drawing yet" % last.get("result"))
    return ", %s failed (%s): %s, with no tier up, split, or ask" % (name, last.get("reason") or "no reason was journaled", kept)


def _pauses(span):
    lines = []
    for event in span:
        payload = event.get("payload") or {}
        if event.get("event") != PAUSED:
            continue
        if payload.get("model") == pacing.FABLE:
            lines.append("- Held the launches on Fable at %s: Fable's weekly window at %s until %s." % (
                _when(event.get("ts")), _number(payload.get("utilization")), payload.get("resets_at")))
        else:
            lines.append("- Paused at %s on the `%s` window at %s until %s." % (
                _when(event.get("ts")), payload.get("window"), _number(payload.get("utilization")), payload.get("resets_at")))
    return (["Pauses and holds:", ""] + lines) if lines else ["No pause and no hold."]


def _peaks(span):
    peaks = {}
    for event in span:
        payload = event.get("payload") or {}
        readings = []
        if event.get("event") == PACING:
            readings = [(window, payload.get(window)) for window in pacing.READINGS]
        elif event.get("event") == PAUSED:
            window = pacing.FABLE if payload.get("model") == pacing.FABLE else payload.get("window")
            readings = [(window, payload.get("utilization"))] if window in pacing.READINGS else []
        for window, value in readings:
            if _is_number(value):
                peaks[window] = max(peaks.get(window, value), value)
    return peaks


def _gates(run, context):
    """The run-end gates of a run that ended and the scope-downs they filed: the verdicts on the general report's claims
    and its kill argument, taken before the run's end (ticket 103; a `wayline report --verify` the owner ran in the run
    is listed with them), and every verdict and ticket after it until the next run started."""
    if run.end is None:
        return []
    from wayline import run_end  # the gates read the report, which renders this account
    after = [event for event in context.events[run.start:run.end] if run_end.is_gate_event(event)] + context.events[run.end + 1:run.after]
    verdicts = [event for event in after if event.get("event") == VERDICT]
    filed = [event for event in after if event.get("event") == TICKET_CREATED]
    if not verdicts and not filed:
        return []
    lines = ["", "The run-end gates:", ""]
    for event in verdicts:
        payload = event.get("payload") or {}
        lines.append("- `%s` on the %s `%s`: %s" % (payload.get("verdict_type"), payload.get("subject_kind"), payload.get("subject"),
                                                     "passed" if payload.get("pass") else "failed"))
    for event in filed:
        payload = event.get("payload") or {}
        lines.append("- scoped down by ticket %s (%s, origin %s)" % (payload.get("ticket"), payload.get("kind"), payload.get("origin")))
    return lines


def _fell_back(span, context):
    lines = []
    for event in span:
        payload = event.get("payload") or {}
        if not payload.get("fallback_from"):
            continue
        if event.get("event") == VERDICT:
            lines.append("- Verdict `%s` on the %s `%s`: %s, on %s (%s)" % (
                payload.get("verdict_type"), payload.get("subject_kind"), payload.get("subject"),
                "passed" if payload.get("pass") else "failed", payload.get("model") or "an unnamed model", _when(event.get("ts"))))
        elif event.get("event") == DECISION:
            ticket = payload.get("ticket")
            lines.append("- Decision by the %s on %s: **%s**, on %s (%s)" % (
                payload.get("decided_by"), "ticket %s" % ticket if ticket is not None else "a question with no ticket",
                _one_line(payload.get("answer")), payload.get("model") or "an unnamed model", _when(event.get("ts"))))
    if not lines:
        return []
    return ["", "On Opus while Fable was spent (none of them is taken again on Fable after the reset):", ""] + lines


def _earlier_runs(runs, context):
    if not runs:
        return []
    lines = ["", "Earlier runs:", "", "| Run | Started | Ended | Reason | Waves | Tickets closed | Turns | Wall clock (h) | GPU (h) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for run in runs:
        span = _span(run, context.events)
        per = _per_ticket(span)
        end = context.events[run.end] if run.end is not None else None
        lines.append("| %d | %s | %s | %s | %d | %d | %d | %.1f | %.2f |" % (
            run.number, _when(context.events[run.start].get("ts")), _when(end.get("ts")) if end else "never journaled",
            (end.get("payload") or {}).get("reason") if end else "none", _waves(span),
            sum(1 for entry in per.values() if entry["outcome"] in ("done", "accepted")), sum(entry["turns"] for entry in per.values()),
            _wall_hours(run, context.events, context.now), _gpu_hours(run, context.events, context.now)))
    return lines


def _runs_section(context):
    runs = _runs(context.events)
    if not runs:
        return []
    return _latest_run(runs[-1], context) + _docs_site(context) + _earlier_runs(runs[:-1], context)


def _docs_site(context):
    """The documentation site, part of done whenever a `code` ticket added public API (decisions 11, 13; ticket 51).

    Nothing when no ticket declared public API and none is a `docs` ticket. Otherwise the declaring tickets, the `docs`
    tickets and their statuses, the last build on `main` (`docs.read_record`), and every declaring ticket no closed
    `docs` ticket waits on, which is the site still owed.
    """
    from wayline import docs  # the docs module reads the code dossier's inventory
    from wayline.plan import adds_public_api
    bodies = {}
    for path in sorted(tickets.tickets_dir(context.project).glob("*.md")):
        try:
            fields, body = tickets.read_ticket(path)
        except (OSError, tickets.TicketError, ValueError):
            continue
        bodies[fields["id"]] = body
    ordered = [context.tickets[number] for number in sorted(context.tickets)]
    declared = [fields for fields in ordered if fields["kind"] == "code" and adds_public_api(bodies.get(fields["id"], ""))]
    documenting = [fields for fields in ordered if fields["kind"] == "docs"]
    if not declared and not documenting:
        return []
    lines = ["", "The documentation site, part of done because %s:" % (
        "ticket(s) %s added public API" % ", ".join(str(fields["id"]) for fields in declared)
        if declared else "the graph holds docs tickets"), ""]
    for fields in documenting:
        lines.append("- Ticket %d, *%s* (docs): %s" % (fields["id"], fields["title"], fields["status"]))
    record = docs.read_record(context.project)
    if record is None:
        lines.append("- The site has not been built on `main` (no `%s`)." % docs.CHECKS_JSON.as_posix())
    else:
        failed = [check["check"] for check in record.get("checks") or [] if not check.get("pass")]
        lines.append("- The site `%s`, built %s: %s." % (
            record.get("site") or docs.SITE_INDEX.as_posix(), record.get("ran_at") or "at an unrecorded time",
            "every machine check passed" if not failed else "the %s check(s) failed" % ", ".join(failed)))
    documented = set()  # a closed docs ticket documents what it waits on, directly or through the tickets it waits on
    for item in documenting:
        if item["status"] in tickets.SATISFIED:
            documented |= _upstream(context.tickets, item["id"])
    for fields in declared:
        if fields["id"] not in documented:
            lines.append("- Owed: ticket %d added public API and no closed docs ticket documents it." % fields["id"])
    return lines


def _upstream(by_id, identifier):
    """Every ticket `identifier` waits on, through any chain of `blocked_by`."""
    seen, stack = set(), list((by_id.get(identifier) or {}).get("blocked_by") or [])
    while stack:
        number = stack.pop()
        if number not in seen:
            seen.add(number)
            stack.extend((by_id.get(number) or {}).get("blocked_by") or [])
    return seen


# --- not pursued, the library ------------------------------------------------------------------------------


def _not_pursued(context):
    last = {}
    for event in context.events:
        if event.get("event") in (PROPOSAL_ADMITTED, PROPOSAL_PARKED):
            payload = event.get("payload") or {}
            last[payload.get("id")] = (event.get("event"), payload)
    lines = ["- Proposal `%s` from ticket %s (%s): parked, reason `%s`" % (
        identifier, payload.get("from"), payload.get("kind"), payload.get("reason"))
        for identifier, (name, payload) in last.items() if name == PROPOSAL_PARKED]
    lines.extend("- Ticket %d, *%s* (%s): parked" % (number, context.tickets[number]["title"], context.tickets[number]["kind"])
                 for number in sorted(context.tickets) if context.tickets[number]["status"] == "parked")
    from wayline import objective_changes  # the objective changes module reads the batches and the concerns
    lines.extend("- Objective proposal `%s` from ticket %s, %s %s: not upheld, %s" % (
        record["id"], record["ticket"], record["kind"], record["objective"], record["why"] or "no reason was given")
        for record in objective_changes.read_proposals(context.events) if record["upheld"] is False)
    return lines


def _library(context):
    from wayline import dossier as dossiers  # the dossier module pulls in the fetch seam
    from wayline import references  # the references module reads every section and the dossiers
    try:
        levels = dossiers.render_levels_report(context.project)
    except (OSError, ValueError) as failure:
        context.notes.append("the dossiers could not be read: %s" % failure)
        return []
    try:
        unresolved = references.unresolved_count(context.project)
    except (OSError, ValueError, LedgerError) as failure:
        context.notes.append("References could not be read: %s" % failure)
        unresolved = 0
    if not any(levels["by_level"].values()) and not unresolved:
        return []
    # The pointer to References' Not yet resolved list (ticket 105), with its count, while it lists anything.
    lines = ["- %d cited reference(s) not yet resolved: %s, under Not yet resolved." % (
        unresolved, "[References](sections/references.md#not-yet-resolved)")] if unresolved else []
    book = Ledger(context.project)

    def named(slug):
        try:
            found = dossiers.read_dossier(book, slug).get("existence") == "verified"
        except (dossiers.DossierError, OSError, ValueError):
            found = False
        return "`%s`%s" % (slug, "" if found else " (unresolved)")

    for level in sorted(levels["by_level"]):
        slugs = levels["by_level"][level]
        lines.append("- Level %d (%d): %s" % (level, len(slugs), ", ".join(named(slug) for slug in slugs) or "none"))
    promoted = {}
    for event in context.events:
        payload = event.get("payload") or {}
        name = event.get("event")
        if name == PROMOTED and payload.get("to_level") == 2:
            promoted[payload.get("slug")] = (event, payload)
        elif (name == ABSORBED and payload.get("level") == 2) or name == DEMOTED:
            promoted.pop(payload.get("slug"), None)
    unread = ["- `%s`: promoted to level 2 on `%s` (%s), and no level-2 read is journaled" % (
        slug, payload.get("trigger"), _when(event.get("ts"))) for slug, (event, payload) in promoted.items()]
    unread.extend("- `%s`: a promotion beyond the phase's reading budget waits on decision ticket %s" % (item["slug"], item["ticket"])
                  for item in levels["not_read_in_full"])
    if unread:
        lines.extend(["", "Promotions not read in full:", ""] + unread)
    moved = dossiers.another_work(context.project)
    if moved:
        lines.extend(["", "Dossiers that now resolve to another work, left as they were:", ""])
        lines.extend("- `%s` (level %s): filed as *%s*; a lookup now finds *%s* (%s)" % (
            slug, entry.get("level"), entry.get("filed"), (entry.get("now_resolves_to") or {}).get("title"),
            (entry.get("now_resolves_to") or {}).get("year")) for slug, entry in sorted(moved.items()))
    return lines


# --- where the project stands ------------------------------------------------------------------------------


def _stands(context):
    from wayline import stopping  # the stopping module imports the goal module, which imports the gates
    from wayline.objectives import ObjectivesUnreadable, read_objectives
    runs = _runs(context.events)
    if not runs:
        parts = ["No run has started yet."]
    elif runs[-1].end is None:
        parts = ["Running since %s (run %d)." % (_when(context.events[runs[-1].start].get("ts")), runs[-1].number)]
    else:
        ended = context.events[runs[-1].end]
        reason = (ended.get("payload") or {}).get("reason")
        parts = ["The last run (run %d) ended %s: %s." % (runs[-1].number, _when(ended.get("ts")), REASONS.get(reason, "no reason was journaled"))]
    try:
        records = read_objectives(context.project)
    except (ObjectivesUnreadable, OSError, ValueError) as failure:
        records = []
        context.notes.append(str(failure))
    if records:
        parts.append("Objectives: %s." % ", ".join("%s %s" % (record.get("id"), record.get("status")) for record in records))
    else:
        parts.append("No objective is recorded.")
    parts.append("Stopping rule: %s." % stopping.describe_rule(stopping.rule_of(context.harness)))
    budgets = context.harness.get("budgets") or {}
    used = {"wallclock_hours": stopping.wallclock_hours(context.events, context.now),
            "gpu_hours": stopping.gpu_hours(context.events, context.now)}
    words = {"wallclock_hours": "wall clock", "gpu_hours": "GPU"}
    spent = {name for name, _, _ in stopping.spent(context.harness, context.events, context.now)}
    shown = []
    for name in stopping.BUDGETS:
        limit = budgets.get(name)
        hours = round(used[name], HOURS_PLACES)
        if _is_number(limit):
            shown.append("%s %s of %s hours%s" % (words[name], _number(hours), _number(limit), ", spent" if name in spent else ""))
        else:
            shown.append("%s %s hours, no limit" % (words[name], _number(hours)))
    parts.append("Budgets: %s." % "; ".join(shown))
    return " ".join(parts)


# --- the view and the render ----------------------------------------------------------------------------------


def account_view(project, now=None, full=True, events=None):
    """What the account says, as a structure: the paragraph, each section's lines, and the counts. Writes nothing.

    `full=False` builds only the paragraph, "Decided for you", and "Waiting on you", which is what `status` and the end
    notice read: the rest walks every run, ticket, and dossier, and a view the dashboard polls need not.
    """
    context = _context(project, now, events)
    return _view(context, full)


def _view(context, full=True):
    unreviewed = _unreviewed(context)
    decided = [_decided_line(decision, context) for decision in unreviewed]
    waiting = _waiting(context)
    sections = {
        TITLES[0]: [_stands(context)],
        TITLES[1]: decided,
        TITLES[2]: waiting,
        TITLES[3]: _changed(context) if full else [],
        TITLES[4]: _runs_section(context) if full else [],
        TITLES[5]: _not_pursued(context) if full else [],
        TITLES[6]: _library(context) if full else [],
    }
    return {"project": str(context.project), "name": context.project.name, "stands": sections[TITLES[0]][0],
            "decided": len(decided), "waiting": len(waiting), "sections": sections, "notes": list(context.notes),
            "path": ACCOUNT_PATH, "unreviewed": [decision.id for decision in unreviewed]}


def counts_line(view):
    """"N decided for you, M waiting on you", with the path: the line the end notice and `status` carry."""
    return "%d decided for you, %d waiting on you: %s" % (view["decided"], view["waiting"], view["path"])


def _text(view, edited):
    """The file: the first line, the banner (the last edit by hand, and the notes), then the sections with something in them.

    `edited` is the last edit by hand, `(when, commit)`, or None; it stays in the banner from the render that noticed it.
    """
    lines = [FIRST_LINE, ""]
    if edited is not None:
        when, commit = edited
        lines.extend(["> %s was edited by hand (noticed %s). The edit was kept as it stood (%s) and is not taken in: the "
                      "account is rendered from the journal and the ledger." % (
                          ACCOUNT, _when(when), "commit `%s`" % commit[:12] if commit else "it could not be committed"), ""])
    for note in view["notes"]:
        lines.extend(["> note: %s" % note, ""])
    for title in TITLES:
        body = view["sections"][title]
        if not body:
            continue
        lines.extend(["## %s" % title, ""] + list(body) + [""])
    return "\n".join(lines).rstrip("\n") + "\n"


@dataclass
class Rendered:
    """One render of the account: its path, sha256, whether it changed the file, the edit it kept, and its view."""

    path: Path
    sha256: str
    changed: bool
    edited: object
    view: dict


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _last_render(events, report):
    for event in reversed(events):
        payload = event.get("payload") or {}
        if event.get("event") == REPORT_RENDERED and payload.get("report") == report:
            return payload
    return None


def _last_edit(events):
    """`(when, commit)` of the account's last render that noticed an edit by hand, or None."""
    for event in reversed(events):
        payload = event.get("payload") or {}
        if event.get("event") == REPORT_RENDERED and payload.get("report") == REPORT_KIND and "edited" in payload:
            return event.get("ts"), payload.get("edited") or ""
    return None


def take_edit(project, relative, report, events=None):
    """The edit rule of a code-rendered file: its edit, if any, committed as it stood. Returns the commit, "" or None.

    `relative` is the file under `research/`, `report` the `report` its renders journal. The file is edited when its
    sha256 differs from the last `report_rendered` of that report. The edit is committed alone, so the history keeps
    what the owner wrote; the next render overwrites it and never takes it in. None means no edit, "" an edit that
    could not be committed (no repository, say).
    """
    project = Path(project).resolve()
    if events is None:
        events, _ = Ledger(project).read_events()
    last = _last_render(events, report)
    path = project / "research" / relative
    if last is None or not path.is_file():
        return None
    if _digest(path.read_text(encoding="utf-8")) == last.get("sha256"):
        return None
    return commit_edit(project, relative)


def commit_edit(project, relative):
    """Commit `research/<relative>` alone, as the owner left it; returns the commit, or "" when it could not be committed."""
    project = Path(project).resolve()
    target = "research/" + relative
    git = ["git", "-C", str(project)]
    identity = [] if subprocess.run(git + ["config", "user.email"], capture_output=True, text=True).stdout.strip() else list(IDENTITY)
    added = subprocess.run(git + ["add", "--", target], capture_output=True, text=True)
    if added.returncode != 0:
        return ""
    done = subprocess.run(git + identity + ["commit", "-q", "-m", EDIT_COMMIT % relative, "--", target], capture_output=True, text=True)
    if done.returncode != 0:
        return ""
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True)
    return head.stdout.strip() if head.returncode == 0 else ""


def render_account(project, now=None):
    """Render `research/ACCOUNT.md` and journal `report_rendered` with `report: account` when it changed; a `Rendered`.

    First the owner's marks on the account's review batches are taken as reviews, an edit of the file is kept as it
    stood, and every unreviewed decision is put in an open review batch. A render that would leave the file as it is
    writes and journals nothing, so rendering again is idempotent.
    """
    project = Path(project).resolve()
    book, told = Ledger(project), []
    try:
        with book.lock():
            return _render(project, book, now, told)
    finally:
        _tell(told)


def _render(project, book, now, told):
    """`render_account` under the ledger's lock; the notices a reversal owes are put in `told`."""
    problems = []
    settle_marks(project, told, problems)
    from wayline import repeats
    try:
        problems.extend(repeats.take_marks(project))  # a merge the owner split leaves "Changed without asking you"
    except (repeats.RepeatsError, ValueError, OSError) as failure:
        problems.append("the marks on the merges and contradictions could not be taken: %s" % failure)
    context = _context(project, now)
    context.notes.extend(problems)
    edited = take_edit(project, ACCOUNT, REPORT_KIND, context.events)
    _batch_unreviewed(project, context)
    view = _view(context)
    stamp = now_ts()  # the edit is noticed at the time its render is journaled, which later banners read back
    noticed = (stamp, edited) if edited is not None else _last_edit(context.events)
    text = _text(view, noticed)
    digest = _digest(text)
    last = _last_render(context.events, REPORT_KIND)
    path = book.research / ACCOUNT
    if edited is None and last is not None and last.get("sha256") == digest and path.is_file():
        return Rendered(path, digest, False, None, view)
    path = book.write_markdown(ACCOUNT, text)
    payload = {"report": REPORT_KIND, "sha256": digest}
    if edited is not None:
        payload["edited"] = edited or None
    book.append_event(REPORT_RENDERED, payload, ts=stamp)
    return Rendered(path, digest, True, edited, view)


def end_notice(project, now=None):
    """The one notice a run end sends: the account's first paragraph, then the counts and the path (decision 17).

    Under `checkpoints` it also names the references raised and still waiting on the owner (ticket 105), which no notice
    of their own told of.
    """
    view = account_view(project, now, full=False)
    return "%s: %s %s%s" % (view["name"], view["stands"], _references_waiting(project), counts_line(view))


def _references_waiting(project):
    """"References waiting on you: ..." for the end notice under `checkpoints`, or "" when none waits or the autonomy is another."""
    from wayline import references  # the references module reads every section and the dossiers
    try:
        if read_harness(project).get("autonomy") != references.CHECKPOINTS:
            return ""
        waiting = references.waiting(project)
    except (ProjectError, OSError, ValueError, LedgerError):
        return ""
    if not waiting:
        return ""
    return "References waiting on you: %s. " % ", ".join("`%s`" % item["slug"] for item in waiting)


# --- reviews --------------------------------------------------------------------------------------------------


def _review_items(project):
    """`{D id: (batch, item)}` for every item of the account's review batches."""
    found = {}
    for batch in batches.read_batches(project):
        if batch["kind"] != REVIEW_BATCH:
            continue
        for item in batch["items"]:
            found[item["ref"]] = (batch, item)
    return found


def _batch_unreviewed(project, context):
    """Put every unreviewed decision no review batch holds yet in one new open batch: marks stand and reverse."""
    held = _review_items(project)
    fresh = [decision for decision in _unreviewed(context) if decision.id not in held]
    if not fresh:
        return None
    items = [{"ref": decision.id, "text": _decided_line(decision, context)[2:], "default": STAND} for decision in fresh]
    return batches.open_batch(project, REVIEW_BATCH, "Decided for you: let them stand or reverse them", items)


def settle_marks(project, told=None, problems=None):
    """Take the owner's marks on the account's review items as reviews; returns the D ids reviewed now.

    A `reverse` mark's note, when it has one, is what the owner wants instead; with none it is "undo it". A mark the
    decider gave is not a review: only the owner reviews what was decided for them. `told` collects the notices a
    reversal owes the owner, sent by the caller once it lets go of the ledger's lock (`_tell`), and `problems` each
    mark that could not be taken, which the account's banner says, since its item is settled and marks it no more.
    The owner's answers to the decisions a reversal reopened are taken first (`_settle_reopened`).
    """
    project = Path(project).resolve()
    _settle_reopened(project)
    events, _ = Ledger(project).read_events()
    reviewed = _reviews(events)
    standing = {decision.id for decision in _decisions(_context(project))}
    taken = []
    for ref, (batch, item) in sorted(_review_items(project).items()):
        if item["mark"] is None or item["by"] != OWNER or ref in reviewed or ref not in standing:
            continue  # one superseded since its item was opened has nothing left to review
        try:
            _apply(project, ref, item["mark"], item["note"] if item["mark"] == REVERSE else None, told)
        except AccountError as failure:
            if problems is not None:
                problems.append("your %s mark on %s (item %d of %s) could not be taken: %s; `wayline review %s %s` takes it again"
                                % (item["mark"], ref, item["id"], batch["id"], failure, ref, item["mark"]))
            continue
        taken.append(ref)
    return taken


def _tell(told):
    """Send the notices a reversal owes the owner, through the notifier, which holds back what the autonomy holds."""
    from wayline.notify import notify
    for event, text, project, ticket in told:
        notify(event, text, project=project, ticket=ticket)


def review(project, identifier, verdict, answer=None):
    """`wayline review <id> stand|reverse [--answer "<text>"]`: the owner's review of one decision made for them.

    Returns what happened, one line the conversation reads back. The decision's item in its review batch is marked
    too, so the marks view shows it settled. Refused for a decision that is not listed: unknown, superseded, or
    reviewed already. A reversal is applied first and journaled `reviewed` after, so a reversal refused before it
    changed anything leaves the decision listed.
    """
    project = Path(project).resolve()
    if verdict not in REVIEWS:
        raise AccountError("a review is %s, got %r" % (" or ".join(REVIEWS), verdict))
    answer = (str(answer).strip() or None) if answer is not None else None
    if verdict == STAND and answer is not None:
        raise AccountError("a decision let stand takes no answer; reverse it to answer it yourself")
    book, told = Ledger(project), []
    with book.lock():
        settle_marks(project, told)
        said = _apply(project, str(identifier), verdict, answer, told)
        held = _review_items(project).get(str(identifier))
        if held is not None and held[1]["mark"] is None:
            try:
                batches.mark(project, held[0]["id"], held[1]["id"], verdict, note=answer, by=OWNER)
            except batches.BatchError:
                pass  # settled meanwhile: the review journaled above is what counts
    _tell(told)
    return said


ALL = "all"  # `wayline review all stand`: the owner's yes to "Decided for you" as one item (ticket 109)


def review_all(project, shown):
    """Let stand each decision the owner was shown under "Decided for you": their yes to the autonomous opening (ticket 109).

    `shown` are the D ids the opening listed. A decision made after it, which the owner never saw, is left listed and
    named; a shown one that no longer stands or was reviewed meanwhile is a problem said, never a silent skip. Returns
    `(lines, problems)`: one line per decision let stand, then one naming what is still listed. The ledger is read and
    the marks settled once, under one lock, whatever the number. A reversal is never taken for all at once, since each
    one is the owner's own answer.
    """
    project = Path(project).resolve()
    book, told, lines, problems = Ledger(project), [], [], []
    shown = list(dict.fromkeys(str(identifier).strip() for identifier in shown if str(identifier).strip()))
    with book.lock():
        settle_marks(project, told)
        context = _context(project)
        listed = {decision.id: decision for decision in _unreviewed(context)}
        held = _review_items(project)
        for identifier in shown:
            decision = listed.pop(identifier, None)
            if decision is None:
                problems.append("%s is not listed under \"Decided for you\" now: reviewed already, superseded, or never a "
                                "decision made for you" % identifier)
                continue
            book.append_event(REVIEWED, {"decision": identifier, "review": STAND, "by": OWNER}, ticket=decision.ticket)
            lines.append("%s stands: %s" % (identifier, _one_line(_answer_of(decision))))
            item = held.get(identifier)
            if item is not None and item[1]["mark"] is None:
                try:
                    batches.mark(project, item[0]["id"], item[1]["id"], STAND, by=OWNER)
                except batches.BatchError:
                    pass  # settled meanwhile: the review journaled above is what counts
        if listed:
            lines.append("Still listed, decided after you were shown the list: %s (wayline review lists them)"
                         % ", ".join(sorted(listed, key=lambda identifier: int(identifier[1:]) if identifier[1:].isdigit() else 0)))
    _tell(told)
    return lines, problems


def _apply(project, identifier, verdict, answer, told=None):
    context = _context(project)
    reviewed = _reviews(context.events)
    if identifier in reviewed:
        raise AccountError("%s was reviewed already: %s at %s" % (identifier, reviewed[identifier].get("review"), _when(reviewed[identifier].get("ts"))))
    found = {decision.id: decision for decision in _decisions(context)}.get(identifier)
    if found is None:
        raise AccountError("%s is not a decision the decider or the conductor made that still stands; the account lists those "
                           "under \"Decided for you\"" % identifier)
    payload = {"decision": identifier, "review": verdict, "by": OWNER}
    if verdict == STAND:
        said = "%s stands: %s" % (identifier, _one_line(_answer_of(found)))
    else:
        said = _reverse(project, context, found, answer, told if told is not None else [])
        if answer is not None:
            payload["answer"] = answer
    Ledger(project).append_event(REVIEWED, payload, ticket=found.ticket)
    return said


def _reverse(project, context, decision, answer, told):
    """The owner's own answer in place of `decision`, through the verbs that already take one; human-only from now on.

    - A decision ticket is asked again, human-only (`_reopen`), and an answer is the owner's answer to it.
    - A grill question is revised by the owner's answer (`grill answer --revise`); with none, it is asked again on a
      human-only decision ticket, whose answer revises it (`_settle_reopened`).
    - A parked proposal the decider kept parked is admitted by `admit`; one it admitted has its ticket, which
      `wayline cancel` parks. With no answer it is asked again on a human-only decision ticket.
    - The paper's venue is named by the owner's next `wayline paper --venue <slug>`.

    Refused, with nothing written, for an answer the decision's verb would not take.
    """
    from wayline import decisions
    from wayline.project import answer as answer_ticket
    why = "The owner reversed %s." % decision.id
    prefix = _prefix_of(decision)
    proposal = decision.ticket is None and not decision.record and prefix.startswith(PROPOSAL_PREFIX)
    if proposal and answer is not None:
        answer = answer.casefold()
        if answer not in PROPOSAL_ANSWERS:
            raise AccountError("%s is about a parked proposal: reverse it with --answer \"%s\"" % (decision.id, "\" or \"".join(PROPOSAL_ANSWERS)))
        admitted = _admitted(context.events, prefix[len(PROPOSAL_PREFIX):].rstrip(": "))
        if answer != PROPOSAL_ANSWERS[0] and admitted is not None:
            raise AccountError("%s admitted that proposal as ticket %s; `wayline cancel %s` parks it" % (decision.id, admitted, admitted))
    if decision.ticket is None and not decision.record and not proposal:
        if answer is not None:
            raise AccountError("%s chose %s; name it yourself with `wayline paper --venue <slug>`, or reverse it with no answer"
                               % (decision.id, _subject(decision, context)))
        return "%s reversed: %s is yours to name, with wayline paper --venue <slug>." % (decision.id, _subject(decision, context))
    try:
        if decision.ticket is not None:
            question = _reopen(project, decision.ticket)
            if answer is None:
                return "%s reopened for you, human only: %s Answer with wayline answer %d \"<answer>\"." % (
                    decision.id, question, decision.ticket)
            try:
                answer_ticket(project, decision.ticket, answer, rationale=why)
            except ProjectError as failure:  # reopened for the owner all the same: the reversal stands, the answer waits
                return "%s reopened for you, human only, but your answer was refused (%s): %s Answer with wayline answer %d \"<answer>\"." % (
                    decision.id, failure, question, decision.ticket)
            return "%s reversed: ticket %d is answered \"%s\", by you; the conductor closes it at its next wave" % (
                decision.id, decision.ticket, answer)
        if answer is not None:
            if decision.record:
                grill.answer(project, decision.record, answer, why, revise=True)
                return "%s reversed: %s is revised to \"%s\", by you" % (decision.id, decision.record, answer)
            Ledger(project).append_event(DECISION, {"ticket": None, "answer": prefix + answer, "decided_by": "human",
                                                    "rationale": why, "confidence": None})
            return "%s reversed: %s%s, by you" % (decision.id, prefix, answer)
        subject = ("grill " + decision.record) if decision.record else prefix.rstrip(": ")
        question = (decision.question if decision.record else
                    "%s answered %s; what do you want instead (%s)?" % (
                        _subject(decision, context), _one_line(_answer_of(decision)), " or ".join(PROPOSAL_ANSWERS)))
        opened = decisions.open_decision(project, question or subject, blocking=None, human_only=True, proposed_by="human",
                                         origin=REOPENED_ORIGIN % (decision.id, subject),
                                         evidence=["the decider's answer, which you reversed: %s" % _one_line(_answer_of(decision))],
                                         notify=lambda event, text, where, ticket: told.append((event, text, where, ticket)))
    except (ProjectError, tickets.TicketError, grill.GrillError) as failure:
        raise AccountError("%s could not be reversed: %s" % (decision.id, failure)) from None
    return "%s reopened for you, human only: %s Answer with wayline answer %d \"<answer>\"." % (
        decision.id, _one_line(question), opened["ticket"])


def _admitted(events, identifier):
    """The ticket a proposal was admitted as, or None while it is parked."""
    ticket = None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == PROPOSAL_ADMITTED and payload.get("id") == identifier:
            ticket = payload.get("ticket")
    return ticket


def _settle_reopened(project):
    """Take the owner's answers to the decision tickets a reversal opened: a grill question revised, a proposal answered.

    A ticket reopened from a decision ticket needs nothing here: its answer is its own. Each answer is taken once: a
    grill question whose latest record is the owner's, or a proposal whose latest answer is the owner's, is left alone.
    """
    from wayline.proposals import _decided_answers
    book = Ledger(project)
    events, _ = book.read_events()
    view = replay.replay(events)
    try:
        opened = [fields for fields in tickets.read_tickets(project)
                  if fields["kind"] == tickets.DECISION and _REOPENED.match(str(fields.get("origin") or ""))]
    except (tickets.TicketError, OSError, ValueError):
        return
    for fields in opened:
        answered = view.answers.get(fields["id"])
        if not answered or answered.get("decided_by") != "human" or not str(answered.get("answer") or "").strip():
            continue
        decision, subject = _REOPENED.match(fields["origin"]).groups()
        why = "The owner answered decision ticket %d, which reopened %s." % (fields["id"], decision)
        text = str(answered["answer"]).strip()
        if subject.startswith("grill "):
            records = grill.read_records(project)
            latest, later = subject[len("grill "):], grill.superseded_by(records)
            while latest in later:
                latest = later[latest]
            record = {item.get("id"): item for item in records}.get(latest)
            if record is None or record.get("decided_by") == "human":
                continue
            try:
                grill.answer(project, latest, text, why, revise=True)
            except grill.GrillError:
                continue
        elif subject.startswith(PROPOSAL_PREFIX):
            identifier, choice = subject[len(PROPOSAL_PREFIX):], text.casefold()
            if choice not in PROPOSAL_ANSWERS or _human_proposal_answer(events, identifier) is not None:
                continue
            book.append_event(DECISION, {"ticket": None, "answer": PROPOSAL_PREFIX + identifier + ": " + choice,
                                         "decided_by": "human", "rationale": why, "confidence": None})


def _human_proposal_answer(events, identifier):
    """The owner's latest answer on a parked proposal, or None."""
    found = None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == DECISION and payload.get("decided_by") == "human" and payload.get("ticket") is None \
                and str(payload.get("answer") or "").startswith("%s%s:" % (PROPOSAL_PREFIX, identifier)):
            found = payload.get("answer")
    return found


def _prefix_of(decision):
    answer = str(decision.answer or "")
    if answer.startswith(PROPOSAL_PREFIX):
        return answer.split(":", 1)[0] + ": "
    if answer.startswith(VENUE_PREFIX):
        return VENUE_PREFIX
    return ""


def _reopen(project, identifier):
    """Ask a decision ticket again, human-only: its answer retired, `ticket_rerun` and `decision_opened` journaled.

    The rerun the conductor applies for `wayline rerun`, done here because the ticket runs no worker, so the frontier
    holds it for the owner at once whether a conductor runs or not. Returns its question.
    """
    from wayline.decisions import HUMAN_ONLY_NO, HUMAN_ONLY_YES, decision_question, decision_record
    book = Ledger(project)
    with book.lock():
        found = {fields["id"]: fields for fields in tickets.read_tickets(project)}.get(identifier)
        if found is None or found["kind"] != tickets.DECISION:
            raise AccountError("ticket %s is not a decision ticket of %s" % (identifier, project))
        fields, body = tickets.read_ticket(tickets.tickets_dir(project) / tickets.filename(found))
        try:
            record = decision_record(body)
        except ProjectError:
            record = None
        if record is not None and not record.get("human_only"):
            body = body.replace(grill.machine_line(record), grill.machine_line(dict(record, human_only=True)))
        body = tickets.retire_answer(body.replace(HUMAN_ONLY_NO, HUMAN_ONLY_YES))
        fields = dict(fields, status="open", human_only=True)
        tickets.write_ticket(book, fields, body)
        book.append_event(TICKET_RERUN, {"ticket": identifier, "by": OWNER}, ticket=identifier)
        book.append_event(DECISION_OPENED, {"ticket": identifier, "blocking": fields.get("blocking"), "human_only": True},
                          ticket=identifier)
    return _one_line(decision_question(fields, body))


def review_command(args):
    """`wayline review <id> stand|reverse [--answer "<text>"] [--project <path>]`, or `wayline review` to list them."""
    parser = argparse.ArgumentParser(prog="wayline review", description="let a decision made for you stand, or reverse it; with no id, list the ones not yet reviewed")
    parser.add_argument("id", nargs="?", help="the decision, D1 onward, as the account's \"Decided for you\" names it; all, with "
                                              "stand, for every one listed")
    parser.add_argument("verdict", nargs="?", choices=REVIEWS, help="stand, or reverse")
    parser.add_argument("--answer", help="with reverse: what you want instead; without one the decision is reopened for you")
    parser.add_argument("--shown", metavar="D1,D2,...", help="with all stand: the decisions the owner was shown, each let stand")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if options.id is None:
            view = account_view(project, full=False)
            for line in view["sections"][TITLES[1]] or ["Nothing is decided for you and not yet reviewed."]:
                print(line)
            return 0
        if options.verdict is None:
            print("wayline review: name the review, stand or reverse", file=sys.stderr)
            return 2
        if options.id == ALL:
            if options.verdict != STAND or options.answer is not None:
                print("wayline review: all takes stand alone; a reversal is your own answer, one at a time", file=sys.stderr)
                return 2
            if not options.shown:
                print("wayline review: all stand takes --shown, the D ids the owner was shown, so a decision made since is "
                      "not let stand unseen", file=sys.stderr)
                return 2
            lines, problems = review_all(project, options.shown.split(","))
            for line in lines:
                print(line)
            for problem in problems:
                print("wayline review: %s" % problem, file=sys.stderr)
            return 1 if problems else 0
        print(review(project, options.id, options.verdict, options.answer))
    except AccountError as failure:
        print("wayline review: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline review: %s" % failure, file=sys.stderr)
        return 1
    return 0


# --- shared helpers -------------------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text if text is not None else "").split())


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value):
    if isinstance(value, float):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value)


def _when(stamp):
    stamp = str(stamp or "")
    return stamp[:16].replace("T", " ") + "Z" if len(stamp) >= 16 else stamp or "?"
