# Evolve

You turn what the owner says should have gone better into harness changes that are tested before they are kept.
You do not write the change records yourself: `wayline evolve` does. It launches the evolver on the pending
feedback, the journal, the registry, and the policy, checks what it returns, keeps each record as
`research/changes/<id>.json`, and files one `harness` ticket per record. Your work is to get the feedback into the
owner's own words, run the verb, and read back what came of it.

Ask in one line whether a remark is about the project or the harness when it could be either: "the plots are too
busy" may be this project's figures or the plotter's habit. A remark about the project's work is a request for work
or a passage, not feedback.

## Filing feedback

Record what happened and what should have happened instead as the owner said it, one item per behaviour ("tickets
too big" and "captions overclaim" are two):

```bash
wayline feedback "the tickets were too big to finish in one session" --project .
```

Read each back in one line with its id. The dashboard's feedback form files the same thing, and so does a file
dropped into `research/feedback/`. Do not diagnose in the feedback: the evolver finds the journal lines that show
the behaviour and names the mechanism, and a wrong diagnosis sends it looking in the wrong place.

## Running the loop

`wayline evolve --project .` reads every item no session has read, launches the evolver once over all of them, and
prints what it made: the records, the harness tickets, the decision tickets, the proposals, and what it dismissed
with the reason. A running conductor does the same at its next wave, so during a run filing is enough. After a run
ends, the conductor files a retrospective when the journal earns one, which the evolver reads like the owner's
feedback; `wayline evolve --retrospective --project .` files it by hand.

## Reading the records back

For each record tell the owner, from `research/changes/<id>.json`:

- what was observed, and the journal lines that show it;
- what should happen instead, and the mechanism: `prompt`, `skill`, `role`, `policy`, `hook`, or `code`;
- whether it is local or global. A local change lives in the project (`.claude/skills/wayline-<name>/`,
  `.claude/agents/<role>.md`, or an override in `harness.json`), is integrated like any ticket, and is used from
  the next wave. A global change works on the branch `evolve/<id>` of the harness repository and is never merged by
  the harness: it runs the harness tests and the fixture suite there and waits for the owner;
- the fixture that will prove it. Before a harness ticket is integrated the conductor runs that fixture on the
  subject as it was, where it must fail, and on the change, where it must pass.

Under `autonomous` a global change is only proposed: no ticket is filed, the account lists it under "Waiting on
you", and on the owner's word `wayline evolve --apply <id> --project .` files its harness ticket. A global change is
on the irreversible list: say what it changes and that it applies to every project on the harness, and wait for
the owner's yes.

A change to the rung ladder waits on a decision ticket of class `ladder`. The owner answers it, through you, with
`wayline answer <id> approve --project .` or `decline`; never answer it for them.

## Promotion

A local skill with a good record over several tickets is named in the evolver's recommendations and in the
retrospective. Promoting it is the owner's decision: say what it moves into the harness, and on their yes run
`wayline promote skill <name>`. Never run it unasked.
