# Changelog

One entry per tag. `wayline upgrade` prints the entries between two tags.

## v0.0.0 (2026-09-12)

The package skeleton (ticket 01, M0 Skeleton).

- `bin/wayline` and `python -m wayline` print the tag and the verb table of Implementation Decisions 1; every verb exits 2 with "not yet implemented" until its ticket lands.
- The module set of Implementation Decisions 1 exists; four are real (`cli`, `frontmatter`, `jsonschema`, `ledger`), the rest are importable stubs that name the ticket that builds them.
- `policy.json` ships the initial values of Implementation Decisions 14 and validates against `schemas/policy.json`.
- Schemas `journal_event`, `ticket`, `result`, `harness`, `policy`, `job`, `manifest`, and `decision`, restricted to the validator's subset, each with valid and invalid examples under `tests/examples/`.
- `wayline.frontmatter` parses and writes the flat YAML subset of Implementation Decisions 2 with line-numbered rejections; the BRIEF 8.2 ticket round-trips after one normalizing pass. Floats are accepted as scalars (a metric value must not silently become a string).
- `wayline.jsonschema` validates `type, required, properties, additionalProperties, enum, const, items, minItems, maxItems, minimum, maximum, pattern, oneOf, $ref` (same file) and reports the failing path; `check_schema` refuses any other keyword.
- `wayline.ledger` is the only writer under `research/`: `append_event`, `write_json`, `write_markdown`, `append_line`, all under `flock(research/.lock)`, JSON and markdown by write-then-rename, appends fsynced; the journal event vocabulary is constants, cross-checked against the spec's table by a test.
- The package imports only the standard library, and a test walks the import graph to keep it so.
