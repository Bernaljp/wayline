"""Drawings and plots: each changed result explored in every useful plot at rest points (Implementation Decision 17; ticket 100).

**When a result is drawn.** Code creates one ticket of the kind `drawing` per result (`open_drawings`); the planner
never writes one (the plan schema's kinds leave it out). Results are drawn at rest points only (`RESTS`): at a run
end, before a checkpoint pause under `checkpoints` (a run coming to rest on a decision ticket the owner answers), and
on the owner's word ("draw R4 again", `draw_again`). At a run end or a checkpoint only the results changed since
their last drawing are drawn (`due`), and only those holding at least one finding from the project's own evidence
(`own_evidence`): a finding that cites a run's artifact. The stopping rule's results go first. What "changed" means is
read from the records: a result whose current findings, leaving out the findings a drawing itself filed, are the ones
its latest drawing was opened over is not drawn again, whether that drawing was accepted or failed, so a rest point
never draws one result twice; a mark on a plot changes no finding, so no mark starts a drawing.

**The plotter.** A drawing runs on the `plotter` role at `policy.roles.plotter` (`opus medium`) with the budget
`policy.drawings.budget` (`small`), stepping down to `policy.drawings.step_down` (`sonnet medium`) when pacing steps
Opus work down (`tier`). It is read-only on the research: its touch set is its own drawing directory
(`drawings/R<n>-<v>/`), it adds no job, and its ticket asks for no GPU. Its brief (`brief`), rendered by code at each
launch into the prompt, carries the result's findings and their `res` artifacts, the objectives, the project summary,
the sorted plot index with its data shapes, the house style, the previous drawing with the owner's marks and notes,
the earlier figures it must answer, and the limits.

**What a drawing writes** (`DRAFT`, `drawings/R<n>-<v>/drawing.json` in its worktree): one script that draws every
plot (PNG and SVG) and table (CSV) and computes every quoted number into `numbers.json`; per plot its chart type, the
plot index entries it follows, its data view, Purpose, Data, What it shows, and whether it is a headline; the
synthesis, the headline, what can and cannot be inferred, and the open questions.

**Acceptance** (`check`): the script is rerun in the clean room and its plots, tables, and `numbers.json` compared;
then every plot gets six of the figure checks (`min_font_pt`, `text_overlap`, `palette`, `generator_clean`,
`regenerates`, `provenance`) and the five readability checks of `wayline.plot_checks`, all read off its SVG, and every
number a plot's explanation, the synthesis, or the inferences quote must be one `numbers.json` holds. A check that
cannot run is listed as not run. A failing plot gets one repair resume (the conductor's acceptance resume) and is then
left out and listed; anything wrong with the drawing as a whole fails it, and a drawing that still fails leaves the
result with its last accepted drawing, listed in the account, with no tier up, split, or ask.

**Plots** (`research/plots.json`, written only here through the ledger): a plot keeps its id across drawings (`R4.3`,
tables `R4.T1`), redrawn while useful, retired when a drawing leaves it out, never reused. The owner's marks are
items of a `plots` batch (`wayline.batches`), one batch per accepted drawing: drop retires the plot at the result's
next drawing, a note is an instruction the next drawing's brief carries, and keep means a drawing never retires it
alone. One record per drawing, `research/drawings/R<n>-<v>.json`, holds what it drew and what it left out, and each
drawing opened, accepted, or failed is journaled as `drawing`.
"""

import hashlib
import json
import re
from collections import namedtuple
from pathlib import Path
from dataclasses import dataclass

from wayline import results as results_module
from wayline import sections, tickets
from wayline.ledger import DRAWING, TICKET_CREATED, ledger_for, now_ts

__all__ = [
    "KIND", "ROLE", "RUN_END", "CHECKPOINT", "OWNER", "RESTS", "PLOTS_JSON", "DRAWINGS_DIR", "DRAFT", "DRAWING_CHECK", "TOOLS_PYTHON",
    "DrawingError", "PlotterTier", "Limits", "Checked", "own_evidence", "signature", "read_records", "due", "tier", "limits",
    "plot_marks", "read_plots", "last_accepted", "drawing_of", "result_heading", "brief", "earlier_figures", "check", "accept",
    "fail", "record_path", "directory", "draw_again", "open_drawings", "follow_merge", "accepted_records", "under_way", "plot_order", "drawing_name",
]

RECORD_SCHEMA = "drawing"
PLOTS_SCHEMA = "plots"

KIND = "drawing"
ROLE = "plotter"
RUN_END, CHECKPOINT, OWNER = "run_end", "checkpoint", "owner"
RESTS = (RUN_END, CHECKPOINT, OWNER)
PLOTS_JSON = "plots.json"
DRAWINGS_DIR = "drawings"  # research/drawings/R<n>-<v>.json, and the drawing ticket's own directory in its worktree
DRAFT = "drawing.json"

OPEN, ACCEPTED, FAILED = "open", "accepted", "failed"
_RECORD = re.compile(r"^(R[1-9][0-9]*)-([1-9][0-9]*)\.json$")
_RES_TAG = re.compile(r"\{res:[^{}]+\}")


def cited(finding):
    """The artifacts a finding's provenance cites: a ticket's finding carries one `<path>#<locator>` string, an older
    line a list."""
    given = finding.get("provenance")
    given = [given] if isinstance(given, str) else list(given or [])
    return [str(item).strip() for item in given if str(item).strip()]


def own_evidence(finding, manifested):
    """Whether a finding stands on the project's own evidence: it cites a run's artifact, by provenance or a `res` tag.

    `manifested` is the paths `research/manifest.json` holds: a provenance citing anything else (a dossier, a document)
    is no run's artifact. A `res` tag names a run's artifact by its form, which the linter resolved at acceptance.
    """
    if any(item.partition("#")[0] in manifested for item in cited(finding)):
        return True
    return bool(_RES_TAG.search(str(finding.get("text") or "")))


def _manifested(project):
    from wayline.provenance import manifest_paths, read_manifest
    return set(manifest_paths(read_manifest(project)))


def _drawing_tickets(project):
    return {fields["id"]: fields for fields in tickets.read_tickets(project) if fields["kind"] == KIND}


def _drawn_from(result, drawn_by):
    """The current findings a drawing is opened over: every one but those a drawing ticket filed."""
    return [finding for finding in result.current if finding.get("ticket") not in drawn_by]


def signature(finding_ids):
    """What a drawing records of the findings it was opened over: their ids, sorted, hashed."""
    return hashlib.sha256("\n".join(sorted(finding_ids)).encode("utf-8")).hexdigest()[:16]


