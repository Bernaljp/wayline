# 06. Dossier inventory for non-arXiv PDFs and keyless literature APIs

Resolves `.scratch/harness/issues/06-pdf-inventory-and-keyless-apis.md` (BRIEF Section 7.3, `scout.py`).
Date: 2026-09-11. Machine: Python 3.12.3, poppler 24.02 (`pdftotext`, `pdfimages`, `pdftoppm`), `mutool`,
`docker` 29.1.3 (client), `pdflatex`, `latexmk`, `latexpand`, `git`, `gh`; one RTX 3090 (24 GB), 128 cores,
~1 TB RAM, 9.8 TB free on `/home`. None of PyMuPDF, pdfplumber, marker, nougat, docling, MinerU, ctags, or
tree-sitter is installed. Nothing was installed for this ticket; footprints come from `pip install --user
--dry-run --report` and PyPI metadata. Every claim carries a URL; anything I could not confirm from a primary
source is marked "unverified".

## Answer

### 1. Non-arXiv PDFs: recommended chain

**Always-on layer (seconds, CPU, no models): `pdftotext -layout`, `pdfinfo`, `pdfimages -list`, and
pdfplumber.** These give the exact text layer, page count, embedded-image list, word and char boxes, and
ruled tables. They cannot give sections, equations as LaTeX, or captions. Use them for the `text_layer`,
`page_count`, `raw_images` fields and as the ground truth that model outputs are checked against.

**Primary structural converter: docling (`pip install docling`, MIT code).** Reasons: pip-only install,
runs on CPU and accelerates on CUDA, produces a lossless JSON `DoclingDocument` with typed items
(section headers, text, captions, tables, pictures, formulas, code, footnotes) and page/bbox provenance
per item, writes figures and tables to PNG files, and has an optional `do_formula_enrichment` pass that
emits LaTeX for formula items. Sources: README and docs (details section). Docling's own docs say the
enrichment models "may increase the processing time consistently", so run formula enrichment on the GPU.

**Fallback A for math-heavy or badly laid-out PDFs: marker (`marker-pdf` 2.0.0, Apache-2.0 code,
OpenRAIL-M weights).** Marker's README reports it ahead of MinerU and docling on olmocr-bench (self-reported,
76.0 percent overall, 83.5 percent born-digital) and converts inline and display math to LaTeX in
`balanced` mode. Cost: marker 2.0 runs its surya VLM behind a local inference server, "vLLM (docker) on
NVIDIA GPUs" or `llama-server` on CPU, so it needs Docker plus the NVIDIA Container Toolkit (Docker is
installed; the toolkit is unverified on this box). Its `--disable_ocr` CPU mode "skips equations", so
the fallback is only useful with the GPU.

**Fallback B: MinerU `pipeline` backend (custom Apache-2.0-based license, CPU or GPU, min 4 GB VRAM,
min 16 GB RAM, 20 GB disk).** Formulas to LaTeX and tables to HTML, images extracted. Heavier than
docling (39 base packages before the `[pipeline]` extra adds torch, plus model downloads from
HuggingFace or ModelScope). Use it when both docling and marker fail on a document.

**References and header metadata: GROBID CRF Docker image (`grobid/grobid:0.9.1-crf`, Apache-2.0,
~500 MB, CPU, 2 to 3 GB RAM).** GROBID is the only candidate that parses the bibliography into
structured `biblStruct` entries (self-reported F1 0.87 on PMC, 0.90 on bioRxiv) and can consolidate
them against Crossref. It returns only coordinates for figures and formulas, never image bytes or
LaTeX, so it is a references-and-metadata tool, not the main converter. Tag verified to exist on Docker
Hub.

**Rejected: nougat.** MIT code but CC-BY-NC weights, last PyPI release 2023-10-04, GPU-only in
practice (`[MISSING_PAGE]` false positives on CPU per its own FAQ), and it emits a flat `.mmd` with no
figure files or item provenance. **PyMuPDF / pymupdf4llm** is excellent and CPU-only (9 packages, layout
model via onnxruntime) but is AGPL-3.0 or commercial, so keep it optional; pdfplumber (MIT) covers the
text-layer role.

**Inventory fields and who fills them (non-arXiv PDF):**

