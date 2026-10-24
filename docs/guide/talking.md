# Talking with a project

The conversation is your talk with a project. It happens in two places, which record the same way: the dashboard's
chat, the main place, and any Claude Code session in the project directory, Remote Control included. In both you talk
as you would to a colleague; the session uses the `wayline` skill (`skills/wayline/SKILL.md`) to turn what you say into
verbs, and nothing lives only in the conversation.

What the session does with what you say:

- **Records without asking** what is clear (materials, references, documents, objectives and goals, your passages,
  answers to decision tickets with your words as the rationale, merges and renames of results, feedback, requests
  for work) and reads each record back in one line with its id (`O3`, `P12`, `R4`, a ticket's number, `D2`).
- **Asks one line** only when something is unclear: is this an objective or a remark, which section a passage goes
  in, which decision your answer is for, whether "compile" means a consolidation of a section or the paper order.
- **Confirms first**, with what will happen and what it costs: starting the run, the paper order, a consolidation,
  and anything on the irreversible list (deleting or overwriting data, spending money or more than a budget, changing
  a goal's measure or the data, a global harness change, after setup changing the stopping rule or raising a budget,
  and making the code repository public).
- **Never does the research.** It answers from what code renders: `research/REPORT.md`, `research/ACCOUNT.md`,
  `research/OBJECTIVES.md`, `research/OUTLINE.md`, the section files, and `wayline status`.

A batch of items for you to mark (plots, merges, objective changes, and so on) is shown as text at five items or
fewer, and otherwise as one line with its count and a link to the [marks view](run.md#the-marks-view).

## The dashboard's chat

One collapsible panel over every view of the dashboard (the whole screen on a phone), one conversation per project.
Each item's insert button puts its reference into your message, and the view and item you have open travel with the
message, so "drop this one" under a plot means that plot. Each message is one Claude Code session in the project on
`opus high`, unless `harness.json`'s `chat` (`{"model", "effort"}`) names another; the last session is resumed while
its reply is under an hour old. Messages are answered one at a time, in order. The conversation is kept under
`research/chat/` (gitignored).

What needs confirming comes back as a card with what will happen, its cost, **Confirm**, and **Not now**; Confirm
runs the action from the dashboard. The chat cannot run a confirmed verb itself, so text inside a document it reads
can at most produce a card. The chat answers at every pacing level except a hit limit, where code says it cannot
answer and launches nothing.

## A Claude Code session, and Remote Control

Any `claude` session started in the project directory reads the project's `CLAUDE.md` and uses the `wayline` skill.
To reach the project from your phone, start Claude Code's Remote Control in the project directory on the workstation:

```bash
cd <project> && claude remote-control
```

Keep it in a terminal that outlives your login (a `tmux` or `screen` session). No unit is installed for it, so start
it again after a reboot.

## Setup

Setup is one conversation from what you hand over to a confirmed plan, at every autonomy, and it is the only time an
automated run asks you anything. Hand over anything in any form: a manuscript, a Methods, a supplement, a referee
report, a folder, a `.zip`, references as bare identifiers. The session writes the intake's settings first (autonomy,
radius, the fallback consent, the ladder consent, the human-only classes), then asks ten questions in order, each
headed `Setup N/10`, with a recommendation:

1. the documents' sorts (and at a start midway the merges, contradictions, and concern placements, one batch);
2. the objectives;
3. the concerns;
4. the missing material;
5. the stopping rule and budgets;
6. the software;
7. the code repository;
8. under `autonomous` only, whether the decider orders the paper at the run's end, and for which venue;
9. the front matter (which may be left for later);
10. the important unresolved references.

A question with nothing to ask is said in one line so you see it was not skipped. Setup ends when the graph is
confirmed, and the run starts on your yes.

How the autonomies differ at setup:

- `interactive`: you confirm the spec and the graph in the conversation.
- `checkpoints`: you answer the "confirm" decision tickets for the spec and the graph.
- `autonomous`: the decider confirms them, takes every grill question that is not human-only or irreversible, and
  setup ends only when every one of the ten questions is answered; nothing about them is asked after setup.

Lowering autonomy means stopping the conductor first; the session never lowers it on its own.

## Verbs the session runs

`wayline intake --from -`, `wayline absorb`, `wayline position`, `wayline grill`, `wayline grill answer`,
`wayline grill --decide-rest`, `wayline specify`, `wayline specify confirm`, `wayline plan --cut-only`,
`wayline plan confirm`, `wayline answer`, `wayline mark`, `wayline ticket add` (work you ask for, drafted as one
ticket and checked like the planner's), `wayline feedback` (comments on how the harness behaved, for the evolve
loop), `wayline switch --autonomy <level>`, and `wayline run --detach`. Every command runs with `--project .`.
