"""Code at the paper order (Implementation Decision 17; ticket 119).

"Aligned" means the code repository at the paper's tag recomputes every number and figure the paper prints. At a paper
order, once the changed results are drawn and the order's batch is settled, and before the writer launches, code takes
its steps (`step`, which the conductor's rest point calls once a wave until it says they are done):

1. **The files.** The scripts behind every figure of the figure plan and every drawing number a current finding cites
   are copied into `code/figures/`, one per drawing (`R4-2.py`), with `FIGURES.md` and `figures.json` saying which
   figure and which finding each is behind; and an environment file (`environment.yml`) and a `Dockerfile` are rendered
   into `code/` from the locks (`code/requirements.lock`, `renv.lock`, `Manifest.toml`, `octave-packages.lock`, and the
   tools the cited jobs called, `code/locks/tools.json`), whatever `harness.json.environment` says. A file of that name
   wayline did not render is the owner's and is kept: wayline's goes beside it (`environment.wayline.yml`,
   `Dockerfile.wayline`). `REPRODUCE.md` and the locks are rendered first (ticket 106), and all of it is committed on
   `main`, so the tag carries them.
2. **The tag.** `paper-N` (N counting orders) is tagged on `main`, and the code repository's split is pushed with the
   tag through the tool runner (`code_repository.push_tag`), never forced; a project with no remote keeps the tag local.
   Journaled `paper_code` `tagged`, with the commit, the split, and whether it was pushed.
3. **The stale re-runs.** Every result (the current findings of one ticket, as `reproduce.runs_by_result` groups them)
   one of whose runs ran at a commit whose `code/` differs from the tag's is re-run at the tag: each job it cites is
   launched again through the job runner's seam (detached, polled once a wave, so the conductor never waits on it) in a
   worktree checked out at the tag (`.worktrees/paper-N`), its paths into tracked code mapped there, its outputs written
   there, and what the project holds untracked (the environment, the data) read where it is. A run no job made has no
   command code can run again, so its result is listed as not re-run. Once a result's jobs end, the numbers check
   (`wayline.numbers`) reads its findings against the re-run's outputs: a number that matched the run and does not match
   the re-run moved, and only then is a ticket cut (one per result, re-running it at the current code, its findings to
   replace the moved ones); a re-run whose numbers held stands with no ticket. Each is journaled `paper_code` `rerun`
   with its outcome: `held`, `moved` (with the ticket), `failed`, or `not_rerun`.
4. **The code-to-Methods check** over all of `code/` at the tag (`methods.check` with every file whole), with the
   reasons and the not-methods every integrated ticket gave; its problems go to the writer and to `PAPER.md`. Journaled
   `paper_code` `done`.

The record of all of it is `research/orders/<N>/code.json` (schema `paper_code`), which `PAPER.md` and the writer's
prompt read (`report_lines`, `writer_lines`). A code repository still private at the order is listed in the account under
"Waiting on you"; making it public stays the owner's word (ticket 121's card).
"""

import json
import os
import re
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.code_repository import CodeRepositoryError, _git, _identity, _out
from wayline.ledger import PAPER_CODE, TICKET_CREATED, ledger_for, now_ts
from wayline.tools import run_tool

__all__ = [
    "PaperCodeError", "TAG", "SCHEMA", "FIGURES", "ENVIRONMENT_FILE", "DOCKERFILE", "BASE_IMAGE", "TAGGED", "LAUNCHED", "RERUN",
    "DONE", "HELD", "MOVED", "FAILED", "NOT_RERUN", "state", "step", "read_record", "record_path", "stale_results",
    "figure_scripts", "copy_figure_scripts", "environment_files", "write_environment", "writer_lines", "report_lines",
]

CODE = "code"
TAG = "paper-%d"
ORDERS = "orders"                         # research/orders/<N>/code.json
RECORD = "code.json"
SCHEMA = "paper_code"
FIGURES = "figures"                       # code/figures/
FIGURES_MD = "FIGURES.md"
FIGURES_JSON = "figures.json"
ENVIRONMENT_FILE = "environment.yml"
DOCKERFILE = "Dockerfile"
BESIDE = {ENVIRONMENT_FILE: "environment.wayline.yml", DOCKERFILE: "Dockerfile.wayline"}
MARK = "Rendered by wayline"              # the first line's words that make a file wayline's to render again
BASE_IMAGE = "mambaorg/micromamba:1.5.10"
WORKTREES = ".worktrees"
LOGS = "results/logs"
COMMIT_MESSAGE = "wayline: code at paper order %d"

TAGGED, LAUNCHED, RERUN, DONE = "tagged", "rerun_launched", "rerun", "done"
HELD, MOVED, FAILED, NOT_RERUN = "held", "moved", "failed", "not_rerun"

_DRAWING_FILE = re.compile(r"^drawings/(R[1-9][0-9]*-[1-9][0-9]*)/(.+\.json)$")


class PaperCodeError(CodeRepositoryError):
    """A step of code's at the order that cannot be taken. A git that failed raises `CodeRepositoryError`, its base."""


def _one_line(text):
    return " ".join(str(text or "").split())


def _plain(path):
    """A project-relative path as a finding cites it, without a leading `./`."""
    text = str(path)
    while text.startswith("./"):
        text = text[2:]
    return text


def _handle(saved):
    """The `JobHandle` a re-run's record keeps as a dict, rebuilt for a poll, a kill, or a cleanup."""
    from wayline import resources
    return resources.JobHandle(**{key: tuple(value) if key in ("gpu_indices", "cores") else value for key, value in saved.items()})


# --- the journal and the record ---------------------------------------------------------------------------------------


