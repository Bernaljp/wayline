"""Critiques and concerns (Implementation Decision 17; ticket 96).

A **critique** is a document that judges the work from outside: a referee report, an editor's letter with points,
a collaborator's list of required experiments, sorted so by ticket 84. Its points become **concerns**: points the
work must answer, or decline with a reason.

**The record.** `research/concerns.json` (schema `concern`), written only by this module through the ledger,
rendered as `research/CONCERNS.md`, and journaled as `concern` with every change. Ids run K1 onward and are never
reused. Each concern records its sources (the critique, the locator, the verbatim text), the inherited claims it
targets, its place (tied to objectives, kept for the paper order, or declined) and its status (`open`,
`answered`, or `declined`) with the answer or the reason.

**Where concerns come from.**

- One Sonnet session at medium per batch of critiques splits them (`split_critiques`, role `critique-splitter`).
  Code checks every span is verbatim in its critique and locates it, keeps only targets among the inherited
  claims, and merges near-identical points from different critiques with every source.
- An open Word comment thread in a document's `comments.json` becomes a concern by code (`from_comments`); a
  resolved one does not.
- An objection of the position memo's hostile review that the owner accepts at the grill becomes a concern with
  the memo as its source (`from_objection`).

**Sorting.** At setup the critic's memo proposes a place for each unsorted concern (`propose`): an objective row,
"for the order", or a decline. The proposals form one `concern_placements` batch of ticket 79, and the grill puts
them to the owner in groups: one question per proposed objective, one for the order, one for the declines.
Specify drafts only once every concern is sorted (`unsorted`). After setup, a concern that needs sorting is a
decision ticket of class `concern` (`settle`): the owner's, or under `autonomous` the decider's unless the owner
named `concern` human-only.

**Following the objectives** (`follow`). Code answers a concern when every objective tied to it is answered and
every inherited claim it targets is replaced or withdrawn. A concern follows a reframe to the successor, and goes
back to be sorted when its objective drops.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, load_schema, validate
from wayline.ledger import CONCERN, K_BY, K_ID, K_OBJECTIVES, K_PLACE, K_STATUS, PAYLOAD_ENUMS, LedgerError, ledger_for
from wayline.project import ProjectError, find_project

__all__ = [
    "CONCERNS_JSON", "CONCERNS_MD", "SCHEMA", "MEMO", "ConcernError", "ConcernsUnreadable", "read_concerns", "read_record",
    "render_concerns", "from_comments", "is_sorted", "unsorted",
]

CONCERNS_JSON = "concerns.json"
CONCERNS_MD = "CONCERNS.md"
SCHEMA = "concern"
MEMO = "POSITION.md"            # the source of an objection of the hostile review the owner accepted
STATUSES = PAYLOAD_ENUMS[(CONCERN, K_STATUS)]
PLACES = PAYLOAD_ENUMS[(CONCERN, K_PLACE)]
OPEN, ANSWERED, DECLINED = "open", "answered", "declined"
OBJECTIVES, ORDER = "objectives", "order"
SPLITTER = "critique-splitter"   # the role one session per batch of critiques runs on (Sonnet at medium)
SPLIT_SCHEMA = "concern_split"
NEAR = 0.8                      # how alike two points' words are, as difflib reads them, for code to merge them
SPLIT_ROOM = 20000              # what a splitter prompt keeps under the context cap for the claims, the rules, and the schema
SPLIT_MIN = 20000               # the least critique text one splitter session takes, however small the cap

_ID = re.compile(r"^K([1-9][0-9]*)\Z")


class ConcernError(ValueError):
    """A change to the concerns this module refuses: an unknown concern, a place that names nothing, a decline with no reason."""


class ConcernsUnreadable(ValueError):
    """`research/concerns.json` is there and is not the record code writes."""


# --- the record ---------------------------------------------------------------------------------------------


def _empty():
    return {"concerns": [], "split": []}


def read_record(project_or_ledger):
    """The whole record, `{concerns, split}`; empty when the project has none yet. Raises `ConcernsUnreadable`."""
    ledger = ledger_for(project_or_ledger)
    if not ledger.path(CONCERNS_JSON).is_file():
        return _empty()
    try:
        record = ledger.read_json(CONCERNS_JSON)
    except (OSError, ValueError) as failure:
        raise ConcernsUnreadable("research/%s cannot be read: %s" % (CONCERNS_JSON, failure)) from None
    problems = validate(record, load_schema(SCHEMA))
    if problems:
        raise ConcernsUnreadable("research/%s cannot be read: %s" % (
            CONCERNS_JSON, "; ".join("%s: %s" % (error.path, error.message) for error in problems[:3])))
    return record


def read_concerns(project_or_ledger):
    """The concerns of `research/concerns.json` in id order; empty when the project has none yet."""
    return list(read_record(project_or_ledger)["concerns"])


def _number(identifier):
    found = _ID.match(str(identifier))
    return int(found.group(1)) if found else 0


def _next_id(record):
    return "K%d" % (max((_number(item.get("id")) for item in record["concerns"]), default=0) + 1)


def _blank(identifier, sources, targets=()):
    return {"id": identifier, "sources": list(sources), "targets": list(targets), "place": None, "objectives": [],
            "status": OPEN, "answer": None, "reason": None, "proposed": None, "returned": None, "sorted_by": None}


def is_sorted(concern):
    """Whether a concern has its place: tied to objectives, kept for the order, or declined."""
    return (concern or {}).get("place") is not None


def unsorted(project_or_ledger):
    """The open concerns that wait to be sorted, in id order."""
    return [item for item in read_concerns(project_or_ledger) if item["status"] == OPEN and not is_sorted(item)]


def _save(ledger, record, changed, by):
    """Write the record, journal one `concern` per changed concern, and render CONCERNS.md; the caller holds the lock."""
    ledger.write_json(CONCERNS_JSON, record, schema=SCHEMA)
    for concern in changed:
        ledger.append_event(CONCERN, {K_ID: concern["id"], K_STATUS: concern["status"], K_PLACE: concern["place"],
                                      K_OBJECTIVES: list(concern["objectives"]), K_BY: by})
    ledger.write_markdown(CONCERNS_MD, render_concerns(record["concerns"]))


def _one_line(text):
    return " ".join(str(text or "").split())


def _known(record):
    """Every source the record holds, as `(critique, locator, text)` with the text on one line, so a source is taken once."""
    return {(source["critique"], source["locator"], _one_line(source["text"])) for item in record["concerns"]
            for source in item["sources"]}


# --- what a concern targets ----------------------------------------------------------------------------------


def inherited_claims(project_or_ledger):
    """The inherited claims standing in the sections now: `{passage id: passage}`, the ones a concern may target."""
    from wayline import sections  # the sections module reads the passages; loaded when a concern is placed

    book = ledger_for(project_or_ledger)
    claims = {}
    for section in sections.INHERITED:
        standing = sections.current_ids(book, section)
        for item in sections.section_items(book, section):
            if item.get("id") in standing and sections.is_inherited(item) and item.get("standing") in sections.STANDINGS:
                claims[item["id"]] = item
    return claims


def _plain(text):
    from wayline import provenance  # the tags a passage carries are not its words
    return _one_line(provenance.strip_tags(str(text or "")))


def _anchored_claims(claims, document_id, block, anchor):
    """The inherited claims of `document_id` in its block `block` whose words the comment's anchor holds, or that hold it."""
    anchor = _one_line(anchor).casefold()
    found = []
    for identifier, item in claims.items():
        doc = str(item.get("doc") or "")
        if not doc.startswith("%s#%s." % (document_id, block)) and doc != "%s#%s" % (document_id, block):
            continue
        words = _plain(item.get("text")).casefold()
        if anchor and words and (anchor in words or words in anchor):
            found.append(identifier)
    return sorted(found, key=lambda identifier: int(identifier[1:]))


