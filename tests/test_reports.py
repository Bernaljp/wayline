"""Current and earlier reports (Implementation Decision 17; ticket 101).

The seam is the ledger over a temporary project: findings filed through `sections.file_finding`, drawings opened,
checked, and accepted through `wayline.drawings` as the conductor does when the plotter's draft comes back, the
drawing's directory integrated into the project, and the renders asserting on the files written under
`research/reports/`, on `research/REPORT.md`, and on the journal.
"""

import contextlib
import io
import json
import shutil
import subprocess

from tests.test_drawings import R1, R2, DrawnCase
from tests.test_results import file
from wayline import drawings, ledger, provenance, reports, results, tickets


class ReportsCase(DrawnCase):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)

    def accept_drawing(self, plots=None, headline=True, redraws=None, **draft):
        """Draw the open drawing, check it, accept it, and integrate its directory into the project, as a run does."""
        folder = self.draw(plots=plots, **draft)
        value = json.loads((folder / drawings.DRAFT).read_text(encoding="utf-8"))
        value["plots"][0]["headline"] = headline
        for index, identifier in enumerate(redraws or []):
            value["plots"][index]["redraws"] = identifier
        (folder / drawings.DRAFT).write_text(json.dumps(value), encoding="utf-8")
        checked = self.check(final=True)
        self.assertTrue(checked.passed, checked.tail())
        record = drawings.accept(self.project, self.ticket(self.identifier), checked)
        target = self.project / self.ticket(self.identifier)["touches"][0]
        shutil.copytree(folder, target, dirs_exist_ok=True)
        self.close(self.identifier, "done")
        return record

    def next_drawing(self, result="R1"):
        [self.identifier] = drawings.open_drawings(self.project, drawings.RUN_END, only=[result])

    def render(self):
        return reports.render_reports(self.project)

    def report(self, name):
        return (self.project / "research" / "reports" / (name + ".md")).read_text(encoding="utf-8")

    def rendered(self):
        return [event["payload"] for event in self.events("report_rendered") if event["payload"].get("report", "").startswith("R")]


class VersionTest(ReportsCase):
    def test_an_accepted_drawing_starts_the_first_version_with_each_plot_explained_then_the_synthesis(self):
        self.accept_drawing()
        self.render()
        text = self.report("R1-1")
        self.assertIn("R1.1", text)
        self.assertIn("![R1.1](../../drawings/R1-1/auroc_box.png)", text)
        for line in ("Purpose: Does the AUROC hold across seeds?", "Data: The held-out AUROC of each seed",
                     "What it shows: The AUROC sits at 0.71 across 3 seeds."):
            self.assertIn(line, text)
        order = [text.index(heading) for heading in ("## Plots", "## Synthesis", "## Headline", "## What can be inferred",
                                                     "## What cannot be inferred", "## Open questions")]
        self.assertEqual(order, sorted(order))
        self.assertIn("The AUROC holds at 0.71 across 3 seeds.", text)
        self.assertIn("Whether it holds on other species.", text)
        self.assertIn("Does the loss track the AUROC?", text)
        self.assertIn("The products raise the AUROC to 0.71.", text)

    def test_a_table_is_its_own_item_rendered_from_its_csv(self):
        self.accept_drawing()
        self.render()
        text = self.report("R1-1")
        self.assertIn("## Tables", text)
        self.assertIn("R1.T1", text)
        self.assertIn("| seed | auroc |", text)
        self.assertIn("| 1 | 0.71 |", text)

    def test_report_rendered_names_the_report_and_its_version_and_a_render_that_changes_nothing_journals_nothing(self):
        self.accept_drawing()
        self.render()
        self.render()
        [payload] = self.rendered()
        self.assertEqual((payload["report"], payload["version"]), ("R1", 1))

    def test_no_report_before_the_first_accepted_drawing(self):
        self.render()
        self.assertFalse((self.project / "research" / "reports" / "R1-1.md").exists())

    def test_the_next_accepted_drawing_starts_the_next_version_and_freezes_the_earlier_one(self):
        self.accept_drawing()
        self.render()
        file(self.ledger, "t3-a1-f1", "The rise holds at 0.71 on split 3.", R1, ticket=3)
        self.render()
        frozen = self.report("R1-1")
        self.assertIn("split 3", frozen)
        self.next_drawing()
        self.accept_drawing(redraws=["R1.1"])
        self.render()
        self.assertIn("R1.1", self.report("R1-2"))
        file(self.ledger, "t4-a1-f1", "The rise holds at 0.71 on split 4.", R1, ticket=4)
        self.render()
        self.assertEqual(self.report("R1-1"), frozen, "an earlier report is never rendered again")
        self.assertIn("split 4", self.report("R1-2"))
        self.assertEqual([(payload["report"], payload["version"]) for payload in self.rendered()],
                         [("R1", 1), ("R1", 1), ("R1", 2), ("R1", 2)])


