"""Reading the paper with its provenance (ticket 141), over HTTP against a fixture composed paper.

The seam is the server's JSON: `paper/read`, the current version's main text as headings, sentences, and figures built
by code from what is on disk and in the ledger, and `items/<id>`, which resolves a sentence's or a figure's item id. The
project holds the composed paper of `tests/reading_fixture.py`, modelled on the M8 toy's. Nothing here calls a model:
the server answers from files and the journal alone.
"""

import json

from tests import reading_fixture as fixture
from tests.projects import ProjectTestCase
from tests.test_dashboard_views import Serving
from wayline import chat, dashboard_views, provenance
from wayline import project as projects


class ReadingCase(Serving, ProjectTestCase):
    token = None  # the dashboard's token, which the browser tests serve with so Comment and This is wrong are on

    def setUp(self):
        super().setUp()
        self.project = (self.temp / "reading-project").resolve()
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.book = fixture.make_reading_paper(self.project)
        self.serve(token=self.token)

    def read(self):
        answer = self.api("/paper/read")
        self.assertEqual(answer.status, 200, answer.body)
        return answer.json

    def sentences(self, view=None):
        view = view or self.read()
        return [sentence for block in view["blocks"] if block["type"] == "paragraph" for sentence in block["sentences"]]

    def sentence(self, text, view=None):
        """The sentence whose text, tags and all, is `text`, in the main text: the abstract repeats the gain."""
        found = [sentence for sentence in self.sentences(view) if sentence["text"] == text and sentence["part"] != "abstract"]
        self.assertEqual(len(found), 1, "%r is not one sentence of the view" % text)
        return found[0]


class MainTextTest(ReadingCase):
    def test_the_main_text_comes_in_order_with_each_heading_carrying_its_id(self):
        view = self.read()
        self.assertEqual(view["version"], 2)
        self.assertEqual([block["part"] for block in view["blocks"] if block["type"] == "part"],
                         ["title", "abstract", "introduction", "results", "discussion", "methods"])
        headings = [(block["part"], block["level"], block["text"], block["id"]) for block in view["blocks"] if block["type"] == "heading"]
        self.assertIn(("results", 2, "Does the product column help, and by how much?", "O1"), headings)
        self.assertIn(("results", 3, "The column lifts the AUROC to near the ceiling", "R1"), headings)
        self.assertIn(("introduction", 2, "Interactions in linear models", "introduction-interactions"), headings)
        self.assertNotIn("supplement", [block["part"] for block in view["blocks"]])

    def test_a_tag_in_a_heading_is_hidden_as_a_sentences_is(self):
        self.book.write_markdown("paper/discussion.md", fixture.TEXTS["discussion"].replace(
            "## Scope {#discussion-scope}", "## Scope of the gain {res:t12-a1/analysis/E2/paired.json#paired_gain} {#discussion-scope}"))
        [heading] = [block for block in self.read()["blocks"] if block["type"] == "heading" and block["part"] == "discussion"]
        self.assertEqual((heading["text"], heading["id"]), ("Scope of the gain", "discussion-scope"))


class SourceTest(ReadingCase):
    def test_each_sentence_is_classed_by_where_it_comes_from(self):
        view = self.read()
        classed = {text: self.sentence(text, view)["source"] for text in (
            fixture.GAIN, fixture.PINNED, fixture.ARMS, fixture.RULES, fixture.LOST, fixture.UNTAGGED, fixture.TRANSITION,
            fixture.OWNERS, fixture.EARLIER)}
        self.assertEqual(classed, {
            fixture.GAIN: "result", fixture.PINNED: "result", fixture.ARMS: "code", fixture.RULES: "literature",
            fixture.LOST: "unresolved", fixture.UNTAGGED: "untagged", fixture.TRANSITION: "prose",
            fixture.OWNERS: "owner", fixture.EARLIER: "document"})

    def test_a_sentence_shows_its_text_without_its_tags_and_its_item_id_is_its_part_and_number(self):
        view = self.read()
        gain = self.sentence(fixture.GAIN, view)
        self.assertEqual(gain["plain"], "Over 20 paired seeds the column lifts the mean held-out AUROC from 0.7681 to 0.8552, "
                                        "a mean paired gain of 0.0872.")
        self.assertEqual(gain["id"], "results.s1")
        figure_line = [sentence for sentence in self.sentences(view) if sentence["plain"].startswith("As Figure 1 shows")]
        self.assertEqual([sentence["id"] for sentence in figure_line], ["results.s4"])
        self.assertEqual([sentence["id"] for sentence in self.sentences(view) if sentence["part"] == "abstract"],
                         ["abstract.s1", "abstract.s2"])
        self.assertEqual(view["counts"]["source"]["result"], 8)


