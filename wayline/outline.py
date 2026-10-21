"""The outline: the proposed shape of the paper (Implementation Decision 17; ticket 104).

**Built by code.** `research/OUTLINE.md` is rendered by code alone, with no model tokens, at every render: in the same
pass as the general report and the account (`provenance.render_report`), at the end of every wave, at `init`, and after
every change the owner makes. It reads the objectives, the results, every section's headings, the concerns, the
inherited passages and the objectives that check them, the headline plots, and the venue once one is named. In order:

1. **Storyline**: the objectives in outline order, each with its status, its results and their standing, and its answer.
2. **Gaps**: what the outline names that holds nothing yet (an objective with no result, a heading with no passage, a
   section with nothing in it, a Methods method with no code behind it, ticket 108). An empty main-text Gaps list is the
   paper order's test of complete.
3. **Introduction**: its headings, then the objectives as the paper's questions.
4. **Results**: one subsection per open or answered objective, the critic's `first` leading, then by id; each result
   with its id, heading, standing, findings and headline plots counted, its concerns, the inherited claims it decides,
   the contradictions it resolves, and its measure. A result serving two objectives sits under the first, with a
   pointer from the second. Then "Beyond the objectives" and "Inherited, checked by no objective".
5. **Discussion**: its headings (each answered objective's passage among them), the owner's, and the parked
   objectives as future work.
6. **Methods**: its headings, then the parameter table the methods inventory generates (ticket 108).
7. **Venue**, once one is named: its `required_structure` mapped to the sections by `check_structure`'s word matching,
   the parts no section feeds listed as made at the order.
8. **Supplement** and **Cut**: what the owner (or the decider) placed there.
9. **Proposed, not settled**: merges of results whose headings sit close under one objective (the local embedding
   model, `propose_merges`), inherited headings no objective checks, and new Results subsections the owner added.
10. **For the order**: the concerns kept for the paper order.

No figures: each result lists its headline plots by id.

**Lines.** Every movable line names its item by an id or a heading's text, so code reads a moved line back without
guessing: `R3` a result, `O2` an objective (its `### O2` subsection in Results), and a heading as `<section>:<text>`
(`introduction:State of the art`, `results:Old SINDy cases` for an inherited Results heading). Lines sit in groups:
`introduction`, `discussion`, `methods`, `results:O2` per objective subsection, `results:beyond`, `results:inherited`,
`supplement`, `cut`, and `objectives` (the order of the subsections).

**The owner's changes.** The owner changes the outline by talking (the conversation calls `wayline outline`: `move`,
`place`, `note`, `heading`) or by editing the file: moving lines, placing one under Supplement or Cut, adding a `Note:`
line under one, or adding a heading to Introduction, Discussion, or Methods. Code takes the edit in before the next
render (`take_in`), reading the file against the layout its first-line render stamp says it printed, so a line that
arrived since is never read as removed. `research/outline.json` (schema `outline`), written only here through the
ledger and journaled as `outline`, holds only what the owner set (or the decider, settling for the owner), and it
always wins:

- a group the owner ordered keeps its order: code never moves a placed line, and lines that arrive later go after the
  placed ones, marked new;
- a placed line whose item is gone (merged, withdrawn, its objective dropped) is listed once, under "Gone since you
  placed them", and its placement dropped (`by: code`); the list clears at the owner's next change;
- a note follows its item through a merge (onto the result it went into) and a reframe (onto the successor), and a
  reframed objective's successor takes its place and its subsection's placements.

Renaming or merging a result changes the result (`wayline result`), not the outline; a new Results subsection is a new
question, which the outline lists as one to open as an objective.

**What follows it before the order.** The sections render their headings in the outline's order, and a heading placed
under Supplement or Cut still renders, at the end of its section under a marker (`section_order`). A worker's context
pack gains its objectives' outline entries with the owner's notes (`pack_text`), and a consolidation reads the section
in the outline's order with its notes (`heading_notes`).

**Merges.** `propose_merges` runs the harness's embedding model (BAAI/bge-base-en-v1.5, through the tool runner, no
tokens) over the headings of the results under each objective, and each pair at or above `SIMILARITY` not proposed
before becomes an item of an `outline_proposals` batch (ticket 79), marks take or decline, default decline: nothing
merges on its own. `take_marks` merges each pair taken (the later result into the earlier), by whoever marked it.
"""

import argparse
import hashlib
import json
import re
import sys

from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import K_ACTION, K_BY, K_ITEM, K_NOTE, K_TO, OUTLINE, PAYLOAD_ENUMS, LedgerError, ledger_for, now_ts

__all__ = [
    "OUTLINE_MD", "OUTLINE_JSON", "SCHEMA", "SIMILARITY", "BATCH_KIND", "OutlineError", "read_record", "render_outline",
    "take_in", "move", "place", "note", "add_heading", "section_order", "section_orders", "heading_notes", "pack_text", "propose_merges",
    "take_marks", "open_proposals", "outline_command", "heading_key",
]

OUTLINE_MD = "OUTLINE.md"
OUTLINE_JSON = "outline.json"
SCHEMA = "outline"
BATCH_KIND = "outline_proposals"
TAKE, DECLINE = "take", "decline"
# Two results' headings under one objective whose embeddings' cosine reaches this sit close enough to propose merging.
# BAAI/bge-base-en-v1.5 puts unrelated short headings near 0.5 and two wordings of one question near 0.9.
SIMILARITY = 0.85
MERGES_CACHE = ".cache/outline_merges.json"  # which headings the last check embedded, so an unchanged set is not run again

ACTIONS = PAYLOAD_ENUMS[(OUTLINE, K_ACTION)]
MOVED, PLACED, NOTED, ADDED, GONE = ACTIONS
BY = PAYLOAD_ENUMS[(OUTLINE, K_BY)]
OWNER, DECIDER, CODE = "owner", "decider", "code"

INTRODUCTION, RESULTS, DISCUSSION, METHODS = "introduction", "results", "discussion", "methods"
SECTIONS = (INTRODUCTION, RESULTS, DISCUSSION, METHODS)
TITLES = {INTRODUCTION: "Introduction", RESULTS: "Results", DISCUSSION: "Discussion", METHODS: "Methods"}
HEADED = (INTRODUCTION, DISCUSSION, METHODS)  # the sections the owner may add a heading to
OBJECTIVES = "objectives"
BEYOND = "results:beyond"
INHERITED = "results:inherited"
SUPPLEMENT, CUT, MAIN = "supplement", "cut", "main"
PLACES = (SUPPLEMENT, CUT)
SUBSECTION = ("open", "answered")  # the objectives with a Results subsection; the parked are future work

STAMP_RE = re.compile(r"^<!-- wayline:render (\{.*\}) -->$")
_RESULT = re.compile(r"^R[1-9][0-9]*$")
_OBJECTIVE = re.compile(r"^O[1-9][0-9]*$")
_ITEM = re.compile(r"^[-*+]\s+(.*\S)\s*$")
_NOTE = re.compile(r"^\s*(?:[-*+]\s+)?note:\s*(.*?)\s*$", re.IGNORECASE)
_LEAD_ID = re.compile(r"^((?:R|O)[1-9][0-9]*)\b")
_CLOSE = r'"(?=\s*(?:\(|:|$))'  # a heading's closing quote: the last one before its annotation, so a quote inside it stays
_QUOTED = re.compile(r'^"(.+)' + _CLOSE)
_SECTION_QUOTED = re.compile(r'^(Introduction|Results|Discussion|Methods):\s*"(.+)' + _CLOSE)
_INHERITED_LINE = re.compile(r'^Inherited\s+"(.+)' + _CLOSE)
_NEW = " (new)"

HEADER = ("Code builds this outline of the paper at every render, from the objectives, the results, the sections' "
          "headings, the concerns, and the inherited passages; no model writes it. Change it by talking, or edit this "
          "file: move a line, put it under Supplement or Cut, add a `Note:` line under it, or add a heading to "
          "Introduction, Discussion, or Methods. What you set is kept in `outline.json` and always wins; a line marked "
          "(new) arrived after you ordered its part. No figures: each result lists its headline plots by id.")
NOTHING = "Nothing yet."
NOTHING_PLACED = "Nothing placed here."


