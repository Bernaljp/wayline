# 22 - Non-arXiv PDF inventory chain and the tools venv (verbatim prototype 30)

**What to build:** For a PDF without source the harness builds the same inventory mechanically as far as the tools allow (text layer, page count, images, sections, figures with captions as files, tables, references) and marks every field a reader must confirm (equation LaTeX and numbers, algorithm and theorem boundaries, figure meaning). The converters live in an optional tools venv the owner installs once; without them the always-on poppler layer still works. The first criterion is the closed prototype ticket's Question, carried verbatim; the real dossier module stands in for the throwaway chain.

**Blocked by:** 21 (arXiv e-print sources and the LaTeX inventory)

**Status:** done

**GitHub:** [#23](https://github.com/Bernaljp/wayline/issues/23) (mirror; the local file is the source)

**Milestone:** M3 Dossiers. **Spec:** milestone M3 criteria 1 and 4; Implementation Decisions 9 (non-arXiv PDFs, inventory); research-notes 06 Section 1 and the comparison table.

- [x] Carried verbatim from the closed prototype ticket 30 (Prototype: inventory one non-arXiv PDF and one arXiv source):

  > How much of the inventory does the recommended tool chain produce mechanically? Run the chain from the research note on one non-arXiv PDF from the owner's field and on one arXiv e-print source tarball. Produce `inventory.json` for each (sections, numbered equations, figures with captions and image files, tables, algorithms, theorems, appendices). Count what was found against a by-eye count on the first ten pages, and list the failure modes (equations as images, multi-column confusion, caption splitting).
  >
  > The answer is the inventory schema fields that are reliable per source type and the model pass that fills the rest. Keep it under `.scratch/proto/pdf-inventory/`; do not commit the PDF.

  The real dossier module stands in for the throwaway chain; the counts, the failure modes, and the reliable-versus-reader-pass split per source type go to `docs/verification/m3.md`, and the PDF stays out of git.
- [x] The always-on layer runs `pdftotext -layout`, `pdfinfo`, `pdfimages -list`, and pdfplumber (from the tools venv, or skipped with a note when absent) for `text_layer`, `page_count`, `raw_images[]`, word and character boxes, and ruled tables.
- [ ] `wayline tools install` creates `~/.wayline/tools/` with docling by default and marker or MinerU on request, records versions, and the harness only ever calls them as subprocesses; docling is the primary structural converter (typed items with page and bbox, figures and tables to PNG, formula enrichment on the GPU); marker then MinerU are fallbacks when docling fails on a document; GROBID (Docker, optional) fills `references[]` and `metadata`; a missing tool records `converter: none` for its fields.
- [x] Every model-derived field carries `provenance: "<tool>-<version>"` with page and bbox; equation LaTeX from a converter is marked OCR-derived; equation numbers are regex-recovered from adjacent `(N)`; algorithms and theorems are found by the heading regex with boundaries left to a reader; appendices by the header regex.
- [x] Tests run on a small committed PDF with recorded docling JSON and on the poppler layer alone; the live criterion above runs on one PDF from the owner's field and the arXiv tarball of ticket 21.
