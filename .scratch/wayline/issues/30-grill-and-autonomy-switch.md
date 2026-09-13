# 30 - The grill and the autonomy switch

**What to build:** The owner is asked the whole frontier of open questions in tiers, each numbered with a recommended answer, with facts looked up rather than asked; every answer lands in `DECISIONS.md` and vocabulary in `CONTEXT.md` as it is settled; and at any moment the owner can say "decide the rest yourself", which raises autonomy and hands the remaining frontier to the decider.

**Blocked by:** 28 (Intake and the goal)

**Status:** done

**GitHub:** [#31](https://github.com/Bernaljp/wayline/issues/31) (mirror; the local file is the source)

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (the grill), 4 (autonomy default); BRIEF 6.2; the map's Notes on batch confirmation.

- [x] The `wayline-grill` skill builds the design tree from `POSITION.md` and `INTAKE.md`, asks the whole frontier per tier (questions whose prerequisites are settled), numbers them, states a recommended answer on each, looks facts up (installed tools, the dossiers, the scout, the consultant) instead of asking, and writes each answer to `DECISIONS.md` as `question, answer, rationale, decided-by: human, confidence, timestamp` and each settled term to `CONTEXT.md` before the next tier.
- [x] `wayline switch --autonomy <interactive|checkpoints|autonomous>` and the same words said in the grill journal `control {command: autonomy}` and update `harness.json`; lowering is only possible when no conductor is alive and is done by editing `harness.json`, which the verb refuses otherwise.
- [x] The `decision` schema (`question, options, answer, rationale, confidence, decided_by, reversible, timestamp`) validates every entry.
- [x] The skill's fixture records one grill over the toy intent with structural checks on `DECISIONS.md`; the switch mid-grill is covered by a test on the journal and `harness.json`.
