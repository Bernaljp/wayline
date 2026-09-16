# Position

The critic's memo for the toy intent, read from the dossiers, `INTAKE.md`, and `GOAL.json` only.

## Closest prior work

| Reference | What it reports | Bearing on the intent | Scout |
|---|---|---|---|
| paper-a: *Interaction features for tabular classification* (2021), doi:10.5555/wayline.fixture.paper-a | Pairwise products of features added to a logistic regression raised AUROC on tabular sets whose labels depend on products of features, and changed nothing on sets whose labels do not. | The nearest work: the same comparison, on real data. | verified |
| paper-b: *Depth versus width in small tabular networks* (2023), doi:10.5555/wayline.fixture.paper-b | A deeper network given no explicit products matched a shallow one given them on its benchmarks. | The competing explanation: a flexible model may find the interaction without the terms. | verified |
| paper-c: *Label noise between annotation sources* (2019), doi:10.5555/wayline.fixture.paper-c | Disagreement between label sources caps the AUROC any model can reach. | Bears only if the labels are noisy beyond their own randomness. | verified |

*A tabular benchmark someone mentioned* did not resolve (`existence: unresolved`) and is dropped
from the table.

## Feasibility

Feasible with the stated compute and data. The generator writes the synthetic set, and a logistic
regression with or without pairwise products fits on a set of that size in seconds on a CPU; no GPU
is needed for the core comparison. The intake does not say which library fits the models.

## Goal feasibility

The goal is a held-out AUROC of 0.85 on `split_b`. The generator draws each label from a logistic
of a linear term and one product term, so no model can beat the AUROC of the true log-odds, and at
the generator's default strengths that ceiling may be close to 0.85. This memo cannot compute the
ceiling without running the generator. If the ceiling is below the target, the goal cannot be
reached by any model. Revised target: 0.83, or a target stated as a gain over the baseline (for
example 0.02 AUROC) rather than an absolute number.

## The hostile reviewer

1. The synthetic set plants the interaction, so recovering it shows only that the method recovers
   what was put there. The result says nothing about real data unless the generator's settings are
   varied.
2. A logistic regression without products is a weak baseline when paper-b reports that a flexible
   model finds interactions on its own; beating it may be beating a straw man.
3. One held-out split and one seed give no variance: a gain of 0.01 could be noise.
4. Trying every pairwise product when one was planted invites reading whichever product helps as a
   discovery.

## Three directions, by distance from the intent

1. **Nearest** (inside `strict`): logistic regression with and without pairwise products on the
   default synthetic set, over several seeds, scored by held-out AUROC on `split_b`.
2. **Moderate**: the same comparison, plus a flexible model without products (gradient-boosted trees
   or a small network) as the second baseline paper-b calls for.
3. **Exploratory**: sweep the generator's interaction strength and find the strength below which the
   products stop helping.
