# Position

Rendered by `wayline position` from `research/position.json`: the claude-opus-5 critic's memo, read from the dossiers, `INTAKE.md`, and `GOAL.json` only.

**Intent.** Decide whether UMAP should be the default 2-D embedding for reading differentiation trajectories in a roughly 3,000-cell, four-timepoint (days 0, 2, 4, 7) mouse haematopoiesis scRNA-seq time course, where the test is whether local neighbourhoods still hold when day 7 is held out.

## Closest prior work

- **mcinnes-2018-umap-uniform-manifold-approximation-projection**
  - title: *UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction* (2018)
  - identifier: arXiv:1802.03426
  - what it reports: The abstract says UMAP is built on Riemannian geometry and algebraic topology, is competitive with t-SNE on visualisation quality, 'arguably preserves more of the global structure', runs faster, and has no computational limit on embedding dimension.
  - bearing on the intent: This is the method under test and the source of the claims the project would check. Its claims are comparative and hedged ('arguably'), and the abstract says nothing about trajectories, stability across seeds, or embedding held-out points. The project has to measure those itself. This is only an abstract-level read (level 1); no full read was done.
  - read at: `research/refs/mcinnes-2018-umap-uniform-manifold-approximation-projection/dossier.json#abstract`
  - scout: verified (arxiv)
- **butler-2018-integrating-single-cell-transcriptomic-data**
  - title: *Integrating single-cell transcriptomic data across different conditions, technologies, and species* (2018)
  - identifier: doi:10.1038/nbt.4096
  - what it reports: The abstract says Seurat integrates scRNA-seq datasets across conditions, technologies and species by using shared sources of variation. One of its examples is haematopoietic progenitors profiled with two technologies, where it learns distinct or transitional cell states jointly.
  - bearing on the intent: This bears on the question only indirectly. Timepoints sequenced separately may carry batch effects, and those can masquerade as or break neighbourhoods across days. So the project must decide whether integration comes before any embedding comparison. It says nothing about whether UMAP itself is sound.
  - read at: `research/refs/butler-2018-integrating-single-cell-transcriptomic-data/dossier.json#abstract`
  - scout: verified (crossref)
- **harris-2020-array-programming-numpy**
  - title: *Array programming with NumPy* (2020)
  - identifier: doi:10.1038/s41586-020-2649-2
  - what it reports: A review of array programming and NumPy's place in the scientific Python ecosystem.
  - bearing on the intent: Tooling only. The pipeline would run on it, but it has no bearing on whether UMAP is suitable.
  - read at: `research/refs/harris-2020-array-programming-numpy/dossier.json#relation_to_intent`
  - scout: verified (crossref)
- **virtanen-2020-scipy-1-0-fundamental-algorithms**
  - title: *SciPy 1.0: fundamental algorithms for scientific computing in Python* (2020)
  - identifier: doi:10.1038/s41592-019-0686-2
  - what it reports: An overview of the capabilities and development practices of SciPy 1.0.
  - bearing on the intent: Tooling only; it has no bearing on the scientific question.
  - read at: `research/refs/virtanen-2020-scipy-1-0-fundamental-algorithms/dossier.json#abstract`
  - scout: verified (crossref)

Dropped, because the scout did not verify them:

- *A comprehensive taxonomy of interpretive marmalade in high-dimensional sponge topology*: research/refs/a-comprehensive-taxonomy-of-interpretive-marmalade-in-high-dimensional/dossier.json says existence: unresolved.

### What the references lack

Work the critic expected beside these and did not find among the dossiers. It named these from what it knows, so the scout has checked none of them: add the ones you want with `wayline absorb`.

