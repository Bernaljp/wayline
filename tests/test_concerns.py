"""Critiques and concerns (decision 17; ticket 96).

The seam is the ledger over a temporary project. The documents are the synthetic start-midway project of ticket 78
(`fixtures/midway/`, nothing of PINF): its manuscript with open and resolved Word comment threads, and its two
referee reports, kept through ticket 84's verb with every conversion answered from the tool runner's recordings. The
critique splitter, the critic, and the decider are scripted through the fake launcher; the conductor's part is
replayed from the journal. What is asserted is what a later reader sees: `research/concerns.json`, `CONCERNS.md`,
the journal, `DECISIONS.md`, the decision tickets, and the prompts the readers are sent.
"""

import json
import unittest

from tests.paths import HARNESS_ROOT
from tests.test_conductor import done, patch
from tests.test_documents import MIDWAY
from tests.test_inherited import InheritedCase
from tests.test_stop_rule import StopRuleCase
from wayline import concerns, worker
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger
from wayline.worker import Envelope


class ConcernsCase(InheritedCase):
    def concerns(self):
        return concerns.read_concerns(self.project)

    def concern(self, identifier):
        return next(item for item in self.concerns() if item["id"] == identifier)

    def record_file(self):
        return json.loads((self.project / "research" / "concerns.json").read_text(encoding="utf-8"))

    def rendered(self):
        return (self.project / "research" / "CONCERNS.md").read_text(encoding="utf-8")

    def journaled(self):
        return [event["payload"] for event in Ledger(self.project).read_events()[0] if event["event"] == "concern"]


class CommentThreadsTest(ConcernsCase):
    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")

    def test_an_open_word_comment_thread_becomes_a_concern_by_code_and_a_resolved_one_does_not(self):
        added = concerns.from_comments(self.project)
        self.assertEqual([item["id"] for item in added], ["K1", "K2"])
        self.assertEqual(self.concern("K1")["sources"],
                         [{"critique": "D1", "locator": "D1#p4", "text": "This contradicts the abstract. Which is right?"}])
        self.assertEqual(self.concern("K2")["sources"], [{"critique": "D1", "locator": "D1#p13", "text": "Add the funder."}])
        self.assertNotIn("2015 review", json.dumps(self.record_file()), "a resolved thread is no concern")
        self.assertEqual([(item["status"], item["place"]) for item in self.concerns()], [("open", None), ("open", None)])
        check(self.record_file(), load_schema("concern"), name="concerns.json")
        self.assertEqual([(event["id"], event["status"], event["by"]) for event in self.journaled()],
                         [("K1", "open", "code"), ("K2", "open", "code")])
        self.assertIn("## K1", self.rendered())
        self.assertIn("This contradicts the abstract. Which is right?", self.rendered())

    def test_the_threads_are_taken_once(self):
        concerns.from_comments(self.project)
        self.assertEqual(concerns.from_comments(self.project), [])
        self.assertEqual(len(self.concerns()), 2)
        self.assertEqual(len(self.journaled()), 2)

    def test_a_thread_targets_the_inherited_claim_it_is_anchored_on(self):
        self.deconstruct()
        concerns.from_comments(self.project)
        target = next(item for item in self.ours() if item.get("doc") == "D1#p4.s2")
        self.assertEqual(self.concern("K1")["targets"], [target["id"]])
        self.assertEqual(self.concern("K2")["targets"], [], "the acknowledgements hold no inherited claim")


# The splitter's answer on the two referee reports of the midway project, as a careful session gives it: the praise
# paragraph left out, point 2 split into its parts, the lamp-flicker point given once per critique (code merges
# them), and two slips code must catch: a span no critique holds, and a target that is not an inherited claim.
def splitter_answer(dusk, not_a_claim):
    def point(critique, text, targets=()):
        return {"sources": [{"critique": critique, "text": text}], "targets": list(targets)}

    return {"concerns": [
        point("D2", "The abstract says synchrony peaks at dusk, but the Results say the order parameter is lowest at dusk. "
                    "One of the two must be wrong.", [dusk]),
        point("D2", "(a) report how many moths were filmed per colony"),
        point("D2", "(b) show that the camera frame rate does not alias the wingbeat."),
        point("D2", "The phase window is not stated consistently between the Methods and the code.", [not_a_claim]),
        point("D2", "The authors should rule out lamp flicker in the enclosure as the cue that drives synchrony."),
        point("D2", "The dusk sweep of 2021 is cited with a value of R but its data are not supplied."),
        point("D3", "Please rule out lamp flicker in the enclosure as the cue that drives the synchrony."),
        point("D3", "Give the band-pass filter's order."),
        point("D3", "The authors fabricated the colonies."),
    ]}


class SplitterCase(ConcernsCase):
    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")
        self.deconstruct()
        self.add(MIDWAY / "critiques" / "referee-1.md", kind="critique")
        self.add(MIDWAY / "critiques" / "referee-2.md", kind="critique")
        self.dusk = next(item["id"] for item in self.ours() if item.get("doc") == "D1#p4.s2")
        self.not_a_claim = next(item["id"] for item in self.ours() if item.get("doc") == "D1#p2.s2")

    def split(self, answer=None):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output=answer or splitter_answer(self.dusk, self.not_a_claim), session_id="split-1",
                                 num_turns=1), role=concerns.SPLITTER)
            report = concerns.split_critiques(self.project)
            self.calls = list(fake.calls)
        return report


