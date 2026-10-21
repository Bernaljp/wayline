"""Objective changes: how the objectives change as results come in (Implementation Decision 17; ticket 91).

**Proposals.** A ticket result and a verdict carry `objective_proposals[]`, each `{kind, objective, reason, evidence,
feasibility}`: `kind` one of `add`, `answer`, `park`, `drop`, `reframe`, `reopen`; `objective` the objective's id, or
the new question's text for an `add`; a reframe's successor question in `successor`; `feasibility`, in the position
memo's row form, with an `add` and a `reframe`. Whoever proposes never makes the change. Each proposal is journaled as
`objective_proposed` (`take_result`, `take_verdict`); one code cannot act on (an objective the project does not hold, a
status the kind does not fit, a missing feasibility or successor) is journaled not upheld with code's reason.

**Judging.** A ticket that carries a proposal always gets its Type-B verdict, at every difficulty (`gates.ticket_asks`),
and that verdict judges each proposal upheld or not with a reason, in the same session (`judgment_text`,
`take_judgments`). The verifier that upholds an `answer` writes the objective's answer, which passes the numbers and
locator checks (`answer_problem`). A proposal the verifier makes inside its own verdict goes straight on. One not
upheld is journaled and listed in the account under "Not pursued".

**The batch.** Code gathers every upheld proposal into one open "Objective changes" decision ticket, whose items are a
batch of ticket 79 (marks approve and decline), and which takes new proposals until it is answered (`settle`). It
pauses the unstarted tickets that serve only an objective that an upheld `park`, `drop`, `reframe`, or `answer`
names; `add` and `reopen` pause nothing, and a declined proposal resumes what it paused.

**Who approves.** The owner, under `interactive` and `checkpoints`, by marking the items or answering the ticket
(`approve all`, `decline all`, `1: approve; 2: decline`). Under `autonomous` the decider takes the batch in one
session, within the rules of `decider_refusal`; what it may not take waits on the owner in a human-only ticket that
pauses nothing, so the tickets it paused resume. The owner's word in the conversation applies directly through the
`wayline objective` verbs (`apply_change` with no proposal), with no proposal and no verdict.

**When approved** (`apply_change`): an objective answered, parked, or dropped parks the unstarted tickets serving only
closed objectives (`ticket_cancelled` with the reason); claims tied only to closed objectives are set aside
(`objectives.set_aside`, shown in `SPEC.md`, back when one reopens); a reframe re-ties the tickets to the successor and
writes a Discussion passage; an answer is written by code as a Discussion passage; a reopen keeps the old answer as
superseded, brings back the tickets its park parked, and, for an answered or dropped objective, owes the planner a cut
of fresh tickets (`reopened`). When a drop is approved, the dropped objective's concerns are sorted in the same answer:
`K3: tie it to O1`, `K3: for the order`, or `K3: decline: <reason>` in the answer or in the drop item's note.

**Answering as it stands.** When the owner or the decider chose "answer it as it stands" at an empty frontier, or
approved an `answer` no verifier wrote, one fresh verifier session per objective on `opus high` writes the answer
(`answer_as_it_stands`), held to the same checks, and code writes it.
"""

import re

from wayline.ledger import OBJECTIVE, OBJECTIVE_PROPOSED, ledger_for

__all__ = [
    "KINDS", "PAUSING", "BATCH_KIND", "APPROVE", "DECLINE", "WORKER", "VERIFIER", "ANSWERING_TIER", "ProposalError",
    "read_proposals", "take_result", "take_verdict", "awaiting", "check_proposal", "judgment_text", "take_judgments",
    "answer_problem", "evidence_of", "apply_change", "reopened", "decider_refusal", "answer_marks", "placements_in",
    "is_changes_ticket", "settle", "answer_as_it_stands", "owed_answers",
]

KINDS = ("add", "answer", "park", "drop", "reframe", "reopen")
PAUSING = ("answer", "park", "drop", "reframe")       # the kinds whose upheld proposal pauses what serves only its objective
CLOSES = {"answer": "answered", "park": "parked", "drop": "dropped"}
CLOSED_STATUSES = ("answered", "parked", "dropped", "reframed")
FEASIBLE_KINDS = ("add", "reframe")                   # the kinds that come with the memo's feasibility row
WORKER, VERIFIER = "worker", "verifier"
BATCH_KIND = "objective_changes"
APPROVE, DECLINE = "approve", "decline"

_ID = re.compile(r"^O[1-9][0-9]*\Z")


class ProposalError(ValueError):
    """A change the module refuses to make: an objective it does not hold, an item it cannot read."""


def _one_line(text):
    return " ".join(str(text or "").split())


def _events(project_or_events):
    if isinstance(project_or_events, list):
        return project_or_events
    events, _ = ledger_for(project_or_events).read_events()
    return events


# --- the proposals, read back from the journal ---------------------------------------------------------------


def read_proposals(project_or_events):
    """Every objective proposal the journal holds, in the order first proposed, its judgment folded in.

    Each is `{id, kind, objective, successor, reason, evidence, feasibility, ticket, by, upheld, why, answer}`:
    `upheld` is None while it waits for its verdict.
    """
    found = {}
    for event in _events(project_or_events):
        if event.get("event") != OBJECTIVE_PROPOSED:
            continue
        payload = event.get("payload") or {}
        identifier = payload.get("id")
        stated = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else {}
        record = found.setdefault(identifier, {
            "id": identifier, "kind": payload.get("kind"), "objective": payload.get("objective"),
            "successor": stated.get("successor"), "reason": stated.get("reason"), "evidence": list(stated.get("evidence") or []),
            "feasibility": stated.get("feasibility"), "ticket": payload.get("ticket"), "by": payload.get("by"),
            "upheld": None, "why": None, "answer": None, "ts": event.get("ts")})
        if payload.get("upheld") is not None:
            record.update(upheld=payload["upheld"], why=payload.get("why"), answer=payload.get("answer"))
    return list(found.values())


def awaiting(project_or_events, ticket):
    """The proposals of `ticket`'s result still waiting for their verdict's judgment, in the order the worker gave them."""
    return [record for record in read_proposals(project_or_events)
            if record["ticket"] == ticket and record["by"] == WORKER and record["upheld"] is None]


