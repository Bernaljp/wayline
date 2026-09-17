---
id: 5
title: Small network baseline with 5-fold CV inside split_a (toy/fit_mlp.py)
kind: code
difficulty: 3
status: open
blocked_by: [1, 3]
touches: [toy/fit_mlp.py]
role: coder
skills: []
acceptance:
  machine: [bash toy/venv.sh && python3 toy/make_sets.py --set default --seeds 0 && .venv/bin/python toy/fit_mlp.py --set default --seed 0 --grid small && test $(wc -l < predictions/default/mlp-raw-0.csv) -eq 5001 && python3 toy/eval.py predictions/default/mlp-raw-0.csv, "bash toy/venv.sh && .venv/bin/python toy/fit_mlp.py --set default --seed 0 --grid full --describe | grep -q 'cv_folds: 5'", "bash toy/venv.sh && .venv/bin/python toy/fit_mlp.py --set default --seed 0 --grid full --describe | grep -q 'tuned_on: split_a'"]
  quality: ["Does the network tune only inside split_a (5-fold CV, the same grid for every seed), score split_b once with the chosen setting, and does the full grid on seed 0 fit inside 18 minutes on 8 cores so ten seeds fit E2's 3 hours?"]
context_pack: [research/SPEC.md#methods, research/SPEC.md#e2-claims-c2, research/SPEC.md#risks, research/DECISIONS.md#q10-how-are-regularization-and-network-settings-tuned-without-touching-split_b, research/refs/paper-b/dossier.json, toy/fit_lr.py]
origin: research/SPEC.md#methods
proposed_by: planner
demo: "`.venv/bin/python toy/fit_mlp.py --set default --seed 0 --grid full` runs GridSearchCV (cv=5, scoring roc_auc) over MLPClassifier settings on split_a, refits the best on all of split_a, writes predictions/default/mlp-raw-0.csv, and prints the chosen setting and the wall-clock time; `--describe` prints the grid, `cv_folds: 5`, `tuned_on: split_a`."
---

## Demo

`.venv/bin/python toy/fit_mlp.py --set default --seed 0 --grid full` runs GridSearchCV (cv=5, scoring roc_auc) over MLPClassifier settings on split_a, refits the best on all of split_a, writes predictions/default/mlp-raw-0.csv, and prints the chosen setting and the wall-clock time; `--describe` prints the grid, `cv_folds: 5`, `tuned_on: split_a`.

## Notes

B2 (Q2, Q8 as the confirmed spec states it): MLPClassifier on the raw 8 features, no products. Same code path as fit_lr.py for reading a set and writing scores (import from toy/features.py; do not edit it). Grid `full`: hidden_layer_sizes {(16,),(32,),(32,16),(64,32)} x alpha {1e-4,1e-3,1e-2}, early_stopping=True, max_iter=300, random_state=0; `small`: (16,) x {1e-3} for smoke tests. Use n_jobs=8 in GridSearchCV. Time the full grid on seed 0 and, per the spec's risk mitigation, trim `full` until one seed fits 18 minutes; record the timing and the final grid in the module docstring. The grid is fixed in code so every seed uses the same one.

## Public API

This ticket adds public API, so a `docs` ticket follows it.
