"""A project: what `init` lays down, what `status` reads back, and where `switch` points.

Implementation Decisions 1 fixes three things this module owns. The project layout: `CLAUDE.md`
with a wayline block, `harness.json` with the pin and the defaults, the `research/` ledger, the
`.claude/` symlinks that make harness skills and workflow scripts visible from a worktree, the
`.gitignore` entries, and a git repository to branch worktrees from. The per-machine pointers:
`~/.wayline/projects.json` and `~/.wayline/active`, which live outside the harness repository
because mutable pointers would dirty a tagged checkout, and outside any project because they
name projects. And the two views that work without a dashboard: `status` and `switch`.

`init` is idempotent by construction: every step writes only what is absent or stale, so a
second run on the same path changes nothing in the project, and a run after an upgrade refreshes
the symlinks and nothing else. The harness home can be moved with `WAYLINE_HOME`, which is what
the tests set so they never touch the owner's `~/.wayline/`.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from string import Template

from wayline import HARNESS_ROOT, POLICY_PATH, TAG, replay
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import CONTROL, DECISION, SWITCHED, Ledger, atomic_write, conductor_holder, now_ts
from wayline.resources import (
    LIVE_JOB_STATUSES, ResourceError, render_resources, snapshot as resources_snapshot,
)
from wayline.tickets import DECISION as DECISION_KIND
from wayline.tickets import (
    GRAPH, SATISFIED, answer_section, by_status, empty_graph, filename, frontier, open_decisions, read_graph,
    read_ticket, read_tickets, refresh_graph, tickets_dir, with_answer, write_ticket,
)

__all__ = [
    "ProjectError", "HARNESS_JSON", "RESEARCH", "GITIGNORE_ENTRIES", "RESEARCH_DIRS",
    "home", "projects_path", "active_path", "read_active", "set_active", "read_projects",
    "register", "default_harness", "detect_hermes", "detect_email", "ask_email", "read_harness", "find_project", "is_project", "policy_for",
    "init_project", "refresh_symlinks", "status_view", "render_status", "switch_project", "read_jobs",
    "window_status", "goal_progress", "init_command", "status_command", "switch_command",
    "control", "answer", "wait_for_conductor", "DRAIN_POLL_S", "AUTONOMY", "set_autonomy",
    "pause_command", "resume_command", "stop_command", "cancel_command", "rerun_command", "answer_command",
]

HARNESS_JSON = "harness.json"
CLAUDE_MD = "CLAUDE.md"
RESEARCH = "research"
GOAL_JSON = "GOAL.json"
JOBS = "jobs"

# The block `init` appends to CLAUDE.md, marked so a second run can find and refresh it instead
# of appending a second copy, and so an owner's own CLAUDE.md is never overwritten.
BLOCK_BEGIN = "<!-- wayline:begin -->"
BLOCK_END = "<!-- wayline:end -->"

GITIGNORE_HEADER = "# wayline"
# The four entries of Implementation Decisions 1, plus the e-print sources: arXiv's terms of use
# forbid re-serving an e-print, so a pushed project never carries the ones its dossiers fetched.
# And the conductor's heartbeat, which is rewritten every wave and means nothing in a commit.
GITIGNORE_ENTRIES = (".worktrees/", "results/", "research/.cache/", "research/sessions/*/*/stream.jsonl", "research/refs/*/source/", "research/conductor.json")

# The directories of the `research/` tree of Implementation Decisions 1.
RESEARCH_DIRS = ("tickets", "refs", "kb", "jobs", "sessions", "paper", "feedback", ".cache")
# The directories a project keeps outside the ledger; both are gitignored.
PROJECT_DIRS = (".worktrees", "results")
# The house style (Implementation Decisions 13): the harness default, copied once into the project,
# where the owner and the figure role edit it and a later `init` never overwrites it.
STYLE_DEFAULT = Path("figures") / "style.default.json"
STYLE_JSON = Path("figures") / "style.json"

JOURNAL = "journal.jsonl"
FINDINGS = "findings.jsonl"
MANIFEST = "manifest.json"

# The autonomy settings from the least autonomous to the most (BRIEF 6.2), one line each, so what
# the owner reads says what the setting does and not only its name.
AUTONOMY = {
    "interactive": "the owner answers every question the grill asks, approves the spec and the graph, answers every decision ticket, and is asked on every `needs_human` result.",
    "checkpoints": "the owner approves the spec and the graph and answers decision tickets; waves run alone.",
    "autonomous": "the decider resolves every open question, every decision ticket not in a human-only class, and every parked proposal, and never anything on the irreversible list.",
}

# `LIVE_JOB_STATUSES` (Implementation Decisions 6) is the job runner's, re-exported here because
# the views were reading it from this module before the runner existed.

_DETECT = object()
_HERMES_PYTHON = Path(".hermes/hermes-agent/venv/bin/python")


class ProjectError(ValueError):
    """A project the harness cannot use, or a pointer it cannot follow."""


# --- the per-machine pointers ------------------------------------------------------------------


def home():
    """`~/.wayline`, or `$WAYLINE_HOME` when it is set (the tests set it)."""
    override = os.environ.get("WAYLINE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".wayline"


def projects_path():
    return home() / "projects.json"


def active_path():
    return home() / "active"


def read_active():
    """The active project's path, or None when no project is active."""
    try:
        text = active_path().read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return Path(text) if text else None


def set_active(project):
    """Point `~/.wayline/active` at a project."""
    target = home()
    target.mkdir(parents=True, exist_ok=True)
    atomic_write(active_path(), str(Path(project).resolve()) + "\n")


def read_projects():
    """Every project `init` has touched: a list of `{path, name, harness_tag, created}`."""
    try:
        value = json.loads(projects_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return value if isinstance(value, list) else []


def register(project, harness_tag):
    """Add or refresh a project's entry in `~/.wayline/projects.json`, keeping its `created`.

    Returns the entry written and whether the file changed.
    """
    project = Path(project).resolve()
    entries = read_projects()
    entry = {"path": str(project), "name": project.name, "harness_tag": harness_tag, "created": now_ts()}
    updated, replaced = [], False
    for existing in entries:
        if isinstance(existing, dict) and existing.get("path") == str(project):
            entry["created"] = existing.get("created", entry["created"])
            updated.append(entry)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(entry)
    text = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    path = projects_path()
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, text)
    return entry, changed


