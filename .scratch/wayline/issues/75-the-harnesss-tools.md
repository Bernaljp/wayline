# 75 - The harness's tools

**What to build:** The harness installs the free software it needs itself, without root, and calls each tool only through its record, so a job never finds the wrong executable. `wayline tools install` gains the harness's tools beside docling, installed at every autonomy with no ask:

- **micromamba**, its static binary at `~/.wayline/tools/bin/`, with `MAMBA_ROOT_PREFIX` and `CONDA_PKGS_DIRS` under `~/.wayline/tools/mamba` and one prefix per tool at `~/.wayline/tools/envs/<tool>`;
- **pandoc** from conda-forge through micromamba (with pandoc-crossref), which settles pandoc's route;
- **uv**, through which every Python package installs: the `python -m venv` fallback goes, since it fails on this workstation;
- **matplotlib and seaborn** in the tools venv, the one interpreter for drawings, figure scripts, and the checks' clean room;
- **tree-sitter-matlab** in the tools venv;
- **the embedding model** (BAAI/bge-base-en-v1.5) from Hugging Face at a pinned revision into `~/.wayline/tools/models/`.

Every download is checked against its published digest. `~/.wayline/tools/tools.json` gains one entry per tool: absolute executable, version, required environment, route, lock or digest or revision, installed when, and installer (`harness`, `owner`, or `system`). It is merged one entry at a time instead of rewritten whole, so two installs never lose each other's entries. `wayline tools install` records LaTeX, poppler, LibreOffice, and git as `system` by absolute path and never changes them. `wayline tools show` prints the record. `wayline tools install <name>` installs one tool. `wayline tools run <name> -- <args>` runs a recorded tool by its absolute path and environment, for a session's short calls.

Live on this workstation, the install is recorded in `docs/verification/m8.md`.

Not part of this ticket:

- a project's tools (Octave, R, Julia), licensed software, the `software` decision, tickets' `software` field, and a job's `tool` (82);
- per-project packages and the movable environment (82, 83);
- the converters that use pandoc (84) and the parsers that use tree-sitter-matlab (107).

**Blocked by:** None - can start immediately. Every module it edits is built. It blocks 82, 84, 95, 100, 104, 107, and 118.

**Status:** done

**GitHub:** [#222](https://github.com/Bernaljp/wayline/issues/222) (mirror; the local file is the source)

**Milestone:** M8 A paper that grows with the work (v1.1.0). **Spec:** Implementation Decision 17 (tools, packages, and environments: the harness's tools, routes, `tools.json`; defects found while charting: `tools.json` merged one entry at a time; converting documents, pandoc's build), 1 (the verb table: `tools install <name>`, `tools run`, `tools show`), 6 (jobs and resources), Testing Decisions (seam 6, the tool runner); M8 criterion 14 (the harness's half); user story 153; research note 03 (`research/installing-software`).

- [x] `wayline tools install` installs micromamba, pandoc with pandoc-crossref, uv, matplotlib, seaborn, tree-sitter-matlab, and the embedding model at its pinned revision by the routes above, without root, each download checked against its digest, a digest mismatch failing that tool alone.
- [x] Python packages install only through uv; the `python -m venv` fallback is removed.
- [x] `tools.json` holds one entry per tool with every field above, merged one entry at a time under a lock; two installs in a row keep both entries.
- [x] LaTeX, poppler, LibreOffice, and git are recorded as `system` by absolute path and never changed.
- [x] `wayline tools install <name>`, `wayline tools show`, and `wayline tools run <name> -- <args>` work; `tools run` uses the recorded executable and environment and refuses a tool not recorded.
- [x] The verb table of decision 1 gains `tools install <name>`, `tools run`, and `tools show` in the same commit.
- [x] Tests through the tool runner's recordings (seam 6, after `tests/test_pdf_inventory.py`'s recorded runner): each route's install, a digest mismatch, a merge of two entries, `system` records, `tools run` by absolute path and environment, `tools show`.
- [x] Live: the install on this workstation, with each entry's version and the disk used, recorded in `docs/verification/m8.md`.
- [x] The changelog describes the new tools and verbs under `## Unreleased`.
- [x] `python -m unittest` passes.
