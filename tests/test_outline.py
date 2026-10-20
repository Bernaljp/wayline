"""The outline (Implementation Decision 17; ticket 104).

The seam is the ledger over a temporary project: objectives, findings, passages, inherited passages, concerns, and the
repeated-claims record go in through the ledger calls their own tickets built, and what is asserted is what lands in
`research/OUTLINE.md`, `research/outline.json`, the journal, the section files, and the batches. An owner's edit is made
by editing the rendered file and rendering again. The embedding model runs through the tool runner's recordings
(`fixtures/outline/recorded/embeddings.json`, BAAI/bge-base-en-v1.5's vectors for the headings the suite embeds,
recorded live by `fixtures/outline/record.py`).
"""

import io
import json
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.projects import ProjectTestCase, open_goal
from tests.test_consolidation import FILM, MERGED, ConsolidationCase
from tests.test_consolidation import answer as consolidation_answer
from tests.test_stop_rule import StopRuleCase
from wayline import cli, objectives, outline, results, sections
from wayline import project as projects
from wayline.ledger import Ledger
from wayline.tools import ToolOutput, Tools

ROOT = Path(__file__).resolve().parent.parent
RECORDED = ROOT / "fixtures" / "outline" / "recorded" / "embeddings.json"

NOISE = "How does noise change the fit?"
DEGREE = "Which polynomial degree fits best?"
TRANSFER = "Does the model transfer to new data?"
STABLE = "Is the solver stable?"


class Embedder:
    """The tool runner answering `embed.py` from the recordings: the vector the live model gave each heading."""

    def __init__(self):
        self.calls = []
        self.table = json.loads(RECORDED.read_text(encoding="utf-8"))

    def __call__(self, argv, cwd=None, timeout=None, env=None):
        argv = [str(part) for part in argv]
        self.calls.append(argv)
        if len(argv) != 4 or not argv[1].endswith("embed.py"):
            return ToolOutput(127, b"", b"not recorded")
        texts = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
        missing = [text for text in texts if text not in self.table]
        if missing:
            return ToolOutput(1, b"", ("nothing recorded for %r" % missing[0]).encode())
        return ToolOutput(0, json.dumps({"model": Path(argv[2]).name, "vectors": [self.table[text] for text in texts]}).encode(), b"")


class OutlineCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "outline-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"rmse": 0.12, "error": 0.3}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)
        self.numbers = iter(range(1, 1000))

    # --- the records, through the ledger calls their tickets built ---------------------------------------------

    def objective(self, text, status="open", answer=None):
        found = objectives.add_objective(self.project, text)[0]
        if status != "open":
            objectives.change_objective(self.project, found["id"], status, "owner", answer=answer)
        return found["id"]

    def finding(self, heading, text="The error rises with the noise.", objectives_=(), replaces=None, evidence=None, negative=False):
        identifier = "t2-a1-f%d" % next(self.numbers)
        record = {"id": identifier, "ticket": 2, "text": text, "provenance": ["results/summary.json#rmse"], "negative": negative,
                  "heading": heading, "replaces": replaces, "objectives": list(objectives_)}
        if evidence:
            record["evidence"] = evidence
        return sections.file_finding(self.ledger, record)

    def passage(self, section, heading, text, by="t3-a1", objectives_=()):
        return sections.add_passage(self.ledger, section, heading, text, by=by, objectives=objectives_)

    def inherited(self, heading, text, doc):
        return sections.add_passage(self.ledger, "results", heading, text, by="document:D1", doc=doc, standing="unchecked")

    def first(self, identifier):
        """The critic's memo marking one objective `first`: the question the others wait on."""
        rows = [{"id": item["id"], "verdict": "reachable", "reasoning": "within reach", "revised_target": None,
                 "first": item["id"] == identifier} for item in objectives.read_objectives(self.project)
                if item["status"] in ("open", "parked")]
        self.ledger.write_json("position.json", {"objectives": rows})

    def concerns(self, *items):
        self.ledger.write_json("concerns.json", {"concerns": [dict({
            "sources": [{"critique": "D2", "locator": "D2#p%d" % index, "text": item.pop("said")}], "targets": [], "place": None,
            "objectives": [], "status": "open", "answer": None, "reason": None, "proposed": None, "returned": None,
            "sorted_by": "owner"}, id="K%d" % index, **item) for index, item in enumerate(items, start=1)], "split": []},
            schema="concern")

    def contradiction(self, first, second, heading):
        self.ledger.write_json("repeats.json", {"read": [first, second], "pending": [], "pairs": [{
            "a": first, "b": second, "found_by": ["consistency"], "similarity": None, "label": "contradicting",
            "outcome": "contradiction", "kept": None, "text": None, "passage": None, "why": "they disagree on the noise",
            "lost": None, "added": [], "flag": False, "results": [heading], "batch": None, "item": None,
            "at": "2026-10-20T00:00:00.000Z"}]}, schema="repeats")

    def plots(self, *entries):
        self.ledger.write_json("plots.json", {"plots": [dict(entry) for entry in entries]})

    # --- what is read back ----------------------------------------------------------------------------------------

    def render(self, **kwargs):
        outline.render_outline(self.project, **kwargs)
        return self.text()

    def text(self):
        return (self.project / "research" / "OUTLINE.md").read_text(encoding="utf-8")

    def body(self):
        return self.text().split("\n", 1)[1]

    def part(self, title):
        """One `## ` part of the rendered outline, its title line included."""
        found = re.search(r"(?ms)^## %s\n.*?(?=^## |\Z)" % re.escape(title), self.body())
        self.assertIsNotNone(found, "no part %r in:\n%s" % (title, self.body()))
        return found.group(0)

    def titles(self):
        return re.findall(r"(?m)^## (.+)$", self.body())

    def record(self):
        return json.loads((self.project / "research" / "outline.json").read_text(encoding="utf-8"))

    def events(self, name):
        return [event["payload"] for event in self.ledger.read_events()[0] if event["event"] == name]

    def edit(self, change):
        """Edit the rendered file as the owner would, and render again."""
        path = self.project / "research" / "OUTLINE.md"
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
        return self.render()

    def section(self, name):
        return (self.project / "research" / "sections" / ("%s.md" % name)).read_text(encoding="utf-8")