# --- harness.json ------------------------------------------------------------------------------


def _policy(harness_root=None):
    """The global defaults of a harness checkout: its own `policy.json`, else the shipped one."""
    if harness_root is not None:
        candidate = Path(harness_root) / "policy.json"
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))


def policy_for(project=None, harness_root=None):
    """The effective policy: the harness defaults under the project's `harness.json` overrides.

    The project's file is read tolerantly, because `wayline accept` runs inside a worktree from a
    worker session and must not fail over an override it cannot read: an unreadable or absent
    `harness.json` leaves the global defaults standing.
    """
    value = _policy(harness_root)
    if project is None:
        return value
    try:
        overrides = json.loads((Path(project) / HARNESS_JSON).read_text(encoding="utf-8")).get("policy")
    except (OSError, ValueError, AttributeError):
        overrides = None
    return _merge(value, overrides if isinstance(overrides, dict) else {})


def _merge(base, overrides):
    """`overrides` wins key by key; two dicts under one key merge, so a project may override one number."""
    merged = dict(base)
    for key, value in overrides.items():
        merged[key] = _merge(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
    return merged


def detect_hermes():
    """The interpreter that runs `hermes_cli`, when this machine has one (Implementation Decisions 7)."""
    candidate = Path.home() / _HERMES_PYTHON
    return str(candidate) if candidate.exists() else None


def detect_email(project=None):
    """The address git is configured with, which is the one `init` offers the owner.

    The polite pools of Crossref, Unpaywall, and their kin want a real address, and the owner
    already gave git one; asking for it again is a question with an obvious answer.
    """
    where = Path(project) if project is not None else Path.home()
    try:
        done = _git(where, "config", "--get", "user.email", check_exit=False)
    except (OSError, ProjectError):
        return None
    address = done.stdout.strip()
    return address if "@" in address else None


def default_harness(harness_tag=TAG, policy=None, hermes_python=_DETECT, owner_email=None):
    """`harness.json` as `init` writes it: the pin and the defaults of Implementation Decisions 14."""
    policy = policy if policy is not None else _policy()
    reservations = policy.get("reservations", {})
    pacing = policy.get("pacing", {})
    dashboard = policy.get("dashboard", {})
    value = {
        "harness_tag": harness_tag,
        "autonomy": "checkpoints",
        "radius": "moderate",
        "human_only": ["goal", "data"],  # decision 4: goal and data changes wait for the owner
        "reservations": {
            "gpu": list(reservations.get("gpu", [])),
            "cores": reservations.get("cores", 8),
            "ram_gb": reservations.get("ram_gb", 64),
            "processes": list(reservations.get("processes", [])),
        },
        "pacing": {"stop_at": pacing.get("stop_at", 0.90), "cheap_at": pacing.get("cheap_at", 0.80)},
        "dashboard": {
            "port": dashboard.get("port", 8765),
            "bind": dashboard.get("bind", "127.0.0.1"),
            "poll_journal_s": dashboard.get("poll_journal_s", 2),
            "poll_views_s": dashboard.get("poll_views_s", 5),
        },
        "notify": {"hermes_python": detect_hermes() if hermes_python is _DETECT else hermes_python},
        "owner_email": owner_email or None,
        "policy": {},
    }
    check(value, load_schema("harness"), name=HARNESS_JSON)
    return value


def read_harness(project):
    """A project's `harness.json`, validated."""
    path = Path(project) / HARNESS_JSON
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectError("%s is not a wayline project (no %s); run wayline init %s" % (project, HARNESS_JSON, project)) from None
    except ValueError as failure:
        raise ProjectError("%s is not readable JSON: %s" % (path, failure)) from None
    try:
        check(value, load_schema("harness"), name=str(path))
    except ValidationError as failure:
        raise ProjectError(str(failure)) from None
    return value


def is_project(path):
    return (Path(path) / HARNESS_JSON).is_file()


def find_project(explicit=None):
    """The project a verb acts on: `--project <path>` when given, else the active pointer."""
    if explicit:
        project = Path(explicit).expanduser().resolve()
        if not is_project(project):
            raise ProjectError("%s is not a wayline project (no %s)" % (project, HARNESS_JSON))
        return project
    active = read_active()
    if active is None:
        raise ProjectError("no active project; run wayline init <path> or wayline switch <path>")
    if not is_project(active):
        raise ProjectError("the active project %s has no %s; run wayline switch <path>" % (active, HARNESS_JSON))
    return active.resolve()


# --- init ---------------------------------------------------------------------------------------


def init_project(path, harness_root=None, harness_tag=TAG, git=True, hermes_python=_DETECT, owner_email=_DETECT):
    """Lay out a project at `path`, register it, and make it active. Returns a report.

    The report is `{"project", "changes", "created", "displaced", "notes"}`: `changes` names every
    file, directory, or symlink this run wrote, so a second run on the same path reports none.
    """
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    project = Path(path).expanduser().resolve()
    created = not project.exists()
    project.mkdir(parents=True, exist_ok=True)
    if not project.is_dir():
        raise ProjectError("%s is not a directory" % project)
    changes, notes = [], []

    def mark(relative):
        changes.append(str(relative))

    # harness.json: written once. `upgrade` moves the pin; `init` never rewrites an owner's file.
    harness_path = project / HARNESS_JSON
    if not harness_path.exists():
        address = detect_email(project) if owner_email is _DETECT else owner_email
        defaults = default_harness(harness_tag, policy=_policy(harness_root), hermes_python=hermes_python, owner_email=address)
        atomic_write(harness_path, json.dumps(defaults, ensure_ascii=False, indent=2) + "\n")
        mark(HARNESS_JSON)
        pinned_tag = harness_tag
        if not address:
            notes.append("no owner address; the scout's requests will carry no mailto, which the polite pools ask for (wayline init --email <address> on a fresh project, or add owner_email to harness.json)")
    else:
        pinned_tag = read_harness(project).get("harness_tag", harness_tag)

    # CLAUDE.md: the block is appended to whatever is there, and refreshed in place afterwards.
    changed, note = _write_claude_block(project, harness_root, pinned_tag)
    if changed:
        mark(CLAUDE_MD)
    if note:
        notes.append(note)

    # .gitignore: the four entries of Implementation Decisions 1, appended once.
    if _write_gitignore(project):
        mark(".gitignore")

    # The project directories that live outside the ledger.
    for name in PROJECT_DIRS:
        if not (project / name).exists():
            (project / name).mkdir(parents=True)
            mark(name + "/")

    # figures/style.json: the house style, copied from the harness default once and never again.
    style_default = harness_root / STYLE_DEFAULT
    if not (project / STYLE_JSON).exists():
        if style_default.is_file():
            (project / STYLE_JSON).parent.mkdir(parents=True, exist_ok=True)
            atomic_write(project / STYLE_JSON, style_default.read_text(encoding="utf-8"))
            mark(STYLE_JSON.as_posix())
        else:
            notes.append("the harness has no %s; the project has no house style until one is written" % STYLE_DEFAULT.as_posix())

    # The research/ tree, through the ledger: it is the only code that writes under research/.
    changes.extend(_write_research(project, harness_root, pinned_tag))

    # The .claude/ tree: symlinks to the harness skills and workflow scripts, refreshed when stale.
    symlink_changes, symlink_notes = refresh_symlinks(project, harness_root)
    changes.extend(symlink_changes)
    notes.extend(symlink_notes)

    # git: a repository to branch worktrees from, when the project root is not one already.
    if git and not _is_repository(project):
        enclosing = _enclosing_repository(project)
        if enclosing is not None:
            notes.append("%s lies inside the repository %s; the project gets its own" % (project.name, enclosing))
        _git_init(project)
        mark(".git/")

    entry, _ = register(project, pinned_tag)
    previous = read_active()
    displaced = str(previous) if previous is not None and previous.resolve() != project else None
    set_active(project)
    return {"project": str(project), "entry": entry, "changes": changes, "created": created, "displaced": displaced, "notes": notes}


def _template(harness_root, relative):
    return (harness_root / "templates" / "project" / relative).read_text(encoding="utf-8")


def _block(harness_root, harness_tag):
    body = Template(_template(harness_root, CLAUDE_MD)).safe_substitute(harness_tag=harness_tag)
    return "%s\n%s%s\n" % (BLOCK_BEGIN, body if body.endswith("\n") else body + "\n", BLOCK_END)


def _write_claude_block(project, harness_root, harness_tag):
    """Append the wayline block to CLAUDE.md, or refresh it in place; never overwrite the file.

    A begin marker with no end marker is a block a crash cut short: everything from it to the end
    of the file is that half-written block and is replaced, so one run repairs the file instead of
    appending a second copy next to the ruin. Returns whether the file changed, and a note when it
    repaired something.
    """
    path = project / CLAUDE_MD
    block = _block(harness_root, harness_tag)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(BLOCK_BEGIN)
    end = existing.find(BLOCK_END, start + len(BLOCK_BEGIN)) if start != -1 else -1
    note = None
    if start != -1 and end > start:
        current = existing[start:end + len(BLOCK_END)] + "\n"
        if current == block:
            return False, None
        text = existing[:start] + block + existing[end + len(BLOCK_END):].lstrip("\n")
    elif start != -1:
        note = "%s carried a wayline block with no closing marker; it was rewritten" % CLAUDE_MD
        text = existing[:start] + block
    elif existing.strip():
        text = existing if existing.endswith("\n") else existing + "\n"
        text = text + "\n" + block
    else:
        text = block
    atomic_write(path, text)
    return True, note


def _write_gitignore(project):
    """Add the missing entries of Implementation Decisions 1 under the `# wayline` header.

    An entry an owner deleted comes back under the header it belongs to, not at the end of the
    file under whatever section happens to be last.
    """
    path = project / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    present = {line.strip() for line in lines}
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in present]
    if not missing:
        return False
    if GITIGNORE_HEADER in present:
        where = [line.strip() for line in lines].index(GITIGNORE_HEADER) + 1
        lines[where:where] = missing
        text = "".join(line + "\n" for line in lines)
    else:
        text = existing
        if text and not text.endswith("\n"):
            text += "\n"
        text += ("\n" if text else "") + GITIGNORE_HEADER + "\n"
        text += "".join(entry + "\n" for entry in missing)
    atomic_write(path, text)
    return True


