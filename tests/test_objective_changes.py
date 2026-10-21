"""Objective changes (Implementation Decision 17; ticket 91).

The seams are the ledger over a temporary project (the one-ticket fixture, laid out), the fake launcher for the
verifier's judgment, the decider's batch, and the answering verifier, and the conductor replayed from its journal.
What is asserted is what a later reader sees: the journal's `objective_proposed`, `objective`, `ticket_cancelled`, and
`marked` events, `research/objectives.json`, the "Objective changes" decision tickets and their batches, the tickets'
statuses and what pauses them, `SPEC.md`, the Discussion section, `CONCERNS.md`, and the account.
"""

import json

from tests.projects import open_objective
from tests.test_conductor import ConductorCase
from wayline import objective_changes, tickets
from wayline.jsonschema import ValidationError, check, load_schema
from wayline.objectives import change_objective, read_objectives


def proposal(kind="park", objective="O2", reason="the sweep shows the interaction terms add nothing past 0.70",
             evidence=("res:t1-a1/results/sweep.json#auroc",), feasibility=None, **extra):
    stated = {"kind": kind, "objective": objective, "reason": reason, "evidence": list(evidence), "feasibility": feasibility}
    stated.update(extra)
    return stated


FEASIBLE = {"verdict": "reachable", "reasoning": "the sweep already measures it", "revised_target": None}


class ChangesCase(ConductorCase):
    def setUp(self):
        super().setUp()
        open_objective(self.project, "Do interaction terms raise the held-out AUROC?")
        open_objective(self.project, "Is the gain robust to the noise level?")

    def proposed(self):
        return [event["payload"] for event in self.events("objective_proposed")]

    def objective(self, identifier):
        return {record["id"]: record for record in read_objectives(self.project)}[identifier]


class TheShapeTest(ChangesCase):
    def test_a_result_and_a_verdict_carry_objective_proposals_of_the_six_kinds(self):
        result = {"ticket_id": 1, "status": "done", "summary": "ran the sweep",
                  "objective_proposals": [proposal(kind) for kind in ("answer", "park", "drop", "reopen")]
                  + [proposal("add", "Does the gain survive label noise?", feasibility=FEASIBLE),
                     proposal("reframe", "O1", successor="Do the products raise AUROC under noise?", feasibility=FEASIBLE)]}
        check(result, load_schema("result"), name="result")
        verdict = {"pass": True, "findings": [], "question_limit": "the sweep",
                   "objective_judgments": [{"proposal": 1, "upheld": True, "why": "the sweep shows it", "answer": None}],
                   "objective_proposals": [proposal("drop")]}
        check(verdict, load_schema("verdict"), name="verdict")

    def test_a_kind_outside_the_six_is_refused_by_the_schema(self):
        with self.assertRaises(ValidationError):
            check({"ticket_id": 1, "status": "done", "summary": "x", "objective_proposals": [proposal("close")]},
                  load_schema("result"), name="result")


class JournalTest(ChangesCase):
    def test_each_proposal_of_a_result_is_journaled_waiting_for_its_verdict(self):
        waiting = objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2")])
        self.assertEqual([item["id"] for item in waiting], ["t1-a1/1"])
        self.assertEqual([(entry["id"], entry["kind"], entry["objective"], entry["ticket"], entry["by"], entry["upheld"])
                          for entry in self.proposed()], [("t1-a1/1", "park", "O2", 1, "worker", None)])
        self.assertEqual(self.proposed()[0]["proposal"], proposal("park", "O2"))

    def test_a_result_carried_again_journals_nothing_new(self):
        objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2")])
        again = objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2")])
        self.assertEqual(len(self.proposed()), 1)
        self.assertEqual([item["id"] for item in again], ["t1-a1/1"])

    def test_code_refuses_a_proposal_it_cannot_act_on_and_journals_it_not_upheld(self):
        change_objective(self.project, "O2", "parked", "owner", answer="later")
        waiting = objective_changes.take_result(self.project, 1, 1, [
            proposal("park", "O7"), proposal("park", "O2"), proposal("reopen", "O1"),
            proposal("add", "Does it hold on real data?"), proposal("reframe", "O1", feasibility=FEASIBLE),
            proposal("reopen", "O2")])
        self.assertEqual([item["id"] for item in waiting], ["t1-a1/6"])
        refused = [(entry["id"], entry["upheld"]) for entry in self.proposed()]
        self.assertEqual(refused, [("t1-a1/1", False), ("t1-a1/2", False), ("t1-a1/3", False), ("t1-a1/4", False),
                                   ("t1-a1/5", False), ("t1-a1/6", None)])
        whys = {entry["id"]: entry["why"] for entry in self.proposed()}
        self.assertIn("O7", whys["t1-a1/1"])
        self.assertIn("parked", whys["t1-a1/2"])
        self.assertIn("open", whys["t1-a1/3"])
        self.assertIn("feasibility", whys["t1-a1/4"])
        self.assertIn("successor", whys["t1-a1/5"])


def judged(*judgments, passed=True, proposals=(), findings=()):
    """The envelope of a verifier's verdict that judges objective proposals: `(number, upheld, why[, answer])` each."""
    from wayline.worker import Envelope
    record = {"pass": passed, "findings": list(findings), "question_limit": "Only ticket 1's work and its proposals.",
              "objective_judgments": [{"proposal": entry[0], "upheld": entry[1], "why": entry[2],
                                       "answer": entry[3] if len(entry) > 3 else None} for entry in judgments]}
    if proposals:
        record["objective_proposals"] = list(proposals)
    return Envelope(structured_output=record, num_turns=4, duration_ms=9000)


class EvidenceCase(ChangesCase):
    """A run artifact in the manifest, so an answer's `res` tag resolves and its numbers can be read."""

    def setUp(self):
        super().setUp()
        from wayline.provenance import register_artifact
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "sweep.json").write_text(json.dumps({"auroc": 0.70, "gain": 0.004}) + "\n", encoding="utf-8")
        register_artifact(self.project, "results/sweep.json", None, "t1-a1", 1)


