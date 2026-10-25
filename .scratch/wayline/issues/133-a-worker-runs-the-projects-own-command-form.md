# 133 - A worker runs the project's own command form

**What to build:** A worker can run the commands the project itself is run with, such as `PYTHONPATH=src python3 -m toy.oracle ...`, without the permission rules refusing them.

On the toy's live run (ticket 122, `docs/verification/m8.md`), experiment ticket 38 (E1, on `sonnet high`) launched with `--allowedTools` holding `Bash(python3 *)`, `Bash(/usr/bin/python3 *)`, `Bash(git add *)`, `Bash(git commit *)`, `Bash(wayline job add*)`, and `Bash(wayline accept*)` under `dontAsk`. Its smoke test, `PYTHONPATH=src python3 -B -m toy.oracle --seed 10001 --rows 2000 --out ...`, was refused three times: a command with an environment assignment in front matches none of those rules. That is the form the project's own measure uses (`PYTHONPATH=src python3 -m toy.eval --split held_out`, O2's `eval_command`), so workers copy it. The worker returned `blocked`, said that `wayline` and `git` were denied as well (it never tried them), and left its job spec uncommitted, so the work was lost and the planner split a ticket that had nothing wrong with it. Ticket 16's worker had written `/usr/bin/python3 -c ...` and got through. E1 was re-cut as ticket 83 and blocked again within minutes: its worker (on `sonnet high`) tried one compound command, `mkdir -p experiments/E1 && cat > experiments/E1/run.sh <<'EOF' ...`, was refused, and returned `blocked` naming `mkdir`, the heredoc, `python3`, `wayline accept`, and git, having tried none of them on their own and never the `Write` tool it holds. Each such block cost the run a split or a stall replan: by 16:08Z the stall rule had re-cut the graph five times, and every ticket on a Sonnet rung that ran code (34, 38, 83) had blocked this way, while Opus workers under the same rules (16) got through. The owner's stand-in then mapped difficulties 1 and 2 to rung 5 in the toy's `harness.json` for the rest of the run. That helped but is not the fix: at the run end, drawing R12's plotter (ticket 145, on `opus medium`) sent one compound command (`cd <worktree>; echo $WAYLINE_PROJECT; grep ...`), was refused, and returned `blocked` naming `wayline tools run matplotlib`, `wayline accept`, and git, none of which it had tried; R1's plotter had run the same `wayline tools run matplotlib -- draw.py` without trouble.

- A worker's session gets the project's import path from its environment (`PYTHONPATH` naming the project's package directory, set by the launcher from `harness.json` or the plan), so no command needs the prefix; or the allowed rules accept the prefixes a project's measure itself uses.
- The worker and experimenter prompts say how to run the project's code under the rules, to write files with `Write` and `Edit` rather than heredocs or redirections, to run one command per call, to try the allowed form before returning `blocked`, and that a refused command is reported as refused, never guessed for another.
- A job's `command` keeps the form it has (`/usr/bin/env PYTHONPATH=src ...` runs fine in a job).

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#340](https://github.com/Bernaljp/wayline/issues/340) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decisions 4 (guards and permissions), 7 (the launcher and the roles); ticket 122's live record.

- [ ] A worker launched on a project whose measure names `PYTHONPATH=src` can run the package's module under `dontAsk`; checked live once and recorded, and the argv or environment covered by a test.
- [ ] The role prompts say how to report a refused command.
- [ ] `python -m unittest` passes.
