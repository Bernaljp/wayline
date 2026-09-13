---
id: 2
title: Train the baseline model
kind: experiment
difficulty: 3
status: accepted
blocked_by: [1]
touches: [src/toy/train.py, results/baseline/]
role: experimenter
skills: []
outputs: [results/baseline/summary.json]
acceptance:
  machine: [python -m unittest]
  quality: []
origin: SPEC.md#c1-interaction-terms
proposed_by: planner
demo: Three seeds of the baseline with held-out AUROC.
---

## Demo

Three seeds of the baseline with held-out AUROC.
