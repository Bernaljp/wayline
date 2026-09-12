"""The arXiv e-print source and the LaTeX inventory, over a tarball written for this suite.

`fixtures/arxiv/tiny-paper.tar.gz` is a paper nobody wrote but the tests: the arXiv terms of use
forbid re-serving an e-print, so no real source is committed here and the live counts of
research-notes 06 are checked once, by hand, in `docs/verification/m3.md`.
"""

import base64
import contextlib
import gzip
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests.paths import FIXTURES_DIR
from tests.projects import ProjectTestCase
from wayline import TAG, cli
from wayline.dossier import (
    ARXIV_HTML, FLAT, INVENTORY, REFS, SOURCE, apply_aux_numbers, arxiv_source_url, aux_numbers,
    build_inventory, environments, extract_source, fetch_arxiv_source, flatten,
    html_inventory, l0_dossier, latex_inventory, main_tex, strip_comments, write_l0,
)
from wayline.fetch import Backend, FetchError, RATE_LIMITS, Fetcher, Request, Response, user_agent
from wayline.jsonschema import load_schema, validate
from wayline.ledger import Ledger
from wayline.project import init_project

ARXIV_FIXTURES = FIXTURES_DIR / "arxiv"
TARBALL = ARXIV_FIXTURES / "tiny-paper.tar.gz"
NO_LATEX = ARXIV_FIXTURES / "no-latex.tar.gz"
LATEXML = ARXIV_FIXTURES / "latexml.html"
IDENTIFIER = "2401.00001"
SLUG = "suite-2024-a-tiny-paper"
EMAIL = "owner@example.org"
ETAG = '"sha256:0f0f0f"'
TARBALL_HEADERS = {
    "content-type": "application/gzip",
    "content-disposition": 'attachment; filename="arXiv-%sv2.tar.gz"' % IDENTIFIER,
    "etag": ETAG,
}


class ServedBackend(Backend):
    """arXiv, as a dictionary: one canned answer per URL, and every request kept for the test."""

    def __init__(self, answers):
        self.answers = dict(answers)
        self.sent = []

    def send(self, request):
        self.sent.append(request)
        answer = self.answers.get(request.url)
        if answer is None:
            raise FetchError("nothing served for %s" % request.url)
        if callable(answer):
            return answer(request)
        status, headers, body = answer
        return Response(request.url, status, dict(headers), body)

    @property
    def urls(self):
        return [request.url for request in self.sent]


def served(answers, email=EMAIL):
    return Fetcher(ServedBackend(answers), email=email)


def tarball_answers(payload=None, html_page=None):
    """The two URLs the chain may ask for, with the ETag dance on the source."""
    body = payload if payload is not None else TARBALL.read_bytes()

    def source(request):
        if request.headers.get("If-None-Match") == ETAG:
            return Response(request.url, 304, {"etag": ETAG}, b"")
        return Response(request.url, 200, dict(TARBALL_HEADERS), body)

    answers = {arxiv_source_url(IDENTIFIER): source}
    if html_page is not None:
        answers[ARXIV_HTML % IDENTIFIER] = (200, {"content-type": "text/html"}, html_page)
    return answers


