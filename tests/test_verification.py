"""Verifying inherited results (decision 17; ticket 97).

The seam is the ledger over a temporary project. The documents are the synthetic start-midway project of ticket 78
(`fixtures/midway/`, nothing of PINF): its manuscript deconstructed by ticket 93's verb, its referee reports split
into concerns by ticket 96's. The critic, the grill's owner, the decider, the consultant, and the verifier are
scripted through the fake launcher; the conductor's part is code's step, read back from the journal. What is asserted
is what a later reader sees: `research/verifications.json`, `VERIFICATIONS.md`, `POSITION.md`, `DECISIONS.md`, the
objectives, the passages and findings, the ticket files, and the journal.
"""

import json

from tests.test_conductor import ConductorCase, done, patch
from tests.test_documents import MIDWAY
from tests.test_inherited import InheritedCase
from wayline import sections, verification
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger


class VerificationCase(InheritedCase):
    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")
        self.deconstruct()
        self.claims = {item["doc"]: item["id"] for item in self.ours() if item["section"] == "results" and item.get("standing")}

    def record(self):
        return json.loads((self.project / "research" / "verifications.json").read_text(encoding="utf-8"))

    def result(self, heading="Results"):
        return next(item for item in verification.read_results(self.project) if item["heading"] == heading)

    def journaled(self):
        return [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "verification"]

    def rendered(self):
        return (self.project / "research" / "VERIFICATIONS.md").read_text(encoding="utf-8")


class InheritedResultsTest(VerificationCase):
    def test_an_inherited_result_is_one_inherited_results_heading_with_all_its_claims(self):
        self.assertTrue(verification.midway(self.project))
        found = verification.inherited_results(self.project)
        self.assertEqual(found, [{"heading": "Results", "claims": [self.claims["D1#p4.s1"], self.claims["D1#p4.s2"],
                                                                     self.claims["D1#p5.s1"]]}])

    def test_a_project_with_no_inherited_results_claim_is_no_start_midway(self):
        from wayline.project import init_project

        other = self.temp / "fresh"
        init_project(other, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=None)
        self.assertFalse(verification.midway(other))
        self.assertEqual(verification.inherited_results(other), [])

    def test_the_record_holds_each_result_unchecked_journaled_and_rendered(self):
        verification.follow(self.project)
        check(self.record(), load_schema("verification"), name="verifications.json")
        result = self.result()
        self.assertEqual((result["standing"], result["reason"], result["verdicts"]), ("unchecked", None, []))
        self.assertEqual(self.journaled(), [{"heading": "Results", "standing": "unchecked", "route": None, "by": "code"}])
        self.assertIn("## Results", self.rendered())
        self.assertIn("unchecked", self.rendered())
        self.assertEqual(verification.follow(self.project), [], "following again changes nothing")


# --- setup: the critic's table, the objective it proposes, the grill's one question ------------------------------

def material_rows(**states):
    """The critic's table for the midway project's one inherited result: the code is present, the 2021 sweep's data is
    missing (no rebuild brings recordings back), the colony counts are fetchable, and MATLAB is licensed and missing."""
    needs = [
        {"kind": "code", "item": "phaselock.py and phaselock.m at the recorded commit", "state": "present", "licensed": False, "rebuild": True},
        {"kind": "data", "item": "data/dusk-sweep-2021.csv", "state": states.get("sweep", "missing"), "licensed": False, "rebuild": False},
        {"kind": "data", "item": "the public colony census", "state": "fetchable", "licensed": False, "rebuild": False},
        {"kind": "software", "item": "MATLAB with the Signal Processing Toolbox", "state": states.get("matlab", "missing"),
         "licensed": True, "rebuild": True},
    ]
    return [{"result": "Results", "needs": needs}]


class SetupCase(VerificationCase):
    """The midway project at setup: its critiques split, its threads taken, two objectives open, the critic's memo written."""

    def setUp(self):
        from tests import test_concerns
        from tests.projects import open_objective
        from wayline import concerns, project, worker
        from wayline.worker import Envelope

        super().setUp()
        self.add(MIDWAY / "critiques" / "referee-1.md", kind="critique")
        self.add(MIDWAY / "critiques" / "referee-2.md", kind="critique")
        self.dusk = self.claims["D1#p4.s2"]
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output=test_concerns.splitter_answer(self.dusk, self.claims["D1#p4.s1"]), session_id="split-1",
                                 num_turns=1), role=concerns.SPLITTER)
            concerns.split_critiques(self.project)
        concerns.from_comments(self.project)
        Ledger(self.project).write_markdown("INTAKE.md", test_concerns.INTAKE)
        harness = project.read_harness(self.project)
        harness["radius"] = "exploratory"
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        for question in test_concerns.QUESTIONS:
            open_objective(self.project, question)

    def memo(self, rows=None):
        from tests import test_concerns

        value = test_concerns.critic_memo()
        value["material"] = material_rows() if rows is None else rows
        return value

    def position(self, *memos):
        from wayline import position, worker
        from wayline.worker import Envelope

        with worker.use_fake() as fake:
            for value in memos or (self.memo(),):
                fake.script(Envelope(structured_output=value, session_id="critic-1", num_turns=3), role=position.CRITIC)
            from tests.scout_net import quiet_search
            with quiet_search():  # the setup search of the missing prior work (ticket 99)
                report = position.position(self.project, notify=lambda *args: None)
            self.critic_calls = [call for call in fake.calls if call.request.role == position.CRITIC]
        return report

    def records(self):
        from wayline import grill

        return grill.read_records(self.project)

    def question(self, words):
        from wayline import grill

        grill.grill_view(self.project)
        return next(record for record in self.records() if words in record["question"] and record.get("answer") is None)

    def answer(self, identifier, text, rationale="as the owner says"):
        from wayline import grill

        return grill.answer(self.project, identifier, text, rationale)

    def first_tier(self, verify="open"):
        """The first tier settled: each objective open, as the owner says, and "Do the inherited results hold?" as `verify`."""
        from wayline import grill

        grill.grill_view(self.project)
        for record in self.records():
            if record.get("objective") and record.get("answer") is None:
                self.answer(record["id"], verify if record["objective"]["text"] == verification.OBJECTIVE else "open")
        grill.grill_view(self.project)

    def objective(self):
        from wayline import objectives

        return next((item for item in objectives.read_objectives(self.project) if item["text"] == verification.OBJECTIVE), None)


