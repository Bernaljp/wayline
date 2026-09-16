# 29 - The position memo

**What to build:** Before any decision is asked, a fresh critic that has read only the dossiers, the intake, and the goal tells the owner whether the idea makes sense: the closest prior work with citations the scout verified, a feasibility verdict with the stated compute and data, goal feasibility with a revised target when the stated one looks out of reach, the hostile reviewer's case, and three directions ranked by radius.

**Blocked by:** 26 (The consultant and the M3 demo), 28 (Intake and the goal)

**Status:** done

**GitHub:** [#30](https://github.com/Bernaljp/wayline/issues/30) (mirror; the local file is the source)

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (position), 1 (roles: critic); BRIEF 6.5.

- [x] `roles/critic/` exists (read-only tools; opus high by policy); `wayline position` launches it through the launcher with only the dossiers, `INTAKE.md`, and `GOAL.json` in its context and a schema for the memo.
- [x] `POSITION.md` is rendered by code from the validated memo with the closest-prior-work table (every row a citation the scout resolved to `existence: verified`, else dropped with a note), the feasibility verdict, the goal feasibility and any revised target, the hostile reviewer's objections, and three directions ranked by distance from the intent under the radius.
- [x] Under autonomy `autonomous` the memo is handed to the decider (ticket 31) instead of shown; otherwise `status` and the dashboard surface it first.
- [ ] Tests use the fake launcher; live: the memo for the M3 intake is produced and read by the owner.
