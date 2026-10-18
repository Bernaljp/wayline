"""Keep-if-better under a quantitative goal (Implementation Decisions 5 and 14; ticket 39).

A ticket whose `goal` names a goal (`goal: "O2"`, ticket 81) is measured by code, never by the
worker's own word: the goal's `eval_command` runs once per seed artifact, from the project root, on the held-out split, and the
change is kept only when the mean of those readings improves on the best kept value, in the goal's
`direction`, by more than `policy.goal.margin_sd` standard deviations across at least
`policy.goal.min_seeds` seeds.

This module is the Type-A half: which files are the seeds, what the command printed for each, and
what the readings say. The conductor acts on the `Judgment`: it fast-forwards a kept change,
leaves a discarded one on its branch, journals `progress` for every evaluation and `discarded`
for every change it did not keep, and ends the run once the best kept value reaches the target.

**The seeds.** Each path the ticket names in `outputs` is one seed's artifact; a path with a glob
character names every file it matches. An experiment ticket's jobs add their `expected_outputs`.
**The command.** `{artifact}` is replaced by the artifact's quoted absolute path and `{split}` by
the quoted held-out split; both are also exported, as `WAYLINE_ARTIFACT` and
`WAYLINE_HELD_OUT_SPLIT`. The metric is read the way intake read it when it accepted the goal.
**The best.** The best kept `progress` value for the goal's metric; before any change was kept,
the goal's `baseline.value` when one was stated; with neither, the first change is kept, since
there is nothing to beat.
"""

import glob
import math
import os
import shlex
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from wayline.gates import TIMEOUT_EXIT_CODE, run_shell
from wayline.intake import GOAL_JSON
from wayline.ledger import PROGRESS
from wayline.objectives import ARTIFACT, metric_value, ticket_goal

__all__ = [
    "SPLIT", "ARTIFACT_ENV", "SPLIT_ENV", "Judgment", "read_goal", "applies", "seed_artifacts",
    "evaluate", "judge", "progress_payloads", "kept_readings", "best_kept", "reached", "run_id", "number", "GoalError",
    "JUDGMENT", "INTEGRATION", "DEFAULT_MIN_SEEDS", "DEFAULT_MARGIN_SD",
]

SPLIT = "{split}"
ARTIFACT_ENV = "WAYLINE_ARTIFACT"
SPLIT_ENV = "WAYLINE_HELD_OUT_SPLIT"
DEFAULT_MIN_SEEDS = 3
DEFAULT_MARGIN_SD = 1
# Beside an attempt's session: what keep-if-better read of it, and the range a running goal ticket's fast-forward
# brought to `main`, which a discard reverts. A restarted conductor reads both instead of measuring or guessing again.
JUDGMENT = "goal.json"
INTEGRATION = "integration.json"


class GoalError(ValueError):
    """An evaluation that measured nothing: no seed artifact, a command that failed, or no number printed."""


@dataclass(frozen=True)
class Judgment:
    """What the readings of one attempt say: kept or not, and the numbers the journal carries.

    `short` is set when fewer seeds were read than the policy asks for: the change is neither
    kept nor discarded, and the ticket fails with a request for more seeds.
    """

    metric: str
    values: tuple
    mean: float
    sd: float
    best: Optional[float]
    kept: bool
    short: Optional[str] = None

    @property
    def seeds(self):
        return len(self.values)

    def words(self):
        """One line a person reads: the mean, the spread, the seeds, and what it was compared to."""
        against = "nothing kept before it" if self.best is None else "the best kept %s" % number(self.best)
        return "%s = %s ± %s (sd) over %d seed(s), against %s" % (
            self.metric, number(self.mean), number(self.sd), self.seeds, against)


def run_id(ticket, attempt):
    return "t%d-a%d" % (ticket, attempt)


def read_goal(ledger):
    """`research/GOAL.json` when it names a metric, a direction, and a command; None otherwise."""
    try:
        goal = ledger.read_json(GOAL_JSON)
    except (OSError, ValueError):
        return None
    if not isinstance(goal, dict) or not goal.get("metric") or goal.get("direction") not in ("up", "down"):
        return None
    if not isinstance(goal.get("eval_command"), str) or not goal["eval_command"].strip():
        return None
    return goal


def applies(ticket, goal, objectives=()):
    """Why keep-if-better does not run on this ticket, or None when it does.

    It runs on a ticket whose `goal` names an objective whose measure reports the goal's own metric
    (ticket 81: the metric is read from the measure in `objectives`, the records of `objectives.json`);
    a ticket without one is integrated as any other, and so is one whose goal reports another metric,
    which is said. Until ticket 87 the command, the split, and the direction are still `GOAL.json`'s.
    """
    named = ticket.get("goal")
    if not named:
        return "the ticket names no goal"
    measure = ticket_goal(ticket, objectives)
    if not measure:
        return "the ticket's goal %s has no measure, so nothing measures it" % named
    if goal is None:
        return "the ticket's goal %s reports %s, and research/GOAL.json states no measurable goal" % (named, measure["metric"])
    if measure["metric"] != goal["metric"]:
        return "the ticket's goal %s reports %s, and the goal's metric is %s" % (named, measure["metric"], goal["metric"])
    return None


