"""The plot index (Implementation Decisions 13): a catalog of chart types the figure role picks from.

`wayline figures build-index` crawls five public galleries (python-graph-gallery,
r-graph-gallery, Altair, seaborn, plotnine) through the fetch seam, at one request per second
with a descriptive User-Agent (`policy.plot_index.crawl_rate_per_s`), and writes
`figures/plot_index.json`: metadata and locators only, never the sites' prose or images. Every
field this module writes was read off a response or computed from one by a rule named in code,
the same discipline the scout holds for a reference: nothing here invents a caption.

Two fields cannot come from a page at all. `known_pitfalls` for matplotlib and TikZ entries is
seeded from the owner's `paper-figures` skill (Section 4), rewritten per entry rather than
copied, per research-notes 11 Section 2's classification table; `family` is this module's own
classification of a chart's name against BRIEF 13.1's eight families, a code decision like the
scout's title-similarity threshold, not a fact read off a page.

`wayline figures refresh` runs the link-liveness check (an HTTP request per stored `source_url`,
updating `last_verified`) or the full re-crawl (rebuilding the index, updating `last_crawled`,
carrying forward `known_pitfalls` an entry accumulated since); `fold_traps_hit` merges a figure
result's promoted traps into the index the same way.

**Data shapes** (Implementation Decision 17; ticket 77). The one field a model fills: each entry's
`data_shape`, one of `DATA_SHAPES` (from the research report prototype's `index_shapes.json`), and
its `canonical_chart_type`, the chart's plain name shared by every page that draws it (null for a
page that is no chart type for research data, shape `none`). `ShapeClassifier` asks one session of
the `shape-classifier` role (`policy.roles`, Haiku at low effort, no tools) per entry through the
launcher, its answer validated against `schemas/index_shape.json`, and keeps the answer under
`research/.cache/figures/shapes/<page sha256>.json`, so a rebuild over unchanged pages spends
nothing; the entry records the hash as `page_sha256`. The page text is the session's to read; the
index stores only the answer. A drawing matches a result's data views against these shapes to
choose which chart types to draw.

`figures/structure_index.json` (the four framework-figure layouts) and `figures/style.default.json`
(the color budget) are static content this module owns outright; they name no site and crawl
nothing.
"""

import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.cli import parse_args
from wayline.fetch import FetchError, caching_fetcher, canonical_url, recording_fetcher
from wayline.project import ProjectError, find_project, policy_for, read_harness

__all__ = [
    "FigureIndexError", "Site", "SITES", "FAMILIES", "DATA_SHAPES", "SHAPE_ROLE", "ShapeClassifier",
    "PLOT_INDEX_JSON", "STRUCTURE_INDEX_JSON",
    "STYLE_DEFAULT_JSON", "build_index", "refresh_liveness", "refresh_full", "fold_traps_hit",
    "structure_index", "default_style", "load_index", "write_index", "index_fetcher",
    "figures_command", "classify_family",
]

FAMILIES = (
    "distribution", "correlation", "ranking", "part_of_a_whole",
    "evolution", "flow", "map", "network", "multi_dimensional",
)

# What a chart type draws (the research report prototype's `index_shapes.json`): dist, one numeric
# variable over groups; xy, two numeric variables per observation; series, a value along an
# ordered x; category, one value per category; whole, parts of a whole; matrix, a value per pair of
# categories; multivar, rows of many variables; none, not a chart type for research data.
DATA_SHAPES = ("dist", "xy", "series", "category", "whole", "matrix", "multivar", "none")
SHAPE_ROLE = "shape-classifier"
SHAPE_SCHEMA = "index_shape"
SHAPE_MAX_TURNS = 3
SHAPE_MAX_MINUTES = 5
SHAPE_PAGE_CHARS = 6000  # of the page's text, enough for the title, the prose, and the call

PLOT_INDEX_JSON = "plot_index.json"
STRUCTURE_INDEX_JSON = "structure_index.json"
STYLE_DEFAULT_JSON = "style.default.json"
FIGURES = "figures"
CACHE = ".cache/figures"

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HEADING = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_TITLE_SPLIT = re.compile(r"\s*[–—-]{1,2}\s*")
_HREF = re.compile(r'href=["\']?([^"\'#>\s]+)')


class FigureIndexError(ValueError):
    """The index cannot be built or read: a source answered nothing usable, or the file is not JSON."""


