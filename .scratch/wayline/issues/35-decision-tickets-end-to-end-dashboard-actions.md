# 35 - Decision tickets end to end and dashboard actions

**What to build:** A decision ticket pauses exactly its subgraph while unrelated branches and jobs continue, the owner is notified and answers it from the dashboard form, the command line, the ticket file, or a session, the answer is journaled as a human decision, the subgraph unblocks, and the tick relaunches a stopped conductor. The dashboard grows its first actions, all routed through the CLI functions with the action token: answer, autonomy, pause, resume, switch, cancel, rerun, pacing, and an intake drop zone.

**Blocked by:** 07 (Frontier, launchable subset, and two parallel workers), 12 (Dashboard graph, ticket pages, and logs endpoints), 14 (The tick (verbatim prototype 29)), 28 (Intake and the goal)

**Status:** ready-for-agent

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 5 (decision tickets), 8 (actions, views), 7 (tick relaunch conditions); BRIEF 6.6.

- [ ] A decision ticket created by the planner or from a worker's `decision_requests` carries the question, options, recommended answer, evidence, `blocking: subgraph | all`, and `human_only`; its creation journals `decision_opened` and notifies; the frontier rule of ticket 07 holds it and its dependents while open.
- [ ] Answer paths: `wayline answer <id> "<text>"`; an edit of the ticket's `## Answer` section detected by the tick or the conductor from the scandir snapshot and journaled; the dashboard's answer form; an interactive session; each produces one `decision` event with `decided_by: human`, marks the ticket done, and unblocks the subgraph at the next wave; when no conductor is alive the tick relaunches it.
- [ ] `GET /api/projects/<id>/decisions` returns open decision tickets with options and evidence and the decision log with decider decisions first; `POST /api/projects/<id>/actions/<name>` implements `answer`, `autonomy`, `pause`, `resume`, `switch`, `cancel`, `rerun`, `pacing`, and `intake` (file drop into the intake), each calling the CLI function in-process, requiring the token header, and never running a shell.
- [ ] The page renders the decisions view with the answer form, the autonomy and pacing controls, the switch and pause and resume buttons, and the intake drop zone.
- [ ] Tests: a fixture graph with a `blocking: subgraph` decision ticket runs with the fake worker and shows the other branch progressing while the blocked one waits, then unblocking after an answer through each path; HTTP tests cover every action and the token.
- [ ] Live: a decision ticket pauses one branch of the toy graph and is answered once from the dashboard through the tunnel and once from `wayline answer`, both journaled, recorded in `docs/verification/m4.md`.
