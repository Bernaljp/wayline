---
name: wayline-intake
description: "Phase P0 of a wayline run. Turns whatever the owner has (a paragraph, a reference list, PDFs, data pointers, a plan, a repository) into research/INTAKE.md and the autonomy, radius, fallback consent, ladder consent, budgets, and human-only classes in harness.json; information only, so each objective, and each goal with its measure, is recorded with wayline objective add. Use it at the start of a project."
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

## What the owner hands over

Tell the owner to hand over anything, in any form: a manuscript as `.docx`, `.tex`, or PDF, a
separate Methods or a supplement, a spreadsheet, a referee report or an editor's letter, a folder,
or a `.zip`. Nothing needs tidying first. Take references as bare identifiers (a DOI, an arXiv id,
an exact title), the owner's plan as the plan, and a collaborator's list of experiments as a
critique.

The project's own writing is a document; published work, the owner's own preprints included, is a
reference. Sort each document with the verb, as a command of its own:

```bash
wayline document add <file> --kind inherited|critique|other
```

- `inherited`: an earlier manuscript, a separate Methods, a supplement, a thesis chapter;
- `critique`: a referee report, an editor's letter with points, a collaborator's list of required
  experiments;
- `other`: anything else, kept and read only.

Ask the owner in one line only when the kind is unclear. A folder is sorted file by file and a
`.zip` is unpacked first: give `--kind` to a folder only when every file in it is of that kind, and
otherwise add the files one by one. A PDF of published work goes `--kind reference`: it joins the
references, and the absorb keeps it as that reference's source. Conversion is code: the verb
converts each file, keeps it under `research/documents/<id>/`, and lists it in
`research/DOCUMENTS.md` with what the conversion lost; read that index back and tell the owner. One
version per text is current, the newest in its source format: hand an older or a newer version over
the same way, and the verb records it as such.

Deconstruct each inherited document into the sections, and again after a newer version of it is
kept, which then comes in like a section edit:

```bash
wayline document deconstruct <id> [--place "<heading or locator>=<section>"]
```

Code cuts the text under Introduction, Results, Discussion, and Methods headings verbatim into
inherited passages, one per claim, each unchecked until this project's evidence answers it; the
title, abstract, captions, back matter, availability statements, and reference list are kept and
never deconstructed. Read the document's headings in `DOCUMENTS.md` first and place each heading the
fixed table does not map with `--place` (`introduction`, `results`, `discussion`, `methods`, or
`kept`); one you leave lands under Results as written and is listed for the owner. Then read the
passages of a separate Methods or supplement in the sections, and move each that reports or
interprets an outcome to where it belongs: `wayline document move <passage> results|discussion`.

## What the intake holds

`research/INTAKE.md` gets these sections, in this order, every one present even when it is short:

- **Intent**: what the owner wants to find out or build, in their words, tightened but not
  reinterpreted. A plan the owner wrote is quoted whole under it.
- **References**: one line per reference, as the owner gave it (a DOI, an arXiv id, a title, a
  URL, a PDF). The scout resolves them later; nothing here is invented.
- **Data**: what data exists, where it is, what is held out, and what may not leave the machine.
- **Code**: the repositories the work builds on (`code`, `--repo`); the verb pins each to its commit
  and copies nothing. The project's own clone, and only it, goes in as `clone` (`--clone`): it is
  absorbed into `code/` with its history, its uncommitted changes as the next commit, so the code
  repository is cut from `code/`. Ask which repository is the project's own; someone else's paper's
  code goes to `absorb --code` as a reference. Ask the code repository's one setup question beside it, as the spec's
  `code_repository`: its `shape` (`package`, the developed method and every model the work applies it
  to, callable from the package, a method with its own maintained package a pinned dependency; or
  `reproducibility`, scripts, helpers, and the environment alone), its `license` (the inherited one by
  default), and its remote: a new private GitHub repository by default, or `remote: owner/name` when the
  owner says wayline may take over their own repository (`confirm_public: true` once, if it is public).
  It is private until the owner says `visibility: public`, which is their word only.
- **Constraints**: deadlines, hardware, licences, methods that are off the table, and anything the
  owner said must not change.