def tar_bytes(files, gzipped=True):
    """A tarball built in memory, for the members a fixture must not contain."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, payload in files:
            info = tarfile.TarInfo(name)
            if isinstance(payload, tuple):  # (link type, target)
                info.type, info.linkname = payload
                archive.addfile(info)
                continue
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(raw.getvalue()) if gzipped else raw.getvalue()


# --- the fetch ------------------------------------------------------------------------------------


class SourceFetchTest(unittest.TestCase):
    def test_the_url_is_the_export_host_of_the_research_note(self):
        self.assertEqual(arxiv_source_url("1706.03762"), "https://export.arxiv.org/src/1706.03762")
        self.assertEqual(arxiv_source_url("1706.03762v7"), "https://export.arxiv.org/src/1706.03762v7")

    def test_the_seam_paces_arxiv_at_one_request_every_three_seconds(self):
        """The terms of use ask for one request per 3 s on a single connection; the seam enforces both."""
        self.assertEqual(RATE_LIMITS["export.arxiv.org"], 3.0)
        self.assertEqual(RATE_LIMITS["arxiv.org"], 3.0)

    def test_the_request_carries_the_owners_address(self):
        fetcher = served(tarball_answers())
        fetch_arxiv_source(fetcher, IDENTIFIER)
        self.assertEqual(fetcher.backend.sent[0].headers["User-Agent"], user_agent(TAG, EMAIL))

    def test_the_tarball_comes_back_with_its_etag_and_its_version(self):
        fetched = fetch_arxiv_source(served(tarball_answers()), IDENTIFIER)
        self.assertEqual((fetched.kind, fetched.etag, fetched.version), ("tarball", ETAG, "v2"))
        self.assertFalse(fetched.from_cache)

    def test_a_known_etag_is_offered_and_the_answer_is_a_304(self):
        fetcher = served(tarball_answers())
        fetched = fetch_arxiv_source(fetcher, IDENTIFIER, etag=ETAG)
        self.assertEqual(fetcher.backend.sent[0].headers["If-None-Match"], ETAG)
        self.assertEqual((fetched.status, fetched.from_cache, fetched.payload), (304, True, b""))
        self.assertEqual(fetched.etag, ETAG)

    def test_a_pdf_only_submission_is_recognized_by_its_bytes(self):
        answers = {arxiv_source_url(IDENTIFIER): (200, {"content-type": "application/pdf"}, b"%PDF-1.4\n%%EOF\n")}
        self.assertEqual(fetch_arxiv_source(served(answers), IDENTIFIER).kind, "pdf")

    def test_a_pdf_served_without_its_content_type_is_still_a_pdf(self):
        answers = {arxiv_source_url(IDENTIFIER): (200, {}, b"%PDF-1.4\n%%EOF\n")}
        self.assertEqual(fetch_arxiv_source(served(answers), IDENTIFIER).kind, "pdf")

    def test_a_status_arxiv_does_not_answer_with_is_an_error(self):
        answers = {arxiv_source_url(IDENTIFIER): (404, {}, b"not found")}
        with self.assertRaises(ValueError):
            fetch_arxiv_source(served(answers), IDENTIFIER)


# --- unpacking ------------------------------------------------------------------------------------


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(self.enterContext(_temporary()))

    def test_the_fixture_unpacks_to_the_files_it_carries(self):
        files = extract_source(TARBALL.read_bytes(), self.temp)
        self.assertEqual(files, [
            "00README.json", "figures/diagram.pdf", "figures/plot.png",
            "ms.tex", "sections/intro.tex", "sections/method.tex",
        ])
        self.assertIn("documentclass", (self.temp / "ms.tex").read_text(encoding="utf-8"))

    def test_a_member_that_would_land_outside_the_directory_is_refused(self):
        payload = tar_bytes([("../escape.tex", b"no"), ("/absolute.tex", b"no"), ("ok.tex", b"\\documentclass{article}")])
        self.assertEqual(extract_source(payload, self.temp), ["ok.tex"])
        self.assertFalse((self.temp.parent / "escape.tex").exists())

    def test_a_symlink_member_is_refused(self):
        payload = tar_bytes([("link.tex", (tarfile.SYMTYPE, "/etc/passwd")), ("ok.tex", b"x")])
        self.assertEqual(extract_source(payload, self.temp), ["ok.tex"])
        self.assertFalse((self.temp / "link.tex").exists())

    def test_an_old_single_file_submission_is_one_gzipped_tex(self):
        payload = gzip.compress(b"\\documentclass{article}\\begin{document}old\\end{document}")
        self.assertEqual(extract_source(payload, self.temp), ["main.tex"])
        self.assertIn("old", (self.temp / "main.tex").read_text(encoding="utf-8"))

    def test_an_uncompressed_tar_is_unpacked_too(self):
        self.assertEqual(extract_source(tar_bytes([("ok.tex", b"x")], gzipped=False), self.temp), ["ok.tex"])


@contextlib.contextmanager
def _temporary():
    directory = tempfile.mkdtemp(prefix="wayline-inventory-test-")
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# --- the main file and the flattening ---------------------------------------------------------------


class MainFileTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(self.enterContext(_temporary()))

    def write(self, name, text):
        path = self.temp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_00readme_json_names_the_top_level_file(self):
        extract_source(TARBALL.read_bytes(), self.temp)
        self.assertEqual(str(main_tex(self.temp)), "ms.tex")

    def test_a_00readme_with_a_toplevelfile_line_names_it_too(self):
        self.write("00README.XXX", "paper.tex toplevelfile\nnotes.tex ignore\n")
        self.write("paper.tex", "\\documentclass{article}")
        self.write("notes.tex", "\\documentclass{article}")
        self.assertEqual(str(main_tex(self.temp)), "paper.tex")

    def test_without_a_readme_the_file_that_inputs_the_others_wins(self):
        self.write("standalone.tex", "\\documentclass{article}\\begin{document}x\\end{document}")
        self.write("paper.tex", "\\documentclass{article}\\input{one}\\input{two}")
        self.write("one.tex", "one")
        self.write("two.tex", "two")
        self.assertEqual(str(main_tex(self.temp)), "paper.tex")

    def test_a_documentclass_inside_a_comment_is_not_a_main_file(self):
        self.write("commented.tex", "% \\documentclass{article}\n")
        self.assertIsNone(main_tex(self.temp))

    def test_a_submission_with_no_latex_has_no_main_file(self):
        extract_source(NO_LATEX.read_bytes(), self.temp)
        self.assertIsNone(main_tex(self.temp))


class FlattenTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(self.enterContext(_temporary()))
        extract_source(TARBALL.read_bytes(), self.temp)

    def test_the_in_house_expander_inlines_every_input(self):
        text, flattened_by, notes = flatten(self.temp, "ms.tex", use_latexpand=False)
        self.assertEqual(flattened_by, "wayline")
        self.assertIn("A tiny paper needs a tiny introduction", text)
        self.assertIn("The method is one numbered equation", text)
        self.assertEqual(latex_inventory(text)["counts"]["unresolved_inputs"], 0)
        self.assertEqual(notes, [])

    def test_an_input_that_is_not_in_the_tarball_is_named_rather_than_dropped(self):
        (self.temp / "ms.tex").write_text("\\documentclass{article}\\input{missing}\n", encoding="utf-8")
        text, _, notes = flatten(self.temp, "ms.tex", use_latexpand=False)
        self.assertIn("\\input{missing}", text)
        self.assertTrue(any("missing" in note for note in notes))
        self.assertEqual(latex_inventory(text)["counts"]["unresolved_inputs"], 1)

    def test_a_file_that_inputs_itself_is_expanded_once(self):
        (self.temp / "ms.tex").write_text("\\documentclass{article}\\input{ms}\n", encoding="utf-8")
        text, _, _ = flatten(self.temp, "ms.tex", use_latexpand=False)
        self.assertEqual(text.count("documentclass"), 2)

    @unittest.skipUnless(shutil.which("latexpand"), "latexpand is not installed")
    def test_latexpand_and_the_in_house_expander_inventory_the_same_paper(self):
        with_tool, flattened_by, _ = flatten(self.temp, "ms.tex")
        without, _, _ = flatten(self.temp, "ms.tex", use_latexpand=False)
        self.assertTrue(flattened_by.startswith("latexpand-"), flattened_by)
        self.assertEqual(latex_inventory(with_tool)["counts"], latex_inventory(without)["counts"])

    def test_comments_are_stripped_and_the_lines_they_sat_on_stay(self):
        text = "one % gone\ntwo \\% kept % gone\nthree\n"
        self.assertEqual(strip_comments(text), "one \ntwo \\% kept \nthree\n")
        self.assertEqual(len(strip_comments(text).split("\n")), len(text.split("\n")))

    def test_the_flattened_paper_carries_no_comment(self):
        text, _, _ = flatten(self.temp, "ms.tex")
        self.assertNotIn("not in flat.tex", text)


# --- the inventory ------------------------------------------------------------------------------


class LatexInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with _temporary() as temp:
            extract_source(TARBALL.read_bytes(), temp)
            text, _, _ = flatten(temp, "ms.tex", use_latexpand=False)
        cls.text = text
        cls.record = latex_inventory(text)

    def test_the_counts_are_what_the_paper_carries(self):
        self.assertEqual(self.record["counts"], {
            "sections": 3, "appendices": 1, "section_headings": 4, "equations": 3, "figures": 2,
            "tables": 1, "algorithms": 1, "theorems": 2, "references": 1, "labels": 12,
            "captions": 4, "refs": 2, "unresolved_inputs": 0,
        })

    def test_a_starred_environment_is_counted_apart_from_its_unstarred_twin(self):
        self.assertEqual(self.record["environments"]["align"], 1)
        self.assertEqual(self.record["environments"]["align*"], 1)
        self.assertEqual(self.record["environments"]["figure"], 1)
        self.assertEqual(self.record["environments"]["figure*"], 1)

    def test_every_item_carries_an_id_a_locator_and_a_provenance(self):
        for key in ("sections", "appendices", "equations", "figures", "tables", "algorithms", "theorems"):
            for item in self.record[key]:
                with self.subTest(item=item["id"]):
                    self.assertRegex(item["locator"], r"^flat\.tex:\d+$")
                    self.assertEqual(item["provenance"], "latex")

    def test_the_locator_points_at_the_line_the_item_begins_on(self):
        lines = self.text.split("\n")
        for item in self.record["equations"] + self.record["figures"]:
            with self.subTest(item=item["id"]):
                line = lines[int(item["locator"].split(":")[1]) - 1]
                self.assertIn("\\begin{", line)

    def test_sections_are_numbered_in_document_order_and_the_appendix_gets_a_letter(self):
        self.assertEqual([(item["number"], item["title"]) for item in self.record["sections"]], [
            ("1", "Introduction"), ("1.1", "What is not in this paper"), ("2", "Method"),
        ])
        self.assertEqual(self.record["appendices"][0]["number"], "A")
        self.assertEqual(self.record["appendices"][0]["kind"], "appendix")

    def test_a_numbered_equation_is_numbered_and_a_starred_one_is_not(self):
        numbers = {item["environment"]: item.get("number") for item in self.record["equations"]}
        self.assertEqual(numbers["equation"], "1")
        self.assertIsNone(numbers["align*"])

    def test_a_multi_row_environment_takes_one_number_per_row(self):
        """`\\nonumber` and the star are honored, so the count after an align is the right one."""
        aligned = [item for item in self.record["equations"] if item["environment"] == "align"][0]
        self.assertEqual(aligned["number"], "2-3")

    def test_nonumber_takes_a_row_out_of_the_count(self):
        text = "\\begin{align}\na &= b \\\\\nc &= d \\nonumber\n\\end{align}\n\\begin{equation}e\\end{equation}"
        numbers = [item.get("number") for item in latex_inventory(text)["equations"]]
        self.assertEqual(numbers, ["1", "2"])

    def test_a_tag_is_taken_as_the_number_it_prints(self):
        text = "\\begin{equation}\\tag{$\\star$} x = 1 \\end{equation}\n\\begin{equation}y\\end{equation}"
        numbers = [item.get("number") for item in latex_inventory(text)["equations"]]
        self.assertEqual(numbers, ["$\\star$", "1"])

    def test_every_number_counted_here_asks_a_reader_to_confirm_it(self):
        for item in self.record["equations"] + self.record["figures"]:
            if item.get("number"):
                self.assertTrue(item.get("confirm"), item["id"])

    def test_a_figure_carries_its_caption_and_its_graphics_target(self):
        first = self.record["figures"][0]
        self.assertEqual(first["caption"], "A plot of nothing against nothing.")
        self.assertEqual(first["graphics"], ["plot"])
        self.assertEqual(first["label"], "fig:plot")

    def test_a_table_keeps_its_source_in_exact_form(self):
        table = self.record["tables"][0]
        self.assertIn("\\begin{tabular}", table["latex"])
        self.assertEqual(table["caption"], "One column of numbers and one of letters.")

    def test_a_label_belongs_to_the_item_that_holds_it(self):
        labels = {item["id"]: item.get("label") for item in self.record["equations"]}
        self.assertEqual(labels["eq-1"], "eq:line")
        self.assertEqual(self.record["sections"][0]["label"], "sec:intro")

    def test_theorems_and_their_kin_are_inventoried_with_the_environment_that_named_them(self):
        self.assertEqual([item["environment"] for item in self.record["theorems"]], ["theorem", "lemma"])
        self.assertEqual(self.record["theorems"][0]["title"], "Tininess")

    def test_a_newtheorem_of_the_papers_own_is_inventoried(self):
        text = "\\newtheorem{principle}{Principle}\n\\begin{principle}\nAll principles are inventoried.\n\\end{principle}"
        record = latex_inventory(text)
        self.assertEqual([item["environment"] for item in record["theorems"]], ["principle"])

    def test_the_bibliography_becomes_the_references(self):
        self.assertEqual(self.record["references"][0]["key"], "knuth1984")
        self.assertIn("Knuth", self.record["references"][0]["text"])

    def test_the_title_and_the_document_class_are_read_off_the_preamble(self):
        self.assertEqual(self.record["metadata"]["documentclass"], "article")
        self.assertIn("tiny paper", self.record["metadata"]["title"])

    def test_an_algorithm_and_the_algorithmic_inside_it_are_one_algorithm(self):
        """`algorithmic` is the body of the float, so counting it would count every algorithm twice."""
        text = ("\\begin{algorithm}\\caption{Sort it}\n\\begin{algorithmic}\n\\STATE do nothing\n"
                "\\end{algorithmic}\\end{algorithm}")
        record = latex_inventory(text)
        self.assertEqual(record["counts"]["algorithms"], 1)
        self.assertEqual(record["algorithms"][0]["caption"], "Sort it")

    def test_environments_nest_without_confusing_their_ends(self):
        text = "\\begin{figure}\\begin{figure}inner\\end{figure}outer\\end{figure}"
        found = environments(text, {"figure"})
        self.assertEqual(len(found), 2)
        self.assertIn("inner", found[0].body)


class AuxTest(unittest.TestCase):
    AUX = (
        "\\relax\n"
        "\\newlabel{sec:intro}{{1}{1}{Introduction}{section.1}{}}\n"
        "\\newlabel{eq:line}{{7}{4}{}{equation.7}{}}\n"
        "\\newlabel{fig:plot}{{3}{2}{A plot}{figure.3}{}}\n"
        "\\newlabel{sub@eq:line}{{7}{4}{}{equation.7}{}}\n"
        "\\gdef \\@abspage@last{15}\n"
    )

    def test_every_labeled_item_gets_its_number_and_its_page(self):
        numbers = aux_numbers(self.AUX)
        self.assertEqual(numbers["eq:line"], {"number": "7", "page": 4})
        self.assertEqual(numbers["fig:plot"], {"number": "3", "page": 2})

    def test_a_packages_own_bookkeeping_is_not_an_item_of_the_paper(self):
        self.assertNotIn("sub@eq:line", aux_numbers(self.AUX))

    def test_the_compiled_numbers_replace_the_counted_ones(self):
        record = {
            "equations": [{"id": "eq-1", "kind": "equation", "locator": "flat.tex:1", "provenance": "latex",
                           "number": "1", "label": "eq:line", "confirm": True}],
            "figures": [{"id": "fig-1", "kind": "figure", "locator": "flat.tex:9", "provenance": "latex",
                         "number": "1", "confirm": True}],
        }
        self.assertEqual(apply_aux_numbers(record, aux_numbers(self.AUX)), 1)
        settled = record["equations"][0]
        self.assertEqual((settled["number"], settled["page"], settled["provenance"]), ("7", 4, "aux"))
        self.assertNotIn("confirm", settled)
        self.assertEqual(record["figures"][0]["number"], "1", "an unlabeled item keeps its counted number")
        self.assertTrue(record["figures"][0]["confirm"])

    def test_an_unnumbered_item_stays_unnumbered_however_the_aux_reads_its_label(self):
        """`\\label` after a `\\section*` records the last section number, which is not its own."""
        record = {"sections": [{"id": "sec-1", "kind": "section", "locator": "flat.tex:9",
                                "provenance": "latex", "label": "sec:intro", "title": "Visualizations"}]}
        self.assertEqual(apply_aux_numbers(record, aux_numbers(self.AUX)), 1)
        self.assertIsNone(record["sections"][0].get("number"))
        self.assertEqual(record["sections"][0]["page"], 1)


class HtmlInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = html_inventory(LATEXML.read_text(encoding="utf-8"), ARXIV_HTML % IDENTIFIER)

    def test_the_sections_come_back_numbered_and_titled(self):
        self.assertEqual([(item["number"], item["title"]) for item in self.record["sections"]], [
            ("1", "Introduction"), ("1.1", "What is not in this paper"), ("2", "Method"),
        ])

    def test_the_mathml_alttext_is_the_latex(self):
        equation = self.record["equations"][0]
        self.assertEqual(equation["latex"], "y = m x + b")
        self.assertEqual(equation["number"], "1")
        self.assertEqual(equation["provenance"], "html")

    def test_a_figure_and_a_table_keep_their_captions_and_nothing_else(self):
        self.assertEqual(self.record["figures"][0]["caption"], "A plot of nothing against nothing.")
        self.assertEqual(self.record["tables"][0]["caption"], "One column of numbers and one of letters.")

    def test_the_locator_is_the_anchor_a_reader_can_open(self):
        self.assertEqual(self.record["figures"][0]["locator"], "%s#S1.F1" % (ARXIV_HTML % IDENTIFIER))

    def test_the_rows_of_one_equation_are_not_several_equations(self):
        self.assertEqual(self.record["counts"]["equations"], 1)


# --- the whole chain, into a project ----------------------------------------------------------------


class BuildInventoryTest(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        self.ledger = Ledger(self.project)
        write_l0(self.ledger, l0_dossier({
            "existence": "verified",
            "resolved_by": "arxiv",
            "query": {"kind": "arxiv", "value": IDENTIFIER, "raw": "arXiv:%s" % IDENTIFIER},
            "identifiers": {"arxiv_id": IDENTIFIER},
            "metadata": {"title": "A tiny paper, written for the inventory", "year": 2024},
            "abstract": None,
            "open_access": {},
            "attempts": [],
        }, SLUG))

    def build(self, answers=None, **options):
        fetcher = served(answers if answers is not None else tarball_answers())
        return build_inventory(self.project, SLUG, fetcher=fetcher, email=EMAIL, **options), fetcher

    def ref(self, *parts):
        return self.project.joinpath("research", REFS, SLUG, *parts)

    def test_the_inventory_is_written_where_the_spec_puts_it_and_validates(self):
        inventory, _ = self.build()
        written = json.loads(self.ref(INVENTORY).read_text(encoding="utf-8"))
        self.assertEqual(validate(written, load_schema("inventory")), [])
        self.assertEqual(written["slug"], SLUG)
        self.assertEqual(written["source_type"], "latex")
        self.assertEqual(written, inventory)

    def test_the_source_is_kept_under_the_reference_and_the_flattened_file_beside_it(self):
        self.build()
        self.assertTrue(self.ref(SOURCE, "ms.tex").is_file())
        self.assertTrue(self.ref(SOURCE, "sections", "method.tex").is_file())
        self.assertTrue(self.ref(SOURCE, "figures", "plot.png").is_file())
        flat = self.ref(SOURCE, FLAT).read_text(encoding="utf-8")
        self.assertIn("A tiny paper needs a tiny introduction", flat)

    def test_the_source_directory_is_gitignored_so_no_e_print_is_ever_republished(self):
        self.assertIn("research/refs/*/source/", (self.project / ".gitignore").read_text(encoding="utf-8").splitlines())

    def test_the_record_says_where_it_came_from(self):
        inventory, _ = self.build()
        source = inventory["source"]
        self.assertEqual(source["kind"], "tarball")
        self.assertEqual(source["url"], arxiv_source_url(IDENTIFIER))
        self.assertEqual((source["arxiv_id"], source["version"], source["etag"]), (IDENTIFIER, "v2", ETAG))
        self.assertEqual(source["main"], "ms.tex")
        self.assertEqual(source["files"], 6)

    def test_every_field_says_what_filled_it(self):
        inventory, _ = self.build(compile_source=False)
        self.assertEqual(inventory["provenance"]["sections"], "latex")
        self.assertEqual(inventory["provenance"]["references"], "latex")
        self.assertEqual(inventory["text_layer"], {"path": "source/flat.tex", "chars": inventory["text_layer"]["chars"], "provenance": "latex"})

    def test_the_counts_of_the_paper_come_through_the_whole_chain(self):
        inventory, _ = self.build(compile_source=False)
        self.assertEqual(inventory["counts"]["section_headings"], 4)
        self.assertEqual(inventory["counts"]["equations"], 3)
        self.assertEqual(inventory["counts"]["figures"], 2)
        self.assertEqual(inventory["environments"]["align*"], 1)

    def test_a_raster_figure_is_kept_as_an_image_file_the_reader_can_open(self):
        inventory, _ = self.build(compile_source=False)
        first = inventory["figures"][0]
        self.assertEqual(first["file"], "figures/fig-1.png")
        self.assertEqual(first["graphics"], ["figures/plot.png"])
        self.assertTrue(self.ref("figures", "fig-1.png").is_file())

    @unittest.skipUnless(shutil.which("pdftoppm"), "poppler is not installed")
    def test_a_pdf_figure_is_rasterized_with_pdftoppm(self):
        inventory, _ = self.build(compile_source=False)
        second = inventory["figures"][1]
        self.assertEqual(second["file"], "figures/fig-2.png")
        self.assertEqual(self.ref("figures", "fig-2.png").read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_without_poppler_the_target_is_still_recorded_and_the_note_says_what_is_missing(self):
        inventory, _ = self.build(compile_source=False, rasterize=False)
        second = inventory["figures"][1]
        self.assertEqual(second["graphics"], ["figures/diagram.pdf"])
        self.assertIsNone(second.get("file"))
        self.assertTrue(any("pdftoppm" in note for note in inventory["notes"]))

    def test_every_image_in_the_tarball_is_listed_whatever_the_paper_does_with_it(self):
        inventory, _ = self.build(compile_source=False)
        self.assertEqual(
            sorted((image["path"], image["format"]) for image in inventory["raw_images"]),
            [("figures/diagram.pdf", "pdf"), ("figures/plot.png", "png")],
        )

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex is not installed")
    def test_a_field_says_the_compile_filled_it_only_when_the_compile_filled_it(self):
        """A paper that labels its figures and not its equations gets one of each, and says so."""
        compiled, _ = self.build()
        counted, _ = self.build(compile_source=False)
        self.assertEqual(compiled["provenance"]["figures"], "aux")
        self.assertEqual(counted["provenance"]["figures"], "latex")
        self.assertEqual(counted["provenance"]["equations"], "latex")

    @unittest.skipUnless(shutil.which("pdflatex"), "pdflatex is not installed")
    def test_a_source_that_compiles_gets_its_numbers_and_pages_from_the_aux(self):
        inventory, _ = self.build()
        equation = inventory["equations"][0]
        self.assertEqual(equation["provenance"], "aux")
        self.assertEqual(equation["page"], 1)
        self.assertNotIn("confirm", equation)
        self.assertEqual(inventory["provenance"]["equations"], "aux")
        self.assertTrue(inventory["source"]["compiled"])
        self.assertEqual(inventory["page_count"], 3)

    def test_a_source_that_is_not_compiled_keeps_the_counted_numbers(self):
        inventory, _ = self.build(compile_source=False)
        self.assertEqual(inventory["equations"][0]["provenance"], "latex")
        self.assertFalse(inventory["source"]["compiled"])
        self.assertIsNone(inventory["page_count"])
        self.assertTrue(any("document order" in note for note in inventory["notes"]))

    def test_a_second_pass_offers_the_etag_and_downloads_nothing(self):
        self.build(compile_source=False)
        inventory, fetcher = self.build(compile_source=False)
        self.assertEqual(fetcher.backend.sent[0].headers.get("If-None-Match"), ETAG)
        self.assertTrue(inventory["source"]["from_cache"])
        self.assertTrue(any("304" in note for note in inventory["notes"]))
        self.assertEqual(inventory["counts"]["section_headings"], 4, "the kept source inventories the same paper")
        self.assertIn("updated", inventory)

    def test_a_pdf_only_submission_is_kept_and_routed_to_the_pdf_chain(self):
        payload = b"%PDF-1.4\n%%EOF\n"
        answers = {arxiv_source_url(IDENTIFIER): (200, {"content-type": "application/pdf", "etag": ETAG}, payload)}
        inventory, _ = self.build(answers)
        self.assertEqual(inventory["source_type"], "pdf")
        self.assertEqual(inventory["source"]["kind"], "pdf")
        self.assertEqual(self.ref(SOURCE, "2401-00001.pdf").read_bytes(), payload)
        self.assertEqual(inventory["figures"], [])
        self.assertTrue(any("ticket 22" in note for note in inventory["notes"]))
        self.assertEqual(validate(inventory, load_schema("inventory")), [])

    def test_a_tarball_that_will_not_flatten_falls_back_to_the_arxiv_html(self):
        answers = tarball_answers(payload=NO_LATEX.read_bytes(), html_page=LATEXML.read_bytes())
        inventory, fetcher = self.build(answers)
        self.assertEqual(inventory["source_type"], "html")
        self.assertEqual(fetcher.backend.urls[-1], ARXIV_HTML % IDENTIFIER)
        self.assertEqual(inventory["equations"][0]["latex"], "y = m x + b")
        self.assertEqual(inventory["provenance"]["equations"], "html")
        self.assertTrue(any("beta" in note for note in inventory["notes"]))
        self.assertEqual(validate(inventory, load_schema("inventory")), [])

    def test_a_reference_with_no_arxiv_id_is_sent_to_the_pdf_chain_rather_than_guessed_at(self):
        write_l0(self.ledger, l0_dossier({
            "existence": "verified", "resolved_by": "crossref",
            "query": {"kind": "doi", "value": "10.1000/x"}, "identifiers": {"doi": "10.1000/x"},
            "metadata": {"title": "A journal paper"}, "abstract": None, "open_access": {}, "attempts": [],
        }, "journal-2024-a-paper"))
        with self.assertRaises(ValueError) as caught:
            build_inventory(self.project, "journal-2024-a-paper", fetcher=served({}), email=EMAIL)
        self.assertIn("ticket 22", str(caught.exception))

    def test_a_reference_with_no_dossier_is_an_error_that_names_the_pass_to_run(self):
        with self.assertRaises(ValueError) as caught:
            build_inventory(self.project, "nobody-2024-nothing", fetcher=served({}), email=EMAIL)
        self.assertIn("absorb --level 0", str(caught.exception))

    def test_the_whole_chain_asks_arxiv_once(self):
        _, fetcher = self.build(compile_source=False)
        self.assertEqual(fetcher.backend.urls, [arxiv_source_url(IDENTIFIER)])


class InventoryVerbTest(ProjectTestCase):
    """`wayline absorb --inventory <slug>` over a recorded response, the way a test may reach it."""

    def setUp(self):
        super().setUp()
        self.project = self.temp / "project"
        init_project(self.project, harness_root=self.fake_harness(), git=False, hermes_python=None, owner_email=EMAIL)
        write_l0(Ledger(self.project), l0_dossier({
            "existence": "verified", "resolved_by": "arxiv",
            "query": {"kind": "arxiv", "value": IDENTIFIER}, "identifiers": {"arxiv_id": IDENTIFIER},
            "metadata": {"title": "A tiny paper, written for the inventory"}, "abstract": None,
            "open_access": {}, "attempts": [],
        }, SLUG))
        self.recordings = self.temp / "recordings"
        self.record(arxiv_source_url(IDENTIFIER), TARBALL.read_bytes(), TARBALL_HEADERS)

    def record(self, url, body, headers):
        """One response on disk in the shape `DirectoryBackend` reads, so `--fixtures` can replay it."""
        request = Request(url, {"User-Agent": user_agent(TAG, EMAIL), "Accept": "*/*"})
        path = self.recordings / request.host / (request.hash + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "request": {"method": "GET", "url": url, "hash": request.hash},
            "response": {"url": url, "status": 200, "headers": dict(headers),
                         "encoding": "base64", "body": base64.b64encode(body).decode("ascii")},
        }), encoding="utf-8")
        return path

    def run_verb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_the_verb_builds_the_inventory_from_a_recorded_response(self):
        code, printed, complaint = self.run_verb(
            "absorb", "--inventory", SLUG, "--project", str(self.project), "--fixtures", str(self.recordings))
        self.assertEqual(code, 0, complaint)
        self.assertIn(SLUG, printed)
        self.assertIn("figures 2", printed)
        self.assertTrue((self.project / "research" / REFS / SLUG / INVENTORY).is_file())

    def test_the_inventory_comes_back_as_json_when_it_is_asked_for(self):
        code, printed, complaint = self.run_verb(
            "absorb", "--inventory", SLUG, "--project", str(self.project),
            "--fixtures", str(self.recordings), "--json")
        self.assertEqual(code, 0, complaint)
        self.assertEqual(json.loads(printed)["counts"]["figures"], 2)

    def test_a_request_nobody_recorded_complains_rather_than_reaching_the_network(self):
        """The recording backend refuses a miss; the verb has to answer that with a line, not a traceback."""
        shutil.rmtree(self.recordings)
        code, _, complaint = self.run_verb(
            "absorb", "--inventory", SLUG, "--project", str(self.project), "--fixtures", str(self.recordings))
        self.assertEqual(code, 1)
        self.assertIn("no recorded response", complaint)

    def test_a_slug_with_no_dossier_complains_and_exits_1(self):
        code, _, complaint = self.run_verb(
            "absorb", "--inventory", "nobody", "--project", str(self.project), "--fixtures", str(self.recordings))
        self.assertEqual(code, 1)
        self.assertIn("nobody", complaint)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
