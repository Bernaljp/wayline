---
id: 10
title: "Analysis of E2: C2, the network against explicit products"
kind: analysis
difficulty: 3
status: open
blocked_by: [7]
touches: [analysis/e2/]
role: analyst
skills: []
resources: {cpu: 1, gpu: 0, ram_gb: 2, wallclock_minutes: 30}
acceptance:
  machine: [test -f analysis/e2/per_seed.csv && test $(tail -n +2 analysis/e2/per_seed.csv | wc -l) -eq 10, "grep -Eq '^verdict_c2: (holds|fails)' analysis/e2/verdict.md"]
  quality: ["Does the verdict rest on the paired margin of lr-products over mlp-raw within each seed (mean above zero per the spec), report how much of the products' gain the network recovers, and cite every number to a manifested artifact?"]
context_pack: [research/SPEC.md#e2-claims-c2, research/SPEC.md#claims, research/CONTEXT.md#language, results/e2/paired_gain.txt, results/e2/mlp_over_raw.txt, results/e1/paired_gain.txt, research/refs/paper-b/dossier.json]
origin: research/SPEC.md#e2-claims-c2
proposed_by: planner
demo: analysis/e2/per_seed.csv holds one row per seed with auroc_products, auroc_mlp, auroc_raw, margin; verdict.md states the mean paired margin, its sd and interval, the fraction of E1's gain the network recovers, the chosen grid settings per seed, and `verdict_c2:`.
---

## Demo

analysis/e2/per_seed.csv holds one row per seed with auroc_products, auroc_mlp, auroc_raw, margin; verdict.md states the mean paired margin, its sd and interval, the fraction of E1's gain the network recovers, the chosen grid settings per seed, and `verdict_c2:`.

## Notes

File one finding for C2. paper-b is the competing explanation; say what this size of network did and did not recover, and no more than the ten seeds show.
