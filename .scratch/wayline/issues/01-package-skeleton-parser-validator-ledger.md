# 01 - Package skeleton, frontmatter parser, schema validator, ledger core

**What to build:** The harness repository becomes a runnable, testable Python package named `wayline`: `bin/wayline` and `python -m wayline` print the version and the verb list; the module set of Implementation Decisions 1 exists as importable stubs; `policy.json` ships the initial values of Implementation Decisions 14; the first schemas ship; the in-house frontmatter parser and serializer round-trip the flat YAML subset a ticket file uses; the in-house JSON Schema subset validator checks every structured value the harness will ever trust; and the ledger module exists as the only writer under a project's `research/`, with its lock, its atomic writes, and the journal event vocabulary. Everything later builds on this slice, so it lands first.

**Blocked by:** None, can start immediately

**Status:** ready-for-agent

**Milestone:** M0 Skeleton. **Spec:** `.scratch/wayline/spec.md`, Implementation Decisions 1, 2, 14; Testing Decisions. Glossary: `CONTEXT.md` (use its terms, avoid its avoid-words in code and docs).

- [ ] `bin/wayline --version` and `python -m wayline --version` print the current tag; `wayline --help` lists every verb of Implementation Decisions 1; a verb not yet implemented exits 2 with "not yet implemented".
- [ ] The package imports only the standard library; a test walks the import graph of every module and fails on any third-party import.
- [ ] `policy.json` carries every key and initial value of the Implementation Decisions 14 table and validates against `schemas/policy.json`.
- [ ] Schemas `journal_event`, `ticket`, `result`, `harness`, `policy`, `job`, `manifest`, and `decision` ship as JSON Schema documents restricted to the validator's subset, each with at least one valid and one invalid example under `tests/`.
- [ ] The frontmatter parser accepts exactly the subset of Implementation Decisions 2 (scalars, flow lists, flow maps, one layer of block nesting with `subkey:` or `- item` lines, trailing comments) and rejects anchors, multi-line scalars, and deeper nesting with a line number; the serializer writes what the parser reads; the BRIEF 8.2 example ticket round-trips unchanged after one normalizing pass.
- [ ] The validator implements `type, required, properties, additionalProperties, enum, const, items, minItems, maxItems, minimum, maximum, pattern, oneOf, $ref` (same file) with positive and negative tests per keyword, and reports the failing path.
- [ ] The ledger module exposes `append_event`, `write_json`, `write_markdown`, `append_line`; every write takes `fcntl.flock` on `research/.lock`; JSON and markdown writes are write-then-rename; a test forks two processes appending 500 events each and finds no interleaved or lost lines.
- [ ] Every event name and payload key of the Implementation Decisions 2 vocabulary is a constant in the ledger module, and a test cross-checks the constants against the table parsed out of the spec so the two cannot drift silently.
- [ ] `python -m unittest` passes in under a minute; the repository is tagged `v0.0.0` and `CHANGELOG.md` has its first entry.
