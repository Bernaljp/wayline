# Changelog

One entry per tag. `wayline upgrade` prints the entries between two tags.

## Unreleased

The guards, the per-launch settings, and `wayline accept` (ticket 04, M0 Skeleton).

- `hooks/touch_set_guard.sh` and `hooks/stop_guard.sh` are the scripts `research-notes/03-hooks/` validated, carried over byte for byte; a test asserts they stay identical.
- `hooks/command_guard.sh` is new: it reads `tool_input.command` and normalizes it before matching. It strips leading assignments, the shell's own reserved words and brace groups, and the `env`, `sudo`, `nice`, `xargs`, `timeout`, `flock`, `command` and `watch` wrappers; it follows `sh -c`, `bash -c`, `eval` and `env -S` bodies, a here-string or heredoc read by a shell, command substitutions, backticks and process substitutions; it splits pipelines and `&&` and `;` segments, reads redirection targets, drops heredoc bodies as data, and takes the basename of an absolute program path. It exits 2 on `git push` in any spelling including `git -C` and `send-pack`, `git reset --hard` under any legal abbreviation, `git clean -f`, `git branch -D` and its short pair, `git worktree remove`, an `rm` target outside the touch set, `find -delete`, `chmod -R`, `truncate`, `dd` writing outside the worktree, an upload flag on `curl` or `wget` including attached-value spellings, `twine`, `pip upload` and their `uv`, `uvx`, `pipx`, `poetry` and `hatch` spellings, `gh pr`, `gh release`, `gh api` with a write method, `rsync` to another host or with `--delete`, and any write target resolving outside the worktree, `results/` and the temporary directory.
- The guard fails closed where it cannot see: a target path hidden behind a variable or a substitution, an `rm` whose targets arrive on stdin from an `xargs` pipeline, a pipe into a shell, a `cd` out of the worktree (which would move the base every relative path resolves against), a command longer than 20000 characters, one nesting more than 64 sub-commands, and one whose lexing would cost more than the budget. The budget matters because a timed-out `PreToolUse` hook does not block, so a guard that ran past the handler timeout would fail open.
- The temporary directory joins the worktree and `results/` as a write root, which widens Implementation Decisions 4 on purpose: scratch output is routine and a temporary file is not data. `WAYLINE_ALLOWED_ROOTS` widens the set further per launch.
- `hooks/worker-settings.json` is the settings template of Implementation Decisions 4 with the `permissions.deny` first layer; `wayline.gates.worker_settings` renders it with `${CLAUDE_PROJECT_DIR}` replaced by the absolute harness path and refuses a template whose handlers have lost `args: []` or the 30 second timeout.
- `wayline accept` runs the ticket's `acceptance.machine` commands with `shell=True` in the current worktree under `policy.acceptance_timeout_s` and writes `TICKET_ACCEPTANCE_FILE` with `ran_at`, `where`, `results` and `pass`, whether they passed or failed, so the stop guard unblocks either way. A command that outlives the timeout has its process group killed and reports exit code 124; one that leaves a process behind holding its output has that output dropped rather than waited on, so `wayline accept` always returns. The file is written by rename, because the stop guard tests only that it exists.
- The guards are tested through piped stdin: the 14 cases `research-notes/03-hook-shape.md` Section 6 recorded, plus 129 command cases, every listed pattern in a benign spelling that passes and the dangerous spellings a `permissions.deny` rule misses.
- `docs/verification/m0.md` records the two live launches that prove the hooks apply under `--permission-mode dontAsk`.

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
