# Sample report

<!-- wayline:records -->
A sample for the linter tests of ticket 40, read against `fixtures/projects/ended-run/`: every claim below is tagged and every tag resolves there. Each test breaks one sentence of it.
<!-- /wayline:records -->

## Findings

Pairwise interaction terms raise the held-out AUROC to 0.861.{res:t3-a1/results/interactions/summary.json#auroc_mean}

The baseline reaches a held-out AUROC of 0.812.{res:t2-a1/results/baseline/summary.json#auroc_mean} Next, the section turns to the references.

Interaction features were studied on tabular data before this run.{ref:paper-a#sec-2}

AUROC means the area under the receiver operating characteristic curve.

Each model was trained on three seeds.

| Run | AUROC |
|---|---|
| t3-a1 | 0.861 |

```
auroc 0.861 without a tag, inside a code block
```

## Negative results

Doubling the depth leaves the held-out AUROC within one standard deviation of the baseline.{res:t4-a1/results/depth/summary.json#auroc_mean}
