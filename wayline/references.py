"""References during a ticket (Implementation Decision 17; ticket 98): `wayline scout <identifier>` and the check at acceptance.

A worker cites only works that exist, for what they say. Workers have no network, so a worker checks
a work mid-ticket with `wayline scout <identifier>` (a DOI, an arXiv id, or an exact title; a URL is
never looked up): code, no tokens, counted under `WAYLINE_TICKET` and refused past
`policy.scout.calls_per_ticket` calls a ticket. It files the L0 dossier at once and prints the slug,
the details, and the abstract; on a service failure it files an unresolved dossier with the `retry`
flag; on no such work it files nothing. Every lookup follows the outcomes and the cache rule of
ticket 71 (`dossier.look_up_one`).

A ticket's result lists every work it drew on in `references[]`, `{identifier, note}`. At acceptance
the Type-A check (`check_references`) confirms every cited work (every `ref` tag in the result's
passages and findings) is a dossier or listed, runs the scout free on the listed works no dossier
holds yet, and keeps each note on its dossier with the ticket's id. "No such work" sends the worker
back as most likely invented; a service failure accepts with the flag. A `ref` tag names a work by its
slug or by its identifier (`{ref:doi:10.1038/x#abstract}`, `{ref:arxiv:1802.03426#abstract}`, or by exact title,
`{ref:title:<exact title>}`, ticket 88), mapped
through position's identifier index, and its locator must name what the dossier holds at its level:
`abstract` or `metadata.<field>` at L0 and L1, and at L2 an entry's locator as well. Dossiers stay at
L0 when cited.

**References rendered and raised** (ticket 105). After every render of the sections code writes two files from the
dossiers, with no model tokens (`render_references`):

- `research/sections/references.md`: the works the sections cite, numbered by first citation through the sections in
  the outline's order (Introduction, Results, Discussion, Methods, each by its headings in the outline's order), each
  entry its authors to three then "et al.", the year, the title, the venue, the identifier, and a link to its dossier;
  then **Not yet resolved**, each unresolved cited work in first-citation order with its state: "to the scout" (no
  lookup has answered yet), "retrying" with the service and the date of its last failure, "gave up" (no service knows
  it, the `retry` flag gave up, or nothing can look it up), or "claim kept, to be resolved" (the owner said "leave it",
  which settles it until the paper order). A work enters References only by being cited, and no passage is written
  into it.
- `research/references.json`: CSL-JSON of the cited works that resolved, in the same order, built from their dossiers.

An unresolved reference is **important** when the owner named it (at intake), or when a standing passage or finding,
a concern, or an objective cites it (`important`). Its failure is final when no service knows it, when its flag gave
up, or when it is a URL or a file no service can look up. Past setup the conductor raises each important one once
its failure is final, never while it is still retrying (`raise_final`), journaled as `reference_raised`, once:
under `interactive` a notice linking to it, a line under the account's "Waiting on you", and the first item of the
next conversation (`waiting`); under `checkpoints` the line, and it is put at the next conversation or with the end
notice; under `autonomous` it was asked at setup (`at_setup`, which includes those still retrying) and is afterward
listed in the account, never notified. "Leave it" settles an item until the order: it is neither raised nor listed.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from wayline import dossier as dossiers
from wayline.cli import parse_args
from wayline.ledger import K_AUTONOMY, K_OUTCOME, K_REASON, PAYLOAD_ENUMS, REFERENCE_RAISED, SCOUTED, LedgerError, ledger_for, now_ts
from wayline.project import ProjectError, find_project, policy_for, read_harness
from wayline.provenance import TAG_RE, identifier_index, parse_tag, ref_slug
from wayline.scout import (FAILED, FOUND, NO_SUCH_WORK, NOT_LOOKED_UP, VERIFIED, Reference, ScoutError, normalize_title, outcome,
                           parse_reference)

__all__ = [
    "CALLS_PER_TICKET", "LOOKED_UP_KINDS", "ReferenceError_", "ScoutRefused", "call_limit", "calls_made", "looked_up", "scout", "scout_command", "render",
    "cited", "held_locators", "check_references", "tagged_reference",
    "REFERENCES_MD", "REFERENCES_JSON", "NOT_YET_RESOLVED", "STATES", "TO_THE_SCOUT", "RETRYING", "GAVE_UP", "CLAIM_KEPT", "Work",
    "ref_tags", "cited_works", "work_named", "standing_of", "entry_line", "csl_item", "references_view", "render_references",
    "unresolved_count", "important", "at_setup", "final", "raise_final", "waiting", "waiting_line", "notice_text", "WHY_IMPORTANT",
]

CALLS_PER_TICKET = 20  # the fallback when a policy carries no `scout.calls_per_ticket`
LOOKED_UP_KINDS = ("doi", "arxiv", "title")  # what a worker may name a work by; a URL and a file are never looked up


class ReferenceError_(ValueError):
    """A reference the scout will not look up for a ticket: empty, a URL, or a local file."""


class ScoutRefused(ReferenceError_):
    """The call past the ticket's `policy.scout.calls_per_ticket`."""


