"""The dashboard's routed views (Implementation Decision 17; tickets 110, 111, and 112): what each view reads, and what
an item link opens.

The dashboard is five hash-routed views behind the project tabs; this module builds the JSON of each of them,
**Research** and the additions to **Run** (ticket 110), **Paper** and **Inherited** (ticket 111), and **Marks** (ticket
112), the "Waiting on you" strip every view shows, the projects page's row for each project, and the resolution of an
item link `#/<project>/<id>`. Like every view the dashboard polls, each function here reads and never writes: no lock, no
render, no model, so the dashboard spends no tokens. A mark the owner gives in Marks is the `mark` action's, which calls
the `wayline mark` verb's function.

**Thin lists.** A view lists items, each an id, a title, a status, and what opens it; it never carries a rendered
file. Every Markdown file code renders (the general report, a result's reports, the account, `OBJECTIVES.md`, the
sections, the outline, `CONCERNS.md`, `VERIFICATIONS.md`) is named here by its path and read only in the popup viewer,
so nothing is rendered twice. Inherited is offered only for a project with documents: without one it is None.

**Item ids.** An item link names one of:

- `O3`, an objective, which opens `OBJECTIVES.md` at its heading over Research;
- `R4`, a result, which opens its current report (the general report at its heading before its first drawing);
- `R4.3`, a plot, and `R4.T1`, a table, which open the image with its explanation, or the table's rows;
- `R4-2`, one of a result's reports, and `report`, the general report;
- `12`, a ticket or a decision ticket, which opens its file over Run;
- `account`, `research/ACCOUNT.md`, over Run;
- `introduction`, `results`, `discussion`, `methods`, `references`, a section, and `outline`, `OUTLINE.md`, over Paper;
- `P12`, a passage, which opens its section at its heading: over Inherited for an inherited claim, else over Paper;
- `D1`, a document, which opens its converted text over Inherited;
- `K3`, a concern, and `M2`, a missing item, which open `CONCERNS.md` and `VERIFICATIONS.md` at their headings;
- `P5+P11`, a pair of the repeated-claims check, a contradiction or a merge, which opens both claims side by side;
- `B3`, a batch, which the page opens in Marks at that batch rather than in the viewer, so it is no id here.

An id that names nothing resolves to None, and the server answers 404 with one line the page shows in the viewer.

**New since you looked.** Each current report and the general report carry the `sha256` their last `report_rendered`
journaled. The page keeps, in its own browser, the hash each report had when the owner last opened it, and marks a
report whose hash moved with a dot. A renewed report notifies nowhere: nothing here or in the renders sends a notice.
"""

import json
import os
import re
from pathlib import Path

from wayline.ledger import REPORT_RENDERED, TICKET_CANCELLED, Ledger
from wayline.project import RESEARCH, ProjectError, read_harness

__all__ = ["VIEWS", "research_view", "run_view", "paper_view", "inherited_view", "marks_view", "item_view", "ITEM_ID"]

# The five views: Research and Run (110), Paper and Inherited (111), Marks (112).
VIEWS = ("research", "run", "paper", "inherited", "marks")
RESEARCH_VIEW, RUN_VIEW, PAPER_VIEW, INHERITED_VIEW, MARKS_VIEW = VIEWS

REPORT_MD = RESEARCH + "/REPORT.md"
OBJECTIVES_MD = RESEARCH + "/OBJECTIVES.md"

# Every id an item link may name, and nothing else: the route matches it before anything is read.
ITEM_ID = re.compile(r"^(?:O[1-9][0-9]*|R[1-9][0-9]*(?:\.T?[1-9][0-9]*|-[1-9][0-9]*)?|[1-9][0-9]*|report|account|outline|"
                     r"introduction|results|discussion|methods|references|[DKM][1-9][0-9]*|P[1-9][0-9]*(?:\+P[1-9][0-9]*)?)$")


def _events(project, problems):
    try:
        return Ledger(project).read_events()[0]
    except (OSError, ValueError) as failure:
        problems.append("journal: %s" % failure)
        return []


def _renders(events):
    """`{report name or "general": {"sha256", "ts"}}`: the last `report_rendered` of each report, a result's by `R4-2`."""
    found = {}
    for event in events:
        if event.get("event") != REPORT_RENDERED:
            continue
        payload = event.get("payload") or {}
        report, version = payload.get("report"), payload.get("version")
        if report in (None, "general"):
            key = "general"
        elif version is not None:
            key = "%s-%s" % (report, version)
        else:
            key = report
        found[key] = {"sha256": payload.get("sha256"), "ts": event.get("ts")}
    return found


def _report_entry(name, renders):
    from wayline import reports
    stamp = renders.get(name) or {}
    return {"name": name, "path": "%s/%s" % (RESEARCH, reports.report_path(*_split_report(name))),
            "sha256": stamp.get("sha256"), "renewed": stamp.get("ts")}


def _split_report(name):
    result, version = name.rsplit("-", 1)
    return result, int(version)


def _result_rows(project, index, plots, renders):
    from wayline import drawings
    from wayline import results as results_module
    rows = []
    for result in results_module.read_results(project):
        current, earlier = index.links(result.id)
        held = index.versions(result.id)
        record = held[-1][1] if held else {}
        rows.append({
            "id": result.id,
            "heading": result.heading,
            "standing": result.standing,
            "objectives": list(result.objectives),
            "findings": len(result.current),
            "headline": record.get("headline"),
            "current": _report_entry(current, renders) if current else None,
            "earlier": [_report_entry(name, renders) for name in earlier],
            "plots": [_plot_row(plot) for plot in sorted(plots, key=lambda plot: drawings.plot_order(plot["id"]))
                      if plot.get("result") == result.id and plot.get("status") == drawings.CURRENT],
            "left_out": [{"what": item.get("what"), "reason": item.get("reason")} for item in record.get("left_out") or []],
        })
    return rows


def _plot_row(plot):
    return {"id": plot["id"], "kind": plot.get("kind"), "chart_type": plot.get("chart_type"), "headline": bool(plot.get("headline")),
            "mark": plot.get("mark"), "path": plot.get("path")}


def _plots(project, index):
    """plots.json's plots, each with the file it opens: a plot's PNG or a table's CSV, as the drawing that drew it last wrote it."""
    from wayline import drawings
    held = drawings.read_plots(project)["plots"]
    entries = index.entries()
    for plot in held:
        entry = (entries.get(plot["id"]) or ({}, None))[0]
        plot["path"] = entry.get("png") if plot.get("kind") == "plot" else entry.get("csv")
    return held


def _read_objectives(project, problems):
    from wayline.objectives import read_objectives
    try:
        return read_objectives(project)
    except (OSError, ValueError) as failure:
        problems.append(str(failure))
        return []


