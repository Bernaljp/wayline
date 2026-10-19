# 94 - Consulting one document

**What to build:** The consultant answers from one dossier or **one document**. Every document kept by "84 - Documents in: converting and keeping a project's documents" is chunked like an L2 source, so a session that needs a fact from the owner's earlier manuscript, a separate Methods, or a critique can ask `wayline consult` about it. It gets an answer with block-anchored locators in that document, exactly as it does for a reference at L2. The consultant's limits and its log are unchanged.

Not part of this ticket:

- the `read` route of a verification, which batches a reference's claims for the consultant and is "97 - Verifying inherited results".

**Blocked by:** 84 - Documents in: converting and keeping a project's documents. It blocks 97.

**Status:** done

**GitHub:** [#241](https://github.com/Bernaljp/wayline/issues/241) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Documents, critiques, and concerns: "Every document is chunked like an L2 source for the consultant, which now answers from one dossier or one document"); Implementation Decision 9 (the consultant); M8 criterion 9; user story 136.

- [x] Each kept document is chunked the way an L2 source is, under the existing `chunk_max_chars`, from its `text.md` and its block anchors, and the chunks are rebuilt when a newer version is taken in.
- [x] `wayline consult` accepts a document id as well as a dossier slug. The answer's locators name the document's block anchors, and the exchange is logged and counted against the ticket's question limit as today.
- [x] A document id that is unknown, or a document with no text yet, is refused with a one-line reason.
- [x] Tests on the ledger seam over a temporary project with the synthetic documents of ticket 78, with the consultant scripted through the fake launcher: chunking, an answer with document locators, the log, the limit, and the refusals.
- [x] Decision 1's verb table row for `consult` names the document form in the same commit.
- [x] `python -m unittest` passes.