def state(events, order):
    """Where code's steps stand for the order `order`, read from the journal: `{tagged, launched, reruns, done}`, the
    `tagged` and `done` payloads (or None), and the `rerun_launched` and `rerun` payloads by result."""
    found = {"tagged": None, "launched": {}, "reruns": {}, "done": None}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("event") != PAPER_CODE or payload.get("order") != order:
            continue
        if payload.get("step") == TAGGED:
            found["tagged"] = dict(payload)
        elif payload.get("step") == LAUNCHED:
            found["launched"][payload.get("result")] = dict(payload)
        elif payload.get("step") == RERUN:
            found["reruns"][payload.get("result")] = dict(payload)
        elif payload.get("step") == DONE:
            found["done"] = dict(payload)
    return found


def record_path(order):
    return "%s/%d/%s" % (ORDERS, order, RECORD)


def read_record(project_or_ledger, order):
    """`research/orders/<order>/code.json`, or None before code's steps began."""
    try:
        return ledger_for(project_or_ledger).read_json(record_path(order))
    except (OSError, ValueError):
        return None


def _blank(order):
    return {"order": order, "tag": TAG % order, "commit": None, "split": None, "pushed": False, "push_problem": None,
            "committed": None, "figures": [], "environment": [], "kept": [], "stale": None, "reruns": [], "methods": None,
            "started": now_ts(), "done": None}


def _write(book, record):
    book.write_json(record_path(record["order"]), record, schema=SCHEMA)


# --- the scripts behind the figures and the cited drawing numbers -----------------------------------------------------


def figure_scripts(project, plan):
    """`[{drawing, script, figures, findings}]`: each drawing whose script is behind a planned figure's panel (or a planned
    table) or computes a number a current finding cites, with its script's path in the project, in drawing order."""
    from wayline import drawings, provenance
    book = ledger_for(project)
    plots = {plot["id"]: plot for plot in drawings.read_plots(book)["plots"]}
    behind = {}

    def take(name):
        if name not in behind:
            try:
                record = book.read_json(drawings.record_path(name))
            except (OSError, ValueError):
                record = {}
            behind[name] = {"drawing": name, "script": record.get("script"), "figures": [], "findings": []}
        return behind[name]

    for figure in list((plan or {}).get("figures") or []) + list((plan or {}).get("supplementary") or []):
        for panel in figure.get("panels") or []:
            made = (plots.get(panel) or {}).get("drawings") or []
            if made:
                entry = take(made[-1])
                if figure["id"] not in entry["figures"]:
                    entry["figures"].append(figure["id"])
    for table in (plan or {}).get("tables") or []:
        made = (plots.get(table.get("plot")) or {}).get("drawings") or []
        if made:
            entry = take(made[-1])
            if table["id"] not in entry["figures"]:
                entry["figures"].append(table["id"])
    for finding in provenance.current_findings(book):
        for locator in provenance._cited(finding):
            found = _DRAWING_FILE.match(_plain(str(locator).partition("#")[0]))
            if found and found.group(2).split("/")[-1] != drawings.DRAFT:
                entry = take(found.group(1))
                if finding["id"] not in entry["findings"]:
                    entry["findings"].append(finding["id"])
    return [behind[name] for name in sorted(behind, key=lambda name: tuple(int(part) for part in re.findall(r"[0-9]+", name)))]


def copy_figure_scripts(project, plan):
    """Copy each script `figure_scripts` names into `code/figures/<drawing><suffix>`, write `FIGURES.md` and
    `figures.json`, and remove the scripts an earlier order copied that no figure or number is behind now. Returns the
    record's `figures`: `[{drawing, file, figures, findings, missing}]`."""
    project = Path(project)
    folder = project / CODE / FIGURES
    try:
        before = json.loads((folder / FIGURES_JSON).read_text(encoding="utf-8")).get("scripts") or []
    except (OSError, ValueError, AttributeError):
        before = []
    copied = []
    for entry in figure_scripts(project, plan):
        source = project / str(entry["script"] or "")
        if not entry["script"] or not source.is_file():
            copied.append(dict(entry, file=None, missing="the drawing's record names no script on disk"))
            continue
        name = entry["drawing"] + source.suffix
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(source.read_bytes())
        copied.append(dict(entry, file="%s/%s/%s" % (CODE, FIGURES, name), missing=None))
    now = {Path(entry["file"]).name for entry in copied if entry["file"]}
    for stale in before:
        name = Path(str((stale or {}).get("file") or "")).name
        if name and name not in now and (folder / name).is_file():
            (folder / name).unlink()
    if copied or before:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / FIGURES_JSON).write_text(json.dumps({"scripts": [{key: entry[key] for key in ("drawing", "file", "figures", "findings")}
                                                                   for entry in copied if entry["file"]]}, indent=2) + "\n", encoding="utf-8")
        (folder / FIGURES_MD).write_text(_figures_md(copied), encoding="utf-8")
    return [{key: entry[key] for key in ("drawing", "file", "figures", "findings", "missing")} for entry in copied]


def _figures_md(copied):
    lines = ["# The scripts behind the figures", "", "%s from its records at the paper order: one script per drawing, each behind "
             "the figures and tables it drew panels for and the numbers the findings cite from it. A script reads the data "
             "its drawing read; `REPRODUCE.md` names the runs that made that data." % MARK, ""]
    for entry in copied:
        if not entry["file"]:
            continue
        said = []
        if entry["figures"]:
            said.append("behind %s" % ", ".join(entry["figures"]))
        if entry["findings"]:
            said.append("computes the numbers findings %s cite" % ", ".join(entry["findings"]))
        lines.append("- `%s` (drawing %s): %s." % (Path(entry["file"]).name, entry["drawing"], "; ".join(said)))
    return "\n".join(lines) + "\n"


# --- the environment file and the Dockerfile ------------------------------------------------------------------------


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _tool_versions(code):
    try:
        tools = json.loads((code / "locks" / "tools.json").read_text(encoding="utf-8")).get("tools") or []
    except (OSError, ValueError, AttributeError):
        return {}
    versions = {}
    for tool in tools:
        if isinstance(tool, dict) and tool.get("name") and tool.get("version"):
            versions.setdefault(str(tool["name"]).lower(), str(tool["version"]))
    return versions