class Project(OutlineCase):
    """A start midway with four objectives, five results, inherited Results, concerns, and a contradiction.

    O1 noise (open), O2 degree (open, a goal, the critic's `first`), O3 transfer (parked), O4 stability (answered).
    R1 and R2 serve O1 and sit close; R3 serves O2 with two headline plots; R4 serves none; R5 serves O1 and O2.
    "Earlier noise study" holds two inherited claims, one decided by R1; "Old SINDy cases" one no objective checks.
    """

    def setUp(self):
        super().setUp()
        self.o1 = self.objective(NOISE)
        self.o2 = open_goal(self.project, DEGREE, metric="rmse", direction="down", target=0.1)["id"]
        self.o3 = self.objective(TRANSFER, status="parked", answer="later")
        self.o4 = self.objective(STABLE, status="answered", answer="It is stable on every split.")
        self.first(self.o2)
        self.passage("introduction", "State of the art", "Polynomial fits are standard.")
        self.passage("introduction", "The gap", "Nobody measured the noise.")
        self.claim = self.inherited("Earlier noise study", "Noise inflates the error.", "D1#p1.s1")["id"]
        self.other = self.inherited("Earlier noise study", "Noise leaves the degree alone.", "D1#p1.s2")["id"]
        self.sindy = self.inherited("Old SINDy cases", "SINDy recovers the cubic.", "D1#p2.s1")["id"]
        self.concerns({"said": "Show the noise effect.", "targets": [self.claim, self.other], "place": "objectives",
                       "objectives": [self.o1]},
                      {"said": "Cite the older fits.", "place": "order"})
        self.contradiction(self.claim, self.other, "Earlier noise study")
        self.finding("Noise sensitivity of the fit", objectives_=[self.o1], replaces=self.claim, evidence="supports")
        self.finding("Noise robustness of the fit", objectives_=[self.o1], negative=True, text="The fit holds at low noise.")
        self.finding("The best polynomial degree", objectives_=[self.o2], text="Degree three fits best.")
        self.finding("The best polynomial degree", objectives_=[self.o2], text="Degree four overfits.")
        self.finding("Runtime of the solver", text="The solver runs in a second.")
        self.finding("Degree under noise", objectives_=[self.o2, self.o1], text="The best degree falls with the noise.")
        self.plots({"id": "R3.1", "result": "R3", "headline": True, "status": "current"},
                   {"id": "R3.2", "result": "R3", "headline": True, "status": "current"},
                   {"id": "R3.3", "result": "R3", "headline": False, "status": "current"})
        self.passage("discussion", "What stability means", "The solver is stable.", by="objective:%s" % self.o4)
        self.passage("methods", "Data", "We fit synthetic polynomials.")


