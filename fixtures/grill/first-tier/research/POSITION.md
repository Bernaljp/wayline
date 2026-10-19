# Position

Rendered by `wayline position` from `research/position.json`: the claude-opus-5 critic's memo, read from the dossiers, `INTAKE.md`, and `OBJECTIVES.md` only.

**Intent.** Find whether adding pairwise feature interaction terms improves held-out AUROC on the synthetic set.

## Closest prior work

- **paper-a**
  - title: *Interaction features for tabular classification* (2021)
  - identifier: doi:10.5555/wayline.fixture.paper-a
  - what it reports: Pairwise products of features added to a logistic regression raised AUROC on tabular sets whose labels depend on products of features, and changed nothing on sets whose labels do not.
  - bearing on the intent: The nearest work: the same comparison, on real data.
  - read at: `research/refs/paper-a/dossier.json#relation_to_intent`
  - scout: verified (crossref)
- **paper-b**
  - title: *Depth versus width in small tabular networks* (2023)
  - identifier: doi:10.5555/wayline.fixture.paper-b
  - what it reports: A deeper network given no explicit products matched a shallow one given them on its benchmarks.
  - bearing on the intent: The competing explanation: a flexible model may find the interaction without the terms.
  - scout: verified (crossref)
- **paper-c**
  - title: *Label noise between annotation sources* (2019)
  - identifier: doi:10.5555/wayline.fixture.paper-c
  - what it reports: Disagreement between label sources caps the AUROC any model can reach.
  - bearing on the intent: Bears only if the labels are noisy beyond their own randomness.
  - read at: `research/refs/paper-c/dossier.json`
  - scout: verified (crossref)

Dropped, because the scout did not verify them:

- *paper-d*: research/refs/paper-d/dossier.json says existence: unresolved.

### What the references lack

Work the critic expected beside these and did not find among the dossiers. It named these from what it knows, so the scout has checked none of them: add the ones you want with `wayline absorb`.

- A gradient-boosted tree baseline, the usual strong model for tabular data, which none of the dossiers covers.

## Feasibility

**Feasible.** No GPU is needed for the core comparison. The intake does not say which library fits the models, nor how many seeds the generator is run with.

- compute: CPU only, as INTAKE.md states; a logistic regression with or without pairwise products fits on a set of this size in seconds.
- data: toy/make_synthetic.py writes the synthetic set and split_b is held out, which is enough to answer the question on synthetic data.

## Objectives

### O1 Do pairwise products raise the held-out AUROC on the synthetic set?

A goal: `auroc` up to 0.85 on the held-out split `split_b`, measured by `echo auroc: 0.5`.

**Uncertain.** The generator draws each label from a logistic of a linear term and one product term, so no model can beat the AUROC of the true log-odds, and at the generator's default strengths that ceiling may be close to the 0.85 target. The ceiling cannot be computed without running the generator.

Revised target: **0.83**. The goal is the owner's to change; this is a proposal.

- why it is reachable: Below the likely ceiling of the true log-odds at the default strengths, so a model can reach it.

### O2 Below what interaction strength do the products stop helping?

An objective without a measure.

**Reachable.** Sweeping the generator's interaction strength over a grid and refitting both models at each point answers it on the synthetic set in minutes on a CPU.

## The hostile reviewer

1. The synthetic set plants the interaction, so recovering it shows only that the method recovers what was put there.
2. A logistic regression without products is a weak baseline when paper-b reports that a flexible model finds interactions on its own.
3. One held-out split and one seed give no variance: a gain of 0.01 could be noise.
4. Trying every pairwise product when one was planted invites reading whichever product helps as a discovery.

## Three directions, by distance from the intent

Nearest first, none farther than the radius `exploratory`. The objectives each direction names are proposals: the grill's first tier asks the owner which the project takes, open or parked.

1. **The comparison as stated** (strict): Logistic regression with and without pairwise products on the default synthetic set, over several seeds, scored by held-out AUROC on split_b.
   - would pursue O1: Do pairwise products raise the held-out AUROC on the synthetic set?
2. **A flexible second baseline** (moderate): The same comparison, plus a flexible model without products (gradient-boosted trees or a small network), the second baseline paper-b calls for.
   - would pursue O1: Do pairwise products raise the held-out AUROC on the synthetic set?
   - proposes a new objective: Does a flexible model without products match the products on the synthetic set?
3. **Where the products stop helping** (exploratory): Sweep the generator's interaction strength and find the strength below which the products stop helping.
   - would pursue O2: Below what interaction strength do the products stop helping?
