"""The position memo, phase P2's first half (Implementation Decisions 10 and 1; BRIEF 6.5). Built by ticket 29.

Before any decision is asked, a fresh critic tells the owner whether the idea makes sense.

**The session.** `wayline position` launches the `critic` role in its position protocol through the
worker launcher (seam 1), on `policy.roles.critic` (`opus`, `high`), with `position.json` as its
schema. It reads only the dossiers, `INTAKE.md`, and `OBJECTIVES.md` (decision 17, in place of
`GOAL.json`; ticket 80): the intake and the objectives are inlined in its prompt with the dossiers
after them, and the session runs in `research/refs/` with its `Read`,
`Glob`, and `Grep` rules scoped to that directory (`scoped_tools`), so no decision, spec, or earlier
memo reaches it. It writes nothing.

**The checks.** Code validates the memo against the schema and then reads what the schema cannot say
(`check_memo`): three directions nearest first, none farther than the project's radius, each naming
objectives the project holds or proposing new ones; one row per open or parked objective, with a
revised target when a goal is out of reach, none when it is reachable, and none for an objective
without a measure; no reference named twice. A memo that fails is returned to the same session once
with the failures; a second failure writes nothing. A project with no goal, or with no objective yet,
is positioned all the same: its directions propose the objectives, and the grill's first tier puts
them to the owner.

**The citations.** Every row of the closest-prior-work table names a reference, and the scout has the
last word on it (`verify_citations`): a slug, a DOI, an arXiv id, or a title that matches a dossier
takes that dossier's `existence`, and one no dossier holds is resolved by the scout through the fetch
seam, which writes it an L0 dossier when it verifies. A row whose reference is not `existence:
verified` is dropped from the table, and the memo says so in a note, so a citation the critic
remembered rather than read never reaches the owner as a fact.

**The memo.** Code writes the validated memo, its resolved rows, and its dropped ones as
`research/position.json` and renders `research/POSITION.md` from that record, and the journal moves to
phase P2 with the critic's session on the event. Under autonomy `autonomous` the memo is handed to the
decider rather than shown: the decider reads `POSITION.md` with every decision it takes, and
`wayline position` has it resolve the grill's open questions at once when there are any. Otherwise the
owner is notified, and `wayline status` and the dashboard's overview show the memo first until the
project moves past P2 (`position_view`).
"""

import argparse
import json
import re
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, gates, grill, pacing, sections, specify, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import Ledger, LedgerError
from wayline.objectives import OBJECTIVES_MD, ObjectivesUnreadable, describe_measure, read_objectives
from wayline.project import ProjectError, find_project, policy_for, read_harness
from wayline.tickets import TicketError

__all__ = [
    "CRITIC", "POSITION_SCHEMA", "POSITION_MD", "POSITION_JSON", "PHASE", "DISTANCES", "ROWED", "PositionError", "critic_tier",
    "rowed",
    "scoped_tools", "inputs_text", "position_prompt", "check_memo", "verify_citations", "render_position", "read_position", "take_memo",
    "write_memo", "position", "position_view", "render_report", "position_command", "SEED_BY", "ref_locator", "prior_work_passages",
]

CRITIC = "critic"
POSITION_SCHEMA = "position"
POSITION_MD = grill.POSITION_MD
POSITION_JSON = grill.POSITION_JSON
PHASE = "P2"
SESSIONS = "sessions/position"      # research/sessions/position/<n>
CRITIC_BUDGET = "medium"            # policy.budget: a read-only memo needs no more turns than a decision
DISTANCES = ("strict", "moderate", "exploratory")   # the radius's own scale, nearest first
REFS = "refs"
# The room the prompt keeps under the context cap for what is not an input: the protocol and the schema.
PROMPT_ROOM = 20000
INPUTS_MIN = 20000
FEASIBILITY = {"feasible": "Feasible", "feasible_with_changes": "Feasible with changes", "infeasible": "Not feasible"}
VERDICTS = {"reachable": "Reachable", "uncertain": "Uncertain", "out_of_reach": "Out of reach"}
# The objectives the memo rows (decision 17): those the project pursues or may take up again; a closed one has its answer.
ROWED = ("open", "parked")
AUTONOMOUS = "autonomous"
READING_TOOLS = ("Read", "Glob", "Grep")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")

RESUME_INVALID = (
    "The memo you returned could not be read: %s. Return the whole memo again through the structured output, as the "
    "position schema asks."
)
RESUME_CHECKS = (
    "The harness's checks failed on the memo you returned:\n\n%s\n\nChange what they name, keep the rest, and return "
    "the whole memo again through the structured output."
)


class PositionError(ValueError):
    """A memo nobody could write: no intake, unreadable objectives, a role that cannot be read, a memo that failed its checks twice."""

    def __init__(self, message, failures=()):
        super().__init__(message)
        self.failures = list(failures)


# --- the tier ---------------------------------------------------------------------------------------


