"""Proposals admission (ticket 37; Implementation Decisions 5, 14; BRIEF 6.3, 9.5).

`wayline.proposals.admit_proposals` is driven directly against a temporary project (Testing
Decisions seam 3): the radius, the mechanical and judged duplicate checks, the per-wave cap, and
the blockers rule, each read back from the ticket files it wrote or the `research/proposals/`
files it parked, and the journal. One conductor-level test (`ConductorAdmitsProposalsTest`) drives
the fake worker (seam 1) through `fixtures/projects/one-ticket/`, to prove the wiring: a worker's
`proposals` are admitted or parked at the wave that carries its result.
"""

import json
import unittest

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive, patch
from wayline import decider, project, proposals, tickets, worker
from wayline.ledger import DECISION, Ledger
from wayline.tickets import write_ticket
from wayline.worker import Envelope

ONE_TICKET = FIXTURES_DIR / "projects" / "one-ticket"


def base_ticket(identifier, title, **extra):
    fields = {
        "id": identifier, "title": title, "kind": "code", "difficulty": 2, "status": "done",
        "blocked_by": [], "touches": ["src/"], "role": "coder", "acceptance": {"machine": [], "quality": []},
        "proposed_by": "planner",
    }
    fields.update(extra)
    return fields


def strict(title="Reproduce the headline claim", **extra):
    proposal = {"title": title, "kind": "code", "why": "it traces to the spec's headline claim", "radius": "strict"}
    proposal.update(extra)
    return proposal


def moderate(title="Probe why the headline claim fails on split B", **extra):
    proposal = {"title": title, "kind": "code", "why": "the claim held on split A and failed on split B", "radius": "moderate"}
    proposal.update(extra)
    return proposal


def exploratory(title="Try a completely different architecture", **extra):
    proposal = {"title": title, "kind": "code", "why": "nothing traces to a claim; this is a new direction", "radius": "exploratory"}
    proposal.update(extra)
    return proposal


