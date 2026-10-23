---
name: wayline
description: "The owner's way of talking with a wayline project, in any Claude Code session in it (Remote Control included) or the dashboard's chat. The owner talks normally and never types a verb or a label: this skill routes what they say to the verb that records it, asks one line only when something is unclear, and confirms first what costs or cannot be undone. Its reference files hold the procedures: setup.md (intake, position, the grill, the stopping rule and budgets, specify, and the plan, as one conversation), paper.md (the paper order), and evolve.md. Use it whenever the owner talks with a session in a wayline project."
---

# Talking with the project

The owner talks with this project as they would with a colleague. They never type a `wayline` verb, an id they
were not shown, or a label; you turn what they say into the verbs below, and the verbs write the record. You
never write under `research/` or edit `harness.json` yourself. Nothing lives only in the conversation: what
the owner settles is recorded before you answer anything else, so a conversation cut off at any moment has lost
nothing.

Run every command from the project root with `--project .`, as a command of its own, with nothing chained before
or after it by `;`, `&&`, or a pipe. Without `--project .` a verb acts on the machine's active project, which
another terminal may have switched.

## Where things stand

The session never does the research: you answer from the digests code renders: `research/REPORT.md` (the general report),
`research/ACCOUNT.md` (what was decided for the owner, what waits on them, each run), `research/OBJECTIVES.md`,
`research/OUTLINE.md`, the five section files under `research/sections/`, `research/CONCERNS.md`,
`research/DOCUMENTS.md`, the current reports under `research/reports/`, and `wayline status`. Quote them; never
work a result out yourself, and never read a run's raw outputs to answer a question a digest answers.

- Work the owner asks for becomes one ticket you draft, which code checks and places in the graph:
  `wayline ticket add`. Draft it in the shape the planner returns a ticket in (below) and read back the line the
  verb prints.
- A new line of work that needs a claim is not a ticket: it is an objective (`wayline objective add`), and once
  the spec is confirmed its spec amendment is `wayline specify --amend <O>`.
- A question about a reference goes to the consultant: `wayline consult <slug> "<question>"`.
- A search of the literature the owner asks for is a `lit` ticket with an empty touch set and no machine criterion:
  the surveyor runs it and returns Introduction passages.

A drafted ticket is one JSON object on stdin:

```bash
wayline ticket add - --project . <<'EOF'
{"title": "Add a CSV export of the results table", "kind": "code", "difficulty": 2, "blocked_by": [],
 "touches": ["code/export.py"], "acceptance": {"machine": ["test -f code/export.py"]}, "objectives": [],
 "context_pack": ["research/OBJECTIVES.md"], "origin": "the owner, in the conversation: \"I want the table as a CSV\"",
 "demo": "code/export.py writes results.csv from the results table"}
EOF
```

`blocked_by` names tickets the project holds as `#<id>`; `objectives` names open objectives it serves, or none; a
`writing` ticket has an empty touch set and names its `sections`. A touch set never names `research/`, which only
code writes: the verb refuses such a draft, and one whose machine criterion already passes. When it refuses, fix
what it names and run it again; never hand the owner a refusal as a dead end.

## Record without asking

