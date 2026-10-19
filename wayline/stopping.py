"""The stopping rule and the budgets (Implementation Decision 17; ticket 87).

**The stopping rule** is `stop_when` in `harness.json`, set at setup: `objectives` (the default, the run ends when
no objective is open), a list of objective ids (the run ends when those are closed), or `frontier` (the run ends
when no work is left). The conductor reads it every wave (`rule_end`), in place of the goal check `GOAL.json` once
drove. A run the rule ended ends `objectives_closed`, or `goal_reached` when every objective it closed was a goal that
reached its target. A project that records no objective at all has nothing for the rule to close, so under
`objectives` it runs until its frontier empties, as under `frontier`.

**A goal reached** is written by code from the measured values (`reached_goals`): an open goal whose best kept
`progress` is at or beyond its target is answered, `by: code`.

**The budgets** are `harness.json.budgets`: `wallclock_hours`, counted from the end of setup (the first `phase` into
the execution phase, P5, that the confirmed plan journals, else the first `run_started`), and `gpu_hours`, each
job's hours times the GPUs it held, a job still running counted to now. Spending either ends the run
`budget_spent`; the decider never extends one; only the owner raises one, with `wayline switch --budget`.

**The switches.** `wayline switch --stop-when <rule>` and `wayline switch --budget <name>=<value>` write `harness.json`
and then journal `control` (`stop_when`, `budget`), so a crash between the two leaves a run that starts from the new
setting. After setup, changing the rule or raising a budget is on the irreversible list (decision 4): the owner's word
alone, which the decider is refused and which the switch, the owner's own verb, says when it applies.
"""

import json
import math
import re
import sys
from pathlib import Path

from wayline import goal as goals
from wayline.jsonschema import check, load_schema
from wayline.ledger import (
    JOB_CANCELLED, JOB_FAILED, JOB_FINISHED, JOB_LAUNCHED, RUN_STARTED, Ledger, atomic_write,
)
from wayline.objectives import OPEN, is_open
from wayline.pacing import epoch
from wayline.jsonschema import ValidationError
from wayline.project import HARNESS_JSON, ProjectError, control, find_project, read_harness

__all__ = [
    "OBJECTIVES", "FRONTIER", "RULES", "BUDGETS", "OBJECTIVES_CLOSED", "GOAL_REACHED", "BUDGET_SPENT", "FRONTIER_EMPTY",
    "EXECUTE_PHASE", "rule_of", "describe_rule", "waited", "covered", "rule_end", "reached_goals", "setup_ended_at", "after_setup",
    "wallclock_hours", "gpu_hours", "spent", "describe_spent", "parse_rule", "set_stop_when", "set_budget", "switch_command", "REPLAN", "ANSWER", "PARK", "DROP", "FRONTIER_OPTIONS",
    "DECIDER_CHOICES", "FRONTIER_ORIGIN", "frontier_origin", "frontier_objective", "frontier_choice", "progressed_since", "last_replan",
    "empty_frontier_asks",
]

OBJECTIVES, FRONTIER = "objectives", "frontier"
RULES = (OBJECTIVES, FRONTIER)
BUDGETS = ("wallclock_hours", "gpu_hours")
# The ends of a run this module names, as `run_ended`'s `reason` carries them.
OBJECTIVES_CLOSED, GOAL_REACHED, BUDGET_SPENT, FRONTIER_EMPTY = "objectives_closed", "goal_reached", "budget_spent", "frontier_empty"
# The phase a confirmed plan moves the project to (`plan.EXECUTE_PHASE`): where setup has ended and the run's work begins.
EXECUTE_PHASE = "P5"
_PHASES = ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")
_JOB_ENDS = (JOB_FINISHED, JOB_FAILED, JOB_CANCELLED)


# --- the rule ------------------------------------------------------------------------------------------------


def rule_of(harness):
    """The project's stopping rule: `objectives` without the key, else `harness.json`'s `stop_when`."""
    rule = (harness or {}).get("stop_when")
    return list(rule) if isinstance(rule, list) else (rule or OBJECTIVES)