ANSWER = "Interaction terms do not raise the held-out AUROC past 0.70 {res:t1-a1/results/sweep.json#auroc}."


class TheVerdictTest(EvidenceCase):
    def asks(self, difficulty, items, quality=()):
        from wayline import gates
        ticket = {"id": 1, "kind": "code", "acceptance": {"quality": list(quality)}}
        return gates.ticket_asks(ticket, difficulty, "sonnet", "research/tickets/01-write-the-hello-file.md",
                                 commit="abc123", objectives=items)

    def test_a_ticket_carrying_a_proposal_earns_a_verdict_at_difficulty_one_and_two(self):
        items = objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2")])
        for difficulty in (1, 2):
            with self.subTest(difficulty=difficulty):
                asks = self.asks(difficulty, items)
                self.assertEqual([ask.verdict_type for ask in asks], ["result"])
                self.assertEqual(asks[0].objective_proposals, items)
                self.assertIn("1. park O2: the sweep shows the interaction terms add nothing past 0.70", asks[0].question)
                self.assertIn("objective_judgments", asks[0].question)
        self.assertEqual(self.asks(1, []), [], "without a proposal a difficulty-1 ticket earns nothing, as before")

    def test_the_read_a_ticket_earns_already_carries_its_proposals(self):
        items = objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2")])
        asks = self.asks(3, items, quality=["the sweep is complete"])
        self.assertEqual([ask.verdict_type for ask in asks], ["quality", "diff"])
        self.assertIsNone(asks[0].objective_proposals)
        self.assertEqual(asks[1].objective_proposals, items)

    def verdict(self, *scripted):
        from wayline import gates, worker
        items = objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2"), proposal("answer", "O1")])
        ask = self.asks(1, items)[0]
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope, role="verifier")
            try:
                taken = gates.verdict_for(ask, project=self.project)
            finally:
                self.calls = list(fake.calls)
        return items, taken

    def test_the_verifier_judges_each_proposal_and_the_upholding_verifier_writes_the_answer(self):
        items, taken = self.verdict(judged((1, False, "one sweep is not enough to park it"), (2, True, "the sweep settles it", ANSWER)))
        self.assertTrue(taken.passed, "a proposal not upheld does not fail the verdict")
        objective_changes.take_judgments(self.project, items, taken.objective_judgments)
        found = {record["id"]: record for record in objective_changes.read_proposals(self.project)}
        self.assertEqual((found["t1-a1/1"]["upheld"], found["t1-a1/1"]["why"]), (False, "one sweep is not enough to park it"))
        self.assertEqual((found["t1-a1/2"]["upheld"], found["t1-a1/2"]["answer"]), (True, ANSWER))
        self.assertEqual(objective_changes.awaiting(self.project, 1), [])

    def test_a_verdict_that_leaves_a_proposal_unjudged_is_resumed_once_with_the_reason(self):
        _, taken = self.verdict(judged((1, False, "not enough")), judged((1, False, "not enough"), (2, False, "not yet")))
        self.assertEqual(len(self.calls), 2)
        self.assertIn("does not judge 2", self.calls[1].message)
        self.assertEqual(len(taken.objective_judgments), 2)

    def test_an_upheld_answer_must_pass_the_numbers_and_locator_checks(self):
        from wayline import gates
        untagged = "Interaction terms do not raise the held-out AUROC."
        wrong = "Interaction terms raise the held-out AUROC to 0.81 {res:t1-a1/results/sweep.json#auroc}."
        for text, said in ((untagged, "cites no"), (wrong, "0.81")):
            with self.subTest(text=text):
                _, taken = self.verdict(judged((1, True, "yes"), (2, True, "yes", text)), judged((1, True, "yes"), (2, True, "yes", text)))
                self.assertIn(said, self.calls[1].message)
                self.assertTrue(taken.passed, "the verdict on the work stands")
                second = taken.objective_judgments[1]
                self.assertEqual((second["upheld"], second["answer"]), (False, None), "the answer is not upheld, never written")
                self.assertIn(said, second["why"])
        with self.assertRaises(gates.GateError):
            self.verdict(judged((1, True, "yes")), judged((1, True, "yes")))  # a proposal left unjudged still loses it

    def test_a_proposal_the_verifier_makes_itself_goes_straight_on(self):
        objective_changes.take_verdict(self.project, 1, 1, "result", [proposal("drop", "O2")])
        found = objective_changes.read_proposals(self.project)
        self.assertEqual([(record["id"], record["by"], record["upheld"]) for record in found], [("t1-a1/result/1", "verifier", True)])


class GraphCase(EvidenceCase):
    """Ticket 1 done; tickets 2 to 4 open, serving O2 only, O1 and O2, and nothing; a spec whose claims name O1 and O2."""

    def setUp(self):
        super().setUp()
        from wayline import specify
        from tests.test_specify import draft
        first = self.ticket(1)
        path = tickets.tickets_dir(self.project) / tickets.filename(first)
        _, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(first, status="done", objectives=["O1"]), body)
        for identifier, served in ((2, ["O2"]), (3, ["O1", "O2"]), (4, [])):
            tickets.write_ticket(self.ledger, dict(first, id=identifier, title="Ticket %d" % identifier, status="open",
                                                   objectives=served, touches=["t%d.txt" % identifier]), body)
        spec = draft()
        spec["claims"][1]["objectives"] = ["O2"]
        spec["claims"][2]["objectives"] = ["O1", "O2"]
        specify._write(self.ledger, spec)
        self.spec_md = self.project / "research" / "SPEC.md"

    def statuses(self):
        return {fields["id"]: fields["status"] for fields in tickets.read_tickets(self.project)}

    def cancelled(self):
        return [(event["payload"]["ticket"], event["payload"]["by"], event["payload"].get("reason"))
                for event in self.events("ticket_cancelled")]

    def objective_events(self):
        return [(event["payload"]["id"], event["payload"]["status"], event["payload"]["by"], event["payload"].get("proposal"))
                for event in self.events("objective")]


