---
id: 4
title: "Logistic regression fits: raw, all 28 products, planted oracle (toy/fit_lr.py)"
kind: code
difficulty: 3
status: open
blocked_by: [1, 3]
touches: [toy/fit_lr.py, toy/features.py, toy/test_features.py]
role: coder
skills: []
acceptance:
  machine: [bash toy/venv.sh && python3 toy/make_sets.py --set default --seeds 0 && .venv/bin/python toy/fit_lr.py --model products --set default --seed 0 && test $(wc -l < predictions/default/lr-products-0.csv) -eq 5001 && python3 toy/eval.py predictions/default/lr-products-0.csv, "bash toy/venv.sh && .venv/bin/python toy/fit_lr.py --model products --set default --seed 0 --describe | grep -q 'n_features: 36'", "bash toy/venv.sh && .venv/bin/python toy/fit_lr.py --model planted --set default --seed 0 --describe | grep -q 'n_features: 9'", bash toy/venv.sh && .venv/bin/python toy/test_features.py]
  quality: []
context_pack: [toy/eval.py:1-4, toy/make_synthetic.py:13-30, research/CONTEXT.md#language, research/SPEC.md#methods, research/SPEC.md#baselines, research/SPEC.md#seams, research/DECISIONS.md#q4-which-interaction-terms-does-the-with-products-model-get]
origin: research/SPEC.md#methods
proposed_by: planner
demo: "`.venv/bin/python toy/fit_lr.py --model products --set default --seed 0` fits on split_a and writes predictions/default/lr-products-0.csv with a `label,score` row per split_b row in file order; `--describe` prints `n_features: 36`, `train_rows: 15000`, `model: lr-products`."
---

## Demo

`.venv/bin/python toy/fit_lr.py --model products --set default --seed 0` fits on split_a and writes predictions/default/lr-products-0.csv with a `label,score` row per split_b row in file order; `--describe` prints `n_features: 36`, `train_rows: 15000`, `model: lr-products`.

## Notes

scikit-learn LogisticRegression with library defaults (the spec's method), no scaling. `--model raw|products|planted` -> files lr-raw, lr-products, lr-planted (B1, the method, B3). toy/features.py: raw = x0..x7; products = raw + the 28 x_i*x_j for i<j (no squares); planted = raw + x2*x3. Train on rows with split == split_a only; score = predict_proba[:,1] on split_b rows, kept in file order. Deterministic (lbfgs); if a ConvergenceWarning appears, report it in the result rather than silently changing max_iter. test_features.py checks the column counts (8, 36, 9) and that x2*x3 appears once. Never read a coefficient as a discovery (A2).

## Public API

This ticket adds public API, so a `docs` ticket follows it.
