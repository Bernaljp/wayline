"""Results: what the project found on one question, the unit the reports present (Implementation Decision 17; ticket 90).

**A result** is one Results heading with its current findings. It gets an id, R1 onward and never reused, when its
heading first appears, at the acceptance of the finding that brings it: code clusters with no session of its own
(`assign`, which `sections.file_finding` calls). A finding joins, in this order:

1. the result of the finding it `replaces`, whatever heading it names, since a scope-down narrows what it replaces;
2. the result whose heading (or an earlier heading of it, or of a result merged into it) is the finding's own, read
   with its spacing and case taken off;
3. a new result under its heading.

A finding with no heading stands under "Findings". The repeated-claims check joins this list once ticket 95 lands.

**The record.** `research/results.json` holds the results, written only through the ledger: each with its `heading`,
every heading that names it (`headings`), the result it was merged into (`merged_into`, null for a live result), and
when it was created and last changed. A finding's own line in `findings.jsonl` carries the `result` it joined, and its
`finding` event too. Each result created, merged, or renamed is journaled as `result`, so the record is a replay of
the journal (`replay`), which is how the tests read a recorded journal.

**The owner's word.** The owner merges or renames results by saying so: the conversation calls `wayline result merge
<id> <into>` or `wayline result rename <id> "<heading>"` (`merge`, `rename`), recorded through the ledger as `result`
with `by: owner`. A merged result's findings, and the findings that later name its headings, belong to the one it went
into; a renamed result keeps its old heading as one that names it. Either re-renders the Results section and the
general report, which present results under their current headings.

**What a result presents** (`read_results`): its current findings (those the Results section still shows), its
objectives (the union of theirs), its standing (`supported` when none is negative, `negative` when all are, `mixed`
otherwise), its counts, and its last change. A result with no current finding presents nothing and is left out.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field

from wayline.ledger import RESULT, LedgerError, ledger_for, make_event, now_ts

__all__ = [
    "RESULTS_JSON", "DEFAULT_HEADING", "CREATED", "MERGED", "RENAMED", "CODE", "OWNER", "SUPPORTED", "NEGATIVE", "MIXED",
    "ResultError", "Clusters", "Result", "heading_key", "load", "assign", "commit", "replay", "read_results",
    "result_headings", "merge", "rename", "result_command",
]

RESULTS_JSON = "results.json"
DEFAULT_HEADING = "Findings"  # what a finding with no heading stands under, as the Results section renders it
CREATED, MERGED, RENAMED = "created", "merged", "renamed"
CODE, OWNER = "code", "owner"
SUPPORTED, NEGATIVE, MIXED = "supported", "negative", "mixed"

_ID = re.compile(r"^R([1-9][0-9]*)$")
_OBJECTIVE = re.compile(r"^O([1-9][0-9]*)$")


class ResultError(LedgerError):
    """A merge or a rename the record refuses: an unknown or merged result, a result merged into itself, a heading in use."""


def heading_key(heading):
    """What a heading is matched by: its words, spacing and case taken off; a blank heading is "Findings"."""
    words = " ".join(str(heading or "").split())
    return (words or DEFAULT_HEADING).casefold()


def _one_line(text):
    return " ".join(str(text or "").split())


# --- the clustering ----------------------------------------------------------------------------------------------


class Clusters:
    """The results and which result each finding joined: one pure state that acceptance and replay both step."""

    def __init__(self):
        self.results = {}  # id -> {id, heading, headings, merged_into, created, changed}, in id order
        self.of = {}       # finding id -> the result it joined when it was filed

    @classmethod
    def from_record(cls, record, findings=()):
        """The state `research/results.json` and `findings.jsonl` hold; a finding filed with no `result` is placed now."""
        clusters = cls()
        for item in (record or {}).get("results") or []:
            if isinstance(item, dict) and _ID.match(str(item.get("id") or "")):
                clusters.results[item["id"]] = {
                    "id": item["id"], "heading": _one_line(item.get("heading")) or DEFAULT_HEADING,
                    "headings": [_one_line(name) for name in item.get("headings") or [item.get("heading")] if _one_line(name)],
                    "merged_into": item.get("merged_into"), "created": item.get("created"), "changed": item.get("changed")}
        for finding in findings:
            if not isinstance(finding, dict) or not finding.get("id"):
                continue
            if finding.get("result") in clusters.results:
                clusters.of[finding["id"]] = finding["result"]
            else:
                clusters.place(finding)
        return clusters

    def resolve(self, identifier):
        """The live result `identifier` stands in now: itself, or the result it was merged into, followed down."""
        seen = set()
        while identifier in self.results and self.results[identifier].get("merged_into") and identifier not in seen:
            seen.add(identifier)
            identifier = self.results[identifier]["merged_into"]
        return identifier

    def live(self):
        return [item for item in self.results.values() if not item.get("merged_into")]

    def named(self, heading):
        """The live result a heading names, or None."""
        key = heading_key(heading)
        for item in self.results.values():
            if any(heading_key(name) == key for name in item["headings"]):
                return self.resolve(item["id"])
        return None

    def next_id(self):
        highest = max((int(_ID.match(identifier).group(1)) for identifier in self.results), default=0)
        return "R%d" % (highest + 1)

    def place(self, finding, ts=None):
        """Which result `finding` joins (the module's docstring): `(id, created)`, `created` the new result's record or None."""
        replaced = finding.get("replaces")
        if replaced and replaced in self.of:
            identifier, created = self.resolve(self.of[replaced]), None
        else:
            identifier, created = self.named(finding.get("heading")), None
        if identifier is None:
            heading = _one_line(finding.get("heading")) or DEFAULT_HEADING
            identifier = self.next_id()
            stamp = ts or finding.get("ts")
            created = {"id": identifier, "heading": heading, "headings": [heading], "merged_into": None, "created": stamp, "changed": stamp}
            self.results[identifier] = created
        elif ts or finding.get("ts"):
            self.results[identifier]["changed"] = ts or finding.get("ts")
        if finding.get("id"):
            self.of[finding["id"]] = identifier
        return identifier, created

    def merge(self, source, into, ts=None):
        """`source` merged into `into`: both live and not the same. Refused with `ResultError` otherwise."""
        for identifier in (source, into):
            if identifier not in self.results:
                raise ResultError("there is no result %s; the results are %s" % (identifier, ", ".join(self.results) or "none yet"))
            if self.results[identifier].get("merged_into"):
                raise ResultError("%s was merged into %s already; name %s instead" % (
                    identifier, self.resolve(identifier), self.resolve(identifier)))
        if source == into:
            raise ResultError("a result is not merged into itself")
        self.results[source]["merged_into"] = into
        self.results[source]["changed"] = self.results[into]["changed"] = ts or now_ts()

    def rename(self, identifier, heading, ts=None):
        """`identifier` named `heading` from now on, its old heading still naming it. Refused with `ResultError` otherwise."""
        heading = _one_line(heading)
        if identifier not in self.results:
            raise ResultError("there is no result %s; the results are %s" % (identifier, ", ".join(self.results) or "none yet"))
        if self.results[identifier].get("merged_into"):
            raise ResultError("%s was merged into %s; rename %s instead" % (identifier, self.resolve(identifier), self.resolve(identifier)))
        if not heading:
            raise ResultError("a result's heading names its question; got nothing")
        other = self.named(heading)
        if other is not None and other != identifier:
            raise ResultError("%r names %s already; merge the two instead" % (heading, other))
        item = self.results[identifier]
        previous = item["heading"]
        item["heading"] = heading
        if all(heading_key(name) != heading_key(heading) for name in item["headings"]):
            item["headings"].append(heading)
        item["changed"] = ts or now_ts()
        return previous

    def record(self):
        """`research/results.json` as code writes it."""
        return {"schema_version": 1, "results": [dict(item, headings=list(item["headings"])) for item in self.results.values()]}


def load(project_or_ledger, findings=None):
    """The clustering as the ledger holds it now: `results.json` and the `result` of every filed finding (`findings`,
    when the caller has read them already)."""
    from wayline.sections import read_findings  # sections calls `assign` from inside its ledger call
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(RESULTS_JSON)
    except (OSError, ValueError):
        record = None
    return Clusters.from_record(record if isinstance(record, dict) else None, read_findings(book) if findings is None else findings)


def assign(project_or_ledger, finding):
    """The result `finding` joins at its acceptance, and the new result's record when it is the first of its heading.

    Pure: nothing is written until `commit`, so a finding the ledger refuses after this creates no result. Call it
    under the ledger's lock.
    """
    clusters = load(project_or_ledger)
    identifier, created = clusters.place(finding)
    return identifier, created, clusters


def commit(project_or_ledger, clusters, created, ticket=None):
    """Write `results.json` and, for a result created at this acceptance, journal it as `result` by code."""
    book = ledger_for(project_or_ledger)
    book.write_json(RESULTS_JSON, clusters.record())
    if created is not None:
        book.append_event(RESULT, {"id": created["id"], "heading": created["heading"], "action": CREATED, "by": CODE}, ticket=ticket)


def replay(events):
    """The clustering rebuilt from a journal's `finding` and `result` events alone, in their order."""
    clusters = Clusters()
    for event in events:
        name, payload = event.get("event"), event.get("payload") or {}
        if name == "finding":
            clusters.place(payload, ts=event.get("ts"))
        elif name == RESULT and payload.get("action") == MERGED:
            clusters.merge(payload.get("id"), payload.get("into"), ts=event.get("ts"))
        elif name == RESULT and payload.get("action") == RENAMED:
            clusters.rename(payload.get("id"), payload.get("heading"), ts=event.get("ts"))
    return clusters


# --- what a result presents ---------------------------------------------------------------------------------------


@dataclass
class Result:
    """One live result as the reports present it."""

    id: str
    heading: str
    findings: list = field(default_factory=list)  # every finding it holds, in arrival order, replaced ones too
    current: list = field(default_factory=list)   # the findings the Results section still shows
    objectives: list = field(default_factory=list)
    changed: str = None

    @property
    def negative(self):
        return sum(1 for finding in self.current if finding.get("negative"))

    @property
    def replaced(self):
        return len(self.findings) - len(self.current)

    @property
    def standing(self):
        if not self.negative:
            return SUPPORTED
        return NEGATIVE if self.negative == len(self.current) else MIXED


def _objective_order(identifier):
    found = _OBJECTIVE.match(str(identifier))
    return (0, int(found.group(1)), "") if found else (1, 0, str(identifier))


def read_results(project_or_ledger):
    """Every live result with a current finding, in id order (the module's docstring)."""
    from wayline import sections  # sections calls `assign` from inside its ledger call
    book = ledger_for(project_or_ledger)
    findings = sections.read_findings(book)
    clusters = load(book, findings)
    current = sections.current_ids(book, sections.RESULTS)
    found = {item["id"]: Result(item["id"], item["heading"], changed=item.get("changed")) for item in clusters.live()}
    for finding in findings:
        identifier = clusters.resolve(clusters.of.get(finding.get("id")))
        if identifier not in found:
            continue
        result = found[identifier]
        result.findings.append(finding)
        if finding.get("id") in current:
            result.current.append(finding)
        stamp = str(finding.get("ts") or "")
        if stamp and stamp > str(result.changed or ""):
            result.changed = stamp
    for result in found.values():
        result.objectives = sorted({str(name) for finding in result.current for name in finding.get("objectives") or []},
                                   key=_objective_order)
    ordered = sorted(found.values(), key=lambda result: int(_ID.match(result.id).group(1)))
    return [result for result in ordered if result.current]


def result_headings(project_or_ledger):
    """`{finding id: its result's current heading}`: what the Results section renders each finding under."""
    clusters = load(project_or_ledger)
    return {finding: clusters.results[clusters.resolve(identifier)]["heading"]
            for finding, identifier in clusters.of.items() if clusters.resolve(identifier) in clusters.results}


# --- the owner's word: merge and rename ----------------------------------------------------------------------------


def _record(project, action, change, by=OWNER, render=True):
    """Apply `change(clusters, stamp)` under the lock, write the record, journal it, and re-render; returns the payload.

    `by` is the owner, or the decider taking a merge the outline proposed (ticket 104); `render` False leaves the renders
    to a caller that is already in a render pass."""
    from wayline import sections  # sections calls `assign` from inside its ledger call
    book = ledger_for(project)
    with book.lock():
        # An edit of the Results file was made under the headings it shows: take it in before they change, or every
        # paragraph under a renamed or merged heading would read as the owner's replacement of it.
        sections.render_section(book, sections.RESULTS)
        clusters = load(book)
        stamp = now_ts()
        payload = change(clusters, stamp)
        payload = dict(payload, action=action, by=by)
        make_event(RESULT, payload)
        book.write_json(RESULTS_JSON, clusters.record())
        book.append_event(RESULT, payload, ts=stamp)
    if render:
        _render(book)
    return payload


def _render(book):
    """The Results section and the general report, which present results under their current headings."""
    from wayline import provenance, sections  # the report pulls in the gates
    sections.render_section(book, sections.RESULTS)
    provenance.render_report(book.project, offline=True)


def merge(project, source, into, by=OWNER, render=True):
    """Merge result `source` into `into` on the owner's word (or the decider's, taking the outline's proposal): journaled as
    `result` `merged`, then re-rendered unless `render` is False."""
    def change(clusters, stamp):
        clusters.merge(source, into, ts=stamp)
        return {"id": source, "heading": clusters.results[source]["heading"], "into": into}
    return _record(project, MERGED, change, by=by, render=render)


def rename(project, identifier, heading):
    """Rename result `identifier` to `heading` on the owner's word: journaled as `result` `renamed`, then re-rendered."""
    def change(clusters, stamp):
        previous = clusters.rename(identifier, heading, ts=stamp)
        return {"id": identifier, "heading": clusters.results[identifier]["heading"], "from": previous}
    return _record(project, RENAMED, change)


def result_command(args):
    """`wayline result merge <id> <into> | rename <id> "<heading>" | draw <id> [--project <path>]`."""
    from wayline.cli import parse_args
    from wayline.project import ProjectError, find_project

    parser = argparse.ArgumentParser(prog="wayline result", description="merge, rename, or draw again the project's results on the owner's word")
    subparsers = parser.add_subparsers(dest="action", required=True)
    merging = subparsers.add_parser("merge", help="merge one result into another: its findings and headings join that one")
    merging.add_argument("source", help="the result merged, R<n>")
    merging.add_argument("into", help="the result it goes into, R<n>")
    merging.add_argument("--project", help="the project; the active one by default")
    renaming = subparsers.add_parser("rename", help="give a result a new heading, which names its question")
    renaming.add_argument("result", help="the result renamed, R<n>")
    renaming.add_argument("heading", help="its new heading")
    renaming.add_argument("--project", help="the project; the active one by default")
    drawing = subparsers.add_parser("draw", help="draw a result again now, changed or not: one drawing ticket the run launches (ticket 100)")
    drawing.add_argument("result", help="the result drawn, R<n>")
    drawing.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        if options.action == "draw":
            from wayline import drawings  # the drawings module reads the results; this one never needs it otherwise
            try:
                ticket = drawings.draw_again(project, options.result)
            except drawings.DrawingError as failure:
                print("wayline result: %s" % failure, file=sys.stderr)
                return 2
            record = drawings.read_records(project, options.result)[-1]
            print("%s-%d opened as drawing ticket %d; the run draws it at its next wave" % (options.result, record["version"], ticket))
        elif options.action == "merge":
            payload = merge(project, options.source, options.into)
            print("%s (%s) merged into %s" % (payload["id"], payload["heading"], payload["into"]))
        else:
            payload = rename(project, options.result, options.heading)
            print("%s renamed: %s (was %s)" % (payload["id"], payload["heading"], payload["from"]))
    except ResultError as failure:
        print("wayline result: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, OSError, ValueError) as failure:
        print("wayline result: %s" % failure, file=sys.stderr)
        return 1
    return 0