class SplitterTest(SplitterCase):
    def test_one_sonnet_session_at_medium_splits_the_batch_of_critiques(self):
        self.split()
        self.assertEqual(len(self.calls), 1, "one session for the batch")
        request = self.calls[0].request
        self.assertEqual((request.role, request.model, request.effort), (concerns.SPLITTER, "sonnet", "medium"))
        self.assertIn("The manuscript is a pleasure to read", request.prompt, "every critique is in the prompt whole")
        self.assertIn("Give the band-pass filter's order.", request.prompt)
        self.assertIn("%s: The order parameter is lowest at dusk across every colony." % self.dusk, request.prompt,
                      "the inherited claims are what it may target")
        for rule in ("praise", "summary", "two points", "verbatim"):
            self.assertIn(rule, request.prompt)

    def test_the_points_become_concerns_verbatim_located_and_merged_across_critiques(self):
        self.split()
        found = self.concerns()
        self.assertEqual([item["id"] for item in found], ["K%d" % number for number in range(1, 8)])
        self.assertEqual(found[0]["sources"][0]["locator"], "D2#p3")
        self.assertEqual(found[0]["targets"], [self.dusk])
        self.assertEqual([source["text"] for source in found[1]["sources"] + found[2]["sources"]],
                         ["(a) report how many moths were filmed per colony",
                          "(b) show that the camera frame rate does not alias the wingbeat."], "a two-point item is two concerns")
        flicker = found[4]
        self.assertEqual([(source["critique"], source["locator"]) for source in flicker["sources"]], [("D2", "D2#p3"), ("D3", "D3#p2")],
                         "near-identical points from two critiques are one concern with both sources")
        self.assertEqual(found[6]["sources"][0]["text"], "Give the band-pass filter's order.")
        text = json.dumps(self.record_file())
        self.assertNotIn("pleasure to read", text, "praise is left out")
        self.assertEqual(self.record_file()["split"], [{"document": "D2", "version": 1}, {"document": "D3", "version": 1}])
        self.assertEqual({event["by"] for event in self.journaled()}, {"session"})

    def test_code_drops_a_span_no_critique_holds_and_a_target_that_is_no_inherited_claim(self):
        report = self.split()
        self.assertNotIn("fabricated", json.dumps(self.record_file()))
        self.assertEqual(self.concern("K4")["targets"], [], "a passage that is no inherited claim is no target")
        dropped = "\n".join(report["dropped"])
        self.assertIn("The authors fabricated the colonies.", dropped)
        self.assertIn(self.not_a_claim, dropped)

    def test_critiques_past_the_splitters_cap_go_in_several_sessions_each_whole(self):
        long = "# Referee report 3\n\n" + "\n\n".join("%d. Report the colony count for sweep %d." % (number, number)
                                                      for number in range(1, 700)) + "\n"
        (self.temp / "referee-3.md").write_text(long, encoding="utf-8")
        self.add(self.temp / "referee-3.md", kind="critique")
        self.assertGreater(len(long), concerns.SPLIT_MIN)
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output={"concerns": []}, session_id="split-1", num_turns=1), role=concerns.SPLITTER)
            fake.script(Envelope(structured_output={"concerns": [{"sources": [{"critique": "D4", "text": "Report the colony count for "
                                                                                                    "sweep 7."}], "targets": []}]},
                                 session_id="split-2", num_turns=1), role=concerns.SPLITTER)
            policy = json.loads((HARNESS_ROOT / "policy.json").read_text(encoding="utf-8"))
            policy["context_pack"]["max_chars"]["sonnet"] = 30000
            report = concerns.split_critiques(self.project, policy=policy)
            prompts = [call.request.prompt for call in fake.calls]
        self.assertEqual(len(prompts), 2)
        self.assertIn("# D2:", prompts[0])
        self.assertNotIn("# D4:", prompts[0])
        self.assertIn("# D4:", prompts[1])
        self.assertEqual(report["added"], ["K1"])
        self.assertEqual([entry["document"] for entry in self.record_file()["split"]], ["D2", "D3", "D4"])

    def test_a_critique_is_split_once(self):
        self.split()
        with worker.use_fake() as fake:
            report = concerns.split_critiques(self.project)
            self.assertEqual(fake.calls, [])
        self.assertEqual(report["added"], [])
        self.assertEqual(len(self.concerns()), 7)

    def test_a_point_near_identical_to_a_recorded_concern_joins_it(self):
        self.split({"concerns": [{"sources": [{"critique": "D2", "text": "The authors should rule out lamp flicker in the "
                                                                          "enclosure as the cue that drives synchrony."}],
                                  "targets": []}]})
        (self.temp / "referee-3.md").write_text("# Referee report 3\n\nRule out lamp flicker in the enclosure as the cue that "
                                                 "drives the synchrony.\n", encoding="utf-8")
        self.add(self.temp / "referee-3.md", kind="critique")
        self.split({"concerns": [{"sources": [{"critique": "D4", "text": "Rule out lamp flicker in the enclosure as the cue that "
                                                                          "drives the synchrony."}], "targets": []}]})
        self.assertEqual([item["id"] for item in self.concerns()], ["K1"])
        self.assertEqual([source["critique"] for source in self.concern("K1")["sources"]], ["D2", "D4"])
        self.assertEqual([event["id"] for event in self.journaled()], ["K1", "K1"], "the join is journaled as a change to K1")


# --- setup: the critic proposes, the grill settles in groups, the batch takes marks, specify waits ---------------

