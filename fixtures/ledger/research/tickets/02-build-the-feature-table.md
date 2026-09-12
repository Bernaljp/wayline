---
id: 2
title: Build the feature table
kind: analysis
difficulty: 2
status: done
blocked_by: [1]
touches: [src/toy/features.py, results/features/]
role: analyst
acceptance:
  machine: [test -f results/features/summary.json]
  quality: [Are the feature definitions the ones the spec names?]
proposed_by: planner
outputs: [results/features/summary.json]
demo: A table of rows by feature with the held-out split marked.
---

## Demo

One summary file with a row count and the feature names.
