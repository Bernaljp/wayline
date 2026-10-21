"""The dashboard's marks view (Implementation Decision 17; ticket 112), over HTTP against a fixture ledger.

The seam is the server: `marks`, the JSON the view reads, and the `mark` action, which saves one mark, one note, or
"take all defaults" through the function the conversation's `wayline mark` verb calls. The project is one drawn as a
run draws it (`test_dashboard_views.DrawnProjectCase`), whose accepted drawing opened a real `plots` batch, with one
batch of every other kind opened as its producer opens it: objective changes on journaled proposals, the software ask,
the account's review, merges and contradictions on two passages each, concern placements, and the outline's proposals.
"""

import http.client
import io
import json
from contextlib import redirect_stdout

from tests.test_dashboard_views import Answer, DrawnProjectCase
from wayline import batches, objective_changes, sections
from wayline.dashboard import ACTIONS, TOKEN_HEADER

TOKEN = "a-token-the-marks-view-acts-with"


class MarksServedCase(DrawnProjectCase):
    """A drawn project holding one open batch of each kind, served with a token."""

    def serve(self):
        super().serve(token=TOKEN)

    def setUp(self):
        super().setUp()
        [self.plots] = batches.read_batches(self.project)  # the accepted drawing's
        [proposal] = objective_changes.take_result(self.project, 3, 1, [{
            "kind": "park", "objective": "O1", "reason": "the sweep shows the products add nothing past 0.70",
            "evidence": ["res:t3-a1/results/sweep.json#auroc"], "feasibility": {"verdict": "reachable", "reasoning": "the sweep measures it"}}])
        objective_changes.take_judgments(self.project, [proposal], [{"proposal": 1, "upheld": True, "why": "the sweep bears it out"}])
        self.changes = batches.open_batch(self.project, "objective_changes", "Objective changes",
                                          [{"ref": proposal["id"], "text": "park O1: the sweep shows the products add nothing"}], decision=7)
        self.software = batches.open_batch(self.project, "software_ask", "Install samtools?",
                                           [{"ref": "software:samtools", "text": "Ticket 4 needs samtools.", "default": "approve"}], decision=8)
        self.review = batches.open_batch(self.project, "account_review", "Decided for you: let them stand or reverse them",
                                         [{"ref": "D1", "text": "D1: the decider held out split 3", "default": "stand"},
                                          {"ref": "D2", "text": "D2: the decider kept the smaller model", "default": "stand"}])
        first, second, third, fourth = (sections.add_passage(self.project, "results", "Results", text, by="owner")["id"] for text in (
            "Moths swarm at dusk.", "At dusk the moths gather in swarms.", "Activity is lowest at dusk.", "Activity peaks at dusk."))
        self.pairs = (first, second, third, fourth)
        self.merges = batches.open_batch(self.project, "merges", "Merged at setup: right, or split them again",
                                         [{"ref": "%s+%s" % (first, second), "text": "merged, keeping the first", "default": "right"}])
        self.contradictions = batches.open_batch(self.project, "contradictions", "Contradictions in the inherited writing",
                                                 [{"ref": "%s+%s" % (third, fourth), "text": "lowest against peaks", "default": "real"}])
        self.placements = batches.open_batch(self.project, "concern_placements", "Where each concern goes",
                                             [{"ref": "K1", "text": "K1: the controls were not blinded; tie it to O1", "default": "take it"}])
        self.outline = batches.open_batch(self.project, "outline_proposals", "Results whose headings sit close: merge them?",
                                          [{"ref": "R1+R2", "text": "Merge R2 into R1", "default": "decline"}])

    def marks(self):
        answer = self.api("/marks")
        self.assertEqual(answer.status, 200, answer.body)
        return answer.json

    def batch(self, identifier, view=None):
        view = view or self.marks()
        return next(batch for batch in view["batches"] + view["settled"] if batch["id"] == identifier)

    def act(self, body, token=TOKEN):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers[TOKEN_HEADER] = token
        try:
            connection.request("POST", "/api/projects/%s/actions/mark" % self.project_id, body=json.dumps(body).encode("utf-8"),
                               headers=headers)
            return Answer(connection.getresponse())
        finally:
            connection.close()

    def on_disk(self, identifier):
        return batches.read_batch(self.project, identifier)

    def marked(self):
        return [event["payload"] for event in self.ledger.read_events()[0] if event["event"] == "marked"]


