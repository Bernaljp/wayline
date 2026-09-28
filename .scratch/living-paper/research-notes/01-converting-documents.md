# 01 - Converting documents both ways with the tools on this machine

## Answer

**In: a project's own documents into text the harness can use.** Measured on copies of thirteen PINF_Project files (counts and structure only below).

- **`.docx`: pandoc 3.11, installed from the official release tarball, is the route.** It gets more of these files right than any other converter here, in 0.02 to 0.9 s a file:
  - headings from paragraph styles;
  - every equation as LaTeX: 447 of 447 compile, and accents, fractions, radicals, sums, and matrices count back to the source's OMML one for one;
  - tracked changes in all three modes, `--track-changes=accept|reject|all`, the last with author and date on each change;
  - comments as spans around their anchor text;
  - tables, footnotes, and images (`--extract-media`).

  It has two gaps. It keeps no comment anchored inside an equation: 6 of the 49 comments in the three commented files are lost. It also does not read Mendeley Cite citations, which Word stores as content controls rather than the field codes pandoc parses, so the manuscript's 41 citations arrive as bare superscript numbers.
- **Beside pandoc, a small standard-library reader in the harness covers both gaps** and needs no install:
  - it decodes each Mendeley Cite control into the CSL-JSON of the works cited: the manuscript cites 56 works, 33 of them with a DOI the scout can resolve directly;
  - it reads comment threads (reply-to and done, from `commentsExtended.xml`) with every anchor;
  - it counts what a converter should have produced, so a converter's output can be checked.

  A 480-line prototype matched pandoc on these files, so it is also the fallback when pandoc is absent. The measured caveat: an OMML-to-LaTeX converter the harness owns is where errors creep in. The prototype printed 5 of 119 accents as the wrong accent, and pandoc printed all 119 right.
- **docling** (already in the tools venv) reads `.docx` but adds nothing pandoc lacks:
  - it gives only the accepted text, with no option;
  - it writes multi-line equations as rows with no environment;
  - it drops 5 accents;
  - it links comments only to whole paragraphs, and only in its JSON;
  - it takes 4 to 9 s a file.
- **LibreOffice is not a text route for `.docx`.**
  - Its text export keeps the inserted and the deleted text together with no markers, and drops every equation and comment.
  - Its HTML export turns each equation into a GIF.
  - It is useful for two things. Through UNO it accepts or rejects every change (339 changes to 0 in about 2 s). It also turns a legacy `.doc`, which pandoc refuses, into a `.docx`.
- **PDF: prefer the `.docx` whenever one exists.** A PDF is the lossy copy.
  - For material that exists only as PDF, such as the second reviewer's attachment, `pdftotext -layout` gives all of the text, with no structure, in under 0.1 s. One regular expression removes a manuscript's margin line numbers; after it, pdftotext recovered 219 of 219 text probes.
  - docling adds structure when it is needed: headings, lists, captions, and display equations as LaTeX with GPU formula enrichment. On the 61-page compiled PDF it wrote 104 display equations, 79 of which compile unmodified. It takes 12 s for 23 pages and 97 s for 61.
  - Inline math stays as Unicode letters in both. LibreOffice cannot turn a PDF into text.
- **`.xlsx`: the standard library.** It writes one CSV per sheet with the cached value of every formula, in 0.05 s.
  - Every route kept every cell.
  - pandoc 3.11 also reads `.xlsx`, with one heading and one table per sheet.
  - docling's Markdown loses the sheet names and splits 14 sheets into 35 tables.

**Out: Markdown section files into a paper.**

- **Install pandoc 3.11 from the release tarball** into `~/.wayline/tools/`, through `wayline tools install`.
  - It is a 35 MB download that unpacks to 157 MB: one statically linked binary, with no root and no venv.
  - The download is checked against the sha256 digest GitHub publishes for the asset.
  - Do not use the `pypandoc_binary` wheel. It is the same size, needs a venv whose Python module the harness would never import, and bundles pandoc 3.9. That version predates the floating tables that two-column venues need.
- **One pandoc serves all three outputs.** Section files with `$...$` and `$$...$$` math, `[@key]` citations, and a BibTeX file compile to:
  - a PDF through `--pdf-engine=xelatex` (2.2 s);
  - a `.docx` whose equations are native Word equations (0.09 s);
  - body-only LaTeX with `--natbib` or `--biblatex` that a venue's class takes. This was compiled in `elsarticle`, in `IEEEtran` (with the two-column filter below), and in the NeurIPS 2026 style under `pdflatex`.

  Citations render through citeproc and a CSL style for the PDF and the `.docx`, and through BibTeX or biber for the venue's LaTeX.
- **Provenance tags pass through as literal text unless something handles them.**
  - A 50-line Lua filter turns each tag into a footnote for a review build, or strips it for a venue build.
  - The harness's own `render_citations` can instead pre-render tags as Markdown footnotes. The risk: when a section already has a footnote with the same number, pandoc silently prints that footnote's text in the tag's place.
  - Footnote markers look exactly like numeric superscript citations.
