# 76 - Objectives: the record and objective add

**What to build:** A project holds objectives, questions the research answers, in place of one required goal. `research/objectives.json`, written only by code and rendered as `research/OBJECTIVES.md`, holds objectives with ids O1 onward, never reused. Each has `id`, `text` (the question), `measure` (null, or `{metric, direction, target, held_out_split, eval_command, baseline: {value, source}, dataset_or_split, min_seeds}`), `status` (`open`, `parked`, `answered`, `dropped`, `reframed`), `answer` (null while open), `evidence` (locators in the linter's `res:` and `ref:` forms), and `reframed_as`. An objective with a measure is a **goal**; an objective has at most one measure.

`wayline objective add "<question>" [--measure <file> --sample <artifact>]` records an objective. With a measure, the objective becomes a goal only when its `eval_command` printed the metric on the sample artifact, the check intake runs on a goal today, moved here. A measure's `target` may be null (keep improving, never reached). A goal whose command is not ready is recorded as an objective without a measure, and the verb says so. Each change is journaled as an `objective` event (with `by`: `owner`, `decider`, or `code`), and `OBJECTIVES.md` re-renders.

`wayline switch --autonomy autonomous` refuses while no objective is open, so setup cannot end without one. `View.progress` gives way to the objectives' statuses, and `wayline status` reads an objective's status rather than the latest reading.

This is the expand step of an expand-contract over `GOAL.json`, which ten modules read today: those readers keep reading it in this ticket. 80 and 81 move them to objectives, and 87 retires `GOAL.json`.

Not part of this ticket:

- intake, position, the grill, and the decider reading objectives, and the `objective` human-only class (80);
- specify, claims' and tickets' `objectives`, and `goal` in place of `goal_metric` (81);
- keep-if-better per goal, the stopping rule, and `GOAL.json`'s retirement (87);
- objective proposals and their batch (91).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 80 and 81.

**Status:** done

**GitHub:** [#223](https://github.com/Bernaljp/wayline/issues/223) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (objectives, goals, and measures; defects found while charting: `View.progress` and `status`; vocabulary the build adds), 1 (the verb table: `objective add`; `switch --autonomy`), 2 (the event table: `objective`), the schemas list (`objectives`); M8 criterion 1; user stories 2, 102, 103, 104, 105.

- [x] `research/objectives.json` has a schema in the schemas list with every field above; ids run O1 onward and are never reused; only code writes it, through the ledger.
- [x] `wayline objective add "<question>"` records an open objective without a measure; with `--measure <file> --sample <artifact>` it records a goal only when the eval command printed the metric on the sample, and otherwise records an objective without a measure and says why.
- [x] A measure with `target: null` is accepted; a second measure on one objective is refused.
- [x] Each change journals an `objective` event with `by`, and `OBJECTIVES.md` renders the objectives in id order with status, measure, answer, and evidence.
- [x] `wayline switch --autonomy autonomous` refuses with no objective open and names `objective add`.
- [x] `View.progress` is replaced by the objectives' statuses, and `wayline status` shows each objective's status.
- [x] `GOAL.json` is still read by every current reader, and a project with both a `GOAL.json` and objectives behaves as today on its goal.
- [x] The verb table of decision 1 gains `objective add`, the event table of decision 2 gains `objective`, and the schemas list gains `objectives`, all in the same commit.
- [x] Tests as plain functions over a temporary project through the ledger seam: an objective recorded and rendered, a goal recorded after its command printed the metric on a sample, a goal refused into an objective without a measure, a null target, the autonomy switch refused and then allowed, `status` reading objective statuses, ids never reused after a drop.
- [x] The changelog describes objectives under `## Unreleased`.
- [x] `python -m unittest` passes.