# --- the count -----------------------------------------------------------------------------------


def calls_made(project_or_ledger, ticket):
    """How many `scouted` events the journal holds for `ticket`."""
    return ledger_for(project_or_ledger).count_events(SCOUTED, ticket)


def call_limit(policy):
    try:
        return int(((policy or {}).get("scout") or {}).get("calls_per_ticket", CALLS_PER_TICKET))
    except (TypeError, ValueError):
        return CALLS_PER_TICKET


def looked_up(identifier):
    """`identifier` read as the question the scout may ask for a ticket; raises ReferenceError_ for a URL, a file, or nothing."""
    text = str(identifier or "").strip()
    try:
        reference = parse_reference(text)
    except ScoutError as failure:
        raise ReferenceError_(str(failure)) from None
    if reference.kind not in LOOKED_UP_KINDS:
        raise ReferenceError_("%s is a URL, which is never looked up; name the work by its DOI, its arXiv id, or its exact title" % text)
    return reference


# --- the verb ------------------------------------------------------------------------------------


def scout(project, identifier, ticket=None, fetcher=None, email=None, clock=None, ledger=None):
    """Look up one work for a ticket: `{identifier, outcome, slug, dossier, ticket, asked, limit}`.

    `ticket` is the asking ticket's id, whose calls are counted and capped; None looks it up
    uncounted. Raises ScoutRefused past the cap and ReferenceError_ for a URL, both before any request.
    """
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    reference = looked_up(identifier)
    limit = call_limit(policy_for(project))
    asked = calls_made(ledger, ticket) if ticket is not None else None
    if ticket is not None and asked >= limit:
        raise ScoutRefused("ticket %s has made %d scout call(s), the most policy.scout.calls_per_ticket (%d) allows; "
                           "list what you still drew on in the result's references, which acceptance looks up" % (ticket, asked, limit))
    found = dossiers.look_up_one(project, reference, fetcher=fetcher, email=email, ledger=ledger, clock=clock or time.time)
    if ticket is not None:
        ledger.append_event(SCOUTED, {"identifier": reference.raw, "outcome": found["outcome"], "slug": found["slug"]}, ticket=ticket)
    return {"identifier": reference.raw, "outcome": found["outcome"], "slug": found["slug"], "dossier": found["dossier"],
            "ticket": ticket, "asked": None if ticket is None else asked + 1, "limit": limit}