class ApprovalTest(GraphCase):
    def test_a_park_parks_the_tickets_serving_only_that_objective_and_sets_its_claims_aside(self):
        from wayline import specify
        report = objective_changes.apply_change(self.project, proposal("park", "O2"), "owner", proposal_id="t1-a1/1")
        self.assertEqual(self.objective("O2")["status"], "parked")
        self.assertEqual(self.objective_events()[-1], ("O2", "parked", "owner", "t1-a1/1"))
        self.assertEqual(report["cancelled"], [2])
        self.assertEqual(self.statuses(), {1: "done", 2: "parked", 3: "open", 4: "open"},
                         "a ticket serving several keeps going while one is open, and one serving none is no objective's")
        self.assertEqual(self.cancelled(), [(2, "owner", "it serves only O2, which was parked")])
        text = self.spec_md.read_text(encoding="utf-8")
        self.assertIn("**C2.**", text)
        self.assertRegex(text, r"\*\*C2\.\*\*.*set aside: its objective O2 is closed")
        self.assertNotRegex(text, r"\*\*C3\.\*\*.*set aside")
        self.assertEqual(specify.check_spec(self.project, against_objectives=False), [])

    def test_a_reopen_brings_the_claims_and_the_tickets_its_park_set_aside_back(self):
        from wayline import specify
        objective_changes.apply_change(self.project, proposal("park", "O2"), "owner")
        report = objective_changes.apply_change(self.project, proposal("reopen", "O2"), "owner")
        self.assertEqual(self.objective("O2")["status"], "open")
        self.assertEqual(report["reopened"], [2])
        self.assertEqual(self.statuses()[2], "open")
        self.assertNotIn("set aside", self.spec_md.read_text(encoding="utf-8"))
        self.assertEqual(specify.check_spec(self.project, against_objectives=False), [])
        self.assertEqual(objective_changes.reopened(self.events()), [], "reopening a parked objective needs no new cut")

    def test_an_owners_reopen_of_an_answered_objective_keeps_the_old_answer_superseded_and_owes_a_cut(self):
        objective_changes.apply_change(self.project, dict(proposal("answer", "O2"), answer=ANSWER), "owner")
        objective_changes.apply_change(self.project, proposal("reopen", "O2"), "owner")
        found = self.objective("O2")
        self.assertEqual((found["status"], found["answer"]), ("open", None))
        self.assertEqual(found["superseded"], [{"status": "answered", "answer": ANSWER,
                                                "evidence": ["res:t1-a1/results/sweep.json#auroc"]}])
        self.assertEqual([identifier for identifier, _ in objective_changes.reopened(self.events())], ["O2"])

    def test_an_answer_is_written_by_code_as_a_discussion_passage(self):
        from wayline import sections
        objective_changes.apply_change(self.project, dict(proposal("answer", "O1"), answer=ANSWER), "decider", proposal_id="t1-a1/2")
        found = self.objective("O1")
        self.assertEqual((found["status"], found["answer"], found["evidence"]),
                         ("answered", ANSWER, ["res:t1-a1/results/sweep.json#auroc"]))
        passages = [item for item in sections.read_passages(self.project) if item["section"] == "discussion"]
        self.assertEqual([(item["by"], item["objectives"], item["text"]) for item in passages], [("objective:O1", ["O1"], ANSWER)])
        self.assertIn(ANSWER.split(" {")[0], (self.project / "research" / "sections" / "discussion.md").read_text(encoding="utf-8"))
        self.assertEqual(self.statuses()[3], "open", "ticket 3 still serves the open O2")

    def test_a_reframe_ties_the_tickets_and_the_claims_to_the_successor(self):
        from wayline import sections
        objective_changes.apply_change(self.project, proposal("reframe", "O2", successor="Is the gain robust to label noise?",
                                                              feasibility=FEASIBLE), "owner")
        self.assertEqual((self.objective("O2")["status"], self.objective("O2")["reframed_as"]), ("reframed", "O3"))
        self.assertEqual(self.objective("O3")["text"], "Is the gain robust to label noise?")
        served = {fields["id"]: fields.get("objectives") for fields in tickets.read_tickets(self.project)}
        self.assertEqual((served[2], served[3]), (["O3"], ["O1", "O3"]))
        self.assertEqual(self.statuses()[2], "open")
        self.assertNotIn("set aside", self.spec_md.read_text(encoding="utf-8"))
        passages = [item for item in sections.read_passages(self.project) if item["section"] == "discussion"]
        self.assertEqual([item["by"] for item in passages], ["objective:O2"])
        self.assertIn("O3", passages[0]["text"])

    def test_a_stopping_rule_naming_a_reframed_objective_waits_on_its_successor(self):
        from wayline import stopping
        objective_changes.apply_change(self.project, proposal("reframe", "O2", successor="Robust to label noise?", feasibility=FEASIBLE),
                                       "owner")
        records = read_objectives(self.project)
        self.assertEqual([record["id"] for record in stopping.waited(["O2"], records)], ["O3"])
        self.assertIsNone(stopping.rule_end(["O2"], records, []))

    def test_spec_md_shows_the_claims_set_aside_whoever_closed_their_objective(self):
        from wayline import specify
        change_objective(self.project, "O2", "answered", "code", answer="reached")
        self.assertRegex(self.spec_md.read_text(encoding="utf-8"), r"\*\*C2\.\*\*.*set aside")
        self.assertEqual(specify.check_spec(self.project, against_objectives=False), [])

    def test_a_ticket_parked_with_two_objectives_comes_back_when_one_of_them_reopens(self):
        objective_changes.apply_change(self.project, proposal("park", "O2"), "owner")
        objective_changes.apply_change(self.project, dict(proposal("answer", "O1"), answer=ANSWER), "owner")
        self.assertEqual(self.statuses()[3], "parked")
        self.assertIn("it serves only O1 and O2, which are closed", self.cancelled()[-1][2])
        objective_changes.apply_change(self.project, proposal("reopen", "O2"), "owner")
        self.assertEqual((self.statuses()[2], self.statuses()[3]), ("open", "open"),
                         "a ticket serving several keeps going while one of them is open")

    def test_an_add_records_an_open_objective(self):
        objective_changes.apply_change(self.project, proposal("add", "Does it hold on real data?", feasibility=FEASIBLE), "decider",
                                       proposal_id="t1-a1/3")
        self.assertEqual((self.objective("O3")["text"], self.objective("O3")["status"]), ("Does it hold on real data?", "open"))
        self.assertEqual(self.objective_events()[-1], ("O3", "open", "decider", "t1-a1/3"))


