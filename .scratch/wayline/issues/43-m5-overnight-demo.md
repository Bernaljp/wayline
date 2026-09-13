# 43 - M5 overnight demo: the toy project end to end across a window boundary

**What to build:** The M5 demo, live: the toy project runs end to end overnight across a window boundary with proposals admitted under `moderate`, a stall replan, verification with `done` and `accepted`, goal progress tracked, `REPORT.md` with every claim tagged and the linter passing, a Fable fallback forced under consent `auto`, and a notification in the morning; the outputs index and the downloads work through an SSH tunnel from another machine.

**Blocked by:** 14 (The tick (verbatim prototype 29)), 36 (M4 live demo: from a vague intent to a graph with roles and skills), 37 (Proposals admission), 38 (Stall detection and the escalation chain), 39 (Keep-if-better under a quantitative goal), 40 (Provenance tags, the linter, and REPORT.md), 41 (The toy project fixture), 42 (Dashboard outputs, downloads, and logs), 54 (Hold only Fable launches while Fable's weekly window is spent), 55 (Fall back to Opus under the fallback consent), 56 (Verdicts on Opus and the verdict principle)

**Status:** ready-for-agent

**GitHub:** [#44](https://github.com/Bernaljp/wayline/issues/44) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** milestone M5 as a whole; Implementation Decisions 5, 7, 11, 15.

- [ ] The toy project is initialized, absorbed, positioned, grilled with the switch raised, specified, planned, and run detached in the evening; the run crosses a real five-hour window boundary, and the journal shows `paused` with the reset time and either the conductor's own continuation or the tick's relaunch.
- [ ] Over the night: proposals admitted under `moderate` and some parked; at least one stall replan (forced with a stalling configuration if the run does not stall on its own); verdicts turning `done` into `accepted`; `progress` events with kept and discarded changes; at least one escalation step live or forced with `--simulate-failure`; the weekly utilization handled with the same thresholds.
- [ ] A Fable fallback is forced under consent `auto` with `wayline run --simulate-limit fable:<seconds>`: the journal shows `paused` with `model: fable`, a Fable ticket and a verdict launched on Opus with `fallback_from`, and `REPORT.md` shows its section "Judged on Opus while Fable was spent"; `docs/verification/m5.md` records the excerpts.
- [ ] In the morning `REPORT.md` is rendered with every claim tagged, the linter passing, the verifier's sample passing, decider decisions first, "not pursued" and unread promotions listed, and a `notified` event delivered through `hermes send`.
- [ ] From another machine through `ssh -L`, the outputs index lists the results, a single file and a zipped directory download, and the logs view tails a job log.
- [ ] `docs/verification/m5.md` records the timeline, the window boundary, the journal excerpts, the report's linter output, and the tunnel session; the repository is tagged `v0.6.0`.
