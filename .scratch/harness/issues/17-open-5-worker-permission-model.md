# 17 — OPEN-5 Worker permission model

Type: grilling
Status: resolved
Blocked by: 03 (Hook shape for the worker guards), 16 (Prototype: the M0 worker launch)
Brief: OPEN-5, C7

## Question

`dontAsk` plus an explicit allowlist plus hooks (default), or `bypassPermissions` inside a container?

Default: `dontAsk` with `--permission-prompts none`, an allowlist per role, `permissions.deny` for the static part of the irreversible list, and hooks for the dynamic part (touch set, stop guard). Containers are deferred and considered only for experiment jobs if isolation is ever needed.

Confirm against what the prototype showed: did any needed action get denied silently, and did the guards fire?

## Answer

Resolved 2026-09-11 by the owner: default confirmed on research evidence, without the prototype; the tracer bullet named below re-verifies it as its first acceptance criterion.

`dontAsk` with `--permission-prompts none`; per-role tool restriction through `--disallowedTools` or `--tools` (never an agent `tools` allowlist, which removes StructuredOutput); `permissions.deny` for the static part of the irreversible list; hooks for the dynamic part (touch-set guard on Write and Edit, stop guard). Containers deferred. Confirmed on research evidence; M0's first acceptance criterion re-verifies it live, including hooks inside `--agents` subagents.