@dataclass(frozen=True)
class Site:
    """One gallery: where its index of chart pages lives, and how to read what it links to."""

    key: str
    index_url: str
    default_library: str
    license_note: str
    page_pattern: str  # a regex matched against an href relative to index_url's directory
    sitemap: bool = False  # plotnine: the index_url is a sitemap, read as XML, not HTML


# The five sources named in BRIEF 13.1 and verified in research-notes 09. `page_pattern` matches
# the relative path of a chart page as it appears in the index page's own `href` attributes.
SITES = {
    "python-graph-gallery": Site(
        "python-graph-gallery", "https://python-graph-gallery.com/all-charts/", "matplotlib",
        "0BSD in the repo LICENSE (holtzy/The-Python-Graph-Gallery), but the copyright line reads "
        "Gatsby Inc.; likely a template artifact, doc-content coverage unverified (research-notes 09)",
        r"^/(\d[\w-]*)/$",
    ),
    "r-graph-gallery": Site(
        "r-graph-gallery", "https://r-graph-gallery.com/all-graphs.html", "ggplot2",
        "MIT in the repo LICENSE (holtzy/R-graph-gallery, 2015-2017 Holtz Yan); doc-content "
        "coverage unverified (research-notes 09)",
        r"^(\d[\w.-]*\.html)$",
    ),
    "altair": Site(
        "altair", "https://altair-viz.github.io/gallery/index.html", "altair",
        "BSD-3-Clause (vega/altair repo); doc-specific statement unverified (research-notes 09)",
        r"^([a-zA-Z][\w]*\.html)$",
    ),
    "seaborn": Site(
        "seaborn", "https://seaborn.pydata.org/examples/index.html", "seaborn",
        "BSD-3-Clause (mwaskom/seaborn repo); doc-specific statement unverified (research-notes 09)",
        r"^\.?/?([a-zA-Z][\w]*\.html)$",
    ),
    "plotnine": Site(
        "plotnine", "https://plotnine.org/sitemap.xml", "plotnine",
        "MIT (has2k1/plotnine repo, 2022 Hassan Kibirige)",
        r"",
        sitemap=True,
    ),
}

# A family classifier: the first pattern whose keyword appears in the chart's name wins. This is
# a code decision, not a fact read off a page, the same status as the scout's title-similarity
# threshold; `multi_dimensional` is the catch-all for a name that matches nothing else.
_FAMILY_KEYWORDS = (
    ("map", ("map", "choropleth", "cartogram")),
    ("network", ("network", "dendrogram", "chord diagram", "tree diagram", "arc diagram", "edge bundling")),
    ("flow", ("sankey", "flow diagram", "funnel")),
    # A compound keyword is checked before the families below get a chance at its head noun, so
    # "stacked area chart" reads as evolution (composition changing over time, research-notes 09's
    # own classification) rather than part_of_a_whole, which a bare "stacked" would give it.
    ("evolution", ("stacked area", "line chart", "area chart", "stream", "time series", "spaghetti", "evolution", "animation", "connected scatter")),
    ("part_of_a_whole", ("pie", "donut", "waffle", "venn", "treemap", "stacked")),
    ("distribution", ("histogram", "density", "violin", "boxplot", "box plot", "ridgeline", "distribution", "ecdf", "strip plot")),
    ("correlation", ("scatter", "correlogram", "heatmap", "bubble", "hexbin", "2d density", "regression")),
    ("ranking", ("bar", "lollipop", "dumbbell", "ranking", "radar", "spider")),
)

# python-graph-gallery is the one site whose pages mix two libraries (matplotlib and seaborn);
# a seaborn call site there overrides the site's matplotlib default. The other four sites are
# single-library galleries by construction, so their own default always stands: `ggplot2` and
# `plotnine` share the same call syntax (`ggplot() + geom_*()`), and a marker built on that
# syntax cannot tell the two libraries apart, only the site they were fetched from can.
_LIBRARY_OVERRIDES = {
    "python-graph-gallery": (("seaborn", re.compile(r"\bsns\s*\.\s*\w+|import\s+seaborn")),),
}

# The function or geom a library call names, once the library itself is known. A syntax
# highlighter wraps each token (including a lone `.`) in its own tag, so the search runs over
# the page with every tag removed rather than replaced by whitespace (`_tight`), and the pattern
# tolerates the run of spaces such stripping still leaves where the source itself had one.
_CALL_PATTERNS = {
    "seaborn": re.compile(r"\bsns\s*\.\s*[A-Za-z_][A-Za-z0-9_]*"),
    "matplotlib": re.compile(r"\bplt\s*\.\s*[A-Za-z_][A-Za-z0-9_]*"),
    "altair": re.compile(r"\bmark_[A-Za-z_]+|\balt\s*\.\s*Chart\b"),
    "plotnine": re.compile(r"\bgeom_[A-Za-z_]+"),
    "ggplot2": re.compile(r"\bgeom_[A-Za-z_]+"),
}

