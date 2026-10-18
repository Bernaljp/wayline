"""Documents in: converting and keeping a project's documents (Implementation Decision 17; ticket 84).

Every conversion runs against the tool runner's recordings (seam 6): `fixtures/documents/recorded/`
holds what pandoc, `pdftotext`, LibreOffice, and docling printed and wrote on the owner's workstation
for the synthetic documents of `fixtures/midway/` and `fixtures/documents/` (nothing of PINF), and
`recorded_runner` replays them, so no tool runs here. Each test keeps documents in a temporary project
through the ledger and reads back what a later session sees: `research/documents/<id>/`,
`research/documents.json`, the journal, and `research/DOCUMENTS.md`.
"""

import hashlib
import io
import json
import re
import shutil
import subprocess
import zipfile
from contextlib import redirect_stderr, redirect_stdout

from tests.paths import FIXTURES_DIR, HARNESS_ROOT
from tests.projects import ProjectTestCase
from wayline import cli
from wayline import documents as documents_module
from wayline.documents import (
    RENDER_MAX_CHARS, DocumentError, add_document, add_documents, read_documents, recorded_runner, render_documents,
)
from wayline.jsonschema import check, load_schema
from wayline.ledger import Ledger
from wayline.project import init_project
from wayline.tools import TOOLS_JSON, Tools

MIDWAY = FIXTURES_DIR / "midway"
OWN = FIXTURES_DIR / "documents"
RECORDED = OWN / "recorded"
# What tools.json records on the owner's workstation for the four tools a conversion runs.
TOOL_VERSIONS = {"pandoc": "3.11", "pdftotext": "24.02.0", "soffice": "24.2.7.2", "docling": "2.126.0"}


def run_verb(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class DocumentsCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=HARNESS_ROOT, git=False, hermes_python=None, owner_email=None)
        self.tools = self.tools_without()
        self.run = recorded_runner(RECORDED)

    def tools_without(self, *missing):
        """A tools home whose `tools.json` records every conversion tool but `missing`, each at a file that exists."""
        root = self.temp / ("tools-without-" + "-".join(missing) if missing else "tools")
        entries = {}
        for name, version in TOOL_VERSIONS.items():
            if name in missing:
                continue
            executable = root / "bin" / ("python" if name == "docling" else name)
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            entries[name] = {"executable": str(executable), "version": version, "route": "system", "env": {}}
        root.mkdir(parents=True, exist_ok=True)
        (root / TOOLS_JSON).write_text(json.dumps({"schema_version": 2, "tools": entries}), encoding="utf-8")
        return Tools(root)

    def add(self, path, kind="inherited", tools=None):
        return add_documents(self.project, path, kind=kind, tools=tools or self.tools, run=self.run)

    def directory(self, document_id="D1"):
        return self.project / "research" / "documents" / document_id

    def text(self, document_id="D1"):
        return (self.directory(document_id) / "text.md").read_text(encoding="utf-8")

    def json_file(self, name, document_id="D1"):
        return json.loads((self.directory(document_id) / name).read_text(encoding="utf-8"))

    def record(self, document_id="D1"):
        return next(document for document in read_documents(self.project) if document["id"] == document_id)

    def events(self):
        return [event for event in Ledger(self.project).read_events()[0] if event["event"] == "document"]

    def index(self):
        return (self.project / "research" / "DOCUMENTS.md").read_text(encoding="utf-8")

    def block_of(self, text, needle):
        """The block anchor of the block of `text.md` that holds `needle`."""
        anchor = None
        for line in text.split("\n"):
            found = re.match(r'^<a id="(p\d+)"></a>$', line)
            if found:
                anchor = found.group(1)
            elif needle in line:
                return anchor
        return None


