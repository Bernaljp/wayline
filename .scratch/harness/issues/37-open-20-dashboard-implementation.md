# 37 — OPEN-20 Dashboard implementation

Type: grilling
Status: resolved
Blocked by: 36 (Prototype: dashboard transport through the tunnel)
Brief: OPEN-20, Section 9.9

## Question

Standard-library HTTP server plus a vanilla single-page app with polling (default), or a web framework with websockets?

Default: standard library, no build step, polling every few seconds, server-sent events only if the prototype showed polling insufficient. Confirm, and decide whether one vendored single-file markdown renderer is allowed in `dashboard/` (default: yes, pinned and checked in, because it is a static asset, not a dependency).

## Answer

Resolved 2026-09-11 by the owner: default confirmed on research evidence, without the prototype; the tracer bullet named below re-verifies it as its first acceptance criterion.

Standard-library `ThreadingHTTPServer`, JSON endpoints, vanilla single-page app, polling with byte-offset journal reads and ETag 304s (2 s logs, 5 s elsewhere), server-sent events only if the logs view proves annoying; `zipfile` streaming for downloads; vendored marked plus DOMPurify checked in as static assets; server-side layered SVG for the DAG. M1's read-only dashboard is the first cut.