- **Autonomy**: `interactive`, `checkpoints` (the default), or `autonomous`, and beside it the fallback
  consent `model_fallback`, which says what becomes of Fable work while Fable's weekly window is spent:
  `auto` falls back to Opus without asking, `ask` waits for the owner's answer, asked once per spent
  window by a human-only decision ticket, and `wait` waits for the reset. Ask it with the autonomy and
  the budgets. When the owner does not say, pass nothing: the project then records no consent and
  behaves as `ask`, except that under `autonomous` an ask nobody answers falls back after two hours.
- **Ladder consent**: `ladder_changes`, asked beside the autonomy and the fallback consent, with `ask`
  recommended. It says whether an autonomous run may change the rung ladder (`tiers` or `difficulty`) on
  its own: `auto` lets the decider approve such a change, `ask` makes it a human-only decision ticket of
  class `ladder` under every autonomy. When the owner does not say, pass nothing: the project then records
  no consent and behaves as `ask`.
- **Radius**: `strict`, `moderate` (the default), or `exploratory`.
- **Budgets**: GPU hours, wall clock hours, and the usage windows the run may spend.
- **Decisions that stay human-only**: the classes the decider never resolves. `objective` (which
  covers a goal's measure) and `data` are always there; the owner may add classes, and is told that
  each one added is a decision the run waits on under `autonomous`. When the project has critiques,
  `concern` is one to offer: named, every concern that needs sorting after setup waits for the owner
  rather than the decider.

What the owner wants answered is not a section: it is recorded as objectives (below).

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
  --clone ../analysis --repo ../baseline-models --constraint "no GPU before October" \
  --autonomy checkpoints --radius moderate --model-fallback ask --ladder-changes ask --gpu-hours 10 --wallclock-hours 48 \
  --human-only "baselines: which baselines the claims are compared against"
```

With the owner in the conversation, the same answers can go in as one JSON spec on stdin:

```bash
wayline intake --from - <<'EOF'
{"intent": "the owner's paragraph",
 "plan": "plan.md",
 "references": ["arXiv:1706.03762", "10.1038/s41592-019-0686-2", "papers/model.pdf"],
 "data": ["data/expression.csv", "split_b is held out and never leaves this machine"],
 "code": ["../baseline-models"],
 "clone": "../analysis",
 "code_repository": {"shape": "package", "license": "MIT"},
 "constraints": ["no GPU before October"],
 "autonomy": "checkpoints", "radius": "moderate", "model_fallback": "ask", "ladder_changes": "ask",
 "budgets": {"gpu_hours": 10, "wallclock_hours": 48},
 "human_only": ["baselines: which baselines the claims are compared against"]}
EOF
```

Leave out, or set to null, whatever the owner did not say; the verb writes "not stated" rather
than a guess, and keeps the project's current autonomy, radius, and fallback consent. Paths are relative to where you
run it. The verb prints what it wrote; read `research/INTAKE.md` back and tell the owner what it
says and what you assumed.

## Objectives and goals

The intake takes information only: it records no goal, and a spec that carries `goal`, `sample`, or
`rationale` is refused. What the owner wants answered is an objective, a question the research
sets out to answer; a goal is an objective with a measure that code checks. The conversation
records each one the owner states, in their words, with its own verb, as a command of its own:

```bash
wayline objective add "Do pairwise products raise held-out AUROC on the synthetic set?"
```

Only when the owner states a quantitative goal, give its measure in a file and an artifact to check
it on:

```bash
wayline objective add "Do pairwise products raise held-out AUROC?" --measure measure.json --sample <artifact>
```

```json
{"metric": "auroc", "direction": "up", "target": 0.9, "held_out_split": "split_b",
 "eval_command": "python eval.py --predictions {artifact}", "baseline": {"value": null, "source": null},
 "dataset_or_split": null, "min_seeds": null}
```

`direction` is `up` or `down`; `target` may be null (keep improving); a baseline number always
carries its source. The verb runs `eval_command` on the sample artifact (`{artifact}` is its path,
also in `WAYLINE_ARTIFACT`), and the command has to print the metric: a JSON object with the
metric's key, a line `auroc: 0.83`, or the number alone on the last line. A command that is
missing, that fails, or that prints no number records the objective without a measure and says
why: tell the owner the reason and what they would have to give for the goal to stand. An
objective has at most one measure; a second metric is a second objective. Read
`research/OBJECTIVES.md` back with each id. Which objectives the project takes, open or parked, the
grill's first tier settles with the owner.

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
