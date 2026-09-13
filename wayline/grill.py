"""Phase P2, the grill: the design tree asked tier by tier, answers in DECISIONS.md, terms in CONTEXT.md.

Implementation Decisions 10 and BRIEF 6.2. The `wayline-grill` skill builds the design tree from
`POSITION.md` and `INTAKE.md` with the owner in the conversation, looks facts up rather than asking
them, and hands every question, answer, and settled term to this verb, because the ledger is the
only writer of `research/` (decision 2) and a model that wrote `DECISIONS.md` itself would bypass it.

The tree lives in `research/DECISIONS.md` itself, so the file the decider, the report, and the
dashboard read is the file the grill writes. Every question is one record of the `decision` schema,
open (`answer: null`) until it is settled. The bullets under each heading are for people; the
record's machine copy is the one-line comment below them, and it is what this module reads back.
Settled records come first, in the order they were settled, and open ones follow in the order they
were asked. A settled record is never rewritten: a changed mind is a new record that `supersedes` it.

A tier is the tree's frontier asked at once: every open question whose prerequisites (`requires`)
are settled. `wayline grill` stamps each question a tier puts to the owner for the first time with
that tier's number; a question left unanswered is asked again in the next tier and keeps its first
number. Under autonomy `autonomous` the frontier is the decider's (ticket 31), so a tier asks the
owner only the human-only questions the decider never resolves (decision 4).
"""

import argparse
import json
import re
import sys
from pathlib import Path

from wayline.cli import parse_args
from wayline.jsonschema import load_schema, validate
from wayline.ledger import DECISION, Ledger, LedgerError, now_ts
from wayline.project import ProjectError, find_project, read_harness

__all__ = [
    "GrillError", "DECISIONS_MD", "CONTEXT_MD", "read_records", "parse_records", "render_decisions", "frontier",
    "missing", "with_question", "with_answer", "with_tier", "with_term", "ask", "answer", "settle_term",
    "apply_batch", "grill_view", "render_grill", "grill_command",
]

DECISIONS_MD = "DECISIONS.md"
CONTEXT_MD = "CONTEXT.md"
POSITION_MD = "POSITION.md"
AUTONOMOUS = "autonomous"

# The machine copy of one record, on a line of its own under the record's bullets.
_RECORD = re.compile(r"^<!-- wayline:decision (\{.*\}) -->$")
_ID = re.compile(r"^Q([1-9][0-9]*)\Z")
# The order a record's keys are written in, so a diff of DECISIONS.md shows what changed and nothing else.
FIELDS = ("id", "ticket", "question", "options", "recommended", "evidence", "requires", "human_only", "reversible",
          "tier", "supersedes", "answer", "rationale", "confidence", "decided_by", "timestamp")
DECIDERS = ("human", "decider")

# What a `--from` batch may carry, per list, and the order the lists are applied in.
BATCH = {
    "questions": ("question", "id", "options", "recommended", "requires", "evidence", "human_only", "reversible"),
    "answers": ("id", "answer", "rationale", "confidence", "revise"),
    "terms": ("term", "definition", "avoid"),
}

INTRO = (
    "The design decisions of this project: the grill's questions, settled by the owner or, once autonomy is "
    "raised, by the decider. `wayline grill` writes this file and reads back the record under each question, "
    "so a decision changes by answering it again (`wayline grill answer <id> ... --revise`), never by editing here."
)
CONTEXT_HEAD = (
    "# Context\n\nThe vocabulary this project's spec, tickets, and report use verbatim, settled in the grill. "
    "`wayline grill term` adds a term or replaces its definition; everything else in this file is kept as written.\n"
)
LANGUAGE = "## Language"
_TERM = re.compile(r"^\*\*(.+)\*\*:\s*$")


class GrillError(ValueError):
    """A write the grill refuses: an unknown question, an open prerequisite, an answer with no rationale."""


# --- reading DECISIONS.md -------------------------------------------------------------------------


