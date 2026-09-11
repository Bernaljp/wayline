# 07 Fixtures for non-deterministic model behavior

Ticket: `.scratch/harness/issues/07-model-behavior-fixtures.md`. Brief: Section 12, OPEN-17.
Verified on 2026-09-11 against Claude Code 2.1.268 (`claude --version`), the code.claude.com docs
markdown (fetched with curl), the promptfoo docs, the DeepEval docs, and the inspect-ai doc sources
on GitHub (the inspect.aisi.org.uk site refused TLS from this machine, so the `.qmd` sources of the
same pages were used). Every claim carries a URL or a command; anything not confirmed by one of
those is marked "unverified".

## Answer

### 1. `claude plugin eval` and `/skill-doctor`

**What `claude plugin eval` is.** Source: `claude plugin --help` and `claude plugin eval --help`
on 2.1.268. It runs eval cases against a plugin and reports scored results. A case is either
`<eval dir>/**/case.yaml` or a `prompt.md` plus `graders/*.md` pair; the eval dir is `evals/`
unless `--eval-dir` or the manifest's `experimental.evals` says otherwise. The target is a path, a
plugin name, or a `plugin@marketplace` id; installed plugins and `~/.claude/skills/<name>`
skills-dir plugins both resolve. Each case runs `case.runs ?? 3` times (`--runs` overrides).
Findings from the help text that matter for this harness:

