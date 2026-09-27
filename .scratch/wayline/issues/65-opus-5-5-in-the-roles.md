# 65 - Opus 5.5 in the roles and the verifier table

**What to build:** A project on the shipped policy runs its planner, writer, and evolver on `opus` at `xhigh` and its decider on `opus` at `max`, and takes every verdict on Opus-authored work in a fresh `opus` session at `max`. No role and no verdict draws on Fable's weekly window unless the project's `harness.json` puts one on Fable.

Why: since 2026-09-22, `--model opus` has launched Opus 5.5. It ranks above Fable 5.1 on every row of its system card's summary table, and on the matched probe Fable 5.1 costs about 2.9 times as much (`.scratch/model-tiers/research-notes/04-opus-5-5.md`).

The roles keep their efforts. These are the efforts decision 15 already gives the same roles when Fable work falls back to Opus, and their records are cut at `context_pack.max_chars.opus` the same way, so the shipped policy takes the harness's fallback shape as its default.

The verifier of an Opus author moves from `fable high` to `opus max`. The writer's claims therefore keep the `opus max` verifier they had while the writer ran on Fable. `gates.verifier_tier` already accepts an entry naming the author's own model, because a fresh session carrying none of the author's context is what makes a verdict.

Not part of this ticket:

- Rungs 6 and 7 of the rung ladder stay Fable until the owner answers the open points of note 04, section 4.
- A Fable author's verifier stays `opus max`.
- `RESOLVED_MODELS`, the fake launcher's answer for an alias, stays as it is, since the family match makes it harmless.

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 53, whose writer, decider, and verdicts it moves.

**Status:** done

**GitHub:** [#160](https://github.com/Bernaljp/wayline/issues/160) (mirror; the local file is the source)

**Milestone:** M7 Figures, docs, paper. **Spec:** Implementation Decisions 14 (the policy table: `roles`, `verifier`), 16 (the cap's sentence on `policy.roles`), 15 (what Fable work becomes on Opus), 11 (the verifier table as the default choice of a verifier); research note `.scratch/model-tiers/research-notes/04-opus-5-5.md`.

- [x] In `policy.json`, `roles.planner`, `roles.writer`, and `roles.evolver` are `opus` at `xhigh`, `roles.decider` is `opus` at `max`, and `verifier.opus` is `opus` at `max`. Every other role, `verifier.sonnet` (`opus high`), `verifier.fable` (`opus max`), `tiers`, `difficulty`, and `context_pack.max_chars` are unchanged.
- [x] The same commit updates:
  - decision 14's policy table, which `tests/spec_table.py` compares with `policy.json`;
  - the sentence of decision 16's cap that names the roles on Fable;
  - any other passage of the spec that names those roles' models or the Opus author's verifier;
  - the models `roles/README.md` names for the decider, the planner, and the evolver;
  - ticket 53's first criterion, which names the writer as `opus, xhigh`, in the ticket file and in its GitHub mirror (#54).
- [x] Work written on Opus is judged by a fresh `opus max` session, never the author's, and its `verdict` event carries no `fallback_from` at any reading of Fable's weekly window. Work written on Fable is still judged at `opus max`. Both are tested with the fake launcher.
- [x] With the shipped policy and Fable's weekly window read at 100%, the planner, the decider, `wayline report --verify` (the writer and its sampled verdicts), and `wayline evolve` launch without a hold and journal no fallback. This is tested with the fake launcher.
- [x] The Fable machinery keeps its coverage. The affected tests cover the hold, the fallback and its consent, verdicts while Fable is spent, the ask when Fable is spent, and the fallbacks of the decider, the planner, and the evolver. Each test that relied on a shipped role or verifier being on Fable builds its own policy with that role or verifier on Fable and still passes. No such test is deleted.
- [x] The planner and the decider read `context_pack.max_chars.opus` (200000), the cap decision 15 already gives them under the fallback, with any cut announced as before. The cap stays, since the decider's records on the M5 toy project come to 166,153 characters. A test pins the cap each reads on the shipped policy.
- [x] The changelog names the move and its reason under the next release.
- [x] `python -m unittest` passes.
