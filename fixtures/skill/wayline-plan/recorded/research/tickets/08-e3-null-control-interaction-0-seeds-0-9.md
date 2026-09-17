---
id: 8
title: "E3: null control, interaction 0, seeds 0-9"
kind: experiment
difficulty: 3
status: open
blocked_by: [2, 3, 4]
touches: [data/null/, predictions/null/, results/e3/]
role: experimenter
skills: []
resources: {cpu: 2, gpu: 0, ram_gb: 4, wallclock_minutes: 20}
acceptance:
  machine: [test $(ls predictions/null/lr-products-*.csv | wc -l) -eq 10 && test $(ls predictions/null/lr-raw-*.csv | wc -l) -eq 10, "grep -q '^auroc_gain: ' results/e3/paired_gain.txt && grep -q '^n_seeds: 10' results/e3/paired_gain.txt"]
  quality: []
context_pack: [research/SPEC.md#e3-claims-c3, research/SPEC.md#anti-claims, research/SPEC.md#seams, toy/make_sets.py, toy/fit_lr.py, toy/paired_gain.py]
origin: research/SPEC.md#e3-claims-c3
proposed_by: planner
demo: "One job: `python3 toy/make_sets.py --set null`; fit lr-raw and lr-products for seeds 0-9 with `--set null`; `python3 toy/paired_gain.py predictions/null --model lr-products --against lr-raw > results/e3/paired_gain.txt`, whose mean gain should sit inside ±0.005."
---

## Demo

One job: `python3 toy/make_sets.py --set null`; fit lr-raw and lr-products for seeds 0-9 with `--set null`; `python3 toy/paired_gain.py predictions/null --model lr-products --against lr-raw > results/e3/paired_gain.txt`, whose mean gain should sit inside ±0.005.

## Notes

C3's test and the refutation check for A1/A2: on D2 nothing was planted, so the products should change AUROC by less than 0.005 in absolute value. Runs in parallel with E1. Manifest results/e3/paired_gain.txt and predictions/null/lr-*.csv.
