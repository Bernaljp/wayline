# What exploring a result took

Measured 2026-10-01 on the toy's M7 results.

## One result, one fresh session (the current report)

The line of work "does the model need to be told which pair matters?" (the all-pairs cost, 10 findings over 4 signals) was explored by one fresh Sonnet session (subagent, default effort), given a brief of about 900 words, a ready loader (`toydata.py`), and the sorted index (`index_shapes.json`). It wrote the plotting script, drew and looked at every plot, checked its inferences, and wrote `current-report.md`.

| measure | value |
|---|---|
| sessions | 1 (Sonnet) |
| tool calls (turns) | 23 |
| tokens | 82,712 |
| wall clock | 3 min 19 s |
| plots | 16, from 16 index entries, with 40 distinct chart types considered |
| report | about 2,800 words |
| inferences it judged artifacts | 2 (C12, C16), and one plot it called partly built in (C11) |
| flaws left | 1 unreadable plot (C10's labels) |

About 5,200 tokens per plot, or 83,000 per result. The numbers it quotes were checked against the data afterward (spread, DeLong exclusions, cross-signal correlation): all correct.

## Six results, one session (the general report)

The general report was built in this wayfinder session (Opus), not metered on its own: about 150,000 tokens and 13 minutes of wall clock from claiming the ticket to the corrected report. That covers reading the project, writing the loader, sorting the index by hand, 27 plots, the report, and a fact-check pass. The fact-check found 7 sentences to correct among the report's numeric claims, 4 of them plainly wrong (a ratio, the product's share of the label, a spread, a claim that seeds keep their order across signals) and 3 loose (a standard deviation, a maximum, a bound), plus one omission (the comparison with the reference's "several points"); and one pattern that looked like a finding and was coupling (P18). Written once by a model and checked by nobody, a report would have carried those errors. Drawing the 27 plots takes 4.7 s of CPU; the cost is all in deciding what to draw and what it means.

## Against the M7 figure pipeline

The run made 8 publication figures through the figure role: 45 sessions in all (4 to 8 per figure), two of them ending `honesty_failed`. An exploratory plot here costs a fraction of one session, because it carries no caption, no critic, and no verifier; its explanation is checked the way any result text is.

## What this projects to

| scope | sessions | tokens (Sonnet) |
|---|---|---|
| one result, every useful plot | 1 | about 80,000 |
| the toy's six results | 6 | about 500,000 |
| a general report assembled from them | 1 more | not measured; the assembly here was part of the Opus session |

Two one-off costs drop out in the design: the index's `data_shape` is empty on all 75 entries today, so sorting it was manual here and would be filled once; and the loader would be the run's own analysis artifacts read directly.