# matplotlib pitfalls, rewritten from the owner's `paper-figures` skill Section 4 (never copied
# verbatim) per research-notes 11 Section 2's classification table. Applied to every entry whose
# `library` is matplotlib.
_MATPLOTLIB_PITFALLS = (
    "A panel box drawn as a figure patch can paint over the axes inside it: figure patches are "
    "drawn after axes at equal z-order, so a filled box at the default zorder hides what is "
    "plotted on top of it. Give panel-box patches a negative zorder.",
    "A row of typeset equations cannot be scaled to a matching bounding-box height, because a "
    "tall multi-line formula shrinks everything else in the row to match; solve instead for one "
    "inches-per-pixel scale that fits every equation in the row.",
    "A few small API gaps bite here: `Text` has no `letterspacing` (space characters by hand); "
    "an annotation on 3D axes needs `text2D`, not `text`; a log-scale axis keeps its minor ticks "
    "after `set_xticks([])`, so `minorticks_off()` must be called explicitly.",
    "Text drawn with a stroke or halo path effect is emitted as outlines and is invisible to a "
    "`pdftotext` sweep of the PDF's text layer; verify such labels against the raster, not the "
    "text layer.",
    "A symbol legend or list embedded in the figure reads better typeset in LaTeX than laid out "
    "with matplotlib's own text primitives.",
)

# The embedding/quiver-specific pitfall (research-notes 11: "pitfalls for embedding and quiver
# types"), added only when the chart's name suggests one of those types.
_EMBEDDING_PITFALL = (
    "`set_aspect(\"equal\", adjustable=\"datalim\")` discards limits set beforehand and "
    "recomputes them from the plotted artists, so arrows near the edge of an embedding can be "
    "pushed outside the axes. Record the bounds the arrows need, expand the shorter axis by hand "
    "to the panel's own aspect ratio, and set `aspect=\"auto\"` instead."
)
_EMBEDDING_MARKERS = ("embedding", "quiver", "vector field")

# The network-family pitfalls (research-notes 11: matplotlib has no flat-bar arrowhead, so a
# signed graph goes to TikZ; plus the TikZ bridge itself), applied to every entry in that family
# regardless of the source site's own library.
_NETWORK_PITFALLS = (
    "matplotlib has no flat-bar arrowhead for a signed regulatory or influence graph; its "
    "closest option, `-[`, reads as a bracket rather than as repression. Draw a signed network "
    "in TikZ instead.",
    "A TikZ bridge for a network figure: a `standalone` document with the `tikz` and "
    "`arrows.meta` libraries, compiled with `pdflatex` and rasterized at 600 dpi with "
    "`pdftoppm`, its white background made transparent before it is embedded. Generate the TikZ "
    "from the real edge data so signs and weights are never hand-typed, and cache each render.",
)


# --- building the index ---------------------------------------------------------------------


def build_index(fetcher, clock=None, max_pages_per_site=None, url_filter=None, shapes=None):
    """Crawl the five sources through `fetcher` and return a fresh `plot_index.json` payload.

    `max_pages_per_site` bounds how many chart pages are fetched per site, for a deliberately
    partial run; `None` (the CLI default) crawls every page the index lists. `url_filter`, when
    given, keeps only the chart URLs it accepts before that cap is applied: the suite uses it to
    pin the exact pages its fixtures recorded, and a project may use it the same way to restrict
    a build to the chart families or libraries it actually needs.

    `shapes`, a `ShapeClassifier`, fills each entry's `data_shape` and `canonical_chart_type`
    (the verb always passes one); without it both stay null. An entry the classifier could not
    answer fails the build once every other entry has been asked, so a rerun asks only for it.
    """
    today = (clock() if clock else datetime.date.today().isoformat())
    entries = []
    counts = {}
    unanswered = []
    for site in SITES.values():
        pages = _crawl_site(fetcher, site, max_pages_per_site, url_filter)
        counts[site.key] = len(pages)
        for url, page_html in pages:
            entry = _entry_from_page(site, url, page_html, today)
            if entry is None:
                continue
            if shapes is not None:
                try:
                    entry.update(shapes.classify(entry, page_html))
                except FigureIndexError as failure:
                    unanswered.append("%s: %s" % (entry["id"], failure))
            entries.append(entry)
    if unanswered:
        raise FigureIndexError("the shape classifier answered nothing usable for %d entr%s: %s"
                               % (len(unanswered), "y" if len(unanswered) == 1 else "ies", "; ".join(unanswered)))
    return {
        "schema_version": 1,
        "built": today,
        "source_counts": counts,
        "entries": entries,
    }


