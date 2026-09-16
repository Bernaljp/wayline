# The sweep project

The M2 demo (ticket 19). Ticket 1 is an `experiment` for the `experimenter`: a three-member job
array over the learning rate of `scripts/train.py`, one GPU and four cores per member, with a GPU
out-of-memory ladder of one step (`--batch-size=256`). Its `0.3` member asks for a batch of 4096,
which holds 32 GiB of device memory on a 24 GB card and fails with `CUDA_ERROR_OUT_OF_MEMORY` until
the ladder retries it. Ticket 2 is an `analysis` for the `analyst`, blocked by ticket 1, which reads
the three manifested results and files findings.

`scripts/train.py` is standard library only: it trains a logistic regression on a synthetic set on
the CPU for `--seconds`, and holds `--batch-size` times 8 MiB on the GPU through the CUDA driver
with `ctypes` while it does.

`fake-worker.json` is what the fake worker returns: for ticket 1, a `running` result with the job
ids and the array it pipes to `wayline job add` (`jobs`); for ticket 2, a `done` result with one
finding on a manifested result and one on a result nobody produced, which the conductor refuses.
`tests/test_sweep.py` runs it with the fake job runner and the recorded machine of
`tests/machine.py`.

## Live

```
cp -r fixtures/projects/sweep /tmp/sweep && rm /tmp/sweep/fake-worker.json
WAYLINE_HOME=/tmp/sweep-home WAYLINE_UNITS=none bin/wayline init /tmp/sweep
WAYLINE_HOME=/tmp/sweep-home WAYLINE_UNITS=none bin/wayline run --project /tmp/sweep
```

The workers are real sessions and the jobs real `systemd-run` units; `docs/verification/m2.md`
records the run of 2026-09-16. `harness.json` sets `poll_seconds` to 10 so the jobs are polled
often enough to watch.
