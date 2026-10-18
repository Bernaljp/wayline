# 123 - M8 live demo: PINF restarted from its own materials, and v1.1.0

**What to build:** The second half of M8's demo, and the release. PINF_Project, a start midway with no metric, restarts on a fresh v1.1.0 project made from a copy of its materials, under `interactive`, with the owner in the sitting. The owner's backup stays untouched. The v1.0.1 project's scout cache is copied in first, so the recorded failures are asked again rather than replayed. In the run:

- the documents are sorted and deconstructed;
- the merges and the concerns are settled in the marks view;
- arXiv 2304.02443 resolves through the API or the abs page;
- both titles resolve, and the IHCV title joins that work's dossier;
- the two OpenReview links are raised at setup;
- at least one inherited result is verified with its route;
- the owner orders a paper from the dashboard's chat.

Nothing of PINF enters the harness repository: `docs/verification/m8.md` holds counts, commands, and journal excerpts only.

Then v1.1.0 ships. The changelog's `## Unreleased` becomes `## v1.1.0 (date)`, opening with its **Breaking** line (`research_version` 2: a v1.0.x project is refused and restarted, never migrated). `wayline/__init__.py` is bumped, the annotated tag `v1.1.0` is pushed, and CI is green.

**Blocked by:** 122 - M8 live demo: the toy overnight. The last ticket of M8.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** milestone M8 (the demo, criterion 20); Implementation Decision 17 (every bullet, as run on PINF; Upgrades: small and big); Implementation Decision 12 (releases, the changelog); user stories 101, 136 to 142, 146, 147, 165, 173, 175.

- [ ] A fresh v1.1.0 project is made from a copy of PINF's materials (the owner's backup untouched), with the v1.0.1 project's scout cache copied in before the first lookup.
- [ ] Under `interactive` the documents are sorted (asked in one line only where unclear) and deconstructed; the merges, contradictions, and concern placements are settled in the marks view; the critiques are split into concerns.
- [ ] arXiv 2304.02443 resolves through the API or the abs page; both titles resolve and the IHCV title joins the same dossier; the two OpenReview links are raised at setup.
- [ ] At least one inherited result is verified, its verdict naming its route.
- [ ] The owner orders a paper from the dashboard's chat and it compiles.
- [ ] `docs/verification/m8.md` records counts, commands, and journal excerpts only; a check over the repository finds no PINF text, file, or branch.
- [ ] The changelog's `## Unreleased` is renamed `## v1.1.0 (date)` and opens with its **Breaking** line; `wayline/__init__.py` reads `1.1.0`; the annotated tag `v1.1.0` is pushed and CI passes on it.
- [ ] `python -m unittest` passes.
