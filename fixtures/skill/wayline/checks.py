"""The `python` structural checks of the setup conversation fixture (decision 12's fixtures; ticket 109).

Each function takes the root a session ran in (the project, or `recorded/` for a recording) and returns the problems
it found; an empty list passes. The conversation is recorded as the turns of one session: turn n's result envelope is
`result-<n>.json` and its trace `trace-<n>.jsonl`, and what the owner said is `input/prompt.md` for turn 1 and
`input/replies/<n>.md` after it. The setup reference heads each of its ten questions `Setup N/10:`, so the order is
read from what the session said at the end of each turn; the order itself is pinned here rather than read from the
skill, so a skill that reorders its questions fails the fixture.
"""

import json
import re
from pathlib import Path

QUESTIONS = 10
LABEL = re.compile(r"\bSetup (\d+)/10\b")
CUT = re.compile(r"^wayline plan\b.*\s--cut-only\b")
# The graph's confirmation, which ends setup: the verb run again without --cut-only, or the owner's word recorded.
CONFIRM = re.compile(r"^wayline (plan(?!.*\s--cut-only\b)(?!.*\b(revise|--replan|--split)\b)|answer \S+ confirm\b)")
STOPPING_RULE, SOFTWARE, LAST = 5, 6, QUESTIONS


def _turns(root):
    """Per turn, in order: the Bash commands it ran, and what it said at its end."""
    turns = []
    for trace in sorted(Path(root).glob("trace-*.jsonl"), key=lambda path: int(path.stem.split("-")[1])):
        commands = []
        for line in trace.read_text(encoding="utf-8").splitlines():
            inner = json.loads(line).get("message")
            for block in (inner.get("content") if isinstance(inner, dict) else None) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                    commands.append(str((block.get("input") or {}).get("command") or "").strip())
        result = json.loads((Path(root) / ("result-%s.json" % trace.stem.split("-")[1])).read_text(encoding="utf-8"))
        turns.append({"commands": commands, "said": result.get("result") or ""})
    return turns


def _first_asked(turns):
    """`{N: the index of the first turn whose closing message asks Setup N/10}`."""
    asked = {}
    for index, turn in enumerate(turns):
        for number in LABEL.findall(turn["said"]):
            asked.setdefault(int(number), index)
    return asked


def asks_the_ten_questions_in_order(root):
    """Every setup question is asked, each under its heading, and none before the one ahead of it."""
    turns, problems = _turns(root), []
    if not turns:
        return ["the recording holds no turn"]
    labels = [int(number) for turn in turns for number in LABEL.findall(turn["said"])]
    for number in range(1, QUESTIONS + 1):
        if number not in labels:
            problems.append("Setup %d/10 was never asked" % number)
    highest = 0
    for number in labels:
        if number < highest:
            problems.append("Setup %d/10 was asked after Setup %d/10, out of order" % (number, highest))
        highest = max(highest, number)
    return problems


def confirms_the_plan_after_the_last_question(root):
    """The graph is cut after the stopping rule is asked, and confirmed only once the last question has been asked."""
    turns, problems = _turns(root), []
    asked = _first_asked(turns)
    for index, turn in enumerate(turns):
        for command in turn["commands"]:
            if CUT.match(command) and index <= asked.get(STOPPING_RULE, len(turns)):
                problems.append("turn %d ran `%s` before the owner answered Setup %d/10: --cut-only comes after the stopping rule and "
                                "the budgets" % (index + 1, command, STOPPING_RULE))
            if CUT.match(command) and index > asked.get(SOFTWARE, len(turns)):
                problems.append("turn %d ran `%s` after Setup %d/10 was asked: the software is the planned work's"
                                % (index + 1, command, SOFTWARE))
            if CONFIRM.match(command) and index <= asked.get(LAST, len(turns)):
                problems.append("turn %d ran `%s`, which may confirm the graph and end setup, before the owner answered Setup %d/10"
                                % (index + 1, command, LAST))
    if not any(CUT.match(command) for turn in turns for command in turn["commands"]):
        problems.append("no turn cut the graph with `wayline plan --cut-only`")
    return problems


def _journal(root):
    path = Path(root) / "research" / "journal.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def nothing_is_asked_after_setup(root):
    """Under `autonomous`, no decision for the owner is opened once the graph's confirmation ended setup."""
    try:
        harness = json.loads((Path(root) / "harness.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["harness.json cannot be read"]
    if harness.get("autonomy") != "autonomous":
        return []
    problems, ended = [], False
    for event in _journal(root):
        payload = event.get("payload") or {}
        if event.get("event") == "phase" and payload.get("to") == "P5":
            ended = True
        elif ended and event.get("event") == "decision_opened" and payload.get("human_only"):
            problems.append("a decision for the owner was opened after setup (ticket %s), which under autonomous asks nothing then"
                            % event.get("ticket"))
    if not ended:
        problems.append("setup never ended: no phase into P5 is journaled")
    return problems


def the_stopping_rule_is_recorded(root):
    """The fifth question's answer reached the ledger, through `wayline switch --stop-when`."""
    if any(event.get("event") == "control" and (event.get("payload") or {}).get("command") == "stop_when" for event in _journal(root)):
        return []
    return ["no `control stop_when` is journaled: the stopping rule lives only in the conversation"]