# --- from a Word comment thread ---------------------------------------------------------------------------------


def _threads(ledger, document):
    """The open comment threads of one document: `(locator, text, block, anchor)` each, in the order `comments.json` keeps."""
    path = ledger.path("documents/%s/comments.json" % document["id"])
    if not path.is_file():
        return []
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = []
    for thread in held.get("threads") or []:
        if not isinstance(thread, dict) or thread.get("done") or not thread.get("comments"):
            continue
        root = thread["comments"][0]
        text = _one_line(root.get("text") if isinstance(root, dict) else None)
        if not text:
            continue
        anchor = thread.get("anchor") if isinstance(thread.get("anchor"), dict) else {}
        block = anchor.get("block")
        locator = "%s#%s" % (document["id"], block) if block else document["id"]
        found.append((locator, text, block, anchor.get("text")))
    return found


def from_comments(project):
    """Every open Word comment thread no concern holds yet becomes one, by code; returns the concerns added.

    A thread is a concern in its root comment's words, located at the block its anchor is in, and it targets the
    inherited claims of that block its anchor covers. A resolved thread (`done`) is none.
    """
    from wayline.documents import read_documents  # the documents module imports the tools record

    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        known = _known(record)
        claims = None
        added = []
        for document in read_documents(ledger.project):
            for locator, text, block, anchor in _threads(ledger, document):
                if (document["id"], locator, text) in known:
                    continue
                if claims is None:
                    claims = inherited_claims(ledger)
                targets = _anchored_claims(claims, document["id"], block, anchor) if block else []
                concern = _blank(_next_id(record), [{"critique": document["id"], "locator": locator, "text": text}], targets)
                record["concerns"].append(concern)
                known.add((document["id"], locator, text))
                added.append(concern)
        if added:
            _save(ledger, record, added, "code")
    return added


# --- the critique splitter ---------------------------------------------------------------------------------------


def _verbatim(text):
    """Text as a verbatim check compares it: whitespace run together, curly quotes and dashes as their plain forms."""
    return _one_line(str(text or "").translate(_PLAIN))


_PLAIN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def _near(one, other):
    """Whether two points say the same thing in nearly the same words: what code merges across critiques."""
    first, second = _verbatim(one).casefold().rstrip("."), _verbatim(other).casefold().rstrip(".")
    return difflib.SequenceMatcher(None, first, second).ratio() >= NEAR


def _critiques(ledger, record):
    """The critiques not split yet, each `(document, blocks)`: every converted critique whose current version `split` lacks."""
    from wayline.documents import read_documents, text_blocks  # the documents module imports the tools record

    done = {(entry["document"], entry["version"]) for entry in record["split"]}
    found = []
    for document in read_documents(ledger.project):
        if document.get("kind") != "critique" or (document["id"], document["version"]) in done or not document.get("converted"):
            continue
        path = ledger.path("documents/%s/text.md" % document["id"])
        if not path.is_file():
            continue
        found.append((document, text_blocks(path.read_text(encoding="utf-8"))))
    return found


def _locate(blocks, document_id, text):
    """The locator of `text` in a critique, `D2#p3` for the block that holds it, or None when it is not there verbatim."""
    wanted = _verbatim(text)
    if not wanted:
        return None
    for locator, block in blocks:
        if wanted in _verbatim(block):
            return "%s#%s" % (document_id, locator)
    if wanted in _verbatim(" ".join(block for _, block in blocks)):
        return document_id  # across two blocks: the critique itself
    return None


def splitter_prompt(batch, claims):
    """The splitter's prompt: what it does, each critique whole, the inherited claims it may target, the schema."""
    from wayline import worker  # the launcher, loaded when a batch is split

    parts = ["# What you are asked for", "",
             "Split these critiques into the points the work must answer, as the schema asks. Copy each point verbatim: "
             "one span of the critique's own words per source, never reworded, since code keeps a source only when its "
             "words are in that critique. Leave out praise and summary. An item that makes two points is two concerns, "
             "each with its own span. The same point in two critiques is one concern with a source from each. Name as "
             "targets only the inherited claims below that a point is about.", ""]
    for document, blocks in batch:
        parts += ["# %s: %s" % (document["id"], _one_line(document.get("title")) or document["id"]), "",
                  "From `research/documents/%s/text.md`; cite it as `%s`." % (document["id"], document["id"]), "", "```"]
        parts += [block for _, block in blocks]
        parts += ["```", ""]
    parts += ["# The inherited claims a point may target", "",
              "The sentences of the project's earlier writing that this project has not checked yet, by passage id:", ""]
    if claims:
        parts += ["- %s: %s" % (identifier, _plain(item.get("text"))) for identifier, item in claims.items()]
    else:
        parts.append("None: the project holds no inherited claim, so every point's `targets` is empty.")
    parts += ["", worker.schema_section("# What you return", SPLIT_SCHEMA)]
    return "\n".join(parts) + "\n"


def _splitter_cap(policy):
    """The characters of critique one splitter session takes: its model's context cap less the room the rest of the prompt needs."""
    model = ((policy.get("roles") or {}).get(SPLITTER) or {}).get("model")
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    cap = caps.get(model, min(caps.values()) if caps else None)
    return None if cap is None else max(SPLIT_MIN, int(cap) - SPLIT_ROOM)


def _batches(found, cap):
    """The critiques in batches, each whole and in order, a batch's text under `cap` unless one critique alone is longer."""
    batches, current, used = [], [], 0
    for document, blocks in found:
        size = sum(len(block) for _, block in blocks)
        if current and cap is not None and used + size > cap:
            batches.append(current)
            current, used = [], 0
        current.append((document, blocks))
        used += size
    if current:
        batches.append(current)
    return batches


