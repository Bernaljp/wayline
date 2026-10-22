"""Batches and marks (ticket 79): one record for every batch of items the owner or the decider settles.

Every test runs over a temporary project through the ledger seam: a producer opens a batch, the
owner marks it, and the producer reads the marks back from the files the ledger wrote.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.paths import SPEC_PATH
from tests.spec_table import spec_verbs
from wayline import batches, cli, dashboard
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger


class BatchTestCase(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="wayline-batches-"))
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / "harness.json").write_text("{}\n", encoding="utf-8")
        self.ledger = Ledger(self.project)
        # The project registered under a temporary ~/.wayline, so the dashboard's link names it as its tabs do.
        home = self.project / "home"
        previous = os.environ.get("WAYLINE_HOME")
        os.environ["WAYLINE_HOME"] = str(home)
        self.addCleanup(lambda: os.environ.pop("WAYLINE_HOME") if previous is None else os.environ.__setitem__("WAYLINE_HOME", previous))
        home.mkdir()
        (home / "projects.json").write_text(json.dumps([{"path": str(self.project.resolve()), "name": "toy"}]), encoding="utf-8")

    def plots(self, count=3, defaults=("keep", None, "drop")):
        items = [{"ref": "P%d" % (n + 1), "text": "plot P%d of R4" % (n + 1), "default": defaults[n % len(defaults)]} for n in range(count)]
        return batches.open_batch(self.project, "plots", "Plots of R4", items, decision=12)

    def on_disk(self, identifier):
        return json.loads((self.project / "research" / "batches" / ("%s.json" % identifier)).read_text(encoding="utf-8"))

    def marked_events(self):
        events, _ = self.ledger.read_events()
        return [event for event in events if event["event"] == "marked"]


class OpenBatchTest(BatchTestCase):
    def test_a_batch_is_written_through_the_ledger_under_its_schema(self):
        batch = self.plots()
        self.assertEqual(batch["id"], "B1")
        record = self.on_disk("B1")
        check(record, load_schema("batch"))
        self.assertEqual((record["kind"], record["title"], record["decision"], record["status"]), ("plots", "Plots of R4", 12, "open"))
        self.assertEqual([item["id"] for item in record["items"]], [1, 2, 3])
        first = record["items"][0]
        self.assertEqual((first["ref"], first["marks"], first["default"], first["note"], first["mark"]), ("P1", ["keep", "maybe", "drop"], "keep", None, None))
        self.assertIsNone(record["items"][1]["default"])

    def test_ids_count_up_and_are_never_reused(self):
        self.assertEqual([self.plots()["id"] for _ in range(3)], ["B1", "B2", "B3"])

    def test_each_kind_carries_the_marks_view_marks(self):
        expected = {
            "plots": ["keep", "maybe", "drop"],
            "objective_changes": ["approve", "decline"],
            "software_ask": ["approve", "decline"],
            "account_review": ["stand", "reverse"],
            "merges": ["right", "split"],
            "contradictions": ["real", "not a contradiction"],
            "concern_placements": ["take it", "another place"],
            "outline_proposals": ["take", "decline"],
            "paper_order": ["the first", "the second", "a typo, fix it", "leave out", "keep, not verified", "hand over", "drop",
                            "to be resolved", "take", "decline", "keep as stated"],
        }
        self.assertEqual(set(batches.KINDS), set(expected))
        for kind, marks in expected.items():
            if kind in batches.PER_ITEM:
                continue
            with self.subTest(kind=kind):
                batch = batches.open_batch(self.project, kind, "a %s batch" % kind, [{"ref": "x1", "text": "one item", "default": marks[0]}])
                self.assertEqual(batches.read_batch(self.project, batch["id"])["items"][0]["marks"], marks)
                batches.mark(self.project, batch["id"], 1, marks[-1])
                self.assertEqual(batches.marks(self.project, batch["id"])[0]["mark"], marks[-1])
                self.assertEqual(batches.read_batch(self.project, batch["id"])["status"], "closed")

    def test_the_schema_names_the_same_kinds(self):
        self.assertEqual(load_schema("batch")["properties"]["kind"]["enum"], list(batches.KINDS))

    def test_a_paper_order_item_carries_its_own_marks_and_a_file_repeating_one_is_refused(self):
        batch = batches.open_batch(self.project, "paper_order", "Paper order 1", [
            {"ref": "reference:smith2020", "text": "Unresolved.", "marks": ["hand over", "drop", "to be resolved"], "default": "to be resolved"}])
        self.assertEqual(batches.read_batch(self.project, batch["id"])["items"][0]["marks"], ["hand over", "drop", "to be resolved"])
        with self.assertRaisesRegex(batches.BatchError, "take"):
            batches.mark(self.project, batch["id"], 1, "take")
        with self.assertRaisesRegex(batches.BatchError, "its own marks"):
            batches.open_batch(self.project, "paper_order", "Paper order 2", [{"ref": "x", "text": "y", "marks": ["take"]}])
        record = self.on_disk(batch["id"])
        record["items"][0]["marks"] = ["drop", "drop"]
        (self.project / "research" / "batches" / ("%s.json" % batch["id"])).write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(batches.BatchError):
            batches.read_batch(self.project, batch["id"])

    def test_a_file_whose_marks_are_not_its_kinds_is_refused_on_read(self):
        self.plots(count=1)
        record = self.on_disk("B1")
        record["items"][0]["marks"] = ["keep", "approve"]
        (self.project / "research" / "batches" / "B1.json").write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(batches.BatchError, "keep, maybe, drop"):
            batches.read_batch(self.project, "B1")

    def test_an_unknown_kind_or_a_default_outside_the_kind_is_refused(self):
        with self.assertRaisesRegex(batches.BatchError, "kind"):
            batches.open_batch(self.project, "figures", "t", [{"ref": "F1", "text": "a figure"}])
        with self.assertRaisesRegex(batches.BatchError, "approve"):
            batches.open_batch(self.project, "plots", "t", [{"ref": "P1", "text": "a plot", "default": "approve"}])
        with self.assertRaisesRegex(batches.BatchError, "no items"):
            batches.open_batch(self.project, "plots", "t", [])
        self.assertFalse((self.project / "research" / "batches").exists(), "a refused batch writes nothing")


class MarkTest(BatchTestCase):
    def test_a_mark_settles_the_item_and_is_journaled(self):
        self.plots()
        batches.mark(self.project, "B1", 2, "maybe", note="redraw on a log axis")
        item = self.on_disk("B1")["items"][1]
        self.assertEqual((item["mark"], item["note"], item["by"]), ("maybe", "redraw on a log axis", "owner"))
        self.assertRegex(item["at"], r"^\d{4}-\d\d-\d\dT")
        [event] = self.marked_events()
        self.assertEqual(event["payload"], {"batch": "B1", "item": 2, "mark": "maybe", "note": "redraw on a log axis", "by": "owner"})

    def test_a_mark_the_kind_does_not_allow_is_refused(self):
        batches.open_batch(self.project, "merges", "Merges at setup", [{"ref": "M1", "text": "R2 and R5 say one thing"}])
        with self.assertRaisesRegex(batches.BatchError, "right, split"):
            batches.mark(self.project, "B1", 1, "keep")
        self.assertIsNone(self.on_disk("B1")["items"][0]["mark"])
        self.assertEqual(self.marked_events(), [])

    def test_an_item_or_a_batch_that_is_not_there_is_refused(self):
        self.plots()
        with self.assertRaisesRegex(batches.BatchError, "no item 9"):
            batches.mark(self.project, "B1", 9, "keep")
        with self.assertRaisesRegex(batches.BatchError, "no batch B7"):
            batches.mark(self.project, "B7", 1, "keep")

    def test_the_decider_settles_as_itself(self):
        batches.open_batch(self.project, "account_review", "Decider decisions", [{"ref": "T31", "text": "chose the smaller model", "default": "stand"}])
        batches.mark(self.project, "B1", 1, "reverse", by="decider")
        self.assertEqual(self.on_disk("B1")["items"][0]["by"], "decider")
        self.assertEqual(self.marked_events()[0]["payload"]["by"], "decider")


class SettlingTest(BatchTestCase):
    def test_the_first_answer_settles_and_a_second_is_refused_naming_it(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "drop")
        with self.assertRaises(batches.BatchError) as caught:
            batches.mark(self.project, "B1", 1, "keep", by="decider")
        self.assertIn("settled as drop by owner", str(caught.exception))
        item = self.on_disk("B1")["items"][0]
        self.assertEqual((item["mark"], item["by"]), ("drop", "owner"))
        self.assertEqual(len(self.marked_events()), 1, "a refused mark journals nothing")

    def test_a_note_alone_is_kept_without_settling(self):
        self.plots()
        batches.mark(self.project, "B1", 3, None, note="the colors clash")
        item = self.on_disk("B1")["items"][2]
        self.assertEqual((item["mark"], item["note"], item["by"], item["at"]), (None, "the colors clash", None, None))
        [event] = self.marked_events()
        self.assertEqual(event["payload"], {"batch": "B1", "item": 3, "note": "the colors clash", "by": "owner"})
        batches.mark(self.project, "B1", 3, "maybe")
        item = self.on_disk("B1")["items"][2]
        self.assertEqual((item["mark"], item["note"]), ("maybe", "the colors clash"), "a later mark keeps the note")

    def test_neither_a_mark_nor_a_note_is_refused(self):
        self.plots()
        with self.assertRaisesRegex(batches.BatchError, "a mark or a note"):
            batches.mark(self.project, "B1", 1, None)

    def test_a_note_on_a_settled_item_is_refused(self):
        """Its producer may already have read the item back, so a later note would be lost on it."""
        self.plots()
        batches.mark(self.project, "B1", 1, "keep")
        with self.assertRaisesRegex(batches.BatchError, "settled as keep"):
            batches.mark(self.project, "B1", 1, None, note="too late")

    def test_a_batch_closes_when_its_last_item_is_settled_and_its_marks_read_back(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "keep")
        batches.mark(self.project, "B1", 2, "drop", note="says nothing new")
        self.assertEqual(self.on_disk("B1")["status"], "open")
        batches.mark(self.project, "B1", 3, "maybe")
        self.assertEqual(self.on_disk("B1")["status"], "closed")
        self.assertEqual(batches.marks(self.project, "B1"), [
            {"item": 1, "ref": "P1", "mark": "keep", "note": None, "by": "owner"},
            {"item": 2, "ref": "P2", "mark": "drop", "note": "says nothing new", "by": "owner"},
            {"item": 3, "ref": "P3", "mark": "maybe", "note": None, "by": "owner"},
        ])

    def test_open_batches_are_listed_and_closed_ones_are_not(self):
        self.plots(count=1)
        batches.open_batch(self.project, "merges", "Merges", [{"ref": "M1", "text": "R2 and R5"}])
        batches.mark(self.project, "B1", 1, "keep")
        self.assertEqual([batch["id"] for batch in batches.read_batches(self.project)], ["B1", "B2"])
        self.assertEqual([batch["id"] for batch in batches.read_batches(self.project, status="open")], ["B2"])


class ChangeTest(BatchTestCase):
    """Where a mark was given (ticket 112): a mark the dashboard gave changes on a second click until its producer acts on it."""

    def test_each_settled_item_says_where_it_was_given(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        batches.mark(self.project, "B1", 2, "drop", via="conversation")
        batches.mark(self.project, "B1", 3, "maybe", by="decider")
        self.assertEqual([(item["by"], item["via"]) for item in self.on_disk("B1")["items"]],
                         [("owner", "dashboard"), ("owner", "conversation"), ("decider", None)])

    def test_a_second_dashboard_mark_changes_the_first_and_is_journaled(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        batches.mark(self.project, "B1", 1, "drop", note="a duplicate of P2", via="dashboard")
        item = self.on_disk("B1")["items"][0]
        self.assertEqual((item["mark"], item["note"], item["by"], item["via"]), ("drop", "a duplicate of P2", "owner", "dashboard"))
        self.assertEqual([event["payload"].get("mark") for event in self.marked_events()], ["keep", "drop"])
        self.assertEqual(batches.marks(self.project, "B1")[0]["mark"], "drop", "its producer reads the changed mark")

    def test_the_same_mark_again_records_nothing_and_a_note_alone_is_kept(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        self.assertEqual(len(self.marked_events()), 1, "a second click on the same mark is no new answer")
        batches.mark(self.project, "B1", 1, None, note="the headline plot", via="dashboard")
        item = self.on_disk("B1")["items"][0]
        self.assertEqual((item["mark"], item["note"]), ("keep", "the headline plot"))

    def test_the_last_item_changed_leaves_its_batch_closed(self):
        self.plots(count=1)
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        batches.mark(self.project, "B1", 1, "maybe", via="dashboard")
        self.assertEqual((self.on_disk("B1")["status"], self.on_disk("B1")["items"][0]["mark"]), ("closed", "maybe"))

    def test_an_item_settled_in_the_conversation_is_not_answered_again_from_the_dashboard(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "drop", via="conversation")
        with self.assertRaisesRegex(batches.BatchError, "settled as drop by owner in the conversation"):
            batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        with self.assertRaisesRegex(batches.BatchError, "settled as drop"):
            batches.mark(self.project, "B1", 1, None, note="too late", via="dashboard")
        self.assertEqual(self.on_disk("B1")["items"][0]["mark"], "drop")
        self.assertEqual(len(self.marked_events()), 1)

    def test_the_conversation_and_the_decider_do_not_change_a_dashboard_mark(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        with self.assertRaisesRegex(batches.BatchError, "settled as keep by owner in the dashboard"):
            batches.mark(self.project, "B1", 1, "drop", via="conversation")
        with self.assertRaisesRegex(batches.BatchError, "settled as keep"):
            batches.mark(self.project, "B1", 1, "drop", by="decider", via="dashboard")

    def test_a_mark_its_producer_acted_on_is_final(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "drop", via="dashboard")
        batches.mark(self.project, "B1", 2, "keep", via="dashboard")
        self.assertEqual(batches.acted_on(self.project, "B1", {1: "drop", 3: "keep"}), [1], "an open item is not acted on")
        self.assertRegex(self.on_disk("B1")["items"][0]["acted"], r"^\d{4}-")
        self.assertIsNone(self.on_disk("B1")["items"][2]["acted"])
        with self.assertRaisesRegex(batches.BatchError, "acted on"):
            batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        self.assertEqual(batches.acted_on(self.project, "B1", {1: "drop"}), [], "acting twice stamps nothing new")
        self.assertEqual(batches.acted_on(self.project, "B1", {2: "drop"}), [], "a mark changed since the producer read it is not the one it acted on")
        batches.mark(self.project, "B1", 2, "maybe", via="dashboard")
        self.assertEqual(self.on_disk("B1")["items"][1]["mark"], "maybe", "an item not acted on still changes")

    def test_changeable_says_which_items_a_dashboard_click_may_change(self):
        self.plots()
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        batches.mark(self.project, "B1", 2, "keep", via="conversation")
        items = self.on_disk("B1")["items"]
        self.assertEqual([batches.changeable(item) for item in items], [True, False, False])

    def test_taking_the_defaults_from_the_dashboard_leaves_them_changeable(self):
        self.plots()
        batch, settled = batches.take_defaults(self.project, "B1", via="dashboard")
        self.assertEqual(settled, [1, 3])
        self.assertEqual([item["via"] for item in batch["items"]], ["dashboard", None, "dashboard"])
        batches.mark(self.project, "B1", 3, "keep", via="dashboard")
        self.assertEqual(self.on_disk("B1")["items"][2]["mark"], "keep")


    def test_a_batch_that_cannot_be_read_is_stamped_nothing_and_raises_nothing(self):
        """Its producer has acted and journaled the act already: the stamp's failing must not fail it."""
        self.plots(count=1)
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        (self.project / "research" / "batches" / "B1.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(batches.acted_on(self.project, "B1", {1: "keep"}), [])
        self.assertEqual(batches.acted_on(self.project, "B9", {1: "keep"}), [])

    def test_an_emptied_note_box_takes_the_note_away(self):
        self.plots()
        batches.mark(self.project, "B1", 1, None, note="a log axis", via="dashboard")
        batches.mark(self.project, "B1", 1, None, via="dashboard", clear_note=True)
        self.assertIsNone(self.on_disk("B1")["items"][0]["note"])
        self.assertEqual(self.marked_events()[-1]["payload"], {"batch": "B1", "item": 1, "note": "", "by": "owner"})
        batches.mark(self.project, "B1", 1, None, via="dashboard", clear_note=True)
        self.assertEqual(len(self.marked_events()), 2, "an item with no note is left as it was")
        batches.mark(self.project, "B1", 2, "keep", note="the headline", via="dashboard")
        batches.mark(self.project, "B1", 2, None, via="dashboard", clear_note=True)
        self.assertEqual((self.on_disk("B1")["items"][1]["mark"], self.on_disk("B1")["items"][1]["note"]), ("keep", None))
        batches.mark(self.project, "B1", 3, "drop", note="says nothing", via="conversation")
        with self.assertRaisesRegex(batches.BatchError, "settled as drop"):
            batches.mark(self.project, "B1", 3, None, via="dashboard", clear_note=True)
        with self.assertRaisesRegex(batches.BatchError, "no mark and no note"):
            batches.mark(self.project, "B1", 1, "keep", via="dashboard", clear_note=True)

    def test_a_batch_written_before_the_marks_view_is_read_with_its_items_open_to_no_place(self):
        self.plots(count=1)
        path = self.project / "research" / "batches" / "B1.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        for item in record["items"]:
            del item["via"], item["acted"]
        path.write_text(json.dumps(record), encoding="utf-8")
        batches.mark(self.project, "B1", 1, "keep", via="dashboard")
        batches.mark(self.project, "B1", 1, "drop", via="dashboard")
        self.assertEqual((self.on_disk("B1")["items"][0]["mark"], self.on_disk("B1")["items"][0]["via"]), ("drop", "dashboard"))


class TakeDefaultsTest(BatchTestCase):
    def test_every_open_item_with_a_default_is_settled_and_the_rest_left_open(self):
        self.plots(count=4, defaults=("keep", None, "drop", "maybe"))
        batches.mark(self.project, "B1", 4, "keep", note="the headline")
        batch, settled = batches.take_defaults(self.project, "B1")
        self.assertEqual(settled, [1, 3])
        self.assertEqual([(item["id"], item["mark"], item["by"]) for item in batch["items"]],
                         [(1, "keep", "owner"), (2, None, None), (3, "drop", "owner"), (4, "keep", "owner")])
        self.assertEqual(self.on_disk("B1")["status"], "open", "item 2 has no default and stays open")
        self.assertEqual([(event["payload"]["item"], event["payload"]["mark"]) for event in self.marked_events()], [(4, "keep"), (1, "keep"), (3, "drop")])

    def test_taking_the_defaults_can_close_the_batch(self):
        batches.open_batch(self.project, "objective_changes", "Objective changes", [
            {"ref": "O3 park", "text": "park O3: its question waits on R2", "default": "approve"},
            {"ref": "O5 add", "text": "add: does the effect hold at scale?", "default": "decline"},
        ])
        batch, settled = batches.take_defaults(self.project, "B1", by="decider")
        self.assertEqual((batch["status"], settled), ("closed", [1, 2]))
        self.assertEqual([(entry["mark"], entry["by"]) for entry in batches.marks(self.project, "B1")], [("approve", "decider"), ("decline", "decider")])

    def test_nothing_left_to_default_journals_nothing(self):
        self.plots(count=1, defaults=(None,))
        self.assertEqual(batches.take_defaults(self.project, "B1")[1], [])
        self.assertEqual(self.marked_events(), [])


class RenderTest(BatchTestCase):
    def test_five_items_are_shown_whole(self):
        self.plots(count=5)
        batches.mark(self.project, "B1", 2, "drop", note="says nothing new")
        text = batches.render(self.project, "B1")
        lines = text.splitlines()
        self.assertEqual(lines[0], "B1 plots: Plots of R4 (decision 12), 5 items, 4 open")
        self.assertIn("  1. P1: plot P1 of R4 [keep, maybe, drop; default keep]", lines)
        self.assertIn("  2. P2: plot P2 of R4 [settled: drop, by owner] note: says nothing new", lines)
        self.assertIn("  4. P4: plot P4 of R4 [keep, maybe, drop; default keep]", lines)
        self.assertIn("  5. P5: plot P5 of R4 [keep, maybe, drop; no default]", lines)
        self.assertEqual(lines[-1], "Also in the marks view: #/%s/B1" % self.project.name)

    def test_six_items_are_one_line_with_the_count_and_a_link(self):
        self.plots(count=6)
        text = batches.render(self.project, "B1")
        self.assertEqual(text, "B1 plots: Plots of R4 (decision 12), 6 items, 6 open, in the marks view: #/%s/B1" % self.project.name)

    def test_the_link_names_the_project_as_the_dashboard_does(self):
        (self.project / "home" / "projects.json").write_text("[]", encoding="utf-8")
        self.plots(count=6)
        self.assertTrue(batches.render(self.project, "B1").endswith("#/%s/B1" % self.project.name))
        renamed = self.project / "home" / "two words"
        renamed.mkdir()
        (renamed / "harness.json").write_text("{}\n", encoding="utf-8")
        batches.open_batch(renamed, "merges", "Merges", [{"ref": "M1", "text": "R2 and R5"}] * 6)
        # A directory name that is no URL segment gets the dashboard's eight-hex suffix, tab or no tab yet.
        self.assertRegex(batches.render(renamed, "B1"), r"#/two-words-[0-9a-f]{8}/B1$")
        (self.project / "home" / "projects.json").write_text(json.dumps([{"path": str(renamed.resolve())}]), encoding="utf-8")
        self.assertEqual(batches.link(renamed, "B1"), "#/%s/B1" % dashboard.project_ids()[str(renamed.resolve())])

    def test_a_blank_note_with_a_mark_is_no_note(self):
        self.plots(count=1)
        batches.mark(self.project, "B1", 1, "keep", note="  ")
        self.assertIsNone(self.on_disk("B1")["items"][0]["note"])
        self.assertNotIn("note", self.marked_events()[0]["payload"])

    def test_an_item_without_its_ref_or_text_or_a_blank_title_is_refused(self):
        with self.assertRaisesRegex(batches.BatchError, "title"):
            batches.open_batch(self.project, "plots", " ", [{"ref": "P1", "text": "a plot"}])
        with self.assertRaisesRegex(batches.BatchError, "`ref`"):
            batches.open_batch(self.project, "plots", "Plots", [{"text": "a plot"}])

    def test_a_closed_batch_says_so(self):
        batches.open_batch(self.project, "contradictions", "Contradictions", [{"ref": "C1", "text": "P3 says up, P9 says down", "default": "real"}])
        batches.take_defaults(self.project, "B1")
        self.assertTrue(batches.render(self.project, "B1").startswith("B1 contradictions: Contradictions, 1 item, closed\n"))


class MarkVerbTest(BatchTestCase):
    def run_verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["mark", *args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def test_the_verb_records_a_mark_with_a_note(self):
        self.plots()
        code, out, err = self.run_verb("B1", "2", "keep", "--note", "the headline plot")
        self.assertEqual(code, 0, err)
        self.assertEqual(batches.marks(self.project, "B1")[1], {"item": 2, "ref": "P2", "mark": "keep", "note": "the headline plot", "by": "owner"})
        self.assertIn("item 2 of B1 (P2) marked keep", out)
        self.assertEqual(self.on_disk("B1")["items"][1]["via"], "conversation", "the verb is the conversation's")

    def test_a_mark_of_several_words_needs_no_quotes(self):
        batches.open_batch(self.project, "contradictions", "Contradictions", [{"ref": "C1", "text": "P3 says up, P9 says down"}])
        code, out, err = self.run_verb("B1", "1", "not", "a", "contradiction")
        self.assertEqual(code, 0, err)
        self.assertEqual(batches.marks(self.project, "B1")[0]["mark"], "not a contradiction")
        self.assertIn("B1 is closed", out)

    def test_a_note_alone_and_the_defaults_and_the_decider(self):
        self.plots()
        self.assertEqual(self.run_verb("B1", "2", "--note", "try a violin")[0], 0)
        code, out, err = self.run_verb("B1", "--defaults", "--by", "decider")
        self.assertEqual(code, 0, err)
        self.assertEqual([(entry["mark"], entry["note"], entry["by"]) for entry in batches.marks(self.project, "B1")],
                         [("keep", None, "decider"), (None, "try a violin", None), ("drop", None, "decider")])
        self.assertIn("2 item(s) of B1 settled by their defaults; 1 open", out)

    def test_a_refused_mark_exits_2_saying_why(self):
        self.plots()
        self.run_verb("B1", "1", "drop")
        code, out, err = self.run_verb("B1", "1", "keep")
        self.assertEqual(code, 2)
        self.assertIn("settled as drop by owner", err)
        code, out, err = self.run_verb("B1", "3", "approve")
        self.assertEqual(code, 2)
        self.assertIn("keep, maybe, drop", err)

    def test_the_batch_alone_prints_its_rendering(self):
        self.plots()
        code, out, err = self.run_verb("B1")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.rstrip("\n"), batches.render(self.project, "B1"))

    def test_the_verb_is_in_the_spec_table_and_built(self):
        self.assertIn("mark", spec_verbs(SPEC_PATH))
        self.assertIsNotNone(cli.lookup("mark").handler)


if __name__ == "__main__":
    unittest.main()
