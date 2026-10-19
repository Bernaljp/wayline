"""Objectives: the questions the research answers, and the goals among them (Implementation Decision 17).

`research/objectives.json`, written only by code through the ledger and rendered as `research/OBJECTIVES.md`,
holds the project's objectives with ids O1 onward, never reused: an objective is never deleted, only
parked, answered, dropped, or reframed, so the next id is always one past the highest. An objective with a
measure is a goal, and it has at most one measure, because keep-if-better compares one number; a second
metric makes a second objective.

A measure stands only when its `eval_command` printed the metric on a sample artifact. That check is the
one intake ran on `GOAL.json`, moved here (`run_on_sample`); since ticket 80 intake takes no goal at all.
A measure whose command is not ready records the objective without it, and `wayline objective add` says why.
The grill's first tier records the owner's word on each objective through this module too (`add_objective`
with `status` for one the position memo proposed, `change_objective` for one already recorded).

Every change is journaled as an `objective` event with `by` (`owner`, `decider`, or `code`), and
`OBJECTIVES.md` is rendered again in the same lock. This is the expand step over `GOAL.json`: every reader
of `GOAL.json` keeps reading it, and a project with both goes on behaving as it did on its goal. One thing
changes for a project that holds a `GOAL.json` alone: `wayline switch --autonomy autonomous` refuses until an
objective is open (`project.set_autonomy`), since setup cannot end without one.
"""

import argparse
import json
import math
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from wayline.cli import parse_args
from wayline.gates import TIMEOUT_EXIT_CODE, run_shell
from wayline.jsonschema import ValidationError, load_schema, validate
from wayline.ledger import K_BY, K_ID, K_MEASURE, K_STATUS, K_TEXT, OBJECTIVE, PAYLOAD_ENUMS, Ledger
from wayline.project import ProjectError, find_project, policy_for

__all__ = [
    "OBJECTIVES_JSON", "OBJECTIVES_MD", "STATUSES", "BY", "ARTIFACT", "ObjectiveError", "MeasureCheck", "metric_value",
    "run_on_sample", "normalize_measure", "check_measure", "read_objectives", "open_objectives", "add_objective",
    "add_measure", "change_objective", "render_objectives", "describe_measure", "objective_command", "ticket_goal", "served",
    "OPEN", "is_open", "named", "check_named", "check_goal", "ObjectivesUnreadable",
]

OBJECTIVES_JSON = "objectives.json"
OBJECTIVES_MD = "OBJECTIVES.md"
STATUSES = PAYLOAD_ENUMS[(OBJECTIVE, K_STATUS)]
BY = PAYLOAD_ENUMS[(OBJECTIVE, K_BY)]
ARTIFACT = "{artifact}"
OPEN = "open"  # the status of an objective pursued now: the only one a claim, a ticket, or the pick order counts
MEASURE_OPTIONAL = ("target", "held_out_split", "baseline", "dataset_or_split", "min_seeds")

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_ID = re.compile(r"^O([1-9][0-9]*)\Z")


class ObjectivesUnreadable(ValueError):
    """`research/objectives.json` is there and is not the record code writes: not JSON, or not in the `objectives` shape."""


class ObjectiveError(ValueError):
    """A change the record refuses: an unknown objective, a second measure, a status outside the set."""


# --- the measure and its check on a sample artifact -------------------------------------------------------


@dataclass
class MeasureCheck:
    """What running a measure's `eval_command` on the sample artifact showed.

    `kind` is `accepted`, or why not: `missing`, `fails`, `no_number`, `invalid`.
    """

    kind: str
    reason: Optional[str]
    measure: Optional[dict]
    value: Optional[float] = None
    sample: Optional[str] = None

    @property
    def accepted(self):
        return self.kind == "accepted"


