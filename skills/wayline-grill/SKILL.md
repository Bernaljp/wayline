---
name: wayline-grill
description: "The second half of phase P2 of a wayline run. Builds the design tree of open questions from research/POSITION.md and research/INTAKE.md, asks its frontier in tiers with a recommended answer on each, looks facts up instead of asking them, lands every answer in research/DECISIONS.md and every settled term in research/CONTEXT.md through `wayline grill`, and raises the autonomy switch when the owner says to decide the rest. Use it after the position memo and before specify."
---

# The grill

The spec is cut from what this conversation settles. Every question the spec, the planner, or a
worker would otherwise have to guess belongs here, and each one is asked once, with your
recommendation, together with every other question that can be asked at the same time.

You do not write the record yourself. `wayline grill` does, because the ledger is the only writer
of `research/`: it holds the design tree in `research/DECISIONS.md`, works out which questions can
be asked, journals each answer, and writes each term into `research/CONTEXT.md`. Your work is the
reading, the looking up, the asking, and turning what the owner says into those commands.

Run every `wayline` command from the project root with `--project .`. Without it a verb acts on the
machine's active project, which another terminal may have switched to a different one.

## Before the first tier

Read `research/INTAKE.md` (the intent, the constraints, the human-only classes),
`research/POSITION.md` (the closest prior work, the feasibility verdict, a verdict on each
objective, the hostile reviewer's objections, the three directions and the objectives each would
pursue), `research/OBJECTIVES.md` (the objectives recorded, a goal being one with a measure), the
dossiers under `research/refs/`, and `research/CONTEXT.md` and `research/DECISIONS.md` when they
exist already, which means a grill is being picked up again. Then run `wayline grill --project .`
to see the tree as it stands.

## The first tier: which objectives the project takes

Before it asks a first tier, `wayline grill` adds one question per objective: each one
`OBJECTIVES.md` holds, open or parked, and each new one the memo's directions propose (a memo
written after a tier was asked is put to the owner in the next one). Each asks
whether the project takes it, `open` or `parked`, with a recommendation and the memo's verdict as
evidence. They are human-only: only the owner answers them, under every autonomy, and while any is
open the tier asks only them, since every later question builds on which objectives are taken. Put
them to the owner as the verb prints them and hand each answer back as `open` or `parked`, with the
owner's reason as the rationale:

```bash
wayline grill answer Q2 parked --rationale "the owner's reason" --project .
```

The verb records each answer through the objectives' ledger: a recorded objective moves to the
status chosen, and a proposed one is recorded as a new objective. A question the owner wants
answered first is an objective too: record it with `wayline objective add` before the first tier,
and it is asked with the others.

When there is no `POSITION.md`, tell the owner in one line that the questions rest on the intake
alone.

## The design tree

A question belongs in the tree when the spec needs its answer and no evidence settles it: what is
claimed and what would refute it, which baseline is the fair comparison, which data and splits the
claims rest on, the metric and what counts as success, what the method may assume, the budget of
an experiment, what is out of scope, which of the position memo's directions is taken, and how
each of the hostile reviewer's objections is met. Walk the sections the spec will have (claims and
anti-claims, methods, experiments, baselines, data, metrics, success criteria, budgets, out of
scope, risks) and the memo's objections, and ask what each leaves open. A question every answer to
which leads to the same spec is not a question.

A question has prerequisites when its sensible options depend on another answer: which
interaction terms to try depends on which model carries them. Name them with `--requires`. The verb
asks a question only once its prerequisites are settled, and that is what makes a tier.

Add prerequisites before the questions that need them, one command each:

```bash
wayline grill ask "Which baseline do the claims compare against?" --option "logistic regression on the raw features" --option "gradient-boosted trees on the raw features" --recommend "logistic regression on the raw features" --evidence "paper-a reports its gains over a linear model (research/refs/paper-a/dossier.json)" --project .
```

```bash
wayline grill ask "Which interaction terms are in scope?" --requires Q1 --recommend "pairwise products only" --project .
```

The verb prints each question's id (`Q1`, `Q2`, and so on). Every question gets a recommended
answer; a question you cannot recommend an answer to is usually a fact you have not looked up yet.

