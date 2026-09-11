# 39 — Keep-if-better protocol under a quantitative goal

Type: grilling
Status: resolved
Blocked by: None
Brief: Section 6.4; graduated from fog after OPEN-12 and OPEN-13

## Question

How does the harness keep or discard a change when a quantitative goal is set?

Default: `GOAL.json` names the held-out split; every experiment ticket that reports the goal metric is evaluated on that split by a Type-A script; a change is kept (merged to main) only when the metric improves in the goal's direction by more than a noise margin measured across the ticket's seeds; a discarded change stays on its ticket branch, is recorded in the journal as `discarded` with the metric, and its findings still enter `findings.jsonl` as negative results. Proposals that chase the goal count against the radius cap like any other. Decide the noise-margin rule (default: the improvement must exceed one standard deviation across seeds, minimum three seeds) and whether a discarded change can be revived by the planner (default: only by a new ticket citing new evidence).

## Answer

Resolved 2026-09-11 by the owner in a grilling round.

`GOAL.json` names the held-out split. A Type-A script evaluates each goal-reporting ticket on that split. A change is kept (merged) only when the metric improves in the goal's direction by more than one standard deviation across at least three seeds. A discarded change stays on its branch, is journaled as `discarded` with the metric, and its findings enter `findings.jsonl` as negative results. Revival only by a new ticket citing new evidence.