def _crawl_site(fetcher, site, max_pages_per_site, url_filter=None):
    """`[(page_url, page_html), ...]` for every chart page `site` links to (or lists, for plotnine)."""
    urls = _sitemap_urls(fetcher, site) if site.sitemap else _index_urls(fetcher, site)
    if url_filter is not None:
        urls = [url for url in urls if url_filter(url)]
    if max_pages_per_site is not None:
        urls = urls[:max_pages_per_site]
    pages = []
    for url in urls:
        try:
            answer = fetcher.fetch(url)
        except FetchError:
            continue
        if answer.ok:
            pages.append((url, answer.text()))
    return pages


def _index_urls(fetcher, site):
    """The chart-page URLs linked from an HTML index page, in the order they appear."""
    try:
        answer = fetcher.fetch(site.index_url)
    except FetchError:
        return []
    if not answer.ok:
        return []
    base = site.index_url.rsplit("/", 1)[0] + "/"
    pattern = re.compile(site.page_pattern)
    seen, urls = set(), []
    for href in _HREF.findall(answer.text()):
        relative = href if not href.startswith(("http://", "https://")) else _relative_to(href, site.index_url)
        if relative is None or not pattern.match(relative):
            continue
        absolute = urllib.parse.urljoin(base, relative)
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)
    return urls


def _relative_to(absolute_href, index_url):
    """`absolute_href` as a path relative to `index_url`'s own host, or None off that host."""
    parts, base = urllib.parse.urlsplit(absolute_href), urllib.parse.urlsplit(index_url)
    if parts.hostname != base.hostname:
        return None
    return parts.path.rsplit("/", 1)[-1] if "/" in parts.path else parts.path


def _sitemap_urls(fetcher, site):
    """plotnine: every `<loc>` under `/gallery/` in the sitemap, `index.html` excluded."""
    try:
        answer = fetcher.fetch(site.index_url)
    except FetchError:
        return []
    if not answer.ok:
        return []
    try:
        root = ElementTree.fromstring(answer.body)
    except ElementTree.ParseError:
        return []
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    urls = []
    for url_element in root.findall(ns + "url"):
        loc = url_element.find(ns + "loc")
        text = (loc.text or "").strip() if loc is not None else ""
        if "/gallery/" in text and not text.endswith("/gallery/index.html") and not text.endswith("/gallery/"):
            urls.append(text)
    return urls


# --- one page into one entry -----------------------------------------------------------------


def _entry_from_page(site, url, page_html, today):
    title = _page_title(page_html)
    if not title:
        return None
    tight = _tight(page_html)
    library = _detect_library(site, tight)
    family = classify_family(title)
    slug = _slug(url)
    return {
        "id": "%s-%s" % (slug, site.key),
        "family": family,
        "chart_type": title,
        "data_shape": None,  # filled by the shape classifier, one of DATA_SHAPES
        "canonical_chart_type": None,
        "page_sha256": page_sha256(page_html),
        "when_to_use": None,
        "when_not_to_use": None,
        "library_implementations": [{
            "library": library,
            "function_or_geom": _call_site(tight, library),
            "snippet_locator": {"source_url": canonical_url(url), "anchor": _first_heading(page_html) or title},
        }],
        "gallery_links": [canonical_url(url), canonical_url(site.index_url)],
        "known_pitfalls": list(_seeded_pitfalls(library, family, title)),
        "source_site": site.key,
        "source_license": site.license_note,
        "last_verified": today,
        "last_crawled": today,
    }


def _page_title(page_html):
    found = _TITLE.search(page_html)
    if not found:
        return None
    text = _clean(found.group(1))
    return _TITLE_SPLIT.split(text, maxsplit=1)[0].strip() if text else None


def _first_heading(page_html):
    found = _HEADING.search(page_html)
    return _clean(found.group(1)) if found else None


def _clean(fragment):
    text = _SPACES.sub(" ", _TAG.sub(" ", html.unescape(fragment))).strip()
    return text or None


