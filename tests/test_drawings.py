"""Drawings and plots (Implementation Decision 17; ticket 100).

The seams are the ledger over a temporary project (findings filed through `sections.file_finding`, drawings opened,
accepted, and failed through `wayline.drawings`, asserting on `research/plots.json`, `research/drawings/`, the tickets,
and the journal), sample generators the clean room reruns and the checks read, the fake launcher scripting the plotter
under the conductor, and replayed journals for the rest points under each autonomy.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import io

from tests import machine
from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_conductor import ConductorCase, done, drive
from tests.test_documents import MIDWAY
from tests.test_inherited import InheritedCase
from tests.test_results import file
from wayline import drawings, results, sections, tickets, worker
from wayline.conductor import Conductor
from wayline import project as projects
from wayline.ledger import Ledger
from wayline.objectives import add_objective

R1 = "Do the products raise the AUROC?"
R2 = "What did the literature say?"
R3 = "Does the loss fall?"

SAMPLES = FIXTURES_DIR / "plots" / "samples"

# A sample generator: the standard library alone, so the suite needs no plotting library. It reads the result's artifact
# where the project keeps it, writes each plot's SVG (a sample a real library wrote) and a small PNG, each table's CSV,
# and every number it quotes into numbers.json, all beside itself, as the plotter's protocol asks.
GENERATOR = '''import json, os, random, struct, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("WAYLINE_PROJECT", ".")
with open(os.path.join(ROOT, "results", "summary.json"), encoding="utf-8") as handle:
    data = json.load(handle)
{seed}
PLOTS = {plots!r}
TABLES = {tables!r}
def png(path, shade):
    rows = b"".join(b"\\x00" + bytes([shade]) * 8 for _ in range(8))
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    with open(path, "wb") as handle:
        handle.write(b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
for name, svg in PLOTS.items():
    with open(os.path.join(HERE, name + ".svg"), "w", encoding="utf-8") as handle:
        handle.write(svg)
    png(os.path.join(HERE, name + ".png"), random.randint(0, 255))
for name, rows in TABLES.items():
    with open(os.path.join(HERE, name + ".csv"), "w", encoding="utf-8") as handle:
        handle.write("\\n".join(",".join(str(cell) for cell in row) for row in rows) + "\\n")
numbers = {{"auroc": data["auroc"], "loss": data["loss"], "seeds": 3}}
{extra}
with open(os.path.join(HERE, "numbers.json"), "w", encoding="utf-8") as handle:
    json.dump(numbers, handle, sort_keys=True)
'''


def sample_svg(name):
    return (SAMPLES / (name + ".svg")).read_text(encoding="utf-8")


def draw_into(folder, project, plots=None, tables=None, seeded=True, extra="", **draft):
    """What the plotter leaves in its drawing directory: the generator, run once, and the draft beside its outputs."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    plots = {"auroc_box": "matplotlib-clean"} if plots is None else plots
    tables = {"auroc_table": [["seed", "auroc"], [1, 0.71]]} if tables is None else tables
    script = GENERATOR.format(seed="random.seed(7)" if seeded else "", plots={name: sample_svg(svg) for name, svg in plots.items()},
                              tables=tables, extra=extra)
    (folder / "draw.py").write_text(script, encoding="utf-8")
    done = subprocess.run([sys.executable, "-I", str(folder / "draw.py")], env=dict(os.environ, WAYLINE_PROJECT=str(project)),
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError("the sample generator failed: %s" % done.stderr)
    value = {"script": "draw.py", "numbers": "numbers.json", "inputs": ["results/summary.json"],
             "plots": [explained(name) for name in plots], "tables": [
                 {"redraws": None, "csv": name + ".csv", "data_view": "AUROC per seed", "inputs": ["results/summary.json"],
                  "purpose": "The values behind the box.", "data": "One row per seed.", "shows": "The seed reaches 0.71."}
                 for name in tables],
             "synthesis": "The AUROC holds at 0.71 across 3 seeds.", "headline": "The rise holds.",
             "can_infer": ["The products help on this split."], "cannot_infer": ["Whether it holds on other species."],
             "open_questions": ["Does the loss track the AUROC?"], "left_out": [], "earlier_figures": []}
    value.update(draft)
    (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
    return folder


def explained(png, svg=None, redraws=None, headline=False, shows="The AUROC sits at 0.71 across 3 seeds."):
    return {"redraws": redraws, "chart_type": "box plot", "index_entries": ["box-py"], "data_view": "AUROC by seed",
            "png": png + ".png", "svg": (svg or png) + ".svg", "inputs": ["results/summary.json"],
            "purpose": "Does the AUROC hold across seeds?", "data": "The held-out AUROC of each seed, from results/summary.json.",
            "shows": shows, "headline": headline}


class DrawingsCase(ProjectTestCase):
    def ticket(self, identifier):
        return {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[identifier]

    def close(self, identifier, status):
        fields = self.ticket(identifier)
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))
        tickets.write_ticket(self.ledger, dict(fields, status=status), body)

    def setUp(self):
        super().setUp()
        self.project = self.temp / "drawings-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71, "loss": 0.25}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)

    def events(self, name):
        return [event for event in self.ledger.read_events()[0] if event["event"] == name]

    def tickets(self, kind=drawings.KIND):
        return [fields for fields in tickets.read_tickets(self.project) if fields["kind"] == kind]


class DrawnCase(DrawingsCase):
    """A drawing opened over R1 and drawn by a sample generator in a stand-in worktree, as the plotter would leave it."""

    def setUp(self):
        super().setUp()
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)
        [self.identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.worktree = self.temp / "worktree"
        self.worktree.mkdir()

    def draw(self, plots=None, tables=None, seeded=True, extra="", **draft):
        """Write the generator into the drawing directory, run it as the plotter would, and write the draft beside it."""
        fields = self.ticket(self.identifier)
        return draw_into(self.worktree / fields["touches"][0], self.project, plots, tables, seeded, extra, **draft)

    def check(self, final=False):
        from wayline.project import policy_for
        return drawings.check(self.project, self.ticket(self.identifier), self.worktree, final=final,
                              policy=policy_for(self.project), python=sys.executable)


class CheckTest(DrawnCase):
    def test_a_clean_drawing_passes_its_rerun_and_every_check(self):
        self.draw()
        checked = self.check()
        self.assertEqual(checked.problems, [])
        self.assertTrue(checked.passed, checked.tail())
        [plot] = checked.items[:1]
        ids = [outcome["id"] for outcome in plot["checks"]]
        self.assertEqual(ids, ["min_font_pt", "text_overlap", "palette", "generator_clean", "regenerates", "provenance",
                               "rotated_text", "axis_label_length", "stacked_titles", "heatmap_cell_labels", "flat_summary_mark",
                               "numbers"])
        self.assertTrue(all(outcome["pass"] is not False for outcome in plot["checks"]), plot["checks"])
        self.assertTrue(next(outcome for outcome in plot["checks"] if outcome["id"] == "regenerates")["pass"])

    def test_a_plot_failing_a_readability_check_fails_the_drawing_until_the_repair_and_is_then_left_out(self):
        self.draw(plots={"auroc_box": "matplotlib-clean", "seed_bars": "matplotlib-rotated-ticks"})
        checked = self.check()
        self.assertFalse(checked.passed)
        self.assertIn("seed_bars.png", checked.tail())
        self.assertIn("rotated_text", checked.tail())
        repaired = self.check(final=True)
        self.assertTrue(repaired.passed, repaired.tail())
        self.assertEqual([entry["what"] for entry in repaired.left_out], ["seed_bars.png (new)"])
        self.assertIn("rotated_text", repaired.left_out[0]["reason"])

    def test_a_number_numbers_json_does_not_hold_fails_its_plot(self):
        self.draw(plots={"auroc_box": "matplotlib-clean"})
        draft_path = self.worktree / "drawings" / "R1-1" / drawings.DRAFT
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        draft["plots"][0]["shows"] = "The AUROC reaches 0.93 on one seed."
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        checked = self.check(final=True)
        self.assertEqual([entry["what"] for entry in checked.left_out], ["auroc_box.png (new)"])
        self.assertIn("0.93", checked.left_out[0]["reason"])

    def test_a_number_in_the_synthesis_numbers_json_does_not_hold_fails_the_drawing_itself(self):
        self.draw(synthesis="The AUROC reaches 0.93.")
        checked = self.check(final=True)
        self.assertFalse(checked.passed)
        self.assertTrue(any("0.93" in problem for problem in checked.problems), checked.problems)

    def test_a_script_that_does_not_rerun_alike_fails_the_drawing(self):
        self.draw(extra='numbers["drawn"] = random.random()', seeded=False)
        checked = self.check(final=True)
        self.assertFalse(checked.passed)
        self.assertTrue(any("numbers.json" in problem for problem in checked.problems), checked.problems)

    def test_more_than_four_headline_plots_fail_the_drawing(self):
        names = {"p%d" % number: "matplotlib-clean" for number in range(1, 6)}
        self.draw(plots=names)
        draft_path = self.worktree / "drawings" / "R1-1" / drawings.DRAFT
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        for plot in draft["plots"]:
            plot["headline"] = True
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        checked = self.check(final=True)
        self.assertTrue(any("headline" in problem for problem in checked.problems), checked.problems)

    def test_a_check_that_cannot_run_is_listed_as_not_run(self):
        folder = self.draw()
        (folder / "draw.R").write_text("# an R script\n", encoding="utf-8")
        draft = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        draft["script"] = "draw.R"
        (folder / drawings.DRAFT).write_text(json.dumps(draft), encoding="utf-8")
        checked = self.check()
        outcome = next(item for item in checked.items[0]["checks"] if item["id"] == "generator_clean")
        self.assertIsNone(outcome["pass"])
        self.assertTrue(outcome["not_run"])
        self.assertIn("Python only", outcome["detail"])


class AcceptTest(DrawnCase):
    def accept(self, final=True):
        checked = self.check(final=final)
        self.assertTrue(checked.passed, checked.tail())
        return drawings.accept(self.project, self.ticket(self.identifier), checked)

    def again(self, finding="t%d-a1-f1"):
        """The next drawing of R1, once a new finding changed it."""
        self.close(self.identifier, "done")
        number = 10 + len(drawings.read_records(self.project, "R1"))
        file(self.ledger, finding % number, "The rise holds at 0.71 on split %d." % number, R1)
        [self.identifier] = drawings.open_drawings(self.project, drawings.RUN_END)

    def plots(self):
        return {plot["id"]: plot for plot in drawings.read_plots(self.project)["plots"]}

    def test_an_accepted_drawing_gives_each_plot_and_table_an_id_and_writes_both_records(self):
        self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "seaborn-clean"})
        draft = self.worktree / "drawings" / "R1-1" / drawings.DRAFT
        value = json.loads(draft.read_text(encoding="utf-8"))
        value["plots"][0]["headline"] = True
        draft.write_text(json.dumps(value), encoding="utf-8")
        record = self.accept()
        plots = self.plots()
        self.assertEqual(sorted(plots), ["R1.1", "R1.2", "R1.T1"])
        self.assertEqual((plots["R1.1"]["kind"], plots["R1.1"]["status"], plots["R1.1"]["headline"], plots["R1.1"]["drawings"]),
                         ("plot", "current", True, ["R1-1"]))
        self.assertEqual((plots["R1.T1"]["kind"], plots["R1.T1"]["chart_type"]), ("table", None))
        self.assertEqual(plots["R1.2"]["data_view"], "AUROC by seed")
        self.assertEqual(record["status"], "accepted")
        self.assertEqual([plot["id"] for plot in record["plots"]], ["R1.1", "R1.2"])
        self.assertEqual(record["plots"][0]["png"], "drawings/R1-1/auroc_box.png", "relative to the project")
        self.assertEqual(record["script"], "drawings/R1-1/draw.py")
        self.assertEqual(drawings.read_records(self.project, "R1")[-1], record)
        event = self.events("drawing")[-1]["payload"]
        self.assertEqual((event["outcome"], event["plots"], event["left_out"]), ("accepted", ["R1.1", "R1.2", "R1.T1"], []))
        from wayline import batches
        batch = batches.read_batch(self.project, record["batch"])
        self.assertEqual((batch["kind"], [item["ref"] for item in batch["items"]]), ("plots", ["R1.1", "R1.2", "R1.T1"]))
        self.assertEqual(batch["items"][0]["marks"], ["keep", "maybe", "drop"])

    def test_ids_persist_across_drawings_retire_when_left_out_and_are_never_reused(self):
        self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "seaborn-clean"})
        self.accept()
        self.again()
        folder = self.draw(plots={"auroc_box": "matplotlib-clean", "loss_line": "seaborn-clean"}, tables={})
        value = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        value["plots"][0]["redraws"] = "R1.1"
        (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
        record = self.accept()
        plots = self.plots()
        self.assertEqual([plot["id"] for plot in record["plots"]], ["R1.1", "R1.3"], "R1.2 retired, its id never reused")
        self.assertEqual((plots["R1.1"]["status"], plots["R1.1"]["drawings"]), ("current", ["R1-1", "R1-2"]))
        self.assertEqual((plots["R1.2"]["status"], plots["R1.T1"]["status"]), ("retired", "retired"))
        self.assertEqual(sorted(record["retired"]), ["R1.2", "R1.T1"])

    def test_a_plot_left_out_at_the_repair_is_listed_in_the_record_and_the_event(self):
        self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "seaborn-clean"})
        self.accept()
        self.again()
        folder = self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "matplotlib-rotated-ticks"}, tables={})
        value = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        value["plots"][0]["redraws"], value["plots"][1]["redraws"] = "R1.1", "R1.2"
        (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
        record = self.accept()
        self.assertEqual([plot["id"] for plot in record["plots"]], ["R1.1"])
        self.assertEqual([entry["what"] for entry in record["left_out"]], ["R1.2"])
        self.assertIn("rotated_text", record["left_out"][0]["reason"])
        self.assertEqual(self.events("drawing")[-1]["payload"]["left_out"], record["left_out"])

    def test_keep_is_never_retired_by_a_drawing_alone_drop_retires_and_a_note_reaches_the_next_brief(self):
        from wayline import batches
        from wayline.project import policy_for
        self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "seaborn-clean", "seed_strip": "seaborn-clean"})
        first = self.accept()
        batches.mark(self.project, first["batch"], 1, "keep")
        batches.mark(self.project, first["batch"], 2, "drop")
        batches.mark(self.project, first["batch"], 3, "maybe", note="Colour the strip by split.")
        self.assertEqual(drawings.due(self.project), [], "no mark starts a drawing")
        self.again()
        text = drawings.brief(self.project, self.ticket(self.identifier), policy_for(self.project))
        self.assertIn("Colour the strip by split.", text)
        self.assertIn("R1.2", text)
        folder = self.draw(plots={"strip": "seaborn-clean"}, tables={})
        value = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        value["plots"][0]["redraws"] = "R1.3"
        (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
        record = self.accept()
        plots = self.plots()
        self.assertEqual((plots["R1.1"]["status"], plots["R1.1"]["mark"]), ("current", "keep"))
        self.assertEqual([(item["mark"], bool(item["acted"])) for item in batches.read_batch(self.project, first["batch"])["items"]][:3],
                         [("keep", True), ("drop", True), ("maybe", True)], "the next drawing took each mark: none changes now")
        self.assertEqual(record["carried"], ["R1.1"])
        self.assertEqual((plots["R1.2"]["status"], plots["R1.2"]["mark"]), ("retired", "drop"))
        self.assertEqual((plots["R1.3"]["status"], plots["R1.3"]["note"]), ("current", "Colour the strip by split."))

    def test_an_acceptance_that_fails_half_way_leaves_the_marks_changeable(self):
        from unittest import mock
        from wayline import batches
        self.draw()
        first = self.accept()
        batches.mark(self.project, first["batch"], 1, "keep", via="dashboard")
        self.again()
        self.draw(tables={})
        with mock.patch.object(batches, "open_batch", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.accept()
        item = batches.read_batch(self.project, first["batch"])["items"][0]
        self.assertEqual((item["mark"], item["acted"]), ("keep", None), "the drawing took no mark: it can still change")

    def test_a_redraw_that_fails_its_checks_leaves_the_plot_as_its_last_accepted_drawing_drew_it(self):
        self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "seaborn-clean"})
        self.accept()
        self.again()
        folder = self.draw(plots={"auroc_box": "matplotlib-clean", "seed_violin": "matplotlib-rotated-ticks"}, tables={})
        value = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        value["plots"][0]["redraws"], value["plots"][1]["redraws"] = "R1.1", "R1.2"
        (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
        record = self.accept()
        plots = self.plots()
        self.assertEqual([entry["what"] for entry in record["left_out"]], ["R1.2"])
        self.assertEqual((plots["R1.2"]["status"], plots["R1.2"]["drawings"]), ("current", ["R1-1"]))
        self.assertIn("R1.2", record["carried"])

    def test_a_drawing_whose_every_plot_fails_fails_as_a_whole(self):
        self.draw(plots={"seed_bars": "matplotlib-rotated-ticks"}, tables={})
        checked = self.check(final=True)
        self.assertFalse(checked.passed)
        self.assertTrue(any("no plot or table" in problem for problem in checked.problems), checked.problems)

    def test_a_dropped_plot_drawn_again_fails_the_drawing(self):
        from wayline import batches
        self.draw()
        first = self.accept()
        batches.mark(self.project, first["batch"], 1, "drop")
        self.again()
        folder = self.draw(tables={})
        value = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        value["plots"][0]["redraws"] = "R1.1"
        (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
        checked = self.check(final=True)
        self.assertTrue(any("dropped" in problem for problem in checked.problems), checked.problems)

    def test_a_drawing_that_still_fails_keeps_the_last_accepted_one(self):
        self.draw()
        self.accept()
        self.again()
        before = self.plots()
        record = drawings.fail(self.project, self.ticket(self.identifier), "its script did not rerun in the clean room")
        self.assertEqual((record["status"], record["reason"]), ("failed", "its script did not rerun in the clean room"))
        self.assertEqual(self.plots(), before)
        self.assertEqual(drawings.last_accepted(self.project, "R1")["version"], 1)
        event = self.events("drawing")[-1]["payload"]
        self.assertEqual((event["outcome"], event["version"], event["reason"]), ("failed", 2, "its script did not rerun in the clean room"))
        self.assertEqual(drawings.due(self.project), [], "a failed drawing is not drawn again until its result changes")


class EarlierFigureTest(InheritedCase):
    """An earlier figure of an inherited document goes to the drawing of the result whose finding replaces its claim."""

    def setUp(self):
        super().setUp()
        self.add(MIDWAY / "manuscript-v2.docx")
        self.deconstruct()
        self.ledger = Ledger(self.project)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71, "loss": 0.25}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)
        [claim] = [item for item in self.ours() if "(Figure 1)" in item["text"]]
        sections.file_finding(self.ledger, {"id": "t2-a1-f1", "ticket": 2, "text": "Larger colonies reach 0.71 only at dusk.",
                                            "provenance": ["results/summary.json#auroc"], "negative": False, "heading": "Results",
                                            "replaces": claim["id"], "objectives": [], "evidence": "narrows"})
        [self.identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.fields = {fields["id"]: fields for fields in tickets.read_tickets(self.project)}[self.identifier]

    def test_the_brief_hands_the_drawing_the_earlier_figure(self):
        from wayline.project import policy_for
        text = drawings.brief(self.project, self.fields, policy_for(self.project))
        self.assertIn("Earlier figures to answer", text)
        self.assertIn("Figure 1. Order parameter R against colony size, forty colonies.", text)

    def test_the_drawing_says_whether_it_agrees_or_fails(self):
        from wayline.project import policy_for
        worktree = self.temp / "worktree"
        folder = draw_into(worktree / self.fields["touches"][0], self.project)
        checked = drawings.check(self.project, self.fields, worktree, final=True, policy=policy_for(self.project), python=sys.executable)
        self.assertTrue(any("earlier figure" in problem for problem in checked.problems), checked.problems)
        [figure] = drawings.earlier_figures(self.project, results.read_results(self.project)[0])
        draft = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        draft["earlier_figures"] = [{"figure": figure["figure"], "plot": "auroc_box.png", "agrees": "disagrees",
                                     "note": "The rise holds only at dusk, where the earlier figure showed it at every hour."}]
        (folder / drawings.DRAFT).write_text(json.dumps(draft), encoding="utf-8")
        checked = drawings.check(self.project, self.fields, worktree, final=True, policy=policy_for(self.project), python=sys.executable)
        self.assertTrue(checked.passed, checked.tail())
        record = drawings.accept(self.project, self.fields, checked)
        self.assertEqual(record["earlier_figures"][0]["plot"], record["plots"][0]["id"])
        self.assertEqual(record["earlier_figures"][0]["agrees"], "disagrees")


class OwnersWordTest(DrawingsCase):
    def setUp(self):
        super().setUp()
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)
        file(self.ledger, "t3-a1-f1", "Earlier work found no effect.", R2, provenance=())

    def test_the_owners_word_draws_an_unchanged_result_again(self):
        [first] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.close(first, "done")
        self.assertEqual(drawings.due(self.project), [])
        second = drawings.draw_again(self.project, "R1")
        fields = self.ticket(second)
        self.assertEqual((fields["origin"], fields["proposed_by"]), ("drawing R1-2 at owner", "human"))
        self.assertEqual(self.events("drawing")[-1]["payload"]["rest"], "owner")

    def test_the_owners_word_is_refused_for_a_result_with_nothing_to_draw_or_a_drawing_under_way(self):
        with self.assertRaises(drawings.DrawingError) as raised:
            drawings.draw_again(self.project, "R2")
        self.assertIn("own evidence", str(raised.exception))
        with self.assertRaises(drawings.DrawingError):
            drawings.draw_again(self.project, "R9")
        drawings.draw_again(self.project, "R1")
        with self.assertRaises(drawings.DrawingError) as raised:
            drawings.draw_again(self.project, "R1")
        self.assertIn("under way", str(raised.exception))

    def test_the_conversation_says_it_with_wayline_result_draw(self):
        from contextlib import redirect_stdout
        from wayline import results
        printed = io.StringIO()
        with redirect_stdout(printed):
            code = results.result_command(["draw", "R1", "--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertIn("R1-1", printed.getvalue())
        self.assertEqual(len(self.tickets()), 1)


class PlotTagTest(DrawingsCase):
    def setUp(self):
        super().setUp()
        self.ledger.write_json("plots.json", {"schema_version": 1, "plots": [
            {"id": "R1.1", "result": "R1", "kind": "plot", "chart_type": "box plot", "index_entries": [], "data_view": "AUROC by seed",
             "status": "current", "headline": True, "mark": None, "note": None, "drawings": ["R1-1"]},
            {"id": "R1.2", "result": "R1", "kind": "plot", "chart_type": "violin plot", "index_entries": [], "data_view": "AUROC by seed",
             "status": "retired", "headline": False, "mark": "drop", "note": None, "drawings": ["R1-1"]}]}, schema="plots")

    def lint(self, text):
        from wayline import provenance
        return provenance.lint_passages(self.project, [{"id": "P1", "by": "owner", "text": text}], {}).problems

    def test_a_plot_tag_resolves_against_plots_json(self):
        self.assertEqual(self.lint("The AUROC holds across seeds ({plot:R1.1})."), [])

    def test_a_plot_tag_naming_no_plot_or_a_retired_one_fails(self):
        [unknown] = self.lint("The AUROC holds across seeds ({plot:R1.9}).")
        self.assertEqual((unknown["problem"], unknown["tag"]), ("unresolved_plot", "plot:R1.9"))
        self.assertIn("plots.json", unknown["detail"])
        [retired] = self.lint("The AUROC holds across seeds ({plot:R1.2}).")
        self.assertIn("retired", retired["detail"])
        [malformed] = self.lint("The AUROC holds across seeds ({plot:figure two}).")
        self.assertEqual(malformed["problem"], "unresolved_plot")


class DrawingRunCase(ConductorCase):
    """The conductor at rest points over the one-ticket fixture, its ticket done and one finding filed, the fake plotter
    drawing with a sample generator in the worktree the conductor made."""

    def setUp(self):
        super().setUp()
        fields = self.ticket(1)
        _, body = tickets.read_ticket(tickets.tickets_dir(self.project) / tickets.filename(fields))
        tickets.write_ticket(self.ledger, dict(fields, status="done"), body)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71, "loss": 0.25}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t1-a1", 1)
        file(self.ledger, "t1-a1-f1", "The products raise the AUROC to 0.71.", R1, ticket=1)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "the finding")

    def plotter(self, **drawing):
        """The fake plotter: the sample generator run in its worktree, committed, and a done result returned."""
        def respond(request, message):
            ticket = int(request.env["WAYLINE_TICKET"])
            touch = self.ticket(ticket)["touches"][0]
            draw_into(Path(request.cwd) / touch, self.project, **drawing)
            subprocess.run(["git", "-C", str(request.cwd), "add", "-A", touch], check=True, capture_output=True)
            # A resume that draws the same again has nothing new to commit.
            subprocess.run(["git", "-C", str(request.cwd), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m",
                            "ticket %d: the drawing" % ticket], capture_output=True)
            return done(ticket, summary="drew the result", outputs_written=[touch])
        return respond

    def run_drawings(self, *responses, before=None, waves=None):
        with worker.use_fake() as fake:
            for respond in responses:
                fake.script(respond=respond, role=drawings.ROLE)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.drawing_python = sys.executable
            if before is not None:
                before(self.conductor)
            results = []
            # A rest point opens its drawings at a wave's end, with nothing in flight: `drive` alone would stop there.
            while len(results) < (waves or 12) and not (results and results[-1].ended):
                results += drive(self.conductor, waves)
            self.calls = list(fake.calls)
        return results

    def launched(self):
        return [event["payload"] for event in self.events("ticket_launched")]


