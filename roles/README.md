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

## The critic's other job: the position memo

Ticket 29 gives the critic its second job. `wayline position` (`wayline.position`) launches it on
`policy.roles.critic` (`opus`, `high`) with the `position` schema in place of `verdict`, so the
sidecar's `output_schema` stays the verdict the gate reads. Its protocol file therefore has one
section per job, `## Verdict` and `## Position`, and each launch is given only its own
(`worker.protocol_for`). The session is fresh and reads only the dossiers, `INTAKE.md`, and
`OBJECTIVES.md` (decision 17, in place of `GOAL.json`; ticket 80). The intake and the objectives are
inlined in its prompt with the dossiers, and it runs in
`research/refs/` with its `Read`, `Glob`, and `Grep` rules scoped to that directory
(`Read(//<project>/research/refs/**)`), so no decision, spec, or earlier memo can reach it. The
working directory alone would not do that: under `dontAsk` a bare `Read` rule reads any path, and a
scoped `Read` alone still lets `Glob` and `Grep` reach outside (`docs/verification/m4.md`). Code
checks what it returns, has the scout verify every citation, and renders `research/POSITION.md`: a
verdict on each open or parked objective, a revised target only for a goal, and directions that
name the objectives they would pursue, as proposals the grill's first tier puts to the owner.

## The decider is launched by the grill and the conductor, one decision per session

`decider` (ticket 31) is outside the librarian's reach too (`kinds` empty), and it is not a judge:
`may_judge` is false, and its `output_schema` is `decision`, the record of `DECISIONS.md` and of a
decision ticket's body. `wayline.decider` launches it, once per open decision, on
`policy.roles.decider` (`opus`, `max`): `wayline grill --decide-rest` walks the design tree's
frontier with it after the autonomy switch, and the conductor launches it in wave step 5 for every
open decision ticket that is not human-only and at the end of the wave for every parked proposal.
A decision ticket is therefore never picked as a worker: it has no touch set, no acceptance, and
nothing to commit, so the session runs in the project itself with `Read`, `Glob`, and `Grep` only,
and the touch-set guard blocks any write it might try, as it does for the verifier.

