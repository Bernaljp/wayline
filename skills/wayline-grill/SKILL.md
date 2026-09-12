---
name: wayline-grill
description: "The second half of phase P2 of a wayline run. Builds the design tree of open questions, asks the frontier of it in tiers with a recommended answer for each, lands every answer in research/DECISIONS.md and every settled term in research/CONTEXT.md, and is where the owner raises the autonomy switch. Use it after the position memo and before specify."
---

# The grill

The project's design is a tree of questions. Most of them cannot be asked yet, because their
answer depends on an answer that is not in yet. Your job is to ask the ones that can be asked,
all of them at once, and to keep asking until nothing is left that the spec would have to guess.

## The tier

A tier is the current frontier: every question whose prerequisites are settled. Ask that whole
frontier in one message, numbered, each question with a recommended answer and the reason for it.
The owner answers the numbers, in any order, in as much or as little detail as they like. Then you
recompute the frontier and ask the next tier.

Asking one question at a time is the failure mode this skill exists to prevent. It spends the
owner's attention on round trips instead of on decisions.

## Facts are looked up, decisions are asked

Before a question reaches the owner, decide which kind it is.

- A **fact** is anything the machine can answer: whether a tool is installed, what a dossier says,
  what the data actually contains, what a paper the scout resolved actually claims. Look it up.
  Run the command, read the dossier, ask the consultant, send the scout. A fact you asked the
  owner for is a question you should have answered yourself.
- A **decision** is a choice with no right answer the evidence settles: what counts as success,
  which baseline is the fair one, what the method is allowed to assume, what the paper will claim.
  Ask it, with your recommendation and your reasoning.

When you look a fact up, say what you found and what it rules out. That is often what makes the
next decision obvious.

## Where the answers go

Every answer lands in `research/DECISIONS.md` as one record: `question`, `answer`, `rationale`,
`decided-by`, `confidence`, `timestamp`. Every term the answers settle lands in
`research/CONTEXT.md` as it settles, so the spec, the tickets, and the report all use one
vocabulary. Neither file is rewritten wholesale; both grow.

An answer the owner gives that contradicts an earlier one is not an error to hide. Record the new
answer, name the record it supersedes, and say what downstream it changes.

## The autonomy switch

The owner raises autonomy by saying so, or with `wayline switch --autonomy autonomous`. When they
do, say plainly what changes: the decider resolves every open question and every decision ticket
that is not `human_only`, the report lists its decisions first, and nothing on the irreversible
list is ever decided without them. Lowering it again means stopping the conductor and editing
`harness.json`, which is deliberate: an autonomous run should not be switchable by a passing
remark.

`wayline grill` is the same phase from the command line. Both it and this skill's fixture arrive
with ticket 30.
