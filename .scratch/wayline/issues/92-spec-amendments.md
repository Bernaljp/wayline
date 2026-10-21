# 92 - Spec amendments

**What to build:** An added or reframed objective gets a **spec amendment**: new work that traces to a claim, without rewriting anything already confirmed. When an "Objective changes" batch (ticket 91) approves an `add` or a `reframe`, the amendment runs in four steps:

1. One specify session, scoped to that objective, appends claims, experiments, metrics, and anti-claims under new ids and rewrites nothing.
2. The spec verifier judges the amendment only.
3. The planner cuts tickets for the new claims only.
4. When no Introduction passage with a `ref` tag covers the objective, a `lit` ticket follows.

Confirming the amendment depends on the autonomy:

- Under `checkpoints`, a "Confirm the amendment" decision ticket pauses only the new tickets, not the `blocking: all` graph gate.
- Under `interactive`, the conversation confirms.
- Under `autonomous`, the decider does.

Reopening a parked objective needs no amendment: its set-aside claims come back. Reopening an answered or dropped objective is the owner's alone. The old answer is kept as superseded, and the planner cuts fresh tickets for its claims.

`wayline specify --amend <objective>` runs the amendment. The conductor runs it after an approved batch, and the conversation runs it after the owner adds an objective once setup is done.

Not part of this ticket:

- the surveyor role and `scout search` that run the `lit` ticket (99); this ticket only cuts it;
- objective proposals and their batch (91).

**Blocked by:** 91 - Objective changes. It blocks 99.

**Status:** done

**GitHub:** [#239](https://github.com/Bernaljp/wayline/issues/239) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("How objectives change as results come in": the spec amendment); decisions 1 (the verb table: `specify --amend`), 10 (specify, the spec verifier, the planner), 11 (the spec verifier); M8 criterion 2; user story 109.

- [x] An approved `add` or `reframe` starts one specify session scoped to that objective, which appends claims, experiments, metrics, and anti-claims under new ids. A Type-A check refuses an amendment that changes or removes anything already in the spec.
- [x] The spec verifier judges the amendment alone, and the planner cuts tickets for the new claims alone, tied to the objective.
- [x] When no Introduction passage with a `ref` tag covers the objective, the planner cuts a `lit` ticket for it.
- [x] Under `checkpoints`, a "Confirm the amendment" decision ticket pauses only the new tickets, and the rest of the run keeps going. Under `interactive` the conversation confirms, and under `autonomous` the decider does.
- [x] Reopening a parked objective restores its set-aside claims with no amendment. Reopening an answered or dropped one is refused unless it is the owner's word, keeps the old answer as superseded, and has the planner cut fresh tickets.
- [x] Tests:
  - the fake launcher for the scoped specify session, the verifier, and the planner;
  - replayed journals for an amendment under each autonomy, the checkpoints ticket pausing only the new tickets, and both kinds of reopen, idempotence included;
  - the append-only check as a Type-A function over two spec versions.
- [x] The verb table of decision 1 gains `specify --amend` in the same commit as the code.
- [x] `CHANGELOG.md` under `## Unreleased` describes spec amendments.
- [x] `python -m unittest` passes.