class DocxTest(DocumentsCase):
    def test_a_docx_converts_through_pandoc_with_headings_every_equation_as_latex_and_tracked_changes_accepted(self):
        self.add(MIDWAY / "manuscript-v2.docx")
        text = self.text()
        for heading in ("# Introduction", "# Results", "# Discussion", "# Methods"):
            self.assertIn("\n%s\n" % heading, text)
        self.assertIn(r"$$R = |\frac{1}{N}\sum exp(i\varphi)|$$", text)
        self.assertIn("gather in dusk swarms", text, "the tracked insertion is kept")
        self.assertNotIn("nightly", text, "the tracked deletion is dropped")
        self.assertIn("Dusk light may be the cue.", text)
        self.assertTrue(text.startswith('---\ntitle: "Wingbeat synchrony in captive lantern moth colonies"\nabstract: "We measure'))
        self.assertRegex(text, r'\n<a id="p1"></a>\n\n# Introduction\n')
        record = self.record()
        self.assertEqual([converter["name"] for converter in record["converters"]], ["pandoc", "wayline.office"])
        self.assertEqual(record["converters"][0]["version"], "3.11")
        self.assertEqual((record["counts"]["headings"], record["counts"]["equations"]), (6, 1))
        self.assertEqual(record["damage"], {"headings": 0, "equations": 0, "citations": 0, "comments": 0})
        self.assertIn("tracked changes accepted: 2 insertions kept, 1 deletion dropped", record["losses"])

    def test_the_reader_writes_mendeley_citations_as_csl_json_and_comment_threads_with_their_anchors(self):
        self.add(MIDWAY / "manuscript-v2.docx")
        works = self.json_file("citations.json")
        self.assertEqual([(work["id"], work["type"], work["title"]) for work in works],
                         [("Okafor2017", "article-journal", "Invented reference Okafor2017"),
                          ("Lindqvist2019", "article-journal", "Invented reference Lindqvist2019")])
        text = self.text()
        self.assertIn("lock together [@Okafor2017].", text)
        self.assertIn("other insects [@Lindqvist2019].", text)
        self.assertNotIn("(Okafor 2017)", text)
        threads = self.json_file("comments.json")["threads"]
        self.assertEqual([(thread["anchor"]["text"], thread["done"], [c["text"] for c in thread["comments"]]) for thread in threads], [
            ("Why they synchronize is unknown.", True, ["Cite the 2015 review here?", "Reply: no such review exists; leave it."]),
            ("The order parameter is lowest at dusk across every colony.", False, ["This contradicts the abstract. Which is right?"]),
            ("We thank the moth keepers of the invented Varga lab.", False, ["Add the funder."]),
        ])
        self.assertEqual([thread["anchor"]["block"] for thread in threads],
                         [self.block_of(text, "Why they synchronize"), self.block_of(text, "lowest at dusk"), self.block_of(text, "moth keepers")])
        self.assertEqual(threads[0]["comments"][0]["author"], "Ines Varga")

    def test_without_pandoc_a_docx_is_kept_and_flagged_not_converted(self):
        self.add(MIDWAY / "manuscript-v2.docx", tools=self.tools_without("pandoc"))
        record = self.record()
        self.assertFalse(record["converted"])
        self.assertTrue(record["losses"][0].startswith("not converted: pandoc is not recorded in tools.json"), record["losses"])
        self.assertFalse((self.directory() / "text.md").exists())
        self.assertTrue((self.directory() / "source" / "manuscript-v2.docx").is_file())
        self.assertEqual(len(self.json_file("comments.json")["threads"]), 3, "the comments are still read")
        self.assertEqual(len(self.json_file("citations.json")), 2)
        self.assertIsNone(self.events()[0]["payload"]["converter"])
        self.assertIn("- Not converted: kept as given in `source/`", self.index())


