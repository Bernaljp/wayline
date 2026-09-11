# 53 - The paper and the M7 demo

**What to build:** On request after the report, `wayline paper --venue <slug>` (or `wayline paper`, with the decider choosing the venue) drafts a paper from the findings and the knowledge base under the claim-provenance rule, runs the linter and the seven checks on every build, takes its figures from the figure role, passes the two-thread kill argument and one independent verdict, and stops at a draft the owner reads; nothing is submitted anywhere. Then the M7 demo runs end to end.

**Blocked by:** 40 (Provenance tags, the linter, and REPORT.md), 50 (The figure role pipeline end to end), 51 (The documentation site), 52 (Venue guidelines)

**Status:** ready-for-agent

**Milestone:** M7 Figures, docs, paper. **Spec:** milestone M7 as a whole; Implementation Decisions 13 (paper), 11 (kill argument, provenance); BRIEF 13.3.

- [ ] `roles/writer/` (fable, xhigh) drafts `research/paper/` from `findings.jsonl`, the knowledge base, and `REPORT.md` under the venue's `guidelines.json`, every claim tagged; `wayline paper` without `--venue` asks the decider to pick the best-fitting venue from `guidelines/` and journals the decision; `paper_started` is journaled.
- [ ] Every build runs the linter of ticket 40 and the seven checks of ticket 52; failures return the draft to the writer with the list; figures are requested from the figure role of ticket 50 with the venue's `target`.
- [ ] The kill argument and one independent verdict through the gate of ticket 32 gate the draft; a fail scopes claims down through a `writing` ticket; the owner reads the result; no verb, action, or role can submit anything.
- [ ] Live M7 demo, recorded in `docs/verification/m7.md`: the plot index is built; a toy result gets ranked candidates and a final figure that passes the checks; the toy package gets a documentation site that passes completeness checks; `wayline paper --venue` produces a draft under the guidelines with the linter and the kill argument passing; the repository is tagged `v1.0.0`.
