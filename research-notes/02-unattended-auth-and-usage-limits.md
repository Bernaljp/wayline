# 02 Unattended auth and usage-limit signals

Resolved 2026-09-11 against Claude Code 2.1.268 (`claude --version`), the official docs at
code.claude.com, the installed binary's string table, and four cheap launches under
`systemd-run --user` (no TTY, no DISPLAY). Raw outputs are at the end; tokens were never printed.

## Answer

1. **Headless subscription auth works from a systemd user unit with no TTY, no DISPLAY, and no
   D-Bus.** Launch 1 (`systemd-run --user --wait --pipe --collect claude -p "say ok" ...`) returned a
   normal `result` with `is_error: false` and `apiKeySource: "none"` (subscription OAuth). Launch 4
   repeated this with `DBUS_SESSION_BUS_ADDRESS` and `SSH_AUTH_SOCK` unset and also succeeded.
   On Linux the credential is the file `~/.claude/.credentials.json` (mode 0600, 508 bytes here,
   one top-level key `claudeAiOauth` holding accessToken, refreshToken, expiresAt,
   refreshTokenExpiresAt, scopes, subscriptionType, rateLimitTier). gnome-keyring is not consulted
   on Linux; the docs name the file as the Linux store and the keychain only on macOS.
   Refresh is automatic and headless (Claude Code "refreshes the profile's login automatically"),
   but the login itself has a finite lifetime: this machine's background session printed
   `Your login expires in 2 days · run /login to renew`, and the file's refresh-token expiry is
   about one day out. When a login expires and cannot be refreshed, `-p` runs fail with
   `Failed to authenticate: OAuth session expired and could not be refreshed`, error code
   `authentication_failed`, and the docs say a background session that outlives the login "stops
   making progress ... until you sign in again". Whether a successful refresh rolls the login
   expiry forward is not documented (unverified).
   `claude setup-token` mints a one-year subscription OAuth token, prints it, saves nothing, and
   is used through `CLAUDE_CODE_OAUTH_TOKEN`. It is inference-only (no Remote Control, no claude.ai
   connectors), draws on the same subscription limits, and ranks above the `/login` credential in
   precedence, so it must be set only in the unit's or cron job's environment, never in the shell
   profile. `--bare` ignores it entirely (API keys only). Recommendation: the conductor runs on the
   stored `/login` credential by default, checks `claude auth status` (exit 0 when logged in) and the
   stored `expiresAt`/`refreshTokenExpiresAt` at every tick, raises a decision ticket when the login is
   within 3 days of expiring, and lets `init` offer a `setup-token` environment file for the tick and
   conductor units as the durable alternative when the user prefers not to re-login.

2. **Usage-limit pacing is available before the limit hits, on two tokenless surfaces.**
   (a) `--output-format stream-json --verbose` emits a `rate_limit_event` message after each API
   response: `rate_limit_info.status` (`allowed` | `allowed_warning` | `rejected`),
   `resetsAt`, `rateLimitType`, `overageStatus`, `isUsingOverage`, and an undocumented
   `unifiedWindows.five_hour|seven_day.{utilization, resetsAt}` with utilization as a 0..1 fraction
   (observed 0.14 and 0.21 in launch 2). The single-object `--output-format json` does not carry it.
   (b) `claude -p "/usage" --output-format json` is a local command: launch 4 returned the plan
   usage text with `num_turns: 0` and `total_cost_usd: 0`, that is, no model call. The text reads
   `Current session: 24% used · resets Sep 11, 10:10pm (Asia/Riyadh)` and
   `Current week (all models): 23% used · resets Sep 16, 5am (...)` plus a per-model weekly line.
   The statusline JSON (`rate_limits.five_hour.used_percentage` and `resets_at`, percent 0..100,
   epoch seconds) is only fed to the statusline script of an interactive session; `-p` runs do not
   render a statusline. The `~/.claude.json` key `cachedUsageUtilization` mirrors the same windows
   but was 5 days stale here, so it is not a pacing source.
   When a limit is hit, the message is `You've hit your session limit · resets 3:45pm` (or
   `weekly limit · resets Mon 12:00am`, or a model-family limit), and "Claude Code blocks further
   requests until the reset time shown in the message". How this surfaces in `-p` was not
   reproducible without exhausting the window (unverified); from the SDK types the expected shape
   is an `assistant` message with `error: "rate_limit"` (documented as "a 429 against your quota"),
   a `rate_limit_event` with `status: "rejected"`, a `result` with `is_error: true` and
   `api_error_status: 429`, and a non-zero exit code. The interactive auto-wait
   (`autoContinueAtUsageLimit`) is explicitly not offered for "background sessions and `-p` runs".
   `CLAUDE_CODE_RETRY_WATCHDOG=1` makes a `-p` run wait out the window inside the process
   ("until the limit resets when the response carries a rate-limit reset time"); the conductor
   should leave it unset so workers fail fast and the conductor's own pause (Brief 9.6) owns the wait.

