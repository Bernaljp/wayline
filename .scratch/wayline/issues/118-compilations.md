# 118 - Compilations

**What to build:** The venue-free paper becomes files the owner can submit, made by code alone through pandoc. A **compilation** produces:

- LaTeX, with the venue's class where one is vendored or a plain article otherwise;
- the PDF, through `latexmk` (xelatex for Unicode);
- a `.docx` with native equations;
- a Markdown copy.

Citations go through citeproc with the venue's CSL style, vendored under `guidelines/<venue>/` from the Citation Style Language styles and named in `reference_style`. A BibTeX venue gets a `.bib` from `references.json`. pandoc-crossref resolves equation and figure references. A Lua filter turns `ref` tags into citations and strips every other tag, so a `doc` tag never reaches the output. The venue's checks run on the real output, so page and template checks become real.

When the paper exceeds a limit, one fresh fitting writer session (about $3) cuts text or moves it to the supplement without adding a claim. A Type-A check confirms that every claim tag is still in the paper and that no number changed. Citations over `max_count` are dropped first from Introduction sentences that cite several works, and never a reference a result or a method rests on.

Every paper gets `research/paper/compilations/plain/`, and a named venue gets `compilations/<venue>/`. Compiling for another venue later is a compilation alone, confirmed by a card. Before compiling, the order asks the scout live once more about every unresolved cited work and never cites one still unresolved.

Not part of this ticket:

- the dashboard's downloads and the card for another venue as buttons, which are 121's;
- the scout's outcomes and retry flag themselves, which are 71's.

**Blocked by:** 71 - The scout's outcomes, cache, and joins; 75 - The harness's tools; 115 - The paper order and the paper's parts. It blocks 120 and 121.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (The paper order and what it compiles: a compilation; Converting documents: out; The scout's outcomes, cache, and joins: the order's last retry; Vocabulary the build adds: the compilation's form of `paper`), 13 (venues, guidelines), 1 (the verb table: the compilation's form of `paper`); M8 criterion 17; user stories 160, 161, 162.

- [ ] A compilation writes LaTeX with a vendored venue class or a plain article, a PDF through `latexmk` with xelatex, a `.docx` with native equations, and a Markdown copy, all through the tool runner's recorded executables in tests.
- [ ] Citations render through citeproc with the CSL named in the venue's `reference_style`, vendored under `guidelines/<venue>/`; a BibTeX venue gets a `.bib`; pandoc-crossref resolves `{#eq:label}` and figure references.
- [ ] The Lua filter turns `ref` tags into citations and strips `res`, `code`, `doc`, and `plot` tags; no tag text survives in any output.
- [ ] The venue's checks run on the compiled output (page count, template); a paper over a limit gets one fitting session, and a Type-A check fails a fitted paper missing a claim tag or with a changed number; over `max_count`, multi-citation Introduction sentences lose citations first and no reference a result or method rests on is dropped.
- [ ] Every order writes `compilations/plain/`; a venue writes `compilations/<venue>/`; compiling for another venue later runs only the compilation, behind a card.
- [ ] Before compiling, every unresolved cited work is looked up live once through the scout; one still unresolved is not cited, following the batch's answer (dropped, or its claim kept marked "to be resolved").
- [ ] Tests: the tool runner's recordings carry pandoc out, `latexmk`, and pandoc-crossref; the fetcher's recordings carry the last retry finding one work and failing on another; the fake launcher scripts the fitting session; the verb table of decision 1 gains the compilation's form in the same commit; CHANGELOG `## Unreleased` names compilations.
- [ ] `python -m unittest` passes.
