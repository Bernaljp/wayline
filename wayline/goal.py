"""Keep-if-better, per goal (Implementation Decisions 5, 14, and 17; tickets 39 and 87).

A goal is an objective with a measure in `research/objectives.json`. A ticket whose `goal` names an open goal
(`goal: "O2"`, ticket 81) is measured by code, never by the worker's own word: the goal's measure gives the metric,
the direction, the held-out split, and the `eval_command`, which runs once per seed artifact, from the project root,
on the held-out split. The change is kept only when the mean of those readings improves on that goal's best kept value,
in the goal's direction, by more than `policy.goal.margin_sd` standard deviations across at least `min_seeds` seeds:
the measure's own `min_seeds` when it carries one, else `policy.goal.min_seeds`. At one seed, a deterministic
computation, any strict gain is kept. `GOAL.json` retired with ticket 87: nothing here reads it.

This module is the Type-A half: which files are the seeds, what the command printed for each, and what the readings
say. The conductor acts on the `Judgment`: it fast-forwards a kept change, leaves a discarded one on its branch,
journals `progress` (with the goal) for every evaluation and `discarded` (with the goal) for every change it did not
keep, and writes a goal reached once its best kept value reaches the target.

**One goal at a time.** Each goal's best kept value is recomputed from its own `progress` events, the ones whose
`goal` is its id, starting at its baseline; a reading of another goal, even on the same metric, is not its. A
ticket reports one goal, so a change kept for one goal is never measured again on another.
**The seeds.** Each path the ticket names in `outputs` is one seed's artifact; a path with a glob
character names every file it matches. An experiment ticket's jobs add their `expected_outputs`.
**The command.** `{artifact}` is replaced by the artifact's quoted absolute path and `{split}` by
the quoted held-out split; both are also exported, as `WAYLINE_ARTIFACT` and
`WAYLINE_HELD_OUT_SPLIT`. The metric is read the way `wayline objective add` read it when it accepted the measure.
**The best.** The goal's best kept `progress` value; before any change was kept for it, its `baseline.value` when
one was stated; with neither, the first change is kept, since there is nothing to beat.
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
from wayline.ledger import PROGRESS
from wayline.objectives import ARTIFACT, is_open, metric_value, named

__all__ = [
    "SPLIT", "ARTIFACT_ENV", "SPLIT_ENV", "Judgment", "goal_for", "applies", "min_seeds", "seed_artifacts",
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


def goal_for(ticket, objectives=()):
    """`(goal, skip)`: the open goal this ticket reports, the objective record with its measure, and why it is not judged.

    `skip` is None when keep-if-better judges the ticket, else the reason, and `goal` is None then. It judges a ticket
    whose `goal` names an open objective with a measure among `objectives`, the records of `objectives.json`. A ticket
    without a goal is integrated as any other; so is one whose goal is closed, since nobody pursues it, and one whose
    goal has no measure, since nothing measures it and nothing takes keep-if-better's place.
    """
    identifier = (ticket or {}).get("goal")
    if not identifier:
        return None, "the ticket names no goal"
    found = named(objectives, identifier)
    if found is None or not found.get("measure"):
        return None, "the ticket's goal %s has no measure, so nothing measures it" % identifier
    if not is_open(found):
        return None, "the ticket's goal %s is %s, and keep-if-better judges only a goal pursued now" % (identifier, found.get("status"))
    return found, None


def applies(ticket, objectives=()):
    """Why keep-if-better does not run on this ticket, or None when it does (`goal_for`'s `skip`)."""
    return goal_for(ticket, objectives)[1]


def min_seeds(measure, policy=None):
    """The seeds keep-if-better needs for a goal: its measure's own `min_seeds`, else `policy.goal.min_seeds`, else 3."""
    own = (measure or {}).get("min_seeds")
    if isinstance(own, int) and not isinstance(own, bool) and own >= 1:
        return own
    return (policy or {}).get("min_seeds", DEFAULT_MIN_SEEDS)


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


def evaluate(measure, artifacts, project, timeout_s):
    """The metric per artifact, in order, under a goal's `measure`; raises `GoalError` when any one of them measured nothing.

    The command runs from `project`, the root on `main`, so a ticket cannot change how its own
    change is measured.
    """
    if not artifacts:
        raise GoalError("no seed artifact exists: the ticket's outputs name none that was written")
    command, metric = measure["eval_command"], measure["metric"]
    split = measure.get("held_out_split")
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
    judge nothing: the `Judgment` carries `short` and is neither kept nor discarded. At `min_seeds` 1, a goal
    measured by a deterministic computation, one reading has a standard deviation of 0, so any strict gain is kept;
    several readings are held to the margin as always.
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


def kept_readings(progress, goal):
    """The values of every kept `progress` payload of the goal `goal` (its id), in order."""
    return [payload["value"] for payload in progress
            if payload.get("goal") == goal and payload.get("kept") and _is_number(payload.get("value"))]


def best_kept(progress, goal, baseline=True):
    """The goal's best kept value among `progress` payloads; its measure's baseline before any was kept, when `baseline`.

    `goal` is the objective record, its id and its measure; only the payloads whose `goal` is that id count.
    """
    measure = goal.get("measure") or {}
    values = kept_readings(progress, goal.get("id"))
    if values:
        return max(values) if measure.get("direction") != "down" else min(values)
    stated = (measure.get("baseline") or {}).get("value")
    return float(stated) if baseline and _is_number(stated) else None


def reached(progress, goal):
    """Whether the goal's best kept value is at or beyond its `target`; a baseline never counts, and no target is never reached."""
    measure = goal.get("measure") or {}
    best, target = best_kept(progress, goal, baseline=False), measure.get("target")
    if best is None or not _is_number(target):
        return False
    return best >= target if measure.get("direction") != "down" else best <= target


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def number(value):
    """A reading as a person reads it: six significant digits, or the value as it is when it is no number."""
    return "%.6g" % value if _is_number(value) else str(value)
