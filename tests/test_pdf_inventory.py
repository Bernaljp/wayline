"""The PDF inventory chain: the always-on poppler and pdfplumber layer, the converters, the verb.

`fixtures/pdf/tiny-paper.pdf` is a two-column paper written for the suite (`fixtures/pdf/make.py`
rebuilds it), and `fixtures/pdf/recorded/` holds what poppler, pdfplumber, and docling made of it
on a machine that had them. The chain is run against those recordings through `recorded_runner`,
so it runs the same on a machine with none of the tools. marker, MinerU, and GROBID could not run
where the recordings were made, so their adapters run on samples written to each tool's documented
output shape under `fixtures/pdf/samples/`. The live counts on a paper from the owner's field are
in `docs/verification/m3.md`, and no such paper is committed here.
"""

import contextlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from tests.test_inventory import served
from wayline import cli
from wayline.dossier import REFS, build_inventory, l0_dossier, write_l0
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger
from wayline.pdf_inventory import (
    CONVERTERS_DIR, Headings, caption_number, docling_items, environment_heading,
    equation_number, grobid_references, grobid_tei, heading_number, html_cells, is_appendix_heading, latex_equation_numbers,
    marker_items, mineru_items, parse_pdfimages_list, parse_pdfinfo, record_tool_outputs,
    recorded_runner, split_pages, text_layer_environments,
)
from wayline.project import init_project
from wayline.tools import TOOLS_JSON, ToolOutput, Tools, ToolsError, driver_cuda, install, install_steps, torch_index

PDF_FIXTURES = FIXTURES_DIR / "pdf"
PDF = PDF_FIXTURES / "tiny-paper.pdf"
RECORDED = PDF_FIXTURES / "recorded"
SAMPLES = PDF_FIXTURES / "samples"
SLUG = "suite-2026-tiny-two-column-paper"
EMAIL = "owner@example.org"
DOCLING = "docling-2.126.0"
POPPLER = "24.02.0"

# Two lines of `pdfinfo`, as poppler 24.02 prints them.
PDFINFO = "Title:           Deep learning enables accurate clustering\nPages:           14\nPage size:       595.276 x 790.866 pts\n"

PDFIMAGES = """page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
   1     0 image     320   180  rgb     3   8  image  no         1  0   112   112  756B 0.4%
   2     1 image     640   200  rgb     3   8  jpeg   no         2  0   123   123 1.7K 0.5%
   2     2 smask     640   200  gray    1   8  image  no         3  0   123   123  12B 0.0%
"""

# The first page of the fixture as `pdftotext -layout` sets it: two columns on every line.
LAYOUT_PAGE = (
    "1     Introduction\n"
    "A tiny paper needs a tiny introduction. The method Figure 1: A signal that rises from left to right and\n"
    "of Section 2 is one line, and Figure 1 shows it do- means nothing.\n"
    "                                                    Theorem 1 (Tininess). Every tiny paper is tiny.\n"
    "1.1    Scope                                                  Proof. By inspection of this page.\n"
    "Nothing at all is in scope, which is the point. The Lemma 1. Some tiny papers are tinier than others.\n"
    "two columns of this page are there to see whether a\n"
    "converter reads the left column to the bottom before Algorithm 1 Do nothing, carefully\n"
    "it starts on the right.                               x←0\n"
    "                                                    A     Proof of the lemma\n"
    "Theorem 2. A heading that opens its line.           The proof of Lemma 1 is left to the reader, who is\n"
)


def fake_tools(root, packages=("docling", "pdfplumber"), **record):
    """A tools record whose venv Python exists, so `Tools.has` answers from the record alone."""
    python = Path(root) / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.touch()
    versions = {"docling": "2.126.0", "pdfplumber": "0.11.10", "marker": "2.0.0", "mineru": "3.4.5"}
    return Tools(root, dict({"packages": {name: versions[name] for name in packages}, "device": "cuda"}, **record))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- the parsers and the regexes ------------------------------------------------------------------


class PopplerParsersTest(unittest.TestCase):
    def test_pdfinfo_gives_the_page_count_as_a_number_and_the_rest_as_printed(self):
        info = parse_pdfinfo(PDFINFO)
        self.assertEqual(info["pages"], 14)
        self.assertEqual(info["title"], "Deep learning enables accurate clustering")
        self.assertEqual(info["page_size"], "595.276 x 790.866 pts")

    def test_the_text_layer_is_split_at_the_form_feed_that_ends_every_page(self):
        self.assertEqual(split_pages("one\n\ftwo\n\f"), ["one\n", "two\n"])
        self.assertEqual(split_pages(""), [])

    def test_every_image_row_of_pdfimages_is_read_and_the_header_is_not(self):
        rows = parse_pdfimages_list(PDFIMAGES)
        self.assertEqual([(row["page"], row["num"], row["type"]) for row in rows], [(1, 0, "image"), (2, 1, "image"), (2, 2, "smask")])
        self.assertEqual((rows[1]["width"], rows[1]["height"], rows[1]["enc"], rows[1]["x_ppi"]), (640, 200, "jpeg", 123))