def _launch_splitter(project, prompt, policy, harness_root):
    """One splitter session, its answer checked against the schema and asked for once more; returns the answer."""
    from wayline import HARNESS_ROOT, provenance, worker

    role = worker.read_role(SPLITTER, harness_root or HARNESS_ROOT, project)
    try:
        request = provenance.structured_request(project, role, policy, harness_root or HARNESS_ROOT, prompt, SPLIT_SCHEMA, "small",
                                                provenance.session_dir(project, SPLITTER))
        envelope = provenance._launch_structured(request, lambda answer: provenance.schema_problem(answer, SPLIT_SCHEMA),
                                                 "critique splitter")
    except provenance.UsageLimited:
        raise
    except provenance.ProvenanceError as failure:
        raise ConcernError(str(failure)) from None
    return envelope.structured_output


def _checked(answer, batch, claims):
    """The splitter's points as `(sources, targets)` code keeps, and a line for everything it dropped."""
    texts = {document["id"]: blocks for document, blocks in batch}
    kept, dropped = [], []
    for number, point in enumerate(answer.get("concerns") or [], start=1):
        sources = []
        for source in point.get("sources") or []:
            critique, text = source.get("critique"), _one_line(source.get("text"))
            locator = _locate(texts[critique], critique, text) if critique in texts else None
            if locator is None:
                dropped.append("point %d: \"%s\" is not verbatim in %s, so it was left out" % (number, text, critique))
                continue
            if all((critique, text) != (other["critique"], other["text"]) for other in sources):
                sources.append({"critique": critique, "locator": locator, "text": text})
        if not sources:
            continue
        targets = []
        for target in point.get("targets") or []:
            if target in claims:
                if target not in targets:
                    targets.append(target)
            else:
                dropped.append("point %d: %s is no inherited claim standing now, so it is no target" % (number, target))
        kept.append((sources, targets))
    return kept, dropped


def _merge_into(concern, sources, targets):
    """Add the sources and targets a concern lacks; returns whether it changed."""
    changed = False
    held = {(source["critique"], source["locator"], _one_line(source["text"])) for source in concern["sources"]}
    for source in sources:
        if (source["critique"], source["locator"], source["text"]) not in held:
            concern["sources"].append(source)
            changed = True
    for target in targets:
        if target not in concern["targets"]:
            concern["targets"].append(target)
            changed = True
    return changed


def _match(record, sources):
    """The recorded concern a point joins: one of another critique whose words are nearly the same, or None."""
    critiques = {source["critique"] for source in sources}
    for concern in record["concerns"]:
        if critiques & {source["critique"] for source in concern["sources"]}:
            continue
        if any(_near(source["text"], held["text"]) for source in sources for held in concern["sources"]):
            return concern
    return None


def split_critiques(project, *, policy=None, harness_root=None):
    """Split every critique not split yet, one splitter session per batch; returns `{added, joined, dropped, critiques}`.

    Nothing is launched when every critique was split at its current version. The critiques go in one batch, or in
    several when together they pass the splitter's context cap, each critique whole. A point code keeps becomes a
    concern by `session`, or joins the recorded concern of another critique it nearly repeats, which gains the source.
    Each batch is recorded as it comes back, so a later one that fails leaves the earlier ones split.
    """
    from wayline import HARNESS_ROOT
    from wayline.project import policy_for

    ledger = ledger_for(project)
    found = _critiques(ledger, read_record(ledger))
    report = {"added": [], "joined": [], "dropped": [], "critiques": [document["id"] for document, _ in found]}
    if not found:
        return report
    policy = policy_for(ledger.project, harness_root or HARNESS_ROOT) if policy is None else policy
    claims = inherited_claims(ledger)
    for batch in _batches(found, _splitter_cap(policy)):
        answer = _launch_splitter(ledger.project, splitter_prompt(batch, claims), policy, harness_root)
        kept, dropped = _checked(answer, batch, claims)
        report["dropped"] += dropped
        _take_batch(ledger, batch, kept, report)
    return report


def _take_batch(ledger, batch, kept, report):
    """Record one batch's points as concerns, or join them to the concerns they nearly repeat, and mark its critiques split."""
    with ledger.lock():
        record = read_record(ledger)
        changed = []
        for sources, targets in kept:
            known = _known(record)
            sources = [source for source in sources if (source["critique"], source["locator"], source["text"]) not in known]
            if not sources:
                continue
            joined = _match(record, sources)
            if joined is not None:
                if _merge_into(joined, sources, targets) and joined not in changed:
                    changed.append(joined)
                    report["joined"].append(joined["id"])
                continue
            concern = _blank(_next_id(record), sources, targets)
            record["concerns"].append(concern)
            changed.append(concern)
            report["added"].append(concern["id"])
        for document, _ in batch:
            entry = {"document": document["id"], "version": document["version"]}
            if entry not in record["split"]:
                record["split"].append(entry)
        _save(ledger, record, changed, "session")


def gather(project, *, policy=None, harness_root=None):
    """Everything setup turns into concerns before the critic reads them: the open comment threads, then the critiques."""
    from_comments(project)
    return split_critiques(project, policy=policy, harness_root=harness_root)


# --- sorting ------------------------------------------------------------------------------------------------------


_OBJECTIVE_ID = re.compile(r"\bO([1-9][0-9]*)\b")
_LEAD = re.compile(r"^(?:accept(?:ed)?\b[\s:,\-]*)?(?:(?:tie|tied|put|place|keep|send)\s+(?:it|them|this|these)?\s*(?:to|for|in)?\s*)?",
                   re.IGNORECASE)
_NEW = re.compile(r"^(?:a\s+)?new objective\s*[:\-]\s*(\S.*)$", re.IGNORECASE)
_DECLINE = re.compile(r"^declin\w*\b[\s:,\-]*(.*)$", re.IGNORECASE)
_ORDER = re.compile(r"^(?:the\s+)?(?:paper\s+)?order\b|^(?:for\s+)?the\s+(?:paper\s+)?order\b", re.IGNORECASE)
_IDS = re.compile(r"^(O[1-9][0-9]*(?:\s*(?:,|and|&|\+)\s*O[1-9][0-9]*)*)\b")
_PLACEHOLDER = re.compile(r"^<[^<>]*>$")   # an option's "<the reason>" picked as it stands, which says nothing


def parse_place(text):
    """The place an answer, a rationale, or a mark's note names, or None when it names none.

    `("objectives", [ids])` for "tie it to O2" or "O1 and O3"; `("order", None)` for "for the order"; `("declined",
    reason)` for "decline: <reason>" (the reason None when it gives none); `("new", question)` for "new objective:
    <question>". An "accept:" in front, as an objection's answer carries, is read past.
    """
    said = _one_line(text)
    rest = _LEAD.sub("", said, count=1).strip()
    for candidate in (rest, said):
        found = _NEW.match(candidate)
        if found:
            question = found.group(1).strip()
            return None if _PLACEHOLDER.match(question) else ("new", question)
        found = _DECLINE.match(candidate)
        if found:
            reason = found.group(1).strip().rstrip(".")
            return (DECLINED, None if not reason or _PLACEHOLDER.match(reason) else reason)
        if _ORDER.match(candidate):
            return (ORDER, None)
        found = _IDS.match(candidate)
        if found:
            return (OBJECTIVES, list(dict.fromkeys("O%s" % number for number in _OBJECTIVE_ID.findall(found.group(1)))))
    return None  # a place is said first: "Not O2; keep it for the order" names none, rather than the O2 it excludes


