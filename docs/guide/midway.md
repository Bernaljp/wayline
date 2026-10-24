# Starting midway

A project can start from work already done: an earlier manuscript, a thesis chapter, a referee report, the code that
made the old results. Hand it over as it is, in any form, during setup or later.

## Documents

A **document** is your own writing handed over: kept as given beside a converted text, under
`research/documents/<id>/` (`D1` onward), recorded in `research/documents.json`, and indexed in
`research/DOCUMENTS.md`. Conversion is by code at every autonomy: `.docx` through pandoc (tracked changes accepted,
equations as LaTeX, comment threads and Mendeley citations read), `.tex` through pandoc, a PDF through `pdftotext`, an
`.xlsx` as one CSV per sheet, a `.doc` through LibreOffice first. A folder is sorted file by file and a `.zip` unpacked.
A newer version of the same text becomes its next version.

Each document has a kind: `inherited` (an earlier manuscript, a separate Methods, a supplement), `critique` (a referee
report, an editor's letter, a collaborator's list of required experiments), `other`, or, for published work including
your own preprints, a reference. The session sorts them and asks only when the kind is unclear. A file dropped on the
dashboard with no session gets code's cautious guess and is never sorted `inherited`.

You can ask about a document: the session sends one question to the consultant, which answers from that document.

## Inherited passages

An inherited document is deconstructed verbatim into **inherited passages** in the sections (Introduction,
Results, Discussion, Methods), each ending with a `{doc:D1#p4.s2}` tag naming where it came from. The title, abstract,
captions, and reference list stay with the document. Each inherited claim stands **unchecked** until a passage or
finding from this project's evidence supports, narrows, or contradicts it, or it is found **unverifiable** with its
reason. Results renders each such claim marked `[unchecked]`.

## Repeated claims

A claim made in several places becomes one passage citing every place. A consistency read and the local embedding
model propose pairs, a confirmer labels each the same, contradicting, or different, and a merge is written only when it
loses nothing and adds no number or citation. You mark the merges (right or split) and the contradictions (real, or
not a contradiction) as batches at setup; standing merges are listed under "Changed without asking you" in the
account. Records: `research/repeats.json`.

## Critiques and concerns

A critique's points, an open comment thread, and an objection of the position memo's hostile review you accept become
**concerns** (`K1` onward), each kept verbatim with every critique that raised it, in `research/CONCERNS.md`. Each is
tied to objectives, kept for the paper order, or declined with a reason; it stays open until answered or declined. At
setup the critic proposes a place for each and you answer `take it` or `another place`. A concern needing a place
after setup is a decision: yours under `interactive` and `checkpoints`; under `autonomous` the decider's, unless you
named `concern` among the human-only classes at intake. At the paper order each project with critiques gets a
response file per critique.

## Verifying what the project inherited

Every inherited result (one inherited Results heading) is recorded in `research/VERIFICATIONS.md` and stays unchecked
until each claim has a verdict or it is unverifiable. At a start midway the critic proposes the objective "Do the
inherited results hold?", and the critic's memo lists the code, data, and software each result needs. Setup's fourth
question asks one question on every missing item (`M1` onward): `as recommended`, one reply for all ("I'll provide
it", "rebuild it", "leave it unverified"), or item by item. Each result gets a verification ticket naming its route:
**reproduction** (the inherited code at its recorded commit), **port** (its logic in another language), or
**reimplementation** (from the inherited Methods), or a read of the reference.

After setup a missing item is a decision of class `material` pausing only that verification: yours under
`interactive` and `checkpoints`, the decider's under `autonomous` (which never answers "I'll provide it"); a
verification that needs a person under `autonomous` makes its result unverifiable.

## Verbs the session runs

`wayline document add <file> --kind inherited` (or `critique`, `other`, `reference`),
`wayline document deconstruct <id>` (with `--place "<heading>=<section>"`), `wayline document move <passage> <section>`,
`wayline document repeats`, `wayline concern split`, `wayline concern place <id> --objective <O>` (or `--order`,
`--decline "<reason>"`), `wayline concern show`, `wayline consult <document id> "<question>"`, and `wayline mark`.