class OutlineError(LedgerError):
    """A change the outline refuses: an item it does not show, a group the item cannot go to, an empty heading."""


def _one_line(text):
    return " ".join(str(text or "").split())


def heading_key(section, heading):
    """The key of a heading line: `<section>:<heading>`."""
    return "%s:%s" % (section, _one_line(heading))


def _split_key(key):
    """`(section, heading)` of a heading key, or None for an objective's or a result's id."""
    section, colon, heading = str(key).partition(":")
    return (section, heading) if colon and section in SECTIONS and heading else None


def _id_number(identifier):
    found = re.match(r"^[A-Z]([1-9][0-9]*)$", str(identifier or ""))
    return int(found.group(1)) if found else 0


# --- the record -----------------------------------------------------------------------------------------------


def _empty():
    return {"groups": {}, "notes": {}, "added": [], "gone": []}


def read_record(project_or_ledger):
    """`research/outline.json`: what the owner set; empty when nothing was."""
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(OUTLINE_JSON)
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as failure:
        raise OutlineError("research/%s cannot be read: %s" % (OUTLINE_JSON, failure)) from None
    try:
        check(record, load_schema(SCHEMA), name="research/%s" % OUTLINE_JSON)
    except ValidationError as failure:
        raise OutlineError(str(failure)) from None
    return record


def _save(book, record, changes, by):
    """Write the record and journal one `outline` event per change, each `(action, item, to, note)`; under the lock."""
    if by not in BY:
        raise OutlineError("an outline change is made by one of %s, got %r" % (", ".join(BY), by))
    book.write_json(OUTLINE_JSON, record, schema=SCHEMA)
    for action, item, to, said in changes:
        payload = {K_ACTION: action, K_ITEM: item}
        if to is not None:
            payload[K_TO] = to
        if action == NOTED:
            payload[K_NOTE] = said
        payload[K_BY] = by
        book.append_event(OUTLINE, payload)


# --- what the outline reads ------------------------------------------------------------------------------------


class _Facts:
    """Everything one render reads, read once. `details` adds what only the file shows (concerns, plots, the venue)."""

    def __init__(self, book, details=True):
        from wayline import results as results_module
        from wayline import sections
        from wayline.objectives import ObjectivesUnreadable, read_objectives
        self.book = book
        try:
            self.objectives = read_objectives(book.project)
        except ObjectivesUnreadable:
            self.objectives = []
        self.by_objective = {item["id"]: item for item in self.objectives}
        self.first = self._first()
        self.clusters = results_module.load(book)
        self.results = results_module.read_results(book)
        self.by_result = {result.id: result for result in self.results}
        result_headings = {result.heading for result in self.results}
        # Every section's current headings in first-appearance order, each with its current items.
        self.headings = {}
        for section in SECTIONS:
            arranged = sections.arranged(book, section, ordered=False)
            self.headings[section] = [(heading, items) for heading, items in arranged.headings
                                      if section != RESULTS or heading not in result_headings]
        self.passages = {item.get("id"): item for item in sections.read_passages(book)}
        self.inherited = {}   # Results heading -> its current inherited claims (unchecked or unverifiable)
        for heading, items in self.headings[RESULTS]:
            claims = [item for item in items if sections.is_inherited(item) and item.get("standing") in sections.STANDINGS]
            if claims:
                self.inherited[heading] = claims
        self.checks = self._checks()
        if details:
            self._details()

    def _first(self):
        """The objective the critic marked `first` in the position memo, followed through reframes; None without one."""
        try:
            memo = self.book.read_json("position.json")
        except (OSError, ValueError):
            return None
        for row in (memo or {}).get("objectives") or []:
            if isinstance(row, dict) and row.get("first"):
                return self.successor(row.get("id"))
        return None

    def successor(self, identifier):
        """The objective that stands where `identifier` stood: itself, or the end of its chain of reframes."""
        seen = set()
        while identifier in self.by_objective and identifier not in seen:
            seen.add(identifier)
            item = self.by_objective[identifier]
            if item.get("status") != "reframed" or not item.get("reframed_as"):
                break
            identifier = item["reframed_as"]
        return identifier

    def status(self, identifier):
        return (self.by_objective.get(identifier) or {}).get("status")

    def _checks(self):
        """`{inherited heading: [objectives]}`: the objectives that check each inherited heading, through the concerns
        tied to them and the verification objective while it is pursued."""
        from wayline import verification
        try:
            ties = verification.ties(self.book.project)
        except (verification.VerificationUnreadable, ValueError, OSError):
            ties = {}
        checking = next((item for item in self.objectives
                         if _one_line(item.get("text")).casefold() == verification.OBJECTIVE.casefold()), None)
        found = {}
        for heading in self.inherited:
            named = set(ties.get(heading) or ())
            if checking is not None and checking.get("status") in SUBSECTION:
                named.add(checking["id"])
            found[heading] = sorted({self.successor(identifier) for identifier in named}, key=_id_number)
        return found

    def _details(self):
        from wayline import concerns, repeats
        try:
            self.concerns = concerns.read_concerns(self.book)
        except concerns.ConcernsUnreadable:
            self.concerns = []
        try:
            self.contradictions = repeats.contradictions(self.book)
        except repeats.RepeatsError:
            self.contradictions = []
        try:
            plots = self.book.read_json("plots.json")
        except (OSError, ValueError):
            plots = {}
        self.plots = [item for item in (plots or {}).get("plots") or [] if isinstance(item, dict)]
        self.venue = self._venue()
        # The methods inventory (ticket 108): the Methods methods with no code behind them, and the parameter table's rows.
        from wayline import methods_inventory
        passages = [item for _, items in self.headings[METHODS] for item in items]
        try:
            self.no_code = methods_inventory.no_code(self.book, passages)
            self.parameters = len(methods_inventory.parameter_rows(self.book))
        except (OSError, ValueError):
            self.no_code, self.parameters = [], 0

    def _venue(self):
        """`(slug, guidelines)` of the venue last named (the paper order's), or None while none is."""
        from wayline import HARNESS_ROOT, guidelines
        from wayline.ledger import PAPER_STARTED
        events, _ = self.book.read_events()
        slug = next((event["payload"].get("venue") for event in reversed(events)
                     if event.get("event") == PAPER_STARTED and (event.get("payload") or {}).get("venue")), None)
        if not slug:
            return None
        try:
            return slug, guidelines.read_guidelines(HARNESS_ROOT, slug)
        except (guidelines.GuidelinesError, ValidationError, OSError, ValueError):
            return slug, None

    # --- per-result readings, for the file ---

    def decided(self, result):
        """`[(claim id, evidence)]`: the inherited claims a result's findings replaced."""
        from wayline import sections
        found = []
        for finding in result.findings:
            target = self.passages.get(finding.get("replaces"))
            if target is not None and sections.is_inherited(target) and target.get("standing") in sections.STANDINGS:
                found.append((target["id"], finding.get("evidence")))
        return found

    def headline_plots(self, result):
        return [str(item.get("id")) for item in self.plots
                if item.get("result") == result.id and item.get("headline") and item.get("status") != "retired"]


# --- the layout -------------------------------------------------------------------------------------------------


class _Layout:
    """Where each line goes in one render: the objectives' order, each group's keys, the new lines, the gone placements,
    the notes shown, and the pointers from an objective to a result it shares with an earlier one."""

    def __init__(self):
        self.order = []          # the objectives with a Results subsection, in outline order
        self.groups = {}         # group -> [key], every group of `_group_names(order)`
        self.new = set()         # keys after the placed lines of a group the owner ordered
        self.gone = []           # [(group, key, why)]: placements whose item is gone, found by this render
        self.notes = {}          # key -> the note shown under its line
        self.pointers = {}       # objective -> [(result, where it sits)]
        self.where = {}          # key -> group

    def keys(self):
        return [key for group in self.groups.values() for key in group]


def _group_names(order):
    return ([INTRODUCTION] + ["results:%s" % identifier for identifier in order] + [BEYOND, INHERITED, DISCUSSION, METHODS]
            + list(PLACES))


def _objective_of(group):
    return group.split(":", 1)[1] if group.startswith("results:O") else None


