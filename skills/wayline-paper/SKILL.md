---
name: wayline-paper
description: "The interactive half of the paper phase: drafts the manuscript from the ledger under a venue's guidelines, with every claim sentence carrying a provenance tag. A shell until ticket 53 fills it in; the CLI verb `wayline paper [--venue <slug>]` is the same phase without a human in the loop."
---

# Paper

This skill is a shell. It is registered, symlinked into every project, and named by its sidecar so
the registry and the librarian can see it, but its body is not written yet: ticket 53 builds the
paper phase, ticket 52 builds the venue guidelines it reads, and ticket 40 builds the provenance
linter every claim sentence has to satisfy.

What it will do, from Implementation Decisions 11 and 13, so that nothing here has to be
re-derived:

- Draft from the ledger, never from memory: `findings.jsonl`, `manifest.json`, `GOAL.json`,
  `DECISIONS.md`, the dossiers, and the figures.
- End every claim sentence with a provenance tag, `{res:<run-id>/<artifact>#<locator>}` for a result
  and `{ref:<slug>#<locator>}` for a reference. A negative result is a claim and needs one too.
- Work under the venue's guidelines: its sections, its limits, its citation style.
- Stop at the kill argument: the strongest rejection memo against the draft, adjudicated point by
  point against the artifacts, with a fail scoping claims down rather than blocking the paper.
- The report is the stopping point of a run; the paper is only ever on request.

Until then, this skill does nothing and should not be assigned to a ticket.
