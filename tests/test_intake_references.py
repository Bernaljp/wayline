"""Intake's references as `{identifier, note}`, read by absorb from top-level items only (ticket 71, decision 17).

Intake never looks a reference up. `INTAKE.md` renders each as a top-level item with its note
nested under it, and absorb looks up only the top-level items: a nested remark is never a query,
and a PDF with no identifier becomes the reference's source with nothing sent to any service.
"""

from tests.projects import ProjectTestCase
from tests.scout_net import DOI, EMAIL, NOW, crossref_work, doi_answers, net_fetcher
from wayline.dossier import absorb_level_0, intake_references, read_dossier, read_intake
from wayline.intake import take_intake
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.scout import UNRESOLVED, VERIFIED

NO_IDENTIFIER_PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
DOI_PDF = b"%PDF-1.7\n<x:xmpmeta><prism:doi>" + DOI.encode() + b"</prism:doi></x:xmpmeta>\n%%EOF\n"


class IntakeReferencesTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "study"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)

    def take(self, references):
        return take_intake(self.project, {"intent": "Does the flow model hold?", "references": references}, base=self.temp)

    def references_section(self):
        text = (self.project / "research" / "INTAKE.md").read_text(encoding="utf-8")
        return text.split("## References\n\n", 1)[1].split("\n## ", 1)[0].strip()

    def absorb(self, answers):
        fetcher, net = net_fetcher(answers)
        return absorb_level_0(self.project, fetcher=fetcher, email=EMAIL, clock=lambda: NOW), net

    def only_dossier(self):
        slugs = sorted(path.parent.name for path in (self.project / "research" / "refs").glob("*/dossier.json"))
        self.assertEqual(len(slugs), 1, slugs)
        return read_dossier(self.ledger, slugs[0])

    def test_a_reference_and_its_note_render_as_an_item_with_the_note_nested(self):
        self.take([{"identifier": DOI, "note": "the method this project extends"}])
        self.assertEqual(self.references_section(), "- %s\n  - the method this project extends" % DOI)

    def test_intake_looks_nothing_up(self):
        fetcher, net = net_fetcher({})
        self.take([{"identifier": DOI, "note": "a remark"}, "Some exact title of a paper"])
        self.assertEqual(net.asked, [])
        self.assertFalse((self.project / "research" / "refs").exists() and any((self.project / "research" / "refs").iterdir()))

    def test_absorb_reads_only_top_level_items_so_a_nested_remark_is_never_looked_up(self):
        text = "## References\n\n- %s\n  - see also Smith et al. on learning flows of single cells\n    - and arXiv:2304.02443\n" % DOI
        references = intake_references(text)
        self.assertEqual([(reference.kind, reference.value) for reference in references], [("doi", DOI)])
        self.assertEqual(references[0].note, "see also Smith et al. on learning flows of single cells and arXiv:2304.02443")

    def test_the_note_is_kept_on_the_dossier_and_never_sent(self):
        self.take([{"identifier": DOI, "note": "the method this project extends"}])
        _, net = self.absorb(doi_answers(crossref_work()))
        self.assertFalse(any("extends" in url for url in net.asked))
        dossier = self.only_dossier()
        self.assertEqual([(note["text"], note["by"]) for note in dossier["notes"]], [("the method this project extends", "intake")])

    def test_a_pdf_with_no_identifier_becomes_its_source_and_nothing_is_asked(self):
        pdf = self.temp / "Smith 2019 draft.pdf"
        pdf.write_bytes(NO_IDENTIFIER_PDF)
        self.take([str(pdf)])
        self.assertTrue(self.references_section().startswith("- PDF: `%s`" % pdf))
        self.assertEqual([reference.kind for reference in read_intake(self.project)], ["file"])
        report, net = self.absorb({})
        self.assertEqual(net.asked, [], "a path alone is never sent to a service, as a title or otherwise")
        dossier = self.only_dossier()
        self.assertEqual((dossier["existence"], dossier["query"]["kind"]), (UNRESOLVED, "file"))
        self.assertNotIn("retry", dossier)
        source = self.project / "research" / "refs" / dossier["slug"] / "source" / pdf.name
        self.assertEqual(source.read_bytes(), NO_IDENTIFIER_PDF)
        self.assertIn("research/refs/*/source/", (self.project / ".gitignore").read_text(encoding="utf-8"))
        self.assertEqual(report["problems"], [])

    def test_a_path_is_never_taken_as_a_reference_to_look_up(self):
        from wayline.intake import IntakeError

        other = self.temp / "related.txt"
        other.write_text("notes\n", encoding="utf-8")
        for given in (str(other), "missing/paper.pdf"):
            with self.subTest(given=given):
                with self.assertRaises(IntakeError):
                    self.take([given])
        references = intake_references("## References\n\n- papers/model.pdf\n- `drafts/old.pdf`\n")
        self.assertEqual([(reference.kind, reference.value) for reference in references],
                         [("file", "papers/model.pdf"), ("file", "drafts/old.pdf")])

    def test_a_pdf_whose_doi_intake_read_is_looked_up_by_the_doi_and_kept_as_its_source(self):
        pdf = self.temp / "paper.pdf"
        pdf.write_bytes(DOI_PDF)
        self.take([str(pdf)])
        self.assertEqual(self.references_section().split("\n")[:2], ["- %s" % DOI, "  - PDF: `%s`" % pdf])
        _, net = self.absorb(doi_answers(crossref_work()))
        self.assertFalse(any("paper.pdf" in url for url in net.asked))
        dossier = self.only_dossier()
        self.assertEqual(dossier["existence"], VERIFIED)
        self.assertTrue((self.project / "research" / "refs" / dossier["slug"] / "source" / "paper.pdf").is_file())
