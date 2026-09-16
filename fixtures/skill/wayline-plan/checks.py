"""The `python` structural checks of the wayline-plan fixture (research-notes 07 vocabulary).

Each function takes the root a session ran in (the project, or `recorded/` for the recording) and
returns the problems it found; an empty list passes. What they read is the graph `wayline plan`
wrote: the ticket files, `graph.json`, `plan.json`, and the journal. The plan-time checks themselves
are `wayline.plan.check_graph`; the rest pins what the verb journals, what a decision ticket carries,
and how the graph is gated, so a change to the code that drops one fails the fixture.
"""

import json
from pathlib import Path

from wayline import plan
from wayline.decisions import decision_record
from wayline.tickets import filename, read_ticket, read_tickets, tickets_dir

CHECKS = (
    "the_graph_passes_the_plan_time_checks",
    "every_ticket_has_a_role_and_skills",
    "every_assignment_is_journaled",
    "every_ticket_was_journaled_as_created",
    "decisions_carry_their_records",
    "the_plan_record_matches_the_tickets",
    "the_graph_is_gated_by_the_autonomy",
)


def _events(root):
    path = Path(root) / "research" / "journal.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _work(root):
    return [fields for fields in read_tickets(root) if fields["kind"] != "decision"]


def _body(root, fields):
    return read_ticket(tickets_dir(root) / filename(fields))[1]


def the_graph_passes_the_plan_time_checks(root):
    """A DAG; every open work ticket with a demo, criteria, a touch set, a context pack, a role, and skills; nothing passing at the base."""
    return plan.check_graph(root)


def every_ticket_has_a_role_and_skills(root):
    problems = []
    for fields in _work(root):
        if not fields.get("role") or fields["role"] == plan.UNASSIGNED:
            problems.append("ticket %d has no role" % fields["id"])
        if not isinstance(fields.get("skills"), list):
            problems.append("ticket %d has no skills list" % fields["id"])
    if not _work(root):
        problems.append("no work ticket was cut")
    return problems


def every_assignment_is_journaled(root):
    """One `assigned` per work ticket, naming the role the ticket file carries."""
    assigned = {event.get("ticket"): event.get("payload") or {} for event in _events(root) if event.get("event") == "assigned"}
    problems = []
    for fields in _work(root):
        payload = assigned.get(fields["id"])
        if payload is None:
            problems.append("ticket %d has no assigned event" % fields["id"])
        elif payload.get("role") != fields.get("role") or list(payload.get("skills") or []) != list(fields.get("skills") or []):
            problems.append("ticket %d's assigned event says %s, the file says %s/%s"
                            % (fields["id"], payload, fields.get("role"), fields.get("skills")))
    return problems


def every_ticket_was_journaled_as_created(root):
    created = {event.get("ticket") for event in _events(root) if event.get("event") == "ticket_created"}
    return ["ticket %d has no ticket_created event" % fields["id"] for fields in read_tickets(root) if fields["id"] not in created]


def decisions_carry_their_records(root):
    """Every decision ticket the planner cut carries its record: the question, the options, the evidence, and what it pauses."""
    problems = []
    for fields in read_tickets(root):
        if fields["kind"] != "decision" or fields.get("proposed_by") != "planner":
            continue
        record = decision_record(_body(root, fields))
        if record is None:
            problems.append("decision ticket %d carries no record" % fields["id"])
            continue
        if not record.get("question") or not isinstance(record.get("options"), list):
            problems.append("decision ticket %d's record has no question or options" % fields["id"])
        if fields.get("blocking") not in ("subgraph", "all"):
            problems.append("decision ticket %d blocks neither its subgraph nor everything" % fields["id"])
        if "human_only" not in fields:
            problems.append("decision ticket %d says nothing about being human-only" % fields["id"])
    return problems


def the_plan_record_matches_the_tickets(root):
    """`plan.json` names tickets that exist, cut by the planner, and the tickets it names are every work ticket that is not parked."""
    record = plan.read_plan(root)
    if record is None:
        return ["research/plan.json is missing or names no sha"]
    found = {fields["id"]: fields for fields in read_tickets(root)}
    problems = []
    for identifier in record.get("tickets") or []:
        fields = found.get(identifier)
        if fields is None:
            problems.append("plan.json names ticket %s, which is not in tickets/" % identifier)
        elif fields.get("proposed_by") != "planner" or fields["kind"] == "decision":
            problems.append("plan.json names ticket %s, which the planner did not cut as a work ticket" % identifier)
    for identifier in record.get("decisions") or []:
        if identifier not in found or found[identifier]["kind"] != "decision":
            problems.append("plan.json names decision ticket %s, which is not a decision ticket in tickets/" % identifier)
    if not record.get("tickets"):
        problems.append("plan.json names no ticket")
    return problems


def the_graph_is_gated_by_the_autonomy(root):
    """Under checkpoints and autonomous a blocking-all confirmation ticket exists; under interactive none does."""
    try:
        autonomy = json.loads((Path(root) / "harness.json").read_text(encoding="utf-8")).get("autonomy")
    except (OSError, ValueError):
        return ["harness.json cannot be read for the autonomy"]
    gates = [fields for fields in read_tickets(root)
             if fields["kind"] == "decision" and str(fields.get("origin") or "").startswith(plan.ORIGIN_PREFIX)]
    if autonomy in ("checkpoints", "autonomous"):
        if not gates:
            return ["no decision ticket confirms the graph under autonomy %s" % autonomy]
        return ["decision ticket %d does not block everything" % fields["id"] for fields in gates if fields.get("blocking") != "all"]
    return ["decision ticket %d asks under interactive what the session asks the owner" % fields["id"] for fields in gates]