- Kobak & Linderman (2021), 'Initialization is critical for preserving global data structure in both t-SNE and UMAP', Nature Biotechnology: argues that UMAP's apparent global-structure advantage comes largely from its initialisation.
- Chari & Pachter (2023), 'The specious art of single-cell genomics', PLoS Computational Biology: argues that 2-D t-SNE/UMAP embeddings distort neighbourhoods and should not be read quantitatively.
- Becht et al. (2019), 'Dimensionality reduction for visualizing single-cell data using UMAP', Nature Biotechnology: the paper that made UMAP the default in single-cell analysis.
- van der Maaten & Hinton (2008), t-SNE, and Kobak & Berens (2019), 'The art of using t-SNE for single-cell transcriptomics': the direct competitor and its single-cell best practice.
- Moon et al. (2019), PHATE, Nature Biotechnology, and Haghverdi et al. (2015/2016), diffusion maps and diffusion pseudotime: embeddings designed specifically for developmental trajectories, and so the competing methods for this exact task.
- Wolf et al. (2019), PAGA, Genome Biology: graph abstraction for reading trajectories without trusting 2-D embedding distances.
- Saelens et al. (2019), 'A comparison of single-cell trajectory inference methods', Nature Biotechnology: benchmark practice for trajectory fidelity.
- Venna & Kaski (2001/2006), trustworthiness and continuity; Sainburg et al. (2021), parametric UMAP: the metric the goal uses, and the standard way to embed held-out points.

## Feasibility

**Feasible with changes.** The intent can be carried out, with three changes.

1. Define 'sound' operationally: which metrics, compared against which alternative embeddings, over how many seeds.
2. Define what 'neighbourhoods survive a held-out timepoint' means computationally. Options are UMAP.transform of day 7 onto a days 0–4 fit, a refit on all days compared with the days 0–4 fit, or parametric UMAP.
3. Write the evaluation script. GOAL.json points to eval/trustworthiness.py, but the intake says there is no code.

The intake leaves several things unsaid:

- how many cells each day has (so how large day 7 is);
- whether PCA precedes the neighbour graph;
- which space trustworthiness is measured against (the 2,000 genes or the principal components);
- whether the timepoints were sequenced as separate batches, which Butler et al. suggest may need integration first;
- what ground truth there is for the trajectories;
- the number of seeds.

Only one of the nine resolved references (McInnes et al.) is on topic; two more (NumPy, SciPy) are tooling. The rest – Transformers, AlphaFold, PyTorch, a SARS-CoV-2 interactome, and a cardiac–renal model – have nothing to do with this question. One reference did not resolve and looks fabricated. The reference list should be pruned. Also, the intake says no quantitative goal was stated, yet GOAL.json has one; that inconsistency should be confirmed with you.

- compute: The intake states one RTX 3090 (24 GB), 16 CPU cores, no cloud, and at most 20 GPU hours. UMAP, t-SNE, PCA, diffusion maps and PHATE on 3,000 cells × 2,000 genes (or 30–50 principal components) each take seconds to a minute on CPU. A sweep of hundreds of runs over seeds and hyperparameters fits in a few CPU hours. The GPU is only needed for parametric UMAP, and even that is small. Compute is not a constraint.
- data: The intake states about 3,000 cells over days 0, 2, 4 and 7. Counts are already normalised and log-transformed, 2,000 highly variable genes are selected, and day 7 is held out. That is enough to compare embeddings on neighbourhood preservation. It is not enough, by itself, to judge whether trajectories are read correctly: the intake mentions no cell-type annotations, lineage labels, or known marker ordering to serve as ground truth.

## Goal feasibility

The goal: trustworthiness_k15 at least 0.98, held out on day 7.

**Uncertain.** GOAL.json asks for trustworthiness at k=15 of at least 0.98 on days 0 to 4, with day 7 held out. The baseline is null, and no dossier reports a trustworthiness value for UMAP or any competing method, on this data or on comparable data. The McInnes abstract gives only qualitative comparisons. So nothing I read supports 0.98 or any other number, and I propose no revised target.

Whether 0.98 is reachable depends on things GOAL.json does not fix:

- the reference space (the 2,000 genes or the principal components; a 2-D embedding usually scores higher against a 30-component PCA than against 2,000 noisy genes);
- the embedding dimension;
- how the held-out day enters the score.

