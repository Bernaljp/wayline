"""The model-behavior fixtures: the runner and the recorder (Implementation Decisions 12).

A fixture pins one real input pack and output of a prompt, a role, a skill, or a verifier under
`fixtures/<kind>/<slug>/` (`fixture.json`, `input/`, `rubric.md`, `recorded/`, `runs/`) and says
what any later output must still do, so a change to the subject is caught when it regresses even
though model outputs vary. `wayline fixture run` runs the subject `n` times through the worker
launcher and holds every sample to two layers:

- the structural layer (Type-A, free): `schema_valid` first and always, then the checks of
  `CHECKS` over a JSONPath subset of the re-validated result, the run's project, and the stream
  trace; every sample must pass (n of n);
- the judged layer (Type-B): a fresh `fixture-judge` session per sample with no tools, shown the
  rubric and only the `show_judge` fields and never launched in the subject's session, passing at
  `at_least` of `sample_size` (`strict` forces n of n). It runs only when every sample passed the
  free layer, since a fixture that failed there has failed already.

The subject a run sends is the pinned pack with the current subject put into it: a role's
`agent.md` becomes the `--agents` prompt, a schema under `schemas/` the `--json-schema`, and any
other subject file replaces its pinned copy (`input/subject/<path>`) where that copy's text sits
in `input/prompt.md`. That is how a change to the subject reaches a pinned input at all.

Subject outputs are cached by the hash of (prompt, agent JSON, context manifest, schema, model,
effort) and verdicts by (rubric, judge model, the fields shown), each with a namespace per sample
index, under `~/.wayline/fixture-cache/`: per-machine and outside the harness checkout, like every
mutable pointer of decision 1. The runner writes `runs/` and, in `fixture.json`, `last_run`,
`quarantine`, and on a rewrite `baseline`; it deletes nothing, in the fixtures or in the cache.

Exit codes: 1 on a regression (a fixture that passed at its baseline fails now and is not
quarantined), 2 on a stop for cost (`fixtures.max_turns_per_suite`, a usage window that refused a
session, or a full suite asked for twice in one weekly window), 0 otherwise.
"""

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from wayline import HARNESS_ROOT, SCHEMAS_DIR, cli, project as projects, worker
from wayline.frontmatter import FrontmatterError, load_document
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger, LedgerError, atomic_write, now_ts
from wayline.registry import FIXTURE_KINDS

__all__ = [
    "FixtureError", "Check", "Sample", "FixtureRun", "SuiteResult", "CHECKS", "JUDGE_ROLE", "VERDICT_SCHEMA",
    "jsonpath", "structural_checks", "subject_sha256", "subject_minutes", "sample_failures", "input_hash", "context_manifest", "render_input",
    "discover", "load_fixture", "run", "run_fixture", "record", "set_baseline", "describe", "fixture_command",
]

FIXTURES = "fixtures"
JUDGE_ROLE = "fixture-judge"             # <harness>/roles/fixture-judge/
VERDICT_SCHEMA = "fixture_verdict"       # <harness>/schemas/fixture_verdict.json
CACHE = "fixture-cache"                  # <home>/fixture-cache/{subject,judge}/<key>/<sample>/<attempt>/
SUITE_STATE = "fixtures.json"            # <home>/fixtures.json: when the last full suite ran
WEEK_SECONDS = 7 * 86400                 # the weekly window when no session reported its reset
JUDGE_MAX_TURNS = 3                      # one question, no tools: the answer is the first turn
JUDGE_MAX_MINUTES = 5
RESULT_TEXT_CHARS = 400                  # what a sample keeps of a session's last words when it returned no output
SUBJECT_MAX_MINUTES = 30                 # policy.budget.small, when neither the fixture nor its role names one
EXIT_REGRESSION = 1
EXIT_COST = 2

CHECKS = (
    "schema_valid", "path_equals", "path_in", "path_matches", "path_contains_all", "path_contains_any",
    "path_count", "path_absent_or_empty", "file_exists", "file_absent", "tool_used", "tool_not_used", "python",
)

# The placeholders a recorded pack carries instead of the paths of the machine it was recorded on.
PLACEHOLDERS = ("harness", "project", "run")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
_STEP_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_-]*)|\.\*|\[(\d+)\]|\[\*\]|\['([^']*)'\]|\[\"([^\"]*)\"\]")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*\Z")
_ROLE_FILE_RE = re.compile(r"^(?:roles/([a-z][a-z0-9-]*)/agent\.md|\.claude/agents/([a-z][a-z0-9-]*)\.md)\Z")
_SKILL_FILE_RE = re.compile(r"^((?:\.claude/)?skills/([a-z0-9][a-z0-9-]*))/.+\Z")


class FixtureError(ValueError):
    """A fixture that cannot be read, rendered, or recorded, or a check outside the vocabulary."""


class _CostStop(Exception):
    """The suite stops launching: the turn ceiling is spent, or a usage window refused a session."""


# --- JSONPath, the subset -------------------------------------------------------------------------


def jsonpath(value, path):
    """Every value `path` names in `value`, in document order; an empty list when it names none.

    The subset: `$`, `.name`, `['name']`, `[n]`, `[*]`, and `.*`. Anything else (recursive descent,
    filters, slices) is refused rather than half-read, because a check that silently matched
    nothing would pass or fail for a reason nobody wrote.
    """
    if not isinstance(path, str) or not path.startswith("$"):
        raise FixtureError("%r is not a JSONPath: it starts with $" % (path,))
    steps, position = [], 1
    while position < len(path):
        match = _STEP_RE.match(path, position)
        if match is None:
            raise FixtureError("%r is outside the JSONPath subset ($, .name, ['name'], [n], [*], .*) at %r" % (path, path[position:]))
        if match.group(0) in (".*", "[*]"):
            steps.append(("*", None))
        elif match.group(2) is not None:
            steps.append(("index", int(match.group(2))))
        else:
            steps.append(("key", next(group for group in (match.group(1), match.group(3), match.group(4)) if group is not None)))
        position = match.end()
    current = [value]
    for kind, argument in steps:
        following = []
        for item in current:
            if kind == "key" and isinstance(item, dict) and argument in item:
                following.append(item[argument])
            elif kind == "index" and isinstance(item, list) and argument < len(item):
                following.append(item[argument])
            elif kind == "*" and isinstance(item, dict):
                following.extend(item.values())
            elif kind == "*" and isinstance(item, list):
                following.extend(item)
        current = following
    return current


def _path_for(steps):
    """The JSONPath of a key sequence, spelled `.name` where it can be and `['name']` where not."""
    return "$" + "".join(".%s" % step if _IDENTIFIER_RE.match(step) else "['%s']" % step.replace("'", "") for step in steps)


# --- the structural layer -------------------------------------------------------------------------


@dataclass
class Check:
    """One structural check on one sample: the check as the fixture wrote it, whether it passed, and why not."""

    check: dict
    passed: bool
    detail: str = ""

    def as_dict(self):
        return {"check": self.check, "passed": self.passed, "detail": self.detail}


def structural_checks(checks, output, root, trace=None, fixture_dir=None, schema=None, ended_ok=True):
    """Every structural check on one sample, `schema_valid` first whether or not it is listed.

    `output` is the session's structured output as the stream carried it, re-validated here
    against `schema`; with no schema, `schema_valid` asks only that the session ended with a
    success result (`ended_ok`). When it fails, every other check is reported failed without being
    run, since a path over an output the schema rejects says nothing. `root` is the project the
    session ran in (the file checks and the `python` checks read it), `trace` its `stream.jsonl`,
    and `fixture_dir` the directory holding `checks.py`.
    """
    listed = [dict(check) for check in (checks or [])]
    first = next((check for check in listed if check.get("check") == "schema_valid"), {"check": "schema_valid"})
    results = [_schema_valid(first, output, schema, ended_ok)]
    rest = [check for check in listed if check.get("check") != "schema_valid"]
    if not results[0].passed:
        return results + [Check(check, False, "not run: the sample did not pass schema_valid") for check in rest]
    for check in rest:
        checker = _CHECKERS.get(check.get("check"))
        try:
            if checker is None:
                raise FixtureError("%r is not a structural check; the checks are %s" % (check.get("check"), ", ".join(CHECKS)))
            passed, detail = checker(check, output, Path(root), trace, fixture_dir)
        except FixtureError as failure:
            passed, detail = False, str(failure)
        results.append(Check(check, bool(passed), detail))
    return results


def _schema_valid(check, output, schema, ended_ok):
    if schema is None:
        return Check(check, bool(ended_ok), "" if ended_ok else "the session did not end with a success result")
    if not isinstance(output, dict):
        return Check(check, False, "the session returned no structured output")
    errors = validate(output, schema)
    return Check(check, not errors, "; ".join("%s: %s" % (error.path, error.message) for error in errors[:5]))


