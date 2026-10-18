"""The document viewer (ticket 74), in a real browser over HTTP against the fixture ledger.

What the viewer promises is only observable where the page runs: math that renders, a sanitizer
that holds, a `<dialog>` a poll leaves open, a zoom that rewraps at phone width, and no request that
leaves the machine. So these tests start the real `DashboardServer` on a copy of `fixtures/ledger/`,
load the real page in a headless Chromium (`tests/browser.py`), and assert on what the page did.
The constructs are the ones research note 04 recorded (`research/viewer-math-and-zoom`, sections 3
and 4): each delimiter, the `*` inside math, each shim, and the numbered equation.

A machine without a Chromium skips them; `WAYLINE_CHROMIUM` names one explicitly.
"""

import json
import os
import re
import struct
import unittest
import zlib

from tests.browser import Browser, find_chromium
from tests.paths import HARNESS_ROOT
from tests.test_dashboard import DashboardTestCase

CHROMIUM = find_chromium()

# What a rendered fragment holds, read off the DOM `renderMarkdown` returns.
PROBE = """(() => {
  const node = renderMarkdown(%s);
  const all = (selector) => [...node.querySelectorAll(selector)];
  // The words around the math: the document with every formula taken out.
  const bare = node.cloneNode(true);
  bare.querySelectorAll('.katex').forEach((formula) => formula.remove());
  return {
    html: node.innerHTML,
    math: all('.katex').length,
    display: all('.katex-display').length,
    // A formula KaTeX could not parse is its red source with the message in its title; a command it
    // does not know is drawn in the same red inside a formula that otherwise parsed.
    errors: all('.katex-error').map((e) => e.getAttribute('title') || e.textContent)
      .concat(all('.katex-html [style*="color:#cc0000"]').map((e) => 'undefined: ' + e.textContent)),
    em_math: all('em').map((e) => e.querySelectorAll('.katex').length),
    strong_math: all('strong').map((e) => e.querySelectorAll('.katex').length),
    // Each number as the reader sees it: an align stacks its rows' tags in one column, one per row.
    tags: all('.katex-html .katex-tag').flatMap((tag) => {
      const rows = [...tag.querySelectorAll('.vlist > span > .pstrut + span')];
      return (rows.length ? rows : [tag]).map((row) => row.textContent.replace(/\u200b/g, ''));
    }).filter(Boolean), // an unnumbered row's cell is empty
    annotations: all('annotation').length,
    text: bare.textContent,
  };
})()"""


