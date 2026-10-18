# 96 - Critiques and concerns

**What to build:** A referee report, an editor's letter with points, or a collaborator's list of required experiments is a **critique**, sorted so by "84 - Documents in: converting and keeping a project's documents". Its points become **concerns** that the work must answer or decline with a reason. They live in `research/concerns.json`, written through the ledger, rendered as `research/CONCERNS.md`, and journaled as `concern`. Each has an id K1 onward and records:

- its sources (critique, locator, verbatim text);
- the inherited passages it targets;
- its objectives, or "for the order";
- its status (`open`, `answered`, or `declined`) with the answer or the reason.

One Sonnet session at medium per batch of critiques splits them. Code checks the verbatim spans. Praise and summary are left out, a two-point item is split, near-identical points from different critiques merge with every source, and targets are chosen among the inherited claims. An open Word comment thread becomes a concern by code. An objection from the position memo's hostile review that the owner accepts at the grill becomes a concern with the memo as its source.

At setup, the critic's memo ties concerns to objective rows, or proposes "for the order" or a decline. The grill settles them in groups: one question per proposed objective with its concerns, one for the order, and one for the declines. Specify drafts only when every concern is sorted. Concern placements are also items in a batch of "79 - Batches and marks" (take it, or another place).

Code answers a concern when every objective tied to it is answered and every inherited claim it targets is replaced or withdrawn. A concern follows a reframe. When its objective drops, it goes back to be sorted inside the same "Objective changes" answer that "91 - Objective changes" built. After setup, a concern that needs sorting is a decision ticket: the owner's, or under `autonomous` the decider's (tie, for the order, or decline with a reason; a new objective only if handed `objective`), unless the owner named `concern` human-only at setup.

Who reads what:

- the critic gets `DOCUMENTS.md` and every concern inlined, its tools reaching `research/documents/`;
- the grill, specify, the planner, and the writer at the order read the index and the concerns;
- a worker's context pack carries the concerns of its ticket's objectives.

Not part of this ticket:

- the concerns' lines in the outline, which are "104 - The outline";
- responses per critique at the order, which are "117 - Builds at the order";
- the Inherited view, which is "111 - Dashboard: the Paper and Inherited views".

**Blocked by:** 79 - Batches and marks; 80 - The front door reads objectives; 84 - Documents in: converting and keeping a project's documents; 93 - Inherited passages. It blocks 97, 104, 109, 111, 112, and 117.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Documents, critiques, and concerns; How objectives change as results come in: a dropped objective's concerns; Setup, at every autonomy); Implementation Decision 10 (the critic, the grill, specify, the decider's human-only classes: `concern`); Implementation Decision 2 (the event table: `concern`); the schemas list (`concern`); M8 criterion 9; user story 139.

- [ ] `research/concerns.json` holds concerns with ids K1 onward, never reused, written only through the ledger, journaled as `concern`, and rendered as `CONCERNS.md`. The `concern` schema validates every record.
- [ ] One Sonnet session at medium per batch of critiques splits them. Code checks each span is verbatim in its source, praise and summary are left out, two-point items split, near-identical points from different critiques merge with all sources, and targets are inherited passages.
- [ ] An open Word comment thread in `comments.json` becomes a concern by code. A resolved thread does not.
- [ ] An accepted hostile-review objection from the grill becomes a concern with the memo as its source.
- [ ] The critic's memo ties each concern to an objective row, or proposes "for the order" or a decline. The grill asks one question per proposed objective, one for the order, and one for the declines. Specify refuses to draft while a concern is unsorted. The placements also form one batch of ticket 79.
- [ ] Code marks a concern answered when its tied objectives are all answered and its targets all replaced or withdrawn. It follows a reframe, and returns to sorting when its objective drops, inside the "Objective changes" answer.
- [ ] After setup, an unsorted concern opens a decision ticket. Under `autonomous` the decider answers it (tie, for the order, or decline with a reason; a new objective only if handed `objective`) unless `concern` is human-only. `concern` is accepted as a `human_only` class at intake.
- [ ] The critic, the grill, specify, the planner, and the writer read `DOCUMENTS.md` and the concerns, and a worker's context pack carries the concerns of its ticket's objectives.
- [ ] Tests on the ledger seam over a temporary project with the synthetic critique of ticket 78, with the splitter, critic, and decider scripted through the fake launcher, plus journal replay for the after-setup decision ticket under each autonomy and the drop re-sort.
- [ ] Decision 2's event table gains `concern`, the schemas list `concern`, and decision 10's human-only classes `concern`, each in the same commit as its code.
- [ ] The CHANGELOG's `## Unreleased` entry and the documentation site describe critiques and concerns.
- [ ] `python -m unittest` passes.
