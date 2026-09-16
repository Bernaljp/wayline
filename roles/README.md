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

## The verifier and the fixture judge are launched by code, not assigned to a ticket

Every other role here is assigned to a ticket by the librarian and launched by the conductor.
`verifier` is not: `wayline.gates.verdict` launches it and its `kinds` is empty. Neither is
`fixture-judge`, which `wayline fixture run` launches once per sample with no tools, the fixture's
rubric, and only the fields the fixture shows it (Implementation Decisions 12). Both have
`may_judge`, as the critic below does. The verifier's prompt is assembled by the gate too, from the
one question, the scope
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

## The roles an L2 absorb launches, and another role that may judge

`absorb`, `synthesizer`, and `critic` are not assigned to tickets either; `wayline.absorb` launches
them, and their `kinds` are empty. `absorb` is the one headless session of a level-2 read: its only
job is to start the saved workflow `workflows/absorb.js` with the arguments code wrote, which is why
its `allowed_tools` are the narrow `Workflow(absorb)` and `Skill(absorb)` rules plus `Read`, `Glob`,
and `Grep`, and why `Workflow` and `Skill` are not on its removal list. The `reader` and the
`synthesizer` run inside that session as workflow agents, defined in the same `--agents` object; in
the conductor fan-out each is a session of its own.

`critic` has `may_judge` too, beside `verifier` and `fixture-judge`. The gate reads the role an ask
names, refuses one without `may_judge`, and runs it on the verifier's tier for the author's model,
so the depth spot-check of an L2 dossier is the critic's read on the verifier the table gives for the
synthesizer's model. That may be the synthesizer's own model, in a fresh session carrying none of the
dossier's context; it is never Haiku, and while Fable's weekly window is spent a critic on Fable runs
on Opus at the same effort under the fallback consent, like any verdict on Fable.
Ticket 29 gives the critic its other job, the position memo.

## The decider is launched by the grill and the conductor, one decision per session

`decider` (ticket 31) is outside the librarian's reach too (`kinds` empty), and it is not a judge:
`may_judge` is false, and its `output_schema` is `decision`, the record of `DECISIONS.md` and of a
decision ticket's body. `wayline.decider` launches it, once per open decision, on
`policy.roles.decider` (`fable`, `max`): `wayline grill --decide-rest` walks the design tree's
frontier with it after the autonomy switch, and the conductor launches it in wave step 5 for every
open decision ticket that is not human-only and at the end of the wave for every parked proposal.
A decision ticket is therefore never picked as a worker: it has no touch set, no acceptance, and
nothing to commit, so the session runs in the project itself with `Read`, `Glob`, and `Grep` only,
and the touch-set guard blocks any write it might try, as it does for the verifier.

Its prompt is assembled by `wayline.decider.decider_prompt`: the one decision (the question, the
options, the recommendation, the evidence, the prerequisites' answers), the irreversible list and
the project's human-only classes, and the records inlined in order (`DECISIONS.md`, `POSITION.md`,
`GOAL.json`, the L0 and L1 records, the query pack), cut at the context cap with the cut announced.
The session hands back a decision on the irreversible list with `answer: null`, and code refuses one
it did give anyway (`decider.irreversible_class`, read on the option's words when the answer only
points at an option): a refused decision becomes the owner's, as a human-only question in the tree
with a human-only decision ticket beside it, as a decision ticket turned human-only, or, for a
parked proposal, as a human-only decision ticket asking whether it is admitted. While Fable's weekly
window is spent it falls back to Opus at the same effort under the fallback consent, and every
decision records the model and the session it came from: a grill question in its `DECISIONS.md`
record, a decision ticket in its `## Answer`, the journal, and a record appended to `DECISIONS.md`,
a parked proposal in the journal alone.

## The planner is launched by the phase verbs, one protocol per phase

`planner` (ticket 33) is launched by code too (`kinds` empty) and does not judge. Its protocol file,
`prompts/roles/planner.md`, holds one `## <Phase>` section per phase, and the verb that launches it
gives the session only its own (`wayline.specify.protocol_for`). `wayline specify` launches it on
`policy.roles.planner` (`fable`, `xhigh`) with the `spec` schema and the decider's records, reading
only: code writes what it returns as `research/spec.json`, renders `research/SPEC.md`, runs the
structural checks, and asks the verifier for the `spec_coverage` verdict, returning the draft to the
same session once per gate. Ticket 34 gives it its plan protocol, and the tickets it cuts.

## The consultant answers one question about one dossier

`consultant` (ticket 26) is launched by code as well (`kinds` empty), on `policy.roles.consultant`
(`sonnet`, `medium`), read-only, with the `consultant_answer` schema: `answer`, `locators`,
`confidence`, `not_in_source`, and `promote_requested`. It has two entry points. `wayline consult
<slug> "<question>"` (`wayline.consult.ask`) launches it from the project root with the question as
the prompt and `research/refs/<slug>` as `--add-dir`. It is the only form a worker calls, and the
`coder`, `experimenter`, `analyst`, and `writer` have `Bash(wayline consult *)` for it. The
request blanks the asking worker's `TICKET_ACCEPTANCE_FILE` and `TICKET_TOUCHES`, which the nested
launch would otherwise inherit: the stop guard would hold the consultant until the worker's own
acceptance ran. Inside `workflows/absorb.js` the consultant is an `agent()` call that answers a
reader's clarification question, and the script returns the answer to code.

Code validates every answer again, including the rule the schema leaves out: an answer read in
the source names a locator. The ledger then appends the exchange to `refs/<slug>/qa_log.md`, one
line each, and journals `consulted`. `promote_requested: true` is the `consultant_question`
trigger of `dossier.promote`, so a question an L1 skim cannot answer promotes the paper inside the
phase's budget, or opens a decision ticket beyond it. A question asked under `WAYLINE_TICKET` counts
against that ticket, and the one past `policy.consultant.max_questions_per_ticket` (5) is refused
before a session starts. One L2 absorb may put as many reader questions to the consultant as one
ticket may ask.

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

## The experimenter and the analyst

`experimenter` takes `experiment` tickets and never runs the experiment: it commits the script,
writes one job file per run with `wayline job add` (the only role with that rule, beside
`nvidia-smi` to look at the card), and returns `status: running` with the job ids. The conductor
integrates its branch, places each job on free devices by the free-slot rule, polls the jobs every
wave, steps the ticket's `retry` ladder on an out-of-memory job, and closes the ticket once every
job exited 0 and its outputs parsed and were manifested (ticket 19). `analyst` takes `analysis`
tickets: it reads the manifested results in the project's `results/` and files findings whose
provenance the manifest resolves; `wayline job add` is on its removal list.