def read_records(project_or_ledger, result=None):
    """Every drawing record under `research/drawings/`, in result and version order; only `result`'s when given."""
    book = ledger_for(project_or_ledger)
    folder = book.research / DRAWINGS_DIR
    found = []
    for path in sorted(folder.glob("R*-*.json")) if folder.is_dir() else ():
        name = _RECORD.match(path.name)
        if name is None or (result is not None and name.group(1) != result):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            found.append(record)
    return sorted(found, key=lambda record: (_number(record.get("result")), int(record.get("version") or 0)))


def _number(result_id):
    found = re.match(r"^R([1-9][0-9]*)$", str(result_id or ""))
    return int(found.group(1)) if found else 0


def _awaiting_resume(events):
    """The tickets whose last `ticket_failed` sent them to their resume, which the conductor still owes them."""
    waiting = set()
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == "ticket_failed":
            (waiting.add if payload.get("next") == "resume" else waiting.discard)(payload.get("ticket"))
        elif event.get("event") in ("ticket_resumed", "ticket_launched", "ticket_done", "ticket_cancelled"):
            waiting.discard(payload.get("ticket"))
    return waiting


def _in_progress(record, by_id, resuming=()):
    """Whether a drawing opened over a result still owes its outcome: its ticket is not closed one way or the other,
    or it failed and waits on its one resume."""
    if record.get("status") != OPEN:
        return False
    fields = by_id.get(record.get("ticket"))
    if fields is None:
        return False
    return fields["status"] in ("open", "running", "blocked", "needs_human") or (fields["status"] == "failed" and fields["id"] in resuming)


def _run_started(events):
    """When the latest run started, or None when no run ever did."""
    started = [event.get("ts") for event in events if event.get("event") == "run_started"]
    return started[-1] if started else None


def _rule_objectives(project):
    """The objectives the stopping rule closes the run on: what makes a result one of the rule's, drawn first."""
    from wayline import stopping
    from wayline.objectives import read_objectives
    from wayline.project import ProjectError, read_harness
    try:
        rule = stopping.rule_of(read_harness(project))
        records = read_objectives(project)
    except (ProjectError, ValueError, OSError):
        return set()
    if rule == stopping.FRONTIER:
        return set()
    return {record.get("id") for record in stopping.covered(rule, records)}


def due(project):
    """The results a rest point draws, the stopping rule's first, then in id order (the module's docstring).

    A result is due when its current findings (those of no drawing) differ from the ones its last accepted drawing was
    drawn over. A drawing of it under way holds it; so does one that failed, or was cancelled, over the same findings
    in this run, so a rest point never draws one result twice; at the next run's rest point it is drawn again.
    """
    book = ledger_for(project)
    by_id = _drawing_tickets(book.project)
    drawn_by = set(by_id)
    events, _ = book.read_events()
    resuming, started = _awaiting_resume(events), _run_started(events)
    records = {}
    for record in read_records(book):
        records.setdefault(record.get("result"), []).append(record)
    manifested = _manifested(book.project)
    rule = _rule_objectives(book.project)
    chosen = []
    for result in results_module.read_results(book):
        own = [finding for finding in _drawn_from(result, drawn_by) if own_evidence(finding, manifested)]
        if not own:
            continue
        held = records.get(result.id) or []
        if held and _in_progress(held[-1], by_id, resuming):
            continue
        now = signature(finding["id"] for finding in _drawn_from(result, drawn_by))
        accepted = [record for record in held if record.get("status") == ACCEPTED]
        if accepted and accepted[-1].get("signature") == now:
            continue
        if any(record.get("status") != ACCEPTED and record.get("signature") == now
               and (started is None or str(record.get("opened") or "") >= started) for record in held):
            continue  # tried over these findings in this run, and not accepted
        chosen.append(result)
    first = [result.id for result in chosen if set(result.objectives) & rule]
    return first + [result.id for result in chosen if result.id not in first]


# --- the plotter's tier and the drawing's limits -------------------------------------------------------------------

# The shipped values (decision 14's policy table), for a policy that names none.
DEFAULT_ROLE = {"model": "opus", "effort": "medium"}
DEFAULT_DRAWINGS = {"budget": "small", "step_down": {"model": "sonnet", "effort": "medium"}, "max_plots": 20, "max_tables": 4,
                    "max_headline": 4}


@dataclass(frozen=True)
class PlotterTier:
    """What a drawing launches at: `policy.roles.plotter` under `policy.drawings.budget`, or its step down."""

    model: str
    effort: str
    max_turns: int
    max_minutes: int
    stepped_from: str = None  # `opus medium` when pacing stepped the launch down

    @property
    def label(self):
        return "%s %s" % (self.model, self.effort)


Limits = namedtuple("Limits", "plots tables headline")


def _drawings_policy(policy):
    return dict(DEFAULT_DRAWINGS, **((policy or {}).get("drawings") or {}))


def tier(policy, cheap=False, model=None, effort=None):
    """The plotter's tier: `opus medium` on the small budget, `sonnet medium` while pacing steps Opus work down (`cheap`).

    `model` and `effort` name the tier a session already under way was launched on, which a resume keeps.
    """
    role = dict(DEFAULT_ROLE, **(((policy or {}).get("roles") or {}).get(ROLE) or {}))
    settings = _drawings_policy(policy)
    budget = ((policy or {}).get("budget") or {}).get(settings["budget"]) or {"max_turns": 40, "max_minutes": 30}
    if model is not None:
        return PlotterTier(model, effort or role["effort"], budget["max_turns"], budget["max_minutes"])
    if cheap:
        down = settings["step_down"]
        return PlotterTier(down["model"], down["effort"], budget["max_turns"], budget["max_minutes"],
                           stepped_from="%s %s" % (role["model"], role["effort"]))
    return PlotterTier(role["model"], role["effort"], budget["max_turns"], budget["max_minutes"])


def limits(policy):
    """A drawing's limits from `policy.drawings`: the most plots, tables, and headline plots, with no minimum."""
    settings = _drawings_policy(policy)
    return Limits(settings["max_plots"], settings["max_tables"], settings["max_headline"])


# --- plots and the owner's marks -----------------------------------------------------------------------------------

PLOTS_BATCH = "plots"
KEEP, MAYBE, DROP = "keep", "maybe", "drop"
CURRENT, RETIRED = "current", "retired"


def plot_marks(project_or_ledger):
    """The owner's mark and note on each plot, `{plot id: {"mark", "note"}}`, from every `plots` batch in id order.

    The first answer settles an item (`wayline.batches`), and a plot's later drawing puts it in a later batch, so the
    latest settled mark across batches is the plot's; a note alone stays until a later one replaces it.
    """
    from wayline import batches  # batches imports the project module, which imports much
    found = {}
    try:
        held = batches.read_batches(project_or_ledger)
    except (batches.BatchError, ValueError, OSError):
        return found
    for batch in held:
        if batch["kind"] != PLOTS_BATCH:
            continue
        for item in batch["items"]:
            entry = found.setdefault(item["ref"], {"mark": None, "note": None})
            if item.get("mark"):
                entry["mark"] = item["mark"]
            if item.get("note"):
                entry["note"] = item["note"]
    return found


