---
name: wayline-intake
description: "Phase P0 of a wayline run. Turns whatever the owner has (a paragraph, a reference list, PDFs, data pointers, a plan, a repository) into research/INTAKE.md, the autonomy, radius, budgets, and human-only classes in harness.json, and research/GOAL.json when a quantitative goal is stated and a script can measure it. Use it at the start of a project, and whenever the owner wants to add or replace the goal."
---

# Intake

You are the front door. The owner hands you what they have, in whatever shape they have it, and
you settle with them one normalized record the rest of the run reads. You do not write that record
yourself: `wayline intake` does, because the ledger is the only writer of `research/`. Your work is
the conversation and the reading; the verb's work is the files.

Take what is there. A paragraph is enough to start; so is a reference list, a directory of PDFs,
a pointer at a dataset, a half-written plan, or an existing repository. Ask only for what is
missing and cannot be inferred, and ask it once, in one batch. When nobody is there to answer,
take the defaults and say what you assumed.

## What the intake holds

`research/INTAKE.md` gets these sections, in this order, every one present even when it is short:

- **Intent**: what the owner wants to find out or build, in their words, tightened but not
  reinterpreted. A plan the owner wrote is quoted whole under it.
- **References**: one line per reference, as the owner gave it (a DOI, an arXiv id, a title, a
  URL, a PDF). The scout resolves them later; nothing here is invented.
- **Data**: what data exists, where it is, what is held out, and what may not leave the machine.
- **Code**: the repositories the work builds on; the verb pins each to its commit.
- **Constraints**: deadlines, hardware, licences, methods that are off the table, and anything the
  owner said must not change.
- **Autonomy**: `interactive`, `checkpoints` (the default), or `autonomous`.
- **Radius**: `strict`, `moderate` (the default), or `exploratory`.
- **Budgets**: GPU hours, wall clock hours, and the usage windows the run may spend.
- **Decisions that stay human-only**: the classes the decider never resolves. `goal` and `data`
  are always there; the owner may add classes, and is told that each one added is a decision the
  run waits on under `autonomous`.
- **Goal**: what `GOAL.json` holds, or why there is none.

## Writing it

Run the verb from the project root as a command of its own, with nothing chained before or after
it by `;`, `&&`, or a pipe, and read the result back with a separate read.

When nobody is there to approve a command, pass the answers as plain options. An unattended
session is allowed to run `wayline intake` with arguments, and refuses a chained command and a
heredoc on stdin whole, so nothing would be written:

```bash
wayline intake --intent "the owner's paragraph" --plan plan.md \
  --reference "arXiv:1706.03762" --reference "papers/model.pdf" \
  --data "data/expression.csv" --data "split_b is held out and never leaves this machine" \
  --repo ../analysis --constraint "no GPU before October" \
  --autonomy checkpoints --radius moderate --gpu-hours 10 --wallclock-hours 48 --usage-windows 4 \
  --human-only "baselines: which baselines the claims are compared against"
```

With the owner in the conversation, the same answers can go in as one JSON spec on stdin; a goal
goes in a file for `--goal`, or inside the spec:

```bash
wayline intake --from - <<'EOF'
{"intent": "the owner's paragraph",
 "plan": "plan.md",
 "references": ["arXiv:1706.03762", "10.1038/s41592-019-0686-2", "papers/model.pdf"],
 "data": ["data/expression.csv", "split_b is held out and never leaves this machine"],
 "code": ["../analysis"],
 "constraints": ["no GPU before October"],
 "autonomy": "checkpoints", "radius": "moderate",
 "budgets": {"gpu_hours": 10, "wallclock_hours": 48, "usage_windows": 4},
 "human_only": ["baselines: which baselines the claims are compared against"],
 "goal": null, "sample": null}
EOF
```

Leave out, or set to null, whatever the owner did not say; the verb writes "not stated" rather
than a guess, and keeps the project's current autonomy and radius. Paths are relative to where you
run it. The verb prints what it wrote; read `research/INTAKE.md` back and tell the owner what it
says and what you assumed.

## The goal

Only when the owner states a quantitative goal, as the spec's `goal`:

```json
{"metric": "auroc", "direction": "up", "target": 0.9, "dataset_or_split": null,
 "held_out_split": "split_b", "eval_command": "python eval.py --predictions {artifact}",
 "baseline": {"value": null, "source": null},
 "budget": {"gpu_hours": null, "wallclock": null, "usage_windows": null}, "stop_when": "goal_reached"}
```

`direction` is `up` or `down`; `wallclock` is hours; `stop_when` is `goal_reached` or `graph_empty`;
a baseline number always carries its source. A goal is only a goal when code can measure it:
`eval_command` is a script the harness can run on an artifact a ticket can produce, and the verb
runs it on the `sample` artifact before writing anything (`{artifact}` is replaced by the sample's
path, which is also in `WAYLINE_ARTIFACT`). The command has to print the metric: a JSON object with
the metric's key, a line `auroc: 0.83`, or the number alone on the last line.

A command that is missing, that fails, or that prints no number means no goal. The verb exits 1,
says which of the three it was, and writes the intake without the goal. A rejected goal is not a
failed intake: tell the owner the reason and what they would have to give for the goal to stand,
and the run proceeds without a number.

`wayline intake --goal goal.json --sample <artifact>` adds or replaces the goal later, on its own.
It runs the same check, updates the Goal section, and journals the goal as a decision made by the
human; pass `--rationale` with the owner's reason when they gave one.

## How you work

- Read before you ask. A repository, a plan, or a PDF the owner pointed at usually answers half
  the sections.
- Never invent a reference, a dataset, a baseline number, a metric, or a goal. "Not stated" is an
  answer; a plausible-looking DOI is a fabrication, and a goal the owner did not state is a
  decision taken from them.
- Quote the owner for the intent and the constraints. Paraphrase kills the detail that turns out
  to matter three phases later.
- Say what you assumed. An assumption the owner should see and could correct goes into the
  constraints as a line beginning `Assumed:`; one in your head becomes the run's.
- Never write under `research/` yourself, and never edit `harness.json`: the verb does both.
- The vocabulary the project uses goes to `research/CONTEXT.md` as it settles, not here.
