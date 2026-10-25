# 137 - The rule's own end waits for its gates

**What to build:** At the stopping rule's own ends, the run-end gates' scope-downs and owed drawings continue the run, and the run ends only when an end holds with no gate owed, as decision 17 says.

On the toy's live run (ticket 122, `docs/verification/m8.md`), O1 to O4 were closed by 03:59Z and the run-end drawings opened (18 tickets, R1 to R18). At 06:36Z the gates sampled 17 never-sampled claims (13 verdicts passed, 4 failed: scope-downs 158 to 161), at 06:56Z the kill argument on `REPORT.md` failed (scope-down 162), and two seconds later the conductor journaled `run_ended` with `reason: objectives_closed`, leaving all five scope-downs open and 12 results undrawn (R4 to R6, R9, R10, R12 to R18; ticket 136 parked most of their drawings). `paper_judged` then refused to launch the decider: "the general report's last kill argument failed, and its scope-down is not done: ticket 162 (open)"; the outline's gaps; and the undrawn results. The decider never judged the order, so M8's demo had no paper. Decision 17: "at the rule's own ends they run first, and their scope-downs continue the run until an end holds with no gate owed; after `budget_spent` or `stall_strict` they run once and their scope-downs wait for the next run".

- At `objectives_closed`, `goal_reached`, and `frontier_empty`, a gate that opens scope-down tickets, or a drawing still owed, keeps the run going; the gates run again at the next end, and `run_ended` is journaled only when none is owed.
- The account and the end notice name the gates' outcome at the end that held.
- `paper_judged` runs only at that end.

**Blocked by:** None - can start immediately. It edits the conductor's end step; 129, 134, and 136 edit nearby steps, so it runs alone or after them.

**Status:** ready-for-agent

**GitHub:** [#344](https://github.com/Bernaljp/wayline/issues/344) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (the stopping rule and budgets: the run-end gates; the paper order judged by the decider), M8 criteria 3 and 19; ticket 122's live record.

- [ ] Replaying a journal where the objectives close and the kill argument fails: the scope-down launches, the gates run again, and `run_ended` follows only once they pass; covered with the fake launcher.
- [ ] The same with a drawing owed: the run waits for it.
- [ ] After `budget_spent`, the gates run once and the scope-downs wait, as now.
- [ ] `python -m unittest` passes.
