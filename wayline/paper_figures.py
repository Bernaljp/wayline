"""Figures at the order (Implementation Decision 17; ticket 116).

At the paper order the figures come from the plots the owner explored and marked, with no panel cap and no splitting
into thin figures.

**The figure plan** (`build`) is code's, from the outline (`outline.paper_structure`) and `research/plots.json` with the
owner's marks, with no model call. Each main-text result gets one figure (`F<n>`, in the outline's order) whose panels
are every current plot marked keep, or, when none of its plots is marked keep, every plot its last drawing's synthesis
cites (by its id, `R4.3`, or by its file, `p3.png`) that the owner did not mark maybe. Its other current plots, maybe
and unmarked, go to its supplementary figure (`S<n>`); a result the outline places in the supplement has only that one;
a drop-marked plot never appears, and is listed as left out. Tables follow the same rule apart: a chosen table is a
numbered table (`T<n>`) and the others supplementary ones (`ST<n>`), each rendered from its CSV. A venue's display-item
limit (`figure_spec.max_count` of the venue named, figures and tables together) moves the last results in outline order
to the supplement, each listed. A main-text result with no plot kept or cited gets no figure: a figure from nothing is
made only on the owner's request (its item's mark) or the venue's requirement, and no vendored venue states one.

**The batch.** The plan joins the order's batch (`batch_items`, ticket 115's `paper.batch_items`): one item per planned
figure showing its panels and its supplementary figure (as planned, or to the supplement), one per figure too large for
one page (`PANELS_PER_PAGE` panels; split, the default, or drop the panels past the page to its supplementary figure),
and one per main-text result with no figure (no figure, the default, or a figure from nothing). Under `autonomous` no
batch is asked, code's defaults stand until the decider answers it (ticket 120), and an oversized figure is split
whoever answered: it never drops. A split figure is consecutive figures of the same result, each within a page.

**The figures** (`make_figures`): each planned figure is one `figure_request/1` in the figure role's planned mode
(`figure_role.make`), whose two sessions finish every panel in the library its drawing was drawn in, write the caption,
run the checks (the five readability checks and the composed-panels check among them), and give the honesty verdict.
A figure whose plan key (its result, its panels, and the files of their drawings) is the previous version's and was
verified is reused with no session. `write` copies each into `research/paper/figures/F<n>/` or `S<n>/` with its
`caption.md` (a marked placeholder for one not made), writes the plan's tables under `tables/`, and returns the
record's `figures` block, whose plan lines `PAPER.md` prints.
"""

import csv
import hashlib
import io
import json
import re
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.ledger import PAPER_STARTED, ledger_for

__all__ = [
    "PANELS_PER_PAGE", "AS_PLANNED", "TO_SUPPLEMENT", "SPLIT", "DROP", "NO_FIGURE", "FROM_NOTHING", "is_figure_ref",
    "build", "batch_items", "plan_lines", "request_for", "figure_id", "make_figures", "write", "label", "writer_lines",
    "report_lines", "display_limit",
]

PANELS_PER_PAGE = 9  # a full-width figure on one page: three rows of three panels at 180 mm by 170 mm
AS_PLANNED, TO_SUPPLEMENT = "as planned", "to the supplement"
SPLIT, DROP = "split", "drop"
NO_FIGURE, FROM_NOTHING = "no figure", "a figure from nothing"
FIGURE, OVERSIZED, NOTHING = "figure:", "oversized:", "nothing:"
KEEP, MAYBE, DROP_MARK = "keep", "maybe", "drop"
FIGURES_DIR = "figures"                  # research/paper/figures/F<n>/ and S<n>/
TABLES_DIR = "tables"
PAPER_TICKET = "paper"
NOT_MADE = "[FIGURE NOT MADE: %s]"

_RESULT = re.compile(r"^R[1-9][0-9]*$")
_PLOT_ID = re.compile(r"\bR[1-9][0-9]*\.T?[1-9][0-9]*\b")
_NUMBER = re.compile(r"^(R[1-9][0-9]*)\.(T?)([1-9][0-9]*)$")


def _one_line(text):
    return " ".join(str(text or "").split())


def _order(identifier):
    found = _NUMBER.match(str(identifier))
    return (int(found.group(1)[1:]), bool(found.group(2)), int(found.group(3))) if found else (0, True, 0)


