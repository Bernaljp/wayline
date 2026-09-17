# 38 - Stall detection and the escalation chain

**What to build:** A run cannot spin: two settling waves without a closed ticket, a new finding, or goal progress file a replan ticket, or stop and report in strict radius; a failed ticket escalates deterministically (resume once with the output, split by the planner, one tier up, then needs a human; the owner put the split before the tier up on 2026-09-17, since a tier up, to Fable above all, is the dearer step); a kind that fails twice at a tier has its default difficulty raised for the rest of the run unless the owner pinned it; and `--simulate-failure` lets the owner watch the chain in minutes.

**Blocked by:** 08 (Integration protocol and the integrator role), 34 (Plan: the planner, plan-time checks, and ticket assignment)

**Status:** done

**GitHub:** [#39](https://github.com/Bernaljp/wayline/issues/39) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 5 (escalation, stall), 14 (`escalation`, `stall.waves`), 15 (a fallback failure never raises a kind); OPEN-12 (map ticket 24); BRIEF 8.4, 9.7.

- [x] A settling wave is one that processed at least one worker or job outcome; the stall counter increments on each settling wave without `ticket_done`, `finding`, or `progress` with `kept: true`, resets on any of them, and at `policy.stall.waves` journals `stall` and files a replan ticket (`wayline plan --replan`) or, in radius `strict`, journals `run_ended` with `stall_strict` and renders the report.
- [x] Escalation on a failed attempt: resume the same session once with the failure output; then file a split (`wayline plan --split <id>`); then relaunch one tier up as a new attempt; then `ticket_needs_human` with a notification; each step journals `ticket_failed` with `next`.
- [x] After two failures of one kind at a tier, that kind's default difficulty rises by one for the rest of the run (`difficulty_raised`), except for tickets with `pinned_difficulty`, and never counting an attempt whose `ticket_launched` carries `fallback_from` (Implementation Decision 15; the test lands with whichever of this ticket and 55 merges second); outcomes feed the registry's outcome record.
- [x] `wayline run --simulate-failure <id>` makes the launcher return a failing acceptance for that ticket on every attempt so the whole chain runs in a demo.
- [x] Tests cover the counter, both stall actions, every escalation step, the difficulty raise, and the pin, with the fake worker and a fake planner.