def critic_tier(policy, fall_back=False):
    """The `(model, effort, fallback_from)` the critic runs at: `policy.roles.critic`, Opus in Fable's place when `fall_back`."""
    entry = ((policy or {}).get("roles") or {}).get(CRITIC) or {}
    model, effort = entry.get("model"), entry.get("effort")
    if model not in worker.MODEL_ALIASES or effort not in worker.EFFORTS:
        raise PositionError("policy.roles.critic names no model and effort the launcher knows; got %r" % (entry,))
    if model == pacing.FABLE and fall_back:
        return pacing.OPUS, effort, pacing.FABLE
    return model, effort, None


def _falls_back_now(project, policy, fall_back):
    if fall_back is not None:
        return bool(fall_back)
    if critic_tier(policy)[0] != pacing.FABLE:
        return False
    return gates.fallback_now(project, "the critic's position memo")


# --- what the critic reads ----------------------------------------------------------------------------


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _fence(text):
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def _dossiers(ledger):
    """`{slug: dossier}` for every readable `research/refs/<slug>/dossier.json`, in slug order."""
    from wayline.dossier import all_slugs, read_dossier  # the dossier module imports the launcher and the fetcher
    found = {}
    for slug in all_slugs(ledger):
        try:
            found[slug] = read_dossier(ledger, slug)
        except (ValueError, OSError):
            continue
    return found


def rowed(objectives):
    """The objectives the memo gives a row each, in id order: the open and the parked."""
    return [objective for objective in objectives or () if objective.get("status") in ROWED]


def inputs_text(project, max_chars=None):
    """The critic's inputs, inlined in order and cut at `max_chars` with every cut announced: `(text, cut)`.

    `INTAKE.md`, then `OBJECTIVES.md`, then each reference's `dossier.json` with its `dossier.md` when it
    was read in full. Nothing else: no decision, no spec, no earlier memo, and no `GOAL.json`.
    """
    research = Path(project) / "research"
    entries = [
        ("research/INTAKE.md", _read(research / "INTAKE.md"), "[wayline: there is no INTAKE.md]"),
        ("research/%s" % OBJECTIVES_MD, _read(research / OBJECTIVES_MD),
         "[wayline: no objective is recorded yet; propose them in the directions]"),
    ]
    refs = research / REFS
    slugs = sorted(path.parent.name for path in refs.glob("*/dossier.json")) if refs.is_dir() else []
    for slug in slugs:
        entries.append(("research/refs/%s/dossier.json" % slug, _read(refs / slug / "dossier.json"), None))
        text = _read(refs / slug / "dossier.md")
        if text is not None:
            entries.append(("research/refs/%s/dossier.md" % slug, text, None))
    if not slugs:
        entries.append(("the dossiers", None, "[wayline: no reference has a dossier; the table of prior work will be empty]"))
    cap = None if max_chars is None else max(INPUTS_MIN, int(max_chars) - PROMPT_ROOM)
    rendered, used, cut = ["# What you read", "", "The intake, the objectives, and the dossiers: nothing else is yours to read."], 0, False
    for heading, text, absent in entries:
        rendered.extend(["", "## %s" % heading, ""])
        if text is None or not text.strip():
            rendered.append(absent or "[wayline: this file is empty]")
            continue
        text = text.rstrip("\n")
        if cap is not None and used >= cap:
            rendered.append("[wayline: left out at the context cap; open the path yourself.]")
            cut = True
            continue
        note = None
        if cap is not None and used + len(text) > cap:
            left_out = len(text) - (cap - used)
            text, cut = text[: cap - used], True
            note = "[wayline: cut here at the context cap; %d character(s) are missing. Open the path for the rest.]" % left_out
        used += len(text)
        fence = _fence(text)
        rendered.extend([fence, text, fence])
        if note:
            rendered.extend(["", note])
    return "\n".join(rendered) + "\n", cut


def position_prompt(role, inputs, harness, project, cut=False, objectives=()):
    """The critic's position prompt: what is asked, the radius, the objectives to row, the inputs, the paths, the protocol, the schema."""
    asked = [objective["id"] for objective in rowed(objectives)]
    head = "\n".join([
        "# What you are asked for",
        "",
        "The position memo of this project: phase P2, before any design question is put to the owner. Tell the owner "
        "whether the idea makes sense: the closest prior work, whether it is feasible with the compute and data they "
        "stated, whether each objective is within reach, what a hostile reviewer would say, and three directions it "
        "could take, each naming the objectives it would pursue.",
        "",
        "- the project's radius: `%s` (no direction may be farther from the intent than this)" % harness.get("radius"),
        "- autonomy: `%s`" % harness.get("autonomy"),
        ("- the objectives: one row in `objectives` for each of %s, and no other" % ", ".join(asked)) if asked else
        "- the objectives: none is recorded yet, so `objectives` is empty and the directions propose them (`id` null)",
    ])
    parts = [head, inputs]
    if cut:
        parts.append("[wayline: the inputs were cut at the context cap; the paths below hold the rest.]")
    parts.append("\n".join([
        "# The paths you may open",
        "",
        "You run in the project's `research/refs/` directory (`%s`), and it is the only one you may open: "
        "`<slug>/dossier.json`, `<slug>/dossier.md`, and what a full read left beside them. Write a locator as "
        "`research/refs/<slug>/...`." % (Path(project) / "research" / REFS),
    ]))
    parts.append(worker.protocol_for(role.protocol, "position"))
    parts.append(worker.schema_section("# The memo", POSITION_SCHEMA, closing=[
        "",
        "`distance` is on the radius's scale, and the directions go nearest first.",
    ]))
    return "\n\n".join(part.strip("\n") for part in parts if part and part.strip()) + "\n"


