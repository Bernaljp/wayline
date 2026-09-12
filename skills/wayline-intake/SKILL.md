---
name: wayline-intake
description: "Phase P0 of a wayline run. Turns whatever the owner has (a paragraph, a reference list, PDFs, data pointers, a plan, a repository) into research/INTAKE.md and, when a quantitative goal is stated, research/GOAL.json. Use it at the start of a project, and whenever the owner wants to add or replace the goal."
---

# Intake

You are the front door. The owner hands you what they have, in whatever shape they have it, and
you hand back one normalized record the rest of the run reads: `research/INTAKE.md`, and
`research/GOAL.json` when a number is what they are after.

Take what is there. A paragraph is enough to start; so is a reference list, a directory of PDFs,
a pointer at a dataset, a half-written plan, or an existing repository. Ask only for what is
missing and cannot be inferred, and ask it once, in one batch.

## What INTAKE.md holds

These sections, in this order, every one present even when it is short:

- **Intent**: what the owner wants to find out or build, in their words, tightened but not
  reinterpreted.
- **References**: one line per reference, as the owner gave it (a DOI, an arXiv id, a title, a
  URL, a path). The scout resolves them later; nothing here is invented, and a reference you
  cannot read is listed with what you could not read about it.
- **Data**: what data exists, where it is, what is held out, and what is not allowed to leave the
  machine.
- **Constraints**: deadlines, hardware, licences, methods that are off the table, and anything the
  owner said must not change.
- **Autonomy**: `interactive`, `checkpoints`, or `autonomous`.
- **Radius**: `strict`, `moderate`, or `exploratory`.
- **Budgets**: GPU hours, wall clock, and the usage windows the run may spend.
- **Decisions that stay human-only**: the classes the decider never resolves. The default is every
  decision that changes the goal or changes the data; the owner may add to it and is told what
  adding means.

`autonomy`, `radius`, `budgets`, and the `human_only` classes are also recorded in the project's
`harness.json`, because that is the file the conductor rereads every wave. `INTAKE.md` is the
owner's copy of the same answers.

## What GOAL.json holds

Only when the owner states a quantitative goal:

```json
{"metric": "", "direction": "maximize | minimize", "target": 0, "dataset_or_split": "",
 "held_out_split": "", "eval_command": "", "baseline": {"value": 0, "source": ""},
 "budget": {"gpu_hours": 0, "wallclock": "", "usage_windows": 0}, "stop_when": ""}
```

A goal is only a goal when code can measure it. `eval_command` is a script the harness can run on
an artifact a ticket can produce, and intake runs it on a sample artifact before the goal is
written. A command that is missing, that fails, or that prints no number means no goal: say which
of the three it was, and what the owner would have to give you for the goal to stand. A rejected
goal is not a failed intake. Record the intent without it and the run proceeds without a number.

## How you work

- Read before you ask. A repository, a plan, or a PDF the owner pointed at usually answers half
  the sections.
- Never invent a reference, a dataset, a baseline number, or a metric. "Not stated" is an answer;
  a plausible-looking DOI is a fabrication.
- Quote the owner for the intent and the constraints. Paraphrase kills the detail that turns out
  to matter three phases later.
- Say what you assumed. An assumption in writing is one the owner can correct; one in your head
  becomes the run's.
- The vocabulary the project uses goes to `research/CONTEXT.md` as it settles, not here.

`wayline intake` is the same phase without a human in the loop, and `wayline intake --goal` adds
or replaces the goal later and journals it as a decision made by the human. Both arrive with
ticket 28, which also fills in this skill's fixture.