class RegexTest(unittest.TestCase):
    def test_a_heading_number_is_split_from_its_title(self):
        self.assertEqual(heading_number("3.2 Results"), ("3.2", "Results"))
        self.assertEqual(heading_number("2. Methods"), ("2", "Methods"))
        self.assertEqual(heading_number("A.1 More proofs"), ("A.1", "More proofs"))
        self.assertEqual(heading_number("Results"), (None, "Results"))

    def test_a_lone_letter_is_a_number_only_in_the_appendix(self):
        """"A Simple Model" is a title; "B Proofs" after the appendix has begun is appendix B."""
        self.assertEqual(heading_number("A Simple Model"), (None, "A Simple Model"))
        self.assertEqual(heading_number("B Proofs", in_appendix=True), ("B", "Proofs"))
        self.assertEqual(heading_number("A. Proofs"), ("A", "Proofs"))

    def test_roman_numbered_sections_are_sections_and_the_letters_under_them_subsections(self):
        """An IEEE-style paper: "I. Introduction" is section one, not appendix I, and "C. Results" is not section 100."""
        headings = Headings()
        read = [headings.read(text) for text in (
            "I. Introduction", "II. Related Work", "A. Datasets", "B. Metrics", "C. Results", "III. Method",
            "IV. Conclusion", "References", "Appendix", "A. Proofs",
        )]
        self.assertEqual([(item["number"], item["level"], item["appendix"]) for item in read], [
            ("I", 1, False), ("II", 1, False), ("A", 2, False), ("B", 2, False), ("C", 2, False), ("III", 1, False),
            ("IV", 1, False), (None, 1, False), (None, 1, True), ("A", 1, True),
        ])

    def test_the_appendix_is_found_by_its_header(self):
        self.assertTrue(is_appendix_heading("Appendix A: Proofs"))
        self.assertTrue(is_appendix_heading("Supplementary Information"))
        self.assertTrue(is_appendix_heading("Proofs", number="B.2"))
        self.assertFalse(is_appendix_heading("Methods", number="4"))

    def test_the_heading_regex_is_the_specs(self):
        self.assertEqual(environment_heading("Theorem 3 (Name). Every x."), ("theorem", "theorem", "3"))
        self.assertEqual(environment_heading("Algorithm 2 Sort"), ("algorithm", "algorithm", "2"))
        self.assertEqual(environment_heading("Corollary 1.2. So."), ("theorem", "corollary", "1.2"))
        self.assertIsNone(environment_heading("Remark 1. Not in the spec's list."))
        self.assertIsNone(environment_heading("The Theorem 1 of Smith"))

    def test_an_equation_number_is_the_parenthesis_a_display_ends_with(self):
        self.assertEqual(equation_number("y = mx + b, (1)"), "1")
        self.assertEqual(equation_number("a = b (A.2)"), "A.2")
        self.assertEqual(equation_number("a = b (12a)."), "12a")
        self.assertIsNone(equation_number("f(x) = (x + 1)"))

    def test_a_caption_names_its_kind_and_its_number(self):
        self.assertEqual(caption_number("Figure 2: Two panels"), ("figure", "2"))
        self.assertEqual(caption_number("Fig. 3 | Clustering"), ("figure", "3"))
        self.assertEqual(caption_number("Table II. Results"), ("table", "II"))
        self.assertEqual(caption_number("Supplementary Figure S4. x"), ("figure", "S4"))
        self.assertIsNone(caption_number("Figures are shown below"))

    def test_an_html_table_becomes_rows_of_cells(self):
        self.assertEqual(html_cells("<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td> 2 </td></tr></table>"), [["a", "b"], ["1", "2"]])


class TextLayerEnvironmentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = text_layer_environments([LAYOUT_PAGE, "Lemma 4. On the second page.\n"])

    def test_a_heading_in_the_second_column_of_a_two_column_line_is_found(self):
        titles = [item["title"] for item in self.found]
        self.assertIn("Lemma 1. Some tiny papers are tinier than others.", titles)
        self.assertIn("Algorithm 1 Do nothing, carefully", titles)
        self.assertIn("Theorem 1 (Tininess). Every tiny paper is tiny.", titles)

    def test_a_heading_that_opens_its_line_is_cut_where_the_other_column_begins(self):
        self.assertIn("Theorem 2. A heading that opens its line.", [item["title"] for item in self.found])

    def test_a_mention_in_a_sentence_is_not_a_heading(self):
        """"The proof of Lemma 1 is left to the reader" names a lemma; it does not open one."""
        self.assertEqual(len([item for item in self.found if item["environment"] == "lemma"]), 2)

    def test_the_locator_is_the_line_in_the_text_layer_and_pages_continue_the_count(self):
        lines = (LAYOUT_PAGE + "\f" + "Lemma 4. On the second page.\n").split("\n")
        for item in self.found:
            with self.subTest(item=item["title"]):
                line = lines[int(item["locator"].split(":")[1]) - 1]
                self.assertIn(item["title"][:12], line)
        self.assertEqual([item["page"] for item in self.found if item["number"] == "4"], [2])

    def test_every_one_is_an_algorithm_or_a_theorem_with_its_number(self):
        self.assertEqual(sorted((item["kind"], item["environment"], item["number"]) for item in self.found), [
            ("algorithm", "algorithm", "1"), ("theorem", "lemma", "1"), ("theorem", "lemma", "4"),
            ("theorem", "theorem", "1"), ("theorem", "theorem", "2"),
        ])


# --- the converters' outputs ------------------------------------------------------------------------


