"""The drafted ticket (Implementation Decision 17, talking with the project; decision 1's verb table; ticket 109).

Work the owner asks for in a conversation becomes one ticket the session drafts, in the shape the planner returns a
ticket in, through `wayline ticket add`: code checks it as the planner's are (the ticket schema, the touch-set rules,
a criterion that already passes at the base commit), has the librarian assign its role and skills, numbers it, writes
it through the ledger, journals `ticket_created` by `human`, and places it in `graph.json`. What is asserted is what the
owner and the conductor see: the exit code and the line read back, the ticket file, the graph, and the journal.
"""

import io
import json
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout

from tests.projects import ProjectTestCase, open_objective
from wayline import cli, drafts, project
from wayline.ledger import Ledger
from wayline.tickets import read_graph, read_tickets, write_ticket


def draft(**changes):
    """A drafted code ticket, in the planner's ticket shape, that a project with no `src/` can take."""
    value = {"title": "Add a CSV export of the results table", "kind": "code", "difficulty": 2, "blocked_by": [],
             "touches": ["src/export.py"], "acceptance": {"machine": ["test -f src/export.py"]}, "objectives": [],
             "context_pack": ["research/OBJECTIVES.md"], "origin": "the owner asked for a CSV export in the conversation",
             "demo": "src/export.py writes results.csv"}
    value.update(changes)
    return value


class DraftedTicketTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        project.init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=None)

    def add(self, value):
        """`wayline ticket add -` with `value` on stdin: (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), unittest.mock.patch("sys.stdin", io.StringIO(json.dumps(value))):
            code = cli.main(["ticket", "add", "-", "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def events(self, name):
        return [event for event in Ledger(self.project).read_events()[0] if event["event"] == name]

    def test_a_drafted_ticket_is_checked_assigned_written_and_placed_in_the_graph(self):
        code, out, err = self.add(draft())
        self.assertEqual(code, 0, err)
        [ticket] = read_tickets(self.project)
        self.assertEqual(ticket["id"], 1)
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(ticket["proposed_by"], "human", "the owner asked for it")
        self.assertEqual(ticket["role"], "coder", "the librarian assigns the role")
        self.assertIn("Ticket 1", out, "the read-back carries the new ticket's id")
        self.assertIn(1, [entry["id"] for entry in read_graph(self.project)["tickets"]], "code placed it in the graph")
        [created] = self.events("ticket_created")
        self.assertEqual((created["payload"]["ticket"], created["payload"]["proposed_by"]), (1, "human"))

    def test_a_draft_naming_research_is_refused_and_nothing_is_written(self):
        code, _, err = self.add(draft(touches=["research/OBJECTIVES.md"]))
        self.assertEqual(code, 1)
        self.assertIn("research/", err)
        self.assertEqual(read_tickets(self.project), [])
        self.assertEqual(self.events("ticket_created"), [])

    def test_a_draft_the_ticket_schema_refuses_is_refused(self):
        code, _, err = self.add(draft(difficulty=9))
        self.assertEqual(code, 1)
        self.assertIn("difficulty", err)
        self.assertEqual(read_tickets(self.project), [])

    def test_a_draft_whose_criterion_passes_already_is_refused(self):
        (self.project / "src").mkdir()
        (self.project / "src" / "export.py").write_text("", encoding="utf-8")
        code, _, err = self.add(draft())
        self.assertEqual(code, 1)
        self.assertIn("passes at the base commit", err)

    def test_a_draft_may_wait_on_a_ticket_the_project_holds_and_serve_an_open_objective(self):
        objective = open_objective(self.project)
        ledger = Ledger(self.project)
        write_ticket(ledger, {"id": 1, "title": "Write the loader", "kind": "code", "difficulty": 2, "status": "open", "blocked_by": [],
                              "touches": ["src/load.py"], "role": "coder", "skills": [], "acceptance": {"machine": ["test -f src/load.py"]},
                              "context_pack": [], "origin": "research/SPEC.md#c1", "proposed_by": "planner", "demo": "it loads"},
                     "## Demo\n\nit loads\n")
        code, _, err = self.add(draft(blocked_by=["#1"], objectives=[objective["id"]]))
        self.assertEqual(code, 0, err)
        ticket = read_tickets(self.project)[-1]
        self.assertEqual((ticket["id"], ticket["blocked_by"], ticket["objectives"]), (2, [1], [objective["id"]]))

    def test_a_draft_waiting_on_a_ticket_the_project_does_not_hold_is_refused(self):
        code, _, err = self.add(draft(blocked_by=["#7"]))
        self.assertEqual(code, 1)
        self.assertIn("#7", err)

    def test_a_writing_ticket_the_owner_asks_for_has_an_empty_touch_set(self):
        code, _, err = self.add(draft(kind="writing", touches=[], acceptance={"machine": []}, sections=["discussion"],
                                      title="Draft a limitations paragraph", demo="Discussion holds a limitations passage"))
        self.assertEqual(code, 0, err)
        self.assertEqual(read_tickets(self.project)[0]["sections"], ["discussion"])

    def test_a_draft_of_a_kind_no_shipped_role_covers_is_refused_rather_than_failing_at_launch(self):
        code, _, err = self.add(draft(kind="lit", touches=["notes/related.md"], acceptance={"machine": ["test -f notes/related.md"]},
                                      title="Survey the related work", demo="notes/related.md lists the related work"))
        self.assertEqual(code, 1)
        self.assertIn("no role", err)
        self.assertEqual(read_tickets(self.project), [])

    def test_the_function_returns_what_it_wrote(self):
        outcome = drafts.add_drafted(self.project, draft())
        self.assertEqual(outcome["ticket"], 1)
        self.assertEqual(outcome["line"], "Ticket 1 (code, difficulty 2, coder): Add a CSV export of the results table")
        with self.assertRaises(drafts.DraftError) as caught:
            drafts.add_drafted(self.project, draft(touches=["research/x"]))
        self.assertTrue(caught.exception.failures)


if __name__ == "__main__":
    unittest.main()
