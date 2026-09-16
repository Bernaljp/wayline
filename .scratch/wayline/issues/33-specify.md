# 33 - Specify

**What to build:** From the decisions, the position memo, and the knowledge base, the harness drafts the research spec with claims and anti-claims, methods, experiments per claim, baselines, data, metrics, success criteria, budgets, out of scope, risks, and seams; code checks its structure, one independent verdict checks that every claim has an experiment and every experiment defends a claim, and under `checkpoints` the owner confirms it before planning.

**Blocked by:** 31 (The decider), 32 (Type-B verdicts: the verifier role and gates)

**Status:** done

**GitHub:** [#34](https://github.com/Bernaljp/wayline/issues/34) (mirror; the local file is the source)

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (specify), 11 (verdicts); BRIEF 6.1 P3.

- [x] `wayline specify` launches the planner role in its specify protocol through the launcher with `DECISIONS.md`, `POSITION.md`, `GOAL.json`, and the query pack, and renders `SPEC.md` from the validated draft with the required sections.
- [x] Type-A checks: every section present, every claim has at least one experiment id, every experiment names a claim, every metric names a script, every anti-claim names the experiment that would confirm it; a failing check returns the draft to the planner once with the failures.
- [x] The verdict gate asks the verifier whether every claim has an experiment and every experiment defends a claim; a fail returns the draft once with the findings.
- [x] Under `checkpoints` a `blocking: all` decision ticket "confirm the spec" is opened and the phase advances on its answer; under `autonomous` the decider answers it; under `interactive` the owner is asked in the session.
- [x] Tests use the fake launcher and a fixture decision log; live: `SPEC.md` for the toy intent passes its checks and its verdict.
