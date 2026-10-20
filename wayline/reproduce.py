"""Reproducing from the code repository (Implementation Decision 17, ticket 106).

"Aligned" means the code repository at the paper's tag recomputes every number and figure the paper prints.
This module makes that checkable. Every job and ticket run records the commit of `main` it ran at (ticket 85);
from those records code renders into `code/`:

- `code/REPRODUCE.md` and `code/reproduce.json`: per result, each run its current findings cite, with its
  command, its commit of `main`, its inputs, outputs, wall-clock time, and hardware (the GPUs it held);
- `code/locks/`: the environment locks as they stood at the commit the cited runs ran at (the project's
  `.venv` lock, `renv.lock`, the Julia environment, the Octave packages), read from git and not from what is
  installed now, and `code/locks/tools.json`, every tool a cited job called with the version and lock digest
  its job record carries;
- `code/README.md`, rendered from the records, keeping word for word the owner's part between
  `OWNER_BEGIN` and `OWNER_END`. A README with no markers (an absorbed clone's) is kept whole as that part.

A result, until the Results headings group them, is the findings of one ticket. A finding another replaces
(its `replaces`, as `sections.file_finding` records it) is no longer current, so the runs it cited drop out.

The code repository never holds `research/`, `jobs/`, or `results/`, so no rendered file names a path under
them: a path under `code/` is given relative to `code/`, and any other path by its file name alone, an output
with its SHA-256 and size.

`render_if_changed` is what the conductor calls after a wave: it renders only when `code/` changed or the cited
runs did (a job a finding cites ran, or the findings cite other runs), and returns the paths it wrote for the
wave's commit; the next push of the code repository carries them.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from wayline import provenance, software
from wayline.ledger import JOB_FINISHED, JOB_LAUNCHED, TICKET_LAUNCHED, TICKET_RESULT, Ledger, atomic_bytes, atomic_write

__all__ = [
    "OWNER_BEGIN", "OWNER_END", "REPRODUCE_MD", "REPRODUCE_JSON", "README", "LOCKS_DIR", "LOCK_FILES",
    "runs_by_result", "render", "render_if_changed",
]

CODE = "code"
REPRODUCE_MD = "REPRODUCE.md"
REPRODUCE_JSON = "reproduce.json"
README = "README.md"
LOCKS_DIR = "locks"
TOOLS_LOCK = "tools.json"
# The package locks ticket 82 writes under `code/`, by language, and the Julia project file beside its manifest.
LOCK_FILES = tuple(software.LOCKS.values()) + ("Project.toml",)
RENDERED = (REPRODUCE_MD, REPRODUCE_JSON, README, LOCKS_DIR)
OWNER_BEGIN = "<!-- wayline:owner -->"
OWNER_END = "<!-- /wayline:owner -->"
_HIDDEN = ("research", "jobs", "results")
# Whatever is left of a path into a directory the code repository does not hold, inside any text: kept as its file name.
_HIDDEN_PATH = re.compile(r"(?:[^\s'\"=:(]*/)?(?:research|jobs|results)/(?:[^\s'\")]*/)?([^\s'\")/]*)")


def _git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True)


# --- naming paths the code repository holds ---------------------------------------------------------------------


def _public_path(text, project):
    """A path as the code repository can name it: relative to `code/` under it, else the file name alone."""
    path = Path(text)
    root = Path(project).resolve()
    if text == str(root):
        return "."
    if path.is_absolute():
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            return text  # outside the project: an interpreter, a system file
    else:
        relative = path
    parts = relative.parts
    if parts and parts[0] == CODE and len(parts) > 1:
        return Path(*parts[1:]).as_posix()
    if path.is_absolute() or (parts and parts[0] in _HIDDEN):
        return relative.name
    return text


def _public_token(token, project):
    key, sep, value = token.partition("=")
    if sep and key.startswith("-"):
        named = key + "=" + _public_path(value, project)
    else:
        named = _public_path(token, project)
    return _scrub(named, project)


def _scrub(text, project):
    """Any path left in `text` into the project or a directory the code repository does not hold, by file name."""
    root = str(Path(project).resolve())
    text = text.replace(root + "/" + CODE + "/", "").replace(root + "/", "").replace(root, ".")
    return _HIDDEN_PATH.sub(lambda match: match.group(1), text)


def _public_command(text, project):
    """A shell line a session ran, its project paths named as the code repository can."""
    return " ".join(_public_token(token, project) for token in text.split(" "))


def _is_file(token, cwd, project):
    _key, sep, value = token.partition("=")
    candidate = Path(value if sep and token.startswith("-") else token)
    if not candidate.is_absolute():
        candidate = Path(cwd or project) / candidate
    try:
        return candidate.is_file() and candidate.resolve().is_relative_to(Path(project).resolve())
    except OSError:
        return False


# --- the records ------------------------------------------------------------------------------------------------


def _events(project):
    return Ledger(project).read_events()[0]


def _launches(events):
    """The latest `job_launched` per job, `job_finished` per job, `ticket_launched` and `ticket_result` per run id."""
    jobs, finished, tickets, durations = {}, {}, {}, {}
    for event in events:
        kind, payload = event.get("event"), event.get("payload") or {}
        if kind == JOB_LAUNCHED and event.get("job"):
            jobs[event["job"]] = payload
        elif kind == JOB_FINISHED and event.get("job"):
            finished[event["job"]] = payload
        elif kind in (TICKET_LAUNCHED, TICKET_RESULT) and payload.get("attempt") is not None:
            run_id = "t%s-a%s" % (payload.get("ticket", event.get("ticket")), payload["attempt"])
            if kind == TICKET_LAUNCHED:
                tickets.setdefault(run_id, payload)  # the commit the attempt started at; a resume runs on
            elif isinstance(payload.get("duration_ms"), (int, float)):
                durations[run_id] = durations.get(run_id, 0) + payload["duration_ms"]  # every session of the attempt
    return jobs, finished, tickets, durations


def _cited_entries(finding, manifest):
    """The manifest entries a finding cites, leaving out a discarded change's (under `.worktrees/`), whose code `main` lacks."""
    by_path = {entry["path"]: entry for entry in manifest.get("entries", [])}
    paths = [locator.partition("#")[0] for locator in provenance._cited(finding)]
    return [by_path[path] for path in paths if path in by_path and not path.startswith(".worktrees/")]


