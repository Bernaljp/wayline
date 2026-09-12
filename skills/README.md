# Skills

One directory per skill of Implementation Decisions 10, holding the two files the registry and
the prompt builder read:

- `SKILL.md`: Claude Code skill frontmatter (`name`, `description`) and a body. The `name` is the
  directory name, which carries the `wayline-` prefix; a ticket names the skill without it, and
  the prompt builder puts the prefix back (`/wayline-<skill>`). Only the first such line in a
  prompt expands, so the conductor inlines the bodies of the rest; a body is therefore written to
  be read either way.
- `wayline.json`: the registry sidecar of Implementation Decisions 10, the same fields a role's
  sidecar carries: `id`, `scope_kind`, `capability_summary`, `applicability_tags`, `cost_hint`,
  `fixtures`, `sha256`. `wayline registry build` reads it, recomputes `sha256` over every file of
  the directory except the sidecar itself, and refuses to register a skill whose declared hash has
  drifted from what is on disk.

`wayline init` symlinks every directory here into the project's `.claude/skills/` and `upgrade`
refreshes the links, so a worker finds the harness's skills beside the project's own local ones.

The five skills here are the interactive phases, one per front-door verb: `wayline-intake` (P0),
`wayline-grill` (P2), `wayline-plan` (P4), `wayline-evolve`, and `wayline-paper`. Each is mirrored
by a CLI verb that does the same work without a human in the loop, and each has a fixture under
`fixtures/skill/<name>/` that its own ticket fills in.

A model-authored skill may take whatever form retrieves best, but it carries the same sidecar and
a fixture: without a passing fixture the registry marks it `assignable: false`, so the librarian
never hands it to a ticket.
