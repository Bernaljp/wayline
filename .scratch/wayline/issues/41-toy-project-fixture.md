# 41 - The toy project fixture

**What to build:** A small but real research project the harness can run end to end overnight and every later live test can reuse: a synthetic dataset with a controllable signal, an intent about feature interaction terms and held-out AUROC, three synthetic references (one with a tiny code repository), a goal with a held-out split and an evaluation command, one GPU experiment that trains a small model in minutes with a retry ladder, and one deliberately oversized configuration that triggers a GPU out-of-memory once.

**Blocked by:** 17 (Job runner seam (verbatim prototype 27)), 28 (Intake and the goal)

**Status:** ready-for-agent

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 14 (the toy project); milestone M5 criterion 1.

- [ ] `fixtures/projects/toy/` holds the intent, a dataset generator with a seed and a signal-strength parameter, two short synthetic papers as PDFs and one as an arXiv-style source tarball with a tiny code repository at a pinned commit, `GOAL.json` (`metric: auroc`, `direction: up`, a reachable `target`, `held_out_split`, `eval_command`, `stop_when: goal_reached`), autonomy `autonomous` after intake, radius `moderate`.
- [ ] The experiment script trains a small model on the GPU in a few minutes, accepts batch size and dataloader-worker overrides for the `retry` ladder, and writes a metrics JSON per seed; an oversized configuration allocates beyond 24 GB so the first attempt is a GPU OOM that the ladder retries.
- [ ] `wayline init` from the fixture produces a project whose `absorb --level 0` resolves the three references from recorded responses and whose experiment ticket runs with fake jobs in the suite and on the GPU live.
- [ ] A README in the fixture explains what a full run should show (the M5 demo) so a later regression can be judged.
