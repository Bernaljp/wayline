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
slug or by its identifier (`{ref:doi:10.1038/x#abstract}`, `{ref:arxiv:1802.03426#abstract}`), mapped
through position's identifier index, and its locator must name what the dossier holds at its level:
`abstract` or `metadata.<field>` at L0 and L1, and at L2 an entry's locator as well. Dossiers stay at
L0 when cited.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from wayline import dossier as dossiers
from wayline.cli import parse_args
from wayline.ledger import SCOUTED, LedgerError, ledger_for
from wayline.project import ProjectError, find_project, policy_for
from wayline.provenance import TAG_RE, identifier_index, parse_tag, ref_slug
from wayline.scout import FAILED, FOUND, NO_SUCH_WORK, VERIFIED, ScoutError, outcome, parse_reference

__all__ = [
    "CALLS_PER_TICKET", "LOOKED_UP_KINDS", "ReferenceError_", "ScoutRefused", "call_limit", "calls_made", "looked_up", "scout", "scout_command", "render",
    "cited", "held_locators", "check_references",
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
    neither a found dossier nor known yet: each listed one, and each cited by `doi:` or `arxiv:` that no
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
        key = (reference.kind, reference.value.lower())
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
        listed[(reference.kind, reference.value.lower())] = slug
    for tag, parts in cited(result):
        if parts is None:
            problems.append("`{%s}` is not a `ref` tag: write `{ref:<slug>#<locator>}`, or `doi:` or `arxiv:` with the identifier in place of the slug" % tag)
            continue
        slug = ref_slug(parts, index())
        if parts.get("identifier"):
            prefix, _, value = parts["identifier"].partition(":")
            named = (prefix, value.lower())
            if named in invented:
                continue  # sent back already, as a work no service knows
            slug = slug or listed.get(named)
            if slug is None or (_dossier(ledger, slug) or {}).get("existence") != VERIFIED:
                slug = look_up(looked_up(parts["identifier"]), "`{%s}`" % tag)
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
