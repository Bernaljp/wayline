# 21 - arXiv e-print sources and the LaTeX inventory

**What to build:** For an arXiv paper the harness fetches the exact source, keeps it local and never republishes it, flattens it, and inventories sections, numbered equations as LaTeX, figures with captions and image files, tables, algorithms, theorems, and appendices, with exact numbers from a compile when the source compiles and a document-order fallback when it does not.

**Blocked by:** 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** ready-for-agent

**GitHub:** [#22](https://github.com/Bernaljp/wayline/issues/22) (mirror; the local file is the source)

**Milestone:** M3 Dossiers. **Spec:** Implementation Decisions 9 (arXiv sources, inventory); research-notes 06 Section 2.

- [ ] The source is fetched from `https://export.arxiv.org/src/<id>[vN]` through the seam at one request per 3 s on one connection with an ETag cache that never expires, stored under `refs/<slug>/source/`; `init`'s `.gitignore` also excludes `research/refs/*/source/` so a pushed project never republishes an e-print (an addition this ticket makes to the spec's ignore list, for the arXiv terms of use); a PDF-only submission is routed to the PDF chain of ticket 22.
- [ ] The main file comes from `00README` or the `\documentclass` grep (preferring the file that inputs the others); `latexpand main.tex > flat.tex` flattens; comments are stripped; `equation`, `align`, `figure`, `table`, `algorithm`, `theorem` and its kin, `\label`, `\caption`, `\ref`, `\eqref`, and `\section` are inventoried by regex.
- [ ] Exact equation and figure numbers and pages come from the `.aux` `\newlabel` lines after one `pdflatex` run when the source compiles; otherwise numbered environments are counted in document order honoring `\nonumber` and `\tag`; figures resolve `\includegraphics` targets against the tarball and PDF figures are rasterized with `pdftoppm`.
- [ ] `https://arxiv.org/html/<id>` is the second source when the tarball will not flatten, with the MathML `alttext` as the LaTeX.
- [ ] `refs/<slug>/inventory.json` validates against the `inventory` schema with per-field `provenance` (`latex`, `aux`, `html`) and page and locator per item.
- [ ] Tests run on a small committed tarball fixture; live on 1706.03762 the counts match research-notes 06 (3 `equation`, 2 `align*`, 5 figures, 4 tables, 13 labels, 9 captions, 23 section headings, 0 unresolved inputs).
