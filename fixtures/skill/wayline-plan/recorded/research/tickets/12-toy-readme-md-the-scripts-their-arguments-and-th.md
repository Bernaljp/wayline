---
id: 12
title: "toy/README.md: the scripts, their arguments, and the file layout"
kind: docs
difficulty: 1
status: open
blocked_by: [1, 2, 3, 4, 5]
touches: [toy/README.md]
role: coder
skills: []
acceptance:
  machine: [test -f toy/README.md && grep -q 'venv.sh' toy/README.md && grep -q 'make_sets.py' toy/README.md && grep -q 'fit_lr.py' toy/README.md && grep -q 'fit_mlp.py' toy/README.md && grep -q 'paired_gain.py' toy/README.md, grep -q 'predictions/' toy/README.md && grep -q 'data/' toy/README.md]
  quality: []
context_pack: [toy/venv.sh, toy/make_sets.py, toy/paired_gain.py, toy/fit_lr.py, toy/fit_mlp.py, research/SPEC.md#seams]
origin: research/SPEC.md#seams
proposed_by: planner
demo: toy/README.md lists each script with its usage line and the layout data/<set>/seed-<k>.csv and predictions/<set>/<model>-<k>.csv, so a person can reproduce E1-E3 from it.
---

## Demo

toy/README.md lists each script with its usage line and the layout data/<set>/seed-<k>.csv and predictions/<set>/<model>-<k>.csv, so a person can reproduce E1-E3 from it.

## Notes

Document what the scripts do as written; do not change them.
