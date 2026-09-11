# 06 - M0 live: one trivial ticket end to end (verbatim prototype 16)

**What to build:** The M0 demo, live and unattended in one command: `init` lays out a project; the conductor runs one trivial ticket through a real `claude -p` in a worktree with `dontAsk`, validates the structured result, runs a machine check, fast-forwards main, closes the ticket, journals it. The first criterion is the closed prototype ticket's Question, carried verbatim; the real `wayline init` plus `wayline run` stands in for the throwaway script, and every record the Question asks for goes to `docs/verification/m0.md`.

**Blocked by:** 05 (The conductor's M0 path with the fake worker)

**Status:** ready-for-agent

**Milestone:** M0 Skeleton. **Spec:** milestone M0 criteria 1, 7, 8, 10; Implementation Decisions 3, 4.

- [ ] Carried verbatim from the closed prototype ticket 16 (Prototype: the M0 worker launch):

  > What is the exact launch that works end to end? Build a throwaway script that:
  >
  > 1. Creates a scratch git repo with one file and a `.claude/skills/<test-skill>/SKILL.md`, adds a worktree on a `ticket/1` branch.
  > 2. Launches `claude -p` from the worktree with `--agents` (role prompt, `model: sonnet`, a tool allowlist, `maxTurns`, `skills: [<test-skill>]`), `--agent worker`, `--effort low`, `--permission-mode dontAsk`, `--settings <file>` carrying a `PreToolUse` touch-set guard and a `Stop` guard, `--output-format stream-json --verbose --json-schema <result schema>` (per OPEN-1: parse the final `result` message for `structured_output` and record any `rate_limit_event`), `--fallback-model sonnet`, and `< /dev/null`. Restrict tools with `--disallowedTools` or `--tools`, never an agent `tools` allowlist, which removes the StructuredOutput tool (Headless worker launch facts).
  > 3. Asks the worker to write one file inside the touch set and attempt one write outside it (the guard must block the second), run a machine check, and commit.
  > 4. Validates the envelope, runs the machine check on the branch, fast-forwards main, removes the worktree.
  >
  > Record the exact command, the raw envelope, the hook stdin as seen, turns, duration, and every flag that behaved differently from the notes. The answer is the launch shape M0 implements. Keep the script under `.scratch/proto/worker-launch/` and mark it throwaway.

  The real `wayline init` and `wayline run` stand in for the throwaway script; the records go to `docs/verification/m0.md`.
- [ ] The live run re-verifies OPEN-5 as decided: `dontAsk` with `--permission-prompts none`, the role's `--allowedTools` and `--disallowedTools`, the `permissions.deny` first layer, and the hooks, including inside a `--agents` subagent (the trivial ticket asks the worker to delegate one read to an Agent-tool subagent; the hook stdin's `agent_id` and `agent_type` are recorded).
- [ ] The prompt carries two `/wayline-<skill>` lines (a second test skill is added for this); the record says whether both expanded; if only the first did, the conductor inlines the remaining skills' bodies under a heading and the record says that path is in use.
- [ ] The launcher's portability seam is confirmed by inspection: one `launch`, one `resume`, one backend named `claude_cli`, and no other place that starts `claude`.
- [ ] `wayline status` after the run shows the closed ticket and the last events; the repository is tagged `v0.1.0` with a changelog entry.