@unittest.skipUnless(CHROMIUM, "no Chromium on this machine (set WAYLINE_CHROMIUM to one)")
class BrowserTestCase(DashboardTestCase):
    """The dashboard of `DashboardTestCase`, loaded in one headless Chromium shared by the class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = Browser(CHROMIUM)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.page = self.browser.page()
        self.addCleanup(self.page.close)

    def origin(self):
        return "http://%s:%d" % (self.host, self.port)

    def open_dashboard(self):
        self.page.goto(self.origin() + "/")
        self.page.wait_for("typeof renderMarkdown === 'function' && document.querySelector('#outputs-body ul.outputs')")

    def render(self, markdown):
        return self.page.evaluate(PROBE % json.dumps(markdown))


class MathRenderingTest(BrowserTestCase):
    """Each construct the research note recorded, through the one path from Markdown to HTML."""

    def setUp(self):
        super().setUp()
        self.open_dashboard()

    def test_a_star_inside_dollar_math_never_pairs_into_emphasis(self):
        out = self.render("Stars: $a^*b^*$ and *see $a*b$ here*.")
        self.assertEqual(out["math"], 2)
        self.assertEqual(out["errors"], [])
        # One emphasis, around the words and the formula, as the author meant: without the mask the
        # `*` inside `$a*b$` closes it early and the last `*` is left as a literal star.
        self.assertEqual(out["em_math"], [1], out["html"])
        self.assertNotIn("$", out["text"])
        self.assertNotIn("*", out["text"])

    def test_each_of_the_four_delimiters_is_taken_before_markdown_reads_it(self):
        cases = {
            "dollar": ("Inline $x_i^* = \\arg\\min_{x} f(x_1, x_2)$ here.", 1, 0),
            "double dollar": ("$$\n\\int_0^1 x\\,dx = \\tfrac{1}{2}\n$$", 1, 1),
            "parenthesis": ("Parenthesis \\(\\mathbf{W}^\\top \\boldsymbol{\\mu} \\in \\mathbb{R}^{d}\\) and a thin space \\(a\\,b\\;c\\!d\\).", 2, 0),
            "bracket": ("\\[\n\\sum_{i=1}^n \\{x_i\\}\n\\]", 1, 1),
            "double dollar inside a paragraph": ("The bound $$a \\le b$$ holds.", 1, 1),
            "two brackets on one line": ("\\[a = b\\] and \\[c = d\\]", 2, 2),
        }
        for name, (source, formulas, displays) in cases.items():
            with self.subTest(delimiter=name):
                out = self.render(source)
                self.assertEqual((out["math"], out["display"]), (formulas, displays), out["html"])
                self.assertEqual(out["errors"], [], out["html"])
                self.assertNotRegex(out["text"], r"[$\\]", out["html"])

    def test_an_align_row_that_starts_with_a_plus_stays_in_its_display(self):
        out = self.render("\\begin{align}\na &= b \\\\\n+ c &= d\n\\end{align}")
        self.assertEqual((out["math"], out["display"]), (1, 1), out["html"])
        self.assertNotIn("<li>", out["html"])
        self.assertEqual(out["errors"], [])

    def test_prices_escaped_dollars_and_code_stay_text(self):
        out = self.render("It costs \\$5 and \\$10, from $20,000 to $30,000, a $ b $ c, and `$x$` in code.")
        self.assertEqual(out["math"], 0, out["html"])
        self.assertIn("$20,000 to $30,000", out["text"])
        self.assertIn("<code>$x$</code>", out["html"])

    def test_a_display_holds_no_blank_line_and_an_unclosed_one_costs_one_paragraph(self):
        out = self.render("$$\nnever closed\n\nA paragraph.\n\nAnother.\n\n$$y$$")
        self.assertEqual(out["math"], 1, out["html"])
        self.assertIn("<p>A paragraph.</p>", out["html"])
        self.assertIn("<p>Another.</p>", out["html"])

    def test_every_formula_keeps_its_mathml_annotation_through_the_sanitizer(self):
        out = self.render("$a$, $b^2$, and\n\n$$c = \\sqrt{d}$$")
        self.assertEqual(out["math"], 3)
        self.assertEqual(out["annotations"], 3, "DOMPurify's defaults strip <annotation>; the viewer adds it back")


class MathShimsTest(BrowserTestCase):
    """The commands a paper's LaTeX has that KaTeX lacks (research note 04, section 3)."""

    def setUp(self):
        super().setUp()
        self.open_dashboard()

    def test_each_shim_renders_without_an_error(self):
        cases = {
            "label": "$$\\begin{equation} a = b \\label{eq:ab} \\end{equation}$$",
            "a redefined macro": "$$\\newcommand{\\R}{\\mathcal{R}}\\newcommand{\\E}{\\mathbb{E}} \\R(\\theta) = \\E[\\ell]$$",
            "a redefined macro without braces": "$$\\newcommand\\N{\\mathcal{N}} \\N(0, 1)$$",
            "DeclareMathOperator": "$$\\DeclareMathOperator{\\Tr}{Tr} \\Tr(A)$$",
            "DeclareMathOperator*": "$$\\DeclareMathOperator*{\\argmin}{arg\\,min} \\argmin_x f(x)$$",
            "multline": "\\begin{multline}\na + b + c \\\\\n+ d + e\n\\end{multline}",
        }
        for name, source in cases.items():
            with self.subTest(shim=name):
                out = self.render(source)
                self.assertEqual(out["math"], 1, out["html"])
                self.assertEqual(out["errors"], [], out["html"])

    def test_a_macro_holds_for_the_rest_of_its_document_and_never_leaks_into_the_next(self):
        out = self.render("$\\newcommand{\\norm}[1]{\\lVert #1 \\rVert}$ and later $\\norm{x}$.")
        self.assertEqual(out["errors"], [], out["html"])
        self.assertTrue(self.render("$\\norm{x}$")["errors"], "a fresh document does not know the last one's macro")

    def test_equations_are_numbered_as_amsmath_does_and_references_resolve_both_ways(self):
        source = "\n\n".join([
            "Bayes' rule is \\eqref{eq:bayes}, the bound is \\eqref{eq:long}, and row \\ref{eq:row3} closes it.",
            "\\begin{equation}\np(z \\mid x) = \\frac{p(x \\mid z) p(z)}{p(x)} \\label{eq:bayes}\n\\end{equation}",
            "\\begin{align}\na &= b \\label{eq:row1} \\\\\n\\log p &\\ge \\mathcal{L} \\tag{ELBO} \\label{eq:elbo} \\\\\nc &= d \\label{eq:row3} \\\\\ne &= f \\notag\n\\end{align}",
            "\\begin{align*}\nu &= v\n\\end{align*}",
            "\\begin{multline}\na + b \\\\\n+ c \\label{eq:long}\n\\end{multline}",
            "After: \\eqref{eq:row1}, \\eqref{eq:elbo}, inside math $\\eqref{eq:bayes}$, and a missing one \\eqref{eq:nowhere}.",
        ])
        out = self.render(source)
        self.assertEqual(out["errors"], [], out["html"])
        self.assertEqual(out["tags"], ["(1)", "(2)", "(ELBO)", "(3)", "(4)"])
        self.assertIn("Bayes' rule is (1), the bound is (4), and row 3 closes it.", out["text"])
        self.assertIn("After: (2), (ELBO), inside math , and a missing one (??).", out["text"])

    def test_a_numbered_equation_written_with_a_pandoc_label_carries_its_number(self):
        out = self.render("$$a = b$$ {#eq:first}\n\n$$c = d$$\n\n$$e = f$$ {#eq:third}\n\nSee \\eqref{eq:third} and @eq:first.")
        self.assertEqual(out["errors"], [], out["html"])
        self.assertEqual(out["tags"], ["(1)", "(2)"])
        self.assertIn("See (2) and (1).", out["text"])


