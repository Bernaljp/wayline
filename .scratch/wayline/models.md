# Wayline tickets: which model and effort to implement each one

Graded on 2026-09-11 with the harness's own difficulty table (spec, Implementation Decisions 14, the `difficulty` row of `policy.json`, from BRIEF 8.4), so the tickets that build the harness are graded the way the harness will grade its own tickets. Ticket NN is GitHub issue NN+1 in `Bernaljp/wayline` for tickets 01 to 53, and a later ticket names its issue in the Issue column; tickets 54 to 57 were added on 2026-09-13 from the Fable fallback map and graded the same way. Ticket 58, a design pass over the dashboard, was added on 2026-09-16 from the owner's verdict in the M1 demo and graded the same way. Ticket 59, worker slots, was added on 2026-09-17 from the review of ticket 38 and graded the same way. 54 was cut as opus high and regraded fable xhigh the same day, because the hold it builds has to replay. Tickets 60 to 64 were added on 2026-09-17 from the finer tiers map (wayline #129), and the same day every open ticket was regraded under the cap (spec, Implementation Decision 16): see "Regraded under the cap" below. Ticket 65, which moves the roles on Fable to Opus 5.5, was added on 2026-09-27 from research note 04 and graded the same way, and 53 was regraded to `opus high` that day: see "Regraded for Opus 5.5" below. Tickets 66 to 70, the follow-ups after v1.0.0, were added the same day from the M7 and docs-site live runs and research note 04, and graded the same way: see "Follow-ups after v1.0.0" below. Each issue also carries a `model:` label with its grade.

| Difficulty | Model | Effort | Tickets | Label |
|---|---|---|---|---|
| 1 | sonnet | low | none | |
| 2 | sonnet | medium | 12, 16, 18, 23, 25, 37, 41, 42, 48 (9) | `model:sonnet-medium` |
| 3 | opus | high | the other 35 | `model:opus-high` |
| 4 | fable | xhigh | 01, 03, 07, 30, 31, 32, 43, 45, 50, 53, 54 (11) | `model:fable-xhigh` |
| 5 | fable | max | 05, 09, 34 (3) | `model:fable-max` |

No ticket is difficulty 1: `to-tickets` cut nothing that small, since every ticket is a tracer bullet with tests. This table is the grading of 2026-09-11 and 2026-09-13, kept as history for the closed tickets; the `fable xhigh` and `fable max` rows no longer apply to any open ticket.

## Regraded under the cap (2026-09-17)

Implementation Decision 16 caps the harness's ticket work at `high` effort, and this file adopts the cap for the owner's build sessions: no implement or review session runs above `high`. A build session gets a model and an effort, not a rung, because it has no harness budget, but the grades follow the rung ladder's cost order (in multiples of Opus 5 at `high`: sonnet low about 0.35, sonnet high 0.50, opus low 0.67, opus high 1.00, fable low 1.54, fable high 2.06), and Fable is kept only where a ticket writes a role prompt whose quality every later project run inherits or sets an interface the others build on.

| Grade | Open tickets | Label |
|---|---|---|
| opus low | 64 | `model:opus-low` |
| opus high | 43, 47, 51, 59, 61, 62, 63 | `model:opus-high` |
| fable high | 45, 50, 53, 60 | `model:fable-high` |

- 45, 50, and 53 were `fable xhigh`; they keep Fable for the evolver's, the figure designer's and critic's, and the writer's prompts, one step down at `high`.
- 43 was `fable xhigh`; it drops to `opus high`, as the four live demos before it (15, 19, 26, 36) ran at `opus high` without an escalation.
- 60 sets the rung ladder that 61, 62, and 63 build on and migrates the table ten test files read, so it takes Fable; 61, 62, and 63 follow decision 16's exact rules at `opus high`; 64 copies what 55 built for `switch --fallback`, so `opus low` suffices.

## Regraded for Opus 5.5 (2026-09-27)

Since 2026-09-22 `opus` launches Opus 5.5 (`claude-opus-5-5`). On the matched probe it costs 0.72 of Opus 5 at `high`, and it ranks above Fable 5.1 on every row of its system card's summary table (`.scratch/model-tiers/research-notes/04-opus-5-5.md`). The cost line above therefore no longer puts Fable first on quality, and no build session keeps Fable for it.

| Grade | Open tickets | Label |
|---|---|---|
| opus high | 53, 65 | `model:opus-high` |

- 53 was `fable high` for the writer's prompt. That reason now points to Opus 5.5, which also leaves Fable's weekly window alone.
- 65 moves the harness's own roles on Fable to Opus 5.5 and blocks 53. It changes five values of `policy.json` and decision 14's table, and moves the Fable tests onto policies of their own. Note 04 and decision 15 give every value.

## Follow-ups after v1.0.0 (2026-09-27)

| Grade | Open tickets | Label |
|---|---|---|
| opus low | 67, 69 | `model:opus-low` |
| opus high | 66, 68, 70 | `model:opus-high` |

- 66 writes the figure designer's caption rule and changes what a paper's figures hand the writer, so it takes `opus high`.
- 67 copies the redraft loop 53 built for the paper. 69 is one launch variable and one exemption in a check. Both take `opus low`, the way 64 copied 55.
- 68 changes the prompt the escalation chain gives a tier up, which replay must rebuild. 70 migrates the shipped rung ladder that about 40 test lines read. Both take `opus high`.

## How the grade was chosen

The grade is for the session that implements the ticket, not for the harness's own workers. A ticket goes up a tier when it:

- sets an interface many later tickets build on (the launcher seam, the conductor's wave, the planner);
- needs reasoning about concurrency or replay (two workers at once, a killed conductor, the journal as the bus);
- writes a role or skill prompt whose quality decides what every later project run produces (the grill, the decider, the verifier, the planner, the evolver, the figure designer, the writer);
- is a live demo across many modules, where diagnosing what broke is the work.

It goes down when the spec and the research notes already carry the exact commands, schemas, unit files, and decode tables, so the session mostly transcribes and tests.

## Launching at the right grade

Each ticket gets a fresh session in its own git worktree. A new agent created from `claude agents` gets the worktree by default (`.claude/worktrees/<name>` on branch `worktree-<name>`, branched from origin's `master`); set its model and effort from the table when you create it. From a terminal the same launch is:

```
claude -w ticket-60 --model fable --effort high
/implement .scratch/wayline/issues/60-the-rung-ladder.md
```

Replace the alias (`sonnet`, `opus`, `fable`) and the effort (`low`, `medium`, `high`) from the grade; under the cap no build session takes `xhigh` or `max`. Merge on GitHub and `git pull` afterwards: the next worktree branches from origin's `master`, which the merge updates, while your local `master` lags until the pull. Follow-up fixes to a ticket already on `master` rarely need its grade: `/clear` and relaunch one tier down.

## Order from here

On 2026-09-27 all 65 tickets of the spec are closed and v1.0.0 is tagged, and this schedule takes the five follow-ups. The waves they fall into are in "What is left after v1.0.0" of `.scratch/wayline/waves.md`; earlier schedules are in this file's history. None of them is a demo, so the rules come down to two: at most three sessions in flight, and a step starts when every ticket of the step before it has landed on `master` and is pushed.

| Step | Tickets, with their grade | Notes |
|---|---|---|
| 1 | 70 opus high, 66 opus high, 67 opus low | Ready now. 70 goes first, since 68 waits for it. |
| 2 | 68 opus high, 69 opus low | 68 waits for 70. 69 is ready now, and waits only for a free slot. |

When all five have landed, tag v1.0.1 on a release commit, the way 53 released v1.0.0. None of the five needs Fable.

## Per ticket

| Ticket | Issue | Wave | Difficulty | Model | Effort | Why |
|---|---|---|---|---|---|---|
| 01 Package skeleton, frontmatter parser, schema validator, ledger core | #2 | 1 | 4 | fable | xhigh | Three in-house parsers the whole harness trusts (frontmatter subset, JSON Schema subset, the ledger lock); every later ticket imports it. |
| 02 init lays out a project and status reads it | #3 | 2 | 3 | opus | high | Broad plumbing (layout, symlinks, pointers, `status`, `graph.json` regeneration) that every verb reads; a mistake here is copied everywhere. |
| 03 Worker launcher seam with fake and claude_cli backends | #4 | 2 | 4 | fable | xhigh | The only place that starts `claude`; the fake backend's scripting shapes every later test; stream parsing on the recorded streams. |
| 04 Guards, per-launch settings, and accept | #5 | 2 | 3 | opus | high | The command guard must catch every dangerous spelling and pass every benign one; 25 cases plus one live launch. |
| 05 The conductor's M0 path with the fake worker | #6 | 3 | 5 | fable | max | The wave, prompt assembly, and the integration protocol: the shape every M1 to M5 ticket extends. |
| 06 M0 live: one trivial ticket end to end | #7 | 4 | 3 | opus | high | A live run against the real CLI; the work is recording and fixing what the CLI does differently from the notes. |
| 07 Frontier, launchable subset, and two parallel workers | #8 | 4 | 4 | fable | xhigh | Two workers at once decide the conductor's concurrency model; six tickets wait on it. |
| 08 Integration protocol and the integrator role | #9 | 6 | 3 | opus | high | Rebase, fast-forward, and a fresh integrator on conflict, with real git conflicts in the tests. |
| 09 Resume from the journal, heartbeat, control events, and worker re-adoption | #10 | 5 | 5 | fable | max | Idempotent replay, re-adopting live workers by pid and stream, SIGKILL mid-wave: the "journal is the bus" thesis. |
| 10 Pacing and pause on usage limits | #11 | 6 | 3 | opus | high | Utilization parsing and the three hit-limit signals; this is what keeps the overnight run alive at the window. |
| 11 Read-only dashboard: transport, tabs, journal tail, overview | #12 | 3 | 3 | opus | high | Threading server, ETags, and the server-sent events alternative; research-notes 08 carries the server. |
| 12 Dashboard graph, ticket pages, and logs endpoints | #13 | 4 | 2 | sonnet | medium | The 43-line layered layout is in the research note; the rest is endpoints and a page. |
| 13 User units, run --detach, and the notifier | #14 | 6 | 3 | opus | high | Touches the owner's systemd user manager and the credentials env file; the uninstall must leave nothing behind. |
| 14 The tick | #15 | 8 | 3 | opus | high | Many branches (login expiry, usage, heartbeat, jobs, relaunch) under a fake clock; a one-minute live test. |
| 15 M1 live demo | #16 | 9 | 3 | opus | high | The first cross-cutting live run; mostly running and recording with the owner at the laptop. |
| 16 Resources detection and slots | #17 | 3 | 2 | sonnet | medium | `nvidia-smi` and `/proc` parsing over recorded readings; the slot rules are given verbatim. |
| 17 Job runner seam | #18 | 4 | 3 | opus | high | The launch line and the decode table are verbatim from research-notes 05; the OOM rule and the `setsid` fallback need care; live on the GPU. |
| 18 Manifest and findings provenance | #19 | 3 | 2 | sonnet | medium | Four ledger functions and one refusal; small and exact. |
| 19 Experiment and analysis tickets end to end (M2 demo) | #20 | 5 | 3 | opus | high | Job polling, arrays by slots, and the retry ladder inside the wave; a live GPU sweep (v0.3.0). |
| 20 Fetch seam, scout, L0 records, and the knowledge base | #21 | 3 | 3 | opus | high | The fetch seam with its recording backend serves four later tickets; five APIs with per-host limits and a cache. |
| 21 arXiv e-print sources and the LaTeX inventory | #22 | 4 | 3 | opus | high | LaTeX regex inventory, `.aux` numbering, the HTML fallback; the live counts on 1706.03762 must match. |
| 22 Non-arXiv PDF inventory chain and the tools venv | #23 | 5 | 3 | opus | high | Poppler plus docling, marker, MinerU, and GROBID as subprocesses in a tools venv; provenance on every field. |
| 23 L1 skims, reading budgets, and promotion triggers | #24 | 4 | 2 | sonnet | medium | One launcher call over a capped input and a promotion function with a budget. |
| 24 The absorb workflow for L2 | #25 | 6 | 3 | opus | high | Workflow script fan-out, the coverage audit, and the conductor fallback; research-notes 04 carries the Workflow facts. |
| 25 Code dossiers | #26 | 4 | 2 | sonnet | medium | A clone at a sha, an `ast` inventory, a recipe run in a fresh venv. |
| 26 The consultant and the M3 demo | #27 | 7 | 3 | opus | high | The consultant role and verb, the Workflow path, and the M3 live demo with the policy numbers revised (v0.4.0). |
| 27 Skills, the registry, and the librarian | #28 | 4 | 3 | opus | high | Sidecars, the registry build with outcome records, the librarian's assignment rule; five tickets wait on it. |
| 28 Intake and the goal | #29 | 5 | 3 | opus | high | The intake skill's prompt and the goal validation; four intake shapes in the tests. |
| 29 The position memo | #30 | 8 | 3 | opus | high | The critic's prompt (the hostile reviewer) and citation filtering; the role's quality shows in every memo. |
| 30 The grill and the autonomy switch | #31 | 6 | 4 | fable | xhigh | The grill skill's prompt decides the whole front door: tiers, recommended answers, facts looked up, and the switch. |
| 31 The decider | #32 | 7 | 4 | fable | xhigh | The decider's prompt and the irreversible-list check that protects data, pushes, budgets, and the goal. |
| 32 Type-B verdicts: the verifier role and gates | #33 | 4 | 4 | fable | xhigh | The verifier's prompt and the gate every later Type-B question reuses; the two-thread kill argument. |
| 33 Specify | #34 | 8 | 3 | opus | high | The specify protocol, its structural checks, and the verdict loop; the planner role itself lands in 34. |
| 34 Plan: the planner, plan-time checks, and ticket assignment | #35 | 9 | 5 | fable | max | The planner's prompt (demo, acceptance, touch set, difficulty, context pack), the plan-time checks, replan, and split; every project run's quality starts here. |
| 35 Decision tickets end to end and dashboard actions | #36 | 9 | 3 | opus | high | Wires the conductor, the tick, the dashboard, and the CLI through four answer paths and nine token-guarded actions. |
| 36 M4 live demo | #37 | 10 | 3 | opus | high | The front door live end to end; the session runs the verbs and records (v0.5.0). |
| 37 Proposals admission | #38 | 8 | 2 | sonnet | medium | The admission rules are given verbatim (radius, similarity thresholds, caps) with a fake judge. |
| 38 Stall detection and the escalation chain | #39 | 10 | 3 | opus | high | The stall counter and the four-step escalation chain inside the wave; `--simulate-failure`. |
| 39 Keep-if-better under a quantitative goal | #40 | 6 | 3 | opus | high | Per-seed statistics, fast-forward only on a real gain, discarded branches kept as negative results. |
| 40 Provenance tags, the linter, and REPORT.md | #41 | 5 | 3 | opus | high | The tag grammar, the haiku classifier cache, the linter, the sampling rule, and the eleven-section report renderer. |
| 41 The toy project fixture | #42 | 6 | 2 | sonnet | medium | A synthetic dataset, a minutes-long trainer with one OOM configuration, three synthetic references, a README. |
| 42 Dashboard outputs, downloads, and logs | #43 | 5 | 2 | sonnet | medium | Range requests and zip streaming from research-notes 08; the outputs index. |
| 43 M5 overnight demo | #44 | 11 | 3 | opus | high | The overnight run across a window boundary exercises everything, the rung ladder included; diagnosing the morning's journal is the work (v0.6.0). Was fable xhigh; regraded under the cap on 2026-09-17. |
| 44 Fixture format and runner | #45 | 6 | 3 | opus | high | The fixture runner (structural checks over a JSONPath subset, the judged layer, caches, quarantine, exit codes) and the record verb. |
| 45 Feedback, change records, harness tickets, and local skills | #46 | 10 | 4 | fable | high | The evolver's prompt, harness tickets on harness worktrees, hot-reloaded local changes, the rule that `autonomous` only proposes global changes, and the ladder consent on ladder changes. Was fable xhigh; regraded under the cap on 2026-09-17. |
| 46 Tags, pins, upgrade, rollback, and promotion | #47 | 7 | 3 | opus | high | Tags, pins, upgrade, and rollback move the harness's own checkout; a promotion branch runs the full fixture suite. |
| 47 M6 demo | #48 | 12 | 3 | opus | high | Feedback through the loop to a tag, live, with the suite offline in under a minute (v0.7.0). |
| 48 The plot index | #49 | 4 | 2 | sonnet | medium | Crawling five galleries through the seam into a metadata-only index; pitfalls rewritten from the owner's skill. |
| 49 Figure machine checks, schemas, and the house style | #50 | 5 | 3 | opus | high | Nineteen mechanical checks with PDF tools, SSIM regeneration, and CVD-simulated color distance, each with good and bad samples. |
| 50 The figure role pipeline end to end | #51 | 12 | 4 | fable | high | The designer's and the critic's prompts carrying the honesty doctrine, the guided path's refusals, and sub-verdicts. Was fable xhigh; regraded under the cap on 2026-09-17. |
| 51 The documentation site | #52 | 12 | 3 | opus | high | The documentarian role, Sphinx in the project's own environment, symbol and example checks. |
| 52 Venue guidelines | #53 | 4 | 3 | opus | high | Seventeen venues' rules from heterogeneous pages into one schema; seven manuscript checks. |
| 53 The paper and the M7 demo | #54 | 13 | 4 | opus | high | The writer's prompt under the provenance rule, the build loop with the linter and the checks, the kill argument (v1.0.0). Was fable xhigh; regraded under the cap on 2026-09-17, and to opus high on 2026-09-27 for Opus 5.5 (research note 04). |
| 54 Hold only Fable launches while Fable's weekly window is spent | #101 | 7 | 4 | fable | xhigh | Rebuilds 10's whole-run pause into a hold on Fable launches that a whole-run pause can start and end inside and that replay must rebuild the same way twice; a refusal can hide inside a subagent of a successful session; 14, 43, and 55 build on the hold. |
| 55 Fall back to Opus under the fallback consent | #102 | 8 | 3 | opus | high | The consent through intake, `switch --fallback`, and `control`, and the launch mapping with its escalation rule; decision 15 gives every value. |
| 56 Verdicts on Opus and the verdict principle | #103 | 9 | 3 | opus | high | A rule change in the gates and the spot-check, fallback verdicts under each consent, and one report section. |
| 57 Ask the owner when Fable is spent | #104 | 10 | 3 | opus | high | A decision ticket opened by code with four options, a superseded close, and a timeout under a fake clock; one dashboard action. |
| 58 A design pass over the dashboard | #114 | 1 | 3 | opus | high | Every view restyled at once under the no-build, no-CDN rule with the dashboard's behavior and tests unchanged; renders in a real browser before and after, and the owner's acceptance through the tunnel. |
| 59 Worker slots count every session a conductor owes | #126 | 11 | 3 | opus | high | A concurrency rule in the wave: every session in flight holds its slot, gate resumes wait for one; tested with delayed fake sessions. |
| 60 The rung ladder | #143 | 1 | 4 | fable | high | The policy's new shape, the schema's cap and old-shape refusal, `tier_for` and the planner by rung, `upgrade`'s migration, and the ten test files that read the old table; 61, 62, and 63 build on it. |
| 61 Escalation by rung | #144 | 2 | 3 | opus | high | The chain's new order by family, the top rung, and the `rung` to `step` rename, in the replay `tests/test_escalation.py` already covers. |
| 62 Pacing and the fallback by rung | #145 | 2 | 3 | opus | high | The step down replacing `cheap_only`'s deferral, the tier-up exemption, the fallback by rung, and a new `--simulate-limit` spelling; decision 16 gives every value. |
| 63 The model that ran | #146 | 2 | 3 | opus | high | The remap switch on every launch, the `modelUsage` check, and a rung held behind a decision ticket after a 404. |
| 64 The ladder consent | #147 | 1 | 2 | opus | low | A copy of what 55 built for `switch --fallback`: a `harness.json` key, the intake question, the switch, the class, one dashboard action. |
| 65 Opus 5.5 in the roles and the verifier table | #160 | 1 | 3 | opus | high | Five values of `policy.json` and decision 14's table, which the tests compare, with the Fable hold and fallback tests moved onto policies of their own; note 04 and decision 15 give every value. |
| 66 The paper's figure text and captions | #163 | 1 | 3 | opus | high | The figure designer's caption rule, a paper's figures handing their text suggestions to the writer, and a caption check routed through the guided path. |
| 67 REPORT.md gets a second draft | #164 | 1 | 2 | opus | low | The paper's redraft loop copied to the report, with the cache keeping the linter's result. |
| 68 A tier up carries the last failure | #165 | 2 | 3 | opus | high | The failure output a resume sends, carried into a tier-up attempt's prompt and rebuilt the same way on a restart. |
| 69 No bytecode in a touch set | #166 | 1 | 2 | opus | low | One launch variable and one exemption in the uncommitted-work check. |
| 70 The rung ladder without Fable | #167 | 1 | 3 | opus | high | The shipped six-rung ladder, decision 14's test-checked rows, the Fable tests moved onto their own rung ladder, and `upgrade`'s index migration. |

## Working the window

- Fable uses the five-hour window fastest, and its weekly window is the scarce one. Run one Fable session at a time and pair it with the opus-grade tickets of the same step. Under the cap no build session runs at `xhigh` or `max`.
- When Fable's weekly window is spent, a Fable ticket either waits for the reset or runs on opus at the same effort (`--model opus --effort high`); the harness gives its own runs the same choice (Implementation Decisions 15).
- The critical path (01, 02, 05, 27, 28, 30, 31, 33, 34, 36, 43, 50, 53) carries 8 of the 14 Fable tickets, so the Fable budget mostly goes to the chain that sets the calendar. What is left of it on 2026-09-17 (60, 61, 43, 50, 53) carries three of the four Fable tickets still open (60, 50, 53; the fourth is 45). Fill around it with opus and sonnet tickets.
- Escalation, the harness's own rule: a ticket that fails its acceptance twice at its grade is rerun one tier up in a fresh session (sonnet medium to opus high, opus high to fable high, and fable high, the top under the cap, to the owner). A ticket that sailed through is not a reason to lower the next one.
- A verdict before merging, the harness's own rule too: for difficulty 4 and 5 tickets, have a different model read the diff before you merge the pull request (for example `/code-review` in a fresh opus session). The harness's verifier table pairs a fable author with an opus reader.
- Live demo tickets (06, 15, 19, 26, 36, 43, 47, 53) need the owner nearby for the tunnel, the phone, and the GPU; the model grade covers the diagnosis, the wallclock is the demo.

## What is ready right now, with its grade

```
gh api "repos/Bernaljp/wayline/issues?state=open&labels=ready-for-agent&per_page=100" \
  --jq '.[] | select(.issue_dependencies_summary.blocked_by == 0)
        | "#\(.number) \(.title)  [\([.labels[].name | select(startswith("model:")) | sub("model:"; "")] | join(","))]"'
```

After the follow-ups were cut on 2026-09-27 it prints 66, 67, 69, and 70; 68 waits for 70.
