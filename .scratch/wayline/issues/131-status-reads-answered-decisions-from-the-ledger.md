# 131 - Status reads answered decisions from the ledger

**What to build:** `wayline status`, the dashboard, and the chat's digests show a decision ticket as closed once its answer is journaled.

On the toy's live setup (ticket 122, `docs/verification/m8.md`), the decider confirmed the spec (decision on ticket 1, D16) at 11:20Z, and replay had ticket 1 `done`, but `wayline status` still listed #1 "Confirm the spec" in the frontier and among the open decision tickets, blocking all, until the conductor's first wave rewrote `graph.json` more than half an hour later. The setup session read that status and told the owner of an "anomaly". Answers recorded before a run (setup's confirmations, an owner's answer while the run is stopped) all leave this gap.

- The frontier and the open decision tickets that status, the dashboard, and the chat's digests show are computed from replay, as `decisions` already reads them, or the verb that journals a `decision` closes the ticket in `graph.json` under the ledger's lock.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#338](https://github.com/Bernaljp/wayline/issues/338) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 2 (replay), 8 (status and the dashboard); ticket 122's live record.

- [ ] Over a temporary project, a `decision` journaled with no conductor running drops its ticket from status's frontier and open decision tickets at once.
- [ ] `python -m unittest` passes.
