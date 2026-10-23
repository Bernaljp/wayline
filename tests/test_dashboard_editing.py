"""The dashboard's editor: the sections, the outline, and a reason in Methods' parameter table (decision 17; ticket 113).

The seam is the server over HTTP against a fixture ledger: `GET edit/<target>` is what the editor opens (the file's text
below its render stamp, and the stamp), and the `edit` and `reason` actions are its saves, token-guarded like every
action. A save does what a file edit does (`wayline edit`), so what is asserted is what the next render takes in: the
passages, withdrawals, and `outline.json` entries it writes, each by the owner.
"""

import http.client
import json

from tests.test_dashboard_views import Answer, Serving
from tests.test_methods_inventory import WINDOW_REASON, InventoryCase
from tests.test_outline import Project as OutlineProject
from tests.test_owner_passages import OwnerCase
from wayline import edits, outline, sections
from wayline.dashboard import ACTIONS, TOKEN_HEADER

TOKEN = "a-token-the-editor-saves-with"


class EditServing(Serving):
    def serve(self, token=TOKEN):
        super().serve(token=token)

    def opened(self, target):
        answer = self.api("/edit/%s" % target)
        self.assertEqual(answer.status, 200, answer.body)
        return answer.json

    def act(self, name, body, token=TOKEN):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers[TOKEN_HEADER] = token
        try:
            connection.request("POST", "/api/projects/%s/actions/%s" % (self.project_id, name),
                               body=json.dumps(body).encode("utf-8"), headers=headers)
            return Answer(connection.getresponse())
        finally:
            connection.close()

    def save(self, target, text, stamp, **more):
        return self.act("edit", dict({"target": target, "text": text, "stamp": stamp}, **more))


class SectionEditCase(EditServing, OwnerCase):
    def setUp(self):
        super().setUp()
        sections.add_passage(self.ledger, "introduction", "The question", "Cells synchronise at dusk.", by="t1-a1")
        sections.add_passage(self.ledger, "introduction", "The question", "Nobody knows why.", by="t1-a1")
        sections.add_passage(self.ledger, "introduction", "The gap", "Earlier work measured nothing.", by="t1-a1")
        self.serve()


class SectionEditTest(SectionEditCase):
    def test_a_save_that_adds_changes_and_removes_text_is_taken_in_by_the_next_render_as_the_owners(self):
        opened = self.opened("introduction")
        self.assertTrue(opened["stamp"].startswith("<!-- wayline:render {"))
        self.assertNotIn("wayline:render", opened["text"])
        text = (opened["text"].replace("Cells synchronise at dusk.", "Cells synchronise at dawn.")
                .replace("Earlier work measured nothing.", "")
                + "\n## The plan\n\nWe film the cells.\n")
        answer = self.save("introduction", text, opened["stamp"])
        self.assertEqual(answer.status, 200, answer.body)
        self.assertTrue(answer.json["ok"])
        sections.render_section(self.ledger, "introduction")
        owners = [item for item in self.passages() if item["by"] == "owner"]
        self.assertEqual(sorted((item.get("replaces") or "", item["heading"], item["text"], bool(item.get("withdrawn"))) for item in owners),
                         sorted([("P1", "The question", "Cells synchronise at dawn.", False),
                                 ("P3", "The gap", "Earlier work measured nothing.", True),
                                 ("", "The plan", "We film the cells.", False)]))
        body = self.text("introduction")
        self.assertIn("Cells synchronise at dawn.", body)
        self.assertNotIn("Earlier work measured nothing.", body)
        self.assertIn("We film the cells.", body)

    def test_a_save_over_a_newer_render_stamp_shows_both_versions_and_writes_only_on_the_owners_choice(self):
        opened = self.opened("introduction")
        sections.add_passage(self.ledger, "introduction", "The gap", "A ticket wrote this meanwhile.", by="t2-a1")
        newer = self.opened("introduction")
        self.assertNotEqual(newer["stamp"], opened["stamp"])
        mine = opened["text"].replace("Nobody knows why.", "Nobody has asked why.")
        answer = self.save("introduction", mine, opened["stamp"])
        self.assertEqual(answer.status, 409, answer.body)
        self.assertFalse(answer.json["ok"])
        self.assertEqual((answer.json["current"]["text"], answer.json["current"]["stamp"]), (newer["text"], newer["stamp"]))
        self.assertEqual(answer.json["yours"]["text"], mine)
        self.assertEqual(self.opened("introduction"), newer, "nothing is written on a conflict")
        answer = self.save("introduction", mine, opened["stamp"], over_newer=True)
        self.assertEqual(answer.status, 200, answer.body)
        sections.render_section(self.ledger, "introduction")
        owners = [item for item in self.passages() if item["by"] == "owner"]
        self.assertEqual([(item.get("replaces"), item["text"], bool(item.get("withdrawn"))) for item in owners],
                         [("P2", "Nobody has asked why.", False)],
                         "read against the render it opened, the passage that arrived since is no withdrawal")
        self.assertIn("A ticket wrote this meanwhile.", self.text("introduction"))

    def test_a_save_over_an_edit_made_in_a_terminal_since_it_opened_is_a_conflict_too(self):
        opened = self.opened("introduction")
        self.edit("introduction", "Nobody knows why.", "Nobody knows why, yet.")
        answer = self.save("introduction", opened["text"].replace("dusk", "dawn"), opened["stamp"], base=opened["base"])
        self.assertEqual(answer.status, 409, answer.body)
        self.assertIn("Nobody knows why, yet.", answer.json["current"]["text"])
        self.assertIn("Nobody knows why, yet.", self.text("introduction"), "the terminal's edit stands")

    def test_a_long_section_saves_past_the_64_kib_an_action_body_otherwise_takes(self):
        opened = self.opened("introduction")
        text = opened["text"] + "\n## Long\n\n" + ("A sentence that goes on. " * 4000) + "\n"
        self.assertEqual(self.save("introduction", text, opened["stamp"], base=opened["base"]).status, 200)

    def test_a_save_of_the_text_as_opened_writes_nothing_new(self):
        opened = self.opened("introduction")
        self.assertEqual(self.save("introduction", opened["text"], opened["stamp"]).status, 200)
        sections.render_section(self.ledger, "introduction")
        self.assertEqual([item for item in self.passages() if item["by"] == "owner"], [])