class CriticTableTest(SetupCase):
    def test_the_critic_is_asked_for_a_row_per_inherited_result_and_its_table_is_rendered(self):
        report = self.position()
        self.assertIsNone(report["stopped"], report)
        prompt = self.critic_calls[0].request.prompt
        self.assertIn("one row in `material` for each of Results", prompt)
        self.assertIn("fetchable", prompt)
        memo = (self.project / "research" / "POSITION.md").read_text(encoding="utf-8")
        self.assertIn("## What each inherited result needs", memo)
        self.assertIn("| Results | data | data/dusk-sweep-2021.csv | missing |", memo)
        self.assertIn("| Results | data | the public colony census | fetchable |", memo)
        self.assertIn('the critic proposes the objective "Do the inherited results hold?"', memo)

    def test_only_missing_items_are_recorded_and_fetchable_data_is_never_missing(self):
        self.position()
        material = self.record()["material"]
        self.assertEqual([(item["id"], item["kind"], item["item"], item["licensed"], item["found_by"]) for item in material],
                         [("M1", "data", "data/dusk-sweep-2021.csv", False, "critic"),
                          ("M2", "software", "MATLAB with the Signal Processing Toolbox", True, "critic")])
        self.assertEqual({(item["reply"], item["by"]) for item in material}, {(None, None)})

    def test_a_memo_with_no_row_for_an_inherited_result_is_returned_once(self):
        report = self.position(self.memo([]), self.memo())
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(len(self.critic_calls), 2)
        self.assertIn("the inherited result Results has no row in material", self.critic_calls[1].message)

    def test_a_row_naming_no_inherited_result_fails_the_memo(self):
        from wayline import objectives, position

        rows = material_rows() + [{"result": "Methods", "needs": []}]
        failures = position.check_memo(self.memo(rows), "exploratory", objectives.read_objectives(self.project),
                                       results=verification.inherited_results(self.project))
        self.assertIn("a row of material names Methods, which is no inherited result", failures)


class ObjectiveProposalTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.position()

    def test_the_first_tier_asks_whether_the_project_takes_the_objective_open_by_default_and_human_only(self):
        record = self.question(verification.OBJECTIVE)
        self.assertEqual(record["objective"], {"id": None, "text": verification.OBJECTIVE})
        self.assertEqual(record["recommended"], "open")
        self.assertTrue(record["human_only"])
        self.assertTrue(any("start midway" in line for line in record["evidence"]), record["evidence"])

    def test_the_owner_may_park_it(self):
        self.first_tier(verify="parked")
        self.assertEqual(self.objective()["status"], "parked")

    def test_taken_open_it_is_recorded_open(self):
        self.first_tier()
        self.assertEqual(self.objective()["status"], "open")


class MaterialQuestionTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.position()

    def material_question(self):
        return next(record for record in self.records() if record.get("material") and record.get("answer") is None)

    def item(self, identifier):
        return next(entry for entry in self.record()["material"] if entry["id"] == identifier)

    def test_one_human_only_question_asks_about_every_missing_item_with_its_replies(self):
        self.first_tier()
        record = self.material_question()
        self.assertEqual(record["material"], {"ids": ["M1", "M2"]})
        self.assertTrue(record["human_only"])
        self.assertEqual(len([other for other in self.records() if other.get("material")]), 1, "one question for every item")
        for reply in ("I'll provide it", "rebuild it", "leave it unverified", "port to Octave", "port to Python"):
            self.assertIn(reply, record["options"])
        self.assertEqual(record["recommended"], "as recommended")
        self.assertIn("data/dusk-sweep-2021.csv", record["question"])
        self.assertIn("MATLAB with the Signal Processing Toolbox", record["question"])
        evidence = "\n".join(record["evidence"])
        self.assertIn("M1: recommended leave it unverified", evidence)
        self.assertIn("M2: licensed software, so I'll provide it, port to Octave, or port to Python; recommended port to Octave", evidence)

    def test_no_question_while_the_objective_is_parked(self):
        self.first_tier(verify="parked")
        self.assertFalse([record for record in self.records() if record.get("material")])

    def test_the_owners_replies_are_recorded_item_by_item(self):
        self.first_tier()
        self.answer(self.material_question()["id"], "M1: I'll provide it; M2: port to Python")
        self.assertEqual([(self.item(name)["reply"], self.item(name)["by"]) for name in ("M1", "M2")],
                         [("I'll provide it", "owner"), ("port to Python", "owner")])
        self.assertEqual(self.result()["standing"], "unchecked")

    def test_as_recommended_takes_each_items_recommendation(self):
        self.first_tier()
        self.answer(self.material_question()["id"], "as recommended")
        self.assertEqual([self.item(name)["reply"] for name in ("M1", "M2")], ["leave it unverified", "port to Octave"])

    def test_leave_it_unverified_makes_the_result_unverifiable_with_the_reason(self):
        self.first_tier()
        self.answer(self.material_question()["id"], "leave it unverified")
        result = self.result()
        self.assertEqual(result["standing"], "unverifiable")
        self.assertIn("data/dusk-sweep-2021.csv is missing and the owner left it unverified", result["reason"])
        standing = {item["doc"]: item.get("standing") for item in self.ours() if item["section"] == "results"
                    and item.get("standing") and item["id"] in sections.current_ids(self.project, "results")}
        self.assertEqual(set(standing.values()), {"unverifiable"})
        self.assertEqual(self.journaled()[-1], {"heading": "Results", "standing": "unverifiable", "route": None, "by": "owner"})

    def test_a_reply_outside_the_set_is_refused_and_records_nothing(self):
        from wayline.grill import GrillError

        self.first_tier()
        identifier = self.material_question()["id"]
        with self.assertRaises(GrillError) as refused:
            self.answer(identifier, "M2: maybe later")
        self.assertIn("port to Octave or port to Python", str(refused.exception))
        with self.assertRaises(GrillError):
            self.answer(identifier, "maybe later")
        self.assertEqual(self.item("M1")["reply"], None, "nothing recorded from a refused answer")

    def test_a_licensed_items_rebuild_is_its_port_to_octave(self):
        self.first_tier()
        self.answer(self.material_question()["id"], "M1: I'll provide it; M2: rebuild it")
        self.assertEqual(self.item("M2")["reply"], "port to Octave")


def finding(identifier, ticket, replaces, evidence, text="R is lowest at dusk in 38 of 40 colonies.", heading="Results"):
    return {"id": identifier, "ticket": ticket, "text": text, "provenance": "results/verify/dusk.json#min_r", "negative": False,
            "heading": heading, "replaces": replaces, "evidence": evidence, "objectives": []}


class AnsweringCase(SetupCase):
    """Past the grill's first tier with the objective open, and the owner's replies: provide the 2021 sweep, port MATLAB to Python."""

    def setUp(self):
        super().setUp()
        self.position()
        self.first_tier()
        self.answer(next(record["id"] for record in self.records() if record.get("material")), "M1: I'll provide it; M2: port to Python")