def _result_group(result, facts, order):
    """The subsection a result sits under by code: the first of its objectives in outline order, else Beyond."""
    served = {facts.successor(identifier) for identifier in result.objectives}
    for identifier in order:
        if identifier in served:
            return "results:%s" % identifier
    return BEYOND


def _defaults(facts, record, order):
    """Code's own place for every line under the objectives' `order`: `{group: [keys]}`."""
    groups = {group: [] for group in _group_names(order)}
    for result in facts.results:  # in id order, the order results first appeared
        groups[_result_group(result, facts, order)].append(result.id)
    for heading in facts.inherited:
        checked = [identifier for identifier in order if identifier in facts.checks.get(heading, ())]
        groups["results:%s" % checked[0] if checked else INHERITED].append(heading_key(RESULTS, heading))
    for heading, _ in facts.headings[RESULTS]:
        if heading not in facts.inherited:
            groups[BEYOND].append(heading_key(RESULTS, heading))
    for section in HEADED:
        keys = [heading_key(section, heading) for heading, _ in facts.headings[section]]
        keys += [heading_key(section, item["heading"]) for item in record.get("added") or []
                 if item.get("section") == section and heading_key(section, item["heading"]) not in keys]
        groups[section] = keys
    return groups


def _gone_reason(key, facts):
    if _RESULT.match(key):
        live = facts.clusters.resolve(key)
        if live != key and live in facts.by_result:
            return "merged into %s" % live
        return "no finding of it stands now"
    if _OBJECTIVE.match(key):
        return "it was %s" % (facts.status(key) or "removed")
    split = _split_key(key)
    return "%s no longer holds it" % TITLES[split[0]] if split else "it is gone"


def _layout(facts, record):
    """One render's layout: code's defaults with the owner's placements laid over them (the module's docstring)."""
    layout = _Layout()
    subsections = [item["id"] for item in facts.objectives if item.get("status") in SUBSECTION]
    default_order = sorted(subsections, key=lambda identifier: (identifier != facts.first, _id_number(identifier)))
    groups = record.get("groups") or {}
    owned_order = []
    for key in groups.get(OBJECTIVES) or []:
        successor = facts.successor(key)
        status = facts.status(successor)
        if status in SUBSECTION:
            if successor not in owned_order:
                owned_order.append(successor)
        elif status != "parked":  # a parked objective's place waits for it to be pursued again
            layout.gone.append((OBJECTIVES, key, _gone_reason(successor, facts)))
    layout.order = owned_order + [identifier for identifier in default_order if identifier not in owned_order]
    if OBJECTIVES in groups:
        layout.new.update(identifier for identifier in default_order if identifier not in owned_order)
    defaults = _defaults(facts, record, layout.order)
    shown = {key for group in defaults.values() for key in group}
    placed, owned = {}, {}
    for group, keys in groups.items():
        if group == OBJECTIVES:
            continue
        objective = _objective_of(group)
        target = "results:%s" % facts.successor(objective) if objective else group
        status = facts.status(facts.successor(objective)) if objective else None
        if objective and status not in SUBSECTION:
            if status != "parked":
                layout.gone.extend((group, key, "its objective %s was %s" % (objective, status or "removed")) for key in keys)
            continue
        for key in keys:
            if key in placed:
                continue
            if key not in shown:
                layout.gone.append((group, key, _gone_reason(key, facts)))
                continue
            placed[key] = target
            owned.setdefault(target, []).append(key)
    for group in _group_names(layout.order):
        theirs = [key for key in defaults.get(group, []) if key not in placed]
        layout.groups[group] = owned.get(group, []) + theirs
        if group in owned:
            layout.new.update(theirs)
        for key in layout.groups[group]:
            layout.where[key] = group
    layout.notes = _notes_shown(facts, record, layout)
    for result in facts.results:
        group = layout.where.get(result.id)
        for identifier in dict.fromkeys(facts.successor(name) for name in result.objectives):
            if identifier in layout.order and group != "results:%s" % identifier:
                layout.pointers.setdefault(identifier, []).append((result.id, _objective_of(group or "") or _place_name(group)))
    return layout


def _place_name(group):
    return {BEYOND: "Beyond the objectives", INHERITED: "Inherited, checked by no objective", SUPPLEMENT: "Supplement",
            CUT: "Cut"}.get(group, group)


def _note_target(key, facts):
    """The line a note on `key` shows under: the result a merged one went into, a reframed objective's successor."""
    if _RESULT.match(key):
        return facts.clusters.resolve(key)
    if _OBJECTIVE.match(key):
        return facts.successor(key)
    return key


def _notes_shown(facts, record, layout):
    """The note under each line: its own, then those of the items merged or reframed into it, which a note follows."""
    shown = {}
    for key, text in sorted((record.get("notes") or {}).items(), key=lambda pair: (_note_target(pair[0], facts) != pair[0], pair[0])):
        target = _note_target(key, facts)
        if target in layout.where or target in layout.order:  # a parked objective's note waits, unprinted, for its subsection
            shown.setdefault(target, []).append(_one_line(text))
    return {key: " ".join(texts) for key, texts in shown.items()}


def _sources(key, facts, record):
    """The keys of the record whose notes show under `key`: its own, and what was merged or reframed into it."""
    return [item for item in (record.get("notes") or {}) if _note_target(item, facts) == key]


# --- the file -----------------------------------------------------------------------------------------------------


def _plural(count, word, plural=None):
    return "%d %s" % (count, word if count == 1 else (plural or word + "s"))


def _measure(objective):
    """A goal's measure in a few words: "`rmse` down to 0.1"; "none" for an objective without one."""
    measure = (objective or {}).get("measure")
    if not measure:
        return "none"
    words = "`%s` %s" % (measure.get("metric"), "down" if measure.get("direction") == "down" else "up")
    if measure.get("target") is not None:
        words += " to %g" % measure["target"]
    return words


def _heading_line(facts, section, heading, record):
    """`"<heading>" (n passages)`, with who wrote it where that matters."""
    from wayline import sections
    items = dict(facts.headings[section]).get(heading, [])
    if not items:
        return '"%s" (yours; nothing yet)' % heading if any(
            item.get("section") == section and item.get("heading") == heading for item in record.get("added") or []) else \
            '"%s" (nothing yet)' % heading
    words = [_plural(len(items), "passage")]
    answered = sorted({str(item.get("by")).split(":", 1)[1] for item in items if str(item.get("by") or "").startswith("objective:")},
                      key=_id_number)
    if answered:
        words.append("answers %s" % ", ".join(answered))
    if any(item.get("by") == sections.OWNER for item in items):
        words.append("yours")
    return '"%s" (%s)' % (heading, "; ".join(words))


def _result_line(facts, result, objective):
    decided = facts.decided(result)
    claims = {claim for claim, _ in decided}
    concerns = [item["id"] for item in facts.concerns if claims & set(item.get("targets") or [])]
    resolves = ["%s+%s" % (item["a"], item["b"]) for item in facts.contradictions if {item["a"], item["b"]} & claims]
    plots = facts.headline_plots(result)
    return '%s "%s": %s; %s, %s; concerns %s; decides %s; resolves %s; measure %s' % (
        result.id, result.heading, result.standing, _plural(len(result.current), "finding"),
        "%s (%s)" % (_plural(len(plots), "headline plot"), ", ".join(plots)) if plots else "no headline plot",
        ", ".join(concerns) or "none",
        ", ".join("%s (%s)" % (claim, evidence) if evidence else claim for claim, evidence in decided) or "none",
        ", ".join(resolves) or "none", _measure(objective))


def _inherited_line(facts, heading):
    claims = facts.inherited.get(heading, [])
    standings = sorted({item.get("standing") for item in claims})
    checked = facts.checks.get(heading) or []
    return 'Inherited "%s": %s, %s%s' % (heading, _plural(len(claims), "claim"), " and ".join(standings),
                                         "; checked by %s" % ", ".join(checked) if checked else "")


