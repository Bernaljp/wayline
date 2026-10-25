# 129 - Verdicts off the wave's path

**What to build:** A wave keeps reading results, launching jobs, and launching tickets while verdicts and decider sessions run.

On the toy's live run (ticket 122, `docs/verification/m8.md`), `_drain_verdicts` took every queued verdict ticket by ticket inside the wave, each a fresh Opus session of 5 to 9 minutes (two per ticket, quality and diff), and the decider on parked proposals ran the same way. While they ran nothing else moved: ticket 16's worker returned `running` with two GPU jobs at 15:16 local, and the conductor launched its jobs only at 16:14, 58 minutes later, after the verdicts of tickets 3, 5, and 6 and two parked-proposal decisions, with the GPU idle and `max_parallel_workers` 2 leaving a slot free. Those verdict-only waves then counted as two settling waves without progress, and the stall rule started a replan in the same second as the jobs launched (and once before, at 11:54Z). The decider on #28 held the first wave five minutes the same way. Later in the night the same held the sweeps back: E3's jobs run about ten minutes each, one at a time on the one GPU, yet they launched at 19:28Z, 19:48Z, 20:50Z, and 21:00Z, and job `t105-8` sat exited (`active exited`) for more than half an hour before a wave concluded it, with the GPU idle. On a 26-ticket graph that is hours of serial time against the run's wall-clock budget; the owner's stand-in raised the budget from 12 to 18 hours through a chat card to let the run finish.

- Verdict and decider sessions launch like workers, as processes the wave polls, under a slot count of their own (`policy.max_parallel_verdicts`, default 2), and the wave goes on reading results, launching jobs, and launching tickets.
- The hold on Fable's window, the pacing hold of the whole queue, and the rule that a ticket is accepted only once all its verdicts are in stay as they are.
- A conductor restarted while verdicts run re-adopts them as it re-adopts workers.
- A wave in which a verdict passed, a ticket is still in its verdicts, or a job is running is not a settling wave without progress for the stall rule.

**Blocked by:** None - can start immediately. It is the conductor's wave; nothing else edits it now.

**Status:** ready-for-agent

**GitHub:** [#336](https://github.com/Bernaljp/wayline/issues/336) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 5 (the wave), 11 (verdicts), 14 (the policy table); ticket 122's live record.

- [ ] A recorded journal with a running result and two queued verdicts launches the result's jobs in the same wave as the verdicts, with the fake launcher.
- [ ] Two waves spent on verdicts with a passing verdict start no stall replan; covered by replay.
- [ ] The policy table gains `max_parallel_verdicts` in the same commit as the code.
- [ ] `python -m unittest` passes.
