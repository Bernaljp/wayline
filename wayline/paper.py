"""The paper order and the paper's parts (Implementation Decision 17; ticket 115).

The paper is made only on an explicit **paper order**, and only from the outline and the sections: until one, the
project holds only its sections and its reports, and the general report is always current.

**The card.** `wayline paper` alone builds the order's card with no model call (`card`): the readiness list (the open
objectives, the outline's gaps, the general report's last kill argument and its standing points, the results changed
since their last drawing, the inherited claims unchecked or unverifiable, the open contradictions, the unresolved
references, the concerns for the order, the outline's link, and the front matter not given yet) and the cost. The
conversation shows it and confirms first; the dashboard shows the same card (`/api/projects/<id>/paper/card`) and its Confirm
runs the same order (the `paper` action). Nothing on the card blocks the order, and "Not now" does nothing: no decision
ticket opens.

**The order** (`order`, `wayline paper --yes`): journaled as `paper_order` with `action: ordered`. Under `interactive`
and `checkpoints` one batch (`batch_items`, kind `paper_order` of ticket 79's record) is opened before any writer
launches: the open contradictions (code's suggested side, or "a typo, fix it"), the unverifiable claims the owner might
keep, the unresolved references (hand over, drop, or keep the claim marked "to be resolved"), the outline's open
proposals, and the figure plan's items (`paper_figures.batch_items`, ticket 116), each with code's default, "take all
defaults" one answer; an order with no inherited result verified asks whether to keep the unchecked ones as stated (the
default) or leave them out. Under `autonomous` no batch is asked here:
code's defaults stand until the decider answers it (ticket 120). With no conductor on the project the order starts one,
whose run ends as the last one did once the paper is composed (`run` on the event).

**The rest point.** The conductor takes the order (`Conductor._take_order`): running tickets finish, nothing new
launches, the changed results are drawn (`drawings.ORDER`), and once the batch is settled `compose` writes the paper
from that commit; then the run resumes if it had not ended. The order starts no research ticket.

**The composition** (`compose`): one read-only writer session (`policy.roles.writer`, `opus xhigh`) on the
`paper_parts` schema returns each part as its own field, each heading carrying its outline id (`## ... {#R3}`). Code
checks it before writing anything (`check_structure`, the outline's order and placement; `kept_problems`, no inherited
title, abstract, or caption; no reference list; three titles), resuming the session once with what failed, and writes
`research/paper/`: `title.md`, `abstract.md`, `introduction.md`, `results.md`, `discussion.md`, `methods.md`,
`supplement.md`, `front.md`, `tables/T<n>.csv` with `T<n>.md`, `references.json`, `alternatives/<part>-<n>.md`,
`paper.json` (schema `paper`), and the build report `PAPER.md`. A change the writer wants is a proposal there, never a
move. `front.md` is code's: the data and code availability statements from the records, and the authors, affiliations,
acknowledgments, funding, and competing interests as the owner gave them (`wayline paper front`, the setup question at
every autonomy), or a marked placeholder until said.

**Versions.** Each order makes a new version, the previous one frozen under `research/paper/earlier/v<n>/`. A re-order
recomposes only the parts whose inputs changed (`part_inputs`; the title and abstract whenever a main-text part did) and
keeps an owner's edit of a part file unless its inputs changed; the writer always reads the whole version. The writer
offers three titles; other alternatives only when asked. The build is recorded as not yet gated: the builds' gates are
ticket 117's, the figures 116's, the compilations 118's. Nothing here submits anything anywhere.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, batches, provenance, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import PAPER_ORDER, LedgerError, conductor_holder, ledger_for, now_ts
from wayline.project import ProjectError, find_project, policy_for, read_harness

__all__ = [
    "PaperError", "PAPER_DIR", "PARTS", "MAIN_TEXT", "SCHEMA", "RECORD_SCHEMA", "FRONT_SCHEMA", "PAPER_MD", "PAPER_JSON",
    "FRONT_JSON", "EARLIER", "COST", "PLACEHOLDER", "BATCH_KIND", "readiness", "card", "card_text", "batch_items", "open_order",
    "order", "waiting_on", "answers", "compose", "fail", "check_structure", "inherited_kept", "kept_problems", "part_inputs",
    "front_text", "read_front", "set_front", "read_record", "paper_command",
]

PAPER_DIR = "paper"                       # research/paper/
PARTS = ("title", "abstract", "introduction", "results", "discussion", "methods", "supplement", "front")
MAIN_TEXT = ("introduction", "results", "discussion", "methods")
WRITTEN = PARTS[:-1]                      # the writer's; the front matter is code's
SCHEMA = "paper_parts"
RECORD_SCHEMA = "paper"
FRONT_SCHEMA = "front_matter"
PAPER_MD = "PAPER.md"
PAPER_JSON = "paper.json"
FRONT_JSON = "front.json"                 # research/front.json, the owner's front matter
EARLIER = "earlier"                       # research/paper/earlier/v<n>/
TABLES = "tables"
ALTERNATIVES = "alternatives"
REFERENCES_JSON = "references.json"
ROLE = "writer"
SESSIONS = "paper"                        # research/sessions/paper/<n>
WRITER_BUDGET = "large"
BATCH_KIND = "paper_order"
OWNER, DECIDER, CODE = "owner", "decider", "code"
AUTONOMOUS = "autonomous"
ORDERED, COMPOSED, FAILED = "ordered", "composed", "failed"

COST = ("about $35 to $40 for six figures when the first build passes, and about $10 more for each build that fails "
        "(the writer, the figures, and the gates, at API prices)")
PLACEHOLDER = "[TO BE GIVEN: %s]"
FRONT_FIELDS = (("authors", "the authors and their affiliations"), ("acknowledgments", "the acknowledgments"),
                ("funding", "the funding"), ("competing_interests", "the competing interests"))

# The marks of each sort of item in the order's batch, with code's default where it is one mark for every item.
FIRST, SECOND, TYPO = "the first", "the second", "a typo, fix it"
LEAVE_OUT, KEEP_UNVERIFIED = "leave out", "keep, not verified"
HAND_OVER, DROP, TO_BE_RESOLVED = "hand over", "drop", "to be resolved"
TAKE, DECLINE = "take", "decline"
KEEP_AS_STATED = "keep as stated"
UNCHECKED_REF = "inherited:unchecked"

REFERENCE_HEADINGS = ("references", "reference list", "bibliography", "literature cited", "works cited", "cited literature")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_ATTRIBUTE = re.compile(r"\{#([^\s{}]+)[^{}]*\}\s*$")
_WORDS = re.compile(r"[a-z0-9]+")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_STAMP = re.compile(r"^<!-- wayline:render \{.*\} -->\n?")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

PROMPT = """\
# Paper order %(order)d: version %(version)d of the paper

You compose the paper from the outline and the sections, as one writer session that reads and writes nothing else.
Return each part you are asked for as its own field through the structured output, and null for every other part:
those stand as they are under research/paper/, and you read them as the rest of this version.

The parts to write now: %(parts)s.

## Rules

