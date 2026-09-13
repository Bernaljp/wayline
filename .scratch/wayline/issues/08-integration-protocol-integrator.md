# 08 - Integration protocol and the integrator role

**What to build:** Two tickets that touched the same files integrate one after the other without corrupting `main`: integration is serialized, the ticket branch is rebased onto `main`, acceptance reruns on the rebased branch and again on `main` after the fast-forward, and when the rebase conflicts a fresh integrator session resolves it once before the ticket fails with a request to split. Ledger commits made by the conductor between waves never break the fast-forward.

**Blocked by:** 07 (Frontier, launchable subset, and two parallel workers), 09 (Resume from the journal, heartbeat, control events, and worker re-adoption; a sequencing edge added on 2026-09-12: all three M1 conductor tickets edit the same wave loop, and 09 rewrites the event replay that 08 and 10 extend)

**Status:** done

**GitHub:** [#9](https://github.com/Bernaljp/wayline/issues/9) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** Implementation Decisions 5 (integration protocol, escalation `next: split`), 1 (roles: integrator).

- [x] Integration runs one ticket at a time under the ledger lock: `git rebase main` in the worktree; on conflict, `git rebase --abort`, then the `integrator` role is launched once in the worktree with the conflicting paths as its touch set and the conflict markers as its context, then the rebase is retried; a second conflict journals `ticket_failed` with `next: split`.
- [x] After a clean rebase, acceptance reruns with `where: rebased`; `git merge --ff-only ticket/<id>` runs on `main`; acceptance reruns with `where: main`; `integrated` records the commit and `resolved_by`; the branch and the worktree are deleted.
- [x] `roles/integrator/` exists (agent.md, wayline.json) with a read-and-edit tool set limited to the conflicting paths.
- [x] The conductor's per-wave `ledger: wave <n>` commits land on `main` and a ticket branched before them still fast-forwards after its rebase (test).
- [x] Tests: the fake worker commits conflicting edits on two tickets with overlapping touch sets; a fake integrator resolves the conflict; the journal shows `resolved_by: integrator`; a second scripted conflict yields `next: split`.
- [x] A worker result with `touched_outside_declared` non-empty or `blocked_on` set marks the ticket `blocked` with the path and journals `ticket_blocked` (no integration is attempted).