def run_on_sample(command, metric, project, sample, timeout_s=None, label="wayline objective"):
    """Run `command` on the sample artifact and read `metric` from what it printed: `(kind, reason, value)`.

    The command runs from the project root with `{artifact}` replaced by the sample's quoted path, which
    is also exported as `WAYLINE_ARTIFACT`. It measures when it exits 0 and prints the metric: a JSON
    object carrying the metric's key, a `<metric>: <value>` line, or a bare number on the last line. Any
    other number in the output is not taken for the metric. `kind` is `accepted` with the value, or
    `missing`, `fails`, or `no_number` with the reason.
    """
    project = Path(project)
    shown = "`%s`" % command
    if sample is not None:
        sample = Path(sample).expanduser().resolve()
        if not sample.exists():
            return "missing", "missing: the sample artifact %s does not exist" % sample, None
    if sample is None:
        return ("missing", "missing: no sample artifact was given (--sample), so eval_command %s was not run on one "
                "and nothing shows it can measure an artifact a ticket produces" % shown, None)
    runnable = command.replace(ARTIFACT, shlex.quote(str(sample)))
    environment = dict(os.environ, WAYLINE_PROJECT=str(project.resolve()), WAYLINE_ARTIFACT=str(sample))
    if timeout_s is None:
        timeout_s = policy_for(project).get("acceptance_timeout_s", 600)
    result = run_shell(runnable, project, timeout_s, env=environment, label=label)
    tail = _last_lines(result["tail"])
    exit_code = result["exit_code"]
    on = " on the sample artifact %s" % sample
    if exit_code == 127:
        return "missing", "missing: eval_command %s exited 127, which is how the shell reports a command it cannot find: %s" % (shown, tail), None
    if exit_code == TIMEOUT_EXIT_CODE:
        return "fails", "fails: eval_command %s was killed after %s seconds%s" % (shown, timeout_s, on), None
    if exit_code != 0:
        return "fails", "fails: eval_command %s exited with exit %d%s: %s" % (shown, exit_code, on, tail or "no output"), None
    value = metric_value(result["tail"], metric)
    if value is None:
        return ("no_number", "no number: eval_command %s exited 0 and printed no number for `%s`; print a JSON object with a \"%s\" key, "
                "a line `%s: <value>`, or the number alone on the last line" % (shown, metric, metric, metric), None)
    return "accepted", None, value


def metric_value(output, metric):
    """The metric's value in a command's output, or None; see `run_on_sample` for the three spellings."""
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


def normalize_measure(stated):
    """The measure with every key of the shape present (an unstated one null, never a guess), and the problems found."""
    value = dict(stated)
    for key in MEASURE_OPTIONAL:
        value.setdefault(key, None)
    if value["baseline"] is None:
        value["baseline"] = {"value": None, "source": None}
    elif isinstance(value["baseline"], dict):
        value["baseline"] = {"value": value["baseline"].get("value"), "source": value["baseline"].get("source"), **value["baseline"]}
    errors = validate(value, load_schema("objectives")["$defs"]["measure"])
    return value, ["%s: %s" % (error.path, error.message) for error in errors]


def check_measure(measure, project, sample=None, timeout_s=None):
    """Normalize a stated measure and run its `eval_command` on `sample`; returns a `MeasureCheck`."""
    if isinstance(measure, list):
        return MeasureCheck("invalid", "invalid: an objective has at most one measure, and %d were given; a second metric "
                            "makes a second objective" % len(measure), None)
    if not isinstance(measure, dict):
        return MeasureCheck("invalid", "invalid: the measure is not a JSON object", None)
    command = measure.get("eval_command")
    if not isinstance(command, str) or not command.strip():
        return MeasureCheck("missing", "missing: the measure names no eval_command, so nothing can measure it", None)
    normalized, problems = normalize_measure(measure)
    if problems:
        return MeasureCheck("invalid", "invalid: the measure is not in the objectives.json shape: %s" % "; ".join(problems), None)
    kind, reason, value = run_on_sample(command, normalized["metric"], project, sample, timeout_s=timeout_s)
    if kind != "accepted":
        return MeasureCheck(kind, reason, None)
    return MeasureCheck("accepted", None, normalized, value=value, sample=str(Path(sample).expanduser().resolve()))