def check_proposal(stated, records, owners_word=False):
    """Why code cannot act on one proposal, or None: the objective it names and the fields its kind needs.

    `records` are `objectives.json`'s objectives. An `add` names a question rather than an objective; every other kind
    names an objective the project holds, open for `answer`, `park`, `drop`, and `reframe`, closed for `reopen`. The
    owner's word through an objective verb (`owners_word`) comes with no feasibility row.
    """
    kind, named = stated.get("kind"), _one_line(stated.get("objective"))
    if kind not in KINDS:
        return "its kind %r is none of %s" % (kind, ", ".join(KINDS))
    if kind in FEASIBLE_KINDS and not owners_word and not isinstance(stated.get("feasibility"), dict):
        return "an %s proposal comes with its feasibility, in the position memo's row form, and this one has none" % kind
    if kind == "add":
        if _ID.match(named):
            return "an add proposal gives the new question's text, not an objective's id (%s)" % named
        return None
    if kind == "reframe" and not _one_line(stated.get("successor")):
        return "a reframe proposal gives its successor question in `successor`, and this one gives none"
    held = {record.get("id"): record for record in records or ()}
    if named not in held:
        return "it names %s, which is no objective the project holds (%s)" % (
            named or "nothing", ", ".join(sorted(held)) or "none yet")
    status = held[named].get("status")
    if kind == "reopen":
        if status not in ("parked", "answered", "dropped"):
            return "it reopens %s, which is %s; only a parked, answered, or dropped objective reopens" % (named, status)
    elif status != "open":
        return "it would %s %s, which is %s; only an open objective is %s" % (
            kind, named, status, {"answer": "answered", "park": "parked", "drop": "dropped", "reframe": "reframed"}[kind])
    return None


def _journal(ledger, identifier, stated, ticket, by, upheld=None, why=None, answer=None):
    payload = {"id": identifier, "kind": stated.get("kind"), "objective": _one_line(stated.get("objective")), "ticket": ticket,
               "by": by, "upheld": upheld, "why": why, "answer": answer, "proposal": dict(stated)}
    ledger.append_event(OBJECTIVE_PROPOSED, payload, ticket=ticket)


def _take(project, ticket, ids_and_proposals, by, upheld_by_default=None, why_by_default=None):
    """Journal each proposal not journaled yet: refused by code with its reason, else `upheld_by_default`."""
    from wayline.objectives import ObjectivesUnreadable, read_objectives  # the objectives module imports the gates

    ledger = ledger_for(project)
    with ledger.lock():
        known = {record["id"] for record in read_proposals(ledger.project)}
        fresh = [(identifier, stated) for identifier, stated in ids_and_proposals if identifier not in known]
        if not fresh:
            return
        try:
            records = read_objectives(ledger.project)
        except ObjectivesUnreadable as failure:
            raise ProposalError(str(failure)) from None
        for identifier, stated in fresh:
            problem = check_proposal(stated, records)
            if problem is not None:
                _journal(ledger, identifier, stated, ticket, by, upheld=False, why="not upheld by code: %s" % problem)
            else:
                _journal(ledger, identifier, stated, ticket, by, upheld=upheld_by_default, why=why_by_default)


def take_result(project, ticket, attempt, proposals):
    """Journal the objective proposals of a done ticket's result; returns those waiting for its verdict's judgment.

    Ids are `t<ticket>-a<attempt>/<n>`, so a result carried again after a restart journals nothing twice.
    """
    items = [("t%d-a%d/%d" % (ticket, attempt, number), stated)
             for number, stated in enumerate(proposals or [], start=1) if isinstance(stated, dict)]
    if items:
        _take(project, ticket, items, WORKER)
    return awaiting(project, ticket)


def take_verdict(project, ticket, attempt, verdict_type, proposals):
    """Journal the objective proposals a verdict made itself: upheld, since a proposal made inside a verdict goes straight on.

    Ids are `t<ticket>-a<attempt>/<verdict type>/<n>`; code still refuses one it cannot act on.
    """
    items = [("t%d-a%d/%s/%d" % (ticket, attempt, verdict_type, number), stated)
             for number, stated in enumerate(proposals or [], start=1) if isinstance(stated, dict)]
    if items:
        _take(project, ticket, items, VERIFIER, upheld_by_default=True,
              why_by_default="proposed inside ticket %d's %s verdict, which goes straight on" % (ticket, verdict_type))


# --- the verdict's judgment ------------------------------------------------------------------------------------


JUDGMENT = (
    "Besides, the ticket's result proposes these changes to the objectives (decision 17). Judge each one, by its number, in "
    "`objective_judgments`: `upheld` true when the work's own evidence bears the change out, with `why`. For an `answer` "
    "you uphold, write the objective's answer in `answer`, a paragraph in which every claim sentence ends with its "
    "{res:...} or {ref:...} tag and every number is at one of its res: locators; code checks both. A proposal you do not "
    "uphold is no finding and does not fail this verdict."
)


def _proposal_line(number, item):
    words = "%d. %s %s" % (number, item.get("kind"), _one_line(item.get("objective")))
    if item.get("kind") == "reframe":
        words += " as \"%s\"" % _one_line(item.get("successor"))
    words += ": %s" % _one_line(item.get("reason"))
    if item.get("evidence"):
        words += " Evidence: %s." % ", ".join("`%s`" % locator for locator in item["evidence"])
    feasibility = item.get("feasibility")
    if isinstance(feasibility, dict):
        words += " Feasibility: %s, %s" % (feasibility.get("verdict"), _one_line(feasibility.get("reasoning")))
    return words


def judgment_text(items):
    """The lines a verdict's question gains for the proposals it judges, numbered as `objective_judgments` names them."""
    return "\n".join([JUDGMENT] + [_proposal_line(number, item) for number, item in enumerate(items, start=1)])


def take_judgments(project, items, judgments):
    """Journal the verdict's judgment of each proposal it was given: `upheld`, `why`, and an upheld answer's text.

    `items` are the proposals as the verdict's question listed them; a proposal judged already is left as it was.
    """
    by_number = {entry.get("proposal"): entry for entry in judgments or [] if isinstance(entry, dict)}
    ledger = ledger_for(project)
    with ledger.lock():
        current = {record["id"]: record for record in read_proposals(ledger.project)}
        for number, item in enumerate(items or [], start=1):
            entry = by_number.get(number)
            record = current.get(item["id"])
            if entry is None or record is None or record["upheld"] is not None:
                continue
            upheld = bool(entry.get("upheld"))
            answer = _one_line(entry.get("answer")) if upheld and record["kind"] == "answer" and _one_line(entry.get("answer")) else None
            stated = {key: record[key] for key in ("kind", "objective", "successor", "reason", "evidence", "feasibility")
                      if record[key] is not None or key == "feasibility"}
            _journal(ledger, record["id"], stated, record["ticket"], record["by"], upheld=upheld,
                     why=_one_line(entry.get("why")) or None, answer=answer)


# --- an answer's checks ----------------------------------------------------------------------------------------


