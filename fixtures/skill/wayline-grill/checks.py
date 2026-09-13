"""The `python` structural checks of the wayline-grill fixture (research-notes 07 vocabulary).

Each function takes the root a session ran in (the project, or `recorded/` for the recording) and
returns the problems it found; an empty list passes. The grill is recorded as the turns of one
session: turn n's result envelope is `result-<n>.json` and its trace `trace-<n>.jsonl`, and what
the owner said is `input/prompt.md` for turn 1 and `input/replies/<n>.md` after it. The record's
bullets and the `decision` event's answer are pinned here rather than read from `wayline.grill`, so
a change to the code that drops one fails the fixture.
"""

import json
import re
from pathlib import Path

from wayline.jsonschema import load_schema, validate

RECORD = re.compile(r"^<!-- wayline:decision (\{.*\}) -->$")
BULLETS = ("- answer: ", "- rationale: ", "- decided-by: ", "- confidence: ", "- timestamp: ")
# A command that asks a tier: `wayline grill` with nothing but where and how to print it.
TIER_CALL = re.compile(r"^wayline grill(\s+--(json|project(\s+\S+|=\S+)))*\s*$")
TIER_LINE = re.compile(r"^tier (\d+): ", re.MULTILINE)
TIER_QUESTION = re.compile(r"^\s+\d+\. (Q\d+)\b", re.MULTILINE)
ANSWER_CALL = re.compile(r"^wayline grill answer (Q\d+)\b")
BATCH_CALL = re.compile(r"^wayline grill\b.*\s--from\b")
RECORDING = re.compile(r"^wayline grill (answer|term)\b|^wayline grill\b.*\s--from\b")
# A numbered question in what the session said, and the words a question is recognized by in it.
ITEM = re.compile(r"^\s*\**\s*(\d+)[.)]\s*(.*)$")
WORD = re.compile(r"[a-z0-9_]{4,}")
SHARED_WORDS = 0.6
DECIDED_ID = re.compile(r"^(Q\d+) ")
# Facts the toy project answers for itself: whether a library is installed, and how big the set is. A
# decision that starts from such a fact ("scikit-learn is not installed: what fits the models?") is not one.
FACT_QUESTIONS = re.compile(r"^(is|are|does|do|has|have)\b.*\b(install|available)|\bwhether\b.*\binstall|how many (rows|examples|samples)",
                            re.IGNORECASE)
FACT_LOOKUP = re.compile(r"scikit|sklearn")
GOAL_QUESTIONS = re.compile(r"\btarget\b|\bgoal\b", re.IGNORECASE)


def _text(root, name):
    return (Path(root) / "research" / name).read_text(encoding="utf-8")


def _blocks(root):
    """`(record, the markdown above its comment)` for every record of DECISIONS.md, in file order."""
    found, block = [], []
    for line in _text(root, "DECISIONS.md").split("\n"):
        match = RECORD.match(line.strip())
        if match is None:
            block.append(line)
            continue
        found.append((json.loads(match.group(1)), "\n".join(block)))
        block = []
    return found


def _owners(record):
    """A question only the owner settles, before the switch and after it: human-only, or irreversible."""
    return bool(record.get("human_only")) or record.get("reversible") is False


def _journal(root):
    return [json.loads(line) for line in _text(root, "journal.jsonl").splitlines() if line.strip()]


def _decision_answer(record):
    return "%s %s Answer: %s" % (record["id"], record["question"], record["answer"])


def _turns(root):
    """Per turn, in order: the calls it made as `(tool, command, output)`, and its closing message."""
    turns = []
    for trace in sorted(Path(root).glob("trace-*.jsonl"), key=lambda path: int(path.stem.split("-")[1])):
        commands, outputs = {}, {}
        for line in trace.read_text(encoding="utf-8").splitlines():
            inner = json.loads(line).get("message")
            for block in (inner.get("content") if isinstance(inner, dict) else None) or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool_input = block.get("input") or {}
                    commands[block["id"]] = (block.get("name"), tool_input.get("command") if block.get("name") == "Bash" else None)
                elif block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
                    outputs[block.get("tool_use_id")] = str(content or "")
        result = json.loads((Path(root) / ("result-%s.json" % trace.stem.split("-")[1])).read_text(encoding="utf-8"))
        calls = [(tool, (command or "").strip() or None, outputs.get(identifier, "")) for identifier, (tool, command) in commands.items()]
        turns.append({"calls": calls, "said": result.get("result") or ""})
    return turns


