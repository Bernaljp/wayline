"""A `dossier` ticket has no worker session: the conductor runs it as a promotion through absorb (decision 17; ticket 98).

The seams are the conductor over a temporary project with the fake launcher, whose calls say no worker
session started, the L2 absorb behind the conductor's `absorb_dossier` (the real one is ticket 24's, tested
in its own suite), and the journal, replayed into the view as a restarted conductor would read it.
"""

import io

from tests import machine
from tests.scout_net import EMAIL, NOW, crossref_work, doi_answers, net_fetcher
from tests.test_conductor import ConductorCase, drive
from tests.test_proposals import ProposalsCase
from wayline import proposals, tickets, worker
from wayline.conductor import Conductor
from wayline.dossier import look_up_one, read_dossier
from wayline.replay import replay


class KindRoleTest(ProposalsCase):
    def test_kind_role_routes_no_dossier_and_lit_to_the_surveyor(self):
        self.assertNotIn("dossier", proposals.KIND_ROLE)
        self.assertEqual(proposals.KIND_ROLE["lit"], "surveyor", "the surveyor ships with ticket 99")

    def test_an_admitted_dossier_proposal_takes_the_role_whose_kinds_name_it(self):
        outcome = self.admit([{"title": "Read the method paper in full", "kind": "dossier", "why": "its exact loss matters",
                               "radius": "moderate"}])[0]
        self.assertEqual(outcome["outcome"], "admitted")
        fields, _ = tickets.read_ticket(next(tickets.tickets_dir(self.project).glob("%02d-*.md" % outcome["ticket"])))
        self.assertEqual(fields["role"], "reader")

    def test_an_admitted_lit_proposal_runs_on_the_surveyor_never_the_coder(self):
        outcome = self.admit([{"title": "Survey the flows literature", "kind": "lit", "why": "the Introduction is empty",
                               "radius": "moderate"}])[0]
        fields, _ = tickets.read_ticket(next(tickets.tickets_dir(self.project).glob("%02d-*.md" % outcome["ticket"])))
        self.assertEqual(fields["role"], "surveyor")


class DossierTicketCase(ConductorCase):
    def setUp(self):
        super().setUp()
        fetcher, _ = net_fetcher(doi_answers(crossref_work()))
        self.slug = look_up_one(self.project, "10.5555/wayline.found", fetcher=fetcher, email=EMAIL, clock=lambda: NOW)["slug"]
        self.ledger.write_json("refs/%s/inventory.json" % self.slug, {"slug": self.slug, "items": []})
        for path in tickets.tickets_dir(self.project).glob("*.md"):
            path.unlink()
        self.absorbed = []

    def write_dossier_ticket(self, identifier=1, blocked_by=()):
        fields = {"id": identifier, "title": "Read %s in full" % self.slug, "kind": "dossier", "difficulty": 2, "status": "open",
                  "blocked_by": list(blocked_by), "touches": [], "role": "reader", "skills": [], "acceptance": {},
                  "context_pack": ["research/refs/%s/dossier.json" % self.slug], "proposed_by": "planner"}
        tickets.write_ticket(self.ledger, fields, "## Demo\n\nThe paper is read in full.\n")

    def absorb(self, project, slug, **_):
        self.absorbed.append(slug)
        self.ledger.append_event("absorbed", {"slug": slug, "level": 2, "session_id": "absorb-session", "chunks": 3, "entries": 9,
                                              "coverage_pass": self.coverage})
        return {"slug": slug, "pass": self.coverage, "coverage": {"pass": self.coverage, "missing": [] if self.coverage else ["eq-2"]},
                "problems": []}

    def conduct(self, coverage=True, waves=None):
        self.coverage = coverage
        with worker.use_fake() as fake:
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            self.conductor.absorb_dossier = self.absorb
            results = drive(self.conductor, waves)
            self.calls = list(fake.calls)
        return results

    def status(self, identifier=1):
        return tickets.read_ticket(next(tickets.tickets_dir(self.project).glob("%02d-*.md" % identifier)))[0]["status"]


class PromotionTest(DossierTicketCase):
    def setUp(self):
        super().setUp()
        self.write_dossier_ticket()
        self.conduct()

    def test_no_worker_session_is_launched(self):
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events("ticket_launched"), [])

    def test_the_paper_is_promoted_and_read_through_absorb(self):
        self.assertEqual(self.absorbed, [self.slug])
        self.assertEqual(read_dossier(self.ledger, self.slug)["level"], 2)
        promoted = self.events("promoted")
        self.assertEqual([(event["ticket"], event["payload"]["slug"], event["payload"]["trigger"]) for event in promoted],
                         [(1, self.slug, "planner_or_decider")])

    def test_the_journal_replays_to_a_done_ticket_with_nothing_owed(self):
        view = replay(self.events())
        self.assertEqual(view.tickets[1].status, "done")
        self.assertEqual(view.tickets[1].attempts, {})
        self.assertEqual(self.status(), "done")
        sequence = [event["event"] for event in self.events() if event["event"] in ("promoted", "absorbed", "ticket_done")]
        self.assertEqual(sequence[-3:], ["promoted", "absorbed", "ticket_done"])


class AlreadyReadTest(DossierTicketCase):
    def test_a_paper_already_read_in_full_is_not_read_again(self):
        dossier = read_dossier(self.ledger, self.slug)
        self.ledger.write_json("refs/%s/dossier.json" % self.slug, dict(dossier, level=2, l2={"coverage": {"pass": True}}))
        self.write_dossier_ticket()
        self.conduct()
        self.assertEqual(self.absorbed, [])
        self.assertEqual(self.status(), "done")


class CoverageFailsTest(DossierTicketCase):
    def test_a_read_that_misses_items_hands_the_ticket_to_a_person(self):
        self.write_dossier_ticket()
        self.conduct(coverage=False)
        self.assertEqual(self.status(), "needs_human")
        self.assertIn("eq-2", self.events("ticket_needs_human")[-1]["payload"]["question"])
        self.assertEqual(replay(self.events()).tickets[1].status, "needs_human")


class BeyondTheBudgetTest(DossierTicketCase):
    def setUp(self):
        super().setUp()
        for slug in ("one", "two", "three"):  # the phase's three level-2 reads already spent
            self.ledger.append_event("promoted", {"slug": slug, "from_level": 0, "to_level": 2, "trigger": "primary_at_intake"})
        self.write_dossier_ticket()
        self.conduct(waves=1)
        self.decision = [event for event in self.events("decision_opened")][-1]["ticket"]

    def test_the_ticket_waits_on_the_promotion_decision_it_opened(self):
        self.assertEqual(self.absorbed, [])
        fields = tickets.read_ticket(next(tickets.tickets_dir(self.project).glob("01-*.md")))[0]
        self.assertEqual((fields["status"], fields["blocked_by"]), ("open", [self.decision]))
        self.assertEqual(read_dossier(self.ledger, self.slug)["level"], 0)

    def test_a_yes_promotes_it_past_the_budget_and_reads_it(self):
        from wayline import project as projects
        projects.answer(self.project, self.decision, "Yes, promote it: its exact loss matters.")
        self.conduct(waves=3)
        self.assertEqual(self.absorbed, [self.slug])
        self.assertEqual(self.status(), "done")

    def test_a_no_closes_it_with_nothing_read(self):
        from wayline import project as projects
        projects.answer(self.project, self.decision, "No; the abstract is enough.")
        self.conduct(waves=3)
        self.assertEqual(self.absorbed, [])
        self.assertEqual(self.status(), "done")
        self.assertEqual(read_dossier(self.ledger, self.slug)["level"], 0)
