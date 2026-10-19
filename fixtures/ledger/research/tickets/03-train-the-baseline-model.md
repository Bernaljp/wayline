---
id: 3
title: Train the baseline model
kind: experiment
difficulty: 3
status: running
blocked_by: [2]
touches: [src/toy/train.py, results/baseline/]
role: experimenter
acceptance:
  machine: [python -m unittest]
  quality: []
proposed_by: planner
resources: {gpu: 1, cpu: 8, ram_gb: 32, wallclock_minutes: 90}
objectives: [O1]
goal: O1
budget: {max_turns: 100, max_minutes: 90}
outputs: [results/baseline/summary.json]
demo: Three seeds of the baseline with held-out AUROC.
---

## Demo

Three seeds, one summary, the metric the goal reads.