class MarksViewTest(MarksServedCase):
    def test_it_lists_every_open_batch_with_its_unsettled_count(self):
        view = self.marks()
        self.assertEqual([(batch["id"], batch["kind"], batch["open"]) for batch in view["batches"]], [
            (self.plots["id"], "plots", 2), (self.changes["id"], "objective_changes", 1), (self.software["id"], "software_ask", 1),
            (self.review["id"], "account_review", 2), (self.merges["id"], "merges", 1), (self.contradictions["id"], "contradictions", 1),
            (self.placements["id"], "concern_placements", 1), (self.outline["id"], "outline_proposals", 1)])
        self.assertEqual(view["settled"], [])
        review = self.batch(self.review["id"], view)
        self.assertEqual((review["title"], review["decision"], review["marks"]),
                         ("Decided for you: let them stand or reverse them", None, ["stand", "reverse"]))
        item = review["items"][0]
        self.assertEqual((item["id"], item["ref"], item["text"], item["default"], item["mark"], item["changeable"]),
                         (1, "D1", "D1: the decider held out split 3", "stand", None, False))

    def test_a_plot_shows_its_svg_from_the_drawings_artifacts_with_its_three_explanations(self):
        plot, table = self.batch(self.plots["id"])["items"]
        self.assertEqual(plot["ref"], "R1.1")
        shown = plot["plot"]
        self.assertEqual((shown["kind"], shown["svg"]), ("plot", "drawings/R1-1/auroc_box.svg"))
        self.assertTrue((self.project / shown["svg"]).is_file(), "the drawing's own SVG, not a re-render")
        self.assertEqual(shown["caption"], {"purpose": "Does the AUROC hold across seeds?", "data": "The held-out AUROC of each seed, from results/summary.json.",
                                            "shows": "The AUROC sits at 0.71 across 3 seeds."})
        svg = self.get("/api/projects/%s/download/%s" % (self.project_id, shown["svg"]))
        self.assertEqual((svg.status, svg.headers["content-type"]), (200, "image/svg+xml"))
        self.assertEqual((table["ref"], table["plot"]["kind"], table["plot"]["svg"]), ("R1.T1", "table", None))
        self.assertEqual(table["plot"]["csv"], "drawings/R1-1/auroc_table.csv")

    def test_a_merge_and_a_contradiction_show_their_texts_side_by_side(self):
        first, second, third, fourth = self.pairs
        [merge] = self.batch(self.merges["id"])["items"]
        self.assertEqual([(side["id"], side["text"]) for side in merge["sides"]],
                         [(first, "Moths swarm at dusk."), (second, "At dusk the moths gather in swarms.")])
        self.assertEqual(merge["sides"][0]["section"], "results")
        [contradiction] = self.batch(self.contradictions["id"])["items"]
        self.assertEqual([side["text"] for side in contradiction["sides"]], ["Activity is lowest at dusk.", "Activity peaks at dusk."])

    def test_a_proposal_shows_its_reason_evidence_feasibility_and_judgment(self):
        [item] = self.batch(self.changes["id"])["items"]
        fields = dict(item["fields"])
        self.assertEqual(fields["reason"], "the sweep shows the products add nothing past 0.70")
        self.assertEqual(fields["evidence"], "res:t3-a1/results/sweep.json#auroc")
        self.assertEqual(fields["feasibility"], "reachable: the sweep measures it")
        self.assertEqual(fields["judgment"], "upheld: the sweep bears it out")
        self.assertEqual(fields["change"], "park O1")

    def test_every_other_kind_shows_the_fields_its_batch_carries(self):
        for batch in (self.software, self.review, self.placements, self.outline):
            with self.subTest(kind=batch["kind"]):
                item = self.batch(batch["id"])["items"][0]
                self.assertEqual((item["text"], item["default"]), (batch["items"][0]["text"], batch["items"][0]["default"]))
                self.assertNotIn("plot", item)

    def test_an_unchanged_ledger_answers_304_and_a_mark_moves_the_tag(self):
        first = self.api("/marks")
        self.assertEqual(self.api("/marks", {"If-None-Match": first.etag}).status, 304)
        batches.mark(self.project, self.review["id"], 1, "stand", via="conversation")
        self.assertEqual(self.api("/marks", {"If-None-Match": first.etag}).status, 200)

    def test_a_producer_acting_moves_the_marks_tag_and_no_other_views(self):
        batches.mark(self.project, self.review["id"], 1, "stand", via="dashboard")
        marks, research = self.api("/marks"), self.api("/research")
        batches.acted_on(self.project, self.review["id"], {1: "stand"})
        self.assertEqual(self.api("/marks", {"If-None-Match": marks.etag}).status, 200, "only the batch file moved")
        self.assertEqual(self.api("/research", {"If-None-Match": research.etag}).status, 304)

    def test_a_batch_link_names_its_project_as_the_dashboard_routes_it(self):
        self.assertEqual(batches.link(self.project, self.review["id"]), "#/%s/%s" % (self.project_id, self.review["id"]))


