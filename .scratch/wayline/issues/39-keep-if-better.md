# 39 - Keep-if-better under a quantitative goal

**What to build:** With a goal set, a change is kept only when it improves the metric on the held-out split in the goal's direction by more than one standard deviation across at least three seeds; a discarded change stays on its branch, is journaled with its metric, and its findings enter the ledger as negative results; progress is tracked so the report can draw the trajectory, and the run ends when the target is reached.

**Blocked by:** 19 (Experiment and analysis tickets end to end (M2 demo)), 28 (Intake and the goal)

**Status:** ready-for-agent

**GitHub:** [#40](https://github.com/Bernaljp/wayline/issues/40) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 5 (keep-if-better, goal check, integration skip on discard), 14 (`goal`); map ticket 39; BRIEF 6.4.

- [ ] For every ticket with `goal_metric`, the conductor runs `GOAL.json.eval_command` on the held-out split and the ticket's outputs per seed before integration, computes the mean and standard deviation, and keeps the change (fast-forward) only when the mean improves in `direction` over the best kept value by more than one standard deviation with at least `policy.goal.min_seeds` seeds; fewer seeds fail the ticket with a request for more.
- [ ] A discarded change journals `discarded` with the metric, the best, the standard deviation, and the seed count; the branch and its worktree stay; the ticket is `done` but not integrated; its findings enter `findings.jsonl` with `negative: true`.
- [ ] Every evaluation journals `progress` with `kept`; the best kept value is what the goal check compares to `target`; with `stop_when: goal_reached` the run ends with `goal_reached` and a notification.
- [ ] Revival of a discarded change is only by a new ticket citing new evidence (the planner's rule; a test asserts a proposal that merely re-runs a discarded ticket is parked as a duplicate).
- [ ] Tests use the fake worker and fake jobs producing per-seed metrics on both sides of the margin.
