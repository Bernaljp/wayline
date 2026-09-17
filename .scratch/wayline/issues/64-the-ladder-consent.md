# 64 - The ladder consent

**What to build:** The owner decides at setup whether an autonomous run may change the rung ladder on its own. `ladder_changes` in `harness.json` is `auto` (under `autonomous`, the decider may approve a proposed change to `tiers` or `difficulty`) or `ask` (such a change is a `human_only` decision ticket of class `ladder` under every autonomy). A project without the key behaves as `ask`. The intake asks it beside autonomy and the fallback consent, with `ask` recommended, and the owner changes it at any moment with `wayline switch --ladder auto|ask` or the dashboard's action, built the way "55 - Fall back to Opus under the fallback consent" built `switch --fallback`. Under `interactive` and `checkpoints` it changes nothing, since the owner already answers every decision ticket. The change records that propose such changes arrive with "45 - Feedback, change records, harness tickets, and local skills", which this ticket unblocks.

**Blocked by:** None - can start immediately. Every module it edits is built.

**Status:** ready-for-agent

**GitHub:** [#147](https://github.com/Bernaljp/wayline/issues/147) (mirror; the local file is the source)

**Milestone:** M6 Evolve. **Spec:** milestone M6 criterion 9; Implementation Decisions 16 (the ladder consent and the evolve loop, the vocabulary the build adds), 1 (`harness.json`, the verb table: `switch --ladder`), 10 (intake, the decider's human-only classes), 8 (dashboard actions), 2 (the event table: the `control` command `ladder_changes`); user story 97.

- [ ] `ladder_changes` (`auto` or `ask`) is in the `harness.json` schema and asked by the intake beside autonomy and `model_fallback`, with `ask` recommended; a project without the key behaves as `ask`, and a missing key stays distinguishable from an explicit `ask`.
- [ ] `wayline switch --ladder auto|ask` writes `harness.json` first and then journals `control` with `command: ladder_changes` and `args: {ladder_changes: <value>}`, accepted at any time, with a conductor running or not; a `project` function is what the dashboard action calls; the verb table of decision 1 and the `control` enumeration of the event table gain it in the same commit.
- [ ] Under `autonomous`, when the consent is `ask` or unset, `ladder` is among the human-only classes the decider is given and a decision ticket of class `ladder` opens `human_only`; when it is `auto`, the decider may answer it; under `interactive` and `checkpoints` the consent changes nothing.
- [ ] The dashboard gains the `ladder_changes` action beside `model_fallback`, token-guarded like the other actions and built in the dashboard's designed style.
- [ ] Tests, as plain functions over a temporary project: the schema with each value and without the key; the intake's question and its recommended answer; `switch --ladder` writing and journaling in that order; the human-only classes under each autonomy and consent; the dashboard action over HTTP with and without the token.
- [ ] `python -m unittest` passes.
