"""The figure role's 19 machine checks, each against a committed passing and failing sample.

The samples under `fixtures/figures/` are rebuilt by `fixtures/figures/make.py`. A check that runs
a tool (poppler, ruff) or the project's matplotlib is tested where the tool is installed and
skipped where it is not, which is GitHub's runner; the PDF walk, the PNG decoder, SSIM, the color
arithmetic, and every check that reads only JSON and text run everywhere.
"""

import importlib.util
import json
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from tests.paths import FIXTURES_DIR
from wayline import figure_checks as fc
from wayline.jsonschema import load_schema, validate

FIGURES = FIXTURES_DIR / "figures"
SAMPLES = FIGURES / "samples"
PROJECT = FIGURES / "project"
POPPLER = unittest.skipUnless(
    all(shutil.which(tool) for tool in ("pdffonts", "pdfinfo", "pdfimages", "pdftotext", "pdftoppm")), "poppler is not installed")
MATPLOTLIB = unittest.skipUnless(importlib.util.find_spec("matplotlib") and importlib.util.find_spec("numpy"), "matplotlib is not installed")
RUFF = unittest.skipUnless(shutil.which("ruff") or shutil.which("uvx"), "ruff is not installed")
POLICY = {"ssim_min": 0.99, "crops_dpi": 600}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def request(**changes):
    base = load(PROJECT / "request.json")
    target = dict(base["target"], **changes.pop("target", {}))
    return dict(base, target=target, **changes)


