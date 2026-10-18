"""One touch-set rule for every ticket, wherever it was filed (ticket 73; Implementation Decision 1).

The planner's tickets were always refused a `research/` touch; a gate's scope-down and a ticket
admitted from a proposal were not, so either could name a path the touch-set hook now denies. Both
are driven here against a temporary project and read back from the tickets and parked proposals.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_proposals import ProposalsCase, moderate
from wayline import gates, plan, proposals, tickets


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
        (outcome,) = self.admit([moderate(touches=["code/src/"])])
        self.assertEqual(outcome["outcome"], "admitted")

    def test_a_code_proposal_whose_touch_set_leaves_code_is_parked(self):
        """Decision 17 (ticket 85): everything a project publishes lives under `code/`, so a code ticket's touch set does."""
        (self.project / "code").mkdir()
        (outcome,) = self.admit([moderate(touches=["code/phaselock.py", "src/"])])
        self.assertEqual((outcome["outcome"], outcome["reason"]), ("parked", "touches"))
        parked = json.loads(proposals.parked_path(self.project, outcome["id"]).read_text(encoding="utf-8"))
        self.assertIn("the touch set entry `src/` is not under code/", parked["touch_problems"][0])


class PlannerCodeTicketTest(unittest.TestCase):
    """The planner's check refuses a code ticket whose touch set leaves `code/` (decision 17, ticket 85)."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project)
        (self.project / "code").mkdir()

    def test_a_code_ticket_outside_code_is_refused(self):
        self.assertEqual(tickets.touch_problem("src/toy/model.py", self.project, kind="code"),
                         "is not under code/, where everything the code repository publishes lives")
        self.assertIsNone(tickets.touch_problem("code/src/toy/model.py", self.project, kind="code"))
        self.assertIsNone(tickets.touch_problem("code", self.project, kind="code"))
        self.assertIsNone(tickets.touch_problem("./code/tests/", self.project, kind="code"))

    def test_another_kind_may_touch_outside_code(self):
        self.assertIsNone(tickets.touch_problem("experiments/sweep.py", self.project, kind="experiment"))
        self.assertIsNone(tickets.touch_problem("experiments/sweep.py", self.project))

    def test_the_setup_answer_alone_makes_a_project_keep_code(self):
        (self.project / "code").rmdir()
        self.assertFalse(tickets.keeps_code(self.project))
        self.assertIsNone(tickets.touch_problem("toy/features.py", self.project, kind="code"),
                          "a layout older than code/ keeps its own paths")
        (self.project / "harness.json").write_text(json.dumps({"code_repository": {"shape": "package"}}))
        self.assertTrue(tickets.keeps_code(self.project))
        self.assertIsNotNone(tickets.touch_problem("toy/features.py", self.project, kind="code"))

    def test_check_tickets_names_the_entry(self):
        fields = {"id": 3, "title": "Add the order parameter", "kind": "code", "difficulty": 2, "status": "open",
                  "blocked_by": [], "touches": ["code/phaselock.py", "phaselock.py"], "role": "coder", "skills": [],
                  "acceptance": {"machine": ["python -m pytest code/tests"], "quality": []},
                  "context_pack": ["research/INTAKE.md"], "proposed_by": "planner", "demo": "the tests pass"}
        failures = plan.check_tickets([(fields, "")], [fields], self.project, base=False)
        self.assertIn("ticket 3: the touch set entry `phaselock.py` is not under code/, where everything the code "
                      "repository publishes lives", failures)
        self.assertFalse([failure for failure in failures if "code/phaselock.py" in failure])
