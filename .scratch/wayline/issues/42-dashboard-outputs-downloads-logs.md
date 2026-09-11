# 42 - Dashboard outputs, downloads, and logs

**What to build:** From the laptop the owner browses every output of a project (results, findings, figures, dossiers, the report, the paper, the docs site), downloads any file, gets a directory as a zip streamed on the fly, reads markdown and images inline, and watches worker, job, and tick logs live.

**Blocked by:** 12 (Dashboard graph, ticket pages, and logs endpoints)

**Status:** ready-for-agent

**Milestone:** M5 Overnight and report. **Spec:** Implementation Decisions 8 (endpoints, views); research-notes 08 Section 3 and 4.

- [ ] `GET /api/projects/<id>/outputs` indexes `results/` (through the manifest), findings, figures, dossiers, `REPORT.md`, `paper/`, and the docs site with sizes and hashes.
- [ ] `GET /download/<path>` serves single files with `Accept-Ranges: bytes`, single-range 206 and 416 past the end; a directory streams as a zip through a chunked-encoding wrapper with `write` and `tell`, `ZIP_DEFLATED`, data descriptors, and flat memory; `zipfile.testzip` and `unzip -t` are clean on a 17 MB fixture tree; large artifacts stream without buffering.
- [ ] Markdown renders inline through `DOMPurify.sanitize(marked.parse(md))` and images inline; the logs view tails worker streams, job logs, and the tick log with 2 s polling.
- [ ] HTTP tests cover the index, ranges, the zip, and the log tails over the fixture ledger; the live tunnel test from another machine is part of ticket 43.
