---
id: 2
title: Write the beta report
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [reports/beta.md]
role: coder
skills: []
outputs: [reports/beta.md]
acceptance:
  machine: ["test -f reports/beta.md", "grep -qx beta reports/beta.md"]
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
