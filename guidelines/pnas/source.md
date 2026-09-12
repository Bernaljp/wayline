# PNAS

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://www.pnas.org/author-center/submitting-your-manuscript | 403 | miss |
| https://www.pnas.org/author-center | 403 | miss |

`date_checked` is 2026-09-11.
The page the venue's own `guidelines_url` names did not answer, so the date is the research note's rather than the build's.

## Verification

Nothing in this file is fully verified.

Unverified, and why:

- `length_limits`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `required_structure`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `figure_spec`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `reference_style`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `reporting_checklists`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `submission_steps`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `template`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.
- `license_of_summary_source`: not reached at build time: https://www.pnas.org/author-center/submitting-your-manuscript.

## Caveats

- pnas.org answers the harness's client with HTTP 403 behind a Cloudflare challenge, so the build cannot re-confirm the note's browser-shaped fetch and every field is unverified until it can.
- Whether a cover letter is required was not stated on the pages the note read.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
