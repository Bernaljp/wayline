# A project that starts midway, invented for the suite

A synthetic project that arrives with its own documents and code, the way a real one does when
the work started before wayline. Everything here is invented (the lantern moths, Ines Varga,
the references); nothing comes from any real project. Tickets that handle a project's own
documents and code (84, 85, 93, 96) test against these materials.

| File | What it is | What it exercises |
|---|---|---|
| `manuscript-v2.docx` | the earlier manuscript, newest version | tracked insertions and deletions (`w:ins`, `w:del`); a resolved comment thread with a reply and two open comments (`comments.xml`, `commentsExtended.xml` `w15:done`); two Mendeley Cite citation fields (`ADDIN MENDELEY_CITATION_V3`); an equation (`m:oMath`); a title, an abstract, a caption, a reference list; headings Introduction, Results, Discussion, Methods, plus Acknowledgements and References that map to none of them |
| `manuscript-v1.docx` | the same manuscript's older version (earlier zip timestamps, no dusk edits) | choosing the newest version in its source format |
| `methods.tex` | a separate Methods in LaTeX | a stated parameter that disagrees with the code: a window of 256 samples, where the code uses 512 |
| `supplement.pdf` | a supplement with no source beside it | a document known only as PDF |
| `measurements.xlsx` | a workbook with two sheets, Colonies and Lighting | spreadsheets with more than one sheet |
| `critiques/referee-1.md` | a referee report: one praise paragraph, five numbered points, point 2 has two parts (a) and (b) | splitting a critique into concerns |
| `critiques/referee-2.md` | a second, shorter critique | its point 1 (lamp flicker) is near-identical to referee 1's point 4 |
| `build_code.py` | builds the code repository into a directory you name: three commits, `phaselock.py` and `phaselock.m` | absorbing code with history: both files develop the order-parameter method, call a used method (`hilbert`), and set a non-default parameter (`window=512`) |
| `make.py` | regenerates the four binary files above, byte for byte | keeping the binaries reviewable as text |

Inside the manuscript text:

- a claim repeated across two sections in different words: "synchrony rises with colony size"
  (Discussion, and the abstract) and "larger colonies beat more nearly in phase" (Results);
- a contradicting pair: the abstract's "it peaks at dusk" against the Results' "the order
  parameter is lowest at dusk";
- the missing-material case: the Results report R = 0.71 from the dusk sweep of 2021, kept in
  `data/dusk-sweep-2021.csv`, and that file is absent on purpose.

`tests/test_midway_fixture.py` opens every file with the standard library and `git` and checks
these markers, so a broken fixture fails the suite. After editing `make.py`, rerun
`python3 fixtures/midway/make.py`.
