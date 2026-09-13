# 56 - Verdicts on Opus and the verdict principle

**What to build:** A Type-B verdict never comes from the session that wrote the work, and it may come from the author's own model in a fresh session with none of the author's context. While Fable's weekly window is spent and the consent allows fallback, every verdict whose table verifier is Fable (ticket verdicts, claim sampling, both threads of the kill argument, the figure honesty verdict) and the depth spot-check are taken by a fresh Opus session at the table's effort; under `wait` they wait for the reset. Every judgment made by fallback is marked in the journal and listed in `REPORT.md`, and none is taken again after the reset.

**Blocked by:** 24 (The absorb workflow for L2), 55 (Fall back to Opus under the fallback consent)

**Status:** ready-for-agent

**GitHub:** [#103](https://github.com/Bernaljp/wayline/issues/103) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** milestone M5 criteria 4 and 12; Implementation Decisions 11 (Type-B verdicts, REPORT.md), 15 (verdicts while Fable is spent, judgments made by fallback, the vocabulary the build adds), 10 (the decider), 9 (the depth spot-check), 2 (the event table).

- [ ] `gates.verifier_tier` accepts a table entry naming the author's model; a verdict session is always a fresh launch carrying none of the author's context, never a resume of the authoring session or a subagent inside it; the model table in `policy.json` is unchanged.
- [ ] The absorb workflow's depth spot-check follows the same rule: its critic may run on the synthesizer's model in a fresh session, and it never runs on Haiku.
- [ ] While the hold stands under `auto`, a verdict whose table verifier is Fable goes to a fresh Opus session at the table verifier's effort (`fable high` becomes `opus high`), for ticket verdicts, claim sampling, both kill-argument threads, the figure honesty verdict, and the depth spot-check; under `wait`, or under `ask` before an answer, it waits and the ticket stays `done`; a difficulty-5 blocker still counts only when `accepted`.
- [ ] `verdict` carries `fallback_from`, and `decision` carries `model` and `fallback_from`, so the decider's decisions record the model they ran on; the keys land in the event table of Implementation Decisions 2.
- [ ] `REPORT.md` gains the section "Judged on Opus while Fable was spent" after the tickets closed `done` versus `accepted`, listing every verdict and decider answer that carries `fallback_from`; nothing is taken again after the reset.
- [ ] Tests: the fake launcher asserts the verifier's model and effort for each verdict kind under each consent; journal replay covers the verdicts queued under `wait` and launched under `auto`; the report section is rendered from a fixture journal.
