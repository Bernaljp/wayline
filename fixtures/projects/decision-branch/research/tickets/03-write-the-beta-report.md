---
id: 3
title: Write the beta report
kind: code
difficulty: 1
status: open
blocked_by: [2]
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

`reports/beta.md` on `main` holds the line `beta`.

## Notes

Waits on decision ticket 2, so it launches only once that ticket is answered.