class FigureCase(unittest.TestCase):
    """A temporary project holding one figure built from samples, and a context over it."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="wayline-figure-test-"))
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.final = {"generator": "figures/f/f.py", "caption": "figures/f/caption.md", "notes": "figures/f/notes.md", "inputs": []}

    def put(self, relative, source=None, text=None):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if source is not None:
            shutil.copy(source, path)
        else:
            path.write_text(text, encoding="utf-8")
        return relative

    def figure(self, pdf=None, png=None, caption=None, notes=None, generator=None):
        if pdf is not None:
            self.final["pdf"] = self.put("figures/f/f.pdf", SAMPLES / pdf)
        if png is not None:
            self.final["png"] = self.put("figures/f/f.png", SAMPLES / png)
        if caption is not None:
            self.put(self.final["caption"], text=caption)
        if notes is not None:
            self.put(self.final["notes"], text=notes)
        if generator is not None:
            self.put(self.final["generator"], text=generator)

    def context(self, req=None, artists=False, style=None, tools=None, **result):
        result = dict({"final": self.final}, **result)
        style = style if style is not None else load(PROJECT / "figures" / "style.json")
        # `artists=False` stands for "no report": the context never tries a clean-room run.
        return fc.FigureContext(self.project, req or request(), result, style=style, policy=POLICY, tools=tools, artists=artists)

    def check(self, check_id, **kwargs):
        outcome = fc.CHECKS[check_id](self.context(**kwargs))
        self.assertEqual(set(outcome), {"id", "type", "pass", "tool", "detail"})
        self.assertEqual((outcome["id"], outcome["type"]), (check_id, "A"))
        return outcome

    def assertPasses(self, outcome):
        self.assertTrue(outcome["pass"], outcome["detail"])

    def assertFails(self, outcome, *fragments):
        self.assertFalse(outcome["pass"], outcome["detail"])
        for fragment in fragments:
            self.assertIn(fragment, outcome["detail"])


def artists(texts=(), panels=(), marked=(), structure=(), mappables=(), colors=(), width_px=700, height_px=400):
    return {
        "saved_to": "figures/f/f.pdf",
        "figure": {"width_px": width_px, "height_px": height_px, "dpi": 200, "width_in": 3.5, "height_in": 2.0, "scale": 1.0},
        "texts": [dict({"role": "text", "fontsize_pt": 6.0, "haloed": False}, **text) for text in texts],
        "panels": list(panels), "marked_lines": list(marked), "structure": list(structure),
        "mappables": list(mappables), "colors": list(colors),
    }


def text(content, extent, **extra):
    return dict({"text": content, "extent": list(extent)}, **extra)


# --- 1 to 6: the files ------------------------------------------------------------------------


@POPPLER
class FontsEmbeddedTest(FigureCase):
    def test_type_42_fonts_pass(self):
        self.figure(pdf="type42.pdf")
        outcome = self.check("fonts_embedded")
        self.assertPasses(outcome)
        self.assertIn("CID TrueType", outcome["detail"])

    def test_type_3_fonts_fail(self):
        self.figure(pdf="type3.pdf")
        self.assertFails(self.check("fonts_embedded"), "Type 3")


class FontsTableTest(unittest.TestCase):
    def test_a_long_font_name_does_not_shift_the_columns(self):
        table = ("name                                 type              encoding         emb sub uni object ID\n"
                 "------------------------------------ ----------------- ---------------- --- --- --- ---------\n"
                 "ABCDEF+AVeryLongFontNameThatOverflowsItsColumn Type 3 Custom yes yes no 17 0\n")
        self.assertEqual(fc.parse_pdffonts(table), [{"name": "ABCDEF+AVeryLongFontNameThatOverflowsItsColumn", "type": "Type 3", "encoding": "Custom", "emb": "yes"}])

    def test_a_missing_tool_fails_the_check_rather_than_skipping_it(self):
        case = FigureCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.figure(pdf="type42.pdf")
        tools = fc.Tools(which=lambda name: None)
        report = fc.run_checks(case.project, request(), {"final": case.final}, style={}, policy=POLICY, tools=tools, artists=False, only={"fonts_embedded"})
        self.assertEqual(report, [{"id": "fonts_embedded", "type": "A", "pass": False, "tool": "pdffonts",
                                   "detail": "pdffonts is not installed, so this check cannot pass"}])


@POPPLER
class JournalWidthTest(FigureCase):
    def test_the_target_width_passes(self):
        self.figure(pdf="width-89mm.pdf")
        self.assertPasses(self.check("journal_width"))

    def test_a_wider_page_fails(self):
        self.figure(pdf="width-120mm.pdf")
        self.assertFails(self.check("journal_width"), "width 120.0 mm")

    def test_a_page_over_the_height_cap_fails(self):
        self.figure(pdf="width-89mm.pdf")
        self.assertFails(self.check("journal_width", req=request(target={"max_height_mm": 20})), "over the 20.0 mm cap")


class ResolutionPngTest(FigureCase):
    def test_a_png_at_the_target_resolution_passes(self):
        self.figure(png="png-300dpi.png")
        self.assertPasses(self.check("resolution", req=request(target={"formats": ["png"]})))

    def test_a_png_under_the_target_resolution_fails(self):
        self.figure(png="png-100dpi.png")
        self.assertFails(self.check("resolution", req=request(target={"formats": ["png"]})), "under 300")


@POPPLER
class ResolutionPdfTest(FigureCase):
    def test_an_embedded_raster_at_the_target_resolution_passes(self):
        self.figure(pdf="raster-1200px.pdf")
        self.assertPasses(self.check("resolution", req=request(target={"formats": ["pdf"]})))

    def test_an_embedded_raster_under_the_target_resolution_fails(self):
        self.figure(pdf="raster-10px.pdf")
        self.assertFails(self.check("resolution", req=request(target={"formats": ["pdf"]})), "10x10 image")


class MinFontTest(FigureCase):
    def test_six_point_text_passes_a_five_point_minimum(self):
        self.figure(pdf="font-6pt.pdf")
        outcome = self.check("min_font_pt")
        self.assertPasses(outcome)
        self.assertIn("6.00 pt", outcome["detail"])

    def test_three_point_text_fails(self):
        self.figure(pdf="font-3pt.pdf")
        self.assertFails(self.check("min_font_pt"), "smallest 3.00 pt")

    def test_sizes_are_scaled_to_the_target_width(self):
        self.figure(pdf="font-6pt-at-half-width.pdf")  # a 40 mm page placed 20 mm wide
        self.assertFails(self.check("min_font_pt", req=request(target={"width_mm": 20})), "smallest 3.00 pt")

    def test_the_artist_report_catches_text_the_pdf_walk_does_not(self):
        self.figure(pdf="font-6pt.pdf")
        report = artists(texts=[text("halo", (0, 0, 10, 10), fontsize_pt=4.0, haloed=True)])
        self.assertFails(self.check("min_font_pt", artists=report), "artists 4.00 pt")


@POPPLER
class MaxWordsTest(FigureCase):
    def abstract(self, cap=60):
        return request(kind="graphical_abstract", register="conceptual", target={"max_words": cap})

    def test_an_abstract_under_its_cap_passes(self):
        self.figure(pdf="abstract-8-words.pdf")
        self.assertPasses(self.check("max_words", req=self.abstract()))

    def test_an_abstract_over_its_cap_fails(self):
        self.figure(pdf="abstract-80-words.pdf")
        self.assertFails(self.check("max_words", req=self.abstract()), "80 words; cap 60")

    def test_an_abstract_without_a_cap_fails(self):
        self.figure(pdf="abstract-8-words.pdf")
        self.assertFails(self.check("max_words", req=self.abstract(cap=None)), "needs target.max_words")

    def test_a_result_figure_has_no_cap(self):
        self.assertPasses(self.check("max_words"))


class ForbiddenTokensTest(unittest.TestCase):
    def test_digits_genes_and_datasets_are_found_and_allowed_tokens_are_not(self):
        found = fc.forbidden_tokens("a Stage 2 TP53 on PBMC3k x10", allow=["^a$", "^x10$"], genes=["TP53"], datasets=["pbmc3k"])
        self.assertEqual(found, ["digits in '2'", "gene name 'TP53'", "digits in 'PBMC3k'", "dataset name 'pbmc3k'"])


@POPPLER
class ForbiddenTextTest(FigureCase):
    def conceptual(self):
        return request(kind="framework", register="conceptual",
                       forbidden_text={"gene_names": None, "dataset_names": ["PBMC3k"], "allow_regex": ["^[a-h]$"]})

    def clean_artists(self):
        return artists(texts=[text("a", (0, 0, 5, 5), role="panel_label"), text("Encoder", (10, 0, 40, 5))])

    def test_a_conceptual_figure_without_numbers_or_names_passes(self):
        self.figure(pdf="conceptual-clean.pdf")
        self.assertPasses(self.check("forbidden_text", req=self.conceptual(), artists=self.clean_artists()))

    def test_digits_and_a_dataset_name_in_the_pdf_fail(self):
        self.figure(pdf="conceptual-digits.pdf")
        self.assertFails(self.check("forbidden_text", req=self.conceptual(), artists=self.clean_artists()), "digits in '1'", "dataset name 'PBMC3k'")

    def test_haloed_text_pdftotext_cannot_see_is_caught_in_the_artists(self):
        self.figure(pdf="conceptual-clean.pdf")
        report = artists(texts=[text("Stage 2", (0, 0, 20, 5), haloed=True)])
        self.assertFails(self.check("forbidden_text", req=self.conceptual(), artists=report), "artists: digits in '2'")

    def test_tick_labels_fail_a_conceptual_figure(self):
        self.figure(pdf="conceptual-clean.pdf")
        report = artists(texts=[text("low", (0, 0, 20, 5), role="ticklabel")])
        self.assertFails(self.check("forbidden_text", req=self.conceptual(), artists=report), "tick label")

    def test_without_an_artist_report_the_check_does_not_pass(self):
        self.figure(pdf="conceptual-clean.pdf")
        self.assertFails(self.check("forbidden_text", req=self.conceptual()), "no artist report")

    def test_a_quantitative_figure_forbids_nothing(self):
        self.figure(pdf="conceptual-digits.pdf")
        self.assertPasses(self.check("forbidden_text"))


# --- 7 and 8: the caption ---------------------------------------------------------------------


class CaptionPanelsTest(FigureCase):
    def setUp(self):
        super().setUp()
        self.figure(png="png-300dpi.png")
        self.report = artists(panels=[{"label": "a", "bbox": [0, 0, 0.5, 1]}, {"label": "b", "bbox": [0.5, 0, 1, 1]}])
        self.req = request(target={"formats": ["png"]})

    def test_every_panel_with_a_caption_entry_passes(self):
        self.figure(caption="**Figure 1.** (a) Held-out AUROC. (b) Runtime (s) against AUROC.\n")
        self.assertPasses(self.check("caption_panels", req=self.req, artists=self.report))

    def test_a_panel_without_a_caption_entry_fails(self):
        self.figure(caption="**Figure 1.** (a) Held-out AUROC.\n")
        self.assertFails(self.check("caption_panels", req=self.req, artists=self.report), "panel(s) b have no caption entry")

    def test_a_caption_entry_without_a_panel_fails(self):
        self.figure(caption="**Figure 1.** (a) Held-out AUROC. (b) Runtime. (c) Memory.\n")
        self.assertFails(self.check("caption_panels", req=self.req, artists=self.report), "caption entries c name no panel")

    def test_a_missing_caption_fails(self):
        self.assertFails(self.check("caption_panels", req=self.req, artists=self.report), "is not on disk")


class CaptionLintTest(FigureCase):
    def test_a_clean_caption_passes(self):
        self.figure(caption="(a) Held-out AUROC per method, normalized to the baseline color scale.\n")
        self.assertPasses(self.check("caption_lint"))

    def test_an_em_dash_and_british_spelling_fail(self):
        self.figure(caption="(a) Held-out AUROC — normalised, in colour.\n")
        self.assertFails(self.check("caption_lint"), "1 em dash", "colour, normalised")

    def test_a_framework_caption_needs_a_forward_reference(self):
        self.figure(caption="(a) The pipeline from reads to networks.\n")
        framework = request(kind="framework", register="conceptual")
        self.assertFails(self.check("caption_lint", req=framework), "forward reference")
        self.figure(caption="(a) The pipeline from reads to networks (see also Figure 3).\n")
        self.assertPasses(self.check("caption_lint", req=framework))

    def test_american_words_that_end_like_british_ones_are_not_flagged(self):
        self.assertEqual(fc.lint_caption("A precise exercise over an hour; analyses of the colorbar."), [])


# --- 9 and 10: the generator ------------------------------------------------------------------


@RUFF
class GeneratorCleanTest(FigureCase):
    def context_with_room(self, source, returncode=0, error=""):
        self.put(self.final["generator"], SAMPLES / source)
        context = self.context()
        context._clean_room = fc.CleanRoom(returncode, error)
        return context

    def test_a_generator_without_unused_names_that_exits_zero_passes(self):
        self.assertPasses(fc.check_generator_clean(self.context_with_room("clean_generator.py")))

    def test_an_unused_import_and_variable_fail(self):
        outcome = fc.check_generator_clean(self.context_with_room("unused_import.py"))
        self.assertFails(outcome, "F401", "F841")
        self.assertIn("figures/f/f.py", outcome["detail"])

    def test_a_generator_that_fails_in_a_fresh_interpreter_fails(self):
        outcome = fc.check_generator_clean(self.context_with_room("clean_generator.py", 1, "FileNotFoundError: data/extra.txt"))
        self.assertFails(outcome, "did not exit 0", "FileNotFoundError")


class FixtureProjectCase(unittest.TestCase):
    """A writable copy of `fixtures/figures/project/`."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="wayline-figure-project-")) / "project"
        self.addCleanup(shutil.rmtree, self.project.parent, ignore_errors=True)
        shutil.copytree(PROJECT, self.project)
        self.request = load(self.project / "request.json")

    def result(self, figure_id):
        return load(self.project / "figures" / figure_id / "result.json")

    def run_checks(self, figure_id, **kwargs):
        return {item["id"]: item for item in fc.run_checks(self.project, self.request, self.result(figure_id), policy=POLICY, **kwargs)}