class MarkActionTest(MarksServedCase):
    def test_mark_is_the_one_action_added(self):
        self.assertEqual(ACTIONS, ("answer", "autonomy", "pause", "resume", "switch", "cancel", "rerun", "pacing", "model_fallback",
                                   "ladder_changes", "intake", "feedback", "mark"))

    def test_a_click_saves_its_mark_at_once_and_the_ledger_reads_it_back(self):
        answer = self.act({"batch": self.plots["id"], "item": 1, "mark": "keep"})
        self.assertEqual(answer.status, 200, answer.body)
        self.assertTrue(answer.json["ok"])
        item = self.on_disk(self.plots["id"])["items"][0]
        self.assertEqual((item["mark"], item["by"], item["via"]), ("keep", "owner", "dashboard"))
        self.assertEqual(self.marked(), [{"batch": self.plots["id"], "item": 1, "mark": "keep", "by": "owner"}])
        shown = self.batch(self.plots["id"])
        self.assertEqual((shown["open"], shown["items"][0]["mark"], shown["items"][0]["via"], shown["items"][0]["changeable"]),
                         (1, "keep", "dashboard", True))

    def test_a_note_saves_with_its_item_and_alone(self):
        self.act({"batch": self.plots["id"], "item": 2, "note": "show the seeds as points"})
        self.assertEqual((self.on_disk(self.plots["id"])["items"][1]["note"], self.on_disk(self.plots["id"])["items"][1]["mark"]),
                         ("show the seeds as points", None))
        self.act({"batch": self.plots["id"], "item": 1, "mark": "maybe", "note": "a log axis"})
        item = self.on_disk(self.plots["id"])["items"][0]
        self.assertEqual((item["mark"], item["note"]), ("maybe", "a log axis"))

    def test_a_second_click_changes_the_mark_until_its_producer_acts_on_it(self):
        self.act({"batch": self.merges["id"], "item": 1, "mark": "right"})
        self.assertEqual(self.batch(self.merges["id"])["status"], "closed", "its one item settled closes it")
        answer = self.act({"batch": self.merges["id"], "item": 1, "mark": "split"})
        self.assertEqual(answer.status, 200, answer.body)
        self.assertEqual(self.on_disk(self.merges["id"])["items"][0]["mark"], "split")
        batches.acted_on(self.project, self.merges["id"], {1: "split"})
        answer = self.act({"batch": self.merges["id"], "item": 1, "mark": "right"})
        self.assertEqual(answer.status, 400)
        self.assertIn("acted on", answer.json["error"])
        self.assertEqual(self.on_disk(self.merges["id"])["items"][0]["mark"], "split")
        self.assertFalse(self.batch(self.merges["id"])["items"][0]["changeable"])

    def test_a_mark_without_the_token_is_refused_and_records_nothing(self):
        for token in (None, "not-the-token"):
            with self.subTest(token=token):
                answer = self.act({"batch": self.plots["id"], "item": 1, "mark": "keep"}, token=token)
                self.assertEqual(answer.status, 403)
                self.assertIn(TOKEN_HEADER, answer.json["error"])
        self.assertIsNone(self.on_disk(self.plots["id"])["items"][0]["mark"])
        self.assertEqual(self.marked(), [])

    def test_an_item_settled_first_in_the_conversation_shows_settled_and_is_not_answered_again(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(batches.mark_command([self.review["id"], "1", "reverse", "--note", "hold out split 2", "--project", str(self.project)]), 0)
        item = self.batch(self.review["id"])["items"][0]
        self.assertEqual((item["mark"], item["by"], item["via"], item["note"], item["changeable"]),
                         ("reverse", "owner", "conversation", "hold out split 2", False))
        answer = self.act({"batch": self.review["id"], "item": 1, "mark": "stand"})
        self.assertEqual(answer.status, 400)
        self.assertIn("settled as reverse by owner in the conversation", answer.json["error"])
        self.assertEqual(self.on_disk(self.review["id"])["items"][0]["mark"], "reverse")
        self.assertEqual(len(self.marked()), 1, "the dashboard recorded no second answer")

    def test_take_all_defaults_records_each_unsettled_items_default_in_one_action(self):
        batches.mark(self.project, self.review["id"], 2, "reverse", via="conversation")
        answer = self.act({"batch": self.review["id"], "defaults": True})
        self.assertEqual(answer.status, 200, answer.body)
        self.assertEqual(answer.json["settled"], [1])
        self.assertEqual([(item["mark"], item["via"]) for item in self.on_disk(self.review["id"])["items"]],
                         [("stand", "dashboard"), ("reverse", "conversation")])
        self.assertEqual(self.on_disk(self.review["id"])["status"], "closed")
        self.assertEqual([batch["id"] for batch in self.marks()["settled"]], [self.review["id"]])

    def test_a_body_the_action_cannot_take_is_refused_saying_why(self):
        for body, said in (({"item": 1, "mark": "keep"}, "batch"), ({"batch": self.plots["id"], "mark": "keep"}, "item"),
                           ({"batch": self.plots["id"], "item": 1, "mark": "approve"}, "keep, maybe, drop"),
                           ({"batch": self.plots["id"], "item": 1}, "a mark or a note"),
                           ({"batch": self.plots["id"], "defaults": True, "item": 1}, "defaults"),
                           ({"batch": "B99", "item": 1, "mark": "keep"}, "no batch B99")):
            with self.subTest(body=body):
                answer = self.act(body)
                self.assertEqual(answer.status, 400, answer.body)
                self.assertIn(said, answer.json["error"])
        self.assertEqual(self.marked(), [])
