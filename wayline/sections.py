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
Headings keep their first-appearance order until the outline orders them (ticket 104, `wayline.outline`): before the
paper order a section renders its headings in the outline's order, and a heading the outline places under Supplement or
Cut still renders, at the end of the section under a marker (`arranged`). Two passages that
replace one passage in the same wave are both kept, and the section notes it; a replacement of a passage
that was already replaced in an earlier wave replaces what stands in its place now, since it is the later
word on the same text.

**Which sections a ticket adds to.** A ticket's `sections` is set by its kind (`KIND_SECTIONS`): `code` and
`experiment` declare Methods, `analysis` Methods and Results, `lit` Introduction, `writing` what it writes,
the other kinds none. `check_result` is the Type-A check at acceptance: a declared section that got no
passage (for Results, no finding) sends the worker back, and so does a `replaces` that names nothing the
section holds. Sections never enter a touch set.

**The owner's passages** (ticket 88). `wayline passage add` writes one `by: owner`, in any section, Results
included; the owner's edit of a section file is taken in before the next render (`take_in`), by the file's
render stamp. The owner's passages steer with no lock: a ticket's passage or finding replaces one only with
evidence and a stated `reason` (`owner_replacement_problem`, part of `check_result`), and is journaled with
`replaces_owner` for the account. A consolidation (`wayline.consolidation`) writes `by: consolidation`. Every
render records the linter's reading of the section in `research/sections/lint.json` (`lint_section`).

**Methods' generated part** (ticket 108, `wayline.methods_inventory`). After its passages, `methods.md` carries what the
methods inventory generates at every render under `INVENTORY`: the parameter table, the software and its versions, and
the proposed citations. An edit is read as passages up to that line and never past it; a reason the owner changes in
the table is taken in as the owner's passage for its row (`parameter`), which the table shows and the text never does
(`is_reason`).
"""

import hashlib
import json
import re

from wayline import results
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import LedgerError, ledger_for, make_event, now_ts

__all__ = [
    "SECTIONS", "TITLES", "WRITTEN", "SECTIONS_DIR", "PASSAGES", "FINDINGS", "KIND_SECTIONS", "BY_RE", "SectionError",
    "section_path", "sections_for_kind", "declared", "read_passages", "read_findings", "add_passage", "file_finding", "seed_passages",
    "arrange", "render_section", "render_sections", "read_stamp", "first_sentence", "pack_text", "check_result",
    "check_replaces", "by_ticket", "INHERITED", "STANDINGS", "EVIDENCE", "UNCHECKED", "UNVERIFIABLE", "is_inherited",
    "paragraph_of", "mark_of", "section_items", "current_ids", "OWNER", "CONSOLIDATION", "LINT", "is_finding", "take_in",
    "lint_section", "owner_replacement_problem", "add_owners_passage", "passage_command", "arranged", "OUTLINED", "PLACED_MARKS",
    "INVENTORY", "NOTES", "is_reason",
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
CONSOLIDATION = "consolidation"
# Who may write a passage straight into Results besides a document: the owner, and a consolidation the owner asked for.
RESULTS_BY = (OWNER, CONSOLIDATION)
# Where code records the linter's reading of each section at every render (ticket 88): what it failed and what it lists.
LINT = "%s/lint.json" % SECTIONS_DIR
# The line after a section's passages that opens code's notes; an edit is read up to it and never past it.
NOTES = "<!-- wayline:notes -->"
# The line before what the methods inventory generates into Methods (ticket 108): the parameter table, the software, the
# proposed citations. An edit is read as passages up to it and never past it; only a reason in the table is taken in.
INVENTORY = "<!-- wayline:inventory -->"
NOTHING_YET = "Nothing yet: code writes this section from the passages tickets return."
# The heading new text the owner wrote above every heading of a section file stands under.
OWNER_HEADING = "The owner's notes"
# The sections whose headings the outline orders (ticket 104); References is rendered by code from the citations.
OUTLINED = ("introduction", "results", "discussion", "methods")
# What a section prints before the headings the outline placed under Supplement or Cut, which still render until the order;
# an edit is never read from it.
PLACED_MARKS = {"supplement": "> Placed in the supplement by the outline: it renders here until the paper order.",
                "cut": "> Cut by the outline: it renders here until the paper order."}
_PLACED_MARK = re.compile(r"^> (?:Placed in the supplement|Cut) by the outline: ")

STAMP_RE = re.compile(r"^<!-- wayline:render (\{.*\}) -->$")
_PASSAGE_ID = re.compile(r"^P([1-9][0-9]*)$")
_PASSAGE_MARK = re.compile(r"^<!-- wayline:passage ([^<>]+?) -->$")
# The marks a render writes after an inherited claim, which are the render's and never part of the owner's text.
_RENDER_MARK = re.compile(r"\s*\[(?:unchecked|unverifiable: [^\[\]]*)\]")
# A tag that is evidence for a passage replacing an owner's: a result, a reference, or the code, never a `doc` tag.
_EVIDENCE_TAG = re.compile(r"\{(?:res|ref|code):[^{}]+\}")
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


def is_reason(item):
    """Whether a passage is the owner's reason for a row of Methods' parameter table (ticket 108): the table shows it,
    never the section's text."""
    return bool((item or {}).get("parameter"))


