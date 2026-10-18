# 80 - The front door reads objectives

**What to build:** Intake, position, the grill, and the decider work from objectives instead of `GOAL.json`, so a project with no metric gets through the front door and a question that must be answered first can lead.

- **Intake takes information only.** `INTAKE.md` loses its `Goal` section and `intake --goal` goes; the measure check moved to `wayline objective add` in 76. The intake wording tells the owner what to hand over, and the goal is recorded by the conversation as an objective.
- **Position.** Its guard on `GOAL.json` goes, so a project with no goal is positioned. The memo reads `OBJECTIVES.md` and the intent; `goal_feasibility` becomes `objectives`, one row per objective with a verdict (`reachable`, `uncertain`, `out_of_reach`), the reasoning, and a revised target for a goal out of reach. Its three directions name the objectives they would pursue, as proposals.
- **The grill.** Its first tier settles which objectives the project takes, open or parked, each question reserved for the owner, recorded through the objectives' ledger.
- **The decider.** It reads `OBJECTIVES.md` in place of `GOAL.json`, and reads the radius, since its additions of objectives are bounded by it (a defect found while charting: `apply_admitted` already trusted it to have weighed the radius). The human-only class `goal` becomes `objective`, which covers goals; a `harness.json` naming `goal` is read as `objective`.

`GOAL.json` is still written by nothing new and still read by the conductor's goal check and keep-if-better until 87 retires it.

Not part of this ticket:

- specify, claims' `objectives`, and tickets' `goal` (81);
- the stopping rule, budgets, and keep-if-better per goal (87);
- the decider's batches of objective changes (91);
- the critic's documents, concerns, and the missing-material table at a start midway (96, 97);
- the setup conversation's order of questions (109).

**Blocked by:** 76 - Objectives: the record and objective add. It blocks 87, 91, 96, and 109.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (objectives, goals, and measures: intake, position, the grill, the decider, the `objective` class; defects found while charting: the decider reads the radius; setup, `human_only` naming `objective`), 10 (the front door: intake, position, grill, decider), 1 (the verb table: `intake --goal` goes), the schemas list (the position memo's `objectives` in place of `goal_feasibility`); M8 criterion 1; user stories 5, 102, 104, 108.

- [ ] `INTAKE.md` has no `Goal` section and `wayline intake --goal` is gone, with the verb table of decision 1 changed in the same commit; intake's settings are unchanged otherwise.
- [ ] `wayline position` runs on a project with no `GOAL.json`; its memo schema has `objectives` (one row per objective: verdict, reasoning, revised target for a goal out of reach) in place of `goal_feasibility`, and its directions name objectives as proposals; `POSITION.md` renders them.
- [ ] The grill's first tier asks, per proposed objective, open or parked, reserved for the owner, and records each answer as an `objective` event.
- [ ] The decider's prompt reads `OBJECTIVES.md` and the radius, not `GOAL.json`; the human-only class `objective` replaces `goal`, and an old `goal` entry in `harness.json` is read as `objective`.
- [ ] The conductor's goal check and keep-if-better still read `GOAL.json` where present, unchanged.
- [ ] Tests: position with the fake launcher on a project with objectives and none with a measure; the memo schema's `objectives` rows; the grill's first tier from a recorded fixture; the decider's prompt assembly asserted on the rendered prompt (objectives and radius present, `GOAL.json` absent); the `goal` to `objective` class reading.
- [ ] Prompts and role files that mention `GOAL.json` or `goal_feasibility` for these phases are updated, and the documentation site's front-door pages follow.
- [ ] `python -m unittest` passes.
