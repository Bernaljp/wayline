---
name: wayline-plan
description: "Phase P4 of a wayline run. Cuts research/SPEC.md into the ticket graph: one file per ticket under research/tickets/, graph.json beside them, a role and skills assigned to every ticket from registry.json, and a decision ticket wherever a choice is still open. Use it after specify, and again whenever the graph has to be re-cut."
---

# Plan

You turn the spec into work the conductor can run unattended. A ticket is a tracer bullet: small
enough that one session closes it, complete enough that closing it moves the project.

## What you write

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

## The librarian

Do not guess at a role or a skill. `registry.json` is the index of every skill and role in both
scopes, with a capability summary, applicability tags, a cost hint, and an outcome record computed
from the journal. The librarian step reads it and assigns per ticket: the role whose kinds cover
the ticket's kind, and the skills whose tags match the ticket's kind, data types, libraries, and
venue. An entry marked `assignable: false` is never assigned, whatever its summary promises. Every
assignment is journaled.

When no role covers a ticket's kind, say so in the plan rather than assigning a role that cannot do
the work. A missing role is a harness ticket, not a rounding error.

## The checks a plan has to pass

The graph is a DAG. Every ticket has a demo, machine criteria, a touch set, a difficulty, a context
pack, a role, and skills. No machine criterion passes at the base commit. Every `code` ticket that
adds public API is followed by a `docs` ticket. Every touch set is a path under the project. A
choice the spec left open is a decision ticket, with `blocking` set to the subgraph it pauses or to
everything, and `human_only` when it changes the goal or the data.

## How you work

- Read the spec, the query pack, and the journal before you cut anything. The journal says what
  already failed, and a plan that repeats it wastes a window.
- Cut for the frontier, not for the outline. Tickets that can run at the same time should not block
  each other because they were written in sequence.
- Prefer more, smaller tickets over fewer large ones, up to the point where a ticket no longer
  demos anything on its own.
- Difficulty is yours to set by the rubric; the conductor raises it from outcomes and a human pins
  it with `pinned_difficulty`. Do not inflate it to buy turns.

`wayline plan` is the same phase from the command line. The planner, its checks, and this skill's
fixture arrive with ticket 34.
