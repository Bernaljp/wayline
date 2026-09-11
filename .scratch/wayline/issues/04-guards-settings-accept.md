# 04 - Guards, per-launch settings, and accept

**What to build:** A worker session cannot write outside its touch set, cannot run anything on the irreversible list in any spelling, and cannot stop before it has run the ticket's machine acceptance. The three hook scripts live in the harness, the per-launch settings file is generated with absolute paths, `wayline accept` is the command a worker runs inside its worktree to execute the ticket's machine criteria and write the acceptance file the stop guard looks for, and one cheap live launch proves the hooks apply under `dontAsk`.

**Blocked by:** 01 (Package skeleton, frontmatter parser, schema validator, ledger core)

**Status:** ready-for-agent

**Milestone:** M0 Skeleton. **Spec:** Implementation Decisions 4; research-notes 03 and the scripts under `research-notes/03-hooks/`.

- [ ] `hooks/touch_set_guard.sh` and `hooks/stop_guard.sh` are the validated scripts from `research-notes/03-hooks/`, unchanged in behavior; `hooks/worker-settings.json` is the template of Implementation Decisions 4 with the deny list.
- [ ] `hooks/command_guard.sh` reads `tool_input.command`, normalizes it (leading `VAR=` assignments, `env`, `sudo`, `nice`, `xargs`, `sh -c` and `bash -c` wrappers, `$(...)` bodies, pipeline and `&&` and `;` segments, absolute paths to `rm`, `git`, `find`, `chmod`) and exits 2 with a reason on every pattern Implementation Decisions 4 lists (`git push` in any spelling including `git -C`, `git reset --hard`, `git clean -f`, `git branch -D`, `git worktree remove`, recursive `rm` outside the touch set, `find -delete`, `chmod -R`, `truncate`, `dd of=`, upload flags on `curl` and `wget`, `twine`, `pip upload`, `gh pr`, `gh release`, and any target path resolving outside the worktree and `results/`).
- [ ] The settings writer produces a per-launch `settings.json` from the template with `${CLAUDE_PROJECT_DIR}` replaced by the absolute harness path and `args: []` and `timeout: 30` on every hook.
- [ ] Piped-stdin tests cover the 14 recorded cases of research-notes 03 Section 6 for the touch-set and stop guards, and at least 25 cases for the command guard (each listed pattern allowed in its benign form and denied in its dangerous spellings).
- [ ] `wayline accept` reads the ticket named by `WAYLINE_TICKET` in `WAYLINE_PROJECT`, runs each `acceptance.machine` command with `shell=True` in the current worktree under `policy.acceptance_timeout_s`, and writes `TICKET_ACCEPTANCE_FILE` with `ran_at, where, results: [{cmd, exit_code, seconds, tail}], pass`; a test runs it on a sample ticket in a scratch worktree with one passing and one failing command.
- [ ] One live `claude -p --model sonnet --effort low --permission-mode dontAsk --permission-prompts none --allowedTools Write --settings <generated file>` asked to write outside `TICKET_TOUCHES` ends with the Write in `permission_denials`, no file on disk, and the guard's stderr echoed by the model, recorded in `docs/verification/m0.md`.
