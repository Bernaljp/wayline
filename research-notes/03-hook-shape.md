# 03: Hook shape for the worker guards

Resolves `.scratch/harness/issues/03-hook-shape.md`. Sources are the official Claude Code docs at
code.claude.com (fetched 2026-09-11), the local CLI (`claude --version` = 2.1.268), and one smoke
launch. Every claim carries a URL or a command. Guard scripts and a settings example live in
`research-notes/03-hooks/`.

## Answer

**Settings JSON shape.** `{"hooks": {"<Event>": [{"matcher": "<pattern>", "hooks": [{"type": "command",
"command": "<path>", "args": [], "timeout": <seconds>}]}]}}`. Matcher on tool events is the tool
name: `Bash`, `Edit|Write` (pipe or comma separated exact names), or an unanchored JavaScript regex
when any other character is present (`^Notebook`, `mcp__memory__.*`); `"*"`, `""`, or omitted matches
all. `PreToolUse`, `PostToolUse` match on tool name; `SubagentStop` on agent type; `SessionStart` on
`startup|resume|clear|compact|fork`; `PreCompact` on `manual|auto`; `Stop` has no matcher (omit it).
Set `"args": []` to run the script in exec form (no shell, placeholders like `${CLAUDE_PROJECT_DIR}`
substituted verbatim). Source: https://code.claude.com/docs/en/hooks#matcher-patterns and
https://code.claude.com/docs/en/hooks#hook-handler-fields.

**Stdin fields.** Every event: `session_id`, `transcript_path`, `cwd`, `hook_event_name`,
`permission_mode` (`"dontAsk"` in our workers), `prompt_id`, `effort.level`, plus `agent_id` and
`agent_type` inside a subagent or under `--agent`. `PreToolUse` adds `tool_name`, `tool_input`,
`tool_use_id`. `tool_input`: Write `{file_path, content}`; Edit `{file_path, old_string, new_string,
replace_all}`; Bash `{command, description, timeout, run_in_background}`; NotebookEdit
`{notebook_path, new_source, cell_id, edit_mode, cell_type}` (not in the hooks reference; the field
names come from the permissions doc and the tool schema). `MultiEdit` is not a current tool; the
permissions doc calls it "the legacy MultiEdit tool". `file_path` is always absolute for Write, Edit,
Read. `Stop` and `SubagentStop` add `stop_hook_active`, `last_assistant_message`; Stop also
`background_tasks`, `session_crons`. `SessionStart` adds `source`; `PreCompact` adds `trigger`,
`custom_instructions`. Observed on 2.1.268 in the smoke run, top-level keys of a PreToolUse Write
input: `cwd, effort, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name,
tool_use_id, transcript_path`. Sources: https://code.claude.com/docs/en/hooks#common-input-fields,
https://code.claude.com/docs/en/hooks#pretooluse-input, https://code.claude.com/docs/en/hooks#stop-input.

**Output contract.** Exit 0 = no decision (normal permission flow), exit 2 = block, and stderr is the
message: on `PreToolUse` it goes to Claude as the denial reason, on `Stop` it goes to Claude as the
reason to keep working. Any other exit code is a non-blocking error (action proceeds). JSON on stdout
is read on every exit code; exit 2 cannot be overridden by JSON. `PreToolUse` JSON:
`{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow|deny|ask|defer",
"permissionDecisionReason": "...", "updatedInput": {...}, "additionalContext": "..."}}`; the top-level
`decision: "block"` form is deprecated for PreToolUse. `Stop`, `SubagentStop`, `PostToolUse`,
`PreCompact` use top-level `{"decision": "block", "reason": "..."}` (reason required on Stop). Default
command-hook timeout is 600 s (30 s on UserPromptSubmit); a timed-out PreToolUse hook does NOT block,
the call continues, so keep guards fast and set an explicit `timeout`. All matching hooks run in
parallel, identical handlers across settings files run once, and the combined PreToolUse result is the
most restrictive (`deny` > `defer` > `ask` > `allow`); one exit-2 hook blocks even if siblings exit 0.
A Stop hook is overridden after 8 consecutive blocks; check `stop_hook_active`. Sources:
https://code.claude.com/docs/en/hooks#exit-code-output, https://code.claude.com/docs/en/hooks#pretooluse-decision-control,
https://code.claude.com/docs/en/hooks#stop-decision-control, https://code.claude.com/docs/en/hooks#timeouts,
https://code.claude.com/docs/en/hooks-guide#combine-results-from-multiple-hooks.

