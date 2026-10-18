# 77 - Plot index data shapes and the five readability checks

**What to build:** Two pieces the drawings (100) rely on, each usable on its own.

**Data shapes in the plot index.** `wayline figures build-index` fills each index entry's `data_shape`, one of `dist`, `xy`, `series`, `category`, `whole`, `matrix`, `multivar`, or `none`, and a canonical chart type, with one Haiku call per entry, cached by the entry's page hash so a rebuild spends nothing on unchanged pages. A drawing later matches a result's data views against these shapes to choose which chart types to draw.

**The five readability checks.** From the owner's notes on the research report prototype (`reaction.md` on the branch `prototype/research-report`), five new checks run on a plot's SVG beside the six figure checks a drawing uses (`min_font_pt`, `text_overlap`, `palette`, `generator_clean`, `regenerates`, `provenance`):

- no rotated text but the y-axis label;
- no axis label over 40 characters;
- no figure title above titled panels;
- heatmap cell labels only up to 36 cells;
- no flat summary mark.

The checks read the SVG every plotting library writes (matplotlib, seaborn, Altair, ggplot2), not only matplotlib's. `generator_clean` lints Python only, and a check that cannot run on a plot (for example `generator_clean` on an R script) is listed as not run, never passed or failed. The thresholds (40 characters, 36 cells) are policy values.

Not part of this ticket:

- drawing tickets, the plotter role, and which checks gate a drawing's acceptance (100);
- the figure finish at the order, which also runs the five new checks (116).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 100.

**Status:** ready-for-agent

**GitHub:** [#224](https://github.com/Bernaljp/wayline/issues/224) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (drawings and plots: `build-index`'s `data_shape`, the six checks and the five new ones, SVG of every library, `generator_clean` Python only, "not run"), 13 (figures, the plot index, the machine checks), 14 (the policy table: the plot checks' thresholds); M8 criterion 6 (the checks' half); user story 128.

- [ ] `wayline figures build-index` writes `data_shape` (one of the eight values) and a canonical chart type on every entry, from one Haiku call per entry through the launcher, cached by page hash; an unchanged page makes no call on a rebuild.
- [ ] Each of the five new checks passes on a clean sample SVG and fails on a sample made to break it: rotated tick labels, a 41-character axis label, a suptitle over titled panels, a labelled heatmap of 37 cells, a flat summary mark.
- [ ] The checks parse SVG from matplotlib, seaborn, Altair, and ggplot2 samples in `fixtures/`; `generator_clean` runs on Python scripts only, and any check that cannot run reports `not run` with the reason.
- [ ] The thresholds 40 and 36 are read from policy, and the policy table of decision 14 gains them in the same commit.
- [ ] Tests: the index build with the fake launcher answering the Haiku calls and a second build hitting the cache; each check over sample SVGs from each library; `not run` for a non-Python generator.
- [ ] `python -m unittest` passes.