- Grader classes. The help text names two "paid graders (llm/baseline)" and says "free graders
  still score" a run that breached the cost ceiling. It also names `tool_used: Skill` as a
  "plugin-fired indicator" that can be marked `with-only`. The free grader list `regex`,
  `tool_used`, `tool_order`, `file_exists` comes from a secondary source
  (https://www.matthewswong.com/en/blog/claude-code-plugin-eval-test-suite/) and is consistent
  with strings in the 2.1.268 binary (`with_only`, `criteria`, `judge_votes`), but the full
  case.yaml schema is unverified: no documentation page exists yet (see enablement below).
- Judge. `--judge-model <model>` "Override LLM-grader model (default: haiku)".
- Ablation. `--ablation with-without` (the default whenever a plugin resolves) runs a
  "no-plugin baseline arm and report[s] the score delta"; with-only graders count as a fired
  indicator, not as score.
- Report. `--json [path]` prints "the full run result (prompts, graders, per-run scores)";
  `aggregate-result.json` lands in `./<eval dir>/results/<timestamp>/` (`--output-dir`);
  `--report <path>` writes a self-contained HTML report; the report is published to claude.ai by
  default "when your account supports it" (`--no-publish` keeps it local). Field names present as
  strings in the binary (`strings` on `~/.local/share/claude/versions/2.1.268`, observed, layout
  unverified): `schema_version`, `claude_version`, `started_at`, `duration_seconds`, `cost_usd`,
  `judge_cost_usd`, `judge_model`, `judge_votes`, `pass_rate`, `pass_rate_without`,
  `score_without`, `runs_without`, `mean_delta`, `skipped_paid_graders`, `partial_reason`,
  `trace_path`, `with_only`, `execution.timeout_seconds`, `execution.max_turns`,
  `cases_passed`, `cases_total`, `overall_score`, `overall_pass_rate`, `evidence`, `misses`,
  `advisories`, `unmocked`.
- Sandbox. Each run happens in a scaffold directory: `--scaffold` runs the case's
  `scaffold_script` ("runs author-supplied bash as you; off by default"), `--no-scaffold` skips it,
  `--keep-temp` preserves the scaffold dirs. MCP servers are replaced by mocks from
  `<eval dir>/mocks/` (`--mocks record | off`). Gated tools need an operator grant
  (`--allow-tools Bash Write Edit WebFetch mcp__*`, with `Tool(pattern:*)` syntax).
- CI. `--threshold <0..1>`: "Exit 1 if any case score is below this threshold (default: 1.0)".
  `--max-cost-usd`: "abort and report partial results if hit (exit 2)", overrun bounded to one
  agent run. `--case <glob>` and `--tag` filter; `--model` overrides the subject model.
- Authoring. `claude plugin eval init [name]` runs an interview; `--bare <name>` writes a blank
  `prompt.md` plus `graders/criteria.md` template (`claude plugin eval init --help`).

**Enablement.** Early access, and not enabled for this account. Command run on 2026-09-11 in a
scratch plugin directory with a minimal `.claude-plugin/plugin.json`:
`claude plugin eval init --bare demo` printed "`plugin eval` is currently in early access" and
wrote nothing. The docs index (https://code.claude.com/docs/llms.txt) lists no eval page, and
`plugins-reference.md`, `plugins.md`, `skills.md`, `commands.md`, and `changelog.md` fetched from
https://code.claude.com/docs/en/ contain zero matches for "plugin eval" or "case.yaml". The help
text and the binary are therefore the only first-party sources; treat the format as unstable.

**Fit for a harness that is not a plugin.** Poor as the fixture runner, useful as a vocabulary and
as a later add-on for promoted skills:

- Its unit of test is "an agent with plugin X loaded, given prompt P, scored on transcript and
  filesystem effects", and its headline number is the with-minus-without delta. The harness's
  fixture unit is "role prompt R (or verifier V) given a recorded input pack, constrained by
  `--json-schema`, produces a structured result that satisfies assertions". Roles are launched
  as `--agents` JSON with a result schema (BRIEF 9.2), not as plugins; the conductor and the
  verifier are not plugins at all.
- It is gated, undocumented, its cost accounting is USD-denominated (meaningless on a
  subscription, see 3), and it publishes reports to claude.ai by default.
- What does fit: BRIEF Section 12 says "Model-authored skills pass a fixture proving they load
  and do what their registry entry says". That is exactly a `tool_used: Skill` with-only grader
  plus a with-without ablation on a skills-dir plugin. When the feature leaves early access,
  `promote <skill>` can emit an `evals/` case for the promoted skill as a second, optional check.
  Until then the harness's own runner covers it with a `tool_used` structural assertion over the
  recorded `stream-json` trace.

**What `/skill-doctor` checks.** Sources: https://code.claude.com/docs/en/commands.md (table row)
and https://code.claude.com/docs/en/skills.md (section "Find unused skills"). It shows "what each
of your skills costs in context and how often it gets used", flags skills "that have never been
invoked and says where to turn them off", and lists plugins not used recently. It requires
v2.1.252 or later and feature-flag fetching; in interactive mode the report opens in the
`/plugin` manager's Stats tab, with `-p` it prints as text, and over Remote Control it replies
"Skill usage reports are not available on this connection". It inspects usage and context cost; it
does not run, grade, or lint a skill. Structural validation of skills, agents, and commands in a
directory is `claude plugin validate <path>` (`claude plugin --help`). Fit: `/skill-doctor` is an
input to the registry's outcome record (BRIEF 5.5, "skills with poor outcome records"), not a
fixture mechanism; `claude plugin validate` is a free Type-A pre-check that belongs in the
skill-load fixture.

### 2. Assertion vocabulary worth borrowing

**promptfoo** (https://www.promptfoo.dev/docs/configuration/expected-outputs/). Deterministic:
`equals`, `contains`, `icontains`, `contains-any`, `contains-all`, `starts-with`, `regex`,
`is-json` and `contains-json` ("optional json schema validation"), `javascript`, `python`,
`cost`, `latency`, `levenshtein`, `bleu`. Model-graded: `llm-rubric`, `model-graded-closedqa`,
`factuality`, `similar` (embedding cosine above `threshold`), `answer-relevance`, `g-eval`.
Composition: `weight` (default 1.0, weighted average), `metric` (a tag for aggregation), and an
assertion set whose `threshold` is the fraction of grouped assertions that must pass.
`llm-rubric` (https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/llm-rubric/)
asks the grader for `{ "reason": "<Analysis>", "score": 0.5, "pass": true }`; with a `threshold`
the row passes only if `pass === true` and `score >= threshold`; the grader is overridable per
assertion (`assertion.provider`), per suite (`defaultTest.options.provider`), or `--grader`;
`rubricPrompt` replaces the grading prompt. Sampling: `--repeat` reruns each row, and "each
repeat index uses a separate cache namespace"
(https://www.promptfoo.dev/docs/configuration/caching/); there is no built-in k-of-n reducer,
the verdict is per row and the suite reports a pass rate. Cache: disk at `~/.promptfoo/cache`,
keyed on provider id, prompt digest, provider config, and context variables; `--no-cache` or
`PROMPTFOO_CACHE_ENABLED=false` disables. Whether grader calls are cached is not stated
(unverified).

**DeepEval** (https://deepeval.com/docs/metrics-llm-evals). `GEval` takes `criteria` or
`evaluation_steps` (not both), `evaluation_params` naming which test-case fields the judge sees,
a 0 to 1 score built from a 1 to 5 judge score weighted by output-token probabilities, a
`threshold` (default 0.5), and `strict_mode` (binary: 1 for perfection, threshold forced to 1).
Success is `score >= threshold`. Cost controls
(https://deepeval.com/docs/evaluation-flags-and-configs): `CacheConfig(use_cache, write_cache)`
keyed on test-case content plus metric configuration, `AsyncConfig(max_concurrent,
throttle_value)`, `ErrorConfig(ignore_errors, skip_on_missing_params)`; the last run is written
to `.deepeval/.latest_test_run.json`. Verdicts are per test case; no k-of-n reducer.

**inspect-ai** (sources: `docs/_builtin-scorers.md`, `docs/model-graded.qmd`,
`docs/multiple-scorers.qmd`, `docs/metrics.qmd`, `docs/options.qmd`, `docs/caching.qmd` at
https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/docs). Built-in scorers: `includes()`,
`match()` (with `location="exact"` and `numeric=True`), `pattern()` (regex, `INCORRECT` with
`reason="invalid_response_format"` when absent), `answer()`, `exact()`, `f1()`, `choice()`,
`model_graded_qa()`, `model_graded_fact()`. Model grading: `partial_credit=True` maps to 0.5; the
grader is a separate `model` or the `"grader"` model role, and `ModelRole("grader",
required=True)` makes the scorer refuse to fall back to the model under test (the C6 rule,
enforced in code); a list of grader models votes with the `"majority"` reducer and records votes
in `metadata.panel`. The docs warn that graders run at the provider's default temperature "so
grades for borderline answers can change from run to run and across epochs". Small fixed sample:
`epochs=Epochs(n, reducers)` with reducers `mean`, `median`, `mode`, `max`, `at_least_{k}`
("1 if at least k samples are correct, else 0"), `pass_at_{k}`, `pass_k_{k}`; CLI `--epochs` and
`--epochs-reducer`. `cascade()` "runs scorers in the order given and stops at the first that
settles the sample, so an expensive stage such as a grader model only runs on samples that
cheaper scorers did not settle". Cache: `cache=True` or `CachePolicy(expiry, scopes,
per_epoch)`; the model name is part of the key, so pin explicit versions.

**What to borrow.** inspect-ai's `at_least_k` over `n` epochs is the OPEN-17 recommendation
("2 of 3") already named and defined; its `cascade()` is the "machine pre-checks before any paid
verdict" rule from C6; its required grader role is the "never the producing session" rule.
promptfoo's `is-json` with a schema, `contains-all`, `regex`, and `javascript`/`python` cover the
structural layer; its `{reason, score, pass}` grader envelope and `pass && score >= threshold`
rule are the right shape for a rubric verdict. DeepEval's `evaluation_params` (show the judge
only the fields the rubric names) and `strict_mode` are worth keeping as options. From
`claude plugin eval`: `runs` default 3, free graders always score even when paid ones are
skipped, `with-only` markers, `--threshold` as the exit-code gate, and a suite-level cost
ceiling.

### 3. Cost on a subscription

Facts (https://code.claude.com/docs/en/costs.md): "Claude Code charges by API token consumption"
applies to API-key use; "Claude Max and Pro subscribers have usage included in their
subscription, so the session cost figure isn't relevant for billing purposes"; plan limits are
"a seat-based usage window on a subscription plan, shared across all models" (session and weekly
windows), and `/usage` shows what counts against them. https://code.claude.com/docs/en/headless.md
adds that `--bare` "doesn't use your subscription login" and needs `ANTHROPIC_API_KEY`, so
fixture runs must not use `--bare`. Consequences:

- The unit of cost is window consumption (tokens and turns inside the current session and
  weekly windows), not dollars. `claude plugin eval`'s `--max-cost-usd`, `cost_usd`, and
  `judge_cost_usd` are API list prices and are only a proxy here. The harness's budget field is
  therefore turns and tokens per suite, read from each run's JSON envelope (the docs name
  `total_cost_usd` and a usage block, https://code.claude.com/docs/en/headless.md), with the
  reset-time pacing from ticket 02.
- A fixture with a judged verdict costs `n` subject runs (each a full `claude -p` with the
  recorded prompt, tools, and `--json-schema`) plus `n` judge runs (a fresh `claude -p` with no
  tools, the rubric, and one output). The judge run is small: rubric plus one structured output
  plus a two-field answer. The subject runs dominate, and they are the same size as the original
  ticket step. Exact token counts are unverified until ticket 32 records them; the fixture record
  below stores them per run so the suite can report its own cost.
- Rules that keep suites cheap, each with a precedent: structural checks first and the judged
  sample only when every structural check passed on every run (inspect `cascade()`, plugin eval
  free-before-paid); cache subject outputs by the hash of (rendered prompt, agent JSON, context
  manifest, schema, model, effort) and judge verdicts by the hash of (rubric, judge model,
  output) so an unchanged artifact costs nothing to re-verify (promptfoo cache key, DeepEval
  `CacheConfig`, inspect `CachePolicy`); a separate cache namespace per sample index so `n`
  samples stay independent (promptfoo `--repeat`); `n = 3`, pass at `at_least_2`; judge on the
  cheapest adequate model at low effort (plugin eval defaults to haiku; ticket 32 uses
  `--model sonnet --effort low`); on a change, run only the fixtures whose `subject` hash
  changed, and the full suite at most once per weekly window; a suite-level ceiling in
  `harness.json` (`fixtures.max_turns_per_suite`) that skips remaining judged samples but still
  runs the free layer, mirroring plugin eval's "paid graders are skipped while free graders still
  score".

## Proposed fixture format

### Layout

```
fixtures/
  <kind>/<slug>/
    fixture.json            the record (schema below)
    input/prompt.md         the exact rendered prompt the conductor sent (Appendix B: $RUN/prompt.md)
    input/agent.json        the --agents JSON used ($RUN/agent.json)
    input/schema.json       pinned copy of the --json-schema used
    input/context/          the context pack files, or manifest.json with path and sha256 per file
    rubric.md               optional; the Type-B question and its answer schema
    recorded/
      result-<session_id>.json   the journaled output that seeded the fixture (the JSON envelope)
      trace-<session_id>.jsonl   optional stream-json trace, needed only for tool_used assertions
    runs/                   written by the runner, never by hand: <run_ts>/<i>.json, verdicts, cost
```

`kind` is one of `prompt`, `role`, `skill`, `verifier`, `conductor`. Conductor fixtures are plain
unit tests with the fake worker (BRIEF Section 12) and use only the structural layer.

### fixture.json

```json
{
  "schema_version": 1,
  "id": "role/worker-smoke-test-ticket",
  "kind": "role",
  "subject": {"path": "roles/worker.md", "sha256": "<hash at recording time>",
              "also": ["schemas/result.json"]},
  "origin": {"project": "specdriven-m0", "ticket": 3, "session_id": "<uuid>",
             "journal_ts": "2026-09-11T20:41:07Z", "change_record": null,
             "reason": "seed: first green M0 run"},
  "launch": {"model": "sonnet", "effort": "medium", "permission_mode": "dontAsk",
             "tools": ["Read", "Edit", "Write", "Bash(pytest*)", "Bash(git*)"],
             "max_turns": 40, "output_format": "json", "json_schema": "input/schema.json",
             "fallback_model": "sonnet"},
  "input": {"prompt": "input/prompt.md", "agent": "input/agent.json",
            "context_manifest": "input/context/manifest.json",
            "input_hash": "<sha256 over prompt, agent, manifest, schema>"},
  "structural": [
    {"check": "schema_valid"},
    {"check": "path_in",          "path": "$.status", "values": ["done"]},
    {"check": "path_contains_all","path": "$.outputs_written", "values": ["tests/test_smoke.py"]},
    {"check": "path_equals",      "path": "$.checks.pytest", "value": "pass"},
    {"check": "path_equals",      "path": "$.touched_outside_declared", "value": []},
    {"check": "path_count",       "path": "$.findings", "min": 1},
    {"check": "path_matches",     "path": "$.findings[*].provenance",
                                  "regex": "^(results|tests)/.+#L\\d+$"},
    {"check": "path_count",       "path": "$.proposals", "max": 0},
    {"check": "path_absent_or_empty", "path": "$.decision_requests"},
    {"check": "file_exists",      "path": "tests/test_smoke.py", "in": "worktree"},
    {"check": "python",           "file": "checks.py", "fn": "cost_within_budget"}
  ],
  "judged": {
    "rubric": "rubric.md",
    "show_judge": ["$.summary", "$.outputs_written", "$.commands_run", "$.findings"],
    "judge": {"model": "haiku", "effort": "low", "tools": [], "votes": 1,
              "must_differ_from_subject_session": true},
    "sample_size": 3,
    "pass_rule": {"at_least": 2},
    "strict": false
  },
  "baseline": {"recorded_at": "2026-09-11T21:03:00Z", "subject_sha256": "<same as subject>",
               "structural": "3/3", "judged": "3/3"},
  "quarantine": {"status": "active", "flake_limit": 2, "flakes": [],
                 "stable_runs_to_restore": 3},
  "cost": {"per_subject_run": {"turns": 12, "input_tokens": 41000, "output_tokens": 3900},
           "per_judge_run": {"turns": 1, "input_tokens": 2100, "output_tokens": 90}},
  "tags": ["m0", "worker", "smoke"]
}
```

Structural vocabulary (Type-A, code only, all free): `schema_valid` (always run, always first;
the `--json-schema` result is re-validated by the runner, not trusted), `path_equals`,
`path_in`, `path_matches` (regex), `path_contains_all`, `path_contains_any`, `path_count`
(`min`, `max`), `path_absent_or_empty`, `file_exists` and `file_absent` in the run's worktree,
`tool_used` and `tool_not_used` over the stream-json trace (the analog of plugin eval's
`tool_used` and of BRIEF 12's "proves it loads"), and `python` for anything else, pointed at a
small function in `checks.py` next to the fixture. Paths are JSONPath over the schema-validated
result. A structural check must pass in every sampled run (`n` of `n`).

Judged layer (Type-B): `rubric.md` holds one question and the answer schema
`{"verdict": "pass" | "fail", "reason": "<one paragraph>"}`. The judge is a fresh `claude -p`
with `--tools ""`, `--json-schema` for the answer, the rubric, and only the fields listed in
`show_judge` (DeepEval's `evaluation_params`). It never runs in or resumes the subject session
(C6; inspect's required grader role). `votes` above 1 means a majority of independent judge
calls per sample (inspect's panel). The fixture's judged layer passes when at least
`pass_rule.at_least` of `sample_size` samples pass (inspect `at_least_k`). `strict: true` forces
`at_least = sample_size` for research-critical prompts (DeepEval `strict_mode`).

Pass and regression: a fixture passes when structural is `n/n` and judged is at least `k/n`.
A change to a subject regresses when any fixture pointing at that subject was passing at its
`baseline` and now fails. The runner prints per fixture `structural i/n`, `judged j/n`, the
baseline, the delta, and the cost; exit 1 on any regression, exit 2 on a cost-ceiling stop with
partial results (plugin eval's exit codes).

Quarantine rule (ticket 33 default, made precise): a flake is a run in which the fixture's
outcome differs from its previous run while `subject.sha256` and `input_hash` are unchanged.
Each flake is appended to `quarantine.flakes` with the run timestamp and the layer that flipped.
On the second flake the status becomes `quarantined`: the fixture keeps running and reporting
but no longer gates a change, the retrospective lists it, and the evolver opens a change record
to tighten or rewrite it. It is restored to `active` after `stable_runs_to_restore` consecutive
identical outcomes, or on a rewrite (which resets the baseline). A fixture is never deleted by
the runner; retirement is a human decision recorded in `origin.reason`.

### rubric.md for the example

```
Question: Does `summary` claim only what `outputs_written`, `commands_run`, and `findings`
support? A claim about a test passing is supported only if a pytest command appears in
`commands_run` and `checks.pytest` is "pass". Answer with the schema; give one sentence per
unsupported claim in `reason`, or "none" if all claims are supported.
```

### Recording a fixture from a journaled run

1. Pick the run. Every launch writes `$RUN/prompt.md`, `$RUN/agent.json`, and
   `$RUN/result.json` (BRIEF Appendix B) and journals `launched` and `done` events carrying
   `session_id` (journal event fields `ts`, `event`, `ticket`, `session_id`, `payload`). The
   command `fixture record --session <id> --kind role --slug worker-smoke-test-ticket` resolves
   the run directory from the journal.
2. Copy the input pack verbatim: `prompt.md`, `agent.json`, the `--json-schema` file as
   `input/schema.json`, and the context pack files (or a manifest with sha256 per file when they
   are large or belong to the project's data). Compute `input_hash` and `subject.sha256` from the
   role, prompt template, or skill the run used (the launch record names it).
3. Copy the output: the JSON envelope from `--output-format json` as
   `recorded/result-<session_id>.json`. Per https://code.claude.com/docs/en/headless.md the
   envelope "includes metadata about the request (session ID, usage, etc.) with the structured
   output in the `structured_output` field" and "includes `total_cost_usd` and a per-model cost
   breakdown" (client-side estimates). The runner validates `structured_output` against
   `input/schema.json`, reads `session_id`, and reads the usage block into `cost` (its
   sub-field names are confirmed by ticket 32 from a real run; only `output_tokens` is named in
   the docs). If the run was launched with `--output-format stream-json`, keep the trace for
   `tool_used` assertions; otherwise omit it.
4. Derive candidate assertions. The recorder proposes one `path_equals` per scalar field and one
   `path_count` per array in the recorded output, plus `schema_valid`. The author (a human, or the
   evolver session for a change record) deletes the incidental ones and keeps those that express
   the ticket's intent. When the fixture comes from feedback ("captions overclaim"), the recorded
   output is the bad case: the assertions and rubric encode the desired behavior, and step 5
   must fail on the old subject before the change is accepted, which is plugin eval's
   with-without idea applied to a prompt edit.
5. Set the baseline. Run the fixture `n` times immediately on the current subject. Record
   `baseline.structural`, `baseline.judged`, and the per-run cost. A fixture whose baseline is
   not stable across two consecutive runs is flagged before it ever gates anything.
6. Link it. Write the fixture id into the change record's `fixture` field (BRIEF 12,
   `schemas/change.json`) and into the skill's registry entry when `kind` is `skill`. Promotion
   copies `fixtures/<kind>/<slug>/` with the artifact (Section 12, "with its fixtures").

## Sources

- Local: `claude --version` (2.1.268); `claude plugin --help`; `claude plugin eval --help`;
  `claude plugin eval init --help`; `claude plugin eval init --bare demo` in a scratch plugin
  (printed "`plugin eval` is currently in early access"); `strings` over
  `~/.local/share/claude/versions/2.1.268` for report field names.
- https://code.claude.com/docs/llms.txt (no eval page listed);
  https://code.claude.com/docs/en/commands.md; https://code.claude.com/docs/en/skills.md;
  https://code.claude.com/docs/en/costs.md; https://code.claude.com/docs/en/headless.md;
  https://code.claude.com/docs/en/plugins-reference.md (no eval content).
- https://www.promptfoo.dev/docs/configuration/expected-outputs/;
  https://www.promptfoo.dev/docs/configuration/expected-outputs/model-graded/llm-rubric/;
  https://www.promptfoo.dev/docs/configuration/caching/.
- https://deepeval.com/docs/metrics-llm-evals; https://deepeval.com/docs/evaluation-flags-and-configs.
- https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/docs/_builtin-scorers.md,
  docs/model-graded.qmd, docs/multiple-scorers.qmd, docs/metrics.qmd, docs/options.qmd,
  docs/caching.qmd (rendered at https://inspect.aisi.org.uk/).
- Secondary, for the free grader list only:
  https://www.matthewswong.com/en/blog/claude-code-plugin-eval-test-suite/.