def scout_command(args):
    """`wayline scout <identifier> [--json] [--project <path>]`: called by workers; the ticket is `WAYLINE_TICKET`."""
    parser = argparse.ArgumentParser(prog="wayline scout", description="check one work with the scout: file its L0 dossier and print its slug, details, and abstract")
    parser.add_argument("identifier", help="a DOI, an arXiv id, or the work's exact title (a URL is never looked up)")
    parser.add_argument("--project", help="the project; WAYLINE_PROJECT or the active one by default")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    raw_ticket = os.environ.get("WAYLINE_TICKET", "").strip()
    if raw_ticket and not raw_ticket.isdigit():
        print("wayline scout: WAYLINE_TICKET is %r, not a ticket id" % raw_ticket, file=sys.stderr)
        return 2
    ticket = int(raw_ticket) if raw_ticket else None
    try:
        project = find_project(options.project or os.environ.get("WAYLINE_PROJECT") or None)
        report = scout(project, options.identifier, ticket=ticket)
    except (ReferenceError_, ProjectError, dossiers.DossierError, LedgerError, ValueError, OSError) as failure:
        print("wayline scout: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 1 if report["outcome"] == NO_SUCH_WORK else 0


def render(report):
    """What a worker reads: the slug and how to cite it, the details, and the abstract; or why nothing was filed."""
    lines = []
    if report["outcome"] == NO_SUCH_WORK:
        lines.append("no such work: every service asked answered no match for %s, so nothing was filed. "
                     "A work no service knows is most likely invented; do not cite it." % report["identifier"])
    else:
        record = report["dossier"]
        metadata = record.get("metadata") or {}
        lines.append("slug        %s" % report["slug"])
        if report["outcome"] == FOUND:
            lines.append("outcome     found, filed at level %d; cite it as {ref:%s#abstract} or {ref:%s#metadata.<field>}"
                         % (record.get("level", 0), report["slug"], report["slug"]))
        else:
            flag = record.get("retry") or {}
            lines.append("outcome     a service failed (%s: %s), so the work is filed unresolved with the retry flag; "
                         "you may cite it and list it in references, and acceptance accepts it with the flag"
                         % (flag.get("service", "unknown"), flag.get("failure", FAILED)))
        for label, value in (("title", metadata.get("title")), ("authors", _authors(metadata.get("authors"))),
                             ("year", metadata.get("year")), ("venue", metadata.get("container")),
                             ("identifiers", ", ".join("%s:%s" % (key, value) for key, value in sorted((record.get("identifiers") or {}).items())))):
            if value:
                lines.append("%-11s %s" % (label, value))
        if report["outcome"] == FOUND:
            lines.append("abstract    %s" % (record.get("abstract") or "none on record: cite only #metadata.<field>, or propose the work's promotion"))
    if report["ticket"] is not None:
        lines.append("calls       %d of %d made by ticket %s" % (report["asked"], report["limit"], report["ticket"]))
    return "\n".join(lines)


# --- the check at acceptance (Type-A) --------------------------------------------------------------


def cited(result):
    """Every `ref` tag the result's passages and findings carry, in order, each once: `[(tag, parts)]` (parts None when malformed)."""
    texts = [item.get("text") for item in (result or {}).get("passages") or [] if isinstance(item, dict)]
    texts += [item.get("text") for item in (result or {}).get("findings") or [] if isinstance(item, dict)]
    found, seen = [], set()
    for text in texts:
        for kind, rest in TAG_RE.findall(str(text or "")):
            tag = "%s:%s" % (kind, rest)
            if kind != "ref" or tag in seen:
                continue
            seen.add(tag)
            found.append((tag, parse_tag(tag)[1]))
    return found


def held_locators(ledger, dossier):
    """What a cited dossier holds at its level, for a `ref` tag's locator (decision 17): a predicate on the locator.

    `abstract` when it holds one and `metadata.<field>` for each field it has, at every level; at L2 also the
    locator of each of its entries.
    """
    metadata = dossier.get("metadata") or {}
    entries = set()
    if int(dossier.get("level") or 0) >= dossiers.LEVEL_2:
        try:
            text = ledger.path("%s/%s/entries.jsonl" % (dossiers.REFS, dossier["slug"])).read_text(encoding="utf-8")
        except OSError:
            text = ""
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("locator"):
                entries.add(str(entry["locator"]))

    def holds(locator):
        if locator == "abstract":
            return bool(dossier.get("abstract"))
        if locator.startswith("metadata."):
            return metadata.get(locator[len("metadata."):]) not in (None, "", [], {})
        return locator in entries

    return holds


def check_references(project, ticket, result, fetcher=None, email=None, clock=None, ledger=None):
    """The Type-A check of a ticket's references at acceptance: `{problems, flagged, filed}`.

    Every cited work (a `ref` tag in the passages or the findings) must be a dossier or listed in
    `result.references` (`{identifier, note}`), and the scout runs free and uncounted on every work that is
    neither a found dossier nor known yet: each listed one, and each cited by `doi:`, `arxiv:`, or `title:` that no
    dossier holds. Found, it is filed; a service failure files it with the `retry` flag and is accepted
    (`flagged`); no such work is a problem, the work most likely invented. A URL is a problem, never looked
    up, and so is a slug no dossier holds. Each note is kept on its dossier as `ticket <id>`. A locator must
    name what the dossier holds at its level (`held_locators`); an identifier tag with no locator is the
    inherited citation's form, and passes. `problems` sends the worker back; an empty list passes.
    """
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    clock = clock or time.time
    problems, flagged, filed, listed, invented = [], [], [], {}, set()
    state = {"index": None}

    def index():
        if state["index"] is None:
            state["index"] = identifier_index(project)
        return state["index"]

    def look_up(reference, named_as):
        """The slug the scout filed `reference` under, or None with the problem said; a failure is flagged."""
        key = _key(reference)
        slug = dossiers.filed_slug(ledger, reference, index())
        record = _dossier(ledger, slug) if slug else None
        if record is not None and record.get("existence") == VERIFIED:
            return record["slug"]
        found = dossiers.look_up_one(project, reference, fetcher=fetcher, email=email, ledger=ledger, clock=clock, finish=False)
        if found["outcome"] == NO_SUCH_WORK:
            problems.append("%s names %s, which no service knows (every one asked answered no match): it is most likely invented; "
                            "take it out, and the claims that cite it, or give its exact DOI, arXiv id, or title" % (named_as, reference.raw))
            invented.add(key)
            return None
        if found["outcome"] == FAILED:
            flagged.append(found["slug"])
        if found["slug"] != slug:
            filed.append(found["slug"])
            state["index"] = None
        return found["slug"]

    for item in (result or {}).get("references") or []:
        identifier, note = str((item or {}).get("identifier") or "").strip(), str((item or {}).get("note") or "").strip()
        try:
            reference = looked_up(identifier)
        except ReferenceError_ as failure:
            problems.append("references names %r: %s" % (identifier, failure))
            continue
        slug = look_up(reference, "references")
        if slug is None:
            continue
        if note:
            dossiers.keep_ticket_note(ledger, slug, note, ticket, now=dossiers.timestamp(clock()))
        listed[_key(reference)] = slug
    for tag, parts in cited(result):
        if parts is None:
            problems.append("`{%s}` is not a `ref` tag: write `{ref:<slug>#<locator>}`, or `doi:`, `arxiv:`, or `title:` with the identifier in place of the slug" % tag)
            continue
        slug = ref_slug(parts, index())
        if parts.get("identifier"):
            reference = tagged_reference(parts["identifier"])
            named = _key(reference)
            if named in invented:
                continue  # sent back already, as a work no service knows
            slug = slug or listed.get(named)
            if slug is None or (_dossier(ledger, slug) or {}).get("existence") != VERIFIED:
                slug = look_up(reference, "`{%s}`" % tag)
                if slug is None:
                    continue
        record = _dossier(ledger, slug)
        if record is None:
            problems.append("`{%s}` names %s, which no dossier holds: check the work with `wayline scout <identifier>` and cite the slug "
                            "it prints, or cite it by `doi:` or `arxiv:`" % (tag, slug))
            continue
        if record.get("existence") != VERIFIED:
            if outcome(record) == NO_SUCH_WORK:
                problems.append("`{%s}` cites refs/%s, which no service knows (every one asked answered no match): it is most likely "
                                "invented; take the claim out, or cite the work by its exact DOI, arXiv id, or title" % (tag, record["slug"]))
            else:
                flagged.append(record["slug"])  # its lookup failed, or nothing can look it up: accepted with its flag, to be resolved
            continue
        locator = parts.get("locator")
        if locator and not held_locators(ledger, record)(locator):
            level = int(record.get("level") or 0)
            problems.append("`{%s}` names #%s, which refs/%s does not hold at level %d: cite #abstract or #metadata.<field>%s; a claim "
                            "beyond the abstract says only what the abstract says, or proposes the work's promotion"
                            % (tag, locator, record["slug"], level, ", or an entry's locator" if level >= dossiers.LEVEL_2 else ""))
        elif not locator and parts.get("slug"):
            problems.append("`{%s}` names no locator: say where in refs/%s the claim is read (#abstract or #metadata.<field>)" % (tag, record["slug"]))
    for slug in filed:
        record = _dossier(ledger, slug)
        if record is not None and record.get("existence") != VERIFIED:
            flagged.append(slug)
    if any((_dossier(ledger, slug) or {}).get("existence") == VERIFIED for slug in filed):
        dossiers.finish_lookups(project, ledger, clock)
    return {"problems": problems, "flagged": sorted(set(flagged)), "filed": filed}


def tagged_reference(identifier):
    """The question an identifier `ref` tag asks the scout: `doi:<doi>` and `arxiv:<id>` read as written, and `title:<exact
    title>` as that title (ticket 88), which the services are asked by its words, never by the prefix."""
    kind, _, value = str(identifier or "").partition(":")
    if kind.lower() == "title":
        return Reference("title", " ".join(value.split()), value.strip())
    return looked_up(identifier)


def _key(reference):
    """What one work is known by within one check: its kind and its value, a title by its normalized words."""
    if reference.kind == "title":
        return ("title", normalize_title(reference.value))
    return (reference.kind, reference.value.lower())


def _dossier(ledger, slug):
    """The dossier filed under `slug`, the one it was joined into for a pointer; None when there is none."""
    try:
        record = dossiers.read_dossier(ledger, slug)
        return dossiers.read_dossier(ledger, record["joined_into"]) if record.get("joined_into") else record
    except dossiers.DossierError:
        return None


def _authors(authors):
    names = [str(name) for name in authors or [] if name]
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "") if names else None


