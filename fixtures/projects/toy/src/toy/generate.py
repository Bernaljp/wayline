"""The synthetic two-class dataset (Implementation Decisions 14): a controllable signal, stdlib only.

Four features, `x1` through `x4`, drawn uniform on `[-1, 1]`. The label comes from a linear part
(`x1`, `x2`) plus one pairwise interaction term (`x3 * x4`), scaled by `--signal` and pushed through
a logistic and a coin flip, so the intent's question -- does modelling the interaction term help --
has a real answer: a model that only sees `x1..x4` is missing exactly the term the label depends on,
and one that also sees `x3 * x4` is not. `--seed` makes every row reproducible; `--signal` is how far
apart the two classes are, which is what keeps O1's target reachable without being trivial.
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

__all__ = ["FEATURES", "row", "generate", "write_split", "main"]

FEATURES = ("x1", "x2", "x3", "x4")
HELD_OUT_FRACTION = 0.2


def row(rng, signal):
    """One labelled row: `x1..x4` uniform on `[-1, 1]`, `y` from a linear part plus `x3 * x4`."""
    x1, x2, x3, x4 = (rng.uniform(-1.0, 1.0) for _ in FEATURES)
    interaction = x3 * x4
    latent = signal * (0.6 * x1 - 0.4 * x2 + 1.1 * interaction) + rng.gauss(0.0, 1.0)
    probability = 1.0 / (1.0 + math.exp(-latent))
    label = 1 if rng.random() < probability else 0
    return {"x1": x1, "x2": x2, "x3": x3, "x4": x4, "interaction": interaction, "y": label}


def generate(seed, signal=1.0, rows=4000):
    """`(train, held_out)`: `rows` labelled rows split `1 - HELD_OUT_FRACTION` / `HELD_OUT_FRACTION`.

    One `Random` draws every row in order, so `rows=8000` extends `rows=4000` rather than
    reshuffling it, and the held-out rows are the last drawn, never the first: a later ticket that
    asks for more rows does not silently change what the held-out split already measured.
    """
    rng = random.Random(seed)
    all_rows = [row(rng, signal) for _ in range(rows)]
    split = int(round(rows * (1.0 - HELD_OUT_FRACTION)))
    return all_rows[:split], all_rows[split:]


def write_split(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")


def read_split(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="toy.generate", description="write the synthetic dataset's two splits")
    parser.add_argument("--seed", type=int, required=True, help="the generator's seed")
    parser.add_argument("--signal", type=float, default=4.0, help="how far apart the two classes are (O1's reachable target assumes the default)")
    parser.add_argument("--rows", type=int, default=20000, help="total rows before the held-out split is taken off the end")
    parser.add_argument("--out", required=True, help="the directory to write train.jsonl, held_out.jsonl, and meta.json into")
    options = parser.parse_args(argv)
    out = Path(options.out)
    train, held_out = generate(options.seed, signal=options.signal, rows=options.rows)
    write_split(out / "train.jsonl", train)
    write_split(out / "held_out.jsonl", held_out)
    meta = {"seed": options.seed, "signal": options.signal, "rows": options.rows,
            "train_rows": len(train), "held_out_rows": len(held_out), "features": list(FEATURES)}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("train %d  held_out %d  -> %s" % (len(train), len(held_out), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