def _found(check, output):
    if output is None:
        raise FixtureError("the session returned no structured output for %s to read" % check["path"])
    return jsonpath(output, check["path"])


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _show(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "..."


def _path_equals(check, output, root, trace, fixture_dir):
    found = _found(check, output)
    if not found:
        return False, "%s matched nothing" % check["path"]
    wrong = [item for item in found if not _same(item, check["value"])]
    return not wrong, ("%s is %s, not %s" % (check["path"], _show(wrong[0]), _show(check["value"])) if wrong else "")


def _path_in(check, output, root, trace, fixture_dir):
    found = _found(check, output)
    if not found:
        return False, "%s matched nothing" % check["path"]
    wrong = [item for item in found if not any(_same(item, option) for option in check["values"])]
    return not wrong, ("%s is %s, which is none of %s" % (check["path"], _show(wrong[0]), _show(check["values"])) if wrong else "")


def _path_matches(check, output, root, trace, fixture_dir):
    found = _found(check, output)
    if not found:
        return False, "%s matched nothing" % check["path"]
    try:
        pattern = re.compile(check["regex"])
    except re.error as failure:
        raise FixtureError("the regex %r does not compile: %s" % (check["regex"], failure))
    wrong = [item for item in found if not isinstance(item, str) or not pattern.search(item)]
    return not wrong, ("%s holds %s, which does not match %s" % (check["path"], _show(wrong[0]), check["regex"]) if wrong else "")


def _collection(check, found):
    """What the contains checks read: the one array, object, or string a plain path names, or what a wildcard matched."""
    if "*" not in check["path"] and len(found) == 1 and isinstance(found[0], (list, dict, str)):
        return found[0]
    return found


def _contains(collection, value):
    if isinstance(collection, str):
        return isinstance(value, str) and value in collection
    if isinstance(collection, dict):
        return isinstance(value, str) and value in collection
    return any(_same(item, value) for item in collection)


def _path_contains_all(check, output, root, trace, fixture_dir):
    found = _found(check, output)
    if not found:
        return False, "%s matched nothing" % check["path"]
    missing = [value for value in check["values"] if not _contains(_collection(check, found), value)]
    return not missing, ("%s lacks %s" % (check["path"], _show(missing)) if missing else "")


def _path_contains_any(check, output, root, trace, fixture_dir):
    found = _found(check, output)
    if not found:
        return False, "%s matched nothing" % check["path"]
    hit = any(_contains(_collection(check, found), value) for value in check["values"])
    return hit, ("" if hit else "%s holds none of %s" % (check["path"], _show(check["values"])))


def _path_count(check, output, root, trace, fixture_dir):
    if "min" not in check and "max" not in check:
        raise FixtureError("path_count on %s names neither min nor max" % check["path"])
    found = _found(check, output)
    if not found:
        count = 0
    elif "*" not in check["path"] and len(found) == 1 and isinstance(found[0], (list, dict)):
        count = len(found[0])
    else:
        count = len(found)
    low, high = check.get("min"), check.get("max")
    passed = (low is None or count >= low) and (high is None or count <= high)
    wanted = " and ".join(part for part in ("at least %d" % low if low is not None else "", "at most %d" % high if high is not None else "") if part)
    return passed, ("" if passed else "%s counts %d, not %s" % (check["path"], count, wanted))


def _empty(item):
    return item is None or (isinstance(item, (list, dict, str)) and len(item) == 0)


def _path_absent_or_empty(check, output, root, trace, fixture_dir):
    found = _found(check, output)
    wrong = [item for item in found if not _empty(item)]
    return not wrong, ("%s holds %s" % (check["path"], _show(wrong[0])) if wrong else "")


def _target(check, root):
    target = (root / check["path"]).resolve()
    if not target.is_relative_to(root.resolve()):
        raise FixtureError("%s leaves the run's project" % check["path"])
    return target


def _file_exists(check, output, root, trace, fixture_dir):
    present = _target(check, root).exists()
    return present, ("" if present else "%s is not in the run's project" % check["path"])


def _file_absent(check, output, root, trace, fixture_dir):
    present = _target(check, root).exists()
    return not present, ("%s is in the run's project" % check["path"] if present else "")


def tool_uses(trace):
    """`(name, input)` for every `tool_use` block of the assistant messages in a stream trace, subagents' included."""
    uses = []
    try:
        with open(trace, "rb") as handle:
            lines = handle.read().splitlines()
    except (OSError, TypeError):
        raise FixtureError("there is no stream trace to read tool uses from")
    for raw in lines:
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("type") != "assistant":
            continue
        content = (message.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                arguments = block.get("input")
                uses.append((block.get("name"), arguments if isinstance(arguments, dict) else {}))
    return uses


def _tool_matches(check, name, arguments):
    if name != check["tool"]:
        return False
    if "arg" in check and check["arg"] not in [value for value in arguments.values() if isinstance(value, str)]:
        return False
    if "input_matches" in check:
        try:
            pattern = re.compile(check["input_matches"])
        except re.error as failure:
            raise FixtureError("the input_matches regex %r does not compile: %s" % (check["input_matches"], failure))
        if not pattern.search(json.dumps(arguments, ensure_ascii=False)):
            return False
    return True


def _describe_tool(check):
    extra = "".join(" with %s %r" % (key, check[key]) for key in ("arg", "input_matches") if key in check)
    return "%s%s" % (check["tool"], extra)


def _tool_used(check, output, root, trace, fixture_dir):
    used = any(_tool_matches(check, name, arguments) for name, arguments in tool_uses(trace))
    return used, ("" if used else "the trace has no call to %s" % _describe_tool(check))


def _tool_not_used(check, output, root, trace, fixture_dir):
    used = any(_tool_matches(check, name, arguments) for name, arguments in tool_uses(trace))
    return not used, ("the trace calls %s" % _describe_tool(check) if used else "")


def _python(check, output, root, trace, fixture_dir):
    """`fn` from `checks.py` beside the fixture, called with (root), (root, output), or (root, output, trace).

    It returns a list of problems (empty passes) or a boolean.
    """
    if fixture_dir is None:
        raise FixtureError("a python check needs the fixture's directory")
    path = Path(fixture_dir) / check["file"]
    name = "wayline_fixture_checks_%s" % hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as failure:  # a checks.py that raises at import fails its checks; it never crashes the suite
        raise FixtureError("%s cannot be loaded: %s: %s" % (check["file"], type(failure).__name__, failure))
    function = getattr(module, check["fn"], None)
    if not callable(function):
        raise FixtureError("%s has no function %s" % (check["file"], check["fn"]))
    positional = [parameter for parameter in inspect.signature(function).parameters.values()
                  if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)]
    arguments = [Path(root), output, None if trace is None else Path(trace)][:max(1, min(len(positional), 3))]
    try:
        answer = function(*arguments)
    except Exception as failure:  # a check that crashes is a check that did not pass, never a crashed suite
        return False, "%s raised %s: %s" % (check["fn"], type(failure).__name__, failure)
    if isinstance(answer, bool):
        return answer, ("" if answer else "%s returned False" % check["fn"])
    problems = [str(problem) for problem in (answer or [])]
    return not problems, "; ".join(problems)


_CHECKERS = {
    "path_equals": _path_equals, "path_in": _path_in, "path_matches": _path_matches,
    "path_contains_all": _path_contains_all, "path_contains_any": _path_contains_any, "path_count": _path_count,
    "path_absent_or_empty": _path_absent_or_empty, "file_exists": _file_exists, "file_absent": _file_absent,
    "tool_used": _tool_used, "tool_not_used": _tool_not_used, "python": _python,
}


# --- hashes and the rendered input ----------------------------------------------------------------


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _digest_path(digest, root, relative):
    path = Path(root) / relative
    files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
    for item in files:
        name = relative if item == path else str(Path(relative) / item.relative_to(path))
        digest.update(name.encode("utf-8") + b"\0")
        try:
            digest.update(item.read_bytes() + b"\0")
        except OSError:
            digest.update(b"<missing>\0")


def subject_sha256(record, root):
    """The subject's hash: its path and every `also` path, names and bytes, a missing file marked as missing."""
    subject = record["subject"]
    digest = hashlib.sha256()
    for relative in [subject["path"]] + list(subject.get("also") or []):
        _digest_path(digest, root, relative)
    return digest.hexdigest()


def context_manifest(directory, record=None):
    """`[{path, sha256}]` for every file of `input/context/`, or the pinned manifest when the files were not copied."""
    context = Path(directory) / "input" / "context"
    if context.is_dir():
        return [{"path": str(path.relative_to(context)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(item for item in context.rglob("*") if item.is_file())]
    named = ((record or {}).get("input") or {}).get("context_manifest")
    if named and (Path(directory) / named).is_file():
        return json.loads((Path(directory) / named).read_text(encoding="utf-8"))
    return []


def input_hash(directory, record):
    """sha256 over the pinned prompt, agent JSON, context manifest, and schema, as they sit in the fixture."""
    directory = Path(directory)
    digest = hashlib.sha256()
    inputs, launch = record.get("input") or {}, record.get("launch") or {}
    for name in (inputs.get("prompt"), inputs.get("agent"), launch.get("json_schema")):
        digest.update((name or "").encode("utf-8") + b"\0")
        try:
            digest.update((directory / name).read_bytes() if name else b"")
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    digest.update(json.dumps(context_manifest(directory, record), sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _definition_sha256(directory, record, pinned_hash):
    """What a rewrite changes: the checks, the judged layer, the rubric, and the input."""
    judged = record.get("judged")
    rubric = None
    if judged:
        try:
            rubric = (Path(directory) / judged["rubric"]).read_text(encoding="utf-8")
        except OSError:
            rubric = None
    return _sha({"structural": record.get("structural"), "judged": judged, "rubric": rubric, "input_hash": pinned_hash})


def _role_of(record, agents):
    role = (record.get("launch") or {}).get("role")
    if role:
        if role not in agents:
            raise FixtureError("launch.role is %r and input.agent defines %s" % (role, ", ".join(sorted(agents)) or "nothing"))
        return role
    if len(agents) != 1:
        raise FixtureError("launch.role is not set and input.agent defines %d agents" % len(agents))
    return next(iter(agents))


def render_input(directory, record, root):
    """`(prompt, agents, schema_text, deliveries)` a run sends: the pinned pack with the current subject put into it.

    Each subject file reaches the run by one route: a role's `agent.md` becomes the `--agents`
    description and prompt, a schema under `schemas/` the pinned `--json-schema`, text pinned under
    `input/subject/` is replaced where it sits in the prompt, and a skill's directory is delivered
    into the run's project as `.claude/skills/<name>/` (`deliveries`, pairs of the project path and
    the source directory). A subject file no route carries is refused: a change to it could never
    be caught, and a fixture that silently ran the old subject would pass forever.

    The texts still carry the `{harness}`, `{project}`, and `{run}` placeholders, which each run
    fills with its own paths; the cache key is taken before that, so it is the same on every run.
    """
    directory, root = Path(directory), Path(root)
    inputs, launch = record["input"], record["launch"]
    try:
        prompt = (directory / inputs["prompt"]).read_text(encoding="utf-8")
        agents = json.loads((directory / inputs["agent"]).read_text(encoding="utf-8"))
        schema_text = (directory / launch["json_schema"]).read_text(encoding="utf-8") if launch.get("json_schema") else None
    except (OSError, ValueError) as failure:
        raise FixtureError("%s: the pinned input cannot be read: %s" % (record["id"], failure))
    role = _role_of(record, agents)
    subject = record["subject"]
    deliveries = []
    for relative in [subject["path"]] + list(subject.get("also") or []):
        current_path = root / relative
        if not current_path.is_file():
            raise FixtureError("%s: the subject file %s is not under %s" % (record["id"], relative, root))
        current = current_path.read_text(encoding="utf-8")
        pinned = directory / "input" / "subject" / relative
        skill = _SKILL_FILE_RE.match(relative)
        carried = False
        if _ROLE_FILE_RE.match(relative):
            description, body = _role_parts(current, relative)
            agents[role] = dict(agents[role], description=description, prompt=body)
            carried = True
        elif relative.startswith("schemas/") and relative.endswith(".json") and schema_text is not None:
            schema_text = current
            carried = True
        if pinned.is_file():
            old = pinned.read_text(encoding="utf-8").strip()
            if old != current.strip():
                if not old or old not in prompt:
                    raise FixtureError("%s: the pinned text of %s is not in %s, so a change to it cannot reach the run"
                                       % (record["id"], relative, inputs["prompt"]))
                prompt = prompt.replace(old, current.strip())
            carried = True
        if skill:
            delivery = (".claude/skills/%s" % skill.group(2), str(root / skill.group(1)))
            if delivery not in deliveries:
                deliveries.append(delivery)
            carried = True
        if not carried:
            raise FixtureError("%s: nothing carries %s into a run (it is not a role's agent.md, a pinned schema, a skill, or text "
                               "pinned under input/subject/), so a change to it could not be caught" % (record["id"], relative))
    return prompt, agents, schema_text, deliveries


def _delivered(deliveries):
    """The files `render_input` delivers into a run's project, as manifest entries, so a change to one is a new cache key."""
    entries = []
    for target, source in deliveries:
        for path in sorted(item for item in Path(source).rglob("*") if item.is_file()):
            entries.append({"path": "%s/%s" % (target, path.relative_to(source)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return entries


def _role_parts(text, relative):
    try:
        frontmatter, body = load_document(text)
    except FrontmatterError as failure:
        raise FixtureError("%s: %s" % (relative, failure))
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip() or not body.strip():
        raise FixtureError("%s needs a description and a body: they are the --agents description and prompt" % relative)
    return description.strip(), body.strip()


def _fill(text, values):
    for name in PLACEHOLDERS:
        text = text.replace("{%s}" % name, str(values[name]))
    return text


# --- the cache ------------------------------------------------------------------------------------


def _cache_root():
    return projects.home() / CACHE


def _check_cache_root():
    """Refuse a cache under `~/.claude/`, before anything is launched or written.

    A subject runs in a project inside the cache, and the worker settings of decision 4 deny
    `Edit(~/.claude/**)`, so a subject there can write nothing: the first live recording, made with
    `WAYLINE_HOME` under `~/.claude/jobs/`, had every write of all three samples refused
    (`docs/verification/m6.md`), and the fixture failed for the harness's reason rather than the subject's.
    """
    root = _cache_root().resolve()
    claude = (Path.home() / ".claude").resolve()
    if root == claude or root.is_relative_to(claude):
        raise FixtureError("the fixture cache %s is under %s, where the worker settings deny every edit (Edit(~/.claude/**)), "
                           "so a subject run there could write nothing; point WAYLINE_HOME elsewhere" % (root, claude))


def _slot(kind, key, name):
    return _cache_root() / kind / key / name


def _cached(slot, marker):
    """The latest attempt under `slot` that finished (it holds `marker`), or None."""
    if not slot.is_dir():
        return None
    finished = [attempt for attempt in slot.iterdir() if attempt.name.isdigit() and (attempt / marker).is_file()]
    return max(finished, key=lambda attempt: int(attempt.name)) if finished else None


def _fresh(slot):
    """The first unused attempt directory under `slot`: a run never reuses or removes an earlier one."""
    slot.mkdir(parents=True, exist_ok=True)
    number = 1
    while (slot / str(number)).exists():
        number += 1
    attempt = slot / str(number)
    attempt.mkdir()
    return attempt


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cost_of(stored):
    usage = stored.get("usage") or {}
    return {
        "turns": int(stored.get("num_turns") or 0),
        "input_tokens": sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


def _stored(envelope):
    parsed = worker.parse_stream(envelope.stream_path) if envelope.stream_path else worker.Parsed()
    result = parsed.result if isinstance(parsed.result, dict) else {}
    return {
        "session_id": envelope.session_id, "model": envelope.model,
        "structured_output": result.get("structured_output"),
        "is_error": envelope.is_error, "subtype": envelope.subtype, "num_turns": envelope.num_turns,
        "usage": envelope.usage, "exit_code": envelope.exit_code, "errors": list(envelope.errors),
        "rate_limit_events": [event.as_dict() for event in envelope.rate_limit_events],
        "stream": str(envelope.stream_path) if envelope.stream_path else None,
        # What the session said last when it returned nothing: an API error ends a session with a success result.
        "result_text": (envelope.result_text or result.get("result") or "")[:RESULT_TEXT_CHARS] if result.get("structured_output") is None else None,
    }


def _refused(stored):
    return any((event or {}).get("status") == "rejected" for event in stored.get("rate_limit_events") or [])


# --- running --------------------------------------------------------------------------------------


@dataclass
class Sample:
    """One subject run and what the two layers made of it."""

    index: int
    cached: bool
    session_id: Optional[str]
    checks: list = field(default_factory=list)
    verdict: Optional[dict] = None
    place: Optional[str] = None

    @property
    def structural_passed(self):
        return bool(self.checks) and all(check.passed for check in self.checks)

    def as_dict(self):
        return {"index": self.index, "cached": self.cached, "session_id": self.session_id, "place": self.place,
                "structural_passed": self.structural_passed, "checks": [check.as_dict() for check in self.checks],
                "verdict": self.verdict}


@dataclass
class FixtureRun:
    """One fixture's run: the counts the runner prints, the verdict on the change, and the samples behind them."""

    id: str
    n: int = 0
    at_least: Optional[int] = None
    structural: int = 0
    judged: Optional[int] = None
    has_judged: bool = False
    passed: bool = False
    regression: bool = False
    gating: bool = False
    quarantined: bool = False
    flake: bool = False
    partial: bool = False
    skipped: Optional[str] = None
    baseline: Optional[dict] = None
    cost: dict = field(default_factory=lambda: {"turns": 0, "input_tokens": 0, "output_tokens": 0})
    sessions: int = 0
    cached: int = 0
    samples: list = field(default_factory=list)
    resets_at: Optional[int] = None

    def as_dict(self):
        return {key: getattr(self, key) for key in ("id", "n", "at_least", "structural", "judged", "passed", "regression", "gating",
                                                   "quarantined", "flake", "partial", "skipped", "baseline", "cost", "sessions", "cached")}


@dataclass
class SuiteResult:
    runs: list
    exit_code: int
    stopped: Optional[str] = None


class _Budget:
    """What the suite may still spend: the turn ceiling stops the judge, and a refused session stops every launch.

    `fixtures.max_turns_per_suite` skips the remaining judged samples and still runs the free layer
    (decision 12), so subject sessions go on after the ceiling; a usage window that refused a session
    would refuse the next one too, so nothing is launched after that.
    """

    def __init__(self, limit):
        self.limit = limit
        self.spent = 0
        self.refused = None

    @property
    def spent_out(self):
        return self.limit is not None and self.spent >= self.limit

    def stop_reason(self):
        if self.refused:
            return self.refused
        return ("the turn ceiling (fixtures.max_turns_per_suite = %d) is spent (%d turns): the remaining judged samples were "
                "skipped, and the structural layer still ran" % (self.limit, self.spent))


def discover(root=HARNESS_ROOT):
    """Every `fixtures/<kind>/<slug>/` under `root` that holds a `fixture.json`, sorted by id."""
    base = Path(root) / FIXTURES
    return sorted(path.parent for kind in FIXTURE_KINDS for path in (base / kind).glob("*/fixture.json"))


def fixture_id(directory):
    return "%s/%s" % (Path(directory).parent.name, Path(directory).name)


def load_fixture(directory):
    """`fixture.json`, validated against the `fixture` schema."""
    path = Path(directory) / "fixture.json"
    try:
        record = _read_json(path)
    except (OSError, ValueError) as failure:
        raise FixtureError("%s cannot be read: %s" % (path, failure))
    errors = validate(record, load_schema("fixture"))
    if errors:
        raise FixtureError("%s is not a valid fixture: %s" % (path, "; ".join("%s: %s" % (error.path, error.message) for error in errors[:5])))
    if record["id"] != fixture_id(directory):
        raise FixtureError("%s names itself %s" % (path, record["id"]))
    return record


def _raw_record(directory):
    """`fixture.json` as JSON, unvalidated, or None: what a fixture that no longer loads still says about its baseline."""
    try:
        value = _read_json(Path(directory) / "fixture.json")
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _cannot_run(run, record, reason):
    """A fixture the runner cannot load, render, or launch: named, and a regression when it passed at its baseline.

    A change that breaks a subject so badly the fixture cannot even run has not stopped it from
    failing; skipping it quietly would let exactly that change through.
    """
    record = record if isinstance(record, dict) else {}
    baseline = record.get("baseline") if isinstance(record.get("baseline"), dict) else None
    run.skipped = reason
    run.baseline = baseline
    run.quarantined = (record.get("quarantine") or {}).get("status") == "quarantined"
    run.regression = bool(baseline and baseline.get("passed"))
    run.gating = run.regression and not run.quarantined
    return run


def _unrunnable(record, directory):
    if record["kind"] == "conductor":
        return "a conductor fixture is a recorded journal the unit suite replays with the fake worker"
    if not record["input"].get("agent"):
        return "input.agent is null: there is no --agents JSON to launch"
    for name in (record["input"]["prompt"], record["input"]["agent"]):
        if not (Path(directory) / name).is_file():
            return "%s is not in the fixture" % name
    return None


def run_fixture(directory, root=HARNESS_ROOT, policy=None, use_cache=True, budget=None, samples=None, stop_at_failure=False):
    """Run one fixture, update its `last_run` and `quarantine` (and `baseline` on a rewrite), write `runs/`.

    With `stop_at_failure` no sample is launched after one fails its structural checks, which must pass n of n:
    the run is then decided over the samples it took, what a change's proof needs and all it pays for.
    """
    directory, root = Path(directory), Path(root)
    policy = projects.policy_for(None) if policy is None else policy
    budget = _Budget(None) if budget is None else budget
    _check_cache_root()
    try:
        record = load_fixture(directory)
    except FixtureError as failure:
        return _cannot_run(FixtureRun(fixture_id(directory)), _raw_record(directory), str(failure))
    run = FixtureRun(record["id"], baseline=record.get("baseline"))
    reason = _unrunnable(record, directory)
    if reason:
        run.skipped = reason
        return run
    settings = policy.get("fixtures") or {}
    judged = record.get("judged")
    run.has_judged = bool(judged)
    run.n = int(samples or (judged["sample_size"] if judged else settings.get("sample_size", 3)))
    if judged:
        run.at_least = run.n if judged.get("strict") else min(int(judged["pass_rule"]["at_least"]), run.n)
    try:
        rendered = render_input(directory, record, root)
        current_subject = subject_sha256(record, root)
        pinned_hash = input_hash(directory, record)
        manifest = context_manifest(directory, record) + _delivered(rendered[3])
    except (FixtureError, OSError, ValueError) as failure:
        return _cannot_run(run, record, str(failure))

    stopped = False
    try:
        for index in range(run.n):
            run.samples.append(_subject_sample(directory, record, rendered, manifest, index, use_cache, budget, run, policy))
            if stop_at_failure and not run.samples[-1].structural_passed:
                run.n = len(run.samples)
                break
        if judged and all(sample.structural_passed for sample in run.samples):
            _judge_samples(directory, record, judged, policy, use_cache, budget, run)
    except _CostStop:
        stopped = True
    except (worker.LaunchError, worker.RoleError, FixtureError, OSError, ValueError) as failure:
        return _cannot_run(run, record, "the launch failed: %s" % failure)
    run.structural = sum(1 for sample in run.samples if sample.structural_passed)
    # A sample that failed the free layer settles the fixture even when the suite stopped: it cannot pass any more.
    decided = not stopped or run.structural < len(run.samples)
    run.partial = not decided
    structural_ok = len(run.samples) == run.n and run.structural == run.n
    judged_ok = True if not judged else (run.judged is not None and run.judged >= run.at_least)
    run.passed = decided and structural_ok and judged_ok

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if decided:
        _settle(directory, record, run, current_subject, pinned_hash, structural_ok, judged_ok if judged and structural_ok else None)
    _write_runs(directory, run, stamp)
    return run


def _subject_sample(directory, record, rendered, manifest, index, use_cache, budget, run, policy=None):
    prompt, agents, schema_text, _ = rendered
    launch = record["launch"]
    key = _sha({"prompt": prompt, "agent": json.dumps(agents, sort_keys=True), "manifest": manifest,
                "schema": schema_text, "model": launch["model"], "effort": launch["effort"]})
    slot = _slot("subject", key, str(index))
    hit = _cached(slot, "envelope.json") if use_cache else None
    if hit is None and budget.refused:
        raise _CostStop()
    if hit is not None:
        attempt, stored, cached = hit, _read_json(hit / "envelope.json"), True
    else:
        attempt = _fresh(slot)
        stored = _launch_subject(directory, record, rendered, attempt, policy)
        cached = False
        if _refused(stored) and stored.get("structured_output") is None:
            # Kept under its own name and never served from the cache: a refusal says nothing about the subject.
            _write_json(attempt / "refused.json", stored)
            _account(run, budget, stored, cached)
            budget.refused = "a usage window refused the subject session %s: nothing more is launched" % stored.get("session_id")
            raise _CostStop()
        if _timed_out(stored):
            # Kept under its own name and never served from the cache: a session stopped at its time limit failed this
            # sample, and says nothing of what the subject returns under another limit.
            _write_json(attempt / "timeout.json", stored)
        else:
            _write_json(attempt / "envelope.json", stored)
    _account(run, budget, stored, cached)
    project_dir = attempt / "project"
    schema = json.loads(_fill(schema_text, _values(attempt))) if schema_text is not None else None
    ended_ok = stored.get("subtype") == "success" and not stored.get("is_error")
    checks = structural_checks(record.get("structural"), stored.get("structured_output"), project_dir,
                               trace=stored.get("stream"), fixture_dir=directory, schema=schema, ended_ok=ended_ok)
    sample = Sample(index, cached, stored.get("session_id"), checks, place=str(attempt))
    sample.stored = stored
    return sample


def _values(attempt):
    return {"harness": str(HARNESS_ROOT), "project": str(attempt / "project"), "run": str(attempt / "session")}


def _timed_out(stored):
    """Whether a subject session was stopped at its time limit before it returned a result."""
    return stored.get("structured_output") is None and any(str(error).startswith("timeout:") for error in stored.get("errors") or [])


def subject_minutes(record, policy):
    """A subject session's time limit: the fixture's own `max_minutes`, else the budget its role launches with.

    The role's `cost_hint` names the budget (`policy.budget.<hint>.max_minutes`), so a fixture of the planner, a
    large-budget role, is given the time the planner is given; a role the harness does not have runs on the small one.
    """
    launch = record.get("launch") or {}
    if launch.get("max_minutes"):
        return launch["max_minutes"]
    sidecar = HARNESS_ROOT / "roles" / str(launch.get("role") or "") / "wayline.json"
    try:
        hint = json.loads(sidecar.read_text(encoding="utf-8")).get("cost_hint") if launch.get("role") else None
    except (OSError, ValueError):
        hint = None
    return ((policy or {}).get("budget") or {}).get(hint or "", {}).get("max_minutes") or SUBJECT_MAX_MINUTES


def _launch_subject(directory, record, rendered, attempt, policy=None):
    prompt, agents, schema_text, deliveries = rendered
    launch = record["launch"]
    values = _values(attempt)
    project_dir = attempt / "project"
    context = Path(directory) / "input" / "context"
    if context.is_dir():
        shutil.copytree(context, project_dir)
    else:
        project_dir.mkdir()
    for target, source in deliveries:  # the current skill replaces whatever copy the pinned context holds
        destination = project_dir / target
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
    env = {name: _fill(value, values) for name, value in (launch.get("env") or {}).items()}
    if "TICKET_TOUCHES" in env:  # a ticket's worker commits on its branch
        _git_init(project_dir, "ticket/%s" % env["WAYLINE_TICKET"] if env.get("WAYLINE_TICKET") else None)
    env["WAYLINE_RUN"] = values["run"]
    env["PATH"] = os.pathsep.join([str(HARNESS_ROOT / "bin")] + [entry for entry in os.environ.get("PATH", os.defpath).split(os.pathsep) if entry])
    schema_path = settings_path = None
    if schema_text is not None:
        schema_path = attempt / "schema.json"
        atomic_write(schema_path, _fill(schema_text, values))
    if launch.get("settings"):
        settings_path = attempt / "settings.json"
        atomic_write(settings_path, _fill((Path(directory) / launch["settings"]).read_text(encoding="utf-8"), values))
    agent_json = json.loads(_fill(json.dumps(agents), values))
    request = worker.LaunchRequest(
        role=_role_of(record, agents), model=launch["model"], effort=launch["effort"], prompt=_fill(prompt, values),
        agent_json=agent_json, allowed_tools=list(launch.get("allowed_tools") or []),
        disallowed_tools=list(launch.get("disallowed_tools") or []), settings_path=settings_path,
        add_dirs=[_fill(entry, values) for entry in launch.get("add_dirs") or []], cwd=str(project_dir), env=env,
        schema_path=schema_path, max_minutes=subject_minutes(record, policy))
    return _stored(worker.launch(request))


def _git_init(directory, branch=None):
    """The run's project as a ticket's worker finds its worktree: the input committed on `main`, checked out on `branch`."""
    identity = ["-c", "user.name=wayline fixture", "-c", "user.email=fixture@wayline.invalid"]
    steps = [["init", "-q", "-b", "main"], ["add", "-A"], identity + ["commit", "-q", "--allow-empty", "-m", "fixture input"]]
    if branch:
        steps.append(["checkout", "-q", "-b", branch])
    for arguments in steps:
        subprocess.run(["git", "-C", str(directory)] + arguments, capture_output=True, text=True)


def _account(run, budget, stored, cached):
    run.sessions += 1
    for event in stored.get("rate_limit_events") or []:
        window = (event or {}).get("seven_day") or {}
        if window.get("resets_at"):
            run.resets_at = max(run.resets_at or 0, int(window["resets_at"]))
    if cached:
        run.cached += 1
        return
    cost = _cost_of(stored)
    for name, value in cost.items():
        run.cost[name] += value
    budget.spent += cost["turns"]


def _judge_samples(directory, record, judged, policy, use_cache, budget, run):
    rubric = (Path(directory) / judged["rubric"]).read_text(encoding="utf-8")
    judge = judged["judge"]
    model, effort = judge["model"], judge["effort"]
    votes = int(judge.get("votes") or 1)
    subject_sessions = {sample.session_id for sample in run.samples if sample.session_id}
    role = worker.read_role(JUDGE_ROLE)
    count = 0
    for sample in run.samples:
        shown = [(path, jsonpath(sample.stored.get("structured_output"), path)) for path in judged["show_judge"]]
        key = _sha({"rubric": rubric, "model": model, "effort": effort, "output": shown})
        answers = []
        for vote in range(votes):
            slot = _slot("judge", key, "%d-%d" % (sample.index, vote))
            hit = _cached(slot, "verdict.json") if use_cache else None
            if hit is None and (budget.refused or budget.spent_out):
                raise _CostStop()
            if hit is not None:
                answer, cached = _read_json(hit / "verdict.json"), True
            else:
                attempt = _fresh(slot)
                answer = _launch_judge(role, model, effort, _judge_prompt(rubric, shown, role), attempt, subject_sessions)
                # Only a usable verdict is served again; one the judge could not give is kept under its own name and asked again.
                _write_json(attempt / ("verdict.json" if answer["usable"] else "unusable.json"), answer)
                cached = False
            _account(run, budget, answer, cached)
            answers.append(answer)
            if answer.get("refused"):
                budget.refused = "a usage window refused the judge session %s: nothing more is launched" % answer.get("session_id")
                raise _CostStop()
        passes = sum(1 for answer in answers if answer["verdict"] == "pass")
        chosen = next(answer for answer in answers if (answer["verdict"] == "pass") == (passes * 2 > votes))
        sample.verdict = {"verdict": "pass" if passes * 2 > votes else "fail", "reason": chosen["reason"],
                          "votes": [{"verdict": answer["verdict"], "session_id": answer.get("session_id")} for answer in answers]}
        count += 1 if sample.verdict["verdict"] == "pass" else 0
    run.judged = count


def _judge_prompt(rubric, shown, role):
    lines = ["# The rubric", "", rubric.strip(), "", "# The output", "",
             "These are the fields of one output the fixture shows you, each under the JSONPath it was read at. "
             "Nothing else of the output, and nothing of the session that wrote it, is yours to judge.", ""]
    for path, values in shown:
        lines += ["## `%s`" % path, ""]
        if not values:
            lines += ["[absent: the path matched nothing in this output]", ""]
            continue
        value = values[0] if len(values) == 1 and "*" not in path else values
        lines += ["```json", json.dumps(value, indent=2, ensure_ascii=False), "```", ""]
    parts = ["\n".join(lines).rstrip(), role.protocol.strip(),
             "# Your answer\n\nReturn `verdict` (`pass` or `fail`) and `reason` (one paragraph) through the structured output."]
    return "\n\n".join(part for part in parts if part) + "\n"


def _launch_judge(role, model, effort, prompt, attempt, subject_sessions):
    request = worker.LaunchRequest(
        role=JUDGE_ROLE, model=model, effort=effort, prompt=prompt, agent_json=role.agent_json(model, effort, JUDGE_MAX_TURNS),
        allowed_tools=[], disallowed_tools=list(role.disallowed_tools), settings_path=None, add_dirs=[], cwd=str(attempt),
        env={"WAYLINE_RUN": str(attempt / "session")}, schema_path=str(SCHEMAS_DIR / (VERDICT_SCHEMA + ".json")),
        max_minutes=JUDGE_MAX_MINUTES)
    envelope = worker.launch(request)
    stored = _stored(envelope)
    answer = envelope.structured_output
    verdict = {"session_id": envelope.session_id, "model": envelope.model, "num_turns": envelope.num_turns,
               "usage": envelope.usage, "rate_limit_events": stored["rate_limit_events"], "refused": False, "usable": False}
    if envelope.session_id and envelope.session_id in subject_sessions:
        verdict.update(verdict="fail", reason="the judge answered from the subject's session %s; a verdict must come from a fresh session" % envelope.session_id)
    elif answer is None:
        verdict.update(verdict="fail", reason="the judge returned no usable verdict: %s" % ("; ".join(envelope.errors) or envelope.subtype or "no structured output"))
        verdict["refused"] = _refused(stored)
    else:
        verdict.update(verdict=answer["verdict"], reason=answer["reason"], usable=True)
    return verdict


def _score(count, n):
    return None if count is None else "%d/%d" % (count, n)


def _settle(directory, record, run, current_subject, pinned_hash, structural_ok, judged_ok):
    """Measure this run against the last one: a flake, a stable run, a restore, a rewrite. Then decide whether it gates."""
    now = now_ts()
    outcome = {"structural": structural_ok, "judged": judged_ok}
    definition = _definition_sha256(directory, record, pinned_hash)
    last = record.get("last_run")
    quarantine = record["quarantine"]
    quarantine.setdefault("stable_runs", 0)
    quarantine.setdefault("restored_at", None)
    quarantine.setdefault("counted_from", 0)
    if last is not None and last.get("definition_sha256") not in (None, definition):
        quarantine.update(status="active", restored_at=now, stable_runs=0, counted_from=len(quarantine["flakes"]))
        record["baseline"] = {"recorded_at": now, "subject_sha256": current_subject, "input_hash": pinned_hash,
                              "structural": _score(run.structural, run.n), "judged": _score(run.judged, run.n),
                              "passed": run.passed, "unstable": _unstable(run)}
    elif last is not None and last.get("subject_sha256") == current_subject and last.get("input_hash") == pinned_hash:
        if last.get("outcome") != outcome:
            run.flake = True
            before = last.get("outcome") or {}
            flipped = [layer for layer in ("structural", "judged") if before.get(layer) != outcome[layer]]
            quarantine["flakes"].append({"ts": now, "layer": flipped[0] if len(flipped) == 1 else "both", "from": before, "to": outcome})
            quarantine["stable_runs"] = 0
            if len(quarantine["flakes"]) - quarantine["counted_from"] >= quarantine["flake_limit"]:
                quarantine["status"] = "quarantined"
        else:
            quarantine["stable_runs"] += 1
            if quarantine["status"] == "quarantined" and quarantine["stable_runs"] >= quarantine["stable_runs_to_restore"]:
                quarantine.update(status="active", restored_at=now, stable_runs=0, counted_from=len(quarantine["flakes"]))
    else:
        quarantine["stable_runs"] = 0
    record["last_run"] = {"ts": now, "subject_sha256": current_subject, "input_hash": pinned_hash, "definition_sha256": definition,
                          "structural": _score(run.structural, run.n), "judged": _score(run.judged, run.n), "outcome": outcome}
    run.baseline = record.get("baseline")
    run.quarantined = quarantine["status"] == "quarantined"
    run.regression = bool(run.baseline and run.baseline.get("passed")) and not run.passed
    run.gating = run.regression and not run.quarantined
    _write_json(Path(directory) / "fixture.json", record)


def _unstable(run):
    return any(count is not None and 0 < count < run.n for count in (run.structural, run.judged))


def _write_runs(directory, run, stamp):
    target = Path(directory) / "runs" / stamp
    target.mkdir(parents=True, exist_ok=False)
    for sample in run.samples:
        _write_json(target / ("%d.json" % sample.index), sample.as_dict())
    _write_json(target / "summary.json", run.as_dict())


def sample_failures(run):
    """One line per sample that failed: the checks it failed with their details, the session's own error, the judge's reason."""
    lines = []
    for sample in run.samples:
        said = ["%s failed: %s" % ((check.check or {}).get("check"), check.detail) for check in sample.checks if not check.passed]
        stored = getattr(sample, "stored", None) or {}
        if said and (stored.get("result_text") or stored.get("errors")):
            said.append("the session said: %s" % (stored.get("result_text") or stored["errors"][0]))
        if not said and sample.verdict and sample.verdict.get("verdict") == "fail":
            said.append("the judge said fail: %s" % sample.verdict.get("reason"))
        if said:
            lines.append("sample %d: %s" % (sample.index + 1, "; ".join(said)))
    return lines


def describe(run):
    """The line the runner prints for one fixture: the layers, the baseline, the delta, the cost, the verdict."""
    if run.skipped:
        if run.gating:
            return "%s: REGRESSION, cannot run: %s" % (run.id, run.skipped)
        if run.regression:
            return "%s: cannot run, quarantined (reported, not gating): %s" % (run.id, run.skipped)
        return "%s: skipped (%s)" % (run.id, run.skipped)
    structural = "structural %d/%d" % (run.structural, run.n)
    if not run.has_judged:
        judged = "judged -"
    elif run.judged is None:
        judged = "judged skipped (%s)" % ("the run stopped" if run.partial else "the structural layer failed")
    else:
        judged = "judged %d/%d (at least %d)" % (run.judged, run.n, run.at_least)
    baseline = run.baseline
    if baseline:
        base = "baseline structural %s judged %s" % (baseline.get("structural"), baseline.get("judged") or "-")
        deltas = []
        for name, now, then in (("structural", run.structural, baseline.get("structural")), ("judged", run.judged, baseline.get("judged"))):
            if now is not None and then:
                deltas.append("%s %+d" % (name, now - int(str(then).split("/")[0])))
        delta = "delta " + (", ".join(deltas) if deltas else "n/a")
    else:
        base, delta = "baseline none", "delta n/a"
    cost = "cost %d turns, %d input tokens, %d output tokens (%d of %d sessions cached)" % (
        run.cost["turns"], run.cost["input_tokens"], run.cost["output_tokens"], run.cached, run.sessions)
    if run.partial:
        verdict = "partial (stopped for cost)"
    elif run.gating:
        verdict = "REGRESSION"
    elif run.regression:
        verdict = "regression, quarantined: reported, not gating"
    else:
        verdict = "pass" if run.passed else "fail"
    flags = "".join(flag for flag, on in ((" [flake]", run.flake), (" [quarantined]", run.quarantined and not run.regression)) if on)
    return "%s: %s, %s, %s, %s, %s: %s%s" % (run.id, structural, judged, base, delta, cost, verdict, flags)


# --- the suite ------------------------------------------------------------------------------------


def _suite_state_path():
    return projects.home() / SUITE_STATE


def _changed(directory, root):
    """Whether `--changed` selects a fixture: its subject changed since it last ran, or it still fails a baseline that passed.

    The second half keeps a regression selected until it is fixed: the run that caught it records
    the new subject hash, and without it the next `--changed` run would pass by selecting nothing.
    """
    try:
        record = load_fixture(directory)
    except FixtureError:
        return True
    last, baseline = record.get("last_run") or {}, record.get("baseline") or {}
    if baseline.get("passed") and last and False in (last.get("outcome") or {}).values():
        return True
    reference = last.get("subject_sha256") or baseline.get("subject_sha256") or record["subject"].get("sha256")
    return subject_sha256(record, root) != reference


def run(root=HARNESS_ROOT, ids=None, changed=False, suite=False, force=False, use_cache=True, policy=None, now=None):
    """Run the fixtures `ids` names, the changed ones (the default), or the full suite; print one line each.

    The full suite runs at most once per weekly window: until the seven-day reset the last suite's
    sessions reported (or seven days after it started, when none did), a second one stops with exit
    2 unless `force`.
    """
    root = Path(root)
    policy = projects.policy_for(None) if policy is None else policy
    clock = time.time() if now is None else now
    found = discover(root)
    if ids:
        by_id = {fixture_id(directory): directory for directory in found}
        unknown = [identifier for identifier in ids if identifier not in by_id]
        if unknown:
            raise FixtureError("no fixture %s under %s" % (", ".join(unknown), root / FIXTURES))
        selected = [by_id[identifier] for identifier in ids]
    elif suite:
        state_path = _suite_state_path()
        state = _read_json(state_path) if state_path.is_file() else {}
        last = state.get("last_suite")
        if last and not force:
            opens = last.get("seven_day_resets_at") or (last["started"] + WEEK_SECONDS)
            if clock < opens:
                reason = ("the full suite already ran in this weekly window (at %s); it may run again from %s, or now with --force"
                          % (_epoch(last["started"]), _epoch(opens)))
                print("wayline fixture run: " + reason)
                return SuiteResult([], EXIT_COST, reason)
        selected = found
    else:
        selected = [directory for directory in found if _changed(directory, root)]

    budget = _Budget((policy.get("fixtures") or {}).get("max_turns_per_suite"))
    runs = []
    for directory in selected:
        outcome = run_fixture(directory, root, policy, use_cache, budget)
        runs.append(outcome)
        print(describe(outcome), flush=True)
    stopped = budget.stop_reason() if any(outcome.partial for outcome in runs) else None
    if stopped:
        print("wayline fixture run: stopped: " + stopped)
    if suite:
        resets = [outcome.resets_at for outcome in runs if outcome.resets_at]
        _write_json(_suite_state_path(), {"last_suite": {"started": clock, "seven_day_resets_at": max(resets) if resets else None}})
    if not selected:
        print("wayline fixture run: no fixture to run")
    code = EXIT_REGRESSION if any(outcome.gating for outcome in runs) else (EXIT_COST if stopped else 0)
    return SuiteResult(runs, code, stopped)


def _epoch(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- recording ------------------------------------------------------------------------------------


def _session_directory(project, session_id, named):
    """The launch directory of `session_id`: the ticket's attempt the journal names, else the stream that carries it."""
    sessions = Path(project) / "research" / "sessions"
    candidates = []
    for event in named:
        payload = event.get("payload") or {}
        ticket, attempt = payload.get("ticket", event.get("ticket")), payload.get("attempt")
        if ticket is not None and attempt is not None:
            candidates.append(sessions / str(ticket) / str(attempt))
    candidates += sorted(path.parent for path in sessions.glob("**/stream.jsonl") if not path.parent.name.startswith("resume-"))
    for candidate in candidates:
        if (candidate / "stream.jsonl").is_file() and worker.parse_stream(candidate / "stream.jsonl").session_id == session_id:
            return candidate
    raise FixtureError("the journal names session %s but no directory under %s holds its stream" % (session_id, sessions))


def _parse_command(command):
    """The launch fields of a spelled launch line (`env.json`'s `command`)."""
    fields = {"allowed_tools": [], "disallowed_tools": [], "add_dirs": []}
    lists = {"--allowedTools": "allowed_tools", "--disallowedTools": "disallowed_tools"}
    singles = {"--agent": "role", "--model": "model", "--effort": "effort", "--fallback-model": "fallback_model"}
    index = 0
    while index < len(command):
        token = command[index]
        if token in lists:
            index += 1
            while index < len(command) and not command[index].startswith("--"):
                fields[lists[token]].append(command[index])
                index += 1
            continue
        if token in singles and index + 1 < len(command):
            fields[singles[token]] = command[index + 1]
            index += 2
            continue
        if token == "--add-dir" and index + 1 < len(command):
            fields["add_dirs"].append(command[index + 1])
            index += 2
            continue
        index += 1
    return fields


def _templater(replacements):
    ordered = sorted(((path, name) for path, name in replacements.items() if path), key=lambda item: -len(item[0]))

    def template(text):
        for path, name in ordered:
            text = re.sub(re.escape(path) + r"(?![\w.-])", lambda _: "{%s}" % name, text)
        return text

    return template


def _proposals(output):
    """`schema_valid`, then one `path_equals` per scalar and one `path_count` per array, for the author to prune."""
    proposals = [{"check": "schema_valid"}]

    def walk(value, steps):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, steps + [key])
        elif isinstance(value, list):
            proposals.append({"check": "path_count", "path": _path_for(steps), "min": len(value), "max": len(value)})
        else:
            proposals.append({"check": "path_equals", "path": _path_for(steps), "value": value})

    if isinstance(output, dict):
        walk(output, [])
    return proposals


def _context_paths(project, ticket):
    """The ticket file and the files its context pack names, as paths under the project."""
    if ticket is None:
        return []
    files = sorted((Path(project) / "research" / "tickets").glob("%02d-*.md" % int(ticket)))
    if not files:
        return []
    paths = [str(files[0].relative_to(project))]
    try:
        frontmatter, _ = load_document(files[0].read_text(encoding="utf-8"))
    except (OSError, FrontmatterError):
        return paths
    for locator in frontmatter.get("context_pack") or []:
        relative = str(locator).split("#", 1)[0]
        if relative and relative not in paths:
            paths.append(relative)
    return paths


def record(project, session_id, kind, slug, root=HARNESS_ROOT, subject_path=None, also=(), context=(), rubric=None,
           show_judge=(), runs=None, change_record=None, policy=None, reason=None):
    """Record a fixture from one journaled session; returns the fixture's directory.

    The session directory is resolved from the journal; its prompt, agent JSON, schema, settings,
    and launch line become `input/` and `launch` with the recording machine's paths replaced by
    `{harness}`, `{project}`, and `{run}`; its result and stream become `recorded/`; the ticket file
    and the files its context pack names (plus `context`) become `input/context/`. The structural
    checks proposed are one `path_equals` per scalar and one `path_count` per array of the recorded
    output. With `runs` (the sample count; None takes the policy's), the fixture is run that many
    times to set the baseline, and a baseline whose samples disagree is flagged unstable. The id is
    linked into `change_record` and, for a skill, into its sidecar's `fixtures`.
    """
    root, project = Path(root), Path(project).resolve()
    policy = projects.policy_for(None) if policy is None else policy
    if kind not in FIXTURE_KINDS or kind == "conductor":
        raise FixtureError("a recorded fixture's kind is one of %s; a conductor fixture is a recorded journal" % ", ".join(k for k in FIXTURE_KINDS if k != "conductor"))
    if not _SLUG_RE.match(slug or ""):
        raise FixtureError("a fixture slug is lowercase letters, digits, and dashes, got %r" % (slug,))
    if runs != 0:
        _check_cache_root()  # the baseline runs in the cache: refuse before anything is recorded
    identifier = "%s/%s" % (kind, slug)
    directory = root / FIXTURES / kind / slug
    if directory.exists():
        raise FixtureError("%s already exists; the recorder never overwrites a fixture" % directory)
    try:
        events, _ = Ledger(project).read_events()
    except (LedgerError, OSError, ValueError) as failure:
        raise FixtureError("the journal of %s cannot be read: %s" % (project, failure))
    named = [event for event in events
             if event.get("session_id") == session_id or (event.get("payload") or {}).get("session_id") == session_id]
    if not named:
        raise FixtureError("the journal of %s names no session %s" % (project, session_id))
    session = _session_directory(project, session_id, named)
    try:
        launched = _read_json(session / "env.json")
        agents_text = (session / "agent.json").read_text(encoding="utf-8")
        prompt_text = (session / "prompt.md").read_text(encoding="utf-8")
        result = _read_json(session / "result.json")
    except (OSError, ValueError) as failure:
        raise FixtureError("the session directory %s is incomplete: %s" % (session, failure))
    fields = _parse_command(launched.get("command") or [])
    environment = launched.get("env") or {}
    first_path = (environment.get("PATH") or "").split(os.pathsep)[0]
    harness = str(Path(first_path).parent) if first_path.endswith(os.sep + "bin") else str(HARNESS_ROOT)
    template = _templater({str(session): "run", launched.get("cwd"): "project", str(project): "project", harness: "harness"})
    agents = json.loads(template(agents_text))
    role = fields.get("role") or (next(iter(agents)) if len(agents) == 1 else None)
    output = result.get("structured_output")
    ticket = next((event.get("ticket") for event in named if event.get("ticket") is not None), None)

    subject_path = subject_path or ("roles/%s/agent.md" % role if kind in ("role", "verifier") and role else None)
    if not subject_path:
        raise FixtureError("a %s fixture names its subject: pass subject_path (--subject)" % kind)
    subject_files = [subject_path] + list(also or [])
    for relative in subject_files:
        if not (root / relative).is_file():
            raise FixtureError("the subject file %s is not under %s" % (relative, root))
        text = (root / relative).read_text(encoding="utf-8").strip()
        carried = (_ROLE_FILE_RE.match(relative) or _SKILL_FILE_RE.match(relative) or (text and text in prompt_text)
                   or (relative.startswith("schemas/") and relative.endswith(".json") and (session / "schema.json").is_file()))
        if not carried:
            raise FixtureError("nothing would carry %s into a run: it is not a role's agent.md, a skill, the pinned schema, or text "
                               "of the session's prompt as it stands now, so a change to it could not be caught" % relative)

    # Built in a scratch directory beside the fixture and renamed into place whole, so a record that fails leaves no
    # half-written fixture behind to block the next attempt. The scratch is the recorder's own, never a fixture.
    parent = root / FIXTURES / kind
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".%s." % slug, suffix=".recording", dir=parent))
    try:
        work.chmod(0o755)
        _write_text(work / "input" / "prompt.md", template(prompt_text))
        _write_json(work / "input" / "agent.json", agents)
        schema_name = None
        if (session / "schema.json").is_file():
            schema_name = "input/schema.json"
            _write_text(work / schema_name, (session / "schema.json").read_text(encoding="utf-8"))
        settings_name = None
        if (session / "settings.json").is_file():
            settings = template((session / "settings.json").read_text(encoding="utf-8"))
            if json.loads(settings):
                settings_name = "input/settings.json"
                _write_text(work / settings_name, settings)
        for relative in subject_files:
            text = (root / relative).read_text(encoding="utf-8").strip()
            if not _ROLE_FILE_RE.match(relative) and not relative.startswith("schemas/") and text and text in prompt_text:
                _write_text(work / "input" / "subject" / relative, text + "\n")
        copied = []
        for relative in _context_paths(project, ticket) + [str(item) for item in context or ()]:
            source = project / relative
            if not source.resolve().is_relative_to(project) or not source.exists() or relative in copied:
                continue
            target = work / "input" / "context" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if source.is_dir() else shutil.copyfile)(source, target)
            copied.append(relative)
        manifest_name = None
        if copied:
            manifest_name = "input/manifest.json"
            _write_json(work / manifest_name, context_manifest(work))
        (work / "recorded").mkdir()
        shutil.copyfile(session / "result.json", work / "recorded" / ("result-%s.json" % session_id))
        _write_text(work / "recorded" / ("trace-%s.jsonl" % session_id), _reduced_trace(session / "stream.jsonl"))

        settings_policy = policy.get("fixtures") or {}
        fixture = {
            "schema_version": 1, "id": identifier, "kind": kind,
            "subject": {"path": subject_path, "sha256": None, "also": list(also or [])},
            "origin": {"project": str(project), "ticket": ticket, "session_id": session_id, "journal_ts": named[0].get("ts"),
                       "change_record": str(change_record) if change_record else None,
                       "reason": reason or "recorded from session %s of %s" % (session_id, project)},
            "launch": {"role": role, "model": fields.get("model"), "effort": fields.get("effort"), "permission_mode": "dontAsk",
                       "max_turns": (agents.get(role) or {}).get("maxTurns"), "output_format": "stream-json", "json_schema": schema_name,
                       "fallback_model": fields.get("fallback_model"), "allowed_tools": fields["allowed_tools"],
                       "disallowed_tools": fields["disallowed_tools"], "add_dirs": [template(entry) for entry in fields["add_dirs"]],
                       "env": {name: template(str(value)) for name, value in environment.items() if name.startswith(("TICKET_", "WAYLINE_"))},
                       "settings": settings_name},
            "input": {"prompt": "input/prompt.md", "agent": "input/agent.json", "context_manifest": manifest_name, "input_hash": None},
            "structural": _proposals(output),
            "baseline": None,
            # policy.json allows 0 for both; a fixture needs at least one flake to quarantine and one run to restore.
            "quarantine": {"status": "active", "flake_limit": max(1, int(settings_policy.get("flake_limit", 2))), "flakes": [],
                           "stable_runs_to_restore": max(1, int(settings_policy.get("stable_runs_to_restore", 3)))},
            "cost": {"per_subject_run": {"turns": result.get("num_turns"), "input_tokens": _cost_of(result)["input_tokens"],
                                         "output_tokens": _cost_of(result)["output_tokens"]}},
        }
        if rubric is not None:
            _write_text(work / "rubric.md", Path(rubric).read_text(encoding="utf-8"))
            judge = settings_policy.get("judge") or {"model": "haiku", "effort": "low"}
            fixture["judged"] = {
                "rubric": "rubric.md",
                "show_judge": list(show_judge) or [_path_for([key]) for key in (output or {})] or ["$"],
                "judge": {"model": judge["model"], "effort": judge["effort"], "tools": [], "votes": 1, "must_differ_from_subject_session": True},
                "sample_size": int(settings_policy.get("sample_size", 3)),
                "pass_rule": {"at_least": int(settings_policy.get("at_least", 2))}, "strict": False}
        fixture["subject"]["sha256"] = subject_sha256(fixture, root)
        fixture["input"]["input_hash"] = input_hash(work, fixture)
        errors = validate(fixture, load_schema("fixture"))
        if errors:
            raise FixtureError("the recorded fixture is not valid: %s" % "; ".join("%s: %s" % (error.path, error.message) for error in errors[:5]))
        _write_json(work / "fixture.json", fixture)
        os.rename(work, directory)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    print("recorded %s from session %s into %s" % (identifier, session_id, directory))
    print("  %d structural checks proposed (schema_valid, then one per scalar and array): prune the incidental ones" % len(fixture["structural"]))

    if change_record:
        change = _read_json(change_record)
        change["fixture"] = identifier
        _write_json(Path(change_record), change)
    if kind == "skill":
        sidecar = (root / subject_path).parent / "wayline.json"
        if sidecar.is_file():
            value = _read_json(sidecar)
            if identifier not in value.setdefault("fixtures", []):
                value["fixtures"].append(identifier)
                _write_json(sidecar, value)

    if runs is None:
        runs = int((fixture.get("judged") or {}).get("sample_size") or settings_policy.get("sample_size", 3))
    if runs:
        outcome = run_fixture(directory, root, policy, use_cache=False, samples=runs)
        print("  baseline: " + describe(outcome))
        fixture = set_baseline(directory, outcome)
        if fixture["baseline"]["unstable"]:
            print("  the baseline is unstable (structural %s, judged %s): tighten the checks or the rubric before it gates anything"
                  % (fixture["baseline"]["structural"], fixture["baseline"]["judged"] or "-"))
    return directory


def set_baseline(directory, outcome, root=None):
    """Write `outcome` into `fixture.json` as the fixture's baseline; returns the record as written.

    The recorder sets it from the first runs of a fixture it just recorded. With `root`, the subject is hashed
    again there first: the evolve loop (ticket 45) sets the baseline of a fixture born from feedback on the
    changed subject, the one the fixture passes on, not on the subject it was recorded against.
    """
    directory = Path(directory)
    fixture = load_fixture(directory)
    if root is not None:
        fixture["subject"]["sha256"] = subject_sha256(fixture, root)
    fixture["baseline"] = {"recorded_at": now_ts(), "subject_sha256": fixture["subject"]["sha256"],
                           "input_hash": fixture["input"]["input_hash"], "structural": _score(outcome.structural, outcome.n),
                           "judged": _score(outcome.judged, outcome.n), "passed": outcome.passed, "unstable": _unstable(outcome)}
    _write_json(directory / "fixture.json", fixture)
    return fixture


def _reduced_trace(path):
    """The stream with `system/init` cut to its session id and model.

    The init lists the recording host's tools, MCP servers, plugins, and working directory, which say
    nothing about the subject and do not belong in a harness checkout; every other line is kept as
    it was, because the tool checks read them.
    """
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            message = json.loads(raw)
        except ValueError:
            message = None
        if isinstance(message, dict) and message.get("type") == "system" and message.get("subtype") == "init":
            raw = json.dumps({key: message.get(key) for key in ("type", "subtype", "session_id", "model")})
        lines.append(raw)
    return "\n".join(lines) + "\n"


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, text)


# --- the verb -------------------------------------------------------------------------------------


def fixture_command(args):
    """`wayline fixture run [<id>...] [--changed] [--suite] [--force] [--no-cache]` and `wayline fixture record ...`."""
    parser = argparse.ArgumentParser(prog="wayline fixture", description="record or run the model-behavior fixtures")
    verbs = parser.add_subparsers(dest="action", required=True)
    runner = verbs.add_parser("run", help="run fixtures: the named ones, the changed ones (the default), or the full suite")
    runner.add_argument("ids", nargs="*", help="fixture ids, <kind>/<slug>")
    runner.add_argument("--changed", action="store_true", help="only the fixtures whose subject changed since they last ran (the default)")
    runner.add_argument("--suite", action="store_true", help="every fixture, at most once per weekly window")
    runner.add_argument("--force", action="store_true", help="run the full suite even if it already ran in this weekly window")
    runner.add_argument("--no-cache", action="store_true", help="launch every subject and judge session again")
    runner.add_argument("--root", default=str(HARNESS_ROOT), help="the tree holding fixtures/ and the subjects (default: the harness)")
    recorder = verbs.add_parser("record", help="record a fixture from a journaled session")
    recorder.add_argument("--session", required=True, help="the session id, as the journal names it")
    recorder.add_argument("--kind", required=True, choices=[kind for kind in FIXTURE_KINDS if kind != "conductor"])
    recorder.add_argument("--slug", required=True)
    recorder.add_argument("--project", help="the project whose journal names the session (default: the active project)")
    recorder.add_argument("--subject", help="the subject file under --root (default for a role or verifier: its agent.md)")
    recorder.add_argument("--also", action="append", default=[], help="a further file whose change is a change to the subject")
    recorder.add_argument("--context", action="append", default=[], help="a further project file the session needs in its project")
    recorder.add_argument("--rubric", help="a rubric.md, which adds the judged layer")
    recorder.add_argument("--show-judge", action="append", default=[], help="a JSONPath the judge is shown (default: every top-level field)")
    recorder.add_argument("--runs", type=int, help="samples for the baseline (default: the policy's sample size)")
    recorder.add_argument("--no-baseline", action="store_true", help="record without running the fixture")
    recorder.add_argument("--change", help="the change record to link the fixture into")
    recorder.add_argument("--reason", help="why the fixture exists (origin.reason)")
    recorder.add_argument("--root", default=str(HARNESS_ROOT), help="the tree to write fixtures/ under (default: the harness)")
    options, code = cli.parse_args(parser, args)
    if options is None:
        return code
    root = Path(options.root).resolve()
    policy = projects.policy_for(root if (root / "harness.json").is_file() else None)
    try:
        if options.action == "run":
            return run(root, ids=options.ids, changed=options.changed, suite=options.suite, force=options.force,
                       use_cache=not options.no_cache, policy=policy).exit_code
        project = projects.find_project(options.project)
        record(project, options.session, options.kind, options.slug, root=root, subject_path=options.subject,
               also=options.also, context=options.context, rubric=options.rubric, show_judge=options.show_judge,
               runs=0 if options.no_baseline else options.runs, change_record=options.change, policy=policy, reason=options.reason)
        return 0
    except (FixtureError, projects.ProjectError, worker.LaunchError, OSError) as failure:
        print("wayline fixture: %s" % failure, file=sys.stderr)
        return 1