# --- References rendered (ticket 105) ---------------------------------------------------------------

REFERENCES_MD = "sections/references.md"
REFERENCES_JSON = "references.json"
NOT_YET_RESOLVED = "Not yet resolved"
# The sections cited through, in the outline's order (`outline.SECTIONS`); References itself cites nothing.
CITING = ("introduction", "results", "discussion", "methods")
# The state of an unresolved cited work in the Not yet resolved list.
TO_THE_SCOUT = "to the scout"
RETRYING = "retrying"
GAVE_UP = "gave up"
CLAIM_KEPT = "claim kept, to be resolved"
STATES = (TO_THE_SCOUT, RETRYING, GAVE_UP, CLAIM_KEPT)
NOTHING_CITED = "Nothing is cited yet: a work enters References only when a section cites it."
ALL_RESOLVED = "Nothing: every cited work resolved."
HEADER = ("Code writes this file from the dossiers after every render, numbered by first citation through the sections; "
          "a work enters it only by being cited.")
_UNREACHABLE = ("url", "file")  # what no service can look up
# The types the services answer with, as CSL names them; an arXiv category or anything unknown is an `article`.
_CSL_TYPES = {
    "journal-article": "article-journal", "article": "article-journal", "research-article": "article-journal",
    "journal article": "article-journal", "review": "article-journal", "proceedings-article": "paper-conference",
    "book-chapter": "chapter", "book": "book", "monograph": "book", "edited-book": "book", "posted-content": "article",
    "preprint": "article", "dissertation": "thesis", "report": "report", "dataset": "dataset",
}