def answer_problem(project, text):
    """Why an objective's answer does not pass code's checks, or None: the locator check, then the numbers check.

    It cites at least one `res` or `ref` tag, every tag in it resolves as the provenance linter resolves it, and every
    number in a sentence that ends with a `res` tag is a value at one of its locators (the numbers check of ticket 90).
    """
    from wayline import numbers, provenance  # the provenance module pulls in the gates

    text = str(text or "")
    tags = provenance.ANY_TAG_RE.findall(text)
    if not any(kind in ("res", "ref") for kind, _ in tags):
        return "it cites no {res:...} or {ref:...} locator, so nothing bears it out"
    resolver = provenance.resolver_for(project)
    for kind, rest in tags:
        found = resolver.problem("%s:%s" % (kind, rest))
        if found is not None:
            return "its tag {%s:%s} does not resolve: %s" % (kind, rest, found[1])
    outcome = numbers.check([{"text": text, "provenance": []}], numbers.reader(project), exempt=numbers.spec_parameters(project))
    unmatched = [(number, sentence) for sentence in outcome.unmatched for number in sentence.unmatched]
    if unmatched:
        return "its number(s) %s are at none of the res: locators their sentence ends with" % ", ".join(
            number for number, _ in unmatched)
    return None


def _discussion(project, objective, text):
    """Code's Discussion passage about one objective, `by: objective:O<n>`; returns its P id."""
    from wayline import sections  # the sections module pulls in the provenance linter
    return sections.add_passage(project, "discussion", objective["text"], text, by="objective:%s" % objective["id"],
                                objectives=[objective["id"]])["id"]


# --- applying one change -----------------------------------------------------------------------------------------


_CANCELLED = "it serves only %s, which %s"
_SERVES = re.compile(r"^it serves only (.+?), which ")


def _serving_only(fields_list, named, records):
    """The work tickets not started or not running that serve only objectives in `named` or already closed, at least one of `named`."""
    from wayline.decisions import PAUSABLE
    from wayline.objectives import served
    held = {record.get("id"): record for record in records}
    found = []
    for fields in fields_list:
        serving = served(fields)
        if fields.get("kind") == "decision" or fields.get("status") not in PAUSABLE or not serving:
            continue
        if not set(serving) & set(named):
            continue
        if all(identifier in named or (identifier in held and held[identifier].get("status") != "open") for identifier in serving):
            found.append(fields)
    return found


def _park_tickets(project, identifier, status, by):
    """Park the unstarted tickets serving only closed objectives, at least `identifier`, each `ticket_cancelled` with why."""
    from wayline import tickets
    from wayline.ledger import TICKET_CANCELLED
    from wayline.objectives import read_objectives, served

    ledger = ledger_for(project)
    parked = []
    with ledger.lock():
        records = read_objectives(ledger.project)
        for fields in _serving_only(tickets.read_tickets(ledger.project), [identifier], records):
            closed = [name for name in served(fields)]
            why = _CANCELLED % (" and ".join(closed), "was %s" % status if len(closed) == 1 else "are closed (%s was %s)" % (identifier, status))
            path = tickets.tickets_dir(ledger.project) / tickets.filename(fields)
            current, body = tickets.read_ticket(path)
            tickets.write_ticket(ledger, dict(current, status="parked"), body)
            ledger.append_event(TICKET_CANCELLED, {"ticket": fields["id"], "by": by, "reason": why}, ticket=fields["id"])
            parked.append(fields["id"])
    return parked


def _restore_tickets(project, identifier, by):
    """The tickets a park of `identifier` parked go back to open now that it reopened, each `ticket_rerun`."""
    from wayline import tickets
    from wayline.ledger import TICKET_CANCELLED, TICKET_RERUN

    ledger = ledger_for(project)
    restored = []
    with ledger.lock():
        events, _ = ledger.read_events()
        why = {}
        for event in events:
            payload = event.get("payload") or {}
            if event.get("event") == TICKET_CANCELLED:
                why[payload.get("ticket")] = payload.get("reason")
            elif event.get("event") == TICKET_RERUN:
                why.pop(payload.get("ticket"), None)
        from wayline.objectives import is_open, named, read_objectives, served
        records = read_objectives(ledger.project)
        for fields in tickets.read_tickets(ledger.project):
            found = _SERVES.match(str(why.get(fields["id"]) or ""))
            if fields["status"] != "parked" or found is None or identifier not in re.findall(r"O[1-9][0-9]*", found.group(1)):
                continue
            if not any(is_open(named(records, name)) for name in served(fields)):
                continue  # a ticket serves on while one of its objectives is open, and only then
            path = tickets.tickets_dir(ledger.project) / tickets.filename(fields)
            current, body = tickets.read_ticket(path)
            tickets.write_ticket(ledger, dict(current, status="open"), body)
            ledger.append_event(TICKET_RERUN, {"ticket": fields["id"], "by": by}, ticket=fields["id"])
            restored.append(fields["id"])
    return restored


def _retie(project, old, new):
    """Every ticket not closed that serves `old` serves its successor `new` instead, its goal included; returns their ids."""
    from wayline import tickets
    ledger = ledger_for(project)
    moved = []
    with ledger.lock():
        for fields in tickets.read_tickets(ledger.project):
            if fields["status"] in tickets.SATISFIED or old not in (list(fields.get("objectives") or []) + [fields.get("goal")]):
                continue
            path = tickets.tickets_dir(ledger.project) / tickets.filename(fields)
            current, body = tickets.read_ticket(path)
            changed = dict(current, objectives=list(dict.fromkeys(new if name == old else name for name in current.get("objectives") or [])))
            if current.get("goal") == old:
                changed["goal"] = new
            tickets.write_ticket(ledger, changed, body)
            moved.append(fields["id"])
    return moved