**Do `--settings` hooks apply in `-p` and inside subagents?** Yes to both. `--settings` sits above
user, project, and local files and below managed settings and merges by key; `-p` shows no trust
dialog and runs settings-file hooks (the docs warn about this for untrusted repos), and the smoke
launch confirmed it: `claude -p ... --permission-mode dontAsk --allowedTools Write --settings
<file>` with a PreToolUse Write hook that exits 2 produced `permission_denials` for the Write, no
file on disk, and the hook's stderr fed back to the model. Hooks from settings files, managed policy,
and plugins "all apply inside subagents, so a PreToolUse hook in settings.json also runs before every
tool a subagent uses", with `agent_id` and `agent_type` in the input; a `Stop` hook in agent
frontmatter becomes `SubagentStop`. Subagent behavior was not smoke-tested (documented only). Env
vars a hook can rely on: `CLAUDE_PROJECT_DIR` (session start root; it does NOT follow a worktree
entered mid-session, use stdin `cwd` for that), `CLAUDE_EFFORT`, `CLAUDE_CODE_REMOTE` (unset locally),
`CLAUDE_ENV_FILE` (SessionStart, Setup, CwdChanged, FileChanged only), plus the parent environment
(so `TICKET_TOUCHES` exported at launch is visible). Sources:
https://code.claude.com/docs/en/settings#settings-precedence, https://code.claude.com/docs/en/hooks#workspace-trust,
https://code.claude.com/docs/en/headless (line "Without --bare, a -p session runs the hooks in a
project's .claude/settings.json"), https://code.claude.com/docs/en/sub-agents#hooks-in-subagents,
https://code.claude.com/docs/en/hooks#reference-scripts-by-path.

**What `permissions.deny` can replace.** For exact command shapes, yes: deny rules are evaluated
first, before ask and allow, are honored in every mode including `dontAsk` and regardless of any
hook `allow`, apply to subagents, and match a subcommand anywhere in a compound command, inside
`$()`, and past leading `VAR=` assignments. But a Bash deny matches the command text only: `Bash(rm
*)` does not match `/bin/rm`, `bash -c 'rm ...'`, `find -delete`, a Python script that deletes, and
`Bash(git push *)` does not match `git -C . push`. So `permissions.deny` is a cheap first layer for
the literal irreversible list (`Bash(git push *)`, `Bash(git push)`, `Bash(git reset --hard *)`,
`Bash(rm -rf *)`), and `command_guard.sh` stays the second layer for spelling variants. Path rules:
`Write(/etc/**)` is accepted but never consulted (startup warning); write `Edit(//etc/**)` instead,
since only `Edit(path)` and `Read(path)` rules are checked, `Edit` covers Write, Edit, and
NotebookEdit, `//` means filesystem root, and `/path` means relative to the settings source. Deny
rules and `dontAsk` compose simply: `dontAsk` auto-denies anything that would prompt; a deny rule
denies even what an allow rule would pass; hooks fire before the permission check and can only
tighten. Sources: https://code.claude.com/docs/en/permissions#manage-permissions,
https://code.claude.com/docs/en/permissions#bash-rule-limits, https://code.claude.com/docs/en/permissions#read-and-edit,
https://code.claude.com/docs/en/permission-modes#allow-only-pre-approved-tools-with-dontask-mode,
https://code.claude.com/docs/en/hooks-guide#hooks-and-permission-modes.

## Details and sources

### 1. Settings JSON and matchers

