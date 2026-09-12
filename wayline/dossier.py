"""Dossiers at L0, L1, and L2 (Implementation Decisions 9): what a reference becomes on disk.

This module builds level 0, which is the level every reference gets: the scout's verified
identifiers, the metadata, the abstract, and a knowledge-base node, written to
`research/refs/<slug>/dossier.json`. Levels 1 and 2 (the skim and the full absorb) are tickets
21 to 25; the record they extend is the one written here.

`wayline absorb --level 0` is the verb: it reads the reference list out of `INTAKE.md`, resolves
each one through the scout, and writes a dossier and a node for every one of them, the
unresolved included. An L0 pass costs nothing but requests, so it is safe to run again: a
reference already resolved is answered out of `research/.cache/scout/` without a new request.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from wayline.cli import parse_args
from wayline.fetch import caching_fetcher, recording_fetcher
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.kb import ID_MAX, make_node, rebuild_query_pack, slugify, write_node
from wayline.ledger import ledger_for, now_ts
from wayline.project import HARNESS_JSON, ProjectError, find_project, policy_for, read_harness
from wayline.scout import Reference, Scout, UNRESOLVED, parse_reference

__all__ = [
    "DossierError", "REFS", "CACHE", "LEVEL_0", "slug_for", "l0_dossier", "write_l0",
    "intake_references", "read_intake", "absorb_level_0", "absorb_command", "scout_fetcher",
]

REFS = "refs"
CACHE = ".cache/scout"
LEVEL_0 = 0
QUERY_PACK_MAX = 20000  # the fallback when a policy carries no `kb.query_pack_max_chars`
INTAKE = "INTAKE.md"

# Words a slug drops: they carry no identity and eat the character budget.
_STOPWORDS = frozenset("a an the of for and or to in on with by via using is are at from".split())
STEM_MAX = ID_MAX - 10  # room under a node id's cap for the `-2` a clashing slug takes
_SENTENCE_END = ".:;,!?"
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_REFERENCES_HEADING = re.compile(r"^references?\b", re.IGNORECASE)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_EMPTY_ANSWER = frozenset(["none", "n/a", "na", "nothing", "tbd", "todo", "-", "none."])
_ALNUM = re.compile(r"[a-z0-9]", re.IGNORECASE)
_DOI_OR_ID = re.compile(r"\b10\.\d{4,9}/|arxiv|https?://", re.IGNORECASE)


class DossierError(ValueError):
    """A dossier the harness will not write, or an intake it cannot read a reference out of."""


# --- the slug -----------------------------------------------------------------------------------


def slug_for(record, taken=()):
    """`<family name>-<year>-<first title words>` for a resolved reference, the query for the rest.

    The slug is a directory name a person reads in a file tree, so it is built from what a
    person recognizes. A reference that resolved nowhere still gets one, out of what the owner
    wrote, because an unresolved reference is a record like any other and has to live somewhere.
    """
    metadata = record.get("metadata") or {}
    identifiers = record.get("identifiers") or {}
    parts = []
    authors = metadata.get("authors") or []
    if authors:
        parts.append(slugify(_family_name(authors[0])))
    if metadata.get("year"):
        parts.append(str(metadata["year"]))
    words = [word for word in slugify(metadata.get("title") or "").split("-") if word and word not in _STOPWORDS]
    parts.extend(words[:5])
    stem = "-".join(part for part in parts if part).strip("-")
    if not stem:
        stem = slugify(identifiers.get("arxiv_id") or identifiers.get("doi") or (record.get("query") or {}).get("value") or "")
    stem = slugify(stem, STEM_MAX) or "reference"
    candidate, suffix = stem, 1
    while candidate in taken:
        suffix += 1
        candidate = "%s-%d" % (slugify(stem, STEM_MAX - len(str(suffix)) - 1), suffix)
    return candidate


def _family_name(author):
    """The name a person is filed under, from either spelling a service uses.

    Crossref and OpenAlex give "Ashish Vaswani"; the preprint servers give "Gordon, David E.".
    Taking the last word of the second form would file the paper under an initial.
    """
    name = str(author or "").strip()
    if "," in name:
        return name.split(",", 1)[0].strip()
    words = [word for word in name.split() if word.strip(".")]
    return words[-1] if words else ""




# --- the record ---------------------------------------------------------------------------------


def l0_dossier(scout_record, slug, created=None):
    """The scout's answer as a validated level 0 dossier."""
    dossier = {
        "schema_version": 1,
        "slug": slug,
        "level": LEVEL_0,
        "existence": scout_record["existence"],
        "resolved_by": scout_record.get("resolved_by"),
        "query": dict(scout_record["query"]),
        "identifiers": dict(scout_record.get("identifiers") or {}),
        "metadata": dict(scout_record.get("metadata") or {}),
        "abstract": scout_record.get("abstract"),
        "open_access": dict(scout_record.get("open_access") or {}),
        "attempts": list(scout_record.get("attempts") or []),
        "created": created or now_ts(),
    }
    check(dossier, load_schema("dossier"), name="refs/%s/dossier.json" % slug)
    return dossier