def _write_research(project, harness_root, harness_tag):
    """The `research/` skeleton: the directories, the templates, and the empty ledger files."""
    ledger = Ledger(project)
    changes = []
    with ledger.lock():
        for name in RESEARCH_DIRS:
            directory = project / RESEARCH / name
            if not directory.exists():
                directory.mkdir(parents=True)
                changes.append("%s/%s/" % (RESEARCH, name))
        for relative in _template_files(harness_root):
            target = project / RESEARCH / relative
            if target.exists():
                continue
            ledger.write_markdown(str(relative), Template(_template(harness_root, Path(RESEARCH) / relative)).safe_substitute(harness_tag=harness_tag))
            changes.append("%s/%s" % (RESEARCH, relative))
        for name in (JOURNAL, FINDINGS):
            if not (project / RESEARCH / name).exists():
                ledger.touch(name)
                changes.append("%s/%s" % (RESEARCH, name))
        if not (project / RESEARCH / MANIFEST).exists():
            ledger.write_json(MANIFEST, {"entries": []}, schema="manifest")
            changes.append("%s/%s" % (RESEARCH, MANIFEST))
        if not (project / RESEARCH / GRAPH).exists():
            ledger.write_json(GRAPH, empty_graph())
            changes.append("%s/%s" % (RESEARCH, GRAPH))
    return changes


