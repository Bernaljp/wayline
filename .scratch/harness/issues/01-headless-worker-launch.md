# 01 — Headless worker launch facts

Type: research
Status: resolved
Blocked by: None
Brief: Section 9.2, Appendix B; fog: the exact claude -p launch

## Question

For Claude Code 2.1.268 in headless mode (`claude -p`), establish from the official docs, `claude --help`, and one cheap smoke test:

1. The `--agents` JSON: every accepted field (description, prompt, model, tools, disallowedTools, maxTurns, skills, permissionMode, effort?) and where `skills` names resolve from: project `.claude/skills`, user `~/.claude/skills`, plugins, or the harness's own `skills/` directory via a path. If only project and user scopes resolve, say how a harness-global skill reaches a worker (symlink into the project, `--plugin-dir`, `--add-dir`).
2. Whether a session whose cwd is `<project>/.worktrees/<id>` (a git worktree) still discovers `<project>/.claude/` settings, skills, agents, and CLAUDE.md, or needs `--add-dir` or `--setting-sources`.
3. With `--output-format json --json-schema <schema>`: the name of the envelope field carrying the validated object, plus `session_id`, `num_turns`, `is_error`, `duration_ms`, usage fields, and what a schema-validation failure looks like (exit code, envelope).
4. `--allowedTools` pattern syntax (`Bash(git *)`, `Edit`, `Write`, `mcp__server__tool`) and how it composes with `--tools` and the agent definition's `tools` list.
5. Whether `claude -p` can be launched from inside a running Claude Code session (any nested-session guard or environment variable), because tests and the evolve loop may do so.
6. `-p --resume <session_id>` to continue a worker with a failure message; `--session-id`; `--no-session-persistence` trade-offs; `--system-prompt-snapshot`.
7. What `--permission-prompts none` does in combination with `--permission-mode dontAsk`.

Smoke test: one `claude -p` with `--model sonnet --effort low`, a trivial inline agent with `skills: ["<a local skill created for the test>"]`, a two-field `--json-schema`, run from a scratch git repo under `.scratch/smoke/` (delete the repo afterwards; keep the command and the raw envelope in the notes).

Deliverable: `research-notes/01-headless-worker-launch.md` with the exact command that worked, the envelope, and every flag that behaved differently from the docs.

## Answer

- Launch that worked (2.1.268): `claude -p "<prompt>" --agents "$(cat agent.json)" --agent worker --model sonnet --effort low --permission-mode dontAsk --permission-prompts none --allowedTools "Bash(git branch *)" --disallowedTools "Edit" "Write" --output-format json --json-schema "$(cat schema.json)" --fallback-model sonnet < /dev/null`. Exit 0, about 7 s, 0.09 USD.
- Envelope: validated object in `structured_output`; also `subtype`, `is_error`, `num_turns`, `session_id`, `duration_ms`, `duration_api_ms`, `total_cost_usd`, `usage`, `modelUsage`, `result`, `permission_denials`. Validation failure is `subtype: error_max_structured_output_retries` (docs); a run can also return `success` with no `structured_output` key and exit 0 (verified), so check the key.
- Trap: an agent `tools` allowlist (for example `["Bash"]`) removes the `StructuredOutput` tool and the run silently returns no structured output. Omit `tools` and restrict with `--disallowedTools` / `--tools` instead.
- `--agents` fields: description, prompt, tools, disallowedTools, model, permissionMode, mcpServers, hooks, maxTurns, skills, initialPrompt, memory, effort, background, isolation. Invalid JSON exits 1; not validated on `--resume`.
- Skills: project `.claude/skills` (cwd up to repo root), `~/.claude/skills`, plugins, and `--add-dir <dir>/.claude/skills` are all discovered. `skills: [...]` did NOT inject content when the agent runs as the main session via `--agent` (verified twice). Put `/skill-name` on the first line of the prompt instead (verified). Harness-global skills reach a worker via `--add-dir "$HARNESS"`, `--plugin-dir`, or a symlink into the project's `.claude/skills`.
- Worktree cwd (`<repo>/.worktrees/<id>`) does NOT discover the main checkout's `.claude/skills` or `CLAUDE.md` (verified); discovery stops at the worktree's git root. Shared: `settings.local.json` approvals, project plugins, `.git`. Keep everything the worker needs tracked in the branch or pass it explicitly (`--settings`, `--agents`, `--add-dir`).
- Allowlist syntax: `Tool`, `Tool(spec)`, `Bash(git *)` prefix, `Edit(src/**)` gitignore-style (`Write(...)` path rules are ignored), `mcp__server__tool`, `mcp__server__*`. Order deny > ask > allow; any deny beats `--allowedTools`. `--tools` limits availability, `--allowedTools` only auto-approves.
- Nested launch: works from inside a running session (all three launches were nested), transcript is written, no guard; use `< /dev/null` to avoid the 3 s stdin wait.
- Resume: `claude -p "<failure msg>" --resume <session_id>` continues the worker with the same `session_id` and honors `--json-schema` (verified). Re-pass `--agents`, `--settings`, `--permission-mode`, `--fallback-model`. `--no-session-persistence` makes resume impossible. System prompt is snapshotted on the first request and reused on resume until compaction (`--system-prompt-snapshot off` to rebuild).
- `--permission-prompts none` + `dontAsk`: dontAsk already denies prompts; `none` adds "do not retry", removes `AskUserQuestion`, cancels MCP elicitations.
- Flags differing from docs: `--max-turns` missing from `--help` but accepted; `--permission-mode` help says `manual` where docs also take `default`.

Full notes with sources and raw envelopes: `research-notes/01-headless-worker-launch.md`.
