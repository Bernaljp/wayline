# 101 - Current and earlier reports

**What to build:** Each result gets a **current report** at full depth, so the owner can see how it looks now and how it looked at each drawing. `research/reports/R<n>-<version>.md` is rendered by code alone. A new version starts when that result's drawing is accepted. Between drawings, code re-renders it with new findings under "Since the plots were drawn" and with replaced findings marked. The next accepted drawing freezes it as an **earlier report**, never edited again.

A report shows only current findings, each replacement with a one-line note ("replaces F12: narrows"). Negative results stay in place, marked. Each plot is shown with its Purpose, Data, and What it shows, followed by the synthesis, the headline, what can and cannot be inferred, and the open questions. Tables are their own items, rendered from their CSV. The general report, built by "90 - Results and the general report", gains, per result:

- the links to its current and earlier reports;
- its headline plots, each with Purpose, Data, and What it shows;
- the synthesis.

The table's "current report" column links to the current report. `report_rendered` gains `report` and `version`. Reports are read-only under the general report's edit rule: an edited report is committed as it stood and listed, never taken in.

A plot the owner asks for is a small drawing of its result, carrying the result's other plots into the new version unchanged. A request for data no result holds is an ordinary analysis ticket.

Not part of this ticket:

- the drawings themselves, which are "100 - Drawings on the plotter";
- the Research view that lists these reports, which is "110 - Dashboard: routes, the projects page, and the Research and Run views".

**Blocked by:** 100 - Drawings on the plotter. It blocks 110.

**Status:** ready-for-agent

**GitHub:** [#248](https://github.com/Bernaljp/wayline/issues/248) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (Results and the reports: current and earlier reports; Drawings and plots: a plot the owner asks for); Implementation Decision 2 (the event table: `report` and `version` on `report_rendered`); M8 criterion 5; user stories 124 and 127.

- [ ] An accepted drawing of R<n> starts `research/reports/R<n>-<v>.md` at the next version and freezes the previous version as an earlier report that no later render changes.
- [ ] Between drawings, the current report re-renders with new findings under "Since the plots were drawn" and replaced ones marked. Only current findings show, each replacement with its one-line note, and negative results stay marked.
- [ ] Each plot renders with Purpose, Data, and What it shows, followed by the synthesis, the headline, inferences, and open questions. Tables render from their CSV as their own items.
- [ ] `REPORT.md` gains, per result, its current and earlier report links, its headline plots with their three explanations, and the synthesis.
- [ ] `report_rendered` carries `report` and `version`. An edited current or earlier report is noticed by its hash, committed as it stood, and listed in the next render's banner, never taken in.
- [ ] A plot the owner asks for becomes a small drawing of its result carrying the other plots unchanged into the new version. Data no result holds becomes an analysis ticket.
- [ ] A result merged into another (`wayline result merge`, or an outline merge proposal of ticket 104 taken) takes its plots with it: each plot of the merged result is re-pointed to the result it went into and keeps its id, so its `plot` tags still resolve and that result's next drawing keeps or retires it, and the merged result's current report freezes as an earlier report. The spec is silent here, and ticket 100 left a merged result's plots current with nothing that would ever draw them again.
- [ ] Tests on the ledger seam over a temporary project with accepted drawing records from the fake launcher, asserting on the files written: versions, the freeze, "Since the plots were drawn", replacement notes, the general report's links, the edit rule, and the small drawing.
- [ ] Decision 2's event table names `report` and `version` on `report_rendered` in the same commit.
- [ ] `python -m unittest` passes.