def apply_change(project, change, by, proposal_id=None, placements=()):
    """Make one change to the objectives with all that follows from it; returns what it did.

    `change` is a proposal's shape (`kind`, `objective`, `successor`, `reason`) with an `answer`'s text in `answer`;
    `by` is `owner` or `decider`; `proposal_id` the approved proposal it applies, None on the owner's word through an
    objective verb. Returns `{kind, objective, successor, cancelled, reopened, passage, placed}`.

    An answered, parked, or dropped objective parks the unstarted tickets serving only closed objectives; claims tied
    only to closed objectives are set aside in `SPEC.md`; a reframe re-ties the tickets to the successor (the claims
    follow it as they are read) and code writes a Discussion passage; an answer is written as a Discussion passage; a
    reopen keeps an answer as superseded and brings back what its park parked. The concerns follow, and a dropped
    objective's concerns are placed by `placements` (`[(K id, parsed place)]`, `concerns.parse_place`'s form).
    """
    from wayline import concerns
    from wayline.objectives import add_objective, change_objective, named, read_objectives, reframe_objective

    kind, identifier = change.get("kind"), _one_line(change.get("objective"))
    reason = _one_line(change.get("reason")) or None
    report = {"kind": kind, "objective": identifier, "successor": None, "cancelled": [], "reopened": [], "passage": None, "placed": []}
    if kind == "add":
        report["objective"] = add_objective(project, identifier, by=by, proposal=proposal_id)[0]["id"]
    elif kind == "answer":
        text = " ".join(str(change.get("answer") or "").split())
        if not text:
            raise ProposalError("an answer to %s needs its text, which the verifier that upheld it or the owner writes" % identifier)
        found = change_objective(project, identifier, "answered", by, answer=text, evidence=evidence_of(text), proposal=proposal_id)
        report["passage"] = _discussion(project, found, text)
        report["cancelled"] = _park_tickets(project, identifier, "answered", by)
    elif kind in ("park", "drop"):
        change_objective(project, identifier, CLOSES[kind], by, answer=reason, proposal=proposal_id)
        report["cancelled"] = _park_tickets(project, identifier, CLOSES[kind], by)
    elif kind == "reframe":
        old, successor = reframe_objective(project, identifier, change.get("successor"), by, reason=reason, proposal=proposal_id)
        report["successor"] = successor["id"]
        _retie(project, identifier, successor["id"])
        report["passage"] = _discussion(project, old, "%s, \"%s\", was reframed as %s, \"%s\"%s" % (
            identifier, old["text"], successor["id"], successor["text"], ": %s" % reason if reason else "."))
    elif kind == "reopen":
        before = (named(read_objectives(project), identifier) or {}).get("status")
        change_objective(project, identifier, "open", by, proposal=proposal_id)
        if before == "parked":
            report["reopened"] = _restore_tickets(project, identifier, by)
    else:
        raise ProposalError("an objective change is one of %s, got %r" % (", ".join(KINDS), kind))
    try:
        concerns.follow(project)
        for concern, parsed in placements or ():
            report["placed"] += [item["id"] for item in concerns.place(project, [concern], parsed, by, only_unsorted=True)]
    except concerns.ConcernError:
        pass  # a concern that cannot be placed stays to be sorted, and ticket 96's decision asks about it
    return report


def reopened(project_or_events):
    """`[(objective, ts)]`: every answered or dropped objective reopened, for the planner to cut fresh tickets for."""
    status, found = {}, []
    for event in _events(project_or_events):
        if event.get("event") != OBJECTIVE:
            continue
        payload = event.get("payload") or {}
        identifier = payload.get("id")
        if payload.get("status") == "open" and status.get(identifier) in ("answered", "dropped"):
            found.append((identifier, event.get("ts")))
        status[identifier] = payload.get("status")
    return found


def evidence_of(text):
    """The `res:` and `ref:` locators an answer's tags name, in order and once each: the objective's evidence."""
    from wayline import provenance
    found = []
    for kind, rest in provenance.ANY_TAG_RE.findall(str(text or "")):
        locator = "%s:%s" % (kind, rest)
        if kind in ("res", "ref") and locator not in found:
            found.append(locator)
    return found


# --- who may approve what ------------------------------------------------------------------------------------------


PREREQUISITE, NEW_QUESTION = "prerequisite", "new question"


def _classes(harness):
    from wayline.project import DEFAULT_HUMAN_ONLY, human_only_classes_now
    harness = harness or {}
    return human_only_classes_now(dict(harness, human_only=harness.get("human_only") or list(DEFAULT_HUMAN_ONLY)))


def decider_refusal(record, harness, records):
    """Why the decider may not take one proposal, approving or declining it, or None: decision 17's rules.

    It answers, parks, and drops, never parking or dropping an objective the stopping rule names; it adds, reframes, or
    reopens only once the owner took `objective` off the human-only classes, its additions bounded by the radius
    (`strict` none); it reopens a parked objective at every radius, and an answered or dropped one never.
    """
    from wayline import stopping
    from wayline.project import OBJECTIVE_CLASS

    kind, identifier = record.get("kind"), _one_line(record.get("objective"))
    held = {item.get("id"): item for item in records or ()}
    if kind == "answer":
        return None
    if kind in ("park", "drop"):
        named = {item["id"] for item in stopping.waited(stopping.rule_of(harness), records or [])}
        if identifier in named:
            return "the stopping rule names %s, so %sing it is the owner's" % (identifier, "park" if kind == "park" else "dropp")
        return None
    if kind == "reopen" and (held.get(identifier) or {}).get("status") in ("answered", "dropped"):
        return "reopening %s, which is %s, is the owner's alone" % (identifier, held[identifier]["status"])
    if OBJECTIVE_CLASS in _classes(harness):
        return "`objective` is a human-only class of this project, so %s is the owner's" % (
            "adding an objective" if kind == "add" else "%s %s" % ("reopening" if kind == "reopen" else "reframing", identifier))
    if kind == "reopen":
        return None
    if (harness or {}).get("radius") not in ("moderate", "exploratory"):
        return "under the radius %s the decider adds no objective and reframes none" % ((harness or {}).get("radius") or "strict")
    return None


def _qualifier_refusal(record, radius, qualifier, taken):
    """Why the decider's approval of an `add` is outside the radius, or None: `moderate` adds a prerequisite, and
    `exploratory` also one new question within the intent per wave (`taken` counts those already approved)."""
    if record.get("kind") != "add":
        return None
    said = _one_line(qualifier).lower()
    if PREREQUISITE in said:
        return None
    if NEW_QUESTION in said and radius == "exploratory":
        return None if taken == 0 else "under exploratory the decider adds one new question per wave, and it took one already"
    if radius == "exploratory":
        return "an add the decider approves says `(prerequisite)` or, once a wave, `(new question)`"
    return "under moderate an add the decider approves is a prerequisite an open objective's work raises, and says `(prerequisite)`"


# --- reading an answer -----------------------------------------------------------------------------------------------


_ALL = re.compile(r"^\s*(approve|decline)(?:\s+(?:all|everything|them all|each|every item))?\s*[.!]?\s*(?:$|[;,:\n])", re.IGNORECASE)
_ITEM = re.compile(r"(?:\bitem\s*)?\b([1-9][0-9]*)\s*[:=.)\-–—]\s*(approve|decline)\b([^;\n]*)", re.IGNORECASE)
_LISTED = re.compile(r"\b(approve|decline)\s+(?:items?\s+)?([1-9][0-9]*(?:\s*(?:,|and|&)\s*[1-9][0-9]*)*)\b", re.IGNORECASE)
_PLACEMENT = re.compile(r"\b(K[1-9][0-9]*)\s*[:=\-–—]\s*([^;\n]+)")


def answer_marks(text, count):
    """`{item number: (mark, qualifier)}` an answer gives, `count` items in all.

    `approve all` or `decline all` at its head marks every item; `approve 1 and 3` or `decline 2, 4` marks those; and
    `<n>: approve (<why>)` marks one with its qualifier. A later form overrides an earlier one for the same item, so
    `approve all; 2: decline` approves every item but 2.
    """
    text = str(text or "")
    found = {}
    whole = _ALL.match(text)
    if whole:
        found = {number: (whole.group(1).lower(), "") for number in range(1, count + 1)}
    for match in _LISTED.finditer(text):
        for number in (int(value) for value in re.findall(r"[1-9][0-9]*", match.group(2))):
            if 1 <= number <= count:
                found[number] = (match.group(1).lower(), "")
    for match in _ITEM.finditer(text):
        number = int(match.group(1))
        if 1 <= number <= count:
            found[number] = (match.group(2).lower(), match.group(3))
    return found