# --- the checks -------------------------------------------------------------------------------------


def _one_line(text):
    return " ".join(str(text or "").split())


def check_memo(memo, radius, objectives=()):
    """The checks on a memo the schema cannot make; returns the failures, each one line, empty when it passes.

    `objectives` are the project's records (`objectives.json`): the memo rows each open or parked one once, a
    revised target follows a goal's verdict and is never given for an objective without a measure, and a
    direction names only objectives the project holds, or new ones with no id.
    """
    try:
        check(memo, load_schema(POSITION_SCHEMA), name="the memo")
    except ValidationError as failure:
        return [str(failure)]
    failures = []
    distances = [direction["distance"] for direction in memo["directions"]]
    order = [DISTANCES.index(distance) for distance in distances]
    if order != sorted(order):
        failures.append("the directions are not nearest first: %s" % ", ".join(distances))
    if radius in DISTANCES:
        for index, direction in enumerate(memo["directions"], 1):
            if DISTANCES.index(direction["distance"]) > DISTANCES.index(radius):
                failures.append("direction %d (%s) is %s, farther than the project's radius %s"
                                % (index, _one_line(direction["title"]), direction["distance"], radius))
    held = {objective.get("id"): objective for objective in objectives or ()}
    for index, direction in enumerate(memo["directions"], 1):
        for named in direction["objectives"]:
            if named["id"] is not None and named["id"] not in held:
                failures.append("direction %d (%s) names %s, which the project does not hold"
                                % (index, _one_line(direction["title"]), named["id"]))
    failures += _row_failures(memo["objectives"], held)
    seen = set()
    for row in memo["prior_work"]:
        key = _one_line(row["reference"]).lower()
        if key in seen:
            failures.append("the reference %s is named more than once" % _one_line(row["reference"]))
        seen.add(key)
    return failures


def _row_failures(rows, held):
    """Why the memo's `objectives` rows are not one per open or parked objective, or a revised target is misplaced."""
    failures, counted = [], {}
    for row in rows:
        counted[row["id"]] = counted.get(row["id"], 0) + 1
        objective = held.get(row["id"])
        if objective is None:
            failures.append("a row of objectives names %s, which the project does not hold" % row["id"])
            continue
        if objective.get("status") not in ROWED:
            failures.append("a row of objectives names %s, which is %s; the memo rows only the open and parked objectives"
                            % (row["id"], objective.get("status")))
            continue
        revised = row["revised_target"]
        if not objective.get("measure"):
            if revised is not None:
                failures.append("%s has no measure, so it takes no revised target" % row["id"])
        elif row["verdict"] == "out_of_reach" and revised is None:
            failures.append("the goal %s is out of reach and no revised target is given" % row["id"])
        elif row["verdict"] == "reachable" and revised is not None:
            failures.append("the goal %s is reachable, so it takes no revised target" % row["id"])
    for objective in rowed(held.values()):
        if counted.get(objective["id"], 0) == 0:
            failures.append("the objective %s has no row in objectives" % objective["id"])
        elif counted[objective["id"]] > 1:
            failures.append("the objective %s has more than one row in objectives" % objective["id"])
    return failures


# --- the citations ----------------------------------------------------------------------------------


def _identifier_keys(dossier):
    keys = set()
    identifiers = dossier.get("identifiers") or {}
    if identifiers.get("doi"):
        keys.add(("doi", str(identifiers["doi"]).lower()))
    if identifiers.get("arxiv_id"):
        keys.add(("arxiv", _bare_arxiv(identifiers["arxiv_id"])))
    from wayline.scout import normalize_title
    for title in ((dossier.get("metadata") or {}).get("title"), ((dossier.get("query") or {}).get("value")
                                                                  if (dossier.get("query") or {}).get("kind") == "title" else None)):
        if title and normalize_title(title):
            keys.add(("title", normalize_title(title)))
    query = dossier.get("query") or {}
    if query.get("kind") in ("doi", "arxiv") and query.get("value"):
        keys.add((query["kind"], str(query["value"]).lower() if query["kind"] == "doi" else _bare_arxiv(query["value"])))
    return keys


def _bare_arxiv(identifier):
    """An arXiv id without its version, lowercased: two spellings of one preprint compare equal."""
    text = str(identifier or "").strip().lower()
    if "v" in text and text.rsplit("v", 1)[1].isdigit():
        text = text.rsplit("v", 1)[0]
    return text


def _reference_key(reference):
    from wayline.scout import normalize_title
    if reference.kind == "doi":
        return ("doi", reference.value.lower())
    if reference.kind == "arxiv":
        return ("arxiv", _bare_arxiv(reference.value))
    if reference.kind == "title":
        return ("title", normalize_title(reference.value))
    return (reference.kind, reference.value)


