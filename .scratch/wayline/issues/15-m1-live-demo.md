# 15 - M1 live demo: five tickets, a killed conductor, a simulated limit, the tick, the dashboard

**What to build:** The M1 demo, live: a five-ticket graph with two independent branches and one touch-set conflict runs with two real workers; the conflict serializes; the hook blocks an out-of-touch-set write; a killed conductor resumes from the journal; a simulated usage-limit error pauses; the tick relaunches after the reset; and the read-only dashboard shows the tabs, the frontier, running tickets, and the journal tail through the tunnel. Context-pack sizes and outcomes are recorded so the caps in `policy.json` rest on a measurement.

**Blocked by:** 06 (M0 live: one trivial ticket end to end (verbatim prototype 16)), 08 (Integration protocol and the integrator role), 09 (Resume from the journal, heartbeat, control events, and worker re-adoption), 10 (Pacing and pause on usage limits), 12 (Dashboard graph, ticket pages, and logs endpoints), 14 (The tick (verbatim prototype 29))

**Status:** ready-for-agent

**Milestone:** M1 Frontier and windows. **Spec:** milestone M1 criteria 3 to 8, 10; Implementation Decisions 5, 14.

- [ ] The five-ticket project from `fixtures/projects/five-tickets/` runs live with `max_parallel_workers: 2`; the journal shows two tickets running concurrently and the conflicting ticket launched only after its counterpart was integrated; if the pair produces a real git conflict, the integrator resolves it live.
- [ ] One ticket asks the worker to write outside its touch set; the envelope's `permission_denials` names the write, the result reports the path, and both are in the journal.
- [ ] The conductor is killed with SIGKILL mid-wave and `wayline run --resume` brings every ticket to `done` with the re-adoption or resume path journaled.
- [ ] `wayline run --simulate-limit 300` pauses the run with `resets_at`; the tick (at one-minute cadence for the test) relaunches it after the reset and the journal shows `run_started` with `resume: true` written by the tick's launch.
- [ ] The dashboard is opened through `ssh -L` from the laptop during the run and shows the tabs, the frontier, the running tickets, and the journal tail.
- [ ] `docs/verification/m1.md` records the context-pack sizes per launch, the first-time pass outcomes, and the caps kept or revised in `policy.json`, plus the commands and journal excerpts for each step above; the repository is tagged `v0.2.0`.