@MATPLOTLIB
@POPPLER
class RegeneratesTest(FixtureProjectCase):
    def test_a_deterministic_generator_regenerates_its_figure(self):
        outcome = self.run_checks("fig1", only={"regenerates"})["regenerates"]
        self.assertTrue(outcome["pass"], outcome["detail"])
        self.assertIn("ssim 1.0000", outcome["detail"])
        self.assertIn("text layer identical", outcome["detail"])

    def test_unseeded_noise_does_not_regenerate(self):
        outcome = self.run_checks("noisy", only={"regenerates"})["regenerates"]
        self.assertFalse(outcome["pass"], outcome["detail"])
        self.assertIn("is under 0.99", outcome["detail"])

    def test_a_generator_reading_an_undeclared_file_does_not_run_in_the_clean_room(self):
        report = self.run_checks("undeclared", only={"regenerates", "generator_clean"})
        self.assertFalse(report["regenerates"]["pass"])
        self.assertIn("extra.txt", report["regenerates"]["detail"])
        self.assertIn("did not exit 0", report["generator_clean"]["detail"])


# --- 11 to 13: color and line ---------------------------------------------------------------


class PaletteTest(FigureCase):
    def test_colors_from_the_house_style_pass(self):
        self.figure(pdf="palette-okabe-ito.pdf")
        outcome = self.check("palette")
        self.assertPasses(outcome)
        self.assertIn("3 hue(s): 3 from the house style, 0 new", outcome["detail"])

    def test_new_colors_too_close_under_color_vision_deficiency_fail(self):
        self.figure(pdf="palette-red-green.pdf")
        self.assertFails(self.check("palette"), "#339933 and #CC3311", "deuteranopia")

    def test_a_new_color_distinct_under_every_simulation_passes(self):
        self.figure(pdf="palette-new-distinct.pdf")
        outcome = self.check("palette")
        self.assertPasses(outcome)
        self.assertIn("1 from the house style, 1 new", outcome["detail"])

    def test_a_colormap_outside_the_house_ramps_fails(self):
        self.figure(pdf="palette-okabe-ito.pdf")
        report = artists(mappables=[{"cmap": "jet", "quantity": "density"}])
        self.assertFails(self.check("palette", artists=report), "colormap jet is not a ramp")

    def test_a_raster_without_an_artist_report_cannot_pass(self):
        self.figure(pdf="raster-10px.pdf")
        self.assertFails(self.check("palette"), "embeds 1 raster")

    def test_a_style_without_colors_fails(self):
        self.figure(pdf="palette-okabe-ito.pdf")
        self.assertFails(self.check("palette", style={}), "has no colors")