def _items(book, section):
    """The log of one section in arrival order: for Results, its findings and its inherited passages by when each came.
    An owner's reason for a parameter is the table's, not the section text's (`is_reason`)."""
    passages = [item for item in read_passages(book) if item.get("section") == section and not is_reason(item)]
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


def _owners(book, section, replaces):
    """Whether replacing `replaces` replaces an owner's passage of `section`: the one it names, or, when that was replaced
    since, what stands in its place now, which is what `arrange` takes out.

    A consolidation's passage is the owner's when any passage it consolidated was, since the owner asked for it.
    """
    if not replaces:
        return False
    items = _items(book, section)
    by_id = {item.get("id"): item for item in items}
    if replaces not in by_id:
        return False
    current = {item.get("id") for item in arrange(items).current()}
    children = {}
    for item in items:
        if item.get("replaces"):
            children.setdefault(item["replaces"], []).append(item)
    standing, queue, seen = [], [by_id[replaces]], set()
    while queue:
        item = queue.pop(0)
        if item.get("id") in seen:
            continue
        seen.add(item.get("id"))
        if item.get("id") in current:
            standing.append(item)
        else:
            queue.extend(children.get(item.get("id"), []))
    return any(_owned(item, by_id) for item in standing)


def _owned(item, by_id, seen=()):
    """Whether a passage is the owner's: by the owner, or a consolidation of a passage that was."""
    if item.get("by") == OWNER:
        return True
    if item.get("by") != CONSOLIDATION or item.get("id") in seen:
        return False
    return any(_owned(by_id[identifier], by_id, seen + (item.get("id"),))
               for identifier in item.get("consolidates") or [] if identifier in by_id)


def owner_replacement_problem(project_or_ledger, section, replaces, text, reason, finding=False):
    """Why a ticket's passage (or finding) may not replace what `replaces` names, or None (decision 17; ticket 88).

    The owner's passages steer with no lock: a later passage replaces one only with evidence (a `res`, `ref`, or
    `code` tag; a finding's provenance is its evidence) and a stated `reason`. Anything else replaces freely.
    """
    if not _owners(ledger_for(project_or_ledger), section, replaces):
        return None
    missing = []
    if not finding and not _EVIDENCE_TAG.search(str(text or "")):
        missing.append("evidence (a `res`, `ref`, or `code` tag on its claim)")
    if not str(reason or "").strip():
        missing.append("a `reason`, one sentence on why the evidence overrides it")
    if not missing:
        return None
    return "replaces %s, the owner's passage, which a later passage replaces only with %s" % (replaces, " and ".join(missing))