class RenderTest(Project):
    def test_code_renders_the_outline_in_its_order_from_the_records(self):
        self.render()
        self.assertTrue(self.text().startswith("<!-- wayline:render {"), "a render stamp on the first line, as the sections carry")
        self.assertEqual(self.titles(), ["Storyline", "Gaps", "Introduction", "Results", "Discussion", "Methods", "Supplement",
                                         "Cut", "Proposed, not settled", "For the order"])

    def test_the_storyline_gives_the_objectives_in_outline_order_with_status_results_standing_and_answer(self):
        self.render()
        storyline = self.part("Storyline")
        lines = re.findall(r"(?m)^- (O\d) \((\w+)\)", storyline)
        self.assertEqual(lines, [("O2", "open"), ("O1", "open"), ("O4", "answered"), ("O3", "parked")],
                         "the critic's first leads, then by id; the parked come last, as future work")
        self.assertIn("R3 supported", storyline)
        self.assertIn("R2 negative", storyline)
        self.assertIn("It is stable on every split.", storyline)

    def test_introduction_lists_its_headings_then_the_objectives_as_the_papers_questions(self):
        self.render()
        introduction = self.part("Introduction")
        self.assertLess(introduction.index('- "State of the art"'), introduction.index('- "The gap"'))
        questions = introduction.split("### The paper's questions", 1)[1]
        self.assertEqual(re.findall(r"(?m)^- (O\d) ", questions), ["O2", "O1", "O4"])

    def test_results_group_by_objective_with_the_critics_first_leading(self):
        self.render()
        part = self.part("Results")
        subsections = re.findall(r"(?m)^### (.+)$", part)
        self.assertEqual(subsections, ["O2 %s" % DEGREE, "O1 %s" % NOISE, "O4 %s" % STABLE, "Beyond the objectives",
                                       "Inherited, checked by no objective"])
        o2 = part.split("### O2", 1)[1].split("### O1", 1)[0]
        o1 = part.split("### O1", 1)[1].split("### O4", 1)[0]
        self.assertEqual(re.findall(r"(?m)^- (R\d)\b", o2), ["R3", "R5"])
        self.assertEqual(re.findall(r"(?m)^- (R\d)\b", o1), ["R1", "R2"], "R5 sits under its first objective")
        self.assertIn("- see R5 under O2", o1, "with a pointer from the second")
        self.assertIn('- Inherited "Earlier noise study"', o1, "an inherited heading its objective checks, through the concern")
        beyond = part.split("### Beyond the objectives", 1)[1]
        self.assertRegex(beyond, r'(?m)^- R4 "Runtime of the solver"')
        self.assertIn('- Inherited "Old SINDy cases"', part.split("### Inherited, checked by no objective", 1)[1])

    def test_each_result_line_carries_its_id_heading_standing_counts_plots_concerns_claims_contradictions_and_measure(self):
        self.render()
        part = self.part("Results")
        r3 = re.search(r"(?m)^- R3 .*$", part).group(0)
        self.assertIn('"The best polynomial degree"', r3)
        self.assertIn("supported", r3)
        self.assertIn("2 findings", r3)
        self.assertIn("2 headline plots (R3.1, R3.2)", r3)
        self.assertIn("measure `rmse` down to 0.1", r3)
        r1 = re.search(r"(?m)^- R1 .*$", part).group(0)
        self.assertIn("concerns K1", r1)
        self.assertIn("decides %s (supports)" % self.claim, r1)
        self.assertIn("resolves %s+%s" % (self.claim, self.other), r1)
        self.assertIn("measure none", r1)
        r2 = re.search(r"(?m)^- R2 .*$", part).group(0)
        self.assertIn("negative", r2)
        self.assertIn("no headline plot", r2)

    def test_discussion_lists_each_answered_objectives_passage_and_the_parked_objectives_as_future_work(self):
        self.render()
        discussion = self.part("Discussion")
        self.assertRegex(discussion, r'(?m)^- "What stability means" .*answers O4')
        future = discussion.split("### Future work", 1)[1]
        self.assertEqual(re.findall(r"(?m)^- (O\d) ", future), ["O3"])

    def test_methods_supplement_cut_proposed_and_for_the_order(self):
        self.render()
        self.assertIn('- "Data"', self.part("Methods"))
        self.assertIn("Nothing placed here.", self.part("Supplement"))
        self.assertIn("Nothing placed here.", self.part("Cut"))
        self.assertIn('Inherited "Old SINDy cases"', self.part("Proposed, not settled"))
        order = self.part("For the order")
        self.assertIn("K2", order)
        self.assertIn("Cite the older fits.", order)
        self.assertNotIn("K1", order)

    def test_the_gaps_name_what_holds_nothing_yet(self):
        self.render()
        gaps = self.part("Gaps")
        self.assertIn("O4", gaps, "an answered objective with no result holds nothing in Results")
        self.assertNotIn("O1", gaps)
        self.assertNotIn("O2", gaps)

    def test_a_render_that_changes_nothing_writes_nothing(self):
        self.render()
        path = self.project / "research" / "OUTLINE.md"
        before = path.stat().st_mtime_ns
        self.assertFalse(outline.render_outline(self.project))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_the_outline_has_no_figures(self):
        self.render()
        self.assertNotRegex(self.body(), r"(?i)\bfigure\b|\]\(.*\.(png|svg)\)")


class CompleteTest(OutlineCase):
    def complete(self):
        o1 = self.objective(NOISE)
        self.passage("introduction", "State of the art", "Polynomial fits are standard.")
        self.finding("Noise sensitivity of the fit", objectives_=[o1])
        self.passage("discussion", "What the noise does", "Noise inflates the error.")
        self.passage("methods", "Data", "We fit synthetic polynomials.")

    def test_the_gaps_list_is_empty_when_every_main_text_line_holds_something(self):
        self.complete()
        self.render()
        self.assertIn("Nothing: every line of the main text holds something.", self.part("Gaps"))

    def test_a_heading_the_owner_added_with_no_passage_is_a_gap_until_one_arrives(self):
        self.complete()
        outline.add_heading(self.project, "discussion", "Limitations")
        self.assertIn('Discussion: "Limitations" holds no passage yet.', self.part("Gaps"))
        self.passage("discussion", "Limitations", "The fits assume Gaussian noise.")
        self.render()
        self.assertIn("Nothing: every line of the main text holds something.", self.part("Gaps"))


class VenueTest(Project):
    def test_a_named_venue_maps_its_required_structure_to_the_sections_by_word_matching(self):
        self.render()
        self.assertFalse([name for name in self.titles() if name.startswith("Venue")], "no venue block while none is named")
        self.ledger.append_event("paper_started", {"venue": "nature-methods"})
        self.render()
        title = next(name for name in self.titles() if name.startswith("Venue"))
        self.assertEqual(self.titles().index(title), self.titles().index("Methods") + 1)
        venue = self.part(title)
        self.assertIn("- Online Methods: Methods", venue)
        self.assertIn("- Results: Results", venue)
        self.assertIn("- Abstract: made at the order", venue)


