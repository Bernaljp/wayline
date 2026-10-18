# 120 - The decider orders the paper under autonomous

**What to build:** An autonomous run can end with a paper the owner never had to order by hand. One setup question decides whether the decider judges the paper order, and for which venue; the default is yes with no venue.

The decider judges only at the stopping rule's own ends, after the run-end gates and the drawings. It never judges after `budget_spent`, `stall_strict`, `stopped`, or `switched`. Code checks first:

- no objective the rule names is open;
- the last kill argument passed or its scope-downs are done;
- the outline has no main-text gap;
- every changed result is drawn;
- at a start midway, "Do the inherited results hold?" is answered.

Only when all of these pass does one decider session on `opus max` read `REPORT.md`, `OBJECTIVES.md`, and `OUTLINE.md` and either order the paper or write why not.

When it orders, the decider answers the order's batch: the figure plan, oversized figures (split, never drop), contradictions, unverifiable claims, unresolved references, and the outline's open proposals. It settles the open proposals in the same session and never moves a line the owner placed. It chooses among the writer's titles and alternatives. Each choice is listed under "Decided for you" in the account. A paper that does not pass its three builds stops under "Waiting on you".

Not part of this ticket:

- the order itself, which is 115's (with its figures, builds, compilations, and code steps in 116 to 119);
- the run-end gates, which are 103's.

**Blocked by:** 103 - The run-end gates; 116 - Figures at the order; 117 - Builds at the order; 118 - Compilations; 119 - Code at the order. It blocks 122.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (The paper order and what it compiles: under `autonomous`; The outline: the decider settles open proposals; The account: Decided for you; Setup, at every autonomy; Vocabulary the build adds: the paper order's setup answer in `harness.json`), 10 (the decider), 1 (`harness.json`); M8 criteria 17 and 19; user stories 157, 172.

- [ ] Setup under `autonomous` asks one question, default yes with no venue, recorded in `harness.json`; the schema gains the key in the same commit.
- [ ] The decider is considered only at `objectives_closed`, `goal_reached`, or `frontier_empty` after the run-end gates and drawings, never after `budget_spent`, `stall_strict`, `stopped`, or `switched`; replayed from journals of each end.
- [ ] Code's five checks run first with no model call, and a failing check records why no session launched.
- [ ] One decider session on `opus max` reads `REPORT.md`, `OBJECTIVES.md`, and `OUTLINE.md` and returns order or not with its reason; an order runs `wayline paper` with the setup's venue.
- [ ] The decider answers the batch (an oversized figure split, never dropped), settles the outline's open proposals without moving an owner-placed line, and picks a title; each answer appears under "Decided for you".
- [ ] Tests: the fake launcher scripts the decider ordering and declining; journal replay covers each end kind and idempotence of a second wave; the account's lines are asserted on the rendered `ACCOUNT.md`.
- [ ] `python -m unittest` passes.
