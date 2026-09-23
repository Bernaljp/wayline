"""The figure role (Implementation Decisions 13; research-notes 11 Sections 1 and 4; ticket 50).

A `figure_request/1` goes in and a `figure_result/1` comes out, the way the spec's doctrine asks:
every step that is not a drawing or a judgment is code, and every drawing and every judgment is a
session of its own.

**Unguided** (a new figure):

1. The data shape is classified in code from the result artifacts (`classify_shape`): the columns,
   their types and cardinalities, the grouping, a pairing, a matrix or a graph, and the chart
   families that shape suits.
2. The candidates come from `figures/plot_index.json` (`take_candidates`), filtered by the shape's
   families and the claim type's, and by the project's library from the request's target, capped at
   `candidates.max` (the request's, else `policy.figures.candidates.max`, 5). A framework figure or a
   graphical abstract takes its candidates from the layouts of `figures/structure_index.json`.
3. One `figure-designer` session draws every candidate from the real data in the house palette
   (`## Drafts`), reading each candidate's pitfalls from the index first and saying which as
   `pitfalls_consulted`. A draft that did not render stays in the result with its error and drops
   out of the ranking; so does one reported rendered whose PNG is not on disk.
4. A fresh `figure-critic` session, never the designer's, ranks every rendered draft with a score
   on `claim_legibility`, `honesty`, `venue_fit`, and `legibility_at_size`, and its reasons.
5. The pick. Under autonomy `interactive` and `checkpoints` it is the owner's: a human-only decision
   ticket carries the ranking and the result waits as `candidates_ranked` until `resume` finds it
   answered. Under `autonomous` it is the decider's, and the decider's rule leaves it nothing to
   weigh, so code applies it: rank 1, with `margin_low: true` when rank 1's total over rank 2's is
   below `policy.figures.margin_threshold` (2). No session ever picks its own candidate.
6. A fresh designer session finishes the pick (`## Finish`): the house style, the caption, the
   notes, and the structured replacements for telling the author anything.
7. The 19 machine checks of ticket 49 run (`figure_checks.run_checks`). A failure goes back to the
   finishing session once with the failed checks, before any verdict is spent; a second failure is
   `failed_checks`.
8. The one honesty verdict goes through the gate of ticket 32 (`gates.verdict`, `figure_honesty`) on
   the crops, the full image, the caption, the notes, the request (the claim and the spec), and the
   check report, after one `equation_match` sub-verdict per equation the figure typesets. A failed
   sub-verdict is an `equation_mismatch` finding and fails the figure.

**Guided** (a revision): the same finishing session, entered with `revision_of` and the
`change_requests`. A request that would make the figure assert something false is refused: the
refusal is recorded with its reason, the nearest honest alternative is drawn as a new candidate,
and a human-only decision ticket asks the owner whether to override it. Only an answer the journal
records as the owner's (`decided_by: human`) sets `overridden_by`; `resume` then has the request
carried out and writes the override into the caption and the notes itself.

**What leaves the role.** Every `findings_for_text` entry becomes a proposal (`proposals`, kind
`writing`); the traps a result would promote into the plot index are filed as feedback for the
evolve loop (`changes.file_from_figure`), whose change can fold them in with `wayline figures
fold-traps`. Every result, whatever its status, is validated against `figure_result/1`, written to
`figures/<figure_id>/figure_result.json`, and journaled as `figure_result` with its path and hash.

The designer writes only under `figures/<figure_id>/` (`TICKET_TOUCHES`); the critic writes nothing.
Both run from the project root on `policy.roles`.
"""

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, decisions, figure_checks, figures, gates, worker
from wayline.cli import parse_args
from wayline.jsonschema import load_schema, validate
from wayline.ledger import FIGURE_RESULT, Ledger
from wayline.project import ProjectError, find_project, policy_for, read_harness
from wayline.provenance import read_manifest, sha256_of
from wayline.replay import replay
from wayline.tickets import TicketError, read_tickets

__all__ = [
    "DESIGNER", "CRITIC", "RUBRIC", "HONESTY_RULES", "FigureError", "classify_shape", "claim_families",
    "take_candidates", "margin_of", "make", "resume_figure", "read_result", "figure_command",
]

DESIGNER = "figure-designer"
CRITIC = "figure-critic"
VERIFIER = "verifier"
REQUEST_SCHEMA, RESULT_SCHEMA = "figure_request", "figure_result"
DRAFTS_SCHEMA, RANKING_SCHEMA, FINISH_SCHEMA = "figure_drafts", "figure_ranking", "figure_finish"
RUBRIC = ("claim_legibility", "honesty", "venue_fit", "legibility_at_size")
RUBRIC_VERSION = "1"
HONESTY_RULES = ("capability_not_realized", "selection_artifact", "invisible_comparison", "omitted_negative",
                 "undisclosed_mixed_data", "equation_mismatch", "implied_claim")
TIER = ("opus", "high")              # the fallback when a policy carries no `roles.figure-designer` or `roles.figure-critic`
BUDGET = {DESIGNER: "medium", CRITIC: "small"}
DEFAULT_MAX = 5
DEFAULT_MARGIN = 2
FIGURES = "figures"
REQUEST_JSON = "request.json"
RESULT_JSON = "figure_result.json"
CHECKS_JSON = "checks.json"
SESSIONS = "sessions/figures"         # research/sessions/figures/<figure_id>/<n>/
BY = "figure"                         # `proposed_by` on the tickets the figure role files
AUTONOMOUS = "autonomous"
OVERRIDE = "override"
KEEP = "keep the refusal"
OVERRIDE_OPTION = "override: draw it as asked"
TERMINAL = ("verified", "failed_checks", "honesty_failed", "refused")

HONESTY_QUESTION = "Does this figure, with its caption and notes, assert something its data does not?"
HONESTY_SCOPE = (
    "Only whether the figure, its caption, and its notes assert something the data does not: a capability the "
    "analysis does not realize, a selection that is not representative beyond its declared statistic, a "
    "comparison the eye cannot make at the figure's size, a load-bearing negative left out, two datasets in one "
    "panel not disclosed, an equation that does not match its code, or a layout that implies a claim the caption "
    "does not make. Style and taste are out of scope. Start the text of every finding with the rule it breaks, in "
    "brackets: [capability_not_realized], [selection_artifact], [invisible_comparison], [omitted_negative], "
    "[undisclosed_mixed_data], [equation_mismatch], or [implied_claim]."
)
EQUATION_QUESTION = "Does the equation the figure typesets, %s, match what the code at %s computes?"
EQUATION_SCOPE = ("Only whether the drawn equation and the code agree term by term: the same quantities, operations, "
                  "indices, and constants. Whether the equation is the right one for the analysis is out of scope.")

RESUME_INVALID = (
    "What you returned could not be used: %s. Fix exactly that and return it again, whole, through the structured "
    "output. Do not redraw what was already right."
)
REPAIR_CHECKS = (
    "The machine checks failed on the figure you finished:\n\n%s\n\nFix the generator, the figure files, the caption, "
    "or the notes so these pass, run the generator again, and return the result again, whole, through the structured "
    "output."
)

_SPACES = re.compile(r"\s+")
_RULE_PREFIX = re.compile(r"^\s*\[([a-z_]+)\]\s*")
_RANK = re.compile(r"\brank\s*#?\s*(\d+)\b|^\s*#?(\d+)\s*$", re.IGNORECASE)
_TIME_NAME = re.compile(r"(^|_)(time|date|day|epoch|step|iter|iteration|year|month|timestamp|t)($|_)", re.IGNORECASE)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_SLUG = re.compile(r"[^a-z0-9]+")

# A claim type's chart families: the small table research-notes 11 Section 4.1 keeps beside the index. The first
# keyword found in the claim type wins its families; a claim type naming none of them takes the shape's alone.
_CLAIM_FAMILIES = (
    (("comparison", "compare", "versus", "difference", "better", "outperform"), ("ranking", "distribution")),
    (("ranking", "rank", "order"), ("ranking",)),
    (("trend", "evolution", "over time", "time course", "trajectory", "convergence", "sweep", "scaling"), ("evolution",)),
    (("correlation", "relationship", "association", "tradeoff", "trade-off", "dependence"), ("correlation",)),
    (("distribution", "spread", "variability", "variance", "uncertainty"), ("distribution",)),
    (("composition", "proportion", "share", "fraction", "breakdown"), ("part_of_a_whole",)),
    (("flow", "process", "pipeline", "mechanism"), ("flow", "network")),
    (("network", "interaction", "regulation", "graph"), ("network",)),
    (("spatial", "geographic", "map"), ("map",)),
)


class FigureError(ValueError):
    """A request the role cannot start on, or a result it cannot resume."""


class _Stop(Exception):
    """The run stops here with the result as it stands: `status` and the `reason` the journal gives it."""

    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


# --- the data shape (code, Type-A) -----------------------------------------------------------------


def _number(text):
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if value == value else None  # NaN is not a number a column can be read by


def _column(name, values):
    """One column's type and cardinality from its non-empty values."""
    present = [value for value in values if value is not None and str(value).strip() != ""]
    distinct = len({str(value) for value in present})
    if present and all(isinstance(value, bool) for value in present):
        kind = "categorical"
    elif present and all(_number(value) is not None for value in present):
        kind = "time" if _TIME_NAME.search(str(name)) else "numeric"
    elif present and all(_ISO_DATE.match(str(value)) for value in present):
        kind = "time"
    else:
        kind = "categorical"
    return {"name": str(name), "type": kind, "cardinality": distinct}


