---
id: 7
title: Export the held-out predictions
kind: code
difficulty: 2
status: blocked
blocked_by: [1]
touches: [src/toy/export.py]
role: coder
acceptance:
  machine: [python -m unittest]
  quality: []
proposed_by: planner
demo: A CSV of predictions for the held-out split.
---

## Demo

The export writes one row per held-out example.
