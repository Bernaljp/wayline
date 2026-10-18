# 122 - M8 live demo: the toy overnight

**What to build:** The first half of M8's demo, live. The toy gets a fresh project on v1.1.0, started from zero with a goal, and runs overnight under `autonomous`. In that run:

- objectives replace GOAL.json;
- passages and findings land in the five sections;
- the goal is reached by keep-if-better and its real question is answered;
- results are drawn at the run end into current reports;
- the general report and the account are rendered by code;
- the run ends on its stopping rule;
- the decider judges and orders a paper, which compiles to a PDF, a `.docx`, and venue LaTeX.

`~/wayline-m7/toy/` stays untouched as the record of the v1.0 run, and the scratch project lives outside `~/.claude`.

The same sitting records the live halves that the suite cannot fake:

- `wayline tools install` installs the harness's tools live on this workstation without root (criterion 14);
- the chat answers a message through the tunnel, with a card confirmed (criterion 15);
- the views and the marks view work at phone width (criterion 16);
- a v1.0.x project is refused by `run` and `tick` with decision 17's message, and `wayline upgrade --to v1.0.1` puts the shared checkout back (criterion 21).

What the run finds wrong is filed as follow-up tickets rather than fixed here.

**Blocked by:** every ticket from 71 to 121. It blocks 123.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** milestone M8 (the demo, criteria 14, 15, and 16 live, 19, and 21); Implementation Decision 17 (every bullet, as run on the toy); Implementation Decision 14 (the toy project); user stories 172, 173, 174.

- [ ] `wayline tools install` runs live on this workstation for micromamba, uv, pandoc, matplotlib and seaborn, tree-sitter-matlab, and the embedding model, without root, each recorded in `tools.json` with its lock; recorded in `docs/verification/m8.md`.
- [ ] A fresh toy project on v1.1.0 (`research_version` 2) is set up in one conversation under `autonomous`, with its goal as an objective with a measure and `stop_when` in `harness.json`; nothing reads a GOAL.json.
- [ ] The overnight run reaches the goal by keep-if-better, answers its real question, draws the changed results at the run end, renders `REPORT.md`, the current reports, and `ACCOUNT.md` by code, and ends on its stopping rule with a single end notice.
- [ ] The decider judges the order, orders the paper, and the paper compiles to a PDF, a `.docx`, and venue LaTeX under `compilations/`.
- [ ] The chat answers a message from the phone through the tunnel and a card is confirmed; the five views and the marks view are checked at phone width; both recorded.
- [ ] A v1.0.x project under v1.1.0: `run` and `tick` refuse with decision 17's message, and `wayline upgrade --to v1.0.1` restores the shared checkout; recorded.
- [ ] `docs/verification/m8.md` holds the journal excerpts, counts, and commands of the run; `~/wayline-m7/toy/` is unchanged.
- [ ] Anything the run found wrong is filed as a follow-up ticket and named in the pull request.
- [ ] `python -m unittest` passes.
