# 25 - Code dossiers

**What to build:** A paper's code gets its own dossier: a clone at a pinned commit, a mechanical inventory of modules and public symbols, entry points, configs, tests, scripts, and data requirements, and a recipe that was actually run in a fresh environment, so `verified: true` means it ran.

**Blocked by:** 20 (Fetch seam, scout, L0 records, and the knowledge base)

**Status:** ready-for-agent

**Milestone:** M3 Dossiers. **Spec:** Implementation Decisions 9 (code dossiers); research-notes 06 Section 4.

- [ ] `wayline absorb --code <slug> <url>@<sha>` clones with `git clone --filter=blob:none --no-checkout` and `git checkout <sha>` (or `fetch --depth 1 origin <sha>`) under `refs/<slug>/code/` and records `url, sha, author_date, nearest tag, submodules`.
- [ ] The inventory uses the standard library `ast` for functions, classes, `__all__`, public symbols, docstrings, and line ranges; entry points from `pyproject.toml` (`tomllib`) and `setup.cfg`; configs, tests, scripts, and data requirements by the globs and greps of research-notes 06; `code_dossier.json` validates against its schema.
- [ ] The verified recipe installs into a fresh venv (`pkg @ git+<url>@<sha>`), runs the smallest test or example, records the log, and sets `verified: true` only if it exited 0; the API map records per module what is good, bad, risky, reusable, and how to call the pieces that matter.
- [ ] A non-Python repository yields an inventory with `language` set and symbols empty, with a note that universal-ctags or tree-sitter is not yet wired.
- [ ] Tests run on a small committed repository fixture; live: the primary paper's code gets a code dossier with `verified: true`.
