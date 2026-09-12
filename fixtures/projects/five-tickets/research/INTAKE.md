# Intake

## The intent

Prove that the conductor schedules a graph rather than a queue: two independent branches run at
the same time, and the one ticket whose touch set collides with another's waits until that other
ticket has been integrated. The answer is a `main` carrying all five tickets' work and a journal
whose launches say when each one was allowed to start.

## What exists already

This file and the five tickets. The project is a fixture: it is copied out of the harness, laid
out by `wayline init`, and run with the fake worker.

## References

None. A fixture that needed a dossier would not be a fixture.

## Constraints

The acceptance commands are shell built-ins, so the fixture runs on a machine with no Python
project, no test framework, and no network.

## Success

`notes/alpha.md`, `notes/INDEX.md`, and `reports/beta.md` on `main`, all five tickets `done`, and
the journal carrying `run_ended` with `frontier_empty`.
