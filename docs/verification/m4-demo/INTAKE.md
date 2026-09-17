# Intake

What the owner handed over, normalized by `wayline intake`. `harness.json` holds the same autonomy, radius, fallback consent, budgets, and human-only classes, and is the copy the conductor reads.

## Intent

I keep reaching for UMAP to look at differentiation time courses, and I am not sure I should. I want to know whether UMAP is a sound default embedding for a small single-cell dynamics study: whether the picture it draws of a branching trajectory is faithful to the data, and whether it still holds on a timepoint the embedding never saw. If it is not, I want to know what to use instead.

## References

- 10.1038/s41586-020-2649-2
- [SciPy 1.0: fundamental algorithms for scientific computing in Python](https://doi.org/10.1038/s41592-019-0686-2)
- https://doi.org/10.1371/journal.pcbi.1008074
- 10.1101/2020.03.22.002386
- arXiv:1706.03762
- arxiv.org/abs/1802.03426
- arXiv:1912.01703
- Highly accurate protein structure prediction with AlphaFold
- Integrating single-cell transcriptomic data across different conditions, technologies, and species
- A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology

## Data

- data/cells.npz: a synthetic differentiation time course made by data/make_cells.py (seed 7): 480 cells (8 days x 60 cells), 50 genes, log-scale X, with day (0 to 7), branch (0 before the branch point, else 1 or 2), and pseudotime; one branch point
- day 7 is held out and never used to fit anything
- eval/sample_pca_day7.npz: the goal's sample artifact, PCA to two dimensions fitted on days 0 to 6 and applied to day 7 (made by eval/pca_sample.py)

## Code

None.

## Constraints

- The machine has one RTX 3090.
- The study may use at most 20 GPU hours.
- Day 7 is held out and never used to fit anything (no fitting, tuning, or model selection on it).
- The goal is measured by eval/trustworthiness.py (trustworthiness at k=15 on day 7) and is run from the project root.
- Assumed: data/make_cells.py, data/cells.npz, eval/trustworthiness.py, and eval/pca_sample.py are the owner's fixed material and must not change; new work adds code beside them.
- Assumed: the owner is not available for questions, so the defaults stand: autonomy checkpoints, radius moderate, no model-fallback consent recorded (behaves as ask), no wall-clock or usage-window limit stated, no human-only classes beyond goal and data. Checkpoint and decision tickets will wait for the owner.
- Assumed: the goal (trustworthiness_k15 >= 0.95 on day 7, stop when reached) measures only local neighbourhood preservation on the held-out day; it does not by itself say whether the branching trajectory is drawn faithfully, which the intent also asks. The goal is recorded as the owner wrote it; the run should not treat reaching it as answering the whole intent.
- Assumed: the references are recorded as the owner gave them. Several look unrelated to the question (e.g. arXiv:1706.03762, AlphaFold, and two that look like general scientific-Python tools) and the last title ('interpretive marmalade in high-dimensional sponge topology') may not exist; the scout should verify each and report any that do not resolve rather than substitute a guess.
- Assumed: the data is synthetic and small, so nothing is flagged as unable to leave the machine; no licence restrictions were stated.

## Autonomy

`checkpoints`: the owner approves the spec and the graph and answers decision tickets; waves run alone.

Fallback consent not stated, so the project behaves as under `ask`: while Fable's weekly window is spent, Fable work waits for the owner's answer on falling back, asked once per spent window by a human-only decision ticket.

## Radius

`moderate`: they may also add follow-ups that directly probe a claim's failure.

## Budgets

- GPU hours: 20
- Wall clock: not stated
- Usage windows: not stated

## Decisions that stay human-only

The decider never resolves these; they wait for the owner.

- `goal`: a decision that changes the goal: the metric, the target, the splits, or the command that measures it.
- `data`: a decision that changes the data: what is used, what is held out, or what may leave the machine.

## Goal

`GOAL.json` holds the goal: `trustworthiness_k15` up to 0.95 on the held-out split `day 7`, measured by `python3 eval/trustworthiness.py --embedding {artifact}`, stop when `goal_reached`. When intake checked it, `eval_command` printed 0.9206 with the sample artifact `<project>/eval/sample_pca_day7.npz`.