def _table(rows, columns):
    """The shape of a table given as records."""
    described = [_column(name, [row.get(name) for row in rows]) for name in columns]
    return {"structure": "table", "rows": len(rows), "columns": described}


def _read_csv(path, delimiter):
    with open(path, encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        return _table(rows, reader.fieldnames or [])


def _json_shape(value):
    """A JSON result's shape: records, columns of equal length, a matrix, or the keys of a nested record."""
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        columns = []
        for item in value:
            columns.extend(key for key, cell in item.items() if key not in columns and not isinstance(cell, (dict, list)))
        return _table(value, columns)
    if isinstance(value, list) and value and all(isinstance(item, list) for item in value) \
            and all(_number(cell) is not None for item in value for cell in item):
        return {"structure": "matrix", "rows": len(value), "columns": [], "width": max(len(item) for item in value)}
    if isinstance(value, dict):
        found = _largest_block(value, ())
        if found is not None:
            path, shape = found
            if path:
                shape["records_under"] = ".".join(path)
            return shape
        return {"structure": "nested", "rows": 1, "columns": [], "keys": sorted(str(key) for key in value)[:40]}
    return {"structure": "opaque", "rows": None, "columns": []}


def _columns_block(value):
    """A table from a record whose scalar lists share one length (at least two of them), else None."""
    lists = {key: cell for key, cell in value.items() if isinstance(cell, list) and cell and not isinstance(cell[0], (dict, list))}
    lengths = {len(cell) for cell in lists.values()}
    if len(lists) < 2 or len(lengths) != 1:
        return None
    rows = [{key: cell[index] for key, cell in lists.items()} for index in range(lengths.pop())]
    return _table(rows, list(lists))


def _largest_block(value, path, depth=0):
    """`(key path, table)` of the biggest table anywhere in a nested record: equal-length columns, or a list of records.

    A result file often keeps its table under a key (`{"auroc": {"raw": [...], "flag": [...]}}`); the one with the most
    cells stands for the file, and the path to it is said, so the designer is pointed at it.
    """
    best = None
    block = _columns_block(value)
    if block is not None:
        best = (path, block)
    for key, cell in value.items():
        candidate = None
        if isinstance(cell, list) and cell and all(isinstance(item, dict) for item in cell):
            candidate = (path + (str(key),), _json_shape(cell))
        elif isinstance(cell, dict) and depth < 4:
            candidate = _largest_block(cell, path + (str(key),), depth + 1)
        if candidate is not None and candidate[1].get("structure") == "table" and (
                best is None or _cells(candidate[1]) > _cells(best[1])):
            best = candidate
    return best


def _cells(shape):
    return (shape.get("rows") or 0) * len(shape.get("columns") or [])


def _file_shape(path):
    suffix = path.suffix.lower()
    try:
        if suffix in (".csv", ".tsv", ".txt"):
            return _read_csv(path, "\t" if suffix == ".tsv" else ",")
        if suffix == ".json":
            return _json_shape(json.loads(path.read_text(encoding="utf-8")))
        if suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            return _json_shape(rows)
    except (OSError, ValueError, csv.Error) as failure:
        return {"structure": "unreadable", "rows": None, "columns": [], "error": str(failure)[:200]}
    return {"structure": "opaque", "rows": None, "columns": []}


def _hints(shape):
    """The chart families a data shape suits, most specific first."""
    structure = shape.get("structure")
    if structure == "matrix":
        return ["correlation"]
    columns = shape.get("columns") or []
    names = {column["name"].lower() for column in columns}
    numeric = [column for column in columns if column["type"] == "numeric"]
    categorical = [column for column in columns if column["type"] == "categorical"]
    time = [column for column in columns if column["type"] == "time"]
    rows = shape.get("rows") or 0
    hints = []
    if {"source", "target"} <= names or {"from", "to"} <= names:
        hints.append("network")
    if time and numeric:
        hints.append("evolution")
    if shape.get("paired"):
        hints.append("ranking")
    if categorical and numeric:
        hints.append("ranking")
        if any(0 < column["cardinality"] < rows for column in categorical):
            hints.append("distribution")  # repeated measures per group: the spread is there to be shown
    if len(numeric) >= 2 and not time:
        hints.append("correlation")
    if len(numeric) == 1 and not categorical and not time:
        hints.append("distribution")
    ordered = []
    for family in hints:
        if family not in ordered:
            ordered.append(family)
    return ordered or ["multi_dimensional"]


def _paired(columns):
    names = [column["name"].lower() for column in columns]
    return any(any(a in name for name in names) and any(b in name for name in names)
               for a, b in (("before", "after"), ("pre", "post"), ("baseline", "treated")))


def classify_shape(project, data):
    """The data shape of a request's `data`, classified in code (research-notes 11 Section 4.1, step 1).

    Each input is read by its extension (CSV, TSV, JSON records or columns, JSONL); what the harness
    cannot read is `opaque`, and a file that is not there is `missing`. The shape of the first
    tabular input stands for the figure, and `family_hint` is the chart families it suits.
    """
    project = Path(project)
    inputs = []
    for entry in data or []:
        path = project / entry["path"]
        shape = _file_shape(path) if path.is_file() else {"structure": "missing", "rows": None, "columns": []}
        shape["path"] = entry["path"]
        if shape.get("columns"):
            shape["paired"] = _paired(shape["columns"])
        inputs.append(shape)
    primary = next((shape for shape in inputs if shape.get("structure") in ("table", "matrix")), inputs[0] if inputs else {})
    columns = primary.get("columns") or []
    return {
        "inputs": inputs,
        "structure": primary.get("structure", "none"),
        "rows": primary.get("rows"),
        "n_variables": len(columns),
        "variable_types": [column["type"] for column in columns],
        "grouping": [column["name"] for column in columns
                     if column["type"] == "categorical" and 0 < column["cardinality"] < (primary.get("rows") or 0)],
        "paired": bool(primary.get("paired")),
        "family_hint": _hints(primary) if primary else ["multi_dimensional"],
    }


def claim_families(claim_type):
    """The chart families a claim type maps to; () when the table names none."""
    lowered = str(claim_type or "").lower()
    for keywords, families in _CLAIM_FAMILIES:
        if any(keyword in lowered for keyword in keywords):
            return families
    return ()


# --- the candidates (code, Type-A) -----------------------------------------------------------------


def _families(request, shape):
    """The families to take candidates from, best first: the claim's that the shape suits, then the claim's, then the shape's.

    The claim goes before the shape where they disagree, because the claim is what the figure has to say and a shape
    read off a file (a wide table, a nested record) can suit a family the claim has no use for.
    """
    asked = (request.get("candidates") or {}).get("families")
    if asked:
        return list(asked)
    hints, claimed = shape.get("family_hint") or [], claim_families(request["claim"].get("claim_type"))
    ordered = [family for family in claimed if family in hints]
    ordered += [family for family in claimed if family not in ordered]
    ordered += [family for family in hints if family not in ordered]
    return ordered


def _libraries(entry):
    return [implementation.get("library") for implementation in entry.get("library_implementations") or []]


def _library_pitfalls(index, library):
    """The pitfalls every entry of `library` in the index carries: the library's own, seeded once per entry."""
    lists = [entry.get("known_pitfalls") or [] for entry in index.get("entries") or [] if library in _libraries(entry)]
    if not lists:
        return []
    return [pitfall for pitfall in lists[0] if all(pitfall in other for other in lists[1:])]


def _slug(text, limit=40):
    return _SLUG.sub("-", str(text).lower()).strip("-")[:limit].rstrip("-") or "candidate"


def take_candidates(request, shape, index, structures=None, policy=None):
    """Up to `candidates.max` candidates from the plot index (research-notes 11 Section 4.1, step 2).

    Entries are taken a family at a time, round the families in the order `_families` gives, so the
    claim's first family always has the first candidate and a family the index is crowded with cannot
    take every slot. Within a family the project's library comes first: an entry the index implements
    in the target's library carries its own pitfalls; one implemented only in another library is still
    a chart type the project's library can draw, and carries the pitfalls every entry of the project's
    library shares. Chart types already taken, and the ids the request excludes, are skipped. A
    framework figure or a graphical abstract takes the layouts of the structure index instead.
    """
    asked = request.get("candidates") or {}
    policy_max = (((policy or {}).get("figures") or {}).get("candidates") or {}).get("max")
    maximum = int(asked.get("max") or policy_max or DEFAULT_MAX)
    exclude = set(asked.get("exclude_index_ids") or [])
    library = request["target"]["library"]
    if request["kind"] != "result":
        layouts = [layout for layout in (structures or figures.structure_index()).get("structures") or []
                   if isinstance(layout, dict) and layout.get("id") and layout["id"] not in exclude]
        return [{"index_id": layout["id"], "chart_type": layout["description"], "family": "framework", "library": library,
                 "index_library": None, "function_or_geom": None, "source_url": None,
                 "layout": layout.get("panel_layout"), "pitfalls": []} for layout in layouts[:maximum]]
    families = _families(request, shape)
    shared = _library_pitfalls(index, library)
    queues = {family: [] for family in families}
    for entry in index.get("entries") or []:
        if isinstance(entry, dict) and entry.get("family") in queues and entry.get("id") and entry["id"] not in exclude:
            queues[entry["family"]].append(entry)
    for family in queues:
        queues[family].sort(key=lambda entry: library not in _libraries(entry))  # stable: the index's own order within
    ranked = []
    while any(queues.values()):
        for family in families:
            if queues[family]:
                ranked.append(queues[family].pop(0))
    taken, seen = [], set()
    for entry in ranked:
        chart = str(entry.get("chart_type") or "").strip().lower()
        if not chart or chart in seen:
            continue
        seen.add(chart)
        own = library in _libraries(entry)
        implementation = next((item for item in entry.get("library_implementations") or [] if item.get("library") == library),
                              (entry.get("library_implementations") or [{}])[0])
        taken.append({
            "index_id": entry["id"], "chart_type": entry["chart_type"], "family": entry["family"], "library": library,
            "index_library": implementation.get("library"), "function_or_geom": implementation.get("function_or_geom"),
            "source_url": (implementation.get("snippet_locator") or {}).get("source_url"), "layout": None,
            "pitfalls": list(entry.get("known_pitfalls") or []) if own else list(shared),
        })
        if len(taken) == maximum:
            break
    return taken


def margin_of(candidates):
    """Rank 1's total over rank 2's, or None when there is no rank 2."""
    ranked = sorted((candidate for candidate in candidates if candidate.get("rank")), key=lambda candidate: candidate["rank"])
    if len(ranked) < 2:
        return None
    return round(ranked[0]["score"]["total"] - ranked[1]["score"]["total"], 6)


# --- the sessions ------------------------------------------------------------------------------------


def _tier(policy, role):
    entry = ((policy or {}).get("roles") or {}).get(role) or {}
    return entry.get("model") or TIER[0], entry.get("effort") or TIER[1]


def _session_dir(project, figure_id):
    """The first free `research/sessions/figures/<figure_id>/<n>`, claimed by creating it."""
    base = Path(project) / "research" / SESSIONS / figure_id
    base.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        candidate = base / str(number)
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            number += 1


class _Run:
    """One pass of the role over one request: the sessions it launches and the result it builds."""

    def __init__(self, project, request, result, *, harness_root, policy, autonomy, checks, notify, say):
        self.project = Path(project).resolve()
        self.request = request
        self.result = result
        self.figure_id = request["figure_id"]
        self.harness_root = Path(harness_root).resolve()
        self.policy = policy
        self.autonomy = autonomy
        self.checks = checks
        self.notify = notify
        self.say = say
        self.directory = FIGURES + "/" + self.figure_id
        self.ticket = _ticket_id(request)
        self.equations = []
        self.prior_verdicts = {}  # equation id -> the sub-verdict an earlier pass took on this same drawing
        self.overridden = []      # the refusals this pass carries out, each with the owner's `by`
        self.designer_model = _tier(policy, DESIGNER)[0]

    # --- launching -------------------------------------------------------------------------------

    def _launch_request(self, role_name, prompt, schema, touches):
        model, effort = _tier(self.policy, role_name)
        role = worker.read_role(role_name, self.harness_root, self.project)
        run_dir = _session_dir(self.project, self.figure_id)
        budget = ((self.policy.get("budget") or {}).get(BUDGET[role_name]) or {})
        env = {"WAYLINE_PROJECT": str(self.project), "WAYLINE_RUN": str(run_dir), "TICKET_ACCEPTANCE_FILE": ""}
        if touches:
            env["TICKET_TOUCHES"] = touches
        return worker.LaunchRequest(
            role=role.name, model=model, effort=effort, prompt=prompt,
            agent_json=role.agent_json(model, effort, budget.get("max_turns")),
            allowed_tools=list(role.allowed_tools), disallowed_tools=list(role.disallowed_tools),
            settings_path=gates.write_worker_settings(run_dir / "settings.json", self.harness_root),
            cwd=self.project, env=env,
            schema_path=self.harness_root / "schemas" / (schema + ".json"),
            max_minutes=budget.get("max_minutes"),
        ), role

    def _converse(self, request, what, check, envelope=None, message=None):
        """Launch (or, given an envelope, resume with `message`), then resume once with the problems; `(envelope, value)`.

        `check(value)` returns the problems with a structured output, or () when code accepts it. A session a usage
        window refused is never resumed: the run stops `blocked` and says which window.
        """
        try:
            envelope = worker.resume(request, envelope.session_id, message) if envelope is not None else worker.launch(request)
        except worker.LaunchError as failure:
            raise _Stop("blocked", "%s could not be launched: %s" % (what, failure)) from None
        self._record_session(request.role, envelope)
        problems = self._problems(envelope, request, what, check)
        if problems and envelope.session_id:
            try:
                envelope = worker.resume(request, envelope.session_id, RESUME_INVALID % "; ".join(problems))
            except worker.LaunchError as failure:
                raise _Stop("blocked", "%s could not be resumed: %s" % (what, failure)) from None
            problems = self._problems(envelope, request, what, check)
        if problems:
            raise _Stop("blocked", "%s returned nothing usable: %s" % (what, "; ".join(problems)))
        return envelope, envelope.structured_output

    def _problems(self, envelope, request, what, check):
        try:
            gates.raise_if_refused(envelope, request.model, what)
        except gates.UsageLimited as refused:
            raise _Stop("blocked", str(refused)) from None
        if not envelope.valid:
            return list(envelope.errors) or ["no structured output"]
        return list(check(envelope.structured_output))

    def _record_session(self, role, envelope):
        entry = {"role": role, "session": envelope.session_id}
        sessions = self.result.setdefault("sessions", [])
        if entry not in sessions:
            sessions.append(entry)

    # --- the prompts -----------------------------------------------------------------------------

    def _header(self, heading):
        request, target = self.request, self.request["target"]
        claim = request["claim"]
        lines = [
            heading, "",
            "- figure: `%s`, written under `%s/`%s" % (self.figure_id, self.directory,
                                                     "" if not request.get("ticket") else " (ticket %s)" % request["ticket"]),
            "- kind: %s; register: %s" % (request["kind"], request["register"]),
            "- the claim it carries (%s): %s" % (claim["claim_type"], _one_line(claim["text"])),
            "- target: %s mm wide%s, no text under %s pt, at least %s dpi, formats %s, library %s%s%s" % (
                target["width_mm"], ", at most %s mm tall" % target["max_height_mm"] if target.get("max_height_mm") else "",
                target["min_font_pt"], target["min_dpi"], ", ".join(target["formats"]), target["library"],
                ", for %s" % target["venue"] if target.get("venue") else "",
                ", at most %d words" % target["max_words"] if target.get("max_words") else ""),
            "- the house style (the color budget; draw data in its colors only): `%s`" % (request.get("style") or figure_checks.DEFAULT_STYLE),
            "- run a script from the project root as `%s <script>`: the one spelling your permissions allow, and the "
            "interpreter the machine checks regenerate the figure with" % _python_spelling(self.project),
        ]
        if claim.get("evidence"):
            lines.append("- the claim's evidence: %s" % "; ".join(claim["evidence"]))
        lines += ["", "# The data", "", "Open these yourself; they are the only data the figure may draw.", ""]
        shapes = {shape["path"]: shape for shape in (self.result.get("data_shape") or {}).get("inputs") or []}
        for entry in request["data"]:
            lines.append("- `%s`%s: %s" % (entry["path"], " (run %s)" % entry["run_id"] if entry.get("run_id") else "",
                                          _describe_shape(shapes.get(entry["path"]))))
        return lines

    def drafts_prompt(self, candidates, role):
        lines = self._header("# The figure you are drafting")
        lines += ["", "# The candidates", "",
                  "Draw each at the paths given, in this order. Read its pitfalls before you draw it.", ""]
        for number, candidate in enumerate(candidates, start=1):
            lines.append("## %d. `%s`: %s (%s)" % (number, candidate["index_id"], candidate["chart_type"], candidate["family"]))
            lines.append("")
            lines.append("- draft script: `%s`" % candidate["generator"])
            lines.append("- draft PNG: `%s`" % candidate["png"])
            if candidate.get("layout"):
                lines.append("- the layout: %s" % candidate["layout"])
            if candidate.get("function_or_geom") or candidate.get("source_url"):
                lines.append("- the index's reference implementation: %s%s%s" % (
                    candidate.get("index_library") or "?", " `%s`" % candidate["function_or_geom"] if candidate.get("function_or_geom") else "",
                    ", %s" % candidate["source_url"] if candidate.get("source_url") else ""))
            if candidate["pitfalls"]:
                lines.append("- pitfalls to read before drawing it:")
                lines.extend("  - %s" % pitfall for pitfall in candidate["pitfalls"])
            else:
                lines.append("- pitfalls to read before drawing it: none listed")
            lines.append("")
        return _prompt(lines, role, "Drafts", DRAFTS_SCHEMA)

    def critic_prompt(self, rendered, role):
        lines = self._header("# The drafts you are ranking")
        if self.request.get("comparables"):
            lines += ["", "# The comparables", ""] + ["- `%s`" % item for item in self.request["comparables"]]
        lines += ["", "# The drafts", "", "Another session drew these. Rank every one.", ""]
        for candidate in rendered:
            lines.append("- `%s`: %s. PNG `%s`, script `%s`" % (candidate["index_id"], candidate["chart_type"],
                                                             candidate["png"], candidate["generator"]))
        return _prompt(lines, role, None, RANKING_SCHEMA)

    def finish_prompt(self, start, role, overridden=()):
        lines = self._header("# The figure you are finishing")
        lines += ["", "# Where you start", ""] + start
        lines += ["", "# What you write", "",
                  "- the final generator: `%s`, run from the project root" % self.paths["generator"]]
        for fmt in self.request["target"]["formats"]:
            lines.append("- the %s it writes: `%s`" % (fmt.upper(), self.paths[fmt]))
        lines += ["- the caption: `%s`" % self.paths["caption"], "- the notes: `%s`" % self.paths["notes"]]
        if self.request["mode"] == "guided":
            lines.append("- an honest alternative to a refused request `<id>`: `%s/alternatives/<id>/draft.py` and its `draft.png`"
                         % self.directory)
        lines += ["", "# What the machine checks read", ""] + _check_contract(self.request)
        if overridden:
            lines += ["", "# The owner's override", "",
                      "The owner has overridden your refusal of these requests through the decision queue. Carry each out as "
                      "asked. The harness records the override in the caption and the notes itself.", ""]
            lines += ["- `%s`: %s (you refused it because: %s)" % (item["id"], item["text"], item["reason"]) for item in overridden]
        return _prompt(lines, role, "Finish", FINISH_SCHEMA)

    # --- the steps -------------------------------------------------------------------------------

    def check_data(self):
        """Every data file the request names is on disk with the hash it names; else the run stops before a session."""
        changed = []
        for entry in self.request["data"]:
            path = self.project / entry["path"]
            if not path.is_file():
                changed.append("%s is not a file in the project" % entry["path"])
            elif sha256_of(path) != entry["sha256"]:
                changed.append("%s no longer has the sha256 the request names" % entry["path"])
        if changed:
            raise _Stop("blocked", "the request's data changed since it was written, so the figure would not show the run it "
                                   "names: %s; write the request again from the current files" % "; ".join(changed))

    def unguided(self):
        self.check_data()
        shape = classify_shape(self.project, self.request["data"])
        self.result["data_shape"] = shape
        try:
            index = figures.load_index(self.project / FIGURES / figures.PLOT_INDEX_JSON)
        except figures.FigureIndexError as failure:
            raise _Stop("blocked", "the plot index cannot be read: %s; run wayline figures build-index" % failure) from None
        structures = _read_json(self.project / FIGURES / figures.STRUCTURE_INDEX_JSON)
        if not isinstance(structures, dict) or not isinstance(structures.get("structures"), list):
            structures = figures.structure_index()
        if not isinstance(index, dict) or not isinstance(index.get("entries"), list):
            raise _Stop("blocked", "the plot index has no entries list; run wayline figures build-index")
        candidates = take_candidates(self.request, shape, index, structures, self.policy)
        self.drafted(candidates)
        return self.rank_and_pick()

    def drafted(self, candidates):
        if not candidates:
            raise _Stop("blocked", "the plot index offers no candidate for the families %s; run wayline figures build-index"
                        % ", ".join(_families(self.request, self.result.get("data_shape") or {})))
        for number, candidate in enumerate(candidates, start=1):
            folder = "%s/candidates/%d-%s" % (self.directory, number, _slug(candidate["index_id"]))
            candidate["generator"], candidate["png"] = folder + "/draft.py", folder + "/draft.png"
        self.draw(candidates)

    def rank_and_pick(self):
        self.rank()
        return self.pick()

    def draw(self, candidates):
        request, role = self._launch_request(DESIGNER, "", DRAFTS_SCHEMA, self.directory + "/")
        request.prompt = self.drafts_prompt(candidates, role)
        by_id = {candidate["index_id"]: candidate for candidate in candidates}

        def check(value):
            problems, seen = [], set()
            for draft in value["drafts"]:
                candidate = by_id.get(draft["index_id"])
                if candidate is None:
                    problems.append("%r is not one of the candidates" % draft["index_id"])
                    continue
                if draft["index_id"] in seen:
                    problems.append("%s is reported twice" % draft["index_id"])
                seen.add(draft["index_id"])
                unknown = [pitfall for pitfall in draft["pitfalls_consulted"] if pitfall not in candidate["pitfalls"]]
                if unknown:
                    problems.append("%s lists pitfalls that were not listed for it: %s" % (draft["index_id"], "; ".join(unknown)[:300]))
                if draft["rendered"] and candidate["pitfalls"] and not draft["pitfalls_consulted"]:
                    problems.append("%s was drawn without reading any of its %d listed pitfalls" % (draft["index_id"], len(candidate["pitfalls"])))
            missing = [identifier for identifier in by_id if identifier not in seen]
            if missing:
                problems.append("no draft is reported for %s" % ", ".join(missing))
            return problems

        _, value = self._converse(request, "the designer's drafts", check)
        self.traps = list(value["traps_hit"])
        drafts = {draft["index_id"]: draft for draft in value["drafts"]}
        out = []
        for candidate in candidates:
            draft = drafts[candidate["index_id"]]
            entry = {"rank": None, "index_id": candidate["index_id"], "chart_type": candidate["chart_type"],
                     "library": candidate["library"], "generator": draft.get("generator"), "png": draft.get("png"),
                     "rendered": bool(draft["rendered"]), "pitfalls_consulted": list(draft["pitfalls_consulted"])}
            if entry["rendered"]:
                missing = [key for key in ("png", "generator") if not self._inside_file(entry[key])]
                if missing:
                    entry["rendered"] = False
                    entry["error"] = "reported rendered, but its %s is not a file under %s/" % (" and ".join(missing), self.directory)
            else:
                entry["error"] = _one_line(draft.get("error") or "did not render")
            out.append(entry)
        self.result["candidates"] = out
        self.result["traps_hit"] = self.traps

    def rank(self):
        rendered = [candidate for candidate in self.result["candidates"] if candidate["rendered"]]
        if not rendered:
            raise _Stop("blocked", "no draft rendered: %s" % "; ".join(
                "%s: %s" % (candidate["index_id"], candidate["error"]) for candidate in self.result["candidates"])[:600])
        if (self.request.get("budget") or {}).get("critic_sessions") == 0:
            raise _Stop("blocked", "the request's budget allows no critic session, and nothing else may rank the drafts")
        request, role = self._launch_request(CRITIC, "", RANKING_SCHEMA, None)
        request.prompt = self.critic_prompt(rendered, role)
        ids = [candidate["index_id"] for candidate in rendered]

        def check(value):
            problems = []
            ranked = [entry["index_id"] for entry in value["ranking"]]
            if sorted(ranked) != sorted(ids):
                problems.append("the ranking names %s; it ranks every draft once: %s" % (", ".join(ranked), ", ".join(ids)))
            ranks = sorted(entry["rank"] for entry in value["ranking"])
            if ranks != list(range(1, len(ranks) + 1)):
                problems.append("the ranks are %s; they run 1 to %d with no ties" % (ranks, len(ranks)))
            by_rank = sorted(value["ranking"], key=lambda entry: entry["rank"])
            totals = [sum(entry["score"][key] for key in RUBRIC) for entry in by_rank]
            for above, below, entry in zip(totals, totals[1:], by_rank[1:]):
                if below > above:
                    problems.append("rank %d (%s) scores %g, more than the rank above it (%g)" % (entry["rank"], entry["index_id"], below, above))
            return problems

        envelope, value = self._converse(request, "the critic's ranking", check)
        ranking = {entry["index_id"]: entry for entry in value["ranking"]}
        for candidate in rendered:
            entry = ranking[candidate["index_id"]]
            candidate["rank"] = entry["rank"]
            candidate["score"] = dict(entry["score"], total=sum(entry["score"][key] for key in RUBRIC))
            candidate["critic_reasons"] = entry["reasons"]
        self.result["candidates"].sort(key=lambda candidate: (candidate["rank"] is None, candidate["rank"] or 0))
        self.result["critic"] = {"session": envelope.session_id, "model": envelope.model or request.model, "rubric_version": RUBRIC_VERSION}
        self.result["status"] = "candidates_ranked"

    def pick(self):
        margin = margin_of(self.result["candidates"])
        threshold = (self.policy.get("figures") or {}).get("margin_threshold", DEFAULT_MARGIN)
        if self.autonomy == AUTONOMOUS:
            self.result["selected"] = {"rank": 1, "by": "decider", "margin": margin,
                                       "margin_low": margin is not None and margin < threshold}
            self.result["status"] = "selected"
            return self.finish_selected()
        ticket = self._ask_pick(margin)
        raise _Stop("candidates_ranked", "the pick is the owner's under autonomy %s: decision ticket %d asks which rank to finish"
                    % (self.autonomy, ticket))

    def _ask_pick(self, margin):
        ranked = [candidate for candidate in self.result["candidates"] if candidate.get("rank")]
        options = ["rank %d: %s, %g of 20, %s" % (candidate["rank"], candidate["chart_type"], candidate["score"]["total"], candidate["png"])
                   for candidate in ranked]
        evidence = ["rank %d (%s): %s" % (candidate["rank"], candidate["index_id"], candidate["critic_reasons"]) for candidate in ranked]
        if margin is not None:
            evidence.append("rank 1 leads rank 2 by %g; policy.figures.margin_threshold is %g"
                            % (margin, (self.policy.get("figures") or {}).get("margin_threshold", DEFAULT_MARGIN)))
        return self._open(
            "Which candidate should figure %s finish? Answer with its rank (for example: rank 1); `wayline figure resume %s` then "
            "finishes it." % (self.figure_id, self.figure_id),
            options, "rank 1", evidence, _pick_origin(self.figure_id, self.result["version"]),
            "Pick the candidate for figure %s" % self.figure_id, pause=True)

    def _open(self, question, options, recommended, evidence, origin, title, pause):
        pauses = [self.ticket] if pause and self.ticket is not None and self.ticket in _ticket_ids(self.project) else []
        try:
            opened = decisions.open_decision(
                self.project, question, options=options, recommended=recommended, evidence=evidence,
                blocking="subgraph" if pauses else None, human_only=True, pauses=pauses, proposed_by=BY, origin=origin,
                title=title, context_pack=[self.directory + "/" + RESULT_JSON], notify=self.notify)
        except (TicketError, ProjectError, OSError) as failure:
            raise _Stop("blocked", "the decision ticket could not be opened: %s" % failure) from None
        return opened["ticket"]

    def finish_selected(self):
        chosen = next(candidate for candidate in self.result["candidates"] if candidate.get("rank") == self.result["selected"]["rank"])
        start = [
            "- the chosen draft, rank %d of %d, `%s`: %s" % (chosen["rank"], sum(1 for c in self.result["candidates"] if c.get("rank")),
                                                           chosen["index_id"], chosen["chart_type"]),
            "  - its script: `%s`" % chosen["generator"],
            "  - its PNG: `%s`" % chosen["png"],
            "  - the critic's reasons: %s" % _one_line(chosen.get("critic_reasons") or ""),
            "- picked by the %s%s" % (self.result["selected"]["by"],
                                      "; the margin over rank 2 was low, so keep the figure's case plain" if self.result["selected"]["margin_low"] else ""),
        ]
        return self.finish(start)

    def guided(self, overridden=()):
        """A guided revision: the finishing session on the figure as it stands and the change requests (research-notes 11 Section 4.1).

        The figure as it stands is this result's own final figure when an earlier pass drew one (an override pass
        starts from the revision the first pass made, with its applied requests in it), else the one `revision_of` names.
        """
        current = self.result.get("final")
        if current:
            start = ["- the figure as it stands, as the earlier pass of this revision left it:"]
            previous = current
        else:
            start = ["- the figure as it stands, from `%s`:" % self.request["revision_of"]]
            previous = _previous_final(self.project, self.request.get("revision_of"))
        if previous:
            start += ["  - `%s`: `%s`" % (key, previous[key]) for key in ("generator", "pdf", "png", "caption", "notes") if previous.get(key)]
        applied = [item for item in self.request.get("change_requests") or [] if item["id"] in (self.result.get("applied") or [])]
        if overridden and applied:
            start += ["", "Already carried out in it, to keep:"] + ["- `%s`: %s" % (item["id"], item["text"]) for item in applied]
        requests = overridden or self.request.get("change_requests") or []
        start += ["", "The change requests:" if not overridden else "The requests the owner overrode:"]
        start += ["- `%s` (from %s): %s" % (item["id"], item.get("from", "human"), item["text"]) for item in requests]
        return self.finish(start, overridden=overridden)

    def finish(self, start, overridden=()):
        self.paths = _final_paths(self.directory, self.figure_id)
        self.overridden = list(overridden)
        request, role = self._launch_request(DESIGNER, "", FINISH_SCHEMA, self.directory + "/")
        request.prompt = self.finish_prompt(start, role, overridden)
        guided = self.request["mode"] == "guided"
        asked = [item["id"] for item in (overridden or self.request.get("change_requests") or [])] if guided else []
        overridden_ids = {item["id"] for item in overridden}
        data = {entry["path"] for entry in self.request["data"]}

        def check(value):
            problems = []
            refused = [refusal["change_request"] for refusal in value["refusals"]]
            if value["drew_final"]:
                for key in ["generator", "caption", "notes"] + list(self.request["target"]["formats"]):
                    if not self._inside_file(self.paths[key]):
                        problems.append("the %s is not at %s" % (key, self.paths[key]))
                if not value["inputs"]:
                    problems.append("inputs is empty: name the data files the figure draws")
            elif not guided or not asked or set(refused) != set(asked) or value["applied"]:
                problems.append("drew_final is false, which only a guided revision whose every request was refused may say")
            unknown = [entry["path"] for entry in value["inputs"] if entry["path"] not in data]
            if unknown:
                problems.append("inputs names %s, which the request's data does not list" % ", ".join(unknown))
            for key in refused + list(value["applied"]):
                if key not in asked:
                    problems.append("%r is not one of the change requests handed to you" % key)
            both = set(refused) & set(value["applied"])
            if both:
                problems.append("%s is both applied and refused" % ", ".join(sorted(both)))
            untouched = [key for key in asked if key not in refused and key not in value["applied"]]
            if untouched:
                problems.append("every change request is applied or refused; %s is neither" % ", ".join(untouched))
            if overridden_ids & set(refused):
                problems.append("a request the owner overrode is refused again; carry it out as asked")
            return problems

        self._finish_check = check
        envelope, value = self._converse(request, "the designer's finish", check)
        self._take_finish(value)
        if not value["drew_final"]:
            raise _Stop("refused", "every change request was refused; the owner may override each through its decision ticket")
        self.run_checks(request, envelope)
        return self.honesty()

    def _take_finish(self, value):
        """What a finish (or its repair) returned, into the result; an override is marked carried out only here."""
        drawn = self._final_from(value) if value["drew_final"] else None  # raises before anything is taken
        for key in ("schematic_elements", "selection_statistics", "findings_for_text"):
            self.result[key] = list(value[key])
        self.result["traps_hit"] = list(self.result.get("traps_hit") or []) + [trap for trap in value["traps_hit"]
                                                                                if trap not in (self.result.get("traps_hit") or [])]
        self.equations = list(value["equations"])
        self.prior_verdicts = {}  # a new drawing: no sub-verdict taken on an earlier one stands for it
        refused_now = {refusal["change_request"] for refusal in value["refusals"]}
        refusals = [refusal for refusal in self.result.get("refusals") or []
                    if refusal["overridden_by"] or refusal["change_request"] not in refused_now]
        candidates = self.result.setdefault("candidates", [])
        for refusal in value["refusals"]:
            alternative = refusal["alternative_png"] if self._inside_file(refusal["alternative_png"]) else None
            refusals.append({"change_request": refusal["change_request"], "reason": refusal["reason"],
                             "alternative_candidate": alternative, "overridden_by": None})
            identifier = "alternative-%s" % refusal["change_request"]
            candidates[:] = [candidate for candidate in candidates if candidate["index_id"] != identifier]
            if alternative:
                candidates.append({
                    "rank": None, "index_id": identifier,
                    "chart_type": "the nearest honest alternative to change request %s" % refusal["change_request"],
                    "library": self.request["target"]["library"],
                    "generator": refusal["alternative_generator"] if self._inside_file(refusal["alternative_generator"]) else None,
                    "png": alternative, "rendered": True, "pitfalls_consulted": []})
        if not candidates:
            del self.result["candidates"]
        for item in self.overridden:
            for refusal in refusals:
                if refusal["change_request"] == item["id"] and not refusal["overridden_by"]:
                    refusal["overridden_by"] = item["by"]
        self.result["refusals"] = refusals
        self.result["applied"] = sorted(set(self.result.get("applied") or []) | set(value["applied"]) | {item["id"] for item in self.overridden})
        for refusal in value["refusals"]:
            self._ask_override(refusal)
        if drawn is not None:
            self.result["final"] = drawn
            if self.overridden:
                self._record_overrides(self.overridden)

    def _final_from(self, value):
        """The `final` block of a drawn figure; the run stops when a data file changed since the request named it."""
        by_path = {entry["path"]: entry for entry in self.request["data"]}
        manifest = {entry["path"]: entry for entry in read_manifest(self.project).get("entries", [])}
        inputs = []
        for entry in value["inputs"]:
            declared = by_path[entry["path"]]
            path = self.project / entry["path"]
            digest = sha256_of(path) if path.is_file() else None
            if digest != declared["sha256"]:
                raise _Stop("blocked", "%s changed while the figure was drawn (its sha256 is not the one the request names), "
                                       "so the figure would not show the run it names" % entry["path"])
            run_id = declared.get("run_id") or (manifest.get(entry["path"]) or {}).get("run_id") or "unmanifested"
            item = {"path": entry["path"], "sha256": digest, "run_id": run_id}
            if entry.get("panels"):
                item["panels"] = list(entry["panels"])
            inputs.append(item)
        formats = self.request["target"]["formats"]
        return {"generator": self.paths["generator"], "pdf": self.paths["pdf"] if "pdf" in formats else None,
                "png": self.paths["png"] if "png" in formats else None,
                "caption": self.paths["caption"], "notes": self.paths["notes"], "crops": [], "inputs": inputs}

    def _ask_override(self, refusal):
        text = next((item["text"] for item in self.request.get("change_requests") or [] if item["id"] == refusal["change_request"]), "")
        self._open(
            "The figure role refused change request %s of figure %s (\"%s\") because: %s. Only the owner can override it: answer "
            "\"%s\" or \"%s\"; `wayline figure resume %s` then carries out an override." % (
                refusal["change_request"], self.figure_id, _one_line(text), _one_line(refusal["reason"]), KEEP, OVERRIDE_OPTION, self.figure_id),
            [KEEP, OVERRIDE_OPTION], KEEP,
            ["the nearest honest alternative: %s" % (refusal["alternative_png"] or "none was possible")],
            _refusal_origin(self.figure_id, self.result["version"], refusal["change_request"]),
            "Override the refusal of %s on figure %s?" % (refusal["change_request"], self.figure_id), pause=False)

    def _record_overrides(self, overridden):
        """The override, in the caption and the notes, in the harness's own words (research-notes 11 Section 4.1)."""
        for key in ("caption", "notes"):
            path = self.project / self.paths[key]
            text = path.read_text(encoding="utf-8").rstrip("\n")
            for item in overridden:
                line = ("Drawn at the owner's direction, overriding the figure role's refusal of change request %s (%s), "
                        "refused because: %s." % (item["id"], _one_line(item["text"]).rstrip("."), _one_line(item["reason"]).rstrip(".")))
                if line not in text:
                    text += "\n\n" + line
            path.write_text(text + "\n", encoding="utf-8")

    def run_checks(self, request, envelope):
        checks = self._checks()
        if not all(check["pass"] for check in checks):
            failed = "\n".join("- %s: %s" % (check["id"], check["detail"]) for check in checks if not check["pass"])
            self.say("  figure %s: %d machine check(s) failed; back to the designer once" % (self.figure_id, sum(1 for c in checks if not c["pass"])))
            _, value = self._converse(request, "the designer's repair", self._finish_check, envelope=envelope, message=REPAIR_CHECKS % failed)
            if not value["drew_final"]:
                raise _Stop("failed_checks", "the repair drew no figure, and the machine checks still fail: %s"
                            % ", ".join(check["id"] for check in checks if not check["pass"]))
            self._take_finish(value)
            checks = self._checks()
        if not all(check["pass"] for check in checks):
            raise _Stop("failed_checks", "%d machine check(s) failed after one repair: %s" % (
                sum(1 for check in checks if not check["pass"]), ", ".join(check["id"] for check in checks if not check["pass"])))

    def _checks(self):
        """The machine checks on the final figure, with its crops made fresh: none left from an earlier drawing is read."""
        shutil.rmtree(self.project / self.directory / "crops", ignore_errors=True)
        checks = self.checks(self.project, self.request, self.result, policy=self.policy.get("figures") or {})
        self.result["checks"] = checks
        crops = sorted((self.project / self.directory / "crops").glob("*.png"))
        self.result["final"]["crops"] = [path.relative_to(self.project).as_posix() for path in crops]
        return checks

    def _report(self, sub):
        """`checks.json`, the check report the verdict reads, with the equations and every sub-verdict taken so far."""
        report = self.directory + "/" + CHECKS_JSON
        _write_json(self.project / report, {
            "figure_id": self.figure_id, "version": self.result["version"], "checks": self.result["checks"],
            "schematic_elements": self.result["schematic_elements"], "selection_statistics": self.result["selection_statistics"],
            "refusals": self.result.get("refusals") or [], "equations": self.equations, "equation_verdicts": sub})
        return report

    def honesty(self):
        """The equation sub-verdicts, then the one honesty verdict; each sub-verdict is written down as it is taken.

        A run stopped between them (a window, a held verdict) leaves the sub-verdicts it took in `checks.json`, and
        `resume_figure` takes up from there: a failed sub-verdict still fails the figure, and none is taken twice.
        """
        prior = getattr(self, "prior_verdicts", {}) or {}
        owed = [equation for equation in self.equations if equation["id"] not in prior]
        budget = (self.request.get("budget") or {}).get("verifier_sessions")
        if budget is not None and budget < 1 + len(owed):
            raise _Stop("blocked", "the honesty verdict and %d equation sub-verdict(s) need %d verifier session(s); the budget allows %d"
                        % (len(owed), 1 + len(owed), budget))
        final = self.result["final"]
        final["output_sha256"] = {fmt: sha256_of(self.project / final[fmt]) for fmt in ("pdf", "png") if final.get(fmt)}
        sub = [prior[equation["id"]] for equation in self.equations if equation["id"] in prior]
        report = self._report(sub)
        for equation in owed:
            verdict = self._verdict(
                "%s#%s" % (self.directory, equation["id"]), EQUATION_QUESTION % (equation["drawn"], equation["implementation"]),
                [final["generator"], equation["implementation"]], EQUATION_SCOPE, gates.EQUATION_MATCH)
            sub.append({"equation": equation["id"], "pass": verdict.passed, "session": verdict.session_id,
                        "findings": [finding.get("text") for finding in verdict.findings]})
            report = self._report(sub)
        by_id = {item["equation"]: item for item in sub}
        mismatches = []
        for equation in self.equations:
            item = by_id[equation["id"]]
            if not item["pass"]:
                mismatches.append({"rule": "equation_mismatch", "locator": equation["implementation"], "text": "equation %s (%s) does not match %s: %s" % (
                    equation["id"], equation["drawn"], equation["implementation"],
                    "; ".join(text for text in item["findings"] if text) or "the sub-verdict failed without a finding")})
        paths = list(final["crops"]) + [final[key] for key in ("png", "pdf", "caption", "notes") if final.get(key)]
        paths += [self.directory + "/" + REQUEST_JSON, report] + [entry["path"] for entry in final["inputs"]]
        spec = self.project / "research" / "SPEC.md"
        if spec.is_file():
            paths.append("research/SPEC.md")
        verdict = self._verdict(self.directory, HONESTY_QUESTION, paths, HONESTY_SCOPE, gates.FIGURE_HONESTY)
        findings = mismatches + [_honesty_finding(finding) for finding in verdict.findings]
        passed = verdict.passed and not mismatches
        self.result["honesty_verdict"] = {"type": "B", "verdict": "pass" if passed else "fail", "session": verdict.session_id,
                                          "model": verdict.model, "findings": findings}
        self.result["status"] = "verified" if passed else "honesty_failed"
        return None

    def _verdict(self, subject, question, paths, scope, verdict_type):
        try:
            verdict = gates.verdict("figure", subject, question, paths, scope, project=self.project,
                                    author_model=self.designer_model, verdict_type=verdict_type, ticket=self.ticket,
                                    harness_root=self.harness_root, policy=self.policy)
        except gates.FableHeld as held:
            raise _Stop("blocked", "the %s verdict waits for Fable's weekly window: %s" % (verdict_type, held)) from None
        except gates.UsageLimited as refused:
            raise _Stop("blocked", str(refused)) from None
        except (gates.GateError, worker.LaunchError) as failure:
            raise _Stop("blocked", "the %s verdict could not be taken: %s" % (verdict_type, failure)) from None
        self._record_session(VERIFIER, worker.Envelope(session_id=verdict.session_id))
        return verdict

    def _inside_file(self, relative):
        """Whether `relative` is a file under the figure's directory."""
        if not relative:
            return False
        path = (self.project / relative).resolve()
        root = (self.project / self.directory).resolve()
        return root in path.parents and path.is_file()


def _honesty_finding(finding):
    text = str(finding.get("text") or "").strip()
    found = _RULE_PREFIX.match(text)
    rule = found.group(1) if found and found.group(1) in HONESTY_RULES else "implied_claim"
    body = text[found.end():].strip() if found and found.group(1) in HONESTY_RULES else text
    return {"rule": rule, "text": body or text or "no text was given", "locator": finding.get("locator")}


def _python_spelling(project):
    """How the designer runs Python: the project's `.venv/bin/python` when it has one, else `python3`.

    `figure_checks.Tools.python_for` makes the same choice for the clean room, and the designer's `Bash(...)` rules
    allow exactly these two spellings, not an absolute path to an interpreter.
    """
    return ".venv/bin/python" if (Path(project) / ".venv" / "bin" / "python").exists() else "python3"


def _describe_shape(shape):
    if not shape:
        return "shape not classified"
    structure = shape.get("structure")
    if structure == "table":
        columns = ", ".join("%s (%s, %d distinct)" % (column["name"], column["type"], column["cardinality"]) for column in shape["columns"][:20])
        more = " and %d more" % (len(shape["columns"]) - 20) if len(shape["columns"]) > 20 else ""
        under = " under the key `%s`" % shape["records_under"] if shape.get("records_under") else ""
        return "a table of %d rows%s: %s%s" % (shape["rows"], under, columns, more)
    if structure == "matrix":
        return "a %d by %d numeric matrix" % (shape["rows"], shape.get("width", 0))
    if structure == "nested":
        return "a nested record with the keys %s" % ", ".join(shape.get("keys") or [])
    return structure or "unknown"


def _check_contract(request):
    """What the 19 checks read, said once so the finishing session can meet them (ticket 49)."""
    target = request["target"]
    lines = [
        "- every font embedded and none Type 3; the page exactly %s mm wide (within 0.5 mm)%s" % (
            target["width_mm"], " and at most %s mm tall" % target["max_height_mm"] if target.get("max_height_mm") else ""),
        "- no text under %s pt at that width; every raster at %s dpi or more" % (target["min_font_pt"], target["min_dpi"]),
        "- the generator passes `ruff check --select F401,F841`, runs with `python -I` from a directory holding only itself, "
        "the data files it draws, and the house style, and regenerates the same image (SSIM 0.99): seed any randomness, read no other file",
        "- the caption has a `(a)`, `(b)` entry for exactly the panels the figure letters, no em dash, no British spelling%s" % (
            ", and a forward reference (\"see also Figure N\")" if request["kind"] != "result" else ""),
        "- colors from the house style only, one ramp per quantity, structure in grey, required and optional by line style",
        "- a panel drawn from two data files says so in the caption (`%s`); every schematic element is named in the caption and "
        "the notes, and marked `# schematic:` in the generator" % figure_checks.MIXED_DATA_MARKER,
    ]
    if request["register"] == "conceptual":
        lines.append("- the conceptual register: no digits, gene names, or dataset names anywhere in the figure's text")
    if target.get("max_words"):
        lines.append("- at most %d words in the figure" % target["max_words"])
    if target["library"] == "matplotlib":
        lines.append("- the checks read the figure's artists, so mark what code cannot infer with a matplotlib `gid`: `panel:<letter>` "
                     "on each panel's axes, `quantity:<name>` on a colormapped artist, `required:<name>` or `optional:<name>` on an "
                     "edge or curve, `connector:<name>` or `container:<name>` on structure; set `pdf.fonttype` to 42")
    return lines


def _prompt(lines, role, section, schema):
    parts = ["\n".join(lines).rstrip()]
    protocol = worker.protocol_for(role.protocol, section) if section else role.protocol
    if protocol.strip():
        parts.append(protocol.strip())
    parts.append(worker.schema_section("# What you return", schema))
    return "\n\n".join(parts) + "\n"


# --- the files, the journal, and what leaves the role -------------------------------------------------


def _one_line(text):
    return _SPACES.sub(" ", str(text)).strip()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _final_paths(directory, figure_id):
    base = "%s/%s" % (directory, figure_id)
    return {"generator": base + ".py", "pdf": base + ".pdf", "png": base + ".png",
            "caption": directory + "/caption.md", "notes": directory + "/notes.md"}


def _previous_final(project, revision_of):
    """The `final` block a guided revision starts from: a figure_result's, or the files beside a final PDF."""
    if not revision_of:
        return None
    value = _read_json(Path(project) / revision_of)
    if isinstance(value, dict) and isinstance(value.get("final"), dict):
        return value["final"]
    return None


def _ticket_id(request):
    text = str(request.get("ticket") or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def _ticket_ids(project):
    try:
        return {ticket["id"] for ticket in read_tickets(project)}
    except (TicketError, OSError):
        return set()


def _pick_origin(figure_id, version):
    return "figure %s v%d: pick" % (figure_id, version)


def _refusal_origin(figure_id, version, change_request):
    return "figure %s v%d: refusal %s" % (figure_id, version, change_request)


def _answered(project, origin):
    """`(ticket, answer)` for the decision ticket opened under `origin`: the answer the journal holds, or None."""
    found = [ticket for ticket in read_tickets(project) if ticket.get("origin") == origin]
    if not found:
        return None, None
    identifier = found[0]["id"]
    events, _ = Ledger(project).read_events()
    return identifier, replay(events).answers.get(identifier)


def _clean(result):
    """The result as the schema has it: the candidates' working fields dropped, None-valued optionals left out."""
    out = dict(result)
    candidates = []
    for candidate in result.get("candidates") or []:
        entry = {key: candidate[key] for key in ("rank", "index_id", "chart_type", "library", "generator", "png", "rendered",
                                                 "error", "pitfalls_consulted", "score", "critic_reasons") if key in candidate}
        if entry.get("rendered"):
            entry.pop("error", None)
        candidates.append(entry)
    if "candidates" in result:
        out["candidates"] = candidates
    return out


def write_result(project, result, reason=None, notify=None, policy=None, harness_root=None):
    """Validate, write, and journal one result; then file what it hands the proposals and the evolve loop."""
    project = Path(project).resolve()
    result = _clean(result)
    problems = validate(result, load_schema(RESULT_SCHEMA))
    if problems:
        raise FigureError("the figure role built a result figure_result/1 refuses: %s" % "; ".join(
            "%s: %s" % (error.path, error.message) for error in problems[:5]))
    relative = "%s/%s/%s" % (FIGURES, result["figure_id"], RESULT_JSON)
    _write_json(project / relative, result)
    payload = {"figure_id": result["figure_id"], "version": result["version"], "path": relative,
               "sha256": sha256_of(project / relative), "status": result["status"]}
    if reason:
        payload["reason"] = _one_line(reason)[:500]
    Ledger(project).append_event(FIGURE_RESULT, payload, ticket=_ticket_id(result))
    _hand_on(project, result, notify=notify, policy=policy, harness_root=harness_root)
    return result


def _hand_on(project, result, notify=None, policy=None, harness_root=None):
    """`findings_for_text` become proposals; promotable traps go to the evolve loop as feedback."""
    from wayline import changes, proposals  # both import much of the harness; only a result that carries these needs them

    findings = result.get("findings_for_text") or []
    if findings:
        asked = [{"title": "Revise the text figure %s bears on: %s" % (result["figure_id"], _one_line(finding["text"])[:60]),
                  "kind": "writing", "radius": "moderate",
                  "why": "%s%s (figure %s, figures/%s/%s)" % (_one_line(finding["text"]).rstrip(".") + ".",
                                                              " At %s." % finding["manuscript_locator"] if finding.get("manuscript_locator") else "",
                                                              result["figure_id"], result["figure_id"], RESULT_JSON)}
                 for finding in findings]
        try:
            proposals.admit_proposals(project, asked, origin_ticket=_ticket_id(result),
                                      origin_prefix="figure %s v%d" % (result["figure_id"], result["version"]),
                                      proposed_by=BY, policy=policy, harness_root=harness_root, notify=notify)
        except (ProjectError, proposals.ProposalsError, TicketError, OSError) as failure:
            print("wayline figure: the findings for the text could not be proposed: %s" % failure, file=sys.stderr)
    traps = [trap for trap in result.get("traps_hit") or [] if trap.get("promote_to_index")]
    if traps and result["status"] not in ("candidates_ranked", "selected"):
        text = _traps_text(result, traps)
        digest = hashlib.sha256(json.dumps(traps, sort_keys=True).encode("utf-8")).hexdigest()[:8]
        changes.file_from_figure(project, text, "figure-%s-v%d-%s" % (result["figure_id"], result["version"], digest))


def _traps_text(result, traps):
    lines = ["# Traps figure %s would promote into the plot index" % result["figure_id"], "",
             "The figure role hit %d library trap(s) the plot index did not name, recorded in `figures/%s/%s` (version %d). "
             "Fold them into `figures/plot_index.json` with `wayline figures fold-traps figures/%s/%s`, which matches each to "
             "its entry by chart type and library and adds it to that entry's `known_pitfalls`." % (
                 len(traps), result["figure_id"], RESULT_JSON, result["version"], result["figure_id"], RESULT_JSON), ""]
    for trap in traps:
        lines.append("- %s, %s: %s Fix: %s" % (trap["library"], trap["chart_type"], _one_line(trap["description"]), _one_line(trap["fix"])))
    return "\n".join(lines) + "\n"


def read_result(project, figure_id):
    """`figures/<figure_id>/figure_result.json`, or None when the figure has none."""
    return _read_json(Path(project) / FIGURES / figure_id / RESULT_JSON)


# --- the entry points ----------------------------------------------------------------------------------


def _autonomy(project, autonomy):
    if autonomy is not None:
        return autonomy
    try:
        return read_harness(project).get("autonomy") or "checkpoints"
    except (ProjectError, OSError, ValueError):
        return "checkpoints"


def _check_request(request):
    if not isinstance(request, dict):
        raise FigureError("a figure request is a JSON object, got %s" % type(request).__name__)
    problems = validate(request, load_schema(REQUEST_SCHEMA))
    if problems:
        raise FigureError("the request is not a figure_request/1: %s" % "; ".join("%s: %s" % (error.path, error.message) for error in problems[:5]))


def _run(project, request, result, harness_root, policy, autonomy, checks, notify, say, step):
    run = _Run(project, request, result, harness_root=harness_root or HARNESS_ROOT, policy=policy, autonomy=autonomy,
               checks=checks or figure_checks.run_checks, notify=notify, say=say or (lambda text: None))
    reason = None
    try:
        run.check_data()
        step(run)
    except _Stop as stop:
        result["status"], reason = stop.status, stop.reason
        if stop.status == "blocked" and result.get("selected") and not result.get("final"):
            result["status"] = "selected"  # picked, and waiting to be finished: `resume_figure` finishes it
            reason = "the pick stands; the finish did not run: %s" % stop.reason
    return write_result(project, result, reason, notify=notify, policy=policy, harness_root=harness_root), reason


def make(project, request, *, harness_root=None, policy=None, autonomy=None, checks=None, notify=None, say=None):
    """Run the figure role on one `figure_request/1`; returns `(figure_result, reason)`.

    `reason` is None when the result is final and says what the figure waits on otherwise (the owner's pick, an
    override, a window), which is also what `figure_result`'s journal event carries. `checks` stands in for
    `figure_checks.run_checks` and `autonomy` for `harness.json`'s; `notify` is the decision tickets' notifier.
    """
    project = Path(project).resolve()
    _check_request(request)
    policy = policy if policy is not None else policy_for(project, harness_root)
    figure_id = request["figure_id"]
    _write_json(project / FIGURES / figure_id / REQUEST_JSON, request)
    previous = read_result(project, figure_id)
    version = (previous.get("version") or 1) + 1 if isinstance(previous, dict) else 1
    result = {"schema": "figure_result/1", "ticket": str(request["ticket"]), "figure_id": figure_id, "version": version,
              "status": "blocked", "sessions": [], "traps_hit": [], "refusals": []}
    if request["mode"] == "guided":
        result["data_shape"] = classify_shape(project, request["data"])
        step = lambda run: run.guided()
    else:
        step = lambda run: run.unguided()
    return _run(project, request, result, harness_root, policy, _autonomy(project, autonomy), checks, notify, say, step)


def resume_figure(project, figure_id, *, harness_root=None, policy=None, autonomy=None, checks=None, notify=None, say=None):
    """Carry on a figure that waited: the owner's pick, the owner's overrides, or a step a window or a failure stopped.

    A stopped figure is taken up at the step it stopped at, and nothing it already has is done again: a held verdict
    is taken with the sub-verdicts already written down, a drawing that failed to finish is finished from its pick,
    and drafts the critic never ranked are ranked. Returns `(figure_result, reason)`; the result is unchanged (and
    nothing is written) when there is nothing to carry on yet, and `reason` then says what it waits on.
    """
    project = Path(project).resolve()
    request = _read_json(project / FIGURES / figure_id / REQUEST_JSON)
    result = read_result(project, figure_id)
    if not isinstance(request, dict) or not isinstance(result, dict):
        raise FigureError("figure %s has no request.json and figure_result.json under figures/%s/ to resume" % (figure_id, figure_id))
    _check_request(request)
    policy = policy if policy is not None else policy_for(project, harness_root)
    autonomy = _autonomy(project, autonomy)
    go = lambda step: _run(project, request, result, harness_root, policy, autonomy, checks, notify, say, step)
    overridden = _overrides(project, request, result)
    if overridden:
        return go(lambda run: run.guided(overridden))
    status = result["status"]
    if status == "candidates_ranked":
        ticket, answer = _answered(project, _pick_origin(figure_id, result["version"]))
        if not answer or answer.get("decided_by") != "human":
            return result, "the pick waits for the owner's answer to decision ticket %s" % ticket
        rank = _rank_of(answer.get("answer"), result)
        if rank is None:
            return result, "the answer to decision ticket %s (%r) names no rank of figure %s" % (ticket, answer.get("answer"), figure_id)
        margin = margin_of(result["candidates"])
        threshold = (policy.get("figures") or {}).get("margin_threshold", DEFAULT_MARGIN)
        result["selected"] = {"rank": rank, "by": "human", "margin": margin, "margin_low": margin is not None and margin < threshold}
        result["status"] = "selected"
        return go(lambda run: run.finish_selected())
    if status == "selected":
        return go(lambda run: run.finish_selected())
    if status == "refused":
        return result, "every change request was refused and no refusal is overridden by the owner"
    if status != "blocked":
        return result, "figure %s is %s; a change to it is a guided revision (a new request with revision_of)" % (figure_id, status)
    if result.get("final") and result.get("checks") and all(check["pass"] for check in result["checks"]):
        return go(lambda run: _verdict_again(run, figure_id))
    if request["mode"] == "guided":
        return go(lambda run: run.guided())
    if result.get("selected"):
        return go(lambda run: run.finish_selected())
    ranked = [candidate for candidate in result.get("candidates") or [] if candidate.get("rank")]
    if ranked:
        return go(lambda run: run.pick())
    if any(candidate.get("rendered") for candidate in result.get("candidates") or []):
        return go(lambda run: run.rank_and_pick())
    return make(project, request, harness_root=harness_root, policy=policy, autonomy=autonomy, checks=checks,
                notify=notify, say=say)


def _verdict_again(run, figure_id):
    """The verdicts of a figure whose checks passed, taken up from what `checks.json` wrote down."""
    run.paths = _final_paths(run.directory, figure_id)
    report = _read_json(run.project / run.directory / CHECKS_JSON) or {}
    if report.get("version") != run.result["version"] or not isinstance(report.get("equations"), list):
        raise _Stop("blocked", "checks.json does not hold this version's equations, so its verdicts cannot be taken up; "
                               "a guided revision draws the figure again")
    run.equations = report["equations"]
    run.prior_verdicts = {item["equation"]: item for item in report.get("equation_verdicts") or []}
    return run.honesty()


def _rank_of(text, result):
    ranks = {candidate["rank"] for candidate in result.get("candidates") or [] if candidate.get("rank")}
    found = _RANK.search(str(text or ""))
    if found:
        rank = int(found.group(1) or found.group(2))
        return rank if rank in ranks else None
    for candidate in result.get("candidates") or []:
        if candidate.get("rank") and candidate["index_id"] in str(text or ""):
            return candidate["rank"]
    return None


def _overrides(project, request, result):
    """The refusals the owner overrode and the role has not yet drawn, each with the `by` it is marked with once drawn.

    Only an answer journaled with `decided_by: human` counts. The decision ticket is human-only, so the decider
    cannot answer it; an answer recorded as anyone else's is ignored here all the same. Nothing is marked here:
    `overridden_by` is set when the pass that draws the override takes its finish, so a pass a window stops
    leaves the override owed and the next `resume_figure` tries it again.
    """
    texts = {item["id"]: item["text"] for item in request.get("change_requests") or []}
    wanted = []
    for refusal in result.get("refusals") or []:
        if refusal.get("overridden_by"):
            continue
        ticket, answer = _answered(project, _refusal_origin(result["figure_id"], result["version"], refusal["change_request"]))
        if not answer or answer.get("decided_by") != "human":
            continue
        if not str(answer.get("answer") or "").strip().lower().startswith(OVERRIDE):
            continue
        wanted.append({"id": refusal["change_request"], "text": texts.get(refusal["change_request"], ""), "reason": refusal["reason"],
                       "from": "human", "by": "human (decision ticket %d)" % ticket})
    return wanted


# --- the verb ---------------------------------------------------------------------------------------


def figure_command(args):
    """`wayline figure make <request.json>` and `wayline figure resume <figure_id>`."""
    parser = argparse.ArgumentParser(prog="wayline figure", description="the figure role: ranked candidates, a pick, a checked and verdicted figure")
    parser.add_argument("action", choices=("make", "resume"))
    parser.add_argument("target", help="make: the figure_request/1 file; resume: the figure's id")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the figure_result as JSON")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    say = lambda text: print(text, flush=True)
    try:
        project = find_project(options.project)
        if options.action == "make":
            request = _read_json(Path(options.target))
            if request is None:
                raise FigureError("%s is not a readable JSON file" % options.target)
            result, reason = make(project, request, say=say)
        else:
            result, reason = resume_figure(project, options.target, say=say)
    except (ValueError, KeyError, worker.RoleError, OSError) as failure:  # FigureError, ProjectError, and an unreadable index are ValueErrors
        print("wayline figure: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2) if options.json else _render(result, reason))
    return 0 if result["status"] in ("verified", "candidates_ranked", "selected") else 3


def _render(result, reason):
    lines = ["figure %s, version %d: %s" % (result["figure_id"], result["version"], result["status"])]
    for candidate in result.get("candidates") or []:
        if candidate.get("rank"):
            lines.append("  rank %d  %-5g %s (%s)" % (candidate["rank"], candidate["score"]["total"], candidate["chart_type"], candidate["png"]))
        elif not candidate.get("rendered"):
            lines.append("  -       did not render: %s (%s)" % (candidate["index_id"], candidate.get("error")))
    selected = result.get("selected")
    if selected:
        lines.append("  picked rank %d by the %s%s" % (selected["rank"], selected["by"], ", margin low" if selected["margin_low"] else ""))
    failed = [check["id"] for check in result.get("checks") or [] if not check["pass"]]
    if result.get("checks"):
        lines.append("  checks: %d of %d pass%s" % (len(result["checks"]) - len(failed), len(result["checks"]),
                                                    " (failed: %s)" % ", ".join(failed) if failed else ""))
    verdict = result.get("honesty_verdict")
    if verdict:
        lines.append("  honesty verdict: %s (%s)" % (verdict["verdict"], verdict.get("model")))
        lines.extend("    [%s] %s" % (finding["rule"], finding["text"]) for finding in verdict["findings"])
    for refusal in result.get("refusals") or []:
        lines.append("  refused %s: %s%s" % (refusal["change_request"], refusal["reason"],
                                            ", overridden by %s" % refusal["overridden_by"] if refusal["overridden_by"] else ""))
    if reason:
        lines.append("  %s" % reason)
    return "\n".join(lines)