def _outputs(project, manifest, run_id, job):
    outputs = []
    for entry in manifest.get("entries", []):
        if (job is not None and entry.get("job") == job) or (job is None and entry.get("job") is None and entry.get("run_id") == run_id):
            outputs.append({"name": _public_path(entry["path"], project), "sha256": entry["sha256"], "size": entry["size"]})
    return sorted(outputs, key=lambda output: output["name"])


def _session_commands(project, run_id):
    """The commands every session of the attempt ran: its first session's `result.json`, then each resume's."""
    match = re.match(r"^t(\d+)-a(\d+)$", run_id or "")
    if not match:
        return []
    attempt = Path(project) / "research" / "sessions" / match.group(1) / match.group(2)
    number = lambda path: int(path.parent.name.partition("-")[2]) if path.parent.name.partition("-")[2].isdigit() else 0
    commands = []
    for path in [attempt / "result.json"] + sorted(attempt.glob("resume-*/result.json"), key=number):
        try:
            returned = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(returned, dict):
            continue
        output = returned.get("structured_output") if isinstance(returned.get("structured_output"), dict) else returned
        commands += [_public_command(line, project) for line in output.get("commands_run") or [] if isinstance(line, str)]
    return commands


def _job_run(project, ledger, manifest, job, run_id, launched, finished):
    try:
        record = ledger.read_json("jobs/%s.json" % job)
    except (OSError, ValueError):
        record = {}
    devices = record.get("devices") or {}
    command = [str(part) for part in record.get("command") or []]
    outputs = _outputs(project, manifest, run_id, job)
    expected = {_public_path(path, project) for path in record.get("expected_outputs") or []}
    inputs = []
    for token in command[1:]:
        if _is_file(token, record.get("cwd"), project):
            name = _public_path(token.partition("=")[2] if token.startswith("-") and "=" in token else token, project)
            if name not in expected and name not in inputs and name not in {output["name"] for output in outputs}:
                inputs.append(name)
    seconds = (finished or {}).get("seconds")
    if seconds is None:
        attempts = record.get("attempts") or []
        seconds = _span(attempts[-1].get("started_at"), attempts[-1].get("ended_at")) if attempts else None
    tools = (launched or {}).get("tools") or record.get("tools") or []
    return {
        "run_id": run_id, "job": job, "commit": (launched or {}).get("commit"),
        "command": [_public_token(token, project) for token in command],
        "inputs": inputs, "outputs": outputs, "seconds": seconds,
        "hardware": {"gpu_uuids": list(devices.get("gpu_uuids") or []), "gpu_indices": list(devices.get("gpu_indices") or []),
                     "cores": list(devices.get("cores") or []), "ram_gb": devices.get("ram_gb")},
        "tools": [{"name": tool.get("name"), "version": tool.get("version"), "lock": tool.get("lock")} for tool in tools],
    }


