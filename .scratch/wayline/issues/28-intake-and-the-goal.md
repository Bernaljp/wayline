# 28 - Intake and the goal

**What to build:** The owner hands wayline anything they have and gets a normalized intake: `INTAKE.md` with the intent, references, data, constraints, autonomy, radius, budgets, and the decision classes that stay human-only, and `GOAL.json` when a quantitative goal is stated, which is rejected unless a script can measure it on an artifact a ticket can produce. A goal can be added or replaced later.

**Blocked by:** 27 (Skills, the registry, and the librarian)

**Status:** ready-for-agent

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (intake), 4 (the irreversible list and `human_only` defaults); BRIEF 6.4.

- [ ] `wayline intake` and the `wayline-intake` skill write `INTAKE.md` with the sections above from whatever the owner gives (a paragraph, a reference list, PDFs, data pointers, a plan, a repository) and record `autonomy`, `radius`, `budgets`, and the `human_only` classes (default: decisions that change the goal or the data) in `harness.json`.
- [ ] `GOAL.json` follows `{metric, direction, target, dataset_or_split, held_out_split, eval_command, baseline: {value, source}, budget: {gpu_hours, wallclock, usage_windows}, stop_when}`; intake runs `eval_command` on a sample artifact and rejects the goal with the reason when the command is missing, fails, or prints no number.
- [ ] `wayline intake --goal` adds or replaces the goal later and journals it as a `decision` with `decided_by: human`.
- [ ] The `wayline-intake` skill's fixture holds a recorded intake and structural checks on the written files.
- [ ] Tests cover a vague intent with references and a goal, a precise plan with a repository, a bad goal, and a later `--goal`.
