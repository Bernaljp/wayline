---
name: wayline-plan
description: "Phase P4 of a wayline run. Cuts research/SPEC.md into the ticket graph: one file per ticket under research/tickets/, graph.json beside them, a role and skills assigned to every ticket from registry.json, and a decision ticket wherever a choice is still open. Use it after specify, and again whenever the graph has to be re-cut."
---

# Plan

You turn the spec into work the conductor can run unattended. A ticket is a tracer bullet: small
enough that one session closes it, complete enough that closing it moves the project.

You do not cut the tickets yourself. `wayline plan` does: it launches the planner on the spec, the
query pack, the registry, and the journal, has the librarian assign a role and skills to every
ticket, runs the plan-time checks, writes `research/tickets/NN-slug.md` and `research/graph.json`
through the ledger, and opens a decision ticket for every choice the planner reports open. Your
work is to run it, read what it cut back to the owner, and record the owner's word on it.

Run every `wayline` command from the project root with `--project .`. Without it a verb acts on the
machine's active project, which another terminal may have switched to a different one.

## Before you cut

`wayline plan` refuses to cut a first graph until the spec is confirmed (`wayline specify` says
`confirmed`, and the journal's phase is P4). Read `research/SPEC.md` first, so you can tell the
owner what the graph should contain: one or more tickets per experiment, the scripts the metrics
name that do not exist yet, the analysis that files the findings, the writing that reports them.
Then run `wayline plan --project .`.

## What it writes

`research/tickets/NN-slug.md` per ticket, and `graph.json` beside them. Every ticket carries:

- `demo`: what a human would watch to believe the ticket is done.
- `acceptance.machine`: the commands code runs to judge it. They must fail at the base commit; a
  criterion that already passes measures nothing.
- `acceptance.quality`: the one question the verifier answers, when the ticket needs a verdict.
- `touches`: the paths the ticket may write, enforced by a hook. Two tickets that write one path
  are never launched into the same wave, so a touch set that is wider than the work costs
  parallelism.
- `difficulty` 1 to 5 by the rubric, which sets the model, the effort, and the budget.
- `context_pack`: the paths and locators the worker is given, smallest first.
- `role` and `skills`, from the librarian.
- `blocked_by`, and `blocking` on a decision ticket.

`research/plan.json` keeps the plan as the planner returned it, with the ids it became.

## The librarian

Do not guess at a role or a skill, and never edit one into a ticket file. `registry.json` is the
index of every skill and role in both scopes, with a capability summary, applicability tags, a
cost hint, and an outcome record computed from the journal; `wayline plan` rebuilds it before every
launch. The librarian step reads it and assigns per ticket: the role whose kinds cover the ticket's
kind, and the skills whose tags match the ticket's kind, data types, libraries, and venue. An entry
marked `assignable: false` is never assigned, whatever its summary promises. Every assignment is
journaled as `assigned`.

When no role covers a ticket's kind, the check fails and the planner is told; a plan that still
needs that kind stops with the failure. Tell the owner: a missing role is a harness ticket, not a
rounding error.

## The checks a plan has to pass

The graph is a DAG. Every ticket has a demo, machine criteria, a touch set, a difficulty, a context
pack, a role, and skills. No machine criterion passes at the base commit (the verb runs each one in
a checkout of `main`). Every `code` ticket that adds public API is followed by a `docs` ticket.
Every touch set is a path under the project and never `research/`. A choice the spec left open is
a decision ticket, with `blocking` set to the subgraph it pauses or to everything, and `human_only`
when it changes the goal or the data. A plan that fails is returned to the planner once with the
failures; a second failure ends the run with nothing written, and the verb prints the failures.

## Reading it back to the owner

`wayline plan` prints every ticket it cut: the id, the kind, the difficulty, the role, the title,
and what it waits on; `wayline status --project .` shows the frontier. Read the graph back in a few
lines: how many tickets, which run first, which decision tickets wait for an answer, what the
planner noted it could not cut. Quote the demos when the owner asks what a ticket does; never
paraphrase a criterion.

Then the confirmation, by the project's autonomy:

- Under `checkpoints` the verb opened a decision ticket "Confirm the graph" with `blocking: all`,
  so the conductor launches nothing until it is answered. The owner answers it with
  `wayline answer <id> confirm --project .`, or `wayline answer <id> "revise: <what to change>"
  --project .`, or in the dashboard. A revise parks the graph at once; run `wayline plan --project .`
  again and it is cut again with the change, and asked about again.
- Under `interactive` no ticket is opened: ask the owner in this conversation, and record the word
  with `wayline plan confirm --project .` or `wayline plan revise "<what to change>" --project .`.
- Under `autonomous` the decider answered the ticket already; say what it decided.

A confirmation journals the phase to P5, and the verb prints `next: wayline run`.

## Cutting again

- `wayline plan --replan --project .` re-cuts every `open` or `blocked` ticket after a stall: the
  planner reads the journal's failures and the graph as it stands, the superseded tickets are
  parked (journaled `ticket_cancelled` by the planner), and the new ones are checked and confirmed
  like a first plan. The conductor calls it at a stall; the owner may call it by hand.
- `wayline plan --split <id> --project .` replaces one failed ticket with smaller ones that inherit
  its blockers and its dependents; the escalation ladder calls it after a tier up failed.

## How you work

- Never write under `research/`, and never edit a ticket file or `graph.json` yourself: the verb
  does, and a hand-written ticket skips the librarian and the checks.
- Read the spec, the query pack, and the journal before you say what the graph should be. The
  journal says what already failed, and a plan that repeats it wastes a window.
- Prefer more, smaller tickets over fewer large ones, up to the point where a ticket no longer
  demos anything on its own; say so when the planner cut too coarse, and send it back with
  `revise`.
- Difficulty is the planner's to set by the rubric; the conductor raises it from outcomes and a
  human pins it with `pinned_difficulty`. Do not ask for it to be inflated to buy turns.
