"""Compilations: the paper typeset under a venue (Implementation Decision 17; ticket 118).

The seams: the ledger of a temporary project holding a composed paper (`tests/compile_fixture.py`), the tool runner
replaying the real runs of pandoc, pandoc-crossref, `latexmk`, and `pdfinfo` that `fixtures/compilations/record.py`
recorded (seam 6), the scripted network the scout's last retry asks (seam 5), and the fake launcher standing in for the
fitting session (seam 1). What is asserted is what the owner and the next component see: the files under
`research/paper/compilations/`, each compilation's record, the dossiers, and the verb's output.
"""

import io
import json
import re
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from tests import compile_fixture as fixture
from tests.paths import HARNESS_ROOT, SPEC_PATH
from tests.projects import ProjectTestCase
from wayline import cli, compilations, paper, worker
from wayline import dossier as dossiers
from wayline import project as projects
from wayline.jsonschema import load_schema, validate
from wayline.worker import Envelope


class CompilationCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "paper-project"
        projects.init_project(self.project, harness_root=self.fake_harness(), git=False)
        self.book = fixture.make_paper(self.project)
        self.tools = fixture.fake_tools(self.temp / "tools")
        self.run = compilations.recorded_runner(fixture.RECORDED)
        self.said = []

    def compiled(self, name, relpath=""):
        return self.project / "research" / "paper" / "compilations" / name / relpath

    def text(self, name, relpath):
        return self.compiled(name, relpath).read_text(encoding="utf-8")

    def docx(self, name):
        with zipfile.ZipFile(self.compiled(name, "paper.docx")) as archive:
            return archive.read("word/document.xml").decode("utf-8")

    def calls(self, tool):
        return [argv for argv in self.run.calls if argv[0].endswith("/" + tool)]

    def retry(self):
        fetcher, self.net = fixture.fetcher()
        return compilations.last_retry(self.project, fetcher=fetcher, clock=lambda: fixture.NOW)

    def order(self):
        fetcher, self.net = fixture.fetcher()
        return compilations.after_order(self.project, {"order": 1, "venue": "nature"}, tools=self.tools, run=self.run,
                                        fetcher=fetcher, clock=lambda: fixture.NOW, say=self.said.append)

    def compile_testconf(self, answers=(), tools=None):
        """`testconf` compiled after the last retry, the fitting session answering `answers` in turn."""
        self.retry()
        shelf = fixture.guidelines_shelf(self.temp / "shelf")
        with worker.use_fake() as fake:
            for answer in answers:
                fake.script(Envelope(structured_output=answer, session_id="fit-1", model="claude-opus-5-5"), role="writer")
            made = compilations.compile_paper(self.project, "testconf", guidelines_root=shelf, tools=tools or self.tools, run=self.run)
            self.fake_calls = list(fake.calls)
        return made


