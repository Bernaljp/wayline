# 31 - The decider

**What to build:** After the switch, a max-effort session resolves every open question, every decision ticket not marked human-only, and every parked proposal at the end of each wave, each with rationale, confidence, and `decided-by: decider`, never touching the irreversible list, so the owner can audit and reverse any of them in the morning.

**Blocked by:** 30 (The grill and the autonomy switch)

**Status:** done

**GitHub:** [#32](https://github.com/Bernaljp/wayline/issues/32) (mirror; the local file is the source)

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (the decider), 4 (the irreversible list), 5 (wave step 5); BRIEF 6.2.

- [x] `roles/decider/` exists; it is launched through the launcher at `--effort max` on fable with `decision.json` as the schema and, in its context, `DECISIONS.md`, `POSITION.md`, `GOAL.json`, the L0 and L1 records, and the query pack.
- [x] `wayline grill --decide-rest` resolves the open frontier of the design tree; under autonomy `autonomous` the conductor launches the decider each wave for open decision tickets not `human_only` and, at the end of the wave, for parked proposals.
- [x] A code check refuses any decider answer whose class is on the irreversible list (delete or overwrite data, push, budgets, spending, goal or data changes, global harness changes, network writes) and turns it into a `human_only` decision ticket instead.
- [x] Every decision is journaled as `decision` with `decided_by: decider`, appended to `DECISIONS.md`, and listed first in the report and the dashboard's decision log.
- [x] Tests use the fake launcher, including a scripted irreversible answer; live: the decider resolves the questions left open after a switch during the M3 intake's grill.
