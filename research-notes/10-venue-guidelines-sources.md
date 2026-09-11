# 10 Venue guidelines sources

Ticket: `.scratch/harness/issues/10-venue-guidelines-sources.md`. Brief: Section 13.3, OPEN-19.
Checked 2026-09-11, via WebSearch to locate each venue's current author-guidelines page and
WebFetch (or, where WebFetch was blocked by a bot check, a fallback fetch tool) to confirm content.
One to two fetches per venue; no template files were downloaded, only their existence and download
URL confirmed. Every claim below carries a source URL; anything not confirmable from a fetched page
is marked "unverified" rather than guessed. Two venues had partial fetch failures, noted inline:
Cell (cell.com returned HTTP 403 to a stateless fetch; its fields come from search-result snippets
of the live page, not a direct fetch, and are flagged) and Genome Biology (the submission-guidelines
page redirects to a Springer login/authorization endpoint; its fields are mostly unverified).

## Answer

| Venue | Guidelines URL | Template without login | Date checked |
|---|---|---|---|
| Nature | https://www.nature.com/nature/for-authors/formatting-guide | Generic Springer Nature LaTeX/Word package only, not Nature-specific: yes | 2026-09-11 |
| Nature Methods | https://www.nature.com/nmeth/submission-guidelines | Not found on nmeth-specific pages: unverified | 2026-09-11 |
| Nature Communications | https://www.nature.com/ncomms/submit/guide-to-authors | No ncomms-specific template found: no (generic Springer Nature package only) | 2026-09-11 |
| Cell | https://www.cell.com/cell/information-for-authors (fetch blocked, HTTP 403; snippet-sourced) | Unverified (page unreachable) | 2026-09-11 |
| Cell Systems | https://www.cell.com/cell-systems/information-for-authors | Yes, https://www.cell.com/information-for-authors/article-templates (Word + LaTeX zip) | 2026-09-11 |
| PNAS | https://www.pnas.org/author-center/submitting-your-manuscript | Yes, Word + LaTeX (incl. Overleaf) at https://www.pnas.org/author-center/submitting-your-manuscript | 2026-09-11 |
| PLOS Computational Biology | https://journals.plos.org/ploscompbiol/s/submission-guidelines | Sample formatting PDFs only, no fillable Word/LaTeX template found: unverified/no | 2026-09-11 |
| eLife | https://elife-rp.msubmit.net/html/elife-rp_author_instructions.html | Yes, LaTeX zip at https://elife-cdn.s3.amazonaws.com/author-guide/elife-latex-template.zip | 2026-09-11 |
| Bioinformatics | https://academic.oup.com/bioinformatics/pages/author-guidelines | Referenced but no direct no-login download link found: unverified | 2026-09-11 |
| Genome Biology | https://genomebiology.biomedcentral.com/submission-guidelines (redirects to Springer login) | Unverified (page unreachable without login) | 2026-09-11 |
| NeurIPS (2026) | https://neurips.cc/Conferences/2026/CallForPapers | Yes, https://media.neurips.cc/Conferences/NeurIPS2026/Formatting_Instructions_For_NeurIPS_2026.zip | 2026-09-11 |
| ICML (2026) | https://icml.cc/Conferences/2026/CallForPapers + AuthorInstructions | Yes, https://media.icml.cc/Conferences/ICML2026/Styles/icml2026.zip | 2026-09-11 |
| ICLR (2027 cycle) | https://iclr.cc/Conferences/2027/AuthorGuidelines | Yes, https://media.iclr.cc/Conferences/ICLR2027/iclr-2027-style-files.zip | 2026-09-11 |
| bioRxiv | https://www.biorxiv.org/submit-a-manuscript | No template mentioned: no | 2026-09-11 |
| arXiv | https://info.arxiv.org/help/submit/index.html | Not linked from this page: unverified | 2026-09-11 |

## Per-venue findings

### Nature
Source: https://www.nature.com/nature/for-authors/formatting-guide (fetched directly; nature.com's
redirect through idp.nature.com is a cookie-consent bot check, not an auth wall).

- Length: physical-sciences Articles ~6 print pages / ~2,500 words + 4 display items; biological/
  clinical/social-sciences Articles ~8 pages / ~4,300 words + 5-6 display items; Methods ≤3,000
  words; up to 50 references "if needed."
- Structure: title, authors/affiliations, bold first-paragraph summary, main text with topical
  subheadings (no mandatory Introduction/Results/Discussion headings, unlike strict IMRAD),
  References, Tables, Figure legends, Methods (with data/code availability), Acknowledgements,
  Funding statement, Author contributions, Competing interests, Additional information.
- Figures: standard widths 90mm (single column) / 180mm (double column), max depth 170mm; Extended
  Data max 10 display items; JPEGs acceptable at initial submission, high-resolution required only
  on acceptance. Color-mode requirement not stated (unverified).
- References: numbered; surname + initials; journal titles italic/abbreviated; volume bold; up to
  50 references.