class AnsweringTest(AnsweringCase):
    def test_code_answers_the_objective_once_every_inherited_result_has_a_verdict(self):
        verification.follow(self.project)
        self.assertEqual(self.objective()["status"], "open")
        for number, (doc, evidence) in enumerate((("D1#p4.s1", "supports"), ("D1#p4.s2", "narrows"), ("D1#p5.s1", "contradicts")), 1):
            sections.file_finding(self.project, finding("t9-a1-f%d" % number, 9, self.claims[doc], evidence))
        verification.follow(self.project)
        self.assertEqual(self.result()["standing"], "verified")
        objective = self.objective()
        self.assertEqual(objective["status"], "answered")
        self.assertIn("Results: verified", objective["answer"])
        events = [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "objective"]
        self.assertEqual((events[-1]["status"], events[-1]["by"]), ("answered", "code"))

    def test_an_unverifiable_result_counts_as_settled(self):
        verification.leave_unverifiable(self.project, "Results", "the 2021 recordings are gone", "owner")
        verification.follow(self.project)
        self.assertEqual(self.objective()["status"], "answered")
        self.assertIn("Results: unverifiable (the 2021 recordings are gone)", self.objective()["answer"])

    def test_a_parked_objective_is_not_answered_by_code(self):
        from wayline import objectives

        objectives.change_objective(self.project, self.objective()["id"], "parked", "owner", answer="later")
        verification.leave_unverifiable(self.project, "Results", "the 2021 recordings are gone", "owner")
        verification.follow(self.project)
        self.assertEqual(self.objective()["status"], "parked")

    def test_a_result_its_document_withdrew_leaves_the_record_and_counts_as_no_verdict(self):
        verification.follow(self.project)
        for doc in ("D1#p4.s1", "D1#p4.s2", "D1#p5.s1"):
            item = next(passage for passage in self.ours() if passage["id"] == self.claims[doc])
            sections.add_passage(self.project, "results", item["heading"], item["text"], by="document:D1", replaces=item["id"],
                                 doc=item["doc"], withdrawn=True)
        verification.follow(self.project)
        self.assertEqual(verification.read_results(self.project), [], "a withdrawn result is no inherited result")
        self.assertEqual(self.objective()["status"], "open", "nothing was verified, so code answers nothing")


class SpecifyTest(AnsweringCase):
    def draft(self, inherited="Results", objectives=None):
        import copy
        from tests.test_specify import DRAFT
        from wayline import objectives as objective_records

        value = copy.deepcopy(DRAFT)
        opened = [item["id"] for item in objective_records.read_objectives(self.project) if item["status"] == "open"]
        verify = self.objective()["id"]
        for claim in value["claims"]:
            claim["objectives"] = [identifier for identifier in opened if identifier != verify]
        value["claims"][2]["objectives"] = [verify] if objectives is None else objectives
        value["claims"][2]["inherited"] = inherited
        return value

    def failures(self, draft):
        from wayline import objectives, specify

        return specify.check_draft(draft, objectives.read_objectives(self.project), inherited=verification.spec_inherited(self.project))

    def test_one_claim_per_inherited_result_under_the_objective_passes(self):
        self.assertEqual(verification.spec_inherited(self.project), {"objective": self.objective()["id"], "headings": ["Results"]})
        self.assertEqual(self.failures(self.draft()), [])

    def test_an_inherited_result_with_no_claim_fails(self):
        failures = self.failures(self.draft(inherited=None))
        self.assertIn("the inherited result Results has no claim: draft one claim with `inherited` naming it, under %s"
                      % self.objective()["id"], failures)

    def test_a_claim_naming_no_inherited_result_or_not_under_the_objective_fails(self):
        self.assertIn("claim C3 verifies Methods, which is no inherited result waiting for its verdict", self.failures(self.draft("Methods")))
        failures = self.failures(self.draft(objectives=[]))
        self.assertIn("claim C3 verifies the inherited result Results and does not name %s" % self.objective()["id"], failures)

    def test_the_spec_renders_which_result_a_claim_verifies(self):
        from wayline import specify

        self.assertIn("verifies the inherited result Results", specify.render_spec(self.draft()))

    def test_the_planners_prompt_names_each_inherited_result(self):
        from wayline import specify, worker

        role = worker.read_role(specify.PLANNER)
        prompt = specify.specify_prompt(role, "", {"autonomy": "checkpoints", "radius": "moderate"}, self.project,
                                        inherited=verification.spec_inherited(self.project))
        self.assertIn("# The inherited results", prompt)
        self.assertIn("- Results: %s" % ", ".join(self.result()["claims"]), prompt)


def planned(key, title, objectives, verifies=None, kind="experiment", blocked_by=()):
    item = {"key": key, "title": title, "kind": kind, "difficulty": 2, "blocked_by": list(blocked_by), "touches": ["results/%s/" % key],
            "acceptance": {"machine": ["test -d results/%s" % key], "quality": []}, "objectives": list(objectives),
            "context_pack": ["research/SPEC.md"], "origin": "research/SPEC.md#claims", "demo": "%s runs" % title}
    if verifies is not None:
        item["verifies"] = verifies
    return item


class PlanCase(AnsweringCase):
    """Past the grill: the dusk contradiction (K1, which targets the dusk claim) tied to O1, the size series to O2."""

    def setUp(self):
        from wayline import concerns

        super().setUp()
        concerns.place(self.project, ["K1"], ("objectives", ["O1"]), "owner")
        self.verify = self.objective()["id"]

    def prepare(self, *tickets, kind="plan"):
        from wayline import plan

        record = {"tickets": list(tickets), "decisions": [], "notes": ""}
        return plan.prepare(record, self.project, plan.read_all(self.project), {}, plan.Cut(kind))

    def by_key(self, prepared):
        return {key: fields for key, fields, _, _ in prepared.tickets}