def placements_in(text):
    """`[(K id, parsed place)]`: the concerns an answer or a note places, `K3: tie it to O1` each, in `concerns.parse_place`'s form."""
    from wayline import concerns
    found = []
    for match in _PLACEMENT.finditer(str(text or "")):
        parsed = concerns.parse_place(match.group(2))
        if parsed is not None and match.group(1) not in [identifier for identifier, _ in found]:
            found.append((match.group(1), parsed))
    return found


# --- the batch and its decision ticket ------------------------------------------------------------------------------


ORIGIN = "objective changes #%d"
_ORIGIN = re.compile(r"^objective changes #([1-9][0-9]*)\Z")
TITLE = "Objective changes"
OPTIONS = ("approve all", "decline all", "<n>: approve; <n>: decline")


def is_changes_ticket(origin):
    """Whether a decision ticket's origin is an "Objective changes" ticket's."""
    return _ORIGIN.match(str(origin or "")) is not None


def _answers(events):
    """`{ticket: payload}`: the answer standing on each decision ticket, a rerun taking it back."""
    from wayline.ledger import DECISION, TICKET_RERUN
    found = {}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == DECISION and isinstance(payload.get("ticket"), int):
            found[payload["ticket"]] = payload
        elif event.get("event") == TICKET_RERUN:
            found.pop(payload.get("ticket"), None)
    return found


def _applied(events):
    """The proposals an `objective` event applied."""
    return {(event.get("payload") or {}).get("proposal") for event in events if event.get("event") == OBJECTIVE} - {None}


def _batches(project):
    from wayline import batches
    return [batch for batch in batches.read_batches(project) if batch["kind"] == BATCH_KIND]


def _item_text(record, held):
    found = held.get(_one_line(record["objective"])) or {}
    words = "%s %s" % (record["kind"], _one_line(record["objective"]))
    if found.get("text"):
        words += " (\"%s\")" % found["text"]
    if record["kind"] == "reframe":
        words += " as \"%s\"" % _one_line(record.get("successor"))
    words += ": %s" % _one_line(record.get("reason"))
    if record.get("evidence"):
        words += " Evidence: %s." % ", ".join(record["evidence"])
    feasibility = record.get("feasibility")
    if isinstance(feasibility, dict):
        words += " Feasibility: %s, %s." % (feasibility.get("verdict"), _one_line(feasibility.get("reasoning")))
    if record["by"] == VERIFIER:
        words += " Proposed inside ticket %s's verdict." % record["ticket"]
    else:
        words += " From ticket %s; the verifier upheld it: %s." % (record["ticket"], _one_line(record.get("why")))
    if record.get("answer"):
        words += " Its answer, as the verifier wrote it: %s" % record["answer"]
    elif record["kind"] == "answer":
        words += " No verifier wrote its answer, so approving it has a fresh verifier write it."
    return words


def _concerns_of(project, identifier):
    """The concerns tied to `identifier`, which go back to be sorted when it drops: `[(K id, its first source's text)]`."""
    from wayline import concerns
    try:
        record = concerns.read_concerns(project)
    except (concerns.ConcernsUnreadable, ValueError, OSError):
        return []
    return [(concern["id"], _one_line((concern.get("sources") or [{}])[0].get("text")))
            for concern in record if concern["status"] == concerns.OPEN and concern.get("place") == concerns.OBJECTIVES
            and identifier in (concern.get("objectives") or [])]


def _record_of(project, batch, records, held, harness):
    """The question, the options, and the evidence of the ticket asking about `batch`'s open items."""
    lines = []
    for item in batch["items"]:
        record = records.get(item["ref"])
        if record is None:
            continue
        if item["mark"] is not None:
            lines.append("item %d, settled: %s by the %s: %s" % (item["id"], item["mark"], item["by"], item["text"]))
            continue
        # Under `autonomous` an item the decider may not take says so, and waits for the owner whatever it answers.
        why = decider_refusal(record, harness, list(held.values())) if (harness or {}).get("autonomy") == "autonomous" else None
        line = "item %d: %s" % (item["id"], item["text"])
        line += " The owner's to take: %s." % why if why else ""
        lines.append(line)
        if record["kind"] == "drop":
            for concern, said in _concerns_of(project, _one_line(record["objective"])):
                lines.append("item %d drops %s, so concern %s (\"%s\") is sorted again in this answer: `%s: tie it to O<n>`, "
                             "`%s: for the order`, or `%s: decline: <the reason>`" % (
                                 item["id"], _one_line(record["objective"]), concern, said, concern, concern, concern))
    question = ("Objective changes (batch %s): approve or decline each change to the objectives below, by its item number "
                "(`1: approve; 2: decline`), or all at once (`approve all`, `decline all`)." % batch["id"])
    return question, list(OPTIONS), lines


def _live(fields, answered):
    return fields is not None and fields["status"] == "open" and fields["id"] not in answered


def _wanted_pauses(project, batch, records, objectives_held, fields_list):
    """The tickets an open batch's unsettled `answer`, `park`, `drop`, and `reframe` items pause."""
    named = sorted({_one_line(records[item["ref"]]["objective"]) for item in batch["items"]
                    if item["mark"] is None and item["ref"] in records and records[item["ref"]]["kind"] in PAUSING})
    if not named:
        return []
    return sorted(fields["id"] for fields in _serving_only(fields_list, named, objectives_held))



def _open_ticket(project, batch_or_items, records, held, harness, notify, human_only=False, why=None):
    """Open one "Objective changes" decision ticket, reusing one a crash left with no batch; returns its id."""
    from wayline import decisions, tickets

    fields_list = tickets.read_tickets(project)
    linked = {batch["decision"] for batch in _batches(project)}
    numbers = [int(_ORIGIN.match(fields["origin"]).group(1)) for fields in fields_list if is_changes_ticket(fields.get("origin"))]
    events, _ = ledger_for(project).read_events()
    answered = _answers(events)
    orphan = [fields for fields in fields_list if is_changes_ticket(fields.get("origin")) and fields["id"] not in linked
              and _live(fields, answered) and bool(fields.get("human_only")) == bool(human_only)]
    origin = orphan[0]["origin"] if orphan else ORIGIN % (max(numbers, default=0) + 1)
    question, options, lines = _record_of(project, batch_or_items, records, held, harness)
    if why:
        lines.append(why)
    pauses = [] if human_only else _wanted_pauses(project, batch_or_items, records, list(held.values()), fields_list)
    opened = decisions.open_decision(project, question, options=options, evidence=lines, blocking=None if human_only else "subgraph",
                                     human_only=human_only, pauses=pauses, proposed_by="conductor", origin=origin, title=TITLE,
                                     notify=notify)
    return opened["ticket"]