- **What breaks, and the fix for each.**
  - A Unicode symbol in prose. pdflatex stops, and xelatex's default font drops the symbol silently. Fix: write it as math, or set a font that has it.
  - A raw `\begin{equation}` and its `\ref` vanish from the `.docx`. Fix: `$$...$$ {#eq:id}` with pandoc-crossref, a 7.5 MB release built for pandoc 3.11, which also resolves `@fig:` references.
  - `longtable` fails in a two-column class. Fix: the four-line Lua filter printed in the pandoc manual.
  - Structured authors print as "true" in the default template. Fix: a plain author list or a template.
- **LibreOffice is no PDF fallback for math.** Its PDF of pandoc's `.docx` garbles multi-line equations, and its PDF of pandoc's HTML prints the MathML as linear text followed by the TeX source.

**Every level of autonomy.**

- Conversion is code, so it runs the same under `interactive`, `checkpoints`, and `autonomous` and spends no model tokens. What it changes is how much a model reads:
  - the Methods is about 119 KB as pandoc Markdown and 86 KB as the standard-library reader's Markdown;
  - the workbook is 48 KB as CSV and 174 KB as pandoc's tables.
- Installing pandoc is the one step autonomy bounds. The map lets the harness ask for and install software outside autonomous runs, so `wayline tools install` should fetch pandoc before a run.
- An autonomous run that finds pandoc missing can still read `.docx` with the standard-library reader. It has no route from section files to a paper until the owner installs pandoc.

## How this was measured

