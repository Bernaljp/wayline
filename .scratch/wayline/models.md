# Wayline tickets: which model and effort to implement each one

Graded on 2026-09-11 with the harness's own difficulty table (spec, Implementation Decisions 14, the `difficulty` row of `policy.json`, from BRIEF 8.4), so the tickets that build the harness are graded the way the harness will grade its own tickets. Ticket NN is GitHub issue NN+1 in `Bernaljp/wayline`; each issue also carries a `model:` label with its row of this table.

| Difficulty | Model | Effort | Tickets | Label |
|---|---|---|---|---|
| 1 | sonnet | low | none | |
| 2 | sonnet | medium | 12, 16, 18, 23, 25, 37, 41, 42, 48 (9) | `model:sonnet-medium` |
| 3 | opus | high | the other 31 | `model:opus-high` |
| 4 | fable | xhigh | 01, 03, 07, 30, 31, 32, 43, 45, 50, 53 (10) | `model:fable-xhigh` |
| 5 | fable | max | 05, 09, 34 (3) | `model:fable-max` |

No ticket is difficulty 1: `to-tickets` cut nothing that small, since every ticket is a tracer bullet with tests.

## How the grade was chosen

The grade is for the session that implements the ticket, not for the harness's own workers. A ticket goes up a tier when it:

