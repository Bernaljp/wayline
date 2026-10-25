# 138 - The manifest follows a changed artifact

**What to build:** A file a run registered in `research/manifest.json` that a later integration changes keeps a provenance that resolves, so drawings, the general report, and the paper can still cite what that run found.

On the toy's live run (ticket 122, `docs/verification/m8.md`), code tickets kept editing files that earlier runs had registered (`src/toy/generate.py` for run t2-a3, `tests/test_oracle.py` for t6-a1, `tests/test_oracle_budget.py` for t53-a1, `tests/test_eval.py` for t95-a1). The manifest kept the old hashes. From then on:

- decision ticket 152 asked whether to register `tests/test_oracle_budget.py` again or pin drawing R6 to the old bytes, and R6's drawing (ticket 167) blocked on "no longer matches its t53-a1 manifest hash";
- R4's redrawing at the paper order (ticket 165) left out all three of its new plots: "provenance: src/toy/generate.py no longer has the hash the manifest holds for run t2-a3";
- the paper's independent read failed build 1 on eight claim sentences citing tests "missing from the hash-pinned files their res: tags name" (the tests had been added by later tickets, after the pinned run).

The run's own retrospective proposed the same (change record 005, "keep the manifest current when an integration changes a registered file").

- When an integration changes a file the manifest registers for an earlier run, the manifest keeps the old entry's bytes reachable (the commit they were registered at, read with `git show`) and gains the new run's entry, so a `{res:<run>/<path>#…}` tag resolves against the run it names.
- A citation of a run's file resolves against that run's bytes, never the working tree's.
- The verdict prompts say which bytes a tag pins, so a reader does not take a later file for the pinned one.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#345](https://github.com/Bernaljp/wayline/issues/345) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 2 (the manifest), 9 (the provenance linter), 17 (drawings; the paper's builds and gates); ticket 122's live record.

- [ ] Over a temporary project: a run registers a file, a later integration changes it, and a `{res:}` tag naming the first run still resolves to the first run's bytes; the drawing and the paper read checks pass on it.
- [ ] `python -m unittest` passes.
