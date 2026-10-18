# 88 - The owner's passages, consolidation, and the linter's new tags

**What to build:** The owner steers the sections in two ways: by talking (the session records the owner's passage) or by editing a section file directly. Every claim sentence is checked when its ticket is accepted.

**The linter's new tags.** Beside `res` and `ref`, the linter knows two new tags:

- `{code:<path>#<symbol>}` or `{code:<path>#L10-L42}`, for a sentence stating what the project's code does. It is resolved against `main` and flagged when it no longer resolves.
- `{doc:<document>#<locator>}`, for inherited text. It is provenance, never a citation.

The linter runs on a ticket's passages and findings at its acceptance, and a failing sentence sends the worker back. It also runs on every render. Before the order, a claim tagged only `doc` and an untagged claim in an owner's passage are listed, never failed.

**The owner's passages.** `wayline passage add --section <s> --heading <h> "<text>"` records an owner's passage with `by: owner`. The conversation calls it, asking only when the section or the place is unclear. When the owner edits a section file instead, code takes the edit in before the next render:

- new text becomes the owner's passages;
- changed text becomes the owner's replacement;
- removed text becomes a withdrawal.

Code uses the file's first-line render stamp, so passages that arrived since the stamp are never taken for deletions. The owner's passages steer with no lock: a later passage may replace one only with evidence and a stated reason. Each such replacement is journaled so the account (ticket 89) lists it under "Changed without asking you", and under `interactive` it is a notice.

**Consolidation.** No model rewrites a section before the order, except a **consolidation**. A consolidation is one read-only writer session that the owner asks for, and an automated run never starts one. It replaces a section's current passages with fewer passages that keep their tags, with `by: consolidation`, checked by the linter like any passage. It is confirmed first with its cost, since it spends tokens. `wayline consolidate <section>` runs it.

Not part of this ticket:

- the `plot` tag (100);
- inherited passages that carry `doc` tags (93);
- the conversation's reading of "compile" as a consolidation or the paper order (109);
- the dashboard's section editor (113) and the consolidation card (121).

**Blocked by:** 86 - Passages and the five sections. It blocks 109, 113, and 121.

**Status:** ready-for-agent

**GitHub:** [#235](https://github.com/Bernaljp/wayline/issues/235) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 ("Sections and passages": tags, the linter at acceptance and render, the owner's edits and passages, consolidation; "Vocabulary the build adds": the conversation's verb for passages); decisions 1 (the verb table: `passage add`, `consolidate`), 2 (the event table: `passage` with `by`), 11 (the provenance linter's tags); M8 criterion 4; user stories 119, 120, 121.

- [ ] The linter accepts `{code:<path>#<symbol>}` and `{code:<path>#L<a>-L<b>}`, resolves them against `main`, and flags one that no longer resolves. It accepts `{doc:<document>#<locator>}` as provenance only.
- [ ] At acceptance the linter runs on the ticket's passages and findings, and a failing sentence sends the worker back. On every render it runs over the sections. A `doc`-only claim and an untagged claim in an owner's passage are listed, not failed.
- [ ] `wayline passage add` records an owner's passage with `by: owner` and journals `passage`.
- [ ] An edit to a section file is taken in before the next render: new text becomes owner's passages, changed text an owner's replacement, removed text a withdrawal. The render stamp keeps passages that arrived since from being read as deletions.
- [ ] A later passage replacing an owner's passage must carry evidence and a reason, or it is refused at acceptance. The replacement is journaled for the account.
- [ ] `wayline consolidate <section>` runs one read-only writer session that replaces the section's current passages with fewer ones keeping their tags, `by: consolidation`, linted. It refuses inside an automated run.
- [ ] Tests:
  - the linter's tags as Type-A functions over a worktree and a result;
  - an owner's edit tested by editing the rendered file and rendering again, including a passage that arrived after the stamp;
  - the consolidation with the fake launcher.
- [ ] The verb table of decision 1 and the event table of decision 2 gain these rows in the same commit as the code.
- [ ] The documentation site and `CHANGELOG.md` under `## Unreleased` describe the new tags, editing a section, and consolidation.
- [ ] `python -m unittest` passes.
