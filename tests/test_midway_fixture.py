"""The synthetic start-midway project: every file opens with the standard library and `git`.

A broken fixture fails here, before tickets 84, 85, 93, or 96 trip over it.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIDWAY = ROOT / "fixtures" / "midway"


def part(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


class TheManuscript(unittest.TestCase):
    def setUp(self):
        self.docx = MIDWAY / "manuscript-v2.docx"
        self.doc = part(self.docx, "word/document.xml")

    def test_tracked_insertions_and_deletions(self):
        self.assertIn("<w:ins ", self.doc)
        self.assertIn("<w:del ", self.doc)
        self.assertIn("<w:delText", self.doc)

    def test_open_and_resolved_comment_threads(self):
        comments = part(self.docx, "word/comments.xml")
        extended = part(self.docx, "word/commentsExtended.xml")
        self.assertGreaterEqual(comments.count("<w:comment "), 3)
        self.assertIn('w15:done="1"', extended)
        self.assertIn('w15:done="0"', extended)
        self.assertIn("w15:paraIdParent", extended)
        self.assertIn("<w:commentRangeStart", self.doc)

    def test_mendeley_cite_fields_and_an_equation(self):
        self.assertIn("MENDELEY_CITATION", self.doc)
        self.assertIn("<m:oMath", self.doc)

    def test_headings_title_abstract_captions_references(self):
        styles = re.findall(r'<w:pStyle w:val="(\w+)"/>', self.doc)
        for s in ("Title", "Abstract", "Heading1", "Caption", "Bibliography"):
            self.assertIn(s, styles)
        heads = re.findall(r'<w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t[^>]*>([^<]+)<', self.doc)
        for h in ("Introduction", "Results", "Discussion", "Methods"):
            self.assertIn(h, heads)
        self.assertTrue(set(heads) - {"Introduction", "Results", "Discussion", "Methods"})
        self.assertIn('w:styleId="Heading1"><w:name w:val="heading 1"/>', part(self.docx, "word/styles.xml"))

    def test_repeated_claim_contradiction_and_missing_data(self):
        text = re.sub(r"<[^>]+>", "", self.doc)
        self.assertIn("synchrony rises with colony size", text)
        self.assertIn("larger colonies beat more nearly in phase", text.lower())
        self.assertIn("peaks at dusk", text)
        self.assertIn("lowest at dusk", text)
        self.assertIn("data/dusk-sweep-2021.csv", text)
        self.assertFalse((MIDWAY / "data" / "dusk-sweep-2021.csv").exists())

    def test_an_older_version_beside_it(self):
        old = MIDWAY / "manuscript-v1.docx"
        self.assertIn("<w:body>", part(old, "word/document.xml"))
        with zipfile.ZipFile(old) as a, zipfile.ZipFile(self.docx) as b:
            self.assertLess(max(i.date_time for i in a.infolist()),
                            max(i.date_time for i in b.infolist()))


class TheOtherDocuments(unittest.TestCase):
    def test_tex_methods_states_a_window_the_code_contradicts(self):
        tex = (MIDWAY / "methods.tex").read_text()
        self.assertIn(r"\section{Methods}", tex)
        self.assertIn("window of 256 samples", tex)

    def test_supplement_is_a_pdf_with_no_source(self):
        self.assertTrue((MIDWAY / "supplement.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertEqual(list(MIDWAY.glob("supplement.*")), [MIDWAY / "supplement.pdf"])

    def test_xlsx_has_two_sheets(self):
        book = part(MIDWAY / "measurements.xlsx", "xl/workbook.xml")
        self.assertEqual(len(re.findall(r"<sheet ", book)), 2)
        part(MIDWAY / "measurements.xlsx", "xl/worksheets/sheet2.xml")

    def test_two_critiques(self):
        one = (MIDWAY / "critiques" / "referee-1.md").read_text()
        two = (MIDWAY / "critiques" / "referee-2.md").read_text()
        self.assertGreaterEqual(len(re.findall(r"^\d+\. ", one, re.M)), 5)
        self.assertIn("(a)", one)
        self.assertIn("(b)", one)
        self.assertIn("pleasure to read", one)
        self.assertIn("lamp flicker", one)
        self.assertIn("lamp flicker", two)
        self.assertLess(len(two), len(one))

    def test_readme_names_every_file(self):
        readme = (MIDWAY / "README.md").read_text()
        for f in MIDWAY.rglob("*"):
            if f.is_file() and f.name != "README.md" and "__pycache__" not in f.parts:
                self.assertIn(f.name, readme)


class TheCode(unittest.TestCase):
    def test_repository_builds_with_history(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        repo = tmp / "phaselock"
        subprocess.run([sys.executable, str(MIDWAY / "build_code.py"), str(repo)], check=True)
        log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(len(log.splitlines()), 3)
        py = (repo / "phaselock.py").read_text()
        self.assertIn("hilbert", py)
        self.assertIn("window=512", py)
        self.assertIn("hilbert", (repo / "phaselock.m").read_text())

    def test_no_nested_git_is_tracked(self):
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "fixtures/midway"],
                                 capture_output=True, text=True, check=True).stdout
        self.assertNotIn(".git/", tracked)


if __name__ == "__main__":
    unittest.main()
