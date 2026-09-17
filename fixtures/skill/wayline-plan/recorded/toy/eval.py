"""Held-out AUROC of a predictions file: `python3 toy/eval.py predictions.csv` prints `auroc: <value>`.

The file has a header and one `label,score` row per held-out example of split_b.
"""

import csv
import sys


def auroc(pairs):
    """The probability that a random positive outscores a random negative, ties counted half."""
    ranked = sorted(pairs, key=lambda pair: pair[1])
    positives = sum(1 for label, _ in ranked if label == 1)
    negatives = len(ranked) - positives
    if not positives or not negatives:
        raise SystemExit("auroc needs both classes in the predictions")
    rank_sum, index = 0.0, 0
    while index < len(ranked):
        end = index
        while end + 1 < len(ranked) and ranked[end + 1][1] == ranked[index][1]:
            end += 1
        average_rank = (index + end) / 2.0 + 1
        rank_sum += average_rank * sum(1 for label, _ in ranked[index:end + 1] if label == 1)
        index = end + 1
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def main(path):
    with open(path, newline="") as handle:
        pairs = [(int(row["label"]), float(row["score"])) for row in csv.DictReader(handle)]
    print("auroc: %.4f" % auroc(pairs))


if __name__ == "__main__":
    main(sys.argv[1])
