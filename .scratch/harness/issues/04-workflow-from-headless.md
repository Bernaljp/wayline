# 04 — Workflow scripts from headless sessions

Type: research
Status: resolved
Blocked by: None
Brief: Sections 3.1, 5.4 (absorb.js, panel.js, verify.js); M3

## Question

1. Can a `claude -p` session run the Workflow tool (a saved `.claude/workflows/<name>.js`, invoked by name) without an interactive permission dialog? What opt-in is required: the keyword in the prompt, a settings flag, `--allowedTools Workflow`, or nothing?
2. The concurrency cap on this machine (the reference says min(16, CPUs - 2); this workstation has 128 cores) and whether workflow agents count as subagents for `SubagentStop` hooks and for the session's tool allowlist.
3. Whether `agent()` inside a workflow can use an `--agents`-defined agent type through `agentType`, and whether those agents get project-local skills.
4. What the run's on-disk files look like (transcript directory, `journal.jsonl`, `agent-<id>.jsonl`) so code could read a workflow's results after the session exits, and how resume by `runId` behaves across sessions.
5. If Workflow is not usable headless: document the fallback for the absorb phase, either the Agent tool fan-out inside one `-p` session or conductor-level fan-out with N `claude -p` readers each given one chunk, with the cost and isolation trade-offs.

Sources: the workflow-authoring reference (load it with the Skill tool), the official docs, `claude --help`, and a smoke test with a two-agent workflow at `--model sonnet --effort low` from a scratch directory.

Deliverable: `research-notes/04-workflow-from-headless.md`.

## Answer

Yes: `claude -p` runs a saved `.claude/workflows/<name>.js` with no dialog (verified on 2.1.268, three launches).
Opt-in is a permission allow rule, not a keyword or settings flag: under `dontAsk` the call is denied until
`--allowedTools Workflow` (or `Workflow(<name>)`) is passed, and in practice `Skill` too, because a saved workflow
surfaces as `/<name>` and the model reaches it through `Skill(<name>)` first (run 2 stalled on that denial).
`--permission-mode auto`, `bypassPermissions`, or a `PreToolUse` allow hook also work (docs). `ultracode` is ignored in `-p`.
Concurrency cap is `min(16, max(2, availableParallelism() - 2))` = 16 on this 128-core box; 1000 agents per run.
Workflow agents run as `agentType: workflow-subagent` through the normal subagent loop, so SubagentStop and the
session's permission rules apply (hook firing inferred from the binary, not exercised); they are absent from the
`-p` result's `subagent_stats`. `agentType` resolves from the same registry as the Agent tool (so `--agents` works)
and the default agent gets the project's skill listing. On disk: `<session>/workflows/wf_<runId>.json` (full result,
logs, per-agent tokens), `workflows/scripts/<name>-wf_<runId>.js`, `subagents/workflows/wf_<runId>/{journal.jsonl,
agent-<id>.jsonl, agent-<id>.meta.json}`. Resume by runId is same-session only (`--resume <session>` can replay).
Absorb phase: use Workflow inside one `-p` session as primary and read `wf_*.json` after exit; conductor-level
`claude -p` fan-out is the fallback when per-chunk isolation or crash survival matters more than cost.
Details: `research-notes/04-workflow-from-headless.md`.