def describe_rule(rule):
    """The rule as a person reads it."""
    if rule == FRONTIER:
        return "frontier (the run ends when no work is left)"
    if isinstance(rule, list):
        return "%s (the run ends when %s closed)" % (", ".join(rule), "it is" if len(rule) == 1 else "they are")
    return "objectives (the run ends when no objective is open)"


def waited(rule, records):
    """The open objectives the rule waits on: every open one under `objectives`, the open ones it names under a list."""
    if rule == FRONTIER:
        return []
    if isinstance(rule, list):
        return [record for record in records if record.get("id") in rule and is_open(record)]
    return [record for record in records if is_open(record)]


def covered(rule, records):
    """The objectives whose closing ends a run under the rule."""
    if isinstance(rule, list):
        return [record for record in records if record.get("id") in rule]
    return list(records)


def rule_end(rule, records, progress):
    """The `run_ended` reason the rule ends the run with now, or None while it waits (or never ends on objectives).

    `records` are `objectives.json`'s objectives and `progress` the `progress` payloads the journal holds.
    `goal_reached` when every objective the rule closed is a goal whose best kept value reached its target,
    `objectives_closed` otherwise.
    """
    if rule == FRONTIER:
        return None
    closing = covered(rule, records)
    if not closing or waited(rule, records):
        return None
    if all(record.get("measure") and goals.reached(progress, record) for record in closing):
        return GOAL_REACHED
    return OBJECTIVES_CLOSED


def reached_goals(records, progress):
    """The open goals whose best kept value is at or beyond their target: code writes each one reached."""
    return [record for record in records
            if record.get("status") == OPEN and record.get("measure") and goals.reached(progress, record)]


# --- the budgets ---------------------------------------------------------------------------------------------


def setup_ended_at(events):
    """When setup ended: the first `phase` into the execution phase or later, else the first `run_started`; None before either."""
    for event in events:
        if event.get("event") == "phase" and (event.get("payload") or {}).get("to") in _PHASES[_PHASES.index(EXECUTE_PHASE):]:
            return event.get("ts")
    for event in events:
        if event.get("event") == RUN_STARTED:
            return event.get("ts")
    return None


def after_setup(events):
    """Whether setup has ended, which puts a change of the rule or a raised budget on the irreversible list."""
    return setup_ended_at(events) is not None


def wallclock_hours(events, now):
    """The wall-clock hours since setup ended, at `now` (epoch seconds); 0 before it ended."""
    started = epoch(setup_ended_at(events))
    return 0.0 if started is None else max(0.0, (now - started) / 3600.0)


def gpu_hours(events, now):
    """Each job's hours times the GPUs it held: from its `job_launched` to its end, or to `now` while it runs."""
    total, live = 0.0, {}
    for event in events:
        name, payload = event.get("event"), event.get("payload") or {}
        job = payload.get("job") or event.get("job")
        if not job:
            continue
        if name == JOB_LAUNCHED:
            if job in live:
                total += _held(live.pop(job), epoch(event.get("ts")))
            gpus = payload.get("gpu_uuids") or []
            live[job] = (epoch(event.get("ts")), len(gpus) if isinstance(gpus, list) else 0)
        elif name in _JOB_ENDS and job in live:
            started, count = live.pop(job)
            seconds = payload.get("seconds") if name == JOB_FINISHED else None
            if _number(seconds):
                total += max(0.0, seconds) / 3600.0 * count
            else:
                total += _held((started, count), epoch(event.get("ts")))
    for started, count in live.values():
        total += _held((started, count), now)
    return total


def _held(launch, end):
    started, count = launch
    if started is None or end is None:
        return 0.0
    return max(0.0, end - started) / 3600.0 * count


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def spent(harness, events, now):
    """The budgets spent at `now`, as `(name, limit, used)`: a stated limit the hours have reached; none stated is no limit."""
    budgets = (harness or {}).get("budgets") or {}
    used = {"wallclock_hours": lambda: wallclock_hours(events, now), "gpu_hours": lambda: gpu_hours(events, now)}
    found = []
    for name in BUDGETS:
        limit = budgets.get(name)
        if _number(limit):
            hours = used[name]()
            if hours >= limit:
                found.append((name, float(limit), hours))
    return found