class PlanWiringTest(PlanCase):
    def test_a_verification_ticket_blocks_the_tickets_built_on_its_result_through_the_concerns_ties(self):
        prepared = self.prepare(planned("T1", "Re-run the dusk series at the recorded commit", [self.verify], verifies="Results"),
                                planned("T2", "Rule out lamp flicker", ["O1"]), planned("T3", "Count moths per colony", ["O2"]))
        self.assertEqual(prepared.failures, [])
        tickets = self.by_key(prepared)
        self.assertEqual(tickets["T1"]["verifies"], "Results")
        self.assertIn(tickets["T1"]["id"], tickets["T2"]["blocked_by"], "O1 is tied to the dusk claim through K1")
        self.assertNotIn(tickets["T1"]["id"], tickets["T3"]["blocked_by"], "nothing ties O2 to the inherited result")

    def test_the_planner_may_split_a_large_result_and_each_piece_blocks(self):
        prepared = self.prepare(planned("T1", "Re-run the size series", [self.verify], verifies="Results"),
                                planned("T2", "Re-run the dusk sweep", [self.verify], verifies="Results"),
                                planned("T3", "Rule out lamp flicker", ["O1"]))
        tickets = self.by_key(prepared)
        self.assertEqual(sorted(tickets["T3"]["blocked_by"]), sorted([tickets["T1"]["id"], tickets["T2"]["id"]]))
        self.assertEqual(tickets["T2"]["blocked_by"], [], "a verification never waits on another")

    def test_a_plan_with_no_verification_of_a_waiting_result_fails(self):
        prepared = self.prepare(planned("T1", "Rule out lamp flicker", ["O1"]), planned("T2", "Count moths per colony", ["O2"]))
        self.assertIn("the inherited result Results waits for its verdict and no ticket verifies it: add one with `verifies` naming "
                      "it, under %s" % self.verify, prepared.failures)

    def test_a_ticket_verifying_no_inherited_result_fails(self):
        prepared = self.prepare(planned("T1", "Re-run the Methods", [self.verify], verifies="Methods"),
                                planned("T2", "Re-run the dusk series", [self.verify], verifies="Results"))
        self.assertIn("T1 (ticket %d) verifies Methods, which is no inherited result waiting for its verdict"
                      % self.by_key(prepared)["T1"]["id"], prepared.failures)

    def test_with_the_objective_parked_nothing_is_asked_of_the_plan(self):
        from wayline import objectives

        objectives.change_objective(self.project, self.verify, "parked", "owner", answer="later")
        prepared = self.prepare(planned("T1", "Rule out lamp flicker", ["O1"]))
        self.assertEqual(prepared.failures, [])

    def test_a_recut_wires_a_kept_ticket_built_on_the_result_too(self):
        from wayline import tickets

        kept = {"id": 1, "title": "Rule out lamp flicker", "kind": "experiment", "difficulty": 2, "status": "failed", "blocked_by": [],
                "touches": ["results/flicker/"], "role": "experimenter", "skills": [], "objectives": ["O1"],
                "acceptance": {"machine": ["test -d results/flicker"], "quality": []}, "context_pack": ["research/SPEC.md"],
                "origin": "research/SPEC.md#claims", "proposed_by": "planner", "demo": "flicker ruled out"}
        tickets.write_ticket(Ledger(self.project), kept, "## Demo\n\nflicker ruled out\n")
        prepared = self.prepare(planned("T1", "Re-run the dusk series", [self.verify], verifies="Results"), kind="replan")
        self.assertEqual(prepared.failures, [])
        self.assertEqual(prepared.repointed[1]["blocked_by"], [self.by_key(prepared)["T1"]["id"]])


INTAKE_COMMIT = "4f2c9a1b7d3e8f60c5a2b9d1e7f3c8a6b2d4e9f1"


class VerdictCase(PlanCase):
    """The plan written: ticket 1 verifies Results, ticket 2 (O1) waits on it, ticket 3 (O2) does not; intake recorded the code's commit."""

    def setUp(self):
        from wayline import project, tickets

        super().setUp()
        harness = project.read_harness(self.project)
        harness["code_repository"] = {"upstream": {"clone": str(self.temp / "phaselock"), "url": None, "commit": INTAKE_COMMIT,
                                                   "uncommitted": None, "license": None}}
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        prepared = self.prepare(planned("T1", "Re-run the dusk series at the recorded commit", [self.verify], verifies="Results"),
                                planned("T2", "Rule out lamp flicker", ["O1"]), planned("T3", "Count moths per colony", ["O2"]))
        ledger = Ledger(self.project)
        for _, fields, body, _ in prepared.tickets:
            tickets.write_ticket(ledger, fields, body)
            ledger.append_event("ticket_created", {"ticket": fields["id"], "kind": fields["kind"], "proposed_by": "planner",
                                                   "origin": fields["origin"], "blocked_by": fields["blocked_by"]}, ticket=fields["id"])
        self.ids = {key: fields["id"] for key, fields, _, _ in prepared.tickets}

    def fields(self, key):
        from wayline import tickets

        return next(item for item in tickets.read_tickets(self.project) if item["id"] == self.ids[key])

    def returned(self, route="reproduced", commit=INTAKE_COMMIT, substitute=None, evidence=("supports", "narrows", "contradicts")):
        findings = [{"text": "Finding %d." % number, "provenance": "results/verify/r.json#k%d" % number, "negative": False,
                     "heading": "Results", "replaces": self.claims[doc], "evidence": said}
                    for number, (doc, said) in enumerate(zip(("D1#p4.s1", "D1#p4.s2", "D1#p5.s1"), evidence), 1)]
        return {"ticket_id": self.ids["T1"], "status": "done", "summary": "re-ran it", "findings": findings,
                "verification": {"route": route, "commit": commit, "substitute": substitute}}

    def standing(self, heading="Results"):
        return next(item for item in verification.read_results(self.project) if item["heading"] == heading)


class ResultCheckTest(VerdictCase):
    def problems(self, result):
        return verification.check_result(self.project, self.fields("T1"), result)

    def test_a_reproduction_at_the_commit_intake_recorded_passes(self):
        self.assertEqual(self.problems(self.returned()), [])
        self.assertEqual(self.problems(self.returned(commit=INTAKE_COMMIT[:12])), [], "an abbreviated commit names it too")

    def test_a_reproduction_at_another_commit_is_refused(self):
        problems = self.problems(self.returned(commit="0123456789abcdef"))
        self.assertTrue(any("reproduced runs the project's own code at the commit intake recorded, %s" % INTAKE_COMMIT[:12] in problem
                            for problem in problems), problems)

    def test_a_verification_names_its_route(self):
        result = self.returned()
        result.pop("verification")
        problems = self.problems(result)
        self.assertTrue(any("names no route" in problem for problem in problems), problems)
        self.assertEqual(verification.check_result(self.project, self.fields("T2"), {"status": "done", "findings": []}), [],
                         "a ticket that verifies nothing is held to none of it")

    def test_a_verdict_on_substitute_data_narrows_every_claim_to_that_data(self):
        problems = self.problems(self.returned(route="ported", commit=None, substitute="the 2023 dusk sweep in place of the 2021 one"))
        self.assertEqual(problems, ["finding 1 replaces %s on substitute data (the 2023 dusk sweep in place of the 2021 one) and says "
                                    "supports: a verdict on substitute data covers only the claim narrowed to that data, so its "
                                    "evidence is narrows" % self.claims["D1#p4.s1"],
                                    "finding 3 replaces %s on substitute data (the 2023 dusk sweep in place of the 2021 one) and says "
                                    "contradicts: a verdict on substitute data covers only the claim narrowed to that data, so its "
                                    "evidence is narrows" % self.claims["D1#p5.s1"]])
        self.assertEqual(self.problems(self.returned(route="ported", commit=None, substitute="the 2023 sweep",
                                                   evidence=("narrows",) * 3)), [])

    def test_a_read_is_codes_route(self):
        problems = verification.check_result(self.project, self.fields("T1"), dict(self.returned(), verification={"route": "read", "commit": None,
                                                                                                                  "substitute": None}))
        self.assertTrue(any("read is the consultant's route" in problem for problem in problems), problems)

    def test_a_running_result_is_held_to_its_route_too(self):
        problems = self.problems(dict(self.returned(commit="0123456789abcdef"), status="running", findings=[]))
        self.assertTrue(any("reproduced runs the project's own code" in problem for problem in problems), problems)
        self.assertEqual(self.problems(dict(self.returned(), status="blocked")), [], "a blocked result is held to none of it")