def environment_files(project, environment_file=ENVIRONMENT_FILE):
    """`{name: text}` of the environment file and the Dockerfile, rendered from the locks `code/` holds; the Dockerfile
    builds `environment_file`, the name the environment file is written under."""
    from wayline import environment, methods_inventory, software
    project = Path(project)
    code = project / CODE
    locks = {language: _read(code / name) for language, name in software.LOCKS.items()}
    tools = _tool_versions(code)
    python = locks[software.PYTHON] is not None or (project / ".venv").exists()
    conda = []
    if python:
        conda += ["python=%s" % environment.python_version(project), "pip"]
    r_version = None
    if locks[software.R] is not None:
        try:
            r_version = (json.loads(locks[software.R]).get("R") or {}).get("Version")
        except (ValueError, AttributeError):
            r_version = None
        conda.append("r-base=%s" % r_version if r_version else "r-base")
    if locks[software.JULIA] is not None:
        found = re.search(r'^julia_version\s*=\s*"([^"]+)"', locks[software.JULIA], re.M)
        conda.append("julia=%s" % found.group(1) if found else "julia")
    if locks[software.OCTAVE] is not None:
        conda.append("octave=%s" % tools["octave"] if tools.get("octave") else "octave")
    pins = sorted("%s==%s" % pair for pair in methods_inventory._packages(software.LOCKS[software.PYTHON], locks[software.PYTHON] or ""))
    lines = ["# %s from the locks in this repository (the environment the cited runs ran in); "
             "`micromamba create -f %s` builds it." % (MARK, environment_file),
             "name: %s" % re.sub(r"[^A-Za-z0-9_.-]", "-", project.name), "channels:", "  - conda-forge", "dependencies:"]
    lines += ["  - %s" % item for item in conda] or ["  []"]
    if pins:
        lines.append("  - pip:")
        lines += ["    - %s" % pin for pin in pins]
    docker = ["# %s from the locks in this repository: the environment the cited runs ran in, whatever the project ran it as."
              % MARK, "FROM %s" % BASE_IMAGE, "COPY --chown=$MAMBA_USER:$MAMBA_USER . /code", "WORKDIR /code",
              "RUN micromamba install -y -n base -f %s && micromamba clean -a -y" % environment_file,
              "ARG MAMBA_DOCKERFILE_ACTIVATE=1"]
    if locks[software.R] is not None:
        docker.append("RUN Rscript -e \"install.packages('renv', repos = 'https://cloud.r-project.org'); "
                      "renv::restore(lockfile = 'renv.lock', prompt = FALSE)\"")
    if locks[software.JULIA] is not None:
        docker.append("RUN julia --project=. -e 'using Pkg; Pkg.instantiate()'")
    for name, version in methods_inventory._packages(software.LOCKS[software.OCTAVE], locks[software.OCTAVE] or ""):
        docker.append("RUN octave --eval \"pkg install 'https://downloads.sourceforge.net/project/octave/Octave%%20Forge%%20Packages/"
                      "Individual%%20Package%%20Releases/%s-%s.tar.gz'\"" % (name, version))
    return {ENVIRONMENT_FILE: "\n".join(lines) + "\n", DOCKERFILE: "\n".join(docker) + "\n"}


def write_environment(project):
    """Write the environment file and the Dockerfile into `code/`: `(written, kept)`, the files written (relative to the
    project) and the owner's files of those names kept, each with wayline's beside it."""
    code = Path(project) / CODE
    targets, kept = {}, []
    for name in (ENVIRONMENT_FILE, DOCKERFILE):
        existing = _read(code / name)
        if existing is not None and MARK not in (existing.splitlines() or [""])[0]:
            kept.append("%s/%s" % (CODE, name))
            targets[name] = BESIDE[name]
        else:
            targets[name] = name
    written = []
    for name, text in environment_files(project, targets[ENVIRONMENT_FILE]).items():
        (code / targets[name]).write_text(text, encoding="utf-8")
        written.append("%s/%s" % (CODE, targets[name]))
    return written, kept


# What the order itself writes into `code/`, which neither the stale check nor the code-to-Methods check counts as the
# project's code: the copied drawing scripts with their index, and wayline's environment files. An owner's file in
# `code/figures/` or an owner's own environment file is code like any other.
_ORDER_FILES = ("%s/%s/%s" % (CODE, FIGURES, FIGURES_MD), "%s/%s/%s" % (CODE, FIGURES, FIGURES_JSON),
                "%s/%s" % (CODE, BESIDE[ENVIRONMENT_FILE]), "%s/%s" % (CODE, BESIDE[DOCKERFILE]))
_ORDER_GLOB = "%s/%s/R[0-9]*-[0-9]*.*" % (CODE, FIGURES)


def _order_written(path, wayline_environment=()):
    """Whether `path` (under `code/`) is one the order writes: `wayline_environment` names the environment files the order
    wrote under their own names this time."""
    import fnmatch
    return path in _ORDER_FILES or path in wayline_environment or fnmatch.fnmatch(path, _ORDER_GLOB)


# --- the tag -----------------------------------------------------------------------------------------------------------


def _commit_files(project, book, run, number, paths):
    """Commit `paths` under `code/` on `main` when they changed; the commit, or None when nothing did."""
    if not paths:
        return None
    with book.lock():
        _git(run, project, "add", "-A", "--", *paths)
        if _git(run, project, "diff", "--cached", "--quiet", "--", *paths, ok=None).returncode == 0:
            return None
        _git(run, project, *_identity(run, project), "commit", "-q", "-m", COMMIT_MESSAGE % number, "--", *paths)
        return _out(_git(run, project, "rev-parse", "HEAD"))