def read_plots(project_or_ledger):
    """`research/plots.json` with the owner's marks and notes read from the batches now; an empty record before any drawing."""
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(PLOTS_JSON)
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict) or not isinstance(record.get("plots"), list):
        record = {"schema_version": 1, "plots": []}
    marks = plot_marks(book)
    for plot in record["plots"]:
        given = marks.get(plot.get("id")) or {}
        plot["mark"] = given.get("mark", plot.get("mark"))
        plot["note"] = given.get("note", plot.get("note"))
    return record


def last_accepted(project_or_ledger, result_id):
    """The result's last accepted drawing record, or None before its first."""
    accepted = [record for record in read_records(project_or_ledger, result_id) if record.get("status") == ACCEPTED]
    return accepted[-1] if accepted else None


# --- the brief -----------------------------------------------------------------------------------------------------


def _parse_origin(origin):
    found = re.match(r"^drawing (R[1-9][0-9]*)-([1-9][0-9]*) at (\w+)$", str(origin or ""))
    return (found.group(1), int(found.group(2)), found.group(3)) if found else (None, None, None)


def drawing_of(ticket):
    """`(result, version, rest)` a drawing ticket's origin names; `(None, None, None)` for any other ticket."""
    if (ticket or {}).get("kind") != KIND:
        return None, None, None
    return _parse_origin(ticket.get("origin"))


def result_heading(project, ticket):
    """The current heading of the result a drawing ticket draws, which its findings stand under; None when it is gone."""
    result_id, _, _ = drawing_of(ticket)
    if result_id is None:
        return None
    clusters = results_module.load(project)
    live = clusters.resolve(result_id)
    return (clusters.results.get(live) or {}).get("heading")


def _summary(book):
    try:
        spec = book.read_json("spec.json")
    except (OSError, ValueError):
        return "No spec yet."
    summary = _one_line((spec or {}).get("summary"))
    if summary:
        return summary
    parts = [_one_line(spec.get("question"))] + [_one_line(item.get("text")) for item in spec.get("data") or [] if isinstance(item, dict)]
    return " ".join(part for part in parts if part) or "The spec has no summary, question, or data."


def _index_lines(project):
    """The plot index sorted by data shape, then canonical chart type: one line per chart type, its entries after it."""
    from wayline.figures import DATA_SHAPES, FIGURES, PLOT_INDEX_JSON, load_index
    try:
        entries = load_index(project / FIGURES / PLOT_INDEX_JSON).get("entries") or []
    except ValueError:
        entries = []
    kinds = {}
    for entry in entries:
        shape, chart = entry.get("data_shape"), _one_line(entry.get("canonical_chart_type"))
        if shape in (None, "none") or not chart:
            continue
        libraries = {implementation.get("library") for implementation in entry.get("library_implementations") or [] if implementation.get("library")}
        held = kinds.setdefault((shape, chart), {"ids": [], "libraries": set()})
        held["ids"].append(str(entry.get("id")))
        held["libraries"] |= libraries
    if not kinds:
        return ["- The plot index holds no entry with a data shape yet (`wayline figures build-index` fills it); "
                "choose canonical chart types by the data shapes below yourself."]
    order = {shape: index for index, shape in enumerate(DATA_SHAPES)}
    lines = []
    for (shape, chart), held in sorted(kinds.items(), key=lambda item: (order.get(item[0][0], len(order)), item[0][1])):
        lines.append("- %s: %s (%s; entries %s)" % (shape, chart, ", ".join(sorted(held["libraries"])) or "any library",
                                                      ", ".join(sorted(held["ids"]))))
    return lines


def _objective_lines(project, wanted):
    from wayline.objectives import read_objectives
    try:
        records = {record.get("id"): record for record in read_objectives(project)}
    except (ValueError, OSError):
        records = {}
    return ["- %s (%s): %s" % (name, (records.get(name) or {}).get("status", "unknown"), _one_line((records.get(name) or {}).get("text")))
            for name in wanted] or ["- None: no objective names this result's findings."]


def brief(project, ticket, policy=None):
    """The drawing's brief as its prompt carries it, rendered by code at each launch (the module's docstring)."""
    book = ledger_for(project)
    result_id, version, rest = drawing_of(ticket)
    if result_id is None:
        raise DrawingError("ticket %s is no drawing ticket code opened" % (ticket or {}).get("id"))
    found = {result.id: result for result in results_module.read_results(book)}
    result = found.get(result_id)
    bound = limits(policy)
    folder = directory(result_id, version)
    lines = ["# The drawing", "",
             "Drawing %s: %s, \"%s\", opened at %s. Your drawing directory, your whole touch set, is `%s`; your draft is "
             "`%s%s`." % (_name(result_id, version), result_id, result.heading if result else "a result no longer live", rest,
                          folder, folder, DRAFT),
             "", "Limits: at most %d plots, %d tables, and %d headline plots, with no minimum." % (bound.plots, bound.tables, bound.headline),
             *_asked_lines(book, result_id, version),
             "", "## What the project is", "", _summary(book)]
    drawn_by = set(_drawing_tickets(book.project))
    lines += ["", "## The result's findings", ""]
    for finding in (result.current if result else []):
        own = " (a drawing's own inference)" if finding.get("ticket") in drawn_by else ""
        lines.append("- %s%s%s: %s" % (finding["id"], " [negative]" if finding.get("negative") else "", own, _one_line(finding.get("text"))))
        for item in cited(finding):
            lines.append("    - artifact: `%s`" % item)
    lines += ["", "## Objectives", ""] + _objective_lines(book.project, result.objectives if result else [])
    lines += ["", "## The plot index, by data shape", ""] + _index_lines(book.project)
    lines += ["", "## The house style", "",
              "`figures/style.json` in the project: its colors, ramps, and smallest text size are what the palette and "
              "font checks hold every plot to."]
    asked = bool(_asked_lines(book, result_id, version))
    lines += ["", "## The previous drawing and the owner's marks", ""] + _previous_lines(book, result_id, asked)
    figures = earlier_figures(book, result) if result else []
    if figures:
        lines += ["", "## Earlier figures to answer", "",
                  "This result's findings replace claims an earlier document illustrated. Draw the same view where the data "
                  "allows, and say in `earlier_figures` whether your plot agrees with it.", ""]
        for figure in figures:
            lines.append("- %s (document %s, whose files are under `research/documents/%s/`): %s"
                         % (figure["figure"], figure["document"], figure["document"], figure["caption"]))
    return "\n".join(lines) + "\n"


