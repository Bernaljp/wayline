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
owner only the human-only and irreversible questions, which the decider never resolves (decision 4).

**The first tier settles the objectives** (decision 17; ticket 80). While the project is in its setup
(its phase is not past P2), before its first tier and, once the position memo is written, before every
tier, `wayline grill` adds one question per objective no question names yet: each open or parked one
`objectives.json` holds, and each new one the memo's directions propose, so a memo written after a tier
was asked is put to the owner too. Each asks
whether the project takes it, `open` or `parked`, is human-only (the owner's at every autonomy), and
carries the objective in its record's `objective` field. While any of them is open on the frontier, a
tier asks the owner only those, since the questions after them build on which objectives the project
takes; the decider's share is as it was. The owner's answer is recorded through the objectives' ledger
as an `objective` event: a recorded objective moves to the status chosen (refused when it was answered,
dropped, or reframed since it was asked), and a proposed one is recorded with it, its new id kept on
the settled record and on any revision of it.

**The repeated claims of a start midway** (decision 17; ticket 95). While the project is in its setup, each pair
of inherited claims the repeated-claims check lists for the grill (a contradiction standing, a pair a check kept
apart, a pair the confirmer flagged) is one human-only question, asked once (`with_repeat_questions`).
"""

import argparse
import json
import re
import sys
from pathlib import Path

from wayline import replay
from wayline.cli import parse_args
from wayline.jsonschema import load_schema, validate
from wayline.ledger import DECISION, Ledger, LedgerError, make_event, now_ts
from wayline.project import ProjectError, find_project, read_harness
from wayline.tickets import DECISION as DECISION_KIND, read_tickets

__all__ = [
    "GrillError", "DECISIONS_MD", "CONTEXT_MD", "read_records", "parse_records", "render_decisions", "frontier",
    "missing", "with_question", "with_answer", "with_tier", "with_term", "ask", "answer", "settle_term", "with_human_only",
    "turn_over", "apply_batch", "grill_view", "render_grill", "grill_command", "machine_line", "record_payload", "superseded_by",
    "decider_share", "TAKE", "objective_questions", "with_objective_questions",
]

DECISIONS_MD = "DECISIONS.md"
CONTEXT_MD = "CONTEXT.md"
POSITION_MD = "POSITION.md"
AUTONOMOUS = "autonomous"

# The machine copy of one record, on a line of its own under the record's bullets.
_RECORD = re.compile(r"^<!-- wayline:decision (\{.*\}) -->$")
_ID = re.compile(r"^Q([1-9][0-9]*)\Z")
# The order a record's keys are written in, so a diff of DECISIONS.md shows what changed and nothing else.
FIELDS = ("id", "ticket", "question", "options", "recommended", "evidence", "requires", "objective", "concerns", "objection", "material",
          "human_only", "reversible",
          "tier", "supersedes", "answer", "rationale", "confidence", "decided_by", "model", "fallback_from", "session_id",
          "timestamp")
# What a settled record carries about the session that answered it (decision 15; ticket 31): never on the owner's answer.
SESSION_FIELDS = ("model", "fallback_from", "session_id")
# `conductor` is the conductor closing the ask of decision 15, superseded or answered at its timeout; the grill reads it back.
DECIDERS = ("human", "decider", "conductor")

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
_TERM = re.compile(r"^\*\*(.+?)\*\*:")
_SECTION_END = re.compile(r"^#{1,2}\s")


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


def owners(record):
    """Whether only the owner settles a question: it is in a human-only class, or its answer cannot be taken back.

    Decision 4 puts both out of the decider's reach, so under `autonomous` they are still the owner's.
    """
    return bool(record.get("human_only")) or record.get("reversible") is False


def missing(record, records, questions=None):
    """The prerequisites of `record` that are not settled yet, in the order it names them."""
    questions = _questions(records) if questions is None else questions
    return [need for need in record.get("requires") or [] if need not in questions or not _settled(questions[need])]


def frontier(records):
    """The open questions whose prerequisites are all settled, in the order they were asked."""
    questions = _questions(records)
    return [record for record in records if record.get("id") and not _settled(record) and not missing(record, records, questions)]


def _waiting(records):
    questions = _questions(records)
    return [record for record in records if record.get("id") and not _settled(record) and missing(record, records, questions)]


def decider_share(records):
    """The frontier's questions the decider resolves under `autonomous`: every open one that is not the owner's (decision 4)."""
    return [record for record in frontier(records) if not owners(record)]


def superseded_by(records):
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
                  human_only=False, reversible=True, objective=None, concerns=None, objection=None, material=None):
    """`records` with one open question added to the tree, and that question.

    The id is the one given (`Q` and a number nobody holds) or the next free one. A prerequisite must
    already be in the tree, which is what keeps the tree acyclic, and a question the tree already
    asks, in any spelling of the same words, is refused with the record that asks it. `objective`
    (`{id, text}`) makes it a question of the first tier, answered `open` or `parked` (ticket 80);
    `concerns` (`{place, objective, ids}`) a question on the critic's proposed places, answered `take it`
    or `another place`, and `objection` (`{index, text}`) one on an objection of the hostile review,
    answered `reject` or an accept with its place (ticket 96); `material` (`{ids}`) the setup's one question on the missing
    material the inherited results need, answered with a reply per item (ticket 97).
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
    record = {
        "id": identifier, "question": question, "options": _strings(options, "options"),
        "recommended": recommended.strip() if recommended and recommended.strip() else None,
        "evidence": _strings(evidence, "evidence"), "requires": requires,
        "human_only": _flag(human_only, "human_only"), "reversible": _flag(reversible, "reversible"),
        "tier": None, "supersedes": None, "answer": None, "rationale": None, "confidence": None, "decided_by": None,
        "timestamp": None,
    }
    if objective is not None:
        record["objective"] = objective
    if concerns is not None:
        record["concerns"] = concerns
    if objection is not None:
        record["objection"] = objection
    if material is not None:
        record["material"] = material
    record = _check(_ordered(record))
    return records + [record], record


def _flag(value, what):
    if not isinstance(value, bool):
        raise GrillError("%s is true or false" % what)
    return value


def with_answer(records, identifier, text, rationale, confidence=None, decided_by="human", revise=False, ts=None,
                model=None, fallback_from=None, session_id=None):
    """`records` with one question settled, and the settled record.

    An open question is settled in place and moves to the end of the settled records. A settled one
    is answered again only with `revise`, as a new record that supersedes it, so the old answer stays
    on the record. A question whose prerequisites are open is refused, and so is the decider on a
    human-only or irreversible question (decision 4). `model` is the model the answering session ran
    on, `fallback_from` is `fable` when it ran on Opus in Fable's place (decision 15), and `session_id`
    names that session (ticket 31); an answer no model gave carries none of them, and a revision never
    inherits the ones before it.
    """
    if not isinstance(identifier, str):
        raise GrillError("a question's id is Q and a number, like Q3; got %r" % (identifier,))
    record = _questions(records).get(identifier)
    if record is None:
        raise GrillError("the design tree has no question %s" % (identifier,))
    text = _text(text, "an answer")
    if record.get("objective"):
        taken = text.casefold().rstrip(".")
        if taken not in TAKE:
            raise GrillError("%s asks whether the project takes an objective: answer open or parked, got %r" % (identifier, text))
        text = taken
    elif record.get("concerns") and record["concerns"].get("place") is None:
        from wayline.concerns import parse_place  # the concerns module reads the documents and the sections
        if parse_place(text) is None:
            raise GrillError("%s asks where a concern goes: answer tie it to O<n>, for the order, or decline: <the reason>, "
                             "got %r" % (identifier, text))
    elif record.get("concerns"):
        taken = text.casefold().rstrip(".")
        if taken not in CONCERN_ANSWERS:
            raise GrillError("%s asks whether concerns go where the critic proposes: answer %s, got %r"
                             % (identifier, " or ".join(CONCERN_ANSWERS), text))
        text = taken
    elif record.get("objection"):
        if not re.match(r"^(?:reject|accept)\b", text.strip(), re.IGNORECASE):
            raise GrillError("%s asks whether the work answers an objection: answer reject, or accept with where it goes "
                             "(\"accept: tie it to O1\", \"accept: for the order\"), got %r" % (identifier, text))
    rationale = _text(rationale, "an answer's rationale")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
        raise GrillError("confidence is a number from 0 to 1, or not stated; got %r" % (confidence,))
    if decided_by not in DECIDERS:
        raise GrillError("decided_by is one of %s, got %r" % (", ".join(DECIDERS), decided_by))
    revise = _flag(revise, "revise")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise GrillError("model is the name of the model the answer ran on, got %r" % (model,))
    if model is not None and decided_by == "human":
        raise GrillError("an answer the owner gave ran on no model, so it carries neither model nor fallback_from")
    if fallback_from not in (None, "fable") or (fallback_from and model is None):
        raise GrillError("fallback_from is fable, on an answer that names the model it ran on in Fable's place; got %r" % (fallback_from,))
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip() or model is None):
        raise GrillError("session_id names the session of an answer that names its model; got %r" % (session_id,))
    if decided_by == "decider" and owners(record):
        raise GrillError("%s is %s: the decider never resolves it, and it waits for the owner"
                         % (identifier, "human-only" if record.get("human_only") else "irreversible"))
    answered = {"answer": text, "rationale": rationale, "confidence": confidence, "decided_by": decided_by, "timestamp": ts or now_ts()}
    answered.update({key: value for key, value in zip(SESSION_FIELDS, (model, fallback_from, session_id)) if value is not None})
    base = {key: value for key, value in record.items() if key not in SESSION_FIELDS}
    position = sum(1 for other in records if _settled(other))
    if _settled(record):
        if not revise:
            raise GrillError("%s is settled (%r); a changed answer is a revision: wayline grill answer %s \"<answer>\" "
                             "--rationale \"<why>\" --revise" % (identifier, record["answer"], identifier))
        later = superseded_by(records).get(identifier)
        if later is not None:
            raise GrillError("%s was revised already by %s; revise %s instead" % (identifier, later, later))
        revision = _check(dict(base, id=_next_id(records), tier=_current_tier(records) or None, supersedes=identifier, **answered))
        return records[:position] + [revision] + records[position:], revision
    needs = missing(record, records)
    if needs:
        raise GrillError("%s waits on %s, which %s not settled; a tier asks a question only once its prerequisites are"
                         % (identifier, ", ".join(needs), "is" if len(needs) == 1 else "are"))
    settled = _check(dict(base, **answered))
    rest = [other for other in records if other is not record]
    return rest[:position] + [settled] + rest[position:], settled


