# 27 - Skills, the registry, and the librarian

**What to build:** Every skill and role the harness or a project holds is registered by code with a capability summary, applicability tags, a cost hint, its fixtures, and an outcome record computed from the journal, so a librarian step can assign a role and skills to every ticket. The five interactive skills exist as shells with their sidecars and fixture directories, and `init` and `upgrade` share one symlink refresher.

**Blocked by:** 05 (The conductor's M0 path with the fake worker)

**Status:** ready-for-agent

**GitHub:** [#28](https://github.com/Bernaljp/wayline/issues/28) (mirror; the local file is the source)

**Milestone:** M4 Front door. **Spec:** Implementation Decisions 10 (interactive skills, registry entry), 1 (skills and roles layout), 12 (fixture layout, for the directories only).

- [ ] A skill is `skills/<wayline-name>/SKILL.md` plus `wayline.json` (`id, scope_kind, capability_summary, applicability_tags: {kinds[], data_types[], libraries[], venues[]}, cost_hint, fixtures[], sha256`); a role's `wayline.json` carries the same registry fields plus `allowed_tools`, `disallowed_tools`, `output_schema`, `may_judge`.
- [ ] `wayline-intake`, `wayline-grill`, `wayline-plan`, `wayline-evolve`, and `wayline-paper` exist as skills (shells for evolve and paper) with sidecars and a `fixtures/skill/<name>/` directory in the Implementation Decisions 12 layout holding a `fixture.json` with structural checks only (the runner arrives with ticket 44).
- [ ] `wayline registry build` scans the harness `skills/` and `roles/` and the project's `.claude/skills/` and `.claude/agents/` into `registry.json` (schema `registry_entry`), computing each entry's `outcome: {assigned, passed_first_time, failed, last_used}` from `ticket_launched` and `ticket_done` or `ticket_failed` pairs in the journal, and runs `claude plugin validate <path>` on every skill directory as a free pre-check; a local model-authored skill without a passing fixture is registered as `assignable: false`.
- [ ] The librarian function takes a ticket and the registry and returns `role` and `skills` by kind, applicability tags, and outcome record, journaling the assignment (the planner calls it in ticket 34).
- [ ] The symlink refresher used by `init` (and later `upgrade`) relinks every harness skill and workflow into the project and removes dangling links.
- [ ] Tests use a fixture skill tree and a fixture journal; the registry lists the five skills with their capability summaries.
