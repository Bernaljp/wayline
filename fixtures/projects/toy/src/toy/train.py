"""The GPU experiment (Implementation Decisions 14): a few minutes on one GPU, one metrics JSON per seed.

Trains a one-layer logistic regression over `x1..x4` plus the `x3 * x4` interaction term (the
term `toy.generate`'s label depends on) and reports held-out AUROC. `--batch-size` sizes a
diagnostic step the training loop always runs before it starts: a batch-by-batch interaction gram
matrix (`X @ X.T`) it uses to down-weight interaction terms for rows that look like duplicates of
each other. At the shipped default this costs nothing; the ticket's oversized configuration passes
a `--batch-size` big enough that the gram matrix alone is larger than a 24 GB card, which is the
GPU OOM the ladder in `research/jobs/<id>.json`'s `retry.gpu_oom` steps down from (Implementation
Decisions 6). Real PyTorch prints one of `resources.GPU_OOM_SIGNATURES` (`CUDA out of memory`) on
that allocation, uncaught, which is what the job log needs for the conductor's OOM rule to see it.

Needs torch; run through the tools venv (`wayline tools install`) or on a machine that has it on
its default interpreter. `toy.generate` and `toy.metrics`, which this imports, do not.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toy.generate import FEATURES, generate  # noqa: E402
from toy.metrics import auroc  # noqa: E402

DEFAULT_MINIBATCH = 256


def ready_interactions(batch_size, device, torch):
    """The gram matrix the interaction weighting reads: `batch_size` rows, deliberately unclamped.

    This is the one line the whole fixture is built around: a normal `--batch-size` (a few
    hundred) allocates nothing a GPU notices, and the oversized configuration's `--batch-size`
    allocates `batch_size**2` floats, which is where the 24 GB card runs out.
    """
    return torch.zeros(batch_size, batch_size, device=device)


def featurize(torch, rows):
    x = torch.tensor([[row[name] for name in FEATURES] + [row["interaction"]] for row in rows], dtype=torch.float32)
    y = torch.tensor([[float(row["y"])] for row in rows], dtype=torch.float32)
    return x, y


def train(seed, signal, rows, batch_size, dataloader_workers, epochs, lr, device_name):
    import torch
    from torch.utils.data import DataLoader, TensorDataset

    torch.manual_seed(seed)
    device = torch.device(device_name)

    train_rows, held_out_rows = generate(seed, signal=signal, rows=rows)
    train_x, train_y = featurize(torch, train_rows)
    held_out_x, held_out_y = featurize(torch, held_out_rows)

    gram = ready_interactions(batch_size, device, torch)  # the line that OOMs when batch_size is oversized
    del gram

    model = torch.nn.Linear(train_x.shape[1], 1).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    loader = DataLoader(TensorDataset(train_x, train_y), batch_size=DEFAULT_MINIBATCH, shuffle=True,
                         num_workers=dataloader_workers)
    model.train()
    for _ in range(epochs):
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(batch_x.to(device)), batch_y.to(device))
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        scores = torch.sigmoid(model(held_out_x.to(device))).cpu().reshape(-1).tolist()
    labels = held_out_y.reshape(-1).tolist()
    return auroc(labels, scores)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="toy.train", description="train the toy model and write its held-out metrics")
    parser.add_argument("--seed", type=int, required=True, help="the generator's seed and torch's; the same seed across attempts is the same data")
    parser.add_argument("--signal", type=float, default=4.0)
    parser.add_argument("--rows", type=int, default=20000)
    parser.add_argument("--batch-size", type=int, default=256,
                         help="the interaction gram matrix's side; the retry ladder's gpu_oom step shrinks this")
    parser.add_argument("--dataloader-workers", type=int, default=0, help="DataLoader's num_workers; the retry ladder's host_oom step shrinks this")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--device", default=None, help="cuda or cpu; cuda when it is available, else cpu")
    parser.add_argument("--out", required=True, help="the summary JSON this attempt writes")
    options = parser.parse_args(argv)

    import torch  # deferred: generate --help and argument errors need no torch import at all

    device_name = options.device or ("cuda" if torch.cuda.is_available() else "cpu")
    started = time.monotonic()
    value = train(options.seed, options.signal, options.rows, options.batch_size, options.dataloader_workers,
                  options.epochs, options.lr, device_name)
    summary = {"seed": options.seed, "auroc": value, "batch_size": options.batch_size,
               "dataloader_workers": options.dataloader_workers, "device": device_name,
               "seconds": round(time.monotonic() - started, 1)}
    out = Path(options.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("auroc: %.4f" % value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
