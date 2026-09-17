# Position

Rendered by `wayline position` from `research/position.json`: the claude-opus-5 critic's memo, read from the dossiers, `INTAKE.md`, and `GOAL.json` only.

**Intent.** The owner wants to know whether UMAP is a sound default 2-D embedding for a small single-cell differentiation time course: whether it draws a branching trajectory faithfully, and whether that picture holds for a timepoint the embedding never saw (day 7). If it does not, they want to know what to use instead.

## Closest prior work

- **mcinnes-2018-umap-uniform-manifold-approximation-projection**
  - title: *UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction* (2018)
  - identifier: arXiv:1802.03426
  - what it reports: The abstract presents UMAP as a manifold-learning method built on Riemannian geometry and algebraic topology. It says UMAP is competitive with t-SNE for visualization quality, arguably preserves more global structure, runs faster, and has no computational limit on embedding dimension.
  - bearing on the intent: This is the method under test, and the dossier has only the abstract (level 1). Its claim that UMAP 'arguably preserves more of the global structure' is the claim this study would check on a branching trajectory. The abstract says nothing about out-of-sample transform on unseen points or about distorted branches, so none of that is established by what was read.
  - read at: `research/refs/mcinnes-2018-umap-uniform-manifold-approximation-projection/dossier.json#abstract`
  - scout: verified (arxiv)
- **butler-2018-integrating-single-cell-transcriptomic-data**
  - title: *Integrating single-cell transcriptomic data across different conditions, technologies, and species* (2018)
  - identifier: doi:10.1038/nbt.4096
  - what it reports: The abstract introduces a Seurat strategy for integrating scRNA-seq datasets across conditions, technologies and species through shared sources of variation.
  - bearing on the intent: Only tangential. It is about aligning batches and datasets, not about whether an embedding is faithful or generalizes to an unseen timepoint. At most it is the single-cell toolkit context in which UMAP became a default.
  - read at: `research/refs/butler-2018-integrating-single-cell-transcriptomic-data/dossier.json#relation_to_intent`
  - scout: verified (crossref)
- **harris-2020-array-programming-numpy**
  - title: *Array programming with NumPy* (2020)
  - identifier: doi:10.1038/s41586-020-2649-2
  - what it reports: A review of NumPy's array-programming model and its role as the base of the scientific Python stack.
  - bearing on the intent: Infrastructure the analysis would cite as software. It has no bearing on the scientific question.
  - read at: `research/refs/harris-2020-array-programming-numpy/dossier.json#abstract`
  - scout: verified (crossref)
- **virtanen-2020-scipy-1-0-fundamental-algorithms**
  - title: *SciPy 1.0: fundamental algorithms for scientific computing in Python* (2020)
  - identifier: doi:10.1038/s41592-019-0686-2
  - what it reports: An overview of SciPy 1.0's capabilities and development practices.
  - bearing on the intent: A software citation only, for distance computations, rank correlations and similar. It has no bearing on the question.
  - read at: `research/refs/virtanen-2020-scipy-1-0-fundamental-algorithms/dossier.json#abstract`
  - scout: verified (crossref)
- **paszke-2019-pytorch-imperative-style-high-performance**
  - title: *PyTorch: An Imperative Style, High-Performance Deep Learning Library* (2019)
  - identifier: arXiv:1912.01703
  - what it reports: Describes PyTorch's design and performance as a deep learning library.
  - bearing on the intent: Relevant only if a parametric (neural-network) embedding is tried as the out-of-sample alternative. Otherwise it is a software citation.
  - read at: `research/refs/paszke-2019-pytorch-imperative-style-high-performance/dossier.json#abstract`
  - scout: verified (arxiv)

Dropped, because the scout did not verify them:

- *a-comprehensive-taxonomy-of-interpretive-marmalade-in-high-dimensional*: research/refs/a-comprehensive-taxonomy-of-interpretive-marmalade-in-high-dimensional/dossier.json says existence: unresolved.

### What the references lack

Work the critic expected beside these and did not find among the dossiers. It named these from what it knows, so the scout has checked none of them: add the ones you want with `wayline absorb`.