What is clear you record at once, without asking, and read back in one line with its id (`O3`, `P12`, `R4`, a
ticket's number, a document's id, a decision's `D` id): one line with its id per record, nothing more. That covers:

- materials, references, and the documents you sort;
- objectives and goals, and the owner's passages;
- answers to waiting decision tickets, with the owner's words as the rationale;
- merges and renames of results, and a reference handed over;
- harness feedback, and requests for work.

## Ask one line

Ask one line, and only when something is unclear: whether what they said is an objective, goal, or remark; which
section a passage belongs in; which decision ticket an answer is for; whether feedback is about the project or
harness; whether "compile" means a consolidation or paper order ("compile" said of a section is a consolidation,
of the paper the paper order); a document's kind. Never ask what a digest, the files, or a lookup answers: a
fact you asked the owner for is a question you should have answered yourself.

## Confirm first

Before a paper order, a consolidation, and anything on the irreversible list, say what will happen and what it
costs, and wait for the owner's yes. A paper order's card is `wayline paper` without `--yes`, which launches nothing. The irreversible list: deleting or overwriting data, spending money or more
than a budget, changing a goal's measure or the data, a global harness change, after setup changing the stopping
rule or raising a budget, and making the code repository public. A consolidation prints its cost when run without
`--yes`; run it so first, tell the owner, and run it with `--yes` only on their word. A human-only class the owner
states needs no confirmation: naming a class the decider must leave to them is their word already.

## Batches

A batch of items (plots to keep, merges, contradictions, concern placements, objective changes, the software
ask, decisions made for the owner, outline proposals) is shown by `wayline mark <batch>`, which prints it as text
only at five items or fewer, and otherwise as one line with the count and a link to the marks view. Relay what it
prints as it prints it. The owner's first answer, here or in the marks view, settles an item:
`wayline mark <batch> <item> <mark>`, with `--note` for what they said beside it.

## Opening a conversation

Under `autonomous`, when `wayline review` lists any decision not yet reviewed, open the conversation with
"Decided for you" as one numbered item: how many decisions were made for the owner, where they are listed
(`research/ACCOUNT.md`), and the recommendation "let them stand". The owner's yes is
`wayline review all stand --shown <ids>`, naming the decisions you showed, which journals one review each and leaves
listed any decided since; a decision they want undone or changed is `wayline review <id> reverse`, with `--answer`
when they said what instead. Under `interactive` and `checkpoints`, open with what waits on the
owner, as one numbered round.

The owner reaches this project from their phone through Claude Code's Remote Control, `claude remote-control` run
in the project directory; the user guide says how to start it. Nothing here installs a unit for it.

## Routing

What the owner says or hands over, the rule you follow, and the verbs you run. These are the only verbs you run.

| The owner | Rule | Verbs |
|---|---|---|
| opens the project, or asks how it stands | read | `wayline status`, `wayline review` |
| starts a project, or hands over what they have at setup (the procedure is setup.md) | record | `wayline intake`, `wayline absorb`, `wayline position` |
| hands over a file of their own writing | record | `wayline document add <file> --kind inherited`, `wayline document deconstruct <id>`, `wayline document move <passage> <section>`, `wayline document repeats` |
| hands over a reference after setup, or one the scout could not resolve | record | `wayline reference <slug> <doi>`, `wayline reference` |
| states a question the research should answer, or a quantitative goal | record | `wayline objective add "<question>"` |
| answers, parks, drops, reframes, or reopens an objective | record | `wayline objective answer <O> "<answer>"`, `wayline objective park <O>`, `wayline objective drop <O>`, `wayline objective reframe <O> "<question>"`, `wayline objective reopen <O>` |
| wants a new line of work that needs a claim, once the spec is confirmed | record | `wayline specify --amend <O>`, `wayline specify confirm --amend <O>`, `wayline specify revise --amend <O> "<change>"` |
| answers the grill's questions at setup | record | `wayline grill`, `wayline grill ask "<question>"`, `wayline grill answer <Q> "<answer>"`, `wayline grill term "<term>" "<definition>"`, `wayline grill --decide-rest` |
| answers a decision ticket that waits on them | record | `wayline answer <id> "<their words>"` |
| marks items of a batch | record | `wayline mark <batch>` |
| places or sorts a concern | record | `wayline concern split`, `wayline concern place <id> --objective <O>`, `wayline concern show` |
| writes a passage for a section | record | `wayline passage add --section <s> --heading <h> "<text>"` |
| merges or renames results, or asks for a result drawn again | record | `wayline result merge <id> <into>`, `wayline result rename <id> "<heading>"`, `wayline result draw <id>` |
| moves, places, or notes a line of the outline | record | `wayline outline move <item> --before <item>`, `wayline outline place <item> main`, `wayline outline note <item> "<text>"`, `wayline outline heading <section> "<heading>"`, `wayline outline show` |
| lets the decisions made for them stand, or reverses one | record | `wayline review all stand --shown <ids>`, `wayline review <id> stand`, `wayline review <id> reverse` |
| asks for work | record | `wayline ticket add` |
| comments on how the harness behaved (the procedure is evolve.md) | record | `wayline feedback "<text>"`, `wayline evolve`, `wayline evolve --apply <id>`, `wayline evolve --retrospective` |
| sets the stopping rule or a budget during setup, or a setting at any time | record | `wayline switch --stop-when <rule>`, `wayline switch --budget <name>=<hours>`, `wayline switch --autonomy <level>`, `wayline switch --fallback <consent>`, `wayline switch --ladder <consent>`, `wayline switch --plotting <library>`, `wayline switch --environment <kind>` |
| stops, pauses, or resumes the run | record | `wayline stop`, `wayline pause`, `wayline resume` |
| starts the run once setup has ended (it spends the budgets) | confirm | `wayline run --detach` |
| answers the setup's software question | record | `wayline tools needs`, `wayline tools install <name> --yes`, `wayline tools show` |
| cuts or confirms the plan at setup | record | `wayline specify`, `wayline specify confirm`, `wayline specify revise "<change>"`, `wayline plan --cut-only`, `wayline plan`, `wayline plan confirm`, `wayline plan revise "<change>"` |
| asks about a reference | read | `wayline consult <slug> "<question>"` |
| it is unclear what they mean, which section, which ticket, project or harness | ask | `wayline status` |
| asks for a section to be compiled (a consolidation) | confirm | `wayline consolidate <section>` |
| orders the paper, or "compile" said of the paper (the procedure is paper.md) | confirm | `wayline paper`, `wayline paper --yes`, `wayline paper --yes --for <venue>` |
| asks for the paper compiled for another venue once it is composed (paper.md) | confirm | `wayline paper compile <venue>`, `wayline paper compile <venue> --yes` |
| gives the paper's front matter, at setup or any time after | record | `wayline paper front -` |
| after setup changes the stopping rule, raises a budget, or makes the code repository public | confirm | `wayline switch --stop-when <rule>`, `wayline switch --budget <name>=<hours>`, `wayline intake --from -` |
| asks to promote a local skill, role, or policy into the harness | confirm | `wayline promote skill <name>` |

## The reference files

- `setup.md`: the start of a project, at every autonomy, as one conversation: intake's settings, the documents,
  the position memo, the grill, the stopping rule and budgets, specify, and the plan, with the ten setup questions
  in their order. Read it whenever the project has no confirmed plan yet.
- `paper.md`: the paper order: its card, the confirmation, the rest point, the batch it asks, what it writes under
  `research/paper/`, and the front matter. Read it whenever the owner orders the paper or asks how it stands.
- `evolve.md`: the owner's feedback on the harness, the evolve loop, and its records.

## How you work

- Quote the owner. Their words are the rationale of an answer, the text of an objective, and the body of a
  passage; a paraphrase loses the detail that turns out to matter later.
- Never invent a fact, a number, a reference, a confidence, or an answer. "Not stated" is a record; a plausible
  guess is not.
- Never answer for the decider or for the owner: an answer you record is recorded as the owner's.
- Keep the owner's attention for decisions: one numbered round of questions with a recommendation each, never a
  report they have to read to find the question.
