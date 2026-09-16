# The one-ticket project

A project with one trivial `code` ticket: write `hello.txt` holding the line `hello`, with two
shell commands as its Type-A gates. It is the smallest thing that exercises the conductor's whole
M0 path, and the suite runs it with the fake worker in `tests/test_conductor.py`.

`fake-worker.json` is the script that fake worker follows: one call, which writes `hello.txt`,
commits it on the ticket branch, and returns a `done` result with one finding.

## From a shell

Copy it out first. Running it in place would put a git repository inside the harness checkout,
and the conductor branches worktrees from the project's own `main`.

```
cp -r fixtures/projects/one-ticket /tmp/one-ticket
bin/wayline init /tmp/one-ticket
WAYLINE_LAUNCHER=fake WAYLINE_FAKE_SCRIPT=/tmp/one-ticket/fake-worker.json \
  bin/wayline run --project /tmp/one-ticket
bin/wayline status --project /tmp/one-ticket
```

`init` registers the project in `~/.wayline/projects.json` and makes it active; export
`WAYLINE_HOME=/tmp/one-ticket-home` before both commands to keep it out of your own pointers.

What to look for afterwards: `hello.txt` on `main`, `git -C /tmp/one-ticket log --oneline` showing
the worker's commit under a `ledger: wave 1` commit, an empty `.worktrees/`, and a journal that
runs `ticket_launched`, `ticket_session`, `ticket_result`, three `acceptance` events,
`integrated`, `manifest` (the cited file registered), `finding`, `ticket_done`, `run_ended`.
