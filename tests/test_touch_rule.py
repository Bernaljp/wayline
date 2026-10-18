"""One touch-set rule for every ticket, wherever it was filed (ticket 73; Implementation Decision 1).

The planner's tickets were always refused a `research/` touch; a gate's scope-down and a ticket
admitted from a proposal were not, so either could name a path the touch-set hook now denies. Both
are driven here against a temporary project and read back from the tickets and parked proposals.
"""

import json

from tests.test_proposals import ProposalsCase, moderate
from wayline import gates, proposals, tickets


class GateFiledTicketTest(ProposalsCase):
    """`gates.file_writing_ticket`, which every gate's scope-down goes through."""

    def file(self, touches):
        return gates.file_writing_ticket(
            self.project, self.ledger, title="Scope the claims down", touches=touches, inputs=["results/a.json"],
            quality=["Is every claim scoped?"], origin="research/paper/paper.md", demo="the gate passes", body="## Why\n\nx\n")

    def test_a_scope_down_naming_research_is_refused_with_the_reason(self):
        with self.assertRaises(gates.GateError) as caught:
            self.file(["research/paper/paper.md"])
        self.assertIn("the touch set entry `research/paper/paper.md` is under research/", str(caught.exception))
        self.assertEqual(tickets.read_tickets(self.project), [])

    def test_a_scope_down_naming_a_project_path_is_filed(self):
        identifier = self.file(["paper/notes.md"])
        (ticket,) = [fields for fields in tickets.read_tickets(self.project) if fields["id"] == identifier]
        self.assertEqual(ticket["touches"], ["paper/notes.md"])


class ProposalAdmittedTicketTest(ProposalsCase):
    """`proposals.admit_proposals` parks a proposal whose touch set the rule refuses."""

    def test_a_proposal_naming_research_is_parked_with_the_reason(self):
        (outcome,) = self.admit([moderate(touches=["src/", "research/sections/"])])
        self.assertEqual((outcome["outcome"], outcome["reason"]), ("parked", "touches"))
        parked = json.loads(proposals.parked_path(self.project, outcome["id"]).read_text(encoding="utf-8"))
        self.assertIn("the touch set entry `research/sections/` is under research/", parked["touch_problems"][0])
        self.assertEqual(tickets.read_tickets(self.project), [])

    def test_a_proposal_naming_project_paths_is_admitted(self):
        (outcome,) = self.admit([moderate(touches=["src/"])])
        self.assertEqual(outcome["outcome"], "admitted")
