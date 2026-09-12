# Nature

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://www.nature.com/nature/for-authors/formatting-guide | 200 | hit |

`date_checked` is 2026-09-12.

## Verification

Fully verified: `length_limits`, `required_structure`, `reference_style`, `reporting_checklists`, `template`, `license_of_summary_source`.

Unverified, and why:

- `figure_spec.color_mode`: research-notes/10-venue-guidelines-sources.md confirmed the rest of the field but not this.
- `submission_steps`: research-notes/10-venue-guidelines-sources.md could not confirm it.

## Reporting-checklist forms

- Reporting Summary cached as `checklist/nature-reporting-summary.pdf` (HTTP 200).

## Caveats

- nature.com redirects a stateless request through a cookie-consent check and answers with `?error=cookies_not_supported` on the URL; the page behind it is the real formatting guide, which is why the build treats it as reached.
- The page says 4300 words without a thousands separator, where the note wrote 4,300; the evidence string is the page's spelling.
- The submission portal is not named on the page, so `submission_steps` records only what the page states and stays unverified.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
