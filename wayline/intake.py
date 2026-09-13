"""Phase P0, intake: what the owner has, normalized, and the goal only when code can measure it.

Implementation Decisions 10 and BRIEF 6.4. `wayline intake` takes whatever the owner hands over
(a paragraph, a reference list, PDFs, data pointers, a plan, a repository) and writes three things:
`research/INTAKE.md` with the sections of `SECTIONS`, the `autonomy`, `radius`, `budgets`, and
`human_only` classes in `harness.json` (the file the conductor rereads), and `research/GOAL.json`
when a quantitative goal was stated and its `eval_command` printed the metric on a sample artifact.

The `wayline-intake` skill is the same phase with a person in the conversation: it settles the
answers with the owner and hands them to this verb as one JSON spec, because the ledger is the only
writer of `research/` (decision 2) and a model that wrote `INTAKE.md` itself would bypass it.

A goal is a human decision (decision 4 puts goal changes on the irreversible list), so every goal
this module writes is journaled as a `decision` with `decided_by: human`, and a goal that cannot be
measured is rejected with the reason rather than written: missing, fails, no number, or invalid.
"""

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from wayline.cli import parse_args
from wayline.gates import TIMEOUT_EXIT_CODE, run_shell
from wayline.jsonschema import ValidationError, check, load_schema, validate
from wayline.ledger import DECISION, Ledger, atomic_write
from wayline.project import AUTONOMY, HARNESS_JSON, ProjectError, find_project, policy_for, read_harness

__all__ = [
    "SECTIONS", "DEFAULT_HUMAN_ONLY", "IntakeError", "GoalCheck", "take_intake", "check_goal", "set_goal",
    "describe_goal", "intake_command",
]

INTAKE_MD = "INTAKE.md"
GOAL_JSON = "GOAL.json"

# The sections of INTAKE.md, in order. The fixture of the wayline-intake skill pins the same list.
SECTIONS = ("Intent", "References", "Data", "Code", "Constraints", "Autonomy", "Radius", "Budgets",
            "Decisions that stay human-only", "Goal")

# BRIEF 6.3.
RADIUS = {
    "strict": "the planner and the decider add only tickets that trace to a spec claim.",
    "moderate": "they may also add follow-ups that directly probe a claim's failure.",
    "exploratory": "they may also add new directions, capped per wave and gated on a novelty check.",
}

# Decision 4: goal and data changes are on the irreversible list, so these two are never removed.
DEFAULT_HUMAN_ONLY = {
    "goal": "a decision that changes the goal: the metric, the target, the splits, or the command that measures it.",
    "data": "a decision that changes the data: what is used, what is held out, or what may leave the machine.",
}

SPEC_FIELDS = ("intent", "plan", "references", "data", "code", "constraints", "materials", "autonomy", "radius",
               "budgets", "human_only", "goal", "sample", "rationale")
LIST_FIELDS = ("references", "data", "code", "constraints", "materials", "human_only")
BUDGET_FIELDS = ("gpu_hours", "wallclock_hours", "usage_windows")
GOAL_OPTIONAL = {"dataset_or_split": None, "held_out_split": None, "baseline": None, "budget": None, "stop_when": "goal_reached"}

