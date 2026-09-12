"""The registry of skills and roles, and the librarian (Implementation Decisions 10).

Every skill and role either scope holds is registered by code, never by hand: `wayline registry
build` scans the harness's `skills/` and `roles/` and the project's `.claude/skills/` and
`.claude/agents/`, reads each artifact's `wayline.json` sidecar for what it is good for, recomputes
its `sha256` from the files on disk, and computes its outcome record from the journal's
`ticket_launched` and `ticket_done` or `ticket_failed` pairs. The result is `research/registry.json`,
one `registry_entry` per artifact.

The librarian is the step that reads it: given a ticket it returns the role and the skills to
assign, by the ticket's kind, the applicability tags, and the outcome record, and journals the
assignment as `assigned`. The planner calls it for every ticket it cuts (ticket 34).

Three rules make the index trustworthy rather than merely long:

- An entry is `assignable: false` when nothing has shown that it works. A local, model-authored
  skill qualifies only with a fixture that passed at its baseline; a local role override with no
  harness sidecar cannot be launched at all, because the tool lists are the harness's.
- A skill a ticket cannot name is not assignable either. The prompt builder looks a ticket's skill
  up as `wayline-<skill>`, so a skill directory without that prefix is unreachable however good it
  is, and the entry says so instead of failing at launch.
- Everything else an entry has to say is a note beside those reasons, not one of them. `problems`
  holds both, the reasons first; a sidecar whose hash has drifted from the files is worth reading
  and is no reason to stop assigning a skill the launch path runs. Nothing under either scope stops
  a build: a broken file is one artifact's problem, and a file whose name is no artifact name at all
  is one note, because the registry is rebuilt at every planner launch.

`claude plugin validate` runs as a free structural pre-check. It is run once per scope root rather
than once per skill directory: run on a bare skill directory it reports only that the directory is
not a plugin, while run on the directory that holds `skills/` it reads every `SKILL.md` under it
and reports the ones with problems. Its findings are notes on the entry; they never decide
`assignable`, because the harness's own launch path, not the plugin loader, is what has to accept a
skill. It is optional: no `claude` on PATH means one note and a build that still finishes.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.cli import parse_args
from wayline.frontmatter import FrontmatterError, load_document
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.ledger import (ASSIGNED, K_ATTEMPT, K_ROLE, K_SKILLS, K_TICKET, Ledger, TICKET_DONE,
                            TICKET_FAILED, TICKET_LAUNCHED, ledger_for, now_ts)
from wayline.project import ProjectError, find_project

__all__ = [
    "RegistryError", "REGISTRY_JSON", "SIDECAR", "SIDECAR_FIELDS", "ROLE_FIELDS", "SKILL_PREFIX",
    "COST_HINTS", "ticket_kinds", "content_sha256", "read_sidecar", "stamp_sidecars",
    "scan", "hash_contents", "outcomes", "plugin_validate", "build", "read_registry", "librarian", "assign",
    "build_command",
]

REGISTRY_JSON = "registry.json"
SIDECAR = "wayline.json"
SKILL_FILE = "SKILL.md"
ROLE_FILE = "agent.md"

# A ticket names a skill without the prefix and the prompt builder puts it back (`/wayline-<skill>`).
SKILL_PREFIX = "wayline-"

# Where each scope keeps its skills and roles.
HARNESS_SKILLS = "skills"
HARNESS_ROLES = "roles"
LOCAL_SKILLS = ".claude/skills"
LOCAL_ROLES = ".claude/agents"

# The sidecar fields of decision 10, shared by both kinds, and the four a role adds.
SIDECAR_FIELDS = ("id", "scope_kind", "capability_summary", "applicability_tags", "cost_hint", "fixtures", "sha256")
ROLE_FIELDS = ("allowed_tools", "disallowed_tools", "output_schema", "may_judge")

COST_HINTS = ("small", "medium", "large")
TAG_DIMENSIONS = ("kinds", "data_types", "libraries", "venues")
FIXTURE_KINDS = ("prompt", "role", "skill", "verifier", "conductor")
SCOPE_KINDS = ("global", "local")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
_FIXTURE_RE = re.compile(r"^(%s)/([a-z0-9][a-z0-9-]*)\Z" % "|".join(FIXTURE_KINDS))
_ZERO_OUTCOME = {"assigned": 0, "passed_first_time": 0, "failed": 0, "last_used": None}


class RegistryError(ValueError):
    """A sidecar the registry cannot read, or a build that cannot reach its scopes."""


def ticket_kinds():
    """The ticket kinds, from the shipped `ticket` schema, so the two cannot drift."""
    return tuple(load_schema("ticket")["$defs"]["kind"]["enum"])


# --- hashing ------------------------------------------------------------------------------------


def hash_contents(directory, skip=(SIDECAR,)):
    """`(digest, unreadable)` over every file under `directory`, names and bytes, `skip` left out.

    The sidecar is skipped because it carries the hash: including it would make the field
    self-referential. A symlink is hashed as its target's contents, which is what a reader of the
    skill sees. A file that cannot be read (a dangling symlink, a mode nobody can open) is hashed
    as a marker and named in `unreadable`, so one broken file inside one skill is that skill's
    problem rather than an exception that takes the whole build down with it.
    """
    directory = Path(directory)
    digest, unreadable = hashlib.sha256(), []
    for path in sorted(directory.rglob("*"), key=lambda item: str(item.relative_to(directory))):
        relative = path.relative_to(directory)
        if relative.name in skip or path.is_dir():
            continue
        digest.update(str(relative).encode("utf-8") + b"\0")
        try:
            digest.update(path.read_bytes() + b"\0")
        except OSError as failure:
            digest.update(b"<unreadable>\0")
            unreadable.append("%s cannot be read: %s" % (relative, failure))
    return digest.hexdigest(), unreadable


def content_sha256(directory, skip=(SIDECAR,)):
    """The hash alone, for a caller with nothing to report to (`stamp_sidecars`, the suite)."""
    return hash_contents(directory, skip)[0]


def stamp_sidecars(root=None):
    """Rewrite every harness sidecar's `sha256` from the files beside it; returns what changed.

    The suite asserts the shipped sidecars are stamped, so this is what to run after editing a
    `SKILL.md` or a role's `agent.md`.
    """
    root = Path(root or HARNESS_ROOT)
    stamped = []
    for directory in _artifact_dirs(root / HARNESS_SKILLS) + _artifact_dirs(root / HARNESS_ROLES):
        path = directory / SIDECAR
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        computed = content_sha256(directory)
        if json.loads(text).get("sha256") == computed:
            continue
        # A textual substitution rather than a re-dump: these files are read by people, and their
        # spelling (a tool list on one line, say) is nobody's to reflow for the sake of one field.
        replaced, count = re.subn(r'("sha256"\s*:\s*)"[0-9a-f]{64}"', lambda match: match.group(1) + '"%s"' % computed, text, count=1)
        if count != 1:
            raise RegistryError("%s has no sha256 line to stamp; add \"sha256\": \"%s\"" % (path, computed))
        path.write_text(replaced, encoding="utf-8")
        stamped.append(str(directory.relative_to(root)))
    return stamped


def _artifact_dirs(parent):
    if not Path(parent).is_dir():
        return []
    return sorted(path for path in Path(parent).iterdir() if path.is_dir() and not path.name.startswith("."))


# --- the sidecar --------------------------------------------------------------------------------


def read_sidecar(path, kind, expect_id=None):
    """One `wayline.json`, with every field checked; raises `RegistryError` naming the file.

    `kind` is `skill` or `role`: a role's sidecar carries the four launch fields as well, and a
    skill's must not. Missing lists and an absent `sha256` default rather than fail, so a sidecar
    written by hand is short; a value of the wrong shape is a refusal, because it is a typo the
    librarian would otherwise act on.
    """
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as failure:
        raise RegistryError("%s cannot be read: %s" % (path, failure)) from None
    except ValueError as failure:
        raise RegistryError("%s is not readable JSON: %s" % (path, failure)) from None
    if not isinstance(value, dict):
        raise RegistryError("%s holds an object of registry fields, got %s" % (path, type(value).__name__))
    allowed = SIDECAR_FIELDS + (ROLE_FIELDS if kind == "role" else ())
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise RegistryError("%s has no field(s) %s (the fields are %s)" % (path, ", ".join(unknown), ", ".join(allowed)))
    identifier = value.setdefault("id", expect_id)
    if not isinstance(identifier, str) or not _NAME_RE.match(identifier):
        raise RegistryError("%s: id is lowercase letters, digits, and dashes, got %r" % (path, identifier))
    if expect_id is not None and identifier != expect_id:
        raise RegistryError("%s names %r but lives under %r" % (path, identifier, expect_id))
    scope = value.setdefault("scope_kind", "global")
    if scope not in SCOPE_KINDS:
        raise RegistryError("%s: scope_kind is one of %s, got %r" % (path, ", ".join(SCOPE_KINDS), scope))
    summary = value.setdefault("capability_summary", "")
    if not isinstance(summary, str) or not summary.strip():
        raise RegistryError("%s: capability_summary says in one sentence what this is good for" % path)
    tags = value.setdefault("applicability_tags", {})
    if not isinstance(tags, dict) or set(tags) - set(TAG_DIMENSIONS):
        raise RegistryError("%s: applicability_tags holds %s and nothing else" % (path, ", ".join(TAG_DIMENSIONS)))
    for dimension in TAG_DIMENSIONS:
        items = tags.setdefault(dimension, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise RegistryError("%s: applicability_tags.%s is a list of non-empty strings" % (path, dimension))
    unknown_kinds = sorted(set(tags["kinds"]) - set(ticket_kinds()))
    if unknown_kinds:
        raise RegistryError("%s: applicability_tags.kinds names no ticket kind(s) %s" % (path, ", ".join(unknown_kinds)))
    cost = value.setdefault("cost_hint", "medium")
    if cost not in COST_HINTS:
        raise RegistryError("%s: cost_hint is one of %s, got %r" % (path, ", ".join(COST_HINTS), cost))
    fixtures = value.setdefault("fixtures", [])
    if not isinstance(fixtures, list) or not all(isinstance(item, str) and _FIXTURE_RE.match(item) for item in fixtures):
        raise RegistryError("%s: fixtures holds ids spelled <kind>/<slug> with kind in %s" % (path, ", ".join(FIXTURE_KINDS)))
    declared = value.setdefault("sha256", None)
    if declared is not None and not re.match(r"^[0-9a-f]{64}\Z", str(declared)):
        raise RegistryError("%s: sha256 is a 64-character hex digest, or absent" % path)
    if kind == "role":
        for key in ("allowed_tools", "disallowed_tools"):
            items = value.setdefault(key, [])
            if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
                raise RegistryError("%s: %s is a list of non-empty strings" % (path, key))
        if not isinstance(value.setdefault("may_judge", False), bool):
            raise RegistryError("%s: may_judge is true or false" % path)
        if value.setdefault("output_schema", None) is not None and not isinstance(value["output_schema"], str):
            raise RegistryError("%s: output_schema names a shipped schema, or is null" % path)
    return value


# --- the scan -----------------------------------------------------------------------------------


def scan(harness_root=None, project=None):
    """`(entries, notes)`: every skill and role of both scopes, without outcomes or pre-check notes.

    Entries are keyed by `(kind, id)` and a local entry wins, because that is what the launch path
    does: a project's own skill or role override is the one a worker gets. A directory or file whose
    name is no artifact name at all (`.claude/agents/README.md`, `.claude/skills/My_Skill/`) is not
    an entry and not an error: it becomes one note on the build, because the registry is rebuilt at
    every planner launch and a stray file beside the real ones must not stop the planner.
    """
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    found, notes = {}, []
    for entry in _collect(_scan_global(harness_root), harness_root, notes):
        found[(entry["kind"], entry["id"])] = entry
    if project is not None:
        project = Path(project).resolve()
        for entry in _collect(_scan_local(project, harness_root, found), project, notes):
            found[(entry["kind"], entry["id"])] = entry
    return [found[key] for key in sorted(found, key=lambda key: (key[0], key[1]))], notes


def _collect(candidates, root, notes):
    """Keep the entries whose id is an artifact name; note the rest, which no ticket could name."""
    kept = []
    for identifier, entry in candidates:
        if entry is not None and _NAME_RE.match(entry["id"]):
            kept.append(entry)
        else:
            notes.append("%s is not a %s name (lowercase letters, digits, and dashes), so it is not registered"
                         % (identifier, "skill" if entry is None or entry["kind"] == "skill" else "role"))
    return kept


def _scan_global(harness_root):
    for directory in _artifact_dirs(harness_root / HARNESS_SKILLS):
        yield directory.name, _skill_entry(directory, harness_root, "global", harness_root)
    for directory in _artifact_dirs(harness_root / HARNESS_ROLES):
        yield directory.name, _role_entry(directory, harness_root, "global")


def _scan_local(project, harness_root, global_entries):
    """The project's own skills and role overrides.

    A symlink into the harness is `init`'s work, not a local skill: it is already registered as
    global, and registering it again under the project's path would double every harness skill.
    """
    for directory in _artifact_dirs(project / LOCAL_SKILLS):
        if _links_into(directory, harness_root):
            continue
        yield directory.name, _skill_entry(directory, project, "local", harness_root)
    roles_dir = project / LOCAL_ROLES
    for path in sorted(roles_dir.glob("*.md")) if roles_dir.is_dir() else []:
        yield path.name, _local_role_entry(path, project, global_entries.get(("role", path.stem)))


def _links_into(path, root):
    """Whether `path` is a symlink whose target lies under `root`.

    A relative target is read against the link's own directory rather than the process's, because
    where the build was started from is not part of what the link means.
    """
    path = Path(path)
    if not path.is_symlink():
        return False
    try:
        target = Path(os.readlink(path))
        if not target.is_absolute():
            target = path.parent / target
        return target.resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):  # pragma: no cover - a symlink loop
        return False


def _entry(identifier, kind, scope_kind, path, root, sidecar, vetoes):
    """One entry from a sidecar, with the hash recomputed and `assignable` decided.

    `vetoes` are the reasons the librarian must not assign this artifact. A sidecar whose declared
    hash has drifted from the files is a note beside them rather than one of them: it says the
    sidecar was not restamped, which is worth reading and is no reason to stop using a skill the
    launch path is perfectly able to run.
    """
    computed, unreadable = hash_contents(path)
    vetoes = vetoes + unreadable
    notes = []
    declared = sidecar.get("sha256")
    if declared is not None and declared != computed:
        notes.append("the sidecar's sha256 was recorded as %s and the files hash to %s; the computed one is registered" % (declared[:12], computed[:12]))
    return {
        "id": identifier,
        "kind": kind,
        "scope_kind": scope_kind,
        "path": str(Path(path).relative_to(root)),
        "sha256": computed,
        "capability_summary": sidecar["capability_summary"],
        "applicability_tags": {dimension: list(sidecar["applicability_tags"][dimension]) for dimension in TAG_DIMENSIONS},
        "cost_hint": sidecar["cost_hint"],
        "fixtures": list(sidecar["fixtures"]),
        "outcome": dict(_ZERO_OUTCOME),
        "assignable": not vetoes,
        "problems": vetoes + notes,
    }


def _skill_entry(directory, root, scope_kind, harness_root):
    vetoes = []
    name = directory.name
    identifier = name[len(SKILL_PREFIX):] if name.startswith(SKILL_PREFIX) else name
    if not name.startswith(SKILL_PREFIX):
        vetoes.append("a ticket names a skill as /%s<skill>, so a directory not called %s%s is one no ticket can reach" % (SKILL_PREFIX, SKILL_PREFIX, identifier))
    if not (directory / SKILL_FILE).is_file():
        vetoes.append("no %s, and the body is what the prompt carries" % SKILL_FILE)
    try:
        sidecar = read_sidecar(directory / SIDECAR, "skill", expect_id=identifier)
    except RegistryError as failure:
        return _unreadable(identifier, "skill", scope_kind, directory, root, vetoes + [str(failure)])
    if scope_kind == "local":
        vetoes = vetoes + _fixture_problems(sidecar["fixtures"], (root, harness_root))
    return _entry(identifier, "skill", scope_kind, directory, root, sidecar, vetoes)


def _role_entry(directory, root, scope_kind):
    vetoes = [] if (directory / ROLE_FILE).is_file() else ["no %s, and the body is the role's system prompt" % ROLE_FILE]
    try:
        sidecar = read_sidecar(directory / SIDECAR, "role", expect_id=directory.name)
    except RegistryError as failure:
        return _unreadable(directory.name, "role", scope_kind, directory, root, vetoes + [str(failure)])
    return _entry(directory.name, "role", scope_kind, directory, root, sidecar, vetoes)


def _local_role_entry(path, project, global_entry):
    """A project's `.claude/agents/<role>.md`: its own words for a role the harness still launches.

    The tool lists stay the harness's (decision 4), so a local override of a harness role inherits
    that role's registry fields, and its summary is the project's: the description in the local
    markdown is the one `worker.read_role` launches with, so it is the one the index has to show.
    An override of a role the harness does not have cannot be launched at all, and the entry says so.
    """
    name = path.stem
    entry = dict(global_entry or {}, id=name, kind="role", scope_kind="local", path=str(path.relative_to(project)))
    entry["outcome"] = dict(_ZERO_OUTCOME)
    problems = []
    try:
        body = path.read_bytes()
    except OSError as failure:
        entry["sha256"] = hashlib.sha256(b"<unreadable>").hexdigest()
        problems.append("%s cannot be read: %s" % (path.name, failure))
    else:
        entry["sha256"] = hashlib.sha256(body).hexdigest()
        described = _description(body)
        if described:
            entry["capability_summary"] = described
    if global_entry is None:
        entry.setdefault("capability_summary", "a local role override of %r" % name)
        entry.setdefault("applicability_tags", {dimension: [] for dimension in TAG_DIMENSIONS})
        entry.setdefault("cost_hint", "medium")
        entry.setdefault("fixtures", [])
        problems.append("the harness has no role %r, and a role without the harness's %s has no tool lists to launch with" % (name, SIDECAR))
    else:
        problems.extend(global_entry.get("problems") or [])
    entry["problems"] = problems
    entry["assignable"] = not problems
    return entry


def _description(body):
    """The `description` of a role markdown's frontmatter, or None when it has none to read."""
    try:
        frontmatter, _ = load_document(body.decode("utf-8"))
    except (UnicodeDecodeError, FrontmatterError):
        return None
    described = frontmatter.get("description")
    return described.strip() if isinstance(described, str) and described.strip() else None


