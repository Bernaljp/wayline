"""Talking with the project: the owner-facing skill's routing table, read by code (Implementation Decision 17; ticket 109).

The owner talks with a project normally, in any Claude Code session in it (Remote Control included) and in the
dashboard's chat, and never types a verb. One skill, `wayline` (`skills/wayline/`), routes everything: its body is the
routing table, and its reference files hold the procedures (`setup.md`, `evolve.md`). Each row of the table names what
the owner says or hands over, the rule the session follows (`record` without asking, `ask` one line, `confirm` first,
or `read` from what code renders), and the `wayline` verbs it runs.

The table is also the conversation's allowlist: the verbs it names are the only ones a session may run, which the
dashboard's chat reads to grant its tools (ticket 114) and the suite holds to decision 1's verb table.
`routed_commands` gives each as the words after `wayline` up to its first placeholder (`objective add`, `switch
--stop-when`, `review all stand`).
"""

import re
from pathlib import Path

from wayline import HARNESS_ROOT

__all__ = ["SKILL", "SKILL_DIR", "RULES", "routing_table", "routed_commands", "command_words"]

SKILL = "wayline"
SKILL_DIR = Path("skills") / SKILL
ROUTING_HEADING = "## Routing"
RULES = ("record", "ask", "confirm", "read")

_COMMAND = re.compile(r"`wayline ([^`]+)`")


def _cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def command_words(command):
    """The words of `wayline <command>` up to its first placeholder or quoted value: `objective add "<q>"` is `objective add`."""
    words = []
    for word in command.split():
        if word.startswith(("<", '"', "'", "[")):
            break
        words.append(word)
    return " ".join(words)


def routing_table(harness_root=HARNESS_ROOT):
    """The rows of the skill's routing table: `[{owner, rule, commands}]`, in the table's order.

    `commands` are the routed forms (`command_words`) of every `wayline ...` the row's last cell names. Raises
    `ValueError` when the skill has no routing table, since a session with none would route nothing.
    """
    lines = (Path(harness_root) / SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(ROUTING_HEADING)
    except ValueError:
        raise ValueError("%s/SKILL.md has no %r section" % (SKILL_DIR, ROUTING_HEADING)) from None
    rows, header = [], None
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            if header is not None and rows:
                break
            continue
        cells = _cells(line)
        if header is None:
            header = cells
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        owner, rule, verbs = cells[0], cells[-2].strip("*_ ").lower(), cells[-1]
        rows.append({"owner": owner, "rule": rule, "commands": [command_words(found) for found in _COMMAND.findall(verbs)]})
    if not rows:
        raise ValueError("%s/SKILL.md's %s section holds no table" % (SKILL_DIR, ROUTING_HEADING))
    return rows


def routed_commands(harness_root=HARNESS_ROOT):
    """Every routed command, once each, in the table's order: the verbs the conversation may run."""
    return list(dict.fromkeys(command for row in routing_table(harness_root) for command in row["commands"]))