class OwnerEditTest(Project):
    """Each kind of owner edit, made by editing the rendered file and rendering again."""

    def test_a_line_moved_within_its_part_is_the_owners_order_and_survives_the_next_render(self):
        self.render()
        self.edit(lambda text: text.replace('- "State of the art" (1 passage)\n- "The gap" (1 passage)',
                                            '- "The gap" (1 passage)\n- "State of the art" (1 passage)'))
        introduction = self.part("Introduction")
        self.assertLess(introduction.index('"The gap"'), introduction.index('"State of the art"'))
        self.assertEqual(self.record()["groups"]["introduction"], ["introduction:The gap", "introduction:State of the art"])
        moved = self.events("outline")
        self.assertEqual([(event["action"], event["item"], event["to"], event["by"]) for event in moved],
                         [("moved", "introduction:The gap", "introduction", "owner")], "of two swapped lines, the one moved up")
        self.render()
        self.assertEqual(len(self.events("outline")), 1, "a render with no edit takes nothing in")
        body = self.section("introduction")
        self.assertLess(body.index("## The gap"), body.index("## State of the art"), "the section follows the outline")

    def test_a_result_moved_to_another_part_and_a_subsection_moved_up(self):
        self.render()

        def change(text):
            r2 = re.search(r"(?m)^- R2 .*\n", text).group(0)
            text = text.replace(r2, "").replace("### Beyond the objectives\n\n", "### Beyond the objectives\n\n" + r2)
            o1 = re.search(r"(?ms)^### O1 .*?(?=^### O4)", text).group(0)
            return text.replace(o1, "").replace("### O2 ", o1 + "### O2 ", 1)
        self.edit(change)
        part = self.part("Results")
        self.assertEqual(re.findall(r"(?m)^### (O\d)", part), ["O1", "O2", "O4"])
        self.assertEqual(re.findall(r"(?m)^- (R\d)\b", part.split("### Beyond the objectives", 1)[1]), ["R2", "R4"])
        self.assertEqual(self.record()["groups"]["objectives"], ["O1", "O2", "O4"])
        events = [(event["action"], event["item"], event["to"]) for event in self.events("outline")]
        self.assertIn(("moved", "R2", "results:beyond"), events)
        self.assertIn(("moved", "O1", "objectives"), events)
        body = self.section("results")
        self.assertLess(body.index("## Noise sensitivity of the fit"), body.index("## The best polynomial degree"))

    def test_a_line_placed_under_supplement_or_cut(self):
        self.render()

        def change(text):
            r2 = re.search(r"(?m)^- R2 .*\n", text).group(0)
            data = '- "Data" (1 passage)\n'
            text = text.replace(r2, "").replace(data, "")
            text = text.replace("## Supplement\n\nNothing placed here.\n", "## Supplement\n\n" + r2)
            return text.replace("## Cut\n\nNothing placed here.\n", "## Cut\n\n" + data)
        self.edit(change)
        self.assertRegex(self.part("Supplement"), r"(?m)^- R2 ")
        self.assertIn('- Methods: "Data"', self.part("Cut"))
        self.assertNotRegex(self.part("Results"), r"(?m)^- R2 ")
        record = self.record()
        self.assertEqual(record["groups"]["supplement"], ["R2"])
        self.assertEqual(record["groups"]["cut"], ["methods:Data"])
        events = [(event["action"], event["item"], event["to"]) for event in self.events("outline")]
        self.assertEqual(sorted(events), [("placed", "R2", "supplement"), ("placed", "methods:Data", "cut")])

    def test_a_note_line_under_a_line_is_kept_and_rendered_under_it(self):
        self.render()
        self.edit(lambda text: re.sub(r"(?m)^(- R1 .*)$", r"\1\n  Note: lead with this result.", text))
        self.assertIn("  Note: lead with this result.", self.part("Results"))
        self.assertEqual(self.record()["notes"], {"R1": "lead with this result."})
        self.assertEqual([(event["action"], event["item"], event["note"]) for event in self.events("outline")],
                         [("noted", "R1", "lead with this result.")])
        self.edit(lambda text: text.replace("  Note: lead with this result.\n", ""))
        self.assertEqual(self.record()["notes"], {}, "a note taken out of the file is taken away")

    def test_a_heading_added_to_introduction_discussion_or_methods(self):
        self.render()
        self.edit(lambda text: text.replace('- "The gap" (1 passage)\n', '- "The gap" (1 passage)\n- Why now\n')
                  .replace("### Future work", "- Limitations\n\n### Future work"))
        self.assertIn('- "Why now" (yours; nothing yet)', self.part("Introduction"))
        self.assertIn('- "Limitations" (yours; nothing yet)', self.part("Discussion"))
        self.assertEqual(self.record()["added"], [{"section": "introduction", "heading": "Why now"},
                                                  {"section": "discussion", "heading": "Limitations"}])
        events = [(event["action"], event["item"]) for event in self.events("outline")]
        self.assertIn(("added", "introduction:Why now"), events)
        self.assertIn(("added", "discussion:Limitations"), events)
        self.assertIn('Introduction: "Why now" holds no passage yet.', self.part("Gaps"))

    def test_a_heading_holding_quotes_reads_back_whole(self):
        self.passage("methods", 'The "fast" solver', "We use least squares.")
        self.render()
        self.edit(lambda text: text.replace('- "Data" (1 passage)\n- "The "fast" solver" (1 passage)',
                                            '- "The "fast" solver" (1 passage)\n- "Data" (1 passage)'))
        self.assertEqual(self.record()["groups"]["methods"], ['methods:The "fast" solver', "methods:Data"])
        self.assertEqual(self.record()["added"], [], "no heading was added")

    def test_a_note_written_under_one_of_an_objectives_lines_is_its_note(self):
        outline.note(self.project, "O1", "the noise story comes first.")
        self.edit(lambda text: re.sub(r"(?m)^(- O1 \(open\) .*)$", r"\1\n  Note: keep it to two results.", text))
        self.assertEqual(self.record()["notes"], {"O1": "keep it to two results."},
                         "the note that changed wins over the one still printed under the subsection")

    def test_an_edit_that_takes_nothing_in_is_written_over_with_every_line(self):
        self.render()
        self.edit(lambda text: text.replace(re.search(r"(?m)^- R3 .*\n", text).group(0), "") + "\nSome prose of mine.\n")
        self.assertRegex(self.part("Results"), r"(?m)^- R3 ", "a line missing from the file is not removed, and comes back")
        self.assertNotIn("Some prose of mine.", self.text())
        self.assertEqual(self.events("outline"), [])

    def test_a_line_pasted_into_a_part_it_cannot_stand_in_stays_where_code_puts_it(self):
        self.render()
        self.edit(lambda text: text.replace("### The paper's questions", re.search(r"(?m)^- R3 .*$", text).group(0)
                                            + "\n\n### The paper's questions"))
        self.assertNotIn("introduction", self.record()["groups"] if (self.project / "research" / "outline.json").exists() else {})
        self.assertNotRegex(self.part("Introduction"), r"(?m)^- R3 ")
        self.assertRegex(self.part("Results"), r"(?m)^- R3 ")

    def test_a_parked_objectives_note_survives_an_edit_of_the_file(self):
        outline.note(self.project, "O1", "the noise story comes first.")
        objectives.change_objective(self.project, self.o1, "parked", "owner", answer="later")
        self.render()
        self.edit(lambda text: re.sub(r"(?m)^(- R3 .*)$", r"\1\n  Note: lead with this.", text))
        self.assertEqual(self.record()["notes"], {"O1": "the noise story comes first.", "R3": "lead with this."})

    def test_lines_that_arrived_since_the_stamp_are_never_read_as_removed(self):
        self.render()
        text = self.text()
        self.finding("Noise under heavy tails", objectives_=[self.o1], text="Heavy tails double the error.")
        self.passage("methods", "Solver", "We use least squares.")
        path = self.project / "research" / "OUTLINE.md"
        path.write_text(text.replace('- "Data" (1 passage)', '- "Data" (1 passage)\n  Note: say which seeds.'), encoding="utf-8")
        self.render()
        self.assertRegex(self.part("Results"), r'(?m)^- R6 "Noise under heavy tails"')
        self.assertIn('"Solver"', self.part("Methods"))
        self.assertEqual([event["action"] for event in self.events("outline")], ["noted"], "nothing else was taken from the edit")

    def test_new_lines_go_after_the_placed_ones_marked_new(self):
        self.render()

        def change(text):
            r1 = re.search(r"(?m)^- R1 .*\n", text).group(0)
            return text.replace(r1, "").replace("- see R5 under O2", r1 + "- see R5 under O2")
        self.edit(change)
        self.assertEqual(self.record()["groups"]["results:O1"], ["R2", "results:Earlier noise study", "R1"])
        self.finding("A noise floor", objectives_=[self.o1], text="Below a floor the noise does nothing.")
        self.render()
        o1 = self.part("Results").split("### O1", 1)[1].split("### O4", 1)[0]
        self.assertEqual(re.findall(r"(?m)^- (R\d|Inherited)", o1), ["R2", "Inherited", "R1", "R6"])
        self.assertRegex(o1, r"(?m)^- R6 .*\(new\)$")
        self.assertNotRegex(o1, r"(?m)^- R1 .*\(new\)$")


