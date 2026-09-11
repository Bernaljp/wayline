# Wayline tickets: what can run in parallel, and what waits

Computed from the 98 blocking edges of the 53 tickets on 2026-09-11. Ticket NN is GitHub issue NN+1 in `Bernaljp/wayline`; the local file under `.scratch/wayline/issues/` is the source, the issue is the mirror.

## The rule

A ticket can start when every ticket in its **Blocked by** line is done: its commit is on `master`, `python -m unittest` passes there, its local `Status:` line is updated, and its GitHub issue is closed. Tickets in the same wave never depend on each other, so any subset of a wave can run at the same time. A ticket may also start as soon as its own blockers are done, even if the rest of its wave is not; the waves below are the earliest start, not a required batch.

## Waves (earliest start)

| Wave | Tickets | Notes |
|---|---|---|
| 1 | 01 (M0, #2) | The foundation. Nothing else can start. |
| 2 | 02 (M0, #3), 03 (M0, #4), 04 (M0, #5) | Three independent slices on top of 01: init, the launcher, the guards. |
| 3 | 05 (M0, #6), 11 (M1, #12), 16 (M2, #17), 18 (M2, #19), 20 (M3, #21) | First wide wave: the conductor, the dashboard, resources, the manifest, the scout are in different modules and merge cleanly. |
| 4 | 06 (M0, #7), 07 (M1, #8), 12 (M1, #13), 17 (M2, #18), 21 (M3, #22), 23 (M3, #24), 25 (M3, #26), 27 (M4, #28), 32 (M4, #33), 48 (M7, #49), 52 (M7, #53) | Widest wave. 06 is the M0 live demo; the rest fan out across M1 to M7. |
| 5 | 08 (M1, #9), 09 (M1, #10), 10 (M1, #11), 19 (M2, #20), 22 (M3, #23), 28 (M4, #29), 40 (M5, #41), 42 (M5, #43), 49 (M7, #50) | M1's conductor features (08, 09, 10) all touch the conductor module: run them one at a time or expect merges. |
| 6 | 13 (M1, #14), 24 (M3, #25), 30 (M4, #31), 39 (M5, #40), 41 (M5, #42), 44 (M6, #45) |  |
| 7 | 14 (M1, #15), 26 (M3, #27), 31 (M4, #32), 46 (M6, #47) |  |
| 8 | 15 (M1, #16), 29 (M4, #30), 33 (M4, #34), 35 (M4, #36), 37 (M5, #38) | 15 closes M1; 33 and 34 (M4) sit on the critical path. |
| 9 | 34 (M4, #35) | 34 is the planner; five later tickets wait on it. |
| 10 | 36 (M4, #37), 38 (M5, #39), 45 (M6, #46) |  |
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
| 08 Integration protocol and the integrator role | #9 | 5 | 07 | 15, 38 |
| 09 Resume from the journal, heartbeat, control events, and worker re-adoption | #10 | 5 | 07 | 13, 15, 44 |
| 10 Pacing and pause on usage limits | #11 | 5 | 07 | 14, 15 |
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

1. One session, one ticket, one git worktree. From the harness root: `git worktree add -b ticket/NN .worktrees/NN master` (the `.worktrees/` directory is ignored), then start Claude Code in `.worktrees/NN` and run `/implement` with the full path of the ticket file (or the issue URL) and ask it to confirm the title back before it starts. Claude Code's `--worktree NN` flag does the same in one step.
2. When the session ends at its commit: from the harness root, `git merge --ff-only ticket/NN` (use a plain `git merge` when other tickets landed first), run `python -m unittest`, push `master`, and `git worktree remove .worktrees/NN`.
3. Close out by hand: set the ticket file's `Status:` to `done`, tick its criteria, close the GitHub issue (`gh issue close <n>`); the parent's progress bar and every dependent's blocked-by count update on their own.
4. Never use `git stash` across worktrees; `refs/stash` is shared.
5. Keep two or three sessions in flight at most: the subscription window is shared by every session, and one ticket typically costs a large part of a window.
6. Run 01 to 05 one at a time on `master` directly (no worktree needed while nothing else runs): they define the modules everything else edits.
7. The eight milestone demos (06, 15, 19, 26, 36, 43, 47, 53) are integration points: run each alone, on `master`, with the tree clean.

## Sequential alternative

If you would rather not manage worktrees, work the waves top to bottom on `master`, one `/implement` per fresh session with `/clear` between, closing each issue as it lands. Nothing is lost except calendar time.

## What is ready right now

```
gh api "repos/Bernaljp/wayline/issues?state=open&labels=ready-for-agent&per_page=100" \
  --jq '.[] | select(.issue_dependencies_summary.blocked_by == 0) | "#\(.number) \(.title)"'
```

That prints the frontier: open tickets with no open blocker, which is exactly the set you can dispatch. It shrinks and grows as issues close.

## Close-out checklist per ticket

- [ ] commit on `master`, suite green, pushed
- [ ] local `Status:` set to `done`, criteria ticked in the file
- [ ] GitHub issue closed
- [ ] if it was a milestone demo: `docs/verification/mN.md` committed and the tag pushed (`git push --tags`)
