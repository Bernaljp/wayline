"""The evolve loop (Implementation Decisions 12): feedback, change records, harness tickets, fixtures, promotion, tags. Built by tickets 45 and 46.

Ticket 46 builds the part that moves harness versions, so that every global change is versioned and
can be undone:

- **Tags and the changelog.** The harness repository is tagged `vMAJOR.MINOR.PATCH` on every global
  change, and `CHANGELOG.md` carries one `## vMAJOR.MINOR.PATCH (date)` entry per tag. Work merged
  since the last tag collects under `## Unreleased`, and the release step renames that heading.
- **The pin.** `harness.json.harness_tag` is the tag a project runs against. `wayline run` refuses
  to start when the harness checkout is not at that tag (`pin_problem`), and names the `upgrade`
  command that fixes it. `WAYLINE_UNPINNED=1` skips the check. It exists for the harness's own
  suite and its development checkout, which run between tags by construction.
- **Upgrade and rollback.** `wayline upgrade [--to <tag>]` checks the harness repository out at
  the tag (detached), repins the project (`project.repin`: the pin, the CLAUDE.md block, the skill
  and workflow symlinks, one commit), prints the changelog entries between the two tags, and
  journals `pinned` with `previous`. A rollback is `upgrade --to` an older tag.
- **Promotion.** `wayline promote skill|role|policy <name>` copies a project's local artifact and
  its fixtures onto the branch `promote/<name>`. The branch is checked out as a worktree of the
  harness repository under `~/.wayline/worktrees/`, so the owner's checkout is never touched. The
  command then runs the harness tests and the full fixture suite there. The same command, run again
  once the owner has merged the branch into the harness `main`, tags the result and journals
  `tagged`. Before the merge it only says that it is waiting. The decision is always the owner's.
  `promotion_candidates` is what the evolver's retrospective reads to recommend a promotion.

Every git operation runs as a subprocess against a harness root that defaults to this checkout, and
every function takes that root as an argument, which is how the tests stand a temporary repository
in for the harness.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from wayline import HARNESS_ROOT, fixtures, pacing, project as projects, registry, worker
from wayline.cli import parse_args
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import K_PREVIOUS, K_TAG, PINNED, TAGGED, Ledger, conductor_holder

__all__ = [
    "EvolveError", "UNPINNED_ENV", "KINDS", "PROMOTE_AFTER_TICKETS",
    "parse_tag", "next_tag", "harness_tags", "tags_at_head", "pin_problem",
    "changelog_entries", "entries_between", "upgrade", "render_upgrade", "upgrade_command", "migrate_difficulty", "nearest_rung",
    "main_branch", "promote", "run_check", "run_checks", "render_promotion", "promote_command",
    "git", "identity", "exists", "worktree_path", "add_unreleased", "release",
    "promotion_candidates", "render_recommendations",
]

UNPINNED_ENV = "WAYLINE_UNPINNED"
CHANGELOG = "CHANGELOG.md"
VERSION_FILE = "wayline/__init__.py"
UNRELEASED = "Unreleased"
PROMOTE_PREFIX = "promote/"
WORKTREES = "worktrees"                  # <home>/worktrees/promote-<name>/, release-<tag>/
KINDS = ("skill", "role", "policy")
# The evolver recommends promoting a local skill once it has passed this many tickets on the
# first attempt and failed none (spec decision: "good over several tickets").
PROMOTE_AFTER_TICKETS = 3
CHECK_TAIL_LINES = 20

_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)\Z")
_HEADING_RE = re.compile(r"^## (\S+)(.*)$", re.MULTILINE)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\Z")
_VERSION_RE = re.compile(r'^__version__ = "[^"]*"', re.MULTILINE)
_LOCAL_ROLE_RE = re.compile(r"^\.claude/agents/([a-z0-9][a-z0-9-]*)\.md\Z")
_IDENTITY = ["-c", "user.name=wayline", "-c", "user.email=wayline@localhost"]


class EvolveError(ValueError):
    """A version move or a promotion the harness refuses, with what to do instead."""


# --- git ---------------------------------------------------------------------------------------------


def _git(root, *args, ok=0):
    """`git -C root args`; raises unless it exits `ok` (None accepts any exit)."""
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if ok is not None and done.returncode != ok:
        raise EvolveError("git %s failed in %s: %s" % (" ".join(args), root, (done.stderr or done.stdout).strip()))
    return done


def _identity(root):
    """No identity flags when git has one configured; the harness's own otherwise, so a commit never fails on it."""
    return [] if _git(root, "config", "user.email", ok=None).stdout.strip() else list(_IDENTITY)


def _exists(root, revision):
    return _git(root, "rev-parse", "--verify", "--quiet", revision, ok=None).returncode == 0


def _tracked_changes(root):
    return [line[3:] for line in _git(root, "status", "--porcelain", "--untracked-files=no").stdout.splitlines() if line]


# --- tags -------------------------------------------------------------------------------------------


def parse_tag(tag):
    """`(major, minor, patch)` for a `vMAJOR.MINOR.PATCH` tag, None for anything else."""
    match = _TAG_RE.match(str(tag or ""))
    return tuple(int(part) for part in match.groups()) if match else None


def next_tag(latest):
    """The next minor tag after `latest` (a promotion adds a capability), or `v0.1.0` after none."""
    if latest is None:
        return "v0.1.0"
    major, minor, _ = parse_tag(latest)
    return "v%d.%d.0" % (major, minor + 1)


def _sorted_tags(lines):
    return sorted({line.strip() for line in lines if parse_tag(line.strip())}, key=parse_tag)


