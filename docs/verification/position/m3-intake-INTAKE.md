# Intake

What the owner handed over, normalized by `wayline intake`. `harness.json` holds the same autonomy, radius, fallback consent, budgets, and human-only classes, and is the copy the conductor reads.

## Intent

Decide whether UMAP is a sound default embedding for a small single-cell dynamics study: about 3,000 cells of a mouse hematopoiesis time course over four timepoints, where the embedding is used to read differentiation trajectories and the neighbourhoods must survive a held-out timepoint.

## References

- 10.1038/s41586-020-2649-2
- [SciPy 1.0: fundamental algorithms for scientific computing in Python](https://doi.org/10.1038/s41592-019-0686-2)
- https://doi.org/10.1371/journal.pcbi.1008074
- 10.1101/2020.03.22.002386
- arXiv:1706.03762
- arxiv.org/abs/1802.03426 (primary: UMAP; code https://github.com/lmcinnes/umap at release-0.5.12)
- arXiv:1912.01703
- Highly accurate protein structure prediction with AlphaFold
- Integrating single-cell transcriptomic data across different conditions, technologies, and species
- A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology

## Data

- a 3,000-cell scRNA-seq time course, four timepoints (day 0, 2, 4, 7); day 7 is held out
- counts are already normalized and log-transformed; 2,000 highly variable genes

## Code

None.

## Constraints

- One RTX 3090 (24 GB) and 16 CPU cores; no cloud.
- At most 20 GPU hours.

## Autonomy

`checkpoints`: the owner approves the spec and the graph and answers decision tickets; waves run alone.

Fallback consent not stated, so the project behaves as under `ask`: while Fable's weekly window is spent, Fable work waits for the owner's answer on falling back, asked once per spent window by a human-only decision ticket.

## Radius

`moderate`: they may also add follow-ups that directly probe a claim's failure.

## Budgets

- GPU hours: not stated
- Wall clock: not stated
- Usage windows: not stated

## Decisions that stay human-only

The decider never resolves these; they wait for the owner.

- `goal`: a decision that changes the goal: the metric, the target, the splits, or the command that measures it.
- `data`: a decision that changes the data: what is used, what is held out, or what may leave the machine.

## Goal

No quantitative goal was stated. `wayline intake --goal <file> --sample <artifact>` adds one later.
