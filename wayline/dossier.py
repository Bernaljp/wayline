"""Dossiers at L0, L1, and L2 (Implementation Decisions 9): what a reference becomes on disk.

Level 0, which every reference gets, is the scout's verified identifiers, the metadata, the
abstract, and a knowledge-base node, written to `research/refs/<slug>/dossier.json`.
`wayline absorb --level 0` reads the reference list out of `INTAKE.md`, resolves each one through
the scout, and writes a dossier and a node for every one of them, the unresolved included. An L0
pass costs nothing but requests, so it is safe to run again: a reference already resolved is
answered out of `research/.cache/scout/` without a new request.

Level 1 is one `reader` (sonnet, medium) call per paper over a capped input, merged into the same
dossier by `absorb_level_1` (`wayline absorb --level 1 <slug>...`). Level 2, the full absorb
workflow (ticket 24), is not built here; what this module does have is the depth budget itself:
`promote` decides, for a trigger of Implementation Decisions 9, whether a paper earns a level-2
read inside `policy.absorb.l2_per_phase` for the current phase, or opens a `decision` ticket
beyond it, and `demote` lowers a level with its own trigger. `render_levels_report` is the
minimal stand-in for the M5 report's "papers not read in full and why" until that report exists.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline import worker
from wayline.cli import parse_args
from wayline.fetch import caching_fetcher, recording_fetcher
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.kb import ID_MAX, NODES_DIR, make_node, rebuild_query_pack, slugify, write_node
from wayline.ledger import ledger_for, now_ts
from wayline.project import HARNESS_JSON, ProjectError, find_project, policy_for, read_harness
from wayline.scout import Reference, Scout, UNRESOLVED, parse_reference
from wayline.tickets import DECISION as DECISION_KIND, TicketError, read_tickets, write_ticket

__all__ = [
    "DossierError", "REFS", "CACHE", "LEVEL_0", "LEVEL_1", "LEVEL_2", "slug_for", "l0_dossier", "write_l0",
    "intake_references", "read_intake", "absorb_level_0", "absorb_command", "scout_fetcher",
    "read_dossier", "l1_input", "l1_prompt", "l1_request", "absorb_level_1",
    "PRIMARY_AT_INTAKE", "CITED_BY_SPEC", "CONTEXT_PACK", "CONSULTANT_QUESTION", "PLANNER_OR_DECIDER",
    "TRIGGERS", "promote", "demote", "render_levels_report", "render_levels_text",
]

REFS = "refs"
CACHE = ".cache/scout"
LEVEL_0 = 0
LEVEL_1 = 1
LEVEL_2 = 2
QUERY_PACK_MAX = 20000  # the fallback when a policy carries no `kb.query_pack_max_chars`
L1_MAX_CHARS = 40000  # the fallback when a policy carries no `absorb.l1_max_chars`
INTAKE = "INTAKE.md"

# The five triggers of Implementation Decisions 9, in the spec's order.
PRIMARY_AT_INTAKE = "primary_at_intake"
CITED_BY_SPEC = "cited_by_spec"
CONTEXT_PACK = "context_pack"
CONSULTANT_QUESTION = "consultant_question"
PLANNER_OR_DECIDER = "planner_or_decider"
TRIGGERS = (PRIMARY_AT_INTAKE, CITED_BY_SPEC, CONTEXT_PACK, CONSULTANT_QUESTION, PLANNER_OR_DECIDER)

# What each trigger reads as in a decision ticket's body, and who it is proposed by absent an override.
_TRIGGER_LABELS = {
    PRIMARY_AT_INTAKE: "named primary at intake",
    CITED_BY_SPEC: "cited by a spec claim, baseline, or method to implement",
    CONTEXT_PACK: "named in a ticket's context pack",
    CONSULTANT_QUESTION: "a consultant question L1 cannot answer",
    PLANNER_OR_DECIDER: "the planner or the decider promotes",
}
_TRIGGER_PROPOSED_BY = {
    PRIMARY_AT_INTAKE: "human",
    CITED_BY_SPEC: "planner",
    CONTEXT_PACK: "planner",
    CONSULTANT_QUESTION: "decider",
    PLANNER_OR_DECIDER: "decider",
}
_PROMOTE_TITLE = re.compile(r"^Promote (?P<slug>.+) to level 2\?\Z")

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


def _all_slugs(ledger):
    """Every slug with a dossier on disk, in file order."""
    directory = ledger.research / REFS
    if not directory.is_dir():
        return []
    return sorted(path.parent.name for path in directory.glob("*/dossier.json"))


def read_dossier(project_or_ledger, slug):
    """`refs/<slug>/dossier.json`, read fresh; raises DossierError when there is none yet."""
    ledger = ledger_for(project_or_ledger)
    try:
        return ledger.read_json("%s/%s/dossier.json" % (REFS, slug))
    except (OSError, ValueError):
        raise DossierError("no dossier for %r; run `wayline absorb --level 0` first" % (slug,)) from None


def _write_dossier(ledger, dossier):
    check(dossier, load_schema("dossier"), name="refs/%s/dossier.json" % dossier["slug"])
    return ledger.write_json("%s/%s/dossier.json" % (REFS, dossier["slug"]), dossier)


def _update_node_level(ledger, slug, level):
    """Keep the knowledge-base node's level in step with its dossier's; a missing node is not an error."""
    path = "%s/%s.json" % (NODES_DIR, slug)
    try:
        node = ledger.read_json(path)
    except (OSError, ValueError):
        return
    if isinstance(node, dict):
        node["level"] = level
        ledger.write_json(path, node)


def _intake_text(project):
    """`INTAKE.md` whole, for the intent the L1 skim reads against; None when the project has none yet."""
    try:
        return (Path(project) / "research" / INTAKE).read_text(encoding="utf-8")
    except OSError:
        return None


# --- level 1: the skim ---------------------------------------------------------------------------


def _read_inventory(ledger, slug):
    """`refs/<slug>/inventory.json` (tickets 21 and 22), when a project already has one."""
    try:
        value = ledger.read_json("%s/%s/inventory.json" % (REFS, slug))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _inventory_sections(inventory):
    """Introduction, conclusion, figure captions, and results table headers, out of an inventory."""
    rendered = []
    for section in inventory.get("sections") or []:
        title = str(section.get("title") or "")
        if re.search(r"\bintroduction\b|\bconclusion\b", title, re.IGNORECASE):
            body = section.get("text")
            if body:
                rendered.append("## %s\n\n%s" % (title, body))
    captions = [figure.get("caption") for figure in (inventory.get("figures") or []) if figure.get("caption")]
    if captions:
        rendered.append("## Figure captions\n\n" + "\n".join("- %s" % caption for caption in captions))
    headers = [table.get("caption") for table in (inventory.get("tables") or []) if table.get("caption")]
    if headers:
        rendered.append("## Results table headers\n\n" + "\n".join("- %s" % header for header in headers))
    return rendered


def _read_text_layer(ledger, slug):
    """Whatever plain text a converter already dropped under `refs/<slug>/`, for a project with no inventory yet."""
    directory = ledger.research / REFS / slug
    for name in ("text.txt", "fulltext.txt"):
        path = directory / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
    texts = []
    for path in sorted((directory / "source").glob("*.txt")) if (directory / "source").is_dir() else []:
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n\n".join(texts) if texts else None


def l1_input(project_or_ledger, slug, max_chars=L1_MAX_CHARS):
    """The capped input for one L1 skim: title, abstract, and the inventory or the text layer.

    Tickets 21 and 22 build the inventory (sections, figures, tables); until a project has one for
    this slug, the skim falls back to whatever plain text a converter already left under the
    reference's own directory, and further back to the title and abstract L0 already verified.
    Returns `(text, cut)`; `cut` is true when there was more than `max_chars` would hold.
    """
    ledger = ledger_for(project_or_ledger)
    dossier = read_dossier(ledger, slug)
    parts = []
    title = (dossier.get("metadata") or {}).get("title")
    if title:
        parts.append("# %s" % title)
    abstract = dossier.get("abstract")
    if abstract:
        parts.append("## Abstract\n\n%s" % abstract)
    inventory = _read_inventory(ledger, slug)
    if inventory is not None:
        parts.extend(_inventory_sections(inventory))
    else:
        text_layer = _read_text_layer(ledger, slug)
        if text_layer:
            parts.append("## Text\n\n%s" % text_layer)
    text = ("\n\n".join(parts)).strip()
    text = (text + "\n") if text else ""
    cap = max(0, int(max_chars))
    cut = len(text) > cap
    return text[:cap], cut


L1_INSTRUCTIONS = (
    "You are skimming one reference for a research project, at a capped budget. Read the "
    "material below and return the structured result: one line on how this paper relates to "
    "the project's stated intent, and one line on what would make it worth a full read."
)


def l1_prompt(intent, capped_text, cut):
    """The whole prompt for one L1 call: the instructions, the intent, the capped paper, the cut notice."""
    parts = [L1_INSTRUCTIONS]
    if intent:
        parts.append("## The project's intent\n\n%s" % intent.strip())
    parts.append("## The paper\n\n%s" % (capped_text.strip() or "(nothing was readable for this reference)"))
    if cut:
        parts.append("[wayline: the paper's material was cut here at the L1 character cap; some of it was left out.]")
    return "\n\n".join(parts) + "\n"


def l1_request(project, slug, capped_text, cut, harness_root=None, intent=None):
    """The `LaunchRequest` for one L1 skim: the `reader` role, sonnet, medium effort (decision 9)."""
    harness_root = Path(harness_root or HARNESS_ROOT)
    role = worker.read_role("reader", harness_root, project)
    name = "l1-%s" % slug
    return worker.LaunchRequest(
        role=role.name, model="sonnet", effort="medium",
        prompt=l1_prompt(intent, capped_text, cut),
        agent_json=role.agent_json("sonnet", "medium", max_turns=6),
        allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
        settings_path=None, add_dirs=[], cwd=project,
        env=worker.session_env(project, name, 1, touches=(), harness_root=harness_root),
        schema_path=harness_root / "schemas" / ((role.output_schema or "l1_record") + ".json"),
        max_minutes=5,
    )


def absorb_level_1(project, slugs=None, launcher=None, harness_root=None, ledger=None):
    """Skim each slug at level 1: one `reader` call per paper, merged into its dossier. Returns a report.

    `slugs` defaults to every slug on disk not already at level 1 or above, so `wayline absorb
    --level 1` with no names catches a project up. A slug already skimmed is left alone: an L1
    call costs a turn, and a dossier already past level 0 does not need repeating.
    """
    project = Path(project)
    ledger = ledger_for(ledger if ledger is not None else project)
    launcher = launcher or worker.launch
    max_chars = (policy_for(project).get("absorb") or {}).get("l1_max_chars", L1_MAX_CHARS)
    intent = _intake_text(project)
    slugs = list(slugs) if slugs else [slug for slug in _all_slugs(ledger) if read_dossier(ledger, slug).get("level", LEVEL_0) < LEVEL_1]
    report = {"project": str(project), "skimmed": [], "problems": []}
    for slug in slugs:
        try:
            dossier = read_dossier(ledger, slug)
            if dossier.get("level", LEVEL_0) >= LEVEL_1:
                report["skimmed"].append({"slug": slug, "status": "already level %d" % dossier["level"], "cut": False})
                continue
            capped, cut = l1_input(ledger, slug, max_chars)
            request = l1_request(project, slug, capped, cut, harness_root=harness_root, intent=intent)
            envelope = launcher(request)
            if not envelope.valid:
                raise DossierError("the L1 session for %s returned no valid structured result: %s"
                                   % (slug, "; ".join(envelope.errors) or "no reason given"))
            record = envelope.structured_output
            dossier["level"] = LEVEL_1
            dossier["relation_to_intent"] = record["relation_to_intent"]
            dossier["deserves_l2_if"] = record["deserves_l2_if"]
            dossier["updated"] = now_ts()
            _write_dossier(ledger, dossier)
            _update_node_level(ledger, slug, LEVEL_1)
            ledger.append_event("absorbed", {"slug": slug, "level": LEVEL_1, "session_id": envelope.session_id}, session_id=envelope.session_id)
            report["skimmed"].append({"slug": slug, "status": "skimmed", "cut": cut})
        except (DossierError, ValidationError, worker.LaunchError, OSError) as failure:
            report["problems"].append({"slug": slug, "problem": str(failure)})
    return report


# --- levels 1 and 2: promotion and demotion (Implementation Decisions 9) -------------------------


def _current_phase(events):
    """The phase the journal last moved to; P1 (where absorb runs) when the journal names none yet."""
    phase = None
    for event in events:
        if event.get("event") == "phase":
            candidate = (event.get("payload") or {}).get("to")
            if candidate:
                phase = candidate
    return phase or "P1"


def _l2_used_in_phase(events, phase):
    """`promoted` events to level 2 since the phase last started; a phase re-entered starts a fresh budget."""
    start = 0
    for index, event in enumerate(events):
        if event.get("event") == "phase" and (event.get("payload") or {}).get("to") == phase:
            start = index + 1
    used = 0
    for event in events[start:]:
        if event.get("event") == "promoted" and (event.get("payload") or {}).get("to_level") == LEVEL_2:
            used += 1
    return used


def promote(project_or_ledger, slug, trigger, phase=None, ticket=None, proposed_by=None, detail=None):
    """Promote `slug` to level 2 on `trigger`, inside `policy.absorb.l2_per_phase`, else open a decision ticket.

    `trigger` is one of the five of Implementation Decisions 9. Inside the current phase's budget
    the dossier is promoted at once and `promoted` is journaled with the trigger; beyond it, a
    `decision` ticket is opened (its `origin` carries the trigger and the budget it exceeded) and
    `ticket_created` and `decision_opened` are journaled. A slug already at level 2 is a no-op.
    Returns a dict describing what happened.
    """
    if trigger not in TRIGGERS:
        raise DossierError("promotion trigger %r is not one of %s" % (trigger, list(TRIGGERS)))
    ledger = ledger_for(project_or_ledger)
    dossier = read_dossier(ledger, slug)
    from_level = dossier.get("level", LEVEL_0)
    if from_level >= LEVEL_2:
        return {"promoted": False, "reason": "already level 2"}
    events, _ = ledger.read_events()
    phase = phase or _current_phase(events)
    limit = ((policy_for(ledger.project).get("absorb") or {}).get("l2_per_phase") or {}).get(phase)
    used = _l2_used_in_phase(events, phase)
    if limit is None or used < limit:
        dossier["level"] = LEVEL_2
        dossier["updated"] = now_ts()
        _write_dossier(ledger, dossier)
        _update_node_level(ledger, slug, LEVEL_2)
        ledger.append_event("promoted", {"slug": slug, "from_level": from_level, "to_level": LEVEL_2, "trigger": trigger}, ticket=ticket)
        return {"promoted": True, "phase": phase, "used": used + 1, "limit": limit}
    ticket_id = _open_promotion_decision(ledger, slug, trigger, phase, used, limit, proposed_by, ticket, detail)
    return {"promoted": False, "decision_ticket": ticket_id, "phase": phase, "used": used, "limit": limit}


def _open_promotion_decision(ledger, slug, trigger, phase, used, limit, proposed_by, ticket, detail):
    """A `decision` ticket asking whether `slug` still earns level 2 beyond the phase's budget."""
    if proposed_by is None:
        proposed_by = "worker:%d" % ticket if trigger == CONSULTANT_QUESTION and ticket else _TRIGGER_PROPOSED_BY[trigger]
    next_id = max((existing["id"] for existing in read_tickets(ledger.project)), default=0) + 1
    budget_text = "%d of %s L2 slot(s) already used" % (used, limit if limit is not None else "unlimited")
    origin = "%s; phase %s, %s" % (_TRIGGER_LABELS[trigger], phase, budget_text)
    if detail:
        origin += "; " + str(detail)
    fields = {
        "id": next_id, "title": "Promote %s to level 2?" % slug, "kind": DECISION_KIND,
        "difficulty": 1, "status": "open", "blocked_by": [], "blocking": None, "human_only": False,
        "touches": [], "role": "decider", "acceptance": {}, "proposed_by": proposed_by,
        "context_pack": ["%s/%s/dossier.json" % (REFS, slug)], "origin": origin,
        "demo": "Read refs/%s/dossier.json and decide whether it earns a full level-2 read." % slug,
    }
    body = (
        "## Decision\n\nPromote `%s` to level 2 (a full read)?\n\n"
        "Trigger: %s.\n\nBudget: phase %s allows %s level-2 read(s) at a time; %s.\n"
    ) % (slug, _TRIGGER_LABELS[trigger], phase, limit if limit is not None else "unlimited", budget_text)
    write_ticket(ledger, fields, body)
    ledger.append_event("ticket_created", {"ticket": next_id, "kind": DECISION_KIND, "proposed_by": proposed_by, "origin": origin, "blocked_by": []}, ticket=next_id)
    ledger.append_event("decision_opened", {"ticket": next_id, "blocking": None, "human_only": False}, ticket=next_id)
    return next_id


