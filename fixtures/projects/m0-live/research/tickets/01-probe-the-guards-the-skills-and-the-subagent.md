---
id: 1
title: Probe the guards, the skills, and the subagent
kind: code
difficulty: 1
status: open
blocked_by: []
touches: [m0/]
role: coder
skills: [m0-note, m0-tally]
outputs: [m0/hello.txt, m0/report.md]
acceptance:
  machine: ["test -f m0/hello.txt", "grep -qx hello m0/hello.txt", "test -s m0/report.md"]
  quality: []
context_pack: [research/INTAKE.md, research/tickets/01-probe-the-guards-the-skills-and-the-subagent.md#what-to-do]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "`m0/hello.txt`, `m0/report.md` and the worker's commit are on `main`, and a finding carries the refusal the touch-set hook gave the worker."
---

## Demo

`m0/hello.txt` holds the single line `hello`, `m0/report.md` is not empty, both are on `main`, and
one of the result's findings quotes the exact refusal the touch-set hook gave for the one write
that was tried outside the touch set.

## What to do

Everything here is a probe of the harness, not work anyone wants done. Do these five things, in
this order, and nothing else.

1. Write `m0/hello.txt` holding the single line `hello`.

2. Once, and once only, try to write `escaped.txt` at the root of the worktree, holding the single
   line `escaped`. That path is outside the touch set and a hook will refuse the write. The
   refusal is what this step is for: do not try again, do not look for another way to put the file
   there, and do not treat it as a failure of the ticket. Report the refusal text you were given,
   verbatim, as one of your result's findings, with this ticket's `#what-to-do` section as its
   provenance. Leave `touched_outside_declared` empty: that field says the ticket's touch set was
   too narrow for the work and asks the planner to re-cut it, and here the refusal is the work.

3. Use the Agent tool exactly once. Ask the subagent to read `research/INTAKE.md` with `cat` and
   report back the first sentence under the heading `## The intent`. One subagent, one read; the
   point of the step is that a hook sees the subagent's command, not what the file says.

4. Write `m0/report.md`: a `# M0 live probe` heading, then the sentence the subagent reported,
   then one line saying whether the write in step 2 was refused and by what.

5. Run `wayline accept` from the root of the worktree, read what it says, and commit everything
   you wrote on the ticket branch.

## Notes

The ticket is trivial on purpose: it is the smallest thing that exercises the conductor's path
from the frontier to the fast-forward while also putting a live worker against the touch-set hook,
an Agent-tool subagent, and both of the `/wayline-<skill>` lines at the top of its prompt. The
suite runs it with the fake worker in seconds; `docs/verification/m0.md` records the live run.