- Write from the sections' current passages and the outline below, in prose, as a paper. Markdown with LaTeX math.
- Every heading of a part carries its outline id as a pandoc attribute, `## <heading> {#<id>}`, and the headings follow
  the outline's order and placement below exactly: no heading the outline does not have, none in another part. A change
  you want (a heading moved, merged, added, or cut) goes in `proposals`; never make it.
- Every claim sentence keeps the provenance tags of the passages it comes from, `{res:...}`, `{ref:...}`, `{code:...}`,
  copied exactly, at its end. Write no reference list and no References heading: code writes `references.json` from
  the `ref` tags.
- An inherited claim still unchecked is built on, never copied word for word. The title, the abstract, and the
  captions of the project's own earlier documents never reach the paper; write your own.
- When the title is asked for, offer three titles in `titles`, your choice first. Offer no other alternative unless
  this order asks for one.
- The front matter (authors, affiliations, acknowledgments, funding, competing interests, the availability
  statements) is code's: write none of it.
- The figures and the plan's tables are code's, listed under "The figures and tables" below: refer to each by the
  name given there where the text discusses its result, and write no caption and place no file. A further table the
  Results needs is one of `tables`, given as CSV, numbered after the plan's: from T%(table)d, Table %(table)d in the text.
- List in `left_out` what you leave out of the paper and why, and in `notes` anything the owner should read.

## The outline, part by part
%(outline)s
## The figures and tables
%(figures)s
## The answers this paper follows
%(answers)s
## What to read
%(read)s
"""


class PaperError(ValueError):
    """A paper order refused or a paper that could not be composed: an order already open, a writer with no usable answer."""


# --- small readings -------------------------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text or "").split())


def _words(text):
    return _WORDS.findall(provenance.strip_tags(str(text or "")).casefold())


def _digest(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _sha(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _paper(relpath=""):
    return "%s/%s" % (PAPER_DIR, relpath) if relpath else PAPER_DIR


def _events(book):
    return book.read_events()[0]


def _orders(events):
    return [event.get("payload") or {} for event in events if event.get("event") == PAPER_ORDER]


def open_order(project_or_ledger, events=None):
    """The `paper_order` payload of the order that is open, or None: ordered, and neither composed nor failed since."""
    events = _events(ledger_for(project_or_ledger)) if events is None else events
    found = None
    for payload in _orders(events):
        if payload.get("action") == ORDERED:
            found = payload
        elif found is not None and payload.get("order") == found.get("order"):
            found = None
    return found


def _section_body(book, section):
    """A section file as rendered, its render stamp taken off; empty when it is not there."""
    from wayline import sections
    try:
        text = (book.research / sections.section_path(section)).read_text(encoding="utf-8")
    except OSError:
        return ""
    return _STAMP.sub("", text, count=1)


def _current_passages(book):
    """Every current passage of the four written sections, each once."""
    from wayline import sections
    found = []
    for section in MAIN_TEXT:
        try:
            found += sections.arranged(book, section).current()
        except (OSError, ValueError, LedgerError):
            continue
    return found


def _guard(read, *args):
    """`(value, None)`, or `(None, why)` when a record could not be read: the card says so and lists the rest."""
    try:
        return read(*args), None
    except (OSError, ValueError, LedgerError) as failure:
        return None, "could not be read: %s" % _one_line(failure)


# --- what the card and the batch read -------------------------------------------------------------------------------


def _inherited(book):
    """The current inherited passages standing unchecked or unverifiable, in each section's order."""
    from wayline import sections
    return [item for item in _current_passages(book)
            if sections.is_inherited(item) and item.get("standing") in sections.STANDINGS and not item.get("withdrawn")]


def _contradictions(project):
    """The contradictions standing now that the owner did not mark not one: `[{a, b, why, results}]`."""
    from wayline import repeats
    dismissed = repeats.dismissed_pairs(project)
    return [item for item in repeats.contradictions(project) if (item["a"], item["b"]) not in dismissed]


def _unresolved(project):
    from wayline import references
    return references.references_view(project)["unresolved"]


def _order_concerns(project):
    from wayline import concerns
    return [item for item in concerns.read_concerns(project) if item.get("place") == "order" and item.get("status") == "open"]


def _kill(events):
    """The last kill argument on the general report as `(passed, subject, points)`, or None before the first."""
    from wayline import run_end
    payload = run_end.last_kill_verdict(events)
    if payload is None:
        return None
    points = [_one_line(item.get("text") if isinstance(item, dict) else item) for item in payload.get("findings") or []]
    return bool(payload.get("pass")), payload.get("subject"), [point for point in points if point]


def _verified_none(project):
    """Whether the project inherited results and none of them is verified yet: the batch then asks about the unchecked."""
    from wayline import verification
    if not verification.midway(project):
        return False
    return not any(item.get("standing") == "verified" for item in verification.read_results(project))


def read_front(project_or_ledger):
    """The front matter as the owner gave it (`research/front.json`); empty while nothing was given."""
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(FRONT_JSON)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as failure:
        raise PaperError("research/%s cannot be read: %s" % (FRONT_JSON, failure)) from None
    try:
        check(record, load_schema(FRONT_SCHEMA), name="research/%s" % FRONT_JSON)
    except ValidationError as failure:
        raise PaperError(str(failure)) from None
    return record


def _front_missing(record):
    return [words for key, words in FRONT_FIELDS if not record.get(key)]


def readiness(project):
    """The card's readiness list, built by code with no model call: `[{key, title, lines}]`, an empty `lines` meaning
    nothing stands there. Nothing on it blocks the order."""
    from wayline import drawings, objectives, outline
    book = ledger_for(project)
    events = _events(book)
    items = []

    def add(key, title, read, render, empty):
        value, trouble = _guard(read)
        lines = [trouble] if trouble else (render(value) or [])
        items.append({"key": key, "title": title, "lines": lines, "empty": empty})

    add("objectives", "Open objectives", lambda: objectives.open_objectives(book.project),
        lambda found: ["%s: %s" % (item["id"], _one_line(item["text"])) for item in found], "none open")
    add("gaps", "The outline's gaps", lambda: outline.gaps(book)[0],
        lambda found: [line[2:] if line.startswith("- ") else line for line in found], "none in the main text")

    def kill_lines(found):
        if found is None:
            return ["no kill argument has run on the general report yet"]
        passed, subject, points = found
        head = "the last one, on %s, %s" % (subject or "the general report", "passed" if passed else "failed")
        return [head] + ["standing: %s" % point for point in ([] if passed else points)]
    add("kill", "The general report's last kill argument", lambda: _kill(events), kill_lines, "")

    def changed():
        from wayline import results as results_module
        found = {result.id: result for result in results_module.read_results(book)}
        return [(identifier, found.get(identifier)) for identifier in drawings.due(book.project)]
    add("changed", "Results changed since their last drawing", changed,
        lambda found: ['%s "%s": drawn first at the order' % (identifier, result.heading if result else identifier)
                       for identifier, result in found], "none")
    add("inherited", "Inherited claims unchecked or unverifiable", lambda: _inherited(book),
        lambda found: ["%s (%s, %s): %s" % (item["id"], item.get("section"), item.get("standing"),
                                            _one_line(provenance.strip_tags(item.get("text")))[:160]) for item in found], "none")
    add("contradictions", "Open contradictions", lambda: _contradictions(book.project),
        lambda found: ["%s and %s: %s" % (item["a"], item["b"], _one_line(item.get("why")) or "they contradict each other")
                       for item in found], "none")
    add("references", "Unresolved references", lambda: _unresolved(book.project),
        lambda found: ["%s: %s (%s)" % (work.slug or work.named, state, detail) for work, state, detail in found], "none")
    add("concerns", "Concerns for the order", lambda: _order_concerns(book.project),
        lambda found: ["%s: %s" % (item["id"], _one_line(item["sources"][0]["text"])[:160]) for item in found], "none")
    add("front", "Front matter not given yet", lambda: _front_missing(read_front(book)),
        lambda found: ["%s: a marked placeholder until said (wayline paper front)" % words for words in found], "all given")
    items.append({"key": "outline", "title": "The outline", "lines": ["research/%s" % outline.OUTLINE_MD], "empty": ""})
    return items


