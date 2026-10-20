"""The linter's new tags as Type-A functions over a worktree and a result (decision 17; ticket 88).

`{code:<path>#<symbol>}` and `{code:<path>#L<a>-L<b>}` resolve against a checkout (a ticket's worktree at its
acceptance, `main` at a render), `{doc:<document>#<locator>}` against the project's documents as provenance only, and
`{ref:title:<exact title>}` through the identifier index's titles. The seams are `provenance.parse_tag`,
`provenance.code_tag_problem`, `provenance.lint`, and `provenance.lint_result` over a temporary project and a
temporary git checkout; what is asserted is what each says of a tag or a sentence.
"""

import io
import json
import subprocess

from tests import machine
from tests.projects import ProjectTestCase
from tests.scout_net import DOI, EMAIL, EMPTY_EUROPEPMC, NOT_FOUND, NOW, crossref_work, doi_answers, net_fetcher, recorded
from tests.test_conductor import ConductorCase, done, drive, hold_the_ladder, patch
from wayline import conductor, provenance, references, sections, tickets, worker
from wayline.conductor import Conductor
from wayline.dossier import look_up_one
from wayline.ledger import Ledger
from wayline.project import init_project

PHASE = '''"""Phase locking."""

RATE = 0.5


def fit(signal):
    return signal


class Model:
    def step(self, value):
        return value
'''


def claims(*texts):
    """The classifier's answer for these sentences: each a claim."""
    return {provenance.sentence_hash(text): provenance.CLAIM for text in texts}


class TagParseTest(ProjectTestCase):
    def test_a_code_tag_names_a_path_and_a_symbol_or_a_line_range(self):
        self.assertEqual(provenance.parse_tag("code:code/phase.py#fit"), ("code", {"path": "code/phase.py", "locator": "fit"}))
        self.assertEqual(provenance.parse_tag("code:code/phase.py#L10-L42"), ("code", {"path": "code/phase.py", "locator": "L10-L42"}))
        self.assertEqual(provenance.parse_tag("code:code/phase.py"), ("code", None))
        self.assertEqual(provenance.parse_tag("code:code/phase.py#not a symbol"), ("code", None))

    def test_a_doc_tag_names_a_document_and_a_locator(self):
        self.assertEqual(provenance.parse_tag("doc:D1#p4.s2"), ("doc", {"document": "D1", "locator": "p4.s2"}))
        self.assertEqual(provenance.parse_tag("doc:D1"), ("doc", None))

    def test_a_ref_tag_names_its_work_by_exact_title(self):
        self.assertEqual(provenance.parse_tag("ref:title:Attention Is All You Need#abstract"),
                         ("ref", {"identifier": "title:Attention Is All You Need", "locator": "abstract"}))
        self.assertEqual(provenance.parse_tag("ref:title:Attention Is All You Need"),
                         ("ref", {"identifier": "title:Attention Is All You Need", "locator": None}))

    def test_the_sentence_splitter_carries_every_kind_of_tag(self):
        found = provenance.sentences("We fit it {code:code/phase.py#fit}. The cells grew {doc:D1#p2.s1}. It is known "
                                     "{ref:title:A work the services know}. Then more.")
        self.assertEqual([sentence.tags for sentence in found[:3]],
                         [("code:code/phase.py#fit",), ("doc:D1#p2.s1",), ("ref:title:A work the services know",)])

    def test_a_doc_tag_is_never_a_citation(self):
        rendered = provenance.render_citations("The cells grew {doc:D1#p2.s1}.\n")
        self.assertIn("{doc:D1#p2.s1}", rendered)
        self.assertNotIn("[^1]", rendered)


class CodeTagTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.temp / "checkout"
        (self.root / "code").mkdir(parents=True)
        (self.root / "code" / "phase.py").write_text(PHASE, encoding="utf-8")
        (self.root / "code" / "spectra.m").write_text("function y = smooth_spectra(x)\n  y = x;\nend\n", encoding="utf-8")

    def problem(self, path, locator, ref=None):
        return provenance.code_tag_problem(provenance.code_reader(self.root, ref), {"path": path, "locator": locator})

    def test_a_function_a_class_a_method_and_a_constant_resolve(self):
        for locator in ("fit", "Model", "Model.step", "step", "RATE"):
            with self.subTest(locator=locator):
                self.assertIsNone(self.problem("code/phase.py", locator))

    def test_a_path_may_be_written_from_inside_code(self):
        self.assertIsNone(self.problem("phase.py", "fit"))

    def test_a_symbol_the_file_does_not_define_is_flagged(self):
        self.assertIn("fit_all", self.problem("code/phase.py", "fit_all"))

    def test_a_file_that_is_not_there_is_flagged(self):
        self.assertIn("code/gone.py", self.problem("code/gone.py", "fit"))

    def test_a_line_range_resolves_inside_the_file_and_is_flagged_past_its_end(self):
        self.assertIsNone(self.problem("code/phase.py", "L1-L5"))
        self.assertIsNone(self.problem("code/phase.py", "L3"))
        self.assertIn("12 lines", self.problem("code/phase.py", "L10-L42"))
        self.assertIsNotNone(self.problem("code/phase.py", "L9-L4"))

    def test_another_language_resolves_a_symbol_the_file_names(self):
        self.assertIsNone(self.problem("code/spectra.m", "smooth_spectra"))
        self.assertIsNotNone(self.problem("code/spectra.m", "rough_spectra"))

    def test_against_main_a_tag_resolves_by_what_main_holds_and_is_flagged_once_main_lost_it(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("-c", "user.name=t", "-c", "user.email=t@example.org", "add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "code")
        (self.root / "code" / "phase.py").write_text("RATE = 1\n", encoding="utf-8")  # not committed: main still has fit
        self.assertIsNone(self.problem("code/phase.py", "fit", ref="main"))
        self.assertIsNotNone(self.problem("code/phase.py", "fit"))
        git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-am", "drop fit")
        self.assertIn("main", self.problem("code/phase.py", "fit", ref="main"))


class LintCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)
        self.worktree = self.temp / "worktree"
        (self.worktree / "code").mkdir(parents=True)
        (self.worktree / "code" / "phase.py").write_text(PHASE, encoding="utf-8")

    @staticmethod
    def result(*texts, findings=()):
        return {"ticket_id": 4, "status": "done", "summary": "s",
                "passages": [{"section": "methods", "heading": "Fitting", "text": text, "replaces": None} for text in texts],
                "findings": list(findings)}

    def lint(self, result, classes=None):
        return provenance.lint_result(self.project, result, classes or {}, code_root=self.worktree)

    def kinds(self, lint):
        return [problem["problem"] for problem in lint.problems]


class LintResultTest(LintCase):
    def test_a_code_tag_that_resolves_in_the_worktree_passes(self):
        text = "The phase is fitted by least squares {code:code/phase.py#fit}."
        lint = self.lint(self.result(text), claims(text))
        self.assertEqual((lint.passed, lint.problems), (True, []))

    def test_a_code_tag_that_does_not_resolve_fails_the_sentence(self):
        text = "The phase is fitted by least squares {code:code/phase.py#fit_all}."
        lint = self.lint(self.result(text), claims(text))
        self.assertFalse(lint.passed)
        self.assertEqual(self.kinds(lint), [provenance.UNRESOLVED_CODE])

    def test_an_untagged_claim_in_a_workers_passage_fails(self):
        text = "The phase locks within ten cycles."
        lint = self.lint(self.result(text), claims(text))
        self.assertEqual(self.kinds(lint), [provenance.UNTAGGED_CLAIM])

    def test_a_sentence_that_is_not_a_claim_needs_no_tag(self):
        text = "We describe the fit below."
        lint = self.lint(self.result(text), {provenance.sentence_hash(text): provenance.TRANSITION})
        self.assertTrue(lint.passed)

    def test_an_unclassified_sentence_is_listed_at_acceptance_never_failed(self):
        lint = self.lint(self.result("The phase locks within ten cycles."))
        self.assertTrue(lint.passed)
        self.assertEqual([item["problem"] for item in lint.listed], [provenance.UNCLASSIFIED])

    def test_a_claim_tagged_only_doc_is_listed_not_failed(self):
        (self.project / "research" / "documents.json").write_text(json.dumps({"documents": [{"id": "D1"}]}), encoding="utf-8")
        text = "The cells synchronise {doc:D1#p2.s1}."
        lint = self.lint(self.result(text), claims(text))
        self.assertTrue(lint.passed)
        self.assertEqual([item["problem"] for item in lint.listed], [provenance.DOC_ONLY_CLAIM])

    def test_a_doc_tag_naming_no_document_is_flagged(self):
        text = "The cells synchronise {doc:D7#p2.s1}."
        self.assertEqual(self.kinds(self.lint(self.result(text), claims(text))), [provenance.UNRESOLVED_DOC])

    def test_a_finding_without_tags_is_tagged_by_its_provenance(self):
        lint = self.lint(self.result(findings=[{"text": "Synchrony rises with size.", "provenance": "results/size.json#r"}]))
        self.assertEqual((lint.passed, lint.problems, lint.listed), (True, [], []))

    def test_a_tag_inside_a_finding_is_checked(self):
        finding = {"text": "Synchrony rises with size {code:code/phase.py#gone}.", "provenance": "results/size.json#r"}
        self.assertEqual(self.kinds(self.lint(self.result(findings=[finding]))), [provenance.UNRESOLVED_CODE])

    def test_a_malformed_tag_fails(self):
        text = "The phase is fitted {code:code/phase.py}."
        self.assertEqual(self.kinds(self.lint(self.result(text), claims(text))), [provenance.MALFORMED_TAG])

    def test_a_res_tag_of_the_attempts_own_run_resolves_by_the_file_in_its_worktree(self):
        (self.worktree / "results").mkdir()
        (self.worktree / "results" / "fit.json").write_text("{}", encoding="utf-8")
        text = "The fit converged {res:t4-a1/results/fit.json#loss}."
        own = provenance.lint_result(self.project, self.result(text), claims(text), code_root=self.worktree, run_id="t4-a1")
        self.assertTrue(own.passed)
        other = provenance.lint_result(self.project, self.result(text), claims(text), code_root=self.worktree, run_id="t5-a1")
        self.assertEqual(self.kinds(other), [provenance.UNRESOLVED_RES])


class LintPassagesTest(LintCase):
    def test_an_untagged_claim_in_an_owners_passage_is_listed_not_failed(self):
        text = "The phase locks within ten cycles."
        lint = provenance.lint_passages(self.project, [{"id": "P1", "by": "owner", "text": text}], claims(text), code_root=self.worktree)
        self.assertTrue(lint.passed)
        self.assertEqual([(item["problem"], item["passage"]) for item in lint.listed], [(provenance.UNTAGGED_CLAIM, "P1")])

    def test_a_problem_names_the_passage_it_is_in(self):
        text = "It is fitted {code:code/phase.py#gone}."
        lint = provenance.lint_passages(self.project, [{"id": "P3", "by": "t2-a1", "text": text}], claims(text), code_root=self.worktree)
        self.assertEqual([problem["passage"] for problem in lint.problems], ["P3"])


class TitleTagTest(LintCase):
    def file(self):
        fetcher, _ = net_fetcher(doi_answers(crossref_work()))
        return look_up_one(self.project, DOI, fetcher=fetcher, email=EMAIL, clock=lambda: NOW)["slug"]

    def test_the_linter_resolves_a_title_tag_through_the_identifier_indexs_titles(self):
        self.file()
        lint = provenance.lint(self.project, "The flows are learned {ref:title:A Work the Services Know#abstract}.\n", {})
        self.assertEqual([problem["problem"] for problem in lint.problems if problem["tag"]], [])

    def test_a_title_no_dossier_holds_does_not_resolve(self):
        lint = provenance.lint(self.project, "The flows are learned {ref:title:A work nobody filed#abstract}.\n", {})
        self.assertEqual([problem["problem"] for problem in lint.problems if problem["tag"]], [provenance.UNRESOLVED_REF])

    def test_the_verifier_opens_the_dossier_a_title_tag_names(self):
        slug = self.file()
        claim = provenance.Claim("It holds {ref:title:A work the services know#abstract}.", ("ref:title:A work the services know#abstract",), "x")
        self.assertEqual(provenance.claim_paths(claim, provenance.identifier_index(self.project)), ["research/refs/%s/#abstract" % slug])

    def test_the_guidelines_check_reads_a_title_tag_as_well_formed(self):
        from wayline import guidelines
        self.file()
        directory = self.temp / "paper"
        directory.mkdir()
        (directory / "paper.md").write_text("# Paper\n\nIt holds {ref:title:A work the services know#abstract}.\n", encoding="utf-8")
        findings = guidelines.check_provenance(guidelines.Manuscript(directory), {}, project=self.project)
        self.assertEqual([finding.level for finding in findings], ["ok"])

    def test_at_acceptance_a_title_a_dossier_holds_passes(self):
        self.file()
        _, fetcher = recorded({})
        check = references.check_references(self.project, 4, self.result("It holds {ref:title:A work the services know#abstract}."),
                                            fetcher=fetcher, email=EMAIL, clock=lambda: NOW)
        self.assertEqual(check["problems"], [])

    def test_at_acceptance_a_title_no_dossier_holds_is_scouted_and_one_no_service_knows_is_sent_back(self):
        _, fetcher = recorded({"api.crossref.org": NOT_FOUND, "api.openalex.org": NOT_FOUND, "export.arxiv.org": NOT_FOUND,
                               "www.ebi.ac.uk": EMPTY_EUROPEPMC})
        check = references.check_references(self.project, 4, self.result("It holds {ref:title:A work nobody wrote}."),
                                            fetcher=fetcher, email=EMAIL, clock=lambda: NOW)
        self.assertEqual(len(check["problems"]), 1)
        self.assertIn("most likely invented", check["problems"][0])


class AtAcceptanceTest(ConductorCase):
    """The linter runs in the worktree's acceptance: a failing sentence sends the worker back with it."""

    def conduct(self, *envelopes, classifier=None, autonomy=None):
        hold_the_ladder(self)
        if autonomy is not None:
            harness = json.loads((self.project / "harness.json").read_text(encoding="utf-8"))
            (self.project / "harness.json").write_text(json.dumps(dict(harness, autonomy=autonomy)), encoding="utf-8")
        self.notices = []
        with worker.use_fake() as fake:
            for envelope, applied in envelopes:
                fake.script(envelope, patch=applied, ticket=1)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            self.conductor.classifier = classifier or (lambda texts: {})
            self.conductor.notify = lambda event, text, project=None, ticket=None: self.notices.append((event, text))
            drive(self.conductor)
            self.calls = list(fake.calls)

    def worktree_acceptances(self):
        return [event["payload"] for event in self.events("acceptance") if event["payload"]["where"] == "worktree"]

    @staticmethod
    def line(payload, command=conductor.LINT_CHECK):
        return [result for result in payload["results"] if result["cmd"] == command][0]

    @staticmethod
    def passage(text, **extra):
        return dict({"section": "methods", "heading": "The files", "text": text, "replaces": None}, **extra)

    def test_a_code_tag_the_worktree_does_not_resolve_sends_the_worker_back(self):
        bad = self.passage("The file is written by `write_hello` {code:code/hello.py#write_hello}.")
        good = self.passage("The file holds one line, `hello` {code:hello.txt#L1}.")
        self.conduct((done(1, passages=[bad]), patch()), (done(1, passages=[good]), None))
        first, last = self.worktree_acceptances()[0], self.worktree_acceptances()[-1]
        self.assertFalse(first["pass"])
        self.assertEqual(self.line(first)["exit_code"], 1)
        self.assertIn("unresolved_code", self.line(first)["tail"])
        self.assertIn("write_hello", [call for call in self.calls if call.kind == "resume"][0].message)
        self.assertTrue(last["pass"])
        self.assertEqual(self.line(last)["exit_code"], 0)

    def test_an_untagged_claim_sends_the_worker_back(self):
        self.conduct((done(1, passages=[self.passage("The file always holds exactly one line.")]), patch()),
                     (done(1, passages=[self.passage("The file holds one line {code:hello.txt#L1}.")]), None),
                     classifier=lambda texts: claims(*texts))
        self.assertIn("untagged_claim", self.line(self.worktree_acceptances()[0])["tail"])
        self.assertTrue(self.worktree_acceptances()[-1]["pass"])

    def test_a_sentence_the_classifier_could_not_classify_is_listed_and_passes(self):
        self.conduct((done(1, passages=[self.passage("The file always holds exactly one line.")]), patch()))
        line = self.line(self.worktree_acceptances()[0])
        self.assertEqual(line["exit_code"], 0)
        self.assertIn("listed, not failed: unclassified", line["tail"])

    def test_the_classifier_is_asked_only_about_sentences_ending_with_no_tag(self):
        hold_the_ladder(self)
        with worker.use_fake() as fake:
            fake.script(done(1, passages=[self.passage("The file holds one line {code:hello.txt#L1}.")]), patch=patch(), ticket=1)
            self.conductor = Conductor(self.project, out=io.StringIO())
            self.conductor.readings = machine.recorded
            self.conductor.plan_pre_check = False
            drive(self.conductor)
            roles = [call.request.role for call in fake.calls]
        self.assertNotIn("classifier", roles)
        self.assertTrue(self.worktree_acceptances()[0]["pass"])

    def test_a_result_without_passages_or_findings_adds_no_lint_line(self):
        self.conduct((done(1), patch()))
        commands = [result["cmd"] for payload in self.worktree_acceptances() for result in payload["results"]]
        self.assertNotIn(conductor.LINT_CHECK, commands)

    def test_replacing_an_owners_passage_needs_evidence_and_a_reason_and_is_a_notice_under_interactive(self):
        path = tickets.tickets_dir(self.project) / "01-write-the-hello-file.md"
        fields, body = tickets.read_ticket(path)
        tickets.write_ticket(self.ledger, dict(fields, sections=["methods"]), body)
        sections.add_passage(self.ledger, "methods", "The files", "The project writes no file yet.", by="owner")
        bare = self.passage("The project writes hello.txt {code:hello.txt#L1}.", replaces="P1")
        argued = dict(bare, reason="hello.txt is on main now.")
        self.conduct((done(1, passages=[bare]), patch()), (done(1, passages=[argued]), None), autonomy="interactive")
        first, last = self.worktree_acceptances()[0], self.worktree_acceptances()[-1]
        self.assertIn("the owner's passage", self.line(first, conductor.SECTIONS_CHECK)["tail"])
        self.assertTrue(last["pass"])
        [replacement] = [item for item in sections.read_passages(self.ledger) if item["by"] == "t1-a1"]
        self.assertEqual((replacement["replaces_owner"], replacement["reason"]), (True, "hello.txt is on main now."))
        self.assertEqual([event for event, _ in self.notices if event == "passage"], ["passage"])