def write_l0(project_or_ledger, dossier):
    """Write `refs/<slug>/dossier.json` and the knowledge-base node that points at it.

    The node is written whether or not the reference resolved: the graph has to be able to say
    that a reference was named and did not resolve, which is a fact about the project.
    """
    ledger = ledger_for(project_or_ledger)
    path = ledger.write_json("%s/%s/dossier.json" % (REFS, dossier["slug"]), dossier, schema="dossier")
    node = make_node(
        dossier["slug"],
        "paper",
        (dossier["metadata"].get("title") or dossier["query"].get("raw") or dossier["query"]["value"]),
        identifiers=dossier["identifiers"] or None,
        year=dossier["metadata"].get("year"),
        level=dossier["level"],
        existence=dossier["existence"],
        source=dossier.get("resolved_by"),
        created=dossier["created"],
    )
    write_node(ledger, node)
    ledger.append_event("absorbed", {"slug": dossier["slug"], "level": LEVEL_0})
    return path


# --- the intake ---------------------------------------------------------------------------------


def intake_references(text):
    """The reference lines of an `INTAKE.md`, parsed.

    The references live under a `## References` heading. When anything under it is a list item,
    the list items are the references and the prose around them is prose, which is what keeps a
    sentence introducing the list from being looked up as a paper. When nothing is a list item,
    every line is taken, because a bare list of DOIs is a list too. A line that only says the
    owner has none is never looked up: resolving the word "None" is a request spent on nothing.
    """
    lines, collecting, found, listed = str(text or "").splitlines(), False, [], []
    for line in lines:
        heading = _HEADING.match(line)
        if heading is not None:
            collecting = bool(_REFERENCES_HEADING.match(heading.group(1).strip()))
            continue
        if not collecting:
            continue
        stripped = line.strip()
        if not stripped or not _ALNUM.search(stripped):
            continue
        if _says_none(stripped):
            continue
        found.append(stripped)
        if _LIST_ITEM.match(stripped):
            listed.append(stripped)
    found = listed or found
    references, seen = [], set()
    for line in found:
        try:
            reference = parse_reference(line)
        except ValueError:
            continue
        key = (reference.kind, reference.value.lower())
        if key in seen:
            continue
        seen.add(key)
        references.append(reference)
    return references


def _says_none(line):
    """Whether a line under the heading is the owner saying there are no references.

    "None." and "None. A fixture that needed a dossier would not be a fixture." are both that
    answer, because the word closes a sentence of its own. "Nothing is known about X" is a title
    and is looked up, because the word runs on into the sentence. A line carrying an identifier
    is never this answer, whatever word it opens with.
    """
    if _DOI_OR_ID.search(line):
        return False
    line = _LIST_MARKER.sub("", line).strip()
    if line.lower().rstrip(".").strip() in _EMPTY_ANSWER:
        return True
    words = line.split()
    if not words:
        return False
    opener = words[0].lower()
    return opener.rstrip(_SENTENCE_END) in _EMPTY_ANSWER and (len(words) == 1 or opener[-1:] in _SENTENCE_END)


def read_intake(project):
    """The references named in the project's `INTAKE.md`; an absent file means no references."""
    path = Path(project) / "research" / INTAKE
    try:
        return intake_references(path.read_text(encoding="utf-8"))
    except OSError:
        return []


# --- the verb -----------------------------------------------------------------------------------


def scout_fetcher(project, email=None, fixtures=None):
    """The fetcher the scout runs on: the project's cache, or a directory of recorded responses."""
    if fixtures is not None:
        return recording_fetcher(fixtures, email=email)
    return caching_fetcher(Path(project) / "research" / CACHE, email=email)