def is_figure_ref(ref):
    """Whether a batch item's ref is one of the figure plan's."""
    return str(ref).startswith((FIGURE, OVERSIZED, NOTHING))


# --- what the plan reads ----------------------------------------------------------------------------------------------


def _last_drawing(book, result_id):
    from wayline import drawings
    return drawings.last_accepted(book, result_id)


def _cited(record):
    """The plot ids a drawing's synthesis cites, by id or by the name of the file it drew."""
    synthesis = str((record or {}).get("synthesis") or "")
    found = set(_PLOT_ID.findall(synthesis))
    for entry in list((record or {}).get("plots") or []) + list((record or {}).get("tables") or []):
        for key in ("png", "svg", "csv"):
            name = Path(str(entry.get(key) or "")).name
            if name and re.search(r"(?<![\w.-])%s(?![\w-])" % re.escape(name), synthesis):
                found.add(entry.get("id"))
    return found


def display_limit(venue):
    """`(slug, max_count)` of a venue's display-item limit, `(slug, None)` where it states none or cannot be read."""
    if not venue:
        return None, None
    from wayline import guidelines
    try:
        spec = guidelines.read_guidelines(HARNESS_ROOT, venue).get("figure_spec") or {}
    except (guidelines.GuidelinesError, OSError, ValueError):
        return venue, None
    return venue, spec.get("max_count")


def _venue_named(book):
    """The venue last named for the paper, as the outline reads it; None while none is."""
    events, _ = book.read_events()
    return next((event["payload"].get("venue") for event in reversed(events)
                 if event.get("event") == PAPER_STARTED and (event.get("payload") or {}).get("venue")), None)


# --- the plan ---------------------------------------------------------------------------------------------------------


def _choose(items, cited):
    """`(chosen, rest, how)`: the keep-marked items, or with none, those the synthesis cites and the owner did not mark maybe."""
    kept = [item["id"] for item in items if item.get("mark") == KEEP]
    if kept:
        chosen, how = kept, "marked keep"
    else:
        chosen, how = [item["id"] for item in items if item["id"] in cited and item.get("mark") != MAYBE], "cited by the synthesis"
    return chosen, [item["id"] for item in items if item["id"] not in chosen], how


def _base(book):
    """Per result in the outline's order: `{result, heading, main, panels, rest, how, tables, rest_tables, dropped}`."""
    from wayline import drawings, outline
    structure = outline.paper_structure(book)
    placed = [(entry["key"], entry["heading"], True) for entry in structure.get("results") or [] if _RESULT.match(entry["key"])]
    placed += [(entry["key"], entry["heading"], False) for entry in structure.get("supplement") or [] if _RESULT.match(entry["key"])]
    plots = [plot for plot in drawings.read_plots(book)["plots"] if plot.get("status") == drawings.CURRENT]
    found, seen = [], set()
    for result_id, heading, main in placed:
        if result_id in seen:
            continue
        seen.add(result_id)
        mine = sorted([plot for plot in plots if plot.get("result") == result_id], key=lambda plot: _order(plot["id"]))
        cited = _cited(_last_drawing(book, result_id))
        dropped = [plot["id"] for plot in mine if plot.get("mark") == DROP_MARK]
        figures = [plot for plot in mine if plot.get("kind") == "plot" and plot.get("mark") != DROP_MARK]
        tables = [plot for plot in mine if plot.get("kind") == "table" and plot.get("mark") != DROP_MARK]
        if main:
            panels, rest, how = _choose(figures, cited)
            chosen_tables, rest_tables, _ = _choose(tables, cited)
        else:
            panels, rest, how = [], [plot["id"] for plot in figures], "placed in the supplement by the outline"
            chosen_tables, rest_tables = [], [plot["id"] for plot in tables]
        found.append({"result": result_id, "heading": heading, "main": main, "panels": panels, "rest": rest, "how": how,
                      "tables": chosen_tables, "rest_tables": rest_tables, "dropped": dropped,
                      "marks": {plot["id"]: plot.get("mark") for plot in mine}})
    return found