def _tight(page_html):
    """`page_html` with every tag removed and nothing put in its place.

    A syntax highlighter emits `sns.violinplot` as three tags around three text nodes, so
    replacing a tag with a space (`_clean`'s rule, right for block-level prose) would drive a
    wedge into the middle of that call; removing it outright keeps the call site readable as one
    token while still separating genuinely distinct words, since real whitespace was already text
    the tags never touched.
    """
    return html.unescape(_TAG.sub("", page_html))


def _slug(url):
    tail = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\.html?$", "", tail)
    tail = re.sub(r"^\d+[-_]?", "", tail)  # a leading numbered-slug prefix carries no identity
    tail = re.sub(r"[_\s]+", "-", tail).strip("-").lower()
    return tail or "entry"


def _detect_library(site, tight_html):
    for library, pattern in _LIBRARY_OVERRIDES.get(site.key, ()):
        if pattern.search(tight_html):
            return library
    return site.default_library


def _call_site(tight_html, library):
    pattern = _CALL_PATTERNS.get(library)
    found = pattern.search(tight_html) if pattern else None
    return re.sub(r"\s+", "", found.group(0)) if found else None


_MAP_KEYWORD = re.compile(r"(?<!heat)map")  # "heatmap" is correlation's, not this family's


def classify_family(chart_type):
    """The family BRIEF 13.1 groups `chart_type` under; `multi_dimensional` when nothing matches.

    A plain substring test is what lets "scatterplot", "boxplot", and "barplot" match their
    single-word keyword, since these galleries rarely space a chart name out; the one keyword
    that test misreads is "map", which a substring search also finds inside "heatmap", so that
    one keyword alone is matched with the lookbehind above instead.
    """
    lowered = (chart_type or "").lower()
    for family, keywords in _FAMILY_KEYWORDS:
        for keyword in keywords:
            found = _MAP_KEYWORD.search(lowered) if keyword == "map" else (keyword in lowered)
            if found:
                return family
    return "multi_dimensional"


def _seeded_pitfalls(library, family, chart_type):
    if library == "matplotlib":
        yield from _MATPLOTLIB_PITFALLS
        if any(marker in (chart_type or "").lower() for marker in _EMBEDDING_MARKERS):
            yield _EMBEDDING_PITFALL
    if family == "network":
        yield from _NETWORK_PITFALLS


# --- data shapes (decision 17) -----------------------------------------------------------------


def page_sha256(page_html):
    """The hash the shape cache is keyed by: the page's text as fetched."""
    return hashlib.sha256(page_html.encode("utf-8")).hexdigest()