def _unreadable(identifier, kind, scope_kind, path, root, problems):
    """An entry for an artifact whose sidecar the build could not use: listed, never assigned."""
    return {
        "id": identifier,
        "kind": kind,
        "scope_kind": scope_kind,
        "path": str(Path(path).relative_to(root)),
        "sha256": content_sha256(path),
        "capability_summary": "unreadable sidecar",
        "applicability_tags": {dimension: [] for dimension in TAG_DIMENSIONS},
        "cost_hint": "medium",
        "fixtures": [],
        "outcome": dict(_ZERO_OUTCOME),
        "assignable": False,
        "problems": problems,
    }


def _fixture_problems(fixtures, roots):
    """Whether a local skill has a fixture that passed, which is what makes it assignable.

    A fixture id is looked for under each of `roots` in turn, the project first and the harness
    second: decision 12's layout is the harness's `fixtures/<kind>/<slug>/`, and a fixture recorded
    for a local skill may be written into either tree, so a gate that looked in one of them would
    hold a working skill back forever.

    Until ticket 44's runner exists the evidence is the baseline the recorder wrote: a fixture with
    no baseline, or with a baseline that records no result, has never passed, and one whose recorded
    layers are not a clean sweep did not pass.
    """
    if not fixtures:
        return ["a local skill names no fixture, so nothing has shown that it works"]
    problems = []
    for identifier in fixtures:
        looked = [Path(root) / "fixtures" / identifier for root in roots]
        found = [directory for directory in looked if (directory / "fixture.json").is_file()]
        if not found:
            problems.append("the fixture %s is in none of %s" % (identifier, ", ".join(str(where) for where in looked)))
            continue
        record = found[0] / "fixture.json"
        try:
            baseline = (json.loads(record.read_text(encoding="utf-8")) or {}).get("baseline")
        except (OSError, ValueError) as failure:
            problems.append("the fixture %s is not readable: %s" % (identifier, failure))
            continue
        scores = [baseline[layer] for layer in ("structural", "judged")
                  if isinstance(baseline, dict) and baseline.get(layer) is not None]
        if not scores:
            problems.append("the fixture %s has no recorded baseline, so it has never passed" % identifier)
        elif not all(_full_pass(score) for score in scores):
            problems.append("the fixture %s did not pass at its baseline (%s)" % (identifier, baseline))
    return problems


