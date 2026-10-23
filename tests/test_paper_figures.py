"""Figures at the order (Implementation Decision 17; ticket 116).

The seams: `paper_figures.build`, the figure plan code builds from the outline and `research/plots.json` with no model
call; the order's batch (`paper.batch_items`) and its answers; the figure role's planned path over the fake launcher
(its two sessions: the designer's finish and the honesty verdict); the composed-panels check on sample generators; and
`paper.compose`, read back from the files it writes under `research/paper/`. The records go in through the ledger, as
the drawings that made them would have left them.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.test_paper import PaperCase, Writer
from wayline import batches, figure_checks, figure_role, paper, paper_figures, worker
from wayline.worker import Envelope

SAMPLES = FIXTURES_DIR / "plots" / "samples"
R2 = "Does the fit hold on the cubic?"
R3 = "Does the loss fall?"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def renumbered(found, calls):
    """The writer's answer with its own tables numbered after the plan's one table."""
    return dict(found, tables=[dict(table, id="T2") for table in found["tables"]])


class FiguresCase(PaperCase):
    """`PaperCase`'s project with three results of its own evidence, R1 to R3, in the outline's order."""

    def setUp(self):
        super().setUp()
        self.finding(R2, text="The cubic fit holds.")
        self.finding(R3, text="The loss falls.")

    def drawn(self, result, plots, tables=(), synthesis="The plots agree.", version=1, library="matplotlib"):
        """A result's accepted drawing as `drawings.accept` leaves it: its files, its record, and its plots' entries.

        `plots` and `tables` are `(number, mark)` pairs; a plot's files are a sample SVG and a small PNG.
        """
        name = "%s-%d" % (result, version)
        folder = self.project / "drawings" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "draw.py").write_text("print('the drawing')\n", encoding="utf-8")
        entries, drawn_plots, drawn_tables = [], [], []
        for number, mark in plots:
            identifier = "%s.%d" % (result, number)
            (folder / ("p%d.svg" % number)).write_text((SAMPLES / "matplotlib-clean.svg").read_text(encoding="utf-8"), encoding="utf-8")
            (folder / ("p%d.png" % number)).write_bytes(PNG)
            drawn_plots.append({"id": identifier, "data_view": "view %d" % number, "purpose": "Purpose %d." % number,
                                "data": "Data %d." % number, "shows": "Shows %d." % number, "checks": [],
                                "chart_type": "box plot", "png": "drawings/%s/p%d.png" % (name, number),
                                "svg": "drawings/%s/p%d.svg" % (name, number), "index_entries": [], "headline": False})
            entries.append({"id": identifier, "result": result, "kind": "plot", "chart_type": "box plot", "index_entries": [],
                            "data_view": "view %d" % number, "status": "current", "headline": False, "mark": mark,
                            "note": None, "drawings": [name]})
        for number, mark in tables:
            identifier = "%s.T%d" % (result, number)
            (folder / ("t%d.csv" % number)).write_text("noise,rmse\n0.1,0.12\n", encoding="utf-8")
            drawn_tables.append({"id": identifier, "data_view": "the errors %d" % number, "purpose": "P.", "data": "D.",
                                 "shows": "S.", "checks": [], "csv": "drawings/%s/t%d.csv" % (name, number)})
            entries.append({"id": identifier, "result": result, "kind": "table", "chart_type": None, "index_entries": [],
                            "data_view": "the errors %d" % number, "status": "current", "headline": False, "mark": mark,
                            "note": None, "drawings": [name]})
        held = self.ledger.read_json("plots.json") if (self.project / "research" / "plots.json").is_file() else {"plots": []}
        self.ledger.write_json("plots.json", {"schema_version": 1, "plots": [plot for plot in held["plots"]
                                                                             if plot["result"] != result] + entries}, schema="plots")
        self.ledger.write_json("drawings/%s.json" % name, {
            "result": result, "version": version, "ticket": 90 + version, "rest": "run_end", "status": "accepted",
            "library": library, "findings": [], "signature": "0" * 16, "opened": "2026-10-20T00:00:00.000Z",
            "closed": "2026-10-20T00:00:00.000Z", "reason": None, "script": "drawings/%s/draw.py" % name,
            "numbers": None, "inputs": ["results/summary.json"], "plots": drawn_plots, "tables": drawn_tables, "carried": [],
            "retired": [], "left_out": [], "synthesis": synthesis, "headline": "The %s headline." % result, "can_infer": [],
            "cannot_infer": [], "open_questions": [], "earlier_figures": [], "batch": None}, schema="drawing")

    def figure(self, plan, identifier):
        return next(item for item in plan["figures"] + plan["supplementary"] if item["id"] == identifier)


class PlanTest(FiguresCase):
    def test_keep_marked_plots_make_the_figure_maybe_and_unmarked_the_supplement_and_drop_nowhere(self):
        self.drawn("R1", [(1, "keep"), (2, "maybe"), (3, None), (4, "drop"), (5, "keep")])
        with worker.use_fake() as fake:
            plan = paper_figures.build(self.project)
            self.assertEqual(fake.calls, [], "the plan is code's")
        self.assertEqual(self.figure(plan, "F1")["panels"], ["R1.1", "R1.5"])
        self.assertEqual(self.figure(plan, "S1")["panels"], ["R1.2", "R1.3"])
        self.assertNotIn("R1.4", json.dumps(plan["figures"] + plan["supplementary"]))
        self.assertIn("R1.4", " ".join(item["what"] for item in plan["left_out"]))

    def test_with_none_marked_keep_the_figure_is_every_plot_the_synthesis_cites(self):
        self.drawn("R1", [(1, None), (2, None), (3, "maybe")], synthesis="R1.2 shows the rise and p3.png the spread; R1.3 agrees.")
        plan = paper_figures.build(self.project)
        self.assertEqual(self.figure(plan, "F1")["panels"], ["R1.2"], "a maybe-marked plot stays in the supplement, cited or not")
        self.assertEqual(self.figure(plan, "S1")["panels"], ["R1.1", "R1.3"])

    def test_a_synthesis_may_cite_a_plot_by_its_file(self):
        self.drawn("R1", [(1, None), (2, None)], synthesis="The spread (p2.png) is narrow.")
        self.assertEqual(self.figure(paper_figures.build(self.project), "F1")["panels"], ["R1.2"])

    def test_there_is_no_panel_cap_and_each_main_text_result_gets_one_figure_in_outline_order(self):
        self.drawn("R1", [(number, "keep") for number in range(1, 9)])
        self.drawn("R3", [(1, "keep")])
        plan = paper_figures.build(self.project)
        self.assertEqual([(item["id"], item["result"]) for item in plan["figures"]], [("F1", "R1"), ("F2", "R3")])
        self.assertEqual(len(self.figure(plan, "F1")["panels"]), 8)
        self.assertEqual(plan["without"], ["R2"], "R2 has no plot: no figure, made from nothing only on request")

    def test_a_retired_plot_and_a_result_the_outline_does_not_hold_draw_nothing(self):
        self.drawn("R1", [(1, "keep"), (2, None)])
        held = self.ledger.read_json("plots.json")
        held["plots"][1]["status"] = "retired"
        self.ledger.write_json("plots.json", held, schema="plots")
        plan = paper_figures.build(self.project)
        self.assertEqual([item["id"] for item in plan["supplementary"]], [])

    def test_chosen_tables_become_numbered_tables_and_the_rest_supplementary_ones(self):
        self.drawn("R1", [(1, "keep")], tables=[(1, "keep"), (2, None)])
        plan = paper_figures.build(self.project)
        self.assertEqual([(item["id"], item["plot"]) for item in plan["tables"]], [("T1", "R1.T1"), ("ST1", "R1.T2")])


# A sample generator of a composed figure: the standard library alone. It writes the figure's SVG with one group per
# panel it draws, each marked `plot:<id>` the way the finishing session is told to, in one of the ways a writer can.
COMPOSER = '''import sys
PANELS = {panels!r}
parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="500" height="200">']
for index, (plot, how) in enumerate(PANELS):
    x = 10 + 160 * index
    if how == "id":
        parts.append('<g id="plot:%s"><rect x="%d" y="10" width="150" height="150" fill="#56B4E9"/></g>' % (plot, x))
    elif how == "aria":
        parts.append('<g aria-label="plot:%s" role="graphics-object"><rect x="%d" y="10" width="150" height="150"/></g>' % (plot, x))
    elif how == "title":
        parts.append('<g><title>plot:%s</title><circle cx="%d" cy="80" r="40"/></g>' % (plot, x + 70))
    else:
        parts.append('<g><rect x="%d" y="10" width="150" height="150"/></g>' % x)
parts.append("</svg>")
open(sys.argv[1], "w", encoding="utf-8").write("\\n".join(parts))
'''


class ComposedPanelsTest(FiguresCase):
    def compose_svg(self, panels):
        script = self.temp / "compose.py"
        script.write_text(COMPOSER.format(panels=panels), encoding="utf-8")
        svg = self.temp / "figure.svg"
        subprocess.run([sys.executable, "-I", str(script), str(svg)], check=True)
        return svg

    def test_every_planned_panel_marked_in_the_composed_figure_passes(self):
        svg = self.compose_svg([("R1.1", "id"), ("R1.2", "aria"), ("R1.5", "title")])
        outcome = figure_checks.check_planned_panels(svg, ["R1.1", "R1.2", "R1.5"])
        self.assertEqual((outcome["id"], outcome["type"], outcome["pass"]), ("planned_panels", "A", True), outcome["detail"])

    def test_a_planned_panel_missing_from_the_composed_figure_fails(self):
        svg = self.compose_svg([("R1.1", "id"), ("R1.2", "unmarked")])
        outcome = figure_checks.check_planned_panels(svg, ["R1.1", "R1.2", "R1.5"])
        self.assertFalse(outcome["pass"])
        self.assertIn("R1.2", outcome["detail"])
        self.assertIn("R1.5", outcome["detail"])

    def test_a_marker_on_an_empty_element_draws_no_panel(self):
        svg = self.temp / "figure.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="plot:R1.1"/></svg>', encoding="utf-8")
        self.assertFalse(figure_checks.check_planned_panels(svg, ["R1.1"])["pass"])

    def test_a_figure_with_no_svg_fails(self):
        outcome = figure_checks.check_planned_panels(self.temp / "missing.svg", ["R1.1"])
        self.assertFalse(outcome["pass"])


def passing_checks(project, request, result, policy=None):
    return [figure_checks.check_outcome(check_id, True, "ok") for check_id in figure_checks.CHECK_IDS]


def verdict(passed=True):
    return Envelope(session_id="s-verify", model="claude-opus-5-5",
                    structured_output={"pass": passed, "question_limit": "does the figure overclaim", "findings": [] if passed else [
                        {"text": "[implied_claim] The layout implies a trend the caption does not state.", "locator": "F1", "severity": "blocker"}]})


class PlannedFigureCase(FiguresCase):
    """The figure role on a planned figure, its two sessions on the fake launcher."""

    def finisher(self, marked=None, svg_sample="matplotlib-clean"):
        """The designer's finish: it writes the figure's files where the prompt says, the SVG marking `marked` panels."""
        def respond(request, message):
            self.prompts.append(request.prompt if message is None else message)
            found = dict(re.findall(r"- the (?:final )?(\w+)(?: it writes)?: `([^`]+)`", request.prompt)) if message is None else self.paths
            self.paths = found
            figure_id = Path(found["generator"]).parent.name
            panels = re.findall(r"plot `(R\d+\.\d+)`", request.prompt) if message is None else self.panels
            self.panels = panels
            shown = panels if marked is None else marked
            body = (SAMPLES / (svg_sample + ".svg")).read_text(encoding="utf-8")
            groups = "".join('<g id="plot:%s"><rect x="1" y="1" width="9" height="9"/></g>' % plot for plot in shown)
            files = {"generator": "print('the figure')\n", "PDF": "%PDF-1.4\n", "PNG": "png", "SVG": body.replace("</svg>", groups + "</svg>"),
                     "caption": "(a) The rise. (b) The spread.\n", "notes": "Composed from the plan.\n"}
            for key, text in files.items():
                target = self.project / found[key]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            return Envelope(session_id="s-finish-%s" % figure_id, model="claude-opus-5-5", structured_output={
                "drew_final": True, "inputs": [{"path": "results/summary.json"}], "schematic_elements": [], "selection_statistics": [],
                "findings_for_text": [{"text": "Say the spread is narrow."}], "traps_hit": [], "equations": [], "applied": [], "refusals": []})
        return respond

    def setUp(self):
        super().setUp()
        self.prompts, self.paths, self.panels = [], {}, []
        self.drawn("R1", [(1, "keep"), (2, "keep"), (3, None)])


class PlannedFigureTest(PlannedFigureCase):
    def make(self, figure="F1", marked=None, repairs=0):
        plan = paper_figures.build(self.project)
        request = paper_figures.request_for(self.project, plan, self.figure(plan, figure))
        with worker.use_fake() as fake:
            for _ in range(1 + repairs):
                fake.script(respond=self.finisher(marked), role="figure-designer")
            fake.script(verdict(), role="verifier")
            result, reason = figure_role.make(self.project, request, checks=passing_checks, autonomy="checkpoints")
            self.calls = [call.request.role for call in fake.calls]
        return request, result, reason

    def test_the_figure_role_starts_from_the_planned_plots_in_two_sessions(self):
        request, result, reason = self.make()
        self.assertEqual(result["status"], "verified", reason)
        self.assertEqual(self.calls, ["figure-designer", "verifier"], "the finish and the honesty verdict: no drafts, no critic, no pick")
        self.assertEqual((request["mode"], request["ticket"]), ("planned", "paper"))
        prompt = self.prompts[0]
        for words in ("plot `R1.1`", "plot `R1.2`", "drawings/R1-1/p1.png", "drawings/R1-1/p1.svg", "drawings/R1-1/draw.py",
                      "matplotlib", "Shows 2.", "every panel", "never split", "plot:R1.1"):
            self.assertIn(words, prompt)
        self.assertNotIn("plot `R1.3`", prompt, "the supplementary figure's plot is not this figure's")
        checks = {check["id"]: check for check in result["checks"]}
        for check_id in ("rotated_text", "axis_label_length", "stacked_titles", "heatmap_cell_labels", "flat_summary_mark", "planned_panels"):
            self.assertIn(check_id, checks)
        self.assertTrue(checks["planned_panels"]["pass"])
        self.assertTrue(result["final"]["svg"].endswith(".svg"))
        self.assertEqual(result["honesty_verdict"]["verdict"], "pass")

    def test_a_figure_missing_a_planned_panel_goes_back_once_and_then_fails_its_checks(self):
        _, result, reason = self.make(marked=["R1.1"], repairs=1)
        self.assertEqual(result["status"], "failed_checks")
        self.assertIn("planned_panels", reason)
        self.assertEqual(self.calls, ["figure-designer", "figure-designer"], "one repair, and no verdict is spent")
        self.assertIn("R1.2", self.prompts[1])

    def test_a_readability_check_runs_on_the_composed_figure(self):
        plan = paper_figures.build(self.project)
        request = paper_figures.request_for(self.project, plan, self.figure(plan, "F1"))
        with worker.use_fake() as fake:
            fake.script(respond=self.finisher(svg_sample="matplotlib-rotated-ticks"), role="figure-designer")
            fake.script(respond=self.finisher(svg_sample="matplotlib-rotated-ticks"), role="figure-designer")
            result, _ = figure_role.make(self.project, request, checks=passing_checks, autonomy="checkpoints")
        self.assertEqual(result["status"], "failed_checks")
        self.assertFalse({check["id"]: check for check in result["checks"]}["rotated_text"]["pass"])


class VenueLimitTest(FiguresCase):
    def setUp(self):
        super().setUp()
        self.drawn("R1", [(1, "keep")], tables=[(1, "keep")])
        self.drawn("R2", [(1, "keep"), (2, None)])
        self.drawn("R3", [(1, "keep")])

    def test_the_limit_moves_the_last_results_in_outline_order_to_the_supplement(self):
        plan = paper_figures.build(self.project, limit=3)
        self.assertEqual([(item["id"], item["result"]) for item in plan["figures"]], [("F1", "R1"), ("F2", "R2")],
                         "R1's figure and table and R2's figure are the three display items")
        self.assertEqual(plan["moved"], ["R3"])
        self.assertEqual([(item["id"], item["result"], item["panels"]) for item in plan["supplementary"]],
                         [("S1", "R2", ["R2.2"]), ("S2", "R3", ["R3.1"])])
        self.assertIn("display-item limit of 3", " ".join(item["why"] for item in plan["left_out"]))

    def test_a_venues_display_item_limit_is_read_from_its_guidelines(self):
        venue = next(path.parent.name for path in sorted((HARNESS_ROOT / "guidelines").glob("*/guidelines.json"))
                     if json.loads(path.read_text(encoding="utf-8"))["figure_spec"]["max_count"] == 6)
        self.assertEqual(paper_figures.display_limit(venue), (venue, 6))
        self.assertEqual(paper_figures.build(self.project, venue=venue)["moved"], [], "four items fit under six")

    def test_the_moved_results_are_listed_in_paper_md(self):
        with mock.patch.object(paper_figures, "display_limit", lambda venue: ("small-venue", 2)):
            self.ledger.append_event("paper_started", {"venue": "small-venue"})
            self.compose(change=renumbered)
        report = self.read("PAPER.md")
        self.assertIn("the figures and tables of R2: moved to the supplement by small-venue's display-item limit of 2", report)
        self.assertIn("the figures and tables of R3: moved to the supplement", report)


class BatchTest(FiguresCase):
    def setUp(self):
        super().setUp()
        self.drawn("R1", [(number, "keep") for number in range(1, 13)] + [(13, "maybe")])
        self.drawn("R2", [(1, None)])
        self.drawn("R3", [(1, "keep"), (2, None)])

    def items(self):
        return {item["ref"]: item for item in paper.batch_items(self.project)}

    def test_the_plan_and_each_oversized_figure_are_items_of_the_orders_batch_with_codes_default(self):
        items = self.items()
        self.assertEqual(items["figure:R3"]["default"], "as planned")
        self.assertIn("R3.1", items["figure:R3"]["text"])
        self.assertIn("S3 (R3): R3.2", items["figure:R3"]["text"], "its supplementary figure is shown with it")
        self.assertEqual((items["oversized:R1"]["marks"], items["oversized:R1"]["default"]), (["split", "drop"], "split"))
        self.assertIn("12 panels", items["oversized:R1"]["text"])
        self.assertEqual((items["nothing:R2"]["marks"], items["nothing:R2"]["default"]), (["no figure", "a figure from nothing"], "no figure"))
        self.assertIn("its plots stand in S2", items["nothing:R2"]["text"])
        made = paper.order(self.project, start=None)
        held = {item["ref"] for item in batches.read_batch(self.project, made["batch"])["items"]}
        self.assertTrue({"figure:R1", "figure:R3", "oversized:R1", "nothing:R2"} <= held)

    def test_an_oversized_figure_splits_by_default_into_figures_of_the_same_result_within_a_page(self):
        plan = paper_figures.build(self.project)
        self.assertEqual([(item["id"], item["result"], len(item["panels"])) for item in plan["figures"]],
                         [("F1", "R1", 6), ("F2", "R1", 6), ("F3", "R3", 1)])
        self.assertIn("part 1 of 2", plan["figures"][0]["line"])

    def test_the_owner_may_drop_the_panels_past_the_page_to_the_supplementary_figure(self):
        plan = paper_figures.build(self.project, [{"ref": "oversized:R1", "mark": "drop", "by": "owner"}])
        self.assertEqual(self.figure(plan, "F1")["panels"], ["R1.%d" % number for number in range(1, 10)])
        self.assertEqual(self.figure(plan, "S1")["panels"], ["R1.10", "R1.11", "R1.12", "R1.13"])

    def test_under_autonomous_an_oversized_figure_is_split_and_never_dropped(self):
        plan = paper_figures.build(self.project, [{"ref": "oversized:R1", "mark": "drop", "by": "decider"}], autonomous=True)
        self.assertEqual([len(item["panels"]) for item in plan["figures"] if item["result"] == "R1"], [6, 6])

    def requests(self):
        """Compose with the figure role recording each request it was handed and making nothing."""
        asked = []

        def make(project, request, **kwargs):
            asked.append(request)
            return None, "recorded"
        with mock.patch.object(figure_role, "make", make):
            self.compose()
        return asked

    def test_under_autonomous_the_composition_splits_the_oversized_figure(self):
        self.autonomy("autonomous")
        asked = self.requests()
        self.assertEqual([request["figure_id"] for request in asked][:2], ["paper-r1-main", "paper-r1-main-2"])
        self.assertEqual([len(request["panels"]) for request in asked][:2], [6, 6])
        self.assertEqual([request["mode"] for request in asked], ["planned"] * len(asked), "no figure from nothing unasked")
        self.assertIn("[FIGURE NOT MADE: blocked: recorded]", self.read("figures/F1/caption.md"))

    def test_a_figure_from_nothing_the_owner_asked_for_is_the_figure_roles_unguided_path(self):
        made = paper.order(self.project, start=None)
        number = {item["ref"]: item["id"] for item in batches.read_batch(self.project, made["batch"])["items"]}
        batches.mark(self.project, made["batch"], number["nothing:R2"], "a figure from nothing")
        [request] = [request for request in self.requests() if request["claim"]["claim_id"] == "R2" and request["figure_id"].endswith("main")]
        self.assertEqual(request["mode"], "unguided")
        self.assertEqual([entry["path"] for entry in request["data"]], ["results/summary.json"], "the result's own evidence")

    def test_to_the_supplement_moves_a_figure_and_a_figure_from_nothing_is_made_only_on_request(self):
        plan = paper_figures.build(self.project, [{"ref": "figure:R3", "mark": "to the supplement", "by": "owner"}])
        self.assertNotIn("R3", [item["result"] for item in plan["figures"]])
        self.assertEqual(self.figure(plan, "S3")["panels"], ["R3.1", "R3.2"])
        self.assertNotIn("R2", [item["result"] for item in plan["figures"]], "no figure from nothing unasked")
        asked = paper_figures.build(self.project, [{"ref": "nothing:R2", "mark": "a figure from nothing", "by": "owner"}])
        [made] = [item for item in asked["figures"] if item["result"] == "R2"]
        self.assertTrue(made["from_nothing"])


class ComposeFiguresTest(PlannedFigureCase):
    """`paper.compose` with a figure plan: the writer's session, then the figure role's two sessions per figure."""

    def setUp(self):
        super().setUp()
        self.drawn("R1", [(1, "keep"), (2, "keep"), (3, None)], tables=[(1, "keep")])

    def compose_with_figures(self, figures=2, verdicts=None):
        payload = paper.open_order(self.project)
        if payload is None:
            paper.order(self.project, start=None)
            payload = paper.open_order(self.project)
        if payload.get("batch"):
            batches.take_defaults(self.project, payload["batch"])
        writer = Writer(self.project, renumbered)
        with worker.use_fake() as fake, mock.patch.object(figure_checks, "run_checks", passing_checks):
            fake.script(respond=writer, role="writer")
            for _ in range(figures):
                fake.script(respond=self.finisher(), role="figure-designer")
            for passed in (verdicts or [True] * figures):
                fake.script(verdict(passed), role="verifier")
            record = paper.compose(self.project, payload)
            self.calls = [call.request.role for call in fake.calls]
        self.writer = writer
        return record

    def test_code_writes_each_figure_and_its_caption_and_paper_md_its_plan_line(self):
        record = self.compose_with_figures()
        self.assertEqual(self.calls, ["writer", "figure-designer", "verifier", "figure-designer", "verifier"])
        folder = self.project / "research" / "paper" / "figures"
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["F1", "S1"])
        for name in ("F1.pdf", "F1.png", "F1.svg", "F1.py", "caption.md"):
            self.assertTrue((folder / "F1" / name).is_file(), name)
        self.assertEqual((folder / "F1" / "caption.md").read_text(encoding="utf-8"), "(a) The rise. (b) The spread.\n")
        self.assertTrue((folder / "S1" / "caption.md").is_file())
        report = self.read("PAPER.md")
        self.assertIn("## Figures", report)
        self.assertIn("- F1 (R1): R1.1, R1.2 (marked keep): verified (the figure role's figures/paper-r1-main/)", report)
        self.assertIn("- S1 (R1): R1.3 (its other plots): verified (the figure role's figures/paper-r1-supplement/)", report)
        self.assertIn("Say the spread is narrow.", report, "the figures' points for the text are kept for the writer")
        self.assertEqual([(entry["id"], entry["status"]) for entry in record["figures"]["figures"]], [("F1", "verified"), ("S1", "verified")])
        self.assertEqual(record["tables"], ["T1", "T2"], "the plan's table first, then the writer's after it")

    def test_a_chosen_table_is_a_numbered_table_rendered_from_its_csv(self):
        self.compose_with_figures()
        self.assertEqual(self.read("tables/T1.csv"), "noise,rmse\n0.1,0.12\n")
        self.assertIn("**Table 1.** the errors 1", self.read("tables/T1.md"))
        self.assertIn("| 0.1 | 0.12 |", self.read("tables/T1.md"))

    def test_the_writer_is_told_the_plan_and_numbers_its_own_tables_after_it(self):
        self.compose_with_figures()
        prompt = self.writer.prompts[0]
        self.assertIn("## The figures and tables", prompt)
        self.assertIn("Figure 1, of R1", prompt)
        self.assertIn("Supplementary Figure S1, of R1", prompt)
        self.assertIn("Table 1, of R1: the errors 1", prompt)
        self.assertIn("from T2, Table 2 in the text", prompt)
        self.assertNotIn("figure:R1", prompt, "the plan's answers are the plan's, not instructions to the writer")

    def test_a_figure_that_fails_its_verdict_leaves_a_marked_placeholder_caption(self):
        self.compose_with_figures(verdicts=[False, False, True])  # a failed verdict is read again by a second session
        caption = self.read("figures/F1/caption.md")
        self.assertIn("[FIGURE NOT MADE: honesty_failed", caption)
        self.assertFalse((self.project / "research" / "paper" / "figures" / "F1" / "F1.pdf").exists())
        self.assertIn("not made (honesty_failed", self.read("PAPER.md"))

    def test_a_re_order_reuses_a_verified_figure_whose_plan_is_unchanged(self):
        self.compose_with_figures()
        self.drawn("R1", [(1, "keep"), (2, "keep"), (3, "keep")], tables=[(1, "keep")])
        record = self.compose_with_figures(figures=1)
        self.assertEqual(self.calls.count("figure-designer"), 1, "only the changed figure is made again")
        by_id = {entry["id"]: entry for entry in record["figures"]["figures"]}
        self.assertEqual(sorted(by_id), ["F1"], "every plot now kept: no supplementary figure")
        self.assertEqual(by_id["F1"]["panels"], ["R1.1", "R1.2", "R1.3"])
        self.assertFalse(by_id["F1"]["reused"])
        self.assertTrue((self.project / "research" / "paper" / "earlier" / "v1" / "figures" / "S1" / "caption.md").is_file())
        self.compose_with_figures(figures=0)
        record = paper.read_record(self.project)
        self.assertTrue(record["figures"]["figures"][0]["reused"])
        self.assertEqual(self.calls, [], "nothing changed: no writer and no figure session")


class ChangelogTest(FiguresCase):
    def test_the_changelog_names_figures_from_marks_under_unreleased(self):
        changelog = (HARNESS_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Figures from marks at the paper order (ticket 116", unreleased)
