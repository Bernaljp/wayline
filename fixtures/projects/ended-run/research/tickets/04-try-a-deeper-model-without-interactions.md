---
id: 4
title: Try a deeper model without interactions
kind: experiment
difficulty: 3
status: done
blocked_by: [2]
touches: [src/toy/depth.py, results/depth/]
role: experimenter
skills: []
outputs: [results/depth/summary.json]
acceptance:
  machine: [python -m unittest]
  quality: []
origin: SPEC.md#a1-depth-alone
proposed_by: planner
demo: Three seeds of a model twice as deep, without interaction terms.
---

## Demo

Three seeds of a model twice as deep, without interaction terms.