def add_passage(project_or_ledger, section, heading, text, *, by, replaces=None, objectives=(), ticket=None, wave=None,
                render=True, evidence=None, doc=None, standing=None, reason=None, withdrawn=False, moved_from=None,
                consolidates=None, merges=None, parameter=None):
    """Write one passage through the ledger: `passages.jsonl` with the next P id, the `passage` event, and the section re-rendered.

    `by` names who contributed it (`BY_RE`); `objectives` are the ticket's; `wave` is the wave it was integrated in,
    which is what tells two replacements of one passage in the same wave from a later word on it. Results is written
    as findings, never here, except an inherited passage (`by` a document). `evidence` is what a passage replacing an
    inherited claim says of it; `doc`, `standing`, `reason`, `withdrawn`, and `moved_from` are an inherited passage's
    (the module's docstring); `merges` names every occurrence a merged inherited passage merges (ticket 95). `parameter`
    makes it the owner's reason for one row of Methods' parameter table (ticket 108, `methods_inventory.parameter_key`),
    which the table shows in place of the ticket's. Returns the record written.
    """
    book = ledger_for(project_or_ledger)
    if evidence is not None and (evidence not in EVIDENCE or replaces is None):
        raise SectionError("a passage's evidence is one of %s, said of the inherited claim it replaces; got %r%s"
                           % (", ".join(EVIDENCE), evidence, "" if replaces else " with nothing replaced"))
    if section not in WRITTEN and not (section == RESULTS and (str(by or "").startswith(DOCUMENT_BY) or by in RESULTS_BY)):
        raise SectionError("a passage names one of %s, got %r%s" % (", ".join(WRITTEN), section,
                                                                  "; a Results passage is a finding" if section == RESULTS else ""))
    heading, text = _one_line(heading), str(text or "").strip()
    if not heading:
        raise SectionError("a passage needs a heading")
    if not text:
        raise SectionError("a passage needs text")
    if parameter is not None:
        from wayline import methods_inventory  # the inventory renders into Methods through this module
        if section != "methods" or by != OWNER or methods_inventory.parse_parameter(parameter) is None:
            raise SectionError("a reason for a parameter is the owner's, in Methods, naming <method>:<name>[@<path>]; got %r"
                               % (parameter,))
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
        # A passage replacing an owner's is journaled for the account, "Changed without asking you" (ticket 88).
        extra = {"evidence": evidence, "doc": doc, "standing": standing, "reason": reason, "withdrawn": True if withdrawn else None,
                 "moved_from": moved_from, "consolidates": list(consolidates) if consolidates else None,
                 "merges": list(merges) if merges else None, "parameter": parameter,
                 "replaces_owner": True if by not in RESULTS_BY and _owners(book, section, replaces) else None}
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
    if not record.get("reason"):
        record.pop("reason", None)
    with book.lock():
        problem = check_replaces(book, RESULTS, record["replaces"])
        if problem is not None:
            raise SectionError("the finding %s" % problem)
        if _owners(book, RESULTS, record["replaces"]):
            record["replaces_owner"] = True  # journaled for the account: changed without asking the owner (ticket 88)
        # The result it joins, clustered by code at its acceptance (ticket 90): written only once the finding is.
        record["result"], created, clusters = results.assign(book, record)
        payload = {key: record[key] for key in ("id", "ticket", "text", "provenance", "negative", "heading", "replaces", "objectives",
                                                "evidence", "reason", "replaces_owner", "result") if key in record}
        make_event(FINDING, payload, ticket=record.get("ticket"))
        line = dict(record, wave=wave) if wave is not None else record
        book.append_record(FINDINGS, line)
        results.commit(book, clusters, created, ticket=record.get("ticket"))  # a result only once its first finding is filed
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
             "and name in `replaces` the id of a passage (a finding, for Results) yours narrows or corrects. Every claim "
             "sentence ends with its provenance tag: `{res:<run-id>/<artifact>#<locator>}`, `{ref:<slug>#<locator>}`, or "
             "`{code:<path>#<symbol>}` (or `#L10-L42`) for what the project's code does; the linter checks each at "
             "acceptance. The owner's passages steer the work: replace one only with evidence (such a tag; a finding's "
             "provenance) and a stated `reason`, or it is sent back. An inherited claim, from the "
             "project's own earlier writing, stands unchecked until a passage or finding of yours replaces it and says in "
             "`evidence` whether this project's evidence `supports`, `narrows`, or `contradicts` it."]
    orders = {}  # the outline read once for every declared section
    for section in wanted:
        shown = arranged(book, section, orders=orders)
        lines += ["", "## %s" % TITLES[section], ""]
        if not shown.headings:
            lines.append("Nothing yet.")
        for heading, current in shown.headings:
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
                   or _evidence_problem(book, item["section"], item.get("replaces"), item.get("evidence"))
                   or owner_replacement_problem(book, item["section"], item.get("replaces"), item.get("text"), item.get("reason")))
        if problem is not None:
            problems.append("passage %d (%s, %s) %s" % (index, TITLES[item["section"]], _one_line(item.get("heading")), problem))
    for index, item in enumerate(findings, start=1):
        problem = (check_replaces(book, RESULTS, item.get("replaces"))
                   or (None if item.get("negative") else _evidence_problem(book, RESULTS, item.get("replaces"), item.get("evidence")))
                   or (None if item.get("negative") else owner_replacement_problem(book, RESULTS, item.get("replaces"), item.get("text"),
                                                                                    item.get("reason"), finding=True)))
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
        self.places = {}     # heading -> supplement or cut, for a heading the outline placed there (`arranged`)

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
    """A finding as Results prints it: the general report's own reading (`provenance.finding_text`), so the two agree."""
    from wayline import provenance  # the provenance module pulls in the gates and the report
    return provenance.finding_text(item, manifest)


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


