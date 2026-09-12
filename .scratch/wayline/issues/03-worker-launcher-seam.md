# 03 - Worker launcher seam with fake and claude_cli backends

**What to build:** Every model call in the harness goes through one seam: `launch(request)` and `resume(request, session_id, message)` over a `LaunchRequest`, returning an `Envelope`. The `claude_cli` backend runs the exact launch line of Implementation Decisions 3 and parses the `stream-json` output; the `fake` backend returns scripted envelopes for tests. A hidden smoke verb launches one real cheap session so the owner can see the envelope and the usage-window utilization the harness paces on. This is also the portability seam: nothing else in the harness ever starts `claude`.

**Blocked by:** 01 (Package skeleton, frontmatter parser, schema validator, ledger core)

**Status:** done

**GitHub:** [#4](https://github.com/Bernaljp/wayline/issues/4) (mirror; the local file is the source)

**Milestone:** M0 Skeleton. **Spec:** Implementation Decisions 3; Testing Decisions seam 1; research-notes 01 and 02 (recorded streams and envelopes).

- [x] `LaunchRequest` carries `role, model, effort, prompt, agent_json, allowed_tools, disallowed_tools, settings_path, add_dirs, cwd, env, schema_path, max_minutes`; `Envelope` carries `session_id, model, structured_output, is_error, subtype, num_turns, duration_ms, duration_api_ms, usage, model_usage, permission_denials, api_error_status, rate_limit_events, exit_code, stream_path`.
- [x] The `claude_cli` backend builds the argv of the Implementation Decisions 3 launch line (a test asserts the exact argv, including `--permission-mode dontAsk --permission-prompts none`, `--output-format stream-json --verbose`, `--json-schema`, `--fallback-model sonnet`, `--add-dir` twice, and stdin from `/dev/null`), exports the `TICKET_*` and `WAYLINE_*` variables, leaves `CLAUDE_CODE_RETRY_WATCHDOG` unset, and writes `prompt.md`, `agent.json`, `settings.json`, `env.json`, `stream.jsonl`, `stderr.txt`, and `result.json` into the session directory `research/sessions/<ticket>/<attempt>/`.
- [x] Stream parsing on the recorded streams from research-notes 01 and 02 extracts `system/init` (session id, model), every `rate_limit_event` including `unifiedWindows.five_hour` and `seven_day` utilization and `resetsAt`, and the final `result`; a `success` result without `structured_output` and a `subtype: error_max_structured_output_retries` are both reported as invalid; a missing `unifiedWindows` block degrades to `status` alone.
- [x] `structured_output` is re-validated in code against the request's schema; the CLI's own validation is not trusted.
- [x] `resume` passes `--resume <session_id>` and re-passes every flag Implementation Decisions 3 lists.
- [x] The `fake` backend is scripted per test with an ordered list of envelopes, optional patches to write and commit in the request's cwd before returning, optional delays, and an optional pid-alive simulation; `WAYLINE_LAUNCHER=fake` selects it for tests and demos.
- [x] `wayline launch --smoke` (hidden) runs one `sonnet --effort low` session with a two-field schema through the real backend and prints the envelope and the five-hour and weekly utilization; the recorded output goes into `docs/verification/m0.md` as the first live record.
- [x] A test greps the package for `claude` invocations and finds only the `claude_cli` backend.
