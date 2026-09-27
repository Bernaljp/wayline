# 69 - No bytecode in a touch set

**What to build:** A worker's own Python runs leave no `__pycache__/` in its worktree, and bytecode never counts as work a worker left uncommitted.

Today the conductor fails an attempt that leaves an untracked file inside its touch set. A `__pycache__/` that the worker's own `python` run writes under a touched package is such a file. 51's documentarian hit this on the toy project, whose `.gitignore` has no `__pycache__/` entry (`docs/verification/m7.md`, "What differed, and what it found in the harness", item 2). No worker launch sets `PYTHONDONTWRITEBYTECODE`. Only the documentarian avoids the trap, because its protocol now says `python3 -B`, and the coder is still exposed.

**Blocked by:** None - can start immediately. Every module it edits is built.

**Status:** ready-for-agent

**GitHub:** [#166](https://github.com/Bernaljp/wayline/issues/166) (mirror; the local file is the source)

**Milestone:** after M7 (v1.0.1). **Spec:** Implementation Decisions 3 (the worker launcher), 5 (the conductor: the branch, not the working tree, is integrated), 4 (the touch set); 51's live record in `docs/verification/m7.md`.

- [ ] Every `LaunchRequest` sets `PYTHONDONTWRITEBYTECODE=1` beside `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP`, unless its `env` already names the variable.
- [ ] The check that fails an attempt for work left uncommitted ignores `__pycache__/` directories and `*.pyc` files inside the touch set, as it already ignores untracked files outside it. Any other untracked file inside the touch set still fails the attempt.
- [ ] Tests:
  - a launch request's environment carries the variable, and keeps a value the caller set;
  - an attempt that leaves `pkg/__pycache__/mod.cpython-312.pyc` under a touched `pkg/` is integrated;
  - an attempt that leaves `pkg/new.py` untracked there is still failed.
- [ ] The changelog names the change under the next release.
- [ ] `python -m unittest` passes.