# A Markdown file long enough to scroll inside the viewer, with math in it.
LONG = "# Notes\n\n" + "\n\n".join(
    "Paragraph %d says $x_{%d}^2 + y^2 = r^2$ and goes on long enough to wrap on a narrow screen, "
    "as a report's paragraphs do." % (n, n) for n in range(120))


class ViewerTestCase(BrowserTestCase):
    """The page with Markdown files under `research/paper/`, which the outputs index lists."""

    NOTES = "research/paper/notes.md"

    @staticmethod
    def output_link(relpath):
        """The expression for the outputs list's link to `relpath`, or undefined until it is drawn."""
        return "[...document.querySelectorAll('#outputs-body li a')].find((a) => a.textContent === %s)" % json.dumps(relpath)

    def write(self, relpath, data):
        path = self.project / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path

    def open_viewer(self, relpath=None):
        """Click the output's `view` button, as the owner does, and wait for the file to render."""
        link = self.output_link(relpath or self.NOTES)
        self.page.wait_for(link)
        self.page.click(link + ".parentNode.querySelector('button')")
        self.page.wait_for("document.getElementById('viewer').open && document.querySelector('#viewer-doc .markdown, #viewer-doc img')")


class ViewerDialogTest(ViewerTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.NOTES, LONG)
        self.open_dashboard()

    def test_a_markdown_output_opens_in_a_modal_dialog_outside_the_redrawn_panels(self):
        self.open_viewer()
        state = self.page.evaluate("""(() => {
          const viewer = document.getElementById('viewer');
          return {
            tag: viewer.tagName, modal: viewer.matches(':modal'), inPanel: Boolean(viewer.closest('main, .panel')),
            formulas: viewer.querySelectorAll('#viewer-doc .katex').length,
            title: document.getElementById('viewer-title').textContent,
          };
        })()""")
        self.assertEqual(state["tag"], "DIALOG")
        self.assertTrue(state["modal"], "opened with showModal(), so the page behind is inert")
        self.assertFalse(state["inPanel"], "a poll redraws the panels; the viewer is not in one")
        self.assertEqual(state["formulas"], 120)
        self.assertEqual(state["title"], self.NOTES)

    def test_a_poll_while_the_viewer_is_open_leaves_it_open_and_scrolled_where_it_was(self):
        self.open_viewer()
        before = self.page.evaluate("""(() => {
          const body = document.getElementById('viewer-body');
          body.scrollTop = 900;
          document.querySelector('#outputs-body ul.outputs').dataset.before = 'yes';
          return body.scrollTop;
        })()""")
        self.assertGreater(before, 0, "the document is long enough to scroll")
        # A new output moves the index's tag, so the page's own next poll (every `poll_views_s`, 5 s in
        # the fixture) redraws the outputs panel whole.
        self.write("research/paper/another.md", "# Another\n")
        self.page.wait_for(self.output_link("research/paper/another.md"), timeout=15)
        after = self.page.evaluate("""(() => ({
          redrawn: !document.querySelector('#outputs-body ul.outputs[data-before]'),
          open: document.getElementById('viewer').open,
          scrollTop: document.getElementById('viewer-body').scrollTop,
          formulas: document.querySelectorAll('#viewer-doc .katex').length,
        }))()""")
        self.assertTrue(after["redrawn"], "the poll did redraw the panel behind the viewer")
        self.assertTrue(after["open"])
        self.assertEqual(after["scrollTop"], before)
        self.assertEqual(after["formulas"], 120)

    def test_escape_closes_the_viewer_and_gives_focus_back_to_the_view_button(self):
        self.open_viewer()
        self.page.press("Escape")
        self.page.wait_for("!document.getElementById('viewer').open")
        focused = self.page.evaluate("document.activeElement.textContent")
        self.assertEqual(focused, "view")