def _template_files(harness_root):
    """The files under `templates/project/research/`, relative to it."""
    root = harness_root / "templates" / "project" / RESEARCH
    if not root.is_dir():
        return []
    return sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())


def refresh_symlinks(project, harness_root=None):
    """Relink every harness skill and workflow script into the project's `.claude/`.

    One refresher, used by `init` and later by `upgrade`: a symlink that points somewhere else (an
    upgrade moved the harness) is replaced; a symlink into this harness whose target is gone is
    removed; a real directory or file (a local skill, a local role override) is left alone and
    reported. Returns `(changes, notes)`, both relative to the project.
    """
    project = Path(project)
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    changes, notes = [], []
    for name in ("skills", "workflows", "agents"):
        directory = project / ".claude" / name
        if not directory.exists():
            directory.mkdir(parents=True)
            changes.append(".claude/%s/" % name)
    for kind, sources in (("skills", _harness_skills(harness_root)), ("workflows", _harness_workflows(harness_root))):
        directory = project / ".claude" / kind
        wanted = {source.name: source for source in sources}
        for name, source in sorted(wanted.items()):
            link = directory / name
            if link.is_symlink():
                if os.readlink(link) == str(source):
                    continue
                link.unlink()
            elif link.exists():
                notes.append(".claude/%s/%s is not a symlink; left alone" % (kind, name))
                continue
            link.symlink_to(source)
            changes.append(".claude/%s/%s" % (kind, name))
        for link in sorted(directory.iterdir()) if directory.is_dir() else []:
            if link.name in wanted or not link.is_symlink():
                continue
            target = Path(os.readlink(link))
            if _under(target, harness_root) and not target.exists():
                link.unlink()
                changes.append("removed .claude/%s/%s" % (kind, link.name))
    return changes, notes


def _under(path, root):
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):  # pragma: no cover - a symlink loop
        return False


def _harness_skills(harness_root):
    directory = harness_root / "skills"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_dir() and not path.name.startswith("."))


def _harness_workflows(harness_root):
    directory = harness_root / "workflows"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and not path.name.startswith("."))


# --- git -----------------------------------------------------------------------------------------


def _git(project, *args, check_exit=True):
    done = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    if check_exit and done.returncode != 0:
        raise ProjectError("git %s failed in %s: %s" % (" ".join(args), project, (done.stderr or done.stdout).strip()))
    return done


def _toplevel(project):
    """The root of the work tree `project` lies in, or None when it lies in none."""
    done = _git(project, "rev-parse", "--show-toplevel", check_exit=False)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return Path(done.stdout.strip()).resolve()


def _is_repository(project):
    """Whether the project directory is itself the root of a work tree.

    A directory that merely lies inside someone else's repository is not one: the conductor's
    worktrees branch from the project's own `main`, so a nested project needs its own repository
    rather than the enclosing one's history.
    """
    return _toplevel(project) == Path(project).resolve()


def _enclosing_repository(project):
    """The repository `project` lies inside, when it is not its own; None otherwise."""
    top = _toplevel(project)
    return None if top is None or top == Path(project).resolve() else top


def _git_init(project):
    """A fresh repository on `main`, with one commit; worktrees branch from `main`."""
    done = _git(project, "init", "-b", "main", check_exit=False)
    if done.returncode != 0:
        _git(project, "init")
        _git(project, "symbolic-ref", "HEAD", "refs/heads/main")
    identity = []
    if not _git(project, "config", "user.email", check_exit=False).stdout.strip():
        identity = ["-c", "user.name=wayline", "-c", "user.email=wayline@localhost"]
    _git(project, "add", "-A")
    _git(project, *identity, "commit", "-m", "wayline: init")


# --- status ---------------------------------------------------------------------------------------


def status_view(project, refresh=True):
    """Everything `status` prints, as a structure the dashboard can render instead.

    A ledger that cannot be read never raises here: what failed lands in `problems`, and the rest
    of the view is still built, because a view that refuses to print is worse than a partial one.

    `refresh=False` computes the graph without writing it, which is what the dashboard passes: its
    views are polled every few seconds and are read-only in M1.
    """
    project = Path(project).resolve()
    harness = read_harness(project)
    ledger = Ledger(project)
    problems = []
    try:
        events, offset = ledger.read_events()
    except OSError as failure:
        events, offset = [], 0
        problems.append("journal: %s" % failure)

    tickets, graph, regenerated = {}, None, False
    try:
        tickets = {fields["id"]: fields for fields in read_tickets(project)}
    except (ValueError, OSError) as failure:
        problems.append("tickets: %s" % failure)
    try:
        graph, regenerated = refresh_graph(project, ledger=ledger, events=events, write=refresh)
    except (ValueError, OSError) as failure:
        # A ticket file a human broke must not blank the view: the last good graph still prints.
        problems.append("graph.json: %s" % failure)
        graph = read_graph(project)
    if graph is None:
        graph = empty_graph()

    jobs, job_problems = read_jobs(project)
    problems.extend(job_problems)
    live_jobs = [job for job in jobs if job["status"] in LIVE_JOB_STATUSES]
    resources, resource_problem = _resources_view(project, harness, live_jobs)
    if resource_problem:
        problems.append(resource_problem)
    active = read_active()
    return {
        "project": str(project),
        "name": project.name,
        "active": active is not None and active.resolve() == project,
        "harness_tag": harness.get("harness_tag"),
        "autonomy": harness.get("autonomy"),
        "radius": harness.get("radius"),
        "frontier": [_ticket_line(entry, tickets) for entry in frontier(graph)],
        "running": [_ticket_line(entry, tickets) for entry in _with_status(graph, "running")],
        "jobs": live_jobs,
        "decisions": [_ticket_line(entry, tickets) for entry in _open_decisions(graph)],
        "counts": {status: len(ids) for status, ids in by_status(graph).items()},
        "window": window_status(events, harness),
        "goal": goal_progress(project, events),
        "resources": resources,
        "events": events[-10:],
        "offset": offset,
        "graph_regenerated": regenerated,
        "problems": problems,
    }


