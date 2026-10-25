"""The showcase: wayline's dashboard over a finished run, as a static site anyone can open.

`python3 -m showcase.build <out>` extracts the snapshot of the M8 toy run (`showcase/toy.tar.xz`, described by
`showcase/toy.json`), serves it with this checkout's own dashboard server on a loopback port, asks the server every GET
the page makes, and writes each answer beside this checkout's own page: `dashboard/index.html` with its asset paths
made relative and one script added before the page's own, `replay.js`, which answers the page's requests from the
recordings, and `app.js`, `style.css`, and `vendor/` as they are. So the showcase is the interface of the commit it is
built from: `.github/workflows/showcase.yml` builds and publishes it on every push to master, and
`tests/test_showcase.py` fails when the server gains a GET route `COVERAGE` does not account for, or a view stops
answering over the snapshot. Nothing in the showcase writes: `replay.js` refuses a POST, and the page, opened without
the dashboard's token, keeps its buttons and the chat off and says why. Two things are the run's rather than the
building machine's: the project's path, and the overview's slots, which are the reading the run's workstation gave when
the snapshot was made (`toy.json`).

`python3 -m showcase.build --snapshot <project>` makes the archive again from a finished project, serving it the same
way and keeping every file the views read, beside the paper, the plots and figures, the built documentation site, and
the small result files. Left out whatever reads them: the session transcripts (each an empty file, so a ticket still
lists its sessions), a session's environment and settings, the raw result tables, and the git, worktree, and cache
directories. `harness.json` loses the owner's address and the notifier, which no view shows, and an archive in which
anything matches a secret's pattern is refused.
"""

import argparse
import copy
import datetime
import http.client
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

import wayline.project
from wayline import TAG, chat, dashboard_views, docs, resources, sections
from wayline.dashboard import LOOPBACK, STATIC_ROOT, make_server
from wayline.project import register, set_active

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "toy.tar.xz"
ABOUT = HERE / "toy.json"
PROJECT = "toy"
REPOSITORY = "https://github.com/Bernaljp/wayline"
# Copied into the site as they are, beside the page's own files.
OWN_FILES = ("replay.js", "withheld.html")

RECORDED, FILES = "recorded", "files"

# Each GET route of the dashboard server (`DashboardHandler.ROUTES`), and how the showcase answers it: from a
# recording, from the published copy of a file, or not at all, for the reason given. `tests/test_showcase.py` fails on
# a route missing here, so a view the server gains is one the showcase answers or says why it does not.
COVERAGE = {
    "api_projects": RECORDED,
    "api_overview": RECORDED,
    "api_journal": RECORDED,
    "api_graph": RECORDED,
    "api_tickets": RECORDED,
    "api_ticket": RECORDED,
    "api_logs": RECORDED,
    "api_outputs": RECORDED,
    "api_download": FILES,
    "api_site": FILES,
    "api_decisions": RECORDED,
    "api_changes": RECORDED,
    "api_research": RECORDED,
    "api_run": RECORDED,
    "api_paper": RECORDED,
    "api_inherited": RECORDED,
    "api_marks": RECORDED,
    "api_waiting": RECORDED,
    "api_item": RECORDED,
    "api_edit": RECORDED,
    "api_chat": RECORDED,
    "api_paper_card": RECORDED,
    "api_card": "a card opens from a button, and a page without the token keeps its buttons off",
    "api_action_get": "an action is a POST, and the showcase takes none",
}

# What the page polls for the project it shows, after `/api/projects` and beside the journal's tail.
VIEWS = ("overview", "graph.svg", "tickets", "outputs", "decisions", "changes", "research", "run", "paper", "inherited",
         "marks", "waiting", "chat", "paper/card")
# Items the page links by name rather than by a numbered id.
NAMED_ITEMS = ("report", "account", "outline") + tuple(sections.SECTIONS)
# An item id where a view or a rendered file writes one: the lettered kinds of `dashboard_views.ITEM_ID`, unanchored.
ITEM_IN_TEXT = re.compile(r"(?<![\w.+-])(O[1-9]\d*|R[1-9]\d*(?:\.T?[1-9]\d*|-[1-9]\d*)?|[DKM][1-9]\d*|P[1-9]\d*(?:\+P[1-9]\d*)?)(?![\w+])")

