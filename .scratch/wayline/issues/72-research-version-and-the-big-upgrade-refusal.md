# 72 - research_version and the big-upgrade refusal

**What to build:** A project made on v1.0.x is refused by v1.1.0 with the way back, never migrated and never half-migrated. `harness.json` gains `research_version`, an integer: absent is 1, and `wayline init` on this release writes 2. It is raised only by a release that changes how `research/` is kept, and that release's `CHANGELOG.md` entry opens with a **Breaking** line.

A small upgrade (same `research_version`) works as decision 12 says, both ways. A big one refuses and changes nothing: `wayline upgrade` says the project was made with the older tag and gives two ways on, keeping the old tag (`wayline upgrade --to v1.0.1`, which holds every project on the shared checkout) or starting a new project on the new release from the old one's materials. A refused upgrade journals nothing. No migration of `research/` and no down-migration is written.

Every verb that writes to an old project refuses with the same message: `run`, `tick`, and the other writing verbs today (the conversation's routed verbs inherit the refusal when they land). The dashboard lists an old project read-only, marked with its tag, its files still opening.

This ticket lands first so that every later ticket of decision 17 builds on projects at `research_version` 2. Tests that make projects through `init` get version 2 and keep passing; a fixture project without the key is an old project only where a test says so.

Not part of this ticket:

- the projects page and the read-only marking in the new routed views (110 carries the marking forward);
- the live check that `run` and `tick` refuse a real v1.0.x project and that `upgrade --to v1.0.1` puts the shared checkout back (M8 criterion 21, recorded in 122).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 110.

**Status:** ready-for-agent

**GitHub:** PENDING

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (upgrades: small and big), 12 (the evolve loop: tags, pins, `upgrade`), 1 (`harness.json`, the verb table's `upgrade` row); M8 criterion 18 (and 21's live half in 122); user story 173.

- [ ] `harness.json` has `research_version` in its schema; absent reads as 1; `wayline init` writes 2; the release's constant is the one place the current version is named.
- [ ] `wayline upgrade` within one `research_version` behaves as today, both ways.
- [ ] `wayline upgrade` to a release with a higher `research_version` refuses, changes no file, journals nothing, and prints the project's tag and the two ways on (`wayline upgrade --to <old tag>`, or a fresh project from the old one's materials).
- [ ] `run`, `tick`, and every other verb that writes to a project refuse a project whose `research_version` is lower than the release's, with the same message; read-only verbs (`status`, reading files) still work.
- [ ] The dashboard lists an old project read-only, marked with its tag, its actions refused and its files open in the viewer.
- [ ] The changelog convention gains the **Breaking** line for a release that raises `research_version`, and this release's `## Unreleased` entry opens with it.
- [ ] Tests over temporary projects: a project from `init` at version 2; a hand-made version 1 project refused by `upgrade`, `run`, and `tick` with nothing changed and nothing journaled; a small upgrade still applied; the dashboard's read-only listing over HTTP with an action refused.
- [ ] `python -m unittest` passes.
