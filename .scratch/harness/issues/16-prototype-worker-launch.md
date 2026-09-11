# 16 — Prototype: the M0 worker launch

Type: prototype
Status: resolved
Blocked by: 01 (Headless worker launch facts), 03 (Hook shape for the worker guards), 12 (OPEN-1 Execution engine), 15 (OPEN-4 Language)
Blocks: 17 (OPEN-5 Worker permission model)
Brief: Appendix B, M0; fog: the exact claude -p launch with --agents and skills

## Question

What is the exact launch that works end to end? Build a throwaway script that:

1. Creates a scratch git repo with one file and a `.claude/skills/<test-skill>/SKILL.md`, adds a worktree on a `ticket/1` branch.
2. Launches `claude -p` from the worktree with `--agents` (role prompt, `model: sonnet`, a tool allowlist, `maxTurns`, `skills: [<test-skill>]`), `--agent worker`, `--effort low`, `--permission-mode dontAsk`, `--settings <file>` carrying a `PreToolUse` touch-set guard and a `Stop` guard, `--output-format stream-json --verbose --json-schema <result schema>` (per OPEN-1: parse the final `result` message for `structured_output` and record any `rate_limit_event`), `--fallback-model sonnet`, and `< /dev/null`. Restrict tools with `--disallowedTools` or `--tools`, never an agent `tools` allowlist, which removes the StructuredOutput tool (Headless worker launch facts).
3. Asks the worker to write one file inside the touch set and attempt one write outside it (the guard must block the second), run a machine check, and commit.
4. Validates the envelope, runs the machine check on the branch, fast-forwards main, removes the worktree.

Record the exact command, the raw envelope, the hook stdin as seen, turns, duration, and every flag that behaved differently from the notes. The answer is the launch shape M0 implements. Keep the script under `.scratch/proto/worker-launch/` and mark it throwaway.

## Answer

Closed 2026-09-11 by the owner's scoping decision: not built as a throwaway. Its Question becomes the first acceptance criterion of tracer bullet M0 Skeleton (BRIEF.md Section 16), which builds the real version; to-tickets must carry it there verbatim.