class DrawingRunTest(DrawingRunCase):
    def test_a_run_end_draws_the_changed_result_on_the_plotter_then_ends(self):
        results = self.run_drawings(self.plotter())
        [launch] = self.launched()
        self.assertEqual((launch["ticket"], launch["role"], launch["model"], launch["effort"]), (2, "plotter", "opus", "medium"))
        self.assertEqual(self.ticket(2)["kind"], "drawing")
        self.assertIn("# The drawing", self.calls[0].request.prompt, "the brief is in the prompt")
        self.assertIn("t1-a1-f1", self.calls[0].request.prompt)
        acceptance = [result for result in self.payload("acceptance")["results"] if result["cmd"] == drawings.DRAWING_CHECK]
        self.assertEqual(len(acceptance), 0, "the last acceptance is on main, where the drawing check does not run")
        worktree = [event["payload"] for event in self.events("acceptance") if event["payload"]["where"] == "worktree"][0]
        self.assertIn(drawings.DRAWING_CHECK, [result["cmd"] for result in worktree["results"]])
        record = drawings.read_records(self.project, "R1")[-1]
        self.assertEqual((record["status"], record["rest"]), ("accepted", "run_end"))
        self.assertTrue((self.project / "drawings" / "R1-1" / "auroc_box.svg").is_file(), "the drawing's artifacts are on main")
        self.assertEqual([plot["id"] for plot in drawings.read_plots(self.project)["plots"]], ["R1.1", "R1.T1"])
        self.assertTrue(results[-1].ended)
        self.assertEqual(self.payload("run_ended")["reason"], "frontier_empty")
        self.assertEqual(self.ticket(2)["status"], "done")

    def test_pacing_steps_the_plotter_down_to_sonnet_medium(self):
        self.run_drawings(self.plotter(), before=lambda conductor: conductor.simulate_step_down(3600))
        [launch] = self.launched()
        self.assertEqual((launch["model"], launch["effort"]), ("sonnet", "medium"))

    def test_a_failing_plot_gets_one_repair_resume_and_is_then_left_out(self):
        broken = {"auroc_box": "matplotlib-clean", "seed_bars": "matplotlib-rotated-ticks"}
        self.run_drawings(self.plotter(plots=broken), self.plotter(plots=broken))
        [resumed] = [event["payload"] for event in self.events("ticket_resumed")]
        self.assertEqual(resumed["reason"], "acceptance_failed")
        self.assertIn("rotated_text", self.calls[1].message)
        record = drawings.read_records(self.project, "R1")[-1]
        self.assertEqual(record["status"], "accepted")
        self.assertEqual([entry["what"] for entry in record["left_out"]], ["seed_bars.png (new)"])
        self.assertEqual([plot["id"] for plot in record["plots"]], ["R1.1"])
        account = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        runs = account[account.index("## Runs"):]
        self.assertIn("R1-1 accepted", runs)
        self.assertIn("left out seed_bars.png (new)", runs)
        self.assertIn("rotated_text", runs)

    def test_a_drawing_that_still_fails_keeps_the_last_accepted_one_with_no_tier_up_split_or_ask(self):
        wrong = dict(synthesis="The AUROC reaches 0.93.")
        results = self.run_drawings(self.plotter(**wrong), self.plotter(**wrong))
        self.assertEqual([event["payload"]["next"] for event in self.events("ticket_failed")], ["resume", "none"],
                         "the one repair resume, then no step")
        self.assertEqual(self.events("ticket_needs_human"), [])
        self.assertEqual(self.events("stall"), [], "a drawing closed with no step is no stall")
        self.assertEqual([event for event in self.events("decision_opened")], [])
        self.assertEqual(len(self.launched()), 1, "no tier up and no split launched another session")
        record = drawings.read_records(self.project, "R1")[-1]
        self.assertEqual(record["status"], "failed")
        self.assertIn("0.93", record["reason"])
        self.assertTrue(results[-1].ended)
        self.assertEqual(self.ticket(2)["status"], "failed")
        self.assertFalse(self.worktree(2).exists(), "a drawing closed with no step keeps no worktree")
        self.assertNotIn("ticket/2", self.branches())
        account = (self.project / "research" / "ACCOUNT.md").read_text(encoding="utf-8")
        runs = account[account.index("## Runs"):]
        self.assertIn("R1-1 failed", runs)
        self.assertIn("R1 keeps no accepted drawing yet", runs)