class OtherFormatsTest(DocumentsCase):
    def test_a_tex_converts_through_pandoc(self):
        self.add(MIDWAY / "methods.tex")
        text = self.text()
        self.assertIn("\n# Methods\n", text)
        self.assertIn("The order parameter $R$ is the modulus", text)
        self.assertIn("window of 256 samples", text)
        record = self.record()
        self.assertEqual(record["converters"], [{"name": "pandoc", "version": "3.11"}])
        self.assertEqual(record["damage"], {"headings": 0, "equations": 0})

    def test_a_pdf_with_no_source_converts_through_pdftotext_layout_with_the_margin_line_numbers_stripped(self):
        self.add(OWN / "numbered-draft.pdf", kind="other", tools=self.tools_without("docling"))
        text = self.text()
        self.assertIn("Wingbeat synchrony: a draft for the lab meeting", text)
        self.assertIn("Lantern moths gather in dusk swarms whose wingbeats lock together.", text)
        self.assertFalse([line for line in text.split("\n") if re.match(r"^\s*\d", line)], "no line opens with a margin number")
        record = self.record()
        self.assertEqual(record["converters"], [{"name": "pdftotext", "version": "24.02.0"}])
        self.assertEqual(record["counts"]["line_numbers_stripped"], 7)
        self.assertIn("7 margin line numbers stripped", record["losses"])
        self.assertIn("docling is not installed (wayline tools install docling), so the text has no headings", record["losses"])

    def test_docling_adds_the_structure_where_it_is_installed(self):
        self.add(FIXTURES_DIR / "pdf" / "tiny-paper.pdf", kind="other")
        record = self.record()
        self.assertEqual([converter["name"] for converter in record["converters"]], ["pdftotext", "docling"])
        self.assertIn("1 Introduction", [heading["text"] for heading in record["headings"]])
        self.assertIn("\n## 1 Introduction\n", self.text())
        plain = documents_module.convert(FIXTURES_DIR / "pdf" / "tiny-paper.pdf", tools=self.tools_without("docling"), run=self.run)
        self.assertEqual(plain.headings, [], "without docling, pdftotext's text has no headings")

    def test_an_xlsx_becomes_one_csv_per_sheet(self):
        self.add(MIDWAY / "measurements.xlsx", kind="other")
        tables = self.directory() / "tables"
        self.assertEqual(sorted(path.name for path in tables.iterdir()), ["Colonies.csv", "Lighting.csv"])
        self.assertEqual((tables / "Colonies.csv").read_text(encoding="utf-8"),
                         "colony,size,R\nC01,12,0.41\nC02,30,0.58\nC03,55,0.69\nC04,80,0.77\n")
        self.assertEqual((tables / "Lighting.csv").read_text(encoding="utf-8").splitlines()[2], "red,18,0.71")
        record = self.record()
        self.assertEqual(record["converters"][0]["name"], "wayline.office")
        self.assertEqual((record["counts"]["sheets"], record["counts"]["rows"]), (2, 9))

    def test_a_doc_becomes_a_docx_through_libreoffice_first(self):
        self.add(OWN / "required-experiments.doc", kind="critique")
        record = self.record()
        self.assertEqual([converter["name"] for converter in record["converters"]], ["soffice", "pandoc", "wayline.office"])
        self.assertTrue((self.directory() / "source" / "required-experiments.doc").is_file())
        self.assertTrue((self.directory() / "source" / "required-experiments.docx").is_file())
        self.assertIn("Film each colony under red light as well as white light.", self.text())

    def test_a_doc_without_libreoffice_is_kept_and_not_converted(self):
        self.add(OWN / "required-experiments.doc", kind="critique", tools=self.tools_without("soffice"))
        record = self.record()
        self.assertFalse(record["converted"])
        self.assertIn("LibreOffice (soffice) is not recorded", record["losses"][0])