def describe_spent(found):
    """One line naming each budget spent and what was used of it."""
    words = {"wallclock_hours": "wall-clock", "gpu_hours": "GPU"}
    return "; ".join("the %s budget of %g hour(s) is spent (%.2f used)" % (words[name], limit, used) for name, limit, used in found)


# --- the switches --------------------------------------------------------------------------------------------


def parse_rule(text):
    """`objectives`, `frontier`, or a comma-separated list of objective ids, as `--stop-when` takes it."""
    text = str(text or "").strip()
    if text in RULES:
        return text
    return [part.strip() for part in text.split(",") if part.strip()]


def _write_harness(project, harness):
    check(harness, load_schema("harness"), name=HARNESS_JSON)
    atomic_write(Path(project) / HARNESS_JSON, json.dumps(harness, ensure_ascii=False, indent=2) + "\n")


def set_stop_when(project, rule, by="cli"):
    """`wayline switch --stop-when`: write the stopping rule to `harness.json`, then journal `control stop_when`.

    `rule` is `objectives`, `frontier`, or a list of ids of objectives the project holds. Returns
    `{from, to, changed, after_setup}`; nothing is written or journaled when it does not change.
    """
    from wayline.objectives import read_objectives  # the objectives module imports the project module, as this one does
    project = Path(project).resolve()
    if isinstance(rule, str) and rule not in RULES or isinstance(rule, list) and not rule or not isinstance(rule, (str, list)):
        raise ProjectError("the stopping rule is objectives, frontier, or a list of objective ids, got %r" % (rule,))
    ledger = Ledger(project)
    with ledger.lock():
        if isinstance(rule, list):
            held = {record["id"] for record in read_objectives(project)}
            unknown = [identifier for identifier in rule if identifier not in held]
            if unknown:
                raise ProjectError("the stopping rule names %s, which the project does not hold (its objectives are %s)"
                                   % (", ".join(unknown), ", ".join(sorted(held)) or "none yet"))
            rule = list(dict.fromkeys(rule))
        harness = read_harness(project)
        before = rule_of(harness)
        events, _ = ledger.read_events()
        report = {"from": before, "to": rule, "changed": before != rule, "after_setup": after_setup(events)}
        if before == rule:
            return report
        _write_harness(project, dict(harness, stop_when=rule))
        control(project, "stop_when", {"stop_when": rule, "from": before}, by=by)
    return report


def set_budget(project, name, value, by="cli"):
    """`wayline switch --budget <name>=<value>`: write one budget to `harness.json`, then journal `control budget`.

    `name` is `wallclock_hours` or `gpu_hours` and `value` a number of hours, 0 or more, or None for no limit.
    Returns `{name, from, to, changed, raised, after_setup}`; `raised` is a limit lifted or removed, which after setup
    is on the irreversible list.
    """
    if name not in BUDGETS:
        raise ProjectError("a budget is one of %s, got %r" % (", ".join(BUDGETS), name))
    if value is not None and (not _number(value) or value < 0):
        raise ProjectError("budget %s is a number of hours, 0 or more, or none; got %r" % (name, value))
    project = Path(project).resolve()
    ledger = Ledger(project)
    with ledger.lock():
        harness = read_harness(project)
        budgets = dict(harness.get("budgets") or {})
        before = budgets.get(name)
        events, _ = ledger.read_events()
        # None is no limit: a limit lifted, or set higher, raises the budget; a first limit or a lower one does not.
        raised = before is not None and (value is None or value > before)
        report = {"name": name, "from": before, "to": value, "changed": before != value, "raised": raised,
                  "after_setup": after_setup(events)}
        if before == value:
            return report
        budgets[name] = value
        _write_harness(project, dict(harness, budgets=budgets))
        control(project, "budget", {"name": name, "value": value, "from": before}, by=by)
    return report