def _resources_view(project, harness, live_jobs):
    """The machine's slots and reservation for `status`; a reading the box cannot produce is a problem, not a crash."""
    policy = policy_for(project).get("jobs", {})
    try:
        return resources_snapshot(
            harness, live_jobs,
            gpu_util_free_below=policy.get("gpu_util_free_below", 20),
            gpu_util_samples=policy.get("gpu_util_samples", 2),
        ), None
    except (ResourceError, OSError) as failure:
        return None, "resources: %s" % failure


def _with_status(graph, status):
    return [entry for entry in graph["tickets"] if entry["status"] == status]


def _open_decisions(graph):
    """The decision tickets `status` lists: the same ones the frontier is paused by (`tickets`)."""
    return open_decisions(graph)


def _ticket_line(entry, tickets):
    """One ticket as `status` shows it: the scheduling fields plus the title from the ticket file."""
    fields = tickets.get(entry["id"], {})
    line = dict(entry)
    line["title"] = fields.get("title", "")
    line["demo"] = fields.get("demo")
    return line


def read_jobs(project):
    """Every `research/jobs/<id>.json`, validated; unreadable files become problems, not failures."""
    directory = Path(project) / RESEARCH / JOBS
    jobs, problems = [], []
    if not directory.is_dir():
        return jobs, problems
    schema = load_schema("job")
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            check(value, schema, name=str(path))
        except (OSError, ValueError) as failure:
            problems.append("jobs: %s" % failure)
            continue
        jobs.append(value)
    return jobs, problems


def window_status(events, harness=None):
    """The usage windows as the journal last saw them: the pacing reading and whether a run is paused.

    The fold is the conductor's own (`replay.View`), so `status` and a conductor never disagree
    about a pause: it lasts until `unpaused`, whatever restarts come in between.
    """
    harness = harness or {}
    pacing = harness.get("pacing", {})
    view = replay.replay(events)
    pause = view.pause or {}
    return {
        "action": view.pacing["action"],
        "five_hour": view.pacing["five_hour"],
        "seven_day": view.pacing["seven_day"],
        "paused": view.pause is not None,
        "resets_at": pause.get("resets_at"),
        "window": pause.get("window"),
        "utilization": pause.get("utilization"),
        "stop_at": pacing.get("stop_at"),
        "cheap_at": pacing.get("cheap_at"),
    }


def goal_progress(project, events):
    """The goal and the progress readings the journal holds for its metric, or None when there is no goal.

    `GOAL.json` is written by the intake phase; this reads it tolerantly, because a goal the owner
    edited by hand should still print.
    """
    path = Path(project) / RESEARCH / GOAL_JSON
    try:
        goal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(goal, dict):
        return None
    metric = goal.get("metric")
    direction = goal.get("direction")
    target = goal.get("target")
    readings = [event.get("payload") or {} for event in events if event.get("event") == "progress"]
    readings = [payload for payload in readings if metric is None or payload.get("metric") == metric]
    kept = [payload for payload in readings if payload.get("kept")]
    latest = (kept or readings)[-1] if (kept or readings) else None
    value = latest.get("value") if latest else None
    reached = None
    if isinstance(value, (int, float)) and isinstance(target, (int, float)) and direction in ("up", "down"):
        reached = value >= target if direction == "up" else value <= target
    return {
        "metric": metric,
        "direction": direction,
        "target": target,
        "value": value,
        "readings": len(readings),
        "kept": len(kept),
        "reached": reached,
        "stop_when": goal.get("stop_when"),
    }


# --- rendering --------------------------------------------------------------------------------------


def render_status(view):
    """The text `wayline status` prints."""
    lines = []
    head = "project  %s  (%s)" % (view["name"], view["project"])
    lines.append(head + ("  [active]" if view["active"] else ""))
    lines.append("harness  %s   autonomy %s   radius %s" % (view["harness_tag"], view["autonomy"], view["radius"]))
    lines.append("")
    lines.extend(_render_tickets("frontier", view["frontier"]))
    lines.extend(_render_tickets("running tickets", view["running"]))
    lines.extend(_render_jobs(view["jobs"]))
    lines.extend(_render_decisions(view["decisions"]))
    lines.append(_render_window(view["window"]))
    lines.append(_render_goal(view["goal"]))
    if view.get("resources") is not None:
        lines.extend(render_resources(view["resources"]))
    lines.append("")
    counts = "   ".join("%s %d" % (status, count) for status, count in view["counts"].items() if count)
    lines.append("tickets  " + (counts or "none"))
    lines.append("")
    lines.append(_events_heading(len(view["events"])))
    for event in view["events"]:
        lines.append("  " + _render_event(event))
    if view["problems"]:
        lines.append("")
        lines.append("problems (%d)" % len(view["problems"]))
        for problem in view["problems"]:
            lines.append("  " + problem)
    # The column padding above is how the eye finds a field; it must not survive to the end of a
    # line, where it is only invisible noise in a terminal, a diff, and a copied paste.
    return "\n".join(line.rstrip() for line in lines)


def _events_heading(count):
    if not count:
        return "last events  none"
    return "last %d event%s" % (count, "" if count == 1 else "s")


def _render_tickets(heading, entries):
    lines = ["%s (%d)" % (heading, len(entries))]
    for entry in entries:
        note = "  attempt %d" % entry["attempt"] if entry.get("attempt") else ""
        lines.append("  #%-3d %-10s d%d  %-14s %s%s" % (entry["id"], entry["kind"], entry["difficulty"], entry["role"], entry["title"], note))
    lines.append("")
    return lines


def _render_jobs(jobs):
    lines = ["running jobs (%d)" % len(jobs)]
    for job in jobs:
        lines.append("  %-12s ticket %-4d %-8s %s" % (job["id"], job["ticket"], job["status"], job.get("unit") or job["backend"]))
    lines.append("")
    return lines