class VerbTest(Project):
    """The conversation's outline verb makes the same changes as a file edit and journals the same `outline` event."""

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["outline", *args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def parity(self, change, *args):
        """The record and the events after a file edit, then after the same change through the verb on a fresh outline."""
        self.render()
        before = self.text()
        self.edit(change)
        by_edit = (self.record(), [dict(event) for event in self.events("outline")])
        (self.project / "research" / "outline.json").unlink()
        (self.project / "research" / "OUTLINE.md").write_text(before, encoding="utf-8")
        journal = self.project / "research" / "journal.jsonl"
        journal.write_text("".join(line + "\n" for line in journal.read_text(encoding="utf-8").splitlines()
                                   if '"event": "outline"' not in line and '"event":"outline"' not in line), encoding="utf-8")
        code, out, err = self.run_cli(*args)
        self.assertEqual(code, 0, err)
        return by_edit, (self.record(), self.events("outline"))

    def test_a_move_by_the_verb_is_the_move_by_an_edit(self):
        edit, verb = self.parity(lambda text: text.replace('- "State of the art" (1 passage)\n- "The gap" (1 passage)',
                                                           '- "The gap" (1 passage)\n- "State of the art" (1 passage)'),
                                 "move", "The gap", "--before", "State of the art")
        self.assertEqual(edit, verb)

    def test_a_placement_by_the_verb_is_the_placement_by_an_edit(self):
        def change(text):
            r2 = re.search(r"(?m)^- R2 .*\n", text).group(0)
            return text.replace(r2, "").replace("## Supplement\n\nNothing placed here.\n", "## Supplement\n\n" + r2)
        edit, verb = self.parity(change, "place", "R2", "supplement")
        self.assertEqual(edit, verb)

    def test_a_note_by_the_verb_is_the_note_by_an_edit(self):
        edit, verb = self.parity(lambda text: re.sub(r"(?m)^(- R1 .*)$", r"\1\n  Note: lead with this result.", text),
                                 "note", "R1", "lead with this result.")
        self.assertEqual(edit, verb)

    def test_a_heading_by_the_verb_is_the_heading_by_an_edit(self):
        edit, verb = self.parity(lambda text: text.replace("### Future work", "- Limitations\n\n### Future work"),
                                 "heading", "discussion", "Limitations")
        self.assertEqual(edit, verb)

    def test_place_main_takes_a_line_back_where_code_puts_it(self):
        outline.place(self.project, "R2", "supplement")
        outline.place(self.project, "R2", "main")
        self.render()
        self.assertRegex(self.part("Results").split("### O1", 1)[1], r"(?m)^- R2 ")
        self.assertEqual([(event["action"], event["to"]) for event in self.events("outline")],
                         [("placed", "supplement"), ("placed", "main")])

    def test_the_verb_refuses_what_the_outline_does_not_show_and_a_new_results_subsection(self):
        code, _, err = self.run_cli("note", "R9", "a note")
        self.assertEqual(code, 2)
        self.assertIn("R9", err)
        code, _, err = self.run_cli("move", "methods:Data", "--to", "introduction")
        self.assertEqual(code, 2)
        code, _, err = self.run_cli("move", "O2", "--before", "O2")
        self.assertEqual(code, 2, err)
        self.assertIn("itself", err)
        with self.assertRaises(outline.OutlineError) as caught:
            outline.add_heading(self.project, "results", "Transfer to field data")
        self.assertIn("objective", str(caught.exception))

    def test_show_prints_the_outline(self):
        code, out, err = self.run_cli("show")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("# Outline"))

    def test_a_new_results_subsection_in_the_file_is_offered_as_an_objective(self):
        self.render()
        self.edit(lambda text: text.replace("### Beyond the objectives", "### Transfer to field data\n\n### Beyond the objectives"))
        self.assertIn('"Transfer to field data", is a new question that needs new work: open it as an objective',
                      self.part("Proposed, not settled"))
        self.objective("Transfer to field data")
        self.render()
        self.assertNotIn("Transfer to field data", self.part("Proposed, not settled"))


