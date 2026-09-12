# Intake

## The intent

Prove that the conductor runs one ticket end to end through a real `claude -p`, and that the four
things M0 could only assume are true of a live worker: the touch-set hook refuses a write outside
the touch set under `--permission-mode dontAsk`, the same hooks fire inside an Agent-tool
subagent, both `/wayline-<skill>` lines at the top of the prompt expand, and `wayline accept`
resolves and satisfies the stop guard. The answer is a `main` that carries the worker's commit, a
journal that says how it got there, and a record in `docs/verification/m0.md` of everything the
live run did that the notes did not predict.

## What exists already

This file, one ticket, and two skills under `.claude/skills/` that exist only to carry a
passphrase each. The project is a fixture: it is copied out of the harness, laid out by
`wayline init`, and run either with the fake worker (the suite) or with a real one (the M0
record).

## References

None. A fixture that needed a dossier would not be a fixture.

## Constraints

The acceptance commands are shell built-ins, so the fixture runs on a machine with no Python
project, no test framework, and no network. The ticket is trivial on purpose: every step of it is
a probe of the harness rather than work anyone wants done.

## Success

`m0/hello.txt` and `m0/report.md` on `main`, the ticket `done`, the journal carrying `run_ended`
with `frontier_empty`, and a finding that quotes the refusal the hook gave the worker.