def describe_measure(measure):
    """One line a person reads: the metric, the direction, the target, the split, and the command."""
    if not isinstance(measure, dict):
        return "none"
    direction = "down" if measure.get("direction") == "down" else "up"
    target = measure.get("target")
    words = "`%s` %s" % (measure.get("metric"), direction)
    words += (" to %s" % _number(target)) if target is not None else ", with no target (keep improving)"
    if measure.get("held_out_split"):
        words += " on the held-out split `%s`" % measure["held_out_split"]
    elif measure.get("dataset_or_split"):
        words += " on `%s`" % measure["dataset_or_split"]
    baseline = measure.get("baseline") or {}
    if baseline.get("value") is not None:
        words += ", baseline %s (%s)" % (_number(baseline["value"]), baseline.get("source"))
    if measure.get("min_seeds") is not None:
        words += ", %d seed%s" % (measure["min_seeds"], "" if measure["min_seeds"] == 1 else "s")
    if measure.get("eval_command"):
        words += ", measured by `%s`" % measure["eval_command"]
    return words


def _number(value):
    return ("%g" % value) if _finite(value) else str(value)


# --- the record ---------------------------------------------------------------------------------------------


def read_objectives(project):
    """The objectives of `research/objectives.json` in id order; empty when the project has none yet.

    Raises `ObjectivesUnreadable` (a `ValueError`) when the file is not JSON or not in the schema's shape, so a
    reader can say so rather than act on a half-read record.
    """
    ledger = Ledger(project)
    if not ledger.path(OBJECTIVES_JSON).is_file():
        return []
    try:
        record = ledger.read_json(OBJECTIVES_JSON)
    except (OSError, ValueError) as failure:
        raise ObjectivesUnreadable("research/%s cannot be read: %s" % (OBJECTIVES_JSON, failure)) from None
    problems = validate(record, load_schema("objectives"))
    if problems:
        raise ObjectivesUnreadable("research/%s cannot be read: %s" % (
            OBJECTIVES_JSON, "; ".join("%s: %s" % (error.path, error.message) for error in problems[:3])))
    return list(record["objectives"])


def is_open(objective):
    """Whether an objective record is pursued now."""
    return (objective or {}).get("status") == OPEN


def open_objectives(project):
    """The objectives pursued now."""
    return [objective for objective in read_objectives(project) if is_open(objective)]


def named(objectives, identifier):
    """The record of the objective `identifier` among `objectives`, or None."""
    for objective in objectives or ():
        if identifier and objective.get("id") == identifier:
            return objective
    return None


def check_named(subject, identifiers, objectives, kind):
    """Why the objectives a claim or a ticket names are refused: one line each for an unknown and a closed one.

    `subject` names the claim or the ticket in the line ("claim C2", "T3 (ticket 3)"), and `kind` is what it is
    ("claim", "ticket"): a claim and a ticket name only open objectives (decision 17).
    """
    failures = []
    for identifier in identifiers or ():
        found = named(objectives, identifier)
        if found is None:
            failures.append("%s names the objective %s, which the project does not hold" % (subject, identifier))
        elif not is_open(found):
            failures.append("%s names the objective %s, which is %s; a %s names only open objectives"
                            % (subject, identifier, found.get("status"), kind))
    return failures


def check_goal(subject, identifier, objectives):
    """Why a ticket's `goal` is refused, or None: it names an open objective with a measure, which gives the metric and direction."""
    found = named(objectives, identifier)
    if found is None:
        return "%s's goal %s is no objective the project holds" % (subject, identifier)
    if not is_open(found):
        return "%s's goal %s is %s; a ticket's goal is an open objective" % (subject, identifier, found.get("status"))
    if not found.get("measure"):
        return ("%s's goal %s has no measure, so it is an objective and not a goal: name it among `objectives` and leave "
                "`goal` null" % (subject, identifier))
    return None


def ticket_goal(ticket, objectives):
    """The measure of the open goal a ticket's `goal` names (`goal: "O2"`), or None: no goal, no measure, or not open.

    The ticket carries the objective's id alone: the metric and the direction it reports are the measure's. A goal
    answered, parked, dropped, or reframed is pursued by nobody, so it gives nothing to measure.
    """
    found = named(objectives, (ticket or {}).get("goal"))
    return found.get("measure") if is_open(found) else None


def served(ticket):
    """The objectives a ticket serves: those it names, and the goal it reports."""
    named = [identifier for identifier in (ticket or {}).get("objectives") or () if identifier]
    goal = (ticket or {}).get("goal")
    return named + ([goal] if goal and goal not in named else [])


