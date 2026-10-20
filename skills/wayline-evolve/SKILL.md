---
name: wayline-evolve
description: "The interactive half of the evolve loop of a wayline run. Takes what the owner says should have gone better, files it as feedback, runs the evolver over it, and reads back the change records, the harness tickets, and the fixtures that will prove them. Use it when the owner comments on how the harness behaved, and after a run to go through its retrospective."
---

# Evolve

You turn what the owner says should have gone better into harness changes that are tested before
they are kept. You do not write the change records yourself. `wayline evolve` does: it launches the
evolver on the pending feedback, the journal, the registry, and the policy, checks what it returns,
keeps each record as `research/changes/<id>.json`, and files one `harness` ticket per record. Your
work is to get the feedback into the owner's own words, run the verb, and read back what came of it.

Run every `wayline` command from the project root with `--project .`. Without it a verb acts on the
machine's active project, which another terminal may have switched to a different one.

## Filing feedback

Ask what happened and what should have happened instead, and file it as the owner said it:
`wayline feedback "<text>" --project .`. One item per behaviour; "tickets too big" and "captions
overclaim" are two items. The dashboard's feedback form files the same thing, and so does a file
dropped into `research/feedback/`. Each is journaled as `feedback` with its source.

Do not diagnose in the feedback. The evolver finds the journal lines that show the behaviour and
names the mechanism; feedback that arrives with a wrong diagnosis sends it looking in the wrong
place.

## Running the loop

`wayline evolve --project .` reads every item no session has read, launches the evolver once over
all of them, and prints what it made: the records, the harness tickets, the decision tickets, the
proposals, and what it dismissed with the reason. `wayline evolve "<text>"` files one more item
first. A running conductor does the same at its next wave, so during a run filing is enough.

After every run that ends, `wayline run` files a retrospective when the journal earns one
(failures, escalations, stalls, rework, turns per closed ticket, skills below the registry's median
first-time pass rate, quarantined fixtures) and the evolver reads it like the owner's feedback.
`wayline evolve --retrospective` files it by hand.

## Reading the records back

For each record tell the owner, from `research/changes/<id>.json`:

- what was observed, and the journal lines that show it;
- what should happen instead, and the mechanism: `prompt`, `skill`, `role`, `policy`, `hook`, `code`;
- whether it is local or global. A local change lives in the project (`.claude/skills/wayline-<name>/`,
  `.claude/agents/<role>.md`, or an override in `harness.json`), is integrated like any ticket, and
  is used from the next wave. A global change works on the branch `evolve/<id>` of the harness
  repository and is never merged by the harness: it runs the harness tests and the full fixture
  suite there, waits as `awaiting_owner`, and `wayline evolve` tags the harness once the owner has
  merged it. `wayline upgrade` then moves the project to the tag;
- the fixture that will prove it. Before a harness ticket is integrated the conductor runs that
  fixture on the subject as it was, where it must fail, and on the change, where it must pass. A
  fixture that passes on both proves nothing and fails the ticket.

Under autonomy `autonomous` a global change is only proposed: no ticket is filed, the account
(`research/ACCOUNT.md`) lists it under "Waiting on you", and `wayline evolve --apply <id>` files its
harness ticket when the owner says so.

A change to the rung ladder (a `policy` change whose keys include `tiers` or `difficulty`) is always
high risk and waits on a decision ticket of class `ladder`. The owner answers it with
`wayline answer <id> approve` or `decline`; under `autonomous` the decider may answer it only when
the ladder consent is `auto` (`wayline switch --ladder auto`). Do not answer it for the owner.

## Promotion

A local skill with a good record over several tickets is named in the evolver's recommendations
and in the retrospective. Promoting it is the owner's decision and the owner's command:
`wayline promote skill <name>`. Never run it unasked.
