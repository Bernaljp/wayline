# 70 - The rung ladder without Fable

**What to build:** The shipped rung ladder stops at Opus 5.5. Rungs 6 and 7 (`fable low` and `fable high`) leave it, and `opus medium` joins between `opus low` and `opus high`. Difficulty 3 then starts on `opus medium`, and difficulties 4 and 5 on `opus high`. No shipped ticket work draws on Fable's weekly window. A project that puts Fable rungs back in its own `harness.json` keeps the hold, the step down on Fable's window, and the fallback, because those rules key on a rung's family.

Why: decision 16 keeps a rung only when it sits between its neighbors on cost and quality, and Opus 5.5 dominates Fable 5.1 on both (`.scratch/model-tiers/research-notes/04-opus-5-5.md`):

- **CursorBench 4.0:** Opus 5.5 at `medium` scores 52.5%, against Fable 5.1 at `max` with 51.8% and Opus 5 at `max` with 46.6%. It costs about $3 a problem, against $4 at `high` (system card, section 8.8).
- **FrontierCode:** Opus 5.5 peaks at `medium`.

The shipped rung ladder, cheapest first, in multiples of Opus 5 at `high` on the matched task:

| Rung | Model | Effort | Budget | Cost | Difficulty |
|---|---|---|---|---|---|
| 1 | `haiku` | `medium` | small | 0.16 | none |
| 2 | `sonnet` | `low` | small | about 0.35 | 1 |
| 3 | `sonnet` | `high` | small | 0.50 | 2 |
| 4 | `opus` | `low` | medium | not measured: the catalog gives Opus 5.5 no effort index and the card no figure | none |
| 5 | `opus` | `medium` | medium | about 0.54: rung 6's 0.72 at CursorBench's $3 against $4 | 3 |
| 6 | `opus` | `high` | large | 0.72, note 04's matched probe | 4 and 5 |

Rung 6 takes the `large` budget that difficulties 4 and 5 had on the Fable rungs, so hard tickets keep their turns and minutes. A difficulty 3 ticket that tiers up to rung 6 gets that budget too.

Not part of this ticket:

- the roles and the verifier table, which ticket 65 moved;
- measuring Opus 5.5 at `low`.

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 68, whose escalation tests are written against this rung ladder.

**Status:** ready-for-agent

**GitHub:** [#167](https://github.com/Bernaljp/wayline/issues/167) (mirror; the local file is the source)

**Milestone:** after M7 (v1.0.1). **Spec:** Implementation Decisions 16 (the rung ladder, the cap, the escalation chain by rung, pacing and the fallback by rung, what status shows), 14 (the policy table: `tiers`, `difficulty`), 15 (the hold and the fallback, for a project's own Fable rungs); research note 04.

- [ ] `policy.json`'s `tiers` is the six rungs above. `difficulty` maps level 1 to rung 2, level 2 to rung 3, level 3 to rung 5, and levels 4 and 5 to rung 6. The same commit changes decision 14's `tiers` and `difficulty` rows, which `tests/spec_table.py` compares with `policy.json`, and decision 16's ladder table.
- [ ] The spec's prose follows. That covers:
  - decision 16's cap, where difficulties 4 and 5 land;
  - the escalation chain by rung: a tier up now stays on Opus up to the top rung, so the split-first rule applies only to a project's own Fable rungs;
  - pacing and the fallback by rung;
  - the status examples: `r6 opus high`, with the Fable step-down example shown on a project's own ladder.

  Decision 15's rules are worded for a Fable rung wherever a project's rung ladder has one.
- [ ] Every rule about a Fable rung keys on the rung's family, never its index. That covers:
  - the hold;
  - the step down on Fable's window, from a project's top Fable rung to the one below it and no further;
  - the fallback to Opus at the same effort and budget;
  - `fallback_from` naming the rung.

  A project whose `harness.json` restores the seven-rung ladder behaves exactly as it did on v1.0.0.
- [ ] About 40 lines of tests across nine files exercised the shipped Fable rungs. They now run on a policy of their own with the seven-rung ladder and still pass, and none is deleted. The files are `test_fallback`, `test_escalation`, `test_conductor`, `test_fable_hold`, `test_fable_ask`, `test_rungs`, `test_step_down`, `test_verdict_fallback`, and `test_vocabulary`.
- [ ] New tests cover the shipped six rungs:
  - difficulty 3 launches on `r5 opus medium`;
  - its tier up goes to `r6 opus high`;
  - a failure on the top rung reaches the split, then `needs_human` with `reason: top_rung`.
- [ ] `wayline upgrade` across this change rewrites a project's `difficulty` override that names rungs of the old rung ladder. It reads each index against the `policy.json` of the tag the project was pinned to, by that rung's model and effort. Old rung 5 (`opus high`) becomes rung 6, and old rungs 6 and 7 (Fable) become rung 6. Each rewrite is printed. A project whose own `tiers` override defines its rung ladder is left as it is.
- [ ] The changelog names the change and its reason under the next release.
- [ ] `python -m unittest` passes.
