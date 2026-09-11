# 34 - Plan: the planner, plan-time checks, and ticket assignment

**What to build:** The spec becomes an executable graph: the planner cuts tickets with a demo, machine acceptance, a touch set, a difficulty by the rubric, a context pack, and a decision ticket wherever a choice remains; the librarian assigns a role and skills to each from the registry; code checks that the graph is a DAG, that every field is present, that no machine criterion already passes at the base commit, and that every code ticket adding public API is followed by a docs ticket. The planner also re-cuts on request: a replan ticket after a stall and a split after a failed escalation.

**Blocked by:** 27 (Skills, the registry, and the librarian), 33 (Specify)

**Status:** ready-for-agent

**GitHub:** [#35](https://github.com/Bernaljp/wayline/issues/35) (mirror; the local file is the source)

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (plan), 2 (ticket files), 5 (escalation `split`, stall `replan`); BRIEF 8.2 to 8.4.

- [ ] `roles/planner/` exists (fable, xhigh); `wayline plan` and the `wayline-plan` skill launch it with `SPEC.md`, the query pack, the registry, and the journal, validate every ticket against the `ticket` schema, write `tickets/NN-slug.md` in the flat YAML subset, and regenerate `graph.json`.
- [ ] The librarian assigns `role` and `skills` to every ticket and the assignments are journaled.
- [ ] Plan-time Type-A checks: a DAG; every ticket has `demo`, `acceptance.machine`, `touches` under the project, `difficulty` 1 to 5, `context_pack`, `role`, `skills`; no machine criterion passes when run at the base commit; every `code` ticket that adds public API (declared by the planner) is followed by a `docs` ticket; a failing check returns the graph to the planner once with the failures.
- [ ] Decision tickets are created with the question, options, recommended answer, evidence, `blocking`, and `human_only` wherever the planner reports an open choice.
- [ ] Under `checkpoints` a `blocking: all` decision ticket "confirm the graph" gates execution; under `autonomous` the decider answers it.
- [ ] `wayline plan --replan` reads the journal and the failures and re-cuts open tickets; `wayline plan --split <id>` replaces one ticket with smaller ones that inherit its blockers and dependents; both are what the conductor calls from ticket 38.
- [ ] Tests use the fake launcher and the plan-time checks on hand-written good and bad graphs; live: the toy spec becomes a graph with roles and skills assigned.