def _ticket_run(project, manifest, run_id, launched, returned):
    duration = returned
    return {
        "run_id": run_id, "job": None, "commit": (launched or {}).get("commit"),
        "command": _session_commands(project, run_id),
        "inputs": [], "outputs": _outputs(project, manifest, run_id, None),
        "seconds": round(duration / 1000) if isinstance(duration, (int, float)) else None,
        "hardware": {"gpu_uuids": [], "gpu_indices": [], "cores": [], "ram_gb": None}, "tools": [],
    }


def _span(start, end):
    from datetime import datetime

    try:
        parse = lambda text: datetime.fromisoformat(text.replace("Z", "+00:00"))
        return round((parse(end) - parse(start)).total_seconds())
    except (AttributeError, TypeError, ValueError):
        return None


def runs_by_result(project):
    """Per result (the current findings of one ticket), the findings and every run they cite, in ticket order."""
    project = Path(project)
    ledger = Ledger(project)
    manifest = provenance.read_manifest(ledger)
    jobs, finished, tickets, durations = _launches(_events(project))
    results = {}
    for finding in provenance.current_findings(ledger):
        key = int(finding.get("ticket") or 0)
        result = results.setdefault(key, {"result": "ticket %d" % key, "findings": [], "texts": [], "runs": []})
        result["findings"].append(finding["id"])
        result["texts"].append(finding.get("text") or "")
        for entry in _cited_entries(finding, manifest):
            run_id, job = entry.get("run_id"), entry.get("job")
            if any(run["run_id"] == run_id and run["job"] == job for run in result["runs"]):
                continue
            if job:
                result["runs"].append(_job_run(project, ledger, manifest, job, run_id, jobs.get(job), finished.get(job)))
            else:
                result["runs"].append(_ticket_run(project, manifest, run_id, tickets.get(run_id), durations.get(run_id)))
    return [results[key] for key in sorted(results)]


# --- the locks --------------------------------------------------------------------------------------------------