def demote(project_or_ledger, slug, to_level, trigger, ticket=None):
    """Lower `slug`'s dossier level, journaling `demoted` with `trigger` (free text: decision 9 names no fixed list)."""
    if to_level not in (LEVEL_0, LEVEL_1):
        raise DossierError("demote only lowers to level 0 or 1, got %r" % (to_level,))
    if not str(trigger or "").strip():
        raise DossierError("a demotion needs a trigger to journal")
    ledger = ledger_for(project_or_ledger)
    dossier = read_dossier(ledger, slug)
    from_level = dossier.get("level", LEVEL_0)
    if to_level >= from_level:
        raise DossierError("%s is at level %d already, not above %d" % (slug, from_level, to_level))
    dossier["level"] = to_level
    if to_level < LEVEL_1:
        dossier.pop("relation_to_intent", None)
        dossier.pop("deserves_l2_if", None)
    dossier["updated"] = now_ts()
    _write_dossier(ledger, dossier)
    _update_node_level(ledger, slug, to_level)
    ledger.append_event("demoted", {"slug": slug, "from_level": from_level, "to_level": to_level, "trigger": str(trigger)}, ticket=ticket)
    return {"from_level": from_level, "to_level": to_level}


# --- the minimal report: papers by level, and what was not read in full -------------------------


