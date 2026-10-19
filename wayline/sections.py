"""The paper's five sections and the passages that make them (Implementation Decision 17; ticket 86).

**The sections.** `research/sections/introduction.md`, `results.md`, `discussion.md`, `methods.md`, and
`references.md` exist from `init` and are rendered by code alone: no model edits them. Each file opens with
a one-line render stamp, an HTML comment carrying the section, when it was rendered, the last passage or
finding id it had seen, and the sha256 of the body below it, so that a later reader (the owner's edits,
ticket 88) can tell an edit from passages that arrived since.

**Passages.** A ticket result's `passages[]`, each `{section, heading, text, replaces}`, go through
`add_passage`, the one ledger call every contributor uses (a ticket's attempt, the owner, a document, a
front-door step, an answered objective, or a consolidation, named by `by`). The ledger keeps them in
`research/passages.jsonl` with ids P1 onward and the ticket's `objectives`, and journals each as `passage`.

**Findings.** A finding is a Results passage: it keeps `findings.jsonl` and its F id, and gains `heading`,
`replaces`, and `objectives`, so a scope-down replaces the finding it narrows. `results.md` renders from
the findings and the inherited Results passages; every other section from `passages.jsonl`.

**Inherited passages** (ticket 93, `wayline.inherited`) are passages `by` a document, deconstructed verbatim
from an earlier manuscript; they alone may stand in Results outside `findings.jsonl`. Each carries `doc`, its
locator in the document, and an inherited claim its `standing`: `unchecked` until a passage or finding replaces
it naming in `evidence` whether this project's evidence supports, narrows, or contradicts it, or `unverifiable`
with its `reason`. A render rejoins the passages of one paragraph of the document, with a replacement in its
place, and marks each claim with its standing. A withdrawal (`withdrawn`) replaces a passage and takes it out
of the section.

**How a section renders** (`arrange`). A replaced passage leaves the file and stays in the log. Within a
heading passages keep their arrival order, and a replacement takes the place of what it replaces (under
that passage's heading when the replacement names the same heading or none, else it moves under its own).
Headings keep their first-appearance order (until the outline orders them, ticket 104). Two passages that
replace one passage in the same wave are both kept, and the section notes it; a replacement of a passage
that was already replaced in an earlier wave replaces what stands in its place now, since it is the later
word on the same text.

**Which sections a ticket adds to.** A ticket's `sections` is set by its kind (`KIND_SECTIONS`): `code` and
`experiment` declare Methods, `analysis` Methods and Results, `lit` Introduction, `writing` what it writes,
the other kinds none. `check_result` is the Type-A check at acceptance: a declared section that got no
passage (for Results, no finding) sends the worker back, and so does a `replaces` that names nothing the
section holds. Sections never enter a touch set.
"""

import hashlib
import json
import re

from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import LedgerError, ledger_for, make_event, now_ts

__all__ = [
    "SECTIONS", "TITLES", "WRITTEN", "SECTIONS_DIR", "PASSAGES", "FINDINGS", "KIND_SECTIONS", "BY_RE", "SectionError",
    "section_path", "sections_for_kind", "declared", "read_passages", "read_findings", "add_passage", "file_finding", "seed_passages",
    "arrange", "render_section", "render_sections", "read_stamp", "first_sentence", "pack_text", "check_result",
    "check_replaces", "by_ticket", "INHERITED", "STANDINGS", "EVIDENCE", "UNCHECKED", "UNVERIFIABLE", "is_inherited",
    "paragraph_of", "mark_of", "section_items", "current_ids",
]

SECTIONS = ("introduction", "results", "discussion", "methods", "references")
TITLES = {"introduction": "Introduction", "results": "Results", "discussion": "Discussion", "methods": "Methods",
          "references": "References"}