There is also a mismatch between the goal and the question. The intent is a decision ('is UMAP a sound default?'), but the goal is an 'up' target with stop_when: goal_reached. That invites tuning UMAP until it crosses 0.98, which answers a different question. It also leaves out continuity, seed variance and trajectory fidelity.

A defensible target would be set like this:

1. Implement eval/trustworthiness.py with the reference space and the handling of day 7 fixed in writing.
2. Measure baselines on days 0–4 with at least 10 seeds each: PCA-2D, t-SNE, UMAP with default settings, diffusion maps and PHATE.
3. Run a designed sweep over the UMAP settings that matter: n_neighbors, min_dist, initialisation (spectral or PCA), and input dimension.
4. Take the best competitor's mean minus its seed spread as the reference point.

The target would then be either 'UMAP within that margin of the best alternative' or 'the best value the sweep reaches'. Any change to the metric, target or splits is yours to decide (a human-only goal decision).

## The hostile reviewer

1. The held-out test is ill-posed: day 7 cells are likely more differentiated states that are absent from days 0–4, so UMAP.transform can only place them onto the existing manifold. 'Neighbourhoods survive' then measures how well the method extrapolates, not whether it is sound, and a high score could simply mean day 7 cells were pulled onto earlier states.
2. Trustworthiness@15 measures only whether nearby points in the embedding are also nearby in the original space. It says nothing about continuity, distances between clusters, branch topology or pseudotime order, which are exactly what 'reading differentiation trajectories' depends on. A 0.98 target on this metric does not answer the stated question.
3. There is no comparison against the methods built for this task (diffusion maps/pseudotime, PHATE, PAGA, force-directed graphs, t-SNE with PCA initialisation), and without them 'UMAP is a sound default' cannot be judged.
4. A fixed target with stop_when: goal_reached turns a decision into hyperparameter hunting: tuning UMAP until it passes 0.98 on the same days it is scored on is selection bias, and it will not generalise.
5. The intake mentions no variance across seeds or subsamples. UMAP layouts are stochastic, and a single run per setting cannot support a claim that it is a 'default'.
6. Prior work already argues that 2-D UMAP/t-SNE neighbourhoods are heavily distorted (Chari & Pachter) and that UMAP's global-structure advantage is largely due to initialisation (Kobak & Linderman). Neither is among the references, so the project risks rediscovering a known result.
7. Possible confounding and leakage: if timepoints were sequenced as separate batches, day-specific batch effects shape the neighbourhoods; and if highly variable genes or PCA were fitted on all four days, including day 7, the held-out day is not really held out.
8. n=1 dataset of 3,000 cells: any conclusion about a 'default' embedding extends from a single small time course with no replicate dataset.

## Three directions, by distance from the intent

Nearest first, none farther than the radius `moderate`.

1. **Seeded benchmark of UMAP against trajectory-aware embeddings** (strict): Fit PCA, t-SNE (PCA initialisation), UMAP (spectral and PCA initialisation), diffusion maps and PHATE on days 0–4 with at least 10 seeds each. Score each on trustworthiness and continuity at several values of k, measured against a fixed reference space. This shows whether UMAP is within seed noise of the best alternative, which is the direct answer to 'sound default?', and it gives the goal a measured baseline.
2. **Held-out day 7: transform vs refit vs original space** (strict): Embed day 7 in three ways: UMAP.transform onto the days 0–4 fit, a full refit on all four days, and parametric UMAP. For each, compare the day 7 cells' k-nearest-neighbour sets with their neighbours in the original space, fitting highly variable genes and PCA on days 0–4 only. Sweep n_neighbors and min_dist. This shows whether neighbourhoods really survive the held-out timepoint, and under which settings they do not.
3. **Probe whether UMAP distorts trajectories** (moderate): Target the claim's failure directly. Compute pseudotime and branch assignments on the neighbour graph in the original space. Then check whether the ordering and branch topology read from each 2-D embedding agree with them (rank correlation, branch agreement) across seeds and subsamples. Optionally, add a simulated branching dataset with known topology. This shows whether a high trustworthiness score still hides distorted trajectories, which is the failure a hostile reviewer would push on.