def with_tier(records, autonomy):
    """`records` with the tier to ask stamped, the tier's number, and its questions.

    The tier is the frontier, minus what the decider takes under `autonomous`: everything but the
    human-only and irreversible questions. A frontier holding a question no tier has asked opens the
    next tier and stamps those questions with it; one holding only questions asked before is the tier
    already open. An empty frontier is no tier (None).
    """
    asked = [record for record in frontier(records) if autonomy != AUTONOMOUS or owners(record)]
    leading = [record for record in asked if record.get("objective")]
    if leading:
        asked = leading  # the first tier settles the objectives before anything that builds on them (ticket 80)
    if not asked:
        return records, None, []
    current = _current_tier(records)
    fresh = {record["id"] for record in asked if record.get("tier") is None}
    if not fresh:
        return records, current, asked
    tier = current + 1
    stamp = lambda record: dict(record, tier=tier) if record.get("id") in fresh else record  # noqa: E731
    return [stamp(record) for record in records], tier, [stamp(record) for record in asked]


# --- the first tier: the objectives (decision 17; ticket 80) ---------------------------------------


# The two answers a question of the first tier takes: the project pursues the objective now, or sets it aside.
TAKE = ("open", "parked")
# The two answers a question on the critic's proposed places takes (ticket 96), the marks of a `concern_placements` batch.
CONCERN_ANSWERS = ("take it", "another place")
POSITION_JSON = "position.json"   # the position memo's record, which `wayline.position` writes
# The phases of the setup, while the first tier's questions are still added (decision 17: setup ends at specify).
SETUP_PHASES = (None, "P0", "P1", "P2")


