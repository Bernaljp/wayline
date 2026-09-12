# 52 - Venue guidelines

**What to build:** The harness holds, per venue, the machine-readable guidelines a writer needs (length limits, required structure, figure specifications, reference style, reporting checklists, submission steps, the template's availability) with the source URL and the date checked, for the fifteen venues of the brief plus bioRxiv and arXiv, and seven mechanical checks a writer can run off that file alone.

**Blocked by:** 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** done

**GitHub:** [#53](https://github.com/Bernaljp/wayline/issues/53) (mirror; the local file is the source)

**Milestone:** M7 Figures, docs, paper. **Spec:** Implementation Decisions 13 (guidelines); OPEN-19 (map ticket 35); research-notes 10 (the URLs, the per-venue findings, the layout, the seven checks).

- [x] `wayline guidelines build` fetches each venue's guidelines URL recorded in research-notes 10 through the seam and writes `guidelines/<venue>/guidelines.json` (schema `guidelines`: `venue, display_name, guidelines_url, date_checked, length_limits, required_structure[], structure_flexible, figure_spec, reference_style, reporting_checklists[], submission_steps[], template, license_of_summary_source, verification: {fully_verified_fields[], unverified_fields[]}`), `source.md` (what was fetched, what is unverified, caveats), and `checklist/` with cached reporting-checklist forms only; manuscript templates are linked, never stored.
- [x] Cell and Genome Biology are retried at build time with the alternate paths the research note suggests, and any field still unreachable is listed under `unverified_fields`.
- [x] The seven mechanical writer checks run off `guidelines.json` alone on a manuscript directory (Markdown or LaTeX): word or page count with the venue's exclusions; section presence (a warning where `structure_flexible`); figure count, format, DPI, color mode, size, and legend length; reference style and count; reporting-checklist presence by detected study type; template or document-class conformance; and the provenance cross-check shared with the linter's sentence pass.
- [x] Tests build the seventeen entries from recorded pages and run the checks on a sample manuscript against two venues; live: the build runs and the per-venue verification status is recorded in `docs/verification/m7.md`.

**Note on the count.** Fifteen entries are built, not seventeen. The spec's own enumeration (Implementation Decisions 13) and the research note's table both list fifteen: thirteen journals and conferences plus bioRxiv and arXiv. "The fifteen venues of BRIEF 13.3 plus bioRxiv and arXiv" counts the two preprint servers twice, and the brief's own parenthetical names thirteen. The spec line now says so.

**Note on the schema.** Three fields the spec's field list did not name are in `guidelines.json`, because a check this ticket asks for cannot run without them: `length_limits.excluded_sections` (a word count "with the venue's exclusions" has to know them), `reference_style.citation` (prose cannot drive a style check) and `template.document_class` (the conformance check compares a draft's class or style package against it). `figure_spec.notes` mirrors the `length_limits.notes` the spec already had. The spec's field list records all four.