def is_finding(item):
    """Whether a Results item is a finding (from `findings.jsonl`), as against a passage someone contributed."""
    return "by" not in (item or {})


def _shown(book, section, items):
    """One section's log as it renders: in Results, each finding under its result's current heading (ticket 90), so a
    merged or renamed result renders as one heading and a scope-down stays where what it narrows stood."""
    if section != RESULTS:
        return items
    headings = results.result_headings(book)
    return [dict(item, heading=headings[item.get("id")]) if is_finding(item) and item.get("id") in headings else item
            for item in items]


def arranged(project_or_ledger, section, ordered=True, orders=None):
    """One section as it renders now: `arrange` over its log, each finding under its result's current heading. With
    `ordered`, the headings follow the outline (ticket 104): the main text in its order, a heading the outline does not
    show after those in first-appearance order, then the headings placed under Supplement and Cut, each in `places`.
    `orders` is a dict a caller arranging several sections passes to each, so the outline is read once for them all."""
    book = ledger_for(project_or_ledger)
    found = arrange(_shown(book, section, _items(book, section)))
    if ordered:
        _order(book, section, found, orders)
    return found


def _order(book, section, found, orders=None):
    """Reorder `found.headings` by the outline's `section_orders`, read into `orders` when it does not hold them yet; a
    section the outline cannot be read for keeps its order."""
    if section not in OUTLINED:
        return
    orders = {} if orders is None else orders
    if "sections" not in orders:
        from wayline import outline  # the outline reads every section, unordered
        try:
            orders["sections"] = outline.section_orders(book)
        except (LedgerError, OSError, ValueError):
            orders["sections"] = {}
    if section not in orders["sections"]:
        return
    main, placed = orders["sections"][section]
    rank = {heading: index for index, heading in enumerate(main)}
    places = dict(placed)
    tail = {heading: index for index, (heading, _) in enumerate(placed)}
    first = [(index, pair) for index, pair in enumerate(found.headings) if pair[0] not in places]
    first.sort(key=lambda entry: (rank.get(entry[1][0], len(rank)), entry[0]))
    last = sorted((pair for pair in found.headings if pair[0] in places), key=lambda pair: tail[pair[0]])
    found.headings = [pair for _, pair in first] + last
    found.places = {heading: places[heading] for heading, _ in last}


def _groups(book, section, items, ordered=False, orders=None):
    """What a render prints of `items`, one section's log: `(arranged, [(heading, ids, text)])`, a paragraph each.

    With `ordered` the headings follow the outline (`arranged`), as the file prints them."""
    items = _shown(book, section, items)
    arranged = arrange(items)
    if ordered:
        _order(book, section, arranged, orders)
    manifest = None
    if section == RESULTS:
        try:
            manifest = book.read_json("manifest.json")
        except (OSError, ValueError):
            manifest = {"entries": []}
    by_id = {item.get("id"): item for item in items}
    groups = []
    for heading, current in arranged.headings:
        for group in _paragraphs(current, by_id):
            texts = []
            for item in group:
                text = (_finding_text(item, manifest) if section == RESULTS and is_finding(item)
                        else str(item.get("text") or "").strip())
                mark = mark_of(item)
                texts.append("%s %s" % (text, mark) if mark else text)
            groups.append((heading, tuple(str(item.get("id")) for item in group), " ".join(texts)))
    return arranged, groups


