# 140 - Four small things the toy run showed

**What to build:** Four smaller faults the toy's live run showed (ticket 122, `docs/verification/m8.md`), each fixed with its test.

- **The general report's render counts.** Every `report_rendered` for `REPORT.md` during the night said `claims: 0, tagged: 0, linter_pass: true`, while the report held 175 findings, each sentence carrying a `{res:…}` tag; a later render said `claims: 27`. The counts the event carries are what the account and the dashboard show of the linter's work, so they count the general report's own claim sentences and tags.
- **The GPU-hours reading.** `wayline status` read the GPU budget as 1.8 of 4 hours at 23:33, the chat's digest said 1.3 a minute later, and status said 1.45 half an hour after that. A spent budget never goes down: the reading is computed one way everywhere, from the journal's job events, and grows monotonically.
- **A proposal refused as "goal".** At the empty frontier, the decider was refused parked proposal `c3a0b19879a6` ("E5: set the goal run's auroc beside E2's 20-seed mean inside E5's result") because "its answer falls in a class on the irreversible list (goal)", though the proposal writes an analysis and changes no measure; it became decision ticket 124, human-only, asked after setup under `autonomous`. The irreversible "goal" class covers changing a goal's measure or data, not work that mentions a goal.
- **A job that barely uses the GPU holds it whole.** The toy's sweeps used the RTX 3090 at 0% and 107 MiB each, yet each job reserved the whole card, so twelve jobs ran one at a time. A job may declare the GPU memory it needs (`resources.gpu_mem_gb`), and jobs whose declared needs fit share a card, under `reservations` and the OOM ladder as they stand.

**Blocked by:** None - can start immediately. The four parts touch different modules (`provenance`/`report`, `stopping`, the decider's refusal rules, `resources`) and may be split.

**Status:** ready-for-agent

**GitHub:** [#347](https://github.com/Bernaljp/wayline/issues/347) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 6 (jobs and resources), 9 (the provenance linter), 17 (budgets; the decider's limits; the account); ticket 122's live record.

- [ ] The general report's `report_rendered` counts its claim sentences and tags; a test over a fixture ledger.
- [ ] The GPU-hours reading is one function, monotone over a replayed journal.
- [ ] A proposal that changes no measure or data is not refused as "goal"; covered by the decider's refusal tests.
- [ ] Two jobs whose declared GPU memory fits launch on one card; covered with the fake job runner.
- [ ] `python -m unittest` passes.