class OneRampPerQuantityTest(FigureCase):
    def test_each_quantity_drawn_with_its_own_ramp_passes(self):
        report = artists(mappables=[{"cmap": "viridis", "quantity": "density"}], structure=[{"gid": "connector:e1", "colors": ["#808080"]}])
        self.assertPasses(self.check("one_ramp_per_quantity", artists=report))

    def test_a_quantity_drawn_with_another_ramp_fails(self):
        report = artists(mappables=[{"cmap": "magma", "quantity": "density"}])
        self.assertFails(self.check("one_ramp_per_quantity", artists=report), "density is drawn with magma, not its ramp viridis")

    def test_one_ramp_spent_on_two_quantities_fails(self):
        style = dict(load(PROJECT / "figures" / "style.json"), ramp_per_quantity={"density": "viridis", "expression": "viridis"})
        report = artists(mappables=[{"cmap": "viridis", "quantity": "density"}, {"cmap": "viridis", "quantity": "expression"}])
        self.assertFails(self.check("one_ramp_per_quantity", artists=report, style=style),
                         "names ramp viridis for density and expression", "colormap viridis is spent on density and expression")

    def test_a_colormap_without_a_quantity_fails(self):
        self.assertFails(self.check("one_ramp_per_quantity", artists=artists(mappables=[{"cmap": "viridis", "quantity": None}])), "declares no quantity")

    def test_colored_structure_fails(self):
        report = artists(structure=[{"gid": "container:stage", "colors": ["#E69F00"]}])
        self.assertFails(self.check("one_ramp_per_quantity", artists=report), "container:stage is colored #E69F00")

    def test_without_an_artist_report_the_check_does_not_pass(self):
        self.assertFails(self.check("one_ramp_per_quantity"), "no artist report")