class ShapeClassifier:
    """One Haiku session per index entry, through the launcher, cached by the entry's page hash.

    `classify(entry, page_html)` returns `{data_shape, canonical_chart_type}`, from
    `research/.cache/figures/shapes/<page sha256>.json` when the page was answered before, and
    otherwise from one session of the `shape-classifier` role, whose answer the launcher
    validates against `schemas/index_shape.json`. A session with no usable answer raises
    `FigureIndexError` and caches nothing. `calls` counts the sessions this classifier launched.
    """

    def __init__(self, project, policy=None, harness_root=None):
        self.project = Path(project).resolve()
        self.harness_root = Path(harness_root or HARNESS_ROOT).resolve()
        entry = ((policy if policy is not None else policy_for(self.project)).get("roles") or {}).get(SHAPE_ROLE) or {}
        self.model, self.effort = entry.get("model") or "haiku", entry.get("effort") or "low"
        self.cache = self.project / "research" / CACHE / "shapes"
        self.calls = 0

    def classify(self, entry, page_html):
        digest = page_sha256(page_html)
        cached = self._cached(digest)
        if cached is not None:
            return cached
        answer = self._ask(entry, page_html, digest)
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / (digest + ".json")).write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return answer

    def _cached(self, digest):
        try:
            stored = json.loads((self.cache / (digest + ".json")).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if stored.get("data_shape") not in DATA_SHAPES:
            return None
        return {"data_shape": stored["data_shape"], "canonical_chart_type": stored.get("canonical_chart_type")}

    def _ask(self, entry, page_html, digest):
        from wayline import worker  # the launcher; only a build that classifies needs it

        role = worker.read_role(SHAPE_ROLE, self.harness_root, self.project)
        run_dir = self.project / "research" / "sessions" / SHAPE_ROLE / digest[:16]
        number = 1
        while (run_dir / str(number)).exists():
            number += 1
        request = worker.LaunchRequest(
            role=SHAPE_ROLE, model=self.model, effort=self.effort, prompt=_shape_prompt(entry, page_html, role),
            agent_json=role.agent_json(self.model, self.effort, SHAPE_MAX_TURNS), allowed_tools=[],
            disallowed_tools=list(role.disallowed_tools), settings_path=None, add_dirs=[], cwd=str(self.project),
            env={"WAYLINE_PROJECT": str(self.project), "WAYLINE_RUN": str(run_dir / str(number))},
            schema_path=str(self.harness_root / "schemas" / (SHAPE_SCHEMA + ".json")), max_minutes=SHAPE_MAX_MINUTES,
        )
        self.calls += 1
        try:
            envelope = worker.launch(request)
        except worker.LaunchError as failure:
            raise FigureIndexError("the session could not be launched: %s" % failure) from None
        if not envelope.valid or not envelope.structured_output:
            raise FigureIndexError("; ".join(envelope.errors) if envelope.errors else "no usable answer")
        answer = envelope.structured_output
        return {"data_shape": answer["data_shape"], "canonical_chart_type": answer.get("canonical_chart_type")}


def _shape_prompt(entry, page_html, role):
    implementation = (entry.get("library_implementations") or [{}])[0]
    text = _clean(page_html) or ""
    lines = [
        "- subject: the data shape of one plot gallery page's chart type",
        "", "## The page, as code read it", "",
        "Title: %s" % (entry.get("chart_type") or ""),
        "Gallery: %s" % (entry.get("source_site") or ""),
        "Library: %s" % (implementation.get("library") or "unknown"),
        "Call: %s" % (implementation.get("function_or_geom") or "none found"),
        "", "Page text (the first %d characters):" % SHAPE_PAGE_CHARS, "", text[:SHAPE_PAGE_CHARS],
        "", "## The shapes", "",
        "- `dist`: one numeric variable, over one or more groups (seeds, arms, conditions)",
        "- `xy`: two numeric variables per observation",
        "- `series`: a value along an ordered x, with or without a band",
        "- `category`: one value per category, with or without an interval",
        "- `whole`: parts that add up to a whole, per category or along x",
        "- `matrix`: a value per pair of categories",
        "- `multivar`: rows of many variables",
        "- `none`: not a chart type for research data (styling, a tutorial, a map, art, interaction, animation)",
    ]
    parts = ["\n".join(lines).rstrip(), (role.protocol or "").strip(),
             "# Your answer\n\nReturn `data_shape` (one of the eight), `canonical_chart_type` (the chart's plain name, "
             "such as `density` or `box with points`, the same for every page that draws it; null when the shape is "
             "`none`), and `reason` (one sentence) through the structured output."]
    return "\n\n".join(part for part in parts if part) + "\n"


# --- refresh ----------------------------------------------------------------------------------


def refresh_liveness(fetcher, index, clock=None):
    """HEAD (falling back to GET) every entry's `source_url`; update `last_verified` on a 200."""
    today = clock() if clock else datetime.date.today().isoformat()
    checked, live, dead = 0, 0, []
    for entry in index.get("entries", []):
        for implementation in entry.get("library_implementations", []):
            url = implementation.get("snippet_locator", {}).get("source_url")
            if not url:
                continue
            checked += 1
            if _reachable(fetcher, url):
                live += 1
                entry["last_verified"] = today
            else:
                dead.append(url)
    return {"checked": checked, "live": live, "dead": dead}


def _reachable(fetcher, url):
    for method in ("HEAD", "GET"):
        try:
            answer = fetcher.fetch(url, method=method)
        except FetchError:
            continue
        if answer.status == 405:  # a site that refuses HEAD; GET is the fallback, not a failure
            continue
        return answer.ok
    return False


def refresh_full(fetcher, previous, clock=None, max_pages_per_site=None, url_filter=None, shapes=None):
    """Rebuild the index; an id also present in `previous` keeps its accumulated `known_pitfalls`.

    `shapes` classifies as `build_index` does; its cache makes the pages that did not change free.
    """
    fresh = build_index(fetcher, clock=clock, max_pages_per_site=max_pages_per_site, url_filter=url_filter, shapes=shapes)
    carried = {entry["id"]: entry.get("known_pitfalls", []) for entry in previous.get("entries", [])}
    for entry in fresh["entries"]:
        old = carried.get(entry["id"])
        if old:
            entry["known_pitfalls"] = _merge_pitfalls(entry["known_pitfalls"], old)
    return fresh


def _merge_pitfalls(seeded, carried):
    merged = list(seeded)
    for pitfall in carried:
        if pitfall not in merged:
            merged.append(pitfall)
    return merged


def fold_traps_hit(index, traps_hit):
    """Merge `traps_hit` entries with `promote_to_index: true` into their matching entries' pitfalls.

    A trap matches an index entry by `chart_type` and, when the trap names one, by `library`; a
    trap that matches nothing is left out, because inventing a new catalog entry from a figure
    result's free text would be exactly the fabrication the scout's discipline forbids here too.
    """
    unmatched = []
    for trap in traps_hit:
        if not trap.get("promote_to_index"):
            continue
        matched = False
        for entry in index.get("entries", []):
            if entry["chart_type"].lower() != str(trap.get("chart_type", "")).lower():
                continue
            if trap.get("library") and not any(
                implementation["library"] == trap["library"] for implementation in entry["library_implementations"]
            ):
                continue
            pitfall = trap.get("description") or trap.get("fix")
            if pitfall and pitfall not in entry["known_pitfalls"]:
                entry["known_pitfalls"].append(pitfall)
            matched = True
        if not matched:
            unmatched.append(trap)
    return unmatched


# --- structure_index.json and style.default.json ----------------------------------------------


def structure_index():
    """The four framework-figure layouts of BRIEF 13.1, static content this module owns outright."""
    return {
        "schema_version": 1,
        "structures": [
            {
                "id": "pipeline",
                "description": "a left-to-right chain of stages, one box per stage, joined by arrows in the order data or control flows",
                "panel_layout": "single row of boxes, equal height, connected by directional arrows",
            },
            {
                "id": "funnel-and-fan",
                "description": "one input narrowing through filtering or selection stages, then broadening into several parallel outputs",
                "panel_layout": "converging boxes into a waist, then diverging boxes out of it",
            },
            {
                "id": "grid",
                "description": "independent components or conditions shown side by side for direct visual comparison",
                "panel_layout": "uniform rows and columns of same-sized panels, shared axis scales where the quantities match",
            },
            {
                "id": "before-and-after",
                "description": "the same subject shown under two conditions or at two times, to make a change legible",
                "panel_layout": "two panels side by side or stacked, identical framing, one labeled difference highlighted",
            },
        ],
    }


def default_style():
    """The color budget of BRIEF 13.1: one categorical set, one ramp per quantity, a diverging
    pair, one special hue, and the equation-parameter colors. The categorical set is Okabe and
    Ito's 2008 palette, chosen for being distinguishable under the common forms of color-vision
    deficiency; a project overrides any of this in its own `figures/style.json`, which `init`
    copies from the same file this reads (`figures/style.default.json` in the harness).

    Two keys serve the palette check rather than the drawing: `diverging.cmap` names the ramp the
    diverging pair is drawn with, and `cvd_min_delta_e` is the CIEDE2000 distance a color outside
    the budget must keep from every other color under simulated color-vision deficiency.
    """
    return json.loads((HARNESS_ROOT / FIGURES / STYLE_DEFAULT_JSON).read_text(encoding="utf-8"))


# --- reading and writing the ledger's copies ----------------------------------------------------


def load_index(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return {"schema_version": 1, "built": None, "source_counts": {}, "entries": []}
    except ValueError as failure:
        raise FigureIndexError("%s is not valid JSON: %s" % (path, failure)) from None


def write_index(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_static(path, payload):
    if Path(path).exists():
        return path  # a project's own edits to a static file are never overwritten by a rebuild
    return write_index(path, payload)


# --- the verb -----------------------------------------------------------------------------------


def index_fetcher(project, email=None, fixtures=None):
    """The fetcher a build or refresh runs on: the project's cache, or a directory of recordings."""
    if fixtures is not None:
        return recording_fetcher(fixtures, email=email)
    return caching_fetcher(Path(project) / "research" / CACHE, email=email)


def figures_command(args):
    if not args:
        print("wayline figures: build-index|refresh", file=sys.stderr)
        return 2
    sub, rest = args[0], args[1:]
    if sub == "build-index":
        return _build_index_command(rest)
    if sub == "refresh":
        return _refresh_command(rest)
    if sub == "fold-traps":
        return _fold_traps_command(rest)
    print("wayline figures: unknown subcommand %r (build-index|refresh|fold-traps)" % sub, file=sys.stderr)
    return 2


def _fold_traps_command(args):
    """`wayline figures fold-traps <figure_result.json>`: the evolve loop's way into the index (ticket 50)."""
    parser = argparse.ArgumentParser(prog="wayline figures fold-traps",
                                     description="fold a figure result's promoted traps into figures/plot_index.json")
    parser.add_argument("result", help="a figure_result/1 file, relative to the project or absolute")
    parser.add_argument("--project", help="the project; the active one by default")
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        source = Path(options.result)
        source = source if source.is_absolute() else Path(project) / source
        traps = json.loads(source.read_text(encoding="utf-8")).get("traps_hit") or []
        path = Path(project) / FIGURES / PLOT_INDEX_JSON
        index = load_index(path)
        promoted = [trap for trap in traps if trap.get("promote_to_index")]
        unmatched = fold_traps_hit(index, promoted)
        write_index(path, index)
    except (ProjectError, FigureIndexError, OSError, ValueError, AttributeError) as failure:
        print("wayline figures fold-traps: %s" % failure, file=sys.stderr)
        return 1
    report = {"promoted": len(promoted), "folded": len(promoted) - len(unmatched), "unmatched": unmatched}
    if options.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        lines = ["%d of %d promoted trap(s) folded into %s" % (report["folded"], report["promoted"], path)]
        lines += ["  no entry for %s, %s: left out" % (trap.get("library"), trap.get("chart_type")) for trap in unmatched]
        print("\n".join(lines))
    return 0


def _add_common(parser):
    parser.add_argument("--project", help="the project to build for; the active one by default")
    parser.add_argument("--fixtures", help="answer every request from this directory of recorded responses instead of the network")
    parser.add_argument("--json", action="store_true", help="print the report as JSON instead of text")


def _build_index_command(args):
    parser = argparse.ArgumentParser(prog="wayline figures build-index", description="build figures/plot_index.json")
    _add_common(parser)
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        email = _email(project)
        fetcher = index_fetcher(project, email=email, fixtures=options.fixtures)
        index = build_index(fetcher, shapes=ShapeClassifier(project))
        directory = Path(project) / FIGURES
        write_index(directory / PLOT_INDEX_JSON, index)
        _write_static(directory / STRUCTURE_INDEX_JSON, structure_index())
        _write_static(directory / STYLE_DEFAULT_JSON, default_style())
    except (ProjectError, FigureIndexError, OSError) as failure:
        print("wayline figures build-index: %s" % failure, file=sys.stderr)
        return 1
    report = {"entries": len(index["entries"]), "source_counts": index["source_counts"]}
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else _render_build(report))
    return 0


def _refresh_command(args):
    parser = argparse.ArgumentParser(prog="wayline figures refresh", description="refresh figures/plot_index.json")
    _add_common(parser)
    parser.add_argument("--full", action="store_true", help="re-crawl every source instead of only checking liveness")
    options, code = parse_args(parser, args)
    if options is None:
        return code
    try:
        project = find_project(options.project)
        email = _email(project)
        fetcher = index_fetcher(project, email=email, fixtures=options.fixtures)
        path = Path(project) / FIGURES / PLOT_INDEX_JSON
        previous = load_index(path)
        if options.full:
            index = refresh_full(fetcher, previous, shapes=ShapeClassifier(project))
            report = {"mode": "full", "entries": len(index["entries"]), "source_counts": index["source_counts"]}
        else:
            index = previous
            report = {"mode": "liveness", **refresh_liveness(fetcher, index)}
        write_index(path, index)
    except (ProjectError, FigureIndexError, OSError) as failure:
        print("wayline figures refresh: %s" % failure, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else _render_refresh(report))
    return 0


def _email(project):
    try:
        return read_harness(project).get("owner_email")
    except (ProjectError, OSError, ValueError):
        return None


def _render_build(report):
    lines = ["%d entries across %d sources:" % (report["entries"], len(report["source_counts"]))]
    for site, count in report["source_counts"].items():
        lines.append("  %-22s %d page(s)" % (site, count))
    return "\n".join(lines)


def _render_refresh(report):
    if report["mode"] == "full":
        lines = ["full re-crawl: %d entries across %d sources:" % (report["entries"], len(report["source_counts"]))]
        for site, count in report["source_counts"].items():
            lines.append("  %-22s %d page(s)" % (site, count))
        return "\n".join(lines)
    lines = ["liveness: %d/%d source URLs answered" % (report["live"], report["checked"])]
    for url in report["dead"]:
        lines.append("  dead: %s" % url)
    return "\n".join(lines)
