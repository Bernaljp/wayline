# 103 - The run-end gates

**What to build:** The general report's claims are tested at every run end without the owner asking. **The run-end gates** run in a fixed order at each end:

1. the drawings of "100 - Drawings on the plotter", for every result changed since its last accepted drawing;
2. sampled claim verdicts on the general report: only claims never sampled, cached by sentence hash, 10 percent of them and at least ten, plus every difficulty-5 claim;
3. the kill argument on the general report, when it changed since the last one.

Both verdict gates file scope-downs, whose findings replace what they narrow.

What follows depends on how the run ended:

- **At the stopping rule's own ends** (`objectives_closed`, `goal_reached`, `frontier_empty`): the gates run first, and their scope-downs continue the run until an end holds with no gate owed.
- **After `budget_spent` or `stall_strict`**: they run once, their scope-downs wait for the next run, and the failed claims are marked.
- **After `stopped` or `switched`**: none run.

The one end notice from the account is sent after the gates. BRIEF P7's "one independent read" is dropped, and sampled verdicts no longer need running by hand.

Not part of this ticket:

- the decider's judgment of the paper order, which runs after these gates at the rule's own ends and is "120 - The decider orders the paper under autonomous";
- the gates of each build at the order, which are "117 - Builds at the order".

**Blocked by:** 87 - Keep-if-better per goal, the stopping rule, and budgets; GOAL.json retires; 90 - Results and the general report; 100 - Drawings on the plotter. It blocks 120.

**Status:** done

**GitHub:** [#250](https://github.com/Bernaljp/wayline/issues/250) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Keep-if-better per goal, the stopping rule, and budgets: the run-end gates; Results and the reports: sampled verdicts and the kill argument at a run end); Implementation Decision 11 (verification, the gates); Implementation Decision 5 (the conductor's end of a run); M8 criteria 3 and 5; user story 126.

- [x] At a run end, the conductor runs the drawings first, then sampled verdicts, then the kill argument, in that order, before it sends the end notice.
- [x] Sampled verdicts take only claims of the general report never sampled, cached by sentence hash: 10 percent, at least ten, plus every difficulty-5 claim. A re-run with no new claims samples nothing.
- [x] The kill argument runs on `REPORT.md` only when it changed since the last kill argument.
- [x] Scope-downs filed by either gate produce findings that name what they narrow in `replaces`.
- [x] At `objectives_closed`, `goal_reached`, and `frontier_empty`, scope-downs continue the run until an end holds with no gate owed. After `budget_spent` and `stall_strict` the gates run once, scope-downs wait for the next run, and failed claims are marked. After `stopped` and `switched` no gate runs.
- [x] The tick does not relaunch a run that ended with gates done, and it relaunches one that continues for scope-downs as the conductor's own run.
- [x] Tests by journal replay with the fake launcher scripting the plotter, the verifier, and the kill argument: each end kind, the sample cache across two runs, the difficulty-5 rule, an unchanged report skipping the kill argument, and idempotence of the replayed wave.
- [x] The CHANGELOG's `## Unreleased` entry describes the run-end gates.
- [x] `python -m unittest` passes.