3. **`--fallback-model` never triggers on usage limits.** The model-config docs state: "Authentication,
   billing, rate-limit, request-size, and transport errors ... never trigger a switch"; fallback
   fires only when the primary is "overloaded, unavailable, or returns another non-retryable server
   error". Session and weekly limits are shared across all models anyway, so a fallback would not help;
   only the per-family Opus/Sonnet/Fable limits can be dodged by switching family, and that must be
   the conductor's own model choice (`--model`), not a fallback chain.

4. **`--bg` is not a worker runner for the conductor; plain `-p` subprocesses are.** `--bg` cannot be
   combined with `-p` ("Claude Code rejects `--bg`"), so a background session is an interactive TUI
   process under the supervisor: `claude logs <id>` returns raw terminal escape output, not
   structured messages, and follow-up input requires `claude attach` (a TTY). What `--bg` does give:
   sessions survive the launching shell (launch 3 was started from a transient systemd unit that
   exited immediately, and the session ran to `state: "done"`); `claude agents --json --all --cwd
   <dir>` is a clean scripting surface (`id`, `state` in working|blocked|done|failed|stopped, `status`,
   `pid`, `sessionId`, `name`); `claude rm <id>` cleans up. The supervisor is started on demand
   ("origin: transient"), idle-exits when no workers or agent views remain, stops an unattached idle
   session after about an hour, and keeps its sockets under `/tmp/cc-daemon-<uid>`. Lingering is
   enabled for this user (`loginctl ... Linger=yes`), so both the supervisor and any systemd user
   timer survive logout. Verdict: workers are `claude -p ... --output-format stream-json --verbose`
   subprocesses (structured result, `rate_limit_event`, exit code, SIGTERM exits 143 and the turn
   resumes on `--resume`); `--bg` stays a human-facing convenience, at most for `claude agents` as a
   read-only view of what the conductor is running (interactive sessions are listed there too).

## Details and sources

### Q1 authentication

- Linux credential store: "On Linux, credentials are stored in `~/.claude/.credentials.json` with
  file mode `0600`." macOS uses the Keychain and falls back to the same file when the Keychain
  rejects the write. Source: https://code.claude.com/docs/en/authentication#credential-management
- Local file: `stat` shows 508 bytes, mode 600, mtime 2026-09-11 19:46. `jq keys` shows one top-level
  key `claudeAiOauth`; its keys are accessToken, expiresAt, rateLimitTier, refreshToken,
  refreshTokenExpiresAt, scopes, subscriptionType. Relative expiry computed with jq at 20:15 local:
  access token about 454 min out, refresh token about 1 day out; subscriptionType `max`,
  rateLimitTier `default_claude_max_5x`, scopes `user:file_upload,user:inference,user:mcp_servers,
  user:profile,user:sessions:claude_code`.
- `claude auth status` (JSON, exit 0): `loggedIn: true`, `authMethod: "claude.ai"`,
  `apiProvider: "firstParty"`, `subscriptionType: "max"`. Docs: "Exits with code 0 if logged in, 1
  if not." Source: https://code.claude.com/docs/en/cli-reference