class RecordTest(DocumentsCase):
    def test_each_document_is_kept_under_its_directory_recorded_with_every_files_sha256_and_journaled(self):
        self.add(MIDWAY / "manuscript-v2.docx")
        record = self.record()
        check({"documents": read_documents(self.project)}, load_schema("document"))
        self.assertEqual((record["id"], record["kind"], record["version"], record["title"], record["sorted_by"]),
                         ("D1", "inherited", 1, "Wingbeat synchrony in captive lantern moth colonies", "session"))
        paths = [entry["path"] for entry in record["files"]]
        self.assertEqual(paths, ["source/manuscript-v2.docx", "citations.json", "comments.json", "text.md"])
        for entry in record["files"]:
            data = (self.directory() / entry["path"]).read_bytes()
            self.assertEqual((entry["sha256"], entry["size"]), (hashlib.sha256(data).hexdigest(), len(data)), entry["path"])
        self.assertEqual(self.events()[0]["payload"], {"id": "D1", "title": "Wingbeat synchrony in captive lantern moth colonies",
                                                       "kind": "inherited", "version": 1,
                                                       "converter": "pandoc 3.11, wayline.office 1.0.1", "by": "session"})
        ignored = (self.project / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("research/documents/*/source/", ignored)
        self.assertIn("research/documents/*/media/", ignored)

    def test_documents_md_renders_kind_version_losses_counts_the_inherited_abstract_and_headings(self):
        self.add(MIDWAY / "manuscript-v2.docx")
        self.add(MIDWAY / "critiques" / "referee-1.md", kind="critique")
        index = self.index()
        intro = self.block_of(self.text(), "# Introduction")
        self.assertIn("## D1 Wingbeat synchrony in captive lantern moth colonies", index)
        self.assertIn("- Kind: inherited, version 1 (manuscript-v2.docx)", index)
        self.assertIn("- Converted: pandoc 3.11, wayline.office 1.0.1", index)
        self.assertIn("- Abstract: We measure how closely lantern moths beat their wings in phase.", index)
        self.assertIn("  - `D1#%s` Introduction: Lantern moths gather in dusk swarms whose wingbeats lock together [@Okafor2017]." % intro, index)
        self.assertRegex(index, r"- Counts: .*6 headings, 1 equation, ")
        self.assertIn("- Damage: none counted", index)
        self.assertIn("- Losses: tracked changes accepted", index)
        critique = index[index.index("## D2"):]
        self.assertIn("- Kind: critique, version 1 (referee-1.md)", critique)
        self.assertNotIn("Abstract", critique, "only an inherited document's abstract is given")
        self.assertIn("`D2#p1` Referee report 1: The manuscript is a pleasure to read", critique)

    def test_documents_md_stays_at_or_under_its_cap_on_a_project_with_many_documents(self):
        folder = self.temp / "many"
        folder.mkdir()
        for number in range(1, 61):
            sections = "\n\n".join("## Section %d of note %d\n\nThe %dth section says something long enough to fill a first "
                                   "sentence of the index, and then some more words. A second sentence." % (part, number, part)
                                   for part in range(1, 25))
            (folder / ("note-%02d.md" % number)).write_text("# Note %d\n\n%s\n" % (number, sections), encoding="utf-8")
        results = self.add(folder, kind="other")
        self.assertEqual(len(results), 60)
        index = self.index()
        self.assertLessEqual(len(index), RENDER_MAX_CHARS)
        for number in range(1, 61):
            self.assertIn("D%d " % number, index)
        many = [dict(self.record("D1"), id="D%d" % number) for number in range(1, 2001)]
        self.assertLessEqual(len(render_documents(many)), RENDER_MAX_CHARS)
        self.assertIn("more documents are in `research/documents.json`", render_documents(many))


class SortTest(DocumentsCase):
    def test_the_verb_records_the_sessions_sort(self):
        code, out, err = run_verb("document", "add", str(MIDWAY / "critiques" / "referee-2.md"), "--kind", "critique",
                                  "--project", str(self.project))
        self.assertEqual(code, 0, err)
        self.assertIn("referee-2.md: kept as D1 version 1, sorted critique", out)
        self.assertEqual((self.record()["kind"], self.record()["sorted_by"]), ("critique", "session"))
        self.assertEqual(self.events()[0]["payload"]["by"], "session")
        code, _, err = run_verb("document", "add", str(MIDWAY / "methods.tex"), "--kind", "manuscript", "--project", str(self.project))
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_with_no_kind_code_guesses_cautiously_and_never_inherited(self):
        results = add_documents(self.project, MIDWAY / "manuscript-v2.docx", tools=self.tools, run=self.run)
        self.assertEqual((results[0]["sorted"], results[0]["by"]), ("other", "code"))
        self.assertEqual(self.record("D1")["sorted_by"], "code")
        results = add_documents(self.project, MIDWAY / "critiques" / "referee-1.md", tools=self.tools, run=self.run)
        self.assertEqual(results[0]["sorted"], "critique")
        references = self.temp / "papers.md"
        references.write_text("- 10.1234/wayline.documents.one\n- arXiv:2401.00002\n", encoding="utf-8")
        results = add_documents(self.project, references, tools=self.tools, run=self.run)
        self.assertEqual((results[0]["sorted"], results[0]["path"]), ("reference", "research/intake/papers.md"))
        self.assertEqual([document["kind"] for document in read_documents(self.project)], ["other", "critique"])

    def test_one_version_per_text_is_current_the_newest_in_its_source_format(self):
        folder = self.temp / "hand-over"
        folder.mkdir()
        for name in ("manuscript-v1.docx", "manuscript-v2.docx"):
            shutil.copy(MIDWAY / name, folder / name)
        shutil.copy(OWN / "numbered-draft.pdf", folder / "manuscript.pdf")
        self.add(folder)
        documents = read_documents(self.project)
        self.assertEqual(len(documents), 1)
        record = documents[0]
        self.assertEqual((record["version"], record["origin"]), (2, "manuscript-v2.docx"))
        self.assertEqual([(earlier["version"], earlier["origin"]) for earlier in record["history"]], [(1, "manuscript-v1.docx")])
        self.assertTrue((self.directory() / "source" / "v1" / "manuscript-v1.docx").is_file())
        self.assertIn("gather in dusk swarms", self.text(), "the newest version's text")
        copies = [entry["path"] for entry in record["files"] if entry.get("copy")]
        self.assertEqual(copies, ["source/manuscript.pdf"], "the PDF of the same text is kept, not converted")
        self.assertEqual([event["payload"]["version"] for event in self.events()], [1, 2, 2])

    def test_a_newer_version_handed_over_later_is_recorded_as_the_next_version(self):
        self.add(MIDWAY / "manuscript-v1.docx")
        self.assertNotIn("Dusk light may be the cue.", self.text())
        self.add(MIDWAY / "manuscript-v2.docx")
        record = self.record()
        self.assertEqual((record["version"], [earlier["origin"] for earlier in record["history"]]), (2, ["manuscript-v1.docx"]))
        self.assertIn("Dusk light may be the cue.", self.text())
        again = self.add(MIDWAY / "manuscript-v1.docx")[0]
        self.assertTrue(again["already"])
        self.assertEqual(self.record()["version"], 2)

    def test_a_zip_is_unpacked_first_and_sorted_file_by_file(self):
        archive = self.temp / "from-the-editor.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.write(MIDWAY / "critiques" / "referee-1.md", "reviews/referee-1.md")
            package.write(MIDWAY / "critiques" / "referee-2.md", "reviews/referee-2.md")
            package.write(MIDWAY / "measurements.xlsx", "measurements.xlsx")
            package.writestr("../escape.md", "outside")
            package.writestr("__MACOSX/._referee-1.md", "resource fork")
        results = add_documents(self.project, archive, tools=self.tools, run=self.run)
        self.assertEqual(sorted((result["name"], result["sorted"]) for result in results),
                         [("measurements.xlsx", "other"), ("referee-1.md", "critique"), ("referee-2.md", "critique")])
        self.assertFalse((self.temp / "escape.md").exists())

    def test_a_pdf_sorted_as_a_reference_becomes_the_references_source_gitignored(self):
        init_project(self.project, harness_root=HARNESS_ROOT, git=True, hermes_python=None, owner_email=None)
        result = add_document(self.project, MIDWAY / "supplement.pdf", kind="reference", tools=self.tools, run=self.run)
        self.assertEqual((result["sorted"], result["path"]), ("reference", "research/intake/supplement.pdf"))
        self.assertEqual(read_documents(self.project), [], "a reference is not a document")
        ignored = subprocess.run(["git", "-C", str(self.project), "check-ignore", "-q", "research/intake/supplement.pdf"])
        self.assertEqual(ignored.returncode, 0, "the reference's PDF is never committed")
        named = self.temp / "Okafor (2017).pdf"
        shutil.copy(OWN / "numbered-draft.pdf", named)
        result = add_document(self.project, named, kind="reference", tools=self.tools, run=self.run)
        self.assertEqual(result["path"], "research/intake/Okafor -2017-.pdf", "a name the drop refuses is made plain")

    def test_a_kind_outside_the_sort_is_refused(self):
        with self.assertRaisesRegex(DocumentError, "inherited, critique, other, reference"):
            add_documents(self.project, MIDWAY / "methods.tex", kind="manuscript", tools=self.tools, run=self.run)


class IntakeWordingTest(DocumentsCase):
    def test_the_intake_tells_the_owner_to_hand_over_anything_in_any_form(self):
        skill = " ".join((HARNESS_ROOT / "skills" / "wayline-intake" / "SKILL.md").read_text(encoding="utf-8").split())
        for words in ("anything, in any form", "references as bare identifiers", "the owner's plan as the plan",
                      "a collaborator's list of experiments as a critique", "wayline document add <file> --kind"):
            self.assertIn(words, skill)
        page = " ".join((HARNESS_ROOT / "dashboard" / "index.html").read_text(encoding="utf-8").split())
        self.assertIn("anything, in any form", page)