Reference block (https://code.claude.com/docs/en/hooks#configuration):

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Write|Edit|NotebookEdit",
        "hooks": [ { "type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/touch_set_guard.sh", "args": [], "timeout": 30 } ] },
      { "matcher": "Bash",
        "hooks": [ { "type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/command_guard.sh", "args": [], "timeout": 30 } ] }
    ],
    "Stop": [ { "hooks": [ { "type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/stop_guard.sh", "args": [] } ] } ]
  }
}
```

- Matcher evaluation (https://code.claude.com/docs/en/hooks#matcher-patterns): `"*"`, `""`, or
  omitted = match all; only letters, digits, `_`, `-`, spaces, `,`, `|` = exact string or a `|` or
  `,` separated list (`Edit|Write`, `Edit, Write`); any other character = JavaScript regex tested
  with `RegExp.prototype.test`, unanchored, so `Edit.*` matches `NotebookEdit` and `^Edit$` is the
  whole-string form. Comma separators need v2.1.191+, hyphens in exact set need v2.1.195+.
- What each event matches: `PreToolUse`, `PostToolUse` tool name; `SubagentStop` and `SubagentStart`
  agent type (frontmatter `name`, or `general-purpose`, `Explore`, `Plan`, plugin-scoped
  `^my-plugin:reviewer$`); `SessionStart` `startup|resume|clear|compact|fork`; `PreCompact`
  `manual|auto`; `Stop` "no matcher support, always fires on every occurrence".
- Handler fields (https://code.claude.com/docs/en/hooks#hook-handler-fields): `type` (`command`,
  `http`, `mcp_tool`, `prompt`, `agent`), `if` (one permission rule, tool events only, best-effort
  filter, "use the permission system rather than a hook to enforce a hard allow or deny"),
  `timeout` (seconds), `statusMessage`, `once` (skill frontmatter only). Command hooks: `command`,
  `args` (exec form when present), `async`, `asyncRewake`, `shell`. "Set `args` whenever the hook
  references a path placeholder, since each element is passed as one argument with no quoting."
- Hook locations (https://code.claude.com/docs/en/hooks#hook-locations): `~/.claude/settings.json`,
  `.claude/settings.json`, `.claude/settings.local.json`, managed policy, plugin `hooks/hooks.json`,
  skill frontmatter, subagent frontmatter. `--settings <file-or-json>` is the command-line level of
  the same stack (https://code.claude.com/docs/en/settings#settings-precedence).
- `disableAllHooks` (https://code.claude.com/docs/en/hooks#disable-or-remove-hooks): a project can set
  it back to `false`; `--settings '{"disableAllHooks": true}'` wins over project and local files.

### 2. Stdin JSON

- Common fields table: https://code.claude.com/docs/en/hooks#common-input-fields. `permission_mode`
  values: `default`, `plan`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions` (Manual arrives
  as `default`). `effort` is present for tool-context events "when the current model supports the
  effort parameter", also exported as `$CLAUDE_EFFORT`. "A hook process inherits the parent
  environment, apart from the `OTEL_*` exporter variables".
- PreToolUse input and tool_input tables: https://code.claude.com/docs/en/hooks#pretooluse-input.
  "For the file tools Write, Edit, and Read, `tool_input.file_path` is always absolute: Claude Code
  expands `~` and relative paths before hooks run." The tables list Bash, PowerShell, Write, Edit,
  Read, Glob, Grep, WebFetch, WebSearch, Agent, AskUserQuestion, ExitPlanMode. There is no
  NotebookEdit or MultiEdit table in the hooks reference.
