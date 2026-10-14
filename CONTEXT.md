# Wayline (the SpecDrivenResearch harness)

The vocabulary the harness's schemas, prompts, code, and tickets use verbatim, so a ticket, a role, and a person mean the same thing. Seeded from BRIEF.md Appendix D. If a word stops appearing in the code, delete it here.

## Language

**Ticket**:
A tracer-bullet unit of work with a kind, difficulty, blockers, touch set, acceptance, role, skills, and context pack.
_Avoid_: task, issue, story

**Decision ticket**:
A question to the human (or the decider) that pauses its subgraph until answered.
_Avoid_: blocker question, checkpoint

**Design tree**:
The questions the grill asks, each with the questions whose answers it waits on; a tier asks every open one whose prerequisites are settled.
_Avoid_: question list, interview

**Touch set**:
The paths a ticket may write, enforced by a hook.
_Avoid_: scope, write set

**Frontier**:
Open tickets whose blockers are done or accepted.
_Avoid_: ready queue, runnable set

**Launchable**:
The frontier minus the tickets that collide with running work, want resources that are not free, or need tools not installed.
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

**Kill argument**:
The two-thread Type-B gate on the general report or the paper: one verifier session writes the strongest rejection memo, a second adjudicates it point by point, and a fail scopes the claims down through a `writing` ticket.
_Avoid_: red team, devil's advocate, peer review

**Venue**:
A journal, conference, or preprint server with a `guidelines/<venue>/guidelines.json`, named by its slug; the paper is drafted and checked under one venue's guidelines and never submitted to it.
_Avoid_: journal (for the slug), target, outlet

**Section**:
One of the five parts of the paper kept as its own file from the project's start: Introduction, Results, Discussion, Methods, and References. Any of them may be empty for a while.
_Avoid_: chapter, part, paper section