def _split(panels, per_page):
    count = -(-len(panels) // per_page)
    size = -(-len(panels) // count)
    return [panels[start:start + size] for start in range(0, len(panels), size)]


def build(project, answers=(), *, autonomous=False, venue=None, limit=None, panels_per_page=PANELS_PER_PAGE):
    """The figure plan, code's with no model call (the module's docstring), following `answers` (`[{ref, mark, by}]`, the
    order's) where they name a figure item and code's defaults elsewhere.

    `venue` is the venue whose display-item limit applies, the one last named by default; `limit` states one outright.
    Returns `{venue, limit, figures, supplementary, tables, left_out, moved, without, oversized}`: each figure
    `{id, result, heading, main, panels, how, part, parts, from_nothing, line}`, each table `{id, result, plot, main, csv,
    caption}`, and `left_out` `[{what, why}]`.
    """
    book = ledger_for(project)
    given = {answer["ref"]: answer for answer in answers or [] if is_figure_ref(answer.get("ref"))}
    if venue is None and limit is None:
        venue = _venue_named(book)
    if limit is None:
        venue, limit = display_limit(venue)
    rows = _base(book)
    left_out, oversized, without = [], [], []
    for row in rows:
        left_out += [{"what": "%s, a plot of %s" % (identifier, row["result"]), "why": "the owner marked it drop"} for identifier in row["dropped"]]
        row["figures"], row["from_nothing"] = [], False
        if not row["main"]:
            continue
        mark = (given.get(FIGURE + row["result"]) or {}).get("mark") or AS_PLANNED
        if mark == TO_SUPPLEMENT and row["panels"]:
            left_out.append({"what": "Figure of %s" % row["result"], "why": "moved to its supplementary figure at the order (%s)"
                             % (given[FIGURE + row["result"]].get("by") or "owner")})
            row["rest"], row["panels"] = row["panels"] + row["rest"], []
        if not row["panels"]:
            asked = (given.get(NOTHING + row["result"]) or {}).get("mark") or NO_FIGURE
            if asked == FROM_NOTHING:
                row["from_nothing"] = True
                row["figures"] = [[]]
            else:
                without.append(row["result"])
                left_out.append({"what": "a figure of %s" % row["result"],
                                 "why": "no plot of it is marked keep or cited by its synthesis; a figure from nothing only on request"})
            continue
        if len(row["panels"]) > panels_per_page:
            oversized.append(row["result"])
            answer = given.get(OVERSIZED + row["result"]) or {}
            if answer.get("mark") == DROP and not autonomous:
                kept, past = row["panels"][:panels_per_page], row["panels"][panels_per_page:]
                left_out.append({"what": "%s from the figure of %s" % (", ".join(past), row["result"]),
                                 "why": "too large for one page, and the order dropped them to its supplementary figure"})
                row["panels"], row["rest"] = kept, past + row["rest"]
                row["figures"] = [kept]
            else:
                row["figures"] = _split(row["panels"], panels_per_page)
        else:
            row["figures"] = [row["panels"]]
    moved = []
    if limit is not None:
        def items():
            return sum(len(row["figures"]) + len(row["tables"]) for row in rows if row["main"])
        for row in reversed([row for row in rows if row["main"]]):
            if items() <= limit:
                break
            if not row["figures"] and not row["tables"]:
                continue
            moved.append(row["result"])
            row["rest"] = [panel for figure in row["figures"] for panel in figure] + row["rest"]
            row["rest_tables"] = row["tables"] + row["rest_tables"]
            row["figures"], row["tables"], row["from_nothing"] = [], [], False
            left_out.append({"what": "the figures and tables of %s" % row["result"],
                             "why": "moved to the supplement by %s's display-item limit of %d" % (venue or "the venue", limit)})
        moved.reverse()
    figures, supplementary, tables = [], [], []
    for row in rows:
        for part, panels in enumerate(row["figures"], start=1):
            figures.append({"id": "F%d" % (len(figures) + 1), "result": row["result"], "heading": row["heading"], "main": True,
                            "panels": list(panels), "how": "a figure from nothing, on request" if row["from_nothing"] else row["how"],
                            "part": part, "parts": len(row["figures"]), "from_nothing": row["from_nothing"]})
        tables += [{"id": "T%d" % (len([t for t in tables if t["main"]]) + 1), "result": row["result"], "plot": plot, "main": True}
                   for plot in row["tables"]]
    for row in rows:
        if row["rest"]:
            supplementary.append({"id": "S%d" % (len(supplementary) + 1), "result": row["result"], "heading": row["heading"],
                                  "main": False, "panels": list(row["rest"]), "how": "its other plots", "part": 1, "parts": 1,
                                  "from_nothing": False})
        tables += [{"id": "ST%d" % (len([t for t in tables if not t["main"]]) + 1), "result": row["result"], "plot": plot, "main": False}
                   for plot in row["rest_tables"]]
    marks = {}
    for row in rows:
        marks.update(row["marks"])
    for figure in figures + supplementary:
        figure["line"] = _line(figure, marks)
    for table in tables:
        table.update(_table_source(book, table["plot"]))
    return {"venue": venue, "limit": limit, "figures": figures, "supplementary": supplementary, "tables": tables,
            "left_out": left_out, "moved": moved, "without": without, "oversized": oversized, "per_page": panels_per_page}


def _line(figure, marks):
    """A figure's plan line: what `PAPER.md` prints and a re-order compares."""
    def named(identifier):
        mark = marks.get(identifier)
        return "%s (%s)" % (identifier, mark) if mark and not figure["main"] else identifier
    part = ", part %d of %d" % (figure["part"], figure["parts"]) if figure["parts"] > 1 else ""
    if figure["from_nothing"]:
        return "%s (%s%s): a figure from nothing, on request" % (figure["id"], figure["result"], part)
    return "%s (%s%s): %s (%s)" % (figure["id"], figure["result"], part, ", ".join(named(item) for item in figure["panels"]), figure["how"])


def _table_source(book, plot_id):
    """A plan table's CSV (relative to the project) and its caption, from the drawing that last drew it."""
    from wayline import drawings
    result_id = plot_id.split(".")[0]
    for record in reversed(drawings.accepted_records(book, result_id)):
        for entry in record.get("tables") or []:
            if entry.get("id") == plot_id:
                return {"csv": entry.get("csv"), "caption": _one_line(entry.get("data_view")) or plot_id}
    return {"csv": None, "caption": plot_id}


def batch_items(project, autonomous=False):
    """The plan's items of the order's batch, `[{ref, text, marks, default}]`, each with code's default: per main-text
    result its figure (with its supplementary figure), a figure too large for one page, or a figure from nothing."""
    plan = build(project, autonomous=autonomous)
    supplementary = {figure["result"]: figure for figure in plan["supplementary"]}
    items = []
    for row in _rows_in_order(plan):
        result, figures = row
        planned = [figure for figure in figures if not figure["from_nothing"]]
        supplement = supplementary.get(result)
        beside = "; its supplementary figure %s" % supplement["line"] if supplement else "; no supplementary figure"
        if planned:
            items.append({"ref": FIGURE + result, "marks": [AS_PLANNED, TO_SUPPLEMENT], "default": AS_PLANNED,
                          "text": "The figure plan for %s: %s%s." % (result, "; ".join(figure["line"] for figure in planned), beside)})
        if result in plan["oversized"]:
            panels = [panel for figure in planned for panel in figure["panels"]]
            past = panels[plan["per_page"]:]
            items.append({"ref": OVERSIZED + result, "marks": [SPLIT, DROP], "default": SPLIT,
                          "text": "The figure of %s holds %d panels, more than one page holds (%d): split it into %d figures of "
                                  "%s, or drop %s past the page to its supplementary figure.%s" % (
                                      result, len(panels), plan["per_page"], len(planned),
                                      " and ".join(str(len(figure["panels"])) for figure in planned) + " panels",
                                      ", ".join(past), " Under autonomous it is split, never dropped." if autonomous else "")})
    from wayline import drawings
    for result in plan["without"]:
        if drawings.last_accepted(project, result) is None:
            continue  # never drawn: the order draws it first, and code's default stands for what that drawing makes
        supplement = supplementary.get(result)
        items.append({"ref": NOTHING + result, "marks": [NO_FIGURE, FROM_NOTHING], "default": NO_FIGURE,
                      "text": "%s has no plot marked keep or cited by its synthesis, so it gets no figure%s. A figure from "
                              "nothing is drawn by the figure role from its data only if you ask." % (
                                  result, " (its plots stand in %s)" % supplement["id"] if supplement else "")})
    return items


def _rows_in_order(plan):
    """`[(result, its main figures)]` for each result with a main figure, in the plan's order."""
    found = []
    for figure in plan["figures"]:
        if not found or found[-1][0] != figure["result"]:
            found.append((figure["result"], []))
        found[-1][1].append(figure)
    return found


# --- the figure role's requests ---------------------------------------------------------------------------------------

WIDTH_MM, PAGE_MM = 180, 170   # a full-width figure, and the full depth of a page
MIN_FONT_PT, MIN_DPI = 5, 300


def figure_id(figure):
    """The figure role's id of a planned figure, `paper-r4-main` (`-2` for a split figure's second part) or
    `paper-r4-supplement`: stable across re-orders, whatever number the figure takes."""
    name = "paper-%s-%s" % (figure["result"].lower(), "main" if figure["main"] else "supplement")
    return name if figure["part"] == 1 else "%s-%d" % (name, figure["part"])


def _panel(book, plot_id):
    """What the figure role starts a panel from: the drawing that last drew the plot, its files, and its library."""
    from wayline import drawings
    plot = next((item for item in drawings.read_plots(book)["plots"] if item.get("id") == plot_id), None) or {}
    for name in reversed(plot.get("drawings") or []):
        try:
            record = book.read_json(drawings.record_path(name))
        except (OSError, ValueError):
            continue
        entry = next((item for item in record.get("plots") or [] if item.get("id") == plot_id), None)
        if entry is not None:
            return {"plot": plot_id, "drawing": name, "library": drawings.library_of_record(record),
                    "chart_type": entry.get("chart_type"), "png": entry.get("png"), "svg": entry.get("svg"),
                    "script": record.get("script"), "purpose": entry.get("purpose"), "shows": entry.get("shows"),
                    "inputs": list(record.get("inputs") or []), "headline": record.get("headline")}
    return None


def _data(book, paths):
    """The request's data entries of the artifacts `paths`, hashed now and with the run the manifest names."""
    from wayline.provenance import read_manifest, sha256_of
    manifest = {entry["path"]: entry for entry in read_manifest(book.project).get("entries", [])}
    found = []
    for path in paths:
        if any(entry["path"] == path for entry in found):
            continue
        target = book.project / path
        found.append({"path": path, "sha256": sha256_of(target) if target.is_file() else "0" * 64,
                      "run_id": (manifest.get(path) or {}).get("run_id")})
    return found


def request_for(project, plan, figure):
    """The `figure_request/1` of one planned figure: the planned mode on its panels, or for a figure from nothing the
    unguided mode on its result's own evidence."""
    from wayline import drawings, figure_checks, results as results_module
    book = ledger_for(project)
    panels = [found for found in (_panel(book, plot) for plot in figure["panels"]) if found is not None]
    libraries = [panel["library"] for panel in panels]
    library = max(libraries, key=libraries.count) if libraries else "matplotlib"
    style = book.project / figure_checks.DEFAULT_STYLE
    try:
        min_font = float(json.loads(style.read_text(encoding="utf-8")).get("min_font_pt") or MIN_FONT_PT)
    except (OSError, ValueError, AttributeError):
        min_font = MIN_FONT_PT
    headline = next((panel["headline"] for panel in panels if panel.get("headline")), None)
    request = {
        "schema": "figure_request/1", "ticket": PAPER_TICKET, "figure_id": figure_id(figure), "kind": "result",
        "register": "quantitative",
        "claim": {"claim_id": figure["result"], "text": _one_line(headline or figure.get("heading") or figure["result"]),
                  "claim_type": "result"},
        "target": {"venue": plan.get("venue"), "width_mm": WIDTH_MM, "max_height_mm": PAGE_MM, "min_font_pt": min_font,
                   "min_dpi": MIN_DPI, "max_words": None, "formats": ["pdf", "png"], "library": library},
    }
    if figure["from_nothing"] or not panels:
        found = {result.id: result for result in results_module.read_results(book)}.get(figure["result"])
        cited = [path for finding in (found.current if found else []) for path in drawings.cited(finding)]
        paths = [str(item).split("#", 1)[0] for item in cited]
        request.update(mode="unguided", data=_data(book, [path for path in paths if (book.project / path).is_file()]))
        return request
    paths = [path for panel in panels for path in panel.pop("inputs")]
    for panel in panels:
        panel.pop("headline", None)
    request.update(mode="planned", panels=panels, data=_data(book, paths))
    return request


def _key(project, request):
    """What a planned figure is made from, hashed: its mode, its panels and the files of their drawings, and its data."""
    from wayline.provenance import sha256_of
    def digest(path):
        target = Path(project) / str(path or "")
        return sha256_of(target) if path and target.is_file() else None
    panels = [(panel["plot"], panel["drawing"], panel["library"], digest(panel["png"]), digest(panel["svg"]), digest(panel.get("script")))
              for panel in request.get("panels") or []]
    return hashlib.sha256(json.dumps([request["mode"], panels, [(entry["path"], entry["sha256"]) for entry in request["data"]],
                                      request["target"]], sort_keys=True).encode("utf-8")).hexdigest()


def make_figures(project, plan, previous=None, *, harness_root=None, policy=None, say=None):
    """Run the figure role on every planned figure, outside the ledger's lock: `{plan id: {figure_id, key, result,
    reason, reused}}`. A figure whose key is the one `previous` (the last version's `figures` block) recorded, and whose
    result is verified, is reused with no session; a figure from nothing that waits on the owner's pick is resumed."""
    from wayline import figure_role
    say = say or (lambda text: None)
    before = {entry["figure_id"]: entry for entry in ((previous or {}).get("figures") or {}).get("figures") or []}
    made = {}
    for figure in plan["figures"] + plan["supplementary"]:
        request = request_for(project, plan, figure)
        identifier, key = request["figure_id"], _key(project, request)
        held = figure_role.read_result(project, identifier)
        same = (before.get(identifier) or {}).get("key") == key and isinstance(held, dict)
        entry = {"figure_id": identifier, "key": key, "result": held, "reason": None, "reused": False}
        try:
            if same and held.get("status") == "verified":
                entry["reused"] = True
            elif same and held.get("status") in ("candidates_ranked", "selected"):
                entry["result"], entry["reason"] = figure_role.resume_figure(project, identifier, harness_root=harness_root,
                                                                             policy=policy, say=say)
            else:
                entry["result"], entry["reason"] = figure_role.make(project, request, harness_root=harness_root, policy=policy, say=say)
        except (ValueError, OSError, KeyError) as failure:  # a FigureError, a role that cannot be read, a file gone
            entry["result"], entry["reason"] = None, _one_line(failure)
        made[figure["id"]] = entry
        status = (entry["result"] or {}).get("status") or "not made"
        say("  paper figure %s (%s): %s%s" % (figure["id"], identifier, status, ", reused" if entry["reused"] else ""))
    return made


def _copy(book, source, relative):
    path = Path(book.project) / str(source or "")
    if source and path.is_file():
        book.write_bytes(relative, path.read_bytes())
        return True
    return False


def write(book, plan, made):
    """Write the figures and the plan's tables under `research/paper/` and return the record's `figures` block. Under the
    ledger's lock. A figure not verified gets a `caption.md` saying so, a marked placeholder, and its files stay out."""
    base = "paper/%s" % FIGURES_DIR
    book.remove_tree(base)
    entries = []
    for figure in plan["figures"] + plan["supplementary"]:
        entry = made.get(figure["id"]) or {"figure_id": figure_id(figure), "key": None, "result": None, "reason": "not made"}
        result = entry["result"] or {}
        status = result.get("status") or "blocked"
        folder = "%s/%s" % (base, figure["id"])
        final = result.get("final") or {}
        if status == "verified":
            for key, name in (("pdf", "%s.pdf"), ("png", "%s.png"), ("svg", "%s.svg"), ("generator", "%s.py")):
                _copy(book, final.get(key), "%s/%s" % (folder, name % figure["id"]))
            caption = (Path(book.project) / final["caption"]).read_text(encoding="utf-8")
        else:
            caption = NOT_MADE % "%s%s" % (status, ": %s" % _one_line(entry.get("reason")) if entry.get("reason") else "")
        book.write_markdown("%s/caption.md" % folder, caption)
        entries.append({"id": figure["id"], "result": figure["result"], "main": figure["main"], "panels": list(figure["panels"]),
                        "line": figure["line"], "figure_id": entry["figure_id"], "key": entry.get("key"), "status": status,
                        "version": result.get("version"), "reused": bool(entry.get("reused")),
                        "reason": _one_line(entry.get("reason")) or None,
                        "findings_for_text": [_one_line(item.get("text")) for item in result.get("findings_for_text") or []]})
    tables = []
    for table in plan["tables"]:
        source = Path(book.project) / str(table.get("csv") or "")
        if not table.get("csv") or not source.is_file():
            continue
        text = source.read_text(encoding="utf-8").strip()
        book.write_markdown("paper/%s/%s.csv" % (TABLES_DIR, table["id"]), text + "\n")
        book.write_markdown("paper/%s/%s.md" % (TABLES_DIR, table["id"]), _table_markdown(table, text))
        tables.append({"id": table["id"], "result": table["result"], "plot": table["plot"], "main": table["main"]})
    return {"venue": plan["venue"], "limit": plan["limit"], "figures": entries, "tables": tables, "moved": list(plan["moved"]),
            "without": list(plan["without"])}


def label(identifier):
    """How the paper names a plan item: Figure 1, Supplementary Figure S1, Table 1, Supplementary Table S1."""
    if identifier.startswith("ST"):
        return "Supplementary Table S%s" % identifier[2:]
    if identifier.startswith("S"):
        return "Supplementary Figure %s" % identifier
    return "%s %s" % ("Figure" if identifier.startswith("F") else "Table", identifier[1:])


def _table_markdown(table, text):
    rows = list(csv.reader(io.StringIO(text)))
    lines = ["**%s.** %s" % (label(table["id"]), _one_line(table["caption"])), ""]
    if rows:
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines.append("| %s |" % " | ".join(cell.replace("|", "\\|") for cell in rows[0]))
        lines.append("|%s|" % "|".join(["---"] * width))
        lines += ["| %s |" % " | ".join(cell.replace("|", "\\|") for cell in row) for row in rows[1:]]
    return "\n".join(lines) + "\n"


def writer_lines(plan):
    """The writer's view of the plan: each figure and table by the number the text refers to it by, and what it shows."""
    lines = []
    for figure in plan["figures"] + plan["supplementary"]:
        lines.append("- %s, of %s (\"%s\"): %s" % (label(figure["id"]), figure["result"], _one_line(figure.get("heading")),
                                                 "a figure from nothing" if figure["from_nothing"] else "panels " + ", ".join(figure["panels"])))
    lines += ["- %s, of %s: %s" % (label(table["id"]), table["result"], table["caption"]) for table in plan["tables"]]
    return "\n".join(lines) if lines else "- none: the plan holds no figure and no table"


def report_lines(block):
    """`PAPER.md`'s Figures section from the record's `figures` block: each figure's plan line and how it stands."""
    if not block:
        return ["No figure plan was made for this version."]
    lines = []
    if block.get("limit") is not None:
        lines.append("The display-item limit of %s is %d; %s." % (block.get("venue") or "the venue", block["limit"],
                                                                "moved to the supplement: %s" % ", ".join(block["moved"]) if block["moved"] else "nothing was moved"))
        lines.append("")
    for entry in block["figures"]:
        state = "verified%s" % (", reused from the last version" if entry["reused"] else "") if entry["status"] == "verified" else \
            "not made (%s%s): its caption.md is a marked placeholder" % (entry["status"], "; %s" % entry["reason"] if entry.get("reason") else "")
        lines.append("- %s: %s (the figure role's figures/%s/)" % (entry["line"], state, entry["figure_id"]))
    lines += ["- %s (%s): %s, from its CSV" % (table["id"], table["result"], table["plot"]) for table in block["tables"]]
    if not block["figures"] and not block["tables"]:
        lines.append("No figure: no plot is marked keep or cited by a synthesis, and none was asked for from nothing.")
    if block.get("without"):
        lines.append("- no figure for %s: no plot kept or cited, and none asked for from nothing" % ", ".join(block["without"]))
    points = [(entry["id"], text) for entry in block["figures"] for text in entry.get("findings_for_text") or []]
    if points:
        lines += ["", "The figures' points for the text, for the writer of the next build:", ""]
        lines += ["- %s: %s" % (identifier, text) for identifier, text in points]
    return lines


def plan_lines(plan):
    """The plan's lines, the figures' then the tables'."""
    lines = [figure["line"] for figure in plan["figures"] + plan["supplementary"]]
    lines += ["%s (%s): %s, %s" % (table["id"], table["result"], table["plot"], table["caption"]) for table in plan["tables"]]
    return lines
