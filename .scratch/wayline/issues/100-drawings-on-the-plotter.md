# 100 - Drawings on the plotter

**What to build:** Each changed result is explored in every useful plot at rest points. Code creates one ticket of the new kind `drawing` per result, and the planner never writes one. It runs on the new **plotter** role on `opus medium` (budget `small`), stepping down to `sonnet medium` when pacing steps Opus work down.

Results are drawn at rest points only:

- at each run end, whose ordering against the gates is "103 - The run-end gates";
- before each checkpoint pause under `checkpoints`;
- on the owner's word ("draw R4 again").

Only results changed since their last accepted drawing are drawn, and only those holding at least one finding from the project's own evidence. The stopping rule's results go first.

A drawing reads the result's findings and their `res` artifacts in place, the objectives, the project summary, the sorted plot index with the data shapes of "77 - Plot index data shapes and the five readability checks", the house style, and the previous drawing with the owner's marks. It writes one script that draws every plot and table and computes every quoted number into `numbers.json`. It is read-only on the research: CPU only, no job, never the project's own code, and missing data becomes an open question. It names the result's data views and draws one plot per canonical chart type whose data shape matches, leaving out near duplicates, a series over an index with no order, collapsed marks, and plots it cannot make readable. It draws at most 20 plots and 4 tables, with no minimum. The plotter writes each plot's Purpose, Data, and What it shows, and the synthesis, headline, what can and cannot be inferred, and open questions, in the same session. Its prompt says a plot of a quantity against one of its own terms says so, and that every mark is explained. An inference a drawing makes about the research is a finding under its result's heading.

Acceptance reruns the script in the clean room and compares the plots and `numbers.json`. It then runs:

- six figure checks: `min_font_pt`, `text_overlap`, `palette`, `generator_clean`, `regenerates`, `provenance`;
- the five readability checks;
- the numbers check;
- provenance.

A failing plot gets one repair resume, then is left out and listed. A drawing that still fails leaves the result with its last accepted drawing, listed in the account, with no tier up, split, or ask.

A **plot** keeps its id across drawings (`R4.3`; tables `R4.T1`): redrawn while useful, retired when left out, never reused. Sections cite it as `{plot:R4.3}`, which the linter checks. The ledger writes `research/plots.json` (each plot's result, chart type, index entries, data view, status, headline flag, the owner's mark and note, and its drawings) and one record per drawing, `research/drawings/R4-2.json`. The script, PNG and SVG files, CSVs, and `numbers.json` are the drawing ticket's artifacts. A drawing marks at most four headline plots.

The owner's marks are items in a batch of "79 - Batches and marks": keep, maybe, or drop, with a note. Drop retires the plot at the next drawing, a note is an instruction for it, keep means a drawing never retires it alone, and no mark starts a drawing. Tables are data tables written as CSV by the script. Plotting runs in Python with matplotlib and seaborn in the tools venv. An earlier figure in a project's documents is folded into the drawing of the result that replaces its claim, which draws the same view where the data allows and says whether it agrees.

Not part of this ticket:

- current and earlier reports, and a plot the owner asks for, which are "101 - Current and earlier reports";
- Altair and R, which are "102 - The plotting library switch";
- the run-end ordering of drawings and gates, which is "103 - The run-end gates";
- the marks view, which is "112 - Dashboard: the marks view".

**Blocked by:** 75 - The harness's tools; 77 - Plot index data shapes and the five readability checks; 79 - Batches and marks; 90 - Results and the general report. It blocks 101, 102, 103, 112, and 116.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Drawings and plots; Sections and passages: the `plot` tag; Results and the reports: the numbers check); Implementation Decision 13 (figures, the figure checks); Implementation Decision 14 (the policy table: the plotter role at `opus medium`, the drawing's limits of 20 plots, 4 tables, and 4 headline plots, the plot checks' thresholds of 40 characters and 36 cells); Implementation Decision 2 (the event table: `marked`, the drawing's acceptance); the schemas list (`plots`, `drawing`, the kind `drawing`); M8 criterion 6; user stories 127, 128, and 129.

- [ ] Code creates one `drawing` ticket per result at each rest point (run end, before a checkpoint pause, the owner's word), only for results changed since their last accepted drawing that hold a finding from the project's own evidence, the stopping rule's results first. The planner refuses to write the kind.
- [ ] `roles/plotter` runs on `opus medium` with budget `small`, steps down to `sonnet medium` with pacing, and has a read-only touch set with no job and CPU only. Its prompt carries the inputs above, the limits, the leave-out rules, the own-term rule, and the explanation of every mark.
- [ ] The drawing's one script writes every plot as PNG and SVG, every table as CSV, and every quoted number into `numbers.json`. Acceptance reruns it in the clean room and compares outputs.
- [ ] Acceptance runs the six figure checks, the five readability checks, the numbers check, and provenance on the SVG. A check that cannot run is listed as not run, and `generator_clean` lints Python only. A failing plot gets one repair resume and is then left out and listed. A still-failing drawing keeps the last accepted one, listed in the account, with no escalation.
- [ ] Plot ids `R<n>.<k>` and `R<n>.T<k>` persist across drawings, retire when left out, and are never reused. `{plot:R4.3}` is a linter tag checked against `plots.json`.
- [ ] `research/plots.json` and `research/drawings/R<n>-<v>.json` are written through the ledger, with at most four headline plots.
- [ ] The owner's marks are a batch of ticket 79. Drop retires at the next drawing, a note reaches the next drawing's prompt, keep is never retired by a drawing alone, and no mark starts one.
- [ ] An earlier figure from an inherited document is handed to the drawing of the result that replaces its claim, which says whether it agrees.
- [ ] Tests: the fake launcher scripting the plotter, sample generators for the clean-room rerun and the checks, the ledger seam over a temporary project for plots and drawings, and journal replay for the rest points under each autonomy, the repair resume, and a left-out plot.
- [ ] Decision 14's policy table gains the plotter role, the drawing's limits, and the checks' thresholds; decision 2's event table gains the drawing's acceptance and `marked` as this ticket uses it; and the schemas list gains `plots`, `drawing`, and the kind `drawing`, each in the same commit as its code.
- [ ] The CHANGELOG's `## Unreleased` entry and the documentation site describe drawings and plots.
- [ ] `python -m unittest` passes.