**Passage**:
A piece of a section's text, from one claim to a paragraph, with its provenance and whoever contributed it; a later passage replaces it without deleting it.
_Avoid_: contribution (a paper's claimed advance), entry, snippet

**Inherited passage**:
A passage deconstructed from a project's own documents, such as an earlier manuscript; its claim stands unchecked until this project's evidence supports, narrows, or contradicts it, or the claim is found unverifiable.
_Avoid_: legacy text, imported text

**Unverifiable**:
The standing of an inherited claim the project tried to check and could not, such as when its data is gone or no rebuild of its code could run; it carries the reason, and it is kept apart from a claim not yet checked.
_Avoid_: unproven, failed, unchecked (a claim nobody has tried yet)

**Reproduction**:
Running a project's own inherited code, at the commit the project recorded and changed only so that it runs here, to check the inherited result it produced.
_Avoid_: replication, rerun

**Port**:
The inherited code's logic carried into another language or runtime, such as MATLAB into Octave or Python, so that an inherited result can be checked when its code cannot run as written; any change to the logic makes a reproduction a port.
_Avoid_: translation, rewrite

**Reimplementation**:
Code written from the inherited Methods to check an inherited result whose code is missing.
_Avoid_: rebuild (the owner's reply at setup that asks for a port or a reimplementation), clone

**Consolidation**:
One writer session's rewrite of a section's current passages into fewer, cleaner passages that keep their tags and replace them, made only when the owner asks.
_Avoid_: compilation (the paper's word), tidy, rewrite

**Finding**:
A Results passage a ticket returns, stating what this project's evidence shows, negative or not, with its provenance.
_Avoid_: observation, outcome

**Result**:
What the project found on one question: the current findings under one heading of the Results section, with their plots; the unit a report presents. A ticket's structured output is its ticket result.
_Avoid_: line of work, topic

**General report**:
The report on all the project's results, by objective and then by result, always current.
_Avoid_: final report, summary, REPORT (alone)

**Drawing**:
One plotter session's exploration of one result: its plots and tables, each explained, and a synthesis across them; accepting it starts a new current report.
_Avoid_: exploration run, plotting pass

**Plot**:
One view of a result's data in a current report, explained but never captioned, kept under its id across drawings until it is retired.
_Avoid_: figure (made only at the paper order), graph

**Current report**:
One result's report at full depth, every useful plot explained; a new one starts each time that result's plots are drawn again.
_Avoid_: line-of-work report, snapshot

**Earlier report**:
A current report that a newer one of the same result has replaced; kept and never edited.
_Avoid_: old report, archive

**Outline**:
The proposed shape of the paper, built by code at any point and changed by the owner: each section's headings in order, what each draws on, and what goes to the supplement or is cut. A document's own list of headings is its headings, not an outline.
_Avoid_: table of contents, plan (the ticket graph's word), structure (a venue's required structure), skeleton

**Document**:
One of a project's own writings handed to the harness, such as an earlier manuscript, a critique, or a cover letter, kept as given beside a converted text; published work, the project's own preprints included, is a reference.
_Avoid_: material (intake's word for any loose argument), attachment, source

**Critique**:
A document that judges the work from outside, such as a referee report, an editor's letter, or a collaborator's list of required experiments; its points become concerns.
_Avoid_: review (a ticket kind and the Type-B gate's word), feedback (the evolve loop's input)

**Concern**:
A point the work must answer, such as an objection to a claim or a required experiment: one a critique raises, kept verbatim with every critique that raised it, or an objection of the position memo's hostile review that the owner accepted at the grill, kept with the memo as its source; it stays open until it is answered or declined with a reason.
_Avoid_: comment (a margin note, which can carry one), issue, objection, review point

**Done**:
Machine checks passed on a ticket.
_Avoid_: complete, finished

**Accepted**:
The quality verdict passed on a done ticket.
_Avoid_: approved, merged

**Reference**:
A published work the project can cite, resolved by the scout and held in a dossier.
_Avoid_: citation, source

**Dossier**:
The structured record of one reference at level L0, L1, or L2.
_Avoid_: summary, notes, expert

**Consultant**:
The on-demand agent that answers one question from one dossier or one document.
_Avoid_: expert, oracle

**Surveyor**:
The session a `lit` ticket runs on: it searches the literature through the scout and writes the Introduction's state of the art from the abstracts it read.
_Avoid_: reader (the L1 skim's role), scout (the code that resolves and searches), librarian (the planner step)

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

**Rung**:
One step a ticket can be launched at: a model, an effort, and a session budget.
_Avoid_: tier (the grill's word; `tier_up` stays the name of the escalation step that climbs one rung), level (a difficulty level names a rung; it is not one)

**Rung ladder**:
The ordered list of rungs, cheapest first, that a tier up climbs and pacing steps down.
_Avoid_: ladder alone (the escalation chain and the footprint ladder are other things)

**The cap**:
The rule that ticket work never runs above `high` effort; roles and verdicts are not bound by it.
_Avoid_: effort limit, ceiling

**Ladder consent**:
The owner's standing answer on whether an autonomous run may change the rung ladder alone: `auto` or `ask`.
_Avoid_: ladder policy, permission

**Evolve**:
The loop that turns owner feedback into tested, versioned harness changes.
_Avoid_: self-improvement, learning

**Change record**:
One change the evolve loop proposes: what was observed with its journal evidence, what is desired, the mechanism, local or global, the risk, and the fixture that will prove it.
_Avoid_: patch, improvement, fix

**Harness ticket**:
The ticket of kind `harness` filed for one change record; a local one is integrated into the project, a global one works on `evolve/<id>` of the harness repository and waits for the owner.
_Avoid_: meta ticket, self ticket

**Evolver**:
The max-effort, read-only session that writes change records from the pending feedback and the retrospective.
_Avoid_: improver, optimizer

**Retrospective**:
What code computes from the journal after a run ended, filed as feedback for the evolver.
_Avoid_: post-mortem, review

**Dashboard**:
The local web view of the ledger and the conductor, a client of the CLI functions, reached through a tunnel, where the owner also talks with the project.
_Avoid_: UI, app, GUI

**Conversation**:
The owner's talk with a project, in the dashboard's chat or in a Claude Code session there, which records what the owner says through the harness's verbs and keeps nothing only in itself.
_Avoid_: front door, console, thread

**Ledger**:
The files under a project's `research/`, written only by code from structured results.
_Avoid_: state, database, memory

**Journal**:
The append-only event log the conductor replays to resume and the account is built from.
_Avoid_: log, history

**Account**:
What wayline did in a project, rendered by code from the journal and the ledger: what was decided for the owner, what waits on the owner, and each run with its end, its gates, and what it spent; never the research.
_Avoid_: run report, status report, log, audit trail

**Refusal**:
A guided change request the figure role declines because the figure would then assert something false; it carries the nearest honest alternative, and only the owner can override it.
_Avoid_: rejection, veto

**Figure**:
A publication figure the figure role makes at the paper order, from chosen plots or from nothing, with a caption.
_Avoid_: plot

**Plotter**:
The role that makes drawings.
_Avoid_: figure designer (the figure role's session that drafts and finishes figures)

**Objective**:
A question the research sets out to answer, often general and not always the project's end: it can be the question that has to be answered before the work goes on. A project holds several, and results can reframe them.
_Avoid_: aim, target, research question (the spec's framing of what it answers)

**Goal**:
An objective with a measure: code checks it, keep-if-better optimizes toward it, and it is reached when the best kept value meets its target, if it has one. It can be the whole aim of a project or of a phase.
_Avoid_: target (a measure's field), KPI

**Measure**:
The metric, direction, target, held-out split, and command that let code read a goal's progress; an objective has at most one.
_Avoid_: metric alone (the spec's metric is a definition with its script)

**Keep-if-better**:
The rule that keeps a goal ticket's change only when its mean over the seeds beats its goal's best kept value on the held-out split by more than one standard deviation; a change it does not keep is discarded.
_Avoid_: hill climbing, accept-if-improved

**Discarded**:
A goal ticket's change keep-if-better did not keep: done, not integrated, its branch kept, its findings negative results.
_Avoid_: rejected, reverted

**Stopping rule**:
The condition set at setup under which a run ends for good, so the tick no longer relaunches it: no objective open, the objectives it names closed, or no work left. The owner's stop, a strict stall, and a spent budget end a run besides it.
_Avoid_: stop condition, termination criterion

**Budget**:
A project's limit on wall-clock hours or GPU hours, set at setup and counted from its end; spending one ends the run, and only the owner raises it.
_Avoid_: allowance, quota

**Job**:
A detached hardware process (experiment or analysis) polled by code; no session waits on it.
_Avoid_: run, task, process

**Tool**:
A program the harness installed, the owner provided, or the machine already had, recorded on the machine with its absolute path, version, and environment, and called only through that record; a library a project's code imports is a package, not a tool.
_Avoid_: dependency, software

**Environment**:
Where a project's tools and packages live and its jobs run: the shared tools on the machine, one conda prefix, a venv, or a container. The owner may move a project between them at any time, and code rebuilds the same versions there from the locks.
_Avoid_: container (one kind of environment), setup (the start of a run)
