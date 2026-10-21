"""The drafted ticket (Implementation Decision 17, talking with the project; decision 1's verb table; ticket 109).

The conversation never does the research: work the owner asks for becomes one ticket the session drafts, and code
places it in the graph. `wayline ticket add` takes that draft, one ticket in the shape the planner returns a ticket in
(the `plan` schema's ticket, its `key` optional), and runs it through the same path a cut takes (`wayline.plan`, cut
`draft`): the plan schema and the ticket schema, the touch-set rules (`tickets.touch_problem`, so a draft naming
`research/` is refused), the objectives it names, a blocker that is `#<id>` of a ticket the project holds, and every
machine criterion run at the base commit, where it must fail. The librarian assigns its role and skills from the
registry, code numbers it from the next free id and writes `research/tickets/NN-slug.md` through the ledger, journals
`ticket_created` with `proposed_by: human` (the owner asked for it) and `assigned`, and regenerates `graph.json`.
Nothing is written when any check fails, and every failure is named at once.

A drafted ticket takes nothing back and asks for no confirmation: the owner's request is the word. A new line of work
that needs a claim is not a drafted ticket; it is an objective, and goes through `wayline specify --amend`.
"""

import argparse
import json
import sys
from pathlib import Path

from wayline import HARNESS_ROOT, plan, registry
from wayline.cli import parse_args
from wayline.ledger import Ledger, LedgerError
from wayline.project import ProjectError, find_project

__all__ = ["DraftError", "KEY", "add_drafted", "ticket_command"]

KEY = "T1"  # the draft's key inside the one-ticket plan it is checked as, when the session gave none


class DraftError(ValueError):
    """A draft code refuses, with every failure it found."""

    def __init__(self, message, failures=()):
        super().__init__(message)
        self.failures = list(failures)


def add_drafted(project, draft, *, harness_root=HARNESS_ROOT, timeout_s=None):
    """Check one drafted ticket as the planner's are, then write it and place it in the graph; returns what was written.

    `{"ticket": id, "line": the one line the conversation reads back}`. Raises `DraftError` with every failure when a
    check refuses it, and `plan.PlanError` when the project changed under it between the check and the write.
    """
    project = Path(project).resolve()
    if not isinstance(draft, dict):
        raise DraftError("a drafted ticket is one JSON object in the shape the planner returns a ticket in")
    item = dict(draft)
    item.setdefault("key", KEY)
    record = {"tickets": [item], "decisions": [], "notes": []}
    ledger = Ledger(project)
    events, _ = ledger.read_events()
    index = registry.build(project, harness_root=harness_root, events=events, pre_check=False)
    cut = plan.Cut("draft")
    # The same checks a cut gets (`plan.check_plan`), at the same base-commit timeout (`check_tickets`' default when None).
    failures, _ = plan.check_plan(record, project, plan.read_all(project), index, cut, timeout_s=timeout_s)
    if failures:
        raise DraftError("the drafted ticket fails the checks a planned one passes; nothing was written", failures)
    outcome = plan.write_plan(project, ledger, record, index, cut)
    [identifier] = outcome["tickets"]
    fields = plan.read_all(project)[identifier][0]
    line = "Ticket %d (%s, difficulty %d, %s): %s" % (identifier, fields["kind"], fields["difficulty"], fields["role"], fields["title"])
    return {"ticket": identifier, "line": line}


def _read_draft(source):
    text = sys.stdin.read() if source in (None, "-") else Path(source).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError as failure:
        raise DraftError("the draft is not JSON: %s" % failure) from None


def ticket_command(args):
    """`wayline ticket add [<draft.json>|-] [--project <path>]`: the conversation's verb for a drafted ticket."""
    parser = argparse.ArgumentParser(
        prog="wayline ticket",
        description="place one ticket a conversation drafted for work the owner asked for: checked as the planner's are, "
                    "assigned a role and skills, written, and placed in the graph (decision 17)")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="check a drafted ticket and place it in the graph")
    add.add_argument("draft", nargs="?", default="-",
                     help="the draft as JSON, one ticket in the planner's shape (title, kind, difficulty, blocked_by as #<id>, "
                          "touches, acceptance, objectives, context_pack, origin, demo); - or nothing reads stdin")
    add.add_argument("--project", help="the project; the active one by default")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        outcome = add_drafted(find_project(options.project), _read_draft(options.draft))
    except DraftError as failure:
        print("wayline ticket: %s" % failure, file=sys.stderr)
        for line in failure.failures:
            print("  - %s" % line, file=sys.stderr)
        return 1
    except (ProjectError, LedgerError, OSError, ValueError) as failure:  # plan.PlanError among them
        print("wayline ticket: %s" % failure, file=sys.stderr)
        return 1
    print(outcome["line"])
    return 0
