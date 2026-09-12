# Recorded worker streams

The `stream.jsonl` files the launcher's parser tests read (Testing Decisions, seam 1). Each file is what `claude -p ... --output-format stream-json --verbose` writes to stdout, one JSON message per line. `schema.json` is the two-field schema of research note 01, which the recorded structured outputs satisfy. The torn-tail case (a partial last line with no newline, which editors tend to fix) is written by the test itself from `synth-killed.jsonl`.

Provenance, so a reader knows what was observed and what was not:

| File | Source |
|---|---|
| `note01-launch2-success.jsonl` | The `result` line is the raw envelope of research note 01, launch 2, verbatim. The `system/init` line follows the note 02 extract with this launch's session id; the `assistant`, `user`, and `rate_limit_event` lines are composed in the observed shapes (the first `rate_limit_event` is note 02's, verbatim). |
| `note01-launch1-success-without-structured-output.jsonl` | The `result` line is note 01, launch 1, verbatim: `subtype: success`, exit 0, and no `structured_output` key. Other lines composed as above. |
| `note01-launch3-resume.jsonl` | The `result` line is note 01, launch 3 (the `--resume` of launch 2), verbatim. |
| `note02-launch2-plain.jsonl` | Research note 02, launch 2: the `system/init` extract, the `rate_limit_event` verbatim, and the `result` extract with the fields the note lists; no `--json-schema` was passed. |
| `synth-max-structured-output-retries.jsonl` | Synthesized from the documented error arm (`subtype: error_max_structured_output_retries`, `errors: string[]`); not observed. |
| `synth-no-unified-windows.jsonl` | Synthesized: a `rate_limit_event` with only the documented fields (`status`, `resetsAt`, `rateLimitType`) and no `unifiedWindows` block. |
| `synth-rejected-429.jsonl` | Synthesized from the shape research note 02 expects at a hit limit (`status: rejected`, an `assistant` message with `error: rate_limit`, a `result` with `is_error: true` and `api_error_status: 429`); marked unverified in the note. |
| `synth-killed.jsonl` | Synthesized: a stream cut after `system/init` and one `assistant` message, as a worker killed by SIGTERM leaves it. |
| `synth-smoke.jsonl` | Synthesized: the shape of `note01-launch2-success.jsonl` with the two fields the smoke verb's schema asks for (`word`, `cwd`), for the smoke verb's test. |
| `synth-invalid-structured-output.jsonl` | Synthesized: the CLI reports `success` with a `structured_output` that violates `schema.json` (a number for a string, an extra property) and one permission denial. |