def _locks(project, results):
    """Each package lock as it stood at each commit a cited run ran at, by `<commit>/<name>`, and the cited jobs' tools.

    Every run names its own `locks/<commit>/` (`run["locks"]`), so a run at an older commit is never given a later
    environment.
    """
    locks, seen = {}, {}
    for result in results:
        for run in result["runs"]:
            commit = run["commit"]
            if commit and commit not in seen:
                seen[commit] = False
                for name in LOCK_FILES:
                    done = _git(project, "show", "%s:%s/%s" % (commit, CODE, name))
                    if done.returncode == 0:
                        locks["%s/%s" % (commit, name)] = done.stdout
                        seen[commit] = True
            run["locks"] = "%s/%s/" % (LOCKS_DIR, commit) if commit and seen[commit] else None
    tools = {}
    for result in results:
        for run in result["runs"]:
            for tool in run["tools"]:
                key = (tool["name"], tool["version"], tool["lock"])
                runs = tools.setdefault(key, [])
                if run["run_id"] not in runs:
                    runs.append(run["run_id"])
    listed = [{"name": name, "version": version, "lock": lock, "runs": runs} for (name, version, lock), runs in sorted(
        tools.items(), key=lambda item: tuple(str(part) for part in item[0]))]
    return locks, listed


# --- the files --------------------------------------------------------------------------------------------------


def _owner_part(existing):
    if existing is None:
        return "\n"
    begin, end = existing.find(OWNER_BEGIN), existing.find(OWNER_END)
    if begin != -1 and end > begin:
        return existing[begin + len(OWNER_BEGIN):end]
    return "\n" + existing if not existing.startswith("\n") else existing


def _readme(project, results, owner):
    from wayline.code_repository import record

    settled = record(project)
    lines = ["# %s" % Path(project).resolve().name, ""]
    facts = []
    if settled.get("shape"):
        facts.append("a %s repository" % ("package" if settled["shape"] == "package" else "reproducibility"))
    if settled.get("license"):
        facts.append("licensed %s" % settled["license"])
    if facts:
        lines += ["This is %s." % ", ".join(facts), ""]
    runs = sum(len(result["runs"]) for result in results)
    lines += ["## Reproducing", "",
              "`REPRODUCE.md` (and `reproduce.json`) lists, per result, each run its findings cite: the command, the "
              "commit it ran at, its inputs, outputs, time, and hardware. `locks/<commit>/` holds the environment each ran in.",
              "", "%d result(s), %d run(s)." % (len(results), runs), "",
              "<!-- Rendered by wayline from its records. Write your own part between the markers below; it is kept. -->",
              OWNER_BEGIN + owner + OWNER_END, ""]
    return "\n".join(lines)


def _reproduce_md(results, tools):
    lines = ["# Reproducing the results", "",
             "Rendered by wayline from its records. Each run gives the commit of `main` it ran at; check that commit out, "
             "install the environment in its `locks/<commit>/`, and run its command.", ""]
    for result in results:
        lines += ["## %s" % result["result"][0].upper() + result["result"][1:], ""]
        for finding, text in zip(result["findings"], result["texts"]):
            lines.append("- %s: %s" % (finding, text))
        lines.append("")
        for run in result["runs"]:
            lines += ["### Run %s%s" % (run["run_id"], " (job %s)" % run["job"] if run["job"] else ""), "",
                      "- Commit: `%s`" % (run["commit"] or "not recorded"),
                      "- Environment: %s" % ("`%s`" % run["locks"] if run.get("locks") else "no lock at that commit")]
            if run["job"]:
                lines.append("- Command: `%s`" % " ".join(run["command"]))
            else:
                lines.append("- Commands: %s" % (", ".join("`%s`" % line for line in run["command"]) or "none recorded"))
            lines.append("- Inputs: %s" % (", ".join("`%s`" % name for name in run["inputs"]) or "none named"))
            lines.append("- Outputs: %s" % (", ".join("`%s` (sha256 %s)" % (output["name"], output["sha256"][:12])
                                                   for output in run["outputs"]) or "none"))
            lines.append("- Time: %s" % ("%d s" % run["seconds"] if run["seconds"] is not None else "not recorded"))
            hardware = run["hardware"]
            gpus = ", ".join(hardware["gpu_uuids"]) or "none"
            lines.append("- Hardware: GPUs held %s; cores %s; RAM %s" % (
                gpus, len(hardware["cores"]) or "not pinned", "%s GB" % hardware["ram_gb"] if hardware["ram_gb"] else "not set"))
            if run["tools"]:
                lines.append("- Tools: %s" % ", ".join("%s %s" % (tool["name"], tool["version"]) for tool in run["tools"]))
            lines.append("")
    if tools:
        lines += ["## Tools", ""]
        lines += ["- %s %s, lock %s" % (tool["name"], tool["version"], tool["lock"]) for tool in tools]
        lines.append("")
    return "\n".join(lines)