def _full_pass(score):
    """A baseline score `"n/n"` with n at least one."""
    match = re.match(r"^(\d+)/(\d+)\Z", str(score or ""))
    return bool(match) and match.group(1) == match.group(2) and int(match.group(2)) > 0


# --- outcomes -----------------------------------------------------------------------------------


def outcomes(events):
    """The outcome record per `(kind, id)`, from the journal's launch and close pairs.

    A launch names the role and the skills it ran with, so a close is attributed to whatever the
    ticket's most recent launch named. `passed_first_time` counts the closes that came back on the
    first attempt, which is the number the evolve loop compares skills by.
    """
    records, launched = {}, {}

    def record(kind, identifier):
        return records.setdefault((kind, identifier), dict(_ZERO_OUTCOME))

    for event in events:
        name = event.get("event")
        payload = event.get("payload") or {}
        ticket = payload.get(K_TICKET, event.get("ticket"))
        if name == TICKET_LAUNCHED:
            keys = [("role", payload[K_ROLE])] if payload.get(K_ROLE) else []
            keys += [("skill", skill) for skill in (payload.get(K_SKILLS) or []) if skill]
            launched[ticket] = {"keys": keys, "attempt": payload.get(K_ATTEMPT)}
            for kind, identifier in keys:
                entry = record(kind, identifier)
                entry["assigned"] += 1
                entry["last_used"] = event.get("ts") or entry["last_used"]
        elif name in (TICKET_DONE, TICKET_FAILED):
            launch = launched.get(ticket)
            if launch is None:
                continue
            for kind, identifier in launch["keys"]:
                entry = record(kind, identifier)
                if name == TICKET_FAILED:
                    entry["failed"] += 1
                elif launch["attempt"] in (1, None):
                    entry["passed_first_time"] += 1
    return records


