---
id: 4
title: Sweep the regulariser
kind: experiment
difficulty: 3
status: open
blocked_by: [3]
touches: [src/toy/sweep.py, results/sweep/]
role: experimenter
acceptance:
  machine: [python -m unittest]
  quality: []
proposed_by: planner
resources: {gpu: 1, cpu: 8, ram_gb: 32, wallclock_minutes: 120}
demo: A curve of held-out AUROC against the regularisation strength.
---

## Demo

The sweep runs after the baseline lands.