RESULTS = "results"
# The sections a passage names; Results is written as findings.
WRITTEN = tuple(name for name in SECTIONS if name != RESULTS)
# The sections an inherited passage stands in: Results too, since nothing of a document is a finding.
INHERITED = ("introduction", "results", "discussion", "methods")
DOCUMENT_BY = "document:"
UNCHECKED = "unchecked"
UNVERIFIABLE = "unverifiable"
STANDINGS = (UNCHECKED, UNVERIFIABLE)
# What a passage or a finding replacing an inherited claim says of it.
EVIDENCE = ("supports", "narrows", "contradicts")
SECTIONS_DIR = "sections"
PASSAGES = "passages.jsonl"
FINDINGS = "findings.jsonl"
PASSAGE = "passage"  # the journal event of one passage written
FINDING = "finding"  # the journal event of one finding written

# The sections each kind declares (decision 17); `writing` declares what it writes, the rest none.
KIND_SECTIONS = {"code": ("methods",), "experiment": ("methods",), "analysis": ("methods", "results"),
                 "lit": ("introduction",)}
WRITING = "writing"

# Who contributed a passage: a ticket's attempt (`t3-a1`), the owner, a document (`document:<id>`), a
# front-door step (`step:<name>`), an answered objective (`objective:O2`), or a consolidation.
BY_RE = re.compile(r"^(t[1-9][0-9]*-a[1-9][0-9]*|owner|document:[A-Za-z0-9._-]+|step:[a-z][a-z0-9-]*|"
                   r"objective:O[1-9][0-9]*|consolidation)$")
OWNER = "owner"

STAMP_RE = re.compile(r"^<!-- wayline:render (\{.*\}) -->$")
_PASSAGE_ID = re.compile(r"^P([1-9][0-9]*)$")
_TAG = re.compile(r"\{(?:res|ref|doc):[^{}]+\}")
_SENTENCE_END = re.compile(r"[.!?](?:\{(?:res|ref|doc):[^{}]+\})*(?=\s|$)")


class SectionError(LedgerError):
    """A passage the ledger refuses: an unknown section, an empty heading or text, a `by` it cannot read, a bad `replaces`."""


def section_path(section):
    """`sections/<section>.md`, relative to `research/`."""
    return "%s/%s.md" % (SECTIONS_DIR, section)


def by_ticket(ticket, attempt):
    """The `by` of a passage a ticket's attempt wrote."""
    return "t%d-a%d" % (ticket, attempt)


def sections_for_kind(kind):
    """The sections a ticket of `kind` declares by default (a `writing` ticket's are its own to name)."""
    return list(KIND_SECTIONS.get(kind, ()))


def declared(fields):
    """The sections a ticket declares: its `sections`, which the plan sets by kind; none for a ticket without the field."""
    return [name for name in fields.get("sections") or [] if name in SECTIONS]


# --- reading the logs ----------------------------------------------------------------------------------


def _read_lines(book, name):
    path = book.research / name
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn line a crashed writer left; the next append closes it
            if isinstance(record, dict):
                records.append(record)
    return records


def read_passages(project_or_ledger):
    """Every passage of `research/passages.jsonl`, in arrival order."""
    return _read_lines(ledger_for(project_or_ledger), PASSAGES)


def read_findings(project_or_ledger):
    """Every finding of `research/findings.jsonl`, in arrival order: the Results section's passages."""
    return _read_lines(ledger_for(project_or_ledger), FINDINGS)


def _items(book, section):
    """The log of one section in arrival order: for Results, its findings and its inherited passages by when each came."""
    passages = [item for item in read_passages(book) if item.get("section") == section]
    if section != RESULTS:
        return passages
    # Each log keeps its own order; the two merge by when each line came, a line with no time (a finding filed before
    # findings carried one) taking the time of the line before it in its own log.
    keyed = []
    for rank, log in enumerate((read_findings(book), passages)):
        stamp = ""
        for index, item in enumerate(log):
            stamp = max(stamp, str(item.get("ts") or ""))
            keyed.append((stamp, rank, index, item))
    return [item for _, _, _, item in sorted(keyed, key=lambda entry: entry[:3])]


def section_items(project_or_ledger, section):
    """Every item one section's log holds, replaced ones too, in arrival order: what `arrange` takes."""
    return _items(ledger_for(project_or_ledger), section)