def _prepare_and_tag(project, book, order, record, run, push_url, say):
    from wayline import code_repository, paper, paper_figures, reproduce
    from wayline.project import read_harness
    number = order["order"]
    tag = TAG % number
    main = code_repository.main_commit(project, run)
    if main is None:
        record.update(push_problem="the project has no repository with a main branch: nothing was tagged")
        _write(book, record)
        book.append_event(PAPER_CODE, {"order": number, "step": TAGGED, "tag": None, "commit": None, "split": None, "pushed": False,
                                       "reason": record["push_problem"]})
        return
    paths = []
    if (project / CODE).is_dir():
        plan = paper_figures.build(project, paper.answers(project, order),
                                   autonomous=read_harness(project).get("autonomy") == paper.AUTONOMOUS, venue=order.get("venue"))
        record["figures"] = copy_figure_scripts(project, plan)
        record["environment"], record["kept"] = write_environment(project)
        try:
            paths += reproduce.render_if_changed(project)
        except (OSError, ValueError) as failure:
            say("  paper order %d: REPRODUCE.md was not rendered: %s" % (number, failure))
        paths += ["%s/%s" % (CODE, FIGURES)] if (project / CODE / FIGURES).exists() else []
        paths += record["environment"]
    record["committed"] = _commit_files(project, book, run, number, paths)
    main = code_repository.main_commit(project, run)
    existing = _out(_git(run, project, "rev-parse", "--verify", "--quiet", "refs/tags/%s^{commit}" % tag, ok=None))
    if existing:
        main = existing  # a step taken before a restart: the tag stands where it was put
    else:
        _git(run, project, *_identity(run, project), "tag", "-a", tag, "-m", "The paper of order %d" % number, main)
    record["commit"] = main
    remote = code_repository.record(project).get("remote")
    split = None
    if not (project / CODE).is_dir() or _git(run, project, "cat-file", "-e", "%s:%s" % (main, CODE), ok=None).returncode != 0:
        record["push_problem"] = "code/ holds nothing at the tag, so there is no code repository to tag"
    elif not remote:
        split = code_repository.split(project, run, at=main)
        record["push_problem"] = "the code repository has no remote yet (the setup question makes one): the tag is local"
    else:
        url = (push_url or code_repository._push_url)(remote)
        try:
            pushed = code_repository.last_push(project)
            if pushed and pushed.get("main") == main:
                split = pushed["commit"]
            else:
                split = code_repository.split(project, run, since=pushed, at=main)
                code_repository.push(project, split, url, remote["repository"], branch=remote.get("branch") or code_repository.MAIN,
                                     main=main, run=run)
            code_repository.push_tag(project, split, url, remote["repository"], tag, run=run)
            record["pushed"] = True
        except code_repository.CodeRepositoryError as failure:
            record["push_problem"] = _one_line(failure)
            say("  paper order %d: the code repository was not pushed with %s: %s" % (number, tag, failure))
    record["split"] = split
    _write(book, record)
    book.append_event(PAPER_CODE, {"order": number, "step": TAGGED, "tag": tag, "commit": main, "split": split,
                                   "pushed": record["pushed"], "reason": record["push_problem"]})
    say("  paper order %d: tagged %s at %s%s" % (number, tag, main[:12], ", pushed with the split" if record["pushed"] else ""))


# --- the stale re-runs ----------------------------------------------------------------------------------------------


def _changed_since(project, run, commit, tag_commit, wayline_environment=()):
    """Whether `code/` (less what wayline renders there) differs between `commit` and the tag; True for an unknown commit."""
    from wayline import reproduce
    if not commit:
        return True
    excluded = [":(exclude)%s/%s" % (CODE, name) for name in reproduce.RENDERED]
    excluded += [":(exclude)%s" % path for path in _ORDER_FILES + tuple(wayline_environment)]
    excluded.append(":(exclude,glob)%s" % _ORDER_GLOB)
    done = _git(run, project, "diff", "--quiet", commit, tag_commit, "--", CODE, *excluded, ok=None)
    return done.returncode != 0


def stale_results(project, tag_commit, run=run_tool, wayline_environment=()):
    """`[{result, ticket, runs, jobs, sessions}]`: each result one of whose cited runs ran at a commit whose `code/` is not the
    tag's, with those stale runs, the jobs that made them (each once), and the stale runs no job made."""
    from wayline import reproduce
    found = []
    for result in reproduce.runs_by_result(project):
        runs = [item for item in result["runs"] if _changed_since(project, run, item.get("commit"), tag_commit, wayline_environment)]
        if not runs:
            continue
        jobs = []
        for item in runs:
            if item.get("job") and item["job"] not in jobs:
                jobs.append(item["job"])
        found.append({"result": result["result"], "ticket": int(result["result"].split()[-1]),
                      "runs": sorted({item["run_id"] for item in runs}), "jobs": jobs,
                      "sessions": sorted({item["run_id"] for item in runs if not item.get("job")})})
    return found


def _relative(project, path):
    """`path` relative to the project, or None outside it; a path inside a ticket's worktree (`.worktrees/<id>/...`), where a
    job a worker added may have named it, is the same path in the project."""
    if not os.path.isabs(path):
        return None
    try:
        parts = Path(path).resolve().relative_to(project).parts
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0] == WORKTREES:
        parts = parts[2:]
    return Path(*parts).as_posix() if parts else "."