class NotServedTest(DrawingRunCase):
    def test_a_plotter_model_nobody_serves_fails_the_drawing_with_no_rung_held_and_no_ask(self):
        from tests.test_model_ran import not_served
        self.run_drawings(lambda request, message: not_served("opus"))
        self.assertEqual(self.payload("ticket_failed")["next"], "none")
        self.assertIn("model_not_served", self.payload("ticket_failed")["reason"])
        self.assertEqual(self.events("decision_opened"), [], "no rung to hold, and a drawing asks nobody")
        self.assertEqual(drawings.read_records(self.project, "R1")[-1]["status"], "failed")


class DrawingFindingTest(DrawingRunCase):
    def test_an_inference_of_a_drawing_is_a_finding_under_its_results_heading(self):
        drawn = self.plotter()

        def respond(request, message):
            envelope = drawn(request, message)
            envelope.structured_output["findings"] = [{
                "text": "Across the 3 seeds the AUROC never falls below 0.71.", "heading": "What the plots show",
                "provenance": "drawings/R1-1/numbers.json#auroc", "negative": False, "replaces": "t1-a1-f1"}]
            # Its number is one numbers.json computes, so it returns the Methods passage saying how (ticket 108).
            envelope.structured_output["passages"] = [{"section": "methods", "heading": "Drawing R1", "replaces": None,
                                                       "text": "The lowest AUROC is the minimum over the seeds' AUROC."}]
            return envelope

        self.run_drawings(respond)
        from wayline import sections as kept
        [finding] = [item for item in kept.read_findings(self.project) if item["ticket"] == 2]
        self.assertEqual((finding["heading"], finding["result"]), (R1, "R1"))
        self.assertIsNone(finding["replaces"], "a drawing is read-only on the research: its inference replaces no finding")
        self.assertIn("t1-a1-f1", [item["id"] for item in results.read_results(self.project)[0].current])
        self.assertEqual([result.id for result in results.read_results(self.project)], ["R1"])
        self.assertEqual(drawings.due(self.project), [], "a drawing's own finding does not make its result changed")