def current_ids(project_or_ledger, section):
    """The ids of the items that stand in a section now."""
    return {item.get("id") for item in arrange(section_items(project_or_ledger, section)).current()}


def is_inherited(item):
    """Whether a passage is an inherited one, contributed by a document."""
    return str((item or {}).get("by") or "").startswith(DOCUMENT_BY)


def paragraph_of(item):
    """The document paragraph an inherited passage was cut from (`D1#p4`), or None for any other passage."""
    doc = (item or {}).get("doc")
    return str(doc).split(".", 1)[0] if doc else None


def mark_of(item):
    """What a render writes after an inherited claim: its standing, with the reason when it is unverifiable."""
    standing = (item or {}).get("standing")
    if standing == UNCHECKED:
        return "[unchecked]"
    if standing == UNVERIFIABLE:
        reason = _one_line(item.get("reason") or "no reason given").replace("[", "(").replace("]", ")")
        return "[unverifiable: %s]" % reason
    return None


# --- writing a passage ---------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text or "").split())


def check_replaces(project_or_ledger, section, replaces):
    """Why `replaces` names nothing `section` holds, or None when it names a passage (a finding, for Results) of it."""
    if replaces is None:
        return None
    held = {item.get("id") for item in _items(ledger_for(project_or_ledger), section)}
    if replaces not in held:
        return "replaces %s, which %s does not hold" % (replaces, TITLES.get(section, section))
    return None


def add_passage(project_or_ledger, section, heading, text, *, by, replaces=None, objectives=(), ticket=None, wave=None,
                render=True, evidence=None, doc=None, standing=None, reason=None, withdrawn=False, moved_from=None):
    """Write one passage through the ledger: `passages.jsonl` with the next P id, the `passage` event, and the section re-rendered.

    `by` names who contributed it (`BY_RE`); `objectives` are the ticket's; `wave` is the wave it was integrated in,
    which is what tells two replacements of one passage in the same wave from a later word on it. Results is written
    as findings, never here, except an inherited passage (`by` a document). `evidence` is what a passage replacing an
    inherited claim says of it; `doc`, `standing`, `reason`, `withdrawn`, and `moved_from` are an inherited passage's
    (the module's docstring). Returns the record written.
    """
    book = ledger_for(project_or_ledger)
    if evidence is not None and (evidence not in EVIDENCE or replaces is None):
        raise SectionError("a passage's evidence is one of %s, said of the inherited claim it replaces; got %r%s"
                           % (", ".join(EVIDENCE), evidence, "" if replaces else " with nothing replaced"))
    if section not in WRITTEN and not (section in INHERITED and str(by or "").startswith(DOCUMENT_BY)):
        raise SectionError("a passage names one of %s, got %r%s" % (", ".join(WRITTEN), section,
                                                                  "; a Results passage is a finding" if section == RESULTS else ""))
    heading, text = _one_line(heading), str(text or "").strip()
    if not heading:
        raise SectionError("a passage needs a heading")
    if not text:
        raise SectionError("a passage needs text")
    if not BY_RE.match(str(by or "")):
        raise SectionError("a passage's by is a ticket's attempt (t3-a1), owner, document:<id>, step:<name>, "
                           "objective:O<n>, or consolidation; got %r" % (by,))
    with book.lock():
        problem = check_replaces(book, section, replaces)
        if problem is not None:
            raise SectionError("the passage %s" % problem)
        highest = max((int(found.group(1)) for found in (_PASSAGE_ID.match(str(item.get("id") or "")) for item in read_passages(book))
                       if found), default=0)
        record = {"id": "P%d" % (highest + 1), "section": section, "heading": heading, "text": text, "replaces": replaces,
                  "by": by, "objectives": list(objectives or []), "ticket": ticket, "wave": wave, "ts": now_ts()}
        extra = {"evidence": evidence, "doc": doc, "standing": standing, "reason": reason, "withdrawn": True if withdrawn else None,
                 "moved_from": moved_from}
        record.update({key: value for key, value in extra.items() if value is not None})
        try:
            check(record, load_schema("passage"), name="passage %s" % record["id"])
        except ValidationError as failure:
            raise SectionError(str(failure)) from None
        payload = {key: record[key] for key in ("id", "section", "heading", "text", "replaces", "by", "objectives")}
        payload.update({key: record[key] for key in extra if key in record})
        make_event(PASSAGE, payload, ticket=ticket)  # refused before anything is written, never after the log took it
        book.append_record(PASSAGES, record)
        book.append_event(PASSAGE, payload, ticket=ticket)
        if render:
            render_section(book, section)
    return record


