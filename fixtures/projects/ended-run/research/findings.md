# Findings

## Ticket 1

- `f-0001` The two label sources disagree on 3.1 percent of the held-out rows. (results/features/summary.json#label_disagreement)

## Ticket 2

- `f-0002` The baseline reaches a held-out AUROC of 0.812, with a standard deviation of 0.004 over three seeds. (results/baseline/summary.json#auroc_mean, results/baseline/summary.json#auroc_sd)

## Ticket 3

- `f-0003` Pairwise interaction terms raise the held-out AUROC to 0.861. That is more than ten baseline standard deviations above the baseline. (results/interactions/summary.json#auroc_mean, results/baseline/summary.json#auroc_sd)

## Ticket 4

- `f-0004` (negative) Doubling the model depth without interaction terms leaves the held-out AUROC at 0.815, within one standard deviation of the baseline. (results/depth/summary.json#auroc_mean, results/depth/summary.json#auroc_sd)
