"""The L2 absorb (Implementation Decisions 9): a promoted paper read in full, its coverage forced by code.

A level-2 read is earned first (`dossier.promote`) and then done here, in four steps that leave
content to the models and everything else to code:

1. Chunking is code. `chunk_inventory` cuts the text layer into one chunk per section (a
   subsection rides with its section while the two fit), cuts a section longer than
   `policy.absorb.chunk_max_chars` into parts, and gives each chunk the inventory items located
   in it as its obligation list. Equations, algorithms, and theorems ride with their section;
   every figure and table is a chunk of its own with its image file. `write_chunks` writes one
   markdown file per chunk and the chunk manifest under `refs/<slug>/absorb/`.
2. A fan-out reads. Under `policy.absorb.fanout: workflow`, `workflow_fanout` launches one
   `claude -p` session from the project root whose prompt's first line is `/absorb <manifest>`;
   the saved workflow `workflows/absorb.js` runs one `reader` per chunk and one `synthesizer`
   over every entry, and its return value is read out of the run file found by
   `glob ~/.claude/projects/*/<session_id>/workflows/wf_*.json`. Under `fanout: conductor`,
   `conductor_fanout` launches the readers and the synthesizer itself, one session each, and
   keeps the coverage bookkeeping. Both are `(context) -> Fanout`.
3. Code merges. Every entry is validated against `dossier_entry` and the sections against
   `dossier_sections`; `entries.jsonl` and `dossier.json` (level 2) are written, `dossier.md` is
   rendered, and the coverage audit (Type-A) fails on any inventory item without an entry, a
   figure counting as covered only when an entry says what it shows.
4. The depth spot-check (Type-B) is queued: an ask for the `critic` on the five most important
   items and every claimed flaw, kept in `dossier.json` until `take_spot_check` (or the
   conductor, through `gates.verdict_for`) takes it.

The absorb session's own directory is `research/sessions/absorb/<slug>/<n>/`, written by the
launcher as every session directory is.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from wayline import HARNESS_ROOT, consult, gates, pacing, worker
from wayline.dossier import LEVEL_2, REFS, SOURCE, DossierError, read_dossier
from wayline.jsonschema import ValidationError, load_schema, validate
from wayline.ledger import LedgerError, ledger_for, now_ts
from wayline.project import ProjectError, find_project, policy_for

__all__ = [
    "ABSORB_DIR", "MANIFEST", "ENTRIES", "DOSSIER_MD", "WORKFLOW", "CONDUCTOR", "FANOUTS", "SECTION_KEYS",
    "TextLayer", "text_layer", "chunk_inventory", "render_chunk", "write_chunks",
    "Context", "Fanout", "workflow_args", "session_prompt", "workflow_fanout", "conductor_fanout",
    "claude_projects_dir", "find_run_file", "read_run_file",
    "merge_entries", "audit_coverage", "unresolved_locators", "spot_check_ask", "render_dossier_markdown",
    "absorb_level_2", "take_spot_check", "level_2_command", "ticket_slug", "promotion_answer", "run_dossier_ticket",
]

ABSORB_DIR = "absorb"            # refs/<slug>/absorb/: the manifest and the chunk files
CHUNKS = "chunks"
MANIFEST = "manifest.json"
ENTRIES = "entries.jsonl"        # refs/<slug>/entries.jsonl
DOSSIER_MD = "dossier.md"        # refs/<slug>/dossier.md
INVENTORY = "inventory.json"
INTAKE = "INTAKE.md"
SESSIONS = "sessions/absorb"     # research/sessions/absorb/<slug>/<n>/

WORKFLOW = "workflow"
CONDUCTOR = "conductor"
FANOUTS = (WORKFLOW, CONDUCTOR)
CHUNK_MAX_CHARS = 20000          # the fallback when a policy carries no `absorb.chunk_max_chars`

ITEM_KEYS = ("sections", "appendices", "equations", "figures", "tables", "algorithms", "theorems")
HEADING_KEYS = ("sections", "appendices")
RIDING_KEYS = ("equations", "algorithms", "theorems")
OWN_CHUNK_KEYS = ("figures", "tables")
SECTION_KEYS = ("method", "claims", "results", "assumptions", "limitations", "flaws_found",
                "reusable_ideas", "open_questions", "relation_to_intent")

SESSION_ROLE = "absorb"
READER = "reader"
SYNTHESIZER = "synthesizer"
CRITIC = "critic"
# The session only starts the workflow and waits, so it runs on the cheapest tier; the readers
# and the synthesizer run on theirs, from `policy.roles`.
SESSION_MODEL, SESSION_EFFORT = "sonnet", "low"
CONSULTANT = consult.ROLE
ROLE_FALLBACKS = {READER: ("sonnet", "medium"), SYNTHESIZER: ("opus", "high"), CONSULTANT: consult.TIER}
NARROW, BROAD = "narrow", "broad"
READ_TOOLS = ("Read", "Glob", "Grep")
# `claude -p` stays open while a workflow runs, up to a 10 minute idle ceiling (research-notes 04);
# an absorb of a long paper runs past it, so the ceiling is lifted for this session.
WAIT_CEILING = {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}
SPOT_CHECK_ITEMS = 5
INTENT_MAX_CHARS = 4000
PAGE_HEIGHT_PT = 792.0           # a US letter page, for placing a bbox on a page of the text layer
ARGS_MARKER = "<!-- wayline:absorb-args -->"

_LINE_LOCATOR = re.compile(r"^(?P<file>[^:#\s]+):(?P<line>\d+)")
_PAGE_LOCATOR = re.compile(r"#page=(?P<page>\d+)")
_SPACES = re.compile(r"\s+")


# --- chunking -----------------------------------------------------------------------------------


@dataclass
class TextLayer:
    """The text a paper's locators point into, line by line, with the line each PDF page starts on.

    `path` is relative to `refs/<slug>/`. Lines are numbered as the inventory numbers them: a
    `pdftotext` form feed sits inside a line rather than ending one, so `text.txt:<n>` is line
    `n` of `text.split("\\n")`, exactly as `pdf_inventory.text_layer_environments` counts.
    """

    path: str
    lines: list
    page_starts: list = field(default_factory=list)

    @property
    def name(self):
        return Path(self.path).name


def text_layer(text, path):
    lines = str(text).split("\n")
    page_starts, first = [], 0
    for page in str(text).split("\f"):
        page_starts.append(first)
        first += page.count("\n")
    return TextLayer(str(path), lines, page_starts)


def _squash(text):
    return _SPACES.sub(" ", str(text or "")).strip().lower()


def _position(item, layer):
    """The 0-based line of the text layer an item sits at, or None when nothing places it.

    A `<file>:<line>` locator is exact. A PDF item is placed on its page: at the line holding its
    title when the page has one, else at its bbox's height on the page, else at the page's first
    line. A PDF's two columns make the last two approximate, which is why no coverage rule rests
    on them: every item is on exactly one obligation list wherever it lands.
    """
    locator = str(item.get("locator") or "")
    match = _LINE_LOCATOR.match(locator)
    if match and (layer is None or Path(match.group("file")).name == layer.name):
        line = int(match.group("line")) - 1
        if layer is not None:
            line = min(max(line, 0), max(len(layer.lines) - 1, 0))
        return max(line, 0)
    if layer is None:
        return None
    page = item.get("page")
    if not isinstance(page, int):
        found = _PAGE_LOCATOR.search(locator)
        page = int(found.group("page")) if found else None
    if not isinstance(page, int) or page < 1 or page > len(layer.page_starts):
        return None
    start = layer.page_starts[page - 1]
    end = layer.page_starts[page] if page < len(layer.page_starts) else len(layer.lines)
    needle = _squash(item.get("title"))[:60]
    if needle:
        for index in range(start, end):
            if needle in _squash(layer.lines[index]):
                return index
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4 and end > start:
        offset = int(max(0.0, float(bbox[1])) / PAGE_HEIGHT_PT * (end - start))
        return start + min(offset, end - start - 1)
    return start


def _chars(layer, start, end):
    if layer is None:
        return 0
    return sum(len(line) + 1 for line in layer.lines[start:end])


def _parts(layer, start, end, max_chars):
    """A line range cut into consecutive ranges of at most `max_chars`; a longer single line stands alone."""
    if layer is None or end <= start:
        return [(start, end)]
    parts, part_start, size = [], start, 0
    for index in range(start, end):
        width = len(layer.lines[index]) + 1
        if size and size + width > max_chars:
            parts.append((part_start, index))
            part_start, size = index, 0
        size += width
    parts.append((part_start, end))
    return parts


def chunk_inventory(inventory, layer=None, max_chars=CHUNK_MAX_CHARS):
    """The chunks of one paper: a list of dicts in reading order, text chunks first, then figures and tables.

    Each chunk carries `id`, `kind` (`text`, `figure`, `table`), `title`, `lines` (1-based,
    inclusive, or None), `chars`, `images` (relative to `refs/<slug>/`: the item's image file, then
    its other `\\includegraphics` targets in the kept source, which are its other panels), `obligations`
    (item ids), and, for rendering, `items` and `text`. A section cut into parts keeps its own
    item on every part, so each reader knows whose text it holds.
    """
    max_chars = max(1, int(max_chars))
    total = len(layer.lines) if layer is not None else 0
    headings, previous = [], 0
    for key in HEADING_KEYS:
        for item in inventory.get(key) or []:
            position = _position(item, layer)
            position = previous if position is None else position
            previous = position
            headings.append((position, len(headings), item))
    headings.sort(key=lambda heading: heading[:2])

    # Headings placed on the same line share one segment: a heading that could not be placed takes
    # the line of the one before it, and giving it a segment of its own would hand its reader no text.
    positions = []
    for position, _, item in headings:
        if positions and positions[-1][0] == position:
            positions[-1][1].append(item)
        else:
            positions.append((position, [item]))
    segments = []
    first = positions[0][0] if positions else total
    if not positions or first > 0:
        segments.append((0, first, []))
    for index, (position, members) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else max(total, position)
        segments.append((position, end, members))

    top = min((item.get("level") or 1 for _, _, item in headings), default=1)
    groups = []
    for start, end, members in segments:
        size = _chars(layer, start, end)
        level = min((item.get("level") or 1 for item in members), default=top)
        joins = (groups and members and level > top and groups[-1]["headings"]
                 and groups[-1]["chars"] + size <= max_chars)
        if joins:
            groups[-1]["end"] = end
            groups[-1]["chars"] += size
            groups[-1]["segments"].append((start, end, members))
            groups[-1]["headings"].extend(members)
        else:
            groups.append({"start": start, "end": end, "chars": size, "segments": [(start, end, members)],
                           "headings": list(members)})

    chunks = []
    for group in groups:
        for part_start, part_end in _parts(layer, group["start"], group["end"], max_chars):
            items = [item for start, end, members in group["segments"] for item in members if (
                part_start == part_end or (start < part_end and max(end, start + 1) > part_start))]
            chunks.append({"kind": "text", "range": (part_start, part_end), "items": items,
                           "title": _heading_title(group["headings"])})

    for key in RIDING_KEYS:
        for item in inventory.get(key) or []:
            position = _position(item, layer)
            chunks_at = [chunk for chunk in chunks if position is not None and chunk["range"][0] <= position]
            inside = [chunk for chunk in chunks_at if position < chunk["range"][1]]
            home = (inside or chunks_at or chunks)[-1 if not inside else 0] if chunks else None
            if home is None:
                home = {"kind": "text", "range": (0, total), "items": [], "title": "The whole paper"}
                chunks.append(home)
            home["items"].append(item)
    chunks = [chunk for chunk in chunks if chunk["items"]]

    result = []
    for chunk in chunks:
        start, end = chunk["range"]
        text = "\n".join(layer.lines[start:end]) if layer is not None else ""
        result.append({
            "kind": "text", "title": chunk["title"], "lines": [start + 1, end] if layer is not None and end > start else None,
            "chars": len(text), "images": [], "items": _in_order(chunk["items"], layer), "text": text,
        })
    for key in OWN_CHUNK_KEYS:
        for item in inventory.get(key) or []:
            text = _captioned_text(item)
            result.append({
                "kind": item.get("kind") or key[:-1], "title": _item_label(item), "lines": None, "chars": len(text),
                "images": _images(item), "items": [item], "text": text,
            })
    for number, chunk in enumerate(result, start=1):
        chunk["id"] = "c-%03d" % number
        chunk["obligations"] = [item["id"] for item in chunk["items"]]
    return result


def _images(item):
    """An item's image file, then the `\\includegraphics` targets the inventory made no image from.

    The inventory makes one image per figure, from the first target that can become one. A figure
    drawn from several files (two panels side by side, measured on 1706.03762's Figures 2, 4, and 5)
    keeps its other panels only in the source, so the reader is pointed at those as well; the chunk
    writer keeps the ones that are on disk.
    """
    targets = item.get("graphics") or []
    images = [item["file"]] if item.get("file") else []
    for target in targets[1:] if images else targets:
        images.append("%s/%s" % (SOURCE, target))
    return images


def _in_order(items, layer):
    """Items in the order a reader meets them, headings before what rides with them at the same line."""
    ranked = [((_position(item, layer) if _position(item, layer) is not None else sys.maxsize),
               0 if item.get("kind") in ("section", "appendix") else 1, index, item)
              for index, item in enumerate(items)]
    return [entry[-1] for entry in sorted(ranked, key=lambda entry: entry[:3])]


def _heading_title(headings):
    if not headings:
        return "Before the first section"
    return _item_label(headings[0])


def _item_label(item):
    kind = str(item.get("kind") or "item")
    number = item.get("number")
    words = [kind.capitalize() if not number else "%s %s" % (kind.capitalize(), number)]
    title = item.get("title") or item.get("caption")
    if title:
        words.append(str(title).strip())
    return ": ".join(words)


def _captioned_text(item):
    """A figure's or a table's own material: caption, source or cells, where it was found."""
    lines = []
    if item.get("caption"):
        lines.append("Caption: %s" % item["caption"])
    if item.get("latex"):
        lines += ["", "Source:", "", item["latex"]]
    if item.get("cells"):
        lines += ["", "Cells as the converter read them:", ""]
        lines += [" | ".join("" if cell is None else str(cell) for cell in row) for row in item["cells"]]
    return "\n".join(lines).strip()


def _fence(text, marker="`"):
    longest = max((len(run) for run in re.findall(r"%s+" % re.escape(marker), text)), default=0)
    return marker * max(3, longest + 1)


READING_RULES = """\
Return one entry for every item on the obligation list below, and none for anything that is not
on it. Every entry has:

- `item_id`: the id exactly as the list gives it, and `kind` as the list gives it.
- `locator`: where you read the item, as `<file>:<line>` with the line numbers printed in the
  margin of the text, or the page the list gives for it.
- `content`: the item in exact form. An equation or an algorithm as the source writes it, a
  theorem's statement word for word, a table's cells, a section's argument in the paper's own
  terms and numbers. Where the list asks you to confirm a field, check it against the text or the
  image and write what is really there.
- `importance`: 1 when the item is incidental to the paper, 5 when the paper stands on it.
- `relation_to_intent`: how the item bears on the project's intent; empty when it does not.
- `oddities`: anything that does not add up, one string each: a number that disagrees with
  another, a step that is skipped, a symbol never defined, text that was cut. Empty when nothing is.

A figure's entry also has `what_it_shows` (read off the image itself, not the caption),
`supports_cited_claim` (the claim that cites the figure, and whether what it shows supports it),
and `anything_odd` (axes, scales, error bars, or panels that mislead; empty when nothing does).

When an item leans on something this chunk does not carry (a symbol defined in another section, a
setting given elsewhere), you may put one clarification question in `question`, beside the
entries: the consultant answers it from the whole dossier, and the answer is recorded for the
paper. Write your entries from what you were given either way; leave `question` out when you
have none.
"""


def render_chunk(slug, chunk, layer_path=None, image_paths=(), intent=None):
    """One chunk's file: how to read it, the intent, the obligation list, the images, and the numbered text."""
    parts = ["# Chunk %s of `%s`: %s" % (chunk["id"], slug, chunk["title"])]
    if chunk["kind"] == "text" and chunk["lines"]:
        parts.append("Lines %d to %d of `%s`." % (chunk["lines"][0], chunk["lines"][1], layer_path))
    elif chunk["kind"] == "text":
        parts.append("[wayline: this paper has no text layer to print. Read each item at its locator in the "
                     "source; an item you cannot find there is an oddity of its entry, not something to guess.]")
    parts.append("## How to read it\n\n" + READING_RULES.rstrip())
    parts.append("## The project's intent\n\n" + (intent.strip() if intent and intent.strip()
                                                  else "The project states no intent yet; leave `relation_to_intent` empty."))
    parts.append("## The obligation list\n\n" + "\n".join(_obligation(item) for item in chunk["items"]))
    if chunk["kind"] != "text":
        if image_paths:
            parts.append("## The image\n\nOpen every file below with the Read tool and look at it before you write the "
                         "entry. A figure drawn from more than one file has one file per panel, and what it shows is "
                         "all of them.\n\n" + "\n".join("- `%s`" % path for path in image_paths))
        else:
            parts.append("## The image\n\n[wayline: the inventory has no image file for this item. Say in "
                         "`what_it_shows` that the image was not available, and read what the caption and source allow.]")
    body = chunk["text"]
    if chunk["kind"] == "text" and chunk["lines"]:
        width = len(str(chunk["lines"][1]))
        body = "\n".join("%*d| %s" % (width, number, line.replace("\f", ""))
                         for number, line in enumerate(body.split("\n"), start=chunk["lines"][0]))
    if body:
        fence = _fence(body)
        parts.append("## The text\n\n%stext\n%s\n%s" % (fence, body, fence))
    return "\n\n".join(parts) + "\n"


def _obligation(item):
    words = ["- `%s`: %s" % (item["id"], item.get("kind"))]
    if item.get("number"):
        words.append(" %s" % item["number"])
    if item.get("title"):
        words.append(", \"%s\"" % str(item["title"]).strip())
    words.append(", at `%s`" % item.get("locator"))
    if item.get("page"):
        words.append(", page %s" % item["page"])
    if item.get("confirm"):
        fields = item.get("confirm_fields") or []
        words.append("; confirm: %s" % (", ".join(fields) if fields else "its number and where it ends"))
    if item.get("ocr"):
        words.append("; its LaTeX was read off the page and is not exact form")
    line = "".join(words)
    if item.get("kind") in ("equation", "algorithm", "theorem") and item.get("latex"):
        fence = _fence(item["latex"])
        line += "\n\n  %slatex\n  %s\n  %s" % (fence, item["latex"].replace("\n", "\n  "), fence)
    return line


def _refs(slug, *parts):
    return "/".join((REFS, slug) + parts)


def _project_path(slug, *parts):
    return "research/" + _refs(slug, *parts)


def write_chunks(ledger, slug, inventory, layer=None, intent=None, max_chars=CHUNK_MAX_CHARS):
    """Cut the paper, write every chunk file and the manifest under `refs/<slug>/absorb/`; returns the manifest.

    The directory is replaced whole, so a second absorb never leaves the chunks of the first beside
    its own. Paths in the manifest are relative to the project root, where the absorb session runs.
    """
    chunks = chunk_inventory(inventory, layer, max_chars)
    ledger.remove_tree(_refs(slug, ABSORB_DIR))
    layer_path = _project_path(slug, layer.path) if layer is not None else None
    listed = []
    for chunk in chunks:
        images = [_project_path(slug, image) for image in chunk["images"] if (ledger.research / REFS / slug / image).is_file()]
        relative = _refs(slug, ABSORB_DIR, CHUNKS, chunk["id"] + ".md")
        ledger.write_markdown(relative, render_chunk(slug, chunk, layer_path, images, intent))
        listed.append({
            "id": chunk["id"], "kind": chunk["kind"], "title": chunk["title"], "path": "research/" + relative,
            "images": images, "lines": chunk["lines"], "chars": chunk["chars"], "obligations": chunk["obligations"],
        })
    manifest = {
        "schema_version": 1, "slug": slug, "created": now_ts(),
        "inventory": _project_path(slug, INVENTORY), "text_layer": layer_path, "chunk_max_chars": int(max_chars),
        "items": sum(len(inventory.get(key) or []) for key in ITEM_KEYS), "chunks": listed,
    }
    ledger.write_json(_refs(slug, ABSORB_DIR, MANIFEST), manifest)
    return manifest


# --- the fan-out --------------------------------------------------------------------------------


@dataclass
class Context:
    """What either fan-out needs to read one paper: the project, the manifest, the policy, the launcher."""

    project: Path
    ledger: object
    slug: str
    manifest: dict
    policy: dict
    harness_root: Path
    intent: Optional[str]
    intent_path: Optional[str]
    launcher: Callable
    projects_dir: Path
    base_dir: Path
    resumer: Optional[Callable] = None  # `(request, session_id, message) -> Envelope`, the launcher's own resume


@dataclass
class Fanout:
    """What a fan-out hands back: the `absorb_result` object (or None), and how it got it."""

    result: Optional[dict] = None
    session_ids: list = field(default_factory=list)
    allow_rules: Optional[str] = None
    run_file: Optional[str] = None
    cost: dict = field(default_factory=lambda: {"agents": None, "tokens": None, "duration_ms": None})
    problems: list = field(default_factory=list)


def _tier(policy, role):
    entry = ((policy or {}).get("roles") or {}).get(role) or {}
    fallback = ROLE_FALLBACKS[role]
    return entry.get("model") or fallback[0], entry.get("effort") or fallback[1]


def _minutes(policy, budget):
    return (((policy or {}).get("budget") or {}).get(budget) or {}).get("max_minutes")


def _session_base(project, slug):
    base = Path(project) / "research" / SESSIONS / slug
    number = 1
    while (base / str(number)).exists():
        number += 1
    return base / str(number)


def _env(context, run_dir, extra=None):
    env = {"WAYLINE_PROJECT": str(context.project), "WAYLINE_RUN": str(run_dir)}
    env.update(extra or {})
    return env


def _settings(context, run_dir):
    run_dir.mkdir(parents=True, exist_ok=True)
    return gates.write_worker_settings(run_dir / "settings.json", context.harness_root)


def workflow_args(context):
    """The `args` the saved workflow takes: the chunks to read, and the tiers the policy gives its roles.

    `consultant` also carries how many of the readers' questions one absorb may ask, which is
    `policy.consultant.max_questions_per_ticket`, and the dossier directory it answers from.
    """
    reader, synthesizer = _tier(context.policy, READER), _tier(context.policy, SYNTHESIZER)
    consultant = _tier(context.policy, CONSULTANT)
    return {
        "slug": context.slug,
        "manifest": _project_path(context.slug, ABSORB_DIR, MANIFEST),
        "intent": context.intent_path,
        "reader": {"model": reader[0], "effort": reader[1]},
        "synthesizer": {"model": synthesizer[0], "effort": synthesizer[1]},
        "consultant": {"model": consultant[0], "effort": consultant[1], "dossier": _project_path(context.slug),
                       "max_questions": consult.question_limit(context.policy)},
        "chunks": [{"id": chunk["id"], "path": chunk["path"], "images": chunk["images"], "obligations": chunk["obligations"]}
                   for chunk in context.manifest["chunks"]],
    }


def session_prompt(context):
    """The absorb session's prompt: `/absorb <manifest>` first, then the exact `args` to start the workflow with."""
    return (
        "/absorb %s\n\n"
        "Start the saved workflow `absorb` once, with its `args` set to exactly the JSON object below. "
        "Pass it as an object, not as a string holding one, and change nothing in it.\n\n"
        "%s\n```json\n%s\n```\n\n"
        "When the run ends, reply with one line: its run id and its status.\n"
    ) % (_project_path(context.slug, ABSORB_DIR, MANIFEST), ARGS_MARKER, json.dumps(workflow_args(context), indent=2))


def _broaden(rule):
    """`Workflow(absorb)` to `Workflow`: the fallback the spec names when the narrow rule is refused."""
    return rule.split("(", 1)[0] if rule.startswith(("Workflow(", "Skill(")) else rule


def _refused(envelope):
    """The Workflow or Skill calls the session's permissions refused, by tool name."""
    names = []
    for denial in envelope.permission_denials or []:
        tool = denial.get("tool_name") if isinstance(denial, dict) else None
        if tool in ("Workflow", "Skill"):
            names.append(tool)
    return names


def workflow_fanout(context):
    """One `claude -p` session running `workflows/absorb.js`; the result comes from its run file.

    The narrow allow rules (`Workflow(absorb)`, `Skill(absorb)`) are tried first. When the session
    reports either tool refused and no run file appeared, the session is launched once more with the
    broad rules (`Workflow`, `Skill`), and `allow_rules` records which of the two produced the run.
    """
    outcome = Fanout()
    try:
        session = worker.read_role(SESSION_ROLE, context.harness_root, context.project)
        readers = worker.read_role(READER, context.harness_root, context.project)
        synthesizers = worker.read_role(SYNTHESIZER, context.harness_root, context.project)
        consultants = worker.read_role(CONSULTANT, context.harness_root, context.project)
    except worker.RoleError as failure:
        outcome.problems.append(str(failure))
        return outcome
    agents = {}
    agents.update(session.agent_json(SESSION_MODEL, SESSION_EFFORT))
    agents.update(readers.agent_json(*_tier(context.policy, READER)))
    agents.update(synthesizers.agent_json(*_tier(context.policy, SYNTHESIZER)))
    agents.update(consultants.agent_json(*_tier(context.policy, CONSULTANT)))
    narrow = list(session.allowed_tools)
    for rules, allowed in ((NARROW, narrow), (BROAD, [_broaden(rule) for rule in narrow])):
        run_dir = context.base_dir / ("session-%s" % rules)
        request = worker.LaunchRequest(
            role=session.name, model=SESSION_MODEL, effort=SESSION_EFFORT, prompt=session_prompt(context),
            agent_json=agents, allowed_tools=allowed, disallowed_tools=list(session.disallowed_tools),
            settings_path=_settings(context, run_dir), add_dirs=[], cwd=context.project,
            env=_env(context, run_dir, WAIT_CEILING), schema_path=None,
            max_minutes=_minutes(context.policy, "large"),
        )
        try:
            envelope = context.launcher(request)
        except worker.LaunchError as failure:
            outcome.problems.append("the absorb session could not be launched: %s" % failure)
            return outcome
        if envelope.session_id:
            outcome.session_ids.append(envelope.session_id)
        run_file = find_run_file(envelope.session_id, context.projects_dir) if envelope.session_id else None
        if run_file is not None:
            outcome.allow_rules = rules
            outcome.run_file = str(run_file)
            status, result, cost = read_run_file(run_file)
            outcome.cost = cost
            if status not in (None, "completed"):
                outcome.problems.append("the workflow run %s ended %s" % (run_file.name, status))
            problems = _result_problems(result)
            if problems:
                outcome.problems.append("the workflow run %s returned no usable absorb_result: %s" % (run_file.name, problems))
            else:
                outcome.result = result
            return outcome
        limit = pacing.hit_limit(envelope, worker.stderr_of(envelope), model=request.model)
        if limit is not None:
            outcome.problems.append("the usage limit refused the absorb session on %s; it is not launched again with other "
                                    "rules, and absorbing again once the window allows launches it fresh"
                                    % ("Fable's weekly window" if limit.model == pacing.FABLE else "the %s window" % limit.window))
            return outcome
        refused = _refused(envelope)
        detail = "; ".join(envelope.errors) or (envelope.result_text or "").strip() or "no reason given"
        if rules == NARROW and refused:
            outcome.problems.append("the narrow rules Workflow(absorb) and Skill(absorb) were refused (%s); "
                                    "launching again with Workflow and Skill" % ", ".join(sorted(set(refused))))
            continue
        outcome.problems.append("the absorb session %s left no workflow run file: %s"
                                % (envelope.session_id or "(no session id)", detail))
        return outcome
    return outcome


def _result_problems(result):
    if not isinstance(result, dict):
        return "the result is %s, not an object" % type(result).__name__
    errors = validate(result, load_schema("absorb_result"))
    return "; ".join("%s: %s" % (error.path, error.message) for error in errors)


def claude_projects_dir():
    """`~/.claude/projects`, or the one under `CLAUDE_CONFIG_DIR` when that names another home."""
    home = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(home) if home else Path.home() / ".claude") / "projects"