def _public_results(results):
    return [{"result": result["result"], "findings": result["findings"], "runs": result["runs"]} for result in results]


def render(project, results=None):
    """Render `REPRODUCE.md`, `reproduce.json`, the locks, and `README.md` into `code/`; returns the paths written.

    `reproduce.json` goes last, so a render that fails part way is not taken for a current one by the next wave.
    """
    project = Path(project)
    code = project / CODE
    results = runs_by_result(project) if results is None else results
    locks, tools = _locks(project, results)
    written = []

    def put(name, text):
        target = code / name
        target.parent.mkdir(parents=True, exist_ok=True)
        (atomic_bytes if isinstance(text, bytes) else atomic_write)(target, text)
        written.append("%s/%s" % (CODE, name))

    put(REPRODUCE_MD, _reproduce_md(results, tools))
    for name, data in locks.items():
        put("%s/%s" % (LOCKS_DIR, name), data)
    put("%s/%s" % (LOCKS_DIR, TOOLS_LOCK), json.dumps({"tools": tools}, indent=2) + "\n")
    for stale in sorted((code / LOCKS_DIR).rglob("*"), reverse=True):
        relative = "%s/%s" % (CODE, stale.relative_to(code).as_posix())
        if stale.is_file() and relative not in written:
            stale.unlink()  # a lock no cited run's commit holds any longer
            if _git(project, "ls-files", "--error-unmatch", "--", relative).returncode == 0:
                written.append(relative)  # its removal is committed; an untracked one has nothing to commit
        elif stale.is_dir() and not any(stale.iterdir()):
            stale.rmdir()
    readme = code / README
    put(README, _readme(project, results, _owner_part(readme.read_text(encoding="utf-8") if readme.is_file() else None)))
    record = {"code_tree": _code_tree(project), "results": _public_results(results)}
    put(REPRODUCE_JSON, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return written


def _code_tree(project):
    """A digest of `code/` on `main`, leaving out what this module renders, so its own commit is no change."""
    done = _git(project, "ls-tree", "-r", "main", "--", CODE)
    if done.returncode != 0:
        return None
    kept = []
    for line in done.stdout.decode().splitlines():
        parts = line.split("\t", 1)[-1].split("/")
        if len(parts) < 2 or parts[1] not in RENDERED:
            kept.append(line)
    return hashlib.sha256("\n".join(kept).encode()).hexdigest() if kept else None


def render_if_changed(project):
    """After a wave: render when `code/` changed or the cited runs did, and only then; returns the paths written."""
    project = Path(project)
    tree = _code_tree(project)
    if tree is None:
        return []
    try:
        before = json.loads((project / CODE / REPRODUCE_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = None
    results = runs_by_result(project)
    _locks(project, results)  # names each run's `locks/<commit>/`, which the comparison reads
    # A render that failed, or a wave commit that did not happen, leaves the rendered files changed on disk: render again.
    uncommitted = _git(project, "status", "--porcelain", "--", *("%s/%s" % (CODE, name) for name in RENDERED)).stdout.strip()
    if not uncommitted and isinstance(before, dict) and before.get("code_tree") == tree \
            and before.get("results") == json.loads(json.dumps(_public_results(results), ensure_ascii=False)):
        return []
    return render(project, results)
