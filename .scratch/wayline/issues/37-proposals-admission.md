# 37 - Proposals admission

**What to build:** Workers, verifiers, and the critic may propose tickets, and code decides: a proposal is admitted when it is inside the radius, not a duplicate, under the per-wave cap, and its blockers exist; otherwise it is parked with the reason, listed in the report under "not pursued", never deleted, and reconsidered by the decider at the end of each wave under `autonomous`.

**Blocked by:** 07 (Frontier, launchable subset, and two parallel workers), 31 (The decider)

**Status:** ready-for-agent

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 5 (proposals), 14 (`proposals`); OPEN-13 (map ticket 25); BRIEF 6.3, 9.5.

- [ ] Admission runs on every result's `proposals[]` and on the critic's and verifier's proposals: inside the radius (`strict` admits only tickets tracing to a spec claim; `moderate` adds follow-ups probing a claim's failure; `exploratory` adds new directions gated on a scout novelty check), not a duplicate (same kind and normalized-title similarity above 0.8, or identical touch set and origin, is a duplicate; similarity between 0.6 and 0.8 goes to one `haiku --effort low` judgment through the launcher), under the per-wave cap (`strict` 0, `moderate` 3, `exploratory` 6), every `blocked_by` existing.
- [ ] Admitted proposals become tickets with `proposed_by` and `origin` and journal `proposal_admitted`; the rest journal `proposal_parked` with `reason` in `radius, duplicate, cap, blockers` and are kept under `research/proposals/` for the report.
- [ ] Under `autonomous` the decider reconsiders parked proposals at the end of each wave and may admit them within the cap.
- [ ] The report renderer lists parked proposals under "not pursued" with their reasons.
- [ ] Tests drive the fake worker with proposals across the three radii, duplicates at 0.85 and 0.7 similarity (fake judge), and a cap overflow.