class LineStyleTest(FigureCase):
    def test_required_solid_and_optional_dashed_pass(self):
        report = artists(marked=[{"gid": "required:e1", "kind": "required", "linestyle": "solid"},
                                 {"gid": "optional:e2", "kind": "optional", "linestyle": "dashed"}])
        self.assertPasses(self.check("required_vs_optional_line_style", artists=report))

    def test_a_dashed_required_edge_and_a_solid_optional_edge_fail(self):
        report = artists(marked=[{"gid": "required:e1", "kind": "required", "linestyle": "dashed"},
                                 {"gid": "optional:e2", "kind": "optional", "linestyle": "solid"}])
        self.assertFails(self.check("required_vs_optional_line_style", artists=report),
                         "required:e1 is required but drawn dashed", "optional:e2 is optional but drawn solid")

    def test_without_an_artist_report_the_check_does_not_pass(self):
        self.assertFails(self.check("required_vs_optional_line_style"), "no artist report")


# --- 14 to 16: what the result declares -------------------------------------------------------


class SelectionTest(FigureCase):
    def test_a_subset_within_its_tolerance_passes(self):
        statistics = [{"panel": "c", "criterion": "sign_balance", "displayed": 0.55, "global": 0.57, "tolerance": 0.10}]
        self.assertPasses(self.check("selection_representativeness", selection_statistics=statistics))

    def test_a_subset_outside_its_tolerance_fails(self):
        statistics = [{"panel": "c", "criterion": "sign_balance", "displayed": 0.55, "global": 0.75, "tolerance": 0.10}]
        self.assertFails(self.check("selection_representativeness", selection_statistics=statistics), "over the tolerance 0.1")


class SchematicTest(FigureCase):
    elements = [{"panel": "b", "element": "regulatory motif", "reason": "below threshold in all runs", "caption_phrase": "schematic"}]

    def test_an_element_named_in_the_caption_notes_and_generator_passes(self):
        self.figure(caption="(b) The regulatory motif is schematic.\n", notes="Panel b draws the regulatory motif by hand.\n",
                    generator="# schematic: regulatory motif, drawn by hand\n")
        self.assertPasses(self.check("schematic_disclosed", schematic_elements=self.elements))

    def test_an_undisclosed_element_fails(self):
        self.figure(caption="(b) The regulatory motif.\n", notes="Panel b.\n", generator="print('motif')\n")
        self.assertFails(self.check("schematic_disclosed", schematic_elements=self.elements),
                         "does not say 'schematic'", "notes do not name regulatory motif", "no '# schematic: regulatory motif'")


class MixedDataTest(FigureCase):
    def inputs(self, first, second):
        return [{"path": "results/t7-a1/x.csv", "sha256": "0" * 64, "run_id": "t7-a1", "panels": first},
                {"path": "results/t8-a1/y.csv", "sha256": "0" * 64, "run_id": "t8-a1", "panels": second}]

    def test_one_run_per_panel_passes(self):
        self.final["inputs"] = self.inputs(["a"], ["b"])
        self.assertPasses(self.check("mixed_data_disclosed"))

    def test_two_runs_in_one_panel_without_the_marker_fail(self):
        self.final["inputs"] = self.inputs(["a"], ["a"])
        self.figure(caption="(a) Both runs.\n")
        self.assertFails(self.check("mixed_data_disclosed"), "panel a from t7-a1, t8-a1", "does not carry [[mixed-data]]")

    def test_two_runs_in_one_panel_with_the_marker_pass(self):
        self.final["inputs"] = self.inputs(["a"], None)
        self.figure(caption="(a) Both runs [[mixed-data]].\n")
        self.assertPasses(self.check("mixed_data_disclosed"))


# --- 17 to 19: crops, overlap, provenance -----------------------------------------------------