def _items_of(records, held):
    return [{"ref": record["id"], "text": _item_text(record, held)} for record in records]


def _take_answers(project, report, say):
    """Each answered "Objective changes" ticket's answer, as marks on its batch's open items (the decider's within its rules)."""
    from wayline import batches, concerns
    from wayline.objectives import read_objectives
    from wayline.project import ProjectError, read_harness

    events, _ = ledger_for(project).read_events()
    answered = _answers(events)
    records = {record["id"]: record for record in read_proposals(events)}
    for batch in _batches(project):
        payload = answered.get(batch["decision"])
        if payload is None or batch["status"] != batches.OPEN:
            continue
        by = "decider" if payload.get("decided_by") == "decider" else "owner"
        try:
            harness = read_harness(project)
        except (ProjectError, ValueError, OSError):
            harness = {}
        held = read_objectives(project)
        marks = answer_marks(payload.get("answer"), len(batch["items"]))
        taken = 0
        for item in batch["items"]:
            if item["mark"] is not None or item["id"] not in marks or item["ref"] not in records:
                continue
            given, qualifier = marks[item["id"]]
            if by == "decider":
                why = decider_refusal(records[item["ref"]], harness, held)
                if why is None and given == APPROVE:
                    why = _qualifier_refusal(records[item["ref"]], harness.get("radius"), qualifier, taken)
                if why is not None:
                    say("  objective change %s: the decider's %s is not taken: %s" % (item["ref"], given, why))
                    continue
                if records[item["ref"]]["kind"] == "add" and given == APPROVE and NEW_QUESTION in _one_line(qualifier).lower():
                    taken += 1
            note = None
            if records[item["ref"]]["kind"] == "drop":
                given_places = [(concern, parsed) for concern, parsed in placements_in(payload.get("answer"))
                                if by == "owner" or concerns.decider_refusal("%s" % _place_words(parsed), harness) is None]
                note = "; ".join("%s: %s" % (concern, _place_words(parsed)) for concern, parsed in given_places) or None
            batches.mark(project, batch["id"], item["id"], given, note=note, by=by)
            if given == DECLINE:
                report["declined"].append(item["ref"])


def _place_words(parsed):
    """A parsed place in the words `concerns.parse_place` reads back."""
    where, value = parsed
    if where == "objectives":
        return "tie it to %s" % " and ".join(value)
    if where == "order":
        return "for the order"
    if where == "new":
        return "new objective: %s" % value
    return "decline: %s" % (value or "")


def _apply_marks(project, report, say):
    """Every approved item not applied yet, applied in item order, `by` whoever marked it; an answer with no text owed."""
    from wayline import batches
    from wayline.objectives import ObjectiveError, named, read_objectives

    events, _ = ledger_for(project).read_events()
    applied = _applied(events)
    records = {record["id"]: record for record in read_proposals(events)}
    for batch in _batches(project):
        acted = {}
        for item in batch["items"]:
            record = records.get(item["ref"])
            if item["mark"] != APPROVE or record is None or item["ref"] in applied:
                continue
            if record["kind"] == "answer" and not record.get("answer"):
                continue  # owed to the answering verifier (`owed_answers`)
            identifier = _one_line(record["objective"])
            if record["kind"] != "add":
                held = read_objectives(project)
                problem = check_proposal(record, held)
                if problem is not None:
                    status = (named(held, identifier) or {}).get("status")
                    if status != {"reopen": "open", "reframe": "reframed"}.get(record["kind"], CLOSES.get(record["kind"])):
                        say("  objective change %s was approved and cannot be made now: %s" % (item["ref"], problem))
                    else:
                        acted[item["id"]] = APPROVE  # the objective stands where the change would put it already
                    continue  # the objective already stands where the change would put it, or elsewhere by the owner's word
            placements = [(concern, parsed) for concern, parsed in placements_in(item.get("note"))
                          if concern in [found for found, _ in _concerns_of(project, identifier)]] if record["kind"] == "drop" else []
            try:
                done = apply_change(project, record, item["by"] or "owner", proposal_id=record["id"], placements=placements)
            except (ProposalError, ObjectiveError, ValueError, OSError) as failure:
                say("  objective change %s could not be made: %s" % (item["ref"], failure))
                continue
            applied.add(item["ref"])
            acted[item["id"]] = APPROVE
            report["applied"].append(item["ref"])
            say("  objective change %s approved by the %s: %s %s%s" % (
                item["ref"], item["by"], record["kind"], done["objective"],
                "; ticket(s) %s parked" % ", ".join(str(number) for number in done["cancelled"]) if done["cancelled"] else ""))
        if acted:  # made: a later click in the marks view changes nothing
            batches.acted_on(project, batch["id"], acted)


def _close_settled(project):
    """A batch every item of which is marked closes its ticket, when nobody answered it: the marks are the owner's answer."""
    from wayline import batches, tickets
    from wayline.project import ProjectError, answer

    events, _ = ledger_for(project).read_events()
    answered = _answers(events)
    by_id = {fields["id"]: fields for fields in tickets.read_tickets(project)}
    for batch in _batches(project):
        fields = by_id.get(batch["decision"])
        if batch["status"] != batches.CLOSED or not _live(fields, answered):
            continue
        said = "; ".join("%d: %s" % (item["id"], item["mark"]) for item in batch["items"])
        try:
            answer(project, fields["id"], said, rationale="every item of batch %s is marked" % batch["id"])
        except ProjectError:
            continue
        # The ticket's answer is these marks: a later click in the marks view would leave it saying another. An approval
        # not made yet ("cannot be made now") stays open to a decline.
        applied = _applied(ledger_for(project).read_events()[0])
        batches.acted_on(project, batch["id"], {item["id"]: item["mark"] for item in batch["items"]
                                                if item["mark"] == DECLINE or item["ref"] in applied})