# --- the structural pre-check -------------------------------------------------------------------


def plugin_validate(scope_root, timeout=60):
    """The free structural pre-check over one scope root: problems per file, or why it did not run.

    The CLI is reached through the launcher seam, which is the only module that knows how the
    executable is spelled and found; a scope with no validator to run is one note on the build.
    """
    from wayline import worker  # lazy: worker reads this module's sidecars, so only one direction is a module-level import

    findings, note = worker.validate_plugin(scope_root, timeout=timeout)
    if note:
        return {}, "the structural pre-check of the skills did not run over %s: %s" % (scope_root, note)
    return findings, None


def _attach_pre_check(entries, roots):
    """Hang each scope's validator findings on the entry whose directory holds the file.

    An entry's `path` is relative to the scope root it was found under, so only that scope's
    entries are candidates for a scope's findings: the same relative path under the other root
    would name a different directory, or none.
    """
    notes = []
    for scope_kind, root, scope_root in roots:
        problems, note = plugin_validate(scope_root)
        if note:
            notes.append(note)
            continue
        candidates = [(entry, (Path(root) / entry["path"]).resolve())
                      for entry in entries if entry["scope_kind"] == scope_kind]
        for path, lines in sorted(problems.items()):
            try:
                reported = Path(path).resolve()
            except (OSError, ValueError):  # pragma: no cover - an unreadable path
                continue
            for entry, directory in candidates:
                if reported.is_relative_to(directory):
                    entry["problems"] = entry["problems"] + list(lines)
    return notes