def _render_decisions(decisions):
    lines = ["open decision tickets (%d)" % len(decisions)]
    for entry in decisions:
        marks = [mark for mark in ("human_only" if entry.get("human_only") else "", "blocking %s" % entry["blocking"] if entry.get("blocking") else "") if mark]
        lines.append("  #%-3d %s%s" % (entry["id"], entry["title"], ("  (%s)" % ", ".join(marks)) if marks else ""))
    lines.append("")
    return lines


def _render_window(window):
    parts = ["window   %s" % ("paused" if window["paused"] else window["action"])]
    if window["paused"]:
        parts.append("%s until %s" % (window["window"] or "unknown", window["resets_at"] or "unknown"))
    for key in ("five_hour", "seven_day"):
        if window[key] is not None:
            parts.append("%s %s" % (key, _number(window[key])))
    return "   ".join(parts)


def _render_goal(goal):
    if goal is None:
        return "goal     none set"
    if goal["value"] is None:
        return "goal     %s (%s), target %s, no reading yet" % (goal["metric"], goal["direction"], _number(goal["target"]))
    reached = "" if goal["reached"] is None else ("  reached" if goal["reached"] else "")
    readings = "%d reading%s" % (goal["readings"], "" if goal["readings"] == 1 else "s")
    return "goal     %s %s of %s (%s)   %s, %d kept%s" % (
        goal["metric"], _number(goal["value"]), _number(goal["target"]), goal["direction"], readings, goal["kept"], reached,
    )


def _number(value):
    if isinstance(value, float):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value)


def _render_event(event):
    payload = event.get("payload") or {}
    ticket = "#%s" % event["ticket"] if event.get("ticket") is not None else ""
    interesting = [(key, value) for key, value in payload.items() if key != "ticket" and value not in (None, [], {}, "")]
    detail = " ".join("%s=%s" % (key, _short(value)) for key, value in interesting[:3])
    return "%-24s %-16s %-5s %s" % (event.get("ts", ""), event.get("event", ""), ticket, detail)


def _short(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value[:3]) + ("..." if len(value) > 3 else "")
    if isinstance(value, dict):
        return "{%d keys}" % len(value)
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


# --- switch -------------------------------------------------------------------------------------------


def switch_project(path, by="cli", wait=None):
    """Point the machine at another project, journalling `switched` in both (decision 1).

    A conductor running on the project being left is asked to drain first: `control stop` with
    `drain` and the project switched to. It launches nothing new, waits for its running workers,
    and ends with `run_ended switched`, leaving its jobs to finish on their own. `wait(project)`
    blocks until it has ended (`wait_for_conductor` by default), and only then is `switched`
    journaled and the pointer moved, so one project never has a conductor draining while the next
    one's starts. `drained` in the report is that conductor's heartbeat, or None when none was
    running. `by` is who asked: `cli`, or `dashboard` for its switch action.
    """
    target = Path(path).expanduser().resolve()
    if not is_project(target):
        raise ProjectError("%s is not a wayline project (no %s); run wayline init %s" % (target, HARNESS_JSON, target))
    previous = read_active()
    previous = previous.resolve() if previous is not None else None
    if previous == target:
        return {"from": None if previous is None else str(previous), "to": str(target), "moved": False, "drained": None}
    payload = {"from": str(previous) if previous else None, "to": str(target)}
    drained = None
    if previous is not None and is_project(previous):
        drained = conductor_holder(previous)
        if drained is not None:
            control(previous, "stop", {"drain": True, "switch_to": str(target)}, by=by)
            (wait or wait_for_conductor)(previous)
        Ledger(previous).append_event(SWITCHED, payload)
    Ledger(target).append_event(SWITCHED, payload)
    register(target, read_harness(target).get("harness_tag", TAG))
    set_active(target)
    return {"from": payload["from"], "to": payload["to"], "moved": True, "drained": drained}


# How often `switch` looks whether the conductor it asked to drain has ended, in seconds.
DRAIN_POLL_S = 2


def wait_for_conductor(project):
    """Block until no conductor holds `project`'s heartbeat, which is when the drained run has ended.

    The drain lasts as long as the conductor's running workers do. A conductor that is killed lets
    go of its lock as it dies, so this never waits on a dead one.
    """
    while conductor_holder(project) is not None:
        time.sleep(DRAIN_POLL_S)


# --- autonomy ---------------------------------------------------------------------------------------------


