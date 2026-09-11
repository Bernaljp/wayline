# 23 - L1 skims, reading budgets, and promotion triggers

**What to build:** Candidate papers get a skim: one cheap model call over a capped input returns a short structured record with a relation-to-intent line and a "would deserve L2 if" line. Depth is earned: the L2 budget per phase is enforced, every promotion trigger promotes automatically inside the budget and opens a decision ticket beyond it, and every promotion or demotion is journaled with its trigger.

**Blocked by:** 03 (Worker launcher seam with fake and claude_cli backends), 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** ready-for-agent

**GitHub:** [#24](https://github.com/Bernaljp/wayline/issues/24) (mirror; the local file is the source)

**Milestone:** M3 Dossiers. **Spec:** Implementation Decisions 9 (levels and budgets), 14 (`absorb`); OPEN-16 (map ticket 31).

- [ ] `wayline absorb --level 1 <slug>` builds the capped input (title, abstract, introduction, conclusion, figure captions, results table headers, cut at `policy.absorb.l1_max_chars`) from the inventory or the text layer, makes one `sonnet --effort medium` call through the launcher with the L1 record schema, and writes the record into `refs/<slug>/dossier.json` at level 1 with `relation_to_intent` and `deserves_l2_if`.
- [ ] The promotion function accepts a trigger (named primary at intake; cited by a spec claim, baseline, or method to implement; named in a ticket's context pack; a consultant question L1 cannot answer; the planner or the decider promotes) and promotes inside `policy.absorb.l2_per_phase` for the current phase or opens a decision ticket beyond it; both paths journal `promoted` or `decision_opened` with the trigger; demotions journal `demoted`.
- [ ] The minimal report renderer lists papers by level and the promotions not read in full with the reason.
- [ ] Tests use the fake launcher for the L1 call and cover the budget boundary in each phase; live: four references from the M3 intake get L1 skims.