def _rerun_spec(project, worktree, job_record, number):
    """The `JobSpec` that runs `job_record`'s command again in the worktree at the tag: the tracked code and the outputs
    there, what the project holds untracked (its environment, its data) where it is."""
    from wayline import resources
    cwd = Path(job_record["cwd"])
    outputs = []
    for output in job_record.get("expected_outputs") or []:
        absolute = output if os.path.isabs(output) else str(cwd / output)
        relative = _relative(project, absolute)
        if relative is not None:
            outputs.append(relative)

    def mapped(text):
        relative = _relative(project, text)
        if relative is None:
            return text
        if relative in outputs or (worktree / relative).exists() or relative == ".":
            return str(worktree / relative) if relative != "." else str(worktree)
        return text

    def token(text):
        key, sep, value = text.partition("=")
        if sep and key.startswith("-") and os.path.isabs(value):
            return key + "=" + mapped(value)
        return mapped(text)

    relative_cwd = _relative(project, str(cwd))
    new_cwd = cwd if relative_cwd is None else (worktree if relative_cwd == "." else worktree / relative_cwd)
    new_cwd.mkdir(parents=True, exist_ok=True)
    command = [token(str(part)) for part in job_record.get("command") or []]
    for part in command[1:]:
        # A relative input the project holds untracked (data a job read beside its cwd) is linked into the worktree.
        if os.path.isabs(part) or part.startswith("-") or not part.strip():
            continue
        original, there = cwd / part, new_cwd / part
        relative = _relative(project, str(original))
        if original.exists() and not there.exists() and relative is not None and relative not in outputs:
            there.parent.mkdir(parents=True, exist_ok=True)
            there.symlink_to(original.resolve())
    for relative in outputs:
        stale = worktree / relative
        if stale.is_file() or stale.is_symlink():
            stale.unlink()  # a tracked copy of the old output is not the re-run's
        stale.parent.mkdir(parents=True, exist_ok=True)
    devices = job_record.get("devices") or {}
    identifier = "paper%d-%s" % (number, job_record["id"])
    return resources.JobSpec(
        id=identifier, ticket=int(job_record["ticket"]), command=tuple(command), cwd=str(new_cwd),
        log=str(Path(project) / LOGS / ("%s.log" % identifier)),
        env={key: token(str(value)) for key, value in (job_record.get("env") or {}).items()},
        gpu_uuids=tuple(devices.get("gpu_uuids") or ()), cores=tuple(devices.get("cores") or ()), ram_gb=devices.get("ram_gb") or 0.0,
        expected_outputs=tuple(str(worktree / relative) for relative in outputs),
        wallclock_minutes=int(job_record.get("wallclock_minutes") or resources.DEFAULT_WALLCLOCK_MINUTES),
        tools=tuple(dict(tool) for tool in job_record.get("tools") or ()), environment=job_record.get("environment"),
    ), outputs


def _worktree(project, run, number, commit):
    path = Path(project) / WORKTREES / (TAG % number)
    if not path.is_dir():
        _git(run, project, "worktree", "add", "--detach", "--force", str(path), commit)
    return path


def _remove_worktree(project, run, number):
    path = Path(project) / WORKTREES / (TAG % number)
    if path.exists():
        _git(run, project, "worktree", "remove", "--force", str(path), ok=None)
    _git(run, project, "worktree", "prune", ok=None)


def _launch(project, book, record, seen, run, say):
    from wayline import resources
    number = record["order"]
    runner = resources.JobRunner(None)
    # The re-runs skip the conductor's placement, so two never share a GPU or a core: a result whose jobs ask for what a
    # running re-run holds waits for a later wave. The rest point runs no ticket meanwhile.
    busy = {device for entry in record["reruns"] for job in entry["jobs"] if job["state"] is None for device in job.get("devices") or []}
    for entry in record["stale"]:
        name = entry["result"]
        if name in seen["launched"] or name in seen["reruns"]:
            continue
        held = next((item for item in record["reruns"] if item["result"] == name), None)
        if held is not None:  # recorded before a restart, and not yet journaled: journal what the record holds
            jobs = [job["rerun"] for job in held["jobs"]]
            if held["outcome"] is None:
                book.append_event(PAPER_CODE, {"order": number, "step": LAUNCHED, "result": name, "jobs": jobs})
            else:
                book.append_event(PAPER_CODE, {"order": number, "step": RERUN, "result": name, "jobs": jobs,
                                               "outcome": held["outcome"], "ticket": held["cut"], "reason": held["reason"]})
            continue
        if not entry["jobs"]:
            why = "its runs were a session's, with no job command code can run again; REPRODUCE.md lists what the session ran"
            record["reruns"].append({"result": name, "ticket": entry["ticket"], "jobs": [], "outcome": NOT_RERUN, "reason": why,
                                     "moved": [], "cut": None})
            _write(book, record)
            book.append_event(PAPER_CODE, {"order": number, "step": RERUN, "result": name, "jobs": [], "outcome": NOT_RERUN,
                                           "ticket": None, "reason": why})
            say("  paper order %d: %s is not re-run: %s" % (number, name, why))
            continue
        wanted = set()
        for job in entry["jobs"]:
            try:
                devices = book.read_json("jobs/%s.json" % job).get("devices") or {}
            except (OSError, ValueError):
                devices = {}
            wanted |= {"gpu:%s" % uuid for uuid in devices.get("gpu_uuids") or []} | {"core:%s" % core for core in devices.get("cores") or []}
        if wanted & busy:
            continue
        worktree = _worktree(project, run, number, record["commit"])
        jobs, problem = [], None
        for job in entry["jobs"]:
            try:
                original = book.read_json("jobs/%s.json" % job)
                spec, outputs = _rerun_spec(project, worktree, original, number)
                handle = runner.launch(spec)
            except (OSError, ValueError, resources.JobError) as failure:
                problem = "job %s could not be launched again: %s" % (job, _one_line(failure))
                break
            jobs.append({"job": job, "rerun": spec.id, "outputs": outputs, "state": None, "exit_code": None, "reason": None,
                         "devices": sorted(["gpu:%s" % uuid for uuid in spec.gpu_uuids] + ["core:%s" % core for core in spec.cores]),
                         "handle": {"id": handle.id, "backend": handle.backend, "log": handle.log, "cwd": handle.cwd,
                                    "unit": handle.unit, "gpu_indices": list(handle.gpu_indices), "cores": list(handle.cores),
                                    "started_at": handle.started_at}})
        if problem is not None:
            for job in jobs:  # the result is not re-run whole: what did launch is stopped and cleaned up
                try:
                    runner.kill(_handle(job["handle"]), hard=True)
                    runner.cleanup(_handle(job["handle"]))
                except (resources.JobError, OSError):
                    pass
                job.update(state="killed", reason="stopped: another job of its result could not be launched")
            record["reruns"].append({"result": name, "ticket": entry["ticket"], "jobs": jobs, "outcome": FAILED, "reason": problem,
                                     "moved": [], "cut": None})
            _write(book, record)
            book.append_event(PAPER_CODE, {"order": number, "step": RERUN, "result": name, "jobs": [job["rerun"] for job in jobs],
                                           "outcome": FAILED, "ticket": None, "reason": problem})
            say("  paper order %d: the re-run of %s failed: %s" % (number, name, problem))
            continue
        busy |= wanted
        note = ("its session run(s) %s, which no job made, were not re-run" % ", ".join(entry["sessions"])
                if entry.get("sessions") else None)
        record["reruns"].append({"result": name, "ticket": entry["ticket"], "jobs": jobs, "outcome": None, "reason": note,
                                 "moved": [], "cut": None})
        _write(book, record)
        book.append_event(PAPER_CODE, {"order": number, "step": LAUNCHED, "result": name, "jobs": [job["rerun"] for job in jobs]})
        say("  paper order %d: re-running %s at %s: job(s) %s" % (number, name, record["tag"], ", ".join(job["rerun"] for job in jobs)))