def file_finding(project_or_ledger, record, wave=None, render=True):
    """Write one finding through the ledger: `findings.jsonl`, the `finding` event, and Results re-rendered.

    `record` carries `id`, `ticket`, `text`, `provenance`, and `negative`, and the Results passage's `heading`,
    `replaces` (a finding's id or an inherited Results passage's, or None), `objectives`, and, when it replaces an
    inherited claim, `evidence`; a `replaces` naming nothing Results holds is refused before anything is written.
    `wave` is kept on the line, as on a passage's. Returns the line written.
    """
    book = ledger_for(project_or_ledger)
    record = dict(record)
    record["heading"] = _one_line(record.get("heading")) or None
    record.setdefault("replaces", None)
    record["objectives"] = list(record.get("objectives") or [])
    record.setdefault("ts", now_ts())  # what orders it against the inherited Results passages it may replace
    if record.get("evidence") is None:
        record.pop("evidence", None)
    elif record["evidence"] not in EVIDENCE or record["replaces"] is None:
        raise SectionError("a finding's evidence is one of %s, said of the inherited claim it replaces; got %r"
                           % (", ".join(EVIDENCE), record["evidence"]))
    payload = {key: record[key] for key in ("id", "ticket", "text", "provenance", "negative", "heading", "replaces", "objectives",
                                            "evidence") if key in record}
    with book.lock():
        problem = check_replaces(book, RESULTS, record["replaces"])
        if problem is not None:
            raise SectionError("the finding %s" % problem)
        make_event(FINDING, payload, ticket=record.get("ticket"))
        line = dict(record, wave=wave) if wave is not None else record
        book.append_record(FINDINGS, line)
        book.append_event(FINDING, payload, ticket=record.get("ticket"))
        if render:
            render_section(book, RESULTS)
    return line


def seed_passages(project_or_ledger, section, items, by, objectives=(), key=None):
    """Code's own passages (`items`: `(heading, text)`), each written once, through the same ledger call as a ticket's.

    A text the section already holds from `by` is skipped. `key(heading, text)` names what a passage is about (a
    reference's slug, a heading): a new text whose key matches a current passage of `by` replaces that passage, so a
    memo taken again or a spec amended rewords what it seeded rather than standing beside it. What setup seeds the
    Introduction with, and what code writes for an answered objective (ticket 91). Returns the records written.
    """
    book = ledger_for(project_or_ledger)
    key = key or (lambda heading, text: (heading, text))
    written = []
    with book.lock():
        ours = [item for item in read_passages(book) if item.get("section") == section and item.get("by") == by]
        held = {_one_line(item.get("text")) for item in ours}
        current = {item.get("id") for item in arrange(_items(book, section)).current()}
        keyed = {key(_one_line(item.get("heading")), _one_line(item.get("text"))): item.get("id")
                 for item in ours if item.get("id") in current}
        for heading, text in items:
            heading, text = _one_line(heading), str(text or "").strip()
            if _one_line(text) in held or not text or not heading:
                continue
            replaces = keyed.pop(key(heading, _one_line(text)), None)
            written.append(add_passage(book, section, heading, text, by=by, replaces=replaces, objectives=objectives, render=False))
            held.add(_one_line(text))
        if written:
            render_section(book, section)
    return written


# --- what a worker is shown ---------------------------------------------------------------------------


def first_sentence(text):
    """The first sentence of a passage, with the provenance tags it ends with: what a worker's context pack shows of it."""
    text = " ".join(str(text or "").split())
    found = _SENTENCE_END.search(text)
    return text[:found.end()] if found else text


