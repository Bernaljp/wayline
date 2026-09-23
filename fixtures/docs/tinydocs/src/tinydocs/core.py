"""Averages and counts."""


def mean(values):
    """The arithmetic mean of `values`, a non-empty sequence of numbers."""
    return sum(values) / len(values)


class Counter:
    """Counts what it is given."""

    def __init__(self):
        self.counts = {}

    def add(self, item):
        """Count `item` once more."""
        self.counts[item] = self.counts.get(item, 0) + 1


def undocumented_helper(value):
    return value * 2


def _private(value):
    return value