def _gather(project, report, notify, say):
    """Upheld proposals not in a batch join the open ticket's batch, or open one; a batch whose ticket was answered with
    items open is asked about again, by the owner alone when the decider answered it."""
    from wayline import batches, tickets
    from wayline.objectives import read_objectives
    from wayline.project import ProjectError, read_harness

    events, _ = ledger_for(project).read_events()
    answered = _answers(events)
    records = {record["id"]: record for record in read_proposals(events)}
    held = {item["id"]: item for item in read_objectives(project)}
    try:
        harness = read_harness(project)
    except (ProjectError, ValueError, OSError):
        harness = {}
    by_id = {fields["id"]: fields for fields in tickets.read_tickets(project)}
    for batch in _batches(project):
        if batch["status"] != batches.OPEN or _live(by_id.get(batch["decision"]), answered):
            continue
        before = by_id.get(batch["decision"]) or {}
        earlier = answered.get(batch["decision"]) or {}
        human_only = bool(before.get("human_only")) or earlier.get("decided_by") == "decider"
        open_items = [item["id"] for item in batch["items"] if item["mark"] is None]
        why = ("the decider's answer to ticket %s left item(s) %s, which wait for the owner" if earlier.get("decided_by") == "decider"
               else "the answer to ticket %s left item(s) %s unsettled, so they are asked again") % (
            batch["decision"], ", ".join(str(number) for number in open_items))
        identifier = _open_ticket(project, batch, records, held, harness, notify, human_only=human_only, why=why)
        batches.extend(project, batch["id"], decision=identifier)
        report["opened"].append(identifier)
        say("  objective changes: ticket %d asks again about item(s) %s of %s" % (identifier, ", ".join(map(str, open_items)), batch["id"]))
    placed = {item["ref"] for batch in _batches(project) for item in batch["items"]}
    pending = [record for record in records.values() if record["upheld"] and record["id"] not in placed]
    if not pending:
        return
    by_id = {fields["id"]: fields for fields in tickets.read_tickets(project)}
    target = next((batch for batch in _batches(project) if batch["status"] == batches.OPEN
                   and _live(by_id.get(batch["decision"]), answered) and not by_id[batch["decision"]].get("human_only")), None)
    if target is not None:
        batches.extend(project, target["id"], _items_of(pending, held))
        report["joined"].extend(record["id"] for record in pending)
        say("  objective changes: %s join ticket %d" % (", ".join(record["id"] for record in pending), target["decision"]))
        return
    draft = {"id": "the next batch", "items": [dict(item, id=number, mark=None, by=None)
                                                for number, item in enumerate(_items_of(pending, held), start=1)]}
    identifier = _open_ticket(project, draft, records, held, harness, notify)
    batches.open_batch(project, BATCH_KIND, TITLE, _items_of(pending, held), decision=identifier)
    report["opened"].append(identifier)
    say("  objective changes: decision ticket %d asks about %s" % (identifier, ", ".join(record["id"] for record in pending)))


def _sync(project):
    """Each open "Objective changes" ticket lists its batch as it stands and pauses exactly what its open items pause."""
    from wayline import decisions, grill, tickets
    from wayline.objectives import read_objectives
    from wayline.project import ProjectError, read_harness

    ledger = ledger_for(project)
    with ledger.lock():
        events, _ = ledger.read_events()
        answered = _answers(events)
        records = {record["id"]: record for record in read_proposals(events)}
        held = {item["id"]: item for item in read_objectives(ledger.project)}
        try:
            harness = read_harness(ledger.project)
        except (ProjectError, ValueError, OSError):
            harness = {}
        fields_list = tickets.read_tickets(ledger.project)
        linked = {batch["decision"]: batch for batch in _batches(ledger.project)}
        for fields in fields_list:
            if not is_changes_ticket(fields.get("origin")):
                continue
            batch = linked.get(fields["id"])
            live = batch is not None and _live(fields, answered)
            # An answered ticket pauses nothing more: what a declined item paused resumes at once.
            wanted = set(_wanted_pauses(ledger.project, batch, records, list(held.values()), fields_list)) \
                if live and fields.get("blocking") == "subgraph" else set()
            for other in fields_list:
                if other["id"] == fields["id"] or other["status"] in tickets.SATISFIED:
                    continue
                has = fields["id"] in other["blocked_by"]
                if has == (other["id"] in wanted) or (not has and other["status"] not in decisions.PAUSABLE):
                    continue
                path = tickets.tickets_dir(ledger.project) / tickets.filename(other)
                current, body = tickets.read_ticket(path)
                edges = set(current["blocked_by"]) | {fields["id"]} if not has else set(current["blocked_by"]) - {fields["id"]}
                tickets.write_ticket(ledger, dict(current, blocked_by=sorted(edges)), body)
            if not live:
                continue
            path = tickets.tickets_dir(ledger.project) / tickets.filename(fields)
            current, body = tickets.read_ticket(path)
            try:
                record = decisions.decision_record(body)
            except ProjectError:
                continue
            if record is None:
                continue
            question, options, lines = _record_of(ledger.project, batch, records, held, harness)
            kept = [line for line in record.get("evidence") or [] if not line.startswith("item ")]
            rewritten = dict(record, question=question, options=options, evidence=[decisions._one_line(line) for line in lines + kept])
            if rewritten == record:
                continue
            paused = sorted(other["id"] for other in tickets.read_tickets(ledger.project) if fields["id"] in other["blocked_by"])
            tail = body.split(decisions.REFUSED_HEADING, 1)
            text = decisions.decision_body(rewritten, paused, current.get("origin"))
            if len(tail) == 2:
                text = text.rstrip("\n") + "\n\n" + decisions.REFUSED_HEADING + tail[1]
            grill.parse_records(text, source="the ticket body")
            tickets.write_ticket(ledger, current, text)


def waiting_batches(project):
    """`{objective: ticket}`: each objective an unsettled item of a waiting "Objective changes" ticket names (an add names
    none), with that ticket. At an empty frontier the batch is the ask about these objectives: the empty-frontier ticket
    folds into it rather than asking about them a second time (decision 17)."""
    from wayline import tickets
    events, _ = ledger_for(project).read_events()
    answered = _answers(events)
    records = {record["id"]: record for record in read_proposals(events)}
    by_id = {fields["id"]: fields for fields in tickets.read_tickets(project)}
    found = {}
    for batch in _batches(project):
        if not _live(by_id.get(batch["decision"]), answered):
            continue
        for item in batch["items"]:
            record = records.get(item["ref"])
            if item["mark"] is None and record is not None and record["kind"] != "add":
                found.setdefault(_one_line(record["objective"]), batch["decision"])
    return found


def settle(project, notify=None, say=None):
    """The conductor's objective-changes step of one wave; returns `{opened, joined, applied, declined}`.

    Answers become marks, marks become changes, a batch settled by marks closes its ticket, upheld proposals gather into
    the open ticket, and each open ticket lists its batch and pauses what its open items pause. Everything is read back
    from the journal and the files, so a second call, or a restarted conductor, does nothing twice.
    """
    say = say or (lambda line: None)
    report = {"opened": [], "joined": [], "applied": [], "declined": []}
    _take_answers(project, report, say)
    _apply_marks(project, report, say)
    _close_settled(project)
    _gather(project, report, notify, say)
    _sync(project)
    return report


# --- answering an objective as it stands ------------------------------------------------------------------------------