- sets an interface many later tickets build on (the launcher seam, the conductor's wave, the planner);
- needs reasoning about concurrency or replay (two workers at once, a killed conductor, the journal as the bus);
- writes a role or skill prompt whose quality decides what every later project run produces (the grill, the decider, the verifier, the planner, the evolver, the figure designer, the writer);
- is a live demo across many modules, where diagnosing what broke is the work.

It goes down when the spec and the research notes already carry the exact commands, schemas, unit files, and decode tables, so the session mostly transcribes and tests.

## Launching at the right grade

Each ticket gets a fresh session. Pick the model and the effort on the command line, then call implement:

```
claude --model fable --effort xhigh
/implement .scratch/wayline/issues/03-worker-launcher-seam.md
```

Replace the alias (`sonnet`, `opus`, `fable`) and the effort (`medium`, `high`, `xhigh`, `max`) from the table. Follow-up fixes to a ticket already on `master` rarely need its grade: `/clear` and relaunch one tier down.

## By wave

Waves are the earliest start from `.scratch/wayline/waves.md`. The suggestion column says how to fill the window: one Fable session at a time, with sonnet-grade tickets of the same wave beside it.

| Wave | Tickets with their grade | Suggestion |
|---|---|---|
| 1 | 01 fable xhigh | Alone on `master`. |
| 2 | 02 opus high, 03 fable xhigh, 04 opus high | 03 first (the seam 05 needs most); 02 and 04 beside it. |
| 3 | 05 fable max, 11 opus high, 16 sonnet medium, 18 sonnet medium, 20 opus high | 05 alone at max with 16 and 18 as cheap fillers; 11 and 20 after. |
| 4 | 06 opus high, 07 fable xhigh, 12 sonnet medium, 17 opus high, 21 opus high, 23 sonnet medium, 25 sonnet medium, 27 opus high, 32 fable xhigh, 48 sonnet medium, 52 opus high | 06 first and alone (M0 demo, v0.1.0). Then 07 and 32 one at a time on Fable; 12, 23, 25, 48 fill the gaps. |
| 5 | 08 opus high, 09 fable max, 10 opus high, 19 opus high, 22 opus high, 28 opus high, 40 opus high, 42 sonnet medium, 49 opus high | 09 at max with 42 beside it; 08 and 10 after 09 (all three edit the conductor). |
| 6 | 13 opus high, 24 opus high, 30 fable xhigh, 39 opus high, 41 sonnet medium, 44 opus high | 30 on Fable with 41 beside it. |
| 7 | 14 opus high, 26 opus high, 31 fable xhigh, 46 opus high | 31 on Fable; 26 ends with the M3 demo (v0.4.0). |
| 8 | 15 opus high, 29 opus high, 33 opus high, 35 opus high, 37 sonnet medium | No Fable ticket; 15 is the M1 demo (v0.2.0), run it alone. |
| 9 | 34 fable max | Alone; five tickets wait on it. |
| 10 | 36 opus high, 38 opus high, 45 fable xhigh | 36 is the M4 demo (v0.5.0), alone on `master`; 45 on Fable after it. |
| 11 | 43 fable xhigh | The overnight run (v0.6.0); start it at the top of a window in the evening. |
| 12 | 47 opus high, 50 fable xhigh, 51 opus high | 50 on Fable; 47 is the M6 demo (v0.7.0). |
| 13 | 53 fable xhigh | The paper and the M7 demo (v1.0.0). |

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
| 08 Integration protocol and the integrator role | #9 | 5 | 3 | opus | high | Rebase, fast-forward, and a fresh integrator on conflict, with real git conflicts in the tests. |
| 09 Resume from the journal, heartbeat, control events, and worker re-adoption | #10 | 5 | 5 | fable | max | Idempotent replay, re-adopting live workers by pid and stream, SIGKILL mid-wave: the "journal is the bus" thesis. |
| 10 Pacing and pause on usage limits | #11 | 5 | 3 | opus | high | Utilization parsing and the three hit-limit signals; this is what keeps the overnight run alive at the window. |
| 11 Read-only dashboard: transport, tabs, journal tail, overview | #12 | 3 | 3 | opus | high | Threading server, ETags, and the server-sent events alternative; research-notes 08 carries the server. |
| 12 Dashboard graph, ticket pages, and logs endpoints | #13 | 4 | 2 | sonnet | medium | The 43-line layered layout is in the research note; the rest is endpoints and a page. |
| 13 User units, run --detach, and the notifier | #14 | 6 | 3 | opus | high | Touches the owner's systemd user manager and the credentials env file; the uninstall must leave nothing behind. |
| 14 The tick | #15 | 7 | 3 | opus | high | Many branches (login expiry, usage, heartbeat, jobs, relaunch) under a fake clock; a one-minute live test. |
| 15 M1 live demo | #16 | 8 | 3 | opus | high | The first cross-cutting live run; mostly running and recording with the owner at the laptop. |
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
| 35 Decision tickets end to end and dashboard actions | #36 | 8 | 3 | opus | high | Wires the conductor, the tick, the dashboard, and the CLI through four answer paths and nine token-guarded actions. |
| 36 M4 live demo | #37 | 10 | 3 | opus | high | The front door live end to end; the session runs the verbs and records (v0.5.0). |
| 37 Proposals admission | #38 | 8 | 2 | sonnet | medium | The admission rules are given verbatim (radius, similarity thresholds, caps) with a fake judge. |
| 38 Stall detection and the escalation chain | #39 | 10 | 3 | opus | high | The stall counter and the four-step escalation chain inside the wave; `--simulate-failure`. |
| 39 Keep-if-better under a quantitative goal | #40 | 6 | 3 | opus | high | Per-seed statistics, fast-forward only on a real gain, discarded branches kept as negative results. |
| 40 Provenance tags, the linter, and REPORT.md | #41 | 5 | 3 | opus | high | The tag grammar, the haiku classifier cache, the linter, the sampling rule, and the eleven-section report renderer. |
| 41 The toy project fixture | #42 | 6 | 2 | sonnet | medium | A synthetic dataset, a minutes-long trainer with one OOM configuration, three synthetic references, a README. |
| 42 Dashboard outputs, downloads, and logs | #43 | 5 | 2 | sonnet | medium | Range requests and zip streaming from research-notes 08; the outputs index. |
| 43 M5 overnight demo | #44 | 11 | 4 | fable | xhigh | The overnight run across a window boundary exercises everything; diagnosing the morning's journal is the work (v0.6.0). |
| 44 Fixture format and runner | #45 | 6 | 3 | opus | high | The fixture runner (structural checks over a JSONPath subset, the judged layer, caches, quarantine, exit codes) and the record verb. |
| 45 Feedback, change records, harness tickets, and local skills | #46 | 10 | 4 | fable | xhigh | The evolver's prompt, harness tickets on harness worktrees, hot-reloaded local changes, and the rule that `autonomous` only proposes global changes. |
| 46 Tags, pins, upgrade, rollback, and promotion | #47 | 7 | 3 | opus | high | Tags, pins, upgrade, and rollback move the harness's own checkout; a promotion branch runs the full fixture suite. |
| 47 M6 demo | #48 | 12 | 3 | opus | high | Feedback through the loop to a tag, live, with the suite offline in under a minute (v0.7.0). |
| 48 The plot index | #49 | 4 | 2 | sonnet | medium | Crawling five galleries through the seam into a metadata-only index; pitfalls rewritten from the owner's skill. |
| 49 Figure machine checks, schemas, and the house style | #50 | 5 | 3 | opus | high | Nineteen mechanical checks with PDF tools, SSIM regeneration, and CVD-simulated color distance, each with good and bad samples. |
| 50 The figure role pipeline end to end | #51 | 12 | 4 | fable | xhigh | The designer's and the critic's prompts carrying the honesty doctrine, the guided path's refusals, and sub-verdicts. |
| 51 The documentation site | #52 | 12 | 3 | opus | high | The documentarian role, Sphinx in the project's own environment, symbol and example checks. |
| 52 Venue guidelines | #53 | 4 | 3 | opus | high | Seventeen venues' rules from heterogeneous pages into one schema; seven manuscript checks. |
| 53 The paper and the M7 demo | #54 | 13 | 4 | fable | xhigh | The writer's prompt under the provenance rule, the build loop with the linter and the checks, the kill argument (v1.0.0). |

## Working the window

- Fable at `xhigh` or `max` uses the five-hour window fastest. Run one Fable session at a time and pair it with the sonnet-grade tickets of the same wave; start a `max` ticket (05, 09, 34) at the top of a window.
- The critical path (01, 02, 05, 27, 28, 30, 31, 33, 34, 36, 43, 50, 53) carries 8 of the 13 Fable tickets, so the Fable budget mostly goes to the chain that sets the calendar. Fill around it with opus and sonnet tickets.
- Escalation, the harness's own rule: a ticket that fails its acceptance twice at its grade is rerun one tier up in a fresh session (sonnet medium to opus high, opus high to fable xhigh). A ticket that sailed through is not a reason to lower the next one.
- A verdict before merging, the harness's own rule too: for difficulty 4 and 5 tickets, have a different model read the diff before `git merge --ff-only` (for example `/code-review` in a fresh opus session). The harness's verifier table pairs a fable author with an opus reader.
- Live demo tickets (06, 15, 19, 26, 36, 43, 47, 53) need the owner nearby for the tunnel, the phone, and the GPU; the model grade covers the diagnosis, the wallclock is the demo.

## What is ready right now, with its grade

```
gh api "repos/Bernaljp/wayline/issues?state=open&labels=ready-for-agent&per_page=100" \
  --jq '.[] | select(.issue_dependencies_summary.blocked_by == 0)
        | "#\(.number) \(.title)  [\([.labels[].name | select(startswith("model:")) | sub("model:"; "")] | join(","))]"'
```

Today it prints only `#2 01 - Package skeleton, ... [fable-xhigh]`.