class OrderCompilationTest(CompilationCase):
    """The order's compilations: the last retry, then `plain/` and the venue it names, `nature`."""

    def setUp(self):
        super().setUp()
        self.done = self.order()
        self.plain, self.nature = self.done["compilations"]

    def test_every_order_writes_plain_and_the_venue_it_names_each_with_its_four_outputs(self):
        for name in ("plain", "nature"):
            with self.subTest(compilation=name):
                record = json.loads(self.text(name, "compilation.json"))
                self.assertEqual(validate(record, load_schema("compilation")), [])
                self.assertEqual(record["outcome"], "compiled")
                self.assertEqual(record["paper_version"], 1)
                for relpath in ("latex/paper.tex", "paper.pdf", "paper.docx", "paper.md"):
                    self.assertTrue(self.compiled(name, relpath).is_file(), relpath)
                self.assertTrue(self.compiled(name, "paper.pdf").read_bytes().startswith(b"%PDF"))
                self.assertEqual(record["pages"], 3, "pdfinfo read the compiled PDF's page count")
        self.assertEqual(self.plain["venue"], None)
        self.assertEqual(self.nature["venue"], "nature")

    def test_the_latex_is_a_plain_article_without_a_vendored_class_and_the_pdf_comes_from_latexmk_with_xelatex(self):
        self.assertRegex(self.text("plain", "latex/paper.tex"), r"\\documentclass(\[[^\]]*\])?\{article\}")
        self.assertEqual((self.nature["document_class"], self.nature["class_vendored"]), ("article", False))
        latexmk = self.calls("latexmk")
        self.assertEqual(len(latexmk), 2)
        self.assertIn("-xelatex", latexmk[0])
        self.assertTrue(latexmk[0][-1].endswith("/latex/paper.tex"))
        self.assertTrue(all(argv[0] == str(self.tools.entry(argv[0].rsplit("/", 1)[1])["executable"]) for argv in self.run.calls),
                        "every tool ran by the executable tools.json records")

    def test_citations_render_through_citeproc_with_the_csl_the_venue_names_and_crossref_resolves_references(self):
        csl = str(HARNESS_ROOT / "guidelines" / "nature" / "nature.csl")
        venue = [argv for argv in self.calls("pandoc") if "/compile-nature/" in argv[-1]]
        self.assertEqual(len(venue), 3, "LaTeX, the .docx, and the Markdown copy")
        for argv in venue:
            self.assertIn("--citeproc", argv)
            self.assertEqual(argv[argv.index("--csl") + 1], csl)
            self.assertEqual(argv[argv.index("--lua-filter") + 1], str(compilations.FILTER))
            self.assertEqual(argv[argv.index("--filter") + 1], str(self.tools.entry("pandoc-crossref")["executable"]))
            self.assertLess(argv.index("--lua-filter"), argv.index("--filter"))
            self.assertLess(argv.index("--filter"), argv.index("--citeproc"))
        self.assertEqual(self.nature["csl"], "nature.csl")
        self.assertNotIn("--csl", [part for argv in self.calls("pandoc") if "/compile-plain/" in argv[-1] for part in argv])
        nature = self.text("nature", "paper.md")
        self.assertIn("standard^[1](#ref-smith-2020-fits)--[3](#ref-kim-2017-survey)^", nature, "Nature's superscripts, three works in one")
        plain = self.text("plain", "paper.md")
        self.assertIn("standard ([Smith and Li 2020](#ref-smith-2020-fits); [Jones 2019](#ref-jones-2019-least)", plain,
                      "pandoc's default author-date style where the paper names no venue")
        for text in (plain, nature, self.text("plain", "latex/paper.tex")):
            self.assertNotIn("@eq:error", text)
            self.assertNotIn("@fig:F1", text)
        self.assertIn("Eq.\xa01", plain, "pandoc-crossref's number, a no-break space before it")
        self.assertIn("Fig.\xa01", plain)
        self.assertIn("Table\xa01 lists", plain)
        self.assertIn("\\label{eq:error}", self.text("plain", "latex/paper.tex"))

    def test_the_docx_carries_its_equations_as_words_own(self):
        self.assertIn("<m:oMath", self.docx("plain"))
        self.assertIn("<m:oMath", self.docx("nature"))

    def test_no_tag_text_survives_in_any_output(self):
        for name in ("plain", "nature"):
            outputs = [self.text(name, "latex/paper.tex"), self.text(name, "paper.md"), re.sub(r"<[^>]+>", "", self.docx(name))]
            for output in outputs:
                for kind in ("ref", "res", "code", "doc", "plot"):
                    self.assertNotIn("{%s:" % kind, output)
                self.assertNotIn("wayline-tag", output)
            self.assertEqual(json.loads(self.text(name, "compilation.json"))["tag_text"], [])
        self.assertEqual(compilations.tag_text("a {res:t1-a1/x.json#y} and {plot:R1.1}"), ["{res:t1-a1/x.json#y}", "{plot:R1.1}"])

    def test_the_last_retry_asks_every_unresolved_cited_work_live_and_finds_one_while_another_still_fails(self):
        retried = self.done["retried"]
        self.assertEqual(retried["asked"], ["lost-work", "late-work", "dropped-work"])
        self.assertEqual((retried["found"], retried["still"]), (["late-work"], ["lost-work", "dropped-work"]))
        self.assertTrue(any("10.5555%2Flate" in url for url in self.net.asked),
                        "the late work's flag was not due for a day, and the order asked it anyway")
        late = dossiers.read_dossier(self.book, "late-work")
        self.assertEqual(late["existence"], "verified")
        lost = dossiers.read_dossier(self.book, "lost-work")
        self.assertEqual(lost["existence"], "unresolved")
        self.assertEqual(lost["retry"]["date"][:10], "2026-09-21", "its failure is today's")
        held = json.loads((self.project / "research" / "paper" / "references.json").read_text(encoding="utf-8"))
        self.assertIn("late-work", [item["id"] for item in held])
        self.assertEqual(self.plain["retried"], retried)

    def test_a_work_still_unresolved_is_never_cited_and_follows_the_batchs_answer(self):
        for name in ("plain", "nature"):
            record = json.loads(self.text(name, "compilation.json"))
            self.assertEqual(record["citations"]["cited"],
                             ["smith-2020-fits", "jones-2019-least", "kim-2017-survey", "lee-2018-noise", "late-work"])
            self.assertEqual(record["citations"]["to_be_resolved"], ["lost-work"])
            markdown = self.text(name, "paper.md")
            self.assertIn("A lost work claimed it first \\[to be resolved\\]", markdown)
            self.assertIn("A third said it again.", markdown, "the dropped work is cited nowhere and its sentence stands")
            self.assertNotIn("nobody wrote", markdown)
        self.assertIn("A Late Agreement", self.text("plain", "paper.md"), "pandoc's default style, title case")

    def test_the_venues_checks_run_on_the_compiled_output(self):
        checks = {(check["check"], check["message"]) for check in self.nature["checks"]}
        self.assertIn(("length", "the compiled PDF is 2 pages against a limit of 8."), checks)
        self.assertTrue(any(check == "template" for check, _ in checks))
        self.assertEqual(self.plain["checks"], [])
        self.assertIsNone(self.nature["fitting"], "nothing exceeds Nature's limits")

    def test_a_venues_page_limit_is_checked_against_the_main_text_not_its_references_or_supplement(self):
        self.assertLess(self.nature["main_pages"], self.nature["pages"])
        self.assertIn(("length", "the compiled PDF is %d pages against a limit of 8." % self.nature["main_pages"]),
                      {(check["check"], check["message"]) for check in self.nature["checks"]})

    def test_a_captions_tags_are_marked_like_the_texts(self):
        markdown = self.text("plain", "paper.md")
        self.assertIn("Table 1: The error of the fit at each noise level.", markdown)
        self.assertIn("grows with the noise ([Lee and Hall 2018](#ref-lee-2018-noise)).", markdown)

    def test_the_conductor_is_said_what_was_compiled(self):
        self.assertTrue(any("1 found" in line for line in self.said))
        self.assertIn("  compilation nature of version 1: compiled", self.said)