def render_levels_report(project):
    """Slugs grouped by level, and every open promotion decision (a paper not read in full) with why."""
    ledger = ledger_for(project)
    by_level = {LEVEL_0: [], LEVEL_1: [], LEVEL_2: []}
    for slug in _all_slugs(ledger):
        try:
            dossier = read_dossier(ledger, slug)
        except DossierError:
            continue
        by_level.setdefault(dossier.get("level", LEVEL_0), []).append(slug)
    pending = []
    try:
        for fields in read_tickets(ledger.project):
            if fields["kind"] != DECISION_KIND or fields["status"] != "open":
                continue
            match = _PROMOTE_TITLE.match(fields["title"])
            if match:
                pending.append({"slug": match.group("slug"), "ticket": fields["id"], "reason": fields.get("origin")})
    except TicketError:
        pass
    return {"by_level": {level: sorted(slugs) for level, slugs in by_level.items()}, "not_read_in_full": pending}


def render_levels_text(report):
    lines = ["papers by level"]
    for level in sorted(report["by_level"]):
        slugs = report["by_level"][level]
        lines.append("  L%d  %-3d  %s" % (level, len(slugs), ", ".join(slugs)))
    if report["not_read_in_full"]:
        lines.append("not read in full:")
        for item in report["not_read_in_full"]:
            lines.append("  %-40s ticket %-4s %s" % (item["slug"], item["ticket"], item["reason"] or ""))
    else:
        lines.append("not read in full: none")
    return "\n".join(lines)