- Reporting checklist: "Reporting Summary," required for life-sciences and behavioral/social-
  sciences articles, template at https://www.nature.com/documents/nr-reporting-summary-flat.pdf
  (fetched directly, no login redirect, dated April 2023, licensed CC BY 4.0 per its own footer).
- Submission: online system, Word or PDF, up to 30MB; portal name not stated (unverified).
- Template without login: no Nature-specific manuscript template (format-flexible at submission
  by design); a generic, non-journal-specific Springer Nature LaTeX/Word package is downloadable
  without login at https://www.springernature.com/gp/authors/campaigns/latex-author-support/see-where-our-services-will-take-you/18782940.
- License of the guidelines page: "(c) 2026 Springer Nature Limited"; Terms and Conditions at
  https://www.nature.com/info/terms-and-conditions.

### Nature Methods
Source: https://www.nature.com/nmeth/submission-guidelines and
https://www.nature.com/nmeth/submission-guidelines/preparing-your-submission (fetched directly);
length/figure numbers from https://www.nature.com/nmeth/content.

- Length: Articles main text ~3,000 words, expandable to 5,000 with editorial approval (excludes
  abstract, Methods, references, figure legends); abstract ≤150 words, unreferenced; ~50
  references as guidance, not a hard cap.
- Structure: Introduction, Results, Discussion, Online Methods, explicitly named (unlike the main
  Nature journal), each subdivided by topical headings; Extended Data optional, max 10 items.
- Figures: up to 6 figures and/or tables in an Article. Resolution/format/color-mode specifics not
  found on the fetched nmeth pages (unverified).
- References: numbered (Nature Portfolio house style); ~50-reference guideline.
- Reporting checklist: Nature Portfolio "Reporting Summary" is standard across Nature-branded
  journals (same template/license as under Nature above); an nmeth-specific page stating this was
  not successfully fetched, so treat as highly likely but unverified for this specific journal.
- Submission: Manuscript Tracking System at https://mts-nmeth.nature.com/, requires login/
  registration.
- Template without login: not found on nmeth-specific pages (unverified).
- License of the guidelines page: "(c) 2026 Springer Nature Limited"; same nature.com-wide Terms
  and Conditions, Privacy Policy, Legal notice as Nature.

### Nature Communications
Source: https://www.nature.com/ncomms/submit, https://www.nature.com/ncomms/submit/guide-to-authors,
and the linked https://www.nature.com/documents/ncomms-submission-guide.pdf (all fetched directly;
the PDF's own revision stamp reads "Revised May 3rd, 2019" but it is the document currently linked
live from the guide-to-authors page as of this check).

- Length: abstract ~150 words, unreferenced; main text ≤5,000 words; up to 10 display items
  (figures + tables); guideline of up to 70 references; Methods typically ≤3,000 words.
- Structure: title (≤15 words), authors, abstract, main text with Results/Methods subheadings,
  References, Acknowledgements (optional), Author contributions, Competing interests, Materials
  and Correspondence, Tables, Figures, Data availability statement (separate section after
  Methods, before References), Code availability statement.
- Figures: RGB color, ≥300 dpi; Arial or Helvetica typeface; avoid red/green contrast (use
  colorblind-safe recoloring, avoid rainbow scale); legends <350 words each; preferred vector
  formats .ai/.eps/.pdf/.ps/.svg, layered .psd/.tif, bitmap .psd/.tif/.png/.jpg; high-resolution
  not required at initial submission.
- References: numbered, one publication per reference number, include cited title.
- Reporting checklist: Nature Portfolio "Reporting summary" required for life-sciences, behavioral/
  social-sciences, and ecological/evolutionary/environmental-sciences articles (same template as
  Nature, CC BY 4.0, no login); plus an "editorial policy checklist" and, for central custom code,
  a "code and software submission checklist." Forms must be opened in Adobe Reader for fillable
  fields.
- Submission: Manuscript Tracking System at https://mts-ncomms.nature.com/ (login required); cover
  letter optional, used only for confidential information not shared with referees.
- Template without login: no ncomms-specific template; the generic Springer Nature package (see
  Nature) is the only no-login option found.
- License: "(c) 2026 Springer Nature Limited" page footer; all content published open access since
  January 2016 under CC BY 4.0.

### Cell
Source: identified via WebSearch as https://www.cell.com/cell/information-for-authors; both this
page and its linked STAR Methods Guide PDF returned HTTP 403 on every direct fetch attempt
(including via web.archive.org, which was blocked outright). Fields below are sourced from
WebSearch result snippets that quote or paraphrase the live page, not from a direct fetch, and are
flagged as such per field.

- Length (snippet-sourced, unverified by direct fetch): Articles capped at 7,000 words, including
  main figure legends but excluding STAR Methods text, supplemental legends, and references; no
  more than 7 figures/tables.
- Structure (snippet-sourced): STAR Methods (Structured, Transparent, Accessible Reporting)
  format, no character limit on STAR Methods, encouraged but not mandatory at initial submission;
  presubmission inquiry option via cellms@cell.com.
