"""The dashboard's routed views (Implementation Decision 17; ticket 110): what each view reads, and what an item link opens.

The dashboard is five hash-routed views behind the project tabs; this module builds the JSON of the two this ticket
adds, **Research** and the additions to **Run**, the "Waiting on you" strip every view shows, the projects page's row
for each project, and the resolution of an item link `#/<project>/<id>`. Paper and Inherited (ticket 111) and Marks
(ticket 112) follow. Like every view the dashboard polls, each function here reads and never writes: no lock, no
render, no model, so the dashboard spends no tokens.

**Thin lists.** A view lists items, each an id, a title, a status, and what opens it; it never carries a rendered
file. Every Markdown file code renders (the general report, a result's reports, the account, `OBJECTIVES.md`) is
named here by its path and read only in the popup viewer, so nothing is rendered twice.

**Item ids.** An item link names one of:

- `O3`, an objective, which opens `OBJECTIVES.md` at its heading over Research;
- `R4`, a result, which opens its current report (the general report at its heading before its first drawing);
- `R4.3`, a plot, and `R4.T1`, a table, which open the image with its explanation, or the table's rows;
- `R4-2`, one of a result's reports, and `report`, the general report;
- `12`, a ticket or a decision ticket, which opens its file over Run;
- `account`, `research/ACCOUNT.md`, over Run.

An id that names nothing resolves to None, and the server answers 404 with one line the page shows in the viewer.

**New since you looked.** Each current report and the general report carry the `sha256` their last `report_rendered`
journaled. The page keeps, in its own browser, the hash each report had when the owner last opened it, and marks a
report whose hash moved with a dot. A renewed report notifies nowhere: nothing here or in the renders sends a notice.
"""

import re
from pathlib import Path

from wayline.ledger import REPORT_RENDERED, TICKET_CANCELLED, Ledger
from wayline.project import RESEARCH, ProjectError, read_harness

__all__ = ["VIEWS", "research_view", "item_view", "ITEM_ID"]

# The views this ticket routes; Paper and Inherited (111) and Marks (112) join them.
VIEWS = ("research", "run")
RESEARCH_VIEW, RUN_VIEW = VIEWS

REPORT_MD = RESEARCH + "/REPORT.md"
OBJECTIVES_MD = RESEARCH + "/OBJECTIVES.md"

# Every id an item link may name, and nothing else: the route matches it before anything is read.
ITEM_ID = re.compile(r"^(?:O[1-9][0-9]*|R[1-9][0-9]*(?:\.T?[1-9][0-9]*|-[1-9][0-9]*)?|[1-9][0-9]*|report|account)$")


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
    """The projects page's row for one current project: the account's standing line, the run state, the waiting count.

    `snapshot` is the project's ledger snapshot: the account's part is read again only once it moved. Whether a
    conductor holds the project is asked at every call, since no file moves when one dies."""
    project = Path(project).resolve()
    held = _SUMMARIES.get(str(project))
    if snapshot is None or held is None or held[0] != snapshot:
        problems = []
        events = _events(project, problems)
        view = _account(project, problems, events) or {}
        held = (snapshot, {"standing": view.get("stands"), "runs": _runs(events), "waiting": view.get("waiting"), "problems": problems})
        if snapshot is not None:
            _SUMMARIES[str(project)] = held
    summary = held[1]
    return {"standing": summary["standing"], "run_state": dict(summary["runs"], conductor=conductor_alive(project)),
            "waiting": summary["waiting"], "problems": list(summary["problems"])}


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
    if item.startswith("O"):
        return _objective_item(project, item)
    if _PLOT.match(item):
        return _plot_item(project, item)
    if _REPORT.match(item):
        return _report_item(project, item)
    return _result_item(project, item)


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