# --- build --------------------------------------------------------------------------------------


def build(project=None, harness_root=None, events=None, write=True, pre_check=True):
    """Scan both scopes, compute the outcomes, and write `research/registry.json`.

    Returns `{"generated", "harness_root", "entries", "notes"}`. Every entry is validated against
    the `registry_entry` schema before anything is written, so a registry the librarian reads is
    one the schema accepts.
    """
    harness_root = Path(harness_root or HARNESS_ROOT).resolve()
    project = Path(project).resolve() if project is not None else None
    entries, notes = scan(harness_root, project)
    ledger = Ledger(project) if project is not None else None
    if events is None and ledger is not None:
        events, _ = ledger.read_events()
    for key, outcome in outcomes(events or []).items():
        for entry in entries:
            if (entry["kind"], entry["id"]) == key:
                entry["outcome"] = outcome
    # `assignable` is decided by the scan, before the pre-check: a validator finding is a note on
    # the entry, not a veto, because the harness's launch path rather than the plugin loader is
    # what has to accept a skill.
    if pre_check:
        roots = [("global", harness_root, harness_root)]
        if project is not None:
            roots.append(("local", project, project / ".claude"))
        notes.extend(_attach_pre_check(entries, roots))
    for entry in entries:
        if not entry["problems"]:
            del entry["problems"]
        check(entry, load_schema("registry_entry"), name="registry entry %s/%s" % (entry["kind"], entry["id"]))
    registry = {"generated": now_ts(), "harness_root": str(harness_root), "entries": entries, "notes": notes}
    if write and ledger is not None:
        ledger.write_json(REGISTRY_JSON, registry)
    return registry


