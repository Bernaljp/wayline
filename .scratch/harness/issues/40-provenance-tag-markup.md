# 40 — Provenance tag markup and the sentence classifier

Type: grilling
Status: resolved
Blocked by: None
Brief: Section 13.4, C8; graduated from fog after OPEN-6

## Question

Fix the claim-provenance markup and the linter's classifier.

Default markup: every claim sentence ends with one or more tags `{res:<run-id>/<artifact>#<locator>}` or `{ref:<slug>#<locator>}`; tags render as citations or supplementary references. Default classifier: sentences are classified (claim, definition, transition, method description) by one `--model haiku --effort low` call per batch of sentences, cached in `research/.cache/claims.json` keyed by the sentence hash, so a rebuild only classifies changed sentences; the linter (Type-A) requires a tag on every claim and resolves every tag against `results/` (via the manifest) or `kb/`; the verifier (Type-B, Claude-only per OPEN-6) samples tagged claims and checks support. Decide the sample size (default: 10 percent of claims, minimum 10, all difficulty-5 claims), and whether a negative result counts as a claim needing a tag (default: yes).

## Answer

Resolved 2026-09-11 by the owner in a grilling round.

Tags `{res:<run-id>/<artifact>#<locator>}` and `{ref:<slug>#<locator>}` end every claim sentence and render as citations. Sentences are classified in batches by one `--model haiku --effort low` call, cached by sentence hash under `research/.cache/claims.json`. The linter (Type-A) requires a tag on every claim and resolves each tag against the manifest or `kb/`. The verifier (Type-B, Claude-only) samples 10 percent of tagged claims, minimum ten, plus every difficulty-5 claim. Negative results are claims and need a tag.