def _next_id(objectives):
    numbers = [int(match.group(1)) for match in (_ID.match(str(objective.get("id"))) for objective in objectives) if match]
    return "O%d" % (max(numbers, default=0) + 1)


def _write(ledger, objectives, objective, by):
    """Write the record, journal the change to `objective`, and render OBJECTIVES.md; the caller holds the lock."""
    if by not in BY:
        raise ObjectiveError("an objective is changed by one of %s, got %r" % (", ".join(BY), by))
    ledger.write_json(OBJECTIVES_JSON, {"objectives": objectives}, schema="objectives")
    measure = objective["measure"]
    ledger.append_event(OBJECTIVE, {K_ID: objective["id"], K_TEXT: objective["text"], K_STATUS: objective["status"],
                                    K_MEASURE: measure["metric"] if measure else None, K_BY: by})
    ledger.write_markdown(OBJECTIVES_MD, render_objectives(objectives))


def add_objective(project, text, measure=None, sample=None, by="owner", timeout_s=None, status=OPEN, answer=None):
    """`wayline objective add`: record an open objective, a goal when its measure printed the metric on the sample.

    Returns `(objective, check)`: `check` is None without a measure, else the `MeasureCheck`. A measure whose
    command is not ready (missing, failing, or printing no number) leaves the objective recorded without one,
    and `check.reason` says why; a measure not in the shape (two of them, a bad direction) is refused with
    `ObjectiveError` and nothing is recorded. The command runs before
    the lock is taken, since it may take as long as the acceptance timeout.

    `status` is `open`, or `parked` for an objective the owner takes up only later (the grill's first tier,
    ticket 80), with `answer` saying why; one `objective` event records it either way.
    """
    text = " ".join(str(text or "").split())
    if not text:
        raise ObjectiveError("an objective is a question, and none was given")
    if status not in (OPEN, "parked"):
        raise ObjectiveError("an objective is recorded open or parked, got %r" % (status,))
    check = check_measure(measure, project, sample=sample, timeout_s=timeout_s) if measure is not None else None
    if check is not None and check.kind == "invalid":
        raise ObjectiveError("the measure is refused and nothing was recorded: %s" % check.reason)
    ledger = Ledger(project)
    with ledger.lock():
        objectives = read_objectives(project)
        objective = {"id": _next_id(objectives), "text": text, "measure": check.measure if check and check.accepted else None,
                     "status": status, "answer": None if status == OPEN else answer, "evidence": [], "reframed_as": None}
        objectives.append(objective)
        _write(ledger, objectives, objective, by)
    return objective, check


def _find(objectives, identifier):
    for objective in objectives:
        if objective.get("id") == identifier:
            return objective
    known = ", ".join(objective.get("id") for objective in objectives) or "none yet"
    raise ObjectiveError("no objective %s (the objectives are %s)" % (identifier, known))


def add_measure(project, identifier, measure, sample=None, by="owner", timeout_s=None):
    """Give an objective without a measure the one it lacked, making it a goal; returns `(objective, check)`.

    A second measure on one objective is refused before anything runs: a second metric makes a second
    objective. A measure the check did not accept changes nothing.
    """
    if _find(read_objectives(project), identifier).get("measure") is not None:
        raise ObjectiveError("%s already has a measure, and an objective has at most one; a second metric makes a second "
                             "objective (wayline objective add)" % identifier)
    check = check_measure(measure, project, sample=sample, timeout_s=timeout_s)
    if check.kind == "invalid":
        raise ObjectiveError("the measure is refused: %s" % check.reason)
    ledger = Ledger(project)
    with ledger.lock():
        objectives = read_objectives(project)
        objective = _find(objectives, identifier)
        if not check.accepted:
            return objective, check
        if objective.get("measure") is not None:
            raise ObjectiveError("%s gained a measure while this one was checked; an objective has at most one" % identifier)
        objective["measure"] = check.measure
        _write(ledger, objectives, objective, by)
    return objective, check


