# Cell

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://www.cell.com/cell/information-for-authors | 403 | miss |
| https://www.cell.com/cell/authors | 403 | miss |
| https://www.cell.com/information-for-authors/figure-guidelines | 403 | miss |

`date_checked` is 2026-09-11.
The page the venue's own `guidelines_url` names did not answer, so the date is the research note's rather than the build's.

## Verification

Nothing in this file is fully verified.

Unverified, and why:

- `length_limits`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `required_structure`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `figure_spec`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `reference_style`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `reporting_checklists`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `submission_steps`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `template`: the note's value is a search-result snippet of the live page, not a fetch of it.
- `license_of_summary_source`: the note's value is a search-result snippet of the live page, not a fetch of it.

## Caveats

- cell.com answers a stateless request with HTTP 403 on every path tried, the note's included, so every field below is a search-result snippet of the live page rather than a fetch. The alternates the note's action item suggests are retried at build time and are refused the same way.
- Cell Press's site-wide figure guidelines and article templates almost certainly apply to Cell as well as to Cell Systems, but that is an inference from a sister journal's pages and is not recorded here as Cell's.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