class SurvivingTest(Project):
    """The owner's placements survive a new result, a merge, and a reframe; a note follows its item."""

    def test_placements_survive_a_new_result(self):
        outline.place(self.project, "R2", "supplement")
        outline.move(self.project, "R3", after="R5")
        self.finding("Degree and runtime", objectives_=[self.o2], text="Higher degrees run longer.")
        self.render()
        o2 = self.part("Results").split("### O2", 1)[1].split("### O1", 1)[0]
        self.assertEqual(re.findall(r"(?m)^- (R\d)\b", o2), ["R5", "R3", "R6"])
        self.assertRegex(self.part("Supplement"), r"(?m)^- R2 ")

    def test_a_merge_lists_the_merged_results_placement_once_and_carries_its_note(self):
        outline.place(self.project, "R2", "supplement")
        outline.note(self.project, "R2", "the robustness half")
        outline.move(self.project, "R1", to="O1")
        results.merge(self.project, "R2", "R1")
        self.render()
        gone = self.part("Gone since you placed them")
        self.assertIn("R2, placed in Supplement: merged into R1.", gone)
        self.assertNotRegex(self.part("Supplement"), r"(?m)^- R2 ")
        self.assertIn("  Note: the robustness half", self.part("Results").split("- R1 ", 1)[1].split("\n- ", 1)[0])
        self.assertEqual(self.record()["gone"], [{"item": "R2", "group": "supplement", "why": "merged into R1"}])
        self.assertIn(("gone", "R2", "code"), [(event["action"], event["item"], event["by"]) for event in self.events("outline")])
        self.render()
        self.assertEqual(self.part("Gone since you placed them").count("R2"), 1, "listed once")
        outline.note(self.project, "R3", "keep it short")
        self.assertNotIn("Gone since you placed them", self.titles(), "the list clears at the owner's next change")

    def test_a_reframe_moves_the_objectives_place_placements_and_note_to_its_successor(self):
        outline.move(self.project, "O1", before="O2")
        outline.move(self.project, "R2", before="R1")
        outline.note(self.project, "O1", "the paper's lead question")
        o6 = self.objective("How does noise of each kind change the fit?")
        objectives.change_objective(self.project, self.o1, "reframed", "owner", answer="split by noise kind", reframed_as=o6)
        self.render()
        part = self.part("Results")
        self.assertEqual(re.findall(r"(?m)^### (O\d)", part), [o6, "O2", "O4"], "the successor takes the reframed one's place")
        o6_part = part.split("### %s" % o6, 1)[1].split("### O2", 1)[0]
        self.assertIn("Note: the paper's lead question", o6_part)
        self.assertEqual(re.findall(r"(?m)^- (R\d)\b", o6_part), ["R2", "R1", "R5"],
                         "R5 sat under O1, which led, when the owner ordered O1's results")
        self.assertNotIn("Gone since you placed them", self.titles())