def _direction_name(index, direction):
    return "direction %d (%s, %s)" % (index, _line(direction.get("title") or "untitled"), direction.get("distance"))


def _memo_line(row):
    revised = row.get("revised_target")
    value = revised.get("value") if isinstance(revised, dict) else None
    return "position memo: %s %s%s: %s" % (row.get("id"), row.get("verdict"),
                                          " (revised target %g)" % value if isinstance(value, (int, float)) else "",
                                          _line(row.get("reasoning") or "no reasoning given"))


def objective_questions(objectives, memo=None, midway=False):
    """The first tier's questions, as `with_question` fields: one per objective to take, open or parked.

    One for each open or parked objective `objectives` holds, recommended as it stands, with the memo's verdict
    on it and the directions that would pursue it as evidence; then one for each new objective the memo's
    directions propose (`id` null), in the memo's order, a question two directions propose asked once. The
    proposals of the nearest direction that proposes any are recommended `open`, the rest `parked`. At a start midway
    (`midway`, decision 17; ticket 97) the critic also proposes "Do the inherited results hold?", recommended `open`,
    unless the project records it already.
    """
    memo = memo if isinstance(memo, dict) else {}
    rows = {row.get("id"): row for row in memo.get("objectives") or () if isinstance(row, dict)}
    directions = [direction for direction in memo.get("directions") or () if isinstance(direction, dict)]
    specs, proposed = [], {}
    for objective in objectives or ():
        if objective.get("status") not in TAKE:
            continue
        identifier = objective["id"]
        measure = objective.get("measure")
        evidence = ["research/OBJECTIVES.md: %s is %s, %s" % (identifier, objective["status"], "a goal measured by `%s`"
                                                                % measure.get("metric") if measure else "an objective without a measure")]
        if identifier in rows:
            evidence.append(_memo_line(rows[identifier]))
        evidence += ["the position memo's %s would pursue it" % _direction_name(index, direction)
                     for index, direction in enumerate(directions, 1)
                     if any(isinstance(named, dict) and named.get("id") == identifier for named in direction.get("objectives") or ())]
        specs.append({"objective": {"id": identifier, "text": objective["text"]},
                      "question": "Does the project take %s, \"%s\": open or parked?" % (identifier, _line(objective["text"])),
                      "recommended": objective["status"], "evidence": evidence})
    recorded = {_normal(objective.get("text") or "") for objective in objectives or ()}
    nearest = None
    for index, direction in enumerate(directions, 1):
        for named in direction.get("objectives") or ():
            if not isinstance(named, dict) or named.get("id") is not None or not str(named.get("text") or "").strip():
                continue
            key = _normal(named["text"])
            if key in recorded:
                continue
            said = "the position memo's %s proposes it" % _direction_name(index, direction)
            if key in proposed:
                proposed[key]["evidence"].append(said)
                continue
            nearest = nearest or index
            text = " ".join(str(named["text"]).split())
            proposed[key] = {"objective": {"id": None, "text": text},
                             "question": "Does the project take the objective the position memo proposes, \"%s\": open or parked?"
                                         % _line(text),
                             "recommended": "open" if index == nearest else "parked", "evidence": [said]}
            specs.append(proposed[key])
    from wayline.verification import OBJECTIVE  # the verification module reads the sections and the concerns
    if midway and memo and _normal(OBJECTIVE) not in recorded and _normal(OBJECTIVE) not in proposed:
        specs.append({"objective": {"id": None, "text": OBJECTIVE},
                      "question": "Does the project take the objective the critic proposes at this start midway, \"%s\": open or "
                                  "parked?" % OBJECTIVE,
                      "recommended": "open",
                      "evidence": ["research/POSITION.md, what each inherited result needs: at every start midway the critic "
                                   "proposes it, open by default, and code answers it once every inherited result has a verdict "
                                   "or is unverifiable"]})
    return specs


def with_objective_questions(records, specs):
    """`records` with the first tier's questions added, each human-only.

    An objective a question already names is skipped, and so is one whose question the tree already asks in
    other words' record (a session that typed it with `grill ask`), so adding them never refuses the tree.
    """
    named = {(record["objective"].get("id") or _normal(record["objective"]["text"]))
             for record in records if record.get("objective")}
    asked = {_normal(record["question"]) for record in records}
    for spec in specs:
        key = spec["objective"]["id"] or _normal(spec["objective"]["text"])
        if key in named or _normal(spec["question"]) in asked:
            continue
        records, _ = with_question(records, spec["question"], options=list(TAKE), recommended=spec["recommended"],
                                   evidence=spec["evidence"], human_only=True, objective=spec["objective"])
        named.add(key)
    return records


