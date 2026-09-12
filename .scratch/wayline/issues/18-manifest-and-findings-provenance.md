# 18 - Manifest and findings provenance

**What to build:** Every result artifact the harness will ever cite is hashed into the manifest, and the ledger refuses a finding whose provenance points anywhere else. `results/` stays outside git, findings are numbered in `findings.jsonl` with `findings.md` rendered from them, and the run id names the ticket attempt that produced or registered an artifact.

**Blocked by:** 02 (init lays out a project and status reads it)

**Status:** done

**GitHub:** [#19](https://github.com/Bernaljp/wayline/issues/19) (mirror; the local file is the source)

**Milestone:** M2 Hardware. **Spec:** Implementation Decisions 6 (artifacts), 2 (the ledger); OPEN-14 (map ticket 26).

- [x] The ledger's `register_artifact(path, job, run_id, ticket)` writes a `manifest.json` entry `{path, size, sha256, job, run_id, ticket, ts}` and journals `manifest`; `run_id` is `t<ticket>-a<attempt>`.
- [x] `add_finding(text, provenance, ticket, negative)` refuses (raises, and the conductor journals the refusal on the ticket) when the provenance's artifact is not in the manifest or the locator is empty; accepted findings get sequential ids in `findings.jsonl` and journal `finding`.
- [x] `findings.md` is rendered from `findings.jsonl` by code after every change, grouped by ticket, negative results marked.
- [x] `init` already ignores `results/`; a check warns when a tracked file under the project exceeds `policy.artifacts.commit_threshold_bytes` and points at the manifest as the alternative (a soft default; no refusal).
- [x] Tests cover registration, refusal, rendering, and the threshold warning.