class FreshVerifierTest(VerdictCase):
    """The fresh verifier at acceptance checks each verdict on an inherited claim explicitly."""

    def setUp(self):
        super().setUp()
        verification.attach_contradiction(self.project, [self.claims["D1#p4.s2"]],
                                          "The abstract says synchrony peaks at dusk; the Results say R is lowest at dusk.")
        self.items = verification.verdict_items(self.project, self.fields("T1"), self.returned())

    def asks(self, difficulty=3):
        from wayline import gates

        return gates.ticket_asks(self.fields("T1"), difficulty, "sonnet", "research/tickets/01-verify.md", commit="abc123",
                                 inherited=self.items)

    def judged(self, holds=(True, True, True)):
        return [{"claim": item["claim"], "holds": held, "why": "the re-run's output says so"} for item, held in zip(self.items, holds)]

    def test_each_inherited_claim_is_listed_with_its_verdict_route_and_contradictions(self):
        self.assertEqual([(item["claim"], item["evidence"], item["route"]) for item in self.items],
                         [(self.claims["D1#p4.s1"], "supports", "reproduced"), (self.claims["D1#p4.s2"], "narrows", "reproduced"),
                          (self.claims["D1#p5.s1"], "contradicts", "reproduced")])
        (ask,) = self.asks()
        for text in ("`inherited`", "The order parameter is lowest at dusk across every colony.", "narrows", "Finding 2.",
                     "reproduced at %s" % INTAKE_COMMIT[:12], "peaks at dusk"):
            self.assertIn(text, ask.question)
        self.assertEqual(ask.inherited, self.items)
        self.assertEqual(self.result()["contradictions"][0]["claims"], [self.claims["D1#p4.s2"]])

    def test_a_ticket_that_earns_no_read_earns_one_for_its_inherited_claims(self):
        from wayline import gates

        (ask,) = self.asks(difficulty=2)
        self.assertEqual(ask.verdict_type, gates.RESULT)
        self.assertIn("`inherited`", ask.question)

    def test_a_verdict_that_leaves_a_claim_unjudged_is_sent_back_and_one_that_does_not_hold_fails(self):
        from tests.test_verdicts import failing, passing
        from wayline import gates, worker

        (ask,) = self.asks()
        with worker.use_fake() as fake:
            fake.script(passing(inherited=self.judged()[:2]))
            fake.script(passing(inherited=self.judged()))
            taken = gates.verdict_for(ask, project=self.project)
            self.assertIn("does not judge %s" % self.claims["D1#p5.s1"], fake.calls[1].message)
        self.assertTrue(taken.passed)
        self.assertEqual(taken.inherited, self.judged())
        with worker.use_fake() as fake:
            fake.script(passing(inherited=self.judged((True, False, True))))
            fake.script(failing(text="The dusk claim's narrowing overstates the re-run.", locator="results/verify/r.json",
                                inherited=self.judged((True, False, True))))
            taken = gates.verdict_for(ask, project=self.project)
            self.assertIn("does not hold", fake.calls[1].message)
        self.assertFalse(taken.passed)


class PackTest(VerdictCase):
    def test_the_verification_tickets_pack_holds_its_claims_the_commit_the_contradictions_and_the_material(self):
        verification.attach_contradiction(self.project, [self.claims["D1#p4.s2"]], "The abstract says synchrony peaks at dusk.")
        text = verification.pack_text(self.project, self.fields("T1"))
        for words in ("# The inherited result this ticket verifies: Results", INTAKE_COMMIT,
                      "%s (unchecked): The order parameter is lowest at dusk across every colony." % self.claims["D1#p4.s2"],
                      "The abstract says synchrony peaks at dusk.", "M1 data data/dusk-sweep-2021.csv: I'll provide it",
                      "M2 software MATLAB with the Signal Processing Toolbox: port to Python", "material <code|data|software>"):
            self.assertIn(words, text)
        self.assertEqual(verification.pack_text(self.project, self.fields("T2")), "", "a ticket that verifies nothing gets none")
        cut = verification.pack_text(self.project, self.fields("T1"), max_chars=400)
        self.assertLessEqual(len(cut), 520)
        self.assertIn("research/VERIFICATIONS.md", cut)


class RepeatedClaimsContradictionTest(VerdictCase):
    """A contradiction the repeated-claims check lists (ticket 95) reaches the verification of its result, read where it is
    listed, so one the owner marked not a contradiction does not."""

    WHY = "lowest at dusk against peaks at dusk"

    def record(self, outcome):
        from wayline import repeats

        ledger = Ledger(self.project)
        with ledger.lock():
            record = repeats.read_record(ledger)
            entry = repeats._entry(self.claims["D1#p4.s2"], self.claims["D1#p5.s1"], ["consistency"], None,
                                   {"label": repeats.CONTRADICTING, "why": self.WHY})
            entry.update(outcome=outcome, flag=True, results=["Results"])
            record["pairs"].append(entry)
            repeats._save(ledger, record)

    def test_the_pack_and_the_verifier_carry_a_contradiction_the_check_lists(self):
        from wayline import repeats

        self.record(repeats.CONTRADICTION)
        self.assertIn("- %s (%s, %s)" % (self.WHY, self.claims["D1#p4.s2"], self.claims["D1#p5.s1"]),
                      verification.pack_text(self.project, self.fields("T1")))
        items = verification.verdict_items(self.project, self.fields("T1"), self.returned())
        self.assertEqual([item["contradictions"] for item in items], [[], [self.WHY], [self.WHY]])

    def test_one_the_owner_marked_not_a_contradiction_is_not_carried(self):
        from wayline import repeats

        self.record(repeats.DISMISSED)
        self.assertNotIn(self.WHY, verification.pack_text(self.project, self.fields("T1")))
        items = verification.verdict_items(self.project, self.fields("T1"), self.returned())
        self.assertEqual([item["contradictions"] for item in items], [[], [], []])


