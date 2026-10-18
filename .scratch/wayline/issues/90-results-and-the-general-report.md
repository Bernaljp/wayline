# 90 - Results and the general report

**What to build:** Results become the unit the reports present, and `research/REPORT.md` becomes the **general report**: always current, about the research, and written by code alone.

**Results.** A result is one Results heading with its current findings. It gets an id, R1 onward, when the heading first appears. A heading names the question, not the number. Results cluster at acceptance with no session of their own, through a reused heading and `replaces` (and, once ticket 95 lands, the repeated-claims check). A result's objectives are the union of its findings'. The owner merges or renames results by saying so: `wayline result merge` and `wayline result rename`, recorded through the ledger, with the conversation calling them.

**The general report.** Code renders it after every integration and from the tick, in this order:

1. What the project is: about 120 words from the spec's `summary` (ticket 81). A spec without one falls back to its question and data.
2. One headline per result.
3. A table, one row per result, with its objectives, its standing (supported, negative, or mixed), its counts, its current report, and its last change.
4. Each objective in id order: open and answered ones first, then parked ones, with dropped and reframed ones one line each with their lineage. Each objective shows its status, its answer and evidence, a goal's kept values, its concerns and their standing, and its results (findings, then headline plots and links to reports once drawings exist).
5. Results beyond the objectives.
6. Inherited claims not yet checked, counted per section.
7. What can and cannot be inferred, with the open questions.

The rest of v1.0's twelve sections has already moved to the account (ticket 89). The Results section renders from the same findings under the same headings, without the report's apparatus. Reports show only current findings, each replacement with a one-line note ("replaces F12: narrows"). Negative results stay in place, marked, and the table flags them. `findings.md` and the unused `add_finding` and `render_findings` retire, and the writer session that rendered report prose goes.

**The numbers check.** This is a Type-A check at acceptance. Every number in a finding must match a value at one of its sentence's `res` locators, allowing for rounding, percents, and the scales 100 and 1000. Counts in words and parameters the spec names are exempt. Each sentence code cannot match goes to a fresh verifier. A failure sends the ticket back.

**The edit rule.** Reports are read-only. An edited report is noticed by its hash against the last `report_rendered`, committed as it stood, and listed in the next render's banner. Code never takes it in.

Not part of this ticket:

- drawings, plots, current and earlier reports, and the numbers check over plot explanations and `numbers.json` (100, 101);
- sampled verdicts and the kill argument at run ends (103);
- the outline (104);
- the dashboard's Research view (110).

**Blocked by:** 86 - Passages and the five sections; 87 - Keep-if-better per goal, the stopping rule, and budgets; GOAL.json retires; 89 - The account. It blocks 100, 103, 104, 109, 110, and 115.

**Status:** ready-for-agent

**GitHub:** [#237](https://github.com/Bernaljp/wayline/issues/237) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Results and the reports": results, the general report, the numbers check, the edit rule; "Vocabulary the build adds": `report` on `report_rendered`, the conversation's verbs for result merges and renames); decisions 1 (the verb table: `result merge`, `result rename`; `report`), 2 (the event table: `report_rendered`), 11 (verification, provenance, and the report); M8 criterion 5; user stories 38, 111, 122, 123, 125.

- [ ] A new Results heading gets an R id at acceptance. A finding reusing a heading or replacing a finding joins that result, and a result's objectives are the union of its findings'.
- [ ] `wayline result merge` and `wayline result rename` record the owner's merge or rename through the ledger and re-render.
- [ ] `REPORT.md` renders by code alone in decision 17's order, after every integration and from the tick, with the summary (or its fallback), headlines, the table with standings, objectives in their order with a goal's kept values, results beyond the objectives, inherited claims unchecked per section, and inferences with open questions.
- [ ] Only current findings show, each replacement with its one-line note, and negative results stay marked and flagged in the table.
- [ ] The Results section renders from the same findings under the same headings.
- [ ] `findings.md`, `add_finding`, `render_findings`, and the report's writer session are gone, and no test or module refers to them.
- [ ] The numbers check at acceptance matches every number in a finding against its `res` locators with rounding, percents, and the scales 100 and 1000, exempts counts in words and spec parameters, sends each unmatched sentence to a fresh verifier, and sends the ticket back on a failure.
- [ ] An edited `REPORT.md` is committed as it stood, listed in the next banner, and never taken in.
- [ ] Tests:
  - the ledger seam over a temporary project, asserting on the files written;
  - the numbers check as a Type-A function with the fake launcher for the verifier;
  - an edited report tested by editing the rendered file and rendering again;
  - replayed journals for clustering by heading and by `replaces`.
- [ ] The verb table of decision 1 and the event table of decision 2 gain these rows in the same commit as the code.
- [ ] `CHANGELOG.md` under `## Unreleased` describes results and the general report.
- [ ] `python -m unittest` passes.