# What the zoom is, read off the page: the document's own CSS zoom, the bar's, and the level shown.
ZOOM = """(() => ({
  doc: getComputedStyle(document.getElementById('viewer-doc')).zoom,
  bar: getComputedStyle(document.querySelector('#viewer .viewer-bar')).zoom,
  level: document.querySelector('#viewer [data-zoom="reset"]').textContent,
}))()"""

# How the document sits in the screen: the viewer's box, whether the document scrolls sideways,
# and the first paragraph's height, which grows when zoom rewraps it.
FIT = """(() => {
  const box = document.getElementById('viewer').getBoundingClientRect();
  const body = document.getElementById('viewer-body');
  const paragraph = document.querySelector('#viewer-doc p');
  return {
    box: [box.left, box.top, box.width, box.height],
    sideways: body.scrollWidth - body.clientWidth,
    paragraph: paragraph.getBoundingClientRect().height,
    paragraphWidth: paragraph.getBoundingClientRect().right,
    buttons: [...document.querySelectorAll('#viewer .viewer-bar button')].map((b) => b.getBoundingClientRect().height),
  };
})()"""


class ViewerZoomTest(ViewerTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.NOTES, LONG)

    def test_plus_minus_and_zero_step_and_reset_the_documents_zoom_alone(self):
        self.open_dashboard()
        self.open_viewer()
        seen = []
        for key in ("+", "+", "-", "-", "-", "0", "="):
            self.page.press(key)
            seen.append(self.page.evaluate(ZOOM))
        self.assertEqual([state["doc"] for state in seen], ["1.1", "1.25", "1.1", "1", "0.9", "1", "1.1"])
        self.assertEqual(seen[1]["level"], "125%")
        self.assertEqual({state["bar"] for state in seen}, {"1"}, "the bar keeps its size")

    def test_at_phone_width_the_viewer_fills_the_screen_and_zoom_rewraps_the_text(self):
        self.page.screen(390, 844, mobile=True)
        self.open_dashboard()
        # A page wider than the phone widens the layout viewport, and the viewer's 100vw with it.
        self.page.wait_for("document.querySelector('#overview-body .grid')")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)
        self.open_viewer()
        before = self.page.evaluate(FIT)
        self.assertEqual(before["box"], [0, 0, 390, 844])
        self.assertLessEqual(before["sideways"], 0, "at 100% the document fits the screen")
        self.assertGreaterEqual(min(before["buttons"]), 44, "a thumb can hit every button")
        for _ in range(3):
            self.page.press("+")
        self.assertEqual(self.page.evaluate(ZOOM)["doc"], "1.5")
        after = self.page.evaluate(FIT)
        self.assertLessEqual(after["sideways"], 0, "at 150% the text rewraps instead of running off the screen")
        self.assertLessEqual(after["paragraphWidth"], 390)
        self.assertGreater(after["paragraph"], before["paragraph"] * 1.5, "the paragraph rewrapped onto more lines")


