# Wayline tickets: what can run in parallel, and what waits

Computed from the 100 blocking edges of the 53 tickets: 98 from the spec on 2026-09-11, plus two sequencing edges added on 2026-09-12 (08 and 10 wait for 09, because all three edit the conductor's wave loop and 09 rewrites the event replay the other two extend). The model and effort to implement each ticket are in `.scratch/wayline/models.md`. Ticket NN is GitHub issue NN+1 in `Bernaljp/wayline`; the local file under `.scratch/wayline/issues/` is the source, the issue is the mirror.

## The rule

A ticket can start when every ticket in its **Blocked by** line is done: its commit is on `master`, `python -m unittest` passes there, its local `Status:` line is updated, and its GitHub issue is closed. Tickets in the same wave never depend on each other, so any subset of a wave can run at the same time. A ticket may also start as soon as its own blockers are done, even if the rest of its wave is not; the waves below are the earliest start, not a required batch.

## Waves (earliest start)

| Wave | Tickets | Notes |
|---|---|---|
| 1 | 01 (M0, #2) | The foundation. Nothing else can start. |
| 2 | 02 (M0, #3), 03 (M0, #4), 04 (M0, #5) | Three independent slices on top of 01: init, the launcher, the guards. |
| 3 | 05 (M0, #6), 11 (M1, #12), 16 (M2, #17), 18 (M2, #19), 20 (M3, #21) | First wide wave: the conductor, the dashboard, resources, the manifest, the scout are in different modules and merge cleanly. |
| 4 | 06 (M0, #7), 07 (M1, #8), 12 (M1, #13), 17 (M2, #18), 21 (M3, #22), 23 (M3, #24), 25 (M3, #26), 27 (M4, #28), 32 (M4, #33), 48 (M7, #49), 52 (M7, #53) | Widest wave. 06 is the M0 live demo; the rest fan out across M1 to M7. |
| 5 | 09 (M1, #10), 19 (M2, #20), 22 (M3, #23), 28 (M4, #29), 40 (M5, #41), 42 (M5, #43), 49 (M7, #50) | 09 is the resume ticket, at max; the six others live in other modules and run beside it. 08 and 10 wait for 09 (wave 6). 19 is the M2 demo: it runs after 15 (rule 7), at no calendar cost. |
| 6 | 08 (M1, #9), 10 (M1, #11), 13 (M1, #14), 24 (M3, #25), 30 (M4, #31), 39 (M5, #40), 41 (M5, #42), 44 (M6, #45) | 08 and 10 both edit the conductor on top of 09: one after the other, or together and expect one real merge plus a suite run. |
| 7 | 14 (M1, #15), 26 (M3, #27), 31 (M4, #32), 46 (M6, #47) | 26 is the M3 demo: it runs after 19 (rule 7). |
| 8 | 15 (M1, #16), 29 (M4, #30), 33 (M4, #34), 35 (M4, #36), 37 (M5, #38) | 15 closes M1, and the demos 19 and 26 follow it (rule 7); 33 and 34 (M4) sit on the critical path. |
| 9 | 34 (M4, #35) | 34 is the planner; five later tickets wait on it. |
| 10 | 36 (M4, #37), 38 (M5, #39), 45 (M6, #46) | 36 is the M4 demo: alone on `master` first. 38 and 45 both touch the conductor loop: 38 first (43 needs it), then 45, or together and expect a merge. |
| 11 | 43 (M5, #44) | 43 is the overnight run; it needs a real night. |
| 12 | 47 (M6, #48), 50 (M7, #51), 51 (M7, #52) |  |
| 13 | 53 (M7, #54) | The last ticket. |

## The critical path

01 -> 02 -> 05 -> 27 -> 28 -> 30 -> 31 -> 33 -> 34 -> 36 -> 43 -> 50 -> 53 (13 tickets in a row). This chain sets the calendar: every other ticket can fill in around it. Keep one session on the next critical-path ticket at all times.

## Per ticket: what it waits for and what it unblocks

| Ticket | Issue | Wave | Waits for | Unblocks |
|---|---|---|---|---|
| 01 Package skeleton, frontmatter parser, schema validator, ledger core | #2 | 1 | nothing | 02, 03, 04 |
| 02 init lays out a project and status reads it | #3 | 2 | 01 | 05, 11, 16, 18, 20 |
| 03 Worker launcher seam with fake and claude_cli backends | #4 | 2 | 01 | 05, 23, 44 |
| 04 Guards, per-launch settings, and accept | #5 | 2 | 01 | 05 |
| 05 The conductor's M0 path with the fake worker | #6 | 3 | 02, 03, 04 | 06, 07, 27, 32 |
| 06 M0 live: one trivial ticket end to end (verbatim prototype 16) | #7 | 4 | 05 | 15 |
| 07 Frontier, launchable subset, and two parallel workers | #8 | 4 | 05 | 08, 09, 10, 19, 35, 37 |
| 08 Integration protocol and the integrator role | #9 | 6 | 07, 09 | 15, 38 |
| 09 Resume from the journal, heartbeat, control events, and worker re-adoption | #10 | 5 | 07 | 08, 10, 13, 15, 44 |
| 10 Pacing and pause on usage limits | #11 | 6 | 07, 09 | 14, 15 |
| 11 Read-only dashboard: transport, tabs, journal tail, overview (verbatim prototype 36) | #12 | 3 | 02 | 12, 13 |
| 12 Dashboard graph, ticket pages, and logs endpoints | #13 | 4 | 11 | 15, 35, 42 |
| 13 User units, run --detach, and the notifier | #14 | 6 | 09, 11 | 14 |
| 14 The tick (verbatim prototype 29) | #15 | 7 | 10, 13 | 15, 35, 43 |
| 15 M1 live demo: five tickets, a killed conductor, a simulated limit, the tick, the dashboard | #16 | 8 | 06, 08, 09, 10, 12, 14 | nothing (a milestone demo) |
| 16 Resources detection and slots | #17 | 3 | 02 | 17 |
| 17 Job runner seam (verbatim prototype 27) | #18 | 4 | 16 | 19, 41 |
| 18 Manifest and findings provenance | #19 | 3 | 02 | 19, 40 |
| 19 Experiment and analysis tickets end to end (M2 demo) | #20 | 5 | 07, 17, 18 | 39 |
| 20 Fetch seam, scout, L0 records, and the knowledge base | #21 | 3 | 02 | 21, 23, 25, 48, 52 |
| 21 arXiv e-print sources and the LaTeX inventory | #22 | 4 | 20 | 22 |
| 22 Non-arXiv PDF inventory chain and the tools venv (verbatim prototype 30) | #23 | 5 | 21 | 24 |
| 23 L1 skims, reading budgets, and promotion triggers | #24 | 4 | 03, 20 | 24 |
| 24 The absorb workflow for L2 | #25 | 6 | 22, 23 | 26 |
| 25 Code dossiers | #26 | 4 | 20 | 26 |
| 26 The consultant and the M3 demo | #27 | 7 | 24, 25 | 29 |
| 27 Skills, the registry, and the librarian | #28 | 4 | 05 | 28, 34, 46 |
| 28 Intake and the goal | #29 | 5 | 27 | 29, 30, 35, 39, 41 |
| 29 The position memo | #30 | 8 | 26, 28 | 36 |
| 30 The grill and the autonomy switch | #31 | 6 | 28 | 31 |
| 31 The decider | #32 | 7 | 30 | 33, 37 |
| 32 Type-B verdicts: the verifier role and gates | #33 | 4 | 05 | 33, 40, 50 |
| 33 Specify | #34 | 8 | 31, 32 | 34 |
| 34 Plan: the planner, plan-time checks, and ticket assignment | #35 | 9 | 27, 33 | 36, 38, 45, 51 |
| 35 Decision tickets end to end and dashboard actions | #36 | 8 | 07, 12, 14, 28 | 36 |
| 36 M4 live demo: from a vague intent to a graph with roles and skills | #37 | 10 | 29, 34, 35 | 43 |
| 37 Proposals admission | #38 | 8 | 07, 31 | 43 |
| 38 Stall detection and the escalation chain | #39 | 10 | 08, 34 | 43 |
| 39 Keep-if-better under a quantitative goal | #40 | 6 | 19, 28 | 43 |
| 40 Provenance tags, the linter, and REPORT.md | #41 | 5 | 18, 32 | 43, 53 |
| 41 The toy project fixture | #42 | 6 | 17, 28 | 43 |
| 42 Dashboard outputs, downloads, and logs | #43 | 5 | 12 | 43, 45 |
| 43 M5 overnight demo: the toy project end to end across a window boundary | #44 | 11 | 14, 36, 37, 38, 39, 40, 41, 42 | 47, 50, 51 |
| 44 Fixture format and runner (verbatim prototype 32) | #45 | 6 | 03, 09 | 45, 46 |
| 45 Feedback, change records, harness tickets, and local skills | #46 | 10 | 34, 42, 44 | 47 |
| 46 Tags, pins, upgrade, rollback, and promotion | #47 | 7 | 27, 44 | 47 |
| 47 M6 demo: feedback to a tagged harness change and back | #48 | 12 | 43, 45, 46 | nothing (a milestone demo) |
| 48 The plot index | #49 | 4 | 20 | 49 |
| 49 Figure machine checks, schemas, and the house style | #50 | 5 | 48 | 50 |
| 50 The figure role pipeline end to end | #51 | 12 | 32, 43, 49 | 53 |
| 51 The documentation site | #52 | 12 | 34, 43 | 53 |
| 52 Venue guidelines | #53 | 4 | 20 | 53 |
| 53 The paper and the M7 demo | #54 | 13 | 40, 50, 51, 52 | nothing (a milestone demo) |

## Running tickets in parallel without corrupting git

`implement` commits to the current branch of the checkout it runs in. It creates no branch, opens no pull request, and closes nothing. Two `implement` sessions in one checkout share one index and one HEAD and corrupt each other (the skill's own docs report amended commits landing on the wrong session and vanished stashes). So:

1. One session, one ticket, one git worktree. A new agent created from `claude agents` gets one by default (`worktree.bgIsolation` is `auto`): `.claude/worktrees/<name>` on branch `worktree-<name>`, branched from origin's `master`. From a terminal, `claude -w ticket-NN --model <alias> --effort <effort>` does the same. Give the session `/implement` with the full path of the ticket file (or the issue URL) and ask it to confirm the title back before it starts. The manual route still works: `git worktree add -b ticket/NN .worktrees/NN master` (the `.worktrees/` directory is ignored), then start Claude Code inside it.
2. When the agent reports done, it has opened a pull request against `master` (`CLAUDE.md` tells every session to: criteria ticked, `Status: done`, `Closes #<issue>` in the body). Read it on GitHub, wait for the `tests` check, and merge it with a merge commit (the repository allows no other kind, so a tag made on the branch stays on `master`'s line; the remote branch is deleted by the merge). The merge closes the issue, so every dependent's blocked-by count updates on its own.
3. Then locally: `git pull` on `master` (a new worktree branches from origin's `master`, which the merge already updated, but anything you run on `master` itself needs the pull), and run the sweep under "Removing ended sessions" below, which deletes the ended sessions with their worktrees and local branches (`git worktree remove .worktrees/NN` for a manual worktree). If other pull requests are open, also run the script under "Bringing the next pull request up to master": a merge on GitHub re-conflicts every open pull request that touches the same lines, and there are lines every ticket touches.
4. Never use `git stash` across worktrees; `refs/stash` is shared.
5. Keep two or three sessions in flight at most: the subscription window is shared by every session, and one ticket typically costs a large part of a window.
6. Run 01 to 05 one at a time on `master` directly (no worktree needed while nothing else runs): they define the modules everything else edits.
7. The eight milestone demos (06, 15, 19, 26, 36, 43, 47, 53) are integration points: run each alone, on `master`, with the tree clean, and in milestone order, so that every tag from v0.1.0 to v1.0.0 contains the code of the tags before it (`upgrade` moves a project between tags and prints the changelog between them, which needs a straight line). 19 and 26 therefore wait for 15 (wave 8), and 39 and 29 wait for them; this costs no calendar time, since none of the four is on the critical path. The schedule that follows these rules step by step is the order column of `.scratch/wayline/models.md`.
8. Same-module pairs: 09 before 08 and 10 (recorded as blocked-by edges, so the frontier query holds 08 and 10 until 09 closes), and 38 before 45 in wave 10 (a note only). Running such a pair together is allowed at the price of one real merge and a suite run on `master` afterwards; if the merge conflicts, start a session at the repo root and use `/resolving-merge-conflicts`.

### Removing ended sessions

No session id to look up: `bash .scratch/wayline/sweep-sessions.sh` fetches, then removes every ended background session of this repository whose worktree branch is merged into origin's `master`, with its worktree and local branch. It keeps and names everything else: a session still working; a branch not yet merged (its pull request is open, and `claude attach <id>` can still reopen the session for a fix); a worktree with uncommitted changes or unpushed commits (`claude rm` refuses those itself and prints the flag that discards them). An ended session that is still open in a terminal, or was cleared with `/clear`, is removed like any other. Run it after merging, from anywhere in the repository:

```
bash .scratch/wayline/sweep-sessions.sh
```

A single session is `claude rm <id>`, the id being the short hex printed when the session started and listed by `claude agents --json --all`. Keep a session until its pull request is merged, so `claude attach <id>` can reopen it for a fix.

### Bringing the next pull request up to master

Every ticket appends to the same lines: the `SHIPPED` list of the schema tests, the changelog's Unreleased section, the verb table. So when several pull requests are open at once, merging one on GitHub re-conflicts the rest. Merge them oldest first, the lowest number, and after each merge run:

```
bash .scratch/wayline/update-next-pr.sh
```

It merges origin's `master` into the oldest open pull request's branch in a temporary worktree, pushes, and stops there; the `tests` check runs on the push, and the pull request is ready to merge when that check is green. A conflict resolved once is resolved the same way again by git rerere, from the resolutions recorded in the repository's `.git/rr-cache`; the resolutions for the pull requests open on 2026-09-12 were recorded in their merge order, which is why the script has answers at all. A conflict with no recorded resolution is left alone and named, for a person to resolve in that branch's worktree: `git merge origin/master`, edit, commit, push. A textual merge can still hide a collision of meaning that only the suite reports: a role sidecar written before ticket 27 landed carried fields the registry now refuses, and the merge said nothing. Read the check, not the merge.

## Sequential alternative

If you would rather not manage worktrees, work the waves top to bottom on `master`, one `/implement` per fresh session with `/clear` between, closing each issue as it lands. Nothing is lost except calendar time.

## What is ready right now

```
gh api "repos/Bernaljp/wayline/issues?state=open&labels=ready-for-agent&per_page=100" \
  --jq '.[] | select(.issue_dependencies_summary.blocked_by == 0) | "#\(.number) \(.title)"'
```

That prints the frontier: open tickets with no open blocker, which is exactly the set you can dispatch. It shrinks and grows as issues close.

## Close-out checklist per ticket

- [ ] pull request read, `tests` check green, merge commit made on GitHub (the merge closes the issue and deletes the remote branch)
- [ ] the ticket file in the pull request has `Status: done` and every criterion ticked; an unticked one is named in the body, decide whether it blocks
- [ ] `git pull` on local `master`; the session sweep ("Removing ended sessions")
- [ ] other pull requests still open: `bash .scratch/wayline/update-next-pr.sh`, then its `tests` check
- [ ] if it was a milestone demo: `docs/verification/mN.md` in the pull request and the tag pushed (`git push --tags`)
