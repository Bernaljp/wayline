---
id: 4
title: Extend the beta report
kind: code
difficulty: 1
status: open
blocked_by: [2]
touches: [reports/beta.md]
role: coder
skills: []
outputs: [reports/beta.md]
acceptance:
  machine: ["grep -qx beta reports/beta.md", "grep -qx 'beta extended' reports/beta.md"]
  quality: []
context_pack: [research/INTAKE.md, research/tickets/04-extend-the-beta-report.md#what-to-do]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`reports/beta.md` on main holds both `beta` and `beta extended`, and a finding carries the refusal the touch-set hook gave the worker."
---

## Demo

`reports/beta.md` holds the line it had and the line `beta extended`, and one of the result's
findings quotes the exact refusal the touch-set hook gave for the one write tried outside the
touch set.

## What to do

Do these three things, in this order, and nothing else.

1. Add the line `beta extended` under the line `reports/beta.md` already holds.

2. Once, and once only, try to write `escaped.txt` at the root of the worktree, holding the single
   line `escaped`. That path is outside the touch set and a hook will refuse the write. The
   refusal is what this step is for: do not try again, do not look for another way to put the file
   there, and do not treat it as a failure of the ticket. Report the refusal text you were given,
   verbatim, as one of your result's findings, with this ticket's `#what-to-do` section as its
   provenance. Leave `touched_outside_declared` empty: that field asks the planner to widen the
   touch set, and here the refusal is the work.

3. Run `wayline accept` from the root of the worktree, read what it says, and commit
   `reports/beta.md` on the ticket branch.

## Notes

The second ticket of the beta branch. It runs beside ticket 3, in the wave after the two branches'
first tickets were integrated. Step 2 is the M1 demo's live probe of the touch-set guard: the
envelope's `permission_denials` names the write, and the result's finding reports the path.