def harness_tags(harness_root=None):
    """Every version tag of the harness repository, oldest first; [] when it has none or is no repository."""
    done = _git(harness_root or HARNESS_ROOT, "tag", "--list", "v*", ok=None)
    return _sorted_tags(done.stdout.splitlines()) if done.returncode == 0 else []


def tags_at_head(harness_root=None):
    """The version tags on the checkout's commit, oldest first; None when the harness is no git checkout.

    Decision 5 phrases the check as `git describe --tags --exact-match`. That command names only one
    tag, so a commit carrying two tags would be checked against whichever it picked. This lists all
    of them instead.
    """
    done = _git(harness_root or HARNESS_ROOT, "tag", "--points-at", "HEAD", ok=None)
    return _sorted_tags(done.stdout.splitlines()) if done.returncode == 0 else None


def pin_problem(project, harness_root=None, environ=None):
    """Why `run` must not start against this harness checkout, with the command that fixes it; None when it may."""
    environ = os.environ if environ is None else environ
    if environ.get(UNPINNED_ENV):
        return None
    harness_root = Path(harness_root or HARNESS_ROOT)
    project = Path(project)
    pin = projects.read_harness(project)["harness_tag"]
    at = tags_at_head(harness_root)
    if at is None:
        return ("the harness at %s is not a git checkout, so it cannot be at the project's pin %s; "
                "run wayline from a clone of the harness repository" % (harness_root, pin))
    if pin in at:
        return None
    known = harness_tags(harness_root)
    if pin not in known:
        return ("the project pins the harness tag %s, and the harness repository %s has no such tag: run wayline upgrade --project %s "
                "to pin its latest tag%s" % (pin, harness_root, project, " (%s)" % known[-1] if known else ""))
    problem = ("the harness checkout %s is %s, and the project pins %s: run wayline upgrade --to %s --project %s to put the checkout back at the pin"
               % (harness_root, "at " + ", ".join(at) if at else "on no tag", pin, pin, project))
    if at:
        problem += ", or wayline upgrade --to %s --project %s to move the project to the checkout's tag" % (at[-1], project)
    return problem


# --- the changelog ----------------------------------------------------------------------------------


def changelog_entries(text):
    """`{tag: entry}` for every `## vMAJOR.MINOR.PATCH` heading, in file order; the entry runs to the next `## ` heading."""
    matches = list(_HEADING_RE.finditer(text))
    entries = {}
    for index, match in enumerate(matches):
        if parse_tag(match.group(1)) is None:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        entries.setdefault(match.group(1), text[match.start():end].rstrip() + "\n")
    return entries


def entries_between(text, one, other):
    """`[(tag, entry)]` for the tags after the older of two tags up to the newer, newest first.

    The same list serves both directions: an upgrade brings these entries, a rollback leaves them behind.
    """
    low, high = sorted((parse_tag(one), parse_tag(other)))
    found = [(tag, entry) for tag, entry in changelog_entries(text).items() if low < parse_tag(tag) <= high]
    return sorted(found, key=lambda item: parse_tag(item[0]), reverse=True)


def _changelog_at(harness_root, tag):
    """`CHANGELOG.md` as the tag has it, else as the checkout has it, else empty."""
    shown = _git(harness_root, "show", "%s:%s" % (tag, CHANGELOG), ok=None)
    if shown.returncode == 0:
        return shown.stdout
    path = Path(harness_root) / CHANGELOG
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _policy_at(harness_root, tag):
    """`policy.json` as the tag has it, or None when the tag carries none or it does not parse."""
    shown = _git(harness_root, "show", "%s:policy.json" % tag, ok=None)
    if shown.returncode != 0:
        return None
    try:
        value = json.loads(shown.stdout)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _add_unreleased(text, paragraph):
    """Add a paragraph at the end of `## Unreleased`, opening that section above the first entry when there is none."""
    matches = list(_HEADING_RE.finditer(text))
    unreleased = next((match for match in matches if match.group(1) == UNRELEASED), None)
    if unreleased is None:
        where = matches[0].start() if matches else len(text)
        head = text[:where] if not matches or text[:where].endswith("\n\n") else text[:where].rstrip("\n") + "\n\n"
        return head + "## %s\n\n%s\n\n" % (UNRELEASED, paragraph) + text[where:]
    following = next((match for match in matches if match.start() > unreleased.start()), None)
    end = following.start() if following else len(text)
    section = text[unreleased.start():end].rstrip("\n")
    return text[:unreleased.start()] + section + "\n\n" + paragraph + "\n\n" + text[end:].lstrip("\n")


def _release_changelog(text, tag, date):
    """Rename `## Unreleased` to the tag's entry; refuses a changelog with nothing released under the tag."""
    for match in _HEADING_RE.finditer(text):
        if match.group(1) == UNRELEASED:
            return text[:match.start()] + "## %s (%s)" % (tag, date) + text[match.end():]
    raise EvolveError("%s has no `## %s` section and no `## %s` entry, and a tag carries one entry (write it, then run again)"
                      % (CHANGELOG, UNRELEASED, tag))


# --- upgrade and rollback -------------------------------------------------------------------------


