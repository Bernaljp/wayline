# A paper written for the suite, and nothing arXiv served

The arXiv terms of use forbid re-serving an e-print, so **no real arXiv source is committed
here**, and none ever should be: `fixtures/fetch/` holds recorded API responses, but never a
`/src/` answer. What the inventory tests run on instead is a paper written for them.

| File | What it is | What it is for |
|---|---|---|
| `tiny-paper.tar.gz` | a three-file LaTeX paper with a `00README.json`, two `\input` sections, one numbered equation, one `align*`, one numbered `align`, a `figure` and a `figure*`, a table, an algorithm, a theorem, a lemma, an appendix, a bibliography, a PNG figure, and a PDF figure | the whole chain: unpack, main file, flatten, inventory, compile, rasterize |
| `no-latex.tar.gz` | a submission carrying a `00README.XXX`, a text file, and an image, and no `.tex` at all | the tarball that will not flatten, so the arXiv HTML rendering is the second source |
| `latexml.html` | a LaTeXML-shaped page with `ltx_section`, `ltx_figure`, `ltx_table`, `ltx_equation` and `ltx_theorem` blocks and a `<math alttext>` | the HTML fallback's parser |

The tiny paper compiles: with `pdflatex` installed the suite checks the exact numbers and pages
that come out of the `.aux`, and without it the same test is skipped and the document-order count
is what runs. `float` is the only package it needs beyond `graphicx` and `amsmath`.

## Remaking them

The two tarballs are generated, because a tarball cannot be read in a diff: `make.py` holds the
paper's sources as text, and

```sh
python3 fixtures/arxiv/make.py
```

rewrites both. Fixed mtimes, fixed ownership, and a gzip stream without a timestamp make the
bytes the same on every machine, so a rebuild that changes nothing shows as no diff. To change a
fixture, edit the sources in `make.py` and run it.

## The live counts

The live half of ticket 21 ran on arXiv `1706.03762` and is recorded in
`docs/verification/m3.md`. Its source was fetched into a project outside this repository and
deleted afterwards.