def _proposed_place(proposed):
    """A proposal as the place `parse_place` reads: what "take it" applies."""
    if proposed["place"] == "objective":
        return (OBJECTIVES, [proposed["objective"]])
    if proposed["place"] == ORDER:
        return (ORDER, None)
    return (DECLINED, proposed["reason"])


def _find(record, identifier):
    for concern in record["concerns"]:
        if concern["id"] == identifier:
            return concern
    known = ", ".join(concern["id"] for concern in record["concerns"]) or "none yet"
    raise ConcernError("no concern %s (the concerns are %s)" % (identifier, known))


def _check_objectives(project, identifiers):
    """Why an objective a concern is tied to cannot take it, or None: each must be one the project holds, open or parked."""
    from wayline.objectives import ObjectivesUnreadable, read_objectives  # the objectives module imports the gates

    try:
        held = {objective["id"]: objective for objective in read_objectives(project)}
    except ObjectivesUnreadable as failure:
        return str(failure)
    for identifier in identifiers:
        found = held.get(identifier)
        if found is None:
            return "%s is no objective the project holds" % identifier
        if found.get("status") not in ("open", "parked"):
            return "%s is %s; a concern is tied only to an open or parked objective" % (identifier, found.get("status"))
    return None


def _apply(concern, place, value, by):
    """Put one concern in its place: tied to objectives, for the order, declined with a reason, or back to be sorted."""
    concern.update(returned=None, answer=None, sorted_by=by if place is not None else None)
    if place == OBJECTIVES:
        concern.update(place=OBJECTIVES, objectives=list(dict.fromkeys(value)), status=OPEN, reason=None)
    elif place == ORDER:
        concern.update(place=ORDER, objectives=[], status=OPEN, reason=None)
    elif place == DECLINED:
        concern.update(place=DECLINED, objectives=[], status=DECLINED, reason=_one_line(value))
    else:
        concern.update(place=None, objectives=[], status=OPEN, reason=None)


def check_place(project, parsed, reason=None):
    """Why a parsed place cannot be taken, or None, with nothing written: a decline with no reason (in `parsed`, else
    `reason`), a tie to an objective the project does not hold open or parked, a new objective with no question."""
    if parsed is None:
        return None
    where, value = parsed
    if where == "new" and not _one_line(value):
        return "a new objective is a question, and none was given"
    if where == DECLINED and not (value or _one_line(reason)):
        return "a concern is declined with a reason, and none was given"
    if where == OBJECTIVES:
        return _check_objectives(project, value)
    return None


def _resolved(project, parsed, reason, by):
    """`(place, value)` for a checked place, a new objective recorded here; a decline takes `reason` when it gave none."""
    where, value = parsed
    if where == "new":
        from wayline.objectives import ObjectiveError, add_objective  # the objectives module imports the gates
        try:
            objective, _ = add_objective(project, value, by=by)
        except ObjectiveError as failure:
            raise ConcernError("the new objective could not be recorded: %s" % failure) from None
        return OBJECTIVES, [objective["id"]]
    if where == DECLINED:
        return where, value or _one_line(reason)
    return where, value


def place_each(project, placements, by, only_unsorted=False):
    """Sort several concerns at once, each `(id, parsed, reason)` in its own place; returns the concerns changed.

    `parsed` is what `parse_place` returns, or None to send the concern back to be sorted. Every concern and every place
    is checked before anything is written, so a refused one sorts none, and a new objective is recorded only once all
    pass, once for the concerns that share it, `by` the same hand. An answered concern is left as it is, and so, with
    `only_unsorted`, is a sorted one.
    """
    if by not in ("owner", "decider"):
        raise ConcernError("a concern is sorted by the owner or the decider, got %r" % (by,))
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        todo = []
        for identifier, parsed, reason in placements:
            concern = _find(record, identifier)
            if concern["status"] == ANSWERED or (only_unsorted and is_sorted(concern)):
                continue
            problem = check_place(ledger.project, parsed, reason)
            if problem is not None:
                raise ConcernError("%s: %s" % (identifier, problem))
            todo.append((concern, parsed, reason))
        resolved, changed = {}, []
        for concern, parsed, reason in todo:
            key = json.dumps([parsed, reason if parsed and parsed[0] == DECLINED else None])
            if key not in resolved:
                resolved[key] = _resolved(ledger.project, parsed, reason, by) if parsed is not None else (None, None)
            before = dict(concern)
            _apply(concern, resolved[key][0], resolved[key][1], by)
            if concern != before:
                changed.append(concern)
        if changed:
            _save(ledger, record, changed, by)
    return changed


def place(project, identifiers, parsed, by, reason=None, only_unsorted=False):
    """Sort concerns into one place: `place_each` with the same place for each. Returns the concerns changed."""
    return place_each(project, [(identifier, parsed, reason) for identifier in identifiers], by, only_unsorted=only_unsorted)


def propose(project, rows):
    """The critic's memo's proposed place for each concern, kept on it (`by: critic`), and one `concern_placements` batch.

    The batch holds one item per concern given a proposal and still unsorted, `take it` its default; a batch for the
    same concerns open already is not opened again. Returns the batch, or None when nothing was proposed.
    """
    from wayline import batches

    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        changed = []
        for row in rows or ():
            concern = _find(record, row["id"])
            proposed = {"place": row["place"], "objective": row.get("objective") if row["place"] == "objective" else None,
                        "reason": _one_line(row["reason"])}
            if concern.get("proposed") != proposed:
                concern["proposed"] = proposed
                changed.append(concern)
        if changed:
            _save(ledger, record, changed, "critic")
        items = [{"ref": concern["id"], "text": _item_text(concern), "default": TAKE_IT}
                 for concern in record["concerns"] if concern.get("proposed") and concern["status"] == OPEN and not is_sorted(concern)]
        if not items:
            return None
        wanted = [item["ref"] for item in items]
        for batch in batches.read_batches(ledger, status=batches.OPEN):
            if batch["kind"] == PLACEMENTS and [item["ref"] for item in batch["items"]] == wanted:
                return batch
        return batches.open_batch(ledger, PLACEMENTS, "Where each concern goes, as the critic proposes", items)


TAKE_IT, ANOTHER_PLACE = "take it", "another place"
PLACEMENTS = "concern_placements"


def _item_text(concern):
    sources = "; ".join("%s: \"%s\"" % (source["locator"], _one_line(source["text"])) for source in concern["sources"])
    return "%s (%s). The critic proposes %s." % (concern["id"], sources, _proposal_line(concern["proposed"]))


