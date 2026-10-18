"""The code repository: `code/`, cut by `git subtree split`, kept on a private GitHub copy (Implementation Decision 17).

Everything a project publishes lives under `code/`: the package or scripts, the tests, the environment
locks, `README.md`, and `LICENSE`. The project stays one working repository, and the code repository is
cut from it with `git subtree split --prefix=code`, so it never holds `research/`, `harness.json`, `jobs/`,
or `results/`.

Intake absorbs a project's own clone into `code/` with its history (`absorb_clone`): `git subtree add
--prefix=code <clone> <recorded commit>`, the clone's uncommitted changes as the next commit, named as
such, and the clone's `.git` kept outside the tree. A nested clone used to reach the wave commit as an
empty gitlink; absorbed, its files are the project's own and its history is `main`'s. Code from someone
else's paper stays `absorb --code`, a reference.

One setup question settles the repository's shape (a package or a reproducibility repository), its
remote, its visibility, and its license (`settle`), recorded in `harness.json` under `code_repository`.
The remote is created with `gh` through the tool runner: a new private repository by default; a new
private one carrying the upstream history for a taken-over repository that is not the owner's, never a
fork, since a fork of a public repository stays public; the owner's own repository only on their word,
confirmed once when it is public. Code, never a worker, pushes `code/`'s split after every wave that
changed it (`push_if_changed`, which the conductor calls and journals as `code_pushed`). Making the
repository public is on the irreversible list and is the owner's word only (`make_public`).

`git` is plain `git` here, run through the runner so a test can read back what ran; `gh` is resolved
through its `tools.json` record like every recorded tool (seam 6).
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from wayline import real_backend
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import CODE_PUSHED, Ledger, atomic_write
from wayline.tools import ToolsError, failure_line, run_recorded, run_tool

__all__ = [
    "CODE", "CLONES", "SHAPES", "VISIBILITIES", "HOWS", "CodeRepositoryError", "record", "absorb_clone", "inherited_license",
    "split", "check_answer", "ANSWER_FIELDS", "settle", "push", "push_if_changed", "make_public", "main_commit",
]

CODE = "code"
MAIN = "main"
# Where a clone that lay inside the project is moved by its absorption: gitignored, so its `.git` is outside the tree.
CLONES = ".clones"
SHAPES = ("package", "reproducibility")
VISIBILITIES = ("private", "public")
# How the remote came to be: a new private repository, a new private one carrying a taken-over repository's
# history (never a fork), or the owner's own repository taken over on their word.
HOWS = ("new", "copy", "owners_own")
KEY = "code_repository"
IDENTITY = ("-c", "user.name=wayline", "-c", "user.email=wayline@localhost")
GIT_TIMEOUT_S = 600

_LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "COPYING", "COPYING.md", "COPYING.txt")
# The license a file's words name, by SPDX id; the first match wins, so the longer names go first.
_LICENSES = (
    ("AGPL-3.0", r"GNU AFFERO GENERAL PUBLIC LICENSE"),
    ("LGPL-3.0", r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 3"),
    ("LGPL-2.1", r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 2\.1"),
    ("GPL-3.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 3"),
    ("GPL-2.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 2"),
    ("Apache-2.0", r"Apache License,?\s+Version 2\.0"),
    ("MPL-2.0", r"Mozilla Public License,?\s+(?:Version|v\.)\s*2\.0"),
    ("MIT", r"\bMIT License\b|Permission is hereby granted, free of charge, to any person obtaining a copy"),
    ("BSD-3-Clause", r"Neither the name of .{0,200}? nor the names of its\s+contributors"),
    ("BSD-2-Clause", r"Redistributions in binary form must reproduce the above copyright"),
    ("Unlicense", r"This is free and unencumbered software released into the public domain"),
)


class CodeRepositoryError(ValueError):
    """A step on the code repository nobody can take: no clone, `code/` already taken, a remote `gh` refused."""


# --- git, through the runner ------------------------------------------------------------------------------


def _git(run, cwd, *args, ok=(0,), env=None):
    done = run(["git", "-C", str(cwd), *args], timeout=GIT_TIMEOUT_S, env=env)
    if ok is not None and done.returncode not in ok:
        raise CodeRepositoryError("git %s failed in %s: %s" % (" ".join(args), cwd, failure_line(done)))
    return done


def _out(done):
    return (done.stdout or b"").decode("utf-8", errors="replace").strip()


def _identity(run, project):
    """The committer identity: the project's own, else wayline's, as `init` commits under."""
    return () if _out(_git(run, project, "config", "user.email", ok=None)) else IDENTITY


def main_commit(project, run=run_tool):
    """The commit `main` is at, or None when the project has no repository or no `main`: what a launch records.

    A project that only lies inside another repository has none of its own, and is not given that one's `main`.
    """
    if not (Path(project) / ".git").exists():
        return None
    done =_git(run, project, "rev-parse", "--verify", "--quiet", "refs/heads/" + MAIN, ok=None)
    return _out(done) or None if done.returncode == 0 else None


# --- the record in harness.json ---------------------------------------------------------------------------


def record(project):
    """`harness.json`'s `code_repository`, or {} when the project has none yet."""
    from wayline.project import read_harness

    return dict(read_harness(project).get(KEY) or {})


