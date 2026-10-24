# Objectives and goals

An **objective** is a question the research sets out to answer. It need not be the project's end: it can be the
question that has to be answered first. A project holds several, `O1` onward, in `research/objectives.json`, rendered
as `research/OBJECTIVES.md`. A **goal** is an objective with a **measure** (metric, direction, target, held-out split,
evaluation command, baseline): code checks it and keep-if-better optimizes toward it. Ids are never reused and an
objective is never deleted: it is answered, parked, dropped, or reframed (its successor named).

## Recording one

Say what you want answered: "I want to know whether the pairwise products help". The session records it and reads
back `O3`. For a goal, give the measure as a file and a sample artifact: the measure is recorded only once its command
printed the metric on the sample; otherwise the objective is kept without one and you are told why. A run cannot go
`autonomous` while no objective is open.

## Changing one

- **On your word**: "O2 is answered: yes, by about 3 points", "park O4", "drop O5", "reframe O1 as ...", "reopen O4".
  These apply directly.
- **Proposed by the work**: a ticket's result or a verdict may carry an objective proposal (add, answer, park, drop,
  reframe, reopen) with its evidence. Whoever proposes never makes the change: a fresh verifier judges each one, and
  the upheld ones gather in one "Objective changes" decision, a batch you mark approve or decline (or say "approve
  all", "1: approve; 2: decline"). Only unstarted tickets serving solely an affected objective pause meanwhile.
  Proposals not upheld are listed under "Not pursued" in the account.
- **Set aside**: once all of a spec claim's objectives are closed, the claim is set aside (kept, no work planned)
  and comes back if one reopens. Unstarted tickets serving only closed objectives are parked.
- **Spec amendment**: an objective added or reframed after the spec was confirmed gets claims appended under new ids,
  never rewriting what was confirmed, and tickets cut for them alone.

Who approves:

- `interactive`: you; an amendment waits for your word.
- `checkpoints`: you, through the decision ticket; a "Confirm the amendment" ticket pauses only the new tickets.
- `autonomous`: the decider, which answers, parks, and drops (never an objective the stopping rule names), and adds,
  reframes, or reopens only once you took `objective` off the human-only classes, within the radius. What it may not
  take waits for you.

## Keep-if-better, the stopping rule, and budgets

**Keep-if-better** keeps a goal ticket's change only when its mean over the seeds beats that goal's best kept value
on the held-out split by more than one standard deviation (a measure's own `min_seeds` overrides the policy's); a
change it does not keep is discarded, its findings kept as negative results. A goal whose best kept value meets its
target is answered by code.

The **stopping rule** (`stop_when` in `harness.json`) ends a run for good: `objectives` (the default, no objective
open), a list of objective ids (those closed), or `frontier` (no work left). **Budgets** are `wallclock_hours`
(counted from the end of setup) and `gpu_hours` (each job's hours times its GPUs); spending one ends the run. Both
are setup's fifth question. After setup, changing the rule or raising a budget is on the irreversible list: the
session confirms it with a card, and the decider is refused both.

When the frontier empties while objectives the rule waits on are still open, one decision per objective offers
replan, answer it as it stands, park, or drop. Under `interactive` and `checkpoints` you answer while the run ends;
under `autonomous` the decider picks replan or answer.

## Verbs the session runs

`wayline objective add "<question>"` (with `--measure <file> --sample <artifact>` for a goal),
`wayline objective answer`, `wayline objective park`, `wayline objective drop`, `wayline objective reframe`,
`wayline objective reopen`, `wayline specify --amend <O>`, `wayline mark`, `wayline switch --stop-when <rule>`,
`wayline switch --budget <name>=<hours>`, and `wayline status` (each goal's best kept value, the rule, and the
budgets).