| Field | Reliable mechanical source | Needs a model or reader pass |
|---|---|---|
| `page_count`, `text_layer`, `raw_images[]` | `pdfinfo`, `pdftotext -layout`, `pdfimages -list` | no |
| `sections[]` (title, level, page, bbox) | docling `section_header` items (layout model) | numbering and appendix detection by regex on the header text; verify order against `pdftotext` |
| `figures[]` (image file, caption, page) | docling `PictureItem.get_image()` + linked captions; marker `Figure`/`Caption` blocks | "what it shows" is a reader task (BRIEF 7.3 step 3) |
| `tables[]` (cells, caption) | docling TableFormer (`TableItem`, export to DataFrame/HTML); marker HTML tables | numeric sanity check is a reader task |
| `equations[]` (latex, number, page) | docling `formula` items + `do_formula_enrichment`; marker `$$` blocks | LaTeX is OCR-derived, never "exact form"; equation numbers must be regex-recovered from adjacent text `(N)` and confirmed by a reader |
| `algorithms[]`, `theorems[]` | none dedicated; regex on `^(Algorithm|Theorem|Lemma|Proposition|Definition|Corollary)\s+\d` in docling text items | boundary of the environment is a reader task |
| `appendices[]` | regex on section headers (`^Appendix`, `^[A-Z]\.\s`) | no |
| `references[]` (structured) | GROBID `processFulltextDocument` TEI `biblStruct` with `consolidateCitations=1` | no |
| `metadata` (title, authors, DOI) | GROBID header + the API chain in Section 3 | no |

Mark every model-derived field with `provenance: "docling-<version>"` or `"marker-<version>"` and keep
the page and bbox so the reader can look at the rendered crop (`pdftoppm -r 150 -f P -l P`).

### 2. arXiv papers: source fetch and LaTeX inventory

- URL: `https://export.arxiv.org/src/<id>[vN]`. `/e-print/<id>` 301-redirects to `/src/<id>` (verified with
  HEAD). `/src/` always returns a gzipped tar per arXiv's MIME-type page; verified
  `Content-Disposition: attachment; filename="arXiv-1706.03762v7.tar.gz"` and `ETag: "sha256:..."`. Older
  single-file submissions also came back as `.tar.gz` (verified on hep-th/9901001). PDF-only submissions
  return `application/pdf`. Use `export.arxiv.org` (the host arXiv sets aside for programmatic access);
  it serves `/src/` (verified 200).
- Rate policy: the API Terms of Use say "make no more than one request every three seconds, and limit
  requests to a single connection at a time"; `robots.txt` sets `Crawl-delay: 15` and disallows
  `/e-print` and `/src` to crawlers; the bulk-data page suggests "bursts at 4 requests per second with a
  1 second sleep" on `export.arxiv.org`. The harness fetches a handful of sources per session, so use
  one request per 3 s, one connection, a `User-Agent` with a `mailto:`, and cache by ETag forever. The
  ToU forbid re-serving e-prints from your own servers, so `refs/<slug>/source/` stays local and out of
  any published artifact.
- Tarball layout (verified on 1706.03762): flat or nested `.tex` files, `.sty`/`.bst`/`.bbl`, and figure
  directories (`Figures/*.png`, `vis/*.pdf`). Newer submissions may include `00README.json` or
  `00README.XXX` with a `<file> toplevelfile` line; otherwise the main file is the `.tex` containing
  `\documentclass` (grep, then prefer the one that `\input`s the others).
- Inventory: `latexpand main.tex > flat.tex` (installed at `/usr/bin/latexpand`; add `--expand-bbl` to
  inline the bibliography), strip `%` comments, then regex the environments. Verified on 1706.03762:
  `equation` 3, `align*` 2, `figure`+`figure*` 5, `table` 4, 13 `\label`, 17 `\ref`/`\eqref`, 9
  `\caption`, 23 `\section`/`\subsection`, 0 unresolved `\input` after flattening. Figures are the
  `\includegraphics` targets resolved against the tarball (PDF figures rasterized with `pdftoppm`).
- Equation and figure numbers: LaTeX does not store them. Two options: (a) count numbered environments in
  document order, skipping `\nonumber` and honoring `\tag`; (b) run `pdflatex` once (installed) and read
  `\newlabel{<label>}{{<number>}{<page>}...}` lines from the `.aux`, which gives exact numbers and pages
  for every labeled item. Do (b) when the source compiles, (a) otherwise. Unlabeled numbered equations
  only get numbers from (a).