class SectionsFollowTest(Project):
    def test_a_heading_placed_under_supplement_or_cut_renders_at_the_end_of_its_section_under_a_marker(self):
        outline.place(self.project, "methods:Data", "cut")
        self.passage("methods", "Solver", "We use least squares.")
        outline.place(self.project, "R1", "supplement")
        methods = self.section("methods")
        self.assertLess(methods.index("## Solver"), methods.index(sections.PLACED_MARKS["cut"]))
        self.assertLess(methods.index(sections.PLACED_MARKS["cut"]), methods.index("## Data"))
        results_body = self.section("results")
        self.assertLess(results_body.index("## Old SINDy cases"), results_body.index(sections.PLACED_MARKS["supplement"]))
        self.assertLess(results_body.index(sections.PLACED_MARKS["supplement"]), results_body.index("## Noise sensitivity of the fit"))

    def test_the_marker_is_never_read_back_as_the_owners_text(self):
        outline.place(self.project, "methods:Data", "cut")
        before = len(sections.read_passages(self.project))
        path = self.project / "research" / "sections" / "methods.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n## Seeds\n\nWe used five seeds.\n", encoding="utf-8")
        sections.render_section(self.ledger, "methods")
        added = sections.read_passages(self.project)[before:]
        self.assertEqual([(item["heading"], item["text"], item["by"]) for item in added], [("Seeds", "We used five seeds.", "owner")])