class BatchCase(GraphCase):
    def uphold(self, *stated, ticket=1, attempt=1, upheld=True):
        """Journal a result's proposals and the verdict's judgment of each: upheld (an answer with ANSWER) or not."""
        items = objective_changes.take_result(self.project, ticket, attempt, list(stated))
        objective_changes.take_judgments(self.project, items, [
            {"proposal": number, "upheld": upheld, "why": "the sweep bears it out" if upheld else "one sweep is not enough",
             "answer": ANSWER if upheld and item["kind"] == "answer" else None}
            for number, item in enumerate(items, start=1)])
        return items

    def settle(self):
        self.sent = []
        return objective_changes.settle(self.project, notify=lambda *args: self.sent.append(args))

    def changes_tickets(self):
        return [fields for fields in tickets.read_tickets(self.project) if objective_changes.is_changes_ticket(fields.get("origin"))]

    def batches(self):
        from wayline import batches
        return [batch for batch in batches.read_batches(self.project) if batch["kind"] == "objective_changes"]

    def paused(self, decision):
        return sorted(fields["id"] for fields in tickets.read_tickets(self.project) if decision in fields["blocked_by"])

    def answer(self, ticket, text):
        from wayline.project import answer
        answer(self.project, ticket, text)


class GatherTest(BatchCase):
    def test_an_upheld_proposal_opens_one_objective_changes_ticket_whose_items_are_a_batch(self):
        self.uphold(proposal("park", "O2"))
        report = self.settle()
        [ticket] = self.changes_tickets()
        self.assertEqual(report["opened"], [ticket["id"]])
        self.assertEqual(ticket["title"], "Objective changes")
        [batch] = self.batches()
        self.assertEqual((batch["decision"], batch["status"]), (ticket["id"], "open"))
        self.assertEqual([(item["ref"], item["marks"], item["mark"]) for item in batch["items"]],
                         [("t1-a1/1", ["approve", "decline"], None)])
        self.assertIn("park O2", batch["items"][0]["text"])
        self.assertEqual(self.paused(ticket["id"]), [2], "only the ticket serving O2 alone waits")
        self.assertEqual([event for event, _, _, _ in self.sent], ["decision_opened"])

    def test_new_upheld_proposals_join_the_open_ticket_until_it_is_answered(self):
        self.uphold(proposal("park", "O2"))
        self.settle()
        self.uphold(proposal("add", "Does it hold on real data?", feasibility=FEASIBLE), ticket=3)
        report = self.settle()
        self.assertEqual(report["opened"], [])
        [ticket] = self.changes_tickets()
        [batch] = self.batches()
        self.assertEqual([item["ref"] for item in batch["items"]], ["t1-a1/1", "t3-a1/1"])
        self.assertIn("Does it hold on real data?", (tickets.tickets_dir(self.project) / tickets.filename(ticket)).read_text(encoding="utf-8"))
        self.assertEqual(self.paused(ticket["id"]), [2], "an add pauses nothing")
        self.settle()
        self.assertEqual((len(self.changes_tickets()), len(self.batches()[0]["items"])), (1, 2), "a second settle changes nothing")

    def test_a_proposal_not_upheld_opens_nothing_and_is_listed_in_the_account_under_not_pursued(self):
        from wayline import account
        self.uphold(proposal("park", "O2"), upheld=False)
        self.settle()
        self.assertEqual(self.changes_tickets(), [])
        account.render_account(self.project)
        text = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        pursued = text.split("Not pursued", 1)[1]
        self.assertIn("t1-a1/1", pursued)
        self.assertIn("park O2", pursued)
        self.assertIn("one sweep is not enough", pursued)

    def test_answer_park_drop_and_reframe_pause_and_add_and_reopen_do_not(self):
        change_objective(self.project, "O1", "parked", "owner", answer="later")
        self.uphold(proposal("reopen", "O1"))
        self.settle()
        [ticket] = self.changes_tickets()
        self.assertEqual(self.paused(ticket["id"]), [])
        self.uphold(proposal("reframe", "O2", successor="Robust to label noise?", feasibility=FEASIBLE), ticket=3)
        self.settle()
        self.assertEqual(self.paused(ticket["id"]), [2, 3], "O1 is parked, so ticket 3 serves only O2 as long as it is")