- **Tickets.** [Bernaljp/wayline #177](https://github.com/Bernaljp/wayline/issues/177), a research ticket of the map [#173](https://github.com/Bernaljp/wayline/issues/173).
- **When and where.** 2026-09-28, on this machine: Linux 6.8, 128 cores, one RTX 3090, Python 3.12.3.
- **Copies, not originals.**
  - Every conversion ran on copies of the PINF files in the scratch directory `/home/bernaljp/.claude/jobs/2a81684c/tmp/research-converting/in/`, outside both the repository and `~/Documents/PINF_Project`.
  - The copies came from `00_compiled/`, `01_manuscript/`, `02_methods/`, `04_supplementary/`, and `06_reviews/`.
  - The scripts named below sit beside the copies. That directory is job scratch and may not survive; the two Lua filters are reproduced in full in this note.
- **Tools.**

| Tool | Version | How it got here |
|---|---|---|
| pandoc | 3.11, released 2026-08-28 | release tarball, unpacked in scratch |
| pandoc (in `pypandoc_binary` 1.17, 2026-03-14) | 3.9 | wheel, in a scratch venv made with `uv` 0.11.29 |
| pandoc-crossref | v0.3.25a, built with pandoc 3.11 | release tarball, unpacked in scratch |
| docling | 2.126.0 (docling-core 2.96.0, torch 2.14.0+cu126) | the harness's tools venv, `~/.wayline/tools/venv` (7.0 GB) |
| LibreOffice | 24.2.7.2, with `python3-uno` | system |
| pdftotext | poppler-utils 24.02.0 | system |
| TeX Live | 2023 (Debian): XeTeX 0.999995, LuaHBTeX 1.17.0, latexmk 4.83, biber 2.19 | system |

- **The ground truth** is `docx_probe.py`. It reads each `.docx` with `zipfile` and `xml.etree.ElementTree`: `document.xml`, `styles.xml`, `comments.xml`, `commentsExtended.xml`, and the footnotes. It uses no converter.
- **Scoring.**
  - **Text probes.** For every paragraph with at least 90 letters and digits, three 30-character windows (start, middle, end) are taken from its lowercased letters and digits. A probe counts as found if it appears in a route's output after the same normalization, done after pandoc's attribute blocks and docling's HTML entities are removed.
  - **Tracked changes.** A diagnostic segment is a `w:ins` whose text has at least 20 letters and digits and does not occur in the rejected text, or a `w:del` whose text does not occur in the accepted text. The manuscript has 35 inserted and 27 deleted diagnostic segments.
    - A route that accepts shows 35/35 and 0/27.
    - A route that rejects shows 0/35 and 27/27.
    - A route that keeps both shows 35/35 and 27/27.
  - **Equations.**
    - *Compile:* each equation is compiled on its own by xelatex with `amsmath`, `amssymb`, and `unicode-math`, 48 at a time.
    - *Fidelity against the source:* the counts of `m:f`, `m:rad`, `m:nary`, `m:acc`, and `m:m` are compared with the matching LaTeX commands. A second check asks whether each OMML equation's letters and digits (Greek as names) appear, in order, in some equation the route wrote.
- **Commands.**

```
# pandoc (IN)
pandoc -f docx+citations -t markdown --wrap=none --track-changes=accept|reject|all --extract-media=DIR IN.docx -o OUT.md
pandoc -f docx+citations -t json --track-changes=all IN.docx -o OUT.json      # for counting
pandoc -f xlsx -t markdown --wrap=none IN.xlsx -o OUT.md
# standard library (IN): scratch prototypes
python3 docx_to_md.py IN.docx accept|reject|marked OUT.md                      # + OUT.comments.json, OUT.citations.json
python3 xlsx_probe.py IN.xlsx OUTDIR                                           # one CSV per sheet
# docling (IN): DocumentConverter defaults; for a PDF, do_formula_enrichment as converters/docling_convert.py sets it
~/.wayline/tools/venv/bin/python docling_any.py IN OUTDIR [--formulas]
# LibreOffice (IN)
soffice -env:UserInstallation=file://SCRATCH/lo-profile --headless --norestore --convert-to "txt:Text (encoded):UTF8" --outdir OUT IN.docx
soffice ... --convert-to html --outdir OUT IN.docx
soffice ... --convert-to 'csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,false,false,false,-1' --outdir OUT IN.xlsx
soffice ... --infilter=writer_pdf_import --convert-to "txt:Text (encoded):UTF8" --outdir OUT IN.pdf
python3 lo_accept.py IN.docx OUTDIR accept|reject      # UNO: .uno:AcceptAllTrackedChanges or .uno:RejectAllTrackedChanges, then store
# pdftotext (IN)
pdftotext -layout IN.pdf OUT.txt ; pdftotext IN.pdf OUT.txt
sed -E 's/^\s*[0-9]{1,4}\s{2,}//' OUT.txt              # strips margin line numbers from -layout output
```

## The documents (counts only)

| File | Paragraphs | Headings by style | Tracked changes | Comments | OMML equations | Tables | Images | Citations |
|---|---|---|---|---|---|---|---|---|
| Manuscript v17 with changes | 166 | 11 (7 level 1, 4 level 2) | 189 `w:ins` (4,279 characters), 102 `w:del` (5,373 characters), 29 paragraph marks, 171 formatting changes, 1 author | 0 | 12 inline | 0 | 0 | 41 Mendeley Cite controls, 69 cited items, 56 works |
| Methods V11 | 908 | 59 (14, 19, 25, and a table-of-contents heading; 10 of the 58 numbered-level headings are empty) | 1 insertion and 1 deletion, both inside one equation | 30: 15 replies, all marked done, 4 authors, 8 zero-length anchors, 4 anchored inside display equations | 395: 284 inline, 111 in 100 display paragraphs, 29 equation arrays, 19 matrices, 119 accents | 49 | 4 | 19 controls, 17 works |
| Methods clean copy | 908 | as above | none | 30 left in `comments.xml`, no anchors in the text | 395 | 49 | 4 | 19 controls |
| Supplement | 172 | 12 | none | 17: 7 replies | 16 inline | 0 | 0 | 0 |
| Supplementary captions | 33 | 1 | none | 2, both anchored inside inline equations | 37 inline | 0 | 0 | 0 |
| Editor letter, Reviewer 1, required experiments | 1, 3, 61 | 0 | none | 0 | 0 | 0 | 0 | 0 |
| Compiled main text `.docx` | 169 | 9 | none | 0 | 12 inline | 0 | 6 | 41 controls |

| File | Facts |
|---|---|
| Supplementary tables `.xlsx` | 14 sheets, 2,866 filled cells (713 text, 2,153 numeric), 221 formula cells all carrying a cached value, 171 merged ranges |
| Manuscript PDF | 23 pages, macOS Quartz, untagged, with margin line numbers (497 lines of the `-layout` text start with one) |
| Compiled PDF | 61 pages: the main text with figures, then the Methods typeset from `.docx` by pandoc and xelatex |
| Reviewer 2 attachment PDF | 3 pages (iText through pdftk), with a text layer |

Structural observations that bear on every route:

- **Unstyled headings.** The manuscript's title, "Abstract", "References", and one run-in heading are bold paragraphs with no heading style. No `.docx` route marks them as headings; docling on the PDF does, from the page.
- **Captions as plain paragraphs.** Figure captions are plain paragraphs under a "Figure Captions" heading (in the compiled `.docx`, plain paragraphs after each image). No route can link a caption to its figure in these files.
- **Equation-number tables.** 47 of the Methods' 49 tables are one row of two cells, Word's equation-number idiom: 44 of them hold an equation, and the numbers "(n)" come from the document's 44 `SEQ` fields, mostly in Caption-styled paragraphs. Every route reproduces them as 47 tables.
- **Reference lists in controls.** Each reference list sits inside a Mendeley bibliography content control, with 56 entries in the manuscript and 18 in the Methods.

## In: `.docx`, route by route

**Tracked changes** (manuscript, 35 inserted and 27 deleted diagnostic segments):

| Route | Accept | Reject | Both, marked | Markers |
|---|---|---|---|---|
| pandoc `--track-changes=` | 35/35, 0/27 | 0/35, 27/27 | 35/35, 27/27 | 168 `.insertion` and 93 `.deletion` spans, each with author and date; 3 `.paragraph-insertion`, 6 `.paragraph-deletion` |
| Standard-library prototype | 35/35, 0/27 | 0/35, 27/27 | 35/35, 27/27 | CriticMarkup `{++ ++}` and `{-- --}` |
| docling | 35/35, 0/27 | none | none | accepts, with no option |
| LibreOffice `--convert-to txt` or `html` | none | none | 35/35, 27/27 | none: both versions run together as one text |
| LibreOffice through UNO | 35/35, 0/27 | 0/35, 27/27 | not applicable | 339 redlines before, 0 after; 1.1 s start and 0.9 s work |

The 171 formatting changes (`w:rPrChange`, `w:pPrChange`) surface in no route. All routes ignore them as text. The Methods' one tracked change sits inside an equation. pandoc applied it; docling wrote no equation matching that one.

**Equations** (Methods: 395 OMML elements; the other files add 65 inline equations):

| Route | Equations written | Compile | Letters and digits of each source equation, in order | Accents (source: 99 `U+0307`, 15 default hat, 5 `U+02D9`) | Equation arrays (29) |
|---|---|---|---|---|---|
| pandoc | 384: 100 display (one per display paragraph) and 284 inline, 2 of them empty | 382/382 (447/447 across the four files with equations) | 317/318; the one miss holds the tracked deletion, which pandoc applied | 99 `\dot`, 15 `\widehat`, 5 `\overset{˙}`: all 119 | 23 `aligned`, 6 `array` |
| docling | 392 | 391/392, plus 3 of the captions file's 37 failing (`! Extra }, or forgotten $`) | 317/318 | 99 `\dot`, 15 `\hat`; the 5 `U+02D9` accents are dropped | 28 written as rows joined by a bare `\\` with no environment, which renders as one line |
| Standard-library prototype | 389 (6 empty OMML skipped) | 389/389 | 318/318 | 99 `\dot` and 20 `\hat`: the 5 `U+02D9` accents come out as hats (a missing map entry) | 29 `aligned` |
| LibreOffice text | 0: every equation is dropped | none | none | none | none |
| LibreOffice HTML | 395 GIF images (the Methods' HTML export took 19 s) | none | none | none | none |

Fractions (40), radicals (4), and n-ary operators (6) came out one for one in pandoc and the prototype. docling wrote 42 fractions and once printed `\det(\left(...\right))` with doubled parentheses. The manuscript's, the supplement's, and the captions file's inline equations agree across the three LaTeX routes, up to synonyms such as `\ge` and `\geq`.

**Comments** (49 in the three commented files):

| Route | Methods (30) | Supplement (17) | Captions (2) | Anchor | Thread and done |
|---|---|---|---|---|---|
| Standard-library prototype | 30 | 17 | 2 | text span; an anchor inside an equation is widened to the equation | reply-to and done, from `commentsExtended.xml` |
| pandoc `--track-changes=all` | 26 | 17 | 0 | text span: `[anchor]{.comment-start id= author= date=}` | not kept |
| docling | 30 | 17 | 2 | JSON links from 38 body items (76 links) to one group per comment; the Markdown lists the comments at the end with author and time | replies not joined |
| LibreOffice | 0 | 0 | 0 | none | none |

- **The six comments pandoc drops** are exactly the six anchored inside equations: 4 in display equations, 2 in inline ones.
- **The clean copy is not clean of comments.** Its `comments.xml` still holds all 30 comments with no anchors in the text:
  - pandoc shows none of them;
  - docling shows all 30, unlinked;
  - the standard-library reader lists them with no anchor.

**Citations and the reference list:**

- **Mendeley Cite controls.** In-text citations are Mendeley Cite content controls. Each control's `w:tag` is `MENDELEY_CITATION_v3_` followed by base64 JSON: `citationID`, `citationItems[].itemData` in CSL-JSON (`DOI`, `PMID`, `URL`, `title`, `author`, `issued`, `container-title`, and more), `properties`, `isEdited`, and `manualOverride`.
- **Decoded by the standard library.** Decoding with `base64` and `json` gives, for the manuscript, 56 works: 33 with a DOI, 12 with a PMID, 24 with a URL, 8 with none of the three. The Methods gives 17 works, 10 with a DOI.
- **No converter reads them.**
  - pandoc's docx reader recognizes only field codes: `ADDIN [ZOTERO_ITEM] CSL_CITATION`, `ADDIN ZOTERO_BIBL` or `Mendeley Bibliography CSL_BIBLIOGRAPHY`, `ADDIN EN.CITE`, and `EN.REFLIST`. So `+citations` produced 0 `Cite` elements, and the numbers survive as 60 superscripts (`model^32^`).
  - docling writes the number as a separate token (`model 32 ,`).
  - LibreOffice glues it to the word (`model32`).
  - The prototype writes `[@doi:...]` and keeps the CSL-JSON beside the Markdown.
- **The formatted reference list** (the bibliography control's 56 entries) survives as text in every route. docling writes `&` as `&amp;`.

**Headings, tables, images, lists:**

- **Headings.** On the style-based headings, pandoc, docling, and the prototype agree: 11 in the manuscript, and 48 non-empty ones in the Methods (docling 49, with the table-of-contents heading). LibreOffice's HTML keeps the 10 empty headings and the table-of-contents heading too, 59 in all; its text export has no heading markup.
- **Tables.** All four structured routes produce 49 tables from the Methods, the 47 equation-number layouts included.
- **Images.** pandoc extracts every image (6 in the compiled `.docx`, 4 in the Methods). docling records them as pictures, 0 of them with a caption. The prototype writes a placeholder with the media path.
- **Numbered lists.** Word's auto-numbered lists are rare here: 2 items in the required-experiments file. pandoc keeps them as an ordered list, docling writes bullets with the number in the text, and LibreOffice's text and the prototype lose the numbers.

**Time** (wall clock, one process per file):

| Route | Smallest file | Manuscript | Methods |
|---|---|---|---|
| Standard-library prototype | 0.04 s | 0.07 s | 0.13 s |
| pandoc | 0.02 s | 0.23 s | 0.9 s |
| docling (about 3.1 s of each is loading) | 4.0 s | 6.2 s | 9.0 s |
| LibreOffice text | 1.3 s | 1.6 s | 2.7 s |
| LibreOffice HTML | 1.2 s | 1.9 s | 19 s |

**Size of what a model would read** (Methods): pandoc Markdown 119 KB, docling 92 KB, the prototype 86 KB, LibreOffice text 66 KB (with no equations).

**A legacy `.doc`.** pandoc refuses it: "Pandoc can convert from DOCX, but not from DOC." A `.doc` made by LibreOffice from the required-experiments file went back through `soffice --convert-to docx` and then pandoc with 45 of 45 probes.

## In: PDF

| PDF | Route | Text probes | Structure | Equations | Time |
|---|---|---|---|---|---|
| Manuscript (23 pages) | `pdftotext -layout` | 152/219; 219/219 after stripping the margin line numbers | none | inline math as Unicode letters | 0.05 s |
| | `pdftotext` (reading order) | 151/219: line numbers land mid-sentence, where a line-start pattern cannot remove them | none | as above | 0.05 s |
| | docling | 212/219 | 17 headers (the 11 styled ones plus the title, "Abstract", the run-in heading, "References", and two captions); 23 list items; three reference-list pages read as `document_index` tables | 0 detected | 12 s |
| | LibreOffice | 0: a 24-byte file | none | none | 2 s |
| Compiled (61 pages) | `pdftotext -layout` | 663/681 | none | display math as Unicode lines | 0.07 s |
| | docling with formula enrichment | 660/681 | 71 headers, 16 tables, 5 pictures (3 linked to a caption), 6 captions, 41 page footers | 104 display equations in LaTeX, 79 compile unmodified (23 fail on `&` outside an environment); median similarity 0.94 to the source's equations | 97 s on the GPU |
| | docling without enrichment | 660/681 | as above | 104 `<!-- formula-not-decoded -->` placeholders | 22 s |
| Reviewer 2 attachment (3 pages) | `pdftotext` | all | none | none | 0.02 s |
| | docling | all 534 words of six or more letters | 1 header, 13 list items (the numbered points) | none | 12 s |

- **The manuscript PDF is the accepted text.** After the strip, it holds 35 of 35 inserted and 0 of 27 deleted segments.
- **docling's losses** are where margin line numbers merge into reference-list items.
- **Math letters in pdftotext.** pdftotext prints italic math letters as Mathematical Alphanumeric Symbols (for example `U+1D461`), which NFKC normalization maps to ASCII.

## In: `.xlsx`

| Route | Text cells | Numeric cells | Sheets | Formulas | Size | Time |
|---|---|---|---|---|---|---|
| Standard library | 713/713 | 2,153/2,153 (as stored) | one CSV per sheet | cached values | 48 KB | 0.05 s |
| LibreOffice CSV, all sheets (`-1`) | 713/713 | all, as displayed ("E+023" exponents) | one file per sheet, named by sheet | cached values | 43 KB | 1.6 s |
| pandoc 3.11 | all (apostrophes escaped) | all, at 15 significant digits | one heading and one table per sheet | cached values | 174 KB, or 60 KB with pipe tables | 0.2 s |
| docling | 713/713 | all, printed at full precision | Markdown loses the names (the JSON keeps them as `sheet` groups); 35 tables | cached values | 534 KB | 4.5 s |

Every "missing" number in the raw string match was the same value printed to a different precision or exponent format.

## Out: installing pandoc

| | Download | On disk | Install | Version | Notes |
|---|---|---|---|---|---|
| Release tarball `pandoc-3.11-linux-amd64.tar.gz` | 34.9 MB, 1.65 s | 157 MB (`bin/pandoc` plus man pages) | unpack, 0.67 s | 3.11 | statically linked, no dependencies; sha256 `37edb3bbcf722f921a009941bf5874e2e0c09263226c9b4a2d980788cb062ab6`, equal to the `digest` the GitHub releases API gives for the asset |
| `pypandoc_binary` 1.17 wheel (manylinux x86_64) | 34.5 MB | 155 MB venv | 2.6 s with `uv` | bundles pandoc 3.9 | the wrapper is MIT-licensed and pandoc GPL-licensed; the harness would run the binary, never import the wrapper |
| pandoc-crossref v0.3.25a | 7.5 MB | 63 MB | unpack | built with pandoc 3.11 | must match pandoc's version; `--filter` it before `--citeproc` |

- **Same speed.** Both pandoc binaries built the synthetic PDF in 2.2 s and the `.docx` in 0.09 s.
- **Where 3.9 falls short.** 3.9 ignores the `.float` table class that 3.11 added for two-column layouts; the same body came out as `longtable` from 3.9 and as `table` from 3.11.
- **Pin the version.** The changelog on pandoc's `main` already has a 3.12 entry dated 2026-09-27, with no tag or binaries yet. Pin a version and its digest rather than "latest".
- **Prior art on this machine.** PINF_Project's own compile script (`tools/build.py`, reference only) already sends the Methods through `pypandoc_binary`'s pandoc and xelatex, noting that LibreOffice mangles Word equation arrays. The measurements below show the same.

## Out: a synthetic paper

The sample is three section files (Introduction, Results, Methods) with:

- inline and display math, including an `aligned` block;
- a raw `\begin{equation}` with `\label` and `\ref`;
- six provenance tags: one `ref`, five `res`, one of them directly after a citation's bracket;
- two BibTeX entries cited as `[@key]`, one with a locator;
- a figure and a pipe table, each with a caption and an id;
- an author footnote;
- `σ ≥` in prose.

It was built with `metadata.yaml`, `refs.bib`, and `nature.csl` from the CSL styles repository.

| Build | Command (after `pandoc metadata.yaml sections/*.md`) | Time | Result |
|---|---|---|---|
| PDF | `--citeproc --csl nature.csl -L provenance.lua --pdf-engine=xelatex` | 2.2 s | 2 pages; tags as footnotes 1 to 6; superscript citations and a numbered reference list; figure, table, and equation (1) numbered; σ and ≥ missing |
| PDF | same with `--pdf-engine=pdflatex` | 0.5 s | fails: `! LaTeX Error: Unicode character σ (U+03C3) not set up for use with LaTeX` |
| PDF | same with `--pdf-engine=lualatex` | 14.5 s first, 3.5 s after | as xelatex (the first run builds the font cache) |
| PDF | same with `--pdf-engine=latexmk --pdf-engine-opt=-xelatex` | 2.2 s | as xelatex |
| PDF | xelatex with `-V mainfont="DejaVu Serif" -V mathfont=STIXTwoMath-Regular.otf` | 2.2 s | σ and ≥ present (`mainfont="STIX Two Text"` fails: TeX Live's copy is not registered with fontconfig) |
| `.docx` | `--citeproc --csl nature.csl -L provenance.lua -o paper.docx` | 0.09 s | 11 native Word equations (9 inline, 2 display), 7 footnotes (6 tags, 1 author note), 1 table, 1 image, citations as text; the raw `\begin{equation}` and its `\ref` are gone ("Equation is the update") |
| LaTeX, standalone | `-s --natbib` or `-s --biblatex`, then `latexmk -xelatex` | 0.06 s, then 3.8 s or 6.6 s | natbib `plainnat` author-year; biblatex numeric |
| LaTeX body | `--natbib -L provenance.lua -t latex -o body.tex`, in a venue wrapper | 0.05 s | `elsarticle` (xelatex, `elsarticle-num`): compiles. `IEEEtran`: `! Package longtable Error: longtable not in 1-column mode`, compiles with `-L float.lua`. NeurIPS 2026 (`\usepackage[main]{neurips_2026}`, `latexmk -pdf`, `plainnat`): compiles once `σ ≥` is written as `$\sigma \geq$` |
| HTML | `-s --mathml --embed-resources` | 0.09 s | MathML |
| LibreOffice PDF of the `.docx` | `soffice --convert-to pdf paper.docx` | 1.3 s | text and inline math fine; `x^\ast` gains a stray "¿"; the `aligned` block prints as "ẋ∧¿ μ x ..."; footnote numbers restart |
| LibreOffice PDF of the HTML | `soffice --convert-to pdf paper.html` | 1.1 s | MathML printed as linear text followed by its TeX annotation; `\ref` dropped |

**A body for a venue's class** needs, beyond the class:

- `amsmath`, `amssymb`, `graphicx`, `longtable`, `booktabs`, `array`, and `hyperref`;
- the three definitions pandoc's own template carries in its `common.latex` partial: the `longtable` setup (lines 71 to 93), `\pandocbounded` (line 103, emitted for any image without a size), and `\tightlist` (line 221, emitted for every list).

A venue wrapper copies them from `pandoc --print-default-data-file templates/common.latex`, or a pandoc template is made from the venue's.

**Provenance tags.**

- **With nothing handling them,** the six tags print literally in the PDF (`{res:t3-a1/summary.json#auroc}`, braces and all), and all six stay literal in the `.docx`.
- **A tag right after a citation's bracket** (`[@strogatz2015]{res:...}`) is not taken for an attribute block; it stays a plain string.
- **The filter below** sees each tag as one `Str`, with any punctuation glued on.
- **A locator with a space** (`#best model`) is split across two strings, and the filter lets it through literally. The harness's `TAG_RE` allows spaces, so either locators forbid them or the filter works on whole `Inlines`.

```lua
-- provenance.lua: metadata `provenance` = footnote (default) | strip | keep
local mode = "footnote"
local seen = 0
local function Meta(meta)
  if meta.provenance then mode = pandoc.utils.stringify(meta.provenance) end
end
local function Str(el)
  local s = el.text
  local out, pos, found = {}, 1, false
  while true do
    local a, b, kind, body = s:find("{(re[sf]):([^{}]+)}", pos)
    if not a then break end
    found = true
    if a > pos then table.insert(out, pandoc.Str(s:sub(pos, a - 1))) end
    seen = seen + 1
    if mode == "footnote" then
      table.insert(out, pandoc.Note({ pandoc.Plain({ pandoc.Code(kind .. ":" .. body) }) }))
    elseif mode == "keep" then
      table.insert(out, pandoc.Str(s:sub(a, b)))
    end
    pos = b + 1
  end
  if not found then return nil end
  if pos <= #s then table.insert(out, pandoc.Str(s:sub(pos))) end
  return out
end
local function Inlines(inlines)   -- drop the space left before a note
  for i = #inlines, 2, -1 do
    if inlines[i - 1].t == "Space" and inlines[i].t == "Note" then inlines:remove(i - 1) end
  end
  return inlines
end
local function Pandoc(doc)
  io.stderr:write(string.format("provenance.lua: %d tags, mode %s\n", seen, mode))
  return doc
end
return { { Meta = Meta }, { Str = Str }, { Inlines = Inlines }, { Pandoc = Pandoc } }
```

- **Footnote mode** gives six footnotes in the PDF, the `.docx`, and the LaTeX body (`\footnote{\texttt{res:t3-a1/summary.json\#auroc}}`).
- **Numbering collides.** Under a numeric superscript style such as Nature's, a footnote marker and a citation number look the same, and in extracted text "0.91" followed by footnote 2 reads "0.912". A review build could give the tags their own marker, such as letters or a bracketed prefix; that is untested.
- **Strip mode** (`-M provenance=strip`) removes them all.
- **The harness's own renderer as a pre-pass** (`wayline.provenance.render_citations`, then pandoc) gives six footnotes too. It also leaves its "Supplementary references" heading and explanation in the paper, and it carries a hazard: a section's own `[^1]` next to a rendered `[^1]` makes pandoc warn `Duplicate note reference '1'` and print the last definition at both places. Measured: the tag's text vanished.

**Cross-references.**

- **Without pandoc-crossref.** `@fig:branch` is read as a citation: citeproc warns "citation fig:branch not found" and prints "Figure?". natbib prints "Figure ?", and biblatex prints the key.
- **With `--filter pandoc-crossref`.** It prints "fig. 1", and `$$...$$ {#eq:rk4}` is numbered "(1)" and referenced as "eq. 1". The prefixes are metadata.

**The two-column filter**, printed in the pandoc manual under "Table placement in LaTeX":

```lua
function Table(el)
  el.classes:insert("float")
  return el
end
```

**docling is not an OUT route.** Its LaTeX export (`docling convert x.md --to latex`, 0.01 s after loading) fails the sample:

- it escapes the math as text (`\$\$ \textbackslash{}mathcal...`);
- it reads a display-math line that starts with `+` as a bullet;
- it drops the figure;
- it leaves `[@key]` and the attribute blocks as literal text.

## What could not be verified

- **Word's rendering.** No Microsoft Word is on this machine, so pandoc's `.docx` was rendered only by LibreOffice, whose own equation import is at fault above. The `.docx` itself carries 11 native Word equations, 7 footnotes, and the table and image.
- **Equation fidelity is not visual.** It was checked by compiling, by construct counts, and by letters and digits in order, not by rendering each equation and comparing it with Word's. An error that keeps every letter and every construct count (a misplaced subscript, say) would pass.
- **The Mendeley Cite format.** No vendor specification of the `MENDELEY_CITATION_v3_` tag was found. It was decoded from the files themselves, and the only outside corroboration is a Zotero developer's statement that Mendeley Cite citations are unreadable by field-code tools.
- **Other citation fields.** pandoc's handling of Zotero, Mendeley Desktop, and EndNote field codes is from its source only; no such document was at hand.
- **Coverage of the prototypes.** The standard-library reader was tested on these nine `.docx` files only. It does not read `numbering.xml` (list numbers), text boxes, or headers and footers, and its accent table is incomplete.
- **docling's speed without a GPU** was not measured. Every docling time here is on the RTX 3090.
- **Other legacy formats.** Legacy `.doc` was tested only on a file LibreOffice itself wrote, and `.odt` and `.rtf`, which pandoc reads natively, were not tested.
- **pandoc 3.12** was not tested; it had no release when these probes ran.

## Sources

- **This repository and the map.**
  - [Ticket #177](https://github.com/Bernaljp/wayline/issues/177) and [map #173](https://github.com/Bernaljp/wayline/issues/173).
  - The owner's brief, `.scratch/living-paper/owner-brief.md`, sections 1.4 and 5.10 (untracked, in the main checkout).
  - `.scratch/wayline/spec.md:309`, decision 1: converters run as subprocesses; the harness imports no third-party package.
  - `.scratch/wayline/spec.md:377`, decision 1's verb table: `tools install` creates the converter venv under `~/.wayline/tools/`.
  - `.scratch/wayline/spec.md:602`, decision 9: the non-arXiv PDF chain, `pdftotext -layout`, and docling with formula enrichment.
  - `wayline/tools.py:50-55`: the tools venv installs docling and pdfplumber.
  - `wayline/pdf_inventory.py:168`: `pdftotext -layout` in the inventory.
  - `converters/docling_convert.py`: formula enrichment on by default.
  - `wayline/intake.py:326-360`: a `.docx` becomes a Data line.
  - `wayline/provenance.py:60`: `TAG_RE`.
  - `wayline/provenance.py:505-528`: `render_citations`.
- **pandoc.**
  - The pandoc 3.11 manual, `share/man/man1/pandoc.1.gz` in the release tarball, also at <https://pandoc.org/MANUAL.html>. The sections used: `--track-changes`, "Extension: citations (docx)", `--citeproc`, `--natbib`, `--biblatex`, `--pdf-engine`, "Table placement in LaTeX", and the LaTeX package list.
  - Installing: <https://pandoc.org/installing.html> ("The executable is statically linked and has no dynamic dependencies or dependencies on external data files").
  - Release 3.11 and its assets and digests: <https://github.com/jgm/pandoc/releases/tag/3.11>.
  - The changelog: <https://github.com/jgm/pandoc/blob/main/changelog.md>. It holds 3.11's LaTeX writer entry ("When the `float` class is attached to a table, a standard floating `table` will be generated instead of a `longtable`", #1023), 3.8.3's `xlsx` reader, and the untagged 3.12 entry.
  - The docx citation fields: <https://github.com/jgm/pandoc/blob/ec47bb2331473682b5fc5e5d8eb3a80c91252324/src/Text/Pandoc/Readers/Docx/Fields.hs#L67-L94>.
  - The longtable issue: <https://github.com/jgm/pandoc/issues/1023>, closed 2026-07-10.
  - The template partial: `pandoc --print-default-data-file templates/common.latex` (pandoc 3.11), lines 71 to 93, 103, and 221.
- **pypandoc and pandoc-crossref.**
  - `pypandoc_binary` 1.17: <https://pypi.org/project/pypandoc-binary/>. The bundled pandoc 3.9 was read from `pypandoc.get_pandoc_version()`.
  - pandoc-crossref v0.3.25a: <https://github.com/lierdakil/pandoc-crossref/releases/tag/v0.3.25a> ("built with Pandoc v3.11").
- **docling 2.126.0**, source in `~/.wayline/tools/venv/lib/python3.12/site-packages/docling/backend/`:
  - `msword_backend.py:51`, OMML to LaTeX;
  - `msword_backend.py:1280-1281`: deleted runs carry `w:delText`, so they are dropped;
  - `msword_backend.py:1549-1553`: `w:ins` is walked into;
  - `msword_backend.py:1960-2006`: equations;
  - `msword_backend.py:3651-3741`: comments in the notes layer, linked to paragraphs;
  - `docx/latex/omml.py:11`: adapted from dwml;
  - `msexcel_backend.py:559`: sheets as groups.
- **LibreOffice 24.2.**
  - Command-line parameters: <https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html>.
  - CSV filter options: <https://help.libreoffice.org/latest/en-US/text/shared/guide/csv_params.html> (token 9 "Save cell contents as shown"; token 12 `-1` for every sheet, one file per sheet).
  - The dispatch commands `.uno:AcceptAllTrackedChanges` and `.uno:RejectAllTrackedChanges` in `/usr/lib/libreoffice/share/registry/writer.xcd`.
- **poppler.** `man pdftotext` (poppler-utils 24.02.0), `-layout`: "Maintain (as best as possible) the original physical layout of the text."
- **Office Open XML.**
  - ECMA-376 Part 1 (Fundamentals and Markup Language Reference): <https://ecma-international.org/publications-and-standards/standards/ecma-376/>.
  - [MS-DOCX] `commentsEx`: <https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/a396bd32-6b3a-419a-b2d5-b01a8dec35b7>.
  - [MS-DOCX] `CT_CommentEx`: <https://learn.microsoft.com/en-us/openspecs/office_standards/ms-docx/9660dacc-2ceb-4352-87d2-42ba1184f522>. `paraIdParent` names the comment a reply answers; `done` marks a comment done.
- **Mendeley Cite.** Zotero forums, dstillman, 2022-05-24: "Zotero can read citations created by Mendeley Desktop, but not Mendeley Cite." <https://forums.zotero.org/discussion/97363/zotero-word-plugin-does-not-detect-mendeley-cite-references-content-controls>.
- **Styles used by the synthetic paper.**
  - NeurIPS 2026 style: <https://media.neurips.cc/Conferences/NeurIPS2026/Formatting_Instructions_For_NeurIPS_2026.zip>, the URL in `guidelines/neurips/guidelines.json`.
  - `nature.csl` from <https://github.com/citation-style-language/styles>.