class DoclingItemsTest(unittest.TestCase):
    """The recorded `DoclingDocument` of the fixture, and the failure modes docling showed on it."""

    @classmethod
    def setUpClass(cls):
        cls.document = read_json(RECORDED / "docling" / "document.json")
        cls.meta = read_json(RECORDED / "docling" / "meta.json")
        cls.record = docling_items(cls.document, cls.meta)

    def test_the_recording_is_docling_with_formula_enrichment(self):
        self.assertEqual((self.meta["version"], self.meta["formula_enrichment"]), ("2.126.0", True))
        self.assertNotIn("data:", json.dumps(self.document), "the helper drops the base64 images docling embeds")

    def test_the_title_docling_calls_a_heading_is_the_title_and_not_a_section(self):
        self.assertEqual(self.record["title"], "A tiny two-column paper, written for the PDF inventory")

    def test_numbers_and_levels_come_from_the_heading_text(self):
        """docling gives every heading level 1; "1.1 Scope" is a level-2 section numbered 1.1."""
        self.assertEqual([(item.get("number"), item["title"], item["level"]) for item in self.record["sections"]], [
            (None, "Abstract", 1), ("1", "Introduction", 1), ("1.1", "Scope", 2), ("2", "Method", 1),
            ("3", "Results", 1), (None, "References", 1),
        ])

    def test_the_lettered_heading_after_numbered_sections_is_the_appendix(self):
        self.assertEqual([(item["number"], item["title"], item["kind"]) for item in self.record["appendices"]], [("A", "Proof of the lemma", "appendix")])

    def test_every_item_keeps_its_page_and_a_bbox_from_the_top_left(self):
        for key in ("sections", "equations", "figures", "tables", "algorithms", "theorems"):
            for item in self.record[key]:
                with self.subTest(item=item["id"]):
                    self.assertIsInstance(item["page"], int)
                    left, top, right, bottom = item["bbox"]
                    self.assertTrue(0 <= left < right <= 612 and 0 <= top < bottom <= 792, item["bbox"])
                    self.assertEqual(item["provenance"], DOCLING)
                    self.assertTrue(item["locator"].startswith("source/paper.pdf#page="))

    def test_equation_latex_is_ocr_derived_and_the_number_is_the_readers_to_confirm(self):
        first = self.record["equations"][0]
        self.assertEqual((first["number"], first["latex"], first["ocr"]), ("1", "y = m x + b ,", True))
        self.assertEqual(first["confirm_fields"], ["latex", "number"])
        self.assertIsNone(self.record["equations"][1].get("number"), "a display the paper does not number gets none")

    def test_numbers_docling_split_off_an_aligned_display_are_recovered_from_beside_it(self):
        """The "(2)" and the "(3) The proof of..." items sit level with the display, one of them in the next column."""
        self.assertEqual(self.record["equations"][2]["number"], "2-3")

    def test_a_caption_docling_did_not_link_goes_to_the_figure_on_its_page_and_asks_a_reader(self):
        first = self.record["figures"][0]
        self.assertEqual((first["number"], first["caption"][:9]), ("1", "Figure 1:"))
        self.assertEqual(first["confirm_fields"], ["caption", "meaning"])
        self.assertEqual(self.record["figures"][1]["confirm_fields"], ["meaning"], "a linked caption is not a guess")

    def test_a_table_keeps_its_cells_and_its_caption(self):
        table = self.record["tables"][0]
        self.assertEqual(table["cells"], [["Run", "Input", "Output"], ["first", "1", "0"], ["second", "2", "0"], ["third", "3", "0"]])
        self.assertEqual((table["number"], table["caption"]), ("1", "Table 1: Numbers the method produced."))

    def test_algorithms_and_theorems_come_from_the_heading_regex_and_leave_their_boundaries_open(self):
        self.assertEqual([(item["environment"], item["number"]) for item in self.record["algorithms"] + self.record["theorems"]],
                         [("algorithm", "1"), ("theorem", "1"), ("lemma", "1")])
        for item in self.record["algorithms"] + self.record["theorems"]:
            self.assertEqual(item["confirm_fields"], ["boundary"])

    def test_every_picture_and_table_image_is_named(self):
        self.assertEqual(self.record["images"], {"fig-1": "pictures/picture-1.png", "fig-2": "pictures/picture-2.png", "tab-1": "tables/table-1.png"})

    def test_without_formula_enrichment_no_equation_carries_latex(self):
        record = docling_items(self.document, dict(self.meta, formula_enrichment=False))
        self.assertEqual([item.get("latex") for item in record["equations"]], [None, None, None])
        self.assertTrue(any("formula enrichment" in note for note in record["notes"]))


def synthetic_docling(*items, pages=2):
    """A `DoclingDocument` of the given items in reading order, with TOPLEFT boxes on letter pages.

    Each item is `(collection, fields)`: `texts`, `pictures`, or `tables`. A `caption` field on a
    picture or a table becomes a caption text item linked to it.
    """
    document = {"body": {"children": []}, "texts": [], "pictures": [], "tables": [], "groups": [],
                "pages": {str(page): {"size": {"width": 612.0, "height": 792.0}} for page in range(1, pages + 1)}}
    for collection, fields in items:
        fields = dict(fields)
        page, box = fields.pop("page", 1), fields.pop("bbox", [72, 72, 300, 90])
        entry = dict(fields, self_ref="#/%s/%d" % (collection, len(document[collection])),
                     prov=[{"page_no": page, "bbox": {"l": box[0], "t": box[1], "r": box[2], "b": box[3], "coord_origin": "TOPLEFT"}}])
        caption = entry.pop("caption", None)
        if caption is not None:
            reference = {"$ref": "#/texts/%d" % len(document["texts"])}
            document["texts"].append({"self_ref": reference["$ref"], "label": "caption", "text": caption, "prov": entry["prov"]})
            entry["captions"] = [reference]
        document[collection].append(entry)
        document["body"]["children"].append({"$ref": entry["self_ref"]})
    return document


