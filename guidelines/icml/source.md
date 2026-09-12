# ICML 2026

What this directory's `guidelines.json` was built from, and what in it cannot be believed without checking again. The fields were transcribed from `research-notes/10-venue-guidelines-sources.md` (checked 2026-09-11); the build re-fetches the pages below and looks for the wording the note read, so a field is fully verified only when its page answered and its wording is still there.

## Pages fetched

| URL | Status | Outcome |
|---|---|---|
| https://icml.cc/Conferences/2026/CallForPapers | 200 | hit |
| https://icml.cc/Conferences/2026/AuthorInstructions | 200 | hit |

`date_checked` is 2026-09-12.

## Verification

Fully verified: `length_limits`, `required_structure`, `reporting_checklists`, `submission_steps`, `license_of_summary_source`.

Unverified, and why:

- `figure_spec.color_mode`: research-notes/10-venue-guidelines-sources.md confirmed the rest of the field but not this.
- `reference_style`: research-notes/10-venue-guidelines-sources.md could not confirm it.
- `template.document_class`: research-notes/10-venue-guidelines-sources.md confirmed the rest of the field but not this.

## Caveats

- The eight-page submission limit is on the call for papers and the nine-page camera-ready limit on the author instructions, so the build fetches both.
- ICML ships a style package rather than a document class: a draft loads it with \usepackage, which is what the conformance check looks for.

Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` holds reporting-checklist forms only.
