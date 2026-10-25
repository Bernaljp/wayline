# 127 - Setup ends ready to run

**What to build:** When setup ends and the owner says yes, the run starts; the owner never runs git.

On the toy's live setup (ticket 122, `docs/verification/m8.md`), the owner's yes reached `wayline run --detach`, which refused: the working tree outside `research/` was not clean. The setup verbs had written `harness.json` (the intake's settings, the stopping rule, the budgets, the code repository, the paper order) without committing it, the owner's handed-over files sat in `owner/`, and the measure's check run had left `src/toy/__pycache__/` untracked. The session cannot commit, so it gave the owner four shell lines to run, and the run started one turn later.

The same night showed it is not setup's alone. The budget cards the owner confirmed in the dashboard's chat (wall clock 12 to 18 to 24 hours, GPU 4 to 8) wrote `harness.json` through `stopping.set_budget` and left it uncommitted. After the run ended, the owner ordered the paper from the chat; the order could not start its own conductor while the old one wound down, and the tick then refused to relaunch for the open order: "the conductor would refuse to start: ... has 1 change(s) outside research/ (harness.json)". The paper order sat until the owner's stand-in committed the file by hand. Then a third time: order 1's figure role wrote the paper's supplement figures under `figures/paper-r*-supplement/` and left them uncommitted, so when the owner ordered the paper again from the phone the tick refused to relaunch for order 2 ("3 change(s) outside research/") and sent a `relaunch_refused` notice, until the files were committed by hand. The figure role's outputs belong in that list of writes the harness commits itself.

- Every verb and dashboard action that writes `harness.json` commits it (with `CLAUDE.md` where it changes), the way `upgrade` already commits its pin.
- Files the owner hands over during setup are committed by the verb that records them (a measure, a document, a sample), or kept under a directory `init` ignores.
- `init`'s `.gitignore` lists `__pycache__/` and `*.pyc` (ticket 69 kept bytecode out of touch sets, not out of the project's tree).
- `run`'s refusal of a dirty tree names each path and the one command that commits it, for the cases left.

**Blocked by:** None - can start immediately.

**Status:** ready-for-agent

**GitHub:** [#334](https://github.com/Bernaljp/wayline/issues/334) (mirror; the local file is the source)

**Milestone:** after M8 (v1.1.x). **Spec:** Implementation Decision 17 (setup), 3 (the project's git), 5 (the conductor's start); ticket 122's live record.

- [ ] After a setup made only of routed verbs, `wayline run --detach` starts with no git command run by hand.
- [ ] `init`'s `.gitignore` keeps bytecode out of the tree.
- [ ] Tests over a temporary project, and `python -m unittest` passes.