@POPPLER
class CropsTest(FigureCase):
    def test_each_panel_is_cropped_at_600_dpi(self):
        self.figure(pdf="width-89mm.pdf")  # 89 by 30 mm
        report = artists(panels=[{"label": "a", "bbox": [0, 0, 0.5, 1]}, {"label": "b", "bbox": [0.5, 0.5, 1, 1]}])
        outcome = self.check("crops", artists=report)
        self.assertPasses(outcome)
        self.assertIn("figures/f/crops/a.png, figures/f/crops/b.png", outcome["detail"])
        width, height = fc.png_size(self.project / "figures/f/crops/a.png")
        self.assertAlmostEqual(width, 89 / 2 / 25.4 * 600, delta=2)
        self.assertAlmostEqual(height, 30 / 25.4 * 600, delta=2)
        self.assertAlmostEqual(fc.png_size(self.project / "figures/f/crops/b.png")[1], 15 / 25.4 * 600, delta=2)

    def test_a_figure_without_panels_gets_one_full_crop(self):
        self.figure(pdf="width-89mm.pdf")
        self.assertPasses(self.check("crops"))
        self.assertTrue((self.project / "figures/f/crops/full.png").is_file())

    def test_no_pdf_fails(self):
        self.assertFails(self.check("crops"), "is not on disk")


class TextOverlapTest(FigureCase):
    def test_separate_texts_inside_the_figure_pass(self):
        report = artists(texts=[text("AUROC", (10, 10, 60, 20)), text("Runtime", (100, 10, 160, 20))])
        self.assertPasses(self.check("text_overlap", artists=report))

    def test_overlapping_texts_fail(self):
        report = artists(texts=[text("AUROC", (10, 10, 60, 20)), text("Runtime", (40, 12, 100, 22))])
        self.assertFails(self.check("text_overlap", artists=report), "'AUROC' and 'Runtime' overlap")

    def test_text_past_the_figure_edge_fails(self):
        report = artists(texts=[text("Runtime (s)", (680, 10, 730, 20))], width_px=700)
        self.assertFails(self.check("text_overlap", artists=report), "clipped at the figure's edge")

    def test_without_an_artist_report_the_check_does_not_pass(self):
        self.assertFails(self.check("text_overlap"), "no artist report")


