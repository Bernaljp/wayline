---
id: 1
title: Write the alpha note
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [notes/alpha.md]
role: coder
skills: []
outputs: [notes/alpha.md]
acceptance:
  machine: [test -f notes/alpha.md, grep -qx alpha notes/alpha.md]
  quality: []
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`notes/alpha.md` on main holds the line `alpha`."
---

## Demo

`notes/alpha.md` on `main` holds the line `alpha`.

## Notes

The alpha branch, which no decision holds: it runs while the beta branch waits for the owner.