- Moon et al. 2019, 'Visualizing structure and transitions in high-dimensional biological data' (PHATE, Nature Biotechnology): a competing embedding designed specifically for branching and progression structure.
- Haghverdi, Buettner & Theis 2015, 'Diffusion maps for high-dimensional single-cell analysis of differentiation data' (Bioinformatics): the classical competitor for differentiation trajectories, with a Nyström-style out-of-sample extension.
- Wolf et al. 2019, 'PAGA: graph abstraction reconciles clustering with trajectory inference' (Genome Biology): graph-level topology and PAGA-initialized embeddings, a direct way to test branch faithfulness.
- Sainburg, McInnes & Gentner 2021, 'Parametric UMAP embeddings for representation and semisupervised learning' (Neural Computation): the natural way to embed an unseen timepoint, competing with umap's transform().
- Kobak & Linderman 2021, 'Initialization is critical for preserving global data structure in both t-SNE and UMAP' (Nature Biotechnology): a competing explanation for any global-structure advantage UMAP shows.
- Kobak & Berens 2019, 'The art of using t-SNE for single-cell transcriptomics' (Nature Communications): t-SNE as the main competing neighbour embedding, including adding new points to an existing embedding.
- Chari & Pachter 2023, 'The specious art of single-cell genomics' (PLOS Computational Biology): argues 2-D t-SNE/UMAP embeddings distort single-cell data; the strongest prior claim that could make the intent's answer foregone.
- Venna & Kaski 2001 (trustworthiness and continuity), and Saelens et al. 2019, 'A comparison of single-cell trajectory inference methods' (Nature Biotechnology): the source of the goal's metric and the standard for scoring trajectory topology.

## Feasibility

**Feasible with changes.** The question can be answered on this data, but only with three changes.

1. Add a faithfulness measure beyond trustworthiness at k=15. The intake itself notes that the goal measures only local neighbourhood preservation. Candidates: continuity, rank correlation of embedded order with ground-truth pseudotime, branch separability, and agreement of the embedding's graph topology with the known single branch point.
2. Do all model selection by validation inside days 0 to 6, e.g. fit on days 0 to 5 and score day 6, so that day 7 is touched once.
3. Report variance over embedding seeds and, ideally, over generator seeds. Other generator seeds are a data change, so that is the owner's decision.

The intake leaves several things unsaid:

- whether the embedding must be two-dimensional (eval/trustworthiness.py may not enforce it, and a higher-dimensional embedding would trivially raise trustworthiness);
- whether trustworthiness is computed within day 7 alone or against the training cells;
- how 'faithful branching' is to be judged;
- which methods count as 'instead';
- how an unseen day is to be embedded (UMAP transform(), parametric UMAP, or refitting with the held-out cells, which the day-7 rule forbids);
- the noise model of make_cells.py, which determines whether the task is easy by construction.

The references also do not support the question. Of the ten, only the UMAP paper bears on it directly, and only through its abstract. Several are unrelated (Transformer, AlphaFold, a SARS-CoV-2 interactome preprint, a heart-failure modelling paper at 10.1371/journal.pcbi.1008074, which may not be the paper the owner meant), and one does not resolve.

- compute: One RTX 3090 and at most 20 GPU hours. The data is 480 cells × 50 genes. At that size, PCA, UMAP, t-SNE, diffusion maps and PHATE each run in seconds on a CPU. Even a parametric UMAP or small autoencoder trains in minutes. Compute is not a constraint: a full sweep with many seeds fits in a small fraction of the budget, and most of the budget will go unused.
- data: data/cells.npz is one synthetic time course (seed 7): 8 days × 60 cells, 50 log-scale genes, one branch point. It has ground-truth day, branch and pseudotime labels, which is exactly what a faithfulness test needs. The held-out day 7 has only 60 cells, however, and as the last day it is probably all post-branch (branch 1 or 2). If so, the held-out test checks extrapolation along two branch tips, not whether the branch point itself is drawn faithfully. A single generator with a single seed also cannot show whether a verdict generalizes.

## Goal feasibility

The goal: trustworthiness_k15 at least 0.95, held out on day 7.

**Uncertain.** The target is trustworthiness_k15 ≥ 0.95 on day 7. The only measured number is the PCA-to-2D baseline: 0.9206, fitted on days 0 to 6 and measured by eval/trustworthiness.py, as recorded in INTAKE.md#Goal and GOAL.json#baseline. The gap is about 0.03.

A nonlinear method could plausibly close it, but nothing read supports a number. The UMAP dossier has only an abstract, with no out-of-sample or trustworthiness figures, and no dossier reports trustworthiness on comparable data.

