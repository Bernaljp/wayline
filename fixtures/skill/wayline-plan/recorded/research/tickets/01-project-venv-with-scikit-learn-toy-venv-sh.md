---
id: 1
title: Project venv with scikit-learn (toy/venv.sh)
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [toy/venv.sh, requirements.txt, .gitignore]
role: coder
skills: []
acceptance:
  machine: ["bash toy/venv.sh && .venv/bin/python -c 'import sklearn, numpy'", grep -q '^scikit-learn' requirements.txt, "grep -q '^\\.venv/' .gitignore && grep -q '^data/' .gitignore && grep -q '^predictions/' .gitignore"]
  quality: []
context_pack: [research/CONTEXT.md#language, research/DECISIONS.md#q3-scikit-learn-is-not-installed-what-fits-the-models, research/SPEC.md#methods]
origin: research/SPEC.md#methods
proposed_by: planner
demo: From a clean checkout, `bash toy/venv.sh` creates .venv/ at the project root and `.venv/bin/python -c 'import sklearn'` prints nothing and exits 0; a second run is a no-op.
---

## Demo

From a clean checkout, `bash toy/venv.sh` creates .venv/ at the project root and `.venv/bin/python -c 'import sklearn'` prints nothing and exits 0; a second run is a no-op.

## Notes

Q3: the project venv, never the tools venv. toy/venv.sh resolves the project root from its own location, runs `python3 -m venv .venv` only if .venv/ is missing, then `pip install -r requirements.txt` (scikit-learn pinned to one version, numpy). Add .venv/, data/, predictions/ to .gitignore so no ticket commits a venv, a set, or scores. CPU only; no GPU packages.

## Public API

This ticket adds public API, so a `docs` ticket follows it.
