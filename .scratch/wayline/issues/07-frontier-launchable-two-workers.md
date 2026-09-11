# 07 - Frontier, launchable subset, and two parallel workers

**What to build:** The conductor schedules a real graph: it computes the frontier (open tickets whose blockers are done or accepted, with the difficulty-5 and decision-ticket rules), removes touch-set conflicts and unavailable resources to get the launchable subset, picks by critical path, goal relevance, difficulty, and id, and runs up to `max_parallel_workers` at once. On a five-ticket fixture graph with two independent branches and one touch-set conflict, two fake workers run in parallel and the conflicting ticket waits until the ticket it conflicts with is integrated.

**Blocked by:** 05 (The conductor's M0 path with the fake worker)

**Status:** ready-for-agent

**Milestone:** M1 Frontier and windows. **Spec:** Implementation Decisions 5 (wave steps 7 to 9, context packs), 14 (`max_parallel_workers`, `context_pack.max_chars`).

- [ ] The frontier is open tickets whose blockers are all `done` or `accepted`, where a difficulty-5 blocker counts only when `accepted`, minus tickets blocked by an open decision ticket with `blocking: subgraph`, minus everything while a `blocking: all` decision ticket is open (decision tickets are a kind the schema already knows; the answer paths arrive with ticket 35).
- [ ] The launchable subset removes tickets whose touch set intersects a running ticket's touch set (directory entries match below, file entries match exactly) and tickets whose job resources are not free (a stub that reports everything free until ticket 16).
- [ ] Pick order is critical-path length, then presence of `goal_metric`, then lower difficulty when pacing says `cheap_only`, then difficulty, then id; up to `policy.max_parallel_workers` run at once; each launch journals `ticket_launched` with `context_chars` and `prompt_sha256`.
- [ ] The context pack is cut at `policy.context_pack.max_chars[<tier>]` with the cut announced in the prompt; the initial caps of Implementation Decisions 14 are in `policy.json`.
- [ ] `fixtures/projects/five-tickets/` holds the M1 graph (two independent branches, one touch-set conflict); the test suite runs it with two fake workers and asserts, from the journal, that two tickets ran concurrently and that the conflicting ticket launched only after `integrated` for the ticket it conflicts with.
- [ ] `WAYLINE_LAUNCHER=fake wayline run` on that fixture closes all five tickets and ends with `frontier_empty`.