def _body(book, section, orders=None):
    """`(body, last, printed)`: the file below its stamp, the last item it saw, and for Methods what the inventory printed."""
    arranged, groups = _groups(book, section, _items(book, section), ordered=True, orders=orders)
    lines = ["# %s" % TITLES[section], ""]
    if not groups:
        lines += [NOTHING_YET, ""]
    heading, place = None, None
    for group_heading, ids, text in groups:
        if group_heading != heading:
            if arranged.places.get(group_heading) != place:
                place = arranged.places.get(group_heading)
                lines += [PLACED_MARKS[place], ""]
            lines += ["## %s" % group_heading, ""]
            heading = group_heading
        lines += ["<!-- wayline:passage %s -->" % " ".join(ids), text, ""]
    printed = None
    if section == "methods":
        from wayline import methods_inventory  # the inventory reads the sections it renders into
        generated, printed = methods_inventory.block(book)
        lines += generated
    if arranged.notes:
        lines += [NOTES, ""]
    for target, ids in arranged.notes:
        lines += ["> Note: %s each replace %s, which they did in the same wave, so both are kept until one replaces the other."
                  % (" and ".join(ids), target), ""]
    return "\n".join(lines).rstrip("\n") + "\n", arranged.last, printed


# --- the owner's edits ----------------------------------------------------------------------------------
#
# The owner may edit a section file instead of telling the session. Before the next render, code takes the edit in
# (`take_in`): the file's body is read against what the render under its first-line stamp printed, which is the
# section's log up to the stamp's `last` id. A marked paragraph whose text or heading changed is the owner's
# replacement of what it printed, a marked paragraph that is gone is a withdrawal of it, and unmarked text is new owner's
# passages under the heading it stands under. A passage that arrived since the stamp is not in the file, so it is never
# read as a deletion; nor is one replaced since, whose place the newer passage now holds.


def _edited(body):
    """A section file's body as `[(heading, ids or None, text)]`, one paragraph each, read up to code's notes."""
    blocks, state = [], {"heading": None, "ids": None, "lines": []}

    def flush():
        if state["lines"]:
            blocks.append((state["heading"], state["ids"], "\n".join(state["lines"]).strip()))
        elif state["ids"] is not None:
            blocks.append((state["heading"], state["ids"], ""))  # a mark left with its text deleted
        state["ids"], state["lines"] = None, []

    for raw in body.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped in (NOTES, INVENTORY):
            break
        mark = _PASSAGE_MARK.match(stripped)
        if _PLACED_MARK.match(stripped):
            flush()  # the outline's marker before what it placed under Supplement or Cut: code's, never the owner's text
        elif mark:
            flush()
            state["ids"] = tuple(mark.group(1).split())
        elif line.startswith("## "):
            flush()
            state["heading"] = _one_line(line[3:]) or None
        elif line.startswith("# ") and state["heading"] is None and not blocks and not state["lines"]:
            continue  # the section's title
        elif not stripped:
            if state["lines"]:
                flush()
        elif stripped != NOTHING_YET:
            state["lines"].append(line)
    flush()
    return blocks


_RES_RUN = re.compile(r"\{res:[^/{}]*/")


def _comparable(text):
    """A paragraph as an edit is judged by: its words and tags without the render's marks, a `res` tag's run left out,
    since a finding's run is read from the manifest when it renders and may have moved since the file was written."""
    return _one_line(_RES_RUN.sub("{res:", _RENDER_MARK.sub("", str(text or ""))))


def _merge_split(blocks, printed):
    """A printed paragraph holding a blank line reads back as its marked first part and unmarked rest: rejoin them."""
    merged, index = [], 0
    while index < len(blocks):
        heading, ids, text = blocks[index]
        index += 1
        old = printed.get(ids) if ids else None
        if old is not None and _comparable(text) != _comparable(old[1]):
            joined, step = text, index
            while step < len(blocks) and blocks[step][1] is None and blocks[step][0] == heading \
                    and _comparable(old[1]).startswith(_comparable(joined + " " + blocks[step][2])):
                joined, step = joined + "\n\n" + blocks[step][2], step + 1
                if _comparable(joined) == _comparable(old[1]):
                    text, index = joined, step
                    break
        merged.append((heading, ids, text))
    return merged


