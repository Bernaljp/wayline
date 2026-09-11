# 09 — Plot index sources: crawlability and licensing

Type: research
Status: resolved
Blocked by: None
Brief: Section 13.1, OPEN-18

## Question

For python-graph-gallery.com, r-graph-gallery.com, the Altair documentation, the seaborn example gallery, and the plotnine gallery:

1. Sitemaps or index pages listing every chart page; page structure (chart family, chart type, code, data shape, pitfalls); approximate page counts.
2. `robots.txt` and license terms for storing a derived catalog locally (not the content itself).
3. Whether the firecrawl CLI plugin (available in interactive sessions) or plain standard-library fetching is adequate for a one-time build and periodic refresh.

Propose the `plot_index.json` entry schema (family, type, data shape it needs, when to use, when not, library implementations with snippet locators, gallery links, known pitfalls) and a refresh cadence.

Deliverable: `research-notes/09-plot-index-sources.md`.

## Answer

- Only plotnine.org has a real `robots.txt` (permissive) and a real `sitemap.xml` (500+ URLs).
- The other four (python-graph-gallery.com, r-graph-gallery.com, altair-viz.github.io,
  seaborn.pydata.org) have no `robots.txt` and no sitemap (all 404); a manual index page stands
  in for each: `/all-charts/`, `/all-graphs.html`, `/gallery/index.html`, `/examples/index.html`.
- Approximate page counts: 100-150+ (python), 150+ (R), 150+ over 13 categories (Altair), about
  50 (seaborn), 34 tagged gallery examples out of 500+ total sitemap URLs (plotnine).
- No `robots.txt` means nothing is disallowed on any of the five.
- Licensing: the two Holtz galleries carry repo-level licenses (0BSD with a stray "Gatsby Inc."
  copyright line for Python, MIT for R) whose coverage of the tutorial prose is unverified.
  Altair/seaborn/plotnine are BSD-3-Clause/BSD-3-Clause/MIT with gallery pages generated from the
  same repo, so those three are the safer bet. A metadata-only catalog (URLs, family/type,
  structure) is referential either way, not a copy of copyrightable prose.
- The `firecrawl` CLI plugin is installed here but was not needed: every page used was static
  HTML, so plain `WebFetch`/stdlib HTTP suffices for both the one-time build and refreshes;
  firecrawl's `firecrawl-map` is only a convenience for interactive rebuilds.
- Proposed cadence: quarterly full re-crawl, plus an immediate re-crawl on any version bump of
  the five libraries, with a cheaper monthly URL-liveness check in between.

Full findings, per-site citations, and the proposed `plot_index.json` schema with one filled
example per site: `research-notes/09-plot-index-sources.md`.
