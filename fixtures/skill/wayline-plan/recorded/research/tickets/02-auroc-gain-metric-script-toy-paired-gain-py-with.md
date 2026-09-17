---
id: 2
title: auroc_gain metric script (toy/paired_gain.py) with a unit test
kind: code
difficulty: 2
status: open
blocked_by: []
touches: [toy/paired_gain.py, toy/test_paired_gain.py]
role: coder
skills: []
acceptance:
  machine: [python3 toy/paired_gain.py --help, python3 toy/test_paired_gain.py]
  quality: []
context_pack: [toy/eval.py, research/SPEC.md#metrics, research/SPEC.md#seams, research/CONTEXT.md#language, research/DECISIONS.md#q9-what-counts-as-the-products-gain-being-real]
origin: research/SPEC.md#metrics
proposed_by: planner
demo: "`python3 toy/paired_gain.py predictions/default --model lr-products --against lr-raw` prints one `seed k: model=… against=… gain=…` line per seed, then `auroc_gain: <mean>`, `auroc_gain_sd: <sd>`, `auroc_gain_ci95: <lo> <hi>`, `n_seeds: 10`; the unit test passes on a tiny fixture it writes itself."
---

## Demo

`python3 toy/paired_gain.py predictions/default --model lr-products --against lr-raw` prints one `seed k: model=… against=… gain=…` line per seed, then `auroc_gain: <mean>`, `auroc_gain_sd: <sd>`, `auroc_gain_ci95: <lo> <hi>`, `n_seeds: 10`; the unit test passes on a tiny fixture it writes itself.

## Notes

Stdlib only (the spec runs it as `python3 toy/paired_gain.py {artifact}`); import auroc from toy/eval.py rather than re-implementing it. Usage: `paired_gain.py <predictions_dir> [--model lr-products] [--against lr-raw] [--seeds 0-9]`; the artifact is the directory, files are `<model>-<seed>.csv` with `label,score` rows (the scores seam). gain = auroc(model) - auroc(against) per seed; mean, sample sd (ddof=1), and a 95% t-interval (t=2.262 for n=10; a small table, no scipy). Exit nonzero naming the first missing seed file. The test builds two synthetic prediction sets with known AUROCs and checks the mean and sd to 4 decimals.

## Public API

This ticket adds public API, so a `docs` ticket follows it.