Its prompt is assembled by `wayline.decider.decider_prompt`: the one decision (the question, the
options, the recommendation, the evidence, the prerequisites' answers), the irreversible list and
the project's human-only classes (`objective` in place of `goal`, which is read so), the project's
radius, which bounds the objectives it may add, and the records inlined in order (`DECISIONS.md`,
`POSITION.md`, `OBJECTIVES.md`, the L0 and L1 records, the query pack), cut at the context cap with
the cut announced.
The session hands back a decision on the irreversible list with `answer: null`, and code refuses one
it did give anyway (`decider.irreversible_class`, read on the option's words when the answer only
points at an option): a refused decision becomes the owner's, as a human-only question in the tree
with a human-only decision ticket beside it, as a decision ticket turned human-only, or, for a
parked proposal, as a human-only decision ticket asking whether it is admitted. A project that puts
it on Fable sees it fall back to Opus at the same effort under the fallback consent while Fable's
weekly window is spent, and every decision records the model and the session it came from: a grill
question in its `DECISIONS.md` record, a decision ticket in its `## Answer`, the journal, and a
record appended to `DECISIONS.md`, a parked proposal in the journal alone.

## The planner is launched by the phase verbs, one protocol per phase

`planner` (tickets 33 and 34) is launched by code too (`kinds` empty) and does not judge. Its protocol
file, `prompts/roles/planner.md`, holds one `## <Phase>` section per phase, and the verb that launches
it gives the session only its own (`wayline.worker.protocol_for`). `wayline specify` launches it on
`policy.roles.planner` (`opus`, `xhigh`) with the `spec` schema and the decider's records, reading
only: code writes what it returns as `research/spec.json`, renders `research/SPEC.md`, runs the
structural checks, and asks the verifier for the `spec_coverage` verdict, returning the draft to the
same session once per gate. `wayline plan` launches it the same way in its plan protocol, with the
`plan` schema (the sidecar's `output_schema` stays `spec`; each verb passes its own), on
`research/SPEC.md`, `GOAL.json`, the query pack, the registry, and the journal's failures: code
numbers the tickets it returns, has the librarian assign a role and skills to each, runs the
plan-time checks (the machine criteria in a checkout of `main`), writes `research/tickets/` and
`graph.json`, opens the decision tickets it reports, and asks for the graph's confirmation by the
autonomy. A plan that fails the checks is returned to the same session once. `--replan` and `--split`
launch it again over the graph as it stands, which is what the conductor calls at a stall and at the
`split` rung of the escalation ladder.

## The evolver is launched by the evolve loop, one session over the pending feedback

`evolver` (ticket 45) is launched by code too (`kinds` empty), does not judge, and writes nothing.
`wayline.changes.evolve` launches it on `policy.roles.evolver` (`opus`, `xhigh`; Opus in Fable's
place when a project puts it on Fable and the hold on Fable's weekly window says so), with the
`change_list` schema: from `wayline evolve`, from `wayline run` once `run_ended` is journaled, and
from the conductor in the wave that finds feedback pending. Its prompt carries the pending items (the owner's, and the retrospective
code filed), the journal numbered by line so that evidence is cited as `research/journal.jsonl#L<n>`,
the change records already open, the registry, and the policy with the project's overrides; the
project and the harness repository are open to it for reading. Code gives each record it returns an
id and a status, forces `risk: high` on a change to the rung ladder, checks the evidence, the target,
and the fixture's name, returns a failing list to the same session once, keeps the records as
`research/changes/<id>.json`, and files one `harness` ticket per record, which the `coder` works
like any ticket.

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

## The figure designer and the figure critic are launched by the figure role, one job per session

`figure-designer` and `figure-critic` (ticket 50) are launched by code (`kinds` empty), from
`wayline.figure_role`, which is the figure role of Implementation Decisions 13: `wayline figure make`
on a `figure_request/1`, and the paper's builder the same way. Both run on `policy.roles`
(`opus`, `high`), from the project root. Code does every step that is not a drawing or a judgment:
it classifies the data shape, takes the candidates from `figures/plot_index.json` (or the layouts of
`figures/structure_index.json` for a framework figure), makes the pick, runs the 19 machine checks,
and asks the verifier for the honesty verdict through the gate.

The designer has two jobs, each a fresh session given only its own section of
`prompts/roles/figure-designer.md`: `## Drafts` returns `figure_drafts` (the sidecar's
`output_schema`), and `## Finish` returns `figure_finish`, on the chosen draft or on a guided
revision's change requests. It writes only under `figures/<figure_id>/` (`TICKET_TOUCHES`), runs
Python and nothing else, and commits nothing. Its prompt carries doctrine and never a library fact:
what a library gets wrong arrives candidate by candidate from the plot index, and the designer says
which pitfalls it read as `pitfalls_consulted`.

The critic is a fresh, read-only session over the drafts, never the session that drew them. It has
`may_judge`, like the critic, and returns `figure_ranking`: every rendered draft ranked, with a score
on `claim_legibility`, `honesty`, `venue_fit`, and `legibility_at_size`, and the reasons.

## The documentarian takes the `docs` tickets

`documentarian` (ticket 51) is the one role whose `kinds` name `docs`, so the librarian gives it
every `docs` ticket; the `coder` no longer covers them. It runs as a ticket worker like the coder,
on the rung the ticket's difficulty gives, and its protocol is three verbs of `wayline.docs`:
`wayline docs init` records the theme once per project in `harness.json.docs` (with the package and
the layout) and lays out the missing skeleton, `wayline docs env` installs `docs/requirements.txt`
into the project's own environment (the harness never imports Sphinx), and `wayline docs build`
runs the machine checks. The conductor accepts every `docs` ticket by `wayline docs build` besides
the ticket's own criteria (`tickets.machine_acceptance`), so a failing check returns the ticket with
the list, and a done `docs` ticket earns one read of the site's clarity and completeness against the
package's purpose (`gates.DOCS_READ`) in place of the read its difficulty would give it. Its Bash
rules are the coder's with `wayline docs *` added and no `Agent`: a site is written in one session.

## The writer is launched by code, and takes the `writing` tickets

`writer` takes every `writing` ticket as a ticket worker, and code launches it read-only and on
`policy.roles.writer` rather than a rung for `wayline paper`, the whole manuscript (`paper_draft`,
ticket 53), and for `wayline consolidate`, a section the owner asked to have rewritten (ticket 88).
The ledger writes what it returns, since nothing under `research/` is a session's to write. The
general report, `REPORT.md`, is rendered by code alone since ticket 90: no writer drafts any of it.
The paper's session is resumed with each failed build's list (the linter, the venue's seven checks, a
figure the figure role could not place), and it is given the open `writing` tickets a failed kill
argument or the independent read filed against the paper. The prompt carries the venue's `guidelines.json`, the
findings with their tags, and the references a `ref` tag can name; `agent.md` stays the C8 rule every
launch shares.

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

## The code reader is launched by the code-to-Methods check

`code-reader` is not assigned to tickets either (`kinds` empty). At a ticket's acceptance, the rule
from code to Methods (`wayline/methods.py`, ticket 107) reads Python and MATLAB with parsers that
spend no tokens; a changed file in any other language, or a MATLAB file tree-sitter-matlab could not
parse, gets one session of this role on `policy.roles.code-reader` (Sonnet at medium effort), with no
tools and the files in its prompt. It returns `code_reading`: what the changed lines develop, use,
and set. Code keeps an item only when grep finds it in the file and applies the same rule to it, so
the reader names things and never judges them.

## The critique splitter is launched at setup, one session per batch of critiques

`critique-splitter` is not assigned to tickets either (`kinds` empty). Once the owner's documents are
sorted, `wayline concern split` and `wayline position` (before the critic reads the concerns) launch
one session of it on `policy.roles.critique-splitter` (Sonnet at medium effort) for every critique not
split yet (`wayline/concerns.py`, ticket 96), with no tools and the critiques and the inherited claims in
its prompt. It returns `concern_split`: each point verbatim with every critique that raised it, praise
and summary left out, a two-point item split, and the inherited claims it targets. Code keeps a source
only when its words are in that critique, locates it at its block, keeps a target only when it is an
inherited claim standing now, and merges near-identical points from different critiques.
