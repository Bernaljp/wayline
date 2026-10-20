"""The owner's passages: `wayline passage add`, an edit to a section file taken in by its render stamp, the rule on
replacing an owner's passage, and the linter on every render (decision 17; ticket 88).

The seam is the ledger over a temporary project: passages go in through `wayline passage add` and the ledger call,
the owner edits the rendered file on disk, and the section is rendered again. What is asserted is what lands in
`research/passages.jsonl`, the journal, the rendered file, and the linter's record beside the sections.
"""

import io
import json
from contextlib import redirect_stderr, redirect_stdout

from tests.projects import ProjectTestCase
from wayline import provenance, sections
from wayline import project as projects
from wayline.ledger import Ledger


class OwnerCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "paper-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.ledger = Ledger(self.project)

    def path(self, section):
        return self.project / "research" / "sections" / ("%s.md" % section)

    def text(self, section):
        return self.path(section).read_text(encoding="utf-8")

    def edit(self, section, old, new):
        text = self.text(section)
        self.assertIn(old, text)
        self.path(section).write_text(text.replace(old, new, 1), encoding="utf-8")

    def passages(self):
        return sections.read_passages(self.ledger)

    def events(self, name):
        return [event for event in self.ledger.read_events()[0] if event["event"] == name]

    def verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sections.passage_command([*args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()


class PassageAddTest(OwnerCase):
    def test_the_verb_records_an_owners_passage_and_journals_it(self):
        code, out, _ = self.verb("add", "--section", "introduction", "--heading", "The question", "Why do cells synchronise?")
        self.assertEqual(code, 0)
        [passage] = self.passages()
        self.assertEqual((passage["id"], passage["by"], passage["section"], passage["heading"]),
                         ("P1", "owner", "introduction", "The question"))
        self.assertIn("P1", out)
        [event] = self.events("passage")
        self.assertEqual(event["payload"]["by"], "owner")
        self.assertIn("Why do cells synchronise?", self.text("introduction"))

    def test_the_owner_may_write_in_results_and_it_renders_as_written(self):
        code, _, _ = self.verb("add", "--section", "results", "--heading", "Synchrony", "Synchrony is what we expect.")
        self.assertEqual(code, 0)
        self.assertIn("Synchrony is what we expect.\n", self.text("results"))
        self.assertNotIn("{res:", self.text("results"))

    def test_a_section_that_does_not_exist_is_refused(self):
        code, _, err = self.verb("add", "--section", "appendix", "--heading", "H", "Text.")
        self.assertNotEqual(code, 0)
        self.assertIn("appendix", err)
        self.assertEqual(self.passages(), [])

    def test_the_owner_may_replace_a_passage_without_a_reason(self):
        sections.add_passage(self.ledger, "methods", "Fitting", "We fit by eye.", by="t1-a1")
        code, _, _ = self.verb("add", "--section", "methods", "--heading", "Fitting", "--replaces", "P1", "We fit by least squares.")
        self.assertEqual(code, 0)
        self.assertNotIn("by eye", self.text("methods"))


class ReplacingAnOwnersPassageTest(OwnerCase):
    def setUp(self):
        super().setUp()
        sections.add_passage(self.ledger, "methods", "Fitting", "We fit the phase by least squares.", by="owner")
        sections.add_passage(self.ledger, "results", "Synchrony", "Synchrony rises with size.", by="owner")

    @staticmethod
    def result(passages=(), findings=()):
        return {"ticket_id": 7, "status": "done", "summary": "s", "passages": list(passages), "findings": list(findings)}

    def problems(self, result):
        return sections.check_result(self.ledger, {"id": 7, "sections": ["methods", "results"]}, result)

    def passage(self, **extra):
        return dict({"section": "methods", "heading": "Fitting", "text": "We fit the phase by maximum likelihood {code:code/fit.py#fit}.",
                     "replaces": "P1"}, **extra)

    def finding(self, **extra):
        return dict({"text": "Synchrony falls with size.", "provenance": "results/size.json#r", "replaces": "P2"}, **extra)

    def test_a_replacement_with_evidence_and_a_reason_passes(self):
        self.assertEqual(self.problems(self.result([self.passage(reason="The likelihood fit converges where least squares does not.")],
                                                   [self.finding(reason="The size sweep says otherwise.")])), [])

    def test_a_replacement_without_a_reason_is_refused(self):
        problems = self.problems(self.result([self.passage()], [self.finding()]))
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("owner's passage" in problem and "reason" in problem for problem in problems))

    def test_a_replacement_without_evidence_is_refused(self):
        problems = self.problems(self.result([self.passage(text="We fit the phase by maximum likelihood.", reason="It is better.")],
                                             [self.finding(reason="r")]))
        self.assertEqual(len(problems), 1)
        self.assertIn("evidence", problems[0])

    def test_naming_a_passage_the_owner_replaced_since_is_replacing_the_owners(self):
        sections.add_passage(self.ledger, "discussion", "Scope", "The study covers one cell line.", by="t2-a1")
        sections.add_passage(self.ledger, "discussion", "Scope", "The study covers two cell lines.", by="owner", replaces="P3")
        late = {"section": "discussion", "heading": "Scope", "text": "The study covers three lines {code:code/lines.py#LINES}.",
                "replaces": "P3"}
        problems = sections.check_result(self.ledger, {"id": 7, "sections": ["discussion"]}, self.result([late]))
        self.assertEqual(len(problems), 1)
        self.assertIn("reason", problems[0])

    def test_the_replacement_is_journaled_for_the_account(self):
        sections.add_passage(self.ledger, "methods", "Fitting", "We fit by likelihood {code:code/fit.py#fit}.", by="t7-a1",
                             replaces="P1", reason="It converges.")
        payload = self.events("passage")[-1]["payload"]
        self.assertEqual((payload["replaces_owner"], payload["reason"]), (True, "It converges."))
        self.assertNotIn("replaces_owner", self.events("passage")[0]["payload"])

    def test_a_finding_replacing_an_owners_passage_is_journaled_too(self):
        sections.file_finding(self.ledger, {"id": "t7-a1-f1", "ticket": 7, "text": "Synchrony falls.", "provenance": ["r.json#a"],
                                            "negative": False, "heading": "Synchrony", "replaces": "P2", "reason": "The sweep."})
        payload = self.events("finding")[-1]["payload"]
        self.assertEqual((payload["replaces_owner"], payload["reason"]), (True, "The sweep."))


class OwnersEditTest(OwnerCase):
    """The owner edits a rendered section file; the next render takes the edit in."""

    def setUp(self):
        super().setUp()
        sections.add_passage(self.ledger, "methods", "Fitting", "We fit the phase by least squares.", by="t1-a1")
        sections.add_passage(self.ledger, "methods", "Fitting", "The fit runs once per cell.", by="t1-a1")
        sections.add_passage(self.ledger, "methods", "Data", "The cells are filmed at 10 Hz.", by="t2-a1")

    def owners(self):
        return [item for item in self.passages() if item["by"] == "owner"]

    def test_an_unedited_file_takes_nothing_in(self):
        sections.render_section(self.ledger, "methods")
        self.assertEqual(self.owners(), [])

    def test_new_text_becomes_an_owners_passage_under_its_heading(self):
        self.edit("methods", "The fit runs once per cell.\n", "The fit runs once per cell.\n\nThe owner checked the fit by hand.\n")
        sections.render_section(self.ledger, "methods")
        [added] = self.owners()
        self.assertEqual((added["heading"], added["text"], added["replaces"]), ("Fitting", "The owner checked the fit by hand.", None))
        text = self.text("methods")
        self.assertLess(text.index("once per cell"), text.index("checked the fit by hand"))
        self.assertIn("<!-- wayline:passage %s -->" % added["id"], text)

    def test_a_new_heading_with_text_becomes_an_owners_passage_under_it(self):
        self.edit("methods", "## Data\n", "## Noise\n\nThe noise is Gaussian.\n\n## Data\n")
        sections.render_section(self.ledger, "methods")
        [added] = self.owners()
        self.assertEqual((added["heading"], added["text"]), ("Noise", "The noise is Gaussian."))

    def test_changed_text_becomes_the_owners_replacement(self):
        self.edit("methods", "We fit the phase by least squares.", "We fit the phase by weighted least squares.")
        sections.render_section(self.ledger, "methods")
        [changed] = self.owners()
        self.assertEqual((changed["replaces"], changed["text"]), ("P1", "We fit the phase by weighted least squares."))
        text = self.text("methods")
        self.assertNotIn("phase by least squares", text)
        self.assertLess(text.index("weighted least squares"), text.index("once per cell"), "the replacement takes the place")

    def test_removed_text_becomes_a_withdrawal(self):
        self.edit("methods", "<!-- wayline:passage P2 -->\nThe fit runs once per cell.\n\n", "")
        sections.render_section(self.ledger, "methods")
        [withdrawal] = self.owners()
        self.assertEqual((withdrawal["replaces"], withdrawal.get("withdrawn")), ("P2", True))
        self.assertNotIn("once per cell", self.text("methods"))
        self.assertEqual([event["payload"]["by"] for event in self.events("passage")][-1], "owner")

    def test_a_passage_that_arrived_after_the_stamp_is_never_taken_for_a_deletion(self):
        self.edit("methods", "The cells are filmed at 10 Hz.", "The cells are filmed at 20 Hz.")
        later = sections.add_passage(self.ledger, "methods", "Data", "Each film lasts an hour.", by="t3-a1", render=False)
        sections.render_section(self.ledger, "methods")
        self.assertEqual([(item["replaces"], item["text"]) for item in self.owners()], [("P3", "The cells are filmed at 20 Hz.")])
        text = self.text("methods")
        self.assertIn("Each film lasts an hour.", text)
        self.assertIn("<!-- wayline:passage %s -->" % later["id"], text)
        self.assertIn("20 Hz", text)

    def test_a_passage_replaced_since_the_stamp_is_not_withdrawn_by_its_absence(self):
        self.edit("methods", "<!-- wayline:passage P3 -->\nThe cells are filmed at 10 Hz.\n", "")
        sections.add_passage(self.ledger, "methods", "Data", "The cells are filmed at 30 Hz {code:code/film.py#rate}.", by="t3-a1",
                             replaces="P3", render=False)
        sections.render_section(self.ledger, "methods")
        self.assertEqual(self.owners(), [])
        self.assertIn("30 Hz", self.text("methods"))

    def test_the_render_after_taking_the_edit_in_is_stable(self):
        self.edit("methods", "The fit runs once per cell.\n", "The fit runs once per cell.\n\nA new line.\n")
        sections.render_section(self.ledger, "methods")
        count = len(self.passages())
        self.assertFalse(sections.render_section(self.ledger, "methods"))
        self.assertEqual(len(self.passages()), count)

    def test_an_edit_is_taken_in_before_a_ticket_passage_renders_the_section(self):
        self.edit("methods", "The fit runs once per cell.", "The fit runs twice per cell.")
        sections.add_passage(self.ledger, "methods", "Data", "Each film lasts an hour.", by="t3-a1")
        self.assertEqual([item["text"] for item in self.owners()], ["The fit runs twice per cell."])
        self.assertIn("twice per cell", self.text("methods"))

    def test_a_finding_whose_run_moved_in_the_manifest_is_not_read_as_edited(self):
        from wayline import provenance
        (self.project / "out").mkdir()
        (self.project / "out" / "fit.csv").write_text("rmse\n0.1\n", encoding="utf-8")
        provenance.register_artifact(self.ledger, "out/fit.csv", None, "t3-a1", 3)
        sections.file_finding(self.ledger, {"id": "t3-a1-f1", "ticket": 3, "text": "The fit holds.", "provenance": ["out/fit.csv#rmse"],
                                            "negative": False, "heading": "Fit"})
        provenance.register_artifact(self.ledger, "out/fit.csv", None, "t9-a1", 9)  # Results is not rendered again
        self.edit("results", "The fit holds.{res:t3-a1/out/fit.csv#rmse}\n", "The fit holds.{res:t3-a1/out/fit.csv#rmse}\n\nThe owner adds a line.\n")
        sections.render_section(self.ledger, "results")
        self.assertEqual([(item["text"], item["replaces"]) for item in self.owners()], [("The owner adds a line.", None)])

    def test_an_inherited_claims_mark_is_not_part_of_the_owners_text(self):
        sections.add_passage(self.ledger, "introduction", "Background", "Cells synchronise {doc:D1#p1.s1}.", by="document:D1",
                             doc="D1#p1.s1", standing=sections.UNCHECKED)
        self.edit("introduction", "Cells synchronise {doc:D1#p1.s1}. [unchecked]", "Cells often synchronise {doc:D1#p1.s1}. [unchecked]")
        sections.render_section(self.ledger, "introduction")
        [changed] = self.owners()
        self.assertEqual(changed["text"], "Cells often synchronise {doc:D1#p1.s1}.")


class RenderLintTest(OwnerCase):
    def lint(self):
        return json.loads((self.project / "research" / sections.LINT).read_text(encoding="utf-8"))["sections"]

    def classify(self, *texts):
        cache = {provenance.sentence_hash(text): provenance.CLAIM for text in texts}
        self.ledger.write_json(provenance.CLAIMS_CACHE, {"schema_version": 1, "classes": cache})

    def test_every_render_records_the_linter_on_the_section(self):
        (self.project / "code").mkdir()
        (self.project / "code" / "fit.py").write_text("def fit():\n    pass\n", encoding="utf-8")
        sections.add_passage(self.ledger, "methods", "Fitting", "We fit by least squares {code:code/fit.py#fit}.", by="t1-a1")
        self.assertEqual(self.lint()["methods"]["problems"], [])
        (self.project / "code" / "fit.py").write_text("def other():\n    pass\n", encoding="utf-8")
        sections.render_section(self.ledger, "methods")
        [problem] = self.lint()["methods"]["problems"]
        self.assertEqual((problem["passage"], problem["problem"]), ("P1", provenance.UNRESOLVED_CODE))

    def test_an_owners_untagged_claim_and_a_doc_only_claim_are_listed_not_failed(self):
        self.classify("Cells synchronise.", "Cells synchronise {doc:D1#p1.s1}.")
        (self.project / "research" / "documents.json").write_text(json.dumps({"documents": [{"id": "D1"}]}), encoding="utf-8")
        sections.add_passage(self.ledger, "introduction", "Background", "Cells synchronise.", by="owner")
        sections.add_passage(self.ledger, "introduction", "Background", "Cells synchronise {doc:D1#p1.s1}.", by="document:D1",
                             doc="D1#p1.s1", standing=sections.UNCHECKED)
        record = self.lint()["introduction"]
        self.assertEqual(record["problems"], [])
        self.assertEqual(sorted((item["passage"], item["problem"]) for item in record["listed"]),
                         [("P1", provenance.UNTAGGED_CLAIM), ("P2", provenance.DOC_ONLY_CLAIM)])
