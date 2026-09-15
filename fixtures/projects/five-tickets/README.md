# The five-ticket project

The M1 graph: two independent branches and one touch-set conflict, which is what the conductor's
frontier, launchable subset, and pick order are for.

```
1 write notes/alpha.md ──▶ 3 extend notes/alpha.md          5 index notes/
2 write reports/beta.md ─▶ 4 extend reports/beta.md
```

Tickets 1 and 2 share no path, so they run at once. Ticket 5's touch set is the directory
`notes/`, which is where 1 and 3 write, so it is in the frontier from the first wave and
launchable in neither of the first two: a ticket whose touch set meets a running ticket's is not
launchable, and the pick order prefers 1 and 3 anyway, because each of them has a ticket waiting
behind it and 5 has none.

With `max_parallel_workers` at its policy value of 2 the run is three waves:

| Wave | Launched | Why not the rest |
|---|---|---|
| 1 | 1, 2 | 5 collides with 1, which is running |
| 2 | 3, 4 | 5 collides with 3, which is running |
| 3 | 5 | nothing is left |

`fake-worker.json` is the script the fake worker follows, one entry per ticket keyed by ticket id
rather than by order, because the launches of one wave overlap. Each entry writes its ticket's
files, commits them on the ticket branch, and returns a `done` result.

Ticket 4 also probes the touch-set guard: its `## What to do` asks the worker to try one write
outside its touch set and report the hook's refusal as a finding, which is what the M1 demo shows
live in the envelope's `permission_denials`, the result, and the journal. The fake entry returns
that finding without the refusal behind it.

## From a shell

Copy it out first. Running it in place would put a git repository inside the harness checkout,
and the conductor branches worktrees from the project's own `main`.

```
cp -r fixtures/projects/five-tickets /tmp/five-tickets
bin/wayline init /tmp/five-tickets
WAYLINE_LAUNCHER=fake WAYLINE_FAKE_SCRIPT=/tmp/five-tickets/fake-worker.json \
  bin/wayline run --project /tmp/five-tickets
bin/wayline status --project /tmp/five-tickets
```

`init` registers the project in `~/.wayline/projects.json` and makes it active; export
`WAYLINE_HOME=/tmp/five-tickets-home` before both commands to keep it out of your own pointers.

What to look for afterwards: three waves, five tickets `done`, `run_ended` with `frontier_empty`,
and, in `research/journal.jsonl`, ticket 2's `ticket_launched` before ticket 1's `ticket_result`
(the two ran at the same time) and ticket 5's `ticket_launched` after the `integrated` of both
ticket 1 and ticket 3 (the conflict serialized).

```
grep -o '"event":"[a-z_]*","ticket":[0-9]*' /tmp/five-tickets/research/journal.jsonl
```