class VenueTest(CompilationCase):
    """`testconf`: a vendored class, a BibTeX template, a cap of three references, and a word limit the paper exceeds."""

    def setUp(self):
        super().setUp()
        self.made = self.compile_testconf([fixture.fitted_answer()])

    def test_a_vendored_class_is_the_documentclass_and_is_kept_beside_the_latex(self):
        self.assertEqual((self.made["document_class"], self.made["class_vendored"]), ("testconf", True))
        self.assertRegex(self.text("testconf", "latex/paper.tex"), r"\\documentclass(\[[^\]]*\])?\{testconf\}")
        self.assertIn("\\ProvidesClass{testconf}", self.text("testconf", "latex/testconf.cls"))

    def test_a_bibtex_venue_gets_a_bib_from_the_csl_items_and_cites_through_natbib(self):
        bib = self.text("testconf", "references.bib")
        self.assertEqual(len(re.findall(r"^@", bib, re.M)), 4)
        self.assertIn("smith-2020-fits", bib)
        self.assertEqual(self.made["outputs"]["bibtex"], {"file": "references.bib", "problem": None})
        latex = self.text("testconf", "latex/paper.tex")
        self.assertIn("\\citep{", latex)
        self.assertIn("\\bibliography{references.bib}", latex, "beside the LaTeX, so its directory compiles as it is")
        bib_call = [argv for argv in self.calls("pandoc") if argv[-1].endswith("references.bib")]
        self.assertEqual(bib_call[0][bib_call[0].index("--from") + 1], "csljson")

    def test_over_the_cap_the_introductions_multi_citation_sentences_lose_citations_first_never_a_result_or_method(self):
        self.assertEqual([item["work"] for item in self.made["citations"]["dropped"]], ["kim-2017-survey"])
        self.assertIn("Introduction sentences citing several works", self.made["citations"]["dropped"][0]["why"])
        self.assertEqual(self.made["citations"]["cited"], ["smith-2020-fits", "jones-2019-least", "lee-2018-noise", "late-work"])
        self.assertNotIn("Kim", self.text("testconf", "references.bib"))

    def test_a_paper_over_a_limit_gets_one_fitting_session_and_is_compiled_from_what_it_returned(self):
        self.assertEqual(len(self.fake_calls), 1, "one fresh fitting session")
        request = self.fake_calls[0].request
        self.assertEqual(request.role, "writer")
        self.assertIn("words, over the 120 The Test Conference allows", request.prompt)
        fitting = self.made["fitting"]
        self.assertEqual(fitting["outcome"], "fitted")
        self.assertEqual(fitting["session_id"], "fit-1")
        self.assertEqual(fitting["still_over"], [])
        self.assertTrue(any("words, over the 120" in limit for limit in fitting["limits"]))
        length = [check for check in self.made["checks"] if check["check"] == "length"]
        self.assertEqual(length[0]["level"], "ok", length)
        self.assertIn("Earlier claims", self.text("testconf", "paper.md"))
        self.assertEqual(self.text("testconf", "fitted/introduction.md"), fixture.FITTED["introduction"])
        self.assertEqual((self.project / "research" / "paper" / "introduction.md").read_text(encoding="utf-8"),
                         fixture.TEXTS["introduction"], "the venue-free paper is unchanged")
        self.assertEqual([call for call in self.run.calls if "/compile-testconf-fitted/" in call[-1]] != [], True)