def _key_line(facts, layout, key, record, objective=None, qualified=False):
    """One movable line's text, after its `- `."""
    if _RESULT.match(key):
        result = facts.by_result[key]
        if objective is None:
            served = [facts.successor(name) for name in result.objectives]
            objective = facts.by_objective.get(served[0]) if served else None
        text = _result_line(facts, result, objective)
    else:
        section, heading = _split_key(key)
        if section == RESULTS and heading in facts.inherited:
            text = _inherited_line(facts, heading)
        else:
            text = _heading_line(facts, section, heading, record)
            if qualified or section == RESULTS:
                text = "%s: %s" % (TITLES[section], text)
    return text + (_NEW if key in layout.new else "")


def _lines_of(facts, layout, group, record, objective=None, qualified=False):
    lines = []
    for key in layout.groups.get(group, []):
        lines.append("- %s" % _key_line(facts, layout, key, record, objective, qualified))
        if layout.notes.get(key):
            lines.append("  Note: %s" % layout.notes[key])
    return lines


def _results_of(facts, objective_id):
    return [result for result in facts.results if objective_id in {facts.successor(name) for name in result.objectives}]


def _storyline(facts, layout):
    lines = []
    parked = [item["id"] for item in facts.objectives if item.get("status") == "parked"]
    for identifier in layout.order + parked:
        objective = facts.by_objective[identifier]
        served = _results_of(facts, identifier)
        said = "%s: %s" % (_plural(len(served), "result"), ", ".join("%s %s" % (result.id, result.standing) for result in served)) \
            if served else "no result yet"
        line = "- %s (%s) %s %s." % (identifier, objective["status"], _one_line(objective["text"]), said)
        if objective["status"] == "parked":
            line += " Future work."
        else:
            line += " Answer: %s" % (_one_line(objective.get("answer")) or "none yet.")
        lines.append(line)  # an objective's note shows once, under its Results subsection
    return lines or ["No objective is recorded yet."]


def _holds(facts, key):
    """Whether a line holds something: a result always does; a heading when a passage stands under it."""
    if _RESULT.match(key):
        return True
    section, heading = _split_key(key)
    if section == RESULTS:
        return heading in facts.inherited or bool(dict(facts.headings[RESULTS]).get(heading))
    return bool(dict(facts.headings[section]).get(heading))


def _gaps(facts, layout, record):
    """`(main, supplement)`: the lines of each that hold nothing yet."""
    main, supplement = [], []
    for identifier in layout.order:
        if not layout.groups.get("results:%s" % identifier):
            main.append("- %s, %s, has no result yet." % (identifier, _one_line(facts.by_objective[identifier]["text"])))
        if facts.status(identifier) == "answered" and not any(
                str(item.get("by")) == "objective:%s" % identifier for _, items in facts.headings[DISCUSSION] for item in items):
            main.append("- %s is answered and its Discussion passage is not written yet." % identifier)
    for section in SECTIONS:
        if section == RESULTS:
            held = facts.results or facts.headings[RESULTS]
        else:
            held = facts.headings[section]
        if not held:
            main.append("- %s holds no passage yet." % TITLES[section])
    for group in [INTRODUCTION, DISCUSSION, METHODS] + list(PLACES):
        for key in layout.groups.get(group, []):
            if not _holds(facts, key):
                section, heading = _split_key(key)
                said = '- %s: "%s" holds no passage yet.' % (TITLES[section], heading)
                if group == SUPPLEMENT:
                    supplement.append(said)
                elif group != CUT:
                    main.append(said)
    # The rule from Methods to code is no gate: a method with no code behind it is a gap, never a failure (ticket 108).
    from wayline import methods_inventory
    main += methods_inventory.gap_lines(facts.no_code)
    return main, supplement


def _venue_lines(facts):
    from wayline import guidelines
    slug, record = facts.venue
    if record is None:
        return ["## Venue: %s" % slug, "", "Its guidelines could not be read, so its structure is not mapped here.", ""]
    lines = ["## Venue: %s" % (record.get("display_name") or slug), "",
             "Its required structure, part by part, and the section that feeds each, by the word matching "
             "`check_structure` uses; a part no section feeds is made at the order.", ""]
    for part in record.get("required_structure") or []:
        fed = [TITLES[section] for section in SECTIONS if guidelines.heading_matches(part, TITLES[section])]
        lines.append("- %s: %s" % (part, ", ".join(fed) if fed else "made at the order"))
    return lines + [""]


def _proposals(facts, layout, record):
    """The lines of "Proposed, not settled": open merges, inherited headings no objective checks, offered objectives."""
    from wayline import batches
    lines = []
    try:
        held = batches.read_batches(facts.book.project, status=batches.OPEN)
    except (batches.BatchError, ValidationError, OSError, ValueError):
        held = []
    for batch in held:
        if batch["kind"] != BATCH_KIND:
            continue
        for item in batch["items"]:
            if item["mark"] is None and _live_pair(facts, item["ref"]):
                lines.append("- %s Batch %s, item %d: take or decline." % (item["text"], batch["id"], item["id"]))
    for heading in facts.inherited:
        if not facts.checks.get(heading):
            lines.append('- Inherited "%s": no objective checks it. Place it under Supplement or Cut, or tie it to an objective.'
                         % heading)
    texts = {_one_line(item["text"]).casefold() for item in facts.objectives}
    for item in record.get("added") or []:
        if item.get("section") == RESULTS and _one_line(item["heading"]).casefold() not in texts:
            lines.append('- A Results subsection you added, "%s", is a new question that needs new work: open it as an objective.'
                         % item["heading"])
    return lines


def _live_pair(facts, ref):
    pair = str(ref).split("+")
    return len(pair) == 2 and all(identifier in facts.by_result for identifier in pair)


def _text(facts, layout, record):
    """OUTLINE.md below its stamp, and the layout it printed (the stamp's), in the module docstring's order."""
    lines = ["# Outline", "", HEADER, "", "## Storyline", ""] + _storyline(facts, layout) + [""]
    main, supplement = _gaps(facts, layout, record)
    lines += ["## Gaps", "", "What the outline names that holds nothing yet; the paper order is complete when the main text's "
              "list is empty.", ""]
    lines += main or ["Nothing: every line of the main text holds something."]
    if supplement:
        lines += ["", "In the supplement:", ""] + supplement
    lines += ["", "## Introduction", ""] + (_lines_of(facts, layout, INTRODUCTION, record) or [NOTHING])
    questions = ["- %s %s" % (identifier, _one_line(facts.by_objective[identifier]["text"])) for identifier in layout.order]
    lines += ["", "### The paper's questions", ""] + (questions or [NOTHING]) + ["", "## Results", ""]
    for identifier in layout.order:
        objective = facts.by_objective[identifier]
        group = "results:%s" % identifier
        tied = [item["id"] for item in facts.concerns if item.get("place") == "objectives" and identifier in (item.get("objectives") or [])]
        lines += ["### %s %s%s" % (identifier, _one_line(objective["text"]), _NEW if identifier in layout.new else ""), ""]
        about = "%s; measure %s; answers %s." % (objective["status"].capitalize(), _measure(objective), ", ".join(tied) or "no concern")
        if objective.get("answer"):
            about += " Answer: %s" % _one_line(objective["answer"])
        lines += [about, ""]
        if layout.notes.get(identifier):
            lines += ["Note: %s" % layout.notes[identifier], ""]
        body = _lines_of(facts, layout, group, record, objective)
        body += ["- see %s under %s" % pointer for pointer in layout.pointers.get(identifier, [])]
        lines += (body or [NOTHING]) + [""]
    for group, title in ((BEYOND, "Beyond the objectives"), (INHERITED, "Inherited, checked by no objective")):
        lines += ["### %s" % title, ""] + (_lines_of(facts, layout, group, record) or [NOTHING]) + [""]
    lines += ["## Discussion", ""] + (_lines_of(facts, layout, DISCUSSION, record) or [NOTHING])
    future = ["- %s (parked) %s" % (item["id"], _one_line(item["text"])) for item in facts.objectives if item.get("status") == "parked"]
    lines += ["", "### Future work", ""] + (future or ["No objective is parked."])
    lines += ["", "## Methods", ""] + (_lines_of(facts, layout, METHODS, record) or [NOTHING])
    if facts.parameters:
        lines += ["", "- Parameter table: %s, generated at the end of Methods from the tickets' `parameters`; a reason is "
                  "edited in its row." % _plural(facts.parameters, "parameter")]
    lines += [""]
    if facts.venue is not None:
        lines += _venue_lines(facts)
    for group, title in ((SUPPLEMENT, "Supplement"), (CUT, "Cut")):
        lines += ["## %s" % title, ""] + (_lines_of(facts, layout, group, record, qualified=True) or [NOTHING_PLACED]) + [""]
    gone = record.get("gone") or []
    if gone:
        lines += ["## Gone since you placed them", ""]
        lines += ["- %s, placed in %s: %s." % (item["item"], _place_name(item["group"]), item["why"]) for item in gone] + [""]
    lines += ["## Proposed, not settled", ""] + (_proposals(facts, layout, record) or ["Nothing proposed."]) + [""]
    order = [item for item in facts.concerns if item.get("place") == "order" and item.get("status") == "open"]
    lines += ["## For the order", ""]
    lines += ['- %s: "%s" (%s)' % (item["id"], _one_line(item["sources"][0]["text"]), item["sources"][0]["locator"]) for item in order] \
        or ["No concern is kept for the order."]
    printed = {"order": list(layout.order), "groups": {group: list(keys) for group, keys in layout.groups.items() if keys},
               "notes": dict(layout.notes)}
    return "\n".join(lines).rstrip("\n") + "\n", printed


