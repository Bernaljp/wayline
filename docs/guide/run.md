# The run

Once setup ends and you say yes, the conductor runs waves until the stopping rule, a budget, a strict stall, or your
stop ends the run. The tick (`wayline-tick.timer`) relaunches work after usage windows, answers, and jobs, and never
relaunches a run that its rule or a spent budget ended. Say "pause", "resume", or "stop" at any time.

## The account

`research/ACCOUNT.md` is what wayline did, rendered by code at the end of every wave; the research itself is in
`research/REPORT.md`. It holds where the project stands, then:

- **Decided for you**: each decision the decider or a conductor default made, not yet reviewed (`D1` onward), with
  the answer, the confidence, and a link to its rationale;
- **Waiting on you**: decision tickets for you, tickets needing a person, proposed harness changes, important
  references that did not resolve, a code repository still private at a paper order;
- **Changed without asking you**: your passages a later passage replaced, and standing merges;
- **Runs**: the latest run in full (its end and reason, each ticket's outcome and model, the run-end gates, drawings,
  hours, tokens per ticket), earlier runs one row each;
- **Not pursued**, and the **Library** (papers by level, unresolved cited references).

Say "let them stand" to the decisions made for you, or "undo D3, I want ..." to reverse one: a reversal is your own
answer, human-only from then on, and never stops the run. The account is read-only.

Each run ends with one end notice: the account's first paragraph and "N decided for you, M waiting on you".

## What each autonomy does after setup

- `interactive`: each notice as it arises; you answer every decision ticket.
- `checkpoints`: decision tickets notify you as they open and pause only their subgraph; other notices are held for
  your next conversation or the end notice.
- `autonomous`: the decider answers every decision outside the human-only classes and the irreversible list; you get
  only the end notice and a notice when the login expires. Your next conversation opens with "Decided for you" and the
  recommendation to let them stand.

The decider never changes the stopping rule or raises a budget, never sets the environment or the plotting library,
and never makes the code repository public.

## The marks view

`#/<project>/marks` in the dashboard holds every open batch: plots (keep, maybe, drop), objective changes and the
software ask (approve, decline), decisions made for you (stand, reverse), merges (right, split), contradictions (real,
not a contradiction), concern placements (take it, another place), and outline proposals (take, decline). Each item is
shown whole with a note box; a mark saves when clicked, and "Take all defaults" settles the rest in one click. The first
answer, here or in the conversation, settles an item, and each settled item shows who gave it. On a phone the view
shows one item per screen.

## The dashboard's views and actions

Views are routed by the address (`#/<project>/<view>`), and the browser's back and forward work:

- **Research**: the general report, each objective with its status, measure, and kept values, its results with
  their reports and plots, the results beyond the objectives, and the plotting library.
- **Run**: the run's state and controls, the account, and Software (`tools.json`, the MATLAB check, the environment,
  a move in progress).
- **Paper**: the five sections and the outline with edit buttons, References with each unresolved row's hand-over
  form, the code repository, Methods' parameter table, and the paper order's card, parts, versions, and compilations.
- **Inherited** (only for a project with documents): documents, concerns, inherited claims with their standing,
  contradictions, merges, and missing material.
- **Marks**, above.

Every item has a link (`#/<project>/R4`, `R4.3`, `O3`, `P12`, `D1`, `K3`, `account`, a ticket number) that opens it in
the viewer. A "Waiting on you" strip on every view mirrors the account, and its count is in the browser tab's title.
`#/` is the projects page. The chat panel sits over every view ([Talking with a project](talking.md)).

The dashboard's actions call the same functions as the verbs and need the token: answer, autonomy, pause, resume,
cancel, rerun, the fallback and ladder consents, feedback, mark, edit, run, the stopping rule, a budget, consolidate,
the paper order, compile, plotting, reference, choose, and making the code repository public.

## Verbs the session runs

`wayline status`, `wayline review` (lists what is not yet reviewed), `wayline review all stand --shown <ids>`,
`wayline review <id> reverse --answer "<text>"`, `wayline pause`, `wayline resume`, `wayline stop`,
`wayline run --detach`, `wayline answer <id> "<text>"`, `wayline mark <batch>`, and `wayline switch --fallback <consent>` or
`wayline switch --ladder <consent>`.