class ProvenanceTest(FixtureProjectCase):
    def check(self, result):
        return fc.run_checks(self.project, self.request, result, style={}, policy=POLICY, artists=False, only={"provenance"})[0]

    def test_manifested_inputs_that_match_their_hashes_pass(self):
        outcome = self.check(self.result("fig1"))
        self.assertTrue(outcome["pass"], outcome["detail"])

    def test_a_changed_input_fails(self):
        (self.project / "results/t7-a1/scores.csv").write_text("method,auroc\nX,0.99\n", encoding="utf-8")
        self.assertIn("does not match its sha256", self.check(self.result("fig1"))["detail"])

    def test_an_input_missing_from_the_manifest_fails(self):
        manifest = load(self.project / "research/manifest.json")
        manifest["entries"] = manifest["entries"][1:]
        (self.project / "research/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        outcome = self.check(self.result("fig1"))
        self.assertFalse(outcome["pass"])
        self.assertIn("results/t7-a1/scores.csv is not in research/manifest.json", outcome["detail"])

    def test_a_malformed_run_id_and_empty_inputs_fail(self):
        result = self.result("fig1")
        result["final"]["inputs"][0]["run_id"] = "run_017"
        self.assertIn("names run 'run_017'", self.check(result)["detail"])
        result["final"]["inputs"] = []
        self.assertIn("nothing traces the figure", self.check(result)["detail"])


# --- the runner and the artist report ---------------------------------------------------------


class RunnerTest(FixtureProjectCase):
    def test_the_report_block_holds_every_check_in_order_and_validates(self):
        tools = fc.Tools(which=lambda name: None)  # no tool at all: every check still answers
        report = fc.run_checks(self.project, self.request, self.result("fig1"), policy=POLICY, tools=tools, artists=False)
        self.assertEqual([item["id"] for item in report], list(fc.CHECK_IDS))
        self.assertEqual(len(fc.CHECK_IDS), 19)
        result = {"schema": "figure_result/1", "ticket": "49", "figure_id": "fig1", "status": "failed_checks", "checks": report}
        self.assertEqual(validate(result, load_schema("figure_result")), [])

    def test_a_check_that_raises_is_recorded_as_failed(self):
        original = fc.CHECKS["caption_lint"]
        fc.CHECKS["caption_lint"] = lambda context: (_ for _ in ()).throw(OSError("disk gone"))
        self.addCleanup(fc.CHECKS.__setitem__, "caption_lint", original)
        report = fc.run_checks(self.project, self.request, self.result("fig1"), style={}, policy=POLICY, artists=False, only={"caption_lint"})
        self.assertEqual(report[0]["pass"], False)
        self.assertIn("disk gone", report[0]["detail"])


@MATPLOTLIB
@POPPLER
@RUFF
class FullRunTest(FixtureProjectCase):
    def test_the_sample_figure_passes_all_nineteen_checks(self):
        report = self.run_checks("fig1")
        self.assertEqual(list(report), list(fc.CHECK_IDS))
        failed = {check_id: item["detail"] for check_id, item in report.items() if not item["pass"]}
        self.assertEqual(failed, {})
        self.assertTrue((self.project / "figures/fig1/crops/a.png").is_file())
        self.assertIn("caption+artists", report["caption_panels"]["tool"])


@MATPLOTLIB
class ArtistReportTest(unittest.TestCase):
    GENERATOR = '''
import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as effects
import matplotlib.pyplot as plt
import numpy

figure, (left, right) = plt.subplots(1, 2, figsize=(4, 2))
left.set_gid("panel:a")
image = left.imshow(numpy.arange(16).reshape(4, 4), cmap="viridis")
image.set_gid("quantity:density")
figure.colorbar(image, ax=left)
left.set_xlim(0, 3)
left.text(0.5, 0.5, "halo", fontsize=5, path_effects=[effects.withStroke(linewidth=2, foreground="w")])
right.plot([0, 1], [0, 1], "--", gid="optional:e1")
right.plot([0, 1], [1, 0], "-", gid="required:e2", color="#0072B2")
right.plot([0, 1], [0.5, 0.5], color="#E69F00", gid="connector:c1")
right.set_axis_off()
right.text(0, 1, "b")
figure.savefig("out.pdf")
'''

    def test_the_report_describes_what_the_checks_read(self):
        work = Path(tempfile.mkdtemp(prefix="wayline-artists-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        (work / "gen.py").write_text(self.GENERATOR, encoding="utf-8")
        run = subprocess.run([sys.executable, "-I", str(fc.ARTISTS_SCRIPT), "--out", "report.json", "--width-mm", "50.8", "gen.py"],
                             cwd=work, capture_output=True, text=True, env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin", "HOME": str(work)})
        self.assertEqual(run.returncode, 0, run.stderr)
        report = load(work / "report.json")
        self.assertEqual(report["schema"], "figure_artists/1")
        figure = report["figures"][0]
        self.assertEqual(figure["saved_to"], "out.pdf")
        self.assertAlmostEqual(figure["figure"]["scale"], 0.5)
        texts = {item["text"]: item for item in figure["texts"]}
        self.assertTrue(texts["halo"]["haloed"])
        self.assertAlmostEqual(texts["halo"]["fontsize_pt"], 2.5)
        self.assertEqual(texts["b"]["role"], "panel_label")
        ticks = [item["text"] for item in figure["texts"] if item["role"] == "ticklabel"]
        self.assertTrue(ticks)
        right_ticks = [item for item in figure["texts"] if item["role"] == "ticklabel" and item["extent"][0] > figure["figure"]["width_px"] * 0.75]
        self.assertEqual(right_ticks, [], "the axis turned off draws no tick labels")
        self.assertEqual({panel["label"] for panel in figure["panels"]}, {"a", "b"})
        self.assertEqual(sorted((line["gid"], line["linestyle"]) for line in figure["marked_lines"]), [("optional:e1", "dashed"), ("required:e2", "solid")])
        self.assertEqual(figure["structure"], [{"gid": "connector:c1", "colors": ["#E69F00"]}])
        self.assertEqual(figure["mappables"], [{"cmap": "viridis", "quantity": "density"}])
        self.assertIn("#0072B2", figure["colors"])


# --- the standard-library readers -------------------------------------------------------------


class PdfWalkTest(unittest.TestCase):
    def test_sizes_colors_and_the_page_come_out_of_a_matplotlib_pdf(self):
        facts = fc.pdf_facts(SAMPLES / "palette-okabe-ito.pdf")
        self.assertAlmostEqual(facts.page_width_pt, 89 / 25.4 * 72, places=2)
        self.assertEqual(facts.colors, {"#E69F00", "#56B4E9", "#009E73", "#FFFFFF"})
        self.assertEqual(fc.pdf_facts(SAMPLES / "font-3pt.pdf").text_sizes, [3.0])
        self.assertEqual(fc.pdf_facts(SAMPLES / "raster-10px.pdf").images, 1)

    def test_the_transformation_matrices_scale_the_text_size(self):
        content = b"q 0.5 0 0 0.5 0 0 cm BT /F1 10 Tf 2 0 0 2 0 0 Tm (x) Tj ET Q BT /F1 4 Tf [(y)] TJ ET 1 0 0 rg"
        pdf = self.write_pdf(content, length=b"%d" % len(content))
        facts = fc.pdf_facts(pdf)
        self.assertEqual(facts.text_sizes, [10.0, 4.0])
        self.assertEqual(facts.colors, {"#FF0000"})
        self.assertEqual((facts.page_width_pt, facts.page_height_pt), (200.0, 100.0))

    def test_an_indirect_length_does_not_truncate_the_stream(self):
        content = zlib.compress(b"BT /F1 7 Tf (x) Tj ET")
        facts = fc.pdf_facts(self.write_pdf(content, length=b"12 0 R", flate=True))
        self.assertEqual(facts.text_sizes, [7.0])

    def write_pdf(self, content, length, flate=False):
        directory = Path(tempfile.mkdtemp(prefix="wayline-pdf-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        filters = b" /Filter /FlateDecode" if flate else b""
        body = (b"%PDF-1.4\n1 0 obj << /Type /Page /MediaBox [0 0 200 100] /Contents 2 0 R >> endobj\n"
                b"2 0 obj << /Length " + length + filters + b" >>\nstream\n" + content + b"\nendstream\nendobj\n"
                b"12 0 obj " + str(len(content)).encode() + b" endobj\n%%EOF\n")
        path = directory / "tiny.pdf"
        path.write_bytes(body)
        return path


class PngTest(unittest.TestCase):
    def test_every_filter_type_decodes_to_the_same_pixels(self):
        rng = random.Random(49)
        width, height = 13, 5
        rows = [bytes(rng.randrange(256) for _ in range(width * 3)) for _ in range(height)]
        expected = bytearray((299 * row[3 * x] + 587 * row[3 * x + 1] + 114 * row[3 * x + 2] + 500) // 1000 for row in rows for x in range(width))
        for kind in range(5):
            with self.subTest(filter=kind):
                path = self.encode(rows, width, height, kind)
                self.assertEqual(fc.png_size(path), (width, height))
                self.assertEqual(fc.png_luma(path), (width, height, expected))

    def test_a_matplotlib_png_decodes(self):
        width, height, luma = fc.png_luma(SAMPLES / "png-100dpi.png")
        self.assertEqual((width, height), fc.png_size(SAMPLES / "png-100dpi.png"))
        self.assertEqual(len(luma), width * height)
        self.assertEqual(max(luma), 255)  # the white ground
        self.assertLess(min(luma), 64)  # the black text

    def encode(self, rows, width, height, kind):
        bpp, previous, raw = 3, bytes(width * 3), bytearray()
        for row in rows:
            out = bytearray()
            for x, value in enumerate(row):
                left = row[x - bpp] if x >= bpp else 0
                above, corner = previous[x], previous[x - bpp] if x >= bpp else 0
                estimate = left + above - corner
                paeth = min((abs(estimate - left), 0, left), (abs(estimate - above), 1, above), (abs(estimate - corner), 2, corner))[2]
                predictor = (0, left, above, (left + above) >> 1, paeth)[kind]
                out.append((value - predictor) & 0xFF)
            raw += bytes([kind]) + out
            previous = row

        def chunk(tag, payload):
            return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))

        data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))
        directory = Path(tempfile.mkdtemp(prefix="wayline-png-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / ("filter-%d.png" % kind)
        path.write_bytes(data)
        return path


class SsimTest(unittest.TestCase):
    def setUp(self):
        rng = random.Random(7)
        self.width, self.height = 24, 16
        self.image = bytearray(rng.randrange(256) for _ in range(self.width * self.height))

    def test_an_image_is_identical_to_itself(self):
        self.assertEqual(fc.ssim(self.image, bytearray(self.image), self.width, self.height), 1.0)

    def test_a_slight_change_stays_close_and_an_inverted_image_does_not(self):
        nudged = bytearray(min(255, value + 2) for value in self.image)
        inverted = bytearray(255 - value for value in self.image)
        self.assertGreater(fc.ssim(self.image, nudged, self.width, self.height), 0.99)
        self.assertLess(fc.ssim(self.image, inverted, self.width, self.height), 0.0)
        self.assertAlmostEqual(fc.ssim(self.image, inverted, self.width, self.height), fc.ssim(inverted, self.image, self.width, self.height))

    def test_mismatched_sizes_raise(self):
        with self.assertRaises(ValueError):
            fc.ssim(self.image, self.image[:-1], self.width, self.height)


class ColorTest(unittest.TestCase):
    def test_ciede2000_reproduces_sharma_wu_and_dalal(self):
        self.assertAlmostEqual(fc.ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)), 2.0425, places=4)
        self.assertAlmostEqual(fc.ciede2000((50.0, 2.5, 0.0), (73.0, 25.0, -18.0)), 27.1492, places=4)
        self.assertAlmostEqual(fc.ciede2000((50.0, 0.0, 0.0), (50.0, -1.0, 2.0)), 2.3669, places=4)

    def test_red_and_green_collapse_under_deuteranopia(self):
        normal = fc.ciede2000(fc.srgb_to_lab(fc.hex_to_rgb("#CC3311")), fc.srgb_to_lab(fc.hex_to_rgb("#339933")))
        seen = [fc.simulate_cvd(fc.hex_to_rgb(color), "deuteranopia") for color in ("#CC3311", "#339933")]
        self.assertGreater(normal, 40)
        self.assertLess(fc.ciede2000(fc.srgb_to_lab(seen[0]), fc.srgb_to_lab(seen[1])), 10)

    def test_greys_spend_no_color(self):
        self.assertTrue(fc.is_grey("#000000"))
        self.assertTrue(fc.is_grey("#7F7F84"))
        self.assertFalse(fc.is_grey("#E69F00"))
        with self.assertRaises(ValueError):
            fc.hex_to_rgb("red")


if __name__ == "__main__":
    unittest.main()
