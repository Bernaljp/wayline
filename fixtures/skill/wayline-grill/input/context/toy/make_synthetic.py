"""The toy project's synthetic set: two classes whose signal lives partly in one feature interaction.

`python3 toy/make_synthetic.py --out data/synthetic.csv --seed 0` writes one row per example:
`split, label, x0 .. x7`. The label's log-odds are a linear term in x0 and x1 plus the product
x2 * x3, so a model without that product cannot recover all of the signal.
"""

import argparse
import csv
import math
import random

N_ROWS = 20000
N_FEATURES = 8
# The last quarter of the rows is split_b, the held-out split: no model trains or tunes on it.
HELD_OUT_FRACTION = 0.25
SIGNAL = 1.0
INTERACTION = 0.6


def make(seed=0, n_rows=N_ROWS, signal=SIGNAL, interaction=INTERACTION):
    rng = random.Random(seed)
    rows = []
    first_held_out = int(n_rows * (1 - HELD_OUT_FRACTION))
    for index in range(n_rows):
        x = [rng.gauss(0.0, 1.0) for _ in range(N_FEATURES)]
        logit = signal * (0.8 * x[0] - 0.5 * x[1]) + interaction * x[2] * x[3]
        label = 1 if rng.random() < 1.0 / (1.0 + math.exp(-logit)) else 0
        rows.append(["split_b" if index >= first_held_out else "split_a", label] + ["%.6f" % value for value in x])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/synthetic.csv")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--signal", type=float, default=SIGNAL)
    parser.add_argument("--interaction", type=float, default=INTERACTION)
    options = parser.parse_args()
    with open(options.out, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["split", "label"] + ["x%d" % index for index in range(N_FEATURES)])
        writer.writerows(make(options.seed, signal=options.signal, interaction=options.interaction))


if __name__ == "__main__":
    main()
