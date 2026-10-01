# Prototype: a research report to react to

*Throwaway. Built 2026-10-01 for the map ticket "A research report to react to: the toy's results explored and explained" (Bernaljp/wayline #176), on the branch `prototype/research-report`. Nothing here is harness code.*

The question: what a research report should look like, made concrete from real results so the owner can react before "The research reports: general, current, and the earlier ones" and "Exploring each result in every useful plot" are decided.

## What is here

| file | what it is |
|---|---|
| `general-report.md` | the general report: objectives, what is known, six results (R1 to R6), every useful plot for each (P01 to P27) with its purpose, data, and inference, what can and cannot be inferred, open questions, index accounting, and what was left out |
| `current-report.md` | one current report, on one line of work ("does the model need to be told which pair matters?"), written by a fresh Sonnet session given only the brief in "The cost" below; plots C01 to C16 |
| `plots/general/`, `plots/current/` | the plots, PNG, with `plots/general/plots.json` naming each plot's result, chart type, and index entries |
| `toydata.py` | reads `~/wayline-m7/toy` in place (never writes); `python3 toydata.py` checks every interval and held-out split against the run's analysis files |
| `classify_index.py`, `index_shapes.json` | the plot index's 75 entries sorted by the data shape each can draw (the index's own `data_shape` is empty on all 75) |
| `general_plots.py`, `current_plots.py` | the two plotting scripts; matplotlib only, the one plotting library installed here |
| `cost.md` | what exploring a result took |
| `build_page.py` | renders both reports into one HTML page for reading |

Rebuild: `python3 toydata.py && python3 classify_index.py && python3 general_plots.py && python3 current_plots.py && python3 build_page.py` (seconds; no model).

## What the owner is asked to react to

1. **Which plots were useful.** By number: the general report's P01 to P27 and the current report's C01 to C16. Several are marked weak or as artifacts on purpose (P14, P15, P18, C11, C12, C16) to show what "every plot the galleries offer" brings in.
2. **How much explanation.** Each plot carries Purpose, Data, and What it shows. Too much, too little, or the wrong kind?
3. **What a current report should cover.** One line of work, here a result with no verdict and a borderline interval. Is this the right unit, and the right depth?
4. **How the general report is organized.** By objective, then by result, with a summary table up front and the run's own account left out (nine findings about code, checks, and compute).
5. **Whether the cost is acceptable.** See `cost.md`.

## Known flaws, left as built

- C10's cell labels are black on dark red and hard to read (the Sonnet session flagged it and left it).
- Plots are matplotlib renderings of gallery chart types, never the galleries' own code: seaborn, altair, and plotnine are not installed.
- Provenance tags (`{res:...}`) sit on the claim sentences taken from the run's findings; sentences derived from the plots themselves carry none, because no run produced the plots. In the design, an exploration run would, and its plots would be its artifacts.
