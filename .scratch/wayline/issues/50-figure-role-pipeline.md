# 50 - The figure role pipeline end to end

**What to build:** A `figure` ticket turns a result into a figure the way the spec's doctrine demands: the data shape is classified in code, candidates come from the plot index, drafts are rendered with real data, a fresh critic ranks them with scores and reasons, the human or the decider picks (with the margin rule), the house style and caption are applied, the 19 checks run, and one honesty verdict decides; a guided revision that would make the figure assert something false is refused with the nearest honest alternative, and only a human can override a refusal.

**Blocked by:** 32 (Type-B verdicts: the verifier role and gates), 43 (M5 overnight demo: the toy project end to end across a window boundary), 49 (Figure machine checks, schemas, and the house style)

**Status:** ready-for-agent

**GitHub:** [#51](https://github.com/Bernaljp/wayline/issues/51) (mirror; the local file is the source)

**Milestone:** M7 Figures, docs, paper. **Spec:** milestone M7 criterion 2; Implementation Decisions 13 (the figure role), 14 (`figures`); research-notes 11 Sections 1 and 4.

- [ ] `roles/figure-designer/` and `roles/figure-critic/` exist; the designer's prompt carries the register rules for a framework figure and the honesty discipline as doctrine and never a library fact (pitfalls arrive per candidate from the index as `pitfalls_consulted`).
- [ ] Unguided path: classify the data shape from the result artifact's schema (code); filter the index by data shape, claim type, and the project's library, capped at `figures.candidates.max`; render drafts with real data and the house palette (one worker session, or one per candidate under a Workflow script), dropping candidates that fail to render with the error recorded; the critic ranks with `claim_legibility, honesty, venue_fit, legibility_at_size` and reasons; the pick is the human's under `interactive` and `checkpoints`, else the decider's rank 1 with `margin_low: true` when the margin over rank 2 is below `figures.margin_threshold`; the worker applies the style, caption, and notes; the checks of ticket 49 run; the honesty verdict runs through the gate of ticket 32 on the crops, the full image, the claim, the caption, the spec, and the check report, with equation verification fanned out as sub-verdicts.
- [ ] Guided path: entered at the styling step with `revision_of` and `change_requests[]`; a request that would make the figure assert something false is recorded in `refusals` with the nearest honest alternative rendered as a new candidate; `overridden_by` can be set only by a human through the decision queue and is recorded in the caption and notes.
- [ ] `findings_for_text` entries become proposals; `traps_hit` entries reach the index through the evolve loop; `figure_result` with every status is validated and journaled.
- [ ] Tests use the fake launcher for the designer, the critic, and the verdict over a fixture result; live: one result from the toy project gets ranked candidates and a final figure that passes the checks and the honesty verdict, recorded in `docs/verification/m7.md`.