- Figures: resolution/format/color mode not surfaced by any snippet (unverified).
- References (snippet-sourced): numbered, superscript in-text citations, standardized Cell Press
  house style since October 2022; "et al." only after 10 authors.
- Reporting checklists: not confirmed from any source (unverified).
- Submission (snippet-sourced): optional presubmission inquiry to cellms@cell.com, or Cell Press
  Multi-Journal Submission for cross-journal consideration; formatting need not be finalized at
  initial submission. Portal software name not confirmed (unverified).
- Template without login: unverified (both candidate pages unreachable).
- License of the guidelines page (snippet-sourced): "Copyright (c) 2026 Elsevier Inc., its
  licensors, and contributors. All rights are reserved, including those for text and data mining,
  AI training, and similar technologies." Terms and Conditions at
  https://www.cell.com/terms-and-conditions permit personal, non-commercial print/download only,
  no redistribution or derivative works.
- Note: Cell Systems (below), a sister Cell Press journal, was reachable via a Firecrawl fallback
  and its https://www.cell.com/information-for-authors/article-templates and
  https://www.cell.com/information-for-authors/figure-guidelines pages (site-wide, so applicable to
  Cell too) confirm a Cell Press LaTeX/Word template and detailed figure specs exist without login;
  these are recorded under Cell Systems and are very likely to apply to Cell as well, but this is
  an inference, not a direct confirmation for the Cell-specific page, so it is not upgraded out of
  "unverified" here.

### Cell Systems
Source: https://www.cell.com/cell-systems/information-for-authors and its subpages
(submit-manuscript, revise-manuscript, article-types, journal-policies), plus the site-wide
https://www.cell.com/information-for-authors/figure-guidelines and
https://www.cell.com/information-for-authors/article-templates. Fetched via a Firecrawl fallback
after direct WebFetch/curl hit a Cloudflare challenge page.

- Length: no explicit total word cap; guidance is "long enough to accurately convey the work...
  short enough to read in one sitting." Title ≤~145 characters; Summary/abstract ≤150 words.
  Figure/table counts by article type: Articles ≤7, Reports ≤4, Brief Reports 2, Methods ≤7,
  Methods in Brief 2.
- Structure: title, author list, affiliations/footnotes, contact information, summary, keywords,
  Introduction, Results, Discussion, Resource availability (lead contact, materials availability,
  data and code availability), Acknowledgments, Author contributions, Declaration of interests,
  Declaration of generative AI use (if applicable), Supplemental information titles/legends,
  Figure titles/legends, Tables, STAR Methods (mandatory), Resource identification initiative,
  References.
- Figures: max counts above; resolution color/grayscale ≥300 dpi, black-and-white ≥500 dpi, line
  art ≥1,000 dpi at final print size; RGB; production formats TIFF/PDF/EPS/JPEG; fonts embedded,
  Arial; max 20MB per file.
- References: numbered, sequential by first citation, in-text numbered superscript; "et al." only
  after 10 authors.
- Reporting checklists: Cell Press's own checklists (battery, photovoltaic-cell, catalysis;
  strongly encouraged, PDF); ARRIVE recommended for animal studies; a clinical-trial checklist PDF
  is offered. No mandatory MDAR/PRISMA-style checklist found on Cell Systems pages specifically.
- Submission: Editorial Manager at editorialmanager.com/cell-systems; initial submission as PDF (or
  Word plus separate files), LaTeX requires an accompanying PDF, files kept small (1-2MB each,
  20MB total); cover letter required (background, conceptual advance, significance/impact,
  consortium status, may suggest/exclude reviewers); Cell Press Multi-Journal Submission option
  available.
- Template without login: yes, Word templates and a Cell Press LaTeX template (.zip with
  .tex/.bib/.bst/.sty) downloadable directly from
  https://www.cell.com/information-for-authors/article-templates, e.g.
  https://www.cell.com/pb-assets/journals/platform/authour-resources/cell-press-latex-template-1747231785383.zip,
  no login prompt encountered.
- License of the guidelines page: same Elsevier footer as Cell ("Copyright (c) 2026 Elsevier Inc.,
  its licensors, and contributors...").

### PNAS
Source: https://www.pnas.org/author-center/submitting-your-manuscript (Firecrawl fallback after a
Cloudflare challenge blocked direct fetch) and https://www.pnas.org/author-center.

- Length: Research Reports preferred 6 pages (~4,000 words, ~50 references, 4 medium graphical
  elements), max 12 pages. Brief Reports ≤3 pages (~1,600 words, ≤15 references). Perspectives
  ≤10 pages. Letters/Author Responses ≤500 words, ≤2 graphical elements, 10-11 references.
  Abstract ≤250 words; Significance Statement ≤120 words.
- Structure: title page, abstract, significance statement (Direct/Contributed submissions only),
  main text (Introduction, Results, Discussion, Materials and methods), Acknowledgments and
  funding, References, Figure legends.
