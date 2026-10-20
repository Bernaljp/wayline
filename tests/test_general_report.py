"""The general report: `research/REPORT.md` rendered by code alone, in decision 17's order (ticket 90).

The seam is the ledger over a temporary project: objectives, findings, concerns, inherited passages, and the spec are
written through the ledger, the report is rendered, and what is asserted is the file it writes and the journal's
`report_rendered`. No session is ever scripted, so a render that launched one would fail. An edited report is tested by
editing the rendered file and rendering again.
"""

import io
import re
import subprocess
from pathlib import Path

from tests.projects import ProjectTestCase, open_goal
from tests.test_conductor import ConductorCase, done, drive, patch
from tests.test_results import file
from wayline import provenance, results, sections, tick, worker
from wayline.conductor import Conductor
from wayline import project as projects
from wayline.ledger import Ledger
from wayline.objectives import add_objective, change_objective

SUMMARY = ("Fireflies in a colony flash together. This project asks whether products of the colony's features raise "
           "the held-out AUROC of a model that predicts synchrony, and where they help.")
R1 = "Do the products raise the AUROC?"
R2 = "Does the loss fall?"
R3 = "Is split B different?"


class GeneralReportCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "report-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=True)
        self.ledger = Ledger(self.project)
        (self.project / "results").mkdir(exist_ok=True)
        (self.project / "results" / "summary.json").write_text('{"auroc": 0.71, "auroc_b": 0.74, "loss": 0.25}\n', encoding="utf-8")
        from wayline.provenance import register_artifact
        register_artifact(self.ledger, "results/summary.json", None, "t2-a1", 2)

    def render(self, **options):
        with worker.use_fake() as fake:
            rendered = provenance.render_report(self.project, offline=True, **options)
            self.assertEqual(list(fake.calls), [], "the general report is rendered by code alone")
        return rendered

    def text(self):
        return (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")

    def section(self, title):
        text = self.text()
        found = re.search(r"^## \d+\. %s\n" % re.escape(title), text, re.M)
        self.assertIsNotNone(found, "no section %r in:\n%s" % (title, text))
        following = re.search(r"^## ", text[found.end():], re.M)
        return text[found.start():found.end() + following.start()] if following else text[found.start():]

    def events(self, name):
        return [event for event in self.ledger.read_events()[0] if event["event"] == name]

    def spec(self, **fields):
        self.ledger.write_json("spec.json", dict({"title": "Fireflies", "question": "Do products help?", "data": []}, **fields))


class TheProjectTest(GeneralReportCase):
    def test_the_sections_render_in_decision_17s_order(self):
        self.render()
        titles = re.findall(r"^## \d+\. (.+)$", self.text(), re.M)
        self.assertEqual(titles[:7], list(provenance.SECTIONS))
        self.assertEqual(provenance.SECTIONS, ("What the project is", "Headlines", "The results", "Objectives",
                                               "Results beyond the objectives", "Inherited claims not yet checked",
                                               "What can and cannot be inferred"))

    def test_what_the_project_is_comes_from_the_spec_summary(self):
        self.spec(summary=SUMMARY)
        self.render()
        self.assertIn(SUMMARY, self.section("What the project is"))

    def test_a_spec_without_a_summary_falls_back_to_its_question_and_data(self):
        self.spec(question="Do products of the colony's features raise the held-out AUROC?",
                  data=[{"id": "D1", "text": "Forty colonies filmed at dusk.", "source": None}])
        self.render()
        part = self.section("What the project is")
        self.assertIn("Do products of the colony's features raise the held-out AUROC?", part)
        self.assertIn("Forty colonies filmed at dusk.", part)

    def test_no_spec_says_so(self):
        self.render()
        self.assertIn("No spec yet", self.section("What the project is"))

    def test_report_rendered_is_journaled_without_a_report_name(self):
        rendered = self.render()
        payload = [event["payload"] for event in self.events("report_rendered") if not event["payload"].get("report")][-1]
        self.assertEqual(payload["sha256"], rendered.sha256)
        self.assertNotIn("report", payload)
        self.assertNotIn("edited", payload)


class ResultsInTheReportTest(GeneralReportCase):
    def setUp(self):
        super().setUp()
        add_objective(self.project, R1)                                   # O1, open
        open_goal(self.project, "Does the AUROC reach 0.8?", metric="auroc", target=0.8)   # O2, a goal
        add_objective(self.project, R2)                                   # O3
        add_objective(self.project, "Does it hold on other species?", status="parked", answer="after the paper")  # O4
        add_objective(self.project, "Is the model fast?")                 # O5
        add_objective(self.project, "Does dusk matter?")                  # O6
        add_objective(self.project, "When in the evening does synchrony peak?")  # O7
        change_objective(self.project, "O3", "answered", "owner", answer="It does not fall.",
                         evidence=["res:t2-a1/results/summary.json#loss"])
        change_objective(self.project, "O5", "dropped", "owner", answer="speed is not the question")
        change_objective(self.project, "O6", "reframed", "owner", reframed_as="O7")
        self.ledger.append_event("progress", {"metric": "auroc", "value": 0.71, "ticket": 2, "run_id": "t2-a1", "kept": True, "goal": "O2"},
                                 ticket=2)
        self.first = file(self.ledger, "t2-a1-f1", "The products raise the held-out AUROC to 0.71.", R1, objectives=["O1"])
        file(self.ledger, "t2-a1-f2", "The loss stays at 0.25.", R2, objectives=["O3"], negative=True)
        file(self.ledger, "t4-a1-f1", "Split B reaches 0.74.", R3, provenance=("results/summary.json#auroc_b",))
        self.narrowed = file(self.ledger, "t5-a1-f1", "On split B only, the products raise the AUROC.", "Where do they help?",
                             replaces=self.first["id"], objectives=["O1"])
        self.ledger.write_json("concerns.json", {"split": [], "concerns": [
            {"id": "K1", "sources": [{"critique": "D2", "locator": "D2#p3", "text": "Rule out lamp flicker as the cue."}],
             "targets": [], "place": "objectives", "objectives": ["O1"], "status": "open", "answer": None, "reason": None,
             "proposed": None, "returned": None, "sorted_by": "owner"},
            {"id": "K2", "sources": [{"critique": "D2", "locator": "D2#p4", "text": "Report the seeds."}],
             "targets": [], "place": "objectives", "objectives": ["O1"], "status": "answered", "answer": "three seeds are reported",
             "reason": None, "proposed": None, "returned": None, "sorted_by": "owner"}]})
        self.render()

    def test_one_headline_per_result(self):
        part = self.section("Headlines")
        self.assertEqual(len(re.findall(r"^- R\d+ ", part, re.M)), 3)
        self.assertIn("R1 %s" % R1, part)
        self.assertIn("On split B only, the products raise the AUROC.", part)
        self.assertIn("R2 %s" % R2, part)

    def test_the_table_has_one_row_per_result_with_its_standing_and_flags_a_negative_one(self):
        part = self.section("The results")
        rows = [line for line in part.splitlines() if re.match(r"^\| R\d", line)]
        self.assertEqual(len(rows), 3)
        self.assertIn("| R1 %s | O1 | supported | 1 current, 1 replaced | none yet |" % R1, part)
        self.assertIn("| R2 %s | O3 | **negative** | 1 current, 1 negative |" % R2, part)
        self.assertIn("| R3 %s | none | supported | 1 current |" % R3, part)

    def test_objectives_render_open_and_answered_then_parked_with_dropped_and_reframed_one_line_each(self):
        part = self.section("Objectives")
        order = [part.index("### %s." % name) for name in ("O1", "O2", "O3", "O7", "O4")]
        self.assertEqual(order, sorted(order), "open and answered in id order, then parked")
        self.assertIn("- O5 (dropped): Is the model fast? speed is not the question", part)
        self.assertIn("- O6 (reframed as O7): Does dusk matter?", part)
        self.assertNotIn("### O5.", part)

    def test_each_objective_shows_its_status_answer_evidence_goal_concerns_and_results(self):
        part = self.section("Objectives")
        o1 = part[part.index("### O1."):part.index("### O2.")]
        self.assertIn("Status: open.", o1)
        self.assertIn("K1 (open): Rule out lamp flicker as the cue.", o1)
        self.assertIn("K2 (answered: three seeds are reported): Report the seeds.", o1)
        self.assertIn("#### R1. %s (supported)" % R1, o1)
        self.assertIn("`t5-a1-f1` (replaces `t2-a1-f1`) On split B only, the products raise the AUROC.", o1)
        self.assertNotIn("to 0.71", o1, "only current findings show")
        o2 = part[part.index("### O2."):part.index("### O3.")]
        self.assertIn("Goal: `auroc`, direction up, target 0.8", o2)
        self.assertIn("Kept values: 0.71 from run `t2-a1` (ticket 2).", o2)
        o3 = part[part.index("### O3."):part.index("### O7.")]
        self.assertIn("Status: answered. Answer: It does not fall.", o3)
        self.assertIn("`res:t2-a1/results/summary.json#loss`", o3)
        self.assertIn("`t2-a1-f2` (negative) The loss stays at 0.25.", o3)

    def test_results_beyond_the_objectives(self):
        part = self.section("Results beyond the objectives")
        self.assertIn("R3. %s" % R3, part)
        self.assertNotIn("R1.", part)

    def test_the_results_section_renders_the_same_findings_under_the_same_headings(self):
        body = (self.project / "research" / "sections" / "results.md").read_text(encoding="utf-8")
        for result in results.read_results(self.project):
            self.assertIn("## %s\n" % result.heading, body)
            self.assertIn("R%s. %s" % (result.id[1:], result.heading), self.text())
            for finding in result.current:
                self.assertIn(finding["text"], body)
        self.assertNotIn("to 0.71", body)

    def test_open_questions_and_what_can_and_cannot_be_inferred(self):
        part = self.section("What can and cannot be inferred")
        can, cannot = part.split("Cannot be inferred")
        self.assertIn("R1 %s (supported)" % R1, can)
        self.assertIn("R2 %s (negative)" % R2, cannot)
        self.assertIn("O1 %s" % R1, part.split("Open questions")[1])
        self.assertIn("K1 Rule out lamp flicker as the cue.", part.split("Open questions")[1])

    def test_the_report_passes_the_linter_on_the_findings_it_renders(self):
        self.assertTrue(provenance.lint_report(self.project).passed, provenance.lint_report(self.project).problems)


class InheritedClaimsTest(GeneralReportCase):
    def test_inherited_claims_not_yet_checked_are_counted_per_section(self):
        for section, text in (("introduction", "Synchrony is common."), ("introduction", "Fireflies flash."),
                              ("results", "Synchrony peaks at dusk.")):
            sections.add_passage(self.ledger, section, "Background", text, by="document:D1", doc="D1#p1.s1", standing="unchecked")
        sections.add_passage(self.ledger, "methods", "Setup", "Colonies were filmed.", by="document:D1", doc="D1#p2.s1",
                             standing="unverifiable", reason="the films are lost")
        self.render()
        part = self.section("Inherited claims not yet checked")
        self.assertIn("- Introduction: 2", part)
        self.assertIn("- Results: 1", part)
        self.assertNotIn("Methods", part)

    def test_none_says_so(self):
        self.render()
        self.assertIn("No inherited claim waits", self.section("Inherited claims not yet checked"))


class EditRuleTest(GeneralReportCase):
    def test_an_edited_report_is_committed_as_it_stood_listed_in_the_banner_and_never_taken_in(self):
        self.render()
        path = self.project / "research" / "REPORT.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nThe owner's own line.\n", encoding="utf-8")
        rendered = self.render()
        self.assertTrue(rendered.edited)
        shown = subprocess.run(["git", "-C", str(self.project), "show", "%s:research/REPORT.md" % rendered.edited],
                               capture_output=True, text=True)
        self.assertIn("The owner's own line.", shown.stdout)
        text = self.text()
        self.assertNotIn("The owner's own line.", text)
        banner = text.split("## 1.")[0]
        self.assertIn("REPORT.md was edited by hand", banner)
        self.assertIn(rendered.edited[:12], banner)
        general = [event["payload"] for event in self.events("report_rendered") if not event["payload"].get("report")]
        self.assertEqual(general[-1]["edited"], rendered.edited)
        self.render()
        self.assertIn("REPORT.md was edited by hand", self.text().split("## 1.")[0], "it stays listed from the render that noticed it")
        self.assertEqual(sum(1 for event in self.events("report_rendered") if "edited" in event["payload"]
                             and not event["payload"].get("report")), 1)
        self.assertEqual(sections.read_passages(self.project), [], "an edited report is never taken in")

    def test_an_unedited_report_journals_no_edit(self):
        self.render()
        self.render()
        self.assertFalse(any("edited" in event["payload"] for event in self.events("report_rendered") if not event["payload"].get("report")))


class WhenItRendersTest(ConductorCase):
    """After every integration, by the conductor, and from the tick, both offline."""

    def test_the_conductor_renders_it_after_a_wave_that_integrated_a_ticket(self):
        conductor = Conductor(self.project, out=io.StringIO())
        result = done(findings=[{"text": "The file says hello.", "provenance": "hello.txt#L1", "heading": "What does the file say?"}])
        with worker.use_fake() as fake:
            fake.script(result, patch=patch())
            drive(conductor, waves=2)
            self.assertEqual([call.request.role for call in fake.calls], ["coder"], "the render launches no session")
        text = (self.project / "research" / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("## 2. Headlines", text)
        self.assertIn("R1 What does the file say? (supported): The file says hello.", text)

    def test_the_tick_renders_the_general_report(self):
        path = tick.render_report(self.project)
        self.assertIn("## 4. Objectives", Path(path).read_text(encoding="utf-8"))