def parse_records(text, source=DECISIONS_MD):
    """Every decision record in a DECISIONS.md text, in file order, each checked against the `decision` schema.

    A record the schema rejects, or a tree whose ids, prerequisites, or revisions do not hold
    together, raises `ProjectError` naming the line: a hand edit is reported, never taken on trust.
    """
    records, schema = [], load_schema("decision")
    for number, line in enumerate(str(text).split("\n"), 1):
        found = _RECORD.match(line.strip())
        if found is None:
            continue
        try:
            record = json.loads(found.group(1))
        except ValueError as failure:
            raise ProjectError("%s line %d: the decision record is not JSON: %s" % (source, number, failure)) from None
        errors = validate(record, schema)
        if errors:
            raise ProjectError("%s line %d: the decision record is not valid: %s" % (
                source, number, "; ".join("%s %s" % (error.path, error.message) for error in errors)))
        records.append(record)
    problems = _structure(records)
    if problems:
        raise ProjectError("%s: %s" % (source, "; ".join(problems)))
    return records


def _structure(records):
    """What the schema cannot see: unique ids, prerequisites and revisions that name earlier records."""
    problems, seen = [], {}
    for record in records:
        identifier = record.get("id")
        if identifier is None and record.get("ticket") is None:
            problems.append("a record for %r names neither a question id nor a ticket" % record["question"])
        if _settled(record) and (record.get("decided_by") is None or record.get("timestamp") is None):
            problems.append("%s is answered with no decided_by or no timestamp" % (identifier or "ticket %s" % record.get("ticket")))
        for need in record.get("requires") or []:
            if need not in seen:
                problems.append("%s requires %s, which no earlier record is" % (identifier, need))
        if record.get("supersedes") is not None:
            earlier = seen.get(record["supersedes"])
            if earlier is None or not _settled(earlier) or not _settled(record):
                problems.append("%s supersedes %s, which is not an earlier settled record" % (identifier, record["supersedes"]))
        if identifier is not None:
            if identifier in seen:
                problems.append("%s appears twice" % identifier)
            seen[identifier] = record
    return problems


def read_records(project):
    """The records of the project's `research/DECISIONS.md`; none when the file does not exist.

    A file with text in it and no record is one wayline did not write, and the grill will not
    overwrite it.
    """
    path = Ledger(project).path(DECISIONS_MD)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    records = parse_records(text, "research/" + DECISIONS_MD)
    if not records and text.strip():
        raise ProjectError("research/%s holds text wayline did not write; move it aside and the grill writes its own" % DECISIONS_MD)
    return records


# --- the tree -------------------------------------------------------------------------------------


def _settled(record):
    return record.get("answer") is not None


def _questions(records):
    return {record["id"]: record for record in records if record.get("id")}


def missing(record, records):
    """The prerequisites of `record` that are not settled yet, in the order it names them."""
    questions = _questions(records)
    return [need for need in record.get("requires") or [] if need not in questions or not _settled(questions[need])]


def frontier(records):
    """The open questions whose prerequisites are all settled, in the order they were asked."""
    return [record for record in records if record.get("id") and not _settled(record) and not missing(record, records)]


def _waiting(records):
    return [record for record in records if record.get("id") and not _settled(record) and missing(record, records)]


def _superseded(records):
    return {record["supersedes"]: record["id"] for record in records if record.get("supersedes")}


def _current_tier(records):
    return max((record["tier"] for record in records if record.get("tier")), default=0)


def _next_id(records):
    numbers = [int(_ID.match(identifier).group(1)) for identifier in _questions(records)]
    return "Q%d" % (max(numbers, default=0) + 1)


def _text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise GrillError("%s needs some text" % what)
    return value.strip()


def _strings(value, what):
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in value):
        raise GrillError("%s is a list of non-empty strings" % what)
    return [item.strip() for item in value]


def _normal(text):
    return " ".join(str(text).split()).casefold()


def _ordered(record):
    return {**{key: record[key] for key in FIELDS if key in record}, **{key: value for key, value in record.items() if key not in FIELDS}}


def _check(record):
    errors = validate(record, load_schema("decision"))
    if errors:
        raise GrillError("the decision record for %r is not valid: %s" % (
            record.get("question"), "; ".join("%s %s" % (error.path, error.message) for error in errors)))
    return record