class VerdictTakenTest(VerdictCase):
    def file(self, result):
        for number, item in enumerate(result["findings"], 1):
            sections.file_finding(self.project, dict(item, id="t%d-a1-f%d" % (self.ids["T1"], number), ticket=self.ids["T1"], objectives=[]))
        return verification.take_result(self.project, self.fields("T1"), result)

    def test_the_verdict_is_recorded_with_its_route_and_the_result_verified(self):
        self.file(self.returned())
        result = self.standing()
        self.assertEqual(result["standing"], "verified")
        (verdict,) = result["verdicts"]
        self.assertEqual((verdict["ticket"], verdict["route"], verdict["commit"], verdict["substitute"]),
                         (self.ids["T1"], "reproduced", INTAKE_COMMIT, None))
        self.assertEqual([(entry["claim"], entry["evidence"]) for entry in verdict["claims"]],
                         [(self.claims["D1#p4.s1"], "supports"), (self.claims["D1#p4.s2"], "narrows"), (self.claims["D1#p5.s1"], "contradicts")])
        self.assertEqual(self.journaled()[-1], {"heading": "Results", "standing": "verified", "route": "reproduced", "by": "code"})
        self.assertIn("reproduced at %s" % INTAKE_COMMIT[:12], self.rendered())

    def test_a_verdict_settling_part_of_the_result_leaves_it_unchecked(self):
        result = self.returned()
        result["findings"] = result["findings"][:1]
        self.file(result)
        self.assertEqual(self.standing()["standing"], "unchecked")
        self.assertEqual(len(self.standing()["verdicts"]), 1)


# --- after setup: a gap is a decision pausing only its verification; unverifiable releases --------------------


class AfterSetupCase(VerdictCase):
    """Setup has ended (P4 -> P5): what code's step reads back from the journal and the files at each wave."""

    def setUp(self):
        super().setUp()
        Ledger(self.project).append_event("phase", {"from": "P4", "to": "P5"})
        self.notified = []

    def notify(self, event, text, project=None, ticket=None):
        self.notified.append((event, text, ticket))

    def settle(self):
        return verification.settle(self.project, notify=self.notify)

    def autonomy(self, level):
        from wayline import project

        harness = project.read_harness(self.project)
        harness["autonomy"] = level
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")

    def material_tickets(self):
        from wayline import tickets

        return [fields for fields in tickets.read_tickets(self.project) if verification.material_of(fields.get("origin"))]

    def decision(self, fields):
        from wayline import decisions, tickets

        return decisions.decision_record(tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1])

    def item(self, identifier):
        return next(entry for entry in verification.read_record(self.project)["material"] if entry["id"] == identifier)

    def block(self, key, path):
        """The verification ticket ends blocked on missing material, as the conductor records a worker's `blocked_on`."""
        from wayline import tickets

        fields = self.fields(key)
        ledger = Ledger(self.project)
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        tickets.write_ticket(ledger, dict(fields, status="blocked"), body)
        ledger.append_event("ticket_blocked", {"ticket": fields["id"], "path": path}, ticket=fields["id"])

    def needs_human(self, key, question="the port of phaselock.m disagrees with the manuscript and a person has to look"):
        from wayline import tickets

        fields = self.fields(key)
        ledger = Ledger(self.project)
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        tickets.write_ticket(ledger, dict(fields, status="needs_human"), body)
        ledger.append_event("ticket_needs_human", {"ticket": fields["id"], "question": question}, ticket=fields["id"])

    def decide(self, fields, answer, rationale="a rebuild from the Methods can work"):
        from tests.test_decider import envelope
        from wayline import decider, decisions, tickets, worker

        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        with worker.use_fake() as fake:
            fake.script(envelope(answer, rationale=rationale), role=decider.DECIDER)
            return decider.decide_ticket(self.project, fields, body, decisions.decision_record(body), notify=self.notify)


class NewGapTest(AfterSetupCase):
    def test_a_gap_a_verification_reports_is_one_decision_pausing_only_that_verification(self):
        from wayline import tickets

        self.block("T1", "material data: the lamp spectra of 2021")
        report = verification.open_gap(self.project, self.ids["T1"], "material data: the lamp spectra of 2021", notify=self.notify)
        self.assertEqual(self.item("M3")["found_by"], "ticket %d" % self.ids["T1"])
        (fields,) = self.material_tickets()
        self.assertEqual(report["ticket"], fields["id"])
        self.assertEqual(verification.material_of(fields["origin"]), "M3")
        record = self.decision(fields)
        self.assertEqual(record["options"], ["I'll provide it", "rebuild it", "leave it unverified"])
        self.assertIn("the lamp spectra of 2021", record["question"])
        self.assertEqual(record["blocking"], "subgraph")
        graph = tickets.build_graph(tickets.read_tickets(self.project))
        paused = tickets.paused_by(graph, [fields["id"]])
        self.assertEqual(paused, {self.ids["T1"], self.ids["T2"]}, "the verification and what waits on it, nothing else")
        self.assertIn(self.ids["T3"], [entry["id"] for entry in graph["tickets"] if entry["status"] == "open"])
        self.assertEqual(self.settle()["opened"], [], "asked once")

    def test_an_answer_that_provides_or_rebuilds_opens_the_blocked_verification_again(self):
        from wayline import project

        self.block("T1", "material data: the lamp spectra of 2021")
        verification.open_gap(self.project, self.ids["T1"], "material data: the lamp spectra of 2021", notify=self.notify)
        project.answer(self.project, self.material_tickets()[0]["id"], "rebuild it", rationale="rebuild them from the 2022 log")
        report = self.settle()
        self.assertEqual((self.item("M3")["reply"], self.item("M3")["by"]), ("rebuild it", "owner"))
        self.assertEqual(report["applied"], ["M3"])
        self.assertEqual(self.fields("T1")["status"], "open")
        reruns = [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "ticket_rerun"]
        self.assertEqual(reruns, [{"ticket": self.ids["T1"], "by": "code"}])

    def test_the_same_gap_reported_again_before_an_answer_is_the_same_ask(self):
        self.block("T1", "material data: the lamp spectra of 2021")
        first = verification.open_gap(self.project, self.ids["T1"], "material data: the lamp spectra of 2021", notify=self.notify)
        again = verification.open_gap(self.project, self.ids["T1"], "material data: the lamp spectra of 2021", notify=self.notify)
        self.assertEqual(again["ticket"], first["ticket"])
        self.assertFalse(again["opened"])
        self.assertEqual(len(self.material_tickets()), 1)

    def test_blocked_on_another_thing_is_no_gap(self):
        self.assertIsNone(verification.gap_of("software octave: the signal package"))
        self.assertEqual(verification.gap_of("material software: MATLAB R2021a"), ("software", "MATLAB R2021a"))


