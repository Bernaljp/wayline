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

## The verifier is launched by a gate, not assigned to a ticket

Every other role here is assigned to a ticket by the librarian and launched by the conductor.
`verifier` is not: `wayline.gates.verdict` launches it and its `kinds` is empty. Its prompt is assembled by the gate too, from the one question, the scope
limit, and the paths, because a verdict has no touch set, no acceptance to run, and nothing to
commit. `docs/verification/m4.md` records what its session can actually do: the `Bash(...)` rules
below are the harness saying what it means to permit, and what makes the role read-only is the
absent write tools and the permission system's own reading of a command.

## The integrator is launched by the conductor, not assigned to a ticket

`integrator` is the other role outside the librarian's reach (`kinds` empty). The conductor
launches it once when rebasing a ticket branch onto `main` conflicts, in that ticket's worktree,
with every path both the branch and `main` changed as `TICKET_TOUCHES` and the conflict markers as
the prompt's context (`wayline.worker.integrator_prompt`). It finishes the rebase itself, since a
resolution committed on the old branch would conflict again when the conductor replays it, and the
conductor's second rebase checks that it did. It has `Edit` and not `Write`: resolving a conflict
changes files that exist. Its rebase commands are spelled out whole (`git rebase main`,
`--continue`, `--abort`), because a `git rebase *` rule would admit `--exec <any command>`.

## The roles an L2 absorb launches, and the second role that may judge

`absorb`, `synthesizer`, and `critic` are not assigned to tickets either; `wayline.absorb` launches
them, and their `kinds` are empty. `absorb` is the one headless session of a level-2 read: its only
job is to start the saved workflow `workflows/absorb.js` with the arguments code wrote, which is why
its `allowed_tools` are the narrow `Workflow(absorb)` and `Skill(absorb)` rules plus `Read`, `Glob`,
and `Grep`, and why `Workflow` and `Skill` are not on its removal list. The `reader` and the
`synthesizer` run inside that session as workflow agents, defined in the same `--agents` object; in
the conductor fan-out each is a session of its own.

`critic` is the second role with `may_judge`, beside `verifier`. The gate reads the role an ask
names, refuses one without `may_judge`, and runs it on the verifier's tier for the author's model,
so the depth spot-check of an L2 dossier is the critic's read of work the readers wrote on sonnet.
Ticket 29 gives the critic its other job, the position memo.

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