def take_marks(project):
    """The marks given in the `concern_placements` batches, applied to the concerns they name that are still unsorted.

    `take it` takes the critic's proposal; `another place` takes the place the item's note names, and with none leaves
    the concern to be sorted. Returns the concerns changed.
    """
    from wayline import batches

    changed = []
    for batch in batches.read_batches(project):
        if batch["kind"] != PLACEMENTS:
            continue
        for item in batch["items"]:
            if item["mark"] is None:
                continue
            record = read_record(project)
            try:
                concern = _find(record, item["ref"])
            except ConcernError:
                continue
            if concern["status"] != OPEN or is_sorted(concern):
                continue
            parsed = _proposed_place(concern["proposed"]) if item["mark"] == TAKE_IT and concern.get("proposed") else \
                parse_place(item["note"]) if item["mark"] == ANOTHER_PLACE else None
            if parsed is None:
                continue
            try:
                changed += place(project, [concern["id"]], parsed, item["by"] or "owner", only_unsorted=True)
            except ConcernError:
                continue
    return changed


def mark_items(project, identifiers, given, by, note=None):
    """Settle the open `concern_placements` items of `identifiers` with `given`, keeping the batch in step with the grill."""
    from wayline import batches

    for batch in batches.read_batches(project, status=batches.OPEN):
        if batch["kind"] != PLACEMENTS:
            continue
        for item in batch["items"]:
            if item["ref"] in identifiers and item["mark"] is None:
                try:
                    batches.mark(project, batch["id"], item["id"], given, note=note, by=by)
                except batches.BatchError:
                    continue


# --- following the objectives and the targets ------------------------------------------------------------------


def _successors(book):
    """`(replaced, moved)`: every later passage or finding by the id it replaces, and the moved passage by where it came from."""
    from wayline import sections  # the sections module reads the passages

    replaced, moved = {}, {}
    for item in list(sections.read_passages(book)) + list(sections.read_findings(book)):
        if item.get("replaces"):
            replaced.setdefault(item["replaces"], []).append(item)
        if item.get("moved_from"):
            moved[item["moved_from"]] = item
    return replaced, moved


def _follow_target(identifier, replaced, moved):
    """`(id, done)`: an inherited claim followed through its document's own rewrites and moves to the passage that holds it
    now, and whether the work replaced it or it was withdrawn."""
    from wayline import sections  # the sections module reads the passages

    seen = set()
    while identifier not in seen:
        seen.add(identifier)
        if identifier in moved:
            identifier = moved[identifier]["id"]
            continue
        later = replaced.get(identifier) or []
        if not later:
            return identifier, False
        rewritten = [item for item in later if sections.is_inherited(item) and not item.get("withdrawn")]
        if len(rewritten) == len(later):
            identifier = rewritten[-1]["id"]  # the document said it again, newer or marked unverifiable: the claim stands
            continue
        return identifier, True
    return identifier, False


def _follow_objectives(identifiers, held):
    """`(kept, dropped)`: each objective followed through its reframes to the one that asks it now, the dropped ones apart."""
    kept, dropped = [], []
    for identifier in identifiers:
        current, seen = identifier, set()
        while current in held and held[current].get("status") == "reframed" and held[current].get("reframed_as") and current not in seen:
            seen.add(current)
            current = held[current]["reframed_as"]
        if (held.get(current) or {}).get("status") == "dropped":
            dropped.append(current)
        elif current not in kept:
            kept.append(current)
    return kept, dropped


def _answer_of(objectives, held, targets):
    said = "; ".join("%s: %s" % (identifier, _one_line((held.get(identifier) or {}).get("answer")) or "answered")
                     for identifier in objectives)
    if targets:
        said += "; %s %s replaced or withdrawn" % (", ".join(targets), "is" if len(targets) == 1 else "are")
    return said


def follow(project):
    """Code's part, after any change to the objectives or the passages: returns the concerns it changed, journaled `by: code`.

    An open concern's targets follow their document's own rewrites and moves. A concern tied to objectives follows each
    reframe to the successor; one whose objectives all dropped goes back to be sorted, with why. A concern whose tied
    objectives are all answered and whose targets the work replaced or withdrew is answered, with what answered it.
    """
    from wayline.objectives import ObjectivesUnreadable, read_objectives  # the objectives module imports the gates

    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        if not any(concern["status"] == OPEN for concern in record["concerns"]):
            return []
        try:
            held = {objective["id"]: objective for objective in read_objectives(ledger.project)}
        except ObjectivesUnreadable as failure:
            raise ConcernError(str(failure)) from None
        replaced, moved = _successors(ledger)
        changed = []
        for concern in record["concerns"]:
            if concern["status"] != OPEN:
                continue
            before = json.dumps(concern, sort_keys=True)
            followed = [_follow_target(identifier, replaced, moved) for identifier in concern["targets"]]
            concern["targets"] = list(dict.fromkeys(identifier for identifier, _ in followed))
            if concern["place"] == OBJECTIVES:
                kept, dropped = _follow_objectives(concern["objectives"], held)
                if not kept:
                    _apply(concern, None, None, None)
                    concern["returned"] = "%s was dropped" % " and ".join(dropped) if dropped else "its objectives are gone"
                else:
                    concern["objectives"] = kept
                    if all((held.get(identifier) or {}).get("status") == ANSWERED for identifier in kept) \
                            and all(done for _, done in followed):
                        concern.update(status=ANSWERED, answer=_answer_of(kept, held, concern["targets"]))
            if json.dumps(concern, sort_keys=True) != before:
                changed.append(concern)
        if changed:
            _save(ledger, record, changed, "code")
    return changed


# --- after setup: a decision ticket per concern to sort ----------------------------------------------------------


CLASS = "concern"                       # the decision class of sorting a concern, which the owner may name human-only
ORIGIN = "concern %s #%d"               # the origin of the n-th decision ticket asking where a concern goes
_ORIGIN = re.compile(r"^concern (K[1-9][0-9]*) #([1-9][0-9]*)\Z")


def concern_of(origin):
    """The concern a decision ticket's origin asks about, or None for a ticket of another kind."""
    found = _ORIGIN.match(str(origin or ""))
    return found.group(1) if found else None


def decider_refusal(answer, harness):
    """Why the decider may not give `answer` to a concern's decision ticket, or None: it names a place, and a new objective
    only when the owner took `objective` off the human-only classes."""
    from wayline.project import DEFAULT_HUMAN_ONLY, OBJECTIVE_CLASS, human_only_classes_now

    parsed = parse_place(answer)
    if parsed is None:
        return "its answer names no place for the concern (tie it to an objective, for the order, or decline with a reason): %s" % answer
    classes = human_only_classes_now(dict(harness or {}, human_only=(harness or {}).get("human_only") or list(DEFAULT_HUMAN_ONLY)))
    if parsed[0] == "new" and OBJECTIVE_CLASS in classes:
        return "a new objective is the owner's while `objective` is a human-only class, and its answer adds one: %s" % answer
    return None


def _question(concern):
    said = "; ".join("%s: \"%s\"" % (source["locator"], _one_line(source["text"])) for source in concern["sources"])
    return ("Where does concern %s go: tied to an objective, kept for the paper order, or declined with a reason? It says %s."
            % (concern["id"], said))