def absorb_level_0(project, references=None, fetcher=None, email=None, ledger=None):
    """Resolve every reference and write its L0 dossier, node, and the query pack. Returns a report.

    A reference already on disk is resolved again and its dossier replaced, because the cache
    makes that free and a reference that was unresolved last week may resolve today. The slug of
    a dossier that already exists is kept, so a re-run never leaves two directories for one work.
    """
    project = Path(project)
    ledger = ledger_for(ledger if ledger is not None else project)
    if email is None:
        email = _email(project)
    fetcher = fetcher if fetcher is not None else scout_fetcher(project, email=email)
    references = references if references is not None else read_intake(project)
    scout = Scout(fetcher, email)

    known = _known_slugs(ledger)
    taken = set(known.values())
    report = {"project": str(project), "references": len(references), "written": [], "verified": 0, "unresolved": 0, "problems": [], "notes": []}
    if not email:
        report["notes"].append(
            "no owner address in %s; the requests carry no mailto, which is what the polite pools ask for "
            "(add \"owner_email\" to harness.json, or lay the project out with wayline init --email <address>)" % HARNESS_JSON
        )
    for reference in references:
        if not isinstance(reference, Reference):
            reference = parse_reference(reference)
        key = (reference.kind, reference.value.lower())
        try:
            resolved = scout.resolve(reference)
            slug = known.get(key) or slug_for(resolved, taken)
            dossier = l0_dossier(resolved, slug)
            write_l0(ledger, dossier)
        except (ValidationError, ValueError, OSError) as failure:
            report["problems"].append({"reference": reference.raw, "problem": str(failure)})
            continue
        known[key] = slug
        taken.add(slug)
        report["written"].append({"slug": slug, "existence": dossier["existence"], "resolved_by": dossier["resolved_by"], "reference": reference.raw})
        report["verified" if dossier["existence"] != UNRESOLVED else "unresolved"] += 1
    rebuild_query_pack(ledger, policy_for(project).get("kb", {}).get("query_pack_max_chars", QUERY_PACK_MAX))
    return report


def _known_slugs(ledger):
    """The slug each already-written dossier was filed under, by the question it answered."""
    known = {}
    directory = ledger.research / REFS
    if not directory.is_dir():
        return known
    for path in sorted(directory.glob("*/dossier.json")):
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            query = existing["query"]
            known[(query["kind"], str(query["value"]).lower())] = existing["slug"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return known


def absorb_command(args):
    parser = argparse.ArgumentParser(prog="wayline absorb", description="build the dossiers for the references")
    parser.add_argument("--level", type=int, default=0, choices=[0, 1, 2], help="the dossier level to build; only level 0 is built so far")
    parser.add_argument("--project", help="the project to absorb into; the active one by default")
    parser.add_argument("--fixtures", help="answer every request from this directory of recorded responses instead of the network")
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.level != LEVEL_0:
        print("wayline absorb: level %d needs the inventory and the skim, which tickets 21 to 24 build" % options.level, file=sys.stderr)
        return 2
    try:
        project = find_project(options.project)
        fetcher = scout_fetcher(project, email=_email(project), fixtures=options.fixtures) if options.fixtures else None
        report = absorb_level_0(project, fetcher=fetcher)
    except (ProjectError, ValidationError, ValueError, OSError) as failure:
        print("wayline absorb: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render(report))
    return 1 if report["problems"] else 0


def _email(project):
    """The address the polite pools are told about, from the project's `harness.json`."""
    try:
        return read_harness(project).get("owner_email")
    except (ProjectError, OSError, ValueError):
        return None


def _render(report):
    lines = ["references  %d  (%d verified, %d unresolved)" % (report["references"], report["verified"], report["unresolved"])]
    for written in report["written"]:
        lines.append("  %-10s %-50s %s" % (written["existence"], written["slug"], written["resolved_by"] or ""))
    for problem in report["problems"]:
        lines.append("  problem    %s: %s" % (problem["reference"], problem["problem"]))
    for note in report["notes"]:
        lines.append("  note       %s" % note)
    if not report["written"] and not report["problems"]:
        lines.append("  nothing to absorb; INTAKE.md names no references")
    return "\n".join(lines)
