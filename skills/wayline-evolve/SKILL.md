---
name: wayline-evolve
description: "The interactive half of the evolve loop: turns the owner's feedback about how the harness behaved into change records, one harness ticket per record, and a fixture that fails on the old behaviour. A shell until ticket 45 fills it in; the CLI verb `wayline evolve` is the same loop without a human in the loop."
---

# Evolve

This skill is a shell. It is registered, symlinked into every project, and named by its sidecar so
the registry and the librarian can see it, but its body is not written yet: ticket 45 builds the
feedback intake, the change records, and the harness tickets, and ticket 44 builds the fixture
runner the loop depends on.

What it will do, from Implementation Decisions 12, so that nothing here has to be re-derived:

- Take feedback from `wayline evolve "<text>"`, the dashboard's form, or a file dropped in
  `research/feedback/`, each journaled as `feedback`.
- Run the retrospective over the journal after every `run_ended`: failures, escalations, stalls,
  rework, turns per closed ticket, and skills whose outcome record sits below the registry's median
  first-time pass rate.
- Write one `change.json` per change: `{id, observed: {text, journal_events[]}, desired, mechanism,
  scope_kind, risk, fixture, status}`.
- File one `harness` ticket per record, with the touch set of a local change being the project's own
  `.claude/` or `harness.json`, and the touch set of a global change being a path in the harness
  repository on the branch `evolve/<id>`.
- Record a fixture that encodes the desired behaviour and fails on the old subject, because a change
  nothing can fail is a change nothing can keep.

Until then, this skill does nothing and should not be assigned to a ticket.