def _poll(project, book, record, seen, harness_root, say):
    """Poll every re-run still running; conclude each result whose jobs all ended. Returns the results still running."""
    from wayline import resources
    number = record["order"]
    running = []
    for entry in record["reruns"]:
        name = entry["result"]
        if name in seen["reruns"]:
            continue
        if entry["outcome"] is not None:  # concluded before a restart, and not yet journaled
            book.append_event(PAPER_CODE, {"order": number, "step": RERUN, "result": name, "jobs": [job["rerun"] for job in entry["jobs"]],
                                           "outcome": entry["outcome"], "ticket": entry["cut"], "reason": entry["reason"]})
            continue
        changed = False
        for job in entry["jobs"]:
            if job["state"] is not None:
                continue
            handle = _handle(job["handle"])
            backend = resources.JOBS_BACKENDS.get(handle.backend) or resources.jobs_backend()
            try:
                polled = backend.poll(handle)
            except (resources.JobError, OSError, ValueError) as failure:
                say("  paper order %d: job %s could not be polled: %s" % (number, job["rerun"], failure))
                continue
            if not polled.terminal:
                continue
            job.update(state=polled.name, exit_code=polled.exit_code, reason=polled.reason)
            try:
                backend.cleanup(handle)
            except (resources.JobError, OSError):
                pass
            changed = True
        if changed:
            _write(book, record)
        if any(job["state"] is None for job in entry["jobs"]):
            running.append(name)
            continue
        _conclude(project, book, record, entry, harness_root, say)
    return running


def _reader(project, worktree, outputs):
    """What the numbers check reads after the re-run: the re-run's outputs in the worktree, every other file in the project."""
    from wayline import numbers
    base, fresh = numbers.reader(project), numbers.reader(worktree)
    fresh_paths = set(outputs)

    def read(path):
        return fresh(path) if _plain(path) in fresh_paths else base(path)

    read.locate = lambda path: fresh.locate(path) if _plain(path) in fresh_paths else base.locate(path)
    return read


def moved_numbers(project, worktree, findings, outputs):
    """`[{finding, sentence, numbers}]`: each sentence of `findings` with a number that matched a value of the run and
    matches none of the re-run's (`outputs`, project-relative, read in `worktree`)."""
    from wayline import numbers
    before = numbers.check(findings, numbers.reader(project))
    after = numbers.check(findings, _reader(project, worktree, outputs))
    found = []
    for was, now in zip(before.sentences, after.sentences):
        gone = [number for number in now.unmatched if number not in was.unmatched]
        if gone:
            found.append({"finding": findings[was.finding - 1]["id"], "sentence": _one_line(was.text), "numbers": gone})
    return found


def _conclude(project, book, record, entry, harness_root, say):
    from wayline import provenance, resources
    number, name = record["order"], entry["result"]
    worktree = Path(project) / WORKTREES / (TAG % number)
    failed = [job for job in entry["jobs"] if job["state"] != "exited" or (job["exit_code"] or 0) != 0]
    problem = None
    if failed:
        problem = "; ".join("job %s ended %s" % (job["rerun"], job["reason"] or job["state"]) for job in failed)
    else:
        missing = [resources.output_problem(str(worktree), relative) for job in entry["jobs"] for relative in job["outputs"]]
        missing = [item for item in missing if item is not None]
        if missing:
            problem = "the re-run exited 0 and %s" % "; ".join(missing)
    if problem is None and not any(job["outputs"] for job in entry["jobs"]):
        problem = "its job(s) declare no expected outputs, so code could not read the re-run's numbers"
    if problem is not None:
        entry.update(outcome=FAILED, reason="; ".join(item for item in (problem, entry.get("reason")) if item))
    else:
        findings = [finding for finding in provenance.current_findings(book) if int(finding.get("ticket") or 0) == entry["ticket"]]
        outputs = sorted({relative for job in entry["jobs"] for relative in job["outputs"]})
        entry["moved"] = moved_numbers(project, worktree, findings, outputs)
        if entry["moved"]:
            entry.update(outcome=MOVED, cut=_cut_ticket(project, book, record, entry))
        else:
            entry["outcome"] = HELD
    _write(book, record)
    book.append_event(PAPER_CODE, {"order": number, "step": RERUN, "result": name, "jobs": [job["rerun"] for job in entry["jobs"]],
                                   "outcome": entry["outcome"], "ticket": entry["cut"], "reason": entry["reason"]})
    say("  paper order %d: the re-run of %s at %s: %s%s" % (
        number, name, record["tag"], {HELD: "its numbers held", MOVED: "its numbers moved", FAILED: "failed"}[entry["outcome"]],
        "; ticket %d is cut" % entry["cut"] if entry["cut"] else (": %s" % entry["reason"] if entry["reason"] else "")))


