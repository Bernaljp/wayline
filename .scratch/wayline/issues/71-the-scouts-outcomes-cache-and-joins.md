# 71 - The scout's outcomes, cache, and joins

**What to build:** A passing outage no longer leaves a project's references broken. Every lookup attempt the scout makes records one of three outcomes: **found**, **no match** (the service answered and nothing matched), or **failed** (an error status, a timeout, or an unreadable answer). "No such work" now means every service asked answered no match. Any failed attempt on a work not found sets the dossier's `retry` flag (service, failure, date).

The cache under `research/.cache/scout/` replays an answer only for a work already found, at every caller: absorb at L0, the tick's retry, and (when they land) `wayline scout`, the check at acceptance, and the order's last retry. Every lookup about a work not yet found goes to the network, and only successful answers are written. The plot-gallery crawl keeps only successful answers too. The suite's recorded fixtures still replay failures, because they are recordings, not the cache.

When arXiv's API fails, the scout reads the `arxiv.org/abs` page's meta tags and records the arXiv DOI `10.48550/arXiv.<id>` as an attempt of its own. A work found that way keeps the `retry` flag, so the API fills in the rest later. Flagged references are retried at most once a day by whatever runs next (an absorb, or the tick while a run is live), and the flag gives up after 7 days.

A lookup never takes back what a dossier knows. It replaces the lookup's own fields (`existence`, `resolved_by`, `identifiers`, `metadata`, `abstract`, `open_access`, `attempts`) only when it finds the same work. It keeps the level, the L1 fields, the `l2` record, `created`, and the node's level, and sets `updated`. It journals a level 0 `absorbed` only for a new dossier or a changed existence. A failure or no match leaves a found dossier as it was. A dossier at L1 or above that now resolves to a different work is left as it was, and the disagreement goes to absorb's report.

One work has one dossier. After a lookup, absorb matches by DOI, arXiv id, or published DOI, and a second reference to a filed work joins it, recording every way it was named. Where two dossiers exist for one work, the higher level stays (the older on a tie) and the other becomes a pointer with its notes moved.

Intake records references as `{identifier, note}` and never looks them up. `INTAKE.md` renders each as a top-level item with the note nested under it, and absorb reads only top-level items, so a nested remark is never looked up. A local file is never a title query: a PDF sorted as a reference becomes its source, and a path alone is never sent to a service.

The owner hands over a DOI or an exact title (back to the scout) or a PDF (the reference's source, gitignored; the scout tries its title, and failing that the dossier is found with `resolved_by: owner` and its details read from the PDF) through one verb, recorded without asking. "Leave it" settles the item until the order. The dossier schema gains `retry`, `resolved_by: owner`, notes, and the names a joined dossier records. No model tokens are spent; OpenAlex at USD 0.001 a request stays the only paid lookup.

The spec puts this ticket in v1.1.0's first wave with no blockers, ahead of `wayline scout`, the check at acceptance, and the order's live retry.

Not part of this ticket:

- `wayline scout <identifier>` and `wayline scout search` for workers, the `references` result field, and the check at acceptance (98, 99);
- which unresolved references are important, and how they are raised under each autonomy (105);
- the account's Library line for a dossier that now resolves to a different work (89 renders it from what this ticket records);
- the order's last live retry (118).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 98 and 118.

**Status:** ready-for-agent

**GitHub:** [#218](https://github.com/Bernaljp/wayline/issues/218) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (the scout's outcomes, cache, and joins; a reference found during a ticket, for the intake shape; build order), 9 (the scout, the dossier), 1 (the verb table: the hand-over verb), 2 (the event table: `absorbed` at level 0), the schemas list (`dossier` gains `retry`, `resolved_by: owner`, notes, joined names); M8 criterion 12, and criterion 20's reference items for the live run; user stories 146, 147.

- [ ] Each lookup attempt records `found`, `no match`, or `failed`; "no such work" is returned only when every service asked answered no match; a failed attempt on a work not found sets `retry` with service, failure, and date.
- [ ] The cache replays an answer only for a work already found, at every caller; a lookup about a work not yet found goes to the network; only successful answers are written to the cache; the plot-gallery crawl keeps only successful answers.
- [ ] When arXiv's API fails, the abs page's meta tags are read and the arXiv DOI is recorded as its own attempt; a work found that way keeps the `retry` flag; a recorded 503 beside the abs page is covered.
- [ ] A flagged reference is retried at most once a day by the next absorb or by the tick while a run is live, and the flag gives up after 7 days (the give-up recorded on the dossier); the 7 days land in the policy table of decision 14 in the same commit.
- [ ] A lookup replaces only the lookup's own fields and only when it finds the same work; the level, L1 fields, `l2`, `created`, and node level survive; `updated` is set; `absorbed` at level 0 is journaled only for a new dossier or a changed existence; a failure or no match leaves a found dossier untouched; an L1+ dossier resolving to another work is left as it was and reported by absorb.
- [ ] Two references to one work (by DOI, arXiv id, or published DOI) give one dossier recording every name; two existing dossiers for one work collapse to the higher level (older on a tie) with the other a pointer carrying its notes.
- [ ] Intake records references as `{identifier, note}` with no lookup; `INTAKE.md` nests the note under its top-level item; absorb reads only top-level items; a nested remark and a path-only PDF are never looked up.
- [ ] The owner's hand-over verb takes a DOI, an exact title, a PDF, or "leave it", recorded without asking; a PDF becomes the reference's gitignored source, its title tried by the scout, else the dossier is found with `resolved_by: owner` from the PDF's details. The verb is a function the dashboard can call in-process, and its row lands in decision 1's verb table in the same commit.
- [ ] The dossier schema gains `retry`, `resolved_by: owner`, notes, and joined names, in the schemas list in the same commit.
- [ ] Tests through the fetch seam with synthetic recorded fixtures: the three outcomes, a cache that never writes a failure, the abs-page fallback with a recorded 503, the daily retry and the seven-day give-up under a fake clock, a found dossier never downgraded, two references to one work joined, a nested remark and a path-only PDF never looked up, the hand-over verb's four forms.
- [ ] The changelog names the change under `## Unreleased`, and the documentation site's scout page describes the outcomes and the retry.
- [ ] `python -m unittest` passes.
