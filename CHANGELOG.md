# Changelog

One entry per tag. `wayline upgrade` prints the entries between two tags.

## Unreleased

`init` lays out a project and `status` reads it (ticket 02, M0 Skeleton).

- `wayline init <path>` lays out the project of Implementation Decisions 1: the `CLAUDE.md` block (appended between markers, never overwriting an existing file, refreshed when the pin moves), `harness.json` with the pin and the defaults of Implementation Decisions 14, the `research/` tree with the `INTAKE.md` template and empty `journal.jsonl`, `findings.jsonl`, `manifest.json`, and `graph.json`, the four `.gitignore` entries, `.claude/` symlinks to the harness skills and workflow scripts, a fresh git repository on `main` with a first commit when the project directory is not itself the root of a work tree, an entry in `~/.wayline/projects.json`, and `~/.wayline/active`. A project laid out inside someone else's repository gets its own and is told so, because the conductor's worktrees branch from the project's own `main`.
- `init` is idempotent: a second run on the same path changes nothing (a test hashes the tree before and after), keeps an owner-edited `harness.json`, `CLAUDE.md`, and `.gitignore`, replaces a symlink that points at another harness checkout, removes a symlink whose harness target is gone, and leaves a local skill that is not a symlink alone.
- `wayline status [--project <path>] [--json]` prints the frontier, the running tickets and jobs, the open decision tickets, the window, the goal progress, the last ten journal events, and the ticket counts, for the active project or the one the flag names. A ledger it cannot read becomes a reported problem and a nonzero exit, never a traceback.
- `wayline switch <path>` moves the pointer and journals `switched` in both projects.
- `wayline.tickets` reads `tickets/NN-slug.md` (the file name must agree with the id), writes them through the ledger, and regenerates `graph.json` from an `os.scandir` snapshot of `tickets/` with the scheduling fields only; a `pinned_difficulty` wins over the ticket's difficulty, the attempt counter comes from the journal's `ticket_launched` events, and a blocking cycle, an unknown blocker, or a duplicate id is refused.
- `templates/project/` holds what `init` lays down; `fixtures/ledger/` is a project whose ledger holds tickets in every status, two jobs, a goal, and a journal longer than the ten events `status` prints.
- `~/.wayline` can be moved with `WAYLINE_HOME`, so the suite never touches the owner's pointers.
- A review pass fixed six defects before the ticket landed: a malformed `graph.json` reaching the frontier computation, trailing padding on rendered status lines, a recovered `.gitignore` entry landing outside its header, a `CLAUDE.md` block with no closing marker needing three runs to converge, `harness.json` reading the shipped `policy.json` rather than the checkout's, and a project inside another repository getting no repository of its own.

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