- Figures: no fixed max count (typical 6-page article has ~4 graphical elements). Size classes
  small ~9x6cm, medium ~11x11cm, large ~18x22cm. Resolution: raster 300ppi (no text)/600-900ppi
  (with text)/1000-1200ppi (line art); vector similarly 300-1200dpi; RGB; formats TIFF, EPS, PDF,
  PPT (3D: PRC/U3D).
- References: numbered in order of first citation; style per *Scientific Style and Format: The
  CSE Manual* (8th ed.); more than 5 authors listed as first author "et al."; dedicated LaTeX
  bibliography style file pnas-new.bst.
- Reporting checklists: ARRIVE guidelines required for animal studies; MIAME checklist required
  for genomic/proteomic high-throughput data deposits. No PRISMA/CONSORT explicitly named on the
  pages checked (unverified for clinical trials/systematic reviews specifically).
- Submission: PNAS's own tracking system at https://www.pnascentral.org/cgi-bin/main.plex; no
  email submissions; format-neutral at initial submission; requires data-sharing plan, funding
  info, and >=3 suggested reviewers/Board/NAS members. Cover letter not mentioned as required on
  this page (unverified whether one is required elsewhere).
- Template without login: yes, Word templates (Research article, Brief Report, SI Appendix) and
  LaTeX templates (main .tex, .cls, .sty, .bst, plus Overleaf versions), e.g.
  https://www.pnas.org/pb-assets/authors/PNASTemplateforMainManuscript-1755285180130.docx and
  https://www.pnas.org/pb-assets/authors/PNAS-template-main-1764608845890.tex, no login prompt
  encountered.
- License of the guidelines page: "Copyright (c) 2026 National Academy of Sciences. All rights
  reserved. | Online ISSN 1091-6490," with a link to "Terms and Privacy Policy."

### PLOS Computational Biology
Source: https://journals.plos.org/ploscompbiol/s/submission-guidelines and
https://journals.plos.org/ploscompbiol/s/figures (fetched directly).

- Length: "Manuscripts can be any length. There are no restrictions on word count, number of
  figures, or amount of supporting information." Abstract ≤300 words; Author Summary 150-200
  words. Software Article submissions specifically: less than 3,500 words.
- Structure: title, authors, affiliations, abstract, author summary, Introduction, Results,
  Discussion, Materials and Methods, Acknowledgments, References, Supporting Information captions.
  Results and Discussion may be combined.
- Figures: no max count. Format: TIFF or EPS only. Resolution 300-600 dpi. Dimensions: width
  789-2250px (2.63-7.5in at 300dpi), height max 2625px. Color: RGB (8-bit/channel) or grayscale
  only. Fonts: Arial/Times/Symbol, 8-12pt. Max 10MB per file.
- References: "Vancouver" style per ICMJE, numbered citation-sequence, in-text numbers in square
  brackets, first six authors then "et al." No explicit reference-count cap.
- Reporting checklists: STARD (diagnostic accuracy), STROBE (observational studies), MIAME
  (microarray), CONSORT + TIDieR (clinical trials), ARRIVE (animal research), PRISMA checklist +
  flow diagram (systematic reviews/meta-analyses), STROBE-MR (Mendelian randomization), COREQ/SRQR
  (qualitative research), all named with links to blank template checklists.
- Submission: own online system ("Submit Now"), single compiled PDF (text + figures) at initial
  submission; cover letter uploaded separately, must address suitability/impact, may suggest an
  Academic Editor; >=4 potential reviewers requested; bioRxiv direct-transfer option available.
- Template without login: sample formatting PDFs exist ("sample title/author/affiliations page,"
  "sample manuscript body") linked with no login prompt, but these are formatting samples, not
  fillable Word/LaTeX manuscript templates. No dedicated LaTeX/Word template comparable to PNAS's
  or eLife's was found (unverified whether one exists beyond the separate LaTeX guidelines page).
- License of the guidelines page: footer states "PLOS is a nonprofit 501(c)(3) corporation" with
  Privacy Policy / Terms of Use links; the page references PLOS's licensing/copyright policy and
  CC BY, but the exact footer wording for CC BY was not captured verbatim (unverified for exact
  wording; PLOS's general CC BY 4.0 publishing policy is well known but not confirmed on this
  specific page's footer text).

### eLife
Source: https://elife-rp.msubmit.net/html/elife-rp_author_instructions.html ("Author Guide,"
fetched directly, HTTP 200, no login required).

- Length: Research Articles have no maximum but authors are asked to try to stay under 5,000
  words in the main text (excluding Methods/References/figure legends); no limit on display items.
  Short Reports ≤1,500 words, ≤3-4 display items. Review Articles up to ~10,000 words (up to 8
  figures for longer reviews). Feature Articles advised <2,000 words, ≤2 display items, ≤20
  references.
- Structure: Introduction, Results, Discussion, Materials and Methods (or Methods, which may
  follow the Introduction where appropriate), Acknowledgements, References, Figures (legend below
  each), Tables.
