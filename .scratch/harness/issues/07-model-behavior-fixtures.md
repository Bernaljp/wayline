# 07 — Fixtures for non-deterministic model behavior

Type: research
Status: resolved
Blocked by: None
Brief: Section 12, OPEN-17; fog: the fixture format

## Question

What first-party and prior-art mechanisms exist for regression-testing prompts, roles, and skills whose outputs vary?

1. Claude Code's `claude plugin eval` (suite format, JSON report, sandbox, CI use, enablement) and `/skill-doctor`: what they check and whether they fit a harness that is not a plugin.
2. promptfoo, DeepEval, and inspect-ai style assertion types (schema, contains, regex, LLM rubric, similarity) and how each handles a judged verdict on a small fixed sample.
3. Cost on a subscription: what a fixture run costs when it includes a judged verdict, and how to keep fixture suites cheap (structural checks first, judged sample last, caching by input hash).

Recommend a fixture file format for this harness (recorded input pack, expected structural assertions on the schema-validated output, optional rubric, sample size, pass threshold) and how a fixture is recorded from a real journaled run.

Deliverable: `research-notes/07-model-behavior-fixtures.md`.

## Answer

- `claude plugin eval` (2.1.268 help text) runs `case.yaml` or `prompt.md + graders/*.md` cases against a plugin, 3 runs per case, free graders (regex, tool_used, tool_order, file_exists) plus paid `llm` and `baseline` graders judged by haiku by default, a with-without ablation delta, `--json`/`aggregate-result.json`, `--threshold` exit 1, `--max-cost-usd` exit 2, scaffold dirs and MCP mocks.
- It is early access and refused on this account (`claude plugin eval init --bare demo` printed the early-access message); no docs page exists in the code.claude.com index, so the case format is unverified beyond the help text and binary strings.
- It does not fit as the harness fixture runner: its unit is "plugin loaded vs not" on a free-form agent run, while ours is a role or prompt under `--agents` plus `--json-schema` producing a structured result. Borrow its vocabulary; use it later, optionally, for promoted skills (`tool_used: Skill` with-only grader).
- `/skill-doctor` reports context cost and invocation counts per skill (v2.1.252+, feature flags); it inspects, never runs. It feeds the registry outcome record. `claude plugin validate <path>` is the free structural lint for skills.
- Vocabulary to borrow: promptfoo `is-json` with schema, `contains-all`, `regex`, `python`, and the `{reason, score, pass}` grader envelope with `pass && score >= threshold`; DeepEval `evaluation_params` and `strict_mode`; inspect-ai `at_least_k` over `n` epochs (the "2 of 3" rule, already defined), `cascade()` (cheap scorers first), a required grader role that cannot fall back to the model under test, and `CachePolicy` scopes.
- Cost on a subscription is window consumption (tokens, turns), not USD; `--bare` needs an API key so fixtures must not use it. A judged fixture costs n subject runs plus n small judge runs; keep it cheap with structural-first gating, output and verdict caches keyed by input hash, n=3 at_least_2, a haiku or sonnet low-effort judge, changed-subject selection, and a per-suite turn ceiling that skips judged samples but still runs the free layer.
- Proposed format: `fixtures/<kind>/<slug>/` with `fixture.json` (subject hash, origin session, launch args, input hash, structural JSONPath assertions, judged block with rubric, sample_size 3, pass_rule at_least 2, baseline, quarantine, cost), `input/` (prompt.md, agent.json, schema.json, context manifest), `rubric.md`, `recorded/`, `runs/`. Structural must be n/n; judged at least k/n; two flakes with unchanged hashes quarantine (report, do not gate, never delete).
- Recording: `fixture record --session <id>` resolves the `$RUN` dir from the journal, copies the input pack and the JSON envelope, proposes assertions from the recorded output for the author to prune, runs n times to set the baseline, and links the fixture to the change record or registry entry.
- Full note with a worked example fixture: `research-notes/07-model-behavior-fixtures.md`.
