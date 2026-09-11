# 09 - Resume from the journal, heartbeat, control events, and worker re-adoption

**What to build:** A conductor killed at any moment is resumed by `wayline run --resume` through the same code path as a start: the journal is replayed into the conductor's working view, live workers are re-adopted by pid and stream file, dead workers are resumed by session id or relaunched, and nothing is lost. The conductor writes a heartbeat, two conductors cannot run on one project, and the owner steers a running conductor with `pause`, `resume`, `stop`, `stop --drain`, `cancel <id>`, `rerun <id>`, `answer <id>`, and `switch`, all of which are journal events the conductor applies at its next wave.

**Blocked by:** 07 (Frontier, launchable subset, and two parallel workers)

**Status:** ready-for-agent

**Milestone:** M1 Frontier and windows. **Spec:** Implementation Decisions 2 (the journal is the bus), 5 (process, resume, termination), 1 (the command).

- [ ] Replay from byte zero rebuilds statuses, attempts, session ids, pids, jobs, the pause, pacing, and the stall counter; replaying twice yields the same view (test); a hand edit of `pinned_difficulty` or a `## Answer` section in a ticket file wins over the journal on reconcile.
- [ ] On resume, a `ticket_launched` without a `ticket_result`: if the pid is alive, the conductor re-adopts it by tailing its `stream.jsonl` for the final result; if dead and `ticket_session` was seen, it resumes by session id; otherwise it relaunches; each case journals `ticket_resumed` with its reason.
- [ ] The heartbeat `research/conductor.json` (`pid, started_at, last_wave_at, harness_tag`) is written every poll; `flock` on it prevents a second conductor on the same project.
- [ ] The conductor remembers its journal offset and applies events appended by other processes since the last wave: `control` (`pause`, `resume`, `stop`, `stop` with `drain`, `cancel`, `rerun`, `autonomy`, `pacing`), `decision`, `feedback`, `switched`; the verbs `wayline pause | resume | stop [--drain] | cancel <id> | rerun <id> | answer <id> "<text>"` append them; `answer` also appends `## Answer` to the ticket file and journals `decision` with `decided_by: human`.
- [ ] `switch` on a project with a live conductor journals `control stop drain`; the conductor stops launching, waits for running workers up to their budgets, journals `run_ended` with `switched`, and leaves jobs running.
- [ ] `fixtures/conductor/m1-kill-resume/` holds a recorded journal and ledger from a run killed mid-wave; the suite replays it and asserts the view; a second test kills the conductor process with SIGKILL during a slow fake worker and resumes it to a clean `frontier_empty`.