class PendingGapTest(AfterSetupCase):
    """Two items still wait for a reply when setup ends: the owner skipped the question."""

    def setUp(self):
        super().setUp()
        ledger = Ledger(self.project)
        with ledger.lock():
            record = verification.read_record(ledger)
            for item in record["material"]:
                item.update(reply=None, by=None)
            ledger.write_json(verification.VERIFICATIONS_JSON, record, schema=verification.SCHEMA)

    def test_under_checkpoints_each_pending_gap_is_the_owners_decision_and_the_answer_is_taken(self):
        from wayline import project

        report = self.settle()
        tickets_ = self.material_tickets()
        self.assertEqual([verification.material_of(fields["origin"]) for fields in tickets_], ["M1", "M2"])
        self.assertEqual(report["opened"], [fields["id"] for fields in tickets_])
        licensed = self.decision(tickets_[1])
        self.assertEqual(licensed["options"], ["I'll provide it", "port to Octave", "port to Python", "leave it unverified"])
        self.assertEqual(licensed["recommended"], "port to Octave")
        self.assertEqual(self.decision(tickets_[0])["recommended"], "leave it unverified", "no rebuild brings recordings back")
        self.assertFalse(any(fields["human_only"] for fields in tickets_), "the class is not human-only; under checkpoints no decider runs")
        project.answer(self.project, tickets_[1]["id"], "port to Python")
        self.settle()
        self.assertEqual((self.item("M2")["reply"], self.item("M2")["by"]), ("port to Python", "owner"))

    def test_under_autonomous_the_decider_rebuilds_or_leaves_and_never_provides(self):
        self.autonomy("autonomous")
        self.settle()
        first, second = self.material_tickets()
        refused = self.decide(first, "I'll provide it")
        self.assertEqual(refused.status, "refused")
        self.assertIn("never provide", refused.why)
        self.assertTrue(self.material_tickets()[0]["human_only"], "turned over to the owner")
        decided = self.decide(second, "port to Python")
        self.assertEqual(decided.status, "decided")
        self.settle()
        self.assertEqual((self.item("M2")["reply"], self.item("M2")["by"]), ("port to Python", "decider"))
        self.assertEqual(self.item("M1")["reply"], None)

    def test_nothing_is_asked_while_the_objective_is_parked(self):
        from wayline import objectives

        objectives.change_objective(self.project, self.verify, "parked", "owner", answer="the owner will verify it later")
        self.assertEqual(self.settle()["opened"], [])
        self.assertEqual(self.material_tickets(), [])

    def test_a_licensed_items_rebuild_from_the_decider_is_taken_as_its_port(self):
        self.autonomy("autonomous")
        self.settle()
        self.assertEqual(self.decide(self.material_tickets()[1], "rebuild it").status, "decided")
        self.assertEqual(self.settle()["applied"], ["M2"])
        self.assertEqual(self.item("M2")["reply"], "port to Octave")
        self.assertEqual(len(self.material_tickets()), 2, "asked once")

    def test_leave_it_unverified_makes_the_result_unverifiable_and_releases_what_its_verification_blocked(self):
        from wayline import project, tickets

        self.settle()
        project.answer(self.project, self.material_tickets()[0]["id"], "leave it unverified", rationale="the recordings are lost")
        self.settle()
        result = self.standing()
        self.assertEqual(result["standing"], "unverifiable")
        self.assertIn("data/dusk-sweep-2021.csv is missing and the owner left it unverified", result["reason"])
        self.assertNotIn(self.ids["T1"], self.fields("T2")["blocked_by"], "released")
        self.assertEqual(self.fields("T1")["status"], "parked")
        self.assertEqual(self.journaled()[-1], {"heading": "Results", "standing": "unverifiable", "route": None, "by": "owner",
                                                "released": [self.ids["T2"]]})
        graph = tickets.build_graph(tickets.read_tickets(self.project))
        self.assertIn(self.ids["T2"], [entry["id"] for entry in tickets.frontier(graph)])


class NeedsHumanTest(AfterSetupCase):
    def test_under_autonomous_a_verification_ending_needs_human_makes_its_result_unverifiable(self):
        self.autonomy("autonomous")
        self.needs_human("T1")
        self.settle()
        result = self.standing()
        self.assertEqual(result["standing"], "unverifiable")
        self.assertIn("ended needs_human under autonomous", result["reason"])
        self.assertIn("the port of phaselock.m disagrees", result["reason"])
        self.assertNotIn(self.ids["T1"], self.fields("T2")["blocked_by"])
        self.assertEqual(self.journaled()[-1]["by"], "code")
        self.assertEqual(self.journaled()[-1]["released"], [self.ids["T2"]])

    def test_under_checkpoints_it_waits_for_the_owner(self):
        self.needs_human("T1")
        self.settle()
        self.assertEqual(self.standing()["standing"], "unchecked")
        self.assertIn(self.ids["T1"], self.fields("T2")["blocked_by"])

    def test_replaying_the_journal_asks_and_releases_nothing_twice(self):
        self.autonomy("autonomous")
        self.needs_human("T1")
        self.settle()
        count = len(self.journaled())
        self.assertEqual(self.settle(), {"opened": [], "applied": [], "waiting": [], "unverifiable": []})
        self.assertEqual(len(self.journaled()), count)


# --- the read route: a cited claim checked against its reference by the consultant -------------------------------

SLUG = "vaswani-2017-attention"
NOTES = ("# Results\n\n## The cited rates\n\n"
         "Attention alone carries the sequence model {ref:arxiv:1706.03762}. "
         "The model trains in twelve hours on eight GPUs {ref:arxiv:1706.03762}.\n")


def consulted(answer, not_in_source=False, promote=False):
    from wayline.worker import Envelope

    return Envelope(structured_output={"answer": answer, "locators": [] if not_in_source else ["dossier.json:abstract"],
                                       "confidence": 0.8, "not_in_source": not_in_source, "promote_requested": promote},
                    session_id="consult-1", num_turns=2)


