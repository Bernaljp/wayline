# 104 - The outline

**What to build:** The owner can see the shape of the paper at any time, long before anything is written. Code alone builds `research/OUTLINE.md` at every render, with no model tokens, from the objectives, the results, every section's headings, the concerns, the inherited passages and what checks them, and the venue once one is named. In order it gives:

- a storyline: the objectives in outline order with their status, results, standing, and answer;
- the gaps: what the outline names that holds nothing yet. An empty main-text Gaps list is the paper order's test of complete;
- Introduction: its headings, then the objectives as the paper's questions;
- Results: one subsection per objective, the critic's `first` leading, then by id. Each result shows its id, heading, standing, its findings and headline plots counted, its concerns, the inherited claims it decides, the contradictions it resolves, and its measure. Then "Beyond the objectives" and "Inherited, checked by no objective";
- Discussion: each answered objective's passage, the owner's headings, and the parked objectives as future work;
- Methods: its headings;
- the venue block once a venue is named: its `required_structure` mapped to the sections by `check_structure`'s word matching, with the parts no section feeds listed as made at the order;
- Supplement and Cut;
- "Proposed, not settled": merges of results whose headings sit close under one objective, found by the local embedding model, and inherited headings no objective checks;
- the concerns for the order.

The outline has no figures: each result lists its headline plots by id.

The owner changes the outline by talking or by editing the file: moving lines, placing one under Supplement or Cut, adding a `Note:` line, or adding a heading to Introduction, Discussion, or Methods. Code takes the edit in like a section edit, through the file's render stamp. `research/outline.json`, written by the ledger and journaled as `outline`, holds only what the owner set, and that always wins:

- code never moves a placed line;
- new lines go after the placed ones, marked new;
- a placed line whose item is gone is listed once;
- a note is carried through a merge or a reframe.

Renaming or merging a result changes the result, not the outline. A new Results subsection that needs work is offered as an objective. Before the order, the sections render their headings in the outline's order. Whatever is placed in Supplement or Cut still renders, at the end of its section under a marker. A worker's context pack gains its objective's outline entry with the owner's notes, and a consolidation follows the outline. Each merge proposal is an item in a batch (79), with the marks take or decline. Under `autonomous` the decider settles the open proposals in the session that judges the order (120), never moving a line the owner placed.

Not part of this ticket:

- binding the paper to the outline at the order: outline ids as pandoc attributes, the order and placement check, and `check_structure`'s order check on a venue that is not `structure_flexible`. 115 owns these;
- Methods' parameter table line and the Methods-to-code gaps, which 108 adds;
- the dashboard's outline editor (113) and the outline's place in the Paper view (111).

**Blocked by:**
- 75 - The harness's tools (the embedding model)
- 79 - Batches and marks
- 90 - Results and the general report
- 93 - Inherited passages
- 96 - Critiques and concerns

It blocks 105, 108, 111, 112, 113, and 115.

**Status:** ready-for-agent

**GitHub:** [#251](https://github.com/Bernaljp/wayline/issues/251) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (the outline; sections and passages: heading order and the owner's edit; documents, critiques, and concerns: what each session reads; vocabulary the build adds: the `outline` event, the `outline` schema, the conversation's outline verb), 1 (the verb table), 2 (the event table), the schemas list; milestone M8 criterion 8; user stories 134 and 135.

- [ ] `research/OUTLINE.md` is rendered by code at every render, with no launch, in the order above. Each part reads the records it names: objectives, results, section headings, concerns, inherited passages, and the venue when one is named.
- [ ] The Gaps list names each outline line that holds nothing yet, and it is empty for a project whose every main-text line has content.
- [ ] Results groups by objective: the critic's `first` leads, then the rest by id. "Beyond the objectives" and "Inherited, checked by no objective" follow. Each result line carries its id, heading, standing, counts, headline plot ids, concerns, the inherited claims it decides, and its measure.
- [ ] Discussion lists each answered objective's passage, the owner's headings, and the parked objectives as future work.
- [ ] With a venue named, the venue block maps `required_structure` to the sections through `check_structure`'s word matching and lists the parts no section feeds as made at the order.
- [ ] `research/outline.json` is written only through the ledger and journaled as `outline`, and holds only what the owner set.
  - A placed line never moves in later renders.
  - New lines follow the placed ones, marked new.
  - A placed line whose item is gone is listed once.
  - A `Note:` survives a merge and a reframe of its item.
- [ ] An owner's edit of `OUTLINE.md` is taken in before the next render, using the render stamp. That covers a moved line, a line placed under Supplement or Cut, a `Note:` line, and a heading added to Introduction, Discussion, or Methods. Lines that arrived since the stamp are never read as removed.
- [ ] The conversation's outline verb makes the same changes as a file edit and journals the same `outline` event.
- [ ] The five sections render their headings in outline order. A heading placed under Supplement or Cut renders at the end of its section under a marker.
- [ ] A worker's context pack holds its objective's outline entry with the owner's notes.
- [ ] Merge proposals come from the local embedding model (no tokens) over the headings of results under one objective. Each is an item in a batch with the marks take or decline, and taking one merges the results.
- [ ] Tests, over a temporary project through the ledger seam:
  - the render from fixture objectives, results, sections, concerns, and inherited passages, asserted on the file written;
  - each kind of owner edit, made by editing the rendered file and rendering again;
  - placements surviving a new result, a merge, and a reframe;
  - the embedding model through the tool runner's recordings.
- [ ] The verb table of decision 1 gains the outline verb, the event table of decision 2 gains `outline`, and the schemas list gains `outline`, all in the same commit as the code.
- [ ] The changelog's `## Unreleased` section describes the outline and how the owner changes it.
- [ ] `python -m unittest` passes.
