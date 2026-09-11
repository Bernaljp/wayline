# 02 - init lays out a project and status reads it

**What to build:** The owner runs `wayline init <path>` and gets a project the harness can serve: the CLAUDE.md block, `harness.json` with the pinned tag and every default, the `research/` skeleton, the symlinks that make harness skills and workflow scripts visible, the `.gitignore` entries, a git repository when there was none, an entry in the per-machine project list, and the active pointer. `wayline status` then reads any project back (frontier, running tickets and jobs, open decision tickets, window status, goal progress, the last ten events) without a dashboard, and `wayline switch <path>` moves the pointer. Running `init` twice changes nothing the second time.

**Blocked by:** 01 (Package skeleton, frontmatter parser, schema validator, ledger core)

**Status:** ready-for-agent

**GitHub:** [#3](https://github.com/Bernaljp/wayline/issues/3) (mirror; the local file is the source)

**Milestone:** M0 Skeleton. **Spec:** Implementation Decisions 1 (project layout, per-machine pointers, the command), 2 (graph.json), 14 (defaults).

- [ ] `wayline init <path>` creates the project layout of Implementation Decisions 1: `CLAUDE.md` block (appended, never overwriting an existing file), `harness.json` (harness_tag from the checkout, autonomy `checkpoints`, radius `moderate`, reservations no GPU, 8 cores, 64 GB, pacing 0.90 and 0.80, dashboard port 8765, notify block, empty policy overrides), the `research/` tree with `INTAKE.md` template, empty `journal.jsonl`, `findings.jsonl`, `manifest.json`, `graph.json`, and `.gitignore` entries for `.worktrees/`, `results/`, `research/.cache/`, and `research/sessions/*/*/stream.jsonl`.
- [ ] `init` symlinks every directory under the harness `skills/` into `<project>/.claude/skills/` and every script under `workflows/` into `<project>/.claude/workflows/`, and refreshes stale symlinks on a second run.
- [ ] `init` runs `git init` and a first commit when the directory is not a repository, and leaves an existing repository alone.
- [ ] `init` writes `~/.wayline/projects.json` (path, name, harness_tag, created) and `~/.wayline/active`; both live outside the harness repository and outside the project.
- [ ] Running `init` twice on the same path is a no-op the second time (a test hashes the tree before and after).
- [ ] `wayline status` prints the frontier, running tickets and jobs, open decision tickets, window status, goal progress, and the last ten journal events for the active project or `--project <path>`, and works on a fixture ledger under `fixtures/ledger/` that holds tickets in every status.
- [ ] `graph.json` is regenerated from `tickets/` by code on every `status` (and later every wave) when an `os.scandir` snapshot shows a change, holding only the scheduling fields of Implementation Decisions 2.
- [ ] `wayline switch <path>` moves the pointer and journals `switched` in both projects (the drain of a running conductor arrives with ticket 09).
- [ ] Tests cover init, idempotence, status over the fixture ledger, and switch, offline.
