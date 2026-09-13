# 40 - Provenance tags, the linter, and REPORT.md

**What to build:** The report is rendered by code from the journal and the findings, every claim sentence ends with a provenance tag that resolves to a manifested artifact or a verified reference, the linter fails the build otherwise, and a verifier samples tagged claims to check that the artifact supports the sentence. Decider decisions come first, parked proposals appear under "not pursued", unread promotions are listed, and the goal trajectory is drawn.

**Blocked by:** 18 (Manifest and findings provenance), 32 (Type-B verdicts: the verifier role and gates)

**Status:** done

**GitHub:** [#41](https://github.com/Bernaljp/wayline/issues/41) (mirror; the local file is the source)

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 11 (provenance tags, REPORT.md), 14 (`provenance`); map ticket 40; BRIEF 13.4.

- [x] Tags `{res:<run-id>/<artifact>#<locator>}` and `{ref:<slug>#<locator>}` end claim sentences and render as citations or supplementary references; negative results are claims and need a tag.
- [x] Sentences are classified (claim, definition, transition, method description) in batches by one `haiku --effort low` call through the launcher, cached under `research/.cache/claims.json` by sentence hash so a rebuild classifies only changed sentences.
- [x] The linter (Type-A) requires a tag on every claim, resolves every `res` tag against `manifest.json` and every `ref` tag against `kb/` and `refs/<slug>/`, and fails the build with the offending sentences.
- [x] The verifier (Type-B, through the gate of ticket 32) samples 10 percent of tagged claims, at least ten, plus every claim from a difficulty-5 ticket, and checks that the artifact or locator supports the sentence; failures are journaled and returned as `writing` tickets.
- [ ] `wayline report` renders `REPORT.md` with the sections of Implementation Decisions 11 in order (decider decisions first, open decision tickets and `needs_human`, goal trajectory with discarded changes, findings by claim, tickets closed with `done` versus `accepted`, negative results, papers by level and unread promotions, "not pursued", proposed global harness changes, resources spent, the run's events), journals `report_rendered`, and replaces the minimal renderer used by the tick; the writer role drafts the prose sections under C8 through the launcher.
- [x] Tests use a sample report with the classifier faked and cover a missing tag, an unresolvable tag, and the sampling rule; live: the report for a fixture run that ended passes the linter.
