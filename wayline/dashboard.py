"""The dashboard server (Implementation Decisions 8): the views of M1 and the actions of M4.

The dashboard is a client of the same functions the command calls, bound to localhost and reached
from the laptop through `ssh -L`. Its views read and never write the ledger; its actions call the
verbs' own functions in this process, which write through the ledger as the verbs do. `wayline
serve` starts it, prints the tunnel line, and stays in the foreground; `wayline-dashboard.service`,
which `init` installs and `run` starts when it is not active, keeps it alive (ticket 13).

Three decisions from `research-notes/08-dashboard-transport.md` are carried here as written, because
they were measured rather than guessed:

- **Transport is polling.** The journal tail asks `journal?since=<byte offset>` every 2 s and
  receives only what was appended; every other view polls every 5 s with `If-None-Match` and gets
  304 when nothing moved. Six pollers at 2 s cost 0.3% of one core, an SSE thread outlives the tab
  that opened it by up to half a minute, and HTTP/1.1 browsers cap an origin at six streams. The
  server-sent events alternative is kept behind `?transport=sse` (unchunked, `Connection: close`,
  `id:` set to the byte offset, `retry: 2000`, a `select()` dead-client check) so the owner can
  compare the two through the tunnel; it becomes the default for the logs view only if the 2 s tail
  latency is judged annoying (OPEN-20).
- **Change detection is one `os.scandir` snapshot** of `(st_mtime_ns, st_size)` per ledger
  directory, taken inside the poll handler behind a 1 s memo, not by a background thread and not by
  hashing contents (0.64 ms against 6 ms for 111 files). Size is half the key because Linux stamps
  inodes from the coarse clock, so two writes inside one jiffy share an `mtime_ns`.
- **The journal needs no snapshot at all.** It is append-only, so its byte length is its version
  and the tail's `since` offset is its cursor.

The token: bound to loopback the views need none (whoever reaches the port is already on the
machine or through the owner's tunnel). Bound wider, every request needs the random token from
`~/.wayline/dashboard.json`, which `serve` prints inside the URL. A browser attaches nothing of its
own to a `<link>` or a `<script>`, so the first request that presents the token in the URL is
answered with it in a `SameSite=Strict` cookie, and the page's own assets and polls carry that: the
rule stays "every request needs the token" rather than "the page loads and its stylesheet does
not". The actions of Implementation Decisions 8 require the token in the header, whatever the
bind, because a page open on the laptop could otherwise POST to the forwarded port, and a cookie
alone must never be enough to act. So the URL `serve` prints carries the token on every bind: the
page reads it from its own address and sends it with each action.

**The actions** (ticket 35) are `POST /api/projects/<id>/actions/<name>` for `answer`, `autonomy`,
`pause`, `resume`, `switch`, `cancel`, `rerun`, `pacing`, `model_fallback` (ticket 57), `ladder_changes` (ticket 64),
`feedback` (ticket 45: the feedback form, filed as `wayline feedback` files it, read back by `GET .../changes`), and
`intake`. Each calls the function its
verb calls and nothing else, so no action runs a shell. A JSON object carries the arguments, and
`intake` takes the dropped file itself as the body, with its name in `X-Wayline-Filename`. The reply
is JSON too: `{"ok": true, "action": ...}` with what the function reported, or `{"ok": false,
"error": ...}` under a 4xx status that says why nothing was done. A `switch` away from a project
whose conductor has to drain answers 202 at once and finishes in a thread, because the drain lasts
as long as that conductor's running workers do.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import select
import socket
import sys
import threading
import time
import zipfile
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from wayline import HARNESS_ROOT, TAG, dag, decisions
from wayline.ledger import TICKET_LAUNCHED, TICKET_NEEDS_HUMAN, TICKET_RESULT, Ledger, atomic_write, conductor_holder
from wayline.project import (
    FINDINGS, HARNESS_JSON, NEEDS_HUMAN_NOTES, RESEARCH, ProjectError, active_path, answer, control, home, is_project, policy_for, rung_label,
    read_active, read_harness, read_jobs, read_projects, set_autonomy, set_ladder_changes, set_model_fallback, set_pacing,
    status_view, steer_ticket, switch_project,
)
from wayline.provenance import FINDINGS_MD, MANIFEST as MANIFEST_JSON, read_manifest, sha256_of
from wayline.tickets import frontier, read_ticket, read_tickets, refresh_graph, tickets_dir

__all__ = [
    "DashboardError", "STATIC_ROOT", "LOOPBACK", "TOKEN_HEADER", "TOKEN_COOKIE", "SSE_RETRY_MS",
    "READINGS_TTL_S", "IDLE_TIMEOUT_S", "TAIL_LINES_MAX", "DashboardHandler", "DashboardServer",
    "dashboard_path", "read_settings", "record_settings", "project_ids", "projects_view", "find_dashboard_project",
    "ledger_snapshot", "etag", "overview_view", "journal_tail", "phase_from_events",
    "graph_svg", "tickets_view", "ticket_view", "log_path", "log_tail",
    "outputs_view", "byte_range", "download_target",
    "static_file", "tunnel_line", "serve_lines", "make_server", "serve", "serve_command",
    "ACTIONS", "FILENAME_HEADER", "JSON_BODY_MAX", "SWITCH_REPLY_S", "ActionConflict", "run_action", "dashboard_url", "is_terminal",
]

STATIC_ROOT = HARNESS_ROOT / "dashboard"
LOOPBACK = "127.0.0.1"
DASHBOARD_JSON = "dashboard.json"
TOKEN_HEADER = "X-Wayline-Token"
TOKEN_QUERY = "token"
TOKEN_COOKIE = "wayline_token"

# The measured defaults of research-notes 08; a project's harness.json may move the poll intervals.
SNAPSHOT_MEMO_S = 1.0
SSE_RETRY_MS = 2000
SSE_PING_S = 15.0
SSE_TICK_S = 0.5
# socketserver's default is 5; a wider bind takes more than one client (research-notes 08, loose ends).
WIDE_QUEUE_SIZE = 16
# How long the overview may reuse a live machine reading before it must take a fresh one; the
# page's own views poll at this cadence, so a reading is never more than one poll old.
READINGS_TTL_S = 5
# How long a kept-alive connection may sit idle before the server closes it and frees its thread.
IDLE_TIMEOUT_S = 30
# How far back a `tail=<lines>` read steps at a time, and the most lines it will answer with.
_TAIL_BLOCK_BYTES = 1 << 16
TAIL_LINES_MAX = 2000

# The phases of BRIEF Section 6, as the journal's `phase` events name them.
PHASES = ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/vnd.microsoft.icon",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}
# The documentation site's pages are model-written, so they are served in a sandbox: an opaque origin whose
# scripts can neither read the dashboard's pages (and the token they carry) nor act as the owner. The page's
# link never carries the token in its URL, which a script in the page could read (app.js `siteRow`).
SITE_CSP = "sandbox allow-scripts allow-popups"
JSON_TYPE = "application/json; charset=utf-8"
TEXT_TYPE = "text/plain; charset=utf-8"

# The actions of Implementation Decisions 8 this dashboard takes (ticket 35), in the order the spec lists them.
ACTIONS = ("answer", "autonomy", "pause", "resume", "switch", "cancel", "rerun", "pacing", "model_fallback", "ladder_changes", "intake", "feedback")
ACTION_ROUTE = re.compile(r"^/api/projects/(?P<project>[^/]+)/actions/(?P<name>[^/]+)/?$")
# The header an intake drop names its file in, and the largest JSON body any other action reads.
FILENAME_HEADER = "X-Wayline-Filename"
JSON_BODY_MAX = 64 * 1024
# How long a switch with no conductor to drain waits for its thread before it answers 202 all the same.
SWITCH_REPLY_S = 5.0


class DashboardError(ValueError):
    """A request the dashboard cannot serve, or a server it cannot start."""


# --- the per-machine dashboard settings ---------------------------------------------------------


class ActionConflict(DashboardError):
    """An action that cannot be taken now, because another like it is still under way (409)."""


def dashboard_path():
    return home() / DASHBOARD_JSON


def read_settings(port=None, bind=None, project=None):
    """`~/.wayline/dashboard.json`: the port, the bind, and the random URL token.

    The token is minted on first read and never rotated by a start, so a URL the owner bookmarked
    on the laptop keeps working across restarts. The file is 0600: it is a bearer credential for
    every view once the server is bound wider than loopback.

    The port and the bind come from the arguments, else the project's `harness.json`, else the
    shipped policy defaults; the file records what this start used, so the tick and the notifier can
    build the URL of a dashboard they did not start. The file never wins over `harness.json`: a
    `--port` passed once must not become the configured port forever.
    """
    path = dashboard_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    defaults = _dashboard_defaults(project)
    token = stored.get("token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
    settings = {
        "port": _port(port, defaults.get("port")),
        "bind": _first_string(bind, defaults.get("bind")) or LOOPBACK,
        "token": token,
        "poll_journal_s": defaults.get("poll_journal_s", 2),
        "poll_views_s": defaults.get("poll_views_s", 5),
    }
    record_settings(settings)
    return settings


def record_settings(settings):
    """Record the port, the bind, and the token of the server that is starting, 0600.

    `serve` calls this again once the socket is bound, so the file names the port the dashboard is
    actually on rather than the one it asked for.
    """
    path = dashboard_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    _store_settings(path, settings, stored if isinstance(stored, dict) else {})


def _dashboard_defaults(project):
    """The `dashboard` block of the project's `harness.json`, under the shipped policy defaults."""
    values = dict(policy_for(project).get("dashboard", {}))
    if project is not None:
        try:
            values.update(read_harness(project).get("dashboard", {}) or {})
        except (ProjectError, OSError):
            pass
    return values


