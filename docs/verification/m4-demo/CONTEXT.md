# Context

The vocabulary this project's spec, tickets, and report use verbatim, settled in the grill. `wayline grill term` adds a term or replaces its definition; everything else in this file is kept as written.

## Language

**Faithful**:
A 2-D embedding is faithful when a person reading the plot would draw the same trajectory the generator made: the same single branch point and the same ordering of days (the owner's definition).
_Avoid_: accurate, correct

**Embedding**:
A two-dimensional map of cells produced by one method under one configuration and seed; every embedding the study scores is 2-D.
_Avoid_: projection, layout

**Held-out day**:
Day 7 of data/cells.npz, never used to fit, tune or select anything; each final configuration is embedded onto it and scored once, and the goal is read there.
_Avoid_: test set, validation day

**Internal split**:
One of the two splits inside days 0 to 6 used for every choice of settings: fit on days 0-4 and score day 5, or fit on days 0-5 and score day 6; choices use the average over both.
_Avoid_: validation set, dev split

**Replicate dataset**:
A time course made by the same generator as data/cells.npz with the same parameters but a different random seed (about ten of them), written by a new script beside make_cells.py, which itself stays unchanged.
_Avoid_: synthetic replicate, bootstrap sample

**Faithfulness measures**:
The six scores that make up the verdict on an embedding: trustworthiness_k15 (the goal's metric), continuity at k=15, Spearman correlation of embedding-derived pseudotime with the true pseudotime over training and held-out cells together, the day-order correlation, branch separability (kNN accuracy of branch 1 vs 2), and agreement of the embedding's kNN-graph topology with the single known branch point. Plot panels are made for the owner to inspect and are not scored.
_Avoid_: quality metrics

**Seed interval**:
The mean of a score over 20 embedding seeds of one configuration, with its 95% bootstrap interval.
_Avoid_: error bar, confidence band

**Comparison set**:
The seven embedding methods the study compares: UMAP, PCA, t-SNE, diffusion maps, PHATE, parametric UMAP, and PAGA-initialized UMAP.
_Avoid_: baselines, competitors

**Null control**:
A dataset from a new script beside make_cells.py that changes one thing about the generator: the no-branch copy (branch latent columns zeroed), or a noise-sweep copy (noise sd 0.3, 0.6 or 1.2). make_cells.py itself is unchanged.
_Avoid_: negative control, ablation

**Day-order correlation**:
Spearman correlation between the order of cells read off a 2-D embedding and their day labels; it scores the 'same ordering of days' part of Faithful.
_Avoid_: time correlation

**Verdict scope**:
The report's verdict holds for this generator family only; transfer to real scRNA-seq data is stated as an anti-claim.