INTAKE = "# Intake\n\n## Intent\n\nFind why lantern moth colonies synchronize their wingbeats at dusk.\n"
QUESTIONS = ("Is synchrony lowest or highest at dusk?", "Does colony size drive synchrony?")
# Where the critic proposes each concern of the midway project goes: K1 to K7 split from the two referee reports,
# K8 and K9 the manuscript's two open comment threads.
PROPOSALS = {
    "K1": ("objective", "O1", "the dusk contradiction is what O1 settles"),
    "K2": ("objective", "O2", "the moth counts are part of the size series"),
    "K3": ("objective", "O2", "aliasing would fake the size effect"),
    "K4": ("order", None, "a consistency fix the paper makes"),
    "K5": ("objective", "O1", "flicker is the rival cue for the dusk effect"),
    "K6": ("decline", None, "the 2021 data are lost and the claim is withdrawn"),
    "K7": ("order", None, "the filter's order is a Methods detail"),
    "K8": ("objective", "O1", "the same contradiction, raised by the coauthor"),
    "K9": ("decline", None, "an acknowledgement is no research point"),
}


def critic_memo(rows=None):
    from tests.test_position import MEMO

    value = json.loads(json.dumps(MEMO))
    value["prior_work"] = []
    value["objectives"] = [{"id": identifier, "verdict": "reachable", "reasoning": "The dusk sweeps answer it.", "revised_target": None}
                           for identifier in ("O1", "O2")]
    value["concerns"] = rows if rows is not None else [
        {"id": identifier, "place": place, "objective": objective, "reason": reason}
        for identifier, (place, objective, reason) in PROPOSALS.items()]
    # The midway project inherits one result; ticket 97's table says it needs only what the project holds.
    value["material"] = [{"result": "Results", "needs": [{"kind": "code", "item": "phaselock.py", "state": "present",
                                                          "licensed": False, "rebuild": True}]}]
    return value


class SetupCase(SplitterCase):
    def setUp(self):
        super().setUp()
        from tests.projects import open_objective
        from wayline import project

        self.split()
        concerns.from_comments(self.project)
        Ledger(self.project).write_markdown("INTAKE.md", INTAKE)
        harness = project.read_harness(self.project)
        harness["radius"] = "exploratory"  # the critic's fixture memo ends on an exploratory direction
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        for question in QUESTIONS:
            open_objective(self.project, question)

    def position(self, *memos):
        from wayline import position

        with worker.use_fake() as fake:
            for value in memos or (critic_memo(),):
                fake.script(Envelope(structured_output=value, session_id="critic-1", num_turns=3), role=position.CRITIC)
            report = position.position(self.project, notify=lambda *args: None)
            self.critic_calls = [call for call in fake.calls if call.request.role == position.CRITIC]
        return report

    def records(self):
        from wayline import grill

        return grill.read_records(self.project)

    def first_tier(self):
        """The grill's first tier settled: each objective taken open, as the owner says; the concerns' questions come after."""
        from wayline import grill

        grill.grill_view(self.project)
        for record in self.records():
            if record.get("objective") and record.get("answer") is None:
                grill.answer(self.project, record["id"], "open", "the owner takes it")
        grill.grill_view(self.project)

    def concern_questions(self):
        self.first_tier()
        return [record for record in self.records() if record.get("concerns")]


class CriticTest(SetupCase):
    def test_the_critic_reads_the_documents_index_and_every_concern_with_its_tools_reaching_the_documents(self):
        self.position()
        request = self.critic_calls[0].request
        self.assertIn("research/DOCUMENTS.md", request.prompt)
        self.assertIn("Referee report 1", request.prompt)
        self.assertIn("research/CONCERNS.md", request.prompt)
        self.assertIn("Give the band-pass filter's order.", request.prompt)
        self.assertIn("This contradicts the abstract. Which is right?", request.prompt)
        documents = "//%s/**" % str((self.project / "research" / "documents").resolve()).strip("/")
        self.assertIn("Read(%s)" % documents, request.allowed_tools)
        self.assertIn("Grep(%s)" % documents, request.allowed_tools)

    def test_the_memo_proposes_a_place_for_each_concern_and_the_placements_form_one_batch(self):
        report = self.position()
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(self.concern("K1")["proposed"], {"place": "objective", "objective": "O1",
                                                          "reason": "the dusk contradiction is what O1 settles"})
        self.assertEqual(self.concern("K6")["proposed"]["place"], "decline")
        self.assertEqual([item["place"] for item in self.concerns()], [None] * 9, "a proposal sorts nothing")
        self.assertEqual({event["by"] for event in self.journaled()[-9:]}, {"critic"})
        from wayline import batches

        (batch,) = batches.read_batches(self.project)
        self.assertEqual((batch["kind"], batch["status"]), ("concern_placements", "open"))
        self.assertEqual([item["ref"] for item in batch["items"]], ["K%d" % number for number in range(1, 10)])
        self.assertEqual({item["default"] for item in batch["items"]}, {"take it"})
        self.assertIn("the critic proposes O1", self.rendered())

    def test_a_memo_that_leaves_a_concern_without_a_place_is_returned_once(self):
        short = critic_memo([row for row in critic_memo()["concerns"] if row["id"] != "K4"])
        report = self.position(short, critic_memo())
        self.assertIsNone(report["stopped"], report)
        self.assertEqual(len(self.critic_calls), 2)
        self.assertIn("the concern K4 has no row in concerns", self.critic_calls[1].message)

    def test_a_proposal_names_an_objective_row(self):
        from wayline import objectives, position

        rows = critic_memo()["concerns"]
        rows[0] = {"id": "K1", "place": "objective", "objective": "O7", "reason": "no such row"}
        rows[1] = {"id": "K2", "place": "order", "objective": "O1", "reason": "the order names no objective"}
        failures = position.check_memo(critic_memo(rows), "exploratory", objectives.read_objectives(self.project),
                                       concerns=self.concerns())
        self.assertIn("the concern K1 is proposed for O7, which is no objective row of the memo", failures)
        self.assertIn("the concern K2 is proposed for the order and names O1; only a tie names an objective", failures)


class GrillGroupsTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.position()

    def answer(self, identifier, text, rationale="as the owner said"):
        from wayline import grill

        return grill.answer(self.project, identifier, text, rationale)

    def group(self, place, objective=None):
        return next(record for record in self.concern_questions()
                    if record["concerns"]["place"] == place and record["concerns"].get("objective") == objective)

    def test_one_question_per_proposed_objective_one_for_the_order_and_one_for_the_declines(self):
        groups = [(record["concerns"]["place"], record["concerns"]["objective"], record["concerns"]["ids"])
                  for record in self.concern_questions()]
        self.assertEqual(groups, [("objectives", "O1", ["K1", "K5", "K8"]), ("objectives", "O2", ["K2", "K3"]),
                                  ("order", None, ["K4", "K7"]), ("declined", None, ["K6", "K9"])])
        for record in self.concern_questions():
            self.assertTrue(record["human_only"], "setup asks the owner")
            self.assertEqual(record["options"], ["take it", "another place"])
        o1 = self.group("objectives", "O1")
        self.assertIn("Give the band-pass filter's order.", json.dumps(self.group("order")))
        self.assertIn("K1", o1["question"])

    def test_take_it_places_the_group_as_proposed_and_marks_its_batch_items(self):
        from wayline import batches

        self.answer(self.group("objectives", "O1")["id"], "take it")
        self.assertEqual([(self.concern(name)["place"], self.concern(name)["objectives"], self.concern(name)["sorted_by"])
                          for name in ("K1", "K5", "K8")], [("objectives", ["O1"], "owner")] * 3)
        self.answer(self.group("declined")["id"], "take it")
        self.assertEqual((self.concern("K6")["status"], self.concern("K6")["reason"]),
                         ("declined", "the 2021 data are lost and the claim is withdrawn"))
        marked = {item["ref"]: (item["mark"], item["by"]) for item in batches.read_batches(self.project)[0]["items"]}
        self.assertEqual(marked["K1"], ("take it", "owner"))
        self.assertEqual(marked["K2"], (None, None))
        self.assertEqual(self.journaled()[-1]["by"], "owner")

    def test_another_place_takes_the_place_the_rationale_names_or_leaves_them_to_be_sorted(self):
        self.answer(self.group("order")["id"], "another place", "tie them to O2: the size series answers both")
        self.assertEqual([self.concern(name)["objectives"] for name in ("K4", "K7")], [["O2"], ["O2"]])
        self.answer(self.group("objectives", "O2")["id"], "another place", "not those")
        self.assertEqual([self.concern(name)["place"] for name in ("K2", "K3")], [None, None])

    def test_a_mark_in_the_marks_view_places_a_concern_too(self):
        from wayline import batches

        batch = batches.read_batches(self.project)[0]
        batches.mark(self.project, batch["id"], 2, "take it")
        batches.mark(self.project, batch["id"], 4, "another place", note="decline: the code was fixed before submission")
        concerns.take_marks(self.project)
        self.assertEqual(self.concern("K2")["objectives"], ["O2"])
        self.assertEqual((self.concern("K4")["status"], self.concern("K4")["reason"]),
                         ("declined", "the code was fixed before submission"))

    def test_specify_refuses_to_draft_while_a_concern_is_unsorted(self):
        from wayline import specify

        with self.assertRaises(specify.SpecifyError) as refused:
            specify.draft_spec(self.project)
        self.assertIn("K1", str(refused.exception))
        self.assertIn("wayline concern place", str(refused.exception))


class FollowTest(SetupCase):
    """Code answers a concern, follows a reframe, and sends it back to be sorted when its objective drops."""

    def setUp(self):
        super().setUp()
        self.position()
        concerns.place(self.project, ["K1"], ("objectives", ["O1"]), "owner")
        concerns.place(self.project, ["K2"], ("objectives", ["O1", "O2"]), "owner")

    def answer_objective(self, identifier):
        from wayline import objectives

        objectives.change_objective(self.project, identifier, "answered", "owner", answer="%s is answered" % identifier)

    def replace_the_dusk_claim(self):
        from wayline import sections

        sections.file_finding(self.project, {"id": "t4-a1-f1", "ticket": 4, "text": "R is lowest at dusk in 38 of 40 colonies.",
                                             "provenance": ["results/dusk.json#min_r"], "negative": False, "heading": "Results",
                                             "replaces": self.dusk, "evidence": "narrows", "objectives": ["O1"]})

    def test_a_concern_is_answered_once_its_objectives_are_answered_and_its_targets_replaced(self):
        self.answer_objective("O1")
        concerns.follow(self.project)
        self.assertEqual(self.concern("K1")["status"], "open", "its target still stands unchecked")
        self.replace_the_dusk_claim()
        concerns.follow(self.project)
        answered = self.concern("K1")
        self.assertEqual(answered["status"], "answered")
        self.assertIn("O1: O1 is answered", answered["answer"])
        self.assertIn(self.dusk, answered["answer"])
        self.assertEqual(self.concern("K2")["status"], "open", "O2 is still open")
        self.assertEqual(self.journaled()[-1], {"id": "K1", "status": "answered", "place": "objectives", "objectives": ["O1"],
                                                "by": "code"})
        self.assertEqual(concerns.follow(self.project), [], "following again changes nothing")

    def test_a_concern_follows_a_reframe_to_the_successor(self):
        from wayline import objectives

        successor, _ = objectives.add_objective(self.project, "Is synchrony lowest at dusk in every colony size?")
        objectives.change_objective(self.project, "O1", "reframed", "owner", answer="narrowed", reframed_as=successor["id"])
        concerns.follow(self.project)
        self.assertEqual(self.concern("K1")["objectives"], [successor["id"]])
        self.assertEqual(self.concern("K2")["objectives"], [successor["id"], "O2"])

    def test_a_concern_goes_back_to_be_sorted_when_its_objective_drops(self):
        from wayline import objectives

        objectives.change_objective(self.project, "O1", "dropped", "owner", answer="out of scope")
        concerns.follow(self.project)
        back = self.concern("K1")
        self.assertEqual((back["place"], back["objectives"], back["status"]), (None, [], "open"))
        self.assertIn("O1 was dropped", back["returned"])
        self.assertEqual(self.concern("K2")["objectives"], ["O2"], "a concern still tied to an open objective stays")
        self.assertIn("K1", [item["id"] for item in concerns.unsorted(self.project)])


