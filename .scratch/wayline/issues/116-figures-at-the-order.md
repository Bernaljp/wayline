# 116 - Figures at the order

**What to build:** At the paper order the figures come from the plots the owner explored and marked, with no panel cap and no splitting into thin figures. Code builds the **figure plan** from the outline. Each main-text result gets one figure whose panels are every plot marked keep, or, when none is marked, every plot the result's synthesis cites. Plots marked maybe, and the other plots, go to that result's supplementary figure (`S1/`); drop-marked plots never appear. A venue's display-item limit moves the last results in outline order to the supplement.

The figure plan joins 115's batch. Under `interactive` and `checkpoints` the owner sees each figure's planned panels, and a figure too large for one page comes with a proposal to drop or split it. Under `autonomous` the decider answers the batch (120), and an oversized figure splits, never drops.

The figure role then starts from the planned plots. Its two sessions finish each plot in the library it was drawn in, write the caption, run the checks (the five new readability checks included), and give the honesty verdict. They compose every planned panel, never split one result into small figures, and never drop a panel to simplify. A Type-A check confirms each planned panel is present in the composed figure. A figure from nothing is made only on the owner's request or the venue's requirement.

Tables the plan chooses become numbered tables rendered from their CSV. Code writes `figures/F1/` and `S1/`, each with `caption.md`, beside 115's parts, and `PAPER.md` gains each figure's plan line and what was left out.

Not part of this ticket:

- the order, the batch's other items, and the writer, which are 115's;
- the drawings and the plot marks themselves, which are 100's;
- a re-order reusing a figure, which this ticket supports by recording the plan line 115's re-order compares.

**Blocked by:** 100 - Drawings on the plotter; 115 - The paper order and the paper's parts. It blocks 120.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (The paper order and what it compiles: the figure plan, figures, tables; Drawings and plots: the owner's marks), 13 (figures, the figure role); M8 criterion 17; user stories 129, 158, 159.

- [ ] Code builds the figure plan from the outline and `research/plots.json` with no model call: one figure per main-text result with every keep-marked plot (or, with none marked, every plot the synthesis cites), maybe and unmarked plots in its supplementary figure, drop-marked plots nowhere, and no panel cap.
- [ ] A venue's display-item limit moves the last results in outline order to the supplement, listed in `PAPER.md`.
- [ ] The figure plan and each oversized figure (with a drop-or-split proposal) are items in the order's batch with code's default; under `autonomous` an oversized figure is split and never dropped.
- [ ] The figure role starts from the planned plots in their drawing's library, runs the checks with the five new readability checks and the honesty verdict, and composes every planned panel; a Type-A check fails a figure missing a planned panel.
- [ ] No figure is made from nothing unless the owner asked or the venue requires it; chosen tables render as numbered tables from their CSV.
- [ ] Code writes `figures/F<n>/` and `S<n>/` with `caption.md` under `research/paper/`, and `PAPER.md` records each figure's plan line.
- [ ] Tests: the plan built from a fixture ledger with marks of each kind and none; the venue limit; the composed-panels check passing and failing on sample generators; the fake launcher scripting the figure role's two sessions; CHANGELOG `## Unreleased` names figures from marks.
- [ ] `python -m unittest` passes.
