# 54 - Hold only Fable launches while Fable's weekly window is spent

**What to build:** When Fable's weekly window is spent, the run keeps going on every other model: a Fable refusal, or Fable's `/usage` reading at the stop threshold, holds only the launches that would run on Fable (tickets, verdicts, the depth spot-check, and the planner, decider, writer, and evolver sessions) while running Fable sessions finish, and Fable work resumes at the reset. A refused session is launched again, never resumed. The owner sees Fable's utilization in `wayline status` and can force the whole path with `--simulate-limit fable:<seconds>`. Until "55 - Fall back to Opus under the fallback consent" lands, every held launch waits for the reset. This ticket is the first build ticket of the Fable fallback map and replaces what "10 - Pacing and pause on usage limits" does on a Fable refusal today: pause the whole run, and resume the refused session in `gates.take_verdict`.

**Blocked by:** 10 (Pacing and pause on usage limits)

**Status:** ready-for-agent

**GitHub:** [#101](https://github.com/Bernaljp/wayline/issues/101) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** milestone M1 criterion 14; Implementation Decisions 15 (reading the window, the hold, the vocabulary the build adds), 5 (pacing and pause, wave step 8, resume), 3 (the stream, resume), 2 (the event table), 1 (`--simulate-limit`).

- [ ] Fable's weekly window is read from the Fable line of `/usage` (`Current week \(Fable\): (\d+)% used · resets (.+?) \(`) at `run` start and before any wave that would launch Fable work, and from a Fable session's own `rate_limit_event` of type `seven_day_overage_included`; the `pacing` event gains `fable`, added to the event table of Implementation Decisions 2 together with its ledger constant.
- [ ] A Fable refusal is recognized in each of its forms: a rejected `rate_limit_event` of type `seven_day_overage_included`; a `result` with `api_error_status: 429` on a Fable launch; the text signal, which now matches "reached your" as well as "hit your" beside "limit"; a subagent's failed task with `error: rate_limit` naming Fable inside an allowed session's stream, whose own `result` stays a success.
- [ ] A refusal, or `pacing.fable` at or above `pacing.stop_at`, journals `paused` with `model: fable` and `window: seven_day` instead of the whole-run pause (`pacing.cheap_at` never applies to Fable's window); `unpaused` with `model: fable` follows at the refusal's `resets_at`, or earlier when `/usage` reads Fable under `stop_at`; a whole-run pause can start and end inside the hold; `model` on both events lands in the event table of Implementation Decisions 2.
- [ ] While the hold stands, launchable drops every launch whose model is Fable or that defines an agent on Fable, and every other launch proceeds; a done ticket any of whose verdicts needs Fable keeps its verdicts queued whole; replay rebuilds the hold, and replaying twice yields the same view.
- [ ] A session refused before its first turn is relaunched and never resumed, by every launch path, `gates.take_verdict` included (it raises `UsageLimited` rather than resuming); a Fable session stopped mid-work waits and is resumed on Fable after the reset.
- [ ] `wayline run --simulate-limit fable:<seconds>` injects one rejected `rate_limit_event` of type `seven_day_overage_included` on the next Fable launch, with a `resetsAt` that many seconds ahead; `--simulate-limit <seconds>` keeps its meaning.
- [ ] `wayline status` and the dashboard overview show `fable <N>` on the window line.
- [ ] Tests: the fake launcher scripted with each refusal form and a graph mixing Fable and Opus tickets; the conductor by journal replay (the hold, the dropped launches, the reset, a whole-run pause inside the hold, idempotence); the `/usage` parser and the signals in the pacing tests, with the recorded streams of the research note on the branch `research/fable-weekly-window`.