def _objective_rows(records, events, results):
    """Each objective with its status, its measure and kept values, its lineage, and the results answering it."""
    from wayline import goal as goals
    from wayline.objectives import describe_measure
    progress = goals.progress_payloads(events)
    rows = []
    for record in records:
        measure = record.get("measure") if isinstance(record.get("measure"), dict) else None
        rows.append({
            "id": record.get("id"),
            "text": record.get("text"),
            "status": record.get("status"),
            "measure": describe_measure(measure) if measure else None,
            "kept": goals.kept_readings(progress, record.get("id")) if measure else [],
            "best": goals.best_kept(progress, record, baseline=False) if measure else None,
            "reached": goals.reached(progress, record) if measure else None,
            "answer": record.get("answer"),
            "lineage": {
                "reframed_as": record.get("reframed_as"),
                "reframed_from": [other.get("id") for other in records if other.get("reframed_as") == record.get("id")],
                "superseded": [{"status": earlier.get("status"), "answer": earlier.get("answer")} for earlier in record.get("superseded") or []],
            },
            "results": [row["id"] for row in results if record.get("id") in row["objectives"]],
        })
    return rows


def _set_aside(project, records, problems):
    """The spec's claims set aside: each tied only to closed objectives (decision 17; ticket 91)."""
    from wayline import specify
    from wayline.objectives import set_aside
    try:
        draft = Ledger(project).read_json(specify.SPEC_JSON) if (project / RESEARCH / specify.SPEC_JSON).is_file() else None
    except (OSError, ValueError) as failure:
        problems.append("spec.json: %s" % failure)
        draft = None
    claims = (draft or {}).get("claims") if isinstance(draft, dict) else None
    if not isinstance(claims, list):
        return []
    aside = set_aside(claims, records)
    return [{"id": claim["id"], "text": claim.get("text"), "objectives": aside[claim["id"]]} for claim in claims if claim.get("id") in aside]


# What `objective_changes` says of a ticket it parked because every objective it served closed.
PARKED_FOR_CLOSED = "it serves only "


def _parked(project, events, problems):
    """The tickets parked for a closed objective, each with why, as its last `ticket_cancelled` said."""
    from wayline.tickets import read_tickets
    why = {}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == TICKET_CANCELLED:
            why[payload.get("ticket")] = payload.get("reason")
    try:
        held = read_tickets(project)
    except (OSError, ValueError) as failure:
        problems.append("tickets: %s" % failure)
        return []
    return [{"id": fields["id"], "title": fields.get("title"), "reason": why[fields["id"]]} for fields in held
            if fields.get("status") == "parked" and str(why.get(fields["id"]) or "").startswith(PARKED_FOR_CLOSED)]


def _plotting(project, problems):
    from wayline import plotting
    try:
        harness = read_harness(project)
    except (ProjectError, OSError, ValueError) as failure:
        problems.append("harness.json: %s" % failure)
        harness = {}
    library = plotting.setting(harness)
    return {"library": library, "label": plotting.LIBRARIES[library].label}


def research_view(project):
    """The Research view: the general report, the objectives, their results, what stands beside them, the plotting library."""
    from wayline import reports
    project = Path(project).resolve()
    problems = []
    events = _events(project, problems)
    renders = _renders(events)
    try:
        index = reports.Index(project)
        results = _result_rows(project, index, _plots(project, index), renders)
    except (OSError, ValueError) as failure:  # the objectives and the general report still show
        problems.append("the results and their drawings: %s" % failure)
        results = []
    general = renders.get("general") or {}
    records = _read_objectives(project, problems)
    held = {record.get("id") for record in records}
    return {
        "report": {"path": REPORT_MD, "exists": (project / REPORT_MD).is_file(), "sha256": general.get("sha256"),
                   "renewed": general.get("ts")},
        "objectives": _objective_rows(records, events, results),
        "results": results,
        "beyond": [row["id"] for row in results if not held & set(row["objectives"])],
        "set_aside": _set_aside(project, records, problems),
        "parked": _parked(project, events, problems),
        "plotting": _plotting(project, problems),
        "problems": problems,
    }


ACCOUNT_MD = RESEARCH + "/ACCOUNT.md"


# --- Run: the account and Software ------------------------------------------------------------------------------


def _account(project, problems, events=None):
    """`account.account_view` with `full=False` (the paragraph, "Decided for you", "Waiting on you"), or None when it fails."""
    from wayline import account
    try:
        return account.account_view(project, full=False, events=events)
    except (OSError, ValueError) as failure:
        problems.append("the account: %s" % failure)
        return None


def run_view(project):
    """What Run adds to today's page: the account, which opens in the viewer, and Software (`tools.json`, the MATLAB
    check's outcome, the environment and a move in progress)."""
    project = Path(project).resolve()
    problems = []
    events = _events(project, problems)
    view = _account(project, problems, events) or {}
    from wayline.tools import Tools
    tools = Tools()
    return {
        "account": {"path": ACCOUNT_MD, "exists": (project / ACCOUNT_MD).is_file(), "decided": view.get("decided"),
                    "waiting": view.get("waiting")},
        "software": {"tools": _tools(tools), "matlab": _matlab(events, tools), "environment": _environment(project, problems)},
        "problems": problems,
    }


def _tools(record):
    return [dict({"name": name}, **{key: (record.entry(name) or {}).get(key) for key in ("version", "installer", "executable", "route")})
            for name in record.names()]


def _matlab(events, tools):
    """MATLAB as `tools.json` records it, and the outcome of its last `matlab -batch "ver"` check; None when neither is there."""
    from wayline.ledger import TOOL_INSTALLED
    from wayline.software import MATLAB
    entry = tools.entry(MATLAB)
    check = None
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == TOOL_INSTALLED and payload.get("name") == MATLAB:
            check = {"outcome": payload.get("outcome"), "version": payload.get("version"), "reason": payload.get("reason"),
                     "ticket": payload.get("ticket"), "ts": event.get("ts")}
    if entry is None and check is None:
        return None
    entry = entry or {}
    return {"executable": entry.get("executable"), "version": entry.get("version"), "release": entry.get("release"),
            "toolboxes": sorted(entry.get("toolboxes") or {}), "check": check}


def _environment(project, problems):
    from wayline import environment
    try:
        setting = environment.setting(project)
    except (ProjectError, OSError, ValueError) as failure:
        problems.append("harness.json: %s" % failure)
        setting = environment.SHARED
    place = environment.place(project, setting)
    return {"setting": setting, "place": place.relative_to(project).as_posix() if place else None,
            "move": environment.move_in_progress(project)}


def move_alive(project):
    """The move under way, which `move_in_progress` reads only while its mover lives: no file moves when one dies, so
    Run's tag carries this too."""
    from wayline import environment
    return environment.move_in_progress(project)