def pack_text(project_or_ledger, declared_sections, max_chars=None):
    """The context pack's part on the paper (decision 17): per declared section, its headings with each current
    passage's id and first sentence, and the owner's passages in full; empty when the ticket declares none.

    `max_chars` is the tier's context cap, which this part keeps to on its own: what does not fit is cut with the cut
    announced, as the planner's pack is.
    """
    book = ledger_for(project_or_ledger)
    wanted = [name for name in SECTIONS if name in set(declared_sections or ())]
    if not wanted:
        return ""
    lines = ["# The paper's sections", "",
             "Code writes `research/sections/` from the passages tickets return; nobody edits the files. Return what this "
             "ticket adds as `passages` (Results as `findings`), each under a heading: reuse a heading below when one fits, "
             "and name in `replaces` the id of a passage (a finding, for Results) yours narrows or corrects. The owner's "
             "passages steer the work: replace one only with evidence and a stated reason. An inherited claim, from the "
             "project's own earlier writing, stands unchecked until a passage or finding of yours replaces it and says in "
             "`evidence` whether this project's evidence `supports`, `narrows`, or `contradicts` it."]
    for section in wanted:
        arranged = arrange(_items(book, section))
        lines += ["", "## %s" % TITLES[section], ""]
        if not arranged.headings:
            lines.append("Nothing yet.")
        for heading, current in arranged.headings:
            lines.append("- %s" % heading)
            for item in current:
                if item.get("by") == OWNER:
                    lines.append("  - %s (the owner's, in full): %s" % (item.get("id"), " ".join(str(item.get("text") or "").split())))
                elif is_inherited(item) and item.get("standing") in STANDINGS:
                    lines.append("  - %s (inherited claim, %s): %s" % (item.get("id"), item["standing"], first_sentence(item.get("text"))))
                else:
                    lines.append("  - %s: %s" % (item.get("id"), first_sentence(item.get("text"))))
    text = "\n".join(lines)
    if max_chars is not None and len(text) > max(0, int(max_chars)):
        cut = text[:max(0, int(max_chars))].rsplit("\n", 1)[0]
        text = cut + ("\n\n[wayline: this part reached the context cap of %d characters; the rest of the declared sections "
                      "is in research/sections/.]" % int(max_chars))
    return text


# --- the Type-A check at acceptance ---------------------------------------------------------------------


def check_result(project_or_ledger, fields, result):
    """The declared-sections check of decision 17 over one ticket result: the problems, each one line, empty when it passes.

    A section the ticket declares that got no passage fails, and Results fails when it got no finding; a passage or a
    finding whose `replaces` names nothing its section holds fails too.
    A ticket without `sections` is held to none. A `running` result (its jobs not yet run) is not held to Results: it
    can have no finding before its jobs have written anything.
    """
    book = ledger_for(project_or_ledger)
    result = result if isinstance(result, dict) else {}
    passages = [item for item in result.get("passages") or [] if isinstance(item, dict)]
    findings = [item for item in result.get("findings") or [] if isinstance(item, dict)]
    problems = []
    for section in declared(fields):
        if section == RESULTS:
            if not findings and result.get("status") != "running":
                problems.append("ticket %s declares Results and returned no finding: a Results passage is a finding, in "
                                "`findings`, with its heading" % fields.get("id"))
        elif not any(item.get("section") == section for item in passages):
            problems.append("ticket %s declares %s and returned no passage for it: add one to `passages` with section `%s`"
                            % (fields.get("id"), TITLES[section], section))
    for index, item in enumerate(passages, start=1):
        if item.get("section") not in WRITTEN:
            continue  # the result's schema refuses it already
        problem = (check_replaces(book, item["section"], item.get("replaces"))
                   or _evidence_problem(book, item["section"], item.get("replaces"), item.get("evidence")))
        if problem is not None:
            problems.append("passage %d (%s, %s) %s" % (index, TITLES[item["section"]], _one_line(item.get("heading")), problem))
    for index, item in enumerate(findings, start=1):
        problem = (check_replaces(book, RESULTS, item.get("replaces"))
                   or (None if item.get("negative") else _evidence_problem(book, RESULTS, item.get("replaces"), item.get("evidence"))))
        if problem is not None:
            problems.append("finding %d %s" % (index, problem))
    return problems