- NotebookEdit fields: the permissions doc names the primary content field as "`notebook_path` for
  NotebookEdit" (https://code.claude.com/docs/en/permissions#tool-specific-permission-rules, the
  paragraph beginning "You can't match a tool's primary content field this way"); the tools
  reference names `cell_id`, `edit_mode` (`replace|insert|delete`), `cell_type`
  (https://code.claude.com/docs/en/tools-reference#notebookedit-tool-behavior); the tool's JSON
  schema (ToolSearch `select:NotebookEdit` in a 2.1.268 session) lists `notebook_path` and
  `new_source` as required, plus `cell_id`, `cell_type`, `edit_mode`.
- MultiEdit: not documented as a tool anywhere in the hooks or tools reference; the permissions doc
  refers to "the legacy `MultiEdit` tool" (https://code.claude.com/docs/en/permissions#read-and-edit).
  Matching `Write|Edit|NotebookEdit` covers the current file-writing tools.
- Stop input (https://code.claude.com/docs/en/hooks#stop-input): "`stop_hook_active` is `true` when
  Claude Code is already continuing as a result of a stop hook. Check this value ... Claude Code
  overrides the hook and ends the turn after 8 consecutive blocks." Cap is adjustable via
  `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (https://code.claude.com/docs/en/hooks-guide#stop-hook-hits-the-block-cap).
- SubagentStop input (https://code.claude.com/docs/en/hooks#subagentstop): `stop_hook_active`,
  `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`.
- SessionStart input: `source`, optional `model`, `agent_type`, `session_title`
  (https://code.claude.com/docs/en/hooks#sessionstart-input). PreCompact input: `trigger`,
  `custom_instructions` (https://code.claude.com/docs/en/hooks#precompact-input).
- Observed (smoke run, 2.1.268, PreToolUse on Write under `-p --permission-mode dontAsk --effort
  low`): keys `cwd, effort, hook_event_name, permission_mode, prompt_id, session_id, tool_input,
  tool_name, tool_use_id, transcript_path`; `effort` = `{"level":"low"}`; `permission_mode` =
  `"dontAsk"`; no `scratchpad_dir` and no `agent_type` (no `--agent` was passed).

### 3. Output contract

- Exit codes (https://code.claude.com/docs/en/hooks#exit-code-output): "Claude Code reads JSON output
  fields from stdout on every exit code, not just 0 ... Exit 2's block is the one outcome JSON can't
  override." Exit 0 stderr goes to the debug log only. Exit 2: "The blocking message is the reason
  from your JSON's blocking decision when it makes one, and your stderr text otherwise." Other codes:
  non-blocking error, action proceeds, first line of stderr shown.
- Per-event exit 2 (https://code.claude.com/docs/en/hooks#exit-code-2-behavior-per-event):
  `PreToolUse` blocks the tool call; `Stop` prevents stopping; `SubagentStop` prevents the subagent
  stopping; `PostToolUse` cannot block, shows stderr to Claude; `SessionStart` shows stderr to user
  only; `PreCompact` blocks compaction.
- PreToolUse decision (https://code.claude.com/docs/en/hooks#pretooluse-decision-control):
  `permissionDecision` `allow` skips the prompt, `deny` prevents the call, `ask` prompts, `defer`
  is for `-p` wrappers; `permissionDecisionReason` is shown to Claude for `deny`; `updatedInput`
  replaces the entire input object and permission rules are evaluated against the returned input;
  `additionalContext` is added alongside the tool result. "A hook that blocks by exiting 2 routes
  the same way as `deny`". Deprecated: top-level `decision`/`reason` with `approve`/`block`.
- Stop decision (https://code.claude.com/docs/en/hooks#stop-decision-control): `decision: "block"`
  with required `reason`; or `hookSpecificOutput.additionalContext` for non-error feedback that
  also continues the conversation under the same loop protections.
- PostToolUse decision (https://code.claude.com/docs/en/hooks#posttooluse-decision-control):
  `decision: "block"` adds `reason` next to the tool result; `updatedToolOutput` replaces it.
- Timeouts (https://code.claude.com/docs/en/hooks#timeouts): default 600 s for command hooks, 30 s
  on UserPromptSubmit, PreModelSwitch, PostModelSwitch, 10 s on MessageDisplay, 1.5 s budget on
  SessionEnd. "A timed-out command, http, or mcp_tool hook doesn't block the tool call. The call
  continues through the normal permission flow, so don't count on a stalled hook to act as a gate."
- Combination (https://code.claude.com/docs/en/hooks-guide#combine-results-from-multiple-hooks):
  "every hook's command runs to completion before Claude Code merges the results. One hook returning
  deny doesn't stop sibling hooks ... For PreToolUse permission decisions, the most restrictive
  answer applies, in the order deny, defer, ask, allow. Text from additionalContext is kept from
  every hook." Multiple `updatedInput`: the last to finish wins, order non-deterministic
  (https://code.claude.com/docs/en/hooks-guide#limitations).
- Dedup (https://code.claude.com/docs/en/hooks#hook-handler-fields): "All matching hooks run in
  parallel. If you define the same handler in more than one settings file, it runs once."

### 4. `--settings`, `-p`, subagents, environment

- `--settings`: "Path to a settings JSON file or an inline JSON string. Values you set here override
  the same keys in your settings.json files for this session. Keys you omit keep their file-based
  values. The file must be a regular file no larger than 2 MiB"
  (https://code.claude.com/docs/en/cli-reference). Precedence: managed > command line (`--settings`)
  > local > project > user (https://code.claude.com/docs/en/settings#settings-precedence). List keys
  such as `permissions.allow` and `permissions.deny` are merged across scopes, not replaced
  (same page, "Precedence rules for list keys"). Note: `-p` does load user and project settings
  files by default; a summarizer claim to the contrary was checked against the raw CLI reference and
  is not in the source. Only `--restricted` "loads only managed settings and --settings", and
  `--setting-sources user,project,local` narrows the file sources.
- `-p` and hooks: "`-p` or SDK session: Claude Code never shows the dialog and treats the folder as
  trusted, so hooks committed in a repository's .claude/settings.json run in a folder you've never
  trusted" (https://code.claude.com/docs/en/hooks#workspace-trust). "Without --bare, a -p session
  runs the hooks in a project's .claude/settings.json" (https://code.claude.com/docs/en/headless).
- Smoke test (verified, 2026-09-11, 2.1.268, 10 s wall clock, from a scratch dir under
  `.scratch/smoke/03/`, deleted afterwards). Command:
  `claude -p "<write hello.txt with the Write tool>" --model sonnet --effort low --permission-mode
  dontAsk --allowedTools Write --settings ./settings.json --output-format json --max-turns 4`
  with `settings.json` = `{"hooks":{"PreToolUse":[{"matcher":"Write","hooks":[{"type":"command",
  "command":"<abs>/hooks/deny_write.sh","args":[],"timeout":20}]}]}}` and a script that dumps stdin,
  prints to stderr, and exits 2. Result: `subtype: success`, `num_turns: 2`,
  `permission_denials: [{tool_name: "Write", tool_input: {file_path: ".../hello.txt", content:
  "hi"}}]`, `hello.txt` absent, and the model's reply was `WRITE_BLOCKED: smoke: Write blocked by
  --settings PreToolUse hook`, that is, the hook's stderr line was fed back to the model. The nested
  launch needed `env -u CLAUDECODE` because the test ran from inside a Claude Code session.
- Subagents (https://code.claude.com/docs/en/sub-agents#hooks-in-subagents): "Hooks from settings
  files, managed policy settings, and plugins all apply inside subagents, so a PreToolUse hook in
  settings.json also runs before every tool a subagent uses." Input carries `agent_id`, `agent_type`.
  Frontmatter `Stop` in an agent definition "is automatically converted to SubagentStop". `--agents`
  JSON accepts `hooks` too, and hooks from `--agents` definitions "run without" the trust step.
  Permission inheritance: in `default`, `dontAsk`, or `plan` the subagent runs in its own
  `permissionMode` if set (except `bypassPermissions`, v2.1.267+); unset means inherit
  (https://code.claude.com/docs/en/sub-agents#permission-modes). "Permissions defined in settings.json
  apply to subagents the same way they apply to the main conversation." Not smoke-tested.
- Environment: `CLAUDE_PROJECT_DIR` "the project root where the session started"; it stays put when
  Claude enters a worktree mid-session, while stdin `cwd` follows
  (https://code.claude.com/docs/en/hooks#reference-scripts-by-path). `CLAUDE_EFFORT`,
  `CLAUDE_CODE_REMOTE`, `CLAUDE_CODE_BRIDGE_SESSION_ID`
  (https://code.claude.com/docs/en/hooks#hook-handler-fields); `CLAUDE_ENV_FILE` only on
  SessionStart, Setup, CwdChanged, FileChanged
  (https://code.claude.com/docs/en/hooks#persist-environment-variables). No `CLAUDE_MODEL`. Since
  Appendix B launches from inside the worktree, `CLAUDE_PROJECT_DIR` equals the worktree root for
  the whole session, so `${CLAUDE_PROJECT_DIR}/.claude/hooks/...` in `worker-settings.json` only
  works if the hooks are present in the worktree; use an absolute `$HARNESS/hooks/...` path in the
  generated settings file instead (the harness writes that file per run anyway).

### 5. `permissions.deny` versus the command guard

- Evaluation order: "Rules are evaluated in order: deny, then ask, then allow. The first match in
  that order determines the outcome, and rule specificity doesn't change the order"
  (https://code.claude.com/docs/en/permissions#manage-permissions). Bare `Bash` removes the tool;
  `Bash(rm *)` leaves it and blocks matching calls.
- Bash syntax (https://code.claude.com/docs/en/permissions#wildcard-patterns): `*` matches any text
  at any position; a trailing ` *` also matches the bare command; the space before `*` matters
  (`Bash(ls *)` does not match `lsof`); `:*` is an equivalent trailing form. Compound commands are
  split on `&&`, `||`, `;`, `|`, `|&`, `&`, newlines, and "deny and ask rules apply when any
  subcommand matches them, including a command nested inside a subshell, a command substitution, or
  a control-flow body". Wrappers `timeout`, `nice`, `nohup`, `stdbuf`, `time`, `command`, `builtin`,
  `noglob`, bare `xargs` are stripped. "A deny or ask rule matches past any leading assignment, so
  `Bash(rm *)` in deny still matches `FOO=bar rm -rf tmp/`."
- Limits (https://code.claude.com/docs/en/permissions#bash-rule-limits): "A Bash rule matches the
  command text Claude writes ... It doesn't match the same program invoked in a different form, so
  a deny or ask rule covers the invocation Claude usually produces and isn't a security boundary
  around the program." Table: `Bash(rm *)` misses `/bin/rm -rf build/`, `bash -c 'rm -rf build/'`;
  `Bash(git push *)` misses `git -C . push origin main`, `git -c push.default=current push`,
  `git 'push' origin main`. `find -exec`/`-delete` and exec wrappers (`watch`, `setsid`, `flock`)
  are not covered by prefix rules. Consequence: keep `command_guard.sh` for normalized matching
  (strip a leading path, unwrap `bash -c`, look for `push` anywhere in a git argv, and so on) and
  treat the deny list as a fast, mode-proof first layer. For OS-level enforcement the docs point to
  the sandbox (https://code.claude.com/docs/en/sandboxing).
- File rules (https://code.claude.com/docs/en/permissions#read-and-edit): "Claude Code checks file
  permissions against `Edit(path)` and `Read(path)` rules only. If you write a path rule for
  `Write`, `NotebookEdit`, `Glob`, or the legacy `MultiEdit` tool instead, Claude Code accepts the
  rule but never consults it, and warns at startup." Path forms: `//path` absolute, `~/path` home,
  `/path` relative to the settings source, `path` relative to cwd. So the ticket's `Write(/etc/**)`
  must be `Edit(//etc/**)`. Edit and Read deny rules also cover `cat`, `sed`, and redirection
  targets in Bash, but "don't apply to ... arbitrary subprocesses that read or write files
  indirectly, like a Python or Node script". A `Read` deny also blocks Edit and Write on the path
  (v2.1.228+) but not NotebookEdit.
- Interaction with `dontAsk` (https://code.claude.com/docs/en/permission-modes#allow-only-pre-approved-tools-with-dontask-mode):
  "Claude Code auto-denies every tool call that would otherwise prompt you. Claude still runs actions
  that need no approval ... plus actions matching your permissions.allow rules and calls approved by
  a PreToolUse hook." Deny rules are unaffected by mode; they run first. Hooks and rules
  (https://code.claude.com/docs/en/permissions#extend-permissions-with-hooks): "Hook decisions don't
  bypass permission rules ... a matching deny rule blocks the call" and "A blocking hook also takes
  precedence over allow rules. A hook that exits with code 2 stops the tool call before permission
  rules are evaluated." And (https://code.claude.com/docs/en/hooks-guide#hooks-and-permission-modes):
  "PreToolUse hooks fire before any permission-mode check, in every permission mode, including
  dontAsk. A hook that returns permissionDecision: deny blocks the tool even in bypassPermissions".
  A worker with `--allowedTools` plus deny rules plus exit-2 hooks therefore has three independent
  layers, and nothing the model does in-session can loosen any of them.
- `--permission-prompts none` (v2.1.259+, https://code.claude.com/docs/en/headless) removes
  `AskUserQuestion` and tells the model not to retry denied calls; worth adding to the Appendix B
  launch line so a denied write ends in a clean report rather than a retry loop.

### 6. Guard scripts (validated)

Files: `research-notes/03-hooks/touch_set_guard.sh`, `research-notes/03-hooks/stop_guard.sh`,
`research-notes/03-hooks/worker-settings.example.json`. Both scripts read stdin JSON with `jq`,
resolve paths with `realpath -m` (so `..`, symlinks, and relative spellings cannot escape), fail
closed when `TICKET_TOUCHES` or the path is missing, and accept `notebook_path` as well as
`file_path`. Validation on 2026-09-11 by piping hand-written stdin in the documented shape with
`CLAUDE_PROJECT_DIR` set to a scratch project:

| Case | Env | Exit |
| :-- | :-- | :-- |
| Write inside `experiments/ablation_b/` | `TICKET_TOUCHES=experiments/ablation_b/:results/ablation_b/` | 0 |
| Write to `src/main.py` (outside) | same | 2, stderr names the path and the touch set |
| Edit inside `results/ablation_b/` | same | 0 |
| Edit with `experiments/ablation_b/../../src/main.py` | same | 2 (resolved to `src/main.py`) |
| NotebookEdit `notebook_path` inside | same | 0 |
| NotebookEdit `notebook_path` outside | same | 2 |
| Write to `experiments/ablation_bX/` (prefix-name trick) | same | 2 |
| Write inside, `TICKET_TOUCHES` unset | none | 2, "no writes are allowed" |
| Write to `src/main.py`, absolute entry | `TICKET_TOUCHES=<abs>/src/` | 0 |
| Write with empty `tool_input` | same as row 1 | 2, "no file path" |
| Stop, `stop_hook_active: true`, acceptance file missing | `TICKET_ACCEPTANCE_FILE=<missing>` | 0, no output (allows stop, avoids the loop) |
| Stop, `stop_hook_active: false`, file missing | same | 0, stdout `{"decision":"block","reason":"The machine acceptance has not been run: ..."}` (valid JSON per `jq`) |
| Stop, file present | `TICKET_ACCEPTANCE_FILE=<existing>` | 0, no output |
| Stop, no `TICKET_ACCEPTANCE_FILE` | none | 0, no output |

`worker-settings.example.json` registers the three guards with `args: []` (exec form) and a
30 s timeout, and carries a `permissions.deny` first layer using the corrected `Edit(//etc/**)`
form. Replace `${CLAUDE_PROJECT_DIR}` with the absolute harness path when the harness writes the
per-run settings file (see Section 4, last bullet).

### Open items for M0 (not part of this ticket)

- Smoke-test a `--agents` subagent under the same settings to observe `agent_id`/`agent_type` and
  confirm the touch-set guard fires inside it (documented yes, unverified).
- Decide whether the harness exports `TICKET_ACCEPTANCE_FILE` or the stop guard reads the ticket's
  run directory from `cwd`.
- `command_guard.sh` is the next script to write; its normalization list comes from the
  `bash-rule-limits` table cited above.