def _write_record(project, value):
    """Merge `value` into `code_repository` and write `harness.json` checked against its schema, under the ledger's lock."""
    from wayline.project import HARNESS_JSON, read_harness

    project = Path(project)
    with Ledger(project).lock():
        harness = read_harness(project)
        harness[KEY] = dict(harness.get(KEY) or {}, **value)
        try:
            check(harness, load_schema("harness"), name=HARNESS_JSON)
        except ValidationError as failure:
            raise CodeRepositoryError(str(failure)) from None
        atomic_write(project / HARNESS_JSON, json.dumps(harness, ensure_ascii=False, indent=2) + "\n")
    return harness[KEY]


# --- intake's absorption ------------------------------------------------------------------------------------


def absorb_clone(project, clone, run=run_tool):
    """Absorb the project's own clone into `code/` with its history; returns the `upstream` record written.

    `git subtree add --prefix=code <clone> <its HEAD>` runs in a temporary worktree of `main`, so a
    `harness.json` the owner's switches left uncommitted never stops it, and `main` is fast-forwarded to
    the result. The clone's uncommitted changes (tracked edits, deletions, and untracked files its
    `.gitignore` does not ignore) follow as the next commit, named as such. A clone that lay inside the
    project is moved under `.clones/` first, which is gitignored, and the empty gitlink a wave commit
    recorded for it is removed in a commit of its own. The upstream remote, the commit, and the inherited
    license are recorded in `harness.json`. Absorbing the same clone at the same commit again changes nothing.
    """
    project, clone = Path(project).resolve(), Path(clone).expanduser().resolve()
    if not (clone / ".git").exists():
        raise CodeRepositoryError("%s is not a git repository, so it has no history to absorb into code/" % clone)
    commit = _out(_git(run, clone, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", ok=None))
    if not commit:
        raise CodeRepositoryError("%s has no commit yet, so no commit pins what code/ would absorb" % clone)
    if main_commit(project, run) is None:
        raise CodeRepositoryError("%s has no git repository on main to absorb into; run wayline init %s" % (project, project))
    upstream = record(project).get("upstream") or {}
    if upstream.get("commit") == commit and upstream.get("clone") in (str(clone), _moved(project, clone)):
        return upstream
    nested = clone.is_relative_to(project)
    own_gitlink = clone.relative_to(project).as_posix() if nested else None
    tracked = [line.split("\t", 1)[-1] for line in _out(_git(run, project, "ls-files", "--stage", "--", CODE)).splitlines()
               if line and not (line.startswith("160000") and line.split("\t", 1)[-1] == own_gitlink)]
    if tracked:
        raise CodeRepositoryError("code/ already holds tracked files, so another clone cannot be absorbed into it; "
                                  "give a second repository to absorb --code as a reference")
    if (project / CODE).exists() and not (nested and clone == project / CODE):
        raise CodeRepositoryError("%s/code already exists and is not this clone; move it away and run intake again" % project)
    gitlink = None
    if nested:
        gitlink = clone.relative_to(project).as_posix()
        moved = project / CLONES / clone.name
        if moved.exists():
            raise CodeRepositoryError("%s already exists, so the clone at %s cannot be moved out of the tree there" % (moved, gitlink))
        moved.parent.mkdir(parents=True, exist_ok=True)
        os.rename(clone, moved)
        try:
            uncommitted = _absorb(project, moved, commit, gitlink, run)
        except BaseException:
            os.rename(moved, clone)  # nothing reached main, so the clone goes back where the owner put it
            raise
        clone = moved
    else:
        uncommitted = _absorb(project, clone, commit, gitlink, run)
    value = {
        "clone": str(clone), "url": _remote_url(clone, run), "commit": commit,
        "uncommitted": uncommitted, "license": inherited_license(project / CODE),
    }
    return _write_record(project, {"upstream": value})["upstream"]


def _moved(project, clone):
    return str(project / CLONES / clone.name)


def _absorb(project, clone, commit, gitlink, run):
    """Commit the clone into `code/` on a worktree of `main` and fast-forward `main`; the uncommitted changes' commit or None."""
    from wayline.project import write_gitignore

    identity = _identity(run, project)
    worktrees = project / ".worktrees"
    worktrees.mkdir(exist_ok=True)
    where = Path(tempfile.mkdtemp(prefix="absorb-code-", dir=worktrees))
    where.rmdir()
    _git(run, project, "worktree", "add", "--detach", str(where), MAIN)
    try:
        if gitlink:
            # The clone moved under `.clones/`, which the project's `.gitignore` now names, and its empty gitlink goes.
            write_gitignore(where)
            _git(run, where, "add", "--", ".gitignore")
            if _out(_git(run, where, "ls-files", "--stage", "--", gitlink)).startswith("160000"):
                _git(run, where, "rm", "-q", "--cached", "--", gitlink)
                if (where / gitlink).is_dir() and not any((where / gitlink).iterdir()):
                    (where / gitlink).rmdir()  # the checkout leaves a gitlink as an empty directory
            if _git(run, where, "diff", "--cached", "--quiet", ok=None).returncode != 0:
                _git(run, where, *identity, "commit", "-q", "-m", "code: the nested clone at %s moved out of the tree to "
                     "%s/, its empty gitlink removed" % (gitlink, CLONES))
        _git(run, where, *identity, "subtree", "add", "--prefix=" + CODE, str(clone), commit,
             "-m", "code: absorb %s at %s with its history" % (clone.name, commit[:12]))
        uncommitted = None
        if _mirror_working_tree(clone, where / CODE, run):
            _git(run, where, "add", "-A", "--", CODE)
            if _git(run, where, "diff", "--cached", "--quiet", "--", CODE, ok=None).returncode != 0:
                _git(run, where, *identity, "commit", "-q", "-m",
                     "code: the uncommitted changes of %s at intake, absorbed as the next commit" % clone.name)
                uncommitted = _out(_git(run, where, "rev-parse", "HEAD"))
        head = _out(_git(run, where, "rev-parse", "HEAD"))
    finally:
        _git(run, project, "worktree", "remove", "--force", str(where), ok=None)
        shutil.rmtree(where, ignore_errors=True)
        _git(run, project, "worktree", "prune", ok=None)
    _git(run, project, "merge", "-q", "--ff-only", head)
    return uncommitted


def _mirror_working_tree(clone, code, run):
    """Make `code` hold the clone's working tree; True when the clone has uncommitted changes to carry."""
    if not _out(_git(run, clone, "status", "--porcelain", "--untracked-files=all")):
        return False
    listed = _out(_git(run, clone, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    keep = {path for path in listed.split("\0") if path and os.path.lexists(clone / path)}
    for path in sorted(keep):
        source, target = clone / path, code / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.is_file():
            target.unlink()
        if source.is_symlink():
            os.symlink(os.readlink(source), target)
        elif source.is_file():
            shutil.copy2(source, target)
    for target in sorted(code.rglob("*"), reverse=True):
        relative = target.relative_to(code).as_posix()
        if (target.is_file() or target.is_symlink()) and relative not in keep:
            target.unlink()
        elif target.is_dir() and not target.is_symlink() and not any(target.iterdir()):
            target.rmdir()
    return True


def _remote_url(clone, run):
    """The clone's upstream: `origin`'s URL, else its first remote's, else None."""
    url = _out(_git(run, clone, "remote", "get-url", "origin", ok=None))
    if url:
        return url
    names = _out(_git(run, clone, "remote", ok=None)).split()
    return (_out(_git(run, clone, "remote", "get-url", names[0], ok=None)) or None) if names else None


def _repository_name(url):
    """`name` of a GitHub URL or `owner/name`, without `.git`; None for anything else."""
    match = re.search(r"(?:github\.com[:/])?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?\Z", str(url or "").strip())
    return match.group(2) if match else None


# --- the split and the push -----------------------------------------------------------------------------------


def split(project, run=run_tool):
    """`git subtree split --prefix=code main`: the code repository's head commit, or None while `code/` holds nothing."""
    project = Path(project)
    if _git(run, project, "cat-file", "-e", "%s:%s" % (MAIN, CODE), ok=None).returncode != 0:
        return None
    return _out(_git(run, project, "subtree", "split", "--prefix=" + CODE, MAIN)).splitlines()[-1]


def _push_url(remote):
    return remote["url"] if remote["url"].endswith(".git") or "://" not in remote["url"] else remote["url"] + ".git"


def _local(url):
    return url.startswith("file://") or "://" not in url and not re.match(r"^[\w.-]+@[\w.-]+:", url)


def push(project, commit, url, repository, run=run_tool):
    """Push `commit` to `url`'s `main`, never forced, and journal `code_pushed`; code alone calls this, never a worker."""
    if run is run_tool and not _local(url):
        real_backend("GitHub (the push of the code repository)")
    # Never a prompt for a password: a run is unattended, and a push without a credential fails and is tried again.
    _git(run, project, "push", url, "%s:refs/heads/%s" % (commit, MAIN), env={"GIT_TERMINAL_PROMPT": "0"})
    Ledger(project).append_event(CODE_PUSHED, {"commit": commit, "remote": repository})
    return commit


def push_if_changed(project, last_pushed, run=run_tool, push_url=_push_url):
    """After a wave: push `code/`'s split when it changed since `last_pushed`, the commit the last `code_pushed` named.

    `code/` changed when its tree on `main` is not the tree of the commit last pushed, which a first push
    always is; a project with no remote, or no `code/`, pushes nothing. Returns the commit pushed, or None.
    """
    project = Path(project)
    remote = record(project).get("remote")
    if not remote:
        return None
    tree = _out(_git(run, project, "rev-parse", "--verify", "--quiet", "%s:%s" % (MAIN, CODE), ok=None))
    if not tree:
        return None
    if last_pushed and _out(_git(run, project, "rev-parse", "--verify", "--quiet", "%s^{tree}" % last_pushed, ok=None)) == tree:
        return None
    return push(project, split(project, run), push_url(remote), remote["repository"], run=run)


# --- the setup question -----------------------------------------------------------------------------------------


def _gh(run, tools, *args):
    if run is run_tool:
        real_backend("GitHub (gh %s)" % " ".join(args[:2]))
    try:
        done = run_recorded("gh", list(args), tools=tools, run=run)
    except ToolsError as failure:
        raise CodeRepositoryError(str(failure)) from None
    if done.returncode != 0:
        raise CodeRepositoryError("gh %s failed: %s" % (" ".join(args), failure_line(done)))
    return _out(done)


def _view(run, tools, repository):
    text = _gh(run, tools, "repo", "view", repository, "--json", "nameWithOwner,url,visibility,viewerPermission")
    try:
        return json.loads(text)
    except ValueError:
        raise CodeRepositoryError("gh repo view %s printed no JSON: %s" % (repository, text[:200])) from None


def _create(run, tools, name):
    """`gh repo create <name> --private`: a new private repository, never a fork; its record."""
    text = _gh(run, tools, "repo", "create", name, "--private")
    match = re.search(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
    if not match:
        raise CodeRepositoryError("gh repo create %s printed no repository URL: %s" % (name, text[:200]))
    return {"repository": match.group(1), "url": "https://github.com/" + match.group(1)}


ANSWER_FIELDS = ("shape", "license", "visibility", "remote", "name", "confirm_public")


def check_answer(answer):
    """The setup answer with every field checked, before anything is made; unknown fields are refused, not ignored."""
    if not isinstance(answer, dict):
        raise CodeRepositoryError("the code repository's answer is an object with %s" % ", ".join(ANSWER_FIELDS))
    unknown = sorted(set(answer) - set(ANSWER_FIELDS))
    if unknown:
        raise CodeRepositoryError("the code repository's answer does not take %s; it takes %s" % (", ".join(unknown), ", ".join(ANSWER_FIELDS)))
    if answer.get("shape") not in SHAPES:
        raise CodeRepositoryError("the code repository's shape is %r; it is one of %s" % (answer.get("shape"), ", ".join(SHAPES)))
    if answer.get("visibility") is not None and answer["visibility"] not in VISIBILITIES:
        raise CodeRepositoryError("the visibility is %r; it is private or public" % answer["visibility"])
    for key in ("license", "name"):
        if answer.get(key) is not None and not isinstance(answer[key], str):
            raise CodeRepositoryError("%s is a string" % key)
    if answer.get("remote") is not None and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z", str(answer["remote"])):
        raise CodeRepositoryError("remote names a GitHub repository as owner/name, got %r" % answer["remote"])
    if not isinstance(answer.get("confirm_public", False), bool):
        raise CodeRepositoryError("confirm_public is true or false")
    return dict(answer)


def settle(project, answer, run=run_tool, tools=None, push_url=_push_url):
    """Record the setup question's answer and make the remote; returns `harness.json`'s `code_repository`.

    `answer` holds `shape` (`package` or `reproducibility`), and optionally `license` (an SPDX id; the
    inherited one by default), `visibility` (`private` by default; `public` is the owner's word),
    `remote` (`owner/name` of a repository to take over), `name` (the new repository's), and
    `confirm_public` (the owner's one confirmation that their own public repository may be taken over).

    A project that already has a remote keeps it and creates nothing. Without one, a taken-over
    repository that is the owner's (`gh repo view` reports `ADMIN`) becomes the remote; any other gets a
    new private repository that carries its history, never a fork; and with none named, a new private
    repository is created, carrying the absorbed upstream's history when intake absorbed a clone. `code/`'s
    split is pushed at once, and only then is the repository made public when the answer says so.
    """
    project = Path(project)
    answer = check_answer(answer)
    visibility = answer.get("visibility") or "private"
    current = record(project)
    upstream = current.get("upstream") or {}
    license = answer["license"] if "license" in answer else (current.get("license") or ((upstream.get("license") or {}).get("spdx")))
    remote = current.get("remote")
    public_already = current.get("visibility") == "public"
    if not remote:
        remote, public_already = _remote(run, tools, project, answer, upstream)
    settled = _write_record(project, {"shape": answer["shape"], "license": license, "remote": remote,
                                      "visibility": "public" if public_already else "private"})
    commit = split(project, run)
    if commit is not None:
        push(project, commit, push_url(remote), remote["repository"], run=run)
    if visibility == "public" and not public_already:
        settled = make_public(project, by="owner", run=run, tools=tools)
    return settled


def _remote(run, tools, project, answer, upstream):
    """The remote the answer names, made: `(remote record, whether it is public already)`."""
    named = answer.get("remote")
    if named:
        seen = _view(run, tools, named)
        if seen.get("viewerPermission") == "ADMIN":
            remote = {"repository": seen["nameWithOwner"], "url": seen["url"], "how": "owners_own"}
            if seen.get("visibility") == "PUBLIC":
                if not answer.get("confirm_public"):
                    raise CodeRepositoryError(
                        "%s is public: taking it over pushes this project's code/ there for anyone to read. Confirm once "
                        "(confirm_public) to take it over, or let wayline create a new private repository" % named)
                remote["confirmed_public"] = True
                return remote, True
            return remote, False
        # Not the owner's: a new private repository carrying its history, never a fork (a fork of a public one stays public).
        made = _create(run, tools, answer.get("name") or _repository_name(named) or project.name)
        return dict(made, how="copy"), False
    made = _create(run, tools, answer.get("name") or project.resolve().name)
    return dict(made, how="copy" if upstream else "new"), False


def make_public(project, by, run=run_tool, tools=None):
    """Make the code repository public: on the irreversible list, so only on the owner's word (`by="owner"`)."""
    if by != "owner":
        raise CodeRepositoryError("making the code repository public is on the irreversible list and is the owner's "
                                  "word only, never %s's" % by)
    remote = record(project).get("remote")
    if not remote:
        raise CodeRepositoryError("the code repository has no remote yet; the setup question makes one")
    _gh(run, tools, "repo", "edit", remote["repository"], "--visibility", "public", "--accept-visibility-change-consequences")
    return _write_record(project, {"visibility": "public"})


def inherited_license(code):
    """The license `code/` came with, by SPDX id when its words name one: `{file, spdx}`, or None without a license file."""
    for name in _LICENSE_FILES:
        path = Path(code) / name
        if path.is_file():
            text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())
            spdx = next((spdx for spdx, pattern in _LICENSES if re.search(pattern, text, re.IGNORECASE)), None)
            return {"file": name, "spdx": spdx}
    return None
