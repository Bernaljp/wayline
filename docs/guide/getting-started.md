# Getting started

## Installing wayline

Wayline is a Python 3.12 package with no third-party packages. Clone the harness repository on the workstation and
run `bin/wayline --help` (or `python3 -m wayline --help`) from it. Per-machine records live in `~/.wayline/`, which
the environment variable `WAYLINE_HOME` moves.

## Installing the harness's tools

The harness needs its own tools to convert documents, compile the paper, draw plots, and compare passages. Run once:

```bash
wayline tools install
```

It installs, never as root and with no ask at any autonomy: micromamba and uv under `~/.wayline/tools/bin/`, pandoc
with pandoc-crossref (from conda-forge into `~/.wayline/tools/envs/pandoc`), matplotlib, seaborn, and
tree-sitter-matlab in the tools venv, and the embedding model BAAI/bge-base-en-v1.5 under `~/.wayline/tools/models/`.
Every download is checked against its published digest. LaTeX, poppler, LibreOffice, git, and `gh` are recorded as
`system` tools by their absolute path and never changed.

- `wayline tools install <name>` installs one tool; `--dry-run` prints what it would do and changes nothing.
- `wayline tools show` prints the record, `~/.wayline/tools/tools.json` (`--json` prints the file).
- `wayline tools run <name> -- <args>` runs a recorded tool by its absolute path and environment, and refuses one
  not recorded.

Project tools, packages, and licensed software are on [Software and environments](software.md).

## Making a project

```bash
wayline init <path>
```

`init` lays out the project (`research/` with the five section files, `harness.json` with `research_version` 2),
registers it, makes it the active project, writes the line "When the owner talks with a session here, use the
`wayline` skill." into the project's `CLAUDE.md`, and installs three user units in `~/.config/systemd/user/`:
`wayline-tick.service` with `wayline-tick.timer` (the tick, every fifteen minutes) and `wayline-dashboard.service`.
`wayline init --uninstall-units` removes them; `WAYLINE_UNITS=none` installs none. `wayline switch <path>` makes
another project the active one.

From here, open a conversation with the project ([Talking with a project](talking.md)): setup is that conversation.

## Reaching the dashboard

The dashboard is served by `wayline-dashboard.service` (or by hand with `wayline serve`), bound to `127.0.0.1` on
port 8765 by default (`harness.json`'s `dashboard.port`, or `wayline serve --port <n>`). `wayline serve` prints its URL
with the token and the one tunnel line to paste on your laptop:

```bash
ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L 8765:127.0.0.1:8765 <workstation>
```

Then open the printed URL in the laptop's browser. Every action needs the token the URL carries, kept in
`~/.wayline/dashboard.json`; when the service writes to the user journal the URL is printed without it, so read the
token from that file. Binding wider (`wayline serve --bind 0.0.0.0`) makes every request need the token. The
dashboard spends no tokens of your subscription except through its chat.

Nothing here differs between the autonomies.