class FittingRefusedTest(CompilationCase):
    def test_a_fitted_paper_missing_a_claim_tag_or_with_a_changed_number_is_refused_and_the_paper_compiled_unfitted(self):
        bad = dict(fixture.fitted_answer(), discussion="## Limits {#discussion-limits}\n\nThe noise model is Gaussian.\n",
                   results=fixture.TEXTS["results"].replace("0.8", "0.9"))
        made = self.compile_testconf([bad, bad])
        fitting = made["fitting"]
        self.assertEqual(fitting["outcome"], "refused")
        self.assertEqual(len(self.fake_calls), 2, "the session, resumed once with what failed")
        problems = "\n".join(fitting["problems"])
        self.assertIn("{ref:lee-2018-noise#abstract} is no longer in the paper", problems)
        self.assertIn("the number 0.9 is not one the paper has", problems)
        self.assertFalse(self.compiled("testconf", "fitted").exists())
        self.assertEqual(made["outcome"], "compiled")
        self.assertEqual([check["level"] for check in made["checks"] if check["check"] == "length"][0], "fail")

    def test_the_type_a_check_of_a_fitted_paper(self):
        before = {"results": "It grows to 0.8 {res:t1-a1/x.json#y}. More {ref:a#abstract}.", "supplement": ""}
        self.assertEqual(compilations.fitting_problems(before, {"results": "It grows to 0.8 {res:t1-a1/x.json#y}.",
                                                                "supplement": "More {ref:a#abstract}."}), [])
        self.assertEqual(compilations.fitting_problems(before, dict(before, results="It grows {res:t1-a1/x.json#y}. More {ref:a#abstract}.")),
                         [], "a number cut is no change")
        problems = compilations.fitting_problems(before, {"results": "It grows to 0.9 {res:t1-a1/x.json#y} {ref:b#abstract}."})
        self.assertEqual(problems, ["the claim tag {ref:a#abstract} is no longer in the paper",
                                    "the tag {ref:b#abstract} is new: a fitted paper adds no claim",
                                    "results: the number 0.9 is not one the paper has; a fitted paper changes no number"])


class FittedBuildFailsTest(CompilationCase):
    def test_a_fitted_paper_that_compiles_to_less_than_the_unfitted_is_set_aside_and_the_unfitted_kept(self):
        recorded = self.run

        def run(argv, cwd=None, timeout=None, env=None):
            if argv[0].endswith("/latexmk") and "/compile-testconf-fitted/" in str(argv[-1]):
                return compilations.ToolOutput(12, b"", b"! LaTeX Error: something the fitted text broke")
            return recorded(argv, cwd=cwd, timeout=timeout, env=env)
        self.run = run
        self.run.calls = recorded.calls
        made = self.compile_testconf([fixture.fitted_answer()])
        self.assertEqual(made["fitting"]["outcome"], "refused")
        self.assertIn("the fitted paper's pdf could not be made", made["fitting"]["problems"][0])
        self.assertEqual(made["outputs"]["pdf"]["file"], "paper.pdf", "the unfitted PDF is kept")
        self.assertFalse(self.compiled("testconf", "fitted").exists())
        self.assertTrue(made["checks"], "the unfitted compilation's checks stand")


class CitationPlanTest(CompilationCase):
    def test_a_work_the_order_dropped_stays_dropped_when_the_last_retry_finds_it(self):
        texts = {part: fixture.TEXTS[part] for part in fixture.TEXTS}
        plan = compilations.plan_citations(self.project, texts, {"kim-2017-survey": paper.DROP})
        self.assertEqual(plan["decisions"]["kim-2017-survey#abstract"], ("drop", "kim-2017-survey"))
        self.assertNotIn("kim-2017-survey", plan["cited"])

    def test_no_work_a_result_or_a_method_rests_on_is_dropped_however_low_the_cap(self):
        texts = {part: fixture.TEXTS[part] for part in fixture.TEXTS}
        plan = compilations.plan_citations(self.project, texts, {"dropped-work": paper.DROP}, max_count=1)
        self.assertEqual([item["work"] for item in plan["dropped"]], ["kim-2017-survey"])
        self.assertIn("smith-2020-fits", plan["cited"])
        self.assertIn("jones-2019-least", plan["cited"])
        self.assertEqual(plan["decisions"]["dropped-work#abstract"], ("drop", "dropped-work"))
        self.assertEqual(plan["decisions"]["lost-work#abstract"], ("mark", "lost-work"))