class Work:
    """One work the sections cite: what it is known by (`key`), how it was first named, and its dossier when one is filed."""

    def __init__(self, key, named, slug=None, record=None):
        self.key, self.named, self.slug, self.record = key, named, slug, record

    @property
    def found(self):
        return (self.record or {}).get("existence") == VERIFIED


def ref_tags(text):
    """The `ref` tags of `text`, in order, each as its parsed parts (None for a malformed one)."""
    return [parse_tag("ref:%s" % rest)[1] for kind, rest in TAG_RE.findall(str(text or "")) if kind == "ref"]


def cited_works(project_or_ledger, index=None):
    """The works the sections cite now, each once, in first-citation order through the sections in the outline's order.

    A replaced or withdrawn passage cites nothing. A tag naming a work by slug or by identifier maps through position's
    identifier index, and a pointer a join left is followed to the dossier it joined, so one work is one entry.
    """
    from wayline import sections  # the sections render this module's file
    book = ledger_for(project_or_ledger)
    index = identifier_index(book.project) if index is None else index
    works, seen, orders = [], set(), {}
    for section in CITING:
        try:
            arranged = sections.arranged(book, section, orders=orders)
        except (OSError, ValueError, LedgerError):
            continue
        for _, current in arranged.headings:
            for item in current:
                for parts in ref_tags(item.get("text")):
                    work = work_named(book, parts, index)
                    if work is not None and work.key not in seen:
                        seen.add(work.key)
                        works.append(work)
    return works


def work_named(book, parts, index):
    """The work one parsed `ref` tag names, or None for a malformed tag."""
    if not parts:
        return None
    slug = ref_slug(parts, index)
    record = _dossier(book, slug) if slug else None
    if record is not None:
        return Work(("slug", record["slug"]), slug, record["slug"], record)
    if parts.get("slug"):
        return Work(("slug", parts["slug"]), parts["slug"])
    kind, _, value = parts["identifier"].partition(":")
    return Work((kind, normalize_title(value) if kind == "title" else value.lower()), parts["identifier"])


def give_up_days(project):
    """`policy.scout.give_up_days`, the days a `retry` flag is retried before it gives up."""
    try:
        return int((policy_for(project).get("scout") or {}).get("give_up_days", dossiers.GIVE_UP_DAYS))
    except (TypeError, ValueError):
        return dossiers.GIVE_UP_DAYS


def standing_of(record, now=None, days=None):
    """An unresolved work's state and what to say of it, `(state, detail)`; `record` None is a work no dossier holds."""
    if record is None:
        return TO_THE_SCOUT, "no lookup has answered yet"
    handed = record.get("handed_over") or []
    if handed and handed[-1].get("answer") == dossiers.LEAVE:
        return CLAIM_KEPT, "you said leave it on %s" % str(handed[-1].get("ts") or "")[:10]
    now = time.time() if now is None else now
    flag = record.get("retry") or {}
    state = dossiers.retry_state(record, now, dossiers.GIVE_UP_DAYS if days is None else days)
    if state in (dossiers.DUE, dossiers.NOT_YET):
        return RETRYING, "%s failed on %s: %s" % (flag.get("service", "a service"), str(flag.get("date") or "")[:10],
                                                   flag.get("failure", FAILED))
    if state in (dossiers.GAVE_UP, dossiers.GIVE_UP_NOW):
        return GAVE_UP, "retried daily from %s and given up; %s last failed: %s" % (
            str(flag.get("since") or flag.get("date") or "")[:10], flag.get("service", "a service"), flag.get("failure", FAILED))
    found = outcome(record)
    if found == NO_SUCH_WORK:
        return GAVE_UP, "every service asked answered no match"
    if found == NOT_LOOKED_UP and (record.get("query") or {}).get("kind") in _UNREACHABLE:
        return GAVE_UP, "a %s, which no service can look up" % ("URL" if record["query"]["kind"] == "url" else "file with no identifier")
    return TO_THE_SCOUT, "no lookup has answered yet"