def upgrade(project, to=None, harness_root=None):
    """Move a project to another harness tag, the latest by default; an older tag rolls it back.

    Returns `{project, harness_root, previous, tag, direction, entries, changes, notes}`, where
    `direction` is `upgrade`, `rollback`, or `unchanged` (the checkout was put back at the pin).
    """
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    project = Path(project).resolve()
    previous = projects.read_harness(project)["harness_tag"]
    tags = harness_tags(harness_root)
    if not tags:
        raise EvolveError("the harness repository %s has no vMAJOR.MINOR.PATCH tag to pin" % harness_root)
    target = tags[-1] if to is None else to
    if target not in tags:
        spelled = "" if parse_tag(target) else " (tags are spelled vMAJOR.MINOR.PATCH)"
        raise EvolveError("the harness repository %s has no tag %s%s; it has %s" % (harness_root, target, spelled, ", ".join(tags)))
    # Every project runs from this one checkout, so a conductor on any of them holds it, not only on this one.
    registered = [Path(entry["path"]) for entry in projects.read_projects() if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
    for candidate in dict.fromkeys([project] + registered):
        try:
            holder = conductor_holder(candidate) if projects.is_project(candidate) else None
        except OSError:
            holder = None
        if holder is not None:
            raise EvolveError("a conductor (pid %s) is running on %s against the harness checkout; run wayline stop --project %s, then upgrade"
                              % (holder.get("pid", "?"), candidate, candidate))
    # The pin commit takes these two files whole, so an owner's unfinished edit to either would ride along in it.
    edited = _git(project, "status", "--porcelain", "--", projects.HARNESS_JSON, projects.CLAUDE_MD, ok=None)
    if edited.returncode == 0 and edited.stdout.strip():
        raise EvolveError("%s has uncommitted changes to %s, which the upgrade rewrites and commits; commit or stash them, then upgrade"
                          % (project, ", ".join(line[3:] for line in edited.stdout.splitlines() if line)))

    notes = []
    # The migration of decision 16 is resolved against the target's ladder here, before the checkout moves, so a refusal
    # leaves the checkout and every pin where they were; `rewrite` applies the same resolution once the pin is written.
    # The pinned tag's ladder is what the override's rung indices were written against (ticket 70).
    ladder_policy = _policy_at(harness_root, target)
    pinned = ((_policy_at(harness_root, previous) or {}) if previous != target else ladder_policy, previous)
    if ladder_policy is None:
        migration = ([], "the harness at %s has no policy.json to read a rung ladder from; the override is left as it is" % target)
    elif not ladder_policy.get("tiers"):
        migration = ([], "the harness at %s has no rung ladder (no policy.tiers); the override is left as it is" % target)
    else:
        harness = projects.read_harness(project)
        migration = migrate_difficulty(harness, projects.merge_policy(ladder_policy, harness.get("policy")), pinned)
    if target not in (tags_at_head(harness_root) or []):
        dirty = _tracked_changes(harness_root)
        if dirty:
            raise EvolveError("the harness checkout %s has uncommitted changes (%s); commit or stash them before it moves to %s"
                              % (harness_root, ", ".join(dirty[:5]), target))
        _git(harness_root, "checkout", "--quiet", "--detach", target + "^{commit}")
        notes.append("the harness checkout %s is now at %s (detached)" % (harness_root, target))
    migrated, note = migration
    if note:
        notes.append(note)

    def rewrite(value):
        if not migrated:
            return False
        lines, _ = migrate_difficulty(value, projects.merge_policy(ladder_policy, value.get("policy")), pinned)
        return bool(lines)

    changes, repinned = projects.repin(project, target, harness_root, rewrite=rewrite)
    notes.extend(repinned)

    direction, entries = "unchanged", []
    if target != previous:
        direction = "upgrade" if parse_tag(target) > parse_tag(previous) else "rollback"
        newer = max(target, previous, key=parse_tag)
        entries = entries_between(_changelog_at(harness_root, newer), previous, target)
        Ledger(project).append_event(PINNED, {K_TAG: target, K_PREVIOUS: previous})
    for entry in projects.read_projects():
        if isinstance(entry, dict) and entry.get("path") != str(project) and entry.get("harness_tag") not in (None, target):
            notes.append("the project %s pins %s, so its next run is refused against this checkout until wayline upgrade --project %s"
                         % (entry["path"], entry["harness_tag"], entry["path"]))
    return {"project": str(project), "harness_root": str(harness_root), "previous": previous, "tag": target,
            "direction": direction, "entries": entries, "changes": changes, "notes": notes, "migrated": migrated}


# --- the migration to the rung ladder (decision 16) ---------------------------------------------------

# The efforts in the launcher's order; the cap holds ticket work at `high`, so an old level above it lands on a rung at `high`.
_EFFORT_RANK = {effort: rank for rank, effort in enumerate(worker.EFFORTS)}
CAP = "high"


def nearest_rung(rungs, model, effort):
    """The 1-based index of the rung whose model family matches `model` and whose effort is nearest `effort` under the cap.

    An effort above `high` is taken as `high` first (the cap). Of two rungs at the same distance the higher
    one is taken, so `sonnet medium` lands on `sonnet high`, where the shipped map puts level 2. A family no
    rung is on takes the top rung on a cheaper family, never a dearer one: the shipped ladder has no Fable
    rung since ticket 70, and a level that was on Fable lands on its top rung, `opus high`. None when no rung
    is on the model's family or a cheaper one, or the model is none of the families; an effort the launcher
    does not know, the level's or a rung's, is refused.
    """
    if effort not in _EFFORT_RANK:
        raise EvolveError("the effort %r is none of %s" % (effort, ", ".join(worker.EFFORTS)))
    family = pacing.family(model)
    wanted = min(_EFFORT_RANK[effort], _EFFORT_RANK[CAP])
    best, cheaper = None, None
    for index, rung in enumerate(rungs, start=1):
        rung_family = pacing.family(rung.get("model")) if isinstance(rung, dict) else None
        if family is None or rung_family is None:
            continue
        if rung_family != family:
            if pacing.FAMILIES.index(rung_family) < pacing.FAMILIES.index(family):
                cheaper = index
            continue
        if rung.get("effort") not in _EFFORT_RANK:
            raise EvolveError("policy.tiers rung %d has the effort %r, none of %s" % (index, rung.get("effort"), ", ".join(worker.EFFORTS)))
        distance = abs(_EFFORT_RANK[rung["effort"]] - wanted)
        if best is None or distance <= best[0]:
            best = (distance, index)
    return cheaper if best is None else best[1]


def migrate_difficulty(harness, policy, pinned=None):
    """Rewrite `harness.json`'s `policy.difficulty` override onto the rung ladder of `policy`, in place.

    Returns `(lines, note)`: one line per level rewritten, and the note for a project that had nothing to
    rewrite. `policy.tiers` is the harness's ladder under the project's own override. A level in the old shape
    (a model and an effort, decision 16) takes the rung whose model matches and whose effort is nearest without
    going above `high` (`nearest_rung`). A level already naming a rung was written against the ladder of the tag
    the project was pinned to: `pinned` is `(that tag's policy, the tag)`, and the level takes the rung of the
    new ladder its old rung's model and effort land on the same way (ticket 70), so a rung that moved is carried
    and one whose index stays is left. A project whose own `policy.tiers` defines its ladder has its rungs left
    as they are. A level on a model no rung carries, or on a rung the pinned ladder lacks, is refused.
    """
    override = (harness.get("policy") or {}).get("difficulty") if isinstance(harness.get("policy"), dict) else None
    if not isinstance(override, dict):
        return [], "harness.json overrides no policy.difficulty; nothing to rewrite to rungs"
    rungs = policy.get("tiers") or []
    lines, note = _carry_rungs(harness, override, rungs, pinned)
    old = projects.old_difficulty_levels(override)
    if not old:
        return lines, None if lines else note
    for level in old:
        entry = override[level]
        model, effort = entry.get("model"), entry.get("effort")
        try:
            rung = nearest_rung(rungs, model, effort)
        except EvolveError as failure:
            raise EvolveError("harness.json's policy.difficulty maps level %s to %s %s: %s; edit the override by hand, then upgrade"
                              % (level, model, effort, failure))
        if rung is None:
            raise EvolveError("harness.json's policy.difficulty maps level %s to %s %s, and no rung of policy.tiers is on that model "
                              "or a cheaper one; edit the override by hand, then upgrade" % (level, model, effort))
        override[level] = rung
        lines.append("difficulty %s: %s %s -> rung %d (%s %s)" % (level, model, effort, rung, rungs[rung - 1]["model"], rungs[rung - 1]["effort"]))
    return lines, None


def _carry_rungs(harness, override, rungs, pinned):
    """Carry the override's levels that name a rung from the pinned tag's ladder onto `rungs`, in place (ticket 70).

    Returns `(lines, note)`: a line for each level whose rung moved or changed model or effort, and the note to
    give when none did.
    """
    unchanged = "harness.json's policy.difficulty override is already a level to rung map; nothing to rewrite"
    named = sorted((level for level, rung in override.items() if isinstance(rung, int) and not isinstance(rung, bool)), key=str)
    if not named or pinned is None:
        return [], unchanged
    if "tiers" in harness["policy"]:
        return [], "harness.json's own policy.tiers defines the project's rung ladder; its policy.difficulty override is left as it is"
    old_policy, tag = pinned
    old_rungs = old_policy.get("tiers") or []
    if not old_rungs:
        return [], "the harness at %s has no rung ladder to read the override's rungs against; they are left as they are" % tag
    if old_rungs == rungs:
        return [], unchanged
    lines = []
    for level in named:
        index = override[level]
        if not 1 <= index <= len(old_rungs) or not isinstance(old_rungs[index - 1], dict):
            raise EvolveError("harness.json's policy.difficulty maps level %s to rung %d, which the rung ladder of %s does not have "
                              "(it has %d rung(s)); edit the override by hand, then upgrade" % (level, index, tag, len(old_rungs)))
        was = old_rungs[index - 1]
        try:
            rung = nearest_rung(rungs, was.get("model"), was.get("effort"))
        except EvolveError as failure:
            raise EvolveError("harness.json's policy.difficulty maps level %s to rung %d of %s, %s %s: %s; edit the override by hand, then upgrade"
                              % (level, index, tag, was.get("model"), was.get("effort"), failure))
        if rung is None:
            raise EvolveError("harness.json's policy.difficulty maps level %s to rung %d of %s, %s %s, and no rung of policy.tiers is on "
                              "that model or a cheaper one; edit the override by hand, then upgrade"
                              % (level, index, tag, was.get("model"), was.get("effort")))
        now = rungs[rung - 1]
        if rung == index and (now.get("model"), now.get("effort")) == (was.get("model"), was.get("effort")):
            continue
        override[level] = rung
        lines.append("difficulty %s: rung %d (%s %s) -> rung %d (%s %s)"
                     % (level, index, was.get("model"), was.get("effort"), rung, now["model"], now["effort"]))
    return lines, unchanged


def render_upgrade(report):
    lines = []
    if report["direction"] == "unchanged":
        lines.append("unchanged  %s stays pinned at %s" % (report["project"], report["tag"]))
    else:
        lines.append("%-9s  %s  %s -> %s" % (report["direction"], report["project"], report["previous"], report["tag"]))
    lines.extend("  wrote  %s" % change for change in report["changes"])
    lines.extend("  %s" % line for line in report.get("migrated") or [])
    if report["entries"]:
        if report["direction"] == "upgrade":
            lines += ["", "changelog  what %s brings since %s:" % (report["tag"], report["previous"]), ""]
        else:
            lines += ["", "changelog  what the rollback to %s leaves behind:" % report["tag"], ""]
        lines.extend(entry for _, entry in report["entries"])
    lines.extend("note  %s" % note for note in report["notes"])
    return "\n".join(lines)


def upgrade_command(args):
    """`wayline upgrade [--to <tag>] [--project <path>]`."""
    parser = argparse.ArgumentParser(prog="wayline upgrade",
                                     description="move the project to another harness tag; --to an older tag rolls it back")
    parser.add_argument("--to", metavar="TAG", help="the tag to pin (default: the harness repository's latest)")
    parser.add_argument("--project", help="the project to move; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        report = upgrade(projects.find_project(options.project), to=options.to, harness_root=HARNESS_ROOT)
    except (EvolveError, projects.ProjectError, ValidationError, OSError) as failure:
        print("wayline upgrade: %s" % failure, file=sys.stderr)
        return 1
    print(render_upgrade(report))
    return 0


# --- promotion: what moves ----------------------------------------------------------------------------


def _harness_path(relative):
    """Where a project-relative artifact path lives in the harness: `.claude/skills/x/...`, `.claude/agents/r.md`, `harness.json`."""
    if relative.startswith(".claude/skills/"):
        return relative[len(".claude/"):]
    match = _LOCAL_ROLE_RE.match(relative)
    if match:
        return "roles/%s/agent.md" % match.group(1)
    if relative == projects.HARNESS_JSON:
        return "policy.json"
    return relative


def _within(path, local):
    return path.startswith(local) if local.endswith("/") else path == local


def _merged(base, override):
    """The project's override over the harness value, dicts merged key by key, as `policy_for` reads them."""
    if not (isinstance(base, dict) and isinstance(override, dict)):
        return override
    value = dict(base)
    for key, item in override.items():
        value[key] = _merged(value.get(key), item)
    return value


def _replace_value(text, key, value):
    """`policy.json` with one top-level key's value replaced in place, every other line as the owner spelled it."""
    match = re.search(r'^  "%s"\s*:\s*' % re.escape(key), text, flags=re.MULTILINE)
    if match is None:
        raise EvolveError("policy.json has no top-level key %r" % key)
    _, end = json.JSONDecoder().raw_decode(text, match.end())
    if "\n" in text[match.end():end]:
        rendered = json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\n  ")
    else:
        rendered = json.dumps(value, ensure_ascii=False)
    return text[:match.end()] + rendered + text[end:]


class _Plan:
    """What a promotion writes into the worktree, computed before any branch exists so a refusal leaves none behind."""

    def __init__(self, kind, name, local):
        self.kind, self.name, self.local = kind, name, local
        self.removes, self.writes, self.stamps, self.records = [], {}, [], []
        self.fixture_ids, self.notes = [], []

    def apply(self, worktree):
        for relative in self.removes:
            shutil.rmtree(worktree / relative, ignore_errors=True)
        for relative, data in sorted(self.writes.items()):
            target = worktree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for relative, make_global in self.stamps:
            _stamp_sidecar(worktree / relative, make_global)
        for relative, record, old_hash in self.records:
            new_hash = fixtures.subject_sha256(record, worktree)
            for holder in (record["subject"], record.get("baseline"), record.get("last_run")):
                if isinstance(holder, dict):
                    key = "sha256" if holder is record["subject"] else "subject_sha256"
                    if holder.get(key) == old_hash:
                        holder[key] = new_hash
            (worktree / relative).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stamp_sidecar(directory, make_global):
    """Restamp a sidecar's `sha256` from the files beside it; a promoted skill's sidecar also becomes `global`.

    A role's sidecar is the harness's own file and keeps its spelling (one textual substitution, as
    `registry.stamp_sidecars` does). A skill's sidecar arrives from the project and is written out whole.
    """
    path = directory / registry.SIDECAR
    text = path.read_text(encoding="utf-8")
    computed = registry.content_sha256(directory)
    value = json.loads(text)
    if make_global or not re.search(r'"sha256"\s*:\s*"[0-9a-f]{64}"', text):
        value.update(scope_kind="global", sha256=computed) if make_global else value.update(sha256=computed)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif value.get("sha256") != computed:
        path.write_text(re.sub(r'("sha256"\s*:\s*)"[0-9a-f]{64}"', lambda match: match.group(1) + '"%s"' % computed, text, count=1),
                        encoding="utf-8")


def _files(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(Path(directory).rglob("*"))
            if path.is_file() and "__pycache__" not in path.relative_to(directory).parts}


def _normal_name(kind, name):
    if kind == "skill" and not name.startswith(registry.SKILL_PREFIX):
        name = registry.SKILL_PREFIX + name
    if not _NAME_RE.match(name):
        raise EvolveError("%r is not a %s name (lowercase letters, digits, dashes, and underscores)" % (name, kind))
    return name


def _plan(kind, name, project, harness_root, main):
    if kind == "skill":
        source = project / registry.LOCAL_SKILLS / name
        if source.is_symlink():
            raise EvolveError("%s is a link to a harness skill, not a local one; there is nothing to promote" % source)
        if not (source / registry.SKILL_FILE).is_file():
            raise EvolveError("the project has no local skill %s (no %s)" % (name, source / registry.SKILL_FILE))
        try:
            sidecar = registry.read_sidecar(source / registry.SIDECAR, "skill", expect_id=name[len(registry.SKILL_PREFIX):])
        except registry.RegistryError as failure:
            raise EvolveError("the local skill %s has no sidecar the registry accepts: %s" % (name, failure)) from None
        plan = _Plan(kind, name, "%s/%s/" % (registry.LOCAL_SKILLS, name))
        destination = "%s/%s" % (registry.HARNESS_SKILLS, name)
        plan.removes.append(destination)
        plan.writes.update({"%s/%s" % (destination, relative): data for relative, data in _files(source).items()})
        plan.stamps.append((destination, True))
        explicit = sidecar["fixtures"]
    elif kind == "role":
        source = project / registry.LOCAL_ROLES / (name + ".md")
        if source.is_symlink() or not source.is_file():
            raise EvolveError("the project has no local role override %s" % source)
        if not _exists(harness_root, "%s:%s/%s/%s" % (main, registry.HARNESS_ROLES, name, registry.SIDECAR)):
            raise EvolveError("the harness %s has no roles/%s/%s, and a role's tool lists are the harness's to write: "
                              "add the role to the harness first, then promote its prompt" % (main, name, registry.SIDECAR))
        plan = _Plan(kind, name, "%s/%s.md" % (registry.LOCAL_ROLES, name))
        plan.writes["%s/%s/%s" % (registry.HARNESS_ROLES, name, registry.ROLE_FILE)] = source.read_bytes()
        plan.stamps.append(("%s/%s" % (registry.HARNESS_ROLES, name), False))
        explicit = []
    else:
        overrides = projects.read_harness(project).get("policy") or {}
        if name not in overrides:
            raise EvolveError("the project's harness.json overrides no policy key %r (it overrides %s)"
                              % (name, ", ".join(sorted(overrides)) or "none"))
        text = _git(harness_root, "show", "%s:policy.json" % main).stdout
        base = json.loads(text)
        if name not in base:
            raise EvolveError("the harness policy.json has no key %r; a new policy key is a schema change, not a promotion" % name)
        promoted = _replace_value(text, name, _merged(base[name], overrides[name]))
        try:
            check(json.loads(promoted), load_schema("policy"), name="policy.json with %s promoted" % name)
        except ValidationError as failure:
            raise EvolveError(str(failure)) from None
        plan = _Plan(kind, name, projects.HARNESS_JSON)
        plan.writes["policy.json"] = promoted.encode("utf-8")
        explicit = []
    _plan_fixtures(plan, explicit, project, harness_root, main)
    return plan


def _plan_fixtures(plan, explicit, project, harness_root, main):
    """The artifact's fixtures: the ids its sidecar names, and every project fixture whose subject is the artifact."""
    wanted = list(explicit)
    for directory in fixtures.discover(project):
        try:
            record = json.loads((directory / "fixture.json").read_text(encoding="utf-8"))
            subject = record["subject"]
            paths = [subject["path"]] + list(subject.get("also") or [])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if any(_within(path, plan.local) for path in paths):
            wanted.append(fixtures.fixture_id(directory))
    for identifier in dict.fromkeys(wanted):
        source = project / fixtures.FIXTURES / identifier
        if not (source / "fixture.json").is_file():
            where = "is already in the harness" if _exists(harness_root, "%s:fixtures/%s/fixture.json" % (main, identifier)) \
                else "is in neither the project nor the harness %s" % main
            plan.notes.append("the fixture %s %s" % (identifier, where))
            continue
        record = json.loads((source / "fixture.json").read_text(encoding="utf-8"))
        old_hash = fixtures.subject_sha256(record, project)
        destination = "%s/%s" % (fixtures.FIXTURES, identifier)
        plan.removes.append(destination)
        for relative, data in _files(source).items():
            if relative == "fixture.json" or relative.split("/")[0] == "runs":  # runs/ is per machine and gitignored
                continue
            if relative.startswith("input/subject/"):
                relative = "input/subject/" + _harness_path(relative[len("input/subject/"):])
            plan.writes["%s/%s" % (destination, relative)] = data
        record["subject"]["path"] = _harness_path(record["subject"]["path"])
        if record["subject"].get("also"):
            record["subject"]["also"] = [_harness_path(path) for path in record["subject"]["also"]]
        plan.records.append(("%s/fixture.json" % destination, record, old_hash))
        plan.fixture_ids.append(identifier)


# --- promotion: the branch, the checks, the tag ----------------------------------------------------------


def main_branch(harness_root=None):
    """The harness's integration branch: `main`, or `master` in a repository that predates the name."""
    for name in ("main", "master"):
        if _exists(harness_root or HARNESS_ROOT, "refs/heads/" + name):
            return name
    raise EvolveError("the harness repository %s has neither a main nor a master branch to promote into" % (harness_root or HARNESS_ROOT))


def run_check(argv, cwd):
    """Run one check in the promotion worktree: `(exit code, output)`."""
    done = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _worktree(name):
    return projects.home() / WORKTREES / name


def _checkout_of(harness_root, branch):
    """The worktree of the harness repository that has `branch` checked out, or None."""
    path = None
    for line in _git(harness_root, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line == "branch refs/heads/" + branch:
            return path
    return None


def _integrated(harness_root, tip, main):
    """How `main` holds the promotion commit `tip`: `ancestor` (merged), `content` (squashed or rebased), or None.

    A squash or rebase merge leaves the branch tip out of `main`'s history, so the promotion also
    counts as integrated when `main` holds every file the promotion commit wrote exactly as the
    branch has it. `CHANGELOG.md` is left out of that comparison, because other entries may have
    landed beside the promotion's paragraph.
    """
    if _git(harness_root, "merge-base", "--is-ancestor", tip, main, ok=None).returncode == 0:
        return "ancestor"
    written = [path for path in _git(harness_root, "diff", "--name-only", tip + "^", tip).stdout.splitlines() if path and path != CHANGELOG]
    if written and _git(harness_root, "diff", "--quiet", tip, main, "--", *written, ok=None).returncode == 0:
        return "content"
    return None


def _remove_promotion(harness_root, branch, worktree):
    """Drop the promotion worktree and its branch: the branch is merged and tagged, or it was never committed."""
    if Path(worktree).exists():
        _git(harness_root, "worktree", "remove", "--force", str(worktree), ok=None)
    _git(harness_root, "worktree", "prune", ok=None)
    if _exists(harness_root, "refs/heads/" + branch):
        _git(harness_root, "branch", "-D", branch)


def promote(kind, name, project, harness_root=None, tag=None, run=None):
    """Promote a local skill, role, or policy key into the harness, one step per call.

    The first call opens `promote/<name>` and runs the checks (`state: branched`). A call before the
    owner has merged the branch changes nothing (`state: waiting`). A call after the merge tags the
    harness `main` and journals `tagged` (`state: tagged`); `tag` names the tag, the next minor by default.
    """
    if kind not in KINDS:
        raise EvolveError("promote takes one of %s, got %r" % (", ".join(KINDS), kind))
    if tag is not None and parse_tag(tag) is None:
        raise EvolveError("%r is not a tag; tags are spelled vMAJOR.MINOR.PATCH" % tag)
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    project = Path(project).resolve()
    name = _normal_name(kind, name)
    main = main_branch(harness_root)
    branch = PROMOTE_PREFIX + name
    worktree = _worktree("promote-" + name)
    base = {"kind": kind, "name": name, "branch": branch, "worktree": str(worktree), "main": main}

    if _exists(harness_root, "refs/heads/" + branch):
        tip = _git(harness_root, "rev-parse", branch).stdout.strip()
        state = _integrated(harness_root, tip, main)
        if state is None:
            return dict(base, state="waiting", next=[
                "review %s and merge it into the harness %s; then run wayline promote %s %s again, and it tags the result "
                "(the local %s must hold it: after a merge on GitHub, pull it first; a squash or rebase merge counts once "
                "%s holds the promoted files as the branch has them)" % (branch, main, kind, name, main, main)])
        if state == "ancestor":
            released = _sorted_tags(_git(harness_root, "tag", "--contains", tip).stdout.splitlines())
        else:  # a squash or rebase merge: the promoted content is on main, and a tag at main's head already covers it
            released = _sorted_tags(_git(harness_root, "tag", "--points-at", main).stdout.splitlines())
        if not released:
            return _release(harness_root, main, tag, project, base)
        _remove_promotion(harness_root, branch, worktree)  # merged and tagged already: a new promotion starts afresh
    return _branch(harness_root, main, project, base, run or run_check)


def run_checks(worktree, run=None):
    """The harness tests and the full fixture suite, run in a worktree of the harness repository: what gates every global change."""
    checks = []
    for check_name, argv in (("tests", [sys.executable, "-m", "unittest"]),
                             ("fixtures", [sys.executable, "-m", "wayline", "fixture", "run", "--suite", "--root", str(worktree)])):
        code, output = (run or run_check)(argv, worktree)
        checks.append({"name": check_name, "command": argv, "exit_code": code,
                       "tail": "\n".join(output.splitlines()[-CHECK_TAIL_LINES:])})
    return checks


def _branch(harness_root, main, project, base, run):
    kind, name, branch, worktree = base["kind"], base["name"], base["branch"], Path(base["worktree"])
    plan = _plan(kind, name, project, harness_root, main)
    _git(harness_root, "worktree", "prune", ok=None)
    if worktree.exists():
        raise EvolveError("%s is in the way of the promotion worktree; remove it, then run again" % worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(harness_root, "worktree", "add", "--quiet", "-b", branch, str(worktree), main)
    try:
        plan.apply(worktree)
        if not _git(worktree, "status", "--porcelain").stdout.strip():
            raise EvolveError("nothing to promote: the harness %s already holds the local %s %s as it is" % (main, kind, name))
        with_fixtures = (" with its fixture%s %s" % ("s" if len(plan.fixture_ids) > 1 else "", ", ".join("`%s`" % item for item in plan.fixture_ids))
                         if plan.fixture_ids else ", with no fixture")
        paragraph = "- Promoted the local %s `%s` from the project `%s`%s (`wayline promote`)." % (kind, name, project.name, with_fixtures)
        changelog = worktree / CHANGELOG
        changelog.write_text(_add_unreleased(changelog.read_text(encoding="utf-8") if changelog.is_file() else "", paragraph), encoding="utf-8")
        _git(worktree, "add", "-A")
        _git(worktree, *_identity(worktree), "commit", "-q", "-m", "Promote the local %s %s from %s" % (kind, name, project.name))
    except BaseException:
        _remove_promotion(harness_root, branch, worktree)
        raise
    commit = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    checks = run_checks(worktree, run)
    return dict(base, state="branched", commit=commit, checks=checks, passed=all(item["exit_code"] == 0 for item in checks),
                fixtures=plan.fixture_ids, notes=plan.notes, next=[
                    "review %s and merge it into the harness %s; then run wayline promote %s %s again, and it tags the result"
                    % (branch, main, kind, name)])


def _release(harness_root, main, tag, project, base):
    """Tag the harness `main` that now holds the promotion: the changelog entry, the package version, the tag, `tagged`."""
    tags = harness_tags(harness_root)
    latest = tags[-1] if tags else None
    tag = tag or next_tag(latest)
    if tag in tags or (latest is not None and parse_tag(tag) <= parse_tag(latest)):
        raise EvolveError("the tag %s is not past the harness's latest tag %s" % (tag, latest))
    place, temporary = _checkout_of(harness_root, main), None
    if place is None:
        temporary = _worktree("release-" + tag)
        _git(harness_root, "worktree", "prune", ok=None)
        if temporary.exists():
            raise EvolveError("%s is in the way of the release worktree; remove it, then run again" % temporary)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        _git(harness_root, "worktree", "add", "--quiet", str(temporary), main)
        place = temporary
    try:
        dirty = _tracked_changes(place)
        if dirty:
            raise EvolveError("%s has %s checked out with uncommitted changes (%s); commit or stash them, then run again"
                              % (place, main, ", ".join(dirty[:5])))
        written = []
        changelog = place / CHANGELOG
        text = changelog.read_text(encoding="utf-8") if changelog.is_file() else ""
        if tag not in changelog_entries(text):
            changelog.write_text(_release_changelog(text, tag, datetime.now(timezone.utc).strftime("%Y-%m-%d")), encoding="utf-8")
            written.append(CHANGELOG)
        version = place / VERSION_FILE
        if version.is_file():
            source = version.read_text(encoding="utf-8")
            bumped = _VERSION_RE.sub('__version__ = "%s"' % tag[1:], source, count=1)
            if bumped != source:
                version.write_text(bumped, encoding="utf-8")
                written.append(VERSION_FILE)
        identity = _identity(place)
        if written:
            _git(place, "add", "--", *written)
            _git(place, *identity, "commit", "-q", "-m", "Release %s" % tag, "--", *written)
        _git(place, *identity, "tag", "-a", tag, "-m", "wayline %s" % tag)
    finally:
        if temporary is not None:
            _git(harness_root, "worktree", "remove", "--force", str(temporary), ok=None)
    Ledger(project).append_event(TAGGED, {K_TAG: tag})
    _remove_promotion(harness_root, base["branch"], Path(base["worktree"]))
    return dict(base, state="tagged", tag=tag, next=["wayline upgrade --to %s --project %s pins the new tag for this project" % (tag, project)])


def render_promotion(report):
    state = report["state"]
    if state == "waiting":
        lines = ["waiting  %s is not merged into the harness %s yet" % (report["branch"], report["main"])]
    elif state == "tagged":
        lines = ["tagged   %s on the harness %s, which holds %s; the branch and its worktree are removed" % (report["tag"], report["main"], report["branch"])]
    else:
        lines = ["branched %s from the harness %s at %s, in %s" % (report["branch"], report["main"], report["commit"][:12], report["worktree"])]
        if report["fixtures"]:
            lines.append("  fixtures  %s" % ", ".join(report["fixtures"]))
        for item in report["checks"]:
            if item["exit_code"] == 0:
                verdict = "pass"
            elif item["name"] == "fixtures" and item["exit_code"] == fixtures.EXIT_COST:
                verdict = "stopped for cost (exit 2): partial results; run it again in the worktree when the window allows"
            else:
                verdict = "FAIL (exit %d)" % item["exit_code"]
            lines.append("  %-8s  %s  (%s)" % (item["name"], verdict, " ".join(item["command"][1:])))
            if item["exit_code"] != 0 and item["tail"]:
                lines.extend("    | " + line for line in item["tail"].splitlines())
        lines.extend("note  %s" % note for note in report["notes"])
    lines.extend("next  %s" % step for step in report["next"])
    return "\n".join(lines)


def promote_command(args):
    """`wayline promote skill|role|policy <name> [--tag <tag>] [--project <path>]`."""
    parser = argparse.ArgumentParser(prog="wayline promote",
                                     description="move a local skill, role, or policy key into the harness on promote/<name>; "
                                                 "run it again after merging the branch to tag the result")
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("name", help="the skill (with or without the wayline- prefix), the role, or the policy key")
    parser.add_argument("--tag", help="the tag to make once main holds the promotion (default: the next minor tag)")
    parser.add_argument("--project", help="the project the local artifact is in; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        report = promote(options.kind, options.name, projects.find_project(options.project), harness_root=HARNESS_ROOT, tag=options.tag)
    except (EvolveError, projects.ProjectError, registry.RegistryError, ValidationError, OSError, ValueError) as failure:
        print("wayline promote: %s" % failure, file=sys.stderr)
        return 1
    print(render_promotion(report))
    return 1 if report["state"] == "branched" and not report["passed"] else 0


# What `wayline.changes` (ticket 45) shares with a promotion: a global change is branched from the harness `main`
# into a worktree under `~/.wayline/worktrees/`, checked there, and tagged once `main` holds it, the same way.
git, identity, exists, worktree_path, add_unreleased, release = _git, _identity, _exists, _worktree, _add_unreleased, _release


# --- the recommendation -----------------------------------------------------------------------------


def promotion_candidates(registry_value, after=PROMOTE_AFTER_TICKETS):
    """The local skills whose outcome record is good over several tickets: `after` first-time passes and no failure.

    What the evolver's retrospective recommends; it recommends and never promotes.
    """
    candidates = []
    for entry in registry_value.get("entries") or []:
        outcome = entry.get("outcome") or {}
        if entry.get("kind") != "skill" or entry.get("scope_kind") != "local":
            continue
        if outcome.get("failed", 0) or outcome.get("passed_first_time", 0) < after:
            continue
        candidates.append({"id": entry["id"], "assigned": outcome.get("assigned", 0), "passed_first_time": outcome["passed_first_time"],
                           "failed": 0, "command": "wayline promote skill %s%s" % (registry.SKILL_PREFIX, entry["id"])})
    return sorted(candidates, key=lambda item: (-item["passed_first_time"], item["id"]))


def render_recommendations(candidates):
    """The retrospective's lines for the candidates; none when there is nothing to recommend."""
    if not candidates:
        return []
    lines = ["Local skills with a good record, which the owner may promote into the harness (nothing is promoted until they run the command):"]
    lines.extend("- `%s%s`: %d of %d launches passed on the first attempt, none failed: `%s`" % (
        registry.SKILL_PREFIX, item["id"], item["passed_first_time"], item["assigned"], item["command"]) for item in candidates)
    return lines
