---
id: 2
title: Write the beta report
kind: code
difficulty: 1
status: done
blocked_by: []
touches: [reports/beta.md]
role: coder
skills: []
outputs: [reports/beta.md]
acceptance:
  machine: [test -f reports/beta.md, grep -qx beta reports/beta.md]
  quality: []
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`reports/beta.md` on main holds the line `beta`."
---

## Demo

`reports/beta.md` exists on `main` and holds the line `beta`.

## Notes

The first ticket of the beta branch. It shares no path with the alpha branch, which is what lets
the two branches run at once.

## Result

### Attempt 1

Wrote reports/beta.md holding the single line beta and committed it on the ticket branch.

Wrote: `reports/beta.md`

Ran: `wayline accept`