def in_setup(events):
    """Whether the project is still in its setup: the journal has not moved it past P2 (decision 17)."""
    phase = None
    for event in events:
        if event.get("event") == "phase" and (event.get("payload") or {}).get("to"):
            phase = event["payload"]["to"]
    return phase in SETUP_PHASES


def _seeded(project, records, events):
    """`records` with a first-tier question for every objective no question names yet, while the project is in its setup.

    Before the first tier, and after it only once the position memo is written: a tree asked before objectives
    existed and with no memo since is left as it is. A question on a contradiction the owner has since marked not one
    is settled with that mark at any time (ticket 95).
    """
    records = with_dismissed_contradictions(project, records)
    if not in_setup(events) or (_current_tier(records) and not Ledger(project).path(POSITION_JSON).is_file()):
        return records
    from wayline.objectives import ObjectivesUnreadable, read_objectives  # the objectives module imports the gates
    try:
        objectives = read_objectives(project)
    except ObjectivesUnreadable as failure:
        raise ProjectError(str(failure)) from None
    try:
        memo = (Ledger(project).read_json(POSITION_JSON) or {}).get("memo")
    except (OSError, ValueError, AttributeError):
        memo = None
    from wayline import verification  # the verification module reads the sections and the concerns
    records = with_objective_questions(records, objective_questions(objectives, memo, verification.midway(project)))
    records = with_repeat_questions(project, records)
    if memo is None or any(record.get("objective") and not _settled(record) for record in records):
        return records  # the concerns' questions name the objectives taken, so they wait for the first tier's answers
    return with_material_question(project, with_concern_questions(project, records, memo, objectives))


def with_material_question(project, records):
    """`records` with the setup's one question on the missing material (decision 17; ticket 97), human-only, asked once for
    the items no open question covers: every missing item the inherited results need, each with its replies."""
    from wayline import verification  # the verification module reads the sections and the concerns

    try:
        spec = verification.material_question(project)
    except verification.VerificationUnreadable as failure:
        raise ProjectError(str(failure)) from None
    if spec is None:
        return records
    covered = {identifier for record in records if record.get("material") and not _settled(record) for identifier in record["material"]["ids"]}
    ids = [identifier for identifier in spec["material"]["ids"] if identifier not in covered]
    if not ids:
        return records
    if ids != spec["material"]["ids"]:
        spec = verification.material_question(project, only=ids)
    asked = sum(1 for record in records if record.get("material"))
    question = spec["question"] if not asked else spec["question"].replace("?", " (asked %d time%s before, for the items still "
                                                                             "waiting)?" % (asked, "" if asked == 1 else "s"), 1)
    records, _ = with_question(records, question, options=spec["options"], recommended=spec["recommended"],
                               evidence=spec["evidence"], human_only=True, material=spec["material"])
    return records


def with_concern_questions(project, records, memo, objectives):
    """`records` with the setup's questions on concerns (decision 17; ticket 96), each human-only, none asked twice.

    One per objection of the memo's hostile review, whether the work must answer it and where; then, over the concerns
    still waiting with the critic's proposal, one per proposed objective with its concerns, one for the order, and one
    for the declines. A group a question already names, in the same concerns, is not asked again.
    """
    from wayline import concerns  # the concerns module reads the documents and the sections; loaded when the memo is there

    try:
        held = concerns.read_concerns(project)
    except concerns.ConcernsUnreadable as failure:
        raise ProjectError(str(failure)) from None
    asked = {_normal(record["question"]) for record in records}
    objections = {record["objection"]["index"] for record in records if record.get("objection")}
    for spec in concerns.objection_questions(memo, objectives):
        if spec["objection"]["index"] in objections or _normal(spec["question"]) in asked:
            continue
        records, _ = with_question(records, spec["question"], options=spec["options"], human_only=True,
                                   evidence=["research/POSITION.md, the hostile reviewer, objection %d" % spec["objection"]["index"]],
                                   objection=spec["objection"])
    named = {tuple(record["concerns"]["ids"]) for record in records if record.get("concerns") and record["concerns"].get("place")}
    for spec in concerns.group_questions(held):
        if tuple(spec["concerns"]["ids"]) in named or _normal(spec["question"]) in asked:
            continue
        records, _ = with_question(records, spec["question"], options=list(CONCERN_ANSWERS), recommended=CONCERN_ANSWERS[0],
                                   evidence=spec["evidence"], human_only=True, concerns=spec["concerns"])
    # A concern no open question covers (no proposal reached it, or a group's answer named no place) is asked about alone.
    for spec in concerns.sort_questions(held, objectives, records):
        if _normal(spec["question"]) in {_normal(record["question"]) for record in records}:
            continue
        records, _ = with_question(records, spec["question"], options=spec["options"], recommended=spec["recommended"],
                                   evidence=spec["evidence"], human_only=True, concerns=spec["concerns"])
    return records


def with_repeat_questions(project, records):
    """`records` with one human-only question per pair the repeated-claims check lists for the grill (ticket 95).

    Each contradicting pair of inherited claims standing, and each pair kept apart or flagged by the confirmer, is asked
    once: a question the tree already asks, in any spelling, is not asked again. A contradiction the owner marked not one
    is no longer listed (`with_dismissed_contradictions` settles the question on it). Reads only.
    """
    from wayline import repeats  # the repeated-claims check reads the sections and the batches

    try:
        listed = repeats.grill_items(project)
    except (repeats.RepeatsError, LedgerError, OSError, ValueError) as failure:
        raise ProjectError("the repeated claims cannot be read: %s" % failure) from None
    for spec in listed:
        if _normal(spec["question"]) in {_normal(record["question"]) for record in records}:
            continue
        records, _ = with_question(records, spec["question"], options=spec["options"], recommended=spec["recommended"],
                                   evidence=spec["evidence"], human_only=True)
    return records


