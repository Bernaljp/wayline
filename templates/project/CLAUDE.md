## This project runs under wayline $harness_tag

The ledger is `research/`. It is written by the harness from structured results, never by hand
while a conductor is running, and it is the project's memory: `INTAKE.md` and `GOAL.json` say
what the work is for, `SPEC.md` states the claims, `tickets/NN-slug.md` are the units of work,
`graph.json` is what the conductor schedules from, `journal.jsonl` is the event log the run
replays to resume, `findings.jsonl` and `manifest.json` carry the results and the artifacts they
cite, and `REPORT.md` is the answer.

`wayline status` prints the frontier, the running tickets and jobs, the open decision tickets,
the window, the goal, and the last events. `wayline run` is the conductor. Settings are in
`harness.json`, which pins the harness tag above; `wayline upgrade` moves the pin.

A worker writes only inside its ticket's touch set, runs `wayline accept` before it stops, and
commits on its ticket branch. It never integrates, never closes a ticket, and never edits
`research/`.
