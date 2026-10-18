# 86 - Passages and the five sections

**What to build:** The paper's five **sections** exist from the project's start and grow with every ticket. The sections are `research/sections/introduction.md`, `results.md`, `discussion.md`, `methods.md`, and `references.md`. `init` writes them, and code renders them after every integration. No model edits them, so BRIEF Section 14 and decision 2 hold as written.

A ticket result gains `passages[]`, each `{section, heading, text, replaces}`, written by the worker who did the work. The ledger keeps them in `research/passages.jsonl` and journals each as `passage`. Each passage has:

- an id, P1 onward;
- `by`, naming a ticket and attempt, the owner, a document, a front-door step, an answered objective, or a consolidation;
- the ticket's `objectives`.

A **finding** is a Results passage. Findings keep `findings.jsonl` and their F ids, and gain `heading`, `replaces`, and `objectives`, so a scope-down replaces the finding it narrows instead of standing beside it.

How a section renders:

- A replaced passage leaves the file and stays in the log.
- When two tickets replace one passage in the same wave, both are kept and the section notes it.
- Within a heading, passages keep their arrival order, and a replacement takes the place of what it replaces.
- Headings keep their first-appearance order until the outline (ticket 104) orders them.
- A worker reuses an existing heading when one fits.

Each kind declares sections. The plan and ticket schemas gain `sections`, set by kind:

- `code` and `experiment` declare Methods;
- `analysis` declares Methods and Results;
- `lit` declares Introduction;
- `writing` declares what it writes;
- every other kind declares none.

A Type-A check at acceptance sends a worker back when a declared section got no passage (for Results, when it got no finding). Sections never enter a touch set. Tickets adding to one section run in the same wave and are integrated one at a time in id order under the ledger lock. A worker's context pack holds, per declared section, its headings with each passage's id and first sentence, plus the owner's passages in full.

The format is Markdown with LaTeX math (`$...$` and `$$...$$`, with a numbered equation written `$$...$$ {#eq:label}`). Each claim sentence ends with a provenance tag that has no space in its locator. Symbols such as σ are written as math. The `res` and `ref` tags are checked as today.

Introduction is seeded at setup by code: from the memo's verified prior work, and from the passages the specify session writes on the gap. Code-written passages (an answered objective's Discussion passage, which ticket 91 writes) go through the same ledger call. The planner no longer cuts a writing ticket after each analysis. A `writing` ticket remains for a scope-down and for work the owner asks for, with an empty touch set that never names `research/`.

Not part of this ticket:

- the `code`, `doc`, and `plot` tags in the linter, the owner's edits taken in through the render stamp, the owner's passages, and the consolidation (88, and `plot` in 100);
- results, their R ids, and the general report (90);
- the outline's ordering of headings (104);
- References' rendering from citations (105);
- inherited passages from documents (93).

**Blocked by:** 81 - Specify and the plan name objectives. It blocks 88, 89, 90, 91, 93, 98, and 107.

**Status:** ready-for-agent

**GitHub:** [#233](https://github.com/Bernaljp/wayline/issues/233) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Sections and passages"; "Vocabulary the build adds": the `passage` schema and event, `result` gaining `passages`, `ticket` and `plan` gaining `sections`); decisions 1 (the layout: `research/sections/`; `init`), 2 (the event table: `passage`), 5 (the conductor's integration, one at a time under the ledger lock), 10 (the planner's cut: no writing ticket after each analysis), 11 (findings gain `heading`, `replaces`, and `objectives`), the schemas list (`passage`, `result`, `ticket`, `plan`); M8 criterion 4; user stories 116, 117, 118.

- [ ] `init` writes the five section files under `research/sections/`, each with a first-line render stamp, and code re-renders them after every integration.
- [ ] A result's `passages[]` (`{section, heading, text, replaces}`) are written through the ledger into `research/passages.jsonl` with ids P1 onward, `by`, and the ticket's `objectives`, and are journaled as `passage`.
- [ ] Findings gain `heading`, `replaces`, and `objectives`. A Results passage is a finding with an F id, and a scope-down's finding replaces the one it narrows.
- [ ] A replaced passage leaves the rendered file and stays in the log. Two replacements of one passage in one wave are both kept and noted in the section. Arrival order within a heading, the replacement's place, and first-appearance heading order hold.
- [ ] The plan and ticket schemas gain `sections`, set by kind as decision 17 lists. A Type-A check at acceptance sends a worker back when a declared section got no passage, or when Results got no finding.
- [ ] Sections never enter a touch set. Tickets adding to one section integrate one at a time in id order under the ledger lock.
- [ ] A worker's context pack holds, per declared section, each heading with its passages' ids and first sentences, plus the owner's passages in full.
- [ ] Introduction is seeded at setup from the memo's verified prior work and the specify session's passages on the gap. Code-written passages go through the same ledger call with their `by`.
- [ ] The planner no longer cuts a writing ticket after each analysis, and a `writing` ticket's touch set is empty and never names `research/`.
- [ ] Tests:
  - the ledger seam over a temporary project: passages and findings written and read back, rendered files asserted on;
  - replayed journals for two tickets adding to one section and two replacing one passage in a wave;
  - the declared-sections check as a Type-A function over a worktree and a result;
  - the context pack asserted on the rendered prompt.
- [ ] The event table of decision 2 and the schemas list gain these rows in the same commit as the code that writes them.
- [ ] The documentation site and `CHANGELOG.md` under `## Unreleased` describe the sections and passages.
- [ ] `python -m unittest` passes.
