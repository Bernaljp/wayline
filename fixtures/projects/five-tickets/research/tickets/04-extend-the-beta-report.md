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
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`reports/beta.md` on main holds both `beta` and `beta extended`."
---

## Demo

`reports/beta.md` holds the line it had and the line `beta extended`.

## Notes

The second ticket of the beta branch. It runs beside ticket 3, in the wave after the two branches'
first tickets were integrated.