ARTIFACT = "{artifact}"
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ""}
TEXT_MAX_BYTES = 1_000_000
PDF_HEAD_BYTES = 4_000_000
PDFTOTEXT_TIMEOUT_S = 30

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)\]]+)", re.IGNORECASE)  # as the scout reads one
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(\S.*)$")
_IDENTIFIER = re.compile(r"\b10\.\d{4,9}/|arxiv|https?://", re.IGNORECASE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_SLUG = re.compile(r"^[a-z][a-z0-9_-]*\Z")
_URI = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_PDF_DOI = re.compile(r"(?:prism:doi>|dc:identifier>\s*(?:doi:)?|/DOI\s*\()\s*(10\.\d{4,9}/[^\s<>()]+)", re.IGNORECASE)
_PDF_ARXIV = re.compile(r"arXiv:\s?(\d{4}\.\d{4,5}(?:v\d+)?)")


class IntakeError(ValueError):
    """An intake nobody can write: a spec field intake does not know, a path that is not there, no intent."""


# --- the goal ---------------------------------------------------------------------------------------


@dataclass
class GoalCheck:
    """What running a goal's `eval_command` on the sample artifact showed.

    `kind` is `accepted`, or why not: `missing`, `fails`, `no_number`, `invalid`.
    """

    kind: str
    reason: Optional[str]
    goal: Optional[dict]
    value: Optional[float] = None
    sample: Optional[str] = None
    stated: Optional[dict] = None

    @property
    def accepted(self):
        return self.kind == "accepted"


def check_goal(goal, project, sample=None, timeout_s=None):
    """Normalize a stated goal and run its `eval_command` on `sample`; returns a `GoalCheck`.

    The command runs from the project root with `{artifact}` replaced by the sample's quoted path,
    which is also exported as `WAYLINE_ARTIFACT`. It measures the goal when it exits 0 and prints
    the metric: a JSON object carrying the metric's key, a `<metric>: <value>` line, or a bare
    number on the last line. Any other number in the output is not taken for the metric.
    """
    project = Path(project)
    stated = goal if isinstance(goal, dict) else None
    if stated is None:
        return GoalCheck("invalid", "invalid: the goal is not a JSON object", None, stated=None)
    command = stated.get("eval_command")
    if not isinstance(command, str) or not command.strip():
        return GoalCheck("missing", "missing: the goal names no eval_command, so nothing can measure it", None, stated=stated)
    normalized, problems = normalize_goal(stated)
    if problems:
        return GoalCheck("invalid", "invalid: the goal is not in the GOAL.json shape: %s" % "; ".join(problems), None, stated=stated)
    shown = "`%s`" % command
    if sample is not None:
        sample = Path(sample).expanduser().resolve()
        if not sample.exists():
            return GoalCheck("missing", "missing: the sample artifact %s does not exist" % sample, None, stated=stated)
    if sample is None:
        return GoalCheck("missing", "missing: no sample artifact was given (--sample), so eval_command %s was not run on one "
                         "and nothing shows it can measure an artifact a ticket produces" % shown, None, stated=stated)
    runnable = command.replace(ARTIFACT, shlex.quote(str(sample)))
    environment = dict(os.environ, WAYLINE_PROJECT=str(project.resolve()), WAYLINE_ARTIFACT=str(sample))
    if timeout_s is None:
        timeout_s = policy_for(project).get("acceptance_timeout_s", 600)
    result = run_shell(runnable, project, timeout_s, env=environment, label="wayline intake")
    tail = _last_lines(result["tail"])
    exit_code = result["exit_code"]
    on = " on the sample artifact %s" % sample
    if exit_code == 127:
        return GoalCheck("missing", "missing: eval_command %s exited 127, which is how the shell reports a command it cannot find: %s" % (shown, tail),
                         None, stated=stated)
    if exit_code == TIMEOUT_EXIT_CODE:
        return GoalCheck("fails", "fails: eval_command %s was killed after %s seconds%s" % (shown, timeout_s, on), None, stated=stated)
    if exit_code != 0:
        return GoalCheck("fails", "fails: eval_command %s exited with exit %d%s: %s" % (shown, exit_code, on, tail or "no output"),
                         None, stated=stated)
    value = metric_value(result["tail"], normalized["metric"])
    if value is None:
        metric = normalized["metric"]
        return GoalCheck(
            "no_number",
            "no number: eval_command %s exited 0 and printed no number for `%s`; print a JSON object with a \"%s\" key, "
            "a line `%s: <value>`, or the number alone on the last line" % (shown, metric, metric, metric),
            None, stated=stated)
    return GoalCheck("accepted", None, normalized, value=value, sample=str(sample) if sample is not None else None, stated=stated)


def normalize_goal(goal):
    """The goal with every key of the shape present, and the problems the schema found; never a guess."""
    value = dict(goal)
    for key, default in GOAL_OPTIONAL.items():
        if value.get(key) is None:
            value[key] = default
    if value["baseline"] is None:
        value["baseline"] = {"value": None, "source": None}
    elif isinstance(value["baseline"], dict):
        value["baseline"] = {"value": value["baseline"].get("value"), "source": value["baseline"].get("source"), **value["baseline"]}
    if value["budget"] is None:
        value["budget"] = {"gpu_hours": None, "wallclock": None, "usage_windows": None}
    elif isinstance(value["budget"], dict):
        value["budget"] = {"gpu_hours": None, "wallclock": None, "usage_windows": None, **value["budget"]}
    errors = validate(value, load_schema("goal"))
    return value, ["%s: %s" % (error.path, error.message) for error in errors]


def metric_value(output, metric):
    """The metric's value in a command's output, or None; see `check_goal` for the three spellings."""
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    for candidate in [str(output or "").strip()] + lines[::-1]:
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict) and _finite(parsed.get(metric)):
            return float(parsed[metric])
    labelled = re.compile(r"^%s\s*[:=]\s*(%s)\s*$" % (re.escape(metric), _NUMBER), re.IGNORECASE)
    for line in lines[::-1]:
        found = labelled.match(line)
        if found and _finite(float(found.group(1))):
            return float(found.group(1))
    if lines and re.fullmatch(_NUMBER, lines[-1]) and _finite(float(lines[-1])):
        return float(lines[-1])
    return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _last_lines(text, count=3):
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    return " | ".join(lines[-count:])


