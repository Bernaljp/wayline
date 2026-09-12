# Nature Communications

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://www.nature.com/ncomms/submit/guide-to-authors | 200 | hit |

`date_checked` is 2026-09-12.

## Verification

Fully verified: `template`, `license_of_summary_source`.

Unverified, and why:

- `length_limits`: the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF.
- `required_structure`: the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF.
- `figure_spec`: the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF.
- `reference_style`: the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF.
- `reporting_checklists`: the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF.
- `submission_steps`: the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF.

## Reporting-checklist forms

- Reporting Summary cached as `checklist/nature-reporting-summary.pdf` (HTTP 200).

## Caveats

- The guide-to-authors page is prose and links https://www.nature.com/documents/ncomms-submission-guide.pdf, which is where every number below was read. The build fetches the page, never the PDF: nothing here reads inside a PDF, so those fields stay unverified however good the note's own reading of them was.
- The PDF's own revision stamp reads May 2019 while the page linking it is current.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