_COPIED = ("kind", "difficulty", "touches", "resources", "role", "skills", "software", "inputs", "outputs", "acceptance",
           "objectives", "sections", "budget")


def _cut_ticket(project, book, record, entry):
    """The one ticket a result whose numbers moved gets: its work again at the current code, its findings to replace the
    moved ones. Built from the result's own ticket, which it re-does; the conductor launches it once the order is done."""
    from wayline import tickets
    try:
        original = next((fields for fields in tickets.read_tickets(project) if fields["id"] == entry["ticket"]), None)
    except (OSError, ValueError):
        original = None
    with book.lock():
        identifier = tickets.next_id(project)
        fields = {"kind": "experiment", "difficulty": 2, "touches": [], "role": "experimenter", "acceptance": {}}
        fields.update({key: original[key] for key in _COPIED if original is not None and key in original})
        if fields["kind"] not in ("experiment", "analysis", "code"):
            fields.update(kind="experiment", role="experimenter")
        fields.update({
            "id": identifier, "status": "open", "blocked_by": [], "proposed_by": "conductor",
            "title": _one_line("Re-run the result of ticket %d: its numbers moved at %s" % (entry["ticket"], record["tag"])),
            "origin": "paper order %d: code re-ran %s at %s" % (record["order"], entry["result"], record["tag"]),
            "demo": "the result of ticket %d recomputed at the current code, its findings replacing the moved ones" % entry["ticket"],
        })
        lines = ["", "## Its numbers moved at %s" % record["tag"], "",
                 "At paper order %d code re-ran %s at the tag %s (commit %s), because its code changed since the run its "
                 "findings cite. These numbers no longer match what the code computes:" % (
                     record["order"], entry["result"], record["tag"], record["commit"]), ""]
        lines += ["- %s: \"%s\" (moved: %s)" % (item["finding"], item["sentence"], ", ".join(item["numbers"])) for item in entry["moved"]]
        lines += ["", "Run the result's work again at the current code (job(s) %s re-ran as %s) and return findings that replace "
                  "%s, each naming the one it replaces in `replaces`." % (
                      ", ".join(job["job"] for job in entry["jobs"]), ", ".join(job["rerun"] for job in entry["jobs"]),
                      ", ".join(sorted({item["finding"] for item in entry["moved"]}))), ""]
        tickets.write_ticket(book, fields, "\n".join(lines))
        book.append_event(TICKET_CREATED, {"ticket": identifier, "kind": fields["kind"], "proposed_by": "conductor",
                                           "origin": fields["origin"], "blocked_by": []}, ticket=identifier)
    return identifier


# --- the code-to-Methods check over all of code/ ---------------------------------------------------------------------


def _given_reasons(book):
    """The `parameters` and `not_methods` every integrated ticket's last attempt gave (its `methods.json`)."""
    from wayline import methods
    latest = {}
    for path in (book.research / "sessions").glob("*/*/%s" % methods.CODE_RULE_FILE):
        ticket, attempt = path.parent.parent.name, path.parent.name
        if ticket.isdigit() and attempt.isdigit() and int(attempt) >= latest.get(int(ticket), (0, None))[0]:
            latest[int(ticket)] = (int(attempt), path.parent)
    parameters, not_methods = [], []
    for ticket in sorted(latest):
        rule = methods.read_code_rule(latest[ticket][1]) or {}
        parameters += [dict(entry) for entry in rule.get("parameters") or []]
        not_methods += [dict(entry) for entry in rule.get("not_methods") or []]
    return {"parameters": parameters, "not_methods": not_methods}


def _check_methods(project, book, record, run, methods_run, methods_tools, policy, harness_root):
    from wayline import methods, reproduce
    mine = [path for path in record["environment"] if path not in record["kept"]]
    if record["commit"] is None or not (Path(project) / CODE).is_dir():
        return {"passed": True, "files": 0, "problems": [], "notes": ["no code/ at the order: nothing to check"]}
    listed = _out(_git(run, project, "ls-tree", "-r", "--name-only", record["commit"], "--", CODE + "/", ok=None)).splitlines()
    skipped = set(reproduce.RENDERED)
    changed = {path: None for path in listed if path and len(path.split("/")) > 1 and path.split("/")[1] not in skipped
               and not _order_written(path, mine)}
    if not changed:
        return {"passed": True, "files": 0, "problems": [], "notes": ["code/ holds no file of its own at the tag"]}
    try:
        outcome = methods.check(book, project, _given_reasons(book), run=methods_run, tools=methods_tools, policy=policy,
                                harness_root=harness_root, changed=changed)
    except (methods.MethodsError, OSError, ValueError) as failure:
        return {"passed": False, "files": len(changed), "problems": [], "notes": ["the check could not run: %s" % _one_line(failure)]}
    if outcome is None:
        return {"passed": True, "files": len(changed), "problems": [], "notes": []}
    if outcome.refused is not None:
        raise outcome.refused  # a closed window is no verdict on the code: the conductor pauses and the check runs after it
    return {"passed": outcome.passed, "files": len(changed), "problems": [_one_line(problem) for problem in outcome.problems],
            "notes": [_one_line(note) for note in outcome.notes]}


# --- the step the conductor takes ---------------------------------------------------------------------------------------