class ReplayTest(DrawingRunCase):
    def test_the_replayed_journal_of_a_drawing_that_still_failed_owes_no_step(self):
        from wayline import replay
        wrong = dict(synthesis="The AUROC reaches 0.93.")
        self.run_drawings(self.plotter(**wrong), self.plotter(**wrong))
        view = replay.View()
        replay.replay(self.events(), view)
        known = view.tickets[2]
        self.assertEqual((known.status, known.step, known.steps), ("failed", "none", ["resume", "none"]))
        conductor = Conductor(self.project, out=io.StringIO())
        conductor.drawing_python = sys.executable
        with worker.use_fake():  # nothing scripted: the run-end gates (ticket 103) reach no real backend
            conductor.wave()
        self.assertEqual(conductor._owed_steps(), [])
        self.assertEqual(len(self.events("ticket_launched")), 1, "a new conductor launches nothing for it")


class RestPointTest(DrawingRunCase):
    """The rest point an empty frontier is, under each autonomy, read back from the journal the run wrote."""

    def autonomy(self, level):
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["autonomy"] = level
        (self.project / "harness.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
        from wayline.decisions import open_decision
        open_decision(self.project, "Which split goes in the paper?", options=["A", "B"], human_only=True, blocking=None,
                      proposed_by="human", notify=lambda *args: None)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "autonomy %s" % level)

    def rest(self):
        return [event["payload"]["rest"] for event in self.events("drawing") if event["payload"]["outcome"] == "opened"]

    def test_under_checkpoints_a_run_coming_to_rest_on_the_owner_draws_at_a_checkpoint(self):
        self.autonomy("checkpoints")
        self.run_drawings(self.plotter())
        self.assertEqual(self.rest(), ["checkpoint"])
        self.assertEqual(drawings.read_records(self.project, "R1")[-1]["status"], "accepted")
        self.assertEqual(self.payload("run_ended")["reason"], "frontier_empty")

    def test_under_interactive_and_autonomous_the_same_rest_is_a_run_end(self):
        for level in ("interactive", "autonomous"):
            with self.subTest(autonomy=level):
                self.setUp()
                self.autonomy(level)
                self.run_drawings(self.plotter())
                self.assertEqual(self.rest(), ["run_end"])
                self.assertEqual(self.payload("run_ended")["reason"], "frontier_empty")

    def test_a_decision_holding_every_ticket_leaves_the_drawing_for_after_the_answer_and_the_run_pauses(self):
        from wayline.decisions import open_decision
        open_decision(self.project, "Stop everything?", options=["yes", "no"], human_only=True, blocking="all",
                      proposed_by="human", notify=lambda *args: None)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a decision holding all")
        results = self.run_drawings()
        self.assertTrue(results[-1].ended)
        self.assertEqual(self.payload("run_ended")["reason"], "frontier_empty")
        self.assertEqual(self.launched(), [])
        self.assertEqual([fields["status"] for fields in tickets.read_tickets(self.project) if fields["kind"] == "drawing"], ["open"],
                         "drawn once the owner's answer lets the frontier go on")

    def test_an_empty_frontier_the_decider_takes_is_no_rest_point(self):
        open_objective = add_objective(self.project, "Does the rise hold at dusk?")[0]["id"]
        self.autonomy("autonomous")
        self.run_drawings(waves=1)
        self.assertEqual(self.events("drawing"), [], "the run goes on with the decider: no drawing yet")
        self.assertTrue(any(open_objective in str(fields.get("origin")) for fields in tickets.read_tickets(self.project)
                            if fields["kind"] == "decision"))

    def test_an_end_of_the_stopping_rule_launches_only_the_drawings_and_ends_after_them(self):
        from wayline.objectives import change_objective
        add_objective(self.project, R1)
        file(self.ledger, "t1-a1-f2", "The rise is 0.71 on every seed.", R1, ticket=1, objectives=["O1"])
        change_objective(self.project, "O1", "answered", "owner", answer="Yes.", evidence=["res:t1-a1/results/summary.json#auroc"])
        other = dict(self.ticket(1), id=3, status="open", title="Write another file", touches=["other.txt"])
        tickets.write_ticket(self.ledger, other, "\nAnother.\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "an objective answered")
        self.run_drawings(self.plotter())
        self.assertEqual([launch["ticket"] for launch in self.launched()], [4], "the drawing alone, never ticket 3")
        self.assertEqual(self.rest(), ["run_end"])
        self.assertEqual(drawings.read_records(self.project, "R1")[-1]["status"], "accepted")
        self.assertEqual(self.payload("run_ended")["reason"], "objectives_closed")
        sequence = self.sequence()
        self.assertLess(sequence.index("drawing"), sequence.index("run_ended"))


MATPLOTLIB_GENERATOR = '''import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("WAYLINE_PROJECT", ".")
with open(os.path.join(ROOT, "results", "summary.json"), encoding="utf-8") as handle:
    data = json.load(handle)
seeds = [1, 2, 3]
values = [data["auroc"], data["auroc"] - 0.02, data["auroc"] + 0.01]
figure, axes = plt.subplots(figsize=(4, 3))
axes.plot(seeds, values, marker="o", color="#0072B2", label="held-out AUROC")
axes.set_xlabel("Seed")
axes.set_ylabel("AUROC")
axes.legend(frameon=False)
figure.tight_layout()
figure.savefig(os.path.join(HERE, "auroc_seeds.svg"))
figure.savefig(os.path.join(HERE, "auroc_seeds.png"), dpi=100)
with open(os.path.join(HERE, "numbers.json"), "w", encoding="utf-8") as handle:
    json.dump({"auroc": data["auroc"], "seeds": 3}, handle, sort_keys=True)
'''


def _has_matplotlib():
    return subprocess.run([sys.executable, "-c", "import matplotlib"], capture_output=True).returncode == 0


class RealLibraryTest(DrawnCase):
    """A drawing matplotlib really drew passes its rerun and every check: the checks read a real SVG without false alarms."""

    def test_a_clean_matplotlib_drawing_passes(self):
        if not _has_matplotlib():
            self.skipTest("this interpreter has no matplotlib, as on the suite's CI")
        folder = self.worktree / "drawings" / "R1-1"
        folder.mkdir(parents=True)
        (folder / "draw.py").write_text(MATPLOTLIB_GENERATOR, encoding="utf-8")
        done_run = subprocess.run([sys.executable, "-I", str(folder / "draw.py")], env=dict(os.environ, WAYLINE_PROJECT=str(self.project)),
                                  capture_output=True, text=True)
        self.assertEqual(done_run.returncode, 0, done_run.stderr)
        plot = explained("auroc_seeds", shows="Each of the 3 seeds sits near 0.71.")
        plot["chart_type"] = "line plot"
        draft = {"script": "draw.py", "numbers": "numbers.json", "inputs": ["results/summary.json"], "plots": [plot], "tables": [],
                 "synthesis": "The AUROC holds near 0.71 across 3 seeds.", "headline": "The rise holds.", "can_infer": [],
                 "cannot_infer": [], "open_questions": [], "left_out": [], "earlier_figures": []}
        (folder / drawings.DRAFT).write_text(json.dumps(draft), encoding="utf-8")
        checked = self.check()
        self.assertTrue(checked.passed, checked.tail())
        self.assertTrue(next(item for item in checked.items[0]["checks"] if item["id"] == "regenerates")["pass"])


class DueTest(DrawingsCase):
    def test_a_result_with_a_finding_from_the_projects_own_evidence_is_due(self):
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)
        file(self.ledger, "t3-a1-f1", "Earlier work found no effect.", R2, provenance=())
        self.assertEqual(drawings.due(self.project), ["R1"])

    def test_own_evidence_is_a_manifested_artifact_by_provenance_or_a_res_tag(self):
        manifested = {"results/summary.json"}
        self.assertTrue(drawings.own_evidence({"provenance": "results/summary.json#auroc", "text": "It is 0.71."}, manifested))
        self.assertTrue(drawings.own_evidence({"provenance": ["results/summary.json#auroc"], "text": "It is 0.71."}, manifested))
        self.assertTrue(drawings.own_evidence({"provenance": "", "text": "It is 0.71 {res:t2-a1/results/summary.json#auroc}."}, manifested))
        self.assertFalse(drawings.own_evidence({"provenance": "", "text": "Earlier work found it {ref:smith2020#abstract}."}, manifested))
        self.assertFalse(drawings.own_evidence({"provenance": "research/refs/smith2020/dossier.json#abstract", "text": "It is known."},
                                               manifested), "a dossier is no run's artifact")

    def test_a_result_whose_findings_cite_no_run_artifact_is_not_drawn(self):
        file(self.ledger, "t3-a1-f1", "Earlier work found no effect.", R2, provenance=("research/refs/smith2020/dossier.json#abstract",))
        self.assertEqual(drawings.due(self.project), [])

    def test_a_drawing_failed_in_an_earlier_run_is_drawn_again_at_the_next_runs_rest_point(self):
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v0", "autonomy": "checkpoints", "radius": "moderate", "pid": 1})
        [first] = drawings.open_drawings(self.project, drawings.RUN_END)
        drawings.fail(self.project, self.ticket(first), "its script did not rerun")
        self.close(first, "failed")
        self.assertEqual(drawings.due(self.project), [], "not again in the run it failed in")
        self.ledger.append_event("run_started", {"resume": False, "harness_tag": "v0", "autonomy": "checkpoints", "radius": "moderate", "pid": 2})
        self.assertEqual(drawings.due(self.project), ["R1"], "changed since its last accepted drawing, in a new run")

    def test_a_drawing_waiting_on_its_resume_is_still_under_way(self):
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)
        [first] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.close(first, "failed")
        self.ledger.append_event("ticket_failed", {"ticket": first, "attempt": 1, "reason": "it failed", "next": "resume"}, ticket=first)
        file(self.ledger, "t4-a1-f1", "The rise holds on split B at 0.71.", R1)
        self.assertEqual(drawings.due(self.project), [])
        with self.assertRaises(drawings.DrawingError):
            drawings.draw_again(self.project, "R1")

    def test_the_stopping_rules_results_come_first(self):
        add_objective(self.project, "Does the loss fall?")       # O1
        add_objective(self.project, "Does the AUROC rise?")      # O2
        harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
        harness["stop_when"] = ["O2"]
        (self.project / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
        file(self.ledger, "t2-a1-f1", "The loss stays at 0.25.", R3, objectives=["O1"], provenance=("results/summary.json#loss",))
        file(self.ledger, "t2-a1-f2", "The products raise the AUROC to 0.71.", R1, objectives=["O2"])
        self.assertEqual(drawings.due(self.project), ["R2", "R1"])


class OpenTest(DrawingsCase):
    def setUp(self):
        super().setUp()
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)

    def test_a_rest_point_opens_one_drawing_ticket_per_due_result_on_the_plotter(self):
        opened = drawings.open_drawings(self.project, drawings.RUN_END)
        [ticket] = self.tickets()
        self.assertEqual(opened, [ticket["id"]])
        self.assertEqual((ticket["role"], ticket["status"], ticket["proposed_by"]), ("plotter", "open", "conductor"))
        self.assertEqual(ticket["touches"], ["drawings/R1-1/"], "read-only on the research: its own drawing directory alone")
        self.assertEqual(ticket["resources"]["gpu"], 0, "CPU only")
        self.assertEqual(ticket["origin"], "drawing R1-1 at run_end")
        created = self.events("ticket_created")[-1]["payload"]
        self.assertEqual((created["kind"], created["proposed_by"]), ("drawing", "conductor"))
        drawn = self.events("drawing")[-1]["payload"]
        self.assertEqual((drawn["result"], drawn["version"], drawn["ticket"], drawn["rest"], drawn["outcome"]),
                         ("R1", 1, ticket["id"], "run_end", "opened"))
        record = drawings.read_records(self.project, "R1")[-1]
        self.assertEqual((record["status"], record["findings"]), ("open", ["t2-a1-f1"]))

    def test_a_drawing_in_progress_is_not_opened_again(self):
        drawings.open_drawings(self.project, drawings.RUN_END)
        self.assertEqual(drawings.open_drawings(self.project, drawings.CHECKPOINT), [])
        self.assertEqual(len(self.tickets()), 1)

    def test_a_result_changed_since_its_last_drawing_is_drawn_at_the_next_version(self):
        [first] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.close(first, "parked")
        self.assertEqual(drawings.due(self.project), [], "unchanged since the drawing that was opened over it")
        file(self.ledger, "t4-a1-f1", "The rise holds on split B at 0.71.", R1)
        [second] = drawings.open_drawings(self.project, drawings.RUN_END)
        self.assertEqual(self.ticket(second)["origin"], "drawing R1-2 at run_end")

    def test_the_planner_never_writes_a_drawing_ticket(self):
        from wayline.jsonschema import load_schema
        self.assertIn("drawing", load_schema("ticket")["$defs"]["kind"]["enum"])
        self.assertNotIn("drawing", load_schema("plan")["properties"]["tickets"]["items"]["properties"]["kind"]["enum"])