def change_objective(project, identifier, status, by, answer=None, evidence=None, reframed_as=None):
    """Move an objective to `status` (with its answer, evidence, and successor), journal it, and render; returns it.

    Nothing is deleted: a dropped objective keeps its id, so no later objective takes it.
    """
    if status not in STATUSES:
        raise ObjectiveError("an objective's status is one of %s, got %r" % (", ".join(STATUSES), status))
    ledger = Ledger(project)
    with ledger.lock():
        objectives = read_objectives(project)
        objective = _find(objectives, identifier)
        if status == "reframed":
            if reframed_as is None:
                raise ObjectiveError("a reframed objective names the objective that replaced it")
            if reframed_as == identifier:
                raise ObjectiveError("%s cannot be reframed as itself" % identifier)
            _find(objectives, reframed_as)
        objective.update(status=status, answer=None if status == OPEN else answer, reframed_as=reframed_as if status == "reframed" else None)
        if evidence is not None:
            objective["evidence"] = list(evidence)
        _write(ledger, objectives, objective, by)
    return objective


def render_objectives(objectives):
    """OBJECTIVES.md: every objective in id order with its status, measure, answer, and evidence."""
    def order(objective):
        match = _ID.match(str(objective.get("id")))
        return int(match.group(1)) if match else 0

    lines = ["# Objectives", "",
             "Rendered by code from `research/objectives.json`; `wayline objective add` records one. An objective with a "
             "measure is a goal.", ""]
    if not objectives:
        lines += ["No objective is recorded yet.", ""]
    for objective in sorted(objectives, key=order):
        lines += ["## %s %s" % (objective["id"], objective["text"]), "",
                  "- Status: %s" % objective["status"],
                  "- Measure: %s" % (describe_measure(objective["measure"]) if objective.get("measure") else "none (an objective, not a goal)"),
                  "- Answer: %s" % (objective.get("answer") or "none yet"),
                  "- Evidence: %s" % (", ".join("`%s`" % locator for locator in objective.get("evidence") or []) or "none")]
        if objective.get("reframed_as"):
            lines.append("- Reframed as: %s" % objective["reframed_as"])
        lines.append("")
    return "\n".join(lines)


# --- the verb -----------------------------------------------------------------------------------------------


def objective_command(args):
    parser = argparse.ArgumentParser(
        prog="wayline objective",
        description="record an objective, a question the research answers; with --measure and --sample, a goal, once its "
                    "eval_command printed the metric on the sample artifact")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="record an open objective")
    add.add_argument("question", help="the question, in the owner's words")
    add.add_argument("--measure", metavar="FILE", help="the measure as JSON: metric, direction, target (null for none), "
                                                       "held_out_split, eval_command, baseline, dataset_or_split, min_seeds")
    add.add_argument("--sample", help="the artifact the measure's eval_command is run on")
    add.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    if options.sample and not options.measure:
        print("wayline objective: --sample is the artifact a measure is checked on; give --measure with it", file=sys.stderr)
        return 2
    try:
        project = find_project(options.project)
        measure = _load_measure(options.measure) if options.measure else None
        objective, check = add_objective(project, options.question, measure=measure, sample=options.sample)
    except ObjectiveError as failure:
        print("wayline objective: %s" % failure, file=sys.stderr)
        return 2
    except (ProjectError, OSError, ValidationError, ObjectivesUnreadable) as failure:
        print("wayline objective: %s" % failure, file=sys.stderr)
        return 1
    print("%s  open  %s" % (objective["id"], objective["text"]))
    if check is None:
        print("  recorded as an objective without a measure")
    elif check.accepted:
        print("  a goal: %s (printed %s on %s)" % (describe_measure(objective["measure"]), _number(check.value), check.sample))
    else:
        print("  recorded as an objective without a measure, because the measure's command is not ready: %s" % check.reason)
    return 0


def _load_measure(source):
    try:
        text = Path(source).expanduser().read_text(encoding="utf-8")
    except OSError as failure:
        raise ObjectiveError("--measure %s cannot be read: %s" % (source, failure.strerror)) from None
    try:
        return json.loads(text)
    except ValueError as failure:
        raise ObjectiveError("--measure %s is not JSON: %s" % (source, failure)) from None