- Second source when the tarball will not flatten: `https://arxiv.org/html/<id>` (allowed by
  `robots.txt`, verified 200), which is LaTeXML output with MathML plus LaTeX `alttext`. Coverage is not
  complete and arXiv calls it beta.

### 3. Keyless metadata APIs: order and limits

All limits below are from the providers' own docs unless flagged; live probes were run on 2026-09-11 with
`User-Agent: SpecDrivenResearch/0.1 (mailto:<address>)`.

**Given a DOI:** Crossref `GET https://api.crossref.org/works/{doi}?mailto=<address>` first (free, no
registration, polite pool by `mailto`; live headers showed `x-api-pool: polite-single`,
`x-rate-limit-limit: 10`, `x-rate-limit-interval: 1s`). Then OpenAlex
`GET https://api.openalex.org/works/doi:{doi}` for OA status, PMID, cited-by count, and referenced works
(keyless budget observed at 1000 credits = USD 0.10 per day, single-entity GET cost USD 0.0001 on first
call and 0 when repeated; a free key gives 10x and 100 requests per second; 429 when exceeded). Then
Unpaywall `GET https://api.unpaywall.org/v2/{doi}?email=<address>` for `best_oa_location.url_for_pdf`
(email is mandatory; the 100,000 calls per day figure is reported by secondary sources because the
Unpaywall product page is JavaScript-rendered, so "100k/day: unverified from primary"). For biomedical
DOIs also Europe PMC `search?query=DOI:{doi}&format=json&resultType=core` (no key; the per-IP limit
"10 requests per second (or 500 requests per minute)" appears in a staff-answered thread on the
official epmc-webservices group, not in the reference page, so treat it as semi-official). Semantic
Scholar last: without a key it shares "1000 requests per second... among all unauthenticated users" and
the live keyless probe returned 429 on the first call, so do not depend on it keyless.

**Given a title:** Crossref `works?query.bibliographic=<title>&rows=3&select=DOI,title,author,issued,score`
first (`query.title` is deprecated). Then OpenAlex `works?search=<title>` (search calls cost USD 0.001,
so about 100 per keyless day; use sparingly). Then Europe PMC `TITLE:"<title>"` (verified hit) for
biomedical work. Semantic Scholar `/paper/search/match?query=<title>` is the best single-hit title
matcher (returns one paper with `matchScore` or 404 "Title match not found") but only with a key.

**Given an arXiv id:** arXiv API `https://export.arxiv.org/api/query?id_list=<id>` first (3 s
spacing; returns `arxiv:doi`, `arxiv:journal_ref`, `arxiv:primary_category`, PDF and abs links; results are
paged in slices of at most 2000 per call). Then Semantic Scholar `/paper/ARXIV:<id>` or POST `/paper/batch` with
`{"ids": ["ARXIV:<id>", ...]}` if a key exists. OpenAlex has no arXiv namespace on the singleton
endpoint (`works/arxiv:<id>` returned 404) and `filter=doi:10.48550/arXiv.<id>` returned 0 results for
1706.03762, so reach OpenAlex through the journal DOI from the arXiv record or through a title search.
bioRxiv and medRxiv: `https://api.biorxiv.org/details/{server}/{doi}/na/json` (verified fields:
`doi, title, authors, date, version, category, jatsxml, abstract, published, license, server`; 30
records per page; no rate limit stated in the docs).

