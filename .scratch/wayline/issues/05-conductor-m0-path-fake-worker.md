# 05 - The conductor's M0 path with the fake worker

**What to build:** `wayline run` takes a project with one open ticket, adds a worktree, assembles the prompt, launches the worker through the launcher seam, validates the result, runs the machine acceptance in the worktree, rebases and fast-forwards `main`, reruns acceptance on `main`, writes the findings and the status through the ledger, journals every step, removes the worktree, and ends when the frontier is empty. With the fake backend this whole path runs in the test suite in seconds and on a fixture project from the command line; the live run is ticket 06.

**Blocked by:** 02 (init lays out a project and status reads it), 03 (Worker launcher seam with fake and claude_cli backends), 04 (Guards, per-launch settings, and accept)

**Status:** ready-for-agent

**Milestone:** M0 Skeleton. **Spec:** Implementation Decisions 1 (roles), 3 (prompt assembly), 5 (process, wave, worker outcome, integration for the conflict-free case, context packs); Testing Decisions seam 4.

- [ ] `roles/coder/agent.md` and `roles/coder/wayline.json` exist with the system prompt, no `tools` field, and the default `allowed_tools` and `disallowed_tools` of Implementation Decisions 4; the conductor composes `agent.json` (description, prompt, model alias, effort, maxTurns, permissionMode) from them.
- [ ] The prompt is assembled in the Implementation Decisions 3 order: one `/wayline-<skill>` line per assigned skill, the ticket restated, the context pack under locator headers cut at the tier's cap with the cut announced, the role protocol from `prompts/`, the result schema instruction, and the contract lines (touch set, `wayline accept`, commit on the branch, never integrate or close or edit `research/`, at most five consultant questions).
- [ ] A wave (one pass, called directly by tests) regenerates `graph.json`, computes the frontier, adds `.worktrees/<id>` on `ticket/<id>` from `main`, launches through the seam, journals `ticket_launched` and `ticket_session`, and on a final result: validates it (invalid: resume once with the error), runs acceptance in the worktree (fail: resume once with the output), rebases, reruns acceptance as `rebased`, fast-forwards `main`, reruns acceptance as `main`, writes findings and `ticket_done`, journals `acceptance` and `integrated`, deletes the branch and the worktree, commits ledger changes as `ledger: wave <n>`, and journals `run_ended` with `frontier_empty` when nothing is left.
- [ ] `wayline run` refuses to start when `git status --porcelain` on `main` shows changes outside `research/`, printing what to do.
- [ ] `fixtures/projects/one-ticket/` holds a project with one trivial `code` ticket (write one file, one machine criterion); the test suite runs the whole path on it with the fake worker (scripted to commit the file) and asserts the journal sequence, the fast-forwarded commit, and the removed worktree; the same runs from the shell with `WAYLINE_LAUNCHER=fake wayline run`.
- [ ] The resume-once paths (invalid result, failed acceptance) and the refuse-on-dirty-main path have tests.
