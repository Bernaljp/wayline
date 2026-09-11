# 11 — Critical review of the paper-figures skill for the figure role

Type: research
Status: resolved
Blocked by: None
Brief: Sections 3.4, 13.1, C5

## Question

Read `~/.claude/skills/paper-figures/SKILL.md` (261 lines; inspiration only, never called by the harness) and BRIEF.md Sections 3.4 and 13.1. Produce:

1. What to keep as doctrine for the figure role: the two working modes, the register rules for a framework figure, the honesty discipline, the verification loop.
2. What is library-specific (the matplotlib and TikZ traps) and should be regenerated per library from the plot index rather than copied.
3. Which verification steps become machine checks (fonts embedded, colorblind-safe palette, journal widths, resolution, no numeric labels in a framework figure, files regenerate from the analysis) and which remain one Type-B honesty verdict ("does the figure assert something the data does not").
4. How the unguided mode should end in a ranked set of rendered candidates instead of a human-directed panel loop, and what the figure role's input and output schema should be.

Deliverable: `research-notes/11-paper-figures-critical-review.md`.

## Answer

Keep as doctrine: the two-mode split (design before drawing, then implement directed changes), the register rules for a framework figure (real shapes stripped of labels, no prose in panels, greyscale structure, one ramp per quantity, line style for required versus optional), the honesty discipline (equations verified against code, representativeness on a computed number, no unrealized capabilities, self-declaring schematic elements, keep the load-bearing negative), and the shape of the verification loop and notes file.

Regenerate, do not copy: all of SKILL.md Section 4 (lines 163 to 205) is matplotlib and TikZ fact; it seeds the `known pitfalls` field of `figures/plot_index.json` and reaches a session only as `pitfalls_consulted` for the library the index selects.

Mechanize: 19 checks become Type-A with concrete commands (pdffonts for embedding with `pdf.fonttype 42`, pdfinfo for width, pdfimages and pixel math for resolution, pdfminer for minimum font size, pdftotext plus a save-time artist assertion for forbidden text in a conceptual register, ruff, a clean-room regeneration with SSIM, palette allowlist plus CVD-simulated distance, selection-statistic tolerance, disclosure presence). One Type-B verdict remains: "does the figure assert something the data does not," rendered by a fresh session on the crops, spec, caption, claim, and check report, with equation verification fanned out as sub-verdicts.

Human-author assumptions that fail unattended: agreement on the proposal before code (lines 28 to 29, 59 to 60), the artifact page (70 to 71), venue browsing and "actually look" by the drawing session (41 to 43), every "tell the author" (137, 159, 228), author-reported defects (215 to 217), and "comply if reaffirmed" (223 to 226). Replacements: index-driven candidates, a critic ranking, a decider pick with a margin rule, structured `findings_for_text`, machine crops for a critic, and a `refusals` record that only a human can override.

Unguided mode ends as: classify data shape (A), filter the index (A), render up to 5 drafts (A for rendered), critic ranks with scores (B), decider or human picks, house style, machine checks, honesty verdict. Input and output JSON schemas (`figure_request/1`, `figure_result/1`) are in the note.

Full note: `research-notes/11-paper-figures-critical-review.md`
