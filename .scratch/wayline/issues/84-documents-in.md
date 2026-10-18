# 84 - Documents in: converting and keeping a project's documents

**What to build:** The owner hands over their own writing in any form, and the project keeps it as a **document**: converted, sorted, recorded, and indexed so that every later session can find its way in. Published work, preprints included, stays a reference.

Conversion is code at every autonomy:

- A `.docx` goes through pandoc (the conda-forge build ticket 75 installs). Pandoc keeps the headings, writes every equation as LaTeX, and accepts tracked changes. A small standard-library reader beside it decodes Mendeley Cite citations into CSL-JSON and reads comment threads with their anchors.
- A `.tex` goes through pandoc.
- A PDF is converted only when no source exists, through `pdftotext -layout` with margin line numbers stripped. Docling adds structure where it is installed.
- An `.xlsx` is read by the standard library, one CSV per sheet.
- LibreOffice only turns a `.doc` into a `.docx`.

Without pandoc, a `.docx` is kept but flagged as not converted.

Each document lives under `research/documents/<id>/`:

- `source/` and `media/`, both gitignored;
- `text.md`, with LaTeX math and block anchors;
- `comments.json`;
- `citations.json`, as CSL-JSON;
- its tables as CSV.

It is recorded in `research/documents.json`: the id, title, kind, version, each file's sha256, the converter and its version, what the conversion lost, and the conversion damage counted. It is journaled as `document`. `research/DOCUMENTS.md`, rendered by code and capped at 20,000 characters, gives each document's:

- kind, version, losses, and counts;
- abstract, for an inherited one;
- headings, with locators and first sentences.

The sort has three kinds:

- `inherited`: an earlier manuscript, a separate Methods, a supplement, or a thesis chapter;
- `critique`: a referee report, an editor's letter with points, or a collaborator's list of required experiments;
- `other`: read only.

The session sorts each document through `wayline document add <file> --kind <kind>`, asking in one line only when the kind is unclear. A file dropped on the dashboard with no session gets code's cautious guess instead: an identifier makes it a reference, review markers make it a critique, and anything else is `other`, never `inherited`. Per text, one version is inherited: the newest, in its source format. A newer version handed over later is recorded as the document's next version. A folder is sorted file by file, and a `.zip` is unpacked first. A PDF sorted as a reference becomes that reference's source, and any other local file is a document. The intake wording tells the owner to hand over anything in any form: references as bare identifiers, the owner's plan as the plan, and a collaborator's list of experiments as a critique.

Not part of this ticket:

- deconstructing an inherited document into passages, and taking a newer version in like a section edit (93);
- the consultant answering from one document (94);
- splitting critiques into concerns, and Word comment threads becoming concerns (96);
- the Inherited view on the dashboard (111).

**Blocked by:** 75 - The harness's tools; 78 - The synthetic start-midway project. It blocks 93, 94, and 96.

**Status:** ready-for-agent

**GitHub:** [#231](https://github.com/Bernaljp/wayline/issues/231) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Documents, critiques, and concerns": documents and their sort; "Converting documents"; "Vocabulary the build adds": the `document` schema and event, the conversation's verb for documents); decisions 1 (the verb table: `document add`), 2 (the event table: `document`), 10 (intake's wording), the schemas list (`document`); M8 criterion 9; user stories 101, 136, 175.

- [ ] A `.docx` from the synthetic start-midway project converts through pandoc with its headings, every equation as LaTeX, and tracked changes accepted. The standard-library reader writes its Mendeley citations as CSL-JSON in `citations.json` and its comment threads with anchors in `comments.json`.
- [ ] A `.tex` converts through pandoc. A PDF with no source converts through `pdftotext -layout` with margin line numbers stripped, with docling's structure where installed. An `.xlsx` becomes one CSV per sheet. A `.doc` becomes a `.docx` through LibreOffice first.
- [ ] Each document is kept under `research/documents/<id>/` with `source/` and `media/` gitignored. It is recorded in `research/documents.json` with its id, title, kind, version, each file's sha256, its converter and version, its losses, and its damage counts, and is journaled as `document`.
- [ ] `research/DOCUMENTS.md` renders from the record with each document's kind, version, losses, counts, abstract (inherited only), and headings with locators and first sentences, and stays at or under 20,000 characters on a project with many documents.
- [ ] `wayline document add <file> --kind inherited|critique|other` records the session's sort. A dashboard drop with no session gets code's cautious guess (identifier: reference; review markers: critique; otherwise `other`), and never `inherited`.
- [ ] One version per text is inherited, the newest in its source format. A folder is sorted file by file, and a `.zip` is unpacked first. A PDF sorted as a reference becomes the reference's source, gitignored.
- [ ] Intake's wording tells the owner to hand over anything in any form.
- [ ] Tests, over the synthetic documents in `fixtures/` (nothing of PINF):
  - the tool runner's recordings of pandoc, `pdftotext`, LibreOffice, and docling;
  - the ledger seam over a temporary project for the record, the event, and the render cap;
  - the dashboard drop's guess over HTTP.
- [ ] The verb table of decision 1, the event table of decision 2, and the schemas list gain these rows in the same commit as the code that writes them.
- [ ] The documentation site and `CHANGELOG.md` under `## Unreleased` describe handing over documents.
- [ ] `python -m unittest` passes.
