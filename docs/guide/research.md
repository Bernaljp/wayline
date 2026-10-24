# The research

## Results

A **finding** is a Results passage a ticket returns: what this project's evidence shows, negative or not, with its
provenance. A **result** (`R1` onward, in `research/results.json`) is one Results heading with its current findings and
their plots. Code joins each finding to a result as it is accepted. Say "merge R3 into R2" or "rename R4 to ..." and the
session records it.

Every number in a finding must match a value in the files its tag points at (the numbers check); one code cannot match
goes to a fresh verifier.

## The general report and the current reports

`research/REPORT.md` is the **general report**: about the research only, always current, written by code alone after
every wave that integrated a ticket. It gives what the project is, a headline per result, a table of the results with
their objectives and standing, each objective with its status and evidence, the results beyond the objectives, the
inherited claims not yet checked, and what can and cannot be inferred. It is read-only: an edit is noticed, committed
as it stood, and never taken in.

Each result with an accepted drawing has a **current report**, `research/reports/R<n>-<version>.md`: every plot with
its Purpose, Data, and What it shows, its tables, then the synthesis, headline, inferences, and open questions.
Findings that arrive after the drawing show under "Since the plots were drawn". The next drawing freezes it as an
**earlier report**, kept and never edited.

At every run end, before the end notice, the run-end gates test the general report: drawings of every changed result,
sampled claim verdicts on claims never sampled, and the kill argument when the report changed. Their scope-downs are
`writing` tickets that narrow claims.

## Drawings and plots

A **drawing** is one plotter session's exploration of one result: up to 20 plots, 4 tables, and 4 headline plots, each
explained. Code opens one drawing ticket per result whose findings changed, at rest points: before a run ends, before it
rests on your answer under `checkpoints`, and when you ask ("draw R4 again"). Acceptance reruns the script in a clean
room and runs the figure checks; a plot that keeps failing is left out and listed.

A **plot** keeps its id across drawings (`R4.3`, tables `R4.T1`). Every accepted drawing puts its plots before you as a
batch in the [marks view](run.md#the-marks-view): keep, maybe, or drop, with a note. Drop retires a plot at the next
drawing, a note reaches that drawing's brief, and keep-marked plots are the ones the paper's figures are made from. You
can also ask for a plot: "plot R4's error by depth".

## The plotting library

`harness.json`'s `plotting` is matplotlib with seaborn (the default), Altair, or R with ggplot2. Say "draw with
Altair from now on", or use the select in the dashboard's Run view. Switching first installs what the library needs as
your yes, then writes the setting; a failed install leaves it as it was. A drawing keeps the library it was opened in,
so a switch never redraws an accepted drawing. The decider never sets it.

How the autonomies differ: under `checkpoints` the run draws before it rests on your answer; under every autonomy
drawings run before a run ends. No mark starts a drawing, and an unmarked plot simply stays.

## Verbs the session runs

`wayline result merge <id> <into>`, `wayline result rename <id> "<heading>"`, `wayline result draw <id>`, `wayline result plot <id> "<request>"`,
`wayline mark <batch> <item> <mark>` (with `--note "<text>"`), `wayline switch --plotting <library>`, and
`wayline report` (renders the general report by code; the conductor runs it for you).
