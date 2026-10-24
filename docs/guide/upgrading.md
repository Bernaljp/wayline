# Upgrading

A project pins the harness tag it runs on in its `harness.json`, and `wayline upgrade --to <tag>` moves it to another
tag, printing the changelog between them (an older tag rolls back).

## `research_version`

`harness.json`'s `research_version` says how a project keeps `research/`. Absent means 1 (projects made on v1.0.x);
`wayline init` on this release writes 2 (`RESEARCH_VERSION` in `wayline/__init__.py`). A small upgrade, within one
`research_version`, works both ways as before.

## Why a v1.0.x project is refused

This release keeps objectives, sections and passages, results, documents, and the account, none of which a v1.0.x
project has. Nothing is migrated. A project made on v1.0.x is refused:

- `wayline upgrade` to this release changes nothing and names the two ways on;
- every verb that writes to it refuses with the same message;
- reading still works (`wayline status`), and the dashboard lists it read-only, marked with its tag.

## The two ways on

1. **Keep the old tag**: `wayline upgrade --to v1.0.1` (or whichever tag it was made with). It holds every project on
   the shared checkout.
2. **Start a new project** on this release from the old one's materials: `wayline init <new path>`, then hand the new
   project the old one's materials in a setup conversation (its earlier writing as documents, its references, its
   code as the clone).

Nothing here differs between the autonomies.
