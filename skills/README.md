# Skills

One directory per skill of Implementation Decisions 10, holding the two files the registry and
the prompt builder read:

- `SKILL.md`: Claude Code skill frontmatter (`name`, `description`) and a body. The `name` is the
  directory name. A skill a ticket is assigned carries the `wayline-` prefix; a ticket names the
  skill without it, and the prompt builder puts the prefix back. Only the first such line in a
  prompt expands, so the conductor inlines the bodies of the rest; a body is therefore written to
  be read either way.
- `wayline.json`: the registry sidecar of Implementation Decisions 10, the same fields a role's
  sidecar carries: `id`, `scope_kind`, `capability_summary`, `applicability_tags`, `cost_hint`,
  `fixtures`, `sha256`. `wayline registry build` reads it, recomputes `sha256` over every file of
  the directory except the sidecar itself, and refuses to register a skill whose declared hash has
  drifted from what is on disk.

`wayline init` symlinks every directory here into the project's `.claude/skills/` and `upgrade`
refreshes the links (removing the link of a skill that no longer ships), so a session finds the
harness's skills beside the project's own local ones.

Two skills ship:

- `wayline`: the owner-facing skill of Implementation Decision 17. The owner talks with a project
  normally, in any Claude Code session in it or the dashboard's chat, and this skill routes what
  they say: its body is the routing table (the only verbs a conversation runs, each a CLI verb of
  decision 1's table), and its reference files hold the procedures, `setup.md` (intake, position,
  the grill, the stopping rule and budgets, specify, and the plan, as one conversation with ten
  questions in order) and `evolve.md`. The block `init` writes into a project's `CLAUDE.md` tells a
  session to use it. It replaced the five phase skills of decision 10 (intake, grill, plan, evolve,
  and paper), whose fixtures under `fixtures/skill/` now hold its setup and evolve procedures. The
  registry lists it and never assigns it to a ticket.
- `wayline-interval-claims`: keeps a claim sentence inside the interval its cited artifact holds;
  the librarian assigns it to writing tickets.

No skill names another skill to call. A model-authored skill may take whatever form retrieves best,
but it carries the same sidecar and a fixture: without a passing fixture the registry marks it
`assignable: false`, so the librarian never hands it to a ticket.
