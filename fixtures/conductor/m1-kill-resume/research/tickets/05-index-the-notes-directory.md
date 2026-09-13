---
id: 5
title: Index the notes directory
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [notes/]
role: coder
skills: []
outputs: [notes/INDEX.md]
acceptance:
  machine: ["test -f notes/INDEX.md", "grep -q alpha.md notes/INDEX.md"]
  quality: []
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`notes/INDEX.md` on main names every file under `notes/`."
---

## Demo

`notes/INDEX.md` exists on `main` and names `alpha.md`.

## Notes

The conflicting ticket, and the point of the fixture. Nothing blocks it, so it is in the frontier
from the first wave; its touch set is the directory `notes/`, which is where tickets 1 and 3
write, so it is launchable only once both of them have been integrated. It could not pass its own
acceptance any earlier either: there is no `alpha.md` to index until ticket 1 lands.
