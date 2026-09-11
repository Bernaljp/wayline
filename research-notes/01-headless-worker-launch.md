# 01 Headless worker launch facts (Claude Code 2.1.268)

Resolves ticket `.scratch/harness/issues/01-headless-worker-launch.md`. Sources: `claude --help` (2.1.268), the official docs at https://code.claude.com/docs/en/ (pages named per claim), and three `claude -p` smoke launches on 2026-09-11 (`--model sonnet --effort low`, scratch repo under `.scratch/smoke/01/`, deleted afterwards). "Verified" means observed in the smoke test; "docs" means stated in the official docs; "unverified" means neither.

## Answer

**Launch command that worked** (launch 2, from the project root; full envelope in the last section):

```bash
claude -p "$(cat prompt.md)" \
  --agents "$(cat agent.json)" --agent worker \
  --model sonnet --effort low --permission-mode dontAsk --permission-prompts none \
  --allowedTools "Bash(pwd)" "Bash(git branch *)" \
  --disallowedTools "Read" "Edit" "Write" "Grep" "Glob" "WebFetch" "WebSearch" "Agent" \
  --output-format json --json-schema "$(cat schema.json)" \
  --fallback-model sonnet < /dev/null > result.json
```

with `agent.json` = `{"worker": {"description": "...", "prompt": "<system prompt>", "model": "sonnet", "maxTurns": 6, "skills": ["smoke-skill"], "permissionMode": "dontAsk", "effort": "low"}}`. Exit 0, wall 7 s, `total_cost_usd` 0.094.

