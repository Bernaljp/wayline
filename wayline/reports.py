"""Current and earlier reports: one result at full depth, version by version (Implementation Decision 17; ticket 101).

**Versions.** `research/reports/R<n>-<v>.md` is rendered by code alone. A result has no report until its first drawing
is accepted; each accepted drawing starts the next version (1, 2, and on, counting accepted drawings only, so a failed
drawing starts none). The latest version is the result's **current report**: every render pass re-renders it, with the
findings filed since its drawing under "Since the plots were drawn" and the findings its drawing was drawn over that
were since replaced marked there. The next accepted drawing freezes it as an **earlier report**, which no later render
writes. A result merged into another starts no version again: its current report freezes at the merge, and its
reports are listed as earlier reports of the result it went into.

**What a report shows.** Only current findings, each replacement with its one-line note and each negative one marked;
then each plot with its Purpose, Data, and What it shows (the drawing's own plots and those it carried, as they were
last drawn); the tables, each its own item rendered from its CSV; then the synthesis, the headline, what can and
cannot be inferred, and the open questions.

**The edit rule.** Reports are read-only. A report whose sha256 differs from its last `report_rendered` (`report`
the result, `version` the version) was edited by hand: it is committed as it stood, journaled as `edited` on a
`report_rendered` of that report, and listed in the banner of its result's current report from then on. A current
report is rendered over; an earlier one is left as the owner left it. Code never takes either in.

**A plot the owner asks for** (`ask_plot`) is a small drawing of its result on the owner's word: its brief carries the
request, and at acceptance the result's other current plots are carried into the new version unchanged. A plot of data
no result holds is an ordinary analysis ticket.
"""

import csv
import hashlib
import re

from wayline import drawings, sections, tickets
from wayline import results as results_module
from wayline.ledger import REPORT_RENDERED, TICKET_CREATED, ledger_for, now_ts

__all__ = ["REPORTS_DIR", "SINCE", "ReportError", "Index", "versions", "report_name", "report_path", "links", "plot_entries",
           "render_reports", "ask_plot"]

REPORTS_DIR = "reports"
SINCE = "Since the plots were drawn"
MAX_ROWS = 50  # the rows of a table a report shows; the CSV holds them all

_NAME = re.compile(r"^(R[1-9][0-9]*)-([1-9][0-9]*)\.md$")


class ReportError(ValueError):
    """A plot request code refuses: a result that is not live, or one whose drawing is under way."""


def report_name(result_id, version):
    return "%s-%d" % (result_id, version)


def report_path(result_id, version):
    """`reports/R4-2.md` under `research/`."""
    return "%s/%s.md" % (REPORTS_DIR, report_name(result_id, version))


class Index:
    """The accepted drawings and the clustering, read once, which every report and link of one render pass reads."""

    def __init__(self, project_or_ledger):
        book = ledger_for(project_or_ledger)
        self.clusters = results_module.load(book)
        self.accepted = {}
        self._entries = None
        for record in drawings.accepted_records(book):
            self.accepted.setdefault(record.get("result"), []).append(record)

    def versions(self, result_id):
        return list(enumerate(self.accepted.get(result_id) or [], start=1))

    def links(self, result_id):
        own = [report_name(result_id, version) for version, _ in self.versions(result_id)]
        merged = [report_name(source, version) for source in _merged_sources(self.clusters, result_id)
                  for version, _ in self.versions(source)]
        return (own[-1] if own else None), own[:-1] + merged

    def entries(self):
        """`{plot id: (entry, kind)}`: each plot or table as the drawing accepted last that drew it explained it."""
        if self._entries is not None:
            return self._entries
        found = self._entries = {}
        records = [record for held in self.accepted.values() for record in held]
        for record in sorted(records, key=lambda record: str(record.get("closed") or "")):
            for kind, key in (("plot", "plots"), ("table", "tables")):
                for entry in record.get(key) or []:
                    found[entry["id"]] = (entry, kind)
        return found


def versions(project_or_ledger, result_id):
    """The result's accepted drawings in order, `[(version, record)]`: version 1 is its first accepted drawing."""
    return list(enumerate(drawings.accepted_records(project_or_ledger, result_id), start=1))


def _merged_sources(clusters, result_id):
    """The results merged into `result_id`, directly or through another merged one, in id order."""
    found = []
    for identifier, item in sorted(clusters.results.items(), key=lambda pair: int(pair[0][1:])):
        if identifier != result_id and item.get("merged_into") and clusters.resolve(identifier) == result_id:
            found.append(identifier)
    return found


def links(project_or_ledger, result_id):
    """`(current, earlier)` report names of a live result: its latest version (None before its first accepted drawing),
    then its earlier versions and every report of the results merged into it."""
    return Index(project_or_ledger).links(result_id)


def plot_entries(project_or_ledger):
    """`{plot id: (entry, kind)}`: each plot or table as the drawing accepted last that drew it explained it."""
    return Index(project_or_ledger).entries()