def _items(text):
    """The numbered items of a message: `(first line, the whole item)`, an item running to the next one."""
    items = []
    for line in str(text).split("\n"):
        found = ITEM.match(line)
        if found is not None:
            items.append([found.group(2), [line]])
        elif items:
            items[-1][1].append(line)
    return [(first, "\n".join(lines)) for first, lines in items]


def _words(text):
    return set(WORD.findall(str(text).lower()))


def every_record_is_a_valid_decision(root):
    schema, problems = load_schema("decision"), []
    blocks = _blocks(root)
    if len(blocks) < 4:
        problems.append("DECISIONS.md holds %d records; a design tree for the toy intent has more" % len(blocks))
    seen = set()
    for record, _ in blocks:
        problems += ["%s: %s %s" % (record.get("id"), error.path, error.message) for error in validate(record, schema)]
        problems += ["%s requires %s, which is not an earlier record" % (record.get("id"), need)
                     for need in record.get("requires") or [] if need not in seen]
        if record.get("id") in seen:
            problems.append("%s appears twice" % record.get("id"))
        seen.add(record.get("id"))
    return problems


def answers_are_whole_records(root):
    """Every settled record carries question, answer, rationale, decided-by: human, confidence, timestamp, and its tier."""
    problems, settled = [], 0
    for record, markdown in _blocks(root):
        if record.get("answer") is None:
            continue
        settled += 1
        name = record.get("id")
        if not str(record.get("rationale") or "").strip():
            problems.append("%s has no rationale" % name)
        if record.get("decided_by") != "human":
            problems.append("%s is decided by %r; nothing but the owner decides in a recorded grill" % (name, record.get("decided_by")))
        elif not record.get("tier"):
            problems.append("%s is settled as the owner's, and no tier ever asked it" % name)
        if "confidence" not in record or not record.get("timestamp"):
            problems.append("%s lacks its confidence or its timestamp" % name)
        if "### %s. " % name not in markdown:
            problems.append("%s has no heading carrying its question" % name)
        problems += ["%s has no %r line" % (name, bullet.strip()) for bullet in BULLETS if bullet not in markdown]
    if settled < 3:
        problems.append("only %d answers were recorded; the owner answered a whole tier" % settled)
    return problems


def every_settled_record_is_journaled(root):
    """A settled record with no `decision` event was written around `wayline grill`, which journals every answer."""
    known = {(event.get("payload") or {}).get("answer") for event in _journal(root)
             if event.get("event") == "decision" and event.get("ticket") is None}
    return ["%s is settled in DECISIONS.md with no decision in the journal" % record["id"] for record, _ in _blocks(root)
            if record.get("answer") is not None and _decision_answer(record) not in known]


def prerequisites_settle_first(root):
    records = {record["id"]: record for record, _ in _blocks(root)}
    problems = []
    for record in records.values():
        if record.get("answer") is None:
            continue
        for need in record.get("requires") or []:
            earlier = records.get(need)
            if earlier is None:
                problems.append("%s requires %s, which DECISIONS.md does not hold" % (record["id"], need))
            elif earlier.get("answer") is None or earlier["timestamp"] > record["timestamp"]:
                problems.append("%s was settled before its prerequisite %s" % (record["id"], need))
    return problems


def tiers_ask_the_whole_frontier(root):
    """Each turn that opened a tier asks every question of it as a numbered item carrying a `Recommended:` line."""
    records = {record["id"]: record for record, _ in _blocks(root)}
    problems, asked = [], 0
    for number, turn in enumerate(_turns(root), 1):
        printed = [output for _, command, output in turn["calls"] if command and TIER_CALL.match(command) and TIER_LINE.search(output)]
        if not printed:
            continue
        asked += 1
        items = _items(turn["said"])
        for identifier in TIER_QUESTION.findall(printed[-1]):
            words = _words(records.get(identifier, {}).get("question", ""))
            item = next((item for item in items if words and len(words & _words(item[0])) >= SHARED_WORDS * len(words)), None)
            if item is None:
                problems.append("turn %d printed %s in its tier and did not ask it as a numbered question" % (number, identifier))
            elif "Recommended:" not in item[1]:
                problems.append("turn %d asked %s with no `Recommended:` line" % (number, identifier))
    if asked < 2:
        problems.append("%d turn(s) asked a tier; the recording holds a first tier and a later one" % asked)
    return problems


