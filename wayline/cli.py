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
    hidden: bool = False  # registered and runnable, but not in the overview (the smoke verb)


def lazy(module, attribute):
    """A handler that imports `module` and calls its `attribute` only when the verb runs."""

    def handler(args):
        return getattr(importlib.import_module(module), attribute)(args)

    return handler


# The verb table of Implementation Decisions 1, grouped as the spec groups it, plus `job`, the
# verb decisions 4 and 6 give experiment workers to write a job file for the runner.
VERBS = [
    Verb("init", "init <path> [--email <address>] | init --uninstall-units", "lay out a project, register it, make it the active one, and install the tick and dashboard user units", "project", lazy("wayline.project", "init_command")),
    Verb("intake", "intake [<material>...] [--goal <file>] [--from <spec>]", "phase P0: take what the owner has and write INTAKE.md, harness settings, and a measurable GOAL.json (also a skill)", "phases", lazy("wayline.intake", "intake_command")),
    Verb("absorb", "absorb [--level 0|1|2 [<slug>...]] [--code <slug> <url>@<sha>] [--inventory <slug> [--pdf <path>]]", "phase P1: build the dossiers for the references (level 2 reads one promoted paper in full), and one reference's inventory from its arXiv source or a PDF", "phases", lazy("wayline.dossier", "absorb_command")),
    Verb("position", "position", "phase P2: a fresh critic writes POSITION.md from the dossiers, the intake, and the goal, with the prior work the scout verified", "phases", lazy("wayline.position", "position_command")),
    Verb("grill", "grill [ask|answer|term] [--from <file>]", "phase P2: ask the design tree's frontier in tiers, and record each answer and term (also a skill)", "phases", lazy("wayline.grill", "grill_command")),
    Verb("specify", "specify [confirm | revise \"<change>\"]", "phase P3: draft SPEC.md with claims, experiments, and seams, check and judge it, and ask for its confirmation", "phases",
         lazy("wayline.specify", "specify_command")),
    Verb("plan", "plan [--replan | --split <id>] [confirm | revise \"<change>\"]",
         "phase P4: cut SPEC.md into the ticket graph with the planner, assign roles and skills from the registry, check it, and ask for its confirmation (also a skill)", "phases",
         lazy("wayline.plan", "plan_command")),
    Verb("run", "run [--resume] [--detach] [--simulate-limit s] [--simulate-failure id]", "the conductor: waves until the frontier is empty (--project picks one, wayline run --help lists the rest)", "conductor", lazy("wayline.conductor", "run_command")),
    Verb("pause", "pause", "journal a control event the conductor applies at its next wave", "controls", lazy("wayline.project", "pause_command")),
    Verb("resume", "resume", "journal a control event the conductor applies at its next wave", "controls", lazy("wayline.project", "resume_command")),
    Verb("stop", "stop [--drain]", "journal a control event the conductor applies at its next wave", "controls", lazy("wayline.project", "stop_command")),
    Verb("cancel", "cancel <id>", "journal a control event cancelling a ticket", "controls", lazy("wayline.project", "cancel_command")),
    Verb("rerun", "rerun <id>", "journal a control event rerunning a ticket", "controls", lazy("wayline.project", "rerun_command")),
    Verb("status", "status [--project <path>] [--json]", "print the frontier, running tickets and jobs, open decisions, the window, the goal, the last events", "views", lazy("wayline.project", "status_command")),
    Verb("answer", "answer <id> \"<text>\" [--rationale \"<why>\"]", "answer a decision ticket from the command line or a session", "views", lazy("wayline.project", "answer_command")),
    Verb("switch", "switch <path> | --autonomy <level> | --fallback auto|ask|wait | --stop-at f --cheap-at f", "make another project the active one, or set its autonomy, its fallback consent, or its pacing thresholds", "views", lazy("wayline.project", "switch_command")),
    Verb("feedback", "feedback \"<text>\"", "file feedback for the evolve loop", "views", lazy("wayline.changes", "feedback_command")),
    Verb("serve", "serve [--bind 0.0.0.0] [--port n]", "the dashboard server", "services", lazy("wayline.dashboard", "serve_command")),
    Verb("tick", "tick [--project <path>]", "the recurrent job that relaunches work after windows, answers, and jobs", "services", lazy("wayline.tick", "tick_command")),
    Verb("accept", "accept [--where worktree|rebased|main]", "run the ticket's machine acceptance inside a worktree (called by workers)", "worktree", lazy("wayline.gates", "accept")),
    Verb("consult", "consult <slug> \"<question>\" [--json]", "ask the consultant one question about one dossier (called by workers; at most policy.consultant.max_questions_per_ticket per ticket)", "worktree", lazy("wayline.consult", "consult_command")),
    Verb("job", "job add [<file>]", "write a job file for the runner from a JSON spec on stdin (called by experiment workers)", "worktree", lazy("wayline.resources", "job_command")),
    Verb("evolve", "evolve [\"<text>\"] [--apply <id>] [--retrospective] [--tag <tag>]", "turn feedback into change records, harness tickets, and fixtures; tag the global changes main now holds", "evolve",
         lazy("wayline.changes", "evolve_command")),
    Verb("promote", "promote skill|role|policy <name> [--tag <tag>]", "move a local skill, role, or policy into the harness on promote/<name>; again after the merge, tag it", "evolve",
         lazy("wayline.evolve", "promote_command")),
    Verb("upgrade", "upgrade [--to <tag>]", "move the project to another harness tag and print the changelog between them; --to an older tag rolls back", "evolve",
         lazy("wayline.evolve", "upgrade_command")),
    Verb("fixture", "fixture record|run [--changed] [--suite]", "record a fixture from a journaled session, or run the fixtures (exit 1 on a regression, 2 on a cost stop)", "evolve",
         lazy("wayline.fixtures", "fixture_command")),
    Verb("registry", "registry build", "build the index of skills and roles", "builders", lazy("wayline.registry", "build_command")),
    Verb("figures", "figures build-index|refresh|fold-traps", "build or refresh the plot index, or fold a figure result's traps into it", "builders", lazy("wayline.figures", "figures_command")),
    Verb("figure", "figure make <request.json> | resume <figure_id> [--json]", "the figure role: ranked candidates from the plot index, a pick, the house style, the 19 checks, and one honesty verdict", "builders", lazy("wayline.figure_role", "figure_command")),
    Verb("guidelines", "guidelines build|check", "build the venue guidelines, or run the seven checks on a draft", "builders", lazy("wayline.guidelines", "build_command")),
    Verb("docs", "docs init|env|build [--theme t] [--offline]", "the documentation site: choose the theme once and lay out the skeleton, install Sphinx in the project's environment, build and check it", "builders",
         lazy("wayline.docs", "docs_command")),
    Verb("paper", "paper [--venue <slug>] [--continue] [--verify]", "draft research/paper/ under a venue's guidelines, build it with the linter and the seven checks, and gate it with the kill argument and one independent read; nothing is submitted", "builders",
         lazy("wayline.paper", "paper_command")),
    Verb("report", "report [--offline] [--no-draft] [--verify]", "render REPORT.md from the ledger, lint every claim, and sample the claims for the verifier", "builders", lazy("wayline.provenance", "report_command")),
    Verb("tools", "tools install|show [--marker] [--mineru] [--grobid] [--dry-run]", "create the optional converter venv under ~/.wayline/tools/ (docling; marker, MinerU, GROBID on request)", "tools",
         lazy("wayline.tools", "tools_command")),
    Verb("launch", "launch --smoke [--dir <path>] [--model <alias>] [--effort <effort>]", "one real cheap session through the launcher; prints the envelope and the usage windows", "tools",
         handler=lazy("wayline.worker", "launch_verb"), hidden=True),
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


def parse_args(parser, args):
    """argparse without the process exit, so the dashboard can call a verb in-process.

    Returns `(options, None)` or `(None, exit_code)`; argparse has already printed the complaint.
    """
    try:
        return parser.parse_args(args), None
    except SystemExit as stop:
        return None, (stop.code if isinstance(stop.code, int) else 2)


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
    stray = [verb.name for verb in VERBS if verb.group not in GROUP_TITLES]
    if stray:
        raise ValueError("verb(s) %s belong to a group the overview does not print" % ", ".join(stray))
    for group in GROUP_TITLES:
        members = [verb for verb in VERBS if verb.group == group and not verb.hidden]
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
    return exit_code(verb.name, verb.handler(args[1:]))


def exit_code(name, result):
    """The process exit code for what a handler returned: None or True is 0, False is 1, an int 0..255 is itself."""
    if result is None or result is True:
        return 0
    if result is False:
        return 1
    if isinstance(result, int) and 0 <= result <= 255:
        return result
    raise TypeError("wayline %s returned %r; a verb returns an exit code 0..255, True, False, or None" % (name, result))