class TagTest(ReadingCase):
    def tags(self, text):
        return {tag["tag"]: tag for tag in self.sentence(text)["tags"]}

    def test_a_res_tag_names_its_run_its_file_and_the_value_its_locator_holds(self):
        tag = self.tags(fixture.PINNED)["res:t3-a1/tests/test_train.py#BASE_AUROC"]
        self.assertEqual((tag["kind"], tag["run"], tag["ticket"], tag["path"], tag["locator"]),
                         ("res", "t3-a1", 3, "tests/test_train.py", "BASE_AUROC"))
        self.assertEqual(tag["held"], ["BASE_AUROC = %s" % fixture.BASE_AUROC])
        self.assertEqual(tag["values"], [float(fixture.BASE_AUROC)])
        self.assertEqual(tag["open"], "tests/test_train.py")
        self.assertIsNone(tag["problem"])
        gain = self.tags(fixture.GAIN)["res:t12-a1/analysis/E2/paired.json#paired_gain"]
        self.assertEqual((gain["held"], gain["values"]), (["paired_gain = 0.0872"], [0.0872]))

    def test_code_ref_and_doc_tags_name_what_they_point_at_and_say_when_they_do_not_resolve(self):
        code = self.tags(fixture.ARMS)["code:src/toy/train.py#ready_interactions"]
        self.assertEqual((code["kind"], code["path"], code["locator"], code["open"], code["problem"]),
                         ("code", "code/src/toy/train.py", "ready_interactions", "code/src/toy/train.py", None))
        rules = self.tags(fixture.RULES)["ref:friedman-2008-rules#abstract"]
        self.assertEqual((rules["slug"], rules["work"], rules["problem"], rules["mark"]),
                         ("friedman-2008-rules", "J. Friedman, B. Popescu (2008), Predictive learning via rule ensembles", None, None))
        lost = self.tags(fixture.LOST)["ref:paper-a#existence"]
        self.assertEqual(lost["mark"], "to be resolved")
        self.assertIn("does not say existence: verified", lost["problem"])
        earlier = self.tags(fixture.EARLIER)["doc:D1#p3"]
        self.assertEqual((earlier["document"], earlier["item"]), ("D1", "D1"))
        self.assertIn("keeps no document D1", earlier["problem"])

    def test_a_res_tag_whose_run_the_manifest_does_not_hold_says_so_and_reads_nothing(self):
        text = fixture.TEXTS["results"].replace(fixture.PINNED, fixture.PINNED.replace("t3-a1", "t4-a1"))
        self.book.write_markdown("paper/results.md", text)
        tag = self.tags(fixture.PINNED.replace("t3-a1", "t4-a1"))["res:t4-a1/tests/test_train.py#BASE_AUROC"]
        self.assertEqual((tag["held"], tag["values"]), ([], []))
        self.assertIn("not from run t4-a1", tag["problem"])


class CheckTest(ReadingCase):
    def test_a_sentence_stands_as_its_checks_left_it_read_from_the_journal_and_the_builds(self):
        view = self.read()
        gain, closes, positive, pinned = (self.sentence(text, view) for text in (fixture.GAIN, fixture.CLOSES, fixture.POSITIVE,
                                                                                 fixture.PINNED))
        self.assertEqual((gain["check"], closes["check"], positive["check"], pinned["check"]), ("passed", "failed", "failed", "unchecked"))
        [support] = gain["checks"]
        self.assertEqual((support["check"], support["verdict_type"], support["pass"], support["model"], support["session_id"]),
                         ("claim verdict", "claim_support", True, "claude-opus-5-5", "a1b2c3d4"))
        [numbers] = closes["checks"]
        self.assertEqual((numbers["check"], numbers["verdict_type"], numbers["pass"], numbers["ticket"]),
                         ("numbers check", "numbers_match", False, 12))
        self.assertIn("does not hold the third place", numbers["findings"][0]["text"])
        self.assertEqual([(check["check"], check["pass"]) for check in positive["checks"]],
                         [("claim verdict", False), ("build 1: the sampled verdicts", False)])
        self.assertIn("counts seeds, not differences", positive["checks"][1]["text"])
        self.assertEqual(pinned["checks"], [])
        self.assertEqual(view["counts"]["check"], {"passed": 2, "failed": 2, "unchecked": 13},
                         "the abstract's copy of the gain is the same claim, and its verdict stands for both")

    def test_a_later_verdict_that_passed_stands_over_an_earlier_one_that_failed(self):
        fixture._verdict(self.book, "ticket 12#numbers-%s" % fixture.sentence_digest(fixture.CLOSES), "numbers_match", True, ticket=12,
                         session="later")
        closes = self.sentence(fixture.CLOSES)
        self.assertEqual(closes["check"], "passed")
        self.assertEqual([check["pass"] for check in closes["checks"]], [True])


    def test_a_numbers_verdict_on_a_findings_sentence_reaches_the_paper_sentence_with_its_words_and_other_tags(self):
        from wayline import sections
        sections.file_finding(self.book, {"id": "t12-a1-f3", "ticket": 12, "text": fixture.CLOSES, "provenance": [], "negative": False,
                                          "heading": "The column lifts the AUROC to near the ceiling", "replaces": None, "objectives": ["O1"]})
        retagged = fixture.CLOSES + " {res:t12-a1/analysis/E2/paired.json#mean_auroc_with}"
        self.book.write_markdown("paper/results.md", fixture.TEXTS["results"].replace(fixture.CLOSES, retagged))
        closes = self.sentence(retagged)
        self.assertEqual([(check["check"], check["pass"]) for check in closes["checks"]], [("numbers check", False)])
        self.assertEqual(closes["check"], "failed")


