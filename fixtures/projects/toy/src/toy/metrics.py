"""AUROC over plain Python lists, no dependency: what both `train` and a test can call."""

__all__ = ["auroc"]


def auroc(labels, scores):
    """The Mann-Whitney U statistic, normalized: `1.0` is perfect, `0.5` is chance, `None` if degenerate."""
    n = len(labels)
    if n == 0 or len(scores) != n:
        raise ValueError("labels and scores are the same length")
    positives = sum(1 for label in labels if label)
    negatives = n - positives
    if positives == 0 or negatives == 0:
        return None
    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    positive_rank_sum = sum(ranks[i] for i in range(n) if labels[i])
    return (positive_rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)
