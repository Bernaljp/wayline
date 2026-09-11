# 08 Dashboard transport: polling versus server-sent events on the standard library

Ticket: `.scratch/harness/issues/08-dashboard-transport.md`. Brief: Section 9.9, OPEN-20.
Resolved 2026-09-11 on Python 3.12.3, Linux 6.8.0-117-generic (CONFIG_HZ=1000), ext4, curl 8, and the
Playwright-cached Chrome headless shell (chromium_headless_shell-1228). Experiment files live under
`/home/bernaljp/.claude/jobs/5a78b0a6/tmp/08/` and are reproduced inline below.

## Answer

**Transport: keep polling as the default (Section 9.9 stands), designed as incremental byte-offset reads
with `ETag` 304s.** The Logs view polls `/api/journal?since=<byte offset>` every 2 s and every other view
polls its JSON endpoint every 5 s with `If-None-Match`. Measured server cost is negligible either way: six
pollers at 2 s cost 0.10 s of CPU over 30 s (0.3% of one core); six SSE streams cost 0.05 s (0.2%); idle is
0.2%. Polling wins on the things that matter for a tunnelled single-owner dashboard: no per-tab thread that
outlives a closed tab (an SSE thread for a quiet stream lingered 30 s after the client left), no per-origin
limit of six concurrent streams in HTTP/1.1 browsers, one code path shared with every other endpoint, and
survival of laptop sleep and tunnel drops by construction (every request is fresh). SSE is nonetheless fully
feasible on the standard library and was proven end to end: a `Connection: close`, unchunked
`text/event-stream` response with `id:` set to the journal byte offset and `retry: 2000`, consumed by a real
headless Chromium, reconnected on its own after the server was killed and restarted, sending
`Last-Event-ID: 204` (server log) and reporting `opens=2 errors=1 messages=10 state=1`.

**The observation that flips it:** in ticket 36, if the owner judges the 2 s tail latency of the Logs view
too slow, or if a polling client through `ssh -L` shows request latency comparable to the poll interval
(long fat tunnel), switch only the Logs view to SSE using the recipe below (about 15 lines), keep polling
everywhere else, and add the `select()`-based dead-client check so streams die within a second. The
observation that would flip it the other way, toward even less: if the tick already rewrites a
`dashboard/state.json` snapshot, the SPA can poll that single static file and the server needs no ledger
readers at all.

**Change detection without inotify:** one `os.scandir` pass per ledger directory recording
`(st_mtime_ns, st_size)` per file, compared as a dict to the previous snapshot. Measured on ext4 in cache:
0.64 ms for 111 files (50 tickets, 20 jobs), 5.5 ms for 901 files (300 tickets, 200 jobs), 26 ms for 4001
files (1000 tickets, 1000 jobs); a content hash of the same trees costs 6, 37, and 182 ms. Do the scan on
demand inside the poll handler with a 1 s memo, not in a background thread. Two caveats with sources: the
kernel stamps inodes with the coarse clock (`current_time()` calls `ktime_get_coarse_real_ts64`), so two
writes within one jiffy (1 ms here, 4 ms on HZ=250 kernels) get the same `mtime_ns` (measured: 7591
rewrites in one second produced 906 distinct values, 1.000 ms apart), which is why size is part of the key
and why the append-only journal uses its byte length as its version. Same-size in-place rewrites inside one
jiffy are the only miss, and the ledger's atomic-rename writers do not produce them.

**Zip streaming recipe:** `zipfile.ZipFile(wrapper, "w", ZIP_DEFLATED)` where `wrapper` is a 10-line
file-like object with `write()` (emits an HTTP chunk `"%x\r\n" + data + "\r\n"` to `self.wfile`), `tell()`
(bytes written so far), and `close()` (emits `0\r\n\r\n`). Because the wrapper cannot seek, `zipfile` flags
each member with the data descriptor bit (`flag_bits & 0x08`, observed) and writes CRC and sizes after the
member data; `ZipFile.close()` appends the central directory. Send
`Transfer-Encoding: chunked`, no `Content-Length`, and keep-alive survives. Measured: a 17 MB tree of 41
files became a 3.19 MB archive in 0.112 s with 0.7 ms to first byte and server RSS flat at 23 MB;
`zipfile.testzip()` and `unzip -t` both clean. Use `z.write(path, arcname)` (it stats the file, so ZIP64
is chosen per member) and pass `force_zip64=True` only for `z.open(name, "w")` members of unknown size
over 2 GiB. Range requests: a 20-line single-range handler returning `206` with `Content-Range`, `416` with
`bytes */size` past the end, and `Accept-Ranges: bytes`; verified with curl `-r 100-199`, a suffix range,
a past-end range, and a byte-exact 1 MiB comparison.