- Figures: no multi-page figures or figure supplements; minimum 300 dpi; minimum physical width
  10cm (20cm if full-page-width, still 300 dpi); RGB color space; minimize whitespace; Colour
  Universal Design principles recommended for accessibility.
- References: any reference style/manager output accepted (APA suggested as closest match); all
  references reformatted in production; DOIs requested where possible; no stated citation-count
  limit for Research Articles (Feature Articles advised <=20 references).
- Reporting checklists: MDAR checklist (Materials Design Analysis Reporting), downloadable as PDF
  (https://elife-cdn.s3.amazonaws.com/xpub/guides/eLife_MDAR_checklist.pdf) and Word, required for
  relevant methodological details (sample-size estimation, replicates, statistical reporting);
  also a Key Resources Table template (docx) and an "Inclusion in Global Research" form.
- Submission: direct submission or preprint transfer from bioRxiv/medRxiv (also accepts Review
  Commons submissions); eLife peer-reviews preprints and publishes a "Reviewed Preprint"
  (assessment + public reviews + optional author response) rather than issuing an accept/reject
  decision; a Version of Record can be requested later. Publishing fee $3,750 as of July 1, 2026
  (waivers available). Cover letter required for Review Articles and Replication Studies, and for
  disclosing certain exceptions (data-sharing exceptions, preregistration); not a blanket
  requirement for Research Articles.
- Template without login: yes, LaTeX template zip at
  https://elife-cdn.s3.amazonaws.com/author-guide/elife-latex-template.zip (also referenced as
  https://cdn.elifesciences.org/author-guide/elife-latex-template.zip); DOCX/RTF also accepted.
- License of the guidelines page: hosted on the Aries/eJournalPress platform (footer references a
  platform software patent notice, not a content license); links to eLife's own Terms and
  Conditions (https://elifesciences.org/terms) and Privacy Policy (https://elifesciences.org/privacy).
  Content itself: eLife articles/Reviewed Preprints are published under CC BY 4.0, per statements
  on this same page.

### Bioinformatics (Oxford University Press)
Source: https://academic.oup.com/bioinformatics/pages/author-guidelines and
https://academic.oup.com/bioinformatics/pages/General_Instructions (fetched directly).

- Length: Original Papers up to 7 pages (~5,000 words, excluding figures); Application Notes up to
  4 pages (~2,600 words, or ~2,000 words plus one figure); Reviews 3-8 pages (~3,000-6,000 words
  excluding figures). Manuscripts exceeding the stated limit by 20% or more are typically returned
  without review.
- Structure: machine-learning papers must include a dedicated subsection describing the
  composition of the training dataset; software papers must include an "Availability and
  Implementation" section; a data availability statement is required for all papers.
- Figures: no max count, resolution, format, or color-mode requirement found (unverified).
- References: citation format (numbered vs. author-date) not stated on the fetched pages
  (unverified); only dataset-citation format (per DataCite recommendations) is specified.
- Reporting checklists: none named (no ARRIVE/MIQE equivalent found); the journal instead requires
  a data availability statement and, for ML papers, the training-dataset subsection above.
- Submission: online portal at http://mc.manuscriptcentral.com/bioinformatics (ScholarOne, login
  required); a cover letter is mandatory, must justify suitability for the journal, disclose
  related publications/preprints, and explain how the submission differs from them.
- Template without login: unverified. The guidelines reference "the journal template" and state
  accepted manuscripts should be Word or LaTeX files, but no direct, no-login download link was
  found on either fetched page.
- License of the guidelines page: states published papers are made available under CC BY as part
  of open-access publishing agreements; this is a publishing-license note, not an explicit
  statement about reuse of the guidelines page text itself.

### Genome Biology (BioMed Central / Springer Nature)
Source attempted: https://genomebiology.biomedcentral.com/submission-guidelines, which 301-redirects
to https://link.springer.com/journal/13059/submission-guidelines, which itself returned a 303
redirect to an idp.springer.com login/authorization endpoint on repeated attempts. **This page
could not be retrieved without login**, so per the ticket's instruction most fields are marked
unverified rather than sourced from a WebSearch snippet.

- Guidelines URL: as above (redirects to a Springer login gate).
- Length limits: unverified (a WebSearch snippet suggested no hard limit but this is not
  confirmed against a fetched page).
- Structure: unverified (a WebSearch snippet mentioned an "Availability of data and materials"
  section, competing-interest declarations, and non-publication-elsewhere confirmation, but this
  is a search snippet, not a direct fetch).
- Figures: unverified.
- References: unverified.
- Reporting checklists: unverified (a WebSearch snippet referenced a "BioMed Central Minimum
  Standards of Reporting Checklist," not confirmed by direct fetch).
- Submission steps: unverified (portal not confirmed; historically BMC/Springer journals use their
  own online system, but no URL was confirmed here).
- Template without login: unverified.
- License of the guidelines page: unverified (page could not be fetched).
- Action item for a future check: retry with an authenticated browser session or a different
  fetch path (e.g., Google cache, or BioMed Central's own biomedcentral.com domain directly rather
  than the link.springer.com mirror) to convert these from unverified to sourced.

### NeurIPS (2026 cycle)
Source: https://neurips.cc/Conferences/2026/CallForPapers and
https://neurips.cc/public/guides/PaperChecklist (fetched directly).

- Length: the CFP page defers page-limit detail to a linked "Main Track Handbook," not directly
  fetched. The style-file formatting instructions (per search results, not independently fetched
  as a PDF) specify papers may be up to 9 pages including figures, with acknowledgments,
  references, the paper checklist, and optional appendices not counted toward that limit --
  **mark the 9-page figure unverified by direct fetch of the CFP page itself.**
- Structure: no fixed section list on the CFP page beyond requiring the NeurIPS Paper Checklist
  (mandatory, embedded in the LaTeX style file; omitting it is grounds for desk rejection).
- Figures: unverified (not stated on either fetched page).
- References: unverified (not stated on the fetched pages).
- Reporting checklist: NeurIPS Paper Checklist, required in every submission, does not count
  toward the page limit. It covers: claims accuracy, limitations, theory/proofs, reproducibility,
  code/data access, experimental details, statistical significance, compute resources, ethics
  compliance, broader impacts, safeguards, licenses, asset documentation, human subjects, IRB
  approval, and LLM-usage declaration.
- Submission: OpenReview, https://openreview.net/group?id=NeurIPS.cc/2026/Conference. 2026 dates:
  abstract submission May 4, 2026 (AoE), full paper submission May 6, 2026 (AoE), author
  notification September 24, 2026 (AoE).
- Template without login: yes,
  https://media.neurips.cc/Conferences/NeurIPS2026/Formatting_Instructions_For_NeurIPS_2026.zip,
  direct .zip, no login wall encountered.
- License of the guidelines page: no copyright/CC notice found; only a cookie-usage disclaimer in
  the footer ("NeurIPS uses cookies for essential functions only. We do not sell your personal
  information.").

### ICML (2026 cycle)
Source: https://icml.cc/Conferences/2026/CallForPapers and
https://icml.cc/Conferences/2026/AuthorInstructions (fetched directly).

- Length: main paper 8 pages at submission (9 pages at camera-ready); references, impact
  statement, and appendices unlimited; submission PDF size cap 50MB, camera-ready cap 20MB.
- Structure: mandatory Impact Statement at the end of the paper (before references, not counted
  toward the page limit; generic boilerplate permitted when impacts are well established); a Lay
  Summary required separately at camera-ready; a conflict-of-interest disclosure paragraph
  required as the last paragraph of the introduction at camera-ready; double-blind anonymization
  required at submission.
- Figures: no max count or resolution/DPI stated; vector graphics (EPS or PDF) preferred for
  plots, bitmap permitted for illustrations that cannot be vectorized. Color mode unverified.
- References: specific citation format not stated; guidance covers content practices (replace
  arXiv citations with peer-reviewed versions where possible, correct bibliographic
  capitalization). No citation-count limit found.
- Reporting checklists: no named checklist equivalent to NeurIPS's Paper Checklist found; an
  ethics review/flagging process exists, and camera-ready requires the conflict-of-interest
  paragraph noted above.
- Submission: OpenReview, https://openreview.net/group?id=ICML.cc/2026/Conference, via the Author
  Console. 2026 dates: account-creation deadline January 8, 2026; abstract deadline January 23,
  2026 AoE; full paper deadline January 28, 2026 AoE. Accepted papers publish through PMLR and
  require a PMLR Publication Agreement.
- Template without login: yes, https://media.icml.cc/Conferences/ICML2026/Styles/icml2026.zip,
  direct .zip, no login wall encountered.
- License of the guidelines page: no copyright/CC statement found; links out to a Privacy Policy
  and a yearly Code of Conduct document rather than stating a license for the guidelines text.

### ICLR (2027 cycle)
Source: https://iclr.cc/Conferences/2027/AuthorGuidelines (fetched directly; this was the current
canonical page for the next open cycle at time of check).

- Length: main text 9 pages or fewer at submission, increased to 10 pages during discussion/
  rebuttal and camera-ready. References do not count toward the page limit and are unlimited.
  Appendices (after the bibliography) may be any length, though reviewers are not required to read
  them.
- Structure: no fixed section list mandated; requires a mandatory AI-use statement (not counted
  toward the page limit) and mentions an optional ethics statement (max 1 page, not counted) and
  an optional reproducibility statement (not counted).
- Figures: no max count, resolution, or color-mode requirements stated (unverified).
- References: no specific citation style or citation-count limit stated on the guidelines page
  itself (the style is set by the LaTeX style file rather than this page; ICLR's style files
  conventionally use natbib author-date citations, but this is unverified as the exact style from
  this page alone). Self-citations should use third-person narrative.
- Reporting checklists: no downloadable checklist template linked; only a recommended (not
  required) "reproducibility statement" as a text section.
- Submission: OpenReview, https://openreview.net/group?id=ICLR.cc/2027/Conference; submit paper
  plus supplementary material as a single file.
- Template without login: yes,
  https://media.iclr.cc/Conferences/ICLR2027/iclr-2027-style-files.zip, no login requirement
  indicated. No Word template mentioned.
- License of the guidelines page: no copyright or terms-of-use statement found (unverified); no
  statement on this page about the licensing policy for accepted papers' content (unverified).
- Other notable policy: authorship cap of 20 papers per author this cycle, plus reviewing-quota
  requirements tied to number of submissions.

### bioRxiv
Source: https://www.biorxiv.org/submit-a-manuscript (fetched directly).

- Length: no explicit length limit specified on the page (unverified beyond that absence).
- Structure: not addressed as a section-by-section outline; the page instead describes required
  metadata (title, abstract, full author list with affiliations, corresponding-author contact
  details, funding sources, competing-interests declaration).
- Figures: accepted formats JPEG, TIFF, EPS, PowerPoint; explicitly incompatible formats PICT,
  Bitmap, Excel, PSD. No max figure count, resolution, or color-mode requirement stated.
- References: not addressed on this page (unverified).
- Reporting checklists: the site runs "a basic screening process for offensive and/or non-
  scientific content and for material that might pose a health or biosecurity risk." No specific
  named checklist or downloadable checklist/template file is linked from this page (there is a
  separate Screening Procedures page at
  https://connect.biorxiv.org/news/2022/06/13/screening_procedures found in search results but not
  fetched -- unverified whether it adds more).
- Submission: authors must first register on the site and supply an institutional affiliation.
  Manuscript deposited as a single PDF (text + figures/tables) or as a Word file plus separate
  figure files, from which bioRxiv generates a single PDF. Submission system at submit.biorxiv.org.
- Template without login: no Word/LaTeX template mentioned as available on this page.
- License: authors choose a posting license from CC BY, CC BY-NC, CC BY-ND, CC BY-NC-ND, CC0, or
  "no reuse" (author retains copyright in all cases). No explicit copyright/terms-of-use statement
  found for the guidelines page's own content (unverified).

### arXiv
Source: https://info.arxiv.org/help/submit/index.html and
https://info.arxiv.org/help/license/index.html (fetched directly).

- Length: no explicit limit stated; submissions must be "topical and refereeable scientific
  contributions that follow accepted standards of scholarly communication." Essentially no page/
  word limit.
- Structure: no mandated section list beyond requiring title/abstract metadata and, for TeX
  submissions, a `\documentclass` directive and an identified top-level TeX file.
- Figures: accepted formats PostScript/EPS (for LaTeX processing) or JPEG, GIF, PNG, PDF (for
  PDFLaTeX processing); mixing formats within one submission is not allowed; figures must be
  embedded (arXiv does not accept submissions with omitted figures or external figure links). No
  max figure count, resolution, or color-mode requirement stated.
- References: not specified (unverified); arXiv has no house citation style, left to the author/
  target journal.
- Reporting checklists: none mentioned.
- Submission: arXiv's own web submission system ("Version 1.5" as described on the page): upload
  files (individually or as zip/tar.gz), select compiler and top-level TeX file, review
  auto-detected file issues, preview compiled PDF, then a metadata page before final submission.
  Submissions received by 14:00 US Eastern typically go public around 20:00 Eastern. All
  submissions undergo moderation for topicality/appropriateness; new users or those submitting to
  a new category may need an endorsement.
- Template without login: no LaTeX/Word template linked from this specific guidelines page
  (unverified whether one exists elsewhere on arXiv's help site without login).
- License: author-selectable per-article license -- CC BY 4.0, CC BY-SA 4.0, CC BY-NC-SA 4.0,
  CC BY-NC-ND 4.0, arXiv's own perpetual non-exclusive license 1.0, or CC Zero (public domain). For
  all options except CC Zero, the original copyright holder retains ownership; the submission page
  states authors "must grant arXiv.org an irrevocable license to distribute the work" regardless of
  the chosen reuse license. Article metadata (not the article itself) is separately released under
  CC0 1.0. No explicit copyright/terms-of-use statement found for the guidelines page's own content
  (unverified).

## Proposed `guidelines/<venue>/` file layout

Per Section 13.3, `guidelines/<venue>/` holds, per venue: format limits, required structure,
reporting checklists, reference style, figure specifications, submission steps, and the source
URLs plus the date they were checked. Proposed layout, one directory per venue (slug form, e.g.
`guidelines/nature-methods/`, `guidelines/plos-compbio/`, `guidelines/neurips/`):

```
guidelines/<venue>/
  guidelines.json      # machine-readable extraction, schema below
  source.md            # human-readable notes: what was fetched, what is unverified, caveats
  checklist/           # cached copies of any downloaded reporting-checklist templates
    <name>.pdf | .docx # only checklist forms, not manuscript templates (avoid redistributing
                        # publisher manuscript templates verbatim; link to them instead)
```

`guidelines.json` schema (one object per venue):

```json
{
  "venue": "plos-compbio",
  "display_name": "PLOS Computational Biology",
  "guidelines_url": "https://journals.plos.org/ploscompbiol/s/submission-guidelines",
  "date_checked": "2026-09-11",
  "length_limits": {
    "word_count": null,
    "page_count": null,
    "abstract_word_count": 300,
    "notes": "No restriction on word count, figures, or supporting information; software articles <3500 words."
  },
  "required_structure": ["Title", "Authors", "Affiliations", "Abstract", "Author Summary",
    "Introduction", "Results", "Discussion", "Materials and Methods", "Acknowledgments",
    "References", "Supporting Information captions"],
  "figure_spec": {
    "max_count": null,
    "formats": ["TIFF", "EPS"],
    "min_dpi": 300, "max_dpi": 600,
    "color_mode": ["RGB", "grayscale"],
    "max_file_size_mb": 10
  },
  "reference_style": {"style": "Vancouver (ICMJE, numbered)", "max_count": null},
  "reporting_checklists": ["STARD", "STROBE", "MIAME", "CONSORT+TIDieR", "ARRIVE", "PRISMA",
    "STROBE-MR", "COREQ/SRQR"],
  "submission_steps": ["single compiled PDF", "cover letter", ">=4 suggested reviewers",
    "bioRxiv direct-transfer option"],
  "template": {"latex_or_word_no_login": false, "url": null, "notes": "sample formatting PDFs only"},
  "license_of_summary_source": {"statement": "unverified exact CC BY wording on this page",
    "url": "https://journals.plos.org/ploscompbiol/s/submission-guidelines"},
  "verification": {"fully_verified_fields": ["length_limits", "required_structure", "figure_spec",
    "reference_style", "reporting_checklists"], "unverified_fields": ["license_of_summary_source"]}
}
```

`source.md` per venue records, in prose, the same caveats as this research-notes file's per-venue
section above (fetch method, any blocked pages, any snippet-only fields), so a future refresh knows
exactly what to re-check first.

## Mechanical checks the writer can run

Given a drafted manuscript (Markdown or LaTeX source, one file or a directory) and a
`guidelines.json` for the target venue, the writer step (13.3) can run these checks without a model
call, all driven off `guidelines.json`'s structured fields:

1. **Word/page count.** Strip markup (LaTeX commands, Markdown syntax), count words in the main
   text (defined as everything between the abstract and the references, or between named section
   markers), compare against `length_limits.word_count` / `page_count` with the venue's own
   exclusions (e.g. Methods excluded for Nature, STAR Methods excluded for Cell family). Flag if
   over. For LaTeX, page count can be estimated with a dry compile against the venue's official
   style file when downloaded.
2. **Section presence.** Check that every heading in `required_structure` appears (case-insensitive
   substring match on section headings, or LaTeX `\section{}` / Markdown `#`/`##` names), and flag
   missing ones. Where the venue is structure-flexible (e.g. Nature's continuous-narrative style),
   this check is skipped or downgraded to a warning rather than a hard fail, driven by a
   `structure_flexible: true` flag added to `guidelines.json` for those venues.
3. **Figure count and format.** Count figure environments/includes; compare to
   `figure_spec.max_count` when set. Where figure files are available, check file format against
   `figure_spec.formats`, check image DPI against `min_dpi`/`max_dpi` (via an image-metadata read,
   e.g. Pillow/ImageMagick `identify`), check color mode (RGB vs CMYK) via the same tool, and check
   file size against `max_file_size_mb`.
2b. **Legend length.** Where a venue caps figure-legend length (e.g. Nature Communications <350
   words), count words per legend block and flag overruns.
4. **Reference style and count.** Detect whether the bibliography is numbered or author-date (by
   inspecting the `.bib`/`.bbl` output or the reference-list formatting) and compare to
   `reference_style.style`; count total references against `reference_style.max_count` when set.
5. **Reporting checklist presence.** If `reporting_checklists` is non-empty and the manuscript
   claims a matching study type (animal study, clinical trial, systematic review, machine-learning
   training set, etc., detected via keyword search or a cheap classification pass), check that a
   corresponding checklist file exists in the submission package; flag if missing.
6. **Template conformance.** If `template.latex_or_word_no_login` is true and the manuscript is
   LaTeX, check that the document class / style file matches the one named in `template.url`
   (e.g. `\documentclass{neurips_2026}` for NeurIPS); flag mismatches.
7. **Provenance cross-check.** Per 13.4, every claim sentence in the draft must already carry a
   provenance tag; that linter is separate from this ticket but the two can share the same
   sentence-classification pass so length/structure/figure checks and claim-tagging checks run in
   one file walk instead of two.

All of the above are Type-A mechanical checks (no model call needed beyond the shared sentence
classifier reused from 13.4); only the reporting-checklist study-type detection in (5) plausibly
benefits from a cheap classification call, and even that can start as a keyword heuristic.
