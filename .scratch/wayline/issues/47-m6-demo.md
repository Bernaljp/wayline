# 47 - M6 demo: feedback to a tagged harness change and back

**What to build:** The M6 demo, live: feedback on M5 ("tickets too big", "captions overclaim"), filed from the dashboard, becomes change records, harness tickets, fixtures, a local skill used in the next wave, and one promotion to the harness with a tag; the project is upgraded and rolled back once. The harness's own suite runs in under a minute with no subscription, GPU, or network.

**Blocked by:** 43 (M5 overnight demo: the toy project end to end across a window boundary), 45 (Feedback, change records, harness tickets, and local skills), 46 (Tags, pins, upgrade, rollback, and promotion)

**Status:** done

**GitHub:** [#48](https://github.com/Bernaljp/wayline/issues/48) (mirror; the local file is the source)

**Milestone:** M6 Evolve. **Spec:** milestone M6 as a whole; Implementation Decisions 12.

- [x] The two feedback items filed from the dashboard become two change records, two harness tickets, and two fixtures; the "captions overclaim" fixture fails on the old subject and passes after the change; the "tickets too big" change is a local planner override applied at once.
- [x] A model-authored local skill from one of the changes is registered, fixture-tested, and assigned by the librarian in the next wave of the toy project (journal excerpt).
- [x] One local skill is promoted to the harness with its fixtures, integrated, and tagged; the toy project is upgraded to the new tag and rolled back once, both journaled as `pinned`.
- [x] `python -m unittest` on the harness passes in under a minute with the network, the GPU, and the subscription unavailable (a test harness flag makes the real backends raise if touched).
- [x] `docs/verification/m6.md` records the fixture stability run, the deliberate break, and the promotion; the repository is tagged `v0.7.0`.
