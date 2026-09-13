# 44 - Fixture format and runner (verbatim prototype 32)

**What to build:** A change to a prompt, a role, a skill, or a verifier is caught when it regresses even though model outputs vary: a fixture records a real input pack and output from a journaled session, structural checks on the schema-validated output must pass every time, a small judged sample must pass at least 2 of 3, flaky fixtures are quarantined and reported rather than deleted, and the runner exits nonzero on a regression. The first criterion is the closed prototype ticket's Question, carried verbatim; the real `wayline fixture record` and `wayline fixture run` stand in for the throwaway runner.

**Blocked by:** 03 (Worker launcher seam with fake and claude_cli backends), 09 (Resume from the journal, heartbeat, control events, and worker re-adoption)

**Status:** done

**GitHub:** [#45](https://github.com/Bernaljp/wayline/issues/45) (mirror; the local file is the source)

**Milestone:** M6 Evolve. **Spec:** milestone M6 criteria 1 and 5; Implementation Decisions 12 (fixtures, runner contract, recording), 14 (`fixtures`); research-notes 07 (the proposed format, adopted).

- [x] Carried verbatim from the closed prototype ticket 32 (Prototype: one behavior fixture):

  > Does the proposed fixture format catch a regression? Record one real input pack and output from the worker-launch prototype (or any journaled `claude -p` run), write it in the format the research note proposes, write a small runner that checks the structural assertions and asks one fresh `--model sonnet --effort low` session a rubric question over a sample of three, and run it twice to see stability. Then break the prompt deliberately and show the fixture failing.
  >
  > The answer is the fixture file format and the runner contract M6 implements. Keep it under `.scratch/proto/fixture/`.

  The real `wayline fixture record` and `wayline fixture run` stand in for the throwaway runner; the first fixture is recorded from a journaled M0 or M5 session; the stability run and the deliberate break go to `docs/verification/m6.md`.
- [x] The layout `fixtures/<kind>/<slug>/` (`kind` in `prompt, role, skill, verifier, conductor`) holds `fixture.json` (schema `fixture`, the record of Implementation Decisions 12), `input/` (`prompt.md`, `agent.json`, `schema.json`, `context/` or `manifest.json`), `rubric.md`, `recorded/`, and `runs/` written only by the runner.
- [x] Structural checks (`schema_valid` first and always, `path_equals`, `path_in`, `path_matches`, `path_contains_all`, `path_contains_any`, `path_count`, `path_absent_or_empty`, `file_exists`, `file_absent`, `tool_used`, `tool_not_used`, `python`) run over a JSONPath subset on the re-validated result and must pass n of n; the judged layer launches a fresh `haiku --effort low` session with no tools, the rubric, and only the `show_judge` fields, answering `{"verdict", "reason"}`, never in the subject's session, passing at `at_least` of `sample_size` (`strict` forces n of n).
- [x] Subject outputs are cached by the hash of (prompt, agent JSON, context manifest, schema, model, effort) and verdicts by (rubric, judge model, output) with a namespace per sample index; `fixture run --changed` runs only fixtures whose `subject.sha256` changed; the full suite runs at most once per weekly window; `fixtures.max_turns_per_suite` skips remaining judged samples but still runs the free layer; fixtures never use `--bare`.
- [ ] The runner prints per fixture `structural i/n`, `judged j/n`, the baseline, the delta, and the cost; exit 1 on any regression (passing at baseline, failing now); exit 2 on a cost-ceiling stop; a flake (a different outcome with unchanged `subject.sha256` and `input_hash`) is appended to `quarantine.flakes` and the second one sets `quarantined` (keeps running and reporting, no longer gates, listed in the retrospective); `stable_runs_to_restore` identical outcomes or a rewrite restores; nothing is ever deleted by the runner.
- [x] `wayline fixture record --session <id> --kind <kind> --slug <slug>` resolves the session directory from the journal, copies the input pack and the envelope, proposes one `path_equals` per scalar and one `path_count` per array for pruning, runs n times to set the baseline, flags an unstable baseline, and links the fixture id into the change record or the skill's sidecar.
- [x] Tests use the fake launcher as subject and judge and cover every check, the pass rule, the caches, the quarantine, and the exit codes.