def _shown(record, entries):
    """The plots and the tables a version shows: its drawing's own and those it carried, in id order."""
    plots = [(entry, "plot") for entry in record.get("plots") or []] + [(entry, "table") for entry in record.get("tables") or []]
    plots += [entries[identifier] for identifier in record.get("carried") or [] if identifier in entries]
    order = drawings.plot_order
    return (sorted((entry for entry, kind in plots if kind == "plot"), key=lambda entry: order(entry["id"])),
            sorted((entry for entry, kind in plots if kind == "table"), key=lambda entry: order(entry["id"])))


def _explained(entry, image_root):
    lines = ["### %s. %s%s" % (entry["id"], entry.get("chart_type") or "table", " (headline)" if entry.get("headline") else ""), ""]
    if entry.get("png"):
        lines.extend(["![%s](%s%s)" % (entry["id"], image_root, entry["png"]), ""])
    lines.extend(["- Purpose: %s" % entry.get("purpose"), "- Data: %s" % entry.get("data"), "- What it shows: %s" % entry.get("shows")])
    return lines


def _table(project, entry):
    path = project / str(entry.get("csv") or "")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = [row for row in csv.reader(handle) if row]
    except (OSError, UnicodeDecodeError, csv.Error):
        return ["(The CSV `%s` could not be read.)" % entry.get("csv")]
    if not rows:
        return ["(The CSV `%s` is empty.)" % entry.get("csv")]
    width = max(len(row) for row in rows)
    cell = lambda text: " ".join(str(text).split()).replace("|", "\\|")  # noqa: E731
    lines = ["| %s |" % " | ".join(cell(item) for item in rows[0] + [""] * (width - len(rows[0]))), "|%s" % "---|" * width]
    for row in rows[1:MAX_ROWS + 1]:
        lines.append("| %s |" % " | ".join(cell(item) for item in row + [""] * (width - len(row))))
    if len(rows) - 1 > MAX_ROWS:
        lines.append("")
        lines.append("(%d more rows in `%s`.)" % (len(rows) - 1 - MAX_ROWS, entry.get("csv")))
    return lines


def _replacer(result, identifier):
    """The current finding that replaces `identifier`, following a chain of replacements, or None."""
    current = {finding["id"] for finding in result.current}
    by_replaced = {finding.get("replaces"): finding["id"] for finding in result.findings if finding.get("replaces")}
    seen = set()
    while identifier in by_replaced and identifier not in seen:
        seen.add(identifier)
        identifier = by_replaced[identifier]
        if identifier in current:
            return identifier
    return None


def _edits(events, names):
    """The banner lines of the hand edits of the reports `names`, oldest first."""
    lines = []
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") != REPORT_RENDERED or "edited" not in payload or not payload.get("version"):
            continue
        name = report_name(payload.get("report"), payload["version"])
        if name in names:
            commit = payload.get("edited")
            lines.append("- %s was edited by hand (noticed %s). The edit was kept as it stood (%s) and is not taken in." % (
                report_path(payload.get("report"), payload["version"]), str(event.get("ts") or "")[:16].replace("T", " ") + "Z",
                "commit `%s`" % commit[:12] if commit else "it could not be committed"))
    return lines


def _text(book, result, version, record, entries, manifest, edits):
    from wayline import provenance  # the provenance module reads this one to render the general report
    name = report_name(result.id, version)
    lines = ["# %s. %s (%s)" % (name, result.heading, result.standing), "",
             "Code renders this report of %s from the ledger alone; it is version %d, started by the accepted drawing %s. It "
             "is never read back: an edit of it is kept in git as it stood and is not taken in, and the next accepted drawing "
             "freezes it as an earlier report." % (result.id, version, drawings.drawing_name(result.id, record["version"]))]
    if edits:
        lines += [""] + edits
    drawn_over, ticket = set(record.get("findings") or []), record.get("ticket")
    main = [finding for finding in result.current if finding["id"] in drawn_over or finding.get("ticket") == ticket]
    since = [finding for finding in result.current if finding not in main]
    gone = [identifier for identifier in sorted(drawn_over) if identifier not in {finding["id"] for finding in result.current}]
    lines += ["", "## Findings", ""]
    lines += [provenance.finding_line(finding, manifest) for finding in main] or ["None of the findings it was drawn over is current."]
    if since or gone:
        lines += ["", "## %s" % SINCE, ""]
        lines += [provenance.finding_line(finding, manifest) for finding in since]
        for identifier in gone:
            replacer = _replacer(result, identifier)
            lines.append("- `%s` was replaced by `%s`." % (identifier, replacer) if replacer else "- `%s` is no longer current." % identifier)
    plots, tables = _shown(record, entries)
    lines += ["", "## Plots", ""]
    for entry in plots:
        lines += _explained(entry, "../../") + [""]
    if not plots:
        lines += ["No plot.", ""]
    if tables:
        lines += ["## Tables", ""]
        for entry in tables:
            lines += _explained(entry, "../../") + [""] + _table(book.project, entry) + [""]
    lines += ["## Synthesis", "", record.get("synthesis") or "None.", "", "## Headline", "", record.get("headline") or "None.", ""]
    for title, key in (("What can be inferred", "can_infer"), ("What cannot be inferred", "cannot_infer"), ("Open questions", "open_questions")):
        lines += ["## %s" % title, ""] + (["- %s" % item for item in record.get(key) or []] or ["None."]) + [""]
    return provenance.render_citations("\n".join(lines))


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _last_renders(events):
    """`{(result, version): the last report_rendered payload}` of the per-result reports."""
    found = {}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") == REPORT_RENDERED and payload.get("version"):
            found[(payload.get("report"), payload["version"])] = payload
    return found


