# The M0 live project

The project the M0 demo runs on: one trivial `code` ticket that writes two files under `m0/`,
tries one write outside its touch set, delegates one read to an Agent-tool subagent, and carries
two `/wayline-<skill>` lines from the two skills under `.claude/skills/`. It is the smallest thing
that exercises the conductor's whole M0 path against a real worker, and every step of it is a
probe of the harness rather than work anyone wants done.

`fixtures/projects/one-ticket/` is the same path with nothing to probe; the suite runs both with
the fake worker, and this one is also what `docs/verification/m0.md` records live.

The two skills carry one passphrase each, written in their `SKILL.md` and nowhere else in the
project. A worker that appends both passphrases to `m0/skills-seen.txt` had both skill bodies in
front of it; a worker that appends only the first had only the first.

`fake-worker.json` is the script the fake worker follows: one call, which writes the three files,
commits them on the ticket branch, and returns a `done` result whose findings carry the refusal the
touch-set hook would have given.

## From a shell, with the fake worker

Copy it out first. Running it in place would put a git repository inside the harness checkout, and
the conductor branches worktrees from the project's own `main`.

```
cp -r fixtures/projects/m0-live /tmp/m0-live
export WAYLINE_HOME=/tmp/m0-live-home
bin/wayline init /tmp/m0-live
WAYLINE_LAUNCHER=fake WAYLINE_FAKE_SCRIPT=/tmp/m0-live/fake-worker.json \
  bin/wayline run --project /tmp/m0-live
bin/wayline status --project /tmp/m0-live
```

## From a shell, live

The same three commands with the real launcher, which is the default, and with the guards asked to
keep what they were handed:

```
cp -r fixtures/projects/m0-live /tmp/m0-live
export WAYLINE_HOME=/tmp/m0-live-home
export WAYLINE_HOOK_RECORD=/tmp/m0-live-hooks.jsonl
bin/wayline init /tmp/m0-live
bin/wayline run --project /tmp/m0-live
bin/wayline status --project /tmp/m0-live
```

`WAYLINE_HOOK_RECORD` is what makes the run recordable: the command guard appends every hook input
it is handed to that file, subagent calls included, which is where the `agent_id` and `agent_type`
of the record come from. Nothing else changes between the two runs.

What to look for afterwards: `m0/hello.txt`, `m0/report.md` and `m0/skills-seen.txt` on `main`,
the worker's commit under a `ledger: wave 1` commit in `git -C /tmp/m0-live log --oneline`, an
empty `.worktrees/`, a finding in `research/findings.md` quoting the hook's own refusal, and a
journal that runs `ticket_launched`, `ticket_session`, `ticket_result`, three `acceptance`
events, `integrated`, `finding`, `ticket_done`, `run_ended`.
