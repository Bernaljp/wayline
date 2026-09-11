# 36 - M4 live demo: from a vague intent to a graph with roles and skills

**What to build:** The M4 demo, live: from a vague intent plus references and a goal, intake, the position memo with feasibility, a tiered grill with facts looked up, a decision ticket that pauses a branch and is answered from the dashboard and from the command line, the switch flipped mid-way, the decider resolving the rest with rationale, a spec, and a graph with roles and skills assigned from the registry.

**Blocked by:** 29 (The position memo), 34 (Plan: the planner, plan-time checks, and ticket assignment), 35 (Decision tickets end to end and dashboard actions)

**Status:** ready-for-agent

**Milestone:** M4 Front door. **Spec:** milestone M4 as a whole; Implementation Decisions 10.

- [ ] Starting from a one-paragraph intent, the ten references of M3, and a goal, the owner runs intake, position, grill (raising the switch mid-way), and plan in one sitting, and every artifact (`INTAKE.md`, `GOAL.json`, `POSITION.md`, `DECISIONS.md` with human and decider entries, `CONTEXT.md`, `SPEC.md`, `tickets/`, `graph.json`, `registry.json`) is present and valid.
- [ ] The decider's decisions carry rationale and confidence, are labeled `decided-by: decider`, and are listed first in `status` and the dashboard; none touches the irreversible list.
- [ ] The graph's plan-time checks pass and every ticket has a role and skills from the registry.
- [ ] `docs/verification/m4.md` records the session, the decision ticket's two answer paths, and the time spent; the repository is tagged `v0.5.0`.
