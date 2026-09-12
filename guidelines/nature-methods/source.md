# Nature Methods

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://www.nature.com/nmeth/submission-guidelines | 200 | hit |
| https://www.nature.com/nmeth/submission-guidelines/preparing-your-submission | 200 | hit |
| https://www.nature.com/nmeth/content | 200 | hit |

`date_checked` is 2026-09-12.

## Verification

Fully verified: `length_limits`, `required_structure`, `reference_style`, `submission_steps`, `license_of_summary_source`.

Unverified, and why:

- `figure_spec.formats`: research-notes/10-venue-guidelines-sources.md confirmed the rest of the field but not this.
- `figure_spec.min_dpi`: research-notes/10-venue-guidelines-sources.md confirmed the rest of the field but not this.
- `figure_spec.color_mode`: research-notes/10-venue-guidelines-sources.md confirmed the rest of the field but not this.
- `reporting_checklists`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `template`: research-notes/10-venue-guidelines-sources.md could not confirm it.

## Reporting-checklist forms

- Reporting Summary cached as `checklist/nature-reporting-summary.pdf` (HTTP 200).

## Caveats

- The submission-guidelines page is a hub; the length and display-item numbers are on https://www.nature.com/nmeth/content and the file list on the preparing-your-submission page, so the build fetches all three.
- The Nature Portfolio Reporting Summary is standard across Nature-branded journals, but no nmeth-specific page saying so was fetched, so `reporting_checklists` stays unverified for this journal.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