def describe_goal(goal):
    """One line a person reads: the metric, the direction, the target, the split, and the command."""
    if not isinstance(goal, dict):
        return "no goal"
    words = "`%s` %s to %s" % (goal.get("metric"), "down" if goal.get("direction") == "down" else "up", _number(goal.get("target")))
    if goal.get("held_out_split"):
        words += " on the held-out split `%s`" % goal["held_out_split"]
    elif goal.get("dataset_or_split"):
        words += " on `%s`" % goal["dataset_or_split"]
    if goal.get("eval_command"):
        words += ", measured by `%s`" % goal["eval_command"]
    if goal.get("stop_when"):
        words += ", stop when `%s`" % goal["stop_when"]
    return words


def _number(value):
    return ("%g" % value) if _finite(value) else str(value)


def _read_goal(ledger):
    try:
        value = ledger.read_json(GOAL_JSON)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_goal(ledger, goal, rationale):
    """Write GOAL.json and journal the human's decision; returns False when the goal was already this one."""
    previous = _read_goal(ledger)
    if previous == goal:
        return False
    if previous is not None:
        rationale = "%s; replaces the goal %s" % (rationale, describe_goal(previous))
    with ledger.lock():
        ledger.write_json(GOAL_JSON, goal, schema="goal")
        ledger.append_event(DECISION, {"ticket": None, "answer": "goal: %s" % describe_goal(goal), "decided_by": "human",
                                       "rationale": rationale, "confidence": None})
    return True


def set_goal(project, goal, sample=None, rationale=None, timeout_s=None):
    """`wayline intake --goal`: check a goal, and when it is measurable write it and update INTAKE.md.

    Returns `(check, changed)`. A rejected goal writes nothing, so the standing goal stays.
    """
    project = Path(project)
    result = check_goal(goal, project, sample=sample, timeout_s=timeout_s)
    if not result.accepted:
        return result, False
    ledger = Ledger(project)
    with ledger.lock():
        changed = _write_goal(ledger, result.goal, rationale or "set by the owner with wayline intake --goal")
        if changed:
            path = ledger.path(INTAKE_MD)
            text = path.read_text(encoding="utf-8") if path.exists() else "# Intake\n"
            ledger.write_markdown(INTAKE_MD, replace_section(text, "Goal", _goal_section(result, None)))
    return result, changed


# --- the materials --------------------------------------------------------------------------------


@dataclass
class Gathered:
    intent: list
    plans: list
    references: list
    reference_notes: list
    data: list
    code: list
    constraints: list


def gather(spec, project, base):
    """Turn the spec's fields and loose materials into the lines of each section."""
    project = Path(project).resolve()
    gathered = Gathered(intent=[], plans=[], references=[], reference_notes=[], data=[], code=[], constraints=[])
    if spec.get("intent"):
        gathered.intent.append(spec["intent"].strip())
    if spec.get("plan"):
        _take_plan(gathered, _existing(spec["plan"], base, "plan"), project)
    for material in spec.get("materials", []):
        _take_material(gathered, material, project, base)
    for reference in spec.get("references", []):
        path = _as_path(reference, base)
        if path is not None and path.is_file() and path.suffix.lower() == ".pdf":
            _take_pdf(gathered, path, project)
        elif reference.strip():
            gathered.references.append(reference.strip())
    for pointer in spec.get("data", []):
        gathered.data.append(_data_line(pointer, project, base))
    for repository in spec.get("code", []):
        gathered.code.append(_code_line(_existing(repository, base, "repository"), project))
    gathered.constraints.extend(line.strip() for line in spec.get("constraints", []) if line.strip())
    return gathered


