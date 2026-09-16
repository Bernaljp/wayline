---
id: 2
title: Analyse the sweep
kind: analysis
difficulty: 2
status: open
blocked_by: [1]
touches: [analysis/]
role: analyst
skills: []
outputs: [analysis/summary.md]
acceptance:
  machine: ["test -s analysis/summary.md"]
  quality: []
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "analysis/summary.md names the best learning rate, and findings.jsonl carries it with provenance into a manifested result."
---

## Demo

`analysis/summary.md` on `main` says which learning rate gave the best held-out AUROC, and
`research/findings.jsonl` carries that finding with its provenance.

## What to do

Read the three results of ticket 1 (`results/sweep/lr-*.json` in the project; the manifest names
them). Write `analysis/summary.md` with a table of learning rate, batch size, AUROC, and loss, and
the best learning rate. File one finding for the best rate, its provenance
`results/sweep/lr-<rate>.json#auroc`, and one negative finding if two rates are within 0.01 AUROC
of each other.