def take_in(project_or_ledger, section):
    """Take the owner's edit of `research/sections/<section>.md` in, before it renders: the passages written, by `owner`.

    Nothing is taken in from a file whose body still matches its stamp's digest, or that has no stamp. Each change is a
    passage through `add_passage`, journaled `passage` like any other.
    """
    book = ledger_for(project_or_ledger)
    with book.lock():
        stamp = read_stamp(book, section)
        try:
            text = (book.research / section_path(section)).read_text(encoding="utf-8")
        except OSError:
            return []
        body = text.partition("\n")[2]
        if stamp is None or hashlib.sha256(body.encode("utf-8")).hexdigest() == stamp.get("sha256"):
            return []
        items = _items(book, section)
        ids = [item.get("id") for item in items]
        last = stamp.get("last")
        seen_then = items[:ids.index(last) + 1] if last in ids else ([] if last is None else items)
        _, groups = _groups(book, section, seen_then)
        printed = {group_ids: (heading, group_text) for heading, group_ids, group_text in groups}
        by_id = {item.get("id"): item for item in items}
        current = {item.get("id") for item in arrange(items).current()}
        written, kept = [], set()

        def add(heading, words, **fields):
            written.append(add_passage(book, section, heading, words, by=OWNER, render=False, **fields))

        def withdraw(identifier):
            item = by_id[identifier]
            add(_one_line(item.get("heading")) or "Findings", str(item.get("text") or "").strip(), replaces=identifier, withdrawn=True)

        for heading, group_ids, words in _merge_split(_edited(body), printed):
            heading = heading or OWNER_HEADING
            words = _RENDER_MARK.sub("", words).strip()
            if group_ids in printed and group_ids not in kept and words:
                kept.add(group_ids)
                old_heading, old_text = printed[group_ids]
                if heading == old_heading and _comparable(words) == _comparable(old_text):
                    continue
                first, rest = group_ids[0], group_ids[1:]
                if first in current:
                    add(heading, words, replaces=first)
                else:
                    add(heading, words)  # what it printed was replaced since: the owner's text stands beside the newer word
                for identifier in rest:
                    if identifier in current:
                        withdraw(identifier)
            elif words:
                add(heading, words)
        for group_ids in printed:
            if group_ids not in kept:
                for identifier in group_ids:
                    if identifier in current:
                        withdraw(identifier)
        if section == "methods":
            # A reason the owner edited in the parameter table is the owner's passage for that row (ticket 108).
            from wayline import methods_inventory  # the inventory reads the sections it renders into
            for key, reason in methods_inventory.taken_reasons(body, stamp.get("parameters") or {}):
                try:
                    add(methods_inventory.PARAMETERS, reason, parameter=key)
                except SectionError:
                    continue  # a row no key can name is left as code prints it, never a render that fails
        return written


def lint_section(project_or_ledger, section, resolver=None):
    """The linter over a section's current passages, as a render records it: `{problems, listed, unclassified}`.

    The classes are the cache's (a render launches no classifier), so a sentence it has not classified is counted and
    neither failed nor listed. Before the paper order an untagged claim in an owner's passage and a claim tagged only
    `doc` are listed, never failed; a `code` tag resolves against `main`.
    """
    from wayline import provenance  # the provenance module pulls in the gates and the report
    book = ledger_for(project_or_ledger)
    current = arrange(_items(book, section)).current()
    linted = provenance.lint_passages(book.project, current, provenance.read_claims_cache(book), resolver=resolver)
    listed = [item for item in linted.listed if item["problem"] != provenance.UNCLASSIFIED]
    return {"problems": linted.problems, "listed": listed, "unclassified": linted.unclassified}


def _record_lint(book, section, resolver=None):
    """Keep the linter's reading of `section` in `research/sections/lint.json`, written only when it changed."""
    reading = lint_section(book, section, resolver)
    try:
        record = book.read_json(LINT)
    except (OSError, ValueError):
        record = None
    record = record if isinstance(record, dict) and isinstance(record.get("sections"), dict) else {"sections": {}}
    if record["sections"].get(section) == reading:
        return reading
    record["sections"][section] = reading
    book.write_json(LINT, record)
    return reading