class AfterSetupCase(SetupCase):
    """Past setup: each concern that needs sorting is a decision ticket, which the code step reads back from the journal."""

    def setUp(self):
        super().setUp()
        self.position()
        self.notified = []
        for record in self.concern_questions():
            if record["concerns"]["place"] != "objectives" or record["concerns"]["objective"] != "O2":
                from wayline import grill

                grill.answer(self.project, record["id"], "take it", "as proposed")
        Ledger(self.project).append_event("phase", {"from": "P4", "to": "P5"})

    def notify(self, event, text, project=None, ticket=None):
        self.notified.append((event, text, ticket))

    def settle(self):
        return concerns.settle(self.project, notify=self.notify)

    def concern_tickets(self):
        from wayline import tickets

        return [fields for fields in tickets.read_tickets(self.project) if concerns.concern_of(fields.get("origin"))]

    def autonomy(self, level, human_only=()):
        from wayline import project

        harness = project.read_harness(self.project)
        harness["autonomy"] = level
        harness["human_only"] = list(harness["human_only"]) + list(human_only)
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")


class AfterSetupTicketTest(AfterSetupCase):
    def test_an_unsorted_concern_opens_one_decision_ticket_of_class_concern_once(self):
        report = self.settle()
        opened = self.concern_tickets()
        self.assertEqual([concerns.concern_of(fields["origin"]) for fields in opened], ["K2", "K3"])
        self.assertEqual(report["opened"], [fields["id"] for fields in opened])
        from wayline import decisions, tickets

        fields = opened[0]
        record = decisions.decision_record(tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1])
        self.assertIn("K2", record["question"])
        self.assertIn("tie it to O2", record["options"])
        self.assertIn("for the order", record["options"])
        self.assertEqual(record["recommended"], "tie it to O2", "the critic's proposal")
        self.assertIsNone(record["blocking"], "sorting a concern pauses no work")
        self.assertFalse(fields["human_only"])
        self.assertEqual(self.settle()["opened"], [], "asked once")
        self.assertEqual(len(self.concern_tickets()), 2)

    def test_before_setup_ends_no_ticket_is_opened(self):
        events = [event for event in Ledger(self.project).read_events()[0] if event["event"] != "phase" or event["payload"]["to"] != "P5"]
        (self.project / "research" / "journal.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        self.assertEqual(self.settle()["opened"], [])

    def test_the_owners_answer_sorts_the_concern(self):
        from wayline import project

        self.settle()
        first, second = self.concern_tickets()
        project.answer(self.project, first["id"], "for the order")
        project.answer(self.project, second["id"], "decline", rationale="the camera ran at 1 kHz, far above the wingbeat")
        self.settle()
        self.assertEqual((self.concern("K2")["place"], self.concern("K2")["sorted_by"]), ("order", "owner"))
        self.assertEqual((self.concern("K3")["status"], self.concern("K3")["reason"]),
                         ("declined", "the camera ran at 1 kHz, far above the wingbeat"))
        self.assertEqual(self.settle()["opened"], [])

    def test_an_answer_that_names_no_place_asks_again_with_why(self):
        from wayline import decisions, project, tickets

        self.settle()
        first = self.concern_tickets()[0]
        project.answer(self.project, first["id"], "hmm, not sure")
        report = self.settle()
        again = [fields for fields in self.concern_tickets() if concerns.concern_of(fields["origin"]) == "K2"]
        self.assertEqual(len(again), 2)
        self.assertEqual(report["opened"], [again[1]["id"]])
        record = decisions.decision_record(tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(again[1]))[1])
        self.assertTrue(any("hmm, not sure" in item for item in record["evidence"]))

    def test_a_concern_whose_objective_drops_is_asked_about_again(self):
        from wayline import objectives, project

        self.settle()
        for fields in self.concern_tickets():
            project.answer(self.project, fields["id"], "tie it to O2")
        self.settle()
        objectives.change_objective(self.project, "O2", "dropped", "owner", answer="the size series is out of scope")
        report = self.settle()
        back = [concerns.concern_of(fields["origin"]) for fields in self.concern_tickets() if fields["id"] in report["opened"]]
        self.assertEqual(back, ["K2", "K3"])
        self.assertIn("O2 was dropped", json.dumps([fields for fields in self.concern_tickets()]) + self.rendered())
        self.assertEqual(self.concern("K2")["place"], None, "the earlier answer is not taken again")

    def test_named_human_only_the_ticket_is_the_owners(self):
        self.autonomy("autonomous", human_only=["concern"])
        self.settle()
        self.assertTrue(all(fields["human_only"] for fields in self.concern_tickets()))


