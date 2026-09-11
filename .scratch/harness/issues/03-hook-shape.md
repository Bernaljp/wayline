# 03 — Hook shape for the worker guards

Type: research
Status: resolved
Blocked by: None
Brief: Section 5.4, C7, Appendix B; fog: the hook shape

## Question

From the official hooks reference, establish:

1. The settings JSON for `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `SessionStart`, `PreCompact` with matcher syntax (exact tool names, pipe alternation, regex).
2. The stdin JSON a hook receives: `session_id`, `cwd`, `tool_name`, `tool_input` fields for `Write`, `Edit`, `MultiEdit`, `Bash`, `NotebookEdit`; `stop_hook_active` on `Stop`.
3. The output contract: exit 0 / 2, stderr fed back to the model, JSON on stdout (`decision: block` with `reason`, `hookSpecificOutput.permissionDecision` allow/deny/ask, `updatedInput`, `additionalContext`), timeouts, and how several hooks on one event combine.
4. Whether hooks passed through `--settings <file>` apply in `-p` sessions and inside `--agents` subagents, and which environment variables a hook can rely on (`CLAUDE_PROJECT_DIR`, others).
5. Whether `permissions.deny` rules (`Bash(git push*)`, `Bash(rm -rf*)`, `Write(/etc/**)`) can replace the command guard for part of the irreversible list, and how deny rules interact with `dontAsk`.

Include a minimal touch-set guard (reads `TICKET_TOUCHES`, exits 2 with a message on a path outside it) and a stop guard sketch, both validated against the documented stdin shape by piping a hand-written stdin JSON into them.

Deliverable: `research-notes/03-hook-shape.md`.

## Answer

Settings shape is `{"hooks": {"PreToolUse": [{"matcher": "Write|Edit|NotebookEdit", "hooks": [{"type": "command", "command": "<abs path>", "args": [], "timeout": 30}]}], "Stop": [{"hooks": [...]}]}}`; matchers are exact tool names with `|` or `,` alternation, or an unanchored JS regex when any other character appears; `Stop` takes no matcher.
Stdin always has `session_id`, `cwd`, `hook_event_name`, `permission_mode`, `transcript_path`, `prompt_id`, `effort`; PreToolUse adds `tool_name`, `tool_input`, `tool_use_id`. `tool_input.file_path` (Write, Edit) is always absolute; NotebookEdit uses `notebook_path`; `MultiEdit` is a legacy name with no current tool. Stop adds `stop_hook_active` and `last_assistant_message`.
Output: exit 0 = no decision, exit 2 = block with stderr fed to Claude (denial reason on PreToolUse, continue reason on Stop); PreToolUse JSON is `hookSpecificOutput.permissionDecision` allow/deny/ask with `permissionDecisionReason`, `updatedInput`, `additionalContext`; Stop, PostToolUse, PreCompact use top-level `{"decision":"block","reason":...}`. Default timeout 600 s and a timed-out PreToolUse hook does not block, so set a short explicit timeout. Parallel hooks combine to the most restrictive decision; Stop blocks are capped at 8 in a row.
`--settings` hooks apply in `-p` (verified by one smoke launch on 2.1.268: Write denied, file absent, stderr echoed back by the model) and, per the docs, inside subagents with `agent_id`/`agent_type` in the input (not smoke-tested). Hooks see `CLAUDE_PROJECT_DIR` (session-start root, does not follow a mid-session worktree), `CLAUDE_EFFORT`, and the parent environment, so `TICKET_TOUCHES` exported at launch is visible.
`permissions.deny` is a valid first layer for the literal irreversible list (`Bash(git push *)`, `Bash(git reset --hard *)`, `Bash(rm -rf *)`): evaluated before allow, honored in `dontAsk` and past any hook `allow`, matches subcommands and `$()`. It misses `/bin/rm`, `bash -c '...'`, `git -C . push`, and scripts, so `command_guard.sh` stays. `Write(/etc/**)` is never consulted; write `Edit(//etc/**)` (Edit rules cover Write and NotebookEdit).
Both guards were validated by piping hand-written stdin (14 cases, exit codes recorded). Full note: `research-notes/03-hook-shape.md`; scripts and example settings: `research-notes/03-hooks/`.
