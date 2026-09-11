# 10 — Venue guidelines sources

Type: research
Status: resolved
Blocked by: None
Brief: Section 13.3, OPEN-19

## Question

For Nature, Nature Methods, Nature Communications, Cell, Cell Systems, PNAS, PLOS Computational Biology, eLife, Bioinformatics, Genome Biology, NeurIPS, ICML, ICLR, bioRxiv, and arXiv:

1. The URL of the current author guidelines and the fields extractable from them: length limits, required structure, figure specifications, reference style, reporting checklists, submission steps.
2. Whether a LaTeX or Word template is downloadable without login.
3. License terms for storing an extracted summary with the source URL and the date checked.

Propose the `guidelines/<venue>/` file layout and the checks the writer can run mechanically (word counts, section presence, figure count, reference format).

Deliverable: `research-notes/10-venue-guidelines-sources.md`.

## Answer

All 15 venues checked 2026-09-11; findings in `research-notes/10-venue-guidelines-sources.md`.
13 of 15 guidelines pages were fetched directly and cited per field. Two had partial failures:
Cell (cell.com returned HTTP 403 to a stateless fetch, so its fields are sourced from search
snippets of the live page, flagged as such) and Genome Biology (the submission-guidelines page
redirects to a Springer login gate; most fields marked unverified, with a suggested retry path).
Nine venues (Nature Communications, Cell Systems, PNAS, eLife, NeurIPS, ICML, ICLR, and generic
Springer Nature) have a LaTeX or Word template downloadable without login; Nature Methods, PLOS
CompBio, Bioinformatics, Genome Biology, bioRxiv, and arXiv do not (or it is unverified). The
note proposes a `guidelines/<venue>/` layout (`guidelines.json` + `source.md` + a `checklist/`
subfolder for reporting-checklist forms only, not manuscript templates) and seven mechanical
checks the writer can run off `guidelines.json` alone: word/page count, section presence, figure
count/format/DPI/color-mode/size, legend length, reference style/count, reporting-checklist
presence by study type, and template/document-class conformance.

See `research-notes/10-venue-guidelines-sources.md`.