def set_autonomy(project, autonomy, by="cli"):
    """`wayline switch --autonomy`: write the setting to `harness.json` and journal `control autonomy`.

    Raising is allowed at any moment, from the command line, the grill, or the dashboard: a running
    conductor applies the event at its next wave, and `harness.json` is what the next run starts
    from. Lowering is allowed only while no conductor holds the project, because an autonomous run
    is not to be lowered by a passing remark in the middle of it (BRIEF 6.2); with one running it is
    refused and nothing is written. `harness.json` is written before the event is journaled, so a
    crash between the two leaves a run that starts from the new setting rather than a journal the
    next `run_started` contradicts. `by` is `cli`, or `dashboard` for its autonomy action.

    While a conductor runs, the autonomy it holds is the journal's (`run_started` and the `control`
    events after it), which a hand edit of `harness.json` does not change. A change is measured
    against both, so an edited file cannot pass a lowering off as a raise, and a run the file already
    names the new setting for is still raised.

    Returns `{from, to, changed, conductor}`, `conductor` being the running conductor's heartbeat.
    """
    project = Path(project).resolve()
    levels = list(AUTONOMY)
    if autonomy not in levels:
        raise ProjectError("autonomy is one of %s, got %r" % (", ".join(levels), autonomy))
    ledger = Ledger(project)
    with ledger.lock():
        harness = read_harness(project)
        written = harness["autonomy"]
        holder = conductor_holder(project)
        held = [written]
        if holder is not None:
            events, _ = ledger.read_events()
            running = replay.replay(events).autonomy
            if running in levels:
                held.append(running)
        report = {"from": held[-1], "to": autonomy, "changed": any(level != autonomy for level in held), "conductor": holder}
        if not report["changed"]:
            return report
        if holder is not None and any(levels.index(autonomy) < levels.index(level) for level in held):
            raise ProjectError(
                "autonomy is lowered only while no conductor is running, and the conductor (pid %s) is running on %s at %s; "
                "wayline stop --project %s, then wayline switch --autonomy %s once it has ended"
                % (holder.get("pid", "?"), project, max(held, key=levels.index), project, autonomy))
        if written != autonomy:
            updated = dict(harness, autonomy=autonomy)
            check(updated, load_schema("harness"), name=HARNESS_JSON)
            atomic_write(project / HARNESS_JSON, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
        control(project, "autonomy", {"autonomy": autonomy}, by=by)
    return report


# --- steering a running conductor ------------------------------------------------------------------------


def control(project, command, args=None, by="cli"):
    """Journal one `control` event for the conductor to apply at its next wave (decision 1).

    The verbs `pause`, `resume`, `stop [--drain]`, `cancel <id>`, and `rerun <id>` are this, and so
    is `switch` asking a running conductor to drain: the journal is the bus, and the conductor is the
    one process that acts on what it carries. `by` is `cli`, or `dashboard` for its actions.
    """
    args = dict(args or {})
    ticket = args.get("ticket")
    return Ledger(Path(project).resolve()).append_event(
        CONTROL, {"command": command, "args": args, "by": by},
        ticket=ticket if isinstance(ticket, int) and not isinstance(ticket, bool) else None)


def answer(project, identifier, text):
    """Answer a decision ticket: `## Answer` in its file, and `decision` with `decided_by: human` (decision 5).

    The conductor closes the ticket at its next wave. A ticket that is not an open decision ticket
    is refused, and so is one already answered; `wayline rerun` asks a decision ticket's question again.
    """
    project = Path(project).resolve()
    ledger = Ledger(project)
    found = {ticket["id"]: ticket for ticket in read_tickets(project)}.get(identifier)
    if found is None:
        raise ProjectError("%s has no ticket %s" % (project, identifier))
    if found["kind"] != DECISION_KIND:
        raise ProjectError("ticket %d is a %s ticket, and only a decision ticket takes an answer" % (identifier, found["kind"]))
    if found["status"] in SATISFIED + ("parked",):
        raise ProjectError("ticket %d is %s; wayline rerun %d asks its question again" % (identifier, found["status"], identifier))
    fields, body = read_ticket(tickets_dir(project) / filename(found))
    events, _ = ledger.read_events()
    if identifier in replay.replay(events).answers or answer_section(body):
        raise ProjectError("ticket %d is answered already; the conductor closes it at its next wave" % identifier)
    text = str(text).strip()
    if not text:
        raise ProjectError("an answer needs some text")
    write_ticket(ledger, fields, with_answer(body, text))
    return ledger.append_event(DECISION, {"ticket": identifier, "answer": text, "decided_by": "human",
                                          "rationale": None, "confidence": None}, ticket=identifier)


# --- the verbs ------------------------------------------------------------------------------------------





def ask_email(given, path, stream=None):
    """The address `init` stores: the flag, else the owner's answer at a terminal, else git's.

    Away from a terminal (the suite, the tick, a script) nothing is asked and git's address
    stands, so `init` stays the non-interactive command every other caller relies on.
    """
    if given:
        return given
    suggestion = detect_email(path if Path(path).is_dir() else None)
    stream = stream if stream is not None else sys.stdin
    if not (hasattr(stream, "isatty") and stream.isatty()):
        return suggestion
    print("owner address for the polite pools (Crossref, Unpaywall)%s: " % (" [%s]" % suggestion if suggestion else ""), end="", flush=True)
    try:
        answer = (stream.readline() or "").strip()
    except (OSError, ValueError, KeyboardInterrupt):
        answer = ""
    return answer or suggestion


def init_command(args):
    parser = argparse.ArgumentParser(prog="wayline init", description="lay out a project, register it, make it active")
    parser.add_argument("path", help="the project directory; it is created when it does not exist")
    parser.add_argument("--no-git", action="store_true", help="do not run git init even when the directory is not a repository")
    parser.add_argument("--email", help="the owner address the scout sends to the polite pools; git's is offered when this is omitted")
    parser.add_argument("--uninstall-units", action="store_true", help="remove the user units (ticket 14 installs them)")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.uninstall_units:
        print("wayline init: --uninstall-units needs the user units, which ticket 14 (the tick) installs", file=sys.stderr)
        return 2
    try:
        report = init_project(options.path, git=not options.no_git, owner_email=ask_email(options.email, options.path))
    except (ProjectError, ValidationError, OSError) as failure:
        print("wayline init: %s" % failure, file=sys.stderr)
        return 1
    print("project  %s" % report["project"])
    if report["changes"]:
        for change in report["changes"]:
            print("  wrote %s" % change)
    else:
        print("  nothing to do; the project is already laid out")
    for note in report["notes"]:
        print("  note  %s" % note)
    if report["displaced"]:
        print("  active project moved from %s; wayline switch %s goes back" % (report["displaced"], report["displaced"]))
    return 0


def status_command(args):
    parser = argparse.ArgumentParser(prog="wayline status", description="print the frontier, the running work, the window, the goal, and the last events")
    parser.add_argument("--project", help="the project to read; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the view as JSON instead of text")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        view = status_view(find_project(options.project))
    except (ProjectError, ValidationError, OSError) as failure:
        print("wayline status: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(view, ensure_ascii=False, indent=2) if options.json else render_status(view))
    return 1 if view["problems"] else 0


def switch_command(args):
    parser = argparse.ArgumentParser(
        prog="wayline switch",
        description="make another project the active one; with --autonomy instead, raise the project's autonomy, "
                    "or lower it while no conductor is running")
    parser.add_argument("path", nargs="?", help="the project to switch to")
    parser.add_argument("--autonomy", choices=list(AUTONOMY), help="the autonomy to set on the project, instead of switching")
    parser.add_argument("--project", help="with --autonomy, the project to set; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.autonomy is not None:
        if options.path is not None:
            print("wayline switch: give a project to switch to or --autonomy, not both (--project names the project --autonomy sets)",
                  file=sys.stderr)
            return 2
        return _switch_autonomy(options)
    if options.path is None or options.project is not None:
        parser.print_usage(sys.stderr)
        print("wayline switch: give the project to switch to, or --autonomy <level> (with --project for another project)", file=sys.stderr)
        return 2
    try:
        previous = read_active()
        if previous is not None and is_project(previous) and previous.resolve() != Path(options.path).expanduser().resolve():
            holder = conductor_holder(previous)
            if holder is not None:
                print("draining the conductor (pid %s) on %s: it launches nothing new and ends once its running workers return"
                      % (holder.get("pid", "?"), previous.resolve()), flush=True)
        moved = switch_project(options.path)
    except (ProjectError, ValidationError, OSError) as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 1
    if not moved["moved"]:
        print("already active: %s" % moved["to"])
    else:
        print("active project  %s" % moved["to"])
        if moved["from"]:
            print("  was  %s" % moved["from"])
        if moved["drained"] is not None:
            print("  its conductor (pid %s) drained and ended" % moved["drained"].get("pid", "?"))
    return 0


def _switch_autonomy(options):
    try:
        project = find_project(options.project)
        report = set_autonomy(project, options.autonomy)
    except (ProjectError, ValidationError, OSError) as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 1
    if not report["changed"]:
        print("autonomy is already %s on %s" % (report["to"], project))
        return 0
    levels = list(AUTONOMY)
    direction = "raised" if levels.index(report["to"]) > levels.index(report["from"]) else "lowered"
    print("autonomy %s from %s to %s on %s" % (direction, report["from"], report["to"], project))
    print("  %s: %s" % (report["to"], AUTONOMY[report["to"]]))
    if report["conductor"] is not None:
        print("  journaled for the conductor (pid %s) to apply at its next wave" % report["conductor"].get("pid", "?"))
    else:
        print("  no conductor is running; the next run starts %s" % report["to"])
    return 0


def _verb_parser(verb, description):
    parser = argparse.ArgumentParser(prog="wayline %s" % verb, description=description)
    parser.add_argument("--project", help="the project to steer; the active one by default")
    return parser


def _project_for(verb, options):
    """The project a verb steers, or None after saying why there is none."""
    try:
        return find_project(options.project)
    except (ProjectError, OSError) as failure:
        print("wayline %s: %s" % (verb, failure), file=sys.stderr)
        return None


def pause_command(args):
    """`wayline pause`: nothing that needs a model launches until `wayline resume`."""
    return _steer("pause", args, "pause the run: nothing that needs a model launches until wayline resume")


def resume_command(args):
    """`wayline resume`: the paused run launches again."""
    return _steer("resume", args, "resume a paused run")


def _steer(command, args, description):
    options, code = parse_args(_verb_parser(command, description), args)
    if options is None:
        return code
    project = _project_for(command, options)
    if project is None:
        return 1
    control(project, command)
    running = conductor_holder(project) is not None
    print("%s journaled for %s%s" % (command, project, "" if running else "; no conductor is running, and the next run takes it in"))
    return 0


def stop_command(args):
    """`wayline stop [--drain]`: the running conductor ends at its next wave, or with --drain once its workers return."""
    parser = _verb_parser("stop", "end the run at its next wave, leaving its running workers to finish; "
                                  "with --drain, launch nothing new and end once they have returned")
    parser.add_argument("--drain", action="store_true", help="launch nothing new and end once the running workers return")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    project = _project_for("stop", options)
    if project is None:
        return 1
    control(project, "stop", {"drain": bool(options.drain)})
    holder = conductor_holder(project)
    if holder is None:
        print("stop journaled for %s; no conductor is running, and a run started later is not stopped by it" % project)
    elif options.drain:
        print("asked the conductor (pid %s) on %s to stop once its running workers return" % (holder.get("pid", "?"), project))
    else:
        print("asked the conductor (pid %s) on %s to stop at its next wave; its running workers finish on their own "
              "and the next run re-adopts them" % (holder.get("pid", "?"), project))
    return 0


def cancel_command(args):
    """`wayline cancel <id>`: the ticket's worker is ended and the ticket is parked."""
    return _ticket_verb("cancel", args, "cancel a ticket: its worker is ended and the ticket is parked")


def rerun_command(args):
    """`wayline rerun <id>`: the ticket's worker is ended and the ticket opens for a new attempt."""
    return _ticket_verb("rerun", args, "rerun a ticket: its worker is ended and the ticket opens for a new attempt")


def _ticket_verb(command, args, description):
    parser = _verb_parser(command, description)
    parser.add_argument("id", type=int, help="the ticket")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    project = _project_for(command, options)
    if project is None:
        return 1
    try:
        known = {ticket["id"] for ticket in read_tickets(project)}
    except (ValueError, OSError) as failure:
        print("wayline %s: %s" % (command, failure), file=sys.stderr)
        return 1
    if options.id not in known:
        print("wayline %s: %s has no ticket %d" % (command, project, options.id), file=sys.stderr)
        return 1
    control(project, command, {"ticket": options.id})
    print("%s of ticket %d journaled for %s" % (command, options.id, project))
    return 0


def answer_command(args):
    """`wayline answer <id> "<text>"`."""
    parser = _verb_parser("answer", "answer a decision ticket")
    parser.add_argument("id", type=int, help="the decision ticket")
    parser.add_argument("text", help="the answer")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    project = _project_for("answer", options)
    if project is None:
        return 1
    try:
        answer(project, options.id, options.text)
    except (ProjectError, ValueError, OSError) as failure:
        print("wayline answer: %s" % failure, file=sys.stderr)
        return 1
    print("ticket %d answered; the conductor closes it at its next wave" % options.id)
    return 0