def render_reports(project_or_ledger):
    """Render every live result's current report and keep the edit rule on every report; returns the names written.

    A render that would leave a current report as it is writes and journals nothing.
    """
    from wayline import account
    from wayline.provenance import read_manifest
    book = ledger_for(project_or_ledger)
    written = []
    with book.lock():
        events, _ = book.read_events()
        last = _last_renders(events)
        folder = book.research / REPORTS_DIR
        # The edit rule first, on every report on disk, current and earlier.
        noticed = {}
        for path in sorted(folder.glob("R*-*.md")) if folder.is_dir() else ():
            found = _NAME.match(path.name)
            key = (found.group(1), int(found.group(2))) if found else None
            if key is None or key not in last or _digest(path.read_text(encoding="utf-8")) == last[key].get("sha256"):
                continue
            noticed[key] = account.commit_edit(book.project, "%s/%s" % (REPORTS_DIR, path.name))
        current = {}
        index = Index(book)
        for result in results_module.read_results(book):
            held = index.versions(result.id)
            if held:
                current[(result.id, held[-1][0])] = (result, held[-1][1])
        stamp = now_ts()
        for key, commit in noticed.items():
            if key in current:
                continue  # rendered over below, with the edit on its render
            path = book.research / report_path(*key)
            payload = {"report": key[0], "version": key[1], "sha256": _digest(path.read_text(encoding="utf-8")), "edited": commit or None}
            book.append_event(REPORT_RENDERED, payload, ts=stamp)
            events.append({"event": REPORT_RENDERED, "ts": stamp, "payload": payload})
        if not current:
            return written
        entries = index.entries()
        manifest = read_manifest(book)
        for key, (result, record) in sorted(current.items(), key=lambda pair: (int(pair[0][0][1:]), pair[0][1])):
            linked = index.links(result.id)
            names = {name for name in [linked[0]] + linked[1] if name}
            told = list(events)
            if key in noticed:
                told.append({"event": REPORT_RENDERED, "ts": stamp, "payload": {"report": key[0], "version": key[1], "edited": noticed[key]}})
            text = _text(book, result, key[1], record, entries, manifest, _edits(told, names))
            digest = _digest(text)
            path = book.research / report_path(*key)
            previous = last.get(key)
            if key not in noticed and previous is not None and previous.get("sha256") == digest and path.is_file():
                continue
            book.write_markdown(report_path(*key), text)
            payload = {"report": key[0], "version": key[1], "sha256": digest}
            if key in noticed:
                payload["edited"] = noticed[key] or None
            book.append_event(REPORT_RENDERED, payload, ts=stamp)
            written.append(report_name(*key))
    return written


def ask_plot(project, result_id, request):
    """The owner asks for a plot: a small drawing of `result_id` carrying its other plots, or, when `result_id` is None
    (data no result holds), an ordinary analysis ticket. Returns `{"kind", "ticket"}`."""
    request = " ".join(str(request or "").split())
    if not request:
        raise ReportError("say what the plot should show")
    if result_id is not None:
        try:
            ticket = drawings.draw_again(project, result_id, asked=request)
        except drawings.DrawingError as failure:
            raise ReportError(str(failure)) from None
        return {"kind": drawings.KIND, "ticket": ticket}
    book = ledger_for(project)
    with book.lock():
        identifier = tickets.next_id(book.project)
        fields = {
            "id": identifier, "title": "Plot asked for: %s" % request, "kind": "analysis", "difficulty": 2, "status": "open",
            "blocked_by": [], "touches": ["results/"], "resources": {"gpu": 0, "cpu": 1}, "role": "analyst", "skills": [],
            "acceptance": {}, "objectives": [], "context_pack": [], "origin": "plot asked for by the owner", "proposed_by": "human",
            "sections": list(sections.sections_for_kind("analysis")),
            "demo": request,
        }
        body = ("\n## The owner's request\n\n%s\n\nNo result holds this data yet: the analysis computes it and files its findings, "
                "and the result they join draws it at its next drawing.\n" % request)
        tickets.write_ticket(book, fields, body)
        book.append_event(TICKET_CREATED, {"ticket": identifier, "kind": "analysis", "proposed_by": "human", "origin": fields["origin"],
                                           "blocked_by": []}, ticket=identifier)
    return {"kind": "analysis", "ticket": identifier}
