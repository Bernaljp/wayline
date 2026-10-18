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
    "head_commit", "absorbed_clone", "CodePushRejected", "last_push",
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
    """The commit `main` is at, or None when the project has no repository or no `main`.

    A project that only lies inside another repository has none of its own, and is not given that one's `main`.
    """
    if not (Path(project) / ".git").exists():
        return None
    done = _git(run, project, "rev-parse", "--verify", "--quiet", "refs/heads/" + MAIN, ok=None)
    return (_out(done) or None) if done.returncode == 0 else None


def head_commit(path, within=None, run=run_tool):
    """The commit checked out where `path` lies, which is what a launch records (decision 17); None outside a repository.

    A ticket's worktree may be on a `ticket/<id>` an earlier attempt left on an older `main`, so the commit it
    runs at is its own HEAD, not `main`'s tip. With `within`, a repository whose root is not under it (one the
    path merely lies inside) gives None.
    """
    done = _git(run, path, "rev-parse", "--show-toplevel", "HEAD", ok=None)
    lines = _out(done).splitlines()
    if done.returncode != 0 or len(lines) != 2:
        return None
    if within is not None and not Path(lines[0]).resolve().is_relative_to(Path(within).resolve()):
        return None
    return lines[1]


# --- the record in harness.json ---------------------------------------------------------------------------


def record(project):
    """`harness.json`'s `code_repository`, or {} when the project has none yet."""
    from wayline.project import read_harness

    return dict(read_harness(project).get(KEY) or {})


def _merged(project, value):
    """`harness.json` with `value` merged into `code_repository`, checked against its schema; nothing is written."""
    from wayline.project import HARNESS_JSON, read_harness

    harness = read_harness(project)
    harness[KEY] = dict(harness.get(KEY) or {}, **value)
    try:
        check(harness, load_schema("harness"), name=HARNESS_JSON)
    except ValidationError as failure:
        raise CodeRepositoryError(str(failure)) from None
    return harness


def _write_record(project, value):
    """Merge `value` into `code_repository` and write `harness.json` checked against its schema, under the ledger's lock."""
    from wayline.project import HARNESS_JSON

    project = Path(project)
    with Ledger(project).lock():
        harness = _merged(project, value)
        atomic_write(project / HARNESS_JSON, json.dumps(harness, ensure_ascii=False, indent=2) + "\n")
    return harness[KEY]


# --- intake's absorption ------------------------------------------------------------------------------------


def absorbed_clone(project, clone):
    """The `upstream` record when `clone` is the clone intake already absorbed, where it is or where the owner put it; else None."""
    upstream = record(project).get("upstream") or {}
    clone = str(Path(clone).expanduser().resolve())
    return upstream if upstream and clone in (upstream.get("clone"), upstream.get("moved_from")) else None


