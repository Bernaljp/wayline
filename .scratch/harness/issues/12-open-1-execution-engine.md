# 12 — OPEN-1 Execution engine

Type: grilling
Status: resolved
Blocked by: 01 (Headless worker launch facts), 04 (Workflow scripts from headless sessions)
Brief: OPEN-1, Sections 5.1, 9.1

## Question

Which process is the outer loop: an external conductor over `claude -p` (default), or a Workflow script?

Default: the external conductor. It survives session death, is cron-able, sets model and effort per ticket, paces on usage windows, owns real worktrees, and waits on hardware jobs. Workflow scripts run only inside phases (absorb, panel, verify).

Sub-questions to settle in the same conversation:
- Does the conductor spawn workers as plain subprocesses it owns, or through `claude --bg` and `claude agents`? (Default: plain subprocesses, because the conductor already tracks pids and results; see Headless worker launch facts and Unattended auth and usage-limit signals.)
- If Workflow scripts from headless sessions turned out unusable, which fallback for absorb: Agent-tool fan-out inside one session, or N headless readers launched by the conductor? (Default: conductor-level fan-out, because it keeps control flow in code.)

What would overturn the default: nothing found so far. Resolve after reading the two research notes.

## Answer

Resolved 2026-09-11 by the owner in a grilling round.

The outer loop is an external conductor process over `claude -p` workers; Workflow scripts run only inside phases. (a) Workers are plain subprocesses the conductor owns and polls; `claude --bg` is at most a human view. (b) Absorb-phase fan-out runs as a Workflow script inside one `-p` session (launched with `--allowedTools Workflow Skill`), with conductor-level `claude -p` fan-out as the fallback when per-chunk isolation or crash survival matters; the script is deterministic code, so C2 holds. (c) Workers run with `--output-format stream-json --verbose`; the conductor parses the final `result` message for `structured_output` and reads `rate_limit_event` messages for pacing.
