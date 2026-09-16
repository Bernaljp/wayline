"""Train a logistic regression on a synthetic two-class set for a while, holding GPU memory in proportion to the batch.

The M2 sweep's experiment (ticket 19). Standard library only: the model trains on the CPU, and the
GPU is touched through the CUDA driver with `ctypes` (`cuMemAlloc`), because this machine has no
torch. The device memory held is `--batch-size` times `--mib-per-example`, so an oversized batch
fails the way a framework's does, with the driver's `CUDA_ERROR_OUT_OF_MEMORY` in the log and a
non-zero exit, and the footprint ladder's smaller batch succeeds. Without a CUDA driver the
allocation is skipped and said.

Writes `--out` as JSON: the settings, the held-out AUROC, the final loss, and how long it ran.
"""

import argparse
import ctypes
import json
import math
import os
import random
import sys
import time


def cuda_hold(mib):
    """Allocate `mib` MiB on device 0 and return the handle keeping it, or exit 1 with the driver's error name."""
    try:
        cuda = ctypes.CDLL("libcuda.so.1")
    except OSError:
        print("no CUDA driver; training on the CPU only", flush=True)
        return None
    device, context, pointer, name = ctypes.c_int(), ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_char_p()
    for call in (lambda: cuda.cuInit(0), lambda: cuda.cuDeviceGet(ctypes.byref(device), 0),
                 lambda: cuda.cuCtxCreate_v2(ctypes.byref(context), 0, device)):
        code = call()
        if code != 0:
            cuda.cuGetErrorName(code, ctypes.byref(name))
            if name.value == b"CUDA_ERROR_NO_DEVICE":
                print("no visible CUDA device; training on the CPU only", flush=True)
                return None
            print("CUDA setup failed: %s" % name.value.decode(), flush=True)
            sys.exit(1)
    code = cuda.cuMemAlloc_v2(ctypes.byref(pointer), ctypes.c_size_t(int(mib) * 1024 * 1024))
    if code != 0:
        cuda.cuGetErrorName(code, ctypes.byref(name))
        print("cuMemAlloc of %d MiB failed: %s" % (mib, name.value.decode()), flush=True)
        sys.exit(1)
    print("holding %d MiB on CUDA_VISIBLE_DEVICES=%s" % (mib, os.environ.get("CUDA_VISIBLE_DEVICES")), flush=True)
    return (cuda, context, pointer)


def synthetic(n, signal, rng):
    rows = []
    for _ in range(n):
        label = rng.random() < 0.5
        x = [rng.gauss(signal if label else -signal, 1.0), rng.gauss(0.0, 1.0)]
        rows.append((x, 1 if label else 0))
    return rows


def auroc(scores):
    positives = [score for score, label in scores if label]
    negatives = [score for score, label in scores if not label]
    wins = sum((p > q) + 0.5 * (p == q) for p in positives for q in negatives)
    return wins / (len(positives) * len(negatives))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--mib-per-example", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--signal", type=float, default=0.8)
    parser.add_argument("--out", required=True)
    options = parser.parse_args(argv)
    held = cuda_hold(options.batch_size * options.mib_per_example)
    rng = random.Random(options.seed)
    train, test = synthetic(4000, options.signal, rng), synthetic(1000, options.signal, rng)
    weights, bias, started, loss, epochs = [0.0, 0.0], 0.0, time.monotonic(), float("nan"), 0
    while time.monotonic() - started < options.seconds:
        rng.shuffle(train)
        total = 0.0
        for start in range(0, len(train), options.batch_size):
            batch = train[start:start + options.batch_size]
            grad, grad_bias = [0.0, 0.0], 0.0
            for x, y in batch:
                p = 1 / (1 + math.exp(-(weights[0] * x[0] + weights[1] * x[1] + bias)))
                total -= math.log(max(p if y else 1 - p, 1e-12))
                grad = [grad[0] + (p - y) * x[0], grad[1] + (p - y) * x[1]]
                grad_bias += p - y
            weights = [weights[i] - options.lr * grad[i] / len(batch) for i in range(2)]
            bias -= options.lr * grad_bias / len(batch)
        loss, epochs = total / len(train), epochs + 1
    scores = [(weights[0] * x[0] + weights[1] * x[1] + bias, y) for x, y in test]
    result = {"seed": options.seed, "lr": options.lr, "batch_size": options.batch_size, "epochs": epochs,
              "loss": round(loss, 6), "auroc": round(auroc(scores), 6),
              "seconds": round(time.monotonic() - started, 1), "gpu_held_mib": options.batch_size * options.mib_per_example if held else 0}
    os.makedirs(os.path.dirname(os.path.abspath(options.out)), exist_ok=True)
    with open(options.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
