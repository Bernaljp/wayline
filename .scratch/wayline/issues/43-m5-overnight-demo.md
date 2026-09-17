# 43 - M5 overnight demo: the toy project end to end across a window boundary

**What to build:** The M5 demo, live: the toy project runs end to end overnight across a window boundary with proposals admitted under `moderate`, a stall replan, verification with `done` and `accepted`, goal progress tracked, `REPORT.md` with every claim tagged and the linter passing, a Fable fallback forced under consent `auto`, the rung ladder shown live (a one rung tier up, a ticket ending at the ladder's top rung, and launches stepped down one rung), and a notification in the morning; the outputs index and the downloads work through an SSH tunnel from another machine.

**Blocked by:** 14 (The tick (verbatim prototype 29)), 36 (M4 live demo: from a vague intent to a graph with roles and skills), 37 (Proposals admission), 38 (Stall detection and the escalation chain), 39 (Keep-if-better under a quantitative goal), 40 (Provenance tags, the linter, and REPORT.md), 41 (The toy project fixture), 42 (Dashboard outputs, downloads, and logs), 54 (Hold only Fable launches while Fable's weekly window is spent), 55 (Fall back to Opus under the fallback consent), 56 (Verdicts on Opus and the verdict principle), 60 (The rung ladder), 61 (Escalation by rung), 62 (Pacing and the fallback by rung), 63 (The model that ran)

**Status:** ready-for-agent

**GitHub:** [#44](https://github.com/Bernaljp/wayline/issues/44) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** milestone M5 as a whole, criterion 18 for the rung ladder; Implementation Decisions 5, 7, 11, 15, 16.

- [ ] The toy project is initialized, absorbed, positioned, grilled with the switch raised, specified, planned, and run detached in the evening; the run crosses a real five-hour window boundary, and the journal shows `paused` with the reset time and either the conductor's own continuation or the tick's relaunch.
- [ ] Over the night: proposals admitted under `moderate` and some parked; at least one stall replan (forced with a stalling configuration if the run does not stall on its own); verdicts turning `done` into `accepted`; `progress` events with kept and discarded changes; at least one escalation step live or forced with `--simulate-failure`; the weekly utilization handled with the same thresholds.
- [ ] A Fable fallback is forced under consent `auto` with `wayline run --simulate-limit fable:<seconds>`: the journal shows `paused` with `model: fable`, a Fable ticket and a verdict launched on Opus with `fallback_from`, and `REPORT.md` shows its section "Judged on Opus while Fable was spent"; `docs/verification/m5.md` records the excerpts.
- [ ] A one rung tier up is forced with `wayline run --simulate-failure <id>`: the journal shows the failed attempt and the next `ticket_launched` one `rung` higher, and `wayline status` labels both launches `r<index> <model> <effort>`.
- [ ] A ticket forced to fail until it climbs to rung 7 ends `needs_human` with `reason: top_rung`, and `wayline status`, the dashboard, and `REPORT.md` show it as "at the ladder's top rung".
- [ ] `wayline run --simulate-limit` past `pacing.cheap_at` shows launches one rung down (a tier-up attempt excepted) and the `stepping down` note on the window line; `docs/verification/m5.md` records the excerpts of all three rung ladder criteria.
- [ ] In the morning `REPORT.md` is rendered with every claim tagged, the linter passing, the verifier's sample passing, decider decisions first, "not pursued" and unread promotions listed, and a `notified` event delivered through `hermes send`.
- [ ] From another machine through `ssh -L`, the outputs index lists the results, a single file and a zipped directory download, and the logs view tails a job log.
- [ ] `docs/verification/m5.md` records the timeline, the window boundary, the journal excerpts, the report's linter output, and the tunnel session; the repository is tagged `v0.6.0`.

## Notes

- **Forcing an escalation (the owner's choice, 2026-09-17, from ticket 38).** Start the run with `wayline run --detach --simulate-failure <id>`; `--detach` passes the flag to the unit. The flag lives only in that conductor: if the tick relaunches the conductor after a pause, the relaunched run no longer fails the ticket, so start it again with the flag if the chain has not reached `needs_human` yet. Under the default `stall.waves` of 2, a ticket that keeps failing also stalls the run, and the planner re-cuts the open tickets on Fable: that is the stall replan this demo asks for, and it is accepted as part of the demo. Since "61 - Escalation by rung", the chain's order is resume, then a one rung tier up before the split while the next rung is on the same model family, and the split first when the next rung is on Fable, then needs_human; a ticket starting at difficulty 3 (rung 5) therefore splits before it climbs onto Fable, and one at difficulty 5 (rung 7) reaches `needs_human` with `reason: top_rung` after its resume and split.
