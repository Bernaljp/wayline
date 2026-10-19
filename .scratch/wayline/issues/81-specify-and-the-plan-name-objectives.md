# 81 - Specify and the plan name objectives

**What to build:** The spec and the ticket graph trace to objectives. Specify drafts once one objective is open; that objective may be the question to answer first, not the project's end. With none open, specify refuses and says the conversation should ask "what should the project answer first?".

- **The spec.** It gains `summary`, about 120 words on what the project is, written by the specify session (the general report opens with it, 90). Claims gain `objectives`, which may be empty, and any id named must be open. A Type-A check at specify confirms every open objective is answered by at least one claim, and that each goal's metric is among the spec's metrics.
- **The plan and tickets.** Tickets and the plan schema gain `objectives` (may be empty: a plotting ticket or an unasked claim needs none; any id named must be open). A ticket's `goal_metric` becomes `goal: "O2"`, the metric and direction read from that goal's measure. The planner reads `OBJECTIVES.md`.
- **Scheduling.** Scheduling's second key becomes a class: 0 for a ticket serving an objective the stopping rule waits on, 1 for another open objective, 2 for none. Until 87 lands `stop_when`, the stopping rule reads as its default, `objectives` (every open objective).

`GOAL.json` is still read by the conductor's goal check and keep-if-better until 87.

Not part of this ticket:

- sections and passages, including the specify session's Introduction passages on the gap (86);
- keep-if-better reading `goal` per ticket and the stopping rule (87);
- set-aside claims and spec amendments (91, 92);
- the `lit` tickets cut per objective (99).

**Blocked by:** 76 - Objectives: the record and objective add. It blocks 86, 87, 91, 97, 99, and 109.

**Status:** done

**GitHub:** [#228](https://github.com/Bernaljp/wayline/issues/228) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (objectives, goals, and measures: claims and tickets name objectives, `goal` replacing `goal_metric`, every open objective answered by a claim, specify drafting with one open objective; keep-if-better per goal, the stopping rule, and budgets: scheduling's class key; results and the reports: the spec's `summary`; vocabulary the build adds), 10 (specify, the planner), 5 (the conductor's scheduling), the schemas list (`spec` gains `summary` and claims' `objectives`; `ticket` and `plan` gain `objectives` and `goal` replacing `goal_metric`); M8 criterion 1; user stories 102, 103.

- [x] `wayline specify` drafts with one open objective and refuses with none, naming the question the conversation should ask.
- [x] The spec schema has `summary` and claims' `objectives`; the specify session writes both; a claim naming a closed or unknown objective is refused.
- [x] A Type-A check at specify fails when an open objective has no claim, or a goal's metric is not among the spec's metrics, naming which.
- [x] Ticket and plan schemas have `objectives` and `goal` in place of `goal_metric`; the planner fills them; `goal` names an objective with a measure, and its metric and direction are read from the measure; a ticket naming a closed objective is refused.
- [x] Scheduling orders the frontier by the class key (0, 1, 2) after its first key, and the conductor's existing scheduling tests are updated to it.
- [ ] Projects and fixtures that carry `goal_metric` are moved to `goal` in the same commit, so nothing reads `goal_metric` afterward.
- [x] The schemas list in the spec matches the new fields in the same commit.
- [x] Tests: specify and the planner with the fake launcher over a temporary project with objectives (one with a measure); the Type-A check's three outcomes; the schema refusals; the scheduling class over replayed journals.
- [x] Prompts and role files for specify and the planner name objectives.
- [x] `python -m unittest` passes.
