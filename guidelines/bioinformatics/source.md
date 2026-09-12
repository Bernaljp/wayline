# Bioinformatics (Oxford University Press)

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://academic.oup.com/bioinformatics/pages/author-guidelines | 403 | miss |
| https://academic.oup.com/bioinformatics/pages/General_Instructions | 403 | miss |

`date_checked` is 2026-09-11.
The page the venue's own `guidelines_url` names did not answer, so the date is the research note's rather than the build's.

## Verification

Nothing in this file is fully verified.

Unverified, and why:

- `length_limits`: not reached at build time: https://academic.oup.com/bioinformatics/pages/author-guidelines.
- `required_structure`: not reached at build time: https://academic.oup.com/bioinformatics/pages/author-guidelines.
- `figure_spec`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `reference_style`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `reporting_checklists`: not reached at build time: https://academic.oup.com/bioinformatics/pages/author-guidelines.
- `submission_steps`: not reached at build time: https://academic.oup.com/bioinformatics/pages/author-guidelines.
- `template`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `license_of_summary_source`: not reached at build time: https://academic.oup.com/bioinformatics/pages/author-guidelines.

## Caveats

- academic.oup.com answers the harness's client with HTTP 403 behind a bot check, on the author-guidelines page and on the General Instructions page the note also read, so nothing below is re-confirmed by the build.
- The guidelines mention 'the journal template' without a no-login download link, so `template` stays unverified.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