def _take_material(gathered, material, project, base):
    """A loose argument: a repository, a PDF or a directory of them, a reference list, a plan, data, or the intent."""
    path = _as_path(material, base)
    if path is None or not path.exists():
        if _IDENTIFIER.match(material.strip()) and " " not in material.strip():
            gathered.references.append(material.strip())
        elif _looks_like_path(material):
            raise IntakeError("%s does not exist; an intake does not read a path that is not there as the intent" % material)
        else:
            gathered.intent.append(material.strip())
        return
    if path.is_dir():
        if (path / ".git").exists():
            gathered.code.append(_code_line(path, project))
            return
        files = [child for child in sorted(path.iterdir()) if child.is_file() and not child.name.startswith(".")]
        if files and all(child.suffix.lower() == ".pdf" for child in files):
            for child in files:
                _take_pdf(gathered, child, project)
            return
        gathered.data.append(_data_line(str(path), project, base))
        return
    if path.suffix.lower() == ".pdf":
        _take_pdf(gathered, path, project)
        return
    if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= TEXT_MAX_BYTES:
        text = path.read_text(encoding="utf-8", errors="replace")
        listed = reference_list(text)
        if listed is not None:
            gathered.references.extend(listed)
            gathered.reference_notes.append("Read from `%s` as a reference list." % _shown(path, project))
        else:
            _take_plan(gathered, path, project)
        return
    gathered.data.append(_data_line(str(path), project, base))


def reference_list(text):
    """The references in a text that is nothing but a reference list, or None when it is prose or a plan.

    Every line that is not blank or a heading has to be a list item or carry an identifier, and at
    least one has to carry a DOI, an arXiv id, or a URL; a numbered plan whose steps name no paper
    is therefore a plan.
    """
    lines = [line for line in text.splitlines() if line.strip() and not _HEADING.match(line)]
    if not lines or not any(_IDENTIFIER.search(line) for line in lines):
        return None
    references = []
    for line in lines:
        item = _LIST_ITEM.match(line)
        if item is None and not _IDENTIFIER.search(line):
            return None
        if item is None and len(line.split()) > 1 and not _IDENTIFIER.match(line.strip()):
            return None
        references.append((item.group(1) if item else line).strip())
    return references


def _take_plan(gathered, path, project):
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    gathered.plans.append((_shown(path, project), text))


def _take_pdf(gathered, path, project):
    """A PDF reference: its DOI or arXiv id when one can be read, its path when not, and a note either way."""
    shown = _shown(path, project)
    try:
        with open(path, "rb") as handle:
            head = handle.read(PDF_HEAD_BYTES)
    except OSError as failure:
        gathered.references.append(shown)
        gathered.reference_notes.append("`%s` could not be read (%s), so it is listed by its path." % (shown, failure.strerror))
        return
    if not head.startswith(b"%PDF-"):
        gathered.references.append(shown)
        gathered.reference_notes.append("`%s` does not start with `%%PDF-`, so it was not read as a PDF and is listed by its path." % shown)
        return
    raw = head.decode("latin-1")
    found = _PDF_DOI.search(raw)
    if found is not None:
        gathered.references.append("%s (`%s`)" % (found.group(1).rstrip(".,;"), shown))
        return
    found = _PDF_ARXIV.search(raw)
    text = None if found else _first_pages(path)
    if found is None and text:
        doi = _DOI.search(text)
        if doi is not None:
            gathered.references.append("%s (`%s`)" % (doi.group(1).rstrip(".,;"), shown))
            gathered.reference_notes.append("The DOI of `%s` was read off its first page; a paper cites DOIs too, so check it." % shown)
            return
        found = _PDF_ARXIV.search(text)
    if found is not None:
        gathered.references.append("arXiv:%s (`%s`)" % (found.group(1), shown))
        return
    gathered.references.append(shown)
    gathered.reference_notes.append("No DOI or arXiv id could be read from `%s`, so it is listed by its path." % shown)