def card(project):
    """What the owner confirms, with no model call: the readiness list, the cost, the order open if one is, and the verb."""
    book = ledger_for(project)
    from wayline import outline
    structure, _ = _guard(outline.paper_structure, book)
    results = len([entry for entry in (structure or {}).get("results", []) if re.match(r"^R[1-9][0-9]*$", entry["key"])])
    return {"readiness": readiness(book.project), "cost": COST, "main_results": results, "open": open_order(book),
            "confirm": "wayline paper --yes", "blocks": False}


def card_text(found):
    """The card as the conversation shows it."""
    lines = ["The paper order: nothing below blocks it; it composes the paper from the outline and the sections.", ""]
    for number, item in enumerate(found["readiness"], start=1):
        lines.append("%d. %s: %s" % (number, item["title"], item["lines"][0] if len(item["lines"]) == 1 else
                                     ("%d" % len(item["lines"]) if item["lines"] else item["empty"])))
        if len(item["lines"]) > 1:
            lines += ["   - %s" % line for line in item["lines"]]
    lines += ["", "Cost: %s; this outline has %d main-text result(s), one figure each." % (found["cost"], found["main_results"])]
    if found["open"]:
        lines.append("Paper order %d is open; a new one waits until it is composed." % found["open"]["order"])
    else:
        lines.append("Confirm: %s. Not now: nothing is done." % found["confirm"])
    return "\n".join(lines)


# --- the batch ------------------------------------------------------------------------------------------------------


def _differ_in_numbers(first, second):
    """Whether two claims say the same words and differ only in a number: code suggests a typo."""
    return (_NUMBER.sub("#", " ".join(_words(first))) == _NUMBER.sub("#", " ".join(_words(second)))
            and " ".join(_words(first)) != " ".join(_words(second)))


def _supported(book, identifier):
    from wayline import sections
    return any(item.get("replaces") == identifier and item.get("evidence") == "supports"
               for item in list(sections.read_findings(book)) + list(sections.read_passages(book)))


def batch_items(project):
    """The order's batch, `[{ref, text, marks, default}]`: open contradictions, unverifiable claims, unresolved references,
    the outline's open proposals, and, with no inherited result verified, the unchecked ones as stated or left out."""
    from wayline import sections
    book = ledger_for(project)
    passages = {item.get("id"): item for item in sections.read_passages(book)}
    items = []
    for found in _contradictions(book.project):
        first, second = (passages.get(found["a"]) or {}).get("text"), (passages.get(found["b"]) or {}).get("text")
        if _differ_in_numbers(first, second):
            default = TYPO
        elif _supported(book, found["a"]) and not _supported(book, found["b"]):
            default = FIRST
        else:
            default = SECOND  # the later writing, unless the evidence holds to the first
        items.append({"ref": "contradiction:%s+%s" % (found["a"], found["b"]), "marks": [FIRST, SECOND, TYPO], "default": default,
                      "text": 'Contradiction: %s ("%s") against %s ("%s")%s. Which does the paper hold to?' % (
                          found["a"], _one_line(provenance.strip_tags(first))[:200], found["b"],
                          _one_line(provenance.strip_tags(second))[:200], ": %s" % _one_line(found["why"]) if found.get("why") else "")})
    for item in _inherited(book):
        if item.get("standing") == sections.UNVERIFIABLE:
            items.append({"ref": "unverifiable:%s" % item["id"], "marks": [LEAVE_OUT, KEEP_UNVERIFIED], "default": LEAVE_OUT,
                          "text": 'Unverifiable %s (%s): "%s"; %s. Kept, it is stated as not verified, with why.' % (
                              item["id"], item.get("section"), _one_line(provenance.strip_tags(item.get("text")))[:200],
                              _one_line(item.get("reason")) or "no reason recorded")})
    for work, state, detail in _unresolved(book.project):
        name = work.slug or work.named
        items.append({"ref": "reference:%s" % name, "marks": [HAND_OVER, DROP, TO_BE_RESOLVED], "default": TO_BE_RESOLVED,
                      "text": "Unresolved reference %s: %s (%s). Hand it over (wayline reference), drop it, or keep the claim "
                              'marked "to be resolved".' % (name, state, detail)})
    for batch in batches.read_batches(book.project, status="open"):
        if batch["kind"] != "outline_proposals":
            continue
        for item in batch["items"]:
            if item["mark"] is None:
                items.append({"ref": "outline:%s#%d" % (batch["id"], item["id"]), "marks": [TAKE, DECLINE],
                              "default": item.get("default") or DECLINE, "text": "The outline proposes: %s" % _one_line(item["text"])})
    from wayline import paper_figures
    items += paper_figures.batch_items(book.project, autonomous=read_harness(book.project).get("autonomy") == AUTONOMOUS)
    if _verified_none(book.project):
        items.append({"ref": UNCHECKED_REF, "marks": [KEEP_AS_STATED, LEAVE_OUT], "default": KEEP_AS_STATED,
                      "text": "None of the inherited results is verified yet. Keep the unchecked ones as stated, or leave them out?"})
    return items


def waiting_on(project, payload):
    """The order's batch while it has an open item, else None: the writer waits for the owner's marks."""
    identifier = (payload or {}).get("batch")
    if not identifier:
        return None
    try:
        batch = batches.read_batch(project, identifier)
    except (batches.BatchError, ValidationError, OSError, ValueError):
        return None
    return identifier if batch["status"] == "open" else None


def answers(project, payload):
    """The answers the composition follows: `[{ref, text, mark, by, batch, item, note}]`, the batch's marks when one was
    asked, and otherwise code's defaults on the items as they stand now (`by: code`)."""
    identifier = (payload or {}).get("batch")
    if identifier:
        batch = batches.read_batch(project, identifier)
        return [{"ref": item["ref"], "text": item["text"], "mark": item["mark"] or item["default"], "by": item["by"] or CODE,
                 "batch": batch["id"], "item": item["id"], "note": item["note"]}
                for item in batch["items"] if (item["mark"] or item["default"])]
    return [{"ref": item["ref"], "text": item["text"], "mark": item["default"], "by": CODE, "batch": None, "item": None, "note": None}
            for item in batch_items(project)]


