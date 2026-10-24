# wayline

One command that turns a research intent into `REPORT.md` under a Claude Code subscription. Deterministic Python (standard library only) decides what runs, when, on which resources, and what counts as done; models decide only content.

- The user guide: [docs/guide/index.md](docs/guide/index.md). The brief: `BRIEF.md`. The glossary: `CONTEXT.md`. The spec: `.scratch/wayline/spec.md`. The tickets: `.scratch/wayline/issues/`, mirrored to GitHub issues.
- Run it: `bin/wayline --help` or `python -m wayline --help` from this directory. Python 3.12, no third-party packages.
- Test it: `python -m unittest` from this directory.
- Versions: one tag per global change, listed in `CHANGELOG.md`; a project pins the tag in its `harness.json`.

Layout (Implementation Decisions 1): `wayline/` is the package, `schemas/` the JSON Schema documents, `policy.json` the global defaults, `templates/project/` what `wayline init` lays down, `fixtures/` the recorded inputs the tests read, and `tests/` the unit suite with the schema examples under `tests/examples/`.

A project: `wayline init <path>` lays one out and makes it active, `wayline objective add "<question>"` records an objective (a goal with `--measure <file> --sample <artifact>`) in `research/objectives.json`, `wayline status` prints the objectives' statuses, the frontier, and the last events, `wayline switch <path>` moves the machine's pointer. The per-machine pointers live in `~/.wayline/`, which `WAYLINE_HOME` moves.
