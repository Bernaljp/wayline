# The toy project

Implementation Decisions 14, milestone M5's demo, and the regression project for the conductor's
live tests. The intent: find whether adding feature interaction terms improves held-out AUROC on a
synthetic set. It is small enough to run overnight and real enough that the answer is not a
foregone conclusion.

## What is here

- `research/INTAKE.md`, `research/GOAL.json`: the intent, three references, and a quantitative
  goal (`auroc` up to `0.82` on the held-out split, `stop_when: goal_reached`).
- `harness.json`: `autonomy: autonomous`, `radius: moderate` -- the settings this project runs
  under once intake is done, not the interactive settings intake itself might have used.
- `src/toy/generate.py`: the dataset. Four features uniform on `[-1, 1]`; the label depends on a
  linear part and one pairwise interaction term, `x3 * x4`, scaled by `--signal`; a fixed 80/20
  split into `train` and `held_out` taken off the end of one seeded draw. Stdlib only.
- `src/toy/train.py`: the GPU experiment. Trains a one-layer logistic regression over the four
  features plus the interaction term, reports held-out AUROC. `--batch-size` sizes a diagnostic
  interaction-gram matrix (`batch_size x batch_size`) the run always builds first; at the default
  (256) this costs nothing, and the oversized configuration's batch size (90000) is enough to ask
  a 24 GB card for more than it has. `--dataloader-workers` sizes the training `DataLoader`. Needs
  torch; run it through `wayline tools install`'s venv, or on a machine that already has it.
- `src/toy/eval.py`: `GOAL.json`'s `eval_command`. Reads a `toy.train` summary (`WAYLINE_ARTIFACT`,
  or a path argument) and prints `auroc: <value>`. Stdlib only.
- `materials/`: the three references' source material -- `paper-a.pdf` and `paper-b.pdf`, two
  short synthetic papers, and `paper-c-source.tar.gz`, an arXiv-style e-print source whose text
  names `fixtures/code/tiny-pkg.git` at its pinned tag `v0.1.0`
  (`5de2bb44acea3892f9e0fc5c7b5b401179889958`) as the code it released. Rebuilt by `make.py`.
- `fixtures/fetch/api.crossref.org/` and `fixtures/fetch/export.arxiv.org/` (outside this
  directory, alongside the harness's other recordings): the three references' Crossref and arXiv
  responses, hand-written because the references are invented, so `absorb --level 0` resolves them
  with no network. Also rebuilt by `make.py`.

None of `research/refs/`, `research/kb/`, `research/jobs/`, or anything else under `research/`
past `INTAKE.md` and `GOAL.json` is committed: those are what a run writes, and a run that has not
happened yet has none of them.

## Rebuilding the generated pieces

`research/INTAKE.md`, `research/GOAL.json`, and `harness.json` are hand-authored, the way
`fixtures/projects/ten-references/` and `fixtures/projects/m0-live/` are. Everything else that is
generated -- the two PDFs, the tarball, the three cassettes -- comes from `make.py`:

```
python3 fixtures/projects/toy/make.py
```

It needs `pdflatex` on the path. A rebuild that changes nothing in the sources here writes the
same bytes back.

## From a shell

Copy it out first, so nothing is written inside the harness checkout:

```
cp -r fixtures/projects/toy /tmp/toy
WAYLINE_HOME=/tmp/toy-home bin/wayline init /tmp/toy --email you@example.org
WAYLINE_HOME=/tmp/toy-home bin/wayline absorb --level 0 --project /tmp/toy --fixtures fixtures/fetch
PYTHONPATH=/tmp/toy/src ~/.wayline/tools/venv/bin/python -m toy.train --seed 1 \
    --out /tmp/toy/results/toy/seed-1/summary.json
```

The first two run offline; `absorb` resolves the three references from the recorded responses.
The third needs a real GPU and the tools venv (`wayline tools install`); on an RTX 3090 it finishes
in a few seconds and prints a held-out AUROC around 0.85, comfortably past `GOAL.json`'s target
of 0.82. Passing `--batch-size 90000` instead is the oversized configuration: it OOMs on the
interaction-gram allocation with a genuine `torch.OutOfMemoryError: CUDA out of memory`, uncaught,
which is what the log needs for the conductor's OOM rule (Implementation Decisions 6) to read it
as a GPU OOM rather than a plain failure -- and `research/jobs/<id>.json`'s `retry.gpu_oom` ladder
names exactly the override (`{"--batch-size": "256"}`) that recovers it on the next attempt, with
the very same seed and so the very same data.

## What a full run should show (the M5 demo)

An overnight run of this project, with `autonomous` autonomy and `moderate` radius, should show:

1. Intake already done (`INTAKE.md`, `GOAL.json` in place); `absorb --level 0` resolving the three
   references, and at least one of them going on to a level-1 read.
2. A planner graph with at least the baseline experiment (`toy.train` at the default batch size)
   and a follow-up that adds the interaction term explicitly to the ticket's own feature list if
   the plan does not already fold it into the one experiment ticket -- either way, a ticket whose
   `goal` names the objective whose measure's metric is `auroc`.
3. The experiment ticket launching a real GPU job, the fake-jobs path already covered by the
   suite (`tests/test_toy_project.py`'s `RetryLadderTest`) and the live path by
   `docs/verification/m5.md`.
4. At least one `progress` event with `metric: auroc`, and the run ending with `run_ended` and
   `reason: goal_reached` once a kept run's AUROC clears `0.82`.
5. `wayline report` rendering a `REPORT.md` whose goal trajectory section shows that progress and
   whose provenance linter passes.

A later regression that runs this project again and gets a different shape of run -- the goal
never reached, no GPU job launched, the references left unresolved -- is the project doing its
job: it is small enough that a difference like that points straight at what changed.