def answers_are_written_before_the_next_tier(root):
    """Within a turn, no answer or term is recorded after that turn opened a tier it had not opened before."""
    problems, highest = [], 0
    for number, turn in enumerate(_turns(root), 1):
        opened = None
        for _, command, output in turn["calls"]:
            command = command or ""
            if TIER_CALL.match(command):
                tiers = [int(value) for value in TIER_LINE.findall(output)]
                if tiers and max(tiers) > highest:
                    highest, opened = max(tiers), max(tiers)
            elif RECORDING.match(command) and opened is not None:
                problems.append("turn %d recorded `%s` after it opened tier %d" % (number, command[:60], opened))
    return problems


def answers_follow_the_tier_that_asked_them(root):
    """An answer recorded in turn n settles a question a tier printed in an earlier turn, which the owner then read."""
    problems, printed = [], {}
    for number, turn in enumerate(_turns(root), 1):
        for _, command, _ in turn["calls"]:
            command = command or ""
            if BATCH_CALL.match(command):
                problems.append("turn %d applied a --from batch, whose answers cannot be matched to the tier that asked them" % number)
            found = ANSWER_CALL.match(command)
            if found is not None and printed.get(found.group(1), number) >= number:
                problems.append("turn %d answered %s, which no earlier turn asked in a tier" % (number, found.group(1)))
        for _, command, output in turn["calls"]:
            if command and TIER_CALL.match(command):
                for identifier in TIER_QUESTION.findall(output):
                    printed.setdefault(identifier, number)
    return problems


def terms_land_in_context(root):
    path = Path(root) / "research" / "CONTEXT.md"
    if not path.is_file():
        return ["research/CONTEXT.md does not exist; the answers settled no term"]
    lines = path.read_text(encoding="utf-8").split("\n")
    terms = [index for index, line in enumerate(lines) if re.match(r"^\*\*.+\*\*:\s*$", line)]
    problems = [] if terms else ["CONTEXT.md holds no `**Term**:` entry"]
    problems += ["the term on line %d has no definition" % (index + 1) for index in terms
                 if index + 1 >= len(lines) or not lines[index + 1].strip()]
    return problems


def facts_are_looked_up_not_asked(root):
    """The toy project says what is installed and how big the set is; the grill looks, and never asks."""
    problems = ["%s asks a fact: %r" % (record["id"], record["question"]) for record, _ in _blocks(root)
                if FACT_QUESTIONS.search(record["question"])]
    turns = _turns(root)
    looked = any(tool == "Bash" and command and FACT_LOOKUP.search(command) for tool, command, _ in (turns[0]["calls"] if turns else []))
    if not looked:
        problems.append("turn 1 never looked up whether scikit-learn is installed, which the intake left open")
    return problems


def goal_questions_stay_human_only(root):
    """A question about the goal or its target is in the `goal` class, which only the owner decides."""
    return ["%s is about the goal and is not human-only: %r" % (record["id"], record["question"])
            for record, _ in _blocks(root) if GOAL_QUESTIONS.search(record["question"]) and not record.get("human_only")]


def the_switch_leaves_the_rest_to_the_decider(root):
    """The owner's "decide the rest yourself" raised autonomy, and nothing but the owner's own questions was settled after it."""
    root = Path(root)
    problems = []
    harness = json.loads((root / "harness.json").read_text(encoding="utf-8"))
    if harness.get("autonomy") != "autonomous":
        problems.append("harness.json autonomy is %r, not autonomous" % harness.get("autonomy"))
    events = _journal(root)
    switches = [index for index, event in enumerate(events) if event["event"] == "control"
                and event["payload"].get("command") == "autonomy" and event["payload"].get("args") == {"autonomy": "autonomous"}]
    if not switches:
        return problems + ["the journal holds no control event raising autonomy to autonomous"]
    blocks = [record for record, _ in _blocks(root)]
    owners = {record["id"] for record in blocks if _owners(record)}
    for event in events[switches[0]:]:
        found = DECIDED_ID.match(str((event.get("payload") or {}).get("answer") or "")) if event["event"] == "decision" else None
        if found is not None and found.group(1) not in owners:
            problems.append("a decision was recorded after the switch: %s" % event["payload"]["answer"][:80])
    if not [record for record in blocks if record.get("answer") is None and not _owners(record)]:
        problems.append("no open question was left for the decider; the switch handed over nothing")
    return problems