class DeciderTest(AfterSetupCase):
    def decide(self, answer, rationale="the size series answers it"):
        from tests.test_decider import envelope
        from wayline import decider, decisions, tickets

        fields = self.concern_tickets()[0]
        body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))[1]
        with worker.use_fake() as fake:
            fake.script(envelope(answer, rationale=rationale), role=decider.DECIDER)
            return decider.decide_ticket(self.project, fields, body, decisions.decision_record(body), notify=self.notify)

    def test_under_autonomous_the_decider_sorts_it(self):
        self.autonomy("autonomous")
        self.settle()
        outcome = self.decide("tie it to O2")
        self.assertEqual(outcome.status, "decided")
        self.settle()
        self.assertEqual((self.concern("K2")["objectives"], self.concern("K2")["sorted_by"]), (["O2"], "decider"))
        self.assertEqual(self.journaled()[-1]["by"], "decider")

    def test_a_decline_needs_its_reason_and_takes_the_rationale(self):
        self.autonomy("autonomous")
        self.settle()
        self.decide("decline", rationale="counting moths per colony is already in the Methods")
        self.settle()
        self.assertEqual(self.concern("K2")["reason"], "counting moths per colony is already in the Methods")

    def test_a_new_objective_is_refused_while_objective_is_human_only(self):
        from wayline import objectives

        self.autonomy("autonomous")
        self.settle()
        before = objectives.read_objectives(self.project)
        outcome = self.decide("new objective: How many moths does a colony need to synchronize?")
        self.assertEqual(outcome.status, "refused")
        self.assertIn("objective", outcome.why)
        self.assertTrue(self.concern_tickets()[0]["human_only"], "turned over to the owner")
        self.assertEqual(objectives.read_objectives(self.project), before)

    def test_handed_objective_the_decider_may_add_one(self):
        from wayline import objectives, project

        self.autonomy("autonomous")
        harness = project.read_harness(self.project)
        harness["human_only"] = ["data"]
        (self.project / project.HARNESS_JSON).write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        self.settle()
        outcome = self.decide("new objective: How many moths does a colony need to synchronize?")
        self.assertEqual(outcome.status, "decided")
        self.settle()
        added = objectives.read_objectives(self.project)[-1]
        self.assertEqual(added["text"], "How many moths does a colony need to synchronize?")
        self.assertEqual(self.concern("K2")["objectives"], [added["id"]])

    def test_an_answer_naming_no_place_is_refused_and_turned_over(self):
        self.autonomy("autonomous")
        self.settle()
        outcome = self.decide("it depends")
        self.assertEqual(outcome.status, "refused")
        self.assertIn("names no place", outcome.why)


class ConductorStepTest(StopRuleCase):
    """The conductor's wave takes the concerns' step: the one-ticket fixture with one unsorted concern, past setup."""

    def setUp(self):
        super().setUp()
        from tests.projects import open_objective

        open_objective(self.project, "Does the hello file say hello?")
        self.set_harness(stop_when="frontier")
        concerns.from_objection(self.project, {"index": 1, "text": "One run gives no variance."}, "accept", "fair")
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})

    def concern_tickets(self):
        from wayline import tickets

        return [fields for fields in tickets.read_tickets(self.project) if concerns.concern_of(fields.get("origin"))]

    def test_under_autonomous_the_decider_sorts_it_within_the_run(self):
        from wayline import decider

        self.set_harness(autonomy="autonomous")
        self.conduct(decider_answers=["tie it to O1"])
        (fields,) = self.concern_tickets()
        self.assertEqual([call.request.role for call in self.calls].count(decider.DECIDER), 1, self.said())
        self.assertEqual(concerns.read_concerns(self.project)[0]["objectives"], ["O1"])
        self.assertEqual(concerns.read_concerns(self.project)[0]["sorted_by"], "decider")
        self.assertIn("concern K1 placed by the decider's answer to ticket %d" % fields["id"], self.said())

    def test_a_workers_prompt_carries_the_concerns_of_the_objectives_its_ticket_serves(self):
        concerns.place(self.project, ["K1"], ("objectives", ["O1"]), "owner")
        self.serve("O1")
        self.conduct((done(), patch()), waves=1)
        (worker_call,) = [call for call in self.calls if call.request.role == "coder"]
        self.assertIn("# The concerns of this ticket's objectives", worker_call.request.prompt)
        self.assertIn("One run gives no variance.", worker_call.request.prompt)

    def test_under_interactive_and_checkpoints_it_waits_for_the_owner_and_the_next_run_takes_the_answer(self):
        from wayline import decider, project

        for autonomy in ("interactive", "checkpoints"):
            with self.subTest(autonomy=autonomy):
                self.setUp()
                self.set_harness(autonomy=autonomy)
                self.conduct((done(), patch()))
                (fields,) = self.concern_tickets()
                self.assertNotIn(decider.DECIDER, [call.request.role for call in self.calls])
                self.assertIsNone(concerns.read_concerns(self.project)[0]["place"])
                project.answer(self.project, fields["id"], "for the order")
                self.conduct(waves=2)
                self.assertEqual(concerns.read_concerns(self.project)[0]["place"], "order")
                self.assertEqual(len(self.concern_tickets()), 1, "asked once")

    def test_the_decider_is_told_how_to_answer_a_concerns_ticket(self):
        from wayline import decider

        self.set_harness(autonomy="autonomous")
        self.conduct(decider_answers=["tie it to O1"])
        (call,) = [call for call in self.calls if call.request.role == decider.DECIDER]
        self.assertIn("A `concern` decision", call.request.prompt)
        self.assertIn("## research/CONCERNS.md", call.request.prompt)