def read_stamp(project_or_ledger):
    """The render stamp on OUTLINE.md's first line, or None when the file or its stamp is missing."""
    path = ledger_for(project_or_ledger).research / OUTLINE_MD
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


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _drop_gone(book, record, layout):
    """List each placement whose item is gone once, and drop it, journaled `gone` by code; returns whether it wrote."""
    if not layout.gone:
        return False
    changes = []
    for group, key, why in layout.gone:
        keys = record["groups"].get(group) or []
        if key in keys:
            keys.remove(key)
        if not keys:
            record["groups"].pop(group, None)
        record.setdefault("gone", []).append({"item": key, "group": group, "why": why})
        changes.append((GONE, key, group, None))
    _save(book, record, changes, CODE)
    return True


def _on_disk(book):
    """The body of OUTLINE.md below its stamp as the file holds it now, or None when there is no file."""
    try:
        return (book.research / OUTLINE_MD).read_text(encoding="utf-8").partition("\n")[2]
    except OSError:
        return None


def _write(book, facts=None):
    """Write OUTLINE.md from the ledger as it is now; returns whether the file changed. The caller holds the lock.

    A file whose body is what this render prints, under a stamp that says so, is left; anything else is written again,
    an edit of it that took nothing in included."""
    record = read_record(book)
    facts = facts or _Facts(book)
    layout = _layout(facts, record)
    if _drop_gone(book, record, layout):
        layout = _layout(facts, record)
    body, printed = _text(facts, layout, record)
    digest = _digest(body)
    stamp = read_stamp(book)
    if stamp is not None and stamp.get("sha256") == digest and _on_disk(book) == body:
        return False
    head = {"outline": True, "rendered_at": now_ts(), "sha256": digest, "printed": printed}
    book.write_markdown(OUTLINE_MD, "<!-- wayline:render %s -->\n%s" % (json.dumps(head, ensure_ascii=False), body))
    return True


def render_outline(project_or_ledger):
    """Render `research/OUTLINE.md` by code, taking the owner's edit of it in first; returns whether the file was written."""
    book = ledger_for(project_or_ledger)
    with book.lock():
        taken = take_in(book)
        written = _write(book)
    return bool(taken) or written


# --- the owner's edit of OUTLINE.md ----------------------------------------------------------------------------------
#
# The file is read against the layout its stamp says it printed: a group whose lines now differ from what it printed
# (restricted to the lines still in it) was ordered by the owner, and is kept as the owner left it; a line moved into
# another group goes with it. A line missing from the file is never read as removed, so a line that arrived since the
# stamp, which the file cannot hold, stays where code puts it.

_PARTS = {"Introduction": INTRODUCTION, "Results": RESULTS, "Discussion": DISCUSSION, "Methods": METHODS,
          "Supplement": SUPPLEMENT, "Cut": CUT}


class _Edited:
    def __init__(self):
        self.order = []      # the objectives in the order of their `### O<n>` subsections
        self.groups = {}     # group -> [keys], in the file's order
        self.notes = {}      # key -> [[note lines]], one list per place the key's line stands with a note under it
        self.present = set() # keys shown as a line somewhere a note can stand under
        self.added = []      # (section, heading) the file names and no section holds
        self.offered = []    # Results subsections the owner added: new questions


def _strip_new(text):
    text = _one_line(text)
    return text[:-len(_NEW)] if text.endswith(_NEW) else text


def _heading_by_text(heading, printed, facts):
    """The key of a quoted heading under Supplement or Cut: the one line of that text the file printed or a section holds."""
    keys = [key for keys in (printed.get("groups") or {}).values() for key in keys
            if _split_key(key) and _split_key(key)[1] == heading]
    keys = list(dict.fromkeys(keys)) or [heading_key(section, heading) for section in SECTIONS
                                         if heading in dict(facts.headings[section]) or heading in facts.inherited]
    return keys[0] if len(keys) == 1 else None


def _known_heading(facts, record, section, heading):
    return (heading in dict(facts.headings[section]) or (section == RESULTS and heading in facts.inherited)
            or any(item.get("section") == section and item.get("heading") == heading for item in record.get("added") or []))


def _read_edit(body, facts, printed, record):
    """What an edited OUTLINE.md says, as `_Edited`."""
    edited = _Edited()
    part, group, last, block = None, None, None, None

    def take(key, into):
        edited.present.add(key)
        if into is not None and _fits(key, into) and key not in edited.groups.get(into, []):
            edited.groups.setdefault(into, []).append(key)

    for raw in body.splitlines():
        line = raw.rstrip()
        if not _NOTE.match(line):
            block = None  # a note's lines run on until another line
        if line.startswith("## "):
            part = _PARTS.get(line[3:].strip())
            group = part if part in HEADED + PLACES else None
            last = None
            continue
        if line.startswith("### "):
            title = _strip_new(line[4:])
            last = None
            if part == RESULTS:
                found = _LEAD_ID.match(title)
                if found and _OBJECTIVE.match(found.group(1)):
                    group, last = "results:%s" % found.group(1), found.group(1)
                    if found.group(1) not in edited.order:
                        edited.order.append(found.group(1))
                    edited.present.add(found.group(1))
                elif title == "Beyond the objectives":
                    group = BEYOND
                elif title == "Inherited, checked by no objective":
                    group = INHERITED
                else:
                    group = None
                    edited.offered.append(title)
            elif part in HEADED and title not in ("The paper's questions", "Future work"):
                key = heading_key(part, title)
                take(key, part)
                last = key
                if not _known_heading(facts, record, part, title):
                    edited.added.append((part, title))
            continue
        found = _NOTE.match(line)
        if found and last is not None:
            if found.group(1):
                if block is None:
                    block = []
                    edited.notes.setdefault(last, []).append(block)
                block.append(found.group(1))
            continue
        found = _ITEM.match(line)
        if found is None:
            continue
        content = _strip_new(found.group(1))
        lead = _LEAD_ID.match(content)
        if content.startswith("see "):
            last = None
        elif lead and _OBJECTIVE.match(lead.group(1)):
            last = lead.group(1)
            edited.present.add(last)
        elif group is None:
            last = None  # a line of a part code writes alone: only an objective's line takes a note there
        elif lead:
            last = lead.group(1)
            take(last, group)
        else:
            key = _line_key(content, part, group, printed, facts, record, edited)
            last = key
            if key is not None:
                take(key, group)
    return edited


def _line_key(content, part, group, printed, facts, record, edited):
    """The key of a heading line in `group`, recording a heading the owner added; None for a line it cannot place."""
    found = _INHERITED_LINE.match(content)
    if found:
        return heading_key(RESULTS, found.group(1))
    found = _SECTION_QUOTED.match(content)
    if found:
        section, heading = found.group(1).lower(), _one_line(found.group(2))
    else:
        found = _QUOTED.match(content)
        heading = _one_line(found.group(1)) if found else _one_line(content.strip('"'))
        if group in PLACES:
            return _heading_by_text(heading, printed, facts) if found else None
        section = RESULTS if group.startswith("results:") else part
        if section == RESULTS and not found:
            edited.offered.append(heading)  # a plain line in Results: a new question
            return None
    if section not in SECTIONS or not heading:
        return None
    if not _known_heading(facts, record, section, heading):
        if section not in HEADED:
            return None
        edited.added.append((section, heading))
    return heading_key(section, heading)