# What `--snapshot` keeps beside the files the views read: what a reader of the run looks at.
PUBLISHED = ("drawings", "figures", "research/drawings", "research/paper", docs.HTML_DIR.as_posix())
SMALL_RESULT = 64 * 1024  # a JSON file under `results/` is kept up to this size; the tables and arrays are not
NEVER_NAMES = frozenset({"stream.jsonl", "stderr.txt", "env.json", "settings.json", "pid", ".env"})
NEVER_ROOTS = (".git/", ".worktrees/", ".wayline/", ".claude/")
KEPT_CACHE = (docs.HTML_DIR.as_posix() + "/", docs.CHECKS_JSON.as_posix())
# Where the build extracts the snapshot; no recording may name it (`tests/test_showcase.py`).
SCRATCH_PREFIX = "wayline-showcase-build-"
SECRET = re.compile(rb"sk-ant-[a-z0-9]{2,8}-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
                    rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY|"
                    rb"CLAUDE_CODE_OAUTH_TOKEN\s*=\s*['\"]?[A-Za-z0-9_\-]{30,}")


class ShowcaseError(RuntimeError):
    """The showcase cannot be built or snapshotted as asked."""


def tail_lines():
    """How many lines the page's first read of the journal asks for (`TAIL_LINES` in `dashboard/app.js`)."""
    found = re.search(r"^const TAIL_LINES = (\d+);$", (STATIC_ROOT / "app.js").read_text(encoding="utf-8"), re.M)
    if found is None:
        raise ShowcaseError("dashboard/app.js no longer names TAIL_LINES, the line count of its first journal read")
    return int(found.group(1))