def _parse_budget(text):
    """`<name>=<hours>` or `<name>=none`, as `--budget` takes it: `(name, value)`."""
    name, _, value = str(text or "").partition("=")
    name, value = name.strip(), value.strip()
    if name not in BUDGETS or not value:
        raise ProjectError("--budget is <name>=<hours> with a name among %s, got %r" % (", ".join(BUDGETS), text))
    if value.lower() == "none":
        return name, None
    try:
        hours = float(value)
    except ValueError:
        raise ProjectError("--budget %s takes a number of hours or none, got %r" % (name, value)) from None
    return name, int(hours) if hours.is_integer() else hours


def switch_command(options):
    """`wayline switch --stop-when` and `--budget`, from `project.switch_command`'s parsed options."""
    try:
        project = find_project(options.project)
        if options.stop_when is not None:
            report = set_stop_when(project, parse_rule(options.stop_when))
        else:
            name, value = _parse_budget(options.budget)
            report = set_budget(project, name, value)
    except ProjectError as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 2
    except (ValidationError, OSError, ValueError) as failure:
        print("wayline switch: %s" % failure, file=sys.stderr)
        return 1
    if options.stop_when is not None:
        if not report["changed"]:
            print("the stopping rule is already %s on %s" % (describe_rule(report["to"]), project))
            return 0
        print("stopping rule from %s to %s on %s" % (describe_rule(report["from"]), describe_rule(report["to"]), project))
        if report["after_setup"]:
            print("  setup has ended, so this change was on the irreversible list: the owner's word alone, and the decider is refused it")
    else:
        def shown(value):
            return "no limit" if value is None else "%g hour(s)" % value
        if not report["changed"]:
            print("budget %s is already %s on %s" % (report["name"], shown(report["to"]), project))
            return 0
        print("budget %s from %s to %s on %s" % (report["name"], shown(report["from"]), shown(report["to"]), project))
        if report["raised"] and report["after_setup"]:
            print("  setup has ended, so raising it was on the irreversible list: the owner's word alone, and the decider never extends one")
    print("  the conductor reads it at its next wave")
    return 0


# --- the empty frontier ------------------------------------------------------------------------------------


# The four options of an empty-frontier ticket, in the order a person reads them and an indexical answer counts.
REPLAN, ANSWER, PARK, DROP = "replan for it", "answer it as it stands", "park it", "drop it"
FRONTIER_OPTIONS = (REPLAN, ANSWER, PARK, DROP)
# What the decider may answer one with under `autonomous`: it never parks or drops an objective the rule names.
DECIDER_CHOICES = (REPLAN, ANSWER)
FRONTIER_ORIGIN = "empty frontier: "
_ORIGIN = re.compile(r"^empty frontier: (O[1-9][0-9]*) #([1-9][0-9]*)\Z")
_CHOICE_WORDS = ((REPLAN, ("replan", "re-plan", "re-cut", "recut")), (ANSWER, ("answer",)), (PARK, ("park",)), (DROP, ("drop",)))


def frontier_origin(identifier, number):
    """The origin of the `number`th empty-frontier ticket about objective `identifier`."""
    return "%s%s #%d" % (FRONTIER_ORIGIN, identifier, number)


def frontier_objective(origin):
    """The objective an empty-frontier ticket's origin names, or None for any other origin."""
    found = _ORIGIN.match(str(origin or ""))
    return found.group(1) if found else None


def frontier_choice(answer):
    """The option an answer picks (`replan for it`, `option 3`, `drop it: nothing more to learn`), or None when it picks none."""
    from wayline.decider import chosen_option  # the decider imports the decisions and the project modules
    text = " ".join(chosen_option(answer, list(FRONTIER_OPTIONS)).split()).lower().strip("`'\". ")
    for option, words in _CHOICE_WORDS:
        if text == option or any(text.startswith(word) for word in words):
            return option
    return None


def _frontier_tickets(fields_list, identifier):
    return sorted((fields for fields in fields_list if frontier_objective(fields.get("origin")) == identifier),
                  key=lambda fields: fields["id"])