def _common(before, after):
    """The longest common subsequence of two key lists, as a set: the lines that kept their relative order.

    Of two swapped lines, the one that now comes first is the one read as moved (moved up)."""
    table = [[0] * (len(after) + 1) for _ in range(len(before) + 1)]
    for i in range(len(before) - 1, -1, -1):
        for j in range(len(after) - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if before[i] == after[j] else max(table[i + 1][j], table[i][j + 1])
    kept, i, j = set(), 0, 0
    while i < len(before) and j < len(after):
        if before[i] == after[j]:
            kept.add(before[i])
            i, j = i + 1, j + 1
        elif table[i][j + 1] >= table[i + 1][j]:
            j += 1
        else:
            i += 1
    return kept


def _pin(record, group, keys):
    """The owner's order of one group: every line in it, taken from any other group it was placed in."""
    groups = record.setdefault("groups", {})
    for other in list(groups):
        if other != group:
            groups[other] = [key for key in groups[other] if key not in keys]
            if not groups[other]:
                del groups[other]
    groups[group] = list(keys)


def _action(key, group, before_group):
    """`placed` when a line crosses between the main text and Supplement or Cut, `moved` otherwise."""
    return PLACED if (group in PLACES) != (before_group in PLACES) else MOVED


def _apply_edit(record, edited, printed, facts):
    """The owner's edit laid over the record; returns the changes, each `(action, item, to, note)`."""
    changes = []
    added = {heading_key(section, heading) for section, heading in edited.added}
    printed_order = [identifier for identifier in printed.get("order") or [] if identifier in edited.order]
    if edited.order and edited.order != printed_order:
        kept = _common(printed_order, edited.order)
        _pin(record, OBJECTIVES, edited.order)
        changes += [(MOVED, identifier, OBJECTIVES, None) for identifier in edited.order if identifier not in kept]
    printed_groups = printed.get("groups") or {}
    printed_where = {key: group for group, keys in printed_groups.items() for key in keys}
    where = {}
    for group, keys in edited.groups.items():
        for key in keys:
            where.setdefault(key, group)
    for group, keys in edited.groups.items():
        keys = [key for key in keys if where[key] == group]
        restricted = [key for key in printed_groups.get(group, []) if where.get(key) == group]
        if keys == restricted:
            continue
        kept = _common(restricted, keys)
        _pin(record, group, keys)
        changes += [(_action(key, group, printed_where.get(key)), key, group, None) for key in keys if key not in kept and key not in added]
    for section, heading in dict.fromkeys(edited.added):
        if not any(item.get("section") == section and item.get("heading") == heading for item in record.get("added") or []):
            record.setdefault("added", []).append({"section": section, "heading": heading})
            changes.append((ADDED, heading_key(section, heading), where.get(heading_key(section, heading), section), None))
    for text in dict.fromkeys(edited.offered):
        if not any(item.get("section") == RESULTS and item.get("heading") == text for item in record.get("added") or []):
            record.setdefault("added", []).append({"section": RESULTS, "heading": text})
            changes.append((ADDED, heading_key(RESULTS, text), RESULTS, None))
    shown = printed.get("notes") or {}
    for key in sorted(edited.present | set(edited.notes)):
        # A line may stand in several places (an objective in the storyline and in Results); the note that changed wins.
        blocks = [_one_line(" ".join(lines)) for lines in edited.notes.get(key, [])]
        changed = [text for text in blocks if text != _one_line(shown.get(key))]
        if blocks and not changed:
            continue
        said = changed[0] if changed else ""
        if said == _one_line(shown.get(key)):
            continue
        _set_note(record, key, said, facts)
        changes.append((NOTED, key, None, said or None))
    return changes


def _set_note(record, key, said, facts):
    notes = record.setdefault("notes", {})
    for source in _sources(key, facts, record):
        notes.pop(source, None)
    if said:
        notes[key] = said


def take_in(project_or_ledger):
    """Take the owner's edit of `research/OUTLINE.md` in, before it renders; returns the changes recorded.

    Nothing is taken from a file whose body still matches its stamp's digest, or that has no stamp. Each change is
    journaled `outline` `by: owner`, the sections render in the new order, and the file is written again.
    """
    from wayline import sections
    book = ledger_for(project_or_ledger)
    with book.lock():
        stamp = read_stamp(book)
        try:
            text = (book.research / OUTLINE_MD).read_text(encoding="utf-8")
        except OSError:
            return []
        body = text.partition("\n")[2]
        if stamp is None or not stamp.get("outline") or _digest(body) == stamp.get("sha256"):
            return []
        facts = _Facts(book, details=False)
        record = read_record(book)
        changes = _apply_edit(record, _read_edit(body, facts, stamp.get("printed") or {}, record), stamp.get("printed") or {}, facts)
        if changes:
            record["gone"] = []
            _save(book, record, changes, OWNER)
            sections.render_sections(book, only=SECTIONS)
        _write(book)
    return changes


# --- the conversation's verb: the same changes as an edit ------------------------------------------------------------


def _group_name(text):
    """A group as the verb names it: `O2` (its Results subsection), `beyond`, `inherited`, a section, `supplement`, `cut`."""
    said = _one_line(text)
    if _OBJECTIVE.match(said):
        return "results:%s" % said
    named = {"beyond": BEYOND, "inherited": INHERITED, "results:beyond": BEYOND, "results:inherited": INHERITED}
    if said.lower() in named:
        return named[said.lower()]
    if said.lower() in HEADED + PLACES or said.startswith("results:O"):
        return said.lower() if not said.startswith("results:") else said
    raise OutlineError("there is no part %r of the outline; name an objective (O2), beyond, inherited, introduction, "
                       "discussion, methods, supplement, or cut" % text)


def _item_key(item, layout):
    """The line an item names: `R3`, `O2`, `<section>:<heading>`, or a heading's text when one line carries it."""
    said = _one_line(item)
    if _OBJECTIVE.match(said):
        if said not in layout.order:
            raise OutlineError("%s has no subsection in the outline: only an open or answered objective has one" % said)
        return said
    if said in layout.where:
        return said
    if _RESULT.match(said):
        raise OutlineError("%s is no result the outline shows; the results are %s" % (
            said, ", ".join(key for key in layout.keys() if _RESULT.match(key)) or "none yet"))
    matches = [key for key in layout.keys() if _split_key(key) and _split_key(key)[1] == said]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise OutlineError("%r names %s; say which as <section>:<heading>" % (said, " and ".join(matches)))
    raise OutlineError("the outline shows no line %r" % said)


def _fits(key, group):
    """Whether a line may stand in `group`: a result or a Results heading in a Results part, a heading in its own section,
    and either under Supplement or Cut. The verb and an edit of the file both keep to it."""
    if group in PLACES:
        return True
    if _RESULT.match(key) or (_split_key(key) and _split_key(key)[0] == RESULTS):
        return group.startswith("results:")
    split = _split_key(key)
    return bool(split) and group == split[0]


def _allowed(key, group, layout):
    return group in layout.groups and _fits(key, group)


def _change(project_or_ledger, change, by):
    """Apply `change(record, layout, facts) -> changes` under the lock after taking a pending edit in, then save and render."""
    from wayline import sections
    if by not in (OWNER, DECIDER):
        raise OutlineError("the outline is changed by the owner or the decider, got %r" % (by,))
    book = ledger_for(project_or_ledger)
    with book.lock():
        take_in(book)
        facts = _Facts(book, details=False)
        record = read_record(book)
        changes = change(record, _layout(facts, record), facts)
        if changes:
            record["gone"] = []
            _save(book, record, changes, by)
            sections.render_sections(book, only=SECTIONS)
            _write(book)
    return changes


def move(project_or_ledger, item, before=None, after=None, to=None, by=OWNER):
    """Move a line before or after another, or to the end of a part (`to`): the owner's order of that part, journaled `outline`."""
    if sum(value is not None for value in (before, after, to)) != 1:
        raise OutlineError("a move names one of before, after, or to")

    def change(record, layout, facts):
        key = _item_key(item, layout)
        anchor = _item_key(before if before is not None else after, layout) if to is None else None
        if anchor == key:
            raise OutlineError("%s cannot move before or after itself" % key)
        if _OBJECTIVE.match(key):
            if anchor is None or not _OBJECTIVE.match(anchor):
                raise OutlineError("an objective moves before or after another objective")
            sequence = [identifier for identifier in layout.order if identifier != key]
            sequence.insert(sequence.index(anchor) + (0 if before is not None else 1), key)
            _pin(record, OBJECTIVES, sequence)
            return [(MOVED, key, OBJECTIVES, None)]
        group = _group_name(to) if to is not None else layout.where.get(anchor)
        if group is None or not _allowed(key, group, layout):
            raise OutlineError("%s cannot go to %s" % (key, to if to is not None else anchor))
        sequence = [other for other in layout.groups.get(group, []) if other != key]
        at = len(sequence) if anchor is None else sequence.index(anchor) + (0 if before is not None else 1)
        sequence.insert(at, key)
        _pin(record, group, sequence)
        return [(_action(key, group, layout.where.get(key)), key, group, None)]
    return _change(project_or_ledger, change, by)


def place(project_or_ledger, item, where, by=OWNER):
    """Place a line under Supplement or Cut (at its end), or back in the main text where code puts it; journaled `placed`."""
    if where not in (MAIN,) + PLACES:
        raise OutlineError("a line is placed in %s, got %r" % (", ".join((MAIN,) + PLACES), where))
    if where != MAIN:
        return move(project_or_ledger, item, to=where, by=by)

    def change(record, layout, facts):
        key = _item_key(item, layout)
        if layout.where.get(key) not in PLACES:
            raise OutlineError("%s is in the main text already" % key)
        for group in PLACES:
            if key in (record.get("groups") or {}).get(group, []):
                record["groups"][group].remove(key)
                if not record["groups"][group]:
                    del record["groups"][group]
        return [(PLACED, key, MAIN, None)]
    return _change(project_or_ledger, change, by)


def note(project_or_ledger, item, text, by=OWNER):
    """Keep a note under a line (an empty one takes it away), journaled `noted`; a note is an instruction for the line."""
    def change(record, layout, facts):
        key = _item_key(item, layout)
        said = _one_line(text)
        if said == _one_line(layout.notes.get(key)):
            return []
        _set_note(record, key, said, facts)
        return [(NOTED, key, None, said or None)]
    return _change(project_or_ledger, change, by)


def add_heading(project_or_ledger, section, heading, before=None, after=None, by=OWNER):
    """Add a heading to Introduction, Discussion, or Methods, which the writer fills at the order; journaled `added`."""
    heading = _one_line(heading)
    if section == RESULTS:
        raise OutlineError("a new Results subsection is a new question that needs new work: open it as an objective "
                           "(wayline objective add \"<question>\")")
    if section not in HEADED:
        raise OutlineError("a heading is added to one of %s, got %r" % (", ".join(HEADED), section))
    if not heading:
        raise OutlineError("a heading needs its text")

    def change(record, layout, facts):
        key = heading_key(section, heading)
        if key in layout.where:
            raise OutlineError("%s already holds the heading %r" % (TITLES[section], heading))
        anchor = _item_key(before if before is not None else after, layout) if (before or after) else None
        group = layout.where.get(anchor, section) if anchor else section
        if group not in (section,) + PLACES:
            raise OutlineError("a %s heading stands in %s, the supplement, or the cut" % (TITLES[section], TITLES[section]))
        record.setdefault("added", []).append({"section": section, "heading": heading})
        sequence = list(layout.groups.get(group, []))
        sequence.insert(len(sequence) if anchor is None else sequence.index(anchor) + (0 if before is not None else 1), key)
        _pin(record, group, sequence)
        return [(ADDED, key, group, None)]
    return _change(project_or_ledger, change, by)


# --- what follows the outline before the order ---------------------------------------------------------------------


def _heading_of(key, facts, section):
    """The heading a line renders under in `section`, or None when the line is not of that section."""
    if _RESULT.match(key):
        return facts.by_result[key].heading if section == RESULTS and key in facts.by_result else None
    split = _split_key(key)
    return split[1] if split and split[0] == section else None


def section_orders(project_or_ledger):
    """`{section: (main, placed)}` for each section the outline orders, from one reading of the ledger: its headings in the
    outline's order, then each placed under Supplement or Cut with its place.

    What `sections` renders the headings in before the order; a heading the outline does not show keeps its place after
    these, in first-appearance order. A pass that renders several sections reads it once and hands it to each.
    """
    book = ledger_for(project_or_ledger)
    facts = _Facts(book, details=False)
    layout = _layout(facts, read_record(book))
    found = {}
    for section in SECTIONS:
        groups = ["results:%s" % identifier for identifier in layout.order] + [BEYOND, INHERITED] if section == RESULTS else [section]
        main = [heading for group in groups for heading in (_heading_of(key, facts, section) for key in layout.groups.get(group, []))
                if heading]
        placed = [(heading, group) for group in PLACES for heading in (_heading_of(key, facts, section) for key in layout.groups[group])
                  if heading]
        found[section] = (list(dict.fromkeys(main)), placed)
    return found


def section_order(project_or_ledger, section):
    """`(main, placed)` of one section (`section_orders`)."""
    return section_orders(project_or_ledger)[section]


def heading_notes(project_or_ledger, section):
    """`{heading: note}`: the owner's notes on a section's lines, what a consolidation of it follows."""
    book = ledger_for(project_or_ledger)
    facts = _Facts(book, details=False)
    layout = _layout(facts, read_record(book))
    found = {}
    for key, said in layout.notes.items():
        heading = _heading_of(key, facts, section)
        if heading:
            found[heading] = said
    return found


def pack_text(project_or_ledger, objective_ids, max_chars=None):
    """The context pack's part on the outline: each of the ticket's objectives' entries with the owner's notes; empty
    when the ticket serves none with a subsection."""
    book = ledger_for(project_or_ledger)
    try:
        facts = _Facts(book, details=False)
        record = read_record(book)
        layout = _layout(facts, record)
    except (OutlineError, OSError, ValueError):
        return ""
    wanted = {facts.successor(identifier) for identifier in objective_ids or ()}
    shown = [identifier for identifier in layout.order if identifier in wanted]
    if not shown:
        return ""
    lines = ["# The outline of this ticket's objectives", "",
             "Where the paper puts this ticket's work (`research/OUTLINE.md`), built by code and steered by the owner: "
             "the results under each objective in the paper's order. The owner's notes are instructions."]
    for identifier in shown:
        lines += ["", "## %s %s" % (identifier, _one_line(facts.by_objective[identifier]["text"]))]
        if layout.notes.get(identifier):
            lines.append("Note: %s" % layout.notes[identifier])
        for key in layout.groups.get("results:%s" % identifier, []):
            if _RESULT.match(key):
                result = facts.by_result[key]
                lines.append('- %s "%s" (%s, %s)' % (key, result.heading, result.standing, _plural(len(result.current), "finding")))
            else:
                heading = _split_key(key)[1]
                lines.append("- %s" % (_inherited_line(facts, heading) if heading in facts.inherited
                                       else "Results: %s" % _heading_line(facts, RESULTS, heading, record)))
            if layout.notes.get(key):
                lines.append("  Note: %s" % layout.notes[key])
        lines += ["- see %s under %s" % pointer for pointer in layout.pointers.get(identifier, [])]
    text = "\n".join(lines)
    if max_chars is not None and len(text) > max(0, int(max_chars)):
        cut = text[:max(0, int(max_chars))].rsplit("\n", 1)[0]
        text = cut + ("\n\n" if cut else "") + "[wayline: the outline's entries reached the context cap; the rest is in research/OUTLINE.md.]"
    return text


# --- merges, proposed by code --------------------------------------------------------------------------------------


def _candidates(facts):
    """`{(a, b): objective}`: every pair of results serving one objective with a subsection, a before b by id."""
    pairs = {}
    for item in facts.objectives:
        if item.get("status") not in SUBSECTION:
            continue
        serving = sorted((result.id for result in _results_of(facts, item["id"])), key=_id_number)
        for index, first in enumerate(serving):
            for second in serving[index + 1:]:
                pairs.setdefault((first, second), item["id"])
    return pairs


def propose_merges(project_or_ledger, run=None, tools=None):
    """Propose merging the results whose headings sit close under one objective: one `outline_proposals` batch of the new
    pairs, or None. The embedding model runs only when the results under the objectives changed since the last check.

    Raises `repeats.RepeatsError` when the model is not recorded or fails; the callers say so and go on.
    """
    from wayline import batches, repeats
    from wayline.tools import run_tool
    book = ledger_for(project_or_ledger)
    facts = _Facts(book, details=False)
    pairs = _candidates(facts)
    if not pairs:
        return None
    seen = sorted([pair[0], pair[1], facts.by_result[pair[0]].heading, facts.by_result[pair[1]].heading] for pair in pairs)
    checked = _digest(json.dumps(seen, ensure_ascii=False))
    try:
        cache = book.read_json(MERGES_CACHE)
    except (OSError, ValueError):
        cache = {}
    if (cache or {}).get("checked") == checked:
        return None
    headings = list(dict.fromkeys(facts.by_result[identifier].heading for pair in pairs for identifier in pair))
    vectors = dict(zip(headings, repeats.embed(headings, run=run or run_tool, tools=tools)))  # outside the lock: it takes seconds
    close = []
    for (first, second), objective in sorted(pairs.items(), key=lambda entry: (_id_number(entry[0][0]), _id_number(entry[0][1]))):
        one, other = facts.by_result[first].heading, facts.by_result[second].heading
        similarity = sum(a * b for a, b in zip(vectors[one], vectors[other]))
        if similarity >= SIMILARITY:
            close.append({"ref": "%s+%s" % (first, second), "default": DECLINE,
                          "text": 'Merge %s into %s: "%s" and "%s" sit close under %s (similarity %.2f).' % (
                              second, first, other, one, objective, similarity)})
    # What was asked already is read, the batch opened, and the set recorded as checked under one lock, in that order, so
    # two callers never open the same pair twice and a batch that could not be opened leaves the set to check again.
    with book.lock():
        asked = set()
        for batch in batches.read_batches(book.project):
            if batch["kind"] == BATCH_KIND:
                asked.update(frozenset(item["ref"].split("+")) for item in batch["items"])
        items = [item for item in close if frozenset(item["ref"].split("+")) not in asked]
        opened = batches.open_batch(book.project, BATCH_KIND, "Results whose headings sit close: merge them?", items) if items else None
        book.write_json(MERGES_CACHE, {"checked": checked})
    return opened


def take_marks(project_or_ledger):
    """Merge each pair of results taken on an `outline_proposals` batch, the later into the earlier, by whoever took it.

    Idempotent: a pair already merged, or one of whose results is gone, is left. Returns the merges made, `(source, into)`.
    """
    from wayline import batches, sections
    from wayline import results as results_module
    book = ledger_for(project_or_ledger)
    merged = []
    with book.lock():
        for batch in batches.read_batches(book.project):
            if batch["kind"] != BATCH_KIND:
                continue
            for item in batch["items"]:
                if item["mark"] != TAKE:
                    continue
                clusters = results_module.load(book)
                pair = [clusters.resolve(identifier) for identifier in item["ref"].split("+")]
                live = {result["id"] for result in clusters.live()}
                if len(pair) != 2 or pair[0] == pair[1] or not set(pair) <= live:
                    if not item.get("acted"):  # merged already, or gone: nothing is left for the mark to do
                        batches.acted_on(book, batch["id"], {item["id"]: TAKE})
                    continue
                into, source = sorted(pair, key=_id_number)
                try:
                    results_module.merge(book.project, source, into, by=item["by"] or OWNER, render=False)
                except results_module.ResultError:
                    continue  # a drawing of it is under way (ticket 101): the mark stays, taken at a later pass
                batches.acted_on(book, batch["id"], {item["id"]: TAKE})  # merged: no later click in the marks view undoes it
                merged.append((source, into))
        if merged:
            sections.render_section(book, sections.RESULTS)
    return merged


def open_proposals(project_or_ledger):
    """The lines of "Proposed, not settled" as the outline shows them: what the account counts as waiting on the owner."""
    book = ledger_for(project_or_ledger)
    facts = _Facts(book, details=False)
    record = read_record(book)
    return _proposals(facts, _layout(facts, record), record)


# --- the verb ------------------------------------------------------------------------------------------------------


def outline_command(args):
    """`wayline outline [show] | move <item> --before|--after <item>|--to <part> | place <item> main|supplement|cut |
    note <item> "<text>" | heading <section> "<heading>" [--before|--after <item>] | propose [--project <path>]`."""
    from wayline.project import ProjectError, find_project
    parser = argparse.ArgumentParser(prog="wayline outline", description="show the outline of the paper, or change it on the "
                                     "owner's word: the same changes as an edit of research/OUTLINE.md")
    subparsers = parser.add_subparsers(dest="action")
    shown = subparsers.add_parser("show", help="render research/OUTLINE.md and print it")
    moving = subparsers.add_parser("move", help="move a line before or after another, or to the end of a part")
    moving.add_argument("item", help="R3, O2, <section>:<heading>, or a heading's text")
    where = moving.add_mutually_exclusive_group(required=True)
    where.add_argument("--before", help="the line it goes before")
    where.add_argument("--after", help="the line it goes after")
    where.add_argument("--to", help="the part it goes to the end of: O2, beyond, inherited, introduction, discussion, methods, "
                                    "supplement, cut")
    placing = subparsers.add_parser("place", help="place a line under Supplement or Cut, or back in the main text")
    placing.add_argument("item")
    placing.add_argument("where", choices=(MAIN,) + PLACES)
    noting = subparsers.add_parser("note", help="keep a note under a line, an instruction for it (\"\" takes it away)")
    noting.add_argument("item")
    noting.add_argument("text")
    adding = subparsers.add_parser("heading", help="add a heading to Introduction, Discussion, or Methods")
    adding.add_argument("section", choices=HEADED)
    adding.add_argument("heading")
    anchor = adding.add_mutually_exclusive_group()
    anchor.add_argument("--before")
    anchor.add_argument("--after")
    proposing = subparsers.add_parser("propose", help="propose merging the results whose headings sit close under one objective")
    for sub in (shown, moving, placing, noting, adding, proposing):
        sub.add_argument("--project", help="the project; the active one by default")
    for sub in (moving, placing, noting, adding):
        sub.add_argument("--by", choices=(OWNER, DECIDER), default=OWNER, help="who changes it (default: owner)")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if options.action in (None, "show"):
            render_outline(project)
            print((ledger_for(project).research / OUTLINE_MD).read_text(encoding="utf-8").partition("\n")[2], end="")
            return 0
        if options.action == "propose":
            from wayline import batches, repeats
            try:
                batch = propose_merges(project)
            except repeats.RepeatsError as failure:
                print("wayline outline: no merge was proposed: %s" % failure, file=sys.stderr)
                return 1
            render_outline(project)
            print(batches.render(project, batch["id"]) if batch else "no new pair of results sits close under one objective")
            return 0
        if options.action == "move":
            changes = move(project, options.item, before=options.before, after=options.after, to=options.to, by=options.by)
        elif options.action == "place":
            changes = place(project, options.item, options.where, by=options.by)
        elif options.action == "note":
            changes = note(project, options.item, options.text, by=options.by)
        else:
            changes = add_heading(project, options.section, options.heading, before=options.before, after=options.after, by=options.by)
    except OutlineError as failure:
        print("wayline outline: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline outline: %s" % failure, file=sys.stderr)
        return 1
    for action, item, to, said in changes:
        print("%s %s%s%s" % (item, action, " to %s" % to if to else "", ": %s" % said if said else ""))
    if not changes:
        print("nothing changed")
    return 0