def with_dismissed_contradictions(project, records):
    """`records` with each open question on a contradiction the owner marked not one settled by that mark (ticket 95).

    The mark is the owner's answer, given in the marks view, so the question is answered `not a contradiction` by them,
    with the batch and item as its rationale. Reads only.
    """
    from wayline import repeats  # the repeated-claims check reads the sections and the batches

    try:
        marked = repeats.dismissed(project)
    except (repeats.RepeatsError, LedgerError, OSError, ValueError) as failure:
        raise ProjectError("the repeated claims cannot be read: %s" % failure) from None
    for evidence, why in marked:
        for record in [record for record in records if evidence in (record.get("evidence") or []) and not _settled(record)]:
            records, _ = with_answer(records, record["id"], "not a contradiction", why, decided_by="human")
    return records


def _objective_of(record, records):
    """The objective a first-tier record settles: its own, or for a revision of a proposal, the id its first answer recorded."""
    taken = dict(record["objective"])
    earlier = _questions(records).get(record.get("supersedes"))
    while taken.get("id") is None and earlier is not None:
        taken["id"] = (earlier.get("objective") or {}).get("id")
        earlier = _questions(records).get(earlier.get("supersedes"))
    return taken


def _check_takes(project, records, identifiers):
    """Why the first-tier answers in `identifiers` cannot be recorded, before any is: an objective closed since it was asked."""
    from wayline.objectives import read_objectives  # the objectives module imports the gates
    held = {objective["id"]: objective for objective in read_objectives(project)}
    questions = _questions(records)
    for identifier in identifiers:
        record = questions[identifier]
        if not record.get("objective"):
            continue
        taken = _objective_of(record, records)
        if taken.get("id") is None:
            continue
        found = held.get(taken["id"])
        if found is None:
            raise GrillError("%s asks about %s, which objectives.json does not hold" % (identifier, taken["id"]))
        if found.get("status") not in TAKE:
            raise GrillError("%s asks about %s, which is %s since it was asked: the grill takes or parks only an open or parked "
                             "objective" % (identifier, taken["id"], found.get("status")))


def _take_objective(project, record, records):
    """Record the owner's answer to a first-tier question through the objectives' ledger; returns the record to keep.

    A recorded objective moves to the status answered; a proposed one is recorded with it, and the record names the
    id it got (a revision of it changes that objective). Either way one `objective` event says so, `by: owner`; a
    parked one keeps the rationale as its answer.
    """
    if not record.get("objective") or not _settled(record):
        return record
    from wayline.objectives import ObjectiveError, add_objective, change_objective  # the objectives module imports the gates
    taken = _objective_of(record, records)
    status = record["answer"]
    why = None if status == "open" else record.get("rationale")
    try:
        if taken.get("id"):
            change_objective(project, taken["id"], status, by="owner", answer=why)
        else:
            taken["id"] = add_objective(project, taken["text"], by="owner", status=status, answer=why)[0]["id"]
    except ObjectiveError as failure:
        raise GrillError("%s could not be recorded in the objectives: %s" % (record["id"], failure)) from None
    if taken == record["objective"]:
        return record
    return _check(_ordered(dict(record, objective=taken)))


def _with_taken(project, records, identifiers):
    """`records` after the first-tier answers in `identifiers` are recorded in the objectives, each kept record in its place.

    Every answer is checked before any is recorded, so a refused one leaves the objectives as they were.
    """
    _check_takes(project, records, identifiers)
    _check_concern_takes(project, records, identifiers)
    _check_material_takes(project, records, identifiers)
    for identifier in identifiers:
        record = _questions(records)[identifier]
        kept = _take_objective(project, record, records)
        if kept is not record:
            records = [kept if other is record else other for other in records]
        _take_concerns(project, kept)
        _take_material(project, kept)
    return records


def _check_material_takes(project, records, identifiers):
    """Why the answers on the missing material in `identifiers` cannot be recorded, before any answer is (ticket 97): a reply
    an item does not take, or an answer that names none."""
    from wayline import verification  # the verification module reads the sections and the concerns

    questions = _questions(records)
    for identifier in identifiers:
        record = questions[identifier]
        if not _settled(record) or not record.get("material"):
            continue
        problem = verification.check_replies(project, record["material"]["ids"], record["answer"])
        if problem is not None:
            raise GrillError("%s could not be recorded in the verifications: %s" % (identifier, problem))


def _take_material(project, record):
    """Record the owner's replies on the missing material through the verifications' ledger (ticket 97)."""
    if not _settled(record) or not record.get("material"):
        return
    from wayline import verification  # the verification module reads the sections and the concerns
    try:
        verification.take_replies(project, record["material"]["ids"], record["answer"], "owner")
    except (verification.VerificationError, verification.VerificationUnreadable) as failure:
        raise GrillError("%s could not be recorded in the verifications: %s" % (record["id"], failure)) from None


def _check_concern_takes(project, records, identifiers):
    """Why the answers on concerns in `identifiers` cannot be recorded, before any answer is (ticket 96): a place that
    cannot be taken, such as a tie to an objective closed since the question was asked or a decline with no reason."""
    from wayline import concerns  # the concerns module reads the documents and the sections

    questions = _questions(records)
    for identifier in identifiers:
        record = questions[identifier]
        if not _settled(record) or not (record.get("concerns") or record.get("objection")):
            continue
        try:
            if record.get("concerns"):
                problem = concerns.check_group(project, record["concerns"], record["answer"], record.get("rationale"),
                                               revise=bool(record.get("supersedes")))
            else:
                problem = concerns.check_objection(project, record["answer"], record.get("rationale"))
        except concerns.ConcernsUnreadable as failure:
            problem = str(failure)
        if problem is not None:
            raise GrillError("%s could not be recorded in the concerns: %s" % (identifier, problem))