def find_run_file(session_id, projects_dir=None):
    """The Workflow run file of a session: `<projects>/*/<session_id>/workflows/wf_*.json`.

    The glob needs no cwd slug (the spec's rule). A session that ran the workflow more than once
    is answered by its latest completed run, or its latest run when none completed.
    """
    if not session_id or "/" in str(session_id):
        return None
    candidates = sorted(Path(projects_dir or claude_projects_dir()).glob("*/%s/workflows/wf_*.json" % session_id),
                        key=lambda path: path.stat().st_mtime)
    if not candidates:
        return None
    for path in reversed(candidates):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("status") == "completed":
                return path
        except (OSError, ValueError):
            continue
    return candidates[-1]


def read_run_file(path):
    """`(status, result, cost)` of a run file: the script's return value and what the run spent."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None, {"agents": None, "tokens": None, "duration_ms": None}
    result = data.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            pass
    cost = {"agents": _integer(data.get("agentCount")), "tokens": _integer(data.get("totalTokens")),
            "duration_ms": _integer(data.get("durationMs"))}
    return data.get("status"), result, cost


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


MISSING_RESUME = (
    "Your entries left out these items of the obligation list: %s. Return the whole list again "
    "through the structured output, with one entry for every item on the obligation list."
)
INVALID_RESUME = (
    "The result you returned could not be used: %s. Return it again through the structured output, "
    "with one entry for every item on the obligation list."
)
SYNTHESIZER_INSTRUCTIONS = (
    "Write the prose sections of the level-2 dossier of `%s` from the readers' entries below and from "
    "nothing else: method, claims, results, assumptions, limitations, flaws found, reusable ideas, open "
    "questions, and the relation to the project's intent. Every sentence carries at least one locator "
    "copied from the entries it rests on, an entry's `locator` or its `item_id`. A section with nothing "
    "to say is an empty list."
)


def synthesizer_prompt(slug, intent, entries):
    """The conductor fan-out's synthesizer prompt: the instructions, the intent, one entry per line."""
    parts = [SYNTHESIZER_INSTRUCTIONS % slug]
    parts.append("## The project's intent\n\n%s" % (intent.strip() if intent and intent.strip() else "The project states no intent yet."))
    parts.append("## The entries, one JSON object per line\n\n" + "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries))
    return "\n\n".join(parts) + "\n"


def _add_usage(cost, envelope):
    cost["agents"] = (cost["agents"] or 0) + 1
    usage = envelope.usage or {}
    tokens = sum(value for key, value in usage.items() if key.endswith("tokens") and isinstance(value, int))
    cost["tokens"] = (cost["tokens"] or 0) + tokens
    cost["duration_ms"] = (cost["duration_ms"] or 0) + (envelope.duration_ms or 0)


def conductor_fanout(context):
    """N reader sessions, one chunk each, then one synthesizer session; the bookkeeping is here.

    A reader whose result is invalid, or leaves obligation items out, is resumed once with the
    reason; what is still missing after that is a failure of its chunk. The chunk file is pasted
    into the reader's prompt whole, and a figure's or table's reader may open its image.
    """
    outcome = Fanout(allow_rules=None, cost={"agents": 0, "tokens": 0, "duration_ms": 0})
    try:
        readers = worker.read_role(READER, context.harness_root, context.project)
        synthesizers = worker.read_role(SYNTHESIZER, context.harness_root, context.project)
    except worker.RoleError as failure:
        outcome.problems.append(str(failure))
        return outcome
    model, effort = _tier(context.policy, READER)
    image_tools = [tool for tool in readers.disallowed_tools if tool not in READ_TOOLS]
    entries, failures, asked = [], [], []
    for chunk in context.manifest["chunks"]:
        run_dir = context.base_dir / chunk["id"]
        prompt = (context.project / chunk["path"]).read_text(encoding="utf-8")
        request = worker.LaunchRequest(
            role=readers.name, model=model, effort=effort, prompt=prompt,
            agent_json=readers.agent_json(model, effort), allowed_tools=list(READ_TOOLS), disallowed_tools=image_tools,
            settings_path=_settings(context, run_dir), add_dirs=[], cwd=context.project, env=_env(context, run_dir),
            schema_path=context.harness_root / "schemas" / "dossier_entry_list.json",
            max_minutes=_minutes(context.policy, "small"),
        )
        got, reason = _read_chunk(context, request, chunk, outcome, asked)
        missing = [item for item in chunk["obligations"] if item not in {entry["item_id"] for entry in got}]
        entries.extend(dict(entry, chunk_id=chunk["id"]) for entry in got)
        if missing or reason:
            failures.append({"chunk": chunk["id"], "reason": reason or "the reader left obligation items out", "missing": missing})

    sections = None
    if entries:
        model, effort = _tier(context.policy, SYNTHESIZER)
        run_dir = context.base_dir / SYNTHESIZER
        request = worker.LaunchRequest(
            role=synthesizers.name, model=model, effort=effort,
            prompt=synthesizer_prompt(context.slug, context.intent, entries),
            agent_json=synthesizers.agent_json(model, effort), allowed_tools=list(synthesizers.allowed_tools),
            disallowed_tools=list(synthesizers.disallowed_tools), settings_path=_settings(context, run_dir), add_dirs=[],
            cwd=context.project, env=_env(context, run_dir),
            schema_path=context.harness_root / "schemas" / "dossier_sections.json",
            max_minutes=_minutes(context.policy, "medium"),
        )
        envelope = _launch(context, request, outcome)
        if envelope is not None and not envelope.valid and envelope.session_id \
                and pacing.hit_limit(envelope, worker.stderr_of(envelope), model=request.model) is None:  # a refused session is never resumed
            envelope = _resume(context, request, envelope.session_id, INVALID_RESUME % ("; ".join(envelope.errors) or "no structured output"), outcome) or envelope
        if envelope is not None and envelope.valid:
            sections = envelope.structured_output
        else:
            failures.append({"chunk": None, "reason": "the synthesizer returned no valid sections: %s"
                             % ("; ".join(envelope.errors) if envelope is not None else "it could not be launched"), "missing": []})
    else:
        failures.append({"chunk": None, "reason": "no reader returned an entry, so the synthesizer was not launched", "missing": []})
    outcome.result = {"entries": entries, "sections": sections, "failures": failures,
                      "consultations": _consult_readers(context, asked, outcome)}
    return outcome


def _consult_readers(context, asked, outcome):
    """The conductor fan-out's consultant: one session per reader question, up to the policy's limit.

    The answers are returned unrecorded, as the workflow's are, so `absorb_level_2` records both alike.
    """
    limit = consult.question_limit(context.policy)
    consultations = []
    refused = None
    for index, item in enumerate(asked):
        if index >= limit:
            consultations.append(dict(item, answer=None, reason="past the %d question(s) one absorb may ask" % limit))
            continue
        if refused:
            consultations.append(dict(item, answer=None, reason="not asked: %s" % refused))
            continue
        try:
            request = consult.consult_request(context.project, context.slug, item["question"], LEVEL_2,
                                              harness_root=context.harness_root, policy=context.policy)
        except (worker.RoleError, OSError) as failure:
            consultations.append(dict(item, answer=None, reason="the consultant could not be launched: %s" % failure))
            continue
        envelope = _launch(context, request, outcome)
        if envelope is not None and not envelope.valid \
                and pacing.hit_limit(envelope, worker.stderr_of(envelope), model=request.model) is not None:
            refused = "the usage limit refused the consultant, and no further question is put to it in this read"
            consultations.append(dict(item, answer=None, reason=refused))
            continue
        if envelope is None or not envelope.valid:
            reason = "; ".join(envelope.errors) if envelope is not None else "it could not be launched"
            consultations.append(dict(item, answer=None, reason="the consultant returned no answer: %s" % (reason or "no structured output")))
            continue
        consultations.append(dict(item, answer=envelope.structured_output, session_id=envelope.session_id))
    return consultations


def _launch(context, request, outcome):
    try:
        envelope = context.launcher(request)
    except worker.LaunchError as failure:
        outcome.problems.append("a %s session could not be launched: %s" % (request.role, failure))
        return None
    _record(envelope, outcome)
    return envelope


def _resume(context, request, session_id, message, outcome):
    """One resume through the resumer that goes with the context's launcher; None when there is none.

    A caller that hands `absorb_level_2` a launcher of its own and no resumer gets no resume at all,
    rather than a resume on whatever backend `WAYLINE_LAUNCHER` names, where the session is not.
    """
    if context.resumer is None:
        outcome.problems.append("a %s session needed a resume, and the launcher it was given came with no resumer" % request.role)
        return None
    try:
        envelope = context.resumer(request, session_id, message)
    except worker.LaunchError as failure:
        outcome.problems.append("a %s session could not be resumed: %s" % (request.role, failure))
        return None
    _record(envelope, outcome)
    return envelope


def _record(envelope, outcome):
    if envelope.session_id and envelope.session_id not in outcome.session_ids:
        outcome.session_ids.append(envelope.session_id)
    _add_usage(outcome.cost, envelope)


def _question(envelope, chunk, asked):
    """Note the reader's clarification question, once per chunk."""
    question = (envelope.structured_output or {}).get("question") if envelope is not None and envelope.valid else None
    if isinstance(question, str) and question.strip() and chunk["id"] not in {item["chunk"] for item in asked}:
        asked.append({"chunk": chunk["id"], "question": question})


def _read_chunk(context, request, chunk, outcome, asked):
    """One reader and at most one resume: `(entries, reason)`, the reason None when nothing went wrong.

    A clarification question the reader asked, at launch or on the resume, is appended to `asked`.
    """
    envelope = _launch(context, request, outcome)
    if envelope is None:
        return [], "the reader could not be launched"
    _question(envelope, chunk, asked)
    got = list(envelope.structured_output["entries"]) if envelope.valid else []
    missing = [item for item in chunk["obligations"] if item not in {entry["item_id"] for entry in got}]
    if envelope.valid and not missing:
        return got, None
    if not envelope.valid and pacing.hit_limit(envelope, worker.stderr_of(envelope), model=request.model) is not None:
        return got, "the usage limit refused the reader, and a refused session is never resumed; absorb again once the window allows"
    if not envelope.session_id:
        return got, "the reader returned no valid entries and no session to resume: %s" % "; ".join(envelope.errors)
    message = MISSING_RESUME % ", ".join(missing) if envelope.valid else INVALID_RESUME % ("; ".join(envelope.errors) or "no structured output")
    resumed = _resume(context, request, envelope.session_id, message, outcome)
    _question(resumed, chunk, asked)
    if resumed is None or not resumed.valid:
        return got, "the reader's resume returned no valid entries: %s" % ("; ".join(resumed.errors) if resumed is not None else "it could not be resumed")
    have = {entry["item_id"] for entry in got}
    return got + [entry for entry in resumed.structured_output["entries"] if entry["item_id"] not in have], None


FANOUT_FUNCTIONS = {WORKFLOW: workflow_fanout, CONDUCTOR: conductor_fanout}


# --- merging, the coverage audit, and the spot-check ---------------------------------------------


def _items(inventory):
    return [item for key in ITEM_KEYS for item in inventory.get(key) or []]


def merge_entries(inventory, result):
    """The entries code keeps, in inventory order, and the problems with the ones it did not keep.

    An entry the `dossier_entry` schema refuses, or one naming an item the inventory does not
    have, is dropped with its reason; an entry whose kind disagrees with the inventory's is kept
    and the disagreement noted, because the item it answers is still the item it names.
    """
    known = {item["id"]: (index, item) for index, item in enumerate(_items(inventory))}
    schema = load_schema("dossier_entry")
    kept, problems = [], []
    for number, entry in enumerate(result.get("entries") or [], start=1):
        errors = validate(entry, schema)
        if errors:
            problems.append("entry %d was dropped: %s" % (number, "; ".join("%s: %s" % (error.path, error.message) for error in errors[:3])))
            continue
        if entry["item_id"] not in known:
            problems.append("entry %d names %s, which the inventory does not have; dropped" % (number, entry["item_id"]))
            continue
        expected = known[entry["item_id"]][1].get("kind")
        if expected and entry["kind"] != expected:
            problems.append("entry %d answers %s as a %s; the inventory has a %s" % (number, entry["item_id"], entry["kind"], expected))
        kept.append(entry)
    kept.sort(key=lambda entry: (known[entry["item_id"]][0], entry.get("chunk_id") or ""))
    return kept, problems


def audit_coverage(inventory, entries):
    """The Type-A gate: every inventory item has an entry, and every figure an entry that says what it shows."""
    answered, described = set(), set()
    for entry in entries:
        answered.add(entry["item_id"])
        if str(entry.get("what_it_shows") or "").strip():
            described.add(entry["item_id"])
    missing = []
    for item in _items(inventory):
        covered = item["id"] in (described if item.get("kind") == "figure" else answered)
        if not covered:
            missing.append(item["id"])
    items = len(_items(inventory))
    return {"pass": not missing, "items": items, "covered": items - len(missing), "missing": missing}


def _locator_path(locator):
    return Path(re.split(r"[:#]", str(locator), maxsplit=1)[0]).name


def unresolved_locators(sections, entries, inventory):
    """Sentence locators that name neither an item, nor an entry's locator, nor a file an entry or item was read in."""
    if not sections:
        return []
    ids = {item["id"] for item in _items(inventory)}
    exact = {entry["locator"] for entry in entries}
    files = {_locator_path(entry["locator"]) for entry in entries} | {_locator_path(item.get("locator") or "") for item in _items(inventory)}
    files.discard("")
    unresolved = []
    for key in SECTION_KEYS:
        for sentence in sections.get(key) or []:
            for locator in sentence["locators"]:
                if locator in ids or locator in exact or _locator_path(locator) in files:
                    continue
                if locator not in unresolved:
                    unresolved.append(locator)
    return unresolved


def _spot_check_author(policy):
    """The author whose verifier tier the critic runs on, and a problem when the spot-check cannot run on that tier.

    The check exists for the flaws, and the flaws were written on the synthesizer's model, so the critic
    runs on the verifier `policy.verifier` gives for that model, or for the reader's when the table gives
    the synthesizer's none it can take. It may be the author's own model: the critic is a fresh session
    carrying none of the dossier's context, which is what keeps it from judging its own work (decision 11).
    A depth spot-check never runs on Haiku (decision 15), so a table that gives neither author a verifier
    other than Haiku is a problem, and the gate refuses the spot-check until the table names another model.
    """
    authors = [_tier(policy, SYNTHESIZER)[0], _tier(policy, READER)[0]]
    reasons = []
    for author in authors:
        try:
            model, _ = gates.verifier_tier(policy, author)
        except gates.GateError as failure:
            reasons.append(str(failure))
            continue
        if model == pacing.HAIKU:
            reasons.append("policy.verifier sends %s to haiku" % author)
            continue
        return author, None
    return authors[0], ("the depth spot-check stays queued and cannot be taken: it never runs on haiku, and neither the "
                        "synthesizer's %s nor the reader's %s gets another verifier (%s)" % (authors[0], authors[1], "; ".join(reasons)))


def spot_check_ask(slug, inventory, entries, sections, author_model, text_layer_path=None):
    """The depth spot-check for the critic: the five most important items and every claimed flaw."""
    order = {item["id"]: index for index, item in enumerate(_items(inventory))}
    ranked, chosen = sorted(entries, key=lambda entry: (-entry["importance"], order.get(entry["item_id"], 0))), []
    for entry in ranked:
        if entry["item_id"] not in chosen:
            chosen.append(entry["item_id"])
        if len(chosen) == SPOT_CHECK_ITEMS:
            break
    flaws = list((sections or {}).get("flaws_found") or [])
    lines = ["Was `refs/%s` read in depth? For each item below, does its entry in `entries.jsonl` give the item "
             "in exact form, at a locator where the source really has it, with nothing the source does not "
             "say; and for each claimed flaw below, is the flaw really in the paper?" % slug, "", "Items:"]
    lines += ["- %s" % item_id for item_id in chosen] or ["- (none)"]
    lines += ["", "Claimed flaws:"]
    lines += ["- %s (%s)" % (flaw["text"], "; ".join(flaw["locators"])) for flaw in flaws] or ["- (none claimed)"]
    paths = [_project_path(slug, DOSSIER_MD), _project_path(slug, ENTRIES), _project_path(slug, INVENTORY)]
    if text_layer_path:
        paths.append(text_layer_path)
    images = {item["id"]: item.get("file") for item in _items(inventory) if item.get("file")}
    paths += [_project_path(slug, images[item_id]) for item_id in chosen if item_id in images]
    return gates.Ask(
        subject_kind="dossier", subject=_refs(slug), question="\n".join(lines), paths=paths,
        scope_limit=("Only the %d item(s) and %d claimed flaw(s) listed, checked against the source at their "
                     "locators. The rest of the dossier, and whether the paper is right, are outside it."
                     % (len(chosen), len(flaws))),
        verdict_type=gates.DEPTH_SPOT_CHECK, author_model=author_model, role=CRITIC,
    ), chosen, len(flaws)


SECTION_TITLES = {
    "method": "Method", "claims": "Claims", "results": "Results", "assumptions": "Assumptions",
    "limitations": "Limitations", "flaws_found": "Flaws found", "reusable_ideas": "Reusable ideas",
    "open_questions": "Open questions", "relation_to_intent": "Relation to the intent",
}


def render_dossier_markdown(dossier, entries):
    """`dossier.md`: the level-2 dossier for a reader, rendered from `dossier.json` and the entries."""
    l2 = dossier["l2"]
    title = (dossier.get("metadata") or {}).get("title") or dossier["slug"]
    coverage = l2["coverage"]
    lines = ["# %s" % title, "",
             "`refs/%s` at level %d, absorbed %s by the %s fan-out: %d chunk(s), %d entr%s."
             % (dossier["slug"], dossier["level"], l2["absorbed"], l2["fanout"], l2["chunks"], l2["entries"],
                "y" if l2["entries"] == 1 else "ies"), "",
             "Coverage audit: %s, %d of %d inventory items covered%s." % (
                 "pass" if coverage["pass"] else "FAIL", coverage["covered"], coverage["items"],
                 "" if coverage["pass"] else "; missing %s" % ", ".join(coverage["missing"])),
             "Depth spot-check: %s by the %s.%s" % (
                 l2["spot_check"]["status"], l2["spot_check"]["role"],
                 " Taken on %s in place of %s, whose weekly window was spent." % (l2["spot_check"].get("model") or "an unnamed model",
                                                                                  l2["spot_check"]["fallback_from"])
                 if l2["spot_check"].get("fallback_from") else "")]
    lines += ["- [%s] %s (%s)" % (finding.get("severity", "?"), finding.get("text", ""), finding.get("locator", "?"))
              for finding in l2["spot_check"].get("findings") or []]
    if l2["failures"]:
        lines += ["", "What came back short:"]
        lines += ["- %s: %s%s" % (failure["chunk"] or "synthesizer", failure["reason"],
                                  " (missing %s)" % ", ".join(failure["missing"]) if failure["missing"] else "")
                  for failure in l2["failures"]]
    sections = l2.get("sections")
    for key in SECTION_KEYS:
        lines += ["", "## %s" % SECTION_TITLES[key], ""]
        sentences = (sections or {}).get(key) or []
        if not sentences:
            lines.append("Nothing." if sections else "[wayline: the synthesizer returned no sections.]")
        lines += ["- %s [%s]" % (sentence["text"].strip(), "; ".join(sentence["locators"])) for sentence in sentences]
    lines += ["", "## Entries"]
    for entry in entries:
        lines += ["", "### %s (%s, `%s`, importance %d)" % (entry["item_id"], entry["kind"], entry["locator"], entry["importance"]), ""]
        fence = _fence(entry["content"])
        lines += [fence, entry["content"], fence]
        if entry.get("what_it_shows"):
            lines += ["", "- What it shows: %s" % entry["what_it_shows"],
                      "- Supports the cited claim: %s" % entry.get("supports_cited_claim", ""),
                      "- Anything odd: %s" % (entry.get("anything_odd") or "nothing")]
        if entry.get("relation_to_intent"):
            lines.append("- Relation to the intent: %s" % entry["relation_to_intent"])
        lines += ["- Oddity: %s" % oddity for oddity in entry.get("oddities") or []]
    return "\n".join(lines) + "\n"


# --- the whole absorb ---------------------------------------------------------------------------


def _read_layer(ledger, slug, inventory):
    layer = inventory.get("text_layer") or {}
    path = layer.get("path")
    if not path:
        return None
    try:
        text = (ledger.research / REFS / slug / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text_layer(text, path)


def _intent(project):
    path = Path(project) / "research" / INTAKE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    cut = text[:INTENT_MAX_CHARS]
    if len(text) > INTENT_MAX_CHARS:
        cut += "\n\n[wayline: INTAKE.md was cut here at %d characters.]" % INTENT_MAX_CHARS
    return cut, "research/" + INTAKE


def absorb_level_2(project, slug, launcher=None, harness_root=None, ledger=None, fanout=None, projects_dir=None, resumer=None):
    """Read one promoted paper in full and write its level-2 dossier. Returns a report.

    `launcher` and `resumer` default to the seam's `worker.launch` and `worker.resume`; a caller
    that passes its own launcher passes its resumer with it, or the conductor fan-out resumes nothing.

    Refuses a paper that is not at level 2 (promote it first) or has no inventory. Raises
    DossierError when the fan-out brings back nothing at all, which leaves the dossier as it
    was; a partial result is merged, audited, and journaled like a whole one, and its gaps are
    what the coverage audit fails on.
    """
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    policy = policy_for(project, harness_root)
    absorb = policy.get("absorb") or {}
    fanout = fanout or absorb.get("fanout") or WORKFLOW
    if fanout not in FANOUTS:
        raise DossierError("policy.absorb.fanout is one of %s, got %r" % (", ".join(FANOUTS), fanout))
    dossier = read_dossier(ledger, slug)
    if dossier.get("level", 0) < LEVEL_2:
        raise DossierError("%s is at level %d; a level-2 read is earned by a promotion first (dossier.promote)"
                           % (slug, dossier.get("level", 0)))
    try:
        inventory = ledger.read_json(_refs(slug, INVENTORY))
    except (OSError, ValueError):
        raise DossierError("%s has no inventory; run `wayline absorb --inventory %s` first" % (slug, slug)) from None

    layer = _read_layer(ledger, slug, inventory)
    intent, intent_path = _intent(project)
    manifest = write_chunks(ledger, slug, inventory, layer, intent, absorb.get("chunk_max_chars", CHUNK_MAX_CHARS))
    context = Context(
        project=project, ledger=ledger, slug=slug, manifest=manifest, policy=policy, harness_root=harness_root,
        intent=intent, intent_path=intent_path, launcher=launcher or worker.launch,
        projects_dir=Path(projects_dir) if projects_dir else claude_projects_dir(), base_dir=_session_base(project, slug),
        resumer=resumer if resumer is not None else (worker.resume if launcher is None else None),
    )
    outcome = FANOUT_FUNCTIONS[fanout](context)
    if outcome.result is None:
        raise DossierError("the %s fan-out for %s brought nothing back: %s"
                           % (fanout, slug, "; ".join(outcome.problems) or "no reason given"))

    entries, problems = merge_entries(inventory, outcome.result)
    problems = outcome.problems + problems
    sections = outcome.result.get("sections")
    if sections is not None:
        errors = validate(sections, load_schema("dossier_sections"))
        if errors:
            problems.append("the sections were dropped: %s" % "; ".join("%s: %s" % (error.path, error.message) for error in errors[:3]))
            sections = None
    coverage = audit_coverage(inventory, entries)
    author, author_problem = _spot_check_author(policy)
    if author_problem:
        problems.append(author_problem)
    ask, chosen, flaws = spot_check_ask(slug, inventory, entries, sections, author, manifest["text_layer"])
    session_id = outcome.session_ids[-1] if outcome.session_ids else None
    consulted = _record_consultations(ledger, slug, outcome.result.get("consultations") or [], session_id, problems)

    ledger.write_bytes(_refs(slug, ENTRIES), "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries).encode("utf-8"))
    dossier["l2"] = {
        "absorbed": now_ts(), "fanout": fanout, "allow_rules": outcome.allow_rules, "session_ids": list(outcome.session_ids),
        "run_file": outcome.run_file, "manifest": _project_path(slug, ABSORB_DIR, MANIFEST),
        "entries_path": _project_path(slug, ENTRIES), "markdown_path": _project_path(slug, DOSSIER_MD),
        "chunks": len(manifest["chunks"]), "entries": len(entries), "coverage": coverage, "sections": sections,
        "unresolved_locators": unresolved_locators(sections, entries, inventory),
        "failures": list(outcome.result.get("failures") or []), "problems": problems, "cost": dict(outcome.cost),
        "spot_check": {
            "status": "queued", "role": ask.role, "verdict_type": ask.verdict_type, "author_model": ask.author_model,
            "items": chosen, "flaws": flaws, "question": ask.question, "scope_limit": ask.scope_limit,
            "paths": ask.paths, "session_id": None, "model": None, "findings": [],
        },
    }
    dossier["updated"] = now_ts()
    ledger.write_json(_refs(slug, "dossier.json"), dossier, schema="dossier")
    ledger.write_markdown(_refs(slug, DOSSIER_MD), render_dossier_markdown(dossier, entries))
    ledger.append_event("absorbed", {
        "slug": slug, "level": LEVEL_2, "session_id": session_id, "chunks": len(manifest["chunks"]),
        "entries": len(entries), "coverage_pass": coverage["pass"],
    }, session_id=session_id)
    return {
        "slug": slug, "fanout": fanout, "allow_rules": outcome.allow_rules, "chunks": len(manifest["chunks"]),
        "entries": len(entries), "coverage": coverage, "sections": sections is not None,
        "failures": dossier["l2"]["failures"], "problems": problems,
        "unresolved_locators": dossier["l2"]["unresolved_locators"], "cost": dict(outcome.cost),
        "session_ids": list(outcome.session_ids), "run_file": outcome.run_file, "spot_check": ask,
        "consultations": consulted, "pass": coverage["pass"] and sections is not None,
    }


# --- a `dossier` ticket, run as a promotion (decision 17; ticket 98) ------------------------------

DONE, WAITS, DECLINED, FAILED = "done", "waits", "declined", "failed"
_REFS_PATH = re.compile(r"(?:^|/)refs/(?P<slug>[a-z0-9][a-z0-9._-]*)(?:/|$)")
_AFFIRMATIVE = re.compile(r"^\W*(?:yes|y|promote|approved?|go|ok|okay|read it)\b", re.IGNORECASE)


def ticket_slug(ticket, slugs):
    """The dossier a `dossier` ticket reads: the first `refs/<slug>/` its context pack or inputs name, else a slug its title names."""
    for path in list(ticket.get("context_pack") or []) + list(ticket.get("inputs") or []):
        found = _REFS_PATH.search(str(path))
        if found is not None and found.group("slug") in slugs:
            return found.group("slug")
    title = str(ticket.get("title") or "")
    named = [slug for slug in slugs if re.search(r"(?<![a-z0-9._-])%s(?![a-z0-9._-])" % re.escape(slug), title)]
    return max(named, key=len) if named else None


def promotion_answer(ticket, slug, tickets_by_id, answers):
    """The answer to the promotion decision a `dossier` ticket waits on (`True` yes, `False` no), or None while none is answered."""
    title = "Promote %s to level 2?" % slug
    for blocker in ticket.get("blocked_by") or []:
        fields = tickets_by_id.get(blocker) or {}
        answer = (answers or {}).get(blocker)
        if fields.get("title") == title and answer:
            return bool(_AFFIRMATIVE.match(str(answer)))
    return None


def run_dossier_ticket(project, ticket, *, tickets_by_id=None, answers=None, absorb=None, inventory=None, ledger=None):
    """Run one `dossier` ticket as a promotion through absorb, with no worker session: `{outcome, slug, reason, decision, report}`.

    The ticket is the planner's or the decider's call that a paper earns a full read, so it promotes on the
    `planner_or_decider` trigger inside the phase's level-2 budget. Beyond it, `dossier.promote` opens the
    decision ticket and the outcome is `waits` with its id; once that decision is answered, a yes promotes past
    the budget and a no closes the ticket (`declined`) with nothing read. A promoted paper is given its inventory
    when it has none (`inventory(project, slug)`, `dossier.build_inventory` by default) and read by
    `absorb(project, slug)` (`absorb_level_2`); `done` when the coverage audit passes, `failed` otherwise. The
    reader's L1 skim is not this: it stays the reader's.
    """
    from wayline import dossier as dossiers  # the dossier module imports this one's neighbours
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    slug = ticket_slug(ticket, set(dossiers.all_slugs(ledger)))
    if slug is None:
        return {"outcome": FAILED, "slug": None, "reason": "the ticket names no dossier: its context pack lists no research/refs/<slug>/ "
                "that exists, and its title names no slug", "decision": None, "report": None}
    record = read_dossier(ledger, slug)
    if record.get("existence") != "verified":
        return {"outcome": FAILED, "slug": slug, "reason": "refs/%s is unresolved, so there is no paper to read; hand it over with "
                "`wayline reference %s`" % (slug, slug), "decision": None, "report": None}
    if record.get("level", 0) < LEVEL_2:
        answered = promotion_answer(ticket, slug, tickets_by_id or {}, answers)
        if answered is False:
            return {"outcome": DECLINED, "slug": slug, "reason": "the promotion of %s beyond the phase's budget was answered no" % slug,
                    "decision": None, "report": None}
        promotion = dossiers.promote(ledger, slug, dossiers.PLANNER_OR_DECIDER, ticket=ticket["id"], force=bool(answered),
                                     detail="dossier ticket %d" % ticket["id"])
        if promotion.get("decision_ticket"):
            return {"outcome": WAITS, "slug": slug, "reason": "beyond the phase's level-2 budget", "decision": promotion["decision_ticket"],
                    "report": None}
    record = read_dossier(ledger, slug)
    if record.get("l2") and (record["l2"].get("coverage") or {}).get("pass"):
        return {"outcome": DONE, "slug": slug, "reason": "already read in full", "decision": None, "report": None}
    if not ledger.path(_refs(slug, INVENTORY)).is_file():
        try:
            (inventory or dossiers.build_inventory)(project, slug)
        except (ValueError, OSError) as failure:
            return {"outcome": FAILED, "slug": slug, "reason": "refs/%s has no inventory and none could be built: %s" % (slug, failure),
                    "decision": None, "report": None}
    try:
        report = (absorb or absorb_level_2)(project, slug)
    except (ValueError, OSError) as failure:
        return {"outcome": FAILED, "slug": slug, "reason": "the level-2 read of %s did not run: %s" % (slug, failure), "decision": None, "report": None}
    if not report.get("pass"):
        coverage = report.get("coverage") or {}
        missing = coverage.get("missing") or []
        return {"outcome": FAILED, "slug": slug, "reason": "the level-2 read of %s did not pass its coverage audit%s" % (
            slug, " (no entry for %s)" % ", ".join(str(item) for item in missing[:10]) if missing else ""), "decision": None, "report": report}
    return {"outcome": DONE, "slug": slug, "reason": None, "decision": None, "report": report}


def _record_consultations(ledger, slug, consultations, session_id, problems):
    """Record every answered reader question as `wayline consult` records one; returns how many were.

    The asker is the chunk's reader (`absorb:<chunk>`); the session is the consultant's own when it ran
    as one, and the absorb session's otherwise, which is where a workflow agent's transcript lives.
    An unanswered or unusable consultation is a problem of the read, never a failure of its coverage.
    """
    recorded = 0
    for item in consultations:
        if not isinstance(item, dict) or item.get("answer") is None:
            reason = item.get("reason") if isinstance(item, dict) else None
            problems.append("a reader's question went unanswered: %s" % (reason or "no reason given"))
            continue
        try:
            consult.record_exchange(ledger, slug, item["question"], item["answer"], "absorb:%s" % item["chunk"],
                                    item.get("session_id") or session_id)
        except (consult.ConsultError, DossierError, LedgerError, ValidationError) as failure:
            problems.append("the consultant's answer to the reader of %s was not recorded: %s" % (item["chunk"], failure))
            continue
        recorded += 1
    return recorded


def take_spot_check(project, slug, harness_root=None, ledger=None, policy=None, fall_back=None):
    """Take the queued depth spot-check of `slug` through the gate and record its outcome in `dossier.json`.

    While Fable's weekly window is spent, a critic whose table verifier is Fable runs on Opus at the table's
    effort under the fallback consent `auto`, and the record carries `fallback_from`; under `wait`, or under
    `ask` before an answer, the gate raises `gates.FableHeld` and the spot-check stays queued (decision 15).
    `fall_back` decides for the caller instead, as `gates.take_verdict` reads it.
    """
    project = Path(project).resolve()
    ledger = ledger_for(ledger if ledger is not None else project)
    dossier = read_dossier(ledger, slug)
    record = (dossier.get("l2") or {}).get("spot_check")
    if not record or record.get("status") != "queued":
        raise DossierError("%s has no queued depth spot-check" % slug)
    ask = gates.Ask(subject_kind="dossier", subject=_refs(slug), question=record["question"], paths=record["paths"],
                    scope_limit=record["scope_limit"], verdict_type=record["verdict_type"],
                    author_model=record["author_model"], role=record["role"])
    taken = gates.verdict_for(ask, project=project, harness_root=Path(harness_root or HARNESS_ROOT), policy=policy, ledger=ledger,
                              fall_back=fall_back)
    record.update({"status": "passed" if taken.passed else "failed", "session_id": taken.session_id,
                   "model": taken.model, "fallback_from": taken.fallback_from, "findings": list(taken.findings)})
    dossier["updated"] = now_ts()
    ledger.write_json(_refs(slug, "dossier.json"), dossier, schema="dossier")
    try:
        lines = (ledger.research / REFS / slug / ENTRIES).read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        entries = []
    ledger.write_markdown(_refs(slug, DOSSIER_MD), render_dossier_markdown(dossier, entries))
    return taken


# --- the verb -----------------------------------------------------------------------------------


def level_2_command(options):
    """`wayline absorb --level 2 <slug> [--fanout workflow|conductor] [--spot-check]`."""
    if len(options.slugs) != 1:
        print("wayline absorb --level 2: name exactly one slug; a level-2 read is one paper at a time", file=sys.stderr)
        return 2
    slug = options.slugs[0]
    waits = None
    try:
        project = find_project(options.project)
        report = absorb_level_2(project, slug, fanout=options.fanout)
        try:
            verdict = take_spot_check(project, slug) if options.spot_check else None
        except gates.FableHeld as held:
            # Not a verdict against the dossier: the spot-check stays queued for the reset, and the read stands (decision 15).
            verdict, waits = None, str(held)
    except (DossierError, ProjectError, ValidationError, gates.GateError, worker.LaunchError, worker.RoleError,
            LedgerError, OSError) as failure:
        print("wayline absorb --level 2: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        shown = dict(report, spot_check=dict(vars(report["spot_check"])))
        if verdict is not None:
            shown["spot_check_verdict"] = verdict.payload
        if waits:
            shown["spot_check_waits"] = waits
        print(json.dumps(shown, ensure_ascii=False, indent=2))
    else:
        print(_render(report, verdict, waits))
    return 0 if report["pass"] and (verdict is None or verdict.passed) else 1


def _render(report, verdict=None, waits=None):
    coverage = report["coverage"]
    lines = [
        "absorbed   %s at level 2 by the %s fan-out%s" % (report["slug"], report["fanout"],
                                                       ", allow rules %s" % report["allow_rules"] if report["allow_rules"] else ""),
        "chunks     %d, entries %d" % (report["chunks"], report["entries"]),
        "coverage   %s: %d of %d items%s" % ("pass" if coverage["pass"] else "FAIL", coverage["covered"], coverage["items"],
                                             "; missing %s" % ", ".join(coverage["missing"]) if coverage["missing"] else ""),
        "sections   %s" % ("written" if report["sections"] else "MISSING"),
        "cost       %s agent(s), %s token(s), %s ms" % (report["cost"]["agents"], report["cost"]["tokens"], report["cost"]["duration_ms"]),
    ]
    if report.get("consultations"):
        lines.append("consulted  %d reader question(s) answered, in qa_log.md" % report["consultations"])
    if verdict is None:
        lines.append("spot-check queued for the %s%s" % (report["spot_check"].role, ": %s" % waits if waits else ""))
    else:
        lines.append("spot-check %s (%s%s, %s)" % ("pass" if verdict.passed else "FAIL", verdict.model,
                                                   " in place of %s" % verdict.fallback_from if verdict.fallback_from else "",
                                                   verdict.session_id))
    for failure in report["failures"]:
        lines.append("  short      %s: %s" % (failure["chunk"] or "synthesizer", failure["reason"]))
    for problem in report["problems"]:
        lines.append("  problem    %s" % problem)
    for locator in report["unresolved_locators"]:
        lines.append("  locator    %s names nothing an entry was read at" % locator)
    return "\n".join(lines)