class MergeTest(Project):
    """Merge proposals from the local embedding model over the headings of the results under one objective."""

    def setUp(self):
        super().setUp()
        self.embedder = Embedder()
        model = self.temp / "models" / "BAAI--bge-base-en-v1.5"
        model.mkdir(parents=True)
        self.model_tools = Tools(root=self.temp / "embedding-tools", record={"tools": {"embedding-model": {
            "executable": sys.executable, "version": "a5beb1e3e68b", "env": {"HF_HUB_OFFLINE": "1"}, "route": "huggingface",
            "model": "BAAI/bge-base-en-v1.5", "path": str(model)}}})

    def propose(self):
        return outline.propose_merges(self.project, run=self.embedder, tools=self.model_tools)

    def test_close_headings_under_one_objective_are_one_batch_of_take_or_decline_items_with_no_tokens(self):
        from wayline import batches, worker
        with worker.use_fake() as fake:
            batch = self.propose()
            self.assertEqual(fake.calls, [], "the embedding model spends no tokens")
        self.assertEqual(len(self.embedder.calls), 1, "one run of the model for every heading")
        self.assertEqual(batch["kind"], "outline_proposals")
        self.assertEqual([(item["ref"], item["marks"], item["default"]) for item in batch["items"]],
                         [("R1+R2", ["take", "decline"], "decline")], "only the close pair, under one objective")
        self.assertIn("O1", batch["items"][0]["text"])
        self.render()
        self.assertIn("Merge R2 into R1", self.part("Proposed, not settled"))
        self.assertIn("%s, item 1: take or decline" % batch["id"], self.part("Proposed, not settled"))
        self.assertIsNone(self.propose(), "an unchanged set of results is not embedded again")
        self.assertEqual(len(self.embedder.calls), 1)
        self.assertEqual(len(batches.read_batches(self.project)), 1)

    def test_taking_a_proposal_merges_the_results_and_declining_leaves_them(self):
        from wayline import batches
        batch = self.propose()
        batches.mark(self.project, batch["id"], 1, "take")
        self.assertEqual(outline.take_marks(self.project), [("R2", "R1")])
        merged = [event for event in self.ledger.read_events()[0] if event["event"] == "result"
                  and event["payload"]["action"] == "merged"]
        self.assertEqual([(event["payload"]["id"], event["payload"]["into"], event["payload"]["by"]) for event in merged],
                         [("R2", "R1", "owner")])
        self.assertEqual(outline.take_marks(self.project), [], "taken once")
        self.render()
        self.assertNotIn("Merge R2 into R1", self.part("Proposed, not settled"))
        self.assertNotRegex(self.part("Results"), r"(?m)^- R2 ")

    def test_a_decline_merges_nothing_and_the_pair_is_not_proposed_again(self):
        from wayline import batches
        batch = self.propose()
        batches.mark(self.project, batch["id"], 1, "decline")
        self.assertEqual(outline.take_marks(self.project), [])
        self.finding("Noise under heavy tails", objectives_=[self.o1], text="Heavy tails double the error.")
        self.assertIsNone(self.propose(), "the declined pair is not proposed again")
        self.assertEqual(len(self.embedder.calls), 2, "a new result is a new set to embed")

    def test_the_account_waits_on_the_open_proposals_as_one_line_with_their_count(self):
        from wayline import account
        self.propose()
        waiting = account.account_view(self.project)["sections"]["Waiting on you"]
        lines = [line for line in waiting if "outline" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("2 open proposals", lines[0], "the merge and the inherited heading no objective checks")
        self.assertIn("research/OUTLINE.md", lines[0])

    def test_a_batch_that_could_not_be_opened_leaves_the_pairs_to_propose_again(self):
        from unittest import mock
        from wayline import batches
        with mock.patch.object(batches, "open_batch", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.propose()
        self.assertIsNotNone(self.propose(), "the set was not recorded as checked")

    def test_a_model_that_is_not_recorded_is_said_and_proposes_nothing(self):
        from wayline import repeats
        with self.assertRaises(repeats.RepeatsError):
            outline.propose_merges(self.project, run=self.embedder, tools=Tools(root=self.temp / "none", record={"tools": {}}))
        self.assertEqual(self.embedder.calls, [])


class RenderPassTest(Project):
    """The outline renders in the same pass as the general report and the account, and takes the marks first."""

    def test_the_general_reports_render_renders_the_outline_and_takes_a_merge_first(self):
        from wayline import batches, provenance
        batch = batches.open_batch(self.project, "outline_proposals", "Results whose headings sit close: merge them?",
                                   [{"ref": "R1+R2", "text": "Merge R2 into R1.", "default": "decline"}])
        batches.mark(self.project, batch["id"], 1, "take")
        (self.project / "research" / "OUTLINE.md").unlink()
        provenance.render_report(self.project, offline=True)
        self.assertTrue((self.project / "research" / "OUTLINE.md").is_file())
        self.assertNotRegex(self.part("Results"), r"(?m)^- R2 ")
        report = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        self.assertNotIn("Noise robustness of the fit", report, "the report renders after the merge, under R1's heading")

    def test_init_lays_the_outline_out(self):
        fresh = self.temp / "fresh-project"
        projects.init_project(fresh, harness_root=self.fake_harness(name="harness-fresh"), git=False)
        text = (fresh / "research" / "OUTLINE.md").read_text(encoding="utf-8")
        self.assertIn("# Outline", text)
        self.assertIn("No objective is recorded yet.", text)


class PackTest(Project):
    def test_a_workers_pack_holds_its_objectives_outline_entry_with_the_owners_notes(self):
        outline.note(self.project, "R1", "lead with this result.")
        outline.note(self.project, "O1", "the noise story comes first in Results.")
        text = outline.pack_text(self.project, [self.o1])
        self.assertIn("## O1 %s" % NOISE, text)
        self.assertIn('- R1 "Noise sensitivity of the fit"', text)
        self.assertIn("  Note: lead with this result.", text)
        self.assertIn("Note: the noise story comes first in Results.", text)
        self.assertNotIn("## O2", text)
        self.assertLess(len(text), 1200, "a few hundred characters")
        self.assertEqual(outline.pack_text(self.project, []), "")

    def test_a_results_heading_of_the_owners_moved_under_an_objective_is_packed_as_a_heading(self):
        sections.add_owners_passage(self.project, "results", "Old cases", "We looked at the old cases.")
        outline.move(self.project, "results:Old cases", to="O1")
        text = outline.pack_text(self.project, [self.o1])
        self.assertIn('- Results: "Old cases" (1 passage; yours)', text)
        self.assertNotIn('Inherited "Old cases"', text)


class CriticFirstTest(unittest.TestCase):
    """The critic's memo marks the question the others wait on `first`, which leads the outline's Results."""

    def test_a_row_may_mark_one_open_objective_first(self):
        from tests.test_position import OBJECTIVES, memo
        from wayline import position
        from wayline.jsonschema import load_schema, validate
        value = memo()
        value["objectives"][1]["first"] = True
        self.assertEqual(validate(value, load_schema("position")), [])
        self.assertEqual(position.check_memo(value, "exploratory", OBJECTIVES), [])
        value["objectives"][0]["first"] = True
        self.assertIn("the objectives O1 and O2 are both marked first; mark at most one",
                      position.check_memo(value, "exploratory", OBJECTIVES))
        parked = [dict(OBJECTIVES[0]), dict(OBJECTIVES[1], status="parked")]
        value["objectives"][0]["first"] = False
        self.assertIn("O2 is parked, and only an open objective is marked first",
                      position.check_memo(value, "exploratory", parked))


class ConsolidationFollowsTest(ConsolidationCase):
    def test_a_consolidation_reads_the_section_in_the_outlines_order_with_its_notes(self):
        outline.move(self.project, "Data", before="Fitting")
        outline.note(self.project, "methods:Data", "name the camera.")
        code, _, err = self.run_verb("methods", "--yes", script=[
            consolidation_answer(("Data", FILM, ["P3"]), ("Fitting", MERGED, ["P1", "P2"]))])
        self.assertEqual(code, 0, err)
        [call] = self.calls
        prompt = call.request.prompt
        self.assertLess(prompt.index("## P3"), prompt.index("## P1"))
        self.assertIn("The outline's note on this heading: name the camera.", prompt)


class ConductorTest(StopRuleCase):
    """The one-ticket fixture past setup, its ticket serving O1."""

    def setUp(self):
        super().setUp()
        from tests.projects import open_objective
        open_objective(self.project, "Does the hello file say hello?")
        self.set_harness(stop_when="frontier")
        self.ledger.append_event("phase", {"from": "P4", "to": "P5"})
        outline.note(self.project, "O1", "say it plainly in Results.")
        self.serve("O1")

    def test_a_workers_prompt_carries_its_objectives_outline_entry_with_the_owners_notes(self):
        from tests.test_conductor import done, patch
        self.conduct((done(), patch()), waves=1)
        (worker_call,) = [call for call in self.calls if call.request.role == "coder"]
        self.assertIn("# The outline of this ticket's objectives", worker_call.request.prompt)
        self.assertIn("Note: say it plainly in Results.", worker_call.request.prompt)

    def test_every_wave_renders_the_outline(self):
        from tests.test_conductor import done, patch
        (self.project / "research" / "OUTLINE.md").unlink()
        self.conduct((done(), patch()), waves=1)
        self.assertIn("Does the hello file say hello?", (self.project / "research" / "OUTLINE.md").read_text(encoding="utf-8"))
