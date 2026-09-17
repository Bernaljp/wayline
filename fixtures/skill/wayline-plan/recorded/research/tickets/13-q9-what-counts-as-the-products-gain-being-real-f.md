---
id: 13
title: "Q9: what counts as the products' gain being real for C1: the mean over..."
kind: decision
difficulty: 1
status: open
blocked_by: []
blocking: subgraph
human_only: true
touches: []
role: decider
skills: []
acceptance: {}
context_pack: [research/SPEC.md]
origin: "plan dba57fe28c80: research/DECISIONS.md#q9-what-counts-as-the-products-gain-being-real"
proposed_by: planner
demo: "The owner answers: Q9: what counts as the products' gain being real for C1: the mean over ten seeds meeting +0.02 alone, or the mean and its 95% interval over seeds excluding 0?"
---

## Decision

Q9: what counts as the products' gain being real for C1: the mean over ten seeds meeting +0.02 alone, or the mean and its 95% interval over seeds excluding 0?

- options:
  - the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0
  - the mean paired gain meets the goal, no interval
  - the gain is positive on every seed
- recommended: the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0
- evidence:
  - DECISIONS.md Q9 is open and human-only; the spec's success criterion states the mean alone and its risk mitigation reports the sd
  - the per-seed ceiling spread on split_b is 0.0066 over seeds 0-4, a third of the target gain (DECISIONS.md Q5, Q9)
  - toy/paired_gain.py (T2) prints the mean, sd, and 95% t-interval, so any answer can be applied without rerunning E1
- blocking: `subgraph`, so ticket 9 and whatever waits on it wait for the answer
- human-only: yes, only the owner answers it
- asked by: plan dba57fe28c80: research/DECISIONS.md#q9-what-counts-as-the-products-gain-being-real

<!-- wayline:decision {"ticket":13,"question":"Q9: what counts as the products' gain being real for C1: the mean over ten seeds meeting +0.02 alone, or the mean and its 95% interval over seeds excluding 0?","options":["the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0","the mean paired gain meets the goal, no interval","the gain is positive on every seed"],"recommended":"the mean paired gain over seeds meets the goal and its 95% interval over seeds excludes 0","evidence":["DECISIONS.md Q9 is open and human-only; the spec's success criterion states the mean alone and its risk mitigation reports the sd","the per-seed ceiling spread on split_b is 0.0066 over seeds 0-4, a third of the target gain (DECISIONS.md Q5, Q9)","toy/paired_gain.py (T2) prints the mean, sd, and 95% t-interval, so any answer can be applied without rerunning E1"],"human_only":true,"reversible":true,"answer":null,"rationale":null,"confidence":null,"decided_by":null,"timestamp":null,"blocking":"subgraph"} -->

## How to answer

`wayline answer 13 "<answer>"`, from the command line or from a session; the answer form in the dashboard's decisions view; or the answer written under an `## Answer` heading at the end of this file. Each is journaled as the owner's decision, and the conductor closes this ticket at its next wave.