1. **Envelope.** The validated object is in `structured_output` (verified). Also present: `type: "result"`, `subtype: "success"`, `is_error`, `num_turns`, `session_id`, `duration_ms`, `duration_api_ms`, `total_cost_usd`, `usage` (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, ...), `modelUsage` (per model: `inputTokens`, `outputTokens`, `costUSD`, ...), `result` (the same object serialized as a string), `permission_denials`, `stop_reason`, `terminal_reason`, `uuid`. A schema-validation failure is `subtype: "error_max_structured_output_retries"` (docs); a run can also end `subtype: "success"` with **no** `structured_output` key and exit 0 (verified in launch 1), so the conductor must test for the key, not the subtype.
2. **Trap: the agent's `tools` allowlist silently disables structured output.** Structured output is produced by a `StructuredOutput` tool the model must call (verified in the transcript). With `"tools": ["Bash"]` in the agent JSON, only `Bash` was offered, no `structured_output` came back, and the run still reported success (launch 1). Omitting `tools` and restricting with `--disallowedTools` instead (launch 2) restored it. Listing `"StructuredOutput"` inside `tools` is the other plausible fix (unverified).
3. **`--agents` fields.** `description`, `prompt`, `tools`, `disallowedTools`, `model`, `permissionMode`, `mcpServers`, `hooks`, `maxTurns`, `skills`, `initialPrompt`, `memory`, `effort`, `background`, `isolation` (docs). Invalid JSON or schema exits 1 with `Error: Invalid --agents configuration:`; the check is skipped on `--resume`/`--continue` (docs).
4. **Skills.** Project `.claude/skills/` (cwd up to the repository root), `~/.claude/skills/`, plugins, and `.claude/skills/` of any `--add-dir` directory are all discovered and listed (verified for project and user skills: the listing in the transcript contained both). **But `skills: [...]` in `--agents` did not preload the skill content when the agent runs as the main session via `--agent`** (launches 1 and 2: token UNKNOWN even with the skill listed). What works: put `/smoke-skill` on the first line of the prompt; Claude Code expands it before the run (launch 3: token returned). For a harness-global skill directory, `--add-dir "$HARNESS"` loads its `.claude/skills/` (docs; also grants file access there), `--plugin-dir` loads it namespaced as `plugin:skill`, or symlink it into the project's `.claude/skills/`.
5. **Worktree discovery: NOT inherited.** With cwd `<repo>/.worktrees/t1` and the worktree's own copies of `.claude/` and `CLAUDE.md` removed, neither the main checkout's `.claude/skills/smoke-skill` nor its `CLAUDE.md` reached the worker (launch 1: both UNKNOWN); from the main checkout root the `CLAUDE.md` token came back (launch 2). Discovery stops at the worktree's own git root. What a worktree does share: saved approvals in the main checkout's `.claude/settings.local.json`, project-scope plugins, `.git` (docs). Hooks and other `.claude/settings.json` keys load from cwd only, "with no parent-directory fallback" (docs). Practical rule: everything a worker needs must be tracked in the branch the worktree checks out, or passed explicitly (`--settings <file>`, `--agents`, `--add-dir <project>`; CLAUDE.md from `--add-dir` only with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`). `--setting-sources` only picks among `user,project,local`; it adds no directory.
6. **Allowlist syntax.** `Tool` or `Tool(specifier)`; `Bash(git *)` prefix (trailing ` *` also matches the bare `git`), `Bash(git:*)` equivalent only at the end of a pattern, exact `Bash(npm run build)`; `Edit(src/**)` and `Read(./.env)` gitignore-style (`Write(...)`/`Glob(...)` path rules are never consulted, use `Edit`/`Read`); `WebFetch(domain:x)`; `mcp__server`, `mcp__server__tool`, `mcp__server__*`; `Agent(name)`. Order: deny, then ask, then allow; a deny at any level (managed, user, project, `--disallowedTools`) cannot be overridden by `--allowedTools`. Composition: `--tools` limits which built-in tools exist; agent `tools` is an allowlist of what the agent gets (removes everything else, `disallowedTools` applied first; an entry with a specifier removes the whole tool); `--allowedTools` only auto-approves. `--disallowedTools "Edit"` removes the tool; `--disallowedTools "Bash(rm *)"` denies only matching calls.
7. **Nested launch works.** All three launches ran from inside a running Claude Code session (`CLAUDECODE=1`, `CLAUDE_CODE_CHILD_SESSION=1` in env): no guard, exit 0, and the transcript was written to `~/.claude/projects/<cwd-slug>/<session_id>.jsonl` (verified). The docs say the inherited child marker turns transcripts off only for an *interactive* nested session; `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1` forces saving. Redirect stdin (`< /dev/null`) or the run waits 3 s and prints a stdin warning to stderr (verified).
8. **Resume.** `claude -p "<failure message>" --resume <session_id>` continued the worker in the same `session_id`, honored `--json-schema`, and returned `structured_output` (launch 3). `num_turns` is per run, not cumulative. Re-pass `--agents`, `--settings`, `--mcp-config`, `--add-dir`, `--plugin-dir`, `--fallback-model`, `--permission-mode` on resume (docs: not restored; a `-p` resume starts in the mode a fresh `-p` run would). The `--agent` choice is restored (docs). `--session-id <uuid>` pins the id (help; collision behavior unverified). `--no-session-persistence` writes no transcript, so the session cannot be resumed (help, docs). `--system-prompt-snapshot on` (default) records the system prompt on the first request and reuses it on every resume even if different `--agents` prompt text is passed, until compaction; pass `off` to rebuild each request (help, docs).
9. **`--permission-prompts none` with `--permission-mode dontAsk`.** `dontAsk` already denies every call that would prompt; `none` additionally tells the model nobody can approve and not to retry, removes `AskUserQuestion`, and cancels unanswered MCP elicitations. Denials appear in `permission_denials` (verified empty). Requires 2.1.259+ (docs).
10. **Flags that differ from the docs.** `--max-turns` is absent from `claude --help` but the parser accepts it (verified with `--version`); the docs list it as print-mode only. `--permission-mode` help lists `manual` where docs also accept `default`. `--effort` help lists `low..max`; docs add `ultracode`.

## Details and sources

### Q1 `--agents` fields and skill resolution

- Field list: https://code.claude.com/docs/en/sub-agents ("The `--agents` flag accepts JSON with a `prompt` field plus these frontmatter fields: `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `mcpServers`, `hooks`, `maxTurns`, `skills`, `initialPrompt`, `memory`, `effort`, `background`, and `isolation`. ... Each top-level key in the JSON is the agent's name. Don't start a name with `-`."). `model` accepts `sonnet`, `opus`, `haiku`, `fable`, a full id, or `inherit`; `permissionMode` accepts `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`, `manual`; `effort` accepts `low`..`max`; `maxTurns` marks output partial when reached.
- Validation: https://code.claude.com/docs/en/errors#invalid-agents-configuration ("exits with code 1 ... When you pass `--safe-mode`, `--resume`, or `--continue` ... Claude Code doesn't check the value").
- Skill locations and precedence: https://code.claude.com/docs/en/skills (enterprise > personal `~/.claude/skills` > project `.claude/skills` > bundled; plugins namespaced `plugin:skill`; `--add-dir` directories' `.claude/skills/` load with live reload; "Claude Code loads project skills from `.claude/skills/` in the directory where you start it and in every parent directory up to the repository root").
- `--add-dir` loads skills, commands, and agents but not general file access or CLAUDE.md: https://code.claude.com/docs/en/permissions#additional-directories-grant-file-access-not-configuration (CLAUDE.md "Only when `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` is set"; skills from added directories load through the `project` setting source, so `--setting-sources` without `project` drops them). Bare mode still loads `--add-dir` skills: https://code.claude.com/docs/en/headless#start-faster-with-bare-mode.
- `skills` preload semantics per docs: "The full content of each listed skill is injected into the subagent's context at startup" (sub-agents page). Observed: not injected for the `--agent` main-session case in 2.1.268 (launches 1 and 2; transcripts contained the skill in the skill index list but never its body). `/skill-name` in the prompt is documented for `-p`: https://code.claude.com/docs/en/headless ("include `/skill-name` in the prompt string and Claude Code expands it before running"), verified in launch 3.

### Q2 worktree discovery

- Observed (launch 1 vs 2) as summarized above. The environment snapshot in the transcript recorded `"isWorktree": true`.
- Skills: "Claude Code treats git worktrees and subdirectories the same way: it discovers skills from the current working directory up to the repository root" (https://code.claude.com/docs/en/skills). For a linked worktree, the repository root is the worktree itself, so a parent main checkout is not a parent for discovery.
- CLAUDE.md: loaded "from your current working directory and every directory above it" (https://code.claude.com/docs/en/memory#how-claude-md-files-load); observed not to cross the worktree boundary in launch 1 (unverified whether a plain subdirectory outside any repo behaves differently).
- Settings: "Hooks and other `.claude/settings.json` keys load from the current working directory's `.claude/` folder with no parent-directory fallback ... `.claude/settings.local.json` loads from the git repository root instead" and in a worktree "it uses the file at the main checkout's root" (https://code.claude.com/docs/en/permissions, https://code.claude.com/docs/en/settings#where-claude-code-looks-for-each-file).
- Shared with the main checkout: `.git`, project-scope plugins, permission approvals (https://code.claude.com/docs/en/worktrees#what-worktrees-share-with-the-main-checkout). `.worktreeinclude` copies gitignored files into worktrees Claude creates, not into ones made with `git worktree add`.
- `-p --worktree` skips the trust check and does not clean up its worktree (https://code.claude.com/docs/en/worktrees).
- `--setting-sources`: "Comma-separated list of setting sources to load (`user`, `project`, `local`)" (help, https://code.claude.com/docs/en/cli-reference).

### Q3 envelope and validation failure

- `structured_output` field: https://code.claude.com/docs/en/headless#get-structured-output; verified in launches 2 and 3.
- Failure subtype `error_max_structured_output_retries`, and "A result can also end with subtype `success` but no `structured_output` value ... Treat that case as a failure as well": https://code.claude.com/docs/en/agent-sdk/structured-outputs#error-handling. Exit code on a retry-exhausted failure: unverified (docs only say non-zero on failed runs in general).
- Invalid schema: "exits with `Error: --json-schema is not a valid JSON Schema` followed by the validator's diagnostic"; `format` is accepted as an annotation only; schemas validated as draft-07 (headless and structured-outputs pages).
- Cost fields are client-side estimates (headless page).

### Q4 allowlist syntax and composition

- Rule syntax, evaluation order, Bash wildcard rules, `:*` equivalence, MCP patterns, Read/Edit gitignore anchors, `Write`/`Glob` path rules ignored: https://code.claude.com/docs/en/permissions#permission-rule-syntax and the sections that follow it.
- `--allowedTools` vs `--tools`: https://code.claude.com/docs/en/cli-reference (`--allowedTools`: "Tools that execute without prompting for permission ... To restrict which tools are available, use `--tools` instead"; `--tools`: "Restrict which built-in tools Claude can use ... doesn't affect MCP tools"; `--disallowedTools`: bare name removes the tool, scoped rule denies only matching calls).
- Agent `tools`/`disallowedTools`: https://code.claude.com/docs/en/sub-agents ("If both are set, `disallowedTools` is applied first, then `tools` is resolved against the remaining pool"; a specifier entry in `disallowedTools` "still removes the whole tool"; use `permissions.deny` for command-level Bash denies). Verified: `tools: ["Bash"]` left only `Bash` in the offered tool list.
- Precedence: "If a tool is denied at any level, no other level can allow it. For example, a managed settings deny can't be overridden by `--allowedTools`" (permissions page).

### Q5 nested launch

- No documented guard. `CLAUDECODE=1` and `CLAUDE_CODE_CHILD_SESSION=1` are informational markers (https://code.claude.com/docs/en/env-vars). Transcript suppression applies to "an interactive session that inherits it" and is overridden by `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1` (https://code.claude.com/docs/en/errors#transcript-saving-is-off-child-session-marker). Verified: all three `-p` launches ran nested and wrote transcripts.
- `-p` rejects `--bg` (headless page). Background subagents keep `-p` open until they finish, capped by `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` (default 10 min idle).

### Q6 resume, session id, persistence, snapshot

- `claude -p "..." --resume <id>` and cross-directory lookup since 2.1.223: https://code.claude.com/docs/en/headless#continue-conversations; verified in launch 3.
- Not restored on resume: `--mcp-config`, `--settings`, `--plugin-dir`, `--fallback-model`, `--add-dir`; agent choice restored; `-p` resume starts in the mode a new `-p` run would: https://code.claude.com/docs/en/sessions#what-a-resumed-session-restores.
- `--session-id <uuid>` (help). `--no-session-persistence`: "sessions will not be saved to disk and cannot be resumed (only works with --print)" (help); `CLAUDE_CODE_SKIP_PROMPT_HISTORY` does the same in any mode (cli-reference).
- `--system-prompt-snapshot`: help text and https://code.claude.com/docs/en/cli-reference#system-prompt-flags-in-resumed-conversations. In bare mode recording is off unless `on` is passed.
- Transcript path: `~/.claude/projects/<cwd with non-alphanumerics replaced by ->/<session-id>.jsonl` (https://code.claude.com/docs/en/sessions#where-transcripts-are-stored); verified.

### Q7 `--permission-prompts none` with `dontAsk`

- https://code.claude.com/docs/en/headless#turn-off-permission-prompts-in-unattended-runs and the `dontAsk` bullet on the same page. Read-only commands and reads inside working directories still run under `dontAsk`; `AskUserQuestion` and MCP `requiresUserInteraction` tools are denied even when allowed.

## Smoke test record

Scratch repo: `.scratch/smoke/01/repo` (git init, one commit containing `.claude/skills/smoke-skill/SKILL.md` with token `SKILL-TOKEN-7F3A`, `CLAUDE.md` with token `CLAUDEMD-TOKEN-9B2C`, `.gitignore` with `.worktrees/`), worktree `.worktrees/t1` on branch `ticket/t1` with its own copies of `.claude/` and `CLAUDE.md` deleted. Repo, worktree, and their transcript directories were deleted afterwards.

Shared files:

```
schema.json
{"type":"object","properties":{"skill_token":{"type":"string"},"report":{"type":"string"}},"required":["skill_token","report"],"additionalProperties":false}

prompt.md
Run exactly two shell commands: `pwd` and `git branch --show-current`. Then return the structured result. skill_token: the smoke skill token if it is already in your context, else UNKNOWN. report: the CLAUDE.md token if it is already in your context (else UNKNOWN), then "|", then the pwd output, then "|", then the branch name. Do not read any files.
```

### Launch 1 (cwd = worktree, agent with `tools: ["Bash"]`)

```bash
cd repo/.worktrees/t1
claude -p "$(cat prompt.md)" \
  --agents '{"worker": {"description": "Smoke-test worker for the SpecDrivenResearch harness.", "prompt": "You are a smoke-test worker. Answer only from what is already in your context plus the two shell commands you are told to run. Never read, cat, grep, or open any file. If you do not know a token, answer UNKNOWN.", "model": "sonnet", "tools": ["Bash"], "maxTurns": 6, "skills": ["smoke-skill"], "permissionMode": "dontAsk", "effort": "low"}}' --agent worker \
  --model sonnet --effort low --permission-mode dontAsk --permission-prompts none \
  --allowedTools "Bash(pwd)" "Bash(git branch *)" \
  --output-format json --json-schema "$(cat schema.json)" --fallback-model sonnet
```

exit 0; stderr: `Warning: no stdin data received in 3s, proceeding without it ...`; wall 8.3 s. Raw envelope (no `structured_output` key):

```json
{"duration_api_ms":4683,"stop_reason":"end_turn","session_id":"66c03632-0d1d-43d9-ade2-ef09678eed88","total_cost_usd":0.027768599999999997,"usage":{"input_tokens":4,"cache_creation_input_tokens":5831,"cache_read_input_tokens":5533,"output_tokens":228,"output_tokens_details":{"thinking_tokens":0},"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":5831,"ephemeral_5m_input_tokens":0},"inference_geo":"not_available","iterations":[{"input_tokens":2,"output_tokens":78,"cache_read_input_tokens":5533,"cache_creation_input_tokens":298,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":298},"type":"message"}],"speed":"standard"},"modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":980,"outputTokens":14,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"webSearchRequests":0,"costUSD":0.00105,"contextWindow":200000,"maxOutputTokens":32000,"thinkingTokens":0,"canonicalModel":"claude-haiku-4-5","provider":"firstParty","costBasis":"list"},"claude-sonnet-5":{"inputTokens":4,"outputTokens":228,"cacheReadInputTokens":5533,"cacheCreationInputTokens":5831,"webSearchRequests":0,"costUSD":0.026718599999999995,"contextWindow":1000000,"maxOutputTokens":64000,"thinkingTokens":0,"canonicalModel":"claude-sonnet-5","provider":"firstParty","costBasis":"list"}},"permission_denials":[],"terminal_reason":"completed","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0,"spawned_by_subagents":0,"completed":0,"failed":0,"killed":{"parent":0,"user":0,"system":0},"refused":{"depth_limit":0,"concurrency_limit":0,"budget":0},"by_type":{}},"is_error":false,"num_turns":3,"subtype":"success","api_error_status":null,"result":"skill_token: UNKNOWN\nreport: UNKNOWN|/home/bernaljp/Documents/SpecDrivenResearch/.scratch/smoke/01/repo/.worktrees/t1|ticket/t1","ttft_ms":1552,"type":"result","duration_ms":3713,"uuid":"ef8914fd-d5cd-4cbe-80ee-856680f0f66e","ttft_stream_ms":1079,"time_to_request_ms":35,"first_content_frame_ms":1079,"queued_turn_count":0,"result_index":0}

```

### Launch 2 (cwd = main checkout root, no `tools` in the agent, `--disallowedTools` instead, `< /dev/null`)

Command as in the Answer section. exit 0; stderr empty; wall 7.1 s. Raw envelope:

```json
{"duration_api_ms":6510,"stop_reason":"tool_use","session_id":"83508b6e-7d57-40cc-9243-83174fde6613","total_cost_usd":0.09429700000000002,"usage":{"input_tokens":4,"cache_creation_input_tokens":21741,"cache_read_input_tokens":21600,"output_tokens":196,"output_tokens_details":{"thinking_tokens":0},"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":21741,"ephemeral_5m_input_tokens":0},"inference_geo":"not_available","iterations":[{"input_tokens":2,"output_tokens":139,"cache_read_input_tokens":21600,"cache_creation_input_tokens":141,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":141},"type":"message"}],"speed":"standard"},"modelUsage":{"claude-haiku-4-5-20251001":{"inputTokens":980,"outputTokens":13,"cacheReadInputTokens":0,"cacheCreationInputTokens":0,"webSearchRequests":0,"costUSD":0.001045,"contextWindow":200000,"maxOutputTokens":32000,"thinkingTokens":0,"canonicalModel":"claude-haiku-4-5","provider":"firstParty","costBasis":"list"},"claude-sonnet-5":{"inputTokens":4,"outputTokens":196,"cacheReadInputTokens":21600,"cacheCreationInputTokens":21741,"webSearchRequests":0,"costUSD":0.09325200000000002,"contextWindow":1000000,"maxOutputTokens":64000,"thinkingTokens":0,"canonicalModel":"claude-sonnet-5","provider":"firstParty","costBasis":"list"}},"permission_denials":[],"terminal_reason":"completed","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0,"spawned_by_subagents":0,"completed":0,"failed":0,"killed":{"parent":0,"user":0,"system":0},"refused":{"depth_limit":0,"concurrency_limit":0,"budget":0},"by_type":{}},"is_error":false,"num_turns":3,"subtype":"success","api_error_status":null,"result":"{\"skill_token\":\"UNKNOWN\",\"report\":\"CLAUDEMD-TOKEN-9B2C|/home/bernaljp/Documents/SpecDrivenResearch/.scratch/smoke/01/repo|main\"}","structured_output":{"skill_token":"UNKNOWN","report":"CLAUDEMD-TOKEN-9B2C|/home/bernaljp/Documents/SpecDrivenResearch/.scratch/smoke/01/repo|main"},"ttft_ms":2571,"type":"result","duration_ms":5569,"uuid":"42779ed4-54e2-4782-8878-17605a1759a2","ttft_stream_ms":2339,"time_to_request_ms":63,"first_content_frame_ms":2340,"queued_turn_count":0,"result_index":0}

```

### Launch 3 (resume of launch 2 with a `/smoke-skill` prefixed failure message)

```bash
cd repo
claude -p "$(cat prompt3.md)" --resume 83508b6e-7d57-40cc-9243-83174fde6613 \
  --agents "$(cat agent2.json)" --agent worker \
  --model sonnet --effort low --permission-mode dontAsk --permission-prompts none \
  --allowedTools "Bash(pwd)" "Bash(git branch *)" \
  --disallowedTools "Read" "Edit" "Write" "Grep" "Glob" "WebFetch" "WebSearch" "Agent" \
  --output-format json --json-schema "$(cat schema.json)" --fallback-model sonnet < /dev/null
```

`prompt3.md`:

```
/smoke-skill
Your previous result was rejected: skill_token was UNKNOWN. Retry. Run exactly one shell command: `git branch --show-current`. Return the structured result again. skill_token: the smoke skill token if it is now in your context, else UNKNOWN. report: the CLAUDE.md token if in your context (else UNKNOWN), then "|", then the branch name. Do not read any files.
```

exit 0; stderr empty; wall 6.9 s. Raw envelope:

```json
{"duration_api_ms":4915,"stop_reason":"tool_use","session_id":"83508b6e-7d57-40cc-9243-83174fde6613","total_cost_usd":0.0132278,"usage":{"input_tokens":4,"cache_creation_input_tokens":696,"cache_read_input_tokens":44079,"output_tokens":162,"output_tokens_details":{"thinking_tokens":0},"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":696,"ephemeral_5m_input_tokens":0},"inference_geo":"not_available","iterations":[{"input_tokens":2,"output_tokens":109,"cache_read_input_tokens":22338,"cache_creation_input_tokens":99,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":99},"type":"message"}],"speed":"standard"},"modelUsage":{"claude-sonnet-5":{"inputTokens":4,"outputTokens":162,"cacheReadInputTokens":44079,"cacheCreationInputTokens":696,"webSearchRequests":0,"costUSD":0.0132278,"contextWindow":1000000,"maxOutputTokens":64000,"thinkingTokens":0,"canonicalModel":"claude-sonnet-5","provider":"firstParty","costBasis":"list"}},"permission_denials":[],"terminal_reason":"completed","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0,"spawned_by_subagents":0,"completed":0,"failed":0,"killed":{"parent":0,"user":0,"system":0},"refused":{"depth_limit":0,"concurrency_limit":0,"budget":0},"by_type":{}},"is_error":false,"num_turns":3,"subtype":"success","api_error_status":null,"result":"{\"skill_token\":\"SKILL-TOKEN-7F3A\",\"report\":\"CLAUDEMD-TOKEN-9B2C|main\"}","structured_output":{"skill_token":"SKILL-TOKEN-7F3A","report":"CLAUDEMD-TOKEN-9B2C|main"},"ttft_ms":2877,"type":"result","duration_ms":5336,"uuid":"b2068f06-b39b-4d00-9121-b4e009584800","ttft_stream_ms":2666,"time_to_request_ms":80,"first_content_frame_ms":2667,"queued_turn_count":0,"result_index":0}

```
