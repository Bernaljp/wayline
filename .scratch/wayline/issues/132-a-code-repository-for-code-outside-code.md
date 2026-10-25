# 132 - A code repository for code that starts outside code/

**What to build:** A project whose own code already lives outside `code/` (a package under `src/`, tests under `tests/`) can take a code repository at setup, and the run never stops to ask about it.

On the toy's live run (ticket 122, `docs/verification/m8.md`), the owner answered Setup 7/10 with "a package, under MIT, in a new private repository". Three things followed:

- Recording it created the private remote `Bernaljp/toy` at once (11:43:48Z, during setup), with nothing to publish yet.
- The setup session told the owner "the plan's code tickets write under `src/toy/`; nothing in this setup keeps a separate `code/` directory, so the plan doesn't need re-cutting". But `keeps_code` is true as soon as `harness.json` has `code_repository`, and `touch_problem` then refuses a code ticket outside `code/` (`wayline/tickets.py`). Tickets 2, 3, and 5 had been cut before the answer and wrote `src/toy/`.
- When the stall rule re-cut the graph mid-run, the plan-time check refused the new code tickets, and the planner opened decision ticket 50, `human_only`, `blocking: subgraph`: how does the project's code get under `code/`? Under `autonomous`, after setup, the owner was asked a question setup should have settled. No verb moves a project's own code into `code/`, since intake's `--code` absorbs only a clone. The owner's stand-in answered "keep the old layout" and removed `code_repository` from `harness.json` by hand.

What to build:

- At Setup 7, when the project already has code outside `code/`, code (not the session) says so and offers the ways on in that one question: move it under `code/` now, by a verb, with the goal's `eval_command` and the cut tickets' paths rewritten in the same step (an `objective` change the owner's answer covers, since it is asked at setup); or no code repository yet.
- The remote is created when the code repository first has something to publish (the first integration under `code/`, or the paper order), not when setup records it.
- The setup reference's rule on re-cutting after Setup 7 is decided by code (`keeps_code` and the cut tickets' touch sets), not left to the session's reading.
- A plan-time refusal of a touch set outside `code/` during a run never opens a human-only ask under `autonomous`: the planner cuts within the rules, or the decider takes it within the radius.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#339](https://github.com/Bernaljp/wayline/issues/339) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (methods and the code: the code repository; setup's seventh question; under `autonomous` nothing is asked after setup); ticket 109; ticket 122's live record.

- [ ] Over a temporary project with `src/` and a measure naming it, Setup 7's package answer moves the code under `code/` by a verb, rewrites the measure's command, and leaves every cut code ticket accepted by the touch-set check.
- [ ] Recording a code repository creates no remote; the first publish does.
- [ ] A re-cut under `autonomous` with a code repository opens no human-only decision ticket; covered by replay.
- [ ] `python -m unittest` passes.