- Precedence (docs, same page as credential management): 1 cloud provider vars, 2
  `ANTHROPIC_AUTH_TOKEN`, 3 `ANTHROPIC_API_KEY` ("In non-interactive mode (`-p`), the key is always
  used when present"), 4 `apiKeyHelper`, 5 `CLAUDE_CODE_OAUTH_TOKEN`, 6 Anthropic profiles, 7
  subscription OAuth from `/login`.
- Keyring: `--bare` help text lists "keychain reads" among what it skips and says "OAuth and keychain
  are never read"; the docs' Linux entry names only the file. Launch 4 ran with
  `DBUS_SESSION_BUS_ADDRESS` unset and succeeded. The `systemctl --user show-environment` of the user
  manager has no DISPLAY or WAYLAND_DISPLAY, so launches 1 to 4 all ran without a display.
- Refresh and expiry: "Claude Code refreshes the profile's login automatically, and when refresh
  fails, requests fail with Anthropic profile login expired"; "When the login you created with
  `/login` is within three days of expiring, Claude Code shows a warning at startup: `Your login
  expires in 3 days · run /login to renew`"; "Once the stored login expires and can't be refreshed,
  each model request fails with `Login expired · Please run /login`"; "Renewing early matters most
  for sessions that run unattended. A background session in agent view or a Remote Control session
  that outlives the login stops making progress once the credential expires and can't recover until
  you sign in again." Source: https://code.claude.com/docs/en/authentication#renew-an-expiring-login
  Observed: launch 3's `claude logs` shows `Your login expires in 2 days · run /login to renew`.
- `-p` wording on expiry: "In non-interactive mode (`-p`) and the Agent SDK, the message reads as
  follows, and the structured error code is `authentication_failed`: `Failed to authenticate: OAuth
  session expired and could not be refreshed`". Source: https://code.claude.com/docs/en/errors#login-expired
- `claude setup-token --help` prints only "Set up a long-lived authentication token (requires Claude
  subscription)". Docs: "generate a one-year OAuth token with `claude setup-token` ... It does not save
  the token anywhere; copy it and set it as the `CLAUDE_CODE_OAUTH_TOKEN` environment variable ...
  This token authenticates with your Claude subscription and requires a Pro, Max, Team, or Enterprise
  plan. It can only make model requests, so it can't establish Remote Control sessions or fetch
  claude.ai connectors. MCP servers you configure locally still work. Bare mode does not read
  `CLAUDE_CODE_OAUTH_TOKEN`." Source: https://code.claude.com/docs/en/authentication#generate-a-long-lived-token
  Env-var entry: "Takes precedence over keychain-stored credentials ... To replace an expired token,
  generate a new one and restart." Source: https://code.claude.com/docs/en/env-vars
  Binary strings confirm `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` exists (undocumented; unverified
  semantics) and the warning "OAuth 401: keeping the user-supplied CLAUDE_CODE_OAUTH_TOKEN instead of
  adopting the stored credential."
- Headless run semantics: "Claude Code exits with code 0 on success and a non-zero code when the run
  fails ... When a failure happens inside the run, such as missing authentication, Claude Code prints
  the failure as the result on stdout." SIGTERM exits 143 and the unfinished turn resumes on
  `--resume`. Source: https://code.claude.com/docs/en/headless

### Q2 usage-limit signals

- Statusline JSON: `rate_limits.five_hour.used_percentage`, `rate_limits.seven_day.used_percentage`
  (0 to 100), `rate_limits.*.resets_at` (epoch seconds); "appears only for Claude.ai Pro and Max
  subscribers ... and only after the first API response in the session. Each window ... may be
  independently absent, and Claude Code drops a window once its `resets_at` time passes."
  Source: https://code.claude.com/docs/en/statusline#rate-limit-usage. The local
  `~/.claude/statusline-command.sh` reads exactly these four fields.
- `rate_limit_event` in stream-json (launch 2, verbatim minus uuids):
  `{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1789153800,
  "rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"org_level_disabled",
  "isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.14,"resetsAt":1789153800},
  "seven_day":{"utilization":0.21,"resetsAt":1789524000}}}}`. The `resetsAt` matched the `/usage`
  text (10:10pm local) and the statusline (17% / "in 1h57m") within the same minute.
  SDK type: `status: "allowed" | "allowed_warning" | "rejected"; resetsAt?; utilization?;
  errorCode?: "credits_required"`. `unifiedWindows` is not in the documented type (observed only).
  Source: https://code.claude.com/docs/en/agent-sdk/typescript#sdkratelimitevent
