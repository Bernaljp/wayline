# 34 — OPEN-18 Plot index sources and refresh

Type: grilling
Status: resolved
Blocked by: 09 (Plot index sources: crawlability and licensing)
Brief: OPEN-18, Section 13.1

## Question

The two galleries and Altair as seeds (given); add seaborn and plotnine (default: yes); refresh cadence (default: on demand through the evolve loop, at most quarterly). Confirm against the research note's licensing findings, and fix the entry schema it proposed.

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

Seeds: python-graph-gallery, r-graph-gallery, Altair, plus seaborn and plotnine. The catalog stores metadata and locators only (no prose), because the Holtz galleries' license coverage of prose is unverified. Plain stdlib fetching. Refresh quarterly and on a library version bump, with a monthly link-liveness check. Entry schema as proposed in research-notes/09-plot-index-sources.md.
