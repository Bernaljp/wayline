"""Rebuild the decision-branch project: its five tickets, its empty ledger files, and its fake worker script.

    python3 fixtures/projects/decision-branch/make.py

The decision ticket's body is written by `wayline.decisions.decision_body`, so a change to how a
decision ticket reads is a change this fixture takes by being rebuilt; `tests/test_decisions.py`
checks the committed file is what this script writes. Everything here is deterministic, so a
rebuild that changes nothing writes the same bytes back.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from wayline import decisions  # noqa: E402
from wayline.frontmatter import dump_document  # noqa: E402
from wayline.tickets import filename, parse_ticket  # noqa: E402

ORIGIN = "research/INTAKE.md#the-intent"


def code_ticket(identifier, title, touches, machine, demo, blocked_by=(), notes=""):
    fields = {
        "id": identifier, "title": title, "kind": "code", "difficulty": 1, "status": "open",
        "blocked_by": list(blocked_by), "touches": list(touches), "role": "coder", "skills": [],
        "outputs": list(touches), "acceptance": {"machine": list(machine), "quality": []},
        "context_pack": ["research/INTAKE.md"], "origin": ORIGIN, "proposed_by": "planner", "demo": demo,
    }
    body = "\n## Demo\n\n%s\n" % demo.replace("on main ", "on `main` ")
    if notes:
        body += "\n## Notes\n\n%s\n" % notes
    return fields, body


QUESTION = "Which form does the beta report take?"
DECISION_RECORD = {
    "ticket": 2, "question": QUESTION, "options": ["one line", "a table"], "recommended": "one line",
    "evidence": ["research/INTAKE.md asks for a report a person reads at a glance",
                 "tickets 3 and 5 write the report, so either form is one ticket's work"],
    "blocking": "subgraph", "human_only": False, "reversible": True,
    "answer": None, "rationale": None, "confidence": None, "decided_by": None, "timestamp": None,
}


def decision_ticket():
    fields = {
        "id": 2, "title": QUESTION, "kind": "decision", "difficulty": 1, "status": "open", "blocked_by": [],
        "blocking": "subgraph", "human_only": False, "touches": [], "role": decisions.DECIDER_ROLE, "skills": [],
        "acceptance": {}, "context_pack": ["research/INTAKE.md"], "origin": ORIGIN, "proposed_by": "planner",
        "demo": "The owner or the decider answers: %s" % QUESTION,
    }
    return fields, "\n" + decisions.decision_body(DECISION_RECORD, paused=[3], origin=ORIGIN)


TICKETS = [
    code_ticket(1, "Write the alpha note", ["notes/alpha.md"], ["test -f notes/alpha.md", "grep -qx alpha notes/alpha.md"],
                "`notes/alpha.md` on main holds the line `alpha`.",
                notes="The alpha branch, which no decision holds: it runs while the beta branch waits for the owner."),
    decision_ticket(),
    code_ticket(3, "Write the beta report", ["reports/beta.md"], ["test -f reports/beta.md", "grep -qx beta reports/beta.md"],
                "`reports/beta.md` on main holds the line `beta`.", blocked_by=[2],
                notes="Waits on decision ticket 2, so it launches only once that ticket is answered."),
    code_ticket(4, "Extend the alpha note", ["notes/alpha.md"],
                ["grep -qx alpha notes/alpha.md", "grep -qx 'alpha extended' notes/alpha.md"],
                "`notes/alpha.md` on main holds both `alpha` and `alpha extended`.", blocked_by=[1]),
    code_ticket(5, "Extend the beta report", ["reports/beta.md"],
                ["grep -qx beta reports/beta.md", "grep -qx 'beta extended' reports/beta.md"],
                "`reports/beta.md` on main holds both `beta` and `beta extended`.", blocked_by=[3],
                notes="Two edges below the decision: the frontier holds it through ticket 3."),
]

# What the fake worker writes and returns per ticket, keyed by ticket id because a wave's launches overlap.
WORK = {
    1: ("notes/alpha.md", "alpha\n", "write notes/alpha.md", "Wrote notes/alpha.md holding the single line alpha."),
    3: ("reports/beta.md", "beta\n", "write reports/beta.md", "Wrote reports/beta.md holding the single line beta, the form the owner chose."),
    4: ("notes/alpha.md", "alpha\nalpha extended\n", "extend notes/alpha.md", "Added the line alpha extended to notes/alpha.md."),
    5: ("reports/beta.md", "beta\nbeta extended\n", "extend reports/beta.md", "Added the line beta extended to reports/beta.md."),
}


def fake_worker():
    entries = []
    for identifier, (path, text, message, summary) in sorted(WORK.items()):
        fields = next(fields for fields, _ in TICKETS if fields["id"] == identifier)
        entries.append({
            "ticket": str(identifier),
            "delay": 0.25,
            "envelope": {
                "structured_output": {
                    "ticket_id": identifier, "status": "done", "summary": summary, "outputs_written": [path],
                    "commands_run": ["wayline accept"],
                    "checks": {command: "pass" for command in fields["acceptance"]["machine"]},
                    "cost": {"turns": 3, "minutes": 1},
                },
                "num_turns": 3, "duration_ms": 4000, "usage": {"input_tokens": 11, "output_tokens": 120},
            },
            "patch": {"files": {path: text}, "message": "ticket %d: %s" % (identifier, message)},
        })
    return entries


def write(relative, text):
    target = HERE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def main():
    for fields, body in TICKETS:
        text = dump_document(fields, body)
        parse_ticket(text, source=filename(fields))  # the fixture holds only tickets the harness reads
        write("research/tickets/" + filename(fields), text)
    write("research/graph.json", json.dumps({"snapshot": {}, "tickets": []}, indent=2) + "\n")
    write("research/manifest.json", json.dumps({"entries": []}, indent=2) + "\n")
    write("research/journal.jsonl", "")
    write("research/findings.jsonl", "")
    write("fake-worker.json", json.dumps(fake_worker(), indent=2) + "\n")


if __name__ == "__main__":
    main()
