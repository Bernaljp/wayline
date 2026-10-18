# 119 - Code at the order

**What to build:** At the paper order, the code repository at the paper's tag recomputes every number and figure the paper prints. Before the writer launches, code runs its steps:

1. Tag `paper-N` on `main` and push the code repository's split with the tag.
2. Re-run at that tag every result whose code changed since its run. A result whose numbers moved gets a ticket; otherwise the re-run stands with no ticket.
3. Copy the scripts behind every figure and every cited drawing number into `code/figures/`.
4. Run the code-to-Methods check over all of `code/`, not only a diff.

Whatever the environment setting, the order also writes an environment file and a Dockerfile into `code/` from the same locks. A repository still private at the order is listed under "Waiting on you".

Not part of this ticket:

- the code repository, the split, and the push after waves, which are 85's;
- `REPRODUCE.md`, `reproduce.json`, and the locks, which are 106's;
- the code-to-Methods check itself, which is 107's;
- the make-public card, which is 121's.

**Blocked by:** 106 - Reproducing from the code repository; 107 - The rule from code to Methods; 115 - The paper order and the paper's parts. It blocks 120.

**Status:** ready-for-agent

**GitHub:** [#266](https://github.com/Bernaljp/wayline/issues/266) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Methods and the code: aligned, the `paper-N` tag, stale re-runs, `code/figures/`; Tools, packages, and environments: the order's environment file and Dockerfile; The paper order and what it compiles: code's steps); M8 criteria 13 and 17; user stories 148, 152.

- [ ] An order tags `paper-N` (N counting orders) and pushes the code repository's split with the tag through the tool runner; the tag is recorded in `PAPER.md`.
- [ ] Every result whose code changed since its run is re-run at the tag; a ticket is cut only when a number its findings cite moved, and `PAPER.md` lists each re-run with its outcome.
- [ ] The scripts behind every figure and every cited drawing number are copied into `code/figures/`, one per figure or drawing, and the split includes them.
- [ ] The code-to-Methods check runs over all of `code/` at the order, and its findings go to the writer and to `PAPER.md`.
- [ ] `code/` gains an environment file and a Dockerfile rendered from the locks, whatever `harness.json.environment` says.
- [ ] Tests: journal replay of an order with one changed result whose numbers held and one whose numbers moved; the tool runner's recordings carry the tag push; the files written under `code/` are asserted over a temporary project.
- [ ] `python -m unittest` passes.