def _identifier(record):
    """The identifier an entry shows: the DOI, else the arXiv id, else PubMed's, else the URL."""
    identifiers = record.get("identifiers") or {}
    for key, label in (("doi", "doi:%s"), ("arxiv_id", "arXiv:%s"), ("pmid", "PMID:%s"), ("url", "%s")):
        if identifiers.get(key):
            return label % identifiers[key]
    return None


def dossier_link(slug, base="../"):
    """A Markdown link to a dossier, from `research/sections/` by default."""
    return "[refs/%s](%srefs/%s/dossier.json)" % (slug, base, slug)


def _title(record):
    return _one_line((record.get("metadata") or {}).get("title") or (record.get("query") or {}).get("value"))


def _name(work):
    """What an unresolved work is called in the list: its slug, its title or the identifier it was asked by, and its dossier."""
    if work.slug is None:
        return "`%s`" % work.named
    record = work.record or {}
    query = record.get("query") or {}
    title = _one_line((record.get("metadata") or {}).get("title") or (query.get("value") if query.get("kind") == "title" else ""))
    asked = "*%s*" % title if title else ("`%s:%s`" % (query["kind"], query["value"]) if query.get("value") else "")
    return "`%s`%s %s" % (work.slug, ", %s," % asked if asked else "", dossier_link(work.slug))


def entry_line(number, record):
    """One numbered entry: authors to three then "et al.", the year, the title, the venue, the identifier, the dossier link."""
    metadata = record.get("metadata") or {}
    head = _authors(metadata.get("authors")) or ""
    if metadata.get("year"):
        head = ("%s (%s)" % (head, metadata["year"])).strip()
    parts = [head, _title(record) or record["slug"], "*%s*" % _one_line(metadata["container"]) if metadata.get("container") else "",
             _identifier(record) or ""]
    return "%d. %s. %s" % (number, ". ".join(part.rstrip(".") for part in parts if part), dossier_link(record["slug"]))


def csl_item(record):
    """One found dossier as a CSL-JSON item, its id the slug; every author is kept."""
    metadata, identifiers = record.get("metadata") or {}, record.get("identifiers") or {}
    kind = str(metadata.get("type") or "").lower()
    item = {"id": record["slug"], "type": _CSL_TYPES.get(kind, "article" if kind or identifiers.get("arxiv_id") else "article-journal")}
    if metadata.get("title"):
        item["title"] = metadata["title"]
    authors = [_csl_name(name) for name in metadata.get("authors") or [] if str(name).strip()]
    if authors:
        item["author"] = authors
    if metadata.get("year"):
        item["issued"] = {"date-parts": [[int(metadata["year"])]]}
    if metadata.get("container"):
        item["container-title"] = metadata["container"]
    for key, name in (("doi", "DOI"), ("pmid", "PMID"), ("pmcid", "PMCID"), ("url", "URL")):
        if identifiers.get(key):
            item[name] = identifiers[key]
    if identifiers.get("arxiv_id"):
        item["note"] = "arXiv:%s" % identifiers["arxiv_id"]
        item.setdefault("URL", "https://arxiv.org/abs/%s" % identifiers["arxiv_id"])
    return item


def _csl_name(name):
    """A name as the scout keeps it ("Given Family") as CSL's family and given; one word is the family alone."""
    words = str(name).split()
    return {"family": words[-1], "given": " ".join(words[:-1])} if len(words) > 1 else {"family": words[0]}


def references_view(project_or_ledger, now=None):
    """What References says now: `{entries: [dossier], unresolved: [(work, state, detail)]}`, both in first-citation order."""
    book = ledger_for(project_or_ledger)
    days = give_up_days(book.project)
    entries, unresolved = [], []
    for work in cited_works(book):
        if work.found:
            entries.append(work.record)
        else:
            state, detail = standing_of(work.record, now, days)
            unresolved.append((work, state, detail))
    return {"entries": entries, "unresolved": unresolved}


def _references_text(view):
    lines = ["# References", "", HEADER, ""]
    if view["entries"]:
        lines += [entry_line(number, record) for number, record in enumerate(view["entries"], start=1)] + [""]
    else:
        lines += [NOTHING_CITED, ""]
    lines += ["## %s" % NOT_YET_RESOLVED, ""]
    if view["unresolved"]:
        lines += ["- %s: %s (%s)" % (_name(work), state, detail) for work, state, detail in view["unresolved"]]
    else:
        lines.append(ALL_RESOLVED)
    return "\n".join(lines) + "\n"