def with_question(records, question, identifier=None, options=(), recommended=None, requires=(), evidence=(),
                  human_only=False, reversible=True):
    """`records` with one open question added to the tree, and that question.

    The id is the one given (`Q` and a number nobody holds) or the next free one. A prerequisite must
    already be in the tree, which is what keeps the tree acyclic, and a question the tree already
    asks, in any spelling of the same words, is refused with the record that asks it.
    """
    question = _text(question, "a question")
    identifier = identifier or _next_id(records)
    if not isinstance(identifier, str) or not _ID.match(identifier):
        raise GrillError("a question's id is Q and a number, like Q3; got %r" % (identifier,))
    questions = _questions(records)
    if identifier in questions:
        raise GrillError("%s is already the question %r" % (identifier, questions[identifier]["question"]))
    same = next((record for record in questions.values() if _normal(record["question"]) == _normal(question)), None)
    if same is not None:
        raise GrillError("the design tree already asks this as %s" % same["id"])
    requires = list(dict.fromkeys(_strings(requires, "requires")))
    unknown = [need for need in requires if need not in questions]
    if unknown:
        raise GrillError("%s requires %s, which the design tree does not hold; add a prerequisite before the questions that need it"
                         % (identifier, ", ".join(unknown)))
    if recommended is not None and not isinstance(recommended, str):
        raise GrillError("a recommended answer is text")
    record = _check({
        "id": identifier, "question": question, "options": _strings(options, "options"),
        "recommended": recommended.strip() if recommended and recommended.strip() else None,
        "evidence": _strings(evidence, "evidence"), "requires": requires,
        "human_only": _flag(human_only, "human_only"), "reversible": _flag(reversible, "reversible"),
        "tier": None, "supersedes": None, "answer": None, "rationale": None, "confidence": None, "decided_by": None,
        "timestamp": None,
    })
    return records + [record], record


def _flag(value, what):
    if not isinstance(value, bool):
        raise GrillError("%s is true or false" % what)
    return value


def with_answer(records, identifier, text, rationale, confidence=None, decided_by="human", revise=False, ts=None):
    """`records` with one question settled, and the settled record.

    An open question is settled in place and moves to the end of the settled records. A settled one
    is answered again only with `revise`, as a new record that supersedes it, so the old answer stays
    on the record. A question whose prerequisites are open is refused, and so is the decider on a
    human-only question (decision 4).
    """
    record = _questions(records).get(identifier)
    if record is None:
        raise GrillError("the design tree has no question %s" % (identifier,))
    text = _text(text, "an answer")
    rationale = _text(rationale, "an answer's rationale")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
        raise GrillError("confidence is a number from 0 to 1, or not stated; got %r" % (confidence,))
    if decided_by not in DECIDERS:
        raise GrillError("decided_by is one of %s, got %r" % (", ".join(DECIDERS), decided_by))
    if decided_by == "decider" and record.get("human_only"):
        raise GrillError("%s is human-only: the decider never resolves it, and it waits for the owner" % identifier)
    answered = {"answer": text, "rationale": rationale, "confidence": confidence, "decided_by": decided_by, "timestamp": ts or now_ts()}
    position = sum(1 for other in records if _settled(other))
    if _settled(record):
        if not revise:
            raise GrillError("%s is settled (%r); a changed answer is a revision: wayline grill answer %s \"<answer>\" "
                             "--rationale \"<why>\" --revise" % (identifier, record["answer"], identifier))
        later = _superseded(records).get(identifier)
        if later is not None:
            raise GrillError("%s was revised already by %s; revise %s instead" % (identifier, later, later))
        revision = _check(dict(record, id=_next_id(records), tier=_current_tier(records) or None, supersedes=identifier, **answered))
        return records[:position] + [revision] + records[position:], revision
    needs = missing(record, records)
    if needs:
        raise GrillError("%s waits on %s, which %s not settled; a tier asks a question only once its prerequisites are"
                         % (identifier, ", ".join(needs), "is" if len(needs) == 1 else "are"))
    settled = _check(dict(record, **answered))
    rest = [other for other in records if other is not record]
    return rest[:position] + [settled] + rest[position:], settled


def with_tier(records, autonomy):
    """`records` with the tier to ask stamped, the tier's number, and its questions.

    The tier is the frontier, minus what the decider takes under `autonomous`. A frontier holding a
    question no tier has asked opens the next tier and stamps those questions with it; one holding
    only questions asked before is the tier already open. An empty frontier is no tier (None).
    """
    asked = [record for record in frontier(records) if autonomy != AUTONOMOUS or record.get("human_only")]
    if not asked:
        return records, None, []
    current = _current_tier(records)
    fresh = {record["id"] for record in asked if record.get("tier") is None}
    if not fresh:
        return records, current, asked
    tier = current + 1
    stamp = lambda record: dict(record, tier=tier) if record.get("id") in fresh else record  # noqa: E731
    return [stamp(record) for record in records], tier, [stamp(record) for record in asked]