def _asked_lines(book, result_id, version):
    """The owner's request, when the drawing is a plot the owner asked for (ticket 101)."""
    try:
        record = book.read_json(record_path(_name(result_id, version)))
    except (OSError, ValueError):
        return []
    if not isinstance(record, dict) or not record.get("asked"):
        return []
    return ["", "## The plot the owner asked for", "", record["asked"], "",
            "This is a small drawing: draw what the owner asked for and nothing else. Every other current plot of the "
            "result is carried into the new version unchanged, whether you name it or not."]


def follow_merge(project_or_ledger, source, into):
    """A result merged into another takes its plots with it: each plot of `source` is re-pointed to `into` and keeps its
    id, so its `plot` tags still resolve and `into`'s next drawing keeps or retires it (ticket 101). Under the ledger's
    lock, from `wayline.results.merge`; returns the ids re-pointed."""
    book = ledger_for(project_or_ledger)
    try:
        record = book.read_json(PLOTS_JSON)
    except (OSError, ValueError):
        return []
    if not isinstance(record, dict) or not isinstance(record.get("plots"), list):
        return []
    moved = []
    for plot in record["plots"]:
        if plot.get("result") == source:
            plot["result"] = into
            moved.append(plot["id"])
    if moved:
        book.write_json(PLOTS_JSON, record, schema=PLOTS_SCHEMA)
    return moved


def _previous_lines(book, result_id, asked=False):
    record = last_accepted(book, result_id)
    if record is None:
        return ["None: this is the result's first accepted drawing."] + _merged_lines({plot["id"]: plot for plot in read_plots(book)["plots"]}, result_id, None)
    plots = {plot["id"]: plot for plot in read_plots(book)["plots"]}
    lines = ["Drawing %s (`%s`). Redraw a plot by naming its id in `redraws`; %s, and a plot the owner marked drop is "
             "retired and never drawn again." % (
                 "a plot you leave out is carried unchanged, since this drawing is a plot the owner asked for" if asked else
                 "a plot you leave out is retired, unless the owner marked it keep",
                 _name(record["result"], record["version"]), directory(record["result"], record["version"]))]
    for entry in record.get("plots", []) + record.get("tables", []):
        held = plots.get(entry["id"]) or {}
        mark = held.get("mark") or "no mark"
        note = " Note: %s" % held["note"] if held.get("note") else ""
        lines.append("- %s (%s; %s%s): Purpose: %s What it shows: %s Mark: %s.%s" % (
            entry["id"], entry.get("chart_type") or "table", entry.get("data_view"), ", headline" if entry.get("headline") else "",
            _one_line(entry.get("purpose")), _one_line(entry.get("shows")), mark, note))
    for identifier in record.get("carried") or []:
        held = plots.get(identifier) or {}
        lines.append("- %s (carried, marked %s)%s" % (identifier, held.get("mark") or "keep",
                                                     " Note: %s" % held["note"] if held.get("note") else ""))
    return lines + _merged_lines(plots, result_id, record, asked)


def _merged_lines(plots, result_id, record, asked=False):
    """The current plots a result merged into this one brought with it, which this drawing keeps or retires."""
    listed = set(record.get("carried") or []) if record else set()
    if record:
        listed |= {entry["id"] for entry in record.get("plots", []) + record.get("tables", [])}
    lines = []
    for identifier, held in sorted(plots.items()):
        if held.get("result") == result_id and held.get("status") == CURRENT and identifier not in listed:
            lines.append("- %s (%s; %s, from a result merged into this one, marked %s): redraw it by its id in `redraws`, or "
                         "leave it out to %s." % (identifier, held.get("chart_type") or "table", held.get("data_view"),
                                                  held.get("mark") or "no mark", "carry it unchanged" if asked else "retire it"))
    return lines


# --- earlier figures -----------------------------------------------------------------------------------------------

_FIGURE_LABEL = re.compile(r"\b(?:Supplementary\s+)?(?:Figure|Fig\.?)\s*(S?\d+)", re.IGNORECASE)


def earlier_figures(project_or_ledger, result):
    """The earlier figures of the project's documents this result's findings answer: `[{figure, document, caption}]`.

    A finding that replaces an inherited claim (a passage `by` a document) answers the figures that claim names
    ("Figure 2", "Fig. 2"), found among the captions the document keeps (`deconstructed.kept`, part `caption`).
    """
    from wayline.documents import read_documents, text_blocks
    book = ledger_for(project_or_ledger)
    passages = {item.get("id"): item for item in sections.read_passages(book)}
    wanted = []
    for finding in result.current:
        target = passages.get(finding.get("replaces"))
        if target is None or not sections.is_inherited(target):
            continue
        document = str(target.get("by"))[len(sections.DOCUMENT_BY):]
        for label in _FIGURE_LABEL.findall(str(target.get("text") or "")):
            if (document, label.upper()) not in wanted:
                wanted.append((document, label.upper()))
    if not wanted:
        return []
    try:
        documents = {str(item.get("id")): item for item in read_documents(book.project)}
    except (OSError, ValueError):
        return []
    figures = []
    for document_id, label in wanted:
        document = documents.get(document_id)
        if document is None:
            continue
        kept = {item.get("locator") for item in (document.get("deconstructed") or {}).get("kept") or [] if item.get("part") == "caption"}
        try:
            text = (book.research / "documents" / document_id / "text.md").read_text(encoding="utf-8")
        except OSError:
            continue
        for locator, block in text_blocks(text):
            found = _FIGURE_LABEL.match(block.strip().lstrip("*_"))
            if locator in kept and found and found.group(1).upper() == label:
                figures.append({"figure": "%s#%s" % (document_id, locator), "document": document_id, "caption": _one_line(block)})
    return figures


# --- acceptance ----------------------------------------------------------------------------------------------------

DRAWING_CHECK = "wayline drawing check"  # the acceptance result's `cmd`
_DEFAULT = TOOLS_PYTHON = object()  # the clean room runs in the tools venv's Python unless a caller names another
_TEXT_FIELDS = ("purpose", "data", "shows")
_LABELS = {"purpose": "Purpose", "data": "Data", "shows": "What it shows"}


