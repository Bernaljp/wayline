---
id: 1
title: Write the hello file
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [hello.txt]
role: coder
skills: []
outputs: [hello.txt]
acceptance:
  machine: ["test -f hello.txt", "grep -qx hello hello.txt"]
  quality: []
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`test -f hello.txt` and `grep -qx hello hello.txt` both pass on main."
---

## Demo

`hello.txt` exists on `main` and holds the single line `hello`.

## Notes

The whole point of this ticket is to be trivial: it is the smallest thing that exercises the
conductor's path from the frontier to the fast-forward, so that the path can be tested in
seconds and demoed from a shell.