ANSWERING_TIER = ("opus", "high")       # decision 17: one fresh verifier session per objective, on opus high
ANSWER_SCHEMA = "objective_answer"
ANSWER_PATHS = ("research/OBJECTIVES.md", "research/findings.jsonl", "research/sections/results.md",
                "research/sections/discussion.md", "research/REPORT.md", "research/manifest.json")
RESUME_ANSWER = ("The answer you returned could not be used: %s.\n\nReturn it again through the structured output, as the "
                 "objective_answer schema asks, with every claim sentence ending with a tag that resolves and every number at "
                 "one of its res: locators. Do not start new work.")


def answer_prompt(role, objective, why, project):
    """The answering verifier's prompt: the objective, why it is answered as it stands, the paths, and the schema."""
    from wayline import worker
    lines = ["# The objective you answer", "",
             "- objective: %s, \"%s\"" % (objective["id"], objective["text"]),
             "- why it is answered now: %s" % why, "",
             "The owner or the decider chose to answer this objective as it stands, from what the run found; nobody asks "
             "for more work. You did not do the work. Read the paths below and write the answer the evidence supports, "
             "including \"the work does not settle it\" when that is what it shows. Every claim sentence ends with its "
             "{res:<run-id>/<artifact>#<locator>} or {ref:<slug>#<locator>} tag, and every number in it is a value at one of "
             "its res: locators: code checks both before the answer is written into OBJECTIVES.md and the Discussion.", "",
             "# The paths", "", "The project is `%s`; open these with the Read tool:" % project, ""]
    lines += ["- `%s`" % path for path in ANSWER_PATHS]
    parts = ["\n".join(lines), worker.schema_section("# The answer", ANSWER_SCHEMA)]
    return "\n\n".join(part.strip("\n") for part in parts) + "\n"


def _unusable_answer(envelope, identifier, project):
    from wayline.jsonschema import ValidationError, check, load_schema
    if not envelope.valid:
        return "; ".join(envelope.errors) or "the session returned no structured answer"
    try:
        check(envelope.structured_output, load_schema(ANSWER_SCHEMA), name="objective_answer")
    except ValidationError as failure:
        return str(failure)
    returned = envelope.structured_output
    if returned["objective"] != identifier:
        return "it answers %s, and the objective asked was %s" % (returned["objective"], identifier)
    return answer_problem(project, returned["answer"])


def answer_as_it_stands(project, identifier, by, why, proposal_id=None, *, harness_root=None, policy=None):
    """One fresh verifier session on `opus high` writes the answer to `identifier`; code checks it and writes it.

    The answer passes the numbers and locator checks (`answer_problem`), or the session is resumed once with the
    reason; a second unusable answer raises `ProposalError` and nothing is written. Written, the objective is answered
    `by` whoever chose it, with its evidence, and code writes the answer as a Discussion passage. A usage window that
    refused the session raises `gates.UsageLimited`, to be launched again, fresh, later. Returns `apply_change`'s report.
    """
    from pathlib import Path

    from wayline import HARNESS_ROOT, gates, worker
    from wayline.objectives import named, read_objectives
    from wayline.project import policy_for

    harness_root = harness_root or HARNESS_ROOT
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    objective = named(read_objectives(project), identifier)
    if objective is None or objective.get("status") != "open":
        raise ProposalError("%s is not an open objective, so it is not answered as it stands" % identifier)
    model, effort = ANSWERING_TIER
    role = worker.read_role(gates.VERIFIER, harness_root, project)
    run_dir = gates.verdict_dir(project, "ticket", "objective-%s" % identifier)
    budget = ((policy.get("budget") or {}).get(gates.VERDICT_BUDGET) or {})
    request = worker.LaunchRequest(
        role=role.name, model=model, effort=effort, prompt=answer_prompt(role, objective, why, project),
        agent_json=role.agent_json(model, effort, budget.get("max_turns")),
        allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
        settings_path=gates.write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[str(Path(harness_root).resolve()), str(project)], cwd=project, env=gates.verdict_env(project, run_dir),
        schema_path=Path(harness_root).resolve() / "schemas" / (ANSWER_SCHEMA + ".json"), max_minutes=budget.get("max_minutes"),
    )
    what = "the answering verifier on %s" % identifier
    envelope = worker.launch(request)
    gates.raise_if_refused(envelope, model, what)
    problem = _unusable_answer(envelope, identifier, project)
    if problem is not None and envelope.session_id:
        envelope = worker.resume(request, envelope.session_id, RESUME_ANSWER % problem)
        gates.raise_if_refused(envelope, model, what)
        problem = _unusable_answer(envelope, identifier, project)
    if problem is not None:
        raise ProposalError("%s returned no answer code could take: %s" % (what, problem))
    return apply_change(project, {"kind": "answer", "objective": identifier, "answer": envelope.structured_output["answer"]}, by,
                        proposal_id=proposal_id)


def owed_answers(project):
    """`[(objective, by, why, proposal)]`: the objectives a fresh verifier answers as they stand, each still open.

    One the owner or the decider chose to answer as it stands at an empty frontier (ticket 87), and one whose `answer`
    proposal was approved with no verifier's text; `by` is who chose it.
    """
    from wayline import stopping, tickets
    from wayline.objectives import read_objectives

    events, _ = ledger_for(project).read_events()
    held = {item["id"]: item for item in read_objectives(project)}
    last_change = {}
    for event in events:
        if event.get("event") == OBJECTIVE:
            last_change[(event.get("payload") or {}).get("id")] = event.get("ts") or ""
    owed = []
    answered = _answers(events)
    stamps = {}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == "decision" and isinstance(payload.get("ticket"), int):
            stamps[payload["ticket"]] = event.get("ts") or ""
    for fields in tickets.read_tickets(project):
        identifier = stopping.frontier_objective(fields.get("origin"))
        given = answered.get(fields["id"])
        if identifier is None or given is None or stopping.frontier_choice(given.get("answer")) != stopping.ANSWER:
            continue
        if (held.get(identifier) or {}).get("status") == "open" and last_change.get(identifier, "") < stamps.get(fields["id"], ""):
            owed.append((identifier, "decider" if given.get("decided_by") == "decider" else "owner",
                         "ticket %d chose to answer it as it stands" % fields["id"], None))
    records = {record["id"]: record for record in read_proposals(events)}
    applied = _applied(events)
    for batch in _batches(project):
        for item in batch["items"]:
            record = records.get(item["ref"])
            if item["mark"] != APPROVE or record is None or record["kind"] != "answer" or record.get("answer") or item["ref"] in applied:
                continue
            identifier = _one_line(record["objective"])
            if (held.get(identifier) or {}).get("status") == "open" and identifier not in [found for found, _, _, _ in owed]:
                owed.append((identifier, item["by"] or "owner", "the answer %s was approved with no verifier's text" % item["ref"],
                             item["ref"]))
    return owed
