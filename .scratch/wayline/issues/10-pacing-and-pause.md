# 10 - Pacing and pause on usage limits

**What to build:** The conductor slows down before the subscription window closes and pauses when it does: it reads the five-hour and weekly utilization from every worker's `rate_limit_event` and from `claude -p "/usage"` at start, launches nothing new above 0.90, only difficulty 1 and 2 above 0.80, recognizes a hit limit by any of three signals, journals `paused` with the reset time, keeps doing subscription-free work, and continues at the reset. `wayline run --simulate-limit <seconds>` fakes a hit limit so the whole path can be demonstrated in minutes, and `wayline status` shows the utilization and the current action.

**Blocked by:** 07 (Frontier, launchable subset, and two parallel workers), 09 (Resume from the journal, heartbeat, control events, and worker re-adoption; a sequencing edge added on 2026-09-12: all three M1 conductor tickets edit the same wave loop, and 09 rewrites the event replay that 08 and 10 extend)

**Status:** done

**GitHub:** [#11](https://github.com/Bernaljp/wayline/issues/11) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** Implementation Decisions 5 (pacing and pause, wave step 8), 3 (stream parsing), 14 (`pacing.stop_at`, `pacing.cheap_at`).

- [x] Utilization comes from every `rate_limit_event`'s `unifiedWindows.five_hour` and `seven_day` and from `claude -p "/usage" --output-format json` parsed with the two regexes of Implementation Decisions 5 at `run` start; the action is `stop` at or above `pacing.stop_at` on either window, `cheap_only` at or above `pacing.cheap_at`, else `normal`; `pacing` is journaled only on change; both thresholds are read from `harness.json`.
- [ ] Under `stop` or while paused nothing that needs a model launches; jobs, machine checks, index builds, and report rendering still run first in the wave.
- [x] A hit limit is any of: a `rate_limit_event` with `status: rejected`, a `result` with `api_error_status: 429`, or a non-zero exit whose stderr or result text contains "hit your" and "limit"; the conductor journals `paused` with `resets_at` from the event or the message, else the next known window reset, else now plus five hours, lets running workers finish, and continues at the reset with `unpaused`.
- [x] `wayline run --simulate-limit <seconds>` makes the launcher inject one `rate_limit_event` with `status: rejected` and a `resetsAt` that many seconds ahead on the next launch.
- [x] `wayline status` prints both utilizations, the action, and the pause with its reset time when paused.
- [x] Tests drive the fake launcher with events at 0.79, 0.81, and 0.91 on each window and a rejected event, and assert the actions, the `paused` payload, and that only jobs and checks ran while paused.