class ApproveTest(BatchCase):
    def test_a_declined_proposal_resumes_what_it_paused(self):
        self.uphold(proposal("park", "O2"))
        self.settle()
        [ticket] = self.changes_tickets()
        self.answer(ticket["id"], "decline")
        report = self.settle()
        self.assertEqual(report["declined"], ["t1-a1/1"])
        self.assertEqual(self.objective("O2")["status"], "open")
        self.assertEqual(self.batches()[0]["items"][0]["mark"], "decline")
        self.assertEqual(self.batches()[0]["items"][0]["by"], "owner")
        self.assertEqual(self.statuses()[2], "open")
        self.assertEqual(self.paused(ticket["id"]), [])

    def test_the_owners_marks_apply_each_item_and_close_the_ticket(self):
        from wayline import batches
        self.uphold(proposal("park", "O2"), proposal("answer", "O1"))
        self.settle()
        [ticket] = self.changes_tickets()
        batch = self.batches()[0]
        batches.mark(self.project, batch["id"], 1, "approve")
        report = self.settle()
        self.assertEqual(report["applied"], ["t1-a1/1"])
        self.assertEqual([item["acted"] is not None for item in self.batches()[0]["items"]], [True, False], "a change made is final")
        self.assertEqual((self.objective("O2")["status"], self.statuses()[2]), ("parked", "parked"))
        self.assertEqual(self.objective_events()[-1], ("O2", "parked", "owner", "t1-a1/1"))
        self.assertNotIn(ticket["id"], [payload["ticket"] for payload in (event["payload"] for event in self.events("decision"))])
        batches.mark(self.project, batch["id"], 2, "approve")
        self.settle()
        self.assertEqual((self.objective("O1")["status"], self.objective("O1")["answer"]), ("answered", ANSWER))
        self.assertEqual(self.statuses()[3], "parked", "ticket 3 served O1 and O2, both closed now")
        [answered] = [event["payload"] for event in self.events("decision") if event["payload"]["ticket"] == ticket["id"]]
        self.assertEqual(answered["decided_by"], "human")
        self.assertIn("1: approve; 2: approve", answered["answer"])
        self.settle()
        self.assertEqual(len([event for event in self.events("objective") if event["payload"].get("proposal")]), 2,
                         "a settled batch applies nothing twice")

    def test_an_answer_naming_each_item_marks_each(self):
        self.uphold(proposal("park", "O2"), proposal("add", "Does it hold on real data?", feasibility=FEASIBLE))
        self.settle()
        [ticket] = self.changes_tickets()
        self.answer(ticket["id"], "1: decline; 2: approve")
        report = self.settle()
        self.assertEqual((report["applied"], report["declined"]), (["t1-a1/2"], ["t1-a1/1"]))
        self.assertEqual(self.objective("O3")["text"], "Does it hold on real data?")
        self.assertEqual(self.objective("O2")["status"], "open")

    def test_an_answer_that_leaves_items_unsettled_asks_again_for_those(self):
        self.uphold(proposal("park", "O2"), proposal("drop", "O1"))
        self.settle()
        [first] = self.changes_tickets()
        self.answer(first["id"], "1: approve")
        self.settle()
        later = [fields for fields in self.changes_tickets() if fields["id"] != first["id"]]
        self.assertEqual(len(later), 1)
        batch = self.batches()[0]
        self.assertEqual((batch["decision"], [item["mark"] for item in batch["items"]]), (later[0]["id"], ["approve", None]))
        self.assertEqual(self.objective("O1")["status"], "open")
        self.assertEqual(self.paused(later[0]["id"]), [3], "ticket 3 now serves only O1, which the open drop names")

    def test_an_answer_without_a_verifiers_text_is_owed_to_the_answering_verifier(self):
        objective_changes.take_verdict(self.project, 1, 1, "result", [proposal("answer", "O1")])
        self.settle()
        [ticket] = self.changes_tickets()
        self.answer(ticket["id"], "approve all")
        self.settle()
        self.assertEqual(self.objective("O1")["status"], "open", "the fresh verifier writes it")
        self.assertEqual([(identifier, by, made) for identifier, by, _, made in objective_changes.owed_answers(self.project)],
                         [("O1", "owner", "t1-a1/result/1")])


def answered(text=ANSWER, objective="O1"):
    from wayline.worker import Envelope
    return Envelope(structured_output={"objective": objective, "answer": text, "question_limit": "What the run found about O1."},
                    num_turns=4, duration_ms=9000)


class AnsweringVerifierTest(GraphCase):
    def answer(self, *scripted, by="decider"):
        from wayline import worker
        with worker.use_fake() as fake:
            for envelope in scripted:
                fake.script(envelope, role="verifier")
            try:
                return objective_changes.answer_as_it_stands(self.project, "O1", by, "ticket 9 chose to answer it as it stands")
            finally:
                self.calls = list(fake.calls)

    def test_one_fresh_verifier_on_opus_high_writes_the_answer_and_code_writes_it_as_a_discussion_passage(self):
        from wayline import sections
        report = self.answer(answered())
        [call] = self.calls
        self.assertEqual((call.request.model, call.request.effort, call.request.role, call.session_id), ("opus", "high", "verifier", None))
        self.assertTrue(str(call.request.schema_path).endswith("objective_answer.json"))
        self.assertIn("O1, \"Do interaction terms raise the held-out AUROC?\"", call.request.prompt)
        self.assertEqual((self.objective("O1")["status"], self.objective("O1")["answer"]), ("answered", ANSWER))
        self.assertEqual(self.objective_events()[-1], ("O1", "answered", "decider", None))
        passage = next(item for item in sections.read_passages(self.project) if item["id"] == report["passage"])
        self.assertEqual((passage["section"], passage["by"]), ("discussion", "objective:O1"))

    def test_an_answer_that_fails_the_checks_is_resumed_once_and_then_nothing_is_written(self):
        wrong = "Interaction terms raise the held-out AUROC to 0.81 {res:t1-a1/results/sweep.json#auroc}."
        report = self.answer(answered(wrong), answered())
        self.assertIn("0.81", self.calls[1].message)
        self.assertEqual(self.objective("O1")["status"], "answered")
        self.assertIsNotNone(report["passage"])

    def test_two_unusable_answers_write_nothing(self):
        with self.assertRaises(objective_changes.ProposalError):
            self.answer(answered("No tag here."), answered("No tag here either."))
        self.assertEqual(self.objective("O1")["status"], "open")


