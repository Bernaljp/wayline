# Setup

Setup is one conversation, at every autonomy, from what the owner hands over to a confirmed plan: intake's
settings, the documents, the position memo, the grill, the stopping rule and budgets, specify, and the plan. It is
the only time an automated run asks the owner anything. Under `autonomous`, nothing about any of these is asked
after setup, so setup ends only when every question is answered, or left for later where this file says it may be
(the front matter alone).

You do not write the record: the verbs do, because the ledger is the only writer of `research/`. Your work is the
reading, the looking up, the asking, and turning what the owner says into the verbs. Run each command from the
project root with `--project .`, on its own, and read what it wrote back to the owner in one line with its id.

**How to ask.** Ask the ten setup questions below in their order. Head each one `Setup N/10: <what it settles>`,
give your recommended answer with its reason, and ask it as one question where this file says one: one message,
answered in one reply. A question with nothing to ask (no documents, no concerns, nothing missing) is said in one
line under its heading, so the owner sees it was not skipped. Never ask the next question before the owner's
answer to this one is recorded.

## Before the first question: what the owner hands over, and intake's settings

Read before you ask: a repository, a plan, or a PDF the owner pointed at usually answers half of what the intake
holds. Tell the owner to hand over anything, in any form: a manuscript as `.docx`, `.tex`, or PDF, a separate
Methods or a supplement, a spreadsheet, a referee report or an editor's letter, a folder, or a `.zip`. Nothing
needs tidying first. Take references as bare identifiers (a DOI, an arXiv id, an exact title), the owner's plan as
the plan, and a collaborator's list of experiments as a critique.

`wayline intake` writes `research/INTAKE.md` (intent, references, data, code, constraints, autonomy, radius, and
the human-only classes) and the settings in `harness.json`. It takes information only: an objective or a goal is
`wayline objective add`'s, and a spec carrying `goal` is refused. Ask, in one round with a recommendation each,
what the owner did not say and the material does not answer:

- **Autonomy**: `interactive`, `checkpoints` (the default), or `autonomous`.
- **Radius**: `strict`, `moderate` (the default), or `exploratory`.
- **The fallback consent** `model_fallback`, what becomes of Fable work while Fable's weekly window is spent: `auto`
  falls back to Opus without asking, `ask` waits for the owner's answer, `wait` waits for the reset. Not said, pass
  nothing: the project behaves as `ask`.
- **The ladder consent** `ladder_changes`, with `ask` recommended: whether an autonomous run may change the rung
  ladder on its own (`auto`) or a change is a human-only decision of class `ladder` (`ask`).