class DoclingFailureModesTest(unittest.TestCase):
    """What the live papers of `docs/verification/m3.md` showed docling doing, each on a document built to show it."""

    META = {"version": "2.126.0", "formula_enrichment": True, "images": {}}

    def test_numbers_the_formula_model_read_into_the_latex_are_taken_off_the_row_ends(self):
        self.assertEqual(latex_equation_numbers("a & = b , \\quad & ( 1 2 ) \\\\ c & = d \\tag{13} \\end{matrix}"), ["12", "13"])
        self.assertEqual(latex_equation_numbers("\\frac { 1 } { 2 } ( x + 1 )"), [])
        record = docling_items(synthetic_docling(("texts", {"label": "formula", "text": "L = K L ( P \\| Q ) , \\quad & ( 2 ) \\\\", "orig": "L = KL(P||Q), (2)x"})), self.META)
        self.assertEqual(record["equations"][0]["number"], "2")

    def test_a_label_drawn_inside_a_figure_is_not_a_heading(self):
        record = docling_items(synthetic_docling(
            ("texts", {"label": "section_header", "text": "1 Introduction", "page": 1}),
            ("pictures", {"label": "picture", "page": 2, "bbox": [100, 100, 500, 500], "caption": "Figure 1: Heads."}),
            ("texts", {"label": "section_header", "text": "Input-Input Layer5", "page": 2, "bbox": [150, 150, 300, 160]}),
        ), self.META)
        self.assertEqual([item["title"] for item in record["sections"]], ["Introduction"])
        self.assertEqual(record["counts"]["headings_inside_figures"], 1)

    def test_an_unnumbered_label_just_above_a_figure_in_a_numbered_paper_is_figure_text(self):
        """The Attention paper's "Input-Input Layer5" sits 50 pt above Figure 4; "References" below a figure is still a heading."""
        record = docling_items(synthetic_docling(
            ("texts", {"label": "section_header", "text": "1 Introduction", "page": 1}),
            ("texts", {"label": "section_header", "text": "2 Method", "page": 1, "bbox": [72, 200, 300, 212]}),
            ("texts", {"label": "section_header", "text": "3 Results", "page": 2, "bbox": [72, 40, 300, 52]}),
            ("texts", {"label": "section_header", "text": "Input-Input Layer5", "page": 2, "bbox": [108, 101, 279, 121]}),
            ("pictures", {"label": "picture", "page": 2, "bbox": [108, 170, 501, 604], "caption": "Figure 4: Two heads."}),
            ("texts", {"label": "section_header", "text": "References", "page": 2, "bbox": [108, 620, 200, 632]}),
        ), self.META)
        self.assertEqual([item["title"] for item in record["sections"]], ["Introduction", "Method", "Results", "References"])
        self.assertEqual(record["counts"]["headings_inside_figures"], 1)

    def test_in_a_paper_that_numbers_no_heading_a_heading_near_a_figure_stays(self):
        record = docling_items(synthetic_docling(
            ("pictures", {"label": "picture", "page": 1, "bbox": [50, 50, 550, 600], "caption": "Fig. 1 The workflow."}),
            ("texts", {"label": "section_header", "text": "Results", "page": 1, "bbox": [44, 640, 74, 648]}),
            ("texts", {"label": "section_header", "text": "Application to macaque retina data", "page": 1, "bbox": [60, 610, 300, 620]}),
        ), self.META)
        self.assertEqual([item["title"] for item in record["sections"]], ["Results", "Application to macaque retina data"])

    def test_a_table_whose_caption_calls_it_a_figure_is_a_figure(self):
        record = docling_items(synthetic_docling(
            ("tables", {"label": "table", "page": 2, "bbox": [50, 50, 550, 300], "caption": "Fig. 10 Comparison with different methods.", "data": {"grid": [[{"text": "a"}]]}}),
        ), self.META)
        self.assertEqual((record["tables"], record["figures"][0]["number"]), ([], "10"))
        self.assertEqual(record["counts"]["tables_captioned_as_figures"], 1)

    def test_a_small_uncaptioned_picture_joins_the_captioned_figure_on_its_page_or_is_left_out(self):
        document = synthetic_docling(
            ("pictures", {"label": "picture", "page": 1, "bbox": [33, 19, 169, 72]}),
            ("pictures", {"label": "picture", "page": 2, "bbox": [174, 94, 240, 219]}),
            ("pictures", {"label": "picture", "page": 2, "bbox": [347, 71, 467, 238], "caption": "Figure 2: (left) One. (right) Two."}),
        )
        record = docling_items(document, dict(self.META, images={"#/pictures/2": "pictures/picture-3.png"}))
        self.assertEqual([(item["id"], item["number"], item["bbox"]) for item in record["figures"]], [("fig-1", "2", [174, 71, 467, 238])])
        self.assertEqual(record["images"], {"fig-1": "pictures/picture-3.png"})
        self.assertEqual((record["counts"]["pictures_folded_into_figures"], record["counts"]["small_pictures_left_out"]), (1, 1))
        self.assertTrue(any("badge" in note for note in record["notes"]))


class MarkerItemsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = marker_items(read_json(SAMPLES / "marker.json"), {"version": "2.0.0", "images": {"/page/0/Figure/6": "pictures/picture-1.png"}})

    def test_pages_come_from_the_block_ids_counted_from_one(self):
        self.assertEqual([item["page"] for item in self.record["sections"] + self.record["appendices"]], [1, 2])

    def test_headings_equations_and_theorems(self):
        self.assertEqual((self.record["sections"][0]["number"], self.record["appendices"][0]["number"]), ("1", "A"))
        equation = self.record["equations"][0]
        self.assertEqual((equation["number"], equation["latex"], equation["provenance"]), ("1", "y = m x + b \\tag{1}", "marker-2.0.0"))
        self.assertEqual([(item["environment"], item["number"]) for item in self.record["theorems"] + self.record["algorithms"]],
                         [("theorem", "1"), ("algorithm", "1")])

    def test_a_caption_after_its_figure_belongs_to_it_and_one_before_its_table_is_paired_by_page(self):
        figure, table = self.record["figures"][0], self.record["tables"][0]
        self.assertEqual((figure["number"], figure["confirm_fields"]), ("1", ["meaning"]))
        self.assertEqual((table["number"], table["cells"]), ("1", [["Run", "Output"], ["first", "0"]]))
        self.assertIn("caption", table["confirm_fields"])
        self.assertEqual(self.record["images"], {"fig-1": "pictures/picture-1.png"})


class MineruItemsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = mineru_items(read_json(SAMPLES / "mineru_content_list.json"), {"version": "3.4.5", "images": {"3": "pictures/picture-1.png"}})

    def test_the_content_list_becomes_items_with_pages_and_no_bbox(self):
        self.assertEqual(self.record["sections"][0]["number"], "1")
        self.assertEqual(self.record["appendices"][0]["title"], "Appendix A. Proofs")
        for key in ("sections", "equations", "figures", "tables"):
            for item in self.record[key]:
                self.assertNotIn("bbox", item, "MinerU's bbox is not in points, so a reader opens the page")
        self.assertEqual(self.record["tables"][0]["page"], 2)

    def test_captions_arrive_attached_and_equations_carry_their_tag(self):
        self.assertEqual((self.record["figures"][0]["number"], self.record["tables"][0]["number"]), ("1", "1"))
        self.assertEqual(self.record["tables"][0]["cells"], [["Run", "Output"], ["first", "0"]])
        self.assertEqual(self.record["equations"][0]["number"], "1")
        self.assertEqual(self.record["theorems"][0]["environment"], "lemma")
        self.assertEqual(self.record["images"], {"fig-1": "pictures/picture-1.png"})