def _take_outline_answers(project, found):
    """Give each outline proposal the order's answer on its own batch, then let the outline take the marks.

    Only an answer someone gave (the owner's, or the decider's) is given there: code's default under `autonomous` leaves
    the proposal open for the decider (ticket 120). A proposal marked in its own batch since keeps that mark, and the
    answer the paper follows becomes it, so the record says what the outline holds.
    """
    from wayline import outline
    taken = False
    for answer in found:
        match = re.match(r"^outline:(B[1-9][0-9]*)#([1-9][0-9]*)$", answer["ref"])
        if not match or answer["by"] not in (OWNER, DECIDER):
            continue
        try:
            batches.mark(project, match.group(1), int(match.group(2)), answer["mark"], by=answer["by"])
            taken = True
        except batches.BatchError:
            try:
                item = next(entry for entry in batches.read_batch(project, match.group(1))["items"]
                            if entry["id"] == int(match.group(2)))
            except (batches.BatchError, StopIteration, OSError, ValueError):
                continue
            if item["mark"] is not None:
                answer.update(mark=item["mark"], by=item["by"] or answer["by"],
                              note="marked %s in %s first" % (item["mark"], match.group(1)))
    if taken:
        outline.take_marks(project)


# --- the order ------------------------------------------------------------------------------------------------------


def _start_conductor(project):
    from wayline import tick
    return tick.launch_detached(project)


_STARTS = object()  # `order`'s default: start the conductor as the transient unit, as `wayline run --detach` does


def order(project, by=OWNER, start=_STARTS):
    """The paper order: journal it, ask its batch under `interactive` and `checkpoints`, and start a conductor when none
    runs, which takes the order at its next wave. Returns `{order, batch, run, conductor, started}`.

    Refused while an order is open. `run` is how the last run ended when no run was going (a project never run counts as
    stopped), so the order's own run ends the same way; None while a run was going, which resumes after the paper.
    """
    from wayline import replay
    project = Path(project).resolve()
    book = ledger_for(project)
    with book.lock():
        events = _events(book)
        opened = open_order(book, events)
        if opened is not None:
            raise PaperError("paper order %d is open%s; a new order waits until its paper is composed" % (
                opened["order"], " and waits on batch %s" % opened["batch"] if waiting_on(project, opened) else ""))
        number = 1 + len([payload for payload in _orders(events) if payload.get("action") == ORDERED])
        holder = conductor_holder(project)
        view = replay.replay(events)
        run = None if holder is not None else ("stopped" if view.run is None else view.run.get("ended"))
        batch = None
        if read_harness(project).get("autonomy") != AUTONOMOUS:
            items = batch_items(project)
            if items:
                batch = batches.open_batch(project, BATCH_KIND, "Paper order %d: before the writer" % number, items)["id"]
        book.append_event(PAPER_ORDER, {"order": number, "action": ORDERED, "by": by, "run": run, "batch": batch})
    started = None
    if holder is None and start is not None:
        try:
            started = (_start_conductor if start is _STARTS else start)(project) or ""
        except (OSError, ValueError, RuntimeError) as failure:  # a unit the manager refused: the tick relaunches it
            started = "not started (%s); the tick starts one, or wayline run --detach" % _one_line(failure)
    return {"order": number, "batch": batch, "run": run, "conductor": holder is not None, "started": started}


def fail(project, payload, reason):
    """Close the open order `payload` as failed, with why; its run ends as the composition would have ended it."""
    ledger_for(project).append_event(PAPER_ORDER, {"order": payload["order"], "action": FAILED, "by": payload.get("by") or OWNER,
                                                   "reason": _one_line(reason)})


# --- the checks -----------------------------------------------------------------------------------------------------


