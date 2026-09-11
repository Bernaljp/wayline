# 06 — Dossier inventory for non-arXiv PDFs and keyless literature APIs

Type: research
Status: resolved
Blocked by: None
Brief: Section 7.3, scout.py; fog: the dossier inventory for non-arXiv PDFs

## Question

1. For a non-arXiv PDF, which locally installable, keyless tools give the best mechanical inventory (sections, numbered equations as LaTeX, figures with captions as image files, tables, algorithms, theorems, appendices)? Candidates: `pdftotext` (installed), PyMuPDF, pdfplumber, marker-pdf, nougat, docling, GROBID (docker), MinerU. For each: install footprint, GPU or CPU cost on this machine (one RTX 3090, 128 cores), license, and fidelity on equations and figure extraction. Recommend a primary and a fallback, and say which inventory fields they populate reliably versus which need a model pass.
2. For arXiv papers: the e-print source fetch (URL form, rate policy, tarball layout) and a LaTeX inventory approach (`\label`, `figure`, `equation`, `algorithm`, `theorem` environments, `\input` resolution).
3. Keyless metadata and citation-existence APIs: arXiv API, OpenAlex, Crossref, Semantic Scholar Graph, Unpaywall (email only), Europe PMC, bioRxiv API: rate limits, polite-pool rules, fields returned, and which one to try first for a DOI, a title, or an arXiv id.
4. For code dossiers: cloning at a pinned commit and a mechanical symbol inventory (Python via `ast`; fallbacks for other languages).

Deliverable: `research-notes/06-pdf-inventory-and-keyless-apis.md` with a recommended chain and the inventory JSON fields it supports.

## Answer

- Non-arXiv PDFs: always run the poppler text layer (`pdftotext -layout`, `pdfinfo`, `pdfimages -list`) plus pdfplumber (MIT) for char and table boxes; primary structural converter is docling (MIT, pip-only, CPU or CUDA, lossless JSON with per-item page/bbox, figures and tables to PNG, `do_formula_enrichment` for LaTeX); fallback A is marker 2.0 on the GPU (Apache code, OpenRAIL-M weights, needs a vLLM Docker inference server; its CPU mode skips equations); fallback B is MinerU `pipeline` (custom Apache-based license, 4 GB VRAM, 16 GB RAM, 20 GB disk). GROBID CRF Docker (Apache, 500 MB, CPU) is the only tool that parses references into structured entries; it returns coordinates, not images or LaTeX. nougat rejected (CC-BY-NC weights, last release 2023-10). PyMuPDF is AGPL, so optional only.
- Reliable mechanical fields: text layer, page count, raw images, section headers, figure files with linked captions, table cells, structured references. Model or reader pass required: equation LaTeX (OCR-derived, never "exact"), equation numbers (regex on adjacent `(N)`), algorithm and theorem boundaries (regex on headings), appendix labeling, figure meaning.
- arXiv: `https://export.arxiv.org/src/<id>vN` always returns a gzipped tar (`/e-print/` 301s to `/src/`); one request per 3 s, single connection, mailto in User-Agent, cache by ETag, never republish the source (ToU). Main file via `00README` `toplevelfile` or `\documentclass` grep; `latexpand` (installed) flattens `\input`; regex the environments (verified on 1706.03762); exact equation and figure numbers from the `.aux` `\newlabel` lines after one `pdflatex` run; `arxiv.org/html/<id>` (LaTeXML, MathML with LaTeX alttext) as the second source.
- DOI: Crossref `/works/{doi}?mailto=` (polite pool, live 10 req/s) then OpenAlex `works/doi:` (keyless budget now about USD 0.10 per day, 100 rps, free key gives 10x) then Unpaywall (email required) then Europe PMC (biomed, 10 rps per IP, semi-official). Title: Crossref `query.bibliographic` then OpenAlex `search=` (USD 0.001 per search) then Europe PMC `TITLE:`. arXiv id: arXiv API `id_list` first; Semantic Scholar `ARXIV:` only with a key (keyless probe got 429 on the first call); OpenAlex has no arXiv id lookup. bioRxiv/medRxiv: `api.biorxiv.org/details/{server}/{doi}/na/json`.
- Code: `git clone --filter=blob:none --no-checkout` + `checkout <sha>` (verified against GitHub, also `fetch --depth 1 origin <sha>`); Python inventory with stdlib `ast` (verified on pdfplumber: 20 modules, 89 symbols), entry points from `pyproject.toml` via `tomllib`; other languages via universal-ctags JSON or tree-sitter-language-pack (MIT), neither installed yet.
- Full write-up with sources and the comparison table: `research-notes/06-pdf-inventory-and-keyless-apis.md`.
