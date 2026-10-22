# SpecDrivenResearch: brief for an autonomous, self-improving research harness on a Claude Code subscription

Revision 2, 2026-09-11. Revision 1 was reviewed by the owner and this revision applies that review in
full: the harness is built from scratch (the owner's existing skills are inspiration, not components),
skills are uncapped but never nested, external model reviewers are optional, the harness improves itself
from the owner's feedback, it serves one project at a time with no cross-contamination, it uses the
workstation's GPUs and CPUs in parallel, it survives subscription windows through recurrent jobs, it
reads references lazily, it pauses on human-decision tickets, it can chase a quantitative goal, it stops
at a report, and it continues to a paper on request under a chosen journal's guidelines.

Labels:

- **DECIDED**: a constraint the owner stated, or a design decision made here because the owner asked for
  the structure and the roles to be decided for them. Settled unless the planning session overturns it.
- **RECOMMENDED**: the preferred option with its reason. Change it if the reason does not hold.
- **OPEN**: a question the first planning session must resolve. Each carries a recommended answer.

The paste-ready prompt for that session is in Section 18.

---

## 1. Purpose in one paragraph

Build a harness that takes a research intent at any level of specificity (a vague direction plus a pile
of references, or a precise plan with half an implementation, optionally with a quantitative goal) and
carries it to a finished report: references absorbed to the depth they deserve, the idea positioned
against the literature, a specification, an executable graph of tickets, implemented and documented
code, experiments and analyses run on the local machine, results verified, and every claim traced to a
result or a reference. The human decides how much to be involved, and can be asked through decision
tickets that pause exactly the work that depends on them. After the human says "continue on your own",
the harness runs unattended until the graph is empty or the goal is met, across subscription windows,
using only a Claude Code subscription. Deterministic code decides what runs, when, on which resources,
and what counts as done; models decide only content. On request the report continues into a paper for a
chosen journal. When the owner says what should have gone better, the harness changes itself: skills,
roles, policies, or code, tested and versioned, local to the project first and global when the owner
promotes the change. While it runs it serves a local dashboard: a tab per project, an index of every
output with downloads, and the controls the human needs, reachable from a laptop through a tunnel.

## 2. Requirements, traceable

| ID | Requirement (owner's words, condensed) |
|----|------------------------------------------|
| R1 | Runs on a Claude Code subscription, no API keys. Portable later to other subscription CLIs if cheap. |
| R2 | Automatic research: once told to continue, it goes to completion without input at each stage. |
| R3 | Programmatic pipeline: code structures the flow (roles, sequences, cycles), not a pile of prose skills. |
| R4 | Spec-driven: tiered rounds of questions, then a spec, then tickets, then implementation of tickets one by one without shared context. |
| R5 | Autonomy switch: "this is enough, decide the rest yourself with a high-effort agent" and continue to the end. |
| R6 | Automatic ticket execution: know what can run in parallel (dependencies and conflicts), run it, merge, close, keep going until done. |
| R7 | Each ticket carries a difficulty; difficulty picks the model and the thinking effort. |
| R8 | Roles are decided by the designer, machine-native, not a copy of a human lab. |
| R9 | Any starting point, vague to precise, nothing to partly implemented; say whether the idea makes sense; respect "stay close" versus "explore". |
| R10 | Reference experts: whole-paper and whole-codebase knowledge that other agents can query; force full reading where it matters. |
| R11 | Internal communication, memory, skills, and indexes need not be English or human-apprehensible; they should minimize loss and maximize retrieval. |
| R12 | Simpler than ARIS. What is disliked is skills nested in skills, not the number of skills. |
| R13 | Self-modification: after a run, the owner says what to improve and the harness changes itself (new skills, changed role behavior, whatever it judges right), safely. |
| R14 | One project at a time. The whole pipeline is local to a project; a new project runs clean. Cross-project reuse only when the owner promotes something (a skill) to the harness. |
| R15 | External model reviewers (Codex or others) are optional, chosen by the owner per step, never required. |
| R16 | Several global or local skills are allowed when they improve the workflow; none calls another. |
| R17 | Build from scratch. The existing ARIS-adapted skills are not used; if something similar is needed, create it. The figures skill is a stronger inspiration, reviewed critically, not copied verbatim. |
| R18 | In any report or paper, every claim comes from the data or results, or from a reference. |
| R19 | Whoever assigns tickets also assigns which skills a ticket should use; some role knows all skills in general terms to assign them well. |
| R20 | Skills, roles, and memories that are not human-facing need not be human-readable. |
| R21 | Experiments and analyses are heavy GPU and CPU jobs; run them in parallel on the workstation that launched the harness. Using the machine is encouraged. |
| R22 | Recurrent jobs and fallbacks: if the usage window is exhausted, a job checks every window and relaunches until everything is done. |
| R23 | Large literature intakes are not read in full; full reading happens when a paper is deemed important for the current front. |
| R24 | Decision tickets: questions to the user that pause the dependent work until answered, picked up by the recurrent job. |
| R25 | The owner may set a quantitative goal; it must be clear, measurable, and feasible, and the harness works toward it. |
| R26 | The general report is always current; the paper is made only on an explicit order, from the owner, or from the decider in an autonomous run. (Revised by spec decision 17, ticket 115: it read "The full report is the stopping point; then continue to a paper with a chosen journal, or the harness chooses, from a local repository of journal guidelines.") |
| R27 | A figures capability with an index of possible plots for given data (python-graph-gallery, r-graph-gallery, Altair as references). |
| R28 | A documentation capability that makes implemented packages understandable, complete, and good-looking (Read the Docs style). |
| R29 | While the harness runs it serves a local dashboard: a tab per project, an index of every output with downloads, and the controls the human needs, reachable from a laptop through a tunnel to the workstation. |

## 3. Inspiration and verified facts

Everything in this section is background for the planning session. None of it is a constraint except
the verified capabilities in 3.1, which bound what can be built.

### 3.1 Code-shaped control flow on a subscription: yes, three ways (verified)

Verified on the installed CLI (`claude --version` = 2.1.268) and the official docs:

1. **Headless sessions from any script.** `claude -p "<prompt>"` uses the same subscription login as
   the interactive session (only `--bare` switches to API keys). A script can launch as many headless
   sessions as it wants, each with its own model, effort, permissions, worktree, preloaded skills, and
   structured output. Flags present in 2.1.268: `-p/--print`, `--output-format text|json|stream-json`,
   `--json-schema`, `--model`, `--fallback-model`, `--effort low|medium|high|xhigh|max`,
   `--permission-mode acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`, `--allowedTools`,
   `--disallowedTools`, `--agents <json>` (inline agent definitions: prompt, model, tools, `maxTurns`,
   `skills`), `--agent <name>`, `--append-system-prompt[-file]`, `--settings <file-or-json>` (hooks
   included), `--setting-sources`, `--strict-mcp-config`, `-w/--worktree [name]`, `--bg`, `--resume`,
   `--continue`, `--session-id`, `--input-format stream-json`. No `--max-turns` in this version; turn caps
   live in the agent definition.
2. **Workflow scripts inside a session.** The Workflow tool runs plain JavaScript calling
   `agent(prompt, {schema, model, effort, isolation: 'worktree', agentType})`, `parallel()`, `pipeline()`,
   `phase()`, with schema-validated returns, up to 16 concurrent agents, resume from a run id, and saved
   scripts in `.claude/workflows/*.js`. Right for deterministic fan-out inside a phase. Wrong for the outer
   loop: it cannot take input mid-run, cannot sleep, cannot touch the file system from the script.
3. **Hooks.** Shell commands on `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `SessionStart`,
   `UserPromptSubmit`, `PreCompact` and others can block an action, inject context, or verify a condition,
   in headless sessions and subagents too. They are the mechanism for machine-enforced rules.

Not on the table: the Claude Agent SDK. Anthropic's SDK docs state that third-party developers may not
offer claude.ai login for products built on the SDK without prior approval. Driving the official CLI from a
personal script is ordinary CLI use; the design never leaves the CLI.

Usage limits are per subscription window (five-hour and weekly), shared by every session and subagent,
so parallel model work multiplies consumption. Hardware jobs cost nothing against the subscription.

An external model for reviews is possible without API keys (a `codex` CLI on a ChatGPT subscription is
one such backend, and one is connected in this environment), but nothing here depends on it (R15).

### 3.2 ARIS, as it actually is (inventoried from a clone at HEAD f1bd907, 2026-09-11)

- 82 mainline skills, 31 shared contract documents, three mirror trees for Codex variants: 187 skill
  files, 105 of them nested. A README of 1,793 lines that an open issue calls unreadable.
- No scheduler, no daemon, no master loop. "In sleep" means a human types one skill in a live session and
  leaves the terminal running; the skill loops internally and writes state files so the model can resume
  after compaction. Their own recovery guide admits nothing guarantees that the model reads them.
- Enforcement is prose; issues report skills silently skipping sub-skills. Their programmatic parts are
  small: a 60-second experiment queue with dependencies, a stale-session watchdog, a stall counter, a
  review gate table, an injection scanner.
- Doctrines worth keeping: Type-A versus Type-B gates ("a loop can drive, it cannot acquit"); reviewer
  independence (paths, not summaries); `done` versus `accepted`; deterministic pre-checks before spending a
  model verdict; a two-thread kill argument; stall detection that forces a structural pivot; scope limits
  in every reviewer prompt; an edges-only knowledge graph with a size-capped query pack.

### 3.3 Matt Pocock's skills (installed plugin 1.2.3, verified against the upstream repository)

- `grilling`: a design tree; each round asks the whole frontier (every question whose prerequisites are
  settled); questions are numbered with a recommended answer; facts are looked up, decisions are asked;
  it ends when the frontier is empty and the human confirms. It refuses a "decide for me" mode on
  principle, so the autonomy switch here is a deliberate, labeled departure.
- `wayfinder`: a map of decision tickets with a destination, fog of war, and frontier; it plans and
  hands off to `to-spec`. `to-spec` writes a decision record with test seams. `to-tickets` cuts
  tracer-bullet tickets with blocked-by edges (no size or difficulty). `implement` runs one ticket per
  fresh session, does not dispatch, does not run in parallel, does not close the ticket; its docs say batch
  dispatch is "requested repeatedly and does not exist". Several sessions in one checkout corrupt git.
- His separate Sandcastle project (TypeScript) runs one agent in a sandboxed worktree with branch
  strategies and merges commits back: prior art for the integration layer, not a dependency.

### 3.4 The owner's existing skills: inspiration only (R17)

The thirteen ARIS-adapted skills under `~/.claude/skills` are not called, copied, or depended on. They
are reading material for the roles that replace them, and the planning session should mine them for
traps and checklists, then write fresh. The strongest inspiration is `~/.claude/skills/paper-figures`
(261 lines plus a references directory, improved during the scHopfield work): its two working modes
(unguided design, where comparables are surveyed before anything is drawn, and guided iteration), the
register rules for a framework figure, the honesty discipline, the matplotlib and TikZ traps, and the
verification loop. Critical review before adoption: it assumes a human author directing panel by panel,
whereas the harness needs the unguided mode to end in a ranked set of rendered candidates; its traps are
library-specific and should be regenerated for whatever the plot index selects; its verification loop is
prose and should become a checklist with machine checks where possible and one Type-B verdict for "does
the figure assert something the data does not".

## 4. Hard constraints (DECIDED)

- **C1 Runtime.** Everything runs through the official Claude Code CLI: interactive sessions for the
  human-in-the-loop phases, `claude -p` sessions for unattended work, Workflow scripts for in-session
  fan-out, hooks for enforcement. No Agent SDK, no mandatory API key. External model reviewers are an
  optional verifier backend the owner enables per step.
- **C2 Control flow is code.** A model never decides what runs next at the pipeline level. Code computes
  the frontier, allocates resources, launches sessions and jobs, checks results, merges, closes, retries,
  pauses on usage limits, and terminates. A model may propose tickets or harness changes; code admits
  them under rules.
- **C3 State is files, and project-local.** All durable project state lives under `<project>/research/`
  and `<project>/.claude/`, as markdown for humans and JSON with schemas for machines. Global state lives
  only in the harness repository (code, global skills, roles, policies, guidelines, indexes, test
  fixtures). No mutable state is shared between projects. Every durable write into shared state goes
  through code, from a structured result.
- **C4 Skills compose in code, never in skills.** A skill never invokes another skill; sequencing lives
  in the conductor and in Workflow scripts. The number of skills is not capped. Skills are global (in the
  harness) or local (in a project). Every skill is registered with a capability summary so the librarian
  can assign it to tickets (Section 5.5).
- **C5 Build from scratch.** Nothing in the harness calls the owner's existing skills. Capabilities they
  covered (literature search and verification, experiment planning and running, compute detection,
  reviewer routing, knowledge base, review loops, paper writing, figures) are rebuilt as harness roles,
  code, and skills, with those skills as inspiration and `paper-figures` as the strongest one.
- **C6 Verification doctrine.** Type-A gates (a script with no taste could answer: exit codes, files
  exist, tests pass, N seeds ran, provenance present) are judged by code. Type-B gates (correct, novel,
  supported, clear, good enough) are never judged by the session that produced the work: a fresh
  independent session, on a different model where possible, or an optional external model, or the human.
  Machine pre-checks run before any paid verdict.
- **C7 Unattended safety.** Worker sessions run with `--permission-mode dontAsk`, an explicit tool
  allowlist, and hooks that deny writes outside the ticket's touch set and deny destructive commands.
  Irreversible actions (deleting data, force-pushing, pushing to shared branches, exceeding the compute or
  usage budget, spending money, changing the harness globally) stay human-gated in every autonomy mode
  unless the intake pre-authorizes them.
- **C8 Claim provenance.** In every human-facing report or paper, every claim traces to a result
  artifact (with the run that produced it) or to a verified reference (with a locator). A linter enforces
  presence (Type-A); a verifier checks support (Type-B). Negative results are findings. Nothing is
  fabricated, including citations.
- **C9 Use the machine.** Experiments and analyses run on the workstation's GPUs and CPUs, in parallel,
  under a resource manager that keeps a reservation for the interactive session. The subscription is
  spent on judgment; the hardware on computation.
- **C10 Governed self-modification.** Changes to the harness go through the same ticket machinery, with
  tests and versioning, project-local first, promoted to global only by the owner.

## 5. Architecture

### 5.1 Three layers

```
  +---------------------------------------------------------------------+
  |  PROGRAMS (deterministic)                                            |
  |  conductor   frontier, worktrees, launch, checks, merge, journal     |
  |  resources   GPU/CPU/RAM slots, detached jobs, polling, OOM retry    |
  |  tick        recurrent job: relaunch after windows, answers, jobs    |
  |  registry    skills and roles, global and local, capability index    |
  |  evolve      feedback -> change records -> harness tickets -> tests  |
  |  workflows   in-session fan-out scripts (absorb, panel, verify)      |
  |  hooks       write-scope guard, command guard, stop guard            |
  |  dashboard   local web view: projects, outputs, downloads, answers   |
  +---------------------------------------------------------------------+
                 | launches / reads / writes
  +---------------------------------------------------------------------+
  |  LEDGER (files in <project>/research/, one project at a time)        |
  |  INTAKE  GOAL  CONTEXT  DECISIONS  POSITION  SPEC  refs/  kb/        |
  |  tickets/  graph.json  journal.jsonl  jobs/  findings  REPORT  paper/|
  +---------------------------------------------------------------------+
                 | every session starts from here
  +---------------------------------------------------------------------+
  |  RUNTIME (Claude Code on the subscription + the workstation)         |
  |  interactive session | claude -p workers | subagents | GPU/CPU jobs  |
  +---------------------------------------------------------------------+
```

The model layer is stateless by construction. Anything a model must remember is in the ledger; anything
a model must be prevented from doing is a hook; anything that must happen in a fixed order is in the
conductor. That is the answer to "enforcement is prose".

### 5.2 Global versus local, and switching projects (R14)

- **The harness** is one repository, installed once, versioned with tags. It holds code, global skills,
  role definitions, prompt templates, schemas, hooks, policy defaults, journal guidelines, the plot index,
  and test fixtures. Nothing project-specific ever lands in it except through promotion.
- **A project** holds its ledger under `research/`, its local skills under `.claude/skills/`, local role
  overrides under `.claude/agents/`, and `harness.json` (pinned harness version, policy overrides, autonomy,
  radius, budgets). A new project starts from the harness's templates and nothing else.
- **One active project at a time.** A pointer in the harness's config names the active project, and `projects.json` there lists every project `init` has touched (the dashboard's tabs). `switch
  <path>` lets running workers finish (or checkpoints them), stops the conductor, moves the pointer; the
  recurrent tick serves only the active project. Two conductors at once is OPEN-3 (recommended: no, because
  usage windows are shared and the resource manager is simpler with one owner).
- **No cross-contamination.** A session for project A never loads project B's ledger; the harness's own
  memory holds only harness matters; Claude Code's auto-memory is per project directory already. Reusing a
  dossier from another project is an explicit copy with provenance, never a shared store.
- **Promotion** is the one sanctioned crossing: a local skill, role override, or policy that the owner
  wants everywhere is promoted into the harness by the evolve loop (Section 12).

### 5.3 Layout

**The harness repository** (this directory):

```
SpecDrivenResearch/
  BRIEF.md
  bin/<cli>                  init | intake | absorb | grill | plan | run | status | answer | switch | evolve | promote | paper | upgrade
  <pkg>/                     Python, standard library only
    conductor.py             frontier, scheduling, worktrees, launch, integrate, pacing, journal, resume
    resources.py             hardware detection, slots, reservations, detached jobs, polling, OOM retry
    tick.py                  the recurrent job (Section 9.6)
    tickets.py               schema, graph.json, local tracker; optional GitHub mirror
    worker.py                prompt assembly, claude -p invocation, result validation, session resume
    registry.py              scans global and local skills and roles into registry.json
    dossier.py               source acquisition, inventory, chunking, coverage audit, promotion
    kb.py                    project knowledge base: nodes and typed edges, query pack
    scout.py                 literature search and citation existence checks (arXiv, OpenAlex, Crossref, Semantic Scholar; no keys)
    gates.py                 Type-A checks; Type-B routing (fresh session, external model, human)
    provenance.py            the claim-provenance linter for reports and papers
    ledger.py                the only writer of shared state; findings and REPORT rendering
    evolve.py                feedback -> change records -> harness tickets -> fixtures -> version
    figures.py               plot index queries, candidate rendering, mechanical figure checks
    docs.py                  documentation site scaffolding and completeness checks
    dashboard.py             local web server: JSON API over the ledger, file downloads, actions routed through the CLI functions
  roles/                     agent definitions (system prompt, tools, model, effort, skills), one file per role
  skills/                    global skills; each has a registry entry; may be model-authored and non-human-readable
  prompts/                   templates for phases and gates
  schemas/                   ticket, result, dossier, code_dossier, decision, proposal, goal, change, registry_entry, journal_event
  workflows/                 absorb.js  panel.js  verify.js
  hooks/                     touch_set_guard.sh  command_guard.sh  stop_guard.sh  worker-settings.json
  dashboard/                 static single-page app (HTML, CSS, vanilla JS), no build step
  guidelines/<venue>/        journal and conference guidelines (Section 13.3)
  figures/plot_index.json    the plot index (Section 13.1)
  fixtures/                  recorded cases for regression tests of prompts, skills, roles, and the conductor
  templates/project/         what init lays down in a project
  tests/                     conductor and resources tested with a fake worker and fake jobs
```

**A project** (state only):

```
<project>/
  CLAUDE.md                  a short block pointing at research/ and the pinned harness
  harness.json               pinned version, policy overrides, autonomy, radius, budgets, resource reservations
  .claude/skills/            local skills (created by the harness or the owner during this project)
  .claude/agents/            local role overrides
  research/
    INTAKE.md                intent, references, data, constraints, autonomy, radius, budgets
    GOAL.json                optional quantitative goal (Section 6.4)
    CONTEXT.md               vocabulary the interview settles
    DECISIONS.md             question, answer, rationale, decided-by (human | decider), confidence
    POSITION.md              novelty and feasibility memo ("does this make sense")
    SPEC.md                  the research spec
    refs/<slug>/             source, figures/, dossier at its current level, code/, qa_log.md
    kb/                      nodes (papers, ideas, experiments, claims) and edges.jsonl; query_pack.md
    tickets/NN-slug.md       one file per ticket
    graph.json               the ticket graph, the only thing the conductor schedules from
    journal.jsonl            append-only event log; resume replays it; the report is built from it
    jobs/<id>.json           hardware job handles the resources module polls
    findings.jsonl           numbered findings with provenance; findings.md is rendered from it
    REPORT.md                the stopping point
    paper/                   on request (Section 13.3)
    feedback/                the owner's improvement notes for the evolve loop
```

### 5.4 Which mechanism implements what

| Need | Mechanism |
|------|-----------|
| Interactive ideation in tiered rounds | interactive session; the harness's own grill skill (rounds, recommended answers, facts looked up) |
| Read a whole paper without skimming | Workflow `absorb.js`: pipeline over chunks and figures with obligation lists; coverage audited by code |
| An expert other agents can ask | `roles/consultant` loaded with one dossier; Agent tool in-session, or `claude -p --agent consultant` from code |
| Decide the rest without the human | `claude -p --effort max` on the decider role, output validated against `decision.json` |
| One ticket, one fresh context | `claude -p` in a conductor-owned worktree, `--agents` supplying role, model, effort, tools, `maxTurns`, `skills` |
| Parallel tickets without collisions | one worktree per ticket; touch sets enforced by a `PreToolUse` hook; serialized integration |
| Heavy experiments and analyses | `resources.py`: detached jobs on assigned GPUs and CPU cores, polled by the tick; no session waits |
| Quality verdicts | `gates.py`: fresh independent session (different model where possible), optional external model, or human |
| Keep running across windows and restarts | the conductor pauses on limits; the recurrent tick relaunches; the journal is the state |
| Ask the human and wait | `decision` tickets; notification; `answer <id>`; the tick resumes the subgraph |
| Improve the harness from feedback | `evolve.py`: change records, harness tickets, fixtures, tags, promotion |
| See and steer everything from a laptop | `dashboard.py`: a local web server started by `run` (or `serve`), bound to localhost, reached through an SSH tunnel |

### 5.5 The skill model (R16, R19, R20)

- A **skill** is a capability package (a document plus optional scripts) that a session loads. It may be
  written by the owner, by the harness, or generated by a model. It is global (harness `skills/`) or local
  (project `.claude/skills/`). It never invokes another skill.
- A **role** is an agent definition: system prompt, tools, model, effort, and the skills preloaded into
  it. Roles are global with local overrides.
- The **registry** (`registry.json`, regenerated by code from both scopes) records for each skill and
  role: id, scope, a capability summary in general terms, applicability tags (ticket kinds, data types,
  libraries, venues), a cost hint, and an outcome record from the journal (how often tickets using it
  passed first time). This is the "one that knows all the skills".
- The **librarian** step, run by the planner when cutting tickets and by the conductor when re-cutting,
  reads the registry and assigns `role` and `skills` to every ticket. Workers receive them preloaded.
  Assignments are journaled, so the registry's outcome record improves the next assignment.
- Skills and roles that only models read may take whatever form retrieves best (Section 11); each must
  still pass a fixture proving it loads and does what its registry entry says.
- User-facing entry points are few (the `bin/<cli>` verbs above, mirrored as slash skills for the
  interactive phases). Role-facing skills are as many as the workflow benefits from. Whether the interactive
  phases are one skill each or one skill with modes is OPEN-2.

## 6. The pipeline

### 6.1 Phases, artifacts, gates

| Phase | Input | Output | Gate to leave | Human needed |
|-------|-------|--------|---------------|--------------|
| P0 Intake | anything the human has | `INTAKE.md`, `GOAL.json` if a goal is stated | schema-complete (A); goal well-formed (A) | yes, short |
| P1 Absorb | references | records for all, skims for candidates, full dossiers for the promoted (Section 7) | coverage complete at each paper's level (A); depth spot-check on promoted items (B) | no |
| P2 Position | dossiers, intent, goal | `POSITION.md` (closest prior work, feasibility verdict, goal feasibility, three directions by radius), `CONTEXT.md`, `DECISIONS.md` | frontier of decisions empty (human, or decider after the switch) | until the switch |
| P3 Specify | decisions | `SPEC.md`: claims and anti-claims, methods, experiments per claim, baselines, data, metrics, success criteria, budgets, out of scope, risks, seams | spec lints clean (A); one independent review that every claim has an experiment and every experiment defends a claim (B) | one approval in `checkpoints` |
| P4 Plan | SPEC | `tickets/`, `graph.json`, with roles and skills assigned, decision tickets where choices remain | DAG; every ticket has a demo, machine checks, touch set, difficulty, context pack, role, skills (A) | one approval in `checkpoints` |
| P5 Execute | graph | closed tickets, code on main, results, findings, proposals | frontier empty and no jobs pending, or goal reached | only on decision tickets |
| P6 Verify | results, claims | claim verdicts; `done` promoted to `accepted`; kill argument survived or claims scoped down | every claim has a verdict (A: present; B: supported) | no |
| P7 Report (retired by spec decision 17: the reports render by code all the time) | journal, findings | `REPORT.md` with provenance on every claim, rendered at every wave that integrates a ticket | linter passes (A); the run-end gates | no |
| P8 Paper order | the outline, the sections, the reports | `research/paper/`: the paper's parts, each in its own file with the version it was last made in, and `PAPER.md` | the outline's order and placement, no inherited title, abstract, or caption (A); the builds' gates (B) | the order: the owner's, or the decider's in an autonomous run |

### 6.2 The autonomy switch (R5)

`harness.json` carries `autonomy: interactive | checkpoints | autonomous`; the human can raise it at any
moment by saying so in the grill or with `switch --autonomy`. Effects:

- `interactive`: the human answers every round, approves the spec and the graph, answers every decision
  ticket, and is asked on every `needs_human` result.
- `checkpoints`: the human approves the spec and the graph, answers decision tickets; waves run alone.
- `autonomous`: the decider resolves every open question, every decision ticket not marked `human_only`,
  and every parked proposal. It runs at `--effort max`, reads the decision log, POSITION.md, GOAL.json and
  the dossier indexes, and writes each decision with rationale, confidence, and `decided-by: decider`, so
  the owner can audit it in the morning and reverse it by filing a ticket. It never decides anything on
  the irreversible list (C7).

The switch is raised at any time and lowered only by stopping the conductor and editing `harness.json`.
This departs from the grilling philosophy the interview borrows from, which holds that an unanswered
interview yields the agent's opinion rather than the owner's; the departure is made safe by labeling
every decider decision as such and listing them first in the report.

### 6.3 The scope radius (R9)

`radius: strict | moderate | exploratory` bounds what the planner and the decider may add:
`strict` admits only tickets that trace to a spec claim; `moderate` adds follow-ups that directly probe a
claim's failure; `exploratory` adds new directions, capped per wave and gated on a novelty check.
POSITION.md always ranks three directions by distance from the intent.

### 6.4 The quantitative goal (R25)

`GOAL.json`: `{metric, direction, target, dataset_or_split, baseline: {value, source}, budget:
{gpu_hours, wallclock, usage_windows}, stop_when: goal_reached | graph_empty}`. Intake rejects a goal
that is not measurable by a script on an artifact the harness can produce. P2's feasibility memo says
whether the target looks reachable with the stated data and compute, and proposes a revised target when
it does not. During P5 every result that reports the metric updates `progress` in the journal; the report
shows the trajectory; stall detection is measured against the goal, not only against closed tickets. In
goal-driven mode the planner keeps proposing experiments inside the radius until the goal is reached or
the budget is spent, keeping a change only when it improves the metric on the held-out split named in the
goal (the keep-if-better loop). A goal can be set at intake or added later with `intake --goal`.

### 6.5 "Does this make sense?" (R9)

Before any decision is asked, P2 produces a feasibility verdict from a fresh critic that has read only
the dossiers, INTAKE.md and GOAL.json: is it already done (closest prior work table with verified
citations), is it feasible with the stated compute and data, what would a hostile reviewer say, which of
three reformulations is strongest. The decider consumes it in autonomous mode; otherwise it is the first
thing shown to the human.

### 6.6 Decision tickets (R24)

A `decision` ticket carries a question, the options the planner sees, its recommended answer, the
evidence, and `blocking: subgraph | all`. While it is open, the conductor does not launch anything blocked
by it (or anything at all when `blocking: all`); unrelated branches and hardware jobs continue. The owner
is notified (desktop notification, and the ticket appears at the top of `status` and REPORT.md). The owner
answers with `answer <id> "..."`, by editing the ticket file, or in an interactive session; the answer is
journaled as a decision with `decided-by: human`. The recurrent tick notices the answer and relaunches
the conductor if it is not running. The planner creates decision tickets whenever a choice is genuinely
open; in `autonomous` mode the decider answers them unless `human_only` is set. The owner can mark at
intake which classes of decision are always `human_only` (for example, anything that changes the goal or
the data).

## 7. Reference absorption, lazily (R10, R23)

### 7.1 Dossiers and consultants, not resident experts

A long-lived expert process is expensive on a subscription and drifts. The machine-native equivalent is
a **dossier**: a persistent, structured, provenance-carrying record built by forced full coverage, plus
an on-demand **consultant** that answers questions from the dossier (and from the source when the
dossier is silent) and appends every answer back to it. Knowledge persists; the expert is instantiated
in milliseconds whenever needed. Paper and code get separate dossiers and share the consultant role.

### 7.2 Levels, and when a paper is promoted

Reading is the most token-intensive phase, so depth is earned:

- **L0 record**: metadata, abstract, verified identifiers, a knowledge-base node. Every reference found
  or given gets this, at near-zero cost.
- **L1 skim**: title, abstract, introduction, conclusion, figure captions, and the results table headers,
  into a short structured summary with a relation-to-intent line and a "would deserve L2 if" line. Given
  to every candidate the scout or the intake flags. Small fixed budget per paper.
- **L2 full dossier**: forced coverage (7.3). Given only when a paper is promoted: named primary at
  intake; cited by a spec claim, a baseline, or a method the harness will implement; named in a ticket's
  context pack; a consultant question that L1 cannot answer; or the planner or decider promotes it.
  A **code dossier** is built only for L2 papers with code, and only when a ticket will use that code.

Promotions and demotions are journaled with the trigger. The absorb budget in `harness.json` caps L2
work per phase; when it is exhausted, promotions queue and the report says which papers were not read
in full and why.

### 7.3 Forcing full reading at L2

1. **Acquire the exact source**: LaTeX source for arXiv papers (exact equations, figures as files,
   labels), otherwise the PDF converted to markdown with images extracted; for code, a clone at a pinned
   commit.
2. **Build the inventory mechanically**: sections, numbered equations, figures, tables, algorithms,
   theorems, appendices; for code: modules, public symbols, entry points, configs, tests, scripts, data
   requirements.
3. **Read per chunk with an obligation list**: each reader receives one chunk and its inventory items and
   returns one schema-validated entry per item (locator, kind, content in exact form, importance, relation
   to intent). Figures go to a reader with the image and caption: what it shows, whether it supports the
   claim it is cited for, anything odd.
4. **Merge in code, synthesize from entries**: the dossier's prose sections (method, claims, results,
   assumptions, limitations, flaws found, reusable ideas, open questions, relation to intent) are written
   from entries, never from the raw paper, so every sentence carries a locator.
5. **Audit coverage in code**: inventory items without an entry fail the gate (A); a critic spot-checks
   depth on the most important items and on every flaw claimed (B).

Code dossiers add **verified recipes**: install into a fresh environment, run the smallest test or example,
record the log; `verified: true` only if it ran. The API map notes per module what is good, bad, risky,
reusable, and how to call the pieces that matter for reproduction and benchmarking.

### 7.4 The consultant protocol

`roles/consultant`: read-only tools, context = one dossier and its source path. Input: one question.
Output: an answer with locators, a confidence, and "not in source" when that is true. Side effect: code
appends the exchange to `refs/<slug>/qa_log.md`; high-value answers are folded into the dossier at the next
absorb pass; a question the dossier cannot answer at L1 triggers promotion (7.2).

### 7.5 The project knowledge base

`research/kb/` holds nodes (papers, ideas, experiments, claims) and typed edges (`extends`,
`contradicts`, `tested_by`, `supports`, `refutes`, `uses`, `depends_on`) in `edges.jsonl`, with a
regenerated `query_pack.md` capped in size for injection into planning and ideation. Dossiers hold depth;
the knowledge base holds relations. Content is never duplicated between them.

## 8. Tickets (R6, R7, R19)

### 8.1 Kinds

`dossier`, `lit`, `code`, `docs`, `experiment`, `analysis`, `figure`, `writing`, `review`, `decision`,
`harness` (a change to the harness, Section 12). Every kind is a tracer bullet: when it closes, something
is demoable or a question is answered.

### 8.2 Schema (frontmatter of `tickets/NN-slug.md`, mirrored in `graph.json`)

```yaml
id: 17
title: Ablate the attention term on dataset B
kind: experiment
difficulty: 3                 # 1..5, Section 8.4
status: open                  # open | running | done | accepted | failed | blocked | needs_human | parked
blocked_by: [12, 14]
blocking: null                # decision tickets only: subgraph | all
human_only: false             # decision tickets only
touches: [experiments/ablation_b/, results/ablation_b/]     # write scope, enforced by hook
resources: {gpu: 1, cpu: 8, ram_gb: 32, wallclock_minutes: 90}
role: experimenter
skills: [sweep-runner, metrics-b]          # assigned by the librarian from the registry
inputs: [research/SPEC.md#claim-2, results/baseline_b/summary.json]
outputs: [results/ablation_b/summary.json, research/findings.jsonl#entry]
acceptance:
  machine: ["python scripts/check_seeds.py results/ablation_b --min 3", "test -f results/ablation_b/summary.json"]
  quality: ["Does the ablation isolate the attention term and nothing else?"]
goal_metric: {reports: auroc_b, expected_direction: down}   # when a goal exists
budget: {max_turns: 150, max_minutes: 120}
context_pack: [research/SPEC.md, research/refs/foo2025/dossier.md#method, research/findings.jsonl#12]
origin: SPEC.md#claim-2
proposed_by: planner          # planner | worker:9 | decider | human | evolve
demo: "A table with three seeds showing the effect of removing the term on dataset B."
```

The **touch set** is the conflict mechanism: two open tickets whose touch sets intersect never run at the
same time, and the hook makes a worker unable to write outside it. A worker that needs to write elsewhere
returns `blocked` with the path, and the planner re-cuts the ticket.

### 8.3 Acceptance criteria

`machine` criteria are commands with exit codes, run in the worktree before integration and on main
after it. `quality` criteria are questions answered under C6. A criterion that already passes at the base
commit is a plan-time lint error.

### 8.4 Difficulty to model and effort (RECOMMENDED defaults, in `policy.json`)

| Difficulty | Signals | Model | Effort | Budget | Extra |
|-----------:|---------|-------|--------|--------|-------|
| 1 | mechanical, one file, fully machine-checkable | sonnet | low | small | none |
| 2 | routine change, known pattern, few files | sonnet | medium | small | none |
| 3 | new code path or experiment, numerical care | opus | high | medium | independent code review |
| 4 | design judgment, several modules, ambiguous acceptance | fable | xhigh | large | independent review of the result |
| 5 | research-critical: the claim depends on it | fable | max | large | independent review mandatory; `accepted` only after it |

Escalation on failure: resume the same session once with the failure output; then one tier up; then the
planner splits the ticket; then `needs_human`. Outcomes feed back: a kind that fails twice at a tier raises
the planner's default for that kind, and the registry's outcome record for the skills involved.

### 8.5 Tracker (RECOMMENDED)

Local files plus `graph.json` are the source of truth: atomic, private, no API limits, diffable, and the
conductor never waits on a network. GitHub Issues with native blocked-by links are an optional one-way
mirror written by code, for visibility.

## 9. The conductor (R2, R3, R6, R21, R22)

### 9.1 Loop

```
load graph.json, journal.jsonl, policy, harness.json (budgets, reservations), GOAL.json
replay the journal (resume is the same code path as start)
loop:
  poll jobs/*.json           -> experiment/analysis tickets done when jobs exited 0 and outputs exist; OOM -> retry smaller
  read answers               -> open decision tickets answered? journal the decision, unblock the subgraph
  admit proposals            -> radius, dedup, wave cap, valid blocked_by; else park
  goal check                 -> if stop_when == goal_reached and progress >= target: finish
  frontier = open tickets whose blockers are done or accepted, not blocked by an open decision ticket
  runnable = frontier minus touch-set conflicts with running tickets minus tickets whose resources are unavailable
  if the usage window is closed: launch nothing that needs a model; do subscription-free work only
  while runnable and worker slots free and window budget not exhausted:
      t = pick(runnable)     # critical path first, then goal relevance, then difficulty, then id
      allocate resources (GPU ids, cores) if the ticket needs them for a job
      worktree = git worktree add -b ticket/<id> .worktrees/<id> origin/main
      launch worker(t) (9.2); journal "launched"
  for each finished worker:
      validate result against result.json   (invalid -> resume the session with the error, once)
      run machine acceptance in the worktree (fail -> resume with the output, once; then escalate 8.4)
      integrate: rebase onto main, rerun machine acceptance, fast-forward main   (conflict -> integrator role)
      ledger: findings entry, status done, journal "done", remove worktree
      quality criteria -> queue a Type-B verdict; pass -> accepted
      proposals -> proposal queue; decision tickets requested by the worker -> created
  stall check: two waves without a closed ticket, a new finding, or goal progress -> replan ticket, or stop-and-report in strict radius
  if frontier empty and nothing running and no jobs pending: P6, P7, exit
  on a usage-limit error: journal "paused" with the reset time; keep polling jobs; sleep until reset; continue
```

### 9.2 Launching a worker

The conductor assembles one prompt from the ticket, the context pack (file contents, sized to the range in
which the model still reasons well), the role's protocol, and the result schema, then runs (shape in
Appendix B):

```
claude -p "<prompt>" \
  --agents '{"worker": {"description": "...", "prompt": "<role system prompt>", "model": "<by difficulty>",
             "tools": [...allowlist...], "maxTurns": <by budget>, "skills": [<assigned skills>]}}' --agent worker \
  --effort <by difficulty> --permission-mode dontAsk \
  --settings '<hooks: touch-set guard, command guard, stop guard>' \
  --output-format json --json-schema "$(cat schemas/result.json)" \
  --fallback-model sonnet
```

The worker protocol: read the ticket and restate it; work at the declared seams test-first when the kind
is `code`; run single checks as it goes and the full machine acceptance at the end; commit on the ticket
branch; return the structured result. It never closes the ticket, never merges, never edits the ledger.
Workers are stateless between tickets; knowledge arrives through the context pack, the assigned skills, or
the consultant.

### 9.3 Experiments and analyses on the workstation (R21)

`resources.py` detects GPUs (ids, memory), CPU cores, RAM, and disk; keeps a reservation for the
interactive session and any process the owner lists in `harness.json`; and hands out slots. An
`experiment` or `analysis` worker prepares configurations and launches jobs through the resources module
as detached processes (a user-level service manager or an equivalent that survives the worker's exit),
each pinned to its assigned GPU ids and cores, with logs and expected outputs recorded in `jobs/<id>.json`.
The worker returns `status: running`; no session waits. Sweeps over seeds, parameters, or datasets are
job arrays that fill the free slots; running several at once is the intended use. The tick and the
conductor poll job files, retry out-of-memory failures with a smaller footprint, mark the ticket done when
jobs exit 0 and outputs parse, and unblock the dependent `analysis` ticket. Large artifacts stay outside
git with a manifest of hashes.

### 9.4 Result schema (abbreviated)

```json
{"ticket_id": 17, "status": "done|running|failed|blocked|needs_human",
 "summary": "...", "outputs_written": ["..."], "commands_run": ["..."],
 "checks": {"pytest": "pass", "seeds>=3": "pass"},
 "findings": [{"text": "...", "provenance": "results/ablation_b/summary.json#L4"}],
 "goal_progress": {"metric": "auroc_b", "value": 0.83},
 "proposals": [{"title": "...", "kind": "experiment", "why": "...", "blocked_by": [17], "radius": "moderate"}],
 "decision_requests": [{"question": "...", "options": ["..."], "recommended": "...", "blocking": "subgraph"}],
 "touched_outside_declared": [], "blocked_on": null, "cost": {"turns": 61, "minutes": 34}}
```

### 9.5 Proposals

Workers, verifiers, and the critic may propose tickets. Code admits a proposal when it is inside the
radius, not a duplicate (mechanical comparison first, a cheap model judgment when close), under the
per-wave cap, and its blockers exist. Otherwise it is parked and listed in REPORT.md; the decider reviews
parked proposals at the end of each wave in autonomous mode.

### 9.6 Usage windows and the recurrent tick (R22)

Two mechanisms, so that neither is a single point of failure:

- **The conductor's own pause.** On a usage-limit error it stops launching model work, lets running
  workers finish, journals the pause with the reset time named in the error (or the next window boundary),
  keeps polling hardware jobs, and resumes at the reset.
- **The tick.** A recurrent job installed by `init` under the user's service manager or cron (every 15 to
  30 minutes; the five-hour window is the longest it ever needs to wait). It reads the active project
  pointer and: exits if a conductor is alive and healthy; polls jobs, runs machine checks, renders REPORT.md
  and sends notifications regardless of the window; and relaunches `run --resume` when work remains and the
  window has reset, or when a decision ticket was answered. If the weekly cap is hit, hardware jobs and
  subscription-free work continue and model work queues until the reset. If the subscription lapses
  entirely, nothing breaks: state waits in the ledger.

`policy.json` sets `max_parallel_workers` (start at 2 or 3 and measure), a per-window worker budget, and
quiet hours. Cheap tickets are preferred when a window is nearly spent, and subscription-free work
(hardware jobs, machine checks, index builds, report rendering) is scheduled first when it is closed.

### 9.7 Resume, stall, termination

Resume is start: the journal is the state. A worker that died mid-ticket is resumed with its session id
when it exists, else relaunched. Two waves without progress trigger a replan ticket (the planner reads the
journal and the failures) or, in strict radius, a stop-and-report. The run ends when the frontier is empty
and no jobs are pending, or when the goal is reached under `stop_when: goal_reached`; then P6 and P7 run.

### 9.8 Notifications and answers

The tick and the conductor send a desktop notification on: a decision ticket opened, `needs_human`, a
pause on usage limits, a goal reached, a run finished. `status` prints the frontier, running tickets and
jobs, open decisions, window state, goal progress, and the last events. `answer <id>` records a decision.

### 9.9 The dashboard (R29)

`run` starts a local web server (and `serve` starts it alone, for reading a project while nothing runs;
the tick keeps it alive between relaunches). It prints its address, `http://127.0.0.1:<port>`, and from a
laptop it is reached with one tunnel: `ssh -L <port>:127.0.0.1:<port> <workstation>`.

**Tabs.** One per project in `projects.json`, the active one marked. Inactive projects are read-only
views of their ledgers with a "make active" control, which calls `switch`.

**Views per project.**
- Overview: phase, autonomy, radius, goal progress, usage-window state, hardware slots in use, running
  workers and jobs, the last journal events.
- Graph: the ticket DAG rendered with status colors, the frontier highlighted, and a page per ticket
  (frontmatter, context pack, result, findings, session and job logs).
- Decisions: open decision tickets with their options, evidence, and an answer form; the decision log,
  decider decisions listed first.
- Outputs: an index of `results/`, `findings`, figures, dossiers, `REPORT.md`, `paper/`, and the
  documentation site, every file downloadable, directories zipped on the fly. Markdown and images render
  inline; large artifacts stream.
- Logs: the journal tail, worker session logs, job logs, live through polling.
- Intake and feedback: drop references, PDFs, or data pointers into the intake; write feedback that lands
  in `research/feedback/` for the evolve loop.

**Actions.** Answer a decision, raise autonomy, pause or resume the conductor, switch project, cancel or
re-run a ticket, file feedback, promote a skill, start the paper phase. Every action calls the same
functions the CLI uses; the dashboard is a client of the ledger and the conductor, never a second writer
(C3). Nothing in it runs a shell.

**Implementation (RECOMMENDED, OPEN-20).** The standard library's threaded HTTP server with a small
router, JSON endpoints that read the ledger, and a static single-page application in vanilla JavaScript
with polling every few seconds. No framework, no build step (C5's standard-library rule holds). Server-sent
events replace polling only if polling proves insufficient.

**Exposure (RECOMMENDED, OPEN-21).** Bound to `127.0.0.1` by default and reached through an SSH tunnel;
when the owner asks for a wider bind, a random token in the URL is required, and the action set stays
limited to the list above.

## 10. Roles (R8)

Roles are functions with contracts, not personas. There is no PI and no student. Each role has a fixed
input, a fixed output schema, a default tier, preloaded skills, and a rule about whether it may judge.

| Role | Purpose | Implemented as | Input | Output | May judge quality? |
|------|---------|----------------|-------|--------|--------------------|
| Conductor | what runs, when, whether it is done (A) | code | graph, journal, policy | launches, merges, ledger | A only |
| Resource manager | slots, jobs, polling, retries | code | hardware, jobs/ | job states | A only |
| Tick | relaunch after windows, answers, jobs | code (recurrent) | active project | relaunches, notifications | no |
| Intake | normalize the human's material and goal | interactive skill | anything | INTAKE.md, GOAL.json | no |
| Reader | one chunk or figure against an obligation list | `absorb.js` agents | chunk + inventory slice | entries | no |
| Synthesizer | dossier prose from entries | one agent | entries | dossier sections | no |
| Coverage auditor | inventory versus entries | code, then a critic for depth | inventory, entries | pass/fail, missing | A; depth B |
| Consultant | one question from one dossier | `roles/consultant` | dossier + question | answer with locators | no |
| Scout | literature and fact searches, citation existence | `scout.py` + agents | claim or question | verified sources, L0 records | no |
| Interviewer | tiered rounds | grill skill | design tree | rounds, DECISIONS entries | no |
| Decider | resolve open decisions after the switch | `claude -p --effort max` | decision log, memos, goal | decisions with rationale | decisions, not quality |
| Planner | spec to graph; re-cut on failure; decision tickets | one session, high tier | SPEC, kb query pack, journal | tickets, graph.json | no |
| Librarian | assign roles and skills to tickets | planner step over the registry | registry, ticket | role, skills per ticket | no |
| Worker | one ticket in one fresh context | `claude -p` in a worktree | ticket + context pack + skills | result.json | self-checks only (A) |
| Integrator | rebase conflicts | fresh session | branch, main | merged branch | no |
| Verifier | quality criteria, claim support, kill argument | `gates.py` backends | artifact paths | verdict JSON | yes, and only this role |
| Figure designer | candidates from the plot index, drafts, final figures | role + `figures.py` | results, plot index | ranked candidates, figures | no |
| Documentarian | package documentation | role + `docs.py` | code, API, examples | docs site, completeness report | no |
| Writer | report and paper text under C8 | role + `provenance.py` | findings, kb, guidelines | REPORT.md, paper/ | no |
| Evolver | feedback into harness changes | `evolve.py` + a session | feedback, journal, fixtures | change records, harness tickets | no |
| Ledger | the only writer of shared state | code | results, verdicts | findings, statuses, REPORT | no |

Why this instead of a lab: a lab hierarchy allocates scarce human attention and trains people. Neither
applies. What a machine needs is that the judge is never the author (C6), that state never lives in
anyone's head (C3), and that breadth is cheap while verdicts are expensive and rare.

## 11. Representation and memory (R11, R20)

**The requirement is fidelity and retrieval, not readability.** Two rules follow:

1. Human-facing artifacts (INTAKE, DECISIONS, POSITION, SPEC, decision tickets, REPORT, paper) are plain
   markdown a person can read.
2. Internal artifacts (skills for roles, role prompts, dossier entries, indexes, memories, context packs,
   inter-agent results) may take whatever form measures best on a benchmark of real consultant questions
   and ticket outcomes, provided each is tool-verifiable (a schema, a fixture) and regenerable from its
   sources. Not human-readable is allowed; unaudited is not.

**RECOMMENDED starting format**: typed records with schemas and stable ids; every fact with a locator
(file, line, page, section, equation label, figure id, commit); exact forms preserved (LaTeX for
equations, tables as CSV or JSON, figures as files plus a description, code as code); context packs
assembled by code per ticket. Reason: current models are strongest on natural language and code, and the
losses seen in practice come from summaries without pointers, state kept in conversation, and retrieval
that misses, not from English. Alternatives (compressed notations, model-authored skills in their own
form, an embedding index built with a local model) are admitted through the evolve loop when they win on
the benchmark. The benchmark itself is built from `qa_log.md` questions and journaled ticket outcomes, so it
grows with use.

Rejected as the medium of record: chat-style agent-to-agent conversation (unstructured, no provenance)
and a vector store as the source of truth (opaque; acceptable only as an index).

## 12. Self-modification: the evolve loop (R13, R14, R16, R20)

The harness is itself a project with a ledger, so improving it uses the same machinery.

- **Feedback intake.** The owner writes feedback in a session (`evolve "the planner cut tickets that
  were too big; the figure captions overclaim"`), or drops files in `research/feedback/`. The evolver also
  runs a retrospective after every run over the journal: failures, escalations, stalls, rework, tokens
  spent per closed ticket, skills with poor outcome records.
- **Change records.** Each item becomes a change record (`schemas/change.json`): observed behavior with
  journal evidence, desired behavior, candidate mechanisms (prompt, skill, role, policy, hook, code), scope
  (local or global), risk, and the fixture that will prove it.
- **Execution.** Change records become `harness` tickets and run through the conductor. Local scope edits
  the project's `.claude/skills`, `.claude/agents`, and `harness.json` overrides; global scope edits the
  harness repository on a branch. A local change is applied to the current project immediately and used
  from the next wave.
- **Tests.** The conductor and the resources module have unit tests with a fake worker and fake jobs.
  Prompts, roles, and skills have fixtures: recorded inputs and expected structured outputs or verdicts from
  past runs. A change must not regress fixtures; the case that motivated the feedback becomes a new fixture.
  Model-authored skills pass a fixture proving they load and do what their registry entry says.
- **Versioning.** The harness repository is tagged on every global change; a project pins a tag in
  `harness.json`; `upgrade` moves a project forward with a changelog; rollback is a pin. Global changes are
  on the irreversible list by default (C7), so in autonomous mode they are proposed in REPORT.md, not applied.
- **Promotion.** `promote <skill|role|policy>` copies a local artifact into the harness with its fixtures.
  The evolver recommends promotion when a local skill has a good outcome record over several tickets; the
  decision is the owner's.

## 13. Figures, documentation, paper (R18, R26, R27, R28)

### 13.1 The plot index and the figure role

`figures/plot_index.json` is built once by crawling python-graph-gallery.com, r-graph-gallery.com, and
the Altair documentation into a catalog: chart family (distribution, correlation, ranking, part of a
whole, evolution, flow, map, network, multi-dimensional), chart type, the data shape it needs, when to
use it and when not, library implementations with snippet locations, gallery links, and known pitfalls. It
is refreshed through the evolve loop. The figure role, for each result: classify the data shape; take
candidates from the index; render quick drafts; have a critic rank them (B) against the claim the figure
must carry; let the human or the decider pick; apply the house style; run mechanical checks (fonts
embedded, colorblind-safe palette, journal widths, resolution) (A); and pass one Type-B honesty check
("does the figure assert something the data does not"). The existing `paper-figures` skill is the
inspiration for the honesty discipline and the verification loop, reviewed critically (3.4).

### 13.2 Documentation (R28)

Every `code` ticket that adds public API is followed by a `docs` ticket (a planner rule). The
documentarian builds a documentation site with a settled structure (tutorials, how-to guides, reference,
explanation), API reference generated from docstrings, executed examples, a figure gallery, and the
configuration for Read the Docs. Machine checks: every public symbol documented and present in the
reference, every example runs, the build is warning-free, links resolve (A). One independent read for
clarity and completeness against the package's purpose (B). Theme and layout are chosen once per project
and recorded in `harness.json`.

### 13.3 The paper on request (R26)

Revised by spec decision 17 (ticket 115): the paper is made only on an explicit paper order, from the outline and
the sections, under no venue; a compilation typesets it under one venue's guidelines. What follows is revision 2's
text.

`paper --venue <name>` after the report, or `paper` alone and the decider picks the best-fitting venue
from the guidelines repository. `guidelines/<venue>/` holds, per venue: format limits, required structure,
reporting checklists, reference style, figure specifications, submission steps, the source URLs and the
date they were checked. It starts with the major venues in the owner's fields (Nature family, Cell family,
PNAS, PLOS, eLife, Bioinformatics, Genome Biology, NeurIPS, ICML, ICLR) and grows through the evolve loop.
The writer drafts from findings and the knowledge base under C8; the provenance linter runs on every
build; figures come from 13.1; a kill argument and an independent review gate the draft; the owner reviews
the result. Nothing is submitted by the harness.

### 13.4 The claim-provenance linter (R18, C8)

Reports and papers use a small markup: every claim sentence ends with one or more provenance tags of the
form `{res:<run-id>/<artifact>#<locator>}` or `{ref:<slug>#<locator>}`. The linter (A) classifies
sentences (claim, definition, transition, method description) with a cheap model call cached per sentence,
requires a tag on every claim, checks that each tag resolves to an artifact in `results/` or a verified
reference in `kb/`, and fails the build otherwise. A verifier (B) samples tagged claims and checks that the
artifact or locator supports the sentence. Tags render as citations or supplementary references in the
final document.

## 14. Deliberately not built

- No model in the scheduling loop; no "orchestrator agent" deciding what to do next.
- No skill that calls a skill. Phases call steps through the conductor or a Workflow script.
- No dependence on the owner's existing skills, on any plugin at unattended runtime, or on an external
  model. Plugins may be used in interactive phases at the owner's choice.
- No long-lived expert processes; dossiers plus consultants.
- No shared documents edited by models; results are structured and the ledger writes.
- No wall-clock loops around verdict-bearing steps; cadence only waits on the external world (jobs,
  downloads, window resets, human answers).
- No shared state between projects; promotion is the only crossing.
- No mirror trees for other CLIs in the first version; the worker launcher is one backend behind a small
  interface.
- No submission of anything anywhere; the harness stops at a reviewed draft.
- No GUI beyond the local dashboard, which is a client of the same functions; `status` and REPORT.md
  remain the views that work without it.

## 15. Open decisions for the first session

- **OPEN-1 Execution engine.** External conductor over `claude -p` (recommended: survives session death,
  cron-able, per-ticket model and effort, pacing, real worktrees, hardware jobs) versus a Workflow script as
  the outer loop (cannot sleep, wait on jobs, or survive the session). Workflow scripts inside phases only.
- **OPEN-2 Interactive entry points.** One skill per interactive phase (intake, grill, plan, evolve,
  paper) versus one skill with modes. Recommended: one per phase; they are small and independently
  testable.
- **OPEN-3 Concurrency across projects.** One active project and one conductor (recommended) versus a
  global scheduler serving several projects under one usage budget.
- **OPEN-4 Language.** Python standard library (recommended) versus Node.
- **OPEN-5 Worker permission model.** `dontAsk` plus allowlist plus hooks (recommended) versus
  `bypassPermissions` inside a container. Containers later for experiment jobs if isolation is needed.
- **OPEN-6 Verifier backends and order.** Fresh session on a different Claude model, then optional
  external model, then human (recommended). Confirm whether a different Claude model is enough
  independence for `accepted`, or whether research-critical claims require the external backend when the
  owner has one configured.
- **OPEN-7 Default autonomy and the irreversible list.** Recommended default `checkpoints`; irreversible
  = delete data, force-push, push to shared branches, exceed the compute or usage budget, spend money, change
  the goal or the data, change the harness globally.
- **OPEN-8 Parallelism and budgets.** Start with `max_parallel_workers: 2`, hardware slots from
  detection minus the reservation, and measure a night.
- **OPEN-9 Name.** The CLI and skill prefix. The owner's choice.
- **OPEN-10 What "done" means.** REPORT.md always; paper only on request (recommended).
- **OPEN-11 Internal representation.** Structured records first, alternatives through the evolve loop
  when they win on the benchmark (recommended), versus designing a compressed notation up front.
- **OPEN-12 Difficulty ownership.** Planner assigns with a rubric and the conductor adjusts from
  outcomes (recommended) versus human assigns.
- **OPEN-13 Proposal caps.** Per wave: `strict` 0, `moderate` 3, `exploratory` 6 (recommended start).
- **OPEN-14 Artifacts.** Results outside git with a hash manifest (recommended) versus git-lfs.
- **OPEN-15 Job runner.** A user-level service manager (survives everything, resource control) versus
  detached processes with a session leader. Recommended: the service manager where available, the
  detached process as fallback.
- **OPEN-16 Reading budgets.** Default L1 budget per paper and L2 budget per phase; which triggers
  promote automatically and which ask (recommended: all listed in 7.2 promote automatically inside the
  budget; beyond it, a decision ticket).
- **OPEN-17 Fixtures for model behavior.** How strict a "regression" is for a prompt change when outputs
  are not deterministic (recommended: structural checks on the schema-validated output plus a Type-B
  verdict on a small fixed sample).
- **OPEN-18 Plot index sources and refresh.** The two galleries and Altair as seeds (given); how often to
  refresh and whether to add Seaborn and Plotnine documentation (recommended: yes, both).
- **OPEN-19 Guidelines seed list.** The venues in 13.3 (recommended start); whether preprint servers
  get entries (recommended: yes, bioRxiv and arXiv).
- **OPEN-20 Dashboard implementation.** Standard-library HTTP server plus a vanilla single-page app
  with polling (recommended: no build step, no dependency, easy to keep alive from the tick) versus a
  web framework with websockets.
- **OPEN-21 Dashboard exposure.** Localhost plus SSH tunnel (recommended) versus binding to the LAN with
  a token; never without one.

## 16. Delivery plan (tracer bullets)

| M | Name | Demo when done |
|---|------|----------------|
| M0 | Skeleton | `init` lays out a project; the conductor runs one trivial ticket through `claude -p` in a worktree with `dontAsk`, validates the structured result, runs a machine check, fast-forwards main, closes the ticket, journals it. Unattended, one command. |
| M1 | Frontier and windows | A five-ticket graph with two independent branches and one touch-set conflict runs with two workers; the conflict serializes; the hook blocks an out-of-scope write; a killed conductor resumes from the journal; a simulated usage-limit error pauses; the tick relaunches after the reset. A read-only dashboard at a local address shows the tabs, the frontier, running tickets, and the journal tail. |
| M2 | Hardware | `experiment` and `analysis` tickets launch detached jobs on assigned GPUs and cores; a sweep fills free slots; an OOM is retried smaller; results and findings land in the ledger; the interactive session's reservation is respected. |
| M3 | Dossiers | Ten references get L0 records; four get L1 skims; one primary paper with code is promoted to L2: inventory extracted, every item covered, figures described, recipe verified by running it; three consultant questions answered with locators; one question triggers a promotion. |
| M4 | Front door | From a vague intent plus references and a goal: intake, position memo with feasibility, tiered grill with facts looked up, a decision ticket that pauses a branch and is answered from the dashboard and from the command line, the switch flipped mid-way, the decider resolving the rest with rationale, a spec, and a graph with roles and skills assigned from the registry. |
| M5 | Overnight and report | A toy project runs end to end overnight across a window boundary: proposals admitted under `moderate`, a stall replan, verification with `done` and `accepted`, goal progress tracked, REPORT.md with every claim tagged and the linter passing, a notification in the morning. The outputs index and the downloads work through an SSH tunnel from another machine. |
| M6 | Evolve | Feedback on M5 ("tickets too big", "captions overclaim"), filed from the dashboard, becomes change records, harness tickets, fixtures, a local skill used in the next wave, and one promotion to the harness with a tag; the project is upgraded and rolled back once. |
| M7 | Figures, docs, paper | The plot index is built; a result gets ranked candidates and a final figure that passes the checks; the package gets a documentation site that passes completeness checks; `paper --venue` produces a draft under the guidelines with the linter and the kill argument passing. |

Suggested first session: `/wayfinder` with Section 18 as the destination. The map's first frontier is
OPEN-1 to OPEN-6; prototype tickets for the `claude -p` launch with `--agents` and `skills`, the touch-set
hook, the detached job runner, and the tick are the cheapest ways to clear fog.

## 17. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Usage windows exhausted by parallel workers | pacing policy, small parallelism, cheap tickets first, pause on limit, the tick relaunches after reset, subscription-free work when closed |
| Runaway ticket generation | radius, per-wave caps, dedup, parked proposals reviewed in the report |
| Self-acquittal | C6: Type-B verdicts only from the verifier; `done` is not `accepted` |
| Skimmed references where depth mattered | promotion triggers in 7.2; consultant questions that fail at L1 promote; the report lists unread promotions |
| Reading everything and burning the window | lazy levels with budgets; L2 only when promoted |
| Git hazards from parallel sessions | conductor-owned worktrees branched from `origin/main`; serialized integration; no shared stash use |
| Merge conflicts | touch sets enforced by hook; integrator role; conflicting tickets never run together |
| Stale or duplicated state | one ledger writer; no duplication between dossiers and the knowledge base; the journal as truth |
| Hardware contention with the owner's own work | reservations in `harness.json`; slots from live detection; jobs pinned to assigned devices |
| Long experiments blocking agents | detached jobs polled by code; no session waits |
| Permission prompts stalling the night | `dontAsk` plus allowlist, tested on M0 before any overnight run |
| Decision tickets starving a run | notifications; `status` shows them first; only the dependent subgraph waits |
| A bad decider call at 3 a.m. | rationale and confidence on every decision, reversible by a ticket, irreversible actions human-gated |
| Self-modification breaking the harness | fixtures, tags, pins, rollback; global changes proposed not applied in autonomous mode |
| Cross-project leakage | project-local state, explicit promotion, explicit dossier import with provenance |
| Claims without support in a report | the provenance linter (A) and sampled support checks (B) |
| Context degradation in long interactive phases | phase boundaries; DECISIONS.md written as decisions land; handoff files when moving sessions |
| Dashboard reachable by others on a network | localhost bind by default; SSH tunnel; a token when bound wider; actions limited to the ledger's own functions; no shell |

## 18. Paste-ready prompt for the first session

```
/wayfinder

Destination: a harness (name to be chosen) that turns a research intent of any specificity, optionally
with a quantitative goal, into a finished report (references absorbed to the depth they deserve,
positioned idea, spec, ticket graph, implemented and documented code, experiments run on this
workstation's GPUs and CPUs, verified results, every claim traced to a result or a reference), running
only on my Claude Code subscription across usage windows, with deterministic code deciding what runs and
when, and models deciding only content. It pauses on decision tickets I answer, continues to a paper for a
chosen journal on request, and improves itself from my feedback through tested, versioned changes. It
serves a local dashboard (a tab per project, an outputs index with downloads, decision answers and
controls) that I reach from my laptop through a tunnel to the workstation.

Read BRIEF.md in this directory first. Its DECIDED items are settled: runtime is the Claude Code CLI only
(claude -p sessions, Workflow scripts, hooks; no Agent SDK, no API keys, external reviewers optional);
control flow is code; state is files under research/ and project-local; skills compose in code and never
call each other, unlimited in number, global or local, registered so a librarian can assign them to
tickets; build from scratch with my existing skills as inspiration only (paper-figures the strongest, read
critically); Type-A gates judged by code, Type-B by an independent session or me; unattended workers run
with dontAsk, an allowlist, and hooks; irreversible actions stay human-gated; every claim in a report or
paper traces to data or a reference; the machine's GPUs and CPUs are used in parallel; a recurrent job
relaunches after usage windows; self-modification is local first and promoted by me; the dashboard is a
client of the same functions, bound to localhost.

Chart the map from the OPEN decisions in BRIEF.md Section 15, in that order, with the recommended answers
as defaults. Look facts up (my installed CLI flags, the Workflow reference, the Pocock plugin docs, my
paper-figures skill) instead of asking me. Fog to expect: the exact claude -p launch with --agents and
skills, the hook shape, the detached job runner, the tick, the dossier inventory for non-arXiv PDFs, the
fixture format for model behavior, the dashboard's polling versus server-sent events. The map is done when M0 to M7 in Section 16 can be written as
tracer-bullet tickets.
```

## Appendix A: schemas to write first

`ticket.json` (8.2), `result.json` (9.4), `dossier.json` (meta, level, inventory, entries with locators,
claims, method, results, limitations, flaws_found, reusable_ideas, relation_to_intent, open_questions,
coverage), `code_dossier.json` (meta, inventory, install_recipe with verified flag and log,
reproduce_recipe, api_map, quality, reusable, pitfalls, how_to_benchmark), `decision.json` (question,
options, answer, rationale, confidence, decided_by, reversible, timestamp), `proposal.json` (9.5),
`goal.json` (6.4), `change.json` (12), `registry_entry.json` (5.5), and the journal event (`ts`, `event`,
`ticket`, `session_id`, `job`, `payload`).

## Appendix B: worker launch, concretely

```bash
git -C "$PROJECT" worktree add -b "ticket/$ID" ".worktrees/$ID" origin/main
cd "$PROJECT/.worktrees/$ID"
TICKET_TOUCHES="experiments/ablation_b/:results/ablation_b/" \
claude -p "$(cat "$RUN/prompt.md")" \
  --agents "$(cat "$RUN/agent.json")" --agent worker \
  --effort high --permission-mode dontAsk \
  --settings "$HARNESS/hooks/worker-settings.json" \
  --output-format json --json-schema "$(cat "$HARNESS/schemas/result.json")" \
  --fallback-model sonnet \
  > "$RUN/result.json"
```

`agent.json` carries the role's description and system prompt, the model, the tool allowlist, `maxTurns`,
and the assigned `skills`. `worker-settings.json` registers `touch_set_guard.sh` on `PreToolUse` for
`Write|Edit` (reads `TICKET_TOUCHES`, exits 2 with a message on a path outside it), `command_guard.sh` on
`PreToolUse` for `Bash` (denies `rm -rf`, `git push`, `git reset --hard`, and the irreversible list), and
`stop_guard.sh` on `Stop` (blocks the stop when the machine acceptance has not been run). The field that
carries the structured object in the JSON envelope, the allowlist pattern syntax, and whether `skills`
in `--agents` resolves local project skills are the first things to confirm on M0.

## Appendix C: sources consulted

- ARIS: https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep (clone at HEAD f1bd907,
  2026-09-11: `AGENT_GUIDE.md`, `skills/shared-references/`, README headings, skill inventory).
- Matt Pocock's skills: the installed plugin 1.2.3 docs, https://github.com/mattpocock/skills (issue #493
  on worktree-based implement), https://github.com/mattpocock/sandcastle.
- The owner's `~/.claude/skills/paper-figures` (inspiration for 13.1) and the other twelve skills there
  (inspiration only, per R17).
- Claude Code 2.1.268 `--help`; the Workflow authoring reference; official docs on headless mode,
  subagents, hooks, worktrees, effort, memory, usage limits, and the Agent SDK authentication policy.
- Plot references named by the owner: https://python-graph-gallery.com/, https://r-graph-gallery.com/,
  https://altair-viz.github.io/.

## Appendix D: vocabulary (short)

On the question whether a glossary matters: only if these words are used verbatim in schemas, prompts,
and code, so that a ticket, a role, and a person mean the same thing by "frontier" or "accepted". The
list is kept to the words the harness itself uses; if a word stops appearing in the code, delete it here.

- **Ticket**: a tracer-bullet unit of work with a kind, difficulty, blockers, touch set, acceptance,
  role, skills, and context pack. **Decision ticket**: a question to the human (or the decider) that pauses
  its subgraph.
- **Touch set**: the paths a ticket may write, enforced by a hook. **Frontier**: open tickets whose
  blockers are done or accepted. **Wave**: one pass of the conductor loop.
- **Type-A gate**: machine-checkable; code judges. **Type-B gate**: a quality verdict; the verifier
  judges, never the author. **Done** versus **accepted**: machine checks passed versus quality verdict passed.
- **Dossier**: the structured record of one reference at level L0, L1, or L2. **Consultant**: the
  on-demand agent that answers from one dossier. **Promotion**: raising a paper's level, or moving a local
  skill into the harness.
- **Autonomy**: `interactive`, `checkpoints`, `autonomous`. **Radius**: `strict`, `moderate`,
  `exploratory`. **Decider**: the max-effort session that resolves decisions after the switch.
- **Registry** and **librarian**: the index of skills and roles, and the step that assigns them.
- **Tick**: the recurrent job that relaunches work after windows and answers. **Evolve**: the loop that
  turns feedback into tested harness changes.
- **Dashboard**: the local web view of the ledger and the conductor, a client of the CLI functions,
  reached through a tunnel.