def _store_settings(path, settings, stored):
    """Write the port, the bind, and the token back, 0600, when any of them changed.

    The file is created empty at 0600 before anything is written to it, because it holds a bearer
    credential: `atomic_write` gives its temp file the mode of the file it replaces, so a target
    that already exists at 0600 is never briefly world-readable, while chmod'ing afterwards leaves
    the token readable to every local account for the length of the write.
    """
    value = {"port": settings["port"], "bind": settings["bind"], "token": settings["token"]}
    if all(stored.get(key) == item for key, item in value.items()):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(path, 0o600)
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _port(*candidates):
    for candidate in candidates:
        if isinstance(candidate, bool):
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 65535:
            return value
    return 8765


def _first_string(*candidates):
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


# --- the projects and their ids ------------------------------------------------------------------


def project_ids(entries=None):
    """The id per project path: the directory name, disambiguated when two projects share one.

    A path is not a URL segment and an index is not stable across a registration, so the dashboard
    names a project by its directory, and by its directory plus eight hex of its path when that
    name is not unique. `/api/projects` carries the id it computed, so a client never derives one.
    """
    entries = read_projects() if entries is None else entries
    paths = [entry["path"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
    names = {}
    for path in paths:
        names[Path(path).name] = names.get(Path(path).name, 0) + 1
    ids = {}
    for path in paths:
        name = Path(path).name
        slug = _url_safe(name) or "project"
        if names[name] > 1 or slug != name:
            slug = "%s-%s" % (slug, hashlib.sha256(path.encode("utf-8")).hexdigest()[:8])
        ids[path] = slug
    return ids


def _url_safe(name):
    return re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-")


def projects_view(active=None, entries=None, settings=None):
    """Every registered project with its id, the active one marked: what the tabs are drawn from.

    A project whose directory no longer holds a `harness.json` stays in the list as `readable:
    false`, because a tab that vanished tells the owner less than a tab that says the path is gone.
    """
    entries = read_projects() if entries is None else entries
    active = read_active() if active is None else active
    active = Path(active).resolve() if active is not None else None
    ids = project_ids(entries)
    projects = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        path = Path(entry["path"])
        projects.append({
            "id": ids[entry["path"]],
            "name": entry.get("name") or path.name,
            "path": entry["path"],
            "harness_tag": entry.get("harness_tag"),
            "created": entry.get("created"),
            "active": active is not None and _same(path, active),
            "readable": is_project(path),
        })
    view = {
        "harness_tag": TAG,
        "active": next((item["id"] for item in projects if item["active"]), None),
        "projects": projects,
    }
    if settings is not None:
        view["settings"] = {
            "poll_journal_s": settings.get("poll_journal_s", 2),
            "poll_views_s": settings.get("poll_views_s", 5),
        }
    return view


def _same(path, other):
    try:
        return Path(path).resolve() == Path(other).resolve()
    except OSError:  # pragma: no cover - a path that cannot be resolved is not the active one
        return False


def find_dashboard_project(project_id, entries=None):
    """The project path an id names, or None; the id is the one `/api/projects` published."""
    entries = read_projects() if entries is None else entries
    for path, slug in project_ids(entries).items():
        if slug == project_id:
            return Path(path)
    return None


# --- change detection and ETags ------------------------------------------------------------------


def ledger_snapshot(project):
    """One `(st_mtime_ns, st_size)` per ledger file: the change detection of decision 8.

    The directories scanned are the ones the read-only views read: `harness.json`, the files at the
    root of `research/`, `research/tickets/`, `research/jobs/`, and the evolve loop's `research/feedback/`
    and `research/changes/` (ticket 45). Session streams and job logs are
    tailed by byte offset instead, which needs no snapshot. Dot files are skipped: they are the
    ledger's lock and the temp files an atomic write leaves for a few milliseconds, neither of which
    is content a view shows.
    """
    project = Path(project)
    research = project / RESEARCH
    values = {}
    _stat_into(values, project / HARNESS_JSON, HARNESS_JSON)
    for relative in ("", "tickets", "jobs", "feedback", "changes"):
        prefix = "/".join(part for part in (RESEARCH, relative) if part)
        try:
            with os.scandir(research / relative) as entries:
                for entry in entries:
                    if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        stamp = entry.stat()
                    except OSError:
                        continue
                    values["%s/%s" % (prefix, entry.name)] = (stamp.st_mtime_ns, stamp.st_size)
        except OSError:
            continue
    return values


def _stat_into(values, path, key):
    try:
        stamp = path.stat()
    except OSError:
        return
    values[key] = (stamp.st_mtime_ns, stamp.st_size)


def etag(*parts):
    """A quoted, opaque ETag over anything JSON can spell (RFC 9110 section 8.8.3).

    The route is part of every tag, so two views of one unchanged project cannot answer 304 to each
    other's `If-None-Match`.
    """
    text = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return '"%s"' % hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()


class Memo:
    """The 1 s memo of Implementation Decisions 8: one scan per second per key, not one per poller.

    A value is built outside the mutex, so a slow scan never queues every other request behind it;
    two pollers arriving together may both scan once, which costs a millisecond and no correctness.
    """

    def __init__(self, ttl=SNAPSHOT_MEMO_S, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._mutex = threading.Lock()
        self._entries = {}

    def get(self, key, build):
        now = self.clock()
        with self._mutex:
            stamped = self._entries.get(key)
        if stamped is not None and now - stamped[0] < self.ttl:
            return stamped[1]
        value = build()
        with self._mutex:
            self._entries[key] = (now, value)
        return value


# --- the views ------------------------------------------------------------------------------------


def phase_from_events(events):
    """The phase the journal last moved to, or None when no `phase` event was ever written."""
    phase = None
    for event in events:
        if event.get("event") == "phase":
            candidate = (event.get("payload") or {}).get("to")
            if candidate in PHASES:
                phase = candidate
    return phase


def overview_view(project, project_id=None):
    """The overview of Implementation Decisions 8: phase, autonomy, radius, the goal, the window,
    the slots in use, the running workers and jobs, and the last events.

    `status_view` is the same function `wayline status` prints, called with `refresh=False` so a
    poll never writes `graph.json`: the dashboard is a reader. The journal is read a second time
    here for the phase, which `status` does not show; the file is append-only and small, and the
    alternative is a phase the overview cannot name.
    """
    project = Path(project).resolve()
    view = status_view(project, refresh=False)
    events, offset = Ledger(project).read_events()
    view["id"] = project_id or project_ids([{"path": str(project)}])[str(project)]
    view["phase"] = phase_from_events(events)
    view["offset"] = offset
    return view


def journal_tail(project, since=0, tail=None):
    """The journal events appended after byte `since`, and the offset to ask for next.

    The journal is the version of itself: `size` is what the tail compares against and `next` is
    the cursor to send back. A `since` past the end of the file (a journal replaced by a shorter
    one, which only a hand ever does) is reported as `truncated` and read from zero, so the tail
    recovers instead of sitting on an offset that will never arrive.

    `tail=<lines>` is how a page that has just opened finds its first offset: it answers with the
    last few whole lines instead of the whole journal, which on a mature project is the largest
    file in the ledger and would be transferred in full only to be trimmed to the last screenful.
    Every poll after that one is a byte offset.
    """
    ledger = Ledger(Path(project))
    size = _journal_size(ledger)
    since = max(int(since), 0)
    truncated = since > size
    start = 0 if truncated else since
    if tail:
        start = _tail_offset(ledger, size, int(tail))
    events, offset = ledger.read_events(start)
    return {"since": start, "next": offset, "size": size, "truncated": truncated, "events": events}


def _tail_offset(ledger, size, lines):
    """The offset where the last `lines` whole lines of the journal begin.

    Read backwards in 64 KiB blocks and stop as soon as enough line breaks have been seen, rather
    than reading a file that may be megabytes to show a screenful. A journal with fewer whole lines
    than asked for is read from the start.
    """
    if lines <= 0 or size == 0:
        return size
    base, tail, breaks = size, b"", []
    try:
        with open(ledger.journal_path, "rb") as handle:
            while base > 0 and len(breaks) <= lines:
                step = min(_TAIL_BLOCK_BYTES, base)
                base -= step
                handle.seek(base)
                tail = handle.read(step) + tail
                breaks = [index for index, byte in enumerate(tail) if byte == 0x0A]
    except OSError:
        return 0
    if len(breaks) <= lines:
        return 0
    # The line after the (lines + 1)-th break from the end is the first one to keep.
    return base + breaks[-(lines + 1)] + 1


def _journal_size(ledger):
    try:
        return ledger.journal_path.stat().st_size
    except OSError:
        return 0


# --- the graph, the ticket pages, and the log tail (Implementation Decisions 8) ------------------


def graph_svg(project):
    """The ticket DAG as inline SVG: `dag.svg` over `refresh_graph(write=False)`, frontier-highlighted.

    Read-only like `overview_view`: a poll must not take the ledger's lock to regenerate
    `graph.json`. A project with no tickets yet draws an empty canvas rather than raising, since
    `dag.layout` has no row to measure a width from when there are no nodes.
    """
    project = Path(project)
    graph, _ = refresh_graph(project, write=False)
    entries = graph["tickets"]
    if not entries:
        return '<svg viewBox="0 0 0 0" xmlns="http://www.w3.org/2000/svg"></svg>\n'
    nodes = [entry["id"] for entry in entries]
    edges = [(blocker, entry["id"]) for entry in entries for blocker in entry["blocked_by"]]
    frontier_ids = {entry["id"] for entry in frontier(graph)}
    status = {entry["id"]: "frontier" if entry["id"] in frontier_ids else entry["status"] for entry in entries}
    return dag.svg(nodes, edges, status)


def tickets_view(project):
    """Every ticket's frontmatter, by id: the list a graph node's click opens one of."""
    return read_tickets(Path(project))


_ATTEMPT_NAME = re.compile(r"^\d+$")
_RESUME_NAME = re.compile(r"^resume-(\d+)$")


def ticket_view(project, ticket_id):
    """One ticket's page: frontmatter, body, the context pack, the latest result, findings, and its logs.

    The frontmatter and body come from the ticket file itself. The latest result is the most recent
    attempt's `research/sessions/<id>/<attempt>/result.json`, the one structured record a worker
    returned, distinct from the body's own prose `## Result` section. Findings are filtered from
    `findings.jsonl` by ticket id: there is no per-ticket findings file to read instead. Session and
    job logs are named here, not read: the log tail endpoint reads them, so a page that only wants
    the list is not made to wait on a file that may be growing.
    """
    project = Path(project)
    path = _ticket_path(project, ticket_id)
    if path is None:
        raise DashboardError("no such ticket: %d (GET /api/projects/<id>/tickets lists them)" % ticket_id)
    fields, body = read_ticket(path)
    return {
        "fields": fields,
        "body": body,
        "context_pack": list(fields.get("context_pack") or []),
        "result": _latest_result(project, ticket_id),
        "findings": _findings_for(project, ticket_id),
        "sessions": _session_logs(project, ticket_id, _launch_labels(project, ticket_id)),
        "jobs": _job_logs(project, ticket_id),
        "needs_human": _needs_human(project, ticket_id, fields),
    }


def _needs_human(project, ticket_id, fields):
    """Why this ticket waits for a person, or None while it does not (decision 16; ticket 61).

    `question` is what the last `ticket_needs_human` asked, and `note` what its `reason` reads as:
    "at the ladder's top rung" for a ticket the escalation chain left with nowhere to climb. A journal
    that cannot be read says nothing here, since the page is worth more without the note than not at all.
    """
    if fields.get("status") != "needs_human":
        return None
    try:
        events, _ = Ledger(project).read_events()
    except (OSError, ValueError):
        return None
    payload = {}
    for event in events:
        body = event.get("payload") or {}
        if event.get("event") == TICKET_NEEDS_HUMAN and body.get("ticket") == ticket_id:
            payload = body  # the latest hand-off wins
    if not payload:
        return None
    return {"question": payload.get("question"), "reason": payload.get("reason"),
            "note": NEEDS_HUMAN_NOTES.get(payload.get("reason"))}


def _ticket_path(project, ticket_id):
    matches = sorted(tickets_dir(project).glob("%02d-*.md" % ticket_id))
    return matches[0] if matches else None


def _session_dir(project, ticket_id):
    return Path(project) / RESEARCH / "sessions" / str(ticket_id)


def _attempt_dirs(project, ticket_id):
    """Every attempt directory of a ticket's sessions, oldest first."""
    base = _session_dir(project, ticket_id)
    if not base.is_dir():
        return []
    attempts = [entry for entry in base.iterdir() if entry.is_dir() and _ATTEMPT_NAME.match(entry.name)]
    return sorted(attempts, key=lambda entry: int(entry.name))


def _latest_result(project, ticket_id):
    for attempt_dir in reversed(_attempt_dirs(project, ticket_id)):
        candidate = attempt_dir / "result.json"
        if not candidate.is_file():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def _findings_for(project, ticket_id):
    path = Path(project) / RESEARCH / FINDINGS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    findings = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("ticket") == ticket_id:
            findings.append(entry)
    return findings


def _launch_labels(project, ticket_id):
    """Each attempt's launch label, `r5 opus high`, by attempt number, from the journal's `ticket_launched` (decision 16).

    A journal written before the rung ladder carries no `rung`, so its labels read `opus high`; a journal that
    cannot be read labels nothing, since the page is worth more without labels than not at all. An attempt whose
    `ticket_result` named the model that ran reads `r5 claude-opus-4-8 high, ran claude-opus-5` (decision 16, ticket 63).
    """
    try:
        events, _ = Ledger(project).read_events()
    except (OSError, ValueError):
        return {}
    launched, ran = {}, {}
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("ticket") != ticket_id or not isinstance(payload.get("attempt"), int):
            continue
        if event.get("event") == TICKET_LAUNCHED:
            launched[payload["attempt"]] = payload  # the latest launch wins
            ran.pop(payload["attempt"], None)  # what a launch ran on is its own result's word
        elif event.get("event") == TICKET_RESULT and payload.get("model_ran"):
            ran[payload["attempt"]] = payload["model_ran"]
    return {attempt: rung_label(payload.get("rung"), payload.get("model"), payload.get("effort"), ran.get(attempt))
            for attempt, payload in launched.items()}


def _session_logs(project, ticket_id, labels=None):
    """The session log ids of one ticket, oldest attempt first, each with a `resume-<k>` after it, and each attempt's launch label."""
    logs = []
    labels = labels or {}
    for attempt_dir in _attempt_dirs(project, ticket_id):
        if (attempt_dir / "stream.jsonl").is_file():
            logs.append({"id": "%d/%s" % (ticket_id, attempt_dir.name), "attempt": int(attempt_dir.name),
                         "label": labels.get(int(attempt_dir.name))})
        resumes = sorted(
            (entry for entry in attempt_dir.iterdir() if entry.is_dir() and _RESUME_NAME.match(entry.name)),
            key=lambda entry: int(_RESUME_NAME.match(entry.name).group(1)),
        )
        for resume_dir in resumes:
            if (resume_dir / "stream.jsonl").is_file():
                logs.append({
                    "id": "%d/%s/%s" % (ticket_id, attempt_dir.name, resume_dir.name),
                    "attempt": int(attempt_dir.name), "resume": resume_dir.name, "label": labels.get(int(attempt_dir.name)),
                })
    return logs


def _job_logs(project, ticket_id):
    jobs, _ = read_jobs(project)
    return [{"id": job["id"], "status": job["status"], "log": job["log"]}
            for job in jobs if job.get("ticket") == ticket_id]


def _ticket_session_snapshot(project, ticket_id):
    """One `(mtime_ns, size)` per file under one ticket's own `research/sessions/<id>/`.

    Not part of `ledger_snapshot`: a resume writes into `resume-<k>/` without touching the ticket
    file (its status does not change), and the attempt that opened it may not have touched the
    ticket file either, so `tickets/<id>`'s ETag needs a snapshot `overview` and `tickets` do not:
    the session list and the latest result it names live here, not in the ticket's frontmatter.
    Scoped to one ticket rather than folded into `ledger_snapshot`, since a poll of one ticket's
    page has no reason to scan every other ticket's session tree.
    """
    values = {}
    for attempt_dir in _attempt_dirs(project, ticket_id):
        _stat_into(values, attempt_dir / "stream.jsonl", attempt_dir.name + "/stream.jsonl")
        _stat_into(values, attempt_dir / "result.json", attempt_dir.name + "/result.json")
        resumes = sorted(entry for entry in attempt_dir.iterdir() if entry.is_dir() and _RESUME_NAME.match(entry.name))
        for resume_dir in resumes:
            key = "%s/%s/stream.jsonl" % (attempt_dir.name, resume_dir.name)
            _stat_into(values, resume_dir / "stream.jsonl", key)
    return values


# The route's `log_id` for `kind=session`: `<ticket>/<attempt>` or `<ticket>/<attempt>/resume-<k>`,
# restricted to digits and the literal `resume-` so a request can never spell a path outside
# `research/sessions/`. For `kind=job` it is a job's own id (schemas/job.json's own pattern).
_SESSION_LOG_ID = re.compile(r"^\d+/\d+(?:/resume-\d+)?$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def log_path(project, kind, log_id):
    """The file `logs/<kind>/<id>` names, or None when the id does not resolve to one.

    `tick` ignores the id: one machine has one tick log, `~/.wayline/tick.log` (spec Per-machine
    pointers), outside every project's ledger, so it is read the same whichever project is open.
    A `job`'s `log` field is ledger-authored (code writes `research/jobs/*.json`, never a request),
    but it is still resolved beneath the project root the way `static_file` refuses an escape,
    since a hand-edited job file is not a reason to read outside the project.
    """
    project = Path(project).resolve()
    if kind == "session":
        if not _SESSION_LOG_ID.match(log_id):
            raise DashboardError("a session log id is ticket/attempt or ticket/attempt/resume-k, got %r" % log_id)
        return project / RESEARCH / "sessions" / log_id / "stream.jsonl"
    if kind == "job":
        if not _JOB_ID.match(log_id):
            raise DashboardError("bad job id: %r" % log_id)
        job_path = project / RESEARCH / "jobs" / (log_id + ".json")
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        raw = job.get("log")
        if not isinstance(raw, str):
            return None
        try:
            resolved = (project / raw).resolve()
        except OSError:
            return None
        return resolved if resolved.is_relative_to(project) else None
    if kind == "tick":
        return home() / "tick.log"
    raise DashboardError("no such log kind: %r (session, job, or tick)" % kind)


def log_tail(path, since=0):
    """The bytes of `path` appended after byte `since`, and the offset to ask for next.

    Plain bytes, not journal lines: a worker stream is `stream.jsonl` but a job or the tick log is
    plain text, so the tail hands back whatever is there and leaves how to show it to the page. A
    log that does not exist yet (a ticket never attempted, a tick that has not run) answers
    `exists: false` rather than raising: a page opened before the first attempt is not an error.
    """
    since = max(int(since), 0)
    stamp = _log_version(path)
    if stamp is None:
        return {"since": since, "next": since, "size": 0, "truncated": False, "text": "", "exists": False}
    size = stamp[1]
    truncated = since > size
    start = 0 if truncated else since
    with open(path, "rb") as handle:
        handle.seek(start)
        chunk = handle.read()
    return {
        "since": start, "next": start + len(chunk), "size": size, "truncated": truncated,
        "text": chunk.decode("utf-8", "replace"), "exists": True,
    }


def _log_version(path):
    if path is None:
        return None
    try:
        stamp = path.stat()
    except OSError:
        return None
    return (stamp.st_mtime_ns, stamp.st_size)


# --- the outputs index and downloads (ticket 42) -------------------------------------------------

# arXiv's terms of use forbid re-serving an e-print (dossier.py's docstring), so nothing under a
# reference's own `source/` is ever indexed or downloaded, whatever a request or a zip walk asks
# for; `init` gitignores it for the same reason.
_REFS_SOURCE = (RESEARCH, "refs")


def _is_source_tree(project, resolved):
    """Whether `resolved` is `research/refs/<slug>/source` or lives beneath it."""
    try:
        relative = resolved.relative_to(project)
    except ValueError:
        return True
    parts = relative.parts
    return len(parts) >= 4 and parts[:2] == _REFS_SOURCE and parts[3] == "source"


def _file_entry(project, path):
    """`{path, size, sha256}` for one existing file, `path` relative-to-project as posix, or None."""
    if path.is_symlink():
        return None
    try:
        stamp = path.stat()
    except OSError:
        return None
    if not path.is_file() or _is_source_tree(project, path):
        return None
    return {"path": path.relative_to(project).as_posix(), "size": stamp.st_size, "sha256": sha256_of(path)}


def _tree_entries(project, root):
    """Every file under `root` (itself relative to `project`), sorted, `source/` trees excluded."""
    base = project / root
    if not base.is_dir():
        return []
    entries = []
    for path in sorted(base.rglob("*")):
        if path.is_dir() or path.is_symlink():
            continue
        entry = _file_entry(project, path)
        if entry is not None:
            entries.append(entry)
    return entries


def _manifest_entries(project):
    """The `results/` index of the ticket: `manifest.json`'s own entries, as recorded.

    Sizes and hashes come from the manifest itself rather than a fresh stat: `register_artifact`
    hashed the file once when it was produced, `results/` is gitignored and may be pruned by the
    owner between runs, and a finding's provenance already points at what the manifest recorded,
    not at whatever happens to be on disk right now.
    """
    manifest = read_manifest(project)
    return [
        {"path": entry["path"], "size": entry["size"], "sha256": entry["sha256"],
         "ticket": entry.get("ticket"), "run_id": entry.get("run_id"), "job": entry.get("job")}
        for entry in manifest.get("entries", []) if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]


def _findings_entries(project):
    return [entry for entry in (
        _file_entry(project, project / RESEARCH / FINDINGS),
        _file_entry(project, project / RESEARCH / FINDINGS_MD),
    ) if entry is not None]


# A dossier's own files, never the `source/`, `inventory.json`, `entries.jsonl`, `code/`, or
# `qa_log.md` beside it: those are absorb's working files, not what the ticket calls "dossiers".
_DOSSIER_FILES = ("dossier.json", "dossier.md", "code_dossier.json")


def _dossier_entries(project):
    entries = []
    refs = project / RESEARCH / "refs"
    if not refs.is_dir():
        return entries
    for slug_dir in sorted(refs.iterdir()):
        if not slug_dir.is_dir():
            continue
        for name in _DOSSIER_FILES:
            entry = _file_entry(project, slug_dir / name)
            if entry is not None:
                entries.append(entry)
    return entries


def _figures_entries(project):
    """Every file under a reference's own `figures/`: the crops its inventory pass extracted."""
    entries = []
    refs = project / RESEARCH / "refs"
    if not refs.is_dir():
        return entries
    for slug_dir in sorted(refs.iterdir()):
        entries.extend(_tree_entries(project, (slug_dir / "figures").relative_to(project)))
    return entries


def outputs_view(project):
    """The outputs index of Implementation Decisions 8: what the owner browses and downloads.

    Every category is a flat list of `{path, size, sha256}` (results carries the manifest's own
    `ticket`, `run_id`, and `job` too), `path` relative to the project root and exactly what
    `GET /api/projects/<id>/download/<path>` takes. `results/` is read through `manifest.json`
    rather than walked, since that is the one tree a finding's provenance already trusts; every
    other category is real files on disk, walked and hashed fresh.
    """
    project = Path(project).resolve()
    return {
        "results": _manifest_entries(project),
        "findings": _findings_entries(project),
        "figures": _figures_entries(project),
        "dossiers": _dossier_entries(project),
        "report": [entry for entry in (_file_entry(project, project / RESEARCH / "REPORT.md"),) if entry is not None],
        "paper": _tree_entries(project, Path(RESEARCH) / "paper"),
        "docs": _tree_entries(project, Path("docs")),
        "site": _site_entries(project),
    }


def _site_entries(project):
    """The built documentation site on `main` (ticket 51): its front page, where `site/` serves it, and its last checks.

    One entry or none. `url` is relative to `/api/projects/<id>/`, where the pages are served inline in
    a sandbox rather than downloaded, so the owner reads the site as a site.
    """
    from wayline import docs  # the docs module reads the code dossier's inventory; keep the server's import light

    entry = _file_entry(project, project / docs.SITE_INDEX)
    if entry is None:
        return []
    record = docs.read_record(project) or {}
    return [dict(entry, url="site/index.html", built=record.get("ran_at"), passed=record.get("pass"))]


def site_target(project, relpath):
    """The file of the built site `site/<path>` names, or None: `index.html` for a directory, nothing outside the site."""
    from wayline import docs

    root = (Path(project) / docs.HTML_DIR).resolve()
    relative = unquote(relpath or "")
    if relative.startswith("/") or ".." in Path(relative).parts:
        return None
    try:
        resolved = (root / relative).resolve()
    except OSError:  # pragma: no cover - a symlink loop under the site
        return None
    if not resolved.is_relative_to(root):
        return None
    if resolved.is_dir():
        resolved = resolved / "index.html"
    return resolved if resolved.is_file() else None


def _outputs_snapshot(project):
    """One `(mtime_ns, size)` per file the outputs index reads: the version behind its ETag.

    Cheap like `ledger_snapshot`, so a poll that finds nothing new never re-hashes a tree; the
    index itself (`outputs_view`) is only built again once this snapshot has actually moved.
    `results/` needs no entry of its own here: `manifest.json` is what `_manifest_entries` reads,
    and its own stat already moves the tag when a new artifact is registered.
    """
    project = Path(project)
    values = {}
    _stat_into(values, project / RESEARCH / MANIFEST_JSON, RESEARCH + "/" + MANIFEST_JSON)
    _stat_into(values, project / RESEARCH / FINDINGS, RESEARCH + "/" + FINDINGS)
    _stat_into(values, project / RESEARCH / FINDINGS_MD, RESEARCH + "/" + FINDINGS_MD)
    _stat_into(values, project / RESEARCH / "REPORT.md", RESEARCH + "/REPORT.md")
    from wayline.docs import CHECKS_JSON  # the docs module reads the code dossier's inventory; keep the server's import light
    _stat_into(values, project / CHECKS_JSON, CHECKS_JSON.as_posix())
    for root in (project / RESEARCH / "refs", project / RESEARCH / "paper", project / "docs"):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink() and not _is_source_tree(project, path):
                _stat_into(values, path, path.relative_to(project).as_posix())
    return values


class _Unsatisfiable(Exception):
    """A `Range` header that names bytes past the end of the file: answer 416, not a body."""


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def byte_range(header, size):
    """The single byte range a `Range` header names, or None to send the whole body.

    RFC 9110 section 14.2's `bytes=<first>-<last>`, `bytes=<first>-`, and `bytes=-<suffix>`; a
    missing header, more than one range, or a unit this server does not parse all mean "send
    everything" rather than a refusal, since only ticket 42 asks for single-range support.
    """
    if not header or "," in header:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:
        length = int(last)
        start, end = max(size - length, 0), size - 1
    else:
        start = int(first)
        end = int(last) if last else size - 1
    if size == 0 or start >= size or start > end:
        raise _Unsatisfiable(size)
    return start, min(end, size - 1)


class _ChunkedWriter:
    """The zip-streaming recipe of research-notes 08 Section 3: `write`, `tell`, and `close` over
    `wfile`, framing every write as one HTTP/1.1 chunk (RFC 9112 section 7.1). `zipfile` cannot
    seek this, so it flags every member with the data descriptor bit and writes CRC and sizes
    after the member's bytes; nothing here buffers more than one write call's worth of data.
    """

    def __init__(self, wfile):
        self._wfile = wfile
        self._pos = 0

    def write(self, data):
        if data:
            self._wfile.write(b"%x\r\n" % len(data))
            self._wfile.write(bytes(data))
            self._wfile.write(b"\r\n")
            self._pos += len(data)
        return len(data)

    def tell(self):
        return self._pos

    def flush(self):
        pass

    def close(self):
        self._wfile.write(b"0\r\n\r\n")


def download_target(project, relpath):
    """The file or directory `download/<path>` names beneath `project`, or None.

    Resolved and checked against the project root the way `static_file` checks against
    `dashboard/`, so `..` and a symlink out both end as None; a path under any reference's own
    `source/` is refused the same way, since that tree must never be re-served.
    """
    project = Path(project).resolve()
    relative = unquote(relpath)
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None
    candidate = project / relative
    try:
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - a symlink loop under the project
        return None
    if not resolved.is_relative_to(project) or not resolved.exists():
        return None
    if _is_source_tree(project, resolved):
        return None
    return resolved


# --- the static page --------------------------------------------------------------------------------


def static_file(relpath, root=None):
    """The file under the harness `dashboard/` directory a request names, or None.

    Nothing outside that directory is servable, whatever the request spells: the path is resolved
    and checked against the root, so `..` and a symlink out both end as None rather than as a read
    of the owner's home.
    """
    root = Path(root or STATIC_ROOT)
    relative = unquote(relpath).lstrip("/")
    if not relative or relative.endswith("/"):
        relative = "index.html"
    candidate = root / relative
    try:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
            return None
    except OSError:  # pragma: no cover - a symlink loop under dashboard/
        return None
    return resolved


def content_type(path):
    return CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


# --- what `serve` prints ----------------------------------------------------------------------------


def tunnel_line(port, workstation=None):
    """The one line the owner pastes on the laptop.

    `ServerAliveInterval` and `ExitOnForwardFailure` are in it because research-notes 08 measured
    what happens without them: a tunnel whose transport died keeps accepting connections on the
    forwarded port, so every request fails until the tunnel is rebuilt by hand.
    """
    workstation = workstation or socket.gethostname() or "<workstation>"
    return "ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L %d:%s:%d %s" % (port, LOOPBACK, port, workstation)


def is_terminal(stream):
    """Whether output to `stream` is read at a terminal rather than kept: a unit's output goes to the user journal."""
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def dashboard_url(settings, host=None, with_token=True):
    """The URL to open, carrying the token.

    Bound to loopback the views need no token, but every action needs it whatever the bind (ticket
    35), and the page sends the one its own address carries, so a URL without it would open a
    dashboard that cannot act. `with_token` False leaves it out, for output that is kept rather than
    read at a terminal. A wider bind prints the machine's own name rather than the bind address,
    because `0.0.0.0` is an address to listen on and not one a laptop can dial.
    """
    if host is None:
        wide = requires_token(settings["bind"])
        host = (socket.gethostname() or settings["bind"]) if wide else LOOPBACK
    url = "http://%s:%d/" % (host, settings["port"])
    return "%s?%s=%s" % (url, TOKEN_QUERY, settings["token"]) if settings.get("token") and with_token else url


def requires_token(bind):
    """Whether a bind exposes the views to the network, and so needs the token on every request."""
    return bind not in (LOOPBACK, "localhost", "::1")


def serve_lines(settings, view, workstation=None, with_token=True):
    """What `wayline serve` prints at start: the URL, the tunnel line, and the tabs it will serve.

    `with_token` False prints the URL without the token and says where the token is, which is what
    `serve` does when its output is not a terminal: `wayline-dashboard.service` writes to the user journal.
    """
    lines = ["wayline %s dashboard  %s" % (TAG, dashboard_url(settings, with_token=with_token))]
    lines.append("  " + tunnel_line(settings["port"], workstation))
    if not with_token:
        lines.append("  the URL that carries the token is printed only at a terminal; the token is in %s" % dashboard_path())
    if requires_token(settings["bind"]):
        lines.append("  bound to %s: every request needs the token above (it lives in %s)" % (settings["bind"], dashboard_path()))
    projects = view.get("projects", [])
    if not projects:
        lines.append("  no projects registered yet; run wayline init <path>")
    else:
        for project in projects:
            marks = [mark for mark in ("active" if project["active"] else "", "" if project["readable"] else "path is gone") if mark]
            lines.append("  %-16s %s%s" % (project["id"], project["path"], ("  (%s)" % ", ".join(marks)) if marks else ""))
    lines.append("  every action needs the token the URL carries; ctrl-c stops the server")
    # The column padding is how the eye finds a field; it must not survive to the end of a line.
    return [line.rstrip() for line in lines]


# --- the server ---------------------------------------------------------------------------------------


class DashboardServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer` with what the handler needs and a flag every stream watches.

    `daemon_threads` is True so an open server-sent-events stream cannot hold `shutdown` (the
    mixin waits for non-daemon threads); `stopping` lets a stream end its loop at once instead of
    waiting for its next write to fail.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, token=None, require_token=False, static_root=None, sse_tick_s=SSE_TICK_S, memo_ttl=SNAPSHOT_MEMO_S, readings_ttl_s=READINGS_TTL_S):
        if require_token:
            self.request_queue_size = WIDE_QUEUE_SIZE
        self.token = token
        self.require_token = bool(require_token)
        self.static_root = Path(static_root or STATIC_ROOT)
        self.sse_tick_s = sse_tick_s
        self.readings_ttl_s = readings_ttl_s
        self.memo = Memo(ttl=memo_ttl)
        self.stopping = threading.Event()
        # Held while a switch waits for a draining conductor, so a second switch is refused rather than queued behind it.
        self.switching = threading.Lock()
        super().__init__(address, handler)

    def shutdown(self):
        self.stopping.set()
        super().shutdown()


class DashboardHandler(BaseHTTPRequestHandler):
    """The small path table of Implementation Decisions 8: the views over `GET`, the actions over `POST`."""

    protocol_version = "HTTP/1.1"
    server_version = "wayline/" + TAG
    sys_version = ""
    # A kept-alive connection with no timeout blocks its thread in `rfile.readline()` for as long
    # as the peer likes, and the token is only checked once a request line has arrived, so without
    # this a stranger on a wide bind could hold threads without presenting anything. 30 s is far
    # longer than the 5 s view poll, so the page's own connections are never cut mid-use.
    timeout = IDLE_TIMEOUT_S

    # The routes, in the order they are tried; the first match wins.
    ROUTES = (
        (re.compile(r"^/api/projects/?$"), "api_projects"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/overview/?$"), "api_overview"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/journal/?$"), "api_journal"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/graph\.svg$"), "api_graph"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/tickets/?$"), "api_tickets"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/tickets/(?P<ticket>\d+)/?$"), "api_ticket"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/logs/(?P<kind>[a-z]+)/(?P<log_id>.+)$"), "api_logs"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/outputs/?$"), "api_outputs"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/download/(?P<relpath>.+)$"), "api_download"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/site/(?P<relpath>.*)$"), "api_site"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/decisions/?$"), "api_decisions"),
        (re.compile(r"^/api/projects/(?P<project>[^/]+)/changes/?$"), "api_changes"),
        (ACTION_ROUTE, "api_action_get"),
    )

    def log_message(self, *args):
        """Silence the access log: a tail polling every 2 s would bury anything worth reading."""

    # --- the request ---

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        self.carry_token = False
        if not self._authorized(query):
            return self._text(HTTPStatus.FORBIDDEN, "this dashboard is bound to %s; every request needs the token from %s\n" % (self.server.server_address[0], dashboard_path()))
        for pattern, name in self.ROUTES:
            match = pattern.match(parsed.path)
            if match:
                return self._route(name, match, query)
        if parsed.path.startswith("/api/"):
            return self._text(HTTPStatus.NOT_FOUND, "no such endpoint: %s\n" % parsed.path)
        return self._static(parsed.path)

    def _route(self, name, match, query):
        try:
            return getattr(self, name)(query, **match.groupdict())
        except DashboardError as failure:
            return self._text(HTTPStatus.BAD_REQUEST, "%s\n" % failure)
        except (OSError, ValueError) as failure:
            # A ledger a hand broke must not take the server down: the other tabs still answer.
            return self._text(HTTPStatus.INTERNAL_SERVER_ERROR, "%s\n" % failure)

    def do_POST(self):
        """An action (ticket 35): the token in its header, a body within its cap, then the verb's own function."""
        parsed = urlparse(self.path)
        self.carry_token = False
        match = ACTION_ROUTE.match(parsed.path)
        if match is None:
            self.close_connection = True  # the body is not read, so the connection cannot carry another request
            return self._text(HTTPStatus.NOT_FOUND, "no such action: %s (POST /api/projects/<id>/actions/<name>)\n" % parsed.path)
        name = match.group("name")
        if not self._action_authorized():
            self.close_connection = True
            return self._action_reply(HTTPStatus.FORBIDDEN, {
                "ok": False, "action": name,
                "error": "an action needs the dashboard's token in the %s header; open the URL wayline serve printed, which "
                         "carries it (it is kept in %s)" % (TOKEN_HEADER, dashboard_path())})
        if name not in ACTIONS:
            self.close_connection = True
            return self._action_reply(HTTPStatus.NOT_FOUND, {
                "ok": False, "action": name, "error": "no action %r; the actions are %s" % (name, ", ".join(ACTIONS))})
        body = self._action_body(name)
        if body is None:
            return None
        try:
            project = self._project(match.group("project"))
            status, report = run_action(name, project, body, self.headers, self.server)
        except ActionConflict as failure:
            return self._action_reply(HTTPStatus.CONFLICT, {"ok": False, "action": name, "error": str(failure)})
        except ValueError as failure:  # a request the action cannot take, or a verb's own refusal (ProjectError, TicketError)
            return self._action_reply(HTTPStatus.BAD_REQUEST, {"ok": False, "action": name, "error": str(failure)})
        except OSError as failure:
            return self._action_reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "action": name, "error": str(failure)})
        return self._action_reply(status, dict(report, ok=True, action=name))

    def _action_authorized(self):
        """Whether this request may act: the token in the `X-Wayline-Token` header, and nothing else stands in for it.

        Not the URL and not the cookie, which a browser attaches to requests a page it did not write
        makes to the forwarded port; not the loopback bind, which the tunnel reaches from the laptop.
        A server started with no token acts for no one.
        """
        token = (getattr(self.server, "token", None) or "").encode("utf-8")
        offered = (self.headers.get(TOKEN_HEADER) or "").encode("utf-8", "replace")
        return bool(token) and secrets.compare_digest(offered, token)

    def _action_body(self, name):
        """The request body, or None once a refusal was sent: a `Content-Length` within the action's cap, read whole."""
        def refuse(code, error):
            self.close_connection = True
            self._action_reply(code, {"ok": False, "action": name, "error": error})
            return None

        if self.headers.get("Transfer-Encoding"):
            return refuse(HTTPStatus.LENGTH_REQUIRED, "an action's body is sent with a Content-Length, not a transfer encoding")
        raw = (self.headers.get("Content-Length") or "0").strip()
        if not raw.isdigit():
            return refuse(HTTPStatus.BAD_REQUEST, "Content-Length is %r, which is not a byte count" % raw)
        length, cap = int(raw), _intake_cap() if name == "intake" else JSON_BODY_MAX
        if length > cap:
            return refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "the body is %d bytes, over the %d an %s action takes%s" % (
                length, cap, name, "; run wayline intake <path> on the workstation for a file this large" if name == "intake" else ""))
        data = self.rfile.read(length) if length else b""
        if len(data) != length:
            return refuse(HTTPStatus.BAD_REQUEST, "the body ended after %d of its %d bytes" % (len(data), length))
        return data

    def _authorized(self, query):
        """Whether this request may be answered: the token in the header, the URL, or the cookie.

        The URL is how the owner arrives (it is the link `serve` prints) and the cookie is how the
        page's own stylesheet, scripts and polls carry the token afterwards, since a browser
        attaches neither a header nor a query of its own to a subresource. A request that presented
        the token in the URL is answered with `Set-Cookie`, which is what `carry_token` records.
        """
        if not getattr(self.server, "require_token", False):
            return True
        token = (self.server.token or "").encode("utf-8")
        if not token:
            return False
        from_url = (query.get(TOKEN_QUERY) or [""])[0]
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        offered = self.headers.get(TOKEN_HEADER) or from_url or (cookie[TOKEN_COOKIE].value if TOKEN_COOKIE in cookie else "")
        # Bytes, not text: `compare_digest` refuses a str carrying anything outside ASCII, and the
        # value comes from a URL a stranger wrote.
        if not secrets.compare_digest(offered.encode("utf-8", "replace"), token):
            return False
        self.carry_token = bool(from_url) and offered == from_url
        return True

    # --- the endpoints ---

    def api_projects(self, query):
        entries = read_projects()
        active = read_active()
        settings = {
            "poll_journal_s": _poll(active, "poll_journal_s", 2),
            "poll_views_s": _poll(active, "poll_views_s", 5),
        }
        tag = etag("projects", self.server.memo.get("projects", _pointer_snapshot))
        if self._not_modified(tag):
            return None
        return self._json(projects_view(active=active, entries=entries, settings=settings), tag)

    def api_overview(self, query, project):
        """The overview, tagged by the ledger, the active pointer, and the age of its readings.

        The ledger snapshot alone is not this view's version. The overview also carries which
        project is active, which lives in `~/.wayline/active` and not in the ledger, and the
        machine's live readings (loadavg, memory, GPU utilization, the free slots), which move
        without any file the snapshot sees moving. Tagged by the snapshot alone, a project with a
        quiet ledger and a long job running would poll every 5 s, be told 304 every time, and show
        slots frozen at whatever they were when the ledger last changed.

        So the pointer is stat'ed into the tag, and the readings get an age: the tag also carries
        which `readings_ttl_s` window the request falls in, which bounds how stale a reading can be
        at one interval while still letting two polls inside one window share a 304 without the
        view being built at all.
        """
        path = self._project(project)
        tag = etag(
            "overview", project,
            self.server.memo.get(("ledger", str(path)), lambda: ledger_snapshot(path)),
            _active_version(), _readings_window(getattr(self.server, "readings_ttl_s", READINGS_TTL_S)),
        )
        if self._not_modified(tag):
            return None
        return self._json(overview_view(path, project_id=project), tag)

    def api_journal(self, query, project):
        path = self._project(project)
        since = _offset(query.get("since", ["0"])[0])
        tail = _tail_lines(query.get("tail", [""])[0])
        if (query.get("transport") or [""])[0] == "sse":
            return self._journal_stream(path, since)
        ledger = Ledger(path)
        # The cursor is part of the tag as well as the journal's version: a client that sent back
        # the tag of one offset while asking for another must not be told "nothing new".
        tag = etag("journal", project, since, tail, _journal_version(ledger))
        if self._not_modified(tag):
            return None
        return self._json(journal_tail(path, since, tail=tail), tag)

    def _journal_stream(self, project, since):
        """The server-sent-events alternative of OPEN-20, kept for the comparison through the tunnel.

        Unchunked with `Connection: close`, because chunking a stream is what the WHATWG spec warns
        against and RFC 9112 section 6.3 makes a body that ends with the connection a valid one.
        `id:` is the journal offset after the line it carries, so a reconnect resumes with
        `Last-Event-ID` and the server keeps no per-client state. The `select()` on a socket the
        client never writes to reports readability only at EOF, which is how the thread learns the
        tab is gone within one tick instead of on its next failed write.
        """
        ledger = Ledger(project)
        last = self.headers.get("Last-Event-ID")
        position = _offset(last) if last and last.strip().isdigit() else since
        size = _journal_size(ledger)
        if position > size:
            position = 0
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        tick = getattr(self.server, "sse_tick_s", SSE_TICK_S)
        pinged = time.monotonic()
        try:
            self.wfile.write(b"retry: %d\n\n" % SSE_RETRY_MS)
            while not self.server.stopping.is_set():
                lines, position = _journal_lines(ledger, position)
                for offset, line in lines:
                    self.wfile.write(b"id: %d\ndata: %s\n\n" % (offset, line))
                if not lines and time.monotonic() - pinged > SSE_PING_S:
                    # The 15 s comment of the WHATWG authoring notes; it doubles as tunnel traffic.
                    self.wfile.write(b": ping\n\n")
                    pinged = time.monotonic()
                if select.select([self.connection], [], [], tick)[0]:
                    return None  # readable on a stream the client never writes to means EOF
        except (BrokenPipeError, ConnectionResetError, OSError):
            return None
        return None

    def api_graph(self, query, project):
        path = self._project(project)
        tag = etag("graph", project, self.server.memo.get(("ledger", str(path)), lambda: ledger_snapshot(path)))
        if self._not_modified(tag):
            return None
        return self._send(HTTPStatus.OK, graph_svg(path).encode("utf-8"), "image/svg+xml",
                           (("ETag", tag), ("Cache-Control", "no-cache")))

    def api_tickets(self, query, project):
        path = self._project(project)
        tag = etag("tickets", project, self.server.memo.get(("ledger", str(path)), lambda: ledger_snapshot(path)))
        if self._not_modified(tag):
            return None
        return self._json(tickets_view(path), tag)

    def api_ticket(self, query, project, ticket):
        path = self._project(project)
        ticket_id = int(ticket)
        tag = etag(
            "ticket", project, ticket,
            self.server.memo.get(("ledger", str(path)), lambda: ledger_snapshot(path)),
            self.server.memo.get(("sessions", str(path), ticket_id), lambda: _ticket_session_snapshot(path, ticket_id)),
        )
        if self._not_modified(tag):
            return None
        return self._json(ticket_view(path, ticket_id), tag)

    def api_logs(self, query, project, kind, log_id):
        path = self._project(project)
        since = _offset(query.get("since", ["0"])[0])
        target = log_path(path, kind, log_id)
        tag = etag("logs", project, kind, log_id, since, _log_version(target))
        if self._not_modified(tag):
            return None
        return self._json(log_tail(target, since), tag)

    def api_outputs(self, query, project):
        path = self._project(project)
        tag = etag("outputs", project, self.server.memo.get(("outputs", str(path)), lambda: _outputs_snapshot(path)))
        if self._not_modified(tag):
            return None
        return self._json(outputs_view(path), tag)

    def api_decisions(self, query, project):
        """The decisions view (ticket 35), tagged by the ledger, which holds `DECISIONS.md` and `harness.json`, and by the active pointer."""
        path = self._project(project)
        tag = etag("decisions", project, self.server.memo.get(("ledger", str(path)), lambda: ledger_snapshot(path)), _active_version())
        if self._not_modified(tag):
            return None
        return self._json(decisions.decisions_view(path), tag)

    def api_changes(self, query, project):
        """The evolve loop's view (ticket 45): the feedback filed and what was made of each item, and the change records."""
        from wayline import changes  # the evolve loop imports the registry and the fixtures, which no other view needs
        path = self._project(project)
        tag = etag("changes", project, self.server.memo.get(("ledger", str(path)), lambda: ledger_snapshot(path)))
        if self._not_modified(tag):
            return None
        return self._json(changes.changes_view(path), tag)

    def api_action_get(self, query, project, name):
        """An action asked for with `GET`: 405, with the method it takes."""
        return self._send(HTTPStatus.METHOD_NOT_ALLOWED, b"an action is a POST with the token in the X-Wayline-Token header\n",
                          TEXT_TYPE, (("Allow", "POST"),))

    def api_download(self, query, project, relpath):
        """A single file, ranged, or a directory streamed as a zip (Implementation Decisions 8)."""
        path = self._project(project)
        target = download_target(path, relpath)
        if target is None:
            return self._text(HTTPStatus.NOT_FOUND, "no such output: %s\n" % relpath)
        if target.is_dir():
            return self._download_zip(path, target)
        return self._download_file(target)

    def api_site(self, query, project, relpath):
        """One page or asset of the built documentation site, inline and sandboxed (ticket 51)."""
        target = site_target(self._project(project), relpath)
        if target is None:
            return self._text(HTTPStatus.NOT_FOUND, "no such page of the documentation site: %s\n" % (relpath or "index.html"))
        return self._send(HTTPStatus.OK, target.read_bytes(), content_type(target),
                          (("Content-Security-Policy", SITE_CSP), ("Cache-Control", "no-cache")))

    def _download_file(self, target):
        try:
            size = target.stat().st_size
        except OSError:
            return self._text(HTTPStatus.NOT_FOUND, "no such output\n")
        try:
            requested = byte_range(self.headers.get("Range"), size)
        except _Unsatisfiable:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", "bytes */%d" % size)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        start, end = requested if requested else (0, max(size - 1, 0))
        length = 0 if size == 0 else end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK)
        self.send_header("Content-Type", content_type(target))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if requested:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % target.name)
        self.end_headers()
        if self.command == "HEAD" or length == 0:
            return None
        with open(target, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(remaining, 1 << 16))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)
        return None

    def _download_zip(self, project, directory):
        """A directory, streamed as a zip through the chunked-encoding wrapper of ticket 42.

        Never buffered whole: `zipfile` writes each member's compressed bytes as they are
        produced, and `_ChunkedWriter` turns every one of those writes into one HTTP chunk.
        """
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="%s.zip"' % directory.name)
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command == "HEAD":
            return None
        writer = _ChunkedWriter(self.wfile)
        try:
            with zipfile.ZipFile(writer, "w", zipfile.ZIP_DEFLATED) as archive:
                for member in sorted(directory.rglob("*")):
                    if member.is_dir() or member.is_symlink() or _is_source_tree(project, member):
                        continue
                    archive.write(member, member.relative_to(directory).as_posix())
            writer.close()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True
        return None

    def _static(self, path):
        target = static_file(path, root=self.server.static_root)
        if target is None:
            return self._text(HTTPStatus.NOT_FOUND, "no such file: %s\n" % path)
        stamp = target.stat()
        tag = etag("static", str(target.name), stamp.st_mtime_ns, stamp.st_size)
        if self._not_modified(tag):
            return None
        return self._send(HTTPStatus.OK, target.read_bytes(), content_type(target), (("ETag", tag), ("Cache-Control", "no-cache")))

    # --- the responses ---

    def _project(self, project_id):
        path = find_dashboard_project(project_id)
        if path is None or not is_project(path):
            raise DashboardError("no registered project with the id %r (GET /api/projects lists them)" % project_id)
        return path.resolve()

    def _action_reply(self, code, value):
        return self._send(code, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"), JSON_TYPE, (("Cache-Control", "no-store"),))

    def _not_modified(self, tag):
        """Answer 304 when the client already holds this version (RFC 9110 section 13.1.2)."""
        offered = self.headers.get("If-None-Match")
        if offered is None or tag not in [item.strip() for item in offered.split(",")]:
            return False
        self._send(HTTPStatus.NOT_MODIFIED, b"", None, (("ETag", tag), ("Cache-Control", "no-cache")))
        return True

    def _json(self, value, tag=None):
        headers = (("ETag", tag), ("Cache-Control", "no-cache")) if tag else (("Cache-Control", "no-cache"),)
        return self._send(HTTPStatus.OK, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"), JSON_TYPE, headers)

    def _text(self, code, text):
        return self._send(code, text.encode("utf-8"), TEXT_TYPE)

    def _send(self, code, body=b"", ctype=TEXT_TYPE, headers=()):
        """One response with an accurate `Content-Length`, which HTTP/1.1 keep-alive requires."""
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        if getattr(self, "carry_token", False):
            self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (TOKEN_COOKIE, self.server.token))
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)
        return None


# --- the actions (ticket 35) --------------------------------------------------------------------------


def _intake_cap():
    from wayline.intake import DROP_MAX_BYTES  # the intake imports the gates, which no view needs
    return DROP_MAX_BYTES


def _fields(body, required=(), optional=()):
    """The JSON object an action's body carries; anything else, a missing key, or a key the action does not take is refused."""
    if not body.strip():
        value = {}
    else:
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as failure:
            raise DashboardError("an action's body is a JSON object: %s" % failure) from None
    if not isinstance(value, dict):
        raise DashboardError("an action's body is a JSON object, got %s" % type(value).__name__)
    unknown = sorted(set(value) - set(required) - set(optional))
    if unknown:
        raise DashboardError("this action does not take %s; it takes %s" % (
            ", ".join(unknown), ", ".join(tuple(required) + tuple(optional)) or "nothing"))
    missing = [key for key in required if key not in value]
    if missing:
        raise DashboardError("this action needs %s" % ", ".join(missing))
    return value


def _string(fields, key, required=True):
    value = fields.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise DashboardError("%s is a string, got %r" % (key, value))
    return value


def run_action(name, project, body, headers=None, server=None):
    """Take one action on one project: `(status, report)`, the report being what the verb's function returned.

    `body` is the raw request body. The functions are the ones the verbs call, told `by="dashboard"`
    wherever the journal records who asked: `project.answer`, `set_autonomy`, `control`,
    `switch_project`, `steer_ticket`, `set_pacing`, `set_model_fallback`, `set_ladder_changes`, and `intake.drop_material`. Raises
    `DashboardError` for a body the action cannot take and `ActionConflict` for a switch already under
    way, and lets a verb's own refusal (a `ValueError`) through, which the handler answers with 400.
    """
    project = Path(project).resolve()
    if name == "intake":
        from wayline.intake import IntakeError, drop_material  # the intake imports the gates, which no view needs
        named = (headers or {}).get(FILENAME_HEADER)
        if not named:
            raise DashboardError("an intake drop names its file in the %s header" % FILENAME_HEADER)
        try:
            return HTTPStatus.OK, drop_material(project, unquote(named), body)
        except IntakeError as failure:
            raise DashboardError(str(failure)) from None
    if name == "answer":
        fields = _fields(body, ("ticket", "answer"), ("rationale", "confidence"))
        event = answer(project, fields["ticket"], _string(fields, "answer"),
                       rationale=_string(fields, "rationale", required=False), confidence=fields.get("confidence"), by="dashboard")
        return HTTPStatus.OK, {"decision": event["payload"], "conductor": conductor_holder(project)}
    if name == "autonomy":
        fields = _fields(body, ("autonomy",))
        return HTTPStatus.OK, set_autonomy(project, _string(fields, "autonomy"), by="dashboard")
    if name in ("pause", "resume"):
        _fields(body)
        event = control(project, name, by="dashboard")
        return HTTPStatus.OK, {"control": event["payload"], "conductor": conductor_holder(project)}
    if name in ("cancel", "rerun"):
        fields = _fields(body, ("ticket",))
        event = steer_ticket(project, name, fields["ticket"], by="dashboard")
        return HTTPStatus.OK, {"control": event["payload"], "conductor": conductor_holder(project)}
    if name == "pacing":
        fields = _fields(body, (), ("stop_at", "cheap_at"))
        return HTTPStatus.OK, set_pacing(project, stop_at=fields.get("stop_at"), cheap_at=fields.get("cheap_at"), by="dashboard")
    if name == "model_fallback":
        fields = _fields(body, ("model_fallback",))
        return HTTPStatus.OK, set_model_fallback(project, _string(fields, "model_fallback"), by="dashboard")
    if name == "ladder_changes":
        fields = _fields(body, ("ladder_changes",))
        return HTTPStatus.OK, set_ladder_changes(project, _string(fields, "ladder_changes"), by="dashboard")
    if name == "feedback":
        from wayline import changes  # the evolve loop imports the registry and the fixtures, which no view needs
        fields = _fields(body, ("text",))
        try:
            return HTTPStatus.OK, changes.file_feedback(project, _string(fields, "text"), source="dashboard")
        except changes.ChangeError as failure:
            raise DashboardError(str(failure)) from None
    if name == "switch":
        _fields(body)
        return _switch(project, server)
    raise DashboardError("no action %r; the actions are %s" % (name, ", ".join(ACTIONS)))


def _switch(project, server):
    """Make `project` the active one, as `wayline switch <path>` does, told `by="dashboard"`.

    The switch always runs on a thread of its own, because `switch_project` waits for a conductor on the
    project being left to drain, which lasts as long as that conductor's running workers do. With a
    conductor holding that project the reply is 202 at once, with its heartbeat. Without one the reply
    waits for the thread, up to `SWITCH_REPLY_S`, and is 200 with what it did or 400 with its refusal; a
    conductor the tick starts in between turns the switch into a drain, and the reply into 202, rather
    than holding the request. The tabs show the new active project once the thread has moved the pointer.
    One switch at a time: another is refused while one lasts.
    """
    lock = getattr(server, "switching", None) or threading.Lock()
    if not lock.acquire(blocking=False):
        raise ActionConflict("a switch is already waiting for a conductor to drain; the active project changes once it has ended")
    outcome = {}
    try:
        previous = read_active()
        previous = previous.resolve() if previous is not None else None
        leaving = previous if previous is not None and previous != project and is_project(previous) else None
        draining = conductor_holder(leaving) if leaving is not None else None
    except BaseException:
        lock.release()
        raise

    def switch():
        try:
            outcome["report"] = switch_project(project, by="dashboard")
        except Exception as failure:  # the reply raises it when it still waits; otherwise this line is all that says it
            outcome["failure"] = failure
            print("wayline serve: the switch to %s failed: %s" % (project, failure), file=sys.stderr, flush=True)
        finally:
            lock.release()

    thread = threading.Thread(target=switch, name="wayline-switch", daemon=True)
    thread.start()
    if draining is None:
        thread.join(SWITCH_REPLY_S)
        if not thread.is_alive():
            if "failure" in outcome:
                raise outcome["failure"]
            return HTTPStatus.OK, dict(outcome["report"], draining=None)
        draining = conductor_holder(leaving) if leaving is not None else None
    return HTTPStatus.ACCEPTED, {"from": str(previous) if previous is not None else None, "to": str(project), "moved": False,
                                 "drained": None, "draining": draining}


def _poll(project, key, default):
    if project is None or not is_project(project):
        return default
    try:
        value = read_harness(project).get("dashboard", {}).get(key, default)
    except (ProjectError, OSError):
        return default
    return value if isinstance(value, (int, float)) and value > 0 else default


def _pointer_snapshot():
    """The version of `/api/projects`: everything the tabs are built from, not only the pointers.

    The two per-machine pointers are most of it, but the view also says whether each project's
    directory is still there and carries the active project's poll intervals, so a project the
    owner deleted or a `harness.json` they edited has to move the tag. Without these a revalidating
    page would keep an enabled tab for a path that is gone, which is the one thing `readable` is
    for.
    """
    values = {}
    _stat_into(values, home() / "projects.json", "projects.json")
    _stat_into(values, home() / "active", "active")
    active = read_active()
    for entry in read_projects():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        values["readable:" + entry["path"]] = is_project(Path(entry["path"]))
    if active is not None:
        _stat_into(values, Path(active) / HARNESS_JSON, "active:" + HARNESS_JSON)
    return values


def _active_version():
    """`(mtime_ns, size)` of the active pointer: the overview says whether it names this project."""
    values = {}
    _stat_into(values, active_path(), "active")
    return values


def _readings_window(ttl_s):
    """Which window of `ttl_s` seconds this request falls in, so a live reading cannot freeze.

    A zero or negative ttl means a reading is never reused: every request gets its own window, and
    so its own tag. That is what a test asks for when it wants to see the readings move.
    """
    return time.time_ns() if not ttl_s or ttl_s <= 0 else int(time.time() // ttl_s)


def _journal_version(ledger):
    """`(mtime_ns, size)` of the journal: its whole version, because it is append-only."""
    try:
        stamp = ledger.journal_path.stat()
    except OSError:
        return (0, 0)
    return (stamp.st_mtime_ns, stamp.st_size)


def _journal_lines(ledger, position):
    """The whole lines after `position`, each with the offset that follows it, and the new position.

    Per-line offsets, not the offset at the end of the read: research-notes 08 measured that a
    reconnect from a chunk-end id splits the next line.
    """
    size = _journal_size(ledger)
    if size <= position:
        return [], position
    try:
        with open(ledger.journal_path, "rb") as handle:
            handle.seek(position)
            chunk = handle.read()
    except OSError:
        return [], position
    lines, offset = [], position
    for raw in chunk.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break  # a line still being written; it arrives whole on the next tick
        offset += len(raw)
        stripped = raw.rstrip(b"\n")
        if stripped.strip():
            lines.append((offset, stripped))
    return lines, offset


def _tail_lines(value):
    """The `tail=<lines>` parameter: None when absent, capped so one request cannot ask for a book."""
    if value in (None, ""):
        return None
    try:
        lines = int(value)
    except (TypeError, ValueError):
        raise DashboardError("tail takes a number of lines, got %r" % (value,)) from None
    if lines <= 0:
        raise DashboardError("tail takes a number of lines above zero, got %d" % lines)
    return min(lines, TAIL_LINES_MAX)


def _offset(value):
    try:
        offset = int(value)
    except (TypeError, ValueError):
        raise DashboardError("since takes a byte offset, got %r" % (value,)) from None
    if offset < 0:
        raise DashboardError("since takes a byte offset at or after zero, got %d" % offset)
    return offset


def make_server(bind=LOOPBACK, port=0, token=None, require_token=None, static_root=None, sse_tick_s=SSE_TICK_S, memo_ttl=SNAPSHOT_MEMO_S, readings_ttl_s=READINGS_TTL_S, handler=None):
    """A bound, unstarted dashboard server. `port=0` takes a free port, which the tests use."""
    if require_token is None:
        require_token = requires_token(bind)
    if require_token and not token:
        raise DashboardError("a dashboard bound to %s needs a token; %s holds one" % (bind, dashboard_path()))
    return DashboardServer(
        (bind, port), handler or DashboardHandler, token=token, require_token=require_token,
        static_root=static_root, sse_tick_s=sse_tick_s, memo_ttl=memo_ttl, readings_ttl_s=readings_ttl_s,
    )


def serve(bind=None, port=None, project=None, workstation=None, out=None):
    """Start the dashboard and serve until the owner interrupts it. Returns an exit code."""
    out = out or sys.stdout
    settings = read_settings(port=port, bind=bind, project=project)
    try:
        server = make_server(settings["bind"], settings["port"], token=settings["token"])
    except (OSError, DashboardError) as failure:
        print("wayline serve: %s" % failure, file=sys.stderr)
        return 1
    settings["port"] = server.server_address[1]
    record_settings(settings)
    for line in serve_lines(settings, projects_view(settings=settings), workstation, with_token=is_terminal(out)):
        print(line, file=out)
    out.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("", file=out)
    finally:
        server.stopping.set()
        server.server_close()
    return 0


def serve_command(args):
    parser = argparse.ArgumentParser(prog="wayline serve", description="the dashboard, bound to localhost")
    parser.add_argument("--bind", help="the address to bind; 127.0.0.1 by default, and anything wider needs the token on every request")
    parser.add_argument("--port", type=int, help="the port; harness.json's dashboard.port (8765) by default")
    parser.add_argument("--project", help="the project whose dashboard settings are read; the active one by default")
    try:
        options = parser.parse_args(args)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 2
    # A port outside the range is a typo, not a preference: substituting 8765 for it would print a
    # URL and a tunnel line for a port the owner never asked for.
    if options.port is not None and not 0 <= options.port <= 65535:
        print("wayline serve: --port takes a port from 0 to 65535, got %d" % options.port, file=sys.stderr)
        return 2
    project = None
    if options.project is not None:
        project = Path(options.project).expanduser()
        if not is_project(project):
            print("wayline serve: %s is not a wayline project (no %s)" % (project, HARNESS_JSON), file=sys.stderr)
            return 1
    elif read_active() is not None and is_project(read_active()):
        project = read_active()
    return serve(bind=options.bind, port=options.port, project=project)
