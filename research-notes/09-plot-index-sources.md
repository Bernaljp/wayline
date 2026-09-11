# 09 Plot index sources: crawlability and licensing

Ticket: `.scratch/harness/issues/09-plot-index-sources.md`. Brief: Section 13.1, OPEN-18.

Verified on 2026-09-11 by fetching, for each of the five gallery/documentation sites, its
`robots.txt`, its `sitemap.xml` (or the closest equivalent index page when no sitemap exists), the
project's license file on GitHub, and two sample chart/example pages, using the `WebFetch` tool
(and `curl` from Bash for raw HTTP status/byte confirmation on `robots.txt` and `sitemap.xml`). No
more than ten pages were fetched per site. Every claim below carries a URL; anything not directly
observed is marked "unverified". One background `curl` batch ran slowly (an earlier
`r-graph-gallery.com/sitemap_index.xml` probe appeared to hang past 120 seconds before the batch
job's completion notification arrived); it was re-run as part of a batched job and did complete,
confirming HTTP 404, so no data point here remains a timeout.

## Answer

### 1. python-graph-gallery.com

- **Index/sitemap URL.** No sitemap: both `https://python-graph-gallery.com/sitemap.xml` and
  `/sitemap_index.xml` return HTTP 404 (confirmed with `curl -o /dev/null -w '%{http_code}'`, and
  independently with `WebFetch`, 2026-09-11). The de facto full index is
  `https://python-graph-gallery.com/all-charts/`, linked from the homepage
  (https://python-graph-gallery.com/), plus per-family index pages such as
  `https://python-graph-gallery.com/violin-plot/`.
- **Approximate page count.** `/all-charts/` lists on the order of 100-150+ distinct chart pages
  (WebFetch estimate from the rendered thumbnail grid, https://python-graph-gallery.com/all-charts/,
  2026-09-11); the homepage groups them into about 40 chart-type sections under 8 families
  (distribution, correlation, ranking, part-of-a-whole, evolution, map, flow, general knowledge;
  https://python-graph-gallery.com/, 2026-09-11).
- **Page structure.** Individual pages use a numbered-slug URL pattern, e.g.
  `https://python-graph-gallery.com/50-basic-violinplot-and-input-formats/`. Structure observed on
  that page and on `https://python-graph-gallery.com/violin-plot/` (family index): title, a short
  intro paragraph, one or more worked sections (verbatim headings on the individual page: "One
  numerical variable only", "One variable and several groups", "Several variables", "Going
  further"), each with a Python code block and an embedded rendered PNG, then a "Related chart
  types" thumbnail strip at the bottom linking sibling chart types in the same family. No explicit
  "pitfalls" heading was seen on this page, but sibling pages in the same family do carry
  caution/callout prose inline (e.g. "Caveat" language reported for other pages in this gallery by
  search snippets; not independently refetched here, so treat as unverified beyond this one page).
- **robots.txt verdict.** No `robots.txt` exists (404), so nothing is disallowed; open crawling is
  permitted by the absence of a robots record.
- **License verdict for a derived catalog.** The site's footer links a "License (GitHub)" entry
  (https://python-graph-gallery.com/about/, 2026-09-11) which resolves to the source repo
  `holtzy/The-Python-Graph-Gallery`. That repo's `LICENSE` file is the BSD Zero-Clause License
  (0BSD), but the copyright line reads "Copyright (c) 2020 Gatsby Inc."
  (https://raw.githubusercontent.com/holtzy/The-Python-Graph-Gallery/master/LICENSE, 2026-09-11).
  This is very likely a leftover from the Gatsby.js starter template the site was scaffolded from,
  not a deliberate license grant over the tutorial prose. Treat "this repo's content is 0BSD" as
  **unverified**. What is not in question: a derived catalog as scoped by this ticket (chart
  family, chart type name, URL, and short structural metadata, no verbatim prose or images) is
  factual/referential, not a copy of the copyrightable expression, so it does not depend on
  resolving that ambiguity either way.
- **Fetch method verdict.** Plain `WebFetch`/stdlib HTTP was adequate for both the index page and
  individual chart pages; nothing on this site required JS rendering or interaction for the text
  content used here.

### 2. r-graph-gallery.com

- **Index/sitemap URL.** `https://r-graph-gallery.com/sitemap.xml` and
  `https://r-graph-gallery.com/sitemap_index.xml` both return HTTP 404 (curl, confirmed
  2026-09-11). The de facto full index is `https://r-graph-gallery.com/all-graphs.html`, linked
  from the homepage (https://r-graph-gallery.com/).
- **Approximate page count.** `/all-graphs.html` lists on the order of 150+ distinct chart pages
  (WebFetch estimate, https://r-graph-gallery.com/all-graphs.html, 2026-09-11), grouped into the
  same 8 families as the Python gallery (same author, same template): distribution, correlation,
  ranking, part-of-a-whole, evolution, map, flow, general knowledge
  (https://r-graph-gallery.com/, 2026-09-11).
- **Page structure.** Individual pages use a numbered-slug `.html` URL, e.g.
  `https://r-graph-gallery.com/136-stacked-area-chart.html`. There are also chart-**type** index
  pages at unnumbered slugs, e.g. `https://r-graph-gallery.com/violin.html`, which list several
  individual numbered pages plus a "🌐 From the Web" section of community links; the ticket's "two
  sample chart pages" were `r-graph-gallery.com/` (family/site structure) and
  `136-stacked-area-chart.html` (individual page: title, intro, four worked sections, with these
  verbatim headings: "Stacked area with ggplot2", "Control stacking order with ggplot2",
  "Proportional stacked area chart", "Color & style", each with an R/ggplot2 code block, plus a
  "Related chart types" footer and an email-signup callout). No dedicated "pitfalls" section, but
  ordering/coloring caveats are folded into the worked sections as prose.
- **robots.txt verdict.** No `robots.txt` (404); nothing disallowed.
- **License verdict for a derived catalog.** No license or terms text found on the site's About
  page (https://r-graph-gallery.com/about.html, 2026-09-11: "no license or terms of use are
  mentioned"). The source repo `holtzy/R-graph-gallery` carries an MIT `LICENSE` file, copyright
  "2015-2017 Holtz Yan"
  (https://raw.githubusercontent.com/holtzy/R-graph-gallery/master/LICENSE, 2026-09-11). As with
  the Python gallery, this is a repo-level software license and its coverage of the prose/tutorial
  content is **unverified**; a metadata-only derived catalog (URLs, chart type, family, library)
  again does not need that question resolved.
- **Fetch method verdict.** Plain `WebFetch`/stdlib HTTP was adequate for every page fetched on
  this site, including the (slow but ultimately 404) sitemap probes.

### 3. Altair (Vega-Altair) documentation gallery

- **Index/sitemap URL.** `https://altair-viz.github.io/sitemap.xml` and
  `https://altair-viz.github.io/robots.txt` both return HTTP 404. This is a GitHub Pages site and
  the 404 is GitHub's own "Page not found" HTML (confirmed byte-for-byte with `curl`, matching
  GitHub Pages' 404 template, 2026-09-11), not a custom robots record. The gallery index is
  `https://altair-viz.github.io/gallery/index.html`. `https://altair-viz.github.io/` itself is the
  live Sphinx-built docs homepage (Vega-Altair 6.2.2), not a redirect
  (https://altair-viz.github.io/, 2026-09-11).
- **Approximate page count.** The gallery index groups roughly 150+ example links into 13
  thematic categories: Simple Charts, Bar Charts, Line Charts, Area Charts, Circular Plots,
  Scatter Plots, Uncertainties and Trends, Distributions, Tables, Maps, Interactive Charts,
  Advanced Calculations, Case Studies, plus a "Recently Added" strip
  (https://altair-viz.github.io/gallery/index.html, 2026-09-11).
- **Page structure.** Individual pages use `https://altair-viz.github.io/gallery/<name>.html`.
  Two sampled: `simple_bar_chart.html` (title, short description, two equivalent code blocks, one
  method-syntax and one attribute-syntax, over a small pandas DataFrame, no download/Binder/Colab
  links, no visible tags) and `scatter_tooltips.html` (title, description, code block using
  `alt.datasets` "cars" data, `.interactive()` for pan/zoom, and tooltip field list). Both pages
  are built by Sphinx-Gallery-style tooling from the project's example scripts; no explicit
  "pitfalls" section on either sampled page.
- **robots.txt verdict.** No custom `robots.txt` on this GitHub Pages host; default-allow.
- **License verdict for a derived catalog.** The docs footer reads "© Copyright 2015-2026,
  Vega-Altair Developers" but does not itself restate the license
  (https://altair-viz.github.io/gallery/index.html, 2026-09-11). The project's repository license
  is BSD-3-Clause (https://raw.githubusercontent.com/vega/altair/main/LICENSE, 2026-09-11), and
  unlike the two gallery sites above, the gallery pages here are generated directly from example
  scripts that live in the same `vega/altair` repository tree, so the BSD-3-Clause grant plausibly
  covers them as a whole; still, treat "the rendered HTML gallery page text is BSD-3-Clause" as
  **unverified** since no doc-specific license statement was found. A metadata-only catalog entry
  is unaffected either way.
- **Fetch method verdict.** Plain `WebFetch` was adequate; static Sphinx HTML, no interaction
  needed.

### 4. seaborn example gallery

- **Index/sitemap URL.** `https://seaborn.pydata.org/robots.txt` and
  `https://seaborn.pydata.org/sitemap.xml` both return HTTP 404 (curl and WebFetch, 2026-09-11).
  The index is `https://seaborn.pydata.org/examples/index.html`.
- **Approximate page count.** Roughly 50 example thumbnails on the index page
  (https://seaborn.pydata.org/examples/index.html, 2026-09-11), organized as a flat thumbnail grid
  labeled by the primary seaborn function demonstrated (lmplot, scatterplot, boxplot, heatmap,
  etc.), not by chart family.
- **Page structure.** Individual pages use relative URLs under `/examples/`, e.g.
  `anscombes_quartet.html`, `grouped_barplot.html`. Two sampled:
  `examples/anscombes_quartet.html` (title only, no prose beyond the title, one code block
  chaining `set_theme()` / `load_dataset("anscombe")` / `lmplot()`, one embedded PNG, built-in
  dataset) and `examples/grouped_barplot.html` (title "Grouped barplots", one code block using
  `set_theme()` / `load_dataset("penguins")` / `catplot()`). Neither sampled page has an explicit
  pitfalls section; seaborn's example gallery is intentionally minimal (code + one figure, little
  prose).
- **robots.txt verdict.** No `robots.txt`; default-allow.
- **License verdict for a derived catalog.** Footer: "© Copyright 2012-2024, Michael Waskom"
  (https://seaborn.pydata.org/examples/anscombes_quartet.html, 2026-09-11), no explicit license
  text on the page itself. Repo license is BSD-3-Clause
  (https://raw.githubusercontent.com/mwaskom/seaborn/master/LICENSE.md, 2026-09-11); the example
  scripts live in the same repo (`doc/example_thumbs`/`examples/`), so as with Altair this plausibly
  covers the gallery, but is **unverified** as a doc-specific statement. Metadata-only catalog use
  is unaffected.
- **Fetch method verdict.** Plain `WebFetch` was adequate.

### 5. plotnine gallery

- **Index/sitemap URL.** `https://plotnine.org/robots.txt` returns HTTP 200 with a single line,
  `Sitemap: https://plotnine.org/sitemap.xml` (confirmed with `curl`, 2026-09-11), with no
  `Disallow` rules at all, fully permissive. `https://plotnine.org/sitemap.xml` is a valid XML
  sitemap. The gallery index is `https://plotnine.org/gallery/`.
- **Approximate page count.** The sitemap carries 500+ URLs total across the whole plotnine site
  (reference/API pages, guides, blog posts, and gallery pages together;
  https://plotnine.org/sitemap.xml, 2026-09-11). The gallery page itself reports "All (34)": 34
  gallery examples specifically, filterable by tags like "bar chart", "scatter plot", "heatmap",
  "theme", "animation" (https://plotnine.org/gallery/, 2026-09-11).
- **Page structure.** Individual pages use `https://plotnine.org/gallery/<slug>.html`. Two
  sampled: `annotated-heatmap.html` (title, one-line intro, three progressively refined code
  blocks: `geom_tile()`+`geom_text()`, then adding `scale_color_manual()`, then
  `scale_y_discrete()`/`theme()`, plus a "Read data" heading, a `pd.read_csv("data/flights.csv")`
  data load, and a closing credit note to the original seaborn example) and
  `bar-plot-with-2-variables.html` (title, description, category tags "bar chart"/"text", a
  synthetic in-page DataFrame, progressive code from stacked to `position="dodge"` to
  labeled/annotated bars, and a closing credit/caveat note about a lost original source link).
  Both sampled pages carry author attribution and tag metadata absent from the other four sites'
  pages, which makes plotnine's pages the easiest to parse mechanically for `plot_index.json`.
- **robots.txt verdict.** Fully permissive, explicitly points at the sitemap.
- **License verdict for a derived catalog.** Repo license (`has2k1/plotnine`) is MIT, copyright
  2022 Hassan Kibirige
  (https://raw.githubusercontent.com/has2k1/plotnine/main/LICENSE, 2026-09-11). MIT is the most
  unambiguous of the five for reuse purposes; gallery examples live in the same repo as the code,
  and each page even lists its author, reinforcing that this is repo-covered content.
- **Fetch method verdict.** Plain `WebFetch` was adequate; the sitemap alone is sufficient to
  build the full catalog without crawling the gallery's tag-filter UI.

### 6. Firecrawl CLI plugin availability

The `firecrawl` plugin is installed in this environment: its skills (`firecrawl-cli`,
`firecrawl-scrape`, `firecrawl-map`, `firecrawl-crawl`, `firecrawl-download`, `firecrawl-search`,
`firecrawl-monitor`, `firecrawl-agent`, `firecrawl-parse`, `firecrawl-interact`) all appear in the
available-skills list for this session. Per this ticket's instructions it was **not invoked**;
this is an availability check only, not a trial run. Because none of the five sites required JS
rendering, login, or interaction to read the content used in this note (all were static
server-rendered HTML: Sphinx docs, a static-site-generator gallery, or a Jekyll/Gatsby-style
blog), plain `WebFetch`/stdlib HTTP was sufficient for a one-time catalog build on all five. The
firecrawl `firecrawl-map` skill would still be the more convenient choice for an interactive,
human-supervised rebuild (it does site-wide URL discovery in one call instead of guessing slug
patterns, which is how `all-charts/` and `all-graphs.html` had to be found here), but it is not
required, and per the harness's plain-stdlib-first bias (Section 3.x elsewhere in BRIEF.md,
referenced but not re-derived here) an unattended refresh job should default to stdlib
`urllib`/`httpx` + the sitemap/index URLs recorded above, falling back to firecrawl only for a
site that starts requiring JS rendering.

## Proposed `plot_index.json` entry schema

```json
{
  "id": "string, stable slug, e.g. \"violin-basic-seaborn\"",
  "family": "string, one of: distribution | correlation | ranking | part_of_a_whole | evolution | flow | map | network | multi_dimensional",
  "chart_type": "string, e.g. \"violin plot\", \"stacked area chart\", \"annotated heatmap\"",
  "data_shape": {
    "n_variables": "integer or range, e.g. 1 or [2,3]",
    "variable_types": ["numeric", "categorical", "..."],
    "grouping": "none | single_group | nested_group",
    "notes": "free text, e.g. \"long-format data frame with one row per observation\""
  },
  "when_to_use": "free text: what claim/question this chart type supports",
  "when_not_to_use": "free text: known failure modes or better alternatives",
  "library_implementations": [
    {
      "library": "string, e.g. \"seaborn\", \"ggplot2\", \"altair\", \"plotnine\", \"matplotlib\"",
      "function_or_geom": "string, e.g. \"sns.violinplot\", \"geom_area\", \"mark_bar\"",
      "snippet_locator": {
        "source_url": "canonical gallery/docs URL for this example",
        "anchor": "heading or code-block index within that page, e.g. \"section:Control stacking order with ggplot2\""
      }
    }
  ],
  "gallery_links": ["one or more source URLs backing this entry"],
  "known_pitfalls": ["free text bullets, e.g. \"violin plots can look bimodal from KDE artifacts on small n\""],
  "source_site": "python-graph-gallery | r-graph-gallery | altair | seaborn | plotnine",
  "source_license": "string, e.g. \"MIT (repo-level, doc coverage unverified)\"",
  "last_verified": "ISO 8601 date this entry's source URL was last checked to still resolve",
  "last_crawled": "ISO 8601 date this entry was last (re)built from source"
}
```

One filled example per site:

```json
{
  "id": "violin-basic-seaborn",
  "family": "distribution",
  "chart_type": "violin plot",
  "data_shape": {
    "n_variables": 1,
    "variable_types": ["numeric", "categorical (optional group)"],
    "grouping": "single_group",
    "notes": "one numeric column, optionally one categorical grouping column, long format"
  },
  "when_to_use": "compare the full distribution shape (not just quartiles) of a numeric variable across a small number of groups",
  "when_not_to_use": "very small n per group, where the KDE can imply structure the data does not have; prefer a strip plot or boxplot instead",
  "library_implementations": [
    {
      "library": "seaborn",
      "function_or_geom": "sns.violinplot",
      "snippet_locator": {
        "source_url": "https://python-graph-gallery.com/50-basic-violinplot-and-input-formats/",
        "anchor": "section:One numerical variable only"
      }
    }
  ],
  "gallery_links": [
    "https://python-graph-gallery.com/violin-plot/",
    "https://python-graph-gallery.com/50-basic-violinplot-and-input-formats/"
  ],
  "known_pitfalls": ["KDE tails can extend past the data's actual range on small samples"],
  "source_site": "python-graph-gallery",
  "source_license": "0BSD in repo LICENSE, but copyright line reads Gatsby Inc.; likely a template artifact, doc-content coverage unverified",
  "last_verified": "2026-09-11",
  "last_crawled": "2026-09-11"
}
```

```json
{
  "id": "stacked-area-ggplot2",
  "family": "evolution",
  "chart_type": "stacked area chart",
  "data_shape": {
    "n_variables": 3,
    "variable_types": ["numeric (x, usually time)", "numeric (y, value)", "categorical (group)"],
    "grouping": "nested_group",
    "notes": "long format: one row per (x, group) pair with a y value"
  },
  "when_to_use": "show how a total and its composition by group change over time",
  "when_not_to_use": "more than ~5-6 groups (bands become unreadable) or when precise per-group comparison matters more than the total (use small multiples of line charts instead)",
  "library_implementations": [
    {
      "library": "ggplot2",
      "function_or_geom": "geom_area",
      "snippet_locator": {
        "source_url": "https://r-graph-gallery.com/136-stacked-area-chart.html",
        "anchor": "section:Stacked area with ggplot2"
      }
    }
  ],
  "gallery_links": [
    "https://r-graph-gallery.com/136-stacked-area-chart.html",
    "https://r-graph-gallery.com/all-graphs.html"
  ],
  "known_pitfalls": ["stacking order changes visual perception of individual group trends; must be controlled explicitly with factor()/sort()"],
  "source_site": "r-graph-gallery",
  "source_license": "MIT in repo LICENSE (2015-2017 Holtz Yan); doc-content coverage unverified",
  "last_verified": "2026-09-11",
  "last_crawled": "2026-09-11"
}
```

```json
{
  "id": "scatter-tooltips-altair",
  "family": "correlation",
  "chart_type": "interactive scatter plot with tooltips",
  "data_shape": {
    "n_variables": 4,
    "variable_types": ["numeric (x)", "numeric (y)", "categorical (color)", "extra fields for tooltip only"],
    "grouping": "single_group",
    "notes": "one row per observation, plus arbitrary extra columns exposed only via tooltip"
  },
  "when_to_use": "an exploratory correlation view meant for interactive/notebook consumption, where a reader needs per-point identity, not a static print figure",
  "when_not_to_use": "static print/paper figures (tooltips do not render) or large-N data where hover targets overlap",
  "library_implementations": [
    {
      "library": "altair",
      "function_or_geom": "mark_circle + encode(tooltip=[...])",
      "snippet_locator": {
        "source_url": "https://altair-viz.github.io/gallery/scatter_tooltips.html",
        "anchor": "code_block:1"
      }
    }
  ],
  "gallery_links": [
    "https://altair-viz.github.io/gallery/scatter_tooltips.html",
    "https://altair-viz.github.io/gallery/index.html"
  ],
  "known_pitfalls": ["interactivity is lost on export to static PNG/PDF; not suitable for the paper role without a static fallback rendering"],
  "source_site": "altair",
  "source_license": "BSD-3-Clause (vega/altair repo); doc-specific statement unverified",
  "last_verified": "2026-09-11",
  "last_crawled": "2026-09-11"
}
```

```json
{
  "id": "grouped-barplot-seaborn",
  "family": "ranking",
  "chart_type": "grouped bar plot with error bars",
  "data_shape": {
    "n_variables": 3,
    "variable_types": ["categorical (x)", "numeric (y)", "categorical (hue/subgroup)"],
    "grouping": "nested_group",
    "notes": "long format, one row per observation; catplot aggregates and draws error bars"
  },
  "when_to_use": "compare a numeric summary across a primary category and a secondary subgroup, with uncertainty shown",
  "when_not_to_use": "more than 2 nesting levels (bars become cluttered) or when exact values matter more than the visual ranking (use a table or dot plot instead)",
  "library_implementations": [
    {
      "library": "seaborn",
      "function_or_geom": "sns.catplot(kind=\"bar\")",
      "snippet_locator": {
        "source_url": "https://seaborn.pydata.org/examples/grouped_barplot.html",
        "anchor": "code_block:1"
      }
    }
  ],
  "gallery_links": [
    "https://seaborn.pydata.org/examples/grouped_barplot.html",
    "https://seaborn.pydata.org/examples/index.html"
  ],
  "known_pitfalls": ["default error bars are computed automatically (bootstrap CI or SD depending on version/args); must confirm which before quoting them in a caption"],
  "source_site": "seaborn",
  "source_license": "BSD-3-Clause (mwaskom/seaborn repo); doc-specific statement unverified",
  "last_verified": "2026-09-11",
  "last_crawled": "2026-09-11"
}
```

```json
{
  "id": "annotated-heatmap-plotnine",
  "family": "correlation",
  "chart_type": "annotated heatmap",
  "data_shape": {
    "n_variables": 3,
    "variable_types": ["categorical (x)", "categorical (y)", "numeric (fill/text)"],
    "grouping": "none",
    "notes": "wide-to-long or already-long matrix-style data, one row per (x, y) cell"
  },
  "when_to_use": "show a value at every combination of two categorical axes and also print the exact value on each cell",
  "when_not_to_use": "continuous x or y axes (use geom_tile/geom_raster without per-cell text instead), or more than a few dozen cells (text becomes unreadable)",
  "library_implementations": [
    {
      "library": "plotnine",
      "function_or_geom": "geom_tile + geom_text",
      "snippet_locator": {
        "source_url": "https://plotnine.org/gallery/annotated-heatmap.html",
        "anchor": "section:Read data"
      }
    }
  ],
  "gallery_links": [
    "https://plotnine.org/gallery/annotated-heatmap.html",
    "https://plotnine.org/gallery/"
  ],
  "known_pitfalls": ["text/fill color contrast must be managed manually (scale_color_manual) or annotations become unreadable on dark fill cells"],
  "source_site": "plotnine",
  "source_license": "MIT (has2k1/plotnine repo, 2022 Hassan Kibirige)",
  "last_verified": "2026-09-11",
  "last_crawled": "2026-09-11"
}
```

## Refresh cadence

- **Cadence.** Quarterly (every 3 months), aligned with the harness's evolve loop mentioned in
  BRIEF.md Section 13.1 ("It is refreshed through the evolve loop"). None of the five sites publish
  a changelog/RSS feed for gallery additions that was found during this research, so time-based
  polling is the only option; quarterly balances staleness against the low rate of new examples
  observed (plotnine's sitemap `lastmod` values were all clustered around 2026-09-01, suggesting
  batch updates rather than a continuous trickle; https://plotnine.org/sitemap.xml, 2026-09-11).
- **Trigger-based refresh, in addition to the calendar one.** Re-run the crawl immediately after a
  version bump of any of the five libraries (seaborn, altair/vega-altair, plotnine, ggplot2,
  matplotlib), since new example pages are usually added alongside new chart-supporting features.
- **Per-site method at refresh time.**
  - plotnine: refetch `sitemap.xml` and diff by `lastmod` and URL set; cheapest of the five.
  - python-graph-gallery / r-graph-gallery: refetch `/all-charts/` and `/all-graphs.html`
    respectively and diff the linked URL list (no sitemap available); treat new numbered slugs as
    new entries.
  - altair / seaborn: refetch `/gallery/index.html` and `/examples/index.html` respectively and
    diff the linked URL list.
- **Verification vs. re-crawl.** `last_verified` (cheap: HEAD/GET the stored `source_url`, confirm
  200) can run more often than `last_crawled` (expensive: re-parse structure and re-derive
  pitfalls/when-to-use text): verify monthly, fully re-crawl quarterly or on a version-bump
  trigger.
- **Politeness.** Since none of the five sites publish a `Disallow` rule and none showed rate
  limiting during this research, a refresh crawl should still self-limit (e.g. 1 request/second,
  a descriptive User-Agent, and the existing ten-pages-per-site-per-session discipline used for
  this ticket) rather than rely on the absence of robots rules as permission to crawl aggressively.