Two features of the setup make the target harder to judge:

- Day 7 lies beyond the training days, so any fitted map is extrapolating rather than interpolating, and nonlinear out-of-sample maps (UMAP transform, parametric networks) often extrapolate worse than a linear projection.
- With 60 held-out cells and k=15, each cell's neighbourhood covers a quarter of the set, so the metric is coarse and sensitive to a few cells.

The target may be reachable, or PCA may already be near the ceiling for a map fitted without day 7. A defensible target would be found in three steps:

1. Run the baselines first: PCA, UMAP with transform(), parametric UMAP, t-SNE with point addition, and diffusion maps with Nyström extension. Score them under a pseudo-held-out split inside the training data (fit on days 0 to 5, score day 6 with the same metric).
2. Run a designed sweep over the settings that matter (n_neighbors, min_dist, initialization, input PCA dimension), over several seeds.
3. Take the best mean value under that split as the reference point for what day 7 can be expected to reach, then evaluate day 7 once.

Only the owner can change the goal. Reaching 0.95 would not by itself answer whether the branching is drawn faithfully.

## The hostile reviewer

1. The headline metric cannot answer the question: trustworthiness at k=15 rewards local neighbourhood preservation. An embedding can score 0.95 while tearing a branch apart, joining the two tips, or scrambling pseudotime order, so 'goal reached' would say nothing about faithful branching.
2. The result is planted and has n=1: one synthetic generator, one seed, one branch point, 50 genes. Whatever UMAP does here may be an artefact of how make_cells.py draws noise and branches, and nothing will transfer to real scRNA-seq with thousands of genes, dropout and batch structure.
3. The comparison set is missing or weak. The only baseline is 2-D PCA. Without PHATE, diffusion maps, t-SNE, PAGA-initialized UMAP and parametric UMAP under the same out-of-sample protocol, 'what to use instead' is unanswered.
4. The held-out design tests the wrong thing. Day 7 is probably entirely post-branch, so the branch point, the structure the intent cares most about, is never evaluated out of sample, and 60 cells with k=15 give a coarse, high-variance score.
5. No variance is reported. UMAP is stochastic and sensitive to n_neighbors, min_dist and initialization, and a 0.03 gap on 60 cells could sit inside seed-to-seed spread. Without repeated seeds and intervals, any ranking is noise.
6. Selection on the held-out day risks leakage. With 'stop when goal_reached', repeated evaluation on day 7 is itself model selection on the test set unless every choice is made on an internal split first.
7. Prior work may already settle the question: the critiques of 2-D single-cell embeddings, and the finding that UMAP's global-structure advantage comes largely from initialization, are not engaged. The reference list is mostly unrelated to the question (Transformer, AlphaFold, a SARS-CoV-2 interactome, a heart-failure model) and one reference does not exist.

## Three directions, by distance from the intent

Nearest first, none farther than the radius `moderate`.

1. **Out-of-sample benchmark with branch-aware metrics** (strict): Compare UMAP (with transform()) against PCA, t-SNE with point addition, diffusion maps with Nyström extension, PHATE, and parametric UMAP. Fit every method on days 0 to 6, embed day 7 without refitting, and score trustworthiness_k15 (the goal), continuity, pseudotime rank correlation and branch separability, over several seeds. The result answers directly whether UMAP is a sound default here and, if not, which method is better and on which criterion.
2. **UMAP sensitivity under an internal held-out split** (strict): Before touching day 7, fit on days 0 to 5, score day 6, and sweep UMAP's n_neighbors, min_dist, initialization (random, spectral, PCA) and input PCA dimension across seeds. Then evaluate the chosen settings once on day 7. This would show whether any verdict on UMAP depends on its defaults or on its seed, and it gives a defensible reference value for the 0.95 target without leaking the held-out day.
3. **Probe how UMAP fails on branch topology** (moderate): Build controls that probe the claim's failure directly: a copy of the data with the branch removed, to see whether UMAP invents a branch; label-permuted or noise-matched versions; and, if the owner approves the data change, other make_cells.py seeds and noise levels, including a split where the held-out cells straddle the branch point. The embedding's inferred topology (e.g. a kNN or PAGA-style graph) would be checked against the known single branch. This would show whether UMAP's picture of a branching trajectory can be trusted or is produced by the method itself.