- **The human-only classes** `human_only`: the classes the decider never resolves. `objective` (which covers a
  goal's measure) and `data` are always there. The owner may name more, `objective` and `concern` among them: named,
  `concern` makes every concern that needs sorting after setup wait for the owner rather than the decider. Tell the
  owner that each class added is a decision a run waits on under `autonomous`. A class the owner states is recorded
  as stated, with no confirmation.

The budgets are not asked here: they are setup's fifth question. Ask which repository is the project's own: it
goes in as the clone (`--clone`) and is absorbed into `code/` with its history; a repository the work only builds
on goes in as code (`--repo`), pinned to its commit. The code repository's shape and remote are setup's seventh
question.

Then write it. With the owner in the conversation, the answers go in as one JSON spec on stdin:

```bash
wayline intake --from - --project . <<'EOF'
{"intent": "the owner's paragraph", "plan": "plan.md",
 "references": ["arXiv:1706.03762", "10.1038/s41592-019-0686-2", "papers/model.pdf"],
 "data": ["data/expression.csv", "split_b is held out and never leaves this machine"],
 "code": ["../baseline-models"], "clone": "../analysis",
 "constraints": ["no GPU before October"],
 "autonomy": "checkpoints", "radius": "moderate", "model_fallback": "ask", "ladder_changes": "ask",
 "human_only": ["concern: a decision that sorts a concern after setup"]}
EOF
```

Leave out, or set to null, whatever the owner did not say; the verb writes "not stated" rather than a guess. Keep
the spec: an intake run again rewrites `INTAKE.md` from the spec it is given, so the seventh question sends the same
spec again with `code_repository` added. When nobody is there to approve a heredoc, pass the same answers as plain
options (`wayline intake --intent "..." --reference "..." --autonomy checkpoints --model-fallback ask
--ladder-changes ask --human-only concern`). Read
`research/INTAKE.md` back and say what you assumed; an assumption the owner should see goes into the constraints as
a line beginning `Assumed:`.

What the owner wants answered is recorded as it is said, each as a command of its own, and read back with its id:

```bash
wayline objective add "Do pairwise products raise held-out AUROC on the synthetic set?" --project .
```

A quantitative goal carries its measure in a file and a sample artifact to check it on
(`wayline objective add "<question>" --measure measure.json --sample <artifact>`): the verb runs its
`eval_command` on the sample, and a command that prints no number records the objective without a measure and says
why. Tell the owner the reason and what they would have to give for the goal to stand. Never invent a goal, a
metric, or a baseline number.

Then build the dossiers for the references with `wayline absorb --project .`.

## Setup 1/10: the documents

Sort every file of the owner's own writing, as a command of its own:

```bash
wayline document add <file> --kind inherited --project .
```

`inherited` is an earlier manuscript, a separate Methods, a supplement, or a thesis chapter; `critique` a referee
report, an editor's letter with points, or a collaborator's list of required experiments; `other` anything else,
kept and read only. Published work, the owner's own preprints included, is a reference (`--kind reference`). Ask in
one line only when a document's kind is unclear. A folder is sorted file by file and a `.zip` is unpacked first.
Read `research/DOCUMENTS.md` back: each document's id and what its conversion lost.

Deconstruct each inherited document into the sections with `wayline document deconstruct <id> --project .`,
placing each heading the fixed table does not map with `--place "<heading>=<section>"` (`introduction`, `results`,
`discussion`, `methods`, or `kept`), and move a passage of a separate Methods that reports or interprets an outcome
with `wayline document move <passage> results --project .`. At a start midway (the project inherited Results
claims), run `wayline document repeats --project .`, the consistency read over the inherited claims, which opens
the merges and the contradictions as batches; split the critiques and the open comment threads into concerns with
`wayline concern split --project .`; and write the position memo with `wayline position --project .`, whose critic
proposes a place for each concern.

Then ask the documents' sorts and, at a start midway, the merges, the contradictions, and the concern placements in
one batch: show each open batch with `wayline mark <batch> --project .` (text at five items or fewer, otherwise its
count and the marks view's link), and record each of the owner's marks with
`wayline mark <batch> <item> <mark> --project .`. With no documents, say so in one line.

When the project has no documents, write the position memo now: `wayline position --project .`. It reads the
dossiers, the intake, and the objectives, and gives each objective a verdict and three directions.

## Setup 2/10: the objectives

Run `wayline grill --project .`. Its first tier asks one human-only question per objective, open or parked: each
one `OBJECTIVES.md` holds and each new one the memo proposes, with a recommendation and the memo's verdict. At a
start midway the critic also proposes "Do the inherited results hold?", open by default. Ask the whole tier in one
message, numbered, and record each answer with the owner's reason:

```bash
wayline grill answer Q2 parked --rationale "the owner's reason" --project .
```

An objective the owner wants answered first is recorded with `wayline objective add` before the tier, and the
grill asks it with the others.

## Setup 3/10: the concerns

Read `research/CONCERNS.md` first: the points the critiques raised, each with the critic's proposed place.
The grill adds, each human-only, one question per proposed objective with its concerns, one for the order, and one
for the declines, over the concerns the batch did not settle; and one per objection of the memo's hostile review.
Put each to the owner with each concern's words from the evidence. A concern question is answered `take it` (each
goes where the critic proposed) or `another place` with the place in the rationale (`tie them to O2`, `for the
order`, `decline: <the reason>`); an objection is answered `reject`, or `accept: tie it to O1`, `accept: for the
order`. A concern the groups did not settle is placed with
`wayline concern place <id> --objective <O> --project .` (or `--order`, or `--decline "<reason>"`). Specify drafts
only once every concern is sorted. With no concerns, say so in one line.

## Setup 4/10: the missing material

At a start midway, with "Do the inherited results hold?" taken open, the grill asks one human-only question on every
item the critic's table in `POSITION.md` marks missing. Ask it in one question, with each item's recommendation,
and record the reply: `as recommended`, one reply for every item (`I'll provide it`, `rebuild it`, `leave it
unverified`), or item by item (`M1: I'll provide it; M2: port to Python`). Licensed software takes `I'll provide
it`, `port to Octave`, or `port to Python`; `leave it unverified` makes that result unverifiable with the item as
its reason. With nothing missing, say so in one line.

Then the rest of the design tree. A question belongs in it when the spec needs its answer and no evidence settles
it: what is claimed and what would refute it, the fair baseline, the data and splits, the metric and what counts as
success, what is out of scope, which direction of the memo is taken. Look facts up instead of asking them (`pip
show`, `wayline tools show`, the code that makes the data, a paper's dossier under `research/refs/`); a question
about a reference goes to the consultant (`wayline consult <slug> "<question>" --project .`). Add a question with
`wayline grill ask "<question>" --recommend "<answer>" --evidence "<where you found it>" --project .` (`--requires
Q1` for a prerequisite, `--human-only` for a class `harness.json` lists, `--irreversible` for an answer that cannot
be taken back), ask each tier `wayline grill --project .` prints in one message, record each answer with
`wayline grill answer <Q> "<answer>" --rationale "<their reason>" --project .`, and settle each term with
`wayline grill term "<term>" "<definition>" --project .` before the next tier. Under `autonomous`, or once the
owner says to decide the rest (`wayline switch --autonomy autonomous --project .` first), the decider takes every
question that is not human-only or irreversible: `wayline grill --decide-rest --project .`, given the longest
timeout your shell allows. Never answer a question for the decider: an answer you record is recorded as the
owner's.

## Setup 5/10: the stopping rule and budgets

Ask in one question when the run ends and what it may spend, with a recommendation: the stopping rule
(`objectives`, the default, ends the run when no objective is open; a list of objective ids when those are closed;
`frontier` when no work is left), and the budgets, `wallclock_hours` counted from the end of setup and `gpu_hours`
as each job's hours times the GPUs it held (`none` for no limit). Record each:

```bash
wayline switch --stop-when objectives --project .
```

```bash
wayline switch --budget wallclock_hours=48 --project .
```

During setup these are the owner's word and need no confirmation; after setup, changing the rule or raising a
budget is on the irreversible list.

Then the spec and the plan. Run `wayline specify --project .`: it drafts `research/SPEC.md` with claims answering
every open objective, checks it, has it judged, and asks for its confirmation by the autonomy (under `interactive`
ask the owner and record `wayline specify confirm --project .` or `wayline specify revise "<change>" --project .`;
under `checkpoints` the owner answers its decision ticket; under `autonomous` the decider does). Read the claims
back in a few lines.

Then cut the graph, and leave its confirmation for the end, since the confirmation ends setup:

```bash
wayline plan --cut-only --project .
```

It cuts `research/tickets/` and `graph.json` with the planner, assigns a role and skills to each ticket from the
registry, runs the plan-time checks, and asks for the confirmation without the decider taking it. Read the graph
back: how many tickets, which run first, which decision tickets wait.

## Setup 6/10: the software

Run `wayline tools needs --project .`. When the planned work needs software this machine lacks, it prints one
question: every free tool with its route and sizes, and any licensed software the owner installs. Ask it in one
question, and on the owner's yes install each one they did not leave: `wayline tools install <name> --yes
--project .`. Licensed software is where the owner says it is: `wayline tools install matlab --at <path>`. When
nothing is needed, say so in one line.

## Setup 7/10: the code repository

Ask in one question the code repository's shape, remote, visibility, and license, with a recommendation each: its
`shape` (`package`: the developed method and every model the work applies it to, callable from the package, a
method with its own maintained package a pinned dependency; or `reproducibility`: scripts, helpers, and the
environment alone), its `license` (the inherited one by default), and its remote: a new private GitHub repository
by default, or `remote: owner/name` when the owner says wayline may take over their own (`confirm_public: true`
once, if it is public). It stays private until the owner says `visibility: public`, which is their word only and on
the irreversible list: confirm it first. Record it by sending the intake's spec again with `code_repository` added:
`wayline intake --from - --project .`, the same spec plus `"code_repository": {"shape": "package", "license": "MIT"}`.

When the answer makes the project keep `code/` and a cut ticket writes code outside it, send the graph back:
`wayline plan revise "code tickets write under code/" --project .`, then `wayline plan --cut-only --project .`.

## Setup 8/10: the paper order

Under `autonomous` only: ask in one question whether the decider judges the paper order when the run's rule ends,
and for which venue; the recommendation is yes, with no venue. No verb records the answer yet: tell the owner it
stands at that default until the decider's order is built, and that this question is asked again then. Under the other
autonomies the owner orders the paper, so say in one line that this question is not theirs to answer now.

## Setup 9/10: the front matter

Ask in one question for the front matter, at every autonomy: the authors and their affiliations, the corresponding
author, the acknowledgments, the funding, and the competing interests. It may be left for later: it is needed only at
the paper order, which marks what is not yet given as a placeholder, and the order's card lists it. Record what the
owner gives as one JSON object (paper.md shows its fields):

```bash
wayline paper front - --project . <<'EOF'
{"authors": [{"name": "Ada Lovelace", "affiliations": ["Analytical Engines Ltd"], "corresponding": true}]}
EOF
```

## Setup 10/10: the important unresolved references

Run `wayline reference --project .`. Before setup ends it lists every important unresolved reference the owner has
not left, those still retrying included. Ask in one question for each: a DOI or an exact title back to the scout, a
PDF as its source, or "leave it" until the paper order. Record each answer without asking again:

```bash
wayline reference <slug> 10.1038/s41592-019-0686-2 --project .
```

When none is waiting, say so in one line.

## Ending setup

Setup ends when the graph is confirmed. Under `autonomous`, check first that each of the ten questions is answered,
or said to have nothing to ask, or, the front matter alone, left for later; then run `wayline plan --project .`,
and the decider confirms the graph. Under `checkpoints` the owner answers its "Confirm the graph" decision ticket
(`wayline answer <id> confirm --project .`, or `"revise: <what to change>"`); under `interactive` record their word
with `wayline plan confirm --project .` or `wayline plan revise "<what to change>" --project .`. The confirmation
moves the phase to P5; on the owner's yes, start the run with `wayline run --detach --project .`.

Never lower autonomy on your own. When the owner wants it lowered, tell them how: stop the conductor
(`wayline stop --project .`), then `wayline switch --autonomy checkpoints --project .` once it has ended.
