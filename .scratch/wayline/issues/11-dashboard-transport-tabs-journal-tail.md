# 11 - Read-only dashboard: transport, tabs, journal tail, overview (verbatim prototype 36)

**What to build:** `wayline serve` starts a standard-library web server on localhost and prints the one SSH tunnel line; from the laptop the owner sees a tab per project, the overview, and a journal tail that updates by itself through incremental polling, with a server-sent events alternative behind a query parameter for comparison. The first criterion is the closed prototype ticket's Question, carried verbatim; the real dashboard stands in for the throwaway server and the owner's reactions through the tunnel are recorded.

**Blocked by:** 02 (init lays out a project and status reads it)

**Status:** ready-for-agent

**GitHub:** [#12](https://github.com/Bernaljp/wayline/issues/12) (mirror; the local file is the source)

**Milestone:** M1 Frontier and windows. **Spec:** milestone M1 criteria 2 and 9; Implementation Decisions 8; research-notes 08 (the server, the scan, the measurements).

- [ ] Carried verbatim from the closed prototype ticket 36 (Prototype: dashboard transport through the tunnel):

  > Which transport feels right from the laptop? Build a throwaway standard-library server with two endpoints over a fake journal that a background thread appends to every second: `/api/journal?since=<n>` polled every two seconds, and `/events` as server-sent events; one static page with project tabs and a journal tail that can switch transport with a query parameter. The owner opens it through `ssh -L` from the laptop and reacts: latency, dropped streams, CPU on the workstation, behavior when the laptop sleeps and wakes.
  >
  > The answer is the transport M1's read-only dashboard uses. Keep it under `.scratch/proto/dashboard/`.

  The real read-only dashboard stands in for the throwaway server: the journal tail polls `/api/projects/<id>/journal?since=<byte offset>` every 2 s by default and switches to the server-sent events endpoint with `?transport=sse`; the owner's reactions through `ssh -o ServerAliveInterval=30 -N -L` are recorded in `docs/verification/m1.md`, and polling stays the default unless the owner judges the logs view annoying (OPEN-20).
- [ ] `http.server.ThreadingHTTPServer` with a small path table serves `GET /api/projects` (from `projects.json`, the active one marked), `GET /api/projects/<id>/overview` (phase, autonomy, radius, goal progress, window status, slots in use, running workers and jobs, last events), and `GET /api/projects/<id>/journal?since=<offset>` returning only the appended bytes; every JSON view carries an ETag from the `os.scandir` `(st_mtime_ns, st_size)` snapshot with a 1 s memo and answers 304 to `If-None-Match`.
- [ ] The static page (`dashboard/index.html`, `app.js`, `style.css`, vendored `marked.umd.js` and `purify.min.js` pinned and checked in) renders the tabs, the overview, and the journal tail, polling 2 s for the tail and 5 s for views; `?transport=sse` switches the tail to an unchunked `Connection: close` `text/event-stream` with `id:` set to the byte offset, `retry: 2000`, and a `select()`-based dead-client check.
- [ ] `wayline serve` binds `127.0.0.1` on `harness.json.dashboard.port` (8765) and prints `ssh -L <port>:127.0.0.1:<port> <workstation>`; `--bind 0.0.0.0` requires the random URL token on every request and raises `request_queue_size` to 16; the token lives in `~/.wayline/dashboard.json` and `serve` prints the URL carrying it.
- [ ] HTTP tests over the fixture ledger cover every endpoint, the 304 path, the byte-offset tail, and the token rule.