def absorb_command(args):
    parser = argparse.ArgumentParser(prog="wayline absorb", description="build the dossiers for the references")
    parser.add_argument("slugs", nargs="*", help="level 1 only: the reference slug(s) to skim; omitted skims every one not already at level 1 or above")
    parser.add_argument("--level", type=int, default=0, choices=[0, 1, 2], help="the dossier level to build; level 2 needs the absorb workflow, ticket 24")
    parser.add_argument("--report", action="store_true", help="print the papers-by-level report and exit; --level is ignored")
    parser.add_argument("--project", help="the project to absorb into; the active one by default")
    parser.add_argument("--fixtures", help="answer every request from this directory of recorded responses instead of the network")
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.level == LEVEL_2 and not options.report:
        print("wayline absorb: level 2 needs the inventory and the absorb workflow, which tickets 21, 22, and 24 build", file=sys.stderr)
        return 2
    try:
        project = find_project(options.project)
    except ProjectError as failure:
        print("wayline absorb: %s" % failure, file=sys.stderr)
        return 1
    if options.report:
        report = render_levels_report(project)
        print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else render_levels_text(report))
        return 0
    try:
        if options.level == LEVEL_1:
            report = absorb_level_1(project, options.slugs or None)
        else:
            fetcher = scout_fetcher(project, email=_email(project), fixtures=options.fixtures) if options.fixtures else None
            report = absorb_level_0(project, fetcher=fetcher)
    except (ProjectError, ValidationError, ValueError, OSError) as failure:
        print("wayline absorb: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif options.level == LEVEL_1:
        print(_render_l1(report))
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


def _render_l1(report):
    lines = ["skimmed  %d" % len(report["skimmed"])]
    for item in report["skimmed"]:
        lines.append("  %-24s %-50s %s" % (item["status"], item["slug"], "(cut)" if item.get("cut") else ""))
    for problem in report["problems"]:
        lines.append("  problem                  %-50s %s" % (problem["slug"], problem["problem"]))
    if not report["skimmed"] and not report["problems"]:
        lines.append("  nothing to skim; every dossier is already level 1 or above")
    return "\n".join(lines)
