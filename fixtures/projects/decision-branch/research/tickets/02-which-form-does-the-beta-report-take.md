---
id: 2
title: Which form does the beta report take?
kind: decision
difficulty: 1
status: open
blocked_by: []
blocking: subgraph
human_only: false
touches: []
role: decider
skills: []
acceptance: {}
context_pack: [research/INTAKE.md]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "The owner or the decider answers: Which form does the beta report take?"
---

## Decision

Which form does the beta report take?

- options:
  - one line
  - a table
- recommended: one line
- evidence:
  - research/INTAKE.md asks for a report a person reads at a glance
  - tickets 3 and 5 write the report, so either form is one ticket's work
- blocking: `subgraph`, so ticket 3 and whatever waits on it wait for the answer
- human-only: no, so under autonomy `autonomous` the decider may answer it
- asked by: research/INTAKE.md#the-intent

<!-- wayline:decision {"ticket":2,"question":"Which form does the beta report take?","options":["one line","a table"],"recommended":"one line","evidence":["research/INTAKE.md asks for a report a person reads at a glance","tickets 3 and 5 write the report, so either form is one ticket's work"],"human_only":false,"reversible":true,"answer":null,"rationale":null,"confidence":null,"decided_by":null,"timestamp":null,"blocking":"subgraph"} -->

## How to answer

`wayline answer 2 "<answer>"`, from the command line or from a session; the answer form in the dashboard's decisions view; or the answer written under an `## Answer` heading at the end of this file. Each is journaled as the owner's decision, and the conductor closes this ticket at its next wave.
