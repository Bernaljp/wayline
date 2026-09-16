---
id: 6
title: "E1: with vs without products on D1, seeds 0-9"
kind: experiment
difficulty: 3
status: open
blocked_by: [2, 3, 4]
touches: [data/default/, predictions/default/, results/e1/]
role: experimenter
skills: []
resources: {cpu: 2, gpu: 0, ram_gb: 4, wallclock_minutes: 20}
acceptance:
  machine: [test $(ls predictions/default/lr-products-*.csv | wc -l) -eq 10 && test $(ls predictions/default/lr-raw-*.csv | wc -l) -eq 10 && test $(ls predictions/default/lr-planted-*.csv | wc -l) -eq 10, "grep -q '^auroc_gain: ' results/e1/paired_gain.txt && grep -q '^n_seeds: 10' results/e1/paired_gain.txt", "grep -q '^auroc_gain: ' results/e1/oracle_gain.txt"]
  quality: []
goal_metric: {reports: auroc_gain, expected_direction: up}
context_pack: [research/SPEC.md#e1-claims-c1, research/SPEC.md#seams, research/CONTEXT.md#language, toy/make_sets.py, toy/fit_lr.py, toy/paired_gain.py]
origin: research/SPEC.md#e1-claims-c1
proposed_by: planner
demo: "One job: `bash toy/venv.sh; python3 toy/make_sets.py --set default; for k in 0..9: .venv/bin/python toy/fit_lr.py --set default --seed $k --model raw|products|planted`; then `python3 toy/paired_gain.py predictions/default --model lr-products --against lr-raw > results/e1/paired_gain.txt` and the same with `--model lr-planted > results/e1/oracle_gain.txt`; the first file ends with the mean gain over ten seeds and its sd."
---

## Demo

One job: `bash toy/venv.sh; python3 toy/make_sets.py --set default; for k in 0..9: .venv/bin/python toy/fit_lr.py --set default --seed $k --model raw|products|planted`; then `python3 toy/paired_gain.py predictions/default --model lr-products --against lr-raw > results/e1/paired_gain.txt` and the same with `--model lr-planted > results/e1/oracle_gain.txt`; the first file ends with the mean gain over ten seeds and its sd.

## Notes

C1's test. Manifest results/e1/paired_gain.txt, results/e1/oracle_gain.txt, and every predictions/default/lr-*.csv. The oracle line (B3, x2*x3 alone) bounds what a product can add; it is a reference, not a criterion. Success per the spec: mean paired auroc_gain >= 0.02.