def _take_concerns(project, record):
    """Record the owner's answer to a question on concerns through the concerns' ledger (ticket 96).

    A group's `take it` places each concern as the critic proposed, `another place` where the rationale says (or leaves
    them to be sorted), and their batch items are marked alike; an accepted objection becomes a concern with the memo as
    its source. A refused placement (a decline with no reason, an objective closed since) refuses the answer.
    """
    if not _settled(record) or not (record.get("concerns") or record.get("objection")):
        return
    from wayline import concerns  # the concerns module reads the documents and the sections
    try:
        if record.get("concerns"):
            concerns.take_group(project, record["concerns"], record["answer"], record.get("rationale"),
                                revise=bool(record.get("supersedes")))
        else:
            concerns.from_objection(project, record["objection"], record["answer"], record.get("rationale"))
    except (concerns.ConcernError, concerns.ConcernsUnreadable) as failure:
        raise GrillError("%s could not be recorded in the concerns: %s" % (record["id"], failure)) from None


# --- CONTEXT.md -----------------------------------------------------------------------------------


def with_term(text, term, definition, avoid=()):
    """A CONTEXT.md text with one term added under `## Language`, or its definition replaced; and which.

    The entry has the glossary's own shape: `**Term**:`, the definition on one line, and an
    `_Avoid_:` line when there are words to avoid. An existing entry is found whether its definition
    follows on the same line or the next, and runs to the next blank line, term, or heading. Every
    line outside that entry is kept as it was; a new entry goes at the end of `## Language`, which
    ends at the next `#` or `##` heading. Returns `(text, "added" | "replaced" | "unchanged")`.
    """
    term = _text(term, "a term")
    if "\n" in term or "**" in term:
        raise GrillError("a term is a name on one line, got %r" % term)
    definition = _text(definition, "a term's definition")
    if re.search(r"\n\s*\n", definition):
        raise GrillError("a term's definition is one paragraph; the glossary keeps one sentence or two per term")
    words = [word.strip() for item in _strings([avoid] if isinstance(avoid, str) else avoid, "avoid")
             for word in item.split(",") if word.strip()]
    entry = ["**%s**:" % term, " ".join(definition.split())] + (["_Avoid_: %s" % ", ".join(words)] if words else [])
    lines = (text if text and text.strip() else CONTEXT_HEAD).rstrip("\n").split("\n")
    start = next((index for index, line in enumerate(lines) if line.strip() == LANGUAGE), None)
    if start is None:
        lines += ["", LANGUAGE]
        start = len(lines) - 1
    end = next((index for index in range(start + 1, len(lines)) if _SECTION_END.match(lines[index])), len(lines))
    for index in range(start + 1, end):
        found = _TERM.match(lines[index])
        if found is None or found.group(1).strip().casefold() != term.casefold():
            continue
        after = index + 1
        while after < end and lines[after].strip() and not _TERM.match(lines[after]) and not lines[after].startswith("#"):
            after += 1
        if lines[index:after] == entry:
            return text, "unchanged"
        lines[index:after] = entry
        return "\n".join(lines) + "\n", "replaced"
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    tail = lines[last:]
    lines[last:] = [""] + entry + ([""] if tail and tail[0].strip() else []) + tail
    return "\n".join(lines) + "\n", "added"


# --- writing through the ledger -------------------------------------------------------------------


def _write_records(ledger, records):
    ledger.write_markdown(DECISIONS_MD, render_decisions(records))


def record_payload(record):
    """The `decision` payload of one settled record; a grill question has no ticket, so its id leads the answer."""
    payload = {"ticket": None, "answer": "%s %s Answer: %s" % (record["id"], record["question"], record["answer"]),
               "decided_by": record["decided_by"], "rationale": record["rationale"], "confidence": record["confidence"]}
    payload.update({key: record[key] for key in ("model", "fallback_from") if record.get(key)})
    return payload


def _journal_settled(ledger, records, now=()):
    """Journal every settled question the journal does not hold yet; returns their ids.

    DECISIONS.md is written first and the journal second, so a process killed in between leaves a
    settled record with no `decision`. Every write of the grill calls this, and so that record is
    journaled by the next one. The records named in `now`, settled by this call, carry their own
    timestamp into the journal; one left behind by a crash is journaled at the time it is found.
    """
    events, _ = ledger.read_events()
    known = {(event.get("payload") or {}).get("answer") for event in events if event.get("event") == DECISION and event.get("ticket") is None}
    journaled = []
    for record in records:
        if not record.get("id") or not _settled(record) or record_payload(record)["answer"] in known:
            continue
        ledger.append_event(DECISION, record_payload(record), ts=record["timestamp"] if record["id"] in now else None,
                            session_id=record.get("session_id"))
        journaled.append(record["id"])
    return journaled


def _read_context(ledger):
    try:
        return ledger.path(CONTEXT_MD).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


# The origin of the decision ticket the decider opens for a question it was refused (ticket 31): `grill Q8`.
TICKET_ORIGIN = "grill "