# A model-written document that tries everything a document should not be able to do to the page.
HOSTILE = """# Results

<style>body { background: rgb(255, 0, 0) !important; } #outputs { display: none; }</style>

<script>window.__pwned = 'script';</script>

<img src="x" onerror="window.__pwned = 'onerror'">

<p onclick="window.__pwned = 'onclick'" onmouseover="window.__pwned = 'onmouseover'">Hover me.</p>

[a link](javascript:window.__pwned='href') and <a href="javascript:window.__pwned='raw'">a raw one</a>.

<iframe src="javascript:parent.__pwned='iframe'"></iframe>

<svg><script>window.__pwned = 'svg';</script></svg>

Math with an escape attempt: $\\href{javascript:window.__pwned='tex'}{x}$ and $a</span><img src=x onerror="window.__pwned='tex2'">$.
"""

# What the rendered document carries, and what it did to the page around it.
AUDIT = """(() => {
  const doc = document.getElementById('viewer-doc');
  const attributes = [...doc.querySelectorAll('*')].flatMap((node) => [...node.attributes].map((a) => [a.name, a.value]));
  return {
    pwned: window.__pwned || null,
    styles: doc.querySelectorAll('style').length,
    scripts: doc.querySelectorAll('script, iframe, object, embed').length,
    handlers: attributes.filter(([name]) => name.startsWith('on')).map(([name]) => name),
    javascript: attributes.filter(([, value]) => /^\\s*javascript:/i.test(value)).map(([name]) => name),
    sheets: document.styleSheets.length,
    background: getComputedStyle(document.body).backgroundColor,
    outputs: getComputedStyle(document.getElementById('outputs')).display,
    formulas: doc.querySelectorAll('.katex, .katex-error').length,
  };
})()"""


class SanitizerTest(ViewerTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.NOTES, HOSTILE)
        self.open_dashboard()

    def test_a_documents_style_script_and_event_attributes_never_take_effect(self):
        page = self.page.evaluate("({ sheets: document.styleSheets.length, background: getComputedStyle(document.body).backgroundColor })")
        self.open_viewer()
        # Hover and click the paragraph that carried the handlers, as the owner reading it would.
        self.page.click("document.querySelector('#viewer-doc p')")
        audit = self.page.evaluate(AUDIT)
        self.assertIsNone(audit["pwned"], "no script, handler, or link ran")
        self.assertEqual(audit["styles"], 0)
        self.assertEqual(audit["scripts"], 0)
        self.assertEqual(audit["handlers"], [])
        self.assertEqual(audit["javascript"], [])
        self.assertEqual(audit["sheets"], page["sheets"], "the document added no stylesheet to the dashboard")
        self.assertEqual(audit["background"], page["background"])
        self.assertNotEqual(audit["outputs"], "none")
        self.assertEqual(audit["formulas"], 2, "every formula is drawn, the refused \\href as its red source")