class ReadTest(VerificationCase):
    """A second inherited document whose result cites a reference the project holds at L0."""

    def setUp(self):
        from tests.paths import FIXTURES_DIR
        from wayline.dossier import l0_dossier, write_l0
        from wayline.fetch import recording_fetcher
        from wayline.scout import Scout, parse_reference

        super().setUp()
        (self.temp / "notes.md").write_text(NOTES, encoding="utf-8")
        self.add(self.temp / "notes.md")
        self.deconstruct("D2")
        scout = Scout(recording_fetcher(FIXTURES_DIR / "fetch", email="owner@example.org"), "owner@example.org")
        write_l0(Ledger(self.project), l0_dossier(scout.resolve(parse_reference("arXiv:1706.03762")), SLUG))
        verification.follow(self.project)
        self.cited = [item["id"] for item in self.ours("D2") if item.get("standing")]

    def read(self, *answers):
        from wayline import consult, worker

        with worker.use_fake() as fake:
            for answer in answers:
                fake.script(answer, role=consult.ROLE)
            report = verification.read(self.project)
            self.calls = list(fake.calls)
        return report

    def test_the_cited_claims_are_read_in_one_batch_per_reference_from_the_abstract(self):
        self.read(consulted("1: supports - the abstract says attention alone suffices\n2: cannot settle - the abstract gives no "
                            "training time"))
        self.assertEqual(len(self.calls), 1, "one question for every claim citing the reference")
        prompt = self.calls[0].request.prompt
        self.assertIn(SLUG, prompt)
        self.assertIn("1. Attention alone carries the sequence model", prompt)
        self.assertIn("2. The model trains in twelve hours on eight GPUs", prompt)
        self.assertIn("abstract", prompt)
        findings = [item for item in sections.read_findings(self.project) if item.get("replaces") in self.cited]
        self.assertEqual([(item["replaces"], item["evidence"]) for item in findings], [(self.cited[0], "supports")])
        self.assertIn("{ref:%s#abstract}" % SLUG, findings[0]["text"])
        result = self.result("The cited rates")
        self.assertEqual(result["standing"], "unchecked", "the claim the abstract cannot settle stays unchecked")
        self.assertEqual([(verdict["route"], verdict["ticket"], [entry["claim"] for entry in verdict["claims"]])
                          for verdict in result["verdicts"]], [("read", None, [self.cited[0]])])
        self.assertEqual(self.record()["reads"], [{"slug": SLUG, "level": 0, "claims": self.cited, "settled": [self.cited[0]]}])

    def test_a_reference_read_at_its_level_is_not_read_again_until_its_dossier_is_promoted(self):
        from wayline.dossier import read_dossier, write_l0

        self.read(consulted("1: supports - yes\n2: cannot settle - no time given"))
        self.assertEqual(self.read(), {"asked": [], "settled": []})
        promoted = read_dossier(Ledger(self.project), SLUG)
        promoted.update(level=1, relation_to_intent="The architecture.", deserves_l2_if="The schedule matters.")
        write_l0(Ledger(self.project), promoted)
        report = self.read(consulted("1: narrows - eight P100 GPUs for twelve hours on the base model"))
        self.assertEqual(report["asked"], [SLUG])
        self.assertIn("1. The model trains in twelve hours on eight GPUs", self.calls[0].request.prompt)
        self.assertNotIn("Attention alone carries", self.calls[0].request.prompt, "a settled claim is not asked again")
        self.assertEqual(self.result("The cited rates")["standing"], "verified")
        self.assertEqual(self.journaled()[-1], {"heading": "The cited rates", "standing": "verified", "route": "read", "by": "code"})

    def test_a_claim_citing_two_references_is_settled_by_the_first_read_and_not_asked_again(self):
        from wayline.dossier import read_dossier, write_l0

        copy = dict(read_dossier(Ledger(self.project), SLUG), slug="vaswani-copy")
        write_l0(Ledger(self.project), copy)
        (self.temp / "more.md").write_text("# Results\n\n## The twice cited claim\n\nAttention needs no recurrence "
                                           "{ref:arxiv:1706.03762}{ref:vaswani-copy#abstract}.\n", encoding="utf-8")
        self.add(self.temp / "more.md")
        self.deconstruct("D3")
        twice = next(item["id"] for item in self.ours("D3") if item.get("standing"))
        first = "\n".join("%d: supports - the abstract says so" % number for number in (1, 2, 3))
        report = self.read(consulted(first))
        self.assertEqual(len(self.calls), 1, "the second reference's read had nothing left to ask")
        self.assertIn(twice, report["settled"])
        self.assertEqual(len([item for item in sections.read_findings(self.project) if item.get("replaces") == twice]), 1)

    def test_an_unusable_answer_is_recorded_as_a_failed_read_and_not_asked_again_at_that_level(self):
        from wayline.worker import Envelope

        unusable = Envelope(structured_output={"answer": "yes"}, session_id="consult-1", num_turns=1)
        report = self.read(unusable, unusable)
        self.assertEqual(report, {"asked": [], "settled": []})
        (failed,) = self.record()["reads"]
        self.assertIn("no usable answer", failed["failed"])
        self.assertEqual(self.read(), {"asked": [], "settled": []})
        self.assertEqual(self.calls, [], "not launched again")

    def test_a_question_the_abstract_cannot_answer_asks_for_the_promotion(self):
        self.read(consulted("The abstract is silent on both.", not_in_source=True, promote=True))
        self.assertEqual(self.result("The cited rates")["standing"], "unchecked")
        self.assertEqual(self.record()["reads"][0]["settled"], [])


# --- the conductor: the check at acceptance, a gap reported blocked ------------------------------------------------


class AtAcceptanceTest(ConductorCase):
    """The conductor holds a verification ticket's result to its route at the worktree's acceptance."""

    def setUp(self):
        from wayline import tickets

        super().setUp()
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, verifies="Results"), body)

    def test_a_verification_with_no_route_is_sent_back_and_one_that_names_it_passes(self):
        from wayline import conductor

        self.conduct((done(), patch()), (done(verification={"route": "ported", "commit": None, "substitute": None}), None))
        acceptance = [event["payload"] for event in self.events("acceptance") if event["payload"]["where"] == "worktree"]
        checked = [[result for result in payload["results"] if result["cmd"] == conductor.VERIFICATION_CHECK][0] for payload in acceptance]
        self.assertEqual([result["exit_code"] for result in checked], [1, 0])
        self.assertIn("names no route", checked[0]["tail"])
        self.assertIn("names no route", self.calls[1].message)
        self.assertEqual(self.ticket()["status"], "done")

    def test_a_worker_blocked_on_missing_material_is_no_planners_recut_when_nothing_is_inherited(self):
        self.conduct((done(status="blocked", blocked_on="material data: data/dusk-sweep-2021.csv"), None))
        self.assertEqual(self.ticket()["status"], "blocked")
        self.assertEqual(self.payload("ticket_blocked")["path"], "material data: data/dusk-sweep-2021.csv")