class GrobidTest(unittest.TestCase):
    TEI = (SAMPLES / "grobid.tei.xml").read_text(encoding="utf-8")

    def test_the_header_gives_the_title_the_authors_and_the_doi(self):
        metadata, _ = grobid_tei(self.TEI, "0.9.1")
        self.assertEqual(metadata, {"title": "A tiny two-column paper, written for the PDF inventory", "authors": ["The Suite"], "doi": "10.0000/tiny.2026.1"})

    def test_every_biblstruct_of_the_bibliography_is_a_reference_and_the_headers_is_not(self):
        _, references = grobid_tei(self.TEI, "0.9.1")
        self.assertEqual([(item["key"], item["title"], item["year"]) for item in references],
                         [("b0", "The TeXbook", "1984"), ("b1", "A Document Preparation System", "1994")])
        self.assertEqual(references[0]["authors"], ["D E Knuth"])
        self.assertEqual((references[1]["doi"], references[1]["page"], references[1]["locator"]), ("10.0000/latex.1994", 2, "source/paper.pdf#page=2"))
        self.assertEqual(references[0]["bbox"], [72.0, 380.1, 301.0, 400.1], "GROBID's page,x,y,w,h becomes a bbox from the top left")
        self.assertEqual({item["provenance"] for item in references}, {"grobid-0.9.1"})

    def grobid_runner(self, alive_after=0, calls=None):
        calls = [] if calls is None else calls
        state = {"checks": 0}

        def run(argv, cwd=None, timeout=None):
            argv = [str(part) for part in argv]
            calls.append(argv)
            if argv[0] == "docker":
                return ToolOutput(0, b"container\n", b"")
            if argv[-1].endswith("/api/isalive"):
                state["checks"] += 1
                return ToolOutput(0 if state["checks"] > alive_after else 7, b"true", b"")
            if argv[-1].endswith("/api/version"):
                return ToolOutput(0, b"0.9.1", b"")
            if argv[-1].endswith("/api/processFulltextDocument"):
                return ToolOutput(0, self.TEI.encode("utf-8"), b"")
            return ToolOutput(127, b"", b"")

        return run, calls

    def test_a_server_that_answers_is_used_through_curl(self):
        run, calls = self.grobid_runner()
        metadata, references, provenance, notes = grobid_references("/tmp/paper.pdf", Tools("/nonexistent", {}), run, sleep=lambda s: None)
        self.assertEqual((provenance, len(references), metadata["doi"]), ("grobid-0.9.1", 2, "10.0000/tiny.2026.1"))
        posted = [argv for argv in calls if argv[-1].endswith("processFulltextDocument")][0]
        self.assertEqual(posted[0], "curl")
        self.assertIn("input=@/tmp/paper.pdf", posted)
        self.assertIn("consolidateCitations=1", posted)
        self.assertFalse(any(argv[0] == "docker" for argv in calls))

    def test_the_container_publishes_the_port_the_url_names(self):
        run, calls = self.grobid_runner(alive_after=1)
        tools = Tools("/nonexistent", {"docker_images": {"grobid": "grobid/grobid:0.9.1-crf"}})
        grobid_references("/tmp/paper.pdf", tools, run, sleep=lambda s: None, url="http://localhost:9090")
        started = [argv for argv in calls if argv[:2] == ["docker", "run"]][0]
        self.assertIn("9090:8070", started)
        self.assertTrue(all(argv[-1].startswith("http://localhost:9090/") for argv in calls if argv[0] == "curl"))

    def test_an_installed_image_is_started_for_the_document_and_stopped_after(self):
        run, calls = self.grobid_runner(alive_after=2)
        tools = Tools("/nonexistent", {"docker_images": {"grobid": "grobid/grobid:0.9.1-crf"}})
        _, references, provenance, _ = grobid_references("/tmp/paper.pdf", tools, run, sleep=lambda s: None)
        self.assertEqual((provenance, len(references)), ("grobid-0.9.1", 2))
        dockers = [argv[:2] for argv in calls if argv[0] == "docker"]
        self.assertEqual(dockers, [["docker", "run"], ["docker", "stop"]])

    def test_no_server_and_no_image_is_converter_none_with_a_note(self):
        run, _ = self.grobid_runner(alive_after=99)
        metadata, references, provenance, notes = grobid_references("/tmp/paper.pdf", Tools("/nonexistent", {}), run, sleep=lambda s: None)
        self.assertEqual((metadata, references, provenance), ({}, [], "none"))
        self.assertTrue(any("wayline tools install --grobid" in note for note in notes))


# --- the whole chain, into a project ------------------------------------------------------------------


class PdfChainTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)
        self.dossier()
        self.tools = fake_tools(self.temp / "tools")

    def dossier(self, slug=SLUG, **open_access):
        write_l0(self.ledger, l0_dossier({
            "existence": "verified", "resolved_by": "crossref",
            "query": {"kind": "doi", "value": "10.0000/tiny"}, "identifiers": {"doi": "10.0000/tiny"},
            "metadata": {"title": "A tiny two-column paper"}, "abstract": None, "open_access": open_access, "attempts": [],
        }, slug))

    def build(self, missing=(), tools=None, recorded=RECORDED, pdf=PDF, calls=None, **options):
        replay = recorded_runner(recorded, missing)

        def run(argv, cwd=None, timeout=None):
            if calls is not None:
                calls.append([str(part) for part in argv])
            return replay(argv, cwd, timeout)

        return build_inventory(self.project, SLUG, pdf=pdf, tools=tools or self.tools, run=run, email=EMAIL, **options)

    def ref(self, *parts):
        return self.project.joinpath("research", REFS, SLUG, *parts)

    def test_the_inventory_validates_and_every_field_names_what_filled_it(self):
        inventory = self.build()
        self.assertEqual(validate(read_json(self.ref("inventory.json")), load_schema("inventory")), [])
        self.assertEqual(inventory["source_type"], "pdf")
        provenance = inventory["provenance"]
        for key in ("sections", "appendices", "equations", "figures", "tables", "algorithms", "theorems"):
            self.assertEqual(provenance[key], DOCLING, key)
        self.assertEqual((provenance["page_count"], provenance["text_layer"], provenance["raw_images"]),
                         ("pdfinfo-" + POPPLER, "pdftotext-" + POPPLER, "pdfimages-" + POPPLER))
        self.assertEqual((provenance["boxes"], provenance["references"]), ("pdfplumber-0.11.10", "none"))
        source = inventory["source"]
        self.assertEqual((source["converter"], source["references_by"], source["formula_enrichment"]), (DOCLING, "none", True))

    def test_the_counts_are_the_fixtures_by_eye_counts(self):
        counts = self.build()["counts"]
        self.assertEqual({key: counts[key] for key in (
            "pages", "sections", "appendices", "equations", "numbered_equations", "figures", "figure_files",
            "tables", "algorithms", "theorems", "raw_images", "ruled_tables")}, {
            "pages": 2, "sections": 6, "appendices": 1, "equations": 3, "numbered_equations": 2, "figures": 2,
            "figure_files": 2, "tables": 1, "algorithms": 1, "theorems": 2, "raw_images": 2, "ruled_tables": 1,
        })

    def test_the_converter_runs_as_a_subprocess_of_the_tools_venv(self):
        calls = []
        self.build(calls=calls)
        docling = [argv for argv in calls if argv[1:2] == [str(CONVERTERS_DIR / "docling_convert.py")]]
        self.assertEqual(len(docling), 1)
        self.assertEqual(docling[0][0], str(self.tools.python))

    def test_the_pdf_is_kept_under_source_which_no_commit_ever_carries(self):
        inventory = self.build()
        self.assertEqual(self.ref("source", "paper.pdf").read_bytes(), PDF.read_bytes())
        self.assertEqual(inventory["source"]["main"], "source/paper.pdf")
        self.assertEqual(inventory["source"]["url"], "file:tiny-paper.pdf", "where the owner keeps the PDF is not committed")
        self.assertIn("research/refs/*/source/", (self.project / ".gitignore").read_text(encoding="utf-8").splitlines())

    def test_the_text_layer_and_the_boxes_are_written_beside_it(self):
        inventory = self.build()
        self.assertIn("Theorem 1 (Tininess)", self.ref("text.txt").read_text(encoding="utf-8"))
        self.assertEqual(inventory["text_layer"]["path"], "text.txt")
        self.assertEqual(len(read_json(self.ref("source", "boxes.json"))["pages"]), 2)
        self.assertEqual((inventory["boxes"]["path"], inventory["boxes"]["pages"]), ("source/boxes.json", 2))
        self.assertGreater(inventory["boxes"]["chars"], inventory["boxes"]["words"])

    def test_every_embedded_image_is_listed_with_its_page_and_size(self):
        images = self.build()["raw_images"]
        self.assertEqual([(image["path"], image["width"], image["height"]) for image in images], [
            ("source/paper.pdf#page=1&image=0", 320, 180), ("source/paper.pdf#page=2&image=1", 640, 200),
        ])

    def test_figures_and_tables_get_image_files_a_reader_opens(self):
        inventory = self.build()
        for item in inventory["figures"] + inventory["tables"]:
            with self.subTest(item=item["id"]):
                self.assertEqual(item["file"], "figures/%s.png" % item["id"])
                self.assertEqual(self.ref(item["file"]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_the_notes_tell_the_reader_pass_what_to_confirm(self):
        notes = self.build()["notes"]
        self.assertTrue(any(note.startswith("the reader pass confirms:") and "latex on 3" in note for note in notes), notes)
        self.assertTrue(any("GROBID" in note for note in notes))

    def test_without_converters_the_poppler_layer_still_works(self):
        inventory = self.build(tools=Tools(self.temp / "no-tools", {}))
        provenance = inventory["provenance"]
        self.assertEqual((inventory["source"]["converter"], provenance["sections"], provenance["figures"]), ("none", "none", "none"))
        self.assertEqual((provenance["page_count"], provenance["algorithms"]), ("pdfinfo-" + POPPLER, "pdftotext-" + POPPLER))
        self.assertEqual((inventory["counts"]["algorithms"], inventory["counts"]["theorems"], inventory["page_count"]), (1, 2, 2))
        self.assertTrue(inventory["theorems"][0]["locator"].startswith("text.txt:"))
        self.assertTrue(any("wayline tools install" in note for note in inventory["notes"]))
        self.assertIsNone(inventory["boxes"])

    def test_pdfplumber_alone_still_finds_the_ruled_table(self):
        inventory = self.build(tools=fake_tools(self.temp / "plumber-only", packages=("pdfplumber",)))
        table = inventory["tables"][0]
        self.assertEqual((table["provenance"], table["page"]), ("pdfplumber-0.11.10", 2))
        self.assertEqual(table["cells"][0], ["Run", "Input", "Output"])
        self.assertEqual(table["confirm_fields"], ["caption", "cells"], "rows without rules between them come back merged")

    def test_without_pdfplumber_the_boxes_are_skipped_with_a_note(self):
        inventory = self.build(tools=fake_tools(self.temp / "docling-only", packages=("docling",)))
        self.assertIsNone(inventory["boxes"])
        self.assertTrue(any("pdfplumber is not in the tools venv" in note for note in inventory["notes"]))
        self.assertEqual(inventory["provenance"]["sections"], DOCLING)

    def test_without_poppler_the_structure_still_comes_from_the_converter(self):
        inventory = self.build(missing=("pdfinfo", "pdftotext", "pdfimages"))
        self.assertEqual((inventory["page_count"], inventory["text_layer"], inventory["raw_images"]), (None, None, []))
        self.assertEqual((inventory["provenance"]["page_count"], inventory["provenance"]["sections"]), ("none", DOCLING))
        self.assertTrue(any("poppler is not installed" in note for note in inventory["notes"]))

    def test_when_docling_fails_marker_is_tried_next(self):
        recorded = self.temp / "recorded"
        shutil.copytree(RECORDED, recorded)
        (recorded / "marker").mkdir()
        shutil.copyfile(SAMPLES / "marker.json", recorded / "marker" / "document.json")
        (recorded / "marker" / "meta.json").write_text(json.dumps({"version": "2.0.0", "formula_enrichment": True, "images": {}}), encoding="utf-8")
        tools = fake_tools(self.temp / "fallbacks", packages=("docling", "pdfplumber", "marker"))
        inventory = self.build(missing=("docling",), tools=tools, recorded=recorded)
        self.assertEqual((inventory["source"]["converter"], inventory["provenance"]["equations"]), ("marker-2.0.0", "marker-2.0.0"))
        self.assertTrue(any(note.startswith("docling failed on this document") for note in inventory["notes"]))
        self.assertTrue(any("never tried: mineru" in note for note in inventory["notes"]))

    def test_when_every_converter_fails_the_fields_say_none_and_why(self):
        tools = fake_tools(self.temp / "all", packages=("docling", "pdfplumber", "marker", "mineru"))
        inventory = self.build(missing=("docling", "marker", "mineru"), tools=tools)
        self.assertEqual((inventory["source"]["converter"], inventory["provenance"]["equations"]), ("none", "none"))
        for name in ("docling", "marker", "mineru"):
            self.assertTrue(any(note.startswith("%s failed" % name) for note in inventory["notes"]), name)

    def test_grobid_fills_the_references_and_the_metadata_when_it_answers(self):
        tei = (SAMPLES / "grobid.tei.xml").read_bytes()
        replay = recorded_runner(RECORDED)

        def run(argv, cwd=None, timeout=None):
            argv = [str(part) for part in argv]
            if argv[0] == "curl":
                if argv[-1].endswith("/api/version"):
                    return ToolOutput(0, b"0.9.1", b"")
                return ToolOutput(0, tei if argv[-1].endswith("processFulltextDocument") else b"true", b"")
            return replay(argv, cwd, timeout)

        inventory = build_inventory(self.project, SLUG, pdf=PDF, tools=self.tools, run=run, email=EMAIL)
        self.assertEqual((inventory["source"]["references_by"], inventory["provenance"]["metadata"]), ("grobid-0.9.1", "grobid-0.9.1"))
        self.assertEqual(len(inventory["references"]), 2)
        self.assertEqual(inventory["metadata"]["doi"], "10.0000/tiny.2026.1")

    def test_a_second_pass_keeps_the_created_time_and_remakes_the_figure_files(self):
        first = self.build()
        stale = self.ref("figures", "fig-9.png")
        stale.write_bytes(b"\x89PNG\r\n\x1a\n")
        second = self.build()
        self.assertEqual(second["created"], first["created"])
        self.assertIn("updated", second)
        self.assertFalse(stale.exists())
        self.assertEqual(second["source"]["sha256"], first["source"]["sha256"])

    def test_a_kept_pdf_is_read_again_without_being_handed_over(self):
        first = self.build()
        again = build_inventory(self.project, SLUG, tools=self.tools, run=recorded_runner(RECORDED), email=EMAIL)
        self.assertEqual((again["source"]["url"], again["source"]["sha256"]), (first["source"]["url"], first["source"]["sha256"]))
        self.assertEqual(again["counts"]["figures"], 2)

    def test_the_open_access_pdf_the_scout_found_is_fetched_when_there_is_no_other(self):
        url = "https://example.org/tiny.pdf"
        self.dossier(pdf_url=url)
        fetcher = served({url: (200, {"content-type": "application/pdf"}, PDF.read_bytes())})
        inventory = build_inventory(self.project, SLUG, fetcher=fetcher, tools=Tools(self.temp / "none", {}),
                                    run=recorded_runner(RECORDED), email=EMAIL)
        self.assertEqual(inventory["source"]["url"], url)
        self.assertEqual(self.ref("source", "paper.pdf").read_bytes(), PDF.read_bytes())

    def test_an_open_access_answer_that_is_not_a_pdf_asks_for_one_by_hand(self):
        url = "https://example.org/landing"
        self.dossier(pdf_url=url)
        fetcher = served({url: (200, {"content-type": "text/html"}, b"<html>a landing page</html>")})
        with self.assertRaises(ValueError) as caught:
            build_inventory(self.project, SLUG, fetcher=fetcher, tools=Tools(self.temp / "none", {}), run=recorded_runner(RECORDED), email=EMAIL)
        self.assertIn("--pdf", str(caught.exception))

    def test_a_heading_that_is_the_pdfs_own_title_is_not_a_section(self):
        from wayline.pdf_inventory import Conversion, Grobid, _assemble, new_record

        layer = {"poppler": POPPLER, "info": {"title": "Deep learning enables accurate clustering with batch effect removal", "pages": 1},
                 "text": "x", "pages": ["x"], "images": [], "boxes": None, "plumber_version": None, "notes": []}
        record = new_record()
        record["images"] = {}
        record["sections"] = [
            {"id": "sec-1", "kind": "section", "title": "Deep learning enables accurate clustering with batch", "page": 1, "locator": "p", "provenance": DOCLING},
            {"id": "sec-2", "kind": "section", "number": "1", "title": "Results", "page": 2, "locator": "p", "provenance": DOCLING},
        ]
        inventory = _assemble(self.ledger, SLUG, layer, Conversion(record, DOCLING, None, [], True), Grobid({}, [], "none", []), "source/paper.pdf")
        self.assertEqual([(item["id"], item["title"]) for item in inventory["sections"]], [("sec-1", "Results")])
        self.assertEqual(inventory["metadata"]["title"], layer["info"]["title"])

    def test_a_file_that_is_not_a_pdf_is_refused(self):
        fake = self.temp / "paper.pdf"
        fake.write_text("not a pdf", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build(pdf=fake)


class RecordingTest(unittest.TestCase):
    def test_what_the_recorder_writes_is_what_the_replay_answers_with(self):
        with contextlib.ExitStack() as stack:
            import tempfile

            target = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            lines = record_tool_outputs(PDF, target, tools=Tools(target / "none", {}), run=recorded_runner(RECORDED))
            for name in ("pdfinfo.txt", "pdftotext.txt", "pdfimages.txt", "pdfinfo-v.txt"):
                self.assertEqual((target / name).read_bytes(), (RECORDED / name).read_bytes(), name)
            self.assertIn("docling: not in the tools venv, nothing recorded", lines)


# --- the tools venv -----------------------------------------------------------------------------------


class ToolsInstallTest(ProjectTestCase):
    def runner(self, cuda="12.2", fail=None, probe=None):
        calls = []
        probe = probe or {"packages": {"docling": "2.126.0", "pdfplumber": "0.11.10", "torch": "2.14.0+cu126"}, "device": "cuda"}

        def run(argv, cwd=None, timeout=None, env=None):
            argv = [str(part) for part in argv]
            calls.append(argv)
            if argv[0] == "nvidia-smi":
                return ToolOutput(0, ("| NVIDIA-SMI 535.309.01   Driver Version: 535.309.01   CUDA Version: %s |" % cuda).encode(), b"") if cuda else ToolOutput(127, b"", b"")
            if fail and fail(argv):
                return ToolOutput(1, b"", b"ERROR: no matching distribution")
            if len(argv) > 1 and argv[1] == "-c":
                return ToolOutput(0, (json.dumps(probe) + "\n").encode(), b"")
            return ToolOutput(0, b"", b"")

        return run, calls

    def test_the_torch_index_follows_the_driver(self):
        self.assertEqual([torch_index(value) for value in (None, (11, 8), (12, 2), (13, 0))], ["cpu", "cu118", "cu126", None])

    def test_the_driver_cuda_version_is_read_off_nvidia_smi(self):
        run, _ = self.runner("12.2")
        self.assertEqual(driver_cuda(run), (12, 2))
        run, _ = self.runner(None)
        self.assertIsNone(driver_cuda(run))

    def test_torch_comes_before_the_converters_and_extras_are_only_on_request(self):
        steps = install_steps(self.temp / "tools", cuda=(12, 2), python="/usr/bin/python3", uv="/bin/uv")
        self.assertEqual([name for name, _ in steps], ["venv", "torch", "converters"])
        self.assertIn("https://download.pytorch.org/whl/cu126", steps[1][1])
        self.assertEqual(steps[2][1][-2:], ["docling", "pdfplumber"])
        with_extras = install_steps(self.temp / "tools", extras=("marker", "mineru"), cuda=None, uv=None)
        self.assertEqual([name for name, _ in with_extras], ["venv", "torch", "converters"], "no python -m venv, no pip")
        self.assertEqual(with_extras[0][1][0], str(self.temp / "tools" / "bin" / "uv"), "the harness's own uv")
        self.assertIn("https://download.pytorch.org/whl/cpu", with_extras[1][1])
        self.assertEqual(with_extras[2][1][-4:], ["docling", "pdfplumber", "marker-pdf", "mineru[pipeline]"])

    def test_the_install_records_what_the_venv_holds(self):
        run, calls = self.runner()
        root = self.temp / "tools"
        record = install(root=root, run=run, uv="/bin/uv", python="/usr/bin/python3")
        written = read_json(root / TOOLS_JSON)
        self.assertEqual(written, record)
        self.assertEqual((record["packages"]["docling"], record["device"], record["torch_index"], record["driver_cuda"]), ("2.126.0", "cuda", "cu126", "12.2"))
        self.assertEqual(Tools(root).version("docling"), "2.126.0")
        self.assertFalse(any(argv[0] == "docker" for argv in calls), "GROBID only on request")

    def test_a_venv_that_exists_is_installed_into_again(self):
        root = self.temp / "tools"
        (root / "venv" / "bin").mkdir(parents=True)
        (root / "venv" / "bin" / "python").touch()
        run, calls = self.runner()
        install(extras=("marker",), root=root, run=run, uv="/bin/uv")
        self.assertFalse(any("venv" in argv[1:2] for argv in calls if argv[0] == "/bin/uv"))
        self.assertTrue(any("marker-pdf" in argv for argv in calls))

    def test_a_failed_step_is_an_error_that_names_it(self):
        run, _ = self.runner(fail=lambda argv: "docling" in argv)
        with self.assertRaises(ToolsError) as caught:
            install(root=self.temp / "tools", run=run, uv="/bin/uv")
        self.assertIn("converters", str(caught.exception))
        self.assertFalse((self.temp / "tools" / TOOLS_JSON).exists())

    def test_a_gpu_torch_cannot_see_is_said_in_the_record(self):
        run, _ = self.runner(probe={"packages": {"docling": "2.126.0"}, "device": "cpu"})
        record = install(root=self.temp / "tools", run=run, uv="/bin/uv")
        self.assertTrue(any("cannot see the GPU" in note for note in record["notes"]))

    def test_grobid_is_pulled_on_request_and_a_failed_pull_is_a_note(self):
        run, _ = self.runner()
        self.assertEqual(install(grobid=True, root=self.temp / "a", run=run, uv="/bin/uv")["docker_images"], {"grobid": "grobid/grobid:0.9.1-crf"})
        run, _ = self.runner(fail=lambda argv: argv[0] == "docker")
        record = install(grobid=True, root=self.temp / "b", run=run, uv="/bin/uv")
        self.assertEqual(record["docker_images"], {})
        self.assertTrue(any("docker pull" in note for note in record["notes"]))

    def test_tools_show_says_when_nothing_is_installed(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["tools", "show"]), 1)
        self.assertIn("wayline tools install", err.getvalue())

    def test_the_dry_run_prints_the_steps_and_installs_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["tools", "install", "--dry-run"]), 0)
        self.assertIn("converters", out.getvalue())
        self.assertFalse((Path(os.environ["WAYLINE_HOME"]) / "tools").exists())


class PdfVerbTest(ProjectTestCase):
    def test_absorb_inventory_with_a_pdf_writes_the_inventory(self):
        project = self.temp / "project"
        init_project(project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        write_l0(Ledger(project), l0_dossier({
            "existence": "verified", "resolved_by": "crossref", "query": {"kind": "doi", "value": "10.0000/tiny"},
            "identifiers": {"doi": "10.0000/tiny"}, "metadata": {"title": "A tiny paper"}, "abstract": None,
            "open_access": {}, "attempts": [],
        }, SLUG))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["absorb", "--inventory", SLUG, "--pdf", str(PDF), "--project", str(project)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("converter none", out.getvalue())
        inventory = read_json(project / "research" / REFS / SLUG / "inventory.json")
        self.assertEqual((inventory["source_type"], inventory["source"]["main"]), ("pdf", "source/paper.pdf"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