def _first_pages(path):
    """The text of a PDF's first page through poppler's `pdftotext`, or None without it."""
    try:
        done = subprocess.run(["pdftotext", "-l", "1", "-q", str(path), "-"], capture_output=True, text=True,
                              errors="replace", timeout=PDFTOTEXT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _data_line(pointer, project, base):
    path = _as_path(pointer, base)
    if path is not None and path.exists():
        shown = _shown(path, project)
        if path.is_dir():
            count = sum(1 for child in path.rglob("*") if child.is_file())
            return "`%s` (a directory, %d file%s)" % (shown, count, "" if count == 1 else "s")
        return "`%s` (a file, %s)" % (shown, _size(path.stat().st_size))
    return pointer.strip()


def _code_line(path, project):
    shown = _shown(path, project)

    def git(*args):
        done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    if head is None:
        return "`%s` (not a git repository with a commit, so no commit pins it)" % shown
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "a detached HEAD"
    line = "`%s` at `%s` on `%s`" % (shown, head, branch)
    remote = git("remote", "get-url", "origin")
    if remote:
        line += ", remote `%s`" % remote
    dirty = git("status", "--porcelain")
    if dirty:
        count = len(dirty.splitlines())
        line += "; %d uncommitted change%s, which the commit does not hold" % (count, "" if count == 1 else "s")
    return line


def _as_path(text, base):
    text = str(text or "").strip()
    if not text or "\n" in text or _URI.match(text):
        return None
    return (Path(base) / Path(text).expanduser()).resolve() if not Path(text).expanduser().is_absolute() else Path(text).expanduser().resolve()


def _existing(text, base, what):
    path = _as_path(text, base)
    if path is None or not path.exists():
        raise IntakeError("the %s %s does not exist" % (what, text))
    return path


def _looks_like_path(text):
    text = text.strip()
    return bool(text) and not any(character.isspace() for character in text) and (
        "/" in text or re.search(r"\.[A-Za-z0-9]{1,5}\Z", text) is not None)


def _shown(path, project):
    path = Path(path).resolve()
    return str(path.relative_to(project)) if path.is_relative_to(project) else str(path)


def _size(size):
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return ("%d %s" % (size, unit)) if unit == "bytes" else ("%.1f %s" % (size, unit))
        size /= 1000.0


# --- the spec ---------------------------------------------------------------------------------------


def normalize_spec(raw):
    """A spec with every field checked for its type; unknown fields are refused, not ignored."""
    if not isinstance(raw, dict):
        raise IntakeError("an intake spec is a JSON object")
    unknown = sorted(set(raw) - set(SPEC_FIELDS))
    if unknown:
        raise IntakeError("intake does not know the field(s) %s; it takes %s" % (", ".join(unknown), ", ".join(SPEC_FIELDS)))
    spec = {}
    for key, value in raw.items():
        if value is None:
            continue
        if key in LIST_FIELDS:
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise IntakeError("%s is a list of strings" % key)
        elif key in ("intent", "plan", "sample", "rationale", "autonomy", "radius"):
            if not isinstance(value, str):
                raise IntakeError("%s is a string" % key)
        elif key == "budgets":
            if not isinstance(value, dict) or set(value) - set(BUDGET_FIELDS):
                raise IntakeError("budgets is an object with %s" % ", ".join(BUDGET_FIELDS))
        spec[key] = value
    if spec.get("autonomy") is not None and spec["autonomy"] not in AUTONOMY:
        raise IntakeError("autonomy is one of %s, got %r" % (", ".join(AUTONOMY), spec["autonomy"]))
    if spec.get("radius") is not None and spec["radius"] not in RADIUS:
        raise IntakeError("radius is one of %s, got %r" % (", ".join(RADIUS), spec["radius"]))
    return spec


def human_only_classes(entries):
    """`slug` or `slug: what it covers`, as the owner named them; goal and data are always first."""
    classes = dict(DEFAULT_HUMAN_ONLY)
    for entry in entries:
        slug, _, description = entry.partition(":")
        slug = slug.strip().lower().replace(" ", "-")
        if not _SLUG.match(slug):
            raise IntakeError("a human-only class is a lower-case name like `baselines`, got %r" % entry)
        if slug not in DEFAULT_HUMAN_ONLY or description.strip():
            classes[slug] = description.strip() or classes.get(slug) or "named by the owner at intake."
    return classes


# --- the intake -------------------------------------------------------------------------------------


def take_intake(project, spec, base=None, timeout_s=None):
    """Write INTAKE.md, the settings in harness.json, and a measurable goal; returns a report.

    `spec` carries the fields of `SPEC_FIELDS`; relative paths in it resolve against `base` (the
    caller's working directory). The goal is checked before anything is written, so a slow or
    failing `eval_command` never leaves half an intake behind. The report is `{intake, harness,
    goal, counts}` where `goal` is the `GoalCheck` or None when no goal was stated.
    """
    project = Path(project).resolve()
    base = Path(base or os.getcwd())
    spec = normalize_spec(spec)
    gathered = gather(spec, project, base)
    if not gathered.intent and not gathered.plans:
        raise IntakeError("an intake needs the intent: a paragraph (--intent, or text as an argument) or a plan (--plan)")
    harness = read_harness(project)
    # The classes already in harness.json stay: an intake that does not name them never shrinks what waits for the owner.
    classes = human_only_classes(list(harness.get("human_only", [])) + spec.get("human_only", []))
    updated = dict(harness)
    updated["autonomy"] = spec.get("autonomy") or harness["autonomy"]
    updated["radius"] = spec.get("radius") or harness["radius"]
    updated["human_only"] = list(classes)
    budgets = {key: harness.get("budgets", {}).get(key) for key in BUDGET_FIELDS}
    budgets.update({key: value for key, value in spec.get("budgets", {}).items() if value is not None})

    goal = None
    if spec.get("goal") is not None:
        goal = check_goal(spec["goal"], project, sample=_sample(spec.get("sample"), base), timeout_s=timeout_s)
    updated["budgets"] = budgets
    schema = load_schema("harness")
    order = list(schema["properties"])  # the schema's order, so the new keys sit beside autonomy and radius
    updated = {key: updated[key] for key in sorted(updated, key=lambda key: order.index(key) if key in order else len(order))}
    try:
        check(updated, schema, name=HARNESS_JSON)
    except ValidationError as failure:
        raise IntakeError(str(failure)) from None

    ledger = Ledger(project)
    with ledger.lock():
        atomic_write(project / HARNESS_JSON, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
        standing = _read_goal(ledger)
        if goal is not None and goal.accepted:
            _write_goal(ledger, goal.goal, spec.get("rationale") or "set by the owner at intake")
            standing = None
        ledger.write_markdown(INTAKE_MD, render(gathered, updated, classes, goal, standing))
    return {
        "intake": str(ledger.path(INTAKE_MD)),
        "harness": updated,
        "goal": goal,
        "counts": {"references": len(gathered.references), "data": len(gathered.data), "code": len(gathered.code),
                   "constraints": len(gathered.constraints)},
    }


def _sample(text, base):
    return None if not text else _as_path(text, base) or Path(text)


# --- INTAKE.md ------------------------------------------------------------------------------------------


def render(gathered, harness, classes, goal, standing):
    """INTAKE.md: every section of `SECTIONS`, in order, none of them empty."""
    parts = ["# Intake", "",
             "What the owner handed over, normalized by `wayline intake`. `harness.json` holds the same "
             "autonomy, radius, budgets, and human-only classes, and is the copy the conductor reads."]

    intent = list(gathered.intent)
    for shown, text in gathered.plans:
        quoted = "\n".join(("> " + line) if line.strip() else ">" for line in text.splitlines())
        intent.append("The owner's plan, from `%s`:\n\n%s" % (shown, quoted))
    sections = {
        "Intent": "\n\n".join(intent),
        "References": _bullets(gathered.references, "None.") + _prose(gathered.reference_notes),
        "Data": _bullets(gathered.data, "Not stated."),
        "Code": _bullets(gathered.code, "None."),
        "Constraints": _bullets(gathered.constraints, "None stated."),
        "Autonomy": "`%s`: %s" % (harness["autonomy"], AUTONOMY[harness["autonomy"]]),
        "Radius": "`%s`: %s" % (harness["radius"], RADIUS[harness["radius"]]),
        "Budgets": _budgets(harness.get("budgets") or {}),
        "Decisions that stay human-only": "The decider never resolves these; they wait for the owner.\n\n"
                                          + _bullets(["`%s`: %s" % (slug, text) for slug, text in classes.items()], ""),
        "Goal": _goal_section(goal, standing),
    }
    for name in SECTIONS:
        parts += ["", "## " + name, "", sections[name].strip()]
    return "\n".join(parts) + "\n"


def _bullets(lines, empty):
    return "\n".join("- " + line for line in lines) if lines else empty


def _prose(notes):
    return ("\n\n" + "\n".join(notes)) if notes else ""


def _budgets(budgets):
    def stated(value, unit=""):
        return "not stated" if value is None else "%s%s" % (_number(value), unit)

    return "\n".join([
        "- GPU hours: %s" % stated(budgets.get("gpu_hours")),
        "- Wall clock: %s" % stated(budgets.get("wallclock_hours"), " hours"),
        "- Usage windows: %s" % stated(budgets.get("usage_windows")),
    ])


def _goal_section(goal, standing):
    later = "`wayline intake --goal <file> --sample <artifact>`"
    if goal is None:
        if standing is not None:
            return "No goal was stated at this intake; the `GOAL.json` already in the ledger stands: %s." % describe_goal(standing)
        return "No quantitative goal was stated. %s adds one later." % later
    if goal.accepted:
        on = "the sample artifact `%s`" % goal.sample if goal.sample else "no sample artifact"
        return "`GOAL.json` holds the goal: %s. When intake checked it, `eval_command` printed %s with %s." % (
            describe_goal(goal.goal), _number(goal.value), on)
    stated = describe_goal(goal.stated) if isinstance(goal.stated, dict) and goal.stated.get("metric") else "the stated goal"
    return "No goal was written. %s was rejected, %s. %s adds it once a script can measure it on an artifact a ticket can produce." % (
        stated[0].upper() + stated[1:], goal.reason, later)


def replace_section(text, heading, body):
    """`text` with the body under `## <heading>` replaced, or the section appended when there is none."""
    lines = text.rstrip("\n").split("\n")
    start = next((index for index, line in enumerate(lines) if line.strip() == "## " + heading), None)
    if start is None:
        return "\n".join(lines) + "\n\n## %s\n\n%s\n" % (heading, body.strip())
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    replaced = lines[:start + 1] + ["", body.strip()] + ([""] + lines[end:] if end < len(lines) else [])
    return "\n".join(replaced) + "\n"


# --- the verb -------------------------------------------------------------------------------------------


def intake_command(args, stdin=None):
    parser = argparse.ArgumentParser(
        prog="wayline intake",
        description="phase P0: write research/INTAKE.md, the settings in harness.json, and GOAL.json when a script can "
                    "measure the goal; with only --goal, add or replace the goal. Exit 1 when a goal was rejected.")
    parser.add_argument("materials", nargs="*", help="what the owner has: the intent as text, a reference list, PDFs, a plan, data, a repository")
    parser.add_argument("--intent", help="the intent, in the owner's words")
    parser.add_argument("--plan", help="a plan file, quoted whole under the intent")
    parser.add_argument("--reference", action="append", default=[], help="one reference: a DOI, an arXiv id, a URL, a title, or a PDF")
    parser.add_argument("--data", action="append", default=[], help="one data pointer: a path, or words saying where the data is")
    parser.add_argument("--repo", action="append", default=[], help="a repository the work builds on")
    parser.add_argument("--constraint", action="append", default=[], help="one constraint")
    parser.add_argument("--autonomy", choices=sorted(AUTONOMY))
    parser.add_argument("--radius", choices=sorted(RADIUS))
    parser.add_argument("--gpu-hours", type=float)
    parser.add_argument("--wallclock-hours", type=float)
    parser.add_argument("--usage-windows", type=int)
    parser.add_argument("--human-only", action="append", default=[], metavar="CLASS[: WHAT IT COVERS]",
                        help="a decision class the decider never resolves; goal and data always are")
    parser.add_argument("--goal", metavar="FILE", help="the goal as JSON, or - for stdin; alone, it adds or replaces the goal")
    parser.add_argument("--sample", help="the artifact the goal's eval_command is run on")
    parser.add_argument("--rationale", help="why the goal is what it is, for the journal")
    parser.add_argument("--from", dest="spec", metavar="FILE", help="the whole intake as one JSON spec, or - for stdin")
    parser.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    stdin = stdin if stdin is not None else sys.stdin
    if options.spec == "-" and options.goal == "-":
        return _refuse("--from - and --goal - cannot both read stdin")
    try:
        project = find_project(options.project)
        spec = normalize_spec(_load_json(options.spec, stdin, "--from")) if options.spec else {}
        flags = _flag_fields(options)
        if options.goal:
            if "goal" in spec:
                raise IntakeError("the goal is given twice, in the spec and with --goal")
            spec["goal"] = _load_json(options.goal, stdin, "--goal")
        if options.sample:
            spec["sample"] = options.sample
        if options.rationale:
            spec["rationale"] = options.rationale
        goal_only = options.goal and not options.spec and not flags
        for key, value in flags.items():
            if key in LIST_FIELDS:
                spec[key] = list(spec.get(key, [])) + value
            elif key == "budgets":
                spec[key] = dict(spec.get(key, {}), **value)
            else:
                spec[key] = value
    except IntakeError as failure:
        return _refuse(str(failure))
    except (ProjectError, OSError) as failure:
        print("wayline intake: %s" % failure, file=sys.stderr)
        return 1

    if goal_only:
        return _goal_only(project, spec)
    try:
        report = take_intake(project, spec)
    except IntakeError as failure:
        return _refuse(str(failure))
    except (ProjectError, OSError, ValidationError) as failure:
        print("wayline intake: %s" % failure, file=sys.stderr)
        return 1
    counts, harness = report["counts"], report["harness"]
    print("intake  %s" % report["intake"])
    print("  references %d   data %d   code %d   constraints %d" % (counts["references"], counts["data"], counts["code"], counts["constraints"]))
    print("  autonomy %s   radius %s   human-only %s" % (harness["autonomy"], harness["radius"], ", ".join(harness["human_only"])))
    goal = report["goal"]
    if goal is None:
        print("  goal  none stated")
        return 0
    if goal.accepted:
        print("  goal  %s (printed %s)" % (describe_goal(goal.goal), _number(goal.value)))
        return 0
    print("wayline intake: the goal was rejected, %s. INTAKE.md was written without it." % goal.reason, file=sys.stderr)
    return 1


def _goal_only(project, spec):
    try:
        result, changed = set_goal(project, spec["goal"], sample=_sample(spec.get("sample"), Path.cwd()),
                                   rationale=spec.get("rationale"))
    except (ProjectError, OSError, ValidationError) as failure:
        print("wayline intake: %s" % failure, file=sys.stderr)
        return 1
    if not result.accepted:
        print("wayline intake: the goal was rejected, %s. The standing goal, if any, is unchanged." % result.reason, file=sys.stderr)
        return 1
    if changed:
        print("goal  %s (printed %s)" % (describe_goal(result.goal), _number(result.value)))
        print("  journaled as a decision by the human")
    else:
        print("goal  unchanged: %s" % describe_goal(result.goal))
    return 0


def _flag_fields(options):
    fields = {}
    if options.materials:
        fields["materials"] = list(options.materials)
    for key, value in (("intent", options.intent), ("plan", options.plan), ("autonomy", options.autonomy), ("radius", options.radius)):
        if value:
            fields[key] = value
    for key, value in (("references", options.reference), ("data", options.data), ("code", options.repo),
                       ("constraints", options.constraint), ("human_only", options.human_only)):
        if value:
            fields[key] = list(value)
    budgets = {key: value for key, value in (("gpu_hours", options.gpu_hours), ("wallclock_hours", options.wallclock_hours),
                                              ("usage_windows", options.usage_windows)) if value is not None}
    if budgets:
        fields["budgets"] = {key: (int(value) if isinstance(value, float) and value.is_integer() else value) for key, value in budgets.items()}
    return fields


def _load_json(source, stdin, flag):
    try:
        text = stdin.read() if source == "-" else Path(source).expanduser().read_text(encoding="utf-8")
    except OSError as failure:
        raise IntakeError("%s %s cannot be read: %s" % (flag, source, failure.strerror)) from None
    try:
        return json.loads(text)
    except ValueError as failure:
        raise IntakeError("%s %s is not JSON: %s" % (flag, source, failure)) from None


def _refuse(message):
    print("wayline intake: %s" % message, file=sys.stderr)
    return 2