def read_registry(project):
    """`research/registry.json`, or an empty registry when the build has not run yet."""
    path = Path(project) / "research" / REGISTRY_JSON
    if not path.is_file():
        return {"generated": None, "harness_root": None, "entries": [], "notes": []}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# --- the librarian ------------------------------------------------------------------------------


def librarian(ticket, registry, tags=None):
    """The role and the skills to assign to one ticket, from the registry.

    `ticket` is a ticket dict (only `kind` is read) and `tags` optionally carries the project's own
    `data_types`, `libraries`, and `venues` for this ticket, which the planner takes from `SPEC.md`.
    Returns `{"role", "skills", "notes"}` with `role` None when no role covers the kind: a missing
    role is a harness ticket, not something to paper over with a role that cannot do the work.

    The order is the same for both kinds: more matching tags first, then the outcome record (a
    record of first-time passes beats no record, and no record beats a record of failures), then
    the cheaper cost hint, then the id, so one registry always gives one assignment.
    """
    kind = (ticket or {}).get("kind")
    entries = [entry for entry in (registry or {}).get("entries") or [] if entry.get("assignable")]
    notes = []
    roles = [entry for entry in entries if entry["kind"] == "role" and kind in entry["applicability_tags"]["kinds"]]
    skills = [entry for entry in entries if entry["kind"] == "skill" and kind in entry["applicability_tags"]["kinds"]
              and _tags_allow(entry, tags)]
    roles.sort(key=lambda entry: _rank(entry, kind, tags))
    skills.sort(key=lambda entry: _rank(entry, kind, tags))
    if not roles:
        notes.append("no assignable role covers a %s ticket; the harness needs one before this ticket can run" % kind)
    return {
        "role": roles[0]["id"] if roles else None,
        "skills": [entry["id"] for entry in skills],
        "notes": notes,
    }