def _evidence_problem(book, section, replaces, evidence):
    """Why `evidence` does not fit what `replaces` names: an inherited claim must be answered by it, nothing else carries it."""
    target = next((item for item in _items(book, section) if item.get("id") == replaces), None) if replaces else None
    claim = target is not None and is_inherited(target) and target.get("standing") in STANDINGS
    if claim and evidence not in EVIDENCE:
        return ("replaces the inherited claim %s, %s: say in `evidence` whether this project's evidence supports, narrows, "
                "or contradicts it" % (replaces, target.get("standing")))
    if not claim and evidence is not None:
        return "carries evidence %r, which is said only of an inherited claim it replaces" % (evidence,)
    return None


# --- arranging and rendering ---------------------------------------------------------------------------


class Arranged:
    """A section as it renders: `headings` in order, each with its current items, and the notes on kept conflicts."""

    def __init__(self):
        self.headings = []   # [(heading, [item])]
        self.notes = []
        self.last = None     # the id of the last item seen

    def current(self):
        return [item for _, items in self.headings for item in items]


def arrange(items):
    """The current items of one section, by heading, in the order decision 17 gives (the module's docstring)."""
    arranged = Arranged()
    slots = {}            # heading -> [item]
    order = []            # headings, first appearance
    where = {}            # id -> heading of a current item
    successors = {}       # id -> [(item, wave)] that replaced it, in arrival order
    by_id = {}
    kept = {}             # id replaced twice in one wave -> the ids kept side by side

    def standing(target):
        """The current items that stand where `target` stood, following its replacements down to what renders now."""
        found, queue = [], list(successors.get(target, []))
        while queue:
            child, _ = queue.pop(0)
            if child.get("id") in where:
                found.append(child)
            else:
                queue.extend(successors.get(child.get("id"), []))
        return found

    for item in items:
        identifier = item.get("id")
        by_id[identifier] = item
        arranged.last = identifier
        heading = _one_line(item.get("heading")) or "Findings"
        target = item.get("replaces")
        if target is None or target not in by_id:
            _append(slots, order, where, item, heading)
            continue
        wave = item.get("wave")
        earlier = successors.setdefault(target, [])
        same_wave = [found for found, found_wave in earlier
                     if wave is not None and found_wave == wave and found.get("id") in where]
        if target in where:
            place_heading = where.pop(target)
            _put(slots, order, where, item, heading, place_heading, slots[place_heading].index(by_id[target]), remove=by_id[target])
        elif same_wave:
            anchor = same_wave[-1]
            place_heading = where[anchor["id"]]
            _put(slots, order, where, item, heading, place_heading, slots[place_heading].index(anchor) + 1)
            ids = kept.setdefault(target, [found.get("id") for found in same_wave])
            ids.append(identifier)
        else:
            now = standing(target)
            if now:
                first = now[0]
                place_heading = where.pop(first["id"])
                _put(slots, order, where, item, heading, place_heading, slots[place_heading].index(first), remove=first)
                for other in now[1:]:
                    slots[where.pop(other["id"])].remove(other)
            else:
                _append(slots, order, where, item, heading)
        earlier.append((item, wave))
        if item.get("withdrawn") and identifier in where:
            slots[where.pop(identifier)].remove(item)  # a withdrawal takes the place of what it replaces, and leaves with it
    arranged.headings = [(heading, list(slots[heading])) for heading in order if slots.get(heading)]
    # A note stands while at least two of the passages kept side by side still render; one replaced since resolves it.
    for target, ids in kept.items():
        current = [identifier for identifier in dict.fromkeys(ids) if identifier in where]
        if len(current) > 1:
            arranged.notes.append((target, current))
    return arranged


def _append(slots, order, where, item, heading):
    if heading not in slots:
        slots[heading] = []
        order.append(heading)
    slots[heading].append(item)
    where[item.get("id")] = heading