@contextmanager
def served(project, home, machine=None):
    """The dashboard serving `project` alone on a loopback port, under `home` as `~/.wayline`; yields `get(path)`,
    which returns `(status, headers, body)`. No message of the chat is answered, so no model runs. `machine`, when
    given, is the slots and reservation the overview shows in place of this machine's live reading."""
    if not hasattr(wayline.project, "resources_snapshot"):
        raise ShowcaseError("wayline.project no longer reads the machine through resources_snapshot, where the "
                            "showcase puts the run's own reading")
    saved_home, saved_start, saved_reading = os.environ.get("WAYLINE_HOME"), chat.start, wayline.project.resources_snapshot
    os.environ["WAYLINE_HOME"] = str(home)
    chat.start = lambda *args, **kwargs: False
    if machine is not None:
        wayline.project.resources_snapshot = lambda *args, **kwargs: copy.deepcopy(machine)
    server = None
    try:
        register(project, TAG)
        set_active(project)
        server = make_server(LOOPBACK, 0, require_token=False, memo_ttl=0.0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host, port = server.server_address[:2]

        def get(path):
            connection = http.client.HTTPConnection(host, port, timeout=120)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
            finally:
                connection.close()

        yield get
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        chat.start, wayline.project.resources_snapshot = saved_start, saved_reading
        if saved_home is None:
            os.environ.pop("WAYLINE_HOME", None)
        else:
            os.environ["WAYLINE_HOME"] = saved_home


def _json(path, answer):
    status, _, body = answer
    if status != 200:
        raise ShowcaseError("GET %s answered %d: %s" % (path, status, body[:300].decode("utf-8", "replace")))
    return json.loads(body)


def crawl(get, project):
    """Every GET the page makes over the one project the server lists: `{path: (status, headers, body)}`.

    The views the page polls, the journal's first screenful, each ticket's page and the logs of its jobs, the editor's
    text of each section and the outline, and every item a view or a rendered file of `project` names, until an item's
    answer names no new one. Downloads and the documentation site are not asked for: the showcase publishes the files.
    """
    answers = {}

    def ask(path):
        if path not in answers:
            answers[path] = get(path)
        return answers[path]

    listed = _json("/api/projects", ask("/api/projects"))["projects"]
    if len(listed) != 1:
        raise ShowcaseError("the showcase serves one project; the server lists %d" % len(listed))
    base = "/api/projects/" + quote(listed[0]["id"], safe="")
    for view in VIEWS:
        ask("%s/%s" % (base, view))
    ask("%s/journal?tail=%d" % (base, tail_lines()))
    numbers = [ticket["id"] for ticket in _json(base + "/tickets", answers[base + "/tickets"])]
    for number in numbers:
        path = "%s/tickets/%d" % (base, number)
        for job in _json(path, ask(path)).get("jobs") or []:
            ask("%s/logs/job/%s?since=0" % (base, job["id"]))
    for name in sections.SECTIONS + ("outline",):
        ask("%s/edit/%s" % (base, name))
    texts = [body for status, _, body in answers.values() if status == 200]
    texts += [path.read_bytes() for path in _markdown(Path(project) / "research")]
    tried = set()
    while True:
        named = {item for text in texts for item in ITEM_IN_TEXT.findall(text.decode("utf-8", "replace"))}
        named |= {str(number) for number in numbers} | set(NAMED_ITEMS)
        new = sorted(item for item in named - tried if dashboard_views.ITEM_ID.match(item))
        if not new:
            return answers
        tried.update(new)
        for item in new:
            status, _, body = ask("%s/items/%s" % (base, quote(item, safe="")))
            if status == 200:
                texts.append(body)


def _markdown(research):
    """The Markdown files under `research/` but the caches and the sessions, which a finished project fills with a
    documentation environment and transcripts no view renders."""
    for directory, children, names in os.walk(research):
        children[:] = [name for name in children if name not in (".cache", "sessions")]
        yield from (Path(directory) / name for name in names if name.endswith(".md"))


def key(path):
    """A request as `replay.js` looks it up: the path decoded, then the query sorted, without the token."""
    parts = urlsplit(path)
    query = sorted((name, value) for name, value in parse_qsl(parts.query) if name != "token")
    return unquote(parts.path) + ("?" + urlencode(query) if query else "")


def _published_files(project):
    """Every file of the extracted snapshot the site publishes, `(path, where in the site)`: the documentation site
    under `site/`, the rest under `files/`; never a transcript's empty stand-in, nor a path through a hidden directory,
    which a static host may not serve."""
    site = docs.HTML_DIR.as_posix() + "/"
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project).as_posix()
        if path.name == "stream.jsonl" and path.stat().st_size == 0:
            continue
        where = "site/" + relative[len(site):] if relative.startswith(site) else "files/" + relative
        if not any(part.startswith(".") for part in where.split("/")):
            yield relative, where


def _about(about):
    try:
        return json.loads(Path(about).read_text(encoding="utf-8"))
    except OSError:
        return {}