def render_section(project_or_ledger, section, resolver=None, orders=None):
    """Write `research/sections/<section>.md` from its log; a body that did not change keeps its file and its stamp.

    The owner's edit of the file is taken in first (`take_in`), and the linter's reading of the section is recorded
    at every render (`lint_section`). `orders` is the outline's reading a pass rendering several sections shares
    (`arranged`); an edit taken in here clears it, since the headings it read have changed. Returns whether the file
    was written.
    """
    book = ledger_for(project_or_ledger)
    if section not in SECTIONS:
        raise SectionError("there is no section %r; the sections are %s" % (section, ", ".join(SECTIONS)))
    with book.lock():
        if take_in(book, section) and orders is not None:
            orders.clear()
        _record_lint(book, section, resolver)
        body, last, printed = _body(book, section, orders)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        stamp = read_stamp(book, section)
        if stamp is not None and stamp.get("sha256") == digest and stamp.get("last") == last \
                and stamp.get("parameters") == (printed or None):
            return False
        record = {"section": section, "rendered_at": now_ts(), "last": last, "sha256": digest}
        if printed:
            record["parameters"] = printed  # each row's reason as printed, so an edit of one is told from a newer reason
        book.write_markdown(section_path(section), "<!-- wayline:render %s -->\n%s" % (json.dumps(record, ensure_ascii=False), body))
    return True


def render_sections(project_or_ledger, only=None):
    """Render every section (or those in `only`); returns the ones written.

    One resolver serves the linter on all of them, so the manifest, the dossiers' index, and `main` are read once, and
    the outline's order of their headings is read once too.
    """
    from wayline import provenance  # the provenance module pulls in the gates and the report
    book = ledger_for(project_or_ledger)
    with book.lock():
        resolver = provenance.resolver_for(book.project)
        orders = {}  # the outline, read once for every section unless an edit taken in changes the headings
        return [section for section in (only or SECTIONS) if render_section(book, section, resolver, orders)]


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


# --- the owner's passage: `wayline passage add` -----------------------------------------------------------


def add_owners_passage(project_or_ledger, section, heading, text, replaces=None, parameter=None):
    """One owner's passage, `by: owner`, through the ledger call, journaled `passage` and rendered (decision 17; ticket 88).

    The conversation calls it, asking the owner only when the section or the place is unclear. The owner's passages
    steer later work with no lock, and the owner replaces any passage without a reason. With `parameter` it is the
    owner's reason for one row of Methods' parameter table (ticket 108).
    """
    if section not in SECTIONS:
        raise SectionError("there is no section %r; the sections are %s" % (section, ", ".join(SECTIONS)))
    return add_passage(project_or_ledger, section, heading, text, by=OWNER, replaces=replaces, parameter=parameter)


def passage_command(args):
    """`wayline passage add --section <s> --heading <h> [--replaces <id>] [--parameter <method>:<name>[@<path>]] "<text>"
    [--project <path>]`."""
    import argparse
    import sys
    from wayline.cli import parse_args
    from wayline.project import ProjectError, find_project  # the project module lays the sections out at init

    parser = argparse.ArgumentParser(prog="wayline passage", description="record an owner's passage in one of the paper's five sections")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="record an owner's passage, by: owner, journaled as passage")
    add.add_argument("text", help="the passage: Markdown with LaTeX math, a claim sentence ending with its provenance tag")
    add.add_argument("--section", required=True, help="one of %s" % ", ".join(SECTIONS))
    add.add_argument("--heading", required=True, help="the heading it stands under; an existing one when it fits")
    add.add_argument("--replaces", help="the id of the passage (or finding) it replaces, which leaves the section and stays in the log")
    add.add_argument("--parameter", help="the row of Methods' parameter table this is the reason for, <method>:<name>, "
                                         "with @<path> for one file only; the table shows it in place of the ticket's reason")
    add.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        record = add_owners_passage(find_project(options.project), options.section, options.heading, options.text,
                                    replaces=options.replaces, parameter=options.parameter)
    except SectionError as failure:
        print("wayline passage: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError) as failure:
        print("wayline passage: %s" % failure, file=sys.stderr)
        return 1
    print("%s  %s, %s%s" % (record["id"], TITLES[record["section"]], record["heading"],
                           "  (replaces %s)" % record["replaces"] if record["replaces"] else ""))
    return 0