def seed_artifacts(outputs, root):
    """The seed artifacts under `root`: each output path that exists, globs expanded, in order, each once."""
    root = Path(root)
    found, seen = [], set()
    for output in outputs or []:
        text = str(output).strip()
        if not text or Path(text).is_absolute() or ".." in Path(text).parts:
            continue
        if glob.has_magic(text):
            matches = sorted(glob.glob(str(root / text), recursive=True))
        else:
            matches = [str(root / text)] if (root / text).exists() else []
        for match in matches:
            real = os.path.realpath(match)
            if real not in seen:
                seen.add(real)
                found.append(Path(match))
    return found


def evaluate(goal, artifacts, project, timeout_s):
    """The metric per artifact, in order; raises `GoalError` when any one of them measured nothing.

    The command runs from `project`, the root on `main`, so a ticket cannot change how its own
    change is measured.
    """
    if not artifacts:
        raise GoalError("no seed artifact exists: the ticket's outputs name none that was written")
    command, metric = goal["eval_command"], goal["metric"]
    split = goal.get("held_out_split")
    values = []
    for artifact in artifacts:
        artifact = Path(artifact).resolve()
        runnable = command.replace(ARTIFACT, shlex.quote(str(artifact))).replace(SPLIT, shlex.quote(split or ""))
        environment = dict(os.environ, WAYLINE_PROJECT=str(Path(project).resolve()),
                           **{ARTIFACT_ENV: str(artifact), SPLIT_ENV: split or ""})
        result = run_shell(runnable, project, timeout_s, env=environment, label="wayline goal")
        tail = " | ".join(line.rstrip() for line in (result["tail"] or "").splitlines()[-3:] if line.strip())
        if result["exit_code"] == TIMEOUT_EXIT_CODE:
            raise GoalError("eval_command `%s` was killed after %s seconds on %s" % (command, timeout_s, artifact))
        if result["exit_code"] != 0:
            raise GoalError("eval_command `%s` exited %s on %s: %s" % (command, result["exit_code"], artifact, tail or "no output"))
        value = metric_value(result["tail"], metric)
        if value is None:
            raise GoalError("eval_command `%s` printed no number for `%s` on %s: %s" % (command, metric, artifact, tail or "no output"))
        values.append(value)
    return tuple(values)


def judge(metric, values, best, direction, min_seeds=DEFAULT_MIN_SEEDS, margin_sd=DEFAULT_MARGIN_SD):
    """Keep only a mean better than `best` in `direction` by more than `margin_sd` standard deviations.

    The standard deviation is the sample one across the seeds. Fewer than `min_seeds` readings
    judge nothing: the `Judgment` carries `short` and is neither kept nor discarded.
    """
    values = tuple(float(value) for value in values)
    mean = statistics.fmean(values) if values else math.nan
    sd = statistics.stdev(values) if len(values) >= 2 else 0.0
    if len(values) < min_seeds:
        short = "%d seed(s) were measured and keep-if-better needs at least %d: run the experiment on %d more seed(s), " \
                "each writing its own artifact among the ticket's outputs" % (len(values), min_seeds, min_seeds - len(values))
        return Judgment(metric, values, mean, sd, best, False, short)
    if best is None:
        return Judgment(metric, values, mean, sd, best, True)
    gain = mean - best if direction == "up" else best - mean
    return Judgment(metric, values, mean, sd, best, gain > margin_sd * sd)


def progress_payloads(events):
    """The payload of every `progress` event, in journal order."""
    return [event.get("payload") or {} for event in events if event.get("event") == PROGRESS]


def kept_readings(progress, metric):
    """The values of every kept `progress` payload for `metric`, in order."""
    return [payload["value"] for payload in progress
            if payload.get("metric") == metric and payload.get("kept") and _is_number(payload.get("value"))]


def best_kept(progress, goal, baseline=True):
    """The best kept value for the goal's metric among `progress` payloads; the stated baseline before any was kept, when `baseline`."""
    values = kept_readings(progress, goal["metric"])
    if values:
        return max(values) if goal["direction"] == "up" else min(values)
    stated = (goal.get("baseline") or {}).get("value")
    return float(stated) if baseline and _is_number(stated) else None


def reached(progress, goal):
    """Whether the best kept value is at or beyond `target` in the goal's direction; a baseline never counts."""
    best, target = best_kept(progress, goal, baseline=False), goal.get("target")
    if best is None or not _is_number(target):
        return False
    return best >= target if goal["direction"] == "up" else best <= target


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def number(value):
    """A reading as a person reads it: six significant digits, or the value as it is when it is no number."""
    return "%.6g" % value if _is_number(value) else str(value)
