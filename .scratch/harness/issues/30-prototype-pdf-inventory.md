# 30 — Prototype: inventory one non-arXiv PDF and one arXiv source

Type: prototype
Status: resolved
Blocked by: 06 (Dossier inventory for non-arXiv PDFs and keyless literature APIs)
Blocks: 31 (OPEN-16 Reading budgets)
Brief: Section 7.3, M3; fog: the dossier inventory for non-arXiv PDFs

## Question

How much of the inventory does the recommended tool chain produce mechanically? Run the chain from the research note on one non-arXiv PDF from the owner's field and on one arXiv e-print source tarball. Produce `inventory.json` for each (sections, numbered equations, figures with captions and image files, tables, algorithms, theorems, appendices). Count what was found against a by-eye count on the first ten pages, and list the failure modes (equations as images, multi-column confusion, caption splitting).

The answer is the inventory schema fields that are reliable per source type and the model pass that fills the rest. Keep it under `.scratch/proto/pdf-inventory/`; do not commit the PDF.

## Answer

Closed 2026-09-11 by the owner's scoping decision: not built as a throwaway. Its Question becomes the first acceptance criterion of tracer bullet M3 Dossiers (BRIEF.md Section 16), which builds the real version; to-tickets must carry it there verbatim.