def step(project, order, *, run=run_tool, push_url=None, methods_run=run_tool, methods_tools=None, policy=None,
         harness_root=HARNESS_ROOT, say=None):
    """Take code's steps for the open order `order` as far as they go now; True once they are all done, False while a
    re-run is still running. Each call resumes from the journal and the record, so a restarted conductor goes on."""
    say = say or (lambda text: None)
    project = Path(project).resolve()
    book = ledger_for(project)
    number = order["order"]
    seen = state(book.read_events()[0], number)
    if seen["done"] is not None:
        return True
    record = read_record(book, number) or _blank(number)
    if seen["tagged"] is None:
        _prepare_and_tag(project, book, order, record, run, push_url, say)
        seen = state(book.read_events()[0], number)
    if record["stale"] is None:
        # With no code/ at the tag there is no code a run could have run on, and nothing to re-run.
        held = record["commit"] and _git(run, project, "cat-file", "-e", "%s:%s" % (record["commit"], CODE), ok=None).returncode == 0
        mine = [path for path in record["environment"] if path not in record["kept"]]
        record["stale"] = stale_results(project, record["commit"], run, mine) if held else []
        _write(book, record)
    _launch(project, book, record, seen, run, say)
    seen = state(book.read_events()[0], number)
    running = _poll(project, book, record, seen, harness_root, say)
    concluded = {entry["result"] for entry in record["reruns"] if entry["outcome"] is not None}
    if running or any(entry["result"] not in concluded for entry in record["stale"]):
        return False  # a re-run still running, or one waiting for the devices another holds
    record["methods"] = _check_methods(project, book, record, run, methods_run, methods_tools, policy, harness_root)
    record["done"] = now_ts()
    _write(book, record)
    _remove_worktree(project, run, number)
    book.append_event(PAPER_CODE, {"order": number, "step": DONE, "tag": record["tag"] if record["commit"] else None,
                                   "commit": record["commit"]})
    problems = len(record["methods"]["problems"])
    say("  paper order %d: code's steps are done; the code-to-Methods check over code/ %s" % (
        number, "passed" if not problems else "found %d problem(s), for the writer and PAPER.md" % problems))
    return True


# --- what the writer and PAPER.md read --------------------------------------------------------------------------------


_SAID = {HELD: "its numbers held; the re-run stands", MOVED: "its numbers moved", FAILED: "the re-run failed",
         NOT_RERUN: "not re-run"}


def _rerun_line(entry):
    line = "- %s: %s" % (entry["result"], _SAID.get(entry["outcome"], entry["outcome"] or "still running"))
    if entry.get("cut"):
        line += "; ticket %d is cut to re-run it at the current code" % entry["cut"]
    if entry.get("reason"):
        line += " (%s)" % entry["reason"]
    for item in entry.get("moved") or []:
        line += "\n  - %s, \"%s\": %s moved" % (item["finding"], item["sentence"], ", ".join(item["numbers"]))
    return line


def writer_lines(record):
    """The writer's prompt's part on code's steps: the results whose numbers moved or could not be recomputed at the tag,
    and the code-to-Methods check's problems, which the Methods should answer."""
    if not record:
        return "- Code took no step at this order."
    lines = ["- The code repository is tagged %s at commit %s." % (record["tag"], record["commit"]) if record.get("commit")
             else "- The project has no repository: nothing was tagged."]
    flagged = [entry for entry in record.get("reruns") or [] if entry["outcome"] in (MOVED, FAILED, NOT_RERUN)]
    if flagged:
        lines.append("- The results whose code changed since their runs, which the tag does not recompute as the findings "
                     "state them: say so where the paper reports them, and claim no reproduction for them.")
        lines += ["  %s" % line for line in "\n".join(_rerun_line(entry) for entry in flagged).splitlines()]
    problems = ((record.get("methods") or {}).get("problems")) or []
    if problems:
        lines.append("- The code-to-Methods check over all of code/ found what the Methods does not yet describe: describe "
                     "each method and give each parameter's reason where the Methods discusses it.")
        lines += ["  - %s" % problem for problem in problems]
    return "\n".join(lines)


def report_lines(record):
    """`PAPER.md`'s section on code's steps at the order."""
    if not record:
        return ["Code took no step at this order."]
    lines = []
    if record.get("commit"):
        lines.append("The code repository is tagged `%s` at commit %s of main%s." % (
            record["tag"], record["commit"],
            " and pushed with its split %s" % (record.get("split") or "")[:12] if record.get("pushed") else
            "; not pushed: %s" % record.get("push_problem") if record.get("push_problem") else ""))
    else:
        lines.append("Nothing was tagged: %s." % (record.get("push_problem") or "the project has no repository"))
    lines += ["", "### Re-runs at the tag", ""]
    reruns = record.get("reruns") or []
    lines += [_rerun_line(entry) for entry in reruns] or ["No result's code changed since its run: nothing was re-run."]
    lines += ["", "### The scripts behind the figures", ""]
    copied = record.get("figures") or []
    for entry in copied:
        behind = ", ".join(entry["figures"] + ["the numbers of %s" % finding for finding in entry["findings"]])
        lines.append("- %s: %s" % ("`%s`" % entry["file"] if entry.get("file") else "drawing %s, not copied (%s)" % (entry["drawing"], entry["missing"]),
                                     behind))
    if not copied:
        lines.append("No figure or cited drawing number has a script to copy.")
    lines += ["", "### The environment", ""]
    if record.get("environment"):
        lines.append("Rendered from the locks: %s." % ", ".join("`%s`" % path for path in record["environment"]))
        lines += ["- `%s` is yours and was kept; wayline's is beside it." % path for path in record.get("kept") or []]
    else:
        lines.append("Nothing rendered: the project has no code/.")
    lines += ["", "### The code-to-Methods check over all of code/", ""]
    methods = record.get("methods") or {}
    if not methods:
        lines.append("Not run.")
    else:
        lines.append("%d file(s) checked: %s" % (methods.get("files", 0), "passed." if methods.get("passed") and not methods.get("problems")
                                                 else "%d problem(s), given to the writer:" % len(methods.get("problems") or [])))
        lines += ["- %s" % problem for problem in methods.get("problems") or []]
        lines += ["- note: %s" % note for note in methods.get("notes") or []]
    return lines