class EditRefusalTest(SectionEditCase):
    def test_the_edit_actions_are_the_only_ones_added_each_refused_without_the_token(self):
        self.assertEqual(ACTIONS[19:], ("edit", "reason"))
        opened = self.opened("introduction")
        before = self.text("introduction")
        for name, body in (("edit", {"target": "introduction", "text": "x\n", "stamp": opened["stamp"]}),
                           ("reason", {"parameter": "m:n", "reason": "x"})):
            with self.subTest(action=name):
                answer = self.act(name, body, token=None)
                self.assertEqual(answer.status, 403)
                self.assertIn(TOKEN_HEADER, answer.json["error"])
        self.assertEqual(self.text("introduction"), before)

    def test_reports_the_account_the_papers_parts_and_references_offer_no_edit(self):
        (self.project / "research" / "REPORT.md").write_text("# Report\n", encoding="utf-8")
        for target in ("report", "account", "references", "R1-1", "abstract", "../REPORT"):
            with self.subTest(target=target):
                self.assertEqual(self.api("/edit/%s" % target).status, 404)
                answer = self.save(target, "# Mine\n", "<!-- wayline:render {} -->")
                self.assertEqual(answer.status, 400, answer.body)
                self.assertIn("not editable", answer.json["error"])
        self.assertEqual((self.project / "research" / "REPORT.md").read_text(encoding="utf-8"), "# Report\n")

    def test_the_paper_view_marks_which_rows_are_editable(self):
        view = self.api("/paper").json
        self.assertEqual({row["id"]: row["editable"] for row in view["sections"]},
                         {"introduction": True, "results": True, "discussion": True, "methods": True, "references": False})
        self.assertTrue(view["outline"]["editable"])


class OutlineEditTest(EditServing, OutlineProject):
    def setUp(self):
        super().setUp()
        self.render()
        self.serve()

    def test_an_outline_save_with_a_move_and_a_note_becomes_the_owners_outline_entries(self):
        opened = self.opened("outline")
        text = opened["text"].replace('- "State of the art" (1 passage)\n- "The gap" (1 passage)',
                                      '- "The gap" (1 passage)\n- "State of the art" (1 passage)\n  Note: open on the gap.')
        self.assertNotEqual(text, opened["text"])
        answer = self.save("outline", text, opened["stamp"])
        self.assertEqual(answer.status, 200, answer.body)
        outline.render_outline(self.project)
        self.assertEqual(self.record()["groups"]["introduction"], ["introduction:The gap", "introduction:State of the art"])
        self.assertEqual(self.record()["notes"], {"introduction:State of the art": "open on the gap."})
        self.assertEqual(sorted((event["action"], event["by"]) for event in self.events("outline")),
                         [("moved", "owner"), ("noted", "owner")])


class ReasonEditTest(EditServing, InventoryCase):
    OWNERS = "Two wingbeats is the shortest span over which the phase is defined."

    def setUp(self):
        super().setUp()
        self.integrated(3, [self.window()])
        self.render()
        self.serve()

    def test_a_reason_edited_in_its_row_is_the_owners_reason_for_that_row(self):
        [row] = self.api("/paper").json["methods"]["parameters"]
        self.assertEqual((row["reason"], row["parameter"]), (WINDOW_REASON, "order_parameter:window@code/phaselock.py"))
        answer = self.act("reason", {"parameter": row["parameter"], "reason": self.OWNERS})
        self.assertEqual(answer.status, 200, answer.body)
        reasons = [item for item in sections.read_passages(self.ledger) if item.get("parameter")]
        self.assertEqual([(item["by"], item["parameter"], item["text"]) for item in reasons],
                         [("owner", "order_parameter:window@code/phaselock.py", self.OWNERS)])
        self.assertIn("| %s |" % self.OWNERS, self.render())

    def test_a_reason_for_a_row_the_table_does_not_hold_is_refused(self):
        answer = self.act("reason", {"parameter": "order_parameter:nothing", "reason": self.OWNERS})
        self.assertEqual(answer.status, 400, answer.body)
        self.assertEqual([item for item in sections.read_passages(self.ledger) if item.get("parameter")], [])


class EditVerbTest(OwnerCase):
    """`wayline edit`: the verb the dashboard's save calls, writing the file as a terminal edit would."""

    def test_the_verb_writes_the_text_under_the_stamp_it_was_opened_with(self):
        sections.add_passage(self.ledger, "methods", "Fitting", "We fit by eye.", by="t1-a1")
        opened = edits.opened(self.project, "methods")
        edits.save(self.project, "methods", opened["text"].replace("by eye", "by least squares"), opened["stamp"])
        self.assertEqual(self.text("methods").split("\n", 1)[0], opened["stamp"])
        sections.render_section(self.ledger, "methods")
        [owner] = [item for item in self.passages() if item["by"] == "owner"]
        self.assertEqual((owner["replaces"], owner["text"]), ("P1", "We fit by least squares."))