class ReadersTest(SetupCase):
    """Who reads what: specify, the decider, and the planner the index and the concerns; a worker its objectives' concerns."""

    def setUp(self):
        super().setUp()
        self.position()
        concerns.place(self.project, ["K1"], ("objectives", ["O1"]), "owner")
        concerns.place(self.project, ["K2"], ("objectives", ["O2"]), "owner")
        concerns.place(self.project, ["K7"], ("order", None), "owner")

    def test_specify_and_the_decider_read_the_documents_index_and_the_concerns(self):
        from wayline import decider

        text, _ = decider.records_text(self.project)
        self.assertIn("## research/DOCUMENTS.md", text)
        self.assertIn("Referee report 1", text)
        self.assertIn("## research/CONCERNS.md", text)
        self.assertIn("Give the band-pass filter's order.", text)

    def test_the_planner_reads_them(self):
        from wayline import plan

        text, _ = plan._records(self.project, None)
        self.assertIn("## research/DOCUMENTS.md", text)
        self.assertIn("## research/CONCERNS.md", text)

    def test_a_project_with_no_documents_reads_neither(self):
        from wayline import decider
        from wayline.project import init_project

        bare = self.temp / "bare"
        init_project(bare, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        text, _ = decider.records_text(bare)
        self.assertNotIn("CONCERNS.md", text)

    def test_a_workers_pack_carries_the_open_concerns_of_its_tickets_objectives(self):
        pack = concerns.pack_text(self.project, ["O1"])
        self.assertIn("## K1, tied to O1", pack)
        self.assertIn("One of the two must be wrong.", pack)
        self.assertIn("targets the inherited claims %s" % self.dusk, pack)
        self.assertNotIn("K2", pack, "a concern of another objective")
        self.assertNotIn("K7", pack, "a concern for the order")
        self.assertEqual(concerns.pack_text(self.project, []), "")

    def test_the_setup_reference_reads_them(self):
        skill = (HARNESS_ROOT / "skills" / "wayline" / "setup.md").read_text(encoding="utf-8")
        self.assertIn("research/DOCUMENTS.md", skill)
        self.assertIn("research/CONCERNS.md", skill)


class VerbTest(SplitterCase):
    """`wayline concern`: the session's verb at setup, splitting the critiques and placing what the groups left."""

    def run_verb(self, *args):
        from tests.test_documents import run_verb

        return run_verb("concern", *args, "--project", str(self.project))

    def test_split_takes_the_comment_threads_and_the_critiques(self):
        with worker.use_fake() as fake:
            fake.script(Envelope(structured_output=splitter_answer(self.dusk, self.not_a_claim), session_id="split-1", num_turns=1),
                        role=concerns.SPLITTER)
            code, out, err = self.run_verb("split")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.concerns()), 9, "two comment threads and seven points")
        self.assertIn("split D2, D3", out)
        self.assertIn("dropped", out)

    def test_place_ties_orders_or_declines_by_the_owner(self):
        self.split()
        self.assertEqual(self.run_verb("place", "K1", "K2", "--order")[0], 0)
        code, _, err = self.run_verb("place", "K3", "--decline", "the frame rate is in the Methods")
        self.assertEqual(code, 0, err)
        self.assertEqual([self.concern(name)["place"] for name in ("K1", "K2", "K3")], ["order", "order", "declined"])
        self.assertEqual(self.concern("K3")["sorted_by"], "owner")
        code, _, err = self.run_verb("place", "K4", "--objective", "O9")
        self.assertEqual(code, 2)
        self.assertIn("O9 is no objective the project holds", err)
        code, _, err = self.run_verb("place", "K4")
        self.assertEqual(code, 2, "a place is named")

    def test_show_prints_the_concerns(self):
        self.split()
        code, out, _ = self.run_verb("show")
        self.assertEqual(code, 0)
        self.assertIn("K1", out)
        self.assertIn("not sorted yet", out)