class OwnersWordTest(GraphCase):
    def run_verb(self, *args):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from wayline.objectives import objective_command
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = objective_command(list(args) + ["--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def test_the_objective_verbs_apply_the_owners_word_with_no_proposal_and_no_verdict(self):
        code, out, err = self.run_verb("park", "O2", "--reason", "the data arrives in March")
        self.assertEqual(code, 0, err)
        self.assertIn("O2  parked", out)
        self.assertIn("ticket(s) 2 parked", out)
        self.assertEqual(self.objective_events()[-1], ("O2", "parked", "owner", None))
        self.assertEqual(self.proposed(), [], "the owner's word is no proposal")
        self.assertEqual(self.events("verdict"), [])
        self.assertEqual(self.run_verb("reopen", "O2")[0], 0)
        self.assertEqual(self.statuses()[2], "open")
        self.assertEqual(self.run_verb("answer", "O1", "Interaction terms add nothing past 0.70.")[0], 0)
        self.assertEqual(self.objective("O1")["answer"], "Interaction terms add nothing past 0.70.")
        self.assertEqual(self.run_verb("reframe", "O2", "Is the gain robust to label noise?")[0], 0)
        self.assertEqual(self.objective("O2")["reframed_as"], "O3")
        self.assertEqual(self.run_verb("drop", "O3", "--reason", "out of scope")[0], 0)
        self.assertEqual(self.objective("O3")["status"], "dropped")

    def test_a_change_the_record_refuses_is_said_and_changes_nothing(self):
        code, _, err = self.run_verb("park", "O9")
        self.assertEqual(code, 2)
        self.assertIn("O9", err)
        code, _, err = self.run_verb("reopen", "O1")
        self.assertEqual(code, 2)
        self.assertIn("open", err)


class IrreversibleTest(ChangesCase):
    def test_changing_a_goals_measure_stays_on_the_list_and_the_objective_changes_leave_it(self):
        from wayline.decider import irreversible_class
        for text in ("change the goal to 0.74 AUROC on split_b", "lower the target to 0.74", "change the goal's measure",
                     "replace the eval command", "drop the eval command", "dropping the primary metric"):
            with self.subTest(text=text):
                self.assertEqual(irreversible_class(text), "goal")
        for text in ("drop the goal O2: the sweep answers nothing more", "park the goal until the data arrives",
                     "add a new goal on label noise", "reframe the goal as a narrower question", "reopen the goal",
                     "answer the goal from the sweep", "1: approve; 2: decline"):
            with self.subTest(text=text):
                self.assertIsNone(irreversible_class(text))


class DeciderBatchTest(BatchCase):
    def harness(self, **changes):
        from wayline.project import read_harness
        harness = read_harness(self.project)
        harness.update(changes)
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def decide(self, answer):
        from tests.test_decider import envelope
        from wayline import decider, decisions, worker
        fields = self.changes_tickets()[-1]
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        with worker.use_fake() as fake:
            fake.script(envelope(answer), role=decider.DECIDER)
            outcome = decider.decide_ticket(self.project, fields, body, decisions.decision_record(body), notify=lambda *args: None)
            self.prompt = fake.calls[0].request.prompt
        return outcome

    def marks(self):
        return [(item["mark"], item["by"]) for item in self.batches()[0]["items"]]

    def test_under_strict_with_objective_human_only_the_decider_answers_and_the_rest_waits_for_the_owner(self):
        self.harness(autonomy="autonomous", radius="strict", stop_when=["O1"])
        self.uphold(proposal("park", "O1"), proposal("drop", "O2"), proposal("add", "Does it hold on real data?", feasibility=FEASIBLE))
        self.settle()
        [first] = self.changes_tickets()
        self.assertEqual(self.paused(first["id"]), [2, 3])
        outcome = self.decide("1: approve; 2: approve; 3: approve (prerequisite)")
        self.assertEqual(outcome.status, "decided")
        self.assertIn("Objective changes", self.prompt)
        self.assertIn("The owner's to take: the stopping rule names O1", self.prompt)
        self.settle()
        self.assertEqual(self.marks(), [(None, None), ("approve", "decider"), (None, None)])
        self.assertEqual(self.objective("O2")["status"], "dropped")
        self.assertEqual(self.objective_events()[-1], ("O2", "dropped", "decider", "t1-a1/2"))
        later = self.changes_tickets()[-1]
        self.assertNotEqual(later["id"], first["id"])
        self.assertTrue(later["human_only"])
        self.assertIsNone(later["blocking"])
        self.assertEqual(self.batches()[0]["decision"], later["id"])
        self.assertEqual(self.paused(first["id"]) + self.paused(later["id"]), [], "what the decider may not take pauses nothing")
        self.assertEqual(self.statuses()[3], "open", "ticket 3 serves O1, still open, as the park waits on the owner")
        text = (tickets.tickets_dir(self.project) / tickets.filename(later)).read_text(encoding="utf-8")
        self.assertIn("left item(s) 1, 3, which wait for the owner", text)
        self.settle()
        self.assertEqual(len(self.changes_tickets()), 2, "asked once")

    def test_under_moderate_with_objective_off_the_list_the_decider_adds_a_prerequisite_only(self):
        self.harness(autonomy="autonomous", radius="moderate", human_only=["data"])
        self.uphold(proposal("add", "Does the baseline hold?", feasibility=FEASIBLE), proposal("add", "Does it hold on real data?", feasibility=FEASIBLE))
        self.settle()
        self.decide("1: approve (prerequisite); 2: approve")
        self.settle()
        self.assertEqual(self.marks(), [("approve", "decider"), (None, None)])
        self.assertEqual(self.objective("O3")["text"], "Does the baseline hold?")

    def test_under_exploratory_the_decider_adds_one_new_question_a_wave(self):
        self.harness(autonomy="autonomous", radius="exploratory", human_only=["data"])
        self.uphold(proposal("add", "Does it hold on real data?", feasibility=FEASIBLE),
                    proposal("add", "Does it hold on images?", feasibility=FEASIBLE),
                    proposal("reframe", "O2", successor="Robust to label noise?", feasibility=FEASIBLE))
        self.settle()
        self.decide("1: approve (new question); 2: approve (new question); 3: approve")
        self.settle()
        self.assertEqual(self.marks(), [("approve", "decider"), (None, None), ("approve", "decider")])
        self.assertEqual([self.objective(identifier)["text"] for identifier in ("O3", "O4")],
                         ["Does it hold on real data?", "Robust to label noise?"])

    def test_the_decider_reopens_a_parked_objective_at_every_radius_and_never_an_answered_one(self):
        self.harness(autonomy="autonomous", radius="strict", human_only=["data"])
        change_objective(self.project, "O1", "parked", "owner", answer="later")
        change_objective(self.project, "O2", "answered", "owner", answer="yes")
        self.uphold(proposal("reopen", "O1"), proposal("reopen", "O2"))
        self.settle()
        self.decide("approve all")
        self.settle()
        self.assertEqual(self.marks(), [("approve", "decider"), (None, None)])
        self.assertEqual((self.objective("O1")["status"], self.objective("O2")["status"]), ("open", "answered"))

    def test_a_drop_asks_for_its_concerns_in_the_same_answer(self):
        from wayline import concerns
        self.harness(autonomy="autonomous", radius="strict")
        ledger_record = {"concerns": [{
            "id": "K1", "sources": [{"critique": "D1", "locator": "D1#p2", "text": "Test it on label noise."}], "targets": [],
            "place": "objectives", "objectives": ["O2"], "status": "open", "answer": None, "reason": None, "proposed": None,
            "returned": None, "sorted_by": "owner"}], "split": []}
        self.ledger.write_json("concerns.json", ledger_record, schema="concern")
        self.harness(stop_when=["O1"])
        self.ledger.append_event("phase", {"from": None, "to": "P5"})  # past setup, where ticket 96 would ask on its own
        self.uphold(proposal("drop", "O2"))
        self.settle()
        [ticket] = self.changes_tickets()
        text = (tickets.tickets_dir(self.project) / tickets.filename(ticket)).read_text(encoding="utf-8")
        self.assertIn("concern K1", text)
        self.decide("1: approve; K1: for the order")
        self.settle()
        found = concerns.read_concerns(self.project)[0]
        self.assertEqual((found["place"], found["sorted_by"]), ("order", "decider"))
        self.assertEqual(concerns.settle(self.project)["opened"], [], "no concern ticket of its own after setup")


class ConductorTest(ChangesCase):
    """The conductor replayed: ticket 1 proposes, the verifier judges, the batch waits, the answer applies, once."""

    def setUp(self):
        super().setUp()
        self.set_harness(stop_when="frontier", autonomy="checkpoints")

    def set_harness(self, **changes):
        from wayline.project import read_harness
        harness = read_harness(self.project)
        harness.update(changes)
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def shape(self, difficulty=1, second=False):
        first = self.ticket(1)
        path = tickets.tickets_dir(self.project) / tickets.filename(first)
        _, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(first, difficulty=difficulty, objectives=["O1"]), body)
        if second:
            tickets.write_ticket(self.ledger, dict(first, id=2, title="Write the two file", objectives=["O2"], blocked_by=[1],
                                                   touches=["two.txt"], outputs=["two.txt"],
                                                   acceptance={"machine": ["test -f two.txt"], "quality": []}), body)

    def run_conductor(self, *scripted, decider_answers=()):
        import io
        from tests import machine
        from tests.test_decider import envelope
        from wayline import decider, worker
        from wayline.conductor import Conductor
        from tests.test_conductor import drive
        with worker.use_fake() as fake:
            for item in scripted:
                envelope_, applied, role = (tuple(item) + (None, None))[:3]
                fake.script(envelope_, patch=applied, role=role)
            for answer_ in decider_answers:
                fake.script(envelope(answer_), role=decider.DECIDER)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.notify = lambda *args: None
            results = []
            while True:
                results.extend(drive(self.conductor, 1))
                if results[-1].ended or len(results) >= 12:
                    break
                self.conductor.settle()
            self.calls = list(fake.calls)
        return results

    def changes_tickets(self):
        return [fields for fields in tickets.read_tickets(self.project) if objective_changes.is_changes_ticket(fields.get("origin"))]

    def test_a_proposal_at_difficulty_one_is_judged_batched_and_applied_once_on_the_owners_answer(self):
        from tests.test_conductor import done, patch
        from wayline.project import answer
        self.shape()
        self.run_conductor((done(objective_proposals=[proposal("park", "O2")]), patch()),
                           (judged((1, True, "the sweep bears it out")), None, "verifier"))
        self.assertEqual([call.request.role for call in self.calls], ["coder", "verifier"])
        self.assertEqual(self.payload("verdict")["verdict_type"], "result")
        self.assertEqual([(entry["id"], entry["upheld"]) for entry in self.proposed()], [("t1-a1/1", None), ("t1-a1/1", True)])
        [ticket] = self.changes_tickets()
        self.assertEqual(self.ticket(1)["status"], "accepted")
        self.assertEqual(self.ticket(ticket["id"])["status"], "open")
        self.assertEqual(self.objective("O2")["status"], "open", "nobody approved it yet")
        answer(self.project, ticket["id"], "approve all")
        self.run_conductor()
        self.assertEqual(self.objective("O2")["status"], "parked")
        self.assertEqual(self.ticket(ticket["id"])["status"], "done")
        applied = [event for event in self.events("objective") if event["payload"].get("proposal")]
        self.run_conductor()
        self.assertEqual([event for event in self.events("objective") if event["payload"].get("proposal")], applied,
                         "a restarted conductor applies nothing twice")
        self.assertEqual(len(self.changes_tickets()), 1)

    def test_what_an_upheld_park_pauses_waits_and_a_decline_resumes_it(self):
        from tests.test_conductor import done, patch
        from wayline.project import answer
        self.shape(difficulty=5, second=True)
        self.run_conductor((done(objective_proposals=[proposal("park", "O2")]), patch()),
                           (judged((1, True, "the sweep bears it out")), None, "verifier"))
        [ticket] = self.changes_tickets()
        self.assertEqual(self.ticket(1)["status"], "accepted")
        self.assertEqual((self.ticket(2)["status"], self.ticket(2)["blocked_by"]), ("open", [1, ticket["id"]]))
        self.assertNotIn(2, [event["payload"]["ticket"] for event in self.events("ticket_launched")])
        answer(self.project, ticket["id"], "decline")
        self.run_conductor((done(2, outputs_written=["two.txt"]), patch({"two.txt": "two\n"}, message="ticket 2: two")))
        self.assertEqual(self.objective("O2")["status"], "open")
        self.assertEqual(self.ticket(2)["status"], "done")

    def test_under_autonomous_the_decider_takes_the_batch_and_the_change_applies_in_the_same_wave(self):
        from tests.test_conductor import done, patch
        self.set_harness(autonomy="autonomous", radius="strict")
        self.shape(difficulty=5, second=True)
        self.run_conductor((done(objective_proposals=[proposal("park", "O2")]), patch()),
                           (judged((1, True, "the sweep bears it out")), None, "verifier"), decider_answers=["1: approve"])
        self.assertEqual(self.objective("O2")["status"], "parked")
        self.assertEqual(self.ticket(2)["status"], "parked")
        self.assertEqual([(event["payload"]["ticket"], event["payload"]["by"]) for event in self.events("ticket_cancelled")],
                         [(2, "decider")])
        self.assertNotIn(2, [event["payload"]["ticket"] for event in self.events("ticket_launched")])

    def test_a_failing_verdict_upholds_nothing_its_rejected_attempt_proposed(self):
        from tests.test_conductor import done, hold_the_ladder, patch
        hold_the_ladder(self)
        self.shape()
        finding = {"text": "hello.txt is empty", "locator": "hello.txt#L1", "severity": "blocker"}
        self.run_conductor((done(objective_proposals=[proposal("park", "O2")]), patch()),
                           (judged((1, True, "the sweep bears it out"), passed=False, findings=[finding]), None, "verifier"))
        [record] = objective_changes.read_proposals(self.project)
        self.assertFalse(record["upheld"])
        self.assertIn("verdict failed", record["why"])
        self.assertEqual(self.changes_tickets(), [])

    def test_a_batch_waiting_when_the_frontier_empties_is_the_ask_about_the_objectives_it_names(self):
        from tests.test_conductor import done, patch
        from wayline import stopping
        self.set_harness(stop_when="objectives")
        self.shape()
        results = self.run_conductor((done(objective_proposals=[proposal("park", "O2")]), patch()),
                                     (judged((1, True, "the sweep bears it out")), None, "verifier"))
        self.assertEqual(results[-1].reason, "frontier_empty")
        asked = [stopping.frontier_objective(fields.get("origin")) for fields in tickets.read_tickets(self.project)
                 if stopping.frontier_objective(fields.get("origin"))]
        self.assertEqual(asked, ["O1"], "O2 is asked about in the Objective changes ticket alone")
        self.assertEqual(len(self.changes_tickets()), 1)


class RestartTest(ChangesCase):
    def test_proposals_whose_judgment_never_reached_the_journal_ride_what_is_still_owed(self):
        from wayline import gates
        items = objective_changes.take_result(self.project, 1, 1, [proposal("park", "O2")])
        ticket = {"id": 1, "title": "Run the sweep", "kind": "code", "acceptance": {"quality": ["the sweep is complete"]}}
        earned, owed = gates.owed_asks(ticket, 3, "sonnet", "abc123", passed={"diff"}, objectives=items)
        self.assertEqual([ask.verdict_type for ask in owed], ["quality"])
        self.assertEqual(owed[0].objective_proposals, items)
        earned, owed = gates.owed_asks(ticket, 3, "sonnet", "abc123", passed={"diff", "quality"}, objectives=items)
        self.assertEqual([(ask.verdict_type, ask.objective_proposals) for ask in owed], [("diff", items)])
        earned, owed = gates.owed_asks(dict(ticket, acceptance={}), 1, "sonnet", "abc123", passed={"result"}, objectives=items)
        self.assertEqual([ask.verdict_type for ask in owed], ["result"])


class AnswerFormsTest(ChangesCase):
    def test_an_answer_marks_all_some_or_each_and_a_later_form_wins(self):
        self.assertEqual(objective_changes.answer_marks("approve all", 2), {1: ("approve", ""), 2: ("approve", "")})
        self.assertEqual(objective_changes.answer_marks("Decline.", 2), {1: ("decline", ""), 2: ("decline", "")})
        self.assertEqual(objective_changes.answer_marks("approve all; 2: decline", 3),
                         {1: ("approve", ""), 2: ("decline", ""), 3: ("approve", "")})
        self.assertEqual(objective_changes.answer_marks("approve 1 and 3, decline 2", 3),
                         {1: ("approve", ""), 2: ("decline", ""), 3: ("approve", "")})
        self.assertEqual(objective_changes.answer_marks("1: approve (prerequisite)", 2), {1: ("approve", " (prerequisite)")})
        self.assertEqual(objective_changes.answer_marks("not now", 2), {})
        self.assertEqual(objective_changes.answer_marks("5: approve", 2), {})

