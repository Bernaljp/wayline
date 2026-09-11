"""The command: a thin argument parser over the package's functions (Implementation Decisions 1).

Every verb is a function in the package that the dashboard calls in-process; this module only
maps `argv` to that function. A verb whose ticket has not landed yet has no handler and exits 2
with "not yet implemented", so a caller can tell a missing feature from a failure.
"""

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Optional

from wayline import TAG

Handler = Callable[[list], int]


@dataclass
class Verb:
    name: str
    usage: str
    help: str
    group: str
    handler: Optional[Handler] = None


def lazy(module, attribute):
    """A handler that imports `module` and calls its `attribute` only when the verb runs."""

    def handler(args):
        return getattr(importlib.import_module(module), attribute)(args)

    return handler


# The verb table of Implementation Decisions 1, grouped as the spec groups it, plus `job`, the
# verb decisions 4 and 6 give experiment workers to write a job file for the runner.
VERBS = [
    Verb("init", "init <path> [--uninstall-units]", "lay out a project, register it, install the user units once per machine", "project"),
    Verb("intake", "intake [--goal]", "phase P0: take what the owner has and write INTAKE.md (also a skill)", "phases"),
    Verb("absorb", "absorb", "phase P1: build the dossiers for the references", "phases"),
    Verb("position", "position", "phase P2: write the position memo", "phases"),
    Verb("grill", "grill", "phase P2: ask the frontier of open questions in tiers (also a skill)", "phases"),
    Verb("specify", "specify", "phase P3: write SPEC.md with claims, experiments, and seams", "phases"),
    Verb("plan", "plan", "phase P4: cut the ticket graph and assign roles and skills (also a skill)", "phases"),
    Verb("run", "run [--resume] [--detach] [--simulate-limit s] [--simulate-failure id]", "the conductor; --detach launches it as the transient unit wayline-conductor", "conductor"),
    Verb("pause", "pause", "journal a control event the conductor applies at its next wave", "controls"),
    Verb("resume", "resume", "journal a control event the conductor applies at its next wave", "controls"),
    Verb("stop", "stop [--drain]", "journal a control event the conductor applies at its next wave", "controls"),
    Verb("cancel", "cancel <id>", "journal a control event cancelling a ticket", "controls"),
    Verb("rerun", "rerun <id>", "journal a control event rerunning a ticket", "controls"),
    Verb("status", "status", "print the frontier, running tickets and jobs, open decisions, the window, the goal, the last events", "views"),
    Verb("answer", "answer <id> \"<text>\"", "answer a decision ticket from the command line", "views"),
    Verb("switch", "switch <path>", "make another project the active one", "views"),
    Verb("feedback", "feedback \"<text>\"", "file feedback for the evolve loop", "views"),
    Verb("serve", "serve [--bind 0.0.0.0] [--port n]", "the dashboard server", "services"),
    Verb("tick", "tick", "the recurrent job that relaunches work after windows, answers, and jobs", "services"),
    Verb("accept", "accept", "run the ticket's machine acceptance inside a worktree (called by workers)", "worktree"),
    Verb("consult", "consult <slug> \"<question>\"", "ask the consultant one question about one dossier (called by workers)", "worktree"),
    Verb("job", "job add <file>", "write a job file for the runner (called by experiment workers)", "worktree"),
    Verb("evolve", "evolve [\"<text>\"]", "turn feedback into change records, harness tickets, and fixtures", "evolve"),
    Verb("promote", "promote skill|role|policy <name>", "move a local skill, role, or policy into the harness", "evolve"),
    Verb("upgrade", "upgrade [--to <tag>]", "move the project to another harness tag", "evolve"),
    Verb("fixture", "fixture record|run", "record or run the model-behavior fixtures", "evolve"),
    Verb("registry", "registry build", "build the index of skills and roles", "builders"),
    Verb("figures", "figures build-index|refresh", "build or refresh the plot index", "builders"),
    Verb("guidelines", "guidelines build", "build the venue guidelines", "builders"),
    Verb("docs", "docs build", "build the documentation site", "builders"),
    Verb("paper", "paper [--venue <slug>]", "draft the paper under a venue's guidelines", "builders"),
    Verb("report", "report", "render REPORT.md from the ledger", "builders"),
    Verb("tools", "tools install", "create the optional converter venv under ~/.wayline/tools/", "tools"),
]

GROUP_TITLES = {
    "project": "Project",
    "phases": "Phases P0 to P4",
    "conductor": "Conductor",
    "controls": "Controls",
    "views": "Views and answers",
    "services": "Services",
    "worktree": "From inside a worktree",
    "evolve": "Evolve",
    "builders": "Builders",
    "tools": "Tools",
}


def lookup(name):
    for verb in VERBS:
        if verb.name == name:
            return verb
    return None


@contextmanager
def temporary_verb(verb):
    """Register `verb` for the duration of a block (tests)."""
    VERBS.append(verb)
    try:
        yield verb
    finally:
        VERBS.remove(verb)


def overview():
    lines = ["wayline " + TAG, "", "usage: wayline <verb> [arguments]", ""]
    width = max(len(verb.usage) for verb in VERBS)
    for group in GROUP_TITLES:
        members = [verb for verb in VERBS if verb.group == group]
        if not members:
            continue
        lines.append(GROUP_TITLES[group] + ":")
        for verb in members:
            built = "" if verb.handler else "  (not yet implemented)"
            lines.append("  %-*s  %s%s" % (width, verb.usage, verb.help, built))
        lines.append("")
    lines.append("wayline --version prints the harness tag; wayline --help prints this text.")
    return "\n".join(lines)


def main(argv=None):
    """Run one verb and return its exit code; 2 for an unknown or unbuilt verb."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(overview())
        return 0
    if args[0] in ("-V", "--version", "version"):
        print("wayline " + TAG)
        return 0
    verb = lookup(args[0])
    if verb is None:
        print("wayline: unknown verb %r (wayline --help lists the verbs)" % args[0], file=sys.stderr)
        return 2
    if verb.handler is None:
        print("wayline %s: not yet implemented" % verb.name, file=sys.stderr)
        return 2
    return int(verb.handler(args[1:]) or 0)