def png(width=4, height=3):
    """A real PNG of one gray, so a browser that loaded it reports its size."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


# A report beside its plots, as a current report sits beside the plots it names.
REPORT = """# A report

![the plot beside it](figures/plot.png)

![a plot from the project's root](/results/baseline/curve.png)

![one that climbs out of the project](../../../outside.png)

![one from the network](https://example.com/plot.png)

[the notes beside it](other.md) and [a file above the project](../../../outside.png).

The other ways a page fetches by itself, each aimed off the workstation:

<img alt="a srcset" src="figures/plot.png" srcset="https://example.com/srcset.png 2x">

<p style="background-image: url(https://example.com/style.png)">A styled paragraph.</p>

<video poster="https://example.com/poster.png" src="https://example.com/video.mp4"></video>

<table background="https://example.com/table.png"><tr><td>a cell</td></tr></table>

<svg width="10" height="10"><image href="https://example.com/svg.png" width="10" height="10"></image></svg>

"""

IMAGES = """(() => [...document.querySelectorAll('#viewer-doc img')].map((image) => ({
  alt: image.alt, src: image.getAttribute('src'), width: image.naturalWidth, refused: image.getAttribute('data-refused'),
})))()"""


class VendoredMathTest(DashboardTestCase):
    """KaTeX as the page asks for it, over HTTP with no browser at all."""

    KATEX = HARNESS_ROOT / "dashboard" / "vendor" / "katex"

    def test_the_page_loads_katex_and_the_server_sends_each_file_as_its_type(self):
        page = self.get("/").text
        for reference, kind in (("/vendor/katex/katex.min.css", "text/css; charset=utf-8"),
                                ("/vendor/katex/katex.min.js", "text/javascript; charset=utf-8")):
            with self.subTest(file=reference):
                self.assertIn('"%s"' % reference, page)
                served = self.get(reference)
                self.assertEqual((served.status, served.headers["content-type"]), (200, kind))

    def test_every_font_the_stylesheet_names_first_is_vendored_beside_it_and_served(self):
        sheet = (self.KATEX / "katex.min.css").read_text(encoding="utf-8")
        firsts = re.findall(r"src:url\((fonts/[^)]+)\)", sheet)
        self.assertEqual(len(firsts), 20)
        for relative in firsts:
            with self.subTest(font=relative):
                self.assertTrue(relative.endswith(".woff2"), "a browser that reads woff2 asks for nothing else")
                served = self.get("/vendor/katex/" + relative)
                self.assertEqual((served.status, served.headers["content-type"]), (200, "font/woff2"))

    def test_no_katex_file_reaches_off_the_workstation(self):
        for name in ("katex.min.css", "katex.min.js"):
            with self.subTest(file=name):
                text = (self.KATEX / name).read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"https?://(?!www\.w3\.org/)[^\s\"')]+", text), [])
                self.assertNotIn("@import", text)


class ImagePathEndpointTest(DashboardTestCase):
    """The route a rendered document's images are served by, over HTTP with no browser at all.

    The viewer resolves an image's relative path against its document's directory and asks the
    download route for the result; the route serves what is inside the project and refuses what is
    not, however the request spells the way out.
    """

    def setUp(self):
        super().setUp()
        (self.project / "research" / "paper" / "figures").mkdir(parents=True, exist_ok=True)
        (self.project / "research" / "paper" / "figures" / "plot.png").write_bytes(png())
        (self.temp / "outside.png").write_bytes(png(7, 7))
        os.symlink(self.temp / "outside.png", self.project / "research" / "paper" / "figures" / "linked.png")

    def image(self, relpath):
        return self.get("/api/projects/%s/download/%s" % (self.project_id, relpath))

    def test_an_image_inside_the_project_is_served_as_an_image(self):
        response = self.image("research/paper/figures/plot.png")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.body, png())

    def test_an_image_path_that_leaves_the_project_is_refused(self):
        for relpath in ("research/paper/../../../outside.png", "research/paper/%2e%2e/%2e%2e/%2e%2e/outside.png",
                        "..%2Foutside.png", "research/paper/figures/linked.png"):
            with self.subTest(path=relpath):
                response = self.image(relpath)
                self.assertEqual(response.status, 404)
                self.assertNotEqual(response.body, png(7, 7))


class RelativeImageTest(ViewerTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.NOTES, REPORT)
        self.write("research/paper/other.md", "# Other notes\n\n$e^{i\\pi} + 1 = 0$\n")
        self.write("research/paper/figures/plot.png", png())
        self.write("results/baseline/curve.png", png(5, 2))
        (self.temp / "outside.png").write_bytes(png(7, 7))
        self.open_dashboard()

    def wait_for_images(self):
        self.page.wait_for("[...document.querySelectorAll('#viewer-doc img[src]')].every((image) => image.complete)")
        return {image["alt"]: image for image in self.page.evaluate(IMAGES)}

    def test_a_relative_image_is_served_from_inside_the_project_and_one_outside_is_refused(self):
        self.open_viewer()
        images = self.wait_for_images()
        beside = images["the plot beside it"]
        self.assertEqual(beside["width"], 4, "the plot loaded")
        self.assertTrue(beside["src"].startswith("/api/projects/%s/download/research/paper/figures/plot.png" % self.project_id), beside)
        self.assertEqual(images["a plot from the project's root"]["width"], 5)
        for alt in ("one that climbs out of the project", "one from the network"):
            with self.subTest(image=alt):
                self.assertIsNone(images[alt]["src"])
                self.assertTrue(images[alt]["refused"])
        asked = self.page.requests()
        self.assertFalse([url for url in asked if "outside.png" in url or "example.com" in url], asked)

    def test_a_relative_link_to_another_markdown_file_opens_it_in_the_viewer(self):
        self.open_viewer()
        self.page.click("[...document.querySelectorAll('#viewer-doc a')].find((a) => a.textContent === 'the notes beside it')")
        self.page.wait_for("document.getElementById('viewer-title').textContent === 'research/paper/other.md' && document.querySelector('#viewer-doc .katex')")
        self.assertEqual(self.page.evaluate("document.getElementById('viewer').open"), True)

    def test_a_link_out_of_the_project_is_left_without_a_target(self):
        self.open_viewer()
        link = self.page.evaluate("""(() => {
          const link = [...document.querySelectorAll('#viewer-doc a')].find((a) => a.textContent === 'a file above the project');
          return link.getAttribute('href');
        })()""")
        self.assertIsNone(link)


class NoRequestLeavesTheMachineTest(ViewerTestCase):
    def setUp(self):
        super().setUp()
        self.write(self.NOTES, LONG + "\n\n$$\\mathcal{L} = \\sum_i \\mathbb{E}\\left[\\log p(x_i)\\right]$$\n")
        self.open_dashboard()

    def test_the_fonts_come_from_the_dashboard_by_relative_url_and_nothing_from_anywhere_else(self):
        self.open_viewer()
        self.page.wait_for("document.fonts.status === 'loaded' && [...document.fonts].some((font) => font.family === 'KaTeX_Main' && font.status === 'loaded')")
        asked = self.page.requests()
        self.assertEqual([url for url in asked if not url.startswith(self.origin() + "/")], [], "every request stayed on the dashboard")
        fonts = {url: status for url, status in self.page.responses().items() if url.endswith(".woff2")}
        self.assertTrue(fonts, "the math asked for its fonts")
        for url, status in fonts.items():
            with self.subTest(font=url):
                self.assertTrue(url.startswith(self.origin() + "/vendor/katex/fonts/KaTeX_"), url)
                self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
