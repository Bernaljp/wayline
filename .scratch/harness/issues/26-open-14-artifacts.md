# 26 — OPEN-14 Artifacts

Type: grilling
Status: resolved
Blocked by: None
Brief: OPEN-14, Section 9.3

## Question

Results outside git with a hash manifest (default), or git-lfs?

Default: `<project>/results/` is git-ignored; `research/manifest.json` records path, size, sha256, producing job and run id; the ledger refuses a findings entry whose provenance points at an unmanifested file. Confirm, and set the size threshold below which a result file may be committed (default: 1 MB).

## Answer

Resolved 2026-09-11 by the owner in a batch grilling round (all defaults confirmed unless stated).

`results/` lives outside git; `research/manifest.json` records path, size, sha256, producing job and run. The ledger refuses a finding whose provenance points at an unmanifested file. Files under about 1 MB may be committed; this is a soft default, and a heavier file may be committed when a ticket or the owner decides it is necessary.