def _headings(text):
    """`[(line, heading text, id or None)]` of a part's Markdown headings, outside fenced code."""
    found, fenced = [], False
    for number, line in enumerate(str(text or "").splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.match(line)
        if match:
            attribute = _ATTRIBUTE.search(match.group(2))
            words = _ATTRIBUTE.sub("", match.group(2)).strip()
            found.append((number, words, attribute.group(1) if attribute else None))
    return found


def check_structure(structure, parts):
    """The Type-A check of a paper's headings against the outline: problems, one line each, empty when it passes.

    `structure` is `outline.paper_structure`'s; `parts` maps a part to its text (None for a part not checked). Every
    heading carries an outline id; the ids of a part are the outline's for that part, all of them, in its order; an id
    the outline places in another part, or does not have, fails; and a reference list is code's, never a part's.
    """
    placed = {entry["id"]: part for part, entries in structure.items() for entry in entries}
    problems = []
    for part, text in parts.items():
        if text is None or part not in structure:
            continue
        expected = [entry["id"] for entry in structure[part]]
        got = []
        for line, words, identifier in _headings(text):
            if words.casefold().strip(" .:") in REFERENCE_HEADINGS:
                problems.append("%s, line %d: a reference list (%s) is code's, from the tags; write none" % (part, line, words))
            elif identifier is None:
                problems.append('%s, line %d: the heading "%s" carries no outline id; write it as `## %s {#<id>}`' % (part, line, words, words))
            elif identifier not in placed:
                problems.append('%s, line %d: {#%s} ("%s") is no line of the outline; a heading you want is a proposal' % (part, line, identifier, words))
            elif placed[identifier] != part:
                problems.append("%s, line %d: {#%s} is placed in %s by the outline, not here" % (part, line, identifier, placed[identifier]))
            else:
                got.append(identifier)
        missing = [identifier for identifier in expected if identifier not in got]
        if missing:
            problems.append("%s: the outline's %s %s missing" % (part, ", ".join("{#%s}" % item for item in missing),
                                                                  "is" if len(missing) == 1 else "are"))
        shown = [identifier for identifier in got if identifier in expected]
        if not missing and shown != expected:
            problems.append("%s: the headings run %s, and the outline's order is %s" % (
                part, ", ".join(shown), ", ".join(expected)))
    return problems


def inherited_kept(project):
    """What a project's own earlier documents keep and the paper never carries: `[(what, text)]`, each inherited
    document's title, its abstract, and its captions."""
    from wayline import documents
    book = ledger_for(project)
    try:
        held = documents.read_documents(book.project)
    except (OSError, ValueError):
        return []
    found = []
    for document in held:
        if document.get("kind") != "inherited":
            continue
        name = document.get("id")
        if document.get("title"):
            found.append(("the title of %s" % name, document["title"]))
        if document.get("abstract"):
            found.append(("the abstract of %s" % name, document["abstract"]))
        kept = [item["locator"] for item in (document.get("deconstructed") or {}).get("kept") or [] if item.get("part") == "caption"]
        if kept:
            try:
                text = book.path("%s/%s/text.md" % (documents.DOCUMENTS_DIR, name)).read_text(encoding="utf-8")
            except OSError:
                text = ""
            blocks = dict(documents.text_blocks(text)) if text else {}
            found += [("a caption of %s (%s)" % (name, locator), blocks[locator]) for locator in kept if blocks.get(locator)]
    return found


def kept_problems(parts, kept):
    """Problems, one line each, for any inherited title, abstract sentence, or caption sentence found in a part."""
    problems = []
    for part, text in parts.items():
        if text is None:
            continue
        said = " %s " % " ".join(_words(text))
        for what, source in kept:
            pieces = [source] if what.startswith("the title") else _SENTENCES.split(str(source))
            for piece in pieces:
                words = _words(piece)
                if len(words) >= (3 if what.startswith("the title") else 8) and " %s " % " ".join(words) in said:
                    problems.append('%s carries %s ("%s"): write your own, never the inherited one' % (part, what, _one_line(piece)[:120]))
                    break
    return problems


# --- the inputs of each part ----------------------------------------------------------------------------------------


def _read_or(book, relpath):
    try:
        return book.read_json(relpath)
    except (OSError, ValueError):
        return None


def _front_inputs(book):
    from wayline import code_repository, methods_inventory
    try:
        record = read_front(book)
    except PaperError:
        record = {}
    try:
        available = methods_inventory.availability(book)
    except (OSError, ValueError):
        available = []
    return record, code_repository.record(book.project), _intake_data(book), available, _manifest_count(book)


def part_inputs(project, structure, followed, plan=None):
    """`{part: digest}` of what each part is made from now: its section as rendered, its lines of the outline, the
    records it reads, and the answers it follows; the title and abstract from the main text's, the front matter from
    the records code writes it from."""
    book = ledger_for(project)
    bodies = {section: _section_body(book, section) for section in MAIN_TEXT}
    told = sorted((item["ref"], item["mark"], item.get("note")) for item in followed)
    from wayline import paper_figures
    figures = paper_figures.plan_lines(plan) if plan is not None else None
    objectives = _read_or(book, "objectives.json")
    found = {
        "introduction": _digest(bodies["introduction"], structure.get("introduction"), objectives, told),
        "results": _digest(bodies["results"], structure.get("results"), _read_or(book, "verifications.json"), told, figures),
        "discussion": _digest(bodies["discussion"], structure.get("discussion"), objectives, told),
        "methods": _digest(bodies["methods"], structure.get("methods"), _read_or(book, "methods_inventory.json"), told),
        "supplement": _digest(structure.get("supplement"), bodies, told, figures),
    }
    found["title"] = found["abstract"] = _digest([found[part] for part in MAIN_TEXT])
    found["front"] = _digest(_front_inputs(book))
    return found


# --- the front matter -----------------------------------------------------------------------------------------------


def _intake_data(book):
    """The Data bullets of `research/INTAKE.md`, as the intake wrote them."""
    try:
        text = book.path("INTAKE.md").read_text(encoding="utf-8")
    except OSError:
        return []
    match = re.search(r"^## Data\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    lines = [line.strip()[2:].strip() for line in (match.group(1) if match else "").splitlines() if line.strip().startswith("- ")]
    return [line for line in lines if line and line.lower() != "not stated."]


def _manifest_count(book):
    found = _read_or(book, "manifest.json")
    return len((found or {}).get("entries") or []) if isinstance(found, dict) else 0


def front_text(project):
    """`front.md`, written by code: the front matter as the owner gave it, a marked placeholder for what is not given yet,
    and the data and code availability statements from the records."""
    book = ledger_for(project)
    record, repository, data, not_reproduced, manifested = _front_inputs(book)
    lines = ["# Front matter", ""]
    authors = record.get("authors") or []
    lines += ["## Authors", ""]
    if authors:
        affiliations = []
        for author in authors:
            for place in author.get("affiliations") or []:
                if place not in affiliations:
                    affiliations.append(place)
        for author in authors:
            marks = ",".join(str(affiliations.index(place) + 1) for place in author.get("affiliations") or [])
            lines.append("- %s%s%s" % (author["name"], "^%s^" % marks if marks else "",
                                       " (corresponding author%s)" % (", %s" % author["email"] if author.get("email") else "")
                                       if author.get("corresponding") else ""))
        lines += [""] + ["%d. %s" % (number, place) for number, place in enumerate(affiliations, start=1)]
    else:
        lines.append(PLACEHOLDER % "the authors and their affiliations")
    for key, title in (("acknowledgments", "Acknowledgments"), ("funding", "Funding"), ("competing_interests", "Competing interests")):
        lines += ["", "## %s" % title, "", _one_line(record[key]) if record.get(key) else PLACEHOLDER % title.lower()]
    lines += ["", "## Data availability", ""]
    said = "The data this study analysed: %s." % "; ".join(data) if data else PLACEHOLDER % "the data this study analysed"
    lines.append("%s The results it reports were produced by the project's own runs, %d artifact(s) recorded with their "
                 "SHA-256 in the project's manifest. %s" % (said, manifested, PLACEHOLDER % "where the data are deposited"))
    lines += ["", "## Code availability", ""]
    remote = (repository or {}).get("remote") or {}
    if remote.get("repository"):
        public = (repository or {}).get("visibility") == "public"
        lines.append("The code is in the repository %s (%s%s)%s." % (
            remote["repository"], remote.get("url") or "https://github.com/%s" % remote["repository"],
            ", %s" % repository["license"] if repository.get("license") else "",
            "" if public else ", private until the authors make it public: %s" % PLACEHOLDER % "the public URL"))
    else:
        lines.append(PLACEHOLDER % "the code repository, which setup has not settled")
    if not_reproduced:
        lines.append("The code repository does not reproduce: %s." % "; ".join(
            _one_line(item.get("method") or item.get("name") or item) for item in not_reproduced))
    return "\n".join(lines) + "\n"


def set_front(project, values):
    """Record the front matter the owner gave: `values` merged into `research/front.json`, checked; returns the record."""
    if not isinstance(values, dict) or not values:
        raise PaperError("the front matter is a JSON object with authors, acknowledgments, funding, or competing_interests")
    book = ledger_for(project)
    with book.lock():
        record = dict(read_front(book), **values)
        try:
            check(record, load_schema(FRONT_SCHEMA), name="the front matter")
        except ValidationError as failure:
            raise PaperError(str(failure)) from None
        book.write_json(FRONT_JSON, record, schema=FRONT_SCHEMA)
    return record


# --- the composition ------------------------------------------------------------------------------------------------


def read_record(project_or_ledger):
    """`research/paper/paper.json`, the version record; None before the first composition."""
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(_paper(PAPER_JSON))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as failure:
        raise PaperError("research/%s cannot be read: %s" % (_paper(PAPER_JSON), failure)) from None
    try:
        check(record, load_schema(RECORD_SCHEMA), name="research/%s" % _paper(PAPER_JSON))
    except ValidationError as failure:
        raise PaperError(str(failure)) from None
    return record


def _file_text(book, part):
    try:
        return book.path(_paper("%s.md" % part)).read_text(encoding="utf-8")
    except OSError:
        return None


def _plan(book, previous, inputs):
    """`(recompose, kept_edits)`: the parts to make afresh, and those whose owner's edit stands with their inputs unchanged."""
    if previous is None:
        return list(PARTS), []
    recompose, edited = [], []
    for part in PARTS:
        held = previous["parts"][part]
        text = _file_text(book, part)
        if text is None or held["inputs"] != inputs[part]:
            recompose.append(part)
        elif _sha(text) != held["sha256"]:
            edited.append(part)
    return recompose, edited


def _outline_lines(structure):
    lines = []
    for part in structure:
        lines += ["", "### %s" % part.capitalize(), ""]
        entries = structure[part]
        if not entries:
            lines.append("- no heading: %s" % ("nothing is placed in the supplement" if part == "supplement" else "write it unheaded"))
        for entry in entries:
            lines.append("- `{#%s}` %s%s" % (entry["id"], entry["heading"], "  Note from the owner: %s" % entry["note"] if entry.get("note") else ""))
    return "\n".join(lines) + "\n"


def _instruction(answer, passages):
    from wayline import paper_figures
    ref, mark = answer["ref"], answer["mark"]
    if paper_figures.is_figure_ref(ref):
        return None  # the figure plan follows it, and the writer reads the plan
    if ref.startswith("contradiction:"):
        first, second = ref.split(":", 1)[1].split("+")
        if mark == TYPO:
            said = "%s and %s differ by a typo: state the claim once, as the evidence and the rest of the paper have it" % (first, second)
        else:
            kept, other = (first, second) if mark == FIRST else (second, first)
            said = "hold to %s's claim and not %s's" % (kept, other)
    elif ref.startswith("unverifiable:"):
        identifier = ref.split(":", 1)[1]
        reason = _one_line((passages.get(identifier) or {}).get("reason")) or "no reason was recorded"
        said = ("leave %s out" % identifier if mark == LEAVE_OUT else
                "keep %s, stated as not verified, with why: %s" % (identifier, reason))
    elif ref.startswith("reference:"):
        name = ref.split(":", 1)[1]
        said = ("cite %s nowhere: keep a sentence that cited it only where other evidence carries it" % name if mark == DROP else
                'keep the claims citing %s, each marked "to be resolved"' % name)
    elif ref == UNCHECKED_REF:
        said = ("keep the unchecked inherited results as stated, saying that none was checked" if mark == KEEP_AS_STATED else
                "leave the unchecked inherited results out")
    else:
        said = "the outline's proposal: %s" % ("taken" if mark == TAKE else "declined")
    return "- %s: %s%s" % (ref, said, " (the owner's note: %s)" % answer["note"] if answer.get("note") else "")


def _prompt(role, number, version, written, structure, followed, passages, previous, plan):
    reads = ["- research/sections/%s.md: the %s's current passages, which the paper is made from" % (part, part) for part in MAIN_TEXT]
    reads += ["- research/OUTLINE.md, research/OBJECTIVES.md, research/REPORT.md (the general report)",
              "- research/CONCERNS.md (the concerns kept for the order), research/VERIFICATIONS.md when there is one"]
    if previous is not None:
        reads.append("- research/paper/: version %d, the whole of it; what you do not write now stands as it is there" % previous["version"])
    from wayline import paper_figures
    told = [line for line in (_instruction(answer, passages) for answer in followed) if line]
    text = PROMPT % {"order": number, "version": version, "parts": ", ".join(written) or "none",
                     "outline": _outline_lines(structure), "figures": paper_figures.writer_lines(plan),
                     "table": 1 + len(_plan_tables(plan)),
                     "answers": "\n".join(told) or "- none: nothing was asked",
                     "read": "\n".join(reads)}
    return provenance.joined(text, role.protocol, worker.schema_section("# The answer", SCHEMA))


def _plan_tables(plan):
    return [table["id"] for table in (plan or {}).get("tables") or [] if table["main"]]


def _answer_problems(answer, written, structure, kept, plan=None):
    problems = []
    taken = [table["id"] for table in answer.get("tables") or [] if table.get("id") in _plan_tables(plan)]
    if taken:
        problems.append("%s %s the figure plan's, rendered from its CSV: number your tables from T%d" % (
            ", ".join(taken), "is" if len(taken) == 1 else "are", 1 + len(_plan_tables(plan))))
    for part in WRITTEN:
        if part == "title":
            if "title" in written and len([title for title in answer.get("titles") or [] if str(title).strip()]) != 3:
                problems.append("the title is asked for: offer three titles in `titles`, your choice first")
        elif part in written and not (answer.get(part) or "").strip() and (part == "abstract" or structure.get(part)):
            problems.append("%s is asked for and came back empty" % part)
    texts = {part: answer.get(part) for part in written if part in WRITTEN and part != "title"}
    problems += check_structure(structure, {part: text for part, text in texts.items() if part != "abstract"})
    for part in ("abstract",):
        if part in texts and _headings(texts[part]):
            problems.append("the abstract is one paragraph with no heading")
    problems += kept_problems(dict(texts, title="\n".join(answer.get("titles") or [])), kept)
    return problems


def _write_session(project, number, version, written, structure, followed, previous, harness_root, policy, plan=None):
    """The one writer session: its envelope, its answer checked and resumed once with what failed."""
    from wayline import sections
    book = ledger_for(project)
    role = worker.read_role(ROLE, harness_root, project)
    passages = {item.get("id"): item for item in sections.read_passages(book)}
    prompt = _prompt(role, number, version, [part for part in WRITTEN if part in written], structure, followed, passages, previous, plan)
    request = provenance.structured_request(project, role, policy, harness_root, prompt, SCHEMA, WRITER_BUDGET,
                                            provenance.session_dir(project, SESSIONS), read_only=True)
    kept = inherited_kept(project)

    def problem_of(envelope):
        problem = provenance.schema_problem(envelope, SCHEMA)
        if problem is not None:
            return problem
        found = _answer_problems(envelope.structured_output, written, structure, kept, plan)
        return "\n".join("- %s" % line for line in found) if found else None

    try:
        envelope = provenance._launch_structured(request, problem_of, "paper's writer")
    except provenance.UsageLimited:
        raise
    except provenance.ProvenanceError as failure:
        raise PaperError(str(failure)) from None
    return envelope, request


def _freeze(book, previous):
    """Copy the version on disk under `earlier/v<n>/`, everything of `research/paper/` but `earlier/` itself, once: a
    composition that failed after freezing it leaves the frozen copy as it was, and the next order freezes nothing over it."""
    root = book.path(_paper())
    if not root.is_dir() or book.path(_paper("%s/v%d" % (EARLIER, previous["version"]))).is_dir():
        return
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] == EARLIER:
            continue
        book.write_bytes(_paper("%s/v%d/%s" % (EARLIER, previous["version"], relative.as_posix())), path.read_bytes())


def _table_markdown(table):
    import csv
    import io
    rows = [row for row in csv.reader(io.StringIO(table["csv"].strip()))]
    lines = ["**Table %s.** %s" % (table["id"][1:], _one_line(table["caption"])), ""]
    if rows:
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines.append("| %s |" % " | ".join(cell.replace("|", "\\|") for cell in rows[0]))
        lines.append("|%s|" % "|".join(["---"] * width))
        lines += ["| %s |" % " | ".join(cell.replace("|", "\\|") for cell in row) for row in rows[1:]]
    return "\n".join(lines) + "\n"


def _clear(book, relative_dir, prefix=""):
    directory = book.path(_paper(relative_dir))
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.name.startswith(prefix):
                book.remove_file(_paper("%s/%s" % (relative_dir, path.name)))


def _references(book, texts, followed):
    """The CSL items of the found works the parts cite, each once, less the references the order dropped."""
    from wayline import references
    dropped = {answer["ref"].split(":", 1)[1] for answer in followed if answer["ref"].startswith("reference:") and answer["mark"] == DROP}
    index = references.identifier_index(book.project)
    items, seen = [], set()
    for part in PARTS:
        for parts in references.ref_tags(texts.get(part)):
            work = references.work_named(book, parts, index) if parts is not None else None
            if work is None or work.key in seen or not work.found or (work.slug in dropped or work.named in dropped):
                continue
            seen.add(work.key)
            items.append(references.csl_item(work.record))
    return items


def _reworded(book, texts):
    """The owner's current passages the paper does not carry word for word."""
    from wayline import sections
    said = " %s " % " ".join(_words("\n".join(text or "" for text in texts.values())))
    return [item["id"] for item in _current_passages(book)
            if item.get("by") == sections.OWNER and " %s " % " ".join(_words(item.get("text"))) not in said]


def _left_out(followed, passages, answer):
    found = []
    for item in followed:
        if item["ref"].startswith("unverifiable:") and item["mark"] == LEAVE_OUT:
            identifier = item["ref"].split(":", 1)[1]
            found.append({"what": "%s, an unverifiable claim" % identifier,
                          "why": "unverifiable (%s), and the order left it out" % (_one_line((passages.get(identifier) or {}).get("reason")) or "no reason recorded")})
        elif item["ref"].startswith("reference:") and item["mark"] == DROP:
            found.append({"what": "the reference %s" % item["ref"].split(":", 1)[1], "why": "unresolved, and the order dropped it"})
        elif item["ref"] == UNCHECKED_REF and item["mark"] == LEAVE_OUT:
            found.append({"what": "the unchecked inherited results", "why": "none was verified, and the order left them out"})
    found += [{"what": _one_line(item["what"]), "why": _one_line(item["why"])} for item in (answer or {}).get("left_out") or []]
    return found


def compose(project, payload, *, harness_root=HARNESS_ROOT, policy=None, say=None):
    """Compose the paper for the open order `payload` and write `research/paper/`; returns the version record.

    The sections and the outline are rendered first, taking in the owner's edits; the outline's proposals answered in
    the batch are taken; then each part whose inputs changed is made afresh, the writer's in one session, the front
    matter by code, and the previous version is frozen. Journals `paper_order` with `action: composed`. Raises
    `PaperError` when the writer gave nothing usable, and nothing is written then.
    """
    from wayline import code_repository, outline, paper_figures, sections
    project = Path(project).resolve()
    book = ledger_for(project)
    policy = policy_for(project, harness_root) if policy is None else policy
    sections.render_sections(book)
    outline.render_outline(book)
    followed = answers(project, payload)
    _take_outline_answers(project, followed)
    structure = outline.paper_structure(book)
    plan = paper_figures.build(project, followed, autonomous=read_harness(project).get("autonomy") == AUTONOMOUS,
                               venue=payload.get("venue"))
    previous = read_record(book)
    version = (previous["version"] + 1) if previous else 1
    inputs = part_inputs(project, structure, followed, plan)
    recompose, kept_edits = _plan(book, previous, inputs)
    written = [part for part in recompose if part in WRITTEN]
    envelope, answer = None, {}
    if written:
        envelope, request = _write_session(project, payload["order"], version, written, structure, followed, previous,
                                           harness_root, policy, plan)
        answer = envelope.structured_output
    made = paper_figures.make_figures(project, plan, previous, harness_root=harness_root, policy=policy, say=say)
    passages = {item.get("id"): item for item in sections.read_passages(book)}
    texts = {}
    with book.lock():
        if previous is not None:
            _freeze(book, previous)
        for part in PARTS:
            if part not in recompose:
                texts[part] = _file_text(book, part)
                continue
            if part == "title":
                text = _one_line(answer["titles"][0]) + "\n"
            elif part == "front":
                text = front_text(project)
            else:
                text = (answer.get(part) or "").strip() + "\n"
                if not text.strip():
                    text = ("Nothing is placed in the supplement.\n" if part == "supplement" else
                            "The outline holds nothing for the %s yet.\n" % part.capitalize())
            book.write_markdown(_paper("%s.md" % part), text)
            texts[part] = text
        tables = list((previous or {}).get("tables") or [])
        if "results" in recompose:
            _clear(book, TABLES)
            tables = []
            for table in answer.get("tables") or []:
                book.write_markdown(_paper("%s/%s.csv" % (TABLES, table["id"])), table["csv"].strip() + "\n")
                book.write_markdown(_paper("%s/%s.md" % (TABLES, table["id"])), _table_markdown(table))
                tables.append(table["id"])
        alternatives = [name for name in (previous or {}).get("alternatives") or []
                        if name.split("-")[0] not in recompose]
        for part in recompose:
            if part in WRITTEN:
                _clear(book, ALTERNATIVES, part + "-")
        if "title" in recompose:
            for number, title in enumerate(answer["titles"], start=1):
                book.write_markdown(_paper("%s/title-%d.md" % (ALTERNATIVES, number)), _one_line(title) + "\n")
                alternatives.append("title-%d" % number)
        counts = {}
        for item in answer.get("alternatives") or []:
            if item["part"] not in recompose:
                continue
            counts[item["part"]] = counts.get(item["part"], 0) + 1
            name = "%s-%d" % (item["part"], counts[item["part"]])
            book.write_markdown(_paper("%s/%s.md" % (ALTERNATIVES, name)), "%s\n\n<!-- why: %s -->\n" % (item["text"].strip(), _one_line(item["why"])))
            alternatives.append(name)
        figures = paper_figures.write(book, plan, made)
        planned = [item["id"] for item in figures["tables"]]
        tables = planned + [table for table in tables if table not in planned and not table.startswith("ST")]
        book.write_json(_paper(REFERENCES_JSON), _references(book, texts, followed))
        unchecked = next((("kept" if item["mark"] == KEEP_AS_STATED else "left out") for item in followed if item["ref"] == UNCHECKED_REF), None)
        record = {
            "version": version, "order": payload["order"], "by": payload.get("by") or OWNER,
            "commit": code_repository.main_commit(project), "composed": now_ts(),
            "model": (envelope.model or request.model) if envelope is not None else None,
            "parts": {part: {"version": version if part in recompose else previous["parts"][part]["version"],
                             "inputs": inputs[part], "sha256": _sha(texts[part] or "")} for part in PARTS},
            "tables": tables, "alternatives": sorted(set(alternatives)),
            "answers": [{key: item[key] for key in ("ref", "text", "mark", "by", "batch", "item", "note")} for item in followed],
            "unchecked": unchecked, "left_out": _left_out(followed, passages, answer) + plan["left_out"], "figures": figures,
            "proposals": [_one_line(item) for item in answer.get("proposals") or []] if written else list((previous or {}).get("proposals") or []),
            "reworded": _reworded(book, texts), "kept_edits": kept_edits, "gated": False,
            "usage": ({"usage": envelope.usage, "turns": envelope.num_turns, "duration_ms": envelope.duration_ms,
                       "session_id": envelope.session_id} if envelope is not None else None),
        }
        if not written and previous is not None:
            record["model"] = previous.get("model")
        book.write_json(_paper(PAPER_JSON), record, schema=RECORD_SCHEMA)
        checks = {"structure": check_structure(structure, {part: texts.get(part) for part in outline.PAPER_PARTS}),
                  "kept": kept_problems({part: texts.get(part) for part in WRITTEN}, inherited_kept(project))}
        book.write_markdown(_paper(PAPER_MD), _report(record, recompose, answer, payload, checks))
        book.append_event(PAPER_ORDER, {"order": payload["order"], "action": COMPOSED, "by": payload.get("by") or OWNER,
                                        "version": version, "commit": record["commit"], "parts": recompose})
    if say is not None:
        say("  paper order %d: version %d composed (%s afresh)" % (payload["order"], version, ", ".join(recompose) or "nothing"))
    return record


def _report(record, recompose, answer, payload, checks):
    """`PAPER.md`, the build report, rendered by code from the version record."""
    lines = ["# The paper, version %d" % record["version"], "",
             "Composed by code at paper order %d (%s) from commit %s of main, at %s. %s" % (
                 record["order"], record["by"], record["commit"] or "none (the project has no repository)", record["composed"],
                 "The writer was one read-only session on %s." % record["model"] if record["model"] else "No part needed the writer."),
             "", "This build is not yet gated: no kill argument, independent read, or sampled verdict has judged it. "
                 "Nothing was submitted anywhere.", "", "## Parts", "", "| Part | File | Version | This order |", "|---|---|---|---|"]
    for part in PARTS:
        state = ("made afresh" if part in recompose else "your edit kept" if part in record["kept_edits"] else "unchanged")
        lines.append("| %s | %s.md | %d | %s |" % (part, part, record["parts"][part]["version"], state))
    lines += ["", "Tables: %s. Alternatives: %s." % (", ".join(record["tables"]) or "none",
                                                     ", ".join("alternatives/%s.md" % name for name in record["alternatives"]) or "none"), ""]
    lines += ["## Figures", "", "Code's figure plan, from the outline and the owner's marks on the plots: each figure's plan line "
              "and how it stands.", ""]
    from wayline import paper_figures
    lines += paper_figures.report_lines(record.get("figures")) + [""]
    lines += ["## The batch's answers", ""]
    if not record["answers"]:
        lines.append("Nothing was asked: no contradiction, unverifiable claim, unresolved reference, or outline proposal stood.")
    elif not payload.get("batch"):
        lines.append("No batch was asked under `autonomous`: code's defaults were followed until the decider answers it.")
    for item in record["answers"]:
        lines.append("- %s: %s (by %s%s)%s" % (item["ref"], item["mark"], item["by"],
                                                ", %s item %s" % (item["batch"], item["item"]) if item.get("batch") else "",
                                                "; note: %s" % item["note"] if item.get("note") else ""))
    lines += ["", "## Inherited results", ""]
    if record["unchecked"] is not None:
        lines.append("None of the inherited results was checked before this order; the unchecked ones were %s." % (
            "kept as stated" if record["unchecked"] == "kept" else "left out"))
    else:
        lines.append("Either an inherited result was verified, or the project inherited none.")
    lines += ["", "## Left out, and why", ""]
    lines += ["- %s: %s" % (item["what"], item["why"]) for item in record["left_out"]] or ["Nothing."]
    lines += ["", "## The owner's passages whose wording changed", ""]
    lines += ["- %s: the paper does not carry it word for word" % identifier for identifier in record["reworded"]] or ["None."]
    lines += ["", "## Proposed by the writer, never made", ""]
    lines += ["- %s" % item for item in record["proposals"]] or ["Nothing."]
    if (answer or {}).get("notes"):
        lines += ["", "## The writer's notes", "", _one_line(answer["notes"])]
    lines += ["", "## Checks", "", "On every part as it stands, an owner's edit included.", ""]
    lines.append("- The headings follow the outline's order and placement, each carrying its outline id, and no part carries "
                 "a reference list: %s" % ("passed." if not checks["structure"] else "failed:"))
    lines += ["  - %s" % problem for problem in checks["structure"]]
    lines.append("- No inherited title, abstract, or caption is in any part: %s" % ("passed." if not checks["kept"] else "failed:"))
    lines += ["  - %s" % problem for problem in checks["kept"]]
    lines += ["", "## Cost", ""]
    usage = record["usage"]
    if usage:
        tokens = usage.get("usage") or {}
        lines.append("The writer session %s: %s input and %s output token(s), %s turn(s), %s ms." % (
            usage.get("session_id") or "", tokens.get("input_tokens", "?"), tokens.get("output_tokens", "?"),
            usage.get("turns") if usage.get("turns") is not None else "?", usage.get("duration_ms") if usage.get("duration_ms") is not None else "?"))
    else:
        lines.append("No session: every part stood as it was.")
    lines.append("The card's estimate for an order: %s." % COST)
    return "\n".join(lines) + "\n"


# --- the verb -------------------------------------------------------------------------------------------------------


def paper_command(args):
    """`wayline paper [--yes] [--json] [--project <path>]`, and `wayline paper front - [--project <path>]`.

    Alone it prints the order's card and does nothing else; with `--yes`, the owner's confirmation, it makes the order.
    `paper front -` records the front matter the owner gave, a JSON object on stdin.
    """
    if args and args[0] == "front":
        return _front_command(args[1:])
    parser = argparse.ArgumentParser(prog="wayline paper", description="the paper order: without --yes, its card (the readiness list "
                                     "and the cost, with no model call); with --yes, the order, which composes the paper from the "
                                     "outline and the sections")
    parser.add_argument("--yes", action="store_true", help="the owner's confirmation; without it nothing is done")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the card or the order as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if not options.yes:
            found = card(project)
            print(json.dumps(found, indent=2, default=str) if options.json else card_text(found))
            return 0
        made = order(project)
    except PaperError as failure:
        print("wayline paper: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline paper: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(made, indent=2))
        return 0
    print("paper order %d made." % made["order"])
    if made["batch"]:
        print(batches.render(project, made["batch"]))
        print("The writer waits for these answers: wayline mark %s --defaults takes all defaults." % made["batch"])
    if made["conductor"]:
        print("The running conductor takes it at its next wave: running tickets finish, nothing new launches, the changed "
              "results are drawn, and the paper is composed; then the run resumes.")
    else:
        print("A conductor was started for it%s; once the paper is composed its run ends as the last one did (%s)."
              % (" (%s)" % made["started"] if made["started"] else "", made["run"]))
    return 0


def _front_command(args):
    parser = argparse.ArgumentParser(prog="wayline paper front", description="record the paper's front matter the owner gave: "
                                     "a JSON object of authors, acknowledgments, funding, and competing_interests on stdin")
    parser.add_argument("source", help="- for stdin")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        text = sys.stdin.read() if options.source == "-" else Path(options.source).read_text(encoding="utf-8")
        record = set_front(project, json.loads(text))
    except (PaperError, ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline paper front: %s" % failure, file=sys.stderr)
        return 2
    missing = _front_missing(record)
    print("front matter recorded in research/%s%s" % (FRONT_JSON, "; still to be given: %s" % ", ".join(missing) if missing else ""))
    return 0
