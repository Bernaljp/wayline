# Intake

Find whether adding feature interaction terms improves held-out AUROC on the synthetic set.

## References

- 10.9999/wayline.toy.a
- 10.9999/wayline.toy.b
- arXiv:2401.00001

## Data

`src/toy/generate.py` writes the synthetic set itself: `x1..x4` uniform on `[-1, 1]`, a label that
depends on a linear part and one pairwise interaction term (`x3 * x4`), and a fixed 80/20 split
into `train` and `held_out`. `--seed` reproduces a draw; `--signal` sets how far apart the two
classes are.

## Code

`fixtures/code/tiny-pkg.git` (tag `v0.1.0`, commit `5de2bb44acea3892f9e0fc5c7b5b401179889958`) is
the tiny repository the third reference's source tarball names: a small package `absorb --code`
can clone and inventory at that pinned commit.

## Constraints

One GPU, a few minutes per attempt. No external data leaves the machine.

## Autonomy

`autonomous` (BRIEF 6.2): after intake, the decider resolves every open question and decision
ticket not in a human-only class.

## Radius

`moderate` (BRIEF 6.3): the planner and the decider may add follow-ups that directly probe a
claim's failure, not new directions.

## Budgets

One GPU, a handful of usage windows: this is a demo project, not a research programme.

## Decisions that stay human-only

- `goal`: a decision that changes the goal: the metric, the target, the splits, or the command
  that measures it.
- `data`: a decision that changes the data: what is used, what is held out, or what may leave the
  machine.

## Goal

`auroc` up to `0.82` on the held-out split `held_out`, measured by
`PYTHONPATH=src python3 -m toy.eval --split held_out`, stop when `goal_reached`.