def render_references(project_or_ledger, now=None):
    """Write `research/sections/references.md` and `research/references.json` from the dossiers; whether either changed.

    The section file carries the render stamp every section does (`sections.read_stamp`), and a body that did not change
    keeps its file and its stamp; `references.json` is written only when its items changed. Code alone writes both: an
    edit of `references.md` by hand is written over at its next change, since References is the dossiers'.
    """
    from wayline import sections  # the sections render this file after their own
    book = ledger_for(project_or_ledger)
    changed = False
    with book.lock():
        view = references_view(book, now)
        body = _references_text(view)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        stamp = sections.read_stamp(book, "references")
        if stamp is None or stamp.get("sha256") != digest:
            record = {"section": "references", "rendered_at": now_ts(), "last": None, "sha256": digest}
            book.write_markdown(REFERENCES_MD, "<!-- wayline:render %s -->\n%s" % (json.dumps(record, ensure_ascii=False), body))
            changed = True
        items = [csl_item(record) for record in view["entries"]]
        try:
            before = book.read_json(REFERENCES_JSON)
        except (OSError, ValueError):
            before = None
        if before != items:
            book.write_json(REFERENCES_JSON, items)
            changed = True
    return changed


def unresolved_count(project_or_ledger, now=None):
    """How many cited works References lists under Not yet resolved: the count the account's Library gives."""
    return len(references_view(project_or_ledger, now)["unresolved"])


# --- important ones raised (ticket 105) -----------------------------------------------------------------

# What makes an unresolved reference important, in the order one is looked for: `reference_raised`'s `reason`.
BY_OWNER, BY_PASSAGE, BY_CONCERN, BY_OBJECTIVE = PAYLOAD_ENUMS[(REFERENCE_RAISED, K_REASON)]
WHY_IMPORTANT = {BY_OWNER: "you named it", BY_PASSAGE: "a standing passage cites it", BY_CONCERN: "a concern cites it",
                 BY_OBJECTIVE: "an objective cites it"}
# Why a failure is final: `reference_raised`'s `outcome`.
NO_MATCH_ANYWHERE, FLAG_GAVE_UP, NOTHING_LOOKS_IT_UP = PAYLOAD_ENUMS[(REFERENCE_RAISED, K_OUTCOME)]
INTERACTIVE, CHECKPOINTS = PAYLOAD_ENUMS[(REFERENCE_RAISED, K_AUTONOMY)]
AUTONOMOUS = "autonomous"
NOT_YET_RESOLVED_LINK = "research/sections/references.md#not-yet-resolved"
# Neither an objective dropped or reframed nor a declined concern needs anything any more.
_SPENT_OBJECTIVES = ("dropped", "reframed")
_SPENT_CONCERNS = ("declined",)


def _final_outcome(record, state):
    """Why a failure in state `state` is final, or None while it is not."""
    if state != GAVE_UP:
        return None
    if record.get("retry"):
        return FLAG_GAVE_UP
    return NO_MATCH_ANYWHERE if outcome(record) == NO_SUCH_WORK else NOTHING_LOOKS_IT_UP


def important(project, now=None):
    """The important unresolved references, each once, in the order they were named: `[{slug, named, reason, state, detail,
    final, record}]`.

    Important: the owner named it at intake, or a standing passage or finding, a concern not declined, or an objective
    neither dropped nor reframed cites it (a `ref` tag in its text, its answer, or its evidence); `reason` is the first of
    these that holds. `final` is why its failure is final (`no such work`, `gave up`, `not looked up`), None while it is
    not; `slug` is None for a work no dossier holds yet, which is always to the scout.
    """
    from wayline.concerns import ConcernsUnreadable, read_concerns  # the concerns module reads the sections
    from wayline.objectives import ObjectivesUnreadable, read_objectives
    book = ledger_for(project)
    index = identifier_index(book.project)
    named = {}  # work key -> (work, reason), in the order first named

    def add(work, reason):
        if work is not None and not work.found and work.key not in named:
            named[work.key] = (work, reason)

    for reference in dossiers.read_intake(book.project):
        slug = dossiers.filed_slug(book, reference, index)
        record = _dossier(book, slug) if slug else None
        if record is not None:
            add(Work(("slug", record["slug"]), reference.raw, record["slug"], record), BY_OWNER)
    for work in cited_works(book, index):
        add(work, BY_PASSAGE)
    try:
        concerns = read_concerns(book)
    except ConcernsUnreadable:
        concerns = []
    for concern in concerns:
        if concern.get("status") in _SPENT_CONCERNS:
            continue
        texts = [source.get("text") for source in concern.get("sources") or []] + [concern.get("answer")]
        for parts in (parts for text in texts for parts in ref_tags(text)):
            add(work_named(book, parts, index), BY_CONCERN)
    try:
        objectives = read_objectives(book.project)
    except ObjectivesUnreadable:
        objectives = []
    for objective in objectives:
        if objective.get("status") in _SPENT_OBJECTIVES:
            continue
        found = ref_tags(objective.get("text")) + ref_tags(objective.get("answer"))
        found += [parse_tag(evidence)[1] for evidence in objective.get("evidence") or [] if str(evidence).startswith("ref:")]
        for parts in found:
            add(work_named(book, parts, index), BY_OBJECTIVE)
    days = give_up_days(book.project)
    items = []
    for work, reason in named.values():
        state, detail = standing_of(work.record, now, days)
        items.append({"slug": work.slug, "named": work.named, "reason": reason, "state": state, "detail": detail,
                      "final": _final_outcome(work.record, state) if work.record else None, "record": work.record})
    return items