- `claude -p "/usage"`: docs list `/usage` as a local command ("Output from a local command such as
  `/voice` or `/usage`", `SDKLocalCommandOutputMessage`), and the headless page says slash commands
  expand in `-p`. Launch 4 confirmed: `assistant` text message plus `result` with `num_turns: 0`,
  `total_cost_usd: 0`, subtype `success`. The percentages are integers in prose; parse with a regex
  on `Current session: (\d+)% used · resets (.+?) \(` and `Current week \(all models\): ...`.
  The reset times are local-time prose, so prefer `rate_limit_event.resetsAt` (epoch) when a worker
  stream is available and use `/usage` for the tick's between-worker check. Note the docs warn the
  usage endpoint itself can be rate limited ("most often because the usage endpoint is rate
  limited"), so poll it at tick cadence, not per second. Source:
  https://code.claude.com/docs/en/costs#when-the-usage-request-fails
- Limit message and behavior: "`You've hit your session limit · resets 3:45pm` ... Claude Code blocks
  further requests until the reset time shown in the message. The session and weekly limits are
  shared across all models ... Usage counts against the session and weekly allowances at the same
  time. A single burst of heavy activity, such as a large workflow fanout, can exhaust the weekly
  allowance before the session window resets." Source:
  https://code.claude.com/docs/en/errors#youve-hit-your-session-limit
- Result shape on errors (SDK): success arm has `is_error`, `api_error_status` ("the HTTP status code
  of the API error that terminated the conversation"), `result`; error arm subtypes are
  `error_max_turns`, `error_during_execution`, `error_max_budget_usd`,
  `error_max_structured_output_retries` with `errors: string[]`. `SDKAssistantMessageError` includes
  `'rate_limit'` ("a 429 against your quota") versus `'overloaded'` (529). Source:
  https://code.claude.com/docs/en/agent-sdk/typescript#sdkresultmessage. Exact `-p` output at a hit
  limit: unverified (not reproduced).
- `api_retry` system events carry `error: "rate_limit"` while retrying; default retry budget is 10
  (`CLAUDE_CODE_MAX_RETRIES`, capped at 15). `CLAUDE_CODE_RETRY_WATCHDOG=1` "Retries 429 and 529
  capacity errors indefinitely ... backs off up to 5 minutes between attempts, or until the limit
  resets when the response carries a rate-limit reset time, so a session that hits a usage limit
  waits out the remaining window." Source: https://code.claude.com/docs/en/env-vars
- Auto-continue is interactive only: "Claude Code doesn't offer the wait at all in these cases:
  Background sessions and `-p` runs: the menu row isn't available." Source:
  https://code.claude.com/docs/en/interactive-mode#wait-for-a-usage-limit-to-reset
- Temporary throttles are distinct: `API Error: Server is temporarily limiting requests (not your
  usage limit)` is retried automatically. Source: https://code.claude.com/docs/en/errors

### Q3 fallback model

- `claude --help`: "--fallback-model <model> Enable automatic fallback to specified model(s) when the
  default model is overloaded or not available. ... Re-tries the primary at the start of each user
  turn."
- Docs: "When the primary model is overloaded, unavailable, or returns another non-retryable server
  error, Claude Code can switch to a fallback model instead of failing the request. Authentication,
  billing, rate-limit, request-size, and transport errors, and a denial by your organization's policy
  check, never trigger a switch." Chains cap at three models; the chain also applies to subagents.
  Source: https://code.claude.com/docs/en/model-config#fallback-model-chains

### Q4 background sessions

- `claude --help`: `--bg` "Start the session in the background and return immediately. Prints the id
  that `claude attach`, `logs`, `stop` and `rm` take; `claude agents` lists them. With --resume
  <session-id>, continues that session in the background under the same ID". Headless docs: "Claude
  Code rejects `--bg` ... with an error naming the conflict" when combined with `-p`.
- Supervisor: "Background sessions don't need any terminal open to keep running. A separate
  supervisor process runs them, so you can close agent view, close your shell, or start a new
  interactive session and your dispatched work keeps going." Idle policy: "Finished or waiting for
  your next message, and unattached for about an hour: the supervisor stops the process to free
  resources. The conversation stays on disk." State under `~/.claude/jobs/<id>/state.json` and
  `~/.claude/daemon/roster.json`; `claude daemon status` for diagnostics. Source:
  https://code.claude.com/docs/en/agent-view
- `claude agents --json` fields: `cwd`, `kind`, `startedAt` always; `id`, `state`
  (working|blocked|done|failed|stopped) for background sessions; `pid`, `status` (busy|waiting|idle)
  while alive; `waitingFor`; `sessionId`, `name`. `--all` adds completed sessions, `--cwd` filters.
  Launch 3 output matched this exactly and `claude rm` returned `removed 06f22b3f`.
- `claude daemon status` here: `origin: transient - started on-demand by claude agents`, socket dir
  `/tmp/cc-daemon-176816/...`, "to let it idle-exit: wait for (or cancel) bg workers and close any
  `claude agents`". `loginctl show-user bernaljp -p Linger` = `Linger=yes`.
- `claude logs <id>` output is the raw TUI frame (ANSI escapes, statusline rows), not messages.

## Raw command outputs (tokens redacted)

Temporary files: /home/bernaljp/.claude/jobs/5a78b0a6/tmp/02/ (help texts, doc markdown, launch
outputs, binary string table).

### claude --version
```
2.1.268 (Claude Code)
```

### claude setup-token --help
```
Usage: claude setup-token [options]

Set up a long-lived authentication token (requires Claude subscription)

Options:
  -h, --help  Display help for command
```

### claude auth status (orgId redacted)
```
{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty","analyticsDisabled":false,
 "projectsDirectory":"/home/bernaljp/.claude/projects","configDirectory":"/home/bernaljp/.claude",
 "email":"jpbernal888@gmail.com","orgId":"<redacted>","orgName":"jpbernal888@gmail.com's Organization",
 "subscriptionType":"max"}
exit=0
```

### Credentials file (structure only)
```
508 bytes mode 600 /home/bernaljp/.claude/.credentials.json
top-level keys: claudeAiOauth
claudeAiOauth: accessToken,expiresAt,rateLimitTier,refreshToken,refreshTokenExpiresAt,scopes,subscriptionType
```

### systemctl --user show-environment (relevant keys)
```
HOME=/home/bernaljp
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin
XDG_RUNTIME_DIR=/run/user/176816
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/176816/bus
SSH_AUTH_SOCK=/run/user/176816/gnupg/S.gpg-agent.ssh
(no DISPLAY, no WAYLAND_DISPLAY)
```

### Launch 1: json under systemd-run (exit 0)
```
systemd-run --user --wait --pipe --collect --quiet -p WorkingDirectory=<tmp> \
  /home/bernaljp/.local/bin/claude -p "say ok" --model sonnet --effort low \
  --output-format json --no-session-persistence
{"duration_api_ms":1541,"stop_reason":"end_turn","session_id":"33fcbf57-...","total_cost_usd":0.0708982,
 "usage":{"input_tokens":2,"cache_creation_input_tokens":16782,"cache_read_input_tokens":18531,"output_tokens":6,...},
 "modelUsage":{"claude-sonnet-5":{...,"provider":"firstParty","costBasis":"list"}},
 "permission_denials":[],"terminal_reason":"completed","is_error":false,"num_turns":1,"subtype":"success",
 "api_error_status":null,"result":"Ok.","type":"result",...}
```
No `rate_limit` field of any kind in the single json object.

### Launch 2: stream-json --verbose under systemd-run (exit 0)
```
message types: system/init, assistant, rate_limit_event, result/success
system/init extract: {"model":"claude-sonnet-5","apiKeySource":"none","permissionMode":"auto",
  "capabilities":["interrupt_receipt_v1","interrupt_cancel_queued_v1","msg_lifecycle_v1"],"claude_code_version":"2.1.268"}
rate_limit_event: {"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1789153800,
  "rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"org_level_disabled",
  "isUsingOverage":false,"unifiedWindows":{"five_hour":{"utilization":0.14,"resetsAt":1789153800},
  "seven_day":{"utilization":0.21,"resetsAt":1789524000}}},"uuid":"...","session_id":"b0003d75-..."}
result extract: {"is_error":false,"subtype":"success","api_error_status":null,"terminal_reason":"completed",
  "stop_reason":"end_turn","result":"ok","num_turns":1}
```

### Launch 3: --bg under systemd-run, then claude agents --json, logs, rm
```
stdout:
backgrounded · 06f22b3f · specdriven-bgtest
  claude agents             list sessions
  claude attach 06f22b3f    open in this terminal
  claude logs 06f22b3f      show recent output
  claude stop 06f22b3f      stop this session
exit=0 (the unit exited immediately; the session kept running under the supervisor)

claude agents --json --all --cwd <tmp>/bgtest  (after ~4 s):
[{"pid":1968939,"id":"06f22b3f","cwd":".../bgtest","kind":"background","startedAt":1789146777326,
  "sessionId":"06f22b3f-c95d-4c05-ba2f-9866ccb8a46a","name":"specdriven-bgtest","status":"idle","state":"done"}]

claude logs 06f22b3f: raw ANSI TUI frame; readable fragments include
  "Sonnet 5 with low effort · Claude Max", "Your login expires in 2 days · run /login to renew",
  "❯ say ok and stop", "● ok", "5h usage 17% in 1h57m  7d usage 21% in 4d8h", "Crunched for 3s · done 8:13 PM"

claude rm 06f22b3f -> "removed 06f22b3f" (exit 0); claude agents --json --all --cwd ... -> []
```

### Launch 4: claude -p "/usage" with D-Bus and SSH agent unset (exit 0)
```
systemd-run --user --wait --pipe --collect --quiet -p WorkingDirectory=<tmp> \
  /usr/bin/env -u DBUS_SESSION_BUS_ADDRESS -u SSH_AUTH_SOCK /home/bernaljp/.local/bin/claude \
  -p "/usage" --model sonnet --effort low --output-format stream-json --verbose --no-session-persistence
message types: system/init, assistant, result/success   (no rate_limit_event: no API call was made)
result extract: {"is_error":false,"subtype":"success","num_turns":0,"total_cost_usd":0}
result text:
You are currently using your subscription to power your Claude Code usage

Current session: 24% used · resets Sep 11, 10:10pm (Asia/Riyadh)
Current week (all models): 23% used · resets Sep 16, 5am (Asia/Riyadh)
Current week (Fable): 43% used · resets Sep 16, 5am (Asia/Riyadh)

What's contributing to your limits usage?
Approximate, based on local sessions on this machine ...
Last 24h · 260 requests · 29 sessions
  53% of your usage came from subagent-heavy sessions
  38% of your usage was at >150k context
  32% of your usage was while 4+ sessions ran in parallel
  ...
```

### claude daemon status
```
pid: 1228551  version: 2.1.268  uptime: 30003s
origin: transient - started on-demand by `claude agents` (pid 1225637) in /home/bernaljp/Documents/agents4research
bg sessions: sock dir /tmp/cc-daemon-176816/612eacfa, control.sock reachable, 1 running
to let it idle-exit: wait for (or cancel) bg workers and close any `claude agents`
```

### Installed binary string table (selected, /home/bernaljp/.local/share/claude/versions/2.1.268)
```
error_during_execution / error_max_budget_usd / error_max_turns / rate_limit_event
"Usage limit reached · continuing automatically at ... · esc to cancel"
"Continuing automatically when your limit resets"
"this session moved to the background, so the task will not resume on its own when the usage limit resets"
"Claude Code exited during the wait, so the task will not resume on its own when the usage limit resets"
CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR, CLAUDE_CODE_RETRY_WATCHDOG, CLAUDE_CODE_MAX_RETRIES
"Use this token by setting: export CLAUDE_CODE_OAUTH_TOKEN=<token>"
"Remote Control requires a full-scope login token. Long-lived tokens (from `claude setup-token` or CLAUDE_CODE_OAUTH_TOKEN) are limited to inference-only"
```