# --- Paper: the sections, the outline, References, the code repository, Methods' generated part -------------------

OUTLINE_MD = RESEARCH + "/OUTLINE.md"


def _section_rows(project, problems):
    """The five sections, each an item opening its file: its title, whether code rendered it yet, when, and how many
    passages stand in it (References takes none: code writes it from what the others cite)."""
    from wayline import sections
    rows = []
    for name in sections.SECTIONS:
        path = "%s/%s" % (RESEARCH, sections.section_path(name))
        stamp = sections.read_stamp(project, name) or {}
        standing = None
        if name != sections.REFERENCES:
            try:
                standing = len(sections.current_ids(project, name))
            except (OSError, ValueError) as failure:
                problems.append("%s: %s" % (sections.TITLES[name], failure))
        rows.append({"id": name, "title": sections.TITLES[name], "path": path, "exists": (project / path).is_file(),
                     "rendered": stamp.get("rendered_at"), "passages": standing,
                     "editable": name != sections.REFERENCES,  # References is code's alone (ticket 113)
                     "consolidates": name in sections.WRITTEN})  # a consolidation rewrites these (ticket 88), from a card (121)
    return rows


def _outline_row(project):
    from wayline import outline
    stamp = outline.read_stamp(project) or {}
    return {"id": "outline", "title": "The outline", "path": OUTLINE_MD, "exists": (project / OUTLINE_MD).is_file(),
            "rendered": stamp.get("rendered_at"), "editable": True}


def _references(project, problems):
    """References as code reads it now: its numbered entries and its Not yet resolved rows, each with its state."""
    from wayline import references, sections
    path = "%s/%s" % (RESEARCH, sections.section_path(sections.REFERENCES))
    try:
        view = references.references_view(project)
    except (OSError, ValueError) as failure:
        problems.append("References: %s" % failure)
        view = {"entries": [], "unresolved": []}
    entries = []
    for number, record in enumerate(view["entries"], start=1):
        metadata = record.get("metadata") or {}
        entries.append({"number": number, "slug": record.get("slug"), "title": metadata.get("title") or record.get("slug"),
                        "authors": list(metadata.get("authors") or [])[:3], "more_authors": len(metadata.get("authors") or []) > 3,
                        "year": metadata.get("year"), "venue": metadata.get("container"),
                        "identifier": references.identifier_of(record)})
    unresolved = []
    asked = _order_batch_items(project, problems)
    for work, state, detail in view["unresolved"]:
        record = work.record or {}
        query = record.get("query") or {}
        unresolved.append({"named": work.named, "slug": work.slug, "state": state, "detail": detail,
                           "title": (record.get("metadata") or {}).get("title") or (query.get("value") if query.get("kind") == "title" else None),
                           "batch": asked.get("reference:%s" % (work.slug or work.named))})
    return {"path": path, "exists": (project / path).is_file(), "entries": entries, "unresolved": unresolved}


def _order_batch_items(project, problems):
    """The open paper order's batch, by each item's ref: `{ref: {batch, item, mark, default, marks}}`, empty with no order
    asking one. A reference's row carries its item, so the hand-over form's "drop it" and "keep the claim marked" are the
    batch's marks (ticket 121), saved through `mark` as the marks view saves them."""
    from wayline import batches, paper
    try:
        opened = paper.open_order(project)
        identifier = paper.waiting_on(project, opened) if opened else None
        if not identifier:
            return {}
        batch = batches.read_batch(project, identifier)
    except (batches.BatchError, OSError, ValueError) as failure:
        problems.append("the paper order's batch: %s" % failure)
        return {}
    return {item["ref"]: {"batch": batch["id"], "item": item["id"], "mark": item.get("mark"), "default": item.get("default"),
                          "marks": list(item.get("marks") or [])} for item in batch["items"]}


def _code_repository(project, events, problems):
    """The code repository: its remote's link, its visibility, and the last push code made, from `harness.json` and the
    journal's last `code_pushed`; `settled` is False until the setup question made a remote."""
    from wayline import code_repository
    try:
        record = code_repository.record(project)
    except (ProjectError, OSError, ValueError) as failure:
        problems.append("harness.json: %s" % failure)
        record = {}
    remote = record.get("remote") or {}
    pushed = code_repository.last_push(project, events)
    return {"settled": bool(remote), "repository": remote.get("repository"), "url": remote.get("url"),
            "visibility": record.get("visibility"), "shape": record.get("shape"), "license": record.get("license"),
            "last_push": pushed}


def _methods(project):
    """Methods' generated part as its last render wrote it (`methods_inventory.json`): the parameter table, each row with
    whose reason it shows, and each Methods method with no code behind it, by the passage naming it."""
    from wayline import methods_inventory
    record = methods_inventory.read_record(project)
    rows = [dict(row, parameter=methods_inventory.parameter_key(row.get("method"), row.get("name"), row.get("path")))
            for row in record.get("parameters") or []]  # what the editor's `reason` names its row by (ticket 113)
    return {"parameters": rows,
            "no_code": [{key: entry.get(key) for key in ("passage", "heading", "named", "why")} for entry in record.get("not_reproduced") or []]}


# How often Paper's and Inherited's tags move with no file moving, so a reference's give-up time reaches the page.
REFERENCES_TICK_S = 60