def at_setup(project, now=None):
    """What setup asks about: every important unresolved reference the owner has not left, those still retrying included."""
    return [item for item in important(project, now) if item["state"] != CLAIM_KEPT]


def final(project, now=None):
    """The important unresolved references whose failure is final and that the owner has not left: what "Waiting on you"
    lists under every autonomy, and what is raised once under `interactive` and `checkpoints`."""
    return [item for item in important(project, now) if item["final"] is not None]


def _raised(events):
    """`{slug: the payload}` of every `reference_raised`, in the order raised."""
    return {(event.get("payload") or {}).get("slug"): event.get("payload") or {} for event in events
            if event.get("event") == REFERENCE_RAISED}


def notice_text(project, item):
    """The notice of one raised reference, linking to where it is listed and to its dossier."""
    title = _title(item["record"] or {})
    return ("%s: reference `%s`%s did not resolve (%s), and %s. Hand over its DOI, its exact title, or the PDF, or say leave it: %s "
            "(research/refs/%s/dossier.json)." % (Path(project).name, item["slug"], ", *%s*," % title if title else "", item["detail"],
                                                  WHY_IMPORTANT[item["reason"]], NOT_YET_RESOLVED_LINK, item["slug"]))


def raise_final(project, notify=None, say=None, now=None):
    """The conductor's step of one wave: each important reference whose failure became final, raised once. Returns them.

    Past setup only, and never under `autonomous`, where setup asked and the account lists it. Each is journaled as
    `reference_raised`, once; under `interactive` a notice linking to it goes out through `notify(event, text, project,
    ticket)` as well. Under `checkpoints` the journal line is the whole of it here: the account lists it under "Waiting
    on you", the next conversation puts it (`waiting`), and the end notice names it. One still retrying, or left, waits.
    """
    from wayline.stopping import after_setup  # the stopping module imports the goal module, which imports the gates
    say = say or (lambda line: None)
    book = ledger_for(project)
    raised = []
    with book.lock():
        events, _ = book.read_events()
        if not after_setup(events):
            return []
        try:
            autonomy = read_harness(book.project).get("autonomy")
        except (ProjectError, OSError, ValueError):
            return []
        if autonomy == AUTONOMOUS:
            return []
        autonomy = CHECKPOINTS if autonomy == CHECKPOINTS else INTERACTIVE
        before = _raised(events)
        for item in final(book.project, now):
            if item["slug"] is None or item["slug"] in before:
                continue
            book.append_event(REFERENCE_RAISED, {"slug": item["slug"], "reason": item["reason"], "outcome": item["final"],
                                                 "autonomy": autonomy})
            raised.append(item)
    for item in raised:
        say("  reference %s did not resolve (%s) and %s: raised to the owner" % (item["slug"], item["detail"], WHY_IMPORTANT[item["reason"]]))
        if autonomy == INTERACTIVE and notify is not None:
            notify(REFERENCE_RAISED, notice_text(book.project, item), book.project, None)
    return raised


def waiting(project, now=None):
    """What the next conversation puts to the owner first: each raised reference still final and not left, in the order raised."""
    book = ledger_for(project)
    events, _ = book.read_events()
    order = list(_raised(events))
    still = {item["slug"]: item for item in final(book.project, now) if item["slug"] in order}
    return [still[slug] for slug in order if slug in still]


def waiting_line(item):
    """One line of "Waiting on you" for an important reference whose failure is final."""
    title = _title(item["record"] or {})
    return "- Reference `%s`%s did not resolve (%s), and %s: `wayline reference %s <doi|title|file.pdf|\"leave it\">`." % (
        item["slug"], ", *%s*," % title if title else "", item["detail"], WHY_IMPORTANT[item["reason"]], item["slug"])


def _one_line(text):
    return " ".join(str(text or "").split())
