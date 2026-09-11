# 08 — Dashboard transport: polling versus server-sent events on the standard library

Type: research
Status: resolved
Blocked by: None
Brief: Section 9.9, OPEN-20; fog: polling versus server-sent events

## Question

With Python 3.12's `http.server.ThreadingHTTPServer` and no third-party dependency:

1. Server-sent events feasibility: chunked responses, keep-alive, one thread per open stream, thread count with a few tabs open, behavior through `ssh -L` (buffering, idle timeouts), `EventSource` reconnect; versus short polling of JSON endpoints with `ETag` or `If-Modified-Since`.
2. Detecting ledger changes without inotify in the standard library: mtime scans of `journal.jsonl`, `jobs/`, `tickets/` at the expected file counts, and their cost.
3. Streaming a zipped directory on the fly with `zipfile` over the socket without buffering the archive; range requests for large artifacts.
4. Rendering markdown client-side without a build step (is one vendored single-file library acceptable under the no-dependency rule?) versus server-side conversion in the standard library.
5. A graph view of the ticket DAG without dependencies: hand-laid inline SVG (layered layout in a few dozen lines) versus a vendored library.

Deliverable: `research-notes/08-dashboard-transport.md` with a recommendation and the observation that would flip it.

## Answer

Keep polling as the default (Section 9.9 stands): the Logs view polls `/api/journal?since=<byte offset>` every 2 s, other views poll JSON with `If-None-Match` every 5 s. Measured on the standard library: six pollers cost 0.3% of one core, six SSE streams 0.2%, so cost does not decide it; polling wins because it adds no thread per open tab (SSE threads for closed tabs lingered up to 30 s), avoids the six-connections-per-origin limit of HTTP/1.1 browsers, and survives laptop sleep and tunnel drops by construction.
SSE is proven feasible if wanted: an unchunked `Connection: close` `text/event-stream` with `id:` = journal byte offset and `retry: 2000`, consumed by a real headless Chromium, reconnected on its own after a server kill and restart and sent `Last-Event-ID`. Flip only the Logs view to SSE if ticket 36 shows the 2 s tail latency or the polling traffic through `ssh -L` is annoying.
Change detection: one `os.scandir` snapshot of `(st_mtime_ns, st_size)` per file, 0.6 ms at 111 files, 5.5 ms at 901, 26 ms at 4001; run it inside the poll handler with a 1 s memo. Linux stamps inodes with the coarse clock (one jiffy, 1 ms here), so size is part of the key and the append-only journal uses its byte length as its version.
Zip streaming: `zipfile.ZipFile(wrapper, "w", ZIP_DEFLATED)` over a 10-line chunked-encoding wrapper with `write` and `tell`; zipfile uses data descriptors on the unseekable target. 17 MB tree streamed with 0.7 ms to first byte and flat RSS. Single-range `206`/`416` handler is 20 lines.
Markdown: vendor `marked.umd.js` (45 KB, MIT, no deps) plus DOMPurify (29 KB) as pinned static assets; sanitize because workers write the markdown and the dashboard has actions. No stdlib markdown module exists.
DAG: server-side layered layout (longest path plus barycenter sweeps, 43 lines) emitting inline SVG with status fills and one link per node; vendor dagre only past a few hundred nodes.
Full note with sources, tables, and code: `research-notes/08-dashboard-transport.md`.