def _as_slug(text):
    """The slug a reference names, when it is written as one (`paper-a`, `research/refs/paper-a`, `refs/paper-a/`)."""
    value = text.strip().strip("`").rstrip("/")
    for prefix in ("research/refs/", "refs/"):
        if value.startswith(prefix):
            value = value[len(prefix):].split("/", 1)[0]
    return value


def _cited(slug, dossier):
    metadata = dossier.get("metadata") or {}
    identifiers = dossier.get("identifiers") or {}
    identifier = ("doi:%s" % identifiers["doi"] if identifiers.get("doi")
                  else "arXiv:%s" % identifiers["arxiv_id"] if identifiers.get("arxiv_id") else None)
    return {"slug": slug, "title": metadata.get("title"), "year": metadata.get("year"), "identifier": identifier,
            "existence": dossier.get("existence"), "resolved_by": dossier.get("resolved_by")}


def verify_citations(project, memo, scout=None, say=lambda text: None):
    """Resolve every prior-work row of `memo`; returns `(kept, dropped, written)`.

    `kept` is the rows whose reference is `existence: verified`, each with its `citation` (slug, title,
    year, identifier, resolver); `dropped` is the rest, each with the `reason`; `written` is the slugs of
    the L0 dossiers the scout wrote for references no dossier held. `scout` is a `wayline.scout.Scout`,
    or None to build one on the project's cache; it is only built when a row needs it.
    """
    from wayline.dossier import QUERY_PACK_MAX, l0_dossier, rebuild_query_pack, scout_fetcher, slug_for, write_l0
    from wayline.scout import Scout, VERIFIED, parse_reference
    project = Path(project).resolve()
    ledger = Ledger(project)
    dossiers = _dossiers(ledger)
    index = {}
    for slug, dossier in dossiers.items():
        for key in _identifier_keys(dossier):
            index.setdefault(key, slug)
    kept, dropped, written = [], [], []
    for row in memo["prior_work"]:
        text = _one_line(row["reference"])
        slug = _as_slug(text)
        if slug not in dossiers:
            try:
                reference = parse_reference(text)
            except ValueError as failure:
                dropped.append(dict(row, reason="it names nothing the scout can read: %s" % failure))
                continue
            slug = index.get(_reference_key(reference))
            if slug is None and reference.kind in ("doi", "arxiv", "title"):
                if scout is None:
                    email = read_harness(project).get("owner_email")
                    scout = Scout(scout_fetcher(project, email=email), email)
                say("  asking the scout about %s" % text)
                try:
                    resolved = scout.resolve(reference)
                except (ValueError, OSError) as failure:
                    dropped.append(dict(row, reason="the scout could not look it up: %s" % failure))
                    continue
                if resolved.get("existence") != VERIFIED:
                    dropped.append(dict(row, reason="the scout could not resolve it (existence: unresolved)"))
                    continue
                again = [index.get(key) for key in _identifier_keys(resolved) if index.get(key)]
                if again:
                    slug = again[0]
                else:
                    slug = slug_for(resolved, set(dossiers))
                    try:
                        filed = l0_dossier(resolved, slug)
                        write_l0(ledger, filed)
                    except (ValidationError, ValueError, OSError) as failure:
                        dropped.append(dict(row, reason="the scout resolved it, and its dossier could not be written: %s" % failure))
                        continue
                    dossiers[slug] = filed
                    for key in _identifier_keys(dossiers[slug]):
                        index.setdefault(key, slug)
                    written.append(slug)
            elif slug is None:
                dropped.append(dict(row, reason="it names no dossier, DOI, arXiv id, or title the scout can look up"))
                continue
        dossier = dossiers[slug]
        if dossier.get("existence") != VERIFIED:
            dropped.append(dict(row, reason="research/refs/%s/dossier.json says existence: %s" % (slug, dossier.get("existence"))))
            continue
        if any(item["citation"]["slug"] == slug for item in kept):
            dropped.append(dict(row, reason="it is research/refs/%s again, which the table already cites" % slug))
            continue
        kept.append(dict(row, citation=_cited(slug, dossier)))
    if written:
        try:
            limit = policy_for(project).get("kb", {}).get("query_pack_max_chars", QUERY_PACK_MAX)
            rebuild_query_pack(ledger, limit)
        except (ValueError, OSError):
            pass  # the pack is rebuilt by the next absorb; the dossiers are written
    return kept, dropped, written


# --- POSITION.md ------------------------------------------------------------------------------------


def _number(value):
    return "%g" % value if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _prose(text):
    """A prose field as the critic wrote it: its paragraphs and lists kept, runs of blank lines folded to one.

    Markdown needs a blank line before a list that follows a paragraph, and a session often leaves it
    out, so one is put there. A line starting with `#` is escaped, so the memo's own headings stay the
    only ones in the file.
    """
    lines, previous = [], ""
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.lstrip().startswith("#"):
            line = line.replace("#", "\\#", 1)
        if not line.strip():
            if lines and lines[-1] != "":
                lines.append("")
            previous = ""
            continue
        if _LIST_ITEM.match(line) and previous and not _LIST_ITEM.match(previous) and not previous.startswith(" "):
            lines.append("")
        lines.append(line)
        previous = line
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _item(marker, text):
    """A list item whose text may run to several lines: the continuation lines indented under the marker."""
    body = _prose(text) or [""]
    pad = " " * len(marker)
    return [marker + body[0]] + [pad + line if line else "" for line in body[1:]]