class WrittenFromTest(ReadingCase):
    def test_a_sentence_names_the_finding_it_was_written_from_its_ticket_run_result_and_objectives(self):
        view = self.read()
        gain = self.sentence(fixture.GAIN, view)
        self.assertEqual([(item["kind"], item["id"], item["ticket"]) for item in gain["from"]], [("finding", "t12-a1-f1", 12)])
        self.assertEqual((gain["result"], gain["objectives"], gain["tickets"], gain["runs"]), ("R1", ["O1"], [12], ["t12-a1"]))
        pinned = self.sentence(fixture.PINNED, view)
        self.assertEqual((pinned["result"], pinned["objectives"], pinned["runs"]), ("R2", ["O1"], ["t3-a1"]))
        parked = self.sentence(fixture.PARKED, view)
        self.assertEqual((parked["result"], parked["objectives"]), ("R3", ["O2"]))
        abstract = [sentence for sentence in self.sentences(view) if sentence["part"] == "abstract" and sentence["text"] == fixture.GAIN]
        self.assertEqual([(sentence["result"], sentence["objectives"]) for sentence in abstract], [("R1", ["O1"])],
                         "outside Results a sentence's result is its finding's")

    def test_the_owners_sentence_names_their_passage(self):
        owners = self.sentence(fixture.OWNERS)
        [passage] = owners["from"]
        self.assertEqual((passage["kind"], passage["by"], passage["section"]), ("passage", "owner", "discussion"))
        self.assertRegex(passage["id"], r"^P[1-9][0-9]*$")

    def test_the_objectives_are_listed_with_their_status_so_a_parked_one_shows_grey(self):
        self.assertEqual([(row["id"], row["status"]) for row in self.read()["objectives"]], [("O1", "open"), ("O2", "parked")])

    def test_each_part_carries_its_alternatives_the_one_it_holds_marked(self):
        [title] = [block for block in self.read()["blocks"] if block["type"] == "part" and block["part"] == "title"]
        self.assertEqual([(item["name"], item["text"], item["current"]) for item in title["alternatives"]],
                         [("title-1", fixture.TITLE, True), ("title-2", fixture.ALTERNATIVE, False)])
        self.assertEqual(title["path"], "research/paper/title.md")


class FigureTest(ReadingCase):
    def test_a_main_text_figure_follows_the_results_with_its_figure_result(self):
        blocks = self.read()["blocks"]
        [figure] = [block for block in blocks if block["type"] == "figure"]
        self.assertEqual(blocks[blocks.index(figure) - 1]["part"], "results")
        self.assertEqual(blocks[blocks.index(figure) + 1]["part"], "discussion")
        self.assertEqual((figure["id"], figure["result"], figure["objectives"], figure["image"], figure["status"]),
                         ("F1", "R1", ["O1"], "research/paper/figures/F1/F1.png", "verified"))
        self.assertEqual(figure["caption"], "**The column lifts every seed.** Paired AUROC with and without the column, one line per seed.")
        self.assertEqual(figure["script"], "figures/paper-r1-main/final/F1.py")
        self.assertEqual([(item["path"], item["run"]) for item in figure["data"]], [("analysis/E2/paired.json", "t12-a1")])
        self.assertEqual([(item["rank"], item["chart_type"], item["png"]) for item in figure["candidates"]],
                         [(1, "paired lines", "figures/paper-r1-main/candidates/c1.png"), (2, "box by arm", None)])
        self.assertEqual([(check["id"], check["pass"]) for check in figure["checks"]], [("fonts_embedded", True), ("min_font_size", True)])
        self.assertEqual((figure["honesty"]["verdict"], figure["honesty"]["findings"][0]["text"]), ("pass", fixture.HONESTY_FINDING))
        self.assertEqual((figure["check"], figure["source"]), ("passed", "result"))

    def test_a_failed_machine_check_fails_the_figure_under_the_check_lens(self):
        path = self.project / "figures" / fixture.FIGURE_ID / "figure_result.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        result["checks"][1].update({"pass": False, "detail": "the smallest text is 4 pt"})
        path.write_text(json.dumps(result), encoding="utf-8")
        [figure] = [block for block in self.read()["blocks"] if block["type"] == "figure"]
        self.assertEqual(figure["check"], "failed")


