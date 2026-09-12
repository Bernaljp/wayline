# Genome Biology

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://genomebiology.biomedcentral.com/submission-guidelines | 200 | hit |
| https://link.springer.com/journal/13059/submission-guidelines/research | 200 | hit |

`date_checked` is 2026-09-12.

## Verification

Fully verified: `length_limits`, `required_structure`, `reference_style`, `reporting_checklists`, `submission_steps`.

Unverified, and why:

- `figure_spec`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `template`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `license_of_summary_source`: research-notes/10-venue-guidelines-sources.md could not confirm it.

## Caveats

- The note could not reach this venue at all: biomedcentral.com 301'd to link.springer.com, which 303'd to a Springer login endpoint, so the note marked every field unverified and left an action item to retry by another path. The retry is what this build does, and it pays: BMC's journals have moved onto Springer Nature Link and the research-article page now answers a stateless request, so the length, structure, reference and checklist fields below were read off a fetched page rather than a snippet.
- The figure specification and the template are still not stated on the pages reached.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
