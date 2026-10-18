# Wayline tickets: what can run in parallel, and what waits

Computed from the 100 blocking edges of the 53 tickets: 98 from the spec on 2026-09-11, plus two sequencing edges added on 2026-09-12 (08 and 10 wait for 09, because all three edit the conductor's wave loop and 09 rewrites the event replay the other two extend). The model and effort to implement each ticket are in `.scratch/wayline/models.md`. On 2026-09-13 the Fable fallback map added tickets 54 to 57 and 11 edges (54 after 10; 55 after 30 and 54; 56 after 24 and 55; 57 after 35 and 55; 14 after 54; 43 after 54, 55, and 56), for 111 edges among 57 tickets. On 2026-09-16 the M1 demo added ticket 58, a design pass over the dashboard, answering the owner's verdict on its look, and one edge (45 after 58, so the feedback form is built in the designed style), for 112 edges among 58 tickets. On 2026-09-17 the review of ticket 38 added ticket 59, worker slots, and one edge (59 after 38), for 113 edges among 59 tickets. The same day the finer tiers map (wayline #129, cut as #141 settled it) added tickets 60 to 64 and eight edges (61, 62, and 63 after 60; 43 after 60, 61, 62, and 63; 45 after 64), for 121 edges among 64 tickets. On 2026-09-27 research note 04 (Opus 5.5) added ticket 65, which moves the roles on Fable to Opus 5.5, and one edge (53 after 65), for 122 edges among 65 tickets. The same day the follow-ups after v1.0.0 added tickets 66 to 70 and one edge (68 after 70), for 123 edges among 70 tickets. On 2026-10-18 the living paper map (wayline #173, decision 17, milestone M8) added tickets 71 to 123 and 151 edges among them, for 274 edges among 123 tickets; 122, the toy's overnight demo, waits for every ticket from 71 to 121 through the five of them nothing else waits for (99, 113, 114, 120, 121). The same day the owner chose one user guide for wayline, written once its features exist, over the documentation site 32 of those tickets named and the harness never had (ticket 51's site documents a project's own package): ticket 124 and six edges (124 after 99, 113, 114, 120, and 121; 122 after 124), for 280 edges among 124 tickets, and those criteria keep only their changelog half. Ticket NN is GitHub issue NN+1 in `Bernaljp/wayline` for tickets 01 to 53, and a later ticket names its issue in the Issue column; the local file under `.scratch/wayline/issues/` is the source, the issue is the mirror.

## The rule

A ticket can start when every ticket in its **Blocked by** line is done: its commit is on `master`, `python -m unittest` passes there, its local `Status:` line is updated, and its GitHub issue is closed. Tickets in the same wave never depend on each other, so any subset of a wave can run at the same time. A ticket may also start as soon as its own blockers are done, even if the rest of its wave is not; the waves below are the earliest start, not a required batch.

## What is left on 2026-10-18: milestone M8

The 70 tickets before it are closed and v1.0.1 is tagged. Milestone M8 (Implementation Decision 17, v1.1.0) is tickets 71 to 124, sub-issues of #217, which is a sub-issue of #1. They fall into 14 waves; the first is exactly what the query under "What is ready right now" prints today. The schedule, with each ticket's grade, is "Order from here" in `.scratch/wayline/models.md`.

| Wave left | Tickets | Notes |
|---|---|---|
| 1 | 71 (#218), 72 (#219), 73 (#220), 74 (#221), 75 (#222), 76 (#223), 77 (#224), 78 (#225), 79 (#226) | Ready now. 71 is the scout fix the spec puts first; 76 starts the critical path; 79 is the batch record seven producers use. |
| 2 | 80 (#227), 81 (#228), 82 (#229), 84 (#231), 85 (#232) | 81 is on the critical path. 80 and 81 both edit the front door's readers of GOAL.json: land 81 first or expect a merge in the plan schema. |
| 3 | 83 (#230), 86 (#233), 87 (#234), 94 (#241), 106 (#253) | 86 is the passage log half the release writes into; 87 retires GOAL.json and needs 80 and 81 merged. |
| 4 | 88 (#235), 89 (#236), 93 (#240), 98 (#245), 107 (#254) | 89 renders the account before 90 moves v1.0's report sections into it. |
| 5 | 90 (#237), 91 (#238), 95 (#242), 96 (#243) | 90 rewrites the general report; 91, 95, and 96 build on the batch record and the passages. |
| 6 | 92 (#239), 97 (#244), 100 (#247), 104 (#251) | 104, the outline, is on the critical path; 100 is the first drawing ticket. |
| 7 | 99 (#246), 101 (#248), 102 (#249), 103 (#250), 105 (#252), 108 (#255) | 105 is on the critical path; 99 waits for the spec amendments of 92. |
| 8 | 109 (#256), 110 (#257) | 109 is the `wayline` skill (critical path); 110 is the dashboard's new shell. |
| 9 | 111 (#258), 112 (#259), 114 (#261), 115 (#262) | 115, the paper order, is on the critical path. 111, 112, and 114 all edit the dashboard's front end: one at a time or expect merges in `app.js`. |
| 10 | 113 (#260), 116 (#263), 117 (#264), 118 (#265), 119 (#266) | Four order tickets on top of 115, and the section editor. |
| 11 | 120 (#267), 121 (#268) | 120 waits for every order ticket; 121 adds the last dashboard actions. |
| 12 | 124 (#282) | 124 is the user guide, written once from the finished features, so the demo runs on a documented release. |
| 13 | 122 (#269) | 122 is the overnight demo: alone on `master`, a real night. |
| 14 | 123 (#270) | 123 is the PINF sitting with the owner, then the v1.1.0 release. |

The critical path of M8 is 76 -> 81 -> 86 -> 89 -> 90 -> 104 -> 105 -> 109 -> 115 -> 116 -> 120 -> 124 -> 122 -> 123, 14 tickets in a row.

Before M8, the five follow-ups after v1.0.0 (66 to 70) ran in two waves and are closed.

## Waves (earliest start)

| Wave | Tickets | Notes |
|---|---|---|
| 1 | 01 (M0, #2), 58 (M5, #114), 60 (M5, #143), 64 (M6, #147) | The foundation: nothing else could start. 58, added on 2026-09-16, and 60 and 64, added on 2026-09-17, have no blocker, since the code they edit is built. |
| 2 | 02 (M0, #3), 03 (M0, #4), 04 (M0, #5), 61 (M5, #144), 62 (M5, #145), 63 (M5, #146) | Three independent slices on top of 01: init, the launcher, the guards. 61, 62, and 63 build on 60. |
| 3 | 05 (M0, #6), 11 (M1, #12), 16 (M2, #17), 18 (M2, #19), 20 (M3, #21) | First wide wave: the conductor, the dashboard, resources, the manifest, the scout are in different modules and merge cleanly. |
| 4 | 06 (M0, #7), 07 (M1, #8), 12 (M1, #13), 17 (M2, #18), 21 (M3, #22), 23 (M3, #24), 25 (M3, #26), 27 (M4, #28), 32 (M4, #33), 48 (M7, #49), 52 (M7, #53) | Widest wave. 06 is the M0 live demo; the rest fan out across M1 to M7. |
| 5 | 09 (M1, #10), 19 (M2, #20), 22 (M3, #23), 28 (M4, #29), 40 (M5, #41), 42 (M5, #43), 49 (M7, #50) | 09 is the resume ticket, at max; the six others live in other modules and run beside it. 08 and 10 wait for 09 (wave 6). 19 is the M2 demo: it runs after 15 (rule 7), at no calendar cost. |
| 6 | 08 (M1, #9), 10 (M1, #11), 13 (M1, #14), 24 (M3, #25), 30 (M4, #31), 39 (M5, #40), 41 (M5, #42), 44 (M6, #45) | 08 and 10 both edit the conductor on top of 09: one after the other, or together and expect one real merge plus a suite run. |
| 7 | 26 (M3, #27), 31 (M4, #32), 46 (M6, #47), 54 (M1, #101) | 26 is the M3 demo: it runs after 19 (rule 7). 54 holds only Fable launches, and the tick waits for it. |
| 8 | 14 (M1, #15), 29 (M4, #30), 33 (M4, #34), 37 (M5, #38), 55 (M5, #102) | 14 waits for 54; 33 and 34 (M4) sit on the critical path. |
| 9 | 15 (M1, #16), 34 (M4, #35), 35 (M4, #36), 56 (M5, #103) | 34 is the planner; five later tickets wait on it. 15 closes M1, and the demos 19 and 26 follow it (rule 7). |
| 10 | 36 (M4, #37), 38 (M5, #39), 45 (M6, #46), 57 (M5, #104) | 36 is the M4 demo: alone on `master` first. 38 and 45 both touch the conductor loop: 38 first (43 needs it), then 45, or together and expect a merge; 57 edits the wave too. |
| 11 | 43 (M5, #44) | 43 is the overnight run; it needs a real night. It also waits for 60 to 63, which ship with it as v0.6.0. |
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
| 10 Pacing and pause on usage limits | #11 | 6 | 07, 09 | 14, 15, 54 |
| 11 Read-only dashboard: transport, tabs, journal tail, overview (verbatim prototype 36) | #12 | 3 | 02 | 12, 13 |
| 12 Dashboard graph, ticket pages, and logs endpoints | #13 | 4 | 11 | 15, 35, 42 |
| 13 User units, run --detach, and the notifier | #14 | 6 | 09, 11 | 14 |
| 14 The tick (verbatim prototype 29) | #15 | 8 | 10, 13, 54 | 15, 35, 43 |
| 15 M1 live demo: five tickets, a killed conductor, a simulated limit, the tick, the dashboard | #16 | 9 | 06, 08, 09, 10, 12, 14 | nothing (a milestone demo) |
| 16 Resources detection and slots | #17 | 3 | 02 | 17 |
| 17 Job runner seam (verbatim prototype 27) | #18 | 4 | 16 | 19, 41 |
| 18 Manifest and findings provenance | #19 | 3 | 02 | 19, 40 |
| 19 Experiment and analysis tickets end to end (M2 demo) | #20 | 5 | 07, 17, 18 | 39 |
| 20 Fetch seam, scout, L0 records, and the knowledge base | #21 | 3 | 02 | 21, 23, 25, 48, 52 |
| 21 arXiv e-print sources and the LaTeX inventory | #22 | 4 | 20 | 22 |
| 22 Non-arXiv PDF inventory chain and the tools venv (verbatim prototype 30) | #23 | 5 | 21 | 24 |
| 23 L1 skims, reading budgets, and promotion triggers | #24 | 4 | 03, 20 | 24 |
| 24 The absorb workflow for L2 | #25 | 6 | 22, 23 | 26, 56 |
| 25 Code dossiers | #26 | 4 | 20 | 26 |
| 26 The consultant and the M3 demo | #27 | 7 | 24, 25 | 29 |
| 27 Skills, the registry, and the librarian | #28 | 4 | 05 | 28, 34, 46 |
| 28 Intake and the goal | #29 | 5 | 27 | 29, 30, 35, 39, 41 |
| 29 The position memo | #30 | 8 | 26, 28 | 36 |
| 30 The grill and the autonomy switch | #31 | 6 | 28 | 31, 55 |
| 31 The decider | #32 | 7 | 30 | 33, 37 |
| 32 Type-B verdicts: the verifier role and gates | #33 | 4 | 05 | 33, 40, 50 |
| 33 Specify | #34 | 8 | 31, 32 | 34 |
| 34 Plan: the planner, plan-time checks, and ticket assignment | #35 | 9 | 27, 33 | 36, 38, 45, 51 |
| 35 Decision tickets end to end and dashboard actions | #36 | 9 | 07, 12, 14, 28 | 36, 57 |
| 36 M4 live demo: from a vague intent to a graph with roles and skills | #37 | 10 | 29, 34, 35 | 43 |
| 37 Proposals admission | #38 | 8 | 07, 31 | 43 |
| 38 Stall detection and the escalation chain | #39 | 10 | 08, 34 | 43 |
| 39 Keep-if-better under a quantitative goal | #40 | 6 | 19, 28 | 43 |
| 40 Provenance tags, the linter, and REPORT.md | #41 | 5 | 18, 32 | 43, 53 |
| 41 The toy project fixture | #42 | 6 | 17, 28 | 43 |
| 42 Dashboard outputs, downloads, and logs | #43 | 5 | 12 | 43, 45 |
| 43 M5 overnight demo: the toy project end to end across a window boundary | #44 | 11 | 14, 36, 37, 38, 39, 40, 41, 42, 54, 55, 56, 60, 61, 62, 63 | 47, 50, 51 |
| 44 Fixture format and runner (verbatim prototype 32) | #45 | 6 | 03, 09 | 45, 46 |
| 45 Feedback, change records, harness tickets, and local skills | #46 | 10 | 34, 42, 44, 58, 64 | 47 |
| 46 Tags, pins, upgrade, rollback, and promotion | #47 | 7 | 27, 44 | 47 |
| 47 M6 demo: feedback to a tagged harness change and back | #48 | 12 | 43, 45, 46 | nothing (a milestone demo) |
| 48 The plot index | #49 | 4 | 20 | 49 |
| 49 Figure machine checks, schemas, and the house style | #50 | 5 | 48 | 50 |
| 50 The figure role pipeline end to end | #51 | 12 | 32, 43, 49 | 53 |
| 51 The documentation site | #52 | 12 | 34, 43 | 53 |
| 52 Venue guidelines | #53 | 4 | 20 | 53 |
| 53 The paper and the M7 demo | #54 | 13 | 40, 50, 51, 52, 65 | nothing (a milestone demo) |
| 54 Hold only Fable launches while Fable's weekly window is spent | #101 | 7 | 10 | 14, 43, 55 |
| 55 Fall back to Opus under the fallback consent | #102 | 8 | 30, 54 | 43, 56, 57 |
| 56 Verdicts on Opus and the verdict principle | #103 | 9 | 24, 55 | 43 |
| 57 Ask the owner when Fable is spent | #104 | 10 | 35, 55 | nothing |
| 58 A design pass over the dashboard | #114 | 1 | nothing | 45 |
| 59 Worker slots count every session a conductor owes | #126 | 11 | 38 | nothing |
| 60 The rung ladder | #143 | 1 | nothing | 43, 61, 62, 63 |
| 61 Escalation by rung | #144 | 2 | 60 | 43 |
| 62 Pacing and the fallback by rung | #145 | 2 | 60 | 43 |
| 63 The model that ran | #146 | 2 | 60 | 43 |
| 64 The ladder consent | #147 | 1 | nothing | 45 |
| 65 Opus 5.5 in the roles and the verifier table | #160 | 1 | nothing | 53 |
| 66 The paper's figure text and captions | #163 | 1 | nothing | nothing |
| 67 REPORT.md gets a second draft | #164 | 1 | nothing | nothing |
| 68 A tier up carries the last failure | #165 | 2 | 70 | nothing |
| 69 No bytecode in a touch set | #166 | 1 | nothing | nothing |
| 70 The rung ladder without Fable | #167 | 1 | nothing | 68 |
| 71 The scout's outcomes, cache, and joins | #218 | 1 | nothing | 98 and 118 |
| 72 research_version and the big-upgrade refusal | #219 | 1 | nothing | 110 |
| 73 The guard and gitignore defects found while charting | #220 | 1 | nothing | 85 |
| 74 The document viewer: dialog, zoom, KaTeX math, and the sanitizer | #221 | 1 | nothing | 110 |
| 75 The harness's tools | #222 | 1 | nothing | 82, 84, 95, 100, 104, 107, and 118 |
| 76 Objectives: the record and objective add | #223 | 1 | nothing | 80 and 81 |
| 77 Plot index data shapes and the five readability checks | #224 | 1 | nothing | 100 |
| 78 The synthetic start-midway project | #225 | 1 | nothing | 84 and 85 |
| 79 Batches and marks | #226 | 1 | nothing | 82, 89, 91, 95, 96, 100, 104, 109, and 112 |
| 80 The front door reads objectives | #227 | 2 | 76 | 87, 91, 96, and 109 |
| 81 Specify and the plan name objectives | #228 | 2 | 76 | 86, 87, 91, 97, 99, and 109 |
| 82 Project tools and the software decision | #229 | 2 | 75 and 79 | 83, 102, 106, 109, 110, and 112 |
| 83 Moving a project's environment | #230 | 3 | 82 | 110 |
| 84 Documents in: converting and keeping a project's documents | #231 | 2 | 75 and 78 | 93, 94, and 96 |
| 85 The code repository | #232 | 2 | 73 and 78 | 97, 106, 107, 109, 111, and 121 |
| 86 Passages and the five sections | #233 | 3 | 81 | 88, 89, 90, 91, 93, 98, and 107 |
| 87 Keep-if-better per goal, the stopping rule, and budgets; GOAL.json retires | #234 | 3 | 80 and 81 | 89, 90, 103, and 109 |
| 88 The owner's passages, consolidation, and the linter's new tags | #235 | 4 | 86 | 109, 113, and 121 |
| 89 The account | #236 | 4 | 79, 86, and 87 | 90, 91, 105, 109, 110, 112, and 115 |
| 90 Results and the general report | #237 | 5 | 86, 87, and 89 | 100, 103, 104, 109, 110, and 115 |
| 91 Objective changes | #238 | 5 | 79, 80, 81, 86, and 89 | 92, 109, and 112 |
| 92 Spec amendments | #239 | 6 | 91 | 99 |
| 93 Inherited passages | #240 | 4 | 84 and 86 | 95, 96, 97, and 104 |
| 94 Consulting one document | #241 | 3 | 84 | 97 |
| 95 Repeated claims | #242 | 5 | 75, 79, and 93 | 111 and 112 |
| 96 Critiques and concerns | #243 | 5 | 79, 80, 84, and 93 | 97, 104, 109, 111, 112, and 117 |
| 97 Verifying inherited results | #244 | 6 | 81, 85, 93, 94, and 96 | 108, 109, 111, 115, and 117 |
| 98 References during a ticket | #245 | 4 | 71 and 86 | 99 and 105 |
| 99 The surveyor and lit tickets | #246 | 7 | 81, 92, and 98 | 122 and 124 |
| 100 Drawings on the plotter | #247 | 6 | 75, 77, 79, and 90 | 101, 102, 103, 112, and 116 |
| 101 Current and earlier reports | #248 | 7 | 100 | 110 |
| 102 The plotting library switch | #249 | 7 | 82 and 100 | 121 |
| 103 The run-end gates | #250 | 7 | 87, 90, and 100 | 120 |
| 104 The outline | #251 | 6 | 75, 79, 90, 93, and 96 | 105, 108, 111, 112, 113, and 115 |
| 105 References rendered and important ones raised | #252 | 7 | 89, 98, and 104 | 109, 111, 115, and 121 |
| 106 Reproducing from the code repository | #253 | 3 | 82 and 85 | 108 and 119 |
| 107 The rule from code to Methods | #254 | 4 | 75, 85, and 86 | 108 and 119 |
| 108 Methods generated by the inventory | #255 | 7 | 97, 104, 106, and 107 | 111, 113, and 115 |
| 109 The wayline skill and setup as one conversation | #256 | 8 | 79, 80, 81, 82, 85, 87, 88, 89, 90, 91, 96, 97, and 105 | 114 and 115 |
| 110 Dashboard: routes, the projects page, and the Research and Run views | #257 | 8 | 72, 74, 82, 83, 89, 90, and 101 | 111, 112, and 114 |
| 111 Dashboard: the Paper and Inherited views | #258 | 9 | 85, 95, 96, 97, 104, 105, 108, and 110 | 113 |
| 112 Dashboard: the marks view | #259 | 9 | 79, 82, 89, 91, 95, 96, 100, 104, and 110 | 121 |
| 113 Dashboard: editing sections and the outline | #260 | 10 | 88, 104, 108, and 111 | 122 and 124 |
| 114 The dashboard's chat | #261 | 9 | 109 and 110 | 122 and 124 |
| 115 The paper order and the paper's parts | #262 | 9 | 89, 90, 97, 104, 105, 108, and 109 | 116, 117, 118, 119, and 121 |
| 116 Figures at the order | #263 | 10 | 100 and 115 | 120 |
| 117 Builds at the order | #264 | 10 | 96, 97, and 115 | 120 |
| 118 Compilations | #265 | 10 | 71, 75, and 115 | 120 and 121 |
| 119 Code at the order | #266 | 10 | 106, 107, and 115 | 120 |
| 120 The decider orders the paper under autonomous | #267 | 11 | 103, 116, 117, 118, and 119 | 122 and 124 |
| 121 Dashboard: cards and new actions | #268 | 11 | 85, 88, 102, 105, 112, 115, and 118 | 122 and 124 |
| 122 M8 live demo: the toy overnight | #269 | 13 | every ticket from 71 to 121, and 124 | 123 |
| 123 M8 live demo: PINF restarted from its own materials, and v1.1.0 | #270 | 14 | 122 | nothing |
| 124 The harness's user guide | #282 | 12 | 99, 113, 114, 120, and 121 | 122 |

## Running tickets in parallel without corrupting git

`implement` commits to the current branch of the checkout it runs in. It creates no branch, opens no pull request, and closes nothing. Two `implement` sessions in one checkout share one index and one HEAD and corrupt each other (the skill's own docs report amended commits landing on the wrong session and vanished stashes). So:

1. One session, one ticket, one git worktree. A new agent created from `claude agents` gets one by default (`worktree.bgIsolation` is `auto`): `.claude/worktrees/<name>` on branch `worktree-<name>`, branched from origin's `master`. From a terminal, `claude -w ticket-NN --model <alias> --effort <effort>` does the same. Give the session `/implement` with the full path of the ticket file (or the issue URL) and ask it to confirm the title back before it starts. The manual route still works: `git worktree add -b ticket/NN .worktrees/NN master` (the `.worktrees/` directory is ignored), then start Claude Code inside it.
2. When the agent reports done, it has opened a pull request against `master` (`CLAUDE.md` tells every session to: criteria ticked, `Status: done`, `Closes #<issue>` in the body). Read it on GitHub, wait for the `tests` check, and merge it with a merge commit (the repository allows no other kind, so a tag made on the branch stays on `master`'s line; the remote branch is deleted by the merge). The merge closes the issue, so every dependent's blocked-by count updates on its own. When more than one pull request is open, stack them first, as "Merging pull requests that are open together" below says, and merge them in number order.
3. Then locally: `git pull` on `master` (a new worktree branches from origin's `master`, which the merge already updated, but anything you run on `master` itself needs the pull), and run the sweep under "Removing ended sessions" below, which deletes the worktrees whose pull requests are merged, with their sessions and local branches (`git worktree remove .worktrees/NN` for a manual worktree outside `.claude/worktrees/`).
4. Never use `git stash` across worktrees; `refs/stash` is shared.
5. Keep two or three sessions in flight at most: the subscription window is shared by every session, and one ticket typically costs a large part of a window.
6. Run 01 to 05 one at a time on `master` directly (no worktree needed while nothing else runs): they define the modules everything else edits.
7. The eight milestone demos (06, 15, 19, 26, 36, 43, 47, 53) are integration points: run each alone, on `master`, with the tree clean, and in milestone order, so that every tag from v0.1.0 to v1.0.0 contains the code of the tags before it (`upgrade` moves a project between tags and prints the changelog between them, which needs a straight line). 19 and 26 therefore wait for 15 (wave 9), and 39 and 29 wait for them; this costs no calendar time, since none of the four is on the critical path. The schedule that follows these rules step by step is "Order from here" in `.scratch/wayline/models.md`.
8. Same-module pairs: 09 before 08 and 10 (recorded as blocked-by edges, so the frontier query holds 08 and 10 until 09 closes), 38 before 45 in wave 10 (a note only), 54 before 55 (a blocked-by edge), 57 beside 38 in wave 10 (a note only), and 59 before 61 (a note only: both edit the conductor's wave). Running such a pair together is allowed at the price of one real merge and a suite run on `master` afterwards; if the merge conflicts, start a session at the repo root and use `/resolving-merge-conflicts`.

### Removing ended sessions

No session id to look up: `bash .scratch/wayline/sweep-sessions.sh` fetches, then removes every worktree under `.claude/worktrees/` whose branch's pull request is merged, with its session and its local branch. An idle session goes with its worktree, and so does a worktree no session is left in. It keeps and names everything else: a worktree whose session is busy; a branch whose pull request is not merged, or that has commits `master` lacks (its pull request is open, and `claude attach <id>` can still reopen the session for a fix); a worktree with uncommitted changes, or with another program running in it. A session with no worktree, such as one just started, is never touched. `--dry-run` prints what would go and removes nothing. Run it after merging, from anywhere in the repository:

```
bash .scratch/wayline/sweep-sessions.sh
```

A single session is `claude rm <id>`, the id being the short hex printed when the session started and listed by `claude agents --json --all`. Keep a session until its pull request is merged, so `claude attach <id>` can reopen it for a fix.

### Merging pull requests that are open together

Every ticket appends to the same lines: the `SHIPPED` list of the schema tests, the changelog's Unreleased section, the verb table. So pull requests open at the same time conflict with each other as soon as one of them is merged. Before merging any of them, stack them:

```
bash .scratch/wayline/stack-open-prs.sh
```

It merges origin's `master` into the lowest-numbered open pull request, then that result into the next one, and so on, and pushes each branch it changes. Every pull request then holds `master` and the ones numbered below it, so they merge one after another with no conflict. Merge them in number order, each once its `tests` check is green: a later one merged first lands the earlier ones with it, unread. Until the one below it is merged, a stacked pull request's diff on GitHub also shows the changes below it. A draft pull request stays out of the stack, which is how to hold one back. Run the script again when a new pull request opens; a branch that already holds everything below it is left as it is.

A conflict resolved once is resolved the same way again by git rerere, from the resolutions recorded in this clone's `.git/rr-cache`. At a conflict with no recorded resolution the script stops and names the files, with the pull requests below it already pushed: merge by hand in a worktree of that branch, or ask a session to, then push and run the script again. A textual merge can still hide a collision of meaning that only the suite reports: a role sidecar written before ticket 27 landed carried fields the registry now refuses, and the merge said nothing. Read the check, not the merge.

## Sequential alternative

If you would rather not manage worktrees, work the waves top to bottom on `master`, one `/implement` per fresh session with `/clear` between, closing each issue as it lands. Nothing is lost except calendar time.

## What is ready right now

```
gh api "repos/Bernaljp/wayline/issues?state=open&labels=ready-for-agent&per_page=100" \
  --jq '.[] | select(.issue_dependencies_summary.blocked_by == 0) | "#\(.number) \(.title)"'
```

That prints the frontier: open tickets with no open blocker, which is exactly the set you can dispatch. It shrinks and grows as issues close.

## Close-out checklist per ticket

- [ ] more than one pull request open: stacked with `bash .scratch/wayline/stack-open-prs.sh`, merged in number order
- [ ] pull request read, `tests` check green, merge commit made on GitHub (the merge closes the issue and deletes the remote branch)
- [ ] the ticket file in the pull request has `Status: done` and every criterion ticked; an unticked one is named in the body, decide whether it blocks
- [ ] `git pull` on local `master`; the session sweep ("Removing ended sessions")
- [ ] if it was a milestone demo: `docs/verification/mN.md` in the pull request and the tag pushed (`git push --tags`)