def _ticket_fields(concern, objectives, why=None):
    """The question, options, recommendation, and evidence of the decision ticket asking where `concern` goes."""
    options = ["tie it to %s" % objective["id"] for objective in objectives if objective.get("status") in ("open", "parked")]
    options += ["for the order", "decline: <the reason>", "new objective: <the question>"]
    proposed = concern.get("proposed")
    recommended = None
    if proposed:
        recommended = {"objective": "tie it to %s" % proposed["objective"], ORDER: "for the order"}.get(
            proposed["place"], "decline: %s" % _one_line(proposed["reason"]))
    evidence = ["targets: %s" % (", ".join(concern["targets"]) or "no inherited claim")]
    if proposed:
        evidence.append("the critic proposed %s" % _proposal_line(proposed))
    if concern.get("returned"):
        evidence.append("back to be sorted: %s" % concern["returned"])
    if why:
        evidence.append(why)
    return _question(concern), options, recommended, evidence


def _askings(events):
    """`(returns, created, answered)` read from the journal: when each concern last came to need sorting (its first record
    or a return to sorting), when each concern's decision ticket was opened, and the last answer to each ticket."""
    from wayline.ledger import DECISION, TICKET_CREATED, TICKET_RERUN

    returns, places, created, answered = {}, {}, {}, {}
    for index, event in enumerate(events):
        name, payload = event.get("event"), event.get("payload") or {}
        if name == CONCERN:
            identifier = payload.get("id")
            if payload.get("place") is None and (identifier not in places or places[identifier] is not None):
                returns[identifier] = index
            places[identifier] = payload.get("place")
        elif name == TICKET_CREATED and concern_of(payload.get("origin")):
            created[payload.get("ticket")] = (index, payload.get("origin"))
        elif name == DECISION and payload.get("ticket") is not None:
            answered[payload["ticket"]] = (index, payload)
        elif name == TICKET_RERUN and payload.get("ticket") in answered:
            answered.pop(payload["ticket"])  # asked again: the answer it had stopped being its answer
    return returns, created, answered


def _worded(project, ticket, answer):
    """An answer that only points at an option ("option 2", "the second") as that option's words; any other as given."""
    from wayline import decider, decisions, tickets  # the decider reads an indexical answer the same way

    try:
        fields = {item["id"]: item for item in tickets.read_tickets(project)}.get(ticket)
        record = decisions.decision_record(tickets.read_ticket(tickets.tickets_dir(project) / tickets.filename(fields))[1]) if fields else None
    except (ValueError, OSError):
        record = None
    return decider.chosen_option(answer, (record or {}).get("options") or [])


def settle(project, notify=None, say=None):
    """The conductor's concerns step of one wave: marks taken, objectives followed, and, past setup, a decision per concern
    to sort. Returns `{opened, applied, waiting}`.

    Past setup, each open concern that waits to be sorted is asked about in one decision ticket of class `concern`
    (`blocking` null: sorting pauses no work), the owner's, or under `autonomous` the decider's unless `concern` is
    human-only. Its answer places the concern, `by` the owner or the decider; an answer that names no place asks again,
    with why. A concern that comes back to be sorted (its objective dropped) is asked about anew, and the answer to the
    earlier asking is not taken again. Everything is read back from the journal and the files, so a second call, or a
    restarted conductor, asks nothing twice.
    """
    from wayline import decisions, stopping, tickets
    from wayline.objectives import ObjectivesUnreadable, read_objectives
    from wayline.project import read_harness

    say = say or (lambda line: None)
    report = {"opened": [], "applied": [], "waiting": []}
    take_marks(project)
    follow(project)
    ledger = ledger_for(project)
    events, _ = ledger.read_events()
    if not stopping.after_setup(events):
        return report
    waiting = unsorted(ledger)
    if not waiting:
        return report
    try:
        held = read_objectives(ledger.project)
    except ObjectivesUnreadable as failure:
        raise ConcernError(str(failure)) from None
    returns, created, answered = _askings(events)
    statuses = {fields["id"]: fields["status"] for fields in tickets.read_tickets(ledger.project) if concern_of(fields.get("origin"))}
    for concern in waiting:
        identifier = concern["id"]
        mine = sorted((index, origin, ticket) for ticket, (index, origin) in created.items() if concern_of(origin) == identifier)
        asked = len(mine)
        current = [(index, ticket) for index, origin, ticket in mine if index > returns.get(identifier, -1)]
        why = None
        if current:
            _, ticket = current[-1]
            given = answered.get(ticket)
            if (given is None or given[0] < current[-1][0]) and statuses.get(ticket, "open") == "open":
                report["waiting"].append(ticket)
                continue
            if given is None or given[0] < current[-1][0]:
                why = "ticket %d was closed with no answer" % ticket
                given = None
        if current and given is not None:
            payload = given[1]
            by = "decider" if payload.get("decided_by") == "decider" else "owner"
            worded = _worded(ledger.project, ticket, payload.get("answer"))
            parsed = parse_place(worded)
            refused = decider_refusal(worded, read_harness(ledger.project)) if by == "decider" and parsed is not None else None
            if refused is not None:
                why = "the decider's answer to ticket %d is not taken: %s" % (ticket, refused)
            elif parsed is not None:
                try:
                    place(ledger.project, [identifier], parsed, by, reason=payload.get("rationale"))
                    report["applied"].append(identifier)
                    say("  concern %s placed by the %s's answer to ticket %d: %s" % (identifier, by, ticket, payload.get("answer")))
                    continue
                except ConcernError as failure:
                    why = "the answer to ticket %d, \"%s\", could not be taken: %s" % (ticket, _one_line(payload.get("answer")), failure)
            else:
                why = "the answer to ticket %d, \"%s\", named no place" % (ticket, _one_line(payload.get("answer")))
        question, options, recommended, evidence = _ticket_fields(concern, held, why)
        opened = decisions.open_decision(ledger.project, question, options=options, recommended=recommended, evidence=evidence,
                                         blocking=None, proposed_by="conductor", origin=ORIGIN % (identifier, asked + 1),
                                         title="Where does concern %s go?" % identifier, notify=notify, decision_class=CLASS)
        if opened["opened"]:
            report["opened"].append(opened["ticket"])
            say("  concern %s waits to be sorted: decision ticket %d" % (identifier, opened["ticket"]))
    return report


# --- the grill's questions --------------------------------------------------------------------------------------


GROUP_ANSWERS = (TAKE_IT, ANOTHER_PLACE)
OBJECTION_LOCATOR = MEMO + "#hostile-review-%d"


