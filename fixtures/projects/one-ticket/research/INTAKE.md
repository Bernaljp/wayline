# Intake

## The intent

Prove that the conductor runs one ticket end to end: frontier, worktree, prompt, worker,
validation, machine acceptance, rebase, fast-forward, ledger, journal, worktree removed. The
answer is a `main` that carries the ticket's commit and a journal that says how it got there.

## What exists already

Nothing but this file and the one ticket. The project is a fixture: it is copied out of the
harness, laid out by `wayline init`, and run with the fake worker.

## References

None. A fixture that needed a dossier would not be a fixture.

## Constraints

The acceptance commands are shell built-ins, so the fixture runs on a machine with no Python
project, no test framework, and no network.

## Success

`hello.txt` on `main` holding the single line `hello`, the ticket `done`, and the journal
carrying `run_ended` with `frontier_empty`.
