# eLife

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://elife-rp.msubmit.net/html/elife-rp_author_instructions.html | 200 | hit |

`date_checked` is 2026-09-12.

## Verification

Fully verified: `length_limits`, `required_structure`, `figure_spec`, `reference_style`, `reporting_checklists`, `submission_steps`, `template`.

Unverified, and why:

- `license_of_summary_source`: research-notes/10-venue-guidelines-sources.md could not confirm it.

## Reporting-checklist forms

- MDAR cached as `checklist/elife-mdar-checklist.pdf` (HTTP 200).

## Caveats

- The Author Guide is served from eLife's submission platform and fetches with no login.
- The page carries the platform's own software notice rather than a licence for its text, so the licence field records eLife's Terms and Conditions and the CC BY 4.0 its articles carry, not a licence for the guide itself.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
