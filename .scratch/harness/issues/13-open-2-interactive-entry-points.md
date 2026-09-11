# 13 — OPEN-2 Interactive entry points

Type: grilling
Status: resolved
Blocked by: None
Brief: OPEN-2, Section 5.5

## Question

One skill per interactive phase (intake, grill, plan, evolve, paper), or one skill with modes?

Default: one per phase. They are small, independently fixture-tested, and mirror the `bin/<cli>` verbs.

Sub-question: how do the harness's global skills become visible to an interactive session in a project? Options: `init` symlinks or copies the harness `skills/` entries into the project's `.claude/skills/` with a marker so the registry knows their scope; or the harness ships as a plugin loaded with `--plugin-dir`. Default: symlink at `init`, refreshed by `upgrade`, because it needs no plugin machinery and the worker launch can use the same path. Verified by Headless worker launch facts: skills are discovered from project `.claude/skills`, `~/.claude/skills`, plugins, and `--add-dir <dir>/.claude/skills`; the `skills` field in `--agents` did not inject content when the agent runs as the main session, whereas `/skill-name` on the prompt's first line does; a worktree cwd does not see the main checkout's `.claude/`. So workers get `--add-dir $HARNESS` plus a `/skill-name` line assembled by the conductor, and this ticket decides only the interactive path.

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

One skill per interactive phase (intake, grill, plan, evolve, paper), each small and fixture-tested, mirrored by the CLI verbs. Harness skills reach an interactive session by symlinks that `init` creates in the project's `.claude/skills/` and `upgrade` refreshes; no plugin machinery. Workers keep the verified path: `--add-dir $HARNESS` plus a `/skill-name` line on the prompt assembled by the conductor.