def progressed_since(events, fields_list, identifier, since):
    """The tickets serving objective `identifier` that were done after `since` (a journal timestamp, None for ever)."""
    from wayline.objectives import served
    serving = {fields["id"] for fields in fields_list if identifier in served(fields)}
    done = []
    for event in events:
        payload = event.get("payload") or {}
        ticket = payload.get("ticket", event.get("ticket"))
        if event.get("event") in ("ticket_done", "ticket_accepted") and ticket in serving and (since is None or event.get("ts", "") > since):
            if ticket not in done:
                done.append(ticket)
    return done


def _answered(events):
    """`{ticket: (answer, ts)}` of every `decision` naming a ticket, the last one standing."""
    found = {}
    for event in events:
        payload = event.get("payload") or {}
        ticket = payload.get("ticket", event.get("ticket"))
        if event.get("event") == "decision" and isinstance(ticket, int) and not isinstance(ticket, bool):
            found[ticket] = (payload.get("answer"), event.get("ts"))
        elif event.get("event") == "ticket_rerun" and isinstance(ticket, int):
            found.pop(ticket, None)
    return found


def last_replan(events, fields_list, identifier):
    """When an empty-frontier ticket about `identifier` was last answered `replan for it`, or None."""
    answered = _answered(events)
    stamps = [answered[fields["id"]][1] for fields in _frontier_tickets(fields_list, identifier)
              if fields["id"] in answered and frontier_choice(answered[fields["id"]][0]) == REPLAN]
    return max(stamps) if stamps else None


def empty_frontier_asks(project, waiting, rule, events, fields_list, notify=None):
    """Open one empty-frontier decision ticket per objective in `waiting`; returns `(opened, standing, settled)`.

    `opened` are the tickets this call opened, `standing` the ones still open from before (each objective asks once per
    empty frontier), and `settled` the objectives an earlier ticket was answered about since which nothing was created:
    asking again would ask the same frontier twice. Each ticket offers the four options; code recommends a replan only
    when a ticket serving the objective was done since its last replan, and answering it as it stands otherwise. It
    pauses nothing and is not human-only: under `autonomous` the decider answers it (replan or answer only).
    """
    from wayline import decisions  # the decisions module imports the notifier and the grill
    answered = _answered(events)
    opened, standing, settled = [], [], []
    for objective in waiting:
        identifier = objective["id"]
        earlier = _frontier_tickets(fields_list, identifier)
        open_one = [fields for fields in earlier if fields["id"] not in answered and fields["status"] not in ("done", "accepted", "parked")]
        if open_one:
            standing.append(open_one[-1]["id"])
            continue
        closed = [fields for fields in earlier if fields["id"] in answered]
        if closed:
            since = answered[closed[-1]["id"]][1]
            created = [event for event in events if event.get("event") == "ticket_created" and event.get("ts", "") > since
                       and frontier_objective((event.get("payload") or {}).get("origin")) is None]
            if not created:
                settled.append(identifier)
                continue
        replanned = last_replan(events, fields_list, identifier)
        moved = progressed_since(events, fields_list, identifier, replanned)
        recommended = REPLAN if moved else ANSWER
        question = ("The frontier is empty, and %s, \"%s\", is still open, which the stopping rule waits on: replan for it, "
                    "answer it as it stands, park it, or drop it?" % (identifier, objective.get("text")))
        evidence = [
            "the stopping rule: %s" % describe_rule(rule),
            "nothing is launchable, running, or owed",
            ("ticket(s) %s serving %s were done since its last replan, so a replan is recommended"
             % (", ".join(str(ticket) for ticket in moved), identifier)) if moved else
            ("no ticket serving %s was done since its last replan, so a replan is not recommended" % identifier),
            "replan for it: the planner cuts new tickets for it within the spec, allowed at every radius",
            "answer it as it stands: a fresh verifier answers it from what the run found",
            "park it or drop it: the owner's alone; the decider only replans or answers",
        ]
        report = decisions.open_decision(
            project, question, options=FRONTIER_OPTIONS, recommended=recommended, evidence=evidence, blocking=None,
            human_only=False, proposed_by="conductor", origin=frontier_origin(identifier, len(earlier) + 1),
            title="The frontier is empty with %s open" % identifier, notify=notify)
        (opened if report["opened"] else standing).append(report["ticket"])
    return opened, standing, settled
