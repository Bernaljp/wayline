# A PDF written for the suite, and what the tools made of it

No paper anyone published is committed here, and none should be: the M3 criterion runs the chain
on a paper from the owner's field once, live, and `docs/verification/m3.md` records the counts.
What the tests run on instead is a paper written for them.

| File | What it is | What it is for |
|---|---|---|
| `tiny-paper.pdf` | two pages, two columns, built by `make.py` with `pdflatex` | the PDF every chain test inventories |
| `tiny-paper.tex` | the source `make.py` compiled, kept so the fixture reads in a diff | reading, not building |
| `recorded/` | what poppler 24.02, pdfplumber 0.11.10, and docling 2.126.0 (formula enrichment on the GPU) printed or wrote for `tiny-paper.pdf` | `recorded_runner` replays it, so the chain runs on a machine with none of the tools |
| `samples/marker.json` | a marker JSON rendering, written to the shape marker's README documents | the marker adapter; marker 2.0 needs a vLLM server this box did not have |
| `samples/mineru_content_list.json` | a MinerU `content_list`, written to its documented shape | the MinerU adapter; not installed here |
| `samples/grobid.tei.xml` | a GROBID TEI document with a header and two `biblStruct` references | the GROBID reader; Docker was not reachable by this user |

## What a reader counts in `tiny-paper.pdf`

| Item | Count | Where |
|---|---|---|
| Pages | 2 | |
| Headings | 8 | the title, Abstract, 1 Introduction, 1.1 Scope, 2 Method, 3 Results, A Proof of the lemma, References |
| Numbered sections | 4 | 1, 1.1, 2, 3 |
| Appendices | 1 | A |
| Display equations | 3 | (1); one unnumbered; one aligned pair numbered (2) and (3) |
| Figures | 2 | Figure 1 in the right column of page 1; Figure 2 spanning both columns of page 2 |
| Tables | 1 | Table 1, ruled at the top, under the header, and at the bottom only |
| Algorithms | 1 | Algorithm 1 |
| Theorem-like blocks | 2 | Theorem 1 (Tininess), Lemma 1 |
| References | 2 | Knuth, Lamport |
| Embedded images | 2 | one per figure |

docling's reading of it, in `recorded/docling/`, shows four of the failure modes the M3 record
names: the numbers of the aligned pair are split off the display, and "(3)" is glued to the
paragraph that starts the next column; Figure 1's caption is found but not linked to its picture;
the theorem and its proof are one text item; and the algorithm is labeled `code`. pdfplumber finds
the ruled table but returns its three data rows as one row, because no rule separates them.

## Remaking them

```sh
python3 fixtures/pdf/make.py            # the PDF, byte for byte the same on the same TeX Live
python3 fixtures/pdf/make.py --record   # and recorded/, from the tools this machine has
```

`--record` uses the tools venv of `wayline tools install`; a tool that is not installed is not
recorded, and the tests that replay it expect it to be there, so record on a machine with docling.
