---
id: 9
title: "Analysis of E1 and E3: C1, C3, and A2's withdrawal rule"
kind: analysis
difficulty: 4
status: open
blocked_by: [6, 8, 13]
touches: [analysis/e1-e3/]
role: analyst
skills: []
resources: {cpu: 1, gpu: 0, ram_gb: 2, wallclock_minutes: 30}
acceptance:
  machine: [test -f analysis/e1-e3/per_seed.csv && test $(tail -n +2 analysis/e1-e3/per_seed.csv | wc -l) -eq 20, "grep -q 'C1' analysis/e1-e3/verdict.md && grep -q 'C3' analysis/e1-e3/verdict.md && grep -Eq '^verdict_c1: (holds|withdrawn|fails)' analysis/e1-e3/verdict.md"]
  quality: ["Does the verdict apply the spec's rules exactly (C1 holds iff E1's mean paired gain >= 0.02, under the Q9 answer; C3 holds iff |E3's mean| < 0.005, else C1 withdrawn per A2), cite every number to a manifested artifact, and read no coefficient as a discovery?"]
context_pack: [research/SPEC.md#success-criteria, research/SPEC.md#anti-claims, research/SPEC.md#e1-claims-c1, research/SPEC.md#e3-claims-c3, research/CONTEXT.md#language, results/e1/paired_gain.txt, results/e1/oracle_gain.txt, results/e3/paired_gain.txt, research/DECISIONS.md#q9-what-counts-as-the-products-gain-being-real]
origin: research/SPEC.md#success-criteria
proposed_by: planner
demo: analysis/e1-e3/per_seed.csv holds one row per (set, seed) with auroc_raw, auroc_products, auroc_planted (default only), gain; verdict.md states the E1 mean, sd, 95% interval, the E3 mean, the oracle bound, and one line each `verdict_c1:` and `verdict_c3:`; the findings filed cite results/e1 and results/e3.
---

## Demo

analysis/e1-e3/per_seed.csv holds one row per (set, seed) with auroc_raw, auroc_products, auroc_planted (default only), gain; verdict.md states the E1 mean, sd, 95% interval, the E3 mean, the oracle bound, and one line each `verdict_c1:` and `verdict_c3:`; the findings filed cite results/e1 and results/e3.

## Notes

File one finding per claim (C1, C3) and one for the anti-claims A1/A2. Apply the Q9 answer to C1 (the decision ticket that pauses this one). Report the oracle gain as the bound the 28 products approach, nothing more (Q4; which product matters is out of scope).