# --- CONTEXT.md -----------------------------------------------------------------------------------


def with_term(text, term, definition, avoid=()):
    """A CONTEXT.md text with one term added under `## Language`, or its definition replaced; and which.

    The entry has the glossary's own shape: `**Term**:`, the definition on one line, and an
    `_Avoid_:` line when there are words to avoid. Everything outside the term's entry is kept.
    Returns `(text, "added" | "replaced" | "unchanged")`.
    """
    term = _text(term, "a term")
    if "\n" in term or "**" in term:
        raise GrillError("a term is a name on one line, got %r" % term)
    definition = _text(definition, "a term's definition")
    if re.search(r"\n\s*\n", definition):
        raise GrillError("a term's definition is one paragraph; the glossary keeps one sentence or two per term")
    avoid = [avoid] if isinstance(avoid, str) else list(avoid or ())
    words = [word.strip() for item in _strings(avoid, "avoid") for word in item.split(",") if word.strip()]
    entry = ["**%s**:" % term, " ".join(definition.split())] + (["_Avoid_: %s" % ", ".join(words)] if words else [])
    lines = (text if text and text.strip() else CONTEXT_HEAD).rstrip("\n").split("\n")
    start = next((index for index, line in enumerate(lines) if line.strip() == LANGUAGE), None)
    if start is None:
        lines += ["", LANGUAGE]
        start = len(lines) - 1
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    blocks, block = [], []
    for line in lines[start + 1:end]:
        if line.strip():
            block.append(line)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    outcome = "added"
    for index, existing in enumerate(blocks):
        found = _TERM.match(existing[0])
        if found and found.group(1).strip().casefold() == term.casefold():
            if existing == entry:
                return text, "unchanged"
            blocks[index], outcome = entry, "replaced"
            break
    else:
        blocks.append(entry)
    body = [""]
    for existing in blocks:
        body += existing + [""]
    return "\n".join(lines[:start + 1] + body + lines[end:]).rstrip("\n") + "\n", outcome


# --- writing through the ledger -------------------------------------------------------------------


def _write_records(ledger, records):
    ledger.write_markdown(DECISIONS_MD, render_decisions(records))


def _journal(ledger, record):
    """The `decision` event of one settled record; a grill question has no ticket, so its id leads the answer."""
    ledger.append_event(DECISION, {
        "ticket": None, "answer": "%s %s Answer: %s" % (record["id"], record["question"], record["answer"]),
        "decided_by": record["decided_by"], "rationale": record["rationale"], "confidence": record["confidence"],
    }, ts=record["timestamp"])


def _read_context(ledger):
    try:
        return ledger.path(CONTEXT_MD).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def ask(project, question, **fields):
    """`wayline grill ask`: add one open question to the design tree; returns its record."""
    ledger = Ledger(project)
    with ledger.lock():
        records, record = with_question(read_records(project), question, **fields)
        _write_records(ledger, records)
    return record


def answer(project, identifier, text, rationale, confidence=None, decided_by="human", revise=False):
    """`wayline grill answer`: settle one question in DECISIONS.md and journal it as a `decision`.

    The decider (ticket 31) settles through this function too, with `decided_by="decider"`.
    """
    ledger = Ledger(project)
    with ledger.lock():
        records, record = with_answer(read_records(project), identifier, text, rationale, confidence=confidence,
                                      decided_by=decided_by, revise=revise, ts=now_ts())
        _write_records(ledger, records)
        _journal(ledger, record)
    return record


def settle_term(project, term, definition, avoid=()):
    """`wayline grill term`: write one settled term to CONTEXT.md; returns `added`, `replaced`, or `unchanged`."""
    ledger = Ledger(project)
    with ledger.lock():
        before = _read_context(ledger)
        text, outcome = with_term(before, term, definition, avoid)
        if outcome != "unchanged":
            ledger.write_markdown(CONTEXT_MD, text)
    return outcome