def _tags_allow(entry, tags):
    """A skill that names data types, libraries, or venues wants one of them to match the ticket's."""
    given = tags or {}
    for dimension in ("data_types", "libraries", "venues"):
        wanted = entry["applicability_tags"][dimension]
        if wanted and not set(wanted) & set(given.get(dimension) or []):
            return False
    return True


def _rank(entry, kind, tags):
    given = tags or {}
    matches = sum(len(set(entry["applicability_tags"][dimension]) & set(given.get(dimension) or []))
                  for dimension in ("data_types", "libraries", "venues"))
    outcome = entry["outcome"]
    if not outcome["assigned"]:
        record = 1  # untried: better than a bad record, worse than a good one
    else:
        record = 2 if outcome["passed_first_time"] * 2 >= outcome["assigned"] else 0
    return (-matches, -record, COST_HINTS.index(entry["cost_hint"]), entry["id"])


def assign(ticket, registry, ledger=None, tags=None):
    """Assign one ticket and journal it as `assigned`; returns the assignment.

    The planner calls this for every ticket it cuts, so the journal says which role and which
    skills every ticket was given and the outcome records of the next build are computable from it.
    """
    assignment = librarian(ticket, registry, tags=tags)
    if ledger is not None:
        ledger_for(ledger).append_event(
            ASSIGNED,
            {K_TICKET: (ticket or {}).get("id"), K_ROLE: assignment["role"], K_SKILLS: list(assignment["skills"])},
            ticket=(ticket or {}).get("id"),
        )
    return assignment


