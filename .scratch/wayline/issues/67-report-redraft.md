# 67 - REPORT.md gets a second draft

**What to build:** When `REPORT.md`'s linter fails on the writer's prose, the writer gets the list and drafts again, the way `wayline paper` returns a failed build to the same writer session. Prose that failed the linter is not served from the cache as if it had passed.

Today the prose is drafted once and never fixed:

- **One lint, then written anyway.** `provenance.render_report` lints once and writes the report with the offending sentences at its top.
- **The cache keeps the failure.** `draft_prose` caches the prose under `research/.cache/report_prose.json`, keyed by a hash of the evidence. Every later render, `--no-draft` included, reads the same failing prose until the findings change.
- **The M5 night showed it.** The redraft failed the linter on five untagged framing sentences (140 of 145 tagged), and nothing asked the writer again (`docs/verification/m5.md`, the report).

`wayline paper` already has the loop to copy: `paper.MAX_BUILDS` builds, each failure list sent back to the same session through `paper.RESUME_BUILD`.

**Blocked by:** None - can start immediately. Every module it edits is built.

**Status:** done

**GitHub:** [#164](https://github.com/Bernaljp/wayline/issues/164) (mirror; the local file is the source)

**Milestone:** after M7 (v1.0.1). **Spec:** Implementation Decisions 11 (provenance, the linter, and the report); the M5 record in `docs/verification/m5.md`.

- [x] Suppose a render's linter fails on sentences the writer wrote. The render resumes the same writer session with the list and lints the new draft, for at most `paper.MAX_BUILDS` drafts. The list names each failing sentence and why, including a sentence the classifier read as a claim. The report is written from the last draft, and a draft that still fails keeps today's banner.
- [x] The prose cache records the linter's result beside the prose. A render that may launch a session redrafts prose that failed, rather than reusing it. An `--offline` render and the tick launch nothing and render what the cache holds, as today.
- [x] Tests with the fake launcher:
  - a first draft with an untagged claim, then a second that passes;
  - three failing drafts, ending in the banner;
  - a cached failing draft redrafted on the next render;
  - an `--offline` render that launches nothing.
- [x] The changelog names the change under the next release.
- [x] `python -m unittest` passes.
