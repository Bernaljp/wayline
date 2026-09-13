# Wayline (the SpecDrivenResearch harness)

The vocabulary the harness's schemas, prompts, code, and tickets use verbatim, so a ticket, a role, and a person mean the same thing. Seeded from BRIEF.md Appendix D. If a word stops appearing in the code, delete it here.

## Language

**Ticket**:
A tracer-bullet unit of work with a kind, difficulty, blockers, touch set, acceptance, role, skills, and context pack.
_Avoid_: task, issue, story

**Decision ticket**:
A question to the human (or the decider) that pauses its subgraph until answered.
_Avoid_: blocker question, checkpoint

**Touch set**:
The paths a ticket may write, enforced by a hook.
_Avoid_: scope, write set

**Frontier**:
Open tickets whose blockers are done or accepted.
_Avoid_: ready queue, runnable set

**Launchable**:
The frontier minus the tickets that collide with running work or want resources that are not free.
_Avoid_: eligible, schedulable

**Wave**:
One pass of the conductor loop.
_Avoid_: iteration, round

**Type-A gate**:
A machine-checkable condition; code judges it.
_Avoid_: hard check, lint

**Type-B gate**:
A quality verdict; a fresh verifier session judges it, never the session that wrote the work.
_Avoid_: review, soft check

**Done**:
Machine checks passed on a ticket.
_Avoid_: complete, finished

**Accepted**:
The quality verdict passed on a done ticket.
_Avoid_: approved, merged

**Dossier**:
The structured record of one reference at level L0, L1, or L2.
_Avoid_: summary, notes, expert

**Consultant**:
The on-demand agent that answers one question from one dossier.
_Avoid_: expert, oracle

**Promotion**:
Raising a paper's dossier level, or moving a local skill, role, or policy into the harness.
_Avoid_: upgrade (reserved for moving a project to a newer harness tag)

**Autonomy**:
The human-involvement setting: `interactive`, `checkpoints`, or `autonomous`.
_Avoid_: mode, level

**Radius**:
The scope bound on what the planner and decider may add: `strict`, `moderate`, or `exploratory`.
_Avoid_: scope, creativity

**Decider**:
The max-effort session that resolves open decisions after the autonomy switch.
_Avoid_: PI, orchestrator

**Registry**:
The generated index of skills and roles, global and local, with capability summaries and outcome records.
_Avoid_: catalog, manifest

**Librarian**:
The planner step that assigns a role and skills to every ticket from the registry.
_Avoid_: router, dispatcher

**Tick**:
The recurrent job that relaunches work after usage windows, answers, and jobs.
_Avoid_: cron job, watchdog, daemon

**Fable's weekly window**:
The weekly allowance of Fable usage, counted apart from the all-models week.
_Avoid_: Fable limit, Fable quota

**Fallback**:
Fable work launched on Opus while Fable's weekly window is spent; never the CLI's switch to another model on overload.
_Avoid_: downgrade, substitution

**Fallback consent**:
The owner's standing answer on fallback for a project: `auto`, `ask`, or `wait`.
_Avoid_: permission, fallback policy

**Evolve**:
The loop that turns owner feedback into tested, versioned harness changes.
_Avoid_: self-improvement, learning

**Dashboard**:
The local web view of the ledger and the conductor, a client of the CLI functions, reached through a tunnel.
_Avoid_: UI, app, GUI

**Ledger**:
The files under a project's `research/`, written only by code from structured results.
_Avoid_: state, database, memory

**Journal**:
The append-only event log the conductor replays to resume and the report is built from.
_Avoid_: log, history

**Job**:
A detached hardware process (experiment or analysis) polled by code; no session waits on it.
_Avoid_: run, task, process