class ItemTest(ReadingCase):
    def test_a_sentence_id_and_a_figure_id_are_item_ids_and_open_the_reading_view(self):
        self.assertTrue(dashboard_views.ITEM_ID.match("results.s12"))
        self.assertTrue(dashboard_views.ITEM_ID.match("F1"))
        self.assertFalse(dashboard_views.ITEM_ID.match("supplement.s1"))
        self.assertFalse(dashboard_views.ITEM_ID.match("results.s0"))
        item = self.api("/items/results.s1").json
        self.assertEqual((item["kind"], item["view"], item["id"], item["path"]), ("sentence", "paper", "results.s1", "research/paper/results.md"))
        self.assertTrue(item["title"].startswith("Over 20 paired seeds"))
        figure = self.api("/items/F1").json
        self.assertEqual((figure["kind"], figure["view"], figure["path"]), ("figure", "paper", "research/paper/figures/F1/F1.png"))

    def test_a_sentence_the_version_no_longer_holds_is_not_found(self):
        self.assertEqual(self.api("/items/results.s99").status, 404)
        self.assertEqual(self.api("/items/F2").status, 404)

    def test_the_chat_takes_a_sentence_id_as_the_item_open(self):
        record = chat.post(self.project, "This is wrong: the gain is per seed.", view="paper", item="results.s12")
        self.assertEqual(record["item"], "results.s12")


class PollTest(ReadingCase):
    def test_an_unchanged_paper_answers_304_and_a_part_or_a_verdict_moves_the_tag(self):
        first = self.api("/paper/read")
        self.assertEqual(self.api("/paper/read", {"If-None-Match": first.etag}).status, 304)
        self.book.write_markdown("paper/discussion.md", fixture.TEXTS["discussion"] + "\nThe owner's own line.\n")
        second = self.api("/paper/read", {"If-None-Match": first.etag})
        self.assertEqual(second.status, 200)
        fixture._verdict(self.book, fixture.claim_subject(fixture.PINNED), "claim_support", True)
        self.assertEqual(self.api("/paper/read", {"If-None-Match": second.etag}).status, 200)

    def test_the_tag_moves_with_the_claim_classes_a_dossier_and_a_file_a_tag_reads(self):
        for change in (
                lambda: self.book.write_json(provenance.CLAIMS_CACHE, {"schema_version": 1, "classes": {}}),
                lambda: (self.project / "research" / "refs" / "paper-a" / "dossier.json").write_text(
                    (self.project / "research" / "refs" / "paper-a" / "dossier.json").read_text(encoding="utf-8") + "\n", encoding="utf-8"),
                lambda: (self.project / "tests" / "test_train.py").write_text(fixture.TEST_TRAIN + "# moved\n", encoding="utf-8")):
            before = self.api("/paper/read")
            change()
            self.assertEqual(self.api("/paper/read", {"If-None-Match": before.etag}).status, 200)

    def test_an_unreadable_manifest_still_shows_the_text_and_says_why_its_tags_hold_nothing(self):
        (self.project / "research" / "manifest.json").write_text("{not json", encoding="utf-8")
        view = self.read()
        self.assertTrue(any(problem.startswith("manifest.json") for problem in view["problems"]), view["problems"])
        gain = self.sentence(fixture.GAIN, view)
        self.assertEqual((gain["source"], gain["tags"][0]["held"]), ("result", []))

    def test_a_project_with_no_composed_paper_answers_an_empty_version_that_says_why(self):
        (self.project / "research" / "paper" / "paper.json").unlink()
        view = self.read()
        self.assertEqual((view["version"], view["blocks"]), (None, []))
        self.assertIn("No paper is composed yet", view["line"])
