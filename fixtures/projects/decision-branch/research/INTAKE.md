# Intake

## The intent

Prove that a decision ticket pauses exactly the branch that waits on it: the alpha note is written
and extended while the beta report waits for the owner to choose its form, and the beta branch runs
once the owner has answered. The owner wants a report a person reads at a glance.

## What exists already

This file and the five tickets. The project is a fixture: it is copied out of the harness, laid
out by `wayline init`, and run with the fake worker.

## References

None. A fixture that needed a dossier would not be a fixture.

## Constraints

The acceptance commands are shell built-ins, so the fixture runs on a machine with no Python
project, no test framework, and no network.

## Success

`notes/alpha.md` and `reports/beta.md` on `main`, all five tickets `done`, one `decision` event for
ticket 2 with `decided_by: human`, and ticket 3 launched only after it.