def _settle_from_tickets(project, ledger, records):
    """`records` with every refused question settled from the owner's answer to its decision ticket, and their ids.

    The decider (ticket 31) turns a question it is refused into a human-only decision ticket whose origin
    names the question. The owner may answer that ticket (`wayline answer`, the dashboard) instead of the
    grill, and the tree must not stay open on a question the owner has answered: the ticket's `decision`
    settles the question here as the owner's, with the ticket named in the rationale when they gave none.
    An answer the owner gave in the grill first leaves the ticket's answer alone.
    """
    open_human = {record["id"] for record in records if record.get("id") and not _settled(record) and record.get("human_only")}
    if not open_human:
        return records, []
    try:
        decision_tickets = [ticket for ticket in read_tickets(project)
                            if ticket["kind"] == DECISION_KIND and str(ticket.get("origin") or "").startswith(TICKET_ORIGIN)]
    except (ValueError, OSError):
        return records, []
    if not decision_tickets:
        return records, []
    events, _ = ledger.read_events()
    view = replay.replay(events)
    settled = []
    for ticket in decision_tickets:
        identifier = ticket["origin"][len(TICKET_ORIGIN):].strip()
        answered = view.answers.get(ticket["id"])
        if identifier not in open_human or answered is None or answered.get("decided_by") != "human" or not answered.get("answer"):
            continue
        if missing(_questions(records)[identifier], records):
            continue
        records, record = with_answer(records, identifier, answered["answer"],
                                      answered.get("rationale") or "the owner answered on decision ticket %d" % ticket["id"],
                                      confidence=answered.get("confidence"), decided_by="human", ts=now_ts())
        settled.append(record["id"])
    return records, settled


def ask(project, question, **fields):
    """`wayline grill ask`: add one open question to the design tree; returns its record."""
    ledger = Ledger(project)
    with ledger.lock():
        records, record = with_question(read_records(project), question, **fields)
        _write_records(ledger, records)
    return record


def answer(project, identifier, text, rationale, confidence=None, decided_by="human", revise=False, model=None, fallback_from=None,
           session_id=None):
    """`wayline grill answer`: settle one question in DECISIONS.md and journal it as a `decision`.

    The decider (ticket 31, `wayline.decider`) settles through this function too, with `decided_by="decider"`,
    the `model` its session ran on, `fallback_from` when it ran on Opus while Fable's weekly window was spent
    (decision 15), and its `session_id`, so the `decision` it journals records the model and the session that
    made it.
    """
    ledger = Ledger(project)
    with ledger.lock():
        records, record = with_answer(read_records(project), identifier, text, rationale, confidence=confidence,
                                      decided_by=decided_by, revise=revise, ts=now_ts(), model=model, fallback_from=fallback_from,
                                      session_id=session_id)
        make_event(DECISION, record_payload(record), ts=record["timestamp"])  # an event the journal refuses writes nothing
        records = _with_taken(project, records, [record["id"]])
        record = _questions(records)[record["id"]]
        _write_records(ledger, records)
        _journal_settled(ledger, records, now=(record["id"],))
        if decided_by == "human":
            _answer_ticket_of(project, ledger, record)
    return record


def _answer_ticket_of(project, ledger, record):
    """The owner's grill answer to a refused question answers its decision ticket too, so none stays open in the dashboard.

    The decider (ticket 31) opens a human-only decision ticket for a question it was refused (origin `grill
    Qn`); the owner may answer in the grill instead. The ticket then takes the same answer as the owner's,
    through `project.answer`, and the conductor closes it at its next wave. A ticket already answered or closed
    is left alone.
    """
    from wayline.project import answer as answer_ticket  # the project module imports the grill's readers
    identifier = record.get("supersedes") or record.get("id")
    try:
        found = [ticket for ticket in read_tickets(project)
                 if ticket["kind"] == DECISION_KIND and str(ticket.get("origin") or "") == TICKET_ORIGIN + identifier]
    except (ValueError, OSError):
        return
    for ticket in found:
        try:
            answer_ticket(project, ticket["id"], record["answer"], rationale=record.get("rationale"), confidence=record.get("confidence"),
                          by="grill")
        except (ProjectError, OSError):
            continue  # answered already, or closed


def append_ticket_record(project, record):
    """Append one settled decision-ticket record (`ticket` set, no `id`) to `research/DECISIONS.md`; returns it.

    The decider's answer to a decision ticket (ticket 31) lands here as well as in the ticket's file and the
    journal, so the file of the project's design decisions holds every decision the decider made. A record
    for the same ticket and answer already there is not appended twice; the record is checked against the
    schema first, and nothing is journaled here, since `decisions.decide` journals the decision itself.
    """
    record = _check(_ordered(dict(record)))
    if record.get("ticket") is None or record.get("id") is not None or not _settled(record):
        raise GrillError("a ticket record names its ticket, no question id, and its answer")
    ledger = Ledger(project)
    with ledger.lock():
        records = read_records(project)
        if any(other.get("ticket") == record["ticket"] and other.get("answer") == record["answer"] for other in records):
            return record
        _write_records(ledger, records + [record])
    return record


def with_human_only(records, identifier, why):
    """`records` with one open question turned over to the owner, and that record.

    The decider's answer to it was refused (ticket 31): the record gains `human_only: true`, so the next
    tier asks the owner and the decider never takes it again, and `why` joins its evidence so the owner
    reads the refusal where the question is. A settled question is never rewritten, so one is refused.
    """
    record = _questions(records).get(identifier)
    if record is None:
        raise GrillError("the design tree has no question %s" % (identifier,))
    if _settled(record):
        raise GrillError("%s is settled, and a settled record is never rewritten" % identifier)
    why = _text(why, "the reason a question is the owner's")
    turned = _check(dict(record, human_only=True, evidence=list(record.get("evidence") or []) + [why]))
    return [turned if other is record else other for other in records], turned


