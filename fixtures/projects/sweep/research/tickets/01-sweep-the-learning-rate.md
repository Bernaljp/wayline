---
id: 1
title: Sweep the learning rate
kind: experiment
difficulty: 2
status: open
blocked_by: []
touches: [sweep/]
resources:
  gpu: 1
  cpu: 4
  ram_gb: 4
  wallclock_minutes: 10
retry:
  gpu_oom: ["--batch-size=256"]
role: experimenter
skills: []
outputs: [results/sweep/lr-0.03.json, results/sweep/lr-0.1.json, results/sweep/lr-0.3.json]
acceptance:
  machine: ["python3 -m py_compile scripts/train.py"]
  quality: []
context_pack: [research/INTAKE.md, scripts/train.py:1-12]
origin: research/INTAKE.md#the-intent
proposed_by: planner
demo: "Three jobs, one per learning rate, each writing its JSON under results/sweep/, launched one GPU job at a time."
---

## Demo

`results/sweep/lr-0.03.json`, `lr-0.1.json`, and `lr-0.3.json` exist in the project and are in
`research/manifest.json`, each written by its own job.

## What to do

`scripts/train.py` is on `main` already. Write one job array of three members with
`wayline job add`, one per learning rate, each running

```
/usr/bin/python3 scripts/train.py --lr <rate> --seconds 60 --out results/sweep/lr-<rate>.json
```

with `--batch-size 4096` on the `0.3` member only (the sweep's deliberately oversized
configuration: its first attempt runs out of GPU memory, and the ticket's `retry` ladder runs it
again at 256) and the default batch on the other two. Each member's `expected_outputs` is its own
`--out` path. Record the three settings in `sweep/plan.md`, write the job spec to
`sweep/jobs.json`, commit both, run `wayline job add sweep/jobs.json`, and return `status: running`
with the three job ids.
