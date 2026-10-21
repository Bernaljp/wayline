## This project runs under wayline $harness_tag

When the owner talks with a session here, use the `wayline` skill.

The ledger is `research/`. It is written by the harness from structured results, never by hand
while a conductor is running, and it is where everything the project knows is kept: `INTAKE.md`
and `OBJECTIVES.md` say what the work is for (a goal is an objective with a measure), `SPEC.md`
states the claims, `tickets/NN-slug.md` are the units of work, `graph.json` is what the conductor schedules from, `journal.jsonl` is the event log the run
replays to resume, `findings.jsonl` and `manifest.json` carry the results and the artifacts they
cite, `REPORT.md` is the answer, and `ACCOUNT.md` is what wayline did: what it decided for the owner,
what waits on the owner, and each run.

`wayline status` prints the frontier, the running tickets and jobs, the open decision tickets,
the window, the objectives, and the last events. `wayline run` is the conductor. Settings are in
`harness.json`, which pins the harness tag above; `wayline upgrade` moves the pin.

A decision ticket (`kind: decision`) is a question for the owner, and while it is open the tickets
that wait on it do not launch. A session the owner is working in answers one for them with
`wayline answer <id> "<answer>" --rationale "<their reasons>" --project .`, which journals the
answer as the owner's at once; the dashboard's decisions view and an `## Answer` section written
at the end of the ticket file answer it too.

A worker writes only inside its ticket's touch set, runs `wayline accept` before it stops, and
commits on its ticket branch. It never integrates, never closes a ticket, and never edits
`research/`.