def apply_batch(project, batch):
    """`wayline grill --from`: questions, then answers, then terms, all checked before anything is written.

    Returns the count of each. One refused entry refuses the batch, so a session never leaves half a
    tier recorded.
    """
    if not isinstance(batch, dict):
        raise GrillError("a grill batch is a JSON object with %s" % ", ".join(BATCH))
    unknown = sorted(set(batch) - set(BATCH))
    if unknown:
        raise GrillError("a grill batch does not know %s; it takes %s" % (", ".join(unknown), ", ".join(BATCH)))
    lists = {}
    for key, fields in BATCH.items():
        entries = batch.get(key) or []
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise GrillError("%s is a list of objects" % key)
        for entry in entries:
            extra = sorted(set(entry) - set(fields))
            if extra:
                raise GrillError("an entry of %s does not know %s; it takes %s" % (key, ", ".join(extra), ", ".join(fields)))
        lists[key] = entries
    ledger = Ledger(project)
    with ledger.lock():
        records = read_records(project)
        for entry in lists["questions"]:
            records, _ = with_question(
                records, entry.get("question"), identifier=entry.get("id"), options=entry.get("options"),
                recommended=entry.get("recommended"), requires=entry.get("requires"), evidence=entry.get("evidence"),
                human_only=entry.get("human_only", False), reversible=entry.get("reversible", True))
        answered = []
        for entry in lists["answers"]:
            records, record = with_answer(records, entry.get("id"), entry.get("answer"), entry.get("rationale"),
                                          confidence=entry.get("confidence"), revise=entry.get("revise") is True, ts=now_ts())
            answered.append(record)
        before = context = _read_context(ledger)
        for entry in lists["terms"]:
            context, _ = with_term(context, entry.get("term"), entry.get("definition"), entry.get("avoid") or ())
        if lists["questions"] or lists["answers"]:
            _write_records(ledger, records)
        if context != before:
            ledger.write_markdown(CONTEXT_MD, context)
        for record in answered:
            _journal(ledger, record)
    return {key: len(entries) for key, entries in lists.items()}


# --- DECISIONS.md ----------------------------------------------------------------------------------


def render_decisions(records):
    """DECISIONS.md: the settled records in the order they were settled, then the open ones."""
    superseded = _superseded(records)
    settled = [record for record in records if _settled(record)]
    still_open = [record for record in records if not _settled(record)]
    parts = ["# Decisions", "", INTRO, "", "## Settled", ""]
    if not settled:
        parts += ["Nothing is settled yet.", ""]
    for record in settled:
        parts += _render_record(record, records, superseded)
    parts += ["## Open", ""]
    if not still_open:
        parts += ["Nothing is open.", ""]
    for record in still_open:
        parts += _render_record(record, records, superseded)
    return "\n".join(parts).rstrip("\n") + "\n"


def _line(text):
    return " ".join(str(text).split())


def _render_record(record, records, superseded):
    name = record.get("id") or "Ticket %s" % record.get("ticket")
    lines = ["### %s. %s" % (name, _line(record["question"])), ""]
    if _settled(record):
        confidence = record.get("confidence")
        lines += [
            "- answer: " + _line(record["answer"]),
            "- rationale: " + (_line(record["rationale"]) if record.get("rationale") else "not stated"),
            "- decided-by: " + str(record["decided_by"]),
            "- confidence: " + ("not stated" if confidence is None else "%g" % confidence),
            "- timestamp: " + str(record["timestamp"]),
        ]
    elif record.get("id"):
        needs = missing(record, records)
        lines.append("- waiting on: " + ", ".join(needs) if needs else "- open: its prerequisites are settled")
    if record.get("id"):
        lines.append("- tier: %s" % (record["tier"] if record.get("tier") else "not asked in a tier"))
    if record.get("recommended"):
        lines.append("- recommended: " + _line(record["recommended"]))
    if record.get("options"):
        lines.append("- options: " + "; ".join(_line(option) for option in record["options"]))
    if record.get("requires"):
        lines.append("- requires: " + ", ".join(record["requires"]))
    if record.get("evidence"):
        lines.append("- evidence:")
        lines += ["  - " + _line(item) for item in record["evidence"]]
    if record.get("human_only"):
        lines.append("- human-only: yes")
    if record.get("reversible") is False:
        lines.append("- reversible: no")
    if record.get("supersedes"):
        lines.append("- supersedes: " + record["supersedes"])
    if record.get("id") in superseded:
        lines.append("- superseded-by: " + superseded[record["id"]])
    return lines + ["", _machine(record), ""]