def _put(slots, order, where, item, heading, place_heading, index, remove=None):
    """`item` at `index` under `place_heading` when it names that heading, else appended under its own; `remove` leaves."""
    if remove is not None:
        slots[place_heading].remove(remove)
    if heading == place_heading or not _one_line(item.get("heading")):
        slots[place_heading].insert(index, item)
        where[item.get("id")] = place_heading
    else:
        _append(slots, order, where, item, heading)


def _finding_text(item, manifest):
    """A finding as Results prints it: its text, with its provenance as `res` tags when the text carries none."""
    text = str(item.get("text") or "").strip()
    if _TAG.search(text):
        return text
    from wayline import provenance  # the provenance module pulls in the gates and the report
    return provenance.tagged_text(text, provenance.finding_tags(item, manifest))


def _paragraphs(current, by_id):
    """The current items of one heading as the paragraphs a render prints: consecutive passages cut from one paragraph
    of a document rejoin, a replacement of one of them standing in its place; every other item is its own."""
    def key(item, seen=()):
        found = paragraph_of(item)
        if found is not None or item.get("replaces") not in by_id or item.get("id") in seen:
            return found
        return key(by_id[item["replaces"]], seen + (item.get("id"),))

    groups, last = [], None
    for item in current:
        found = key(item)
        if found is not None and found == last:
            groups[-1].append(item)
        else:
            groups.append([item])
        last = found
    return groups


def _body(book, section):
    items = _items(book, section)
    arranged = arrange(items)
    manifest = None
    if section == RESULTS:
        try:
            manifest = book.read_json("manifest.json")
        except (OSError, ValueError):
            manifest = {"entries": []}
    lines = ["# %s" % TITLES[section], ""]
    if not arranged.headings:
        lines += ["Nothing yet: code writes this section from the passages tickets return.", ""]
    by_id = {item.get("id"): item for item in items}
    for heading, current in arranged.headings:
        lines += ["## %s" % heading, ""]
        for group in _paragraphs(current, by_id):
            texts = []
            for item in group:
                text = (_finding_text(item, manifest) if section == RESULTS and not is_inherited(item)
                        else str(item.get("text") or "").strip())
                mark = mark_of(item)
                texts.append("%s %s" % (text, mark) if mark else text)
            lines += ["<!-- wayline:passage %s -->" % " ".join(str(item.get("id")) for item in group), " ".join(texts), ""]
    for target, ids in arranged.notes:
        lines += ["> Note: %s each replace %s, which they did in the same wave, so both are kept until one replaces the other."
                  % (" and ".join(ids), target), ""]
    return "\n".join(lines).rstrip("\n") + "\n", arranged.last


def render_section(project_or_ledger, section):
    """Write `research/sections/<section>.md` from its log; a body that did not change keeps its file and its stamp.

    Returns whether the file was written.
    """
    book = ledger_for(project_or_ledger)
    if section not in SECTIONS:
        raise SectionError("there is no section %r; the sections are %s" % (section, ", ".join(SECTIONS)))
    with book.lock():
        body, last = _body(book, section)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        stamp = read_stamp(book, section)
        if stamp is not None and stamp.get("sha256") == digest and stamp.get("last") == last:
            return False
        record = {"section": section, "rendered_at": now_ts(), "last": last, "sha256": digest}
        book.write_markdown(section_path(section), "<!-- wayline:render %s -->\n%s" % (json.dumps(record, ensure_ascii=False), body))
    return True


def render_sections(project_or_ledger, only=None):
    """Render every section (or those in `only`); returns the ones written."""
    book = ledger_for(project_or_ledger)
    return [section for section in (only or SECTIONS) if render_section(book, section)]


def read_stamp(project_or_ledger, section):
    """The render stamp on the first line of a section's file, or None when the file or its stamp is missing."""
    path = ledger_for(project_or_ledger).research / section_path(section)
    try:
        with open(path, encoding="utf-8") as handle:
            first = handle.readline().rstrip("\n")
    except OSError:
        return None
    found = STAMP_RE.match(first)
    if found is None:
        return None
    try:
        record = json.loads(found.group(1))
    except ValueError:
        return None
    return record if isinstance(record, dict) else None
