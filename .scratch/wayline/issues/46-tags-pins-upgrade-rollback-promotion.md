# 46 - Tags, pins, upgrade, rollback, and promotion

**What to build:** Global change is versioned and reversible: the harness repository is tagged on every global change, a project pins a tag, `run` refuses when the checkout is not at the pin, `upgrade` moves a project forward with a changelog and `upgrade --to` rolls it back, and `promote` copies a local skill, role, or policy into the harness with its fixtures on a branch that the owner integrates and tags.

**Blocked by:** 27 (Skills, the registry, and the librarian), 44 (Fixture format and runner (verbatim prototype 32))

**Status:** ready-for-agent

**Milestone:** M6 Evolve. **Spec:** Implementation Decisions 12 (versioning, pins, upgrade, rollback, promotion), 5 (run refuses on a pin mismatch), 1 (CHANGELOG.md); BRIEF 12.

- [ ] Tags are `vMAJOR.MINOR.PATCH`; `CHANGELOG.md` carries one entry per tag; `harness.json.harness_tag` is the pin; `wayline run` refuses to start when `git describe --tags --exact-match` on the harness checkout differs from the pin and prints the `upgrade` command that fixes it.
- [ ] `wayline upgrade [--to <tag>]` checks the harness repository out at the target tag (a detached checkout is fine), rewrites the pin, refreshes the skill and workflow symlinks with the refresher of ticket 27, prints the changelog entries between the two tags, and journals `pinned` with `previous`; rollback is `upgrade --to <older tag>`.
- [ ] `wayline promote skill | role | policy <name>` copies the local artifact and its fixtures into the harness on the branch `promote/<name>`, runs the tests and the full fixture suite, and, once the owner integrates it into the harness `main`, tags the result and journals `tagged`; the evolver's retrospective recommends promotion when a local skill's outcome record is good over several tickets, and the decision stays the owner's.
- [ ] Tests run against a temporary git repository standing in for the harness (tag, pin mismatch refusal, upgrade forward, rollback, promotion branch).
