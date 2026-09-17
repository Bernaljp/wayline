---
id: 3
title: "Generate the twenty sets (toy/make_sets.py: D1 default, D2 null)"
kind: code
difficulty: 1
status: open
blocked_by: [1]
touches: [toy/make_sets.py]
role: coder
skills: []
acceptance:
  machine: [python3 toy/make_sets.py --set default --seeds 0-1 && test -f data/default/seed-0.csv && test $(wc -l < data/default/seed-1.csv) -eq 20001, "python3 toy/make_sets.py --set null --seeds 0 && test -f data/null/seed-0.csv && test $(grep -c '^split_b,' data/null/seed-0.csv) -eq 5000"]
  quality: []
context_pack: [toy/make_synthetic.py, research/SPEC.md#data, research/SPEC.md#seams]
origin: research/SPEC.md#data
proposed_by: planner
demo: "`python3 toy/make_sets.py --set default` writes data/default/seed-0.csv … seed-9.csv (signal 1.0, interaction 0.6); `--set null` writes data/null/seed-0..9.csv at interaction 0; each has 20001 lines, split_b its last 5000 rows; rerunning skips files that exist."
---

## Demo

`python3 toy/make_sets.py --set default` writes data/default/seed-0.csv … seed-9.csv (signal 1.0, interaction 0.6); `--set null` writes data/null/seed-0..9.csv at interaction 0; each has 20001 lines, split_b its last 5000 rows; rerunning skips files that exist.

## Notes

Stdlib only; call make_synthetic.make(seed, interaction=…) directly, never change make_synthetic.py. `--set default|null`, `--seeds 0-9` (default all ten). D2 is the same generator at interaction 0 (Q7 as the confirmed spec states it). Byte-identical output on rerun; skip an existing file. Do not commit data/ (ignored by T1).

## Public API

This ticket adds public API, so a `docs` ticket follows it.
