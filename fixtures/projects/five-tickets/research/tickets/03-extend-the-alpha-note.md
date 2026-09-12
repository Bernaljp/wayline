---
id: 3
title: Extend the alpha note
kind: code
difficulty: 1
status: open
blocked_by: [1]
touches: [notes/alpha.md]
role: coder
skills: []
outputs: [notes/alpha.md]
acceptance:
  machine: ["grep -qx alpha notes/alpha.md", "grep -qx 'alpha extended' notes/alpha.md"]
  quality: []
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`notes/alpha.md` on main holds both `alpha` and `alpha extended`."
---

## Demo

`notes/alpha.md` holds the line it had and the line `alpha extended`.

## Notes

The second ticket of the alpha branch, so ticket 1 is on the longer critical path and the pick
order puts it before the ticket nothing waits on.