def turn_over(project, identifier, why):
    """Mark one open question of `research/DECISIONS.md` human-only, with `why` in its evidence; returns the record."""
    ledger = Ledger(project)
    with ledger.lock():
        records, record = with_human_only(read_records(project), identifier, why)
        _write_records(ledger, records)
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
                                          confidence=entry.get("confidence"), revise=entry.get("revise", False), ts=now_ts())
            make_event(DECISION, record_payload(record), ts=record["timestamp"])
            answered.append(record["id"])
        before = context = _read_context(ledger)
        for entry in lists["terms"]:
            context, _ = with_term(context, entry.get("term"), entry.get("definition"), entry.get("avoid"))
        # Last, once every question, answer, and term is checked, so a refused entry recorded no objective.
        records = _with_taken(project, records, answered)
        if lists["questions"] or lists["answers"]:
            _write_records(ledger, records)
        if context != before:
            ledger.write_markdown(CONTEXT_MD, context)
        _journal_settled(ledger, records, now=answered)
    return {key: len(entries) for key, entries in lists.items()}


# --- DECISIONS.md ----------------------------------------------------------------------------------


def render_decisions(records):
    """DECISIONS.md: the settled records in the order they were settled, then the open ones."""
    superseded = superseded_by(records)
    settled = [record for record in records if _settled(record)]
    still_open = [record for record in records if not _settled(record)]
    questions = _questions(records)
    parts = ["# Decisions", "", INTRO, "", "## Settled", ""]
    if not settled:
        parts += ["Nothing is settled yet.", ""]
    for record in settled:
        parts += _render_record(record, records, superseded, questions)
    parts += ["## Open", ""]
    if not still_open:
        parts += ["Nothing is open.", ""]
    for record in still_open:
        parts += _render_record(record, records, superseded, questions)
    return "\n".join(parts).rstrip("\n") + "\n"


def _line(text):
    """Text on one line of the markdown a person reads; a `<!--` in it would hide the rest of the record in a rendered view."""
    return " ".join(str(text).split()).replace("<!--", "<\\!--")


def _render_record(record, records, superseded, questions):
    name = record.get("id") or "Ticket %s" % record.get("ticket")
    lines = ["### %s. %s" % (name, _line(record["question"])), ""]
    if _settled(record):
        confidence = record.get("confidence")
        lines += [
            "- answer: " + _line(record["answer"]),
            "- rationale: " + (_line(record["rationale"]) if record.get("rationale") else "not stated"),
            "- decided-by: " + str(record["decided_by"]),
        ] + ([
            "- model: %s%s" % (record["model"], " in place of %s, whose weekly window was spent" % record["fallback_from"]
                               if record.get("fallback_from") else ""),
        ] if record.get("model") else []) + [
            "- confidence: " + ("not stated" if confidence is None else "%g" % confidence),
            "- timestamp: " + str(record["timestamp"]),
        ]
    elif record.get("id"):
        needs = missing(record, records, questions)
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
    return lines + ["", machine_line(record), ""]


def machine_line(record):
    """The record as the one-line comment `parse_records` reads: compact JSON that no character can end early."""
    text = json.dumps(_ordered(record), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for character in "<>\x85  ":
        text = text.replace(character, "\\u%04x" % ord(character))
    return "<!-- wayline:decision %s -->" % text


# --- the view -------------------------------------------------------------------------------------


def grill_view(project, stamp=True):
    """What `wayline grill` prints, as a structure: the tier to ask, the decider's share, what waits.

    With `stamp` the tier's new questions are stamped with its number in DECISIONS.md, which is what
    asking a tier means, and a settled question a crash left unjournaled is journaled; the dashboard
    passes `stamp=False` to look without asking, which reads without taking the ledger's lock.
    """
    project = Path(project).resolve()
    autonomy = read_harness(project)["autonomy"]
    ledger = Ledger(project)
    if stamp:
        with ledger.lock():
            records = read_records(project)
            settled, now = _settle_from_tickets(project, ledger, _seeded(project, records, ledger.read_events()[0]))
            stamped, tier, asked = with_tier(settled, autonomy)
            if stamped != records:
                _write_records(ledger, stamped)
                records = stamped
            _journal_settled(ledger, records, now=now)
    else:
        records = _seeded(project, read_records(project), ledger.read_events()[0])
        _, tier, asked = with_tier(records, autonomy)
    superseded = superseded_by(records)
    questions = _questions(records)
    current = [record for record in records if record.get("id") and record["id"] not in superseded]
    return {
        "project": str(project),
        "autonomy": autonomy,
        "decisions": "research/" + DECISIONS_MD,
        "position": ("research/" + POSITION_MD) if ledger.path(POSITION_MD).is_file() else None,
        "tier": tier,
        "ask": asked,
        "decider": decider_share(records) if autonomy == AUTONOMOUS else [],
        "waiting": [dict(record, needs=missing(record, records, questions)) for record in _waiting(records)],
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
        lines.append("autonomy is autonomous: the decider resolves these %d open question%s (wayline grill --decide-rest), "
                     "and never a human-only or irreversible one"
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
    parser.add_argument("--decide-rest", action="store_true",
                        help="under autonomy autonomous, launch the decider on every open question that is not human-only or "
                             "irreversible, one session each, until the frontier holds only the owner's (ticket 31)")
    parser.add_argument("--json", action="store_true", help="print the tier as JSON")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if options.batch:
            apply_batch(project, _load_json(options.batch))
        if options.decide_rest:
            from wayline import decider  # the launcher and the decisions module, which the grill alone never needs
            report = decider.decide_rest(project)
            print(decider.render_decided(report))
            print("")
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
