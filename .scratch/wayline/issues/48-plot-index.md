# 48 - The plot index

**What to build:** The harness owns an index of chart types the figure role can choose from: built once by crawling the five sources through the fetch seam, holding metadata and locators only, seeded with library pitfalls regenerated from the owner's paper-figures skill, and refreshed monthly for liveness and quarterly or on a library version bump for content.

**Blocked by:** 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** ready-for-agent

**Milestone:** M7 Figures, docs, paper. **Spec:** Implementation Decisions 13 (plot index), 14 (`plot_index`); OPEN-18 (map ticket 34); research-notes 09 (sources, schema, cadence) and 11 Section 2 (the traps).

- [ ] `wayline figures build-index` fetches python-graph-gallery `/all-charts/`, r-graph-gallery `/all-graphs.html`, Altair `/gallery/index.html`, seaborn `/examples/index.html`, and plotnine `sitemap.xml` and their linked pages through the seam at one request per second with the descriptive User-Agent, and writes `figures/plot_index.json`.
- [ ] Every entry follows the schema of research-notes 09 (`id, family, chart_type, data_shape: {n_variables, variable_types[], grouping, notes}, when_to_use, when_not_to_use, library_implementations: [{library, function_or_geom, snippet_locator: {source_url, anchor}}], gallery_links[], known_pitfalls[], source_site, source_license, last_verified, last_crawled`) and holds no prose copied from the sites and no images.
- [ ] The matplotlib and TikZ `known_pitfalls` are seeded from the traps in Section 4 of the owner's `paper-figures` skill, rewritten per entry (not copied), per the classification table in research-notes 11 Section 2; `figures/structure_index.json` holds the layout structures for framework figures; `figures/style.default.json` holds the default color budget.
- [ ] `wayline figures refresh` runs the link-liveness check (HEAD or GET each `source_url`, updating `last_verified`) monthly and the full re-crawl quarterly or on a version bump of seaborn, altair, plotnine, ggplot2, or matplotlib, diffing the index page URL lists (plotnine by sitemap `lastmod`) and updating `last_crawled`; `traps_hit` entries with `promote_to_index: true` from figure results are folded into `known_pitfalls`.
- [ ] Tests build the index from recorded pages for all five sites; live: the index is built and its size and per-site counts are recorded in `docs/verification/m7.md`.