# --- the verb -----------------------------------------------------------------------------------


def build_command(args):
    parser = argparse.ArgumentParser(prog="wayline registry", description="build the index of skills and roles")
    parser.add_argument("action", choices=["build"], help="build rewrites research/registry.json from both scopes")
    parser.add_argument("--project", help="the project to build for; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the registry as JSON instead of a table")
    parser.add_argument("--no-pre-check", action="store_true", help="skip the free structural pre-check of the skills")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        registry = build(find_project(options.project), pre_check=not options.no_pre_check)
    except (RegistryError, ProjectError, ValidationError, OSError) as failure:
        print("wayline registry build: %s" % failure, file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(registry, ensure_ascii=False, indent=2))
        return 0
    print(render(registry))
    return 0


def render(registry):
    """The table `wayline registry build` prints: one line per entry, then the notes."""
    entries = registry.get("entries") or []
    lines = ["registry  %d entries  %s" % (len(entries), registry.get("generated") or "")]
    width = max([len(entry["id"]) for entry in entries] + [4])
    for entry in entries:
        outcome = entry["outcome"]
        lines.append("  %-6s %-8s %-*s  %s%s" % (
            entry["kind"], entry["scope_kind"], width, entry["id"],
            "" if entry["assignable"] else "(not assignable) ",
            entry["capability_summary"],
        ))
        if outcome["assigned"]:
            lines.append("  %-6s %-8s %-*s  %d assigned, %d passed first time, %d failed, last %s" % (
                "", "", width, "", outcome["assigned"], outcome["passed_first_time"], outcome["failed"], outcome["last_used"]))
        for problem in entry.get("problems") or []:
            lines.append("  %-6s %-8s %-*s  ! %s" % ("", "", width, "", problem))
    for note in registry.get("notes") or []:
        lines.append("  note  %s" % note)
    return "\n".join(lines)
