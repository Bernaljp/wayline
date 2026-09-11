# 52 - Venue guidelines

**What to build:** The harness holds, per venue, the machine-readable guidelines a writer needs (length limits, required structure, figure specifications, reference style, reporting checklists, submission steps, the template's availability) with the source URL and the date checked, for the fifteen venues of the brief plus bioRxiv and arXiv, and seven mechanical checks a writer can run off that file alone.

**Blocked by:** 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** ready-for-agent

**Milestone:** M7 Figures, docs, paper. **Spec:** Implementation Decisions 13 (guidelines); OPEN-19 (map ticket 35); research-notes 10 (the URLs, the per-venue findings, the layout, the seven checks).

- [ ] `wayline guidelines build` fetches each venue's guidelines URL recorded in research-notes 10 through the seam and writes `guidelines/<venue>/guidelines.json` (schema `guidelines`: `venue, display_name, guidelines_url, date_checked, length_limits, required_structure[], structure_flexible, figure_spec, reference_style, reporting_checklists[], submission_steps[], template, license_of_summary_source, verification: {fully_verified_fields[], unverified_fields[]}`), `source.md` (what was fetched, what is unverified, caveats), and `checklist/` with cached reporting-checklist forms only; manuscript templates are linked, never stored.
- [ ] Cell and Genome Biology are retried at build time with the alternate paths the research note suggests, and any field still unreachable is listed under `unverified_fields`.
- [ ] The seven mechanical writer checks run off `guidelines.json` alone on a manuscript directory (Markdown or LaTeX): word or page count with the venue's exclusions; section presence (a warning where `structure_flexible`); figure count, format, DPI, color mode, size, and legend length; reference style and count; reporting-checklist presence by detected study type; template or document-class conformance; and the provenance cross-check shared with the linter's sentence pass.
- [ ] Tests build the seventeen entries from recorded pages and run the checks on a sample manuscript against two venues; live: the build runs and the per-venue verification status is recorded in `docs/verification/m7.md`.