**Citation existence check (the scout's main use):** Crossref by DOI, else Crossref bibliographic query
with a `score` threshold and a title similarity check in code, else OpenAlex, else Europe PMC (biomed),
else arXiv API (if an arXiv id or a `ti:` query). A reference that resolves nowhere is marked
`existence: unresolved`, not `fabricated`.

### 4. Code dossiers: pinned clone and symbol inventory

- Clone at a pinned commit: `git clone --filter=blob:none --no-checkout <url> && git checkout <sha>`
  (verified on GitHub, 14 MB for pdfplumber), or `git init && git fetch --depth 1 origin <sha> && git
  checkout FETCH_HEAD` (also verified; depends on the server allowing a raw SHA in `want`, which GitHub
  does). Record `url`, `sha`, `author_date`, nearest tag (`git describe --tags --always`), and
  `git submodule status`. Verified-recipe installs use pip's VCS form `pkg @ git+https://...@<full sha>`.
- Python inventory with the stdlib `ast` (no install): parse every `*.py`, walk `tree.body` for
  `FunctionDef`, `AsyncFunctionDef`, `ClassDef` (name, `lineno`, `end_lineno`, decorators via
  `ast.unparse`, docstring via `ast.get_docstring`), read `__all__` by `ast.literal_eval`, and mark
  public symbols as `__all__` members or non-underscore names. Verified on pdfplumber: 20 modules, 89
  top-level symbols. Entry points from `pyproject.toml` `[project.scripts]` and
  `[project.entry-points]` (stdlib `tomllib`) and `setup.cfg`; configs by glob (`*.yaml`, `*.yml`,
  `*.json`, `*.toml`, `configs/`); tests by `tests/`, `test_*.py`, `*_test.py`, `conftest.py`; scripts
  by `scripts/`, `bin/`, `*.sh`, and `if __name__ == "__main__"`; data requirements by grep for
  `hf_hub_download`, `load_dataset`, `urlretrieve`, `requests.get`, `wget`, `curl`, and `.tar.gz` URLs.
- Other languages: universal-ctags `ctags --output-format=json -R` (not installed; JSON output needs a
  libjansson build; apt package `universal-ctags`) or `tree-sitter` 0.26 plus
  `tree-sitter-language-pack` 1.18 (MIT, pip, ships grammars for many languages) with per-language
  queries for definitions. Neither is needed until a non-Python code dossier is promoted.

## Comparison table (PDF tools)

| Tool | Version (PyPI) | License: code / models | Install footprint (dry run) | Compute here | Sections | Equations to LaTeX | Figures to files + captions | Tables | Structured refs | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| poppler `pdftotext`/`pdfimages` | 24.02 (installed) | GPL (poppler) | 0 | CPU, ms per page | no | no | raw images only, no captions | no | no | always-on text layer |
| pdfplumber | 0.11.10 | MIT / none | 4 pkgs (pdfminer.six, pillow, pypdfium2) | CPU | no | no | image boxes only | ruled tables | no | text-layer fallback, char boxes |
| PyMuPDF + pymupdf4llm | 1.28.2 | AGPL-3.0 or commercial / layout model via onnxruntime | 9 pkgs | CPU, "without any GPU requirement" | font-size headers | no | `write_images` PNG per image area, no caption link | `find_tables`, cell structure | no | optional; license is the blocker |
| docling | 2.126.0 | MIT / "refer to the model licenses" | `docling-slim[standard]` + torch (dry run timed out resolving; torch-class footprint) | CPU or CUDA (`--extra-index-url .../whl/cpu` for CPU torch) | layout model `section_header` | `do_formula_enrichment` (CodeFormula) | `PictureItem.get_image()` PNG, captions linked | TableFormer | no | primary |
| marker-pdf | 2.0.0 (2026-07-20) | Apache-2.0 / OpenRAIL-M (free under USD 5M) | 26 direct deps incl. torch, transformers, surya; plus vLLM Docker (GPU) or llama-server (CPU) | GPU for math; CPU `--disable_ocr` skips equations | `section_hierarchy` | yes, `$$` blocks, inline math in balanced mode | images saved, `Caption` blocks | HTML | no | fallback A (GPU) |
| MinerU | 3.4.5 (4.0.0a6 pre) | MinerU Open Source License (Apache-2.0 + MAU/revenue thresholds) / models on HF or ModelScope | 39 base pkgs, `[pipeline]` adds torch, onnxruntime; min 20 GB disk | pipeline: CPU or GPU, 4 GB VRAM, 16 GB RAM; vlm: 8 GB VRAM | yes | yes | yes, with captions and footnotes | HTML | no | fallback B |
| nougat-ocr | 0.1.17 (2023-10-04) | MIT / CC-BY-NC | 25 direct deps incl. transformers | GPU in practice | markdown headings | yes (Mathpix markdown) | no image files | LaTeX tables | no | rejected (stale, NC weights) |
| GROBID | 0.9.1 Docker | Apache-2.0 | `grobid:0.9.1-crf` ~500 MB; `-full` ~8 GB | CRF: CPU, 2 to 4 GB RAM; full: GPU advised | TEI `div`/`head` | coordinates only | coordinates only | coordinates only | yes, F1 0.87 to 0.90, Crossref consolidation | references and header metadata |

## Details with sources

### PDF tools

**poppler (installed).** `pdftotext version 24.02.0`, Poppler Developers, https://poppler.freedesktop.org.
Local check: `/usr/bin/pdftotext`, `/usr/bin/pdfimages`, `/usr/bin/pdftoppm`, `/usr/bin/pdfinfo`.

**pdfplumber.** "Built on pdfminer.six", extracts chars, words, lines, rects, curves, images with
metadata, `extract_table`/`extract_tables`; "Works best on machine-generated, rather than scanned,
PDFs"; no OCR. MIT. https://github.com/jsvine/pdfplumber. PyPI 0.11.10 (2026-06-15), requires
pdfminer.six, pillow, pypdfium2: https://pypi.org/pypi/pdfplumber/json.

**PyMuPDF / pymupdf4llm.** License: "both, open-source AGPL and commercial license agreements"
(https://pymupdf.readthedocs.io/en/latest/about.html); PyPI license field "Dual Licensed - GNU AFFERO
GPL 3.0 or Artifex Commercial License" (https://pypi.org/pypi/pymupdf/json). pymupdf4llm "includes
layout analysis without any GPU requirement"
(https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/); `to_markdown(write_images, image_path,
image_format, embed_images, page_chunks)` with per-chunk `metadata`, `toc_items`, `images`, `tables`
(bbox, row_count, col_count), `graphics`
(https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html). Dry run: 9 packages including
`pymupdf-layout` and `onnxruntime`.

**docling.** "Advanced PDF understanding incl. page layout, reading order, table structure, code,
formulas, image classification"; "Local execution capabilities for sensitive data and air-gapped
environments"; "The Docling codebase is under MIT license. For individual model usage, please refer to
the model licenses found in the original packages" (https://github.com/docling-project/docling
README). Formula enrichment: `do_formula_enrichment` "will analyze the equation formulas in documents and
extract their LaTeX representation", CodeFormula model; enrichments "require extra models executions
which may increase the processing time consistently"
(https://github.com/docling-project/docling/blob/main/docs/usage/enrichments.md). Figure export:
`pipeline_options.images_scale`, `generate_page_images`, `generate_picture_images`,
`element.get_image(conv_res.document).save(fp, "PNG")` for `PictureItem` and `TableItem`,
`save_as_markdown(..., image_mode=ImageRefMode.REFERENCED)`
(https://github.com/docling-project/docling/blob/main/docs/examples/export_figures.py). CPU install:
`pip install docling --extra-index-url https://download.pytorch.org/whl/cpu`
(https://github.com/docling-project/docling/blob/main/docs/getting_started/installation.md). PyPI:
`docling` 2.126.0 (2026-09-04) depends on `docling-slim[standard]`, which pulls docling-core,
docling-ibm-models, docling-parse, huggingface-hub, pypdfium2, pylatexenc, accelerate
(https://pypi.org/pypi/docling/json, https://pypi.org/pypi/docling-slim/json). Dry-run resolution did
not finish in 10 minutes (heavy torch-class resolver), so the exact package count is unverified; the
dependency list above is from PyPI metadata. Model licenses for the layout/TableFormer/CodeFormula
weights: unverified here (the README defers to the model cards).

**marker.** "Formats tables, forms, equations, inline math, links, references, and code blocks";
"Extracts and saves images"; "Works on GPU, CPU, or MPS"; "Our code is licensed under Apache 2.0... Our
model weights use a modified AI Pubs Open Rail-M license (free for research, personal use, and startups
under $5M funding/revenue)"; "Surya auto-spawns the server on first use, and you need vllm (NVIDIA GPU)
or llama.cpp (CPU / Apple Silicon)"; NVIDIA path needs "Docker plus the NVIDIA Container Toolkit";
`--disable_ocr` is "pure text-layer extraction (equations and scanned pages are skipped)"; "Inline math
is converted to LaTeX automatically in balanced mode"; JSON output has `block_type` (Figure, Caption,
Table, Equation, SectionHeader, ...) and `section_hierarchy`; olmocr-bench "Balanced mode scores 76.0%
overall, 83.5% on born-digital PDFs, ahead of MinerU and docling" (self-reported)
(https://github.com/datalab-to/marker README). PyPI 2.0.0 (2026-07-20), requires torch>=2.7,
transformers>=5.12, surya-ocr (https://pypi.org/pypi/marker-pdf/json). Dry run timed out; VRAM need
is not stated in the README (unverified).

**nougat.** "the academic document PDF parser that understands LaTeX math and tables"; output `.mmd`
"mostly compatible with Mathpix Markdown"; models `0.1.0-small` (default) and `0.1.0-base`; "Nougat
codebase is licensed under MIT. Nougat model weights are licensed under CC-BY-NC"; `[MISSING_PAGE]`
false positives "when computing on CPU or older GPUs" (https://github.com/facebookresearch/nougat
README). PyPI `nougat-ocr` 0.1.17 last uploaded 2023-10-04 (https://pypi.org/pypi/nougat-ocr/json).
Compatibility with current transformers 5.x: unverified.

**GROBID.** Extracts header, references (F1 "around .87" PMC, ".90" bioRxiv), "paragraph, section
titles, reference and footnote callouts, figures, tables, data availability statements", TEI output
with PDF coordinates; header-only "less than 2 GB memory", citations "around 3GB", full structures
"around 4GB"; Apache license (https://grobid.readthedocs.io/en/latest/Introduction/). Docker: full image
~8 GB with GPU advised, `grobid/grobid:0.9.1-full`; CRF-only ~500 MB, CPU, 2 GB RAM minimum,
`grobid/grobid:0.9.1-crf` (https://grobid.readthedocs.io/en/latest/Grobid-docker/); both tags verified
with `docker manifest inspect`. `processFulltextDocument` parameters `consolidateHeader`,
`consolidateCitations`, `includeRawCitations`, `teiCoordinates`, `segmentSentences`, `generateIDs`;
consolidation is "an additional external call to CrossRef API or biblio-glutton"
(https://grobid.readthedocs.io/en/latest/Grobid-service/). Coordinates only, format `page,x,y,w,h`, on
`figure`, `formula`, `ref`, `biblStruct`, `persName`, `head`, `s`, `p`
(https://grobid.readthedocs.io/en/latest/Coordinates-in-PDF/).

**MinerU.** "Formulas to LaTeX, Tables to HTML"; "Extract images, image descriptions, tables, table
titles, and footnotes"; "Supports running in a pure CPU environment, and also supports GPU/MPS
acceleration"; hardware table: pipeline "Pure CPU Support" yes, "Min VRAM 4GB", RAM "Min 16GB,
Recommended 32GB or more", disk "Min 20GB"; vlm min VRAM 8 GB, hybrid 2 GB; "MinerU has officially moved
from AGPLv3 to the MinerU Open Source License, a custom license based on Apache 2.0"
(https://github.com/opendatalab/MinerU README). License text: Apache-2.0 plus a separate commercial
license once "monthly active users (MAU) exceed 100 million; or total monthly revenue exceeds USD 20
million", and an online-service attribution duty
(https://github.com/opendatalab/MinerU/blob/master/LICENSE.md). PyPI `mineru` 3.4.5, Python 3.10 to
3.13, `[pipeline]` extra adds torch, torchvision, transformers, onnxruntime
(https://pypi.org/pypi/mineru/json); dry run of the base package: 39 packages. The old `magic-pdf`
1.3.12 (AGPL-3.0, 2025-05-24) is the superseded name (https://pypi.org/pypi/magic-pdf/json).

### arXiv

- Terms of use: "make no more than one request every three seconds, and limit requests to a single
  connection at a time"; may not "Store and serve arXiv e-prints (PDFs, source files, or other content)
  from your servers"; metadata is CC0 (https://info.arxiv.org/help/api/tou.html).
- API: `http://export.arxiv.org/api/query` with `search_query`, `id_list`, `start`, `max_results`;
  "incorporate a 3 second delay"; `max_results` "limited to 30000 in slices of at most 2000 at a time";
  prefixes `ti:`, `au:`, `all:`; Atom entries carry `arxiv:doi`, `arxiv:journal_ref`,
  `arxiv:primary_category`, `link rel` alternate/related (https://info.arxiv.org/help/api/basics.html,
  https://info.arxiv.org/help/api/user-manual.html). Live: `id_list=1706.03762` returned
  `primary_category cs.CL`, published 2017-06-12, v7 updated 2023-08-02.
- Bulk and robots: "use the dedicated site export.arxiv.org... specifically set aside for programmatic
  access"; "bursts at 4 requests per second with a 1 second sleep, per burst"; "Please do not attempt to
  download the complete corpus programmatically" (https://info.arxiv.org/help/bulk_data.html); "arXiv
  monitors activity and will deny access to sites that violate these guidelines"
  (https://info.arxiv.org/help/robots.html); `https://arxiv.org/robots.txt` live: `Crawl-delay: 15`,
  `Disallow: /e-print`, `Disallow: /src`, `Allow: /html`, `Allow: /abs`, `Allow: /pdf`.
- Delivery formats: `/src/` "consistently returns gzipped tar archives regardless of source file
  structure"; `/e-print/` returns single TeX files natively; PDF-only as `application/pdf`
  (https://info.arxiv.org/help/mimetypes.html); "as a gzipped tar file (for downloads consisting of
  multiple files)" or "as a gzipped TeX file (for downloads consisting of a single file only)"
  (https://info.arxiv.org/help/unpack.html). Live: `/e-print/1706.03762` 301 to `/src/1706.03762`;
  `/src/` 200, `application/gzip`, `arXiv-1706.03762v7.tar.gz`, `ETag "sha256:..."`; the same on
  `export.arxiv.org`.
- 00README: `myMainTexFile.tex toplevelfile`, `filename ignore`, JSON form auto-generated for newer
  submissions (https://info.arxiv.org/help/00README.html).
- HTML: `arxiv.org/html/<id>`, LaTeXML conversion, MathML with LaTeX alternative text, beta, not all
  papers convert (https://info.arxiv.org/about/accessible_HTML.html).
- Local tools: `latexpand` and `kpsewhich` at `/usr/bin`; regex smoke test results in the Answer.

### APIs

**Crossref.** "/works/{doi}" returns "metadata for the specified Crossref DOI"; `query.bibliographic`
"useful for citation look up. Includes titles, authors, ISSNs and publication years"; "query.title has
been deprecated"; `select` subsets fields; `rows` default 20, max 1000; "a public, open, and free API
for all" without "API tokens or registration"; polite pool: "any API queries that use HTTPS and have
appropriate contact information will be directed to a special pool", via `?mailto=` or a `User-Agent`
containing `mailto:`; limits advertised in `X-Rate-Limit-Limit` and `X-Rate-Limit-Interval` (doc
example 50 per 1s); back off on slow responses; paid "Plus" tier exists for production SLAs
(https://github.com/CrossRef/rest-api-doc). Live 2026-09-11: `x-rate-limit-limit: 10`,
`x-rate-limit-interval: 1s`, `x-api-pool: polite-single`.

**OpenAlex.** Docs moved from docs.openalex.org to help.openalex.org (301). "OpenAlex data is free, and
so is casual use of the API... To use the API at any real scale, though, you'll want a free API key: it
raises your daily budget 10×"; "Two things return 429 Too Many Requests: exceeding your daily budget, or
making more than 100 requests per second"; key via `api_key=` or `Authorization: Bearer`;
`X-RateLimit-Limit` is "Your total daily budget", `X-RateLimit-Credits-Used` the cost of the request
(https://help.openalex.org/api/authentication.md). Blog: "you'll need an API key for all requests",
"You can still make a few calls without an API key for demo purposes, but it's not suitable for any kind
of production use", "$1 of free usage per day" per key, single work lookup by DOI or ID $0, searches
"$0.001" per call (https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/).
Singleton lookups: `works/https://doi.org/...`, `works/doi:...`, `works/pmid:...`
(https://help.openalex.org/api/get-single-entities.md). Live keyless: 200 with
`x-ratelimit-limit: 1000`, `x-ratelimit-limit-usd: 0.1`, `x-ratelimit-cost-usd: 0.0001` on the first
DOI GET and 0 on repeats; `works/arxiv:1706.03762` 404; `filter=ids.arxiv:` 400 invalid;
`filter=doi:10.48550/arXiv.1706.03762` count 0. The `mailto` polite pool is no longer mentioned in the
new docs (it is harmless to keep sending).

**Semantic Scholar.** Without key: "rate-limited to 1000 requests per second shared among all
unauthenticated users"; with key "1 RPS on all endpoints" introductory; key via form, delivered by email
(https://www.semanticscholar.org/product/api). Graph spec: key goes in header `x-api-key`;
`/paper/{paper_id}`; `/paper/search/match` "intended for retrieval of a single paper based on closest
title match", returns `matchScore` or 404 "Title match not found"; `/paper/batch` POST with
`{"ids": [..., "ARXIV:2106.15928"]}` and `fields` as a query parameter; `/paper/{id}/citations` and
`/references` with `contexts`, `intents`, `isInfluential`
(https://api.semanticscholar.org/graph/v1/swagger.json). Live keyless: HTTP 429 "Too Many Requests...
apply for a key" on the first call.

**Unpaywall.** Live: `GET https://api.unpaywall.org/v2/10.1038/s41586-020-2649-2?email=<address>`
returned `is_oa`, `oa_status`, `title`, `journal_name`, `year`, `best_oa_location` with `url_for_pdf`,
`url_for_landing_page`, `version`, `license`, `host_type`. The product page
(https://unpaywall.org/products/api) is JavaScript-rendered and returned no text to `curl` or the
fetcher; the "100,000 calls per day" and "email required" statements come from secondary pages quoting
it (https://libguides.ucalgary.ca/c.php?g=732144&p=5260801,
https://github.com/api-evangelist/unpaywall), so the daily cap is unverified from primary.

**Europe PMC.** Search at `https://www.ebi.ac.uk/europepmc/webservices/rest/search`; `resultType`
`idlist`, `lite` (default), `core`; formats XML, JSON, DC; covers "articles, preprints and more"; no key,
no rate limit stated (https://europepmc.org/RestfulWebService). Live: `DOI:` and `TITLE:"..."` fields
work; `SRC:PPR AND DOI:10.1101/2020.03.22.002386` returns the preprint (`PPR118574`); `lite` fields
include `doi`, `pmid`-style `id`, `source`, `title`, `authorString`, `journalTitle`, `citedByCount`,
`isOpenAccess`, `inEPMC`, `hasPDF`, `fullTextIdList`. Rate limit "10 requests per second (or 500
requests per minute)" and "The API limit is applied per IP address" (Europe PMC staff reply, 2024-12-11,
https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8): semi-official.

**bioRxiv / medRxiv.** `https://api.biorxiv.org/details/[server]/[DOI]/na/[format]` "returns detail for
a single manuscript"; interval form `details/[server]/[YYYY-MM-DD]/[YYYY-MM-DD]/[cursor]/[format]`;
formats JSON, XML, HTML; "30 papers served in a call"; no rate limit stated
(https://api.biorxiv.org/). Live: three versions of 10.1101/2020.03.22.002386 with the fields listed
above.

### Code

- git: a refspec `<src>` "can also be a fully spelled hex object name" (https://git-scm.com/docs/git-fetch);
  verified `git fetch --depth 1 origin <sha>` and `git clone --filter=blob:none --no-checkout` +
  `checkout <sha>` against github.com/jsvine/pdfplumber (14 MB each).
- pip: `MyProject @ git+https://git.example.com/MyProject.git@<sha>`; "a full hash allows pip to operate
  more efficiently"; pip requests partial clones with Git 2.17+
  (https://pip.pypa.io/en/stable/topics/vcs-support/).
- Python `ast`: `ast.parse`, `ast.walk`, `ast.get_docstring`, `ast.unparse`, `FunctionDef`/`ClassDef`
  fields `name`, `args`, `decorator_list`, `lineno`, `end_lineno` (https://docs.python.org/3/library/ast.html).
- universal-ctags: `--output-format=json` "available only if the ctags executable is built with
  libjansson"; `-R`; `--list-languages`; `--fields` (https://docs.ctags.io/en/latest/man/ctags.1.html).
  Not installed.
- tree-sitter 0.26.0 and tree-sitter-language-pack 1.18.0 on PyPI, both MIT
  (https://pypi.org/pypi/tree-sitter/json, https://pypi.org/pypi/tree-sitter-language-pack/json). Not
  installed.

### Open items

- docling and marker exact installed-package counts (dry-run resolver exceeded 10 minutes): unverified.
- NVIDIA Container Toolkit presence (needed for marker's vLLM server): unverified.
- Unpaywall 100k/day cap: secondary sources only.
- Semantic Scholar keyless access is effectively unavailable at the moment (429 on first call); a free
  key would make it the best title matcher and arXiv-id resolver.
