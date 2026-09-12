# Roles

One directory per role of Implementation Decisions 1, holding the two files the conductor reads
to launch it:

- `agent.md`: Claude Code subagent markdown. The frontmatter carries `name` and `description`;
  the body is the role's system prompt, which becomes `prompt` in the `--agents` object. It never
  carries a `tools` field: an agent tool allowlist removes the StructuredOutput tool, so tool
  restriction lives in `wayline.json` instead.
- `wayline.json`: `role`, `summary`, `kinds`, `may_judge`, `output_schema`, `allowed_tools`
  (passed as `--allowedTools`, auto-allowed under `dontAsk`), and `disallowed_tools` (passed as
  `--disallowedTools`, removal). A project overrides a role in its own `.claude/agents/<role>.md`.

The conductor composes `agent.json` from the two: `description` and `prompt` from `agent.md`,
`model` and `effort` from the ticket's difficulty tier, `maxTurns` from its budget, and
`permissionMode: dontAsk`. The per-launch protocol the role follows is separate, in
`prompts/roles/<role>.md`, because it is part of the prompt and changes with the phase.

## Why `disallowed_tools` names tools the harness never asked for

`--settings` adds to the owner's user configuration rather than replacing it, so a worker starts
with the owner's MCP servers and plugin skills in its tool list. `docs/verification/m0.md`
records exactly that from the ticket 03 smoke launch. Every role therefore names `mcp__*`,
`Workflow`, `Skill`, and the scheduling tools in `disallowed_tools`, whether or not the role
would otherwise have them.

Two things about that list are checked by the live run of ticket 06, not by the suite: whether a
glob (`mcp__*`) is accepted where a tool name is expected, and whether disallowing the `Skill`
tool also stops the `/wayline-<skill>` lines at the top of the prompt from expanding. The
assumption is that it does not, because those lines are expanded into the prompt by the CLI
before the session starts. If the live run shows otherwise, `Skill` comes off this list and the
skills' bodies are inlined instead.