def paper_snapshot(project):
    """What Paper reads outside the ledger's snapshot: the section files (`section_snapshot`), and the minute: a retried
    reference gives up at the moment its flag's days run out, with no file moving, so the tag moves each minute and
    References shows it given up within one."""
    import time
    paper = Path(project) / PAPER_DIR
    found = dict(section_snapshot(project), minute=int(time.time() // REFERENCES_TICK_S))
    # The paper's parts, its record, its alternatives, its earlier versions, and each compilation's record (ticket 121),
    # none of which the ledger's snapshot scans: a choice or a compilation moves only these.
    found.update(_stamps(paper, "paper/"))
    found.update(_stamps(paper / "alternatives", "alternatives/"))
    for directory in ("earlier", "compilations"):
        try:
            with os.scandir(paper / directory) as entries:
                names = sorted(entry.name for entry in entries if entry.is_dir(follow_symlinks=False))
        except OSError:
            names = []
        found[directory] = names
        if directory == "compilations":
            for name in names:
                found.update(_stamps(paper / directory / name, "compilations/%s/" % name))
    return found


def section_snapshot(project):
    """The `(mtime_ns, size)` of each section file, which the ledger's snapshot does not scan: an owner's edit of one
    moves no ledger file until the next render takes it in."""
    from wayline import sections
    return _stamps(Path(project) / RESEARCH / sections.SECTIONS_DIR)


def _stamps(directory, prefix=""):
    """`{prefix + name: (mtime_ns, size)}` of the files directly in `directory`, dot files left out; nothing when it is
    not there. What a view's tag carries of files the ledger's snapshot does not scan."""
    found = {}
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.name.startswith(".") and entry.is_file(follow_symlinks=False):
                    stamp = entry.stat()
                    found[prefix + entry.name] = (stamp.st_mtime_ns, stamp.st_size)
    except OSError:
        pass
    return found


def paper_view(project):
    """The Paper view: the five sections and the outline, each opening in the viewer, References with its Not yet
    resolved rows, the code repository, and Methods' parameter table and the methods with no code behind them."""
    project = Path(project).resolve()
    problems = []
    events = _events(project, problems)
    record = _paper_record(project, problems)
    return {
        "sections": _section_rows(project, problems),
        "outline": _outline_row(project),
        "references": _references(project, problems),
        "code_repository": _code_repository(project, events, problems),
        "methods": _methods(project),
        "paper": _paper_parts(project, record),
        "compilations": _compilation_rows(project, record, problems),
        "venues": venues(),
        "order": _open_order(project, problems),
        "problems": problems,
    }


# --- Paper: the paper's parts, earlier versions, and the compilations (ticket 121) ----------------------------------

PAPER_DIR = RESEARCH + "/paper"
PART_TITLES = {"title": "Title", "abstract": "Abstract", "introduction": "Introduction", "results": "Results",
               "discussion": "Discussion", "methods": "Methods", "supplement": "Supplement", "front": "Front matter"}
# What a compilation offers to download, each the file or directory under `compilations/<name>/` it is.
DOWNLOADS = (("pdf", "paper.pdf"), ("docx", "paper.docx"), ("latex", "latex"), ("markdown", "paper.md"))


def _paper_record(project, problems):
    from wayline import paper
    try:
        return paper.read_record(project)
    except (paper.PaperError, OSError, ValueError) as failure:
        problems.append(str(failure))
        return None


def _paper_parts(project, record):
    """The paper's version: each part with the version it was last made in, whether the owner changed its file since (an
    edit, or a choice), and its alternatives, the one the part holds now marked; the earlier versions, newest first."""
    from wayline import paper
    if record is None:
        return None
    book = Ledger(project)
    parts = []
    for part in paper.PARTS:
        path = "%s/%s.md" % (PAPER_DIR, part)
        try:
            text = (project / path).read_text(encoding="utf-8")
        except OSError:
            text = None
        held = record["parts"][part]
        current = (text or "").strip()
        parts.append({
            "part": part, "title": PART_TITLES.get(part, part), "path": path, "exists": text is not None, "version": held["version"],
            "edited": text is not None and paper._sha(text) != held["sha256"],
            "alternatives": [{"name": name, "text": _clip(alternative), "path": "%s/%s/%s.md" % (PAPER_DIR, paper.ALTERNATIVES, name),
                              "current": alternative == current} for name, alternative in paper.alternatives_of(book, record, part)],
        })
    return {"version": record["version"], "order": record["order"], "composed": record["composed"], "report": "%s/%s" % (PAPER_DIR, paper.PAPER_MD),
            "parts": parts, "chosen": [{key: choice.get(key) for key in ("part", "alternative", "at")} for choice in record.get("chosen") or []],
            "earlier": _earlier(project)}


def _earlier(project):
    """Each frozen version under `research/paper/earlier/v<n>/`, newest first: its build report and its title."""
    from wayline import paper
    root = project / PAPER_DIR / paper.EARLIER
    found = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        match = re.match(r"^v([1-9][0-9]*)$", entry.name)
        if not match or not entry.is_dir():
            continue
        try:
            title = (entry / "title.md").read_text(encoding="utf-8")
        except OSError:
            title = ""
        report = entry / paper.PAPER_MD
        found.append({"version": int(match.group(1)), "title": _clip(title),
                      "report": report.relative_to(project).as_posix() if report.is_file() else None,
                      "path": entry.relative_to(project).as_posix()})
    return sorted(found, key=lambda item: -item["version"])


def venues(root=None):
    """The venues a compilation can be made for: each slug under the harness's `guidelines/` with its display name."""
    from wayline import HARNESS_ROOT, guidelines
    shelf = Path(root or HARNESS_ROOT) / guidelines.GUIDELINES_DIR
    found = []
    try:
        entries = sorted(shelf.iterdir())
    except OSError:
        return []
    for entry in entries:
        try:
            record = json.loads((entry / guidelines.GUIDELINES_JSON).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found.append({"venue": entry.name, "display_name": record.get("display_name") or entry.name})
    return found


def _compilation_rows(project, record, problems):
    """Each compilation: its venue, the version it was made from, its outcome, its four downloads (the LaTeX directory a
    zip), and the parts chosen since it was made (`made before part X changed`)."""
    from wayline import compilations
    try:
        held = compilations.read_compilations(project)
    except (OSError, ValueError) as failure:
        problems.append("the compilations: %s" % failure)
        return []
    names = {item["venue"]: item["display_name"] for item in venues()}
    rows = []
    for compiled in held:
        base = "%s/%s/%s" % (PAPER_DIR, compilations.COMPILATIONS, compiled["name"])
        downloads = {kind: "%s/%s" % (base, name) for kind, name in DOWNLOADS if (project / base / name).exists()}
        rows.append({
            "name": compiled["name"], "venue": compiled.get("venue"),
            "display_name": names.get(compiled.get("venue"), compiled.get("venue")) if compiled.get("venue") else "plain, no venue",
            "paper_version": compiled.get("paper_version"), "compiled": compiled.get("compiled"), "outcome": compiled.get("outcome"),
            "older": bool(record) and compiled.get("paper_version") != record["version"],
            "made_before": compilations.made_before(record, compiled), "downloads": downloads,
            "problems": {output: item.get("problem") for output, item in (compiled.get("outputs") or {}).items() if item.get("problem")},
            "checks_failed": [check.get("check") for check in compiled.get("checks") or [] if check.get("level") == "fail"],
            "record": "%s/%s" % (base, compilations.RECORD_JSON),
        })
    return rows


def _open_order(project, problems):
    """The paper order open now, `{order, batch, venue}`, or None: while one is open, a new order and a choice wait."""
    from wayline import paper
    try:
        opened = paper.open_order(project)
    except (OSError, ValueError) as failure:
        problems.append("the paper order: %s" % failure)
        return None
    if opened is None:
        return None
    return {"order": opened.get("order"), "batch": paper.waiting_on(project, opened), "venue": opened.get("venue")}


# --- Inherited: what a start midway brought, and what became of it ------------------------------------------------


def _documents(project, problems):
    from wayline import documents
    try:
        return documents.read_documents(project)
    except (OSError, ValueError) as failure:
        problems.append("documents.json: %s" % failure)
        return []


def _document_count(project, problems):
    """How many documents the project holds, or None when `documents.json` cannot be read: not known is not none, so the
    page still offers Inherited, which says why."""
    found = []
    held = _documents(project, found)
    problems.extend(found)
    return None if found else len(held)


def _document_path(project, document):
    """What a document opens, `(path, focus)`: its converted `text.md`, or `DOCUMENTS.md` at its entry for one kept as given."""
    from wayline import documents
    path = "%s/%s/%s/text.md" % (RESEARCH, documents.DOCUMENTS_DIR, document["id"])
    if (project / path).is_file():
        return path, None
    return "%s/%s" % (RESEARCH, documents.DOCUMENTS_MD), document["id"]


def _document_rows(project, held):
    rows = []
    for document in held:
        path, focus = _document_path(project, document)
        rows.append({"id": document["id"], "title": document.get("title"), "kind": document.get("kind"), "version": document.get("version"),
                     "converted": document.get("converted"), "path": path, "focus": focus,
                     "headings": [{key: heading.get(key) for key in ("level", "locator", "text")} for heading in document.get("headings") or []]})
    return rows


def _concern_rows(project, problems):
    """Each concern with its sources, verbatim, and its standing: its place, its status, and the answer or the reason."""
    from wayline import concerns
    try:
        held = concerns.read_concerns(project)
    except (OSError, ValueError) as failure:
        problems.append(str(failure))
        return []
    rows = []
    for concern in held:
        sources = [{key: source.get(key) for key in ("critique", "locator", "text")} for source in concern.get("sources") or []]
        rows.append({"id": concern["id"], "text": sources[0]["text"] if sources else None, "sources": sources,
                     "targets": list(concern.get("targets") or []), "place": concern.get("place"),
                     "objectives": list(concern.get("objectives") or []), "status": concern.get("status"),
                     "answer": concern.get("answer"), "reason": concern.get("reason")})
    return rows


def _words(text):
    """A passage's words, its tags taken off: what a row shows."""
    from wayline import provenance
    return " ".join(provenance.strip_tags(str(text or "")).split())


def _claim_rows(project, passages, problems):
    """The inherited claims standing now: each Results claim of an inherited result with its standing, its verdict, and
    its route (`verification.claim_rows`), followed wherever it went, then the other sections' claims, which no
    verification reaches, with their standing. Each once, by the passage that holds it now, which its link opens."""
    from wayline import sections, verification
    try:
        followed = verification.claim_rows(project)
    except (OSError, ValueError) as failure:
        problems.append("the inherited claims: %s" % failure)
        return []
    rows = []
    for row in followed:
        passage = passages.get(row["current"]) or {}
        rows.append({"id": row["current"], "claim": row["claim"], "section": passage.get("section") or sections.RESULTS,
                     "heading": passage.get("heading") or row["heading"], "result": row["heading"], "text": _words(passage.get("text")),
                     "standing": row["standing"], "reason": row["reason"], "verdict": row["verdict"], "route": row["route"],
                     "ticket": row["ticket"], "by": row["by"]})
    listed = {row["id"] for row in rows}
    for section in sections.INHERITED:
        if section == sections.RESULTS:
            continue
        try:
            items = sections.section_items(project, section)
            standing = {item.get("id") for item in sections.arrange(items).current()}
        except (OSError, ValueError) as failure:
            problems.append("%s: %s" % (sections.TITLES[section], failure))
            continue
        for item in items:
            if (item.get("id") in standing and item.get("id") not in listed and sections.is_inherited(item)
                    and item.get("standing") in sections.STANDINGS):
                rows.append({"id": item["id"], "claim": item["id"], "section": section, "heading": item.get("heading"), "result": None,
                             "text": _words(item.get("text")), "standing": item["standing"],
                             "reason": item.get("reason") if item["standing"] == sections.UNVERIFIABLE else None,
                             "verdict": None, "route": None, "ticket": None, "by": None})
    return rows


def pair_id(first, second):
    """A pair's item id, `P5+P11`: the two claims in the order the check read them."""
    return "%s+%s" % (first, second)


def _pairs(project, passages, problems):
    """`(contradictions, merges)` of the repeated-claims check (ticket 95), each pair by its id with both claims' words."""
    from wayline import repeats
    try:
        contradicting, merged = repeats.contradictions(project), repeats.merges(project)
    except (OSError, ValueError) as failure:
        problems.append("the repeated claims: %s" % failure)
        return [], []

    def row(entry):
        texts = [_words((passages.get(entry[side]) or {}).get("text")) for side in ("a", "b")]
        return dict(entry, id=pair_id(entry["a"], entry["b"]), texts=texts)

    return [row(entry) for entry in contradicting], [row(entry) for entry in merged]


def _material(project, problems):
    """The missing material each inherited result needs, with the owner's (or the decider's) reply, or none yet."""
    from wayline import verification
    try:
        held = verification.read_record(project)["material"]
    except (OSError, ValueError) as failure:
        problems.append(str(failure))
        return []
    return [{key: item.get(key) for key in ("id", "heading", "kind", "item", "licensed", "rebuild", "reply", "by", "found_by")}
            for item in held]


def inherited_view(project):
    """The Inherited view, or None for a project with no documents: the documents and their headings, the concerns, the
    inherited claims with their standing, verdict, and route, the unverifiable ones with their reasons, the contradicting
    pairs, the setup's merges, and the missing material with the owner's replies."""
    from wayline import sections
    project = Path(project).resolve()
    problems = []
    held = _documents(project, problems)
    if not held and not problems:
        return None
    try:  # read once for the claims and the pairs
        passages = {item.get("id"): item for item in sections.read_passages(project)}
    except (OSError, ValueError) as failure:
        problems.append("passages.jsonl: %s" % failure)
        passages = {}
    claims = _claim_rows(project, passages, problems)
    contradictions, merges = _pairs(project, passages, problems)
    return {
        "documents": _document_rows(project, held),
        "concerns": _concern_rows(project, problems),
        "claims": claims,
        "unverifiable": [{key: claim[key] for key in ("id", "section", "heading", "text", "reason")} for claim in claims
                         if claim["standing"] == "unverifiable"],
        "contradictions": contradictions,
        "merges": merges,
        "material": _material(project, problems),
        "problems": problems,
    }


# --- Marks: every batch put before the owner, each item whole ------------------------------------------------------


def _drawn(project, problems):
    """`{batch id: {plot or table id: its entry}}`: what each accepted drawing drew, by the `plots` batch it opened."""
    from wayline import drawings
    try:
        records = drawings.read_records(project)
    except (OSError, ValueError) as failure:
        problems.append("the drawings: %s" % failure)
        return {}
    found = {}
    for record in records:
        if record.get("batch"):
            entries = found.setdefault(record["batch"], {})
            for kind, key in (("plot", "plots"), ("table", "tables")):
                for entry in record.get(key) or []:
                    if isinstance(entry, dict) and entry.get("id"):
                        entries[entry["id"]] = (kind, entry)
    return found


def _plot_shown(drawn, ref):
    """A plot as its drawing drew it, its SVG and PNG as written beside it (never a re-render), with its three explanations;
    a table with its CSV, which opens in the viewer by the item's id."""
    kind, entry = drawn.get(ref) or (None, None)
    if entry is None:
        return None
    return {"kind": kind, "svg": entry.get("svg"), "png": entry.get("png"), "csv": entry.get("csv"), "chart_type": entry.get("chart_type"),
            "data_view": entry.get("data_view"), "caption": {"purpose": entry.get("purpose"), "data": entry.get("data"), "shows": entry.get("shows")}}


def _sides(passages, ref):
    """The two passages a merge or a contradiction names (`P5+P11`), each with where it stands, to show side by side: in
    the viewer for a pair's link, in Marks for a merges or contradictions batch's item."""
    sides = []
    for side in ref.split("+"):
        passage = passages.get(side) or {}
        sides.append({"id": side, "section": passage.get("section"), "heading": passage.get("heading"), "text": _words(passage.get("text"))})
    return sides


def _proposal_fields(record):
    """An objective change as the verifier judged it: what it changes, its reason, evidence, feasibility, and judgment."""
    change = "%s %s" % (record.get("kind"), record.get("objective"))
    if record.get("successor"):
        change += ' as "%s"' % record["successor"]
    feasibility = record.get("feasibility") if isinstance(record.get("feasibility"), dict) else None
    upheld = record.get("upheld")
    judgment = None if upheld is None else "%s: %s" % ("upheld" if upheld else "not upheld", record.get("why") or "no reason given")
    return [[name, value] for name, value in (
        ("change", change), ("reason", record.get("reason")), ("evidence", ", ".join(record.get("evidence") or []) or None),
        ("feasibility", "%s: %s" % (feasibility.get("verdict"), feasibility.get("reasoning")) if feasibility else None),
        ("judgment", judgment), ("answer", record.get("answer")), ("from", "ticket %s" % record["ticket"] if record.get("ticket") else None))
        if value]


def _mark_item(batch, item, read):
    """One item whole: its own fields, whether a click may still change it, and what its kind shows of it."""
    from wayline import batches
    shown = dict(item, changeable=batches.changeable(item))
    kind = batch["kind"]
    if kind == "plots":
        shown["plot"] = _plot_shown(read["drawn"].get(batch["id"], {}), item["ref"])
    elif kind in ("merges", "contradictions") and "+" in item["ref"]:
        shown["sides"] = _sides(read["passages"], item["ref"])
    elif kind == "objective_changes" and item["ref"] in read["proposals"]:
        shown["fields"] = _proposal_fields(read["proposals"][item["ref"]])
    return shown


def _batch_row(batch, read):
    open_items = sum(1 for item in batch["items"] if item["mark"] is None)
    return {"id": batch["id"], "kind": batch["kind"], "title": batch["title"], "decision": batch["decision"], "status": batch["status"],
            "open": open_items, "marks": list(batch["items"][0]["marks"]), "defaults": sum(1 for item in batch["items"] if item["mark"] is None
                                                                                       and item["default"] is not None),
            "items": [_mark_item(batch, item, read) for item in batch["items"]]}


def marks_snapshot(project):
    """The `(mtime_ns, size)` of each batch and drawing record, which Marks reads and the ledger's snapshot does not scan:
    only Marks' tag moves with them, so a mark moves no other view's."""
    found = {}
    for folder in ("batches", "drawings"):
        found.update(_stamps(Path(project) / RESEARCH / folder, folder + "/"))
    return found


def marks_view(project):
    """The Marks view: every open batch, oldest first, each with its unsettled count and its items whole (a plot's SVG with
    its three explanations, a merge's or a contradiction's two texts side by side, a proposal's reason, evidence,
    feasibility, and judgment, and every other kind as its batch carries it), then the settled batches, newest first, whose
    marks given here may still change until their producer acts on them."""
    from wayline import batches, objective_changes, sections
    project = Path(project).resolve()
    problems, held = [], []
    for identifier in batches.batch_ids(project):
        try:
            held.append(batches.read_batch(project, identifier))
        except (OSError, ValueError) as failure:  # a batch file a hand broke: said, and the other batches still show
            problems.append("batch %s: %s" % (identifier, failure))
    kinds = {batch["kind"] for batch in held}
    read = {"drawn": _drawn(project, problems) if "plots" in kinds else {}, "passages": {}, "proposals": {}}
    if kinds & {"merges", "contradictions"}:
        try:
            read["passages"] = {item.get("id"): item for item in sections.read_passages(project)}
        except (OSError, ValueError) as failure:
            problems.append("passages.jsonl: %s" % failure)
    if "objective_changes" in kinds:
        read["proposals"] = {record["id"]: record for record in objective_changes.read_proposals(_events(project, problems))}
    rows = [_batch_row(batch, read) for batch in held]
    return {"batches": [row for row in rows if row["status"] == batches.OPEN],
            "settled": [row for row in reversed(rows) if row["status"] != batches.OPEN], "problems": problems}


# --- "Waiting on you" and the projects page ----------------------------------------------------------------------

# The account's lines that name a ticket, which the strip links to: `- Decision ticket 12 ...`, `- Ticket 7, ...`.
_WAITING_TICKET = re.compile(r"^- (?:Decision ticket|Ticket) ([1-9][0-9]*)\b")


def _waiting_items(lines):
    items = []
    for line in lines:
        found = _WAITING_TICKET.match(line)
        items.append({"text": line[2:] if line.startswith("- ") else line, "item": found.group(1) if found else None})
    return items


def waiting_view(project):
    """The "Waiting on you" strip every view shows: the account's section, line by line, each a ticket's with its link."""
    from wayline import account
    project = Path(project).resolve()
    problems = []
    view = _account(project, problems)
    lines = (view or {}).get("sections", {}).get(account.TITLES[2], [])
    return {"count": len(lines), "items": _waiting_items(lines), "decided": (view or {}).get("decided"), "path": ACCOUNT_MD,
            "problems": problems}


def _runs(events):
    """Where the project's runs stand: `running` since a `run_started` no `run_ended` closed, else `ended` with its reason,
    else `not started`."""
    from wayline.ledger import RUN_ENDED, RUN_STARTED
    state = {"state": "not started", "since": None, "reason": None}
    for event in events:
        if event.get("event") == RUN_STARTED:
            state = {"state": "running", "since": event.get("ts"), "reason": None}
        elif event.get("event") == RUN_ENDED:
            state = {"state": "ended", "since": event.get("ts"), "reason": (event.get("payload") or {}).get("reason")}
    return state


def conductor_alive(project):
    """Whether a conductor holds the project's lock now: no file moves when one dies, so a view's tag carries this too."""
    from wayline.ledger import conductor_holder
    try:
        return conductor_holder(project) is not None
    except OSError:  # a heartbeat that cannot be opened names no conductor the page can show
        return False


# The account's part of each project's row, by project, with the ledger snapshot it was read under: the projects page is
# polled every few seconds by every open page, and one project's journal moving must not re-read every other account.
_SUMMARIES = {}


def project_summary(project, snapshot=None):
    """The projects page's row for one current project: the account's standing line, the run state, the waiting count,
    and how many documents it holds (the page offers Inherited only for a project with one, ticket 111).

    `snapshot` is the project's ledger snapshot: the account's part is read again only once it moved. Whether a
    conductor holds the project is asked at every call, since no file moves when one dies."""
    project = Path(project).resolve()
    held = _SUMMARIES.get(str(project))
    if snapshot is None or held is None or held[0] != snapshot:
        problems = []
        events = _events(project, problems)
        view = _account(project, problems, events) or {}
        held = (snapshot, {"standing": view.get("stands"), "runs": _runs(events), "waiting": view.get("waiting"),
                           "documents": _document_count(project, problems), "problems": problems})
        if snapshot is not None:
            _SUMMARIES[str(project)] = held
    summary = held[1]
    return {"standing": summary["standing"], "run_state": dict(summary["runs"], conductor=conductor_alive(project)),
            "waiting": summary["waiting"], "documents": summary["documents"], "problems": list(summary["problems"])}


_ASKED = re.compile(r"#([1-9][0-9]*)\Z")


def decision_kind(project, origin, read=None):
    """`(kind, about)` of an open decision ticket by its origin: the new kinds Run gives a card of its own, each with its
    fields, or `("decision", {})` for any other. `read` caches the records the kinds look things up in, across one view."""
    from wayline import concerns, objective_changes, software, stopping, verification
    read = {} if read is None else read
    origin = str(origin or "")
    asked = _ASKED.search(origin)
    asked = int(asked.group(1)) if asked else None
    if objective_changes.is_changes_ticket(origin):
        return "objective_changes", {"round": asked}
    tool = software.asked({"kind": "decision", "origin": origin})
    if tool is not None:
        from wayline.tools import Tools
        name, gap = tool
        if "tools" not in read:
            read["tools"] = Tools()
        entry = read["tools"].entry(name)
        return "software", {"tool": name, "gap": gap, "licensed": name in software.LICENSED, "recorded": bool(entry),
                            "version": (entry or {}).get("version")}
    objective = stopping.frontier_objective(origin)
    if objective is not None:
        from wayline.objectives import named
        if "objectives" not in read:
            read["objectives"] = _read_objectives(project, [])
        return "empty_frontier", {"objective": objective, "asked": asked, "text": (named(read["objectives"], objective) or {}).get("text")}
    concern = concerns.concern_of(origin)
    if concern is not None:
        if "concerns" not in read:
            try:
                read["concerns"] = concerns.read_concerns(project)
            except (OSError, ValueError):
                read["concerns"] = []
        found = next((item for item in read["concerns"] if item.get("id") == concern), {})
        sources = [source.get("text") for source in found.get("sources") or [] if isinstance(source, dict) and source.get("text")]
        return "concern", {"concern": concern, "asked": asked, "sources": sources, "status": found.get("status")}
    item = verification.material_of(origin)
    if item is not None:
        if "material" not in read:
            try:
                read["material"] = verification.read_record(project)["material"]
            except (OSError, ValueError):
                read["material"] = []
        found = next((entry for entry in read["material"] if entry.get("id") == item), {})
        return "verification_gap", {"item": item, "asked": asked, "missing": found.get("kind"), "what": found.get("item"),
                                    "heading": found.get("heading")}
    return "decision", {}


def software_snapshot(project):
    """The `(mtime_ns, size)` of what Software reads outside the ledger: `tools.json`, the environment's record, a move's marker."""
    from wayline import environment
    from wayline.tools import TOOLS_JSON, tools_home
    found = {}
    for key, path in (("tools", tools_home() / TOOLS_JSON), ("env", Path(project) / environment.WAYLINE_DIR / environment.RECORD),
                      ("move", Path(project) / environment.WAYLINE_DIR / environment.MOVING)):
        try:
            stamp = path.stat()
        except OSError:
            continue
        found[key] = (stamp.st_mtime_ns, stamp.st_size)
    return found
# The rows of a table the viewer shows; the CSV, downloadable from the viewer, holds them all (as a report shows 50).
TABLE_ROWS = 51

_PLOT = re.compile(r"^(R[1-9][0-9]*)\.(T?)[1-9][0-9]*$")
_REPORT = re.compile(r"^(R[1-9][0-9]*)-([1-9][0-9]*)$")


def _item(kind, view, identifier, title, path, **more):
    return dict({"found": True, "kind": kind, "view": view, "id": identifier, "title": title, "path": path}, **more)


def item_view(project, item):
    """What the item link `#/<project>/<item>` opens, `{found, kind, view, id, title, path, ...}`, or None when the project
    holds no such item (the module's docstring lists the kinds)."""
    project = Path(project).resolve()
    if not ITEM_ID.match(str(item or "")):
        return None
    if item == "report":  # a file not rendered yet is no item: the page says "not found", not an error
        return _item("report", RESEARCH_VIEW, item, "The general report", REPORT_MD) if (project / REPORT_MD).is_file() else None
    if item == "account":
        return _item("account", RUN_VIEW, item, "The account", ACCOUNT_MD) if (project / ACCOUNT_MD).is_file() else None
    if item.isdigit():
        return _ticket_item(project, int(item))
    if item in _PAPER_FILES:
        return _paper_file_item(project, item)
    resolve = _BY_LETTER.get(item[0])
    if resolve is not None:
        return resolve(project, item)
    if _PLOT.match(item):
        return _plot_item(project, item)
    if _REPORT.match(item):
        return _report_item(project, item)
    return _result_item(project, item)


# --- Paper's and Inherited's items (ticket 111) ---------------------------------------------------------------------

# What a title shows of a passage or a concern before it is cut: the viewer's bar is one line.
TITLE_CHARS = 160


def _clip(text):
    text = " ".join(str(text or "").split())
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"


def _paper_files():
    from wayline import sections
    files = {name: ("section", sections.TITLES[name], "%s/%s" % (RESEARCH, sections.section_path(name))) for name in sections.SECTIONS}
    files["outline"] = ("outline", "The outline", OUTLINE_MD)
    return files


def _paper_file_item(project, name):
    kind, title, path = _PAPER_FILES[name]
    return _item(kind, PAPER_VIEW, name, title, path) if (project / path).is_file() else None


def _passage_item(project, identifier):
    """A passage opens its section at its heading: an inherited claim over Inherited with its standing, any other over Paper;
    a pair `P5+P11` of the repeated-claims check opens both claims side by side."""
    from wayline import sections
    if "+" in identifier:
        return _pair_item(project, identifier)
    passages = sections.read_passages(project)
    passage = next((item for item in passages if item.get("id") == identifier), None)
    if passage is None:
        return None
    claim = sections.is_inherited(passage) and passage.get("standing") in sections.STANDINGS
    status, shown = (passage.get("standing") if claim else None), passage
    later = [item for item in passages + sections.read_findings(project) if item.get("replaces") == identifier]
    if later:
        # Replaced: by this project's evidence (a verdict on an inherited claim), or by a later word. It opens where the
        # replacement stands, unless a withdrawal took it out of the section.
        replacement = next((item for item in later if not sections.is_inherited(item) and item.get("evidence")), later[-1])
        status = "verified" if claim and replacement.get("evidence") and not sections.is_inherited(replacement) else "replaced"
        if not replacement.get("withdrawn"):
            shown = dict(replacement, section=replacement.get("section") or sections.RESULTS)
    else:
        replacement = None
    return _item("claim" if claim else "passage", INHERITED_VIEW if claim else PAPER_VIEW, identifier, _clip(_words(passage.get("text"))),
                 "%s/%s" % (RESEARCH, sections.section_path(shown.get("section"))), focus=shown.get("heading"), status=status,
                 replaced_by=(replacement or {}).get("id"))


# A pair's kind by what came of it: a merge (standing, or split by the owner since) or a contradiction (or one dismissed).
_PAIR_KINDS = {"merged": "merge", "split": "merge", "split_late": "merge", "contradiction": "contradiction", "dismissed": "contradiction"}


def _pair_item(project, identifier):
    from wayline import repeats, sections
    first, second = identifier.split("+")
    try:
        held = repeats.read_record(project)["pairs"]
    except (OSError, ValueError):  # the Inherited view says why; a link to a pair it cannot read names nothing
        return None
    entry = next((entry for entry in held if (entry["a"], entry["b"]) == (first, second)), None)
    if entry is None:
        return None
    sides = _sides({item.get("id"): item for item in sections.read_passages(project)}, identifier)
    kind = _PAIR_KINDS.get(entry["outcome"], "pair")
    fields = [["why", entry.get("why")], ["outcome", entry["outcome"]]]
    if kind == "merge":
        fields += [["kept", entry.get("text")], ["merged into", entry.get("passage")]]
    title = "Merged at setup" if kind == "merge" else "Contradicting claims" if kind == "contradiction" else "Claims compared"
    return _item(kind, INHERITED_VIEW, identifier, title, None, status=entry["outcome"], sides=sides,
                 fields=[pair for pair in fields if pair[1]])


def _document_item(project, identifier):
    document = next((document for document in _documents(project, []) if document.get("id") == identifier), None)
    if document is None:
        return None
    path, focus = _document_path(project, document)
    return _item("document", INHERITED_VIEW, identifier, document.get("title"), path, focus=focus, status=document.get("kind"))


def _concern_item(project, identifier):
    from wayline import concerns
    row = next((row for row in _concern_rows(project, []) if row["id"] == identifier), None)
    if row is None:
        return None
    return _item("concern", INHERITED_VIEW, identifier, _clip(row["text"]), "%s/%s" % (RESEARCH, concerns.CONCERNS_MD), focus=identifier,
                 status=row["status"])


# The heading `VERIFICATIONS.md` lists the missing material under, which a missing item's link scrolls to.
MISSING_MATERIAL = "Missing material"


def _material_item(project, identifier):
    from wayline import verification
    found = next((item for item in _material(project, []) if item["id"] == identifier), None)
    if found is None:
        return None
    return _item("material", INHERITED_VIEW, identifier, found["item"], "%s/%s" % (RESEARCH, verification.VERIFICATIONS_MD),
                 focus=MISSING_MATERIAL, status=found["reply"] or "waiting")


def _ticket_item(project, number):
    from wayline.tickets import filename, read_tickets, tickets_dir
    for fields in read_tickets(project):
        if fields["id"] == number:
            path = (tickets_dir(project) / filename(fields)).relative_to(project).as_posix()
            kind = "decision" if fields.get("kind") == "decision" else "ticket"
            return _item(kind, RUN_VIEW, str(number), fields.get("title"), path, status=fields.get("status"))
    return None


def _objective_item(project, identifier):
    from wayline.objectives import named
    found = named(_read_objectives(project, []), identifier)
    if found is None:
        return None
    return _item("objective", RESEARCH_VIEW, identifier, found.get("text"), OBJECTIVES_MD, focus=identifier, status=found.get("status"))


def _live_result(project, identifier):
    from wayline import results as results_module
    return next((result for result in results_module.read_results(project) if result.id == identifier), None)


def _result_item(project, identifier):
    from wayline import reports
    result = _live_result(project, identifier)
    if result is None:
        return None
    current = reports.links(project, identifier)[0]
    if current is None:  # before its first drawing a result is its heading in the general report
        return _item("result", RESEARCH_VIEW, identifier, result.heading, REPORT_MD, focus=identifier, status=result.standing)
    return _item("result", RESEARCH_VIEW, identifier, result.heading, _report_entry(current, {})["path"], status=result.standing)


def _report_item(project, name):
    path = _report_entry(name, {})["path"]
    if not (project / path).is_file():
        return None
    return _item("report", RESEARCH_VIEW, name, "Report %s" % name, path)


def _plot_item(project, identifier):
    from wayline import drawings, reports
    plot = next((plot for plot in drawings.read_plots(project)["plots"] if plot.get("id") == identifier), None)
    entry, kind = reports.plot_entries(project).get(identifier) or (None, None)
    if plot is None or entry is None:
        return None
    if kind == "table":
        rows = reports.read_rows(project / str(entry.get("csv") or ""))
        return _item("table", RESEARCH_VIEW, identifier, entry.get("data_view") or identifier, entry.get("csv"), status=plot.get("status"),
                     rows=(rows or [])[:TABLE_ROWS], unreadable=rows is None,
                     caption={"purpose": entry.get("purpose"), "data": entry.get("data"), "shows": entry.get("shows")})
    return _item("plot", RESEARCH_VIEW, identifier, entry.get("chart_type") or identifier, entry.get("png"), status=plot.get("status"),
                 caption={"purpose": entry.get("purpose"), "data": entry.get("data"), "shows": entry.get("shows")})


# How `item_view` resolves an id past the words and the tickets: a section's or the outline's name, else by its letter.
_PAPER_FILES = _paper_files()
_BY_LETTER = {"O": _objective_item, "P": _passage_item, "D": _document_item, "K": _concern_item, "M": _material_item}

