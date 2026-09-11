# 45 - Feedback, change records, harness tickets, and local skills

**What to build:** The owner says what should have gone better, from the dashboard, the command line, or a file, and the harness changes itself under test: each item becomes a change record with journal evidence and the fixture that will prove it, each record becomes a harness ticket that runs through the conductor, a local change is applied at once and used from the next wave (including a model-authored skill that the librarian starts assigning), a global change lands on a harness branch with the tests and the fixture suite green, and under `autonomous` a global change is proposed in the report rather than applied.

**Blocked by:** 34 (Plan: the planner, plan-time checks, and ticket assignment), 42 (Dashboard outputs, downloads, and logs), 44 (Fixture format and runner (verbatim prototype 32))

**Status:** ready-for-agent

**Milestone:** M6 Evolve. **Spec:** Implementation Decisions 12 (intake, change records, application), 10 (registry, model-authored skills), 4 (global changes are irreversible); BRIEF 12.

- [ ] `wayline evolve "<text>"`, the dashboard's feedback form (a new action and view), and files dropped in `research/feedback/` each journal `feedback` with the source; after every `run_ended` the evolver runs a retrospective over the journal (failures, escalations, stalls, rework, turns per closed ticket, skills below the registry's median first-time pass rate).
- [ ] `roles/evolver/` (fable, xhigh) turns feedback and the retrospective into change records under the `change` schema (`id, observed: {text, journal_events[]}, desired, mechanism, scope_kind, risk, fixture, status`), journaled as `change_record`.
- [ ] Code files one `harness` ticket per record through the conductor: a local change's touch set is the project's `.claude/skills/<name>/`, `.claude/agents/<role>.md`, or `harness.json`; a global change's touch set is a path in the harness repository on the branch `evolve/<id>` checked out as a worktree of the harness repository.
- [ ] A local change is used from the next wave: the registry is rebuilt at every planner launch and the conductor rereads `harness.json` every wave; a model-authored skill ships `SKILL.md`, `wayline.json`, and a fixture, and becomes assignable only when the fixture passes; the journal shows the librarian assigning it.
- [ ] A global change runs the harness tests and the full fixture suite on its branch and waits for the owner to integrate it into the harness `main` (ticket 46 tags); under `autonomous` the change is written into `REPORT.md` as a proposal and nothing is applied (test).
- [ ] A fixture born from feedback encodes the desired behavior and the runner shows it failing on the old subject before the harness ticket is accepted.
- [ ] Tests use the fake launcher for the evolver and the conductor path for a local and a global change; live: "tickets too big" and "captions overclaim" filed from the dashboard on the M5 run become change records and harness tickets.
