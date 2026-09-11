# 02 — Unattended auth and usage-limit signals

Type: research
Status: resolved
Blocked by: None
Brief: Sections 3.1, 9.6; OPEN-8; fog: the tick

## Question

1. Does `claude -p` authenticate with the subscription when launched from a systemd user unit or cron (no TTY, no DISPLAY, no interactive keyring)? Where the OAuth credentials live on Linux (`~/.claude/.credentials.json` exists here, 508 bytes, mode 600), whether token refresh works headless, whether gnome-keyring is consulted, and what `claude setup-token` provides and whether a cron-launched conductor should use it.
2. How a five-hour or weekly usage limit surfaces in `-p` output: the error text, `is_error`, the exit code, and whether the reset time is stated. Whether `--output-format stream-json` `system`/`result` messages, or any other CLI surface, expose `rate_limits.five_hour.used_percentage` and `resets_at` the way the statusline input JSON does (see `~/.claude/statusline-command.sh`, which reads `rate_limits.five_hour` and `rate_limits.seven_day`). The conductor wants to pace before hitting the limit, not only react to it.
3. Whether `--fallback-model` triggers on usage limits or only on overload and unavailability.
4. Whether `claude --bg` plus `claude agents`, `logs`, `stop`, `rm` is a usable worker runner for the conductor compared with plain subprocesses, and whether `--bg` sessions survive the launching shell's exit.

Deliverable: `research-notes/02-unattended-auth-and-usage-limits.md` with sources for every claim; run the cheapest possible check where docs are silent (for example, `claude -p` under `systemd-run --user --wait --pipe` with `--model sonnet --effort low`).

## Answer

1. Subscription auth works headless: `claude -p` under `systemd-run --user` with no TTY, no DISPLAY, and D-Bus unset ran on the stored `/login` credential (`apiKeySource: "none"`). Linux stores it in `~/.claude/.credentials.json` (0600, key `claudeAiOauth`); gnome-keyring is not used. Refresh is automatic, but the login has a finite lifetime (this box shows "expires in 2 days"); when it lapses, `-p` fails with `authentication_failed`. `claude setup-token` mints a one-year inference-only subscription token for `CLAUDE_CODE_OAUTH_TOKEN`; it outranks `/login`, so set it only in the unit's environment. Default to the stored login, check `claude auth status` and the expiry at every tick, and offer setup-token as the durable path.
2. Pace before the limit with two tokenless surfaces: `--output-format stream-json --verbose` emits a `rate_limit_event` per API response (`status` allowed|allowed_warning|rejected, `resetsAt` epoch, `unifiedWindows.five_hour|seven_day.utilization` 0..1, undocumented), and `claude -p "/usage"` returns the plan usage text with `num_turns: 0`, `total_cost_usd: 0`. The statusline `rate_limits` JSON only reaches interactive statusline scripts. At a hit limit the text is `You've hit your session limit · resets 3:45pm`; the exact `-p` result shape is unverified (expected `is_error: true`, `api_error_status: 429`, non-zero exit). Auto-continue is not offered to `-p` runs; leave `CLAUDE_CODE_RETRY_WATCHDOG` unset so workers fail fast and the conductor owns the wait.
3. `--fallback-model` never fires on rate or usage limits, only on overloaded/unavailable/server errors (docs quote in notes). Session and weekly limits are shared across models anyway.
4. `--bg` is not a worker runner: it rejects `-p`, `claude logs` is a raw TUI frame, and follow-up needs `claude attach`. It does survive the launching shell (supervisor, Linger=yes here) and `claude agents --json --all --cwd` is a clean state feed, so keep it as a human view at most. Workers are plain `claude -p ... stream-json` subprocesses.

Notes with sources and raw outputs: research-notes/02-unattended-auth-and-usage-limits.md
