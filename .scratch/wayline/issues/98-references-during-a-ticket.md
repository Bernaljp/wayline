# 98 - References during a ticket

**What to build:** A worker cites only works that exist, for what they say. A ticket result gains `references[]`, each `{identifier, note}`: a DOI, an arXiv id, or an exact title. A URL is never looked up. The note is kept on the dossier with the ticket's id, and the scout never reads it. The list holds every work the ticket drew on, and a work enters References only by being cited.

Workers have no network, so they check a work mid-ticket with `wayline scout <identifier>`. It is code with no tokens, counted under `WAYLINE_TICKET` and capped at 20 calls a ticket, and it is given to the coder, analyst, experimenter, writer, and surveyor. It files the L0 dossier at once and prints the slug, details, and abstract. On a service failure it files an unresolved dossier with the `retry` flag. On no such work it files nothing. It follows the outcomes and cache rule that "71 - The scout's outcomes, cache, and joins" built.

A `ref` tag names a work by slug or by identifier (`{ref:doi:10.1038/...#abstract}`, `{ref:arxiv:1802.03426#abstract}`), mapped through position's identifier index, and passages are never rewritten.

At acceptance, a Type-A check confirms every cited work is a dossier or in `references`. The scout runs free on the rest. "No such work" sends the worker back as most likely invented, and a service failure accepts with the flag. The locator must name what the dossier holds at its level: `abstract` or `metadata.<field>` at L0 and L1, an entry's locator at L2. A claim beyond the abstract says only what it says, or proposes the work's promotion. Dossiers stay at L0 when cited, and decision 9's promotion triggers stand.

A `dossier` ticket has no worker session: the conductor runs it as a promotion through `absorb`, and the reader keeps the L1 skim. `proposals.KIND_ROLE` loses its `dossier` and `lit` routes.

Not part of this ticket:

- `wayline scout search`, the surveyor, and `lit` tickets, which are "99 - The surveyor and lit tickets";
- rendering `references.md` and `references.json`, and raising important unresolved references, which are "105 - References rendered and important ones raised".

**Blocked by:** 71 - The scout's outcomes, cache, and joins; 86 - Passages and the five sections. It blocks 99 and 105.

**Status:** ready-for-agent

**GitHub:** [#245](https://github.com/Bernaljp/wayline/issues/245) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (A reference found during a ticket; The scout's outcomes, cache, and joins: the check at acceptance as a caller); Implementation Decision 1 (the verb table: `scout <identifier>`); Implementation Decision 9 (dossiers, the scout, absorb, promotions); Implementation Decision 14 (the policy table: the scout's cap of 20 calls a ticket); the schemas list (`result` gains `references`); M8 criterion 11; user stories 143 and 144.

- [ ] The `result` schema gains `references[]` of `{identifier, note}`. A URL identifier is refused, and each note is kept on its dossier with the ticket id.
- [ ] `wayline scout <identifier>` runs from inside a worker with no network of its own, counted per `WAYLINE_TICKET` and refused past 20 calls. It files the L0 dossier and prints slug, details, and abstract; files an unresolved dossier with `retry` on a failure; and files nothing on no such work. The coder, analyst, experimenter, writer, and surveyor roles get it.
- [ ] `ref` tags accept a slug or a `doi:` or `arxiv:` identifier, resolved through position's identifier index, and inherited citations are identifier tags with no locator.
- [ ] At acceptance, the Type-A check runs the scout on every cited work that is neither a dossier nor listed. No such work sends the worker back, a service failure accepts with the flag, and a locator beyond what the dossier's level holds is sent back.
- [ ] A `dossier` ticket is run by the conductor as an `absorb` promotion with no worker session, and `KIND_ROLE` has no `dossier` or `lit` route.
- [ ] Tests through the fetch seam's recordings (found, no match, a 503 failure, the cap) and the ledger seam over a temporary project for the acceptance check; journal replay for a `dossier` ticket run as a promotion.
- [ ] Decision 1's verb table gains `scout <identifier>`, decision 14's policy table the per-ticket cap, and the schemas list `result.references`, each in the same commit as its code.
- [ ] The documentation site describes `wayline scout` for workers.
- [ ] `python -m unittest` passes.