**Markdown rendering:** vendor `marked.umd.js` (44,870 bytes, MIT, zero dependencies, version 18.0.12)
plus `DOMPurify` (`purify.min.js`, 29,369 bytes) as pinned static assets under `dashboard/static/`, and
render client-side with `DOMPurify.sanitize(marked.parse(md))`. This is compatible with the no-dependency
rule: the Brief's rule is "`<pkg>/` Python, standard library only" (BRIEF line 257) and C5 forbids calling
the owner's existing skills; a checked-in JavaScript file is served by the server, never imported by the
harness, which is also ticket 37's stated default. Sanitizing is not optional here: workers (models) write
the markdown that the dashboard renders, and the dashboard has action endpoints, so an unsanitized
`<script>` in a findings file would be a prompt-injection path into real actions. The standard library has
no markdown module (`"markdown" in sys.stdlib_module_names` is False); a server-side subset renderer is
about 150 lines and would still need escaping, so it only wins if the owner rejects any vendored file.

**DAG view:** hand-laid inline SVG from a layered layout computed server-side in Python and returned as an
SVG string. The 43-line prototype below (longest-path layering, two barycenter sweeps, grid coordinates,
straight edges with an arrow marker, one `<a>` per node with a status fill) laid out a 14-node, 18-edge
DAG into eight layers and a 4.3 KB well-formed SVG. This covers the ticket graph at the sizes Section 9
implies (tens to low hundreds of nodes). Flip to a vendored `@dagrejs/dagre` (`dist/dagre.min.js`, 48,956
bytes, MIT, 3.1.1, depends on `@dagrejs/graphlib`; confirm the dist bundle carries it before vendoring)
only if the graph passes a few hundred nodes or the owner needs edge routing around nodes.

## 1. Server-sent events on `ThreadingHTTPServer`

### What the standard library gives you

- `ThreadingHTTPServer` "is identical to HTTPServer but uses threads to handle requests by using the
  ThreadingMixIn. This is useful to handle web browsers pre-opening sockets, on which HTTPServer would
  wait indefinitely." (https://docs.python.org/3.12/library/http.server.html#http.server.ThreadingHTTPServer)
