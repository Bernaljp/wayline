# Cell Systems

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://www.cell.com/cell-systems/information-for-authors | 403 | miss |
| https://www.cell.com/information-for-authors/figure-guidelines | 403 | miss |

`date_checked` is 2026-09-11.
The page the venue's own `guidelines_url` names did not answer, so the date is the research note's rather than the build's.

## Verification

Nothing in this file is fully verified.

Unverified, and why:

- `length_limits`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `required_structure`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `figure_spec`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `reference_style`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `reporting_checklists`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `submission_steps`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `template`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.
- `license_of_summary_source`: not reached at build time: https://www.cell.com/cell-systems/information-for-authors.

## Caveats

- The note reached these pages through a browser-shaped fallback after a Cloudflare challenge; the harness's own client is refused with HTTP 403, so the build cannot re-confirm any of it and every field is unverified for as long as that holds.
- The figure and template facts are from the site-wide Cell Press pages, which apply to every Cell Press journal.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