@dataclass
class Checked:
    """What a drawing's acceptance found: its own problems, each plot's and table's checks, and what it left out.

    `items` is one entry per plot and table of the draft, in its order: `{what, kind, entry, checks, failed}`, `what`
    the id it redraws or its file named new, `failed` the reasons it fails. With `final` (the repair resume is spent),
    an item that fails is left out and listed rather than failing the drawing; a problem of the drawing as a whole
    always fails it.
    """

    final: bool
    problems: list
    items: list
    left_out: list
    draft: dict = None

    @property
    def passed(self):
        return not self.problems and (self.final or not any(item["failed"] for item in self.items))

    def kept(self):
        """The items that stand: every item with no failure."""
        return [item for item in self.items if not item["failed"]]

    def tail(self):
        lines = ["the drawing: %s" % problem for problem in self.problems]
        for item in self.items:
            if item["failed"]:
                verb = "left out" if self.final else "fails"
                lines.append("%s %s: %s" % (item["what"], verb, "; ".join(item["failed"])))
        not_run = sorted({"%s (%s)" % (outcome["id"], outcome["detail"]) for item in self.items for outcome in item["checks"]
                          if outcome.get("not_run")})
        lines += ["not run: %s" % entry for entry in not_run]
        if not lines:
            return "the script reran alike in the clean room, and every plot and table passed its checks"
        return "\n".join(lines)

    def acceptance_result(self):
        return {"cmd": DRAWING_CHECK, "exit_code": 0 if self.passed else 1, "seconds": 0.0, "tail": self.tail()}

    def to_json(self):
        return {"final": self.final, "problems": self.problems, "items": self.items, "left_out": self.left_out, "draft": self.draft}

    @classmethod
    def from_json(cls, value):
        return cls(bool(value.get("final")), list(value.get("problems") or []), list(value.get("items") or []),
                   list(value.get("left_out") or []), value.get("draft"))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _style(project):
    try:
        return json.loads((project / "figures" / "style.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _manifest(project):
    from wayline.provenance import read_manifest
    found = {}
    for entry in read_manifest(project).get("entries", []):
        if entry.get("path"):
            found[entry["path"]] = entry
    return found


def _draft_items(draft):
    plots = [entry for entry in draft.get("plots") or [] if isinstance(entry, dict)]
    tables = [entry for entry in draft.get("tables") or [] if isinstance(entry, dict)]
    return [("plot", entry) for entry in plots] + [("table", entry) for entry in tables]


def _what(kind, entry):
    if entry.get("redraws"):
        return str(entry["redraws"])
    return "%s (new)" % (entry.get("png") if kind == "plot" else entry.get("csv"))


def _in_folder(folder, name):
    """`name` as a file of the drawing directory `folder`, or None when it is blank or reaches outside it."""
    if not _text(name):
        return None
    relative = Path(str(name))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return folder / relative


def _draft_problems(book, result_id, draft, folder, bound, expected_figures):
    """What is wrong with the drawing as a whole, before any plot is looked at."""
    problems = []
    for name, what in (("script", "its script"), ("numbers", "its numbers.json")):
        path = _in_folder(folder, draft.get(name))
        if path is None:
            problems.append("%s %r is outside its drawing directory or not named" % (what, draft.get(name)))
        elif not path.is_file():
            problems.append("%s %r is not a file in its drawing directory" % (what, draft.get(name)))
    for name in ("synthesis", "headline"):
        if not _text(draft.get(name)):
            problems.append("it has no %s" % name)
    plots = [entry for kind, entry in _draft_items(draft) if kind == "plot"]
    tables = [entry for kind, entry in _draft_items(draft) if kind == "table"]
    if len(plots) > bound.plots:
        problems.append("it draws %d plots, and a drawing draws at most %d" % (len(plots), bound.plots))
    if len(tables) > bound.tables:
        problems.append("it writes %d tables, and a drawing writes at most %d" % (len(tables), bound.tables))
    headlines = sum(1 for entry in plots if entry.get("headline") is True)
    if headlines > bound.headline:
        problems.append("it marks %d headline plots, and a drawing marks at most %d" % (headlines, bound.headline))
    record = read_plots(book)
    ours = {plot["id"]: plot for plot in record["plots"] if plot.get("result") == result_id}
    seen = set()
    for kind, entry in _draft_items(draft):
        redraws = entry.get("redraws")
        if not redraws:
            continue
        held = ours.get(redraws)
        if redraws in seen:
            problems.append("it redraws %s twice" % redraws)
        elif held is None:
            problems.append("it redraws %s, which is no plot of %s" % (redraws, result_id))
        elif (held["kind"] == "table") != (kind == "table"):
            problems.append("it redraws %s as a %s, and %s is a %s" % (redraws, kind, redraws, held["kind"]))
        elif held["status"] == RETIRED:
            problems.append("it redraws %s, which was retired and is never drawn again" % redraws)
        elif held.get("mark") == DROP:
            problems.append("it redraws %s, which the owner dropped" % redraws)
        seen.add(redraws)
    answered = {str(item.get("figure")) for item in draft.get("earlier_figures") or [] if isinstance(item, dict)
                and item.get("agrees") in ("agrees", "disagrees", "cannot tell") and _text(item.get("note"))}
    for figure in expected_figures:
        if figure["figure"] not in answered:
            problems.append("it does not say whether it agrees with the earlier figure %s" % figure["figure"])
    return problems


def check(project, ticket, worktree, final=False, policy=None, python=_DEFAULT):
    """A drawing's acceptance in its worktree (the module's docstring): a `Checked`.

    `final` says the repair resume is spent, so a plot that fails is left out. `python` is the clean room's
    interpreter, the tools venv's by default.
    """
    from wayline import drawing_checks
    from wayline.numbers import spec_parameters
    book = ledger_for(project)
    project = book.project
    result_id, version, _ = drawing_of(ticket)
    if result_id is None:
        raise DrawingError("ticket %s is no drawing ticket code opened" % (ticket or {}).get("id"))
    folder_name = directory(result_id, version).rstrip("/")
    folder = Path(worktree) / folder_name
    try:
        draft = json.loads((folder / DRAFT).read_text(encoding="utf-8"))
    except OSError:
        return Checked(final, ["it wrote no %s in %s" % (DRAFT, folder_name)], [], [])
    except ValueError as failure:
        return Checked(final, ["its %s is not JSON: %s" % (DRAFT, failure)], [], [])
    if not isinstance(draft, dict):
        return Checked(final, ["its %s is not an object" % DRAFT], [], [])
    bound = limits(policy)
    found = {result.id: result for result in results_module.read_results(book)}
    expected = earlier_figures(book, found[result_id]) if result_id in found else []
    problems = _draft_problems(book, result_id, draft, folder, bound, expected)
    manifest = _manifest(project)
    inputs = [str(item) for item in draft.get("inputs") or [] if _text(item)]
    unmanifested = [item for item in inputs if item not in manifest]
    if not inputs:
        problems.append("it names no input: nothing traces it to a run")
    if unmanifested:
        problems.append("it reads %s, which research/manifest.json does not hold" % ", ".join(unmanifested))
    exempt = spec_parameters(project)
    numbers_name = str(draft.get("numbers") or "")
    numbers_path = _in_folder(folder, numbers_name)
    shipped, unread = drawing_checks.read_numbers(numbers_path) if numbers_path is not None else (None, "its numbers.json is not named")
    values = drawing_checks.values_of(shipped) if shipped is not None else []
    problems += drawing_checks.numbers_problems(
        [("the synthesis", draft.get("synthesis")), ("the headline", draft.get("headline"))]
        + [("what can be inferred", text) for text in draft.get("can_infer") or []]
        + [("what cannot be inferred", text) for text in draft.get("cannot_infer") or []]
        + [("an open question", text) for text in draft.get("open_questions") or []], values, exempt)
    script = str(draft.get("script") or "")
    python = drawing_checks.interpreter() if python is _DEFAULT else python
    script_path = _in_folder(folder, script)
    room = drawing_checks.rerun(project, folder, folder_name, script, [item for item in inputs if item in manifest],
                                python, policy_timeout(policy)) if script_path is not None and script_path.is_file() else \
        drawing_checks.Room(None, "there is no script in its drawing directory to rerun", ran=False)
    try:
        if room.failed:
            problems.append("its script did not rerun in the clean room: %s" % (room.error or "exit %s" % room.returncode))
        elif room.ran and shipped is not None:
            again, why = drawing_checks.read_numbers(room.root / folder_name / numbers_name)
            if again is None:
                problems.append("the rerun wrote no numbers.json it could read: %s" % why)
            elif again != shipped:
                problems.append("the rerun's numbers.json differs from the drawing's: the script does not compute its numbers alike")
        elif shipped is None:
            problems.append(unread)
        script_outcome = drawing_checks.generator_clean(script_path, room) if script_path is not None and script_path.is_file() else \
            drawing_checks.not_run("generator_clean", "there is no script in its drawing directory")
        ssim_min = float(((policy or {}).get("figures") or {}).get("ssim_min", 0.99))
        style = _style(project)
        items = []
        for kind, entry in _draft_items(draft):
            items.append(_check_item(project, folder, folder_name, kind, entry, room, script_outcome, ssim_min, style, policy,
                                     manifest, inputs, values, exempt))
    finally:
        room.close()
    if final and items and not any(not item["failed"] for item in items):
        problems.append("no plot or table passed its checks after the repair: the result keeps its last accepted drawing")
    left_out = [{"what": item["what"], "reason": "; ".join(item["failed"])} for item in items if item["failed"]] if final else []
    return Checked(final, problems, items, left_out, draft)


def policy_timeout(policy):
    return int((policy or {}).get("acceptance_timeout_s") or 600)


def _check_item(project, folder, folder_name, kind, entry, room, script_outcome, ssim_min, style, policy, manifest, inputs, values, exempt):
    from wayline import drawing_checks
    what = _what(kind, entry)
    failed = []
    for field in ("data_view",) + _TEXT_FIELDS + (("chart_type",) if kind == "plot" else ()):
        if not _text(entry.get(field)):
            failed.append("no %s" % _LABELS.get(field, field.replace("_", " ")))
    reads = [str(item) for item in entry.get("inputs") or inputs if _text(item)]
    provenance = drawing_checks.check_provenance(project, reads, manifest)
    number_problems = drawing_checks.numbers_problems([(_LABELS[field], entry.get(field)) for field in _TEXT_FIELDS], values, exempt)
    files = (("png", "svg") if kind == "plot" else ("csv",))
    outside = [entry.get(name) for name in files if _in_folder(folder, entry.get(name)) is None]
    missing = [entry.get(name) for name in files if entry.get(name) not in outside and not (folder / str(entry.get(name))).is_file()]
    if outside or missing:
        if outside:
            failed.append("its %s %s outside its drawing directory or not named" % (" and ".join(map(str, outside)), "is" if len(outside) == 1 else "are"))
        if missing:
            failed.append("its %s %s not in its drawing directory" % (" and ".join(map(str, missing)), "is" if len(missing) == 1 else "are"))
        checks = []
    else:
        main = str(entry["png"] if kind == "plot" else entry["csv"])
        if not room.ran:
            regenerates = drawing_checks.not_run("regenerates", room.error)
        elif room.failed:
            regenerates = drawing_checks.outcome("regenerates", False, "the script did not rerun: %s" % room.error)
        elif kind == "plot":
            same, detail = drawing_checks.same_png(folder / main, room.root / folder_name / main, ssim_min)
            regenerates = drawing_checks.outcome("regenerates", same, detail)
        else:
            again = room.root / folder_name / main
            same = again.is_file() and again.read_bytes() == (folder / main).read_bytes()
            regenerates = drawing_checks.outcome("regenerates", same, "the rerun wrote the same CSV" if same else "the rerun's CSV differs")
        if kind == "plot":
            checks = drawing_checks.plot_checks_for(folder / str(entry["svg"]), style, policy, script_outcome, regenerates, provenance, number_problems)
        else:
            checks = [regenerates, provenance, drawing_checks.outcome(drawing_checks.NUMBERS, not number_problems,
                                                                     "; ".join(number_problems) or "every number it quotes is a value in numbers.json")]
    failed += ["%s: %s" % (outcome["id"], outcome["detail"]) for outcome in checks if outcome.get("pass") is False]
    return {"what": what, "kind": kind, "entry": entry, "checks": checks, "failed": failed}


# --- recording the outcome -----------------------------------------------------------------------------------------

_PLOT_ID = re.compile(r"^(R[1-9][0-9]*)\.(T?)([1-9][0-9]*)$")


def _next_number(plots, result_id, table):
    """The next unused plot (or table) number of a result: one past every id it ever held, retired ones too."""
    used = [int(found.group(3)) for found in (_PLOT_ID.match(str(plot.get("id"))) for plot in plots)
            if found and found.group(1) == result_id and bool(found.group(2)) == table]
    return max(used or [0]) + 1


def _record_of(book, ticket):
    result_id, version, _ = drawing_of(ticket)
    if result_id is None:
        raise DrawingError("ticket %s is no drawing ticket code opened" % (ticket or {}).get("id"))
    name = _name(result_id, version)
    try:
        record = book.read_json(record_path(name))
    except (OSError, ValueError):
        raise DrawingError("research/%s is not there to close: drawing %s was never opened" % (record_path(name), name)) from None
    return result_id, version, name, record


def _batch_items(entries):
    items = []
    for entry in entries:
        kind = entry.get("chart_type") or "table"
        items.append({"ref": entry["id"], "text": "%s (%s, %s). Purpose: %s Data: %s What it shows: %s" % (
            entry["id"], kind, entry["data_view"], entry["purpose"], entry["data"], entry["shows"])})
    return items


def accept(project, ticket, checked):
    """Record an accepted drawing: its plots' ids, `plots.json`, its record, its `plots` batch, and `drawing` accepted.

    The drawing's plots and tables that passed keep the id they redraw or take the result's next; a plot of its last
    drawing it did not draw is retired, unless the owner marked it keep, when it is carried unchanged; a plot the owner
    dropped is retired whatever the drawing did. Returns the record written.
    """
    from wayline import batches
    book = ledger_for(project)
    with book.lock():
        result_id, version, name, record = _record_of(book, ticket)
        if record.get("status") != OPEN:
            return record  # closed already, by a run before a restart
        folder = directory(result_id, version)
        draft = checked.draft or {}
        held = read_plots(book)
        plots = held["plots"]
        by_id = {plot["id"]: plot for plot in plots}
        drawn = {"plot": [], "table": []}
        for item in checked.kept():
            entry, kind = item["entry"], item["kind"]
            identifier = entry.get("redraws") or "%s.%s%d" % (result_id, "T" if kind == "table" else "",
                                                             _next_number(plots, result_id, kind == "table"))
            drawn_entry = {"id": identifier, "data_view": _one_line(entry.get("data_view")), "purpose": _one_line(entry.get("purpose")),
                           "data": _one_line(entry.get("data")), "shows": _one_line(entry.get("shows")), "checks": item["checks"]}
            if kind == "plot":
                drawn_entry.update(chart_type=_one_line(entry.get("chart_type")), png=folder + str(entry["png"]), svg=folder + str(entry["svg"]),
                                   index_entries=[str(name_) for name_ in entry.get("index_entries") or [] if _text(name_)],
                                   headline=entry.get("headline") is True)
            else:
                drawn_entry.update(csv=folder + str(entry["csv"]))
            drawn[kind].append(drawn_entry)
            plot = by_id.get(identifier)
            if plot is None:
                plot = {"id": identifier, "result": result_id, "kind": kind, "mark": None, "note": None, "drawings": []}
                plots.append(plot)
                by_id[identifier] = plot
            plot.update(chart_type=drawn_entry.get("chart_type"), index_entries=drawn_entry.get("index_entries", []),
                        data_view=drawn_entry["data_view"], status=CURRENT, headline=drawn_entry.get("headline", False),
                        drawings=list(plot.get("drawings") or []) + [name])
        ids = {entry["id"] for entries in drawn.values() for entry in entries}
        # A plot this drawing tried to redraw and left out for its checks stays as its last accepted drawing drew it.
        failed_redraws = {item["entry"].get("redraws") for item in checked.items if item["failed"] and item["entry"].get("redraws")}
        carried, retired = [], []
        for plot in plots:
            if plot.get("result") != result_id or plot["id"] in ids or plot.get("status") != CURRENT:
                continue
            if plot.get("mark") == DROP:
                plot.update(status=RETIRED, headline=False)
                retired.append(plot["id"])
            elif plot.get("mark") == KEEP or plot["id"] in failed_redraws or record.get("asked"):
                carried.append(plot["id"])
                if not record.get("asked"):
                    plot["headline"] = False  # the headlines are this drawing's to mark; an asked plot carries them unchanged
            else:
                plot.update(status=RETIRED, headline=False)
                retired.append(plot["id"])
        batch = None
        if drawn["plot"] or drawn["table"]:
            batch = batches.open_batch(book, PLOTS_BATCH, "Plots of %s, drawing %s: keep, maybe, or drop" % (result_id, name),
                                       _batch_items(drawn["plot"] + drawn["table"]))["id"]
        record.update(
            status=ACCEPTED, closed=now_ts(), reason=None,
            script=folder + str(draft.get("script")) if draft.get("script") else None,
            numbers=folder + str(draft.get("numbers")) if draft.get("numbers") else None,
            inputs=[str(item) for item in draft.get("inputs") or [] if _text(item)],
            plots=drawn["plot"], tables=drawn["table"], carried=carried, retired=retired, left_out=list(checked.left_out)
            + [{"what": _one_line(item.get("what")), "reason": _one_line(item.get("reason"))} for item in draft.get("left_out") or []
               if isinstance(item, dict) and _text(item.get("what")) and _text(item.get("reason"))],
            synthesis=_one_line(draft.get("synthesis")) or None, headline=_one_line(draft.get("headline")) or None,
            can_infer=_lines(draft.get("can_infer")), cannot_infer=_lines(draft.get("cannot_infer")),
            open_questions=_lines(draft.get("open_questions")), earlier_figures=_figures(draft, folder, drawn), batch=batch)
        for plot in plots:
            plot.setdefault("mark", None)
            plot.setdefault("note", None)
        book.write_json(PLOTS_JSON, {"schema_version": 1, "plots": plots}, schema=PLOTS_SCHEMA)
        book.write_json(record_path(name), record, schema=RECORD_SCHEMA)
        book.append_event(DRAWING, {"result": result_id, "version": version, "ticket": ticket["id"], "rest": record["rest"],
                                    "outcome": ACCEPTED, "plots": sorted(ids, key=_plot_order), "left_out": list(checked.left_out),
                                    "retired": retired}, ticket=ticket["id"])
    return record


def accepted_records(project_or_ledger, result_id=None):
    """The accepted drawing records, of `result_id` alone when given, in result and version order."""
    return [record for record in read_records(project_or_ledger, result_id) if record.get("status") == ACCEPTED]


def under_way(project_or_ledger, result_id):
    """Whether a drawing of `result_id` is under way: opened and still owing its outcome."""
    book = ledger_for(project_or_ledger)
    latest = read_records(book, result_id)
    return bool(latest) and _in_progress(latest[-1], _drawing_tickets(book.project), _awaiting_resume(book.read_events()[0]))


def plot_order(identifier):
    """The order plots are listed in: plots before tables, each by number."""
    return _plot_order(identifier)


def drawing_name(result_id, version):
    """`R4-2`: the name of a result's drawing of that version."""
    return _name(result_id, version)


def _plot_order(identifier):
    found = _PLOT_ID.match(identifier)
    return (bool(found.group(2)), int(found.group(3))) if found else (True, 0)


def _lines(values):
    return [_one_line(value) for value in values or [] if _text(value)]


def _figures(draft, folder, drawn):
    """The draft's answers on earlier figures, a plot named by its file turned into its id."""
    by_file = {}
    for entry in drawn["plot"]:
        by_file[entry["png"][len(folder):]] = entry["id"]
        by_file[entry["id"]] = entry["id"]
    answers = []
    for item in draft.get("earlier_figures") or []:
        if not isinstance(item, dict) or item.get("agrees") not in ("agrees", "disagrees", "cannot tell") or not _text(item.get("note")):
            continue
        answers.append({"figure": _one_line(item.get("figure")), "plot": by_file.get(str(item.get("plot"))),
                        "agrees": item["agrees"], "note": _one_line(item["note"])})
    return answers


def fail(project, ticket, reason):
    """Record a drawing that still failed: its result keeps its last accepted drawing, and `drawing` failed is journaled."""
    book = ledger_for(project)
    with book.lock():
        result_id, version, name, record = _record_of(book, ticket)
        if record.get("status") != OPEN:
            return record  # closed already, by a run before a restart
        record.update(status=FAILED, closed=now_ts(), reason=_one_line(reason) or "it failed")
        book.write_json(record_path(name), record, schema=RECORD_SCHEMA)
        book.append_event(DRAWING, {"result": result_id, "version": version, "ticket": ticket["id"], "rest": record["rest"],
                                    "outcome": FAILED, "reason": record["reason"]}, ticket=ticket["id"])
    return record


# --- opening a drawing ---------------------------------------------------------------------------------------------


class DrawingError(ValueError):
    """A drawing code refuses to open: no such result, one with no finding of its own evidence, one in progress."""


def record_path(name):
    """`drawings/R4-2.json` under `research/`, for the drawing named `R4-2`."""
    return "%s/%s.json" % (DRAWINGS_DIR, name)


def _name(result_id, version):
    return "%s-%d" % (result_id, version)


def directory(result_id, version):
    """The drawing ticket's own directory, its touch set: where its script writes every plot, table, and number."""
    return "%s/%s/" % (DRAWINGS_DIR, _name(result_id, version))


def _blank_record(result_id, version, ticket, rest, finding_ids):
    return {"result": result_id, "version": version, "ticket": ticket, "rest": rest, "status": OPEN,
            "findings": sorted(finding_ids), "signature": signature(finding_ids), "opened": now_ts(), "closed": None,
            "reason": None, "script": None, "numbers": None, "inputs": [], "plots": [], "tables": [], "carried": [],
            "retired": [], "left_out": [], "synthesis": None, "headline": None, "can_infer": [], "cannot_infer": [],
            "open_questions": [], "earlier_figures": [], "batch": None}


def _one_line(text):
    return " ".join(str(text or "").split())


def _open_one(book, result, rest, drawn_by, proposed_by, asked=None):
    """One drawing ticket for `result`, its record, and its two events; returns the ticket's id. Under the ledger's lock."""
    version = max([int(record.get("version") or 0) for record in read_records(book, result.id)] or [0]) + 1
    name = _name(result.id, version)
    identifier = tickets.next_id(book.project)
    finding_ids = [finding["id"] for finding in _drawn_from(result, drawn_by)]
    fields = {
        "id": identifier, "title": _one_line("Draw %s: %s" % (result.id, result.heading)), "kind": KIND, "difficulty": 2,
        "status": "open", "blocked_by": [], "touches": [directory(result.id, version)], "resources": {"gpu": 0, "cpu": 1},
        "role": ROLE, "skills": [], "acceptance": {}, "objectives": list(result.objectives), "context_pack": [],
        "origin": "drawing %s at %s" % (name, rest), "proposed_by": proposed_by,
        "demo": "%s explored in every useful plot, each explained, with a synthesis after them" % result.id,
    }
    body = ("\n## Drawing %s\n\nCode opened this drawing of %s (\"%s\") at a rest point (%s), over its findings %s. Its brief, "
            "rendered by code at each launch, is in the prompt.\n" % (name, result.id, result.heading, rest, ", ".join(finding_ids)))
    tickets.write_ticket(book, fields, body)
    record = _blank_record(result.id, version, identifier, rest, finding_ids)
    if asked:
        record["asked"] = asked  # a plot the owner asked for: a small drawing carrying the result's other plots (ticket 101)
    book.write_json(record_path(name), record, schema=RECORD_SCHEMA)
    book.append_event(TICKET_CREATED, {"ticket": identifier, "kind": KIND, "proposed_by": proposed_by, "origin": fields["origin"],
                                       "blocked_by": []}, ticket=identifier)
    book.append_event(DRAWING, {"result": result.id, "version": version, "ticket": identifier, "rest": rest, "outcome": "opened"},
                      ticket=identifier)
    return identifier


def draw_again(project, result_id, asked=None):
    """The owner's word, "draw R4 again": one drawing of `result_id` now, changed or not; returns its ticket's id.

    Refused for a result that is not live, one with no finding from the project's own evidence, and one whose drawing
    is under way. The conductor launches it at its next wave, as any open ticket. `asked` is the plot the owner asked
    for (`wayline.reports.ask_plot`): the brief carries it, and acceptance carries the result's other plots unchanged.
    """
    book = ledger_for(project)
    with book.lock():
        found = {result.id: result for result in results_module.read_results(book)}
        result = found.get(result_id)
        if result is None:
            raise DrawingError("%s is no live result with a current finding; the results are %s"
                               % (result_id, ", ".join(found) or "none yet"))
        by_id = _drawing_tickets(book.project)
        drawn_by = set(by_id)
        if not [finding for finding in _drawn_from(result, drawn_by) if own_evidence(finding, _manifested(book.project))]:
            raise DrawingError("%s holds no finding from the project's own evidence: there is nothing of its own to draw" % result_id)
        latest = read_records(book, result_id)
        if latest and _in_progress(latest[-1], by_id, _awaiting_resume(book.read_events()[0])):
            raise DrawingError("%s's drawing %s-%d is under way (ticket %d)" % (result_id, result_id, latest[-1]["version"], latest[-1]["ticket"]))
        return _open_one(book, result, OWNER, drawn_by, "human", asked=asked)


def open_drawings(project, rest, only=None, proposed_by="conductor"):
    """Open one drawing ticket per result `due` at the rest point `rest`, the stopping rule's first; returns their ids.

    `only` names the results to open when they are due (none else). Nothing is opened for a result whose drawing is in
    progress or which has not changed since its last drawing.
    """
    if rest not in RESTS:
        raise DrawingError("a rest point is one of %s, got %r" % (", ".join(RESTS), rest))
    book = ledger_for(project)
    opened = []
    with book.lock():
        chosen = due(book.project)
        if only is not None:
            chosen = [identifier for identifier in chosen if identifier in set(only)]
        if not chosen:
            return opened
        drawn_by = set(_drawing_tickets(book.project))
        found = {result.id: result for result in results_module.read_results(book)}
        for identifier in chosen:
            opened.append(_open_one(book, found[identifier], rest, drawn_by, proposed_by))
    return opened
