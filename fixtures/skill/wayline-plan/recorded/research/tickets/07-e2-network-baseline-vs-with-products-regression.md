---
id: 7
title: "E2: network baseline vs with-products regression on D1, seeds 0-9"
kind: experiment
difficulty: 3
status: open
blocked_by: [2, 5, 6]
touches: [data/default/, predictions/default/, results/e2/]
role: experimenter
skills: []
resources: {cpu: 8, gpu: 0, ram_gb: 16, wallclock_minutes: 180}
acceptance:
  machine: [test $(ls predictions/default/mlp-raw-*.csv | wc -l) -eq 10, "grep -q '^auroc_gain: ' results/e2/paired_gain.txt && grep -q '^n_seeds: 10' results/e2/paired_gain.txt", "grep -q '^auroc_gain: ' results/e2/mlp_over_raw.txt"]
  quality: []
context_pack: [research/SPEC.md#e2-claims-c2, research/SPEC.md#risks, research/SPEC.md#seams, toy/fit_mlp.py, toy/paired_gain.py, results/e1/paired_gain.txt]
origin: research/SPEC.md#e2-claims-c2
proposed_by: planner
demo: "One job per seed (or one sequential job): `.venv/bin/python toy/fit_mlp.py --set default --seed $k --grid full`; then `python3 toy/paired_gain.py predictions/default --model lr-products --against mlp-raw > results/e2/paired_gain.txt` and `--model mlp-raw --against lr-raw > results/e2/mlp_over_raw.txt`; the first ends with the mean paired margin of the with-products regression over the network."
retry:
  host_oom: [--grid=small]
  gpu_oom: []
---

## Demo

One job per seed (or one sequential job): `.venv/bin/python toy/fit_mlp.py --set default --seed $k --grid full`; then `python3 toy/paired_gain.py predictions/default --model lr-products --against mlp-raw > results/e2/paired_gain.txt` and `--model mlp-raw --against lr-raw > results/e2/mlp_over_raw.txt`; the first ends with the mean paired margin of the with-products regression over the network.

## Notes

C2's test; the same ten sets as E1 and E1's lr-products scores (deterministic: refit with toy/fit_lr.py if a file is missing). Ten seeds at the grid T5 fixed; stay inside 3 hours (spec budget). Manifest both result files and predictions/default/mlp-raw-*.csv. Success per the spec: mean paired margin above zero.