class ProposalsCase(ProjectTestCase):
    """A bare project (no tickets) with the real harness checkout, so the real `dedup-judge` role reads."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        project.init_project(self.project)
        self.ledger = Ledger(self.project)

    def write(self, *fields):
        for entry in fields:
            write_ticket(self.ledger, entry)

    def events(self, name=None):
        found, _ = self.ledger.read_events()
        return [event for event in found if name is None or event["event"] == name]

    def admit(self, proposal_list, **kwargs):
        kwargs.setdefault("origin_ticket", 1)
        kwargs.setdefault("origin_prefix", "ticket 1 attempt 1")
        kwargs.setdefault("proposed_by", "worker:1")
        return proposals.admit_proposals(self.project, proposal_list, **kwargs)


class RadiusTest(ProposalsCase):
    """The project's `radius` (moderate by default) is a ceiling on a proposal's own declared radius."""

    def test_a_strict_proposal_is_inside_every_radius(self):
        # The strict cap is 0 by default (spec: the cap, not the radius, keeps strict work out in
        # practice); a raised cap isolates the radius rule itself from the cap rule below.
        policy = project.policy_for(self.project)
        policy["proposals"]["cap"] = dict(policy["proposals"]["cap"], strict=5)
        outcomes = self.admit([strict()], policy=policy)
        self.assertEqual(outcomes[0]["outcome"], "admitted")

    def test_a_moderate_proposal_is_inside_the_default_moderate_project_radius(self):
        outcomes = self.admit([moderate()])
        self.assertEqual(outcomes[0]["outcome"], "admitted")

    def test_an_exploratory_proposal_is_outside_the_default_moderate_project_radius(self):
        outcomes = self.admit([exploratory()])
        self.assertEqual(outcomes[0], {"id": outcomes[0]["id"], "outcome": "parked", "reason": "radius"})
        parked = json.loads((self.project / "research" / "proposals" / ("%s.json" % outcomes[0]["id"])).read_text(encoding="utf-8"))
        self.assertEqual(parked["reason"], "radius")
        self.assertEqual(parked["status"], "parked")

    def test_an_exploratory_proposal_is_inside_an_exploratory_project_radius(self):
        harness_path = self.project / "harness.json"
        harness = json.loads(harness_path.read_text(encoding="utf-8"))
        harness["radius"] = "exploratory"
        harness_path.write_text(json.dumps(harness), encoding="utf-8")
        outcomes = self.admit([exploratory()])
        self.assertEqual(outcomes[0]["outcome"], "admitted")

    def test_a_proposal_with_no_radius_or_an_unknown_one_is_parked_radius(self):
        outcomes = self.admit([strict(radius=None)])
        self.assertEqual(outcomes[0]["reason"], "radius")
        outcomes = self.admit([strict(title="A second one", radius="wide-open")])
        self.assertEqual(outcomes[0]["reason"], "radius")

    def test_the_journal_and_the_ticket_the_admission_writes(self):
        outcomes = self.admit([moderate(why="it probes claim C1's failure")])
        ticket = tickets.read_tickets(self.project)[0]
        self.assertEqual((ticket["kind"], ticket["proposed_by"], ticket["origin"], ticket["status"]),
                         ("code", "worker:1", "ticket 1 attempt 1: proposal 1", "open"))
        payload = self.events("proposal_admitted")[0]["payload"]
        self.assertEqual(payload, {"id": outcomes[0]["id"], "from": 1, "kind": "code", "ticket": ticket["id"]})


class DuplicateTest(ProposalsCase):
    """The mechanical check (same kind, title similarity) and the judged one (haiku, the dedup-judge role)."""

    def setUp(self):
        super().setUp()
        self.write(base_ticket(1, "Sweep the interaction strength across seeds", status="done"))

    def test_a_similarity_above_the_threshold_parks_mechanically_with_no_session(self):
        with worker.use_fake() as fake:
            outcomes = self.admit([moderate(title="Sweep interaction strength across seeds and folds")])
            self.assertEqual(fake.calls, [], "a similarity above the threshold never asks the judge")
        self.assertEqual(outcomes[0]["reason"], "duplicate")

    def test_a_similarity_in_the_judged_range_asks_the_dedup_judge_and_a_duplicate_verdict_parks_it(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"verdict": "duplicate", "reason": "same manipulation"}, num_turns=1, duration_ms=10),
                       role=proposals.DEDUP_ROLE)
            outcomes = self.admit([moderate(title="Sweep interaction magnitude across different seeds")])
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(fake.calls[0].request.model, "haiku")
            self.assertEqual(fake.calls[0].request.effort, "low")
        self.assertEqual(outcomes[0]["reason"], "duplicate")

    def test_a_similarity_in_the_judged_range_with_a_distinct_verdict_admits_it(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"verdict": "distinct", "reason": "a different manipulation entirely"},
                                 num_turns=1, duration_ms=10), role=proposals.DEDUP_ROLE)
            outcomes = self.admit([moderate(title="Sweep interaction magnitude across different seeds")])
            self.assertEqual(len(fake.calls), 1, "the judged range still asks, even though it admits")
        self.assertEqual(outcomes[0]["outcome"], "admitted")

    def test_a_low_similarity_of_a_different_kind_is_not_a_duplicate(self):
        outcomes = self.admit([moderate(title="Write the onboarding docs", kind="docs")])
        self.assertEqual(outcomes[0]["outcome"], "admitted")

    def test_an_identical_touch_set_and_origin_is_a_duplicate_without_a_title_match(self):
        # A ticket a *later* proposal of the same source (`ticket 9 attempt 1`) was admitted as:
        # its origin's source, once the `: proposal N` suffix `_origin` adds is cut, is what a new
        # proposal of the same source and the same touches is compared against.
        self.write(base_ticket(2, "Completely unrelated title", touches=["a.py", "b.py"], origin="ticket 9 attempt 1: proposal 2"))
        outcomes = self.admit([moderate(title="Nothing alike in words", touches=["b.py", "a.py"])],
                              origin_prefix="ticket 9 attempt 1")
        self.assertEqual(outcomes[0]["reason"], "duplicate")


class CapTest(ProposalsCase):
    def test_the_moderate_cap_of_three_parks_the_fourth_moderate_proposal_this_wave(self):
        titles = ["Probe why the claim fails on split B", "Add a null control for the manipulation",
                  "Re-run the pipeline with a different seed", "Plot the residuals by group"]
        wave_cap = {}
        outcomes = []
        for index, title in enumerate(titles):
            outcomes += self.admit([moderate(title=title)], origin_prefix="ticket 1 attempt %d" % index, wave_cap=wave_cap)
        self.assertEqual([entry["outcome"] for entry in outcomes], ["admitted", "admitted", "admitted", "parked"])
        self.assertEqual(outcomes[3]["reason"], "cap")

    def test_the_strict_cap_of_zero_parks_every_strict_proposal(self):
        outcomes = self.admit([strict()], wave_cap={})
        self.assertEqual(outcomes[0]["reason"], "cap")

    def test_a_fresh_call_with_no_wave_cap_given_does_not_carry_the_count_from_a_previous_one(self):
        self.admit([moderate(title="First of a wave")])
        outcomes = self.admit([moderate(title="Something about a null control instead")])
        self.assertEqual(outcomes[0]["outcome"], "admitted")


class BlockersTest(ProposalsCase):
    def test_a_blocked_by_naming_no_ticket_parks_blockers(self):
        outcomes = self.admit([moderate(blocked_by=[99])])
        self.assertEqual(outcomes[0]["reason"], "blockers")

    def test_a_blocked_by_naming_an_existing_ticket_admits(self):
        self.write(base_ticket(1, "An existing ticket"))
        outcomes = self.admit([moderate(blocked_by=[1])])
        self.assertEqual(outcomes[0]["outcome"], "admitted")
        self.assertEqual(tickets.read_tickets(self.project)[-1]["blocked_by"], [1])


class ParkedTest(ProposalsCase):
    def test_parked_is_never_deleted_and_status_stays_parked(self):
        self.admit([exploratory()])
        found = list((self.project / "research" / "proposals").glob("*.json"))
        self.assertEqual(len(found), 1)
        record = json.loads(found[0].read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "parked")
        self.assertEqual(record["title"], exploratory()["title"])

    def test_a_repeated_call_with_the_same_origin_does_not_park_or_journal_twice(self):
        self.admit([exploratory()])
        self.admit([exploratory()])
        self.assertEqual(len(list((self.project / "research" / "proposals").glob("*.json"))), 1)
        self.assertEqual(len(self.events("proposal_parked")), 1)

    def test_a_repeated_call_with_the_same_origin_does_not_admit_twice(self):
        self.admit([moderate()])
        outcomes = self.admit([moderate()])
        self.assertEqual(len(tickets.read_tickets(self.project)), 1)
        self.assertEqual(len(self.events("proposal_admitted")), 1)
        self.assertEqual(outcomes[0]["outcome"], "admitted")


class ApplyAdmittedTest(ProposalsCase):
    """`apply_admitted` reads the decider's `admit`/`keep parked` opinion (ticket 31) back and actually admits it."""

    def park_and_decide(self, proposal, answer):
        parked = self.admit([proposal], wave_cap={"strict": 5})[0]  # a raised strict cap keeps this out of the way, unparked
        self.ledger.append_event(DECISION, {"ticket": None, "answer": decider.PROPOSAL_ANSWER % (parked["id"], answer),
                                           "decided_by": decider.DECIDER, "rationale": "because", "confidence": 0.8})
        return parked["id"]

    def test_an_admit_answer_admits_it_within_the_cap(self):
        identifier = self.park_and_decide(exploratory(), decider.ADMIT)
        outcomes = proposals.apply_admitted(self.project)
        self.assertEqual(outcomes, [{"id": identifier, "outcome": "admitted", "ticket": outcomes[0]["ticket"]}])
        ticket = tickets.read_tickets(self.project)[0]
        self.assertEqual(ticket["id"], outcomes[0]["ticket"])
        record = json.loads((self.project / "research" / "proposals" / ("%s.json" % identifier)).read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "admitted")  # never deleted; its status moves off `parked`

    def test_a_keep_parked_answer_admits_nothing(self):
        self.park_and_decide(exploratory(), decider.KEEP_PARKED)
        self.assertEqual(proposals.apply_admitted(self.project), [])
        self.assertEqual(tickets.read_tickets(self.project), [])

    def test_an_admit_answer_the_cap_does_not_allow_stays_parked(self):
        identifier = self.park_and_decide(exploratory(), decider.ADMIT)
        caps = project.policy_for(self.project)["proposals"]["cap"]
        outcomes = proposals.apply_admitted(self.project, wave_cap={"exploratory": caps["exploratory"]})
        self.assertEqual(outcomes, [{"id": identifier, "outcome": "parked", "reason": "cap"}])
        self.assertEqual(tickets.read_tickets(self.project), [])

    def test_an_undecided_parked_proposal_is_left_alone(self):
        self.admit([exploratory()], wave_cap={"strict": 5})
        self.assertEqual(proposals.apply_admitted(self.project), [])


class ConductorAdmitsProposalsTest(ConductorCase):
    """The wiring: a worker's `proposals` are admitted or parked at the wave that carries its result (ticket 37)."""

    def test_a_result_s_proposals_are_admitted_and_parked_by_the_wave_that_carries_it(self):
        self.conduct((done(proposals=[moderate(), exploratory()]), patch()))
        outcomes_admitted = self.events("proposal_admitted")
        outcomes_parked = self.events("proposal_parked")
        self.assertEqual(len(outcomes_admitted), 1)
        self.assertEqual(len(outcomes_parked), 1)
        self.assertEqual(outcomes_admitted[0]["payload"]["from"], 1)
        admitted_ticket = tickets.read_tickets(self.project)[outcomes_admitted[0]["payload"]["ticket"] - 1]
        self.assertEqual(admitted_ticket["proposed_by"], "worker:1")
        parked = list((self.project / "research" / "proposals").glob("*.json"))
        self.assertEqual(len(parked), 1)


if __name__ == "__main__":
    unittest.main()
