# Software and environments

A **tool** is a program the harness installed, you provided, or the machine already had, recorded in
`~/.wayline/tools/tools.json` with its absolute path, version, and environment, and called only through that record.
A library a project's code imports is a **package**, not a tool.

## Harness tools

Installed by `wayline tools install` with no ask at any autonomy ([Getting started](getting-started.md)): micromamba,
uv, pandoc, the tools venv's plotting and parsing libraries, and the embedding model. System tools (LaTeX, poppler,
LibreOffice, git, `gh`, SingularityCE) are recorded by path and never changed.

## Project tools and packages

A project's tools (Octave, R with renv, Julia) install only after a yes, never as root, under `~/.wayline/tools/`. The
planner names the software each ticket needs, and a ticket does not launch until its tools are recorded. During setup
the sixth question lists every tool the planned work lacks, sized; say yes and the session installs them. After
setup a missing tool is one `software` decision (Install, Not now, Go without) pausing only the tickets that need it:

- `interactive` and `checkpoints`: you answer it (or mark the software ask in the marks view).
- `autonomous`: the decider answers it.

A project's packages install with no ask, into its own environment: Python through uv into `<project>/.venv`
(locked in `code/requirements.lock`), R packages under `<project>/.wayline/packages/r` (`code/renv.lock`), Julia into
`code/` (`Project.toml`, `Manifest.toml`), Octave Forge packages into the shared prefix
(`code/octave-packages.lock`).

## Licensed software

MATLAB is never installed by code. Tell the session where it is installed; it records the path after one
`matlab -batch "ver"` check (never the license number). A licensed tool's decision is always human-only. At setup a
missing licensed tool can instead be ported to Octave or Python.

## Moving a project's environment

`harness.json`'s `environment` is one of four: `shared` (the default: the tools as recorded, plus the project's
packages), `conda` (one prefix at `<project>/.wayline/env`), `venv` (one venv at `<project>/.wayline/env-venv`, Python
only), or `container` (one Singularity image at `<project>/.wayline/env.sif`, built without root). Say "move this
project into a container". Code builds the new environment from the locks, runs each tool's version check inside it,
and only when every check passes writes the setting; a failure leaves everything as it was and prints the failing step.
Jobs already running finish where they started. The dashboard's Run view shows a move in progress. The decider never
moves a project, at any autonomy.

## Verbs the session runs

`wayline tools needs`, `wayline tools install <name> --yes` (or `--decision <id>`, `--dry-run`, `--change`),
`wayline tools install matlab --at <path>`, `wayline tools package <python|r|julia|octave> <name>`,
`wayline tools show`, `wayline tools run <name> -- <args>`, and `wayline switch --environment <kind>`.