class ToolsTest(CompilationCase):
    def test_a_tool_tools_json_does_not_record_leaves_its_output_out_and_says_why(self):
        executables = {name: (self.tools.entry(name)["executable"], "1") for name in ("pandoc", "pandoc-crossref", "pdfinfo")}
        tools = fixture.tools_record(self.temp / "fewer", executables)
        self.retry()
        made = compilations.compile_paper(self.project, None, tools=tools, run=self.run)
        self.assertEqual(made["outcome"], "partial")
        self.assertIn("latexmk is not recorded", made["outputs"]["pdf"]["problem"])
        self.assertTrue(self.compiled("plain", "paper.docx").is_file())
        self.assertFalse(self.compiled("plain", "paper.pdf").exists())

    def test_no_paper_composed_is_refused(self):
        (self.project / "research" / "paper" / "paper.json").unlink()
        with self.assertRaises(compilations.CompilationError):
            compilations.compile_paper(self.project, None, tools=self.tools, run=self.run)

    def test_a_venue_naming_a_csl_it_does_not_vendor_is_refused(self):
        shelf = fixture.guidelines_shelf(self.temp / "shelf")
        path = shelf / "guidelines" / "testconf" / "guidelines.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["reference_style"].update(csl="missing.csl", bibtex=False)
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(compilations.CompilationError) as refused:
            compilations.compile_paper(self.project, "testconf", guidelines_root=shelf, tools=self.tools, run=self.run)
        self.assertIn("missing.csl", str(refused.exception))


class VerbTest(CompilationCase):
    def verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        original = compilations.compile_paper

        def compile_paper(project, venue, **_):
            return original(project, venue, tools=self.tools, run=self.run)
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(compilations, "compile_paper", compile_paper):
            code = cli.main(["paper", *args, "--project", str(self.project)])
        return code, out.getvalue(), err.getvalue()

    def test_compiling_for_another_venue_later_is_a_compilation_alone_behind_a_card(self):
        self.retry()
        code, out, _ = self.verb("compile", "nature")
        self.assertEqual(code, 0)
        self.assertIn("Compile the paper for Nature (nature)", out)
        self.assertIn("one fitting session, about $3", out)
        self.assertIn("Confirm: wayline paper compile nature --yes", out)
        self.assertFalse(self.compiled("nature").exists(), "the card does nothing")
        code, out, _ = self.verb("compile", "nature", "--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("compiled nature from version 1: compiled", out)
        self.assertIsNone(json.loads(self.text("nature", "compilation.json"))["retried"], "a compilation alone asks no scout")
        self.assertEqual([event["payload"]["action"] for event in self.book.read_events()[0] if event["event"] == "paper_order"],
                         ["ordered", "composed"], "no order was made")

    def test_an_unknown_venue_is_refused(self):
        code, _, err = self.verb("compile", "nowhere")
        self.assertEqual(code, 2)
        self.assertIn("no venue nowhere", err)

    def test_the_order_names_the_venue_it_compiles_for(self):
        self.book.append_event("paper_order", {"order": 2, "action": "failed", "by": "owner", "reason": "a test"})
        with mock.patch.object(paper, "_start_conductor", lambda project: "started"):
            made = paper.order(self.project, start=None, venue="nature")
        self.assertEqual(made["venue"], "nature")
        ordered = [event["payload"] for event in self.book.read_events()[0] if event["event"] == "paper_order"][-1]
        self.assertEqual((ordered["action"], ordered["venue"]), ("ordered", "nature"))
        with self.assertRaises(paper.PaperError):
            paper.order(self.project, start=None, venue="nowhere")

    def test_the_verb_table_of_decision_1_and_the_cli_carry_the_compilations_form(self):
        spec = SPEC_PATH.read_text(encoding="utf-8")
        row = next(line for line in spec.splitlines() if line.strip().startswith("| `paper [--yes]"))
        self.assertIn("`paper compile <slug> [--yes] [--json]`", row)
        self.assertIn("--for <slug>", row)
        self.assertIn("compile <slug>", cli.lookup("paper").usage)