class BetweenDrawingsTest(ReportsCase):
    def test_new_findings_go_under_since_the_plots_were_drawn_and_a_replaced_one_is_marked_not_shown(self):
        self.accept_drawing()
        self.render()
        file(self.ledger, "t3-a1-f1", "The rise holds only on the held-out split.", R1, replaces="t2-a1-f1", ticket=3)
        file(self.ledger, "t4-a1-f1", "The rise is gone on the noisy split.", R1, negative=True, ticket=4)
        self.render()
        text = self.report("R1-1")
        since = text[text.index("## Since the plots were drawn"):text.index("## Plots")]
        self.assertIn("The rise holds only on the held-out split.", since)
        self.assertIn("(replaces `t2-a1-f1`", since)
        self.assertIn("(negative)", since)
        self.assertIn("`t2-a1-f1` was replaced by `t3-a1-f1`", since)
        self.assertNotIn("The products raise the AUROC to 0.71.", text, "only current findings show")


class GeneralReportTest(ReportsCase):
    def test_the_general_report_links_the_current_and_earlier_reports_and_shows_the_headline_plots_and_synthesis(self):
        self.accept_drawing()
        file(self.ledger, "t3-a1-f1", "The rise holds at 0.71 on split 3.", R1, ticket=3)
        self.next_drawing()
        self.accept_drawing(redraws=["R1.1"], synthesis="The AUROC stays at 0.71 over 3 seeds.")
        provenance.render_report(self.project, offline=True)
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("| [R1-2](reports/R1-2.md) |", text, "the table's current report column")
        self.assertIn("Current report: [R1-2](reports/R1-2.md). Earlier reports: [R1-1](reports/R1-1.md).", text)
        self.assertIn("![R1.1](../drawings/R1-2/auroc_box.png)", text)
        self.assertIn("Purpose: Does the AUROC hold across seeds?", text)
        self.assertIn("What it shows: The AUROC sits at 0.71 across 3 seeds.", text)
        self.assertIn("Synthesis: The AUROC stays at 0.71 over 3 seeds.", text)
        self.assertTrue((self.project / "research" / "reports" / "R1-2.md").is_file(), "the reports render in the same pass")


class EditRuleTest(ReportsCase):
    def test_an_edited_current_or_earlier_report_is_committed_as_it_stood_listed_and_never_taken_in(self):
        self.accept_drawing()
        self.render()
        file(self.ledger, "t3-a1-f1", "The rise holds at 0.71 on split 3.", R1, ticket=3)
        self.next_drawing()
        self.accept_drawing(redraws=["R1.1"])
        self.render()
        earlier = self.project / "research" / "reports" / "R1-1.md"
        current = self.project / "research" / "reports" / "R1-2.md"
        earlier.write_text(earlier.read_text(encoding="utf-8") + "\nMy own note on the first drawing.\n", encoding="utf-8")
        current.write_text("I rewrote it all.\n", encoding="utf-8")
        self.render()
        log = subprocess.run(["git", "-C", str(self.project), "log", "--format=%s"], capture_output=True, text=True).stdout
        self.assertIn("reports/R1-1.md as edited by hand", log)
        self.assertIn("reports/R1-2.md as edited by hand", log)
        edited = {(payload["report"], payload["version"]): payload["edited"] for payload in self.rendered() if "edited" in payload}
        self.assertEqual(sorted(edited), [("R1", 1), ("R1", 2)])
        self.assertTrue(all(edited.values()))
        text = self.report("R1-2")
        self.assertNotIn("I rewrote it all.", text, "never taken in")
        self.assertIn("reports/R1-1.md was edited by hand", text)
        self.assertIn("reports/R1-2.md was edited by hand", text)
        self.assertIn("My own note on the first drawing.", self.report("R1-1"), "an earlier report is never rendered again")
        before = len(self.rendered())
        self.render()
        self.assertEqual(len(self.rendered()), before, "an edit is noticed once")