class PlotterTest(DrawingsCase):
    def test_the_plotter_runs_on_opus_medium_with_the_small_budget(self):
        from wayline.project import policy_for
        tier = drawings.tier(policy_for(self.project))
        self.assertEqual((tier.model, tier.effort, tier.max_turns, tier.max_minutes), ("opus", "medium", 40, 30))
        self.assertIsNone(tier.stepped_from)

    def test_pacing_steps_the_plotter_down_to_sonnet_medium(self):
        from wayline.project import policy_for
        tier = drawings.tier(policy_for(self.project), cheap=True)
        self.assertEqual((tier.model, tier.effort, tier.max_turns), ("sonnet", "medium", 40))
        self.assertEqual(tier.stepped_from, "opus medium")

    def test_the_role_is_read_only_with_no_job_and_its_prompt_carries_the_rules(self):
        from wayline import worker
        role = worker.read_role(drawings.ROLE)
        self.assertEqual(role.kinds, [], "code assigns the plotter; the librarian never does")
        self.assertNotIn("Bash(wayline job add*)", role.allowed_tools)
        self.assertIn("Bash(wayline job add*)", role.disallowed_tools)
        self.assertIn("WebFetch", role.disallowed_tools)
        words = " ".join((role.system_prompt + role.protocol).split()).lower()
        for rule in ("one of its own terms", "every mark is explained", "cpu only", "never the project's own code", "open question",
                     "near duplicate", "no order", "collapsed", "readable", "numbers.json", "purpose", "what it shows",
                     "at most 20 plots and 4 tables", "at most 4 headline plots", "no minimum"):
            self.assertIn(rule, words)

    def test_the_brief_carries_every_input_of_a_drawing(self):
        from wayline.project import policy_for
        add_objective(self.project, "Do the products raise the AUROC?")
        self.ledger.write_json("spec.json", {"title": "Fireflies", "question": "Do products help?", "data": [],
                                             "summary": "Fireflies in a colony flash together."})
        index = {"schema_version": 1, "entries": [
            {"id": "violin-py", "chart_type": "Violin plot", "data_shape": "dist", "canonical_chart_type": "violin plot",
             "library_implementations": [{"library": "seaborn"}]},
            {"id": "scatter-py", "chart_type": "Scatterplot", "data_shape": "xy", "canonical_chart_type": "scatter plot",
             "library_implementations": [{"library": "matplotlib"}]},
            {"id": "box-py", "chart_type": "Boxplot", "data_shape": "dist", "canonical_chart_type": "box plot",
             "library_implementations": [{"library": "matplotlib"}]},
            {"id": "css-tricks", "chart_type": "Styling", "data_shape": "none", "canonical_chart_type": None,
             "library_implementations": [{"library": "matplotlib"}]},
        ]}
        (self.project / "figures").mkdir(exist_ok=True)
        (self.project / "figures" / "plot_index.json").write_text(json.dumps(index), encoding="utf-8")
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1, objectives=["O1"])
        [identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        text = drawings.brief(self.project, self.ticket(identifier), policy_for(self.project))
        for expected in ("R1", R1, "t2-a1-f1", "The products raise the AUROC to 0.71.", "results/summary.json#auroc",
                         "O1", "Do the products raise the AUROC?", "Fireflies in a colony flash together.",
                         "figures/style.json", "drawings/R1-1/", "drawing.json", "at most 20 plots", "4 tables", "4 headline plots"):
            self.assertIn(expected, text)
        shapes = text[text.index("plot index"):]
        self.assertLess(shapes.index("box plot"), shapes.index("violin plot"), "sorted by shape, then chart type")
        self.assertLess(shapes.index("violin plot"), shapes.index("scatter plot"))
        self.assertNotIn("Styling", text, "a page that is no chart type for research data is left out")

    def test_the_brief_names_a_findings_artifact_as_the_conductor_files_it(self):
        from wayline.project import policy_for
        sections.file_finding(self.ledger, {"id": "t2-a1-f1", "ticket": 2, "text": "The products raise the AUROC to 0.71.",
                                            "provenance": "results/summary.json#auroc", "negative": False, "heading": R1,
                                            "replaces": None, "objectives": []})
        [identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        text = drawings.brief(self.project, self.ticket(identifier), policy_for(self.project))
        self.assertIn("    - artifact: `results/summary.json#auroc`", text)
        self.assertNotIn("    - artifact: `r`", text)

    def test_a_path_outside_the_drawing_directory_is_refused(self):
        file(self.ledger, "t2-a1-f1", "The products raise the AUROC to 0.71.", R1)
        [identifier] = drawings.open_drawings(self.project, drawings.RUN_END)
        worktree = self.temp / "worktree"
        folder = draw_into(worktree / "drawings" / "R1-1", self.project)
        (worktree / "outside.svg").write_text(sample_svg("matplotlib-clean"), encoding="utf-8")
        draft = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        draft["plots"][0]["svg"] = "../../outside.svg"
        (folder / drawings.DRAFT).write_text(json.dumps(draft), encoding="utf-8")
        from wayline.project import policy_for
        checked = drawings.check(self.project, self.ticket(identifier), worktree, final=True, policy=policy_for(self.project),
                                 python=sys.executable)
        self.assertEqual([entry["what"] for entry in checked.left_out], ["auroc_box.png (new)"])
        self.assertIn("outside its drawing directory", checked.left_out[0]["reason"])

    def test_the_limits_are_policys(self):
        from wayline.project import policy_for
        limits = drawings.limits(policy_for(self.project))
        self.assertEqual((limits.plots, limits.tables, limits.headline), (20, 4, 4))