class ParsePlaceTest(unittest.TestCase):
    """How an answer, a rationale, or a note names a place: said first, never picked out of a sentence that excludes it."""

    def test_the_places(self):
        cases = {
            "tie it to O2": ("objectives", ["O2"]), "O1 and O3": ("objectives", ["O1", "O3"]),
            "accept: tie it to O1": ("objectives", ["O1"]), "for the order": ("order", None),
            "accept: for the order": ("order", None), "keep it for the paper order": ("order", None),
            "decline: the data are lost": ("declined", "the data are lost"), "decline": ("declined", None),
            "decline: <the reason>": ("declined", None), "new objective: Does flicker drive it?": ("new", "Does flicker drive it?"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(concerns.parse_place(text), expected)

    def test_no_place_is_read_out_of_a_sentence_that_names_none_first(self):
        for text in ("Not O2; keep it for the paper order", "These do not belong with O3",
                     "out of scope, wrong order of priorities", "accept", "hmm", "new objective: <the question>"):
            with self.subTest(text=text):
                self.assertIsNone(concerns.parse_place(text))


class ReviewFixesTest(SetupCase):
    """What the review of ticket 96 found: answers recorded whole, every unsorted concern asked about, nothing orphaned."""

    def setUp(self):
        super().setUp()
        self.position()

    def test_a_grill_batch_whose_concern_answer_is_refused_records_nothing(self):
        from wayline import grill

        self.first_tier()
        group = next(record for record in self.records() if (record.get("concerns") or {}).get("place") == "order")
        before = (self.records(), self.concerns())
        with self.assertRaises(grill.GrillError):
            grill.apply_batch(self.project, {"answers": [{"id": group["id"], "answer": "another place",
                                                           "rationale": "tie them to O9"}]})
        self.assertEqual((self.records(), self.concerns()), before)

    def test_a_concern_a_group_left_unplaced_is_asked_about_alone_and_its_answer_places_it(self):
        from wayline import grill

        self.first_tier()
        group = next(record for record in self.records() if (record.get("concerns") or {}).get("place") == "order")
        grill.answer(self.project, group["id"], "another place", "not for the order")
        grill.grill_view(self.project)
        alone = [record for record in self.records() if record.get("concerns") and record["concerns"]["place"] is None]
        self.assertEqual([record["concerns"]["ids"] for record in alone], [["K4"], ["K7"]])
        self.assertTrue(all(record["human_only"] for record in alone))
        with self.assertRaises(grill.GrillError):
            grill.answer(self.project, alone[0]["id"], "no idea", "the owner is unsure")
        grill.answer(self.project, alone[0]["id"], "decline", "the code was fixed before submission")
        self.assertEqual((self.concern("K4")["status"], self.concern("K4")["reason"]),
                         ("declined", "the code was fixed before submission"))

    def test_an_objection_accepted_with_no_place_is_asked_about_alone(self):
        from wayline import grill

        self.first_tier()
        objection = next(record for record in self.records() if record.get("objection"))
        grill.answer(self.project, objection["id"], "accept", "a fair point")
        grill.grill_view(self.project)
        self.assertTrue(any(record.get("concerns") and record["concerns"]["ids"] == ["K10"] for record in self.records()))

    def test_after_setup_specify_does_not_wait_on_a_concern_its_ticket_asks_about(self):
        from wayline import specify

        Ledger(self.project).append_event("phase", {"from": "P4", "to": "P5"})
        with worker.use_fake():
            with self.assertRaises(Exception) as raised:
                specify.draft_spec(self.project)
        self.assertNotIn("wait to be sorted", str(raised.exception))

    def test_a_new_objective_for_a_concern_that_cannot_take_it_is_not_recorded(self):
        from wayline import objectives

        before = objectives.read_objectives(self.project)
        with self.assertRaises(concerns.ConcernError):
            concerns.place(self.project, ["K99"], ("new", "Does flicker drive it?"), "owner")
        concerns.place(self.project, ["K1"], ("objectives", ["O1"]), "owner")
        self.assertEqual(concerns.place(self.project, ["K1"], ("new", "Does flicker drive it?"), "owner", only_unsorted=True), [])
        self.assertEqual(objectives.read_objectives(self.project), before)

    def test_a_workers_pack_keeps_to_what_the_cap_leaves_it(self):
        concerns.place(self.project, ["K1", "K5", "K8"], ("objectives", ["O1"]), "owner")
        pack = concerns.pack_text(self.project, ["O1"], max_chars=200)
        self.assertLessEqual(len(pack.split("\n\n[wayline")[0]), 200)
        self.assertIn("reached the context cap", pack)

    def test_a_concern_tied_to_an_objective_the_record_no_longer_holds_does_not_stop_the_step(self):
        concerns.place(self.project, ["K1"], ("objectives", ["O2"]), "owner")
        path = self.project / "research" / "objectives.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["objectives"] = [objective for objective in record["objectives"] if objective["id"] != "O2"]
        path.write_text(json.dumps(record), encoding="utf-8")
        concerns.follow(self.project)
        self.assertEqual(self.concern("K1")["objectives"], ["O2"])


class ClosedTicketTest(AfterSetupCase):
    def test_a_ticket_closed_with_no_answer_asks_again(self):
        from wayline import tickets

        self.settle()
        first = self.concern_tickets()[0]
        fields, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(first))
        tickets.write_ticket(Ledger(self.project), dict(fields, status="parked"), body)  # a cancel parks it
        report = self.settle()
        again = [fields for fields in self.concern_tickets() if concerns.concern_of(fields["origin"]) == "K2"]
        self.assertEqual(len(again), 2)
        self.assertEqual(report["opened"], [again[1]["id"]])
        self.assertEqual(self.settle()["opened"], [], "asked once more, not every wave")


class ObjectionTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.position()

    def objections(self):
        self.first_tier()
        return [record for record in self.records() if record.get("objection")]

    def test_the_objections_wait_for_the_first_tier(self):
        from wayline import grill

        grill.grill_view(self.project)
        self.assertEqual([record for record in self.records() if record.get("objection") or record.get("concerns")], [])
        self.assertTrue(self.objections())

    def test_one_question_per_objection_of_the_hostile_review(self):
        from tests.test_position import MEMO

        asked = self.objections()
        self.assertEqual([record["objection"]["text"] for record in asked], MEMO["hostile_review"])
        self.assertTrue(all(record["human_only"] for record in asked))
        self.assertIn("accept: tie it to O1", asked[0]["options"])
        self.assertIn("reject", asked[0]["options"])

    def test_an_accepted_objection_becomes_a_concern_with_the_memo_as_its_source_and_a_rejected_one_does_not(self):
        from tests.test_position import MEMO
        from wayline import grill

        first, second = self.objections()[:2]
        grill.answer(self.project, first["id"], "accept: tie it to O1", "the planted interaction is a fair point")
        grill.answer(self.project, second["id"], "reject", "the baseline is the one asked for")
        added = self.concerns()[-1]
        self.assertEqual(added["id"], "K10")
        self.assertEqual(added["sources"], [{"critique": "POSITION.md", "locator": "POSITION.md#hostile-review-1",
                                             "text": MEMO["hostile_review"][0]}])
        self.assertEqual((added["place"], added["objectives"], added["sorted_by"]), ("objectives", ["O1"], "owner"))
        self.assertEqual(len(self.concerns()), 10, "a rejected objection is no concern")
