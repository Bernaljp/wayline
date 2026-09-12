# 21 - arXiv e-print sources and the LaTeX inventory

**What to build:** For an arXiv paper the harness fetches the exact source, keeps it local and never republishes it, flattens it, and inventories sections, numbered equations as LaTeX, figures with captions and image files, tables, algorithms, theorems, and appendices, with exact numbers from a compile when the source compiles and a document-order fallback when it does not.

**Blocked by:** 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** done

**GitHub:** [#22](https://github.com/Bernaljp/wayline/issues/22) (mirror; the local file is the source)

**Milestone:** M3 Dossiers. **Spec:** Implementation Decisions 9 (arXiv sources, inventory); research-notes 06 Section 2.

- [x] The source is fetched from `https://export.arxiv.org/src/<id>[vN]` through the seam at one request per 3 s on one connection with an ETag cache that never expires, stored under `refs/<slug>/source/`; `init`'s `.gitignore` also excludes `research/refs/*/source/` so a pushed project never republishes an e-print (an addition this ticket makes to the spec's ignore list, for the arXiv terms of use); a PDF-only submission is routed to the PDF chain of ticket 22.
- [x] The main file comes from `00README` or the `\documentclass` grep (preferring the file that inputs the others); `latexpand main.tex > flat.tex` flattens; comments are stripped; `equation`, `align`, `figure`, `table`, `algorithm`, `theorem` and its kin, `\label`, `\caption`, `\ref`, `\eqref`, and `\section` are inventoried by regex.
- [x] Exact equation and figure numbers and pages come from the `.aux` `\newlabel` lines after one `pdflatex` run when the source compiles; otherwise numbered environments are counted in document order honoring `\nonumber` and `\tag`; figures resolve `\includegraphics` targets against the tarball and PDF figures are rasterized with `pdftoppm`.
- [x] `https://arxiv.org/html/<id>` is the second source when the tarball will not flatten, with the MathML `alttext` as the LaTeX.
- [x] `refs/<slug>/inventory.json` validates against the `inventory` schema with per-field `provenance` (`latex`, `aux`, `html`) and page and locator per item.
- [x] Tests run on a small committed tarball fixture; live on 1706.03762 the counts match research-notes 06 (3 `equation`, 2 `align*`, 5 figures, 4 tables, 13 labels, 9 captions, 23 section headings, 0 unresolved inputs).

## How it was verified

`python -m unittest` from the repository root: 942 tests, all passing, of which `tests/test_inventory.py` is this ticket's 73. They run on `fixtures/arxiv/tiny-paper.tar.gz`, a paper written for the suite, because the arXiv terms of use forbid re-serving an e-print and no real source is committed anywhere in this repository. The two tests that need `pdflatex` and the one that needs `pdftoppm` skip themselves where the tools are absent, which is what CI does; `latexpand` has a test of its own and an in-house expander stands in for it.

The live run is recorded in `docs/verification/m3.md`: `1706.03762` fetched from the live `export.arxiv.org` into a project outside the repository, one request, 4.6 s for the whole chain, and all eight of the last criterion's counts matching. The e-print was deleted afterwards. A second pass offered `If-None-Match`, took the 304, and re-inventoried the kept source to the same counts without moving a byte.

Two failure modes the live paper found are written up in that record: a `\label` after a `\section*` reads as the previous section's number in the `.aux`, so the compile now settles only numbers the count already gave; and the Attention paper labels no equation, so its equation numbers are counted rather than exact, which is why `provenance` is per field rather than per record.