def _machine(record):
    """The record as the one-line comment `parse_records` reads: compact JSON that no character can end early."""
    text = json.dumps(_ordered(record), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for character in "<>\x85  ":
        text = text.replace(character, "\\u%04x" % ord(character))
    return "<!-- wayline:decision %s -->" % text


# --- the view -------------------------------------------------------------------------------------


def grill_view(project, stamp=True):
    """What `wayline grill` prints, as a structure: the tier to ask, the decider's share, what waits.

    With `stamp` the tier's new questions are stamped with its number in DECISIONS.md, which is what
    asking a tier means; the dashboard passes `stamp=False` to look without asking.
    """
    project = Path(project).resolve()
    autonomy = read_harness(project)["autonomy"]
    ledger = Ledger(project)
    with ledger.lock():
        records = read_records(project)
        stamped, tier, asked = with_tier(records, autonomy)
        if stamp and stamped != records:
            _write_records(ledger, stamped)
            records = stamped
    superseded = _superseded(records)
    current = [record for record in records if record.get("id") and record["id"] not in superseded]
    return {
        "project": str(project),
        "autonomy": autonomy,
        "decisions": "research/" + DECISIONS_MD,
        "position": ("research/" + POSITION_MD) if ledger.path(POSITION_MD).is_file() else None,
        "tier": tier,
        "ask": asked,
        "decider": [record for record in frontier(records) if autonomy == AUTONOMOUS and not record.get("human_only")],
        "waiting": [dict(record, needs=missing(record, records)) for record in _waiting(records)],
        "settled": sum(1 for record in current if _settled(record)),
        "total": len(current),
    }


def render_grill(view):
    """The text `wayline grill` prints."""
    lines = ["grill  %s" % view["project"],
             "autonomy %s   settled %d of %d in %s" % (view["autonomy"], view["settled"], view["total"], view["decisions"]),
             ("position memo  %s" % view["position"]) if view["position"] else
             "no position memo yet: wayline position writes it, and until then the tree rests on INTAKE.md alone", ""]
    if not view["total"]:
        lines.append('no questions yet: build the design tree from POSITION.md and INTAKE.md with '
                     'wayline grill ask "<question>" --recommend "<answer>" (the wayline-grill skill does)')
        return "\n".join(lines)
    if view["ask"]:
        count = len(view["ask"])
        lines.append("tier %d: ask the owner %s at once, numbered, each with its recommended answer" % (
            view["tier"], "this question" if count == 1 else "these %d questions" % count))
        for number, record in enumerate(view["ask"], 1):
            marks = [mark for mark, on in (("human-only", record.get("human_only")),
                                           ("irreversible", record.get("reversible") is False),
                                           ("first asked in tier %s" % record.get("tier"), record.get("tier") not in (None, view["tier"])))
                     if on]
            lines.append("  %d. %s  %s%s" % (number, record["id"], _line(record["question"]), "  (%s)" % ", ".join(marks) if marks else ""))
            if record.get("options"):
                lines.append("       options: %s" % " | ".join(_line(option) for option in record["options"]))
            lines.append("       recommended: %s" % (_line(record["recommended"]) if record.get("recommended") else "none given; give one before asking"))
            for item in record.get("evidence") or []:
                lines.append("       evidence: %s" % _line(item))
        lines.append("")
    if view["decider"]:
        lines.append("autonomy is autonomous: the decider (ticket 31) resolves these %d open question%s, and never a human-only one"
                     % (len(view["decider"]), "" if len(view["decider"]) == 1 else "s"))
        lines += ["  %s  %s" % (record["id"], _line(record["question"])) for record in view["decider"]]
        lines.append("")
    if view["waiting"]:
        lines.append("waiting on answers (%d)" % len(view["waiting"]))
        lines += ["  %s  %s  needs %s" % (record["id"], _line(record["question"]), ", ".join(record["needs"])) for record in view["waiting"]]
        lines.append("")
    if not (view["ask"] or view["decider"] or view["waiting"]):
        lines.append("every question is settled: the frontier is empty and the grill is done")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


# --- the verb -------------------------------------------------------------------------------------


def grill_command(args):
    args = list(args)
    if args and args[0] in _SUBCOMMANDS:
        return _SUBCOMMANDS[args[0]](args[1:])
    parser = argparse.ArgumentParser(
        prog="wayline grill",
        description="phase P2: ask the owner the design tree's frontier one tier at a time. Alone, it stamps and prints "
                    "the tier to ask. `wayline grill ask` adds a question to the tree, `wayline grill answer` settles one, "
                    "`wayline grill term` settles a term in CONTEXT.md, and --from applies a batch of the three first.")
    parser.add_argument("--from", dest="batch", metavar="FILE",
                        help='{"questions": [...], "answers": [...], "terms": [...]} as JSON, or - for stdin')
    parser.add_argument("--json", action="store_true", help="print the tier as JSON")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if options.batch:
            apply_batch(project, _load_json(options.batch))
        view = grill_view(project)
    except GrillError as failure:
        return _refuse(failure)
    except (ProjectError, LedgerError, OSError) as failure:
        return _fail(failure)
    print(json.dumps(view, ensure_ascii=False, indent=2) if options.json else render_grill(view))
    return 0


def _ask_command(args):
    parser = argparse.ArgumentParser(prog="wayline grill ask", description="add one open question to the design tree")
    parser.add_argument("question", help="the question, as the owner will read it")
    parser.add_argument("--id", help="its id, Q and a number; the next free one by default")
    parser.add_argument("--option", action="append", default=[], help="one option the owner chooses among")
    parser.add_argument("--recommend", help="the recommended answer")
    parser.add_argument("--requires", action="append", default=[], metavar="ID", help="a question whose answer this one waits on")
    parser.add_argument("--evidence", action="append", default=[], help="a fact looked up that bears on it, with where it was found")
    parser.add_argument("--human-only", action="store_true", help="in a human-only class: the decider never resolves it")
    parser.add_argument("--irreversible", action="store_true", help="its answer cannot be taken back")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    return _run(options, lambda project: _said_asked(ask(
        project, options.question, identifier=options.id, options=options.option, recommended=options.recommend,
        requires=options.requires, evidence=options.evidence, human_only=options.human_only, reversible=not options.irreversible)))


def _said_asked(record):
    print("%s  added to the design tree: %s" % (record["id"], _line(record["question"])))
    if record["requires"]:
        print("  waits on %s" % ", ".join(record["requires"]))


def _answer_command(args):
    parser = argparse.ArgumentParser(prog="wayline grill answer", description="settle one question of the design tree as the owner's answer")
    parser.add_argument("id", help="the question, like Q3")
    parser.add_argument("answer", help="the owner's answer")
    parser.add_argument("--rationale", required=True, help="why: the owner's reason, or the recommendation's when they took it")
    parser.add_argument("--confidence", type=float, help="0 to 1, when the owner's words say how sure they are")
    parser.add_argument("--revise", action="store_true", help="answer a settled question again, superseding its record")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    return _run(options, lambda project: _said_answered(answer(
        project, options.id, options.answer, options.rationale, confidence=options.confidence, revise=options.revise)))


def _said_answered(record):
    revised = "  (supersedes %s)" % record["supersedes"] if record.get("supersedes") else ""
    print("%s  settled by the %s: %s%s" % (record["id"], record["decided_by"], _line(record["answer"]), revised))
    print("  written to research/%s and journaled as a decision" % DECISIONS_MD)


def _term_command(args):
    parser = argparse.ArgumentParser(prog="wayline grill term", description="settle one term in research/CONTEXT.md")
    parser.add_argument("term", help="the term, as the spec and the tickets will write it")
    parser.add_argument("definition", help="what it means in this project, in one paragraph")
    parser.add_argument("--avoid", action="append", default=[], help="words not to use for it, comma-separated")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    return _run(options, lambda project: print("term  %s  %s in research/%s" % (
        options.term.strip(), settle_term(project, options.term, options.definition, options.avoid), CONTEXT_MD)))


_SUBCOMMANDS = {"ask": _ask_command, "answer": _answer_command, "term": _term_command}


def _run(options, action):
    try:
        action(find_project(options.project))
    except GrillError as failure:
        return _refuse(failure)
    except (ProjectError, LedgerError, OSError) as failure:
        return _fail(failure)
    return 0


def _load_json(source):
    try:
        text = sys.stdin.read() if source == "-" else Path(source).expanduser().read_text(encoding="utf-8")
    except OSError as failure:
        raise GrillError("--from %s cannot be read: %s" % (source, failure.strerror)) from None
    try:
        return json.loads(text)
    except ValueError as failure:
        raise GrillError("--from %s is not JSON: %s" % (source, failure)) from None


def _refuse(failure):
    print("wayline grill: %s" % failure, file=sys.stderr)
    return 2


def _fail(failure):
    print("wayline grill: %s" % failure, file=sys.stderr)
    return 1