def _withheld(about):
    """The lines `replay.js` answers with where the showcase holds nothing; `{path}` and `{id}` are filled in there."""
    left = about.get("left_out", {})
    transcripts = left.get("transcripts", {})
    return {
        "transcripts": "Session transcripts are not part of the showcase (%d sessions, %d MB in all); the ticket's page "
                       "shows what each session returned." % (transcripts.get("count", 0), transcripts.get("bytes", 0) // 10**6),
        "tick": "The machine's tick log is not part of the showcase.",
        "file": "{path} is not part of the showcase, which publishes the paper, the reports, the plots and figures, the "
                "documentation site, and the small result files, but not the raw result tables or the transcripts.",
        "item": "{id}: not part of this showcase",
        "missing": "{path} is not part of the showcase.",
        "action": "This is a read-only showcase of a finished run: nothing can be changed from it.",
    }


def _banner(files):
    links = [["the paper (PDF)", "files/" + path] for path in ("research/paper/compilations/arxiv/paper.pdf",) if path in files]
    links += [["about this run", REPOSITORY + "/tree/master/showcase#readme"], ["wayline on GitHub", REPOSITORY]]
    return {
        "title": "A read-only showcase.",
        "text": "wayline's own dashboard over a toy run of October 24 to 25, 2026: an hour's setup, an autonomous night, "
                "and a compiled paper the next afternoon. Rebuilt whenever the interface changes; the buttons and the "
                "chat are off.",
        "links": links,
    }


def build(out, archive=ARCHIVE, about=ABOUT):
    """Write the site to `out` (a directory that does not exist, is empty, or holds an earlier showcase); returns
    `{path: status}` of what was recorded."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        if not (out / "showcase.json").is_file():
            raise ShowcaseError("%s holds files and no showcase.json; the showcase writes only into its own directory" % out)
        shutil.rmtree(out)
    about = _about(about)
    with tempfile.TemporaryDirectory(prefix=SCRATCH_PREFIX) as scratch:
        scratch = Path(scratch)
        with tarfile.open(archive) as tar:
            tar.extractall(scratch, filter="data")
        project = scratch / PROJECT
        with served(project, scratch / "home", machine=(about.get("machine") or {}).get("view")) as get:
            answers = crawl(get, project)
        # The project where the run kept it, rather than where this build extracted it.
        where = [(path.encode(), about.get("source", PROJECT).encode())
                 for path in sorted({str(project), str(project.resolve())}, key=len, reverse=True)]
        out.mkdir(parents=True)
        recordings, tags = {}, {}
        (out / "r").mkdir()
        for number, path in enumerate(sorted(answers)):
            status, headers, body = answers[path]
            for scratch_path, kept_path in where:
                body = body.replace(scratch_path, kept_path)
            kind = headers.get("content-type", "text/plain")
            name = "r/%d%s" % (number, ".json" if "json" in kind else ".svg" if "svg" in kind else ".txt")
            (out / name).write_bytes(body)
            recordings[key(path)] = {"status": status, "type": kind, "etag": headers.get("etag"), "body": name}
            if headers.get("etag"):
                tags.setdefault(unquote(urlsplit(path).path), []).append(headers["etag"])
        files = []
        for relative, where in _published_files(project):
            target = out / where
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / relative, target)
            if where.startswith("files/"):
                files.append(relative)
    page = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(page_of(page), encoding="utf-8")
    for name in ("app.js", "style.css"):
        shutil.copyfile(STATIC_ROOT / name, out / name)
    shutil.copytree(STATIC_ROOT / "vendor", out / "vendor")
    for name in OWN_FILES:
        shutil.copyfile(HERE / name, out / name)
    index = {"project": PROJECT, "recordings": recordings, "tags": tags, "files": files, "withheld": _withheld(about),
             "banner": _banner(set(files)), "snapshot": about}
    (out / "showcase.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {path: answers[path][0] for path in answers}


def page_of(page):
    """The dashboard's `index.html` as the showcase serves it: its asset paths relative, so the site works under any
    path, and `replay.js` loaded before the page's first script."""
    page = re.sub(r'\b(href|src)="/(?!/)', r'\1="', page)
    first = page.index("<script ")
    return page[:first] + '<script src="replay.js"></script>\n' + page[first:]


# --- the snapshot ---------------------------------------------------------------------------------------------------

_reading = threading.Event()


def _left_out(path):
    """Whether a project file stays out of the snapshot whatever reads it: a transcript, a session's environment or
    settings, a dotenv, or anything under git, the worktrees, the machine's pointers, or a cache but the built site."""
    if path.rsplit("/", 1)[-1] in NEVER_NAMES or path.startswith(NEVER_ROOTS):
        return True
    return path.startswith("research/.cache/") and not path.startswith(KEPT_CACHE)


def _scrubbed(path, data):
    """A file as the snapshot keeps it: `harness.json` without the owner's address and the notifier, which no view shows."""
    if path != "harness.json":
        return data
    value = json.loads(data)
    value["owner_email"] = None
    value.pop("notify", None)
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def snapshot(source, archive=ARCHIVE, about=ABOUT):
    """Make `archive` and `about` again from the finished project at `source`; returns what `about` records."""
    source = Path(source).resolve()
    root = str(source) + os.sep
    read = set()

    def hook(event, args):
        if _reading.is_set() and event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.path.abspath(os.fsdecode(args[0]))
            if path.startswith(root):
                read.add(path[len(root):].replace(os.sep, "/"))

    sys.addaudithook(hook)  # a hook stays for the life of the process, so `_reading` gates it to the crawl
    with tempfile.TemporaryDirectory(prefix="showcase-home-") as home:
        with served(source, Path(home)) as get:
            _reading.set()
            try:
                crawl(get, source)
            finally:
                _reading.clear()
    chosen = {path for path in read if (source / path).is_file()}
    for top in PUBLISHED:
        chosen.update(path.relative_to(source).as_posix() for path in (source / top).rglob("*") if path.is_file())
    results = [path for path in (source / "results").rglob("*") if path.is_file()]
    chosen.update(path.relative_to(source).as_posix() for path in results
                  if path.suffix == ".json" and path.stat().st_size <= SMALL_RESULT)
    chosen = sorted(path for path in chosen if not _left_out(path) and not (source / path).is_symlink())
    transcripts = sorted((source / "research" / "sessions").rglob("stream.jsonl"))
    written = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=written, mode="w:xz", preset=9) as tar:
        for path in chosen:
            data = _scrubbed(path, (source / path).read_bytes())
            found = SECRET.search(data)
            if found:
                raise ShowcaseError("%s matches a secret's pattern (%s...); nothing was written" % (path, found.group(0)[:12]))
            total += len(data)
            tar.addfile(_entry(path, len(data), (source / path).stat().st_mtime), io.BytesIO(data))
        for transcript in transcripts:
            path = transcript.relative_to(source).as_posix()
            tar.addfile(_entry(path, 0, transcript.stat().st_mtime), io.BytesIO(b""))
    kept_results = {path for path in chosen if path.startswith("results/")}
    machine = resources.snapshot(json.loads((source / "harness.json").read_text(encoding="utf-8")), [])
    for gpu in machine["gpus"]:
        gpu["uuid"] = ""  # a hardware identifier, which no view shows
    record = {
        "what": "The M8 toy run (ticket 122): wayline's v1.1.0 line, before its release, under autonomous on a synthetic "
                "two-class question, October 24 to 25, 2026. Recorded in docs/verification/m8.md, section \"The toy "
                "overnight on v1.1.0\".",
        "made": datetime.date.today().isoformat(),
        "source": "~/" + source.relative_to(Path.home()).as_posix() if source.is_relative_to(Path.home()) else str(source),
        # The overview's slots as the run's own workstation read them when the snapshot was made, with no job running.
        "machine": {"read_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "view": machine},
        "files": len(chosen),
        "bytes": total,
        "left_out": {
            "transcripts": {"count": len(transcripts), "bytes": sum(path.stat().st_size for path in transcripts)},
            "results": {"count": len(results) - len(kept_results),
                        "bytes": sum(path.stat().st_size for path in results) - sum((source / path).stat().st_size for path in kept_results)},
        },
        "scrubbed": {"harness.json": ["owner_email", "notify"], "machine": ["each GPU's uuid"]},
    }
    Path(archive).write_bytes(written.getvalue())
    Path(about).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _entry(path, size, mtime):
    """A file's entry in the archive, owned by nobody in particular."""
    entry = tarfile.TarInfo("%s/%s" % (PROJECT, path))
    entry.size, entry.mtime, entry.mode = size, int(mtime), 0o644
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m showcase.build", description=__doc__.split("\n\n")[0])
    parser.add_argument("out", nargs="?", help="the directory the site is written to")
    parser.add_argument("--snapshot", metavar="PROJECT", help="make showcase/toy.tar.xz again from this finished project first")
    args = parser.parse_args(argv)
    if not args.out and not args.snapshot:
        parser.error("name the directory to write the site to, or --snapshot PROJECT, or both")
    try:
        if args.snapshot:
            record = snapshot(args.snapshot)
            print("snapshot: %d files, %d bytes, into %s" % (record["files"], record["bytes"], ARCHIVE))
        if args.out:
            statuses = build(args.out)
            failed = sorted(path for path, status in statuses.items() if status >= 500)
            print("showcase: %d recordings into %s%s" % (len(statuses), args.out, "; failed: " + ", ".join(failed) if failed else ""))
            return 1 if failed else 0
    except ShowcaseError as failure:
        print("showcase: %s" % failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