def group_questions(items):
    """The grill's questions on the critic's proposals: one per proposed objective with its concerns, one for the order,
    one for the declines, each over the concerns still unsorted with such a proposal, as `{question, concerns, evidence}`."""
    groups = {}
    for concern in sorted(items, key=lambda item: _number(item["id"])):
        proposed = concern.get("proposed")
        if not proposed or concern["status"] != OPEN or is_sorted(concern):
            continue
        key = {"objective": (OBJECTIVES, proposed["objective"]), ORDER: (ORDER, None), "decline": (DECLINED, None)}[proposed["place"]]
        groups.setdefault(key, []).append(concern)

    def order(key):
        return ({OBJECTIVES: 0, ORDER: 1, DECLINED: 2}[key[0]], int(key[1][1:]) if key[1] else 0)

    specs = []
    for key in sorted(groups, key=order):
        members = groups[key]
        ids = [concern["id"] for concern in members]
        named = ", ".join(ids)
        if key[0] == OBJECTIVES:
            question = "Do the concerns %s go to %s, as the critic proposes?" % (named, key[1])
        elif key[0] == ORDER:
            question = "Do the concerns %s wait for the paper order, as the critic proposes?" % named
        else:
            question = "Are the concerns %s declined, for the reasons the critic gives?" % named
        evidence = ["%s: %s; the critic: %s" % (concern["id"], "; ".join("%s \"%s\"" % (source["locator"], _one_line(source["text"]))
                                                                         for source in concern["sources"]),
                                               _one_line(concern["proposed"]["reason"])) for concern in members]
        specs.append({"question": question, "concerns": {"place": key[0], "objective": key[1], "ids": ids}, "evidence": evidence})
    return specs


def _group_placements(project, group, answer, rationale):
    """`[(id, parsed, reason)]` an answer to a grill question on concerns places: a group's `take it` each as proposed,
    its `another place` (or a lone concern's answer) where the words name, or nothing when they name no place."""
    record = read_record(project)
    if group.get("place") is None:  # one concern the groups left: the answer itself names its place
        return [(identifier, parse_place(answer), rationale) for identifier in group["ids"]]
    if answer == TAKE_IT:
        found = [_find(record, identifier) for identifier in group["ids"]]
        return [(concern["id"], _proposed_place(concern["proposed"]), None) for concern in found if concern.get("proposed")]
    parsed = parse_place(rationale)
    return [(identifier, parsed, rationale) for identifier in group["ids"]] if parsed is not None else []


def check_group(project, group, answer, rationale, revise=False):
    """Why an answer to a grill question on concerns cannot be recorded, or None, with nothing written."""
    try:
        placements = _group_placements(project, group, answer, rationale)
        record = read_record(project)
        for identifier, parsed, reason in placements:
            concern = _find(record, identifier)
            if concern["status"] == ANSWERED or (not revise and is_sorted(concern)):
                continue
            if group.get("place") is None and parsed is None:
                return "%s: the answer names no place (tie it to O<n>, for the order, or decline: <the reason>)" % identifier
            problem = check_place(project, parsed, reason)
            if problem is not None:
                return "%s: %s" % (identifier, problem)
    except (ConcernError, ConcernsUnreadable) as failure:
        return str(failure)
    return None


def take_group(project, group, answer, rationale, revise=False):
    """The owner's answer to a grill question on concerns, recorded whole or not at all.

    A group's `take it` places each concern as the critic proposed, its `another place` where the rationale says, or
    with no place named leaves them to be sorted (the grill then asks about each); a lone concern's answer names its
    place. The group's `concern_placements` items are marked alike.
    """
    problem = check_group(project, group, answer, rationale, revise)
    if problem is not None:
        raise ConcernError(problem)
    changed = place_each(project, [entry for entry in _group_placements(project, group, answer, rationale) if entry[1] is not None],
                         "owner", only_unsorted=not revise)
    if group.get("place") is not None:
        mark_items(project, group["ids"], answer, "owner", note=None if answer == TAKE_IT else rationale)
    return changed


def sort_questions(items, objectives=(), records=()):
    """One question for each open concern waiting to be sorted that no open question of the grill covers: those no proposal
    reached, and those a group's `another place` left; as `{question, concerns, options, recommended, evidence}`."""
    covered = {identifier for record in records or () if record.get("concerns") and record.get("answer") is None
               for identifier in record["concerns"]["ids"]}
    asked = {}
    for record in records or ():
        if record.get("concerns") and record["concerns"].get("place") is None:
            for identifier in record["concerns"]["ids"]:
                asked[identifier] = asked.get(identifier, 0) + 1
    ties = ["tie it to %s" % objective["id"] for objective in objectives or () if objective.get("status") in ("open", "parked")]
    specs = []
    for concern in sorted(items, key=lambda item: _number(item["id"])):
        if concern["status"] != OPEN or is_sorted(concern) or concern["id"] in covered:
            continue
        question, _, recommended, evidence = _ticket_fields(concern, objectives)
        if asked.get(concern["id"]):
            question += " (asked again)" if asked[concern["id"]] == 1 else " (asked %d times before)" % asked[concern["id"]]
        specs.append({"question": question, "concerns": {"place": None, "objective": None, "ids": [concern["id"]]},
                      "options": ties + ["for the order", "decline: <the reason>"], "recommended": recommended, "evidence": evidence})
    return specs


def objection_questions(memo, objectives=()):
    """One question per objection of the memo's hostile review: does the work answer it, and where; as `{question, objection, options}`."""
    ties = ["accept: tie it to %s" % objective["id"] for objective in objectives or () if objective.get("status") in ("open", "parked")]
    options = ties + ["accept: for the order", "reject"]
    specs = []
    for index, text in enumerate((memo or {}).get("hostile_review") or (), start=1):
        text = _one_line(text)
        if text:
            specs.append({"question": "Must the work answer objection %d of the hostile review: \"%s\"?" % (index, text),
                          "objection": {"index": index, "text": text}, "options": options})
    return specs


def from_objection(project, objection, answer, rationale=None):
    """An objection of the hostile review the owner accepted at the grill becomes a concern with the memo as its source.

    `answer` is the grill's: `reject` records nothing; an accept is placed where it says ("accept: tie it to O1", "accept:
    for the order"), or left to be sorted when it names no place. Taken once: a second accept of the same objection
    places the concern it made. Returns the concern, or None.
    """
    problem = check_objection(project, answer, rationale)
    if problem is not None:
        raise ConcernError(problem)
    if _one_line(answer).casefold().startswith("reject"):
        return None
    source = {"critique": MEMO, "locator": OBJECTION_LOCATOR % objection["index"], "text": _one_line(objection["text"])}
    ledger = ledger_for(project)
    with ledger.lock():
        record = read_record(ledger)
        concern = next((item for item in record["concerns"]
                        if any((held["critique"], held["locator"]) == (MEMO, source["locator"]) for held in item["sources"])), None)
        if concern is None:
            concern = _blank(_next_id(record), [source])
            record["concerns"].append(concern)
            _save(ledger, record, [concern], "owner")
        parsed = parse_place(answer)
        if parsed is not None:
            place(project, [concern["id"]], parsed, "owner", reason=rationale)
    return _find(read_record(project), concern["id"])