Mark a question `--human-only` when its answer falls in a class `harness.json` lists under
`human_only`; a change to an objective (a goal's measure among them) or to the data always does
(`objective` was named `goal` before, and is read so). Mark it `--irreversible` when its answer
cannot be taken back: it spends a budget, deletes or overwrites data, or changes a goal's measure.
The decider never resolves either kind, even after the switch; both wait for the owner.

## Facts are looked up, decisions are asked

Before a question goes in the tree, decide which kind it is.

- A **fact** is anything the machine can answer. Whether a library is installed:
  `pip show <name>`, or `python3 -c "import <name>"`. What the tools venv holds:
  `wayline tools show`. How much data there is and how it is split: read the code that makes it or
  the data itself. What a paper claims or reports: its dossier, `research/refs/<slug>/dossier.json`
  and `dossier.md`. Whether a reference exists at all: the dossier's `existence`. Look it up. A fact
  you asked the owner for is a question you should have answered yourself.
- A **decision** is a choice the evidence does not settle. Ask it.

When a question rests on a paper that has no dossier, say so and recommend absorbing it
(`wayline absorb`) rather than guessing what it says. Where `wayline consult <slug> "<question>"`
is available, it asks the consultant about one dossier.

Put what you found on the question it bears on, with where you found it
(`--evidence "20000 rows; the last quarter is split_b, held out (toy/make_synthetic.py)"`), and
tell the owner, in a sentence or two before the tier, what you looked up and what it rules out.
That is often what makes a recommendation obvious.

## Asking a tier

Run `wayline grill --project .`. It stamps the tier and prints it: every question whose
prerequisites are settled, numbered, with its options, your recommended answer, and the evidence.
Ask the owner that whole tier in one message, in that order and with those numbers:

```
Tier 1: 3 questions. Answer by number, in any order; "yes" to a number takes the recommendation.

1. Which baseline do the claims compare against?
   Options: logistic regression on the raw features; gradient-boosted trees on the raw features
   Recommended: logistic regression on the raw features, because paper-a reports its gains over a linear model and matching it keeps the comparison readable.
```

Every question carries a line beginning `Recommended:` with its reason. Write `human-only` or
`irreversible` beside a question the decider will never take. Ask nothing that is not in the tier,
and hold nothing in it back: asking one question at a time spends the owner's attention on round
trips instead of on decisions, and that is the failure this skill exists to prevent.

Say once, at the first tier, that the owner can tell you to decide the rest at any moment.

## Recording the answers

When the owner replies, record every answer before anything else, one command per answer:

```bash
wayline grill answer Q1 "logistic regression on the raw features" --rationale "the owner took the recommendation: paper-a reports its gains over a linear model" --project .
```

- The answer is what the owner chose, in their words when they gave words. The rationale is their
  reason; when they only took the recommendation, it is the recommendation's reason, marked as such.
- Pass `--confidence` (0 to 1) only when their words say how sure they are: "definitely" is high,
  "I suppose" is low. Otherwise leave it out, and the record says "not stated". Never invent one.
- A number the owner skipped stays open and is asked again in the next tier. A reply that asks you
  something back is not an answer: answer it, and ask the question again.
- An answer that changes a settled one is a revision:
  `wayline grill answer <id> "<new answer>" --rationale "<why>" --revise --project .`. Tell the
  owner which later answers rested on the old one.
- An answer that opens a question the tree did not have is a new question: add it, requiring the
  question whose answer opened it.

Then settle the terms. A term is a word the spec, the tickets, and the report will use with a
meaning particular to this project, such as "held-out split" or "interaction term". Settle each one
the answers fixed, before the next tier:

```bash
wayline grill term "Interaction term" "The product of two raw features, added to the model as a column of its own." --avoid "cross feature" --project .
```

Only then run `wayline grill --project .` for the next tier, and ask it. The order matters:
everything the owner settled is written before anything new is asked, so a conversation cut off at
any moment has lost nothing.

Run each command on its own, with nothing chained before or after it by `;`, `&&`, or a pipe. When
nobody is there to approve commands, a chained command or a heredoc is refused whole and nothing is
written. With the owner at a terminal that asks before each command, the answers, terms, and new
questions of one reply can go in as one batch, which is checked whole before anything is written:

```bash
wayline grill --project . --from - <<'EOF'
{"answers": [{"id": "Q1", "answer": "logistic regression on the raw features", "rationale": "the owner took the recommendation"}],
 "terms": [{"term": "Interaction term", "definition": "The product of two raw features.", "avoid": ["cross feature"]}],
 "questions": []}
EOF
```

## The autonomy switch

The owner raises autonomy by telling you to decide the rest ("decide the rest yourself", "you pick
the rest", "go autonomous"), or with `wayline switch --autonomy autonomous` themselves. When they
tell you:

1. Record the answers and terms that came in the same message first, as above.
2. Run `wayline switch --autonomy autonomous --project .`. It journals the switch and writes it to
   `harness.json`.
3. Do not answer the remaining questions yourself. They are the decider's, and the decider records
   its decisions as `decided-by: decider`, so the owner can audit and reverse each one. An answer
   you record through `wayline grill answer` is recorded as the owner's, which would be false.
4. Run `wayline grill --decide-rest --project .`. It launches the decider, one max-effort session
   per open question that is not human-only or irreversible, until only the owner's questions are
   left, and prints each decision with its confidence and the command that reverses it. A question
   the decider was refused (its answer would cross the irreversible list) comes back as the
   owner's, with a decision ticket beside it. Then run `wayline grill --project .`: it asks only
   the human-only and irreversible questions, which still wait for the owner. Ask those, if there
   are any, and record the owner's answers to them as before.

   Each decision takes two to four minutes, so the verb often runs longer than a command's default
   timeout. Give it the longest timeout your shell tool allows. If it is still running when that
   timeout ends, do not end your turn with it unfinished: when your session ends, the decider's
   session is killed with it, and the question it was deciding stays open. Say which questions are
   decided so far (`wayline grill --project .` lists them), and tell the owner that `wayline grill
   --decide-rest` takes up the rest, and that `wayline specify` does so on its own before it drafts.
5. Tell the owner plainly what changed: the decider resolves every open question and every decision
   ticket that is not human-only, the report lists its decisions first, and nothing on the
   irreversible list is decided without them.

Never lower autonomy, and never raise it on a remark that was not an instruction. When the owner
wants it lowered, tell them how: stop the conductor (`wayline stop --project .`), then
`wayline switch --autonomy checkpoints --project .` (or `interactive`) once it has ended.

## When the grill is done

`wayline grill` says every question is settled when the frontier is empty. Tell the owner, sum up
the decisions in a few lines, and name the next phase, `wayline specify`.

## How you work

- Never write under `research/`, and never edit `harness.json`, yourself: the verbs do both.
- Quote the owner. A paraphrased answer loses the detail that turns out to matter at the spec.
- Never invent a fact, a number, a reference, a confidence, or an answer. "Not stated" is a record;
  a plausible guess is not.
- Keep the owner's attention for decisions: a tier is questions and recommendations, not a report.