- `ThreadingMixIn` "processes each request in a separate thread"; `daemon_threads` defaults to False,
  "meaning that Python will not exit until all threads created by ThreadingMixIn have exited";
  `server_close` "waits until all non-daemon threads complete, except if block_on_close attribute is False"
  (https://docs.python.org/3.12/library/socketserver.html#socketserver.ThreadingMixIn). Set
  `srv.daemon_threads = True` so open streams never block `shutdown`.
- Keep-alive requires `protocol_version = "HTTP/1.1"`: "the server will permit HTTP persistent
  connections; however, your server must then include an accurate Content-Length header (using
  send_header()) in all of its responses to clients. For backwards compatibility, the setting defaults to
  'HTTP/1.0'." (https://docs.python.org/3.12/library/http.server.html#http.server.BaseHTTPRequestHandler.protocol_version).
  `handle()` loops `while not self.close_connection: self.handle_one_request()`
  (`/usr/lib/python3.12/http/server.py` lines 432-438). Measured: two GETs on one curl invocation showed
  `1 connects` then `0 connects` for the second request.
- Writes are unbuffered: `StreamRequestHandler.wbufsize = 0` selects `_SocketWriter`, whose `write()` is
  `self._sock.sendall(b)` ("Does not hold data in a buffer, avoiding any need to call flush()",
  `/usr/lib/python3.12/socketserver.py` lines 794-841). So each `wfile.write` of an event leaves the
  process immediately; nothing in the stack chunks or buffers a stream. `disable_nagle_algorithm` is
  available (default False) if millisecond delivery ever matters.
- No `Range` support and no `do_HEAD` unless you write them: the docs list `If-Modified-Since` and
  `Last-Modified` for `SimpleHTTPRequestHandler` only
  (https://docs.python.org/3.12/library/http.server.html#http.server.SimpleHTTPRequestHandler.do_GET) and
  never mention `Range`; a `HEAD` to my handler returned `501 Unsupported method ('HEAD')`.
- The docs warn: "http.server is not recommended for production. It only implements basic security
  checks." That is consistent with OPEN-21's localhost bind plus tunnel.

### Chunked or not

The WHATWG spec: "Authors are also cautioned that HTTP chunking can have unexpected negative effects on the
reliability of this protocol, in particular if the chunking is done by a different layer unaware of the
timing requirements. If this is a problem, chunking can be disabled for serving event streams."
(https://html.spec.whatwg.org/multipage/server-sent-events.html#authoring-notes). The clean choice on the
standard library is no chunking at all: send `Connection: close` and write raw event text. RFC 9112 section
6.3 makes that a valid body: "this is a response message without a declared message body length, so the
message body length is determined by the number of octets received prior to the server closing the
connection" (https://www.rfc-editor.org/rfc/rfc9112.html#name-message-body-length). Chromium accepted
exactly this response (see the browser test).

### Reconnection, `Last-Event-ID`, keep-alive comments, connection limit

- Reconnect: the user agent waits "a delay equal to the reconnection time of the event source", which
  "must initially be an implementation-defined value, probably in the region of a few seconds"; a `retry:`
  field "consisting of only ASCII digits" sets it in milliseconds; on reconnect, "If the EventSource
  object's last event ID string is not the empty string ... Set (Last-Event-ID, lastEventIDValue) in
  request's header list." It stops only on failure: "Once the user agent has failed the connection, it does
  not attempt to reconnect", and failure means an HTTP 204, a non-200 status, or a wrong content type.
  (https://html.spec.whatwg.org/multipage/server-sent-events.html#processing-model)
- Proxies: "Legacy proxy servers are known to, in certain cases, drop HTTP connections after a short
  timeout. To protect against such proxy servers, authors can include a comment line (one starting with a
  ':' character) every 15 seconds or so." (same URL, authoring notes). The prototype sends `: ping` every
  15 s.
- Connection limit: "Clients that support HTTP's per-server connection limitation might run into trouble
  when opening multiple pages from a site if each page has an EventSource to the same domain." (spec);
  MDN: "When not used over HTTP/2, SSE suffers from a limitation to the maximum number of open connections
  ... set to a very low number (6) ... marked as 'Won't fix' in Chrome and Firefox"
  (https://developer.mozilla.org/en-US/docs/Web/API/EventSource). `http.server` is HTTP/1.1 only, so six
  tabs with a stream each exhaust the origin and the seventh tab's polling requests queue behind them.

### Through `ssh -L`

Documentation only; keyless ssh to this host was unavailable (`ssh -o BatchMode=yes 127.0.0.1 true` was
refused), so ticket 36 remains the live test.

- `-L`: "Specifies that connections to the given TCP port or Unix socket on the local (client) host are to
  be forwarded to the given host and port ... Whenever a connection is made to the local port or socket,
  the connection is forwarded over the secure channel, and a connection is made to either host port
  hostport ... from the remote machine." (https://man.openbsd.org/ssh.1#L). ssh forwards a byte stream per
  TCP connection and knows nothing about HTTP, so it neither chunks nor waits for a response to complete;
  a long-lived stream is one channel held open.
- Idle: `ServerAliveInterval` "The default is 0, indicating that these messages will not be sent to the
  server"; `ServerAliveCountMax` default 3; `TCPKeepAlive` default yes
  (https://man.openbsd.org/ssh_config.5). Nothing in ssh times out an idle channel. What kills streams is
  the laptop sleeping: the TCP session dies, the browser's `EventSource` sees an error and reconnects every
  `retry` ms, and each attempt hits the local forwarded port, which ssh still holds even when its
  transport is dead, so attempts fail until the tunnel is re-established. Polling behaves identically per
  request. Recommend `ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -N -L ...` in the docs so
  a dead tunnel exits within 90 s instead of hanging (`-N`: "Do not execute a remote command. This is
  useful for just forwarding ports.").
- The 15 s comment line doubles as tunnel traffic; with polling, every request is traffic.

### Threads, CPU, and zombie streams (measured)

`load.sh` counts the server's `utime+stime` from `/proc/PID/stat` over a window while N curl clients run
against it; thread count is read from `/proc/PID/status` mid-window.

| mode | clients | window | server CPU | share of one core | threads mid-window |
|---|---|---|---|---|---|
| idle (appender thread only) | 0 | 10 s | 0.02 s | 0.2% | 2 |
| SSE | 6 | 30 s | 0.05 s | 0.2% | 8 |
| poll `?since=` every 2 s | 6 | 30 s | 0.10 s | 0.3% | 2 |
| poll with `If-None-Match` every 2 s | 6 | 30 s | 0.08 s | 0.3% | 2 |
| SSE | 24 | 20 s | 0.16 s | 0.8% | 26 |

Thread count is 2 at rest plus exactly one per open stream. After clients disconnect, a stream thread dies
only when its next write fails: an active stream (journal line every second) was gone 1.5 s later
(`BrokenPipeError`); a quiet stream (nothing to send) survived the first 15 s `: ping` (the first write
after the peer closes succeeds into the kernel buffer) and was gone by 32 s (`ConnectionResetError`). Six
tabs opened and closed a few times can therefore hold a dozen threads for half a minute. If SSE is ever
adopted, add `select.select([self.connection], [], [], 0.5)` in the loop: readability on a stream the
client never writes to means EOF, and the thread can exit at once (not tested here).

### Latency and resume (measured with curl)

Events arrived once per second in step with the appender (timestamps 47.988, 48.989, 49.989 for
consecutive lines). With `id:` equal to the byte offset after each line, `Last-Event-ID: 170` resumed with
`id: 204` and the next full line. An earlier version of the prototype emitted the chunk-end offset for
every line of a multi-line chunk, which made resume from a mid-chunk id split a line; the fix (per-line
offsets, `32 66 100 134 168` on the first chunk) is in the code below. This id scheme means the server
keeps no per-client state at all.

### Real-browser reconnect (Chrome headless shell)

`/page` serves a page that opens `new EventSource('/events?since=0')` and writes counters into the DOM;
an `<img>` pointing at a second server that sleeps 14 s holds the page's load event open so
`--dump-dom` serializes after the test window. At t=4 s the server was `kill -9`'d and restarted 0.5 s
later with an empty journal.

```
chrome-headless-shell --headless --no-sandbox --disable-gpu --dump-dom http://127.0.0.1:8765/page
-> opens=2 errors=1 messages=10 lastId=338 state=1          (dump after 14.2 s)
server events.log:  connect Last-Event-ID=None
                    connect Last-Event-ID=204
```

One `onerror`, one automatic reopen within the 2 s `retry`, the header carried the last id, and the stream
was OPEN at the end. This is the behavior Section 9.9 would rely on if SSE were adopted.

## 2. Detecting ledger changes without inotify

- `os.scandir`: "Using scandir() instead of listdir() can significantly increase the performance of code
  that also needs file type or file attribute information, because os.DirEntry objects expose this
  information if the operating system provides it when scanning a directory"; `DirEntry.is_dir()` needs no
  system call in most cases, `DirEntry.stat()` "on Unix ... requires a system call" and caches its result
  (https://docs.python.org/3.12/library/os.html#os.scandir). `st_mtime_ns`: "The time of last modification
  of path in nanoseconds since the epoch, as an integer. The exact meaning and resolution depend on the
  operating system and filesystem." (https://docs.python.org/3.12/library/os.html#os.stat_result.st_mtime_ns)
- Resolution on Linux: `fs/inode.c` v6.8, `current_time()` is `ktime_get_coarse_real_ts64(&now); return
  timestamp_truncate(now, inode);`
  (https://raw.githubusercontent.com/torvalds/linux/v6.8/fs/inode.c, lines 2492-2497). Kernel docs:
  "Historically, the kernel has always used coarse time values to stamp inodes. This value is updated every
  jiffy, so any change that happens within that jiffy will end up with the same timestamp."
  (https://docs.kernel.org/filesystems/multigrain-ts.html; multigrain timestamps are opt-in per
  filesystem and not in 6.8). Measured here: 1.000 ms steps (CONFIG_HZ=1000 from
  `/boot/config-6.8.0-117-generic`).
- Cost (`scan.py`, median of 20 scans, `(mtime_ns, size)` per file, journal stat plus `tickets/` plus
  `jobs/*/`):

| tickets | jobs (3 files each) | journal | files | scan median | scan max | content hash |
|---|---|---|---|---|---|---|
| 50 | 20 | 1 MB | 111 | 0.64 ms | 0.68 ms | 6 ms |
| 300 | 200 | 10 MB | 901 | 5.50 ms | 5.57 ms | 37 ms |
| 1000 | 1000 | 50 MB | 4001 | 25.7 ms | 26.3 ms | 182 ms |

The journal itself needs no scan: it is append-only, so `st_size` is its version and the poll's `since`
offset is the cursor; the `ETag` `"mtime_ns:size"` gives 304s for free (measured: same tag -> `304 0B`,
one second later after an append -> `200`). RFC 9110 defines `ETag`/`If-None-Match` -> 304 (sections 8.8.3,
13.1.2, 15.4.5) and notes `Last-Modified`/`If-Modified-Since` have one-second granularity (sections 8.8.2,
13.1.3; https://www.rfc-editor.org/rfc/rfc9110.html), another reason to prefer `ETag` over
`If-Modified-Since` for files that change many times a second.

## 3. Streaming a zip and serving ranges

- Docs: "Changed in version 3.5: Added support for writing to unseekable streams"
  (https://docs.python.org/3.12/library/zipfile.html#zipfile.ZipFile); `force_zip64`: "When writing a
  file, if the file size is not known in advance but may exceed 2 GiB, pass force_zip64=True"
  (https://docs.python.org/3.12/library/zipfile.html#zipfile.ZipFile.open); ZIP64 is on by default
  (`allowZip64=True`, "Changed in version 3.4").
- Source path for an unseekable target (`/usr/lib/python3.12/zipfile/__init__.py`): the constructor
  tries `fp.tell()` and wraps the object in `_Tellable` if that fails, then tries `fp.seek(start_dir)`
  and sets `_seekable = False` on failure (lines 1366-1381); `_open_to_write` sets
  `flag_bits |= _MASK_USE_DATA_DESCRIPTOR` when not seekable (line 1704) and `_ZipWriteFile.close`
  writes `struct.pack('<LLLL'|'<LLQQ', _DD_SIGNATURE, CRC, compress_size, file_size)` after the data
  (lines 1258-1263); `close()` writes the end records (lines 1955-1975). Nothing is buffered beyond the
  compressor's output for one write call. My wrapper provides its own `tell()`, so `_Tellable` is not
  even needed, but the seek probe still fails and the descriptor path is used (observed
  `flag_bits 0x8`, `compress 8`).
- Chunked framing per RFC 9112 section 7.1: `chunk = chunk-size [chunk-ext] CRLF chunk-data CRLF;
  last-chunk = 1*("0") [chunk-ext] CRLF` (https://www.rfc-editor.org/rfc/rfc9112.html#name-chunked-transfer-coding).
- Measured: `curl -o tree.zip http://127.0.0.1:8765/zip` -> `200 3187095B ttfb=0.000683s total=0.111897s`;
  `VmRSS` 22936 kB before, 23060 kB after; `zipfile.testzip() -> None`, 41 entries; `unzip -tq`: "No
  errors detected in compressed data".
- Range (RFC 9110 sections 14.2 to 14.4, 15.3.7, 15.5.17): `curl -r 100-199` -> `206 Partial Content`,
  `Content-Range: bytes 100-199/67108864`, `Content-Length: 100`; `Range: bytes=-1024` -> `206 1024B`;
  `Range: bytes=99999999999-` -> `416`; a 1 MiB mid-file range compared byte-equal with the source. Send
  files in 64 KiB reads, never `f.read()` whole.

## 4. Markdown

- No stdlib module: `python3 -c "import sys; print('markdown' in sys.stdlib_module_names)"` -> False.
- marked: MIT, "Marked does not sanitize the output HTML. Please use a sanitize library, like DOMPurify"
  (https://github.com/markedjs/marked); package.json on the CDN: version 18.0.12, license MIT,
  dependencies empty, browser field `./lib/marked.umd.js`
  (https://cdn.jsdelivr.net/npm/marked/package.json). Shipped size: `curl -sL
  https://cdn.jsdelivr.net/npm/marked@18.0.12/lib/marked.umd.js | wc -c` -> 44870. DOMPurify:
  `https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js` -> 29369 bytes.
- Rule check: BRIEF line 257 scopes "standard library only" to `<pkg>/` (Python); Section 9.9 says "No
  framework, no build step"; ticket 37's default is "yes, pinned and checked in, because it is a static
  asset, not a dependency". A vendored file satisfies all three; record the version and SHA-256 next to the
  file.

## 5. DAG view

`dag.py` (43 lines, below) is the whole layout: layering by longest path from sources, two barycenter
sweeps (down by parents, up by children), fixed grid coordinates centered per layer, straight edges with
an SVG arrow marker, `<a href="/ticket/<id>">` around each node, fill by status. Output for the 14-node
test: layers `{0: 1, 106: 2, 212: 3, 318: 3, 424: 1, 530: 1, 636: 2, 742: 1}`, canvas 480 x 848, 4258
bytes, parsed by `xml.etree` with 14 `rect` and 18 `line` elements. Frontier highlighting is a fill color;
the page per ticket is the link target. dagre for comparison: `@dagrejs/dagre` 3.1.1, MIT, depends on
`@dagrejs/graphlib` 4.0.5, `dist/dagre.min.js` 48,956 bytes (https://github.com/dagrejs/dagre,
https://cdn.jsdelivr.net/npm/@dagrejs/dagre/package.json).

## Experiment code

### `server.py` (76 lines, final version)

```python
# Throwaway transport probe: polling with ETag, SSE fed by a file-appending thread,
# chunked zip streaming through a file-like wrapper, and Range on a large file.
import json, os, sys, threading, time, zipfile, hashlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
D = os.path.dirname(os.path.abspath(__file__)); JOURNAL = os.path.join(D, "journal.jsonl")
TREE = os.path.join(D, "tree"); BIG = os.path.join(D, "big.bin")

def appender():                       # the "conductor": one journal line per second
    n = 0
    while True:
        with open(JOURNAL, "a") as f: f.write(json.dumps({"n": n, "t": time.time()}) + "\n")
        n += 1; time.sleep(1)

class Chunked:                        # file-like over wfile: HTTP/1.1 chunked body
    def __init__(self, w): self.w, self.pos = w, 0
    def write(self, b):
        if b: self.w.write(b"%x\r\n" % len(b) + bytes(b) + b"\r\n"); self.pos += len(b)
        return len(b)
    def tell(self): return self.pos
    def flush(self): self.w.flush()
    def close(self): self.w.write(b"0\r\n\r\n")

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def head(self, code, ctype, **hdr):
        self.send_response(code); self.send_header("Content-Type", ctype)
        for k, v in hdr.items(): self.send_header(k.replace("_", "-"), v)
        self.end_headers()
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/journal":                       # short polling, ETag = mtime_ns:size
            st = os.stat(JOURNAL); tag = '"%d:%d"' % (st.st_mtime_ns, st.st_size)
            if self.headers.get("If-None-Match") == tag: return self.head(304, "text/plain", Content_Length="0")
            since = int(q.get("since", ["0"])[0])
            with open(JOURNAL, "rb") as f: f.seek(since); body = f.read()
            self.head(200, "application/json", ETag=tag, Content_Length=str(len(body) + 32))
            self.wfile.write(json.dumps({"next": since + len(body), "b64": len(body)}).encode().ljust(32) + body)
        elif u.path == "/events":                          # SSE: tail the journal by size, no chunking layer
            self.head(200, "text/event-stream", Cache_Control="no-cache", Connection="close")
            pos = int(self.headers.get("Last-Event-ID", q.get("since", ["0"])[0]))
            open(os.path.join(D, "events.log"), "a").write("connect Last-Event-ID=%s\n" % self.headers.get("Last-Event-ID"))
            self.wfile.write(b"retry: 2000\n\n"); last_ping = time.time()
            while True:
                if os.stat(JOURNAL).st_size > pos:
                    with open(JOURNAL, "rb") as f: f.seek(pos); chunk = f.read(); pos += len(chunk)
                    off = pos - len(chunk)
                    for line in chunk.splitlines(keepends=True):
                        off += len(line); self.wfile.write(b"id: %d\ndata: %s\n\n" % (off, line.rstrip(b"\n")))
                elif time.time() - last_ping > 15: self.wfile.write(b": ping\n\n"); last_ping = time.time()
                time.sleep(0.5)
        elif u.path == "/zip":                             # stream a directory, never buffered whole
            self.head(200, "application/zip", Transfer_Encoding="chunked", Content_Disposition='attachment; filename="tree.zip"')
            out = Chunked(self.wfile)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(TREE):
                    for fn in files: p = os.path.join(root, fn); z.write(p, os.path.relpath(p, TREE))
            out.close()
        elif u.path == "/big":                             # single byte range, 206 / 416
            size = os.path.getsize(BIG); rng = self.headers.get("Range")
            start, end = 0, size - 1
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-"); start = int(a) if a else size - int(b); end = int(b) if a and b else end
                if start >= size: return self.head(416, "text/plain", Content_Range="bytes */%d" % size, Content_Length="0")
            n = end - start + 1
            self.head(206 if rng else 200, "application/octet-stream", Accept_Ranges="bytes", Content_Length=str(n),
                      **({"Content_Range": "bytes %d-%d/%d" % (start, end, size)} if rng else {}))
            with open(BIG, "rb") as f:
                f.seek(start)
                while n > 0: buf = f.read(min(n, 1 << 16)); self.wfile.write(buf); n -= len(buf)
        elif u.path == "/page":                            # browser probe: EventSource state written into the DOM
            body = (b"<pre id=o></pre><img src=http://127.0.0.1:8766/hold><script>const o=document.getElementById('o');let n=0,e=0,op=0,last='';"
                    b"const s=new EventSource('/events?since=0');s.onopen=()=>{op++;r()};s.onerror=()=>{e++;r()};"
                    b"s.onmessage=m=>{n++;last=m.lastEventId;r()};function r(){o.textContent=`opens=${op} errors=${e} messages=${n} lastId=${last} state=${s.readyState}`}</script>")
            self.head(200, "text/html", Content_Length=str(len(body))); self.wfile.write(body)
        else: self.head(404, "text/plain", Content_Length="0")

if __name__ == "__main__":
    open(JOURNAL, "w").close(); threading.Thread(target=appender, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H); srv.daemon_threads = True
    print("pid", os.getpid(), "threads-baseline", threading.active_count(), flush=True); srv.serve_forever()
```

Fixtures: `tree/` is 40 text files of 20,000 lines plus a 3 MiB random `noise.bin` (17 MB); `big.bin` is
64 MiB of `os.urandom`. `hold.py` is a five-line `HTTPServer` on 8766 that sleeps 14 s before answering
404, used only to hold the browser's load event.

### Commands

```
curl -s -o /dev/null -w "poll %{http_code} %{size_download}B %{time_total}s\n" "http://127.0.0.1:8765/api/journal?since=0"
T=$(curl -s -D - -o /dev/null "$U/api/journal?since=0" | tr -d '\r' | awk -F': ' '/^ETag/{print $2}')
curl -s -o /dev/null -w "%{http_code}\n" -H "If-None-Match: $T" "$U/api/journal?since=0"        # 304
curl -sN --max-time 4 "$U/events?since=0"                                                        # one event per second
curl -sN --max-time 1.2 -H "Last-Event-ID: 170" "$U/events"                                       # resumes at id 204
curl -s -o /dev/null -o /dev/null -w "%{num_connects}\n" "$U/api/journal?since=0" "$U/api/journal?since=0"   # 1 then 0
curl -s -o tree.zip -w "zip: %{http_code} %{size_download}B ttfb=%{time_starttransfer}s total=%{time_total}s\n" "$U/zip"
curl -s -D - -o /dev/null -r 100-199 "$U/big" | grep -E "HTTP/|Content-Range|Content-Length|Accept-Ranges"
curl -s -o /dev/null -w "%{http_code}\n" -H "Range: bytes=99999999999-" "$U/big"                   # 416
```

### `load.sh`

```bash
#!/bin/bash
# server CPU (utime+stime from /proc/PID/stat) over WINDOW seconds with N clients of one kind
U=http://127.0.0.1:8765; PID=$1; MODE=$2; N=$3; WINDOW=$4; CLK=$(getconf CLK_TCK)
cpu() { awk '{print $14+$15}' /proc/$PID/stat; }
c0=$(cpu); t0=$(date +%s.%N)
if [ $MODE = sse ]; then for i in $(seq $N); do curl -sN --max-time $WINDOW "$U/events?since=0" > /dev/null & done
elif [ $MODE = poll ]; then for i in $(seq $N); do ( end=$((SECONDS+WINDOW)); while [ $SECONDS -lt $end ]; do curl -s "$U/api/journal?since=999999999" > /dev/null; sleep 2; done ) & done
elif [ $MODE = poll304 ]; then for i in $(seq $N); do ( end=$((SECONDS+WINDOW)); tag=; while [ $SECONDS -lt $end ]; do tag=$(curl -s -D - -o /dev/null -H "If-None-Match: $tag" "$U/api/journal?since=0" | tr -d '\r' | awk -F': ' '/^ETag/{print $2}'); sleep 2; done ) & done
fi
sleep $((WINDOW/2)); TH=$(awk '/^Threads/{print $2}' /proc/$PID/status); wait
c1=$(cpu); t1=$(date +%s.%N)
awk -v c0=$c0 -v c1=$c1 -v t0=$t0 -v t1=$t1 -v clk=$CLK -v m=$MODE -v n=$N -v th=$TH 'BEGIN{s=(c1-c0)/clk; printf "%-8s clients=%2d window=%.0fs server-cpu=%.2fs (%.1f%% of one core) threads-mid-window=%d\n", m, n, t1-t0, s, 100*s/(t1-t0), th}'
```

Run as `./load.sh $PID idle 0 20; ./load.sh $PID sse 6 30; ./load.sh $PID poll 6 30; ./load.sh $PID
poll304 6 30; ./load.sh $PID sse 24 20`.

### `scan.py`

```python
# Cost of an mtime/size scan over ledger-shaped directories, without inotify.
import os, time, statistics as S
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan")
def make(n_tickets, n_jobs, journal_mb):
    os.makedirs(f"{R}/tickets", exist_ok=True); os.makedirs(f"{R}/jobs", exist_ok=True)
    for i in range(n_tickets): open(f"{R}/tickets/t{i:04d}.md", "w").write("x")
    for i in range(n_jobs):
        os.makedirs(f"{R}/jobs/j{i:04d}", exist_ok=True)
        for fn in ("meta.json", "stdout.log", "stderr.log"): open(f"{R}/jobs/j{i:04d}/{fn}", "w").write("x")
    with open(f"{R}/journal.jsonl", "wb") as f: f.write(b"{}" * (journal_mb * 512 * 1024))
def snapshot():                       # one number per file: (mtime_ns, size); no content read
    s = os.stat(f"{R}/journal.jsonl"); out = {"journal": (s.st_mtime_ns, s.st_size)}
    with os.scandir(f"{R}/tickets") as it:
        for e in it: st = e.stat(); out[e.path] = (st.st_mtime_ns, st.st_size)
    with os.scandir(f"{R}/jobs") as it:
        for d in it:
            if d.is_dir():                # d_type: no syscall
                with os.scandir(d.path) as jt:
                    for e in jt: st = e.stat(); out[e.path] = (st.st_mtime_ns, st.st_size)
    return out
def digest():                         # a hash-based alternative: read every file; expected to be far costlier
    import hashlib; h = hashlib.blake2b()
    for root, _, files in os.walk(R):
        for fn in files: h.update(open(os.path.join(root, fn), "rb").read())
    return h.hexdigest()
for nt, nj, mb in [(50, 20, 1), (300, 200, 10), (1000, 1000, 50)]:
    import shutil; shutil.rmtree(R, ignore_errors=True); make(nt, nj, mb)
    n = len(snapshot())
    t = [];  [t.append(time.perf_counter()) or snapshot() or t.append(time.perf_counter()) for _ in range(20)]
    ms = [(t[i+1]-t[i])*1e3 for i in range(0, len(t), 2)]
    t2 = time.perf_counter(); digest(); d = (time.perf_counter()-t2)*1e3
    a = snapshot(); b = snapshot(); print(f"tickets={nt} jobs={nj} journal={mb}MB files={n}: scan median {S.median(ms):.2f} ms (max {max(ms):.2f}), equal-snapshot-compare {a==b}, content-hash {d:.0f} ms")
```

mtime granularity probe: rewrite one file in a loop for one second and count distinct `st_mtime_ns`
values (`7591 rewrites in 1 s -> 906 distinct mtime_ns values; min step 1.000 ms, median step 1.000 ms`).

### `dag.py`

```python
# Layered DAG layout for inline SVG in a few dozen lines: longest-path layering,
# barycenter ordering (two sweeps), fixed grid coordinates, straight edges.
def layout(nodes, edges, w=120, h=36, gx=40, gy=70):
    parents = {n: [] for n in nodes}; kids = {n: [] for n in nodes}
    for a, b in edges: kids[a].append(b); parents[b].append(a)
    layer = {}
    def L(n):                                    # longest path from any source
        if n not in layer: layer[n] = 1 + max((L(p) for p in parents[n]), default=-1)
        return layer[n]
    for n in nodes: L(n)
    rows = {}
    for n in nodes: rows.setdefault(layer[n], []).append(n)
    order = {n: i for r in rows.values() for i, n in enumerate(r)}
    for _ in range(2):                            # barycenter sweeps down then up
        for r in sorted(rows):
            key = lambda n: (sum(order[p] for p in parents[n]) / len(parents[n])) if parents[n] else order[n]
            rows[r].sort(key=key); order.update({n: i for i, n in enumerate(rows[r])})
        for r in sorted(rows, reverse=True):
            key = lambda n: (sum(order[k] for k in kids[n]) / len(kids[n])) if kids[n] else order[n]
            rows[r].sort(key=key); order.update({n: i for i, n in enumerate(rows[r])})
    width = max(len(r) for r in rows.values())
    pos = {}
    for r, ns in rows.items():
        x0 = (width - len(ns)) * (w + gx) / 2
        for i, n in enumerate(ns): pos[n] = (x0 + i * (w + gx), r * (h + gy))
    return pos, (width * (w + gx), (len(rows)) * (h + gy))
def svg(nodes, edges, status, color={"done": "#9be49b", "running": "#ffd966", "open": "#ddd", "frontier": "#8ecae6"}):
    pos, (W, H) = layout(nodes, edges); w, h = 120, 36; out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    out.append('<defs><marker id="a" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z"/></marker></defs>')
    for a, b in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]; out.append(f'<line x1="{x1+w/2}" y1="{y1+h}" x2="{x2+w/2}" y2="{y2}" stroke="#666" marker-end="url(#a)"/>')
    for n in nodes:
        x, y = pos[n]; out.append(f'<a href="/ticket/{n}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{color[status[n]]}" stroke="#333"/>'
                                  f'<text x="{x+w/2}" y="{y+h/2+5}" text-anchor="middle" font-size="12">{n}</text></a>')
    return "\n".join(out) + "\n</svg>"
```

Long edges that skip layers are drawn straight through intermediate layers; if that becomes unreadable,
insert dummy nodes per skipped layer before the barycenter sweeps (about ten more lines), which is the
standard Sugiyama refinement.

## Loose ends

- Tunnel behavior (buffering, sleep and wake) is documented, not measured; ticket 36 is the live test and
  should run with `ssh -o ServerAliveInterval=30 -N -L`.
- Nagle: `disable_nagle_algorithm` was left at its default; SSE delivery matched the 1 s appender cadence
  with no visible lag at that rate, so it was not needed.
- `request_queue_size` defaults to 5 (socketserver docs); with six tabs polling this never queued, but a
  wider bind under OPEN-21 should raise it to 16.