def _lead(label, text):
    """`**Label.** text`, with the first paragraph run on after the label and the rest kept as written."""
    body = _prose(text) or [""]
    if _LIST_ITEM.match(body[0]):
        return ["**%s.**" % label, ""] + body
    return ["**%s.** %s" % (label, body[0])] + body[1:]


def render_position(record):
    """`POSITION.md` from the record `write_memo` keeps: the prior work, the verdicts, the objections, the directions."""
    memo = record["memo"]
    lines = ["# Position", "",
             "Rendered by `wayline position` from `research/position.json`: the %s critic's memo, read from the dossiers, "
             "`INTAKE.md`, and `OBJECTIVES.md` only." % (record.get("model") or "unnamed"), ""]
    lines += _lead("Intent", memo["intent"]) + ["", "## Closest prior work", ""]
    if not record["prior_work"]:
        lines.append("No reference the scout verified bears on the intent.")
    for row in record["prior_work"]:
        citation = row["citation"]
        title = "*%s*" % _one_line(citation.get("title") or "untitled")
        if citation.get("year"):
            title += " (%s)" % citation["year"]
        lines += ["- **%s**" % citation["slug"], "  - title: %s" % title]
        if citation.get("identifier"):
            lines.append("  - identifier: %s" % citation["identifier"])
        lines += _item("  - what it reports: ", row["reports"])
        lines += _item("  - bearing on the intent: ", row["bearing"])
        if row.get("locator"):
            lines.append("  - read at: `%s`" % _one_line(row["locator"]))
        lines.append("  - scout: verified" + (" (%s)" % citation["resolved_by"] if citation.get("resolved_by") else ""))
    if record["dropped"]:
        lines += ["", "Dropped, because the scout did not verify them:", ""]
        lines += ["- *%s*: %s." % (_one_line(row["reference"]), _one_line(row["reason"])) for row in record["dropped"]]
    missing = memo.get("missing_prior_work") or []
    if missing:
        lines += ["", "### What the references lack", "",
                  "Work the critic expected beside these and did not find among the dossiers. It named these from what it "
                  "knows, so the scout has checked none of them: add the ones you want with `wayline absorb`.", ""]
        for gap in missing:
            lines += _item("- ", gap)
    feasibility = memo["feasibility"]
    lines += ["", "## Feasibility", ""] + _lead(FEASIBILITY[feasibility["verdict"]], feasibility["reasoning"]) + [""]
    lines += _item("- compute: ", feasibility["compute"]) + _item("- data: ", feasibility["data"])
    lines += ["", "## Objectives", ""] + _objective_rows(memo["objectives"], record.get("objectives") or [])
    lines += ["", "## The hostile reviewer", ""]
    for index, text in enumerate(memo["hostile_review"], 1):
        lines += _item("%d. " % index, text)
    lines += ["", "## Three directions, by distance from the intent", "",
              "Nearest first, none farther than the radius `%s`. The objectives each direction names are proposals: the "
              "grill's first tier asks the owner which the project takes, open or parked." % record.get("radius"), ""]
    for index, direction in enumerate(memo["directions"], 1):
        marker = "%d. " % index
        lines += _item(marker + "**%s** (%s): " % (_one_line(direction["title"]), direction["distance"]), direction["text"])
        for named in direction.get("objectives") or ():
            pad = " " * len(marker)
            if named.get("id"):
                lines.append(pad + "- would pursue %s: %s" % (named["id"], _one_line(named["text"])))
            else:
                lines.append(pad + "- proposes a new objective: %s" % _one_line(named["text"]))
    return "\n".join(lines).rstrip("\n") + "\n"