def absorb_clone(project, clone, run=run_tool):
    """Absorb the project's own clone into `code/` with its history; returns the `upstream` record written.

    `git subtree add --prefix=code <clone> <its HEAD>` runs in a temporary worktree of `main`, so a
    `harness.json` the owner's switches left uncommitted never stops it, and `main` is fast-forwarded to
    the result. The clone's uncommitted changes (tracked edits, deletions, and untracked files its
    `.gitignore` does not ignore) follow as the next commit, named as such. A clone that lay inside the
    project is moved under `.clones/` first, which is gitignored, and the empty gitlink a wave commit
    recorded for it is removed in a commit of its own. The upstream remote, the commit, and the inherited
    license are recorded in `harness.json`, checked before `main` moves.

    The clone already absorbed, named where it is or where the owner put it, is not absorbed again,
    whatever it has done since: `code/` is where the work goes on, and its record is handed back.
    The project itself, and a repository that encloses it, are refused.
    """
    project, clone = Path(project).resolve(), Path(clone).expanduser().resolve()
    done = absorbed_clone(project, clone)
    if done is not None:
        return done
    if clone == project:
        raise CodeRepositoryError("%s is the project itself; intake absorbs the project's own clone, a repository of its own" % clone)
    if project.is_relative_to(clone):
        raise CodeRepositoryError("%s encloses the project %s; absorbing it would pour the project into its own code/" % (clone, project))
    if not (clone / ".git").exists():
        raise CodeRepositoryError("%s is not a git repository, so it has no history to absorb into code/" % clone)
    commit = _out(_git(run, clone, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", ok=None))
    if not commit:
        raise CodeRepositoryError("%s has no commit yet, so no commit pins what code/ would absorb" % clone)
    if main_commit(project, run) is None:
        raise CodeRepositoryError("%s has no git repository on main to absorb into; run wayline init %s" % (project, project))
    nested = clone.is_relative_to(project)
    own_gitlink = clone.relative_to(project).as_posix() if nested else None
    tracked = [line.split("\t", 1)[-1] for line in _out(_git(run, project, "ls-files", "--stage", "--", CODE)).splitlines()
               if line and not (line.startswith("160000") and line.split("\t", 1)[-1] == own_gitlink)]
    if tracked:
        raise CodeRepositoryError("code/ already holds tracked files, so another clone cannot be absorbed into it; "
                                  "give a second repository to absorb --code as a reference")
    if (project / CODE).exists() and not (nested and clone == project / CODE):
        raise CodeRepositoryError("%s/code already exists and is not this clone; move it away and run intake again" % project)
    moved = project / CLONES / clone.name if nested else None
    if moved is not None and moved.exists():
        raise CodeRepositoryError("%s already exists, so the clone at %s cannot be moved out of the tree there" % (moved, own_gitlink))
    value = {"clone": str(moved or clone), "url": _remote_url(clone, run), "commit": commit,
             "uncommitted": None, "license": inherited_license(clone)}
    if moved is not None:
        value["moved_from"] = str(clone)
    _merged(project, {"upstream": value})  # a record harness.json would refuse stops the absorption before main moves
    if moved is not None:
        moved.parent.mkdir(parents=True, exist_ok=True)
        os.rename(clone, moved)
        try:
            value["uncommitted"] = _absorb(project, moved, commit, own_gitlink, run)
        except BaseException:
            os.rename(moved, clone)  # nothing reached main, so the clone goes back where the owner put it
            raise
    else:
        value["uncommitted"] = _absorb(project, clone, commit, None, run)
    value["license"] = inherited_license(project / CODE)
    return _write_record(project, {"upstream": value})["upstream"]


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
    """Make `code` hold the clone's working tree; True when the clone has uncommitted changes to carry.

    A path the clone's index or working tree names is kept, a submodule's directory included: removing the
    empty directory a gitlink is checked out as would stage the gitlink's deletion.
    """
    if not _out(_git(run, clone, "status", "--porcelain", "--untracked-files=all")):
        return False
    listed = _out(_git(run, clone, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    staged = (_git(run, clone, "ls-files", "-z", "--stage").stdout or b"").decode("utf-8", errors="replace")
    gitlinks = {entry.split("\t", 1)[1] for entry in staged.split("\0") if entry.startswith("160000 ") and "\t" in entry}
    keep = {path for path in listed.split("\0") if path and (os.path.lexists(clone / path) or path in gitlinks)}
    for path in sorted(keep):
        source, target = clone / path, code / path
        if path in gitlinks or (source.is_dir() and not source.is_symlink()):
            # A submodule: its gitlink is the commit the index pins, which the absorbed commit already holds. Its empty
            # directory stays, since a gitlink whose directory is missing is staged as deleted.
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.is_file():
            target.unlink()
        if source.is_symlink():
            os.symlink(os.readlink(source), target)
        elif source.is_file():
            shutil.copy2(source, target)
    submodules = tuple(path + "/" for path in keep if path in gitlinks or ((clone / path).is_dir() and not (clone / path).is_symlink()))
    for target in sorted(code.rglob("*"), reverse=True):
        relative = target.relative_to(code).as_posix()
        if relative in keep or relative.startswith(submodules):
            continue
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.is_dir() and not any(target.iterdir()):
            target.rmdir()
    return True


def _remote_url(clone, run):
    """The clone's upstream: `origin`'s URL, else its first remote's, else None."""
    url = _out(_git(run, clone, "remote", "get-url", "origin", ok=None))
    if url:
        return url
    names = _out(_git(run, clone, "remote", ok=None)).split()
    return (_out(_git(run, clone, "remote", "get-url", names[0], ok=None)) or None) if names else None


def _github_name(url):
    """`owner/name` of a GitHub URL (https or ssh) or of `owner/name` itself, lowercased; None for anything else."""
    match = re.search(r"(?:github\.com[:/]|\A)([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?\Z", str(url or "").strip())
    return ("%s/%s" % match.groups()).lower() if match else None


# --- the split and the push -----------------------------------------------------------------------------------


class CodePushRejected(CodeRepositoryError):
    """The remote refused the split: its branch holds commits the split does not descend from. Never forced."""

    def __init__(self, message, commit):
        super().__init__(message)
        self.commit = commit


def _is_ancestor(run, project, older, newer):
    return _git(run, project, "merge-base", "--is-ancestor", older, newer, ok=None).returncode == 0


def split(project, run=run_tool, since=None, at=MAIN):
    """`git subtree split --prefix=code`: the code repository's head commit at `at`, or None while `code/` holds nothing.

    `since` is the last `code_pushed` (`{commit, main}`): the split it pushed and the commit of `main` it was cut
    from. The split then walks only what `main` gained since, not its whole history, which a ledger commit a wave
    lengthens: a join commit carrying the trailers `git subtree add` writes (`git-subtree-mainline`,
    `git-subtree-split`) maps that `main` to that split, and the walk starts from a commit off `main` whose parents
    are `at` and the join. The result is the commit the whole walk gives, so the pushes stay one history. A `since`
    that `main` no longer holds falls back to the whole walk. Neither commit made for the walk is on any branch.
    """
    project = Path(project)
    if _git(run, project, "cat-file", "-e", "%s:%s" % (at, CODE), ok=None).returncode != 0:
        return None
    rev = at
    base, cut = (since or {}).get("main"), (since or {}).get("commit")
    if base and cut and _git(run, project, "cat-file", "-e", cut + "^{commit}", ok=None).returncode == 0 \
            and _git(run, project, "cat-file", "-e", base + "^{commit}", ok=None).returncode == 0 \
            and _is_ancestor(run, project, base, at) \
            and _out(_git(run, project, "rev-parse", "%s:%s" % (base, CODE), ok=None)) == \
            _out(_git(run, project, "rev-parse", cut + "^{tree}", ok=None)):
        identity = _identity(run, project)
        # `--ignore-joins` reads only a join whose subject is the one `git subtree add` writes by default, which this one
        # alone has (intake's absorption names its own), so the last push is the one join the walk starts from.
        join = _out(_git(run, project, *identity, "commit-tree", base + "^{tree}", "-p", base, "-p", cut, "-m",
                         "Add '%s/' from commit '%s'\n\ngit-subtree-dir: %s\ngit-subtree-mainline: %s\ngit-subtree-split: %s"
                         % (CODE, cut, CODE, base, cut)))
        rev = _out(_git(run, project, *identity, "commit-tree", at + "^{tree}", "-p", at, "-p", join, "-m",
                        "wayline: the walk of code/'s split from the last push"))
        walked = _git(run, project, "subtree", "split", "--prefix=" + CODE, "--ignore-joins", rev, ok=None)
        if walked.returncode == 0 and _out(walked):
            return _out(walked).splitlines()[-1]
        rev = at  # a join the walk cannot read (one an owner's own `git subtree add` wrote, say): the whole walk instead
    return _out(_git(run, project, "subtree", "split", "--prefix=" + CODE, rev)).splitlines()[-1]


def _push_url(remote):
    return remote["url"] if remote["url"].endswith(".git") or "://" not in remote["url"] else remote["url"] + ".git"


def _local(url):
    return url.startswith("file://") or "://" not in url and not re.match(r"^[\w.-]+@[\w.-]+:", url)


_REJECTED = re.compile(r"\[rejected\]|non-fast-forward|fetch first|\[remote rejected\]", re.IGNORECASE)


def push(project, commit, url, repository, branch=MAIN, main=None, run=run_tool):
    """Push `commit` to `url`'s `branch`, never forced, and journal `code_pushed`; code alone calls this, never a worker.

    `main` is the commit of `main` the split was cut from, which the next split starts its walk after. A remote
    whose branch holds commits the split does not descend from raises `CodePushRejected`.
    """
    if run is run_tool and not _local(url):
        real_backend("GitHub (the push of the code repository)")
    main = main or main_commit(project, run)
    # Never a prompt for a password: a run is unattended, and a push without a credential fails and is tried again.
    done = _git(run, project, "push", url, "%s:refs/heads/%s" % (commit, branch), env={"GIT_TERMINAL_PROMPT": "0"}, ok=None)
    if done.returncode != 0:
        said = failure_line(done)
        if _REJECTED.search((done.stderr or b"").decode("utf-8", errors="replace") + said):
            raise CodePushRejected("%s refused the push of code/'s split %s to %s, which holds commits the split does not "
                                   "descend from (%s); wayline never forces a push" % (repository, commit[:12], branch, said), commit)
        raise CodeRepositoryError("git push to %s failed: %s" % (repository, said))
    Ledger(project).append_event(CODE_PUSHED, {"commit": commit, "remote": repository, "main": main})
    return commit


def push_if_changed(project, last_pushed, run=run_tool, push_url=_push_url, skip=None):
    """After a wave: push `code/`'s split when it changed since `last_pushed`, the last `code_pushed` (`{commit, main}`).

    `code/` changed when its tree on `main` is not the tree of the commit last pushed, which a first push
    always is; a project with no remote, or no `code/`, pushes nothing, and neither does a split equal to `skip`
    (one the remote refused, which pushing again cannot mend). Returns the commit pushed, or None.
    """
    project = Path(project)
    remote = record(project).get("remote")
    if not remote:
        return None
    at = main_commit(project, run)
    tree = _out(_git(run, project, "rev-parse", "--verify", "--quiet", "%s:%s" % (at, CODE), ok=None)) if at else ""
    if not tree:
        return None
    last = (last_pushed or {}).get("commit")
    if last and _out(_git(run, project, "rev-parse", "--verify", "--quiet", "%s^{tree}" % last, ok=None)) == tree:
        return None
    cut = split(project, run, since=last_pushed, at=at)
    if cut is None or cut == skip:
        return None
    return push(project, cut, push_url(remote), remote["repository"], branch=remote.get("branch") or MAIN, main=at, run=run)


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
    text = _gh(run, tools, "repo", "view", repository, "--json", "nameWithOwner,url,visibility,viewerPermission,defaultBranchRef")
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
    return {"repository": match.group(1), "url": "https://github.com/" + match.group(1), "branch": MAIN}


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


def last_push(project):
    """The last `code_pushed` the journal holds, as `{commit, main}`, or None before the first push."""
    events, _ = Ledger(project).read_events()
    pushed = [event.get("payload") or {} for event in events if event.get("event") == CODE_PUSHED]
    return {"commit": pushed[-1].get("commit"), "main": pushed[-1].get("main")} if pushed else None


def settle(project, answer, run=run_tool, tools=None, push_url=_push_url):
    """Record the setup question's answer and make the remote; returns `harness.json`'s `code_repository`.

    `answer` holds `shape` (`package` or `reproducibility`), and optionally `license` (an SPDX id; the
    inherited one by default), `visibility` (`private` by default; `public` is the owner's word),
    `remote` (`owner/name` of a repository to take over), `name` (the new repository's), and
    `confirm_public` (the owner's one confirmation that their own public repository may be taken over).

    A project that already has a remote keeps it and creates nothing. Without one:

    - with none named, a new private repository is created, carrying the absorbed upstream's history
      when intake absorbed a clone (`how: copy`), else `how: new`;
    - a named repository that is the owner's (`gh repo view` reports `ADMIN`) becomes the remote, its
      default branch the one pushed, once its branch holds nothing the split does not descend from;
    - a named repository that is not the owner's gets a new private repository carrying its history,
      never a fork, which only the clone intake absorbed from it can carry: any other is refused.

    `code/`'s split is pushed at once, and only then is the repository made public when the answer says so.
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
        remote, public_already = _remote(run, tools, project, answer, upstream, push_url)
    settled = _write_record(project, {"shape": answer["shape"], "license": license, "remote": remote,
                                      "visibility": "public" if public_already else "private"})
    push_if_changed(project, last_push(project), run=run, push_url=push_url)
    if visibility == "public" and not public_already:
        settled = make_public(project, by="owner", run=run, tools=tools)
    return settled


def _remote(run, tools, project, answer, upstream, push_url):
    """The remote the answer names, made: `(remote record, whether it is public already)`."""
    named = answer.get("remote")
    if not named:
        made = _create(run, tools, answer.get("name") or project.resolve().name)
        return dict(made, how="copy" if upstream else "new"), False
    seen = _view(run, tools, named)
    if seen.get("viewerPermission") != "ADMIN":
        # Not the owner's: a new private repository carrying its history, never a fork (a fork of a public one stays
        # public). The history is the one intake absorbed into code/, which only a clone of this repository holds.
        if _github_name(upstream.get("url")) != _github_name(named):
            raise CodeRepositoryError(
                "%s is not yours, and it is not the repository intake absorbed into code/ (%s), so a new private "
                "repository could not carry its history: absorb its clone at intake first (the spec's clone), and "
                "wayline then creates the private copy" % (named, upstream.get("url") or "no clone was absorbed"))
        made = _create(run, tools, answer.get("name") or named.split("/")[-1])
        return dict(made, how="copy"), False
    branch = ((seen.get("defaultBranchRef") or {}).get("name")) or MAIN
    remote = {"repository": seen["nameWithOwner"], "url": seen["url"], "how": "owners_own", "branch": branch}
    public = seen.get("visibility") == "PUBLIC"
    if public and not answer.get("confirm_public"):
        raise CodeRepositoryError(
            "%s is public: taking it over pushes this project's code/ there for anyone to read. Confirm once "
            "(confirm_public) to take it over, or let wayline create a new private repository" % named)
    _check_takes(run, project, remote, push_url)
    if public:
        remote["confirmed_public"] = True
    return remote, public


def _check_takes(run, project, remote, push_url):
    """Refuse the owner's repository when its branch holds commits `code/`'s split does not descend from.

    An unforced push there would be refused at every wave; wayline never forces one, and says so now, before
    anything is recorded. An empty repository, or one whose branch is the absorbed history, takes the split.
    """
    url = push_url(remote)
    if run is run_tool and not _local(url):
        real_backend("GitHub (reading %s before taking it over)" % remote["repository"])
    fetched = _git(run, project, "fetch", "--quiet", url, "refs/heads/%s" % remote["branch"], env={"GIT_TERMINAL_PROMPT": "0"}, ok=None)
    if fetched.returncode != 0:
        said = failure_line(fetched)
        if "couldn't find remote ref" in said.lower() or "couldn't find remote ref" in (fetched.stderr or b"").decode("utf-8", "replace").lower():
            return  # an empty repository, or one without that branch yet
        raise CodeRepositoryError("%s could not be read before taking it over: %s" % (remote["repository"], said))
    theirs = _out(_git(run, project, "rev-parse", "FETCH_HEAD"))
    cut = split(project, run)
    if cut is None or not _is_ancestor(run, project, theirs, cut):
        raise CodeRepositoryError(
            "%s's %s holds commits code/'s history does not descend from (%s), so a push there would be refused, and "
            "wayline never forces one: absorb its clone at intake first (the spec's clone), or let wayline create a new "
            "private repository" % (remote["repository"], remote["branch"], theirs[:12]))


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