def check_objection(project, answer, rationale=None):
    """Why an answer to an objection's question cannot be recorded, or None, with nothing written: a place it names that
    cannot be taken. An accept that names no place is taken, and the concern it makes is asked about on its own."""
    if _one_line(answer).casefold().startswith("reject"):
        return None
    return check_place(project, parse_place(answer), rationale)


# --- a worker's context pack ------------------------------------------------------------------------------------


def pack_text(project_or_ledger, objectives, max_chars=None):
    """The context pack's part on the concerns: the open concerns tied to one of the ticket's objectives; empty with none.

    `max_chars` is what the tier's context cap leaves this part: what does not fit is cut with the cut announced, as the
    sections' part is, and a part with no room left is only the line that says where the concerns are.
    """
    wanted = set(objectives or ())
    if not wanted:
        return ""
    try:
        found = [concern for concern in read_concerns(project_or_ledger)
                 if concern["status"] == OPEN and concern["place"] == OBJECTIVES and wanted & set(concern["objectives"])]
    except ConcernsUnreadable:
        return ""
    if not found:
        return ""
    lines = ["# The concerns of this ticket's objectives", "",
             "Points the work must answer, raised by critiques of the project's earlier writing (`research/CONCERNS.md`). Your "
             "result answers what it can of them with evidence; a concern is answered once its objectives are answered and the "
             "inherited claims it targets are replaced or withdrawn."]
    for concern in found:
        lines += ["", "## %s, tied to %s" % (concern["id"], ", ".join(concern["objectives"]))]
        lines += ["- %s: \"%s\"" % (source["locator"], _one_line(source["text"])) for source in concern["sources"]]
        if concern["targets"]:
            lines.append("- targets the inherited claims %s" % ", ".join(concern["targets"]))
    text = "\n".join(lines)
    if max_chars is not None and len(text) > max(0, int(max_chars)):
        cut = text[:max(0, int(max_chars))].rsplit("\n", 1)[0]
        text = cut + ("\n\n" if cut else "") + ("[wayline: the concerns of this ticket's objectives reached the context cap; "
                                                "the rest are in research/CONCERNS.md.]")
    return text


# --- the verb ---------------------------------------------------------------------------------------------------


def concern_command(args):
    """`wayline concern split | place <id>... --objective <O>... | --order | --decline "<reason>" | show`."""
    from wayline import gates, worker

    parser = argparse.ArgumentParser(prog="wayline concern", description="the project's concerns: split its critiques and comment "
                                                                         "threads into concerns, place one, or show them")
    subparsers = parser.add_subparsers(dest="action", required=True)
    split = subparsers.add_parser("split", help="turn the open comment threads and the critiques not split yet into concerns")
    split.add_argument("--project", help="the project; the active one by default")
    placing = subparsers.add_parser("place", help="sort concerns as the owner: tie them to objectives, keep them for the order, "
                                                  "or decline them with a reason")
    placing.add_argument("ids", nargs="+", metavar="id", help="the concerns, K1 onward")
    where = placing.add_mutually_exclusive_group(required=True)
    where.add_argument("--objective", action="append", metavar="O", help="an objective to tie them to (repeat for several)")
    where.add_argument("--order", action="store_true", help="keep them for the paper order")
    where.add_argument("--decline", metavar="REASON", help="decline them, with the reason")
    placing.add_argument("--project", help="the project; the active one by default")
    show = subparsers.add_parser("show", help="print CONCERNS.md")
    show.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if options.action == "show":
            print(render_concerns(read_concerns(project)).rstrip("\n"))
            return 0
        if options.action == "split":
            report = gather(project)
            if report["critiques"]:
                print("split %s: %d new concern(s), %d joined" % (", ".join(report["critiques"]), len(report["added"]),
                                                                   len(report["joined"])))
            else:
                print("no critique waits to be split")
            for line in report["dropped"]:
                print("  dropped: %s" % line)
            print("research/%s holds %d concern(s), %d waiting to be sorted" % (CONCERNS_MD, len(read_concerns(project)),
                                                                                 len(unsorted(project))))
            return 0
        parsed = (OBJECTIVES, options.objective) if options.objective else (ORDER, None) if options.order else (DECLINED, options.decline)
        changed = place(project, options.ids, parsed, "owner")
    except ConcernError as failure:
        print("wayline concern: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, ConcernsUnreadable, LedgerError, ValidationError, ValueError, OSError, gates.GateError,
            worker.LaunchError, worker.RoleError) as failure:
        print("wayline concern: %s" % failure, file=sys.stderr)
        return 1
    for concern in changed:
        print("%s  %s" % (concern["id"], _place_line(concern)))
    if not changed:
        print("nothing changed: %s %s placed so already, or answered" % (", ".join(options.ids), "is" if len(options.ids) == 1 else "are"))
    return 0


# --- CONCERNS.md ------------------------------------------------------------------------------------------------


def _place_line(concern):
    if concern["place"] == OBJECTIVES:
        return "tied to %s" % ", ".join(concern["objectives"])
    if concern["place"] == ORDER:
        return "for the paper order"
    if concern["place"] == DECLINED:
        return "declined"
    proposed = concern.get("proposed")
    if proposed:
        return "not sorted yet; the critic proposes %s" % _proposal_line(proposed)
    return "not sorted yet"


def _proposal_line(proposed):
    if proposed["place"] == "objective":
        return "%s (%s)" % (proposed["objective"], _one_line(proposed["reason"]))
    if proposed["place"] == ORDER:
        return "the paper order (%s)" % _one_line(proposed["reason"])
    return "a decline (%s)" % _one_line(proposed["reason"])


def render_concerns(items):
    """CONCERNS.md: every concern in id order with its sources, targets, place, and status."""
    lines = ["# Concerns", "",
             "Rendered by code from `research/concerns.json`. A concern is a point the work must answer: a critique's "
             "point kept verbatim with every critique that raised it, an open Word comment thread, or an objection of the "
             "position memo's hostile review the owner accepted. It stays open until it is answered or declined with a "
             "reason.", ""]
    if not items:
        lines += ["No concern is recorded yet.", ""]
    for concern in sorted(items, key=lambda item: _number(item["id"])):
        lines += ["## %s" % concern["id"], ""]
        lines.append("- Sources:")
        lines += ["  - %s: \"%s\"" % (source["locator"], _one_line(source["text"])) for source in concern["sources"]]
        lines.append("- Targets: %s" % (", ".join(concern["targets"]) or "no inherited claim"))
        lines.append("- Place: %s" % _place_line(concern))
        if concern.get("returned"):
            lines.append("- Back to be sorted: %s" % _one_line(concern["returned"]))
        status = concern["status"]
        if status == ANSWERED:
            status += ": %s" % _one_line(concern["answer"])
        elif status == DECLINED:
            status += ": %s" % _one_line(concern["reason"])
        lines.append("- Status: %s" % status)
        lines.append("")
    return "\n".join(lines)