def _objective_rows(rows, recorded):
    """The `## Objectives` section: each row under its objective's question, the goal's measure, the verdict, a revised target."""
    if not rows:
        return ["No objective is recorded yet; the directions below propose them."]
    known = {objective.get("id"): objective for objective in recorded}
    lines = []
    for row in rows:
        objective = known.get(row["id"]) or {}
        lines += ["### %s %s" % (row["id"], _one_line(objective.get("text") or "an objective the record does not name")), ""]
        if objective.get("measure"):
            lines += ["A goal: %s." % objective["measure"], ""]
        else:
            lines += ["An objective without a measure.", ""]
        lines += _lead(VERDICTS[row["verdict"]], row["reasoning"])
        if row["revised_target"] is not None:
            lines += ["", "Revised target: **%s**. The goal is the owner's to change; this is a proposal."
                      % _number(row["revised_target"]["value"]), ""]
            lines += _item("- why it is reachable: ", row["revised_target"]["why"])
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def read_position(project):
    """`research/position.json` as `write_memo` left it, or None when no memo was written."""
    try:
        return json.loads((Path(project) / "research" / POSITION_JSON).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


# --- the session ------------------------------------------------------------------------------------


def _session_dir(project):
    base = Path(project) / "research" / SESSIONS
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


def _budget(policy, key):
    return ((policy.get("budget") or {}).get(CRITIC_BUDGET) or {}).get(key)


def _context_cap(policy, model):
    caps = (policy.get("context_pack") or {}).get("max_chars") or {}
    return caps.get(model, min(caps.values()) if caps else None)


def scoped_tools(tools, directory):
    """The role's reading tools confined to `directory`: `Read(//<dir>/**)`, and the same for `Glob` and `Grep`.

    Under `dontAsk` a bare `Read` rule admits any path on the machine, whatever the session's working
    directory, and a scoped `Read` alone still lets `Glob` and `Grep` list and search outside it; all
    three scoped keep the session inside (`docs/verification/m4.md`, ticket 29). Any other tool passes as it is.
    """
    root = "//%s/**" % str(Path(directory).resolve()).strip("/")
    return ["%s(%s)" % (tool, root) if tool in READING_TOOLS else tool for tool in tools]


def _unusable(envelope):
    if not envelope.valid:
        return "; ".join(envelope.errors) or "the session returned no structured memo"
    try:
        check(envelope.structured_output, load_schema(POSITION_SCHEMA), name="the memo")
    except ValidationError as failure:
        return str(failure)
    return None


def _objectives(project):
    """The project's objectives as `objectives.json` holds them; an unreadable record stops the memo with the reason."""
    try:
        return read_objectives(project)
    except ObjectivesUnreadable as failure:
        raise PositionError(str(failure)) from None


def take_memo(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, say=lambda text: None, objectives=None):
    """One critic session on the project, checked but not written: `(memo, envelope, model, fallback_from)`.

    `objectives` are the records the memo is asked for and checked against; None reads `objectives.json`.

    An unreadable memo, and a memo that fails `check_memo`, are each returned to the same session once;
    what fails a second time raises `PositionError`. A session a usage window refused raises
    `gates.UsageLimited`, and the hold on Fable's window `gates.FableHeld`, before a session is spent.
    """
    project = Path(project).resolve()
    policy = policy_for(project, harness_root) if policy is None else policy
    harness = read_harness(project)
    objectives = _objectives(project) if objectives is None else objectives
    what = "the critic's position memo"
    model, effort, fallback_from = critic_tier(policy, _falls_back_now(project, policy, fall_back))
    role = worker.read_role(CRITIC, harness_root, project)
    inputs, cut = inputs_text(project, _context_cap(policy, model))
    refs = project / "research" / REFS
    refs.mkdir(parents=True, exist_ok=True)
    run_dir = _session_dir(project)
    request = worker.LaunchRequest(
        role=role.name, model=model, effort=effort, prompt=position_prompt(role, inputs, harness, project, cut, objectives),
        agent_json=role.agent_json(model, effort, _budget(policy, "max_turns")),
        allowed_tools=scoped_tools(role.allowed_tools, refs), disallowed_tools=list(role.disallowed_tools),
        settings_path=gates.write_worker_settings(run_dir / "settings.json", harness_root),
        add_dirs=[str(refs)],
        cwd=refs,
        env=gates.verdict_env(project, run_dir),
        schema_path=Path(harness_root).resolve() / "schemas" / (POSITION_SCHEMA + ".json"),
        max_minutes=_budget(policy, "max_minutes"),
    )
    say("writing the position memo: the critic on %s at %s%s" % (model, effort, " in place of fable" if fallback_from else ""))
    envelope = worker.launch(request)
    gates.raise_if_refused(envelope, model, what)
    session_id = envelope.session_id

    def again(message):
        if not session_id:
            raise PositionError("the critic's session has no id to be resumed with")
        returned = worker.resume(request, session_id, message)
        gates.raise_if_refused(returned, model, what)
        return returned

    problem = _unusable(envelope)
    if problem is not None:
        say("  the memo could not be read (%s); returned to the critic once" % problem)
        envelope = again(RESUME_INVALID % problem)
        problem = _unusable(envelope)
        if problem is not None:
            raise PositionError("the critic returned no memo the schema accepts: %s" % problem)
        failures = check_memo(envelope.structured_output, harness.get("radius"), objectives)
        if failures:
            raise PositionError("the memo failed its checks after it was returned once; nothing was written", failures)
    else:
        failures = check_memo(envelope.structured_output, harness.get("radius"), objectives)
        if failures:
            say("  the memo failed %d check(s); returned to the critic once" % len(failures))
            envelope = again(RESUME_CHECKS % "\n".join("- " + failure for failure in failures))
            problem = _unusable(envelope)
            if problem is not None:
                raise PositionError("the critic's second memo could not be read: %s" % problem, failures)
            failures = check_memo(envelope.structured_output, harness.get("radius"), objectives)
            if failures:
                raise PositionError("the memo failed its checks twice; nothing was written", failures)
    envelope.session_id = envelope.session_id or session_id
    return envelope.structured_output, envelope, envelope.model or model, fallback_from


def write_memo(project, memo, *, session_id=None, model=None, fallback_from=None, scout=None, say=lambda text: None,
               objectives=None):
    """Resolve the memo's citations, write `research/position.json` and `research/POSITION.md`, seed the Introduction, and move to P2.

    `objectives` are the records the memo was checked against, kept beside it as it read them; None reads
    `objectives.json`, for a memo written apart from its session. Returns the record written.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    objectives = _objectives(project) if objectives is None else objectives
    kept, dropped, written = verify_citations(project, memo, scout=scout, say=say)
    # The objectives as the memo read them: what `POSITION.md` names beside each row, kept as the memo saw them.
    objectives = [{"id": objective["id"], "text": objective["text"], "status": objective["status"],
                   "measure": describe_measure(objective["measure"]) if objective.get("measure") else None}
                  for objective in objectives]
    record = {"memo": memo, "prior_work": kept, "dropped": dropped, "dossiers_written": written,
              "radius": read_harness(project).get("radius"), "objectives": objectives,
              "session_id": session_id, "model": model, "fallback_from": fallback_from}
    ledger.write_json(POSITION_JSON, record)
    ledger.write_markdown(POSITION_MD, render_position(record))
    sections.seed_passages(ledger, "introduction", prior_work_passages(record), by=SEED_BY, key=_cited_slug)
    events, _ = ledger.read_events()
    specify.move_phase(ledger, events, PHASE, session_id=session_id)
    return record


# --- the Introduction's seed (decision 17; ticket 86) ------------------------------------------------


SEED_BY = "step:position"
PRIOR_WORK = "Prior work"


def ref_locator(row):
    """Where a prior-work row was read, as a `ref` tag's locator: the anchor of its locator, else its file, else `dossier`."""
    locator = _one_line(row.get("locator"))
    anchor = locator.partition("#")[2] or locator.rsplit("/", 1)[-1] if locator else ""
    return re.sub(r"\s+", "-", anchor.strip()) or "dossier"


def _cited_slug(heading, text):
    """What a seeded prior-work passage is about: the reference its tag names, so a memo taken again rewords that row."""
    found = re.search(r"\{ref:([^#{}]+)#", text)
    return found.group(1) if found else text


def prior_work_passages(record):
    """The Introduction's passages code seeds from the memo: one per verified row, `(heading, text)`, each claim tagged.

    Only the rows the scout verified (`record["prior_work"]`) seed anything; a dropped row never reaches the paper.
    """
    items = []
    for row in record.get("prior_work") or []:
        citation = row["citation"]
        title = "*%s*" % _one_line(citation.get("title") or citation["slug"])
        if citation.get("year"):
            title += " (%s)" % citation["year"]
        reports = _one_line(row["reports"])
        if reports and reports[-1] not in ".!?":
            reports += "."
        items.append((PRIOR_WORK, "%s reports: %s{ref:%s#%s}" % (title, reports, citation["slug"], ref_locator(row))))
    return items


# --- where the memo stands --------------------------------------------------------------------------


def position_view(project, harness=None, events=None):
    """What `status` and the dashboard show of the memo, or None when there is no memo.

    `first` is whether it leads the view: a memo written and not handed to the decider, while the
    project has not moved past P2. `text` is `POSITION.md` as written.
    """
    project = Path(project).resolve()
    record = read_position(project)
    if record is None or not isinstance(record.get("memo"), dict):
        return None
    harness = read_harness(project) if harness is None else harness
    if events is None:
        events, _ = Ledger(project).read_events()
    phase = specify.current_phase(events)
    memo = record["memo"]
    handed = harness.get("autonomy") == AUTONOMOUS
    try:
        feasibility = memo["feasibility"]["verdict"]
        objectives = [{"id": row["id"], "verdict": row["verdict"],
                       "revised_target": row["revised_target"]["value"] if isinstance(row.get("revised_target"), dict) else None}
                      for row in memo["objectives"]]
        directions = ["%s (%s)" % (_one_line(item["title"]), item["distance"]) for item in memo["directions"]]
    except (KeyError, TypeError):
        return None
    return {
        "path": "research/%s" % POSITION_MD,
        "feasibility": feasibility,
        "objectives": objectives,
        "verdicts": verdicts_line(objectives),
        "cited": len(record.get("prior_work") or []),
        "dropped": len(record.get("dropped") or []),
        "objections": len(memo.get("hostile_review") or []),
        "directions": directions,
        "model": record.get("model"),
        "handed_to": "decider" if handed else "owner",
        "first": not handed and (phase is None or specify.PHASES.index(phase) <= specify.PHASES.index(PHASE)),
        "text": _read(project / "research" / POSITION_MD) or "",
    }


def verdicts_line(objectives):
    """The memo's verdict on each objective in one line: `O1 uncertain (revised target 0.83), O2 reachable`."""
    if not objectives:
        return "none recorded"
    return ", ".join("%s %s%s" % (item["id"], item["verdict"], " (revised target %s)" % _number(item["revised_target"])
                                  if item.get("revised_target") is not None else "") for item in objectives)


def render_view(view):
    """The lines `wayline status` leads with while the memo is the owner's to read."""
    lines = ["position memo  %s: read it before the grill" % view["path"],
             "  feasibility %s   objectives %s   prior work %d cited, %d dropped   objections %d"
             % (view["feasibility"], view["verdicts"], view["cited"], view["dropped"], view["objections"])]
    lines += ["  %d. %s" % (index, direction) for index, direction in enumerate(view["directions"], 1)]
    return lines


# --- the verb ---------------------------------------------------------------------------------------


def position(project, *, harness_root=HARNESS_ROOT, policy=None, fall_back=None, scout=None, notify=None, out=None):
    """Write the position memo and hand it on by autonomy; returns the report.

    The report is `{project, autonomy, did, stopped, failures, view}`. `notify(event, text, path, ticket)`
    stands in for the notifier in tests; `scout` for the scout the citations are resolved with.
    """
    project = Path(project).resolve()
    say = (lambda text: print(text, file=out)) if out is not None else (lambda text: None)
    ledger = Ledger(project)
    harness = read_harness(project)
    autonomy = harness.get("autonomy")
    report = {"project": str(project), "autonomy": autonomy, "did": [], "stopped": None, "failures": [], "view": None}
    # No guard on GOAL.json or on objectives (decision 17): a project with no goal is positioned, and its directions propose them.
    if not ledger.path("INTAKE.md").is_file():
        raise PositionError("%s has no research/INTAKE.md; the memo reads it, so run wayline intake first" % project)
    objectives = _objectives(project)  # read once: the memo is asked for, checked against, and kept with these
    try:
        memo, envelope, model, fallback_from = take_memo(project, harness_root=harness_root, policy=policy,
                                                         fall_back=fall_back, say=say, objectives=objectives)
    except PositionError as failure:
        report.update(stopped=str(failure), failures=failure.failures)
        return report
    except gates.FableHeld as held:
        report["stopped"] = "Fable's weekly window is held until %s and the consent waits: %s" % (held.resets_at, held)
        return report
    except gates.UsageLimited as refused:
        report["stopped"] = "the usage limit refused the critic: %s" % refused
        return report
    except (worker.LaunchError, worker.RoleError) as failure:
        report["stopped"] = str(failure)
        return report
    record = write_memo(project, memo, session_id=envelope.session_id, model=model, fallback_from=fallback_from,
                        scout=scout, say=say, objectives=objectives)
    report["did"].append("wrote research/%s: %d prior work(s) cited, %d dropped, on %s%s"
                         % (POSITION_MD, len(record["prior_work"]), len(record["dropped"]), model,
                            " in place of fable" if fallback_from else ""))
    if record["dossiers_written"]:
        report["did"].append("the scout verified and filed %s" % ", ".join(record["dossiers_written"]))
    if autonomy == AUTONOMOUS:
        report["did"].append("handed to the decider, which reads research/%s with every decision it takes" % POSITION_MD)
        _decide(project, report, harness_root, policy, fall_back, notify, say)
    else:
        _tell_owner(project, record, notify)
        report["did"].append("the owner was notified; wayline status and the dashboard show the memo first")
    report["view"] = position_view(project)
    return report


def _decide(project, report, harness_root, policy, fall_back, notify, say):
    """Under autonomous: the decider on whatever the grill left open for it, now that the memo is there."""
    from wayline import decider  # the decider imports the grill and the gates, as this module does; loaded when used
    decider.settle_grill(project, report, harness_root=harness_root, policy=policy, fall_back=fall_back, notify=notify, say=say)


def _tell_owner(project, record, notify):
    memo = record["memo"]
    rows = [{"id": row["id"], "verdict": row["verdict"],
             "revised_target": row["revised_target"]["value"] if row["revised_target"] else None} for row in memo["objectives"]]
    text = "The position memo is written (research/%s): %s; objectives %s. Read it before the grill." % (
        POSITION_MD, FEASIBILITY[memo["feasibility"]["verdict"]].lower(), verdicts_line(rows))
    if notify is not None:
        notify("position", text, str(Path(project) / "research" / POSITION_MD), None)
        return
    from wayline.notify import notify as send  # the notifier imports the project module, as this one does
    send("position", text, project=project)


def render_report(report):
    """The text `wayline position` prints: what was done, then the memo itself when it is the owner's."""
    lines = ["position  %s  (autonomy %s)" % (report["project"], report["autonomy"])]
    lines += ["  " + line for line in report["did"]] or ["  nothing was written"]
    if report["stopped"]:
        lines.append("  stopped: %s" % report["stopped"])
        lines += ["    - " + str(failure) for failure in report["failures"]]
    view = report.get("view")
    if view is not None and view["handed_to"] == "owner" and not report["stopped"]:
        lines += ["", view["text"].rstrip("\n")]
    return "\n".join(lines)


def position_command(args):
    parser = argparse.ArgumentParser(
        prog="wayline position",
        description="phase P2: a fresh critic reads only the dossiers, INTAKE.md, and OBJECTIVES.md and writes "
                    "research/POSITION.md: the closest prior work the scout verified, feasibility, a verdict on each "
                    "objective, the hostile reviewer, and three directions by radius, each naming the objectives it "
                    "would pursue. Under autonomous it goes to the decider.")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        report = position(project, out=None if options.json else sys.stdout)
    except PositionError as failure:
        print("wayline position: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, LedgerError, TicketError, OSError) as failure:
        print("wayline position: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else render_report(report))
    return 1 if report["stopped"] else 0
