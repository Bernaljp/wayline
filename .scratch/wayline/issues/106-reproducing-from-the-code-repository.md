# 106 - Reproducing from the code repository

**What to build:** "Aligned" means that the code repository at the paper's tag recomputes every number and figure the paper prints. This ticket makes that checkable. 85 records the commit of `main` that every job and ticket run ran at. From that record code renders these files into `code/`:

- `code/REPRODUCE.md` and `code/reproduce.json`: per result, the commands that made the runs its findings cite, their inputs, outputs, time, and hardware;
- environment locks from the environment the jobs actually ran in: the project's `.venv` lock, an R `renv.lock`, a Julia environment, and the tools' entries in `tools.json`;
- `code/README.md`, keeping a part the owner writes.

The files render after every wave that changed `code/` or ran a job a finding cites. They go out with the code repository's next push.

Not part of this ticket:

- creating and pushing the code repository, and the commit on `job_launched` and `ticket_launched` (85);
- the software versions in Methods, which 108 renders from these locks;
- at the order: the `paper-N` tag, re-running stale results, the environment file, and the Dockerfile (119).

**Blocked by:**
- 82 - Project tools and the software decision
- 85 - The code repository

It blocks 108 and 119.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Methods and the code: "Aligned", `REPRODUCE.md`, `reproduce.json`, the locks, `README.md`; tools, packages, and environments: per-project packages locked in `code/`); milestone M8 criterion 13; user story 152.

- [ ] `code/REPRODUCE.md` and `code/reproduce.json` list, per result, each run its current findings cite. Each run gives its command, its commit of `main`, its inputs, outputs, wall-clock time, and hardware (GPUs held).
- [ ] The locks in `code/` come from the environment the cited jobs ran in, not from what is installed now. A tool a job called appears with the version and lock digest its job record carries.
- [ ] `code/README.md` renders from the records and keeps, word for word, a part the owner wrote between its markers.
- [ ] The files re-render after a wave that changed `code/` or ran a cited job, and only then. They are committed with the wave and pushed with the next push of the code repository.
- [ ] None of them names a path under `research/`, `jobs/`, or `results/` that the code repository does not hold.
- [ ] Tests, over a temporary project through the ledger seam, with fixture job records and results:
  - the rendered files;
  - an owner's part surviving a re-render;
  - a finding replaced by another, which changes the runs listed.
- [ ] The documentation site and the changelog's `## Unreleased` section describe `REPRODUCE.md` and the locks.
- [ ] `python -m unittest` passes.
