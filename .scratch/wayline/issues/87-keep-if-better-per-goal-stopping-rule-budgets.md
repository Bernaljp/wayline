# 87 - Keep-if-better per goal, the stopping rule, and budgets; GOAL.json retires

**What to build:** A run ends where the owner meant it to, and every goal is chased on its own. This is the contract step of the objectives work: ticket 76 added objectives beside GOAL.json, tickets 80 and 81 moved the front door and the plan onto them, and after this ticket nothing reads GOAL.json.

**Keep-if-better per goal.** `progress` and `discarded` gain `goal`. Each goal's best kept value is recomputed from its own events, starting at its baseline. The metric, direction, split, and command come from its measure. The rule is unchanged (`policy.goal.min_seeds` 3 and `margin_sd` 1), except that a measure may carry its own `min_seeds`, down to 1 for a deterministic computation, where any strict gain is kept. A change kept for one goal is never re-measured on another. A ticket serving an objective with no measure gets nothing in place of keep-if-better. Code writes a goal "reached" from the measured values.

**The stopping rule.** `stop_when` in `harness.json`, set at setup, is one of:

- `objectives`: the default; the run ends when no objective is open;
- a list of objective ids: the run ends when those are closed;
- `frontier`: the run ends when no work is left, the v1.0 `graph_empty` made real.

The conductor reads it every wave in place of today's goal check. `run_ended` gains the reasons `objectives_closed` and `budget_spent`. `goal_reached` stays for a rule whose objectives all closed by reaching their targets. The tick does not relaunch a run that its stopping rule or a spent budget ended.

**Budgets.** `harness.json.budgets` keeps `wallclock_hours` (counted from the end of setup) and `gpu_hours` (each job's hours times the GPUs it held), now read by code. Spending either ends the run `budget_spent`, and the decider never extends one. `usage_windows` goes. After setup, changing `stop_when` or raising a budget is on the irreversible list. `wayline switch --stop-when <rule>` and `wayline switch --budget <name>=<value>` are the verbs.

**The empty frontier.** When nothing is launchable, running, or owed, and the rule still waits on open objectives, code opens one decision ticket covering each such objective. It offers four options:

1. replan for it, allowed at every radius since it stays within the spec;
2. answer it as it stands;
3. park it;
4. drop it.

Code recommends a replan only if a ticket serving the objective progressed since its last replan. Who answers depends on the autonomy:

- Under `interactive` and `checkpoints` the owner answers. The run ends `frontier_empty` meanwhile, and the tick relaunches after the answer.
- Under `autonomous` the decider answers, in one session per empty frontier, limited to replan or answer for an objective the rule names.

Under `stop_when: frontier` no ticket opens, and the end notice lists the open objectives. The stall counter is unchanged. Scheduling's class key (0 for a ticket serving an objective the rule waits on, 1 for another open objective, 2 for none) is ticket 81's, and this ticket feeds it the rule's objectives.

**Retiring GOAL.json.** Every reader of GOAL.json moves to `objectives.json` and `harness.json`, and the `goal` schema retires. The toy project's fixture moves its goal into `research/objectives.json` as an objective with a measure, and its `stop_when` into `harness.json`.

Not part of this ticket:

- the run-end gates (drawings, sampled verdicts, the kill argument) and how each end treats them (103);
- answering an objective "as it stands" by a fresh verifier and its Discussion passage, which the empty-frontier ticket hands to ticket 91's path;
- the stopping rule's and budgets' setup question in the conversation (109);
- the account's "where the project stands" paragraph (89).

**Blocked by:** 80 - The front door reads objectives; 81 - Specify and the plan name objectives. It blocks 89, 90, 103, and 109.

**Status:** ready-for-agent

**GitHub:** [#234](https://github.com/Bernaljp/wayline/issues/234) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Keep-if-better per goal, the stopping rule, and budgets"; "Objectives, goals, and measures": GOAL.json retires; "Vocabulary the build adds": `goal` on `progress` and `discarded`, the `run_ended` reasons, `switch --stop-when` and `--budget`, `harness.json` gaining `stop_when` and losing `usage_windows`, `goal` retiring from the schemas); decisions 1 (the verb table; `harness.json`), 2 (the event table: `progress`, `discarded`, `run_ended`), 4 (the irreversible list), 5 (the conductor's wave), 7 (the tick's relaunch), 14 (the policy table: `goal`; the toy project); M8 criterion 3 and the toy's part of criterion 1; user stories 2, 103, 112, 113, 114, 115, 174.

- [ ] `progress` and `discarded` carry `goal`. Each goal's best kept value is recomputed from its own events from its baseline, with its measure's metric, direction, split, and command. A measure's own `min_seeds` overrides the policy's, and at 1 any strict gain is kept.
- [ ] A change kept for one goal is never re-measured on another, and a ticket serving an objective with no measure is not judged by keep-if-better. A goal is written "reached" by code from the measured values.
- [ ] `stop_when` in `harness.json` takes `objectives` (the default), a list of objective ids, or `frontier`, and the conductor reads it every wave. `run_ended` journals `objectives_closed`, `goal_reached`, `frontier_empty`, or `budget_spent`, and the tick refuses to relaunch a run that its rule or a budget ended.
- [ ] `budgets.wallclock_hours` (from the end of setup) and `budgets.gpu_hours` (job hours times GPUs held) end the run `budget_spent` when spent. The decider never extends one, and `usage_windows` is gone from the schema.
- [ ] `wayline switch --stop-when` and `wayline switch --budget` write `harness.json` and journal `control`. After setup, changing the rule or raising a budget is on the irreversible list.
- [ ] An empty frontier with the rule waiting on open objectives opens one decision ticket per such objective with replan, answer as it stands, park, and drop. Replan is recommended only after progress since the last replan. Under `interactive` and `checkpoints` the run ends `frontier_empty` and the tick relaunches after the answer. Under `autonomous` the decider takes one session and only replans or answers for an objective the rule names.
- [ ] Under `stop_when: frontier` no such ticket opens, and the end notice lists the open objectives.
- [ ] No module reads `GOAL.json`, the `goal` schema is retired, and a project holding a `GOAL.json` runs as if it were absent.
- [ ] The toy fixture's goal is an objective with a measure in `objectives.json`, and its `stop_when` is in `harness.json`. Its conductor tests pass on the new shape.
- [ ] Tests:
  - replayed journals for keep-if-better on two goals, a measure with `min_seeds` 1, each `run_ended` reason, a spent wall-clock budget and a spent GPU budget, a relaunch the tick refuses, and the empty-frontier ticket under each autonomy, idempotence included;
  - the schema and the switches as plain functions over a temporary project.
- [ ] The verb table of decision 1, the event table of decision 2, the policy table of decision 14, and the schemas list gain these rows in the same commit as the code.
- [ ] `CHANGELOG.md` under `## Unreleased` describes the stopping rule, the budgets, and GOAL.json's retirement.
- [ ] `python -m unittest` passes.