class AskedPlotTest(ReportsCase):
    def test_a_plot_the_owner_asks_for_is_a_small_drawing_carrying_the_other_plots_unchanged_into_the_new_version(self):
        self.accept_drawing(plots={"auroc_box": "matplotlib-clean", "seed_violin": "seaborn-clean"})
        self.render()
        opened = reports.ask_plot(self.project, "R1", "A strip of the AUROC by seed.")
        self.assertEqual(opened["kind"], drawings.KIND)
        self.identifier = opened["ticket"]
        prompt = drawings.brief(self.project, self.ticket(self.identifier))
        self.assertIn("A strip of the AUROC by seed.", prompt)
        record = self.accept_drawing(plots={"seed_strip": "seaborn-clean"}, headline=False)
        self.assertEqual(sorted(record["carried"]), ["R1.1", "R1.2", "R1.T1"])
        self.assertEqual(record["retired"], [])
        self.render()
        text = self.report("R1-2")
        for identifier in ("R1.1", "R1.2", "R1.3", "R1.T1"):
            self.assertIn("### %s" % identifier, text)
        self.assertIn("![R1.1](../../drawings/R1-1/auroc_box.png)", text, "a carried plot is shown as it was drawn")

    def test_a_plot_of_data_no_result_holds_is_an_ordinary_analysis_ticket(self):
        opened = reports.ask_plot(self.project, None, "The loss per epoch on the noisy split.")
        self.assertEqual(opened["kind"], "analysis")
        fields = self.ticket(opened["ticket"])
        self.assertEqual((fields["kind"], fields["status"], fields["proposed_by"]), ("analysis", "open", "human"))
        self.assertIn("The loss per epoch on the noisy split.", fields["title"])

    def test_the_conversation_says_it_with_wayline_result_plot(self):
        self.accept_drawing()
        with contextlib.redirect_stdout(io.StringIO()):
            code = results.result_command(["plot", "R1", "A strip of the AUROC by seed.", "--project", str(self.project)])
        self.assertEqual(code, 0)
        self.assertEqual(drawings.read_records(self.project, "R1")[-1]["asked"], "A strip of the AUROC by seed.")


class MergedResultTest(ReportsCase):
    def setUp(self):
        super().setUp()
        self.accept_drawing()
        file(self.ledger, "t3-a1-f1", "The literature found 0.71 too.", R2, ticket=3)
        self.next_drawing("R2")
        self.accept_drawing()
        self.render()

    def plots(self):
        return {plot["id"]: plot for plot in drawings.read_plots(self.project)["plots"]}

    def test_a_merged_results_plots_follow_it_keep_their_ids_and_its_report_freezes(self):
        frozen = self.report("R2-1")
        results.merge(self.project, "R2", "R1")
        plots = self.plots()
        self.assertEqual((plots["R2.1"]["result"], plots["R2.1"]["status"]), ("R1", "current"))
        self.assertEqual(provenance.lint_passages(self.project, [{"id": "P1", "by": "owner", "text": "The rise holds ({plot:R2.1})."}], {}).problems, [])
        file(self.ledger, "t4-a1-f1", "The literature agrees at 0.71.", R2, ticket=4)
        self.render()
        self.assertEqual(self.report("R2-1"), frozen)
        provenance.render_report(self.project, offline=True)
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("[R2-1](reports/R2-1.md)", text, "the merged result's report is an earlier report of the one it went into")

    def test_the_next_drawing_of_the_result_it_went_into_keeps_or_retires_it(self):
        results.merge(self.project, "R2", "R1")
        self.next_drawing("R1")
        self.assertIn("R2.1", drawings.brief(self.project, self.ticket(self.identifier)))
        record = self.accept_drawing(redraws=["R1.1"])
        self.assertIn("R2.1", record["retired"])
        self.assertEqual(self.plots()["R2.1"]["status"], "retired")


class ReviewFixesTest(ReportsCase):
    def test_a_plot_the_owner_asks_for_keeps_the_results_headline_plots(self):
        self.accept_drawing()
        reports.ask_plot(self.project, "R1", "A strip of the AUROC by seed.")
        self.identifier = drawings.read_records(self.project, "R1")[-1]["ticket"]
        self.accept_drawing(plots={"seed_strip": "seaborn-clean"}, headline=False)
        provenance.render_report(self.project, offline=True)
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Headline plot R1.1", text)
        self.assertNotIn("Headline plot R1.3", text)

    def test_a_result_whose_drawing_is_under_way_is_not_merged(self):
        self.accept_drawing()
        file(self.ledger, "t3-a1-f1", "The literature found 0.71 too.", R2, ticket=3)
        self.next_drawing("R2")
        with self.assertRaises(results.ResultError):
            results.merge(self.project, "R2", "R1")

    def test_a_merged_plot_redrawn_by_the_result_it_went_into_shows_its_newest_drawing(self):
        self.accept_drawing()
        file(self.ledger, "t3-a1-f1", "The literature found 0.71 too.", R2, ticket=3)
        self.next_drawing("R2")
        self.accept_drawing()
        results.merge(self.project, "R2", "R1")
        self.next_drawing("R1")
        self.accept_drawing(plots={"auroc_box": "matplotlib-clean"}, redraws=["R2.1"])
        self.assertEqual(reports.plot_entries(self.project)["R2.1"][0]["png"], "drawings/R1-2/auroc_box.png")
